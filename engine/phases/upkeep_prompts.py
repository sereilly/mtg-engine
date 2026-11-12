"""What the upkeep step asks a seat before it resolves (CR 503), and how each
answer is addressed and read back.

The prompt half of the step's protocol: the pay-or-consequence prices a
controller must decide on (``get_upkeep_pay_triggers``, gated on the
intervening-if exactly as the resolver gates it, CR 603.4), Power Leak's
pay-any-amount prevention, the optional offers (Nether Shadow's return from
the graveyard, Vesuvan Doppelganger's re-copy) and the targets a mandatory
upkeep trigger has its controller choose as it is put on the stack (CR
603.3d). A web seat is shown these and answers before
:meth:`~engine.phases.upkeep_step.UpkeepStepMixin.resolve_upkeep` runs — the
deferral the step exists to give it — and an AI or headless seat passes no
answers and takes each prompt's default.

Every answer is addressed by the permanent it is about
(``Permanent.permanent_id``, CR 400.7), and the two prompts whose subject is
not a permanent by :func:`subject_prompt_key`; :func:`upkeep_prompt_key` is the
one function the arming and the answering side of the web layer both read. The
read-back half — the name shorthand re-keyed, a target pick read by id and
held to the trigger's own legal list — lives here beside the asking half, so
what is asked and what is read back cannot drift.

Split out of ``upkeep_step.py`` at the pre-Fifth-Dawn split round, and composed
onto ``Game`` immediately after :class:`~engine.phases.upkeep_step.UpkeepStepMixin`.
"""

from __future__ import annotations

import re

from ..auras import aura_enchants
from ..copies import RECOPY_EACH_UPKEEP, grants_ability
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..trigger_utils import (battlefield_triggers, iter_triggered_abilities,
                             matching_triggers)
from ..mixins._constants import _UPKEEP_PAY_KINDS
from ..cumulative_upkeep import upcoming_cost
from ..upkeep_costs import (UpkeepCost, cost_from_payload, cost_prompt_fields,
                            resolved_toll_instruction)

#: What separates a printed name from the ordinal that says *which* same-named
#: subject a prompt is about. A character no card name contains, so
#: ``"Nether Shadow#1"`` can never collide with a card called that.
SUBJECT_ORDINAL_SEPARATOR = "#"


def subject_prompt_key(card_name: str, ordinal: int) -> str:
    """The address of the *ordinal*-th subject printed *card_name*.

    The graveyard's and the obligation list's answer to ``permanent_id``, and
    it has to be a different answer for the same reason
    :class:`engine.game_types.GraveyardTarget` does: ``load_cards`` dedupes by
    ``oracle_id``, so two Nether Shadows in one graveyard are literally one
    ``CardDefinition`` object and neither an id nor ``is`` can tell them apart.
    What can is *order* — and ``ordinal`` here is exactly
    ``GraveyardTarget.ordinal``, which copy of the card counting from the
    bottom of the pile, read off the one function that computes it
    (``Game.graveyard_target_at``). A Nafs Asp obligation is the same shape one
    list over: its records are equal dicts, so which one a prompt is about is
    its position among that player's obligations from that source.

    A **string** rather than the pair, because this key is a dict key in
    ``session.upkeep_resolved_choices`` and that dict is serialized to the
    client — JSON has no tuple keys. The separator is the whole of the
    encoding, spelled once here and mirrored by ``upkeepPromptKey`` in
    ``web/static/app.js``.
    """
    return f"{card_name}{SUBJECT_ORDINAL_SEPARATOR}{ordinal}"


