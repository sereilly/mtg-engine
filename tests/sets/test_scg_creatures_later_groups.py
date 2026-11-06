"""Scourge creatures, W1G6 onward (W1G1-W1G5 are in test_scg_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Dragons: Bladewing's Thrall's graveyard trigger (it compiled supported and
# never fired — the offer wrapping its return hid CR 113.6m's zone from the
# graveyard scan), Bladewing the Risen's "target Dragon permanent card".

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("SCG", "LEA", "ONS", "LGN"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_table(set_pool, *, graveyard=(), hand=(), interactive=()):
    me = _W1G6PlayerState(
        name="Me",
        graveyard=[_w1g6_card(set_pool, n) for n in graveyard],
        hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Swamp")] * 8,
    )
    opp = _W1G6PlayerState(name="Opp", library=[_w1g6_card(set_pool, "Forest")] * 8)
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game


def _w1g6_enter(game, set_pool, seat, name):
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_settle(game):
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)


def _w1g6_named(game, seat, name):
    return [p for p in game.controlled_by(seat) if p.card.name == name]


def test_w1g6_bladewings_thrall_returns_when_a_dragon_enters(set_pool):
    """"When a Dragon enters, you may return this card from your graveyard to
    the battlefield." Shivan Dragon enters: the Thrall comes back, and has
    flying while its controller controls a Dragon."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"])
    _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Bladewing's Thrall"]
    _w1g6_settle(game)
    (thrall,) = _w1g6_named(game, 0, "Bladewing's Thrall")
    assert not game.players[0].graveyard
    assert game._has_keyword(thrall, "flying")


def test_w1g6_bladewings_thrall_ignores_a_creature_that_is_not_a_dragon(set_pool):
    """The trigger's own noun phrase is asked of the entering permanent from
    the graveyard too — a Grizzly Bears triggers nothing."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"])
    _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert not game.stack
    assert [card.name for card in game.players[0].graveyard] == ["Bladewing's Thrall"]


def test_w1g6_bladewings_thrall_returns_under_its_owner_for_an_opponents_dragon(set_pool):
    """Ruling 2017-11-17: it "triggers even if a Dragon enters the battlefield
    under an opponent's control. The owner of Bladewing's Thrall, not the
    controller of that Dragon, will control Bladewing's Thrall." Asked, and
    declined, it stays."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"], interactive={0})
    _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, "Bladewing's Thrall", accept=True)
    _w1g6_resolve_stack(game)
    (thrall,) = _w1g6_named(game, 0, "Bladewing's Thrall")
    # No Dragon of its controller's: no flying.
    assert not game._has_keyword(thrall, "flying")

    declined = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"], interactive={0})
    _w1g6_enter(declined, set_pool, 0, "Shivan Dragon")
    declined.resolve_top_of_stack()
    assert declined.confirm_optional_pay(0, "Bladewing's Thrall", accept=False)
    _w1g6_resolve_stack(declined)
    assert [card.name for card in declined.players[0].graveyard] == ["Bladewing's Thrall"]


def _w1g6_cast_bladewing(game):
    game._close_current_priority_step()
    assert game.queue_from_hand(0, "Bladewing the Risen").supported


def test_w1g6_bladewing_the_risen_offers_only_a_dragon_permanent_card(set_pool):
    """"…return target Dragon permanent card from your graveyard to the
    battlefield." The picker offers the Shivan Dragon and neither the Grizzly
    Bears nor the Lightning Bolt beside it."""
    game = _w1g6_table(
        set_pool, hand=["Bladewing the Risen"],
        graveyard=["Grizzly Bears", "Shivan Dragon", "Lightning Bolt"],
    )
    spec = game.cast_target_spec(0, _w1g6_card(set_pool, "Bladewing the Risen"))
    assert [t["name"] for t in spec["valid_targets"]] == ["Shivan Dragon"]
    _w1g6_cast_bladewing(game)
    _w1g6_settle(game)
    assert {p.card.name for p in game.controlled_by(0)} == {
        "Bladewing the Risen", "Shivan Dragon",
    }
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g6_bladewing_the_risen_asked_names_its_dragon_and_may_decline(set_pool):
    """An asked seat names the target as the trigger goes on the stack (CR
    603.3d) — offered the Dragon alone — and then answers the "may"."""
    for accept in (True, False):
        game = _w1g6_table(
            set_pool, hand=["Bladewing the Risen"],
            graveyard=["Grizzly Bears", "Shivan Dragon"], interactive={0},
        )
        _w1g6_cast_bladewing(game)
        game.resolve_top_of_stack()
        (choice,) = game.pending_choices
        assert choice.kind == "trigger_target"
        assert [t["name"] for t in choice.data["targets"]] == ["Shivan Dragon"]
        assert game.resolve_pending_choice(
            "trigger_target", 0, seat=0, graveyard_index=1
        )
        game.resolve_top_of_stack()
        assert game.confirm_optional_pay(0, "Bladewing the Risen", accept=accept)
        _w1g6_resolve_stack(game)
        returned = [p.card.name for p in game.controlled_by(0)]
        assert ("Shivan Dragon" in returned) is accept


def test_w1g6_bladewing_the_risen_does_nothing_when_its_target_leaves_first(set_pool):
    """CR 608.2b in response: the targeted Dragon card leaves the graveyard
    with the trigger on the stack, so the trigger has no legal target and
    nothing comes back — and no other card is taken in its place."""
    game = _w1g6_table(
        set_pool, hand=["Bladewing the Risen"],
        graveyard=["Shivan Dragon", "Shivan Dragon"],
    )
    _w1g6_cast_bladewing(game)
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Bladewing the Risen"]
    pile = game.players[0].graveyard
    game.players[0].exile.append(pile.pop(0))
    game.players[0].exile.append(pile.pop(0))
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Bladewing the Risen"]


def test_w1g6_bladewing_the_risen_pumps_dragon_creatures(set_pool):
    """"{B}{R}: Dragon creatures get +1/+1 until end of turn" — every Dragon,
    the opponent's too, and nothing else; gone at cleanup."""
    game = _w1g6_table(set_pool)
    bladewing = _w1g6_enter(game, set_pool, 0, "Bladewing the Risen")
    _w1g6_settle(game)
    theirs = _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(0, "Bladewing the Risen").supported
    _w1g6_resolve_stack(game)
    assert (bladewing.effective_power, bladewing.effective_toughness) == (5, 5)
    assert (theirs.effective_power, theirs.effective_toughness) == (6, 6)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    game.resolve_cleanup_step(0)
    assert (theirs.effective_power, theirs.effective_toughness) == (5, 5)


# --- The drive list: Dragons supported on arrival ---------------------------


