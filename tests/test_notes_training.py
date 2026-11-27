import ast
import json
from pathlib import Path

import pytest

import training.score_notes
from training.make_notes import DETAILS, SPLITS, SUBJECTS, Maker, make, part, problem_with, to_chat
from training.score_notes import compare, draft_of, read, run, score

NOTES = "issue 95 fix booking list shows the wrong date, pr 102 merged\npracticed explaining the menu, done\ntoday test the menu\nno blockers"
ANSWER = {
    "done": [
        {"issue": "issue-95", "label": "FIX", "task": "Booking list shows the wrong date", "refs": [{"ref": "PR #102", "status": "Merged"}]},
        {"task": "Practiced explaining the menu", "status": "Done"},
    ],
    "plans": [{"task": "Test the menu"}],
    "no_blockers": True,
}
EXAMPLE = {"id": "test-1", "notes": NOTES, "answer": ANSWER, "day": "2026-11-25"}


def changed(**parts):
    return json.loads(json.dumps({**ANSWER, **parts}))


def result(answer):
    return compare(ANSWER, draft_of(EXAMPLE, json.dumps(answer)))


def test_the_same_seed_gives_the_same_examples():
    first, dropped = make("train", 40)
    assert first == make("train", 40)[0] and first != make("train", 40, seed=2)[0]
    assert len({example["notes"] for example in first}) == 40 and sum(dropped.values()) < 40


def test_every_answer_agrees_with_the_apps_fact_check():
    for split in SPLITS:
        for example in make(split, 40)[0]:
            assert problem_with(example) == ""
            assert len(example["answer"].get("done", [])) <= 5


def test_the_splits_have_different_subjects_and_details():
    for items in (SUBJECTS, DETAILS):
        parts = [set(part(items, split)) for split in SPLITS]
        assert not parts[0] & parts[1] and not parts[0] & parts[2] and not parts[1] & parts[2]
        assert set().union(*parts) == set(items)
    assert not {example["notes"] for example in make("train", 60)[0]} & {example["notes"] for example in make("test", 60)[0]}


def test_numbers_links_and_statuses_have_no_typos():
    maker = Maker(1, "train")
    text = "issue 927 language switch, https://github.com/acme/app/pull/2244 merged, waiting for review yesterday"
    for _ in range(50):
        changed_text = maker.typos(text)
        assert "issue 927" in changed_text and "https://github.com/acme/app/pull/2244 merged, waiting for review yesterday" in changed_text


@pytest.mark.parametrize(
    "answer, reason",
    [
        (changed(done=[{**ANSWER["done"][0], "refs": [{"ref": "PR #102", "status": "In review"}]}, ANSWER["done"][1]]), "status"),
        (changed(done=[{**ANSWER["done"][0], "refs": [{"ref": "PR #7"}]}, ANSWER["done"][1]]), "status"),
        (changed(done=[{**ANSWER["done"][0], "issue": "issue-7"}, ANSWER["done"][1]]), "issue"),
        (changed(no_blockers=False, blockers=[]), ""),
    ],
)
def test_answers_that_the_app_would_change_are_dropped(answer, reason):
    assert reason in problem_with({**EXAMPLE, "answer": answer}) and (reason or problem_with({**EXAMPLE, "answer": answer}) == "")


def test_notes_without_tasks_have_an_empty_answer():
    assert problem_with({"notes": "hello good morning", "answer": {}, "day": "2026-11-25"}) == ""


def test_chat_examples_have_the_day_and_a_readable_answer():
    chat = to_chat(EXAMPLE)
    assert "Wednesday, November 25th" in chat["prompt"][0]["content"] and "Tuesday, November 24th" in chat["prompt"][0]["content"]
    assert json.loads(chat["completion"][0]["content"]) == ANSWER


def test_a_right_answer_has_no_mistakes():
    scores = result(ANSWER)
    assert scores["found"] == scores["tasks"] == scores["place"] == 3 and scores["fields"] == scores["fields_right"]
    assert scores["wrong"] == scores["silent"] == scores["invented"] == 0


@pytest.mark.parametrize(
    "answer, wrong, silent",
    [
        # a lost task, and the app asks about the lost part of the notes
        (changed(done=ANSWER["done"][:1]), 1, 0),
        # an invented task is doubtful, so the app asks
        (changed(plans=[*ANSWER["plans"], {"task": "Prepare the quarterly revenue forecast"}]), 1, 0),
        # a status that the notes don't give is left out by the app, so it isn't wrong
        (changed(done=[{**ANSWER["done"][0], "refs": [{"ref": "PR #102", "status": "Draft"}]}, ANSWER["done"][1]]), 0, 0),
        # a plan under the finished tasks, without any question about it
        (changed(done=[*ANSWER["done"], {"task": "Test the menu", "status": ""}], plans=[]), 0, 0),
    ],
)
def test_mistakes(answer, wrong, silent):
    scores = result(answer)
    assert scores["wrong"] == wrong and scores["silent"] == silent


def test_a_wrong_fact_without_a_warning_is_silent():
    notes = NOTES.replace("today test the menu", "test the menu")
    example = {**EXAMPLE, "notes": notes}
    answer = changed(done=[*ANSWER["done"], {"task": "Test the menu", "status": "Done"}], plans=[])
    draft = draft_of(example, json.dumps(answer))
    draft.questions = []
    scores = compare(ANSWER, draft)
    assert scores["wrong"] >= 1 and scores["silent"] == scores["wrong"]


@pytest.mark.parametrize("text", ["not json", "[]", None, "{}"])
def test_no_report(text):
    scores = compare(ANSWER, draft_of(EXAMPLE, text))
    assert scores["readable"] == 0 and scores["found"] == 0
    empty = {**EXAMPLE, "notes": "hello good morning", "answer": {}}
    assert compare({}, draft_of(empty, "{}"))["readable"] == 1


def test_run_continues_after_a_stop(tmp_path):
    examples = [EXAMPLE, {**EXAMPLE, "id": "test-2"}]
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 2:
            raise ConnectionError("stopped")
        return json.dumps(ANSWER)

    path = tmp_path / "answers.jsonl"
    with pytest.raises(ConnectionError):
        run(examples, ask, path)
    rows = run(examples, ask, path, short=True)
    assert len(rows) == len(read(path)) == 2 and len(prompts) == 3
    assert "You sort an engineer's plain notes" in prompts[0] and "You sort" not in prompts[2] and NOTES in prompts[0] and NOTES in prompts[2]
    scores = score(examples, rows)
    assert scores["notes"] == 2 and scores["right fields %"] == scores["tasks found %"] == 100 and scores["reports with a wrong fact and no warning"] == 0


def test_the_notebook_has_valid_code_and_uses_functions_that_exist():
    notebook = json.loads((Path(__file__).parent.parent / "training" / "notes_lora.ipynb").read_text(encoding="utf-8"))
    lines = [line for cell in notebook["cells"] if cell["cell_type"] == "code" for line in "".join(cell["source"]).splitlines()]
    plain = "\n".join(line.replace(line.strip(), "pass") if line.strip().startswith(("!", "%")) else line for line in lines)
    names = {alias.name for node in ast.walk(ast.parse(plain)) if isinstance(node, ast.ImportFrom) and node.module == "training.score_notes" for alias in node.names}
    assert names and all(hasattr(training.score_notes, name) for name in names)
