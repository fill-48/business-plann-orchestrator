#!/usr/bin/env python3
"""T-REPORT-ENCODING — report JSON dei validator su console non UTF-8.

Su Windows la console usa tipicamente cp1252: se il report di un validator
contiene un carattere non rappresentabile (es. il '≤' nei messaggi di
`validate_market_arithmetic`), la stampa su stdout non deve sollevare
UnicodeEncodeError, non deve alterare gli exit code 0/1/2/3 e deve produrre
sempre JSON parseable. Il comportamento deve valere **senza** che il
chiamante imposti PYTHONIOENCODING (un testkit può impostarlo, una
sessione reale no) — qui PYTHONIOENCODING=cp1252 è usato solo per simulare
in modo deterministico la console Windows su qualunque piattaforma.

Verifiche:
1. unit — `_framework.Report` con errore contenente '≤', stampato da un
   sotto-processo con stdout cp1252: exit 0, stdout JSON parseable, il
   carattere sopravvive al round-trip `json.loads`;
2. integrazione — `validate_market_arithmetic` su fixture SOM > SAM
   (`market_ordering`, messaggio con '≤') con stdout cp1252: exit 1 e
   report (result/errors/warnings) identico a quello ottenuto con stdout
   UTF-8;
3. invarianza del caso PASS — candidate valido con stdout cp1252: exit 0 e
   JSON parseable.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import test_market_arithmetic as market


class TestFailure(AssertionError):
    pass


S4 = market.S4
LEQ = "≤"


def cp1252_env():
    """Ambiente Windows-like: stdout del figlio forzato a cp1252.

    Rimuove PYTHONUTF8/PYTHONIOENCODING ereditati e imposta cp1252 come
    farebbe la console Windows di default (locale getpreferredencoding).
    """
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    return env


def utf8_env():
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_cli(root, name, project, candidate, stage, phase, env):
    cmd = [sys.executable, str(Path(root) / kit.VALIDATORS_REL / f"{name}.py"),
           "--project", str(project), "--stage", stage, "--phase", phase]
    if candidate is not None:
        cmd += ["--candidate", str(candidate)]
    proc = subprocess.run(cmd, capture_output=True, env=env)
    out = proc.stdout.decode("cp1252", errors="replace")
    err = proc.stderr.decode("cp1252", errors="replace")
    return proc.returncode, out, err


def parse_or_fail(out, err, label):
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise TestFailure(
            f"{label}: stdout non JSON parseable con console cp1252 "
            f"- out {ascii(out.strip()[:200])} "
            f"err {ascii(err.strip()[:200])}")


def check_unit_report(root):
    """1. Report con '≤' stampato con stdout cp1252: mai UnicodeEncodeError."""
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);\n"
        "import _framework as fw\n"
        "r = fw.Report('encoding-probe', '04_market-and-competition', 'egress')\n"
        "r.add_error('market_ordering', ref='ASS-001',"
        " message='richiesto SOM \\u2264 SAM \\u2264 TAM')\n"
        "print(r.to_json())\n"
    )
    validators_dir = str(Path(root) / kit.VALIDATORS_REL)
    proc = subprocess.run([sys.executable, "-c", script, validators_dir],
                          capture_output=True, env=cp1252_env())
    out = proc.stdout.decode("cp1252", errors="replace")
    err = proc.stderr.decode("cp1252", errors="replace")
    if proc.returncode != 0:
        raise TestFailure(
            "unit: stampa del report con LEQ su stdout cp1252 fallita "
            f"(exit {proc.returncode}): {ascii(err.strip()[:300])}")
    report = parse_or_fail(out, err, "unit")
    msg = report["errors"][0]["message"]
    if LEQ not in msg:
        raise TestFailure(
            f"unit: LEQ perso nel round-trip json.loads: {ascii(msg)}")


def check_integration(root):
    """2.+3. validate_market_arithmetic con stdout cp1252 vs utf-8."""
    with tempfile.TemporaryDirectory(prefix="bpo-encoding-") as tmp:
        tmp = Path(tmp)

        # FAIL case: SOM > SAM -> market_ordering (messaggio con '≤').
        pf = market.stage4_project(tmp, "enc-fail")
        prop = market.market_proposed()
        prop = market.with_entry(prop, "reachable_share", value=0.9,
                                 display_value="0.9 ratio")
        prop = market.with_entry(prop, "som_y1_revenue", value=9000000,
                                 display_value="9000000 EUR")
        cf = kit.make_candidate(pf, S4, structured=market.structured(),
                                proposed=prop)

        exit_cp, out_cp, err_cp = run_cli(root, "validate_market_arithmetic",
                                          pf, cf, S4, "egress", cp1252_env())
        report_cp = parse_or_fail(out_cp, err_cp, "integrazione cp1252")
        if exit_cp != 1:
            raise TestFailure("integrazione cp1252: atteso exit 1 "
                              f"(candidate invalido), ottenuto {exit_cp} "
                              f"(err {err_cp.strip()[:200]!r})")
        codes = [e["code"] for e in report_cp["errors"]]
        if "market_ordering" not in codes:
            raise TestFailure(
                f"integrazione cp1252: atteso market_ordering, got {codes}")
        ordering_msgs = [e["message"] for e in report_cp["errors"]
                         if e["code"] == "market_ordering"]
        if not any(LEQ in m for m in ordering_msgs):
            raise TestFailure(
                "fixture non piu discriminante: il messaggio market_ordering "
                f"non contiene LEQ: {ascii(ordering_msgs)}")

        exit_u8, out_u8, err_u8 = run_cli(root, "validate_market_arithmetic",
                                          pf, cf, S4, "egress", utf8_env())
        report_u8 = json.loads(out_u8)
        if exit_u8 != exit_cp:
            raise TestFailure(
                f"exit code divergente tra console: cp1252={exit_cp} "
                f"utf-8={exit_u8}")
        for key in ("result", "errors", "warnings", "affected_refs"):
            if report_cp[key] != report_u8[key]:
                raise TestFailure(
                    f"report divergente tra console per {key}: "
                    f"cp1252={report_cp[key]!r} utf-8={report_u8[key]!r}")

        # PASS case invariato con stdout cp1252.
        pp = market.stage4_project(tmp, "enc-pass")
        cp = kit.make_candidate(pp, S4, structured=market.structured(),
                                proposed=market.market_proposed())
        exit_ok, out_ok, err_ok = run_cli(root, "validate_market_arithmetic",
                                          pp, cp, S4, "egress", cp1252_env())
        report_ok = parse_or_fail(out_ok, err_ok, "PASS cp1252")
        if exit_ok != 0 or report_ok["result"] != "PASS":
            raise TestFailure(
                f"PASS cp1252: atteso exit 0/PASS, ottenuto exit {exit_ok} "
                f"result {report_ok.get('result')!r}")


def run(root):
    check_unit_report(root)
    check_integration(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-REPORT-ENCODING report JSON su stdout anche con console "
          "non UTF-8")


if __name__ == "__main__":
    main()
