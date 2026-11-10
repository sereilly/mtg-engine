"""CR 704.3 after the turn-based actions: the state check comes first.

"Whenever a player would get priority … the game checks for any of the
listed conditions for state-based actions" (CR 704.3), and a step's
turn-based actions are dealt with before that (CR 703.3, CR 117.3a). So a
turn-based action that makes a state-based action due — a draw from an empty
library, a creature tapped by its own attack, a life payment to block, combat
damage, an "until end of turn" effect ending in cleanup — has its
consequence performed **before the first player receives priority**, not at
whatever next happens to run the sweep.

The engine ran the check after a resolution, after a special action and after
an activation's cost, and after the draw, the untap and combat damage. The
census below puts, for each turn-based action of CR 703.4 the engine performs,
a board on which that action makes a state-based action due, steps into the
step through the engine's own entry points, and reads the board at the first
priority two ways:

* ``window`` — the step as the web layer drives it: it returns with a
  priority window open for a player (``defer_priority=True``, a declaration,
  ``allow_damage_skip=False``), and that is the moment a person acts;
* ``driver`` — the step as the simulator drives it: a ``priority_driver``
  is asked for each seat (``Game.offer_priority``), and the board is read at
  each offer in the step.

Cleanup gives no player priority unless the check finds something
(CR 514.3a), so there the moment is the end of the step, before the next turn
begins.

The CR 703.4 actions the engine does not perform, or that cannot make a
state-based action due, are not on the list: 703.4b (day and night), 703.4e
(Archenemy), 703.4f-g (Sagas, Attractions) have no mechanic here; 703.4h and
703.4k change nothing a state-based action reads; 703.4q empties mana, and
this CR has no mana burn. 703.4n's discard is not either: the only statics a
hand feeds are Maro's P/T (which cannot fall below the maximum it is
discarding down to) and attack restrictions, and what a discard *triggers*
(Megrim, madness) the step already settles.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_counters
from tests.helpers import _nosick, resolve_stack


def _card(name: str, text: str, *, power: int = 1, toughness: int = 1,
          type_line: str = "Creature — Soldier", colors=("W",)) -> CardDefinition:
    card = CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )
    assert compile_card_oracle(card).supported, name
    return card


#: The two statics no shipped card prints in this shape: the untap step's own
#: action turning one off, and phasing taking one away.
TAPPED_LORD = _card(
    "Census Tapped Lord",
    "As long as this creature is tapped, other creatures you control get +0/+2.",
)
PHASING_LORD = _card(
    "Census Phasing Lord", "Phasing\nOther creatures you control get +0/+2.",
)
#: An attack trigger and a block trigger, so the step's first offer of
#: priority is made with an object on the stack.
HERALD = _card("Census Herald", "Whenever this creature attacks, you gain 1 life.")
SENTRY = _card(
    "Census Sentry", "Whenever this creature blocks, you gain 1 life.",
    power=1, toughness=4, colors=("G",),
)


def _game(seats: int = 2) -> Game:
    game = Game(players=[PlayerState(name=f"P{seat}") for seat in range(seats)])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.turn = 3
    return game


def _library(game, pool, seat: int, count: int = 8) -> None:
    game.players[seat].library = [pool["LEA"]["Forest"]] * count


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _cast(game, seat: int, card, target=None) -> None:
    game.players[seat].hand.append(card)
    kwargs = {} if target is None else {"target_permanent_ids": [target.permanent_id]}
    result = game.cast_from_hand(seat, card.name, **kwargs)
    assert result.supported, result.details
    resolve_stack(game)


def _in_graveyard(game, permanent) -> bool:
    return not game.is_on_battlefield(permanent) and any(
        card is permanent.card for player in game.players for card in player.graveyard
    )


def _to_declare_attackers(game) -> None:
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.advance_combat_phase()  # the beginning of combat
    game.advance_combat_phase()  # …closed, and the declare attackers step entered
    assert game.current_step == "declare_attackers", game.current_step


def _to_declare_blockers(game, attackers, defender: int = 1) -> None:
    _to_declare_attackers(game)
    ok, why = game.declare_attackers(
        game.active_player_index,
        [game.battlefield_index_of(attacker) for attacker in attackers],
        defending_player_index=defender,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step


class Watch:
    """A priority driver that records, at each offer made in *step*, whether
    the state-based action under test has been performed — and passes."""

    def __init__(self, step: str, done):
        self.step, self.done, self.seen = step, done, []

    def __call__(self, game, seat) -> bool:
        if game.current_step == self.step:
            self.seen.append(self.done(game))
        return False


# --- the cases: a board, the step's turn-based action, and what is due --------
#
# Each returns (game, done, step, run) where ``run(game, how)`` steps into the
# step the way *how* drives it ("window" or "driver") and ``done(game)`` says
# whether the state-based action has been performed.


def _draw_from_an_empty_library(pool):
    """703.4d → 704.5b."""
    game = _game()
    _library(game, pool, 1)
    done = lambda g: g.players[0].lost

    def run(g, how):
        g.resolve_draw_step(0, defer_priority=how == "window")

    return game, done, "draw", run


def _a_skipped_draw_after_nafs_asp(pool):
    """The draw step's own effect before its draw: Nafs Asp's "that player
    loses 1 life at the beginning of their next draw step unless they pay {1}
    before that draw step", owed by a seat at 1 life with no mana — under a
    Necropotence ("Skip your draw step."). The step skips its draw and opens
    its window; the life loss is still 704.5a."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    _put(game, 0, pool["ICE"]["Necropotence"])
    game.players[0].life = 1
    # The record Nafs Asp's damage trigger files (`arm_draw_step_life_loss_unless_pay`).
    game.pending_draw_step_life_loss.append({
        "player_index": 0, "amount": 1, "cost": 1, "source_name": "Nafs Asp",
    })
    done = lambda g: g.players[0].lost

    def run(g, how):
        g.resolve_draw_step(0, defer_priority=how == "window")
        assert any("skips their draw step" in line for line in g.log), g.log[-3:]

    return game, done, "draw", run


