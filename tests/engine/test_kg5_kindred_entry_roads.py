"""Census: every road onto the battlefield asks CR 400.4a of the card it takes
out of a zone — or is listed with the reason its card is a permanent card by
construction.

    400.4a If an instant or sorcery card would enter the battlefield, it
    remains in its previous zone.

``Game._put_permanent_onto_battlefield`` is the one funnel every entry goes
through, but by the time it is called the card has left its zone, and "remains
in its previous zone" is a card that never left. So the question is asked on
each road, before the take, through ``engine/permanent_cards.py``
(``is_permanent_card`` / ``stays_out_of_battlefield``). This census reads every
caller of the funnel out of ``engine/`` (an AST walk, so a new road cannot be
missed by a hand-kept list) and holds each to one of three answers:

* it asks itself;
* a named function upstream of it asks, before the card leaves its zone;
* its card is a permanent card by construction, for a stated reason — and
  where that reason is a claim about compiled programs, the pool census below
  holds the claim.

Validated backwards: the first test, with these tables, over the base's
sources (59f133e63, where only ``handlers/hand._put_entrants`` asked anything,
through a local tuple) names 23 of the 38 callers; removing any one road's ask
names it again. The pool census beside it fails on any compiled program whose
card the structural reasons would not cover.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar.vocabulary import PERMANENT_CARD_TYPES
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.permanent_cards import is_permanent_card

ENGINE = Path(__file__).resolve().parents[2] / "engine"
FUNNEL = "_put_permanent_onto_battlefield"
ASKS = frozenset({"stays_out_of_battlefield", "is_permanent_card"})

#: Callers whose question is asked by a function in front of them, before the
#: card leaves its zone.
ASKED_UPSTREAM = {
    "handlers/reanimation.py:_return_planned_cards":
        "handlers/reanimation.py:return_all_cards_from_graveyard",
    "mixins/stack/choices/hand.py:_resolve_put_from_hand_choice":
        # The answer is checked against the candidate list.
        "handlers/hand.py:put_from_hand_candidates",
    "mixins/stack/choices/pile_picks.py:_move_picked_pile_card":
        # The pick's own fate; the other caller moves only "the rest", which
        # the lowering sends to a graveyard (``_lower_reveal_top_opponent_chooses``).
        "mixins/stack/choices/pile_picks.py:_resolve_opponent_picks_revealed",
    "mixins/stack/choices/search.py:_place_found_card":
        # Every slot the battlefield: asked before the finds are taken. A split
        # between the battlefield and another zone over a phrase that can name
        # an instant refuses (``lowering/search.MIXED_SLOTS_ADMIT_A_NONPERMANENT``).
        "mixins/stack/choices/search.py:_resolve_search_library_picks",
    "replacements/zone_changes.py:discarded_onto_battlefield":
        "replacements/zone_changes.py:_discard_battlefield_entry",
}

#: Callers whose card is a permanent card by construction, and why.
PERMANENT_BY_CONSTRUCTION = {
    "handlers/tokens.py:create_token": "a token (CR 111.1), not a card in a zone",
    "mixins/permanent_state.py:create_token_copy": "a token copy (CR 707.2)",
    "mixins/stack/choices/card_names.py:_resolve_name_and_strip": "the tokens it makes",
    "mixins/stack/resolution.py:_resolve_card":
        "a permanent spell resolving (CR 608.3); an instant or sorcery spell "
        "goes to its owner's graveyard instead (CR 608.2n)",
    "mixins/stack/choices/spells.py:_resolve_face_down_cast":
        "a face-down spell, a 2/2 creature (CR 702.37c, 708.2)",
    "replacements/permanents.py:_resolve_entry_discard_toll":
        "the permanent already on its way in (Mox Diamond's toll is its own entry)",
    "handlers/reanimation.py:reanimate_bound_card":
        "the card of the creature whose death fired the trigger (CR 603.10a)",
    "handlers/reanimation.py:return_source_card_to_battlefield":
        "the ability's own source card (census: a permanent card)",
    "handlers/reanimation.py:return_self_from_graveyard":
        "this card returning itself (census: a permanent card)",
    "handlers/reanimation.py:reanimate_aura_onto_source":
        "an Aura card (census: its payload names the enchantment type)",
    "handlers/search.py:place_held_card":
        "Transmute Artifact's held find (census: its search names a permanent type)",
    "handlers/stack.py:_redirect_countered_card":
        "a countered spell, sent there only behind a printed spell class "
        "(census: Desertion's artifact)",
    "mixins/oracle_instructions.py:_apply_aura_effect":
        "the reanimation Aura's creature card (asked of the card's type line)",
    "phases/cleanup_step.py:resolve_cleanup_step":
        "a permanent exiled until end of turn returning (CR 610.3)",
    "phases/upkeep_step.py:_resolve_upkeep_actions":
        "Nether Shadow's own creature card returning itself",
}


def _units(tree: ast.Module):
    """Module-level functions and class methods, each with its nested defs."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield inner


def _called(unit) -> set[str]:
    names = set()
    for node in ast.walk(unit):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(getattr(func, "attr", None) or getattr(func, "id", None))
    return names


