# Инструменты проекта

Все команды ниже выполняются из корня репозитория. Python указан из `.venv`, активация окружения не требуется.

## Установка

- `setup/setup.ps1` — установка зависимостей и создание ярлыка; вызывается корневым `Setup.cmd`.
- `setup/create-shortcut.ps1` — иконка и ярлык Windows.

```powershell
.\Setup.cmd
powershell -ExecutionPolicy Bypass -File scripts/setup/create-shortcut.ps1 -DesktopShortcut
```

## Автоматические проверки

`checks/` использует изолированные данные и имитации провайдеров. Платные API не вызываются. Проверки браузера требуют установленного Microsoft Edge; `--desktop` открывает тестовое окно WebView2.

```powershell
.\.venv\Scripts\python.exe scripts/checks/check-ui.py
.\.venv\Scripts\python.exe scripts/checks/check-rubric-ui.py
.\.venv\Scripts\python.exe scripts/checks/check-live.py
.\.venv\Scripts\python.exe scripts/checks/check-avatar.py
.\.venv\Scripts\python.exe scripts/checks/check-desktop.py
```

`check-live.py` и `check-avatar.py` поддерживают `--desktop`. `check-desktop.py --audio путь.mp3` проверяет готовую запись без генерации новой. Для отдельной проверки правил окончания речи есть `node scripts/checks/check-live-unit.js`; Node.js нужен только для этой команды.

## Диагностика провайдеров

`diagnostics/` выполняет **реальные API-запросы** с настройками `.env`. Результаты сохраняются в `logs/`.

```powershell
.\.venv\Scripts\python.exe scripts/diagnostics/check-discussion.py
.\.venv\Scripts\python.exe scripts/diagnostics/check-transcription.py
.\.venv\Scripts\python.exe scripts/diagnostics/check-fish.py
```

## Работа с вопросами

`content/sync-questions.py` импортирует банк, предварительно создавая резервную копию локальных данных. При настроенных внешних embeddings использует API. Перед запуском закрой приложение.

```powershell
.\.venv\Scripts\python.exe scripts/content/sync-questions.py
```

`content/upgrade-rubrics.py` — разовая миграция банка и архива критериев. Обычный запуск и установка приложения её не требуют; скрипт изменяет файлы в `content/`.

## Оценка моделей

`evaluation/` содержит генератор черновых ответов, экспорт/импорт разметки и прогон рабочего оценщика. Подробная методика — в [evals/README.md](../evals/README.md).

```powershell
# Только план, без API.
.\.venv\Scripts\python.exe scripts/evaluation/eval-judge.py --include-drafts
# Локальная проверка инфраструктуры, без API.
.\.venv\Scripts\python.exe scripts/evaluation/eval-judge.py --include-drafts --limit 8 --self-test
```

`eval-judge.py --run` отправляет платные запросы модели. `build-judge-dataset.py` пересоздаёт синтетические кандидаты разметки; он не нужен для обычной тренировки. `review-judge-gold.py` экспортирует таблицы и импортирует человеческую разметку.
