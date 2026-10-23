"""Command line: python -m finllm_qa <command> (see --help)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .briefs import build_briefs
from .checker import Checker
from .facts import FactStore, build_facts, load_facts
from .sources import ROOT

REPORTS = ROOT / "reports"


def _setup():
    store = FactStore(load_facts())
    briefs = build_briefs(store)
    return store, briefs, {b.id: b for b in briefs}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="finllm_qa", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-facts", help="download FRED/SEC data and rebuild data/facts.csv")
    sub.add_parser("benchmark", help="run the synthetic error-injection benchmark")
    g = sub.add_parser("generate", help="write commentary with a local Hugging Face model (downloads weights)")
    g.add_argument("--model", required=True)
    g.add_argument("--batch-size", type=int, default=16)
    g.add_argument("--4bit", dest="four_bit", action="store_true", help="load the model 4-bit quantized")
    sub.add_parser("score-llm", help="check every reports/llm/*.jsonl file")
    c = sub.add_parser("check", help="check one text against one brief")
    c.add_argument("brief_id")
    c.add_argument("text")
    sub.add_parser("briefs", help="list brief ids")
    args = ap.parse_args(argv)

    if args.cmd == "build-facts":
        df = build_facts()
        print(f"{len(df)} facts -> data/facts.csv")
        return
    store, briefs, by_id = _setup()
    if args.cmd == "briefs":
        print("\n".join(by_id))
    elif args.cmd == "check":
        res = Checker(store).check(args.text, by_id[args.brief_id])
        print(json.dumps([f.__dict__ for f in res.findings], indent=2) if res.flagged else "no findings")
    elif args.cmd == "benchmark":
        from .evaluate import build_docs, run
        from .report import benchmark_report
        result = run(build_docs(briefs), by_id, Checker(store))
        benchmark_report(result, REPORTS)
    elif args.cmd == "generate":
        from .llm import generate
        name = args.model.split("/")[-1]
        generate(briefs, args.model, REPORTS / "llm" / f"{name}.jsonl", batch_size=args.batch_size,
                 four_bit=args.four_bit)
    elif args.cmd == "score-llm":
        from .report import llm_report
        llm_report(sorted((REPORTS / "llm").glob("*.jsonl")), by_id, Checker(store), REPORTS)


if __name__ == "__main__":
    main()
