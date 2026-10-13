"""Census: a prompt armed part-way through a resolution holds its object.

Odyssey's wave 1 reported (W1G7, one probe) that a plain "you may" triggered
ability — Confessor's "Whenever a player discards a card, you may gain 1
life." — leaves the stack with its ``optional_pay`` still owed, against
CLAUDE.md's "while a prompt is owed, the game waits" (CR 608.2, CR 117.3b).

**The report was the probe.** It resolved the trigger by calling
``Game.resolve_top_of_stack()`` directly, and that call's default is the
documented headless one: "the object resolves and pops immediately and the
caller drains the prompts deterministically". No path a table takes makes
that call. The three that resolve for one — ``pass_priority``, the step
drain ``_resolve_priority_window`` and ``_settle`` behind ``cast_from_hand``
/ ``activate_permanent_ability`` — each derive ``pause_for_choices`` from
whether anybody is there to wait for, and each holds the object.

So this file is the measurement rather than a fix, and it is here so the
next probe written the same way finds its answer:

* Confessor on the priority path and on the convenience path: held, the
  window refused, released by the last answer;
* the probe's own path, pinned as what it is;
* the registry census the brief asked for. "A kind that refuses every action
  but lets the object leave is a contradiction" — ``holds_priority`` is
  derived from ``blocked_detail``, and the stamp that holds an object is
  written in one place for every kind, so the census asks each registered
  kind whether the two agree. It reads 0 disagreements over every kind in
  the registry, and one kind held by nothing: the notification;
* the two ways an arming site could go round that one place — building a
  ``PendingChoice`` itself, or passing its own ``_stack_item`` — counted in
  the source, with the one stated exception named.
"""

from __future__ import annotations

import ast
from pathlib import Path

from engine import Game, PlayerState
from engine.models import Permanent
from engine.pending_choices import CHOICE_SPECS

ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: A registry that lost its kinds would pass every loop below.
_KINDS_FLOOR = 80


