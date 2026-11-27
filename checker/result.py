from dataclasses import dataclass

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"  # a possible problem a person should look at
SKIP = "SKIP"  # the check could not run (AI turned off, no API key, unknown check type)

ICONS = {PASS: "✅", FAIL: "❌", WARN: "⚠️", SKIP: "⏭️"}


@dataclass
class CheckResult:
    rule_id: str
    title: str
    status: str
    where: str = ""
    message: str = ""

    @classmethod
    def from_rule(cls, rule: dict, status: str, where: str = "", message: str = "") -> "CheckResult":
        rule_id = rule.get("id", rule.get("check", "unknown"))
        return cls(rule_id=rule_id, title=rule.get("title") or rule_id, status=status, where=where, message=message)
