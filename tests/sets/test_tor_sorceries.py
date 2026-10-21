"""Torment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

import pytest as _w1g8_pytest

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_eddy_table(set_pool, *, lands=True):
    """Churning Eddy in seat 0's hand; a Grizzly Bears and a Forest for
    seat 1, a Hill Giant and an Island for seat 0."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Churning Eddy"]]),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    placed = {}
    for seat, key, name in (
        (1, "bears", "Grizzly Bears"), (0, "giant", "Hill Giant"),
        (1, "forest", "Forest"), (0, "island", "Island"),
    ):
        if not lands and key in ("forest", "island"):
            continue
        placed[key] = _W1G8Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, placed[key], None)
    return game, placed


def test_w1g8_churning_eddy_returns_a_creature_and_a_land_on_two_boards(set_pool):
    """"Return target creature and target land to their owners' hands." It
    refused at the parse ("no spell picks two targets from one verb"): two
    targets of one verb are one announcement (CR 601.2c), described as ordered
    roles the way Fumarole's destroy is. The two need not sit on one
    battlefield, and each goes to its own owner's hand (CR 400.3)."""
    game, placed = _w1g8_eddy_table(set_pool)
    assert _w1g8_compile(set_pool("TOR")["Churning Eddy"]).supported

    spec = game.cast_target_spec(0, set_pool("TOR")["Churning Eddy"])
    assert [role["kind"] for role in spec["roles"]] == ["creature", "land"]
    assert sorted(o["name"] for o in spec["valid_targets"]) == [
        "Grizzly Bears", "Hill Giant",
    ], "the creature slot offers creatures and nothing else"

    result = game.cast_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["island"].permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert game.is_on_battlefield(placed["giant"])
    assert game.is_on_battlefield(placed["forest"])


def test_w1g8_churning_eddy_needs_both_targets_to_be_cast(set_pool):
    """Every target is chosen as part of one announcement: with no land on the
    battlefield there is no legal announcement, and the spell is not cast
    (CR 601.2c) — not cast and half-resolved."""
    game, placed = _w1g8_eddy_table(set_pool, lands=False)
    refused = game.cast_from_hand(
        0, "Churning Eddy", target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Churning Eddy"]
    assert game.is_on_battlefield(placed["bears"])


def test_w1g8_churning_eddy_still_returns_the_target_that_is_left(set_pool):
    """CR 608.2b: one illegal target of two leaves the other to be returned —
    and the departed slot is not filled by whatever slid into its place."""
    game, placed = _w1g8_eddy_table(set_pool)
    result = game.queue_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["forest"].permanent_id],
    )
    assert result.supported, result.details
    game.remove_from_battlefield(placed["bears"])
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Forest"]
    assert game.is_on_battlefield(placed["giant"]), "not a stand-in for the Bears"
    assert game.is_on_battlefield(placed["island"])


