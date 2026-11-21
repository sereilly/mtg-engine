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

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), library=None):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name=f"P{seat}",
            library=list(library) if (seat == 0 and library) else [lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, card, seat):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def test_w1g6_oni_possession_makes_a_bigger_demon_spirit_and_eats_a_creature(set_pool):
    """"Enchanted creature gets +3/+3 and has trample" and "is a Demon Spirit":
    a Grizzly Bears becomes a 5/5 trampling Demon Spirit and stops being a Bear
    (CR 205.1a — the new creature types replace the old). "At the beginning of
    your upkeep, sacrifice a creature": the next upkeep costs a creature."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Oni Possession"]])
    bears = _w1g6_put(game, lea["Grizzly Bears"], 0)
    _w1g6_put(game, lea["Llanowar Elves"], 0)
    assert game.cast_from_hand(0, "Oni Possession", target_permanent_ids=[bears.permanent_id]).supported
    _w1g6_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    assert game._has_keyword(bears, "trample")
    assert bears.has_type("Demon") and bears.has_type("Spirit")
    assert not bears.has_type("Bear")

    game.start_turn(0)
    _w1g6_settle(game)
    # The stated default gives up the cheapest creature: the Elves.
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Oni Possession"]


def test_w1g6_night_dealings_counts_damage_to_another_player(set_pool):
    """"Whenever a source you control deals damage to another player, put that
    many theft counters on this enchantment": a Bolt at the opponent (3) and a
    Hill Giant's combat damage (3) count; the opponent's Bolt at you and your
    Bolt at yourself do not. "{2}{B}{B}, Remove X theft counters: Search your
    library for a nonland card with mana value X" then fetches the Hill Giant
    for X=4."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
        library=[lea["Forest"], lea["Grizzly Bears"], lea["Hill Giant"], lea["Craw Wurm"]],
    )
    dealings = _w1g6_put(game, chk["Night Dealings"], 0)
    _w1g6_put(game, lea["Hill Giant"], 0)
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 3
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 3

    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 14
    assert _w1g6_counters_on(dealings, "theft") == 6

    assert not game.activate_permanent_ability(0, "Night Dealings", x_value=7).supported
    assert game.activate_permanent_ability(0, "Night Dealings", x_value=4).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 2
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]

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


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

from engine import Game as _W2G4Game, PlayerState as _W2G4PlayerState
from engine.models import Permanent as _W2G4Permanent
from tests.helpers import settle as _w2g4_settle


def _w2g4_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g4_put(game, card, seat=0):
    permanent = _W2G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w2g4_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=()):
    card = lambda name: _w2g4_card(set_pool, name)  # noqa: E731
    game = _W2G4Game(players=[
        _W2G4PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Island")] * 10),
        _W2G4PlayerState(name="Bob", hand=[card(n) for n in opponent_hand],
                         library=[card("Island")] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {
        seat: [_w2g4_put(game, card(name), seat) for name in names]
        for seat, names in ((0, mine), (1, theirs))
    }
    game.start_turn(0)
    _w2g4_settle(game)
    return game, placed[0], placed[1]


def _w2g4_cast_swirl(game, set_pool, color):
    """Alice casts Swirl the Mists as an interactive seat and answers its
    entry choice ("choose a color word") with *color*; returns the Swirl."""
    game.players[0].hand.append(_w2g4_card(set_pool, "Swirl the Mists"))
    game.interactive_seats = {0}
    assert game.queue_from_hand(0, "Swirl the Mists").supported
    asked = []

    def answer(game, choice):
        asked.append(choice.data.get("needs_color"))
        assert game.confirm_enter_choice(0, mana_color=color)

    _w2g4_settle(game, answers={"enter_choice": answer})
    game.interactive_seats = set()
    assert asked == [True]
    return next(p for p in game.controlled_by(0) if p.card.name == "Swirl the Mists")


def test_w2g4_swirl_the_mists_rewrites_every_colour_word_on_the_board(set_pool):
    """"All instances of color words in the text of spells and permanents are
    changed to the chosen color word." Swirl naming red: Black Knight's
    "protection from white" and White Knight's "protection from black" both
    read "protection from red", so a Lightning Bolt can target neither; once
    Swirl leaves, "It ends as soon as Swirl the Mists leaves the battlefield"
    (ruling 2004-12-01) and the Bolt kills the Black Knight."""
    game, (black_knight, white_knight), _ = _w2g4_table(
        set_pool, mine=["Black Knight", "White Knight"],
        opponent_hand=["Lightning Bolt", "Lightning Bolt"],
    )
    swirl = _w2g4_cast_swirl(game, set_pool, "R")
    for knight in (black_knight, white_knight):
        assert "Protection from red" in knight.effective_card.oracle_text
        assert not game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[knight.permanent_id],
        ).supported
    game.sacrifice_permanent(swirl)
    _w2g4_settle(game)
    assert "Protection from white" in black_knight.effective_card.oracle_text
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[black_knight.permanent_id],
    ).supported
    _w2g4_settle(game)
    assert not game.is_on_battlefield(black_knight)
    assert game.is_on_battlefield(white_knight)


def test_w2g4_swirl_the_mists_reaches_spells_cast_and_permanents_entering_after_it(set_pool):
    """"Swirl the Mists' ability also affects spells that are cast and
    permanents that enter after Swirl the Mists enters." (Ruling 2004-12-01.)
    Under a red Swirl a Terror on the stack reads "nonartifact, nonred", so
    one aimed at a Shivan Dragon has an illegal target as it resolves
    (CR 608.2b) and the Dragon lives; a Black Knight put onto the battlefield
    afterwards has protection from red as it arrives."""
    from engine.text_changes import spell_text_card

    game, _mine, (dragon,) = _w2g4_table(set_pool, hand=["Terror"], theirs=["Shivan Dragon"])
    _w2g4_cast_swirl(game, set_pool, "R")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[dragon.permanent_id]).supported
    assert "nonred creature" in spell_text_card(game.stack[-1]).oracle_text
    _w2g4_settle(game)
    assert game.is_on_battlefield(dragon)
    assert any("every target is illegal" in line for line in game.log)
    knight = _w2g4_put(game, _w2g4_card(set_pool, "Black Knight"))
    assert "Protection from red" in knight.effective_card.oracle_text
    assert game._has_keyword(knight, "protection")


def test_w2g4_swirl_the_mists_at_a_seat_nobody_asks_uses_its_stamped_word(set_pool):
    """A seat nobody asks takes the entry choice's stated default, and the
    board reads that word: every colour word on a White Knight becomes it."""
    from engine.text_changes import COLOR_WORDS

    game, (knight,), _ = _w2g4_table(set_pool, hand=["Swirl the Mists"], mine=["White Knight"])
    assert game.queue_from_hand(0, "Swirl the Mists").supported
    _w2g4_settle(game)
    swirl = next(p for p in game.controlled_by(0) if p.card.name == "Swirl the Mists")
    word = COLOR_WORDS[swirl.metadata["chosen_color"]]
    assert f"Protection from {word}" in knight.effective_card.oracle_text

# ==== end W2G4 ======================================================