def upkeep_prompt_key(entry: dict):
    """The key *entry*'s answer belongs under in the map handed to
    :meth:`UpkeepStepMixin.resolve_upkeep`.

    ``permanent_id`` for a prompt whose subject is on the battlefield, which is
    every one of them but two: Nether Shadow's return offer is about a card in
    a **graveyard** and Nafs Asp's is about an obligation *record* whose source
    may have left, and neither has a permanent id to be addressed by. Those two
    carry a ``subject_ordinal`` instead and are filed under
    :func:`subject_prompt_key` — which is what makes two eligible Nether
    Shadows two offers, where a bare name made them one and a single "yes"
    returned both.

    The bare name survives as the third form, for an entry carrying neither
    address: it names a *card*, so it answers every subject of that name at
    once. On a board with one copy that is exact, which is why it stayed
    correct for as long as it did.

    One function, read by the arming side (``web/turn_steps.py``) and by the
    answering side (``web/action_turn.py``), so what a prompt is filed under and
    what an answer is filed under cannot drift — which is the whole failure this
    file just came out of, one level up.
    """
    permanent_id = entry.get("permanent_id")
    if permanent_id is not None:
        return permanent_id
    ordinal = entry.get("subject_ordinal")
    if ordinal is None:
        return entry["card_name"]
    return subject_prompt_key(entry["card_name"], ordinal)


def upkeep_subject_answer(answers: dict | None, card_name: str, ordinal: int):
    """The seat's answer for the *ordinal*-th subject printed *card_name*, or
    None if they were not asked about it.

    The read half of :func:`subject_prompt_key`, and the twin of
    ``upkeep_effects.upkeep_answer`` one zone over. The bare name is consulted
    **after** the exact address and never before it: the specific answer wins
    over the blanket one, the same precedence
    :meth:`UpkeepPromptsMixin._upkeep_answers_by_permanent` gives an explicit id
    over a name. The fallback is what keeps every headless caller and every
    test in this repo working — ``{"Nether Shadow": True}`` still means "every
    one of them", which on a graveyard holding one copy is exact.

    Returns the raw value rather than a bool so a caller can tell "not asked"
    from "answered no": those two take different defaults, and collapsing them
    is how a prompt nobody was shown ends up counting as a refusal.
    """
    if not answers:
        return None
    exact = answers.get(subject_prompt_key(card_name, ordinal))
    if exact is not None:
        return exact
    return answers.get(card_name)


