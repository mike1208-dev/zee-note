"""
Finds the statuses that plain notes give to PRs, issues and tasks. It only says whether a status of the AI is supported;
it never chooses one itself.
"""

import re
from dataclasses import dataclass, field
from difflib import get_close_matches

WORDS = {
    "Merged": r"\bmerged\b|マージ(?:済|した|しました|完了|されました)",
    "In review": r"\b(?:waiting for|awaiting|under|pending) (?:\w+ )?review\b|\breview\b|レビュー(?:中|待ち)",
    "In progress": r"\bin progress\b|\bwip\b|\bongoing\b|\bworking on\b|\binvestigating\b|\bunfinished\b|\bstarted\b|\bstill (?:on|doing|open)\b|\bci is running\b"
    r"|\bnot (?:finished|done|complete)\b|\bnot merged\b|進行中|対応中|作業中",
    "Draft": r"\bdraft\b|ドラフト",
    "Closed": r"\bclosed\b|クローズ",
    "Open": r"\b(?:re)?open(?:ed)?\b",
    "Done": r"\b(?:done|finished|completed?|fixed|deployed|shipped|released|passed|pass|solved|resolved|verified)\b|\bit work(?:s|ed)\b|\bworks (?:now|well|fine)\b|\blooks? (?:ok|good)\b"
    r"|✅|完了|修正した|修正しました|対応済|問題なし",
}
PR_STATUSES = {"Merged", "In review", "Draft", "Closed", "Open"}
FINISHED = {"Merged", "Done"}
NOT = r"\b(?:not|never|no|cannot|without)\b|n['’]t\b|\b(?:isnt|wasnt|havent|hasnt|didnt)\b"
NOT_YET = r"\b(?:will|would|gonna|going to|to be|after|until|once|when|if|ask(?:ing)? for|ready for|almost|nearly|half|only|should|want to|need(?:s)? to)\b"
# A later step that isn't done yet, such as "merged but not deployed", doesn't say that the work isn't finished
LATER_STEPS = {"deployed", "shipped", "released", "passed", "pass", "verified"}
PREFIX = r"(?:\b(?P<pr>prs?|pull requests?|mrs?)|\b(?P<issue>issues?|tickets?)|/(?P<link>pull|issues)/|#)"
NUMBER = re.compile(rf"{PREFIX}[\s-]*#?\s*(?P<number>\d+)", re.IGNORECASE)
# "PR 101, 102 and 103", and "PR 101 in review, 102 merged". Not "12 tests", hours, dates or parts of a longer number
NOT_COUNTED = r"(?![\d.:/%]*\d|\s*(?:%|h\b|hrs?\b|hours?\b|min|days?\b|weeks?\b|times\b|of\b|tests?\b|comments?\b|files?\b|cases?\b|bugs?\b|users?\b|prs?\b|issues?\b|tasks?\b))"
NEXT_IN_LIST = re.compile(rf"\s*(?:,|、|/|&|\band\b|\bor\b|と)\s*#?(\d+)\b{NOT_COUNTED}", re.IGNORECASE)
NEXT_IN_SENTENCE = re.compile(rf"(?:,|、|\band\b|\bbut\b)\s*#?(\d{{2,}})\b{NOT_COUNTED}", re.IGNORECASE)
# A number without "issue" or "PR" at the start of a line or sentence: "1680 chore - ...", "95: ...", "1680 new form"
BARE = re.compile(
    r"(?im)(?:^|(?<=[.!?;]\s))\W*(?P<number>\d+)(?:\W{1,3}(?:feat|fix|chore|bug|test|refactor|docs)\b|\s*[:–-]\s+(?=[a-z])|(?<=\d{3})\s+(?=[a-z]))(?!hours?\b)"
)
TYPOS = ("merged", "review", "finished", "completed")
NOT_TYPOS = {"merge", "merges", "emerged", "reviewed", "preview", "finish", "complete", "unfinished", "competed"}


