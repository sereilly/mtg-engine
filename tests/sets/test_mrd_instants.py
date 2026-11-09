"""Mirrodin instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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
#
# Entwine (CR 702.42): "You may choose all modes of this spell instead of
# just the number specified. If you do, you pay an additional [cost]." An
# entwined cast pays its entwine offer (``optional_cost_payments``) and names
# every mode with its own targets (``mode_choices``); 702.42b resolves them in
# printed order.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), graveyard=(),
                interactive=(), active=0):
    """Seat 0 (A) to act in *active*'s first main phase, mana off unless a
    test turns it on; each named permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
            graveyard=[card(n) for n in graveyard],
        ),
        _w1g4_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(active)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g4_dreams_grip_entwined_taps_one_permanent_and_untaps_another(set_pool):
    """Both modes, each at its own target, for {U} and the entwine's {1}."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Dream's Grip"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    game.enforce_mana_costs = True
    mine[0].tapped = True
    game.players[0].mana_pool["U"] = 2
    result = game.cast_from_hand(
        0, "Dream's Grip", optional_cost_payments={"{1}": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 1, "target_player_index": 0, "target_permanent_index": 0},
        ],
    )
    assert result.supported, result.details
    assert theirs[0].tapped and not mine[0].tapped, game.log
    assert game.players[0].mana_pool["U"] == 0, "the entwine's {1} was paid"


def test_w1g4_dreams_grip_entwine_unpaid_or_short_is_refused(set_pool):
    """CR 702.42a ties the two halves together: every mode without the cost is
    refused, the cost with one mode is refused, and a pool holding {U} alone
    cannot pay the entwine."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Dream's Grip"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    both = [
        {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
        {"index": 1, "target_player_index": 0, "target_permanent_index": 0},
    ]
    unpaid = game.cast_from_hand(0, "Dream's Grip", mode_choices=both)
    assert not unpaid.supported and "entwine" in unpaid.details
    one = game.cast_from_hand(
        0, "Dream's Grip", optional_cost_payments={"{1}": 1}, mode_choices=both[:1],
    )
    assert not one.supported and "every mode" in one.details
    game.enforce_mana_costs = True
    game.players[0].mana_pool["U"] = 1
    short = game.cast_from_hand(
        0, "Dream's Grip", optional_cost_payments={"{1}": 1}, mode_choices=both,
    )
    assert not short.supported
    assert not theirs[0].tapped
    assert [c.name for c in game.players[0].hand] == ["Dream's Grip"]


def test_w1g4_betrayal_of_flesh_entwined_sacrifices_three_lands(set_pool):
    """"Entwine—Sacrifice three lands.": both modes, the creature destroyed and
    the named creature card back, three lands gone; with two lands the cost
    cannot be paid and nothing happens."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Betrayal of Flesh"], mine=["Swamp"] * 4, theirs=["Grizzly Bears"],
        graveyard=["Hill Giant", "Craw Wurm"],
    )
    result = game.cast_from_hand(
        0, "Betrayal of Flesh", optional_cost_payments={"sacrifice three lands": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 1, "target_player_index": 0, "target_permanent_index": 1},
        ],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(theirs[0]), game.log
    board = [p.card.name for p in game.players[0].battlefield]
    assert board.count("Swamp") == 1 and "Craw Wurm" in board, board
    assert "Hill Giant" in [c.name for c in game.players[0].graveyard]

    game, _mine, theirs = _w1g4_table(
        set_pool, ["Betrayal of Flesh"], mine=["Swamp"] * 2, theirs=["Grizzly Bears"],
        graveyard=["Hill Giant"],
    )
    refused = game.cast_from_hand(
        0, "Betrayal of Flesh", optional_cost_payments={"sacrifice three lands": 1},
    )
    assert not refused.supported
    assert game.is_on_battlefield(theirs[0])
    assert [p.card.name for p in game.players[0].battlefield] == ["Swamp", "Swamp"]


def test_w1g4_betrayal_of_flesh_entwined_keeps_its_creature_when_the_card_leaves(set_pool):
    """CR 608.2b per mode: the graveyard card named for the second mode leaves
    in response, so that mode does nothing — no other card comes back in its
    place — and the first mode's still-legal target is destroyed."""
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Betrayal of Flesh"], mine=["Swamp"] * 3, theirs=["Grizzly Bears"],
        graveyard=["Hill Giant", "Craw Wurm"],
    )
    queued = game.queue_from_hand(
        0, "Betrayal of Flesh", optional_cost_payments={"sacrifice three lands": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 1, "target_player_index": 0, "target_permanent_index": 1},
        ],
    )
    assert queued.supported, queued.details
    graveyard = game.players[0].graveyard
    wurm = next(c for c in graveyard if c.name == "Craw Wurm")
    graveyard.remove(wurm)
    game.players[0].exile.append(wurm)
    _w1g4_resolve_stack(game)
    assert not game.is_on_battlefield(theirs[0]), game.log
    assert not game.players[0].battlefield, "a card nobody named came back"
    assert "Hill Giant" in [c.name for c in graveyard]


