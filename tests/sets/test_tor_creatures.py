"""Torment creatures (legendary ones too).

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

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_duel(*, hand0=(), hand1=(), bf0=(), bf1=(), library0=None):
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library0) if library0 is not None else [filler] * 10,
            hand=list(hand0),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10, hand=list(hand1),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def test_w1g5_cephalid_vandal_mills_one_more_card_each_upkeep(set_pool):
    """A shred counter each upkeep, then a mill of one card per shred counter:
    1, then 2, then 3 — the count read off the source as the trigger resolves."""
    vandal = set_pool("TOR")["Cephalid Vandal"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(10)]
    game = _w1g5_duel(bf0=[vandal], library0=library)

    milled = []
    for _turn in range(3):
        before = len(game.players[0].graveyard)
        game.start_turn(0)
        _w1g5_resolve_stack(game)
        milled.append(len(game.players[0].graveyard) - before)

    assert milled == [1, 2, 3]
    assert "Cephalid Vandal gets a shred counter (3 total)" in game.log
    assert "A milled 3 card(s)" in game.log


def test_w1g5_pitchstone_wall_returns_the_discarded_card_if_sacrificed(set_pool):
    """Two discards, two triggers. Taking the first offer sacrifices the Wall
    and returns that card; the second finds no Wall to sacrifice ("if you do")
    and returns nothing."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    wall, sludge = tor["Pitchstone Wall"], tor["Mind Sludge"]
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g5_duel(
        hand0=[bolt, bears, forest], hand1=[sludge],
        bf0=[wall], bf1=[lea["Swamp"], lea["Swamp"]],
    )
    game.interactive_seats = {0}

    game.cast_from_hand(1, sludge.name, target_player_index=0)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1], to_library=False,
    )
    assert [item.card.name for item in game.stack] == ["Pitchstone Wall"] * 2
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g5_resolve_stack(game)

    a = game.players[0]
    assert sorted(card.name for card in a.hand) == ["Forest", "Lightning Bolt"]
    assert sorted(card.name for card in a.graveyard) == ["Grizzly Bears", "Pitchstone Wall"]
    assert not list(game.controlled_by(0))


def test_w1g5_pitchstone_wall_declined_returns_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[lea["Lightning Bolt"]], hand1=[tor["Mind Sludge"]],
        bf0=[tor["Pitchstone Wall"]], bf1=[lea["Swamp"]],
    )

    game.cast_from_hand(1, "Mind Sludge", target_player_index=0)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Pitchstone Wall"]


def test_w1g5_pitchstone_wall_ignores_an_opponents_discard(set_pool):
    """"Whenever **you** discard a card": the Wall's controller only."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[tor["Mind Sludge"]], hand1=[lea["Lightning Bolt"]],
        bf0=[tor["Pitchstone Wall"], lea["Swamp"]],
    )

    game.cast_from_hand(0, "Mind Sludge", target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]
    assert not game.stack


def test_w1g5_nantuko_cultivator_counts_and_draws_the_lands_discarded(set_pool):
    """Discard three lands: three +1/+1 counters and three cards. It placed
    none and drew none — the counters read Tetravus's ``trigger_count`` and
    the draw's handler never read ``amount_from`` — and with the counter
    step unreadable the offer could not fold its payoffs, so both ran before
    the discard was even answered."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    forest, island, bolt = lea["Forest"], lea["Island"], lea["Lightning Bolt"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Instant") for i in range(10)]
    game = _w1g5_duel(hand0=[cultivator, forest, forest, island, bolt], library0=library)
    game.interactive_seats = {0}

    game.cast_from_hand(0, cultivator.name)
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    owed = game.pending_choice_of("discard", 0)
    assert owed is not None and owed.data.get("up_to")
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1, 2], to_library=False,
    )
    _w1g5_resolve_stack(game)

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Lightning Bolt", "W1G5 Card 0", "W1G5 Card 1", "W1G5 Card 2",
    ]


