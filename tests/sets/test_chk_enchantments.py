"""Champions of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# The drive list's Auras: Indomitable Will (flash), Vigilance,
# Uncontrollable Anger.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def test_w1g2_indomitable_will_flashes_in_to_save_a_blocker(set_pool):
    """Flash: cast in the declare blockers step on the Bears blocking a Hill
    Giant, it is a 3/4 that survives the 3 damage."""
    game = _w1g2_table(set_pool, hands=((), [set_pool("CHK")["Indomitable Will"]]))
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(giant)], defending_player_index=1)[0]
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(giant)}
    )[0]
    game.priority_player_index = 1
    assert game.cast_from_hand(
        1, "Indomitable Will", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g2_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(bears)


def test_w1g2_vigilance_and_uncontrollable_anger_on_a_bear(set_pool):
    """Vigilance gives the enchanted creature vigilance; Uncontrollable Anger
    makes it a +2/+2 that must attack — a declaration without it is refused."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([chk["Vigilance"], chk["Uncontrollable Anger"]], ()))
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    for aura in ("Vigilance", "Uncontrollable Anger"):
        assert game.cast_from_hand(0, aura, target_permanent_ids=[bears.permanent_id]).supported
        _w1g2_settle(game)
    assert bears.has_keyword("vigilance")
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(0, [], defending_player_index=1)[0]
    assert game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)[0]
    assert not bears.tapped

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Vassal's Duty ------------------------------------------------------------
# "{1}: The next 1 damage that would be dealt to target legendary creature you
# control this turn is dealt to you instead." CR 614.9's redirect as a point
# pool (Daughter of Autumn's record), the ability's controller taking it.


def test_w1g8_vassals_duty_moves_one_point_to_its_controller(set_pool):
    duty = set_pool("CHK")["Vassal's Duty"]
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, (_, legend), _ = _w1g8_table([duty, kumano], [], opponent_hand=[bolt, bolt])
    used = game.activate_permanent_ability(
        0, "Vassal's Duty", target_permanent_ids=[legend.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[legend.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.players[0].life == 19
    assert legend.damage_marked == 2
    # Spent: the next Bolt is dealt to Kumano whole, and kills it.
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[legend.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.players[0].life == 19
    assert not game.is_on_battlefield(legend)


def test_w1g8_vassals_duty_targets_only_a_legendary_creature_you_control(set_pool):
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    duty = set_pool("CHK")["Vassal's Duty"]
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    bears = set_pool("LEA")["Grizzly Bears"]
    ability = compile_card_oracle(duty).activated_abilities[0]
    assert derive_activation_spec(ability) == {
        "kind": "creature", "own_only": True,
        "filter": {"supertypes": ["legendary"]},
    }
    game, (_, bear), (theirs,) = _w1g8_table([duty, bears], [kumano])
    for chosen in (bear, theirs):
        assert not game.activate_permanent_ability(
            0, "Vassal's Duty", target_permanent_ids=[chosen.permanent_id]
        ).supported


# --- Tide of War --------------------------------------------------------------
# "Whenever one or more creatures block, flip a coin. If you win the flip,
# each blocking creature is sacrificed by its controller. If you lose the
# flip, each blocked creature is sacrificed by its controller." Its rulings
# (2004-12-01): the controller always flips; once a combat, only if a blocker
# is declared; a blocked attacker stays blocked when its blockers go.

from tests.helpers import drive_combat as _w1g8_drive_combat


def _w1g8_tide_combat(set_pool, monkeypatch, won: bool, *, block: bool = True):
    tide = set_pool("CHK")["Tide of War"]
    giant = set_pool("LEA")["Hill Giant"]
    bears = set_pool("LEA")["Grizzly Bears"]
    flips: list[bool] = []

    def coin() -> bool:
        flips.append(won)
        return won

    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", coin)
    game, (hill,), (_, bear) = _w1g8_table([giant], [tide, bears])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    slot = next(
        i for i, perm in enumerate(game.players[1].battlefield) if perm is bear
    )
    assert game.declare_blockers(1, {slot: 0} if block else {})[0]
    _w1g8_settle(game)
    return game, hill, bear, flips


def test_w1g8_tide_of_war_won_flip_sacrifices_the_blockers(set_pool, monkeypatch):
    game, hill, bear, flips = _w1g8_tide_combat(set_pool, monkeypatch, True)
    assert flips == [True]
    assert not game.is_on_battlefield(bear)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Grizzly Bears"]
    assert game.is_on_battlefield(hill) and hill.blocked
    _w1g8_drive_combat(game)
    # Still blocked with its blocker gone: no damage to the player.
    assert game.players[1].life == 20


def test_w1g8_tide_of_war_lost_flip_sacrifices_the_blocked(set_pool, monkeypatch):
    game, hill, bear, flips = _w1g8_tide_combat(set_pool, monkeypatch, False)
    assert flips == [False]
    assert not game.is_on_battlefield(hill)
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Hill Giant"]
    assert game.is_on_battlefield(bear)


def test_w1g8_tide_of_war_needs_a_blocker(set_pool, monkeypatch):
    game, hill, bear, flips = _w1g8_tide_combat(
        set_pool, monkeypatch, True, block=False
    )
    assert flips == []
    assert game.is_on_battlefield(hill) and game.is_on_battlefield(bear)

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA", "TMP"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, mine=(), theirs=()):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g9_heartbeat_of_spring_adds_one_mana_inline_for_every_players_land(set_pool):
    """"Whenever a player taps a land for mana, that player adds one mana of
    any type that land produced." A triggered mana ability (CR 605.1b): the
    extra mana is there as the tap returns, with nothing on the stack. One
    unit, of a type the land made, when the land made two (ruling
    2020-08-07: "you choose one type that was produced and add one mana of
    that type"); unrestricted beside a land whose own mana is restricted
    ("with no restrictions or riders"); and for the opponent's land too."""
    game, mine, theirs = _w1g9_table(
        set_pool,
        mine=["Heartbeat of Spring", "Forest", "Ancient Tomb", "Untaidake, the Cloud Keeper"],
        theirs=["Island"],
    )
    alice, bob = game.players
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[1].permanent_id)
    assert _w1g9_pool(alice) == {"G": 2}
    assert game.stack == []

    assert game.tap_land_for_mana(0, "Ancient Tomb", "C", permanent_id=mine[2].permanent_id)
    assert _w1g9_pool(alice) == {"G": 2, "C": 3}
    assert alice.life == 18

    slot = [p.permanent_id for p in alice.battlefield].index(mine[3].permanent_id)
    assert game.activate_permanent_ability(
        0, "Untaidake, the Cloud Keeper", permanent_index=slot,
    ).supported
    assert alice.restricted_mana == {"legendary": {"C": 2}}
    assert _w1g9_pool(alice) == {"G": 2, "C": 4}
    assert game.stack == []

    assert game.tap_land_for_mana(1, "Island", "U", permanent_id=theirs[0].permanent_id)
    assert _w1g9_pool(bob) == {"U": 2}

# ==== end w1g9 ======================================================
