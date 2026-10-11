"""Apocalypse sorceries.

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

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.board_payment import board_can_pay as _w1g7_board_can_pay
from engine.grammar import compile_line as _w1g7_compile_line
from engine.mana_payment import mana_cost_from_symbols as _w1g7_cost
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_sorcery_duel(*, interactive=()):
    """A two-seat game with costs off, nobody interactive unless a test says."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, p0, p1


def _w1g7_sorcery_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_floating(player):
    """The mana in *player*'s pool, zero entries dropped."""
    return {symbol: amount for symbol, amount in player.mana_pool.items() if amount}


def _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name):
    """Seat 0 casts False Dawn for free and it resolves; costs then go on."""
    caster = game.players[0]
    caster.hand = [set_pool("APC")["False Dawn"], *caster.hand]
    if not caster.library:
        caster.library = [catalog_by_name["Grizzly Bears"]]
    assert game.cast_from_hand(0, "False Dawn").supported
    _w1g7_resolve_stack(game)
    game.enforce_mana_costs = True


# -- False Dawn --------------------------------------------------------------


def test_false_dawn_turns_the_colored_mana_its_caster_adds_white(
    set_pool, catalog_by_name
):
    """"Until end of turn, spells and abilities you control that would add
    colored mana instead add that much white mana." A land's mana ability, a
    creature's and a ritual are all "abilities and spells you control"; {C} is
    not coloured mana (CR 106.1a) and the opponent's Mountain is not the
    caster's."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    tropical = _w1g7_sorcery_put(game, 0, catalog_by_name["Tropical Island"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Llanowar Elves"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Sol Ring"])
    mountain = _w1g7_sorcery_put(game, 1, catalog_by_name["Mountain"])
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert (
        "False Dawn: colored mana A's spells and abilities would add is {W} "
        "this turn"
    ) in game.log

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"W": 1}
    # A dual land asked for blue still makes white.
    assert game.tap_land_for_mana(0, "Tropical Island", "U", permanent_id=tropical.permanent_id)
    assert _w1g7_floating(p0) == {"W": 2}
    assert game.activate_permanent_ability(0, "Llanowar Elves").supported
    assert _w1g7_floating(p0) == {"W": 3}
    assert "Llanowar Elves added {W} instead (False Dawn)" in game.log
    assert game.activate_permanent_ability(0, "Sol Ring").supported
    assert _w1g7_floating(p0) == {"W": 3, "C": 2}

    assert game.tap_land_for_mana(1, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert _w1g7_floating(p1) == {"R": 1}


def test_false_dawn_lets_white_mana_pay_for_any_color(set_pool, catalog_by_name):
    """"Until end of turn, you may spend white mana as though it were mana of
    any color." Three Forests cast a {2}{U} creature and pay a Dark Ritual's
    {B} — and the Ritual, a spell its caster controls, adds {W}{W}{W} ("that
    much white mana")."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forests = [_w1g7_sorcery_put(game, 0, catalog_by_name["Forest"]) for _ in range(4)]
    p0.hand = [catalog_by_name["Prodigal Sorcerer"], catalog_by_name["Dark Ritual"]]
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert "False Dawn: A may spend {W} as though it were mana of any color this turn" in game.log

    for forest in forests:
        game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"W": 4}

    assert game.cast_from_hand(0, "Prodigal Sorcerer").supported
    assert _w1g7_floating(p0) == {"W": 1}
    assert "Prodigal Sorcerer" in [perm.card.name for perm in p0.battlefield]

    assert game.cast_from_hand(0, "Dark Ritual").supported
    assert _w1g7_floating(p0) == {"W": 3}
    assert "Dark Ritual added {W} instead (False Dawn)" in game.log