def _confessor_duel(set_pool):
    ody, lea = set_pool("ODY"), set_pool("LEA")
    m21 = set_pool("M21")
    game = Game(players=[
        PlayerState("Caster", library=[lea["Forest"]] * 6, hand=[m21["Mind Rot"]]),
        PlayerState(
            "Victim", library=[lea["Forest"]] * 6,
            hand=[lea["Grizzly Bears"], lea["Forest"]],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._put_permanent_onto_battlefield(0, Permanent(card=ody["Confessor"]), None)
    game.interactive_seats = {0}
    return game


def _both_pass(game):
    first = game.priority_player_index
    if first is None:
        first = game.priority_player_index = 0
        game.priority_pass_count = 0
    result = game.pass_priority(first)
    return game.pass_priority(game.priority_player_index) if result == "passed" else result


def _stack(game) -> list:
    return [(item.card.name, item.resolution_held) for item in game.stack]


# ---------------------------------------------------------------------------
# The reported card, on the paths a table takes
# ---------------------------------------------------------------------------

def test_confessors_offer_holds_its_trigger_on_the_priority_path(set_pool):
    game = _confessor_duel(set_pool)
    assert game.queue_from_hand(0, "Mind Rot", target_player_index=1).supported
    _both_pass(game)                                        # Mind Rot resolves
    game.auto_resolve_pending_choices(only_player_index=1)  # the victim discards
    assert _stack(game) == [("Confessor", False), ("Confessor", False)]

    assert _both_pass(game) == "awaiting_choice"

    # One trigger is mid-resolution and still on the stack; the other has not
    # started. The offer names the object it belongs to.
    assert _stack(game) == [("Confessor", False), ("Confessor", True)]
    (offer,) = game.pending_choices
    assert offer.kind == "optional_pay" and offer.data["_stack_item"] is game.stack[-1]
    assert game.waiting_prompt() is offer
    assert "Confessor ability resolved" not in game.log

    # Passing again does not move it: nobody receives priority (CR 117.3b).
    assert _both_pass(game) == "awaiting_choice"
    assert _stack(game) == [("Confessor", False), ("Confessor", True)]
    assert game.players[0].life == 20

    assert game.confirm_optional_pay(0, accept=True)
    assert game.players[0].life == 21
    assert _stack(game) == [("Confessor", False)]
    assert "Confessor finished resolving" in game.log


def test_confessors_offer_holds_its_trigger_on_the_convenience_path(set_pool):
    """``cast_from_hand`` resolves through ``_settle``, the third caller."""
    game = _confessor_duel(set_pool)
    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    game.auto_resolve_pending_choices(only_player_index=1)
    game._settle()

    assert _stack(game) == [("Confessor", False), ("Confessor", True)]
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.pending_choices[0].data["_stack_item"] is game.stack[-1]


def test_the_headless_call_is_the_one_that_does_not_wait(set_pool):
    """The probe's path, pinned as what it is. ``resolve_top_of_stack()`` with
    no argument is the headless entry point: the object pops, the prompt is
    queued with no object behind it, and the caller drains it. A drive that
    calls it at an interactive table is measuring this, not the game."""
    game = _confessor_duel(set_pool)
    assert game.queue_from_hand(0, "Mind Rot", target_player_index=1).supported
    game.resolve_top_of_stack()
    game.auto_resolve_pending_choices(only_player_index=1)

    while game.stack and game.resolve_top_of_stack():
        pass

    assert game.stack == []
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"] * 2
    assert all("_stack_item" not in choice.data for choice in game.pending_choices)
    # …and the caller's drain is what answers them.
    game.auto_resolve_pending_choices()
    assert game.pending_choices == [] and game.players[0].life == 22


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def test_every_kind_that_blocks_holds_the_object_that_armed_it():
    """For every registered kind: armed while an object resolves, is the
    object recorded on the prompt exactly when the prompt refuses every other
    action? An interactive seat owes each one, so nothing defaults at arm."""
    game = Game(players=[PlayerState("A"), PlayerState("B")])
    game.interactive_seats = {0}
    resolving = object()
    held, carried_on_around = [], []
    for kind, spec in CHOICE_SPECS.items():
        game.pending_choices.clear()
        game.resolving_stack_item = resolving
        try:
            choice = game.arm_pending_choice(kind, 0)
        finally:
            game.resolving_stack_item = None
        assert choice is not None, f"{kind} defaulted for an interactive seat"
        stamped = choice.data.get("_stack_item") is resolving
        assert stamped == spec.holds_priority, (
            f"{kind}: refuses other actions = {spec.blocked_detail is not None}, "
            f"holds the resolving object = {stamped}"
        )
        (held if stamped else carried_on_around).append(kind)

    assert len(CHOICE_SPECS) >= _KINDS_FLOOR, len(CHOICE_SPECS)
    assert len(held) + len(carried_on_around) == len(CHOICE_SPECS)
    # What holds nothing is what blocks nothing: a notification.
    assert all(CHOICE_SPECS[kind].blocked_detail is None for kind in carried_on_around)
    assert "optional_pay" in held and "hand_reveal" in carried_on_around


def _calls(tree, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called == name:
                yield node


def test_one_place_builds_a_prompt_and_one_site_names_its_own_object():
    """The census above asks ``arm_pending_choice``. This asks whether that is
    the only way in: a ``PendingChoice`` built anywhere else, or an arming
    that passes its own ``_stack_item``, would be a prompt the stamp never
    reached."""
    built, own_object, files = [], [], 0
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        files += 1
        relative = path.relative_to(ENGINE).as_posix()
        built += [relative for _ in _calls(tree, "PendingChoice")]
        for call in _calls(tree, "arm_pending_choice"):
            if any(keyword.arg == "_stack_item" for keyword in call.keywords):
                own_object.append(relative)

    assert files >= 150, files
    assert built == ["mixins/stack/choices.py"]
    # Phantasmal Terrain's land type, armed as the Aura enters: the game waits
    # and there is no finished object to hold (the registration says so).
    assert own_object == ["mixins/oracle_instructions.py"]
