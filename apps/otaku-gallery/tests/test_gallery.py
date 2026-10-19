import json
import tempfile
import unittest
from pathlib import Path

from otaku_gallery.gallery import Gallery, ManifestError, validate_item

ROOT = Path(__file__).resolve().parent.parent
ENTRY = {"id": "demo", "file": "demo.svg", "title": "T", "description": "D", "alt": "A", "creator": "C", "creator_kind": "k",
         "license": "CC0-1.0", "license_label": "CC0 1.0", "source_label": "S", "tags": ["a"], "topics": []}


class GalleryTests(unittest.TestCase):
    def test_bundled_manifest(self):
        g = Gallery(ROOT / "data" / "gallery.json", ROOT / "web" / "art")
        self.assertEqual(len(g.items), 8)
        self.assertGreaterEqual(len(g.items), 5)
        ids = [i["id"] for i in g.items]
        self.assertEqual(len(ids), len(set(ids)))
        for item in g.items:
            self.assertEqual(item["license"], "CC0-1.0")
            self.assertTrue(item["license_url"].startswith("https://creativecommons.org/"))
            self.assertTrue(g.path_for("bundled", item["file"]).is_file())
            for topic in item["topics"]:
                self.assertTrue(topic["query"] and topic["id"])

    def test_every_svg_is_listed_and_every_listing_has_a_file(self):
        listed = {i["file"] for i in Gallery(ROOT / "data" / "gallery.json", ROOT / "web" / "art").items}
        on_disk = {p.name for p in (ROOT / "web" / "art").glob("*.svg")}
        self.assertEqual(listed, on_disk)

    def test_rejects_non_open_licence_and_bad_names(self):
        for patch in ({"license": "All rights reserved"}, {"license": "CC-BY-NC-4.0"}, {"license": ""},
                      {"file": "../x.svg"}, {"file": "x.exe"}, {"id": "Bad Id"}, {"creator": ""}, {"topics": [{"id": "x", "label": "", "query": ""}]}):
            with self.assertRaises(ManifestError, msg=str(patch)):
                validate_item({**ENTRY, **patch}, "bundled")

    def test_local_manifest_is_opt_in_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
            (tmp / "gallery.json").write_text(json.dumps({"items": [ENTRY]}))
            g = Gallery(ROOT / "data" / "gallery.json", ROOT / "web" / "art", local_manifest=tmp / "gallery.json", media_dir=tmp)
            self.assertEqual(len(g.items), 9)
            self.assertEqual(g.get("demo")["url"], "media/demo.svg")
            (tmp / "gallery.json").write_text(json.dumps({"items": [{**ENTRY, "file": "missing.svg"}]}))
            with self.assertRaises(ManifestError):
                Gallery(ROOT / "data" / "gallery.json", ROOT / "web" / "art", local_manifest=tmp / "gallery.json", media_dir=tmp)


if __name__ == "__main__":
    unittest.main()
