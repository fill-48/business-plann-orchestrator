#!/usr/bin/env python3
"""T-INSTALL — install, reinstall with backup and uninstall in a temporary home.

For every available installer (bash `install.sh`, PowerShell `install.ps1`):

1. a fresh install copies exactly the skill package (same files, same bytes)
   into <home>/.claude/skills/business-plan-orchestrator, without Python
   caches planted in the source;
2. a reinstall backs up the previous installation (with local changes) into
   <home>/.claude/skill-backups/ and restores a pristine copy;
3. an uninstall backs up and removes the installation;
4. backups never land inside <home>/.claude/skills/ (Claude Code would
   discover them as duplicate skills);
5. the bash installer rejects unknown options.

Installers run from a temporary mirror of the repository: the checkout is
never written.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import smoke_support as s


def exercise(kind, root, work, failures):
    mirror = s.make_mirror(root, work / "mirror")
    # A cache planted in the source must never be installed.
    cache = mirror / s.SKILL_REL / "validators" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "planted.cpython-312.pyc").write_bytes(b"\0cache")

    home = work / "home"
    home.mkdir()
    installed = home / ".claude" / "skills" / s.SKILL_NAME
    backups = home / ".claude" / "skill-backups"
    expected = s.tree_digest(root / s.SKILL_REL)

    proc = s.run_installer(kind, mirror, home)
    if not s.check(proc.returncode == 0,
                   f"[{kind}] install exit {proc.returncode}: {proc.stderr[-400:]}",
                   failures):
        return
    got = s.tree_digest(installed, skip_cache=False)
    s.check(got == expected,
            f"[{kind}] installed tree differs from the package: "
            f"missing={sorted(set(expected) - set(got))[:5]} "
            f"extra={sorted(set(got) - set(expected))[:5]} "
            f"changed={sorted(k for k in expected if k in got and got[k] != expected[k])[:5]}",
            failures)
    s.check(not backups.exists() or not any(backups.iterdir()),
            f"[{kind}] a first install must not create backups", failures)

    # Reinstall over a locally modified installation.
    marker = installed / "LOCAL-CHANGE.txt"
    marker.write_text("local change", encoding="utf-8")
    proc = s.run_installer(kind, mirror, home)
    s.check(proc.returncode == 0,
            f"[{kind}] reinstall exit {proc.returncode}: {proc.stderr[-400:]}",
            failures)
    saved = sorted(backups.glob(f"{s.SKILL_NAME}.bak-*")) if backups.exists() else []
    s.check(len(saved) == 1, f"[{kind}] reinstall backups: {saved}", failures)
    if saved:
        s.check((saved[0] / "LOCAL-CHANGE.txt").is_file(),
                f"[{kind}] the backup does not contain the previous installation",
                failures)
        s.check((saved[0] / "SKILL.md").is_file(),
                f"[{kind}] the backup is nested or incomplete", failures)
    s.check(s.tree_digest(installed, skip_cache=False) == expected,
            f"[{kind}] reinstall did not restore a pristine package", failures)

    # Uninstall (same second as the previous backup: names must not collide).
    proc = s.run_installer(kind, mirror, home,
                           "--uninstall" if kind == "bash" else "-Uninstall")
    s.check(proc.returncode == 0,
            f"[{kind}] uninstall exit {proc.returncode}: {proc.stderr[-400:]}",
            failures)
    s.check(not installed.exists(), f"[{kind}] uninstall left {installed}",
            failures)
    saved = sorted(backups.glob(f"{s.SKILL_NAME}.bak-*"))
    s.check(len(saved) == 2 and all((b / "SKILL.md").is_file() for b in saved),
            f"[{kind}] uninstall must add a complete backup: {saved}", failures)
    skills_dir = home / ".claude" / "skills"
    leaked = [p.name for p in skills_dir.iterdir()] if skills_dir.exists() else []
    s.check(not leaked, f"[{kind}] leftovers in the skills directory: {leaked}",
            failures)

    if kind == "bash":
        proc = s.run_installer(kind, mirror, home, "--bogus")
        s.check(proc.returncode == 2,
                f"[bash] unknown option must exit 2, got {proc.returncode}",
                failures)


def run(root):
    failures = []
    kinds = s.available_installers()
    s.check(bool(kinds), "no installer shell available (bash or PowerShell)",
            failures)
    for kind in kinds:
        with tempfile.TemporaryDirectory(prefix=f"bpo-install-{kind}-") as tmp:
            exercise(kind, root, Path(tmp), failures)
    s.finish(f"T-INSTALL installers {'/'.join(kinds) or '-'}: install, "
             "backup, reinstall, uninstall", failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    run(Path(args.root).resolve())


if __name__ == "__main__":
    main()