class UpkeepPromptsMixin:
    """The upkeep step's prompts and their answers, composed onto ``Game``."""

    def _upkeep_answers_by_permanent(self, answers: dict | None) -> dict | None:
        """Normalise one prompt-answer map so every battlefield answer is keyed
        by ``Permanent.permanent_id``.

        The web layer sends ids. A **string** key is the shorthand every
        headless caller and every test in this repo uses: it names a *card*, so
        it answers **every** permanent of that name at once. On a board with one
        copy that is exact, which is why it stayed correct for as long as it
        did; with two copies it is one answer for two decisions, and there was
        no way to say "pay for this one, let that one go".

        Expanded here, once, above every handler — not read as a fallback down
        in :func:`upkeep_effects.upkeep_answer`. A fallback per reader is ten
        places that have to agree about precedence, which is the reason
        ``web/actions.py`` resolves its permanent ids in one preamble too.

        An explicit id **wins** over a name covering the same permanent: the id
        is the specific answer and the name is the blanket one, and letting
        dict order decide is the silent precedence this step's registry exists
        to remove.

        Unmatched string keys are **kept**, not dropped: the two prompts whose
        subject is not a permanent (see :func:`upkeep_prompt_key`) are keyed by
        :func:`subject_prompt_key`, which is a string this loop can match no
        permanent to, and their readers look them up in this same map through
        :func:`upkeep_subject_answer`.
        """
        if not answers:
            return answers
        # Under either name a copy answers to: the one its prompt labels it
        # by (``card_name``, its name — CR 707.2) and the card it is printed
        # on, which is what this shorthand has always matched.
        by_name: dict[str, list] = {}
        for permanent in self.all_permanents():
            for name in dict.fromkeys((permanent.effective_card.name, permanent.card.name)):
                by_name.setdefault(name, []).append(permanent)
        keyed = dict(answers)
        for key, value in answers.items():
            if not isinstance(key, str):
                continue
            for permanent in by_name.get(key, ()):
                keyed.setdefault(permanent.permanent_id, value)
        return keyed

    def get_upkeep_pay_triggers(self, player_index: int) -> list[dict]:
        """Return pay-or-consequence upkeep triggers that the player must decide on.

        Only returns triggers where the permanent's controller is ``player_index``
        and the condition is ``upkeep_self`` (i.e. fires on *their* upkeep) —
        and, since echo, only those whose intervening-if is true (CR 603.4).

        This is the **prompt** side of the check ``resolve_upkeep`` already made
        on the resolution side, and it has to be the same check: an ability
        whose condition is false did not trigger, so offering its payment is
        offering to pay for nothing. No card in the pool reached the pair before
        — every trigger on one of these instruction kinds was ungated — so the
        gap cost nothing until CR 702.30a printed a condition on exactly this
        shape, at which point an echo creature would have asked for its cost at
        every upkeep for the rest of the game while the handler correctly
        sacrificed nothing. A player quoted a price the engine will not charge
        is the same defect as one charged a price they were not quoted.
        """
        from ..game_types import OracleExecutionContext
        from ..handlers.control_flow import evaluate_condition

        controller = self.players[player_index]
        choices: list[dict] = []
        for _idx, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"upkeep_self"},
            instruction_kinds=_UPKEEP_PAY_KINDS,
            players=[controller],
        ):
            gate = (trig.instruction.payload or {}).get("intervening_if")
            if gate is not None and not evaluate_condition(
                self,
                OracleExecutionContext(
                    caster=controller,
                    target=controller,
                    card=permanent.card,
                    source_permanent=permanent,
                    trigger_context={"event_subject_player": player_index},
                ),
                gate,
            ):
                continue
            # The cost a counter-escalating upkeep will ask for (CR 702.24a's
            # cumulative upkeep, and Cyclone printing the same sentence
            # longhand): the counter for THIS upkeep is added when the trigger
            # resolves, so the prompt quotes the counters already on it plus
            # one. `upcoming_cost` and the handlers' `scaled_cost` share that
            # arithmetic — this used to be a branch naming one card's
            # instruction kind, which is a second copy of it and the way a
            # player gets quoted one number and charged another.
            #
            # "…unless you pay **its mana cost**" is resolved first, through the
            # reader the handlers charge from. An unpayable one (CR 118.6: the
            # permanent has no mana cost) offers nothing — there is no payment
            # to quote, and the handler sacrifices without asking.
            tolled = resolved_toll_instruction(permanent, trig.instruction, self)
            if tolled is None:
                continue
            cost = upcoming_cost(permanent, tolled)
            choices.append({
                "card_name": permanent.effective_card.name,
                # Which permanent this price is being quoted for (CR 400.7's
                # identity). ``card_name`` stays for the label; it is no longer
                # the address, because two copies print two of these entries
                # and a client that could not tell them apart could not answer
                # them apart either.
                "permanent_id": permanent.permanent_id,
                **cost_prompt_fields(cost),
                "kind": trig.instruction.kind,
                # "unless you pay" alternative consequence, used to label the
                # decline button (e.g. Force of Nature deals 8 damage; it is
                # not a sacrifice).
                "damage": int(trig.instruction.payload.get("damage", 0)),
            })

        # Paralyze-style auras: "At the beginning of the upkeep of enchanted
        # creature's controller, that player may pay {N}. If they do, untap the
        # creature." The aura may be controlled by either player, so scan every
        # battlefield for one whose enchanted creature this player controls.
        for permanent in self.all_permanents():
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(controller, attached):
                continue
            trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"upkeep_enchanted_controller"},
                instruction_kinds={"upkeep_pay_to_untap_enchanted"},
            ), None)
            if trig is not None:
                choices.append({
                    "card_name": permanent.effective_card.name,
                    "permanent_id": permanent.permanent_id,
                    **cost_prompt_fields(cost_from_payload(trig.instruction.payload)),
                    "kind": trig.instruction.kind,
                    "damage": 0,
                })

        # Farmstead-style enchant-land grants: "Enchanted land has 'At the beginning
        # of your upkeep, you may pay {N}. If you do, you gain X life.'" The enchanted
        # land's controller (player_index) may pay for the life.
        for permanent in self.all_permanents():
            if not permanent.has_type("enchantment"):
                continue
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(controller, attached):
                continue
            text = compile_card_oracle(permanent.effective_card).normalized_text
            if (
                not aura_enchants(permanent.effective_card.oracle_text, "land")
                or "you may pay" not in text or "you gain" not in text
            ):
                continue
            pay_match = re.search(r"you may pay ((?:\{[wubrgc]\})+)", text)
            mana: dict[str, int] = {}
            if pay_match:
                for sym in re.findall(r"\{([wubrg])\}", pay_match.group(1)):
                    mana[sym.upper()] = mana.get(sym.upper(), 0) + 1
            choices.append({
                "card_name": permanent.effective_card.name,
                "permanent_id": permanent.permanent_id,
                **cost_prompt_fields(UpkeepCost(mana=mana)),
                "kind": "upkeep_pay_to_gain_life",
                "damage": 0,
            })
        return choices

    def get_upkeep_mana_prevention_triggers(self, player_index: int) -> list[dict]:
        """Return upkeep triggers where this player may pay any amount of mana to
        prevent that much damage (Power Leak). The UI prompts for an amount; the
        chosen value is passed back via ``resolve_upkeep(mana_prevention=...)``.
        """
        victim = self.players[player_index]
        triggers: list[dict] = []
        for permanent in self.all_permanents():
            if "prevent x of that damage" not in permanent.effective_card.oracle_text.lower():
                continue
            attached = permanent.metadata.get("attached_to")
            if attached is None or not self.controls(victim, attached):
                continue
            trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"upkeep_enchanted_controller"},
                instruction_kinds={"deal_damage"},
            ), None)
            if trig is not None:
                triggers.append({
                    "card_name": permanent.effective_card.name,
                    "permanent_id": permanent.permanent_id,
                    "kind": "upkeep_pay_to_prevent_damage",
                    "damage": int(trig.instruction.payload.get("amount", 1)),
                })
        return triggers

    def _graveyard_return_candidates(self, player_index: int) -> list:
        """``(graveyard index, ordinal, card)`` for each card whose "return
        during your upkeep" condition is currently met for ``player_index``
        (Nether Shadow with enough creature cards above it). Shared by the
        prompt query and the upkeep resolver so both agree on which cards are
        eligible **and on how to name one of them**.

        **The index is part of the answer, not scaffolding.** A graveyard holds
        ``CardDefinition`` objects and ``load_cards`` dedupes by ``oracle_id``, so
        two copies of one card in one graveyard are the *same object* — which
        means a caller handed only the card cannot say which copy was eligible.
        This used to return the card alone and the resolver removed it with
        ``[c for c in graveyard if c is not card]``, which removes **every** copy:
        with one Nether Shadow deep enough to return and a second one on top, five
        cards went in and four came out. That is the look-alike bug class
        ``tests/engine/test_control_reads.py`` bans on the battlefield, and it is
        worse here, because on the battlefield the copies are distinct objects.

        The **ordinal** beside it is the other half of that fact, and it is the
        half the *player* needed: an index is a slot and renumbers, so it cannot
        be handed out and taken back, but ``GraveyardTarget.ordinal`` — which
        copy of this card, counting from the bottom — survives everything except
        another copy of the same card leaving the same pile. It is read off
        ``Game.graveyard_target_at`` rather than recounted here, so the prompt's
        address and a target's are one derivation.
        """
        owner = self.players[player_index]
        candidates = []
        for grave_index, card in enumerate(owner.graveyard):
            trig = next(matching_triggers(
                card,
                condition_kinds={"upkeep_self"},
                instruction_kinds={"upkeep_return_self_from_graveyard"},
            ), None)
            if trig is None:
                continue
            instr = trig.instruction
            creatures_above = sum(
                1
                for above in owner.graveyard[grave_index + 1:]
                if above.primary_type == "creature"
            )
            if creatures_above >= int(instr.payload.get("min_creatures_above", 3)):
                target = self.graveyard_target_at(player_index, grave_index)
                candidates.append((grave_index, target.ordinal, card))
        return candidates

    def get_optional_upkeep_triggers(self, player_index: int) -> list[dict]:
        """Optional ("you may") upkeep triggers awaiting a yes/no decision on this
        player's own upkeep.

        Generic across trigger sources; currently covers graveyard-recursion
        abilities (Nether Shadow) and Vesuvan Doppelganger's granted re-copy.
        Each entry carries a human-readable ``prompt`` and the key its answer
        goes under — see :func:`upkeep_prompt_key`.
        """
        triggers: list[dict] = []
        # **The graveyard half.** Its subject is a card in a graveyard, which
        # has no ``permanent_id`` to be addressed by — so it carries the other
        # address, ``subject_ordinal`` (see :func:`subject_prompt_key`). It used
        # to be deduped by printed name, which made two eligible Nether Shadows
        # one offer whose single "yes" returned **both**: a creature created out
        # of nothing, in the player's favour, silently. CR 603.3d makes them two
        # abilities and CR 603.3 puts each on the stack on its own, so they are
        # two offers and each is answerable alone.
        for _grave_index, ordinal, card in self._graveyard_return_candidates(player_index):
            triggers.append({
                "card_name": card.name,
                "permanent_id": None,
                "subject_ordinal": ordinal,
                "kind": "upkeep_return_self_from_graveyard",
                "prompt": f"Return {card.name} to the battlefield from your graveyard?",
            })
        # Living Artifact used to be surfaced here, matched on a substring of
        # its own text and answered through `optional_choices`. Its trigger now
        # takes the ordinary route (CR 603.3) and asks through the general
        # `optional_pay` prompt, which the web layer renders from the registry —
        # so listing it here as well would offer the same decision twice, only
        # one of which anything acts on.
        # Vesuvan Doppelganger's granted ability: "At the beginning of your
        # upkeep, you may have this creature become a copy of target creature."
        # Carries a creature-target choice alongside the yes/no.
        for perm_index, perm in enumerate(self.players[player_index].battlefield):
            if not grants_ability(perm, RECOPY_EACH_UPKEEP):
                continue
            valid_targets = [
                {
                    "kind": "permanent", "seat": s, "index": i,
                    "id": p.permanent_id, "name": p.effective_card.name,
                }
                for s, player in enumerate(self.players)
                for i, p in enumerate(player.battlefield)
                if p is not perm and self._is_creature(p)
            ]
            if not valid_targets:
                continue
            triggers.append({
                "card_name": perm.effective_card.name,
                # CR 603.3d, and the reason the name dedupe that used to stand
                # here is gone: two Vesuvan Doppelgangers are two triggers, each
                # choosing its own creature to copy, and one prompt for both
                # made the second one's choice for it.
                "permanent_id": perm.permanent_id,
                "kind": "upkeep_recopy",
                "prompt": f"Have {perm.effective_card.name} become a copy of a different creature?",
                "needs_target": "creature",
                "valid_targets": valid_targets,
                "permanent_index": perm_index,
            })
        return triggers

    def _base_pt_copy_candidates(self, source: Permanent) -> list[Permanent]:
        """Legal targets for a "change …'s base power and toughness to the
        power and toughness of target creature other than ~" upkeep trigger
        (Halfdane): every creature on any battlefield except the source itself
        — the exclusion is by identity, because a look-alike is a different
        permanent (CR 400.7)."""
        return [
            perm
            for _seat, perm in self.permanents_with_controller()
            if perm.is_creature and perm is not source
        ]

    def _upkeep_target_pick(
        self, source: Permanent, trigger_targets: dict | None
    ) -> "tuple[bool, Permanent | None]":
        """Whether *source*'s upkeep trigger was given a target at its prompt,
        and the permanent that answer names — None where it has left.

        **An answer is a ``permanent_id``** (CR 400.7), the ``id`` each
        ``valid_targets`` entry carries. It was a ``(seat, battlefield
        index)`` pair: a *slot*, read again when the step resolved, so a
        permanent leaving in between renumbered the slot onto its neighbour
        and every reader below acted on whichever permanent slid in — or, past
        the end of the list, took the engine's first candidate instead of the
        player's. Nothing resolves between the prompt and this step today; an
        id makes that a fact about the answer rather than about the gate.

        A pair is refused outright rather than read as a stale answer: a
        caller still writing slots would otherwise lose every choice it makes,
        silently.
        """
        chosen = (trigger_targets or {}).get(source.permanent_id)
        if chosen is None:
            return False, None
        if isinstance(chosen, bool) or not isinstance(chosen, int):
            raise TypeError(
                f"{source.card.name}'s upkeep target is answered by the chosen "
                f"permanent's permanent_id, not {chosen!r}"
            )
        return True, self.permanent_by_id(chosen)

    def _resolve_upkeep_trigger_target(
        self, source: Permanent, trigger_targets: dict | None, candidates: list[Permanent]
    ) -> Permanent | None:
        """The target its controller picked for *source*'s mandatory targeted
        upkeep trigger, or — for a seat nobody asked (AI/headless play) — the
        first legal candidate. Returns None with no candidates (CR 603.3d: a
        trigger with no legal target is removed from the stack).

        **A pick that no longer names a legal target is not replaced.** It
        fell back to the first candidate, so a player's choice became the
        engine's without a word; the target they chose is gone or illegal, and
        CR 608.2b removes an ability whose every target is (the step resolves
        this trigger as it puts it on the stack, so the two checks are one).

        Keyed by *source*'s ``permanent_id``. It took the printed name, which
        is one answer for every copy: CR 603.3d chooses a target per ability,
        by its controller, as it goes on the stack."""
        answered, picked = self._upkeep_target_pick(source, trigger_targets)
        if not answered:
            return candidates[0] if candidates else None
        if picked is not None and any(picked is perm for perm in candidates):
            return picked
        self.log.append(
            f"{source.card.name}'s upkeep trigger does nothing: the target "
            "chosen for it is no longer a legal one (CR 608.2b)"
        )
        return None

    def _printed_target_upkeep_trigger(self, trig, controller) -> tuple | None:
        """The target-prompt entry an upkeep trigger's own instruction supplies,
        or None when it names no object target.

        The twin of the hand-written table in ``get_upkeep_target_triggers``,
        and the arm that should grow: the printed noun phrase is already in the
        instruction's ``targets`` payload — put there by the same lowering that
        built the effect — so a card that says "target non-Wall creature an
        opponent controls" needs no row of its own, and neither does the next
        one. The table above it holds the effects whose legal targets are *not*
        a filter over the battlefield (a land of your own to sacrifice, every
        creature but the source).

        It was Erhnam Djinn's row, with a hand-written candidate lookup beside
        it, back when a card-keyed hook carried the whole ability. Deriving the
        candidates from the payload is what let the hook go without the human
        losing the choice.
        """
        from ..subject_filters import subject_matches

        described = trig.instruction.payload.get("targets")
        if not isinstance(described, dict) or described.get("kind") != "object":
            return None
        if described.get("quantifier") != "target":
            return None
        filters = described.get("filter") or {}
        seat = self.seat_index(controller)

        def find_candidates(_controller, source):
            described_set = [
                perm
                for perm in self.all_permanents()
                if subject_matches(
                    self, perm, filters, observer=seat, source=source
                )
            ]
            # What the phrase *describes* is not yet what the ability may
            # *target* (CR 115.1): shroud, hexproof and protection from the
            # source are asked by the picker, not by the noun phrase. This
            # prompt answered with the described set alone, so Erhnam Djinn was
            # offered an Autumn Willow — and the answer is stamped on the stack
            # object as the choice the event made, which nothing re-checks.
            #
            # Held to the list the trigger would choose from for itself
            # (``_trigger_target_candidates``, asked of the trigger as it will
            # exist — the prospective-object reading
            # ``legality_cast_spec.entry_trigger_cast_targets`` takes of an entry
            # trigger). Only ever narrower: where that picker declines the
            # phrase there is no list to hold this one to, and it stands.
            legal = self._upkeep_trigger_legal_targets(source, seat, trig)
            if legal is None:
                return described_set
            return [
                perm for perm in described_set
                if any(perm is allowed for allowed in legal)
            ]

        return (
            "upkeep_trigger_target",
            "creature" if filters.get("type_filter") == "creature" else "permanent",
            lambda name: f"{name}: choose a target for its upkeep trigger.",
            find_candidates,
        )

    def _upkeep_trigger_legal_targets(
        self, source: Permanent, seat: int, trig
    ) -> "list[Permanent] | None":
        """The permanents *trig* could legally target if it went on the stack
        now, or None when the trigger's own picker makes no choice it could
        list (a player, a phrase it cannot narrow, no target at all).

        ``_trigger_target_candidates`` asked of the trigger as it will exist:
        a prospective stack object with this source and this instruction and
        nothing announced, which is what ``_enqueue_triggered_ability`` builds
        a moment later. The upkeep step has two readers of it, and both are
        an answer given *before* the object exists — the prompt that offers a
        target, and the pick that comes back.
        """
        from ..game_types import StackItem

        offer = self._trigger_target_candidates(StackItem(
            source.card, seat, None, None, None,
            ability_instruction=trig.instruction,
            ability_effect_kind=trig.effect_kind,
            ability_text=trig.source_line,
            source_permanent=source,
        ))
        if offer is None:
            return None
        return [
            found
            for entry in offer[2] if entry.get("kind") == "permanent"
            for found in (self.permanent_at(entry["seat"], entry["index"]),)
            if found is not None
        ]

    def get_upkeep_target_triggers(self, player_index: int) -> list[dict]:
        """Mandatory upkeep triggers that need the controller to choose a target.

        Same payload shape as ``get_optional_upkeep_triggers`` (``card_name``,
        ``permanent_id``, ``prompt``, ``valid_targets``) plus ``mandatory:
        True``, so the web layer and UI reuse one channel — the difference is
        only that the player picks a target rather than answering yes/no, and
        can't decline.

        **One entry per trigger, never one per card name.** This deduped by
        ``perm.card.name``, so two Erhnam Djinns produced a single prompt and
        the second ability's target was never asked for — it took the first
        one's answer, and both grants landed on one creature. CR 603.3d hands
        the choice to CR 601.2c, which makes it per ability. Measured on a
        board: Erhnam Djinn and Afiya Grove are the two shipped cards a seat
        can hold two of (Halfdane prints the third such trigger and is
        legendary, so CR 704.5j means one controller never has two).
        """
        # instruction kind -> (choice kind, target-noun the UI highlights,
        # prompt builder, candidate lookup). A lookup takes the trigger's
        # controller and its source permanent — most read one or the other,
        # and handing both over is what let the base-P/T copy exclude its own
        # source without the table growing a second shape.
        targeted_kinds = {
            "set_source_base_pt_from_target_until_next_upkeep": (
                "upkeep_copy_base_pt",
                "creature",
                lambda name: (
                    f"{name}: choose a creature whose power and toughness "
                    f"{name} copies until the end of your next upkeep."
                ),
                lambda controller, source: self._base_pt_copy_candidates(source),
            ),
        }
        triggers: list[dict] = []
        controller = self.players[player_index]
        for perm in self.controlled_by(player_index):
            program = compile_card_oracle(perm.effective_card)
            for trig in battlefield_triggers(program.triggered_abilities):
                if trig.instruction is None or trig.condition.kind != "upkeep_self":
                    continue
                entry = targeted_kinds.get(trig.instruction.kind)
                if entry is None:
                    entry = self._printed_target_upkeep_trigger(trig, controller)
                if entry is None:
                    continue
                choice_kind, target_noun, build_prompt, find_candidates = entry
                candidates = find_candidates(controller, perm)
                if not candidates:
                    continue
                triggers.append({
                    "card_name": perm.effective_card.name,
                    "permanent_id": perm.permanent_id,
                    "kind": choice_kind,
                    "mandatory": True,
                    "prompt": build_prompt(perm.effective_card.name),
                    "needs_target": target_noun,
                    # ``id`` is the answer (``_upkeep_target_pick``); the seat
                    # and slot are where the client draws the highlight.
                    "valid_targets": [
                        {
                            "kind": "permanent", "seat": s, "index": i,
                            "id": p.permanent_id, "name": p.effective_card.name,
                        }
                        for s, player in enumerate(self.players)
                        for i, p in enumerate(player.battlefield)
                        if any(p is c for c in candidates)
                    ],
                })
        return triggers
