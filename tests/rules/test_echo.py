"""Echo — CR 702.30.

The keyword's whole content is the triggered ability CR 702.30a says it *is*,
so these tests drive the real turn structure rather than calling a handler:
what is being checked is that the printed word produces a trigger, that
CR 702.30a's intervening-if is true at exactly one of the controller's upkeeps
and false at every later one, and that a control change starts the window
again.

**Every permanent here enters through the entry seam**
(``_put_permanent_onto_battlefield``) rather than being appended to a
battlefield list, and every turn is started through ``begin_turn_bookkeeping``
except where a test says otherwise on purpose. Neither is ceremony: a permanent
that skipped the entry path has no id and no layer contribution, and a turn
advanced by hand is a turn the rest of the engine never saw begin.

The condition itself is deliberately robust to both — it is answered from a
record the *upkeep step* writes, not from a moment-of-arrival stamp against a
clock — and two tests below drive exactly that: one runs the AI simulator's
turn shape, which advances no seat ordinal at all, and one lets a permanent
arrive part-way through an upkeep.

``engine/echo.py`` documents the rewrite; the per-card tests for the Urza's
Saga cards that print it are in ``tests/sets/test_usg_creatures.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.echo import ECHO_RULES_TEXT, echo_cost, expand_echo_line, is_echo_line
from engine.grammar import parse_line
from engine.grammar.errors import GrammarError
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle, expand_ability_lines

from tests.helpers import resolve_stack

#: The reminder text every Urza-block echo card is printed with, so the
#: fixtures below are the line the engine actually receives rather than a
#: tidied version of it — the parenthetical is what ``echo_cost`` has to get
#: past, and it names a cost ("its echo cost") the sentence cannot use.
_ECHO_REMINDER = (
    " (At the beginning of your upkeep, if this came under your control since "
    "the beginning of your last upkeep, sacrifice it unless you pay its echo "
    "cost.)"
)


def _echo_creature(name: str, cost: str, *, extra: str = "") -> CardDefinition:
    """A 2/2 whose only ability is echo *cost*.

    The ingested ``keywords`` field carries "Echo" exactly as Scryfall spells
    it, because that field is what ``oracle.UNSUPPORTED_KEYWORDS`` is matched
    against before any line is classified — a fixture that left it out would
    test a card the engine never sees.
    """
    text = f"Echo {cost}{_ECHO_REMINDER}"
    if extra:
        text = f"{text}\n{extra}"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=text,
        colors=(),
        color_identity=(),
        keywords=("Echo",),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": "2", "toughness": "2"},
    )


def _forest(index: int) -> CardDefinition:
    """A land that taps for {G}.

    An upkeep cost is paid from floating mana *or* by tapping lands during the
    step (``can_pay_upkeep_mana``), and the step empties the pool when it ends
    (CR 500.4) — so a tapped land is the observable that survives, exactly as
    the cumulative-upkeep tests next door note.
    """
    name = f"Forest {index}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land — Forest",
        oracle_text="", colors=(), color_identity=("G",), keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land — Forest"},
    )


def _rig(*, lands: tuple[int, int] = (0, 0)) -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=_forest(i)) for i in range(lands[0])],
    )
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=_forest(100 + i)) for i in range(lands[1])],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _begin(game: Game, seat: int) -> None:
    """Start *seat*'s next turn the way ``Game.start_turn`` and the web layer
    both do — ``Game.turn`` forward, then the turn's bookkeeping.

    Written out rather than calling ``start_turn``, which would run the untap,
    upkeep and draw steps in one breath and leave no room to inspect the offer
    between them.
    """
    game.turn += 1
    game.begin_turn_bookkeeping(seat)


def _untap_lands(player: PlayerState) -> None:
    for perm in player.battlefield:
        if perm.card.primary_type == "land":
            perm.tapped = False


def _tapped_lands(player: PlayerState) -> int:
    return sum(
        1 for perm in player.battlefield
        if perm.card.primary_type == "land" and perm.tapped
    )


def _offers(game: Game, seat: int) -> list[str]:
    return [choice["card_name"] for choice in game.get_upkeep_pay_triggers(seat)]


# ---------------------------------------------------------------------------
# CR 702.30a — the keyword *is* the ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.30a")
def test_702_30a_the_keyword_line_becomes_the_rules_sentence():
    """"Echo [cost]" *means* the sentence, so the compiler's text — the text
    every other reader of a card's lines starts from — carries the sentence and
    not the word."""
    card = _echo_creature("Echoer", "{1}{G}")

    expanded = expand_ability_lines(card.oracle_text, card_name=card.name)

    assert expanded == ECHO_RULES_TEXT.format(cost="{1}{G}")
    assert "Echo" not in expanded


@pytest.mark.cr("702.30a")
def test_702_30a_the_keyword_line_produces_a_gated_upkeep_trigger():
    """The compiled card carries a triggered ability with no printed trigger
    line anywhere on it — and the ability carries CR 603.4's gate, which is the
    half that makes it echo rather than an every-upkeep tax."""
    program = compile_card_oracle(_echo_creature("Echoer", "{1}{G}"))

    assert program.supported
    assert [
        (trig.condition.kind, trig.instruction.kind)
        for trig in program.triggered_abilities
    ] == [("upkeep_self", "upkeep_pay_or_sacrifice_self")]
    assert program.triggered_abilities[0].instruction.payload["intervening_if"] == {
        "kind": "came_under_your_control_since_your_last_upkeep"
    }


@pytest.mark.cr("702.30a")
def test_702_30a_the_first_upkeep_after_it_arrives_charges_the_echo_cost():
    """A creature that came under your control on your last turn owes echo at
    your next upkeep, and paying keeps it."""
    game, p1, _ = _rig(lands=(4, 0))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    assert _offers(game, 0) == ["Echoer"]
    game.resolve_upkeep(0)

    assert perm in p1.battlefield
    assert _tapped_lands(p1) == 2, "{1}{G} is two lands"


@pytest.mark.cr("702.30a")
def test_702_30a_a_creature_that_has_survived_an_upkeep_never_echoes_again():
    """The intervening-if is false from the second upkeep on, so the ability
    does not trigger — and the *prompt* has to agree, or a player is asked for
    a cost nothing will charge."""
    game, p1, _ = _rig(lands=(4, 0))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)
    _untap_lands(p1)

    _begin(game, 1)
    _begin(game, 0)
    assert _offers(game, 0) == []
    game.resolve_upkeep(0)

    assert perm in p1.battlefield
    assert _tapped_lands(p1) == 0, "nothing is charged once echo is done"


@pytest.mark.cr("702.30a")
def test_702_30a_a_creature_that_arrived_on_an_opponents_turn_still_echoes_once():
    """The window is "since the beginning of your last upkeep", not "this
    turn": a permanent that arrived while an opponent was taking their turn
    owes echo at the controller's next upkeep exactly as one cast on their own
    turn does."""
    game, p1, _ = _rig(lands=(4, 0))
    game.begin_turn_bookkeeping(0)
    _begin(game, 1)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 0)
    assert _offers(game, 0) == ["Echoer"]
    game.resolve_upkeep(0)
    assert perm in p1.battlefield

    _untap_lands(p1)
    _begin(game, 1)
    _begin(game, 0)
    assert _offers(game, 0) == []


@pytest.mark.cr("702.30a")
def test_702_30a_an_unpaid_echo_sacrifices_the_creature():
    game, p1, _ = _rig(lands=(0, 0))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)

    assert perm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Echoer"]


@pytest.mark.cr("702.30a", "118.3")
def test_702_30a_partial_payment_is_not_allowed():
    """A player holding one of the two mana pays **none** of it (CR 118.3) and
    the creature is sacrificed — the same reading cumulative upkeep takes, and
    the reason both go through ``can_pay_upkeep_mana`` rather than a pool read
    that would waive the generic half."""
    game, p1, _ = _rig(lands=(1, 0))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)

    assert perm not in p1.battlefield
    assert _tapped_lands(p1) == 0, "nothing is spent when the whole cost cannot be paid"


@pytest.mark.cr("702.30a")
def test_702_30a_a_declined_offer_sacrifices_a_creature_that_could_have_paid():
    """The offer is a choice, so an affordable echo the controller declines is
    still a sacrifice — the ``human_choices`` channel the pay-or-consequence
    registry has always read."""
    game, p1, _ = _rig(lands=(4, 0))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0, human_choices={"Echoer": False})

    assert perm not in p1.battlefield
    assert _tapped_lands(p1) == 0


@pytest.mark.cr("702.30a")
def test_702_30a_echo_is_charged_on_its_controllers_upkeep_only():
    """"At the beginning of **your** upkeep": the opponent's upkeep is not an
    occasion for it, and the seat check must not be the only thing keeping it
    quiet there."""
    game, p1, p2 = _rig(lands=(4, 4))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    assert _offers(game, 1) == []
    game.resolve_upkeep(1)

    assert perm in p1.battlefield
    assert _tapped_lands(p1) == 0
    assert _tapped_lands(p2) == 0


@pytest.mark.cr("702.30a", "613.1")
def test_702_30a_a_control_change_starts_the_window_again():
    """CR 702.30a says "came under your **control**", not "entered the
    battlefield". A creature that has already paid its echo owes a fresh one to
    whoever takes it — and the seat it owes it to is the new controller, whose
    own window the stamp names."""
    game, p1, p2 = _rig(lands=(4, 4))
    game.begin_turn_bookkeeping(0)
    perm = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, perm, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)          # the one echo P1 owes
    _untap_lands(p1)
    _begin(game, 1)
    _begin(game, 0)
    assert _offers(game, 0) == [], "P1's echo is finished"

    game.take_control(perm, 1, source=perm)

    _begin(game, 1)
    assert _offers(game, 1) == ["Echoer"], "the new controller owes a fresh echo"
    game.resolve_upkeep(1)
    assert perm in p2.battlefield
    assert _tapped_lands(p2) == 2

    _untap_lands(p2)
    _begin(game, 0)
    _begin(game, 1)
    assert _offers(game, 1) == [], "and only one"


@pytest.mark.cr("702.30a", "400.7")
def test_702_30a_a_creature_that_leaves_and_returns_owes_echo_again():
    """CR 400.7: what returns is a new object, so it has just come under your
    control — which is what the stamp says without anything having to remember
    the old one."""
    game, p1, _ = _rig(lands=(8, 0))
    game.begin_turn_bookkeeping(0)
    card = _echo_creature("Echoer", "{1}{G}")
    first = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, first, None)

    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)
    _untap_lands(p1)
    game.remove_from_battlefield(first)

    second = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, second, None)
    _begin(game, 1)
    _begin(game, 0)

    assert _offers(game, 0) == ["Echoer"]
    game.resolve_upkeep(0)
    assert second in p1.battlefield


@pytest.mark.cr("702.30a")
def test_702_30a_the_creatures_other_abilities_are_untouched():
    """The rewrite replaces one line, not the card. Crater Hellion's shape:
    echo plus a trigger of its own."""
    program = compile_card_oracle(_echo_creature(
        "Echoer", "{1}{G}",
        extra="When this creature enters, it deals 2 damage to each opponent.",
    ))

    assert program.supported
    assert [trig.condition.kind for trig in program.triggered_abilities] == [
        "upkeep_self", "enters_battlefield",
    ]


@pytest.mark.cr("603.4")
def test_603_4_the_condition_survives_its_second_check_on_the_stack():
    """CR 603.4 checks an intervening-if **twice** — when the ability would
    trigger, and again as it resolves — and an ordinary upkeep trigger resolves
    in the priority window *after* the step has finished running.

    So this is the test the record's shape exists for. The upkeep step writes
    "this is the first of my upkeeps you have seen" at the top of the step, once
    and never again while the controller is unchanged, which is what lets the
    fire check and the resolution re-check read one answer. A record written as
    the step *ended* would pass every echo test in this file — echo resolves
    inline, inside the registry — and silently answer False for every card that
    ever prints this condition on an ordinary effect.

    One draw, at the one upkeep, over six of them.
    """
    drawer = CardDefinition(
        name="Drawer", mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text=(
            "At the beginning of your upkeep, if this permanent came under "
            "your control since the beginning of your last upkeep, draw a card."
        ),
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Drawer", "type_line": "Creature — Test",
             "power": "2", "toughness": "2"},
    )
    game, p1, _p2 = _rig()
    p1.library = [_forest(i) for i in range(20)]
    game.begin_turn_bookkeeping(0)
    game._put_permanent_onto_battlefield(0, Permanent(card=drawer), None)

    drawn = []
    for seat in (1, 0, 1, 0, 1, 0):
        _begin(game, seat)
        before = len(p1.hand)
        game.resolve_upkeep(seat)
        resolve_stack(game)
        drawn.append(len(p1.hand) - before)

    assert drawn == [0, 1, 0, 0, 0, 0]


@pytest.mark.cr("702.30a")
def test_702_30a_echo_is_right_in_a_driver_that_never_advances_the_seat_ordinal():
    """The engine has three turn drivers and they do not agree about what a
    turn boundary is: ``Game.start_turn`` and the web layer both call
    ``begin_turn_bookkeeping``, and ``run_ai_simulation`` open-codes the step
    calls and increments ``Game.turn`` alone — so ``seat_turn_counts`` never
    moves there.

    That is why the record is not a seat-turn ordinal like the two stamps
    beside it in ``turn_state``. Under the simulator's clock an ordinal
    comparison reads True at every upkeep, which is an echo creature taxed for
    the rest of the game — worse than the card, and silent.

    This drives the simulator's shape deliberately: no bookkeeping call, only
    ``Game.turn``.
    """
    game, p1, _p2 = _rig(lands=(6, 0))
    game.turn = 1
    permanent = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, permanent, None)
    assert game.seat_turn_counts == {}, "the simulator advances no seat ordinal"

    charged = []
    for seat in (1, 0, 1, 0):
        game.turn += 1
        for perm in p1.battlefield:
            perm.tapped = False
        game.resolve_upkeep(seat)
        charged.append(_tapped_lands(p1))

    assert charged == [0, 2, 0, 0], "echo is due once, at P1's first upkeep after it arrived"
    assert permanent in p1.battlefield


@pytest.mark.cr("702.30a")
def test_702_30a_a_permanent_that_arrives_during_the_upkeep_owes_the_next_one():
    """The step stamps the permanents it finds when it begins, so one that
    arrives later in the same step has still seen none of your upkeeps — and
    owes echo at the next one rather than having been quietly aged by an upkeep
    it was not present for."""
    game, p1, _p2 = _rig(lands=(4, 0))
    game.begin_turn_bookkeeping(0)
    _begin(game, 1)
    _begin(game, 0)
    game.resolve_upkeep(0)

    late = Permanent(card=_echo_creature("Echoer", "{1}{G}"))
    game._put_permanent_onto_battlefield(0, late, None)

    for perm in p1.battlefield:
        perm.tapped = False
    _begin(game, 1)
    _begin(game, 0)
    assert _offers(game, 0) == ["Echoer"]
    game.resolve_upkeep(0)
    assert late in p1.battlefield
    assert _tapped_lands(p1) == 2


# ---------------------------------------------------------------------------
# CR 702.30b — the errata'd cost is read, never re-derived
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.30b")
@pytest.mark.parametrize("cost", ["{G}", "{1}{G}", "{2}{W}{W}", "{4}{R}{R}"])
def test_702_30b_the_printed_echo_cost_is_the_one_charged(cost):
    """Urza-block cards were errata'd to an echo cost equal to their mana cost,
    and the ingested text already carries the errata. So the cost is *read*
    off the printed line — a fixture whose mana cost is empty still charges
    what its echo line says, which is what proves nothing re-derives it from
    ``CardDefinition.mana_cost``."""
    card = _echo_creature("Echoer", cost)
    assert card.mana_cost == ""

    program = compile_card_oracle(card)

    assert echo_cost(f"Echo {cost}{_ECHO_REMINDER}") == cost
    assert program.triggered_abilities[0].source_line.endswith(f"pay {cost}.")


@pytest.mark.cr("702.30b")
def test_702_30b_an_echo_line_with_no_cost_leaves_the_card_unsupported():
    """The pre-errata printing, and the direction a keyword rewrite has to
    fail in: the shape test still calls it an echo line, the reader refuses it,
    and the card is reported unsupported naming the clause rather than entering
    play with an echo nothing charges."""
    assert is_echo_line("Echo")
    assert echo_cost("Echo") is None
    assert expand_echo_line("Echo") is None

    program = compile_card_oracle(_costless_echo())

    assert not program.supported
    assert "Echo" in program.reason


def _costless_echo() -> CardDefinition:
    return CardDefinition(
        name="Costless Echoer", mana_cost="", cmc=0.0,
        type_line="Creature — Test", oracle_text="Echo",
        colors=(), color_identity=(), keywords=("Echo",), produced_mana=(),
        raw={"name": "Costless Echoer", "type_line": "Creature — Test",
             "power": "2", "toughness": "2"},
    )


# ---------------------------------------------------------------------------
# CR 603.4 — the condition as a grammar production, and what it refuses
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.4")
def test_603_4_the_condition_is_a_production_and_not_an_echo_only_trick():
    """The clause reads under any effect, which is the difference between a
    parser production and a keyword-shaped special case."""
    node = parse_line(
        "At the beginning of your upkeep, if this permanent came under your "
        "control since the beginning of your last upkeep, draw a card."
    )

    assert node.intervening_if.__class__.__name__ == "CameUnderControlSinceLastUpkeep"


@pytest.mark.cr("603.4")
@pytest.mark.parametrize("window", [
    "since the beginning of your last turn",
    "since your last upkeep",
    "this turn",
])
def test_603_4_a_different_window_refuses_rather_than_borrowing_this_one(window):
    """The stamp answers one window. A sentence naming another has to fail the
    line — a window silently widened is an echo that never stops, and a
    narrowed one is an ability that never fires."""
    with pytest.raises(GrammarError):
        parse_line(
            "At the beginning of your upkeep, if this permanent came under "
            f"your control {window}, sacrifice it unless you pay {{1}}{{G}}."
        )


@pytest.mark.cr("603.4")
def test_603_4_came_under_your_control_with_no_window_refuses():
    """"Came under your control" on its own is true of everything you have ever
    controlled. Consuming the prefix and dropping the rest is the partial match
    this grammar refuses by construction."""
    with pytest.raises(GrammarError):
        parse_line(
            "At the beginning of your upkeep, if this permanent came under "
            "your control, sacrifice it unless you pay {1}{G}."
        )
