"""CR 108.3 / CR 400.3 — a spell's card leaves the stack for its **owner's**
zones, whoever cast it.

"If an object would go to any library, graveyard, or hand other than its
owner's, it goes to its owner's corresponding zone" (CR 400.3), and the owner
of a card is "the player who started the game with it in their deck"
(CR 108.3). Casting a card does not change who owns it: the caster *controls*
the spell (CR 108.4) and nothing more.

The engine read the stack object's ``caster_index`` as the owner at every site
a spell's card leaves the stack. True for every card cast out of its caster's
own hand, and false for exactly the cards that are interesting — a permission
that opens *another* player's zone. Grinning Totem exiles a card out of an
opponent's library into that opponent's exile and lets its controller play it;
the stolen spell then resolved into the thief's graveyard, was countered into
it, fizzled into it, was bounced into the thief's hand. A stolen creature died
into the thief's graveyard, and a stolen commander was never offered its
owner's command zone (CR 903.9a looks in the owner's graveyard).

``StackItem.owner_index`` is the fix — stamped by the cast path from the seat
whose pile the card left, read at every leave-the-stack site. This file is the
census of those sites: one test per way a card leaves the stack, each driving
a cross-seat spell through the real engine. ``ROUTES`` below is the list, and
the floor at the bottom holds it to the number of sites the fix touched, so a
route quietly dropped from the census reads as a failure rather than as a
smaller green run.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.commander import COMMANDER
from engine.exiled_records import EXILED_SPELL_CONTROLLER_KEY, live_records
from engine.models import Permanent

from tests.helpers import _nosick, resolve_stack


#: Every leave-the-stack route this file drives, by the test that drives it.
#: Kept as data so the floor test can hold the census to its size.
ROUTES = (
    "resolves",                    # CR 608.2n
    "countered",                   # CR 701.6a
    "countered_by_the_rules",      # CR 608.2b
    "countered_onto_a_library",    # CR 614.1 replacing 701.6a (Memory Lapse)
    "countered_for_an_unpaid_cost",  # CR 701.6a, the pay-or-countered prompt
    "returned_to_hand",            # Unsubstantiate
    "exiled_by_an_effect",         # Ertai's Meddling
    "exiled_by_end_the_turn",      # CR 724.1b
    "aura_with_no_target",         # CR 303.4g/608.3b's Aura that cannot attach
    "permanent_spell_resolves",    # CR 110.2: owner's card, caster's control
    "land_played",                 # CR 305.1: no stack, same owner question
    "commander_countered",         # CR 903.9a reads the owner's graveyard
    "player_leaves",               # CR 800.4a
)


def _w2g5_cross_seat(set_pool, stolen, *, p0_battlefield=(), p1_battlefield=(),
                     p1_hand=(), commander=False):
    """Seat 0 has played Grinning Totem against seat 1 and found *stolen*.

    *stolen* is a ``(set code, card name)`` pair put on top of seat 1's
    library. The Totem's search exiles it into **seat 1's** exile (CR 400.3)
    and gives seat 0 permission to play it — the one shipped shape in which the
    caster of a spell is not its owner. Both seats are interactive afterwards,
    so a spell cast in response goes on the stack above the stolen one rather
    than resolving on the spot.
    """
    mir = set_pool("MIR")
    card = set_pool(stolen[0])[stolen[1]]
    totem = Permanent(card=mir["Grinning Totem"])
    filler = [mir["Island"]] * 8
    players = [
        PlayerState(
            name="P0", battlefield=[totem, *p0_battlefield], library=list(filler)
        ),
        PlayerState(
            name="P1", battlefield=list(p1_battlefield), hand=list(p1_hand),
            library=[card, *filler],
        ),
    ]
    game = Game(players=players, commander_variant=COMMANDER if commander else None)
    if commander:
        game.designate_commander(1, card)
    game.enforce_mana_costs = False
    # Seat 1 answers its own commander's CR 903.9a offer below; otherwise only
    # the searcher has anything to decide.
    game.interactive_seats = {0, 1} if commander else {0}
    for permanent in game.all_permanents():
        _nosick(permanent)
    assert game.activate_permanent_ability(
        0, "Grinning Totem", target_player_index=1
    ).supported
    game.resolve_stack()
    assert game.confirm_search_library(0, 0, "library")
    if commander:
        # A commander exiled is offered home at once (CR 903.9a); its owner
        # leaves it in exile, which is what makes it the opponent's to play.
        game.check_state_based_actions()
        assert game.confirm_commander_zone_change(1, to_command_zone=False)
    assert [c.name for c in game.players[1].exile] == [card.name]
    game.interactive_seats = {0, 1}
    return game, card


def _w2g5_names(pile) -> list[str]:
    return [c.name for c in pile]


def _w2g5_stack_slot(game, item) -> int:
    """*item*'s bottom-first stack index, found by identity (a ``StackItem``
    compares by value)."""
    return next(i for i, entry in enumerate(game.stack) if entry is item)


def _w2g5_cast_stolen_shock(game, *, at_seat=1, at_permanent=None):
    kwargs = {"target_player_index": at_seat}
    if at_permanent is not None:
        kwargs["target_permanent_index"] = at_permanent
    result = game.queue_from_hand(0, "Shock", from_zone="exile", **kwargs)
    assert result.supported, result.details
    (item,) = [i for i in game.stack if i.card.name == "Shock"]
    return item  # _w2g5_cast_stolen_shock


@pytest.mark.cr("108.3", "400.3", "608.2n")
def test_a_stolen_spell_resolves_into_its_owners_graveyard(set_pool):
    game, _ = _w2g5_cross_seat(set_pool, ("STH", "Shock"))
    item = _w2g5_cast_stolen_shock(game)
    assert (item.caster_index, item.owner_index) == (0, 1)

    resolve_stack(game)

    assert game.players[1].life == 18
    assert _w2g5_names(game.players[1].graveyard) == ["Shock"]
    # Seat 0's graveyard holds only the Totem it sacrificed as a cost.
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("400.3", "701.6a")
def test_a_stolen_spell_is_countered_into_its_owners_graveyard(set_pool):
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("LEA")["Counterspell"]]
    )
    _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(1, "Counterspell").supported

    resolve_stack(game)

    assert game.players[1].life == 20, "countered, so no damage"
    assert sorted(_w2g5_names(game.players[1].graveyard)) == ["Counterspell", "Shock"]
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("400.3", "608.2b")
def test_a_stolen_spell_with_no_legal_target_goes_to_its_owners_graveyard(set_pool):
    """Every target illegal, so the spell "doesn't resolve … and, if it's a
    spell, [is] put into its owner's graveyard" — the owner, not the caster."""
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_battlefield=[bears], p1_hand=[lea["Unsummon"]],
    )
    _w2g5_cast_stolen_shock(game, at_seat=1, at_permanent=0)
    assert game.queue_from_hand(
        1, "Unsummon", target_player_index=1, target_permanent_index=0
    ).supported

    resolve_stack(game)

    assert _w2g5_names(game.players[1].hand) == ["Grizzly Bears"]
    assert sorted(_w2g5_names(game.players[1].graveyard)) == ["Shock", "Unsummon"]
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("400.3", "614.1")
def test_memory_lapse_puts_a_stolen_spell_on_its_owners_library(set_pool):
    """"…put it on top of **its owner's** library instead of into that
    player's graveyard." The replacement changes which zone; CR 400.3 still
    decides whose."""
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("MIR")["Memory Lapse"]]
    )
    _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(1, "Memory Lapse").supported

    resolve_stack(game)

    assert game.players[1].library[0].name == "Shock"
    assert "Shock" not in _w2g5_names(game.players[0].library)
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("400.3", "701.6a")
def test_an_unpaid_counter_puts_a_stolen_spell_in_its_owners_graveyard(set_pool):
    """Force Spike's "unless its controller pays {1}": the *controller* is
    asked to pay — the caster, seat 0 — and the countered card goes to its
    *owner's* graveyard. Two seats, one prompt, and the bin used to read the
    payer's."""
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("LEG")["Force Spike"]]
    )
    _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(1, "Force Spike").supported
    game.interactive_seats = {1}  # seat 0 answers the payment by default

    resolve_stack(game)

    assert game.players[1].life == 20
    assert sorted(_w2g5_names(game.players[1].graveyard)) == ["Force Spike", "Shock"]
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("400.3", "108.3")
def test_unsubstantiate_returns_a_stolen_spell_to_its_owners_hand(set_pool):
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("M21")["Unsubstantiate"]]
    )
    item = _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(
        1, "Unsubstantiate", target_stack_index=_w2g5_stack_slot(game, item)
    ).supported

    resolve_stack(game)

    assert _w2g5_names(game.players[1].hand) == ["Shock"]
    assert _w2g5_names(game.players[0].hand) == []
    assert game.players[1].life == 20