def test_w1g4_blinding_beam_entwined_holds_the_players_next_untap_step(set_pool):
    """Two creatures tapped, and "Creatures don't untap during target player's
    next untap step" — a lock on the step, so a creature that arrives after
    the spell resolved stays tapped too (CR 611.2c; the 2013-06-07 ruling).
    The step after that untaps them."""
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Blinding Beam"], theirs=["Grizzly Bears", "Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Blinding Beam", optional_cost_payments={"{1}": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": [0, 1]},
            {"index": 1, "target_player_index": 1},
        ],
    )
    assert result.supported, result.details
    assert all(p.tapped for p in theirs), game.log
    late = _w1g4_Permanent(card=_w1g4_card(set_pool, "Craw Wurm"))
    game._put_permanent_onto_battlefield(1, late, None)
    late.tapped = True
    game.start_turn(1)
    assert all(p.tapped for p in (*theirs, late)), game.log
    game.start_turn(0)
    game.start_turn(1)
    assert not any(p.tapped for p in (*theirs, late)), game.log


def test_w1g4_blinding_beam_second_mode_alone_names_a_player(set_pool):
    """The untap-lock mode on its own: the caster's creatures untap as usual
    on its own step, and only the named player's step is held."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Blinding Beam"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    theirs[0].tapped = True
    mine[0].tapped = True
    result = game.cast_from_hand(0, "Blinding Beam", mode_index=1, target_player_index=1)
    assert result.supported, result.details
    game.start_turn(1)
    assert theirs[0].tapped
    game.start_turn(0)
    assert not mine[0].tapped


def test_w1g4_grab_the_reins_entwined_sacrifices_the_creature_it_stole(set_pool):
    """The ruling (2004-12-01): "If you pay the entwine cost, you can sacrifice
    the creature you gain control of." Steal first (printed order, CR 702.42b),
    then the sacrifice is chosen at resolution — here the stolen Hill Giant —
    and its power is dealt to the target named at announcement."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Grab the Reins"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
        interactive=(0,),
    )
    queued = game.queue_from_hand(
        0, "Grab the Reins", optional_cost_payments={"{2}{R}": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 1, "target_player_index": 1},
        ],
    )
    assert queued.supported, queued.details
    game.resolve_top_of_stack()
    assert game.controller_index_of(theirs[0]) == 0
    assert game._has_keyword(theirs[0], "haste"), "it gains haste"
    assert [c.kind for c in game.pending_choices] == ["sacrifice"]
    assert game.confirm_sacrifice(0, permanent_ids=[theirs[0].permanent_id])
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17, game.log
    assert game.is_on_battlefield(mine[0])
    assert "Hill Giant" in [c.name for c in game.players[1].graveyard]


def test_w1g4_grab_the_reins_steal_mode_grants_the_haste_it_prints(set_pool):
    """"…you gain control of target creature **and it gains haste**": the
    pronoun is the stolen creature, not the spell — it lowered to the spell's
    own source and the creature had no haste."""
    game, _mine, theirs = _w1g4_table(set_pool, ["Grab the Reins"], theirs=["Hill Giant"])
    result = game.cast_from_hand(
        0, "Grab the Reins", mode_index=0, target_player_index=1,
        target_permanent_ids=[theirs[0].permanent_id],
    )
    assert result.supported, result.details
    assert game.controller_index_of(theirs[0]) == 0
    assert game._has_keyword(theirs[0], "haste"), game.log


def test_w1g4_incite_war_entwined(set_pool):
    """The named player's creatures must attack this turn, and the caster's
    gain first strike: cast in the opponent's turn, where it matters."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Incite War"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
        active=1,
    )
    result = game.cast_from_hand(
        0, "Incite War", optional_cost_payments={"{2}": 1},
        mode_choices=[{"index": 0, "target_player_index": 1}, {"index": 1}],
    )
    assert result.supported, result.details
    assert game._must_attack_if_able(theirs[0]), game.log
    assert game._has_keyword(mine[0], "first strike")
    assert not game._has_keyword(theirs[0], "first strike")


def test_w1g4_roar_of_the_kha_entwined_pumps_and_untaps(set_pool):
    game, mine, _theirs = _w1g4_table(
        set_pool, ["Roar of the Kha"], mine=["Grizzly Bears", "Grizzly Bears"],
    )
    mine[0].tapped = True
    result = game.cast_from_hand(0, "Roar of the Kha", optional_cost_payments={"{1}{W}": 1})
    assert result.supported, result.details
    assert not mine[0].tapped
    assert [(p.effective_power, p.effective_toughness) for p in mine] == [(3, 3), (3, 3)]


def test_w1g4_wail_of_the_nim_entwined_regenerates_then_deals_damage(set_pool):
    """Printed order: the caster's creatures are shielded first, so the 1
    damage to each creature kills only the opponent's 1/1 (CR 701.19a)."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Wail of the Nim"], mine=["Llanowar Elves"], theirs=["Llanowar Elves"],
    )
    result = game.cast_from_hand(0, "Wail of the Nim", optional_cost_payments={"{B}": 1})
    assert result.supported, result.details
    _w1g4_resolve_stack(game)
    assert game.is_on_battlefield(mine[0]) and mine[0].tapped, game.log
    assert not game.is_on_battlefield(theirs[0])
    assert [p.life for p in game.players] == [19, 19]


def test_w1g4_wail_of_the_nim_first_mode_shields_only_the_casters_creatures(set_pool):
    game, mine, theirs = _w1g4_table(
        set_pool, ["Wail of the Nim"], mine=["Llanowar Elves"], theirs=["Llanowar Elves"],
    )
    result = game.cast_from_hand(0, "Wail of the Nim", mode_index=0)
    assert result.supported, result.details
    assert mine[0].regeneration_shield == 1
    assert theirs[0].regeneration_shield == 0

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
