"""CR 514.3a: the cleanup step's one exception to "no player receives priority".

    514.3a At this point, the game checks to see if any state-based actions
    would be performed and/or any triggered abilities are waiting to be put
    onto the stack (including those that trigger "at the beginning of the next
    cleanup step"). If so, those state-based actions are performed, then those
    triggered abilities are put on the stack, then the active player gets
    priority. Players may cast spells and activate abilities. Once the stack
    is empty and all players pass in succession, another cleanup step begins.

Three halves, each a board here, driven where the engine gives priority to a
table whose seats a driver plays (``Game.priority_driver``, the simulator's):

* **a state-based action alone opens the window** — on e245e624c the step gave
  priority only when something had triggered;
* **what is cast in the window is undone by the next cleanup step** — an
  "until end of turn" pump ends and marked damage is removed. On e245e624c a
  second cleanup step was begun only for a hand over its maximum, so a Giant
  Growth cast in response to Thawing Glaciers' return lasted the whole of the
  next turn;
* **the step after it counts no turn twice** — Peace Talks' "this turn and
  next turn" is a count of turns, and a cleanup that runs two steps must not
  end it a turn early.

The web layer holds no cleanup window for a person (``web/game_flow.
_advance_phase``), so an interactive table still has the window collapsed to
its outcome — the objects resolve in the step, nobody is asked.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import _nosick, settle


@pytest.fixture(scope="module")
def pool(set_pool):
    return {
        code: set_pool(code)
        for code in ("LEA", "ALL", "VIS", "6ED")
    }


def _game(pool) -> Game:
    forest = pool["LEA"]["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 10),
        PlayerState("P2", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _cast(game, seat: int, card, target=None) -> None:
    game.players[seat].hand.append(card)
    kwargs = {} if target is None else {"target_permanent_ids": [target.permanent_id]}
    result = game.cast_from_hand(seat, card.name, **kwargs)
    assert result.supported, result.details
    settle(game)


class Offers:
    """A ``priority_driver`` that records every offer as ``(step, seat,
    stack size)`` and passes — or, given *act*, lets it act once."""

    def __init__(self, act=None):
        self.seen: list[tuple] = []
        self.act = act

    def __call__(self, game, seat) -> bool:
        self.seen.append((game.current_step, seat, len(game.stack)))
        if self.act is not None and self.act(game, seat):
            self.act = None
            return True
        return False


def _cleanup_ends_a_pump(pool):
    """Giant Growth, then Enfeeblement: a 3/3 until the +3/+3 ends, and then a
    0/0 (CR 704.5f)."""
    game = _game(pool)
    bears = _put(game, 0, pool["LEA"]["Grizzly Bears"])
    _cast(game, 0, pool["LEA"]["Giant Growth"], bears)
    _cast(game, 0, pool["6ED"]["Enfeeblement"], bears)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    return game, bears


@pytest.mark.cr("514.3a", "704.5f")
def test_a_state_based_action_alone_gives_the_active_player_priority(pool):
    game, bears = _cleanup_ends_a_pump(pool)
    offers = game.priority_driver = Offers()

    assert game.resolve_cleanup_step(0)

    assert not game.is_on_battlefield(bears)
    cleanup = [offer for offer in offers.seen if offer[0] == "cleanup"]
    assert cleanup[:2] == [("cleanup", 0, 0), ("cleanup", 1, 0)], offers.seen


@pytest.mark.cr("514.3a")
def test_a_cleanup_with_nothing_to_do_gives_nobody_priority(pool):
    game = _game(pool)
    _put(game, 0, pool["LEA"]["Grizzly Bears"])
    offers = game.priority_driver = Offers()

    assert game.resolve_cleanup_step(0)

    assert offers.seen == []


def _glaciers_table(pool):
    """Thawing Glaciers activated on P1's turn: its "return this land to its
    owner's hand at the beginning of the next cleanup step" waits for P1's
    cleanup. P2 has a Craw Wurm, a Giant Growth and a Lightning Bolt."""
    game = _game(pool)
    glaciers = _put(game, 0, pool["ALL"]["Thawing Glaciers"])
    glaciers.tapped = False   # it entered tapped; a turn has gone by
    game.players[0].library = [pool["LEA"]["Forest"]] * 10
    result = game.activate_permanent_ability(
        0, "Thawing Glaciers",
        source_permanent_index=game.players[0].battlefield.index(glaciers),
    )
    assert result.supported, result.details
    settle(game)
    wurm = _put(game, 1, pool["LEA"]["Craw Wurm"])
    game.players[1].hand.extend([pool["LEA"]["Giant Growth"], pool["LEA"]["Lightning Bolt"]])
    return game, glaciers, wurm


@pytest.mark.parametrize("spell", ["Giant Growth", "Lightning Bolt"])
@pytest.mark.cr("514.3a", "514.2")
def test_what_is_cast_in_the_window_ends_with_the_next_cleanup_step(pool, spell):
    """P2 is given priority with Glaciers' return on the stack and casts an
    instant at its own Craw Wurm. The cleanup step that begins once the stack
    is empty ends the +3/+3 and removes the 3 damage (CR 514.2), so the Wurm
    starts P2's turn a 6/4 with no damage."""
    game, glaciers, wurm = _glaciers_table(pool)

    def respond(table, seat):
        if seat != 1 or not table.stack or table.current_step != "cleanup":
            return False
        return table.cast_from_hand(
            1, spell, target_permanent_ids=[wurm.permanent_id],
        ).supported

    offers = game.priority_driver = Offers(act=respond)
    assert game.resolve_cleanup_step(0)
    settle(game)

    assert offers.act is None, f"P2 never cast {spell} in the cleanup step: {offers.seen}"
    assert any(card is glaciers.card for card in game.players[0].hand)
    assert game.is_on_battlefield(wurm)
    assert (wurm.effective_power, wurm.effective_toughness, wurm.damage_marked) == (6, 4, 0)


