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

from engine import Game as _w1g3i_Game, PlayerState as _w1g3i_Player
from engine.game_types import CardDefinition as _w1g3i_CardDefinition
from engine.models import Permanent as _w1g3i_Permanent
from tests.helpers import resolve_stack as _w1g3i_resolve_stack


def _w1g3i_card(name, type_line, power="2", toughness="2"):
    return _w1g3i_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 instants: a typed card


def _w1g3i_bolt_game(set_pool, *, theirs=(), interactive=()):
    """Prophetic Bolt in seat 0's hand over a five-card library."""
    board1 = [_w1g3i_Permanent(card=card) for card in theirs]
    library = [_w1g3i_card(f"Card {n}", "Land") for n in range(1, 6)]
    game = _w1g3i_Game(players=[
        _w1g3i_Player(
            name="P0", hand=[set_pool("APC")["Prophetic Bolt"]], library=library,
        ),
        _w1g3i_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board1  # W1G3 instants: the Bolt's game


def test_w1g3_prophetic_bolt_offers_any_target_and_refuses_what_is_not_one(set_pool):
    """"Prophetic Bolt deals 4 damage to any target." The picker offers both
    players and the creature (CR 115.4) and not the artifact beside it; naming
    the artifact is refused at announcement with the card still in hand."""
    game, theirs = _w1g3i_bolt_game(set_pool, theirs=[
        _w1g3i_card("A Bear", "Creature — Bear"),
        _w1g3i_card("A Rock", "Artifact"),
    ])
    bear, rock = theirs
    bolt = set_pool("APC")["Prophetic Bolt"]

    spec = game.cast_target_spec(0, bolt)
    assert spec["requires_target"]
    offered = {
        (t["kind"], t.get("name", t["seat"])) for t in spec["valid_targets"]
    }
    assert offered == {("player", 0), ("player", 1), ("permanent", "A Bear")}

    refused = game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[rock.permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Prophetic Bolt"]
    assert game.players[1].life == 20 and game.is_on_battlefield(rock)


def test_w1g3_prophetic_bolt_kills_the_creature_then_digs_four(set_pool):
    """"…deals 4 damage to any target. Look at the top four cards of your
    library. Put one of those cards into your hand and the rest on the bottom
    of your library in any order."

    A 2/4 takes the four; the caster looks at four — the spell held on the
    stack while it chooses (CR 608.2) — keeps the one it picks, and the other
    three go under the fifth card. The fifth is not an answer: it was never
    looked at. The creature dies when the spell has finished and not before.

    The rest go down **as they lay, unasked**. That is the look-and-pick
    family's standing convention, shared with Impulse and held by
    ``test_401_4_the_rest_going_to_the_bottom_is_not_asked_about``; the
    recruiters in this set do ask (``offer_library_bottom_order``), and the
    wave reported the difference rather than settling it from one side."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear", "2", "4")],
        interactive={0},
    )
    bear, = theirs
    me = game.players[0]

    assert game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported

    # Mid-resolution: the damage is marked and the Bear is still there, because
    # state-based actions wait for the spell to finish (CR 704.3).
    assert bear.damage_marked == 4 and game.is_on_battlefield(bear), game.log
    assert [item.card.name for item in game.stack] == ["Prophetic Bolt"]
    assert game.waiting_prompt().kind == "look_top_pick"
    assert not game.confirm_look_top_pick(0, 4), "the fifth card was never looked at"

    assert game.confirm_look_top_pick(0, 2)
    game._settle()

    assert not game.is_on_battlefield(bear), game.log
    assert [c.name for c in game.players[1].graveyard] == ["A Bear"]
    assert [c.name for c in me.hand] == ["Card 3"]
    assert [c.name for c in me.library] == ["Card 5", "Card 1", "Card 2", "Card 4"]
    assert game.stack == [] and game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_at_a_player_with_nobody_to_ask(set_pool):
    """The same spell headless: four to the face, the first card looked at is
    kept (the stated default) and the rest go down as they lay."""
    game, _ = _w1g3i_bolt_game(set_pool)
    me = game.players[0]

    assert game.cast_from_hand(0, "Prophetic Bolt", target_player_index=1).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert game.players[1].life == 16 and me.life == 20
    assert [c.name for c in me.hand] == ["Card 1"]
    assert [c.name for c in me.library] == ["Card 5", "Card 2", "Card 3", "Card 4"]
    assert game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_whose_target_left_does_nothing_at_all(set_pool):
    """CR 608.2b: with its only target gone the spell is removed from the
    stack and none of it happens — the look is the rule's *second* sentence,
    not a consolation. The library is exactly as it was."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear")],
    )
    bear, = theirs
    me = game.players[0]

    assert game.queue_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported
    game.remove_from_battlefield(bear)
    _w1g3i_resolve_stack(game)

    assert me.hand == [] and game.pending_choices == []
    assert [c.name for c in me.library] == [f"Card {n}" for n in range(1, 6)]
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]
    assert game.players[1].life == 20

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

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.grammar import compile_line as _w1g7_compile_line
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_instant_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt one of these cards arms is *queued* rather than answered by its own
    default — a headless probe cannot tell "nobody was asked" from "nobody was
    there to ask"."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def _w1g7_instant_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_bolt_at_seat_zero(game, catalog_by_name):
    """Seat 1 puts a Lightning Bolt on the stack aimed at seat 0."""
    game.players[1].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game.stack[-1]