@pytest.fixture(scope="module")
def engine_calls() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for path in sorted(ENGINE.rglob("*.py")):
        rel = path.relative_to(ENGINE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for unit in _units(tree):
            calls.setdefault(f"{rel}:{unit.name}", set()).update(_called(unit))
    return calls


def test_every_road_onto_the_battlefield_asks_cr_400_4a(engine_calls):
    callers = {key for key, names in engine_calls.items() if FUNNEL in names}
    assert len(callers) >= 30, sorted(callers)
    unanswered = []
    for key in sorted(callers):
        if engine_calls[key] & ASKS:
            continue
        upstream = ASKED_UPSTREAM.get(key)
        if upstream is not None:
            if not engine_calls.get(upstream, set()) & ASKS:
                unanswered.append(f"{key}: its upstream {upstream} asks nothing")
            continue
        if key in PERMANENT_BY_CONSTRUCTION:
            continue
        unanswered.append(key)
    assert not unanswered, (
        "a road onto the battlefield that never asks whether its card can "
        "enter (CR 400.4a, engine/permanent_cards.py) — ask it before the card "
        "leaves its zone, or list the reason its card is a permanent card:\n  "
        + "\n  ".join(unanswered)
    )


def test_the_road_tables_name_only_callers_that_do_not_ask(engine_calls):
    """A listed road that stopped calling the funnel, or that now asks for
    itself, is a stale row — the table is the corpus the census acts on."""
    callers = {key for key, names in engine_calls.items() if FUNNEL in names}
    stale = [
        key for key in (*ASKED_UPSTREAM, *PERMANENT_BY_CONSTRUCTION)
        if key not in callers or engine_calls[key] & ASKS
    ]
    assert not stale, stale


# --- the pool census: the structural reasons, and the fold --------------------


def _walk(obj, out, *, kind=None):
    if isinstance(obj, OracleInstruction):
        out.append((obj.kind, obj.payload))
        _walk(obj.payload, out)
        return
    if isinstance(obj, dict):
        for value in obj.values():
            _walk(value, out)
        return
    if isinstance(obj, (list, tuple)):
        for value in obj:
            _walk(value, out)
        return
    for name in getattr(obj, "__dataclass_fields__", ()):
        _walk(getattr(obj, name, None), out)


def _types(value) -> tuple[str, ...]:
    if value in (None, "", "any"):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(word) for word in value)
    return (str(value),)


@pytest.fixture(scope="module")
def pool():
    rows = []
    for unit in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        program = compile_card_oracle(unit)
        found: list = []
        _walk((program.instructions, program.triggered_abilities,
               program.activated_abilities,
               tuple(mode.instruction for mode in program.modes)), found)
        rows.append((unit, found))
    return rows


def test_the_structural_roads_carry_only_permanent_cards(pool):
    """The claims ``PERMANENT_BY_CONSTRUCTION`` makes about compiled programs:
    a card that returns itself (or its source's card) to the battlefield is a
    permanent card; the Aura reanimation names the enchantment type; Transmute
    Artifact's search and Desertion's redirect name permanent types."""
    examined: dict[str, int] = {}
    wrong = []
    permanent = set(PERMANENT_CARD_TYPES)
    for unit, found in pool:
        for kind, payload in found:
            if kind == "return_self_from_graveyard" and payload.get("to", "battlefield") == "battlefield":
                examined[kind] = examined.get(kind, 0) + 1
                if not is_permanent_card(unit):
                    wrong.append((unit.name, kind))
            elif kind == "return_source_card_to_battlefield":
                examined[kind] = examined.get(kind, 0) + 1
                if not is_permanent_card(unit):
                    wrong.append((unit.name, kind))
            elif kind == "reanimate_aura_onto_source":
                examined[kind] = examined.get(kind, 0) + 1
                if not set(_types(payload.get("card_type"))) <= permanent or not _types(payload.get("card_type")):
                    wrong.append((unit.name, kind))
            elif kind == "transmute_by_sacrifice":
                examined[kind] = examined.get(kind, 0) + 1
                named = _types((payload.get("search_filter") or {}).get("type_filter"))
                if not named or not set(named) <= permanent:
                    wrong.append((unit.name, kind))
            elif payload.get("countered_destination") == "battlefield_your_control":
                examined["battlefield_your_control"] = examined.get("battlefield_your_control", 0) + 1
                named = _types((payload.get("countered_filter") or {}).get("type_filter"))
                if not named or not set(named) <= permanent:
                    wrong.append((unit.name, kind))
    assert not wrong, wrong
    assert examined.get("return_self_from_graveyard", 0) >= 10, examined
    assert examined.get("return_source_card_to_battlefield", 0) >= 5, examined
    assert examined.get("reanimate_aura_onto_source", 0) >= 1, examined
    assert examined.get("transmute_by_sacrifice", 0) >= 1, examined
    assert examined.get("battlefield_your_control", 0) >= 1, examined


def test_the_one_predicate_reads_every_card_as_the_readings_it_replaced(pool):
    """The fold moved nothing on the pool: ``is_permanent_card`` answers every
    card as ``handlers/hand``'s ``primary_type in _PERMANENT_TYPES`` did (which
    read one word of a multi-type line and left out battles), and its negation
    as Dodecapod's ``primary_type in ("instant", "sorcery")`` did. The pool has
    no Kindred and no battle card, which is where the readings part."""
    old_permanent = {"artifact", "creature", "enchantment", "land", "planeswalker"}
    differ = []
    for unit, _found in pool:
        new = is_permanent_card(unit)
        if new != (unit.primary_type in old_permanent):
            differ.append((unit.name, unit.type_line, "permanent types"))
        if (not new) != (unit.primary_type in ("instant", "sorcery")):
            differ.append((unit.name, unit.type_line, "instant or sorcery"))
    assert len(pool) >= 6000
    assert not differ, differ[:20]
