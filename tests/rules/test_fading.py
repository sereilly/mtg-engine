"""Fading — CR 702.32.

The keyword's whole content is the two abilities CR 702.32a says it
*represents*, so these tests drive the real entry seam and the real upkeep
rather than calling a handler: what is being checked is that the printed word
puts N fade counters on the permanent as it enters, that each of its
controller's upkeeps takes one off, and that the upkeep which finds none
sacrifices it — the *(N+1)*th, never the Nth.

Every permanent enters through ``_put_permanent_onto_battlefield`` and every
turn starts through ``begin_turn_bookkeeping``, for the reasons
``tests/rules/test_echo.py`` gives one keyword over: a permanent that skipped
the entry path has no counters and no id, and a turn advanced by hand is one the
engine never saw begin.

``engine/fading.py`` documents the rewrite; the per-card tests for the Nemesis
cards that print it are in ``tests/sets/test_nem_*.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.fading import (
    FADING_RULES_TEXT, expand_fading_line, fading_count, is_fading_line,
    unread_fading_line,
)
from engine.grammar import parse_line
from engine.models import CardDefinition, Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle, expand_ability_lines

from tests.helpers import resolve_stack

#: The reminder text every Nemesis fading card is printed with, so a fixture is
#: the line the engine actually receives. It says "remove a fade counter from
#: **it**" and "sacrifice **it**", where the rule says "this permanent" and
#: "the permanent" — the rewrite carries the rule.
_REMINDER = (
    " (This {noun} enters with {word} fade counter{s} on it. At the beginning "
    "of your upkeep, remove a fade counter from it. If you can't, sacrifice it.)"
)

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 7: "seven"}


def _fader(
    name: str, count: int, *, type_line: str = "Creature — Test", extra: str = "",
    printed: str | None = None,
) -> CardDefinition:
    """A permanent whose printed text is "Fading *count*" with its reminder.

    The ingested ``keywords`` field carries "Fading" exactly as Scryfall spells
    it, because that field is what ``oracle.UNSUPPORTED_KEYWORDS`` is matched
    against before any line is classified.
    """
    noun = type_line.split(" — ")[0].split()[-1].lower()
    line = printed if printed is not None else (
        f"Fading {count}"
        + _REMINDER.format(noun=noun, word=_WORDS.get(count, str(count)),
                           s="" if count == 1 else "s")
    )
    text = f"{line}\n{extra}" if extra else line
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="2", toughness="2")
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=("Fading",), produced_mana=(),
        raw=raw,
    )


def _rig() -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game, p1, p2


def _enter(game: Game, seat: int, card: CardDefinition) -> Permanent:
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _upkeep(game: Game, seat: int) -> None:
    """*seat*'s next turn, up to the end of its upkeep with the stack drained."""
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_upkeep(seat)
    resolve_stack(game)


def _fade_trace(game: Game, perm: Permanent, owner: PlayerState, seats) -> list:
    """The fade counters left after each upkeep in *seats* — or ``"gone"``."""
    trace = []
    for seat in seats:
        _upkeep(game, seat)
        on = any(p is perm for p in game.all_permanents())
        trace.append(counters_on(perm, "fade") if on else "gone")
    return trace


# ---------------------------------------------------------------------------
# CR 702.32a — the keyword *is* the two abilities
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.32a")
def test_702_32a_the_keyword_line_becomes_the_two_rules_sentences():
    """"Fading N" *means* two abilities, so the compiler's text — the text every
    other reader of a card's lines starts from — carries two lines and not the
    word."""
    card = _fader("Fader", 3)

    expanded = expand_ability_lines(card.oracle_text, card_name=card.name)

    assert expanded == FADING_RULES_TEXT.format(count="three", noun="counters")
    assert expanded.splitlines() == [
        "This permanent enters with three fade counters on it.",
        "At the beginning of your upkeep, remove a fade counter from this "
        "permanent. If you can't, sacrifice the permanent.",
    ]
    assert "Fading" not in expanded


@pytest.mark.cr("702.32a")
def test_702_32a_fading_one_is_one_counter_in_the_singular():
    """Parallax Dementia's printing, and the sentence the entry reader has to
    read as *one* counter rather than refuse."""
    assert expand_fading_line(_fader("Fader", 1).oracle_text).startswith(
        "This permanent enters with one fade counter on it."
    )


