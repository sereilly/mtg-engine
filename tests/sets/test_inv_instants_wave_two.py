"""Invasion instants, wave two.

Split from `test_inv_instants.py` at the wave boundary when two waves' blocks summed
past the per-set file cap at integration (tests/sets/README.md: past the
printed-type axis the next division is a round boundary). Everything here
follows that file's block convention - one delimited block per group, each
with its own imports at the top of the block - which is what let the blocks
move whole.
"""


# --- W2G3: the stack ---
#
# Two things. Mages' Contest — the pool's second auction, Illicit Auction's
# round of offers with two bidders and a spell for a stake. And the one
# CR 601.2c gate for a spell that targets an object on the stack, where the
# first wave left two (W1G2's for a named spell, W1G8's for Teferi's Response
# above): what it means for the Invasion counterspells whose counter is the
# first of two sentences.

import pytest as _w2g3_pytest

from engine import Game as _W2G3Game
from engine.models import Permanent as _W2G3Permanent
from engine.models import PlayerState as _W2G3PlayerState
from engine.oracle import compile_card_oracle as _w2g3_compile
from engine.targeting import derive_cast_spec as _w2g3_cast_spec
from tests.helpers import resolve_stack as _w2g3_resolve_stack


def _w2g3_table(set_pool, *, seats: int = 2, interactive=None, library: int = 6):
    """*seats* players at 20 life, costs off; every seat answers its own
    prompts unless *interactive* names the ones that do."""
    island = set_pool("LEA")["Island"]
    game = _W2G3Game(players=[
        _W2G3PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = (
        set(range(seats)) if interactive is None else set(interactive)
    )
    return game


def _w2g3_cast(game, set_pool, seat: int, name: str, code: str = "LEA", **announced):
    """*seat* casts *name* out of *code*; returns the result."""
    game.players[seat].hand.append(set_pool(code)[name])
    outcome = game.queue_from_hand(seat, name, **announced)
    return outcome


def _w2g3_contest(set_pool, *, seats: int = 2, rival: int = 1, interactive=None):
    """Seat *rival* has a Lightning Bolt on the stack aimed at seat 0, and seat
    0 has answered it with Mages' Contest, now resolving the way the app
    resolves it (the object held while the bidding runs). Returns
    ``(game, bolt_item)``."""
    game = _w2g3_table(set_pool, seats=seats, interactive=interactive)
    game.active_player_index = rival
    assert _w2g3_cast(
        game, set_pool, rival, "Lightning Bolt", target_player_index=0,
    ).supported
    bolt = game.stack[0]
    assert _w2g3_cast(
        game, set_pool, 0, "Mages' Contest", "INV", target_stack_index=0,
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    return game, bolt


def _w2g3_asked(game) -> "tuple[int, int, int] | None":
    """``(seat asked, high bid, high bidder)`` of the bid owed now, or None."""
    if not game.pending_choices:
        return None
    choice = game.pending_choices[0]
    assert choice.kind == "bid_life"
    asked = (
        choice.player_index, choice.data["high_bid"], choice.data["high_bidder"],
    )
    return asked


def _w2g3_names(game, seat: int, zone: str) -> list[str]:
    cards = getattr(game.players[seat], zone)
    return [card.name for card in cards]


def test_mages_contest_targets_a_spell_and_compiles_to_an_auction_and_a_counter(set_pool):
    """"You and **target spell's** controller bid life." The one instance of
    the word names a spell, so the picker is a counterspell's; and the program
    is the auction followed by an ordinary conditional counter, not a fused
    kind."""
    card = set_pool("INV")["Mages' Contest"]
    program = _w2g3_compile(card)
    assert program.supported
    assert _w2g3_cast_spec(card, program) == {"kind": "stack"}
    (sequence,) = program.instructions
    auction, won = sequence.payload["steps"]
    assert auction.kind == "bid_life"
    assert auction.payload["bidders"] == ["you", "target_spells_controller"]
    assert auction.payload["starting_bid"] == 1
    assert won.kind == "if_then" and won.payload["condition"]["kind"] == "won_bidding"
    assert [step.kind for step in won.payload["then"]] == ["counter_top_stack_spell"]


def test_mages_contest_counters_the_spell_when_its_opening_bid_stands(set_pool):
    """"You start the bidding with a bid of 1." The rival passes, so the high
    bid stands at 1: the caster loses 1 life and the spell is countered."""
    game, bolt = _w2g3_contest(set_pool)
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Mages' Contest",
    ], "the Contest is still resolving while a bid is owed (CR 608.2)"
    assert _w2g3_asked(game) == (1, 1, 0)

    assert game.confirm_bid_life(1, None)

    assert game.stack == [] and game.pending_choices == []
    assert [player.life for player in game.players] == [19, 20]
    assert _w2g3_names(game, 1, "graveyard") == ["Lightning Bolt"]
    assert _w2g3_names(game, 0, "graveyard") == ["Mages' Contest"]


def test_mages_contest_does_not_counter_when_the_spells_controller_wins(set_pool):
    """"The high bidder loses life equal to the high bid. **If you win** the
    bidding, counter that spell." The rival tops the bid and the caster lets
    it stand: the rival pays 3 life, the Bolt is not countered and goes on to
    resolve."""
    game, bolt = _w2g3_contest(set_pool)

    assert game.confirm_bid_life(1, 3)
    assert _w2g3_asked(game) == (0, 3, 1)
    assert game.confirm_bid_life(0, None)

    assert len(game.stack) == 1 and game.stack[0] is bolt
    assert [player.life for player in game.players] == [20, 17]
    _w2g3_resolve_stack(game)
    assert [player.life for player in game.players] == [17, 17]


def test_mages_contest_bidding_goes_round_until_the_high_bid_stands(set_pool):
    """"In turn order, each player may top the high bid. The bidding ends if
    the high bid stands." Three raises and a pass; only the last bid is paid,
    and only by the seat that made it."""
    game, _bolt = _w2g3_contest(set_pool)

    assert game.confirm_bid_life(1, 3)
    assert game.confirm_bid_life(0, 5)
    assert _w2g3_asked(game) == (1, 5, 0)
    assert not game.confirm_bid_life(1, 5), "a bid has to top the high bid"
    assert _w2g3_asked(game) == (1, 5, 0)
    assert game.confirm_bid_life(1, 6)
    assert game.confirm_bid_life(0, 9)
    assert game.confirm_bid_life(1, None)

    assert game.stack == []
    assert [player.life for player in game.players] == [11, 20]
    assert _w2g3_names(game, 1, "graveyard") == ["Lightning Bolt"]


def test_mages_contest_is_between_two_seats_in_a_three_seat_game(set_pool):
    """"**You and target spell's controller** bid life" — not each player. In
    a three-seat game the seat in between is never asked."""
    game, bolt = _w2g3_contest(set_pool, seats=3, rival=2)
    asked = [_w2g3_asked(game)[0]]

    assert game.confirm_bid_life(2, 4)
    asked.append(_w2g3_asked(game)[0])
    assert game.confirm_bid_life(0, None)

    assert asked == [2, 0] and game.pending_choices == []
    assert [player.life for player in game.players] == [20, 20, 16]
    assert len(game.stack) == 1 and game.stack[0] is bolt


def test_mages_contest_against_a_seat_nobody_asks_is_won_at_the_opening_bid(set_pool):
    """A seat the engine plays passes where the offer stands (the auction's
    registered default: a default never bids life nobody decided to spend), so
    nothing is left owed and the whole resolution finishes at once."""
    game, _bolt = _w2g3_contest(set_pool, interactive={0})

    assert game.stack == [] and game.pending_choices == []
    assert [player.life for player in game.players] == [19, 20]
    assert _w2g3_names(game, 1, "graveyard") == ["Lightning Bolt"]


def test_mages_contest_over_its_casters_own_spell_is_an_auction_of_one(set_pool):
    """"You and target spell's controller" are one player, who bids once: the
    opening bid stands unopposed."""
    game = _w2g3_table(set_pool)
    assert _w2g3_cast(
        game, set_pool, 0, "Lightning Bolt", target_player_index=1,
    ).supported
    assert _w2g3_cast(
        game, set_pool, 0, "Mages' Contest", "INV", target_stack_index=0,
    ).supported

    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.stack == [] and game.pending_choices == []
    assert [player.life for player in game.players] == [19, 20]
    assert _w2g3_names(game, 0, "graveyard") == ["Lightning Bolt", "Mages' Contest"]


def test_mages_contest_winning_does_not_counter_an_uncounterable_spell(set_pool):
    """The counter is the ordinary one, so "This spell can't be countered"
    (Scragnoth) answers it: the bid is still lost — the two sentences are
    separate — and the creature resolves."""
    game = _w2g3_table(set_pool)
    assert _w2g3_cast(game, set_pool, 1, "Scragnoth", "TMP").supported
    assert _w2g3_cast(
        game, set_pool, 0, "Mages' Contest", "INV", target_stack_index=0,
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.confirm_bid_life(1, None)

    assert [item.card.name for item in game.stack] == ["Scragnoth"]
    assert [player.life for player in game.players] == [19, 20]
    assert any("can't be countered" in line for line in game.log)


def test_mages_contest_cannot_be_cast_without_a_spell_to_target(set_pool):
    """CR 601.2c: no spell on the stack, no target, no cast — and an ability
    is not a spell (CR 113.7a)."""
    game = _w2g3_table(set_pool)
    contest = set_pool("INV")["Mages' Contest"]
    game.players[0].hand.append(contest)

    assert not game.queue_from_hand(0, "Mages' Contest").supported

    sorcerer = _W2G3Permanent(card=set_pool("LEA")["Prodigal Sorcerer"])
    game._put_permanent_onto_battlefield(1, sorcerer, None)
    sorcerer.metadata["summoning_sickness_turn"] = -99
    assert game.queue_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0,
    ).supported
    assert not game.queue_from_hand(
        0, "Mages' Contest", target_stack_index=0,
    ).supported
    assert game.players[0].hand == [contest] and len(game.stack) == 1


def test_mages_contest_does_not_resolve_once_its_spell_has_left_the_stack(set_pool):
    """CR 608.2b: the Bolt is countered in response, so the Contest's only
    target is gone and there is no bidding at all — nobody loses life."""
    game = _w2g3_table(set_pool)
    assert _w2g3_cast(
        game, set_pool, 1, "Lightning Bolt", target_player_index=0,
    ).supported
    assert _w2g3_cast(
        game, set_pool, 0, "Mages' Contest", "INV", target_stack_index=0,
    ).supported
    assert _w2g3_cast(
        game, set_pool, 1, "Counterspell", target_stack_index=0,
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [item.card.name for item in game.stack] == ["Mages' Contest"]

    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.stack == [] and game.pending_choices == []
    assert [player.life for player in game.players] == [20, 20]
    assert any("608.2b" in line for line in game.log)


def test_illicit_auction_still_hands_the_creature_to_the_high_bidder(set_pool):
    """The auction the Contest's round was built from, driven beside it: the
    loop now carries a second outcome and the first must not have moved. Three
    seats, each asked in turn order; the high bidder pays and takes it."""
    game = _w2g3_table(set_pool, seats=3)
    bears = _W2G3Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game._put_permanent_onto_battlefield(2, bears, None)
    assert _w2g3_cast(
        game, set_pool, 0, "Illicit Auction", "MIR",
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w2g3_asked(game) == (1, 0, 0)
    assert game.confirm_bid_life(1, 2)
    assert game.confirm_bid_life(2, None)
    assert game.confirm_bid_life(0, None)

    assert game.stack == [] and game.pending_choices == []
    assert [player.life for player in game.players] == [20, 18, 20]
    assert game.controller_index_of(bears) == 1


@_w2g3_pytest.mark.parametrize(
    "name", ["Absorb", "Exclude", "Undermine", "Mages' Contest"],
)
def test_an_invasion_counterspell_cannot_be_cast_onto_an_empty_stack(set_pool, name):
    """CR 601.2c. Absorb and Undermine compile to a ``sequence``, which no
    per-kind arm read, so both were castable with nothing to counter and
    resolved their second sentence alone — Absorb for 3 life."""
    game = _w2g3_table(set_pool)
    card = set_pool("INV")[name]
    game.players[0].hand.append(card)

    refused = game.queue_from_hand(0, name)

    assert not refused.supported
    assert refused.details == f"no valid target for {name}"
    assert game.players[0].hand == [card] and game.stack == []
    assert game.players[0].life == 20


def test_absorb_counters_and_gains_three_when_it_has_a_spell(set_pool):
    game = _w2g3_table(set_pool)
    assert _w2g3_cast(
        game, set_pool, 1, "Lightning Bolt", target_player_index=0,
    ).supported
    assert _w2g3_cast(
        game, set_pool, 0, "Absorb", "INV", target_stack_index=0,
    ).supported
    _w2g3_resolve_stack(game)

    assert game.stack == []
    assert [player.life for player in game.players] == [23, 20]
    assert _w2g3_names(game, 1, "graveyard") == ["Lightning Bolt"]


def test_exclude_cast_bare_is_aimed_at_the_creature_spell_not_the_spell_on_top(set_pool):
    """"Counter target **creature** spell. Draw a card." A caller that names
    nothing is given the topmost spell the phrase admits — the Bears under the
    Bolt — and with only the Bolt there the cast is refused."""
    game = _w2g3_table(set_pool)
    assert _w2g3_cast(game, set_pool, 1, "Grizzly Bears").supported
    assert _w2g3_cast(
        game, set_pool, 1, "Lightning Bolt", target_player_index=0,
    ).supported
    bears, bolt = game.stack
    hand = len(game.players[0].hand)

    assert _w2g3_cast(game, set_pool, 0, "Exclude", "INV").supported
    assert game.stack[-1].target_stack_item is bears
    game.resolve_top_of_stack()

    assert len(game.stack) == 1 and game.stack[0] is bolt
    assert _w2g3_names(game, 1, "graveyard") == ["Grizzly Bears"]
    assert len(game.players[0].hand) == hand + 1

    lone = _w2g3_table(set_pool)
    assert _w2g3_cast(
        lone, set_pool, 1, "Lightning Bolt", target_player_index=0,
    ).supported
    assert not _w2g3_cast(lone, set_pool, 0, "Exclude", "INV").supported
    assert _w2g3_names(lone, 0, "hand") == ["Exclude"]


# --- W2G1: kicker spells ---
import pytest as _w2g1_pytest

from engine import Game as _W2G1Game
from engine import PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile
from tests.helpers import _nosick as _w2g1_nosick
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_duel(set_pool, name, pool, *, theirs=()):
    """Seat 0 holds the INV instant *name* with *pool* floating; seat 1 holds
    the LEA cards *theirs*. Costs are charged: a kicker is a price, and a rig
    that waives mana cannot tell a kicked cast from a free one."""
    lea = set_pool("LEA")
    game = _W2G1Game(players=[
        _W2G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
        ),
        _W2G1PlayerState(
            "Victim", library=[lea["Forest"]] * 10,
            hand=[lea[other] for other in theirs],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w2g1_duel


def _w2g1_put(game, seat, card):
    permanent = _W2G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w2g1_put


def _w2g1_names(cards):
    return [card.name for card in cards]  # _w2g1_names


# --- Prohibit ---------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("spell, mana, x_value, kicked, countered", [
    ("Lightning Bolt", {"R": 1}, None, False, True),    # mana value 1 <= 2
    ("Hill Giant", {"R": 4}, None, False, False),       # 4 > 2
    ("Hill Giant", {"R": 4}, None, True, True),         # 4 <= 4, kicked
    ("Craw Wurm", {"G": 6}, None, True, False),         # 6 > 4
    # CR 202.3b: on the stack an X in the cost is the announced value.
    ("Fireball", {"R": 4}, 1, False, True),             # {X}{R}, X=1: 2
    ("Fireball", {"R": 4}, 3, False, False),            # X=3: 4
    ("Fireball", {"R": 4}, 3, True, True),
])
def test_w2g1_prohibit_counters_by_the_spells_mana_value(
    set_pool, spell, mana, x_value, kicked, countered,
):
    """"Counter target spell if its mana value is 2 or less. If this spell was
    kicked, counter that spell if its mana value is 4 or less instead."

    The clause is a condition on the *effect* (CR 608.2c), not a targeting
    restriction: every row is a legal announcement, paid for in full, and the
    rows that are not countered resolve as if Prohibit had not been cast."""
    game = _w2g1_duel(set_pool, "Prohibit", {"U": 4}, theirs=[spell])
    game.players[1].mana_pool.update(mana)
    is_creature = "Creature" in set_pool("LEA")[spell].type_line
    announced = {} if is_creature else {"target_player_index": 0}
    if x_value is not None:
        announced["x_value"] = x_value
    assert game.queue_from_hand(1, spell, **announced).supported

    result = game.queue_from_hand(
        0, "Prohibit", target_stack_index=0,
        optional_cost_payments={"{2}": 1} if kicked else None,
    )
    assert result.supported, result
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 2)
    _w2g1_resolve_stack(game)

    assert _w2g1_names(game.players[0].graveyard) == ["Prohibit"]
    on_their_board = _w2g1_names(p.card for p in game.controlled_by(1))
    if countered:
        assert _w2g1_names(game.players[1].graveyard) == [spell]
        assert game.players[0].life == 20 and on_their_board == []
        assert any("countered by Prohibit" in line for line in game.log)
    elif is_creature:
        assert on_their_board == [spell]
    else:
        assert game.players[0].life == 20 - (x_value or 3), game.log


def test_w2g1_prohibit_offers_every_spell_whatever_it_costs(set_pool):
    """CR 601.2c reads the printed target phrase, which is "target spell": a
    six-drop is offered to the picker exactly as a one-drop is."""
    game = _w2g1_duel(set_pool, "Prohibit", {"U": 4}, theirs=["Craw Wurm"])
    game.players[1].mana_pool.update({"G": 6})
    assert game.queue_from_hand(1, "Craw Wurm").supported

    spec = game.cast_target_spec(0, set_pool("INV")["Prohibit"])
    assert spec["requires_target"]
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Craw Wurm"]


# --- Overload ---------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("artifact, kicked, destroyed", [
    ("Sol Ring", False, True),              # 1 <= 2
    ("Jayemdae Tome", False, False),        # 4 > 2
    ("Jayemdae Tome", True, True),          # 4 <= 5, kicked
    ("Colossus of Sardia", True, False),    # 9 > 5
])
def test_w2g1_overload_destroys_by_the_artifacts_mana_value(
    set_pool, artifact, kicked, destroyed,
):
    """"Destroy target artifact if its mana value is 2 or less. If this spell
    was kicked, destroy that artifact if its mana value is 5 or less instead."
    One artifact is announced whichever arm resolves, and "that artifact" is
    it."""
    game = _w2g1_duel(set_pool, "Overload", {"R": 3})
    pool = {**set_pool("LEA"), **set_pool("ATQ")}
    victim = _w2g1_put(game, 1, pool[artifact])
    bystander = _w2g1_put(game, 1, set_pool("LEA")["Mox Ruby"])

    result = game.cast_from_hand(
        0, "Overload", target_permanent_ids=[victim.permanent_id],
        optional_cost_payments={"{2}": 1} if kicked else None,
    )
    assert result.supported, result
    _w2g1_resolve_stack(game)

    assert game.is_on_battlefield(victim) is (not destroyed), game.log
    assert game.is_on_battlefield(bystander), "a zero-drop nobody aimed at"
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 2)


