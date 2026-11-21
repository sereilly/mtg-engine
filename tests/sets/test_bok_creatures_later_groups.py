"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g7_ishi_ishi_shoots_the_opponent_who_casts_a_spirit_or_arcane_spell(set_pool):
    """Whenever an opponent casts a Spirit or Arcane spell, Ishi-Ishi deals 2
    damage to that player. An Arcane instant and a Spirit creature spell each
    cost their caster 2; a spell that is neither costs nothing, and neither
    does Ishi-Ishi's own controller's Spirit (the trigger is "an opponent")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool,
        hand=[chk["Kami of the Hunt"]],
        opponent_hand=[chk["Glacial Ray"], lea["Lightning Bolt"], chk["Kami of the Hunt"]],
    )
    _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        1, "Glacial Ray", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [20, 18]
    assert "Ishi-Ishi, Akki Crackshot dealt 2 damage to P1" in game.log
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    # Its controller's own Spirit spell is no opponent's.
    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    game.start_turn(1)
    _w1g7_settle(game)
    assert game.cast_from_hand(1, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 16]


def _w1g7_activate(game, permanent, seat, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    return result


def test_w1g7_shimmering_glasskite_counters_only_the_first_targeting_each_turn(set_pool):
    """Whenever this creature becomes the target of a spell or ability for the
    first time each turn, counter that spell or ability. The opponent's first
    Lightning Bolt at it is countered (the Bolt goes to the graveyard, the
    Glasskite takes no damage); a second targeting the same turn — an
    activated ability — resolves. The count is swept in the cleanup step, so
    next turn's first targeting is countered again."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    glass = _w1g7_put(game, bok["Shimmering Glasskite"])
    sorcerer = _w1g7_put(game, lea["Prodigal Sorcerer"], seat=1)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Shimmering Glasskite and moved to graveyard" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt"]
    _w1g7_activate(game, sorcerer, 1, target_permanent_ids=[glass.permanent_id])
    _w1g7_settle(game)
    assert "Prodigal Sorcerer dealt 1 damage to Shimmering Glasskite" in game.log
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    sorcerer.tapped = False
    _w1g7_activate(game, sorcerer, 1, target_permanent_ids=[glass.permanent_id])
    _w1g7_settle(game)
    assert game.log.count("Shimmering Glasskite countered Prodigal Sorcerer's ability") == 1
    assert glass.damage_marked == 0


def test_w1g7_jetting_glasskite_counters_its_controllers_own_spell_and_a_trigger(set_pool):
    """"That spell or ability" is whichever targeted it first, whoever controls
    it: its own controller's Giant Growth is countered (no +3/+3). On the next
    turn the first targeting is an opponent's **triggered** ability —
    Flametongue Kavu's entry trigger, "it deals 4 damage to target creature" —
    and the trigger is countered (CR 701.6a: an ability has no card to bin)."""
    bok, lea, pls = set_pool("BOK"), set_pool("LEA"), set_pool("PLS")
    game = _w1g7_table(
        set_pool, hand=[lea["Giant Growth"]], opponent_hand=[pls["Flametongue Kavu"]],
    )
    glass = _w1g7_put(game, bok["Jetting Glasskite"])
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert glass.effective_power == 4
    assert "Giant Growth was countered by Jetting Glasskite and moved to graveyard" in game.log
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    assert game.cast_from_hand(
        1, "Flametongue Kavu", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Jetting Glasskite countered Flametongue Kavu's ability" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0


def test_w1g7_kira_grants_each_creature_its_own_first_time_counter(set_pool):
    """Creatures you control have the Glasskite's trigger. A Grizzly Bears
    under Kira counters the first Bolt at it; a Glasskite under Kira holds the
    ability twice (printed and granted), both trigger, the first counters and
    the second finds nothing to counter — and a person is not asked to order
    two instances of one ability (the granted line is recorded lowercase)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool, opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
        interactive=(0,),
    )
    _w1g7_put(game, bok["Kira, Great Glass-Spinner"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    glass = _w1g7_put(game, bok["Shimmering Glasskite"])
    game._recompute_continuous_effects()
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Grizzly Bears and moved to graveyard" in game.log
    assert game.is_on_battlefield(bears)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[glass.permanent_id]
    ).supported
    assert not [c for c in game.pending_choices if c.kind == "order_triggers"]
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Shimmering Glasskite and moved to graveyard" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0


def test_w1g7_kira_arriving_after_a_creature_was_targeted_counters_nothing_that_turn(set_pool):
    """"For the first time each turn" is the creature's history, kept whatever
    it said: a Grizzly Bears targeted by its controller's Giant Growth before
    Kira arrived has had its first time, so the opponent's Bolt that turn
    resolves. Kira itself, never targeted, still counters its own first."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool, hand=[lea["Giant Growth"], bok["Kira, Great Glass-Spinner"]],
        opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert bears.effective_power == 5
    assert game.cast_from_hand(0, "Kira, Great Glass-Spinner").supported
    _w1g7_settle(game)
    (kira,) = [p for p in game.all_permanents() if p.card.name.startswith("Kira")]
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt dealt 3 damage to Grizzly Bears" in game.log
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[kira.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Kira, Great Glass-Spinner and moved to graveyard" in game.log
    assert game.is_on_battlefield(kira)

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
