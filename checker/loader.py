import io
from pathlib import Path

SUPPORTED_EXTENSIONS = (".md", ".txt", ".pdf", ".docx")


def read_document(filename: str, data: bytes) -> str:
    """
    Turns an uploaded file into plain text.

    Args:
        filename: Original file name, used to pick the reader by extension
        data: Raw file bytes
    """
    ext = Path(filename).suffix.lower()
    if ext in (".md", ".txt"):
        return data.decode("utf-8-sig", errors="replace")
    if ext == ".pdf":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if ext == ".docx":
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(_docx_line(p) for p in document.paragraphs)
    raise ValueError(f"Unsupported file type '{ext}'. Use one of: {', '.join(SUPPORTED_EXTENSIONS)}")


def _docx_line(paragraph) -> str:
    # Keep Word headings as Markdown headings so section checks work the same for every format
    style = paragraph.style.name if paragraph.style is not None else ""
    if style.startswith("Heading"):
        level = style.split()[-1]
        hashes = "#" * int(level) if level.isdigit() else "#"
        return f"{hashes} {paragraph.text}"
    return paragraph.text