def test_w1g6_dragon_tyrant_is_kept_for_four_red_and_sacrificed_without(set_pool):
    """"At the beginning of your upkeep, sacrifice this creature unless you
    pay {R}{R}{R}{R}": four Mountains pay it, none cannot. It has flying,
    trample and double strike, and "{R}: +1/+0" pumps it."""
    for mountains in (4, 0):
        game = _w1g6_table(set_pool)
        tyrant = _w1g6_enter(game, set_pool, 0, "Dragon Tyrant")
        lands = [_w1g6_enter(game, set_pool, 0, "Mountain") for _ in range(mountains)]
        game.enforce_mana_costs = True
        game.start_turn(0)
        _w1g6_settle(game)
        assert game.is_on_battlefield(tyrant) is bool(mountains)
        assert all(land.tapped for land in lands)
    game = _w1g6_table(set_pool)
    tyrant = _w1g6_enter(game, set_pool, 0, "Dragon Tyrant")
    assert all(
        game._has_keyword(tyrant, word)
        for word in ("flying", "trample", "double strike")
    )
    assert game.activate_permanent_ability(0, "Dragon Tyrant").supported
    _w1g6_resolve_stack(game)
    assert tyrant.effective_power == 7


def test_w1g6_dragon_mage_wheels_both_hands_on_combat_damage(set_pool):
    """"Whenever this creature deals combat damage to a player, each player
    discards their hand, then draws seven cards." """
    from tests.helpers import declare_attack as _w1g6_declare_attack

    game = _w1g6_table(set_pool, hand=["Lightning Bolt", "Swamp"])
    game.players[1].hand = [_w1g6_card(set_pool, "Forest")]
    _w1g6_enter(game, set_pool, 0, "Dragon Mage")
    _w1g6_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g6_settle(game)
    assert game.players[1].life == 15
    assert len(game.players[0].hand) == 7 and len(game.players[1].hand) == 7
    assert sorted(c.name for c in game.players[0].graveyard) == ["Lightning Bolt", "Swamp"]
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]


def test_w1g6_dragonstalker_blocks_a_dragon_unharmed_and_dragons_cannot_block_it(set_pool):
    """"Protection from Dragons" (CR 702.16): blocking a Shivan Dragon it is
    dealt nothing and deals its 3, and a Dragon cannot block it."""
    game = _w1g6_table(set_pool)
    stalker = _w1g6_enter(game, set_pool, 1, "Dragonstalker")
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    _w1g6_settle(game)
    assert game.is_on_battlefield(stalker) and stalker.damage_marked == 0
    assert dragon.damage_marked == 3

    game = _w1g6_table(set_pool)
    _w1g6_enter(game, set_pool, 0, "Dragonstalker")
    _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "cannot block" in why

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.damage_redirects import redirects_on as _w1g7_redirects_on
from engine.face_down import (is_face_down as _w1g7_is_face_down,
                              morph_cost as _w1g7_morph_cost)
from engine.mana_payment import mana_cost_from_symbols as _w1g7_symbols
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.special_actions import (
    take_permanent_special_action as _w1g7_take_special_action)
from engine.targeting import derive_instruction_spec as _w1g7_instruction_spec
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_perm(card):
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_game(mine=(), theirs=(), *, hand=(), their_hand=()):
    me = _W1G7PlayerState(
        name="P0", battlefield=[_w1g7_perm(c) for c in mine], hand=list(hand), life=20,
    )
    them = _W1G7PlayerState(
        name="P1", battlefield=[_w1g7_perm(c) for c in theirs],
        hand=list(their_hand), life=20,
    )
    game = _W1G7Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    return game


def _w1g7_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Goblin Psychopath -------------------------------------------------------
#
# "Whenever this creature attacks or blocks, flip a coin. If you lose the flip,
# the next time it would deal combat damage this turn, it deals that damage to
# you instead." A CR 614.9 redirect of its own next combat damage to anyone,
# armed on resolution (ruling 2004-10-04: "resolves before combat damage is
# assigned"). The flip is the engine's (``handlers/_common.flip_coin``),
# fixed here through the module ``control_flow`` reads it from.


def _w1g7_flip(monkeypatch, won):
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: won
    )


def _w1g7_psychopath_attacks(set_pool, monkeypatch, *, won, blockers=(), blocks=None):
    _w1g7_flip(monkeypatch, won)
    game = _w1g7_game(mine=[set_pool("SCG")["Goblin Psychopath"]], theirs=list(blockers))
    _w1g7_declare_attack(game, 0, blocks=blocks or {})
    _w1g7_resolve_stack(game)
    return game


def test_w1g7_goblin_psychopath_losing_the_flip_hits_its_controller(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    assert any("lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 15 and game.players[1].life == 20
    assert any(
        "5 damage to P1 is dealt to P0 instead (Goblin Psychopath)" in line
        for line in game.log
    )


def test_w1g7_goblin_psychopath_winning_the_flip_deals_its_damage(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=True)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 15


def test_w1g7_goblin_psychopath_one_time_covers_every_blocker(set_pool, monkeypatch):
    """"The next time" is one time (CR 510.2: combat damage is dealt at once):
    blocked by two, both blockers' shares go to its controller."""
    pool = set_pool("2ED")
    game = _w1g7_psychopath_attacks(
        set_pool, monkeypatch, won=False,
        blockers=(pool["Grizzly Bears"], pool["Hill Giant"]), blocks={0: 0, 1: 0},
    )
    game.advance_combat_phase()
    assert game.current_step == "combat_damage"
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 3}})
    assert ok, why
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == 15
    assert [c.name for c in game.players[1].graveyard] == []
    assert [c.name for c in game.players[0].graveyard] == ["Goblin Psychopath"]
    # The time is over once the step's dealing is (``end_simultaneous_redirects``).
    assert _w1g7_redirects_on(game.players[0]) == []


