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


# --- W1G3: activation costs ---
# The five spellshapers ("<mana>, {T}, Discard two cards: …"), and the costs
# paid with permanents: Copper-Leaf Angel's "Sacrifice X lands", Jeweled
# Spirit's "Sacrifice two lands", Keldon Battlewagon's "Tap an untapped creature
# you control" read back as "the power of the creature tapped this way".

import random as _w1g3_random

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

from tests.helpers import resolve_stack


def _w1g3_game(mine, theirs=(), *, hand=(), their_hand=(), interactive=()):
    """Seat 0 holds *mine* and *hand*, seat 1 *theirs* and *their_hand*; turn 0
    begun, mana not enforced, nothing summoning sick. Returns the game and the
    two permanent lists in the order given."""
    me = [Permanent(card=card) for card in mine]
    them = [Permanent(card=card) for card in theirs]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(me), hand=list(hand)),
        PlayerState(name="P1", battlefield=list(them), hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in (*me, *them):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, me, them


def _w1g3_spec(set_pool, name):
    """The activation picker spec of *name*'s first ability."""
    (ability,) = compile_card_oracle(set_pool("PCY")[name]).activated_abilities
    return derive_activation_spec(ability)


def test_w1g3_latulla_discards_two_identical_cards_and_deals_x(set_pool):
    """"{X}{R}, {T}, Discard two cards: Latulla deals X damage to any target."

    Two copies of one card in a hand are one ``CardDefinition`` object, so the
    payment is collected by position: the second Bears is a second card, not
    the first one seen twice.
    """
    lea = set_pool("LEA")
    bears = lea["Grizzly Bears"]
    game, (latulla,), _ = _w1g3_game(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=[bears, bears],
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=3,
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert p0.hand == [] and [c.name for c in p0.graveyard] == ["Grizzly Bears"] * 2
    assert latulla.tapped
    assert p1.life == 17


def test_w1g3_latulla_with_one_card_is_refused_before_anything_is_paid(set_pool):
    """CR 601.2h via 602.2b: one card is no payment of a two-card cost, and the
    refusal comes before the {T}, the mana or the one card is spent."""
    lea = set_pool("LEA")
    game, (latulla,), _ = _w1g3_game(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=[lea["Grizzly Bears"]],
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=3,
    )
    assert not result.supported
    assert "not enough cards" in result.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert not latulla.tapped and game.players[1].life == 20


def test_w1g3_greel_makes_target_player_discard_x_at_random(set_pool):
    """"{X}{B}, {T}, Discard two cards: Target player discards X cards at
    random." The payer's named card is honoured, the second is the next one in
    hand, and the target loses exactly X."""
    lea = set_pool("LEA")
    bears, bolt = lea["Grizzly Bears"], lea["Lightning Bolt"]
    _w1g3_random.seed(4)
    game, _, _ = _w1g3_game(
        [set_pool("PCY")["Greel, Mind Raker"]],
        hand=[bears, bolt, lea["Hill Giant"]], their_hand=[bolt, bolt, bears],
    )
    result = game.queue_permanent_ability(
        0, "Greel, Mind Raker", target_player_index=1, x_value=2, cost_hand_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert [c.name for c in p0.graveyard] == ["Lightning Bolt", "Grizzly Bears"]
    assert [c.name for c in p0.hand] == ["Hill Giant"]
    assert len(p1.hand) == 1 and len(p1.graveyard) == 2
    assert "P1 discarded 2 cards at random" in game.log


def test_w1g3_alexi_returns_x_targets_from_both_battlefields(set_pool):
    """"Return X target creatures to their owners' hands." The picker asks for
    X and then that many creatures, and each goes to its own owner's hand."""
    lea = set_pool("LEA")
    spec = _w1g3_spec(set_pool, "Alexi, Zephyr Mage")
    assert spec["kind"] == "creature" and spec["x_targets"]
    assert spec["cost_spec"]["discard_cost"] and spec["cost_spec"]["count"] == 2

    game, (_, giant), (angel,) = _w1g3_game(
        [set_pool("PCY")["Alexi, Zephyr Mage"], lea["Hill Giant"]],
        [lea["Serra Angel"]], hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Alexi, Zephyr Mage", x_value=2,
        target_permanent_ids=[giant.permanent_id, angel.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert [c.name for c in p0.hand] == ["Hill Giant"]
    assert [c.name for c in p1.hand] == ["Serra Angel"]
    assert [p.card.name for p in p0.battlefield] == ["Alexi, Zephyr Mage"]


def test_w1g3_alexi_cannot_name_more_targets_than_its_x(set_pool):
    """CR 601.2c fixes the number of targets from the X announced at 601.2b.
    The handler returns every slot it is handed, so the count is enforced at
    the announcement — with nothing paid."""
    lea = set_pool("LEA")
    game, (alexi,), theirs = _w1g3_game(
        [set_pool("PCY")["Alexi, Zephyr Mage"]],
        [lea["Grizzly Bears"], lea["Hill Giant"]],
        hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Alexi, Zephyr Mage", target_player_index=1, x_value=1,
        target_permanent_ids=[perm.permanent_id for perm in theirs],
    )
    assert not result.supported and "too many targets" in result.details
    assert len(game.players[0].hand) == 2 and not alexi.tapped
    assert len(game.players[1].battlefield) == 2


def test_w1g3_jolrael_animates_only_the_target_players_lands(set_pool):
    """"All lands target player controls become 3/3 creatures until end of
    turn. They're still lands." The seat is announced (the picker asks for a
    player), the sweep reads it, and cleanup ends it."""
    lea = set_pool("LEA")
    forest = lea["Forest"]
    spec = _w1g3_spec(set_pool, "Jolrael, Empress of Beasts")
    assert spec["kind"] == "player"

    game, (_, my_forest), (f1, f2, bears) = _w1g3_game(
        [set_pool("PCY")["Jolrael, Empress of Beasts"], forest],
        [forest, forest, lea["Grizzly Bears"]],
        hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Jolrael, Empress of Beasts", target_player_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)

    for land in (f1, f2):
        assert land.is_creature and land.has_type("land")
        assert (land.effective_power, land.effective_toughness) == (3, 3)
    assert not my_forest.is_creature, "the activator's own land is not swept"
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert not f1.is_creature and f1.has_type("land")


def test_w1g3_mageta_destroys_every_other_creature_through_regeneration(set_pool):
    """"Destroy all creatures except for Mageta. Those creatures can't be
    regenerated." The exemption is the source itself, and a regeneration
    shield already up does not save a Drudge Skeletons."""
    lea = set_pool("LEA")
    game, (mageta, bears), (skeletons, giant) = _w1g3_game(
        [set_pool("PCY")["Mageta the Lion"], lea["Grizzly Bears"]],
        [lea["Drudge Skeletons"], lea["Hill Giant"]],
        hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    shield = game.queue_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    resolve_stack(game)

    result = game.queue_permanent_ability(0, "Mageta the Lion")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Mageta the Lion"]
    assert game.players[1].battlefield == []
    assert {c.name for c in game.players[1].graveyard} == {
        "Drudge Skeletons", "Hill Giant",
    }


def test_w1g3_copper_leaf_angel_sacrifices_x_lands_for_x_counters(set_pool):
    """"{T}, Sacrifice X lands: Put X +1/+1 counters on this creature." The X
    announced is both the payment and the effect; a named land is honoured."""
    spec = _w1g3_spec(set_pool, "Copper-Leaf Angel")
    assert spec["sacrifice_cost"] and spec["kind"] == "land" and spec["announces_x"]
    forest = set_pool("LEA")["Forest"]
    game, (angel, f1, f2, f3), _ = _w1g3_game(
        [set_pool("PCY")["Copper-Leaf Angel"], forest, forest, forest],
    )
    result = game.queue_permanent_ability(
        0, "Copper-Leaf Angel", x_value=2, cost_permanent_ids=[f3.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert not game.is_on_battlefield(f3), "the named land paid"
    assert sum(game.is_on_battlefield(land) for land in (f1, f2)) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Forest"]
    assert (angel.effective_power, angel.effective_toughness) == (4, 4)
    assert angel.tapped


def test_w1g3_copper_leaf_angel_refuses_an_x_the_board_cannot_pay(set_pool):
    """An X larger than the lands there are is an announcement that cannot be
    paid (CR 601.2h) — refused, never clamped, and nothing is spent."""
    forest = set_pool("LEA")["Forest"]
    game, (angel, *_lands), _ = _w1g3_game(
        [set_pool("PCY")["Copper-Leaf Angel"], forest, forest],
    )
    result = game.queue_permanent_ability(0, "Copper-Leaf Angel", x_value=3)
    assert not result.supported and "fewer than the 3 announced" in result.details
    assert len(game.players[0].battlefield) == 3 and not angel.tapped


def test_w1g3_jeweled_spirit_gains_protection_from_artifacts_or_a_colour(set_pool):
    """"Sacrifice two lands: This creature gains protection from artifacts or
    from the color of your choice until end of turn." Two protection abilities,
    one chosen; the colour rides the activation like Knight of Dawn's."""
    lea = set_pool("LEA")
    lands = [lea["Forest"], lea["Mountain"], lea["Forest"]]

    game, (spirit, *_), _ = _w1g3_game([set_pool("PCY")["Jeweled Spirit"], *lands])
    result = game.queue_permanent_ability(0, "Jeweled Spirit")
    assert result.supported, result.details
    resolve_stack(game)
    assert game._protection_qualities(spirit) == {("card_type", "artifact")}
    assert len(game.players[0].battlefield) == 2, "two lands paid"

    game, (spirit, *_), _ = _w1g3_game(
        [set_pool("PCY")["Jeweled Spirit"], *lands], interactive={0},
    )
    result = game.queue_permanent_ability(0, "Jeweled Spirit", mana_color="R")
    assert result.supported, result.details
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)
    assert game._protection_qualities(spirit) == {("color", "R")}

    game.resolve_cleanup_step(0)
    assert game._protection_qualities(spirit) == set()


def test_w1g3_jeweled_spirit_with_one_land_is_refused(set_pool):
    lea = set_pool("LEA")
    game, (spirit, forest), _ = _w1g3_game(
        [set_pool("PCY")["Jeweled Spirit"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Jeweled Spirit")
    assert not result.supported
    assert game.is_on_battlefield(forest)
    assert game._protection_qualities(spirit) == set()


def test_w1g3_keldon_battlewagon_gets_the_tapped_creatures_power(set_pool):
    """"Tap an untapped creature you control: This creature gets +X/+0 until
    end of turn, where X is the power of the creature tapped this way." The
    record of what the cost tapped, read at resolution."""
    lea = set_pool("LEA")
    game, (wagon, giant, bears), _ = _w1g3_game(
        [set_pool("PCY")["Keldon Battlewagon"], lea["Hill Giant"], lea["Grizzly Bears"]],
    )
    result = game.queue_permanent_ability(
        0, "Keldon Battlewagon", cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert giant.tapped and not bears.tapped
    assert (wagon.effective_power, wagon.effective_toughness) == (3, 3)

    result = game.queue_permanent_ability(
        0, "Keldon Battlewagon", cost_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert (wagon.effective_power, wagon.effective_toughness) == (5, 3)

    game.resolve_cleanup_step(0)
    assert wagon.effective_power == 0


def test_w1g3_keldon_battlewagon_cannot_block(set_pool):
    lea = set_pool("LEA")
    game, (bears,), (wagon,) = _w1g3_game(
        [lea["Grizzly Bears"]], [set_pool("PCY")["Keldon Battlewagon"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert not game._can_block_attacker(wagon, bears)
    assert not game.declare_blockers(1, {0: 0})[0]


def test_w1g3_keldon_battlewagon_is_sacrificed_at_end_of_combat(set_pool):
    """"When this creature attacks, sacrifice it at end of combat." — a
    delayed trigger the attack arms, which fires at the end of combat step."""
    game, (wagon,), _ = _w1g3_game([set_pool("PCY")["Keldon Battlewagon"]])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    resolve_stack(game)
    present_through: list[str] = []
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        if game.is_on_battlefield(wagon):
            present_through.append(game.current_step)
        game.advance_combat_phase()
        resolve_stack(game)
    assert "end_of_combat" in present_through, present_through
    assert game.players[1].life == 20, "a 0-power attacker deals nothing"
    assert not game.is_on_battlefield(wagon)
    assert [c.name for c in game.players[0].graveyard] == ["Keldon Battlewagon"]
