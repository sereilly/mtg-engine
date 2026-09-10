"""Mercadian Masques sorceries.

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
# Land Grant, the one card in this pool whose CR 118.9 alternative cost is
# paid by **information**: "If you have no land cards in hand, you may reveal
# your hand rather than pay this spell's mana cost." Both halves are unusual --
# the condition reads a hand rather than a board, and the payment moves nothing
# -- so the two are asserted apart: an offer that appeared on a hand holding a
# land would be a free Rampant Growth, and a payment nobody could see would be
# a free spell with a log line.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_grant_table(set_pool, hand, mine=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: this card is about not paying a
    mana cost, and a game that charges none cannot tell a free cast from an
    ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    caster.library = [pool["Forest"], pool["Plains"], pool["Wild Jhovall"]]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_grant_offers(game, card):
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(0, card, spell_hand_index=0)
        if offer["kind"] == "alternative"
    ]


def test_g1_land_grant_is_free_only_with_no_land_in_hand(set_pool):
    """CR 601.2b: the condition is a **hand**, and it is checked at the cast.

    A card in a hand has no computed characteristics (CR 613.1), so the phrase
    is put to the card matcher rather than to ``subject_matches`` -- a narrowing
    only the permanent matcher could answer would be silently dropped by the
    hand scan, and the offer would stand on a hand the card does not name.
    """
    card = set_pool("MMQ")["Land Grant"]

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Forest"])
    assert _g1_grant_offers(game, card) == []

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Brainstorm"])
    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_offer_survives_an_empty_hand(set_pool):
    """An empty hand holds no land card, so the offer stands and is payable.

    CR 601.2h has no shortfall to find in a reveal: showing nothing is still
    showing what you have. A gate that treated "nothing to reveal" as unpayable
    would refuse the card on exactly the board it is designed for.
    """
    card = set_pool("MMQ")["Land Grant"]
    game, _, _ = _g1_grant_table(set_pool, ["Land Grant"])

    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_reveals_the_hand_and_fetches_for_nothing(set_pool):
    """The whole card: the hand is shown, the Forest arrives, no mana is spent.

    The reveal goes through ``record_reveal`` -- the feed the web layer reads,
    the same seam the ``reveal_hand`` *effect* uses -- rather than a log line
    alone: a reveal the client cannot show is a reveal the opponent has to take
    on trust, and here it is the entire price of the spell.

    The spell is already off the hand when the price is paid (CR 601.2a), so
    what is shown is the hand Land Grant's own condition is about.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Brainstorm", "Wild Jhovall"],
    )

    result = game.cast_from_hand(0, "Land Grant", alternative_cost=True)
    resolve_stack(game)
    # The library search is a queued decision the spell does not wait on, so it
    # is drained the way an AI or headless seat drains one.
    game.auto_resolve_pending_choices(0)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert caster.battlefield == []
    assert "Forest" in [held.name for held in caster.hand]
    revealed = [line for line in game.log if "revealed their hand" in line]
    assert len(revealed) == 1
    assert "Brainstorm" in revealed[0] and "Wild Jhovall" in revealed[0]
    # CR 601.2a: the spell is on the stack and cannot be among what it reveals.
    assert "Land Grant" not in revealed[0].split(": ", 1)[1]


def test_g1_land_grant_still_costs_its_mana_when_a_land_is_held(set_pool):
    """CR 118.9b: the alternative is optional and the printed cost stands.

    Which is exactly what Land Grant did on every board before this round -- the
    line was claimed by nothing, so it was always cast at ``{1}{G}``. The
    regression to watch for is the other direction, and it is the one this
    asserts: with a land in hand the offer is gone and the mana is still spent.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Forest"], mine=("Forest", "Forest"),
    )
    caster.mana_pool["G"] = 1
    caster.mana_pool["C"] = 1

    result = game.cast_from_hand(0, "Land Grant")
    resolve_stack(game)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert not any("revealed their hand" in line for line in game.log)
