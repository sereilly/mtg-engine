"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game
from engine import PlayerState as _w1g9_PlayerState
from engine.models import CardDefinition as _w1g9_CardDefinition
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_vanilla(name, power, toughness, *, subtype="Test", colors=()):
    """A creature carrying only its numbers, its type and its colour.

    Invented rather than pulled from a pool: every test below is about a
    relation between two creatures (who is blocking whom, which colour blocked),
    and a pool creature would bring its own printed line along with the answer.
    """
    type_line = f"Creature - {subtype}"
    return _w1g9_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g9_ready(card):
    """*card* as a permanent that may attack and tap this turn."""
    permanent = _w1g9_Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_main(mine, theirs, *, libraries=((), ())):
    """A two-seat game in the first main phase of seat 0's turn, costs off."""
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P1", battlefield=list(mine), library=list(libraries[0])
        ),
        _w1g9_PlayerState(
            name="P2", battlefield=list(theirs), library=list(libraries[1])
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _w1g9_to_attackers(game):
    """Advance *game* from a main phase to its declare-attackers step."""
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    return game


def _w1g9_slot(game, seat, permanent):
    """Where *permanent* sits on *seat*'s battlefield, for the two entry
    points (attackers, blockers) that still take a slot."""
    return next(
        slot for slot, found in enumerate(game.controlled_by(seat))
        if found is permanent
    )


# --- Cromat -----------------------------------------------------------------


def _w1g9_cromat_blocked(set_pool):
    """Cromat attacking, blocked by the first of two identical 5/5s.

    Two on the far side on purpose, and identical: one blocked and one did not,
    and nothing about either creature tells them apart — so a dropped relation
    shows up as the bystander being reachable.
    """
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    ally = _w1g9_ready(_w1g9_vanilla("Ally", 1, 1))
    blocker = _w1g9_ready(_w1g9_vanilla("Blocker", 5, 5))
    bystander = _w1g9_ready(_w1g9_vanilla("Bystander", 5, 5))
    filler = _w1g9_vanilla("Filler", 1, 1)
    game = _w1g9_to_attackers(_w1g9_main(
        [cromat, ally], [blocker, bystander], libraries=([filler, filler], [filler]),
    ))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g9_resolve_stack(game)
    return game, cromat, ally, blocker, bystander


def test_w1g9_cromat_compiles_all_five_abilities(set_pool):
    program = _w1g9_compile(set_pool("APC")["Cromat"])

    assert program.supported
    assert len(program.activated_abilities) == 5
    destroy = program.activated_abilities[0].instruction
    assert destroy.payload["targets"]["filter"]["in_combat_with_source"] is True


def test_w1g9_cromat_has_nothing_to_destroy_outside_a_block(set_pool):
    """"Destroy target creature **blocking or blocked by Cromat**." With no
    block there is no such creature, so the ability cannot be activated at all
    (CR 602.2b through CR 601.2c) — named target or not."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    foe = _w1g9_ready(_w1g9_vanilla("Foe", 5, 5))
    game = _w1g9_main([cromat], [foe])

    assert game.activation_target_spec(0, 0, 0)["valid_targets"] == []
    named = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[foe.permanent_id],
    )
    bare = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0
    )

    assert not named.supported and not bare.supported
    assert game.is_on_battlefield(foe) and not game.stack


def test_w1g9_cromat_is_offered_only_the_creature_blocking_it(set_pool):
    """The picker's list and the announcement gate are one list: the blocker
    and nothing else — not the identical creature beside it, not Cromat's own
    side, not Cromat."""
    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)

    offered = game.activation_target_spec(0, 0, 0)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(1, "Blocker")]
    for illegal in (bystander, ally, cromat):
        refused = game.activate_permanent_ability(
            0, "Cromat", permanent_index=0, ability_index=0,
            target_permanent_ids=[illegal.permanent_id],
        )
        assert not refused.supported, illegal.card.name
    assert not game.stack

    result = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    )

    assert result.supported, result.details
    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)
    assert [card.name for card in game.players[1].graveyard] == ["Blocker"]
    assert "Cromat destroyed Blocker" in game.log


def test_w1g9_cromat_blocking_destroys_the_attacker_it_blocked(set_pool):
    """The relation read from the other end: Cromat as the blocker, and the
    one legal target is the attacker it is blocking — not the attacker that got
    through beside it."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    blocked = _w1g9_ready(_w1g9_vanilla("Blocked", 5, 5))
    unblocked = _w1g9_ready(_w1g9_vanilla("Unblocked", 5, 5))
    game = _w1g9_to_attackers(_w1g9_main([blocked, unblocked], [cromat]))
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    offered = game.activation_target_spec(1, 0, 0)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(0, "Blocked")]
    assert not game.activate_permanent_ability(
        1, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[unblocked.permanent_id],
    ).supported
    assert game.activate_permanent_ability(
        1, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocked.permanent_id],
    ).supported

    assert not game.is_on_battlefield(blocked)
    assert game.is_on_battlefield(unblocked)


