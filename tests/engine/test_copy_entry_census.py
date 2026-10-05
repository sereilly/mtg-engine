"""Census: a copy fires the copied permanent's own enters-the-battlefield trigger.

CR 707.5: an object that enters as a copy "becomes a copy as it enters the
battlefield", and "any enters-the-battlefield triggered abilities of the copy
will have a chance to trigger". CR 603.6d checks an entering permanent as it
exists *after* the event, so what triggers is what the copy has — the copied
object's text.

``_apply_self_enters_battlefield_triggers`` compiled ``permanent.card``, the card
as printed. For a Clone that is Clone, which prints no entry trigger; for a
token copy (``create_token_copy``) it is a card that carries nothing but a name.
So every copy in the pool — Clone, Vesuvan Doppelganger, Copy Artifact, and the
token copies of Dance of Many, Dual Nature, Echo Chamber and Sublime Epiphany —
arrived and fired nothing. Nothing crashed and nothing reported unsupported: the
abilities compile perfectly and the dispatcher simply never read them.

The sweep asks the question of **every supported permanent in both manifest
roles** that prints an inline entry trigger, rather than of the one invented
"Healer" the defect was measured on, and it asks three things of each:

* the original, entering un-copied, fires each of its entry triggers **once** —
  reading ``effective_card`` must not double anything;
* a token copy fires exactly what the original fired;
* a Clone cast to copy a creature fires exactly what that creature fired.

A trigger counts as fired when it is executed inline or put on the stack —
CR 603.3c may then take a stacked one straight back off for want of a legal
target, which is still a trigger that triggered. Validated backwards: on the
tree before the fix both copy halves read zero for every card, and the floors
below are what stop a later filter from making the sweep pass by looking at
nothing.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.modal_triggers import INLINE_TRIGGER_CONDITIONS
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_PERMANENT_TYPES = frozenset({"creature", "artifact", "enchantment", "land"})

# 194 non-Aura permanents across both roles print a supported inline entry
# trigger (October 2026). Floors, not equalities: the pool grows.
_MIN_PERMANENTS = 185
_MIN_CREATURES = 130
# ...and of those, the comparisons that could fail: an original that fired at
# least once and was still on the battlefield to be copied.
_MIN_TOKEN_COMPARISONS = 150
_MIN_CLONE_COMPARISONS = 115


@lru_cache(maxsize=1)
def _entry_trigger_cards() -> tuple:
    """``(card, entry trigger instructions)`` for every supported permanent
    that prints an inline entry trigger, deduped by name over both roles."""
    seen: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in compilation_units(load_cards(path)):
            seen.setdefault(card.name, card)
    rows = []
    for card in seen.values():
        if card.primary_type not in _PERMANENT_TYPES or "Aura" in card.type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        instructions = tuple(
            trig.instruction
            for trig in program.triggered_abilities
            if trig.condition.kind in INLINE_TRIGGER_CONDITIONS
            and trig.supported
            and trig.instruction is not None
        )
        if instructions:
            rows.append((card, instructions))
    return tuple(sorted(rows, key=lambda row: row[0].name))


def _recording_game(hand=()) -> tuple[Game, list]:
    """A two-seat game whose entry-trigger dispatch is recorded.

    Both ways an entry trigger leaves ``_apply_self_enters_battlefield_triggers``
    are wrapped — the inline execution and the push — and each is recorded
    against the permanent whose entry is being processed, so the copy and its
    original are told apart on one board.

    Only the calls the function makes *itself* count: a stacked trigger is
    executed again when it resolves, and an inline one that stops to ask is
    executed again when it resumes, and neither is a second triggering. Each
    call opens a window whose depth tracks nesting, so a trigger that puts a
    permanent onto the battlefield (Dance of Many) records that permanent's
    triggers under its own window.
    """
    game = Game(players=[PlayerState(name="P0", hand=list(hand)), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    fired: list = []
    windows: list = []
    entry = game._apply_self_enters_battlefield_triggers
    execute = game._execute_oracle_instruction
    enqueue = game._enqueue_triggered_ability

    def recording_entry(controller_index, permanent, *args, **kwargs):
        windows.append([permanent, 0])
        try:
            return entry(controller_index, permanent, *args, **kwargs)
        finally:
            windows.pop()

    def recording_execute(instruction, context, *args, **kwargs):
        if windows and windows[-1][1] == 0:
            fired.append((windows[-1][0], instruction))
        if windows:
            windows[-1][1] += 1
        try:
            return execute(instruction, context, *args, **kwargs)
        finally:
            if windows:
                windows[-1][1] -= 1

    def recording_enqueue(**kwargs):
        if windows and windows[-1][1] == 0:
            fired.append((windows[-1][0], kwargs.get("instruction")))
        return enqueue(**kwargs)

    game._apply_self_enters_battlefield_triggers = recording_entry
    game._execute_oracle_instruction = recording_execute
    game._enqueue_triggered_ability = recording_enqueue
    return game, fired


def _fired_from(fired: list, permanent: Permanent, instructions: tuple) -> int:
    """How many of *instructions* fired from *permanent*'s entry.

    Compared by value, not identity: a copy's text may carry a line granted on
    top of the copied one (Pursued Whale's own Pirate makes "creatures you
    control attack each combat if able"), which is a different card to the
    compiler and so a different — equal — instruction object."""
    return sum(
        1 for source, instruction in fired
        if source is permanent and instruction in instructions
    )


def _settled(game: Game, permanent: Permanent) -> bool:
    """Drain the stack and the state-based actions, then ask whether
    *permanent* is still there to be copied. A 2/0 Zombie Mob entering with no
    creature card to count survives only until somebody checks."""
    resolve_stack(game)
    game.check_state_based_actions()
    resolve_stack(game)
    return game.is_on_battlefield(permanent)


def _sweep_token_copies() -> tuple[int, int, list[str]]:
    """``(examined, compared, wrong)``: *compared* counts the cards whose
    original fired something and was still there to copy — the comparisons
    that could have failed."""
    examined = compared = 0
    wrong: list[str] = []
    for card, instructions in _entry_trigger_cards():
        examined += 1
        game, fired = _recording_game()
        original = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, original, None)
        present = _settled(game, original)
        own = _fired_from(fired, original, instructions)
        # Never more than once per printed ability: the original has the one
        # card either way, so reading ``effective_card`` cannot double it.
        if own > len(instructions):
            wrong.append(f"{card.name}: the original fired {own} times for {len(instructions)} abilities")
            continue
        if not present:
            # Its own entry trigger or the state-based check took it away, so
            # there is nothing left on the battlefield to copy.
            continue
        token = game.create_token_copy(0, original)
        resolve_stack(game)
        copied = _fired_from(fired, token, instructions)
        compared += own > 0
        if copied != own:
            wrong.append(f"{card.name}: original fired {own}, token copy fired {copied}")
    return examined, compared, wrong


def _sweep_clones() -> tuple[int, int, list[str]]:
    """``(examined, compared, wrong)``, as :func:`_sweep_token_copies`."""
    clone_card = next(
        card
        for path in manifest_set_paths()
        for card in load_cards(path)
        if card.name == "Clone"
    )
    examined = compared = 0
    wrong: list[str] = []
    for card, instructions in _entry_trigger_cards():
        if card.primary_type != "creature":
            continue
        examined += 1
        game, fired = _recording_game(hand=[clone_card])
        original = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, original, None)
        present = _settled(game, original)
        own = _fired_from(fired, original, instructions)
        if not present:
            continue
        slot = game.battlefield_index_of(original)
        seat = game.controller_index_of(original)
        game.cast_from_hand(0, "Clone", target_player_index=seat, target_permanent_index=slot)
        resolve_stack(game)
        clone = next(
            (perm for perm in game.all_permanents() if perm.card is clone_card),
            None,
        )
        if clone is None:
            # The copied trigger may have removed the Clone itself (a bounce
            # whose default target is the first creature offered), so the
            # record is read by identity over every firing instead.
            clone = next(
                (source for source, _ in fired
                 if source is not None and source.card is clone_card),
                None,
            )
        copied = 0 if clone is None else _fired_from(fired, clone, instructions)
        compared += own > 0
        if copied != own:
            wrong.append(f"{card.name}: original fired {own}, Clone copying it fired {copied}")
    return examined, compared, wrong


def test_a_token_copy_fires_what_its_original_fires():
    examined, compared, wrong = _sweep_token_copies()
    assert examined >= _MIN_PERMANENTS, (
        f"the sweep examined {examined} permanents with an entry trigger; the "
        f"floor is {_MIN_PERMANENTS} — a filter has started hiding the pool"
    )
    assert compared >= _MIN_TOKEN_COMPARISONS, (
        f"only {compared} originals fired something to compare against; the "
        f"floor is {_MIN_TOKEN_COMPARISONS} — a sweep where nothing fires "
        "agrees with every copy"
    )
    assert not wrong, (
        f"{len(wrong)} of {examined} token copies did not fire the copied entry "
        "trigger (CR 707.5, CR 603.6d):\n  " + "\n  ".join(wrong)
    )


def test_a_clone_fires_what_the_creature_it_copies_fires():
    examined, compared, wrong = _sweep_clones()
    assert examined >= _MIN_CREATURES, (
        f"the sweep examined {examined} creatures with an entry trigger; the "
        f"floor is {_MIN_CREATURES} — a filter has started hiding the pool"
    )
    assert compared >= _MIN_CLONE_COMPARISONS, (
        f"only {compared} originals fired something to compare against; the "
        f"floor is {_MIN_CLONE_COMPARISONS} — a sweep where nothing fires "
        "agrees with every copy"
    )
    assert not wrong, (
        f"{len(wrong)} of {examined} Clones did not fire the copied entry "
        "trigger (CR 707.5, CR 603.6d):\n  " + "\n  ".join(wrong)
    )


@pytest.mark.parametrize("vanilla", ["Grizzly Bears", "Craw Wurm"])
def test_a_clone_of_a_creature_with_no_entry_trigger_fires_nothing(vanilla):
    """Clone's **own** printed line is a CR 614.1c replacement, not a trigger:
    copying a creature with no entry trigger, nothing is announced at all."""
    cards = {
        card.name: card
        for path in manifest_set_paths()
        for card in load_cards(path)
        if card.name in {"Clone", vanilla}
    }
    game, fired = _recording_game(hand=[cards["Clone"]])
    original = Permanent(card=cards[vanilla])
    game._put_permanent_onto_battlefield(1, original, None)
    game.cast_from_hand(0, "Clone", target_player_index=1, target_permanent_index=0)
    resolve_stack(game)
    clone = next(perm for perm in game.all_permanents() if perm.card.name == "Clone")
    assert clone.effective_card.name == vanilla
    assert not [entry for entry in fired if entry[0] is clone]