def test_w1g7_goblin_psychopath_blocking_and_losing_sends_its_damage_home(
    set_pool, monkeypatch
):
    _w1g7_flip(monkeypatch, False)
    giant = set_pool("2ED")["Hill Giant"]
    game = _w1g7_game(mine=[giant], theirs=[set_pool("SCG")["Goblin Psychopath"]])
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_resolve_stack(game)
    assert any("Goblin Psychopath: lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    # Its 5 went to its own controller; the Giant's 3 still landed on it.
    assert game.players[1].life == 15
    assert _w1g7_named(game, 0, "Hill Giant").damage_marked == 0
    assert _w1g7_named(game, 1, "Goblin Psychopath").damage_marked == 3


def test_w1g7_goblin_psychopath_gone_before_damage_hurts_nobody(set_pool, monkeypatch):
    """The ruling's point: the trigger resolves first, "This gives you a chance
    to possibly get rid of it before it hurts you." Removed from the battlefield
    after the flip, it deals no damage and the record moves none."""
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    psychopath = _w1g7_named(game, 0, "Goblin Psychopath")
    game.players[0].hand.append(set_pool("2ED")["Unsummon"])
    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[psychopath.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 20


def test_w1g7_goblin_psychopath_compiles_its_whole_line(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Goblin Psychopath"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported
    steps = trigger.instruction.payload["steps"]
    assert [s.kind for s in steps] == ["flip_coin", "if_then"]
    (redirect,) = steps[1].payload["then"]
    assert redirect.payload == {"protects": "any", "combat_only": True, "uses": 1}
    # It targets nothing, so nothing is asked of the picker.
    assert _w1g7_instruction_spec([trigger.instruction]) is None


# --- Karona's Zealot ---------------------------------------------------------
#
# "When this creature is turned face up, all damage that would be dealt to it
# this turn is dealt to target creature instead." Rulings (2018-03-16): a target
# that has left or stopped being a creature takes nothing — later damage stays
# on the Zealot — and the damaged permanent's controller orders replacements.


def _w1g7_turn_up_zealot(set_pool, game, seat=0):
    zealot = set_pool("SCG")["Karona's Zealot"]
    player = game.players[seat]
    player.hand.append(zealot)
    game.enforce_mana_costs = True
    player.mana_pool.update({"C": 3})
    assert game.queue_from_hand(seat, "Karona's Zealot", alternative_cost=True).supported
    _w1g7_resolve_stack(game)
    (permanent,) = [p for p in game.controlled_by(seat) if _w1g7_is_face_down(p)]
    permanent.metadata["summoning_sickness_turn"] = -99
    for symbol, count in _w1g7_symbols(_w1g7_morph_cost(zealot)).items():
        key = "C" if symbol == "generic" else symbol
        player.mana_pool[key] = player.mana_pool.get(key, 0) + count
    game.priority_player_index = seat
    assert _w1g7_take_special_action(game, seat, permanent, "turn_face_up") is None
    assert sum(player.mana_pool.values()) == 0
    game.enforce_mana_costs = False
    return permanent


def _w1g7_bolt(set_pool, game, target, seat=1):
    game.players[seat].hand.append(set_pool("2ED")["Lightning Bolt"])
    assert game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()


def test_w1g7_karonas_zealot_moves_all_its_damage_this_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"], pool["Wall of Stone"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    (trigger,) = [item for item in game.stack if item.card.name == "Karona's Zealot"]
    wall = _w1g7_named(game, 1, "Wall of Stone")
    # The trigger's target, named by id as an announcement names it.
    trigger.target_permanent_id = [wall.permanent_id]
    _w1g7_resolve_stack(game)
    assert any(
        "all damage that would be dealt to Karona's Zealot this turn is dealt to "
        "Wall of Stone instead" in line for line in game.log
    )
    # Every instance this turn, not the next one: two Bolts, both moved.
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 3
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 6


def test_w1g7_karonas_zealot_target_gone_leaves_the_damage_on_it(set_pool):
    """The ruling's example: the 1/1 took the first 3 and died; the next 3 has
    nowhere to go and is dealt to the Zealot (CR 614.9)."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0
    assert "Grizzly Bears" in [c.name for c in game.players[1].graveyard]
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_redirect_ends_with_the_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    assert _w1g7_redirects_on(zealot)
    game.resolve_cleanup_step(0)
    assert _w1g7_redirects_on(zealot) == []
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_targets_a_creature(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Karona's Zealot"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported and trigger.condition.kind == "turned_face_up"
    spec = _w1g7_instruction_spec([trigger.instruction])
    assert spec is not None and spec.get("kind") == "creature", spec


@_w1g7_pytest.mark.parametrize("asked", [False, True], ids=["default", "asked"])
def test_w1g7_karonas_zealot_beside_a_shield_its_controller_orders(set_pool, asked):
    """CR 616.1: a prevention shield on the Zealot and its redirect contend over
    one Bolt, and the Zealot's controller chooses (ruling 2018-03-16). A seat
    nobody asks moves the damage first (redirects sit ahead of the shields,
    ``replacements/registry.py``); one that is asked may spend the shield."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]], hand=[pool["Healing Salve"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    giant = _w1g7_named(game, 1, "Hill Giant")
    assert game.queue_from_hand(
        0, "Healing Salve", mode_index=1, target_permanent_ids=[zealot.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    if asked:
        game.interactive_seats = {0}
    game.players[1].hand.append(pool["Lightning Bolt"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[zealot.permanent_id]
    ).supported
    if not asked:
        _w1g7_resolve_stack(game)
        assert zealot.damage_marked == 0 and giant.damage_marked == 3
        return
    game.resolve_top_of_stack()
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert order.player_index == 0 and len(order.data["options"]) == 2
    keys = list(order.data["_keys"])
    shield_first = next(
        i for i, key in enumerate(keys) if key != "_apply_recorded_redirect"
    )
    assert "_apply_recorded_redirect" in keys
    assert game.resolve_pending_choice("effect_order", 0, option_index=shield_first)
    _w1g7_resolve_stack(game)
    assert zealot.damage_marked == 0 and giant.damage_marked == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Xantid Swarm: "Whenever this creature attacks, defending player can't cast
# spells this turn." The seat the attack froze (CR 506.2, 603.10), through
# the cast-prohibition table every cast path asks.
from engine import Game as _W1G8Game
from engine.cast_prohibitions import cast_prohibition as _w1g8_cast_prohibition
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_combat(set_pool, attackers, *, seats=2, hands=None):
    """*attackers* on seat 0, every seat holding *hands*[seat], at seat 0's
    declare-attackers step."""
    lea = set_pool("LEA")
    players = [
        _W1G8PlayerState(
            name=f"P{seat}", hand=list((hands or {}).get(seat, ())),
            library=[lea["Plains"]] * 5,
        )
        for seat in range(seats)
    ]
    game = _W1G8Game(players=players)
    game.enforce_mana_costs = False
    mine = []
    for card in attackers:
        perm = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        mine.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game, mine


def test_w1g8_xantid_swarm_stops_the_defending_player_casting_this_turn(set_pool):
    """Before the trigger resolves the defender may still cast (2016-06-08:
    "The defending player may cast spells before Xantid Swarm's triggered
    ability resolves."); once it has, every spell is refused — an instant in
    combat and a creature later — while the attacker casts freely."""
    lea = set_pool("LEA")
    growth = lea["Giant Growth"]
    game, (swarm,) = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"]],
        hands={0: [growth], 1: [growth, growth, lea["Grizzly Bears"]]},
    )
    bears = _W1G8Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    assert game.declare_attackers(0, [0], 1)[0]
    assert [item.card.name for item in game.stack] == ["Xantid Swarm"]
    # In response: allowed.
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    assert any("P1 can't cast any spells this turn (Xantid Swarm)" in line for line in game.log)

    refused = game.cast_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert "can't cast any spells this turn" in refused.details
    prohibited = _w1g8_cast_prohibition(game, 1, lea["Grizzly Bears"])
    assert prohibited is not None and prohibited.kind == "casting_forbidden_this_turn"
    assert len(game.players[1].hand) == 2
    # The attacker is not bound.
    assert _w1g8_cast_prohibition(game, 0, growth) is None
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[swarm.permanent_id]).supported


def test_w1g8_xantid_swarm_binds_only_the_player_it_attacked(set_pool):
    """2016-06-08: "In a multiplayer game, only the player Xantid Swarm
    attacked is affected. Other defending players may cast spells." Swarm at
    P2, a Bear at P1: only P2 is stopped."""
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"], lea["Grizzly Bears"]], seats=3,
    )
    ok, why = game.declare_attackers(0, [0, 1], attacker_targets={0: 2, 1: 1})
    assert ok, why
    _w1g8_resolve_stack(game)
    growth = lea["Giant Growth"]
    assert _w1g8_cast_prohibition(game, 2, growth) is not None
    assert _w1g8_cast_prohibition(game, 1, growth) is None
    assert _w1g8_cast_prohibition(game, 0, growth) is None


def test_w1g8_xantid_swarm_ban_ends_with_the_turn(set_pool):
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(set_pool, [set_pool("SCG")["Xantid Swarm"]])
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g8_resolve_stack(game)
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is not None
    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Statics, sweeps, types and counters. Each card is put where it belongs on a
# real board, driven through the engine's own entry points (an activation, a
# declared attack or block, a death, the upkeep), and the board, the counters
# and the log are read afterwards — for a person answering each prompt and for
# a seat nobody asks.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import counters_on as _w1g9_counters_on
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_activation_spec as _w1g9_activation_spec
from tests.helpers import declare_attack as _w1g9_declare_attack
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_permanent(card):
    permanent = _W1G9Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_game(mine=(), theirs=(), *, interactive=False):
    p1 = _W1G9PlayerState(name="A", battlefield=list(mine),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g9_plus1(permanent) -> int:
    return _w1g9_counters_on(permanent, "+1/+1")


# --- Thundercloud Elemental --------------------------------------------------


def test_w1g9_thundercloud_taps_every_creature_with_toughness_two_or_less(set_pool):
    """"{3}{U}: Tap all creatures with toughness 2 or less." Both sides, read
    as the ability resolves: a Bear (2) on each side and an Elf (1) are
    tapped; a Hill Giant (3) and the Elemental itself (4) are not."""
    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    my_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    their_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([elemental, my_bear], [their_bear, elf, giant])
    result = game.activate_permanent_ability(
        0, "Thundercloud Elemental", ability_index=0,
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert my_bear.tapped and their_bear.tapped and elf.tapped
    assert not giant.tapped and not elemental.tapped
    assert any("Thundercloud Elemental tapped" in line for line in game.log)


def test_w1g9_thundercloud_reads_toughness_as_it_resolves(set_pool):
    """The toughness is the creature's as the sweep resolves (layer 7): a Bear
    given +0/+1 in response has toughness 3 and stays untapped."""
    from engine.pt import add_pt_modifier

    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([elemental], [bear])
    result = game.queue_permanent_ability(
        0, "Thundercloud Elemental", ability_index=0,
    )
    assert result.supported, result.details
    assert [item.card.name for item in game.stack] == ["Thundercloud Elemental"]
    add_pt_modifier(bear, 0, 1, until="end_of_turn")
    assert bear.effective_toughness == 3
    _w1g9_resolve_stack(game)
    assert not bear.tapped
    assert any("nothing to tap or untap" in line for line in game.log)


def test_w1g9_thundercloud_strips_flying_from_every_other_creature(set_pool):
    """Its second ability, compiled on arrival: "All other creatures lose
    flying until end of turn" — the Elemental keeps its own."""
    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    djinn = _w1g9_permanent(_W1G9_CATALOG["Mahamoti Djinn"])
    game, _p1, _p2 = _w1g9_game([elemental], [djinn])
    result = game.activate_permanent_ability(
        0, "Thundercloud Elemental", ability_index=1,
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game._has_keyword(djinn, "flying")
    assert game._has_keyword(elemental, "flying")


# --- Mercurial Kite -------------------------------------------------------------


def _w1g9_untap_step(game, seat):
    """Run *seat*'s untap step the way a turn does."""
    game.active_player_index = seat
    game.turn += 1
    game.start_turn(seat)


def test_w1g9_mercurial_kite_taps_and_freezes_the_creature_it_damages(set_pool):
    """"Whenever this creature deals combat damage to a creature, tap that
    creature. That creature doesn't untap during its controller's next untap
    step." Blocked by a Wall of Air (0/5), the Kite's damage taps the Wall;
    the Wall's controller's next untap step leaves it tapped and the one after
    untaps it."""
    scg = set_pool("SCG")
    kite = _w1g9_permanent(scg["Mercurial Kite"])
    wall = _w1g9_permanent(_W1G9_CATALOG["Wall of Air"])
    game, _p1, _p2 = _w1g9_game([kite], [wall])
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    assert game.is_on_battlefield(wall) and wall.tapped
    assert any("Wall of Air won't untap" in line for line in game.log)
    _w1g9_untap_step(game, 1)
    assert wall.tapped, "held down for its controller's next untap step"
    _w1g9_untap_step(game, 0)
    _w1g9_untap_step(game, 1)
    assert not wall.tapped, "the one after untaps it"


def test_w1g9_mercurial_kite_damaging_a_player_holds_nothing_down(set_pool):
    """Unblocked, the Kite deals its damage to a player: the condition names a
    creature, so nothing triggers and nothing is held down."""
    scg = set_pool("SCG")
    kite = _w1g9_permanent(scg["Mercurial Kite"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g9_game([kite], [bear])
    _w1g9_declare_attack(game, 0)
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    assert p2.life == 18
    assert not bear.tapped
    assert not any("won't untap" in line for line in game.log)


# --- Ageless Sentinels ----------------------------------------------------------


def test_w1g9_ageless_sentinels_becomes_a_bird_giant_and_can_attack(set_pool):
    """"When this creature blocks, it becomes a Bird Giant, and it loses
    defender." Both creature types replace Wall (CR 205.1a; the 2004-10-04
    ruling "It becomes both creature type Giant and creature type Bird"), the
    change outlives the turn (CR 611.2a), and without defender it attacks on
    its controller's turn (the 2005-08-01 ruling)."""
    scg = set_pool("SCG")
    sentinels = _w1g9_permanent(scg["Ageless Sentinels"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([bear], [sentinels])
    assert sentinels.has_type("wall") and game._has_keyword(sentinels, "defender")
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    _w1g9_resolve_stack(game)
    assert sentinels.has_type("bird") and sentinels.has_type("giant")
    assert not sentinels.has_type("wall")
    assert not game._has_keyword(sentinels, "defender")
    assert game._has_keyword(sentinels, "flying")
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    _w1g9_untap_step(game, 1)
    assert sentinels.has_type("bird") and not sentinels.has_type("wall")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        1, [game.battlefield_index_of(sentinels)], defending_player_index=0,
    )
    assert ok, why


def test_w1g9_ageless_sentinels_left_and_back_is_a_wall_again(set_pool):
    """The change is the permanent's (CR 400.7): returned to the battlefield
    it is a new object, a Wall with defender."""
    scg = set_pool("SCG")
    sentinels = _w1g9_permanent(scg["Ageless Sentinels"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g9_game([bear], [sentinels])
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    _w1g9_resolve_stack(game)
    assert sentinels.has_type("giant")
    game.remove_from_battlefield(sentinels)
    again = _W1G9Permanent(card=scg["Ageless Sentinels"])
    game._put_permanent_onto_battlefield(1, again, None)
    assert again.has_type("wall") and not again.has_type("giant")
    assert game._has_keyword(again, "defender")


# --- Ambush Commander -----------------------------------------------------------


def test_w1g9_ambush_commander_makes_its_controllers_forests_green_elves(set_pool):
    """"Forests you control are 1/1 green Elf creatures that are still lands."
    Layer 4 (creature, Elf, still a Forest land), 5 (green) and 7b (1/1) on
    its controller's Forests; an opponent's Forest is untouched; and when the
    Commander leaves, the Forests are lands again (CR 611.3a)."""
    from engine.object_colors import object_colors

    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    island = _w1g9_permanent(_W1G9_CATALOG["Island"])
    their_forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([commander, forest, island], [their_forest])
    assert forest.is_creature and forest.has_type("elf")
    assert forest.has_type("land") and forest.has_type("forest")
    assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert set(object_colors(game, forest)) == {"G"}
    assert not island.is_creature
    assert not their_forest.is_creature and not their_forest.has_type("elf")
    game.remove_from_battlefield(commander)
    game._recompute_continuous_effects()
    assert not forest.is_creature and not forest.has_type("elf")


def test_w1g9_ambush_commander_sacrifices_a_forest_as_an_elf(set_pool):
    """"{1}{G}, Sacrifice an Elf: Target creature gets +3/+3 until end of
    turn." An animated Forest is an Elf, so it pays the cost."""
    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([commander, forest, bear])
    spec = _w1g9_activation_spec(_w1g9_compile(scg["Ambush Commander"]).activated_abilities[0])
    assert spec["cost_spec"]["filter"] == {"subtype_filter": "elf"}
    result = game.activate_permanent_ability(
        0, "Ambush Commander", ability_index=0,
        target_permanent_ids=[bear.permanent_id],
        cost_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(forest)
    assert (bear.effective_power, bear.effective_toughness) == (5, 5)


def test_w1g9_a_forest_that_just_arrived_is_summoning_sick(set_pool):
    """The 2008-08-01 ruling (CR 302.6): an animated land that has not been
    controlled continuously since its controller's turn began can neither
    attack nor be tapped for mana — while one controlled since then can."""
    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    old_forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([commander, old_forest])
    new_forest = _W1G9Permanent(card=_W1G9_CATALOG["Forest"])
    game._put_permanent_onto_battlefield(0, new_forest, None)
    assert new_forest.is_creature and game._is_summoning_sick(new_forest)
    refusal = game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=new_forest.permanent_id,
    )
    assert refusal is not None and not new_forest.tapped
    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=old_forest.permanent_id,
    ) is None
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [game.battlefield_index_of(new_forest)], defending_player_index=1,
    )
    assert not ok


def test_w1g9_a_land_animator_reads_any_creature_type_it_prints(set_pool):
    """Name-agnostic (``engine/land_animation.py``): an invented creature
    printing "Mountains you control are 2/2 red Goblin creatures that are
    still lands." animates Mountains as red Goblins, and one printing a word
    that is neither a colour nor a creature type is refused rather than
    animated as if the word were not there."""
    import dataclasses

    scg = set_pool("SCG")
    goblin_lord = dataclasses.replace(
        scg["Ambush Commander"], name="Invented Goblin Commander",
        oracle_text="Mountains you control are 2/2 red Goblin creatures that are still lands.",
    )
    assert _w1g9_compile(goblin_lord).supported
    refused = dataclasses.replace(
        goblin_lord, name="Invented Artifact Commander",
        oracle_text="Mountains you control are 2/2 artifact Goblin creatures that are still lands.",
    )
    assert not _w1g9_compile(refused).supported
    mountain = _w1g9_permanent(_W1G9_CATALOG["Mountain"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([_w1g9_permanent(goblin_lord), mountain, forest])
    assert mountain.is_creature and mountain.has_type("goblin")
    assert (mountain.effective_power, mountain.effective_toughness) == (2, 2)
    assert not forest.is_creature


# --- Forgotten Ancient ----------------------------------------------------------


def _w1g9_ancient_board(scg, *, interactive, counters=3):
    ancient = _w1g9_permanent(scg["Forgotten Ancient"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    their_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, p1, p2 = _w1g9_game([ancient, bear, giant], [their_bear], interactive=interactive)
    if counters:
        game.place_plus1_counters(ancient, counters)
    return game, ancient, bear, giant, their_bear


def _w1g9_to_the_distribution(game):
    """Seat 0's upkeep, with the ancient's trigger resolved up to the prompt
    a person answers: the "you may" first, then the distribution."""
    game.turn = 2
    game.start_turn(0)
    assert not game.resolve_top_of_stack(), "held for the 'may' answer"
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    (choice,) = game.pending_choices_of("counter_distribution", 0)
    return choice


def test_w1g9_forgotten_ancient_moves_counters_where_its_controller_says(set_pool):
    """"At the beginning of your upkeep, you may move any number of +1/+1
    counters from this creature onto other creatures." The 2022-12-08 ruling:
    nothing is targeted, and how many and onto which creatures is chosen as
    the ability resolves — so a person splits three counters between their
    Bear and an opponent's (any creature but itself), and the move is one
    action (CR 122.5)."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    choice = _w1g9_to_the_distribution(game)
    offered = {perm.permanent_id for perm in game.live_counter_distribution(choice)}
    assert offered == {bear.permanent_id, giant.permanent_id, their_bear.permanent_id}
    assert game.counter_distribution_maximum(choice) == 3
    assert game.confirm_counter_distribution(
        0, [bear.permanent_id, their_bear.permanent_id], [2, 1],
    )
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 0
    assert (_w1g9_plus1(bear), _w1g9_plus1(their_bear), _w1g9_plus1(giant)) == (2, 1, 0)
    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
    assert not game.stack and not game.pending_choices


@_w1g9_pytest.mark.parametrize("ids_and_amounts", [
    "over_the_total", "onto_itself", "a_zero_share", "a_repeated_creature",
    "lists_that_do_not_pair",
])
def test_w1g9_forgotten_ancient_refuses_an_answer_the_card_does_not_allow(
    set_pool, ids_and_amounts,
):
    """Every bad answer is refused whole, with nothing moved and the prompt
    still owed: more counters than the source has, the source itself ("other
    creatures"), a share of none, a creature named twice, lists of different
    lengths."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    _w1g9_to_the_distribution(game)
    ids, amounts = {
        "over_the_total": ([bear.permanent_id, giant.permanent_id], [2, 2]),
        "onto_itself": ([ancient.permanent_id], [1]),
        "a_zero_share": ([bear.permanent_id], [0]),
        "a_repeated_creature": ([bear.permanent_id, bear.permanent_id], [1, 1]),
        "lists_that_do_not_pair": ([bear.permanent_id], [1, 1]),
    }[ids_and_amounts]
    assert not game.confirm_counter_distribution(0, ids, amounts)
    assert _w1g9_plus1(ancient) == 3
    assert game.pending_choices_of("counter_distribution", 0)


def test_w1g9_forgotten_ancient_may_move_none(set_pool):
    """"Any number" includes none: two empty lists keep every counter."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    _w1g9_to_the_distribution(game)
    assert game.confirm_counter_distribution(0, [], [])
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 3
    assert any("no +1/+1 counters moved" in line for line in game.log)


def test_w1g9_forgotten_ancient_default_grows_its_own_strongest_creature(set_pool):
    """A seat nobody asks takes the stated policy: every counter onto its own
    strongest other creature (the Hill Giant, power 3), none onto an
    opponent's."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=False)
    game.turn = 2
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 0
    assert (_w1g9_plus1(giant), _w1g9_plus1(bear), _w1g9_plus1(their_bear)) == (3, 0, 0)


def test_w1g9_forgotten_ancient_without_counters_offers_nothing(set_pool):
    """With no counter on it there is no move to offer (``offers
    ._action_is_takeable``): the upkeep asks nothing."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(
        set_pool("SCG"), interactive=True, counters=0,
    )
    game.turn = 2
    game.start_turn(0)
    _w1g9_resolve_stack(game)
    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.pending_choices_of("counter_distribution", 0)


def test_w1g9_forgotten_ancient_takes_a_counter_whenever_a_player_casts(set_pool):
    """Its first ability, compiled on arrival: "Whenever a player casts a
    spell, you may put a +1/+1 counter on this creature" — an opponent's
    spell included; the trigger resolves before the spell (the ruling)."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(
        set_pool("SCG"), interactive=False, counters=0,
    )
    game.players[1].hand.append(_W1G9_CATALOG["Giant Growth"])
    game.priority_player_index = 1
    result = game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[their_bear.permanent_id],
    )
    assert result.supported, result.details
    assert [item.card.name for item in game.stack] == ["Giant Growth", "Forgotten Ancient"]
    _w1g9_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g9_plus1(ancient) == 1


# --- Supported on arrival, driven: Nefashu, Carrion Feeder, Trap Digger, -------
# --- Daru Spiritualist ---------------------------------------------------------


@_w1g9_pytest.mark.parametrize("interactive", [False, True])
def test_w1g9_nefashu_shrinks_up_to_five_creatures_when_it_attacks(set_pool, interactive):
    """"Whenever this creature attacks, up to five target creatures each get
    -1/-1 until end of turn." A seat nobody asks names every opposing
    creature; a person names two of three, and only those shrink. The Elf
    named dies as the next step's state check runs."""
    scg = set_pool("SCG")
    nefashu = _w1g9_permanent(scg["Nefashu"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([nefashu], [bear, elf, giant], interactive=interactive)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    if interactive:
        (prompt,) = game.pending_choices_of("trigger_target", 0)
        assert prompt.data.get("up_to")
        assert game.confirm_trigger_target(
            0, permanent_ids=[bear.permanent_id, elf.permanent_id],
        )
    _w1g9_resolve_stack(game)
    game.advance_combat_phase()
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)
    assert not game.is_on_battlefield(elf)
    expected_giant = (3, 3) if interactive else (2, 2)
    assert (giant.effective_power, giant.effective_toughness) == expected_giant
    assert (nefashu.effective_power, nefashu.effective_toughness) == (5, 3)


def test_w1g9_carrion_feeder_eats_a_creature_and_cannot_block(set_pool):
    """"This creature can't block. Sacrifice a creature: Put a +1/+1 counter on
    this creature." """
    scg = set_pool("SCG")
    feeder = _w1g9_permanent(scg["Carrion Feeder"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([feeder, bear], [giant])
    result = game.activate_permanent_ability(
        0, "Carrion Feeder", ability_index=0, cost_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(bear)
    assert _w1g9_plus1(feeder) == 1 and feeder.effective_power == 2
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(0, {0: 0})
    assert not ok


def test_w1g9_trap_digger_springs_a_trapped_land_on_a_ground_attacker(set_pool):
    """"{2}{W}, {T}: Put a trap counter on target land you control. Sacrifice
    a land with a trap counter on it: This creature deals 3 damage to target
    attacking creature without flying." The counter goes only on the
    controller's own land; the sacrifice must be a trapped land, and the
    target an attacker without flying."""
    scg = set_pool("SCG")
    digger = _w1g9_permanent(scg["Trap Digger"])
    trapped = _w1g9_permanent(_W1G9_CATALOG["Plains"])
    plain = _w1g9_permanent(_W1G9_CATALOG["Plains"])
    their_land = _w1g9_permanent(_W1G9_CATALOG["Mountain"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    djinn = _w1g9_permanent(_W1G9_CATALOG["Mahamoti Djinn"])
    game, _p1, _p2 = _w1g9_game([digger, trapped, plain], [their_land, giant, djinn])
    refused = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=0, target_permanent_ids=[their_land.permanent_id],
    )
    assert not refused.supported
    result = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=0, target_permanent_ids=[trapped.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert _w1g9_counters_on(trapped, "trap") == 1
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [1, 2], defending_player_index=0)
    assert ok, why
    assert not game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[djinn.permanent_id],
        cost_permanent_ids=[trapped.permanent_id],
    ).supported, "a flyer is not a legal target"
    assert not game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[plain.permanent_id],
    ).supported, "an untrapped land pays nothing"
    result = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[trapped.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(trapped) and game.is_on_battlefield(plain)
    assert not game.is_on_battlefield(giant)


def test_w1g9_daru_spiritualist_toughens_a_targeted_cleric(set_pool):
    """"Whenever a Cleric creature you control becomes the target of a spell or
    ability, it gets +0/+2 until end of turn." The trigger resolves first, so
    the Spiritualist (a 1/1 Cleric) survives the Shock aimed at it."""
    scg = set_pool("SCG")
    spiritualist = _w1g9_permanent(scg["Daru Spiritualist"])
    game, _p1, p2 = _w1g9_game([spiritualist], [])
    p2.hand.append(_W1G9_CATALOG["Shock"])
    game.active_player_index = 1
    game.priority_player_index = 1
    result = game.queue_from_hand(
        1, "Shock", target_permanent_ids=[spiritualist.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert game.is_on_battlefield(spiritualist)
    assert spiritualist.effective_toughness == 3


@_w1g9_pytest.mark.full
def test_w1g9_the_seeded_games_exercise_the_ancient_and_the_faces(set_pool):
    """The AI simulator over Scourge with W1G9's trigger-driven cards pinned:
    a Forgotten Ancient's upkeep move and a Faces of the Past's choice each
    happen at least once (a floor, never a count)."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        manifest_set_path("SCG", include_measured=True), games=4, seed=7, max_turns=14,
        required_cards=["Forgotten Ancient", "Faces of the Past"],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    assert any("Forgotten Ancient: moved" in line for line in report.log_lines)
    assert any("Faces of the Past: chose" in line for line in report.log_lines)

# ==== end W1G9 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ======================================================


# ==== W2G2 ==========================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ======================================================


# ==== W2G3 ==========================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ======================================================


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ======================================================


# ==== W2G5 ==========================================================
# W2G5's tests go between this line and the "end W2G5" line.
#
# The promotion rehearsal's inventories and the deletion probe's readings:
# Skirk Volcanist's divided damage trigger, as a seat nobody asks divides it
# and as the AI weighs turning it face up; Eternal Dragon's graveyard
# ability in its controller's upkeep; Mercurial Kite's "its controller's next
# untap step" across a change of control; Bladewing the Risen's "Dragon
# creatures" on a Dragon that is not a creature.

from collections import Counter as _W2G5Counter
from dataclasses import replace as _w2g5_replace

import pytest as _w2g5_pytest

from engine import Game as _W2G5Game, PlayerState as _W2G5PlayerState
from engine import ai_simulator as _w2g5_ai_simulator
from engine.ai_special_actions import (
    choose_special_action as _w2g5_choose_special_action,
    take_chosen_special_action as _w2g5_take_chosen_special_action,
)
from engine.card_loader import load_catalog as _w2g5_load_catalog
from engine.control import change_control as _w2g5_change_control
from engine.face_down import face_down_card as _w2g5_face_down_card
from engine.models import Permanent as _W2G5Permanent
from engine.special_actions import (
    take_permanent_special_action as _w2g5_take_special_action,
)
from tests.helpers import declare_attack as _w2g5_declare_attack
from tests.helpers import resolve_stack as _w2g5_resolve_stack

_W2G5_CATALOG = {card.name: card for card in _w2g5_load_catalog()}


def _w2g5_card(set_pool, name):
    scg = set_pool("SCG")
    return scg[name] if name in scg else _W2G5_CATALOG[name]


def _w2g5_permanent(card, *, face_down=False):
    permanent = _W2G5Permanent(card=_w2g5_face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g5_volcanist_table(set_pool, theirs=(), mine=(), *, mountains=2):
    """Seat 0's face-down Skirk Volcanist beside *mountains* Mountains and
    *mine*, seat 1's *theirs*; seat 0 holds priority in its main phase, mana
    enforced, nobody asked anything."""
    volcanist = _w2g5_permanent(_w2g5_card(set_pool, "Skirk Volcanist"), face_down=True)
    own = [volcanist,
           *[_w2g5_permanent(_W2G5_CATALOG["Mountain"]) for _ in range(mountains)],
           *[_w2g5_permanent(_w2g5_card(set_pool, name)) for name in mine]]
    placed = {name: _w2g5_permanent(_w2g5_card(set_pool, name)) for name in theirs}
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="A", battlefield=own, library=[_W2G5_CATALOG["Island"]] * 10),
        _W2G5PlayerState(name="B", battlefield=list(placed.values()),
                         library=[_W2G5_CATALOG["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 3
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    placed.update({p.card.name: p for p in own[1 + mountains:]})
    return game, volcanist, placed


def _w2g5_alive(game, placed):
    return {name: game.is_on_battlefield(p) for name, p in placed.items()}


@_w2g5_pytest.mark.parametrize("theirs, dead", [
    (("Hill Giant", "Grizzly Bears"), {"Grizzly Bears"}),
    (("Llanowar Elves", "Grizzly Bears", "Hill Giant"), {"Llanowar Elves", "Grizzly Bears"}),
    (("Hill Giant", "Craw Wurm", "Grizzly Bears", "Llanowar Elves"),
     {"Llanowar Elves", "Grizzly Bears"}),
], ids=["giant-bears", "elves-bears-giant", "four"])
def test_w2g5_skirk_volcanist_divides_its_damage_where_it_kills(set_pool, theirs, dead):
    """"When this creature is turned face up, it deals 3 damage divided as you
    choose among one, two, or three target creatures." A seat nobody asks
    splits the 3 by what each share kills (CR 704.5g) — the lethal share
    first, the remainder one apiece. Validated backwards: the spread it gave
    before (1 apiece, or 2 + 1) killed nothing on the first and third boards
    and the Elves alone on the second."""
    game, volcanist, placed = _w2g5_volcanist_table(set_pool, theirs)

    assert _w2g5_take_special_action(game, 0, volcanist, "turn_face_up") is None
    _w2g5_resolve_stack(game)
    game.check_state_based_actions()

    assert {name for name, alive in _w2g5_alive(game, placed).items() if not alive} == dead
    dealt = [line for line in game.log if line.startswith("Skirk Volcanist dealt")]
    assert sum(int(line.split()[3]) for line in dealt) == 3, dealt


def test_w2g5_skirk_volcanist_with_nothing_opposing_harms_its_own_board_least(set_pool):
    """No opposing creature: a target is still owed (CR 603.3d). A Serra Angel
    lives through all 3, so it takes them — the Volcanist itself, the offer's
    first, died to them before; where every candidate dies, the one worth
    least does."""
    game, volcanist, placed = _w2g5_volcanist_table(
        set_pool, mine=("Savannah Lions", "Serra Angel"),
    )
    assert _w2g5_take_special_action(game, 0, volcanist, "turn_face_up") is None
    _w2g5_resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(volcanist)
    assert _w2g5_alive(game, placed) == {"Savannah Lions": True, "Serra Angel": True}
    assert placed["Serra Angel"].damage_marked == 3


def test_w2g5_skirk_volcanist_no_share_kills_so_the_damage_is_concentrated(set_pool):
    """A Serra Angel and a Craw Wurm: 3 damage kills neither, so it goes on one
    (the divided spell's policy — a share is measured against a toughness)
    rather than spread to no purpose."""
    game, volcanist, placed = _w2g5_volcanist_table(set_pool, ("Serra Angel", "Craw Wurm"))
    assert _w2g5_take_special_action(game, 0, volcanist, "turn_face_up") is None
    _w2g5_resolve_stack(game)
    assert sorted(p.damage_marked for p in placed.values()) == [0, 3]


def test_w2g5_the_ai_turns_skirk_volcanist_face_up_where_its_damage_kills(set_pool):
    """`ai_special_actions` rehearses the face-up and reads the trigger's
    default split, so the split decides whether the card is played at all:
    over an Elves, a Bears and a Giant, the spread (killing the Elves alone)
    read as two Mountains thrown away and nothing was proposed. Now the
    Elves and the Bears die for them."""
    game, volcanist, placed = _w2g5_volcanist_table(
        set_pool, ("Llanowar Elves", "Grizzly Bears", "Hill Giant"), mountains=3,
    )

    choice = _w2g5_choose_special_action(game, 0)

    assert choice is not None and choice.kind == "turn_face_up"
    _w2g5_take_chosen_special_action(game, 0, choice)
    _w2g5_resolve_stack(game)
    game.check_state_based_actions()
    assert _w2g5_alive(game, placed) == {
        "Llanowar Elves": False, "Grizzly Bears": False, "Hill Giant": True,
    }
    assert game.is_on_battlefield(volcanist) and volcanist.card.name == "Skirk Volcanist"


def test_w2g5_the_ai_leaves_skirk_volcanist_down_where_nothing_dies(set_pool):
    """The other half of the weighing: a lone Serra Angel survives 3, so two
    Mountains buy nothing and the face-down creature stays as it is."""
    game, volcanist, _placed = _w2g5_volcanist_table(set_pool, ("Serra Angel",), mountains=3)
    assert _w2g5_choose_special_action(game, 0) is None


# --- Eternal Dragon ---------------------------------------------------------------


def test_w2g5_eternal_dragon_comes_back_in_its_controllers_upkeep(set_pool):
    """"{3}{W}{W}: Return this card from your graveyard to your hand. Activate
    only during your upkeep." The simulator answers its own upkeep's priority
    (CR 117.3a) with the graveyard chooser, as it does for Shard Phoenix: the
    Dragon comes back, counted, and its five Plains pay for it."""
    players = [
        _W2G5PlayerState(name="AI-A", graveyard=[_w2g5_card(set_pool, "Eternal Dragon")],
                         library=[_W2G5_CATALOG["Plains"]] * 8),
        _W2G5PlayerState(name="AI-B", library=[_W2G5_CATALOG["Plains"]] * 8),
    ]
    game = _w2g5_ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=_w2g5_ai_simulator._resolve_pending_choices,
    )
    report = _w2g5_ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = _w2g5_ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = 0
    for _ in range(5):
        game._put_permanent_onto_battlefield(0, _w2g5_permanent(_W2G5_CATALOG["Plains"]), None)
    game._set_phase_and_step("beginning", "upkeep")

    game._resolve_priority_window()

    assert [card.name for card in game.players[0].hand] == ["Eternal Dragon"]
    assert game.players[0].graveyard == []
    assert report.activations_from_graveyard == _W2G5Counter({"Eternal Dragon": 1})
    assert all(p.tapped for p in game.controlled_by(0))


# --- Mercurial Kite ---------------------------------------------------------------


def _w2g5_untap_step(game, seat):
    game.active_player_index = seat
    game.turn += 1
    game.start_turn(seat)


def test_w2g5_mercurial_kites_untap_step_is_whoever_controls_the_creature(set_pool):
    """"That creature doesn't untap during its controller's next untap step."
    The marker follows the creature, not the seat that controlled it when it
    was dealt the damage — Tamiyo, the Moon Sage's ruling on the same words
    (2012-05-01): "If the permanent changes controllers before its first
    controller's next untap step has come around, then it won't untap during
    its new controller's next untap step." So the Kite's controller steals
    the Wall it froze: its own next untap step leaves the Wall tapped, the one
    after untaps it."""
    kite = _w2g5_permanent(_w2g5_card(set_pool, "Mercurial Kite"))
    wall = _w2g5_permanent(_W2G5_CATALOG["Wall of Air"])
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="A", battlefield=[kite], library=[_W2G5_CATALOG["Island"]] * 10),
        _W2G5PlayerState(name="B", battlefield=[wall], library=[_W2G5_CATALOG["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    _w2g5_declare_attack(game, 0, blocks={0: 0})
    for _ in range(3):
        game.advance_combat_phase()
        _w2g5_resolve_stack(game)
    assert game.is_on_battlefield(wall) and wall.tapped

    _w2g5_change_control(wall, 0, source=kite)
    game._sync_control()
    assert game.controller_index_of(wall) == 0

    _w2g5_untap_step(game, 1)
    assert wall.tapped, "seat 1's untap step no longer reaches it"
    _w2g5_untap_step(game, 0)
    assert wall.tapped, "its new controller's next untap step is the one named"
    _w2g5_untap_step(game, 1)
    _w2g5_untap_step(game, 0)
    assert not wall.tapped, "and the one after untaps it"


# --- Bladewing the Risen ----------------------------------------------------------


def test_w2g5_bladewings_pump_reaches_dragon_creatures_and_no_other_dragon(set_pool):
    """"{B}{R}: Dragon creatures get +1/+1 until end of turn." The probe saw
    "creatures" ignored by the rule that matched; it is the handler's own head
    (``buff_creatures_global`` asks ``is_creature`` of every permanent), so a
    Dragon that is not a creature — an invented Kindred Enchantment — Dragon
    (CR 308.2: a kindred has creature types) — is a Dragon to ``has_type``
    and still gets nothing."""
    bladewing = _w2g5_permanent(_w2g5_card(set_pool, "Bladewing the Risen"))
    hoard_card = _w2g5_replace(
        _W2G5_CATALOG["Bad Moon"], name="Probe Hoard",
        type_line="Kindred Enchantment — Dragon", oracle_text="",
    )
    hoard = _w2g5_permanent(hoard_card)
    shivan = _w2g5_permanent(_W2G5_CATALOG["Shivan Dragon"])
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="A", battlefield=[bladewing, hoard],
                         library=[_W2G5_CATALOG["Swamp"]] * 10),
        _W2G5PlayerState(name="B", battlefield=[shivan], library=[_W2G5_CATALOG["Swamp"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    assert hoard.has_type("dragon") and not hoard.is_creature

    assert game.activate_permanent_ability(0, "Bladewing the Risen").supported
    _w2g5_resolve_stack(game)

    assert (bladewing.effective_power, bladewing.effective_toughness) == (5, 5)
    assert (shivan.effective_power, shivan.effective_toughness) == (6, 6)
    assert not hoard.is_creature
    assert any("gives 2 creature(s) +1/+1" in line for line in game.log)

# ==== end W2G5 ======================================================
