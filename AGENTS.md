# SEO Production Pipeline: agent contract

Read `MINI_PRD.md`, `SOURCE_INVENTORY.md`, and the relevant skill before work.

- Keep each agent usable alone. Record explicit inputs, outputs, evidence, missing data, and status.
- Run the full sequence only through the orchestrator and its quality gates.
- Treat current API output and the live site as truth. Old reports are history.
- Do not invent frequency, intent, ranking, source claims, or publication success.
- Do not put tokens, service-account files, client records, databases, or raw reports in Git or model prompts.
- Keep WordPress in draft mode until the article is reviewed. Use a clean release worktree for each custom-site integration.
- Before a production change, capture exact live SHA, data path, backup, rollback path, and expected URL.
- After a change, verify HTTP, rendered desktop/mobile page, canonical, robots, sitemap, OG image, and source references.
- Preserve source attribution and licenses when importing material. Never overwrite changes in source repositories.
- Use concise STE-100 language: outcome, evidence, next step or blocker.
