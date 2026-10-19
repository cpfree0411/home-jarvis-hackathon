"""Server-side NVIDIA Nemotron 3 Ultra writer via Nebius Token Factory.

Text only: no SDK, no tools, no media, no request logging. The API key is read
from the NEBIUS_API_KEY environment variable at call time and is never sent to
the browser or written anywhere.
"""
import http.client
import json
import os
import socket
import threading
import time

from .errors import ResearchError
from .evidence import evidence_for_model
from .research import PROMPT, SCHEMA

MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"
HOST = "api.tokenfactory.us-central1.nebius.com"
TARGET = "/v1/chat/completions"
MAX_TOKENS = 4000
MAX_RESPONSE = 200_000
MAX_REQUEST = 100_000
SOCKET_TIMEOUT_S = 10


def validate_schema(value, schema):
    """The small JSON-schema subset used by SCHEMA, without adding a dependency."""
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool}
    if not isinstance(value, kinds[schema["type"]]):
        raise ValueError("type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("enum")
    if isinstance(value, dict):
        if schema.get("additionalProperties") is False and set(value) - set(schema.get("properties", {})):
            raise ValueError("additionalProperties")
        if any(k not in value for k in schema.get("required", [])):
            raise ValueError("required")
        for k, spec in schema.get("properties", {}).items():
            if k in value:
                validate_schema(value[k], spec)
    if isinstance(value, list):
        for item in value:
            validate_schema(item, schema["items"])


class NebiusWriter:
    model = MODEL

    def __init__(self, connection=http.client.HTTPSConnection, environ=None):
        self.connection = connection
        self.environ = environ if environ is not None else os.environ
        self.lock = threading.Lock()
        self.active = None
        self.usage = {}
        self.metrics = {}

    def api_key(self):
        value = (self.environ.get("NEBIUS_API_KEY") or "").strip()
        if not value or any(c.isspace() for c in value):
            raise ResearchError("nebius_key_unavailable")
        return value

    def configured(self):
        try:
            self.api_key()
            return True
        except ResearchError:
            return False

    def cancel(self):
        with self.lock:
            conn = self.active
        if conn:
            try:
                if conn.sock:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                conn.close()
            except OSError:
                pass

    def build_payload(self, query, records):
        prompt = PROMPT.replace("{query}", query).replace("{evidence}", evidence_for_model(records))
        return json.dumps({
            "model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "research_page", "schema": SCHEMA, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False}}, ensure_ascii=False).encode()

    def write(self, query, records, timeout=35, cancelled=None):
        self.usage, self.metrics = {}, {}
        payload = self.build_payload(query, records)
        if len(payload) > MAX_REQUEST:
            raise ResearchError("nebius_input_limit")
        key = self.api_key()
        if cancelled and cancelled():
            raise ResearchError("cancelled")
        conn = self.connection(HOST, timeout=min(SOCKET_TIMEOUT_S, timeout))
        result, done = {}, threading.Event()
        with self.lock:
            self.active = conn
        started = time.monotonic()

        def send():
            try:
                conn.request("POST", TARGET, body=payload, headers={
                    "Authorization": "Bearer " + key, "Content-Type": "application/json"})
                resp = conn.getresponse()
                result["http_status"] = resp.status
                if resp.status != 200:
                    raise ResearchError("nebius_http_%d" % resp.status)
                raw = resp.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ResearchError("nebius_oversize")
                data = json.loads(raw)
                if data.get("model") != MODEL:
                    raise ResearchError("nebius_model_mismatch")
                choice = data["choices"][0]
                message = choice["message"]
                if choice.get("finish_reason") != "stop" or message.get("tool_calls"):
                    raise ResearchError("nebius_incomplete")
                output = json.loads(message["content"])
                validate_schema(output, SCHEMA)
                usage = data.get("usage") or {}
                result["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                                   if type(usage.get(k)) is int and usage[k] >= 0}
                result["output"] = output
            except ResearchError as exc:
                result["error"] = exc.code
            except (ValueError, TypeError, KeyError, IndexError):
                result["error"] = "nebius_schema"
            except Exception:  # noqa: BLE001 - never log exception strings, headers, or bodies
                result["error"] = "nebius_unavailable"
            finally:
                conn.close()
                done.set()

        threading.Thread(target=send, daemon=True, name="nebius-http").start()
        try:
            while not done.wait(0.1):
                if cancelled and cancelled():
                    raise ResearchError("cancelled")
                if time.monotonic() - started >= timeout:
                    raise ResearchError("nebius_timeout")
            if cancelled and cancelled():
                raise ResearchError("cancelled")
            self.metrics = {"http_status": result.get("http_status"),
                            "latency_ms": int((time.monotonic() - started) * 1000),
                            "request_bytes": len(payload)}
            if result.get("error"):
                raise ResearchError(result["error"])
            self.usage = result["usage"]
            return result["output"], self.metrics["latency_ms"]
        finally:
            self.cancel()
            with self.lock:
                self.active = None
