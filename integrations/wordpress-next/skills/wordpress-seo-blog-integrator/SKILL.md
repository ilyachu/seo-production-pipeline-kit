---
name: wordpress-seo-blog-integrator
description: Интегрирует переносимый headless WordPress SEO-блог в существующий сайт с адаптацией вёрстки и безопасных credentials. Use when user asks «добавь SEO-блог в готовый сайт», «подключи WordPress как headless CMS», «интегрируй blog starter» или даёт ссылку на этот репозиторий.
---

# WordPress SEO Blog Integrator

## Когда использовать

- У готового сайта нет SEO-блога.
- Нужно подключить WordPress, сохранив текущий frontend и дизайн.
- Нужно перенести routes, metadata, schema, sitemap/robots и draft workflow.

## Вход

- Host repository и его AGENTS/CLAUDE/project instructions.
- Framework/version, package manager и deploy target.
- `SITE_URL`, публичный HTTPS `WORDPRESS_BASE_URL`.
- Бренд-токены, shell/header/footer и требования SEO.

## Порядок

1. Read-only исследуй host repo. Верни карту `path:line`, зависимости и точную границу изменений.
2. Выбери адаптацию: Next.js App Router template или перенос data contract/UI в другой framework.
3. Сохрани текущий layout, header/footer, токены, analytics, consent и routing conventions.
4. Интегрируй public read path без write credentials в browser bundle.
5. Добавь blog list, article, category, error/empty states, featured media и related links.
6. Объедини metadata, canonical, OG, Article/CollectionPage schema, sitemap и robots с текущими реализациями.
7. Добавь `.env.example`; реальные значения остаются в server secrets.
8. Настрой draft preflight отдельно. Не публикуй.
9. Запусти host lint/typecheck/tests/build и browser QA на desktop/mobile.

## Выход

- Малый diff в host repository.
- Карта скопированных/адаптированных файлов.
- Environment contract без секретов.
- Evidence: команды, routes, metadata/schema, browser console, residual risks.

## Самостоятельный режим

Если host repo недоступен, подготовь интеграционный план и список файлов, но не утверждай, что вёрстка или build совместимы.

## Режим конвейера

Работай после того, как SEO-пайплайн подготовил материал. WordPress publisher создаёт draft; этот skill отвечает за отображение, индексацию и интеграцию с shell сайта.

## Проверка

- Существующие страницы и shell не заменены.
- Write secrets отсутствуют в Git и client bundle.
- CMS URL использует HTTPS.
- `/blog`, статья, категория, sitemap и robots проверены.
- Canonical, OG, JSON-LD, alt, responsive и accessibility работают.
- Live publish не выполнялся без явного подтверждения.
