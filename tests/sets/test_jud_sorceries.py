"""Judgment sorceries.

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
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import _nosick as _w1g8_nosick
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_duel() -> "_w1g8_Game":
    """Two seats, mana costs waived, seat 0's turn started for real."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g8_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


def _w1g8_therapy_victim(set_pool, game) -> None:
    lea = set_pool("LEA")
    game.players[1].hand.extend([
        lea["Lightning Bolt"], lea["Lightning Bolt"], lea["Forest"],
        lea["Grizzly Bears"],
    ])


# --- Cabal Therapy --------------------------------------------------------

def test_w1g8_cabal_therapy_discards_every_card_with_the_chosen_name(set_pool):
    """"Choose a nonland card name. Target player reveals their hand and
    discards all cards with that name." Ruling 2016-06-08: the name is chosen
    as Cabal Therapy resolves, and nothing happens between the naming and the
    discard — the resolution waits on the name, then reveals and discards."""
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    assert game.queue_from_hand(0, "Cabal Therapy", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    owed = game.pending_choices_of("choose_card_name")
    assert [choice.player_index for choice in owed] == [0]
    assert _w1g8_names(game.players[1].hand) == [
        "Forest", "Grizzly Bears", "Lightning Bolt", "Lightning Bolt",
    ]
    assert game.confirm_choose_card_name(0, "Lightning Bolt")
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Grizzly Bears"]
    assert _w1g8_names(game.players[1].graveyard) == ["Lightning Bolt", "Lightning Bolt"]
    assert _w1g8_names(game.players[0].graveyard) == ["Cabal Therapy"]
    assert "P1 named Lightning Bolt" in game.log


def test_w1g8_cabal_therapy_refuses_a_land_name(set_pool):
    """"…a **nonland** card name": a land's name is refused with the prompt
    kept (the answer check the Meddling Mage entry choice already asks), and
    the default a non-interactive seat takes obeys the bound too."""
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    lea = set_pool("LEA")
    # What the caster can see of the target: a graveyard of Forests and one
    # Bolt. The commonest *nonland* name there is the Bolt.
    game.players[1].graveyard.extend([lea["Forest"], lea["Forest"], lea["Lightning Bolt"]])
    assert game.queue_from_hand(0, "Cabal Therapy", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert not game.confirm_choose_card_name(0, "Forest")
    (choice,) = game.pending_choices_of("choose_card_name")
    assert choice.data["excluded_card_type"] == "land"
    assert choice.data["default_name"] == "Lightning Bolt"
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Grizzly Bears"]


def test_w1g8_cabal_therapy_flashes_back_by_sacrificing_a_creature(set_pool):
    """"Flashback—Sacrifice a creature." Cast from the graveyard, the creature
    is the price (CR 702.34a, CR 118.9), the spell does what it does from a
    hand, and it is exiled afterwards."""
    game = _w1g8_duel()
    therapy = set_pool("JUD")["Cabal Therapy"]
    game.players[0].graveyard.append(therapy)
    bears = _w1g8_nosick(_w1g8_Permanent(card=set_pool("LEA")["Grizzly Bears"]))
    game.players[0].battlefield.append(bears)
    _w1g8_therapy_victim(set_pool, game)
    assert game.queue_from_hand(
        0, "Cabal Therapy", from_zone="graveyard", target_player_index=1,
    ).supported
    assert game.stack[-1].flashback
    assert not any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    _w1g8_resolve_stack(game)
    assert game.confirm_choose_card_name(0, "Grizzly Bears")
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Lightning Bolt", "Lightning Bolt"]
    assert _w1g8_names(game.players[0].exile) == ["Cabal Therapy"]
    assert _w1g8_names(game.players[0].graveyard) == ["Grizzly Bears"]


def test_w1g8_cabal_therapy_without_a_creature_cannot_be_flashed_back(set_pool):
    """CR 601.2h: no creature to sacrifice is a flashback cost that cannot be
    paid, and the card stays in the graveyard."""
    game = _w1g8_duel()
    game.players[0].graveyard.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    refused = game.cast_from_hand(
        0, "Cabal Therapy", from_zone="graveyard", target_player_index=1,
    )
    assert not refused.supported
    assert _w1g8_names(game.players[0].graveyard) == ["Cabal Therapy"]
    assert len(game.players[1].hand) == 4


# --- Firecat Blitz --------------------------------------------------------

def _w1g8_blitz_board(set_pool, mountains: int) -> "tuple[_w1g8_Game, list]":
    """Seat 0: Firecat Blitz in its graveyard, *mountains* Mountains and a
    Forest on the battlefield, exactly {R}{R} floating — costs enforced."""
    lea = set_pool("LEA")
    game = _w1g8_duel()
    game.enforce_mana_costs = True
    player = game.players[0]
    player.graveyard.append(set_pool("JUD")["Firecat Blitz"])
    lands = [_w1g8_nosick(_w1g8_Permanent(card=lea["Mountain"])) for _ in range(mountains)]
    player.battlefield.extend(lands + [_w1g8_nosick(_w1g8_Permanent(card=lea["Forest"]))])
    player.mana_pool["R"] = 2
    return game, lands


def _w1g8_board_names(game, seat: int) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g8_firecat_blitz_flashes_back_sacrificing_x_mountains(set_pool):
    """"Flashback—{R}{R}, Sacrifice X Mountains." The X announced with the cast
    sizes the sacrifice and the tokens alike (CR 107.3a): the two Mountains the
    caster named go, the third stays, and two hasty 1/1 Elemental Cats are
    exiled at the beginning of the next end step."""
    game, lands = _w1g8_blitz_board(set_pool, 3)
    spec = game.cast_target_spec(0, set_pool("JUD")["Firecat Blitz"], from_zone="graveyard")
    assert spec["announces_x"] and spec["max_x"] == 3
    named = [lands[0].permanent_id, lands[2].permanent_id]
    cast = game.cast_from_hand(
        0, "Firecat Blitz", from_zone="graveyard", x_value=2,
        alternative_cost_permanent_ids=named,
    )
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert any(p is lands[1] for p in game.controlled_by(0))
    assert _w1g8_board_names(game, 0) == [
        "Elemental Cat Token", "Elemental Cat Token", "Forest", "Mountain",
    ]
    cats = [p for p in game.controlled_by(0) if p.card.name == "Elemental Cat Token"]
    assert all(game._has_keyword(cat, "haste") for cat in cats)
    assert _w1g8_names(game.players[0].graveyard) == ["Mountain", "Mountain"]
    assert _w1g8_names(game.players[0].exile) == ["Firecat Blitz"]
    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain"]


def test_w1g8_firecat_blitz_cannot_sacrifice_more_mountains_than_it_has(set_pool):
    """CR 601.2h: three Mountains are no payment for an X of four, and naming
    one Mountain for an X of two is a partial payment — both refused with
    nothing spent and the card still in the graveyard."""
    game, lands = _w1g8_blitz_board(set_pool, 3)
    refused = game.cast_from_hand(0, "Firecat Blitz", from_zone="graveyard", x_value=4)
    assert not refused.supported and "flashback cost" in refused.details
    refused = game.cast_from_hand(
        0, "Firecat Blitz", from_zone="graveyard", x_value=2,
        alternative_cost_permanent_ids=[lands[0].permanent_id],
    )
    assert not refused.supported
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain", "Mountain", "Mountain"]
    assert game.players[0].mana_pool["R"] == 2
    assert _w1g8_names(game.players[0].graveyard) == ["Firecat Blitz"]


def test_w1g8_firecat_blitz_flashed_back_with_no_x_announced_sacrifices_nothing(set_pool):
    """The flashback's X is paid in Mountains, not mana, so mana floating says
    nothing about it: with {R}{R}{R}{R} in the pool and no X announced, the cast
    is X = 0 — no Mountain is sacrificed and no cat made — rather than an X
    inferred from the pool and charged in lands nobody named."""
    game, _lands = _w1g8_blitz_board(set_pool, 3)
    game.players[0].mana_pool["R"] = 4
    cast = game.cast_from_hand(0, "Firecat Blitz", from_zone="graveyard")
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain", "Mountain", "Mountain"]
    assert game.players[0].mana_pool["R"] == 2
    assert _w1g8_names(game.players[0].exile) == ["Firecat Blitz"]


def test_w1g8_firecat_blitz_from_hand_makes_x_cats_and_sacrifices_nothing(set_pool):
    """Cast from a hand for {X}{R}{R}: X cats, no Mountain sacrificed."""
    game, _lands = _w1g8_blitz_board(set_pool, 2)
    game.enforce_mana_costs = False
    blitz = game.players[0].graveyard.pop()
    game.players[0].hand.append(blitz)
    assert game.cast_from_hand(0, "Firecat Blitz", x_value=3).supported
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0).count("Elemental Cat Token") == 3
    assert _w1g8_board_names(game, 0).count("Mountain") == 2
    assert _w1g8_names(game.players[0].graveyard) == ["Firecat Blitz"]

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
