"""CR 603.3c / CR 700.2b — a modal triggered ability chooses its mode, and that
mode's targets, **as it is put on the stack**.

The rule is explicit about the moment, and the moment is the whole point. This
engine used to choose a trigger's mode at *resolution*: by then nothing collects
a target, so a mode reading "target player" had no picker in front of it and
`engine/oracle.py` refused every card printing one rather than admit an ability
that would run against a target nobody chose. Four earlier rounds diagnosed that
and each correctly declined to half-build it.

The three things the rule asks for, and that this file holds:

* the mode is chosen at the push, before anything can respond (CR 700.2b);
* the mode's targets are chosen in the same announcement (CR 603.3d routes to
  CR 601.2c, and CR 115.8 lets each mode target differently);
* a mode with no legal target **can't be chosen** (CR 700.2b), and an ability
  with no choosable mode is *removed from the stack* rather than resolving into
  a no-op — a different observable state, since nothing responds to it and
  nothing counts it as having resolved.

The cards here are built in the test rather than taken from the pool on
purpose: Relic Bind's two modes both target a player, and a player is never
absent, so the pool cannot exercise the empty case at all.
"""

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _r30_modal_aura(name: str, *bullets: str) -> CardDefinition:
    """An Aura whose becomes-tapped trigger offers *bullets* as its modes."""
    text = "\n".join(
        ["Enchant artifact", "Whenever enchanted artifact becomes tapped, choose one —"]
        + [f"• {bullet}" for bullet in bullets]
    )
    return CardDefinition(
        name=name, mana_cost="{1}{U}", cmc=2.0, type_line="Enchantment — Aura",
        oracle_text=text, colors=("U",), color_identity=("U",), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Enchantment - Aura"},
    )


def _r30_artifact(name: str = "Trinket") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Artifact", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _r30_board(aura_card: CardDefinition, *, extra_artifacts: int = 0):
    """Seat 0 controls the Aura; seat 1 controls the artifact it enchants."""
    aura = Permanent(card=aura_card)
    host = Permanent(card=_r30_artifact("Host"))
    p1 = PlayerState(name="A", battlefield=[aura])
    p2 = PlayerState(name="B", battlefield=[host])
    for index in range(extra_artifacts):
        p2.battlefield.append(Permanent(card=_r30_artifact(f"Spare {index}")))
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    attach_aura(aura, host)
    return game, p1, p2, aura, host


@pytest.mark.cr("700.2b", "603.3c")
def test_the_mode_is_chosen_as_the_ability_goes_on_the_stack():
    """Not at resolution. The ability is on the stack with its mode still
    unchosen for exactly as long as the prompt is unanswered, and the prompt is
    owed the instant the object arrives — nobody receives priority in between."""
    card = _r30_modal_aura("Probe Bind", "Target player gains 1 life.", "Destroy target artifact.")
    assert compile_card_oracle(card).supported
    game, _p1, _p2, _aura, host = _r30_board(card)

    game.become_tapped(host)

    assert [item.card.name for item in game.stack] == ["Probe Bind"]
    pending = game.pending_choices_of("mode_choice", 0)
    assert len(pending) == 1, "the mode is owed at the push, not at resolution"
    assert pending[0].data["_trigger_item"] is game.stack[-1]
    assert game.stack[-1].chosen_mode_index is None

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=0, target={"seat": 1})
    assert game.stack[-1].chosen_mode_index == 0


@pytest.mark.cr("603.3d", "601.2c", "115.8")
def test_the_mode_and_its_target_are_one_announcement():
    """CR 603.3d sends the rest of the process through CR 601.2c, so the target
    is chosen with the mode. Each mode may target something different
    (CR 115.8), which is why the candidates hang off the mode and not off the
    ability."""
    card = _r30_modal_aura("Probe Bind", "Destroy target artifact.", "Target player gains 1 life.")
    game, _p1, p2, _aura, host = _r30_board(card, extra_artifacts=1)

    game.become_tapped(host)
    options = game.pending_choices_of("mode_choice", 0)[0].data["_options"]
    assert [option["spec"]["kind"] for option in options] == ["artifact", "player"]

    spare = next(perm for perm in p2.battlefield if perm.card.name == "Spare 0")
    assert game.resolve_pending_choice(
        "mode_choice", 0, mode_index=0, target={"permanent_id": spare.permanent_id},
    )
    item = game.stack[-1]
    assert item.target_permanent_id == spare.permanent_id

    game.resolve_top_of_stack()
    assert [perm.card.name for perm in p2.battlefield] == ["Host"], (
        "the chosen artifact was destroyed, not the one that happened to sit "
        "in the same battlefield slot"
    )


