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

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.color_changes import change_color as _w1g8_change_color
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Terror": "LEA", "Lightning Bolt": "LEA", "Swamp": "LEA", "Forest": "LEA",
    "Island": "LEA", "Healing Salve": "LEA", "Giant Growth": "LEA",
    "Grizzly Bears": "LEA", "Drudge Skeletons": "LEA", "Counterspell": "LEA",
    "Library of Leng": "LEA", "Megrim": "STH",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_duel(set_pool, *, hand=(), opp_hand=(), library=(), opp_library=(),
               interactive=()) -> _w1g8_Game:
    """Two seats with costs enforced and mana to pay them, so a refused cast
    can be shown to have spent nothing."""
    forest = _w1g8_card(set_pool, "Forest")
    me = _w1g8_PlayerState(
        name="Me", hand=[_w1g8_card(set_pool, n) for n in hand],
        library=[_w1g8_card(set_pool, n) for n in library] or [forest] * 12,
    )
    opp = _w1g8_PlayerState(
        name="Opp", hand=[_w1g8_card(set_pool, n) for n in opp_hand],
        library=[_w1g8_card(set_pool, n) for n in opp_library] or [forest] * 12,
    )
    game = _w1g8_Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_W1G8_RICH)
    opp.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_settle(game) -> None:
    """Resolve the stack and take every owed default — the two calls an AI or
    headless seat's loop makes between actions."""
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_exile_on_the_wire(game, viewer, seat: int) -> list:
    from web.serialization import _serialize_player

    payload = _serialize_player(game.players[seat], viewer, seat, game)["exile"]
    return [entry if isinstance(entry, str) else entry["name"] for entry in payload]


# --- Mind Extraction ----------------------------------------------------------

_W1G8_VICTIM_HAND = [
    "Terror", "Lightning Bolt", "Swamp", "Gerrard's Verdict", "Dodecapod",
    "Healing Salve",
]


@_w1g8_pytest.mark.parametrize("sacrificed, gone", [
    # Black: the black card and the white-black one (CR 105.2b: it *is* black).
    ("Drudge Skeletons", ["Terror", "Gerrard's Verdict"]),
    # White-black: every card sharing either colour (the ruling of 2004-10-04).
    ("Putrid Warrior", ["Terror", "Gerrard's Verdict", "Healing Salve"]),
])
def test_w1g8_mind_extraction_discards_every_card_of_the_sacrificed_creatures_colors(
    set_pool, sacrificed, gone,
):
    """"Target player reveals their hand and discards all cards of each of the
    sacrificed creature's colors." The land, the red card and the colorless
    artifact stay, whatever was sacrificed."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=_W1G8_VICTIM_HAND)
    paid = _w1g8_put(game, set_pool, 0, sacrificed)
    bystander = _w1g8_put(game, set_pool, 0, "Grizzly Bears")

    spec = game.cast_target_spec(0, _w1g8_card(set_pool, "Mind Extraction"))
    assert [t["seat"] for t in spec["valid_targets"]] == [0, 1]
    assert {t["name"] for t in spec["cost_spec"]["valid_targets"]} == {
        sacrificed, "Grizzly Bears",
    }
    assert game.queue_from_hand(
        0, "Mind Extraction", target_player_index=1,
        cost_permanent_ids=[paid.permanent_id],
    ).supported
    assert _w1g8_names(game.players[0].graveyard) == [sacrificed], "paid as it was cast"
    assert game.is_on_battlefield(bystander)
    _w1g8_settle(game)

    kept = [name for name in _W1G8_VICTIM_HAND if name not in gone]
    assert _w1g8_names(game.players[1].hand) == kept, game.log
    assert sorted(_w1g8_names(game.players[1].graveyard)) == sorted(gone)
    assert any(
        line.startswith("Opp reveals their hand: Terror, Lightning Bolt")
        for line in game.log
    ), game.log


def test_w1g8_mind_extraction_with_a_colorless_sacrifice_only_reveals(set_pool):
    """"If you sacrifice a colorless creature, you get to see their hand but
    they discard no cards." A colourless creature has no colours for a card to
    be *of* — read as "no narrowing" it would empty the hand."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=_W1G8_VICTIM_HAND)
    _w1g8_put(game, set_pool, 0, "Dodecapod")

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == _W1G8_VICTIM_HAND
    assert game.players[1].graveyard == []
    assert any("Opp reveals their hand" in line for line in game.log)
    assert any("colorless, so nothing is discarded" in line for line in game.log)