@pytest.mark.cr("400.3", "406.1")
def test_ertais_meddling_exiles_a_stolen_spell_into_its_owners_exile(set_pool):
    """"**Target spell's controller** exiles it with X delay counters on it. At
    the beginning of each of **that player's** upkeeps …" — two seats once the
    caster is not the owner. The card is in its owner's exile (and the record
    that keeps its counters is live there), while the delay counts down on the
    upkeeps of the player who *controlled* the spell."""
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("TMP")["Ertai's Meddling"]]
    )
    item = _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(
        1, "Ertai's Meddling", x_value=1, target_stack_index=_w2g5_stack_slot(game, item)
    ).supported

    resolve_stack(game)

    assert _w2g5_names(game.players[1].exile) == ["Shock"]
    assert _w2g5_names(game.players[0].exile) == []
    (record,) = [r for r in live_records(game) if r.card.name == "Shock"]
    assert record.owner_index == 1
    (delayed,) = [
        d for d in game.delayed_triggers if d.source_name == "Ertai's Meddling"
    ]
    assert delayed.captured.get(EXILED_SPELL_CONTROLLER_KEY) == 0

    # Seat 0's upkeep — the spell's controller's — takes the last counter off,
    # seat 0 puts the card onto the stack as a copy of the original (still
    # aimed at seat 1), and the card it is resolves into its owner's graveyard.
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert game.players[1].life == 18
    assert "Shock" in _w2g5_names(game.players[1].graveyard)
    assert "Shock" not in _w2g5_names(game.players[0].graveyard)


