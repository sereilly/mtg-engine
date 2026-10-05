"""Invasion instants.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: kicker ---
from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_instant_duel(set_pool, name, pool):
    """Seat 0 holds the INV instant *name* with *pool* floating, and costs are
    charged — a kicker is a price, so a rig that waives mana cannot tell a
    kicked cast from a free one."""
    lea = set_pool("LEA")
    mine = _W1G1PlayerState(
        "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
    )
    theirs = _W1G1PlayerState("Victim", library=[lea["Forest"]] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_instant_duel


def _w1g1_onto_battlefield(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g1_onto_battlefield


def test_w1g1_dismantling_blow_kicked_also_draws_two(set_pool):
    """"Destroy target artifact or enchantment. If this spell was kicked, draw
    two cards." The plain additive shape: the condition is read at resolution
    off the spell's own stack record."""
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    ring = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    result = game.cast_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[ring.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[0].hand] == ["Forest", "Forest"]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g1_dismantling_blow_unkicked_only_destroys(set_pool):
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    ring = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    result = game.cast_from_hand(
        0, "Dismantling Blow", target_permanent_ids=[ring.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert game.players[0].hand == []
    # {2}{W} spent; the three that would have paid the kicker are still there.
    assert sum(game.players[0].mana_pool.values()) == 3


def test_w1g1_dismantling_blow_asks_for_its_target_kicked_or_not(set_pool):
    """The destroy is no part of the kicker (CR 702.33g reaches only a part
    that has its effect *only if* kicked), so the picker asks for the artifact
    or enchantment on either announcement — and offers nothing else."""
    card = set_pool("INV")["Dismantling Blow"]
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    for announced in ({}, {"{2}{U}": 1}):
        spec = game.cast_target_spec(0, card, optional_cost_payments=announced)
        assert spec["requires_target"]
        assert [entry["name"] for entry in spec["valid_targets"]] == ["Sol Ring"]

    refused = game.cast_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[
            next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
            .permanent_id
        ],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 6


def test_w1g1_agonizing_demise_kicked_burns_the_creatures_controller(set_pool):
    """"Destroy target nonblack creature. It can't be regenerated. If this
    spell was kicked, Agonizing Demise deals damage equal to that creature's
    power to the creature's controller." The power is the destroyed creature's
    last known (CR 608.2h) and the damage goes to *its* controller."""
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    giant = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    giant.regeneration_shield = 1
    result = game.cast_from_hand(
        0, "Agonizing Demise", optional_cost_payments={"{1}{R}": 1},
        target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert [player.life for player in game.players] == [20, 17]


def test_w1g1_agonizing_demise_unkicked_deals_no_damage(set_pool):
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    giant = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    result = game.cast_from_hand(
        0, "Agonizing Demise", target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g1_agonizing_demise_cannot_be_aimed_at_a_black_creature(set_pool):
    """"…target **nonblack** creature": the picker offers only the Giant, and a
    cast naming the Knight is refused before any mana is spent."""
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    knight = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Black Knight"])
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    spec = game.cast_target_spec(0, set_pool("INV")["Agonizing Demise"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Hill Giant"]

    refused = game.cast_from_hand(
        0, "Agonizing Demise", optional_cost_payments={"{1}{R}": 1},
        target_permanent_ids=[knight.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(knight)
    assert sum(game.players[0].mana_pool.values()) == 6


def test_w1g1_explosive_growth_is_two_or_five_never_seven(set_pool):
    """"Target creature gets +2/+2 until end of turn. If this spell was kicked,
    **that creature** gets +5/+5 until end of turn **instead**." One pump on
    the one creature the spell names, sized by the kicker — the back-reference
    in the second sentence is the first sentence's own target, so the spell
    still names exactly one creature (CR 601.2c)."""
    card = set_pool("INV")["Explosive Growth"]
    for kick, body in ((None, (4, 4)), ("{5}", (7, 7))):
        game = _w1g1_instant_duel(set_pool, "Explosive Growth", {"G": 9})
        bears = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Grizzly Bears"])
        giant = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Hill Giant"])
        spec = game.cast_target_spec(
            0, card, optional_cost_payments={kick: 1} if kick else None
        )
        assert spec["kind"] == "creature" and "max_targets" not in spec
        result = game.cast_from_hand(
            0, "Explosive Growth",
            optional_cost_payments={kick: 1} if kick else None,
            target_permanent_ids=[bears.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        assert (bears.effective_power, bears.effective_toughness) == body
        assert (giant.effective_power, giant.effective_toughness) == (3, 3)
        assert sum(game.players[0].mana_pool.values()) == (3 if kick else 8)


def test_w1g1_orims_touch_prevents_two_or_four(set_pool):
    """"Prevent the next 2 damage that would be dealt to any target this turn.
    If this spell was kicked, prevent the next 4 damage that would be dealt to
    **that permanent or player** this turn instead." One shield of one size on
    the one thing the spell names, a creature or a player."""
    from engine.damage_events import deal_damage

    bolt = set_pool("LEA")["Lightning Bolt"]
    for kick, prevented in ((None, 2), ("{1}", 4)):
        announced = {kick: 1} if kick else None

        game = _w1g1_instant_duel(set_pool, "Orim's Touch", {"W": 4})
        giant = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Hill Giant"])
        result = game.cast_from_hand(
            0, "Orim's Touch", optional_cost_payments=announced,
            target_permanent_ids=[giant.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        event = {"recipient": giant, "amount": 5, "source": bolt, "combat": False}
        assert deal_damage(game, event).dealt == 5 - prevented

        game = _w1g1_instant_duel(set_pool, "Orim's Touch", {"W": 4})
        result = game.cast_from_hand(
            0, "Orim's Touch", optional_cost_payments=announced,
            target_player_index=0,
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        # A fresh event each time: `deal_damage` writes what survived the
        # shields back onto the one it is handed.
        for seat, survives in ((0, 5 - prevented), (1, 5)):
            event = {
                "recipient": game.players[seat], "amount": 5, "source": bolt,
                "combat": False,
            }
            # …seat 1 was given no shield.
            assert deal_damage(game, event).dealt == survives


def test_w1g1_a_copy_of_a_kicked_spell_is_kicked(set_pool):
    """CR 707.10: a copy of a spell copies the choices made as it was cast, and
    paying a kicker is one (CR 702.33d). Fork on a kicked Dismantling Blow puts
    a kicked copy on the stack: the copy resolves first, destroys the artifact
    and draws the two cards — and the original, its only target gone, is
    removed by CR 608.2b and draws nothing."""
    lea = set_pool("LEA")
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3, "R": 2})
    game.players[0].hand.append(lea["Fork"])
    ring = _w1g1_onto_battlefield(game, 1, lea["Sol Ring"])
    assert game.queue_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[ring.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Fork").supported
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[0].hand] == ["Forest", "Forest"]
    assert "Dismantling Blow (copy) resolved" in game.log
# end of the W1G1 instants block
