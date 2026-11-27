"""
Step 4: scores a model on labelled rule checks, through the same code as the app.

    python -m training.evaluate data/training/test.jsonl --name untrained
    python -m training.evaluate data/training/test.jsonl --name groq --model qwen/qwen3.8-27b

Each line of the file needs report_id, rule_id, question, text and label ("pass" or "fail"). The known terms of the rules in
rules/daily_report.yaml are used, as in the app. If it stops, run the same command again to continue. The default model
is the local one (LOCAL_MODEL_* in .env), so nothing is sent anywhere. Never use a Groq model on real reports
unless the team has approved it.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # before checker.llm_checks reads GROQ_MODEL

from checker import local_model  # noqa: E402
from checker.llm_checks import llm_check  # noqa: E402
from checker.result import FAIL, PASS, SKIP  # noqa: E402
from checker.styles import load_styles  # noqa: E402
from training.generate_examples import read_rows  # noqa: E402

RESULTS = Path("data/results")
VERDICTS = {PASS: "pass", FAIL: "fail"}  # anything else is "unsure" (also when the answer is unreadable)


def model_version(model: str) -> str:
    """
    Which model gives the answers, so answers of another one aren't reused.
    """
    if model != local_model.MODEL_ID:
        return model
    path = os.getenv("LOCAL_MODEL_PATH")
    if path:
        return f"{path} {os.stat(path).st_size} {os.stat(path).st_mtime_ns}"
    return f"{os.getenv('LOCAL_MODEL_REPO')} {os.getenv('LOCAL_MODEL_FILE')}"


def run(examples: list[dict], model: str, client=None, partial: Path | None = None) -> pd.DataFrame:
    """
    partial: where the answers are saved one by one, to continue after a stop.
    """
    known_terms = {rule["id"]: rule.get("known_terms") for rule in load_styles()["daily_report"].rules}
    version = model_version(model)
    saved = {row["key"]: row for row in read_rows(partial)} if partial else {}
    if client is None and model != local_model.MODEL_ID:
        from groq import Groq

        client = Groq(max_retries=8)
    rows = []
    for number, example in enumerate(examples, start=1):
        rule = {"id": example["rule_id"], "check": "llm", "question": example["question"], "known_terms": known_terms.get(example["rule_id"])}
        key = hashlib.sha256(json.dumps([number, version, rule, example["text"], example["label"]]).encode()).hexdigest()
        if key not in saved:
            started = time.perf_counter()
            result = llm_check(example["text"], rule, model=model, client=client)
            if result.status == SKIP:
                kept = f"{len(rows)} answers are saved. Run the same command again to continue." if partial else "Nothing was scored."
                raise SystemExit(f"Stopped: {result.message}\n{kept}")
            saved[key] = {
                "key": key,
                "report_id": example["report_id"],
                "rule_id": example["rule_id"],
                "label": example["label"],
                "verdict": VERDICTS.get(result.status, "unsure"),
                "message": result.message,
                "seconds": time.perf_counter() - started,
            }
            if partial:
                partial.parent.mkdir(parents=True, exist_ok=True)
                with partial.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(saved[key]) + "\n")
        rows.append({name: value for name, value in saved[key].items() if name != "key"})
        print(f"{number}/{len(examples)}", end="\r", flush=True)
    return pd.DataFrame(rows)


def scores(results: pd.DataFrame) -> dict:
    """
    "unsure" is never counted as correct: it isn't a found rule break, and it isn't a pass.
    """
    breaks = results[results.label == "fail"]
    good = results[results.label == "pass"]
    false_alarms = int((good.verdict == "fail").sum())
    return {
        "checks": len(results),
        "rule breaks": len(breaks),
        "rule breaks found": (breaks.verdict == "fail").mean() if len(breaks) else None,
        "good checks": len(good),
        "false alarms": false_alarms,
        "false alarms per report": false_alarms / results.report_id.nunique(),
        "accuracy": (results.verdict == results.label).mean(),
        "unsure": int((results.verdict == "unsure").sum()),
        "seconds per check": results.seconds.mean(),
    }


def score_table(results: pd.DataFrame) -> pd.DataFrame:
    table = {"ALL": scores(results)}
    for rule_id, part in results.groupby("rule_id"):
        table[rule_id] = scores(part)
    return pd.DataFrame(table).T


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--name", required=True, help="name for the result files, e.g. untrained")
    parser.add_argument("--model", default=local_model.MODEL_ID)
    args = parser.parse_args()
    if args.model == local_model.MODEL_ID and not local_model.is_configured():
        raise SystemExit("Set LOCAL_MODEL_REPO and LOCAL_MODEL_FILE (or LOCAL_MODEL_PATH) in .env first.")

    if not args.file.exists():
        raise SystemExit(f"There is no file {args.file}.")
    stem = f"{args.name}_{args.file.stem}"
    partial = RESULTS / f"{stem}_partial.jsonl"
    results = run(read_rows(args.file), args.model, partial=partial)
    RESULTS.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS / f"{stem}_answers.csv", index=False, encoding="utf-8-sig")
    table = score_table(results)
    table.to_csv(RESULTS / f"{stem}_scores.csv", encoding="utf-8-sig")
    partial.unlink(missing_ok=True)
    print(table.T.to_string())
