#!/usr/bin/env python3
"""Dependency-free structural validator for this skill pack."""

from __future__ import annotations

import json
import re
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REQUIRED_HEADINGS = (
    "## Когда использовать",
    "## Вход",
    "## Выход",
    "## Самостоятельный режим",
    "## Режим конвейера",
    "## Проверка",
)
FORBIDDEN_CLAIMS = ("+17,4%", "+5,8%", "в 2–4 раза чаще", "0,5–2,5%")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if match:
            result[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return result


def local_links(text: str) -> list[str]:
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    return [link.split("#", 1)[0] for link in links if link and "://" not in link and not link.startswith("#")]


def validate() -> list[str]:
    errors: list[str] = []
    skill_dirs = sorted(path for path in SKILLS.iterdir() if path.is_dir())
    if len(skill_dirs) < 12:
        errors.append(f"expected at least 12 skills, found {len(skill_dirs)}")

    names: set[str] = set()
    for skill_dir in skill_dirs:
        entry = skill_dir / "SKILL.md"
        if not entry.exists():
            errors.append(f"{skill_dir.relative_to(ROOT)}: missing SKILL.md")
            continue
        text = entry.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        name = fm.get("name", "")
        description = fm.get("description", "")
        rel = entry.relative_to(ROOT)
        if name != skill_dir.name:
            errors.append(f"{rel}: name '{name}' must match folder '{skill_dir.name}'")
        if name in names:
            errors.append(f"{rel}: duplicate skill name '{name}'")
        names.add(name)
        if len(description) < 50 or "Use when" not in description:
            errors.append(f"{rel}: description must explain purpose and include 'Use when' triggers")
        for heading in REQUIRED_HEADINGS:
            if heading not in text:
                errors.append(f"{rel}: missing heading '{heading}'")
        for link in local_links(text):
            if not (skill_dir / link).resolve().exists():
                errors.append(f"{rel}: broken local link '{link}'")
        for claim in FORBIDDEN_CLAIMS:
            if claim in text:
                errors.append(f"{rel}: unsupported numeric claim '{claim}'")

    publisher = SKILLS / "seo-wordpress-publisher" / "SKILL.md"
    if publisher.exists():
        text = publisher.read_text(encoding="utf-8").lower()
        if "status=draft" not in text or "явного подтверждения" not in text:
            errors.append("seo-wordpress-publisher: must default to status=draft and require explicit approval")

    schema_path = ROOT / "contracts" / "article-package.schema.json"
    try:
        json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"contracts/article-package.schema.json: {exc}")
    root_client = ROOT / "scripts" / "wordstat_client.py"
    installed_client = SKILLS / "seo-wordstat-collector" / "scripts" / "wordstat_client.py"
    if not installed_client.exists():
        errors.append("seo-wordstat-collector: missing bundled scripts/wordstat_client.py")
    elif hashlib.sha256(root_client.read_bytes()).digest() != hashlib.sha256(installed_client.read_bytes()).digest():
        errors.append("seo-wordstat-collector: bundled wordstat client differs from root script")
    root_contract = ROOT / "contracts" / "pipeline.md"
    installed_contract = SKILLS / "seo-pipeline-orchestrator" / "references" / "pipeline.md"
    if not installed_contract.exists():
        errors.append("seo-pipeline-orchestrator: missing bundled references/pipeline.md")
    elif hashlib.sha256(root_contract.read_bytes()).digest() != hashlib.sha256(installed_contract.read_bytes()).digest():
        errors.append("seo-pipeline-orchestrator: bundled pipeline contract differs from root contract")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Skill pack validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    count = len([path for path in SKILLS.iterdir() if path.is_dir()])
    print(f"OK: {count} skills, frontmatter, contracts, links and safety rules validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
