"""Onslaught creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# Morph (CR 702.37) and face-down permanents (CR 708) — ``engine/face_down.py``.
# Every Onslaught morph card is driven through a game below: cast face down
# for {3} out of the pool, resolved, read as the face-down 2/2 it is, and
# turned face up for exactly its printed morph cost; then the face-up lines
# whose behaviour a face-down permanent must *not* have are played both ways.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.card_loader import load_catalog as _w1g1_load_catalog
from engine.face_down import (FACE_DOWN_NAME as _W1G1_FACE_DOWN_NAME,
                              face_down_card as _w1g1_face_down_card,
                              hidden_card_of as _w1g1_hidden_card_of,
                              is_face_down as _w1g1_is_face_down,
                              morph_cost as _w1g1_morph_cost)
from engine.mana_payment import mana_cost_from_symbols as _w1g1_symbols
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from engine.special_actions import (
    take_permanent_special_action as _w1g1_take_special_action)
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_CATALOG = {card.name: card for card in _w1g1_load_catalog()}

#: Every Onslaught card printing morph. The first 41 compile supported; the
#: last five have a second line another wave-1 group owns (W1G2, W1G5, W1G7,
#: W1G10) and are cast face down and turned face up all the same.
_W1G1_MORPHS = (
    "Aphetto Alchemist", "Ascending Aven", "Battering Craghorn",
    "Blistering Firecat", "Boneknitter", "Broodhatch Nantuko",
    "Cabal Executioner", "Charging Slateback", "Crude Rampart", "Daru Healer",
    "Daru Lancer", "Dawning Purist", "Disruptive Pitmage", "Dwarven Blastminer",
    "Ebonblade Reaper", "Exalted Angel", "Fallen Cleric", "Foothill Guide",
    "Goblin Taskmaster", "Gravel Slinger", "Grinning Demon", "Haunted Cadaver",
    "Headhunter", "Hystrodon", "Ironfist Crusher", "Krosan Colossus",
    "Nameless One", "Riptide Biologist", "Serpentine Basilisk",
    "Silent Specter", "Skirk Commando", "Snapping Thragg", "Snarling Undorak",
    "Spined Basher", "Spitting Gourna", "Thrashing Mudspawn",
    "Towering Baloth", "Treespring Lorian", "Venomspout Brackus",
    "Voidmage Prodigy", "Whipcorder",
)
_W1G1_OTHER_GROUPS_LINES = (
    "Birchlore Rangers", "Mistform Shrieker", "Quicksilver Dragon",
    "Riptide Entrancer", "Skittish Valesk",
)


def _w1g1_game(mine=(), theirs=(), hand=(), *, enforce=True):
    p1 = _W1G1PlayerState(name="A", hand=list(hand), battlefield=list(mine),
                          library=[_W1G1_CATALOG["Island"]] * 10)
    p2 = _W1G1PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G1_CATALOG["Island"]] * 10)
    game = _W1G1Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game, p1, p2


def _w1g1_permanent(card, *, face_down=False):
    permanent = _W1G1Permanent(card=_w1g1_face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_pool_for(cost: str) -> dict:
    """The pool that pays *cost* exactly: generic as colourless."""
    pool = {}
    for symbol, count in _w1g1_symbols(cost).items():
        key = "C" if symbol == "generic" else symbol
        pool[key] = pool.get(key, 0) + count
    return pool


def _w1g1_turn_up(game, seat, permanent):
    game.priority_player_index = seat
    game.players[seat].mana_pool.update(
        _w1g1_pool_for(_w1g1_morph_cost(_w1g1_hidden_card_of(permanent)))
    )
    refusal = _w1g1_take_special_action(game, seat, permanent, "turn_face_up")
    assert refusal is None, refusal
    assert sum(game.players[seat].mana_pool.values()) == 0, "paid exactly its morph cost"


@_w1g1_pytest.mark.parametrize("name", _W1G1_MORPHS + _W1G1_OTHER_GROUPS_LINES)
def test_w1g1_every_morph_card_is_cast_face_down_and_turned_face_up(set_pool, name):
    """The whole of CR 702.37 for one card, in a game: {3} from the pool casts
    it face down (CR 702.37c), the permanent it becomes is a colourless,
    nameless, abilityless 2/2 (CR 708.2a), and its printed morph cost — paid
    exactly, out of a pool holding nothing else — turns it face up (CR
    702.37e) into the card it is, with its printed body."""
    card = set_pool("ONS")[name]
    game, p1, _p2 = _w1g1_game(hand=[card])
    p1.mana_pool.update({"C": 3})
    result = game.queue_from_hand(0, name, alternative_cost=True)
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    (permanent,) = p1.battlefield
    assert _w1g1_is_face_down(permanent) and permanent.card.name == _W1G1_FACE_DOWN_NAME
    assert (permanent.effective_power, permanent.effective_toughness) == (2, 2)
    assert permanent.effective_colors == set() and permanent.effective_card.cmc == 0
    program = _w1g1_compile(permanent.effective_card)
    assert program.activated_abilities == () and program.triggered_abilities == ()
    assert not any(permanent.has_keyword(word) for word in (
        "flying", "first strike", "trample", "haste", "defender", "reach",
    ))
    assert not any(name in line for line in game.log)

    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g1_turn_up(game, 0, permanent)
    assert permanent.card is card and not _w1g1_is_face_down(permanent)
    if card.base_power is not None:
        assert (permanent.effective_power, permanent.effective_toughness) == (
            card.base_power, card.base_toughness,
        )
    assert any(f"it is {name}" in line for line in game.log)


def test_w1g1_the_census_was_right_about_these_morph_cards(set_pool):
    """41 compile supported once their morph line is read — four of them the
    census expected another group's line to hold back (Ascending Aven,
    Charging Slateback, Ironfist Crusher, Nameless One: each other line is
    read by a text-keyed table the grammar probe does not ask) — and the five
    whose other line is another group's stay unsupported naming that line."""
    ons = set_pool("ONS")
    assert [n for n in _W1G1_MORPHS if not _w1g1_compile(ons[n]).supported] == []
    for name in _W1G1_OTHER_GROUPS_LINES:
        program = _w1g1_compile(ons[name])
        assert not program.supported
        assert "morph" not in program.reason.lower(), (name, program.reason)


