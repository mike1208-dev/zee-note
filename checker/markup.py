"""
Turns the report's Markdown into HTML, for the preview, and into Slack's format, for pasting. Only the Markdown that the report
uses is known (lists, bold, links and emoji codes), so other characters of the notes stay as they are.
"""

import json
import re
from html import escape

EMOJI = {"date": "📅", "white_check_mark": "✅", "dart": "🎯", "construction": "🚧", "memo": "📝"}
LINK = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s()]+)\)|(https?://[^\s<>()\"]*[^\s<>()\".,;:!?])")


def escape_markdown(text: str) -> str:
    """
    For text of the user in Streamlit's own Markdown.
    """
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>$:])", r"\\\1", text)


def _emoji(text: str) -> str:
    return re.sub(r":(\w+):", lambda match: EMOJI.get(match[1], match[0]), text)


def _parts(text: str):
    """
    Yields (text, bold, link) for each part of a line.
    """
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):  # every second part is bold
        position = 0
        for match in LINK.finditer(part):
            yield _emoji(part[position : match.start()]), bool(i % 2), ""
            yield match[1] or match[3], bool(i % 2), match[2] or match[3]
            position = match.end()
        yield _emoji(part[position:]), bool(i % 2), ""


def _inline(line: str) -> str:
    html = ""
    for text, bold, link in _parts(line):
        text = escape(text)
        if link:
            text = f'<a href="{escape(link)}" target="_blank" rel="noopener">{text}</a>'
        html += f"<strong>{text}</strong>" if bold and text else text
    return html


def _lines(markdown: str):
    """
    Yields (text, level) for each line. The level is 0 for a line that isn't a list item.
    """
    level = 0
    for line in markdown.splitlines():
        item = re.match(r"( *)[-*] (.*)", line)
        level = min(len(item[1]) // 2 + 1, level + 1) if item else 0
        yield (item[2] if item else line).rstrip(), level


def to_html(markdown: str) -> str:
    html, depth, in_text = "", 0, False
    for line, level in _lines(markdown):
        # a line that isn't an item ends the list, and an item one level up ends the items inside it
        is_text = not level and bool(line)
        html += "</p>" if in_text and not is_text else ""
        html += "</li></ul>" * max(depth - level, 0)
        if level:
            html += ("<ul>" if level > depth else "</li>") + f"<li>{_inline(line)}"
        elif is_text:
            html += ("<br>" if in_text else "<p>") + _inline(line)
        depth, in_text = level, is_text
    return html + ("</p>" if in_text else "") + "</li></ul>" * depth


def to_slack(markdown: str) -> str:
    """
    The format of Slack's own message box (a Quill Delta). From HTML, Slack doesn't keep a link whose text is its address.
    """
    ops = []
    for line, level in _lines(markdown):
        for text, bold, link in _parts(line):
            attributes = {**({"bold": True} if bold else {}), **({"link": link} if link else {})}
            if text:
                ops.append({"insert": text, **({"attributes": attributes} if attributes else {})})
        indent = {"indent": level - 1} if level > 1 else {}
        ops.append({"insert": "\n", **({"attributes": {"list": "bullet", **indent}} if level else {})})
    return json.dumps({"ops": ops}, ensure_ascii=False)