def test_w1g9_cromat_a_target_that_left_the_fight_is_not_destroyed(set_pool):
    """CR 608.2b: the target is asked again as the ability resolves. A blocker
    removed from combat in response is no longer "blocking Cromat", and the
    destroy does not go looking for somebody else."""
    from engine.handlers.combat import _take_permanent_out_of_combat

    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)
    queued = game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    )
    assert queued.supported and len(game.stack) == 1

    _take_permanent_out_of_combat(game, blocker, frees_blocked_attackers=False)
    _w1g9_resolve_stack(game)

    assert game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)
    assert not any("destroyed" in line for line in game.log)


def test_w1g9_cromat_tucked_in_response_still_destroys_its_blocker(set_pool):
    """Two of the five abilities on one stack: the destroy, then "{G}{U}: Put
    Cromat on top of its owner's library" in response. Cromat is gone when the
    destroy resolves, and CR 608.2h reads the block it was in as last known
    information — the creature that blocked it is still the creature named."""
    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)
    assert game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    ).supported
    assert game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=4
    ).supported
    _w1g9_resolve_stack(game)

    assert not game.is_on_battlefield(cromat)
    assert game.players[0].library[0].name == "Cromat"
    assert len(game.players[0].library) == 3
    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)


def test_w1g9_cromat_flies_grows_and_regenerates(set_pool):
    """The three abilities that act on Cromat itself, in one combat: flying and
    +1/+1 until end of turn, and a regeneration shield that is spent when a
    7/7 deals it lethal damage — Cromat is tapped, out of combat, and alive."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    wall = _w1g9_ready(_w1g9_vanilla("Big Wall", 7, 7))
    game = _w1g9_to_attackers(_w1g9_main([cromat], [wall]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    for ability in (1, 3, 2):
        assert game.activate_permanent_ability(
            0, "Cromat", permanent_index=0, ability_index=ability
        ).supported
    assert game._has_keyword(cromat, "flying")
    assert (cromat.effective_power, cromat.effective_toughness) == (6, 6)
    assert cromat.regeneration_shield == 1

    game.advance_combat_phase()   # combat damage

    assert game.is_on_battlefield(cromat)
    assert "Cromat regenerated" in game.log
    assert cromat.tapped and cromat.regeneration_shield == 0
    assert cromat.damage_marked == 0

    game.resolve_cleanup_step(0)
    assert not game._has_keyword(cromat, "flying")
    assert (cromat.effective_power, cromat.effective_toughness) == (5, 5)


# --- Zombie Boa ---------------------------------------------------------------


def _w1g9_boa_game(set_pool, *, interactive=False):
    boa = _w1g9_ready(set_pool("APC")["Zombie Boa"])
    green = _w1g9_ready(_w1g9_vanilla("Green One", 1, 1, colors=("G",)))
    red = _w1g9_ready(_w1g9_vanilla("Red One", 1, 1, colors=("R",)))
    game = _w1g9_main([boa], [green, red])
    if interactive:
        game.interactive_seats = {0}
    return game, boa, green, red


def _w1g9_boa_attacks_into(game, blockers):
    """The Boa attacks and each permanent in *blockers* blocks it."""
    _w1g9_to_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {_w1g9_slot(game, 1, blocker): 0 for blocker in blockers}
    )[0]
    _w1g9_resolve_stack(game)
    game._settle()


def test_w1g9_zombie_boa_destroys_only_a_blocker_of_the_chosen_color(set_pool):
    """"Choose a color. Whenever this creature becomes blocked by a creature
    **of that color** this turn, destroy that creature."

    A human seat is asked for the colour as the ability resolves (CR 608.2d),
    and the answer is what the delayed ability watches for: blocked by a green
    creature and a red one at once, with red chosen, the red one dies and the
    green one is left blocking.
    """
    game, boa, green, red = _w1g9_boa_game(set_pool, interactive=True)

    assert game.queue_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    game.resolve_top_of_stack()
    assert [choice.kind for choice in game.pending_choices] == ["color_choice"]
    assert not game.delayed_triggers, "nothing is armed before the colour is chosen"
    assert game.confirm_color_choice(0, "R")
    if game.stack:
        game.resolve_top_of_stack()

    (armed,) = game.delayed_triggers
    assert armed.event == "source_becomes_blocked_by"
    assert armed.agent_filter == {"type_filter": "creature", "color_filter": "R"}

    _w1g9_boa_attacks_into(game, [green, red])

    assert not game.is_on_battlefield(red)
    assert game.is_on_battlefield(green)
    assert "Zombie Boa destroyed Red One" in game.log


def test_w1g9_zombie_boa_leaves_another_colors_blocker_alone(set_pool):
    """The narrowing is the whole card: with green chosen, a red blocker
    triggers nothing at all — no ability goes on the stack."""
    game, boa, green, red = _w1g9_boa_game(set_pool, interactive=True)
    assert game.queue_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_color_choice(0, "G")
    if game.stack:
        game.resolve_top_of_stack()

    _w1g9_to_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, red): 0})[0]

    assert not game.stack
    assert game.is_on_battlefield(red) and game.is_on_battlefield(green)


def test_w1g9_zombie_boa_a_headless_seat_chooses_and_the_trigger_fires(set_pool):
    """No prompt for a seat nobody is sitting in: the default colour is the one
    the opponents hold most of, and the ability is armed in the same
    resolution. One green creature and one red one is a tie the default breaks
    for green, which is the creature that then dies blocking."""
    game, boa, green, red = _w1g9_boa_game(set_pool)

    result = game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0)
    assert result.supported, result.details
    (armed,) = game.delayed_triggers
    chosen = armed.agent_filter["color_filter"]
    victim, survivor = (green, red) if chosen == "G" else (red, green)

    _w1g9_boa_attacks_into(game, [victim])

    assert not game.is_on_battlefield(victim)
    assert game.is_on_battlefield(survivor)


def test_w1g9_zombie_boa_is_activated_only_as_a_sorcery(set_pool):
    """"Activate only as a sorcery." Refused in combat with nothing armed; the
    same seat in its main phase a moment earlier is allowed."""
    game, boa, green, red = _w1g9_boa_game(set_pool)
    _w1g9_to_attackers(game)

    refused = game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0)

    assert not refused.supported
    assert "sorcery" in refused.details
    assert not game.delayed_triggers and not game.stack


def test_w1g9_zombie_boa_the_watch_ends_with_the_turn(set_pool):
    """"…this turn" is CR 603.7b's stated duration: the cleanup step takes the
    ability off the waiting list, so a block next turn destroys nothing."""
    game, boa, green, red = _w1g9_boa_game(set_pool)
    assert game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    assert len(game.delayed_triggers) == 1

    game.resolve_cleanup_step(0)

    assert not game.delayed_triggers


def test_w1g9_of_that_color_refuses_without_a_step_that_chose_one():
    """The refusal half of the production. "Of that color" on a delay's agent
    names a colour an earlier sentence of the same effect chose; with no such
    sentence the words name nothing, and the line must refuse rather than arm
    an ability that can never match."""
    from engine.grammar import compile_line

    bare = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a creature of that "
        "color this turn, destroy that creature.",
        card_name="Test",
    )
    assert bare.parsed and not bare.lowered
    assert "chose a color" in bare.lowering_error

    printed = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a black creature "
        "this turn, destroy that creature.",
        card_name="Test",
    )
    assert printed.lowered
    (created,) = printed.instructions
    assert created.payload["event"] == "source_becomes_blocked_by"
    assert created.payload["agent_filter"] == {
        "type_filter": "creature", "color_filter": "B",
    }

    windowless = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a black creature, "
        "destroy that creature.",
        card_name="Test",
    )
    assert not windowless.lowered, "an ability with no window is not a delay"


# --- Drive list: Kavu Mauler, Flowstone Charger, Spectral Lynx, the pumps ------


def test_w1g9_kavu_mauler_counts_the_other_attacking_kavu(set_pool):
    """"…it gets +1/+1 until end of turn for each **other attacking Kavu**."
    Two Kavu attack beside it, a third stays home and a Bear attacks too: +2/+2
    and no more. Trample then carries the excess over a chump blocker."""
    mauler = _w1g9_ready(set_pool("APC")["Kavu Mauler"])
    others = [
        _w1g9_ready(_w1g9_vanilla("Kavu A", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Kavu B", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Kavu Home", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Bear", 2, 2, subtype="Bear")),
    ]
    chump = _w1g9_ready(_w1g9_vanilla("Chump", 1, 1))
    game = _w1g9_to_attackers(_w1g9_main([mauler, *others], [chump]))

    assert game.declare_attackers(0, [0, 1, 2, 4])[0]
    _w1g9_resolve_stack(game)
    assert (mauler.effective_power, mauler.effective_toughness) == (6, 6)

    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    # 5 trampled over the 1/1, plus 2 + 2 + 2 from the unblocked three.
    assert game.players[1].life == 9
    assert not game.is_on_battlefield(chump)
    game.resolve_cleanup_step(0)
    assert (mauler.effective_power, mauler.effective_toughness) == (4, 4)


def test_w1g9_flowstone_charger_trades_toughness_for_power(set_pool):
    """"Whenever this creature attacks, it gets +3/-3 until end of turn." A
    2/5 becomes a 5/2 for the turn — and one already carrying 2 damage dies of
    it as the trigger resolves (CR 704.5g)."""
    charger = _w1g9_ready(set_pool("APC")["Flowstone Charger"])
    game = _w1g9_to_attackers(_w1g9_main([charger], []))
    assert game.declare_attackers(0, [0])[0]
    _w1g9_resolve_stack(game)

    assert (charger.effective_power, charger.effective_toughness) == (5, 2)
    game.resolve_cleanup_step(0)
    assert (charger.effective_power, charger.effective_toughness) == (2, 5)

    hurt = _w1g9_ready(set_pool("APC")["Flowstone Charger"])
    hurt.damage_marked = 2
    game = _w1g9_to_attackers(_w1g9_main([hurt], []))
    assert game.declare_attackers(0, [0])[0]
    _w1g9_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(hurt)
    assert [card.name for card in game.players[0].graveyard] == ["Flowstone Charger"]


def test_w1g9_spectral_lynx_regenerates_and_is_protected_from_green(set_pool):
    """Both printed lines in play. "{B}: Regenerate" — a shield spent on lethal
    combat damage from a red 5/5, leaving the Lynx tapped and alive. And
    protection from green (CR 702.16): a green attacker it blocks deals it no
    damage, and a green creature may not block it."""
    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    red = _w1g9_ready(_w1g9_vanilla("Red Foe", 5, 5, colors=("R",)))
    game = _w1g9_to_attackers(_w1g9_main([red], [lynx]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.activate_permanent_ability(1, "Spectral Lynx", permanent_index=0).supported
    assert lynx.regeneration_shield == 1
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert game.is_on_battlefield(lynx)
    assert lynx.tapped and lynx.regeneration_shield == 0
    assert "Spectral Lynx regenerated" in game.log

    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    green = _w1g9_ready(_w1g9_vanilla("Green Foe", 5, 5, colors=("G",)))
    game = _w1g9_to_attackers(_w1g9_main([green], [lynx]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert game.is_on_battlefield(lynx) and lynx.damage_marked == 0
    assert green.damage_marked == 2

    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    green = _w1g9_ready(_w1g9_vanilla("Green Foe", 5, 5, colors=("G",)))
    game = _w1g9_to_attackers(_w1g9_main([lynx], [green]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {0: 0})
    assert not blocked and "cannot block" in why


@_w1g9_pytest.mark.parametrize(
    "name, pool, grown",
    [
        ("Angelfire Crusader", {"R": 2, "W": 1}, (4, 3)),
        ("Ebony Treefolk", {"B": 2, "G": 2, "R": 1}, (5, 5)),
    ],
)
def test_w1g9_the_two_pumps_cost_what_they_print(set_pool, name, pool, grown):
    """"{R}: +1/+0" and "{B}{G}: +1/+1", with costs enforced: nothing with an
    empty pool, twice with mana for two, refused a third time on the mana that
    is the wrong colour, and gone at cleanup."""
    creature = _w1g9_ready(set_pool("APC")[name])
    printed = (creature.effective_power, creature.effective_toughness)
    game = _w1g9_main([creature], [])
    game.enforce_mana_costs = True

    assert not game.activate_permanent_ability(0, name, permanent_index=0).supported
    game.players[0].mana_pool.update(pool)
    assert game.activate_permanent_ability(0, name, permanent_index=0).supported
    assert game.activate_permanent_ability(0, name, permanent_index=0).supported
    third = game.activate_permanent_ability(0, name, permanent_index=0)

    assert not third.supported and "insufficient mana" in third.details
    assert (creature.effective_power, creature.effective_toughness) == grown
    game.resolve_cleanup_step(0)
    assert (creature.effective_power, creature.effective_toughness) == printed

# ==== end W1G9 ========================================================
