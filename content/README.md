# Банк вопросов

Пять разделов: Классический ML, Data Science, NLP, CV, DL. Сейчас в банке **500 вопросов**:

| Раздел | Junior | Middle | Senior | Всего |
|---|---:|---:|---:|---:|
| Классический ML | 40 | 40 | 20 | 100 |
| Data Science | 40 | 40 | 20 | 100 |
| NLP | 40 | 40 | 20 | 100 |
| CV | 40 | 40 | 20 | 100 |
| DL | 40 | 40 | 20 | 100 |

Все пять тем доступны для тренировки. Градация авторская: это глубина ожидаемого рассуждения, а не универсальное соответствие должности.

Полные списки формулировок — [Классический ML](classical-ml.md), [Data Science](data-science.md), [NLP](nlp.md), [CV](cv.md), [DL](dl.md). Источник приложения — [questions.json](questions.json): у каждой карточки есть постоянный ID, тема, сложность, теги, ориентир для ответа и три содержательных критерия проверки. Ключевые слова используются только в явно обозначенном демо; реальная проверка учитывает смысл.

Data Science покрывает вероятность, статистический вывод, дизайн экспериментов, причинный анализ, SQL, pandas и качество данных. NLP — подготовку текста, классические представления, embeddings, трансформеры, обучение, retrieval, RAG, оценку генерации и эксплуатационные ограничения. Первые 100 карточек классического ML не изменены; новые ID: 101–200 для DS и 201–300 для NLP.

CV покрывает представления изображений, CNN и ViT, аугментации, детекцию, сегментацию, трекинг, геометрию, метрики и эксплуатацию. DL — backpropagation, активации, оптимизаторы, нормализацию, регуляризацию, вычислительный граф, точность, память, распределённое обучение и генеративные модели. ID 301–400 относятся к CV, 401–500 — к DL; прежние 300 карточек не изменены.

Это авторская подборка типовых вопросов. Частота конкретных формулировок не измерялась; вопросы не выдаются за утечки реальных интервью. Покрытие ориентируется на блоки, которые описывают работодатели, включая [ML-интервью Яндекса](https://yandex.ru/jobs/interview/mldev) и [ML-интервью Т-Банка](https://www.tbank.ru/career/it/interview/ml/).

Технические ориентиры для проверки и дальнейшего расширения:

- [Линейные модели](https://scikit-learn.org/stable/modules/linear_model.html): МНК, логистическая регрессия, регуляризация.
- [Ансамбли](https://scikit-learn.org/stable/modules/ensemble.html): леса, бэггинг, бустинг, OOB, стэкинг.
- [Метрики](https://scikit-learn.org/stable/modules/model_evaluation.html): классификация, регрессия, усреднения, AUC.
- [Кросс-валидация](https://scikit-learn.org/stable/modules/cross_validation.html): выбор схемы оценки и групповые/временные ограничения.
- [Калибровка](https://scikit-learn.org/stable/modules/calibration.html): вероятности и независимая подгонка калибратора.
- [Кластеризация](https://scikit-learn.org/stable/modules/clustering.html): k-means, DBSCAN и оценка разбиений.
- [Утечки и типовые ошибки](https://scikit-learn.org/stable/common_pitfalls.html): обучение преобразований и разделение данных.
- [Статистические методы SciPy](https://docs.scipy.org/doc/scipy/reference/stats.html) и [Манн — Уитни](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html): гипотезы, предпосылки, распределения и ранги.
- [Статистический вывод statsmodels](https://www.statsmodels.org/stable/stats.html): оценки, сравнения и интервалы.
- [Объединение данных pandas](https://pandas.pydata.org/docs/user_guide/merging.html): ключи и кардинальность соединений.
- [Hugging Face LLM Course](https://huggingface.co/learn/llm-course/chapter1/1): классический NLP, токенизаторы, архитектуры и обучение.
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762): scaled dot-product attention и трансформер.
- [Speculative decoding](https://arxiv.org/abs/2211.17192): принятие draft-токенов с коррекцией распределения.
- [DPO](https://arxiv.org/abs/2305.18290): оптимизация по предпочтениям без отдельного RL-цикла.
- [Transfer Learning for CV](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html) и [детекция TorchVision](https://docs.pytorch.org/tutorials/intermediate/torchvision_tutorial.html): обучение визуальных моделей и разметка.
- [Conv2d](https://docs.pytorch.org/docs/stable/generated/torch.nn.Conv2d.html) и [NMS](https://docs.pytorch.org/vision/stable/generated/torchvision.ops.nms.html): геометрия свёртки и подавление рамок.
- [COCO evaluation](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py): AP, пороги IoU, размеры объектов и видимость ключевых точек.
- [BatchNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.BatchNorm2d.html), [LayerNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html) и [GroupNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.GroupNorm.html): оси статистик и поведение train/eval.
- [AdamW](https://arxiv.org/abs/1711.05101): различие L2 и decoupled weight decay.
- [AMP examples](https://docs.pytorch.org/docs/stable/notes/amp_examples.html) и [DDP](https://docs.pytorch.org/docs/stable/generated/torch.nn.parallel.DistributedDataParallel.html): unscale, накопление и усреднение градиентов.

ID 1–6 сохранены от начальной версии, чтобы старые ответы и обсуждения продолжали открываться. Старые названия разделов отображаются как «Классический ML», содержимое истории не переписывается. Удалять или переиспользовать ID карточек с историей нельзя.

После правок банк валидируется и синхронизируется с Qdrant при запуске. Для явной загрузки с резервной копией локальных данных закройте приложение и выполните `python scripts/sync-questions.py`. Команда использует модель embeddings из `.env`, сохраняет отчёт в `logs/question-import.json` и проверяет сохранность существующей истории. Семантические векторы рассчитываются пакетами только для новых или изменённых индексируемых текстов; обновление критериев и эталонов не требует повторной векторизации. Проверочный поиск проводится по всем пяти разделам.
