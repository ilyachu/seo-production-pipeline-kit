# Интеграция в существующий сайт

## 1. Сначала исследование

Агент должен найти: framework/version, App Router или Pages Router, alias `@/`, текущие layout/header/footer, дизайн-токены, metadataBase, sitemap/robots, image policy, тесты и deploy runtime. До этого копировать файлы нельзя.

## 2. Минимальная граница

Из `template/next-app-router/` обычно нужны:

- `config/blog.ts`;
- `lib/wordpress.ts`;
- `components/blog/*`;
- `app/blog/*`;
- `app/blog/blog.css` или перенос его правил в текущий CSS-слой.

Snippets не копируются вслепую: их содержимое объединяется с существующими `sitemap`, `robots` и `next.config`.

## 3. Дизайн

`BlogFrame` — намеренно простой wrapper. Замените его на текущий `SiteShell`/layout, но не дублируйте `<html>` и `<body>`. Перенесите CSS variables в токены проекта. Проверьте длинные русские H1, таблицы, изображения и код на 320/390/768/1440 px.

## 4. WordPress data flow

Frontend читает только опубликованные записи:

`Next server → WORDPRESS_BASE_URL/wp-json/wp/v2 → posts/categories/media → site routes`

Используется `_embed=true`, чтобы получить author, featured media и terms. Pagination берётся из `X-WP-Total` и `X-WP-TotalPages`. Если CMS временно недоступна, UI показывает контролируемое состояние, а не маскирует ошибку пустым «успехом».

## 5. SEO

- self-referencing canonical;
- уникальные title/description;
- Open Graph/Twitter image;
- Article JSON-LD на статье;
- CollectionPage на ленте и рубрике;
- blog/post/category URLs в sitemap;
- robots с URL sitemap;
- 404 для неизвестного slug;
- внутренние ссылки и breadcrumbs;
- alt для featured image.

Schema должна совпадать с видимым контентом. Не добавляйте FAQPage автоматически.

## 6. Безопасность

WordPress HTML рендерится как trusted CMS content. Если писать могут непроверенные роли/плагины, добавьте sanitization на сервере или ограничьте HTML на стороне WordPress. Никогда не принимайте произвольный HTML от посетителя и не прокидывайте его в `dangerouslySetInnerHTML`.

Write credentials не нужны для frontend routes. Они используются только server-side draft script/CI secret и только по HTTPS.

## 7. Проверка

В target-проекте обязательны его собственные lint/typecheck/test/build. Затем реальный браузер:

- `/blog`;
- один `/blog/<slug>`;
- одна `/blog/category/<slug>`;
- `/sitemap.xml` и `/robots.txt`;
- desktop + mobile;
- console/network errors;
- canonical/OG/JSON-LD в HTML;
- изображение и alt;
- controlled error при недоступной CMS.

Отдельно проверьте draft через `scripts/wp-preflight.mjs`, затем `scripts/wp-create-draft.mjs article.json`. Публичная публикация не входит в автоматический шаг.