@dataclass
class Evidence:
    said: set[str] = field(default_factory=set)
    denied: set[str] = field(default_factory=set)

    def add(self, other: "Evidence"):
        self.said |= other.said
        self.denied |= other.denied


@dataclass
class Mention:
    position: int
    end: int
    number: str
    kind: str  # "pr", "issue", or "" when the notes don't say it


def mentions(text: str) -> list[Mention]:
    """
    The PR and issue numbers of the text, not its other numbers.
    """
    found = []
    for match in NUMBER.finditer(text):
        kind = "pr" if match["pr"] or (match["link"] or "").lower() == "pull" else "issue" if match["issue"] or match["link"] else ""
        found.append(Mention(match.start(), match.end(), match["number"], kind))
        while after := NEXT_IN_LIST.match(text, found[-1].end):
            found.append(Mention(after.start(1), after.end(1), after[1], kind))
    for sentence in re.finditer(r"[^\n;。]+", text):
        inside = [item for item in found if sentence.start() <= item.position < sentence.end()]
        for match in NEXT_IN_SENTENCE.finditer(text, sentence.start(), sentence.end()):
            before = [item for item in inside if item.end <= match.start()]
            if before and len(before[-1].number) == len(match[1]) and not any(item.position <= match.start(1) < item.end for item in found):
                found.append(Mention(match.start(1), match.end(1), match[1], before[-1].kind))
                inside.append(found[-1])
    for match in BARE.finditer(text):
        if not any(item.position <= match.start("number") < item.end for item in found):
            found.append(Mention(match.start("number"), match.end("number"), match["number"], ""))
    return sorted(found, key=lambda item: item.position)


def sentences(notes: str) -> list[str]:
    return [part for part in re.split(r"[\n;。]|(?<=[.!?])\s+", notes) if part.strip()]


def _fix_typos(text: str) -> str:
    def fix(match):
        word = match[0].lower()
        if word in NOT_TYPOS or re.search(r"(?:ly|ers?|ion|ing|s)$", word):
            return match[0]
        close = get_close_matches(word, TYPOS, n=1, cutoff=0.83)
        return close[0] if close else match[0]

    return re.sub(r"\b[A-Za-z]{5,10}\b", fix, text)


def _find(text: str) -> list[tuple[int, str, bool]]:
    """
    (position, status, whether it's denied) of each status in the text. "will be merged" is neither said nor denied.
    """
    found = []
    for status, pattern in WORDS.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            before = " ".join(text[: match.start()].split()[-3:])
            if re.search(NOT, before, re.IGNORECASE):
                if match[0].lower() not in LATER_STEPS:
                    found.append((match.start(), status, True))
            elif not re.search(NOT_YET, before, re.IGNORECASE):
                found.append((match.start(), status, False))
        if status == "Merged" and re.search(r"マージ(?:されて|して)い?(?:ない|ません)", text):
            found.append((0, status, True))
    return found


def _evidence(found) -> Evidence:
    return Evidence({status for _, status, denied in found if not denied}, {status for _, status, denied in found if denied})


