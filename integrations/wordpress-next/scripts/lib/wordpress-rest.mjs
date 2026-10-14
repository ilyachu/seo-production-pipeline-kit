import fs from "node:fs/promises";
import path from "node:path";

export function normalizeBaseUrl(value) {
  if (!value) throw new Error("WORDPRESS_BASE_URL is required");
  const url = new URL(value);
  if (url.protocol !== "https:") throw new Error("WORDPRESS_BASE_URL must use HTTPS");
  url.pathname = url.pathname.replace(/\/+$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

export function configFromEnv(env = process.env, { publicOnly = false } = {}) {
  const baseUrl = normalizeBaseUrl(env.WORDPRESS_BASE_URL);
  const config = { baseUrl, apiUrl: `${baseUrl}/wp-json/wp/v2` };
  if (publicOnly) return config;
  if (!env.WORDPRESS_USERNAME) throw new Error("WORDPRESS_USERNAME is required for authenticated checks");
  if (!env.WORDPRESS_APPLICATION_PASSWORD) throw new Error("WORDPRESS_APPLICATION_PASSWORD is required for authenticated checks");
  return {
    ...config,
    username: env.WORDPRESS_USERNAME,
    applicationPassword: env.WORDPRESS_APPLICATION_PASSWORD,
  };
}

export function authHeader(config) {
  const token = Buffer.from(`${config.username}:${config.applicationPassword}`, "utf8").toString("base64");
  return `Basic ${token}`;
}

export function safeHttpError(response, body = "") {
  const compact = String(body).replace(/\s+/g, " ").slice(0, 240);
  return new Error(`WordPress HTTP ${response.status}${compact ? `: ${compact}` : ""}`);
}

export async function requestJson(url, options = {}, fetchImpl = fetch) {
  const response = await fetchImpl(url, options);
  const text = await response.text();
  if (!response.ok) throw safeHttpError(response, text);
  return text ? JSON.parse(text) : null;
}

export async function preflight(config, { publicOnly = false, fetchImpl = fetch } = {}) {
  await requestJson(`${config.baseUrl}/wp-json/`, {}, fetchImpl);
  const result = { public_api: "ok", authenticated_api: "skipped" };
  if (!publicOnly) {
    const me = await requestJson(
      `${config.apiUrl}/users/me?context=edit`,
      { headers: { Authorization: authHeader(config) } },
      fetchImpl,
    );
    result.authenticated_api = "ok";
    result.user = { id: me.id, name: me.name, roles: me.roles ?? [] };
  }
  return result;
}

export async function findPostBySlug(config, slug, fetchImpl = fetch) {
  const url = new URL(`${config.apiUrl}/posts`);
  url.searchParams.set("slug", slug);
  url.searchParams.set("context", "edit");
  url.searchParams.set("status", "any");
  const posts = await requestJson(
    url,
    { headers: { Authorization: authHeader(config) } },
    fetchImpl,
  );
  return posts[0] ?? null;
}

function mediaType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return ({ ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif" })[ext];
}

export function contentDispositionFilename(filePath) {
  const raw = path.basename(filePath).replace(/[\r\n"]/g, "_");
  const ascii = raw.replace(/[^\x20-\x7E]/g, "_");
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(raw)}`;
}

export async function uploadMedia(config, filePath, alt, fetchImpl = fetch) {
  const contentType = mediaType(filePath);
  if (!contentType) throw new Error("featured_image must be PNG, JPG, WEBP or GIF");
  const bytes = await fs.readFile(filePath);
  const media = await requestJson(
    `${config.apiUrl}/media`,
    {
      method: "POST",
      headers: {
        Authorization: authHeader(config),
        "Content-Disposition": contentDispositionFilename(filePath),
        "Content-Type": contentType,
      },
      body: bytes,
    },
    fetchImpl,
  );
  if (alt) {
    await requestJson(
      `${config.apiUrl}/media/${media.id}`,
      {
        method: "POST",
        headers: { Authorization: authHeader(config), "Content-Type": "application/json" },
        body: JSON.stringify({ alt_text: alt }),
      },
      fetchImpl,
    );
  }
  return media;
}

export function normalizeDraftPayload(payload, featuredMedia = 0) {
  if (payload.status && payload.status !== "draft") {
    throw new Error("This starter only creates status=draft");
  }
  for (const field of ["title", "slug", "content"]) {
    if (!payload[field] || typeof payload[field] !== "string") throw new Error(`Article field '${field}' is required`);
  }
  return {
    title: payload.title,
    slug: payload.slug,
    content: payload.content,
    excerpt: payload.excerpt ?? "",
    status: "draft",
    featured_media: featuredMedia || undefined,
    categories: Array.isArray(payload.categories) ? payload.categories : [],
    tags: Array.isArray(payload.tags) ? payload.tags : [],
  };
}

export async function createDraft(config, payload, fetchImpl = fetch) {
  const existing = await findPostBySlug(config, payload.slug, fetchImpl);
  if (existing) throw new Error(`A WordPress post with slug '${payload.slug}' already exists (id ${existing.id})`);
  let media = null;
  if (payload.featured_image) media = await uploadMedia(config, payload.featured_image, payload.alt ?? "", fetchImpl);
  const draft = normalizeDraftPayload(payload, media?.id ?? 0);
  const created = await requestJson(
    `${config.apiUrl}/posts`,
    {
      method: "POST",
      headers: { Authorization: authHeader(config), "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    },
    fetchImpl,
  );
  const verified = await requestJson(
    `${config.apiUrl}/posts/${created.id}?context=edit`,
    { headers: { Authorization: authHeader(config) } },
    fetchImpl,
  );
  if (verified.status !== "draft" || verified.slug !== payload.slug) {
    throw new Error(`Draft read-back verification failed: post ${created.id} has status '${verified.status}' and slug '${verified.slug}', expected 'draft' and '${payload.slug}'`);
  }
  return {
    post_id: verified.id,
    status: verified.status,
    slug: verified.slug,
    edit_link: verified.link ?? null,
    media_id: media?.id ?? null,
    verified: true,
  };
}
