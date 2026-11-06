"""Every question a split damage sentence asks is asked in APNAP order.

CR 616.1: "If two or more players have to make these choices at the same
time, choices are made in APNAP order (see rule 101.4)." CR 101.4: the
active player "makes any choices required, then the next player in turn
order …". One printed damage sentence the lowering splits into steps
(``oracle_types.ONE_DEALING``) is one simultaneous dealing (CR 608.2f), so
every affected player's CR 616.1e choices about all of it are made at once:
the active player's — about themself and each permanent they control, across
every step — before the next player's.

kg3 ordered a split sentence's **steps** by the player each affects, and only
where every step names one recipient it can say before it runs
(``control_flow._in_apnap_order``); a sentence with a sweep or "each player"
in it, or a recipient that function did not read, kept the printed order, so
the seats were asked step by step:

* Disorder — "2 damage to each white creature and each player who controls a
  white creature": the active player and then the other about their white
  creatures, and then both again about themselves;
* Kaervek's Hex — two sweeps, each across both seats;
* Warpath — "each blocking creature and each blocked creature": the defender
  (blockers, printed first) before the active player;
* Bellowing Fiend — "3 damage to that creature's controller and 3 damage to
  you", the first recipient a frozen seat: the damaged creature's controller
  before the active player.

``handlers/control_flow.sequence`` now has the dealing collect every chunk
the steps produce at the damage seams (``simultaneous_damage.begin_sentence``,
``collect``) and deal them as one loop in APNAP order of the seat each one's
question goes to, the printed order within a seat (CR 101.4c)
(``deal_sentence``). Hail Storm, whose printed order is already APNAP on
every board it can be cast on, is the control.

Measured backwards on 313bd09d: Disorder asked [0, 1, 0, 1] (three seats:
[1, 2, 0, 1, 2, 0]), Kaervek's Hex [0, 1, 0, 1], Warpath [1, 0] and Bellowing
Fiend [1, 0]; the control and the totals pass there too.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.shields import add_shield, make_counting_pool, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(seats: int = 2, *, active: int = 0) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _contend(*recipients) -> None:
    """Two prevention effects on each recipient, each large enough to stay
    applicable for every chunk the sentence deals it: each chunk's event asks
    its affected player which applies first (CR 616.1e)."""
    for recipient in recipients:
        add_shield(recipient, make_numeric_pool(10, source_name="Test Pool A"))
        add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Test Pool B"))


def _cast(game: Game, seat: int, card: CardDefinition, **kwargs) -> None:
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(seat, card.name, **kwargs)
    assert result.supported, result.details


def _asked(game: Game) -> list[int]:
    """Resolve the stack, answering each CR 616.1e question as it is asked,
    and return the seat each was asked of, in order."""
    asked: list[int] = []
    for _ in range(64):
        owed = [c for c in game.pending_choices if c.kind == "effect_order"]
        if owed:
            seat = owed[0].player_index
            asked.append(seat)
            assert game.resolve_pending_choice("effect_order", seat, option_index=0)
            continue
        if not game.stack:
            break
        game.resolve_top_of_stack(pause_for_choices=True)
    assert not game.pending_choices, game.pending_choices
    assert game.simultaneous_damage is None
    return asked


def _to_blocks(game: Game, attacker: Permanent, blocker: Permanent) -> None:
    active = game.active_player_index
    game.start_turn(active)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, why = game.declare_attackers(
        active, [game.battlefield_index_of(attacker)],
        defending_player_index=1 - active,
    )
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(
        1 - active, {game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)},
    )
    assert ok, why


@pytest.mark.cr("616.1", "101.4", "608.2f")
@pytest.mark.parametrize("active", [0, 1])
def test_disorder_asks_each_seat_about_its_creature_and_itself_together(active):
    game = _table(active=active)
    angels = [_put(game, seat, "Serra Angel") for seat in (0, 1)]
    _contend(*game.players, *angels)
    game.interactive_seats = {0, 1}

    _cast(game, active, _POOL["Disorder"])

    other = 1 - active
    assert _asked(game) == [active, active, other, other], game.log[-12:]


@pytest.mark.cr("616.1", "101.4")
def test_disorder_at_three_seats_goes_round_the_table_from_the_active_player():
    game = _table(3, active=1)
    angels = [_put(game, seat, "Serra Angel") for seat in range(3)]
    _contend(*game.players, *angels)
    game.interactive_seats = {0, 1, 2}

    _cast(game, 1, _POOL["Disorder"])

    assert _asked(game) == [1, 1, 2, 2, 0, 0], game.log[-16:]


@pytest.mark.cr("616.1", "101.4c")
def test_kaervek_s_hex_asks_about_both_chunks_of_a_green_creature_before_the_next_seat():
    """A green creature is nonblack too: two chunks, both its controller's
    questions, asked one after the other in the order printed."""
    game = _table()
    bears = [_put(game, seat, "Grizzly Bears") for seat in (0, 1)]
    _contend(*bears)
    game.interactive_seats = {0, 1}

    _cast(game, 0, _POOL["Kaervek's Hex"])

    assert _asked(game) == [0, 0, 1, 1], game.log[-12:]
    # Each chunk's first effect prevented it: nothing was dealt.
    assert [bear.damage_marked for bear in bears] == [0, 0]


@pytest.mark.cr("616.1", "101.4", "608.2f")
def test_warpath_asks_the_attacker_about_the_blocked_creature_first():
    """"…to each blocking creature and each blocked creature." The blockers
    are printed first and are the defender's; the blocked attacker is the
    active player's, whose question comes first."""
    game = _table()
    attacker = _put(game, 0, "Grizzly Bears")
    blocker = _put(game, 1, "Grizzly Bears")
    _to_blocks(game, attacker, blocker)
    _contend(attacker, blocker)
    game.interactive_seats = {0, 1}

    _cast(game, 0, _POOL["Warpath"])

    assert _asked(game) == [0, 1], game.log[-10:]


