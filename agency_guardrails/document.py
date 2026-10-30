"""Parse a file into a :class:`Document` that rules can read.

Every document keeps the raw text plus a *prose view* (``doc.text``) of the
same length: markup, code, URLs and front-matter keys are blanked out with
spaces, and HTML entities are decoded in place (padded with spaces). Because
offsets line up with the raw file, any regex match on the prose view maps
back to an exact line and column in the original.
"""

from __future__ import annotations

import bisect
import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KIND_BY_EXT = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdx": "markdown",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
}

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dl", "dt",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody",
    "td", "tfoot", "th", "thead", "tr", "ul", "title", "body", "head", "html",
}

_TAG = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)\b[^>]*>", re.S)
_RAW_BLOCK = re.compile(r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DECL = re.compile(r"<![^>]*>|<\?[^>]*\?>", re.S)
_ENTITY = re.compile(r"&(#\d{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_URL = re.compile(r"\b(?:https?|ftp)://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+")
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
_WORD = re.compile(r"[^\W_]+(?:['\N{RIGHT SINGLE QUOTATION MARK}-][^\W_]+)*", re.U)


def kind_for(path: str) -> str:
    return KIND_BY_EXT.get(Path(path).suffix.lower(), "other")


def blank(s: str) -> str:
    """Replace every character except newlines with a space."""
    return re.sub(r"[^\n]", " ", s)


def words(text: str) -> List[str]:
    return _WORD.findall(text)


def normalize(text: str) -> str:
    """Lowercase, unify dashes and whitespace: for keyword and question matching."""
    text = html.unescape(text).lower()
    text = re.sub(r"[\N{HYPHEN}-\N{HORIZONTAL BAR}-]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.U)
    return re.sub(r"\s+", " ", text).strip()


def _sub_same_length(pattern: re.Pattern, text: str, repl) -> str:
    def _r(m: re.Match) -> str:
        out = repl(m)
        if len(out) != len(m.group(0)):  # pragma: no cover - defensive
            raise AssertionError("replacement must keep length")
        return out

    return pattern.sub(_r, text)


def _decode_entities(text: str) -> str:
    def repl(m: re.Match) -> str:
        decoded = html.unescape(m.group(0))
        if decoded == m.group(0) or len(decoded) != 1:
            return m.group(0)
        if decoded == "\xa0":
            decoded = " "
        return decoded + " " * (len(m.group(0)) - 1)

    return _sub_same_length(_ENTITY, text, repl)


def mask_markup(text: str) -> str:
    """Blank out HTML markup and decode entities, keeping offsets stable."""
    text = _sub_same_length(_RAW_BLOCK, text, lambda m: blank(m.group(0)))
    text = _sub_same_length(_COMMENT, text, lambda m: blank(m.group(0)))
    text = _sub_same_length(_DECL, text, lambda m: blank(m.group(0)))

    def tag(m: re.Match) -> str:
        s = blank(m.group(0))
        if m.group(1).lower() in BLOCK_TAGS and len(s) >= 2:
            return "\n\n" + s[2:]
        return s

    text = _sub_same_length(_TAG, text, tag)
    return _decode_entities(text)


def mask_urls(text: str) -> str:
    return _sub_same_length(_URL, text, lambda m: blank(m.group(0)))


@dataclass
class Heading:
    level: int
    text: str
    offset: int


@dataclass
class Block:
    text: str
    offset: int


@dataclass
class Element:
    tag: str
    attrs: Dict[str, Optional[str]]
    offset: int
    text: str = ""


@dataclass
class JsonLd:
    offset: int
    raw: str
    data: Any = None
    error: str = ""

    def items(self) -> List[Dict[str, Any]]:
        """Flatten top-level objects, lists and @graph into a list of nodes."""
        out: List[Dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for n in node:
                    walk(n)
            elif isinstance(node, dict):
                out.append(node)
                if "@graph" in node:
                    walk(node["@graph"])

        walk(self.data)
        return out


class _StructureParser(HTMLParser):
    """Collect headings, paragraphs, images, links, meta and JSON-LD with offsets."""

    CAPTURE = {"title", "h1", "h2", "h3", "h4", "h5", "h6", "p", "a", "summary", "dt", "script"}

    def __init__(self, line_starts: List[int], structure: bool = True):
        super().__init__(convert_charrefs=True)
        self.line_starts = line_starts
        self.structure = structure
        self.open: List[List[Any]] = []  # [tag, offset, attrs, parts]
        self.quotes_open: List[Tuple[str, int]] = []
        self.title: Optional[str] = None
        self.meta: Dict[str, str] = {}
        self.headings: List[Heading] = []
        self.paragraphs: List[Block] = []
        self.images: List[Element] = []
        self.links: List[Element] = []
        self.questions: List[Block] = []
        self.jsonld: List[JsonLd] = []
        self.quote_spans: List[Tuple[int, int]] = []

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def _close(self, tag: str) -> None:
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                item = self.open.pop(i)
                self._finish(item)
                return

    def handle_starttag(self, tag: str, attrs_list: List[Tuple[str, Optional[str]]]) -> None:
        attrs = {k.lower(): v for k, v in attrs_list}
        off = self._offset()
        if tag == "img":
            self.images.append(Element(tag, attrs, off))
            return
        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name and attrs.get("content") is not None:
                self.meta.setdefault(name, attrs.get("content") or "")
            return
        if tag in ("blockquote", "q"):
            self.quotes_open.append((tag, off))
        if tag in BLOCK_TAGS and tag not in ("a", "br", "hr"):
            self._close("p")
        if tag == "script":
            if (attrs.get("type") or "").lower() != "application/ld+json":
                return
        if tag in self.CAPTURE:
            self.open.append([tag, off, attrs, []])

    def handle_startendtag(self, tag: str, attrs_list: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag in self.CAPTURE and tag not in ("img", "meta"):
            self._close(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("blockquote", "q"):
            for i in range(len(self.quotes_open) - 1, -1, -1):
                if self.quotes_open[i][0] == tag:
                    _, start = self.quotes_open.pop(i)
                    self.quote_spans.append((start, self._offset()))
                    break
        if tag in self.CAPTURE:
            self._close(tag)

    def handle_data(self, data: str) -> None:
        for item in self.open:
            item[3].append(data)

    def _finish(self, item: List[Any]) -> None:
        tag, off, attrs, parts = item
        raw = "".join(parts)
        text = re.sub(r"\s+", " ", raw).strip()
        if tag == "script":
            node = JsonLd(off, raw)
            try:
                node.data = json.loads(raw)
            except ValueError as exc:
                node.error = str(exc)
            self.jsonld.append(node)
        elif tag == "a":
            self.links.append(Element(tag, attrs, off, text))
        elif not self.structure:
            return
        elif tag == "title":
            if self.title is None:
                self.title = text
        elif tag[0] == "h" and tag[1:].isdigit():
            self.headings.append(Heading(int(tag[1:]), text, off))
        elif tag == "p":
            if text:
                self.paragraphs.append(Block(text, off))
        elif tag in ("summary", "dt"):
            if text:
                self.questions.append(Block(text, off))

    def close(self) -> None:
        super().close()
        while self.open:
            self._finish(self.open.pop())


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s")
_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
_MD_LINK_TARGET = re.compile(r"\]\(\s*[^)\n]*\)")
_MD_REF = re.compile(r"^ {0,3}\[[^\]]+\]:\s+\S+.*$", re.M)
_INLINE_CODE = re.compile(r"(`+)[^`\n]+?\1")
_FRONT_VISIBLE = {"title", "description", "meta_description", "summary", "excerpt", "subtitle"}


def md_inline_text(s: str) -> str:
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[*_`~]", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


class Document:
    """A parsed file. Construct with :meth:`from_path` or directly from text."""

    def __init__(self, path: str, raw: str, kind: Optional[str] = None):
        self.path = path
        self.raw = raw
        self.kind = kind or kind_for(path)
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", raw)]
        self.text = raw
        self.front_matter: Dict[str, str] = {}
        self.title: Optional[str] = None
        self.title_offset = 0
        self.meta_description: Optional[str] = None
        self.meta_offset = 0
        self.focus_keyword: Optional[str] = None
        self.headings: List[Heading] = []
        self.paragraphs: List[Block] = []
        self.questions: List[Block] = []
        self.images: List[Element] = []
        self.links: List[Element] = []
        self.jsonld: List[JsonLd] = []
        self.quote_spans: List[Tuple[int, int]] = []
        if self.kind == "html":
            self._parse_html()
        elif self.kind == "markdown":
            self._parse_markdown()
        if self.kind in ("html", "markdown", "text"):
            self.quote_spans.extend(self._inline_quotes())
            self.quote_spans.sort()
        self._blocks = [m.start() for m in _BLANK_LINE.finditer(self.text)]

    @classmethod
    def from_path(cls, path: str, display: Optional[str] = None) -> "Document":
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        return cls(display or path, raw)

    # positions -----------------------------------------------------------
    def position(self, offset: int) -> Tuple[int, int]:
        """1-based (line, column) for a character offset."""
        offset = max(0, min(offset, len(self.raw)))
        idx = bisect.bisect_right(self.line_starts, offset) - 1
        return idx + 1, offset - self.line_starts[idx] + 1

    def line(self, number: int) -> str:
        start = self.line_starts[number - 1]
        end = self.line_starts[number] - 1 if number < len(self.line_starts) else len(self.raw)
        return self.raw[start:end]

    def in_quote(self, offset: int) -> bool:
        return any(a <= offset < b for a, b in self.quote_spans)

    def passage(self, offset: int, window: int = 240) -> Tuple[int, int]:
        """Bounds of the paragraph around ``offset`` in the prose view, capped at ``window``."""
        i = bisect.bisect_right(self._blocks, offset)
        start = self._blocks[i - 1] if i > 0 else 0
        end = self._blocks[i] if i < len(self._blocks) else len(self.text)
        return max(start, offset - window), min(end, offset + window)

    @property
    def first_paragraph(self) -> Optional[Block]:
        return self.paragraphs[0] if self.paragraphs else None

    @property
    def h1(self) -> Optional[Heading]:
        for h in self.headings:
            if h.level == 1:
                return h
        return None

    # parsing ---------------------------------------------------------------
    def _parse_html(self) -> None:
        self.text = mask_urls(mask_markup(self.raw))
        p = _StructureParser(self.line_starts)
        p.feed(self.raw)
        p.close()
        self.title = p.title
        m = re.search(r"<title\b", self.raw, re.I)
        self.title_offset = m.start() if m else 0
        self.meta_description = p.meta.get("description") or p.meta.get("og:description")
        m = re.search(r"<meta\b[^>]*\bname=[\"']?description", self.raw, re.I)
        self.meta_offset = m.start() if m else 0
        self.focus_keyword = (
            p.meta.get("focus-keyword") or p.meta.get("focus_keyword") or p.meta.get("guardrails:focus-keyword")
        )
        self.headings = p.headings
        self.paragraphs = p.paragraphs
        self.questions = p.questions
        self.images = p.images
        self.links = p.links
        self.jsonld = p.jsonld
        self.quote_spans = p.quote_spans

    def _parse_markdown(self) -> None:
        raw = self.raw
        chars = list(raw)

        def blank_range(a: int, b: int) -> None:
            for k in range(a, b):
                if chars[k] != "\n":
                    chars[k] = " "

        body_start = 0
        fm = re.match(r"---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(?:\r?\n|$)", raw, re.S)
        if fm:
            body_start = fm.end()
            blank_range(0, fm.end())
            pos = fm.start(1) if fm.group(1) else fm.end()
            for line in (fm.group(1) or "").splitlines(True):
                km = re.match(r"([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
                if km:
                    key = km.group(1).lower()
                    value = km.group(2)
                    vstart = pos + km.start(2)
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                        vstart += 1
                    self.front_matter[key] = value
                    if key in _FRONT_VISIBLE:
                        for k, ch in enumerate(value):
                            chars[vstart + k] = ch
                        if key == "title":
                            self.title_offset = pos
                        else:
                            self.meta_offset = pos
                pos += len(line)

        # fenced code blocks
        in_fence = None
        offset = 0
        lines = raw.splitlines(True)
        line_offsets = []
        for line in lines:
            line_offsets.append(offset)
            if offset >= body_start:
                fm_ = _FENCE.match(line)
                if in_fence is not None:
                    blank_range(offset, offset + len(line))
                    if fm_ and fm_.group(1)[0] == in_fence[0] and len(fm_.group(1)) >= len(in_fence):
                        in_fence = None
                elif fm_:
                    in_fence = fm_.group(1)
                    blank_range(offset, offset + len(line))
            offset += len(line)

        code_masked = "".join(chars)
        code_masked = _sub_same_length(_INLINE_CODE, code_masked, lambda m: blank(m.group(0)))

        # raw HTML inside markdown: images, links, JSON-LD and quotes
        p = _StructureParser(self.line_starts, structure=False)
        p.feed(code_masked)
        p.close()
        self.images = list(p.images)
        self.links = list(p.links)
        self.jsonld = list(p.jsonld)
        self.quote_spans = list(p.quote_spans)
        for m in _MD_IMAGE.finditer(code_masked):
            self.images.append(Element("img", {"alt": m.group(1), "src": m.group(2), "_md": "1"}, m.start()))

        text = _sub_same_length(_MD_LINK_TARGET, code_masked, lambda m: "]" + blank(m.group(0)[1:]))
        text = _sub_same_length(_MD_REF, text, lambda m: blank(m.group(0)))
        text = mask_urls(mask_markup(text))
        self.text = text

        # headings and paragraphs from the code-masked source
        para: List[Tuple[int, str]] = []

        def flush() -> None:
            if para:
                joined = md_inline_text(" ".join(t for _, t in para))
                if joined:
                    self.paragraphs.append(Block(joined, para[0][0]))
                para.clear()

        masked_lines = code_masked.splitlines(True)
        for idx, line in enumerate(masked_lines):
            off = line_offsets[idx]
            stripped = line.strip()
            if off < body_start or not stripped:
                flush()
                continue
            hm = _ATX.match(line.rstrip("\r\n"))
            if hm:
                flush()
                self.headings.append(Heading(len(hm.group(1)), md_inline_text(hm.group(2)), off))
                continue
            if (
                stripped.startswith((">", "|", "<", "![", "[!"))
                or _LIST.match(line)
                or _HR.match(line)
                or _MD_REF.match(line)
            ):
                flush()
                if stripped.startswith(">"):
                    self.quote_spans.append((off, off + len(line)))
                continue
            if re.match(r"^\*\*[^*]+\?\*\*\s*$", stripped):
                flush()
                self.questions.append(Block(md_inline_text(stripped), off))
                continue
            para.append((off + len(line) - len(line.lstrip()), stripped))
        flush()

        fmk = self.front_matter
        self.title = fmk.get("title") or (self.h1.text if self.h1 else None)
        if not fmk.get("title") and self.h1:
            self.title_offset = self.h1.offset
        self.meta_description = fmk.get("description") or fmk.get("meta_description")
        self.focus_keyword = (
            fmk.get("focus_keyword") or fmk.get("focus_keyphrase") or fmk.get("focus-keyword") or fmk.get("keyword")
        )

    def _inline_quotes(self) -> List[Tuple[int, int]]:
        spans = []
        for m in re.finditer(r"\N{LEFT DOUBLE QUOTATION MARK}[^\N{RIGHT DOUBLE QUOTATION MARK}]{1,1200}\N{RIGHT DOUBLE QUOTATION MARK}|\"[^\"\n]{1,400}\"", self.text):
            spans.append((m.start(), m.end()))
        return spans
