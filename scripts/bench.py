"""Speed and memory on this machine: the checker (CPU) and, with --llm, local generation (GPU).

    python scripts/bench.py                 # checker only, offline
    python scripts/bench.py --llm           # also time each model on 32 briefs (needs the weights)

Writes reports/bench.json and reports/bench.md.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finllm_qa.__main__ import _setup  # noqa: E402
from finllm_qa.checker import Checker  # noqa: E402
from finllm_qa.evaluate import build_docs  # noqa: E402
from finllm_qa.llm import SYSTEM, load_outputs, prompt_for  # noqa: E402

REPORTS = Path(__file__).resolve().parents[1] / "reports"
MODELS = ["Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct", "HuggingFaceTB/SmolLM2-1.7B-Instruct",
          "ibm-granite/granite-3.3-2b-instruct"]


def _cpu_name() -> str:
    if platform.system() == "Windows":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return platform.processor() or platform.machine()


def time_checker(texts: list[tuple[str, object]], checker: Checker) -> dict:
    for text, brief in texts[:50]:  # warm-up: compiled regexes, caches
        checker.check(text, brief)
    ms = []
    for text, brief in texts:
        t0 = time.perf_counter()
        checker.check(text, brief)
        ms.append(1000 * (time.perf_counter() - t0))
    ms.sort()
    return {"docs": len(ms), "ms_p50": statistics.median(ms), "ms_p95": ms[int(0.95 * len(ms)) - 1],
            "docs_per_s": len(ms) / (sum(ms) / 1000)}


def time_generation(model_id: str, briefs, n: int = 32, batch_size: int = 8, max_new_tokens: int = 180) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    src = model_id
    local = os.environ.get("MODEL_DIR")
    if local and (Path(local) / model_id.split("/")[-1]).is_dir():
        src = str(Path(local) / model_id.split("/")[-1])
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(src, padding_side="left")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(src, dtype=torch.bfloat16, device_map="cuda").eval()
    load_s = time.perf_counter() - t0
    torch.cuda.reset_peak_memory_stats()
    new_tokens, t_gen = 0, 0.0
    for i in range(0, n, batch_size):
        chunk = briefs[i:i + batch_size]
        chats = [[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt_for(b)}] for b in chunk]
        enc = tok([tok.apply_chat_template(c, tokenize=False, add_generation_prompt=True) for c in chats],
                  return_tensors="pt", padding=True).to(model.device)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tok.pad_token_id)
        torch.cuda.synchronize()
        t_gen += time.perf_counter() - t0
        for seq in out[:, enc["input_ids"].shape[1]:]:
            new_tokens += len(tok(tok.decode(seq, skip_special_tokens=True), add_special_tokens=False)["input_ids"])
    row = {"model": model_id, "load_s": load_s, "s_per_commentary": t_gen / n, "tokens_per_s": new_tokens / t_gen,
           "peak_gb": torch.cuda.max_memory_allocated() / 2**30, "params_m": model.num_parameters() / 1e6}
    del model
    torch.cuda.empty_cache()
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    store, briefs, by_id = _setup()
    checker = Checker(store)
    llm_texts = [(r["text"], by_id[r["brief_id"]]) for p in sorted((REPORTS / "llm").glob("*.jsonl"))
                 for r in load_outputs(p)]
    bench_texts = [(d.text, by_id[d.brief_id]) for d in build_docs(briefs)]
    t0 = time.perf_counter()
    result = {"cpu": _cpu_name(), "checker": {"LLM commentaries": time_checker(llm_texts, checker),
                                               "benchmark documents": time_checker(bench_texts, checker)}}
    result["checker_total_s"] = time.perf_counter() - t0
    result["peak_rss_mb"] = psutil.Process().memory_info().peak_wset / 2**20 if platform.system() == "Windows" \
        else psutil.Process().memory_info().rss / 2**20
    md = [f"Checker on {result['cpu']} (one core, pure Python):", "",
          "| Texts | Count | Median | 95th percentile | Throughput |", "| --- | --- | --- | --- | --- |"]
    for name, c in result["checker"].items():
        md.append(f"| {name} | {c['docs']:,} | {c['ms_p50']:.1f} ms | {c['ms_p95']:.1f} ms | {c['docs_per_s']:,.0f} texts/s |")
    if args.llm:
        import torch
        result["gpu"] = torch.cuda.get_device_name(0)
        result["generation"] = [time_generation(m, briefs) for m in MODELS]
        md += ["", f"Generation on {result['gpu']} (bf16, greedy, batch 8, up to 180 new tokens, 32 briefs):", "",
               "| Model | Parameters | Seconds per commentary | Tokens/s, batch of 8 | Peak GPU memory | Load time |",
               "| --- | --- | --- | --- | --- | --- |"]
        for g in result["generation"]:
            md.append(f"| {g['model'].split('/')[-1]} | {g['params_m']:,.0f}M | {g['s_per_commentary']:.2f} | "
                      f"{g['tokens_per_s']:.0f} | {g['peak_gb']:.1f} GB | {g['load_s']:.0f} s |")
    (REPORTS / "bench.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (REPORTS / "bench.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
