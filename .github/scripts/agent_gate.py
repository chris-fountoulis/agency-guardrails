#!/usr/bin/env python3
"""Leak gate for agent branches. Runs in public CI before an agent branch is merged.

Scans only what the branch adds on top of the base: added lines, commit messages and commit
authors. Fails closed: a missing hash key, an unreadable diff or any hit stops the merge.

Checks:
- em and en dashes
- secret shaped strings, IP addresses, local home paths
- email addresses outside an allowlist
- commit authors other than the maintainer's noreply address
- names and internal terms that must never be published. These are stored only as keyed
  hashes in .github/leak-hashes.txt, so this public file does not reveal them. The key is
  the LEAK_HMAC_KEY repository secret.

Usage: agent_gate.py BASE_REF [--no-hash]
"""
import hashlib, hmac, os, re, subprocess, sys, unicodedata

AUTHOR = "31489251+chris-fountoulis@users.noreply.github.com"
MAX_ADDED = 1500           # added lines outside data/ per branch
PATTERNS = [
    ("dash", re.compile("[\u2013\u2014]")),
    ("secret", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{30,}"
                          r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[bpa]-[0-9A-Za-z-]{10,}"
                          r"|AIza[0-9A-Za-z_-]{35}")),
    ("ip", re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")),
    ("path", re.compile(r"/Users/[a-z]|/home/[a-z]+/Desktop")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@(?!(?:growthofinfluence\.com|users\.noreply\.github\.com"
                         r"|anthropic\.com|github\.com|example\.(?:com|org|net)|acme-agency\.(?:com|test)"
                         r")\b)[A-Za-z0-9.-]+\.[a-z]{2,}")),
    ("greek", re.compile("[Ͱ-Ͽἀ-῿]{3,}")),
]


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, errors="replace")
    if r.returncode:
        sys.exit(f"gate: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def ngrams(line):
    toks = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", line).lower())
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            yield " ".join(toks[i:i + n])


def main(argv):
    if not argv:
        sys.exit(__doc__)
    base, use_hash = argv[0], "--no-hash" not in argv
    key = os.environ.get("LEAK_HMAC_KEY", "").encode()
    hashes = set()
    if use_hash:
        if not key:
            sys.exit("gate: LEAK_HMAC_KEY is not set, failing closed")
        with open(".github/leak-hashes.txt", encoding="utf-8") as f:
            hashes = {h.strip() for h in f if h.strip() and not h.startswith("#")}
    hits = []

    def scan(where, text):
        for name, rx in PATTERNS:
            if rx.search(text):
                hits.append(f"{where}: {name}")
        if use_hash:
            for g in ngrams(text):
                if hmac.new(key, g.encode(), hashlib.sha256).hexdigest()[:24] in hashes:
                    hits.append(f"{where}: private term")
                    break

    for line in git("log", "--format=%H %ae", f"{base}..HEAD").splitlines():
        sha, email = line.split(" ", 1)
        if email != AUTHOR:
            hits.append(f"commit {sha[:8]}: author {email} is not the maintainer noreply address")
        scan(f"commit {sha[:8]} message", git("log", "-1", "--format=%B", sha))

    added, path, lineno = 0, None, 0
    for line in git("diff", "-U0", "--no-color", f"{base}...HEAD").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            if not path.startswith("data/"):
                added += 1
            if not re.search(r"\.(png|jpe?g|gif|ico|woff2?|ttf|pdf)$", path):
                scan(f"{path}:{lineno}", line[1:])
            lineno += 1
    if added > MAX_ADDED:
        hits.append(f"branch adds {added} lines outside data/, limit is {MAX_ADDED}")

    for h in dict.fromkeys(hits):
        print(h)
    print(f"gate: {len(set(hits))} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
