"""Weatherlight creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: cumulative upkeep beyond a mana cost ---
from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g3_solo_game(card, *, library=0, life=20, library_card=None):
    """One permanent on P1's battlefield and nothing else in the way.

    Built here rather than through a fixture because the point of every test in
    this block is the *upkeep step*, and a shared deck would leave which cards
    are on the board to the shuffle.
    """
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_aboroth_pays_its_upkeep_in_minus_counters_and_shrinks_to_death(set_pool):
    """"Cumulative upkeep—Put a -1/-1 counter on this creature."

    CR 702.24a's cost is paid **once per age counter**, so the 9/9 loses one
    point on its first upkeep, two more on its second and three more on its
    third — and the fourth kills it. A cost that scaled the payload instead of
    the repetition would put a single counter down every turn and leave an
    8/8 standing forever.
    """
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])
    assert (perm.effective_power, perm.effective_toughness) == (9, 9)

    seen = []
    for _ in range(4):
        game.resolve_upkeep(0)
        seen.append((counters_on(perm, "age"), perm.effective_power))
        if perm not in p1.battlefield:
            break

    assert seen == [(1, 8), (2, 6), (3, 3), (4, -1)]
    assert perm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Aboroth"]


def test_aboroths_upkeep_prompt_quotes_the_act_and_its_repetition(set_pool):
    """The offer is made before the trigger resolves, so the counter it is
    about to place is already in the quoted cost — the same rule the mana
    spelling follows, and the reason a player is not shown one cost and
    charged another."""
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])

    first = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert first["cost_label"] == "put a -1/-1 counter on this creature"

    game.resolve_upkeep(0)
    second = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert second["cost_label"] == "put a -1/-1 counter on this creature 2 times"


def test_aboroth_compiles_its_keyword_into_one_upkeep_trigger(set_pool):
    """The keyword line is the *only* line on the card, so before this round it
    was refused outright and Aboroth was unsupported — not a permanent with a
    free upkeep, which is the direction a widened gate would have gone."""
    program = compile_card_oracle(set_pool("WTH")["Aboroth"])

    assert program.supported
    assert [
        (trig.condition.kind, trig.instruction.kind)
        for trig in program.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]


def _w1g3_settle(game):
    """Run the stack down, answering the announcement it now stops for.

    Never a bare ``while game.stack`` loop: a pay-or-sacrifice upkeep owes an
    interactive seat a prompt, and while one is owed the game waits (CR 608.2,
    CR 117.3b) — so the bare loop spins. Drained with the registry's own
    defaults.
    """
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game.auto_resolve_pending_choices(kinds=("trigger_target",))
        game._settle()


def test_revered_unicorn_gains_life_for_every_age_counter_it_had(set_pool, cards):
    """"When this creature leaves the battlefield, you gain life equal to the
    number of age counters on it."

    The counter is placed *before* the payment is offered (CR 702.24a), so the
    upkeep that kills the Unicorn is also the one that puts its fourth counter
    down — and the number the trigger reads is last-known information
    (CR 603.10), taken off a permanent already in the graveyard.
    """
    unicorn = Permanent(card=set_pool("WTH")["Revered Unicorn"])
    lands = [Permanent(card=cards["Plains"]) for _ in range(8)]
    p1 = PlayerState(name="P1", battlefield=[unicorn] + lands, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.interactive_seats = {0}

    for _ in range(3):
        game.resolve_upkeep(0, human_choices={"Revered Unicorn": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
    assert counters_on(unicorn, "age") == 3 and p1.life == 20

    game.resolve_upkeep(0, human_choices={"Revered Unicorn": False})
    _w1g3_settle(game)

    assert unicorn not in p1.battlefield
    assert p1.life == 24, "four age counters when it left, not three"


def test_revered_unicorns_leave_trigger_counts_through_the_shared_evaluator(set_pool):
    """The amount is the ``source_counters`` spec Malignant Growth's draw and
    Primordial Ooze's where-clause already write — one evaluator, so the three
    printed word orders cannot count differently."""
    program = compile_card_oracle(set_pool("WTH")["Revered Unicorn"])
    leave = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "leaves_battlefield"
    )

    assert leave.supported
    assert leave.instruction.payload["x_from_count"] == {"source_counters": "age"}


def test_mwonvuli_ooze_is_one_plus_twice_its_age_counters(set_pool, cards):
    """"Mwonvuli Ooze's power and toughness are each equal to 1 plus twice the
    number of age counters on it." (CR 604.3 over CR 122.1's counters.)

    Three upkeeps, because the arithmetic is what is being checked: a dropped
    "twice" is a 1/1 that grows by one and a constant applied on the wrong side
    of the multiplier is a 2/2 that grows by two, and both look right for
    exactly one turn.
    """
    ooze = Permanent(card=set_pool("WTH")["Mwonvuli Ooze"])
    lands = [Permanent(card=cards["Forest"]) for _ in range(12)]
    p1 = PlayerState(name="P1", battlefield=[ooze] + lands, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.interactive_seats = {0}

    assert (ooze.effective_power, ooze.effective_toughness) == (1, 1)
    sizes = []
    for _ in range(3):
        game.resolve_upkeep(0, human_choices={"Mwonvuli Ooze": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
        sizes.append((ooze.effective_power, ooze.effective_toughness))

    assert sizes == [(3, 3), (5, 5), (7, 7)]
    assert counters_on(ooze, "age") == 3


def test_mwonvuli_ooze_counts_through_the_one_evaluator(set_pool):
    """The count is the ``source_counters`` spec every other reading of "the
    number of <kind> counters on it" writes — not a second counter in the
    characteristic-defining table, which is what a per-card row would have
    been."""
    program = compile_card_oracle(set_pool("WTH")["Mwonvuli Ooze"])
    cda = next(i for i in program.instructions if i.kind == "dynamic_pt_count")

    assert cda.payload == {
        "count_spec": {"source_counters": "age", "multiplier": 2, "plus": 1}
    }
