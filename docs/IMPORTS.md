# Происхождение импорта

Срез: 2026-10-13. Файлы скопированы в новый репозиторий. Исходные репозитории не изменялись. Каждый блок ниже сохраняет лицензию источника и полный commit SHA.

`docs/seo-agent-map.html` построен локальным CLI [QingYunA/answer-me-with-html](https://github.com/QingYunA/answer-me-with-html) версии 0.5.2 из Markdown-источника `docs/seo-agent-map.md`. CLI не входит в этот репозиторий; HTML — самостоятельный файл. Инструмент имеет лицензию MIT. Его код не копировался.

Для отдельного просмотра HTML адаптирован после генерации: агентам оставлены текстовые описания без ссылок на приватные файлы, убраны элементы комментариев и копирования исходника. Встроенный Markdown синхронизирован с `docs/seo-agent-map.md`; это проверяет `tests/test_public_artifact.py`.

Не импортировались: `seo_writer`, `seo_ya`, отчёты с данными конкретных сайтов, `.env`, service-account JSON, токены и живые пароли.

## seo-article-agents

- URL: https://github.com/ilyachu/seo-article-agents
- Commit: `b6c3de582e52027b6a2b2b82ac22cf536e0f7463`
- Дата commit: 2026-09-04 23:25:03 +0300
- Лицензия: MIT. Copyright (c) 2026 Ilya Chumachenkov
- Файл лицензии: точная копия исходного [docs/licenses/seo-article-agents.LICENSE](licenses/seo-article-agents.LICENSE). Корневой [LICENSE](../LICENSE) — полный текст MIT для нового репозитория от того же автора.
- Замечание: в исходном `LICENSE` только заголовок MIT и строка copyright. Полный текст permission notice в источнике отсутствует; копия сохранена без изменений.

Скопировано в те же пути относительно корня:

- `skills/` — 12 skills: `seo-pipeline-orchestrator`, `seo-wordstat-collector`, `seo-keyword-strategist`, `seo-research-dossier`, `seo-brand-brief`, `seo-outline-planner`, `seo-linking-editor`, `seo-article-writer`, `seo-image-producer`, `seo-meta-generator`, `seo-content-auditor`, `seo-wordpress-publisher`
- `contracts/pipeline.md`
- `contracts/article-package.schema.json`
- `scripts/wordstat_client.py`
- `scripts/validate_skills.py`
- `scripts/install.sh`
- `tests/test_validate_skills.py`
- `tests/test_wordstat_client.py`
- `examples/article-package.example.json` — искусственный пакет для проверки структуры

Не копировались README, AGENTS.md, AUDIT.md, Makefile, `docs/`, остальные `examples/`, `.git` и `__pycache__` этого источника. Внутри `seo-wordstat-collector` оставлен его собственный `.gitignore`: он не содержит секретов и не даёт закоммитить локальный `config.json`.

`scripts/wordstat_client.py` и копия в skill совпадают по байтам. То же для `contracts/pipeline.md` и копии в `seo-pipeline-orchestrator/references/pipeline.md`.

## seo-blog-starter

- URL: https://github.com/ilyachu/seo-blog-starter
- Commit: `0b39eebfdca2065aebcea51759d30e918549473e`
- Дата commit: 2026-09-04 23:23:54 +0300
- Лицензия: MIT. Copyright (c) 2026 Ilya Chumachenkov
- Файл лицензии: [integrations/wordpress-next/LICENSE](../integrations/wordpress-next/LICENSE) и точная копия [docs/licenses/seo-blog-starter.LICENSE](licenses/seo-blog-starter.LICENSE)
- Назначение: `integrations/wordpress-next/`

Скопировано дерево starter, кроме метаданных Git (`.git`). Это шаблон Next.js App Router и headless WordPress: `template/`, `scripts/`, `skills/wordpress-seo-blog-integrator/`, `tests/`, `docs/`, `AGENTS.md`, `README.md`, `.gitignore`, `.env.example`.

Проверка примеров на секреты:

- `.env.example` содержит пустой `WORDPRESS_APPLICATION_PASSWORD=`. Файл нужен офлайн-валидатору шаблона. Это не секрет.
- `docs/article-payload.example.json` — учебный payload без учётных данных.
- `docs/credentials.md` описывает порядок Application Password и показывает шаблон `xxxx xxxx xxxx xxxx`. Живого пароля нет.

Отдельного каталога примеров с секретами в источнике не было, поэтому ни один такой пример не переносился. Файла `.env` в источнике не было.

## seo-skills

- URL: https://github.com/ilyachu/seo-skills
- Commit: `be8051acf46e186f14aa7308e3312bed38288734`
- Дата commit: 2026-08-22 11:41:38 +0300
- Лицензия: MIT. Copyright (c) 2026 chu_il
- Файл лицензии: [knowledge/checklist/LICENSE](../knowledge/checklist/LICENSE) и точная копия [docs/licenses/seo-skills.LICENSE](licenses/seo-skills.LICENSE)
- Назначение: `knowledge/checklist/`

Скопированы и адаптированы 14 файлов чек-листа: `01-indexing.md` … `14-prioritization.md`. Каталоги `skills/`, `README.md`, `CONTRIBUTING.md` и `.github` этого репозитория не копировались. Пункты чек-листа — методика, не исполняемый аудит. 35 ссылок на skills, отсутствующие в этом пакете, заменены названиями идей; текст методики и атрибуция сохранены.

Ссылки вида `[Назад к чек-листу](../README.md)` теперь ведут на локальный [knowledge/README.md](../knowledge/README.md). Этот индекс создан для нового репозитория и не копирует устаревающие инструкции доступа к API.

## Редакционная SVG-обложка

Идея макета, не копия файла и не контент конкретного сайта.

- Источник идеи: `writer_rerait_moi/enrichment/local_svg_covers.py`; абсолютный путь и файлы авторского проекта в этот репозиторий не входят.
- Commit этого файла: `35e3fde3e793cb56db17bd115ce55616d12944c0` (2026-04-20 13:07:43 +0300). Отдельной лицензии в том репозитории нет. Исходный файл не изменялся.
- Что взято из идеи: детерминированный локальный SVG 1600×900, перенос строк, экранирование текста, тёплое поле, тонкая сетка, рамка, одна акцентная полоса, крупная типографика на обложке, alt и prompt в самом файле.
- Не переносились: брендовые подписи, палитры и тексты статей конкретных сайтов, сетевые генераторы, учётные данные.
- Новая реализация в этом репозитории: [tools/render_svg_cover.py](../tools/render_svg_cover.py). Проверенный пример входа: [examples/cover-demo.svg](../examples/cover-demo.svg). Зависимостей кроме стандартной библиотеки Python нет.
