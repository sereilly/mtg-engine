"""Casting and playing cards from somewhere other than the hand (CR 601.3),
through the permission seam in ``engine/cast_permissions.py``.

The rules split cleanly: the *permission* is CR 601.3 (a player can begin to
cast a spell only if a rule or effect allows it), a land played from another
zone still consumes the land drop (CR 305.1–305.2), a cast "without paying its
mana cost" locks {X} at 0 (CR 107.3b), a grant's duration follows CR 611.2a
(stated duration, or end of game bounded by the card staying the object it was,
CR 400.7), and the printed "if that spell would be put into your graveyard,
exile it instead" rider is a replacement (CR 614.1a) that follows the spell
whether it resolves or is countered.
"""

import pytest

from engine import Game, PlayerState
from engine.cast_permissions import (expire_at_upkeep, grant_permission,
                                    permission_for)
from engine.exiled_records import live_records, record_exiled_card
from engine.linked_exile import face_down_exiled_cards
from engine.models import CardDefinition


def _mk_card(
    name: str,
    type_line: str = "Instant",
    oracle_text: str = "Draw a card.",
    mana_cost: str = "{R}",
    colors: tuple[str, ...] = ("R",),
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={},
    )


def _game(p1_kwargs: dict | None = None, p2_kwargs: dict | None = None) -> Game:
    return Game(players=[
        PlayerState(name="P1", **(p1_kwargs or {})),
        PlayerState(name="P2", **(p2_kwargs or {})),
    ])


@pytest.mark.cr("601.3")
def test_601_3_casting_from_the_graveyard_needs_an_effect():
    """Without a permission effect, a card in the graveyard cannot be cast —
    and the refusal names the rule rather than crashing or quietly casting."""
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert not result.supported
    assert "601.3" in result.details
    assert spell in game.players[0].graveyard


@pytest.mark.cr("601.3")
def test_601_3_a_permission_effect_opens_the_zone_and_is_consumed():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert result.supported, result.details
    # The spell resolved: it drew a card and went to the graveyard afterwards
    # (CR 608.2n), and the one-card grant is spent.
    assert len(game.players[0].hand) == 1
    assert not game.cast_permissions
    assert game.cast_from_hand(0, "Test Draw", from_zone="graveyard").supported is False


