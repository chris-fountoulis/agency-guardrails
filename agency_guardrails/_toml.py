"""TOML loading with an honest Python 3.9 story.

Python 3.11+ ships :mod:`tomllib`. On 3.9 and 3.10 we use ``tomli`` if it is
installed, otherwise the small parser below. The fallback covers the subset
a guardrails config needs: tables, arrays of tables, dotted and quoted keys,
basic and literal strings (with escapes), integers, floats, booleans, arrays
and inline tables. It rejects anything else with a clear error rather than
guessing. Dates and multi-line strings are not supported by the fallback.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

try:  # pragma: no cover - depends on interpreter
    import tomllib as _tomllib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on interpreter
    try:
        import tomli as _tomllib  # type: ignore[import-not-found,no-redef]
    except ImportError:
        _tomllib = None  # type: ignore[assignment]


class TOMLError(ValueError):
    pass


def loads(text: str) -> Dict[str, Any]:
    """Parse TOML text with the best parser available."""
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception as exc:  # normalise the error type
            raise TOMLError(str(exc)) from None
    return parse(text)


_BARE = re.compile(r"[A-Za-z0-9_-]+")
_NUMBER = re.compile(r"[+-]?(\d[\d_]*)(\.\d[\d_]*)?([eE][+-]?\d+)?")
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.line = 1

    # helpers -----------------------------------------------------------
    def error(self, msg: str) -> TOMLError:
        line = self.s.count("\n", 0, self.i) + 1
        return TOMLError("%s (line %d)" % (msg, line))

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def skip_ws(self, newlines: bool = False) -> None:
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t" or (newlines and c in "\r\n"):
                self.i += 1
            elif c == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            raise self.error("expected %r" % ch)
        self.i += 1

    def end_of_line(self) -> None:
        self.skip_ws()
        c = self.peek()
        if c == "":
            return
        if c == "\r":
            self.i += 1
            c = self.peek()
        if c != "\n":
            raise self.error("unexpected text after value")
        self.i += 1

    # keys --------------------------------------------------------------
    def key_part(self) -> str:
        c = self.peek()
        if c == '"':
            return self.basic_string()
        if c == "'":
            return self.literal_string()
        m = _BARE.match(self.s, self.i)
        if not m:
            raise self.error("invalid key")
        self.i = m.end()
        return m.group(0)

    def key(self) -> List[str]:
        parts = [self.key_part()]
        self.skip_ws()
        while self.peek() == ".":
            self.i += 1
            self.skip_ws()
            parts.append(self.key_part())
            self.skip_ws()
        return parts

    # values ------------------------------------------------------------
    def basic_string(self) -> str:
        if self.s.startswith('"""', self.i):
            raise self.error("multi-line strings are not supported by the fallback parser")
        self.expect('"')
        out = []
        while True:
            if self.i >= len(self.s):
                raise self.error("unterminated string")
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\n":
                raise self.error("newline in string")
            if c == "\\":
                nxt = self.s[self.i + 1 : self.i + 2]
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                    self.i += 2
                elif nxt in ("u", "U"):
                    width = 4 if nxt == "u" else 8
                    hexdigits = self.s[self.i + 2 : self.i + 2 + width]
                    if not re.fullmatch(r"[0-9A-Fa-f]{%d}" % width, hexdigits):
                        raise self.error("bad unicode escape")
                    out.append(chr(int(hexdigits, 16)))
                    self.i += 2 + width
                else:
                    raise self.error("bad escape \\%s" % nxt)
                continue
            out.append(c)
            self.i += 1

    def literal_string(self) -> str:
        if self.s.startswith("'''", self.i):
            raise self.error("multi-line strings are not supported by the fallback parser")
        self.expect("'")
        end = self.s.find("'", self.i)
        nl = self.s.find("\n", self.i)
        if end == -1 or (nl != -1 and nl < end):
            raise self.error("unterminated literal string")
        value = self.s[self.i : end]
        self.i = end + 1
        return value

    def value(self) -> Any:
        c = self.peek()
        if c == '"':
            return self.basic_string()
        if c == "'":
            return self.literal_string()
        if c == "[":
            return self.array()
        if c == "{":
            return self.inline_table()
        for word, val in (("true", True), ("false", False)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        m = _NUMBER.match(self.s, self.i)
        if m and m.group(0):
            self.i = m.end()
            text = m.group(0).replace("_", "")
            if m.group(2) or m.group(3):
                return float(text)
            return int(text)
        raise self.error("unsupported value")

    def array(self) -> List[Any]:
        self.expect("[")
        items: List[Any] = []
        while True:
            self.skip_ws(newlines=True)
            if self.peek() == "]":
                self.i += 1
                return items
            items.append(self.value())
            self.skip_ws(newlines=True)
            if self.peek() == ",":
                self.i += 1
                continue
            self.skip_ws(newlines=True)
            self.expect("]")
            return items

    def inline_table(self) -> Dict[str, Any]:
        self.expect("{")
        table: Dict[str, Any] = {}
        self.skip_ws()
        if self.peek() == "}":
            self.i += 1
            return table
        while True:
            self.skip_ws()
            parts = self.key()
            self.skip_ws()
            self.expect("=")
            self.skip_ws()
            _assign(table, parts, self.value(), self)
            self.skip_ws()
            if self.peek() == ",":
                self.i += 1
                continue
            self.expect("}")
            return table

    # document ----------------------------------------------------------
    def document(self) -> Dict[str, Any]:
        root: Dict[str, Any] = {}
        current = root
        defined = set()
        while True:
            self.skip_ws(newlines=True)
            if self.i >= len(self.s):
                return root
            if self.s.startswith("[[", self.i):
                self.i += 2
                self.skip_ws()
                parts = self.key()
                self.expect("]")
                self.expect("]")
                parent = _descend(root, parts[:-1], self)
                arr = parent.setdefault(parts[-1], [])
                if not isinstance(arr, list):
                    raise self.error("%s is not an array of tables" % ".".join(parts))
                current = {}
                arr.append(current)
                self.end_of_line()
            elif self.peek() == "[":
                self.i += 1
                self.skip_ws()
                parts = self.key()
                self.expect("]")
                name = tuple(parts)
                if name in defined:
                    raise self.error("table [%s] defined twice" % ".".join(parts))
                defined.add(name)
                current = _descend(root, parts, self)
                self.end_of_line()
            else:
                parts = self.key()
                self.skip_ws()
                self.expect("=")
                self.skip_ws()
                _assign(current, parts, self.value(), self)
                self.end_of_line()


def _descend(table: Dict[str, Any], parts: List[str], p: _Parser) -> Dict[str, Any]:
    for part in parts:
        nxt = table.setdefault(part, {})
        if isinstance(nxt, list):
            if not nxt or not isinstance(nxt[-1], dict):
                raise p.error("%s is not a table" % part)
            nxt = nxt[-1]
        if not isinstance(nxt, dict):
            raise p.error("%s is not a table" % part)
        table = nxt
    return table


def _assign(table: Dict[str, Any], parts: List[str], value: Any, p: _Parser) -> None:
    target = _descend(table, parts[:-1], p)
    if parts[-1] in target:
        raise p.error("duplicate key %s" % ".".join(parts))
    target[parts[-1]] = value


def parse(text: str) -> Dict[str, Any]:
    """Parse TOML with the built-in fallback parser (always available)."""
    return _Parser(text).document()


def backend() -> Tuple[str, bool]:
    """Return (name, is_fallback) for diagnostics."""
    if _tomllib is None:
        return ("agency_guardrails._toml", True)
    return (_tomllib.__name__, False)
