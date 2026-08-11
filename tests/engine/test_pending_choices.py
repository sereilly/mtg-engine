"""The pending-choice registry has to be complete, in both directions.

An interactive decision needs five parts: something arms it, a resolver, a
default for non-interactive seats, a renderer, and an action that answers it.
They used to be five unrelated edits in five files, and the failure modes are
silent and asymmetric — a missing default hangs an AI seat forever, a missing
gate lets a player act around their own prompt, a missing renderer and action
mean the prompt is armed and never shown. Primal Clay shipped with the last
three missing and nothing noticed.

These tests read the registry rather than a list of kinds, so a new prompt is
covered the moment it is registered, and fail if a kind is armed with no spec.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from engine.pending_choices import CHOICE_SPECS, ChoiceSpec, PendingChoice, register_choice
from web.prompts import PROMPT_RENDERERS, blocking_prompt
from web.schemas import ActionKind

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
# The one dispatch over ActionKind, split out of web/app.py into its own module.
DISPATCH_SOURCE = (REPO / "web" / "actions.py").read_text(encoding="utf-8")
ACTION_KINDS = set(get_args(ActionKind))


def _engine_sources() -> list[str]:
    return [path.read_text(encoding="utf-8") for path in ENGINE.rglob("*.py")]


def _incomplete(kind: str, spec: ChoiceSpec) -> list[str]:
    """Every part *kind* is missing. One function so the tests below and the
    fault-injection test that proves they fire share it."""
    problems: list[str] = []
    if spec.resolve is None:
        problems.append("no resolver")
    if spec.default is None:
        problems.append("no default for non-interactive seats")
    if kind not in PROMPT_RENDERERS:
        problems.append("no renderer in web/prompts.py")
    if spec.action not in ACTION_KINDS:
        problems.append(f"action {spec.action!r} is not an ActionKind")
    elif f'req.action == "{spec.action}"' not in DISPATCH_SOURCE:
        problems.append(f"action {spec.action!r} is never dispatched in web/actions.py")
    if not spec.prompt_key:
        problems.append("no prompt_key")
    return problems


def test_every_registered_choice_is_complete():
    """A prompt with a part missing is armed and then unreachable."""
    missing = {
        kind: problems
        for kind, spec in CHOICE_SPECS.items()
        if (problems := _incomplete(kind, spec))
    }
    assert not missing, f"incomplete pending choices: {missing}"


def test_the_completeness_check_fires():
    """Verified by injection: a kind registered with no renderer and no action
    is reported. A guard nobody has watched fail is a guard nobody has tested."""
    spec = ChoiceSpec(
        kind="_probe",
        resolve=lambda game, choice, response: True,
        default=lambda game, choice: None,
        action="never_dispatched",
        prompt_key="_probe",
    )
    problems = _incomplete("_probe", spec)
    assert "no renderer in web/prompts.py" in problems
    assert any("is not an ActionKind" in p for p in problems)


def test_kinds_and_keys_are_unique():
    actions = [spec.action for spec in CHOICE_SPECS.values()]
    keys = [spec.prompt_key for spec in CHOICE_SPECS.values()]
    assert len(set(actions)) == len(actions), "two prompts answered by one action"
    assert len(set(keys)) == len(keys), "two prompts sharing a state key"


def test_duplicate_registration_raises():
    """Which resolver ran would otherwise depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register_choice(
            "discard",
            resolve=lambda game, choice, response: True,
            default=lambda game, choice: None,
            action="discard_confirm",
            prompt_key="discard_select",
        )


def _armed_kinds() -> set[str]:
    """Kinds the engine actually arms. A replacement effect suspended on a
    decision is armed as ``ReplacementChoice(kind=…)`` rather than through
    ``arm_pending_choice``, so both spellings count."""
    kinds: set[str] = set()
    for source in _engine_sources():
        kinds.update(re.findall(r'arm_pending_choice\(\s*"([a-z_]+)"', source))
        kinds.update(
            re.findall(r'ReplacementChoice\((?:[^()]|\([^()]*\))*?kind="([a-z_]+)"', source, re.S)
        )
    return kinds


def test_every_armed_kind_is_registered():
    """``arm_pending_choice("x", …)`` with no spec for ``x`` would raise only
    when that card is played."""
    armed = _armed_kinds()
    assert armed, "found no arm sites — the scan pattern has gone stale"
    assert armed <= set(CHOICE_SPECS), f"armed with no spec: {armed - set(CHOICE_SPECS)}"


def test_every_registered_kind_is_armed():
    """A spec nothing arms is dead code that reads like coverage."""
    unreachable = set(CHOICE_SPECS) - _armed_kinds()
    assert not unreachable, f"registered but never armed: {unreachable}"


class _StubGame:
    """Just enough game for ``blocking_prompt``: it only walks the prompts."""

    def __init__(self, pairs):
        self._pairs = pairs

    def iter_pending_prompts(self):
        return iter(self._pairs)


