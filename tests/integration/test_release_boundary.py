#!/usr/bin/env python3
"""T-BOUNDARY — chiusura dello Stage 9 e release boundary sull'ULTIMO stage.

Il confine e' `13_document-generation`, ULTIMO stage di `stage_order`: non
esiste uno stage reale «oltre».

FORME DELLE GUARDIE NEGATIVE. Poiche' nessuno stage reale e' oltre il confine,
ogni guardia negativa conserva un bersaglio NON VACUO in una delle forme
ammesse: (T1) variante di config
in-process sulle funzioni pure del transaction manager
(`beyond_release_boundary`, `boundary_next_action`, `impact_window`); (T2)
identificatore ASSENTE da `stage_order` sul config reale -> exit 2, zero
mutazione, prima di lock e I/O. La catena CLI `stage_not_implemented` resta
viva nel solo specchio con il confine forzato (forma T3, `DG-C-16`).

Semantica scelta, UNA sola: `stage_not_implemented` come risultato di
dominio del transaction manager (exit 1, nessuna mutazione). Nessun nuovo
stato di governance e nessun uso di exit 2 come gate di prodotto —
l'invocazione di un validator fuori matrice resta un errore d'uso.

Invarianti verificate qui:
- `enforcement-config.json` dichiara `release_boundary = 13_document-generation`;
- il commit dell'advance dallo Stage 9 chiude lo Stage 9 senza renderlo
  terminale: `09_roadmap-and-milestones` in `completed_stages`,
  `current_stage = 10_financial-plan`, `status = not_started` e un
  `next_action` **boundary-aware** calcolato NELLA STESSA transazione, che
  invita ad avviare lo Stage 10, DENTRO il confine;
- nessuno stage esiste oltre il confine: `apply` e `advance-stage` su un
  identificatore assente da `stage_order` sono errori d'uso (exit 2) senza
  mutazioni (T2); `governance-status` e `next_action` restano boundary-aware
  su una variante in-process con il confine a `12_data-room` (T1);
- `validate_stage_gate --stage 13_document-generation` resta exit 2,
  documentato come errore di invocazione/configurazione e mai come gate.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


S7 = "07_operations-and-ip"
S8 = "08_team-and-governance"
S9 = "09_roadmap-and-milestones"
S10 = "10_financial-plan"
S11 = "11_funding-request"
S12 = "12_data-room"
S13 = "13_document-generation"

# Clausola ASSOLUTA (1b): nessun token di stage e' vietato per nome. Lo Stage
# 13, `13_document-generation`, e' DENTRO il confine — l'ultimo di
# `stage_order` — e una voce validator lo nomina legittimamente
# (`validate_document_generation`, `stages: [13]`). La clausola parametrica
# (1a) porta da sola il gate.
FORBIDDEN_STAGE_TOKENS = ()
#: Forma T2: un identificatore ASSENTE da `stage_order`, bersaglio non vacuo
#: di ogni operazione «oltre» l'ultimo stage.
ABSENT_STAGE = "14_after-terminal"

COMPLETED_THROUGH_8 = m5.COMPLETED_THROUGH_8


def beyond_boundary_project(tmp, name):
    """Progetto al confine: current_stage = 13_document-generation, l'ultimo
    stage di `stage_order`, con 00-12 completati. Lo Stage 13 e' DENTRO il
    confine: il progetto e' il bersaglio delle sonde T2 e T1, non un progetto
    «oltre»."""
    project = kit.make_project(
        tmp, name=name, current_stage=S13, status="not_started",
        completed=COMPLETED_THROUGH_8 + [S9, S10, S11, S12],
        assumptions=m5.market_assumptions())
    for stage in (m5.S6, S7, S8, S9, S10, S11, S12, S13):
        (project / stage).mkdir(exist_ok=True)
    return project


def stage_ordinal(config, stage):
    order = config.get("stage_order", {})
    if stage not in order:
        raise TestFailure(
            f"{stage!r} non è una cartella di stage canonica di stage_order")
    return int(order[stage])


def absolute_token_violations(config):
    """Clausola ASSOLUTA (1b), indipendente dal boundary.

    Respinge ogni voce validator che nomina un token di
    `FORBIDDEN_STAGE_TOKENS`, qualunque sia il `release_boundary`. Con il
    confine sull'ultimo stage l'elenco è vuoto: la clausola resta come
    struttura del gate congiuntivo, senza token vietati.
    """
    declared = json.dumps(config.get("validators", {}))
    return [f"nessuna voce validator può nominare {token}, a nessun boundary"
            for token in FORBIDDEN_STAGE_TOKENS if token in declared]


def parametric_stage_violations(config):
    """Clausola PARAMETRICA (1a) e invariante di `egress_required`.

    Nessuna voce validator nomina — per token o per ordinale — uno stage con
    ordinale maggiore di `stage_ordinal(release_boundary) + 1`, e nessun
    validator che dichiara stage oltre il boundary compare in
    `egress_required`. La forma è parametrica: vale per qualunque valore di
    `release_boundary`.
    """
    boundary = config.get("release_boundary")
    boundary_ordinal = stage_ordinal(config, boundary)
    max_declarable = boundary_ordinal + 1
    validators = config.get("validators", {})
    egress_required = config.get("egress_required", [])
    declared = json.dumps(validators)
    violations = []
    for stage, ordinal in sorted(config.get("stage_order", {}).items(),
                                 key=lambda kv: int(kv[1])):
        if int(ordinal) > max_declarable and stage in declared:
            violations.append(
                f"nessuna voce validator può nominare {stage}: ordinale "
                f"{ordinal} oltre {max_declarable} = ordinale del boundary "
                f"{boundary} + 1")
    for name, spec in sorted(validators.items()):
        stages = [int(s) for s in spec.get("stages", [])]
        beyond = [s for s in stages if s > max_declarable]
        if beyond:
            violations.append(
                f"{name}: la matrice non deve superare l'ordinale "
                f"{max_declarable}, trovato {beyond}")
        past_boundary = [s for s in stages if s > boundary_ordinal]
        if past_boundary and name in egress_required:
            violations.append(
                f"{name}: dichiara gli stage {past_boundary} oltre il "
                f"boundary {boundary} e non può comparire in egress_required")
    return violations


def boundary_violations(config):
    """Le due clausole sono CONGIUNTIVE: una voce è ammessa se e solo se
    soddisfa (1a) e (1b). Dove divergono, prevale l'assoluta."""
    return absolute_token_violations(config) + parametric_stage_violations(config)