# -- Evasive Action ----------------------------------------------------------


def test_evasive_action_prices_the_toll_at_one_per_basic_land_type(
    set_pool, catalog_by_name
):
    """"Domain — Counter target spell unless its controller pays {1} **for each
    basic land type among lands you control**." Three types is {3}, asked of
    the spell's controller, and a board that cannot cover it loses the spell."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(2)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    assert game.queue_from_hand(0, "Evasive Action", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    owed = game.pending_mana_payment
    assert owed is not None and owed["player_index"] == 1 and owed["amount"] == 3
    assert "Evasive Action: B must pay {3} or Lightning Bolt is countered" in game.log
    # Two Mountains cannot make three mana: saying yes is still a counter.
    assert game.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 20
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert [land.tapped for land in mountains] == [False, False]
    assert any("Lightning Bolt was countered by Evasive Action" in line for line in game.log)


def test_evasive_action_lets_a_paid_spell_resolve(set_pool, catalog_by_name):
    """The other answer: {3} paid from three lands, and the Bolt lands."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(3)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 17
    assert all(land.tapped for land in mountains)
    assert "B paid {3}; Lightning Bolt is not countered" in game.log


@_w1g7_pytest.mark.parametrize(
    "lands, owed",
    [
        # Types, not lands: two Islands are one type, and a Tropical Island is
        # an Island and a Forest (CR 305.6) — two types among three lands.
        (("Island", "Island", "Tropical Island"), 2),
        (("Island", "Swamp", "Mountain", "Forest", "Plains", "Plains"), 5),
        (("Island",), 1),
    ],
)
def test_evasive_action_counts_basic_land_types_not_lands(
    set_pool, catalog_by_name, lands, owed
):
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in lands:
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    # The *spell's* controller's lands are not counted, whatever they are.
    for name in ("Swamp", "Mountain", "Forest", "Plains"):
        _w1g7_instant_put(game, 1, catalog_by_name[name])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.pending_mana_payment["amount"] == owed


