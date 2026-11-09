from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
import random

from . import ai_rehearsal
from .ai_combat import run_ai_combat_phase
from .ai_mulligan import take_opening_mulligans
from .ai_policy import (
    choose_cast_action,
    choose_land_drop,
)
from .ai_actions import (activation_announcement, cast_announcement, spell_being_cast,
                         zone_being_cast_from)
from .ai_abilities import choose_activation_action
from .ai_foreign_activations import choose_foreign_activation_action
from .ai_hand_activations import choose_hand_activation_action
from .ai_graveyard_activations import (
    activate_chosen_graveyard_ability,
    choose_graveyard_activation_action,
)
from .ai_payment import tap_planned_lands
from .ai_priority import PriorityAct, PriorityAsk, act_at_priority
from .ai_rehearsal import rehearsing
from .ai_special_actions import special_action_before_combat
from .ai_weighed_cast import permitted_casts
from .card_loader import load_cards
from .face_down import cast_announces_morph
from .game import Game
from .game_result_bans import player_cant_lose
from .oracle import compile_card_oracle
from .models import CardDefinition, PlayerState
from .limited_deck import build_limited_deck, limited_sideboard
from .simulation_checks import _assert_expected, _snap, _zone_counter


@dataclass
class InteractionIssue:
    game_index: int
    turn: int
    message: str


