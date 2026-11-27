"""
Checks that need understanding ("Is it clear?", "Does the summary match?"), answered by an LLM: through
Groq's cloud API (free tier, needs GROQ_API_KEY) or a small model inside the app (see local_model.py).
"""

import json
import os
import re
from functools import lru_cache

from checker import local_model
from checker.result import FAIL, PASS, SKIP, WARN, CheckResult

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
# Models offered in the app's dropdown (all tested on Groq). When Groq retires or adds models,
# override with GROQ_MODELS="model-a,model-b" in .env / Secrets instead of changing code.
MODELS = list(
    dict.fromkeys(
        [DEFAULT_MODEL]
        + [m.strip() for m in os.getenv("GROQ_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-20b,openai/gpt-oss-120b").split(",") if m.strip()]
    )
)
MAX_CHARS = 8000  # models lose track of very long input
MAX_ANSWER_TOKENS = 300  # without a cap, Groq reserves more than some models' limit per minute

# The document comes before the rule, so the local model reads it once and reuses it for the next rules.
# The local model is trained on this exact prompt: after a change, rebuild the dataset and train again.
PROMPT = """You are reviewing a team document against ONE rule.

Document:
\"\"\"
{text}
\"\"\"

Rule: {question}

Answer only with JSON in exactly this format:
{{"verdict": "pass" | "fail" | "unsure", "reason": "one short sentence", "quote": "the exact text that breaks the rule, or an empty string"}}"""

VERDICTS = {"pass": PASS, "fail": FAIL}
BROKEN_ANSWER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
QUOTED_TERM = re.compile(r"(?<!\w)['‘\"“]([^'’\"”]+)['’\"”](?!\w)")  # not the apostrophe in "doesn't"
# The other words an AI uses in its reason. Any word that isn't here, known or quoted may be an unknown term, so the fail stays
PLAIN_WORDS = set(
    """a abbreviation abbreviations acronym acronyms advanced an and any are as be but by clear common contains define defined definition
    description did do does doesn't doesnt don't explain explained explaining explains explanation for has have in include includes internal
    introduces is isn't it its lacks like lines mention mentions missing name named names new no not of on one or report report's several
    short software some such task tasks technical term terms that the their there these they this two unclear undefined unexplained unusual
    use used uses using was were which with without word words""".split()
)

# The words of a quoted task that can't be terms. A quote with any other unknown word keeps the fail
QUOTE_WORDS = PLAIN_WORDS | set(
    """add added after all asked at back before between by change changed changes check checked complete completed connect create created
    data day days done each file files finish finished first fix fixed from get got how improve improved into is it last list make made
    more move moved need needs next now old on only open opened out over part plan planned prepare prepared remove removed run send sent
    set share shared show start started still study studied through to today tomorrow two up update updated updates user users via wait
    waiting when while will work worked working write wrote yesterday""".split()
)


@lru_cache
def _known_terms(terms: tuple) -> tuple[frozenset[str], list[str]]:
    """
    The terms in lowercase, and the ones with more than one word (the longest first).
    """
    known = frozenset(str(term).lower() for term in terms)
    return known, sorted((term for term in known if " " in term), key=len, reverse=True)


