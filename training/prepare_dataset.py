"""
Step 2: turns the kept pairs into train.jsonl, val.jsonl and test.jsonl, plus review.csv for checking by hand.

    python -m training.prepare_dataset

Delete a bad pair by adding its ID (from review.csv) to data/training/rejected.txt, one per line, and run it again.
"""

import json
import random
from pathlib import Path

import pandas as pd

from checker.llm_checks import MAX_CHARS, PROMPT
from training.generate_examples import OUTPUT, ai_rules, is_current, read_rows

FOLDER = OUTPUT.parent
VAL_SHARE = 0.1  # to choose the best version during training
TEST_SHARE = 0.1  # for the score, so never used in training
REVIEW_PER_RULE = 5


def to_examples(row: dict) -> list[dict]:
    pair_id = f"{row['rule_id']}-{row['attempt']}"
    answers = [
        ("pass", row["good"], {"verdict": "pass", "reason": row["good_reason"], "quote": ""}),
        ("fail", row["broken"], {"verdict": "fail", "reason": row["broken_reason"], "quote": row["broken_quote"]}),
    ]
    return [
        {
            "report_id": f"{pair_id}-{label}",
            "rule_id": row["rule_id"],
            "question": row["question"],
            "text": text,
            "label": label,
            # The same prompt as the app, so the model is trained on what it will be asked
            "prompt": [{"role": "user", "content": PROMPT.format(question=row["question"], text=text[:MAX_CHARS])}],
            "completion": [{"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}],
        }
        for label, text, answer in answers
    ]


def split(rows: list[dict]) -> dict[str, list[dict]]:
    """
    Splits by pair (both halves stay together) and by rule, so every rule is in all parts.
    """
    parts = {"train": [], "val": [], "test": []}
    for rule_id in sorted({row["rule_id"] for row in rows}):
        mine = sorted((row for row in rows if row["rule_id"] == rule_id), key=lambda row: row["attempt"])
        random.Random(rule_id).shuffle(mine)
        val, test = (max(1, round(len(mine) * share)) if len(mine) > 2 else 0 for share in (VAL_SHARE, TEST_SHARE))
        parts["val"] += mine[:val]
        parts["test"] += mine[val : val + test]
        parts["train"] += mine[val + test :]
    return parts


def write(path: Path, examples: list[dict]) -> None:
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")


def prepare(folder: Path = FOLDER) -> dict[str, int]:
    rejected_file = folder / "rejected.txt"
    rules = {rule["id"]: rule for rule in ai_rules()}
    rejected = set(rejected_file.read_text(encoding="utf-8").split()) if rejected_file.exists() else set()
    kept = [
        row
        for row in read_rows(folder / OUTPUT.name)
        if row["kept"] and row["rule_id"] in rules and f"{row['rule_id']}-{row['attempt']}" not in rejected
    ]
    rows = [row for row in kept if is_current(row, rules[row["rule_id"]])]
    if len(rows) < len(kept):
        print(f"Left out {len(kept) - len(rows)} pairs made for an older question. Make new ones with training.generate_examples.")
    sizes = {}
    for name, part in split(rows).items():
        examples = [example for row in part for example in to_examples(row)]
        random.Random(0).shuffle(examples)
        write(folder / f"{name}.jsonl", examples)
        sizes[name] = len(examples)

    review = []
    for rule_id in sorted({row["rule_id"] for row in rows}):
        mine = [row for row in rows if row["rule_id"] == rule_id]
        review += random.Random(rule_id).sample(mine, min(REVIEW_PER_RULE, len(mine)))
    columns = ["rule_id", "attempt", "question", "good", "good_reason", "broken", "broken_reason", "broken_quote"]
    table = pd.DataFrame(review, columns=columns)
    table.insert(0, "pair_id", [f"{row['rule_id']}-{row['attempt']}" for row in review])
    table.to_csv(folder / "review.csv", index=False, encoding="utf-8-sig")
    return sizes


if __name__ == "__main__":
    for name, size in prepare().items():
        print(f"{name}: {size} examples")
    print(f"Check {FOLDER / 'review.csv'} by hand before training.")
