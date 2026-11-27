import json
from types import SimpleNamespace

import pandas as pd
import pytest

from checker.llm_checks import PROMPT, token_cap
from training.evaluate import run, scores
from training.generate_examples import BREAKS, JUDGE, WRITER, StopRun, ai_rules, generate, make_pair, make_prompt, problem_with, read_rows
from training.prepare_dataset import prepare, split, to_examples

PAIR = {
    "good": "Yesterday\n- Added the reset form (Merged)",
    "good_reason": "The task is concrete.",
    "broken": "Yesterday\n- Worked on the form (Merged)",
    "broken_reason": "It doesn't say what changed.",
    "broken_quote": "Worked on the form",
}


class FakeGroq:
    """Writes PAIR, and judges reports with the given verdicts."""

    def __init__(self, good="pass", broken="fail", pair=PAIR):
        self.pair, self.verdicts, self.calls = pair, {PAIR["good"]: good, PAIR["broken"]: broken}, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **_):
        self.calls.append(model)
        if model == WRITER:
            content = json.dumps(self.pair)
        else:
            verdict = next(v for text, v in self.verdicts.items() if text in messages[0]["content"])
            if verdict == "limit":
                raise ConnectionError("rate limit")
            content = json.dumps({"verdict": verdict, "reason": "", "quote": ""})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


RULE = next(rule for rule in ai_rules() if rule["id"] == "concrete_tasks")


def test_every_ai_rule_has_ways_to_break_it():
    assert {rule["id"] for rule in ai_rules()} == set(BREAKS)
    assert WRITER != JUDGE
    for rule in ai_rules():
        assert rule["question"] in make_prompt(rule, 1)
        assert make_prompt(rule, 1) == make_prompt(rule, 1)


@pytest.mark.parametrize(
    "change, expected",
    [
        ({}, ""),
        ({"good": ""}, "missing"),
        ({"broken": PAIR["good"]}, "same"),
        ({"broken_quote": ""}, "no quote"),
        ({"broken_quote": "not there"}, "isn't in"),
        ({"broken_quote": None}, "missing"),
        ({"good": "Yesterday\\n- Added the reset form"}, "raw codes"),
        ({"good": "U0001F4C5 Yesterday"}, "raw codes"),
        ({"good": "**Yesterday**\n- Added the reset form (Merged)"}, "formatting"),
    ],
)
def test_problem_with(change, expected):
    problem = problem_with({**PAIR, **change})
    assert expected in problem and bool(problem) == bool(expected)


def test_generate_keeps_agreed_pairs_and_continues(tmp_path):
    path = tmp_path / "pairs.jsonl"
    generate([RULE], 2, FakeGroq(), path)
    assert [row["kept"] for row in read_rows(path)] == [True, True]
    generate([RULE], 3, client := FakeGroq(), path)
    assert len(read_rows(path)) == 3
    assert client.calls.count(WRITER) == 1
    assert [row["attempt"] for row in read_rows(path)] == [1, 2, 3]


def test_generate_drops_pairs_the_judge_disagrees_with_and_gives_up(tmp_path):
    path = tmp_path / "pairs.jsonl"
    generate([RULE], 1, FakeGroq(broken="pass"), path)
    rows = read_rows(path)
    assert len(rows) == 3 and not any(row["kept"] for row in rows)


def test_generate_records_the_writer(tmp_path):
    path = tmp_path / "pairs.jsonl"
    generate([RULE], 1, FakeGroq(), path)
    assert read_rows(path)[0]["writer"] == WRITER


def test_a_limit_stops_the_run_instead_of_counting_as_disagreement(tmp_path):
    path = tmp_path / "pairs.jsonl"
    with pytest.raises(StopRun):
        generate([RULE], 1, FakeGroq(good="limit"), path)
    assert read_rows(path) == []


def make_rows(count, rule_id="concrete_tasks"):
    return [{**PAIR, "rule_id": rule_id, "question": RULE["question"], "attempt": i, "kept": True} for i in range(1, count + 1)]


def test_examples_use_the_apps_prompt():
    good, broken = to_examples(make_rows(1)[0])
    assert good["prompt"][0]["content"] == PROMPT.format(question=RULE["question"], text=PAIR["good"])
    assert json.loads(broken["completion"][0]["content"]) == {
        "verdict": "fail", "reason": PAIR["broken_reason"], "quote": PAIR["broken_quote"]
    }


def test_split_keeps_every_rule_in_both_parts():
    parts = split(make_rows(20) + make_rows(20, "real_blockers"))
    assert {name: len(part) for name, part in parts.items()} == {"train": 32, "val": 4, "test": 4}
    for part in parts.values():
        assert {row["rule_id"] for row in part} == {"concrete_tasks", "real_blockers"}


