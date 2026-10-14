# WordPress credentials

## Чтение

Для опубликованных `posts`, `categories` и `media` REST API обычно публичен. Frontend получает только `WORDPRESS_BASE_URL` на сервере.

## Запись draft

1. В WordPress создайте отдельного пользователя с минимальной ролью, достаточной для статей и загрузки медиа.
2. В профиле пользователя создайте отдельный Application Password с понятным именем, например `seo-blog-starter`.
3. Передавайте логин и пароль через secret manager или локальный `.env`, не через Git/чат.
4. Убедитесь, что CMS работает по HTTPS. Не отключайте SSL-проверку ради обхода ошибки.
5. Запустите `node scripts/wp-preflight.mjs`.
6. Создайте только draft: `node scripts/wp-create-draft.mjs path/to/article.json`.
7. Откройте draft в админке, проверьте вёрстку, ссылки, изображение, SEO-поля и только затем публикуйте вручную или отдельным подтверждённым действием.

Переменные:

```text
WORDPRESS_BASE_URL=https://cms.example.com
WORDPRESS_USERNAME=seo-editor
WORDPRESS_APPLICATION_PASSWORD=xxxx xxxx xxxx xxxx
```

Запрещено:

- `NEXT_PUBLIC_WORDPRESS_APPLICATION_PASSWORD`;
- password в query string или CLI argv;
- хранить Authorization header в логах;
- использовать общий admin вместо отдельной учётки;
- повторять POST после timeout, не проверив, создался ли объект;
- отправлять `status=publish` без явного подтверждения.
