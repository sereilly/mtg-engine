"""Apocalypse instants.

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

from engine import Game as _w1g5i_Game, PlayerState as _w1g5i_Player
from engine import faces as _w1g5i_faces
from engine.models import Permanent as _w1g5i_Permanent
from tests.helpers import _mk_card as _w1g5i_mk_card
from tests.helpers import resolve_stack as _w1g5i_resolve_stack

_W1G5I_REQUIRED = "must be chosen as a target if able"


def _w1g5i_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0, interactive=()):
    """Two boards placed and unsick, *active*'s turn begun."""
    board0 = [_w1g5i_Permanent(card=card) for card in mine]
    board1 = [_w1g5i_Permanent(card=card) for card in theirs]
    filler = _w1g5i_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5i_Game(players=[
        _w1g5i_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5i_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 instants: the duel


def _w1g5i_half(card, name):
    """The half of a split card named *name* (CR 709.3) — the card the picker
    and the cast path are asked about."""
    return next(face for face in _w1g5i_faces.face_cards(card) if face.name == name)  # W1G5


def _w1g5i_stats(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # W1G5 instants


def test_fire_divides_two_damage_among_one_or_two_targets(set_pool):
    """Fire // Ice, the Fire half {1}{R}: "Fire deals 2 damage divided as you
    choose among one or two targets." Cast by the half's name; one damage to a
    2/1 and one to a face; and the refusals around it — three targets, a
    division that does not total 2, no target at all, and the card's whole
    name — each with the card still in hand."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Savannah Lions"], lea["Grizzly Bears"]], hand0=[card],
    )
    lions, bears = theirs
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Fire"))
    assert (spec["kind"], spec["division"], spec["max_targets"], spec["division_total"]) == (
        "divided", "chosen", 2, 2,
    )
    for announcement, why in (
        ({"divided_targets": [(1, 0, 1), (1, 1, 1), (1, None, 0)]}, "at most 2 targets"),
        ({"divided_targets": [(1, 0, 2), (1, 1, 1)]}, "must total 2"),
        ({}, "at least one target"),
    ):
        refused = game.queue_from_hand(0, "Fire", **announcement)
        assert not refused.supported and why in refused.details, refused
    whole = game.queue_from_hand(0, "Fire // Ice", target_player_index=1)
    assert not whole.supported and "split card" in whole.details
    assert game.players[0].hand == [card] and not game.stack

    assert game.queue_from_hand(
        0, "Fire", divided_targets=[(1, game.battlefield_index_of(lions), 1), (1, None, 1)],
    ).supported
    _w1g5i_resolve_stack(game)
    game._settle()
    assert game.players[1].life == 19
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert bears.damage_marked == 0
    # CR 709.4: in the graveyard it is the whole card again, once.
    assert [c.name for c in game.players[0].graveyard] == ["Fire // Ice"]


def test_fire_must_put_one_of_its_two_targets_on_a_flagbearer(set_pool):
    """Two slots under Standard Bearer: the rule is about the announcement,
    not about each target. A division with no Flagbearer in it is refused;
    one damage to the Bearer and one to the Bears is accepted, and both die
    or bleed as dealt — the second slot is free."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel(
        [], [apc["Standard Bearer"], lea["Grizzly Bears"]], hand0=[card],
    )
    bearer, bears = theirs
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Fire"))
    assert [entry["id"] for entry in spec["required_targets"]] == [bearer.permanent_id]
    # The list is whole: a second slot may be anything Fire could target.
    assert {entry.get("name") for entry in spec["valid_targets"]} >= {
        "Standard Bearer", "Grizzly Bears",
    }
    assert any(entry["kind"] == "player" for entry in spec["valid_targets"])

    bears_slot, bearer_slot = game.battlefield_index_of(bears), game.battlefield_index_of(bearer)
    refused = game.queue_from_hand(
        0, "Fire", divided_targets=[(1, bears_slot, 1), (1, None, 1)],
    )
    assert not refused.supported and _W1G5I_REQUIRED in refused.details, refused
    assert game.queue_from_hand(
        0, "Fire", divided_targets=[(1, bearer_slot, 1), (1, bears_slot, 1)],
    ).supported
    _w1g5i_resolve_stack(game)
    assert bears.damage_marked == 1
    game._settle()
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_ice_taps_a_permanent_and_draws(set_pool):
    """The Ice half {1}{U}: "Tap target permanent. / Draw a card." Any
    permanent — a land here — and the card is drawn by the caster."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Forest"]], hand0=[card])
    forest = theirs[0]
    library = len(game.players[0].library)
    assert game.cast_from_hand(0, "Ice", target_permanent_ids=[forest.permanent_id]).supported
    assert forest.tapped
    assert len(game.players[0].hand) == 1 and len(game.players[0].library) == library - 1
    assert len(game.players[1].hand) == 0


def test_illusion_turns_a_permanent_the_colour_its_caster_names_for_a_turn(set_pool):
    """Illusion // Reality, the Illusion half {U}: "Target spell or permanent
    becomes the color of your choice until end of turn." The colour is asked
    as the spell resolves (CR 608.2d), of its caster; the green Bears are blue
    — and nothing else — until cleanup, and green again after it."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Illusion // Reality"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Grizzly Bears"]], hand0=[card], interactive=(0,))
    bears = theirs[0]
    assert set(bears.effective_colors) == {"G"}
    assert game.queue_from_hand(0, "Illusion", target_permanent_ids=[bears.permanent_id]).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert set(bears.effective_colors) == {"G"}, "nothing is recoloured before the answer"
    assert game.confirm_color_choice(0, "U")
    _w1g5i_resolve_stack(game)
    assert set(bears.effective_colors) == {"U"}
    game.resolve_cleanup_step(0)
    assert set(bears.effective_colors) == {"G"}


def test_reality_destroys_an_artifact_and_nothing_else(set_pool):
    """The Reality half {2}{G}: "Destroy target artifact." A creature named
    for it is refused at the announcement; the Sol Ring goes to its owner's
    graveyard."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Illusion // Reality"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Grizzly Bears"], lea["Sol Ring"]], hand0=[card])
    bears, ring = theirs
    offered = game.cast_target_spec(0, _w1g5i_half(card, "Reality"))["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Sol Ring"]
    refused = game.queue_from_hand(0, "Reality", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and game.players[0].hand == [card]
    assert game.cast_from_hand(0, "Reality", target_permanent_ids=[ring.permanent_id]).supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Sol Ring"]


def test_night_shrinks_one_creature_for_the_turn(set_pool):
    """Night // Day, the Night half {B}: "Target creature gets -1/-1 until end
    of turn." A 2/1 dies of it; a 2/2 is a 1/1 until cleanup and a 2/2 after."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Night // Day"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Savannah Lions"], lea["Grizzly Bears"]], hand0=[card, card],
    )
    lions, bears = theirs
    assert game.cast_from_hand(0, "Night", target_permanent_ids=[lions.permanent_id]).supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Savannah Lions"]
    assert game.cast_from_hand(0, "Night", target_permanent_ids=[bears.permanent_id]).supported
    assert _w1g5i_stats(bears) == (1, 1)
    game.resolve_cleanup_step(0)
    assert _w1g5i_stats(bears) == (2, 2)


def test_day_pumps_the_creatures_of_the_player_it_targets_and_no_others(set_pool):
    """The Day half {2}{W}: "Creatures target player controls get +1/+1 until
    end of turn." The picker is a player picker — it derived none, so a client
    sent a bare cast — and the pump reaches that player's creatures alone: it
    used to compile as "all creatures" and pump both boards. Each seat in
    turn; gone at cleanup; a creature arriving afterwards is not pumped
    (CR 611.2c)."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Night // Day"]
    game, mine, theirs = _w1g5i_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"], lea["Grizzly Bears"]],
        hand0=[card, card],
    )
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Day"))
    assert spec["kind"] == "player"
    assert [entry["seat"] for entry in spec["valid_targets"]] == [0, 1]

    assert game.cast_from_hand(0, "Day", target_player_index=0).supported
    assert _w1g5i_stats(mine[0]) == (3, 3)
    assert [_w1g5i_stats(p) for p in theirs] == [(2, 1), (2, 2)]
    late = _w1g5i_Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert _w1g5i_stats(late) == (2, 2)

    assert game.cast_from_hand(0, "Day", target_player_index=1).supported
    assert [_w1g5i_stats(p) for p in theirs] == [(3, 2), (3, 3)]
    assert _w1g5i_stats(mine[0]) == (3, 3)
    game.resolve_cleanup_step(0)
    assert _w1g5i_stats(mine[0]) == (2, 2)
    assert [_w1g5i_stats(p) for p in theirs] == [(2, 1), (2, 2)]


def test_order_exiles_an_attacking_creature_and_only_one(set_pool):
    """Order // Chaos, the Order half {3}{W}: "Exile target attacking
    creature." Outside combat it has no legal target and is refused; once the
    Bears attack, the Bears are its only target — the Lions that stayed home
    are not offered — and are exiled."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Order // Chaos"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Grizzly Bears"], lea["Savannah Lions"]], hand0=[card], active=1,
    )
    bears, lions = theirs
    refused = game.queue_from_hand(0, "Order", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and game.players[0].hand == [card]

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [game.battlefield_index_of(bears)])[0]
    offered = game.cast_target_spec(0, _w1g5i_half(card, "Order"))["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]
    assert not game.queue_from_hand(
        0, "Order", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Order", target_permanent_ids=[bears.permanent_id]).supported
    _w1g5i_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Savannah Lions"]
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == []


def test_chaos_stops_every_block_this_turn_including_a_late_arrival(set_pool):
    """The Chaos half {2}{R}: "Creatures can't block this turn." No target.
    Neither the Lions that were there nor a Bears that arrives after Chaos
    resolved may be declared as a blocker ("including ones that weren't on the
    battlefield as Chaos resolved" — ruling, 2022-12-08), and after cleanup
    they may."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Order // Chaos"]
    game, mine, theirs = _w1g5i_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"]], hand0=[card],
    )
    attacker, lions = mine[0], theirs[0]
    assert game.cast_target_spec(0, _w1g5i_half(card, "Chaos"))["kind"] == "none"
    assert game.cast_from_hand(0, "Chaos").supported
    late = _w1g5i_Permanent(card=lea["Grizzly Bears"])
    late.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(1, late, None)

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    for blocker in (lions, late):
        declared = game.declare_blockers(1, {
            game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)],
        })
        assert declared[0] is False, (blocker.card.name, declared)
    game.resolve_cleanup_step(0)
    assert game.blocking_restrictions_until_eot == []

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