@dataclass
class SimulationReport:
    games_requested: int
    games_completed: int
    interaction_count: int
    issues: list[InteractionIssue] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    #: Casts the engine declined for a rules reason, by the reason it gave.
    #: **Not** issues: a spell refused for want of a legal target is the cast
    #: gate working (CR 601.2c), and nothing is spent. They are counted because
    #: the AI re-proposes the same card the next turn, so a large number here is
    #: a seat doing nothing all game — which no other number in this report
    #: shows.
    refused_casts: Counter[str] = field(default_factory=Counter)
    #: The attack-side twin of the above, and it could not exist until this
    #: simulator had a combat phase: a declaration the engine refuses costs
    #: nothing and breaks no rule, so it fails no assertion — the seat just does
    #: not attack, and proposes the same illegal set again next turn. A non-zero
    #: count means the AI is choosing sets a restriction forbids; a *silent*
    #: one (even the fallback refused) is an issue rather than a count, because
    #: that seat attacks with nobody for the rest of the game.
    refused_attacks: Counter[str] = field(default_factory=Counter)
    #: The block-side twin, and the last of the three declarations this report
    #: can be silent about. `declare_ai_blockers` fell back to `{}` exactly the
    #: way the attack side did before that counter existed, and nothing above it
    #: could tell "the defender chose not to block" from "the defender's whole
    #: declaration was refused": both read as zero blockers. A non-zero count
    #: means the AI is choosing block maps a CR 509.1b restriction forbids; a
    #: *silent* one (even the empty declaration refused) is an issue rather than
    #: a count, because that seat blocks with nobody for the rest of the game.
    refused_blocks: Counter[str] = field(default_factory=Counter)
    #: The activation-side twin of ``refused_casts``, and the one this report
    #: never had: an activation the engine declines spends nothing and breaks
    #: no rule, and the AI proposes it again next turn. NEM's wave 2 found 80 of
    #: them across one ten-game run each of USG, TMP and MMQ by reading the
    #: log by hand — Serra's Hymn announced with no division, Rootwater Diver
    #: and Groundskeeper aimed at an empty graveyard — while every number this
    #: report printed read clean.
    refused_activations: Counter[str] = field(default_factory=Counter)
    #: How much combat actually happened. Reported for the reason
    #: `interaction_count` is: "no illegal interactions" over a run where nobody
    #: ever attacked is a true statement about nothing, and that was every run
    #: this script produced before combat existed here.
    attacks_declared: int = 0
    attackers_declared: int = 0
    blockers_declared: int = 0
    #: See `ai_combat.CombatOutcome`: the multi-blocked / banding splits, not
    #: every combat that dealt damage.
    manual_damage_splits: int = 0
    #: How many ending phases actually ran (CR 512-514), for the reason the
    #: combat counts above exist. Until PCY's wave 2 this loop went main ->
    #: combat -> next seat, so no simulated turn had ever ended: every "until
    #: end of turn" pump and shield lasted the whole game, marked damage was
    #: never removed (CR 514.2), no "at the beginning of the end step" trigger
    #: fired (CR 513.1a) and no hand was ever discarded down to its maximum
    #: (CR 514.1). Zero here is the fourth omission of the "it plays a whole
    #: turn" class coming back.
    end_steps: int = 0
    cleanup_steps: int = 0
    #: Cards the active player discarded to maximum hand size in cleanup
    #: (CR 514.1) — a number that could only ever have read zero before.
    cleanup_discards: int = 0
    #: Abilities activated on a permanent another seat controls (CR 602.1b,
    #: "Any player may activate this ability"). Zero in every run before
    #: `ai_foreign_activations.choose_foreign_activation_action` existed,
    #: because every chooser walked the seat's own battlefield.
    foreign_activations: int = 0
    #: Lands played (CR 305.1), by the land-drop pass rather than as the
    #: turn's one cast. **Not** counted in ``interaction_count``: a land play is
    #: a special action that uses no stack (CR 116.2a), and a run whose only
    #: actions were land drops cast nothing — which is what that count's zero
    #: exists to say. Until PCY's wave 3 a land *was* the turn's cast, so a
    #: seat that played one cast nothing else that turn, and every number this
    #: report printed was over games in which no mana cost was ever paid.
    lands_played: int = 0
    #: Step changes that left something owed behind them, by what and where:
    #: ``"upkeep -> draw: optional_pay (Elfhame Sanctuary)"``. **The sixth
    #: omission of the "it plays a whole turn" class, and the first that is not
    #: a missing phase**: every step ran, in order, and a decision one of them
    #: asked for was taken two steps later. An upkeep trigger's "you may search
    #: your library … If you do, you skip your draw step this turn" was answered
    #: after the draw, so the skip was armed and never spent; Mirri's Guile
    #: arranged the top three after the turn's card had been drawn off them;
    #: a combat trigger's "you may" was taken once combat was over. The run
    #: completed, the interaction count was non-zero and the issue list was
    #: empty — and here the *log* read right too, because each line was there,
    #: in the wrong order.
    #:
    #: Counted by the game itself at the one line every step change passes
    #: through (``_SimulatedGame._set_phase_and_step``), never by this module's
    #: own walk, because the walk is what was wrong. Zero is the claim that no
    #: step of any simulated turn ended around an unanswered question (CR 608.2,
    #: CR 500.2); ``simulate_ai_games.py`` exits 1 on anything else.
    steps_left_owing: Counter[str] = field(default_factory=Counter)
    #: Turns that were **extra** turns (CR 500.7) — Time Walk's, Time Warp's,
    #: Final Fortune's. Zero in every run before INV's wave 2, and not because
    #: no seat cast one: the loop alternated the two seats itself, so an extra
    #: turn was queued by the spell and never taken, and "you skip your next
    #: turn" (Meditate, Chronatog) skipped nothing. The seventh omission of
    #: the class, found by counting the queue at the end of four games with
    #: Time Walk pinned: five resolved, five still queued.
    extra_turns_taken: int = 0
    #: Modal spells cast ("Choose one —", CR 700.2), by the index of the mode
    #: each cast named. **Every key was 0 before the AI had a mode chooser**:
    #: the policy named no mode, the engine resolved the first bullet, and a
    #: run over a set of Charms read exactly as clean as it does now — the
    #: card was cast, it resolved, nothing was refused. A report whose only
    #: key is 0 over a pool that prints modal spells is that coming back.
    modal_casts: Counter[int] = field(default_factory=Counter)
    #: Spells cast — and lands played — from a zone **other than the hand**
    #: (CR 601.3), by the zone: ``"graveyard"`` (flashback, CR 702.34a;
    #: Yawgmoth's Will), ``"exile"`` (an Elkin Bottle's card), ``"library"``
    #: (Temporal Aperture's top card), ``"command"`` (CR 903.8). **Empty in
    #: every run before ODY's wave 2**, and not because no deck held such a
    #: card: `ai_policy.choose_cast_action` walked the hand and nothing else,
    #: so the second half of every flashback card — Odyssey's headline
    #: mechanic, 28 cards — was text no simulated game reached, and the run
    #: read exactly as clean as it does now. Each card was cast from hand, it
    #: resolved, nothing was refused. A report with no ``"graveyard"`` key over
    #: a pool that prints flashback is that coming back.
    casts_from_zones: Counter[str] = field(default_factory=Counter)
    #: How many step changes that count was taken over. A zero above means
    #: something only beside a number here: an instrument that looked at
    #: nothing reports nothing owed.
    step_changes: int = 0
    #: Rehearsals that **raised** during this run, by what was being rehearsed
    #: and what the engine raised (``ai_rehearsal.REHEARSALS_RAISED``).
    #:
    #: The policy carries a candidate cast out on a copy of the game before it
    #: proposes it, and a copy that raises answers "this could not be weighed"
    #: — so an engine exception on a card's cast, which used to stop a
    #: simulated run on the spot (that was how a crash-on-cast card was
    #: found), is now caught one layer down and read as a quiet "no". Where
    #: the policy's answer to "could not be weighed" is to hold the card, that
    #: card is never cast again and nothing says why. So it is counted, each
    #: distinct one is an issue naming the card and the exception, and
    #: ``simulate_ai_games.py`` exits 1 on any: a raised rehearsal is a crash
    #: the game was spared, not a decision.
    rehearsals_raised: Counter[str] = field(default_factory=Counter)
    #: Spells cast **when the engine gave a seat priority** somewhere other
    #: than its own main phase (`Game.priority_driver`, answered by
    #: `_answer_priority`): in response to an object on the stack another seat
    #: controls, in combat, and on the opponent's turn — three overlapping
    #: views of the same casts (a Giant Growth answering a block on the
    #: opponent's turn is all three). **All three read 0 in every run before
    #: round 4**: the engine's headless window was "both players pass", so a
    #: simulated seat cast in its own main phase and nowhere else, and no
    #: counterspell, combat trick, Fog or end-of-turn removal had ever been
    #: cast in a simulated game. The run read exactly as clean as it does now.
    casts_in_response: int = 0
    casts_in_combat: int = 0
    casts_on_opponents_turn: int = 0
    #: Of the casts in combat, those made in the declare-attackers step with
    #: the attack declared and the blocks still to come (the
    #: ``"declare_attackers"`` window, CR 508.2): a creature flashed in to
    #: block with. **Zero in every run before kg3**: that window was passed
    #: without asking, so no simulated seat had ever cast an ambush blocker,
    #: and a flash creature came down at the end step or not at all.
    casts_before_blocks: int = 0
    #: The refusals among them, by card and the engine's reason — counted like
    #: ``refused_casts``, because a refused response costs nothing but the
    #: mana its taps floated, and the seat proposes it again at the next window.
    refused_instant_casts: Counter[str] = field(default_factory=Counter)
    #: How many times a seat was given priority in one of the windows the
    #: simulator answers (`ai_priority.instant_speed_window`), and in how many of those it
    #: held an instant it could pay for, so the chooser was asked. The zeroes
    #: above mean something only beside these: a run whose windows were never
    #: opened reports no response cast in exactly the way a run with no
    #: windows did.
    priority_offers: int = 0
    priority_offers_weighed: int = 0
    #: Abilities activated at the same moments, by window (``"response"``,
    #: ``"declare_attackers"``, ``"combat"``, ``"end_step"`` —
    #: `ai_priority.instant_speed_window` — and ``"upkeep"``, the seat's own, for its
    #: graveyard alone), and the
    #: refusals among them. Empty in every run before round 4 for the casts'
    #: reason: the only activations a simulated seat made were its own main
    #: phase's, so a regeneration shield was never raised in front of the
    #: spell it answers.
    activations_at_instant_speed: Counter[str] = field(default_factory=Counter)
    refused_instant_activations: Counter[str] = field(default_factory=Counter)
    #: CR 116.2c-e special actions a seat took (`ai_special_actions`), by the
    #: offer's kind — "ignore_attached_static_until_eot" for a creature bought
    #: a turn off Volrath's Curse or Lost in Thought. **Empty in every run
    #: before JUD's wave 2**, and not because nothing was offered: the offer
    #: stood every main phase and no AI path answered it, so a cursed creature
    #: never attacked again however cheap the price — and the run read exactly
    #: as clean as it does now. The refusals among them are beside it.
    special_actions_taken: Counter[str] = field(default_factory=Counter)
    refused_special_actions: Counter[str] = field(default_factory=Counter)
    #: Spells cast **face down** for a morph cost (CR 702.37c), by the card
    #: each one hid. Its partner is ``special_actions_taken["turn_face_up"]``
    #: (CR 702.37e): one counts the morphs put on the table, the other the
    #: ones turned up. **Both zero in every run before ONS's wave 1**, and
    #: necessarily — no card could be cast face down — so a pool printing
    #: morph that reads zero here is that coming back, or the policy never
    #: finding the {3} worth it.
    face_down_casts: Counter[str] = field(default_factory=Counter)
    #: Cards brought into a game from a seat's sideboard (CR 400.11b: a Wish,
    #: Ring of Ma'rûf), counted off the sideboards at each game's end. **Zero in
    #: every run before JUD's wave 2**, and necessarily: no seat was dealt a
    #: sideboard, so the offer was never made and the cast was never proposed.
    #: A zero over a pool that prints a Wish is that coming back.
    cards_from_outside_game: int = 0
    #: Mulligans taken (CR 103.5), by ``ai_mulligan``'s keep decision. **Zero
    #: in every run before the ``kg2`` round**: each seat kept what it was
    #: dealt, so a one-land seven was played out. Zero over a run of games is
    #: that coming back (one seat in nine is dealt 0-1 or 6-7 lands).
    mulligans_taken: int = 0
    #: Abilities activated from a card **in its owner's graveyard** (CR
    #: 113.6b/m — Ashen Ghoul, Carrionette, Glory, Necrosavant, Shard
    #: Phoenix, Whiteout), by the card. **Empty in every run before the kg3
    #: round**: no AI path called `Game.activate_from_graveyard`, so each such
    #: card was put in a graveyard and left there, and the run read exactly as
    #: clean as it does now. Counted wherever one is taken — the main phase,
    #: the seat's own upkeep (where most of them may only be activated) and
    #: the priority windows (`_answer_priority`). A pool printing one that
    #: reads empty here is that coming back.
    activations_from_graveyard: Counter[str] = field(default_factory=Counter)
    #: Abilities activated from a card **in its owner's hand** at instant
    #: speed (CR 113.6j — a cycle whose trigger pays then: Decree of Silence
    #: in response to a spell), by the card. **Empty in every run before the
    #: kg4 round**: the hand was asked in its owner's main phase alone, so a
    #: cycle's "you may counter target spell" was spent on an empty stack.
    #: Counted by `_answer_priority`; the main phase's cycles are its own log
    #: lines.
    activations_from_hand_at_instant_speed: Counter[str] = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return not self.issues


