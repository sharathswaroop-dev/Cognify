"""Read an uploaded document into text and cut it into pieces a memory can hold.

Supported: .txt .md .csv .json .log and .pdf (text PDFs; a scanned PDF has no text to read and is refused with a clear message)."""
from __future__ import annotations

import io
import re

MAX_BYTES = 2_000_000
MAX_CHUNKS = 60
TEXT = (".txt", ".md", ".markdown", ".csv", ".json", ".log")


class DocError(ValueError):
    pass


def extract(name: str, data: bytes) -> str:
    n = name.lower()
    if len(data) > MAX_BYTES:
        raise DocError(f"That file is larger than {MAX_BYTES // 1_000_000} MB. Split it or share the key pages.")
    if n.endswith(TEXT):
        return data.decode("utf-8", errors="replace")
    if n.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        except Exception as exc:
            raise DocError("That PDF could not be read.") from exc
        if len(text.strip()) < 30:
            raise DocError("That PDF has no readable text (it may be a scan). Paste the text into the chat instead.")
        return text
    raise DocError("I can read .txt, .md, .csv, .json, .log and text PDFs. For other files, paste the text into the chat.")


def chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Paragraph-aware pieces of about `size` characters with a little overlap; at most MAX_CHUNKS."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    if not text:
        raise DocError("That file is empty.")
    paras, out, cur = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()], [], ""
    for p in paras:
        while len(p) > size:                      # a very long paragraph is cut at a sentence end where possible
            cut = max(p.rfind(". ", 0, size), p.rfind("\n", 0, size), size // 2)
            piece, p = p[:cut + 1].strip(), p[cut + 1:].strip()
            if cur:
                out.append(cur)
                cur = ""
            out.append(piece)
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            cur = cur[-overlap:] + "\n\n" + p if overlap and len(cur) > overlap else p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        out.append(cur)
    if len(out) > MAX_CHUNKS:
        raise DocError(f"That document is about {len(out)} sections; the limit is {MAX_CHUNKS}. Share the most useful part.")
    return out
