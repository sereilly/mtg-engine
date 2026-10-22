"""Two answers a seat nobody asks used to give without looking at the board.

* **The mode of a modal triggered ability** (CR 700.2b) — the pool prints
  four: Relic Bind, Elder Gargaroth, Trufflesnout and Apocalypse's Putrid
  Warrior. The registry's default was
  the first offered mode that is not a price, so Trufflesnout took its counter
  at three life and Relic Bind pinged an opponent at twenty while its
  controller sat at one. The default now asks the policy
  (``ai_prompts.choose_trigger_mode``), which answers the prompt in each
  offered mode on a scratch copy of the game and takes the one measured to do
  most — the valuation the cast chooser weighs a spell's bullets with.
* **"The color of your choice", for a sweep** — Root Greevil ("Destroy all
  enchantments of the color of your choice"), Wash Out, Dromar, the Banisher.
  The default colour was the one the opponents held most of among *every*
  permanent, so against an army of green creatures and one white enchantment
  Root Greevil named green and destroyed nothing. It is now the colour the
  sweep behind the choice is worth most in
  (``ai_prompt_readers.color_most_worth_sweeping``).
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_prompt_readers import chosen_color_sweeps, color_most_worth_sweeping
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers import EFFECT_HANDLERS
from engine.modal_triggers import modal_trigger_modes
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, *, hand=(), life=(20, 20)) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[forest] * 20, life=life[0]),
        PlayerState(name="Opp", library=[forest] * 20, life=life[1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _put(game, seat, card, *, tapped=False) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _settle(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()


# --- the mode of a modal triggered ability -----------------------------------


def test_the_pool_prints_four_modal_triggered_abilities(pool):
    """The floor: every one of them is driven below, and a fourth is a card
    this file has not looked at."""
    carriers = sorted(
        name for name, card in pool.items()
        if compile_card_oracle(card).supported and any(
            ability.instruction is not None and modal_trigger_modes(ability.instruction)
            for ability in compile_card_oracle(card).triggered_abilities
        )
    )
    assert carriers == [
        "Elder Gargaroth", "Putrid Warrior", "Relic Bind", "Trufflesnout",
    ]


def test_trufflesnout_takes_the_life_when_life_is_what_it_is_short_of(pool):
    """"Put a +1/+1 counter on this creature" or "You gain 4 life". At twenty
    life the counter is worth more than the life; at three it is not."""
    boar = pool["Trufflesnout"]
    healthy = _table(pool, hand=[boar])
    assert healthy.cast_from_hand(ME, "Trufflesnout").supported
    _settle(healthy)
    entered = next(iter(healthy.controlled_by(ME)))
    assert (entered.effective_power, entered.effective_toughness) == (3, 3)
    assert healthy.players[ME].life == 20

    dying = _table(pool, hand=[boar], life=(3, 20))
    assert dying.cast_from_hand(ME, "Trufflesnout").supported
    _settle(dying)
    entered = next(iter(dying.controlled_by(ME)))
    assert (entered.effective_power, entered.effective_toughness) == (2, 2)
    assert dying.players[ME].life == 7


def _relic_bind(pool, life):
    game = _table(pool, life=life)
    host = _put(game, OPP, _mk_card(name="Their Trinket", type_line="Artifact"))
    aura = _put(game, ME, pool["Relic Bind"])
    attach_aura(aura, host)
    return game, host


def test_relic_bind_pings_or_heals_by_which_is_worth_more(pool):
    """"This Aura deals 1 damage to target player or planeswalker" or "Target
    player gains 1 life", each time the enchanted artifact becomes tapped. A
    point of an opponent's twenty is worth less than a point of its
    controller's last four — and is worth the game when it is their last."""
    game, host = _relic_bind(pool, (20, 20))
    game.become_tapped(host)
    _settle(game)
    assert (game.players[ME].life, game.players[OPP].life) == (20, 19)

    game, host = _relic_bind(pool, (4, 20))
    game.become_tapped(host)
    _settle(game)
    assert (game.players[ME].life, game.players[OPP].life) == (5, 20)

    game, host = _relic_bind(pool, (4, 1))
    game.become_tapped(host)
    _settle(game)
    assert game.players[OPP].life == 0


def test_elder_gargaroth_makes_the_beast(pool):
    """Three modes — a 3/3 Beast, three life, a card — and the Beast measures
    most on every board a seat is alive on, which is also the first bullet.
    Here so the third carrier is driven through the same hook as the other
    two, and so a weight that ever puts a card above a 3/3 says so."""
    game = _table(pool)
    elder = _put(game, ME, pool["Elder Gargaroth"])
    game.start_turn(ME)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    slot = game.battlefield_index_of(elder)
    declared, why = game.declare_attackers(ME, [slot], defending_player_index=OPP)
    assert declared, why
    _settle(game)
    names = sorted(permanent.card.name for permanent in game.controlled_by(ME))
    assert len(names) == 2 and "Elder Gargaroth" in names
    assert game.players[ME].life == 20 and not game.players[ME].hand


