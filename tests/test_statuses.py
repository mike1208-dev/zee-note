import pytest

from checker.statuses import by_number, check


@pytest.mark.parametrize(
    "notes, number, status, expected",
    [
        # the status next to the number
        ("pr 102 merged. reset form pr 101 still in review", "102", "Merged", "ok"),
        ("pr 102 merged. reset form pr 101 still in review", "101", "Merged", ""),
        ("backend PR 2115 merged, frontend PR 2116 in review", "2116", "In review", "ok"),
        ("backend PR 2115 merged, frontend PR 2116 in review", "2115", "In review", ""),
        ("merged PR 2918 for caching so reverted it with PR 2919, also merged", "2919", "Merged", "ok"),
        ("fixed issue-2010 issue-2011 in PR-2020 yesterday, merged", "2011", "Merged", "ok"),
        ("I've solved issue-1677 (PR-1679) and issue-1680 (PR-1682). Both PRs merged.", "1679", "Merged", "ok"),
        ("login redirect issue 210 pr 215 merged today working on logout", "215", "Merged", "ok"),
        # in the same sentence, after the number
        ("fixed it in PR 612, still waiting for review", "612", "In review", "ok"),
        ("PR-4019 review, not merged", "4019", "In review", "ok"),
        ("PR-4019 review, not merged", "4019", "Merged", ""),
        # whole words only
        ("fixed report preview, pr 34 merged", "34", "In review", ""),
        ("reviewed PR 520 and left 3 comments", "520", "In review", ""),
        ("deployment of PR 5 is planned", "5", "Done", ""),
        ("updated release notes in PR 5", "5", "Done", ""),
        # not yet
        ("PR 7 will be merged after the tests", "7", "Merged", ""),
        ("PR 7 is ready for review", "7", "In review", ""),
        ("PR 7 is almost done", "7", "Done", ""),
        # both finished and not finished
        ("PR 2618 merged, dropdown done\nwait correction PR 2618 is approved but not merged yet", "2618", "Merged", "conflict"),
        ("issue 2710 completed yesterday, PR 2718 merged\nissue 2710 still not fixed", "2710", "Done", "conflict"),
        # typos and Japanese
        ("notifcation badge issue-701 pr-709 mergd", "709", "Merged", "ok"),
        ("issue-1210、PR-1218はマージ済み。", "1218", "Merged", "ok"),
        ("PR-1218はまだマージされていない。", "1218", "Merged", ""),
        # several numbers
        ("PR 101 login in review, 102 merged", "101", "Merged", ""),
        ("PR 101 login in review, 102 merged", "102", "Merged", "ok"),
        ("PR 101, 102 and 103 merged", "101", "Merged", "ok"),
        ("PR 101, 102 and 103 merged", "103", "Merged", "ok"),
        ("PR 101 and 102 merged, PR 103 in review", "101", "Merged", "ok"),
        ("PR 101 and 102 merged, PR 103 in review", "103", "Merged", ""),
        ("PR 12 in review, 10 tests passed", "12", "In review", "ok"),
        # a later step isn't a contradiction
        ("issue 95 fix booking date, pr 102 merged but not deployed yet", "102", "Merged", "ok"),
        ("fixed the date, pr 102 merged, not verified yet", "102", "Merged", "ok"),
        ("pr 102 merged but not finished", "102", "Merged", "ok"),
        # about all tests, not about the PRs
        ("PR 101 login page fix\nAll unit tests passed", "101", "Done", ""),
        ("PR 101 login page fix\nall the tests passed", "101", "Done", ""),
        ("PR 101 login page fix\nall three are merged", "101", "Merged", "ok"),
        ("PR 101 menu, PR 102 cart\nboth of them in review", "102", "In review", "ok"),
        ("PR 101 login page completely broken", "101", "Done", ""),
        # nothing about it
        ("worked on pr 9", "9", "Merged", ""),
    ],
)
def test_statuses_of_numbers(notes, number, status, expected):
    assert check(status, [number], "", notes) == expected


@pytest.mark.parametrize(
    "notes, task, status, expected",
    [
        ("practiced the presentation, done\ntoday fix the menu", "Practiced the presentation", "Done", "ok"),
        ("wrote 6 tests. all passed", "Wrote 6 tests", "Done", "ok"),
        ("fixed the menu. wrote 6 tests. all passed. wrote docs", "Wrote docs", "Done", ""),  # not about every task
        ("wrote 6 tests all passed", "Wrote 6 tests", "Done", "ok"),
        ("wrote a checklist\ntoday document the deployment", "Wrote a checklist", "Done", ""),
        ("refactored the search. wrote tests\nboth in review", "Refactored the search", "In review", "ok"),
        ("cart page is not finished", "Cart page", "Done", ""),
        ("cart page is not finished", "Cart page", "In progress", "ok"),
        ("met Lina", "Something else", "Done", ""),
        ("", "Something", "Done", ""),
    ],
)
def test_statuses_of_tasks_without_numbers(notes, task, status, expected):
    assert check(status, [], task, notes) == expected


def test_numbers_without_a_status_are_known_too():
    assert by_number("issue 5 and pr 6").keys() == {"5", "6"} and not by_number("issue 5")["5"].said


def test_an_answer_at_the_end_gives_the_status():
    notes = "practiced the project presentation\ntoday: add validation\nPracticed the project presentation: In progress"
    assert check("In progress", [], "Practiced the project presentation", notes) == "ok"
