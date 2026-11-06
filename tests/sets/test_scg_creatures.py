"""Scourge creatures (legendary ones too).

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

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Statics, sweeps, types and counters. Each card is put where it belongs on a
# real board, driven through the engine's own entry points (an activation, a
# declared attack or block, a death, the upkeep), and the board, the counters
# and the log are read afterwards — for a person answering each prompt and for
# a seat nobody asks.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import counters_on as _w1g9_counters_on
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_activation_spec as _w1g9_activation_spec
from tests.helpers import declare_attack as _w1g9_declare_attack
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_permanent(card):
    permanent = _W1G9Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_game(mine=(), theirs=(), *, interactive=False):
    p1 = _W1G9PlayerState(name="A", battlefield=list(mine),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g9_plus1(permanent) -> int:
    return _w1g9_counters_on(permanent, "+1/+1")


# --- Thundercloud Elemental --------------------------------------------------


def test_w1g9_thundercloud_taps_every_creature_with_toughness_two_or_less(set_pool):
    """"{3}{U}: Tap all creatures with toughness 2 or less." Both sides, read
    as the ability resolves: a Bear (2) on each side and an Elf (1) are
    tapped; a Hill Giant (3) and the Elemental itself (4) are not."""
    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    my_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    their_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([elemental, my_bear], [their_bear, elf, giant])
    result = game.activate_permanent_ability(
        0, "Thundercloud Elemental", ability_index=0,
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert my_bear.tapped and their_bear.tapped and elf.tapped
    assert not giant.tapped and not elemental.tapped
    assert any("Thundercloud Elemental tapped" in line for line in game.log)


def test_w1g9_thundercloud_reads_toughness_as_it_resolves(set_pool):
    """The toughness is the creature's as the sweep resolves (layer 7): a Bear
    given +0/+1 in response has toughness 3 and stays untapped."""
    from engine.pt import add_pt_modifier

    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([elemental], [bear])
    result = game.queue_permanent_ability(
        0, "Thundercloud Elemental", ability_index=0,
    )
    assert result.supported, result.details
    assert [item.card.name for item in game.stack] == ["Thundercloud Elemental"]
    add_pt_modifier(bear, 0, 1, until="end_of_turn")
    assert bear.effective_toughness == 3
    _w1g9_resolve_stack(game)
    assert not bear.tapped
    assert any("nothing to tap or untap" in line for line in game.log)


def test_w1g9_thundercloud_strips_flying_from_every_other_creature(set_pool):
    """Its second ability, compiled on arrival: "All other creatures lose
    flying until end of turn" — the Elemental keeps its own."""
    scg = set_pool("SCG")
    elemental = _w1g9_permanent(scg["Thundercloud Elemental"])
    djinn = _w1g9_permanent(_W1G9_CATALOG["Mahamoti Djinn"])
    game, _p1, _p2 = _w1g9_game([elemental], [djinn])
    result = game.activate_permanent_ability(
        0, "Thundercloud Elemental", ability_index=1,
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game._has_keyword(djinn, "flying")
    assert game._has_keyword(elemental, "flying")


# --- Mercurial Kite -------------------------------------------------------------


def _w1g9_untap_step(game, seat):
    """Run *seat*'s untap step the way a turn does."""
    game.active_player_index = seat
    game.turn += 1
    game.start_turn(seat)


def test_w1g9_mercurial_kite_taps_and_freezes_the_creature_it_damages(set_pool):
    """"Whenever this creature deals combat damage to a creature, tap that
    creature. That creature doesn't untap during its controller's next untap
    step." Blocked by a Wall of Air (0/5), the Kite's damage taps the Wall;
    the Wall's controller's next untap step leaves it tapped and the one after
    untaps it."""
    scg = set_pool("SCG")
    kite = _w1g9_permanent(scg["Mercurial Kite"])
    wall = _w1g9_permanent(_W1G9_CATALOG["Wall of Air"])
    game, _p1, _p2 = _w1g9_game([kite], [wall])
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    assert game.is_on_battlefield(wall) and wall.tapped
    assert any("Wall of Air won't untap" in line for line in game.log)
    _w1g9_untap_step(game, 1)
    assert wall.tapped, "held down for its controller's next untap step"
    _w1g9_untap_step(game, 0)
    _w1g9_untap_step(game, 1)
    assert not wall.tapped, "the one after untaps it"


def test_w1g9_mercurial_kite_damaging_a_player_holds_nothing_down(set_pool):
    """Unblocked, the Kite deals its damage to a player: the condition names a
    creature, so nothing triggers and nothing is held down."""
    scg = set_pool("SCG")
    kite = _w1g9_permanent(scg["Mercurial Kite"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g9_game([kite], [bear])
    _w1g9_declare_attack(game, 0)
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    assert p2.life == 18
    assert not bear.tapped
    assert not any("won't untap" in line for line in game.log)


# --- Ageless Sentinels ----------------------------------------------------------


def test_w1g9_ageless_sentinels_becomes_a_bird_giant_and_can_attack(set_pool):
    """"When this creature blocks, it becomes a Bird Giant, and it loses
    defender." Both creature types replace Wall (CR 205.1a; the 2004-10-04
    ruling "It becomes both creature type Giant and creature type Bird"), the
    change outlives the turn (CR 611.2a), and without defender it attacks on
    its controller's turn (the 2005-08-01 ruling)."""
    scg = set_pool("SCG")
    sentinels = _w1g9_permanent(scg["Ageless Sentinels"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([bear], [sentinels])
    assert sentinels.has_type("wall") and game._has_keyword(sentinels, "defender")
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    _w1g9_resolve_stack(game)
    assert sentinels.has_type("bird") and sentinels.has_type("giant")
    assert not sentinels.has_type("wall")
    assert not game._has_keyword(sentinels, "defender")
    assert game._has_keyword(sentinels, "flying")
    for _ in range(3):
        game.advance_combat_phase()
        _w1g9_resolve_stack(game)
    _w1g9_untap_step(game, 1)
    assert sentinels.has_type("bird") and not sentinels.has_type("wall")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        1, [game.battlefield_index_of(sentinels)], defending_player_index=0,
    )
    assert ok, why


def test_w1g9_ageless_sentinels_left_and_back_is_a_wall_again(set_pool):
    """The change is the permanent's (CR 400.7): returned to the battlefield
    it is a new object, a Wall with defender."""
    scg = set_pool("SCG")
    sentinels = _w1g9_permanent(scg["Ageless Sentinels"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g9_game([bear], [sentinels])
    _w1g9_declare_attack(game, 0, blocks={0: 0})
    _w1g9_resolve_stack(game)
    assert sentinels.has_type("giant")
    game.remove_from_battlefield(sentinels)
    again = _W1G9Permanent(card=scg["Ageless Sentinels"])
    game._put_permanent_onto_battlefield(1, again, None)
    assert again.has_type("wall") and not again.has_type("giant")
    assert game._has_keyword(again, "defender")


# --- Ambush Commander -----------------------------------------------------------


def test_w1g9_ambush_commander_makes_its_controllers_forests_green_elves(set_pool):
    """"Forests you control are 1/1 green Elf creatures that are still lands."
    Layer 4 (creature, Elf, still a Forest land), 5 (green) and 7b (1/1) on
    its controller's Forests; an opponent's Forest is untouched; and when the
    Commander leaves, the Forests are lands again (CR 611.3a)."""
    from engine.object_colors import object_colors

    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    island = _w1g9_permanent(_W1G9_CATALOG["Island"])
    their_forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([commander, forest, island], [their_forest])
    assert forest.is_creature and forest.has_type("elf")
    assert forest.has_type("land") and forest.has_type("forest")
    assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert set(object_colors(game, forest)) == {"G"}
    assert not island.is_creature
    assert not their_forest.is_creature and not their_forest.has_type("elf")
    game.remove_from_battlefield(commander)
    game._recompute_continuous_effects()
    assert not forest.is_creature and not forest.has_type("elf")


def test_w1g9_ambush_commander_sacrifices_a_forest_as_an_elf(set_pool):
    """"{1}{G}, Sacrifice an Elf: Target creature gets +3/+3 until end of
    turn." An animated Forest is an Elf, so it pays the cost."""
    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([commander, forest, bear])
    spec = _w1g9_activation_spec(_w1g9_compile(scg["Ambush Commander"]).activated_abilities[0])
    assert spec["cost_spec"]["filter"] == {"subtype_filter": "elf"}
    result = game.activate_permanent_ability(
        0, "Ambush Commander", ability_index=0,
        target_permanent_ids=[bear.permanent_id],
        cost_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(forest)
    assert (bear.effective_power, bear.effective_toughness) == (5, 5)


def test_w1g9_a_forest_that_just_arrived_is_summoning_sick(set_pool):
    """The 2008-08-01 ruling (CR 302.6): an animated land that has not been
    controlled continuously since its controller's turn began can neither
    attack nor be tapped for mana — while one controlled since then can."""
    scg = set_pool("SCG")
    commander = _w1g9_permanent(scg["Ambush Commander"])
    old_forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([commander, old_forest])
    new_forest = _W1G9Permanent(card=_W1G9_CATALOG["Forest"])
    game._put_permanent_onto_battlefield(0, new_forest, None)
    assert new_forest.is_creature and game._is_summoning_sick(new_forest)
    refusal = game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=new_forest.permanent_id,
    )
    assert refusal is not None and not new_forest.tapped
    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=old_forest.permanent_id,
    ) is None
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [game.battlefield_index_of(new_forest)], defending_player_index=1,
    )
    assert not ok


def test_w1g9_a_land_animator_reads_any_creature_type_it_prints(set_pool):
    """Name-agnostic (``engine/land_animation.py``): an invented creature
    printing "Mountains you control are 2/2 red Goblin creatures that are
    still lands." animates Mountains as red Goblins, and one printing a word
    that is neither a colour nor a creature type is refused rather than
    animated as if the word were not there."""
    import dataclasses

    scg = set_pool("SCG")
    goblin_lord = dataclasses.replace(
        scg["Ambush Commander"], name="Invented Goblin Commander",
        oracle_text="Mountains you control are 2/2 red Goblin creatures that are still lands.",
    )
    assert _w1g9_compile(goblin_lord).supported
    refused = dataclasses.replace(
        goblin_lord, name="Invented Artifact Commander",
        oracle_text="Mountains you control are 2/2 artifact Goblin creatures that are still lands.",
    )
    assert not _w1g9_compile(refused).supported
    mountain = _w1g9_permanent(_W1G9_CATALOG["Mountain"])
    forest = _w1g9_permanent(_W1G9_CATALOG["Forest"])
    game, _p1, _p2 = _w1g9_game([_w1g9_permanent(goblin_lord), mountain, forest])
    assert mountain.is_creature and mountain.has_type("goblin")
    assert (mountain.effective_power, mountain.effective_toughness) == (2, 2)
    assert not forest.is_creature


# --- Forgotten Ancient ----------------------------------------------------------


def _w1g9_ancient_board(scg, *, interactive, counters=3):
    ancient = _w1g9_permanent(scg["Forgotten Ancient"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    their_bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, p1, p2 = _w1g9_game([ancient, bear, giant], [their_bear], interactive=interactive)
    if counters:
        game.place_plus1_counters(ancient, counters)
    return game, ancient, bear, giant, their_bear


def _w1g9_to_the_distribution(game):
    """Seat 0's upkeep, with the ancient's trigger resolved up to the prompt
    a person answers: the "you may" first, then the distribution."""
    game.turn = 2
    game.start_turn(0)
    assert not game.resolve_top_of_stack(), "held for the 'may' answer"
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    (choice,) = game.pending_choices_of("counter_distribution", 0)
    return choice


def test_w1g9_forgotten_ancient_moves_counters_where_its_controller_says(set_pool):
    """"At the beginning of your upkeep, you may move any number of +1/+1
    counters from this creature onto other creatures." The 2022-12-08 ruling:
    nothing is targeted, and how many and onto which creatures is chosen as
    the ability resolves — so a person splits three counters between their
    Bear and an opponent's (any creature but itself), and the move is one
    action (CR 122.5)."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    choice = _w1g9_to_the_distribution(game)
    offered = {perm.permanent_id for perm in game.live_counter_distribution(choice)}
    assert offered == {bear.permanent_id, giant.permanent_id, their_bear.permanent_id}
    assert game.counter_distribution_maximum(choice) == 3
    assert game.confirm_counter_distribution(
        0, [bear.permanent_id, their_bear.permanent_id], [2, 1],
    )
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 0
    assert (_w1g9_plus1(bear), _w1g9_plus1(their_bear), _w1g9_plus1(giant)) == (2, 1, 0)
    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
    assert not game.stack and not game.pending_choices


@_w1g9_pytest.mark.parametrize("ids_and_amounts", [
    "over_the_total", "onto_itself", "a_zero_share", "a_repeated_creature",
    "lists_that_do_not_pair",
])
def test_w1g9_forgotten_ancient_refuses_an_answer_the_card_does_not_allow(
    set_pool, ids_and_amounts,
):
    """Every bad answer is refused whole, with nothing moved and the prompt
    still owed: more counters than the source has, the source itself ("other
    creatures"), a share of none, a creature named twice, lists of different
    lengths."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    _w1g9_to_the_distribution(game)
    ids, amounts = {
        "over_the_total": ([bear.permanent_id, giant.permanent_id], [2, 2]),
        "onto_itself": ([ancient.permanent_id], [1]),
        "a_zero_share": ([bear.permanent_id], [0]),
        "a_repeated_creature": ([bear.permanent_id, bear.permanent_id], [1, 1]),
        "lists_that_do_not_pair": ([bear.permanent_id], [1, 1]),
    }[ids_and_amounts]
    assert not game.confirm_counter_distribution(0, ids, amounts)
    assert _w1g9_plus1(ancient) == 3
    assert game.pending_choices_of("counter_distribution", 0)


def test_w1g9_forgotten_ancient_may_move_none(set_pool):
    """"Any number" includes none: two empty lists keep every counter."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=True)
    _w1g9_to_the_distribution(game)
    assert game.confirm_counter_distribution(0, [], [])
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 3
    assert any("no +1/+1 counters moved" in line for line in game.log)


def test_w1g9_forgotten_ancient_default_grows_its_own_strongest_creature(set_pool):
    """A seat nobody asks takes the stated policy: every counter onto its own
    strongest other creature (the Hill Giant, power 3), none onto an
    opponent's."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(set_pool("SCG"), interactive=False)
    game.turn = 2
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    _w1g9_resolve_stack(game)
    assert _w1g9_plus1(ancient) == 0
    assert (_w1g9_plus1(giant), _w1g9_plus1(bear), _w1g9_plus1(their_bear)) == (3, 0, 0)


def test_w1g9_forgotten_ancient_without_counters_offers_nothing(set_pool):
    """With no counter on it there is no move to offer (``offers
    ._action_is_takeable``): the upkeep asks nothing."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(
        set_pool("SCG"), interactive=True, counters=0,
    )
    game.turn = 2
    game.start_turn(0)
    _w1g9_resolve_stack(game)
    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.pending_choices_of("counter_distribution", 0)


def test_w1g9_forgotten_ancient_takes_a_counter_whenever_a_player_casts(set_pool):
    """Its first ability, compiled on arrival: "Whenever a player casts a
    spell, you may put a +1/+1 counter on this creature" — an opponent's
    spell included; the trigger resolves before the spell (the ruling)."""
    game, ancient, bear, giant, their_bear = _w1g9_ancient_board(
        set_pool("SCG"), interactive=False, counters=0,
    )
    game.players[1].hand.append(_W1G9_CATALOG["Giant Growth"])
    game.priority_player_index = 1
    result = game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[their_bear.permanent_id],
    )
    assert result.supported, result.details
    assert [item.card.name for item in game.stack] == ["Giant Growth", "Forgotten Ancient"]
    _w1g9_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g9_plus1(ancient) == 1


# --- Supported on arrival, driven: Nefashu, Carrion Feeder, Trap Digger, -------
# --- Daru Spiritualist ---------------------------------------------------------


@_w1g9_pytest.mark.parametrize("interactive", [False, True])
def test_w1g9_nefashu_shrinks_up_to_five_creatures_when_it_attacks(set_pool, interactive):
    """"Whenever this creature attacks, up to five target creatures each get
    -1/-1 until end of turn." A seat nobody asks names every opposing
    creature; a person names two of three, and only those shrink. The Elf
    named dies as the next step's state check runs."""
    scg = set_pool("SCG")
    nefashu = _w1g9_permanent(scg["Nefashu"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([nefashu], [bear, elf, giant], interactive=interactive)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    if interactive:
        (prompt,) = game.pending_choices_of("trigger_target", 0)
        assert prompt.data.get("up_to")
        assert game.confirm_trigger_target(
            0, permanent_ids=[bear.permanent_id, elf.permanent_id],
        )
    _w1g9_resolve_stack(game)
    game.advance_combat_phase()
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)
    assert not game.is_on_battlefield(elf)
    expected_giant = (3, 3) if interactive else (2, 2)
    assert (giant.effective_power, giant.effective_toughness) == expected_giant
    assert (nefashu.effective_power, nefashu.effective_toughness) == (5, 3)


def test_w1g9_carrion_feeder_eats_a_creature_and_cannot_block(set_pool):
    """"This creature can't block. Sacrifice a creature: Put a +1/+1 counter on
    this creature." """
    scg = set_pool("SCG")
    feeder = _w1g9_permanent(scg["Carrion Feeder"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g9_game([feeder, bear], [giant])
    result = game.activate_permanent_ability(
        0, "Carrion Feeder", ability_index=0, cost_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(bear)
    assert _w1g9_plus1(feeder) == 1 and feeder.effective_power == 2
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(0, {0: 0})
    assert not ok


def test_w1g9_trap_digger_springs_a_trapped_land_on_a_ground_attacker(set_pool):
    """"{2}{W}, {T}: Put a trap counter on target land you control. Sacrifice
    a land with a trap counter on it: This creature deals 3 damage to target
    attacking creature without flying." The counter goes only on the
    controller's own land; the sacrifice must be a trapped land, and the
    target an attacker without flying."""
    scg = set_pool("SCG")
    digger = _w1g9_permanent(scg["Trap Digger"])
    trapped = _w1g9_permanent(_W1G9_CATALOG["Plains"])
    plain = _w1g9_permanent(_W1G9_CATALOG["Plains"])
    their_land = _w1g9_permanent(_W1G9_CATALOG["Mountain"])
    giant = _w1g9_permanent(_W1G9_CATALOG["Hill Giant"])
    djinn = _w1g9_permanent(_W1G9_CATALOG["Mahamoti Djinn"])
    game, _p1, _p2 = _w1g9_game([digger, trapped, plain], [their_land, giant, djinn])
    refused = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=0, target_permanent_ids=[their_land.permanent_id],
    )
    assert not refused.supported
    result = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=0, target_permanent_ids=[trapped.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert _w1g9_counters_on(trapped, "trap") == 1
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [1, 2], defending_player_index=0)
    assert ok, why
    assert not game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[djinn.permanent_id],
        cost_permanent_ids=[trapped.permanent_id],
    ).supported, "a flyer is not a legal target"
    assert not game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[plain.permanent_id],
    ).supported, "an untrapped land pays nothing"
    result = game.activate_permanent_ability(
        0, "Trap Digger", ability_index=1, target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[trapped.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert not game.is_on_battlefield(trapped) and game.is_on_battlefield(plain)
    assert not game.is_on_battlefield(giant)


def test_w1g9_daru_spiritualist_toughens_a_targeted_cleric(set_pool):
    """"Whenever a Cleric creature you control becomes the target of a spell or
    ability, it gets +0/+2 until end of turn." The trigger resolves first, so
    the Spiritualist (a 1/1 Cleric) survives the Shock aimed at it."""
    scg = set_pool("SCG")
    spiritualist = _w1g9_permanent(scg["Daru Spiritualist"])
    game, _p1, p2 = _w1g9_game([spiritualist], [])
    p2.hand.append(_W1G9_CATALOG["Shock"])
    game.active_player_index = 1
    game.priority_player_index = 1
    result = game.queue_from_hand(
        1, "Shock", target_permanent_ids=[spiritualist.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert game.is_on_battlefield(spiritualist)
    assert spiritualist.effective_toughness == 3


@_w1g9_pytest.mark.full
def test_w1g9_the_seeded_games_exercise_the_ancient_and_the_faces(set_pool):
    """The AI simulator over Scourge with W1G9's trigger-driven cards pinned:
    a Forgotten Ancient's upkeep move and a Faces of the Past's choice each
    happen at least once (a floor, never a count)."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        manifest_set_path("SCG", include_measured=True), games=4, seed=7, max_turns=14,
        required_cards=["Forgotten Ancient", "Faces of the Past"],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    assert any("Forgotten Ancient: moved" in line for line in report.log_lines)
    assert any("Faces of the Past: chose" in line for line in report.log_lines)

# ==== end W1G9 ======================================================
