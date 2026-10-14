"""Customer-facing HTML must remain self-contained and free of operator notes."""

from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "seo-agent-map.html"
SOURCE = ROOT / "docs" / "seo-agent-map.md"


class PublicPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.review_controls = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if values.get("data-am") in {"reply", "remark", "copy"}:
            self.review_controls += 1


class PublicArtifactTest(unittest.TestCase):
    def test_html_has_no_private_navigation_or_review_controls(self) -> None:
        page = HTML.read_text()
        visible = page.split('<textarea id="am-source"', 1)[0]
        parser = PublicPageParser()
        parser.feed(visible)

        self.assertEqual(parser.links, ["https://github.com/ilyachu/seo-blog-starter"])
        self.assertEqual(parser.review_controls, 0)
        self.assertNotIn('<p class="am-colophon">', visible)
        self.assertNotIn('href="../', visible)
        self.assertIn("SEO-конвейер: от аудита до публикации", visible)

    def test_embedded_markdown_matches_source(self) -> None:
        page = HTML.read_text()
        match = re.search(
            r'<textarea id="am-source" hidden readonly aria-hidden="true">(.*?)</textarea>',
            page,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(unescape(match.group(1)), SOURCE.read_text())
        self.assertTrue((ROOT / "docs" / "GETTING_STARTED.md").is_file())


if __name__ == "__main__":
    unittest.main()