def test_evasive_action_with_no_basic_land_type_counters_nothing(
    set_pool, catalog_by_name
):
    """A domain of zero is a price of {0}, which every board covers: no prompt
    is armed and the spell resolves. A nonbasic land with no basic land type
    (Mishra's Factory) contributes nothing."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    _w1g7_instant_put(game, 0, catalog_by_name["Mishra's Factory"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert game.pending_mana_payment is None
    assert p0.life == 17
    assert "B pays {0}; Lightning Bolt is not countered by Evasive Action" in game.log


def test_evasive_action_needs_a_spell_to_name(set_pool):
    """CR 601.2c: with nothing on the stack there is no target, and the cast is
    refused with the card still in hand."""
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Evasive Action"]]

    result = game.cast_from_hand(0, "Evasive Action")

    assert not result.supported
    assert [card.name for card in p0.hand] == ["Evasive Action"]


def test_a_counted_counter_price_refuses_what_the_flow_cannot_charge():
    """The production's refusals. "Beyond the first" is a discount the payment
    never takes, and a coloured rate times a count is arithmetic the prompt
    does not do — each must leave its line unsupported rather than charge the
    wrong number."""
    discounted = _w1g7_compile_line(
        "Counter target spell unless its controller pays {1} for each creature "
        "you control beyond the first."
    )
    assert discounted.parse_error == "no counter price discounts the first counted object"

    coloured = _w1g7_compile_line(
        "Counter target spell unless its controller pays {U} for each basic "
        "land type among lands you control."
    )
    assert coloured.parsed and not coloured.usable
    assert coloured.lowering_error == "only a printed generic cost is paid per counted object"


# -- Jaded Response ----------------------------------------------------------


@_w1g7_pytest.mark.parametrize(
    "mine, theirs, countered",
    [
        # A red creature of the caster's shares red with the Bolt.
        ("Goblin Balloon Brigade", None, True),
        # A blue one shares nothing with it.
        ("Prodigal Sorcerer", None, False),
        # "A creature **you control**": the opponent's red creature is nobody's
        # business here.
        (None, "Goblin Balloon Brigade", False),
        # CR 105.2c: a colourless object shares a colour with nothing.
        ("Ornithopter", None, False),
        (None, None, False),
    ],
)
def test_jaded_response_counters_only_a_spell_sharing_a_color_with_your_creature(
    set_pool, catalog_by_name, mine, theirs, countered
):
    """"Counter target spell **if it shares a color with a creature you
    control**." Asserted on the life total: a counter that fired without its
    condition, or a condition that never held, both read wrong here."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    if mine:
        _w1g7_instant_put(game, 0, catalog_by_name[mine])
    if theirs:
        _w1g7_instant_put(game, 1, catalog_by_name[theirs])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    # "Target spell" is the whole of the targeting restriction (CR 608.2b), so
    # the Bolt is a legal target whether or not the condition will hold.
    offered = game.cast_target_spec(0, set_pool("APC")["Jaded Response"])
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Lightning Bolt"]
    assert game.cast_from_hand(0, "Jaded Response", target_stack_index=0).supported
    _w1g7_resolve_stack(game)

    assert p0.life == (20 if countered else 17)
    assert [card.name for card in p0.graveyard] == ["Jaded Response"]
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert countered == any(
        "Lightning Bolt was countered by Jaded Response" in line for line in game.log
    )


