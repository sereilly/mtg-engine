"""Census: a draw an interactive replacement suspended is counted by the
sentence behind it.

"Draw X cards. **For each card drawn this way**, discard a card unless you
sacrifice a permanent." (Read the Runes.) "…then this enchantment deals damage
to the player equal to **the number of cards they drew this way**." (Malignant
Growth.) "For each card less than two a player **draws this way**, that player
gains 2 life." (Truce.) Each reads a record its draw writes —
``oracle_types.DREW_COUNT`` or ``DREW_BY_SEAT`` — and the draw wrote what
``Game._draw_with_replacements`` returned: 0 for a draw an interactive
replacement suspends (Obstinate Familiar's "you may skip that draw" offered to
a person), whose cards arrive with the answer. Measured at round ``kg3``'s
base: Read the Runes for two under an interactive Familiar, both draws
answered "draw", drew two cards, recorded 0 and discarded nothing.

The record is now the draw's last resumable step, counted from the drawer's
``cards_drawn_this_turn``. The census asks the pool which cards read either
record and which writer feeds each; every writer kind found is driven here,
by a shipped card that reads it, with the drawer interactive (each pattern of
answers) and with the drawer a seat nobody asks.
"""

from __future__ import annotations

import json

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from engine.oracle_types import DREW_BY_SEAT, DREW_COUNT

_CARDS = {card.name: card for card in load_catalog()}

#: The writer kinds of the two records, and the shipped card that drives each
#: one here.
DRIVEN = {
    "draw_controller_cards": "Read the Runes",
    "draw_target_cards": "Malignant Growth",
    "each_player_draws_up_to_cards": "Truce",
}
_WRITERS = {*DRIVEN, "draw_up_to_cards"}


