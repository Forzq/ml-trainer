"""Training session transitions, answer evaluation and follow-up discussion."""
import json
import uuid
from contextlib import contextmanager
from threading import Lock

import httpx
from app.training.errors import TrainingError
from app.questions.catalog import TOPICS
from app.questions.selection import select_questions
from app.integrations.openrouter import log_model_failure


class TrainingService:
    def __init__(self, store, reader, settings, *, evaluate, discuss):
        self.store = store
        self.reader = reader
        self.settings = settings
        self._operations_lock = Lock()
        self._active_sessions = set()
        self.evaluate = evaluate
        self.discuss = discuss

    @contextmanager
    def _reserve_session(self, session_id, owner):
        key = (owner, session_id)
        with self._operations_lock:
            if key in self._active_sessions:
                raise TrainingError(409, "В этой тренировке уже выполняется запрос. Попробуй после его завершения.")
            self._active_sessions.add(key)
        try:
            yield
        finally:
            with self._operations_lock:
                self._active_sessions.remove(key)

    def new_session(self, body, *, owner=""):
        store = self.store
        if body.topic not in ["all"] + [t["id"] for t in TOPICS]:
            raise TrainingError(422, "Неизвестная тема.")
        selected = store.search(topic=body.topic, level=body.level)
        if not selected:
            raise TrainingError(422, "Для выбранной темы и сложности пока нет вопросов.")
        # Balance eligible topics and prefer less-practiced cards within each topic.
        with store.connect() as db:
            counts = dict(db.execute("""
                SELECT a.question_id, COUNT(*) FROM attempts a JOIN sessions s ON s.id=a.session_id
                WHERE s.owner_id=? GROUP BY a.question_id
            """, (owner,)))
            selected = select_questions(selected, counts, body.count, prioritize_interviews=body.prioritize_interviews)
            session_id = str(uuid.uuid4())
            profile = {"candidate_level": body.candidate_level, "specialization": next((t["name"] for t in TOPICS if t["id"] == body.topic), "Общий ML / Data Science")}
            snapshots = {str(card["id"]): card for card in selected}
            db.execute("INSERT INTO sessions(id,topic,question_ids,profile,question_snapshots,owner_id) VALUES(?,?,?,?,?,?)",
                       (session_id, body.topic, json.dumps([c["id"] for c in selected]), json.dumps(profile, ensure_ascii=False), json.dumps(snapshots, ensure_ascii=False), owner))
        return self.reader.state(session_id, owner=owner)

    def answer(self, session_id, body, *, owner=""):
        with self._reserve_session(session_id, owner):
            state = self.reader.state(session_id, owner=owner)
            if state["completed"]:
                raise TrainingError(409, "Эта тренировка уже завершена.")
            if state["reviewing"]:
                raise TrainingError(409, "Ответ уже разобран. Можно обсудить его в чате или перейти к следующему вопросу.")
            if body.question_id != state["question"]["id"]:
                raise TrainingError(409, "Вопрос уже изменился. Обнови тренировку.")
            text = body.answer.strip()
            if not body.skip and not text:
                raise TrainingError(422, "Напиши или запиши ответ.")
            card = self.reader.card(session_id, body.question_id, owner=owner)
            if body.skip:
                result = {"score": 0, "feedback": "Ориентир для ответа: " + card["reference"],
                          "covered": [], "missing": [c["label"] for c in card["criteria"]], "mode": "skipped"}
            else:
                try:
                    result = self.evaluate(card, text, self.settings, profile=state["profile"], voice=body.voice)
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
                    log_model_failure("evaluate", self.settings.trainer_model_name, body.question_id, error)
                    raise TrainingError(502, "Модель не смогла проверить ответ. Проверь ключ, баланс и название модели. Ответ сохранён в поле ввода; можно повторить запрос.")
            with self.store.connect() as db:
                db.execute("INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES(?,?,?,?,?,?)",
                           (session_id, body.question_id, text, json.dumps(result, ensure_ascii=False), result["score"], result["mode"]))
            return {"evaluation": result, "session": self.reader.state(session_id, owner=owner)}

    def discussion(self, session_id, body, *, owner=""):
        with self._reserve_session(session_id, owner):
            state = self.reader.state(session_id, owner=owner)
            if state["completed"] or not state["reviewing"]:
                raise TrainingError(409, "Обсуждение доступно после разбора текущего ответа.")
            if state["question"]["id"] != body.question_id:
                raise TrainingError(409, "Вопрос уже изменился. Обнови тренировку.")
            text = body.message.strip()
            if not text:
                raise TrainingError(422, "Напиши или запиши уточнение.")
            attempt = next(item for item in state["attempts"] if item["question"]["id"] == body.question_id)
            try:
                card = self.reader.card(session_id, body.question_id, owner=owner)
                result = self.discuss(card, attempt, text, self.settings, profile=state["profile"], voice=body.voice)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
                log_model_failure("discuss", self.settings.trainer_model_name, body.question_id, error)
                raise TrainingError(502, "Тренер не смог ответить. Сообщение осталось в поле ввода; можно отправить ещё раз.")
            with self.store.connect() as db:
                db.execute("INSERT INTO discussions(session_id,question_id,message,reply,mode) VALUES(?,?,?,?,?)",
                           (session_id, body.question_id, text, result["reply"], result["mode"]))
            return {"discussion": result, "session": self.reader.state(session_id, owner=owner)}

    def next_question(self, session_id, body, *, owner=""):
        with self._reserve_session(session_id, owner):
            state = self.reader.state(session_id, owner=owner)
            if state["completed"] or not state["reviewing"]:
                raise TrainingError(409, "Сначала ответь на текущий вопрос или пропусти его.")
            if state["question"]["id"] != body.question_id:
                raise TrainingError(409, "Вопрос уже изменился. Обнови тренировку.")
            with self.store.connect() as db:
                if state["current_index"] + 1 >= state["total"]:
                    db.execute("UPDATE sessions SET completed_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?", (session_id, owner))
                else:
                    db.execute("UPDATE sessions SET current_index=current_index+1 WHERE id=? AND owner_id=?", (session_id, owner))
            return self.reader.state(session_id, owner=owner)

    def finish(self, session_id, *, owner=""):
        with self._reserve_session(session_id, owner):
            self.reader.state(session_id, owner=owner)
            with self.store.connect() as db:
                db.execute("UPDATE sessions SET completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP) WHERE id=? AND owner_id=?", (session_id, owner))
            return self.reader.state(session_id, owner=owner)
