"""Judgment instants.

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
from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_duel(*, active: int = 0) -> "_w1g8_Game":
    """Two seats, mana costs waived, seat *active*'s turn started for real."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(active)
    return game


def _w1g8_zone_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


# --- Seedtime -------------------------------------------------------------

def test_w1g8_seedtime_takes_an_extra_turn_when_an_opponent_cast_a_blue_spell(set_pool):
    """"Take an extra turn after this one if an opponent cast a blue spell this
    turn." Ruling 2004-10-04: "an unresolved spell still counts" — the blue
    spell here is cast *in response*, so it is still on the stack above
    Seedtime when it is cast, and resolves before it."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(jud["Seedtime"])
    game.players[1].hand.append(lea["Ancestral Recall"])
    game.players[1].library.extend([lea["Island"]] * 3)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.extra_turns.get(0, 0) == 1
    assert game.extra_turns.get(1, 0) == 0
    assert "P1 gained an extra turn" in game.log
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Seedtime"]


def test_w1g8_seedtime_without_a_blue_opposing_cast_takes_no_turn(set_pool):
    """The narrowing is enforced, not dropped: an opponent's *red* spell does
    not open it, and neither does a blue spell Seedtime's own caster cast."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.extend([jud["Seedtime"], lea["Ancestral Recall"]])
    game.players[0].library.extend([lea["Island"]] * 3)
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 17                 # the Bolt resolved
    assert game.extra_turns.get(0, 0) == 0
    assert not any("gained an extra turn" in line for line in game.log)
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


def test_w1g8_seedtime_is_cast_only_during_its_casters_turn(set_pool):
    """"Cast this spell only during your turn." (CR 601.3.) Refused on the
    opponent's turn with the card still in hand, and legal again on the
    caster's own."""
    jud = set_pool("JUD")
    game = _w1g8_duel(active=1)
    game.players[0].hand.append(jud["Seedtime"])
    refused = game.cast_from_hand(0, "Seedtime")
    assert not refused.supported
    assert "can only be cast during your turn" in refused.details
    assert _w1g8_zone_names(game.players[0].hand) == ["Seedtime"]
    game.start_turn(0)
    assert game.cast_from_hand(0, "Seedtime").supported
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


# --- Laquatus's Disdain ---------------------------------------------------