def check_config(root):
    config = kit.read_json(root / kit.CONFIG_REL)
    if config.get("release_boundary") != S13:
        raise TestFailure(
            "enforcement-config deve dichiarare release_boundary = "
            f"{S13!r}, trovato {config.get('release_boundary')!r}")
    violations = boundary_violations(config)
    if violations:
        raise TestFailure("; ".join(violations))


def check_terminal_state(root, tmp):
    # Lo Stage 9 ha il proprio validator di dominio in egress: la chiusura
    # dello Stage 9 si raggiunge solo con una roadmap REALE (DAG aciclico,
    # owner sui ROLE- canonici, contratto financial_plan_inputs risolvibile),
    # non con un piano segnaposto. La fixture è quella condivisa con
    # T-MILESTONE-CHAIN: il boundary si dimostra su un avanzamento legittimo.
    project = m5.make_stage9_project(tmp, "terminal")
    candidate = kit.make_candidate(
        project, S9, tx_id="tx-stage9",
        structured=m5.milestone_structured(),
        proposed=m5.milestone_proposed(),
        handoff="# Handoff Stage 9\n\nRoadmap e milestone completate.\n")
    exit_code, out, err = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", S9,
        "--candidate", candidate, "--gate-result", "approved")
    if exit_code != 0:
        raise TestFailure(
            f"advance dallo Stage 9: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")

    front = kit.load_module(root, kit.VALIDATORS_REL, "_framework") \
        .parse_front_matter(
            (project / "shared/project-status.md").read_text(encoding="utf-8"))
    if S9 not in front.get("completed_stages", []):
        raise TestFailure(f"Stage 9 non in completed_stages: {front}")
    if front.get("current_stage") != S10:
        raise TestFailure(f"current_stage: {front.get('current_stage')!r}")
    if front.get("status") != "not_started":
        raise TestFailure(f"status: {front.get('status')!r}")
    next_action = front.get("next_action", "")
    if "release boundary" in next_action.lower():
        raise TestFailure(
            "next_action non deve portare il messaggio di confine — lo "
            f"Stage 10 e' DENTRO il release boundary: "
            f"{next_action!r}")
    if f"avviare {S10}" not in next_action:
        raise TestFailure(
            f"next_action deve invitare ad avviare lo Stage 10: "
            f"{next_action!r}")
    return project


