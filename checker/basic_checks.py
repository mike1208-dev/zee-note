"""
Checks done with plain Python: fast, free and always give the same answer.
Each check takes (text, rule) and returns a CheckResult. Register new ones in CHECKS.
"""

import re

from checker.result import FAIL, PASS, SKIP, WARN, CheckResult

# A pattern with a repeated group that repeats inside, such as (a+)+ or (\w+\s?)+, can take minutes on one line and
# freeze the whole app, so it's refused when saved and never run. A fixed count, as in (\.\d{1,3}){3}, is fine
NESTED = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)(?:[+*]|\{\d+,\d*\})")
LONGEST_PATTERN = 200


def risky_pattern(pattern: str) -> bool:
    return len(pattern) > LONGEST_PATTERN or bool(NESTED.search(pattern))

# (name, pattern, status). Known token formats are a FAIL; "password: ..." style lines are only a WARN
SECRET_PATTERNS = [
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), FAIL),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), FAIL),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), FAIL),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), FAIL),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), FAIL),
    ("Private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), FAIL),
    (
        "Password or key value",
        re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
        WARN,
    ),
]


# Slack shortcodes (:dart:, :+1:), keycaps and emoji characters, with their joiners and skin tones
EMOJI = (
    r"(?:(?<!\d):[a-z0-9+-][a-z0-9_+-]*:|[0-9#*]\uFE0F?\u20E3"
    r"|[\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF][\uFE0E\uFE0F\u200D\U0001F3FB-\U0001F3FF]*)"
)
BULLET = r"[-*+•◦▪][\uFE0E\uFE0F]?\s+"
NUMBER = r"\d+(?:[.,]\d+)?"
DURATION = rf"{NUMBER}\s*-?\s*(?:(?:hours?|hrs?|h)(?:\s*(?:and\s+)?\d+\s*(?:minutes?|mins?|m)?)?|minutes?|mins?)\b"
HOURS = (  # a duration with nothing but working time around it: "~2 hours", "2-3 hours planned"
    rf"(?:(?:time|est\.?|estimated?|took|spent|planned|total|about|around|approx\.?|approximately|~|≈)[:\s]*){{0,3}}"
    rf"(?:{NUMBER}\s*[-–~]\s*)?{DURATION}"
    r"(?:\s+(?:in total|total|spent|planned|worked|so far|left|remaining|each|today|yesterday)\b)?"
)
MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?)\.?"
)
DATE = (
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?"
    rf"|{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}(?:,?\s+\d{{4}})?"
    r"|(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?)\b"
)
BRACKETS = r"(?:\([^()]*\)|\[[^\[\]]*\])"
# What may follow a section name in a heading: brackets, hours or a date, then ": ..." or " - ...". The repeats
# are limited, or a long line of hours takes forever to match
HEADING_REST = (
    rf"(?:['’]s?)?(?P<suffix>(?:\s*[,–—-]?\s*(?:{BRACKETS}|(?<![a-z0-9]){HOURS}|(?<![a-z0-9]){DATE})){{0,4}})"
    r"\s*(?P<tail>:.*|\s-+\s.*|[–—].*)?"
)
# Sections that end the ones with hours
SECTION_END = ["Blockers", "Notes", "Issues", "Problems", "Risks", "Questions", "Tomorrow", "Next steps", "Next week", "Overall progress"]



def _normalize_heading(line: str) -> str:
    # "## 1. Done:", "**Done**", "Done:" -> "done"; Slack: "• :dart: *Today (7 hours)*" -> "today (7 hours)"
    original = line.strip().lower()
    line = re.sub(rf"^{BULLET}(?=[*_ ]*{EMOJI})", "", line.strip())  # a bullet is only a heading if an emoji follows
    line = re.sub(EMOJI, " ", line).strip()
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"^\d+[.)]\s*", "", line)
    line = re.sub(r"[*`]|(?<!\w)_|_(?!\w)", "", line).strip().rstrip(":. ")
    return re.sub(r"\s+", " ", line).lower() or original


def _heading_matches(line: str, names: list[str]):
    """
    Yields a match for each way the line is a heading with one of the names.
    """
    heading = _normalize_heading(line)
    for name in names:
        name = re.escape(_normalize_heading(name))
        if not name:
            continue
        if match := re.fullmatch(name + HEADING_REST, heading):
            yield match
        for part in heading.split("/") if "/" in heading else []:  # "Blockers / Notes" counts as both
            match = re.fullmatch(name + HEADING_REST, part.strip())
            if match and not match["tail"]:
                yield match


