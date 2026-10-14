#!/usr/bin/env node
import fs from "node:fs/promises";
import { configFromEnv, createDraft, preflight } from "./lib/wordpress-rest.mjs";

const articlePath = process.argv[2];
if (!articlePath || process.argv.length !== 3) {
  console.error("Usage: node scripts/wp-create-draft.mjs path/to/article.json");
  process.exit(2);
}

try {
  const payload = JSON.parse(await fs.readFile(articlePath, "utf8"));
  const config = configFromEnv(process.env);
  await preflight(config);
  const result = await createDraft(config, payload);
  console.log(JSON.stringify({ ok: true, ...result }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
  process.exitCode = 1;
}
