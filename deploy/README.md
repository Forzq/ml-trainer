# Закрытая бета Mockroom

Адрес беты — `https://mockroom.dynv6.net`. На VPS бета использует отдельный проект Docker Compose, порт `127.0.0.1:8766` и отдельный том данных. Пользовательский доступ открывается через Caddy. Базу беты и личную базу из SSH-версии обслуживают разные контейнеры.

## Выкладка на Linux VPS

Команды выполняются на VPS из корня репозитория. Нужны Docker Compose, DNS A-запись на публичный IPv4 VPS и свободные TCP-порты 80 и 443 для Caddy. Если эти порты уже обслуживает веб-сервер, добавь маршрут для домена в его конфигурацию вместо запуска второго прокси. [Требования Caddy к HTTPS](https://caddyserver.com/docs/automatic-https#hostname-requirements)

На текущем VPS бета установлена в `/opt/mockroom-beta`. При доставке исходников архивом каталоги `app`, `web`, `content` и `deploy` должны быть доступны на чтение и обход, чтобы контейнер мог читать скопированные файлы от имени `appuser`. Серверный `.env` хранится с правами `600`.

Серверный `.env` содержит ключи моделей, голосовых сервисов и существующую настройку `OPENROUTER_PROXY_URL`, если она нужна. `compose.beta.yaml` включает закрытый режим и локальную индексацию каталога.

Сначала подними бэкенд на loopback и проверь, что API закрыт без сессии:

```bash
docker compose -f compose.beta.yaml up -d --build trainer
curl --fail http://127.0.0.1:8766/api/health
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Host: mockroom.dynv6.net' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8766/api/history
```

Последняя команда должна вернуть `401`. Затем подними Caddy и дождись выпуска сертификата:

```bash
docker compose -f compose.beta.yaml --profile edge up -d caddy
docker compose -f compose.beta.yaml logs --tail=50 caddy
curl --fail https://mockroom.dynv6.net/api/health
curl -s -o /dev/null -w '%{http_code}\n' https://mockroom.dynv6.net/api/history
```

Публичный запрос истории без входа должен вернуть `401`. Открой адрес в браузере и проверь появление формы входа. Перед выдачей приглашений проверь вход в двух разных профилях браузера, ответы и историю каждого участника.

## Приглашения и доступ

```bash
docker compose -f compose.beta.yaml exec trainer python -m app.beta.admin invite --label 'Участник 1'
docker compose -f compose.beta.yaml exec trainer python -m app.beta.admin list
```

Команда выдаёт одноразовый код на 72 часа, идентификатор приглашения и идентификатор участника. Передай участнику адрес беты и его код. Браузер запоминает сессию на 30 дней. Для повторного входа с сохранением истории выпусти код с `invite --account ID_УЧАСТНИКА`.

```bash
docker compose -f compose.beta.yaml exec trainer python -m app.beta.admin revoke-invite ID_ПРИГЛАШЕНИЯ
docker compose -f compose.beta.yaml exec trainer python -m app.beta.admin revoke-account ID_УЧАСТНИКА
```

## Суточные квоты

По умолчанию у участника 30 запросов в сутки, у всей беты 100. Общий предел действует на всех, включая участников с персональной квотой. Оценка ответа, разбор и голосовые запросы с подключёнными провайдерами расходуют квоту. Одна голосовая тренировка может расходовать несколько запросов. История, локальный каталог и вход доступны при исчерпании квоты.

На VPS из `/opt/mockroom-beta` запусти следующие команды. `limits` показывает расход, текущие квоты и ID участников.

```bash
beta() { docker compose -f compose.beta.yaml exec -T trainer python -m app.beta.admin "$@"; }
beta limits
beta set-limit 45 --account ID_УЧАСТНИКА
beta set-limit 0 --account ID_УЧАСТНИКА
beta reset-limit --account ID_УЧАСТНИКА
beta set-limit 25 --default
beta set-limit 75 --global
```

Изменения действуют сразу и сохраняются в `beta.sqlite3`. Значение `0` приостанавливает запросы к платным функциям в выбранной квоте. Расход за сегодня сохраняется при изменении лимита и обнуляется в полночь UTC. `reset-limit --default` и `reset-limit --global` возвращают значения из `MOCKROOM_BETA_USER_LIMIT` и `MOCKROOM_BETA_TOTAL_LIMIT` в `.env` или встроенные значения, если переменные отсутствуют.

Для отдельного суточного бюджета в долларах создай ключ для беты с `Credit limit` и сбросом `Daily`. Укажи его в `OPENROUTER_API_KEY` только в `/opt/mockroom-beta/.env` и примени смену ключа командой `docker compose -f compose.beta.yaml up -d --no-deps trainer`. Бюджет ключа можно менять в OpenRouter без обновления контейнера. [Настройка ключа и лимита](https://learn.openrouter.ai/courses/first-request/create-an-api-key)

## Отзыв доступа и резервное копирование

Отзыв кода действует до активации. Отзыв аккаунта завершает его сессии и отключает вход. Резервируй `history.sqlite3` и `beta.sqlite3` из тома беты средствами SQLite backup либо при остановленном контейнере. Для остановки публичного входа используй `docker compose -f compose.beta.yaml --profile edge stop caddy`.