@pytest.mark.cr("616.1", "101.4")
def test_bellowing_fiend_asks_you_before_the_damaged_creature_s_controller():
    """"Whenever this creature deals damage to a creature, this creature deals
    3 damage to that creature's controller and 3 damage to you." On its
    controller's turn the controller is the active player."""
    game = _table()
    fiend = _put(game, 0, "Bellowing Fiend")
    angel = _put(game, 1, "Serra Angel")
    _to_blocks(game, fiend, angel)
    _contend(*game.players)
    game.interactive_seats = {0, 1}

    game.advance_combat_phase()  # combat damage: the Fiend deals 3 to the Angel
    assert angel.damage_marked == 3, game.log[-10:]

    assert _asked(game) == [0, 1], game.log[-10:]


@pytest.mark.cr("616.1", "101.4")
def test_hail_storm_s_printed_order_is_already_apnap():
    """The control: "2 damage to each attacking creature and 1 damage to you
    and each creature you control", cast by the defender. The attackers are
    the active player's and come first in print and in turn order alike."""
    game = _table()
    attacker = _put(game, 0, "Grizzly Bears")
    blocker = _put(game, 1, "Grizzly Bears")
    _to_blocks(game, attacker, blocker)
    _contend(game.players[1], attacker, blocker)
    game.interactive_seats = {0, 1}

    _cast(game, 1, _POOL["Hail Storm"])

    assert _asked(game) == [0, 1, 1], game.log[-10:]


@pytest.mark.cr("608.2f", "120.8")
def test_nobody_asked_disorder_deals_what_it_prints():
    """The totals are the printed ones. Disorder's ruling (2004-10-04):
    "Players take 0 or 2 damage. Disorder does not do 2 damage per creature
    to the player.\""""
    game = _table()
    angel = _put(game, 0, "Serra Angel")
    lions = _put(game, 0, "Savannah Lions")
    bears = _put(game, 1, "Grizzly Bears")
    _cast(game, 0, _POOL["Disorder"])
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (18, 20), game.log[-8:]
    assert (angel.damage_marked, bears.damage_marked) == (2, 0)
    assert not game.is_on_battlefield(lions)
    assert game.log.count("Disorder dealt 2 damage to P0") == 1, game.log[-8:]
    assert game.log.count("Disorder dealt 2 damage to Serra Angel, Savannah Lions") == 1, game.log[-8:]
    assert game.simultaneous_damage is None
