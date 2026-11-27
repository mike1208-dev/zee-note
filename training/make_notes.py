"""
Makes rough notes with their correct fields, to train a small model for checker/writer.py.

    python -m training.make_notes --train 2000 --val 200 --test 200

The fields are chosen first and the notes are written from them by code, so the answer is always known and no AI is used.
The validation and test notes use subjects, details and status words that the training notes never have. The results go to data/notes/.
"""

import argparse
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from checker.writer import WriterError, extract, long_date

OUTPUT = Path("data/notes")
SPLITS = ("train", "val", "test")

# A trained model doesn't need the long rules of the app's prompt
SHORT_PROMPT = """Sort the notes into the fields of a daily report, as JSON. The report is for {day}, so "done" is the work of {done_days}. Use only facts from the notes.

Notes:
{notes}"""

SUBJECTS = """booking list|password reset form|checkout page|user profile|order history|search filter|payment form|admin dashboard|email template|login page
notification badge|report export|calendar view|product page|shopping cart|sign up form|file upload|settings page|invoice table|customer list
audit log|image gallery|date picker|access page|coupon form|shipping page|feedback form|chat window|navigation menu|price table
mobile menu|error page|help center|review list|stock counter|map view|video player|language switch|session timer|landing page
import tool|backup job|cache layer|queue worker|webhook handler|rate limiter|api gateway|database index|log viewer|deploy script
health check|unit test suite|onboarding checklist|release notes|api documentation|setup guide|design system|icon set|form validation|loading state""".replace("\n", "|").split("|")
DETAILS = """shows the wrong date|is too slow|breaks on small screens|loses the selected filter|has no error message|sends two emails|does not save changes|shows old data
fails for long names|has a wrong total|is missing a label|crashes with empty input|ignores the time zone|does not close|overlaps the header|logs out users
repeats the last item|hides the save button|counts deleted items|opens the wrong page|needs two clicks|keeps the old price|drops special characters|flickers on reload""".replace("\n", "|").split("|")
# past, base
VERBS = [("fixed", "fix"), ("added", "add"), ("updated", "update"), ("refactored", "refactor"), ("tested", "test"), ("improved", "improve"), ("removed", "remove"),
         ("investigated", "investigate"), ("documented", "document"), ("cleaned up", "clean up"), ("redesigned", "redesign"), ("checked", "check")]
LABELS = ["FEAT", "FIX", "CHORE", "BUG", "TEST", "REFACTOR", "DOCS"]
STATUSES = {
    "Merged": ["merged", "is merged", "got merged", "was merged yesterday evening", "already merged", "mergd", "マージ済み"],
    "In review": ["in review", "waiting for review", "is under review", "still in review", "awaiting review", "pending review", "レビュー待ち"],
    "Draft": ["draft", "is a draft", "still a draft", "draft only", "opened as draft"],
    "Open": ["open", "is open", "still open", "opened"],
    "Done": ["done", "finished", "completed", "all done", "is done", "✅"],
    "In progress": ["in progress", "still in progress", "wip", "ongoing", "not finished"],
}
OTHER_TASKS = [("had a sync with {name} about the {subject}", "Had a sync with {name} about the {subject}"), ("helped {name} with the {subject}", "Helped {name} with the {subject}"),
               ("practiced explaining the {subject}", "Practiced explaining the {subject}"), ("read about {subject} testing", "Read about {subject} testing"),
               ("reviewed the code of the {subject}", "Reviewed the code of the {subject}"), ("wrote notes about the {subject}", "Wrote notes about the {subject}")]
BLOCKERS = ["waiting for {name} to confirm the {subject}", "no access to the {subject}", "need the design of the {subject}", "can't reach the {subject} on staging",
            "waiting for the api of the {subject}", "need a decision about the {subject}"]
NO_BLOCKERS = ["no blockers", "blockers: none", "nothing is blocking me", "no blocker", "nothing blocking"]
OTHERS = ["off on friday", "the server restarts at noon", "new laptop arrived", "office is closed on monday"]
REMARKS = ["don't include lunch", "please don't mention the break", "do not list the small talk"]
NAMES = "Sam Lina Noah Mina Kai Yuki Omar Ella".split()
JAPANESE = [("ログイン画面の表示を直した", "Fixed the display of the login screen"), ("予約一覧の日付ずれを修正した", "Fixed the date shift in the reservation list"),
            ("通知一覧を確認した", "Checked the notification list"), ("検索機能を追加した", "Added the search feature"), ("資料を更新した", "Updated the documents"),
            ("決済画面のテストを書いた", "Wrote tests for the payment screen"), ("請求書の合計を直した", "Fixed the total of the invoice"), ("設定画面を改善した", "Improved the settings screen")]