def _w1g8_firebolt_flashed_back(set_pool) -> "_w1g8_Game":
    """Seat 0 flashes Firebolt back at seat 1, leaving it on the stack."""
    game = _w1g8_duel()
    game.players[0].graveyard.append(set_pool("ODY")["Firebolt"])
    assert game.queue_from_hand(
        0, "Firebolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert game.stack[-1].flashback and game.stack[-1].cast_from_zone == "graveyard"
    return game


def test_w1g8_laquatuss_disdain_counters_a_spell_cast_from_a_graveyard(set_pool):
    """"Counter target spell cast from a graveyard. Draw a card." A flashed-back
    Firebolt is countered (and, flashed back, exiled — CR 702.34a), and the
    Disdain's caster draws."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_firebolt_flashed_back(set_pool)
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    game.players[1].library.append(lea["Island"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Firebolt"]
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20                       # Firebolt never resolved
    assert _w1g8_zone_names(game.players[0].exile) == ["Firebolt"]
    assert _w1g8_zone_names(game.players[1].hand) == ["Island"]
    assert any(
        line.startswith("Firebolt was countered by Laquatus's Disdain")
        for line in game.log
    )


def test_w1g8_laquatuss_disdain_counters_any_graveyard_cast_not_only_flashback(set_pool):
    """Ruling 2004-10-04: "Can be used to counter a spell cast using the
    Flashback ability, **or cast from the graveyard using any other effect**."
    A graveyard opened by another permission (CR 601.3) is a graveyard cast."""
    from engine.cast_permissions import grant_permission

    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    assert game.queue_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert not game.stack[-1].flashback
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Lightning Bolt"]


def test_w1g8_laquatuss_disdain_cannot_be_cast_at_a_spell_cast_from_a_hand(set_pool):
    """The narrowing is the picker's and the gate's: a Lightning Bolt cast from
    a hand is not offered, and naming it anyway is refused before anything is
    spent (CR 601.2c) — the Disdain stays in hand and the Bolt resolves."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert spec["valid_targets"] == []
    refused = game.cast_from_hand(1, "Laquatus's Disdain", target_stack_index=0)
    assert not refused.supported
    assert _w1g8_zone_names(game.players[1].hand) == ["Laquatus's Disdain"]
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17


# --- Flash of Insight -----------------------------------------------------

def _w1g8_insight_board(set_pool, *, blue_in_graveyard: int) -> "_w1g8_Game":
    """Seat 0: Flash of Insight on the bottom of its graveyard, *blue_in_graveyard*
    Counterspells and a Lightning Bolt above it, five lands in its library, and
    exactly {1}{U} floating — mana costs enforced."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.enforce_mana_costs = True
    player = game.players[0]
    player.graveyard.append(jud["Flash of Insight"])
    player.graveyard.extend([lea["Counterspell"]] * blue_in_graveyard)
    player.graveyard.append(lea["Lightning Bolt"])
    player.library.extend([lea[name] for name in (
        "Island", "Forest", "Mountain", "Swamp", "Plains",
    )])
    player.mana_pool.update({"U": 1, "C": 1})
    return game


def test_w1g8_flash_of_insight_flashes_back_exiling_x_blue_cards(set_pool):
    """"Flashback—{1}{U}, Exile X blue cards from your graveyard." X is the
    caster's announcement (CR 107.3a) and both the price and the effect read
    it: two blue cards leave the graveyard, the top two cards are looked at,
    one goes to hand and the other to the bottom (CR 702.34a: the spell is
    exiled afterwards). The Lightning Bolt is not blue and stays."""
    game = _w1g8_insight_board(set_pool, blue_in_graveyard=3)
    player = game.players[0]
    spec = game.cast_target_spec(0, set_pool("JUD")["Flash of Insight"], from_zone="graveyard")
    assert spec["announces_x"] and spec["max_x"] == 3     # the spell itself is not one
    # The caster names which blue cards pay (CR 601.2b) — slots in the pile as
    # it stands, the spell still at the bottom of it.
    cast = game.cast_from_hand(
        0, "Flash of Insight", from_zone="graveyard", x_value=2,
        cost_graveyard_indices=[1, 3],
    )
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert not any(player.mana_pool.values())
    assert _w1g8_zone_names(player.exile) == ["Counterspell", "Counterspell", "Flash of Insight"]
    assert _w1g8_zone_names(player.graveyard) == ["Counterspell", "Lightning Bolt"]
    assert len(player.hand) == 1 and player.hand[0].name in ("Island", "Forest")
    assert [card.name for card in player.library][:3] == ["Mountain", "Swamp", "Plains"]
    assert len(player.library) == 4
    assert "P1 is looking at the top 2 cards of their library" in game.log


def test_w1g8_flash_of_insight_cannot_exile_itself_to_pay_for_its_flashback(set_pool):
    """"You can't exile Flash of Insight to pay for its own flashback cost." CR
    601.2a moves it to the stack before any cost is paid, so with two other
    blue cards an X of three is unpayable (CR 601.2h): refused with nothing
    spent and the card still in the graveyard. An X of two is fine."""
    game = _w1g8_insight_board(set_pool, blue_in_graveyard=2)
    player = game.players[0]
    refused = game.cast_from_hand(0, "Flash of Insight", from_zone="graveyard", x_value=3)
    assert not refused.supported
    assert "flashback cost" in refused.details and "601.2h" in refused.details
    assert player.mana_pool["U"] == 1 and player.exile == []
    assert "Flash of Insight" in _w1g8_zone_names(player.graveyard)
    assert game.cast_from_hand(0, "Flash of Insight", from_zone="graveyard", x_value=2).supported


def test_w1g8_flash_of_insight_holds_a_named_set_of_cards_to_the_announced_x(set_pool):
    """CR 601.2h: "Partial payments are not allowed." Naming one blue card for
    an X of two, or naming the Lightning Bolt, or the spell's own slot, is
    refused before anything is spent."""
    for named in ([1], [1, 4], [0, 1]):
        game = _w1g8_insight_board(set_pool, blue_in_graveyard=3)
        refused = game.cast_from_hand(
            0, "Flash of Insight", from_zone="graveyard", x_value=2,
            cost_graveyard_indices=named,
        )
        assert not refused.supported, named
        assert game.players[0].exile == [] and len(game.players[0].graveyard) == 5


def test_w1g8_flash_of_insight_from_hand_looks_at_x(set_pool):
    """Cast from a hand for {X}{1}{U}, it exiles nothing and looks at X."""
    lea = set_pool("LEA")
    game = _w1g8_duel()
    player = game.players[0]
    player.hand.append(set_pool("JUD")["Flash of Insight"])
    player.graveyard.append(lea["Counterspell"])
    player.library.extend([lea["Island"], lea["Forest"], lea["Mountain"]])
    assert game.cast_from_hand(0, "Flash of Insight", x_value=3).supported
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert _w1g8_zone_names(player.graveyard) == ["Counterspell", "Flash of Insight"]
    assert len(player.hand) == 1 and len(player.library) == 2
    assert "P1 is looking at the top 3 cards of their library" in game.log


# --- Spelljack ------------------------------------------------------------

def _w1g8_spelljacked(set_pool, name: str, *, from_zone: str = "hand", **cast) -> "_w1g8_Game":
    """Seat 1 casts *name* at seat 0; seat 0 answers with Spelljack, paying
    {3}{U}{U}{U} for it, and the stack is drained. Costs enforced from then on."""
    game = _w1g8_duel(active=1)
    spell = (set_pool("ODY") if name == "Firebolt" else set_pool("LEA"))[name]
    getattr(game.players[1], "graveyard" if from_zone == "graveyard" else "hand").append(spell)
    assert game.queue_from_hand(1, name, from_zone=from_zone, **cast).supported
    game.players[0].hand.append(set_pool("JUD")["Spelljack"])
    assert game.queue_from_hand(0, "Spelljack", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    game.enforce_mana_costs = True
    return game


def test_w1g8_spelljack_counters_exiles_and_lets_its_caster_cast_the_card_free(set_pool):
    """"Counter target spell. If that spell is countered this way, exile it
    instead of putting it into its owner's graveyard. You may play it without
    paying its mana cost for as long as it remains exiled." The Bolt never
    resolves; it waits in its owner's exile, and Spelljack's caster casts it
    there with an empty pool. Ruling 2004-10-04: "If you cast an instant or
    sorcery, it goes to its owner's graveyard when it resolves.\""""
    game = _w1g8_spelljacked(set_pool, "Lightning Bolt", target_player_index=0)
    assert game.players[0].life == 20
    assert _w1g8_zone_names(game.players[1].exile) == ["Lightning Bolt"]
    assert game.players[1].graveyard == []
    # Seat 1 may not cast its own card back; seat 0 may, and for nothing.
    game.start_turn(0)
    assert not game.cast_from_hand(1, "Lightning Bolt", from_zone="exile", target_player_index=0).supported
    assert not any(game.players[0].mana_pool.values())
    cast = game.cast_from_hand(0, "Lightning Bolt", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.players[1].exile == []
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Lightning Bolt"]
    assert game.players[0].graveyard == [] or _w1g8_zone_names(game.players[0].graveyard) == ["Spelljack"]


def test_w1g8_spelljack_permission_lasts_for_as_long_as_the_card_remains_exiled(set_pool):
    """CR 611.2a's duration stated as a zone: the turn ending does not end it,
    and the card leaving exile does."""
    from engine.cast_permissions import expire_end_of_turn, permission_for

    game = _w1g8_spelljacked(set_pool, "Lightning Bolt", target_player_index=0)
    bolt = game.players[1].exile[0]
    expire_end_of_turn(game)
    assert permission_for(game, 0, bolt, "exile") is not None
    game.players[1].exile.remove(bolt)
    game.players[1].graveyard.append(bolt)
    assert permission_for(game, 0, bolt, "exile") is None


def test_w1g8_spelljack_on_a_flashed_back_spell(set_pool):
    """Ruling 2004-10-04: "This spell can be used on a spell cast using
    Flashback." The flashed-back Firebolt is exiled (by its own keyword, CR
    702.34a, and by Spelljack's replacement — one exile either way), and its
    new controller may cast it from there, as an ordinary cast this time: it
    goes to its owner's graveyard when it resolves, not to exile."""
    game = _w1g8_spelljacked(
        set_pool, "Firebolt", from_zone="graveyard", target_player_index=0,
    )
    assert game.players[0].life == 20
    assert _w1g8_zone_names(game.players[1].exile) == ["Firebolt"]
    game.start_turn(0)
    cast = game.cast_from_hand(0, "Firebolt", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert not game.stack or not game.stack[-1].flashback
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 18
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Firebolt"]


def test_w1g8_spelljack_casts_an_x_spell_for_x_equal_to_zero(set_pool):
    """"(If it has X in its mana cost, X is 0.)" — CR 107.3b: cast while paying
    neither its mana cost nor an alternative cost that includes X, a Fireball
    announced at five deals nothing."""
    game = _w1g8_spelljacked(set_pool, "Fireball", x_value=3, target_player_index=0)
    assert game.players[0].life == 20
    game.start_turn(0)
    cast = game.cast_from_hand(0, "Fireball", from_zone="exile", x_value=5, target_player_index=1)
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Fireball"]


# --- Shaman's Trance --------------------------------------------------------

def _w1g8_tranced(set_pool) -> "_w1g8_Game":
    """Seat 0 resolves Shaman's Trance on its own turn. Seat 1's graveyard holds
    a Lightning Bolt, a Firebolt and a Mountain; seat 0's holds a Lightning
    Bolt of its own. Costs waived."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Shaman's Trance"])
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    game.players[1].graveyard.extend([lea["Lightning Bolt"], ody["Firebolt"], lea["Mountain"]])
    assert game.cast_from_hand(0, "Shaman's Trance").supported
    _w1g8_resolve_stack(game)
    return game


def test_w1g8_shamans_trance_opens_other_players_graveyards_to_its_caster(set_pool):
    """"You may play lands and cast spells from other players' graveyards this
    turn as though those cards were in your graveyard." Seat 0 casts seat 1's
    Bolt (it goes back to its owner's graveyard, CR 608.2n), plays seat 1's
    Mountain as its land drop, and flashes back seat 1's Firebolt (ruling
    2004-10-04: "You can use Flashback on cards to cast them") — exiled to its
    owner's exile. Its own graveyard is not one the sentence opens."""
    from engine.cast_permissions import playable_from_zones

    game = _w1g8_tranced(set_pool)
    offered = {(entry["owner_seat"], entry["name"]) for entry in playable_from_zones(game, 0)}
    assert offered == {(1, "Lightning Bolt"), (1, "Firebolt"), (1, "Mountain")}

    assert game.cast_from_hand(0, "Lightning Bolt", from_zone="graveyard", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17
    assert "Lightning Bolt" in _w1g8_zone_names(game.players[1].graveyard)

    assert game.cast_from_hand(0, "Mountain", from_zone="graveyard").supported
    mountain = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert "Mountain" not in _w1g8_zone_names(game.players[1].graveyard)
    # Played by seat 0, still seat 1's card (CR 108.3): it dies into seat 1's pile.
    assert game.owner_index_of(mountain) == 1

    flashed = game.queue_from_hand(
        0, "Firebolt", from_zone="graveyard", target_player_index=1,
        alternative_cost=True,
    )
    assert flashed.supported, flashed.details
    assert game.stack[-1].flashback
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 15
    assert _w1g8_zone_names(game.players[1].exile) == ["Firebolt"]


def test_w1g8_shamans_trance_closes_other_players_graveyards_to_them(set_pool):
    """"Other players can't play lands or cast spells from their graveyards this
    turn." Seat 1 may not flash back its own Firebolt nor play its Mountain out
    of its graveyard — and the cast is refused before anything is spent."""
    game = _w1g8_tranced(set_pool)
    game.enforce_mana_costs = True
    game.players[1].mana_pool.update({"R": 1, "C": 4})
    refused = game.cast_from_hand(1, "Firebolt", from_zone="graveyard", target_player_index=0)
    assert not refused.supported
    assert "can't play lands or cast spells from their graveyard" in refused.details
    assert game.players[1].mana_pool["R"] == 1
    assert "Firebolt" in _w1g8_zone_names(game.players[1].graveyard)
    assert game.players[0].life == 20


def test_w1g8_shamans_trance_on_an_opponents_turn_stops_their_graveyard_land_drop(set_pool):
    """Both verbs are printed, so the ban binds a land drop too (CR 305.1) —
    which matters on the opponent's own turn, where the instant is cast in
    their upkeep: with their graveyard opened by another effect, their
    Mountain still may not be played from it, while one from hand may."""
    from engine.cast_permissions import grant_permission

    lea = set_pool("LEA")
    game = _w1g8_duel(active=1)
    game.players[0].hand.append(set_pool("JUD")["Shaman's Trance"])
    game.players[1].graveyard.append(lea["Mountain"])
    game.players[1].hand.append(lea["Mountain"])
    grant_permission(
        game, player_index=1, zone="graveyard", mode="play", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    assert game.cast_from_hand(0, "Shaman's Trance").supported
    _w1g8_resolve_stack(game)
    refused = game.cast_from_hand(1, "Mountain", from_zone="graveyard")
    assert not refused.supported
    assert "can't play lands or cast spells from their graveyard" in refused.details
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Mountain"]
    assert game.cast_from_hand(1, "Mountain").supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Mountain"]


def test_w1g8_shamans_trance_ends_with_the_turn(set_pool):
    """"This turn" on both halves: after the cleanup sweep (CR 514.2) and the
    next turn's bookkeeping, seat 0 has no permission over seat 1's pile and
    seat 1 may flash its own Firebolt back again."""
    from engine.cast_permissions import playable_from_zones

    game = _w1g8_tranced(set_pool)
    game.resolve_cleanup_step(0)
    game.begin_turn_bookkeeping(1)
    assert playable_from_zones(game, 0) == []
    game.start_turn(1)
    cast = game.cast_from_hand(1, "Firebolt", from_zone="graveyard", target_player_index=0)
    assert cast.supported, cast.details
    assert game.players[0].life == 18

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