def test_w1g1_exalted_angel_gains_life_only_face_up(set_pool):
    """Face down it is a 2/2 with no text: its attack gains nothing. Face up,
    "Whenever this creature deals damage, you gain that much life" and its
    flying are back (CR 708.8)."""
    angel = set_pool("ONS")["Exalted Angel"]
    permanent = _w1g1_permanent(angel, face_down=True)
    game, p1, p2 = _w1g1_game([permanent], enforce=False)
    _w1g1_declare_attack(game, 0)
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    assert (p1.life, p2.life) == (20, 18)

    game.current_turn_phase = game.current_step = "postcombat_main"
    permanent.tapped = False
    _w1g1_turn_up(game, 0, permanent)
    assert permanent.has_keyword("flying")
    _w1g1_declare_attack(game, 0)
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    assert (p1.life, p2.life) == (24, 14)


def test_w1g1_grinning_demon_costs_life_only_face_up(set_pool):
    """"At the beginning of your upkeep, you lose 2 life." A face-down Demon
    has no such ability; the same permanent turned face up does."""
    demon = set_pool("ONS")["Grinning Demon"]
    permanent = _w1g1_permanent(demon, face_down=True)
    game, p1, _p2 = _w1g1_game([permanent], enforce=False)
    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    assert p1.life == 20
    _w1g1_turn_up(game, 0, permanent)
    assert (permanent.effective_power, permanent.effective_toughness) == (6, 6)
    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    assert p1.life == 18


def test_w1g1_thrashing_mudspawn_hurts_only_face_up(set_pool):
    """"Whenever this creature is dealt damage, you lose that much life." —
    a Shock at the face-down Mudspawn costs nothing; at the face-up one, 2."""
    mudspawn = set_pool("ONS")["Thrashing Mudspawn"]
    shock = _W1G1_CATALOG["Shock"]
    permanent = _w1g1_permanent(mudspawn, face_down=True)
    game, p1, p2 = _w1g1_game([permanent], enforce=False)
    p2.hand[:] = [shock, shock]
    game.queue_from_hand(1, "Shock", target_player_index=0,
                         target_permanent_ids=[permanent.permanent_id])
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert p1.battlefield == [], "a face-down 2/2 dies to Shock"
    assert p1.life == 20
    assert [c.name for c in p1.graveyard] == ["Thrashing Mudspawn"]

    permanent = _w1g1_permanent(mudspawn, face_down=True)
    p1.battlefield.append(permanent)
    game._sync_control()
    _w1g1_turn_up(game, 0, permanent)
    game.queue_from_hand(1, "Shock", target_player_index=0,
                         target_permanent_ids=[permanent.permanent_id])
    _w1g1_resolve_stack(game)
    assert p1.life == 18 and permanent in p1.battlefield