def _w1g8_evolution_table(set_pool):
    """Parallel Evolution in seat 0's hand. Seat 0 controls a Saproling token
    and a nontoken Grizzly Bears; seat 1 controls a token copy of a Hill
    Giant (a copy effect of its own, CR 707.2) and nothing else."""
    from engine.tokens import make_token_card

    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Parallel Evolution"]]),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    saproling = _W1G8Permanent(card=make_token_card(
        "Saproling", 1, 1, "Creature — Saproling", colors=("G",),
    ), metadata={"is_token": True})
    game._put_permanent_onto_battlefield(0, saproling, None)
    bears = _W1G8Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    giant = _W1G8Permanent(card=lea["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    giant_token = game.create_token_copy(1, giant)
    game.remove_from_battlefield(giant)
    return game, saproling, bears, giant_token


def _w1g8_tokens(game, seat):
    return sorted(
        (p.effective_card.name, p.effective_power, p.effective_toughness)
        for p in game.controlled_by(seat) if p.metadata.get("is_token")
    )


def test_w1g8_parallel_evolution_copies_each_token_for_its_controller(set_pool):
    """"For each creature token on the battlefield, its controller creates a
    token that's a copy of that creature." It refused in lowering ("that
    creature" with nothing in this effect that chose one): inside a loop over
    the board, "that creature" is the permanent the iteration is on and "its
    controller" is that permanent's controller. Each side doubles its own
    tokens; a nontoken creature is not copied; and the set is fixed when the
    loop starts, so the copies made are not themselves copied."""
    game, saproling, bears, giant_token = _w1g8_evolution_table(set_pool)
    result = game.cast_from_hand(0, "Parallel Evolution")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)

    assert _w1g8_tokens(game, 0) == [("Saproling", 1, 1)] * 2
    assert _w1g8_tokens(game, 1) == [("Hill Giant", 3, 3)] * 2, (
        "a copy of a token copy copies what that token copies (CR 707.2)"
    )
    assert [p.card.name for p in game.controlled_by(0) if not p.metadata.get("is_token")] == [
        "Grizzly Bears"
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Parallel Evolution"]


def test_w1g8_parallel_evolution_flashes_back_and_doubles_again(set_pool):
    """Its flashback line reads (CR 702.34): cast again from the graveyard it
    doubles the doubled board, and is exiled as it leaves the stack."""
    game, _saproling, _bears, _giant_token = _w1g8_evolution_table(set_pool)
    game.cast_from_hand(0, "Parallel Evolution")
    _w1g8_resolve_stack(game)
    again = game.cast_from_hand(0, "Parallel Evolution", from_zone="graveyard")
    assert again.supported, again.details
    _w1g8_resolve_stack(game)

    assert len(_w1g8_tokens(game, 0)) == 4
    assert len(_w1g8_tokens(game, 1)) == 4
    assert [c.name for c in game.players[0].exile] == ["Parallel Evolution"]
    assert not game.players[0].graveyard


def _w1g8_retraced_table(set_pool, hand, *, mine=(), theirs=(), humans=(0,)):
    """Retraced Image plus *hand* in seat 0's hand; the named permanents on
    each side."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player(
            "A", hand=[set_pool("TOR")["Retraced Image"]] + [lea[n] for n in hand],
        ),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    game.start_turn(0)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, _W1G8Permanent(card=lea[name]), None)
    result = game.cast_from_hand(0, "Retraced Image")
    assert result.supported, result.details
    return game


def _w1g8_reveal(game, name):
    (asked,) = game.pending_choices
    assert asked.kind == "choose_cards_in_hand" and asked.data["count"] == 1
    slot = [c.name for c in game.players[0].hand].index(name)
    assert game.confirm_choose_cards_in_hand(0, [slot])
    _w1g8_resolve_stack(game)


def test_w1g8_retraced_image_puts_a_namesake_onto_the_battlefield(set_pool):
    """"Reveal a card in your hand, then put that card onto the battlefield if
    it has the same name as a permanent." It refused at the parse: the trailing
    "if" is part of the clause after the "then" — the reveal happens either
    way — and "it has the same name as a permanent" names the revealed card.
    The caster is asked which card to reveal (a hand picker), and "a
    permanent" is any permanent: here the opponent's."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    _w1g8_reveal(game, "Grizzly Bears")

    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert "A revealed Grizzly Bears (Retraced Image)" in game.log


def test_w1g8_retraced_image_reveals_and_keeps_a_card_with_no_namesake(set_pool):
    """No permanent shares the revealed card's name: it is revealed and stays
    in hand — the reveal is not conditional, only the put is."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Grizzly Bears"], mine=["Hill Giant"],
    )
    _w1g8_reveal(game, "Island")

    assert [p.card.name for p in game.controlled_by(0)] == ["Hill Giant"]
    assert sorted(c.name for c in game.players[0].hand) == ["Grizzly Bears", "Island"]
    assert "A revealed Island (Retraced Image)" in game.log


def test_w1g8_retraced_image_never_puts_an_instant_onto_the_battlefield(set_pool):
    """CR 400.4a: an instant card that would enter the battlefield stays where
    it was. A token can carry any name, so "the same name as a permanent" can
    hold for a revealed Lightning Bolt — and the Bolt stays in hand."""
    from engine.tokens import make_token_card

    game = _w1g8_retraced_table(set_pool, ["Lightning Bolt"], humans=(0,))
    namesake = _W1G8Permanent(card=make_token_card(
        "Lightning Bolt", 1, 1, "Creature — Elemental",
    ), metadata={"is_token": True})
    game._put_permanent_onto_battlefield(1, namesake, None)
    _w1g8_reveal(game, "Lightning Bolt")

    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt"]
    assert not list(game.controlled_by(0))
    assert any("400.4a" in line for line in game.log)


def test_w1g8_retraced_image_a_seat_nobody_asks_reveals_the_namesake(set_pool):
    """The stated default reveals the first card in hand order; a pick the
    next sentence turns into a free permanent (``hand_pick_entry_consumer``)
    is ordered first — and here, only a pick the guarding "if it has the same
    name as a permanent" admits enters at all, so that one goes first."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Hill Giant", "Grizzly Bears"],
        mine=["Grizzly Bears"], humans=(),
    )
    _w1g8_resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Grizzly Bears",
    ]
    assert sorted(c.name for c in game.players[0].hand) == ["Hill Giant", "Island"]


@_w1g8_pytest.mark.parametrize("namesake", [False, True])
def test_w1g8_the_ai_casts_retraced_image_only_over_a_namesake(set_pool, namesake):
    """An AI seat holding no card a permanent shares a name with would spend
    Retraced Image on a reveal: the rehearsal reads the reveal as a change
    worth nothing and proposed it. The hand-pick gate the AI asks before the
    cast (Stronghold Gambit's) now reads the guard around the entering step
    too, so the card is held until something in hand would enter."""
    from engine.ai_policy import choose_cast_action

    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Retraced Image"], lea["Hill Giant"]],
                    library=[lea["Island"]] * 5),
        _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = True
    game.start_turn(0)
    game._close_current_priority_step()
    game._put_permanent_onto_battlefield(0, _W1G8Permanent(card=lea["Island"]), None)
    if namesake:
        game._put_permanent_onto_battlefield(1, _W1G8Permanent(card=lea["Hill Giant"]), None)

    action = choose_cast_action(game, 0)
    assert (action is not None and action.card_name == "Retraced Image") is namesake

# ==== end W1G8 ======================================================
