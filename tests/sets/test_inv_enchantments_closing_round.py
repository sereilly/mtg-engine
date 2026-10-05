"""Invasion enchantments, the closing round.

Split from `test_inv_enchantments.py` at the round boundary, before it could
cross the per-set file cap: that file stands at 2,276 lines on `main` with wave
two's blocks in it, and this block is 360 more (tests/sets/README.md: past the
printed-type axis the next division is a round boundary — the cut
`test_inv_instants_wave_two.py` already makes one file over). Everything here
follows that file's block convention — one delimited block per group, each with
its own imports at the top of the block.
"""


# --- W3G1: Psychic Battle ---
# The last card of the set. "Whenever a player chooses one or more targets,
# each player reveals the top card of their library. The player who reveals the
# card with the greatest mana value may change the target or targets. If two or
# more cards are tied for greatest, the target or targets remain unchanged.
# Changing targets this way doesn't trigger abilities of permanents named
# Psychic Battle."
#
# The rules underneath it — what counts as choosing a target, and CR 115.7's
# change — are in tests/rules/test_target_choices.py on invented cards. These
# are the card: who is asked, when, and what the answer does.
import pytest as _w3g1_pytest

from engine import Game as _W3G1Game
from engine import PlayerState as _W3G1PlayerState
from engine.models import Permanent as _W3G1Permanent
from engine.stack_targets import TARGETS_CHOSEN_ITEM as _W3G1_CHOSEN_ITEM

from tests.helpers import _mk_card as _w3g1_mk_card
from tests.helpers import _nosick as _w3g1_nosick
from tests.helpers import resolve_stack as _w3g1_resolve_stack

_W3G1_SETS = ("INV", "LEA", "ICE", "VIS")


def _w3g1_card(set_pool, name):
    for code in _W3G1_SETS:
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)


def _w3g1_table(set_pool, *, tops, hands=None, boards=None, interactive=(), battles=(0,)):
    """One seat per entry of *tops* — the card on top of that seat's library,
    or None for an empty one — with a Psychic Battle per entry of *battles*.
    Returns the game and each seat's named permanents."""
    seats = len(tops)
    hands = hands or [[] for _ in range(seats)]
    boards = boards or [[] for _ in range(seats)]
    players, placed = [], {}
    for seat in range(seats):
        battlefield = []
        for name in list(boards[seat]) + ["Psychic Battle"] * list(battles).count(seat):
            permanent = _w3g1_nosick(_W3G1Permanent(card=_w3g1_card(set_pool, name)))
            battlefield.append(permanent)
            placed.setdefault((seat, name), []).append(permanent)
        players.append(_W3G1PlayerState(
            name=f"P{seat}", life=20, battlefield=battlefield,
            hand=[_w3g1_card(set_pool, name) for name in hands[seat]],
            library=[_w3g1_card(set_pool, tops[seat])] * 6 if tops[seat] else [],
        ))
    game = _W3G1Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w3g1_resolve_stack(game)
    return game, placed


def _w3g1_offer(game):
    """The owed re-aim prompt as ``(seat, [option, ...])`` — live ones only."""
    choice = game.pending_choice_of("retarget_choice")
    assert choice is not None, [c.kind for c in game.pending_choices]
    live = game.live_retarget_choices(choice)
    return choice.player_index, [(position, choice.data["options"][position]) for position in live]


def _w3g1_pick(game, wanted):
    """Answer the re-aim prompt with the first option *wanted* accepts."""
    seat, options = _w3g1_offer(game)
    position = next(position for position, option in options if wanted(option))
    assert game.confirm_retarget_choice(seat, position)
    return seat


def test_psychic_battle_goes_on_the_stack_above_the_spell_and_asks_the_bigger_card(set_pool):
    """A Lightning Bolt at seat 1's Bears. The trigger is above the Bolt, both
    players reveal, seat 1's Shivan Dragon (6) beats a Forest (0), and seat 1
    is the one asked — with the Bolt still waiting underneath."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], []],
        boards=[["Grizzly Bears"], ["Grizzly Bears"]], interactive=(0, 1),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Psychic Battle"]
    assert game.stack[1].trigger_context[_W3G1_CHOSEN_ITEM] is game.stack[0]

    game._settle()
    seat, options = _w3g1_offer(game)

    assert seat == 1
    assert "P0 revealed Forest from the top of their library" in game.log
    assert "P1 revealed Shivan Dragon from the top of their library" in game.log
    assert game.stack[0].card.name == "Lightning Bolt", "the Bolt has not resolved"
    assert options[0][1]["kind"] == "keep"
    # Every other legal target of "any target": both faces and seat 0's Bears —
    # and not the Bears it already points at.
    assert {
        (option["kind"], option["seat"] if option["kind"] == "player" else option["permanent_id"])
        for _position, option in options[1:]
    } == {
        ("player", 0), ("player", 1),
        ("permanent", placed[(0, "Grizzly Bears")][0].permanent_id),
    }


def test_psychic_battle_changes_the_target_to_the_one_chosen(set_pool):
    """Seat 1 sends the Bolt at its caster's face: 3 to seat 0, the Bears live."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], []],
        boards=[["Grizzly Bears"], ["Grizzly Bears"]], interactive=(1,),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    _w3g1_pick(game, lambda option: option["kind"] == "player" and option["seat"] == 0)
    _w3g1_resolve_stack(game)
    game.check_state_based_actions()

    assert game.players[0].life == 17
    assert game.is_on_battlefield(theirs)


