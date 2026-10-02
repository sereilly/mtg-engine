"""Nemesis enchantments, Auras included.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: alternative costs and redirects ---
# Lashknife: an Aura whose alternative cost (CR 118.9) taps a creature. The
# Aura gate (`engine/auras.py`) refused the card on that line before this round
# — "unimplemented aura effect" — because it read the cost sentence as an effect
# the Aura has while attached.
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g2e_table(set_pool, hand, mine=()):
    """Two seats, mana costs **enforced**: the card is about which price is
    paid. Basics and bystanders come from the base set."""
    pools = (set_pool("NEM"), set_pool("LEA"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [card(name) for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    caster.battlefield.extend(Permanent(card=card(name)) for name in mine)
    game._sync_control()
    return game, caster


def test_w1g2_lashknife_taps_the_named_creature_and_grants_first_strike(set_pool):
    """The whole card: a Plains on the board, the Hill Giant named to pay, the
    Bears enchanted. The deterministic pick would have tapped the Bears (it
    keeps the bigger creature), so a payment that ignored the choice fails
    here; and the first strike is read through the layer accessor, so it is
    the Aura's static and not a flag the cast left behind."""
    game, caster = _w1g2e_table(
        set_pool, ["Lashknife"], mine=("Plains", "Grizzly Bears", "Hill Giant")
    )
    bears, giant = caster.battlefield[1], caster.battlefield[2]

    result = game.cast_from_hand(
        0, "Lashknife", alternative_cost=True,
        target_player_index=0, target_permanent_index=1,
        alternative_cost_permanent_ids=[giant.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert (bears.tapped, giant.tapped) == (False, True)
    assert game._has_keyword(bears, "first strike")
    assert not game._has_keyword(giant, "first strike")
    assert not any(caster.mana_pool.values())


def test_w1g2_lashknife_offers_only_creatures_that_can_pay(set_pool):
    """What the cast picker offers is the list the payment takes from: an
    untapped creature the caster controls. The tapped Bears and the Plains are
    not offered, and a name outside the list is refused with nothing paid."""
    game, caster = _w1g2e_table(
        set_pool, ["Lashknife"], mine=("Plains", "Grizzly Bears", "Hill Giant")
    )
    caster.battlefield[1].tapped = True
    giant = caster.battlefield[2]

    offers = game.cast_cost_offers(0, set_pool("NEM")["Lashknife"], spell_hand_index=0)
    (offer,) = [o for o in offers if o["kind"] == "alternative"]
    assert offer["payable"] and offer["permanent_verb"] == "tap"
    assert offer["permanent_choices"] == [
        {"id": giant.permanent_id, "name": "Hill Giant"}
    ]

    plains = caster.battlefield[0]
    refused = game.cast_from_hand(
        0, "Lashknife", alternative_cost=True,
        target_player_index=0, target_permanent_index=2,
        alternative_cost_permanent_ids=[plains.permanent_id],
    )
    assert not refused.supported
    assert not giant.tapped and [c.name for c in caster.hand] == ["Lashknife"]
