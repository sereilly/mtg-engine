"""Prophecy creatures.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: spell costs ---
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

#: The five Avatars, each with the colour of its two printed pips, a board on
#: which its fronted condition holds, and the nearest board on which it does
#: not. The near misses are the point: six lands, 4 life, a lead of three, one
#: card in hand, nine creature cards — every one is the threshold minus one, so
#: a reading that is off by one passes the "met" half and fails here.
_W1G2_AVATARS = (
    ("Avatar of Fury", "R",
     {"theirs": ("Mountain",) * 7}, {"theirs": ("Mountain",) * 6}),
    ("Avatar of Hope", "W", {"life": 3}, {"life": 4}),
    ("Avatar of Might", "G",
     {"theirs": ("Grizzly Bears",) * 4},
     {"theirs": ("Grizzly Bears",) * 4, "mine": ("Grizzly Bears",)}),
    ("Avatar of Will", "U", {}, {"their_hand": ("Island",)}),
    ("Avatar of Woe", "B",
     {"my_grave": ("Grizzly Bears",) * 5, "their_grave": ("Grizzly Bears",) * 5},
     {"my_grave": ("Grizzly Bears",) * 5,
      "their_grave": ("Grizzly Bears",) * 4 + ("Island",)}),
)


def _w1g2_avatar_game(set_pool, avatar, *, life=20, mine=(), theirs=(),
                      their_hand=(), my_grave=(), their_grave=(), seats=2):
    """A duel (or a free-for-all of *seats*) with *avatar* in P1's hand, mana
    enforced and P1's pool empty — so a cast succeeds only if the reduction
    took off all six generic."""
    lea = set_pool("LEA")
    players = [
        _W1G2PlayerState(name="P1", life=life, hand=[set_pool("PCY")[avatar]]),
        _W1G2PlayerState(name="P2", hand=[lea[n] for n in their_hand]),
    ] + [_W1G2PlayerState(name=f"P{n}") for n in range(3, seats + 1)]
    players[0].graveyard.extend(lea[n] for n in my_grave)
    players[1].graveyard.extend(lea[n] for n in their_grave)
    game = _W1G2Game(players=players)
    for name in mine:
        game._put_permanent_onto_battlefield(0, _W1G2Permanent(card=lea[name]), None)
    for name in theirs:
        game._put_permanent_onto_battlefield(1, _W1G2Permanent(card=lea[name]), None)
    game.start_turn(0)
    game.enforce_mana_costs = True
    return game


@_w1g2_pytest.mark.parametrize(
    "avatar,color,met,unmet", _W1G2_AVATARS, ids=[a[0] for a in _W1G2_AVATARS]
)
def test_w1g2_avatar_costs_six_less_exactly_when_its_condition_holds(
    set_pool, avatar, color, met, unmet,
):
    """"If <condition>, this spell costs {6} less to cast." (CR 601.2f.)

    Driven through the real cast with two pips of the Avatar's colour in the
    pool and nothing else: met, the spell resolves and the pool is spent;
    unmet, the cast is refused for want of mana and nothing moves — the card is
    still in hand and the two pips are still in the pool. The condition is the
    grammar's own reading of the fronted clause, answered by the evaluator every
    intervening-if uses, so a wording the grammar cannot read refuses the line
    and the card stays unsupported rather than reading as unconditional.
    """
    program = _w1g2_compile(set_pool("PCY")[avatar])
    assert program.supported, program.reason

    game = _w1g2_avatar_game(set_pool, avatar, **met)
    game.players[0].mana_pool[color] = 2
    result = game.cast_from_hand(0, avatar)
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert any(p.card.name == avatar for p in game.players[0].battlefield), game.log
    assert game.players[0].mana_pool[color] == 0

    game = _w1g2_avatar_game(set_pool, avatar, **unmet)
    game.players[0].mana_pool[color] = 2
    result = game.cast_from_hand(0, avatar)
    assert not result.supported
    assert "insufficient mana" in result.details, result.details
    assert [c.name for c in game.players[0].hand] == [avatar]
    assert game.players[0].mana_pool[color] == 2


@_w1g2_pytest.mark.parametrize(
    "avatar,color,met,unmet", _W1G2_AVATARS, ids=[a[0] for a in _W1G2_AVATARS]
)
def test_w1g2_the_ai_prices_the_avatar_at_the_reduced_cost(
    set_pool, avatar, color, met, unmet,
):
    """The AI's affordability read asks the same ``cost_reduction_for_cast``
    the cast does — priced at {6}{X}{X} on a board where the card costs {X}{X},
    the AI would never propose the cast; priced cheap where it is not, it would
    propose a cast the rules refuse every turn."""
    from engine.ai_policy import _cost_for

    for board, generic in ((met, 0), (unmet, 6)):
        game = _w1g2_avatar_game(set_pool, avatar, **board)
        cost = _cost_for(game, game.players[0], set_pool("PCY")[avatar], None)
        assert cost.get("generic", 0) == generic, (board, cost)
        assert cost.get(color) == 2, cost


def test_w1g2_an_opponent_is_one_opponent_at_a_free_for_all_table(set_pool):
    """"If **an** opponent controls seven or more lands" is an existential over
    seats: one opponent must hold the count. Two opponents with four lands each
    hold eight between them and neither holds seven — pooled, the Avatar would
    be {6} cheaper on a board the card does not name.
    """
    from engine.cost_modifiers import cost_reduction_for_cast

    pcy = set_pool("PCY")
    game = _w1g2_avatar_game(set_pool, "Avatar of Fury", seats=3)
    for seat in (1, 2):
        for _ in range(4):
            game._put_permanent_onto_battlefield(
                seat, _W1G2Permanent(card=set_pool("LEA")["Mountain"]), None
            )
    assert cost_reduction_for_cast(game, 0, pcy["Avatar of Fury"])[0].generic == 0
    for _ in range(3):
        game._put_permanent_onto_battlefield(
            2, _W1G2Permanent(card=set_pool("LEA")["Mountain"]), None
        )
    assert cost_reduction_for_cast(game, 0, pcy["Avatar of Fury"])[0].generic == 6


def test_w1g2_avatar_of_will_asks_each_opponent_for_an_empty_hand(set_pool):
    """"If an opponent has no cards in hand" — the same existential, asked of
    hands. The word used to resolve to the evaluator's *target* seat, which a
    cast-time cost does not have; at a three-seat table one empty hand is
    enough and a hand-holding opponent beside it changes nothing."""
    from engine.cost_modifiers import cost_reduction_for_cast

    lea = set_pool("LEA")
    game = _w1g2_avatar_game(
        set_pool, "Avatar of Will", their_hand=("Island",), seats=3
    )
    will = set_pool("PCY")["Avatar of Will"]
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 6, "P3 is empty"
    game.players[2].hand.append(lea["Island"])
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 0
    game.players[1].hand.clear()
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 6


def test_w1g2_avatar_of_might_needs_one_opponent_four_ahead(set_pool):
    """"…controls **at least four more** creatures than you." The margin is the
    printed number, read by the reader the seat comparison "at least two fewer"
    already uses, and it is a lead over *your* count: four Bears against your
    none qualifies, four against your one does not, and two opponents' Bears are
    never added together."""
    from engine.cost_modifiers import cost_reduction_for_cast

    bear = set_pool("LEA")["Grizzly Bears"]
    might = set_pool("PCY")["Avatar of Might"]
    game = _w1g2_avatar_game(set_pool, "Avatar of Might", seats=3)
    for seat, count in ((1, 3), (2, 3)):
        for _ in range(count):
            game._put_permanent_onto_battlefield(seat, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 0, "3 and 3"
    game._put_permanent_onto_battlefield(2, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 6, "a lead of 4"
    game._put_permanent_onto_battlefield(0, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 0, "a lead of 3"


def test_w1g2_avatar_of_woe_counts_creature_cards_in_every_graveyard(set_pool):
    """"…ten or more creature cards **total in all graveyards**." Every pile,
    summed — "total" is the reading the count's ``owner: "all"`` already has —
    and *creature* cards only: a land card in a graveyard is not one of the
    ten."""
    from engine.cost_modifiers import cost_reduction_for_cast

    lea = set_pool("LEA")
    woe = set_pool("PCY")["Avatar of Woe"]
    game = _w1g2_avatar_game(
        set_pool, "Avatar of Woe", my_grave=("Grizzly Bears",) * 9,
        their_grave=("Island",) * 4,
    )
    assert cost_reduction_for_cast(game, 0, woe)[0].generic == 0
    game.players[1].graveyard.append(lea["Grizzly Bears"])
    assert cost_reduction_for_cast(game, 0, woe)[0].generic == 6


def test_w1g2_avatar_of_hope_blocks_any_number_of_creatures(set_pool):
    """Avatar of Hope's other line — Wall of Glare's permission, which the
    block-permission table already read; the card was unsupported for its cost
    line alone. Three attackers rather than two, so a grant of one additional
    block cannot pass."""
    bear = set_pool("LEA")["Grizzly Bears"]
    hope = _W1G2Permanent(card=set_pool("PCY")["Avatar of Hope"])
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P1", battlefield=[_W1G2Permanent(card=bear) for _ in range(3)]),
        _W1G2PlayerState(name="P2", battlefield=[hope]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1, 2], 1)
    assert declared, why
    game.advance_combat_phase()

    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why


def test_w1g2_a_trailing_and_a_fronted_condition_together_refuse(set_pool):
    """One sentence, two conditions — a conjunction no reader here was asked
    to read, and either half alone is a cheaper spell than the card. The line
    refuses rather than keeping one."""
    from engine.cost_modifiers import self_cost_reduction

    assert self_cost_reduction(
        "If you have 3 or less life, this spell costs {6} less to cast if an "
        "opponent has no cards in hand."
    ) is None
    # …and a fronted condition the grammar cannot read refuses too.
    assert self_cost_reduction(
        "If the moon is full, this spell costs {6} less to cast."
    ) is None
    # …as does one it reads but a spell being cast cannot ask (CR 601.2f has no
    # trigger to have frozen "that player").
    assert self_cost_reduction(
        "If that player has no cards in hand, this spell costs {6} less to cast."
    ) is None


def test_w1g2_defense_of_the_heart_counts_one_opponents_creatures(set_pool):
    """"At the beginning of your upkeep, if **an opponent** controls three or
    more creatures, …" — the shipped card the existential above fixed. The
    evaluator pooled every opponent's board, so at a three-seat table two
    opponents with two creatures each fired it; a duel cannot tell the readings
    apart, which is how it shipped.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers.control_flow import evaluate_condition

    ulg = set_pool("ULG")
    bear = set_pool("LEA")["Grizzly Bears"]
    defense = ulg["Defense of the Heart"]
    gate = next(
        trig.instruction.payload["intervening_if"]
        for trig in _w1g2_compile(defense).triggered_abilities
        if trig.instruction is not None
        and "intervening_if" in trig.instruction.payload
    )
    game = _W1G2Game(players=[_W1G2PlayerState(name=f"P{n}") for n in (1, 2, 3)])
    for seat in (1, 2):
        for _ in range(2):
            game._put_permanent_onto_battlefield(seat, _W1G2Permanent(card=bear), None)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=defense,
    )
    assert not evaluate_condition(game, context, gate), "2 + 2 is not one opponent's 3"
    game._put_permanent_onto_battlefield(2, _W1G2Permanent(card=bear), None)
    assert evaluate_condition(game, context, gate)
