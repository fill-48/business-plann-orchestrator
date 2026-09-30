#!/usr/bin/env python3
"""T-STRUCTURE — repository structure, schemas, example and documentation links.

1. every JSON file parses; every *.schema.json is a valid Draft 2020-12 schema;
2. the fictional example validates against the package schemas;
3. every relative Markdown link in the repository resolves;
4. every stage of `stage_order` has its workflow, and `release_boundary` is
   the last stage;
5. the published version (0.7.1) is consistent across README, CHANGELOG,
   SKILL.md and the architecture reference;
6. the documentation files promised by the README exist.
"""
import argparse
import json
import re
from pathlib import Path

import smoke_support as s

VERSION = "0.7.1"
EXAMPLE = "examples/fictional-startup"
EXAMPLE_SCHEMAS = {
    "shared/assumptions-register.json": "assumptions-register",
    "shared/evidence-register.json": "evidence-register",
    "shared/source-register.json": "source-register",
    "shared/risk-register.json": "risk-register",
    "shared/decisions-register.json": "decisions-register",
    "shared/conditions-register.json": "conditions-register",
    "shared/startup-profile.json": "startup-profile",
    "shared/project-config.json": "project-config",
    "07_operations-and-ip/structured-output.json": "operations-model",
    "08_team-and-governance/structured-output.json": "team-governance",
    "09_roadmap-and-milestones/structured-output.json": "milestone-plan",
}
DOCS = ("installation", "usage", "workflow", "methodology", "architecture",
        "troubleshooting", "privacy-and-data-handling")


def load_validator(failures):
    try:
        from jsonschema import Draft202012Validator
        return Draft202012Validator
    except ImportError:
        failures.append("jsonschema is not installed (pip install -r requirements.txt)")
        return None


def check_json(root, validator, failures):
    count = 0
    for path in s.repo_files(root):
        if path.suffix != ".json":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{rel}: invalid JSON: {exc}")
            continue
        count += 1
        if rel.endswith(".schema.json") and validator is not None:
            try:
                validator.check_schema(doc)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{rel}: invalid JSON Schema: {exc}")
    s.check(count > 30, f"suspiciously few JSON files: {count}", failures)


def check_example(root, validator, failures):
    if validator is None:
        return
    schemas = root / s.SKILL_REL / "schemas"
    for rel, name in EXAMPLE_SCHEMAS.items():
        path = root / EXAMPLE / rel
        if not s.check(path.is_file(), f"{EXAMPLE}/{rel} missing", failures):
            continue
        schema = json.loads((schemas / f"{name}.schema.json").read_text(encoding="utf-8"))
        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator(schema).iter_errors(doc), key=lambda e: e.path)
        s.check(not errors, f"{EXAMPLE}/{rel} violates {name}: "
                f"{[e.message for e in errors[:2]]}", failures)
    status = (root / EXAMPLE / "shared" / "project-status.md").read_text(encoding="utf-8")
    s.check(status.startswith("---\n"), "example project-status.md has no front matter",
            failures)
    for marker in ("Esempio completamente fittizio",):
        for md in sorted((root / EXAMPLE).rglob("*.md")):
            text = md.read_text(encoding="utf-8")
            s.check(marker in text, f"{md.relative_to(root).as_posix()}: "
                    "missing the fictional-example banner", failures)


def check_links(root, failures):
    count = 0
    for path in s.repo_files(root):
        if path.suffix != ".md":
            continue
        rel = path.relative_to(root).as_posix()
        for target in s.markdown_links(path):
            if not target:
                continue
            count += 1
            s.check((path.parent / target).resolve().exists(),
                    f"{rel}: broken link: {target}", failures)
    s.check(count > 100, f"suspiciously few links checked: {count}", failures)


def check_stages(root, failures):
    skill = root / s.SKILL_REL
    config = json.loads((skill / "config" / "enforcement-config.json").read_text(encoding="utf-8"))
    order = sorted(config["stage_order"], key=config["stage_order"].get)
    s.check(config["release_boundary"] == order[-1],
            f"release_boundary {config['release_boundary']!r} is not the last "
            f"stage {order[-1]!r}", failures)
    workflows = {p.name for p in (skill / "workflows").glob("*.md")}
    for stage in order:
        number = config["stage_order"][stage]
        expected = f"{number + 1:02d}_{stage[3:]}.md" if number else "01_idea-discovery.md"
        s.check(expected in workflows, f"stage {stage}: workflow {expected} missing",
                failures)
    skill_md = (skill / "SKILL.md").read_text(encoding="utf-8")
    for name in sorted(workflows):
        s.check(f"workflows/{name}" in skill_md, f"SKILL.md does not route {name}",
                failures)


def check_version(root, failures):
    readme = (root / "README.md").read_text(encoding="utf-8")
    s.check(f"v{VERSION}" in readme, f"README does not state v{VERSION}", failures)
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## \[([^\]]+)\]", changelog, re.M)
    s.check(first is not None and first.group(1) == VERSION,
            f"CHANGELOG top entry is {first.group(1) if first else None!r}, "
            f"expected {VERSION}", failures)
    skill = (root / s.SKILL_REL / "SKILL.md").read_text(encoding="utf-8")
    s.check(VERSION in skill, f"SKILL.md does not state {VERSION}", failures)
    arch = (root / s.SKILL_REL / "reference" / "architecture.md").read_text(encoding="utf-8")
    s.check(VERSION in arch, f"architecture reference does not state {VERSION}",
            failures)


def check_docs(root, failures):
    for name in DOCS:
        s.check((root / "docs" / f"{name}.md").is_file(), f"docs/{name}.md missing",
                failures)
    for name in ("README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md",
                 "CHANGELOG.md", "requirements.txt",
                 "install.sh", "install.ps1", ".gitignore", ".gitattributes"):
        s.check((root / name).is_file(), f"{name} missing", failures)
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    s.check(license_text.startswith("MIT License") and
            "Copyright (c) 2026 " in license_text and
            "Permission is hereby granted, free of charge" in license_text,
            "LICENSE is not the expected MIT licence", failures)


def run(root):
    failures = []
    validator = load_validator(failures)
    check_json(root, validator, failures)
    check_example(root, validator, failures)
    check_links(root, failures)
    check_stages(root, failures)
    check_version(root, failures)
    check_docs(root, failures)
    s.finish("T-STRUCTURE JSON, schemas, example, links, stages, version, docs",
             failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    run(Path(args.root).resolve())


if __name__ == "__main__":
    main()