def check_operations_beyond_boundary(root, tmp, terminal_project, tm):
    """Con il confine sull'ULTIMO stage non esiste uno stage reale «oltre». Gli operatori ESPLICITI (`apply`,
    `advance-stage`) bersagliano su ENTRAMBI i progetti un identificatore
    ASSENTE da `stage_order` (forma T2): errore d'uso, exit 2, ZERO mutazione,
    prima di lock e I/O. Il validator fuori matrice resta un errore d'uso.

    `governance-status` legge il `current_stage` PROPRIO del progetto: la sua
    guardia di confine e il `next_action` sono misurati in forma T1, sulla
    variante in-process con il confine a `12_data-room`, dove lo Stage 13
    torna «oltre»; sul config reale lo Stage 13 e' DENTRO."""
    projects = (("progetto dopo la chiusura dello Stage 9", terminal_project),
               ("progetto al confine", beyond_boundary_project(tmp, "beyond")))
    for label, project in projects:
        before = kit.snapshot_canonical(project)
        candidate = kit.make_candidate(
            project, ABSENT_STAGE, tx_id="tx-absent",
            structured={"document_generation": {}}, handoff="# Handoff\n")
        for command in ("apply", "advance-stage"):
            exit_code, out, err = kit.run_tm_cli(
                root, command, "--project", project, "--stage", ABSENT_STAGE,
                "--candidate", candidate)
            if exit_code != 2:
                raise TestFailure(
                    f"{label}: {command} su uno stage assente da stage_order "
                    f"deve dare exit 2, ottenuto {exit_code} (out "
                    f"{out.strip()!r} err {err.strip()!r})")
            if kit.snapshot_canonical(project) != before:
                raise TestFailure(
                    f"{label}: {command} oltre l'ultimo stage ha mutato il "
                    "canonico")

        # il validator fuori matrice resta un errore d'USO, non un gate
        exit_code, out, _ = kit.run_validator_cli(
            root, "validate_stage_gate", project=project, stage=S13,
            phase="ingress")
        if exit_code != 2:
            raise TestFailure(
                f"{label}: validate_stage_gate su uno stage fuori matrice "
                f"deve restare exit 2 (errore d'uso), ottenuto {exit_code}")

    # governance-status e next_action: forma T1 sulla variante in-process con
    # il confine a 12_data-room (la guardia di cmd_governance_status e'
    # `beyond_release_boundary` sul current_stage del progetto).
    real = kit.read_json(root / kit.CONFIG_REL)
    variant = json.loads(json.dumps(real))
    variant["release_boundary"] = S12
    if not tm.beyond_release_boundary(S13, variant):
        raise TestFailure(
            "T1: a confine 12 lo Stage 13 deve essere oltre il boundary: la "
            "guardia di governance-status sarebbe vacua")
    if tm.beyond_release_boundary(S13, real):
        raise TestFailure(
            "config reale: lo Stage 13 e' DENTRO il confine e non deve essere "
            "classificato oltre")
    action = tm.boundary_next_action(S13, variant)
    if "release boundary" not in action.lower():
        raise TestFailure(
            f"T1: next_action a confine 12 non boundary-aware: {action!r}")
    if tm.boundary_next_action(S13, real) != f"avviare {S13}":
        raise TestFailure(
            "config reale: next_action dello Stage 13 deve invitare ad "
            f"avviarlo: {tm.boundary_next_action(S13, real)!r}")


