"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# Cards in a graveyard as targets. Nantuko Tracer's entry trigger targets a
# card in any graveyard and bottoms it into its owner's library (CR 404.1:
# the pile a card is in is its owner's).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_tracer_game(set_pool, *, interactive, mine=("Swamp",),
                      theirs=("Grizzly Bears", "Terror")):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Nantuko Tracer"]],
            graveyard=[lea[name] for name in mine], library=[lea["Forest"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in theirs],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_nantuko_tracer_bottoms_an_opponents_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)          # the creature

    # CR 603.3d: the target is chosen as the trigger is put on the stack, out
    # of every graveyard (the Tracer's own controller's included).
    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert {(t["seat"], t["name"]) for t in asked.data["targets"]} == {
        (0, "Swamp"), (1, "Grizzly Bears"), (1, "Terror"),
    }
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=1)

    # "You may": asked as it resolves (CR 608.2d).
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    victim = game.players[1]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    assert victim.library[-1].name == "Terror" and len(victim.library) == 6
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert len(game.players[0].library) == 5


def test_w1g3_nantuko_tracer_bottoms_its_controllers_own_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    assert game.players[0].graveyard == []
    assert game.players[0].library[-1].name == "Swamp"
    assert len(game.players[1].library) == 5


def test_w1g3_nantuko_tracer_declined_or_whose_card_left_moves_nothing(set_pool):
    declined = _w1g3_tracer_game(set_pool, interactive=True)
    assert declined.queue_from_hand(0, "Nantuko Tracer").supported
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_trigger_target(0, seat=1, graveyard_index=0)
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_optional_pay(0, accept=False)
    _w1g3_resolve(declined)
    assert [c.name for c in declined.players[1].graveyard] == ["Grizzly Bears", "Terror"]
    assert len(declined.players[1].library) == 5

    # CR 608.2b: the named card leaves in response, and the trigger does
    # nothing — it does not bottom the card that slid into its slot.
    left = _w1g3_tracer_game(set_pool, interactive=True)
    assert left.queue_from_hand(0, "Nantuko Tracer").supported
    left.resolve_top_of_stack(pause_for_choices=True)
    assert left.confirm_trigger_target(0, seat=1, graveyard_index=0)
    victim = left.players[1]
    victim.exile.append(victim.graveyard.pop(0))           # the Bears, in response
    _w1g3_resolve(left)
    left.auto_resolve_pending_choices()
    assert [c.name for c in victim.graveyard] == ["Terror"]
    assert len(victim.library) == 5


def test_w1g3_nantuko_tracer_under_an_ai_seat_names_and_bottoms_a_card(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=False, mine=())
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()

    victim = game.players[1]
    assert len(victim.graveyard) == 1 and len(victim.library) == 6
    assert victim.library[-1].name in ("Grizzly Bears", "Terror")

    # With every graveyard empty the trigger has no target and is removed
    # (CR 603.3d); the creature still resolves.
    empty = _w1g3_tracer_game(set_pool, interactive=False, mine=(), theirs=())
    assert empty.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(empty)
    empty.auto_resolve_pending_choices()
    assert any(p.card.name == "Nantuko Tracer" for p in empty.controlled_by(0))
    assert empty.pending_choices == [] and empty.stack == []


# Selfless Exorcist: the exiled card is the source of the damage (CR 120.2),
# and its power is the one it has in exile — printed, or what its
# characteristic-defining ability says (CR 604.3, 113.6a; ruling 2013-04-15).

from engine.models import Permanent as _w1g3_Permanent


def _w1g3_exorcist_game(set_pool, theirs, *, mine=("Grizzly Bears",)):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    pool = {**lea, **set_pool("ICE"), **jud}
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", graveyard=[pool[name] for name in mine],
            library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[pool[name] for name in theirs],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    exorcist = _w1g3_Permanent(card=jud["Selfless Exorcist"])
    game._put_permanent_onto_battlefield(0, exorcist, None)
    exorcist.tapped = False
    exorcist.metadata["summoning_sickness_turn"] = -99
    _w1g3_resolve(game)
    return game, exorcist


