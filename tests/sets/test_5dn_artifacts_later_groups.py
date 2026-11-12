"""Fifth Dawn artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

import random as _w1g6_random

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_activation_spec as _w1g6_activation_spec
from tests.helpers import client as _w1g6_client
from tests.helpers import seat_plays_first as _w1g6_seat_plays_first
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hands=((), ()), interactive=(), start=True):
    """Two seats with Plains libraries; seat 0's first turn begun."""
    plains = set_pool("LEA")["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name=f"P{seat}", hand=list(hands[seat]), library=[plains] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    if start:
        game.start_turn(0)
        _w1g6_settle(game)
    return game


def _w1g6_put(game, seat, card, *, sick=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def test_w1g6_eon_hub_skips_every_players_upkeep_and_nothing_else(set_pool):
    """'Players skip their upkeep steps.' CR 614.10 / 500.11: the upkeep never
    begins — Cosmic Larva's "At the beginning of your upkeep, sacrifice this
    creature unless you sacrifice two lands" and Copper Tablet's "each
    player's upkeep" damage never trigger, on either player's turn (ruling
    2004-12-01: "Upkeep-triggered abilities don't trigger"), while the draw
    step goes on ("The turn proceeds from untap step to draw step"). Once the
    Hub has left, the next upkeep begins and both trigger."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool, start=False)
    hub = _w1g6_put(game, 1, fdn["Eon Hub"])
    larva = _w1g6_put(game, 0, fdn["Cosmic Larva"])
    _w1g6_put(game, 1, lea["Copper Tablet"])
    game.start_turn(0)
    _w1g6_settle(game)
    for _ in range(2):
        game.start_next_turn()
        _w1g6_settle(game)
    assert game.is_on_battlefield(larva)
    assert (game.players[0].life, game.players[1].life) == (20, 20)
    skips = [line for line in game.log if "skips their upkeep step (Eon Hub)" in line]
    assert len(skips) == 3, skips
    assert any(line == "P1 drew 1 card(s) in draw step" for line in game.log)
    assert not any("Copper Tablet" in line for line in game.log)

    game.remove_from_battlefield(hub)
    _w1g6_settle(game)
    active = game.start_next_turn()
    _w1g6_settle(game)
    assert active == 1 and game.players[1].life == 19
    active = game.start_next_turn()
    _w1g6_settle(game)
    assert active == 0 and game.players[0].life == 19
    # No lands to sacrifice, so the Larva goes.
    assert not game.is_on_battlefield(larva)


def test_w1g6_eon_hub_skips_a_persons_upkeep_in_the_web_beginning_phase(set_pool):
    """The web's own walk of the beginning phase (``turn_steps._begin_turn``)
    on a person's turn: the upkeep is skipped before any of it is gathered —
    Lord of the Pit's "sacrifice a creature" is never asked, the phase-rail
    upkeep stop is not honoured for a step that never begins, and the turn
    reaches its draw and main phase. Without the Hub the same turn stops on
    the Lord's question."""
    from web.turn_steps import _begin_turn

    fdn, lea = set_pool("5DN"), set_pool("LEA")
    for with_hub in (True, False):
        _w1g6_random.seed(3)
        sid = _w1g6_client.post(
            "/api/sessions", json={"mode": "human_vs_ai", "seed": 3}
        ).json()["session_id"]
        session = _w1g6_seat_plays_first(sid, 0)
        game = session.game
        for player in game.players:
            player.battlefield, player.hand, player.graveyard = [], [], []
            player.library = [lea["Plains"]] * 12
        if with_hub:
            _w1g6_put(game, 1, fdn["Eon Hub"])
        _w1g6_put(game, 0, lea["Lord of the Pit"])
        bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
        session.self_stop_steps.add("upkeep")
        game.turn += 1
        _begin_turn(session, 0)
        state = _w1g6_client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        if with_hub:
            assert "Player 1 skips their upkeep step (Eon Hub)" in game.log
            assert session.upkeep_pay_choices == [] and not game.pending_choices
            assert state["current_step"] == "precombat_main"
            assert state["players"][0]["hand_count"] == 1
            assert game.is_on_battlefield(bears)
        else:
            assert state["current_step"] == "upkeep", state["current_step"]


def test_w1g6_possessed_portal_skips_every_draw(set_pool):
    """'If a player would draw a card, that player skips that draw instead.'
    Every seat's draws, from a spell and in the draw step alike (CR 614.11:
    a replaced draw is no draw) — so nothing is drawn, the library stays as
    it was, and Underworld Dreams' "Whenever an opponent draws a card" sees
    none."""
    fdn, lea, eighth = set_pool("5DN"), set_pool("LEA"), set_pool("8ED")
    game = _w1g6_table(set_pool, hands=([lea["Ancestral Recall"]], ()))
    _w1g6_put(game, 1, fdn["Possessed Portal"])
    _w1g6_put(game, 0, eighth["Underworld Dreams"])
    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)
    assert result.supported, result
    _w1g6_settle(game)
    assert game.players[1].hand == [] and len(game.players[1].library) == 20
    assert game.log.count("P1 skipped a draw (Possessed Portal)") == 3
    game.start_next_turn()
    _w1g6_settle(game)
    assert game.players[1].hand == [] and len(game.players[1].library) == 20
    assert game.players[1].life == 20


def test_w1g6_possessed_portal_end_step_asks_each_player_in_turn(set_pool):
    """'At the beginning of each end step, each player sacrifices a permanent
    of their choice unless they discard a card.' Each player is offered the
    discard (CR 118.12a), in turn order, and a decline is that player's own
    sacrifice — at interactive seats: the active player declines and
    sacrifices the creature they name, the other discards. The toll used to be
    put to nobody in particular while the sacrifice swept every seat, so an
    empty-handed player never sacrificed; a seat with no card is not offered
    the discard and sacrifices."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hands=([lea["Lightning Bolt"]], [lea["Giant Growth"]]),
        interactive=(0, 1),
    )
    _w1g6_put(game, 0, fdn["Possessed Portal"])
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Forest"])
    asked = []

    def pay(game, choice):
        asked.append(("offer", choice.player_index))
        return game.confirm_optional_pay(choice.player_index, accept=choice.player_index == 1)

    def sacrifice(game, choice):
        asked.append(("sacrifice", choice.player_index))
        return game.confirm_sacrifice(choice.player_index, permanent_ids=[bears.permanent_id])

    def discard(game, choice):
        asked.append(("discard", choice.player_index))
        return game.confirm_discard(choice.player_index, [0])

    game.resolve_end_step(0)
    left = _w1g6_settle(
        game, answers={"optional_pay": pay, "sacrifice": sacrifice, "discard": discard},
        defaults=False,
    )
    assert left is None
    assert asked == [("offer", 0), ("sacrifice", 0), ("offer", 1), ("discard", 1)]
    assert not game.is_on_battlefield(bears) and len(game.players[0].hand) == 1
    assert [card.name for card in game.players[1].graveyard] == ["Giant Growth"]

    # The next end step, headless: seat 1 has no card to discard, so it
    # sacrifices its Forest; seat 0 discards the card it kept.
    game.interactive_seats = set()
    game.resolve_end_step(1)
    _w1g6_settle(game)
    assert game.players[0].hand == []
    assert [p.card.name for p in game.controlled_by(1)] == []


def test_w1g6_skullcage_counts_the_hand_as_it_resolves(set_pool):
    """'At the beginning of each opponent's upkeep, this artifact deals 2
    damage to that player unless they have exactly three or exactly four cards
    in hand.' Zero, one, two, five or more: 2 damage (ruling 2004-12-01);
    three or four: none; never on its controller's own upkeep. And the hand is
    counted only as the ability resolves (ruling 2004-12-01): a hand of three
    as it triggers and two by the time it resolves is damaged."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    for size, damaged in ((0, True), (2, True), (3, False), (4, False), (5, True)):
        game = _w1g6_table(set_pool, hands=((), [lea["Forest"]] * size))
        _w1g6_put(game, 0, fdn["Skullcage"])
        game.start_next_turn()  # seat 1's upkeep, before its draw
        _w1g6_settle(game)
        assert game.players[1].life == (18 if damaged else 20), size
        game.start_next_turn()  # seat 0's own upkeep
        _w1g6_settle(game)
        assert game.players[0].life == 20

    game = _w1g6_table(set_pool, hands=((), [lea["Forest"]] * 3))
    _w1g6_put(game, 0, fdn["Skullcage"])
    game.active_player_index = 1
    game.resolve_upkeep(1, defer_priority=True)
    assert [item.card.name for item in game.stack] == ["Skullcage"]
    game.players[1].hand = game.players[1].hand[:2]
    _w1g6_settle(game)
    assert game.players[1].life == 18


def test_w1g6_door_to_nothingness_announces_the_player_who_loses(set_pool):
    """'This artifact enters tapped. {W}{W}{U}{U}{B}{B}{R}{R}{G}{G}, {T},
    Sacrifice this artifact: Target player loses the game.' CR 104.3e. The
    activation announces its target player (CR 602.2b; the derivation offered
    no picker) and that player loses; the Door is sacrificed as the cost."""
    fdn = set_pool("5DN")
    door_card = fdn["Door to Nothingness"]
    ability = _w1g6_compile(door_card).activated_abilities[0]
    assert _w1g6_activation_spec(ability)["kind"] == "player"
    for loser in (1, 0):
        game = _w1g6_table(set_pool)
        game.enforce_mana_costs = True
        door = _w1g6_put(game, 0, door_card)
        assert door.tapped
        game.become_untapped(door)
        game.players[0].mana_pool.update({c: 2 for c in "WUBRG"})
        result = game.activate_permanent_ability(
            0, door_card.name, permanent_index=game.battlefield_index_of(door),
            target_player_index=loser,
        )
        assert result.supported, result
        _w1g6_settle(game)
        assert not game.is_on_battlefield(door)
        assert game.is_game_over()
        assert f"Door to Nothingness: P{loser} lost the game (104.3e)" in game.log

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
