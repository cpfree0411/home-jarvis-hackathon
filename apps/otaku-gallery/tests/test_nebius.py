import json
import unittest

from otaku_gallery.errors import ResearchError
from otaku_gallery.nebius import HOST, MAX_TOKENS, MODEL, NebiusWriter, TARGET, validate_schema
from otaku_gallery.research import SCHEMA
from tests.helpers import conn_factory, good_draft, nebius_body, sample_records

KEY = "test-key-not-real-0123456789"


def writer(status=200, body=None, key=KEY):
    return NebiusWriter(connection=conn_factory(status, body), environ={"NEBIUS_API_KEY": key} if key else {})


class NebiusWriterTests(unittest.TestCase):
    def test_exact_model_and_request_shape(self):
        w = writer(body=nebius_body())
        output, ms = w.write("Cyberpunk", sample_records())
        self.assertEqual(output["status"], "answered")
        self.assertEqual(w.usage, {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168})
        self.assertGreaterEqual(w.metrics["latency_ms"], 0)
        method, target, body, headers = w.connection.last.request_args
        self.assertEqual((method, target, w.connection.last.host), ("POST", TARGET, HOST))
        payload = json.loads(body)
        self.assertEqual(payload["model"], "nvidia/Nemotron-3-Ultra-550b-a55b")
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], MAX_TOKENS)
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], SCHEMA)
        self.assertNotIn("tools", payload)
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertIn("Cyberpunk", payload["messages"][0]["content"])

    def test_key_is_not_in_the_payload_or_errors(self):
        w = writer(401, {"error": "nope"})
        with self.assertRaises(ResearchError) as cm:
            w.write("q", sample_records())
        self.assertEqual(cm.exception.code, "nebius_http_401")
        self.assertNotIn(KEY, w.connection.last.request_args[2].decode())
        self.assertNotIn(KEY, str(cm.exception))

    def test_missing_or_malformed_key(self):
        for key in (None, "", "two words"):
            with self.assertRaises(ResearchError) as cm:
                writer(key=key).write("q", sample_records())
            self.assertEqual(cm.exception.code, "nebius_key_unavailable")
        self.assertFalse(writer(key=None).configured())
        self.assertTrue(writer().configured())

    def test_rejects_wrong_model_truncation_tool_calls_and_bad_json(self):
        cases = {"nebius_model_mismatch": nebius_body(model="other/model"),
                 "nebius_incomplete": nebius_body(finish="length"),
                 "nebius_schema": nebius_body(content="not json")}
        for code, body in cases.items():
            with self.assertRaises(ResearchError, msg=code) as cm:
                writer(body=body).write("q", sample_records())
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(ResearchError) as cm:
            writer(body=nebius_body(tool_calls=[{"id": "1"}])).write("q", sample_records())
        self.assertEqual(cm.exception.code, "nebius_incomplete")

    def test_network_failure_is_generic(self):
        class Broken(conn_factory()):
            def request(self, *a, **k):
                raise OSError("secret detail that must not leak")
        with self.assertRaises(ResearchError) as cm:
            NebiusWriter(connection=Broken, environ={"NEBIUS_API_KEY": KEY}).write("q", sample_records())
        self.assertEqual(cm.exception.code, "nebius_unavailable")
        self.assertNotIn("secret detail", str(cm.exception))

    def test_schema_violation_is_rejected(self):
        draft = good_draft()
        del draft["overview"]
        with self.assertRaises(ResearchError) as cm:
            writer(body=nebius_body(draft)).write("q", sample_records())
        self.assertEqual(cm.exception.code, "nebius_schema")

    def test_oversize_input_is_refused_before_any_connection(self):
        records = sample_records("x" * 150_000)
        w = writer(body=nebius_body())
        with self.assertRaises(ResearchError) as cm:
            w.write("q", records)
        self.assertEqual(cm.exception.code, "nebius_input_limit")

    def test_cancelled_before_send(self):
        with self.assertRaises(ResearchError) as cm:
            writer(body=nebius_body()).write("q", sample_records(), cancelled=lambda: True)
        self.assertEqual(cm.exception.code, "cancelled")

    def test_validate_schema_subset(self):
        validate_schema(good_draft(), SCHEMA)
        for mutate in (lambda d: d.update(confidence="certain"), lambda d: d.update(sections=[{"heading": "x"}]),
                       lambda d: d.update(age_appropriate="yes"), lambda d: d.update(unexpected="x")):
            d = good_draft()
            mutate(d)
            with self.assertRaises(ValueError):
                validate_schema(d, SCHEMA)


if __name__ == "__main__":
    unittest.main()
