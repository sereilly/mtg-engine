"""Weatherlight enchantments.

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
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_psychic_vortex_draws_one_card_per_age_counter_each_upkeep(set_pool):
    """"Cumulative upkeep—Draw a card."

    The card was **supported before this round** — its end-step trigger claimed
    it — and its upkeep did nothing at all, which is the failure mode a support
    census cannot see. Three upkeeps draw one, then two, then three.
    """
    pool = set_pool("WTH")
    game, p1, perm = _w1g3_solo_game(
        pool["Psychic Vortex"], library=12, library_card=pool["Fog Elemental"]
    )

    drawn = []
    for _ in range(3):
        game.resolve_upkeep(0)
        drawn.append((counters_on(perm, "age"), len(p1.hand)))

    assert drawn == [(1, 1), (2, 3), (3, 6)]
    assert perm in p1.battlefield


def test_psychic_vortexs_upkeep_is_a_cumulative_upkeep_trigger(set_pool):
    program = compile_card_oracle(set_pool("WTH")["Psychic Vortex"])

    assert program.supported
    assert sorted(
        trig.instruction.kind for trig in program.triggered_abilities
        if trig.instruction is not None
    ) == ["cumulative_upkeep", "sequence"]


def _w1g3_settle(game):
    """Run the stack down, answering the announcement it now stops for.

    Never a bare ``while game.stack`` loop: a pay-or-sacrifice upkeep owes an
    interactive seat a prompt, and while one is owed the game waits (CR 608.2,
    CR 117.3b).
    """
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game.auto_resolve_pending_choices(kinds=("trigger_target",))
        game._settle()


def test_wave_of_terror_kills_the_mana_value_its_age_counters_name(set_pool, cards):
    """"At the beginning of your draw step, destroy each creature with mana
    value equal to the number of age counters on this enchantment."

    The card was **supported before this round** on its keyword line alone, with
    this whole ability compiling to no instruction — a hollow line, and the one
    of the three silent failures an instrument can see.

    Both boards, because the sentence names no controller: a sweep narrowed to
    the caster's own creatures would be a strictly better card. Four draw steps,
    because a bound read as a constant, as "at most", or off the wrong pile all
    look identical on the first one.
    """
    wave = Permanent(card=set_pool("WTH")["Wave of Terror"])
    lands = [Permanent(card=cards["Swamp"]) for _ in range(12)]
    mine = {
        name: Permanent(card=cards[name])
        for name in ("Savannah Lions", "Grizzly Bears", "Gray Ogre", "Hill Giant")
    }
    theirs = {
        name: Permanent(card=cards[name])
        for name in ("Merfolk of the Pearl Trident", "Hurloon Minotaur")
    }
    p1 = PlayerState(name="P1", battlefield=[wave] + lands + list(mine.values()))
    p2 = PlayerState(name="P2", battlefield=list(theirs.values()))
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    survivors = []
    for _ in range(4):
        game.resolve_upkeep(0, human_choices={"Wave of Terror": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
        game.resolve_draw_step(0)
        _w1g3_settle(game)
        survivors.append(sorted(
            perm.card.name
            for seat in (p1, p2) for perm in seat.battlefield
            if "Creature" in perm.card.type_line
        ))

    assert survivors == [
        # 1 age counter: both mana-value-1 creatures, one per seat
        ["Gray Ogre", "Grizzly Bears", "Hill Giant", "Hurloon Minotaur"],
        ["Gray Ogre", "Hill Giant", "Hurloon Minotaur"],
        ["Hill Giant"],
        [],
    ]
    assert wave in p1.battlefield, "the enchantment is not a creature"


def test_wave_of_terrors_sweep_carries_both_of_its_riders(set_pool):
    """The counted bound *and* "They can't be regenerated." A sweep that kept
    the first and dropped the second would be a card that works more often than
    it prints — and one that kept neither would take the whole board."""
    program = compile_card_oracle(set_pool("WTH")["Wave of Terror"])
    sweep = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "draw_step_self"
    )

    assert sweep.instruction.kind == "destroy_all_matching"
    assert sweep.instruction.payload == {
        "type_filter": "creature",
        "mana_value_equals_source_counters": "age",
        "bypass_regeneration": True,
    }
