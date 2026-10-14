# SEO Blog Starter

Переносимый headless WordPress-блог для уже существующего сайта. Репозиторий рассчитан на работу через агента: дайте Codex или Claude Code ссылку на этот проект и попросите интегрировать блог в ваш код без замены текущего дизайна.

Для полного процесса подготовки SEO-статей используйте совместимый набор [SEO Article Agents](https://github.com/ilyachu/seo-article-agents).

Основа выделена из проверенного production-паттерна, но персональные тексты, контакты, домены, доступы, серверные конфиги и брендовые компоненты удалены.

## Что получает сайт

- `/blog` — лента статей с категориями и пагинацией;
- `/blog/[slug]` — статья, хлебные крошки, время чтения, share/copy, связанные материалы;
- `/blog/category/[slug]` — страницы рубрик;
- headless WordPress REST client с `_embed`, Yoast fallback и контролируемой ошибкой;
- metadata, canonical, Open Graph/Twitter, Article и CollectionPage JSON-LD;
- фрагменты для sitemap, robots и `next.config`;
- адаптируемая CSS-тема без Tailwind и внешних UI-зависимостей;
- безопасный WordPress preflight и создание только draft.

## Быстрый старт с агентом

Для Codex:

> Используй `$wordpress-seo-blog-integrator`. Проанализируй мой сайт, интегрируй SEO-блог из этого репозитория в существующий дизайн. Не заменяй header/footer и токены бренда. Сначала покажи карту файлов и план, затем внеси изменения. Настрой WordPress только через server env. Проверь build, desktop/mobile, metadata, sitemap и draft preflight.

Для Claude Code:

> Используй `/wordpress-seo-blog-integrator` и интегрируй этот starter в текущий сайт. Сохрани существующую дизайн-систему. Никаких секретов в Git. Публикация — только draft.

Установка skill:

```bash
cp -R skills/wordpress-seo-blog-integrator ~/.agents/skills/       # Codex
cp -R skills/wordpress-seo-blog-integrator ~/.claude/skills/       # Claude Code
```

## Ручная интеграция

1. Прочитайте [docs/integration.md](docs/integration.md).
2. Скопируйте нужные файлы из `template/next-app-router/` в существующий Next.js App Router проект.
3. Адаптируйте `blog.css` к токенам сайта, а `BlogFrame` — к текущему layout/header/footer.
4. Заполните `.env.local` по [.env.example](.env.example).
5. Добавьте WordPress image host, sitemap и robots по snippets.
6. Запустите build и browser QA.

## Credentials

Чтение опубликованных постов обычно не требует логина. Для загрузки медиа/создания draft нужна отдельная WordPress-учётка и Application Password. Полный порядок: [docs/credentials.md](docs/credentials.md).

Никогда не храните пароль в Git, чате, URL, frontend env или browser bundle. Используйте только HTTPS и server-only env.

## Локальная проверка репозитория

```bash
node scripts/validate-template.mjs
node --test tests/*.test.mjs
node scripts/wp-preflight.mjs --public-only
```

Последняя команда требует `WORDPRESS_BASE_URL`. Live publish в этом starter отсутствует намеренно: `wp-create-draft.mjs` отказывается принимать статус `publish`.

## Ограничение совместимости

Готовые компоненты предназначены для Next.js App Router. Для другого фреймворка используйте data contract из `lib/wordpress.ts` и SEO-checklist, а UI перепишите средствами проекта.

## Лицензия

MIT
