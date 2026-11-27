import pandas as pd

from checker import basic_checks, llm_checks, local_model
from checker.result import ICONS, PASS, SKIP, CheckResult
from checker.styles import Style


def run_checks(
    text: str,
    style: Style,
    use_llm: bool = True,
    model: str = llm_checks.DEFAULT_MODEL,
    client=None,
) -> list[CheckResult]:
    """
    Runs every rule of the style on the text, in the order they appear in the YAML file.
    """
    results = []
    secret_found = any(rule.get("check") == "no_secrets" for rule in style.rules) and basic_checks.no_secrets(text, {}).status != PASS
    limit_hit = ""  # once the AI service says its limit is reached, the other AI rules don't ask it again
    for rule in style.rules:
        check = rule.get("check")
        if check == "llm":
            if use_llm and limit_hit:
                results.append(CheckResult.from_rule(rule, SKIP, message=limit_hit))
            elif use_llm and secret_found and model != local_model.MODEL_ID:
                message = "Not sent to the AI service, because the text may contain a secret. Remove it and check again."
                results.append(CheckResult.from_rule(rule, SKIP, message=message))
            elif use_llm:
                results.append(llm_checks.llm_check(text, rule, model=model, client=client))
                if results[-1].status == SKIP and "limit" in results[-1].message:
                    limit_hit = results[-1].message
            else:
                results.append(CheckResult.from_rule(rule, SKIP, message="AI checks are turned off."))
        elif check in basic_checks.CHECKS:
            try:
                results.append(basic_checks.CHECKS[check](text, rule))
            except Exception as e:  # a badly edited rule must not break the whole report
                results.append(CheckResult.from_rule(rule, SKIP, message=f"This rule has an error: {e}"))
        else:
            results.append(CheckResult.from_rule(rule, SKIP, message=f"Unknown check type '{check}' in the rules file."))
    return results


def count(results: list[CheckResult], status: str) -> int:
    return sum(r.status == status for r in results)


def summary(results: list[CheckResult]) -> str:
    skipped = count(results, SKIP)
    text = f"{count(results, PASS)} / {len(results) - skipped} rules passed"
    return text + (f" ({skipped} skipped)" if skipped else "")


def to_dataframe(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Result": ICONS[r.status], "Rule": r.title, "Where": r.where, "Why / suggested fix": r.message}
            for r in results
        ]
    )