DONE_WORDS = ["yesterday", "yday", "Yesterday", "ytd", "✅ yesterday"]
TODAY_WORDS = ["today", "tdy", "Today", "🎯 today", "today will", "plan for today"]
BLOCKER_WORDS = ["blocker", "blocked", "🚧", "blockers", "blocked by"]


def part(items: list, split: str) -> list:
    """
    Different items for each split, so a test never has the subjects or words of the training.
    """
    tests, vals = max(1, len(items) // 6), max(1, len(items) // 6)
    return {"test": items[:tests], "val": items[tests : tests + vals], "train": items[tests + vals :]}[split]


class Maker:
    def __init__(self, seed: int, split: str):
        self.r = random.Random(f"{split}-{seed}")
        self.split, self.numbers = split, set()
        self.subjects, self.details = part(SUBJECTS, split), part(DETAILS, split)
        # common words are in all splits, the rarer ones are split
        self.status_words = {status: words[:2] + part(words[2:], split) for status, words in STATUSES.items()}

    def maybe(self, chance: float) -> bool:
        return self.r.random() < chance

    def number(self) -> str:
        while True:
            number = str(self.r.choice([self.r.randint(10, 99), self.r.randint(100, 999), self.r.randint(1000, 4999)]))
            if number not in self.numbers:
                self.numbers.add(number)
                return number

    def subject(self) -> str:
        return self.r.choice(self.subjects)

    def fill(self, text: str) -> tuple[str, dict]:
        values = {"name": self.r.choice(NAMES), "subject": self.subject()}
        return text.format(**values), values

    def phrase(self, past: bool) -> tuple[str, str]:
        """
        (in the notes, the task)
        """
        verb = self.r.choice(VERBS)[0 if past else 1]
        article = "the " if self.maybe(0.5) else ""
        text = f"{verb} {article}{self.subject()}"
        return text, text[0].upper() + text[1:]

    def title(self) -> str:
        return f"{self.subject()} {self.r.choice(self.details)}"

    def status(self, pull: bool) -> tuple[str, str]:
        """
        (status, its words), both empty when the notes don't say it
        """
        if self.maybe(0.2):
            return "", ""
        status = self.r.choices(["Merged", "In review", "Draft", "Open"] if pull else ["Done", "In progress"], [6, 4, 1, 1] if pull else [3, 1])[0]
        return status, self.r.choice(self.status_words[status])

    def pull(self) -> tuple[str, dict]:
        number = self.number()
        status, words = self.status(pull=True)
        if self.maybe(0.12):
            ref = text = f"https://github.com/acme/app/pull/{number}"
        else:
            ref = f"PR #{number}"
            text = self.r.choice(["pr {}", "PR {}", "pr-{}", "PR #{}", "pull request {}"]).format(number)
        if not words and self.maybe(0.3):
            words = "not merged yet"  # says only what it isn't
        return f"{text} {words}".strip(), {"ref": ref, **({"status": status} if status else {})}

    def issue_text(self, number: str) -> str:
        return self.r.choice(["issue {}", "issue-{}", "Issue {}", "issue #{}"]).format(number)

    def done_task(self) -> tuple[str, dict]:
        kind = self.r.random()
        if kind < 0.4:  # an issue with a label, a title and PRs
            number, label, title = self.number(), self.r.choice(LABELS), self.title()
            shown = self.r.choice([label.lower(), f"[{label}]", label]) if self.maybe(0.75) else ""
            pulls = [self.pull() for _ in range(self.r.choices([0, 1, 2], [1, 8, 1])[0])]
            text = ", ".join([" ".join(filter(None, (self.issue_text(number), shown, title))), *(t for t, _ in pulls)])
            answer = {"issue": f"issue-{number}", **({"label": label} if shown else {}), "task": title[0].upper() + title[1:]}
        elif kind < 0.5:  # an issue without a title
            number = self.number()
            pulls = [self.pull()]
            text = f"{self.r.choice(['solved', 'fixed', 'closed'])} {self.issue_text(number)} ({pulls[0][0]})"
            answer = {"issue": f"issue-{number}"}
        elif kind < 0.75:  # only a PR
            text, task = self.phrase(past=True)
            pulls = [self.pull()]
            text, answer = f"{text}, {pulls[0][0]}", {"task": task}
        else:  # no numbers
            if self.maybe(0.1):
                text, task = self.r.choice(part(JAPANESE, self.split))
            elif self.maybe(0.35):
                rough, clean = self.r.choice(OTHER_TASKS)
                values = self.fill("{name}")[1]
                text, task = rough.format(**values), clean.format(**values)
            else:
                text, task = self.phrase(past=True)
            pulls = []
            status, words = self.status(pull=False)
            text = f"{text}{', ' if words and words != '✅' else ' '}{words}".strip()
            return text, {"task": task, **({"status": status} if status else {})}
        return text, {**answer, **({"refs": [ref for _, ref in pulls]} if pulls else {})}

    def plan(self) -> tuple[str, dict]:
        if self.maybe(0.4):
            number, title = self.number(), self.title()
            label = self.r.choice(LABELS) if self.maybe(0.6) else ""
            return " ".join(filter(None, (self.issue_text(number), label.lower(), title))), {"issue": f"issue-{number}", **({"label": label} if label else {}), "task": title[0].upper() + title[1:]}
        text, task = self.phrase(past=False)
        return text, {"task": task}

    def typos(self, text: str) -> str:
        """
        One or two wrong letters in longer words, never in numbers, links, names or status words.
        """
        words = text.split(" ")
        safe = {word for group in STATUSES.values() for phrase in group for word in phrase.split()} | {"yesterday", "today", "tomorrow", "blockers", "blocker", "issue", "pull", "request"}
        places = [i for i, word in enumerate(words) if re.fullmatch(r"[a-z]{6,}", word) and word not in safe]
        for i in self.r.sample(places, min(len(places), self.r.randint(1, 2))):
            word, at = words[i], self.r.randint(2, len(words[i]) - 2)
            words[i] = self.r.choice([word[:at] + word[at + 1 :], word[:at] + word[at + 1] + word[at] + word[at + 2 :]])
        return " ".join(words)

    def example(self) -> dict:
        """
        {"notes", "answer", "day"}
        """
        self.numbers = set()
        day = date(2026, 1, 5) + timedelta(days=self.r.randint(0, 360))
        while day.weekday() in (0, 5, 6):
            day += timedelta(days=1)  # Tuesday to Friday, so "yesterday" is a working day
        if self.maybe(0.02):
            return {"notes": self.r.choice(["hello good morning", "thanks", "test", "good morning team"]), "answer": {}, "day": day.isoformat()}

        done = [self.done_task() for _ in range(self.r.choices([0, 1, 2, 3, 4, 5], [1, 3, 5, 5, 3, 1])[0])]
        plans = [self.plan() for _ in range(self.r.choices([0, 1, 2, 3], [2, 6, 4, 1])[0])]
        if not done and not plans:
            plans = [self.plan()]
        answer: dict = {}
        if done:
            answer["done"] = [item for _, item in done]
        if plans:
            answer["plans"] = [item for _, item in plans]

        paragraph = self.maybe(0.25)
        done_word = self.r.choice(DONE_WORDS) if self.maybe(0.8) else ""
        today_word = self.r.choice(TODAY_WORDS)
        groups = []
        if done:
            texts = [text for text, _ in done]
            lines = [f"{done_word} {texts[0]}".strip(), *texts[1:]] if paragraph or self.maybe(0.5) else [*([f"{done_word}:"] if done_word else []), *texts]
            groups.append(lines)
        if plans:
            groups.append([f"{today_word}{self.r.choice([': ', ' '])}{text}" for text, _ in plans])
        kind = self.r.random()
        if kind < 0.4:
            text = self.fill(self.r.choice(part(BLOCKERS, self.split)))[0]
            groups.append([f"{self.r.choice(BLOCKER_WORDS)}: {text}"])
            answer["blockers"] = [text[0].upper() + text[1:]]
        elif kind < 0.75:
            groups.append([self.r.choice(NO_BLOCKERS)])
            answer["no_blockers"] = True
        extras = []
        if self.maybe(0.08):
            text, task = self.phrase(past=True)
            extras.append(f"last week {text}")
            answer["older"] = [task]
        if self.maybe(0.1):
            text, task = self.phrase(past=False)
            extras.append(f"tomorrow {text}")
            answer["later"] = [task]
        if self.maybe(0.08):
            text = self.r.choice(part(OTHERS, self.split))
            extras.append(text)
            answer["others"] = [text[0].upper() + text[1:]]
        if self.maybe(0.06):
            text = self.r.choice(part(REMARKS, self.split))
            extras.append(text)
            answer["remarks"] = [text[0].upper() + text[1:]]
        if self.maybe(0.06):
            name = self.r.choice(NAMES)
            groups.insert(0, [f"@{name} please check"])
            answer["reviewer"] = name
        if extras:
            groups.append(extras)
        if self.maybe(0.2):  # not always in the usual order
            self.r.shuffle(groups)

        lines = [line for group in groups for line in group]
        if paragraph:
            notes = self.r.choice([". ", "; "]).join(lines)
        else:
            bullet = self.r.choice(["", "", "", "- ", "• ", "* "])
            notes = "\n".join(bullet + line for line in lines)
        if self.maybe(0.3):
            notes = "\n".join(self.typos(line) for line in notes.split("\n"))
        if self.maybe(0.04):
            notes = notes.upper() if "http" not in notes else notes
        elif self.maybe(0.1):
            notes = notes.replace(", ", " ")
        return {"notes": notes, "answer": answer, "day": day.isoformat()}


def as_client(answer: dict):
    """
    Stands in for the AI service, so the app's own code can read an answer.
    """
    message = SimpleNamespace(content=json.dumps(answer, ensure_ascii=False))
    create = lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def problem_with(example: dict) -> str:
    """
    Why the app's fact check disagrees with the answer, or "". An example that the app itself would change teaches the wrong thing.
    """
    answer = example["answer"]
    try:
        draft = extract(example["notes"], client=as_client(answer), day=date.fromisoformat(example["day"]))
    except WriterError as e:
        return "" if not answer else str(e)
    if not answer:
        return "no tasks, but a report"
    for name in ("done", "plans"):
        if len(getattr(draft, name)) != len(answer.get(name, [])):
            return f"{name}: tasks were moved or dropped"
    for item, right in zip(draft.done, answer.get("done", [])):
        refs = {ref["ref"]: ref.get("status", "") for ref in right.get("refs", [])}
        if item.ref_statuses != refs or (not refs and item.status != right.get("status", "")):
            return "a status was not kept"
    for item, right in zip([*draft.done, *draft.plans], [*answer.get("done", []), *answer.get("plans", [])]):
        if item.issue != right.get("issue", "").removeprefix("issue-") or item.label != right.get("label", ""):
            return "an issue or label was not kept"
    if draft.no_blockers != answer.get("no_blockers", False) or len(draft.blockers) != len(answer.get("blockers", [])):
        return "blockers"
    wrong = [question for question in draft.questions if re.match(r"The AI added|Check this number|Your notes say both", question)]
    return wrong[0] if wrong else ""


def make(split: str, count: int, seed: int = 1) -> tuple[list[dict], dict[str, int]]:
    """
    The examples, and how often an example was dropped for which reason.
    """
    maker, examples, seen, dropped = Maker(seed, split), [], set(), {}
    while len(examples) < count:
        example = maker.example()
        reason = "same notes again" if example["notes"] in seen else problem_with(example)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            if sum(dropped.values()) > 20 * count + 100:
                raise SystemExit(f"Too many examples were dropped: {dropped}")
            continue
        seen.add(example["notes"])
        examples.append({"id": f"{split}-{len(examples) + 1}", **example})
    return examples, dropped


def to_chat(example: dict) -> dict:
    """
    An example in the shape that the Colab notebook trains on.
    """
    day = date.fromisoformat(example["day"])
    before = long_date(day - timedelta(days=1))
    prompt = SHORT_PROMPT.format(day=f"today ({long_date(day)})", done_days=f"yesterday ({before})", notes=example["notes"])
    answer = json.dumps(example["answer"], ensure_ascii=False)
    return {"prompt": [{"role": "user", "content": prompt}], "completion": [{"role": "assistant", "content": answer}]}


def write(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for split, count in zip(SPLITS, (2000, 200, 200)):
        parser.add_argument(f"--{split}", type=int, default=count)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    for split in SPLITS:
        examples, dropped = make(split, getattr(args, split), args.seed)
        write(OUTPUT / f"{split}_examples.jsonl", examples)
        if split != "test":
            write(OUTPUT / f"{split}.jsonl", [to_chat(example) for example in examples])
        print(f"{split}: {len(examples)} examples, dropped: {dropped}")


if __name__ == "__main__":
    main()
