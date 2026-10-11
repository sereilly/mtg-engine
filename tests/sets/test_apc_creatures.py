"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game, PlayerState as _w1g5_Player
from engine.models import Permanent as _w1g5_Permanent
from engine.stack_targets import chosen_targets as _w1g5_chosen_targets
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack

_W1G5_REQUIRED = "must be chosen as a target if able"


def _w1g5_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0, interactive=()):
    """Two boards placed and unsick, *active*'s turn begun. Cards are card
    objects; returns ``(game, seat 0's permanents, seat 1's permanents)``."""
    board0 = [_w1g5_Permanent(card=card) for card in mine]
    board1 = [_w1g5_Permanent(card=card) for card in theirs]
    filler = _w1g5_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5_Game(players=[
        _w1g5_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 creatures: the duel


def _w1g5_names(game, seat):
    return [permanent.card.name for permanent in game.controlled_by(seat)]  # W1G5 creatures


def test_standard_bearer_takes_the_bolt_meant_for_anything_else(set_pool):
    """Standard Bearer {1}{W} 1/1 Human Flagbearer: "While an opponent is
    choosing targets as part of casting a spell they control…, that player
    must choose at least one Flagbearer on the battlefield if able."

    Lightning Bolt against a board holding the Bearer: the picker offers the
    Bearer and nothing else, a Bolt at the face, at the Bears, or at nothing is
    refused with the card still in hand, and the Bolt that names the Bearer
    kills it — after which the second Bolt goes where its caster likes."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, _mine, theirs = _w1g5_duel(
        [], [apc["Standard Bearer"], lea["Grizzly Bears"]],
        hand0=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bearer, bears = theirs
    offered = game.cast_target_spec(0, lea["Lightning Bolt"])
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Standard Bearer"]
    assert [entry["id"] for entry in offered["required_targets"]] == [bearer.permanent_id]

    for announcement in (
        {"target_player_index": 1},
        {"target_permanent_ids": [bears.permanent_id]},
        {},
    ):
        refused = game.queue_from_hand(0, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5_REQUIRED in refused.details, refused
        assert "Flagbearer" in refused.details and "Standard Bearer" in refused.details
    assert not game.stack and len(game.players[0].hand) == 2

    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bearer.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[1].graveyard] == ["Standard Bearer"]

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


def test_a_flagbearer_binds_only_an_opponent_who_is_able(set_pool):
    """The three edges of "an opponent … if able". The Bearer's own controller
    casts at what they like; Royal Assassin's "target tapped creature" cannot
    name an untapped Bearer, so it is not bound; and a spell whose only target
    is a player never is."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5_duel(
        [lea["Royal Assassin"]], [apc["Standard Bearer"], lea["Grizzly Bears"]],
        hand0=[lea["Ancestral Recall"]], hand1=[lea["Giant Growth"]],
    )
    bearer, bears = theirs
    # Its controller's own spell.
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    # "Target tapped creature": the untapped Bearer is no legal target.
    bears.tapped = True
    spec = game.activation_target_spec(0, game.battlefield_index_of(mine[0]), ability_index=0)
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert "required_targets" not in spec
    assert game.queue_permanent_ability(
        0, "Royal Assassin", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Standard Bearer"]
    # "Target player draws three cards."
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    assert len(game.players[0].hand) == 3


def test_coalition_honor_guard_binds_an_activation_and_never_a_trigger(set_pool):
    """Coalition Honor Guard {3}{W} 2/4 Human Flagbearer, the same sentence.
    "…or activating an ability they control": Prodigal Sorcerer aimed at the
    face is refused, and a Sorcerer that names nothing has one legal
    announcement and makes it — the Guard takes the damage. "Triggered
    abilities … don't have to target a Flagbearer" (ruling, 2016-06-08):
    Nekrataal's entry trigger destroys the Bears beside it."""
    apc, lea, vis = set_pool("APC"), set_pool("LEA"), set_pool("VIS")
    game, _mine, theirs = _w1g5_duel(
        [lea["Prodigal Sorcerer"]],
        [apc["Coalition Honor Guard"], lea["Grizzly Bears"]],
        hand0=[vis["Nekrataal"]],
    )
    guard, bears = theirs
    refused = game.queue_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert not refused.supported and _W1G5_REQUIRED in refused.details, refused
    assert game.players[1].life == 20 and not game.stack

    assert game.queue_permanent_ability(0, "Prodigal Sorcerer").supported
    targets = _w1g5_chosen_targets(game, game.stack[-1])
    assert [target.permanent_id for target in targets] == [guard.permanent_id]
    _w1g5_resolve_stack(game)
    assert guard.damage_marked == 1 and game.players[1].life == 20

    assert game.queue_from_hand(
        0, "Nekrataal", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Coalition Honor Guard"]
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


def test_any_players_flagbearer_answers_the_requirement(set_pool):
    """"Any player's Flagbearer may be targeted" (ruling, 2016-06-08): with a
    Flagbearer on each side, a Giant Growth its caster may not put on their own
    Bears goes on their own Honor Guard."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5_duel(
        [lea["Grizzly Bears"], apc["Coalition Honor Guard"]], [apc["Standard Bearer"]],
        hand0=[lea["Giant Growth"]],
    )
    bears, guard = mine
    offered = game.cast_target_spec(0, lea["Giant Growth"])["valid_targets"]
    assert sorted(entry["name"] for entry in offered) == [
        "Coalition Honor Guard", "Standard Bearer",
    ]
    refused = game.queue_from_hand(0, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and _W1G5_REQUIRED in refused.details
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[guard.permanent_id]
    ).supported
    assert (guard.effective_power, guard.effective_toughness) == (5, 7)


def test_a_flagbearer_without_its_ability_demands_nothing(set_pool):
    """The requirement is an ability of the Flagbearer, so Humility ("All
    creatures lose all abilities…") turns it off: the Bolt goes to the face
    with the Bearer — still a Flagbearer — sitting there."""
    apc, lea, tmp = set_pool("APC"), set_pool("LEA"), set_pool("TMP")
    game, _mine, theirs = _w1g5_duel(
        [], [apc["Standard Bearer"], tmp["Humility"]], hand0=[lea["Lightning Bolt"]],
    )
    assert theirs[0].has_type("flagbearer")
    assert "required_targets" not in game.cast_target_spec(0, lea["Lightning Bolt"])
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


def test_a_target_chosen_before_the_flagbearer_arrived_stays_chosen(set_pool):
    """The rule is about *choosing* targets. A Bolt already on the stack aimed
    at the Bears is not made illegal by a Bearer that enters in response
    (CR 608.2b re-asks what the spell printed, not what a permanent demanded of
    the announcement), and resolves where it was aimed."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, _mine, theirs = _w1g5_duel([], [lea["Grizzly Bears"]], hand0=[lea["Lightning Bolt"]])
    bears = theirs[0]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    game._put_permanent_onto_battlefield(
        1, _w1g5_Permanent(card=apc["Standard Bearer"]), None
    )
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Standard Bearer"]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_mystic_snake_counters_the_spell_its_caster_named(set_pool):
    """Mystic Snake {1}{G}{U}{U} 2/2, flash: "When this creature enters,
    counter target spell." Two spells are on the stack and the Snake is flashed
    in naming the **lower** one. The named Bolt is countered and the Shock
    above it resolves. The announcement used to be dropped between the cast and
    the trigger, which then countered whatever was on top."""
    apc, lea, sth = set_pool("APC"), set_pool("LEA"), set_pool("STH")
    game, _mine, _theirs = _w1g5_duel(
        hand0=[apc["Mystic Snake"]], hand1=[lea["Lightning Bolt"], sth["Shock"]], active=1,
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    offered = game.cast_target_spec(0, apc["Mystic Snake"])
    assert offered["kind"] == "stack"
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Lightning Bolt", "Shock"]

    bolt = game.stack[0]
    assert game.queue_from_hand(0, "Mystic Snake", target_stack_index=0).supported
    game.resolve_top_of_stack()
    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.target_stack_item is bolt
    assert [t.kind for t in _w1g5_chosen_targets(game, trigger)] == ["stack"]
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 18  # the Shock resolved, the Bolt did not
    assert "Lightning Bolt was countered by Mystic Snake and moved to graveyard" in game.log
    assert _w1g5_names(game, 0) == ["Mystic Snake"]


def test_mystic_snake_with_no_spell_to_counter_loses_its_trigger(set_pool):
    """CR 603.3d: cast into an empty stack, the Snake's trigger has no legal
    target and is removed as it would be put on the stack. A 2/2 with flash and
    nothing else — it used to resolve "with no spell to counter"."""
    apc = set_pool("APC")
    game, _mine, _theirs = _w1g5_duel(hand0=[apc["Mystic Snake"]])
    assert game.cast_target_spec(0, apc["Mystic Snake"])["valid_targets"] == []
    assert game.queue_from_hand(0, "Mystic Snake").supported
    game.resolve_top_of_stack()
    assert not game.stack
    assert (
        "Mystic Snake's triggered ability was removed from the stack: "
        "it has no legal target (603.3d)"
    ) in game.log
    snake = next(iter(game.controlled_by(0)))
    assert (snake.effective_power, snake.effective_toughness) == (2, 2)


def test_a_snake_nobody_cast_chooses_for_itself_and_prefers_an_opponents_spell(set_pool):
    """Put onto the battlefield without being cast, the Snake's trigger chooses
    its target as it goes on the stack (CR 603.3d): with its controller's own
    Giant Growth on top of an opponent's Bolt, the default is the opponent's
    spell, and the Growth resolves."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5_duel(
        [lea["Grizzly Bears"]], hand0=[lea["Giant Growth"]],
        hand1=[lea["Lightning Bolt"]], active=1,
    )
    bears = mine[0]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    bolt = game.stack[0]
    game._put_permanent_onto_battlefield(0, _w1g5_Permanent(card=apc["Mystic Snake"]), None)
    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.target_stack_item is bolt
    assert "Mystic Snake: targets Lightning Bolt" in game.log
    game.resolve_top_of_stack()   # the trigger
    game.resolve_top_of_stack()   # Giant Growth
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    assert not game.stack and game.players[0].life == 20


def test_the_snake_chooses_again_when_the_spell_it_named_has_gone(set_pool):
    """The cast's announcement is a pre-answer to the trigger's own choice and
    has to be one that choice would accept: with the named Bolt countered while
    the Snake waited, the trigger says so and takes the Shock instead."""
    apc, lea, sth = set_pool("APC"), set_pool("LEA"), set_pool("STH")
    game, _mine, _theirs = _w1g5_duel(
        hand0=[apc["Mystic Snake"]], hand1=[lea["Lightning Bolt"], sth["Shock"]], active=1,
    )
    game.queue_from_hand(1, "Shock", target_player_index=0)
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    shock, bolt = game.stack
    assert game.queue_from_hand(0, "Mystic Snake", target_stack_index=1).supported
    game.counter_stack_object(bolt)
    game.resolve_top_of_stack()
    assert (
        "Mystic Snake's triggered ability can't target what was named as it "
        "was cast; it chooses again (603.3d)"
    ) in game.log
    assert game.stack[-1].target_stack_item is shock
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 20

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
