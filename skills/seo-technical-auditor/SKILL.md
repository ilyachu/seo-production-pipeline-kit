---
name: seo-technical-auditor
description: Снимает ограниченный same-origin срез публичного HTTPS-сайта и сохраняет HTTP/HTML evidence без балла и без данных панелей. Use when user asks «проверь технику сайта», «запусти technical audit», «обойди robots и sitemap», «проверь title, canonical и 404» или нужен baseline перед контентом.
---

# SEO Technical Auditor

Запускай только `tools/technical_audit.py`. Это не полный технический аудит: команда не ходит в Google Search Console, PageSpeed Insights и Яндекс Вебмастер и не придумывает их цифры. Общего `score` в отчёте нет.

## Когда использовать

- Нужен проверяемый baseline публичного HTTPS-сайта без токенов панелей.
- Перед контентным конвейером нужно понять, что уже видно по HTTP и HTML.
- После правки нужно повторить тот же URL и тот же `--max-pages`.

## Вход

- `--site`: абсолютный `https://` URL без логина, пароля и без localhost, private, loopback или link-local адреса.
- `--max-pages`: целое число страниц больше нуля. Это потолок обхода, не обещание покрыть весь сайт.
- `--output`: путь JSON. Для прогона конвейера клади файл в `runs/` и не коммить сырой отчёт.

Токены Метрики, Вебмастера, Search Console и PageSpeed этому шагу не нужны. Их отсутствие не заполняй оценками.

## Что делать

Из корня репозитория:

```bash
python tools/technical_audit.py --site https://example.com/ --max-pages 20 --output audit.json
```

Команда сама обходит только свой origin с User-Agent `seo-technical-audit/1.0`. В evidence попадают `robots.txt`, sitemap того же сайта, HTTP-статус, title, meta description, H1, canonical, noindex, изображения без атрибута alt, внутренние 404 и редиректы. Чужой origin, редирект на другой сайт и адрес из `Disallow` не запрашиваются. Для редиректа `requested_url` и `final_url` записываются отдельно; метаданные конечной страницы нельзя приписывать исходному URL.

Коды процесса: `0` отчёт записан, `2` отвергнут URL или `--max-pages`, `1` файл отчёта не записан. Не подменяй ненулевой код текстом об успехе.

Прочитай JSON. Не пересчитывай находки в один балл и не добавляй проверки, которых нет в файле.

## Выход

Файл по `--output`. В конвейере это `technical-audit.json`.

Обязательное доказательство: URL в `inputs.site` и `pages[].url`, время в `checked_at`, метод в `agent` = `technical_audit` и `findings[].source` = `crawl`, наблюдение HTTP/HTML в `pages`, `robots`, `sitemap`, `internal_404` и `findings`.

Статусы отчёта, не путать с вердиктом сайта:

- `status` = `completed`: robots.txt удалось прочитать либо он не скрыл правила ответом 5xx или обрывом. Страницы запрошены в пределах лимита. `Disallow` оставляет `status` = `completed`, пишет URL в `robots.blocked` и не делает вид, что эти URL открыты.
- `status` = `blocked`: `robots.txt` вернул HTTP 0 или 500 и выше. `pages` пустой, `crawl.status` = `not_checked`, в `not_checked` есть `on_page` с причиной. Страницы не угадывай.
- `crawl.status`: `completed` или `not_checked`. `crawl.truncated` и `sitemap.truncated` означают неполную выборку даже при `completed`.
- Находка: `severity` только `high`, `medium` или `low`. Поле `impact` — отдельное предложение о последствии, не повтор severity. Рядом должны быть `check`, `url`, `observation`, `fix`, `recheck`, `checked_at`.

`not_checked` всегда содержит `gsc`, `psi` и `webmaster` со статусом `not_checked` и непустой `reason`. Это честный пропуск, не провал и не успех. При `blocked` туда же попадает `on_page`.

Риски, которые нужно назвать в ответе:

- выборка ограничена `--max-pages`, очередью, 20 файлами sitemap и 1000 URL sitemap;
- видны только same-origin HTML/HTTP сигналы из списка выше, не скорость, не мобильный замер, не индекс, не ссылочный профиль и не аналитика;
- `completed` не значит «сайт в порядке» и не значит «сайт проверен целиком»;
- `blocked`, пустые `pages` и `truncated: true` нельзя описывать как выполненный обход страниц.

## Самостоятельный режим

Если нет `--site` или `--max-pages`, остановись со статусом `needs_input`. Если сеть или запись файла не удались, статус `failed` и текст ошибки команды. При успешном запуске верни путь к JSON, `status` отчёта, число `pages`, флаги `truncated`, находки с `severity` и `impact`, список `not_checked` с причинами и риски из раздела «Выход». Не изображай непроверенные панели выполненными.

## Режим конвейера

Пиши только свой артефакт. Не заполняй `semantic`, `research`, `draft`, `meta`, `audit` статьи и `publication`. В сопроводительной записи укажи `inputs_used`, `assumptions`, `missing_inputs` и статус роли: `ready`, `needs_input`, `blocked` или `failed`.

`ready` значит только то, что JSON команды записан и прочитан. Он не закрывает ворота «техника исправлена» и не ставит контентному аудиту `pass`. Если отчёт `blocked`, статус роли тоже `blocked`. `needs_input` и `failed` не считаются выполнением шага. Следующую роль не запускай и чужие артефакты не меняй.

## Проверка

- В отчёте есть `schema_version` = `1`, `inputs.site`, `inputs.max_pages`, `checked_at`, `pages`, `findings`, `not_checked`.
- У каждой находки `severity` из `high`/`medium`/`low`, а `impact` — фраза не из этих трёх слов.
- `gsc`, `psi`, `webmaster` лежат в `not_checked` с причиной; ключа `score` нет.
- При нечитаемом robots.txt статус отчёта `blocked`, страницы не запрошены, `on_page` помечен `not_checked`.
- В ответе нет формулировки, что выполнен полный технический аудит или что индекс, Core Web Vitals и панели проверены.
- В JSON и в команде нет паролей, токенов и приватных ключей.
