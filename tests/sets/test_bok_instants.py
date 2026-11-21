"""Betrayers of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# The five Shoals' pitch ("You may exile a <colour> card with mana value X
# from your hand rather than pay this spell's mana cost") and Disrupting
# Shoal's "Counter target spell if its mana value is X".

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ()), mana=True):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = mana
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_names(cards):
    return [card.name for card in cards]


def test_w1g2_blazing_shoal_pitch_reads_x_off_the_exiled_card(set_pool):
    """No land and no mana: Hill Giant ({3}{R}, mana value 4) is exiled for the
    pitch, nothing names X, and the Bears get +4/+0 — the exiled card's mana
    value is the X (CR 107.3a)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [bok["Blazing Shoal"], lea["Hill Giant"], lea["Lightning Bolt"]], (),
    ))
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    result = game.cast_from_hand(
        0, "Blazing Shoal", target_permanent_ids=[bears.permanent_id],
        alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 2), game.log
    assert _w1g2_names(game.players[0].exile) == ["Hill Giant"]
    assert _w1g2_names(game.players[0].hand) == ["Lightning Bolt"]


def test_w1g2_blazing_shoal_announced_x_holds_the_exiled_card_to_it(set_pool):
    """X announced as 1: Hill Giant (mana value 4) named for it is refused with
    nothing spent, and with no card named the 1-drop pays."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [bok["Blazing Shoal"], lea["Hill Giant"], lea["Lightning Bolt"]], (),
    ))
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    refused = game.cast_from_hand(
        0, "Blazing Shoal", target_permanent_ids=[bears.permanent_id],
        alternative_cost=True, alternative_cost_hand_index=1, x_value=1,
    )
    assert not refused.supported
    assert "with X = 1" in refused.details
    assert len(game.players[0].hand) == 3 and not game.stack
    result = game.cast_from_hand(
        0, "Blazing Shoal", target_permanent_ids=[bears.permanent_id],
        alternative_cost=True, x_value=1,
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_names(game.players[0].exile) == ["Lightning Bolt"]
    assert bears.effective_power == 3


def test_w1g2_nourishing_shoal_cannot_pitch_itself_or_another_colour(set_pool):
    """The spell is on the stack before its cost is paid (CR 601.2a), so a lone
    Shoal has nothing to exile; a blue card does not pay a green pitch; a
    second Nourishing Shoal (mana value 2: its {X} is 0 in hand, CR 202.3e)
    does, for 2 life."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=([bok["Nourishing Shoal"]], ()))
    assert not game.cast_from_hand(0, "Nourishing Shoal", alternative_cost=True).supported
    game = _w1g2_table(set_pool, hands=(
        [bok["Nourishing Shoal"], lea["Counterspell"]], (),
    ))
    wrong = game.cast_from_hand(
        0, "Nourishing Shoal", alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert not wrong.supported and "does not answer" in wrong.details
    game = _w1g2_table(set_pool, hands=(
        [bok["Nourishing Shoal"], bok["Nourishing Shoal"]], (),
    ))
    assert game.cast_from_hand(0, "Nourishing Shoal", alternative_cost=True).supported
    _w1g2_settle(game)
    assert game.players[0].life == 22
    assert _w1g2_names(game.players[0].exile) == ["Nourishing Shoal"]


def test_w1g2_sickening_shoal_offer_names_each_cards_x(set_pool):
    """The cast-cost offer the client reads: each black card in hand with the X
    it would name, and the price spelled with its "mana value X"."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [bok["Sickening Shoal"], lea["Sengir Vampire"], lea["Dark Ritual"],
         lea["Giant Growth"]], (),
    ))
    offers = game.cast_cost_offers(0, game.players[0].hand[0], spell_hand_index=0)
    (offer,) = [entry for entry in offers if entry["kind"] == "alternative"]
    assert offer["label"] == "exile a black card with mana value X from your hand"
    assert offer["x_is_chosen_card_mana_value"] is True
    assert [(choice["name"], choice["x"]) for choice in offer["hand_choices"]] == [
        ("Sengir Vampire", 5), ("Dark Ritual", 1),
    ]
    victim = _w1g2_put(game, lea["Hill Giant"], 1)
    assert game.cast_from_hand(
        0, "Sickening Shoal", target_permanent_ids=[victim.permanent_id],
        alternative_cost=True, alternative_cost_hand_index=1,
    ).supported
    _w1g2_settle(game)
    assert "Hill Giant" in _w1g2_names(game.players[1].graveyard), game.log


def test_w1g2_disrupting_shoal_counters_only_a_spell_whose_mana_value_is_x(set_pool):
    """Bob casts Hill Giant (mana value 4). Alice pitches Control Magic ({2}{U}{U}):
    countered. Pitching a 2-drop instead, the Shoal resolves and does nothing
    (ruling 2005-02-01: "can target any spell, but does nothing unless that
    spell's mana value is X")."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    for pitched, countered in (("Control Magic", True), ("Counterspell", False)):
        game = _w1g2_table(set_pool, hands=(
            [bok["Disrupting Shoal"], lea[pitched]], [lea["Hill Giant"]],
        ), mana=False)
        assert game.queue_from_hand(1, "Hill Giant").supported
        game.enforce_mana_costs = True
        result = game.queue_from_hand(
            0, "Disrupting Shoal", target_stack_index=0,
            alternative_cost=True, alternative_cost_hand_index=1,
        )
        assert result.supported, result
        _w1g2_settle(game)
        on_board = [perm.card.name for perm in game.controlled_by(1)]
        assert (on_board == []) is countered, game.log
        assert ("Hill Giant" in _w1g2_names(game.players[1].graveyard)) is countered
        assert _w1g2_names(game.players[0].exile) == [pitched]


def test_w1g2_disrupting_shoal_hard_cast_reads_its_announced_x(set_pool):
    """Cast for {X}{U}{U} with X = 1: a 1-drop spell is countered, X = 2 is
    not (CR 107.3a: on the stack the X is the announced value)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    for x_value, countered in ((1, True), (2, False)):
        game = _w1g2_table(set_pool, hands=(
            [bok["Disrupting Shoal"]], [lea["Lightning Bolt"]],
        ), mana=False)
        assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        assert game.queue_from_hand(
            0, "Disrupting Shoal", target_stack_index=0, x_value=x_value,
        ).supported
        _w1g2_settle(game)
        assert (game.players[0].life == 20) is countered, game.log

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
