"""Explicit local/live M11 evaluation and offline human adjudication CLI.

Run from the repository root with the project interpreter. Results are local;
source samples are authored fixtures. This does not execute repository commands.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile

from scripts.evaluate_agents import MeasuredProvider, adjudicate_row, load_corpus, review_input, run_case, summarize


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", action="store_true", help="Scripted harness check; never measures model quality")
    mode.add_argument("--live", action="store_true", help="Explicit paid provider run; requires model tiers, rates and cost cap")
    mode.add_argument("--rescore", type=Path, help="Existing local results; no provider calls")
    result.add_argument("--output", type=Path, required=True, help="New result file; existing files are refused")
    result.add_argument("--mode", choices=("specialist", "full", "both"), default="both")
    result.add_argument('--evidence-mode', choices=('autonomous','provided'), default='autonomous',
                        help='Specialist source retrieval or supplied immutable source; acknowledgments remain required')
    result.add_argument("--case", action="append", choices=[case["case_id"] for case in load_corpus()])
    result.add_argument("--rates", type=Path, help="JSON model -> input_per_million/output_per_million USD; supply current rates")
    result.add_argument("--max-cost-usd", type=float, help="Conservative supplied-rate estimate cap, not a billing guarantee")
    result.add_argument("--judgments", type=Path, help="JSON case_id:mode -> findings/tools annotations")
    return result


async def execute(args, provider, models, stream):
    rows = []
    cases = [case for case in load_corpus() if not args.case or case["case_id"] in args.case]
    modes = ("specialist", "full") if args.mode == "both" else (args.mode,)
    judgments = json.loads(args.judgments.read_text(encoding="utf-8")) if args.judgments else {}
    from langsmith import tracing_context
    with tempfile.TemporaryDirectory(prefix="devwatch-m11-evaluation-") as runtime, tracing_context(enabled=False, parent=False):
        for index, case in enumerate(cases):
            for mode in modes:
                if args.fixture:
                    from tests.evaluation_provider import EvaluationProvider
                    current_provider = MeasuredProvider(EvaluationProvider(review_input(case)))
                else:
                    current_provider = provider
                row = await run_case(case, Path(runtime) / f"case-{index}-{mode}", mode=mode,
                                     provider=current_provider, live=args.live, models=models,
                                     evidence_mode=args.evidence_mode)
                key = case["case_id"] + ":" + mode
                if key in judgments:
                    row = adjudicate_row(row, judgments[key])
                rows.append(row)
                document = {**summarize(rows, live=args.live), "planned_runs": len(cases) * len(modes),
                            "complete": len(rows) == len(cases) * len(modes), "results": rows}
                stream.seek(0)
                json.dump(document, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
                print(json.dumps({"case_id": case["case_id"], "mode": mode, "status": row["status"],
                                  "score": row["score"], "metrics": row["metrics"]}), flush=True)
                if args.live and row["metrics"]["unknown_provider_calls"]:
                    # Preserve observed results; do not repeat an unavailable or
                    # uncertain paid-provider run throughout the remaining corpus.
                    return document
    return document


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.evidence_mode=='provided' and args.mode!='specialist':
        arguments.error('provided evidence requires --mode specialist')
    if args.output.exists():
        arguments.error("output already exists; choose a new file")
    provider, models = None, None
    if args.live:
        if not args.rates or args.max_cost_usd is None:
            arguments.error("live runs require --rates and --max-cost-usd")
        from devwatch.providers.openai_adapter import OpenAIProviderAdapter
        from devwatch.review.service import ServiceSettings
        models = ServiceSettings.from_env().models
        configured = OpenAIProviderAdapter(provider_name=os.getenv("DEVWATCH_PROVIDER", "openai"), request_delay=0)
        if not configured.is_available():
            arguments.error("configured provider credentials are unavailable")
        rates = json.loads(args.rates.read_text(encoding="utf-8"))
        if set(models.values()) - set(rates):
            arguments.error("rates are required for every configured model")
        provider = MeasuredProvider(configured, rates=rates, max_cost_usd=args.max_cost_usd)
    if args.rescore:
        if not args.judgments:
            arguments.error("rescoring requires --judgments")
        document = json.loads(args.rescore.read_text(encoding="utf-8"))
        judgments = json.loads(args.judgments.read_text(encoding="utf-8"))
        rows = [adjudicate_row(row, judgments[row["case_id"] + ":" + row["mode"]])
                if row["case_id"] + ":" + row["mode"] in judgments else row for row in document["results"]]
        document.update(summarize(rows, live=document["mode"] == "live-model"), results=rows)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write("\n")
    else:
        with args.output.open("x+", encoding="utf-8") as stream:
            document = asyncio.run(execute(args, provider, models, stream))
    print(json.dumps({key: value for key, value in document.items() if key != "results"}))
    # Harness execution and quality are distinct outcomes; no invented accuracy gate.
    return 0 if document["complete"] and all(row["status"] == "completed" for row in document["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
