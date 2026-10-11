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

from engine import Game as _w1g3s_Game, PlayerState as _w1g3s_Player
from engine.game_types import CardDefinition as _w1g3s_CardDefinition


def _w1g3s_index_game(set_pool, size, *, interactive=()):
    """Index in seat 0's hand over a library of *size* numbered cards."""
    library = [
        _w1g3s_CardDefinition(
            name=f"Card {n}", mana_cost="", cmc=0.0, type_line="Land",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": f"Card {n}", "type_line": "Land"},
        )
        for n in range(1, size + 1)
    ]
    game = _w1g3s_Game(players=[
        _w1g3s_Player(name="P0", hand=[set_pool("APC")["Index"]], library=library),
        _w1g3s_Player(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game  # W1G3 sorceries: the Index game


def test_w1g3_index_puts_the_top_five_back_in_the_order_its_caster_chooses(set_pool):
    """"Look at the top five cards of your library, then put them back in any
    order." The caster is shown five of six and asked for an order; a
    permutation of the wrong length is refused, the answer is the new top of
    the library, and the sixth card stays sixth. Nothing is drawn."""
    game = _w1g3s_index_game(set_pool, 6, interactive={0})
    me = game.players[0]

    assert game.cast_from_hand(0, "Index").supported

    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert waiting.data["top_count"] == 5 and waiting.data.get("position") is None
    assert [c.name for c in game.reorder_library_pile(waiting)] == [
        f"Card {n}" for n in range(1, 6)
    ]
    assert [item.card.name for item in game.stack] == ["Index"]

    assert not game.confirm_reorder_library(0, [0, 1, 2])
    assert not game.confirm_reorder_library(0, [5, 4, 3, 2, 1])
    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
    game._settle()

    assert [c.name for c in me.library] == [
        "Card 5", "Card 4", "Card 3", "Card 2", "Card 1", "Card 6",
    ]
    assert me.hand == [] and game.stack == []
    assert [c.name for c in me.graveyard] == ["Index"]


def test_w1g3_index_over_a_short_library_orders_what_is_there(set_pool):
    """Three cards are looked at when three is all there is (CR 609.3), and
    one card has no order to choose: nothing is asked and the spell resolves."""
    game = _w1g3s_index_game(set_pool, 3, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.waiting_prompt().data["top_count"] == 3
    assert game.confirm_reorder_library(0, [1, 2, 0])
    game._settle()
    assert [c.name for c in game.players[0].library] == ["Card 2", "Card 3", "Card 1"]

    game = _w1g3s_index_game(set_pool, 1, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.pending_choices == [] and game.stack == []
    assert [c.name for c in game.players[0].library] == ["Card 1"]
    assert [c.name for c in game.players[0].graveyard] == ["Index"]

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5s_Game, PlayerState as _w1g5s_Player
from engine import faces as _w1g5s_faces
from engine.models import Permanent as _w1g5s_Permanent
from tests.helpers import _mk_card as _w1g5s_mk_card
from tests.helpers import resolve_stack as _w1g5s_resolve_stack


def _w1g5s_duel(mine=(), theirs=(), *, hand0=(), graveyard0=(), graveyard1=()):
    """Two boards placed and unsick, seat 0's turn begun."""
    board0 = [_w1g5s_Permanent(card=card) for card in mine]
    board1 = [_w1g5s_Permanent(card=card) for card in theirs]
    filler = _w1g5s_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5s_Game(players=[
        _w1g5s_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10, graveyard=list(graveyard0)),
        _w1g5s_Player(name="P1", battlefield=board1, library=[filler] * 10,
                      graveyard=list(graveyard1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._settle()
    return game, board0, board1  # W1G5 sorceries: the duel


def _w1g5s_half(card, name):
    return next(face for face in _w1g5s_faces.face_cards(card) if face.name == name)  # W1G5


def test_life_makes_its_casters_lands_creatures_that_are_still_lands(set_pool):
    """Life // Death, the Life half {G}: "All lands you control become 1/1
    creatures until end of turn. They're still lands." The caster's Forests
    are 1/1 creatures and still Forests; the opponent's is untouched; a land
    played afterwards is not animated (CR 611.2c); and at cleanup they are
    lands and nothing else."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, mine, theirs = _w1g5s_duel(
        [lea["Forest"], lea["Forest"], lea["Grizzly Bears"]], [lea["Forest"]], hand0=[card],
    )
    assert game.cast_target_spec(0, _w1g5s_half(card, "Life"))["kind"] == "none"
    assert game.cast_from_hand(0, "Life").supported
    for forest in mine[:2]:
        assert forest.is_creature and forest.has_type("land") and forest.has_type("forest")
        assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert (mine[2].effective_power, mine[2].effective_toughness) == (2, 2)
    assert not theirs[0].is_creature
    late = _w1g5s_Permanent(card=lea["Forest"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert not late.is_creature
    game.resolve_cleanup_step(0)
    assert not any(forest.is_creature for forest in mine[:2])
    assert all(forest.has_type("forest") for forest in mine[:2])


def test_death_returns_a_creature_card_and_charges_its_mana_value_in_life(set_pool):
    """The Death half {1}{B}: "Return target creature card from your graveyard
    to the battlefield. You lose life equal to its mana value." The Craw Wurm
    (mana value 6) comes back under its owner's control and the caster is at
    14. Only a creature card, only the caster's own graveyard: a Bolt there and
    a creature in the opponent's are neither offered nor accepted, and with
    nothing to return the spell cannot be cast."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, _mine, _theirs = _w1g5s_duel(
        hand0=[card], graveyard0=[lea["Lightning Bolt"], lea["Craw Wurm"]],
        graveyard1=[lea["Grizzly Bears"]],
    )
    offered = game.cast_target_spec(0, _w1g5s_half(card, "Death"))["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Craw Wurm")]
    for announcement in (
        {"target_player_index": 0, "target_permanent_index": 0},   # the Bolt
        {"target_player_index": 1, "target_permanent_index": 0},   # their Bears
    ):
        refused = game.queue_from_hand(0, "Death", **announcement)
        assert not refused.supported, refused
    assert game.players[0].hand == [card]

    assert game.cast_from_hand(
        0, "Death", target_player_index=0, target_permanent_index=1
    ).supported
    wurm = next(iter(game.controlled_by(0)))
    assert wurm.card.name == "Craw Wurm"
    assert game.players[0].life == 14 and game.players[1].life == 20
    assert sorted(c.name for c in game.players[0].graveyard) == ["Life // Death", "Lightning Bolt"]

    empty, _mine, _theirs = _w1g5s_duel(hand0=[card], graveyard0=[lea["Lightning Bolt"]])
    refused = empty.queue_from_hand(0, "Death")
    assert not refused.supported and "no valid target" in refused.details


def test_vindicate_destroys_whatever_permanent_it_names(set_pool):
    """Vindicate {1}{W}{B}: "Destroy target permanent." A land, an artifact,
    an enchantment, a creature — each named by id and each in its owner's
    graveyard afterwards, with the rest of the board where it was."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], lea["Sol Ring"], lea["Crusade"], lea["Grizzly Bears"]],
        hand0=[vindicate] * 4,
    )
    offered = game.cast_target_spec(0, vindicate)
    assert offered["kind"] == "permanent"
    assert [entry["name"] for entry in offered["valid_targets"]] == [
        "Forest", "Sol Ring", "Crusade", "Grizzly Bears",
    ]
    for victim in theirs:
        before = [p.card.name for p in game.controlled_by(1)]
        assert game.cast_from_hand(
            0, "Vindicate", target_permanent_ids=[victim.permanent_id]
        ).supported
        before.remove(victim.card.name)
        assert [p.card.name for p in game.controlled_by(1)] == before
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Crusade", "Forest", "Grizzly Bears", "Sol Ring",
    ]
    assert game.players[1].life == 20


def test_vindicate_has_to_be_spent_on_a_flagbearer(set_pool):
    """Under Standard Bearer the land Vindicate was held for is not a legal
    announcement while the Bearer can be named; with the Bearer destroyed the
    next one takes the land."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], apc["Standard Bearer"]], hand0=[vindicate, vindicate],
    )
    forest, bearer = theirs
    refused = game.queue_from_hand(0, "Vindicate", target_permanent_ids=[forest.permanent_id])
    assert not refused.supported and "must be chosen as a target if able" in refused.details
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[bearer.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert list(game.controlled_by(1)) == []

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
