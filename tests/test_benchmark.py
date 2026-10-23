from finllm_qa.briefs import build_briefs
from finllm_qa.checker import Checker
from finllm_qa.evaluate import build_docs, run
from finllm_qa.facts import FactStore, load_facts


def test_benchmark_regression():
    """On the committed fact table: no false alarms, every numeric corruption caught."""
    store = FactStore(load_facts())
    briefs = build_briefs(store)[::3]
    res = run(build_docs(briefs), {b.id: b for b in briefs}, Checker(store))["results"]
    for style in ("dev", "heldout"):
        assert res[style]["clean"]["flag_rate"] == 0
        for kind in ("value", "scale", "unit", "unsupported"):
            assert res[style][kind]["flag_rate"] == 1, (style, kind)
