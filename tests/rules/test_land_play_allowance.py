"""CR 305.2 — "You may play [any number of / N additional] lands on each of your turns".

CR 305.2 says a player normally plays one land per turn "however, continuous
effects may increase this number", and 305.2a makes the comparison a *count*:
lands the player can play this turn versus lands already played. Fastbond's
unlimited form and the "an additional land" / "two additional lands" forms are
the same template with that count as its parameter, derived in
``engine/land_play_allowance.py``.

What stood here was ``Game._fastbond_count``, which counted battlefield
permanents **named "Fastbond"**, read from four places (cast validation, the
land-drop damage, the AI's land policy, the web layer's playable list). Measured
before the table: an invented card with Fastbond's exact text compiled
**supported**, granted no extra land play and dealt no damage — the
supported-but-wrong failure, because the parse-coverage gate claimed the
*sentence* while the code behind the claim fired for one *name*.

Every property is therefore pinned with an invented card, and the numbers differ
from Fastbond's wherever a number is a parameter.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.land_play_allowance import land_play_allowance_for
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _card(name: str, type_line: str, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{G}", cmc=1.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


def _forest(label: str) -> CardDefinition:
    return _card(label, "Basic Land — Forest", "({T}: Add {G}.)")


def _game(battlefield, hand) -> tuple[Game, PlayerState]:
    player = PlayerState(
        name="P1", battlefield=list(battlefield), hand=list(hand), life=20,
    )
    game = Game(players=[player, PlayerState(name="P2", life=20)])
    # CR 305.2's count is only enforced when the engine is enforcing costs; that
    # is the mode every real session runs in.
    game.enforce_mana_costs = True
    return game, player


def _play_lands(game: Game, player: PlayerState, count: int) -> list[bool]:
    return [game.cast_from_hand(0, f"Forest {i + 1}").supported for i in range(count)]


# Invented allowances. "Verdant Rush" carries Fastbond's exact wording under a
# name the engine has never seen; the other two use the bounded forms with
# numbers Fastbond does not print.
VERDANT_RUSH = _card(
    "Verdant Rush", "Enchantment",
    "You may play any number of lands on each of your turns.\n"
    "Whenever you play a land, if it wasn't the first land you played this turn, "
    "this enchantment deals 1 damage to you.",
)
PATHFINDER_LORE = _card(
    "Pathfinder Lore", "Enchantment",
    "You may play an additional land on each of your turns.",
)
SETTLERS_CHARTER = _card(
    "Settlers' Charter", "Enchantment",
    "You may play two additional lands on each of your turns.",
)


# ---------------------------------------------------------------------------
# The permission is derived from the printed line, not from a name
# ---------------------------------------------------------------------------

@pytest.mark.cr("305.2", "305.2a")
def test_allowance_is_keyed_on_the_printed_line_not_the_card_name():
    """An invented card with Fastbond's exact text grants the extra land plays.

    Against the name-keyed count this replaced, the second land was refused
    while the card still reported `supported`.
    """
    game, player = _game(
        [Permanent(card=VERDANT_RUSH)],
        [_forest("Forest 1"), _forest("Forest 2"), _forest("Forest 3")],
    )
    assert _play_lands(game, player, 3) == [True, True, True]
    assert sum(1 for p in player.battlefield if p.card.primary_type == "land") == 3


@pytest.mark.cr("305.2", "305.2b")
def test_the_bounded_form_grants_exactly_what_it_prints():
    """"an additional land" is one more, not unlimited — CR 305.2b refuses the
    play once the count is reached. Reading this form as Fastbond's would be the
    same defect in the other direction."""
    game, player = _game(
        [Permanent(card=PATHFINDER_LORE)],
        [_forest("Forest 1"), _forest("Forest 2"), _forest("Forest 3")],
    )
    assert _play_lands(game, player, 3) == [True, True, False]


@pytest.mark.cr("305.2a")
def test_the_number_in_the_bounded_form_is_data():
    """"two additional lands" is CR 305.2's one plus two — three, and the fourth
    is refused."""
    game, player = _game(
        [Permanent(card=SETTLERS_CHARTER)],
        [_forest(f"Forest {i + 1}") for i in range(5)],
    )
    assert _play_lands(game, player, 5) == [True, True, True, False, False]


@pytest.mark.cr("305.2a")
def test_two_allowances_add_up():
    """CR 305.2a compares one number against another, so two sources of extra
    land plays are one larger number — nothing about the count is per-card.
    One plus one plus two is four."""
    game, player = _game(
        [Permanent(card=PATHFINDER_LORE), Permanent(card=SETTLERS_CHARTER)],
        [_forest(f"Forest {i + 1}") for i in range(5)],
    )
    assert _play_lands(game, player, 5) == [True, True, True, True, False]


@pytest.mark.cr("305.2")
def test_with_no_allowance_the_second_land_is_refused():
    game, player = _game([], [_forest("Forest 1"), _forest("Forest 2")])
    assert _play_lands(game, player, 2) == [True, False]


# ---------------------------------------------------------------------------
# The rider that rides with it
# ---------------------------------------------------------------------------

@pytest.mark.cr("305.2", "120.3a")
def test_the_self_damage_rider_fires_for_an_invented_card():
    game, player = _game(
        [Permanent(card=VERDANT_RUSH)],
        [_forest("Forest 1"), _forest("Forest 2"), _forest("Forest 3")],
    )
    _play_lands(game, player, 3)
    # First land is free; the second and third each cost 1 life.
    assert player.life == 18


@pytest.mark.cr("120.3a")
def test_the_rider_amount_is_data_not_a_constant():
    """The dispatch dealt ``fastbond_count`` damage — one per *permanent named
    Fastbond* — so the printed number was never read at all."""
    steep_price = _card(
        "Steep Price", "Enchantment",
        "You may play any number of lands on each of your turns.\n"
        "Whenever you play a land, if it wasn't the first land you played this turn, "
        "this enchantment deals 3 damage to you.",
    )
    game, player = _game(
        [Permanent(card=steep_price)],
        [_forest("Forest 1"), _forest("Forest 2")],
    )
    _play_lands(game, player, 2)
    assert player.life == 17


@pytest.mark.cr("305.2")
def test_an_allowance_without_a_rider_costs_no_life():
    game, player = _game(
        [Permanent(card=PATHFINDER_LORE)],
        [_forest("Forest 1"), _forest("Forest 2")],
    )
    _play_lands(game, player, 2)
    assert player.life == 20


# ---------------------------------------------------------------------------
# The gate reads the same table as the dispatch
# ---------------------------------------------------------------------------

@pytest.mark.cr("305.2")
def test_the_support_gate_claims_the_card_through_this_table():
    """``oracle._derived_static_claims`` asks ``land_play_allowance_for``, so the
    thing that says "supported" and the thing that grants the land play are one
    table. When they were two, the sentence was claimed pool-wide and the
    behaviour was granted to one name."""
    program = compile_card_oracle(PATHFINDER_LORE)
    assert program.supported is True
    claims = {i.value for i in program.instructions if i.kind == "derived_static_rule"}
    assert "land_play_allowance" in claims


@pytest.mark.cr("305.2")
def test_a_wording_the_table_cannot_read_is_not_claimed():
    """"...on each of your opponents' turns" is not this template. Nothing may
    report it as understood, because nothing implements it."""
    assert land_play_allowance_for(
        "You may play an additional land on each of your opponents' turns."
    ) is None


@pytest.mark.cr("305.2")
def test_the_rider_alone_grants_no_land_play():
    """The permission clause is what makes an allowance. A card printing only the
    damage trigger must not be read as granting a land."""
    assert land_play_allowance_for(
        "Whenever you play a land, if it wasn't the first land you played this turn, "
        "this enchantment deals 1 damage to you."
    ) is None


# ---------------------------------------------------------------------------
# The printed card, for the CR anchor
# ---------------------------------------------------------------------------

@pytest.mark.cr("305.2", "305.2a")
def test_fastbond(cards):
    game, player = _game(
        [Permanent(card=cards["Fastbond"])],
        [_forest("Forest 1"), _forest("Forest 2"), _forest("Forest 3")],
    )
    assert _play_lands(game, player, 3) == [True, True, True]
    assert player.life == 18


# ---------------------------------------------------------------------------
# The same count with a duration instead of a source (CR 305.1/305.2)
# ---------------------------------------------------------------------------
#
# Everything above is a permanent's static ability, recomputed from the board.
# Summer Bloom and Solfatara say the same two things "this turn", with no
# permanent left behind to say them — so they are recorded on the game and
# cleared at the turn boundary, and read by the *same* gate. A second gate would
# be a second answer to "may this seat play a land?", which is the split this
# whole module exists to prevent.


def _turn_effect_game() -> Game:
    game = Game(players=[
        PlayerState(name="P1", life=20), PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    return game


@pytest.mark.cr("305.2", "305.2a")
def test_a_this_turn_grant_and_a_permanent_s_allowance_add_up(set_pool):
    """CR 305.2a compares one number against one number, so both sources of
    "lands the player can play this turn" feed the same total."""
    from engine.land_play_allowance import grant_extra_land_plays

    game, player = _game([Permanent(card=PATHFINDER_LORE)], [])
    grant_extra_land_plays(game, 0, 3)

    # One by rule, one from the enchantment, three from the resolved effect.
    for played in range(5):
        game.lands_played_this_turn[0] = played
        assert game._may_play_another_land(0), f"land {played + 1} of 5"
    game.lands_played_this_turn[0] = 5
    assert not game._may_play_another_land(0)
    assert player is game.players[0]


@pytest.mark.cr("305.1", "305.2b")
def test_a_this_turn_prohibition_outranks_every_allowance():
    """CR 305.1's permission withdrawn, which no count adds up to: "a player
    can't play a land, for any reason, if…".

    The same asymmetry the board-wide prohibition (Worms of the Earth) already
    has, and it is asked in the same place and before the count.
    """
    from engine.land_play_allowance import (
        forbid_land_plays_this_turn, grant_extra_land_plays,
    )

    game, _player = _game([Permanent(card=VERDANT_RUSH)], [])
    grant_extra_land_plays(game, 0, 3)
    assert game._may_play_another_land(0)

    forbid_land_plays_this_turn(game, 0)

    assert not game._may_play_another_land(0)
    assert game._may_play_another_land(1), "one seat, not the table"


@pytest.mark.cr("305.2")
def test_both_this_turn_records_are_cleared_at_the_turn_boundary():
    """"…this turn". A prohibition that outlived its turn is a seat that quietly
    stops playing lands, and a grant that did is a free land drop every turn
    after."""
    from engine.land_play_allowance import (
        forbid_land_plays_this_turn, grant_extra_land_plays,
    )

    game = _turn_effect_game()
    grant_extra_land_plays(game, 0, 3)
    forbid_land_plays_this_turn(game, 1)

    game.start_turn(0)

    assert game.extra_land_plays_this_turn == {}
    assert game.land_plays_forbidden_this_turn == set()
    game.lands_played_this_turn[0] = 1
    assert not game._may_play_another_land(0)
    assert game._may_play_another_land(1)
