# Банк вопросов

С версии рубрик v1 у критериев есть стабильный `id` и `max_points`, сумма весов карточки — 100. Поле `followups` содержит необязательное углубление: его отсутствие в ответе не уменьшает основной балл. Пересмотрены 17 перегруженных карточек, включая 302 («Изображение как тензор»); прежние варианты сохранены в `question-versions-v1.json` для истории. Эталоны могут содержать дополнительный контекст, который не становится обязательным без явного вопроса. Снимок карточки сохраняется в тренировке, поэтому изменение банка не меняет уже заданное условие.

В банке **569 вопросов** по шести направлениям.

| Раздел | Junior | Middle | Senior | Всего |
|---|---:|---:|---:|---:|
| Классический ML | 43 | 50 | 20 | 113 |
| Data Science | 46 | 47 | 20 | 113 |
| NLP | 40 | 50 | 21 | 111 |
| CV | 40 | 44 | 20 | 104 |
| DL | 40 | 41 | 20 | 101 |
| Системный дизайн | 4 | 17 | 6 | 27 |

Все шесть тем доступны для тренировки. Уровни задают глубину ожидаемого рассуждения.

Полные списки формулировок — [Классический ML](classical-ml.md), [Data Science](data-science.md), [NLP](nlp.md), [CV](cv.md), [DL](dl.md), [Системный дизайн](ml-system-design.md). У каждой карточки в банке есть постоянный ID, тема, сложность, теги, ориентир для ответа и критерии проверки. Ключевые слова используются в деморежиме. Основной оценщик учитывает смысл. [Банк карточек](questions.json)

Data Science покрывает вероятность, статистический вывод, дизайн экспериментов, причинный анализ, SQL, pandas и качество данных. NLP — подготовку текста, классические представления, embeddings, трансформеры, обучение, retrieval, RAG, оценку генерации и эксплуатационные ограничения. Основные диапазоны ID: 1–100 для классического ML, 101–200 для DS и 201–300 для NLP.

CV покрывает представления изображений, CNN и ViT, аугментации, детекцию, сегментацию, трекинг, геометрию, метрики и эксплуатацию. DL — backpropagation, активации, оптимизаторы, нормализацию, регуляризацию, вычислительный граф, точность, память, распределённое обучение и генеративные модели. ID 301–400 относятся к CV, 401–500 — к DL.

Системный дизайн объединяет практические задачи по постановке, данным, инференсу, запуску моделей и мониторингу. В него входят кейсы по скорингу, рекомендациям и RAG.

Введите `mock-interview` в поиск банка, чтобы открыть 93 карточки, сверенные с видео. Поле `mock_sources` хранит ссылку на запись, дату, интервал и пересказ эпизода. Источники маркируются по формату `mock`, `real-interview`, `interview-review` или `expert-review`. Технические уточнения входят в эталон `reference`.

Поиск `github_ques` открывает 248 карточек, сверенных с шестью коллекциями GitHub. У 220 существующих карточек добавлены источники, у 22 из них также уточнены эталоны или дополнительные вопросы. Ещё 28 карточек добавлены для самостоятельной практики. Поле `github_sources` хранит имя репозитория и ссылку на строку вопроса в использованной версии. У одной карточки могут быть оба тега. Наличие вопроса в подборке не учитывается как запись интервью при выборе приоритета в тренировке.