@pytest.mark.cr("601.3")
def test_601_3_an_opponents_grant_is_not_yours():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell]})
    grant_permission(
        game, player_index=1, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    assert permission_for(game, 0, spell, "graveyard") is None


@pytest.mark.cr("400.7")
def test_400_7_the_permission_dies_when_the_card_leaves_the_zone():
    """A grant names its cards by identity; a card that left the zone is a new
    object, so the permission does not follow it and does not resurrect a
    look-alike that arrives later."""
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    assert permission_for(game, 0, spell, "graveyard") is not None
    game.players[0].graveyard.remove(spell)
    assert permission_for(game, 0, spell, "graveyard") is None


@pytest.mark.cr("305.1", "305.2a", "305.2b")
def test_305_2_a_land_played_from_exile_consumes_the_land_drop():
    land = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    second = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    game = _game({"exile": [land], "hand": [second]})
    game.enforce_mana_costs = True
    grant_permission(
        game, player_index=0, zone="exile", mode="play",
        cards=[land], duration="end_of_turn", source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Peak", from_zone="exile")
    assert result.supported, result.details
    assert any(perm.card is land for perm in game.players[0].battlefield)
    # CR 305.2b: the drop is spent — the hand copy is refused this turn.
    refused = game.cast_from_hand(0, "Test Peak")
    assert not refused.supported


@pytest.mark.cr("305.1")
def test_305_1_a_cast_grant_does_not_play_a_land():
    """A land is played, never cast, so a "you may cast" permission does not
    reach it — the grant's mode has to say "play"."""
    land = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    game = _game({"exile": [land]})
    grant_permission(
        game, player_index=0, zone="exile", mode="cast",
        cards=[land], duration="end_of_turn", source_name="Test Grant",
    )
    assert permission_for(game, 0, land, "exile", as_land=True) is None
    result = game.cast_from_hand(0, "Test Peak", from_zone="exile")
    assert not result.supported


@pytest.mark.cr("107.3b", "118.9")
def test_107_3b_a_free_cast_locks_x_at_zero():
    blaze = _mk_card(
        "Test Blaze", oracle_text="Test Blaze deals X damage to any target.",
        mana_cost="{X}{R}", type_line="Sorcery",
    )
    game = _game({"hand": [blaze]})
    game.enforce_mana_costs = True
    grant_permission(
        game, player_index=0, zone="hand", mode="cast", cards=None,
        free=True, duration="end_of_turn", source_name="Test Waiver",
    )
    # An empty mana pool would refuse this cast outright; the waiver casts it
    # and the only legal choice for X is 0.
    result = game.queue_from_hand(0, "Test Blaze", use_free_permission=True)
    assert result.supported, result.details
    assert game.stack and game.stack[-1].x_value == 0
    assert game.stack[-1].cast_from_zone == "hand"


@pytest.mark.cr("611.2a", "514.2")
def test_611_2a_a_stated_duration_ends_at_cleanup_an_unstated_one_does_not():
    spell = _mk_card("Test Draw")
    other = _mk_card("Test Draw Two")
    game = _game({"graveyard": [spell, other]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration="end_of_turn", source_name="Turn Grant",
    )
    lasting = grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[other], duration=None, source_name="Lasting Grant",
    )
    game.resolve_cleanup_step(0)
    assert permission_for(game, 0, spell, "graveyard") is None
    assert permission_for(game, 0, other, "graveyard") is lasting


@pytest.mark.cr("614.1a", "608.2n")
def test_614_1a_the_exile_instead_rider_follows_the_resolving_spell():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, exile_instead=True,
        source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert result.supported, result.details
    assert spell in game.players[0].exile
    assert spell not in game.players[0].graveyard


@pytest.mark.cr("614.1a")
def test_614_1a_the_rider_also_follows_a_countered_spell():
    """"Would be put into your graveyard" is not "resolves": a countered spell
    is bound the same way, so the rider has to ride the stack object rather
    than the resolution path."""
    spell = _mk_card("Test Draw")
    counter = _mk_card(
        "Test Veto", oracle_text="Counter target spell.",
        mana_cost="{U}{U}", colors=("U",),
    )
    game = _game({"graveyard": [spell]}, {"hand": [counter]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, exile_instead=True,
        source_name="Test Grant",
    )
    queued = game.queue_from_hand(0, "Test Draw", from_zone="graveyard")
    assert queued.supported, queued.details
    countered = game.cast_from_hand(1, "Test Veto")
    assert countered.supported, countered.details
    assert spell in game.players[0].exile
    assert spell not in game.players[0].graveyard


@pytest.mark.cr("800.4m", "611.2a")
def test_800_4m_an_until_your_next_turn_grant_ends_as_that_turn_begins():
    """"Until your next turn, you may play those cards." (Three Wishes.)

    CR 800.4m states the moment a duration of this shape ends: it lasts until
    that player's turn *would have begun*. So an opponent's whole turn is
    inside the window and the granting seat's own turn boundary is what closes
    it — never the boundary of whoever is next to play.
    """
    spell = _mk_card("Test Draw")
    game = _game({"exile": [spell]})
    grant_permission(
        game, player_index=0, zone="exile", mode="play",
        cards=[spell], duration="your_next_turn", source_name="Test Grant",
    )

    game.begin_turn_bookkeeping(1)
    assert permission_for(game, 0, spell, "exile") is not None

    game.begin_turn_bookkeeping(0)
    assert permission_for(game, 0, spell, "exile") is None


@pytest.mark.cr("502.4", "800.4m")
def test_800_4m_the_turn_grant_and_the_upkeep_grant_are_different_moments():
    """The two durations are one step apart and are not the same key.

    No *player* can tell them apart — CR 502.4 gives nobody priority in the
    untap step between them — but the engine can, and a permission read as the
    later duration would still be offered by ``playable_from_zones`` at a
    moment the card had already ended it.
    """
    early = _mk_card("Test Early")
    late = _mk_card("Test Late")
    game = _game({"exile": [early, late]})
    grant_permission(
        game, player_index=0, zone="exile", mode="play",
        cards=[early], duration="your_next_turn", source_name="Turn Grant",
    )
    grant_permission(
        game, player_index=0, zone="exile", mode="play",
        cards=[late], duration="your_next_upkeep", source_name="Upkeep Grant",
    )

    game.begin_turn_bookkeeping(0)
    assert permission_for(game, 0, early, "exile") is None
    assert permission_for(game, 0, late, "exile") is not None

    expire_at_upkeep(game, 0)
    assert permission_for(game, 0, late, "exile") is None


@pytest.mark.cr("406.3", "601.3")
def test_406_3_a_spell_can_exile_face_down_with_no_permanent_to_hold_the_record():
    """CR 406.3: a card exiled face down is hidden from every player, its owner
    included, and an effect is what opens it to one of them.

    The record of *which* exiled card is hidden cannot live on the card — two
    copies of one card in a deck are the same object — so it lives on the
    exiling permanent. A **spell** never becomes one, which is what
    ``engine/exiled_records.py`` answers for; both registers are read by one
    function, because "is this face down to me" has one answer.
    """
    hidden = _mk_card("Test Hidden")
    game = _game({"exile": [hidden]})
    record_exiled_card(game, hidden, 0, face_down=True)

    assert [c.name for c in face_down_exiled_cards(game, 0)] == ["Test Hidden"]
    assert [c.name for c in face_down_exiled_cards(game, 0, 1)] == ["Test Hidden"]

    # "You may look at those cards for as long as they remain exiled."
    list(live_records(game))[0].looker_index = 0
    assert face_down_exiled_cards(game, 0, 0) == []
    assert [c.name for c in face_down_exiled_cards(game, 0, 1)] == ["Test Hidden"]


@pytest.mark.cr("406.3", "400.7")
def test_400_7_a_face_down_record_stops_speaking_once_its_card_leaves_exile():
    """The register derives liveness from the zone rather than maintaining it,
    so a card pulled out of exile by anything at all retires its record —
    otherwise the next effect to exile the same card would find that record
    alive and go on hiding it from the table.
    """
    hidden = _mk_card("Test Hidden")
    game = _game({"exile": [hidden]})
    record_exiled_card(game, hidden, 0, face_down=True)

    game.players[0].exile.remove(hidden)
    assert list(live_records(game)) == []
    assert face_down_exiled_cards(game, 0) == []


# ---------------------------------------------------------------------------
# A blanket grant over one position in an ordered zone, and a timing grant (W2G1)
# ---------------------------------------------------------------------------

from engine.card_loader import load_cards as _w2g1_load_cards
from engine.card_loader import load_catalog as _w2g1_load_catalog
from engine.card_loader import manifest_set_path as _w2g1_set_path
from engine.cast_permissions import playable_from_zones as _w2g1_playable
from engine.cast_timing import casts_at_instant_speed as _w2g1_instant_speed
from engine.cast_timing import expire_end_of_turn as _w2g1_expire_flash
from engine.models import Permanent as _W2G1Permanent

_W2G1_WTH = {
    c.name: c
    for c in _w2g1_load_cards(_w2g1_set_path("WTH", include_measured=True))
}
_W2G1_CATALOG = {c.name: c for c in _w2g1_load_catalog()}


def _w2g1_main_phase_duel():
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.turn = 3
    game.current_turn_phase = "precombat_main"
    return game, p1, p2


@pytest.mark.cr("601.3", "400.5")
def test_601_3_a_blanket_grant_opens_one_position_in_an_ordered_zone():
    """"A player can begin to cast a spell only if a rule or effect allows
    that player to cast it."

    Bösium Strip: "Until end of turn, you may cast instant and sorcery spells
    from the top of your graveyard." No card is named, so the grant carries a
    class of spells plus a *position* — and CR 400.5 is what makes the position
    meaningful, since a graveyard's order can't be changed except when an
    effect allows it.

    Dropping the position is not a smaller permission but a strictly larger
    one: the whole graveyard becomes castable, which is a card nobody printed.
    """
    game, p1, _p2 = _w2g1_main_phase_duel()
    p1.battlefield.append(_W2G1Permanent(card=_W2G1_WTH["Bösium Strip"]))
    p1.graveyard = [
        _W2G1_CATALOG["Giant Growth"],
        _W2G1_CATALOG["Grizzly Bears"],
        _W2G1_CATALOG["Lightning Bolt"],
    ]

    assert _w2g1_playable(game, 0) == []
    game.activate_permanent_ability(0, "Bösium Strip")
    resolve_stack(game)

    assert [e["name"] for e in _w2g1_playable(game, 0)] == ["Lightning Bolt"]
    buried = {card.name: card for card in p1.graveyard}
    assert permission_for(game, 0, buried["Giant Growth"], "graveyard") is None
    assert permission_for(game, 0, buried["Grizzly Bears"], "graveyard") is None


@pytest.mark.cr("614.1a", "404.1")
def test_614_1a_a_spell_cast_from_the_top_of_a_graveyard_is_exiled_instead():
    """"If a spell cast this way would be put into a graveyard, exile it
    instead."

    CR 404.1 is what makes the rider load-bearing: a finished instant is put on
    **top** of its owner's graveyard, which for this card is the very position
    it was just cast from — so without the replacement the spell is castable
    again the same turn, for ever. The wording differs from the printing the
    engine already read ("that spell" / "your graveyard"), and one field takes
    both.
    """
    game, p1, p2 = _w2g1_main_phase_duel()
    p1.battlefield.append(_W2G1Permanent(card=_W2G1_WTH["Bösium Strip"]))
    p1.graveyard = [
        _W2G1_CATALOG["Grizzly Bears"], _W2G1_CATALOG["Lightning Bolt"],
    ]

    game.activate_permanent_ability(0, "Bösium Strip")
    resolve_stack(game)
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1, from_zone="graveyard"
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert p2.life == 17
    assert [c.name for c in p1.exile] == ["Lightning Bolt"]
    assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("702.8a", "611.1", "514.2")
def test_702_8a_a_granted_flash_widens_when_rather_than_where():
    """"Flash means 'You may play this card any time you could cast an
    instant.'"

    Winding Canyons grants it to a *class of spells* for a turn (CR 611.1's
    continuous effect), which is a different axis from every other permission
    in this file: those say which zone a spell may be cast **from**, and this
    says **when**. Folded together, a timing grant would have to name a zone it
    does not have.

    Three things have to be true of it and none is visible from the card: it
    reaches only the seat that granted it, only the printed type, and it ends
    at CR 514.2's cleanup with the "until end of turn" effects.
    """
    game, p1, _p2 = _w2g1_main_phase_duel()
    p1.battlefield.append(_W2G1Permanent(card=_W2G1_WTH["Winding Canyons"]))
    bears = _W2G1_CATALOG["Grizzly Bears"]

    game.active_player_index = 1
    assert not _w2g1_instant_speed(bears, game, 0)

    game.active_player_index = 0
    game.activate_permanent_ability(0, "Winding Canyons", ability_index=1)
    resolve_stack(game)

    game.active_player_index = 1
    assert _w2g1_instant_speed(bears, game, 0), "on the opponent's turn"
    assert not _w2g1_instant_speed(bears, game, 1), "and only for the granter"
    assert not _w2g1_instant_speed(_W2G1_CATALOG["Black Lotus"], game, 0), (
        "and only for the type it names"
    )

    _w2g1_expire_flash(game)
    assert not _w2g1_instant_speed(bears, game, 0)


# --- W2G5: enforcement, entry replacement and the last statics ---

from engine.models import Permanent as _W2G5Permanent  # noqa: E402
from engine.card_loader import load_cards as _w2g5_load  # noqa: E402
from engine.card_loader import manifest_set_path as _w2g5_path  # noqa: E402
from engine.spell_prohibitions import (  # noqa: E402
    casting_forbidden_this_turn,
    clear_turn_spell_prohibitions,
    forbid_casting_this_turn,
    forbid_nonmana_activations_this_turn,
)
from tests.helpers import resolve_stack


def _w2g5_spell(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


@pytest.mark.cr("601.3", "205.2")
def test_601_3_a_per_seat_cast_prohibition_is_read_by_card_type():
    """CR 601.3: "a player can begin to cast a spell only if … no rule or effect
    prohibits that player from casting it."

    The record is per **seat** and narrowed by card type, and the type test is
    the one CR 205.2 asks: a card has *every* type its line names, so an artifact
    creature is stopped by a ban on either word.
    """
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    forbid_casting_this_turn(game, 1, ("instant",))

    assert casting_forbidden_this_turn(
        game, 1, _w2g5_spell("Bolt", "Instant")
    ) == "instant"
    assert casting_forbidden_this_turn(
        game, 1, _w2g5_spell("Bear", "Creature - Bear")
    ) is None
    assert casting_forbidden_this_turn(
        game, 0, _w2g5_spell("Bolt", "Instant")
    ) is None, "the prohibition names one seat"


@pytest.mark.cr("601.3")
def test_601_3_two_prohibitions_on_one_seat_accumulate():
    """Two Abeyances are two prohibitions. A second resolution that *replaced*
    the first would let a narrower copy of an effect undo a wider one."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    forbid_casting_this_turn(game, 1, ("instant", "sorcery"))
    forbid_casting_this_turn(game, 1, ("creature",))

    for type_line in ("Instant", "Sorcery", "Creature - Bear"):
        assert casting_forbidden_this_turn(
            game, 1, _w2g5_spell("X", type_line)
        ) is not None


@pytest.mark.cr("602.5", "605.1a")
def test_602_5_a_per_seat_activation_prohibition_spares_mana_abilities():
    """CR 602.5: "a player can't begin to activate an ability that's prohibited
    from being activated" — with CR 605.1a's mana ability as the exception.

    Asked of ``mana_payment.is_mana_ability``, the reader Faith's Fetters'
    identical exception already uses, rather than of a second opinion about
    which abilities make mana. The two readings are not the same: the
    same-named function in ``ai_valuation`` answers False for a mana ability
    that lowers to a ``sequence`` (the painlands, the depletion lands), which
    would shut off an ability the card leaves open.
    """
    lea = {c.name: c for c in _w2g5_load([_w2g5_path("LEA")])}
    seat = PlayerState(
        name="P1",
        battlefield=[
            _W2G5Permanent(card=lea["Birds of Paradise"]),
            _W2G5Permanent(card=lea["Icy Manipulator"]),
        ],
    )
    game = Game(players=[PlayerState(name="P0"), seat])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in seat.battlefield:
        perm.metadata["summoning_sickness_turn"] = -1
    forbid_nonmana_activations_this_turn(game, 1)

    assert game.activate_permanent_ability(1, "Birds of Paradise").supported
    assert not game.activate_permanent_ability(
        1, "Icy Manipulator", permanent_index=1,
        target_player_index=0, target_permanent_index=0,
    ).supported


@pytest.mark.cr("514.2")
def test_a_per_seat_prohibition_does_not_outlive_its_turn():
    """"Until end of turn." Both records are dropped in one turn-boundary sweep,
    for the reason the land-play records are: a prohibition that outlived its
    turn is a seat that quietly stops casting, and no test would say which turn
    it came from."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    forbid_casting_this_turn(game, 1, ("instant",))
    forbid_nonmana_activations_this_turn(game, 1)

    clear_turn_spell_prohibitions(game)

    assert casting_forbidden_this_turn(
        game, 1, _w2g5_spell("Bolt", "Instant")
    ) is None
    assert game.nonmana_activations_forbidden_this_turn == set()

# --- end W2G5 ---


# ---------------------------------------------------------------------------
# A **compound** duration: a swept moment and a re-asked state (W3G4)
# ---------------------------------------------------------------------------
#
# "Until end of turn, for as long as that card remains on top of your library,
# … you may play that card without paying its mana cost." (Temporal Aperture.)
# CR 611.2a states a moment and CR 611.2b states a condition, on one effect —
# the first sentence in this pool to state both.
#
# The engine needs no new representation for that, and these tests are what
# says so: a *moment* is swept (``expire_end_of_turn``) and a *state* is
# re-asked on every read (``_covers``), so the two are answered at different
# times and neither can be a special case of the other. What was missing was a
# way to spell the second condition, not a way to hold two of them.

from engine.cast_permissions import expire_end_of_turn as _w3g4_expire_eot
from engine.cast_permissions import playable_from_zones as _w3g4_playable
from engine.oracle import compile_card_oracle as _w3g4_compile

_W3G4_LIBRARY_CARDS = [
    _w2g5_spell("First", "Instant"),
    _w2g5_spell("Second", "Instant"),
    _w2g5_spell("Third", "Instant"),
]


def _w3g4_granted_top_permission():
    """A seat holding "play the top card of your library, until end of turn,
    for as long as it stays on top" over the first card of a three-card deck."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    first, second, third = _W3G4_LIBRARY_CARDS
    game.players[0].library = [first, second, third]
    grant_permission(
        game, player_index=0, zone="library", mode="play", cards=[first],
        position="top", free=True, duration="end_of_turn",
        source_name="a compound duration",
    )
    return game, first, second


@pytest.mark.cr("611.2a", "611.2b", "601.3")
def test_a_stated_moment_and_a_stated_state_are_both_honoured():
    """Neither half alone is the effect. While both hold the permission is
    live; this is the control the two ending tests below are read against."""
    game, first, _second = _w3g4_granted_top_permission()

    assert permission_for(game, 0, first, "library") is not None


@pytest.mark.cr("611.2b", "401.5")
def test_the_state_half_ends_the_permission_with_nothing_sweeping():
    """CR 611.2b's "for as long as" clause, over the object CR 401.5 names.

    The card never leaves the library — another card is simply put in front of
    it — so no zone-membership check can see this, and no sweep runs between the
    two reads. The position is the whole of what ends it, and which end "top"
    means is the *zone's* answer: a library's first card, where CR 404.1 puts a
    graveyard's on the pile's other end."""
    game, first, second = _w3g4_granted_top_permission()

    game.players[0].library.remove(second)
    game.players[0].library.insert(0, second)

    assert first in game.players[0].library
    assert permission_for(game, 0, first, "library") is None


@pytest.mark.cr("611.2a", "514.2")
def test_the_moment_half_ends_the_permission_with_the_state_still_true():
    """The mirror. The card is still the library's first, so the only thing
    that can have ended the grant is CR 514.2's cleanup sweep — which is why
    the two halves are stored in two fields and not contested in one."""
    game, first, _second = _w3g4_granted_top_permission()

    _w3g4_expire_eot(game)

    assert game.players[0].library[0] is first
    assert permission_for(game, 0, first, "library") is None


@pytest.mark.cr("601.3", "400.2")
def test_a_library_permission_offers_only_its_own_seats_top_card():
    """CR 601.3's permission is offered through the one seam the web layer
    reads. A library is hidden (CR 400.2), so the offer is the seat's own first
    card and nothing else — the rest of the deck is not a pile a viewer may be
    shown, however many cards a grant might cover."""
    game, first, _second = _w3g4_granted_top_permission()
    game.players[1].library = list(_W3G4_LIBRARY_CARDS)

    offered = _w3g4_playable(game, 0)

    assert [(e["zone"], e["index"], e["name"], e["free"]) for e in offered] == [
        ("library", 0, first.name, True)
    ]
    assert _w3g4_playable(game, 1) == []


@pytest.mark.cr("118.9", "601.3")
def test_a_cost_waiver_an_exiled_cards_grant_cannot_carry_refuses_the_line():
    """The refusal that keeps the new phrase honest.

    "…without paying its mana cost" became readable behind "that card" for
    Temporal Aperture, and "that card" is also how an *exiled-cards* permission
    names its pile. That arm's payload has nowhere to put a waiver, so a card
    printing one would be a permission with CR 118.9 quietly dropped — the
    player paying for a spell the effect gave away. It refuses by name instead.
    """
    def _card(effect: str) -> CardDefinition:
        return CardDefinition(
            name=f"Test Waiver {len(effect)}", mana_cost="{2}", cmc=2.0,
            type_line="Sorcery",
            oracle_text=f"Exile the top card of your library. {effect}",
            colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
        )

    honoured = "Until end of turn, you may play that card."
    dropped = "Until end of turn, you may play that card without paying its mana cost."

    # The pair is the assertion: the waiver is the only difference between the
    # sentence the engine carries out and the one it declines.
    assert _w3g4_compile(_card(honoured)).supported
    assert not _w3g4_compile(_card(dropped)).supported

# --- end W3G4 ---
