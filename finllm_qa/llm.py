"""Generate commentary with small open-weight LLMs running locally (no paid API).

Off by default: run `python -m finllm_qa generate --model <hf id>` to download the weights
from Hugging Face and write reports/llm/<model>.jsonl. Greedy decoding, so runs repeat.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .briefs import Brief

SYSTEM = "You are a financial journalist who writes accurate, concise market commentary."
INSTRUCTION = (
    "Write a 2-3 sentence commentary for an investment newsletter based ONLY on the facts below. "
    "Mention the key figures and how they changed. Do not add numbers, dates, comparisons or "
    "claims that are not in the facts or directly computable from them.\n\nFacts:\n"
)


def prompt_for(b: Brief) -> str:
    return INSTRUCTION + "\n".join(f"- {line}" for line in b.fact_lines())


def generate(briefs: list[Brief], model_id: str, out_path: Path, batch_size: int = 16,
             max_new_tokens: int = 180, four_bit: bool = False, label: str | None = None) -> list[dict]:
    """`model_id` is a Hugging Face id or a local folder; `label` names the model in the output."""
    label = label or model_id
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_id, padding_side="left")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = None
    if four_bit:  # lets a 7B model fit in 8 GB of VRAM
        from transformers import BitsAndBytesConfig
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                                   bnb_4bit_quant_type="nf4")
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda",
                                                 quantization_config=quant)
    model.eval()

    rows: list[dict] = []
    t0 = time.time()
    for i in range(0, len(briefs), batch_size):
        chunk = briefs[i:i + batch_size]
        chats = [[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt_for(b)}] for b in chunk]
        texts = [tok.apply_chat_template(c, tokenize=False, add_generation_prompt=True) for c in chats]
        enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        for b, seq in zip(chunk, out[:, enc["input_ids"].shape[1]:]):
            rows.append({"brief_id": b.id, "model": label + (" (4-bit)" if four_bit else ""), "text": tok.decode(seq, skip_special_tokens=True).strip()})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{label}: {len(rows)} commentaries in {time.time() - t0:.0f}s -> {out_path}")
    return rows


def load_outputs(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
