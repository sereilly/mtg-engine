"""Onslaught lands.

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

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: Onslaught's five cycling lands -----------------------------------
#
# "This land enters tapped. / {T}: Add {B}. / Cycling {B}" — a mana source on
# the battlefield, "{B}, Discard this card: Draw a card" in a hand, and never
# the second where it is the first (CR 702.29b / 113.6j). Supported on
# arrival; driven here for the first time.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

_W1G3_CYCLING_LANDS = (
    ("Barren Moor", "B"),
    ("Forgotten Cave", "R"),
    ("Lonely Sandbar", "U"),
    ("Secluded Steppe", "W"),
    ("Tranquil Thicket", "G"),
)


def _w1g3_table(set_pool, *hand):
    ons = set_pool("ONS")
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[ons["Plains"]] * 5,
    )
    game = Game(players=[alice, PlayerState(name="Bob", library=[ons["Plains"]] * 5)])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice


@pytest.mark.parametrize(("name", "symbol"), _W1G3_CYCLING_LANDS)
def test_w1g3_a_cycling_land_cycles_from_hand_for_its_colour(set_pool, name, symbol):
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program)] == [
        "{T}: Add {%s}." % symbol
    ]
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{%s}, Discard this card: Draw a card." % symbol
    ]

    game, alice = _w1g3_table(set_pool, name)
    alice.mana_pool[symbol] = 1
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert alice.mana_pool[symbol] == 0
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]


@pytest.mark.parametrize(("name", "symbol"), _W1G3_CYCLING_LANDS)
def test_w1g3_a_cycling_land_enters_tapped_and_only_taps_for_mana(set_pool, name, symbol):
    """Played, it enters tapped; untapped, its first ability adds its colour
    and the cycling ability is not there to reach."""
    game, alice = _w1g3_table(set_pool, name)
    assert game.cast_from_hand(0, name).supported
    (land,) = [p for p in game.controlled_by(0) if p.card.name == name]
    assert land.tapped, "This land enters tapped."

    land.tapped = False
    assert game.activate_permanent_ability(0, name, ability_index=0).supported
    assert alice.mana_pool[symbol] == 1
    assert game.activate_permanent_ability(0, name, ability_index=1).supported is False
    assert len(alice.library) == 5 and alice.graveyard == []
    assert game.is_on_battlefield(land)

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
from engine.type_changes import gain_types as _w1g7_gain_types
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_perm(pool, name):
    return _w1g7_nosick(_w1g7_Permanent(card=pool[name]))


def _w1g7_game(mine=(), theirs=(), *, p1=None, p2=None):
    one = _w1g7_PlayerState(name="P1", battlefield=list(mine), **(p1 or {}))
    two = _w1g7_PlayerState(name="P2", battlefield=list(theirs), **(p2 or {}))
    game = _w1g7_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def test_w1g7_unholy_grotto_puts_a_zombie_card_on_top(set_pool):
    """"{B}, {T}: Put target Zombie card from your graveyard on top of your
    library." The picker offers the Zombie cards in the activator's own pile
    and nothing else; the activation moves the one named."""
    pool = set_pool("ONS")
    grotto = _w1g7_perm(pool, "Unholy Grotto")
    game, p1, p2 = _w1g7_game(
        [grotto],
        p1={"graveyard": [pool["Wirewood Elf"], pool["Gangrenous Goliath"],
                          pool["Shepherd of Rot"]],
            "library": [pool["Swamp"]] * 3},
        p2={"graveyard": [pool["Aphetto Vulture"]]},
    )
    spec = game.activation_target_spec(0, 0, ability_index=1)
    offered = {
        (entry.get("seat"), entry.get("index")) for entry in spec["valid_targets"]
    }
    assert offered == {(0, 1), (0, 2)}, spec

    result = game.activate_permanent_ability(
        0, "Unholy Grotto", ability_index=1,
        target_role_refs=[{"graveyard_seat": 0, "graveyard_index": 2}],
    )
    assert result.supported, result.details
    _w1g7_resolve(game)
    assert p1.library[0].name == "Shepherd of Rot"
    assert [c.name for c in p1.graveyard] == ["Wirewood Elf", "Gangrenous Goliath"]
    assert grotto.tapped


def test_w1g7_starlit_sanctum_drains_the_sacrificed_clerics_power(set_pool):
    """"{B}, {T}, Sacrifice a Cleric creature: Target player loses life equal
    to the sacrificed creature's power." The power it had as it was
    sacrificed (CR 608.2h) — pumped, not printed — and only a Cleric pays."""
    from engine.pt import add_pt_modifier

    pool = set_pool("ONS")
    sanctum = _w1g7_perm(pool, "Starlit Sanctum")
    cleric = _w1g7_perm(pool, "Daunting Defender")
    elf = _w1g7_perm(pool, "Wirewood Elf")
    game, p1, p2 = _w1g7_game([sanctum, cleric, elf])
    add_pt_modifier(cleric, 2, 0)
    game._recompute_continuous_effects()
    result = game.activate_permanent_ability(
        0, "Starlit Sanctum", ability_index=2, target_player_index=1,
        cost_permanent_ids=[cleric.permanent_id],
    )
    assert result.supported, result.details
    _w1g7_resolve(game)
    assert p2.life == 15
    assert [c.name for c in p1.graveyard] == ["Daunting Defender"]
    assert game.is_on_battlefield(elf)

    # With no Cleric left the cost cannot be paid — the Elf is no Cleric.
    sanctum.tapped = False
    refused = game.activate_permanent_ability(
        0, "Starlit Sanctum", ability_index=2, target_player_index=1,
    )
    assert not refused.supported
    assert game.is_on_battlefield(elf) and p2.life == 15

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# The tribal lands that compiled on arrival and had never been run: each
# non-mana ability through the real activation path, its picker held to the
# printed type.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import (
    derive_activation_spec as _w1g8_derive_activation_spec,
    usable_activated_abilities as _w1g8_usable,
)
from tests.helpers import _nosick as _w1g8_nosick, resolve_stack as _w1g8_resolve


def _w1g8_board(set_pool, mine, theirs=()):
    pool = set_pool("ONS")
    perms = [_w1g8_nosick(_w1g8_Permanent(card=pool[name])) for name in mine]
    others = [_w1g8_nosick(_w1g8_Permanent(card=pool[name])) for name in theirs]
    one = _w1g8_PlayerState(name="P1", battlefield=list(perms), library=[pool["Island"]] * 5)
    two = _w1g8_PlayerState(name="P2", battlefield=list(others), library=[pool["Island"]] * 5)
    game = _w1g8_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, perms, others


def _w1g8_land_ability(land):
    abilities = _w1g8_usable(_w1g8_compile(land.card))
    (index,) = [
        i for i, ability in enumerate(abilities)
        if not ability.source_line.startswith("{T}: Add")
    ]
    return index, abilities[index]


def _w1g8_offered(game, land):
    index, ability = _w1g8_land_ability(land)
    spec = _w1g8_derive_activation_spec(ability)
    return {
        game.players[found["seat"]].battlefield[found["index"]].permanent_id
        for found in game._enumerate_targets(0, land.card, spec, for_cast=False)
        if found["kind"] == "permanent"
    }


def _w1g8_use(game, land, target=None):
    index, _ability = _w1g8_land_ability(land)
    kwargs = {"ability_index": index}
    if target is not None:
        kwargs.update(
            target_player_index=game.controller_index_of(target),
            target_permanent_ids=[target.permanent_id],
        )
    result = game.activate_permanent_ability(0, land.card.name, **kwargs)
    assert result.supported, result.details
    _w1g8_resolve(game)
    game._recompute_continuous_effects()
    assert land.tapped


def test_w1g8_riptide_laboratory_returns_a_wizard_you_control(set_pool):
    game, (lab, wizard, elf), (theirs,) = _w1g8_board(
        set_pool, ["Riptide Laboratory", "Aphetto Grifter", "Wirewood Elf"],
        ["Aphetto Grifter"],
    )
    assert _w1g8_offered(game, lab) == {wizard.permanent_id}
    _w1g8_use(game, lab, wizard)
    assert [card.name for card in game.players[0].hand] == ["Aphetto Grifter"]
    assert game.is_on_battlefield(theirs) and game.is_on_battlefield(elf)


def test_w1g8_daru_encampment_and_goblin_burrows_pump_their_type(set_pool):
    game, (camp, burrows, soldier, goblin), _ = _w1g8_board(
        set_pool, ["Daru Encampment", "Goblin Burrows", "Glory Seeker", "Skirk Prospector"],
    )
    assert _w1g8_offered(game, camp) == {soldier.permanent_id}
    assert _w1g8_offered(game, burrows) == {goblin.permanent_id}
    _w1g8_use(game, camp, soldier)
    _w1g8_use(game, burrows, goblin)
    assert (soldier.effective_power, soldier.effective_toughness) == (3, 3)
    assert (goblin.effective_power, goblin.effective_toughness) == (3, 1)
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert (soldier.effective_power, goblin.effective_power) == (2, 1)


def test_w1g8_wirewood_lodge_untaps_an_elf(set_pool):
    game, (lodge, elf, seeker), (their_elf,) = _w1g8_board(
        set_pool, ["Wirewood Lodge", "Wirewood Elf", "Glory Seeker"], ["Wirewood Elf"],
    )
    elf.tapped = seeker.tapped = their_elf.tapped = True
    assert _w1g8_offered(game, lodge) == {elf.permanent_id, their_elf.permanent_id}, (
        '"target Elf" names no controller'
    )
    _w1g8_use(game, lodge, elf)
    assert not elf.tapped and seeker.tapped and their_elf.tapped


def test_w1g8_seaside_haven_sacrifices_a_bird_to_draw(set_pool):
    game, (haven, bird, seeker), _ = _w1g8_board(
        set_pool, ["Seaside Haven", "Aven Brigadier", "Glory Seeker"],
    )
    _w1g8_use(game, haven)
    assert len(game.players[0].hand) == 1
    assert not game.is_on_battlefield(bird) and game.is_on_battlefield(seeker)

    # No Bird left: the cost cannot be paid and nothing happens.
    haven.tapped = False
    index, _ability = _w1g8_land_ability(haven)
    refused = game.activate_permanent_ability(0, "Seaside Haven", ability_index=index)
    assert not refused.supported
    assert game.is_on_battlefield(seeker) and len(game.players[0].hand) == 1


def test_w1g8_contested_cliffs_makes_your_beast_fight(set_pool):
    """'Target Beast creature you control fights target creature an opponent
    controls.' Each deals damage equal to its power to the other (CR 701.14)."""
    game, (cliffs, beast, _seeker), (elf, _goliath) = _w1g8_board(
        set_pool, ["Contested Cliffs", "Graxiplon", "Glory Seeker"],
        ["Wirewood Elf", "Gangrenous Goliath"],
    )
    index, _ability = _w1g8_land_ability(cliffs)
    result = game.activate_permanent_ability(
        0, "Contested Cliffs", ability_index=index, target_player_index=0,
        target_permanent_ids=[beast.permanent_id, elf.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve(game)
    assert not game.is_on_battlefield(elf)
    assert beast.damage_marked == 1

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# --- W1G12: revealing (drive list) --------------------------------------------
from engine import Game as _w1g12_Game
from engine.models import PlayerState as _w1g12_PlayerState


def test_w1g12_grand_coliseum_enters_tapped_and_only_its_colour_costs_life(set_pool):
    """"This land enters tapped. / {T}: Add {C}. / {T}: Add one mana of any
    color. This land deals 1 damage to you." Played, it is tapped; its {C} is
    painless; any colour — red here — costs its controller 1 life, dealt by
    the land (CR 120.3)."""
    ons = set_pool("ONS")
    alice = _w1g12_PlayerState(name="Alice", hand=[ons["Grand Coliseum"]])
    game = _w1g12_Game(players=[alice, _w1g12_PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    assert game.cast_from_hand(0, "Grand Coliseum").supported
    (land,) = [p for p in game.controlled_by(0) if p.card.name == "Grand Coliseum"]
    assert land.tapped, "This land enters tapped."

    land.tapped = False
    assert game.activate_permanent_ability(0, "Grand Coliseum", ability_index=0).supported
    assert alice.mana_pool["C"] == 1 and alice.life == 20
    land.tapped = False
    assert game.activate_permanent_ability(
        0, "Grand Coliseum", ability_index=1, mana_color="R",
    ).supported
    resolve_stack(game)
    assert alice.mana_pool["R"] == 1
    assert alice.life == 19
    assert any("Grand Coliseum dealt 1 damage to Alice" in line for line in game.log)

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
