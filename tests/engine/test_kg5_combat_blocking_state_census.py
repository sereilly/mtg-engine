"""Pool census: every printed reading of the *state* "blocking" answers the
same for a blocker whose attackers have all left combat as for one still
blocking an attacker (CR 509.1g).

"It remains a blocking creature until it's removed from combat or the combat
phase ends." The attackers leaving is neither, but the combat record dropped
the blocker the moment its last attacker left (``_prune_combat_state`` and
``_renumber_combat_after_removal``), so a blocker whose Grizzly Bears had been
bolted stopped being "target blocking creature" (Dauthi Jackal, Righteousness,
Rabid Rats), "attacking or blocking creature" (the archers and ballistae),
"nonblocking" (Unlikely Alliance) and "blocking Wall you control" (Glyph of
Destruction) at the next prune.

The population is the pool's own: every compilation unit whose compiled
program carries a payload naming the state (``blocking_only``,
``not_blocking``, ``any_states`` with ``"blocking"``) and no relation to
another object (those — "blocking it", "it's blocking" — are about *whom* it
blocks, which does change when the attacker goes). On a board where two
Grizzly Bears are blocked by two Shivan Dragons and the first Bears is bolted,
the blocker whose attacker died and the one still blocking must get the same
answer from three readers:

* the filter reader (``subject_matches``), asked each payload's state words;
* the picker each targeting card goes through (``cast_target_spec`` for a
  spell, ``activation_target_spec`` per ability for a permanent), the card held
  by each seat in turn — a Dragon meets the narrowings the pool prints beside
  the state most often ("with flying", "Dragon");
* the condition reader, for "as long as it's blocking".

Each carries a floor on what it examined. Measured backwards on the tree
before the fix (``engine/`` reverted to 59f133e63, this file unchanged): all
48 units disagreed at the filter reader — 47 positive readings refused the
blocker whose attacker died, and Unlikely Alliance's "nonblocking" admitted
it; the picker offered it for none of the 34 units that offer the blocker
still blocking, and offered it to Unlikely Alliance; Snow Devil's condition
read it as not blocking.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, unit_label
from engine.handlers._filters import permanent_state_holds
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.subject_filters import subject_matches
from tests.helpers import _game, _nosick, declare_attack, settle

#: Payload keys that make a filter about the source's (or another object's)
#: combat *relation* rather than the creature's own state.
RELATIONAL = frozenset({
    "blocking_source", "blocked_by_source", "blocking_attached_host",
    "blocking_bound_target", "blocking_target", "also_blocking_target",
    "blocked_by_bound_object", "blocked_by_target_object", "blocked_by_role",
})


def _names_the_state(payload: dict) -> bool:
    if any(payload.get(key) for key in RELATIONAL):
        return False
    states = payload.get("any_states") or ()
    return bool(
        payload.get("blocking_only") or payload.get("not_blocking")
        or (isinstance(states, (list, tuple)) and "blocking" in states)
    )


def _payloads(obj, out: list) -> None:
    """Every dict reachable from a compiled program, depth first."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for field in dataclasses.fields(obj):
            _payloads(getattr(obj, field.name), out)
    elif isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            _payloads(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _payloads(value, out)


@pytest.fixture(scope="module")
def population():
    """``(unit label, payload)`` for every state payload, and the units whose
    conditions name the state ("as long as it's blocking")."""
    filters: list[tuple[str, dict]] = []
    conditions: list[str] = []
    units: dict[str, object] = {}
    for unit in compilation_units(load_catalog()):
        found: list[dict] = []
        _payloads(compile_card_oracle(unit), found)
        for payload in found:
            if _names_the_state(payload):
                filters.append((unit_label(unit), payload))
                units[unit_label(unit)] = unit
            if payload.get("state") == "blocking":
                conditions.append(unit_label(unit))
    return filters, conditions, units


def _board(by_name, *, hand_for=None, card=None):
    """Two Grizzly Bears attack; a Shivan Dragon blocks each, and the first
    Bears is bolted. With *card*, it is then put in seat *hand_for*'s hand (a
    spell) or onto that seat's battlefield (a permanent), after the combat it
    must not take part in. Returns the game, ``(orphan, live)`` and the
    placed permanent (or None)."""
    game = _game(
        PlayerState(name="A"),
        PlayerState(name="D", hand=[by_name["Lightning Bolt"]]),
    )
    attackers, blockers = [], []
    for seat, names, into in ((0, ["Grizzly Bears"] * 2, attackers),
                              (1, ["Shivan Dragon"] * 2, blockers)):
        for name in names:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            into.append(_nosick(permanent))
    game._sync_control()
    game._settle()
    declare_attack(game, 0, blocks={0: 0, 1: 1})
    settle(game)
    result = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[attackers[0].permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    game.get_combat_state()  # a prune, as every step and web payload makes
    orphan, live = blockers
    assert game.creatures_blocked_by(orphan) == []
    assert len(game.creatures_blocked_by(live)) == 1
    placed = None
    if card is not None:
        if _is_spell(card):
            game.players[hand_for].hand.append(card)
        else:
            placed = _nosick(Permanent(card=card))
            game._put_permanent_onto_battlefield(hand_for, placed, None)
            game._sync_control()
    return game, (orphan, live), placed


def _is_spell(card) -> bool:
    words = card.type_line.lower()
    return "instant" in words or "sorcery" in words


def _offered(game, spec: dict) -> set[int]:
    return {
        game.players[entry["seat"]].battlefield[entry["index"]].permanent_id
        for entry in spec.get("valid_targets") or ()
        if entry.get("kind") == "permanent"
    }


def test_every_printed_blocking_state_reads_a_blocker_whose_attacker_left(population, catalog_by_name):
    """The filter reader (``subject_matches``), asked the state words each
    payload prints and nothing else: the narrowings beside them are not what
    an attacker leaving changes."""
    filters, _, _ = population
    game, (orphan, live), _ = _board(catalog_by_name)
    units = {label for label, _ in filters}
    # A floor on the population: 48 units on 2026-11-10.
    assert len(units) >= 40, sorted(units)

    disagreements = []
    for label, payload in filters:
        state = {
            key: payload[key] for key in ("blocking_only", "not_blocking", "any_states")
            if key in payload
        }
        for observer in (0, 1):
            as_live = subject_matches(game, live, state, observer=observer)
            as_orphan = subject_matches(game, orphan, state, observer=observer)
            if as_live != as_orphan:
                disagreements.append(
                    f"{label} {state}: blocking an attacker {as_live}, "
                    f"its attacker gone {as_orphan}"
                )
    assert not disagreements, "\n".join(sorted(set(disagreements)))


def test_every_blocking_target_picker_offers_a_blocker_whose_attacker_left(population, catalog_by_name):
    """The picker each printed target goes through (``cast_target_spec`` for
    a spell, ``activation_target_spec`` per ability for a permanent), the card
    held by each seat in turn: it offers the blocker whose attacker died
    exactly when it offers the one still blocking."""
    _, _, by_label = population
    labels = sorted(by_label)

    disagreements, offering = [], set()
    for label in labels:
        unit = by_label[label]
        if not _is_spell(unit) and not compile_card_oracle(unit).activated_abilities:
            continue  # a trigger or a static: no picker of its own
        for seat in (0, 1):
            game, (orphan, live), placed = _board(catalog_by_name, hand_for=seat, card=unit)
            if placed is None:
                specs = [game.cast_target_spec(seat, unit)]
            else:
                index = game.battlefield_index_of(placed)
                count = len(game.usable_abilities_of(placed, card=placed.effective_card))
                specs = [game.activation_target_spec(seat, index, n) for n in range(count)]
            for spec in specs:
                offered = _offered(game, spec)
                if live.permanent_id in offered:
                    offering.add(label)
                if (live.permanent_id in offered) != (orphan.permanent_id in offered):
                    disagreements.append(f"{label} held by seat {seat}: {spec.get('kind')} {offered}")
    assert not disagreements, "\n".join(disagreements)
    # A floor on what was offered at all: 34 units of 45 on 2026-11-10 (the
    # rest are mass spells, or print a narrowing a Dragon does not meet).
    assert len(offering) >= 30, sorted(set(labels) - offering)


def test_every_blocking_condition_reads_a_blocker_whose_attacker_left(population, catalog_by_name):
    """"…as long as it's blocking" (Snow Devil) through the condition reader."""
    _, conditions, _ = population
    game, (orphan, live), _ = _board(catalog_by_name)
    assert conditions, "no condition names the blocking state"
    assert permanent_state_holds(live, "blocking")
    assert permanent_state_holds(orphan, "blocking"), conditions
