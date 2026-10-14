# Integration contract

- Inspect the host repository and its instructions before editing.
- Reuse the host layout, tokens, components and package manager.
- Copy the smallest required blog slice; do not replace unrelated routes or shell components.
- Keep WordPress read configuration server-side. Keep write credentials only in secret env.
- Use HTTPS. Default every write to `draft`; publishing requires explicit approval outside this starter.
- Preserve canonical, metadata, Article/CollectionPage JSON-LD, sitemap/robots, responsive layout and accessibility.
- Run the host lint/typecheck/build/tests and real browser QA after integration.