def test_false_dawn_is_what_the_castable_highlight_and_the_planner_read(
    set_pool, catalog_by_name
):
    """The payment questions asked *without* tapping anything: what a land
    would put in the pool, and whether the board covers a cost. Before the
    spell two Forests cannot pay {U}{U}; after it they can, and the opponent's
    Mountain still cannot pay {U}."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    mountain = _w1g7_sorcery_put(game, 1, catalog_by_name["Mountain"])
    blue = _w1g7_cost("{U}{U}")
    assert not _w1g7_board_can_pay(game, 0, blue)
    assert game._land_payment_colors(forest) == ("G",)

    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert game._land_payment_colors(forest) == ("W",)
    assert game._land_payment_colors(mountain) == ("R",)
    assert _w1g7_board_can_pay(game, 0, blue)
    assert not _w1g7_board_can_pay(game, 1, _w1g7_cost("{U}"))


def test_false_dawn_changes_no_permanent_and_draws_a_card(set_pool, catalog_by_name):
    """The card's rulings: it "does not change the color of any permanents" and
    "does not change any lands into Plains" — the effect is on mana and on how
    it is spent. And the third sentence: draw a card."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    elves = _w1g7_sorcery_put(game, 0, catalog_by_name["Llanowar Elves"])
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert [card.name for card in p0.hand] == ["Island"]
    assert [card.name for card in p0.graveyard] == ["False Dawn"]
    assert forest.basic_land_types == ("forest",)
    assert game._effective_colors(elves) == {"G"}


def test_false_dawn_ends_in_the_cleanup_step(set_pool, catalog_by_name):
    """Both sentences are "until end of turn": after cleanup the Forest makes
    green again and green does not pay for blue."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert p0.mana_spending_permissions

    game.resolve_cleanup_step(0)

    assert p0.mana_spending_permissions == ()
    assert game._land_payment_colors(forest) == ("G",)
    assert not _w1g7_board_can_pay(game, 0, _w1g7_cost("{U}{U}"))
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"G": 1}


def test_false_dawn_reaches_a_triggered_mana_ability_its_caster_controls(
    set_pool, catalog_by_name
):
    """Wild Growth's "adds an additional {G}" is an ability of the Aura, which
    its controller controls — so it adds {W} too."""
    from engine.auras import attach_aura

    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    growth = _w1g7_sorcery_put(game, 0, catalog_by_name["Wild Growth"])
    attach_aura(growth, forest)
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)

    assert _w1g7_floating(p0) == {"W": 2}
    assert "Wild Growth: A added an additional {W}" in game.log


def test_the_turn_long_mana_sentences_are_read_only_behind_their_window(
    set_pool, catalog_by_name
):
    """The two productions sit behind "Until end of turn," and nowhere else.
    The bare permission is a *static* line two shipped cards print, read by
    ``engine/mana_spending.py``'s derivation — a production that claimed it
    would take both cards' lines away."""
    dawn = _w1g7_compile(set_pool("APC")["False Dawn"])
    assert [step.kind for step in dawn.instructions[0].payload["steps"]] == [
        "swap_controller_added_mana_until_eot", "grant_mana_spending_until_eot",
    ]
    for name in ("Celestial Dawn", "Sunglasses of Urza"):
        program = _w1g7_compile(catalog_by_name[name])
        assert program.supported
        assert any(
            step.kind == "derived_static_rule" and step.value == "mana_spending"
            for step in program.instructions
        )

    assert not _w1g7_compile_line(
        "You may spend white mana as though it were mana of any color."
    ).parsed
    # The half that takes something away is not a permission, and "colorless"
    # is not a colour coloured mana can become.
    assert not _w1g7_compile_line(
        "Until end of turn, you may spend other mana only as though it were "
        "colorless mana."
    ).parsed
    assert not _w1g7_compile_line(
        "Until end of turn, spells and abilities you control that would add "
        "colored mana instead add that much colorless mana."
    ).parsed
    # A window with no sweep behind it refuses in the lowering.
    longer = _w1g7_compile_line(
        "Until your next turn, you may spend white mana as though it were mana "
        "of any color."
    )
    assert longer.parsed and not longer.usable


# -- Planar Despair (driven) -------------------------------------------------


