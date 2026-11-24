#!/usr/bin/env python3
"""Exercise the private OpenAI-compatible API through a localhost port-forward."""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


MODEL = "qwen3-1.7b"


def open_request(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    return urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json"}), timeout=120)


def read_json(base, path, payload=None):
    with open_request(base, path, payload) as response:
        return json.load(response)


def stream_events(response):
    if response.headers.get_content_type() != "text/event-stream":
        raise ValueError("Expected an SSE response")
    for line in response:
        if line.startswith(b"data:"):
            value = line[5:].strip()
            yield None if value == b"[DONE]" else json.loads(value)


def smoke(base):
    path = "/v1/chat/completions"
    with open_request(base, "/health"):
        pass
    models = read_json(base, "/v1/models")
    if MODEL not in {model["id"] for model in models["data"]}:
        raise ValueError("Expected model alias is missing")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "List eight common planets, one per line."}],
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0, "max_tokens": 64,
    }

    def check_completion():
        completion = read_json(base, path, payload)
        if not completion["choices"][0]["message"]["content"].strip():
            raise ValueError("Expected a nonempty completion")

    check_completion()
    streaming = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    start = time.perf_counter()
    chunks = []
    output_tokens = 0
    done = False
    with open_request(base, path, streaming) as response:
        for event in stream_events(response):
            if event is None:
                done = True
                break
            if event.get("usage"):
                output_tokens = event["usage"]["completion_tokens"]
            if any(choice["delta"].get("content") for choice in event["choices"]):
                chunks.append(time.perf_counter())
    elapsed = time.perf_counter() - start
    if len(chunks) < 2 or not done or output_tokens < 2:
        raise ValueError("Expected multiple streamed chunks, usage and DONE")

    # Closing the first live stream exercises cancellation and slot reuse.
    cancelled = {**streaming, "max_tokens": 128, "ignore_eos": True}
    with open_request(base, path, cancelled) as response:
        for event in stream_events(response):
            if event is None:
                raise ValueError("Cancellation stream finished before first content")
            if any(choice["delta"].get("content") for choice in event["choices"]):
                break
        else:
            raise ValueError("Cancellation stream closed before first content")
    check_completion()

    overlong = {**payload, "messages": [{"role": "user", "content": " apple" * 4096}]}
    try:
        read_json(base, path, overlong)
    except HTTPError as error:
        with error:
            detail = error.read().lower()
            if error.code != 400 or not any(term in detail for term in (b"context", b"token")):
                raise
    else:
        raise ValueError("The server accepted an oversized context")
    print(json.dumps({
        "ttft_seconds": chunks[0] - start,
        "tpot_seconds_estimate": (chunks[-1] - chunks[0]) / (output_tokens - 1),
        "generation_seconds": elapsed,
        "output_tokens": output_tokens,
        "tokens_per_second": output_tokens / elapsed,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18000")
    smoke(parser.parse_args().url.rstrip("/"))