def only_known_terms(known: list[str], reason: str, quote: str) -> bool:
    """
    Whether every term the AI complains about is a known one. If that isn't clear it's False, so the fail stays.
    """
    known, phrases = _known_terms(tuple(known))

    def is_known(text: str) -> bool:
        text = text.lower()
        if text in known or text.removesuffix("s") in known:
            return True
        parts = re.split(r"[\s/]+", text)
        return len(parts) > 1 and all(is_known(part) for part in parts if part)

    def words(text: str) -> list[str]:
        found = (word.strip(".,:;!?()[]*_`'\"‘’“”•◦▪-–—") for word in text.split())
        return [word for word in found if re.search(r"[^\W\d_]", word)]  # not "#42" or "60%"

    named = [term.strip(" .,:;*`") for term in QUOTED_TERM.findall(reason)]
    if not all(is_known(term) for term in named):
        return False
    rest = QUOTED_TERM.sub(" ", reason)
    for phrase in phrases:
        rest, count = re.subn(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", rest, flags=re.IGNORECASE)
        named += [phrase] * count
    for word in words(rest):
        if word.lower() in PLAIN_WORDS and not (word.isupper() and len(word) > 1):
            continue
        if not is_known(word):
            return False
        if word != word.lower():  # "API"; a lowercase word such as "page" may only be part of the sentence
            named.append(word)
    in_quote = words(quote)
    if not named:
        return bool(in_quote) and all(is_known(word) for word in in_quote)
    return all(is_known(word) or word.lower() in QUOTE_WORDS for word in in_quote)


def default_client(model: str = DEFAULT_MODEL):
    if model == local_model.MODEL_ID:
        return local_model.get_client()
    from groq import Groq

    # reads GROQ_API_KEY. A short wait and one retry, so a slow service doesn't hold a report for minutes
    return Groq(timeout=20, max_retries=1)


def error_text(error: Exception) -> str:
    """
    An error for the user. The answers of the service can have account details, so they're only printed to the log.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        return str(error)  # no API key, no connection, model file missing, ...
    print(f"AI service: {type(error).__name__}: {error}", flush=True)
    if status == 429 and "per day" in str(error):
        return "Today's free limit of this AI model is used up. Choose another model, or try later."
    if status == 429:
        return "The AI service's limit is reached. Wait a minute and try again, or choose another model."
    return f"The AI service didn't answer ({type(error).__name__}). Try again, or choose another model."


def token_cap(model: str, tokens: int = MAX_ANSWER_TOKENS) -> dict:
    """
    gpt-oss models think before they answer, which a small cap would cut off.
    """
    return {} if model.startswith("openai/gpt-oss") else {"max_completion_tokens": tokens}


def llm_check(text: str, rule: dict, model: str = DEFAULT_MODEL, client=None) -> CheckResult:
    """
    rule.question: the rule written as a yes/no question for the model.
    rule.known_terms: terms that are never a problem, so a fail that is only about them becomes a pass.
    """
    truncated = len(text) > MAX_CHARS
    # the document is in triple quotes, so triple quotes in it could end it early and add orders of their own
    unquoted = lambda value: str(value).replace('"""', "'''")  # noqa: E731
    prompt = PROMPT.format(question=unquoted(rule.get("question", rule.get("title", ""))), text=unquoted(text[:MAX_CHARS]))
    try:
        client = client or default_client(model)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
            **token_cap(model),
        )
        content = response.choices[0].message.content
    except Exception as e:  # no API key, rate limit, model retired, model file missing, ...
        return CheckResult.from_rule(rule, SKIP, message=f"AI check skipped: {error_text(e)}")

    try:
        # The local model may put a line break inside a quote. Other control characters mean a broken answer
        answer = None if BROKEN_ANSWER.search(content or "") else json.loads(content or "", strict=False)
    except json.JSONDecodeError:
        answer = None
    if not isinstance(answer, dict):
        return CheckResult.from_rule(rule, WARN, message="The AI gave an unreadable answer. Check this rule by hand.")

    status = VERDICTS.get(str(answer.get("verdict", "")).lower(), WARN)
    message = str(answer.get("reason") or "").strip()
    if status == FAIL and only_known_terms(rule.get("known_terms") or [], message, str(answer.get("quote") or "")):
        status, message = PASS, f"Only known terms were named. The AI said: {message}" if message else "Only known terms were named."
    if truncated:
        message += f" (Only the first {MAX_CHARS} characters were checked.)"
    quote = str(answer.get("quote") or "").strip()
    where = f'"{quote[:80]}"' if quote and status != PASS else ""
    return CheckResult.from_rule(rule, status, where=where, message=message)
