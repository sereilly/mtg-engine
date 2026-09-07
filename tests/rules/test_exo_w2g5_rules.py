"""A player who has left the game is not a legal target (EXO wave 2, W2G5).

`Game.opponents_of` has excluded a departed seat since free-for-all arrived
(CR 800.4a), and `legality._enumerate_targets`' own seat loop never asked it —
so the list the picker hands the browser, and the list the announcement gate
checks a named seat against, both went on offering a player who is no longer in
the game.

Silent at two seats, because a game with one player left is over. At three it is
an ordinary illegal announcement, and Oath of Ghouls *prefers* the departed
player: its clause is "whose graveyard has fewer creature cards in it than their
graveyard does", and a graveyard that has left the game is empty.

Its own file per SET_PLAYBOOK's block convention — a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent

_EXO_PATH = manifest_set_path("EXO", include_measured=True)


def _w2g5_body(name):
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear", "power": "1",
             "toughness": "1"},
    )


def _w2g5_exo(name):
    return next(card for card in load_cards(_EXO_PATH) if card.name == name)


def _w2g5_three_seats(oath_name, graveyards):
    """Seat 0 controls *oath_name*; seat 1 is about to lose; seat 2 is the
    upkeep player who will be asked to announce the target."""
    oath = Permanent(card=_w2g5_exo(oath_name))
    players = [
        PlayerState(
            name="P%d" % seat, life=0 if seat == 1 else 20,
            battlefield=[oath] if seat == 0 else [],
            graveyard=[_w2g5_body("D%d-%d" % (seat, i)) for i in range(count)],
            library=[_w2g5_body("L%d-%d" % (seat, i)) for i in range(5)],
        )
        for seat, count in enumerate(graveyards)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game._settle()
    game.check_state_based_actions()
    return game


@pytest.mark.cr("800.4a", "102.1", "601.2c")
def test_a_player_who_has_left_the_game_is_not_offered_as_a_target():
    """CR 800.4a puts the seat out of the game and CR 102.1 says a player is
    one of the people *in* it, so CR 601.2c has nobody there to choose.

    Oath of Ghouls announces at seat 2, whose graveyard holds three creature
    cards. Seat 0 holds one and qualifies; seat 1 has died with an empty
    graveyard and qualifies *harder* — which is why this is the card that shows
    it rather than a card where the departed seat merely happens to pass.
    """
    game = _w2g5_three_seats("Oath of Ghouls", (1, 0, 3))
    assert game.players[1].lost, "seat 1 must actually have left the game"

    game.start_turn(2)

    prompts = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    assert prompts[0].player_index == 2
    assert sorted(t["seat"] for t in prompts[0].data["targets"]) == [0], (
        "only the living opponent is a legal answer"
    )


@pytest.mark.cr("800.4a", "601.2c")
def test_the_living_opponents_are_still_offered():
    """The paired direction: nothing else was narrowed away. With every seat
    alive the same board offers both opponents, so the check above is about the
    departed seat and not about the clause.
    """
    game = _w2g5_three_seats("Oath of Ghouls", (1, 0, 3))
    game.players[1].lost = False
    game.players[1].life = 20

    game.start_turn(2)

    prompts = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert len(prompts) == 1
    assert sorted(t["seat"] for t in prompts[0].data["targets"]) == [0, 1]