def _w1g3_exorcise(game, slot, seat=1):
    result = game.activate_permanent_ability(
        0, "Selfless Exorcist", target_player_index=seat, target_permanent_index=slot,
    )
    assert result.supported, result.details
    _w1g3_resolve(game)


def test_w1g3_selfless_exorcist_offers_creature_cards_in_every_graveyard(set_pool):
    game, _exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    spec = game.activation_target_spec(0, 0)
    assert {(t["seat"], t["name"]) for t in spec["valid_targets"]} == {
        (0, "Grizzly Bears"), (1, "Hill Giant"), (1, "Craw Wurm"),
    }
    # A land card is not a creature card, and the announcement says so.
    assert not game.activate_permanent_ability(
        0, "Selfless Exorcist", target_player_index=1, target_permanent_index=0,
    ).supported


def test_w1g3_selfless_exorcist_takes_the_exiled_cards_power_in_damage(set_pool):
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 1)                                   # Hill Giant, 3/3

    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert game.is_on_battlefield(exorcist) and exorcist.damage_marked == 3
    assert "Hill Giant deals 3 damage to Selfless Exorcist" in game.log


def test_w1g3_selfless_exorcist_dies_to_a_bigger_card(set_pool):
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 2)                                   # Craw Wurm, 6/4

    assert [c.name for c in game.players[1].exile] == ["Craw Wurm"]
    assert not game.is_on_battlefield(exorcist)
    assert "Selfless Exorcist" in [c.name for c in game.players[0].graveyard]


def test_w1g3_selfless_exorcist_reads_a_characteristic_defined_power_in_exile(set_pool):
    """Lhurgoyf's power is the number of creature cards in all graveyards, in
    exile as anywhere (CR 604.3): with Lhurgoyf exiled that is the Bears, the
    Giant and the Wurm — 3, not the 0 a printed "*" reads as."""
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Lhurgoyf", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 0)

    assert [c.name for c in game.players[1].exile] == ["Lhurgoyf"]
    assert exorcist.damage_marked == 3
    assert game.card_power_outside_battlefield(game.players[1].exile[0], 1) == 3


def test_w1g3_selfless_exorcist_whose_card_left_in_response_does_nothing(set_pool):
    """CR 608.2b: its one target gone, the ability does not resolve — nothing
    is exiled and no damage is dealt."""
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    result = game.queue_permanent_ability(
        0, "Selfless Exorcist", target_player_index=1, target_permanent_index=2,
    )
    assert result.supported, result.details
    victim = game.players[1]
    victim.library.append(victim.graveyard.pop(2))           # the Wurm, in response
    _w1g3_resolve(game)

    assert victim.exile == [] and exorcist.damage_marked == 0
    assert game.is_on_battlefield(exorcist)


# The Advocates: "{T}: Return N target cards from an opponent's graveyard to
# their hand. <a second targeted sentence>." One announcement (CR 602.2b
# through 601.2c): a roles walk with one graveyard role per printed card — all
# out of one opponent's pile, each after the one before it — and the second
# target's role.

from engine.keywords import grant_keyword as _w1g3_grant_keyword

_W1G3_THEIRS = ("Swamp", "Hill Giant", "Terror", "Craw Wurm")


def _w1g3_advocate_game(set_pool, name, *, mine=("Grizzly Bears",),
                        theirs=_W1G3_THEIRS, their_board=(), third=None):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    seats = [
        _w1g3_PlayerState(
            name="P0", graveyard=[lea[n] for n in mine], library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[n] for n in theirs], library=[lea["Island"]] * 5,
        ),
    ]
    if third is not None:
        seats.append(_w1g3_PlayerState(
            name="P2", graveyard=[lea[n] for n in third], library=[lea["Island"]] * 5,
        ))
    game = _w1g3_Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    advocate = _w1g3_Permanent(card=jud[name])
    game._put_permanent_onto_battlefield(0, advocate, None)
    advocate.tapped = False
    advocate.metadata["summoning_sickness_turn"] = -99
    board = []
    for other in their_board:
        permanent = _w1g3_Permanent(card=lea[other])
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        board.append(permanent)
    _w1g3_resolve(game)
    return game, advocate, board


