import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


@dataclass
class Style:
    """
    One document style (daily report, issue/PR, work plan, ...) and its rules.
    """

    id: str
    name: str
    rules: list[dict]
    description: str = ""
    detect: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "detect": self.detect,
            "rules": self.rules,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Style":
        detect, rules = data.get("detect") or [], data.get("rules") or []
        if isinstance(detect, str):
            detect = detect.split(",")
        return cls(
            id=data["id"],
            name=str(data.get("name") or data["id"]),
            description=str(data.get("description") or ""),
            detect=[str(word).strip() for word in detect],
            rules=[rule for rule in rules if isinstance(rule, dict)],
        )


def slugify(text: str) -> str:
    # "Meeting notes!" -> "meeting_notes"
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50]


def load_styles(rules_dir: Path = RULES_DIR) -> dict[str, Style]:
    """
    Loads every rules/*.yaml file. Adding a new style = adding a new file.
    """
    styles = {}
    for path in sorted(Path(rules_dir).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        styles[path.stem] = Style.from_dict({**data, "id": path.stem})
    return styles