def _untap_ends_a_tapped_only_static(pool):
    """703.4c → 704.5f: the lord untaps, its +0/+2 ends, a 2/2 with two
    -1/-1 counters is 0/0."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    lord = _put(game, 0, TAPPED_LORD)
    game.become_tapped(lord)
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    add_pt_counters(bears, "-1/-1", 2)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bears), "the board must stand before the step"
    done = lambda g: _in_graveyard(g, bears)

    def run(g, how):
        g.resolve_untap_step(0)
        g.resolve_upkeep(0, defer_priority=how == "window")

    return game, done, "upkeep", run


def _phasing_takes_a_lord_away(pool):
    """703.4a → 704.5f."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    _put(game, 0, PHASING_LORD)
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    add_pt_counters(bears, "-1/-1", 2)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bears), "the board must stand before the step"
    done = lambda g: _in_graveyard(g, bears)

    def run(g, how):
        g.resolve_untap_step(0)
        g.resolve_upkeep(0, defer_priority=how == "window")

    return game, done, "upkeep", run


def _attacking_taps_juniper_order_advocate(pool, *, with_trigger=False):
    """703.4i → 704.5g: "As long as this creature is untapped, green creatures
    you control get +1/+1." The Advocate taps to attack, and a Grizzly Bears
    dealt 2 damage this turn is a 2/2 again."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    advocate = _put(game, 0, pool["ALL"]["Juniper Order Advocate"])
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    attackers = [advocate]
    if with_trigger:
        attackers.append(_put(game, 0, HERALD))
    # Two pings from an opposing Prodigal Sorcerer earlier in the turn.
    pinger = _put(game, 1, pool["LEA"]["Prodigal Sorcerer"])
    assert game._mark_damage_on_permanent(bears, 2, source=pinger) == 2
    game.check_state_based_actions()
    assert game.is_on_battlefield(bears), "a 3/3 with 2 damage stands"
    done = lambda g: _in_graveyard(g, bears)

    def run(g, how):
        _to_declare_attackers(g)
        ok, why = g.declare_attackers(
            0, [g.battlefield_index_of(p) for p in attackers], defending_player_index=1,
        )
        assert ok, why
        if how == "driver":
            g.advance_combat_phase()

    return game, done, "declare_attackers", run


def _blocking_pays_heat_waves_life(pool, *, with_trigger=False):
    """703.4j → 704.5a: "Nonblue creatures can't block creatures you control
    unless their controller pays 1 life for each blocking creature they
    control." The defender, at 1, pays it."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    _put(game, 0, pool["VIS"]["Heat Wave"])
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    blocker = _put(game, 1, SENTRY if with_trigger else pool["LEA"]["Hill Giant"])
    game.players[1].life = 1
    done = lambda g: g.players[1].lost

    def run(g, how):
        _to_declare_blockers(g, [bears])
        ok, why = g.declare_blockers(
            1, {g.battlefield_index_of(blocker): g.battlefield_index_of(bears)},
        )
        assert ok, why
        if how == "driver":
            g.advance_combat_phase()

    return game, done, "declare_blockers", run


