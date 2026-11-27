from checker.result import PASS, SKIP

AI_OFF = "AI checks are turned off."  # the message of run_checks

# The rules that look at the same thing as a question
SAME_POINT = {"status_or_result": "What is the status", "concrete_tasks": "What exactly", "terms_explained": "A reader who", "real_blockers": "Do you have any blockers"}


def points_to_check(questions: list[str], results, edited: bool) -> list[str]:
    """
    The questions and the failed rules, with each point only once.
    """
    points, skipped = list(questions), {}
    for result in results:
        same = [point for point in points if result.rule_id in SAME_POINT and point.startswith(SAME_POINT[result.rule_id])]
        if result.status == PASS and edited:  # the edits answered it
            points = [point for point in points if point not in same]
        elif result.status == SKIP and result.message != AI_OFF:
            skipped.setdefault(result.message, []).append(result.title)
        elif result.status != PASS and result.message != AI_OFF and not same:
            points.append(" ".join(f"{result.title}: {result.message} {result.where}".split()))
    # the same reason for several rules is one point
    return points + [f"{len(titles)} rule{'' if len(titles) == 1 else 's'} not checked. {reason}" for reason, titles in skipped.items()]


# The writer's questions that list what they ask about, so that each item can be answered on its own
ASKS = (
    "What is the title of:",
    "What exactly was done, or will be done?",
    "Your notes say both that this is finished and that it isn't. Which is right?",
    "What is the status (Done or In progress)?",
    "What is the status of the PR (for example Merged or In review)?",
    "Is this right? It isn't clearly in your notes:",
    "Is this a plan, or is it done already?",
    "Write this in English:",
    "This looks like older work, so it isn't in the report. Should it be?",
    "These plans are for later, so they aren't in the report. Should they be?",
    "These remarks were left out of the report:",
    "This part of your notes may be missing in the report:",
    "A reader who isn't technical may not know:",
)


def split_point(point: str) -> dict:
    """
    The question and the items it lists. A point that isn't one of these questions has no items.
    """
    for ask in ASKS:
        if point.startswith(ask + " "):
            joiner = ", " if ask.startswith("A reader") else "; "
            return {"ask": ask, "items": [item.strip() for item in point[len(ask) :].split(joiner) if item.strip()]}
    return {"ask": point, "items": []}
