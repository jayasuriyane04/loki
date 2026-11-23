"""Run LOKI's offline evaluations against the real models.

    cd backend
    .\\.venv\\Scripts\\python.exe -m eval.run rag            # retrieval benchmark (Precision/Recall/NDCG/MRR)
    .\\.venv\\Scripts\\python.exe -m eval.run rag --answers  # + answer correctness, citations, faithfulness
    .\\.venv\\Scripts\\python.exe -m eval.run agent          # tool selection, task completion, recovery
    .\\.venv\\Scripts\\python.exe -m eval.run voice          # WER, STT latency, time to first audio, barge-in

Needs Ollama (scripts/start-ollama.ps1) and Postgres (docker compose up -d postgres). Uses the database in
EVAL_DATABASE_URL (default: loki_eval on the local Postgres), which is wiped first. Reports are written to
eval/results/ and appear on the Analytics page.
"""

import argparse
import json
import sys
import time


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suite", choices=["rag", "agent", "voice"])
    ap.add_argument("--answers", action="store_true", help="rag: also generate and score answers with the LLM")
    ap.add_argument("--no-judge", action="store_true", help="rag --answers: skip the LLM faithfulness judge")
    ap.add_argument("--repeat", type=int, default=1, help="agent: run every scenario N times")
    args = ap.parse_args()

    from eval.common import prepare_environment

    prepare_environment(voice=args.suite == "voice")
    from fastapi.testclient import TestClient

    from app.main import app

    t0 = time.time()
    with TestClient(app) as client:
        if args.suite == "rag":
            from eval import rag

            path = rag.run(client, app, answers=args.answers, judge=args.answers and not args.no_judge)
        elif args.suite == "agent":
            from eval import agent

            path = agent.run(client, app, repeat=args.repeat)
        else:
            from eval import voice

            path = voice.run(client, app)
    report = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(report["headline"], indent=2))
    print(f"\nReport: {path}  ({time.time() - t0:.0f} s)", file=sys.stderr)


if __name__ == "__main__":
    main()
