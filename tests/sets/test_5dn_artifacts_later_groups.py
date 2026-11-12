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

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.linked_exile import face_down_exiled_cards as _w1g5_face_down
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_card(set_pool, name):
    for code in ("5DN", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), opponent_hand=(),
                interactive=()):
    """Costs not enforced, every permanent past summoning sickness, seat 0
    active in its first main phase. Cards from Fifth Dawn, else Alpha."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A",
                         hand=[_w1g5_card(set_pool, n) for n in hand],
                         library=[_w1g5_card(set_pool, "Island")] * 10),
        _W1G5PlayerState(name="W1G5-B",
                         hand=[_w1g5_card(set_pool, n) for n in opponent_hand],
                         library=[_w1g5_card(set_pool, "Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G5Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g5_settle(game)
    return game, rows[0], rows[1]  # _w1g5_table


def _w1g5_shackle(set_pool, *, islands=2, theirs=("Grizzly Bears", "Craw Wurm"), **kwargs):
    game, mine, theirs = _w1g5_table(
        set_pool, mine=["Vedalken Shackles"] + ["Island"] * islands,
        theirs=list(theirs), **kwargs,
    )
    return game, mine[0], mine[1:], theirs


def test_w1g5_vedalken_shackles_steals_only_a_creature_within_your_island_count(set_pool):
    """"{2}, {T}: Gain control of target creature with power less than or
    equal to the number of Islands you control for as long as this artifact
    remains tapped." With two Islands the Craw Wurm (6) cannot be named and
    nothing is paid finding out; the Grizzly Bears (2) are taken."""
    game, shackles, _islands, (bears, wurm) = _w1g5_shackle(set_pool)
    refused = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[wurm.permanent_id]
    )
    assert not refused.supported
    assert not shackles.tapped, "a refused activation pays nothing"
    taken = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    )
    assert taken.supported, taken.details
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    assert game.controller_index_of(wurm) == 1
    assert shackles.tapped


def test_w1g5_vedalken_shackles_keeps_a_creature_that_grows_past_the_count(set_pool):
    """The ruling (2004-12-01): "The creature's power and the number of
    Islands you control matter only when the ability is activated and when it
    resolves. After that, only the fact that Vedalken Shackles remains tapped
    matters." Giant Growth on the stolen Bears changes nothing."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(
        set_pool, opponent_hand=["Giant Growth"],
    )
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    grown = game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert grown.supported, grown.details
    _w1g5_settle(game)
    assert bears.effective_power == 5
    assert game.controller_index_of(bears) == 0


def test_w1g5_vedalken_shackles_counts_your_islands_as_it_resolves(set_pool):
    """CR 608.2b: the bound is asked again on resolution. An Island leaving
    in response leaves one, the Bears' 2 power is past it, and the ability does
    nothing."""
    game, _shackles, islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    assert game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.remove_from_battlefield(islands[0])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untapped_in_response_steals_nothing(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles becomes untapped before
    its ability resolves, you won't gain control of the creature." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    assert game.become_untapped(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untap_choice_is_the_whole_card(set_pool):
    """"You may choose not to untap this artifact during your untap step."
    The choice is offered at seat 0's untap step; a seat nobody sits in keeps
    the Shackles tapped while the steal is live, and choosing to untap it
    (the person's answer, ``keep_tapped_ids=[]``) gives the Bears back —
    as does the Shackles leaving the battlefield (the ruling: "it's no longer
    tapped, so the control-changing effect ends")."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0

    assert [entry["id"] for entry in game.get_optional_untap_permanents(0)] == [
        shackles.permanent_id
    ]
    game.start_turn(1)
    _w1g5_settle(game)
    game.start_turn(0)
    _w1g5_settle(game)
    assert shackles.tapped, "headless play keeps a live steal"
    assert game.controller_index_of(bears) == 0

    game.start_turn(1)
    _w1g5_settle(game)
    game.resolve_untap_step(0, keep_tapped_ids=[])
    _w1g5_settle(game)
    assert not shackles.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_leaving_ends_the_steal(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles leaves the battlefield,
    it's no longer tapped, so the control-changing effect ends." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    game.remove_from_battlefield(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def _w1g5_egg(set_pool, hand, *, pick=None, interactive=()):
    """Seat 0 casts Summoner's Egg holding *hand*; with *pick* (seat 0
    interactive) it takes the imprint offer and exiles that card by name.
    Returns ``(game, egg)`` with the Egg on the battlefield."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Summoner's Egg", *hand], opponent_hand=["Disenchant"],
        interactive=interactive,
    )
    assert game.queue_from_hand(0, "Summoner's Egg").supported
    answers = {}
    if pick is not None:
        hand_of = game.players[0].hand
        answers = {
            "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
            "exile_from_hand_choice": lambda g, c: g.confirm_exile_from_hand_choice(
                c.player_index,
                next(i for i, card in enumerate(hand_of) if card.name == pick),
            ),
        }
    _w1g5_settle(game, answers=answers)
    egg = next(
        p for p in game.controlled_by(game.players[0]) if p.card.name == "Summoner's Egg"
    )
    return game, egg


def _w1g5_disenchant(game, permanent):
    game.active_player_index = 1
    cast = game.queue_from_hand(1, "Disenchant", target_permanent_ids=[permanent.permanent_id])
    assert cast.supported, cast.details
    _w1g5_settle(game)


