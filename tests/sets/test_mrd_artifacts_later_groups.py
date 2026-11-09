"""Mirrodin artifacts, the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

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
#
# Farsight Mask: "Whenever a source an opponent controls deals damage to you,
# if this artifact is untapped, you may draw a card." The `damage_dealt` row's
# seat narrowing on the damager's side ("a source **an opponent** controls"),
# once per source (each attacker separately, 2004-12-01), with CR 603.4's
# intervening "if" asked as it triggers and again as it resolves.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                 interactive=()):
    """Seat 0 (A) in its first main phase, mana off; each named permanent
    untapped and able to act."""
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
        ),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Island")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g12_settle(game):
    """Drain the stack and take every offer a headless seat is owed."""
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()


def test_w1g12_farsight_mask_draws_once_per_opposing_source(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 16
    assert len(game.players[0].hand) == 2


def test_w1g12_farsight_mask_ignores_your_own_source_and_a_tapped_mask(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask", "Pyrite Spellbomb"],
    )
    assert game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=0, ability_index=0,
    ).supported
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Grizzly Bears"],
    )
    mask.tapped = True
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []


def test_w1g12_farsight_mask_tapped_before_it_resolves_draws_nothing(set_pool):
    # 2004-12-01: "Farsight Mask must be untapped both when the damage is
    # dealt and when you would draw the card." Bolted, the trigger waits on
    # the stack, and the Mask is tapped in response.
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Farsight Mask"]
    mask.tapped = True
    _w1g12_settle(game)
    assert game.players[0].hand == []
    assert "Farsight Mask ability did nothing: its condition is no longer true" in game.log


def test_w1g12_farsight_mask_asks_an_interactive_seat(set_pool):
    for accept, drawn in ((True, 1), (False, 0)):
        game, _, _ = _w1g12_table(
            set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
            interactive=(0,),
        )
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        game.resolve_top_of_stack()
        game.resolve_top_of_stack()
        assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=accept)
        _w1g12_settle(game)
        assert len(game.players[0].hand) == drawn


# Damping Matrix: "Activated abilities of artifacts and creatures can't be
# activated unless they're mana abilities." Null Rod's board-wide row
# (``activation_prohibitions``) with a type list and CR 605.1a's exception,
# asked of the ability on every road: the activation path, the wire's
# ``ability_denials`` and the AI's choosers.


def test_w1g12_damping_matrix_stops_nonmana_abilities_of_artifacts_and_creatures(set_pool):
    game, (_matrix, sorcerer, _elves, bomb, scimitar), (exile,) = _w1g12_table(
        set_pool,
        mine=["Damping Matrix", "Prodigal Sorcerer", "Llanowar Elves",
              "Pyrite Spellbomb", "Leonin Scimitar"],
        theirs=["Tel-Jilad Exile"],
    )
    refused = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert not refused.supported
    assert "(Damping Matrix)" in refused.details
    # Refused before the cost: the Spellbomb is not sacrificed.
    assert not game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=1, ability_index=0,
    ).supported
    assert game.is_on_battlefield(bomb)
    # Equip is an activated ability of an artifact (2017-03-14).
    assert not game.activate_permanent_ability(
        0, "Leonin Scimitar", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    assert not game.activate_permanent_ability(1, "Tel-Jilad Exile").supported
    assert game.players[1].life == 20


def test_w1g12_damping_matrix_leaves_mana_abilities_open(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Damping Matrix", "Llanowar Elves", "Sol Ring", "Seat of the Synod"],
    )
    assert game.activate_permanent_ability(0, "Llanowar Elves").supported
    assert game.activate_permanent_ability(0, "Sol Ring").supported
    assert game.players[0].mana_pool["G"] == 1
    assert game.players[0].mana_pool["C"] == 2


def test_w1g12_damping_matrix_is_on_the_wire_and_ends_when_it_leaves(set_pool):
    from web.offers import _ability_denial

    game, (matrix, sorcerer, elves), _ = _w1g12_table(
        set_pool, mine=["Damping Matrix", "Prodigal Sorcerer", "Llanowar Elves"],
    )
    (ping,) = game.usable_abilities_of(sorcerer)
    (tap,) = game.usable_abilities_of(elves)
    assert "(Damping Matrix)" in (_ability_denial(game, 0, sorcerer, ping) or "")
    assert _ability_denial(game, 0, elves, tap) is None
    game.remove_from_battlefield(matrix)
    assert _ability_denial(game, 0, sorcerer, ping) is None
    assert game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 19


# Quicksilver Fountain. "At the beginning of each player's upkeep, that player
# puts a flood counter on target non-Island land they control of their choice.
# That land is an Island for as long as it has a flood counter on it." / "At
# the beginning of each end step, if all lands on the battlefield are Islands,
# remove all flood counters from them." The Abyss's choice made by the upkeep
# player, a CR 305.7 land-type change ended by the last flood counter
# (``named_counters.remove_counters``), and a universal condition whose set
# "them" names.


def _w1g12_flood(land):
    from engine.named_counters import counters_on

    return counters_on(land, "flood")


def test_w1g12_quicksilver_fountain_floods_a_land_of_the_upkeep_players(set_pool):
    game, (_fountain, plains), (mountain, forest) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"], theirs=["Mountain", "Forest"],
    )
    # A's own upkeep ran as the table opened: A's only land is flooded.
    assert _w1g12_flood(plains) == 1 and plains.has_type("island")
    assert not plains.has_type("plains")
    game.start_turn(1)
    _w1g12_settle(game)
    flooded = [land for land in (mountain, forest) if _w1g12_flood(land)]
    assert len(flooded) == 1
    (land,) = flooded
    assert land.has_type("island")
    assert land.effective_produced_mana == ("U",)


def test_w1g12_quicksilver_fountain_asks_the_upkeep_player_for_their_land(set_pool):
    game, (_fountain, plains), (mountain, forest, island) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"],
        theirs=["Mountain", "Forest", "Island"], interactive=(1,),
    )
    game.start_turn(1)
    assert not game.resolve_top_of_stack()  # held for B's answer
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("permanent_choice", 1)
    # Not an Island, and not another player's land.
    assert not game.confirm_permanent_choice(1, island.permanent_id)
    assert not game.confirm_permanent_choice(1, plains.permanent_id)
    assert game.confirm_permanent_choice(1, forest.permanent_id)
    _w1g12_resolve_stack(game)
    assert _w1g12_flood(forest) == 1 and forest.has_type("island")
    assert _w1g12_flood(mountain) == 0 and mountain.has_type("mountain")


def test_w1g12_quicksilver_fountain_end_step_resets_an_all_island_board(set_pool):
    game, _, (mountain,) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Island"], theirs=["Mountain"],
    )
    game.start_turn(1)
    _w1g12_settle(game)
    assert mountain.has_type("island") and _w1g12_flood(mountain) == 1
    game.resolve_end_step(1)
    _w1g12_settle(game)
    assert _w1g12_flood(mountain) == 0
    assert mountain.has_type("mountain") and not mountain.has_type("island")


def test_w1g12_quicksilver_fountain_end_step_waits_while_a_land_is_not_an_island(set_pool):
    game, (_fountain, plains), (mountain, forest) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"], theirs=["Mountain", "Forest"],
    )
    game.start_turn(1)
    _w1g12_settle(game)
    game.resolve_end_step(1)
    _w1g12_settle(game)
    # One of B's two lands is still not an Island: nothing is removed.
    assert _w1g12_flood(plains) == 1
    assert sum(_w1g12_flood(land) for land in (mountain, forest)) == 1


def test_w1g12_quicksilver_fountains_island_outlives_it_and_ends_with_the_counter(set_pool):
    # 2004-12-01: "The land stays an Island until the flood counter is
    # removed, even if Quicksilver Fountain leaves the battlefield." And once
    # the counter is gone the effect is over (CR 611.2b): a flood counter put
    # back later does not revive it.
    from engine.named_counters import add_counters, remove_counters

    game, (fountain, plains), _ = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"],
    )
    game.remove_from_battlefield(fountain)
    assert plains.has_type("island") and not plains.has_type("plains")
    remove_counters(plains, "flood", 1)
    assert plains.has_type("plains") and not plains.has_type("island")
    add_counters(plains, "flood", 1)
    assert plains.has_type("plains") and not plains.has_type("island")

# ==== end W1G12 ======================================================
