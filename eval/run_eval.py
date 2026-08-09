"""Deterministic evaluation of the assist pipeline against eval/cases.json.

Runs in-process (no HTTP server needed) against the seeded database and the
active provider from .env:

    python eval/run_eval.py            # from the repo root
    python run_eval.py                 # from eval/

Metrics:
- retrieval hit@k : an expected doc id appears in the top-k retrieved chunks
- draft rate      : answerable cases that produced a validated, cited draft
- groundedness    : drafts containing every required keyword group
- refusal rate    : must-refuse cases that actually ended in a refusal

The checks are deterministic on purpose — no LLM-as-judge — so a run is
reproducible and comparable across providers (see README).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "api"))

from app.assist import assist_events            # noqa: E402
from app.config import get_settings             # noqa: E402
from app.retrieval import retrieve              # noqa: E402


def run_case(case: dict) -> dict:
    out: dict = {"id": case["id"]}

    result = retrieve(case["question"])
    retrieved_docs = {h["doc_id"] for h in result.hits}
    if case.get("expected_docs"):
        out["hit"] = any(d in retrieved_docs for d in case["expected_docs"])

    events = list(assist_events(case["question"]))
    final_event, final_payload = events[-1]

    if case.get("expect_refusal"):
        out["refused_correctly"] = final_event == "refusal"
        out["refusal_reason"] = (
            final_payload.get("reason") if final_event == "refusal" else "DRAFTED"
        )
        return out

    out["drafted"] = final_event == "done"
    if out["drafted"]:
        draft = final_payload["draft"].lower()
        missing = [
            group
            for group in case.get("must_contain", [])
            if not any(term.lower() in draft for term in group)
        ]
        out["grounded"] = not missing
        out["missing_terms"] = missing
    else:
        out["refusal_reason"] = final_payload.get("reason")
    return out


def main() -> None:
    s = get_settings()
    cases = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
    print(f"Provider: {s.provider} | cases: {len(cases)}")
    print("-" * 72)

    t0 = time.perf_counter()
    results = []
    for case in cases:
        r = run_case(case)
        results.append(r)
        if case.get("expect_refusal"):
            status = "PASS" if r["refused_correctly"] else "FAIL"
            detail = f"refusal={r['refusal_reason']}"
        else:
            ok = r.get("hit", True) and r.get("drafted") and r.get("grounded")
            status = "PASS" if ok else "FAIL"
            detail = (
                f"hit@k={'Y' if r.get('hit') else 'N'}"
                f" draft={'Y' if r.get('drafted') else 'N (' + str(r.get('refusal_reason')) + ')'}"
                f" grounded={'Y' if r.get('grounded') else 'N ' + str(r.get('missing_terms', ''))}"
            )
        print(f"  {status}  {r['id']:<24} {detail}")

    answerable = [r for r in results if "drafted" in r]
    with_hit = [r for r in results if "hit" in r]
    refusals = [r for r in results if "refused_correctly" in r]
    drafted = [r for r in answerable if r["drafted"]]

    print("-" * 72)
    print(f"retrieval hit@{s.retrieval_k}: {sum(r['hit'] for r in with_hit)}/{len(with_hit)}")
    print(f"draft rate:        {len(drafted)}/{len(answerable)}")
    print(f"groundedness:      {sum(r['grounded'] for r in drafted)}/{len(drafted)}")
    print(f"refusal handling:  {sum(r['refused_correctly'] for r in refusals)}/{len(refusals)}")
    print(f"wall time:         {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()