# The prompts a headless simulation answers for itself, in the order it answers
# them. Naming the kinds rather than draining the whole queue keeps the order
# fixed: a library search consumes randomness, so which prompt is answered first
# is part of what a seed reproduces.
#
# Every kind registered ``suspends`` has to appear here, and that is a stronger
# requirement than "otherwise its prompt sits unanswered": a suspending prompt
# holds the rest of its resolution on ``game.resume_stack``, so leaving one
# owed would leave that resolution unfinished for the rest of the game (and,
# before Judgment's W2G2, stopped the *next* resumable loop anywhere in the
# game after one step). ``effect_order`` is the
# one exception and does not need draining — a non-interactive seat is answered
# with the default before it is ever queued (engine/replacements/). Held by
# tests/ai/test_ai_simulator.py.
_SIMULATED_CHOICES = (
    "search_library", "search_exile_cards", "scry", "reorder_library", "discard",
    "balance", "optional_pay", "untap_up_to", "look_top_pick",
    # Appended rather than inserted: no deck the simulator builds arms this
    # one today, so the position cannot change an existing seed, and a
    # blocking prompt left owed would freeze the seat that owes it.
    "revealed_hand_pick",
    # A counted search's "which found card goes where" — consumes no
    # randomness (the shuffle was the search's), but it suspends, so leaving
    # one owed would wedge every later resumable loop.
    "search_destination",
    # "Choose a number" (Shapeshifter) and "remove any number of counters"
    # (Tetravus). Appended for the same reason as the two above: no deck the
    # simulator builds arms one today, so the position cannot change an
    # existing seed — and the counter form suspends.
    "number_choice",
    # "Put two cards from your hand on top of your library" (Brainstorm,
    # Stunted Growth). Appended, and this one a simulated deck really can arm —
    # it suspends, so a seat left owing it would wedge every later resumable
    # loop, which is what the guard beside this list checks for.
    "hand_to_library",
    # "Target opponent chooses a card in your graveyard" (Forgotten Lore).
    # Appended for the reason the three above are: no seed builds a deck that
    # arms it today, so the position cannot change an existing run - and it
    # suspends, because the sentence after it reads the pick and the round
    # after that may not choose it again.
    "graveyard_pick_for_price",
    # "Choose a card name." (Foreshadow.) Appended for the reason the entries
    # above are — the position cannot change an existing seed — and it
    # suspends, so a seat left owing it would wedge every later resumable loop.
    "choose_card_name",
    # "Each player may draw up to two cards" (Truce). Appended for the reason
    # the four above are — the position cannot change an existing seed — and it
    # suspends, so a seat left owing it would wedge every later resumable loop.
    # A simulated HML deck really can arm it, and on *every* seat at once.
    "draw_up_to",
    # "Exile any number of cards from your hand face down." (Scroll Rack.)
    # Appended for the reason every entry above it is — the position cannot
    # change an existing seed — and it suspends, because the sentence behind it
    # puts *that many* cards from the library into the hand. A simulated TMP
    # deck really can arm it.
    "exile_hand_pile_choice",
    # "Starting with you, each player chooses one of the exiled cards and
    # puts it onto the battlefield tapped under their control." (Thieves'
    # Auction.) Appended for the reason every entry above it is — the
    # position cannot change an existing seed — and it suspends hardest of
    # any of them: the whole of the rest of the resolution is other seats
    # picking out of the pile this answer shortens, so a seat left owing it
    # would wedge the round-robin and every later resumable loop with it.
    "exiled_pile_claim",
    # "…becomes the basic land type of your choice" (Jinx, Shimmering Mirage;
    # Phantasmal Terrain as it enters). Appended for the reason every entry
    # above it is. It was answered by the catch-all pass below while it only
    # held priority; it suspends now — the step behind it (Shimmering Mirage's
    # draw) waits for the type — so it belongs to the named pass, last, which
    # is where the catch-all answered it when nothing else was queued.
    "land_type_choice",
)


def _resolve_pending_choices(game: Game) -> None:
    """Answer every prompt the table is owed, with each kind's own default.

    The named kinds first and in their fixed order, which is what a seed
    reproduces. **Then everything else that is queued.** The list above was
    also the *whole* of what this answered, and the guard beside it only asks
    that the suspending kinds are on it — so a kind that holds priority without
    suspending was simply never answered, for the life of the game. Phantasmal
    Terrain's "As this Aura enters, choose a basic land type"
    (``land_type_choice``) sat queued 26 times in a ten-game Invasion run; the
    Aura was on the battlefield and changed no land. The web layer's AI seat
    has never had this hole, because ``web/prompts.auto_resolve_ai_prompts`` is
    generic over the queue; this is now the same statement.

    It is also `Game.prompt_driver` for a simulated game — see
    `run_ai_simulation` — so the engine calls it between one stack object and
    the next rather than this module remembering to after each step.
    """
    game.auto_resolve_pending_choices(kinds=_SIMULATED_CHOICES)
    if game.pending_choices:
        game.auto_resolve_pending_choices()


class _SimulatedGame(Game):
    """A `Game` that counts what each step leaves owed as the next one begins.

    The honesty check for `SimulationReport.steps_left_owing`, and a subclass
    rather than a field on `Game` because it is the simulator's instrument: the
    engine has nothing to do with the answer. `_set_phase_and_step` is the line
    every way into a step already passes through, so the count cannot be
    walked around by a driver that orders its own calls differently — which is
    the failure it exists to see.

    Two things can be owed. A **prompt** the game is waiting on
    (`Game.waiting_prompt`: the kinds that hold priority, so a notification
    such as a revealed hand is not one), from any step. And an **object still
    on the stack**, from a step that has a priority window — the untap step has
    none (CR 502.4: a trigger from it waits for the upkeep) and neither,
    ordinarily, has cleanup (CR 514.3), so a stack carried out of those is the
    rules working.
    """

    def _set_phase_and_step(self, phase: str, step: str) -> None:
        leaving = self.current_step
        if leaving and leaving != step:
            self._steps_left_owing["_examined"] += 1
            for what in _owed_when_leaving(self, leaving):
                self._steps_left_owing[f"{leaving} -> {step}: {what}"] += 1
        super()._set_phase_and_step(phase, step)

    @property
    def _steps_left_owing(self) -> Counter[str]:
        return self.__dict__.setdefault("_w2g6_steps_left_owing", Counter())


def _owed_when_leaving(game: Game, leaving_step: str) -> list[str]:
    """What *leaving_step* is ending around — see `_SimulatedGame`."""
    owed: list[str] = []
    if game.pending_choices or game.pending_replacement_choices:
        waiting = game.waiting_prompt()
        if waiting is not None:
            source = waiting.data.get("card_name") or waiting.data.get("source_name")
            owed.append(f"{waiting.kind}" + (f" ({source})" if source else ""))
    if game.stack and game._receives_priority(leaving_step):
        owed.append(f"{game.stack[-1].card.name} on the stack")
    return owed


def _execute_foreign_activation(
    game: Game, active: int, action, report: SimulationReport,
    game_index: int, turn: int,
) -> None:
    """Carry out `ai_foreign_activations.choose_foreign_activation_action`'s
    choice.

    The activator pays (CR 602.1a) from its own lands, so the taps are on
    *active*'s board; the permanent is on ``action.source_controller_index``'s,
    which is what ``activate_permanent_ability`` counts ``permanent_index``
    into when it is given that seat.
    """
    # The action as it reads once it is paid for — see `tap_planned_lands`.
    action = tap_planned_lands(game, active, action)
    result = game.activate_permanent_ability(
        active, action.permanent_name, **activation_announcement(action),
    )
    _resolve_pending_choices(game)
    report.interaction_count += 1
    report.foreign_activations += 1
    owner = game.players[action.source_controller_index].name
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[active].name} "
        f"activate {owner}'s {action.permanent_name} -> {result.details}"
    )
    if not result.supported:
        report.refused_activations[
            f"{action.permanent_name} ({owner}'s): {result.details}"
        ] += 1


#: Bounds on the main phase's two repeated passes. A turn has one land drop
#: plus whatever an allowance adds (CR 305.2) — Fastbond's "any number" is
#: bounded by the hand, and this by a number no real hand reaches, so a land
#: that returns itself to hand on entering cannot loop. Casts are bounded by
#: the mana the seat has, and this by a number a turn's mana does not reach
#: in a limited deck, so a spell that untaps lands or returns itself cannot.
_MAX_LAND_DROPS = 8
_MAX_CASTS_PER_MAIN_PHASE = 8