@pytest.mark.cr("702.32a")
def test_702_32a_the_trigger_sacrifices_the_source_and_nothing_else():
    """The rule's last sentence says "sacrifice **the permanent**", and that is
    a back-reference to the source — the same pronoun "the creature" is. The
    compiled step must be ``sacrifice_self``: the forced-sacrifice prompt would
    let its controller give up *any* permanent instead, and keep this one."""
    program = compile_card_oracle(_fader("Fader", 3))

    assert program.supported
    [trigger] = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    remove, branch = trigger.instruction.payload["steps"]
    assert (remove.kind, remove.payload) == (
        "remove_counter_from_self", {"counter": "fade"}
    )
    assert branch.payload["condition"] == {
        "kind": "it_happened", "key": "removed_counter", "negated": True,
    }
    assert [step.kind for step in branch.payload["then"]] == ["sacrifice_self"]


@pytest.mark.cr("702.32a")
@pytest.mark.parametrize("type_line", [
    "Creature — Test", "Artifact", "Enchantment",
])
def test_702_32a_the_permanent_enters_with_n_fade_counters(type_line):
    """The first ability, on each permanent type Nemesis prints it on."""
    game, p1, _ = _rig()

    perm = _enter(game, 0, _fader("Fader", 4, type_line=type_line))

    assert counters_on(perm, "fade") == 4


@pytest.mark.cr("702.32a")
def test_702_32a_fading_three_fades_three_times_and_is_sacrificed_at_the_fourth():
    """A counter leaves at each of its controller's next three upkeeps, and the
    fourth — finding none — sacrifices it. Not the third: the last counter
    leaving is not the sacrifice, the *failure* to remove one is."""
    game, p1, _ = _rig()
    perm = _enter(game, 0, _fader("Fader", 3))

    trace = _fade_trace(game, perm, p1, (1, 0, 1, 0, 1, 0, 1, 0))

    assert trace == [3, 2, 2, 1, 1, 0, 0, "gone"]
    assert [card.name for card in p1.graveyard] == ["Fader"]
    assert any("Fader was sacrificed" in line for line in game.log)


@pytest.mark.cr("702.32a")
def test_702_32a_only_its_controllers_upkeep_fades_it():
    """"At the beginning of **your** upkeep": the opponent's upkeeps are not
    occasions, however many of them pass."""
    game, p1, _ = _rig()
    perm = _enter(game, 0, _fader("Fader", 2))

    assert _fade_trace(game, perm, p1, (1, 1, 1)) == [2, 2, 2]


@pytest.mark.cr("702.32a", "613.1b")
def test_702_32a_a_control_change_moves_the_upkeep_with_the_permanent():
    """"Your" is whoever controls it now (CR 613 layer 2). Taken by the
    opponent, it fades on *their* upkeep and no longer on its owner's — and it
    is still the same counters, which the control change did not reset."""
    game, p1, p2 = _rig()
    perm = _enter(game, 0, _fader("Fader", 3))
    _upkeep(game, 0)
    assert counters_on(perm, "fade") == 2

    game.take_control(perm, 1, source=perm)

    assert _fade_trace(game, perm, p2, (0, 1, 0, 1, 0, 1)) == [2, 1, 1, 0, 0, "gone"]
    assert [card.name for card in p1.graveyard] == ["Fader"], (
        "sacrificed by its controller, it goes to its owner's graveyard"
    )


@pytest.mark.cr("702.32a", "602.2")
def test_702_32a_counters_spent_on_its_own_ability_bring_the_sacrifice_forward():
    """The upkeep removes *a* fade counter, not *its* fade counter: one spent
    paying an activated ability's cost is one the upkeep no longer finds, so a
    fading creature that used its ability dies an upkeep sooner."""
    game, p1, _ = _rig()
    perm = _enter(game, 0, _fader(
        "Fader", 3,
        extra="Remove a fade counter from this creature: This creature gets "
              "+1/+1 until end of turn.",
    ))

    assert game.activate_permanent_ability(0, "Fader").supported
    resolve_stack(game)
    assert counters_on(perm, "fade") == 2
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)

    # Unspent, the same creature would still be on the battlefield after
    # these six upkeeps (3, 2, 2, 1, 1, 0) and gone only at the eighth.
    assert _fade_trace(game, perm, p1, (1, 0, 1, 0, 1, 0)) == [
        2, 1, 1, 0, 0, "gone",
    ]