def test_psychic_battle_lets_the_winner_leave_the_targets_alone(set_pool):
    """"…**may** change": declining is an answer, and the Bolt lands as cast."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], []],
        boards=[[], ["Grizzly Bears"]], interactive=(1,),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    _w3g1_pick(game, lambda option: option["kind"] == "keep")
    _w3g1_resolve_stack(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(theirs)
    assert [player.life for player in game.players] == [20, 20]


@_w3g1_pytest.mark.parametrize(
    "tops", [("Shivan Dragon", "Shivan Dragon"), ("Forest", "Forest"), (None, None)],
    ids=["two sixes", "two lands", "nothing revealed"],
)
def test_psychic_battle_changes_nothing_on_a_tie(set_pool, tops):
    """"If two or more cards are tied for greatest, the target or targets
    remain unchanged." Two lands tie at zero, and with no card revealed at all
    nobody revealed the greatest."""
    game, placed = _w3g1_table(
        set_pool, tops=list(tops), hands=[["Lightning Bolt"], []],
        boards=[[], ["Grizzly Bears"]], interactive=(0, 1),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    game.check_state_based_actions()

    assert game.pending_choice_of("retarget_choice") is None
    assert not game.is_on_battlefield(theirs)


def test_psychic_battle_a_player_with_no_library_reveals_no_card(set_pool):
    """Seat 1's library is empty, so seat 0's Forest is the only card revealed
    — and the greatest of the cards revealed, though its mana value is 0."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", None], hands=[[], ["Lightning Bolt"]],
        boards=[["Grizzly Bears"], []], interactive=(0,),
    )
    mine = placed[(0, "Grizzly Bears")][0]

    assert game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[mine.permanent_id]).supported
    seat = _w3g1_pick(game, lambda option: option["kind"] == "player" and option["seat"] == 1)
    _w3g1_resolve_stack(game)

    assert seat == 0
    assert "P1 has no library to reveal from" in game.log
    assert game.players[1].life == 17 and game.is_on_battlefield(mine)


def test_psychic_battle_reads_both_halves_of_a_split_card(set_pool):
    """CR 709.4b: Assault // Battery in a library is one card of mana value 5
    ({R} and {3}{G}), which beats a Hill Giant's 4."""
    game, placed = _w3g1_table(
        set_pool, tops=["Hill Giant", "Assault // Battery"],
        hands=[["Lightning Bolt"], []], boards=[[], ["Grizzly Bears"]],
        interactive=(0, 1),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported

    seat, _options = _w3g1_offer(game)
    assert seat == 1


@_w3g1_pytest.mark.parametrize("seats", [3, 4])
def test_psychic_battle_every_player_reveals_and_one_of_them_chooses(set_pool, seats):
    """"**Each** player reveals": a third and a fourth seat are in the
    comparison whoever cast the spell and whoever it points at. The last seat
    reveals the Dragon and is asked, and sends seat 0's Bolt at seat 1."""
    tops = ["Forest", "Grizzly Bears", "Hill Giant", "Shivan Dragon"][4 - seats:]
    game, placed = _w3g1_table(
        set_pool, tops=tops, hands=[["Lightning Bolt"]] + [[] for _ in range(seats - 1)],
        interactive=tuple(range(seats)),
    )
    winner = seats - 1

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=winner).supported
    reveals = [line for line in game.log if "from the top of their library" in line]
    assert len(reveals) == seats
    assert _w3g1_pick(game, lambda option: option["kind"] == "player" and option["seat"] == 1) == winner
    _w3g1_resolve_stack(game)

    assert game.players[1].life == 17 and game.players[winner].life == 20


