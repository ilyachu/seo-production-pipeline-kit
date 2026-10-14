---
name: seo-wordstat-collector
description: Собирает реальную частотность Wordstat через Yandex Cloud Search API и отдаёт JSON/CSV без выдуманных чисел. Use when user asks «выгрузи Wordstat», «собери частотность», «получи запросы по региону», «подготовь CSV для семантики» или начинает SEO-пайплайн.
---

# SEO Wordstat Collector

Собирай top requests и associations до классификации семантики. Пошаговая настройка: [setup.md](references/setup.md).

## Когда использовать

- Нужны реальные запросы и частотность по теме/региону.
- Есть Yandex Cloud service account или ручная выгрузка Wordstat.
- Нужно создать вход для `seo-keyword-strategist`.

## Вход

- Фраза исследования.
- Регион: название и ID Яндекса.
- Бизнес-цель: статья, посадочная, каталог, сравнение и что продаём/объясняем.
- `config.json` с folder ID и путём к авторизованному ключу либо ручной CSV.

Без региона и бизнес-цели задай один короткий вопрос и остановись. Не подставляй регион молча.

Если нет Cloud-конфига, спроси `folder_id` и **путь** к ключу сервисного аккаунта либо попроси ручную CSV-выгрузку. Объясни выдачу прав через [setup.md](references/setup.md). Значение ключа в чат не проси. Пока нет ни доступа, ни CSV, верни `needs_input` с точным списком недостающего.

## Настройка и запуск

Из клонированного репозитория:

```bash
python3 scripts/wordstat_client.py doctor \
  --config skills/seo-wordstat-collector/config.json

python3 scripts/wordstat_client.py top \
  --phrase "доставка цветов" \
  --region 213 \
  --limit 100 \
  --format csv \
  --config skills/seo-wordstat-collector/config.json \
  --output wordstat.csv
```

После отдельной установки skill агент должен определить абсолютный каталог текущего `seo-wordstat-collector` и запускать `<skill-dir>/scripts/wordstat_client.py`. Не предполагай, что пользователь находится в корне клона.

Скрипт использует стандартную библиотеку Python и `openssl`: короткий JWT PS256 обменивается на IAM token, затем вызывается HTTPS Wordstat endpoint. Ключ/токен не передаются через argv и не печатаются.

## Выход

В `semantic.raw_queries` или отдельном JSON/CSV:

- `source`, `phrase`, `regions`, `collected_at`;
- `topRequests` и `associations`;
- для строки: `phrase`, `count_raw` и нормализованный `count` (`null`, если не разобран).

CSV использует колонки `section,phrase,count_raw,count,phrase_query,regions` и UTF-8 BOM для Excel.

## Самостоятельный режим

Верни файл Wordstat и короткую сводку: дата, регион, число top/associations, код результата. При отсутствии Cloud-доступа предложи ручной CSV-фолбэк из setup.md; только фактически переданный CSV помечай `source=manual`.

## Режим конвейера

Заполни только `semantic.raw_queries`, сохрани сырой ответ и передай `seo-keyword-strategist`. Не определяй ядро/интент на этом шаге и не «улучшай» частотность.

## Проверка

- Region ID и бизнес-цель зафиксированы.
- `count_raw` сохранён, `count` не выдуман.
- Для Cloud-ответа поддерживаются `results` и `associations`.
- Ошибка API имеет non-zero code; вместо данных не возвращается строка-«успех».
- В артефактах/логах нет private key, JWT или IAM token.

Коды: `0` успех; `2` неполный конфиг; `3` файл не найден; `4` сеть/API; `5` auth/роль.
