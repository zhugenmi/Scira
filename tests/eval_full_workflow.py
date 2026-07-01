"""
Scira full-mode workflow evaluation.

Runs one complete `full` research workflow end-to-end and records:
  - 覆盖论文数 (papers covered)
  - 生成字数 (generated word/char count)
  - 耗时 (duration)
  - token 成本美元数 (estimated cost in USD)

Usage:
    python -m tests.eval_full_workflow                       # default topic
    python -m tests.eval_full_workflow "graph neural networks"  # custom topic
    python -m tests.eval_full_workflow --max-papers 5 "topic"   # cap download

Output:
    - stdout: human-readable summary
    - data/outputs/eval_result_<timestamp>.json: machine-readable metrics
    - the generated report itself is saved by the workflow to data/outputs/

NOTE: full mode pauses at the download-approval checkpoint. This eval auto-selects
all pending papers and calls run_download_and_rest to continue — that mirrors what
the /api/workflow/approve-download endpoint does in the real server.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Make src/ importable when run as `python -m tests.eval_full_workflow`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.workflow import run_workflow, run_download_and_rest  # noqa: E402
from src.utils.logger import logger  # noqa: E402


DEFAULT_TOPIC = "graph neural networks for knowledge graph completion"


def count_words(text: str) -> Dict[str, int]:
    """Count CJK chars + latin words separately, since reports are mixed zh/en."""
    if not text:
        return {"chars": 0, "cjk_chars": 0, "latin_words": 0, "total_units": 0}
    cjk = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))
    return {
        "chars": len(text),
        "cjk_chars": cjk,
        "latin_words": latin,
        "total_units": cjk + latin,  # rough "word count" for mixed text
    }


def run_eval(topic: str, max_papers: int | None = None) -> Dict[str, Any]:
    """Run one full-mode workflow and collect metrics. Returns metrics dict."""
    logger.info(f"=== EVAL START | topic={topic!r} | max_papers={max_papers} ===")
    t0 = time.time()

    # Step 1: run_workflow pauses at download-approval checkpoint.
    state = run_workflow(
        user_query=topic,
        auto_approve=True,
        workflow_mode="full",
    )

    pending = state.get("pending_download_papers") or []
    if pending:
        logger.info(f"Download approval checkpoint: {len(pending)} papers pending, auto-selecting all")
        selected = pending if not max_papers else pending[:max_papers]
        # Step 2: continue the rest of the pipeline (download → read → analyze → write → revise)
        state = run_download_and_rest(state, selected_papers=selected)
    else:
        # No checkpoint raised — either retrieval failed or mode didn't need download.
        logger.warning(
            f"No pending download papers; literature_data={len(state.get('literature_data') or [])}. "
            "Pipeline may not have run end-to-end."
        )

    elapsed = time.time() - t0

    # ---- collect metrics from final state ----
    final_review = state.get("final_review") or ""
    word_counts = count_words(final_review)

    metrics = {
        "topic": topic,
        "model": state.get("token_usage", {}) and _safe_env("LLM_MODEL_NAME", "gpt-4o"),
        "started_at": datetime.fromtimestamp(t0).isoformat(),
        "duration_seconds": round(elapsed, 2),
        "duration_human": _human_duration(elapsed),
        "papers": {
            "search_results": len(state.get("search_results") or []),
            "downloaded_parsed": len(state.get("literature_data") or []),
            "references": len(state.get("reference_list") or []),
            "reading_errors": len(state.get("reading_errors") or []),
        },
        "generated_text": {
            "final_review_chars": word_counts["chars"],
            "cjk_chars": word_counts["cjk_chars"],
            "latin_words": word_counts["latin_words"],
            "total_word_units": word_counts["total_units"],
            "sections_written": len(state.get("chapter_drafts") or {}),
            "has_abstract": bool(state.get("abstract")),
            "has_introduction": bool(state.get("introduction")),
            "has_conclusion": bool(state.get("conclusion")),
        },
        "token_usage": state.get("token_usage") or {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "request_count": 0,
            "estimated_cost_usd": 0.0,
        },
        "final_phase": str(state.get("current_phase")),
        "errors": state.get("error_messages") or [],
        "report_path": state.get("report_path"),
    }
    logger.info(f"=== EVAL END | duration={metrics['duration_human']} ===")
    return metrics


def _safe_env(key: str, default: str) -> str:
    import os
    return os.getenv(key, default)


def _human_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


def save_metrics(metrics: Dict[str, Any]) -> Path:
    """Persist metrics JSON next to the generated report."""
    out_dir = Path("data/outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = re.sub(r"[^\w一-鿿\-\s]", "_", metrics["topic"])[:50].replace(" ", "")
    path = out_dir / f"eval_result_{safe_topic}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return path


def print_summary(metrics: Dict[str, Any], json_path: Path) -> None:
    tu = metrics["token_usage"]
    p = metrics["papers"]
    g = metrics["generated_text"]
    print("\n" + "=" * 60)
    print("Scira full-mode workflow — evaluation result")
    print("=" * 60)
    print(f"  Topic              : {metrics['topic']}")
    print(f"  Model              : {metrics['model']}")
    print(f"  Duration           : {metrics['duration_human']} ({metrics['duration_seconds']}s)")
    print(f"  Papers covered     : {p['search_results']} searched / "
          f"{p['downloaded_parsed']} parsed / {p['references']} referenced "
          f"({p['reading_errors']} parse errors)")
    print(f"  Generated text     : {g['final_review_chars']} chars "
          f"(~{g['total_word_units']} word units, {g['sections_written']} sections)")
    print(f"  Token usage        : {tu.get('total_input_tokens', 0)} in / "
          f"{tu.get('total_output_tokens', 0)} out / {tu.get('request_count', 0)} requests")
    print(f"  Estimated cost     : ${tu.get('estimated_cost_usd', 0):.4f}")
    print(f"  Final phase        : {metrics['final_phase']}")
    if metrics["errors"]:
        print(f"  Errors ({len(metrics['errors'])})   : {metrics['errors'][:3]}")
    print(f"  Report saved       : {metrics['report_path']}")
    print(f"  Metrics JSON       : {json_path}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one full-mode Scira workflow and collect metrics.")
    parser.add_argument("topic", nargs="?", default=DEFAULT_TOPIC, help="Research topic.")
    parser.add_argument("--max-papers", type=int, default=None,
                        help="Cap number of papers to download/parse (default: all pending).")
    args = parser.parse_args()

    metrics = run_eval(args.topic, max_papers=args.max_papers)
    json_path = save_metrics(metrics)
    print_summary(metrics, json_path)
    return 0 if metrics["final_phase"] in ("PipelinePhase.FINAL", "final") else 1


if __name__ == "__main__":
    raise SystemExit(main())
