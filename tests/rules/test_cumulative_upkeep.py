"""Cumulative upkeep — CR 702.24.

The keyword's whole content is the triggered ability CR 702.24a says it *is*,
so these tests drive the real upkeep step rather than calling the handler: what
is being checked is that the printed word produces a trigger, that the trigger
escalates its cost with the age counters it puts down, and that a cost the
engine cannot charge refuses the card rather than shipping it for free.

``engine/cumulative_upkeep.py`` documents the rewrite; the per-card tests for
the Ice Age cards that print it are in ``tests/sets/``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _mk(name: str, cost: str, *, extra_text: str = "", type_line: str = "Enchantment") -> CardDefinition:
    """A permanent whose only ability is cumulative upkeep *cost*.

    The ingested ``keywords`` field carries "Cumulative upkeep" exactly as
    Scryfall spells it, because that field is what ``UNSUPPORTED_KEYWORDS``
    used to veto the card on — a fixture that left it out would test a card the
    engine never sees.
    """
    reminder = (
        " (At the beginning of your upkeep, put an age counter on this permanent, "
        "then sacrifice it unless you pay its upkeep cost for each age counter on it.)"
    )
    text = f"Cumulative upkeep {cost}{reminder}"
    if extra_text:
        text = f"{text}\n{extra_text}"
    return _card(name, type_line, text, keywords=("Cumulative upkeep",))


def _card(
    name: str,
    type_line: str,
    oracle_text: str,
    *,
    keywords: tuple[str, ...] = (),
    power: str = "",
    toughness: str = "",
) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if power:
        raw |= {"power": power, "toughness": toughness}
    return CardDefinition(
        name=name,
        mana_cost="{2}",
        cmc=2.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=keywords,
        produced_mana=(),
        raw=raw,
    )


def _forest(name: str = "Forest") -> CardDefinition:
    """A land that taps for {G}.

    Upkeep costs are paid from floating mana *or* by tapping lands during the
    step (``can_pay_upkeep_mana``), and the step empties the pool when it ends
    (CR 500.4) — so a tapped land is the observable that survives the
    resolution, and asserting on leftover floating mana asserts nothing.
    """
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Basic Land — Forest",
        oracle_text="",
        colors=(),
        color_identity=("G",),
        keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land — Forest"},
    )


def _game(
    permanent: Permanent,
    *,
    pool: dict[str, int] | None = None,
    lands: int = 0,
) -> tuple[Game, PlayerState]:
    battlefield = [permanent] + [Permanent(card=_forest(f"Forest {i}")) for i in range(lands)]
    p1 = PlayerState(name="P1", battlefield=battlefield, mana_pool=dict(pool or {}), life=20)
    p2 = PlayerState(name="P2", life=20)
    return Game(players=[p1, p2]), p1


def _tapped_lands(player: PlayerState) -> int:
    return sum(1 for perm in player.battlefield if perm.card.primary_type == "land" and perm.tapped)


@pytest.mark.cr("702.24a")
def test_702_24a_the_keyword_line_produces_an_upkeep_trigger():
    """"Cumulative upkeep [cost]" *means* "At the beginning of your upkeep …",
    so the compiled card carries a triggered ability with no printed trigger
    line anywhere on it."""
    program = compile_card_oracle(_mk("Ager", "{1}"))

    assert program.supported
    assert [
        (trig.condition.kind, trig.instruction.kind)
        for trig in program.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]


@pytest.mark.cr("702.24a")
def test_702_24a_first_upkeep_places_one_counter_and_charges_the_cost_once():
    perm = Permanent(card=_mk("Ager", "{1}"))
    game, p1 = _game(perm, lands=3)

    game.resolve_upkeep(0)

    assert counters_on(perm, "age") == 1
    assert perm in p1.battlefield
    assert _tapped_lands(p1) == 1


@pytest.mark.cr("702.24a")
def test_702_24a_the_cost_is_paid_once_for_each_age_counter():
    """"you may pay [cost] for each age counter on it" — and the counter this
    resolution places counts, because 702.24a puts it down first."""
    perm = Permanent(card=_mk("Ager", "{1}"))
    game, p1 = _game(perm, lands=6)

    game.resolve_upkeep(0)  # 1 counter -> {1}
    assert _tapped_lands(p1) == 1
    for land in p1.battlefield:
        land.tapped = False

    game.resolve_upkeep(0)  # 2 counters -> {2}
    assert counters_on(perm, "age") == 2
    assert _tapped_lands(p1) == 2
    assert perm in p1.battlefield


@pytest.mark.cr("702.24a")
def test_702_24a_a_coloured_cost_escalates_by_pip():
    perm = Permanent(card=_mk("Ager", "{U}"))
    game, p1 = _game(perm, pool={"U": 1})

    game.resolve_upkeep(0)  # one counter, {U}
    assert perm in p1.battlefield

    p1.mana_pool["U"] = 1  # a second {U} would be needed for two counters
    game.resolve_upkeep(0)
    assert perm not in p1.battlefield, "{U}{U} is not covered by one floating {U}"


@pytest.mark.cr("702.24a")
def test_702_24a_unpaid_cumulative_upkeep_sacrifices_the_permanent():
    perm = Permanent(card=_mk("Ager", "{U}"))
    game, p1 = _game(perm)

    game.resolve_upkeep(0)

    assert perm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Ager"]


@pytest.mark.cr("702.24a")
def test_702_24a_partial_payment_is_not_allowed():
    """"Partial payments aren't allowed" — a player holding one of the two
    mana the second upkeep asks for pays **none** of it and sacrifices."""
    perm = Permanent(card=_mk("Ager", "{1}{U}"))
    game, p1 = _game(perm, lands=4)  # four {G} lands, no blue anywhere

    game.resolve_upkeep(0)

    assert perm not in p1.battlefield
    assert _tapped_lands(p1) == 0, "nothing is spent when the whole cost cannot be paid"


@pytest.mark.cr("702.24a")
def test_702_24a_the_prompt_quotes_the_cost_this_upkeep_will_ask_for():
    """The decision is offered before the trigger resolves, so the counter it is
    about to place has to be in the quoted number — otherwise a player is shown
    one cost and charged another."""
    perm = Permanent(card=_mk("Ager", "{1}"))
    game, p1 = _game(perm, lands=4)

    first = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Ager")
    assert first["mana"] == {"generic": 1}

    game.resolve_upkeep(0)
    assert perm in p1.battlefield
    second = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Ager")
    assert second["mana"] == {"generic": 2}


@pytest.mark.cr("702.24a")
def test_702_24a_declining_the_offer_sacrifices_even_when_the_cost_is_affordable():
    """The payment is a "may" — a player who can pay and says no sacrifices."""
    perm = Permanent(card=_mk("Ager", "{1}"))
    game, p1 = _game(perm, lands=3)

    game.resolve_upkeep(0, human_choices={"Ager": False})

    assert perm not in p1.battlefield
    assert _tapped_lands(p1) == 0


@pytest.mark.cr("702.24b")
def test_702_24b_two_instances_each_trigger_and_each_counts_every_counter():
    """"If a permanent has multiple instances of cumulative upkeep, each
    triggers separately. However, the age counters are not connected to any
    particular ability; each … will count the total number of age counters on
    the permanent at the time that ability resolves."

    So two instances of "{1}" on one upkeep cost {1} then {2}, not {1} twice."""
    card = _card(
        "Twice Aged",
        "Enchantment",
        "Cumulative upkeep {1}, cumulative upkeep {1}",
        keywords=("Cumulative upkeep",),
    )
    program = compile_card_oracle(card)
    assert len(program.triggered_abilities) == 2

    perm = Permanent(card=card)
    game, p1 = _game(perm, lands=5)

    game.resolve_upkeep(0)

    assert counters_on(perm, "age") == 2
    assert perm in p1.battlefield
    assert _tapped_lands(p1) == 3, "{1} for the first instance, {2} for the second"


@pytest.mark.cr("702.24a")
def test_702_24a_a_cost_the_engine_cannot_charge_refuses_the_card():
    """CR 702.24a admits any cost, and this engine can only charge mana. A
    "Pay 2 life" upkeep must leave the card **unsupported** — admitting it would
    ship a permanent whose upkeep is silently free, which is a strictly better
    card than the one printed."""
    card = _card(
        "Blood Ager",
        "Enchantment",
        "Cumulative upkeep—Pay 2 life.",
        keywords=("Cumulative upkeep",),
    )
    program = compile_card_oracle(card)

    assert not program.supported
    assert not [
        trig for trig in program.triggered_abilities
        if trig.instruction and trig.instruction.kind == "cumulative_upkeep"
    ]


@pytest.mark.cr("702.24a")
def test_702_24a_the_keyword_rides_a_line_with_other_keywords():
    """The rewrite reads one comma-joined keyword line, so a creature printing
    "Flying, cumulative upkeep {U}" keeps both."""
    card = _card(
        "Winged Ager",
        "Creature — Illusion",
        "Flying, cumulative upkeep {U}",
        keywords=("Flying", "Cumulative upkeep"),
        power="4",
        toughness="4",
    )
    program = compile_card_oracle(card)

    assert program.supported
    assert len(program.triggered_abilities) == 1
    perm = Permanent(card=card)
    assert perm.has_keyword("flying")
