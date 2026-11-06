"""Scourge enchantments, Auras included.

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
# Dragons and Auras. The five Dragon Auras' "When a creature with mana value 6
# or greater enters, you may return this card from your graveyard to the
# battlefield attached to that creature": a trigger that functions from a
# graveyard (CR 113.6m), narrowed by the entering creature's mana value, and an
# Aura put onto the battlefield attached to a host the effect names (CR 303.4i:
# not targeted, and it stays in the graveyard when it cannot enchant it).

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("SCG", "LEA", "LEG", "USG", "ONS", "STH"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_table(set_pool, *, graveyard=(), hand=(), opp_graveyard=(), interactive=()):
    me = _W1G6PlayerState(
        name="Me",
        graveyard=[_w1g6_card(set_pool, n) for n in graveyard],
        hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Island")] * 8,
    )
    opp = _W1G6PlayerState(
        name="Opp",
        graveyard=[_w1g6_card(set_pool, n) for n in opp_graveyard],
        library=[_w1g6_card(set_pool, "Forest")] * 8,
    )
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game


def _w1g6_enter(game, set_pool, seat, name):
    """Put *name* onto the battlefield under *seat* — not cast, so only the
    entry announcement runs (CR 603.6a)."""
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_settle(game):
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)


def _w1g6_attached(game, name):
    return [
        perm.metadata.get("attached_to") for perm in game.all_permanents()
        if perm.card.name == name
    ]


def _w1g6_graveyard(game, seat=0):
    return [card.name for card in game.players[seat].graveyard]


def test_w1g6_dragon_fangs_returns_attached_to_an_entering_six_drop(set_pool):
    """Dragon Fangs in the graveyard, Shivan Dragon (mana value 6) enters: the
    Aura comes back attached to it, and its static is live — 6/6 trample."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Dragon Fangs"]
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Fangs") == [dragon]
    assert "Dragon Fangs" not in _w1g6_graveyard(game)
    assert (dragon.effective_power, dragon.effective_toughness) == (6, 6)
    assert game._has_keyword(dragon, "trample")
    assert "Dragon Fangs attached to Shivan Dragon" in game.log


def test_w1g6_a_small_creature_entering_triggers_no_dragon_aura(set_pool):
    """Grizzly Bears (mana value 2) is not "a creature with mana value 6 or
    greater": nothing triggers from the graveyard."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Scales"])
    _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert not game.stack
    assert _w1g6_graveyard(game) == ["Dragon Scales"]


def test_w1g6_dragon_aura_stays_in_the_graveyard_when_its_host_leaves_first(set_pool):
    """CR 303.4i, in response: the Dragon is destroyed with the trigger on the
    stack, so the effect names a host that is gone and the Aura remains in its
    current zone."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Shadow"], hand=["Terror"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Dragon Shadow"]
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[dragon.permanent_id]
    ).supported
    assert [item.card.name for item in game.stack] == ["Dragon Shadow", "Terror"]
    _w1g6_settle(game)
    assert not game.is_on_battlefield(dragon)
    assert "Dragon Shadow" in _w1g6_graveyard(game)
    assert not _w1g6_attached(game, "Dragon Shadow")
    assert any("stays in the graveyard" in line for line in game.log)


def test_w1g6_two_dragon_auras_both_trigger_and_both_attach(set_pool):
    """Two Dragon Auras in the graveyard and one big creature entering: both
    trigger, both come back onto it."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath", "Dragon Wings"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert sorted(item.card.name for item in game.stack) == ["Dragon Breath", "Dragon Wings"]
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Breath") == [dragon]
    assert _w1g6_attached(game, "Dragon Wings") == [dragon]
    assert game._has_keyword(dragon, "haste")


def test_w1g6_an_interactive_seat_is_asked_and_may_decline(set_pool):
    """The return is a "may": an asked seat that declines keeps the Aura in its
    graveyard; one that accepts gets it back attached."""
    for accept in (False, True):
        game = _w1g6_table(set_pool, graveyard=["Dragon Scales"], interactive={0})
        dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
        game.resolve_top_of_stack()
        assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, "Dragon Scales", accept=accept)
        _w1g6_resolve_stack(game)
        if accept:
            assert _w1g6_attached(game, "Dragon Scales") == [dragon]
            assert (dragon.effective_power, dragon.effective_toughness) == (6, 7)
            assert game._has_keyword(dragon, "vigilance")
        else:
            assert _w1g6_graveyard(game) == ["Dragon Scales"]


def test_w1g6_an_opponents_six_drop_triggers_the_owners_aura(set_pool):
    """"A creature … enters" is anyone's. Asked, the owner may put the Aura on
    the opponent's creature — it returns under the owner's control (CR
    108.4a); the AI declines a helpful Aura onto the wrong side."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"], interactive={0})
    dragon = _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, "Dragon Fangs", accept=True)
    _w1g6_resolve_stack(game)
    fangs = next(p for p in game.all_permanents() if p.card.name == "Dragon Fangs")
    assert fangs.metadata.get("attached_to") is dragon
    assert game.controller_index_of(fangs) == 0
    assert game.controller_index_of(dragon) == 1

    ai = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    _w1g6_enter(ai, set_pool, 1, "Shivan Dragon")
    _w1g6_settle(ai)
    assert _w1g6_graveyard(ai) == ["Dragon Fangs"]
    assert any("wrong side" in line for line in ai.log)


def test_w1g6_protection_keeps_the_aura_in_the_graveyard_and_shroud_does_not(set_pool):
    """Ivory Guardians (protection from red) can't be enchanted by Dragon
    Breath (CR 702.16c), so the Aura stays put; Zephid's shroud is no bar,
    because nothing targets (CR 303.4i names the host, CR 115.1)."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath"])
    _w1g6_enter(game, set_pool, 0, "Ivory Guardians")
    _w1g6_settle(game)
    assert _w1g6_graveyard(game) == ["Dragon Breath"]
    assert any("protection" in line for line in game.log)

    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    zephid = _w1g6_enter(game, set_pool, 0, "Zephid")
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Fangs") == [zephid]


def test_w1g6_dragon_breaths_firebreathing_pumps_the_creature_it_returned_onto(set_pool):
    """The other lines, driven attached: Dragon Breath's "{R}: Enchanted
    creature gets +1/+0 until end of turn"."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    _w1g6_settle(game)
    assert game.activate_permanent_ability(0, "Dragon Breath").supported
    _w1g6_resolve_stack(game)
    assert dragon.effective_power == 6


def test_w1g6_dragon_auras_cast_from_the_hand_still_enchant(set_pool):
    """Cast the ordinary way, each Aura's static applies to its target — Dragon
    Shadow's +1/+0 and fear on a Grizzly Bears."""
    game = _w1g6_table(set_pool, hand=["Dragon Shadow"])
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, "Dragon Shadow", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g6_resolve_stack(game)
    assert _w1g6_attached(game, "Dragon Shadow") == [bears]
    assert bears.effective_power == 3
    assert game._has_keyword(bears, "fear")

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
