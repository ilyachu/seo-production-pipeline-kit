"""Обложка SVG: разбор XML, экранирование, детерминизм и поля текста.

Запуск: python3 -m unittest tests/test_render_svg_cover.py
Сети и учётных данных нет.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import render_svg_cover as cover  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
# Independent of the renderer: same safe rectangle and 1em / 0.5em ceiling.
SAFE_LEFT = 112
SAFE_RIGHT = 1488
SAFE_TOP = 96
SAFE_BOTTOM = 824

DEMO = {
    "title": "Как собрать поисковую статью из проверяемых фактов, а не из списка ключевых слов",
    "subtitle": "Редакционная обложка: крупный заголовок, бумажное поле и одна акцентная полоса",
    "site_name": "Полевая редакция",
    "accent": "#8C3D2F",
}


def parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg.encode("utf-8"))


def ceiling_width(text: str, font_size: int) -> int:
    units = sum(0.5 if char == " " else 1.0 for char in text)
    return math.ceil(units * font_size)


class RenderSvgCoverTest(unittest.TestCase):
    def test_xml_canvas_and_metadata(self):
        svg = cover.render_svg("Поисковая статья", subtitle="Короткий тезис", site_name="Журнал", accent="#225544")
        root = parse_svg(svg)
        self.assertEqual(root.tag, f"{SVG}svg")
        self.assertEqual(root.get("width"), "1600")
        self.assertEqual(root.get("height"), "900")
        self.assertEqual(root.get("viewBox"), "0 0 1600 900")
        self.assertTrue((root.findtext(f"{SVG}title") or "").startswith("Обложка статьи"))
        self.assertIn("1600×900", root.findtext(f"{SVG}desc") or "")
        meta = json.loads(root.findtext(f"{SVG}metadata") or "")
        self.assertEqual(meta["generator"], "local-editorial-svg")
        self.assertEqual(meta["width"], 1600)
        self.assertEqual(meta["height"], 900)
        self.assertEqual(meta["alt"], root.findtext(f"{SVG}title"))
        self.assertEqual(meta["prompt"], root.findtext(f"{SVG}desc"))
        self.assertIn("Поисковая статья", meta["alt"])
        self.assertIn("#225544", meta["prompt"])
        self.assertEqual(svg.count("http://"), 1)
        self.assertIn("http://www.w3.org/2000/svg", svg)
        self.assertNotIn("https://", svg)
        self.assertNotIn("href=", svg)
        self.assertNotRegex(svg.lower(), r"api[_-]?key|token|password|secret")

    def test_escapes_markup_in_text_and_metadata(self):
        title = 'A & B <script> "кавычки"'
        subtitle = "C > D & E"
        site = "Сайт <бренд>"
        svg = cover.render_svg(title, subtitle=subtitle, site_name=site, accent="#ABCDEF")
        self.assertNotIn("<script>", svg)
        self.assertIn("&amp;", svg)
        self.assertIn("&lt;", svg)
        self.assertIn("&gt;", svg)
        self.assertIn("&quot;", svg)
        root = parse_svg(svg)
        texts = [node.text or "" for node in root.iter(f"{SVG}text")]
        self.assertNotIn("script", {node.tag for node in root.iter()})
        titled = [node.text or "" for node in root.iter(f"{SVG}text") if node.get("data-role") == "title"]
        self.assertEqual(" ".join(titled), title)
        self.assertIn(subtitle, texts)
        self.assertIn(site, texts)
        self.assertEqual(root.findtext(f"{SVG}title"), cover.build_alt(title, subtitle, site))
        meta = json.loads(root.findtext(f"{SVG}metadata") or "")
        self.assertEqual(meta["alt"], root.findtext(f"{SVG}title"))
        self.assertIn(title, meta["prompt"])

    def test_same_input_is_byte_stable(self):
        kwargs = {
            "title": "Один и тот же заголовок",
            "subtitle": "Один и тот же подзаголовок",
            "site_name": "Одно издание",
            "accent": "#123456",
        }
        self.assertEqual(cover.render_svg(**kwargs), cover.render_svg(**kwargs))

    def test_long_cyrillic_stays_inside_margins(self):
        title = "Ширина кириллического заголовка " * 12
        subtitle = "Подзаголовок тоже длинный и должен остаться в поле. " * 6
        site = "Очень длинное название издания без переноса за край макета"
        svg = cover.render_svg(title, subtitle=subtitle, site_name=site, accent="#8C3D2F")
        root = parse_svg(svg)
        nodes = list(root.iter(f"{SVG}text"))
        self.assertGreaterEqual(len(nodes), 3)
        seen_ellipsis = False
        for node in nodes:
            content = node.text or ""
            self.assertTrue(content)
            x = int(node.get("x") or "0")
            y = int(node.get("y") or "0")
            size = int(node.get("font-size") or "0")
            self.assertGreaterEqual(x, SAFE_LEFT)
            self.assertLessEqual(x + ceiling_width(content, size), SAFE_RIGHT)
            self.assertGreaterEqual(y - math.ceil(size * 0.95), SAFE_TOP)
            self.assertLessEqual(y + math.ceil(size * 0.30), SAFE_BOTTOM)
            if content.endswith("…"):
                seen_ellipsis = True
        self.assertTrue(seen_ellipsis)

    def test_cli_writes_file_and_rejects_bad_accent(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "cover.svg"
            code = cover.main(
                [
                    "--title",
                    "Заголовок & проверка",
                    "--subtitle",
                    "Подзаголовок",
                    "--site-name",
                    "Издание",
                    "--accent",
                    "#0A0A0A",
                    "--output",
                    str(destination),
                ]
            )
            self.assertEqual(code, 0)
            parse_svg(destination.read_text(encoding="utf-8"))
        self.assertEqual(
            cover.main(["--title", "X", "--accent", "red", "--output", "unused.svg"]),
            2,
        )
        with self.assertRaises(ValueError):
            cover.render_svg("   ")

    def test_checked_in_demo_matches_renderer(self):
        expected = cover.render_svg(
            DEMO["title"],
            subtitle=DEMO["subtitle"],
            site_name=DEMO["site_name"],
            accent=DEMO["accent"],
        )
        actual = (ROOT / "examples" / "cover-demo.svg").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
