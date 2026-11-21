"""Soulshift — CR 702.46.

CR 702.46a *defines* the keyword as one triggered ability: "When this
permanent is put into a graveyard from the battlefield, you may return target
Spirit card with mana value N or less from your graveyard to your hand."
``engine/soulshift.py`` rewrites the printed line into that sentence; these
tests drive the trigger through a real death and the real stack: the target
is chosen as the trigger is put on the stack (CR 603.3d) with the creature
already in the graveyard, the narrowing (a Spirit, mana value N or less) is
the picker's and the resolution's, "you may" is the resolution's offer, and
CR 702.46b's instances trigger separately. The per-card tests for the
Champions of Kamigawa soulshift creatures are in
``tests/sets/test_chk_creatures.py`` (W1G3's section).
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.soulshift import (SOULSHIFT_RULES_TEXT, expand_soulshift_line,
                              is_soulshift_line, soulshift_count,
                              unread_soulshift_line)

from tests.helpers import _nosick, settle

_REMINDER = (
    " (When this creature dies, you may return target Spirit card with mana "
    "value {n} or less from your graveyard to your hand.)"
)


def _card(name: str, cost: int, type_line: str, text: str = "",
          power: str = "2", toughness: str = "2") -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return CardDefinition(
        name=name, mana_cost="{%d}" % cost if cost else "", cmc=float(cost),
        type_line=type_line, oracle_text=text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _soulshifter(name: str, cost: int, *counts: int) -> CardDefinition:
    return _card(
        name, cost, "Creature — Spirit",
        "\n".join(f"Soulshift {n}" + _REMINDER.format(n=n) for n in counts),
    )


def _spirit(name: str, cost: int) -> CardDefinition:
    return _card(name, cost, "Creature — Spirit")


_DOOM = _card("Doom Test", 0, "Instant", "Destroy target creature.")


def _rig(source: CardDefinition, graveyard, *, interactive=()) -> tuple[Game, Permanent]:
    perm = _nosick(Permanent(card=source))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], graveyard=list(graveyard),
                    hand=[_DOOM], library=[_card("Filler", 0, "Land")] * 10),
        PlayerState(name="P2", library=[_card("Filler", 0, "Land")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game, perm


def _kill(game: Game, perm: Permanent) -> None:
    assert game.cast_from_hand(0, "Doom Test", target_permanent_ids=[perm.permanent_id]).supported


@pytest.mark.cr("702.46a")
def test_the_rewrite_is_the_rules_text_with_the_printed_n():
    printed = "Soulshift 4" + _REMINDER.format(n=4)
    assert is_soulshift_line(printed)
    assert soulshift_count(printed) == 4
    assert expand_soulshift_line(printed) == SOULSHIFT_RULES_TEXT.format(count=4)
    assert expand_ability_lines("Flying\n" + printed) == (
        "Flying\nWhen this permanent is put into a graveyard from the battlefield, "
        "you may return target Spirit card with mana value 4 or less from your "
        "graveyard to your hand."
    )
    # A sentence mentioning the word is not the keyword line.
    assert not is_soulshift_line("Creatures with soulshift get +1/+1.")


@pytest.mark.cr("702.46a")
def test_a_soulshift_line_the_rewrite_cannot_read_keeps_the_card_unsupported():
    """"Soulshift X" has no N to write, and an artifact whose other line
    compiles would otherwise report supported with the keyword dropped."""
    card = _card(
        "Unread Test", 3, "Artifact",
        "{T}: You gain 1 life.\nSoulshift X",
    )
    assert unread_soulshift_line(expand_ability_lines(card.oracle_text)) == "Soulshift X"
    program = compile_card_oracle(card)
    assert not program.supported
    assert "soulshift" in program.reason


@pytest.mark.cr("702.46a", "603.3d", "603.10a")
def test_the_target_is_a_spirit_card_of_mana_value_n_or_less_chosen_after_the_death():
    """The trigger is a leaves-the-battlefield ability (CR 603.10a) put on the
    stack after the death, so the target is chosen from the graveyard as it is
    then: only a Spirit card of mana value N or less is offered."""
    game, perm = _rig(
        _soulshifter("Shifter Test", 5, 3),
        [_spirit("Spirit Three", 3), _spirit("Spirit Four", 4),
         _card("Bear Two", 2, "Creature — Bear"), _card("Arcane Two", 2, "Instant — Arcane")],
        interactive=(0,),
    )
    _kill(game, perm)
    asked = settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Spirit Three"]
    spot = asked.data["targets"][0]
    assert game.confirm_trigger_target(0, seat=spot["seat"], graveyard_index=spot["graveyard_index"])
    settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert [c.name for c in game.players[0].hand] == ["Spirit Three"]
    assert "Shifter Test" in [c.name for c in game.players[0].graveyard]


@pytest.mark.cr("702.46a")
def test_you_may_decline_the_return():
    game, perm = _rig(_soulshifter("Shifter Test", 5, 3), [_spirit("Spirit Two", 2)])
    _kill(game, perm)
    settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=False),
    })
    assert game.players[0].hand == []
    assert "Spirit Two" in [c.name for c in game.players[0].graveyard]


@pytest.mark.cr("702.46a")
def test_a_spirit_whose_mana_value_is_at_most_n_may_return_itself():
    """The creature is in the graveyard when its trigger's target is chosen,
    so one that answers its own narrowing is a legal target (no Champions of
    Kamigawa card can: each one's mana value exceeds its N)."""
    game, perm = _rig(_soulshifter("Self Shifter", 2, 2), [])
    _kill(game, perm)
    settle(game)
    assert [c.name for c in game.players[0].hand] == ["Self Shifter"]


@pytest.mark.cr("603.3d")
def test_with_no_spirit_card_to_name_the_trigger_is_removed():
    game, perm = _rig(
        _soulshifter("Shifter Test", 5, 3),
        [_spirit("Spirit Four", 4), _card("Bear Two", 2, "Creature — Bear")],
    )
    _kill(game, perm)
    settle(game)
    assert game.players[0].hand == []
    assert any("removed from the stack" in line for line in game.log), game.log[-6:]


@pytest.mark.cr("702.46b")
def test_each_instance_triggers_separately():
    game, perm = _rig(
        _soulshifter("Twice Shifter", 6, 3, 2),
        [_spirit("Spirit Three", 3), _spirit("Spirit One", 1)],
    )
    _kill(game, perm)
    settle(game)
    assert sorted(c.name for c in game.players[0].hand) == ["Spirit One", "Spirit Three"]
    assert sum("triggered (died)" in line for line in game.log) == 2, game.log


@pytest.mark.cr("608.2b", "702.46a")
def test_a_target_that_leaves_the_graveyard_in_response_returns_nothing(set_pool):
    """Respond to the trigger: exile its target from the graveyard with Coffin
    Purge before it resolves, and the return finds no legal target."""
    game, perm = _rig(
        _soulshifter("Shifter Test", 5, 3),
        [_spirit("Spirit Three", 3)],
        interactive=(0,),
    )
    purge = set_pool("ODY")["Coffin Purge"]
    game.players[0].hand.append(purge)
    _kill(game, perm)
    asked = settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target"
    spot = asked.data["targets"][0]
    assert game.confirm_trigger_target(0, seat=spot["seat"], graveyard_index=spot["graveyard_index"])
    trigger = game.stack[-1]
    assert trigger.ability_text.startswith("When this permanent is put into a graveyard")
    result = game.cast_from_hand(
        0, "Coffin Purge", target_player_index=0, target_graveyard_indices=[spot["graveyard_index"]],
    )
    assert result.supported, result
    settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].exile] == ["Spirit Three"]
