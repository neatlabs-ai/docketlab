# Copyright 2026 Security 360, LLC DBA NEATLABS(TM)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Attachment text extraction.

This is where naive pipelines lose the comments that matter. Trade associations,
law firms, and agencies' own advocacy offices file PDFs; the inline comment box
usually just says "See attached." A tool that reads only `attributes.comment`
silently drops the entire substantive tail and then reports that the docket was
mostly form letters.
"""
from __future__ import annotations

import html
import re
import unicodedata

import requests

from . import config

try:
    import pymupdf  # PyMuPDF
except ImportError:  # pragma: no cover
    pymupdf = None


_TAG = re.compile(r"<[^>]{1,400}>")
_SCRIPTY = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def normalize(text: str) -> str:
    """Canonical form used for hashing, similarity, and word counts.

    regulations.gov returns comment bodies as HTML, not plain text — `<br/>`
    between every paragraph and entity-encoded quotes throughout. Left in, that
    markup inflates token counts, pollutes shingles so near-duplicate detection
    sees structure instead of content, and drags embeddings toward whichever
    comments happen to share formatting.
    """
    if not text:
        return ""
    t = _SCRIPTY.sub(" ", text)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>", "\n\n", t, flags=re.I)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\u00ad", "")                      # soft hyphens
    t = re.sub(r"[\u2018\u2019]", "'", t)
    t = re.sub(r"[\u201c\u201d]", '"', t)
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _pdf_text(data: bytes) -> str:
    if pymupdf is None:
        return ""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    parts = []
    for i, page in enumerate(doc):
        if i >= 1200:
            parts.append("[TRUNCATED-AT-1200-PAGES]")
            break
        parts.append(page.get_text("text"))
    doc.close()
    text = "\n".join(parts).strip()
    # A scanned PDF yields almost nothing. Flag it rather than pretending.
    if len(text) < 40:
        return "[SCANNED-NO-TEXT-LAYER]"
    return text


def _docx_text(data: bytes) -> str:
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except Exception:
        return ""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        runs = [t.text or "" for t in p.iter(f"{ns}t")]
        if runs:
            paras.append("".join(runs))
    return "\n".join(paras)


MAX_ATTACHMENT_BYTES = 60 * 1024 * 1024  # a comment attachment, not a data set


def _fetch(url: str) -> bytes | None:
    """Stream with a hard ceiling. One oversized file should not stall a pull."""
    try:
        with requests.get(url, timeout=90, stream=True) as r:
            r.raise_for_status()
            declared = r.headers.get("Content-Length")
            if declared and int(declared) > MAX_ATTACHMENT_BYTES:
                return None
            buf = bytearray()
            for chunk in r.iter_content(262144):
                buf.extend(chunk)
                if len(buf) > MAX_ATTACHMENT_BYTES:
                    return None
            return bytes(buf)
    except Exception:
        return None


def harvest_attachments(comment_id: str, payload: dict) -> tuple[str, int]:
    """Download every attachment on a comment and return (text, file_count)."""
    included = payload.get("included") or []
    chunks, count = [], 0
    outdir = config.FILES / comment_id
    for item in included:
        if item.get("type") != "attachments":
            continue
        for fmt in item.get("attributes", {}).get("fileFormats") or []:
            url = fmt.get("fileUrl")
            if not url:
                continue
            ext = (fmt.get("format") or url.rsplit(".", 1)[-1] or "").lower()
            count += 1
            outdir.mkdir(parents=True, exist_ok=True)
            local = outdir / url.rsplit("/", 1)[-1]
            if local.exists():
                data = local.read_bytes()
            else:
                data = _fetch(url)
                if data is None:
                    chunks.append("[ATTACHMENT-UNREACHABLE-OR-OVERSIZED]")
                    continue
                local.write_bytes(data)
            if ext == "pdf":
                chunks.append(_pdf_text(data))
            elif ext in ("docx", "doc"):
                chunks.append(_docx_text(data))
            elif ext in ("txt", "htm", "html"):
                chunks.append(data.decode("utf-8", errors="replace"))
            else:
                chunks.append(f"[UNPARSED-FORMAT {ext}]")
    return normalize("\n\n".join(c for c in chunks if c)), count
