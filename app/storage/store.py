"""Composition facade for the question index and training history repositories."""
from app.core.config import Settings
from app.questions.catalog import load_cards
from app.search.embeddings import Embeddings
from app.search.index import QuestionIndex
from app.storage.history import HistoryRepository


class Store:
    def __init__(self, settings: Settings):
        self.cards = load_cards()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings = Embeddings(settings)
        self.index = QuestionIndex(settings, self.cards, self.embeddings)
        self.by_id = self.index.by_id
        self.vectors = self.index.vectors
        self.collection = self.index.collection
        self.db_path = settings.data_dir / "history.sqlite3"
        try:
            self.history_repository = HistoryRepository(self.db_path, self.by_id)
            self.legacy_cards = self.history_repository.legacy_cards
            self.seed()
        except Exception:
            self.index.close()
            raise

    def connect(self):
        return self.history_repository.connect()

    def seed(self):
        return self.index.seed()

    def search(self, query="", topic="all", level="all"):
        return self.index.search(query, topic, level)

    def stats(self, owner=""):
        return self.history_repository.stats(owner)

    def history(self, page=1, page_size=30, *, owner=""):
        return self.history_repository.history(page, page_size, owner=owner)

    def close(self):
        self.index.close()
