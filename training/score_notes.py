"""
Scores a model on the made-up notes, through the app's own code.

    python -m training.score_notes --gguf model.gguf --name untrained
    python -m training.score_notes --gguf model.gguf --name trained --short
    python -m training.score_notes --groq qwen/qwen3.8-27b --name qwen

The answers are kept in data/notes/answers_<name>.jsonl, so a stopped run continues where it was. --short asks with the short prompt
that a model is trained on; without it, the app's prompt is used. Only made-up notes are sent to Groq: never use real ones here.
"""

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

from checker.writer import Draft, WriterError, extract
from training.make_notes import OUTPUT, as_client, to_chat, write

CONTEXT_TOKENS, MAX_ANSWER_TOKENS = 4096, 950


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()] if path.exists() else []


def words(text: str) -> set[str]:
    return {word[:4] for word in re.findall(r"\w+", text.lower())} - {"the", "a", "an"}


def likeness(one: str, other: str) -> float:
    a, b = words(one), words(other)
    return len(a & b) / len(a | b) if a | b else 1


def numbers(issue: str, refs) -> set[str]:
    return set(re.findall(r"\d+", issue)) | {number for ref in refs for number in re.findall(r"\d+", ref)[-1:]}


def flat(answer: dict) -> list[dict]:
    """
    The tasks of an expected answer, in the same shape as the ones of a draft.
    """
    tasks = []
    for place in ("done", "plans"):
        for item in answer.get(place, []):
            refs = {ref["ref"]: ref.get("status", "") for ref in item.get("refs", [])}
            tasks.append({"place": place, "issue": item.get("issue", "").removeprefix("issue-"), "task": item.get("task", ""), "status": item.get("status", ""), "refs": refs})
    return tasks


def flat_draft(draft: Draft) -> list[dict]:
    return [
        {"place": place, "issue": item.issue, "task": item.task, "status": item.status, "refs": {ref: item.ref_statuses.get(ref, "") for ref in item.refs}}
        for place in ("done", "plans")
        for item in getattr(draft, place)
    ]


def match(expected: list[dict], found: list[dict]) -> list[tuple[dict, dict | None]]:
    """
    Each expected task with the found one that is most like it: by its numbers first, then by its words.
    """
    left, pairs = list(found), []
    for task in expected:
        own = numbers(task["issue"], task["refs"])

        def score(other, task=task, own=own):
            same_numbers = len(own & numbers(other["issue"], other["refs"])) * 2
            return same_numbers + likeness(task["task"], other["task"]) + 0.1 * (task["place"] == other["place"])

        best = max(left, key=score, default=None)
        if best is not None and score(best) < 0.55:
            best = None
        if best is not None:
            left.remove(best)
        pairs.append((task, best))
    return pairs


def by_number(refs: dict[str, str]) -> dict[str, str]:
    return {re.findall(r"\d+", ref)[-1]: status for ref, status in refs.items() if re.search(r"\d", ref)}


def compare(answer: dict, draft: Draft | None) -> dict:
    """
    The counts for one example. "wrong" are facts that the report states wrongly; a wrong one is "silent" if no question is about it.
    """
    expected = flat(answer)
    result = {"tasks": len(expected), "found": 0, "place": 0, "fields": 0, "fields_right": 0, "invented": 0, "wrong": 0, "silent": 0, "readable": 1}
    if draft is None:  # no report
        result.update(readable=0 if expected else 1, fields=0)
        return result
    found = flat_draft(draft)
    pairs = match(expected, found)

    def wrong(text: str):
        result["wrong"] += 1
        # a question about it names its number, or most of its words
        about = [question for question in draft.questions if (set(re.findall(r"\d+", text)) & set(re.findall(r"\d+", question))) or (words(text) and len(words(text) & words(question)) / len(words(text)) > 0.6)]
        result["silent"] += not about

    for task, other in pairs:
        if other is None:
            wrong(f"{task['issue']} {task['task']} {' '.join(task['refs'])}")  # a lost task
            continue
        result["found"] += 1
        result["place"] += task["place"] == other["place"]
        if task["place"] != other["place"]:
            wrong(f"{other['issue']} {other['task']}")
        right_refs, refs = by_number(task["refs"]), by_number(other["refs"])
        checks = [(task["issue"], other["issue"]), (set(right_refs), set(refs))]
        if task["place"] == "done":
            checks += [(status, refs.get(number, "")) for number, status in right_refs.items()] or [(task["status"], other["status"])]
        result["fields"] += len(checks)
        for right, value in checks:
            result["fields_right"] += right == value
            if right != value and value and (isinstance(value, str) or not value <= right):  # an empty field is missing, not wrong
                wrong(f"{other['issue']} {other['task']} {' '.join(other['refs'])}")
    used = [id(other) for _, other in pairs if other is not None]
    for other in found:
        if id(other) not in used:
            result["invented"] += 1
            wrong(f"{other['issue']} {other['task']}")
    right_blockers = answer.get("blockers", [])
    if draft.no_blockers and not answer.get("no_blockers"):
        wrong("blockers")
    result["blockers"], result["blockers_found"] = len(right_blockers), sum(any(likeness(text, other) > 0.5 for other in draft.blockers) for text in right_blockers)
    result["questions"] = len(draft.questions)
    return result