def test_jaded_response_reads_the_colors_as_it_resolves(set_pool, catalog_by_name):
    """The card's ruling: "It does not check colors until it resolves" (CR
    608.2c). The red creature that made the cast worthwhile leaves in response,
    and the Bolt is no longer a spell this counters."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    goblin = _w1g7_instant_put(game, 0, catalog_by_name["Goblin Balloon Brigade"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert game.queue_from_hand(0, "Jaded Response", target_stack_index=0).supported
    game.remove_from_battlefield(goblin)
    _w1g7_resolve_stack(game)

    assert p0.life == 17


def test_jaded_response_sees_a_spell_an_effect_recolored(set_pool, catalog_by_name):
    """The spell's colour is what it is *on the stack* (CR 613.1): a Bolt a
    Vodalian Mystic has made blue shares blue with a Prodigal Sorcerer, and no
    longer shares red with a Goblin."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    _w1g7_instant_put(game, 0, catalog_by_name["Prodigal Sorcerer"])
    bolt = _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    bolt.choices["color_override"] = "U"
    p0.hand = [set_pool("APC")["Jaded Response"]]

    game.cast_from_hand(0, "Jaded Response", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert p0.life == 20


def test_jaded_response_cannot_be_cast_at_an_empty_stack(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert not game.cast_from_hand(0, "Jaded Response").supported
    assert [card.name for card in p0.hand] == ["Jaded Response"]


def test_a_shared_color_condition_is_asked_of_a_spell_and_refuses_elsewhere():
    """The lowering's refusals: the clause about a targeted *permanent* turns on
    whether an object is one of the things it is compared with, which no card
    prints to rule on; and under a trigger "it" names the event's subject."""
    on_a_permanent = _w1g7_compile_line(
        "Destroy target creature if it shares a color with a creature you control."
    )
    assert on_a_permanent.parsed and not on_a_permanent.usable
    assert "asked of a targeted spell" in on_a_permanent.lowering_error

    under_a_trigger = _w1g7_compile_line(
        "Whenever a player casts a spell, counter it if it shares a color with "
        "a creature you control."
    )
    assert not under_a_trigger.usable

    trailing = _w1g7_compile_line(
        "Counter target spell if it shares a color with a creature you control "
        "and draw a card."
    )
    assert not trailing.parsed


# -- Suffocating Blast (driven, and declined) --------------------------------


def test_suffocating_blast_is_refused_until_a_spell_and_a_creature_can_be_named_together(
    set_pool,
):
    """"Counter target spell and Suffocating Blast deals 3 damage to target
    creature." Two targets in two zones (CR 601.2c announces both), and no
    announcement here carries a stack slot beside a battlefield one. It
    compiled on arrival off its *first* target alone, and driven that was: a
    picker offering the spell and nothing else, the cast accepted with no
    creature on any battlefield, a named artifact dealt the damage, and an
    unnamed creature slot answered by whichever creature the resolver met.

    Refused, by the roles walk that proves the two targets are two, until the
    stack slot exists — a card that reports unsupported naming its clause is
    the honest state for one that cannot be announced."""
    blast = set_pool("APC")["Suffocating Blast"]
    program = _w1g7_compile(blast)

    assert not program.supported
    assert program.instructions == ()

    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [blast]
    assert not game.cast_from_hand(0, "Suffocating Blast").supported
    assert [card.name for card in p0.hand] == ["Suffocating Blast"]


def test_one_target_named_once_beside_a_spell_is_still_one_announcement(catalog_by_name):
    """The refusal's edge: it fires on a spell target *beside another target*,
    never on a counterspell with a second sentence. Every shipped counter that
    goes on to do something keeps the program it had."""
    for name in ("Counterspell", "Memory Lapse", "Exclude", "Absorb", "Undermine"):
        if name in catalog_by_name:
            assert _w1g7_compile(catalog_by_name[name]).supported, name
    plain = _w1g7_compile_line("Counter target spell. Draw a card.")
    assert plain.usable


# -- Shimmering Mirage (driven) ----------------------------------------------


def test_shimmering_mirage_changes_a_land_and_draws_a_card(set_pool, catalog_by_name):
    """"Target land becomes the basic land type of your choice until end of
    turn. / Draw a card." A land is the only thing it may name, the type is
    asked as it resolves, and the turn's end gives the Forest back."""
    game, p0, p1 = _w1g7_instant_duel()
    forest = _w1g7_instant_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    mirage = set_pool("APC")["Shimmering Mirage"]
    p0.hand = [mirage]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, mirage)
    assert offered["kind"] == "land"
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Forest"]
    assert not game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]

    assert game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_land_type_choice["player_index"] == 0
    assert forest.basic_land_types == ("forest",)
    assert game.confirm_land_type(0, "island") is True

    assert forest.basic_land_types == ("island",)
    assert [card.name for card in p0.hand] == ["Island"]
    assert [card.name for card in p0.graveyard] == ["Shimmering Mirage"]
    assert game.stack == []

    game.resolve_cleanup_step(0)
    assert forest.basic_land_types == ("forest",)


def test_shimmering_mirage_with_no_land_to_name_cannot_be_cast(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Shimmering Mirage"]]

    assert not game.cast_from_hand(0, "Shimmering Mirage").supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]


# -- Smash (driven) ----------------------------------------------------------


def test_smash_destroys_the_named_artifact_and_draws_a_card(set_pool, catalog_by_name):
    """"Destroy target artifact. / Draw a card." An artifact creature is an
    artifact (CR 205.2); a creature that is not one is refused at announcement
    with the card still in hand."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    thopter = _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    smash = set_pool("APC")["Smash"]
    p0.hand = [smash]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, smash)
    assert sorted(entry["name"] for entry in offered["valid_targets"]) == [
        "Ornithopter", "Sol Ring",
    ]
    assert not game.cast_from_hand(
        0, "Smash", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Smash"]

    assert game.cast_from_hand(
        0, "Smash", target_permanent_ids=[thopter.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Sol Ring", "Grizzly Bears"]
    assert [card.name for card in p1.graveyard] == ["Ornithopter"]
    assert [card.name for card in p0.hand] == ["Island"]
    assert ring in p1.battlefield


def test_smash_whose_artifact_has_left_draws_nothing(set_pool, catalog_by_name):
    """CR 608.2b: with its only target gone the spell does not resolve — the
    second sentence is not a consolation prize."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    p0.hand = [set_pool("APC")["Smash"]]
    p0.library = [catalog_by_name["Island"]]

    assert game.queue_from_hand(
        0, "Smash", target_permanent_ids=[ring.permanent_id]
    ).supported
    game.remove_from_battlefield(ring)
    _w1g7_resolve_stack(game)

    assert p0.hand == []
    assert [card.name for card in p0.library] == ["Island"]
    # …and it did not go looking for the other artifact.
    assert [perm.card.name for perm in p1.battlefield] == ["Ornithopter"]

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
