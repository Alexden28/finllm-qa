"""Draw the audit sample: findings and unflagged commentaries from the held-out models.

Writes reports/audit.csv (or --out) with an empty `label` and `reason` per row, to be filled by
reading each case against its brief:
  findings:  true_error | ungrounded (true violation of "use only the facts", maybe correct in
             the world) | false_alarm
  unflagged: clean | missed_error
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finllm_qa.briefs import build_briefs  # noqa: E402
from finllm_qa.checker import Checker  # noqa: E402
from finllm_qa.facts import FactStore, load_facts  # noqa: E402
from finllm_qa.llm import load_outputs  # noqa: E402

HELD_OUT = ["SmolLM2-1.7B-Instruct", "Qwen2.5-3B-Instruct", "Qwen2.5-7B-Instruct"]
N_FINDINGS, N_UNFLAGGED = 60, 45


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=HELD_OUT, help="reports/llm/<name>.jsonl files to sample")
    ap.add_argument("--out", default="audit.csv", help="file name under reports/")
    args = ap.parse_args()
    store = FactStore(load_facts())
    briefs = {b.id: b for b in build_briefs(store)}
    checker = Checker(store)
    findings, unflagged = [], []
    for name in args.models:
        path = ROOT / "reports" / "llm" / f"{name}.jsonl"
        if not path.exists():
            continue
        for o in load_outputs(path):
            res = checker.check(o["text"], briefs[o["brief_id"]])
            facts = " | ".join(briefs[o["brief_id"]].fact_lines())
            if res.flagged:
                for f in res.findings:
                    findings.append({"kind": "finding", "model": name, "brief_id": o["brief_id"], "facts": facts,
                                     "text": o["text"], "flagged": f.text, "verdict": f.verdict, "error": f.error,
                                     "detail": f.detail})
            else:
                unflagged.append({"kind": "unflagged", "model": name, "brief_id": o["brief_id"], "facts": facts,
                                  "text": o["text"]})
    rng = random.Random(2026)
    rows = rng.sample(findings, min(N_FINDINGS, len(findings))) + rng.sample(unflagged, min(N_UNFLAGGED, len(unflagged)))
    cols = ["kind", "model", "brief_id", "facts", "text", "flagged", "verdict", "error", "detail", "label", "reason"]
    with (ROOT / "reports" / args.out).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"{len(findings)} findings, {len(unflagged)} unflagged commentaries; sampled {len(rows)} rows")


if __name__ == "__main__":
    main()
