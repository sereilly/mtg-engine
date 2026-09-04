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
from web.action_registry import ACTION_HANDLERS
from web.prompts import PROMPT_RENDERERS, blocking_prompt
from web.schemas import ActionKind
from tests.source_index import source_text

# The handlers under test register when web/actions.py's decorators run, so
# the registry is only populated once that module is imported. The full suite
# always imports it somewhere earlier; this file run alone found the registry
# empty and reported every handler missing. The import is the fixture.
import web.actions  # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
ACTION_KINDS = set(get_args(ActionKind))


def _engine_sources() -> list[str]:
    return [source_text(path) for path in ENGINE.rglob("*.py")]


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
    elif spec.action not in ACTION_HANDLERS:
        # The registry IS the dispatch (web/action_registry.py), so "reachable"
        # is a key lookup rather than a grep of the old if/elif chain.
        problems.append(f"action {spec.action!r} has no registered handler")
    for extra in spec.also_answers:
        if extra not in ACTION_KINDS:
            problems.append(f"also_answers {extra!r} is not an ActionKind")
        elif extra not in ACTION_HANDLERS:
            problems.append(f"also_answers {extra!r} has no registered handler")
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
    actions = [
        action
        for spec in CHOICE_SPECS.values()
        for action in (spec.action, *spec.also_answers)
    ]
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

    # A second answer (a search's "fail to find") must pass the same gate —
    # search_library_decline shipped registered but unreachable, every attempt
    # refused with the prompt's own blocked_detail.
    for extra in spec.also_answers:
        assert blocking_prompt(game, 0, extra, frozenset()) is None, (
            f"{kind} refuses {extra!r}, which is declared to answer it"
        )

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
    written around finishing immediately, and flipping them is its own job.

    ``discard`` used to be the example here and now suspends (Recall's "then
    return a card ... for each card discarded this way" is a later step of the
    same resolution). ``mana_payment`` is the remaining shape: Power Sink's
    payment decides nothing a later step of its own resolution reads."""
    game = _game_with_library()
    game.arm_pending_choice("mana_payment", 0, amount=2)
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
        # "Discard X cards, **then** return a card from your graveyard to your
        # hand for each card discarded this way" (Recall): the answer is the
        # count and the identity the next step of the same sentence works from.
        "discard",
        # "Each player may draw up to two cards. **For each card less than two
        # a player draws this way**, that player gains 2 life." (Truce.) The
        # discard's twin one zone over and for its reason: the sentence behind
        # it is sized from every seat's answer, so nothing may run until the
        # last of them is given.
        "draw_up_to",
        "scry",             # arranges the library a later draw reads
        "search_library",   # removes a card from it and shuffles the rest
        "reorder_library",  # same, by permutation
        # The picks are the cards the same resolution's next step ("You may
        # cast them this turn.") grants permission over.
        "search_exile_cards",
        # The found cards land only when the finder says where (Cultivate);
        # a later step of the same resolution must not read a board they have
        # not reached yet.
        "search_destination",
        # Reshapes the library; the spell's own CR 608.2n move waits behind it.
        "look_top_pick",
        # Phyrexian Portal's three decisions, each of which arms the next.
        # The division decides what the controller is choosing between, the
        # choice decides which pile is searched, and the search decides what
        # goes back into the library - three steps of one resolution.
        "library_pile_split",
        "pile_exile_choice",
        "pile_search",
        # "As many times as you choose, you may pay 1 life…" (Lim-Dul's Vault).
        # The answer decides whether the *next* step is another round of the
        # same offer or the shuffle that ends the card, and both are steps of
        # this resolution.
        "library_cycle_offer",
        # "Sacrifice an artifact. **If you do**, search your library…"
        # (Transmute Artifact): what the player gives up decides what the rest
        # of the resolution may find. Only an interactive seat queues it —
        # `default_at_arm` answers for everyone else before the flag is set.
        "sacrifice",
        # "Remove any number of +1/+1 counters … create **that many** … tokens"
        # (Tetravus): the answer is the count the next step of the same
        # sentence uses. Shapeshifter arms the same kind at the end of what it
        # is part of, where suspending costs nothing.
        "number_choice",
        # "In turn order, each player may top the high bid. ... The high bidder
        # loses life equal to the high bid and gains control of the creature."
        # (Illicit Auction): the answer decides who is asked next and, when the
        # round runs out, which seat pays and takes the creature -- both steps
        # of the same resolution, armed by the answer to the one before them.
        "bid_life",
        # "Attach target Aura … to **another permanent of that type**"
        # (Enchantment Alteration): the attach behind the choice is a later step
        # of the same sentence and reads the answer out of `results`. Only an
        # interactive seat ever queues it — `default_at_arm` answers for
        # everyone else before the flag is set.
        "permanent_choice",
        # "…chooses up to two Plains. **Then destroy all Plains that weren't
        # chosen this way by any player.**" (Raiding Party): the sweep behind
        # the pick is a later step of the same resolution and subtracts exactly
        # what this records — and the iteration behind *it* arms the next one,
        # which is how a chain of decisions stays one resolution.
        "permanent_set_choice",
        # "Each player may tap any number of untapped white creatures they
        # control. **For each creature tapped this way**, …" (Raiding Party):
        # the loop behind it walks what this prompt tapped. Siege Striker arms
        # the same kind with nothing behind it, where suspending costs nothing —
        # the same note `number_choice` above carries about Shapeshifter.
        "tap_any_number",
        # "Target opponent chooses a card in your graveyard. You may pay {G}.
        # If you do, **repeat this process** …" (Forgotten Lore): the pick is
        # what the payment offer behind it is about, and the set of picks is
        # what the round after that may not choose again.
        "graveyard_pick_for_price",
        # "Starting with you, each player may put a permanent card from their
        # hand onto the battlefield. **Repeat this process until no one puts a
        # card onto the battlefield.**" (Eureka): the answers are what decides
        # whether the round happens again, so the round has to still be there
        # to decide it.
        "put_from_hand_choice",
        # "choose two cards in your hand drawn this turn. **For each of those
        # cards**, …" (Sylvan Library): the pick is the set the next step of
        # the same resolution repeats over.
        "choose_cards_in_hand",
        # "**For each of those cards**, pay 4 life or put the card on top of
        # your library" (Sylvan Library): a mode picked inside a repetition
        # acts on the object the repetition is currently on, so the next
        # iteration is a later step that must wait for this answer.
        "mode_choice",
        # "Choose a player who cast one or more sorcery spells this turn.
        # Backdraft deals damage to **that player** equal to half the damage
        # dealt by **one of those** sorcery spells this turn." The first answer
        # narrows the second prompt and the second answer sizes the damage, so
        # both are steps a later step of the same resolution reads.
        "player_choice",
        "cast_choice",
        # "Change the target of target spell with a single target."
        # (Deflection.) The answer *is* the new target, and the step behind it
        # in the same sentence is what writes it onto the stack item.
        "retarget_choice",
        # "For each land, destroy that land unless any player pays 1 life."
        # (Cleansing.) The answer decides whether the next step of the same
        # resolution destroys that land — and, one step earlier than that,
        # whether the seat behind this one is offered it at all.
        "pay_life_to_save",
        # "Draw three cards, **then** put two cards from your hand on top of
        # your library in any order." (Brainstorm.) The two halves are one
        # resolution, and the second reshapes the hand and the library the
        # first filled, so nothing after it may read either.
        "hand_to_library",
        # "You may exile a nonland card from your hand. **You may cast that
        # card** for as long as it remains exiled." (Ice Cauldron.) The second
        # sentence grants permission over exactly what the first exiled, so a
        # step that ran before the answer would grant it over nothing.
        "exile_from_hand_choice",
        # "…and you decide whether to flip again." (Game of Chaos.) The answer
        # is whether the rest of the resolution happens at all, and the round it
        # starts arms the next offer.
        "flip_again",
        # "Then any other player may pay 2 life. If a player does, put that card
        # into its owner's graveyard. Otherwise, that player draws a card."
        # (Zur's Weirding.) The answer decides what happens to the card on top
        # of the library — and, one step earlier, whether the seat behind this
        # one is offered it at all.
        "revealed_draw_buyout",
        # "You may exile up to two target creature cards from defending
        # player's graveyard. **If you do, you gain 1 life for each card exiled
        # this way** …" (Rysorian Badger.) The answer is the count the step
        # behind it reads, which is Recall's shape one zone over.
        "graveyard_exile_pick",
        # "Exile up to three target cards from **a single graveyard**." (Ebony
        # Charm.) The answer is *which pile*, and the step behind it is the pick
        # out of that pile — armed by this answer, which is how a chain of
        # decisions stays one resolution (CR 608.2).
        "graveyard_pile_choice",
    }, suspending


def test_the_only_prompt_that_holds_nothing_is_hand_reveal():
    """``holds_priority`` is what makes "the game waits" a property of the queue
    rather than a hand-kept list, so the set of kinds that *don't* wait is the
    ratchet. Everything else is armed part-way through a resolution and the
    game must stop for it (CR 117.3b); ``hand_reveal`` is the one notification —
    the viewer has already seen the hand, and nothing waits on dismissing it.

    Three kinds (land_type_choice, kudzu_reattach, face_down_cast) were on this
    list by omission: each is armed from an effect handler mid-resolution and so
    should have held priority, but carried no ``blocked_detail`` and so did not.
    A new prompt that lands here needs to prove it decides nothing the rest of
    the resolution reads."""
    non_holding = {kind for kind, spec in CHOICE_SPECS.items() if not spec.holds_priority}
    assert non_holding == {"hand_reveal"}, non_holding


def test_game_carries_no_per_card_pending_field():
    """The queue replaced sixteen one-card ``Game`` fields. A new one would be
    a prompt outside the registry again, with none of the five parts enforced."""
    from engine.game import Game

    fields = {
        name for name in Game.__dataclass_fields__
        if name.startswith("pending_")
    }
    # ``pending_choices`` is the queue; the other two are delayed *effects*
    # with no decision in them.
    #
    # ``pending_end_step_tokens`` used to be a third: Rukh Egg's "create a
    # token at the beginning of the next end step", queued at the Game level
    # and drained by the end step. The grammar reads that delay now, so the
    # trigger goes on the stack (CR 603.3) and arms an ordinary delayed
    # ability — one fewer per-card field, and the field is gone with it.
    assert fields == {
        "pending_choices",
        "pending_replacement_choices",
        "pending_draw_step_life_loss",
    }, fields
