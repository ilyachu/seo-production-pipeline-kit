#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const required = [
  "README.md",
  ".env.example",
  "skills/wordpress-seo-blog-integrator/SKILL.md",
  "template/next-app-router/lib/wordpress.ts",
  "template/next-app-router/config/blog.ts",
  "template/next-app-router/components/blog/BlogFrame.tsx",
  "template/next-app-router/components/blog/BlogList.tsx",
  "template/next-app-router/components/blog/BlogPost.tsx",
  "template/next-app-router/components/blog/BlogTools.tsx",
  "template/next-app-router/app/blog/page.tsx",
  "template/next-app-router/app/blog/[slug]/page.tsx",
  "template/next-app-router/app/blog/category/[slug]/page.tsx",
  "template/next-app-router/app/blog/blog.css",
  "scripts/wp-preflight.mjs",
  "scripts/wp-create-draft.mjs",
];
const errors = required.filter((rel) => !fs.existsSync(path.join(root, rel))).map((rel) => `missing ${rel}`);
const env = fs.readFileSync(path.join(root, ".env.example"), "utf8");
if (!env.includes("WORDPRESS_APPLICATION_PASSWORD=")) errors.push("missing Application Password placeholder");
if (/WORDPRESS_APPLICATION_PASSWORD=\S+/.test(env)) errors.push(".env.example contains a non-empty password");
const createDraft = fs.readFileSync(path.join(root, "scripts/wp-create-draft.mjs"), "utf8");
const lib = fs.readFileSync(path.join(root, "scripts/lib/wordpress-rest.mjs"), "utf8");
if (!lib.includes('status: "draft"') || !lib.includes("only creates status=draft")) errors.push("draft-only guard missing");
if (createDraft.includes("process.argv[3]")) errors.push("credentials must not be accepted in argv");
for (const rel of ["template/next-app-router/app/blog/page.tsx", "template/next-app-router/app/blog/[slug]/page.tsx", "template/next-app-router/app/blog/category/[slug]/page.tsx"]) {
  const source = fs.readFileSync(path.join(root, rel), "utf8");
  if (!source.includes('.replace(/</g, "\\\\u003c")')) errors.push(`${rel}: JSON-LD must escape '<'`);
}
const wpTemplate = fs.readFileSync(path.join(root, "template/next-app-router/lib/wordpress.ts"), "utf8");
if (!wpTemplate.includes('status: result.status')) errors.push("WordPress template must preserve fetch status");
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`OK: ${required.length} required files, secret placeholders and draft-only guard validated`);