def _w1g3_announcements(tree, prefix=()):
    """Every complete announcement the roles walk offers, as tuples of
    ``(kind, seat, index)``."""
    for node in tree:
        here = prefix + ((node["kind"], node["seat"], node["index"]),)
        if node.get("next"):
            yield from _w1g3_announcements(node["next"], here)
        else:
            yield here


def _w1g3_refs(*picks):
    """The wire's ``target_role_refs``: ``(seat, index)`` for a card in a
    graveyard, a ``Permanent`` for a permanent."""
    return [
        {"permanent_id": pick.permanent_id} if isinstance(pick, _w1g3_Permanent)
        else {"graveyard_seat": pick[0], "graveyard_index": pick[1]}
        for pick in picks
    ]


def _w1g3_names(cards):
    return [card.name for card in cards]


def test_w1g3_nullmage_advocate_announces_two_cards_of_one_opponents_pile_and_a_permanent(set_pool):
    game, _advocate, (icy,) = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", their_board=("Icy Manipulator",),
    )
    spec = game.activation_target_spec(0, 0)
    assert spec["kind"] == "roles"
    assert [role["role"] for role in spec["roles"]] == [
        "first card", "second card", "artifact_or_enchantment",
    ]
    offered = set(_w1g3_announcements(spec["valid_targets"]))
    # Every pair of P1's four cards once (CR 115.3; the walk takes them in pile
    # order), never a card of the activator's own, and the Icy as the third.
    icy_slot = ("permanent", 1, game.battlefield_index_of(icy))
    assert offered == {
        (("graveyard", 1, a), ("graveyard", 1, b), icy_slot)
        for a in range(4) for b in range(a + 1, 4)
    }

    result = game.activate_permanent_ability(
        0, "Nullmage Advocate", target_role_refs=_w1g3_refs((1, 1), (1, 3), icy),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    victim = game.players[1]
    assert sorted(_w1g3_names(victim.hand)) == ["Craw Wurm", "Hill Giant"]
    assert _w1g3_names(victim.graveyard) == ["Swamp", "Terror", "Icy Manipulator"]
    assert not game.is_on_battlefield(icy)
    assert _w1g3_names(game.players[0].hand) == []


def test_w1g3_nullmage_advocate_needs_two_cards_in_a_single_opponents_graveyard(set_pool):
    """The 2004-10-04 ruling: "You can't activate this ability unless a single
    opponent has at least two cards in their graveyard to target." One card
    each in two opponents' piles is not two cards in one."""
    lone, advocate, _ = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", theirs=("Swamp",), third=("Island",),
        their_board=("Icy Manipulator",),
    )
    assert lone.activation_target_spec(0, 0)["valid_targets"] == []
    refused = lone.activate_permanent_ability(
        0, "Nullmage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (2, 0), lone.permanent_by_id(
            next(p.permanent_id for p in lone.controlled_by(1))
        )),
    )
    assert not refused.supported
    assert not advocate.tapped and lone.stack == []

    # Two in the third seat's pile: only that pile is offered.
    two, _advocate, _ = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", theirs=("Swamp",), third=("Island", "Plains"),
        their_board=("Icy Manipulator",),
    )
    offered = set(_w1g3_announcements(two.activation_target_spec(0, 0)["valid_targets"]))
    assert {(path[0][1], path[1][1]) for path in offered} == {(2, 2)}


