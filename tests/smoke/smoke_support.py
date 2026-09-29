"""Shared helpers for the smoke tests.

The smoke tests never write into the checkout: installers run from a
temporary mirror of the repository and install into a temporary home.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_NAME = "business-plan-orchestrator"
SKILL_REL = f".claude/skills/{SKILL_NAME}"
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class TestFailure(AssertionError):
    pass


def check(condition, message, failures):
    if not condition:
        failures.append(message)
    return condition


def finish(label, failures):
    if failures:
        print(f"FAIL: {label}")
        for item in failures:
            print(f"  - {item}")
        sys.exit(1)
    print(f"PASS: {label}")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root, skip_cache=True):
    """relative posix path -> sha256 for every file under root."""
    root = Path(root)
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if skip_cache and ("__pycache__" in path.parts or path.suffix == ".pyc"):
            continue
        out[rel] = sha256(path)
    return out


def repo_files(root):
    """Files that belong to the repository (what would be committed).

    Inside a Git work tree: tracked files plus untracked, non-ignored files.
    Otherwise: every file except VCS metadata and local caches.
    """
    root = Path(root)
    if (root / ".git").exists() and shutil.which("git"):
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"], capture_output=True)
        if proc.returncode == 0:
            rels = [r for r in proc.stdout.decode("utf-8").split("\0") if r]
            return sorted(root / r for r in rels if (root / r).is_file())
    skip_dirs = {".git", "__pycache__", ".working", ".tx", ".pytest_cache"}
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts) & skip_dirs) \
                and path.suffix != ".pyc":
            files.append(path)
    return files


def markdown_links(path):
    text = Path(path).read_text(encoding="utf-8")
    # ignore links inside fenced code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for match in LINK_RE.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        yield target.split("#", 1)[0]


def find_bash():
    """A POSIX bash able to handle native paths (Git Bash on Windows)."""
    if os.name == "nt":
        for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                          r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(candidate).is_file():
                return candidate
        found = shutil.which("bash")
        if found and "system32" not in found.lower():
            return found
        return None
    return shutil.which("bash")


def find_powershell():
    for name in ("pwsh", "powershell") if os.name == "nt" else ("pwsh",):
        found = shutil.which(name)
        if found:
            return found
    return None


def make_mirror(root, dest):
    """Copy installers and the skill package into a temporary mirror."""
    root, dest = Path(root), Path(dest)
    shutil.copytree(root / SKILL_REL, dest / SKILL_REL,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("install.sh", "install.ps1", "requirements.txt"):
        shutil.copy2(root / name, dest / name)
    return dest


def home_env(home):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_installer(kind, mirror, home, *args):
    mirror = Path(mirror)
    if kind == "bash":
        bash = find_bash()
        cmd = [bash, str(mirror / "install.sh"), *args]
    elif kind == "powershell":
        shell = find_powershell()
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(mirror / "install.ps1"), *args]
    else:
        raise ValueError(kind)
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=home_env(home), cwd=str(mirror))


def available_installers():
    kinds = []
    if find_bash():
        kinds.append("bash")
    if find_powershell():
        kinds.append("powershell")
    return kinds


def install_skill(root, workdir):
    """Install the skill into a fresh temporary home and return its path.

    Uses the first available installer; falls back to a plain copy only when
    no shell is available (the installer itself is covered by test_install).
    """
    workdir = Path(workdir)
    home = workdir / "home"
    home.mkdir(parents=True)
    kinds = available_installers()
    if kinds:
        mirror = make_mirror(root, workdir / "mirror")
        proc = run_installer(kinds[0], mirror, home)
        if proc.returncode != 0:
            raise TestFailure(f"installer {kinds[0]} failed: "
                              f"{proc.stdout}\n{proc.stderr}")
    else:
        shutil.copytree(Path(root) / SKILL_REL,
                        home / ".claude" / "skills" / SKILL_NAME,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return home / ".claude" / "skills" / SKILL_NAME