def test_w1g5_summoners_egg_hatches_the_imprinted_creature_when_it_dies(set_pool):
    """"Imprint — When this creature enters, you may exile a card from your
    hand face down. When this creature dies, turn the exiled card face up. If
    it's a creature card, put it onto the battlefield under your control."
    The Craw Wurm is exiled face down — hidden from every seat, its owner
    included (CR 406.3; the ruling: "you can't look at the card once it's
    imprinted"), and unnamed in the log — and enters when the Egg dies."""
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm", "Lightning Bolt"], pick="Craw Wurm", interactive=(0,),
    )
    wurm = _w1g5_card(set_pool, "Craw Wurm")
    assert [c.name for c in _w1g5_face_down(game, 0, 0)] == ["Craw Wurm"]
    assert [c.name for c in _w1g5_face_down(game, 0, 1)] == ["Craw Wurm"]
    assert not any("Craw Wurm" in line for line in game.log)
    _w1g5_disenchant(game, egg)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Craw Wurm"]
    assert all(card is not wurm for card in game.players[0].exile)
    assert "Summoner's Egg turns Craw Wurm face up in exile" in game.log


def test_w1g5_summoners_egg_leaves_a_noncreature_card_exiled_face_up(set_pool):
    """The ruling (2004-12-01): "If the card is not a creature card when it's
    turned face up, it remains exiled face up." """
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm", "Lightning Bolt"], pick="Lightning Bolt", interactive=(0,),
    )
    _w1g5_disenchant(game, egg)
    assert list(game.controlled_by(game.players[0])) == []
    assert [c.name for c in game.players[0].exile] == ["Lightning Bolt"]
    assert _w1g5_face_down(game, 0) == []
    assert "no creature card is exiled with Summoner's Egg" in game.log


def test_w1g5_summoners_egg_leaving_without_dying_keeps_the_card_face_down(set_pool):
    """Only "dies" turns the card up: an Egg returned to its owner's hand
    leaves its imprint exiled face down for good (CR 406.3 has no ending)."""
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm"], pick="Craw Wurm", interactive=(0,),
    )
    game.remove_from_battlefield(egg)
    game.players[0].hand.append(egg.card)
    _w1g5_settle(game)
    assert [c.name for c in _w1g5_face_down(game, 0)] == ["Craw Wurm"]
    assert list(game.controlled_by(game.players[0])) == []


def test_w1g5_summoners_egg_seat_nobody_asks_imprints_its_best_creature(set_pool):
    """A seat nobody asks takes the offer and imprints the most expensive
    creature card — the one the dies trigger would hatch — not the cheapest
    card in hand (``ai_prompt_readers.linked_exile_returns_to_battlefield``)."""
    game, egg = _w1g5_egg(set_pool, ["Lightning Bolt", "Grizzly Bears", "Craw Wurm"])
    assert [c.name for c in _w1g5_face_down(game, 0)] == ["Craw Wurm"]
    _w1g5_disenchant(game, egg)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Craw Wurm"]

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
#
# Doubling Cube: CR 701.10f's "double … unspent mana", a mana ability.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.mana_abilities import is_mana_ability as _w1g7_is_mana_ability
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, mine=(), enforce=False):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(name=f"P{seat}", library=[lea["Island"]] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.start_turn(0)
    _w1g7_settle(game)
    placed = []
    for card in mine:
        permanent = _W1G7Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    _w1g7_settle(game)
    return game, placed


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_doubling_cube_doubles_each_type_and_copies_no_restriction(set_pool):
    """Its rulings (2004-12-01): the type is the colour or colourless, and
    "Any restrictions on the unspent mana aren't copied" — artifacts-only
    {U}{U}{U} stays as it was and {U}{U}{U} for anything joins it. It is a
    mana ability: it never touches the stack."""
    cube = set_pool("5DN")["Doubling Cube"]
    assert _w1g7_is_mana_ability(_w1g7_compile(cube).activated_abilities[0])
    game, (permanent,) = _w1g7_table(set_pool, mine=[cube])
    player = game.players[0]
    player.mana_pool.update({"W": 1, "B": 2, "C": 4})
    player.restricted_mana.setdefault("artifact", {})["U"] = 3

    result = game.activate_permanent_ability(0, "Doubling Cube")

    assert result.supported, result
    assert not game.stack
    assert permanent.tapped
    assert _w1g7_pool(player) == {"W": 2, "U": 3, "B": 4, "C": 8}
    assert player.restricted_mana["artifact"] == {"U": 3}


def test_w1g7_doubling_cube_doubles_what_is_left_after_its_own_cost(set_pool):
    """CR 602.2/605.3: the {3} is paid as the ability is activated and the
    effect doubles the pool it leaves — five {C} pay three and the two left
    become four. An empty pool adds nothing."""
    cube = set_pool("5DN")["Doubling Cube"]
    game, _ = _w1g7_table(set_pool, mine=[cube], enforce=True)
    player = game.players[0]
    player.mana_pool["C"] = 5

    result = game.activate_permanent_ability(0, "Doubling Cube")

    assert result.supported, result
    assert _w1g7_pool(player) == {"C": 4}
    assert "Doubling Cube doubled P0's unspent mana, adding {C}{C}" in game.log

    game, _ = _w1g7_table(set_pool, mine=[cube])
    game.activate_permanent_ability(0, "Doubling Cube")
    assert _w1g7_pool(game.players[0]) == {}
    assert "Doubling Cube: P0 has no unspent mana to double" in game.log

# ==== end w1g7 ======================================================
