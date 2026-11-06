"""Scourge creatures (legendary ones too).

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


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
