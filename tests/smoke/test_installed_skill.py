#!/usr/bin/env python3
"""T-INSTALLED-SKILL — the installed skill is self-sufficient.

The skill is installed into a temporary home and exercised from a working
directory outside the repository:

1. the package contains only runtime material (no tests, docs, examples,
   caches) and SKILL.md has a valid front matter;
2. every relative Markdown link of the installed package resolves to a file
   inside the installed package;
3. no installed text refers to repository-only material (engineering
   documents, repository-relative script paths, files outside the package);
4. no runtime Python module derives paths above its own package (for example
   `SKILL_ROOT.parents[2]` or `Path(__file__).parents[4]`): the behaviour of an
   installed skill must not depend on where a repository checkout is;
5. the transaction manager and several validators, launched from the
   installed copy with a working directory outside the repository, run on a
   copy of the fictional example and leave it byte-identical.
"""
import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import smoke_support as s

TEXT_SUFFIXES = {".md", ".json", ".py"}
# Names of documents that exist only outside the published package are
# assembled at runtime so that the scan of this repository does not match
# its own patterns.
FORBIDDEN_TEXT = (
    ("../../../", "link that escapes the package"),
    ("AGENT_" + "ARCHITECTURE.md", "repository-level document"),
    ("business-plan-" + "logic.md", "unpublished document"),
    ("docs/" + "reviews", "unpublished document"),
    ("tests/manifest", "engineering manifest"),
    ("release-0.", "engineering manifest"),
    ("projects/example-startup", "engineering demo project"),
    ("python .claude/skills/", "repository-relative command"),
    ("python .../", "abbreviated command without <skill_dir>"),
    ("dalla radice che contiene", "repository-relative working directory"),
)
IMPACT_RUNS = (
    ("validate_market_arithmetic", "04_market-and-competition"),
    ("validate_operations_feasibility", "07_operations-and-ip"),
    ("validate_team_and_governance", "08_team-and-governance"),
    ("validate_milestone_chain", "09_roadmap-and-milestones"),
)


def check_package(skill, failures):
    top = sorted(p.name for p in skill.iterdir())
    for unexpected in ("tests", "docs", "examples", "projects", "README.md"):
        s.check(unexpected not in top,
                f"installed package contains {unexpected!r}", failures)
    caches = [p for p in skill.rglob("*")
              if p.name == "__pycache__" or p.suffix == ".pyc"]
    s.check(not caches, f"installed package contains caches: {caches[:3]}",
            failures)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if s.check(match is not None, "SKILL.md has no front matter", failures):
        head = match.group(1)
        s.check(re.search(r"^name: business-plan-orchestrator$", head, re.M)
                is not None, "SKILL.md front matter: wrong name", failures)
        s.check(re.search(r"^description: \S", head, re.M) is not None,
                "SKILL.md front matter: missing description", failures)


def check_links(skill, failures):
    root = skill.resolve()
    count = 0
    for md in sorted(skill.rglob("*.md")):
        for target in s.markdown_links(md):
            if not target:
                continue
            count += 1
            resolved = (md.parent / target).resolve()
            rel = md.relative_to(skill).as_posix()
            try:
                resolved.relative_to(root)
            except ValueError:
                failures.append(f"{rel}: link escapes the package: {target}")
                continue
            s.check(resolved.exists(), f"{rel}: broken link: {target}",
                    failures)
    s.check(count > 50, f"suspiciously few links checked: {count}", failures)


def check_text(skill, failures):
    for path in sorted(skill.rglob("*")):
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(skill).as_posix()
        for needle, why in FORBIDDEN_TEXT:
            if needle in text:
                failures.append(f"{rel}: contains {needle!r} ({why})")


def ancestor_depth(node):
    """(N, base) for expressions `<base>.parents[N]` where the base is the
    module file (`__file__`) or the package root (`SKILL_ROOT`)."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "parents":
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            base = ast.dump(node.value.value)
            if "__file__" in base:
                return index.value, "file"
            if "'SKILL_ROOT'" in base:
                return index.value, "skill_root"
    return None


def check_location_independence(skill, failures):
    """A module may reach its own package root (SKILL_ROOT, i.e. the parent
    of its sub-directory) but nothing above it."""
    for path in sorted(skill.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(skill).as_posix()
        # validators/x.py: parents[0] = validators/, parents[1] = package root
        depth_to_root = len(Path(rel).parts) - 1
        for node in ast.walk(tree):
            found = ancestor_depth(node)
            if not found:
                continue
            index, base = found
            limit = depth_to_root if base == "file" else -1
            if index > limit:
                failures.append(
                    f"{rel}:{node.lineno}: path computed above the installed "
                    f"package (parents[{index}]): behaviour depends on where "
                    "the skill is located")


def run_py(args, cwd):
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=str(cwd), env=s.home_env(Path(cwd)))


def check_runtime(root, skill, work, failures):
    project = work / "workdir" / "demo"
    import shutil
    shutil.copytree(root / "examples" / "fictional-startup", project)
    before = s.tree_digest(project)
    cwd = project.parent
    proc = run_py([str(skill / "transaction" / "transaction_manager.py"),
                   "recover", "--project", "demo"], cwd)
    if s.check(proc.returncode == 0,
               f"transaction_manager recover exit {proc.returncode}: "
               f"{proc.stderr[-300:]}", failures):
        try:
            s.check(json.loads(proc.stdout).get("actions") == [],
                    f"recover on a clean project is not a no-op: {proc.stdout}",
                    failures)
        except json.JSONDecodeError:
            failures.append(f"recover did not print JSON: {proc.stdout[:200]}")
    for validator, stage in IMPACT_RUNS:
        proc = run_py([str(skill / "validators" / f"{validator}.py"),
                       "--project", "demo", "--stage", stage,
                       "--phase", "impact"], cwd)
        s.check(proc.returncode == 0,
                f"{validator} --stage {stage} --phase impact exit "
                f"{proc.returncode}: {(proc.stdout + proc.stderr)[-300:]}",
                failures)
    s.check(s.tree_digest(project) == before,
            "running the installed skill modified the example project",
            failures)


def run(root):
    failures = []
    with tempfile.TemporaryDirectory(prefix="bpo-installed-") as tmp:
        work = Path(tmp)
        skill = s.install_skill(root, work)
        check_package(skill, failures)
        check_links(skill, failures)
        check_text(skill, failures)
        check_location_independence(skill, failures)
        check_runtime(root, skill, work, failures)
    s.finish("T-INSTALLED-SKILL installed package is self-sufficient",
             failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    run(Path(args.root).resolve())


if __name__ == "__main__":
    main()
