"""Exercise the actual Google wire protocol with a local scripted socket, no API call."""
import asyncio
import json

import pytest

from ask_three_en import speech


class Socket:
    def __init__(self, early_close=False):
        self.sent = []
        self.events = asyncio.Queue()
        self.early_close = early_close

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        realtime = msg.get("realtimeInput", {})
        if "audio" in realtime:
            await self.events.put({"serverContent": {"interimInputTranscription": {"text": "My friend"}}})
        if "activityEnd" in realtime:
            await self.events.put({"serverContent": {"inputTranscription": {"text": "My friend asked for advice."}}})
            await self.events.put(None)

    async def recv(self):
        return '{"setupComplete": {}}'

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.early_close:
            raise StopAsyncIteration
        msg = await self.events.get()
        if msg is None:
            raise StopAsyncIteration
        return json.dumps(msg)


def test_speech_wire_protocol_and_final_transcript(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "google-test-placeholder")
    captured = {}

    async def run():
        socket = Socket()

        def connect(endpoint, **kwargs):
            captured.update(endpoint=endpoint, **kwargs)
            return socket
        monkeypatch.setattr(speech.websockets, "connect", connect)

        async def audio():
            yield b"\0\0" * 1600
            await asyncio.sleep(0)
        events = [e async for e in speech.GeminiTranscribeLive().stream(audio())]
        return socket.sent, events

    sent, events = asyncio.run(run())
    assert sent[0]["setup"]["inputAudioTranscription"] == {"languageCodes": ["en-US"]}
    assert sent[0]["setup"]["model"] == "models/gemini-3.5-transcribe-live"
    assert sent[1] == {"realtimeInput": {"activityStart": {}}}
    assert sent[2]["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
    assert sent[-1] == {"realtimeInput": {"activityEnd": {}}}
    assert events[-1] == {"type": "complete", "text": "My friend asked for advice."}
    assert captured["additional_headers"] == {"x-goog-api-key": "google-test-placeholder"}
    assert speech.GeminiTranscribeLive("auto").setup_message()["setup"]["inputAudioTranscription"] == {}


def test_early_speech_close_fails_promptly(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "google-test-placeholder")

    async def run():
        monkeypatch.setattr(speech.websockets, "connect", lambda *a, **kw: Socket(early_close=True))

        async def audio():
            await asyncio.sleep(10)
            yield b"\0\0"
        async with asyncio.timeout(2):
            return [e async for e in speech.GeminiTranscribeLive().stream(audio())]

    with pytest.raises(RuntimeError, match="closed before audio ended"):
        asyncio.run(run())


def test_invalid_pcm_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "google-test-placeholder")

    async def run():
        monkeypatch.setattr(speech.websockets, "connect", lambda *a, **kw: Socket())

        async def audio():
            yield b"odd"
        return [e async for e in speech.GeminiTranscribeLive().stream(audio())]

    with pytest.raises(ValueError, match="invalid PCM chunk"):
        asyncio.run(run())
