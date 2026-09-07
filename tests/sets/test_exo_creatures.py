"""Exodus creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: the Keepers, and a seat picked out by a comparison ---
import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g1_card(name, type_line="Creature — Bear", colors=()):
    """A creature with no text at all, so a Keeper's own restriction is the
    only thing under test."""
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1",
             "toughness": "1", "colors": list(colors)},
    )


def _g1_board(set_pool, keeper, *, mine=(), theirs=(), my_life=20,
              their_life=20, my_hand=(), their_hand=(), my_gy=(), their_gy=()):
    """*keeper* on seat 0's battlefield, ready to activate, against a seat 1
    the caller has stocked to answer (or fail) its comparison."""
    subject = Permanent(card=set_pool("EXO")[keeper])
    subject.metadata["summoning_sickness_turn"] = -99
    seat0 = PlayerState(
        name="P0", life=my_life,
        battlefield=[subject] + [Permanent(card=c) for c in mine],
        hand=list(my_hand), graveyard=list(my_gy),
        library=[_g1_card("Mine %d" % i) for i in range(5)],
    )
    seat1 = PlayerState(
        name="P1", life=their_life,
        battlefield=[Permanent(card=c) for c in theirs],
        hand=list(their_hand), graveyard=list(their_gy),
        library=[_g1_card("Theirs %d" % i) for i in range(5)],
    )
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    game._settle()
    game.start_turn(0)
    return game, seat0, seat1, subject


def _g1_activate(game, keeper):
    return game.activate_permanent_ability(
        0, keeper, permanent_index=0, target_player_index=1,
    )


@pytest.mark.parametrize("keeper", [
    "Keeper of the Beasts", "Keeper of the Dead", "Keeper of the Flame",
    "Keeper of the Light", "Keeper of the Mind",
])
def test_every_keeper_is_supported(set_pool, keeper):
    program = compile_card_oracle(set_pool("EXO")[keeper])
    assert program.supported, program.reason


def test_keeper_of_the_light_gains_life_off_an_opponent_who_is_ahead(set_pool):
    """"{W}, {T}: Choose target opponent who has more life than you do as you
    activate this ability. You gain 3 life."
    """
    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Light", my_life=20, their_life=25,
    )

    result = _g1_activate(game, "Keeper of the Light")
    assert result.supported, result.details
    resolve_stack(game)

    assert seat0.life == 23


def test_keeper_of_the_light_is_refused_with_nothing_paid_when_nobody_is_ahead(
    set_pool,
):
    """CR 602.2b/601.2c: an ability with a mandatory target it cannot fill is
    refused **before any cost is paid**, not activated into a no-op. The
    creature staying untapped is the half that would be invisible otherwise —
    an unenforced narrowing costs its controller a tap and gains 3 life anyway.
    """
    game, seat0, _seat1, keeper = _g1_board(
        set_pool, "Keeper of the Light", my_life=20, their_life=15,
    )

    result = _g1_activate(game, "Keeper of the Light")

    assert not result.supported
    assert seat0.life == 20
    assert keeper.tapped is False


def test_keeper_of_the_beasts_reads_the_board_rather_than_a_life_total(set_pool):
    """The comparison is a *counted noun phrase*, so the same clause counts
    creatures here and a life total on Keeper of the Light."""
    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Beasts",
        theirs=(_g1_card("Theirs A"), _g1_card("Theirs B")),
    )

    result = _g1_activate(game, "Keeper of the Beasts")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in seat0.battlefield] == [
        "Keeper of the Beasts", "Beast Token",
    ]


def test_keeper_of_the_beasts_is_refused_on_an_equal_board(set_pool):
    game, seat0, _seat1, _keeper = _g1_board(set_pool, "Keeper of the Beasts")

    result = _g1_activate(game, "Keeper of the Beasts")

    assert not result.supported
    assert len(seat0.battlefield) == 1


def test_keeper_of_the_mind_needs_the_printed_margin_of_two(set_pool):
    """"…who has **at least two** more cards in hand than you do". The
    threshold is data, so one card ahead is not enough and two is.
    """
    one_ahead = _g1_board(
        set_pool, "Keeper of the Mind",
        my_hand=[_g1_card("Mine")],
        their_hand=[_g1_card("A"), _g1_card("B")],
    )
    game, seat0, _seat1, _keeper = one_ahead
    assert not _g1_activate(game, "Keeper of the Mind").supported
    assert len(seat0.hand) == 1

    game, seat0, _seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Mind",
        my_hand=[_g1_card("Mine")],
        their_hand=[_g1_card("A"), _g1_card("B"), _g1_card("C")],
    )
    result = _g1_activate(game, "Keeper of the Mind")
    assert result.supported, result.details
    resolve_stack(game)
    assert len(seat0.hand) == 2


def test_keeper_of_the_flame_burns_the_player_the_activation_chose(set_pool):
    """"…This creature deals 2 damage to **that player**." The seat named by
    the sentence in front of it, which is the one the activation announced."""
    game, seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Flame", my_life=20, their_life=25,
    )

    result = _g1_activate(game, "Keeper of the Flame")
    assert result.supported, result.details
    resolve_stack(game)

    assert seat1.life == 23
    assert seat0.life == 20


def test_keeper_of_the_dead_destroys_out_of_the_chosen_players_board(set_pool):
    """"Destroy target nonblack creature **that player** controls."

    The seat is the one the *activation* chose, which no trigger context holds
    — so the destroy reads the record the choosing step wrote. Without it the
    sentence found no seat and destroyed nothing while the ability reported
    itself resolved.
    """
    game, seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Dead",
        mine=(_g1_card("My Own Bear"),),
        theirs=(_g1_card("Blacky", colors=["B"]), _g1_card("Whitey", colors=["W"])),
        my_gy=[_g1_card("Dead %d" % i) for i in range(3)],
    )

    result = _g1_activate(game, "Keeper of the Dead")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in seat1.battlefield] == ["Blacky"], (
        "the black creature is excluded and the white one is destroyed"
    )
    assert "My Own Bear" in [p.card.name for p in seat0.battlefield], (
        "'that player controls' is the chosen opponent's board, not the "
        "activator's"
    )


def test_keeper_of_the_dead_wants_two_fewer_and_not_merely_fewer(set_pool):
    game, _seat0, seat1, _keeper = _g1_board(
        set_pool, "Keeper of the Dead",
        theirs=(_g1_card("Victim"),),
        my_gy=[_g1_card("Dead %d" % i) for i in range(3)],
        their_gy=[_g1_card("Theirs A"), _g1_card("Theirs B")],
    )

    result = _g1_activate(game, "Keeper of the Dead")

    assert not result.supported
    assert [p.card.name for p in seat1.battlefield] == ["Victim"]


def test_a_comparison_the_evaluator_cannot_count_refuses_the_line():
    """The clause carries a whole noun phrase, and the gate that admits the
    card is the same reader that counts it. A phrase no count can take has to
    refuse the sentence rather than be admitted with the comparison dropped —
    an unenforced seat narrowing is an ability that hits everybody.
    """
    line = compile_line(
        "choose target opponent who controls more creatures blocking it than "
        "you do as you activate this ability. you gain 3 life"
    )
    assert not line.instructions
    assert line.parse_error or line.lowering_error


def test_a_bare_choose_target_opponent_still_needs_its_binder():
    """The comparison is what makes a narrowed choice non-vacuous; without one
    the module's original rule stands, and a sentence that chooses a player and
    never mentions them again is refused."""
    line = compile_line("choose target opponent. you gain 3 life")
    assert not line.instructions