@pytest.mark.parametrize("life, gains", [((3, 20), True), ((20, 3), False)])
def test_putrid_warrior_takes_the_side_of_the_swing_its_seat_is_short_of(
    pool, life, gains,
):
    """"Whenever this creature deals damage, choose one — • Each player loses
    1 life. • Each player gains 1 life." The two modes are symmetric, so what
    decides is that a point of life is worth more the less of it there is: at
    three against twenty the seat gains, and at twenty against a player its
    attack has just put on one, everybody loses."""
    game = _table(pool, life=life)
    warrior = _put(game, ME, pool["Putrid Warrior"])
    game.start_turn(ME)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    declared, why = game.declare_attackers(
        ME, [game.battlefield_index_of(warrior)], defending_player_index=OPP,
    )
    assert declared, why
    for _ in range(8):
        _settle(game)
        if game.players[OPP].life < life[1] or game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    _settle(game)
    swing = 1 if gains else -1
    assert game.players[ME].life == life[0] + swing, game.log[-6:]
    assert game.players[OPP].life == max(0, life[1] - 2 + swing), game.log[-6:]


def test_an_interactive_seat_is_still_asked(pool):
    """The hook is the *default*: a human's prompt is queued as it always
    was, with nothing chosen for them."""
    game = _table(pool, hand=[pool["Trufflesnout"]], life=(3, 20))
    game.interactive_seats = {ME}
    assert game.queue_from_hand(ME, "Trufflesnout").supported
    game.resolve_top_of_stack()
    assert [choice.kind for choice in game.pending_choices] == ["mode_choice"]
    assert game.players[ME].life == 3


# --- "the color of your choice", for a sweep ----------------------------------


def test_every_sweep_kind_named_is_a_registered_handler():
    """A kind renamed out from under the reader would silently restore the
    board-wide count."""
    from engine.ai_prompt_readers import _COLOR_SWEEP_KINDS

    assert set(_COLOR_SWEEP_KINDS) <= set(EFFECT_HANDLERS)


def test_the_sweeps_a_chosen_colour_narrows_are_read_off_the_program(pool):
    assert chosen_color_sweeps(pool["Root Greevil"]) == ({"type_filter": "enchantment"},)
    assert len(chosen_color_sweeps(pool["Wash Out"])) == 1
    assert len(chosen_color_sweeps(pool["Dromar, the Banisher"])) == 1
    # A colour chosen for something that is not a sweep of the board.
    assert chosen_color_sweeps(pool["Persecute"]) == ()


def _greevil_table(pool):
    """Root Greevil against four green creatures and one white enchantment,
    with a green enchantment of its controller's own."""
    game = _table(pool)
    greevil = _put(game, ME, pool["Root Greevil"])
    mine = _put(game, ME, _mk_card(name="Own Glade", type_line="Enchantment", colors=("G",)))
    for _ in range(4):
        _put(game, OPP, pool["Grizzly Bears"])
    theirs = _put(game, OPP, pool["Crusade"])
    return game, greevil, mine, theirs


def test_root_greevil_names_the_colour_its_sweep_is_worth_most_in(pool):
    """The opponents hold four green permanents and one white, so the
    board-wide count named green — and "destroy all green enchantments" hit
    one enchantment, the caster's own. The colour is for the sweep."""
    game, _greevil, mine, theirs = _greevil_table(pool)
    assert color_most_worth_sweeping(game, ME, pool["Root Greevil"]) == "W"
    game.players[ME].mana_pool["G"] = 3
    assert game.queue_permanent_ability(ME, "Root Greevil", ability_index=0).supported
    _settle(game)
    assert not game.is_on_battlefield(theirs), "the white enchantment was the one to take"
    assert game.is_on_battlefield(mine)
    assert sum(1 for p in game.controlled_by(OPP) if p.is_creature) == 4


def test_a_sweep_worth_nothing_in_any_colour_keeps_the_standing_default(pool):
    """No enchantment on the other side: no colour's sweep is worth more than
    nothing, the reader says so, and the choice falls through to the policy
    it always had."""
    game = _table(pool)
    _put(game, ME, pool["Root Greevil"])
    _put(game, OPP, pool["Grizzly Bears"])
    assert color_most_worth_sweeping(game, ME, pool["Root Greevil"]) is None
    assert color_most_worth_sweeping(game, ME, pool["Grizzly Bears"]) is None
