"""Per-card tests for Ice Age (ICE).

Conventions: `tests/sets/README.md`. The set starts as one file and splits by
the printed type of the card each test names when it outgrows one.

CR-level tests for the mechanics this set introduced live in `tests/rules/` —
cumulative upkeep is `tests/rules/test_cumulative_upkeep.py`. What belongs here
is the *card*: that this printing compiles, and that its own numbers and text
do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _cu_trigger(card):
    """The cumulative upkeep ability *card* compiles to, or None."""
    return next(
        (
            trig
            for trig in compile_card_oracle(card).triggered_abilities
            if trig.instruction is not None
            and trig.instruction.kind == "cumulative_upkeep"
        ),
        None,
    )


# --- Round 1: cumulative upkeep (CR 702.24) ---


def test_illusionary_wall_carries_its_cumulative_upkeep(set_pool):
    """A creature printing "Cumulative upkeep {U}" alongside defender: the
    keyword line is one line and both halves survive it."""
    wall = set_pool("ICE")["Illusionary Wall"]
    program = compile_card_oracle(wall)

    assert program.supported
    trigger = _cu_trigger(wall)
    assert trigger is not None
    assert trigger.instruction.payload["mana"] == {"U": 1}
    assert Permanent(card=wall).has_keyword("defender")


def test_illusionary_wall_ages_and_is_sacrificed_when_unpaid(set_pool):
    wall = Permanent(card=set_pool("ICE")["Illusionary Wall"])
    p1 = PlayerState(name="P1", battlefield=[wall], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)

    assert counters_on(wall, "age") == 1
    assert wall not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Illusionary Wall"]


def test_mystic_remora_cumulative_upkeep_reaches_an_enchantment(set_pool):
    """The rewrite has to run on the **non-creature** front end too.

    Mystic Remora prints cumulative upkeep beside a trigger the engine cannot
    yet read. The creature loop and the permanent loop are different code, and
    with the rewrite in only the first one this card compiled *supported* with
    its upkeep silently dropped — a strictly better card than the one printed.
    """
    remora = set_pool("ICE")["Mystic Remora"]
    trigger = _cu_trigger(remora)

    assert trigger is not None
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.payload["mana"] == {"generic": 1}


def test_soldevi_simulacrum_escalates_across_two_upkeeps(set_pool):
    """"Cumulative upkeep {1}" on the board: {1} the first upkeep, {2} the
    second, paid by tapping lands during the step."""
    sim = Permanent(card=set_pool("ICE")["Soldevi Simulacrum"])
    forests = [Permanent(card=set_pool("ICE")["Forest"]) for _ in range(4)]
    p1 = PlayerState(name="P1", battlefield=[sim, *forests], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    assert sum(1 for f in forests if f.tapped) == 1
    for forest in forests:
        forest.tapped = False

    game.resolve_upkeep(0)
    assert counters_on(sim, "age") == 2
    assert sum(1 for f in forests if f.tapped) == 2
    assert sim in p1.battlefield


def test_polar_kraken_refuses_a_cost_the_engine_cannot_charge(set_pool):
    """"Cumulative upkeep—Sacrifice a land." CR 702.24a admits any cost and
    this engine charges mana, so the card stays unsupported **naming the
    clause** rather than shipping with a free upkeep."""
    kraken = set_pool("ICE")["Polar Kraken"]
    program = compile_card_oracle(kraken)

    assert not program.supported
    assert "cumulative upkeep" in (program.reason or "").lower()
    assert _cu_trigger(kraken) is None


def test_halls_of_mist_still_reports_its_unread_static_line(set_pool):
    """A land whose cumulative upkeep now compiles, and whose *other* line the
    engine does not implement.

    The land support gate used to skip the static check for any land carrying
    an ability, so implementing the keyword would have turned this card
    supported with "Creatures that attacked … can't attack" doing nothing. The
    gate reads every land now and names the line it cannot claim.
    """
    program = compile_card_oracle(set_pool("ICE")["Halls of Mist"])

    assert not program.supported
    assert "can't attack" in (program.reason or "")
