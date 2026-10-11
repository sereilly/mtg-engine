"""Apocalypse enchantments.

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

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Forest": "LEA", "Terror": "LEA", "Grizzly Bears": "LEA", "Hill Giant": "LEA",
    "Shock": "STH",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_duel(set_pool, *, hand=(), opp_hand=()) -> _w1g8_Game:
    forest = _w1g8_card(set_pool, "Forest")
    me = _w1g8_PlayerState(
        name="Me", hand=[_w1g8_card(set_pool, n) for n in hand], library=[forest] * 12,
    )
    opp = _w1g8_PlayerState(
        name="Opp", hand=[_w1g8_card(set_pool, n) for n in opp_hand],
        library=[forest] * 12,
    )
    game = _w1g8_Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    me.mana_pool.update(_W1G8_RICH)
    opp.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_enchant(game, set_pool, aura: str, host) -> None:
    assert game.queue_from_hand(0, aura, target_permanent_ids=[host.permanent_id]).supported
    _w1g8_resolve_stack(game)
    assert aura in _w1g8_names(game.controlled_by(0)), game.log


def _w1g8_combat(game, attacker, *, active: int, blocker=None) -> None:
    """*attacker* attacks the other seat through the real combat phase, blocked
    by *blocker* or by nobody, and every trigger the damage raised resolves."""
    defender = 1 - active
    game.active_player_index = active
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.declare_attackers(
        active, [game.battlefield_index_of(attacker)], defending_player_index=defender,
    )[0]
    game.advance_combat_phase()
    blocks = {} if blocker is None else {game.battlefield_index_of(blocker): 0}
    assert game.declare_blockers(defender, blocks)[0]
    game.advance_combat_phase()
    _w1g8_resolve_stack(game)
    for _ in range(8):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    _w1g8_resolve_stack(game)


# --- Squee's Embrace (driven) -------------------------------------------------------


def test_w1g8_squees_embrace_pumps_and_returns_the_dead_creature_to_its_owner(set_pool):
    """"Enchanted creature gets +2/+2. / When enchanted creature dies, return
    that card to its owner's hand." The Bears are a 4/4 under it; killed, the
    card is in a hand and not in a graveyard, and the Aura has gone to its
    owner's graveyard (CR 704.5m)."""
    game = _w1g8_duel(set_pool, hand=["Squee's Embrace", "Terror"])
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    spec = game.cast_target_spec(0, _w1g8_card(set_pool, "Squee's Embrace"))
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]

    _w1g8_enchant(game, set_pool, "Squee's Embrace", bears)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)

    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    _w1g8_resolve_stack(game)

    assert _w1g8_names(game.players[0].hand) == ["Grizzly Bears"], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Terror"]
    # The next time anybody would receive priority (CR 704.3):
    game.check_state_based_actions()
    assert sorted(_w1g8_names(game.players[0].graveyard)) == ["Squee's Embrace", "Terror"]
    assert list(game.controlled_by(0)) == []


def test_w1g8_squees_embrace_on_an_opponents_creature_returns_it_to_their_hand(set_pool):
    """"Its **owner's** hand": put on the other player's creature, the card
    goes back to them — not to the Aura's controller."""
    game = _w1g8_duel(set_pool, hand=["Squee's Embrace", "Terror"])
    theirs = _w1g8_put(game, set_pool, 1, "Grizzly Bears")

    _w1g8_enchant(game, set_pool, "Squee's Embrace", theirs)
    assert (theirs.effective_power, theirs.effective_toughness) == (4, 4)
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[theirs.permanent_id]).supported
    _w1g8_resolve_stack(game)

    assert _w1g8_names(game.players[1].hand) == ["Grizzly Bears"], game.log
    assert game.players[0].hand == [] and game.players[1].graveyard == []


# --- Soul Link (driven) ----------------------------------------------------------------


def test_w1g8_soul_link_gains_for_damage_the_creature_deals(set_pool):
    """"Whenever enchanted creature deals damage, you gain that much life."
    An unblocked 2/2 is 2 life for the Aura's controller."""
    game = _w1g8_duel(set_pool, hand=["Soul Link"])
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    _w1g8_enchant(game, set_pool, "Soul Link", bears)

    _w1g8_combat(game, bears, active=0)

    assert (game.players[0].life, game.players[1].life) == (22, 18), game.log


def test_w1g8_soul_link_gains_for_damage_the_creature_is_dealt(set_pool):
    """"Whenever enchanted creature is dealt damage, you gain that much
    life." A Shock at the Giant is 2 life for the Aura's controller."""
    game = _w1g8_duel(set_pool, hand=["Soul Link"], opp_hand=["Shock"])
    giant = _w1g8_put(game, set_pool, 0, "Hill Giant")
    _w1g8_enchant(game, set_pool, "Soul Link", giant)

    assert game.queue_from_hand(1, "Shock", target_permanent_ids=[giant.permanent_id]).supported
    _w1g8_resolve_stack(game)

    assert game.players[0].life == 22 and giant.damage_marked == 2, game.log


def test_w1g8_soul_link_gains_both_ways_in_one_combat(set_pool):
    """Both abilities in one damage step: the Giant deals 3 to the Bears that
    block it and is dealt their 2, so the controller gains 3 and 2."""
    game = _w1g8_duel(set_pool, hand=["Soul Link"])
    giant = _w1g8_put(game, set_pool, 0, "Hill Giant")
    bears = _w1g8_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_enchant(game, set_pool, "Soul Link", giant)

    _w1g8_combat(game, giant, active=0, blocker=bears)

    assert game.players[0].life == 25, game.log
    assert game.players[1].life == 20
    assert _w1g8_names(game.players[1].graveyard) == ["Grizzly Bears"]


def test_w1g8_soul_link_on_an_opponents_creature_pays_the_auras_controller(set_pool):
    """"**You** gain" is the Aura's controller, whoever controls the creature:
    their Bears hit me for 2 and I gain it straight back."""
    game = _w1g8_duel(set_pool, hand=["Soul Link"])
    theirs = _w1g8_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_enchant(game, set_pool, "Soul Link", theirs)

    _w1g8_combat(game, theirs, active=1)

    assert (game.players[0].life, game.players[1].life) == (20, 20), game.log
    assert any("Me gained 2 life from Soul Link" in line for line in game.log)

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
