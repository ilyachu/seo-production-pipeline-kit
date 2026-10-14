#!/usr/bin/env node
import { configFromEnv, preflight } from "./lib/wordpress-rest.mjs";

const publicOnly = process.argv.includes("--public-only");
try {
  const config = configFromEnv(process.env, { publicOnly });
  const result = await preflight(config, { publicOnly });
  console.log(JSON.stringify({ ok: true, base_url: config.baseUrl, ...result }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
  process.exitCode = 1;
}
