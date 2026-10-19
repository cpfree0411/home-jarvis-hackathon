import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("audit_repo", ROOT / "scripts" / "audit_repo.py")
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)


class AuditTests(unittest.TestCase):
    def test_repository_is_clean(self):
        findings, count = audit_mod.audit(ROOT)
        self.assertEqual(findings, [])
        self.assertGreater(count, 30)

    def test_audit_detects_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subprocess.run(["git", "init", "-q", str(tmp)], check=True)
            (tmp / "LICENSE").write_text("MIT License\n")
            (tmp / "NOTICE").write_text("x\n")
            lan = ".".join(["192", "168", "1", "20"])
            home = "/ho" + "me/alice/secret"
            fake = "NEBIUS_API_KEY=" + "A1b2C3d4E5f6G7h8I9j0"
            (tmp / "leak.py").write_text("HOST='%s'\nP='%s'\n%s\n" % (lan, home, fake))
            (tmp / ".env").write_text("X=1\n")
            (tmp / "bad.svg").write_text("<svg><script>alert(1)</script></svg>")
            (tmp / "k.txt").write_text("-----BEGIN " + "PRIVATE KEY-----\n")
            (tmp / "kr.md").write_text("\ud55c\uad6d\uc5b4\n")
            (tmp / "jv.md").write_text("see the Jar" + "vis server\n")
            subprocess.run(["git", "-C", str(tmp), "remote", "add", "origin", "https://example.invalid/x.git"], check=True)
            kinds = {f["check"] for f in audit_mod.audit(tmp)[0]}
            for expected in ("lan-ip", "home-path", "key-assignment", "forbidden-file", "svg-active-or-external-content",
                             "private-key", "hangul", "private-markers", "git-remote"):
                self.assertIn(expected, kinds)

    def test_audit_catches_the_live_key_value_without_printing_it(self):
        secret = "zz-test-secret-value-12345"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "LICENSE").write_text("MIT License\n")
            (tmp / "NOTICE").write_text("x\n")
            (tmp / "a.txt").write_text("token is " + secret + "\n")
            old = os.environ.get("NEBIUS_API_KEY")
            os.environ["NEBIUS_API_KEY"] = secret
            try:
                findings = audit_mod.audit(tmp)[0]
            finally:
                if old is None:
                    del os.environ["NEBIUS_API_KEY"]
                else:
                    os.environ["NEBIUS_API_KEY"] = old
            self.assertIn("live-secret-in-tree", {f["check"] for f in findings})
            self.assertNotIn(secret, repr(findings))


if __name__ == "__main__":
    unittest.main()
