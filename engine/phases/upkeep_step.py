from __future__ import annotations

"""Upkeep step (CR 503).

"At the beginning of upkeep" triggered abilities are put on the stack here, plus
the pay-or-consequence upkeep triggers that may require an interactive choice,
enchant-land upkeep effects, and graveyard-recursion upkeep triggers.

The pay-or-consequence effects themselves live in upkeep_effects.py, registered
by (trigger condition, instruction kind); this module scans the battlefield and
dispatches. A new upkeep card is an entry there, never a branch here.
"""

import re

from ..auras import aura_enchants
from ..delayed_triggers import fire_delayed_triggers
from ..exiled_records import live_records
from ..keywords import (clear_granted_ability_lines,
                        clear_granted_keywords)
from ..copies import RECOPY_EACH_UPKEEP, grants_ability
from ..land_types import MIRE_COUNTER, end_land_type_change
from ..layer_bridge import GAINED_TYPES
from ..models import Permanent
from ..cast_permissions import expire_at_upkeep as expire_upkeep_permissions
from ..oracle import OracleInstruction, compile_card_oracle
from ..trigger_utils import iter_triggered_abilities, matching_triggers
from ..mixins._constants import _UPKEEP_PAY_KINDS
from ..cumulative_upkeep import upcoming_cost
from ..mana_payment import plan_payment, untapped_mana_lands
from ..upkeep_costs import UpkeepCost, cost_from_payload, cost_prompt_fields
from ..effect_labels import triggered_label
from ..handlers import EFFECT_HANDLERS
from .upkeep_effects import UPKEEP_EFFECTS, UpkeepContext, UpkeepEffectsMixin

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
    def can_pay_upkeep_mana(self, player, mana: dict[str, int], *, purpose=None) -> bool:
        """Whether *player* can cover an upkeep cost's mana: from the pool and by
        tapping untapped mana-producing lands, coloured pips included.

        An upkeep payment happens inside the trigger's resolution with no
        priority window, so the payer may activate mana abilities while paying
        (CR 605.3a) and the question is ``mana_payment.plan_payment``'s — the
        one every other offered price in the engine asks. This used to cover
        the coloured pips from floating mana alone and let only the *generic*
        part tap, so Stasis, Glaciers, Demonic Hordes, every {U} cumulative
        upkeep and both FEM Chants were sacrificed on the first upkeep of every
        AI or headless game with the right lands untapped, and Island Fish
        Jasconius never untapped at all.

        *purpose* is what the cost is for, so "spend this mana only to pay
        cumulative upkeep costs" (Adarkar Unicorn, Snowfall) can be counted:
        that mana lives in its own bucket beside the pool, and a payment that
        does not ask cannot see it. Without a purpose only the ordinary pool is
        offered, which is what every caller written before this got.
        """
        return self._upkeep_payment_plan(player, mana, purpose) is not None

    def _upkeep_payment_plan(self, player, mana: dict[str, int], purpose):
        """How *player* would pay *mana* now, or None — asked once by the
        affordability test and once by the spend, so the two cannot disagree
        about which lands and which units are in play."""
        return plan_payment(
            self._upkeep_pool(player, purpose),
            untapped_mana_lands(self.controlled_by(player)),
            mana,
            produces=self._land_payment_colors,
        )

    def _upkeep_pool(self, player, purpose) -> dict[str, int]:
        """The mana an upkeep payment may draw on: the pool, plus any restricted
        bucket *purpose* admits (CR 106.6).

        One reader for both halves of the pair, so what is *offered* and what
        is *spent* cannot disagree about which buckets are in play — the split
        that let Energy Flux's generic-only cost be paid by every artifact on
        the board. The restricted units go in **first**: ``plan_payment`` pays
        the generic part from the pool in insertion order, and a restricted
        unit is lost at the next step boundary either way, so anything else
        spent ahead of it is thrown away (the casting path's reason).
        """
        from ..restricted_mana import spendable_restricted_mana

        merged = dict(spendable_restricted_mana(player, purpose))
        for symbol, amount in player.mana_pool.items():
            merged[symbol] = merged.get(symbol, 0) + amount
        return merged

    def _spend_upkeep_mana(self, player, mana: dict[str, int], *, purpose=None) -> None:
        """Spend an upkeep cost validated by ``can_pay_upkeep_mana``: the plan's
        floating units out of the pool (restricted bucket first where the
        purpose admits it) and the plan's lands tapped.

        Both halves, because a plan is *how* a cost is paid and paying from one
        without the other would let the same land answer two costs — the
        sibling ``_spend_payment_plan`` says the same. A plan that cannot be
        formed here is a caller that skipped the affordability test, and that
        is raised rather than spent in part: a cost half charged is a free
        ability, the class Vodalian War Machine's tap costs were.
        """
        from ..restricted_mana import debit_restricted_mana, spendable_restricted_mana

        plan = self._upkeep_payment_plan(player, mana, purpose)
        if plan is None:
            raise ValueError(
                f"{player.name} cannot pay {mana} at upkeep; the caller must ask "
                "can_pay_upkeep_mana first"
            )
        restricted = spendable_restricted_mana(player, purpose)
        for symbol, amount in plan.from_pool.items():
            from_restricted = min(amount, restricted.get(symbol, 0))
            if from_restricted:
                debit_restricted_mana(player, purpose, symbol, from_restricted)
            player.mana_pool[symbol] = (
                int(player.mana_pool.get(symbol, 0)) - (amount - from_restricted)
            )
        for land in plan.tapped:
            self.become_tapped(land)

    def can_pay_upkeep_cost(self, player, cost, *, purpose=None) -> bool:
        """Whether *player* can pay a whole upkeep cost — CR 702.24a's [cost],
        which is mana, life and a sacrifice in whatever combination the card
        printed (``upkeep_costs.UpkeepCost``).

        Asked about all of it at once, because partial payment is never allowed
        (CR 702.24a's last sentence, and CR 601.2h's rule for every other cost):
        a player who cannot cover the life half pays none of the mana half
        either. That is also why this wraps :meth:`can_pay_upkeep_mana` rather
        than replacing it — the mana question is unchanged and has one answer;
        what is new is that it is no longer the only question.
        """
        from ..handlers.life_and_game import can_pay_life

        if not self.can_pay_upkeep_mana(player, cost.mana, purpose=purpose):
            return False
        # CR 119.4: life may be paid only down to 0.
        if cost.life and not can_pay_life(player, cost.life):
            return False
        if cost.sacrifices:
            # The charger's own candidate reader, so what is *offered* and what
            # can actually be given up cannot disagree — the split that let
            # Energy Flux's generic cost be paid for free one method up.
            candidates = self._sacrifice_candidate_indices(player, cost.sacrifice)
            if len(candidates) < cost.sacrifices:
                return False
        return True

    def pay_upkeep_cost(self, player, cost, *, reason: str, purpose=None) -> None:
        """Pay an upkeep cost already validated by :meth:`can_pay_upkeep_cost`.

        The sacrifice goes through ``arm_forced_sacrifice``, which is what makes
        *which* permanent the payer's choice (CR 701.21a) and prompts a human
        seat for it; the affordability test above is what stops that prompt from
        being armed for a payment the player could not have made.
        """
        self._spend_upkeep_mana(player, cost.mana, purpose=purpose)
        if cost.life:
            player.life -= cost.life
            self.log.append(f"{player.name} paid {cost.life} life for {reason}")
        if cost.sacrifices:
            # `seat_index`, not `players.index`: the latter is an equality
            # search over a mutable dataclass, so two seats holding equal state
            # would resolve to the same one.
            self.arm_forced_sacrifice(
                self.seat_index(player),
                cost.sacrifices,
                filter=cost.sacrifice,
                reason=reason,
            )

    def get_upkeep_pay_triggers(self, player_index: int) -> list[dict]:
        """Return pay-or-consequence upkeep triggers that the player must decide on.

        Only returns triggers where the permanent's controller is ``player_index``
        and the condition is ``upkeep_self`` (i.e. fires on *their* upkeep).
        """
        controller = self.players[player_index]
        choices: list[dict] = []
        for _idx, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"upkeep_self"},
            instruction_kinds=_UPKEEP_PAY_KINDS,
            players=[controller],
        ):
            # The cost a counter-escalating upkeep will ask for (CR 702.24a's
            # cumulative upkeep, and Cyclone printing the same sentence
            # longhand): the counter for THIS upkeep is added when the trigger
            # resolves, so the prompt quotes the counters already on it plus
            # one. `upcoming_cost` and the handlers' `scaled_cost` share that
            # arithmetic — this used to be a branch naming one card's
            # instruction kind, which is a second copy of it and the way a
            # player gets quoted one number and charged another.
            cost = upcoming_cost(permanent, trig.instruction)
            choices.append({
                "card_name": permanent.card.name,
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
                    "card_name": permanent.card.name,
                    **cost_prompt_fields(cost_from_payload(trig.instruction.payload)),
                    "kind": trig.instruction.kind,
                    "damage": 0,
                })

        # Farmstead-style enchant-land grants: "Enchanted land has 'At the beginning
        # of your upkeep, you may pay {N}. If you do, you gain X life.'" The enchanted
        # land's controller (player_index) may pay for the life.
        for permanent in self.all_permanents():
            if permanent.card.primary_type != "enchantment":
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
                "card_name": permanent.card.name,
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
                    "card_name": permanent.card.name,
                    "kind": "upkeep_pay_to_prevent_damage",
                    "damage": int(trig.instruction.payload.get("amount", 1)),
                })
        return triggers

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

    def _graveyard_return_candidates(self, player_index: int) -> list:
        """``(graveyard index, card)`` for each card whose "return during your
        upkeep" condition is currently met for ``player_index`` (Nether Shadow
        with enough creature cards above it). Shared by the prompt query and the
        upkeep resolver so both agree on which cards are eligible.

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
                candidates.append((grave_index, card))
        return candidates

    def get_optional_upkeep_triggers(self, player_index: int) -> list[dict]:
        """Optional ("you may") upkeep triggers awaiting a yes/no decision on this
        player's own upkeep.

        Generic across trigger sources; currently covers graveyard-recursion
        abilities (Nether Shadow). Each entry carries a human-readable ``prompt``
        and the ``card_name`` used to key the player's decision.
        """
        triggers: list[dict] = []
        seen: set[str] = set()
        for _grave_index, card in self._graveyard_return_candidates(player_index):
            if card.name in seen:
                continue
            seen.add(card.name)
            triggers.append({
                "card_name": card.name,
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
            if perm.card.name in seen:
                continue
            valid_targets = [
                {"kind": "permanent", "seat": s, "index": i, "name": p.card.name}
                for s, player in enumerate(self.players)
                for i, p in enumerate(player.battlefield)
                if p is not perm and self._is_creature(p)
            ]
            if not valid_targets:
                continue
            seen.add(perm.card.name)
            triggers.append({
                "card_name": perm.card.name,
                "kind": "upkeep_recopy",
                "prompt": f"Have {perm.card.name} become a copy of a different creature?",
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

    def _upkeep_land_sacrifice_candidates(self, controller) -> list[Permanent]:
        """Legal choices for Serendib Djinn's upkeep "sacrifice a land": every
        land its controller controls (you choose which of your own permanents a
        sacrifice takes, CR 701.21a)."""
        return [perm for perm in self.controlled_by(controller) if perm.card.primary_type == "land"]

    def _resolve_upkeep_trigger_target(
        self, card_name: str, trigger_targets: dict | None, candidates: list[Permanent]
    ) -> Permanent | None:
        """The target a human picked for a mandatory targeted upkeep trigger, or —
        for AI/headless play, or a stale pick whose permanent has since left the
        battlefield — the first legal candidate. Returns None with no candidates
        (CR 603.3d: a trigger with no legal target is removed from the stack)."""
        chosen = (trigger_targets or {}).get(card_name)
        if chosen is not None:
            seat, index = chosen
            if 0 <= seat < len(self.players) and 0 <= index < len(self.players[seat].battlefield):
                candidate = self.players[seat].battlefield[index]
                if any(candidate is perm for perm in candidates):
                    return candidate
        return candidates[0] if candidates else None

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
            return [
                perm
                for perm in self.all_permanents()
                if subject_matches(
                    self, perm, filters, observer=seat, source=source
                )
            ]

        return (
            "upkeep_trigger_target",
            "creature" if filters.get("type_filter") == "creature" else "permanent",
            lambda name: f"{name}: choose a target for its upkeep trigger.",
            find_candidates,
        )

    def get_upkeep_target_triggers(self, player_index: int) -> list[dict]:
        """Mandatory upkeep triggers that need the controller to choose a target.

        Same payload shape as ``get_optional_upkeep_triggers`` (``card_name``,
        ``prompt``, ``valid_targets``) plus ``mandatory: True``, so the web layer
        and UI reuse one channel — the difference is only that the player picks a
        target rather than answering yes/no, and can't decline.
        """
        # instruction kind -> (choice kind, target-noun the UI highlights,
        # prompt builder, candidate lookup). A lookup takes the trigger's
        # controller and its source permanent — most read one or the other,
        # and handing both over is what let the base-P/T copy exclude its own
        # source without the table growing a second shape.
        targeted_kinds = {
            "upkeep_sacrifice_land_conditional_damage": (
                "upkeep_sacrifice_land",
                "land",
                lambda name: f"{name}: choose a land to sacrifice.",
                lambda controller, source: self._upkeep_land_sacrifice_candidates(controller),
            ),
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
        seen: set[str] = set()
        controller = self.players[player_index]
        for perm in self.controlled_by(player_index):
            program = compile_card_oracle(perm.effective_card)
            for trig in program.triggered_abilities:
                if trig.instruction is None or trig.condition.kind != "upkeep_self":
                    continue
                entry = targeted_kinds.get(trig.instruction.kind)
                if entry is None:
                    entry = self._printed_target_upkeep_trigger(trig, controller)
                if entry is None:
                    continue
                if perm.card.name in seen:
                    continue
                choice_kind, target_noun, build_prompt, find_candidates = entry
                candidates = find_candidates(controller, perm)
                if not candidates:
                    continue
                seen.add(perm.card.name)
                triggers.append({
                    "card_name": perm.card.name,
                    "kind": choice_kind,
                    "mandatory": True,
                    "prompt": build_prompt(perm.card.name),
                    "needs_target": target_noun,
                    "valid_targets": [
                        {"kind": "permanent", "seat": s, "index": i, "name": p.card.name}
                        for s, player in enumerate(self.players)
                        for i, p in enumerate(player.battlefield)
                        if any(p is c for c in candidates)
                    ],
                })
        return triggers

    def _force_sacrifice_first_land(self, controller, source, chosen: Permanent | None = None) -> Permanent | None:
        """Sacrifice a land on *controller*'s battlefield to *source*'s upkeep
        effect, logging it. Returns the sacrificed land so callers can branch on
        its type (Serendib Djinn's "if it was an Island" damage), or None if the
        player controls no land.

        ``chosen`` is the land its controller picked (CR 701.21a: you choose
        which of your own permanents a sacrifice takes). Without one — AI /
        headless play, or an effect where another player does the choosing — the
        first land is taken, the deterministic forced-sacrifice fallback."""
        for idx, land in enumerate(controller.battlefield):
            if land.card.primary_type != "land":
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

    def _destroy_least_power_creature(self, owner, victim, card_name: str, chosen: bool = False) -> None:
        """Drop of Honey's kill (CR 701.7, "it can't be regenerated")."""
        self.remove_from_battlefield(victim)
        self._permanent_to_graveyard(owner, victim)
        how = "least power, controller's choice" if chosen else "least power"
        self.log.append(
            f"{card_name} destroyed {victim.card.name} ({how}; it can't be regenerated)"
        )

    def _live_least_power_candidates(self, choice) -> list:
        """The tied creatures still on a battlefield — a candidate can die to
        something else while the prompt waits."""
        return [
            perm
            for perm in (choice.data.get("_candidate_perms") or [])
            if self.is_on_battlefield(perm)
        ]

    def confirm_least_power_choice(
        self, player_index: int, target_seat: int, target_permanent_index: int
    ) -> bool:
        """Resolve a pending Drop of Honey tie-break: destroy the creature the
        controller chose among those tied for least power."""
        return self.resolve_pending_choice(
            "least_power_choice", player_index,
            target_seat=target_seat, target_permanent_index=target_permanent_index,
        )

    def _resolve_least_power_choice(
        self, choice, target_seat: int, target_permanent_index: int
    ) -> bool:
        """If every stored candidate has meanwhile left the battlefield, the
        prompt clears with nothing to destroy."""
        live = self._live_least_power_candidates(choice)
        if not live:
            self.discard_pending_choice(choice)
            self.log.append(f"{choice.data['card_name']}: no tied creature remains to destroy")
            return True
        if not (0 <= target_seat < len(self.players)):
            return False
        owner = self.players[target_seat]
        if not (0 <= target_permanent_index < len(owner.battlefield)):
            return False
        victim = owner.battlefield[target_permanent_index]
        if not any(victim is perm for perm in live):
            return False
        self.discard_pending_choice(choice)
        self._destroy_least_power_creature(owner, victim, choice.data["card_name"], chosen=True)
        self.check_state_based_actions()
        return True

    def _default_least_power_choice(self, choice) -> None:
        """Break the tie by battlefield scan order — the first tied creature."""
        self.discard_pending_choice(choice)
        live = self._live_least_power_candidates(choice)
        if not live:
            return
        victim = live[0]
        owner = self.players[self.controller_index_of(victim)]
        self._destroy_least_power_creature(owner, victim, choice.data["card_name"])

    def resolve_upkeep(self, player_index: int, human_choices: dict[str, bool] | None = None, optional_choices: dict[str, bool] | None = None, defer_priority: bool = False, mana_prevention: dict[str, int] | None = None, sacrifice_choices: dict[str, int] | None = None, trigger_targets: dict[str, tuple[int, int]] | None = None) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
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
            # "Until **your** next upkeep, target noncreature artifact becomes
            # an artifact creature…" (Xenic Poltergeist) — the same moment and
            # the same reasoning as the sweep above: it expires at the
            # start of that upkeep, before this turn's own triggers get a
            # chance to grant a fresh one. Whose upkeep is the seat recorded
            # when the ability resolved, because CR 109.5 makes it the
            # controller of the ability rather than of the affected permanent.
            gained = perm.metadata.get(GAINED_TYPES)
            if gained:
                kept = [
                    g for g in gained
                    if not (
                        g.get("duration") == "until_your_next_upkeep"
                        and g.get("seat") == player_index
                    )
                ]
                if kept:
                    perm.metadata[GAINED_TYPES] = kept
                else:
                    perm.metadata.pop(GAINED_TYPES, None)
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
            for trig in program.triggered_abilities:
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
                        picked = (trigger_targets or {}).get(permanent.card.name)
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
                            "target_player_index": (
                                picked[0] if picked
                                else player_index
                                if cond in ("upkeep_chosen", "upkeep_enchanted_controller")
                                else None
                            ),
                            "target_permanent_index": picked[1] if picked else None,
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
        for record in live_records(self):
            if record.controller_index != player_index:
                continue
            for trig in matching_triggers(record.card, condition_kinds={"upkeep_self"}):
                if trig.instruction.kind not in EFFECT_HANDLERS:
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
                        "exile_record": record,
                    },
                })

        # Handle enchant-land auras with optional upkeep life gain (e.g. Farmstead)
        for permanent in self.all_permanents():
            if permanent.card.primary_type != "enchantment":
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
                if human_choices is not None and permanent.card.name in human_choices:
                    wants_pay = bool(human_choices[permanent.card.name])
                else:
                    wants_pay = can_pay
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
        accepted_returns = [
            (grave_index, card)
            for grave_index, card in self._graveyard_return_candidates(player_index)
            if optional_choices is None or optional_choices.get(card.name, False)
        ]
        # Remove highest index first, so popping one does not renumber the slots
        # of the ones still to come — the same ordering rule the several-card
        # graveyard return follows. Removing by identity instead would take every
        # copy of the card (see `_graveyard_return_candidates`).
        for grave_index, _card in sorted(accepted_returns, reverse=True):
            if 0 <= grave_index < len(owner.graveyard):
                owner.graveyard.pop(grave_index)
        # Then onto the battlefield in printed graveyard order, so the log reads
        # bottom-up as it always has.
        for _grave_index, card in accepted_returns:
            self._put_permanent_onto_battlefield(player_index, Permanent(card=card), None)
            self.log.append(
                f"{owner.name} returned {card.name} to the battlefield from the graveyard"
            )

        # Vesuvan Doppelganger's upkeep re-copy: apply an accepted choice to the
        # player-chosen creature. Declined (or target-less) prompts do nothing;
        # AI/headless runs (optional_choices is None) keep the current copy.
        for perm in list(owner.battlefield):
            if not grants_ability(perm, RECOPY_EACH_UPKEEP):
                continue
            if optional_choices is None or not optional_choices.get(perm.card.name, False):
                continue
            chosen = (trigger_targets or {}).get(perm.card.name)
            source = None
            if chosen is not None:
                seat, index = chosen
                if 0 <= seat < len(self.players) and 0 <= index < len(self.players[seat].battlefield):
                    candidate = self.players[seat].battlefield[index]
                    if candidate is not perm and self._is_creature(candidate):
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

        # Put the collected non-interactive upkeep triggers on the stack in APNAP
        # order; they resolve through the upkeep priority window opened below.
        self._enqueue_triggered_batch(upkeep_events)

        # CR 704.3: state-based actions are checked before a player receives
        # priority. Several upkeep effects deal damage inline (Cyclone's wind
        # counters, the pay-or-suffer family), and this is what destroys what
        # they killed — the handlers no longer sweep for themselves.
        self.check_state_based_actions()

        self._close_or_defer_step(phase, step, defer_priority)
