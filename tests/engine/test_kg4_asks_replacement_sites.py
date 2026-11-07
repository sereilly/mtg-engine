"""Census: every place a CR 614 event runs its CR 616.1 process either can
put the choice to the affected player, or has a recorded reason it cannot.

CR 616.1: "If two or more replacement and/or prevention effects are
attempting to modify the way an event affects an object or player, the
affected object's controller (or its owner if it has no controller) or the
affected player chooses one to apply". The registry asks only when its caller
hands it a way to re-run the event (``apply_replacements``' ``restart``, or an
``ask`` hook to ``effect_ordering.apply_in_order``); a call with neither takes
the default order for every seat, an interactive one included, and nothing
fails. kg4 `leftovers` counted eight such sites (deaths, discards, +1/+1
counters, a land's mana, the graveyard seam, leaving the battlefield,
entering it, untapping); only draws, life gains, damage and buyback asked.

Each site is classified here, so a new call cannot go silent unseen:

* **asks** — it passes ``restart`` (or ``ask``);
* **one effect** — every kind it raises has at most one registration, and a
  contention needs two. Asserted against the live registry, so the day a
  second is registered the site fails here instead of silently taking the
  default;
* **declined** — a contention the pool can build, measured and left with the
  parts that would clear it (the report of round kg4 `asks`).

An entry naming a site that no longer exists fails too. The behaviour of the
sites that ask is driven board by board in
``tests/regressions/test_kg4_asks_contended_moves.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from engine.damage_events import RESULT_KINDS
from engine.replacements.registry import REPLACEMENTS

_ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: Sites that pass no ``restart``, by (module, enclosing function): the kinds
#: each raises, and why it does not ask.
_ONE_EFFECT = {
    ("damage_events.py", "_process_results"): (
        tuple(RESULT_KINDS.values()),
        "CR 120.4c's results half: by then the dealt half has applied real "
        "effects, so a re-run would replay them",
    ),
    ("mixins/effects.py", "place_plus1_counters"): (
        ("plus1_counters",),
        "one effect (Conclave Mentor), standing for every copy: each adds "
        "one, so their order changes nothing",
    ),
    ("mixins/zone_funnels.py", "_leaving_battlefield_replaced"): (
        ("would_leave_battlefield",),
        "one effect (Dreams of the Dead's exile); a death asks it joined to "
        "the would-die and graveyard effects it meets there",
    ),
    ("mixins/land_tapped_for_mana.py", "_land_tapped_for_mana"): (
        ("land_mana_produced",),
        "one registration; the several producers that print it (Infernal "
        "Darkness, Deep Water …) reduce to one symbol by timestamp in "
        "land_mana_swaps.swapped_production, asked mid-payment (CR 601.2g)",
    ),
}

#: Contentions the pool can build that are measured and left (kg4 `asks`'s
#: report names the parts). Each must still have two or more registrations —
#: a declined site whose kind falls to one belongs in ``_ONE_EFFECT``.
_DECLINED = {
    ("mixins/zone_funnels.py", "_begin_entry"): (
        ("would_enter_battlefield",),
        "Land Equilibrium beside an Alliances land's unpayable toll (or "
        "Containment Priest beside a toll on an uncast creature): the entry "
        "seam's callers read False as 'replaced' and run their tails at "
        "once, and Land Equilibrium's effect does not replace the entry "
        "(the land still enters), so a suspended entry is not 'did not "
        "enter' whatever is answered. (Worms of the Earth is a CR 614.17 "
        "'can't', never a contender — 614.17c — and its order 0 already "
        "says so.)",
    ),
}


def _name(call: ast.Call) -> str:
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def _enclosing(parents, node):
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return None


def _census():
    """Every ``apply_replacements`` / ``apply_in_order`` call in ``engine/``:
    (module, function) -> whether it can ask."""
    sites: dict[tuple[str, str], list[bool]] = {}
    for path in sorted(_ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.relative_to(_ENGINE).as_posix()
        parents = {
            child: node for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _name(node)
            if called not in ("apply_replacements", "apply_in_order"):
                continue
            function = _enclosing(parents, node)
            if function in ("apply_replacements", "apply_in_order"):
                continue  # the definitions' own recursion, if any
            keywords = {keyword.arg for keyword in node.keywords}
            asks = bool(keywords & {"restart", "ask"})
            sites.setdefault((module, function), []).append(asks)
    return sites


def test_every_replacement_site_asks_or_says_why_it_cannot():
    sites = _census()
    # A floor on what was examined: thirteen calls at kg4 (eleven
    # ``apply_replacements``, two ``apply_in_order``) — a census that found
    # none has measured nothing.
    assert sum(len(calls) for calls in sites.values()) >= 12, sites
    silent = {site for site, calls in sites.items() if not all(calls)}
    excused = set(_ONE_EFFECT) | set(_DECLINED)
    unexplained = sorted(silent - excused)
    assert not unexplained, (
        "a CR 614 event that passes no restart never puts CR 616.1e's choice "
        f"to the affected player: {unexplained} — pass restart=, or record "
        "the reason here"
    )
    stale = sorted(excused - silent)
    assert not stale, f"excused sites that no longer exist or now ask: {stale}"


def test_a_site_excused_as_one_effect_still_has_one():
    contended = {
        site: {kind: len(REPLACEMENTS.get(kind, ())) for kind in kinds}
        for site, (kinds, _reason) in _ONE_EFFECT.items()
        if any(len(REPLACEMENTS.get(kind, ())) > 1 for kind in kinds)
    }
    assert not contended, (
        "a second effect of this kind is registered, so two can contend and "
        f"the site must ask (pass restart=): {contended}"
    )
    # …and the kinds named are real ones, or the check above passes over
    # nothing.
    # (A results kind with no registration yet — ``damage_marked`` — is a
    # real kind all the same.)
    unknown = sorted(
        kind for kinds, _ in _ONE_EFFECT.values() for kind in kinds
        if kind not in REPLACEMENTS and kind not in RESULT_KINDS.values()
    )
    assert not unknown, unknown


def test_a_declined_site_is_still_contended():
    settled = {
        site: kinds for site, (kinds, _reason) in _DECLINED.items()
        if all(len(REPLACEMENTS.get(kind, ())) < 2 for kind in kinds)
    }
    assert not settled, (
        f"these kinds can no longer contend; move the site to _ONE_EFFECT: {settled}"
    )
