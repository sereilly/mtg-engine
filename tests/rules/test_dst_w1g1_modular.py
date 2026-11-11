"""Modular — CR 702.43.

CR 702.43a *defines* the keyword as two abilities: "This permanent enters with
N +1/+1 counters on it" and "When this permanent is put into a graveyard from
the battlefield, you may put a +1/+1 counter on target artifact creature for
each +1/+1 counter on this permanent." ``engine/modular.py`` rewrites the
printed line into those two sentences; these tests drive what each one does
through the real entry seam, a real death and the real trigger, and what the
rewrite refuses. CR 702.43b's "each one works separately" is two printed lines.

Fixtures print the keyword with no ingested ``keywords`` field, so "has
modular" is answered off the printed line the way a copy's or a fixture's is.
The per-card tests for the eleven Arcbound creatures are in
``tests/sets/test_dst_artifacts.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.modular import (MODULAR_RULES_TEXT, expand_modular_line,
                            is_modular_line, modular_count,
                            unread_modular_line)
from engine.models import CardDefinition, Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle, expand_ability_lines

from tests.helpers import settle


def _modular(name: str, *lines: str, type_line: str = "Artifact Creature — Test") -> CardDefinition:
    """A 0/0 artifact creature printing *lines* (each "Modular N" with the
    reminder text Darksteel prints)."""
    text = "\n".join(lines)
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "0", "toughness": "0"},
    )


_REMINDER = (
    " (This creature enters with {word} +1/+1 counter{s} on it. When it dies, "
    "you may put its +1/+1 counters on target artifact creature.)"
)


def _line(count: int, word: str) -> str:
    return f"Modular {count}" + _REMINDER.format(word=word, s="" if count == 1 else "s")


def _rig(*, interactive=()) -> Game:
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.begin_turn_bookkeeping(0)
    return game


def _enter(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    settle(game)
    return permanent


def _kill(game: Game, permanent: Permanent) -> None:
    """A death through the state-based check (CR 704.5f): enough -1/-1 counters
    to take it to 0 toughness."""
    game.place_pt_counters(permanent, "-1/-1", permanent.effective_toughness)


@pytest.mark.cr("702.43a")
def test_the_keyword_line_becomes_the_two_abilities_it_represents():
    printed = _line(3, "three")
    assert modular_count(printed) == 3 and is_modular_line(printed)
    assert expand_modular_line(printed) == MODULAR_RULES_TEXT.format(
        count="three", noun="counters"
    )
    expanded = expand_ability_lines(f"Flying\n{printed}").splitlines()
    assert expanded == [
        "Flying",
        "This permanent enters with three +1/+1 counters on it.",
        "When this permanent is put into a graveyard from the battlefield, you "
        "may put a +1/+1 counter on target artifact creature for each +1/+1 "
        "counter on this permanent.",
    ]
    program = compile_card_oracle(_modular("Test Modular", printed))
    assert program.supported, program.reason
    assert [t.condition.kind for t in program.triggered_abilities] == ["dies"]


@pytest.mark.cr("702.43a")
def test_a_modular_line_the_rewrite_cannot_read_keeps_the_card_unsupported():
    """"Modular—Sunburst" (a later set's count) is a modular line nothing here
    writes, so the card names it rather than entering as a 0/0 with nothing."""
    card = _modular("Test Sunburst", "Modular—Sunburst")
    assert unread_modular_line(card.oracle_text) == "Modular—Sunburst"
    program = compile_card_oracle(card)
    assert not program.supported
    assert "modular" in program.reason
    assert not is_modular_line("Modular Hope deals 2 damage to any target.")


@pytest.mark.cr("702.43a")
def test_it_enters_with_n_counters_and_passes_them_on_as_it_dies():
    game = _rig()
    dying = _enter(game, 0, _modular("Test Two", _line(2, "two")))
    heir = _enter(game, 0, _modular("Test One", _line(1, "one")))
    assert counters_on(dying, "+1/+1") == 2 and dying.effective_power == 2
    assert game._has_keyword(dying, "modular")

    _kill(game, dying)
    settle(game)

    assert dying not in game.players[0].battlefield
    assert counters_on(heir, "+1/+1") == 3


@pytest.mark.cr("702.43a", "603.10a")
def test_the_count_is_the_one_it_left_the_battlefield_with():
    """A leaves-the-battlefield ability looks back in time (CR 603.10a): the
    counters it gained after entering go, and its 0/0 card in the graveyard
    carries none to read."""
    game = _rig()
    dying = _enter(game, 0, _modular("Test Two", _line(2, "two")))
    heir = _enter(game, 0, _modular("Test One", _line(1, "one")))
    game.place_pt_counters(dying, "+1/+1", 3)

    _kill(game, dying)
    settle(game)

    assert counters_on(heir, "+1/+1") == 6


@pytest.mark.cr("702.43a", "603.3d")
def test_with_no_artifact_creature_to_target_the_trigger_is_removed():
    game = _rig()
    lone = _enter(game, 0, _modular("Test Two", _line(2, "two")))
    bystander = _enter(game, 0, CardDefinition(
        name="Test Bear", mana_cost="", cmc=0.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Test Bear", "power": "2", "toughness": "2"},
    ))

    _kill(game, lone)
    settle(game)

    assert counters_on(bystander, "+1/+1") == 0
    assert any("no legal target (603.3d)" in line for line in game.log)


@pytest.mark.cr("702.43a")
def test_a_player_may_decline_and_may_aim_at_any_artifact_creature():
    """"Target artifact creature" is anybody's, and "you may" is asked as it
    resolves: an interactive seat names the opponent's creature and then
    declines, and nothing moves; the next time it accepts."""
    for accept in (False, True):
        game = _rig(interactive=(0,))
        dying = _enter(game, 0, _modular("Test Two", _line(2, "two")))
        theirs = _enter(game, 1, _modular("Test One", _line(1, "one")))

        _kill(game, dying)
        owed = settle(game, defaults=False)
        assert owed is not None and owed.kind == "trigger_target"
        game.confirm_trigger_target(0, permanent_id=theirs.permanent_id)
        owed = settle(game, defaults=False)
        assert owed is not None and owed.kind == "optional_pay"
        game.confirm_optional_pay(0, accept=accept)
        settle(game)

        assert counters_on(theirs, "+1/+1") == (3 if accept else 1)


@pytest.mark.cr("702.43a")
def test_a_seat_nobody_asks_declines_to_feed_an_opponents_creature():
    """The target is mandatory while one exists, so a seat whose only other
    artifact creature is across the table still names it — and the "may" is
    then declined rather than taken as a gift."""
    game = _rig()
    dying = _enter(game, 1, _modular("Test Two", _line(2, "two")))
    mine = _enter(game, 0, _modular("Test One", _line(1, "one")))

    _kill(game, dying)
    settle(game)

    assert counters_on(mine, "+1/+1") == 1
    assert any("it would help an opponent's permanent" in line for line in game.log)


@pytest.mark.cr("702.43b")
def test_each_instance_enters_and_triggers_separately():
    """Two printed instances: one entry adds both counts, and each death
    trigger counts every +1/+1 counter on the creature — 1 + 2 = 3 each."""
    game = _rig()
    double = _enter(game, 0, _modular(
        "Test Double", _line(1, "one"), _line(2, "two"),
    ))
    heir = _enter(game, 0, _modular("Test One", _line(1, "one")))
    assert counters_on(double, "+1/+1") == 3

    _kill(game, double)
    settle(game)

    assert counters_on(heir, "+1/+1") == 1 + 3 + 3


@pytest.mark.cr("702.43a", "707.2")
def test_a_copy_of_a_modular_creature_has_modular():
    """Sculpting Steel copying an Arcbound Bruiser (CR 707.2's copiable
    values): it enters with three counters, has the word, and dies passing
    them on."""
    from engine.card_loader import load_cards, manifest_set_path

    dst = {c.name: c for c in load_cards(manifest_set_path("DST", include_measured=True))}
    mrd = {c.name: c for c in load_cards(manifest_set_path("MRD"))}
    game = _rig()
    bruiser = _enter(game, 0, dst["Arcbound Bruiser"])
    game.players[0].hand.append(mrd["Sculpting Steel"])
    assert game.cast_from_hand(0, "Sculpting Steel").supported
    settle(game)
    steel = next(p for p in game.players[0].battlefield if p is not bruiser)
    assert steel.effective_card.name == "Arcbound Bruiser"
    assert counters_on(steel, "+1/+1") == 3 and game._has_keyword(steel, "modular")

    _kill(game, steel)
    settle(game)

    assert counters_on(bruiser, "+1/+1") == 6