def by_number(notes: str) -> dict[str, Evidence]:
    """
    The statuses the notes give to each PR or issue number.
    """
    result: dict[str, Evidence] = {}
    for sentence in sentences(_fix_typos(notes)):
        all_mentions, active = mentions(sentence), []
        start, waiting = 0, []
        for clause in re.split(r"(,|、|\bbut\b|\s/\s)", sentence):
            numbers = [item for item in all_mentions if start <= item.position < start + len(clause)]
            found = _find(clause)
            for item in numbers:
                result.setdefault(item.number, Evidence())
            if numbers and not found and not re.search(r"[^\W\d_]", re.sub(PREFIX, "", clause, flags=re.IGNORECASE)):
                waiting += [item.number for item in numbers]  # "PR 101, 102 merged"
            elif numbers:
                groups: list[list[Mention]] = []
                for item in numbers:  # "PR 101 and 102" is one group
                    if groups and re.fullmatch(rf"(?i)\s*(?:and|&|or)?\s*(?:{PREFIX}[\s-]*#?)?", sentence[groups[-1][-1].end : item.position]) and item.kind == groups[-1][-1].kind:
                        groups[-1].append(item)
                    else:
                        groups.append([item])
                for position, status, denied in found:  # a status belongs to the numbers before it, or to the first ones after it
                    before = [group for group in groups if group[0].position - start < position]
                    for number in [item.number for item in (before[-1] if before else groups[0])] + (waiting if not before or before[-1] is groups[0] else []):
                        result[number].add(_evidence([(position, status, denied)]))
                active = [item.number for item in numbers] + waiting
                waiting = []
            elif active or waiting:
                for number in active or waiting:
                    result[number].add(_evidence(found))
            start += len(clause)
        if not all_mentions:
            for number in result:
                result[number].said |= _of_all(sentence)
    return result


FOR_ALL = re.compile(
    r"(?i)\W*(?:and |so |yes )?(?:both|all(?: of them)?(?: (?:two|three|four|five|\d+))?|everything)\s+(?:of (?:them|these)\s+)?"
    r"(?:the\s+)?(?:(?:prs?|pull requests?|issues?|tickets?|tasks?|changes)\s+)?(?:(?:are|were|is|was|got|have|been|has|now|already|in|under)\s+)*"
)


def _of_all(sentence: str) -> set[str]:
    """
    The statuses of a sentence such as "both merged". "All unit tests passed" isn't about the PRs.
    """
    match = FOR_ALL.match(sentence)
    if not match:
        return set()
    found = [item for item in _find(sentence) if item[0] == match.end()]
    return {status for _, status, denied in found if not denied and not re.match(r"(?i)pass", sentence[match.end() :])}


def words(text: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{4,}", re.sub(r"https?://\S+", " ", text.lower())))


def same_words(text: str, other: str) -> set[str]:
    """
    The words of the text that are in the other one too. "fixing" and "fixed" are the same, and so is a word with a typo.
    """
    others = words(other)
    starts = {word[:4] for word in others}
    return {word for word in words(text) if word[:4] in starts or get_close_matches(word, others, n=1, cutoff=0.8)}


def _of_task(task: str, notes: str) -> Evidence:
    """
    The statuses in the sentence that is most like the task, or in a short one after it.
    """
    parts = sentences(_fix_typos(notes))
    if not parts:
        return Evidence()
    scores = [len(same_words(task, part)) for part in parts]
    best = len(scores) - 1 - scores[::-1].index(max(scores))  # of two as alike, the later one: an answer or a correction
    if not scores[best]:
        return Evidence()
    text = parts[best]
    after = parts[best + 1] if best + 1 < len(parts) else ""
    if after and len(after.split()) <= 5 and not mentions(after) and not re.match(r"\W*(?:today|tomorrow|next|plan|no block|block)", after, re.IGNORECASE):
        text += ", " + after
    evidence = _evidence(_find(text))
    for part in parts[best + 1 :]:
        evidence.said |= _of_all(part)
    return evidence


def check(status: str, numbers: list[str], task: str, notes: str, known: dict[str, Evidence] | None = None) -> str:
    """
    "ok" if the notes support the status, "conflict" if they say that the work is finished and that it isn't, or "".
    """
    known = by_number(notes) if known is None else known
    given = Evidence()
    for number in numbers:
        given.add(known.get(number, Evidence()))
    if given.said & given.denied & FINISHED and not given.said & (PR_STATUSES - {"Merged"}):
        return "conflict"
    if status in given.denied:
        return ""
    if status in given.said:
        return "ok"
    if given.said & PR_STATUSES:  # the notes give another one
        return ""
    of_task = _of_task(task, notes)
    return "ok" if status in of_task.said and status not in of_task.denied else ""
