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

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


@_w1g2_pytest.mark.parametrize(
    ("graveyard", "survives", "damage", "counters"),
    [(0, True, 0, 2), (7, False, 6, 2)],
    ids=["four-damage-prevented", "threshold-six-unpreventable"],
)
def test_w1g2_lightning_surge_against_a_phantom(
    set_pool, catalog_by_name, graveyard, survives, damage, counters,
):
    """Lightning Surge, from the drive list, against Phantom Centaur (3
    counters, 2/0). Without threshold its 4 damage is prevented for a counter.
    With seven cards in its caster's graveyard it deals 6 "and the damage can't
    be prevented": the 6 is marked, and the Phantom still pays its counter
    (2022-12-08: "the damage is dealt and a +1/+1 counter is removed",
    CR 615.12) — so a 4/1 takes 6 and dies."""
    jud = set_pool("JUD")
    island = catalog_by_name["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", library=[island] * 5),
        _W1G2PlayerState(name="Bob", library=[island] * 5,
                         graveyard=[island] * graveyard),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.current_turn_phase = "main1"
    centaur = _W1G2Permanent(card=jud["Phantom Centaur"])
    game._put_permanent_onto_battlefield(0, centaur, None)
    _w1g2_resolve_stack(game)
    game.players[1].hand.append(jud["Lightning Surge"])
    result = game.cast_from_hand(
        1, "Lightning Surge", target_player_index=0,
        target_permanent_ids=[centaur.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    damage_marked = centaur.damage_marked
    game._settle()

    assert game.is_on_battlefield(centaur) is survives
    assert damage_marked == damage
    assert int(centaur.metadata.get("plus_counters", 0)) == counters

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Rats' Feast (supported on arrival, driven here): "Exile X target cards from a
# single graveyard." The X cards are targets announced with the spell
# (CR 601.2c), all in one pile, and a card gone in response is not replaced
# (CR 608.2b).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.stack_targets import chosen_targets as _w1g3_chosen_targets
from tests.helpers import resolve_stack as _w1g3_resolve

_W1G3_THEIRS = ("Swamp", "Hill Giant", "Terror", "Craw Wurm")


def _w1g3_feast_game(set_pool):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Rats' Feast"]], graveyard=[lea["Grizzly Bears"]],
            library=[lea["Swamp"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in _W1G3_THEIRS],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_rats_feast_names_x_cards_of_one_pile_and_does_not_replace_a_lost_one(set_pool):
    game = _w1g3_feast_game(set_pool)
    spec = game.cast_target_spec(0, set_pool("JUD")["Rats' Feast"])
    assert spec["single_graveyard"] and spec["x_targets"]
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}

    assert game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1, 3],
    ).supported
    named = _w1g3_chosen_targets(game, game.stack[-1])
    assert [(t.stamp.seat, t.stamp.card.name) for t in named] == [
        (1, "Hill Giant"), (1, "Craw Wurm"),
    ]
    victim = game.players[1]
    victim.hand.append(victim.graveyard.pop(1))            # the Giant, in response
    _w1g3_resolve(game)

    assert [c.name for c in victim.exile] == ["Craw Wurm"]
    assert [c.name for c in victim.graveyard] == ["Swamp", "Terror"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Rats' Feast"]


def test_w1g3_rats_feast_names_exactly_x_and_x_zero_names_none(set_pool):
    game = _w1g3_feast_game(set_pool)
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1],
    ).supported
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=1, target_player_index=1, target_permanent_index=[1, 2],
    ).supported
    assert game.stack == []
    assert game.queue_from_hand(0, "Rats' Feast", x_value=0).supported
    _w1g3_resolve(game)
    assert game.players[1].exile == [] and len(game.players[1].graveyard) == 4

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
#
# Threshold "instead" sorceries: the second paragraph replaces the first when
# seven or more cards are in the caster's graveyard as the spell resolves
# (CR 608.2c), and exactly one of the two ever happens.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.targeting import derive_cast_spec as _w1g7_derive_cast_spec
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_table(set_pool, catalog_by_name, graveyard=()):
    """Two seats; seat 0's graveyard holds *graveyard* (card names), mana off."""
    jud = set_pool("JUD")

    def card(name):
        return jud[name] if name in jud else catalog_by_name[name]

    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="Alice", library=[island] * 10,
                         graveyard=[card(name) for name in graveyard]),
        _W1G7PlayerState(name="Bob", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g7_card = card
    return game


def _w1g7_bears(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Bear Token"]


@_w1g7_pytest.mark.parametrize(("others", "bears"), [(6, 2), (7, 4)])
def test_w1g7_grizzly_fate_makes_four_bears_only_at_threshold(
    set_pool, catalog_by_name, others, bears,
):
    """Two 2/2 green Bears, or four instead with seven cards in the graveyard
    — never six: the pair is one effect."""
    game = _w1g7_table(set_pool, catalog_by_name, ["Island"] * others)
    game.players[0].hand.append(game._w1g7_card("Grizzly Fate"))
    assert game.cast_from_hand(0, "Grizzly Fate").supported
    _w1g7_resolve_stack(game)

    made = _w1g7_bears(game, 0)
    assert len(made) == bears
    assert all(
        (p.effective_power, p.effective_toughness) == (2, 2) for p in made
    )
    assert _w1g7_bears(game, 1) == []
    assert [c.name for c in game.players[0].graveyard][-1] == "Grizzly Fate"


def test_w1g7_grizzly_fate_flashed_back_does_not_count_itself(
    set_pool, catalog_by_name,
):
    """Ruling 2013-04-15: "At the time this spell is resolving, it is on the
    stack and not in the graveyard. This means that you should not count this
    card when determining whether the Threshold effect occurs." Six other
    cards plus Grizzly Fate is seven before the flashback cast and six while it
    resolves: two Bears, and the card is exiled (CR 702.34a)."""
    game = _w1g7_table(
        set_pool, catalog_by_name, ["Island"] * 6 + ["Grizzly Fate"]
    )
    result = game.cast_from_hand(0, "Grizzly Fate", from_zone="graveyard")
    assert result.supported, result.details
    _w1g7_resolve_stack(game)

    assert len(_w1g7_bears(game, 0)) == 2
    assert [c.name for c in game.players[0].exile] == ["Grizzly Fate"]
    assert len(game.players[0].graveyard) == 6


@_w1g7_pytest.mark.parametrize(
    ("others", "to_hand", "to_battlefield"), [(4, True, False), (5, False, True)],
)
def test_w1g7_stitch_together_returns_to_hand_or_to_the_battlefield(
    set_pool, catalog_by_name, others, to_hand, to_battlefield,
):
    """The target creature card counts toward the seven: with it, a Hill Giant
    and four Islands (six) it goes to the hand, with five Islands (seven) it
    enters the battlefield instead — the one card the spell targeted either
    way, and never the Giant."""
    game = _w1g7_table(
        set_pool, catalog_by_name,
        ["Island"] * others + ["Hill Giant", "Grizzly Bears"],
    )
    caster = game.players[0]
    stitch = game._w1g7_card("Stitch Together")
    caster.hand.append(stitch)
    bears_slot = len(caster.graveyard) - 1
    offered = {t["name"] for t in game.cast_target_spec(0, stitch)["valid_targets"]}
    assert offered == {"Hill Giant", "Grizzly Bears"}
    assert game.cast_from_hand(
        0, "Stitch Together", target_player_index=0,
        target_permanent_index=bears_slot,
    ).supported
    _w1g7_resolve_stack(game)

    assert ("Grizzly Bears" in [c.name for c in caster.hand]) is to_hand
    on_board = [p.card.name for p in game.controlled_by(0)]
    assert ("Grizzly Bears" in on_board) is to_battlefield
    assert "Hill Giant" in [c.name for c in caster.graveyard]
    assert "Hill Giant" not in on_board


def test_w1g7_stitch_together_with_its_target_gone_does_nothing(
    set_pool, catalog_by_name,
):
    """CR 608.2b: its one target left the graveyard in response, so the spell
    does not resolve — no other creature card is returned in its place, by
    either arm."""
    game = _w1g7_table(
        set_pool, catalog_by_name, ["Island"] * 6 + ["Hill Giant", "Grizzly Bears"],
    )
    caster = game.players[0]
    caster.hand.append(game._w1g7_card("Stitch Together"))
    assert game.queue_from_hand(
        0, "Stitch Together", target_player_index=0,
        target_permanent_index=len(caster.graveyard) - 1,
    ).supported
    caster.exile.append(caster.graveyard.pop())     # the Bears, in response
    _w1g7_resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == []
    assert "Hill Giant" in [c.name for c in caster.graveyard]
    assert "Hill Giant" not in [c.name for c in caster.hand]


def test_w1g7_threshold_sorceries_pickers_name_what_the_cards_print(set_pool):
    """Stitch Together names a creature card in its caster's own graveyard;
    Grizzly Fate names nothing."""
    jud = set_pool("JUD")
    stitch, fate = jud["Stitch Together"], jud["Grizzly Fate"]
    assert _w1g7_derive_cast_spec(stitch, _w1g7_compile(stitch)) == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
    }
    assert _w1g7_derive_cast_spec(fate, _w1g7_compile(fate)) is None


@_w1g7_pytest.mark.parametrize(("others", "swept"), [(6, False), (7, True)])
def test_w1g7_swirling_sandstorm_needs_threshold_and_spares_fliers(
    set_pool, catalog_by_name, others, swept,
):
    """Drive list. Ruling 2004-10-04: "This card does nothing if you don't
    have seven cards in your graveyard when it resolves." With seven, 5 damage
    to each creature without flying — the caster's own Craw Wurm included —
    and the Suntail Hawk is untouched."""
    from engine.models import Permanent

    game = _w1g7_table(set_pool, catalog_by_name, ["Island"] * others)
    board = {}
    for seat, name in ((1, "Grizzly Bears"), (1, "Suntail Hawk"), (0, "Craw Wurm")):
        board[name] = Permanent(card=game._w1g7_card(name))
        game._put_permanent_onto_battlefield(seat, board[name], None)
    _w1g7_resolve_stack(game)
    game.players[0].hand.append(game._w1g7_card("Swirling Sandstorm"))
    assert game.cast_from_hand(0, "Swirling Sandstorm").supported
    _w1g7_resolve_stack(game)

    assert game.is_on_battlefield(board["Grizzly Bears"]) is not swept
    assert game.is_on_battlefield(board["Craw Wurm"]) is not swept
    assert game.is_on_battlefield(board["Suntail Hawk"])
    assert board["Suntail Hawk"].damage_marked == 0

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
