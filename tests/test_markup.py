import json
import re

from checker.markup import escape_markdown, to_html, to_slack


def test_lists_bold_emojis_and_links():
    html = to_html("""@Sam  
Hello

:date: **[Wednesday]**

- :dart: **Today** (7 hours)
  - issue-1 ― [FIX] Dates
    - [PR #2](https://x.test/pull/2) ― Merged
  - See https://x.test/a?b=1&c=2.

- Notes""")
    assert html == (
        "<p>@Sam<br>Hello</p><p>📅 <strong>[Wednesday]</strong></p>"
        "<ul><li>🎯 <strong>Today</strong> (7 hours)<ul><li>issue-1 ― [FIX] Dates<ul>"
        '<li><a href="https://x.test/pull/2" target="_blank" rel="noopener">PR #2</a> ― Merged</li></ul></li>'
        '<li>See <a href="https://x.test/a?b=1&amp;c=2" target="_blank" rel="noopener">https://x.test/a?b=1&amp;c=2</a>.</li></ul></li></ul>'
        "<ul><li>Notes</li></ul>"
    )


def test_slack_format():
    ops = json.loads(to_slack("""@Sam
Hello

- :dart: **Today** (7 hours).
  - [issue-1](https://x.test/issues/1) ― [FIX] Dates.
    - https://x.test/pull/2 ― Merged.

- Notes"""))["ops"]
    assert ops == [
        {"insert": "@Sam"}, {"insert": "\n"}, {"insert": "Hello"}, {"insert": "\n"}, {"insert": "\n"},
        {"insert": "🎯 "}, {"insert": "Today", "attributes": {"bold": True}}, {"insert": " (7 hours)."}, {"insert": "\n", "attributes": {"list": "bullet"}},
        {"insert": "issue-1", "attributes": {"link": "https://x.test/issues/1"}}, {"insert": " ― [FIX] Dates."},
        {"insert": "\n", "attributes": {"list": "bullet", "indent": 1}},
        {"insert": "https://x.test/pull/2", "attributes": {"link": "https://x.test/pull/2"}}, {"insert": " ― Merged."},
        {"insert": "\n", "attributes": {"list": "bullet", "indent": 2}},
        {"insert": "\n"}, {"insert": "Notes"}, {"insert": "\n", "attributes": {"list": "bullet"}},
    ]


def test_text_of_the_user_is_never_html():
    html = to_html('- <img src=x onerror=alert(1)>\n[x](javascript:alert(1)) [y](https://x.test/"onclick="a) **<b>**')
    assert re.findall(r"<(\w+)", html) == ["ul", "li", "p", "a", "strong"] and 'href="https://x.test/&quot;onclick=&quot;a"' in html


def test_other_characters_stay_as_they_are():
    text = "Cut __init__ to $5 and ~2 hours, a*b*c, 10:30:45 :unknown: #3"
    assert to_html(text) == f"<p>{text}</p>"


def test_uneven_lists_are_closed():
    for markdown in ("      - deep\n- flat\n  - in\ntext", "- a\n\n\n- b\n    - too deep", "", "\n", "-", "**", "****"):
        html = to_html(markdown)
        assert all(html.count(f"<{tag}>") == html.count(f"</{tag}>") for tag in ("ul", "li", "p", "strong"))


def test_escape_markdown():
    assert escape_markdown("**a** :red[b] $1$") == r"\*\*a\*\* \:red\[b\] \$1\$"
