"""Every printed "any number of" / "up to N" pick out of a hand asks the seat
that picks, when a person sits there, before a card leaves the hand.

Ugin, the Spirit Dragon's −10 ("…then put up to seven permanent cards from
your hand onto the battlefield") lowered to a fused sweep that took the first
seven eligible cards and asked nobody, so a human could not keep a card back
(found by W1G13 beside Onslaught). It is now Tempting Wurm's pick and put:
``choose_cards_in_hand`` with an ``up_to`` ceiling, then
``put_chosen_hand_cards_onto_battlefield``.

The census is every such line in both manifest roles — "reveal any number of
<colour> cards in your hand" (Metalworker and the Urza's Destiny Seers and
Scents), "discard any number of / up to N cards", "exile / shuffle any number
of cards from your hand", Kamahl's Summons, Tempting Wurm, Ugin — driven
through its real entry point (activated, cast, or put onto the battlefield for
an entry trigger) with both seats interactive and holding a hand any filter
answers. A row passes when a prompt is owed to a seat; it fails when a card left
a hand with nobody asked. Rows that cannot be driven here (a counterspell
with no spell to counter) are counted, not passed.

Validated backwards: with the fused sweep restored it names Ugin alone.
"""

from __future__ import annotations

import dataclasses
import re

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card

_PICK = re.compile(
    r"\b(?:up to (?:one|two|three|four|five|six|seven|x|\d+)|any number of)\b"
    r"[^.]*\bcards?\b[^.]*\b(?:in|from) (?:your|their) hand"
    r"|\bdiscard (?:up to \w+|any number of) cards\b(?! at random)",
    re.I,
)
#: 23 printed lines when this was written, 20 of them drivable here.
_POPULATION_FLOOR = 20
_ASKED_FLOOR = 18


def _hand(pool) -> list:
    """A card of each colour, an artifact, an enchantment, a land and an
    instant — something for every filter in the population to answer."""
    coloured = [
        dataclasses.replace(
            _mk_creature_card(name, 1, 1),
            colors=(symbol,), mana_cost="{%s}" % symbol, cmc=1.0,
        )
        for symbol, name in (
            ("W", "White Card"), ("U", "Blue Card"), ("B", "Black Card"),
            ("R", "Red Card"), ("G", "Green Card"),
        )
    ]
    return [
        *coloured,
        _mk_card("Hand Artifact", "Artifact"),
        _mk_card("Hand Enchantment", "Enchantment"),
        pool["Plains"],
        pool["Lightning Bolt"],
    ]


def _drive(pool, card, line) -> str:
    program = compile_card_oracle(card)
    if not program.supported:
        return "unsupported"
    hand = _hand(pool)
    me = PlayerState(name="Me", hand=list(hand), library=[pool["Plains"]] * 10)
    them = PlayerState(name="Them", hand=list(hand), library=[pool["Plains"]] * 10)
    game = Game(players=[me, them])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    far = Permanent(card=_mk_creature_card("Far Bear", 2, 2))
    game._put_permanent_onto_battlefield(1, far, None)
    index = next(
        (i for i, ability in enumerate(program.activated_abilities)
         if ability.source_line
         and line.strip().startswith(ability.source_line.strip()[:40])),
        None,
    )
    before = [list(me.hand), list(them.hand)]
    if index is not None:
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
        source.metadata["summoning_sickness_turn"] = -99
        source.metadata["loyalty_counters"] = 20
        game._sync_control()
        game.pending_choices.clear()
        game.stack.clear()
        result = game.activate_permanent_ability(
            0, card.name, ability_index=index, target_player_index=1,
        )
        if not result.supported:
            result = game.activate_permanent_ability(
                0, card.name, ability_index=index,
                target_permanent_ids=[far.permanent_id],
            )
    elif "Instant" in card.type_line or "Sorcery" in card.type_line:
        me.hand = [card, *hand]
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        if not result.supported:
            me.hand = [card, *hand]
            result = game.cast_from_hand(
                0, card.name, target_permanent_ids=[far.permanent_id],
            )
    elif line.lower().startswith("when this creature enters"):
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
        result = None
    else:
        return "not driven"
    if result is not None and not result.supported:
        return "refused"
    for _ in range(3):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack()
    if any(choice.player_index in (0, 1) for choice in game.pending_choices):
        return "asked"
    moved = [
        held.name for seat, cards in enumerate(before) for held in cards
        if not any(held is still for still in game.players[seat].hand)
    ]
    return f"not asked, moved {moved}" if moved else "nothing moved"


def test_every_hand_pick_asks_the_seat_that_picks():
    pool: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        pool.setdefault(card.name, card)
    rows = [
        (name, _drive(pool, card, line))
        for name, card in sorted(pool.items())
        for line in (card.oracle_text or "").split("\n")
        if _PICK.search(line)
    ]
    assert len(rows) >= _POPULATION_FLOOR, rows
    asked = [name for name, verdict in rows if verdict == "asked"]
    assert len(asked) >= _ASKED_FLOOR, rows
    assert "Ugin, the Spirit Dragon" in asked
    silent = [(name, verdict) for name, verdict in rows if verdict.startswith("not asked")]
    assert silent == [], silent
