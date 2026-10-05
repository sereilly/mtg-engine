"""A printed bound on "choose a card name" is a rule, not a label.

"Choose a **creature** card name" (Wood Sage) bounds CR 202.1's freedom to
name any card. The bound reached the prompt as a word for the player to read
and was enforced by nothing: the seat could name Mountain, and the sentence
behind the choice — "reveal the top four cards of your library and put all of
them with that name into your hand" — would hand over every Mountain it turned
up. Wrong in the player's favour, on a card that reported supported, and
invisible to every census because nothing about the compiled program is wrong.

Found at Invasion's first wave while giving Desperate Research ("…other than a
basic land card name") the same prompt, and fixed in the one place both bounds
are answered: ``PendingChoicesMixin._named_card_breaks_printed_bound``.

The engine holds no card catalog, so a card *type* cannot be asked of a bare
name. It is asked of every card in the game bearing that name — which is exact
for everything a name can do: a name borne by no card here matches nothing,
whatever type it would have had.
"""

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_card


def _sage_game(set_pool, library):
    sage = Permanent(card=set_pool("TMP")["Wood Sage"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sage], library=list(library)),
        PlayerState(name="P2"),
    ])
    game._sync_control()
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    sage.metadata["summoning_sickness_turn"] = -99
    game.activate_permanent_ability(0, "Wood Sage", ability_index=0)
    game.resolve_top_of_stack()
    return game


def _bear():
    card = _mk_card("Grizzly Bears", "{1}{G}", "Creature — Bear", "")
    card.raw.update({"power": "2", "toughness": "2"})
    return card


def test_wood_sage_cannot_name_a_card_that_is_not_a_creature_card(set_pool):
    mountain = _mk_card("Mountain", "Basic Land — Mountain")
    game = _sage_game(set_pool, [mountain, _bear(), mountain, mountain, _bear()])
    prompt = game.pending_choice_of("choose_card_name", 0)
    assert prompt is not None and prompt.data.get("card_type") == "creature"

    assert not game.confirm_choose_card_name(0, "Mountain"), (
        "a land's name is not a creature card name"
    )
    assert game.pending_choice_of("choose_card_name", 0) is not None, (
        "a refused answer leaves the prompt owed"
    )
    assert game.players[0].hand == []

    assert game.confirm_choose_card_name(0, "Grizzly Bears")
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Mountain"] * 3


def test_wood_sage_may_still_name_a_card_nobody_in_the_game_has(set_pool):
    """CR 202.1 lets a player name any card. A name no card in this game bears
    cannot be checked against a type — and cannot matter either: it matches
    nothing, so the whole revealed pile is binned."""
    mountain = _mk_card("Mountain", "Basic Land — Mountain")
    game = _sage_game(set_pool, [mountain] * 4)
    assert game.confirm_choose_card_name(0, "Craw Wurm")
    assert game.players[0].hand == []
    assert len(game.players[0].graveyard) == 4
