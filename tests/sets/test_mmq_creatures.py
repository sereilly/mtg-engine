"""Mercadian Masques creatures.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: alternative and additional casting costs ---
# CR 118.9's *second* printed spelling, which the rule names beside the first:
# "You may cast this spell without paying its mana cost." Mercadian Masques
# prints it five times, once per colour, each behind a two-land condition
# checked at CR 601.2b — so what is asserted here is the board and the mana
# pool, never that a sentence parsed.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

#: (Legate, the land **you** must control, the land an **opponent** must).
#: Printed as a cycle, so the table is the cycle: a reader that admitted one
#: seat's land for the other's would pass on any single card and fail on all
#: five, which is what the swapped-board test below asks.
_G1_LEGATES = (
    ("Cho-Arrim Legate", "Plains", "Swamp"),
    ("Deepwood Legate", "Swamp", "Forest"),
    ("Kyren Legate", "Mountain", "Plains"),
    ("Rushwood Legate", "Forest", "Island"),
    ("Saprazzan Legate", "Island", "Mountain"),
)


def _g1_duel(set_pool, hand, mine=(), theirs=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: every card in this block is about
    not paying a mana cost, and a game that charges none cannot tell a free cast
    from an ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    for name in theirs:
        other.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_offers(game, seat, card, hand_index=0):
    """The alternative-cost offers the picker would show, with payability."""
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(
            seat, card, spell_hand_index=hand_index
        )
        if offer["kind"] == "alternative"
    ]


_G1_FREE = ("cast it without paying its mana cost", True)


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_is_free_when_both_lands_are_there(set_pool, name, mine, theirs):
    """CR 118.9: the printed alternative cost is a price of nothing.

    Every one of the five compiled ``supported`` before this round — on its
    *other* line, a keyword or an activated ability — while the sentence the
    card is named for was claimed by nobody at all. So it was castable only at
    its printed mana cost, and the whole point of the cycle did not exist.
    "The sentence parses" is exactly the evidence that was wrong, so the board
    is what is asserted: nothing tapped, nothing in the pool, the creature in
    play.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name], mine=(mine,), theirs=(theirs,))

    assert compile_card_oracle(card).supported
    assert _g1_offers(game, 0, card) == [_G1_FREE]

    result = game.cast_from_hand(0, name, alternative_cost=True)

    assert result.supported, result.details
    assert [perm.card.name for perm in caster.battlefield] == [mine, name]
    # CR 118.9c: the alternative replaces the payment, never the mana cost.
    assert not any(caster.mana_pool.values())
    assert not any(perm.tapped for perm in caster.battlefield)
    assert card.mana_cost


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_offers_nothing_on_an_empty_board(set_pool, name, mine, theirs):
    """CR 601.2b: a condition that does not hold is not an offer.

    Not "an offer that cannot be paid" — those are different answers and the
    difference is what a picker shows. An unmet condition means there is no
    alternative cost to announce, so the caster is refused by CR 118.9 rather
    than by CR 601.2h, and nothing is spent either way.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name])

    assert _g1_offers(game, 0, card) == []

    result = game.cast_from_hand(0, name, alternative_cost=True)

    assert not result.supported
    assert "CR 118.9" in result.details
    assert [held.name for held in caster.hand] == [name]


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_reads_which_seat_controls_which_land(set_pool, name, mine, theirs):
    """The two land types are not interchangeable, and neither are the seats.

    "If an opponent controls a Swamp and **you** control a Plains" is two
    clauses about two different battlefields. A reader that scanned one board
    for both, or that folded the pair into "these two lands are somewhere",
    passes every other test in this block: both lands are on the table here,
    only on the wrong sides.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name], mine=(theirs,), theirs=(mine,))

    assert _g1_offers(game, 0, card) == []
    assert not game.cast_from_hand(0, name, alternative_cost=True).supported
    assert [held.name for held in caster.hand] == [name]


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_needs_both_halves_of_its_condition(set_pool, name, mine, theirs):
    """Each clause alone is not the condition (CR 601.2b).

    An "and" read as an "or" is an offer standing on strictly more boards than
    the card names — the direction a cost must never drift in, and invisible to
    every test that sets up the board the card asks for.
    """
    card = set_pool("MMQ")[name]

    game, _, _ = _g1_duel(set_pool, [name], mine=(mine,))
    assert _g1_offers(game, 0, card) == []

    game, _, _ = _g1_duel(set_pool, [name], theirs=(theirs,))
    assert _g1_offers(game, 0, card) == []


def test_g1_legate_condition_is_re_asked_at_every_cast(set_pool):
    """CR 601.2b checks the condition **as the spell is cast**, not once.

    The offer is derived from the board at the moment of the announcement, so a
    Legate that was free while both lands were there is not free after one
    leaves. A condition resolved at compile time — the tempting place, since the
    printed sentence never changes — would be a permanently free creature.
    """
    card = set_pool("MMQ")["Kyren Legate"]
    game, _, other = _g1_duel(
        set_pool, ["Kyren Legate"], mine=("Mountain",), theirs=("Plains",),
    )

    assert _g1_offers(game, 0, card) == [_G1_FREE]

    game.remove_from_battlefield(other.battlefield[0])

    assert _g1_offers(game, 0, card) == []


def test_g1_legate_still_costs_its_mana_when_the_offer_is_declined(set_pool):
    """CR 118.9b: the alternative cost is optional, and declining is a real cast.

    The caster who says nothing pays the printed price — which is what the five
    Legates did on every board before this round, and what they must go on doing
    on a board that does not meet the condition.
    """
    game, caster, _ = _g1_duel(
        set_pool, ["Kyren Legate"], mine=("Mountain", "Mountain"),
    )
    caster.mana_pool["R"] = 1
    caster.mana_pool["C"] = 1

    result = game.cast_from_hand(0, "Kyren Legate")

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert [perm.card.name for perm in caster.battlefield].count("Kyren Legate") == 1