def check_boundary_negative_cases(root):
    """La forma boundary-aware dell'invariante NON è un indebolimento: i
    casi negativi TN-01…TN-04 devono fallire e la configurazione reale deve
    passare.

    Ogni caso è costruito su una COPIA sintetica della configurazione reale:
    nessun file di configurazione è scritto e il boundary reale non si muove.
    """
    real = kit.read_json(root / kit.CONFIG_REL)

    def variant(**over):
        config = json.loads(json.dumps(real))
        config.update(over)
        return config

    def must_fail(label, config, checker=boundary_violations):
        violations = checker(config)
        if not violations:
            raise TestFailure(
                f"caso negativo {label}: l'invariante di sostituzione non è "
                "più un gate — l'input doveva essere respinto e non lo è")
        return violations

    # TN-01 — voce validator con stages: [15] al boundary 13 (al boundary
    # reale [14] sarebbe DENTRO il dichiarabile, 14 <= 13 + 1, e non
    # dimostrerebbe nulla).
    tn01 = variant()
    tn01["validators"]["validate_stage_beyond_probe"] = {
        "stages": [15], "phases": ["egress"], "introduced_in": "NEVER"}
    must_fail("TN-01 stages: [15] a boundary 13", tn01)

    # TN-02 — forma T1: sulla variante con il confine a 12, una
    # voce che dichiara 13_document-generation (stages: [13]) ed entra in
    # egress_required e' RESPINTA dalla clausola parametrica (1a): lo Stage 13
    # vi e' oltre il boundary.
    tn02 = variant(release_boundary=S12)
    tn02["validators"]["validate_stage_beyond_probe"] = {
        "stages": [13], "phases": ["egress"], "introduced_in": "NEVER",
        "declared_stage_dir": "13_document-generation"}
    tn02["egress_required"] = [
        name for name in tn02.get("egress_required", [])
        if name != "validate_document_generation"] + [
        "validate_stage_beyond_probe"]
    must_fail("TN-02 13_document-generation in egress a boundary 12", tn02)

    # TN-03 — forma T1: la STESSA dichiarazione sulla stessa variante, FUORI
    # da egress_required, e' AMMESSA dal parametro (13 <= 12 + 1): il gate
    # discrimina l'ingresso in egress, non il nome. Senza token vietati per
    # nome (1b) e' la prova che la regola parametrica non e' ne' vacua ne'
    # indiscriminata.
    tn03 = variant(release_boundary=S12)
    tn03["validators"] = {
        name: spec for name, spec in tn03["validators"].items()
        if name != "validate_document_generation"}
    tn03["egress_required"] = [name for name in tn03["egress_required"]
                               if name != "validate_document_generation"]
    tn03["validators"]["validate_stage_beyond_probe"] = {
        "stages": [13], "phases": ["egress"], "introduced_in": "NEVER",
        "declared_stage_dir": "13_document-generation"}
    if parametric_stage_violations(tn03):
        raise TestFailure(
            "TN-03: al boundary 12 la dichiarazione dello Stage 13 fuori da "
            "egress_required deve essere ammessa dal parametro: "
            f"{parametric_stage_violations(tn03)}")

    # TN-04 — validator oltre il boundary presente in egress_required.
    # `validate_document_generation` dichiara stages: [13], DENTRO il
    # boundary: non dimostrerebbe nulla, quindi il caso è costruito con una
    # voce sintetica allo stage 14.
    tn04 = variant()
    tn04["validators"]["validate_stage_beyond_probe"] = {
        "stages": [14], "phases": ["egress"], "introduced_in": "NEVER"}
    tn04["egress_required"] = list(tn04.get("egress_required", [])) + [
        "validate_stage_beyond_probe"]
    must_fail("TN-04 validator oltre il boundary in egress_required", tn04)

    # Controllo positivo: la configurazione reale non produce alcuna
    # violazione. Senza di esso i casi negativi non
    # dimostrerebbero che il gate discrimina.
    if boundary_violations(real):
        raise TestFailure(
            "la configurazione reale deve superare l'invariante di "
            f"sostituzione: {boundary_violations(real)}")


def check_impact_window_capped(root, tm):
    """La finestra impact non supera mai il release boundary.

    Il boundary e' lo Stage 13, l'ultimo, quindi `impact_window(cfg, S13)` INCLUDE lo Stage 13 e parte dallo
    Stage 4; gli Stage 10, 11 e 12 vi restano. Il cap resta misurato in forma
    T1: con il confine a 12 lo Stage 13 torna FUORI dalla finestra."""
    config = tm.fw.load_config()
    window = tm.impact_window(config, S13)
    if window[0] != "04_market-and-competition" or window[-1] != S13:
        raise TestFailure(
            f"finestra attesa da 04_market-and-competition a {S13}, "
            f"trovata {window}")
    variant = json.loads(json.dumps(config))
    variant["release_boundary"] = S12
    capped = tm.impact_window(variant, S13)
    if S13 in capped or capped[-1] != S12:
        raise TestFailure(
            f"T1: a confine 12 la finestra deve fermarsi a {S12}: {capped}")
    for stage in (S10, S11, S12):
        if stage not in window:
            raise TestFailure(
                f"lo stage {stage} deve restare DENTRO la finestra impact: "
                f"{window}")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    check_config(root)
    check_boundary_negative_cases(root)
    check_impact_window_capped(root, tm)
    with tempfile.TemporaryDirectory(prefix="bpo-boundary-") as tmp:
        tmp = Path(tmp)
        terminal = check_terminal_state(root, tmp)
        check_operations_beyond_boundary(root, tmp, terminal, tm)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-BOUNDARY chiusura dello Stage 9 e release boundary")


if __name__ == "__main__":
    main()