@pytest.mark.cr("702.32a")
def test_702_32a_an_ability_cannot_spend_a_counter_that_is_not_there():
    """The cost side of the same counters: with none left the ability is
    refused and nothing resolves — a free repeatable ability is the classic
    failure of a counter cost."""
    game, _, _ = _rig()
    perm = _enter(game, 0, _fader(
        "Fader", 1,
        extra="Remove a fade counter from this creature: This creature gets "
              "+1/+1 until end of turn.",
    ))
    assert game.activate_permanent_ability(0, "Fader").supported
    resolve_stack(game)

    refused = game.activate_permanent_ability(0, "Fader")
    resolve_stack(game)

    assert not refused.supported
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)


@pytest.mark.cr("702.32a")
def test_702_32a_the_simulators_turn_shape_fades_it_the_same():
    """``run_ai_simulation`` advances ``Game.turn`` and calls the steps, with
    no bookkeeping call — and the trigger has no window to get wrong, so the
    count is the same there."""
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.turn = 1
    perm = _enter(game, 0, _fader("Fader", 2))

    trace = []
    for seat in (1, 0, 1, 0, 1, 0):
        game.turn += 1
        game.resolve_upkeep(seat)
        resolve_stack(game)
        on = any(p is perm for p in game.all_permanents())
        trace.append(counters_on(perm, "fade") if on else "gone")

    assert trace == [2, 1, 1, 0, 0, "gone"]


@pytest.mark.cr("702.32a")
def test_702_32a_the_creatures_other_abilities_are_untouched():
    """The rewrite replaces one line, not the card."""
    program = compile_card_oracle(_fader(
        "Fader", 3, extra="When this creature enters, you gain 2 life.",
    ))

    assert program.supported
    assert [trig.condition.kind for trig in program.triggered_abilities] == [
        "upkeep_self", "enters_battlefield",
    ]


# ---------------------------------------------------------------------------
# A fading line the rewrite cannot read stays refused *as fading*
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.32a")
@pytest.mark.parametrize("printed", ["Fading X", "Fading", "Fading 14"])
def test_702_32a_an_unreadable_fading_line_leaves_the_card_unsupported(printed):
    """The direction a keyword rewrite has to fail in. An artifact whose
    *other* line compiles would otherwise report supported with its fading
    dropped — a permanent that never fades — which is exactly what Rejuvenation
    Chamber did before the rewrite existed. "Fading 14" is a count the number
    table cannot spell, so the entry sentence could not carry it."""
    card = _fader(
        "Fader", 0, type_line="Artifact", printed=printed,
        extra="{T}: You gain 2 life.",
    )
    assert is_fading_line(printed)
    assert fading_count(printed) is None
    assert unread_fading_line(card.oracle_text) == printed

    program = compile_card_oracle(card)

    assert not program.supported
    assert "fading" in program.reason


@pytest.mark.cr("702.32a")
def test_702_32a_a_sentence_opening_with_the_word_is_not_a_keyword_line():
    """The shape test is wider than the reader but not unbounded: a card
    *named* "Fading …" starting a sentence is not a fading line."""
    assert not is_fading_line("Fading Hope deals 2 damage to any target.")


# ---------------------------------------------------------------------------
# "the permanent" is a back-reference, never a choice
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.32a", "701.21a")
def test_701_21a_the_permanent_at_phrase_end_is_the_source():
    """The generic noun is the same definite back-reference "the creature"
    is, so it reaches ``sacrifice_self`` rather than the forced-sacrifice
    prompt (CR 701.21a: a sacrifice names a permanent you control; this one
    names exactly one)."""
    node = parse_line("Sacrifice the permanent.")

    subject = node.statement.subject
    assert (subject.quantifier, subject.filter.is_source) == ("it", True)


@pytest.mark.cr("701.21a")
def test_701_21a_a_back_reference_with_nothing_bound_refuses_the_line():
    """"Sacrifice **that** permanent" under a trigger that bound nothing used to
    reach the forced-sacrifice prompt with an empty filter — "sacrifice any
    permanent you control", compiling supported. A back-reference names one
    object, so with nothing to name it the line refuses by name instead."""
    card = CardDefinition(
        name="Backref", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="At the beginning of your upkeep, sacrifice that permanent.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Backref", "type_line": "Artifact"},
    )

    program = compile_card_oracle(card)

    assert not program.supported
    assert all(
        trig.instruction is None
        or trig.instruction.kind != "sacrifice_matching_permanent"
        for trig in program.triggered_abilities
    )