def test_w1g8_mind_extraction_reads_the_colour_the_creature_last_had(set_pool):
    """CR 608.2h: the creature is a card in a graveyard by resolution, so its
    colours are the ones it last had on the battlefield — a green Bears turned
    black takes the black cards, and the green Giant Growth stays."""
    hand = ["Terror", "Giant Growth", "Lightning Bolt"]
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=hand)
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    _w1g8_change_color(bears, ["B"], until_eot=True)

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Giant Growth", "Lightning Bolt"]
    assert _w1g8_names(game.players[1].graveyard) == ["Terror"]


def test_w1g8_mind_extraction_cannot_be_cast_with_no_creature_to_sacrifice(set_pool):
    """The additional cost is mandatory (CR 601.2h): no creature, no cast, and
    nothing is spent on the way to the refusal."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=["Terror"])
    before = dict(game.players[0].mana_pool)

    result = game.queue_from_hand(0, "Mind Extraction", target_player_index=1)

    assert not result.supported and "no creature to sacrifice" in result.details
    assert _w1g8_names(game.players[0].hand) == ["Mind Extraction"]
    assert dict(game.players[0].mana_pool) == before
    assert game.stack == [] and _w1g8_names(game.players[1].hand) == ["Terror"]


def test_w1g8_megrim_sees_each_card_mind_extraction_takes(set_pool):
    """Nobody chooses, but they are still discards (CR 701.9a): a watcher fires
    once per card."""
    game = _w1g8_duel(
        set_pool, hand=["Mind Extraction"], opp_hand=["Terror", "Gerrard's Verdict", "Island"],
    )
    _w1g8_put(game, set_pool, 0, "Megrim")
    _w1g8_put(game, set_pool, 0, "Drudge Skeletons")

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Island"]
    assert game.players[1].life == 16, game.log


# --- Gerrard's Verdict ---------------------------------------------------------


@_w1g8_pytest.mark.parametrize("picks, gained", [
    ([0, 2], 6),      # Forest and Island
    ([0, 1], 3),      # Forest and Grizzly Bears
    ([1, 3], 0),      # Grizzly Bears and Terror
])
def test_w1g8_gerrards_verdict_gains_three_per_land_the_player_chose_to_discard(
    set_pool, picks, gained,
):
    """"Target player discards two cards. You gain 3 life for each land card
    discarded this way." The discarding player chooses (CR 701.9b), so nothing
    is gained until they have — and what is counted is what they picked."""
    hand = ["Forest", "Grizzly Bears", "Island", "Terror"]
    game = _w1g8_duel(
        set_pool, hand=["Gerrard's Verdict"], opp_hand=hand, interactive=(0, 1),
    )

    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert game.players[0].life == 20, "the gain waits for the answer"
    assert game.confirm_discard(1, picks)

    assert game.players[0].life == 20 + gained, game.log
    assert sorted(_w1g8_names(game.players[1].graveyard)) == sorted(hand[i] for i in picks)
    assert _w1g8_names(game.players[0].graveyard) == ["Gerrard's Verdict"]


def test_w1g8_gerrards_verdict_counts_what_was_discarded_not_what_was_asked(set_pool):
    """One card in hand is one discard (CR 608.2: as much as possible), and an
    empty hand is none — the printed "two" is not the number counted."""
    game = _w1g8_duel(set_pool, hand=["Gerrard's Verdict"], opp_hand=["Island"])
    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[0].life == 23 and game.players[1].hand == []

    game = _w1g8_duel(set_pool, hand=["Gerrard's Verdict"])
    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[0].life == 20
    assert _w1g8_names(game.players[0].graveyard) == ["Gerrard's Verdict"]


def test_w1g8_a_land_put_on_the_library_by_library_of_leng_is_not_a_land_card_discarded(
    set_pool,
):
    """CR 701.9c: a card discarded into a hidden zone unrevealed has undefined
    characteristics, so it is discarded and is not "a land card"."""
    game = _w1g8_duel(
        set_pool, hand=["Gerrard's Verdict"], opp_hand=["Forest", "Island"],
        interactive=(0, 1),
    )
    _w1g8_put(game, set_pool, 1, "Library of Leng")

    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(1, [0, 1], to_library=True)

    assert game.players[0].life == 20, game.log
    assert _w1g8_names(game.players[1].library[:2]) == ["Forest", "Island"]
    assert game.players[1].graveyard == []


@_w1g8_pytest.mark.parametrize("text", [
    # No step of the effect discarded anything for "this way" to name.
    "You gain 3 life for each land card discarded this way.",
    # What is discarded is a card (CR 701.9a); "each land discarded" is a
    # sentence nobody printed and is not read as a count of lands in play.
    "Target player discards two cards. You gain 3 life for each land discarded this way.",
    # The record holds printed cards, so only what is printed on one is
    # testable — "you control" is not.
    "Target player discards two cards. You gain 3 life for each land card you control discarded this way.",
])
def test_w1g8_a_discarded_card_count_the_record_cannot_answer_is_refused(text):
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
    )
    assert not _w1g8_compile(probe).supported


# --- Suppress --------------------------------------------------------------------


def _w1g8_suppress_turn(game) -> None:
    """Start seat 0's turn through the real turn structure, and refill the
    pool the beginning phase emptied."""
    game.start_turn(0)
    game.players[0].mana_pool.update(_W1G8_RICH)


def test_w1g8_suppress_hides_a_hand_until_the_end_of_that_players_next_turn(set_pool):
    """"Target player exiles all cards from their hand face down. At the
    beginning of the end step of that player's next turn, that player returns
    those cards to their hand." Cast on my turn: gone through my end step,
    still gone while they draw and play their turn, back at *their* end step —
    with the card they drew in between untouched."""
    held = ["Terror", "Counterspell", "Island"]
    game = _w1g8_duel(
        set_pool, hand=["Suppress"], opp_hand=held, opp_library=["Swamp"] * 10,
    )
    _w1g8_suppress_turn(game)

    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[1].hand == []
    assert _w1g8_names(game.players[1].exile) == held

    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert game.players[1].hand == [], "my end step is not theirs"

    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g8_names(game.players[1].hand) == ["Swamp"], "they still draw"
    game.resolve_end_step(1)
    assert _w1g8_names(game.stack) == ["Suppress"], "a trigger, on the stack"
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Swamp", *held], game.log
    assert game.players[1].exile == []
    assert game.delayed_triggers == []


def test_w1g8_suppress_is_face_down_to_every_viewer_and_the_log_names_nothing(set_pool):
    """CR 406.3: a card exiled face down can't be examined by any player — its
    owner included, since nothing here says they may look. The wire sends a
    card back for each, to the opponent, the owner and a spectator alike, and
    neither the exile nor the return writes a card name into the public log."""
    held = ["Terror", "Counterspell"]
    game = _w1g8_duel(set_pool, hand=["Suppress"], opp_hand=held)
    _w1g8_suppress_turn(game)
    game.players[1].exile.append(_w1g8_card(set_pool, "Giant Growth"))  # face up, before

    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)

    for viewer in (0, 1, None):
        assert _w1g8_exile_on_the_wire(game, viewer, 1) == [
            "Giant Growth", "<hidden>", "<hidden>",
        ], viewer
    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[1].hand)) == ["Counterspell", "Forest", "Terror"]
    assert _w1g8_exile_on_the_wire(game, 0, 1) == ["Giant Growth"]
    told = [line for line in game.log if "Terror" in line or "Counterspell" in line]
    assert told == [], told
    assert sum("returned a face-down card" in line for line in game.log) == 2


def test_w1g8_suppress_cast_on_that_players_own_turn_waits_for_their_next_one(set_pool):
    """"That player's **next** turn": aimed at myself in my own main phase,
    this turn's end step is not the one named, and neither is my opponent's —
    the cards come back a full round later."""
    game = _w1g8_duel(set_pool, hand=["Suppress", "Terror", "Island"])
    _w1g8_suppress_turn(game)

    assert game.queue_from_hand(0, "Suppress", target_player_index=0).supported
    _w1g8_settle(game)
    assert game.players[0].hand == []

    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert game.players[0].hand == [], "this turn is not my next turn"
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)
    assert game.players[0].hand == [], "nor is my opponent's turn"
    game.start_next_turn()
    assert game.active_player_index == 0
    game.resolve_end_step(0)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[0].hand)) == ["Forest", "Island", "Terror"]
    assert game.players[0].exile == []


def test_w1g8_suppress_returns_only_what_is_still_exiled(set_pool):
    """CR 608.2: as much as possible. A card something else took out of exile
    in between is not conjured back, and an empty hand arms a trigger that
    returns nothing."""
    game = _w1g8_duel(set_pool, hand=["Suppress"], opp_hand=["Terror", "Counterspell"])
    _w1g8_suppress_turn(game)
    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    terror = _w1g8_card(set_pool, "Terror")
    assert game.take_card_from_exile(game.players[1], terror)
    game.put_card_into_graveyard(game.players[1], terror)

    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[1].hand)) == ["Counterspell", "Forest"]
    assert _w1g8_names(game.players[1].graveyard) == ["Terror"]

    game = _w1g8_duel(set_pool, hand=["Suppress"])
    _w1g8_suppress_turn(game)
    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest"]
    assert any("no exiled cards to put back" in line for line in game.log)


@_w1g8_pytest.mark.parametrize("text", [
    # "Those cards" with no step in front that exiled a pile names nothing.
    "At the beginning of the end step of that player's next turn, that player "
    "returns those cards to their hand.",
    # One hand and every player: the actor and the owner are one claim.
    "Each player exiles all cards from your hand face down.",
    # A pick is owed by the seat that makes it; a named seat takes the hand.
    "Target player exiles any number of cards from their hand face down.",
])
def test_w1g8_a_hand_exile_the_handlers_cannot_perform_is_refused(text):
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
    )
    assert not _w1g8_compile(probe).supported


# --- Last Caress (driven) ---------------------------------------------------------


def test_w1g8_last_caress_drains_one_and_draws(set_pool):
    """"Target player loses 1 life and you gain 1 life. / Draw a card." Three
    things for three mana, on the opponent or on oneself."""
    game = _w1g8_duel(set_pool, hand=["Last Caress"], library=["Swamp"] * 5)
    spec = game.cast_target_spec(0, _w1g8_card(set_pool, "Last Caress"))
    assert spec["requires_target"] and [t["seat"] for t in spec["valid_targets"]] == [0, 1]

    assert game.queue_from_hand(0, "Last Caress", target_player_index=1).supported
    _w1g8_settle(game)

    assert (game.players[0].life, game.players[1].life) == (21, 19)
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]

    game = _w1g8_duel(set_pool, hand=["Last Caress"], library=["Swamp"] * 5)
    assert game.queue_from_hand(0, "Last Caress", target_player_index=0).supported
    _w1g8_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]


@_w1g8_pytest.mark.slow
def test_w1g8_the_ai_plays_the_hand_spells_through_whole_games():
    """The three sorceries, Dodecapod and Haunted Angel pinned into both decks
    of six simulated games: each is cast and resolves, none is refused, and no
    step ends owing a prompt one of them armed. (APC is a measured set, so
    other cards' unsupported casts are in the report; only these lines are
    read.)"""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = [
        "Mind Extraction", "Gerrard's Verdict", "Suppress", "Dodecapod",
        "Haunted Angel",
    ]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )

    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, sorted(cast)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if any(n in i.message for n in names)] == []
    w1g8_nothing_left_owing = not report.steps_left_owing
    assert w1g8_nothing_left_owing, report.steps_left_owing

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