def test_w2g1_overload_may_be_aimed_at_any_artifact_and_at_nothing_else(set_pool):
    """The mana value is asked at resolution, so a nine-drop is a legal target
    the spell simply does nothing to; a creature is not an artifact and the
    cast is refused with nothing spent."""
    game = _w2g1_duel(set_pool, "Overload", {"R": 3})
    colossus = _w2g1_put(game, 1, set_pool("ATQ")["Colossus of Sardia"])
    giant = _w2g1_put(game, 1, set_pool("LEA")["Hill Giant"])

    spec = game.cast_target_spec(0, set_pool("INV")["Overload"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Colossus of Sardia"]

    refused = game.cast_from_hand(
        0, "Overload", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 3
    assert game.is_on_battlefield(colossus)


# --- Scorching Lava ---------------------------------------------------------


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_scorching_lava_exiles_what_it_kills_only_when_kicked(set_pool, kicked):
    """"…If this spell was kicked, that creature can't be regenerated this
    turn and if it would die this turn, exile it instead." Two points to a 2/2
    either way; the kick decides which zone it ends up in."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    bears = _w2g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])

    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[bears.permanent_id],
        optional_cost_payments={"{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    assert not game.is_on_battlefield(bears)
    assert _w2g1_names(game.players[1].exile) == (["Grizzly Bears"] if kicked else [])
    assert _w2g1_names(game.players[1].graveyard) == ([] if kicked else ["Grizzly Bears"])


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_scorching_lava_kicked_beats_a_regeneration_shield(set_pool, kicked):
    """"…can't be regenerated this turn" (CR 701.19c). The same shield saves
    the creature from the unkicked spell, which is what shows the kicked run
    measured the rider rather than a shield that never worked."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    bears = _w2g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    bears.regeneration_shield = 1

    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[bears.permanent_id],
        optional_cost_payments={"{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    assert game.is_on_battlefield(bears) is (not kicked), game.log
    if kicked:
        assert _w2g1_names(game.players[1].exile) == ["Grizzly Bears"]
    else:
        assert bears.tapped and bears.damage_marked == 0


def test_w2g1_scorching_lava_marks_a_survivor_for_the_turn_and_spares_a_player(set_pool):
    """The riders last "this turn", so a creature that survives the two points
    carries them until cleanup; "that creature" is the guard, so a kicked Lava
    aimed at a player is two damage and nothing else."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    giant = _w2g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[giant.permanent_id],
        optional_cost_payments={"{R}": 1},
    ).supported
    _w2g1_resolve_stack(game)
    assert giant.damage_marked == 2
    assert giant.metadata.get("cant_be_regenerated_this_turn")
    assert giant.metadata.get("exile_if_dies_this_turn")

    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    assert game.cast_from_hand(
        0, "Scorching Lava", optional_cost_payments={"{R}": 1},
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 18


# --- Urza's Rage ------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("kicked, damage", [(False, 3), (True, 10)])
def test_w2g1_urzas_rage_deals_three_or_ten(set_pool, kicked, damage):
    """"Urza's Rage deals 3 damage to any target. If this spell was kicked,
    **instead** it deals 10 damage to **that permanent or player** …" One
    target, announced once; the fronted "instead" replaces the three rather
    than adding to it (thirteen is the two sentences read as steps)."""
    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    assert game.cast_from_hand(
        0, "Urza's Rage", optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 20 - damage
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 9)

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    wurm = _w2g1_put(game, 1, set_pool("LEA")["Craw Wurm"])      # 6/4
    elemental = _w2g1_put(game, 1, set_pool("LEA")["Force of Nature"])  # 8/8
    assert game.cast_from_hand(
        0, "Urza's Rage", target_permanent_ids=[elemental.permanent_id],
        optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 20, "a creature was named, not the face"
    assert game.is_on_battlefield(elemental) is (not kicked)
    assert game.is_on_battlefield(wurm) and wurm.damage_marked == 0


@_w2g1_pytest.mark.parametrize("kicked, life", [(False, 20), (True, 10)])
def test_w2g1_urzas_rage_kicked_goes_through_a_players_shield(set_pool, kicked, life):
    """"…and the damage can't be prevented." A Circle-shaped shield on the
    player swallows the three and does nothing to the ten — any recipient, not
    only a creature, which is what separates this clause from Lava Burst's."""
    from engine.shields import PREVENT_NEXT_N, Shield, add_shield

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    add_shield(game.players[1], Shield(kind=PREVENT_NEXT_N, amount=10, uses=None))
    assert game.cast_from_hand(
        0, "Urza's Rage", optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == life, game.log


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_urzas_rage_kicked_goes_through_a_creatures_shield(set_pool, kicked):
    """The same clause about a permanent: a ten-point shield on a 9/9 absorbs
    the unkicked three whole, and absorbs none of the kicked ten."""
    from engine.shields import PREVENT_NEXT_N, Shield, add_shield

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    colossus = _w2g1_put(game, 1, set_pool("ATQ")["Colossus of Sardia"])   # 9/9
    add_shield(colossus, Shield(kind=PREVENT_NEXT_N, amount=10, uses=None))
    assert game.cast_from_hand(
        0, "Urza's Rage", target_permanent_ids=[colossus.permanent_id],
        optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    if kicked:
        assert not game.is_on_battlefield(colossus), game.log
    else:
        assert game.is_on_battlefield(colossus) and colossus.damage_marked == 0


def test_w2g1_urzas_rage_cant_be_countered(set_pool):
    """"This spell can't be countered." A Counterspell aimed at it resolves
    and the Rage resolves after it."""
    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 3}, theirs=["Counterspell"])
    game.players[1].mana_pool.update({"U": 2})
    assert game.queue_from_hand(0, "Urza's Rage").supported
    game.queue_from_hand(1, "Counterspell", target_stack_index=0)
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 17, game.log


def test_w2g1_urzas_rage_program_carries_the_printed_lock_on_one_arm(set_pool):
    """The rider is written into the kicked arm's payload and nowhere else:
    an unkicked Rage is an ordinary three-damage spell."""
    program = _w2g1_compile(set_pool("INV")["Urza's Rage"])
    branch = next(i for i in program.instructions if i.kind == "if_then")
    kicked, plain = branch.payload["then"][0], branch.payload["else"][0]
    assert (kicked.payload["amount"], plain.payload["amount"]) == (10, 3)
    assert kicked.payload.get("cant_be_prevented") is True
    assert "cant_be_prevented" not in plain.payload
    assert kicked.payload["targets"] == plain.payload["targets"]


# --- Vigorous Charge --------------------------------------------------------


def _w2g1_charge(set_pool, *, kicked, blocker=None, second_attacker=False):
    """Vigorous Charge on a 6/4 that then attacks, through to the end of the
    combat damage step. Returns the game."""
    lea = set_pool("LEA")
    game = _w2g1_duel(set_pool, "Vigorous Charge", {})
    game.interactive_seats = set()
    wurm = _w2g1_nosick(_w2g1_put(game, 0, lea["Craw Wurm"]))
    if second_attacker:
        _w2g1_nosick(_w2g1_put(game, 0, lea["Hill Giant"]))
    if blocker:
        _w2g1_nosick(_w2g1_put(game, 1, lea[blocker]))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"G": 1, "W": 1})
    assert game.cast_from_hand(
        0, "Vigorous Charge", target_permanent_ids=[wurm.permanent_id],
        optional_cost_payments={"{W}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game._has_keyword(wurm, "trample")
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1] if second_attacker else [0])[0]
    game.advance_combat_phase()
    if blocker:
        assert game.declare_blockers(1, {0: 0})[0]
    _w2g1_resolve_stack(game)
    game.advance_combat_phase()
    _w2g1_resolve_stack(game)
    return game  # _w2g1_charge


def test_w2g1_vigorous_charge_unkicked_is_trample_and_nothing_else(set_pool):
    """"…if this spell was kicked, you gain life equal to that damage." The
    gate is asked as the delayed ability would be created: unkicked, none is,
    and six combat damage gains nobody anything."""
    game = _w2g1_charge(set_pool, kicked=False)
    assert game.delayed_triggers == []
    assert (game.players[0].life, game.players[1].life) == (20, 14)


def test_w2g1_vigorous_charge_kicked_gains_the_damage_dealt_to_a_player(set_pool):
    game = _w2g1_charge(set_pool, kicked=True)
    assert (game.players[0].life, game.players[1].life) == (26, 14), game.log


def test_w2g1_vigorous_charge_counts_trample_damage_on_both_sides_of_a_block(set_pool):
    """"Whenever that creature deals combat damage this turn" — to anything.
    Blocked by a 2/2, the 6/4 trampler assigns two to the blocker and four to
    the player, and the life gained is all six."""
    game = _w2g1_charge(set_pool, kicked=True, blocker="Grizzly Bears")
    assert game.players[1].life == 16
    assert game.players[0].life == 26, game.log


def test_w2g1_vigorous_charge_watches_only_the_creature_it_named(set_pool):
    """Another attacker's three points are not "that creature"'s damage, and
    the ability is gone with the turn (CR 603.7b)."""
    game = _w2g1_charge(set_pool, kicked=True, second_attacker=True)
    assert game.players[1].life == 11
    assert game.players[0].life == 26, game.log

    from engine.delayed_triggers import expire_delayed_triggers

    assert [entry.event for entry in game.delayed_triggers] == [
        "bound_permanent_deals_combat_damage"
    ]
    expire_delayed_triggers(game)
    assert game.delayed_triggers == []
# end of the W2G1 instants block


# --- W2G2: bound objects ---
from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile
from engine.targeting import derive_cast_spec as _w2g2_cast_spec
from tests.helpers import resolve_stack as _w2g2_resolve_stack


def _w2g2_instant_duel(set_pool, *, active: int = 0):
    """Two seats with costs off and ten Islands each to draw from."""
    island = set_pool("LEA")["Island"]
    w2g2_game = _W2G2Game(players=[
        _W2G2PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    w2g2_game.enforce_mana_costs = False
    w2g2_game.active_player_index = active
    return w2g2_game


def _w2g2_instant_put(game, set_pool, seat: int, name: str, code: str = "LEA"):
    """*name* on *seat*'s battlefield, past its summoning sickness."""
    w2g2_permanent = _W2G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, w2g2_permanent, None)
    w2g2_permanent.metadata["summoning_sickness_turn"] = -99
    return w2g2_permanent


# --- Defiling Tears --------------------------------------------------------
#
# "Until end of turn, target creature becomes black, gets +1/-1, and gains
# "{B}: Regenerate this creature.""
#
# One target and a list of three things said about it. Each member lowers to
# its own step, and all three have to land on the one creature that was named.


def test_defiling_tears_does_all_three_things_to_the_one_target(set_pool):
    game = _w2g2_instant_duel(set_pool)
    giant = _w2g2_instant_put(game, set_pool, 0, "Hill Giant")
    bystander = _w2g2_instant_put(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("INV")["Defiling Tears"])

    assert game.cast_from_hand(
        0, "Defiling Tears", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w2g2_resolve_stack(game)

    assert giant.effective_colors == {"B"}
    assert (giant.effective_power, giant.effective_toughness) == (4, 2)
    assert giant.effective_card.oracle_text == "{B}: Regenerate this creature"
    # The creature beside it is not the target and is none of the three.
    assert bystander.effective_colors == {"G"}
    assert (bystander.effective_power, bystander.effective_toughness) == (2, 2)
    assert bystander.effective_card.oracle_text == ""


def test_defiling_tears_grant_is_a_real_ability_and_the_colour_a_real_colour(set_pool):
    """The quoted ability can be activated and shields the creature; "becomes
    black" is what Terror's "nonblack" reads (CR 105.3)."""
    game = _w2g2_instant_duel(set_pool)
    giant = _w2g2_instant_put(game, set_pool, 0, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Defiling Tears"])
    game.cast_from_hand(
        0, "Defiling Tears", target_permanent_ids=[giant.permanent_id],
    )
    _w2g2_resolve_stack(game)

    assert game.activate_permanent_ability(
        0, "Hill Giant", ability_index=0,
    ).supported
    _w2g2_resolve_stack(game)
    assert "Hill Giant gains regeneration shield" in game.log

    game.players[1].hand.append(set_pool("LEA")["Terror"])
    refused = game.cast_from_hand(
        1, "Terror", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(giant)


def test_defiling_tears_ends_at_cleanup_all_three_together(set_pool):
    """The fronted "Until end of turn" governs every member of the list
    (CR 611.2a), so the colour, the P/T and the ability leave together."""
    game = _w2g2_instant_duel(set_pool)
    giant = _w2g2_instant_put(game, set_pool, 0, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Defiling Tears"])
    game.cast_from_hand(
        0, "Defiling Tears", target_permanent_ids=[giant.permanent_id],
    )
    _w2g2_resolve_stack(game)

    game.resolve_cleanup_step(0)

    assert giant.effective_colors == {"R"}
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert giant.effective_card.oracle_text == ""
    assert not game.activate_permanent_ability(
        0, "Hill Giant", ability_index=0,
    ).supported


def test_defiling_tears_minus_one_toughness_kills_a_one_toughness_creature(set_pool):
    """-1 toughness is not damage: Savannah Lions (2/1) is put into the
    graveyard by state-based actions (CR 704.5f), and nothing regenerates it."""
    game = _w2g2_instant_duel(set_pool)
    lions = _w2g2_instant_put(game, set_pool, 1, "Savannah Lions")
    game.players[0].hand.append(set_pool("INV")["Defiling Tears"])

    game.cast_from_hand(
        0, "Defiling Tears", target_permanent_ids=[lions.permanent_id],
    )
    _w2g2_resolve_stack(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(lions)
    assert [card.name for card in game.players[1].graveyard] == ["Savannah Lions"]


def test_defiling_tears_offers_one_creature_target(set_pool):
    tears = set_pool("INV")["Defiling Tears"]
    assert _w2g2_cast_spec(tears, _w2g2_compile(tears)) == {"kind": "creature"}


# --- Spinal Embrace --------------------------------------------------------
#
# "Cast this spell only during combat.
#  Untap target creature you don't control and gain control of it. It gains
#  haste until end of turn. At the beginning of the next end step, sacrifice it.
#  If you do, you gain life equal to its toughness."
#
# Every "it" after the first clause names the creature the first clause took:
# the steal reads the untap's record, the delayed sacrifice is bound to the
# target, and the life is the toughness it had as it was sacrificed.


def _w2g2_embrace_table(set_pool):
    """Seat 0 at its own beginning of combat with Spinal Embrace in hand and a
    Grizzly Bears; seat 1 with a tapped Craw Wurm (6/4)."""
    game = _w2g2_instant_duel(set_pool)
    wurm = _w2g2_instant_put(game, set_pool, 1, "Craw Wurm")
    wurm.tapped = True
    bears = _w2g2_instant_put(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("INV")["Spinal Embrace"])
    game._set_phase_and_step("combat", "beginning_of_combat")
    w2g2_embrace = (game, wurm, bears)
    return w2g2_embrace


def test_spinal_embrace_untaps_steals_and_hastens_the_one_creature(set_pool):
    game, wurm, _bears = _w2g2_embrace_table(set_pool)

    assert game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w2g2_resolve_stack(game)

    assert not wurm.tapped
    assert game.controller_index_of(wurm) == 0
    assert game._has_keyword(wurm, "haste")
    # The steal is untimed (CR 611.2a): cleanup ends the haste and not the
    # control change, so only the delayed sacrifice gives the creature up.
    assert [entry.event for entry in game.delayed_triggers] == ["next_end_step"]


def test_spinal_embrace_sacrifices_it_at_the_end_step_and_gains_its_toughness(set_pool):
    """The stolen creature — not the spell, not the caster's own creature — is
    sacrificed, it goes to its **owner's** graveyard, and the caster gains its
    toughness (Craw Wurm, 6/4)."""
    game, wurm, bears = _w2g2_embrace_table(set_pool)
    game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[wurm.permanent_id],
    )
    _w2g2_resolve_stack(game)

    game.resolve_end_step(0)
    _w2g2_resolve_stack(game)

    assert not game.is_on_battlefield(wurm)
    assert game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Craw Wurm"]
    assert game.players[0].life == 24
    assert game.players[1].life == 20


def test_spinal_embrace_gains_nothing_when_it_cannot_sacrifice(set_pool):
    """"If you do": a creature its owner has taken back by the end step is not
    the caster's to sacrifice (CR 701.21a), so it stays and no life is gained."""
    from engine.control import change_control

    game, wurm, bears = _w2g2_embrace_table(set_pool)
    game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[wurm.permanent_id],
    )
    _w2g2_resolve_stack(game)
    change_control(wurm, 1, source=bears)
    game._sync_control()

    game.resolve_end_step(0)
    _w2g2_resolve_stack(game)

    assert game.is_on_battlefield(wurm)
    assert game.controller_index_of(wurm) == 1
    assert game.players[0].life == 20


def test_spinal_embrace_gains_nothing_when_the_creature_is_gone(set_pool):
    game, wurm, _bears = _w2g2_embrace_table(set_pool)
    game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[wurm.permanent_id],
    )
    _w2g2_resolve_stack(game)
    game.remove_from_battlefield(wurm)

    game.resolve_end_step(0)
    _w2g2_resolve_stack(game)

    assert game.players[0].life == 20


def test_spinal_embrace_is_cast_only_during_combat_at_a_creature_you_dont_control(set_pool):
    game, wurm, bears = _w2g2_embrace_table(set_pool)
    embrace = set_pool("INV")["Spinal Embrace"]
    assert _w2g2_cast_spec(embrace, _w2g2_compile(embrace)) == {
        "kind": "creature", "opponent_only": True,
    }

    # "…target creature you don't control": the caster's own is no target.
    assert not game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[bears.permanent_id],
    ).supported
    game._set_phase_and_step("precombat_main", "precombat_main")
    refused = game.cast_from_hand(
        0, "Spinal Embrace", target_permanent_ids=[wurm.permanent_id],
    )
    assert not refused.supported
    assert game.players[0].hand == [embrace]
    assert game.controller_index_of(wurm) == 1