@pytest.mark.cr("724.1b", "400.3")
def test_end_the_turn_exiles_a_stolen_spell_into_its_owners_exile(set_pool):
    game, _ = _w2g5_cross_seat(
        set_pool, ("STH", "Shock"), p1_hand=[set_pool("M21")["Discontinuity"]]
    )
    _w2g5_cast_stolen_shock(game)
    assert game.queue_from_hand(1, "Discontinuity").supported

    resolve_stack(game)

    assert sorted(_w2g5_names(game.players[1].exile)) == ["Discontinuity", "Shock"]
    assert _w2g5_names(game.players[0].exile) == []
    assert game.players[1].life == 20


@pytest.mark.cr("724.1b", "113.7a")
def test_end_the_turn_exiles_no_card_for_an_ability_on_the_stack(set_pool):
    """"Exile every object on the stack" — an **ability** is an object with no
    card (CR 113.7a), so it simply ceases to exist. The process binned
    ``item.card`` for every object, which for an ability is its *source's*
    card: Prodigal Sorcerer's ping put a second Prodigal Sorcerer into exile
    while the first was still on the battlefield."""
    lea = set_pool("LEA")
    sorcerer = _nosick(Permanent(card=lea["Prodigal Sorcerer"]))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[sorcerer]),
        PlayerState(name="P1", hand=[set_pool("M21")["Discontinuity"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1
    ).supported
    assert game.queue_from_hand(1, "Discontinuity").supported

    resolve_stack(game)

    assert game.stack == []
    assert game.players[0].exile == [], "no phantom Sorcerer"
    assert game.is_on_battlefield(sorcerer)
    assert game.players[1].life == 20, "the ping was exiled, not resolved"


@pytest.mark.cr("303.4g", "400.3")
def test_a_stolen_aura_that_cannot_attach_goes_to_its_owners_graveyard(set_pool):
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])
    game, _ = _w2g5_cross_seat(
        set_pool, ("LEA", "Holy Strength"), p0_battlefield=[bears],
        p1_hand=[lea["Unsummon"]],
    )
    assert game.queue_from_hand(
        0, "Holy Strength", from_zone="exile",
        # The Totem was sacrificed, so the Bears are seat 0's only permanent.
        target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(
        1, "Unsummon", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported

    resolve_stack(game)

    assert _w2g5_names(game.players[0].hand) == ["Grizzly Bears"]
    assert "Holy Strength" in _w2g5_names(game.players[1].graveyard)
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("108.3", "110.2", "400.3")
def test_a_stolen_creature_is_its_owners_card_and_dies_into_their_graveyard(set_pool):
    """CR 110.2: a permanent's controller is the player under whose control it
    entered; its owner is still the player who started the game with the card.
    The two come apart here, and the graveyard is the owner's."""
    game, _ = _w2g5_cross_seat(
        set_pool, ("MIR", "Bay Falcon"), p1_hand=[set_pool("LEA")["Terror"]]
    )
    assert game.queue_from_hand(0, "Bay Falcon", from_zone="exile").supported
    resolve_stack(game)
    (falcon,) = [p for p in game.controlled_by(0) if p.card.name == "Bay Falcon"]
    assert (game.controller_index_of(falcon), game.owner_index_of(falcon)) == (0, 1)

    assert game.queue_from_hand(
        1, "Terror", target_player_index=0,
        target_permanent_ids=[falcon.permanent_id],
    ).supported
    resolve_stack(game)

    assert not game.is_on_battlefield(falcon)
    assert sorted(_w2g5_names(game.players[1].graveyard)) == ["Bay Falcon", "Terror"]
    assert _w2g5_names(game.players[0].graveyard) == ["Grinning Totem"]


@pytest.mark.cr("108.3", "305.1", "400.3")
def test_a_stolen_land_is_its_owners_card(set_pool):
    """A land is *played* (CR 305.1) — no stack — and the same question is asked
    of the permanent it becomes: seat 0 controls it, seat 1 owns it."""
    game, _ = _w2g5_cross_seat(
        set_pool, ("MIR", "Forest"), p1_hand=[set_pool("LEA")["Ice Storm"]]
    )
    assert game.queue_from_hand(0, "Forest", from_zone="exile").supported
    (forest,) = [p for p in game.controlled_by(0) if p.card.name == "Forest"]
    assert game.owner_index_of(forest) == 1

    assert game.queue_from_hand(
        1, "Ice Storm", target_player_index=0,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    resolve_stack(game)

    assert not game.is_on_battlefield(forest)
    assert "Forest" in _w2g5_names(game.players[1].graveyard)
    assert "Forest" not in _w2g5_names(game.players[0].graveyard)


@pytest.mark.cr("903.9a", "400.3")
def test_a_commander_cast_by_another_player_still_reaches_its_owners_command_zone(
    set_pool,
):
    """CR 903.9a asks about a commander in *a* graveyard, and its owner is the
    one offered the command zone — but this engine reads the owner's own
    graveyard to find it, which is where CR 400.3 puts it. A commander
    countered into its *caster's* graveyard was in a pile nothing looks in, and
    was never offered home."""
    game, gadrak = _w2g5_cross_seat(
        set_pool, ("M21", "Gadrak, the Crown-Scourge"),
        p1_hand=[set_pool("LEA")["Counterspell"]], commander=True,
    )
    assert game.queue_from_hand(0, gadrak.name, from_zone="exile").supported
    assert game.queue_from_hand(1, "Counterspell").supported
    game.interactive_seats = {0}  # seat 1 takes CR 903.9a's default: home

    resolve_stack(game)
    game.check_state_based_actions()

    assert [c is gadrak for c in game.players[1].command_zone] == [True]
    assert gadrak not in game.players[0].graveyard
    assert gadrak not in game.players[1].graveyard


@pytest.mark.cr("903.9a", "108.3")
def test_a_commander_another_player_cast_dies_and_goes_home(set_pool):
    game, gadrak = _w2g5_cross_seat(
        set_pool, ("M21", "Gadrak, the Crown-Scourge"),
        p1_hand=[set_pool("LEA")["Terror"]], commander=True,
    )
    assert game.queue_from_hand(0, gadrak.name, from_zone="exile").supported
    resolve_stack(game)
    (permanent,) = [p for p in game.controlled_by(0) if p.card is gadrak]
    assert game.is_commander_permanent(permanent), "still seat 1's commander"
    game.interactive_seats = {0}

    assert game.queue_from_hand(
        1, "Terror", target_player_index=0,
        target_permanent_ids=[permanent.permanent_id],
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()

    assert [c is gadrak for c in game.players[1].command_zone] == [True]


@pytest.mark.cr("800.4a")
def test_a_player_leaving_exiles_the_stolen_spell_they_controlled(set_pool):
    """"…if there are any objects still controlled by that player, those
    objects are exiled." The spell seat 0 cast leaves with seat 0, into its
    *owner's* exile — it used to cease to exist, deleting seat 1's card from a
    game seat 1 is still in."""
    game, _ = _w2g5_cross_seat(set_pool, ("STH", "Shock"))
    _w2g5_cast_stolen_shock(game)

    game._eliminate_player(0)

    assert game.stack == []
    assert _w2g5_names(game.players[1].exile) == ["Shock"]


@pytest.mark.cr("400.3")
def test_the_census_covers_every_leave_the_stack_route():
    """The floor. Thirteen routes were changed by the fix and thirteen are
    driven above; a route deleted from the census must be deleted here too,
    which is a decision rather than a quiet shrink."""
    assert len(ROUTES) >= 13
    assert len(set(ROUTES)) == len(ROUTES)