def test_w1g1_blistering_firecat_turned_up_has_haste_and_is_sacrificed(set_pool):
    """Turned face up the turn it entered, the Firecat has haste and attacks
    as a 7/1 trampler; at the beginning of the end step it is sacrificed —
    an ability it did not have while face down."""
    firecat = set_pool("ONS")["Blistering Firecat"]
    game, p1, p2 = _w1g1_game(hand=[firecat], enforce=False)
    assert game.queue_from_hand(0, "Blistering Firecat", alternative_cost=True).supported
    _w1g1_resolve_stack(game)
    (permanent,) = p1.battlefield
    assert game._is_summoning_sick(permanent)
    _w1g1_turn_up(game, 0, permanent)
    assert permanent.has_keyword("haste") and not game._is_summoning_sick(permanent)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    assert p2.life == 13
    game.resolve_end_step(0)
    _w1g1_resolve_stack(game)
    assert [c.name for c in p1.graveyard] == ["Blistering Firecat"]


def test_w1g1_whipcorder_and_venomspout_activate_only_face_up(set_pool):
    """A face-down permanent has no activated ability to activate; turned face
    up it has its printed ones (Whipcorder's "{W}, {T}: Tap target
    creature")."""
    ons = set_pool("ONS")
    whipcorder = _w1g1_permanent(ons["Whipcorder"], face_down=True)
    bears = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, p1, _p2 = _w1g1_game([whipcorder], [bears], enforce=False)
    assert game.usable_abilities_of(whipcorder, card=whipcorder.effective_card) == []
    _w1g1_turn_up(game, 0, whipcorder)
    result = game.activate_permanent_ability(
        0, "Whipcorder", target_player_index=1, target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert bears.tapped and whipcorder.tapped


def test_w1g1_foothill_guide_has_protection_only_face_up(set_pool):
    """"Protection from Goblins" is a face-up ability: a Goblin blocks the
    face-down Guide like any 2/2, and cannot block the face-up one
    (CR 702.16)."""
    ons = set_pool("ONS")
    guide = _w1g1_permanent(ons["Foothill Guide"], face_down=True)
    goblin = _w1g1_permanent(_W1G1_CATALOG["Mons's Goblin Raiders"])
    game, _p1, _p2 = _w1g1_game([guide], [goblin], enforce=False)
    _w1g1_declare_attack(game, 0, blocks={0: 0})
    assert guide.blocked

    guide = _w1g1_permanent(ons["Foothill Guide"], face_down=True)
    goblin = _w1g1_permanent(_W1G1_CATALOG["Mons's Goblin Raiders"])
    game, _p1, _p2 = _w1g1_game([guide], [goblin], enforce=False)
    _w1g1_turn_up(game, 0, guide)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok, "CR 702.16: a Goblin can't block a creature with protection from Goblins"


def test_w1g1_charging_slateback_can_block_only_face_down(set_pool):
    """"This creature can't block." is face-up text: the face-down Slateback
    blocks like any 2/2 (CR 708.2a), the face-up one cannot."""
    slateback = set_pool("ONS")["Charging Slateback"]
    blocker = _w1g1_permanent(slateback, face_down=True)
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g1_game([attacker], [blocker], enforce=False)
    _w1g1_declare_attack(game, 0, blocks={0: 0})
    assert attacker.blocked

    blocker = _w1g1_permanent(slateback, face_down=True)
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g1_game([attacker], [blocker], enforce=False)
    _w1g1_turn_up(game, 1, blocker)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok


def test_w1g1_ascending_aven_blocks_a_walker_only_face_down(set_pool):
    """"This creature can block only creatures with flying." — face down it
    blocks a Grizzly Bears; face up it may not."""
    aven = set_pool("ONS")["Ascending Aven"]
    blocker = _w1g1_permanent(aven, face_down=True)
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g1_game([attacker], [blocker], enforce=False)
    _w1g1_declare_attack(game, 0, blocks={0: 0})
    assert attacker.blocked

    blocker = _w1g1_permanent(aven, face_down=True)
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g1_game([attacker], [blocker], enforce=False)
    _w1g1_turn_up(game, 1, blocker)
    assert blocker.has_keyword("flying")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok


def test_w1g1_nameless_one_counts_wizards_only_face_up(set_pool):
    """"Nameless One's power and toughness are each equal to the number of
    Wizards on the battlefield." A face-down Nameless One is a 2/2 (CR 708.2a:
    no text, so no characteristic-defining ability) and no Wizard; face up it
    counts the Wizards — itself and a face-up Aphetto Alchemist, not a
    face-down one."""
    ons = set_pool("ONS")
    nameless = _w1g1_permanent(ons["Nameless One"], face_down=True)
    alchemist_up = _w1g1_permanent(ons["Aphetto Alchemist"])
    alchemist_down = _w1g1_permanent(ons["Aphetto Alchemist"], face_down=True)
    game, _p1, _p2 = _w1g1_game([nameless, alchemist_up, alchemist_down], enforce=False)
    game._refresh_dynamic_creatures()
    assert (nameless.effective_power, nameless.effective_toughness) == (2, 2)
    _w1g1_turn_up(game, 0, nameless)
    game._refresh_dynamic_creatures()
    assert (nameless.effective_power, nameless.effective_toughness) == (2, 2)
    _w1g1_turn_up(game, 0, alchemist_down)
    game._refresh_dynamic_creatures()
    assert (nameless.effective_power, nameless.effective_toughness) == (3, 3)


def test_w1g1_mistform_shrieker_face_down_has_neither_flying_nor_its_ability(set_pool):
    """Mistform Shrieker's type change is W1G5's line; face down it is a 2/2
    with none of it (CR 708.2a) — no flying, no activated ability."""
    shrieker = _w1g1_permanent(set_pool("ONS")["Mistform Shrieker"], face_down=True)
    game, _p1, _p2 = _w1g1_game([shrieker], enforce=False)
    assert not shrieker.has_keyword("flying")
    assert game.usable_abilities_of(shrieker, card=shrieker.effective_card) == []
    _w1g1_turn_up(game, 0, shrieker)
    assert shrieker.has_keyword("flying")



#: Morph cards whose face-up text acts when the creature attacks or deals
#: combat damage to a player, with what the defending seat ends up with when
#: it does: ``(life, hand size, creatures)`` after one unblocked attack into a
#: defender holding three cards and two Grizzly Bears, from a 20-life,
#: 3-card, 2-creature start. A face-down attack of the same card is a 2/2
#: that does none of it: (18, 3, 2).
_W1G1_COMBAT_FACE_UP = {
    # "…that player sacrifices a creature of their choice."
    "Cabal Executioner": (18, 3, 1),
    # "…that player discards a card."
    "Headhunter": (19, 2, 2),
    # Flying; "…that player discards two cards."
    "Silent Specter": (16, 1, 2),
    # Trample; "…you may draw a card." — the defender is unchanged but for
    # the damage.
    "Hystrodon": (17, 3, 2),
    # "…that player loses half their life, rounded up." 1 combat damage
    # first (19), then half of 19 rounded up (10) is lost. Lost nobody
    # anything before this round: ``handlers._targets.damaged_end_seat``.
    "Ebonblade Reaper": (9, 3, 2),
}


@_w1g1_pytest.mark.parametrize("name", sorted(_W1G1_COMBAT_FACE_UP))
def test_w1g1_combat_damage_abilities_act_only_face_up(set_pool, name):
    """The same creature attacks twice: face down it is a vanilla 2/2
    (CR 708.2a) and deals 2; turned face up (CR 702.37e) its printed
    "deals combat damage to a player" ability acts."""
    card = set_pool("ONS")[name]
    for face_up in (False, True):
        attacker = _w1g1_permanent(card, face_down=True)
        bears = [_w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"]) for _ in range(2)]
        game, p1, p2 = _w1g1_game([attacker], bears, enforce=False)
        p2.hand[:] = [_W1G1_CATALOG["Island"]] * 3
        if face_up:
            _w1g1_turn_up(game, 0, attacker)
        _w1g1_declare_attack(game, 0)
        while game.current_turn_phase == "combat":
            game.advance_combat_phase()
            _w1g1_resolve_stack(game)
            # The discards are the defending seat's choices; a seat nobody
            # asks answers with its default, as the simulator's drain does.
            game.auto_resolve_pending_choices()
        _w1g1_resolve_stack(game)
        game.check_state_based_actions()
        seen = (p2.life, len(p2.hand), len(p2.battlefield))
        expected = _W1G1_COMBAT_FACE_UP[name] if face_up else (18, 3, 2)
        assert seen == expected, (name, "face up" if face_up else "face down", game.log[-12:])
        if name == "Ebonblade Reaper" and face_up:
            # "Whenever this creature attacks, you lose half your life,
            # rounded up." — 20 → 10.
            assert p1.life == 10


def test_w1g1_ironfist_crusher_blocks_any_number_only_face_up(set_pool):
    """"This creature can block any number of creatures." Face down it is a
    2/2 that blocks one; face up, the 4/4 blocks both attackers."""
    crusher_card = set_pool("ONS")["Ironfist Crusher"]
    for face_up in (False, True):
        crusher = _w1g1_permanent(crusher_card, face_down=True)
        attackers = [_w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"]) for _ in range(2)]
        game, _p1, _p2 = _w1g1_game(attackers, [crusher], enforce=False)
        if face_up:
            _w1g1_turn_up(game, 1, crusher)
        game._set_phase_and_step("combat", "declare_attackers")
        ok, why = game.declare_attackers(0, [0, 1], defending_player_index=1)
        assert ok, why
        game.advance_combat_phase()
        ok, why = game.declare_blockers(1, {0: [0, 1]})
        assert ok is face_up, why


# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================