def _play_land_drops(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """The turn's land drops (CR 305.1/305.2), before anything is cast.

    **Their own pass, and first**, because a land was the turn's one *cast*
    until PCY's wave 3: ``choose_cast_action`` scored a land 1.0 and every
    spell at least 1.5, so a seat that played a land cast nothing else that
    turn and a seat holding a spell kept its land in hand. That was invisible
    for as long as this simulator ignored mana costs — a spell cost nothing,
    so the land lost every comparison it should have won. How many drops the
    turn has is `Game._may_play_another_land`'s answer (asked inside
    `ai_policy.choose_land_drop`), the one every land-drop gate asks, so an
    additional-land effect gives the seat its extra plays here too.

    A refused play is counted with the refused casts and ends the pass: the
    chooser asks the cast path's own gates, so a refusal is a policy bug to
    surface rather than a land to retry.
    """
    seat_name = game.players[active].name
    for _ in range(_MAX_LAND_DROPS):
        if game.is_game_over():
            return
        action = choose_land_drop(game, active)
        if action is None:
            return
        # The land the chooser named, out of the zone it named: the hand, or a
        # zone an effect lets the seat **play** from (CR 305.1 with CR 601.3's
        # permission: an Elkin Bottle's exiled land, a graveyard under
        # Yawgmoth's Will). Through `cast_announcement` like every cast — the
        # zone is part of what is announced, and for a land in hand the rest
        # of that dict is the defaults this call always took.
        land = zone_being_cast_from(game, active, action)[action.hand_index]
        result = game.cast_from_hand(
            active, land.name, **cast_announcement(action),
        )
        _resolve_pending_choices(game)
        report.log_lines.append(
            f"G{game_index} T{turn} {seat_name} play {land.name} -> {result.details}"
            + _zone_named(action)
        )
        if not result.supported:
            report.refused_casts[f"{land.name}: {result.details}"] += 1
            return
        report.lands_played += 1
        if action.from_zone != "hand":
            report.casts_from_zones[action.from_zone] += 1


def _play_one_cast(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> bool:
    """Cast what `ai_policy.choose_cast_action` proposes, paying for it.

    True when a spell was cast and accepted, so the caller may ask for another;
    False when nothing was proposed or the cast was refused — a refusal is not
    retried, because the policy would propose the same card again.
    """
    active_player = game.players[active]
    cast_action = choose_cast_action(game, active)
    if cast_action is None:
        return False
    # `hand_index` indexes the zone `from_zone` names — the hand, the command
    # zone, or a graveyard, an exile or a library an effect has opened
    # (CR 601.3: a flashback card, a card an Elkin Bottle exiled) — through the
    # one reader every executor shares. This read "the command zone for a
    # commander cast, the hand otherwise", so a cast proposed from a graveyard
    # would have been read off the hand at the graveyard's index.
    cast_zone = zone_being_cast_from(game, active, cast_action)
    # The spell, not the zone's card: a split card is cast as the half the
    # policy scored (CR 709.3), and every line below — the cast, the log, the
    # support check, the effect audit — is about that half.
    card_to_cast = spell_being_cast(cast_zone, cast_action)

    # The payment: the planned lands tapped into the pool, each for the colour
    # the plan counted on (`ai_payment.tap_planned_lands`, the web AI seat's
    # executor too); the cast below spends it. What comes back is the action
    # **as it reads now**: a source that pays by being sacrificed renumbers
    # the battlefield under every slot the announcement names.
    cast_action = tap_planned_lands(game, active, cast_action)

    before = _snap(game)
    answered_before = report.casts_in_response
    # Forward the *whole* choice. Dropping the permanent target was invisible
    # while the decklist was eight cards that target a player or nothing: an
    # Aura reaches `cast_from_hand` with no index and is refused ("Evil
    # Presence requires a target", CR 601.2c/115.1b), and the AI had already
    # picked a legal land for it.
    #
    # Through `ai_actions.cast_announcement`, the one function that turns a
    # `CastAction` into a cast: the seat, the object, the X, the alternative
    # cost (CR 118.9), the division (CR 601.2d), the optional costs and the
    # mode (CR 601.2b). Each of those was once a keyword spelled here and
    # missing from another executor.
    # CR 702.37c: whether this announcement casts the card face down — asked
    # of the engine's own reading of it before the card leaves the zone.
    morphed = cast_announces_morph(game, active, card_to_cast, cast_action)
    result = game.cast_from_hand(
        active, card_to_cast.name, **cast_announcement(cast_action),
    )
    _resolve_pending_choices(game)
    after = _snap(game)
    report.interaction_count += 1
    if result.supported and morphed:
        report.face_down_casts[card_to_cast.name] += 1
    # Which mode, for a modal spell — after the outcome, so the line still
    # reads "cast <name> -> <outcome>" for everything that greps it.
    modes_named = _modes_named(card_to_cast, cast_action)
    named = "".join(
        f" [mode {index}: {label}]" for index, label in modes_named
    )
    report.log_lines.append(
        f"G{game_index} T{turn} {active_player.name} cast {card_to_cast.name} "
        f"-> {result.details}{named}{_zone_named(cast_action)}"
    )
    if result.supported:
        report.modal_casts.update(index for index, _label in modes_named)
        if cast_action.from_zone != "hand":
            report.casts_from_zones[cast_action.from_zone] += 1
    if not result.supported:
        # Two different things wore one message. `supported` on a cast result
        # means "the cast went through", so a spell declined for want of a
        # legal target, for a printed timing clause or by City in a Bottle was
        # reported as an *unsupported card* — which the pool has none of. Ask
        # the compiler, which is what that word actually means.
        if not compile_card_oracle(card_to_cast).supported:
            report.issues.append(InteractionIssue(
                game_index, turn,
                f"Unsupported card cast in simulation: {card_to_cast.name}",
            ))
        else:
            report.refused_casts[f"{card_to_cast.name}: {result.details}"] += 1
        # The oracle below is about what a spell *did*, and a refused one did
        # nothing — asked anyway, it reported a refused Unsummon as "did not
        # remove one target creature", an issue out of a cast that broke no
        # rule. Unreachable while every cast was free; one refusal for want of
        # mana made it a false exit 1 (5ED's run, once costs were enforced).
        return False
    if report.casts_in_response != answered_before:
        # The other seat answered the spell before it resolved (the engine
        # gives priority before each resolution, `Game.priority_driver`): a
        # Bolt countered, or its damage prevented by a response, dealt less
        # than it prints and broke no rule. The oracle below is about a
        # resolution nothing else touched — "nothing else in these pools
        # deals damage to the Bolt's target as it is cast" — which is no
        # longer this one.
        return True
    expectation_error = _assert_expected(
        card_to_cast, before, after, active, cast_action.target_player_index,
        named_a_permanent=bool(cast_action.target_permanent_ids),
    )
    if expectation_error:
        report.issues.append(InteractionIssue(game_index, turn, expectation_error))
    return True


def _zone_named(cast_action) -> str:
    """`` [from graveyard]`` for a cast or a land play out of a zone other
    than the hand, and nothing for one out of it — after the outcome, like the
    mode, so every line about a hand cast reads as it always did."""
    if cast_action.from_zone == "hand":
        return ""
    return f" [from {cast_action.from_zone}]"


def _modes_named(card: CardDefinition, cast_action) -> list[tuple[int, str]]:
    """``(mode index, printed bullet)`` for each mode a cast of *card*
    resolves, or ``[]`` for a spell whose caster chooses no mode.

    A modal spell cast naming none is mode 0 — that is what the engine resolves
    it as (`cast_targets.announced_mode_instructions`), and it is what every
    simulated cast was before the policy had a mode to name.
    """
    program = compile_card_oracle(card)
    if (
        card.primary_type not in ("instant", "sorcery")
        or not program.modes
        or program.mode_chooser is not None
    ):
        return []
    if cast_action.mode_choices:
        indices = sorted(int(choice["index"]) for choice in cast_action.mode_choices)
    else:
        indices = [cast_action.mode_index or 0]
    return [
        (index, program.modes[index].label)
        for index in indices if 0 <= index < len(program.modes)
    ]


def _play_casts(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """Cast spells until the seat proposes nothing it can pay for.

    **More than one**, now that each one is paid for: a cast was the turn's one
    action while mana was free, which cost nothing to model and was no less
    true than the free mana itself. With costs enforced, one spell per turn is
    a seat that taps two of its six lands and passes holding a hand of
    two-drops — and the deck builder deals the cheapest spells it can, so that
    was most turns of most games. Each cast plans against the lands the last
    one left untapped, so the loop ends when the mana does.

    The land-drop pass is asked again after every cast, because a spell can
    grant a drop the turn did not have when the pass first ran ("You may play
    any number of lands on each of your turns", Fastbond; Summer Bloom) — and
    a drop left there was taken by the cast chooser instead, as a "cast", which
    is the land-as-the-turn's-action shape this pass exists to end.
    """
    for _ in range(_MAX_CASTS_PER_MAIN_PHASE):
        if game.is_game_over():
            return
        if not _play_one_cast(game, active, report, game_index, turn):
            return
        _play_land_drops(game, active, report, game_index, turn)


def _casts_on_loan(game: Game, seat: int) -> frozenset:
    """Which casts from outside its hand *seat* is offered right now
    (`ai_weighed_cast.permitted_casts`), as ``(zone, pile's seat, spell name)`` —
    so the main loop can tell when an activation has opened a new one."""
    return frozenset(
        (permitted.zone, permitted.owner_seat, permitted.spell.name)
        for permitted in permitted_casts(game, seat)
    )


def _play_activations(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """One ability on the seat's own battlefield, one from its hand, one from
    its graveyard and one on another seat's battlefield, each planned against
    the lands the casts left untapped and paid for the same way."""
    active_player = game.players[active]
    activation_action = None if game.is_game_over() else choose_activation_action(game, active)
    if activation_action is not None:
        activation_action = tap_planned_lands(game, active, activation_action)
        # The whole announcement, from the one place an action becomes one
        # (`ai_actions.activation_announcement`): the targets, a "Choose
        # flying, …" word, the card a "Discard a card" cost takes, which
        # ability, an X, a text change's two words.
        result = game.activate_permanent_ability(
            active, activation_action.permanent_name,
            **activation_announcement(activation_action),
        )
        _resolve_pending_choices(game)
        report.interaction_count += 1
        report.log_lines.append(
            f"G{game_index} T{turn} {active_player.name} "
            f"activate {activation_action.permanent_name} -> {result.details}"
        )
        if not result.supported:
            report.refused_activations[
                f"{activation_action.permanent_name}: {result.details}"
            ] += 1

    # An ability activated from the seat's **hand** (CR 113.6j) — cycling. A
    # separate pass rather than a branch above, because `activate_from_hand`
    # takes neither a permanent nor a target; after the battlefield pass, so
    # the lands it plans against are the ones nothing else wanted.
    hand_activation = (
        None if game.is_game_over()
        else choose_hand_activation_action(game, active)
    )
    if hand_activation is not None:
        hand_activation = tap_planned_lands(game, active, hand_activation)
        result = game.activate_from_hand(
            active,
            hand_activation.card_name,
            ability_index=hand_activation.ability_index,
            hand_index=hand_activation.hand_index,
        )
        if result.supported:
            # `activate_from_hand` is the **queue** form — the web's, which
            # leaves the ability on the stack for the table to respond to
            # (CR 117.3c). `activate_permanent_ability`, above, settles what it
            # queues; this entry point has no such twin, so the settling is
            # done here, with the engine's own loop. Without it a cycling
            # ability sat on the stack through the rest of the main phase and
            # the step ended around it — every simulated cycle in a precombat
            # main phase, which is why all three Urza's sets exited 1 on
            # `steps_left_owing` and no other set printed the keyword to show
            # it.
            game._settle()
            game.clear_priority_window()
        _resolve_pending_choices(game)
        report.interaction_count += 1
        report.log_lines.append(
            f"G{game_index} T{turn} {active_player.name} "
            f"activate {hand_activation.card_name} from hand "
            f"-> {result.details}"
        )
        if not result.supported:
            report.refused_activations[
                f"{hand_activation.card_name} (from hand): {result.details}"
            ] += 1

    # An ability activated from the seat's **graveyard** (CR 113.6b/m) —
    # Whiteout's return, Carrionette's exile, Glory's shield. The engine's
    # third activation door, so a third pass, after the hand's for its reason.
    # Settled here as the hand's is: `activate_from_graveyard` is the queue
    # form too.
    graveyard_activation = (
        None if game.is_game_over()
        else choose_graveyard_activation_action(game, active)
    )
    if graveyard_activation is not None:
        result = activate_chosen_graveyard_ability(game, active, graveyard_activation)
        if result.supported:
            game._settle()
            game.clear_priority_window()
        _resolve_pending_choices(game)
        report.interaction_count += 1
        report.log_lines.append(
            f"G{game_index} T{turn} {active_player.name} "
            f"activate {graveyard_activation.card_name} from graveyard "
            f"-> {result.details}"
        )
        if result.supported:
            report.activations_from_graveyard[graveyard_activation.card_name] += 1
        else:
            report.refused_activations[
                f"{graveyard_activation.card_name} (from graveyard): {result.details}"
            ] += 1

    # An ability on a permanent **another seat controls** that this seat may
    # activate (CR 602.1b, "Any player may activate this ability"). Last of the
    # main-phase passes, so it spends only mana nothing of the seat's own
    # wanted. No simulated seat had ever done this: every chooser walked its
    # own board.
    foreign_activation = (
        None if game.is_game_over()
        else choose_foreign_activation_action(game, active)
    )
    if foreign_activation is not None:
        _execute_foreign_activation(
            game, active, foreign_activation, report, game_index, turn,
        )


def _play_special_actions(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """The CR 116 special action the seat takes before its combat, if any
    (`ai_special_actions.special_action_before_combat`, which holds the
    priority the action needs), counted."""
    taken = special_action_before_combat(game, active)
    if taken is None:
        return
    choice, refusal = taken
    _resolve_pending_choices(game)
    # "When this creature is turned face up, …" (CR 702.37e, 603.3): the
    # trigger is on the stack in this main phase, and it resolves here (CR
    # 116.3), before the combat it may decide (Patron of the Wild's +3/+3,
    # Skirk Marauder's 2 damage, Warbreak Trumpeter's Goblins) — it was
    # carried across the step into the beginning of combat.
    if refusal is None and game.stack:
        _drain_step(game)
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[active].name} special action "
        f"{choice.kind} ({choice.name}) -> {refusal or 'taken'}"
    )
    if refusal is None:
        report.special_actions_taken[choice.kind] += 1
    else:
        report.refused_special_actions[f"{choice.name}: {refusal}"] += 1


def _play_combat_phase(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """One combat phase through `ai_combat.run_ai_combat_phase`, recorded.

    A function rather than the inline block it was, because a turn can now
    reach a combat phase from two places: the turn's own, and one CR 500.8 adds
    after the postcombat main phase (Relentless Assault), which the ending-phase
    walk below enters through the turn's plan.
    """
    combat = run_ai_combat_phase(game, active)
    report.attacks_declared += combat.attacks_declared
    report.attackers_declared += combat.attackers
    report.blockers_declared += combat.blockers
    report.manual_damage_splits += combat.manual_damage_splits
    for seat_name, why in combat.refused_attacks:
        report.refused_attacks[f"{seat_name}: {why}"] += 1
    for seat_name, why in combat.silent_attacks:
        report.issues.append(InteractionIssue(
            game_index, turn,
            f"{seat_name} attacked with nobody: even the "
            f"every-legal-attacker fallback was refused ({why})",
        ))
    for seat_name, why in combat.refused_blocks:
        report.refused_blocks[f"{seat_name}: {why}"] += 1
    for seat_name, why in combat.silent_blocks:
        report.issues.append(InteractionIssue(
            game_index, turn,
            f"{seat_name} blocked with nobody: even the empty "
            f"declaration was refused ({why})",
        ))
    _resolve_pending_choices(game)


#: Bounds on the two loops below. Generous: a turn has five phases plus
#: whatever CR 500.8 adds, and a step's stack is drained in one pass unless a
#: drained choice put something new on it.
_MAX_REMAINING_PHASES = 12
_MAX_DRAIN_PASSES = 8


def _drain_step(game: Game) -> None:
    """Resolve a step's stack and the prompts it armed, until neither moves.

    `_resolve_priority_window` stops at an object whose resolution is held for
    an answer (CR 608.2) and the simulator answers afterwards, so one pass can
    leave the rest of the step's triggers waiting behind the one that asked.
    In a main phase the cast that follows drains them; nothing follows an end
    step but cleanup, so they would otherwise resolve a turn late, in the next
    turn's upkeep.
    """
    for _ in range(_MAX_DRAIN_PASSES):
        game._resolve_priority_window()
        _resolve_pending_choices(game)
        if not game.stack:
            return


def _play_rest_of_turn(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """Everything after the turn's first combat phase: the postcombat main
    phase, any phase CR 500.8 added, and the ending phase (CR 512-514).

    The **fourth** omission of the "it plays a whole turn" class, after
    `begin_turn_bookkeeping`, the precombat main phase and combat, and it
    failed the way all three did: the run completed, the interaction count was
    non-zero and the issue list was empty. What was missing was every end of
    every turn. W1G1 counted ``resolve_end_step`` = 0 and
    ``resolve_cleanup_step`` = 0 over three LEA games; W1G2 watched a Snag cast
    on turn 4 still preventing damage on turn 18. Every "until end of turn"
    effect in every simulated game was permanent, marked damage accumulated
    across turns, no end-step trigger ever fired and no hand was ever
    discarded down to its maximum.

    **The walk is the engine's, not this function's.** Which phase comes next
    is `Game.enter_next_turn_phase`, the seam the web layer's phase rail goes
    through — so an extra combat phase (Relentless Assault) is entered and
    fought rather than skipped, and the ending phase is entered by the same
    call that would enter anything else. What this function supplies is only
    what the engine waits for a *player* to do: close a main phase nobody is
    casting in, fight a combat phase, and walk the end step's priority window
    to cleanup, which is the web layer's ``step == "end"`` branch
    (``close_end_step`` then ``resolve_cleanup_step``) for a seat nobody asks.

    Cleanup's discard is the engine's own non-interactive default, the same
    one an AI seat gets in the web app (``defer_discard_selection`` is only
    ever set for a human), so a simulated game and an unattended web game
    discard the same cards.
    """
    for _ in range(_MAX_REMAINING_PHASES):
        if game.is_game_over():
            return
        phase = game.current_turn_phase
        if phase == "ending":
            break
        if phase == "combat":
            # Still inside a combat phase the driver could not finish: a prompt
            # it does not answer is outstanding, or a resolution is suspended.
            # `run_ai_combat_phase` left the phase where it stood rather than
            # forcing it, and so does this — the turn ends unfinished, as every
            # turn did before this function existed, rather than re-entering a
            # combat that has already declared.
            return
        # A main phase. The simulator casts in the precombat one only, so this
        # is the postcombat one or an extra one: nothing is done in it, its
        # priority window (and any "each of your main phases" trigger the entry
        # announced) is drained, and the turn's plan says what follows.
        game._close_current_priority_step()
        _resolve_pending_choices(game)
        entered = game.enter_next_turn_phase(phase)
        if entered is None:
            return
        if entered == "combat":
            # CR 500.8's "additional combat phase" (Relentless Assault),
            # entered by the plan and fought like the turn's own.
            _play_combat_phase(game, active, report, game_index, turn)
    else:
        return

    if game.is_game_over():
        return
    # CR 513: `enter_turn_phase("ending")` ran `resolve_end_step`, which put the
    # "at the beginning of the end step" triggers on the stack and opened the
    # active player's priority window. The window gives each seat priority
    # before each trigger resolves and once more with the stack empty
    # (`Game.offer_priority`), which is where the opponent's end-of-turn
    # instant is cast (`ai_priority.instant_speed_window`).
    _drain_step(game)
    report.end_steps += 1
    if game.is_game_over():
        return
    game.close_end_step()
    # CR 514: discard to hand size, then CR 514.2's "until end of turn" ends
    # and damage is removed.
    hand_before = len(game.players[active].hand)
    game.resolve_cleanup_step(active)
    _drain_step(game)
    report.cleanup_steps += 1
    report.cleanup_discards += max(0, hand_before - len(game.players[active].hand))


def _priority_answerer(table: Game, report: SimulationReport, game_index: int, clock: list):
    """`Game.priority_driver` for one simulated game.

    A closure rather than a bound method or a partial, for what a rehearsal
    does with the game: it deep-copies it, and a copy carries this attribute
    with it. A function is copied as itself, so the copy's driver is this one —
    which answers only for *table*, the game it was made for, and only outside
    a rehearsal (`ai_rehearsal.rehearsing`): a copy's priority is passed, as
    every copy's was before there was a driver. A method or a partial would
    have copied the report into every rehearsal.

    *clock* is ``[turn]``, the round the report's lines are numbered by,
    which the turn loop updates.
    """

    def answer(game: Game, seat: int) -> bool:
        if game is not table or rehearsing():
            return False
        return _answer_priority(game, seat, report, game_index, clock[0])

    return answer


def _answer_priority(
    game: Game, seat: int, report: SimulationReport, game_index: int, turn: int
) -> bool:
    """*seat* has priority (`Game.offer_priority`): the answer every table
    that plays a seat nobody asks gives — the web AI seat's too
    (`ai_priority.act_at_priority`: its windows, ``instant_speed_window``;
    an instant, then an ability at instant speed, then one of a card in the
    graveyard) — recorded. True when something went on the stack.

    The offer counts are for the windows the instant choosers weigh: the
    seat's own upkeep, answered for its graveyard alone, is not one of them.
    """
    asked = PriorityAsk()
    act = act_at_priority(game, seat, asked=asked)
    report.priority_offers += asked.offered
    report.priority_offers_weighed += asked.weighed
    if act is None:
        return False
    report.interaction_count += 1
    if act.kind == "activate":
        return _record_activation(game, seat, act, report, game_index, turn)
    if act.kind == "graveyard":
        return _record_graveyard_activation(game, seat, act, report, game_index, turn)
    if act.kind == "hand":
        return _record_hand_activation(game, seat, act, report, game_index, turn)
    card, action, result = act.card, act.action, act.result
    when = _when_at_priority(game, act.answering, act.in_combat)
    modes_named = _modes_named(card, action)
    named = "".join(f" [mode {index}: {label}]" for index, label in modes_named)
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[seat].name} cast {card.name} "
        f"-> {result.details} [{when}]{named}{_zone_named(action)}"
    )
    if not result.supported:
        report.refused_instant_casts[f"{card.name}: {result.details}"] += 1
        return False
    report.casts_in_response += act.answering is not None
    report.casts_in_combat += act.in_combat
    report.casts_before_blocks += act.window == "declare_attackers"
    report.casts_on_opponents_turn += act.off_turn
    report.modal_casts.update(index for index, _label in modes_named)
    if action.from_zone != "hand":
        report.casts_from_zones[action.from_zone] += 1
    return True


def _when_at_priority(game: Game, answering: str | None, in_combat: bool) -> str:
    """The bracket a priority action's log line ends with: what it answered,
    or the step it was taken in."""
    if answering is not None:
        return f"in response to {answering}"
    if in_combat:
        return f"in the {game.current_step.replace('_', ' ')} step"
    return "in the end step"


def _record_activation(
    game: Game, seat: int, act: PriorityAct, report: SimulationReport,
    game_index: int, turn: int,
) -> bool:
    """Record an ability `act_at_priority` activated at instant speed: True
    when it went on the stack."""
    action, result = act.action, act.result
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[seat].name} "
        f"activate {action.permanent_name} -> {result.details} "
        f"[{_when_at_priority(game, act.answering, act.in_combat)}]"
    )
    if not result.supported:
        report.refused_instant_activations[
            f"{action.permanent_name}: {result.details}"
        ] += 1
        return False
    report.activations_at_instant_speed[act.window] += 1
    return True


def _record_hand_activation(
    game: Game, seat: int, act: PriorityAct, report: SimulationReport,
    game_index: int, turn: int,
) -> bool:
    """Record an ability of a card in *seat*'s hand `act_at_priority`
    activated: True when it went on the stack."""
    action, result = act.action, act.result
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[seat].name} "
        f"activate {action.card_name} from hand -> {result.details} "
        f"[{_when_at_priority(game, act.answering, act.in_combat)}]"
    )
    if not result.supported:
        report.refused_instant_activations[
            f"{action.card_name} (from hand): {result.details}"
        ] += 1
        return False
    report.activations_at_instant_speed[act.window] += 1
    report.activations_from_hand_at_instant_speed[action.card_name] += 1
    return True


