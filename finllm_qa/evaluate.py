"""Synthetic benchmark: correct commentaries plus one-error corruptions of each."""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .briefs import Brief
from .checker import Checker, sentence_spans
from .corrupt import CORRUPTIONS, Label
from .templates import write

ERROR_FOR = {"period_swap": "period"}  # corruption kind -> finding error that names it


@dataclass
class Doc:
    id: str
    brief_id: str
    style: str
    kind: str  # "clean" or a corruption name
    text: str
    label: Label | None = None


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


def build_docs(briefs: list[Brief], styles=("dev", "heldout"), seed: int = 0) -> list[Doc]:
    docs: list[Doc] = []
    for b in briefs:
        for style in styles:
            rng = _rng(str(seed), b.id, style)
            clean = write(b, rng, style)
            docs.append(Doc(f"{b.id}/{style}/clean", b.id, style, "clean", clean))
            for kind, fn in CORRUPTIONS.items():
                out = fn(clean, b, _rng(str(seed), b.id, style, kind))
                if out is not None and out[0] != clean:
                    docs.append(Doc(f"{b.id}/{style}/{kind}", b.id, style, kind, out[0], out[1]))
    return docs


def run(docs: list[Doc], briefs: dict[str, Brief], checker: Checker) -> dict:
    stats: dict = defaultdict(lambda: defaultdict(lambda: {"n": 0, "flagged": 0, "located": 0, "typed": 0}))
    misses: list[dict] = []
    for d in docs:
        res = checker.check(d.text, briefs[d.brief_id])
        s = stats[d.style][d.kind]
        s["n"] += 1
        s["flagged"] += res.flagged
        if d.label is not None:
            sent = next(sp for sp in sentence_spans(d.text) if sp[0] <= d.label.start < sp[1] or sp[1] == len(d.text))
            hit = [f for f in res.findings if sent[0] <= f.start < sent[1]]
            s["located"] += bool(hit)
            s["typed"] += any(f.error == ERROR_FOR.get(d.kind, d.kind) for f in hit)
            if not res.flagged:
                misses.append({"id": d.id, "text": d.text, "changed": [d.label.before, d.label.after]})
        elif res.flagged:
            misses.append({"id": d.id, "text": d.text, "false_alarm": [asdict(f) for f in res.findings]})
    out = {}
    for style, kinds in stats.items():
        out[style] = {}
        for kind, s in sorted(kinds.items()):
            row = {"n": s["n"], "flag_rate": s["flagged"] / s["n"]}
            if kind != "clean":
                row["located"] = s["located"] / s["n"]
                row["typed"] = s["typed"] / s["n"]
            out[style][kind] = row
    return {"results": out, "misses": misses}


def write_report(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
