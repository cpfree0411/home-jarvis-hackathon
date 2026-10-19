"""Optional live speech-to-text through Google's Gemini Live transcription WebSocket.

The browser streams PCM16 mono 16 kHz to this server; only this server talks to
Google, with the server-side GEMINI_API_KEY. Raw audio is never stored.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator

import websockets

MAX_SECONDS = 10 * 60


class GeminiTranscribeLive:
    MODEL = "gemini-3.5-transcribe-live"
    ENDPOINT = ("wss://generativelanguage.googleapis.com/ws/"
                "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")

    def __init__(self, language: str = "en-US"):
        # "auto" lets the model detect the language; a BCP-47 code pins it.
        self.language = language

    def setup_message(self) -> dict:
        transcription = {} if self.language.lower() == "auto" else {"languageCodes": [self.language]}
        return {"setup": {"model": f"models/{self.MODEL}",
                          "generationConfig": {"responseModalities": ["TEXT"]},
                          "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
                          "inputAudioTranscription": transcription}}

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[dict]:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("speech key unavailable")
        finals: list[str] = []
        interim = ""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        stopped = asyncio.Event()
        async with asyncio.timeout(MAX_SECONDS + 20), websockets.connect(self.ENDPOINT, max_size=256 * 1024, open_timeout=10, close_timeout=3,
                                      additional_headers={"x-goog-api-key": key}) as socket:
            await socket.send(json.dumps(self.setup_message()))
            first = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            if "setupComplete" not in first:
                raise RuntimeError("transcription setup rejected")
            await socket.send(json.dumps({"realtimeInput": {"activityStart": {}}}))

            async def sender():
                sent = 0
                async for chunk in audio:
                    if len(chunk) % 2 or len(chunk) > 64000 or not chunk:
                        raise ValueError("invalid PCM chunk")
                    sent += len(chunk)
                    if sent > 16000 * 2 * MAX_SECONDS:
                        raise ValueError("transcription time limit")
                    await socket.send(json.dumps({"realtimeInput": {"audio": {
                        "data": base64.b64encode(chunk).decode("ascii"),
                        "mimeType": "audio/pcm;rate=16000"}}}))
                await socket.send(json.dumps({"realtimeInput": {"activityEnd": {}}}))
                stopped.set()

            async def receiver():
                nonlocal interim
                async for raw in socket:
                    content = json.loads(raw).get("serverContent", {})
                    partial = content.get("interimInputTranscription") or {}
                    final = content.get("inputTranscription") or {}
                    if partial.get("text"):
                        interim = partial["text"].strip()
                        await queue.put({"type": "interim", "text": " ".join(finals + [interim])})
                    if final.get("text"):
                        finals.append(final["text"].strip())
                        interim = ""
                        await queue.put({"type": "final_segment", "text": " ".join(finals)})

            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            try:
                while True:
                    if send_task.done() and send_task.exception():
                        raise send_task.exception()
                    if recv_task.done():
                        if recv_task.exception():
                            raise recv_task.exception()
                        if not stopped.is_set():
                            raise RuntimeError("transcription connection closed before audio ended")
                        if queue.empty():
                            break
                    if stopped.is_set() and queue.empty():
                        try:
                            yield await asyncio.wait_for(queue.get(), timeout=2.0)
                            continue
                        except asyncio.TimeoutError:
                            break
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        pass
            finally:
                send_task.cancel()
                recv_task.cancel()
                await asyncio.gather(send_task, recv_task, return_exceptions=True)
        text = " ".join(finals).strip() or interim.strip()
        yield {"type": "complete", "text": text}
