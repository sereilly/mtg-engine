from __future__ import annotations

from ..game_over_guard import goes_no_further

"""Upkeep step (CR 503).

"At the beginning of upkeep" triggered abilities are put on the stack here, plus
the pay-or-consequence upkeep triggers that may require an interactive choice,
enchant-land upkeep effects, and graveyard-recursion upkeep triggers.

The pay-or-consequence effects themselves live in upkeep_effects.py, registered
by (trigger condition, instruction kind); this module scans the battlefield and
dispatches. A new upkeep card is an entry there, never a branch here.

What a seat is asked before the step resolves, and how its answers are
addressed and read back, is upkeep_prompts.py's; what paying an upkeep cost
takes is upkeep_payment.py's. Both were split out of this module at the
pre-Fifth-Dawn split round and are composed onto ``Game`` right after it.
"""

import re

from ..auras import aura_enchants
from ..delayed_triggers import fire_delayed_triggers
from ..exiled_records import (EXILE_RECORD_KEY, functions_in_exile,
                              live_records)
from ..keywords import (clear_granted_ability_lines,
                        clear_granted_keywords,
                        clear_removed_ability_keywords,
                        clear_removed_ability_lines,
                        clear_all_abilities_removals)
from ..copies import RECOPY_EACH_UPKEEP, grants_ability
from ..land_types import MIRE_COUNTER, end_land_type_change
from ..type_changes import end_type_changes
from ..models import Permanent
from ..entry_awaiting import entry_happened
from ..permanent_cards import stays_out_of_battlefield
from ..cast_permissions import expire_at_upkeep as expire_upkeep_permissions
from ..phasing_locks import expire_phase_out_locks
from ..pt import BASE_PT_UPKEEP_START_REVERT_KEY, clear_base_pt
from ..replacements.damage_substitutions import DAMAGE_TO_COUNTER_REMOVAL_RECORD
from ..oracle import OracleInstruction, compile_card_oracle
from ..trigger_utils import battlefield_triggers, matching_triggers
from ..turn_state import record_controllers_upkeep
from ..effect_labels import triggered_label
from ..handlers import EFFECT_HANDLERS
from .upkeep_effects import (UPKEEP_EFFECTS, UpkeepContext, UpkeepEffectsMixin,
                             upkeep_answer)
from .upkeep_prompts import upkeep_subject_answer

#: Upkeep conditions whose seat this loop can name: "at the beginning of
#: **your** upkeep" is the source's controller, "at the beginning of **each
#: player's** upkeep" is the player whose upkeep it is, "at the beginning of
#: **the chosen player's** upkeep" is the seat the permanent recorded when the
#: effect that named them resolved (`chosen_player_index`), and "at the
#: beginning of the upkeep of **enchanted <noun>'s** controller" is whoever
#: controls the permanent the source is attached to.
#:
#: `upkeep_chosen` was in that second group until Takklemaggot's returning
#: enchantment granted itself "At the beginning of that player's upkeep, this
#: enchantment deals 1 damage to that player" — an ordinary trigger with an
#: ordinary handler behind it, which the registry had no pair for and this loop
#: refused to name a seat for, so it fired nowhere at all.
#:
#: `upkeep_enchanted_controller` joined it for the same reason. Its seat is not
#: one this loop lacks — it is on the attachment, which the registry's three
#: handlers each re-read at their own first line — and while it was excluded,
#: every Aura printing this condition needed a registry pair whether or not
#: anything about it was interactive. Erosion and Curse Artifact are the
#: ordinary shape: an offer with a penalty, which the grammar reads as a `may`
#: and the generic pending-choice queue already runs.
_ORDINARY_UPKEEP_SEATS = frozenset({
    "upkeep_self", "upkeep_each", "upkeep_chosen", "upkeep_enchanted_controller",
})


def upkeep_trigger_seat_matches(game, permanent, cond: str, player_index: int) -> bool:
    """Whether a trigger of *cond* on *permanent* fires on *player_index*'s upkeep.

    Only the two conditions that name a seat *other than* the ordinary ones
    answer anything here; the rest already fired on the right upkeep by the
    time this is asked. One reader for the loop below and for the support gate
    in ``engine/auras.py``, so what the engine claims it can fire and what it
    actually fires cannot drift.
    """
    if cond == "upkeep_chosen":
        return permanent.metadata.get("chosen_player_index") == player_index
    if cond == "upkeep_enchanted_controller":
        attached = permanent.metadata.get("attached_to")
        return (
            attached is not None
            and game.controller_index_of(attached) == player_index
        )
    return True


