"""Census: the by-position defaults with a population, driven over every card
that arms them.

``test_kg4_defaults_unasked_picks.py`` drives one board per prompt kind. Three
of the kinds are armed by more than a handful of cards in the pool, and the
instruction that arms each one carries the card's own narrowing (a creature
card, a green creature card, an artifact card; two cards, three, one; "lands",
"creatures") — so each census here walks every compilation unit
(``faces.compilation_units``), executes the arming instruction itself for a
seat nobody asks on a table where the first thing offered is the worse one,
and asserts the pick was the better one:

* ``put_chosen_card_from_hand_onto_battlefield`` (``put_from_hand_choice``):
  the cheaper of two eligible cards first in hand, the dearer put;
* ``put_hand_cards_on_library`` / ``shuffle_hand_cards_into_library``
  (``hand_to_library``): a dear spell first in hand behind three lands with
  three lands on the battlefield, the lands put back;
* ``untap_up_to_matching`` (``untap_up_to``): eight tapped basic lands ahead of
  a tapped dual land, the dual untapped.

Each asserts a floor on how many instructions it examined, so a census that
stopped finding its population reads red rather than empty. Validated
backwards: every examined instruction fails on ``313bd09d``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers.hand import put_from_hand_candidates
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _steps(instruction):
    yield instruction
    payload = instruction.payload or {}
    for key in ("steps", "then", "else", "action", "otherwise", "effect", "reflexive"):
        nested = payload.get(key)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                if hasattr(child, "kind"):
                    yield from _steps(child)


def _arming(kinds):
    """``(unit, instruction)`` for every supported unit's step of *kinds*."""
    found = []
    seen = set()
    for unit in compilation_units(load_catalog()):
        if unit.name in seen:
            continue
        seen.add(unit.name)
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [a.instruction for a in program.activated_abilities if a.instruction is not None]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction is not None]
        for root in roots:
            for step in _steps(root):
                if step.kind in kinds:
                    found.append((unit, step))
    return found


def _table(catalog_by_name, unit, *, hand=(), lands=()) -> tuple[Game, OracleExecutionContext]:
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand), library=[catalog_by_name["Island"]] * 8),
        PlayerState(name="P1", library=[catalog_by_name["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for land in lands:
        permanent = Permanent(card=catalog_by_name[land])
        game._put_permanent_onto_battlefield(0, permanent, None)
    source = None
    if unit.primary_type not in ("instant", "sorcery"):
        source = Permanent(card=unit)
        game._put_permanent_onto_battlefield(0, source, None)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[0], card=unit, source_permanent=source,
    )
    return game, context


#: Two eligible cards, the cheaper first: whichever pair a printed narrowing
#: admits both of.
_PAIRS = (
    ("Llanowar Elves", "Craw Wurm"),
    ("Ornithopter", "Juggernaut"),
    ("Goblin Balloon Brigade", "Goblin King"),
)


def test_every_put_from_hand_offer_puts_the_dearer_card(catalog_by_name):
    examined, wrong = [], []
    for unit, step in _arming({"put_chosen_card_from_hand_onto_battlefield"}):
        for cheap, dear in _PAIRS:
            game, context = _table(
                catalog_by_name, unit, hand=[catalog_by_name[cheap], catalog_by_name[dear]],
            )
            try:
                offered = put_from_hand_candidates(game, step.payload, game.players[0])
            except ValueError:
                # A narrowing with an amount only the resolution knows
                # ("mana value X or less"): not examinable from here.
                break
            if offered != [0, 1]:
                continue
            game._execute_oracle_instruction(step, context)
            if not game.pending_choices_of("put_from_hand_choice", 0) and len(game.players[0].hand) == 2:
                continue
            game.auto_resolve_pending_choices()
            examined.append(unit.name)
            if [c.name for c in game.players[0].hand] != [cheap]:
                wrong.append((unit.name, [c.name for c in game.players[0].hand]))
            break
    assert len(examined) >= 10, examined
    assert wrong == [], wrong


def test_every_hand_to_library_offer_puts_back_what_it_least_wants(catalog_by_name):
    examined, wrong = [], []
    for unit, step in _arming({"put_hand_cards_on_library", "shuffle_hand_cards_into_library"}):
        payload = step.payload or {}
        if payload.get("whole_hand") or payload.get("any_number"):
            continue
        hand = [catalog_by_name[name] for name in ("Shivan Dragon", "Forest", "Forest", "Forest")]
        game, context = _table(
            catalog_by_name, unit, hand=hand, lands=("Mountain", "Mountain", "Mountain"),
        )
        game._execute_oracle_instruction(step, context)
        owed = game.pending_choices_of("hand_to_library", 0)
        if not owed or int(owed[0].data["count"]) >= len(hand):
            continue
        game.auto_resolve_pending_choices()
        examined.append(unit.name)
        if "Shivan Dragon" not in [c.name for c in game.players[0].hand]:
            wrong.append(unit.name)
    assert len(examined) >= 5, examined
    assert wrong == [], wrong


def test_every_untap_up_to_offer_untaps_the_dual_land_first(catalog_by_name):
    examined, wrong = [], []
    for unit, step in _arming({"untap_up_to_matching"}):
        payload = step.payload or {}
        if payload.get("who") == "event_subject_player" or payload.get("cost_each"):
            continue
        game, context = _table(catalog_by_name, unit)
        lands = []
        for name in ("Plains",) * 8 + ("Tundra",):
            permanent = Permanent(card=catalog_by_name[name], tapped=True)
            game._put_permanent_onto_battlefield(0, permanent, None)
            lands.append(permanent)
        game._execute_oracle_instruction(step, context)
        owed = game.pending_choices_of("untap_up_to", 0)
        if not owed or int(owed[0].data.get("amount", 0)) >= len(lands):
            continue
        game.auto_resolve_pending_choices()
        if not any(not land.tapped for land in lands) or unit.name in examined:
            continue
        examined.append(unit.name)
        if lands[-1].tapped:
            wrong.append(unit.name)
    assert len(examined) >= 6, examined
    assert wrong == [], wrong
