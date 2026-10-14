#!/usr/bin/env python3
"""Deterministic editorial SVG covers for SEO articles.

Layout idea, not a copy: writer_rerait_moi/enrichment/local_svg_covers.py
at 35e3fde3e793cb56db17bd115ce55616d12944c0. No client branding or copy.

Python standard library only. No network and no credentials.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path

WIDTH = 1600
HEIGHT = 900
# Contract for tests: every text glyph box stays inside this rectangle.
SAFE_LEFT = 112
SAFE_RIGHT = 1488
SAFE_TOP = 96
SAFE_BOTTOM = 824
TEXT_WIDTH = SAFE_RIGHT - SAFE_LEFT

ASCENT = 0.95
DESCENT = 0.30

INK = "#1C1916"
PAPER = "#FBF6EE"
FIELD = "#E7DCCB"
GRID = "#DDD0BE"
MUTED = "#5E584F"
DEFAULT_ACCENT = "#8C3D2F"
DEFAULT_SITE = "Редакция"

SERIF = "Georgia, 'Times New Roman', Times, serif"
SANS = "Arial, Helvetica, sans-serif"

ACCENT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
WHITESPACE_RE = re.compile(r"\s+")

TITLE_SIZES = (84, 72, 60, 50, 42, 34)
TITLE_MAX_LINES = 6
SUBTITLE_SIZES = (32, 28, 24)
SUBTITLE_MAX_LINES = 3
KICKER_SIZES = (22, 18, 14)


def _clean(value: str, limit: int) -> str:
    kept = []
    for char in value or "":
        if char in "\n\t" or ord(char) >= 32:
            kept.append(char)
    text = WHITESPACE_RE.sub(" ", "".join(kept)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,;:.") + "…"


def glyph_units(char: str) -> float:
    """Upper bound in em. Cyrillic capitals can be nearly a full em."""

    if char == " ":
        return 0.5
    return 1.0


def text_width(text: str, font_size: int) -> int:
    units = sum(glyph_units(char) for char in text)
    return math.ceil(units * font_size)


def _ascent(font_size: int) -> int:
    return math.ceil(font_size * ASCENT)


def _descent(font_size: int) -> int:
    return math.ceil(font_size * DESCENT)


def _block_height(line_count: int, font_size: int, gap: int) -> int:
    if line_count <= 0:
        return 0
    line = _ascent(font_size) + _descent(font_size)
    return line_count * line + (line_count - 1) * gap


def _wrap_unlimited(text: str, font_size: int, max_width: int) -> list[str]:
    if not text:
        return []
    if max_width < font_size:
        raise ValueError("cover width is smaller than one glyph")
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if text_width(word, font_size) <= max_width:
            candidate = word if not current else f"{current} {word}"
            if text_width(candidate, font_size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
            continue
        if current:
            lines.append(current)
            current = ""
        chunk = ""
        for char in word:
            candidate = f"{chunk}{char}"
            if text_width(candidate, font_size) <= max_width:
                chunk = candidate
                continue
            if chunk:
                lines.append(chunk)
            chunk = char
        current = chunk
    if current:
        lines.append(current)
    return lines


def _fit_ellipsis(text: str, font_size: int, max_width: int) -> str:
    mark = "…"
    raw = text.rstrip()
    if text_width(raw, font_size) <= max_width:
        return raw
    trimmed = raw
    while trimmed and text_width(f"{trimmed}{mark}", font_size) > max_width:
        trimmed = trimmed[:-1].rstrip()
    if not trimmed:
        return mark if text_width(mark, font_size) <= max_width else ""
    return f"{trimmed}{mark}"


def _clamp_lines(lines: list[str], font_size: int, max_width: int, max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    bare = kept[-1].rstrip(" ,;:.")
    marked = f"{bare}…"
    if text_width(marked, font_size) <= max_width:
        kept[-1] = marked
    else:
        kept[-1] = _fit_ellipsis(bare, font_size, max_width)
    return [line for line in kept if line]


def wrap_lines(text: str, *, font_size: int, max_width: int, max_lines: int) -> list[str]:
    return _clamp_lines(_wrap_unlimited(text, font_size, max_width), font_size, max_width, max_lines)


def _validate_accent(accent: str) -> str:
    if not ACCENT_RE.fullmatch(accent or ""):
        raise ValueError("accent must be a #RRGGBB color")
    return accent


def build_alt(title: str, subtitle: str, site_name: str) -> str:
    parts = [f"Обложка статьи «{title}»"]
    if site_name:
        parts.append(f"издание {site_name}")
    if subtitle:
        parts.append(subtitle)
    return ". ".join(parts)


def build_prompt(title: str, subtitle: str, site_name: str, accent: str) -> str:
    subtitle_text = subtitle or "без подзаголовка"
    return (
        "Редакционная SVG-обложка 1600×900. Тёплое бумажное поле, тонкая сетка, "
        f"узкая чернильная рамка, одна акцентная полоса {accent}. "
        f"Подпись издания: {site_name or 'без названия'}. "
        f"Крупный заголовок: {title}. Подзаголовок: {subtitle_text}. "
        "Только типографика. Без маскота, логотипа, фотографии и внешних запросов."
    )


def _pick_pair(
    title: str,
    subtitle: str,
    max_width: int,
    max_height: int,
) -> tuple[list[str], int, list[str], int]:
    gap_between = 36
    for title_size in TITLE_SIZES:
        title_gap = max(8, title_size // 8)
        title_lines = _wrap_unlimited(title, title_size, max_width)
        if not title_lines or len(title_lines) > TITLE_MAX_LINES:
            continue
        title_height = _block_height(len(title_lines), title_size, title_gap)
        remain = max_height - title_height - (gap_between if subtitle else 0)
        if remain < 0:
            continue
        if not subtitle:
            return title_lines, title_size, [], 0
        for subtitle_size in SUBTITLE_SIZES:
            subtitle_gap = max(6, subtitle_size // 8)
            subtitle_lines = _wrap_unlimited(subtitle, subtitle_size, max_width)
            if len(subtitle_lines) > SUBTITLE_MAX_LINES:
                continue
            if _block_height(len(subtitle_lines), subtitle_size, subtitle_gap) <= remain:
                return title_lines, title_size, subtitle_lines, subtitle_size
    title_size = TITLE_SIZES[-1]
    subtitle_size = SUBTITLE_SIZES[-1]
    title_lines = wrap_lines(title, font_size=title_size, max_width=max_width, max_lines=TITLE_MAX_LINES)
    subtitle_lines = (
        wrap_lines(subtitle, font_size=subtitle_size, max_width=max_width, max_lines=SUBTITLE_MAX_LINES)
        if subtitle
        else []
    )
    return title_lines, title_size, subtitle_lines, subtitle_size


def _kicker(site_name: str, max_width: int) -> tuple[str, int]:
    if not site_name:
        return "", 0
    for size in KICKER_SIZES:
        lines = _wrap_unlimited(site_name, size, max_width)
        if len(lines) == 1:
            return lines[0], size
    return wrap_lines(site_name, font_size=KICKER_SIZES[-1], max_width=max_width, max_lines=1)[0], KICKER_SIZES[-1]


def _text(
    *,
    x: int,
    y: int,
    size: int,
    weight: int,
    fill: str,
    family: str,
    role: str,
    content: str,
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{html.escape(fill, quote=True)}" '
        f'font-family="{html.escape(family, quote=True)}" font-size="{size}" '
        f'font-weight="{weight}" data-role="{role}">{html.escape(content, quote=True)}</text>'
    )


def _place(lines: list[str], size: int, cursor: int, gap: int, weight: int, fill: str, family: str, role: str) -> tuple[list[str], int]:
    elements: list[str] = []
    for line in lines:
        baseline = cursor + _ascent(size)
        elements.append(
            _text(x=SAFE_LEFT, y=baseline, size=size, weight=weight, fill=fill, family=family, role=role, content=line)
        )
        cursor = baseline + _descent(size) + gap
    if lines:
        cursor -= gap
    return elements, cursor


def render_svg(
    title: str,
    subtitle: str = "",
    site_name: str = DEFAULT_SITE,
    accent: str = DEFAULT_ACCENT,
) -> str:
    clean_title = _clean(title, 400)
    if not clean_title:
        raise ValueError("title is empty")
    clean_subtitle = _clean(subtitle, 240)
    clean_site = _clean(site_name, 80)
    color = _validate_accent(accent)
    alt = build_alt(clean_title, clean_subtitle, clean_site)
    prompt = build_prompt(clean_title, clean_subtitle, clean_site, color)
    meta = {
        "role": "seo-article-cover",
        "generator": "local-editorial-svg",
        "width": WIDTH,
        "height": HEIGHT,
        "alt": alt,
        "prompt": prompt,
        "origin": (
            "Independent editorial SVG inspired by the local renderer idea. "
            "No client branding or copy was used."
        ),
    }
    meta_text = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    label, label_size = _kicker(clean_site, TEXT_WIDTH)
    label_height = _block_height(1 if label else 0, label_size or 0, 0)
    label_gap = 32 if label else 0
    budget = SAFE_BOTTOM - SAFE_TOP - label_height - label_gap
    title_lines, title_size, subtitle_lines, subtitle_size = _pick_pair(
        clean_title, clean_subtitle, TEXT_WIDTH, budget
    )
    title_gap = max(8, title_size // 8)
    subtitle_gap = max(6, subtitle_size // 8) if subtitle_lines else 0

    cursor = SAFE_TOP
    texts: list[str] = []
    if label:
        placed, cursor = _place([label], label_size, cursor, 0, 700, INK, SANS, "site")
        texts.extend(placed)
        cursor += label_gap
    placed, cursor = _place(title_lines, title_size, cursor, title_gap, 700, INK, SERIF, "title")
    texts.extend(placed)
    if subtitle_lines:
        cursor += 36
        placed, cursor = _place(
            subtitle_lines, subtitle_size, cursor, subtitle_gap, 400, MUTED, SANS, "subtitle"
        )
        texts.extend(placed)

    rule = ""
    rule_y = SAFE_BOTTOM - 10
    if cursor + 28 < rule_y:
        rule = (
            f'<rect x="{SAFE_LEFT}" y="{rule_y}" width="168" height="4" fill="{html.escape(color, quote=True)}"/>'
        )

    grid = []
    for pos in range(80, WIDTH, 80):
        grid.append(f'<path d="M{pos} 0V{HEIGHT}"/>')
    for pos in range(80, HEIGHT, 80):
        grid.append(f'<path d="M0 {pos}H{WIDTH}"/>')

    body = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">
  <title>{html.escape(alt, quote=True)}</title>
  <desc>{html.escape(prompt, quote=True)}</desc>
  <metadata>{html.escape(meta_text, quote=True)}</metadata>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{FIELD}"/>
  <g fill="none" stroke="{GRID}" stroke-width="1">
    {"".join(grid)}
  </g>
  <rect x="48" y="48" width="1504" height="804" fill="{PAPER}" stroke="{INK}" stroke-width="2"/>
  <rect x="48" y="48" width="12" height="804" fill="{html.escape(color, quote=True)}"/>
  {"".join(texts)}
  {rule}
</svg>
"""
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a deterministic editorial SVG article cover.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--site-name", default=DEFAULT_SITE)
    parser.add_argument("--accent", default=DEFAULT_ACCENT)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        svg = render_svg(args.title, subtitle=args.subtitle, site_name=args.site_name, accent=args.accent)
    except ValueError as exc:
        print(f"render_svg_cover: {exc}", file=sys.stderr)
        return 2
    destination = Path(args.output)
    destination.write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
