"""When a card hands a choice to "an opponent" and there are several, the
controller decides which opponent (CR 601.7a, 602.3a, 700.2e; CR 608.2d for a
choice made as the effect is applied) — so at a three-seat table a person in
the controller's seat is asked first.

Callous Oppressor ("As this creature enters, an opponent chooses a creature
type") took the next opponent in turn order and asked its controller nothing
(found by W1G4); Wormfang Crab ("When this creature enters, an opponent
chooses a permanent you control …") took the lowest-indexed opponent. Both now
ask: the Oppressor through ``enter_choice``'s opponent shape
(``then_opponent_chooses_creature_type``), the Crab through the
``choose_opponent`` step Animal Magnetism and Guided Passage already put in
front of their picks.

The census drives every printed "an opponent chooses / separates" and "… of an
opponent's choice" in both manifest roles at a three-seat table with every
seat interactive and reads who is asked first. The rows that still pick an
opponent without asking are the choices CR 601.7a / 602.3a / 700.2e put **in
the announcement** — a mode chosen by an opponent (Fatal Lore, Library of
Lat-Nam, Misfortune) and a target of an opponent's choice (Cuombajj Witches,
Echo Chamber, Nova Pentacle, Preacher) — which the engine models at resolution
or at the mode prompt with the first opponent. They are named here, so a new
card that picks an opponent silently fails rather than joining them.

Validated backwards: on the tree before the fix it names Callous Oppressor and
Wormfang Crab among the silent picks.
"""

from __future__ import annotations

import random
import re

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card

_CHOOSER = re.compile(
    r"\ban opponent (?:chooses|separates|may choose)\b|\bof an opponent's choice\b"
    r"|\bone of (?:your|their) opponents\b",
    re.I,
)

#: Announcement-time choices the engine still hands to the first opponent:
#: a mode (CR 700.2e) or a target (CR 601.7a / 602.3a) an opponent chooses.
#: Each needs the controller's pick of the opponent carried by the cast or
#: activation itself — measured and left, see the module docstring.
_ANNOUNCEMENT_TIME_PICKS = frozenset({
    "Cuombajj Witches", "Echo Chamber", "Fatal Lore", "Library of Lat-Nam",
    "Misfortune", "Nova Pentacle", "Preacher",
})
#: Printed rows when this was written (18), and those that ask the controller.
_POPULATION_FLOOR = 15
_ASKING_FLOOR = 6


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(pool) -> Game:
    hand = [pool["Plains"], _mk_creature_card("Hand Bear", 2, 2), pool["Lightning Bolt"]]
    players = [
        PlayerState(
            name=name, hand=list(hand), library=[pool["Plains"]] * 12,
            graveyard=[_mk_creature_card(f"{name} Dead", 2, 2)],
        )
        for name in ("Alice", "Bob", "Cara")
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game.active_player_index = 0
    for seat in range(3):
        _put(game, seat, _mk_creature_card(f"Seat{seat} Bear", 2, 2))
        _put(game, seat, pool["Plains"])
        _put(game, seat, _mk_card(f"Seat{seat} Charm", "Enchantment"))
    game._sync_control()
    game.pending_choices.clear()
    return game


def _first_asked(game) -> str | None:
    for choice in game.pending_choices:
        seats = choice.data.get("seats") or choice.data.get("opponents") or ()
        if choice.player_index == 0 and len(seats) > 1:
            return "controller"
        if choice.player_index in (1, 2):
            return "opponent"
        return "other"
    return None


def _drive(pool, card, line) -> str:
    program = compile_card_oracle(card)
    if not program.supported:
        return "unsupported"
    game = _table(pool)
    lowered = line.lower()
    index = next(
        (i for i, ability in enumerate(program.activated_abilities)
         if ability.source_line
         and line.strip().startswith(ability.source_line.strip()[:30])),
        None,
    )
    if index is not None:
        _put(game, 0, card)
        game._sync_control()
        game.pending_choices.clear()
        result = game.activate_permanent_ability(0, card.name, ability_index=index)
        if not result.supported:
            result = game.activate_permanent_ability(
                0, card.name, ability_index=index, target_player_index=1,
            )
        if not result.supported:
            return "refused"
    elif "Instant" in card.type_line or "Sorcery" in card.type_line:
        game.players[0].hand.insert(0, card)
        result = game.cast_from_hand(0, card.name)
        if not result.supported:
            return "refused"
    elif lowered.startswith(("as this", "when this")) and "enters" in lowered:
        _put(game, 0, card)
    else:
        return "not driven"
    for _ in range(4):
        asked = _first_asked(game)
        if asked or not game.stack:
            break
        game.resolve_top_of_stack()
    return _first_asked(game) or "nobody"


def test_an_opponent_s_choice_asks_the_controller_which_opponent():
    pool: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        pool.setdefault(card.name, card)
    # Goblin Festival's choice follows a lost coin flip; the census is a
    # measurement, so it is made under one seed and the RNG is put back.
    saved = random.getstate()
    random.seed(20041004)
    try:
        rows = [
            (name, _drive(pool, card, line))
            for name, card in sorted(pool.items())
            for line in (card.oracle_text or "").split("\n")
            if _CHOOSER.search(line)
        ]
    finally:
        random.setstate(saved)
    assert len(rows) >= _POPULATION_FLOOR, rows
    asking = {name for name, verdict in rows if verdict == "controller"}
    assert len(asking) >= _ASKING_FLOOR, rows
    assert {"Callous Oppressor", "Wormfang Crab"} <= asking
    silent = {name for name, verdict in rows if verdict == "opponent"}
    assert silent <= _ANNOUNCEMENT_TIME_PICKS, sorted(silent - _ANNOUNCEMENT_TIME_PICKS)