def test_planar_despair_shrinks_every_creature_by_its_casters_domain(
    set_pool, catalog_by_name
):
    """"Domain — All creatures get -1/-1 until end of turn for each basic land
    type among lands you control." Island, two Swamps and a Tropical Island are
    three types (Island, Swamp, Forest); the opponent's lands are not counted.
    Both players' 2/2s and a 0/3 die, a 6/4 lives as a 3/1, and the cleanup
    step gives it its size back."""
    game, p0, p1 = _w1g7_sorcery_duel()
    for name in ("Island", "Swamp", "Swamp", "Tropical Island"):
        _w1g7_sorcery_put(game, 0, catalog_by_name[name])
    for name in ("Mountain", "Plains"):
        _w1g7_sorcery_put(game, 1, catalog_by_name[name])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 1, catalog_by_name["Wall of Wood"])
    wurm = _w1g7_sorcery_put(game, 1, catalog_by_name["Craw Wurm"])
    p0.hand = [set_pool("APC")["Planar Despair"]]

    assert game.cast_from_hand(0, "Planar Despair").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert [perm.card.name for perm in p0.battlefield if perm.is_creature] == []
    assert [perm.card.name for perm in p1.battlefield if perm.is_creature] == ["Craw Wurm"]
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)
    assert sorted(card.name for card in p1.graveyard) == ["Grizzly Bears", "Wall of Wood"]

    game.resolve_cleanup_step(0)
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)


def test_planar_despair_with_no_basic_land_type_changes_nothing(
    set_pool, catalog_by_name
):
    """A domain of zero is -0/-0: every creature keeps its size."""
    game, p0, p1 = _w1g7_sorcery_duel()
    _w1g7_sorcery_put(game, 0, catalog_by_name["Mishra's Factory"])
    bears = _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    p0.hand = [set_pool("APC")["Planar Despair"]]

    assert game.cast_from_hand(0, "Planar Despair").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert bears in p1.battlefield


# -- Tranquil Path (driven) --------------------------------------------------


def test_tranquil_path_destroys_every_enchantment_and_draws_a_card(
    set_pool, catalog_by_name
):
    """"Destroy all enchantments. / Draw a card." Both players', Auras
    included; nothing that is not an enchantment is touched."""
    from engine.auras import attach_aura

    game, p0, p1 = _w1g7_sorcery_duel()
    _w1g7_sorcery_put(game, 0, set_pool("APC")["Unnatural Selection"])
    _w1g7_sorcery_put(game, 1, set_pool("APC")["Ice Cave"])
    forest = _w1g7_sorcery_put(game, 1, catalog_by_name["Forest"])
    growth = _w1g7_sorcery_put(game, 1, catalog_by_name["Wild Growth"])
    attach_aura(growth, forest)
    _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Sol Ring"])
    p0.hand = [set_pool("APC")["Tranquil Path"]]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    assert game.cast_from_hand(0, "Tranquil Path").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert [perm.card.name for perm in p0.battlefield] == ["Sol Ring"]
    assert [perm.card.name for perm in p1.battlefield] == ["Forest", "Grizzly Bears"]
    assert sorted(card.name for card in p0.graveyard) == [
        "Tranquil Path", "Unnatural Selection",
    ]
    assert sorted(card.name for card in p1.graveyard) == ["Ice Cave", "Wild Growth"]
    assert [card.name for card in p0.hand] == ["Island"]


def test_tranquil_path_with_no_enchantment_still_draws(set_pool, catalog_by_name):
    """It targets nothing, so an empty board is no reason not to resolve."""
    game, p0, p1 = _w1g7_sorcery_duel()
    p0.hand = [set_pool("APC")["Tranquil Path"]]
    p0.library = [catalog_by_name["Island"]]

    assert game.cast_from_hand(0, "Tranquil Path").supported
    _w1g7_resolve_stack(game)

    assert [card.name for card in p0.hand] == ["Island"]

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