def _is_heading(line: str, names: list[str]) -> bool:
    return any(_heading_matches(line, names))


def _has_hours(line: str) -> bool:
    """
    In a line a duration only counts as working time as an item in brackets or backticks, or after a dash at the end,
    so that "cut the build time from 2 hours to 5 minutes" and "(30 min timeout)" don't.
    """
    for content in re.findall(r"[(\[`]([^()\[\]`]*)[)\]`]", line):
        items = re.split(r"[,;/|+·]|\s[-–—]\s|\band\b", content)
        if any(re.fullmatch(HOURS, item.strip(" ."), re.IGNORECASE) for item in items):
            return True
    return bool(re.search(rf"(?<!\d)[-–—:]\s*{HOURS}\s*{BRACKETS}?[*_.\s]*$", line, re.IGNORECASE))


def _heading_has_hours(line: str, names: list[str]) -> bool:
    if _has_hours(_normalize_heading(line)):
        return True
    for match in _heading_matches(line, names):
        if re.search(DURATION, re.sub(BRACKETS, "", match["suffix"])):
            return True
        if re.match(rf"[:\s–—-]*{HOURS}\s*(?:$|[,;.:+=–—-])", match["tail"] or ""):
            return True
    return False


def _names(section: str | list[str]) -> list[str]:
    return [section] if isinstance(section, str) else section


def _content_lines(text: str):
    """
    Yields (line_number, line), skipping code blocks and tables so they don't count as prose.
    """
    in_code = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or line.strip().startswith("|"):
            continue
        yield number, line


def required_sections(text: str, rule: dict) -> CheckResult:
    """
    rule.sections: list of section names. An item can also be a list of accepted alternatives,
    e.g. ["Blockers", "Issues"].
    """
    lines = text.splitlines()
    missing = []
    for section in rule.get("sections", []):
        names = _names(section)
        if not any(_is_heading(line, names) for line in lines):
            missing.append(" / ".join(names))
    if missing:
        return CheckResult.from_rule(rule, FAIL, message=f"Missing section(s): {', '.join(missing)}. Add a heading for each.")
    return CheckResult.from_rule(rule, PASS)


def no_secrets(text: str, rule: dict) -> CheckResult:
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern, status in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append((number, name, status))
                break
    if not hits:
        return CheckResult.from_rule(rule, PASS)
    # The secret itself is never repeated in the report
    status = FAIL if any(status == FAIL for _, _, status in hits) else WARN
    where = ", ".join(f"line {number}" for number, _, _ in hits[:5])
    kinds = sorted({name for _, name, _ in hits})
    return CheckResult.from_rule(rule, status, where=where, message=f"Looks like: {', '.join(kinds)}. Remove it before sharing.")


def word_count(text: str, rule: dict) -> CheckResult:
    """
    rule.min / rule.max: allowed number of words (both optional).
    """
    words = len(text.split())
    minimum, maximum = rule.get("min"), rule.get("max")
    if minimum is not None and words < minimum:
        return CheckResult.from_rule(rule, FAIL, message=f"{words} words; at least {minimum} expected. Add more detail.")
    if maximum is not None and words > maximum:
        return CheckResult.from_rule(rule, FAIL, message=f"{words} words; at most {maximum} allowed. Shorten it.")
    return CheckResult.from_rule(rule, PASS, message=f"{words} words")


def long_sentences(text: str, rule: dict) -> CheckResult:
    """
    rule.max_words: longest allowed sentence (default 35). Long sentences are a WARN, not a FAIL.
    """
    limit = rule.get("max_words", 35)
    long_ones = []
    for number, line in _content_lines(text):
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if len(sentence.split()) > limit:
                long_ones.append(number)
    if not long_ones:
        return CheckResult.from_rule(rule, PASS)
    where = ", ".join(f"line {n}" for n in sorted(set(long_ones))[:5])
    return CheckResult.from_rule(
        rule, WARN, where=where, message=f"{len(long_ones)} sentence(s) longer than {limit} words. Split them."
    )


def forbidden_phrases(text: str, rule: dict) -> CheckResult:
    """
    rule.phrases: words that must not appear (case-insensitive), e.g. TODO, TBD.
    """
    phrases = rule.get("phrases", [])
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        for phrase in phrases:
            if re.search(rf"(?i)\b{re.escape(phrase)}\b", line):
                hits.append((number, phrase))
    if not hits:
        return CheckResult.from_rule(rule, PASS)
    where = ", ".join(f"line {number}" for number, _ in hits[:5])
    found = sorted({phrase for _, phrase in hits})
    return CheckResult.from_rule(rule, FAIL, where=where, message=f"Found: {', '.join(found)}. Replace with real content.")