def test_w1g3_forcemage_advocate_returns_one_card_and_counters_a_creature(set_pool):
    game, advocate, _ = _w1g3_advocate_game(set_pool, "Forcemage Advocate")
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == ["card", "creature"]
    # Its own Grizzly Bears card is not an opponent's.
    assert all(path[0][1] == 1 for path in _w1g3_announcements(spec["valid_targets"]))

    result = game.activate_permanent_ability(
        0, "Forcemage Advocate", target_role_refs=_w1g3_refs((1, 2), advocate),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert _w1g3_names(game.players[1].hand) == ["Terror"]
    assert (advocate.effective_power, advocate.effective_toughness) == (3, 2)


def test_w1g3_pulsemage_advocate_returns_three_and_reanimates_your_creature_card(set_pool):
    game, _advocate, _ = _w1g3_advocate_game(set_pool, "Pulsemage Advocate")
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == [
        "first card", "second card", "third card", "creature card",
    ]
    assert len(list(_w1g3_announcements(spec["valid_targets"]))) == 4   # C(4, 3) × 1

    result = game.activate_permanent_ability(
        0, "Pulsemage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (1, 2), (1, 3), (0, 0)),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert sorted(_w1g3_names(game.players[1].hand)) == ["Craw Wurm", "Swamp", "Terror"]
    assert _w1g3_names(game.players[1].graveyard) == ["Hill Giant"]
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Pulsemage Advocate", "Grizzly Bears",
    ]


def test_w1g3_pulsemage_advocate_needs_a_creature_card_of_your_own(set_pool):
    """The 2004-10-04 ruling: "…and you have a creature card in your graveyard
    to target." Three of the opponent's cards are not enough alone."""
    game, advocate, _ = _w1g3_advocate_game(
        set_pool, "Pulsemage Advocate", mine=("Forest",),
    )
    assert game.activation_target_spec(0, 0)["valid_targets"] == []
    assert not game.activate_permanent_ability(
        0, "Pulsemage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (1, 1), (1, 2), (0, 0)),
    ).supported
    assert not advocate.tapped


def _w1g3_spurnmage_in_combat(set_pool):
    """P1 attacks with a Grizzly Bears into P0's Spurnmage Advocate."""
    game, advocate, (bears,) = _w1g3_advocate_game(
        set_pool, "Spurnmage Advocate", their_board=("Grizzly Bears",),
    )
    declare_attack = __import__("tests.helpers", fromlist=["declare_attack"]).declare_attack
    declare_attack(game, 1)
    assert bears.attacking
    return game, advocate, bears


def test_w1g3_spurnmage_advocate_destroys_the_attacker_and_returns_two_cards(set_pool):
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    result = game.activate_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert sorted(_w1g3_names(game.players[1].hand)) == ["Hill Giant", "Swamp"]
    assert not game.is_on_battlefield(bears)


def test_w1g3_spurnmage_advocate_still_destroys_with_both_cards_gone(set_pool):
    """The 2004-10-04 ruling: "The ability is not countered if both cards are
    missing from the graveyard on resolution and the creature target is
    there." CR 608.2b removes it only when *every* target is illegal."""
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    ).supported
    victim = game.players[1]
    victim.exile.extend([victim.graveyard.pop(1), victim.graveyard.pop(0)])
    _w1g3_resolve(game)

    assert not game.is_on_battlefield(bears)
    assert victim.hand == []
    assert _w1g3_names(victim.graveyard) == ["Terror", "Craw Wurm", "Grizzly Bears"]


def test_w1g3_spurnmage_advocate_spares_a_creature_given_shroud_but_returns_the_cards(set_pool):
    """CR 608.2b's last sentence: the illegal target is not affected and the
    rest of the ability still happens."""
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 2), (1, 3), bears),
    ).supported
    _w1g3_grant_keyword(bears, "shroud")
    _w1g3_resolve(game)

    assert game.is_on_battlefield(bears)
    assert sorted(_w1g3_names(game.players[1].hand)) == ["Craw Wurm", "Terror"]


def test_w1g3_spurnmage_advocate_with_every_target_gone_does_nothing(set_pool):
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    ).supported
    victim = game.players[1]
    victim.exile.extend([victim.graveyard.pop(1), victim.graveyard.pop(0)])
    _w1g3_grant_keyword(bears, "shroud")
    _w1g3_resolve(game)

    assert any("every target is illegal" in line for line in game.log), game.log[-4:]
    assert game.is_on_battlefield(bears) and victim.hand == []