@pytest.mark.cr("514.3a", "611.2a")
def test_a_second_cleanup_step_counts_no_turn_twice(pool):
    """Peace Talks, then a cleanup that runs two steps (the pump's end kills a
    creature, CR 514.3a opens the window, another cleanup step begins): "this
    turn and next turn" still holds on P2's turn, and ends with it."""
    game, bears = _cleanup_ends_a_pump(pool)
    raider = _put(game, 1, pool["LEA"]["Grizzly Bears"])
    _cast(game, 0, pool["VIS"]["Peace Talks"])
    assert game.attack_restrictions_until_eot and game.targeting_bans
    offers = game.priority_driver = Offers()

    assert game.resolve_cleanup_step(0)
    assert not game.is_on_battlefield(bears)
    assert any(offer[0] == "cleanup" for offer in offers.seen), offers.seen
    game.priority_driver = None

    game.start_next_turn()
    assert game.active_player_index == 1
    assert game.attack_restrictions_until_eot and game.targeting_bans
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    slot = game.players[1].battlefield.index(raider)
    assert not game.declare_attackers(1, [slot])[0]

    game.resolve_cleanup_step(1)
    assert not game.attack_restrictions_until_eot and not game.targeting_bans


@pytest.mark.cr("514.1", "611.2a")
def test_a_discard_chosen_later_counts_the_turn_once(pool):
    """The web's cleanup with a person's discard runs the step twice: once to
    find the discard owed (``defer_discard_selection``), once with it chosen.
    Peace Talks' "this turn and next turn" was counted by both, so it ended at
    the end of the turn it was cast in — the reproduction, on e245e624c:
    ``remaining_turns`` 2, then 1, then the entry gone."""
    game = _game(pool)
    game.players[0].hand.extend([pool["LEA"]["Forest"]] * 9)
    _cast(game, 0, pool["VIS"]["Peace Talks"])
    assert len(game.players[0].hand) == 9

    assert game.resolve_cleanup_step(0, defer_discard_selection=True) is False
    assert game.resolve_cleanup_step(0, discard_hand_indices=[0, 1]) is True

    assert len(game.players[0].hand) == 7
    assert [entry["remaining_turns"] for entry in game.attack_restrictions_until_eot] == [1]
    assert [entry["remaining_turns"] for entry in game.targeting_bans] == [1]
