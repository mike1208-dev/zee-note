from checker.basic_checks import forbidden_phrases, long_sentences, no_secrets, required_sections, word_count
from checker.result import FAIL, PASS, WARN

SECTIONS_RULE = {"id": "has_sections", "sections": [["Done", "Completed"], "Next", "Blockers"]}


def test_required_sections_accepts_headings_bold_and_colons():
    text = "## 1. Completed\n- fixed login\n**Next**\n- tests\nBlockers: none"
    assert required_sections(text, SECTIONS_RULE).status == PASS


def test_required_sections_reports_missing():
    result = required_sections("# Done\n- fixed login", SECTIONS_RULE)
    assert result.status == FAIL
    assert "Next" in result.message and "Blockers" in result.message
    assert "Done" not in result.message


def test_required_sections_does_not_match_inside_sentences():
    result = required_sections("I am done with next week's blockers.", SECTIONS_RULE)
    assert result.status == FAIL


def test_no_secrets_flags_token_without_repeating_it():
    token = "ghp_" + "a" * 36
    result = no_secrets(f"Intro\nuse {token} to log in", {"id": "no_secrets"})
    assert result.status == FAIL
    assert result.where == "line 2"
    assert token not in result.message


def test_no_secrets_password_line_is_only_a_warning():
    assert no_secrets("password: hunter22", {"id": "no_secrets"}).status == WARN


def test_no_secrets_clean_text_passes():
    assert no_secrets("The API key is stored in the team vault.", {"id": "no_secrets"}).status == PASS


def test_word_count_limits():
    rule = {"id": "length", "min": 3, "max": 5}
    assert word_count("one two", rule).status == FAIL
    assert word_count("one two three four", rule).status == PASS
    assert word_count("one two three four five six", rule).status == FAIL


def test_long_sentences_warns_and_ignores_code_blocks():
    long_line = " ".join(["word"] * 40)
    rule = {"id": "short", "max_words": 35}
    assert long_sentences(f"Short one.\n{long_line}.", rule).status == WARN
    assert long_sentences(f"Short one.\n```\n{long_line}\n```", rule).status == PASS


def test_forbidden_phrases_matches_whole_words_only():
    rule = {"id": "no_placeholders", "phrases": ["TODO", "TBD"]}
    result = forbidden_phrases("Deadline: tbd\nTODOS are fine as a word", rule)
    assert result.status == FAIL
    assert result.where == "line 1"
    assert forbidden_phrases("All done.", rule).status == PASS