def test_w1g3_an_advocate_card_that_left_its_pile_is_not_replaced(set_pool):
    """One card of two gone in response: the other still returns, and the
    card that slid into the departed card's slot is not taken in its place."""
    game, _advocate, (icy,) = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", their_board=("Icy Manipulator",),
    )
    assert game.queue_permanent_ability(
        0, "Nullmage Advocate", target_role_refs=_w1g3_refs((1, 1), (1, 2), icy),
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(1))          # Hill Giant, in response
    _w1g3_resolve(game)

    assert _w1g3_names(victim.hand) == ["Terror"]
    assert _w1g3_names(victim.graveyard) == ["Swamp", "Craw Wurm", "Icy Manipulator"]


# Shieldmage Advocate: "…Prevent all damage that would be dealt to any target
# this turn by a source of your choice." The second role is CR 115.4's union —
# a player or a permanent — and the source is CR 609.7a's choice beside the
# roles (``requires_source``), named on the activation's source fields.

from engine.handlers._common import apply_damage_to_creature as _w1g3_damage_creature


def _w1g3_shieldmage(set_pool):
    return _w1g3_advocate_game(
        set_pool, "Shieldmage Advocate", their_board=("Grizzly Bears", "Hill Giant"),
    )


def test_w1g3_shieldmage_advocate_offers_a_card_and_any_target_and_asks_for_a_source(set_pool):
    game, advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == ["card", "any target"]
    assert spec["requires_source"]
    assert {(t["seat"], t["name"]) for t in spec["source_targets"]} >= {
        (1, "Grizzly Bears"), (1, "Hill Giant"),
    }
    second = {
        (node["kind"], node["seat"], node.get("index"))
        for node in spec["valid_targets"][0]["next"]
    }
    # Both players and every creature: "any target" (CR 115.4).
    assert second == {
        ("player", 0, None), ("player", 1, None),
        ("permanent", 0, game.battlefield_index_of(advocate)),
        ("permanent", 1, game.battlefield_index_of(bears)),
        ("permanent", 1, game.battlefield_index_of(giant)),
    }


def test_w1g3_shieldmage_advocate_shields_its_controller_from_the_chosen_source(set_pool):
    game, _advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    result = game.activate_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=[{"graveyard_seat": 1, "graveyard_index": 1}, {"seat": 0}],
        source_seat=1, source_permanent_index=game.battlefield_index_of(bears),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert _w1g3_names(game.players[1].hand) == ["Hill Giant"]
    me = game.players[0]
    game._deal_damage_to_player(me, 2, source=bears)
    game._deal_damage_to_player(me, 2, source=bears)        # all of it, all turn
    assert me.life == 20
    game._deal_damage_to_player(me, 3, source=giant)        # another source
    assert me.life == 17
    assert game.players[1].life == 20


def test_w1g3_shieldmage_advocate_shields_a_creature_and_only_from_its_source(set_pool):
    game, advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    result = game.activate_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=_w1g3_refs((1, 0), advocate),
        source_seat=1, source_permanent_index=game.battlefield_index_of(giant),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    _w1g3_damage_creature(game, advocate, 3, giant)
    assert advocate.damage_marked == 0
    _w1g3_damage_creature(game, advocate, 2, bears)
    assert advocate.damage_marked == 2
    # The player beside it is not shielded: the shield is around what was named.
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 17


def test_w1g3_shieldmage_advocate_still_shields_with_its_card_gone(set_pool):
    """CR 608.2b: one of two targets illegal, the ability still resolves —
    the card is not returned and the shield is still armed."""
    game, _advocate, (bears, _giant) = _w1g3_shieldmage(set_pool)
    assert game.queue_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=[{"graveyard_seat": 1, "graveyard_index": 2}, {"seat": 0}],
        source_seat=1, source_permanent_index=game.battlefield_index_of(bears),
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(2))           # Terror, in response
    _w1g3_resolve(game)

    assert victim.hand == []
    game._deal_damage_to_player(game.players[0], 2, source=bears)
    assert game.players[0].life == 20

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

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
