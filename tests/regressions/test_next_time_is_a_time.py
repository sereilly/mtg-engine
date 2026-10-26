"""A "the next time damage would be dealt to <recipient>" redirect covers
**every chunk dealt at that time**, not the first chunk.

Mirrorwood Treefolk's own rulings (2004-10-04, Scryfall): "The ability applies
to the next time damage is dealt. Normally this means damage from one source at
one time, but during combat it is possible for multiple sources to damage the
Treefolk at one time, in which case damage from all of those sources is
redirected." Glarecaster's ruling of the same date says the same of its two
recipients, and W1G9 built the occasion for it (``damage_redirects.SharedNextTime``:
spent at the first chunk's moment, open for every other chunk of that dealing,
closed by the combat damage step's tail). The Treefolk's record still carried
``uses=1``, so blocked by two creatures it moved the first blocker's damage and
took the second's.

The census reads every damage "next time" sentence in both manifest roles and
sorts it by what it is keyed on, from the printed words alone:

* **recipient-keyed, any source** — "the next time damage would be dealt to
  this creature …": several sources can deal damage to it at once (CR 510.2),
  which is the shape the rulings speak to. Each is driven: the creature
  attacks, two blockers deal their damage in one combat damage step, and both
  chunks must reach the chosen target.
* **source-keyed** — "the next time <a source> would deal damage …": CR 615.8's
  "next instance of damage from that source". One source dealing damage to one
  recipient deals it once per dealing, so the question does not arise; the
  rows that may reach several recipients from one source (Penance's "deal
  damage this turn", Shadowbane's "you and/or creatures you control") are
  counted and left — no ruling on any of them says whether a sweep's several
  chunks are one instance.

Validated backwards: with ``uses=1`` restored in
``handlers/redirection.redirect_next_damage_from_source_until_eot`` the
Treefolk row fails (the second blocker's 2 damage is marked on it).
"""

from __future__ import annotations

import dataclasses
import re

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, resolve_stack

_NEXT_TIME = re.compile(
    r"\bthe next time\b[^.]*\bwould (?:deal|be dealt)\b|\bthe next time damage would\b",
    re.I,
)
_RECIPIENT_KEYED = re.compile(r"\bthe next time damage would be dealt to\b", re.I)

#: Damage "next time" lines in both roles when this was written (59), and the
#: recipient-keyed ones among them (2: Mirrorwood Treefolk, Glarecaster).
_LINE_FLOOR = 50
_RECIPIENT_FLOOR = 2


def _population():
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    rows = []
    for name, card in sorted(cards.items()):
        for line in (card.oracle_text or "").split("\n"):
            # Reminder text is the keyword's, not the card's ("Regenerate" says
            # "the next time this creature would be destroyed").
            printed = re.sub(r"\([^)]*\)", "", line)
            if _NEXT_TIME.search(printed):
                rows.append((name, card, printed.strip()))
    return rows


def _blocker(name):
    """A 2/2 that can block anything the census attacks with (Glarecaster
    flies, CR 702.9b)."""
    return dataclasses.replace(
        _mk_creature_card(name, 2, 2, "Flying"), keywords=("Flying",),
    )


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _two_blockers_onto(card, line):
    """*card* (seat 0) arms the ability printed on *line* at seat 1, attacks,
    and is blocked by two 2/2s. Returns (the creature, seat 1's life), or None
    when the line is not an activated ability of a creature."""
    program = compile_card_oracle(card)
    index = next(
        (i for i, ability in enumerate(program.activated_abilities)
         if ability.source_line and ability.source_line.strip() in line),
        None,
    )
    if index is None or "Creature" not in card.type_line:
        return None
    game = Game(players=[PlayerState(name="Holder"), PlayerState(name="Blocker")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    protected = _put(game, 0, card)
    first = _put(game, 1, _blocker("First Blocker"))
    second = _put(game, 1, _blocker("Second Blocker"))
    game._sync_control()
    game._set_phase_and_step("precombat_main", "precombat_main")
    armed = game.activate_permanent_ability(
        0, card.name, ability_index=index, target_player_index=1,
    )
    assert armed.supported, armed.details
    resolve_stack(game)
    game._set_phase_and_step("combat", "declare_attackers")
    declared = game.declare_attackers(
        0, [game.battlefield_index_of(protected)], defending_player_index=1,
    )
    assert declared[0], declared
    game._set_phase_and_step("combat", "declare_blockers")
    blocked = game.declare_blockers(1, {
        game.battlefield_index_of(first): [game.battlefield_index_of(protected)],
        game.battlefield_index_of(second): [game.battlefield_index_of(protected)],
    })
    assert blocked[0], blocked
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    resolve_stack(game)
    return protected, game.players[1].life


def test_a_recipient_keyed_next_time_moves_every_chunk_of_one_dealing():
    rows = _population()
    assert len(rows) >= _LINE_FLOOR, len(rows)
    recipient_keyed = [row for row in rows if _RECIPIENT_KEYED.search(row[2])]
    assert len(recipient_keyed) >= _RECIPIENT_FLOOR, recipient_keyed
    driven = 0
    wrong = []
    for name, card, line in recipient_keyed:
        outcome = _two_blockers_onto(card, line)
        if outcome is None:
            continue
        driven += 1
        protected, life = outcome
        if protected.damage_marked or life != 16:
            wrong.append((name, protected.damage_marked, life))
    assert driven >= _RECIPIENT_FLOOR, driven
    assert wrong == [], (
        "a 'next time' that moved only part of one dealing "
        "(name, damage left on the creature, the target's life): "
        f"{wrong}"
    )


def test_mirrorwood_treefolk_moves_both_blockers_then_the_time_is_over(set_pool):
    """Blocked by two 2/2s, all four points reach the player it named; the
    redirect is then spent — a Shock at the Treefolk after combat lands."""
    treefolk = set_pool("PLS")["Mirrorwood Treefolk"]
    game = Game(players=[PlayerState(name="Holder"), PlayerState(name="Blocker")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    protected = _put(game, 0, treefolk)
    first = _put(game, 1, _blocker("First Blocker"))
    second = _put(game, 1, _blocker("Second Blocker"))
    game.players[1].hand.append(set_pool("ONS")["Shock"])
    game._sync_control()
    game._set_phase_and_step("precombat_main", "precombat_main")
    assert game.activate_permanent_ability(
        0, "Mirrorwood Treefolk", target_player_index=1,
    ).supported
    resolve_stack(game)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(protected)], defending_player_index=1,
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {
        game.battlefield_index_of(first): [game.battlefield_index_of(protected)],
        game.battlefield_index_of(second): [game.battlefield_index_of(protected)],
    })[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    resolve_stack(game)
    assert protected.damage_marked == 0
    assert game.players[1].life == 16
    assert sum(
        "is dealt to Blocker instead (Mirrorwood Treefolk)" in line
        for line in game.log
    ) == 2

    game._set_phase_and_step("postcombat_main", "postcombat_main")
    game.active_player_index = 1
    game.cast_from_hand(1, "Shock", target_permanent_ids=[protected.permanent_id])
    resolve_stack(game)
    assert protected.damage_marked == 2, "the next time was that combat's"
    assert game.players[1].life == 16
