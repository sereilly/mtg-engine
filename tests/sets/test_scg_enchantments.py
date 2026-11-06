"""Scourge enchantments, Auras included.

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
# Decree of Silence: its opponent-cast trigger compiled to nothing until this
# round ("If there are three or more depletion counters on this enchantment"
# was a condition no production read), and its cycle trigger counters a
# spell on the stack.
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, bob_hand, *, active=1):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_depletion(permanent):
    return permanent.metadata.get("depletion_counters", 0)


def test_w1g2_decree_of_silence_counters_each_opponent_spell_and_dies_at_three(set_pool):
    """"Whenever an opponent casts a spell, counter that spell and put a
    depletion counter on this enchantment. If there are three or more
    depletion counters on this enchantment, sacrifice it." Three spells are
    countered; the fourth resolves."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [], [lea["Lightning Bolt"], lea["Lightning Bolt"],
                       lea["Grizzly Bears"], lea["Grizzly Bears"]],
    )
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])

    for count, name in enumerate(("Lightning Bolt", "Lightning Bolt", "Grizzly Bears"), 1):
        assert game.queue_from_hand(1, name, target_player_index=0).supported
        assert game.stack[-1].card.name == "Decree of Silence"
        _w1g2_drain(game)
        assert alice.life == 20
        if count < 3:
            assert _w1g2_depletion(decree) == count
            assert game.is_on_battlefield(decree)
    assert not game.is_on_battlefield(decree)
    assert [c.name for c in alice.graveyard] == ["Decree of Silence"]
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt", "Lightning Bolt", "Grizzly Bears"]

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g2_drain(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_w1g2_decree_of_silence_leaves_its_controllers_spells_alone(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [lea["Lightning Bolt"]], [], active=0)
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    _w1g2_drain(game)
    assert bob.life == 17 and _w1g2_depletion(decree) == 0


def test_w1g2_two_decrees_of_silence_counter_that_spell_and_no_bystander(set_pool):
    """"Counter **that spell**" is the spell the trigger fired on, found by
    identity (CR 603.3's trigger sits above it). Alice bolts Bob; Bob bolts
    back in response and both Decrees trigger. The first counters Bob's bolt;
    the second finds it gone and must not counter Alice's bolt, now the top
    spell — but it still takes its depletion counter."""
    lea, scg = set_pool("LEA"), set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [lea["Lightning Bolt"]], [lea["Lightning Bolt"]], active=0,
    )
    first = _w1g2_put(game, 0, scg["Decree of Silence"])
    second = _w1g2_put(game, 0, scg["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Lightning Bolt", "Decree of Silence", "Decree of Silence",
    ]
    _w1g2_drain(game)
    assert alice.life == 20, "Bob's bolt was countered"
    assert bob.life == 17, "Alice's bolt was not"
    assert (_w1g2_depletion(first), _w1g2_depletion(second)) == (1, 1)


def test_w1g2_decree_of_silence_cycled_counters_target_spell(set_pool):
    """"When you cycle this card, you may counter target spell." Cycled in
    response; the trigger resolves before the cycling draw (2022-12-08)."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Silence"]], [lea["Lightning Bolt"]],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.activate_from_hand(0, "Decree of Silence").supported
    trigger = game.stack[-1]
    assert trigger.ability_text.startswith("When you cycle this card")
    assert trigger.target_stack_item is not None or trigger.targets_chosen
    _w1g2_drain(game)
    assert alice.life == 20
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt"]
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_silence_cycles_with_no_spell_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The draw still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Silence"]], [])
    assert game.activate_from_hand(0, "Decree of Silence").supported
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

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
#
# Grip of Chaos: "Whenever a spell or ability is put onto the stack, if it has
# a single target, reselect its target at random. (Select from among all legal
# targets.)" A new event (`Game.announce_put_onto_stack`), CR 603.4's
# intervening-if over CR 115.9a's count, and Psychic Battle's change of the
# event's object made by the seeded RNG.
import random as _w1g8_random

from engine import Game as _W1G8Game
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_table(set_pool, hand=(), *, bob_hand=(), interactive=False):
    lea = set_pool("LEA")
    alice = _W1G8PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G8PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G8Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g8_put(game, seat, card):
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g8_drain(game):
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_grip_triggers(game):
    return [
        item for item in game.stack
        if item.card.name == "Grip of Chaos" and item.ability_kind == "triggered"
    ]


def _w1g8_bolt_outcome(game, alice, bob, bears, elves):
    """Where the Bolt's 3 damage went."""
    if bears.damage_marked == 3:
        return "bears"
    if elves.damage_marked == 3:
        return "elves"
    if alice.life == 17:
        return "alice"
    if bob.life == 17:
        return "bob"
    return None


def test_w1g8_grip_of_chaos_reselects_a_single_target_among_every_legal_one(set_pool):
    """Each seeded game puts Grip's trigger above a Lightning Bolt aimed at
    Bob's Bears; as it resolves, the Bolt's target is drawn from every legal
    target — both players and both creatures — and the original is one of the
    answers (2004-10-04: "it may still choose the original one"). Over a dozen
    seeds every answer is legal, the original is kept at least once and the
    Bolt is moved at least once; one seed always gives one answer."""
    lea = set_pool("LEA")
    outcomes = []
    for seed in range(12):
        game, alice, bob = _w1g8_table(set_pool, [lea["Lightning Bolt"]])
        _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        elves = _w1g8_put(game, 0, lea["Llanowar Elves"])
        assert game.queue_from_hand(
            0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        # The Bolt keeps its target until the trigger resolves (2004-10-04).
        assert len(_w1g8_grip_triggers(game)) == 1
        assert game.stack[0].target_permanent_id == [bears.permanent_id]
        _w1g8_random.seed(seed)
        _w1g8_drain(game)
        outcomes.append(_w1g8_bolt_outcome(game, alice, bob, bears, elves))
    assert None not in outcomes
    assert "bears" in outcomes
    assert set(outcomes) - {"bears"}

    again = []
    for _ in range(2):
        game, alice, bob = _w1g8_table(set_pool, [lea["Lightning Bolt"]])
        _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        elves = _w1g8_put(game, 0, lea["Llanowar Elves"])
        game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
        _w1g8_random.seed(7)
        _w1g8_drain(game)
        again.append(_w1g8_bolt_outcome(game, alice, bob, bears, elves))
    assert again[0] == again[1]


def test_w1g8_grip_of_chaos_keeps_a_target_with_no_other_legal_one(set_pool):
    """2004-10-04: "If there are no other legal targets, it keeps its
    target." Terror's only legal creature is the one it named."""
    lea = set_pool("LEA")
    game, _alice, _bob = _w1g8_table(set_pool, [lea["Terror"]])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_drain(game)
    assert not game.is_on_battlefield(bears)
    assert any("has no other legal target" in line for line in game.log)


def test_w1g8_grip_of_chaos_reselects_among_the_targets_legal_as_it_resolves(set_pool):
    """2004-10-04: "You determine the new target when this ability resolves,
    at which time the set of legal targets may have changed." Alice gains
    shroud in response (Gilded Light, which targets nothing and so is not
    reselected itself): no seed sends Bob's Bolt at her."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    for seed in range(8):
        game, alice, bob = _w1g8_table(
            set_pool, [scg["Gilded Light"]], bob_hand=[lea["Lightning Bolt"]],
        )
        _w1g8_put(game, 0, scg["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        assert game.queue_from_hand(0, "Gilded Light").supported
        assert len(_w1g8_grip_triggers(game)) == 1
        _w1g8_random.seed(seed)
        _w1g8_drain(game)
        assert alice.life == 20, seed
        assert bears.damage_marked == 3 or bob.life == 17


def test_w1g8_grip_of_chaos_ignores_what_has_no_single_target(set_pool):
    """An untargeted spell, a spell with two targets and Grip's own trigger do
    not set it off (CR 603.4: the condition is false, so it never triggers) —
    which is also why two Grips do not loop. One target of an "up to two"
    does."""
    lea = set_pool("LEA")
    lead_astray = set_pool("JUD")["Lead Astray"]
    game, _alice, _bob = _w1g8_table(set_pool, [lea["Wrath of God"], lead_astray, lead_astray])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    elves = _w1g8_put(game, 1, lea["Llanowar Elves"])
    assert game.queue_from_hand(0, "Wrath of God").supported
    assert _w1g8_grip_triggers(game) == []
    game.stack.clear()
    assert game.queue_from_hand(
        0, "Lead Astray", target_permanent_ids=[bears.permanent_id, elves.permanent_id],
    ).supported
    assert _w1g8_grip_triggers(game) == []
    game.stack.clear()
    assert game.queue_from_hand(
        0, "Lead Astray", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert len(_w1g8_grip_triggers(game)) == 2
    _w1g8_drain(game)
    assert game.stack == []


def test_w1g8_grip_of_chaos_reaches_an_activated_ability(set_pool):
    """"…a spell **or ability**": Prodigal Sorcerer's ping is put onto the
    stack with one target and is reselected like a spell."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g8_table(set_pool)
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    _w1g8_put(game, 0, lea["Prodigal Sorcerer"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id], ability_index=0,
    ).supported
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_random.seed(1)
    _w1g8_drain(game)
    assert any("Prodigal Sorcerer" in line and "Grip of Chaos" in line for line in game.log)
    assert bears.damage_marked + (20 - alice.life) + (20 - bob.life) + sum(
        perm.damage_marked for perm in game.controlled_by(0)
    ) == 1


def test_w1g8_grip_of_chaos_trigger_can_be_stifled(set_pool):
    """The reselection is a triggered ability on the stack (the third
    ruling), so Stifle counters it and the Bolt keeps its target. Stifle has a
    single target itself, so it sets Grip off too — and the only other legal
    target for it is nothing, so that trigger keeps it."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    game, _alice, bob = _w1g8_table(
        set_pool, [lea["Lightning Bolt"]], bob_hand=[scg["Stifle"]],
    )
    _w1g8_put(game, 0, scg["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    # Bottom-first: the Bolt is 0, Grip's trigger 1.
    assert game.queue_from_hand(1, "Stifle", target_stack_index=1).supported
    assert len(_w1g8_grip_triggers(game)) == 2
    _w1g8_random.seed(0)
    _w1g8_drain(game)
    assert bears.damage_marked == 3
    assert any("Stifle countered Grip of Chaos" in line for line in game.log)


def test_w1g8_grip_of_chaos_hears_a_trigger_whose_target_a_person_chose(set_pool):
    """A triggered ability is put onto the stack once its controller names
    its target (CR 603.3d): Decree of Savagery's cycle trigger, aimed by a
    person, sets Grip off only after the answer — and Grip moves the four
    counters among the creatures."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    game, _alice, _bob = _w1g8_table(set_pool, [scg["Decree of Savagery"]], interactive=True)
    _w1g8_put(game, 0, scg["Grip of Chaos"])
    mine = _w1g8_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g8_put(game, 1, lea["Llanowar Elves"])
    assert game.activate_from_hand(0, "Decree of Savagery").supported
    assert game.pending_choice_of("trigger_target", 0) is not None
    assert _w1g8_grip_triggers(game) == []
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=theirs.permanent_id,
    )
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_random.seed(2)
    _w1g8_drain(game)
    assert any("Grip of Chaos" in line and "Decree of Savagery" in line for line in game.log)

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
