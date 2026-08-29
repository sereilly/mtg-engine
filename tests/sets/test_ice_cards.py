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


# --- Round 2: the Scarab cycle — a conditional static on an Aura's host ---


def _scarab_board(set_pool, scarab_name: str, opponent_permanent: str | None):
    """A 2/2 bear wearing *scarab_name*, with the opponent's board as named.

    The Aura is attached with ``attach_aura`` rather than cast, because what is
    under test is the continuous effect while attached (CR 611.3a) — recomputed
    on every read, never applied once at attachment.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])  # a vanilla 2/2, no text at all
    scarab = Permanent(card=pool[scarab_name])
    p1 = PlayerState(name="P1", battlefield=[bear, scarab], life=20)
    theirs = [Permanent(card=pool[opponent_permanent])] if opponent_permanent else []
    p2 = PlayerState(name="P2", battlefield=theirs, life=20)
    game = Game(players=[p1, p2])
    attach_aura(scarab, bear)
    game._settle()
    return game, bear, scarab


def test_black_scarab_grants_nothing_while_no_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", None)

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_black_scarab_grants_plus_two_while_an_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")  # a black creature

    assert (bear.effective_power, bear.effective_toughness) == (4, 4)


def test_black_scarab_reads_the_condition_on_every_recompute(set_pool):
    """CR 611.3a — the condition is asked continuously, not locked in when the
    Aura attached. Removing the opponent's black permanent removes the bonus
    with nothing to undo."""
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")
    assert bear.effective_power == 4

    game.remove_from_battlefield(game.players[1].battlefield[0])
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_scarab_condition_is_measured_from_the_auras_controller(set_pool):
    """CR 109.5: the ability is the Aura's, so "an opponent" is an opponent of
    whoever controls the Aura — not of whoever controls the creature.

    The cycle exists to be put on an opponent's creature, so this is the case
    the card is printed for rather than a corner: P1's Scarab on P1's own black
    creature must see P1's board as "you", find no *opponent* with a black
    permanent, and grant nothing.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    black_bear = Permanent(card=pool["Moor Fiend"])
    scarab = Permanent(card=pool["Black Scarab"])
    p1 = PlayerState(name="P1", battlefield=[black_bear, scarab], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(scarab, black_bear)
    game._settle()

    assert (black_bear.effective_power, black_bear.effective_toughness) == (3, 3)


def test_every_scarab_in_the_cycle_compiles_to_the_same_shape(set_pool):
    """Five cards, one sentence with the colour word changed — the reason this
    is a production rather than five entries."""
    pool = set_pool("ICE")
    colors = {
        "Black Scarab": "B", "Blue Scarab": "U", "Green Scarab": "G",
        "Red Scarab": "R", "White Scarab": "W",
    }
    for name, symbol in colors.items():
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        static = next(
            i for i in program.instructions if i.kind == "conditional_static"
        )
        assert static.payload["subject"] == "attached", name
        assert static.payload["power"] == 2 and static.payload["toughness"] == 2
        assert static.payload["condition"]["who"] == "opponent", name
        assert static.payload["condition"]["filter"]["color_filter"] == symbol, name


# --- Round 3: the cantrip cycle — "at the beginning of the next turn's upkeep" ---


def test_pyknite_draws_at_the_next_turns_upkeep(set_pool):
    """The cantrip run end to end: the creature enters, arms the delayed
    ability, and the card arrives at the *next* upkeep — not this one, and not
    at resolution."""
    pool = set_pool("ICE")
    pyknite = Permanent(card=pool["Pyknite"])
    p1 = PlayerState(
        name="P1",
        battlefield=[pyknite],
        library=[pool["Balduvian Bears"], pool["Balduvian Bears"]],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game._apply_self_enters_battlefield_triggers(0, pyknite, None, None)
    game._settle()
    assert p1.hand == [], "the draw is delayed, not part of the enters trigger"

    game.resolve_upkeep(0)
    game._settle()
    assert len(p1.hand) == 1


def test_the_cantrip_cycle_arms_the_unseated_upkeep_event(set_pool):
    """Seven cards, one sentence. What makes it one round rather than seven is
    that they all compile to the same delayed event — and it is the *unseated*
    one, because "the next turn's upkeep" is whichever comes next."""
    pool = set_pool("ICE")
    for name in (
        "Portent", "Krovikan Fetish", "Panic", "Pyknite",
        "Touch of Vitae", "Barbed Sextant",
    ):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        events = {
            instruction.payload.get("event")
            for instruction in _all_instructions(program)
            if instruction.kind == "create_delayed_trigger"
        }
        assert events == {"next_turns_upkeep"}, (name, events)


def _all_instructions(program):
    """Every instruction the program carries, card-level and per-ability.

    The cycle prints its cantrip in three places — a spell's second sentence, an
    Aura's enters trigger, an artifact's activated ability — so a reader that
    looked only at ``program.instructions`` would find the clause on some of
    them and quietly miss it on the rest.
    """
    def walk(instruction):
        yield instruction
        # A `sequence` is how two sentences on one line compose (Barbed
        # Sextant's "Add one mana of any color. Draw a card at …"), so a reader
        # that stopped at the top level would find the clause on five of the
        # seven and report the other two clean.
        for step in instruction.payload.get("steps", ()):
            yield from walk(step)

    for instruction in program.instructions:
        yield from walk(instruction)
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        if ability.instruction is not None:
            yield from walk(ability.instruction)
