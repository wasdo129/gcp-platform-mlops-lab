"""Measure FP32 inference on the native CPU against a verified local snapshot."""

import argparse
import json
import platform
import resource
import time
from pathlib import Path


PROMPTS = (
    "Explain in one sentence why the sky appears blue.",
    "List three ways to keep a small PostgreSQL deployment reliable.",
    "In two sentences, compare batch inference and streaming inference.",
)
MAX_NEW_TOKENS = 128


def benchmark(snapshot):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from transformers.generation.streamers import BaseStreamer

    class TokenTimer(BaseStreamer):
        def __init__(self):
            self.puts = 0
            self.first = None

        def put(self, value):
            # Greedy generation emits the prompt before its first output token.
            self.puts += 1
            if self.puts == 2:
                self.first = time.perf_counter()

        def end(self):
            pass

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    start = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float32, attn_implementation="sdpa",
    ).eval()
    load_seconds = time.perf_counter() - start
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    measurements = []
    for prompt in PROMPTS:
        start = time.perf_counter()
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True,
            enable_thinking=False, return_tensors="pt", return_dict=True,
        )
        tokenize_seconds = time.perf_counter() - start
        input_tokens = inputs["input_ids"].shape[-1]
        if input_tokens + MAX_NEW_TOKENS > 2048:
            raise ValueError("Prompt exceeds the benchmark context")
        timer = TokenTimer()
        start = time.perf_counter()
        with torch.inference_mode():
            result = model.generate(
                input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"],
                max_new_tokens=MAX_NEW_TOKENS, do_sample=False, use_cache=True, streamer=timer,
            )
        generation_seconds = time.perf_counter() - start
        output_tokens = result.shape[-1] - input_tokens
        if not output_tokens or timer.first is None:
            raise RuntimeError("The model did not generate a timed output token")
        measurements.append({
            "tokenization_seconds": tokenize_seconds, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "ttft_seconds": timer.first - start,
            "generation_seconds": generation_seconds,
            "tokens_per_second": output_tokens / generation_seconds,
        })
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() != "Darwin":
        rss *= 1024
    return {"architecture": platform.machine(), "model_load_seconds": load_seconds,
            "peak_rss_bytes": rss, "measurements": measurements}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    print(json.dumps(benchmark(parser.parse_args().snapshot), indent=2))
