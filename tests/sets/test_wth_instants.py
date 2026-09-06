"""Weatherlight instants.

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


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str, colors: tuple = ()) -> CardDefinition:
    """A vanilla card to stack a graveyard with. The colour is what Spinning
    Darkness's cost scans for, so it is the one characteristic that varies."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2",
             "toughness": "2", "colors": list(colors)},
    )


def _w1g1_darkness(set_pool, graveyard):
    """Spinning Darkness in hand with *graveyard* behind it and a creature to
    aim at. The graveyard is bottom-first (CR 404.1: an arriving card goes on
    top, so the last element is the top card)."""
    victim = Permanent(card=_w1g1_card("Victim", "Creature — Bear"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Spinning Darkness"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", battlefield=[victim],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.start_turn(0)
    return game, victim


def test_spinning_darkness_is_cast_for_three_black_cards_and_no_mana(set_pool):
    """"You may exile the top three black cards of your graveyard rather than
    pay this spell's mana cost." (CR 118.9.)

    The mana is *never* paid — the game has no lands at all here — and the
    three cards come off the top of the pile, skipping the white card that
    happens to be above one of them. CR 118.9c leaves the printed {4}{B}{B}
    untouched; what is skipped is the payment.
    """
    game, victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black Deep", "Creature — Zombie", ("B",)),
        _w1g1_card("White Card", "Creature — Bear", ("W",)),
        _w1g1_card("Black Mid", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Top", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert sorted(card.name for card in me.exile) == [
        "Black Deep", "Black Mid", "Black Top"
    ]
    # The spell itself lands in the graveyard on resolution (CR 608.2m), so
    # the pile is read for what the *cost* left behind.
    assert [
        card.name for card in me.graveyard if card.name != "Spinning Darkness"
    ] == ["White Card"]
    if game.stack:
        game.resolve_top_of_stack()
    assert victim.damage_marked == 3
    assert me.life == 23


def test_spinning_darkness_refuses_a_pile_that_cannot_pay_in_full(set_pool):
    """CR 118.3: a cost is paid in full or not at all, and CR 601.2h then makes
    an unpayable alternative cost an *uncastable* spell — never one cast for
    nothing, which is what a partial charge would be once the mana payment has
    already been replaced."""
    game, _victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black One", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Two", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert len(me.graveyard) == 2, "the two black cards are still there"
    assert me.exile == []
    assert [card.name for card in me.hand] == ["Spinning Darkness"]


# --- W2G3: phasing and end of combat ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g3i_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g3i_debt(set_pool):
    """Debt of Loyalty in hand, an opponent's creature to point it at."""
    victim = Permanent(card=_w2g3i_creature("Victim", 2, 2))
    victim.summoning_sick = False
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Debt of Loyalty"]]),
        PlayerState(name="P2", battlefield=[victim]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    result = game.cast_from_hand(
        0, "Debt of Loyalty", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    for _ in range(20):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game, victim


def test_debt_of_loyalty_delays_the_steal_until_the_shield_is_spent(set_pool):
    """"Regenerate target creature. You gain control of that creature **if it
    regenerates this way**." (CR 603.7, CR 701.19c.)

    The trailing "if" is a delay, not a condition on this resolution — CR 701.19c
    is explicit that creating a regeneration shield is not regenerating, so a
    reading that asked the question now would answer no on every board and the
    control change would never happen at all.

    The entry binds the spell's **target**, not its source: the source is an
    instant that is in a graveyard by the time the shield is spent, and
    CR 603.7d's own-source default would watch it.
    """
    program = compile_card_oracle(set_pool("WTH")["Debt of Loyalty"])
    assert program.supported, program.reason
    (sequence,) = program.instructions
    _regen, delay = sequence.payload["steps"]
    assert delay.payload["event"] == "source_regenerates"
    assert delay.payload["instruction"].kind == "gain_control_of_bound_permanent"
    assert delay.payload["binds_target"] is True

    game, victim = _w2g3i_debt(set_pool)
    assert victim.regeneration_shield == 1
    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == victim.permanent_id
    assert game.controller_index_of(victim) == 1


def test_debt_of_loyalty_takes_the_creature_when_it_regenerates(set_pool):
    """The shield spent is the event, and the control change follows it."""
    game, victim = _w2g3i_debt(set_pool)

    game._destroy_swept_permanents(game.players[1], lambda p: p is victim)
    for _ in range(20):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game._settle()

    assert game.controller_index_of(victim) == 0, game.log
    assert victim in game.players[0].battlefield
    assert victim not in game.players[1].battlefield


def test_debt_of_loyalty_takes_nothing_if_the_creature_is_never_destroyed(set_pool):
    """The half the printed "if" is for.

    A card that gained control on resolution would be a strictly better spell
    than the one printed, and nothing in the compiled program would look wrong:
    the steal happens, the log says so, and the creature simply changes hands a
    turn early and unconditionally.
    """
    game, victim = _w2g3i_debt(set_pool)
    game._settle()

    assert game.controller_index_of(victim) == 1, game.log
    assert victim in game.players[1].battlefield
