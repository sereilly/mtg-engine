"""Torment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def test_w1g7_last_laugh_sacrifices_itself_once_its_damage_empties_the_board(set_pool):
    """"When no creatures are on the battlefield, sacrifice this enchantment."

    Drop of Honey's state trigger in the other word order. A Bolt kills the
    Elves; Last Laugh's ping kills the Raiders; with no creature left anywhere
    it is sacrificed — and the ping for the Raiders' death still resolves from
    a source that has left, so each player loses 2."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    laugh = _w1g7_Permanent(card=tor["Last Laugh"])
    elves = _w1g7_Permanent(card=lea["Llanowar Elves"])
    raiders = _w1g7_Permanent(card=lea["Mons's Goblin Raiders"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[laugh, elves], hand=[lea["Lightning Bolt"]]),
        _w1g7_PlayerState(name="P1", battlefield=[raiders]),
    ])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[elves.permanent_id])
    _w1g7_resolve_stack(game)
    game._settle()

    assert [c.name for c in game.players[0].graveyard] == [
        "Lightning Bolt", "Llanowar Elves", "Last Laugh",
    ]
    assert [c.name for c in game.players[1].graveyard] == ["Mons's Goblin Raiders"]
    assert [p.life for p in game.players] == [18, 18]
    assert any("Last Laugh sacrificed" in line for line in game.log)


def test_w1g7_last_laugh_stays_while_any_creature_is_on_the_battlefield(set_pool):
    """The set is every battlefield: an opponent's creature keeps it."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    laugh = _w1g7_Permanent(card=tor["Last Laugh"])
    ogre = _w1g7_Permanent(card=lea["Gray Ogre"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[laugh]),
        _w1g7_PlayerState(name="P1", battlefield=[ogre]),
    ])
    game.check_state_based_actions()
    assert laugh in game.players[0].battlefield
    game.remove_from_battlefield(ogre)
    game.check_state_based_actions()
    assert laugh not in game.players[0].battlefield
    assert [c.name for c in game.players[0].graveyard] == ["Last Laugh"]


def _w1g7_floating_shield_on_bears(set_pool, color):
    """Floating Shield cast on seat 0's Bears, its entry colour answered as
    *color*; seat 1 holds two Lightning Bolts."""
    from tests.helpers import _nosick

    tor, lea = set_pool("TOR"), set_pool("LEA")
    bears = _nosick(_w1g7_Permanent(card=lea["Grizzly Bears"]))
    lions = _nosick(_w1g7_Permanent(card=lea["Savannah Lions"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[bears, lions], hand=[tor["Floating Shield"]]),
        _w1g7_PlayerState(name="P1", hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    game.interactive_seats = {0}
    assert game.queue_from_hand(
        0, "Floating Shield", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 0)]
    assert game.confirm_enter_choice(0, mana_color=color)
    game.interactive_seats = set()
    shield = next(p for p in game.controlled_by(0) if p.card.name == "Floating Shield")
    return game, shield, bears, lions


def test_w1g7_floating_shield_protects_its_creature_from_the_chosen_color(set_pool):
    """"Enchanted creature has protection from the chosen color." Red named:
    a Bolt cannot target the Bears; the unenchanted Lions are fair game."""
    game, shield, bears, lions = _w1g7_floating_shield_on_bears(set_pool, "R")
    assert shield.metadata.get("attached_to") is bears
    refused = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id]).supported
    assert lions not in game.players[0].battlefield


def test_w1g7_floating_shield_naming_its_own_color_does_not_fall_off(set_pool):
    """"This effect doesn't remove this Aura." (CR 702.16n.) The Shield is
    white; naming white would otherwise put it into the graveyard as a
    state-based action (CR 702.16c)."""
    game, shield, bears, _ = _w1g7_floating_shield_on_bears(set_pool, "W")
    game.check_state_based_actions()
    assert shield in game.players[0].battlefield
    assert shield.metadata.get("attached_to") is bears


def test_w1g7_floating_shield_sacrificed_gives_its_color_to_another_creature(set_pool):
    """"Sacrifice this Aura: Target creature gains protection from the chosen
    color until end of turn." The Aura is gone by resolution — the colour is
    read off it as it last existed (CR 608.2h) — so the Lions are protected
    from red, the Bears no longer are, and cleanup ends it."""
    game, shield, bears, lions = _w1g7_floating_shield_on_bears(set_pool, "R")
    assert game.activate_permanent_ability(
        0, "Floating Shield", target_permanent_ids=[lions.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert [c.name for c in game.players[0].graveyard] == ["Floating Shield"]
    assert any("Savannah Lions gains protection from red" in line for line in game.log)

    refused = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]).supported
    assert bears not in game.players[0].battlefield

    game.resolve_cleanup_step(0)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id]).supported
    assert lions not in game.players[0].battlefield


def _w1g7_transcendence_at(set_pool, life):
    """Seat 0 at *life* with Transcendence; seat 1 holds a Lightning Bolt.
    One sweep first, so the starting totals are seen and are not a loss."""
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", life=life,
            battlefield=[_w1g7_Permanent(card=set_pool("TOR")["Transcendence"])],
        ),
        _w1g7_PlayerState(name="P1", hand=[set_pool("LEA")["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.check_state_based_actions()
    _w1g7_resolve_stack(game)
    return game


def _w1g7_bolt_seat_zero(game):
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    _w1g7_resolve_stack(game)


def test_w1g7_transcendence_turns_a_loss_into_twice_the_gain(set_pool):
    """"Whenever you lose life, you gain 2 life for each 1 life you lost."
    Bolted from 15: 12, then one gain of 6 (CR 119.3), to 18."""
    game = _w1g7_transcendence_at(set_pool, 15)
    _w1g7_bolt_seat_zero(game)
    assert game.players[0].life == 18 and not game.players[0].lost
    assert "P0 gained 6 life from Transcendence (12 -> 18)" in game.log


def test_w1g7_transcendence_loses_the_game_at_twenty_or_more(set_pool):
    """"When you have 20 or more life, you lose the game." Bolted from 19 the
    gain lands on 22, and the state trigger ends it (CR 603.8)."""
    game = _w1g7_transcendence_at(set_pool, 19)
    assert not game.players[0].lost
    _w1g7_bolt_seat_zero(game)
    assert game.players[0].life == 22
    assert game.players[0].lost and not game.players[1].lost


def test_w1g7_transcendence_survives_zero_or_less_life(set_pool):
    """"You don't lose the game for having 0 or less life." Bolted from 1 to
    -2, the state-based action does not end the game (CR 704.5a), and the
    trigger lifts it to 4."""
    game = _w1g7_transcendence_at(set_pool, 1)
    _w1g7_bolt_seat_zero(game)
    # The sweep that saw -2 is the one that announced the loss.
    assert "P0 gained 6 life from Transcendence (-2 -> 4)" in game.log
    assert not any("704.5a" in line for line in game.log)
    assert game.players[0].life == 4 and not game.players[0].lost


def test_w1g7_transcendence_at_twenty_loses_as_soon_as_it_is_seen(set_pool):
    """The state is true from the start at 20 life: the first sweep puts the
    trigger on the stack and its controller loses."""
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", battlefield=[_w1g7_Permanent(card=set_pool("TOR")["Transcendence"])],
        ),
        _w1g7_PlayerState(name="P1"),
    ])
    game.check_state_based_actions()
    assert [item.ability_text for item in game.stack] == [
        "When you have 20 or more life, you lose the game."
    ]
    _w1g7_resolve_stack(game)
    assert game.players[0].lost

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
