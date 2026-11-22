# Банк вопросов

С версии рубрик v1 у критериев есть стабильный `id` и `max_points`, сумма весов карточки — 100. Поле `followups` содержит необязательное углубление: его отсутствие в ответе не уменьшает основной балл. Пересмотрены 17 перегруженных карточек, включая 302 («Изображение как тензор»); прежние варианты сохранены в `question-versions-v1.json` для истории. Эталоны могут содержать дополнительный контекст, который не становится обязательным без явного вопроса. Снимок карточки сохраняется в тренировке, поэтому изменение банка не меняет уже заданное условие.

В банке **530 вопросов** по шести направлениям.

| Раздел | Junior | Middle | Senior | Всего |
|---|---:|---:|---:|---:|
| Классический ML | 43 | 45 | 20 | 108 |
| Data Science | 44 | 42 | 20 | 106 |
| NLP | 40 | 43 | 20 | 103 |
| CV | 40 | 40 | 20 | 100 |
| DL | 40 | 40 | 20 | 100 |
| Системный дизайн | 4 | 5 | 4 | 13 |

Все шесть тем доступны для тренировки. Уровни задают глубину ожидаемого рассуждения.

Полные списки формулировок — [Классический ML](classical-ml.md), [Data Science](data-science.md), [NLP](nlp.md), [CV](cv.md), [DL](dl.md), [Системный дизайн](ml-system-design.md). У каждой карточки в банке есть постоянный ID, тема, сложность, теги, ориентир для ответа и критерии проверки. Ключевые слова используются в деморежиме. Основной оценщик учитывает смысл. [Банк карточек](questions.json)

Data Science покрывает вероятность, статистический вывод, дизайн экспериментов, причинный анализ, SQL, pandas и качество данных. NLP — подготовку текста, классические представления, embeddings, трансформеры, обучение, retrieval, RAG, оценку генерации и эксплуатационные ограничения. Основные диапазоны ID: 1–100 для классического ML, 101–200 для DS и 201–300 для NLP.

CV покрывает представления изображений, CNN и ViT, аугментации, детекцию, сегментацию, трекинг, геометрию, метрики и эксплуатацию. DL — backpropagation, активации, оптимизаторы, нормализацию, регуляризацию, вычислительный граф, точность, память, распределённое обучение и генеративные модели. ID 301–400 относятся к CV, 401–500 — к DL.

Системный дизайн объединяет практические задачи по постановке, данным, инференсу, запуску моделей и мониторингу. В него входят кейсы по скорингу, рекомендациям и RAG.

Введите `mock-interview` в поиск банка, чтобы открыть 62 карточки, сверенные с видео. Поле `mock_sources` хранит ссылку на запись, дату, интервал и пересказ эпизода. У источников MLinside указан формат `expert-review`, у разборов банковских интервью — `interview-review`. Технические уточнения входят в эталон `reference`.

Из мока взяты вопросы о переобучении, ансамблях и кейсе модерации. [Запись мока от 17 ноября 2026](https://rutube.ru/video/b3c5fb775446b19f0c02f6295c8d2030/)

По двум выпускам MLinside обновлены 24 существующие карточки и добавлены 10. Обработаны все 25 пронумерованных пунктов, включая вопросы по Python, вероятности и статистике. Эти выпуски от мая 2025 добавлены как исключение по дате. [Часть 1](https://www.youtube.com/watch?v=yKcVqADPoXE) · [Часть 2](https://www.youtube.com/watch?v=Xdx5ud_04ek)

Интервью на Middle ML Developer в Газпромбанке сопоставлено с 23 карточками, в том числе четырьмя кейсами по скорингу в системном дизайне. В эталонах уточнены предпосылки МНК, построение ROC и оценка при фиксированной доле одобрений. [Запись от 11 августа 2026](https://rutube.ru/video/a75eac4d7c1e76e9d9a75c48b8f9db97/)

Из интервью на ML NLP Engineer взяты четыре карточки или уточнения по precision и recall, MAP и MRR, пайплайну RAG и HyDE. Для выбора метрики в скоринге фиксируются положительный класс и стоимость ошибок. Выигрыш HyDE проверяется сравнением с обычным поиском на одном наборе. [Запись от 11 августа 2026](https://rutube.ru/video/2444aac17e534d4c84c2c94d14dfc066/) · [Работа о HyDE](https://arxiv.org/abs/2212.10496)

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

После правок банк валидируется и синхронизируется с Qdrant при запуске. Для явной загрузки с резервной копией локальных данных закройте приложение и выполните `python scripts/content/sync-questions.py`. Команда использует модель embeddings из `.env`, сохраняет отчёт в `logs/question-import.json` и проверяет сохранность существующей истории. Семантические векторы рассчитываются пакетами для новых или изменённых индексируемых текстов. Проверочный поиск проводится по всем шести разделам.
