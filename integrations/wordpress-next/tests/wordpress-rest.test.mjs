import assert from "node:assert/strict";
import test from "node:test";
import { configFromEnv, contentDispositionFilename, normalizeBaseUrl, normalizeDraftPayload, safeHttpError } from "../scripts/lib/wordpress-rest.mjs";

test("normalizeBaseUrl requires HTTPS and removes trailing slash", () => {
  assert.equal(normalizeBaseUrl("https://cms.example.com/"), "https://cms.example.com");
  assert.throws(() => normalizeBaseUrl("http://cms.example.com"), /HTTPS/);
});

test("public config does not require write credentials", () => {
  assert.deepEqual(configFromEnv({ WORDPRESS_BASE_URL: "https://cms.example.com" }, { publicOnly: true }), {
    baseUrl: "https://cms.example.com",
    apiUrl: "https://cms.example.com/wp-json/wp/v2",
  });
});

test("draft payload is always draft and rejects publish", () => {
  const result = normalizeDraftPayload({ title: "T", slug: "t", content: "<p>x</p>" });
  assert.equal(result.status, "draft");
  assert.throws(() => normalizeDraftPayload({ title: "T", slug: "t", content: "x", status: "publish" }), /only creates/);
});

test("HTTP error never includes authorization data", () => {
  const error = safeHttpError({ status: 401 }, "rest_not_logged_in");
  assert.match(error.message, /401/);
  assert.doesNotMatch(error.message, /Basic|PASSWORD/);
});

test("media header supports Cyrillic filenames with an ASCII fallback", () => {
  const header = contentDispositionFilename("/tmp/схема выбора.png");
  assert.match(header, /^attachment; filename="[\x20-\x7E]+"; filename\*=UTF-8''/);
  assert.match(header, /%D1%81%D1%85%D0%B5%D0%BC%D0%B0/);
  assert.doesNotThrow(() => new Headers({ "Content-Disposition": header }));
});
