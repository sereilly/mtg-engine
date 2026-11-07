"""The noun a roles announcement's prompt asks for, over every role in the pool.

A roles announcement ("Kaboom! deals 4 damage to any number of target players
or planeswalkers", Legerdemain's two permanents) is walked one role at a time,
and each step's prompt reads "Choose the <noun> for <card> (n of m)", the noun
being the client's `roleTargetNoun` over the role the server sent. Two of its
branches named the wrong thing: a "player or planeswalker" role (Kaboom!'s
twelve, Lunge, Shower of Sparks) said "player" over a planeswalker that
glowed, and the positional names `target_descriptions._slot_roles_spec` gives
the slots of "two target permanents" whose narrowings differ said
"Choose the slot 0 for Legerdemain (1 of 2)".

The census runs the real function (lifted out of app.js) over every role of
every cast, activation and trigger spec the pool compiles, and holds each noun
to what a player could read: never a positional slot name, never an
underscore-joined spec kind, and "player or planeswalker" for the widened seat
role. On the base before this fix it reported 14 player-or-planeswalker roles
named "player" and Legerdemain's and Gauntlets of Chaos's slots by position.
"""

from __future__ import annotations

import json
import re

from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.targeting import (
    derive_activation_spec, derive_cast_spec, derive_instruction_spec,
)
from tests.helpers import run_app_js

_PRELUDE = 'const SEAT_ROLE_KINDS = ["player", "player_or_planeswalker"];'
_FUNCTIONS = [
    "roleTargetNoun", "roleReadsAGraveyard", "roleChoosesAPlayer", "roleChoosesASpell",
]


def _specs_of(card):
    """Every target spec *card* compiles to: its cast, each activated
    ability's and each triggered ability's."""
    program = compile_card_oracle(card)
    found = [derive_cast_spec(card, program)]
    found += [derive_activation_spec(ability) for ability in program.activated_abilities]
    found += [
        derive_instruction_spec(getattr(trigger, "instructions", None) or ())
        for trigger in program.triggered_abilities
    ]
    return [spec for spec in found if isinstance(spec, dict)]


def _pool_roles() -> dict[str, list[str]]:
    """Each distinct role (as the wire carries it, its filter aside) and the
    cards whose announcements walk it."""
    rows: dict[str, list[str]] = {}
    for card in compilation_units(load_catalog()):
        for spec in _specs_of(card):
            if spec.get("kind") != "roles":
                continue
            for role in spec.get("roles") or ():
                key = json.dumps(
                    {k: role.get(k) for k in sorted(role) if k != "filter"},
                    sort_keys=True, default=str,
                )
                rows.setdefault(key, []).append(card.name)
    return rows


def test_every_role_in_the_pool_is_asked_for_by_a_noun_a_player_can_read():
    rows = _pool_roles()
    roles = [json.loads(key) for key in rows]
    nouns = run_app_js(
        _FUNCTIONS, "return INPUT.map((role) => roleTargetNoun(role));", roles,
        prelude=_PRELUDE,
    )
    examined = sum(len(cards) for cards in rows.values())
    # A census that measured nothing looks like one that found nothing.
    assert len(roles) >= 50 and examined >= 100, (len(roles), examined)
    kinds = {role.get("kind") for role in roles}
    assert "player_or_planeswalker" in kinds
    assert any(re.fullmatch(r"slot_\d+", str(role.get("role") or "")) for role in roles)

    wrong = []
    for role, noun in zip(roles, nouns):
        cards = rows[json.dumps(role, sort_keys=True, default=str)]
        if role.get("kind") == "player_or_planeswalker" and noun != "player or planeswalker":
            wrong.append((role.get("kind"), role.get("role"), noun, cards[:3]))
        elif re.search(r"\bslot \d+\b", noun) or "_" in noun:
            wrong.append((role.get("kind"), role.get("role"), noun, cards[:3]))
    assert not wrong, wrong


def test_the_two_reported_nouns():
    """The census's two finds, by name: Kaboom!'s roles and Legerdemain's
    first slot."""
    cases = {}
    for card in compilation_units(load_catalog()):
        if card.name not in ("Kaboom!", "Legerdemain"):
            continue
        for spec in _specs_of(card):
            if spec.get("kind") == "roles":
                cases[card.name] = spec["roles"][0]
    assert set(cases) == {"Kaboom!", "Legerdemain"}, set(cases)
    nouns = run_app_js(
        _FUNCTIONS,
        "return Object.fromEntries(Object.entries(INPUT).map(([k, r]) => [k, roleTargetNoun(r)]));",
        cases, prelude=_PRELUDE,
    )
    assert nouns["Kaboom!"] == "player or planeswalker"
    assert nouns["Legerdemain"] != "slot 0"
    assert "slot" not in nouns["Legerdemain"]