def _combat_damage_kills_a_blocker(pool):
    """703.4m → 704.5g."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    giant = _put(game, 0, pool["LEA"]["Hill Giant"])
    bears = _put(game, 1, pool["LEA"]["Grizzly Bears"])
    done = lambda g: _in_graveyard(g, bears)

    def run(g, how):
        _to_declare_blockers(g, [giant])
        ok, why = g.declare_blockers(
            1, {g.battlefield_index_of(bears): g.battlefield_index_of(giant)},
        )
        assert ok, why
        g.advance_combat_phase(allow_damage_skip=how != "window")

    return game, done, "combat_damage", run


def _cleanup_ends_a_pump(pool):
    """703.4p → 704.5f: Giant Growth, then Enfeeblement — a 3/3 until the
    +3/+3 ends."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    game._set_phase_and_step("precombat_main", "precombat_main")
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    _cast(game, 0, pool["LEA"]["Giant Growth"], bears)
    _cast(game, 0, pool["6ED"]["Enfeeblement"], bears)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    done = lambda g: _in_graveyard(g, bears)

    def run(g, how):
        g._set_phase_and_step("ending", "end")
        g.resolve_cleanup_step(0)

    return game, done, "cleanup", run


def _cleanup_ends_a_control_change(pool):
    """703.4p → 704.5j: Ray of Command took a legend on its controller's
    turn, who then cast the other copy; the steal ends in their cleanup."""
    game = _game()
    _library(game, pool, 0)
    _library(game, pool, 1)
    game.active_player_index = 1
    game._set_phase_and_step("precombat_main", "precombat_main")
    first = _put(game, 1, pool["LEG"]["Sir Shandlar of Eberyn"])
    _cast(game, 0, pool["5ED"]["Ray of Command"], first)
    assert game.controller_index_of(first) == 0
    second = _put(game, 1, pool["LEG"]["Sir Shandlar of Eberyn"])
    done = lambda g: sum(
        1 for p in g.controlled_by(1) if p.card.name == "Sir Shandlar of Eberyn"
    ) == 1 and (_in_graveyard(g, first) or _in_graveyard(g, second))

    def run(g, how):
        g._set_phase_and_step("ending", "end")
        g.resolve_cleanup_step(1)

    return game, done, "cleanup", run


CASES = {
    "703.4d draw from an empty library": _draw_from_an_empty_library,
    "the draw step's life loss before a skipped draw": _a_skipped_draw_after_nafs_asp,
    "703.4c untap ends a static": _untap_ends_a_tapped_only_static,
    "703.4a phasing takes a lord away": _phasing_takes_a_lord_away,
    "703.4i an attack taps a lord": _attacking_taps_juniper_order_advocate,
    "703.4i an attack taps a lord, a trigger on the stack": (
        lambda pool: _attacking_taps_juniper_order_advocate(pool, with_trigger=True)
    ),
    "703.4j a block pays life to 0": _blocking_pays_heat_waves_life,
    "703.4j a block pays life to 0, a trigger on the stack": (
        lambda pool: _blocking_pays_heat_waves_life(pool, with_trigger=True)
    ),
    "703.4m combat damage kills a blocker": _combat_damage_kills_a_blocker,
    "703.4p cleanup ends a pump": _cleanup_ends_a_pump,
    "703.4p cleanup ends a control change": _cleanup_ends_a_control_change,
    # "603.7 the end step sacrifices a lord" (Krovikan Elementalist's delayed
    # sacrifice of a Lord of Atlantis) was a case here while the end step
    # carried its delayed removals out inline before its window. Since kg5
    # each is a delayed triggered ability on the stack (CR 603.7), so it is
    # performed in the window like any resolution, and the check after it is
    # ``_check_between_resolutions``' (tests/rules/test_kg5_delayed_end_step_marks.py).
}


