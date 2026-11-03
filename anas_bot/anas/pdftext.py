"""Estrazione del testo dai PDF delle ordinanze (pypdf, puro Python)."""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)


def pdf_to_text(data: bytes) -> str:
    """Testo di tutte le pagine. Stringa vuota se il PDF è una scansione o è rotto."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        log.warning("PDF non leggibile: %s", exc)
        return ""
    return "\n".join(pages)