def test_psychic_battle_two_of_them_each_trigger_once_and_not_on_each_other(set_pool):
    """Two on the table: one choice, two triggers. The first to resolve
    changes the target and the second is not answered by that change — it is
    the *other* original trigger that resolves next, and nothing after it."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], []], boards=[[], ["Grizzly Bears"]],
        interactive=(1,), battles=(0, 1),
    )
    theirs = placed[(1, "Grizzly Bears")][0]

    assert game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Psychic Battle", "Psychic Battle"]
    game._settle()
    _w3g1_pick(game, lambda option: option["kind"] == "player" and option["seat"] == 0)
    game._settle()
    assert [item.card.name for item in game.stack if item.card.name == "Psychic Battle"] == ["Psychic Battle"]
    _w3g1_pick(game, lambda option: option["kind"] == "keep")
    _w3g1_resolve_stack(game)

    assert game.players[0].life == 17
    assert sum(1 for line in game.log if line.startswith("P0 revealed")) == 2


def test_psychic_battle_its_change_still_triggers_a_watcher_with_another_name(set_pool):
    """"…doesn't trigger abilities of permanents **named Psychic Battle**" is
    a name, not a category: the same ability printed on a card called something
    else does trigger on a change Psychic Battle made."""
    watcher = _w3g1_mk_card(
        name="W3G1 Watcher", type_line="Enchantment",
        oracle_text=_w3g1_card(set_pool, "Psychic Battle").oracle_text.replace(
            "Psychic Battle", "W3G1 Watcher"
        ),
    )
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], []], boards=[[], ["Grizzly Bears"]],
        interactive=(1,),
    )
    theirs = placed[(1, "Grizzly Bears")][0]
    assert game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    # The watcher arrives after the Bolt's own choice, so the only thing it can
    # answer is the change.
    game._put_permanent_onto_battlefield(0, _W3G1Permanent(card=watcher), 0)
    game._settle()
    _w3g1_pick(game, lambda option: option["kind"] == "player" and option["seat"] == 0)

    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "W3G1 Watcher"]


def test_psychic_battle_triggers_when_deflection_re_aims_a_spell(set_pool):
    """A target changed by another effect is a target chosen: Deflection's own
    choice triggers it, and so does the new target Deflection gives the Bolt."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Forest"],
        hands=[["Lightning Bolt"], ["Deflection"]], boards=[["Grizzly Bears"], []],
    )
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(1, "Deflection", target_stack_index=0).supported
    _w3g1_resolve_stack(game)

    # Bolt, Deflection, and the Bolt again as Deflection moves it: three
    # choices, each tied 0-0 and so changing nothing.
    assert sum(1 for line in game.log if line.startswith("P0 revealed")) == 3
    assert game.players[1].life == 20, "Deflection moved the Bolt off seat 1"


def test_psychic_battle_does_nothing_once_the_spell_has_left_the_stack(set_pool):
    """CR 603.10 looks back at the object the targets were chosen for, and a
    countered spell is not that object any more — the reveal still happens and
    nothing is offered."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt"], ["Counterspell"]], interactive=(1,),
    )
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    bolt_trigger = game.stack[-1]
    # Seat 1 counters the Bolt in response to the trigger, and declines to
    # re-aim its own Counterspell (which has no other spell to go to anyway).
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w3g1_resolve_stack(game)

    assert game.pending_choice_of("retarget_choice") is None
    assert bolt_trigger not in game.stack and game.players[1].life == 20
    assert any("no longer on the stack" in line for line in game.log), game.log


def test_psychic_battle_ignores_a_spell_that_chose_no_target(set_pool):
    """"…chooses **one or more** targets": Wrath of God chooses none, and
    nothing is revealed."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"], hands=[["Wrath of God"], []],
        boards=[["Grizzly Bears"], ["Grizzly Bears"]], interactive=(0, 1),
    )

    assert game.cast_from_hand(0, "Wrath of God").supported

    assert not any("revealed" in line for line in game.log)
    assert game.pending_choices == []


def test_psychic_battle_re_aims_an_entry_trigger_announced_with_its_creature(set_pool):
    """Man-o'-War's "return target creature" is announced as the creature is
    cast in this engine, so that is when the choice is made and when it can be
    changed: seat 1 turns the bounce onto seat 0's own Bears."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"], hands=[["Man-o'-War"], []],
        boards=[["Grizzly Bears"], ["Grizzly Bears"]], interactive=(1,),
    )
    mine, theirs = placed[(0, "Grizzly Bears")][0], placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Man-o'-War", target_permanent_ids=[theirs.permanent_id]).supported
    _w3g1_pick(game, lambda option: option.get("permanent_id") == mine.permanent_id)
    _w3g1_resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert game.is_on_battlefield(theirs) and game.players[1].hand == []


def test_psychic_battle_a_seat_the_engine_plays_moves_harm_off_its_own_side(set_pool):
    """The stated policy for a seat nobody is asking: a Bolt at its creature is
    sent back at the caster, a Bolt already pointing elsewhere is left alone,
    and its own Giant Growth stays where it was aimed. Decided as the trigger
    resolves — the Bolt is the next thing to resolve, and an answer taken after
    the stack emptied would be too late."""
    game, placed = _w3g1_table(
        set_pool, tops=["Forest", "Shivan Dragon"],
        hands=[["Lightning Bolt", "Lightning Bolt"], ["Giant Growth"]],
        boards=[["Grizzly Bears"], ["Grizzly Bears"]],
    )
    mine, theirs = placed[(0, "Grizzly Bears")][0], placed[(1, "Grizzly Bears")][0]

    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id]).supported
    assert game.players[0].life == 17 and game.is_on_battlefield(theirs)

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 14, "not seat 1's problem; left as cast"

    assert game.cast_from_hand(1, "Giant Growth", target_permanent_ids=[theirs.permanent_id]).supported
    assert theirs.effective_power == 5 and mine.effective_power == 2
    assert game.pending_choices == []