def summary(results: list[dict]) -> dict:
    def total(key):
        return sum(result.get(key, 0) for result in results)

    def share(part, whole):
        return round(100 * total(part) / total(whole), 1) if total(whole) else None

    return {
        "notes": len(results),
        "readable answers %": round(100 * total("readable") / len(results), 1) if results else None,
        "tasks found %": share("found", "tasks"),
        "right section %": share("place", "found"),
        "right fields %": share("fields_right", "fields"),
        "blockers found %": share("blockers_found", "blockers"),
        "invented tasks": total("invented"),
        "reports with a wrong fact and no warning": sum(result["silent"] > 0 for result in results),
        "points to check per report": round(total("questions") / len(results), 1) if results else None,
    }


def gguf_model(path: str):
    from llama_cpp import Llama

    from checker.local_model import threads

    llm = Llama(model_path=path, n_ctx=CONTEXT_TOKENS, n_threads=threads(), n_threads_batch=threads(), verbose=False)

    def ask(prompt: str) -> str:
        llm.reset()
        response = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=MAX_ANSWER_TOKENS, response_format={"type": "json_object"}
        )
        return response["choices"][0]["message"]["content"]

    return ask


def groq_model(model: str):
    from dotenv import load_dotenv

    load_dotenv()
    from groq import Groq

    from checker.llm_checks import token_cap

    client = Groq()
    options = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}  # as in the app

    def ask(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"}, **options, **token_cap(model, MAX_ANSWER_TOKENS)
        )
        return response.choices[0].message.content

    return ask


def app_prompt(example: dict) -> str:
    """
    The prompt that the app would send.
    """
    sent = []

    class Stop(WriterError):
        pass

    def create(messages, **_):
        sent.append(messages[0]["content"])
        raise Stop

    client = as_client({})
    client.chat.completions.create = create
    try:
        extract(example["notes"], client=client, day=date.fromisoformat(example["day"]))
    except WriterError:
        pass
    return sent[0]


def draft_of(example: dict, text: str | None) -> Draft | None:
    """
    What the app makes of an answer, or None if there is no report.
    """
    try:
        answer = json.loads(text or "", strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(answer, dict):
        return None
    try:
        return extract(example["notes"], client=as_client(answer), day=date.fromisoformat(example["day"]))
    except WriterError:
        return None


def run(examples: list[dict], ask, path: Path, short: bool = False) -> list[dict]:
    """
    Asks for the answers that aren't in the file yet. Stops at the first error, and continues there the next time.
    """
    rows = read(path)
    done = {row["id"] for row in rows}
    for example in examples:
        if example["id"] in done:
            continue
        prompt = to_chat(example)["prompt"][0]["content"] if short else app_prompt(example)
        started = time.perf_counter()
        text = ask(prompt)
        rows.append({"id": example["id"], "text": text, "seconds": round(time.perf_counter() - started, 1)})
        write(path, rows)
        print(f"{len(rows)} of {len(examples)}: {rows[-1]['seconds']} s", flush=True)
    return rows


def score(examples: list[dict], rows: list[dict]) -> dict:
    texts = {row["id"]: row for row in rows}
    answered = [example for example in examples if example["id"] in texts]
    results = [compare(example["answer"], draft_of(example, texts[example["id"]]["text"])) for example in answered]
    seconds = sorted(texts[example["id"]]["seconds"] for example in answered)
    return {**summary(results), "seconds per report (middle)": seconds[len(seconds) // 2] if seconds else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="name of the answers file")
    parser.add_argument("--file", type=Path, default=OUTPUT / "test_examples.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="only the first notes")
    parser.add_argument("--short", action="store_true", help="the short prompt of a trained model")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--gguf", help="a model file on this computer")
    where.add_argument("--groq", help="a Groq model")
    args = parser.parse_args()
    examples = read(args.file)[: args.limit or None]
    path = OUTPUT / f"answers_{args.name}.jsonl"
    rows = run(examples, gguf_model(args.gguf) if args.gguf else groq_model(args.groq), path, args.short) if args.gguf or args.groq else read(path)
    scores = score(examples, rows)
    write(OUTPUT / f"scores_{args.name}.json", [scores])
    for name, value in scores.items():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
