import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")


def text_files():
    skip = {".git", "__pycache__", "media", ".venv", "build", "dist"}
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & skip) and p.suffix in {".py", ".js", ".css", ".html", ".md", ".json", ".svg", ".txt", ".sh", ".example"}:
            yield p


class EnglishCoverageTests(unittest.TestCase):
    def test_no_korean_anywhere(self):
        bad = [str(p.relative_to(ROOT)) for p in text_files() if HANGUL.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [])

    def test_html_declares_english(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)

    def test_error_messages_are_complete_english_sentences(self):
        from otaku_gallery.errors import MESSAGES
        for code, msg in MESSAGES.items():
            self.assertTrue(msg.isascii() and msg[0].isupper() and msg.endswith("."), code)

    def test_manifest_and_prompt_are_english(self):
        data = json.loads((ROOT / "data" / "gallery.json").read_text(encoding="utf-8"))
        for item in data["items"]:
            for key in ("title", "description", "alt", "creator", "source_label"):
                self.assertTrue(item[key].isascii(), (item["id"], key))
                self.assertFalse(HANGUL.search(item[key]))


class FrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_scripts_parse(self):
        for name in ("app.js", "research.js", "strings.js"):
            done = subprocess.run(["node", "--check", str(ROOT / "web" / name)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_no_remote_resources_or_inline_handlers(self):
        for name in ("index.html", "app.css", "research.css"):
            text = (ROOT / "web" / name).read_text(encoding="utf-8")
            self.assertFalse(re.search(r"(?:src|href)=[\"']https?:", text), name)
            self.assertNotIn("@import", text)
            self.assertNotRegex(text, r"\son[a-z]+=")

    def test_dom_text_uses_textcontent(self):
        for name in ("app.js", "research.js"):
            js = (ROOT / "web" / name).read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", js)
            self.assertNotIn("insertAdjacentHTML", js)
            self.assertNotIn("document.write", js)
            self.assertNotIn("eval(", js)

    def test_strings_cover_every_dynamic_label(self):
        strings = (ROOT / "web" / "strings.js").read_text(encoding="utf-8")
        research = (ROOT / "web" / "research.js").read_text(encoding="utf-8")
        for ref in sorted(set(re.findall(r"\bS\.([A-Za-z]+)", research))):
            self.assertIn(ref + ":", strings, ref)


if __name__ == "__main__":
    unittest.main()
