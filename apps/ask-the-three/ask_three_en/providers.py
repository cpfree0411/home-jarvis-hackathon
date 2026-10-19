"""Model providers. Every network call is a bounded, text-only HTTPS POST from the server.

Keys are read from the process environment at call time and only ever placed in
the Authorization / x-api-key header of the one provider request. Errors are a
fixed category string (ProviderError.code); provider text, headers and keys are
never logged, stored, or chained into exceptions.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_REQUEST = 48_000
MAX_RESPONSE = 256 * 1024
MAX_TOKENS = 1200
TIMEOUT = 90
CLI_TIMEOUT = 180

PANEL_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["A", "B"]},
        "strength": {"type": "string", "enum": ["CLOSE", "LEAN", "STRONG"]},
        "reasoning": {"type": "string"},
        "other_side_credit": {"type": "string"},
        "suggestion": {"type": "string"},
    },
    "required": ["choice", "strength", "reasoning", "other_side_credit", "suggestion"],
    "additionalProperties": False,
}
_SIDE = {"type": "object", "properties": {"label": {"type": "string"}, "position": {"type": "string"}},
         "required": ["label", "position"], "additionalProperties": False}
ORGANIZER_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "context": {"type": "string"},
        "subject": {"type": "string"},
        "entities": {"type": "array", "items": {
            "type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
            "required": ["name", "role"], "additionalProperties": False}},
        "side_a": _SIDE,
        "side_b": _SIDE,
    },
    "required": ["title", "context", "subject", "entities", "side_a", "side_b"],
    "additionalProperties": False,
}

last_usage: dict = {}


class ProviderError(RuntimeError):
    """A bounded, fixed category. Never carries provider text, headers, or a key."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _key(name: str, code: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or any(c.isspace() for c in value):
        raise ProviderError(code)
    return value


def post_json(url: str, body: dict, headers: dict, prefix: str, timeout: int = TIMEOUT,
              connection=None) -> dict:
    """POST one JSON body, return the decoded JSON object. All faults become ProviderError."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ProviderError(f"{prefix}_endpoint")
    data = json.dumps(body, ensure_ascii=False).encode()
    if len(data) > MAX_REQUEST:
        raise ProviderError(f"{prefix}_input_limit")
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    deadline = time.monotonic() + timeout
    conn_cls = connection or http.client.HTTPSConnection
    conn = conn_cls(parts.hostname, parts.port or 443, timeout=min(45, timeout))
    fault, raw = None, b""
    try:
        try:
            conn.request("POST", target, body=data, headers={
                **headers, "Content-Type": "application/json", "Accept": "application/json"})
            resp = conn.getresponse()
            if resp.status != 200:
                raise ProviderError(f"{prefix}_http_{int(resp.status)}")
            while True:
                if time.monotonic() > deadline:
                    raise ProviderError(f"{prefix}_timeout")
                chunk = resp.read(65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > MAX_RESPONSE:
                    raise ProviderError(f"{prefix}_oversize")
        except ProviderError as exc:
            fault = exc.code
        except (socket.timeout, TimeoutError):
            fault = f"{prefix}_timeout"
        except Exception:
            # Exception strings can echo request details: keep only a category and
            # raise outside the handler so no original exception is chained.
            fault = f"{prefix}_network"
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if fault:
        raise ProviderError(fault)
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ProviderError(f"{prefix}_envelope")
    return value


def _record_usage(provider: str, model: str, usage: dict, started: float, finish) -> dict:
    global last_usage
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
    last_usage = {k: usage[k] for k in keys if type(usage.get(k)) is int and usage[k] >= 0}
    last_usage.update({"provider": provider, "model": model, "finish_reason": finish,
                       "latency_s": round(time.monotonic() - started, 3)})
    # Counts only, for cost readback in the service log. Never prompt or answer text.
    print("provider_usage " + json.dumps(last_usage), flush=True)
    return last_usage


def _chat_message(data: dict, prefix: str):
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        raise ProviderError(f"{prefix}_envelope")
    if message.get("tool_calls"):
        raise ProviderError(f"{prefix}_tool_call")
    return choice, message


def nebius_complete(prompt: str, schema_name: str, schema: dict, model: str, base: str,
                    connection=None) -> str:
    """Nebius Token Factory, OpenAI-compatible chat completions, NVIDIA Nemotron.

    Thinking is off and temperature is 0 so a judge seat answers directly and
    reproducibly; the strict json_schema is enforced provider-side and again by our parser.
    """
    key = _key("NEBIUS_API_KEY", "nebius_key_unavailable")
    started = time.monotonic()
    data = post_json(base + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": schema_name, "schema": schema, "strict": True}},
        "chat_template_kwargs": {"enable_thinking": False},
    }, {"Authorization": "Bearer " + key}, "nebius", connection=connection)
    choice, message = _chat_message(data, "nebius")
    if data.get("model") != model:
        # Never accept a silent substitution for the requested model.
        raise ProviderError("nebius_model_mismatch")
    _record_usage("nebius", model, data.get("usage") or {}, started, choice.get("finish_reason"))
    content = message.get("content")
    if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
        raise ValueError("incomplete")
    return content


def openai_complete(prompt: str, model: str, base: str, connection=None) -> str:
    key = _key("OPENAI_API_KEY", "openai_key_unavailable")
    started = time.monotonic()
    data = post_json(base + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": MAX_TOKENS * 4,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "panel_result", "schema": PANEL_SCHEMA, "strict": True}},
    }, {"Authorization": "Bearer " + key}, "openai", connection=connection)
    choice, message = _chat_message(data, "openai")
    served = str(data.get("model") or "")
    if not served.startswith(model):
        raise ProviderError("openai_model_mismatch")
    _record_usage("openai", served, data.get("usage") or {}, started, choice.get("finish_reason"))
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("incomplete")
    return content


def anthropic_complete(prompt: str, model: str, connection=None) -> str:
    key = _key("ANTHROPIC_API_KEY", "anthropic_key_unavailable")
    started = time.monotonic()
    data = post_json("https://api.anthropic.com/v1/messages", {
        "model": model,
        "max_tokens": MAX_TOKENS * 2,
        "messages": [{"role": "user", "content": prompt}],
    }, {"x-api-key": key, "anthropic-version": "2023-06-01"}, "anthropic", connection=connection)
    served = str(data.get("model") or "")
    if not served.startswith(model):
        raise ProviderError("anthropic_model_mismatch")
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise ProviderError("anthropic_envelope")
    _record_usage("anthropic", served, data.get("usage") or {}, started, data.get("stop_reason"))
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    if data.get("stop_reason") != "end_turn" or not text.strip():
        raise ValueError("incomplete")
    return text


# ----------------------------------------------------------------- local CLIs (opt-in)

def _link_credential(target: Path, source: str, default: Path, code: str):
    """The CLI keeps its own login; the role home only references it, never copies it."""
    src = Path(source).expanduser() if source else default
    if not src.is_file():
        raise ProviderError(code)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink() and Path(os.readlink(target)) != src:
        target.unlink()
    if not target.exists() and not target.is_symlink():
        target.symlink_to(src)


def _bin_path(name: str, code: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ProviderError(code)
    return found


def _link_dirs(exe: str) -> list[str]:
    """Every directory along the launcher's symlink chain, so e.g. a Node shim finds its node."""
    dirs, path = [], Path(exe)
    for _ in range(8):
        if str(path.parent) not in dirs:
            dirs.append(str(path.parent))
        if not path.is_symlink():
            break
        target = Path(os.readlink(path))
        path = target if target.is_absolute() else path.parent / target
    return dirs


