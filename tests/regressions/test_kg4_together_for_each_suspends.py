"""A ``for_each`` whose repetitions each stop to ask still puts what it puts
onto the battlefield in one event (CR 603.6a).

Glyph of Reincarnation: "Destroy all creatures that were blocked by target
Wall this turn. They can't be regenerated. For each creature that died this
way, put a creature card from the graveyard of the player who controlled that
creature the last time it became blocked by that Wall onto the battlefield
under its owner's control." Its ruling (2004-10-04): "First place all the
affected creatures in the graveyard, then choose the appropriate number of
creatures from the attacker's graveyard and put them onto the battlefield."

Each repetition is a pick out of a graveyard (``search_library`` over the
graveyard zone), armed for every seat and answered after the call that armed
it has returned. The loop's ``with entering_together():`` block closed at
the first repetition's suspension, so each card entered at its own answer: a
Soul Warden the second pick returned never saw the first pick's creature
arrive. The loop now opens its event with ``entering_together_through``, and
each answer re-joins it. Driven with the Warden picked first and picked last,
at a table nobody asks and with the caster a person, both picks answered by
the caster.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent

_CARDS = {card.name: card for card in load_catalog()}

WARDEN = "Soul Warden"


def _creature(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


def _board(interactive: bool) -> Game:
    """P1 attacks with two creatures into P2's Wall of Glare ("can block any
    number of creatures"), which blocks both; P2 holds the Glyph, and P1's
    graveyard holds a Soul Warden and a Grizzly Bears."""
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=_creature("Attacker One")),
                     Permanent(card=_creature("Attacker Two"))],
        graveyard=[_CARDS[WARDEN], _CARDS["Grizzly Bears"]],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=_CARDS["Wall of Glare"])],
        hand=[_CARDS["Glyph of Reincarnation"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()   # declare_blockers
    assert game.declare_blockers(1, {0: [0, 1]})[0]
    game.advance_combat_phase()   # combat damage
    game.end_combat(step_already_started=True)
    game._settle()
    assert len(game.players[0].battlefield) == 2, game.log[-8:]
    game.interactive_seats = {1} if interactive else set()
    return game


def _pick(game: Game, name: str) -> None:
    owed = [c for c in game.pending_choices if c.kind == "search_library"]
    assert owed, ([c.kind for c in game.pending_choices], game.log[-6:])
    assert owed[0].player_index == 1
    graveyard = game.players[0].graveyard
    index = next(i for i, card in enumerate(graveyard) if card.name == name)
    assert game.confirm_search_library(1, index, zone="graveyard")


@pytest.mark.parametrize("interactive", [False, True], ids=["nobody_asked", "a_person"])
@pytest.mark.parametrize("warden_first", [True, False], ids=["warden_first", "warden_last"])
def test_glyph_of_reincarnations_picks_enter_together(warden_first, interactive):
    game = _board(interactive)
    game.current_turn_phase = "postcombat_main"
    life = game.players[0].life
    assert game.cast_from_hand(
        1, "Glyph of Reincarnation",
        target_player_index=1, target_permanent_index=0,
    ).supported
    game._settle()
    order = [WARDEN, "Grizzly Bears"] if warden_first else ["Grizzly Bears", WARDEN]
    for name in order:
        _pick(game, name)
        game._settle()
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == sorted([WARDEN, "Grizzly Bears"]), (names, game.log[-12:])
    gained = game.players[0].life - life
    assert gained == 1, (
        f"the Soul Warden returned {'first' if warden_first else 'last'} "
        f"gained {gained}; returned beside the Bears it is 1\n"
        + "\n".join(game.log[-15:])
    )
    assert not getattr(game, "open_entry_events", [])