@pytest.mark.cr("700.2b")
def test_a_mode_with_no_legal_target_is_not_offered():
    """"If one of the modes would be illegal (due to an inability to choose
    legal targets, for example), that mode can't be chosen." It is absent from
    the offered list rather than offered and refused, because "can't be chosen"
    is a statement about the announcement, not about its outcome."""
    card = _r30_modal_aura(
        "Probe Bind", "Destroy target creature.", "Target player gains 1 life.",
    )
    game, _p1, _p2, _aura, host = _r30_board(card)

    game.become_tapped(host)

    choice = game.pending_choices_of("mode_choice", 0)[0]
    assert choice.data["labels"] == ["Target player gains 1 life"], (
        "there is no creature on either battlefield, so the destroy mode "
        "cannot be chosen at all"
    )
    assert [option["index"] for option in choice.data["_options"]] == [1], (
        "the offered entry keeps its *printed* position, so the mode it runs "
        "is the one whose label was shown"
    )


@pytest.mark.cr("700.2b", "603.3c")
def test_an_ability_with_no_choosable_mode_leaves_the_stack():
    """"If no mode is chosen, the ability is removed from the stack." It does
    not resolve into a no-op: an ability that resolved would have been a thing
    to respond to and a thing the log records resolving."""
    card = _r30_modal_aura(
        "Probe Bind", "Destroy target creature.", "Tap target creature.",
    )
    game, _p1, _p2, _aura, host = _r30_board(card)

    game.become_tapped(host)

    assert game.stack == []
    assert game.pending_choices_of("mode_choice", 0) == []
    assert any("no mode could be chosen" in line for line in game.log)


@pytest.mark.cr("700.2b")
def test_an_answer_naming_an_unoffered_target_is_refused():
    """The picker and the answer path read one candidate list. An answer naming
    something that list never held leaves the prompt owed rather than being
    performed — the ability is still mid-announcement, and CR 601.2c has not
    been satisfied."""
    card = _r30_modal_aura(
        "Probe Bind", "Destroy target artifact.", "Target player gains 1 life.",
    )
    game, _p1, _p2, _aura, host = _r30_board(card)

    game.become_tapped(host)

    assert not game.resolve_pending_choice(
        "mode_choice", 0, mode_index=0, target={"permanent_id": 999_999},
    )
    assert game.pending_choices_of("mode_choice", 0), "the prompt is still owed"
    assert game.stack[-1].chosen_mode_index is None


@pytest.mark.cr("700.2b")
def test_a_non_interactive_seat_takes_the_first_offered_mode():
    """The stated policy for every seat this engine does not ask. "Offered"
    rather than "printed": CR 700.2b has already removed the modes whose
    targets could not be chosen, so the default can never land on one."""
    card = _r30_modal_aura(
        "Probe Bind", "Destroy target creature.", "Target player gains 1 life.",
    )
    game, p1, _p2, _aura, host = _r30_board(card)
    game.interactive_seats = set()

    game.become_tapped(host)
    game.resolve_top_of_stack()

    assert p1.life == 21, "the life-gain mode was the only one that could be chosen"


@pytest.mark.cr("700.2b", "603.3")
def test_a_targeted_mode_is_refused_where_the_trigger_never_reaches_the_stack():
    """The gate and the dispatch read one table.

    An enters-the-battlefield trigger is still carried out *inline*, inside the
    resolution of the spell that put the permanent there — a standing
    approximation of CR 603.3. A trigger with no push has no moment at which
    CR 700.2b lets its mode be chosen, so a targeted mode there would reach
    resolution with no picker and run against whatever the cast happened to
    name. The compiler refuses the card instead, reading the same
    ``INLINE_TRIGGER_CONDITIONS`` the inline path selects on — so the day an
    ETB trigger uses the stack, both change together.
    """
    card = CardDefinition(
        name="Probe Boar", mana_cost="{2}{G}", cmc=3.0, type_line="Creature — Boar",
        oracle_text=(
            "When this creature enters, choose one —\n"
            "• Destroy target artifact.\n"
            "• You gain 4 life."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Probe Boar", "type_line": "Creature - Boar", "power": "2",
             "toughness": "2"},
    )

    program = compile_card_oracle(card)

    assert not program.supported
    assert "has no picker" in program.reason
    assert "Destroy target artifact" in program.reason


@pytest.mark.cr("700.2b")
def test_an_untargeted_mode_is_fine_on_that_same_inline_trigger():
    """The refusal is about the *target*, not about the modal head: an inline
    trigger whose modes choose nothing has nothing to pick and works
    (Trufflesnout, which ships)."""
    card = CardDefinition(
        name="Probe Boar", mana_cost="{2}{G}", cmc=3.0, type_line="Creature — Boar",
        oracle_text=(
            "When this creature enters, choose one —\n"
            "• Put a +1/+1 counter on this creature.\n"
            "• You gain 4 life."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Probe Boar", "type_line": "Creature - Boar", "power": "2",
             "toughness": "2"},
    )

    assert compile_card_oracle(card).supported
