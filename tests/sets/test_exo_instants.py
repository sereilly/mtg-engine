"""Exodus instants.

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


# --- W1G5: printed costs, and a flip inside a loop ---
#
# Forbid's and Sonic Burst's costs (CR 601.2b, CR 702.27a) and Fighting Chance's
# per-creature coin flip (CR 705.1). Imports are in this block, per the header's
# parallel-authorship convention.

import random as _g5_random

from engine import Game as _G5Game
from engine.cast_costs import additional_costs as _g5_costs
from engine.card_loader import load_catalog as _g5_catalog
from engine.models import PlayerState as _G5Player, Permanent as _G5Permanent
from engine.oracle import compile_card_oracle as _g5_compile
from tests.helpers import resolve_stack as _g5_drain

_G5_POOL = {card.name: card for card in _g5_catalog()}


def _g5_ready(perm: _G5Permanent) -> _G5Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g5_forbid_game(set_pool, spares):
    """Forbid in hand behind an opponent's Lightning Bolt, with *spares* other
    cards to pay a buyback with."""
    caster = _G5Player(
        name="A",
        hand=[set_pool("EXO")["Forbid"]] + [_G5_POOL["Grizzly Bears"]] * spares,
    )
    opponent = _G5Player(name="B", hand=[_G5_POOL["Lightning Bolt"]])
    game = _G5Game(players=[caster, opponent])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    return game, caster, opponent


def test_forbid_charges_its_two_card_buyback_and_comes_back(set_pool):
    """"Buyback—Discard two cards." CR 702.27a's optional additional cost with a
    **counted** discard, which nothing in the pool had printed before.

    The count is the whole of what makes such a cost unpayable (CR 601.2h), so
    both halves are asserted here: the cast that pays it and the one that cannot.
    """
    (cost,) = _g5_costs(set_pool("EXO")["Forbid"])
    assert cost.optional_key == "discard two cards"
    assert cost.discard_cards == 2 and not cost.discard_at_random

    game, caster, opponent = _g5_forbid_game(set_pool, spares=2)
    result = game.queue_from_hand(
        0, "Forbid", target_stack_index=0,
        optional_cost_payments={"discard two cards": 1},
    )
    _g5_drain(game)

    assert result.supported, result.details
    assert len(caster.graveyard) == 2, "both cards, not one"
    assert [c.name for c in opponent.graveyard] == ["Lightning Bolt"]
    assert "Forbid" in [c.name for c in caster.hand], "CR 702.27a's hand return"


def test_forbid_refuses_a_buyback_a_one_card_hand_cannot_pay(set_pool):
    """CR 601.2h: one card is no more a payment of a two-card cost than none.

    The half a gate that asked only "is there a card in hand?" would get wrong —
    and it would get it wrong by admitting the cast and then charging one, which
    is a spell bought back for half its printed price.
    """
    game, caster, _opponent = _g5_forbid_game(set_pool, spares=1)
    result = game.queue_from_hand(
        0, "Forbid", target_stack_index=0,
        optional_cost_payments={"discard two cards": 1},
    )

    assert not result.supported
    assert "601.2h" in result.details
    assert len(caster.hand) == 2, "nothing is spent on the way to a refusal"


def test_forbid_declined_leaves_the_hand_alone(set_pool):
    """An offer is not a price (CR 601.2b): a caster who declines pays nothing
    and the spell goes to the graveyard."""
    game, caster, _opponent = _g5_forbid_game(set_pool, spares=2)
    game.queue_from_hand(0, "Forbid", target_stack_index=0)
    _g5_drain(game)

    assert caster.graveyard[-1].name == "Forbid"
    assert len(caster.hand) == 2, "the discard is only charged when taken"


def test_sonic_burst_discards_at_random_and_ignores_a_named_card(set_pool):
    """"As an additional cost to cast this spell, discard a card at random."

    "At random" is not a narrowing of *which* card may pay — every card in hand
    may — it is the removal of the payer's choice. So the assertion is that a
    named card is **not** honoured: a cost the payer picks is a strictly better
    cost than one chance picks, and the two shapes are otherwise identical.
    """
    (cost,) = _g5_costs(set_pool("EXO")["Sonic Burst"])
    assert cost.discard_cards == 1 and cost.discard_at_random

    picked = set()
    for seed in range(12):
        _g5_random.seed(seed)
        caster = _G5Player(
            name="A",
            hand=[
                set_pool("EXO")["Sonic Burst"],
                _G5_POOL["Grizzly Bears"], _G5_POOL["Hill Giant"],
                _G5_POOL["Mons's Goblin Raiders"],
            ],
        )
        game = _G5Game(players=[caster, _G5Player(name="B")])
        game.enforce_mana_costs = False
        # Index 1 is named, and the point of the test is that it is ignored.
        result = game.queue_from_hand(
            0, "Sonic Burst", target_player_index=1, cost_hand_index=1,
        )
        _g5_drain(game)
        assert result.supported, result.details
        assert game.players[1].life == 16, "4 damage to any target"
        picked.add(caster.graveyard[0].name)

    assert len(picked) > 1, (
        "every seed binned the same card, so the payer's index was honoured "
        "or the deterministic first-card default was taken"
    )


def test_sonic_burst_cannot_be_cast_off_an_empty_hand(set_pool):
    """CR 601.2h again, on the mandatory half of the same clause: the spell is
    on the stack (CR 601.2a) and so cannot discard itself to pay for itself."""
    caster = _G5Player(name="A", hand=[set_pool("EXO")["Sonic Burst"]])
    game = _G5Game(players=[caster, _G5Player(name="B")])
    game.enforce_mana_costs = False

    result = game.queue_from_hand(0, "Sonic Burst", target_player_index=1)

    assert not result.supported and "601.2h" in result.details


def _g5_fighting_chance_board(set_pool, blockers):
    """Two 3/3s attack; *blockers* 8/8s block them one apiece, and the defender
    holds Fighting Chance."""
    attackers = [_g5_ready(_G5Permanent(card=_G5_POOL["Hill Giant"])) for _ in range(2)]
    walls = [
        _g5_ready(_G5Permanent(card=_G5_POOL["Force of Nature"]))
        for _ in range(blockers)
    ]
    attacker_seat = _G5Player(name="P0", battlefield=list(attackers))
    defender = _G5Player(
        name="P1", battlefield=list(walls),
        hand=[set_pool("EXO")["Fighting Chance"]],
    )
    game = _G5Game(players=[attacker_seat, defender])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, list(range(2)))[0]
    game.auto_resolve_pending_choices()
    game.advance_combat_phase()          # declare blockers
    game.declare_blockers(1, {i: [i] for i in range(blockers)})
    return game, attacker_seat


def test_fighting_chance_flips_once_per_blocking_creature(set_pool):
    """"For each blocking creature, flip a coin. If you win the flip, prevent
    all combat damage that would be dealt by that creature this turn."

    CR 705.1's flip is *inside* the loop and so is what rides on it — "that
    creature" names the member the flip was made for, and there is no other
    creature it could name. Two blockers therefore mean two flips and two
    independent answers; a reading that left the conditional beside the loop
    would ask about "the" flip where the loop made one per creature.
    """
    (loop,) = _g5_compile(set_pool("EXO")["Fighting Chance"]).instructions
    assert loop.kind == "for_each"
    assert loop.payload["iterator"] == {
        "type_filter": "creature", "blocking_only": True,
    }
    flip, stakes = loop.payload["effect"]
    assert flip.kind == "flip_coin"
    assert stakes.kind == "if_then"
    assert stakes.payload["condition"] == {"kind": "coin_flip", "won": True}
    assert stakes.payload["then"][0].kind == "prevent_damage_by_target_until_eot"

    _g5_random.seed(0)
    game, _attackers = _g5_fighting_chance_board(set_pool, blockers=2)
    assert game.queue_from_hand(1, "Fighting Chance").supported
    _g5_drain(game)

    assert sum("coin flip" in line for line in game.log) == 2


def test_fighting_chance_saves_exactly_the_attackers_whose_flips_it_won(set_pool):
    """The behavioural half, over enough seeds to see every outcome: an 8/8
    blocker kills a 3/3 attacker unless its damage was prevented, so the number
    of surviving attackers is the number of flips won."""
    seen = set()
    for seed in range(8):
        _g5_random.seed(seed)
        game, attacker_seat = _g5_fighting_chance_board(set_pool, blockers=2)
        game.queue_from_hand(1, "Fighting Chance")
        _g5_drain(game)
        won = sum("won the coin flip" in line for line in game.log)
        game.advance_combat_phase()      # combat damage
        assert len(attacker_seat.battlefield) == won, game.log
        seen.add(won)

    assert seen >= {0, 1}, (
        "every seed gave the same answer; the flip is not being re-asked "
        "per creature"
    )
# end of the W1G5 instants block