def _when_at_upkeep(game: Game, answering: str | None, in_combat: bool) -> str:
    """`_when_at_priority`'s bracket, with the seat's own upkeep named."""
    if answering is None and not in_combat and game.current_step == "upkeep":
        return "in the upkeep"
    return _when_at_priority(game, answering, in_combat)


def _record_graveyard_activation(
    game: Game, seat: int, act: PriorityAct, report: SimulationReport,
    game_index: int, turn: int,
) -> bool:
    """Record an ability of a card in *seat*'s graveyard `act_at_priority`
    activated: True when it went on the stack."""
    action, result = act.action, act.result
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[seat].name} "
        f"activate {action.card_name} from graveyard -> {result.details} "
        f"[{_when_at_upkeep(game, act.answering, act.in_combat)}]"
    )
    if not result.supported:
        report.refused_instant_activations[
            f"{action.card_name} (from graveyard): {result.details}"
        ] += 1
        return False
    report.activations_at_instant_speed[act.window] += 1
    report.activations_from_graveyard[action.card_name] += 1
    return True


def run_ai_simulation(
    cards_path: Path | Sequence[Path],
    games: int = 10,
    seed: int = 1337,
    max_turns: int = 18,
    required_cards: Sequence[str] = (),
) -> SimulationReport:
    """Play *games* AI-vs-AI games out of whichever pool *cards_path* names.

    Each seat gets its own random limited deck from that pool, so the set under
    test is the set being played. *required_cards* pins names into both decks —
    for a regression test whose subject has to reach the battlefield to be
    regressed.
    """
    cards = {card.name: card for card in load_cards(cards_path)}
    report = SimulationReport(games_requested=games, games_completed=0, interaction_count=0)
    rng = random.Random(seed)
    # The engine's coin flips, opening-hand shuffles, and random effects use the
    # module-level RNG. Seed it so the simulation is fully reproducible — the
    # deck-construction rng above only covers deck ordering.
    random.seed(seed)
    # What this run adds to the process's record of rehearsals that raised
    # (`SimulationReport.rehearsals_raised`): read as a difference, since the
    # record is the process's and a test before this one may have written it.
    raised_seen = Counter(ai_rehearsal.REHEARSALS_RAISED)

    for game_index in range(1, games + 1):
        # Each seat's sideboard is the rest of its card pool (CR 100.4b; see
        # `limited_sideboard` for what the pool is). Until JUD's wave 2 no
        # seat had one, so a Wish ("…a card you own from outside the game",
        # CR 400.11b) and Ring of Ma'rûf had nothing to bring in, the
        # rehearsal read their casts as moving nothing, and no simulated game
        # ever cast one. Dealt without touching the run's RNG, so every deck
        # is the one it was.
        deck_a = build_limited_deck(
            cards, rng.randint(1, 1_000_000), required=required_cards
        )
        p1 = PlayerState(
            name=f"AI-A-{game_index}", library=deck_a,
            sideboard=limited_sideboard(cards, deck_a),
        )
        deck_b = build_limited_deck(
            cards, rng.randint(1, 1_000_000), required=required_cards
        )
        p2 = PlayerState(
            name=f"AI-B-{game_index}", library=deck_b,
            sideboard=limited_sideboard(cards, deck_b),
        )
        sideboard_sizes = [len(p1.sideboard), len(p2.sideboard)]
        # CR 601.2f-h and 602.2b: a spell or an ability is paid for. This read
        # `Game(players=[p1, p2])`, and `enforce_mana_costs` defaults to False,
        # so in every simulated game this project ever ran nothing cost
        # anything: a seat cast a six-drop on its first turn with no land, and
        # the land drop was the turn's one action rather than the thing that
        # pays for the rest (W2G3's census: 32 of LEA's 82 nonland casts, 62
        # of M21's 78 and 75 of TMP's 94 cost more than the caster's lands).
        # The fifth omission of the "it plays a whole turn" class, and the
        # same shape: the run completed, the interaction count was non-zero
        # and the issue list was empty. The web app's games have always
        # enforced costs (`web/session_store.py`); now these do too, and the
        # AI pays through the same seam its web seat does — the policy plans
        # the taps, `tap_planned_lands` fills the pool, the cast spends it.
        #
        # `prompt_driver` is the sixth, and the reason is in
        # `SimulationReport.steps_left_owing`: the engine asks for this table's
        # answers where it is owed them, instead of this loop draining the
        # queue wherever it happens to stand.
        game = _SimulatedGame(
            players=[p1, p2], enforce_mana_costs=True,
            prompt_driver=_resolve_pending_choices,
        )
        # `priority_driver` is the eighth: priority given where the engine
        # gives it (CR 117.3-117.4) — before each object resolves and as each
        # step's window closes — and answered by the chooser the web AI seat
        # answers with. Until it existed the window was "both players pass",
        # so no instant had ever been cast in a simulated game anywhere but its
        # caster's own main phase. See `SimulationReport.casts_in_response`.
        clock = [1]
        game.priority_driver = _priority_answerer(game, report, game_index, clock)
        starting_player = game.select_starting_player()
        game.deal_opening_hands(starting_player)
        report.mulligans_taken += take_opening_mulligans(game, starting_player)

        initial_cards = _zone_counter(game)
        log_cursor = 0
        report.log_lines.append(f"=== Game {game_index} ===")

        # `game.turn` starts at 1 and `start_next_turn` increments it before
        # each turn, so it is reset to 0 for the first increment to land on 1.
        game.turn = 0
        # **The starting player takes the first turn** (CR 103.8): the seat
        # that won the flip, whose choice — the AI's, to play first — is the
        # one `select_starting_player` logs (CR 103.1). Until the kg3 round
        # seat 0 always took it: the flip set the deal and the mulligan
        # declarations (CR 103.5) and then the log's "chooses to go first"
        # was untrue in every game the flip went to seat 1. The engine works
        # out whose turn is next from whose turn it was (CR 500.7 keeps the
        # rotation's place across extra turns), so the seat "before" the
        # starting player is recorded as the one whose turn it was.
        game.active_player_index = (starting_player - 1) % len(game.players)

        # *max_turns* is rounds, as it always was: two turns each. An extra
        # turn is one of them, so a game with Time Walk in it still ends.
        for half_turn in range(2 * max_turns):
            turn = half_turn // 2 + 1
            clock[0] = turn
            # **Whose turn comes next is `Game.start_next_turn`'s answer.**
            # This read ``for active in (0, 1)``, the last piece of the turn
            # structure the loop still decided for itself, and so no simulated
            # game had ever taken an extra turn or skipped one: Time Walk put
            # its turn on `extra_turn_queue` and the loop walked past it. Nine
            # shipped cards add or skip a turn.
            #
            # It is also the beginning phase and the entry into the main
            # phase — `Game.start_turn`, the engine's own walk, called rather
            # than copied. See the notes below.
            active = game.start_next_turn()
            report.extra_turns_taken += bool(game.current_turn_is_extra)
            active_player = game.players[active]
            opponent = game.players[1 - active]

            # This loop open-coded all of that, and each piece left out was
            # invisible in the same way: the run completes, the interaction
            # count is non-zero and the issue list is empty.
            #
            # * `begin_turn_bookkeeping` was missing first, which froze
            #   every per-seat-turn record in every AI game:
            #   `seat_turn_counts` is written in exactly one place, so
            #   Wiitigo's "since your last upkeep" read False forever,
            #   Giant Turtle, Goblin Rock Sled and Tangle Kelp never saw
            #   "attacked during your last turn", and Wall of Dust and
            #   Oracle en-Vec never saw "during its controller's next
            #   turn". Found by W1G2 while building echo.
            # * Then the main-phase *entry* (CR 505): the loop went
            #   draw -> cast, so no `main_phase_first` /
            #   `main_phase_each_yours` trigger had ever fired in an AI
            #   game — Sanctum of Fruitful Harvest, Eladamri's Vineyard,
            #   Carpet of Flowers.
            # * And the sixth of the class is not a missing call at all:
            #   upkeep then draw, with the *answer* to what the upkeep
            #   asked taken after both. See
            #   `SimulationReport.steps_left_owing`; the fix is the
            #   `prompt_driver` this game was built with, so each of these
            #   steps answers its own prompts inside its own priority
            #   window, in the engine's order rather than this loop's.
            #
            # What follows the beginning phase is the turn plan's answer
            # (`enter_next_turn_phase`, inside `start_turn`), not a phase
            # named here.
            #
            # The drain is the half `_close_or_defer_step` does for every
            # other step and `_enter_main_phase` does not, because a main
            # phase is not closed before the active player acts in it: the
            # entry opens a priority window, and the triggers it announced
            # have to resolve before the cast below sees the board.
            game._resolve_priority_window()
            _resolve_pending_choices(game)

            # The main phase's passes, in the order a player takes them:
            # the land drop, then casts paid for out of the lands, then
            # the activations, each planned against what is still
            # untapped. See `_play_land_drops` and `_play_casts`.
            #
            # **Only in a main phase the turn has.** "The player skips each
            # instance of the chosen step or phase this turn" (Fatespinner's
            # "main phase") leaves the beginning phase straight into combat
            # (CR 500.11), and a seat playing its lands and sorceries there
            # would be taking a main phase the card took away.
            in_main = game.current_turn_phase == "precombat_main"
            if in_main:
                _play_land_drops(game, active, report, game_index, turn)
                _play_casts(game, active, report, game_index, turn)
            lent = _casts_on_loan(game, active)
            if in_main:
                _play_activations(game, active, report, game_index, turn)
            # An activation can **lend** the seat a card: "{3}, {T}: Exile the
            # top card of your library. Until the beginning of your next
            # upkeep, you may play that card." (Elkin Bottle; Aerial Caravan,
            # Temporal Aperture, Bösium Strip, Grinning Totem.) The casts were
            # asked before the activations, so the card it bought was never
            # played — and the permission ends before this seat's next main
            # phase. Asked again, and only when an activation opened a cast
            # from outside the hand that was not there before it — a card
            # lent, or a flashback card a looter's discard just put in the
            # graveyard — so a turn in which none did is the turn it always
            # was.
            if in_main and not game.is_game_over() and _casts_on_loan(game, active) - lent:
                _play_land_drops(game, active, report, game_index, turn)
                _play_casts(game, active, report, game_index, turn)

            # CR 506-511, the half of a turn this loop did not have. It went
            # main phase -> cast -> activate -> next seat, so no simulated
            # game had ever declared an attacker, declared a block or run a
            # combat damage step — which is why `refused_attacks` below could
            # not have been measured before, and why "run the sim" was never
            # an end-to-end check for combat work however green it came back.
            #
            # The same shape as the two omissions above it and found the same
            # way: the run completes, the interaction count is non-zero and
            # the issue list is empty, so nothing fails. What is absent is
            # every creature that ever attacked, and the only proof is to
            # count the log lines that are not there.
            #
            # Driven through `engine/ai_combat.py`, which the web layer's AI
            # attack declaration also goes through — a refused declaration is
            # silent, and a second copy of that fallback chain would be a
            # second place for the silence to live.
            if not game.is_game_over():
                # CR 116.2d: an offer that buys a creature its attack this
                # turn is taken, if at all, before the attack is declared.
                _play_special_actions(game, active, report, game_index, turn)
            # The turn's own combat, from its main phase or — with that main
            # phase skipped — from inside the combat phase the beginning
            # phase handed over to. A turn already past combat (both skipped)
            # has none to fight; what is left is `_play_rest_of_turn`'s.
            if not game.is_game_over() and game.current_turn_phase in (
                "precombat_main", "combat",
            ):
                _play_combat_phase(game, active, report, game_index, turn)

            # CR 512-514, the half of a turn this loop still did not have
            # after combat arrived: the postcombat main phase, anything
            # CR 500.8 added, and the ending phase. See `_play_rest_of_turn`.
            if not game.is_game_over():
                _play_rest_of_turn(game, active, report, game_index, turn)

            new_logs = game.log[log_cursor:]
            report.log_lines.extend(f"  {line}" for line in new_logs)
            log_cursor = len(game.log)

            # A rehearsal that raised this turn: an engine exception the real
            # cast would have crashed on, caught in the copy. Each distinct
            # one is an issue, in the turn it first happened.
            raised = ai_rehearsal.REHEARSALS_RAISED - raised_seen
            if raised:
                for what in sorted(raised):
                    if what not in report.rehearsals_raised:
                        report.issues.append(InteractionIssue(
                            game_index, turn,
                            "A rehearsal raised (a crash the game was spared, "
                            f"and a cast nobody weighed): {what}",
                        ))
                report.rehearsals_raised.update(raised)
                raised_seen = Counter(ai_rehearsal.REHEARSALS_RAISED)

            current = _zone_counter(game)
            if current != initial_cards:
                lost = initial_cards - current
                gained = current - initial_cards
                report.issues.append(
                    InteractionIssue(
                        game_index, turn,
                        "Zone conservation failed: "
                        f"missing {dict(lost) or '{}'}, extra {dict(gained) or '{}'}",
                    )
                )
                # Re-baseline, or one leak reports itself on every later
                # turn of the game and buries whatever comes next.
                initial_cards = current

            if active_player.lost or opponent.lost or any(
                # A seat at 0 life ends the game unless a printed ban keeps
                # it playing (Platinum Angel, ``engine/game_result_bans.py``):
                # the engine plays on, so the simulation does too.
                player.life <= 0 and not player_cant_lose(game, seat)
                for seat, player in ((active, active_player), (1 - active, opponent))
            ):
                break

        report.cards_from_outside_game += sum(
            before - len(player.sideboard)
            for before, player in zip(sideboard_sizes, game.players)
        )
        owing = Counter(game._steps_left_owing)
        report.step_changes += owing.pop("_examined", 0)
        report.steps_left_owing.update(owing)
        report.games_completed += 1
        report.log_lines.append(
            f"RESULT G{game_index}: {game.players[0].name}={game.players[0].life}, {game.players[1].name}={game.players[1].life}"
        )
        report.log_lines.append("")

    return report