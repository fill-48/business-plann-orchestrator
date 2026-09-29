#!/usr/bin/env python3
"""T-PUBLICATION-BOUNDARY — the repository contains only publishable material.

Scans every file that belongs to the repository (tracked and untracked,
non-ignored files in a Git work tree; every non-cache file otherwise) for:

1. paths that must never be published (engineering archives, generated
   reports, real projects);
2. engineering-process residue (review/authorization vocabulary, internal
   milestone and decision identifiers, references to unpublished documents);
3. secrets (private keys, cloud and VCS tokens, credentials in URLs);
4. local environment details (absolute user paths, temporary directories);
5. e-mail addresses;
6. the .gitignore entries that keep user data and generated files out.

Names of real people and organisations cannot be listed here without
publishing them: they are covered by the maintainers' release checklist.

Synthetic secrets used by the validator tests are built by string
concatenation, so they never appear literally in the sources.
"""
import argparse
import re
from pathlib import Path

import smoke_support as s

FORBIDDEN_PATHS = (
    r"^docs/reviews/", r"^docs/superpowers/", r"^docs/HANDOFF\.md$",
    r"^docs/ISSUES\.md$", r"^docs/RELEASE_", r"^docs/STAGE\d", r"^tests/reports/",
    r"^tests/manifest/", r"^projects/", r"^business-plan-logic\.md$",
    r"^AGENT_ARCHITECTURE\.md$", r"(^|/)__pycache__/", r"\.pyc$",
    r"(^|/)\.working/", r"(^|/)shared/\.tx/", r"\.bak-", r"(^|/)\.env$",
)

GOVERNANCE = (
    # "red-team reviewer" / "grant-readiness-reviewer" are product roles of
    # the architecture specification, not engineering reviewers.
    ("role", r"Product Owner|\bPO\b|(?<!red-team[- ])(?<!readiness-)"
             r"[Rr]eviewer\b|\bCodex\b|\bderoga\b|\bwaiver\b"),
    ("process", r"\bdisposition\b|\bamendment\b|\bruling\b|\bre-?check\b|"
                r"planning package|evidence package|\bmandato\b"),
    ("wave", r"\b[Ww]ave ?\d|\bW\d-|-W\d\b|-W\d-|\bW\dR\d"),
    ("milestone", r"\bS1[0-3][-_]M\d|\bM\d[ab]\b"),
    ("decision-id", r"\bDEC-(?:W\d|S1\d|M\d)[-\w]*|\bDELTA-W|\bIR-S1\d|\bAP-S1\d|"
                    r"\bOBS-S1\d|\bST-W\d|\bOMIT-W|\bAC-W\d|\bTD-W\d|\bAMB-W|"
                    r"\bNS-W\d|\bOB-W\d|\bRUL-W|\bF-FINAL|\bR2-M-"),
    ("document", r"docs/reviews|RELEASE_0\.|STAGE1\d_\w+\.md|"
                 r"STAGE1\d_(?:WAVE|FINANCIAL|DOCUMENT|PRODUCT)|business-plan-logic|"
                 r"AGENT_ARCHITECTURE|HANDOFF\.md|test_manifest_0_|"
                 r"release-0\.\d-required|tests/lib\b"),
    ("release-phase", r"\b[Rr]elease 0\.\d\b|\bslice 0\.\d"),
    ("vcs", r"\b(?:candidat[oa]|review|commit|HEAD) [0-9a-f]{7,40}\b"),
)

#: Functional identifiers kept on purpose (changing them would alter a
#: published contract). Each entry: (path regex, token regex, reason).
ALLOWED = (
    (r"schemas/financial-plan\.schema\.json$", r"DEC-S10-23",
     "schema const of financial_plan...decision_ref (contract)"),
    (r"output/build_canonical_output\.py$", r"DEC-S10-23",
     "value emitted for the schema const above"),
    (r"tests/integration/.*\.py$", r"DEC-S10-23",
     "assertion on the schema const above"),
)

SECRETS = (
    ("private key", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    ("aws key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github token", r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    ("slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("api key", r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}|\bAIza[0-9A-Za-z_-]{35}"),
    ("url credential", r"[a-z][a-z0-9+.-]*://[^/\s:@\"']+:[^@\s\"']+@[^\s\"']+"),
    ("assignment", r"(?i)\b(?:password|passwd|secret|api_key|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
)

LOCAL = (
    ("user path", r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z]|/Users/[a-z][a-z0-9_-]+/|"
                  r"/home/(?!runner\b)[a-z][a-z0-9_-]+/"),
    ("temp dir", r"[\\/]AppData[\\/]Local[\\/]Temp[\\/]|/private/var/folders/|"
                 r"/tmp/tmp[a-z0-9_]{6,}"),
)

EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
EMAIL_ALLOWED = r"@(?:example\.(?:com|org|net)|users\.noreply\.github\.com)$|^noreply@"

GITIGNORE_REQUIRED = ("__pycache__/", "*.py[cod]", "**/.working/",
                      "**/shared/.tx/", "tests/reports/", "*.bak-*",
                      "/projects/", ".env")


def allowed(rel, token):
    return any(re.search(p, rel) and re.fullmatch(t, token)
               for p, t, _ in ALLOWED)


def scan(root, failures):
    files = s.repo_files(root)
    s.check(len(files) > 100, f"suspiciously few files: {len(files)}", failures)
    this = Path(__file__).resolve()
    for path in files:
        rel = path.relative_to(root).as_posix()
        for pattern in FORBIDDEN_PATHS:
            if re.search(pattern, rel):
                failures.append(f"forbidden path: {rel}")
        if path.resolve() == this:
            continue  # the patterns themselves live here
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"non-text file in the repository: {rel}")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            where = f"{rel}:{number}"
            for label, pattern in GOVERNANCE:
                for match in re.finditer(pattern, line):
                    if not allowed(rel, match.group(0)):
                        failures.append(f"{where}: engineering residue "
                                        f"[{label}] {match.group(0)!r}")
            for label, pattern in SECRETS + LOCAL:
                match = re.search(pattern, line)
                if match:
                    failures.append(f"{where}: {label}: {match.group(0)[:40]!r}")
            for match in re.finditer(EMAIL, line):
                if not re.search(EMAIL_ALLOWED, match.group(0)):
                    failures.append(f"{where}: e-mail address {match.group(0)!r}")


def check_gitignore(root, failures):
    path = root / ".gitignore"
    if not s.check(path.is_file(), ".gitignore missing", failures):
        return
    lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    for entry in GITIGNORE_REQUIRED:
        s.check(entry in lines, f".gitignore lacks {entry!r}", failures)


def run(root):
    failures = []
    scan(root, failures)
    check_gitignore(root, failures)
    if len(failures) > 60:
        extra = len(failures) - 60
        failures = failures[:60] + [f"... and {extra} more"]
    s.finish("T-PUBLICATION-BOUNDARY no engineering residue, secrets, local "
             "paths or personal data", failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    run(Path(args.root).resolve())


if __name__ == "__main__":
    main()