def cli_command(seat: str, settings, prompt: str):
    state = Path(settings.state_dir)
    home = str(Path.home())
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    if seat == "gpt":
        exe = _bin_path(settings.codex_bin, "codex_cli_unavailable")
        role = state / "codex"
        _link_credential(role / "auth.json", settings.codex_auth, Path(home) / ".codex" / "auth.json",
                         "codex_auth_unavailable")
        cmd = [exe, "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
               "--sandbox", "read-only", "--skip-git-repo-check", "--color", "never",
               "--model", settings.codex_model, "--cd", str(state / "workspace"),
               "-c", 'model_reasoning_effort="low"', "-c", 'model_reasoning_summary="none"',
               "-c", "hide_agent_reasoning=true", "-c", 'history.persistence="none"',
               "-c", 'web_search="disabled"', "-c", "tools.web_search=false",
               "-c", "features.shell_tool=false", "-c", "features.multi_agent=false",
               "-c", "features.hooks=false", "-c", "features.memories=false",
               "-c", "features.remote_plugin=false", "-"]
        # Codex's Node launcher expects the real OS home; CODEX_HOME stays isolated.
        env = {"HOME": home, "CODEX_HOME": str(role)}
    elif seat == "claude":
        exe = _bin_path(settings.claude_bin, "claude_cli_unavailable")
        role = state / "claude"
        _link_credential(role / ".credentials.json", settings.claude_credentials,
                         Path(home) / ".claude" / ".credentials.json", "claude_auth_unavailable")
        cmd = [exe, "--model", settings.claude_model, "--effort", "medium",
               "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-chrome",
               "--no-session-persistence", "--setting-sources", "", "--output-format", "json", "-p"]
        env = {"HOME": str(role), "CLAUDE_CONFIG_DIR": str(role), "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
               "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
               "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1", "DISABLE_AUTOUPDATER": "1"}
    else:
        raise ValueError(seat)
    env.update({"USER": user, "LOGNAME": user, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb",
                "PATH": ":".join(_link_dirs(exe) + ["/usr/local/bin", "/usr/bin", "/bin"])})
    return cmd, env


def cli_complete(seat: str, settings, prompt: str, timeout: int = CLI_TIMEOUT) -> str:
    cmd, env = cli_command(seat, settings, prompt)
    state = Path(settings.state_dir)
    work = state / "workspace"
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = "codex" if seat == "gpt" else "claude"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ask-three-en-", dir=state) as temp:
        with open(Path(temp) / "out", "wb+") as out, open(Path(temp) / "err", "wb+") as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=work,
                                    env=env, start_new_session=True)

            def stop():
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()

            deadline = time.monotonic() + timeout
            pending = prompt.encode()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop()
                    raise ProviderError(f"{prefix}_timeout")
                try:
                    proc.communicate(input=pending, timeout=min(0.5, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pending = None
                    if os.fstat(out.fileno()).st_size > MAX_RESPONSE or os.fstat(err.fileno()).st_size > MAX_RESPONSE:
                        stop()
                        raise ProviderError(f"{prefix}_oversize")
            if proc.returncode:
                # stderr may echo the prompt or account details: keep only the exit code.
                raise ProviderError(f"{prefix}_exit_{proc.returncode}")
            out.seek(0)
            value = out.read(MAX_RESPONSE).decode("utf-8", "replace").strip()
    if seat == "claude":
        try:
            envelope = json.loads(value)
        except ValueError:
            envelope = None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), str):
            raise ProviderError("claude_envelope")
        if envelope.get("is_error"):
            raise ProviderError("claude_cli_error")
        value = envelope["result"]
    _record_usage(prefix + "-cli", settings.codex_model if seat == "gpt" else settings.claude_model, {},
                  started, "exit_0")
    return value
