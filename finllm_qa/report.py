"""Turn benchmark and LLM-check results into JSON, Markdown tables and figures."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .briefs import Brief  # noqa: E402
from .checker import Checker  # noqa: E402
from .llm import load_outputs  # noqa: E402

KIND_ORDER = ["value", "scale", "arithmetic", "unit", "direction", "metric", "period", "period_swap",
              "entity", "unsupported"]
KIND_LABEL = {
    "value": "wrong number", "scale": "million vs billion", "arithmetic": "% change miscomputed",
    "unit": "pp written as %", "direction": "rose/fell flipped", "metric": "metric swapped",
    "period": "period outside brief", "period_swap": "prior period's label", "entity": "wrong company/economy",
    "unsupported": "invented claim",
}
INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
SERIES = ["#2f6fb3", "#d9822b"]


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def benchmark_report(result: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    res = result["results"]
    lines = ["| Injected error | Docs (A / B) | Flagged, style A | Flagged, style B | Right sentence and type, A / B |",
             "| --- | --- | --- | --- | --- |"]
    for k in KIND_ORDER:
        a, b = res["dev"].get(k), res["heldout"].get(k)
        if not a or not b:
            continue
        lines.append(f"| {KIND_LABEL[k]} | {a['n']} / {b['n']} | {a['flag_rate']:.1%} | {b['flag_rate']:.1%} | "
                     f"{a['typed']:.1%} / {b['typed']:.1%} |")
    a, b = res["dev"]["clean"], res["heldout"]["clean"]
    lines.append(f"| none (clean text): false alarms | {a['n']} / {b['n']} | {a['flag_rate']:.1%} | "
                 f"{b['flag_rate']:.1%} | |")
    (out / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    kinds = [k for k in KIND_ORDER if k in res["dev"]]
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=160)
    y = range(len(kinds))
    for i, (style, name) in enumerate((("dev", "template style A"), ("heldout", "template style B"))):
        vals = [res[style][k]["flag_rate"] * 100 for k in kinds]
        ax.barh([v + (i - 0.5) * 0.38 for v in y], vals, height=0.36, color=SERIES[i], label=name)
    ax.set_yticks(list(y), [KIND_LABEL[k] for k in kinds], color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Corrupted commentaries flagged (%)", color=MUTED, fontsize=9)
    ax.set_title("Recall by injected error type (0 false alarms on 534 clean texts)", color=INK, fontsize=10,
                 loc="left")
    _style(ax)
    ax.tick_params(axis="y", colors=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.4, -0.13), ncol=2)
    fig.tight_layout()
    fig.savefig(out / "benchmark_recall.png")
    plt.close(fig)
    print((out / "benchmark.md").read_text(encoding="utf-8"))


def llm_report(paths: list[Path], briefs: dict[str, Brief], checker: Checker, out: Path) -> None:
    rows, examples = [], []
    for path in paths:
        outputs = load_outputs(path)
        model = outputs[0]["model"]
        n_docs = flagged = contra_docs = nums = supported = 0
        errors: Counter = Counter()
        verdicts: Counter = Counter()
        for o in outputs:
            res = checker.check(o["text"], briefs[o["brief_id"]])
            n_docs += 1
            flagged += res.flagged
            contra_docs += any(f.verdict == "contradicted" for f in res.findings)
            nums += res.n_numbers
            supported += res.n_supported
            errors.update(f.error for f in res.findings if f.verdict == "contradicted")
            verdicts.update(f.verdict for f in res.findings)
            for f in res.findings:
                examples.append({"model": model, "brief_id": o["brief_id"], "text": o["text"], **f.__dict__})
        rows.append({
            "model": model, "docs": n_docs, "flagged_docs": flagged / n_docs,
            "docs_with_contradiction": contra_docs / n_docs, "numbers": nums,
            "numbers_supported": supported / nums if nums else 0.0,
            "contradicted_findings": verdicts["contradicted"], "unverifiable_findings": verdicts["unverifiable"],
            "contradicted_by_error": dict(errors.most_common()),
        })
    rows.sort(key=lambda r: r["docs_with_contradiction"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with (out / "llm_findings.jsonl").open("w", encoding="utf-8") as f:
        for e in examples:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    lines = ["| Model | Commentaries | With a contradicted claim | With any finding | Numbers traced to the brief |",
             "| --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['model']} | {r['docs']} | {r['docs_with_contradiction']:.1%} | {r['flagged_docs']:.1%} | "
                     f"{r['numbers_supported']:.1%} of {r['numbers']} |")
    (out / "llm_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows_plot = rows[::-1]  # barh draws bottom-up; best model on top
    fig, ax = plt.subplots(figsize=(7.2, 1.3 + 0.55 * len(rows)), dpi=160)
    names = [r["model"].split("/")[-1] for r in rows_plot]
    contra = [r["docs_with_contradiction"] * 100 for r in rows_plot]
    other = [(r["flagged_docs"] - r["docs_with_contradiction"]) * 100 for r in rows_plot]
    ax.barh(names, contra, color="#c23b3b", height=0.55, label="contradicts the data")
    ax.barh(names, other, left=contra, color="#e8a5a5", height=0.55, label="only unverifiable claims")
    for i, (c, o) in enumerate(zip(contra, other)):
        ax.text(c + o + 1, i, f"{c:.0f}% contradicted", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xlabel("Commentaries with at least one finding (%)", color=MUTED, fontsize=9)
    ax.set_title(f"Local LLMs writing from {rows[0]['docs']} real fact sheets", color=INK, fontsize=10, loc="left")
    _style(ax)
    ax.tick_params(axis="y", colors=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.45, -0.38), ncol=2)
    fig.tight_layout()
    fig.savefig(out / "llm_findings.png")
    plt.close(fig)
    print((out / "llm_results.md").read_text(encoding="utf-8"))