def _nodes(obj, out):
    if hasattr(obj, "kind") and hasattr(obj, "payload"):
        out.append(obj)
        _nodes(obj.payload, out)
    elif isinstance(obj, dict):
        for value in obj.values():
            _nodes(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _nodes(value, out)
    return out


def _readers() -> dict[str, set[str]]:
    """``{card name: writer kinds}`` for every compiled ability in the pool
    that holds a draw writer and reads one of its records."""
    found: dict[str, set[str]] = {}
    for card in compilation_units(load_catalog()):
        program = compile_card_oracle(card)
        roots = [
            *program.instructions,
            *(a.instruction for a in program.activated_abilities if a.instruction),
            *(t.instruction for t in program.triggered_abilities if t.instruction),
        ]
        for root in roots:
            nodes = _nodes(root, [])
            writers = {node.kind for node in nodes if node.kind in _WRITERS}
            reads = any(
                key in json.dumps(node.payload, default=str)
                for node in nodes for key in (DREW_COUNT, DREW_BY_SEAT)
            )
            if writers and reads:
                found.setdefault(card.name, set()).update(writers)
    return found


def test_every_writer_a_pool_reader_depends_on_is_driven_here():
    readers = _readers()
    assert len(readers) >= 3, readers
    fed = set().union(*readers.values())
    assert fed <= set(DRIVEN), sorted(fed - set(DRIVEN))
    assert {DRIVEN[kind] for kind in fed} <= set(readers), readers


# -- the boards ---------------------------------------------------------------


def _perm(name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(*, hands=((), ()), boards=((), ()), interactive=(0, 1), active=0) -> Game:
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=[_CARDS[name] for name in hands[seat]],
            library=[_CARDS[name] for name in ("Forest", "Island", "Swamp", "Mountain") * 3],
            battlefield=[_perm(name) for name in boards[seat]],
        )
        for seat in range(2)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.start_priority_window(active)
    return game


def _answer(game: Game, skips: list[bool]) -> list[str]:
    """Answer every owed decision: each Familiar offer from *skips* in turn
    ("draw the card" is option 0), everything else with its default. Returns
    the offer kinds answered."""
    answered: list[str] = []
    skips = list(skips)
    for _ in range(40):
        if game.pending_replacement_choices:
            choice = game.pending_replacement_choices[0]
            assert choice.kind == "skip_draw", choice.kind
            assert game.resolve_replacement_choice(
                choice.player_index, 1 if skips.pop(0) else 0, kind=choice.kind
            )
            answered.append(choice.kind)
            continue
        owed = [choice for _spec, choice in game.iter_pending_prompts()]
        if owed:
            game.auto_resolve_choice(owed[0])
            continue
        if game.stack:
            game.resolve_top_of_stack(pause_for_choices=True)
            continue
        break
    assert not skips, skips
    return answered


#: (the Familiar's answers, cards drawn).
PATTERNS = [([False, False], 2), ([False, True], 1), ([True, True], 0)]


@pytest.mark.parametrize("skips,drawn", PATTERNS)
def test_read_the_runes_counts_the_draws_an_interactive_familiar_let_through(skips, drawn):
    game = _game(hands=(("Read the Runes", "Shock", "Grizzly Bears"), ()),
                 boards=(("Obstinate Familiar",), ()))
    caster = game.players[0]
    game.cast_from_hand(0, "Read the Runes", x_value=2)
    assert _answer(game, skips) == ["skip_draw", "skip_draw"]
    assert len(caster.cards_drawn_this_turn) == drawn
    # One card discarded or one permanent sacrificed per card drawn this way:
    # everything in the graveyard but the spell itself.
    given_up = [card.name for card in caster.graveyard if card.name != "Read the Runes"]
    assert len(given_up) == drawn, (given_up, game.log)
    assert f"Read the Runes drew {drawn} card" in game.log
    assert "Read the Runes drew 0 card" not in game.log or drawn == 0


def test_read_the_runes_under_a_familiar_nobody_is_asked_about():
    game = _game(hands=(("Read the Runes", "Shock", "Grizzly Bears"), ()),
                 boards=(("Obstinate Familiar",), ()), interactive=())
    caster = game.players[0]
    game.cast_from_hand(0, "Read the Runes", x_value=2)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert len(caster.cards_drawn_this_turn) == 2
    assert len([c for c in caster.graveyard if c.name != "Read the Runes"]) == 2, game.log


def _growth_board(interactive):
    """Malignant Growth with two growth counters on seat 0; seat 1, whose
    draw step it is, controls Obstinate Familiar."""
    game = _game(boards=(("Malignant Growth",), ("Obstinate Familiar",)),
                 interactive=interactive, active=1)
    growth = game.players[0].battlefield[0]
    add_counters(growth, "growth", 2)
    game._set_phase_and_step("beginning", "draw")
    return game


@pytest.mark.parametrize("skips,drawn", PATTERNS)
def test_malignant_growth_deals_what_an_interactive_familiar_let_through(skips, drawn):
    game = _growth_board(interactive=(0, 1))
    victim = game.players[1]
    game._enqueue_draw_step_triggers(1)
    assert _answer(game, skips) == ["skip_draw", "skip_draw"]
    assert len(victim.cards_drawn_this_turn) == drawn
    assert victim.life == 20 - drawn, game.log
    assert f"P1 drew {drawn} cards" in game.log


def test_malignant_growth_under_a_familiar_nobody_is_asked_about():
    game = _growth_board(interactive=())
    victim = game.players[1]
    game._enqueue_draw_step_triggers(1)
    game.resolve_stack()
    assert len(victim.cards_drawn_this_turn) == 2
    assert victim.life == 18, game.log


@pytest.mark.parametrize("skips,drawn", PATTERNS)
def test_truce_pays_for_the_cards_an_interactive_familiar_skipped(skips, drawn):
    game = _game(hands=(("Truce",), ()), boards=(("Obstinate Familiar",), ()))
    caster, other = game.players
    game.cast_from_hand(0, "Truce")
    assert game.confirm_draw_up_to(0, 2)
    assert game.confirm_draw_up_to(1, 1)
    assert _answer(game, skips) == ["skip_draw", "skip_draw"]
    game._settle()
    assert len(caster.cards_drawn_this_turn) == drawn
    # "For each card less than two a player draws this way, that player
    # gains 2 life."
    assert caster.life == 20 + 2 * (2 - drawn), game.log
    assert other.life == 22, game.log
    assert f"P0 drew {drawn} card(s)" in game.log


def test_truce_under_a_familiar_nobody_is_asked_about():
    game = _game(hands=(("Truce",), ()), boards=(("Obstinate Familiar",), ()),
                 interactive=())
    caster, other = game.players
    game.cast_from_hand(0, "Truce")
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert len(caster.cards_drawn_this_turn) == 2
    assert (caster.life, other.life) == (20, 20), game.log


def test_each_player_draws_reports_what_arrived_and_in_turn_order():
    """"Each player draws a card" (Winter Sky's shape): the report per seat
    is what that seat's draw delivered, and the next seat's draw waits for an
    interactive offer about the one before it (CR 121.2 — a draw is finished
    before the next begins)."""
    from engine.oracle_types import OracleInstruction
    from engine.game_types import OracleExecutionContext

    game = _game(boards=(("Obstinate Familiar",), ("Obstinate Familiar",)))
    p0, p1 = game.players
    game._execute_oracle_instruction(
        OracleInstruction("draw_target_cards", None, {"recipient": "each_player", "amount": 1}),
        OracleExecutionContext(caster=p0, target=p0, card=_CARDS["Winter Sky"]),
    )
    # Seat 0's offer is owed, and seat 1 has not been asked yet.
    assert [(c.kind, c.player_index) for c in game.pending_replacement_choices] == [
        ("skip_draw", 0),
    ]
    assert game.resolve_replacement_choice(0, 0, kind="skip_draw")
    assert [(c.kind, c.player_index) for c in game.pending_replacement_choices] == [
        ("skip_draw", 1),
    ]
    assert game.resolve_replacement_choice(1, 1, kind="skip_draw")
    assert (len(p0.cards_drawn_this_turn), len(p1.cards_drawn_this_turn)) == (1, 0)
    reports = [line for line in game.log if line.endswith(" cards") and " drew " in line]
    assert reports == ["P0 drew 1 cards", "P1 drew 0 cards"], game.log
