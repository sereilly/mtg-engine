"""Scourge instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Decree of Savagery's cycle trigger (a printed number of +1/+1 counters on one
# target, refused until this round), and the cycling instants on W1G2's drive
# list (Spark Spray, Wipe Clean).
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, *, interactive=False):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g2_decree_of_savagery_counters_each_creature_you_control(set_pool):
    lea = set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Decree of Savagery").supported
    _w1g2_drain(game)
    assert _w1g2_pt(mine) == (6, 6) and _w1g2_pt(theirs) == (2, 2)


def test_w1g2_decree_of_savagery_cycled_puts_four_counters_on_the_target(set_pool):
    """"When you cycle this card, you may put four +1/+1 counters on target
    creature." Compiled to nothing until this round (the count was refused as
    "variable"); the target is chosen as the trigger goes on the stack, by a
    person here, and it may be any creature."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Savagery"]], interactive=True,
    )
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Llanowar Elves"])

    assert game.activate_from_hand(0, "Decree of Savagery").supported
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None
    offered = {t.get("permanent_id") for t in prompt.data["targets"]}
    assert {mine.permanent_id, theirs.permanent_id} <= offered
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=theirs.permanent_id,
    )
    game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, [c.kind for c in game.pending_choices]
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g2_drain(game)
    assert _w1g2_pt(theirs) == (5, 5)
    assert _w1g2_pt(mine) == (2, 2)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_savagery_cycles_with_no_creature_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The trigger is removed (CR 603.3d); the draw
    still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    assert game.activate_from_hand(0, "Decree of Savagery").supported
    assert len(game.stack) == 1
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert any("no legal target" in line for line in game.log)


def test_w1g2_spark_spray_deals_one_to_any_target(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Spark Spray"]] * 2)
    elves = _w1g2_put(game, 1, lea["Llanowar Elves"])
    assert game.cast_from_hand(0, "Spark Spray", target_permanent_ids=[elves.permanent_id]).supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(elves)
    assert game.cast_from_hand(0, "Spark Spray", target_player_index=1).supported
    _w1g2_drain(game)
    assert bob.life == 19


def test_w1g2_wipe_clean_exiles_target_enchantment(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Wipe Clean"]])
    moon = _w1g2_put(game, 1, lea["Bad Moon"])
    assert game.cast_from_hand(0, "Wipe Clean", target_permanent_ids=[moon.permanent_id]).supported
    _w1g2_drain(game)
    assert not game.is_on_battlefield(moon)
    assert [c.name for c in bob.exile] == ["Bad Moon"] and bob.graveyard == []


def test_w1g2_the_cycling_instants_cycle(set_pool):
    for name in ("Spark Spray", "Wipe Clean"):
        game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")[name]])
        assert game.activate_from_hand(0, name).supported, name
        _w1g2_drain(game)
        assert [c.name for c in alice.hand] == ["Plains"], name

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# "The greatest mana value among permanents you control" as an amount
# (Accelerated Mutation, Reward the Faithful) and as a comparison's bound
# (Dispersal Shield): one aggregate (`ast.GreatestManaValueAmong`,
# `evaluate_count`'s ``greatest_mana_value``), counted at resolution. Reward
# the Faithful is also "any number of target players each …", the Wheel and
# Deal seat loop with the caster admitted.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from engine.targeting import spec_roles as _w1g4_spec_roles
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_table(set_pool, hand, *, players=2):
    lea = set_pool("LEA")
    seats = [
        _W1G4PlayerState(
            name=f"P{seat + 1}", library=[lea["Island"]] * 8,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(players)
    ]
    game = _W1G4Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    _w1g4_resolve_stack(game)
    return permanent


def test_w1g4_accelerated_mutation_pumps_by_the_greatest_mana_value_you_control(set_pool):
    """Shivan Dragon (6) is the greatest among the caster's permanents; the
    opponent's Lord of the Pit (7) is not one "you control"."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Accelerated Mutation"]])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    _w1g4_put(game, 0, lea["Shivan Dragon"])
    _w1g4_put(game, 1, lea["Lord of the Pit"])
    assert game.cast_from_hand(
        0, "Accelerated Mutation", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (8, 8), game.log


def test_w1g4_the_greatest_mana_value_is_counted_as_the_spell_resolves(set_pool):
    """CR 608.2: the count is taken at resolution, so a Shivan Dragon that
    leaves in response leaves the Bears' own 2."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Accelerated Mutation"]])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    dragon = _w1g4_put(game, 0, lea["Shivan Dragon"])
    assert game.queue_from_hand(
        0, "Accelerated Mutation", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert len(game.stack) == 1
    game.remove_from_battlefield(dragon)
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4), game.log


def _w1g4_shield(set_pool, spell, *, x_value=None, mine=("Grizzly Bears",)):
    """Seat 1 casts *spell* (at seat 0 where it targets a player); seat 0
    answers with Dispersal Shield over a board of *mine*, with a Shivan Dragon
    on seat 1's side that is not "you control"."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Dispersal Shield"]])
    game.players[1].hand.append(lea[spell])
    for name in mine:
        _w1g4_put(game, 0, lea[name])
    _w1g4_put(game, 1, lea["Shivan Dragon"])
    announced = {} if "Creature" in lea[spell].type_line else {"target_player_index": 0}
    if x_value is not None:
        announced["x_value"] = x_value
    assert game.queue_from_hand(1, spell, **announced).supported
    assert game.queue_from_hand(0, "Dispersal Shield", target_stack_index=0).supported
    _w1g4_resolve_stack(game)
    return game


@_w1g4_pytest.mark.parametrize("spell, x_value, mine, countered", [
    ("Lightning Bolt", None, ("Grizzly Bears",), True),     # 1 <= 2
    ("Hill Giant", None, ("Grizzly Bears",), False),        # 4 > 2
    ("Hill Giant", None, ("Grizzly Bears", "Hill Giant"), True),  # 4 <= 4
    # CR 202.3e: on the stack an X in the cost is the announced value.
    ("Fireball", 1, ("Grizzly Bears",), True),              # {X}{R}, X=1: 2
    ("Fireball", 2, ("Grizzly Bears",), False),             # X=2: 3
    # Nothing controlled is a greatest of 0: even a one-drop is greater.
    ("Lightning Bolt", None, (), False),
])
def test_w1g4_dispersal_shield_counters_by_the_two_mana_values(
    set_pool, spell, x_value, mine, countered,
):
    """"Counter target spell if its mana value is less than or equal to the
    greatest mana value among permanents you control." A condition on the
    effect (CR 608.2c), not a targeting restriction: every row is a legal
    announcement, and a row not countered resolves as if the Shield had not
    been cast."""
    game = _w1g4_shield(set_pool, spell, x_value=x_value, mine=mine)
    their_graveyard = [card.name for card in game.players[1].graveyard]
    if countered:
        assert their_graveyard == [spell], game.log
        assert game.players[0].life == 20
        assert any("countered by Dispersal Shield" in line for line in game.log)
    elif "Creature" in set_pool("LEA")[spell].type_line:
        assert spell in [p.card.name for p in game.controlled_by(1)], game.log
    else:
        assert game.players[0].life == 20 - (x_value or 3), game.log


def test_w1g4_dispersal_shield_offers_every_spell(set_pool):
    """The clause does not narrow the target (CR 601.2c reads "target spell"):
    a spell the Shield will not counter is still one the picker offers."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Dispersal Shield"]])
    game.players[1].hand.append(lea["Craw Wurm"])
    assert game.queue_from_hand(1, "Craw Wurm").supported
    spec = game.cast_target_spec(0, set_pool("SCG")["Dispersal Shield"])
    assert spec["requires_target"]
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Craw Wurm"]