- Классический ML, CV и DL. [epishchik/ML-Interview](https://github.com/epishchik/ML-Interview) · [justxor/MachineLearningRoadmap](https://github.com/justxor/MachineLearningRoadmap/tree/main/interview-prep) · [andrewekhalel/MLQuestions](https://github.com/andrewekhalel/MLQuestions)
- Data Science и эксперименты. [kojino/120-Data-Science-Interview-Questions](https://github.com/kojino/120-Data-Science-Interview-Questions)
- NLP, LLM и проектирование систем. [landedjobs/ai-interview-questions](https://github.com/landedjobs/ai-interview-questions) · [chiphuyen/machine-learning-systems-design](https://github.com/chiphuyen/machine-learning-systems-design)

Поле `interview_frequency` хранит редакционную оценку типичности для соответствующей роли. Три звезды — базовый или регулярно повторяющийся вопрос, две — вопрос, который периодически встречается, одна — узкий вопрос или конкретная задача. Записи помогают подтвердить актуальность вопроса. Статистика частоты по всему рынку для этой оценки не собиралась.

Из мока взяты вопросы о переобучении, ансамблях и кейсе модерации. [Запись мока от 17 ноября 2026](https://rutube.ru/video/b3c5fb775446b19f0c02f6295c8d2030/)

По двум выпускам MLinside обновлены 24 существующие карточки и добавлены 10. Обработаны все 25 пронумерованных пунктов, включая вопросы по Python, вероятности и статистике. Эти выпуски от мая 2025 добавлены как исключение по дате. [Часть 1](https://www.youtube.com/watch?v=yKcVqADPoXE) · [Часть 2](https://www.youtube.com/watch?v=Xdx5ud_04ek)

Интервью на Middle ML Developer в Газпромбанке сопоставлено с 23 карточками, в том числе четырьмя кейсами по скорингу в системном дизайне. В эталонах уточнены предпосылки МНК, построение ROC и оценка при фиксированной доле одобрений. [Запись от 11 августа 2026](https://rutube.ru/video/a75eac4d7c1e76e9d9a75c48b8f9db97/)

Из интервью на ML NLP Engineer взяты четыре карточки или уточнения по precision и recall, MAP и MRR, пайплайну RAG и HyDE. Для выбора метрики в скоринге фиксируются положительный класс и стоимость ошибок. Выигрыш HyDE проверяется сравнением с обычным поиском на одном наборе. [Запись от 11 августа 2026](https://rutube.ru/video/2444aac17e534d4c84c2c94d14dfc066/) · [Работа о HyDE](https://arxiv.org/abs/2212.10496)

По трём записям YouTube обновлены 25 карточек и добавлены 6. Классический ML дал вопросы про OvR/OvO и MAPE. Из мока по Data Science взяты кейс про шеринг аккаунтов и уточнения про формулу Байеса и PSI. Из AI-интервью добавлены HNSW, расчёт VRAM для LLM и проектирование исследовательского агента. [Classic ML, 15 января 2025](https://www.youtube.com/watch?v=AsHMSRIVzLE) · [Mock Data Science, 11 февраля 2026](https://www.youtube.com/watch?v=AuBCrqAPNUU) · [AI Engineer, 12 июля 2026](https://www.youtube.com/watch?v=jmOzoC02-zQ)

Из обзора личного опыта по собеседованиям на ML/AI-инженера добавлены пять упражнений Middle: проверка LLM-судьи на gold и silver, настройки контекста RAG, выбор модели под бюджет памяти, технический рассказ о проекте и оценка действий агента. У 20 существующих карточек появились таймкоды, а у 12 из них уточнены формулировки, эталоны или дополнительные вопросы. Обзор помечен как `expert-review`. Частотные оценки опираются на специализацию и несколько источников. [Обзор от 26 сентября 2026](https://www.youtube.com/watch?v=PzKt8Pea2iE)

Это авторская подборка типовых вопросов. Частота конкретных формулировок не измерялась; вопросы не выдаются за утечки реальных интервью. Покрытие ориентируется на блоки, которые описывают работодатели, включая [ML-интервью Яндекса](https://yandex.ru/jobs/interview/mldev) и [ML-интервью Т-Банка](https://www.tbank.ru/career/it/interview/ml/).

Технические ориентиры для проверки и дальнейшего расширения:

- [Линейные модели](https://scikit-learn.org/stable/modules/linear_model.html): МНК, логистическая регрессия, регуляризация.
- [Ансамбли](https://scikit-learn.org/stable/modules/ensemble.html): леса, бэггинг, бустинг, OOB, стэкинг.
- [Метрики](https://scikit-learn.org/stable/modules/model_evaluation.html): классификация, регрессия, усреднения, AUC.
- [Кросс-валидация](https://scikit-learn.org/stable/modules/cross_validation.html): выбор схемы оценки и групповые/временные ограничения.
- [Калибровка](https://scikit-learn.org/stable/modules/calibration.html): вероятности и независимая подгонка калибратора.
- [Кластеризация](https://scikit-learn.org/stable/modules/clustering.html): k-means, DBSCAN и оценка разбиений.
- [HNSW в Qdrant](https://qdrant.tech/documentation/manage-data/indexing/) и [PagedAttention](https://arxiv.org/abs/2309.06180): параметры поиска и управление KV-кэшем.
- [FlashAttention](https://arxiv.org/abs/2205.14135), [QLoRA](https://arxiv.org/abs/2305.14314) и [латентная диффузия](https://arxiv.org/abs/2112.10752): первичные работы для новых вопросов по NLP и DL.
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