class UpkeepStepMixin(UpkeepEffectsMixin):
    def _process_mire_cleanups(self, player_index: int) -> None:
        """Drain Cyclopean Tomb's rest-of-game mire-removal obligations.

        For each obligation belonging to this player, remove all mire counters
        from one still-mired land at the beginning of their upkeep (the trigger
        acts on a single land per upkeep). A land whose counter has already gone —
        because the land left the battlefield or was freed by a prior upkeep — is
        no longer eligible. An obligation with no eligible lands left is dropped
        (it would do nothing on future upkeeps).
        """
        if not self.mire_cleanup_obligations:
            return

        def _on_battlefield(land) -> bool:
            return self.is_on_battlefield(land)

        surviving: list = []
        for obligation in self.mire_cleanup_obligations:
            if obligation.get("controller_index") != player_index:
                surviving.append(obligation)
                continue
            lands = [
                land
                for land in obligation.get("lands", [])
                if land.metadata.get("mire_counter") and _on_battlefield(land)
            ]
            if lands:
                freed = lands.pop(0)
                freed.metadata.pop("mire_counter", None)
                # The counter is what the type change hung on, so removing it
                # drops that one contribution — not every land-type effect on
                # the land, which is what clearing the stored type did.
                end_land_type_change(freed, source=MIRE_COUNTER)
                self.log.append(f"Mire counter removed from {freed.card.name}")
            if lands:
                obligation["lands"] = lands
                surviving.append(obligation)
        self.mire_cleanup_obligations = surviving

    def _force_sacrifice_first_land(self, controller, source, chosen: Permanent | None = None) -> Permanent | None:
        """Sacrifice a land on *controller*'s battlefield to *source*'s upkeep
        effect, logging it. Returns the sacrificed land, or None if the player
        controls no land.

        One caller left — the pay-or-tap-and-sacrifice upkeep (Demonic
        Hordes), handing it the land an opponent chose
        (``UpkeepEffectsMixin._sacrifice_a_land_an_opponent_chooses``).
        Serendib Djinn used to be the other, and is now an ordinary stack
        trigger whose sacrifice goes through the standing forced-sacrifice
        prompt like every other one.

        ``chosen`` is the land picked for it. Without one the first land is
        taken, the deterministic forced-sacrifice fallback."""
        for idx, land in enumerate(controller.battlefield):
            if not land.has_type("land"):
                continue
            if chosen is not None and land is not chosen:
                continue
            removed = self.sacrifice_permanent(land)
            if removed is None:
                continue
            self.log.append(f"{source.card.name} forced sacrifice of {removed.card.name}")
            return removed
        # A stale pick (the land left the battlefield since the prompt) still
        # has to sacrifice something — fall back to the first land.
        return self._force_sacrifice_first_land(controller, source) if chosen is not None else None

    @goes_no_further()
    def resolve_upkeep(self, player_index: int, human_choices: dict[int | str, bool] | None = None, optional_choices: dict[int | str, bool] | None = None, defer_priority: bool = False, mana_prevention: dict[int | str, int] | None = None, sacrifice_choices: dict[int | str, int] | None = None, trigger_targets: dict[int | str, int] | None = None) -> None:
        """Run this seat's upkeep step, carrying out the prompt answers in hand.

        Every answer map is keyed by ``Permanent.permanent_id``; a string key is
        the legacy shorthand for "every copy of this card"
        (:meth:`_upkeep_answers_by_permanent`). *trigger_targets*' **values**
        are ids too — the ``id`` of the ``valid_targets`` entry chosen
        (:meth:`_upkeep_target_pick`).

        The step's turn-based half is one window for CR 603.3b
        (``putting_triggers_on_stack``): everything "at the beginning of the
        upkeep" sets off — the battlefield's triggers, CR 603.7's delayed ones,
        an Aura's — goes on the stack together and its controller orders it
        (Tangle Wire's fade removal against its tap). Closed before the
        priority window, which is what would resolve them.
        """
        with self.putting_triggers_on_stack():
            self._resolve_upkeep_actions(
                player_index, human_choices, optional_choices,
                mana_prevention, sacrifice_choices, trigger_targets,
            )
        self._close_or_defer_step("beginning", "upkeep", defer_priority)

    def _resolve_upkeep_actions(self, player_index: int, human_choices: dict[int | str, bool] | None = None, optional_choices: dict[int | str, bool] | None = None, mana_prevention: dict[int | str, int] | None = None, sacrifice_choices: dict[int | str, int] | None = None, trigger_targets: dict[int | str, int] | None = None) -> None:
        """The upkeep step up to its priority window (:meth:`resolve_upkeep`)."""
        # Every prompt answer, re-keyed to the permanent it is about, before
        # anything reads one. See :meth:`_upkeep_answers_by_permanent` — this is
        # the one place a printed card name is turned into an address, so no
        # handler below can be written against a name again.
        human_choices = self._upkeep_answers_by_permanent(human_choices)
        optional_choices = self._upkeep_answers_by_permanent(optional_choices)
        mana_prevention = self._upkeep_answers_by_permanent(mana_prevention)
        sacrifice_choices = self._upkeep_answers_by_permanent(sacrifice_choices)
        trigger_targets = self._upkeep_answers_by_permanent(trigger_targets)
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        # Imported here rather than at module scope for the reason the two
        # copies further down state: ``handlers.control_flow`` dispatches back
        # through ``EFFECT_HANDLERS``, so a module-level import closes a cycle.
        from ..game_types import OracleExecutionContext
        from ..handlers.control_flow import evaluate_condition

        # CR 702.30a's "since the beginning of your last upkeep", written from
        # the far end: stamp this upkeep as the first of *this seat's* that each
        # permanent they control has seen, for the ones that have not seen one
        # already (``engine/turn_state.py`` says why the record is shaped this
        # way rather than as a moment-of-arrival stamp against a clock).
        #
        # **At the top of the step, before anything is collected or resolved.**
        # CR 603.4 checks an intervening-if twice — once to decide whether the
        # ability triggers and again as it resolves — and the offer that quotes
        # its cost is collected before either. All three have to read one
        # unchanging answer, which they do because this write happens before all
        # of them and never repeats while the controller stays the same.
        #
        # Over the permanents this seat controls *now*, so one that enters later
        # in this same step is correctly still owed its first upkeep.
        record_controllers_upkeep(
            self, list(self.controlled_by(player_index)), player_index
        )
        self._process_mire_cleanups(player_index)
        # Layer 6: a keyword or a quoted ability granted "until your next
        # upkeep" (Erhnam Djinn, Gabriel Angelfire) expires now, at the start
        # of that same upkeep, before this turn's own upkeep triggers — which
        # may grant a fresh one — run.
        #
        # This was two metadata keys written by a card-keyed hook, because the
        # keyword channel recorded its duration as a boolean and had no room
        # for a third answer. The hook is gone; both grant channels take the
        # sweep's name, so a card printing this duration over any keyword or
        # any quoted line ends here without an edit.
        # The same printed duration over a *permission* rather than a
        # characteristic (Elkin Bottle), swept at the same moment and for the
        # same reason: it ends as the upkeep begins, before this turn's own
        # triggers get a chance to grant a fresh one.
        expire_upkeep_permissions(self, player_index)
        for perm in self.all_permanents():
            clear_granted_keywords(perm, "your_next_upkeep", seat=player_index)
            clear_granted_ability_lines(perm, "your_next_upkeep", seat=player_index)
            clear_removed_ability_keywords(
                perm, "your_next_upkeep", seat=player_index
            )
            clear_removed_ability_lines(
                perm, "your_next_upkeep", seat=player_index
            )
            clear_all_abilities_removals(
                perm, "your_next_upkeep", seat=player_index
            )
            # "**Until your next upkeep**, target permanent can't phase out."
            # (Spatial Binding.) The same moment and the same seat rule as the
            # two grant sweeps above — and *before* CR 702.26a's phasing event,
            # which the untap step ran one step earlier this turn, so the lock
            # covers the whole window the card names and no more.
            expire_phase_out_locks(perm, "your_next_upkeep", seat=player_index)
            # "For each 1 damage that would be dealt to you **until your next
            # upkeep**, you remove an echo counter from this enchantment
            # instead." (Soul Echo.) The same moment and the same seat rule as
            # the sweeps above, and the same reason it is here rather than at
            # the end of the previous turn: this turn's own upkeep trigger
            # offers a fresh one, and a record left standing would make the
            # offer meaningless.
            # "…has base power and toughness 0/1 **until your next upkeep**."
            # (Cycle of Life.) The same moment and the same seat rule as the
            # sweeps above, and Halfdane's stamp one step earlier: that one ends
            # as this seat's upkeep *ends* and is cleared by the draw step,
            # this one ends as it *begins*. A stamp written during this very
            # upkeep survives to the next one, which is what keeps an ability
            # activated in your own upkeep from expiring in the same breath.
            stamp = perm.metadata.get(BASE_PT_UPKEEP_START_REVERT_KEY)
            if (
                isinstance(stamp, dict)
                and stamp.get("seat") == player_index
                and int(stamp.get("turn", 0)) < self.turn
            ):
                clear_base_pt(perm)
            record = perm.metadata.get(DAMAGE_TO_COUNTER_REMOVAL_RECORD)
            if isinstance(record, dict) and record.get("seat") == player_index:
                perm.metadata.pop(DAMAGE_TO_COUNTER_REMOVAL_RECORD, None)
            # "Until **your** next upkeep, target noncreature artifact becomes
            # an artifact creature…" (Xenic Poltergeist) — the same moment and
            # the same reasoning as the sweep above: it expires at the
            # start of that upkeep, before this turn's own triggers get a
            # chance to grant a fresh one. Whose upkeep is the seat recorded
            # when the ability resolved, because CR 109.5 makes it the
            # controller of the ability rather than of the affected permanent.
            end_type_changes(
                perm,
                lambda record: (
                    record.get("duration") == "until_your_next_upkeep"
                    and record.get("seat") == player_index
                ),
            )
        # Non-interactive "at the beginning of upkeep" triggers (fixed upkeep damage)
        # are collected here and put on the stack (CR 603.3); they resolve through the
        # upkeep priority window. The pay-or-consequence triggers below stay inline
        # because their interactive prompt protocol (human_choices / mana_prevention /
        # sacrifice_choices) is driven directly by the web layer.
        upkeep_events: list[dict] = []

        def _enqueue_upkeep_damage(perm, controller_idx, victim_idx, amount, source_line=None):
            upkeep_events.append({
                "controller_index": controller_idx,
                "source_permanent": perm,
                "instruction": OracleInstruction("deal_damage_to_player", None, {}),
                "effect_kind": "triggered_damage",
                "ability_text": source_line,
                "trigger_context": {"victim_player_index": victim_idx, "amount": int(amount)},
            })

        for controller_seat, permanent in self.permanents_with_controller():
            controller = self.players[controller_seat]
            program = compile_card_oracle(permanent.effective_card)
            # CR 113.6m: "return this card from your graveyard" (Squee,
            # Goblin Nabob, Ghastly Remains) is the graveyard scan's below,
            # never this one's.
            for trig in battlefield_triggers(program.triggered_abilities):
                if trig.instruction is None:
                    continue
                kind = trig.instruction.kind
                cond = trig.condition.kind

                # "at the beginning of YOUR upkeep" only fires during the
                # controller's own upkeep.
                #
                # `continue`, not `break` — CR 603.3, the same reading the
                # ordinary branch below already states and this line still
                # contradicted. A permanent printing "your upkeep" *before*
                # "each player's upkeep" lost the second ability on every
                # upkeep but its controller's: Cold Snap's cumulative upkeep is
                # its first line, so on an opponent's turn the loop stopped
                # there and the enchantment dealt nobody any damage.
                if cond == "upkeep_self" and controller_seat != player_index:
                    continue

                # "at the beginning of each **opponent's** upkeep" (Psychic
                # Allergy) is `upkeep_each` narrowed by a printed noun, carried
                # as the condition's `upkeep_scope` payload rather than as a
                # kind of its own (idiom 19). Whose opponents is CR 109.5's
                # answer — the *source's* controller — so the card's own upkeep
                # is not one of them. `continue`, not `break`: another ability
                # on the same permanent may still have triggered (CR 603.3).
                if (
                    cond == "upkeep_each"
                    and trig.condition.payload.get("upkeep_scope") == "opponent"
                    and controller_seat == player_index
                ):
                    continue

                # CR 603.4: a gated trigger whose condition is false **does
                # not trigger**. This step had no such check anywhere — only the
                # resolution re-check downstream — so Misers' Cage went on the
                # stack on every opponent's upkeep and was talked out of it on
                # the way down. That is not the same ability: one that never
                # triggered holds no priority, cannot be countered, and nothing
                # in response sees it. The end step has made this check since
                # round 45 and says so in the same words; this is the upkeep's.
                #
                # Above the registry lookup, not inside either branch: whether
                # an ability triggered is prior to how it is carried out, and
                # the pay-or-consequence handlers below reach the player
                # directly without ever building a stack object to re-check.
                #
                # The context carries the seat *this* firing is about, which is
                # what lets "if **that player** has five or more cards in hand"
                # be asked before the event exists.
                gate = (trig.instruction.payload or {}).get("intervening_if")
                if gate is not None and not evaluate_condition(
                    self,
                    OracleExecutionContext(
                        caster=self.players[controller_seat],
                        target=self.players[player_index],
                        card=permanent.card,
                        source_permanent=permanent,
                        trigger_context={"event_subject_player": player_index},
                    ),
                    gate,
                ):
                    continue

                handler = UPKEEP_EFFECTS.get((cond, kind))
                # An amount defined by a where-clause is counted at
                # **resolution** (CR 608.2), and the registry's handlers read
                # their amount straight off the payload — they know a printed
                # number and Storm World's turn-start land count, and nothing
                # else. Psychic Allergy's "X is the number of nontoken
                # permanents of the chosen color they control" is a third
                # spelling they would silently read as Storm World's. So the
                # pair is declined and the trigger goes on the stack like any
                # other, where `count_from_payload` answers it.
                if handler is not None and "x_from_count" in trig.instruction.payload:
                    handler = None
                # The two fixed-damage rows read a number and deal it to the
                # player whose upkeep it is, and nothing else. A printed
                # **target** is something else: "…deals 1 damage to target
                # opponent or planeswalker" (Scalding Tongs, Thumbscrews) and
                # "…deals 3 damage to target creature you control" (Spiteful
                # Bully) all dealt their damage to their own controller's face.
                # So is an **intervening "if"**: the row queues a damage event
                # of its own with no condition on it, so CR 603.4's second
                # check — as the ability resolves — was never made (Misers'
                # Cage, Kezzerdrix, Mask of Intolerance: answer the trigger by
                # making its condition false and the damage came anyway).
                # Either one is declined exactly as the where-clause above is,
                # and the trigger goes on the stack as itself, where the
                # target is chosen (CR 603.3d) and the gate re-asked.
                if (
                    handler is not None
                    and kind == "deal_damage"
                    and cond in ("upkeep_self", "upkeep_each")
                    and (
                        "targets" in trig.instruction.payload
                        or "intervening_if" in trig.instruction.payload
                    )
                ):
                    handler = None
                if handler is None and cond in _ORDINARY_UPKEEP_SEATS:
                    # An upkeep trigger with nothing interactive about it —
                    # "At the beginning of your upkeep, you may search your
                    # library …" (Sanctum of All). CR 603.3: it goes on the
                    # stack and resolves through EFFECT_HANDLERS like any other
                    # trigger, which is what makes it the *ordinary* case and
                    # the registry above the exception.
                    #
                    # The registry is asked first because those handlers are
                    # pay-or-consequence shapes whose prompt protocol the web
                    # layer drives inline; a pair it answers never reaches here.
                    # Only the two conditions whose seat is unambiguous are
                    # admitted: "your upkeep" is the source's controller and
                    # "each player's upkeep" is whoever's it is, where
                    # `upkeep_enchanted_controller` and `upkeep_chosen` name a
                    # seat this loop does not have in hand.
                    if not upkeep_trigger_seat_matches(
                        self, permanent, cond, player_index
                    ):
                        # The permanent names one seat — the one an effect chose
                        # for it, or the one that controls what it is attached
                        # to — and this is somebody else's upkeep. `continue`,
                        # not `break`: another ability on the same permanent may
                        # still have triggered (CR 603.3).
                        continue
                    if kind in EFFECT_HANDLERS:
                        # The target its controller picked at the prompt, if
                        # this trigger asked for one (CR 603.3d — targets are
                        # chosen as the ability is put on the stack). Without
                        # this the stack object carries none and the handler
                        # falls back to the first legal candidate, which is
                        # the answer for an AI seat and the wrong one for a
                        # player who was just asked.
                        answered, named = self._upkeep_target_pick(
                            permanent, trigger_targets
                        )
                        # …and it is an answer to CR 603.3d's choice, so it
                        # has to be one that choice would have accepted. The
                        # stamp below reads as "the event made the choice",
                        # which skips the picker — so a pick naming something
                        # the ability cannot target (a land for "target
                        # creature", a creature with shroud) reached the
                        # handler unchecked, and the handler's own fallback
                        # then acted on whichever bystander it scanned first.
                        # Set aside instead: the trigger goes on the stack
                        # with nothing announced and chooses for itself — a
                        # seat that is asked is asked again, from the legal
                        # list. So is a pick whose permanent has *gone*: the
                        # answer is an id, and an id names that permanent or
                        # nothing, never the one now in its slot.
                        picked = None
                        picked_from_its_list = False
                        if answered and named is not None:
                            legal = self._upkeep_trigger_legal_targets(
                                permanent, controller_seat, trig
                            )
                            if legal is not None and not any(
                                named is allowed for allowed in legal
                            ):
                                picked = None
                            else:
                                # The slot is read now, as the object goes on
                                # the stack, and ``_stamp_stack_targets`` turns
                                # it straight back into this id.
                                picked = (
                                    self.controller_index_of(named),
                                    self.battlefield_index_of(named),
                                )
                                # A pick the ability's own list accepted is a
                                # target chosen for it (CR 603.3d), and says so
                                # on the stack object — which is what lets CR
                                # 608.2b be asked of it as it resolves. Where
                                # the picker has no list the pick rides
                                # unjudged, here and there alike.
                                picked_from_its_list = legal is not None
                        upkeep_events.append({
                            "controller_index": controller_seat,
                            "source_permanent": permanent,
                            # "…deals 1 damage to **that player**": the seat
                            # the condition named, which for a chosen-player
                            # trigger is the one whose upkeep this is — the
                            # gate above already checked they are the same.
                            # "…deals 1 damage to **that player**" /
                            # "…unless **that player** pays {1}": the seat the
                            # condition named. For both of the conditions that
                            # name one, the gate above has already checked it is
                            # the seat whose upkeep this is.
                            # A pick is a choice (``targets_chosen``); the
                            # seat the condition named is what the event is
                            # about (``StackItem.about_player_index``).
                            "target_player_index": picked[0] if picked else None,
                            "about_player_index": (
                                player_index
                                if not picked and cond in (
                                    "upkeep_chosen", "upkeep_enchanted_controller",
                                )
                                else None
                            ),
                            "target_permanent_index": picked[1] if picked else None,
                            "targets_chosen": picked_from_its_list,
                            "instruction": trig.instruction,
                            "effect_kind": triggered_label(kind, cond),
                            "ability_text": trig.source_line or None,
                            # Whose upkeep this firing is, frozen now (CR
                            # 603.10). "At the beginning of each player's
                            # upkeep, … that player …" is one ability with a
                            # different seat each time it fires, and by the
                            # time the stack resolves it the only seat still
                            # readable off the board is the source's
                            # controller — which is the wrong one on every
                            # upkeep but their own.
                            "trigger_context": {
                                "event_subject_player": player_index,
                            },
                        })
                        # `continue`, not `break`. CR 603.3 puts **every**
                        # ability that triggered on the stack, and this loop
                        # stopped at the first one — invisible until Tetravus,
                        # the only card in the pool printing two upkeep
                        # triggers, whose second one never fired.
                        continue
                if handler is not None:
                    handler(self, UpkeepContext(
                        game=self,
                        player_index=player_index,
                        controller=controller,
                        permanent=permanent,
                        trig=trig,
                        cond=cond,
                        kind=kind,
                        human_choices=human_choices,
                        optional_choices=optional_choices,
                        mana_prevention=mana_prevention,
                        sacrifice_choices=sacrifice_choices,
                        trigger_targets=trigger_targets,
                        enqueue_damage=_enqueue_upkeep_damage,
                    ))
                    continue

        # Upkeep triggers of a card that is in **exile**. All Hallow's Eve
        # keeps working from there: "At the beginning of your upkeep, if this
        # card is exiled with a scream counter on it, remove a scream counter
        # from it."
        #
        # A parallel scan rather than a row in the loop above, because the loop
        # above iterates ``permanents_with_controller()`` and there is no
        # permanent here to iterate — a sorcery exiling itself never becomes
        # one. What the two scans share is the *event*, which is why this
        # appends to the same ``upkeep_events`` list and goes on the stack in
        # the same APNAP batch (CR 603.3b): an exiled card's trigger is an
        # ordinary triggered ability in every respect except where its source
        # is.
        #
        # The stack item carries ``card=`` and no source permanent, which
        # ``_enqueue_triggered_ability`` has always supported; the record rides
        # the trigger context, because CR 603.10 freezes what the ability needs
        # as it goes on the stack and nothing on the board could name the right
        # record afterwards. The intervening-if is *not* pre-checked here — CR
        # 603.4 checks it at both ends, the fire site and the resolution, and
        # the resolution end is already armed in ``_run_stack_item_resolution``.
        #
        # **Only a trigger that functions from exile** (CR 113.6: a
        # permanent card's abilities function on the battlefield unless they
        # say otherwise; CR 113.6k: a trigger condition that can't trigger from
        # the battlefield — "if this card is exiled" — functions where it can).
        # The register holds cards for other reasons too — a face-down exile
        # (Three Wishes, Suppress), the cards a Dimensional Breach will hand
        # back — and an ordinary "at the beginning of your upkeep, this
        # creature deals 1 damage to you" (Juzám Djinn) fired from there.
        for record in live_records(self):
            if record.controller_index != player_index:
                continue
            for trig in matching_triggers(
                record.card, condition_kinds={"upkeep_self"}, zone="exile",
            ):
                if trig.instruction.kind not in EFFECT_HANDLERS:
                    continue
                # Only an ability that says it works from exile (CR 113.6):
                # a record holds any card something will read again, and
                # Juzám Djinn's own upkeep damage is not one of them.
                if not functions_in_exile(trig):
                    continue
                upkeep_events.append({
                    "controller_index": record.controller_index,
                    "card": record.card,
                    "source_permanent": None,
                    "instruction": trig.instruction,
                    "effect_kind": triggered_label(trig.instruction.kind, "upkeep_self"),
                    "ability_text": trig.source_line or None,
                    "trigger_context": {
                        "event_subject_player": player_index,
                        EXILE_RECORD_KEY: record,
                    },
                })

        # …and of a card that is in a **graveyard** (CR 113.6b). "At the
        # beginning of your upkeep, if this card is in your graveyard with a
        # creature card directly above it, you may pay {1}." (Death Spark.)
        #
        # The exile scan's twin one zone over, and beside it rather than folded
        # into it for that scan's reason: neither zone's objects are permanents,
        # so ``permanents_with_controller()`` cannot reach them, and what the
        # three scans share is the event rather than the walk. The end step has
        # had this scan since Silversmote Ghoul; the upkeep had none at all, so
        # a graveyard-functioning upkeep trigger compiled clean and was
        # announced by nothing — the failure ``engine/events.py`` exists to
        # describe, one step over from where it was fixed.
        #
        # Scoped to this upkeep's own player, which is what "your" means for a
        # card nobody controls (CR 108.4a: the controller of a card that has none
        # is its owner). The intervening-if **is** pre-checked, as the end step's
        # graveyard scan pre-checks it and for CR 603.4's reason: the condition
        # is what says the ability functions at all, and a trigger that went on
        # the stack from a graveyard position it never had would be announced to
        # every player before being silently removed.
        # Imported here rather than at module scope, exactly as the end step's
        # copy of this scan is: ``handlers.control_flow`` dispatches back
        # through ``EFFECT_HANDLERS``, so a module-level import closes the cycle.
        from ..events import graveyard_trigger_events
        from ..game_types import OracleExecutionContext
        from ..handlers.control_flow import evaluate_condition

        for grave_event in graveyard_trigger_events(
            self, "upkeep_self", [self.players[player_index]]
        ):
            grave_gate = (grave_event["instruction"].payload or {}).get(
                "intervening_if"
            )
            if grave_gate is not None and not evaluate_condition(
                self,
                OracleExecutionContext(
                    caster=self.players[player_index],
                    target=self.players[player_index],
                    card=grave_event["card"],
                ),
                grave_gate,
            ):
                continue
            grave_event["trigger_context"] = {"event_subject_player": player_index}
            upkeep_events.append(grave_event)

        # Handle enchant-land auras with optional upkeep life gain (e.g. Farmstead)
        for permanent in self.all_permanents():
            if not permanent.has_type("enchantment"):
                continue
            prog = compile_card_oracle(permanent.effective_card)
            text = prog.normalized_text
            if not aura_enchants(permanent.effective_card.oracle_text, "land"):
                continue
            attached_land = permanent.metadata.get("attached_to")
            if attached_land is None:
                continue
            if self.controller_index_of(attached_land) != player_index:
                continue
            instr = next((i for i in prog.instructions if i.kind == "target_gains_life"), None)
            if instr is None:
                continue
            # Parse the optional mana payment from text (e.g. "you may pay {w}{w}")
            pay_match = re.search(r"you may pay ((?:\{[wubrgcWUBRGC]\})+)", text)
            gainer = self.players[player_index]
            paid = False
            if pay_match:
                cost_str = pay_match.group(1).upper()
                cost: dict[str, int] = {}
                for sym in re.findall(r"\{([WUBRG])\}", cost_str):
                    cost[sym] = cost.get(sym, 0) + 1
                can_pay = all(gainer.mana_pool.get(sym, 0) >= cnt for sym, cnt in cost.items())
                # Honor a human's decision (from the upkeep-pay prompt) when given;
                # otherwise auto-pay when able (beneficial default for AI/headless).
                # The Aura's own prompt answer, by permanent id like every
                # other one on this step (`upkeep_effects.upkeep_answer` says
                # why): two Farmsteads on two of this player's lands are two
                # offers, and a name key made them one.
                answered = upkeep_answer(human_choices, permanent)
                wants_pay = can_pay if answered is None else bool(answered)
                if wants_pay and can_pay:
                    for sym, cnt in cost.items():
                        gainer.mana_pool[sym] -= cnt
                    paid = True
            else:
                paid = True  # No payment required
            if paid:
                amount = int(instr.payload.get("amount", 1))
                self._gain_life(gainer, amount, permanent.card.name)

        # Graveyard-recursion upkeep triggers (e.g. Nether Shadow). These abilities
        # function from the owner's graveyard, so they aren't covered by the
        # battlefield loop above. A card may return itself to the battlefield if at
        # least N creature cards lie above it (i.e. were put into the graveyard more
        # recently — appended later in the list). These are optional ("you may"):
        # ``optional_choices`` maps the card name to the player's decision. When it
        # is None (AI turns, scripted/test runs) the beneficial default is taken;
        # when provided, the card returns only on an explicit yes.
        owner = self.players[player_index]
        # One answer per eligible copy, addressed by its ordinal: with two
        # Nether Shadows deep enough to return, "yes" to the first and "no" to
        # the second returns exactly one. ``optional_choices is None`` is still
        # the headless/AI signal for "nobody was asked", which takes the
        # beneficial default; a map that was given but says nothing about this
        # copy is a decline, exactly as it was.
        accepted_returns = [
            (grave_index, card)
            for grave_index, ordinal, card in self._graveyard_return_candidates(player_index)
            if (
                optional_choices is None
                or bool(upkeep_subject_answer(optional_choices, card.name, ordinal))
            )
            # CR 400.4a / 614.17, asked before the card leaves the graveyard.
            and not stays_out_of_battlefield(self, card, owner, "graveyard")
        ]
        # Remove highest index first, so popping one does not renumber the slots
        # of the ones still to come — the same ordering rule the several-card
        # graveyard return follows. Removing by identity instead would take every
        # copy of the card (see `_graveyard_return_candidates`).
        for grave_index, _card in sorted(accepted_returns, key=lambda pair: pair[0], reverse=True):
            if 0 <= grave_index < len(owner.graveyard):
                owner.graveyard.pop(grave_index)
        # Then onto the battlefield in printed graveyard order, so the log reads
        # bottom-up as it always has.
        for _grave_index, card in accepted_returns:
            returning = Permanent(card=card)

            def returned(returning=returning, card=card) -> None:
                if entry_happened(returning):
                    self.log.append(
                        f"{owner.name} returned {card.name} to the battlefield from the graveyard"
                    )

            self._put_permanent_onto_battlefield(player_index, returning, None, then=returned)

        # Vesuvan Doppelganger's upkeep re-copy: apply an accepted choice to the
        # player-chosen creature. Declined (or target-less) prompts do nothing;
        # AI/headless runs (optional_choices is None) keep the current copy.
        for perm in list(owner.battlefield):
            if not grants_ability(perm, RECOPY_EACH_UPKEEP):
                continue
            if optional_choices is None or not optional_choices.get(perm.permanent_id, False):
                continue
            # The chosen creature by id: one that has left is no answer at all,
            # never the creature that took its battlefield slot.
            _answered, candidate = self._upkeep_target_pick(perm, trigger_targets)
            source = None
            if (
                candidate is not None
                and candidate is not perm
                and self._is_creature(candidate)
            ):
                source = candidate
            if source is None:
                self.log.append(f"{perm.card.name}: no valid creature chosen to copy")
                continue
            self._apply_copy(perm, source)
            self.log.append(f"{perm.card.name} becomes a copy of {source.card.name}")
            self._refresh_dynamic_creatures()

        # "At the beginning of your next upkeep, …" (Hazezon Tamar, Giant
        # Slug). CR 603.7's delayed abilities trigger at the same moment as the
        # battlefield's own upkeep triggers, so they are announced here rather
        # than at the step's entry — and scoped to the entry's own controller,
        # which is what "your" says: an upkeep belongs to one player, so an
        # ability an opponent created is not waiting for this one.
        fire_delayed_triggers(self, "controllers_next_upkeep", seat=player_index)
        # "…at the beginning of **the next turn's** upkeep" (Ice Age's cantrip
        # cycle). Unseated: the ability names whichever upkeep comes next, not
        # one of its controller's, so an entry armed on an opponent's turn fires
        # on yours. Announced beside the seated one because both are CR 603.7
        # abilities triggering at the same moment as the battlefield's own.
        fire_delayed_triggers(self, "next_turns_upkeep")
        # "…at the beginning of **their** next upkeep" (Sabertooth Cobra).
        # Seated like the controller's row above and by a different seat: the
        # one the creating event recorded, which is what `EVENTS_SEATED_BY_
        # BOUND_PLAYER` makes `matching_delayed_triggers` compare against.
        fire_delayed_triggers(self, "damaged_players_next_upkeep", seat=player_index)
        # "…at the beginning of **each of that player's upkeeps**" (Ertai's
        # Meddling). The repeating sibling of the row above, on the same seat
        # rule and announced from the same moment; `once=False` on the entry is
        # what makes it stay on the waiting list rather than the fire site
        # knowing anything about it.
        fire_delayed_triggers(self, "bound_players_upkeep", seat=player_index)
        # "…at the beginning of **each player's upkeep**, that player …"
        # (Dimensional Breach.) Unseated — every upkeep — with the upkeep's
        # player frozen as the seat the firing is about, under the key the
        # static ``upkeep_each`` trigger freezes it by.
        fire_delayed_triggers(
            self, "each_players_upkeep",
            about_player_index=player_index,
            trigger_context={"event_subject_player": player_index},
        )

        # Put the collected non-interactive upkeep triggers on the stack in APNAP
        # order; they resolve through the upkeep priority window opened below.
        self._enqueue_triggered_batch(upkeep_events)

        # CR 704.3: state-based actions are checked before a player receives
        # priority. Several upkeep effects deal damage inline (Cyclone's wind
        # counters, the pay-or-suffer family), and this is what destroys what
        # they killed — the handlers no longer sweep for themselves. Inside the
        # step's CR 603.3b window, so what dies here triggers beside the
        # upkeep's own triggers and is ordered with them.
        self._check_after_turn_based_actions()
