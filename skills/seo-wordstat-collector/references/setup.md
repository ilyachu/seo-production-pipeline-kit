# Настройка доступа к Wordstat через Yandex Cloud Search API

Один раз на машину. Дальше скилл работает без дополнительных действий.

> **Ключ никогда не коммитится в репозиторий.** Файл авторизованного ключа хранится вне
> дерева проекта (например, `~/.config/yandex-cloud/wordstat-key.json`) с правами `600`.
> Даже если положить его внутрь папки скилла — он попадёт под `.gitignore`, но правильный
> вариант всё равно хранить его снаружи. Если ключ случайно попал в коммит, считай его
> скомпрометированным: удали ключ в консоли Yandex Cloud и создай новый.

## 1. Сервисный аккаунт

Консоль Yandex Cloud → нужный каталог → **Сервисные аккаунты** → **Создать**.
Имя, например `wordstat-collector`.

Через CLI:

```bash
yc iam service-account create --name wordstat-collector
```

## 2. Роль search-api.webSearch.user

Сервисному аккаунту нужна роль **`search-api.webSearch.user`** на каталог (или на облако).
Без неё запросы к Wordstat вернут `403` — скрипт в этом случае прямо назовёт роль в ошибке.

```bash
yc resource-manager folder add-access-binding <folder-id> \
  --role search-api.webSearch.user \
  --subject serviceAccount:<service-account-id>
```

В консоли: каталог → **Права доступа** → добавить сервисный аккаунт → роль `search-api.webSearch.user`.

## 3. Folder ID

`folder_id` — идентификатор каталога, в котором выдана роль и включён Search API.
Он виден в URL консоли (`.../folders/b1g...`) или так:

```bash
yc config get folder-id
# или
yc resource-manager folder list
```

Важно: `folder_id` в конфиге и каталог, где выдана роль, должны совпадать. Расхождение
выглядит как `403`, хотя роль «вроде выдана».

## 4. Авторизованный ключ (JSON)

Wordstat вызывается от имени сервисного аккаунта по IAM-токену, а IAM-токен получается
из короткоживущего JWT, подписанного приватным ключом. Нужен **авторизованный ключ** —
JSON с полями `id`, `service_account_id`, `private_key`.

```bash
mkdir -p ~/.config/yandex-cloud
yc iam key create \
  --service-account-name wordstat-collector \
  --algorithm RSA-2048 \
  --output ~/.config/yandex-cloud/wordstat-key.json
chmod 600 ~/.config/yandex-cloud/wordstat-key.json
```

Файл выглядит так (значения — примерные, не рабочие):

```json
{
  "id": "aje...",
  "service_account_id": "aje...",
  "created_at": "2026-01-01T00:00:00Z",
  "key_algorithm": "RSA_2048",
  "public_key": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
}
```

Алгоритм подписи — **PS256** (RSA-PSS, SHA-256). Скрипт подписывает JWT через `openssl`,
записывая приватный ключ во временный файл с правами `600` и удаляя его сразу после подписи.
Содержимое ключа не попадает ни в аргументы команды, ни в вывод.

## 5. Конфиг скилла

```bash
cp skills/seo-wordstat-collector/config.example.json \
   skills/seo-wordstat-collector/config.json
```

Заполни два поля:

```json
{
  "backend": "cloud",
  "folder_id": "b1g...",
  "authorized_key_file": "/Users/<you>/.config/yandex-cloud/wordstat-key.json",
  "endpoints": {
    "iam_token": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
    "top_requests": "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"
  },
  "request_timeout_seconds": 30
}
```

`config.json` и любые файлы ключей уже перечислены в `skills/seo-wordstat-collector/.gitignore`.

## 6. HTTPS-эндпоинты

| Назначение | Метод и адрес |
|------------|---------------|
| Обмен JWT на IAM-токен | `POST https://iam.api.cloud.yandex.net/iam/v1/tokens` |
| Топ-запросы Wordstat | `POST https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests` |

Оба — только HTTPS. `doctor` откажет, если в конфиге окажется `http://`.

## 7. Проверка

```bash
python3 scripts/wordstat_client.py doctor --config skills/seo-wordstat-collector/config.json
```

Ожидаемо: `OK: конфиг заполнен структурно корректно.` и код возврата `0`.
`doctor` проверяет **только структуру конфига** — сеть не дёргает, приватный ключ не читает
и ничего секретного не печатает. Код `2` = список незаполненных полей.

Боевой запрос:

```bash
python3 scripts/wordstat_client.py top \
  --phrase "доставка цветов" --region 213 --limit 20 \
  --config skills/seo-wordstat-collector/config.json
```

Если установлен только skill, используй абсолютный путь к его встроенному `scripts/wordstat_client.py`, который агент видит в метаданных skill.

## Обращение с секретами

- Ключ хранится вне репозитория, права `600`, владелец — только ты.
- **Никогда не коммить ключ.** Ни в этот репозиторий, ни в любой другой.
- Не передавай ключ и IAM-токен в аргументах команд — они видны в `ps` и в истории shell.
  Скрипт принимает только `--config` с путём к файлу.
- IAM-токен живёт ~12 часов, JWT — минуты. Скрипт не кэширует токен на диск.
- Не вставляй содержимое ключа в чат, issue, скриншот или лог.
- Ротация: `yc iam key list --service-account-name wordstat-collector`,
  затем `yc iam key delete --id <старый>` после создания нового.

## Типовые ошибки

| Симптом | Причина | Решение |
|---------|---------|---------|
| `403`, код возврата 5 | нет роли `search-api.webSearch.user` | выдать роль на тот же каталог, что в `folder_id` |
| `401`, код возврата 5 | ключ удалён / чужой SA / часы машины сбиты | пересоздать ключ, синхронизировать время |
| `404`, код возврата 4 | Search API не включён или адрес изменён | проверить `endpoints` и активацию сервиса |
| `429`, код возврата 4 | превышена квота | пауза, затем повтор; при регулярном — запросить квоту |
| «Не найден исполняемый файл openssl» | нет OpenSSL в PATH | установить OpenSSL |
| код возврата 2 | конфиг с плейсхолдерами | заполнить поля из вывода `doctor` |

## Ручной фолбэк без API

Если доступа к Yandex Cloud нет или сервис недоступен, частотность собирается руками —
это допустимый путь, но источник обязательно помечается как ручной.

1. Открой [wordstat.yandex.ru](https://wordstat.yandex.ru), выбери **тот же регион**,
   который используешь в конвейере.
2. Введи фразу, выгрузи левую колонку (запросы) и правую («что ещё искали» → ассоциации).
3. Сложи в CSV с той же схемой, что отдаёт скрипт:

```csv
section,phrase,count_raw,count,phrase_query,regions
topRequests,доставка цветов москва,5 000,5000,доставка цветов,213
topRequests,доставка цветов недорого,1 200,1200,доставка цветов,213
associations,букет на 8 марта,310,310,доставка цветов,213
```

- `count_raw` — ровно как в интерфейсе Wordstat, вместе с пробелами-разделителями.
- `count` — то же число без пробелов; если разобрать нельзя (`<10`), оставь пустым.
- `regions` — ID региона, тот же, что выбран в интерфейсе.
- Файл сохраняй в UTF-8 (в Excel — «CSV UTF-8»), иначе кириллица поедет.

Передавая такой файл в `seo-keyword-strategist`, укажи: «частотность собрана вручную
из веб-Wordstat, дата <дата>, регион <ID>» — чтобы дальше по конвейеру было видно
происхождение чисел.