def test_prepare_writes_files_and_respects_rejected_pairs(tmp_path):
    rows = make_rows(10) + [{**make_rows(1)[0], "attempt": 99, "kept": False}]
    (tmp_path / "pairs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert prepare(tmp_path) == {"train": 16, "val": 2, "test": 2}
    pairs = [{e["report_id"].rsplit("-", 1)[0] for e in read_rows(tmp_path / f"{name}.jsonl")} for name in ("train", "val", "test")]
    assert sum(map(len, pairs)) == len(set.union(*pairs)) == 10  # no pair is in two files
    assert len(pd.read_csv(tmp_path / "review.csv")) == 5

    (tmp_path / "rejected.txt").write_text("concrete_tasks-1\nconcrete_tasks-2\n", encoding="utf-8")
    assert sum(prepare(tmp_path).values()) == 16


def test_pairs_for_an_older_question_do_not_count(tmp_path):
    path = tmp_path / "pairs.jsonl"
    old = [{**row, "question": "The old question?"} for row in make_rows(5)]
    path.write_text("".join(json.dumps(r) + "\n" for r in old), encoding="utf-8")
    assert sum(prepare(tmp_path).values()) == 0

    generate([RULE], 1, FakeGroq(), path)
    assert [row["attempt"] for row in read_rows(path)] == [1, 2, 3, 4, 5, 6]  # a new number, so an ID is never used twice
    assert sum(prepare(tmp_path).values()) == 2


def test_rows_with_unusual_line_separators_can_be_read(tmp_path):
    path = tmp_path / "pairs.jsonl"
    text = "a\u2028b\u2029c\u0085d"
    path.write_text(json.dumps({"good": text}, ensure_ascii=False) + "\n\n", encoding="utf-8")
    assert read_rows(path) == [{"good": text}]


def test_an_empty_answer_is_a_dropped_pair():
    class EmptyGroq(FakeGroq):
        def _create(self, **_):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])

    row = make_pair(RULE, 1, EmptyGroq())
    assert not row["kept"] and "JSON" in row["why"]


def test_only_models_that_think_first_have_no_answer_cap():
    assert token_cap(JUDGE) == {"max_completion_tokens": 300}
    assert token_cap(WRITER) == {}


def test_scores():
    results = pd.DataFrame(
        [
            ("a", "r1", "fail", "fail"),
            ("a", "r2", "fail", "unsure"),
            ("b", "r1", "pass", "fail"),
            ("b", "r2", "pass", "pass"),
        ],
        columns=["report_id", "rule_id", "label", "verdict"],
    ).assign(seconds=1.0)
    s = scores(results)
    assert s["rule breaks found"] == 0.5
    assert s["false alarms"] == 1 and s["false alarms per report"] == 0.5
    assert s["accuracy"] == 0.5 and s["unsure"] == 1


def test_run_stops_when_the_model_cannot_answer():
    example = {"report_id": "a", "rule_id": "r", "question": "q", "text": PAIR["good"], "label": "pass"}
    assert run([example], JUDGE, FakeGroq()).verdict.tolist() == ["pass"]
    with pytest.raises(SystemExit):
        run([example], JUDGE, FakeGroq(good="limit"))


def test_run_continues_after_a_stop(tmp_path):
    partial = tmp_path / "answers.jsonl"
    examples = [
        {"report_id": "a", "rule_id": "r", "question": "q", "text": PAIR["good"], "label": "pass"},
        {"report_id": "b", "rule_id": "r", "question": "q", "text": PAIR["broken"], "label": "fail"},
    ]
    with pytest.raises(SystemExit, match="1 answers are saved"):
        run(examples, JUDGE, FakeGroq(broken="limit"), partial)
    results = run(examples, JUDGE, client := FakeGroq(), partial)
    assert results.verdict.tolist() == ["pass", "fail"] and len(client.calls) == 1
    run(examples, "another model", client := FakeGroq(), partial)  # never reuses another model's answers
    assert len(client.calls) == 2


def test_run_uses_the_known_terms_as_the_app_does():
    class TermsGroq(FakeGroq):
        def _create(self, **_):
            content = json.dumps({"verdict": "fail", "reason": "It uses the abbreviation 'API' without explanation.", "quote": ""})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    example = {"report_id": "a", "rule_id": "terms_explained", "question": "q", "text": "x", "label": "pass"}
    assert run([example], JUDGE, TermsGroq()).verdict.tolist() == ["pass"]
    assert run([{**example, "rule_id": "concrete_tasks"}], JUDGE, TermsGroq()).verdict.tolist() == ["fail"]