def must_contain(text: str, rule: dict) -> CheckResult:
    """
    rule.phrases: text that must appear (case-insensitive), e.g. a ticket link or a sign-off.
    """
    lowered = text.lower()
    missing = [phrase for phrase in rule.get("phrases", []) if phrase.lower() not in lowered]
    if missing:
        return CheckResult.from_rule(rule, FAIL, message=f"Missing: {', '.join(missing)}. Add it.")
    return CheckResult.from_rule(rule, PASS)


def pattern(text: str, rule: dict) -> CheckResult:
    """
    rule.pattern: a regular expression, e.g. [A-Z]+-\\d+ for ticket numbers like ABC-123.
    rule.must: "match" (default, it must appear somewhere) or "not_match" (it must not appear).
    rule.label: what the pattern means, used in the message.
    """
    if risky_pattern(rule.get("pattern", "")):
        return CheckResult.from_rule(rule, SKIP, message="This pattern could take too long to check. Ask a manager to simplify it.")
    regex = re.compile(rule.get("pattern", ""), re.MULTILINE)
    label = rule.get("label") or f"text matching {rule.get('pattern')}"
    if rule.get("must", "match") == "not_match":
        lines = [number for number, line in enumerate(text.splitlines(), start=1) if regex.search(line)]
        if lines:
            where = ", ".join(f"line {n}" for n in lines[:5])
            return CheckResult.from_rule(rule, FAIL, where=where, message=f"Found {label}. Remove it.")
        return CheckResult.from_rule(rule, PASS)
    if regex.search(text):
        return CheckResult.from_rule(rule, PASS)
    return CheckResult.from_rule(rule, FAIL, message=f"No {label} found. Add one.")


def mention_at_top(text: str, rule: dict) -> CheckResult:
    """
    rule.lines: how many lines count as the top (default 3, empty lines are ignored).
    """
    lines = [line for line in text.splitlines() if line.strip()][: rule.get("lines", 3)]
    # "@Dan" or Slack's "<@U0123|Dan>", but not an email address
    if any(re.search(r"(?<![\w.+-])@\w", line) for line in lines):
        return CheckResult.from_rule(rule, PASS)
    return CheckResult.from_rule(rule, FAIL, message="No reviewer is tagged at the top. Add one, e.g. @Name.")


def _section_lines(text: str, sections: list[list[str]], ends: list[str]):
    """
    Yields (section index, whether it's the heading, line) for the lines in the sections. The headings in ends close a section.
    """
    current, level = None, 0
    for line in text.splitlines():
        marks = re.match(r"\s*(#*)", line)[1]
        heading = next((i for i, names in enumerate(sections) if _is_heading(line, names)), None)
        if heading is not None:
            current, level = heading, len(marks)
        elif _is_heading(line, ends) or 0 < len(marks) <= level:  # "## Ideas" ends "## Today", "### Ideas" doesn't
            current = None
        if current is not None:
            yield current, heading is not None, line


def working_hours(text: str, rule: dict) -> CheckResult:
    """
    rule.sections: sections that must give hours, same shape as in required_sections. The hours can be in
    the heading ("Today (7 hours)") or on a task ("Write tests (2 hours)").
    """
    sections = [_names(section) for section in rule.get("sections", [])]
    found = set()
    for current, is_heading, line in _section_lines(text, sections, SECTION_END):
        if _heading_has_hours(line, sections[current]) if is_heading else _has_hours(line):
            found.add(current)
    missing = [" / ".join(names) for i, names in enumerate(sections) if i not in found]
    if missing:
        return CheckResult.from_rule(
            rule, FAIL, message=f"No hours for: {', '.join(missing)}. Add them, e.g. {sections[-1][0]} (7 hours)."
        )
    return CheckResult.from_rule(rule, PASS)


CHECKS = {
    "required_sections": required_sections,
    "no_secrets": no_secrets,
    "word_count": word_count,
    "long_sentences": long_sentences,
    "forbidden_phrases": forbidden_phrases,
    "must_contain": must_contain,
    "pattern": pattern,
    "mention_at_top": mention_at_top,
    "working_hours": working_hours,
}