@_w1g4_pytest.mark.parametrize("named", [[0], [1], [0, 1], [1, 2], [0, 1, 2], []])
def test_w1g4_reward_the_faithful_heals_exactly_the_named_players(set_pool, named):
    """"Any number of target players each gain life equal to the greatest mana
    value among permanents you control." The caster may be named (CR 115.1a),
    zero players is a legal announcement, and **every** named player gains the
    *caster's* greatest — the third seat's Shivan Dragon (6) is not a
    permanent "you" control, whoever the loop is on (CR 109.5)."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]], players=3)
    _w1g4_put(game, 0, lea["Hill Giant"])        # 4: the caster's greatest
    _w1g4_put(game, 1, lea["Grizzly Bears"])
    _w1g4_put(game, 2, lea["Shivan Dragon"])
    assert game.cast_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    _w1g4_resolve_stack(game)
    assert [player.life for player in game.players] == [
        24 if seat in named else 20 for seat in range(3)
    ], game.log


@_w1g4_pytest.mark.parametrize("named", [[0, 0], [1, 0]])
def test_w1g4_reward_the_faithful_names_each_player_once(set_pool, named):
    """CR 115.3: one player once per printed "target"; and the set is announced
    once, in seat order, rather than once per ordering."""
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]])
    assert not game.cast_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Reward the Faithful"]


def test_w1g4_reward_the_faithful_skips_a_player_that_became_illegal(
    set_pool, catalog_by_name,
):
    """CR 608.2b: of two named players, the one that gained shroud is not
    affected and the other still gains."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]])
    _w1g4_put(game, 0, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": 0}, {"seat": 1}],
    ).supported
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=catalog_by_name["Ivory Mask"]), None,
    )
    _w1g4_resolve_stack(game)
    assert [player.life for player in game.players] == [22, 20], game.log


def test_w1g4_reward_the_faithful_announces_a_chain_of_player_roles(set_pool):
    """The picker offers a seat per role, the caster's included, each a later
    seat than the last — what the client and the gates read."""
    card = set_pool("SCG")["Reward the Faithful"]
    roles = _w1g4_spec_roles(_w1g4_cast_spec(card, _w1g4_compile(card)))
    assert roles and all(role.get("kind") == "player" for role in roles)
    assert not any(role.get("opponents_only") for role in roles)
    assert all(role.get("optional_role") for role in roles)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