@pytest.fixture(scope="module")
def pool(set_pool):
    return {
        code: set_pool(code)
        for code in ("LEA", "ALL", "VIS", "6ED", "5ED", "LEG", "ICE")
    }


def _verdicts(pool, offers: list | None = None) -> dict:
    """``{(case, how): None | why}`` — None where the state-based action was
    performed before the step's first priority. *offers*, if given, collects
    how many times each driven step offered priority."""
    verdicts = {}
    for name, build in CASES.items():
        for how in ("window", "driver"):
            game, done, step, run = build(pool)
            watch = None
            if how == "driver":
                watch = game.priority_driver = Watch(step, done)
            run(game, how)
            if watch is not None and offers is not None:
                offers.append(len(watch.seen))
            if step == "cleanup":
                # CR 514.3a: no window unless the check finds something — the
                # moment is the end of the step, before the next turn begins.
                verdicts[(name, how)] = None if done(game) else "not done as cleanup ended"
                continue
            if how == "window":
                opened = game.priority_player_index is not None or game.is_game_over()
                if not opened:
                    verdicts[(name, how)] = "the step opened no priority window"
                elif not done(game):
                    verdicts[(name, how)] = "not done when the window opened"
                else:
                    verdicts[(name, how)] = None
                continue
            if not all(watch.seen):
                verdicts[(name, how)] = f"not done at an offer of priority ({watch.seen})"
            elif not watch.seen and not game.is_game_over():
                verdicts[(name, how)] = "the step offered no priority"
            elif not done(game):
                verdicts[(name, how)] = "not done by the end of the step"
            else:
                verdicts[(name, how)] = None
    return verdicts


@pytest.mark.cr("704.3", "117.5", "117.3a", "703.3", "514.3a")
def test_each_turn_based_action_is_followed_by_the_state_check(pool):
    offers: list = []
    verdicts = _verdicts(pool, offers)
    assert len(verdicts) == 2 * len(CASES) >= 22
    # …and the driver was asked: the steps that do not end the game offer
    # priority, so a census whose driver saw nothing would be measuring nothing.
    # Six with the end step's sacrifice among the cases; five since kg5.
    assert sum(1 for seen in offers if seen) >= 5, offers
    failing = {key: why for key, why in verdicts.items() if why}
    assert failing == {}


@pytest.mark.cr("704.3", "703.3")
def test_the_census_names_every_case_with_the_check_switched_off(pool, monkeypatch):
    """Backwards: with ``_check_after_turn_based_actions`` doing nothing, every
    case is named — so none of them is passing on some other sweep's account.

    On the tree before round ``kg`` (c42aec75) the census's first ten cases
    named the six whose steps had no check of their own — both attack cases
    and both block cases at the window, the two with a trigger on the stack at
    the driver's first offer too (the defender at 0 life *survived* there: its
    block trigger resolved first and gained the life back), and both cleanup
    cases at both — and passed the draw, untap, phasing and combat damage,
    whose checks this name now covers. The skipped draw (and the end step's
    sacrifice, a case until kg5 made it a stack object) were written after the
    fix; on that tree the step opened its window with no check
    (``_close_or_defer_step``'s skip exits), which is the switch below."""
    monkeypatch.setattr(Game, "_check_after_turn_based_actions", lambda self: False)
    verdicts = _verdicts(pool)
    named = {name for (name, _how), why in verdicts.items() if why}
    assert named == set(CASES)
