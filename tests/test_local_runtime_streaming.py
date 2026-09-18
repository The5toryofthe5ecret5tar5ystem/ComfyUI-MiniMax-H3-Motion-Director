"""Local generation must report progress while it runs.

A 27B model on partial GPU offload writes a couple of tokens per second, so a
2000-token enhancement is a 10-20 minute wait. The completion used to be called
non-streaming, which meant the console was silent for exactly that whole time -
indistinguishable from a hang, and reported as one twice in a live session.

These tests drive `LocalChat.chat` with a fake llama.cpp object so the streaming
accumulation, the progress cadence and the final report are pinned without a GPU.
"""

from __future__ import annotations

import types

import pytest

from mmx_pkg.lib.prompt_local_runtime import LocalChat


class _FakeStream:
    """One chunk per token, the way llama.cpp streams."""

    def __init__(self, tokens, *, reasoning=False, usage=None, content_key=None):
        self._tokens = tokens
        self._reasoning = reasoning
        self._usage = usage
        self._content_key = content_key

    def __iter__(self):
        for token in self._tokens:
            delta = {"content": token} if self._content_key is None else {self._content_key: token}
            if self._reasoning:
                delta = {"reasoning_content": token}
            yield {"choices": [{"delta": delta, "finish_reason": None}]}
        if self._usage:
            yield {"choices": [], "usage": self._usage}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


class _FakeLlama:
    def __init__(self, stream):
        self._stream = stream
        self.calls: list[dict] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs.get("stream") is True, "local generation must stream"
        return self._stream


def _chat_with(stream) -> tuple["LocalChat", _FakeLlama]:
    chat = LocalChat("/tmp/model.gguf")
    fake = _FakeLlama(stream)
    chat.llm = fake
    return chat, fake


def test_streamed_tokens_are_joined_into_the_same_answer(capsys):
    chat, fake = _chat_with(_FakeStream(["Hello", " ", "world"]))
    text = chat.chat([{"role": "user", "content": "hi"}])
    assert text == "Hello world"
    assert fake.calls and fake.calls[0]["stream"] is True
    captured = capsys.readouterr().out
    assert "generated 3 tokens" in captured
    assert "tok/s" in captured


def test_reasoning_only_models_still_answer(capsys):
    """The non-streaming path fell back to reasoning_content; streaming keeps it."""
    chat, _ = _chat_with(_FakeStream(["thinking", "...", "answer"], reasoning=True))
    assert chat.chat([{"role": "user", "content": "hi"}]) == "thinking...answer"
    capsys.readouterr()


def test_usage_counters_win_over_the_chunk_count(capsys):
    chat, _ = _chat_with(_FakeStream(
        ["a", "b"],
        usage={"prompt_tokens": 1998, "completion_tokens": 512},
    ))
    assert chat.chat([{"role": "user", "content": "hi"}]) == "ab"
    out = capsys.readouterr().out
    assert "generated 512 tokens" in out
    assert "1998 prompt tokens" in out


def test_progress_lines_appear_mid_generation(monkeypatch, capsys):
    """Long runs must print progress, not only a final line."""
    ticks = iter([0.0, 1.0, 9.0, 12.0, 13.0, 14.0])
    monkeypatch.setattr(
        "mmx_pkg.lib.prompt_local_runtime.time.monotonic",
        lambda: next(ticks, 14.0),
    )
    chat, _ = _chat_with(_FakeStream([f"t{i} " for i in range(6)]))
    chat.chat([{"role": "user", "content": "hi"}])
    out = capsys.readouterr().out
    assert "generating..." in out, "no progress line was printed mid-run"


def test_empty_completion_returns_empty_string(capsys):
    chat, _ = _chat_with(_FakeStream([]))
    assert chat.chat([{"role": "user", "content": "hi"}]) == ""
    capsys.readouterr()


def test_unloaded_model_raises():
    chat = LocalChat("/tmp/model.gguf")
    with pytest.raises(Exception):
        chat.chat([{"role": "user", "content": "hi"}])