@pytest.mark.parametrize("kind", sorted(CHOICE_SPECS))
def test_a_gating_prompt_refuses_everything_but_its_own_action(kind):
    """Whatever a kind's gate says, it must apply to the action that answers it
    and to the seat that owes it — a prompt that blocks its own answer is a
    deadlock, and one that blocks nothing is a prompt players act around."""
    spec = CHOICE_SPECS[kind]
    choice = PendingChoice(kind=kind, player_index=0, data={})
    game = _StubGame([(spec, choice)])

    answering = blocking_prompt(game, 0, spec.action, frozenset())
    assert answering is None, f"{kind} refuses the action that answers it"

    other = blocking_prompt(game, 0, "pass_priority", frozenset())
    if spec.blocked_detail is None:
        assert other is None
    else:
        assert other is not None and other[0] is spec
        assert blocking_prompt(game, 0, "pass_priority", frozenset({"pass_priority"})) is None

    # A seat that owes nothing is only held up by the kinds that stop the whole
    # game (a library search everyone is waiting on).
    bystander = blocking_prompt(game, 1, "pass_priority", frozenset())
    if spec.blocked_detail is not None and spec.blocks_every_seat:
        assert bystander is not None
    else:
        assert bystander is None


# ---------------------------------------------------------------------------
# ``suspends`` — the flag that stops the steps queued behind a prompt
# ---------------------------------------------------------------------------
#
# The rules half is tests/rules/test_resumption.py. These are about the field's
# own bookkeeping: set at arm, cleared once (and only once) at the answer, and
# never left set for a later loop to trip over.


def _game_with_library(size: int = 5):
    from engine import Game, PlayerState
    from tests.helpers import CARDS_BY_NAME

    player = PlayerState(name="P1", library=[CARDS_BY_NAME["Mountain"]] * size)
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game


def test_arming_a_suspending_kind_stops_the_resolution_it_is_part_of():
    game = _game_with_library()
    game.arm_pending_choice("scry", 0, top_count=2, amount=2)
    assert game.effect_suspended is True


def test_arming_a_non_suspending_kind_leaves_the_resolution_running():
    """Opt-in, not universal: the kinds that complete inline have callers
    written around finishing immediately, and flipping them is its own job."""
    game = _game_with_library()
    game.arm_pending_choice("discard", 0, count=1)
    assert game.effect_suspended is False


def test_answering_lifts_the_suspension():
    game = _game_with_library()
    game.arm_pending_choice("scry", 0, top_count=2, amount=2)
    assert game.confirm_scry(0, card_order=[0, 1], bottom_count=0) is True
    assert game.effect_suspended is False
    assert game.resume_stack == []


def test_a_rejected_answer_leaves_the_prompt_owed_and_the_work_waiting():
    """Clearing on a rejected answer would resume the steps behind the prompt
    against a decision nobody made — the exact bug, one layer along."""
    game = _game_with_library()
    game.arm_pending_choice("scry", 0, top_count=2, amount=2)
    assert game.confirm_scry(0, card_order=[0, 0], bottom_count=0) is False
    assert game.effect_suspended is True
    assert game.pending_choice_of("scry") is not None


def test_a_non_interactive_seat_never_leaves_the_flag_set():
    """An AI seat queues these kinds and the auto-resolver drains them. A flag
    left standing would stop the *next* resumable loop after one step, anywhere
    in the game, with nothing pointing back at what set it."""
    game = _game_with_library()
    game.interactive_seats = set()
    game.arm_pending_choice("scry", 0, top_count=2, amount=2)
    game.auto_resolve_pending_choices()
    assert game.effect_suspended is False
    assert game.pending_choices == []


def test_the_kinds_that_suspend_are_the_ones_that_shape_a_later_step():
    """A ratchet on the opt-in list. Adding a kind here is a claim that its
    answer decides what a later step of the same resolution sees; removing one
    reintroduces the bug this field exists for."""
    suspending = {kind for kind, spec in CHOICE_SPECS.items() if spec.suspends}
    assert suspending == {
        "effect_order",     # CR 616.1e — the event itself has not happened yet
        "scry",             # arranges the library a later draw reads
        "search_library",   # removes a card from it and shuffles the rest
        "reorder_library",  # same, by permutation
        # The picks are the cards the same resolution's next step ("You may
        # cast them this turn.") grants permission over.
        "search_exile_cards",
    }, suspending


def test_game_carries_no_per_card_pending_field():
    """The queue replaced sixteen one-card ``Game`` fields. A new one would be
    a prompt outside the registry again, with none of the five parts enforced."""
    from engine.game import Game

    fields = {
        name for name in Game.__dataclass_fields__
        if name.startswith("pending_")
    }
    # ``pending_choices`` is the queue; the other two are delayed *effects* with
    # no decision in them — a token that appears at the next end step, and a
    # life loss that happens unless paid for before a draw step.
    assert fields == {
        "pending_choices",
        "pending_replacement_choices",
        "pending_end_step_tokens",
        "pending_draw_step_life_loss",
    }, fields