def test_w1g5_nantuko_cultivator_declined_places_and_draws_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    game = _w1g5_duel(hand0=[cultivator, lea["Forest"]])

    game.cast_from_hand(0, cultivator.name)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_swarm_table(set_pool, *, humans=()):
    """Shambling Swarm and a Savannah Lions for seat 0, a Grizzly Bears and a
    Hill Giant for seat 1, and a Lightning Bolt in seat 1's hand to kill the
    Swarm with."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", library=[lea["Forest"]] * 10),
        _W1G8Player("B", library=[lea["Forest"]] * 10, hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    placed = {}
    for seat, name, card in (
        (0, "swarm", set_pool("TOR")["Shambling Swarm"]),
        (0, "lions", lea["Savannah Lions"]),
        (1, "bears", lea["Grizzly Bears"]),
        (1, "giant", lea["Hill Giant"]),
    ):
        placed[name] = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, placed[name], None)
    return game, placed


def _w1g8_bolt_the_swarm(game, swarm):
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[swarm.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)


def _w1g8_body(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g8_shambling_swarm_dies_and_a_seat_nobody_asks_spreads_its_counters(set_pool):
    """"When this creature dies, distribute three -1/-1 counters among one,
    two, or three target creatures." It compiled, reported supported and
    announced nothing: the handler found one creature on its own and put all
    three counters on it, and a person was never asked. A seat nobody asks
    now announces as a divided spell is proposed — the opponent's creatures,
    spread — and the shares come back at the next end step."""
    game, placed = _w1g8_swarm_table(set_pool)
    _w1g8_bolt_the_swarm(game, placed["swarm"])

    assert "Shambling Swarm: targets Grizzly Bears (2), Hill Giant (1)" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(placed["bears"]), "2/2 with two -1/-1 counters"
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert _w1g8_body(placed["lions"]) == (2, 1), "its controller's own is spared"

    # One delayed removal per counter, each bound to its own creature; the
    # Bears' two find nothing (CR 400.7), the Giant's one finds the Giant.
    assert sorted(t.bound_permanent_id for t in game.delayed_triggers) == sorted([
        placed["bears"].permanent_id, placed["bears"].permanent_id,
        placed["giant"].permanent_id,
    ])
    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (3, 3)
    assert placed["giant"].metadata.get("minus_counters", 0) == 0
    assert not game.delayed_triggers


def test_w1g8_shambling_swarm_asks_its_controller_for_the_division(set_pool):
    """A person is asked which creatures **and** how the three counters are
    divided among them (CR 603.3d, CR 601.2d) — and the dying Swarm itself is
    not on offer, because the ability goes on the stack after it has died.
    Two targets are 2+1 or 1+2, which is the announcer's choice: an answer
    leaving it out is refused, and so is one that does not total three."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    assert bolt.supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert (asked.data["max_targets"], asked.data["division_total"]) == (3, 3)
    assert asked.data["division"] == "chosen"
    offered = {t["permanent_id"] for t in asked.data["targets"]}
    assert placed["swarm"].permanent_id not in offered
    assert offered == {
        placed[name].permanent_id for name in ("lions", "bears", "giant")
    }

    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert not game.confirm_trigger_target(0, permanent_ids=pair), "2+1 or 1+2?"
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 1])
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[3, 0])
    assert not game.confirm_trigger_target(0, permanent_ids=[]), "one or more"
    assert game.pending_choices == [asked]

    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 2])
    _w1g8_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g8_body(placed["bears"]) == (1, 1)
    assert _w1g8_body(placed["giant"]) == (1, 1)

    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["bears"]) == (2, 2)
    assert _w1g8_body(placed["giant"]) == (3, 3)


def test_w1g8_shambling_swarm_forced_divisions_need_no_amounts(set_pool):
    """One target takes all three and three targets take one apiece — no
    choice is left to make, so an answer naming either needs no division."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    assert game.confirm_trigger_target(0, permanent_id=placed["giant"].permanent_id)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (0, 0)
    assert _w1g8_body(placed["bears"]) == (2, 2)


def test_w1g8_shambling_swarm_keeps_a_departed_targets_share_out(set_pool):
    """CR 608.2b: a target that has left is illegal and its share goes
    nowhere — the survivor keeps exactly what was announced for it, and the
    ability still resolves for it."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.players[0].hand.append(set_pool("LEA")["Unsummon"])
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[2, 1])

    # In response, the Bears go back to their owner's hand.
    bounce = game.cast_from_hand(
        0, "Unsummon", target_player_index=1,
        target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert bounce.supported, bounce.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert placed["giant"].metadata.get("minus_counters") == 1


def _w1g8_cast_firecat(set_pool, monkeypatch, coins):
    """Crazed Firecat cast and resolved with the flips scripted, entry
    trigger and all."""
    script = iter(coins)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda: next(script)
    )
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Crazed Firecat"]]),
        _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    result = game.cast_from_hand(0, "Crazed Firecat")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)
    (firecat,) = game.controlled_by(0)
    return game, firecat


def test_w1g8_crazed_firecat_counts_the_flips_it_won(monkeypatch, set_pool):
    """"When this creature enters, flip a coin until you lose a flip. Put a
    +1/+1 counter on this creature for each flip you won." Won, won, lost:
    two counters, and the losing flip ends the run (the scripted coin has no
    fourth face to give)."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [True, True, False])
    assert _w1g8_body(firecat) == (6, 6)
    assert firecat.metadata.get("plus_counters") == 2
    assert "Crazed Firecat: won 2 flip(s) before losing one" in game.log


def test_w1g8_crazed_firecat_that_loses_the_first_flip_gets_nothing(monkeypatch, set_pool):
    """The losing flip is not a flip won: lose the first and the Firecat is
    its printed 4/4."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [False])
    assert _w1g8_body(firecat) == (4, 4)
    assert not firecat.metadata.get("plus_counters")


def test_w1g8_for_each_flip_you_won_names_a_run_or_nothing():
    """The count is the run's record, read through the producer gate every
    back-reference passes: with no run of flips in front of it the words name
    nothing, and the line refuses rather than placing zero counters."""
    from engine.grammar import compile_line

    lone = compile_line(
        "When this creature enters, put a +1/+1 counter on this creature for "
        "each flip you won."
    )
    assert not lone.usable and lone.lowering_error

# ==== end W1G8 ======================================================
