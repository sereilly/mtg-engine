from __future__ import annotations

"""Authoritative legality queries for the web UI.

The browser used to re-derive which creatures may attack, which blocks are legal,
and which permanents/players are legal targets for a spell or ability by parsing
oracle text client-side. That duplicated engine rules and drifted from them. This
module centralises those queries on the backend so the server is the single source
of truth: it computes the legal choices and the web layer ships them to the
frontend (see ``web/serialization.py``), which only renders and validates
clicks against the supplied lists.

Two concerns live here:

* Combat legality — ``legal_attacker_indices`` / ``legal_blocker_assignments``
  mirror the acceptance checks in the declare-attackers/blockers steps so the UI
  offers exactly the assignments the engine would accept.
* Target legality — ``cast_target_spec`` / ``activation_target_spec`` classify
  what a spell/ability targets and enumerate every legal target, gating spell
  targets through the engine's own ``_validate_cast_targets`` so protection,
  colour/type filters, and shroud are enforced identically to resolution.

**Neither half reads oracle text to classify a target any more.**
``cast_target_spec`` asks ``engine/targeting.py``, which derives the whole spec
— kind and flags — from the compiled program; ``activation_target_spec`` asks
the same module for the spec of one *ability*, since a permanent may carry
several that target differently. There is one parse of a card and nothing to
keep in sync. What is left here is the *enumeration*: given a spec, which
permanents, players, graveyard cards and stack items satisfy it.

One line shape survives as a text fallback, named and measured in
:data:`_UNDERIVABLE_ABILITY_TARGETS`, because the program genuinely cannot
describe it.
"""

import re

from .handlers._common import (graveyard_card_matches, permanent_matches_filter,
                               state_holds)
from .models import CardDefinition, Permanent
from .alternative_costs import alternative_costs
from .cast_costs import cast_announces_x, costs_charged_from
from .cast_restrictions import timing_fixed_seat
from .cost_x_definitions import (caps_cast_x, cast_x_ceiling,
                                 cast_x_value, defines_cast_x)
from .oracle import compile_card_oracle, expand_ability_lines
from .mana_payment import (mana_cost_from_symbols, plan_payment, total_pips,
                          untapped_mana_lands)
from .oracle_types import cost_target_count
from .static_bonuses import conditional_static_holds
from .subject_filters import card_matches_any, subject_matches
from .modal_triggers import modal_trigger_mode_spec, modal_trigger_modes
from .targeting import (
    GRAVEYARD_TARGET_KIND,
    ROLES_TARGET_KIND,
    derive_activation_spec,
    derive_cast_spec,
    role_relation_holds,
    spec_roles,
    usable_activated_abilities,
)

# An oracle line whose cost is followed by a colon is an activated ability
# (CR 602.1), not a cast-time effect. The cost may mix symbols with prose
# ("{T}, Sacrifice a creature:", "{2}, {T}, Discard the last card you drew this
# turn:"), so after the cost accept anything up to the colon — barring a period,
# which would mean the colon belongs to a later sentence rather than to a cost.
#
# **The cost need not open with a mana symbol.** "Sacrifice this creature:"
# (Selfless Savior) and "Tap two untapped Spirits you control:" (Shacklegeist)
# are activated abilities with no symbol in them at all, and requiring one read
# both as cast-time effects — so a guard asking "does this card name a target as
# it is cast?" answered yes about an ability's target. Two shapes, both anchored:
# a leading symbol, or a leading verb from the closed list of cost actions the
# pool prints. A bare prose prefix is deliberately *not* admitted, because
# "Enchant creature" and a reminder line would join it.
_COST_VERBS = r"sacrifice|tap|discard|exile|pay|remove|return|reveal|untap"
_ACTIVATED_LINE_RE = re.compile(
    r"^\s*(?:\{[^}]+\}|(?:" + _COST_VERBS + r")\b)[^:.]*:", re.I
)


def _oracle_lines(card: CardDefinition) -> list[str]:
    # The same rewrites the compiler applies (Pyramids' modal bullets, the
    # CR 702.6a expansion of an equip line, a legendary card's shortened
    # self-reference written out in full), so the resulting effects classify
    # as activated-ability lines, not cast effects.
    return expand_ability_lines(
        card.oracle_text or "", card_name=card.name, legendary=card.is_legendary
    ).split("\n")


def _cast_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that are *not* activated abilities (cast effects).

    Nothing here classifies a cast target from text any more — the complement of
    :func:`_activated_lines` is kept because the guard that replaced the cascade
    needs the same split to ask "does this card name a target as it is cast?",
    and defining it twice is how the two would come to disagree.
    """
    return [line.lower() for line in _oracle_lines(card) if not _ACTIVATED_LINE_RE.match(line)]


def _activated_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that *are* activated abilities."""
    return [line.lower() for line in _oracle_lines(card) if _ACTIVATED_LINE_RE.match(line)]


def _type_line(card: CardDefinition) -> str:
    return (card.type_line or "").lower()


def cast_target_kind(card: CardDefinition) -> str:
    """The target kind of *card* cast from hand, without enumerating targets.

    Exposed for the web layer's stack serialization, which needs to know which
    zone an already-recorded target index points into — a reanimation spell's
    ``target_permanent_index`` indexes a graveyard, not a battlefield.

    Answered entirely from the compiled program (engine/targeting.py). "none" is
    the answer for a spell that chooses nothing as it is cast, and
    tests/engine/test_targeting.py fails if a card that names a target starts
    answering it.
    """
    return cast_spec_of(card)["kind"]


def cast_spec_of(card: CardDefinition) -> dict:
    """The cast-time target spec of *card* — kind plus the flags that narrow the
    picker — or ``{"kind": "none"}`` when it chooses nothing as it is cast."""
    return derive_cast_spec(card, compile_card_oracle(card)) or {"kind": "none"}


def _cant_be_enchanted_by_auras(perm) -> bool:
    """Aura-derived, printed on the permanent itself, or flagged; one question,
    every source."""
    from .auras import aura_restriction_active, cant_be_enchanted_by_own_text

    return (
        bool(perm.metadata.get("cant_be_enchanted_by_auras"))
        or aura_restriction_active(perm, "cant_be_enchanted_by_auras")
        or cant_be_enchanted_by_own_text(perm)
    )


# ---------------------------------------------------------------------------
# Activated-ability target classification
# ---------------------------------------------------------------------------

# Activated-ability instruction kinds whose payload carries a finer target
# restriction than the kind alone (a tapped/coloured destroy, a non-Wall attack
# mark). The enumerator gates candidates through these so an ability offers
# exactly what it could legally affect, matching its resolution.
def targeting_instruction(instruction):
    """The instruction inside *instruction* that actually names a target.

    An ability's own instruction may be a control-flow wrapper — Lesser
    Werewolf's whole sentence is an ``if_then``, and Hydroblast's two modes are
    each one — and the per-kind filter check below reads the *targeting*
    instruction, so a wrapper handed to it looks like a kind with no filter and
    every restriction the card printed is dropped. The same recursion
    ``engine/targeting.py`` already does to derive the spec: the two must
    agree, or the picker offers what the gate refuses.

    **Public because the web layer asks it too.** `web/serialization.py` derives
    a modal mode's picker kind from the mode's instruction, and it read the kind
    off the wrapper — a second descent that was not one. A mode wrapped in an
    `if_then` fell past every branch of that table to its "designates a player"
    default, so Hydroblast would have offered a *player* as the target of
    "counter target spell". One reader, asked twice, is what stops the picker
    and the gate describing different cards.
    """
    from .targeting import _nested_steps

    if instruction is None:
        return None
    # **What names a target, not which kinds someone listed.** This was a
    # frozen set of thirteen instruction kinds — the same thirteen
    # `_ability_target_legal` branched on, written out a second time — so a
    # kind absent from it returned None here and the filter was dropped one
    # step *before* the check that would have applied it. That is why Grapeshot
    # Catapult's "target creature with flying" offered every creature in the
    # browser even once the check below could answer it: two copies of one
    # list, and the earlier copy decided.
    #
    # An instruction that carries a `targets` description is one that names a
    # target, whatever its kind — a payload *shape*, not a card list. The set
    # below stays because four kinds narrow without one (Stone Giant's
    # "toughness less than this creature's power", Old Man of the Sea's power
    # comparison, Sorceress Queen's "other than this creature", Nettling Imp's
    # non-Wall): each is a relation to the *source* rather than a description of
    # the target, so it has a branch of its own below and nothing in `targets`
    # to find it by. Dwarven Warriors' "power 2 or less" left the list when it
    # stopped being a relation and became a filter payload — a bound printed on
    # the card is a description of the target like any other.
    if instruction.kind in _FILTERABLE_ABILITY_KINDS:
        return instruction
    if isinstance(instruction.payload.get("targets"), dict):
        return instruction
    for step in _nested_steps(instruction):
        found = targeting_instruction(step)
        if found is not None:
            return found
    return None


_FILTERABLE_ABILITY_KINDS = {
    "add_counter_to_target",
    "destroy_target_permanent",
    "grant_regeneration_to_target_creature",
    "mark_non_wall_target_to_attack",
    "grant_flying_and_delayed_destruction",
    "set_base_pt_target_until_eot",
    "set_source_base_pt_from_target",
    "steal_creature_while_tapped_and_weaker",
    "steal_target_linked_to_source",
    "tap_target_permanent",
    "attach_source_to_target",
    "produce_mana_instead",
}


# What is left of the shadow parser: line shapes whose *compiled program* cannot
# say what they target, matched against the ability's own line.
#
# "Untap target creature" (Jandor's Saddlebags) lowers to
# `untap_target_permanent`, whose handler untaps whatever it is handed —
# `_tap_or_untap_target` passes `predicate=lambda p: True`. The grammar already
# refuses to lower a restricted untap onto that kind for exactly this reason
# ("no untap handler honors this restriction", engine/grammar/lower.py), so the
# instruction reaches here with an empty payload. Deriving "permanent" off the
# kind would be honest about the handler and wrong about the card: the UI would
# offer lands for an ability that may only untap a creature, and the handler
# would untap the land. So the derivation refuses, and this reads the line.
#
# It goes away when that handler honours its filter — at which point the
# grammar lowers the line with its restriction, the derivation answers, and
# tests/engine/test_activation_targeting.py fails on this entry being stale.
#: Empty, and that is the whole point: this was the last of the shadow parser on
#: the activation side. Its one entry covered "untap target creature", which the
#: grammar refused to lower because ``untap_target_permanent`` ignored filters —
#: so deriving "creature" off the instruction kind would have offered lands.
#: Round 98 taught that handler its noun phrase, the grammar lowers the line, and
#: the derivation answers from the compiled program like everything else.
#:
#: A new entry here is a claim that a program *genuinely cannot* describe what a
#: line targets. Keep it empty if you can.
_UNDERIVABLE_ABILITY_TARGETS: tuple[tuple[re.Pattern, dict], ...] = ()



def _fallback_activation_spec(source_line: str) -> dict | None:
    """The spec of an ability line the compiled program cannot describe."""
    lowered = (source_line or "").lower()
    for pattern, spec in _UNDERIVABLE_ABILITY_TARGETS:
        if pattern.search(lowered):
            return dict(spec)
    return None


def _activation_spec(abilities) -> tuple[dict, object | None]:
    """The spec of the first of *abilities* that chooses anything, with the
    ability it came from.

    Called with one ability when the UI named which one is being activated, and
    with all of a permanent's usable abilities for the default prompt a
    single-ability permanent shows. Scanning in order is what makes the two
    agree: a mana ability chooses nothing, so Desert's default prompt is its
    damage ability's, exactly as it was when a per-card cascade produced it.
    """
    for ability in abilities:
        spec = derive_activation_spec(ability)
        if spec is None:
            spec = _fallback_activation_spec(getattr(ability, "source_line", ""))
        if spec is not None:
            return spec, ability
    return {"kind": "none"}, None


_TARGET_STEP_KEYS = ("steps", "then", "else", "action", "otherwise", "effect")


#: Instruction kinds that target an object but carry no ``targets`` quantifier
#: in their payload (the derivation encodes the target elsewhere). Only banding
#: today; kept as a set so a second such kind is one entry, not a second branch.
#: Kinds whose target is mandatory although no ``targets`` quantifier rides
#: their payload. ``counter_stack_ability`` names its object in a noun phrase
#: the stack lowering reads into ``ability_kinds`` rather than into a targets
#: description, so without this row Ayesha Tanaka could be tapped with an empty
#: stack — the cost paid for a counter that had nothing to counter.
#: The graveyard kinds are the same row for the same reason, one zone over: a
#: card in a graveyard is named by the noun phrase the graveyard lowering reads
#: into ``card_type``/``card_types``/``any_card``, and no ``targets``
#: description rides beside it. Without them **every** graveyard-targeting
#: ability in the pool was activatable with every graveyard empty — Adun
#: Oakenshield and Argivian Archaeologist tapped for nothing, Obsessive
#: Stitcher and Triassic Egg *sacrificed themselves* for nothing — which is the
#: precise failure this gate replaced a per-kind if-chain to end, still live in
#: the one family the if-chain had never named.
_QUANTIFIERLESS_TARGET_KINDS = frozenset({
    "grant_banding_to_target", "counter_stack_ability",
    "reanimate_creature", "reanimate_creature_to_battlefield",
    "reanimate_aura_onto_source",
    "return_creature_from_graveyard_to_hand", "exile_target_graveyard_card",
    "put_graveyard_card_on_library_bottom", "put_graveyard_cards_on_library_top",
})

#: Target kinds ``illegal_targets_refusal`` declines to answer for, because a
#: *player* may be among the chosen targets and a player target reaches the
#: stack item through the same field as the seat a permanent target sits on.
#: "Every target is illegal" is unanswerable where the two cannot be told
#: apart, and a wrong "yes" there counters a spell that still has a legal
#: target — strictly worse than the rule going unenforced for those kinds.
#: ``none``/``modal``/``hand_card`` are in it for the plainer reason: they are
#: not object targets at all.
_UNFIZZLABLE_TARGET_KINDS = frozenset({
    "none", "modal", "hand_card",
    "player", "any", "divided", "player_or_planeswalker",
})

#: Target kinds ``cast_target_refusal`` leaves to the per-kind arms in
#: ``_validate_cast_targets``. A named index means something different in each
#: of them — a position in the stack, a card in hand — while the battlefield
#: enumeration this gate compares against is a battlefield slot, so comparing
#: the two would refuse legal casts rather than illegal ones. A **graveyard**
#: index used to hide here too, and hiding it was the laxity rather than the
#: safety: the arms key on the *primary* instruction kind, so a spell whose
#: graveyard targeting sits inside a ``sequence`` (Fungal Rebirth,
#: Experimental Overload) reached no arm and an announcement naming an
#: opponent's pile was accepted and silently re-pointed at the caster's own.
#: The gate now has a graveyard branch of its own, compared against the
#: ``graveyard``-kind entries the same enumeration emits.
_UNCHECKED_CAST_TARGET_KINDS = frozenset({
    "none", "modal", "hand_card", "stack",
    "spell_or_permanent",
})


def _ability_target_quantifiers(instruction) -> list[str]:
    """Every *mandatory-context* ``targets`` quantifier this ability carries.

    Walks only the unconditional ``sequence`` steps, never a conditional branch
    (``then``/``else``/``action``): a target inside "if you lose the flip,
    counter target artifact spell" (Goblin Artisans) is not chosen at
    activation, so an empty stack must not make the *whole* ability
    unactivatable — the draw before the flip always happens. Basri Ket's "up to
    one target creature" sits directly in the sequence, so it is seen (and, as
    an "up_to", does not make a target mandatory).

    A **counted** announcement is mandatory too, and reported as "target" here
    so the one caller keeps one word to test. "Choose **two** target blocked
    attacking creatures" (General Jarkeld) parses as ``exactly`` with a count of
    two, which is CR 601.2c's "the announcement is illegal unless every target
    can be chosen" just as plainly as the singular word is — and left out, the
    gate returned None and the ability was activatable naming a creature nobody
    was blocking. A count read off X ("X target lands", Candelabra of Tawnos) is
    deliberately *not* mandatory: X may legally be announced as zero, and there
    is then nothing to target."""
    quantifiers: list[str] = []

    def walk(instr) -> None:
        if instr is None:
            return
        payload = getattr(instr, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and "quantifier" in targets:
            quantifier = targets.get("quantifier")
            count = targets.get("count")
            if quantifier == "exactly" and isinstance(count, int) and count >= 1:
                quantifier = "target"
            quantifiers.append(quantifier)
        elif getattr(instr, "kind", None) in _QUANTIFIERLESS_TARGET_KINDS:
            # A kind whose target rides somewhere other than a ``targets``
            # description — and only where the description is genuinely absent,
            # which is what "quantifierless" means. Liliana, Death Mage's "+1:
            # Return **up to one** target creature card from your graveyard"
            # lowers the same graveyard kind *with* a quantifier, and CR 601.2c
            # lets an "up to" announcement name none: reading the kind first
            # would have made her +1 unusable with an empty graveyard.
            #
            # Asked here rather than of the top instruction alone, which is how
            # Grave Robbers and Scavenging Ooze — whose graveyard exile is the
            # first step of a printed two-sentence ``sequence`` — answered
            # "chooses nothing" while their single-sentence siblings answered
            # correctly.
            quantifiers.append("target")
        for step in payload.get("steps") or ():
            walk(step)

    walk(instruction)
    return quantifiers


class LegalityMixin:
    """Backend legality queries surfaced to the web UI. Composed onto ``Game``."""

    # -- Combat ------------------------------------------------------------
    def is_unblockable(self, perm: Permanent) -> bool:
        """Whether *perm* is a creature that can't be blocked by ANY creature —
        i.e. genuinely unblockable, not merely evasive. Dwarven Warriors' granted
        "can't be blocked this turn" (``cant_be_blocked_until_eot``) and any inherent
        "can't be blocked" text qualify; conditional evasion (flying, fear, landwalk,
        "except by Walls") does not, since some creature could still block it. The UI
        reads this to tag and fade the creature."""
        if not self._is_creature(perm):
            return False
        if perm.metadata.get("cant_be_blocked_until_eot"):
            return True
        seat = self.controller_index_of(perm)
        return any(
            i.kind == "cant_be_blocked"
            # "…as long as <condition>" (Tome Anima): unblockable exactly
            # while the condition holds, so the UI tag tracks the state.
            or (
                i.kind == "conditional_static"
                and i.payload.get("cant_be_blocked")
                and seat is not None
                and conditional_static_holds(self, seat, perm, i.payload.get("condition") or {})
            )
            for i in compile_card_oracle(perm.effective_card).instructions
        )

    def opponents_of(self, player_index: int) -> list[int]:
        """Every other player still in the game (CR 800.4a: a player who has left
        the game is no longer anyone's opponent). In a 2-player game this is just
        the other seat; in a 3+ player (Free-For-All) game it's every living seat
        but this one."""
        return [
            i for i, p in enumerate(self.players)
            if i != player_index and not p.lost
        ]

    def legal_attacker_indices(self, attacker_index: int, against: int | None = None) -> list[int]:
        """Battlefield indices of creatures that may legally be declared as
        attackers this turn — untapped, not summoning sick, and allowed to attack
        an opponent (mirrors the declare-attackers acceptance checks).

        When ``against`` is given, mirrors the original single-opponent behavior
        exactly (legal against that one specific opponent). When omitted, returns
        creatures legal against ANY living opponent — the union view a 3+ player
        UI needs before the player has picked which opponent to attack."""
        player = self.players[attacker_index]
        opponents = [against] if against is not None else self.opponents_of(attacker_index)
        return [
            idx
            for idx, perm in enumerate(player.battlefield)
            # _is_creature so animated lands (Kormus Bell, Living Lands) are offered.
            if self._is_creature(perm)
            and not perm.tapped
            and not self._is_summoning_sick(perm)
            and any(self.can_attack(perm, opp) for opp in opponents)
        ]

    def legal_blocker_assignments(self, defender_index: int) -> list[dict[str, int]]:
        """Every legal ``{"blocker_index", "attacker_index"}`` pair for the
        defending player, mirroring ``declare_blockers`` acceptance (creature,
        untapped, ``_can_block_attacker``, and Raging River pile restrictions)."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return []
        if defender_index not in self.combat_defending_players():
            return []
        # Camouflage replaces blocker declaration with pile assignment, so there
        # are no individually declarable blocker→attacker pairs this combat.
        if self.is_camouflage_active() and self.combat_attackers:
            return []
        defender = self.players[defender_index]
        attacker_controller = self.players[self.active_player_index]
        pairs: list[dict[str, int]] = []
        for blocker_idx, blocker in enumerate(defender.battlefield):
            # is_creature so animated lands (Kormus Bell, Living Lands) may block.
            if not blocker.is_creature or blocker.tapped:
                continue
            # CR 802.4a: this defender can only block attackers aimed at them.
            for attacker_idx, defending_idx in self.combat_attackers.items():
                if defending_idx != defender_index:
                    continue
                if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                    continue
                attacker = attacker_controller.battlefield[attacker_idx]
                if not self._can_block_attacker(blocker, attacker):
                    continue
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    continue
                pairs.append({"blocker_index": blocker_idx, "attacker_index": attacker_idx})
        return pairs

    # -- Targeting ---------------------------------------------------------
    def cast_target_spec(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        from_zone: str = "hand",
        spell_hand_index: int | None = None,
        optional_cost_payments: dict[str, int] | None = None,
    ) -> dict:
        """Target spec for casting ``card`` from ``caster_index``'s *from_zone*:
        the target kind plus every legal target, enumerated and gated through the
        engine's own cast-target validation so the UI offers exactly what would
        resolve.

        ``from_zone`` is the zone the cast would leave, because a printed
        additional cost may name one (Demonic Embrace's graveyard price) and the
        picker has to charge what the payment path will charge — the same test
        ``queue_from_hand`` makes.

        ``optional_cost_payments`` is CR 601.2b's answer **so far** — the offers
        the caster has already accepted. It is what makes this spec re-askable:
        the offer ceilings below are computed against it, and so is CR 601.2c's
        target count for the one shape whose count a payment decides (Primitive
        Justice destroys one artifact, plus another for each {1}{R} and each
        {1}{G} paid). ``spell_hand_index`` is which copy is being cast, needed
        for the same reason CR 601.2a is: a spell cannot be exiled to pay for
        itself, and a second copy in hand can."""
        # Modal "Choose one —" spells choose a mode first; each mode carries its
        # own target spec (filled in by the web layer per mode), so report "modal"
        # and let the UI run its mode-choice flow rather than enumerating here.
        program = compile_card_oracle(card)
        if len(program.modes) >= 2:
            return {"kind": "modal", "requires_target": False, "valid_targets": []}
        # The compiled program answers in full — the kind *and* the flags that
        # narrow the picker (own_only, stack filters, sacrifice_cost, ...).
        # There is no text cascade behind this any more: a program that
        # describes no cast-time choice means the spell makes none.
        spec = derive_cast_spec(card, program, from_zone=from_zone) or {"kind": "none"}
        spec["requires_target"] = spec["kind"] != "none"
        # CR 107.3c: a spell that defines its own X takes the announcement away
        # from the caster, so the picker must not ask for one — and a divided
        # spell's caster needs the number *before* announcing the division
        # (CR 601.2d), which is exactly what a browser that had asked for X
        # would have got wrong. Answered here rather than in the browser because
        # the definition counts a graveyard, which only the game can read.
        if defines_cast_x(card.oracle_text):
            defined = cast_x_value(self, caster_index, card.oracle_text)
            if defined is not None:
                spec["defined_x"] = defined
        # CR 601.2b's bound, the other half of the same question: the caster
        # still announces X and this is the largest legal answer (Winter's
        # Chill). Reported here for ``defined_x``'s reason — the number counts
        # a board only the game can read — so the picker offers what the cast
        # path would accept rather than a range it will then refuse.
        if caps_cast_x(card.oracle_text):
            bound = cast_x_ceiling(self, caster_index, card.oracle_text)
            spec["max_x"] = 0 if bound is None else bound[0]
        # CR 107.3a's *other three* places an X can live. The browser asked only
        # the mana-cost string, so Fire Covenant ({1}{B}{R}, "pay X life") and
        # Infernal Harvest ({1}{B}, "return X Swamps") were offered no X box at
        # all and cast at CR 107.3b's 0 -- legal and useless. Reported as a flag
        # rather than left to a substring probe for the reason `defined_x` is:
        # what a card's costs say is the compiler's answer, not the client's.
        if cast_announces_x(card, from_zone=from_zone):
            spec["announces_x"] = True
            # And the ceiling that goes with it, which the mana pool cannot
            # supply because this X is not paid in mana: a life total (CR 119.4)
            # or a board of Swamps (CR 601.2h). The same numbers
            # `_unpayable_additional_cost` refuses above, so the picker offers
            # exactly what the cast would accept.
            bound = self._additional_cost_x_ceiling(
                caster_index, card, from_zone=from_zone
            )
            if bound is not None:
                spec["max_x"] = (
                    bound if spec.get("max_x") is None
                    else min(int(spec["max_x"]), bound)
                )
        # CR 601.2b's *optional* prices, and how many times each is payable
        # against the answer so far. The picker had no shape for an offer at
        # all — it modelled a cost the caster will certainly pay — so every card
        # printing one was castable at its printed default and at no other
        # price.
        offers = self.cast_cost_offers(
            caster_index, card, from_zone=from_zone,
            spell_hand_index=spell_hand_index, taken=optional_cost_payments,
        )
        if offers:
            spec["cost_offers"] = offers
        # CR 601.2c's count, once CR 601.2b has been answered. The arithmetic
        # lives in ``oracle_types.cost_target_count`` because the grammar writes
        # the description, this turns it into a picker size and
        # ``_validate_cast_targets`` gates the announcement against it — three
        # readers of one pair of dict keys, which is why none of them owns the
        # sum. Emitted as an ordinary ``max_targets`` so the several-target
        # picker has to know nothing about costs.
        sized = cost_target_count(spec.get("cost_targets"), optional_cost_payments)
        if sized is not None and sized > 1:
            spec["max_targets"] = sized
        if spec["kind"] == ROLES_TARGET_KIND:
            # A spell whose targets are of *different kinds*, chosen in
            # dependency order (CR 601.2c). ``valid_targets`` is role 0's list —
            # the shape every caller downstream already reads, so "does this
            # spell have a legal target at all?" keeps working — and each entry
            # carries under ``next`` the targets the later roles would then
            # allow. One walk, so what the browser offers and what
            # ``_validate_cast_targets`` accepts come from the same call.
            spec["valid_targets"] = self._role_target_walk(
                caster_index, card, spec, (), for_cast=True
            )
            return spec
        spec["valid_targets"] = self._enumerate_targets(caster_index, card, spec, for_cast=True)
        # Demonic Embrace, Goblin Grenade, Soul Exchange: a spell with a target
        # *and* a choosable cost carries two pickers, each enumerating its own
        # candidates — the cost over the caster's own cards with no targeting
        # legality, the target through everything above. The activation side has
        # answered this way since Dwarven Weaponsmith; the cast side used to
        # answer with the cost alone, which is how the target went unasked.
        if spec.get("cost_spec"):
            cost_spec = dict(spec["cost_spec"])
            cost_spec["valid_targets"] = self._enumerate_targets(
                caster_index, card, cost_spec, for_cast=True,
            )
            spec["cost_spec"] = cost_spec
        # "Any number of target …" (Drafna's Restoration) prints no maximum, so
        # the cap is however many legal targets there are — a number that exists
        # here and nowhere earlier. Filled in as an ordinary `max_targets` so
        # every reader downstream sees the shape it already handles.
        if spec.pop("unbounded_targets", False):
            spec["max_targets"] = len(spec["valid_targets"])
        return spec

    def cast_cost_offers(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        from_zone: str = "hand",
        spell_hand_index: int | None = None,
        taken: dict[str, int] | None = None,
    ) -> list[dict]:
        """Every *optional* price CR 601.2b lets the caster announce for *card*,
        with what each one costs and how many times it is payable.

        The two optional cost kinds this engine has grown, described in one
        vocabulary because the browser asks one question about them ("what are
        you paying for this?"):

        * **CR 118.9's alternative cost** -- "You may pay 1 life and exile a blue
          card from your hand rather than pay this spell's mana cost." Taken or
          not; the exile half names a card, so the cards that answer it are
          enumerated here through ``_alternative_cost_payers``, the same list the
          payment picks from.
        * **CR 601.2b's optional additional mana** -- "you may pay {1}{R} and/or
          {1}{G} any number of times." Taken any number of times, *independently*
          per offer (Primitive Justice prints two), which is why ``times`` is a
          map and not a count.

        ``taken`` is the answer so far, and the ceilings are computed against it:
        raising one offer spends mana the others can no longer have. A client
        that re-asks after each click therefore gets a ceiling that is true
        jointly, rather than three standalone maxima that cannot all be taken.

        **The ceiling is computed from the pool and the board**, through
        ``plan_payment`` -- the same matching the payment itself runs, so an
        offer this shows as payable is one the cast will accept. It reads the
        *printed* mana cost: a CR 601.2f increase in force would make the number
        optimistic, and an optimistic offer is refused by the payment with
        nothing spent, where a pessimistic one silently withholds a price the
        player could afford.
        """
        caster = self.players[caster_index]
        answered = {str(key): int(value) for key, value in (taken or {}).items()}
        offers: list[dict] = []

        for cost in alternative_costs(card):
            entry: dict = {
                "kind": "alternative",
                "label": cost.describe(),
                "payable": self._unpayable_alternative_cost(
                    caster_index, card, cost, spell_hand_index=spell_hand_index,
                ) is None,
            }
            if cost.exile_from_hand is not None:
                payers = self._alternative_cost_payers(
                    caster_index, cost, spell_hand_index=spell_hand_index,
                )
                # By hand *position*, because that is what the wire carries and
                # what CR 601.2a's withholding is expressed in: a deck repeats
                # one immutable definition per copy, so two copies of one card
                # in hand are the same Python object and only the index tells
                # the spell apart from the card paying for it.
                entry["hand_choices"] = [
                    {"index": position, "name": held.name}
                    for position, held in enumerate(caster.hand)
                    if position != spell_hand_index
                    and any(held is payer for payer in payers)
                ]
            offers.append(entry)
            # CR 118.9a: only one alternative cost may be applied, and
            # ``_resolve_alternative_cost`` refuses a card printing two rather
            # than choosing for the player. Offering both would be this picker
            # describing an announcement the engine will not accept.
            break

        every_offer = [
            offer
            for cost in costs_charged_from(card, from_zone)
            for offer in cost.optional_mana
        ]
        if not every_offer:
            # Before reading the board at all: this runs for every card in every
            # hand on every poll, and all but three cards in the pool print no
            # optional mana cost.
            return offers
        pool = dict(caster.mana_pool)
        lands = untapped_mana_lands(self.controlled_by(caster_index))
        printed = mana_cost_from_symbols(card.mana_cost or "") or {}
        for offer in every_offer:
            one = offer.cost
            # What the rest of the announcement has already claimed, so the
            # ceilings cannot each promise the same mana.
            floor = dict(printed)
            for other in every_offer:
                if other.symbols == offer.symbols:
                    continue
                for symbol, amount in other.cost.items():
                    floor[symbol] = floor.get(symbol, 0) + amount * answered.get(
                        other.symbols, 0
                    )
            reachable = sum(pool.values()) + len(lands)
            ceiling = (
                max(1, reachable // max(1, total_pips(one))) if offer.repeatable else 1
            )
            payable = 0
            for times in range(ceiling, 0, -1):
                required = dict(floor)
                for symbol, amount in one.items():
                    required[symbol] = required.get(symbol, 0) + amount * times
                if plan_payment(pool, lands, required) is not None:
                    payable = times
                    break
            offers.append({
                "kind": "optional_mana",
                # The canonical spelling ``mana_cost_label`` produces, which is
                # the key ``optional_cost_payments`` is read back by -- so what
                # the browser sends and what ``cost_target_count`` counts are the
                # same string, however the card printed it.
                "symbols": offer.symbols,
                "label": offer.symbols,
                "repeatable": offer.repeatable,
                "max_times": payable,
                "times": answered.get(offer.symbols, 0),
            })
        return offers

    def _additional_cost_x_ceiling(
        self, caster_index: int, card: CardDefinition, *, from_zone: str,
    ) -> int | None:
        """The largest X the printed additional costs of *card* leave payable,
        or None when no printed cost names one.

        CR 107.3a lets the caster announce any X; CR 601.2h then refuses the
        cast when the announcement prices a cost they cannot pay. So the
        announcement has a ceiling, and it is *not* the mana pool: Fire
        Covenant's X is paid in life (CR 119.4 caps a life payment at the life
        total) and Infernal Harvest's in Swamps (there is no fifth Swamp to
        return off a board of four). The picker reads it so the browser offers
        exactly the range ``_unpayable_additional_cost`` would accept -- the
        picker-and-gate pairing this engine keeps having to re-establish, here on
        the half where disagreement means a cast announced and then refused.

        The minimum across every X-bearing cost, because one cast pays all of
        them: a card printing "pay X life **and** return X Swamps" is priced by
        whichever runs out first. No card prints two today; the minimum is what
        makes that a fact about the pool rather than an assumption in the code.
        """
        caster = self.players[caster_index]
        charged = costs_charged_from(card, from_zone)
        # CR 601.2b's printed life prices are paid out of the same total, so
        # they are claimed before the announced one is offered a ceiling --
        # the arithmetic ``_unpayable_additional_cost``'s ``life_already_owed``
        # does one step later, for the same reason.
        fixed_life = sum(cost.pay_life for cost in charged)
        bounds: list[int] = []
        for cost in charged:
            if cost.pay_life_x:
                bounds.append(max(0, caster.life - max(0, fixed_life)))
            if cost.return_count_x:
                bounds.append(len(self._additional_cost_candidates(
                    caster_index, cost, giving_up="return",
                )))
        return min(bounds) if bounds else None

    # -- Several targets of different kinds (CR 601.2c) ---------------------
    def role_target_options(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: tuple, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> list[dict]:
        """Every legal target for the **next** role, given the roles already
        chosen - and the whole of what makes a roles spell safe.

        One call, and it is both the gate and the picker: ``cast_target_spec``
        walks it to build the list the browser offers, and
        :meth:`_validate_cast_targets` walks the same call over the targets a
        caster actually named. That is the shape ``trigger_mode_options``
        already has, and it is here for the reason CLAUDE.md keeps naming - a
        picker and a gate with two tables between them is this engine's
        recurring defect, and on a *target* list the failure is a spell cast at
        something nothing ever checked.

        Two narrowings live here and nowhere else, because neither is a
        property of one permanent:

        * **the dependency.** "target creature that **target Wall** blocked
          this turn" - which creatures are legal at all is decided by the block
          record on the Wall already chosen. ``subject_matches`` answers about a
          candidate alone and could never see it.
        * **CR 601.2c distinctness.** The same object can't be chosen for two
          targets of one spell unless the spell says otherwise, so a permanent
          already taken by an earlier role is not offered to a later one.

        Returns [] once every role is chosen, which is what ends the walk.
        """
        roles = spec_roles(spec)
        if len(chosen) >= len(roles):
            return []
        role = roles[len(chosen)]
        # ``for_cast=False`` even for a spell, and that is not a loosening.
        # The cast-time probe inside ``_enumerate_targets`` re-enters
        # ``_validate_cast_targets`` with **one** slot, which for a roles spell
        # is an incomplete announcement — so it would refuse every candidate,
        # and the recursion would be asking the whole-announcement gate a
        # question about a single permanent. The narrower path applies
        # ``_can_be_targeted``: the identical CR 702.16b/702.11b/shroud check
        # the cast gate runs over the targets a caster names, plus Wall of
        # Shadows' "abilities that can target only Walls" question, which it can
        # answer here because the role *is* the spec.
        candidates = self._enumerate_targets(
            caster_index, card, role, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent, ability_source=ability_source,
        )
        taken = {id(perm) for perm in chosen if perm is not None}
        related = self._role_relation_test(role, roles, chosen)
        options: list[dict] = []
        for candidate in candidates:
            perm = self.permanent_at(candidate.get("seat"), candidate.get("index"))
            if perm is None or id(perm) in taken:
                continue
            if related is not None and not related(perm):
                continue
            options.append({**candidate, "role": role.get("role")})
        return options

    def _role_relation_test(self, role: dict, roles: list[dict], chosen: tuple):
        """The predicate *role*'s dependency imposes, or None when it has none.

        The relation itself is ``engine/targeting.ROLE_RELATION_TESTS``, which
        the resolution's CR 608.2b re-check reads too — the picker, this gate
        and that re-check are three questions about one relation, and this repo
        keeps finding the bug where they were three tables.

        A dependency that table does not implement offers **nothing**, never
        everything: an unanswerable narrowing must refuse, the same direction
        ``defending_player_only`` takes in the enumerator below. A role whose
        earlier target has not been chosen — or has left the battlefield — is
        in that same position, which ``role_relation_holds`` answers the same
        way.
        """
        if role.get("relation") is None:
            return None
        earlier_index = next(
            (
                index for index, entry in enumerate(roles)
                if entry.get("role") == role.get("depends_on")
            ),
            None,
        )
        earlier = (
            chosen[earlier_index]
            if earlier_index is not None and earlier_index < len(chosen)
            else None
        )
        return lambda perm: role_relation_holds(role, earlier, perm, self)

    def _role_target_walk(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: tuple, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> list[dict]:
        """The whole choice tree of a roles spell **or ability**, depth-first.

        Each entry is one legal target for the current role with the entries
        legal *after* it under ``next`` - so the browser can walk the roles in
        one payload rather than asking the server again between clicks, and so
        a role 0 candidate that leaves role 1 with nothing to choose is visible
        as an empty ``next`` rather than as a dead end discovered mid-prompt.

        The three ability keywords are carried, not defaulted away: an
        *activated* ability's roles (Sorrow's Path's two blockers) are
        enumerated with the same source-permanent and instruction narrowing
        every one-target ability gets, and a walk that dropped them would offer
        a list the activation gate then refuses.
        """
        options = self.role_target_options(
            caster_index, card, spec, chosen, for_cast=for_cast,
            source_permanent=source_permanent,
            ability_instruction=ability_instruction,
            ability_source=ability_source,
        )
        walked: list[dict] = []
        for option in options:
            perm = self.permanent_at(option.get("seat"), option.get("index"))
            following = self._role_target_walk(
                caster_index, card, spec, chosen + (perm,), for_cast=for_cast,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=ability_source,
            )
            if not following and len(chosen) + 1 < len(spec_roles(spec)):
                # CR 601.2c: every target of the spell is chosen, so a first
                # choice that leaves a later role with no legal object is not a
                # legal first choice at all. Dropped here rather than offered
                # and refused after the click.
                continue
            walked.append({**option, "next": following})
        return walked

    def _role_targets_legal(
        self, caster_index: int, card: CardDefinition, spec: dict,
        chosen: list, *, for_cast: bool, source_permanent=None,
        ability_instruction=None, ability_source=None,
    ) -> bool:
        """Whether *chosen* - one permanent per role, in role order - is a legal
        announcement, asked through the very list the picker was built from."""
        roles = spec_roles(spec)
        if len(chosen) != len(roles) or any(perm is None for perm in chosen):
            return False
        for index in range(len(roles)):
            options = self.role_target_options(
                caster_index, card, spec, tuple(chosen[:index]), for_cast=for_cast,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=ability_source,
            )
            if not any(
                self.permanent_at(option.get("seat"), option.get("index"))
                is chosen[index]
                for option in options
            ):
                return False
        return True

    def enumerate_targets_for_kind(self, caster_index: int, card: CardDefinition, kind: str, **flags) -> list[dict]:
        """Enumerate legal targets for a pre-classified target ``kind`` (used by the
        web layer to fill in valid targets for each mode of a modal spell, whose
        kind is derived from the chosen mode's instruction rather than card text)."""
        spec = {"kind": kind, **flags}
        return self._enumerate_targets(caster_index, card, spec, for_cast=False)

    def activation_target_spec(
        self, controller_index: int, permanent_index: int, ability_index: int | None = None
    ) -> dict:
        """Target spec for activating the ability of the permanent at
        ``permanent_index`` on ``controller_index``'s battlefield: the target
        kind plus every legal target. With ``ability_index`` (multi-ability
        cards whose abilities target differently — Pyramids), the spec is that
        one ability's; without it, the first ability that chooses anything.

        Derived from the compiled program (engine/targeting.py), per ability
        rather than per card — the question "what does this ability target?" has
        one answer per ability and a card-level classifier could only give one
        answer for all of them."""
        player = self.players[controller_index]
        if not (0 <= permanent_index < len(player.battlefield)):
            return {"kind": "none", "requires_target": False, "valid_targets": []}
        source_permanent = player.battlefield[permanent_index]
        # effective_card so a copy (Clone / Vesuvan Doppelganger) offers the
        # copied creature's activated abilities (CR 707.2).
        card = source_permanent.effective_card
        usable = usable_activated_abilities(compile_card_oracle(card))
        if ability_index is not None:
            usable = usable[ability_index:ability_index + 1] if 0 <= ability_index < len(usable) else []
        spec, spec_ability = _activation_spec(usable)
        # A Sleight of Mind text change retargets a color-word counter
        # (Lifeforce black -> red) with no step here: the spec was derived from
        # the effective card, whose text layer 3 already rewrote, so the UI is
        # offered the new colour's spells by construction.
        # The narrowing the *spec* does not carry, taken from the same ability's
        # instruction: Royal Assassin's tapped-only, King Suleiman's subtype,
        # Pyramids' "attached to a land". Reading it off the ability that
        # supplied the spec is what keeps a two-ability permanent from narrowing
        # one ability's prompt with the other ability's filter.
        ability_instruction = targeting_instruction(
            getattr(spec_ability, "instruction", None)
        )
        spec["requires_target"] = spec["kind"] != "none"
        if spec["kind"] == ROLES_TARGET_KIND:
            # An **ability** whose targets are of different kinds, chosen in
            # dependency order (CR 602.2b reaches CR 601.2c). The same walk the
            # cast side runs, and it has to be the same one: `_enumerate_targets`
            # has no arm for a roles spec, so an ability described this way was
            # handed an empty list and refused for want of a target it could
            # not enumerate.
            spec["valid_targets"] = self._role_target_walk(
                controller_index, card, spec, (), for_cast=False,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=source_permanent,
            )
            return spec
        spec["valid_targets"] = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent,
            # The *ability's* targets, which is a narrower claim than
            # "source_permanent is set": the cost picker below is handed the
            # same permanent and chooses no target at all (CR 601.2b), and Jade
            # Monolith's source picker chooses a source rather than a target.
            ability_source=source_permanent,
        )
        # Dwarven Weaponsmith: an ability with a target *and* a choosable cost
        # carries two pickers, and each enumerates its own candidates — the cost
        # over the payer's own permanents with no targeting legality, the target
        # through everything above.
        if spec.get("cost_spec"):
            cost_spec = dict(spec["cost_spec"])
            cost_spec["valid_targets"] = self._enumerate_targets(
                controller_index, card, cost_spec, for_cast=False,
                source_permanent=source_permanent,
            )
            spec["cost_spec"] = cost_spec
        # Jade Monolith's second choice — the damage source: any permanent on
        # either battlefield or any spell on the stack.
        if spec.get("requires_source"):
            spec["source_targets"] = self._enumerate_targets(
                controller_index, card, {"kind": "permanent", "also_stack": True},
                for_cast=False,
            )
        return spec

    def trigger_mode_options(
        self, controller_index: int, card: CardDefinition, instruction, source_permanent=None,
    ) -> list[dict]:
        """Every mode of a modal triggered ability that *can* be chosen, each
        with the targets it could choose (CR 700.2b, CR 603.3c/603.3d).

        One call, asked at the one moment the rule allows the choice — as the
        ability is put on the stack — and asked by **both** halves of that
        moment: ``_choose_trigger_mode`` reads it to decide whether the ability
        may go on the stack at all (an empty list means no mode is legal, and
        the ability is removed), and the prompt it arms offers exactly these
        entries. That is the same shape ``activation_target_refusal`` already
        gives an activated ability, and for the same reason: a gate and a
        picker with two tables between them is this engine's recurring defect.

        A mode that targets and has no legal target is **omitted**, not offered
        and refused — CR 700.2b says it "can't be chosen". A mode that targets
        nothing is always choosable and carries an empty candidate list.

        The candidates come from ``_enumerate_targets``, so a mode is offered
        the same list an activated ability with that same effect would be — the
        protection, shroud and per-kind narrowing all included.
        """
        options: list[dict] = []
        for index, mode in enumerate(modal_trigger_modes(instruction)):
            mode_instruction = mode["instruction"]
            spec = dict(modal_trigger_mode_spec(mode) or {"kind": "none"})
            spec["requires_target"] = spec["kind"] != "none"
            valid = self._enumerate_targets(
                controller_index, card, spec, for_cast=False,
                ability_instruction=targeting_instruction(mode_instruction),
                source_permanent=source_permanent,
                ability_source=source_permanent,
            )
            if spec["requires_target"] and not valid:
                continue
            options.append({
                "index": index,
                "label": mode["label"],
                "instruction": mode_instruction,
                "spec": spec,
                "valid_targets": valid,
            })
        return options

    def activation_target_refusal(
        self, controller_index: int, source_permanent, ability, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, target_stack_item=None,
    ) -> str | None:
        """CR 602.2b/601.2c enforced once, before any cost is paid: an ability
        that targets cannot be activated unless a legal target exists, and a
        *named* target must itself be legal.

        The same ``valid_targets`` the web picker is handed (engine derives it
        from the compiled program), so the list offered and the list enforced
        are one list. This replaced a per-kind if-chain in ``activation.py``
        that checked four instruction kinds by hand and let every other
        object-targeted ability be activated with nothing to target — paying
        the cost (tapping the source, most often) and then dealing to the face
        or doing nothing. Returns the refusal text, or None when the ability
        does not target (so nothing is gated).
        """
        card = source_permanent.effective_card
        spec, _ = _activation_spec([ability])
        kind = spec.get("kind")
        if kind in ("none", "modal", "hand_card"):
            return None
        # A cost payment (Sacrifice) and a chosen *source* (Jade Monolith,
        # Circle of Protection) are not targets — CR 601.2b/601.2c — so an empty
        # board does not make them unactivatable. Their own paths validate them.
        if (
            spec.get("sacrifice_cost") or spec.get("discard_cost")
            or spec.get("also_stack") or spec.get("requires_source")
        ):
            return None
        instruction = getattr(ability, "instruction", None)
        if kind == ROLES_TARGET_KIND:
            # An ability naming several targets of *different* kinds, chosen in
            # dependency order (Sorrow's Path's two blockers, the second settled
            # by whose creature the first is). There is no second gate behind
            # this one — the cast side defers a roles announcement to
            # ``_validate_cast_targets`` and an activation has nothing of the
            # sort — so the whole announcement is checked here, through the very
            # walk the picker was built from.
            ability_instruction = targeting_instruction(instruction)
            refused = f"no valid target for {card.name}"
            named = [
                self.permanent_by_id(pid)
                for pid in (target_permanent_ids or [])
                if isinstance(pid, int)
            ]
            if named:
                legal = self._role_targets_legal(
                    controller_index, card, spec, named, for_cast=False,
                    source_permanent=source_permanent,
                    ability_instruction=ability_instruction,
                    ability_source=source_permanent,
                )
                return None if legal else refused
            # Nothing named: CR 602.2b's half of the question — could the whole
            # announcement be made at all? An empty walk means no, and the cost
            # is never paid.
            walked = self._role_target_walk(
                controller_index, card, spec, (), for_cast=False,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=source_permanent,
            )
            return None if walked else refused
        quantifiers = _ability_target_quantifiers(instruction)
        mandatory = "target" in quantifiers
        if not mandatory:
            # No mandatory target to enforce — an all-"up to" target may choose
            # none, and a kind with no target quantifier resolves its own choice
            # (a shield's "of your choice", an attacker the handler picks). Only
            # a *named* target still has to be legal, which the per-kind pickers
            # and the resolution already check for these.
            return None
        ability_instruction = targeting_instruction(instruction)
        valid = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent,
            ability_source=source_permanent,
        )
        # A player/"any" ability always has a legal target (a player is always
        # there), so those never refuse for want of one — the whole set of
        # legal permanents, graveyard cards and stack spells is what an empty
        # board can leave empty.
        legal_perm = {
            (t["seat"], t["index"]) for t in valid
            if t.get("kind") in ("permanent", "graveyard")
        }
        legal_stack = [t for t in valid if t.get("kind") == "stack"]
        refused = f"no valid target for {card.name}"

        # A named target must be legal. The web layer sends ids; a test or the
        # AI may send an index on a seat.
        if target_permanent_ids:
            chosen = [pid for pid in target_permanent_ids if pid is not None]
            if chosen:
                for pid in chosen:
                    perm = self.permanent_by_id(pid)
                    if perm is None:
                        return refused
                    seat = self.controller_index_of(perm)
                    idx = self.battlefield_index_of(perm)
                    if (seat, idx) not in legal_perm:
                        return refused
                return None
        if target_permanent_index is not None:
            # A bare index carries no seat, so it is legal if it names a legal
            # target on the seat the caller gave — or, when none was given, on
            # either battlefield (Xenic Poltergeist may animate your own
            # artifact; the resolution finds it by index without a seat).
            seats = (
                [target_player_index] if target_player_index is not None
                else list(range(len(self.players)))
            )
            indices = (
                target_permanent_index
                if isinstance(target_permanent_index, list)
                else [target_permanent_index]
            )
            for idx in indices:
                if idx is not None and not any((seat, idx) in legal_perm for seat in seats):
                    return refused
            return None
        if target_stack_item is not None:
            # A named stack spell (Deathgrip, Goblin Artisans): re-locate the
            # legal items by their top-first index, the convention
            # _enumerate_stack_targets emits, and compare by identity.
            depth = len(self.stack)
            legal_items = [
                self.stack[depth - 1 - t["stack_index"]]
                for t in legal_stack
                if 0 <= depth - 1 - t["stack_index"] < depth
            ]
            if not any(item is target_stack_item for item in legal_items):
                return refused
            return None

        # Nothing was named, and the target is mandatory: the ability is
        # activatable only if some legal target exists (CR 602.2b). This is the
        # census case — an empty board for a "destroy target creature" / "deals
        # N damage to target creature" ability, which used to pay the cost and
        # no-op (or, with an opponent creature present but none chosen, hit the
        # face).
        if not valid:
            return refused
        return None

    def cast_target_refusal(
        self, caster_index: int, card: CardDefinition, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, from_zone: str = "hand",
        optional_cost_payments: dict | None = None,
    ) -> str | None:
        """CR 601.2c: a **named** target — a battlefield permanent, or a slot
        in a graveyard — must be a legal one, checked before any cost is paid.
        Returns the refusal, or None.

        The cast-side twin of :meth:`activation_target_refusal`, and it exists
        for the same reason that one replaced a per-kind if-chain in
        ``activation.py``: ``_validate_cast_targets`` checks the target of the
        instruction kinds it has arms for, so a card whose primary instruction
        is a ``sequence`` wrapper — every "Destroy target artifact. You gain
        life…" — reached no arm and had its target unchecked. Divine Offering
        could be cast on Grizzly Bears.

        It cannot live inside ``_validate_cast_targets``, which is what makes
        this a second function rather than one more check there:
        ``_enumerate_targets(for_cast=True)`` probes each candidate *through*
        that method, so asking it from inside would recurse. Called beside it
        instead, from the one cast path, before the mana is spent.

        Only what the caller **named** is checked here. "Is there any legal
        target at all?" is the arms' own question and several of them answer it
        with a card-specific rule; this one answers "is the one you named among
        the ones the picker would have offered?", which is idiom #9 — the
        picker's enumeration is a hint and the engine re-checks the answer.

        **One shape is the exception, and it is the exception because the count
        itself was announced**: a spell whose targets are sized by a CR 601.2b
        optional additional cost (Primitive Justice's "for each additional
        {1}{R} you paid, destroy **another** target artifact"). CR 601.2c fixes
        the number of targets one step after that payment, so "how many did you
        name?" is answerable here and nowhere else — *optional_cost_payments* is
        the announcement, passed down from the one cast path. A caster who takes
        three offers with two artifacts on the table cannot make a legal
        announcement, and CR 601.2c makes that an uncastable spell rather than
        an ineffective one: the refusal lands before any mana is spent.

        That is the engine's only enforced target **floor**. Everywhere else a
        printed count is a maximum the announcement may fall short of — there is
        no ``min_targets`` in this engine, so "one or more target creatures"
        (Heaven's Gate and its four colour siblings) may still be cast naming
        none. Widening this to those is a separate change with a separate blast
        radius; what makes the cost-sized case answerable *now* is that its
        number comes from an announcement the same cast already made.
        """
        if card.primary_type not in ("instant", "sorcery"):
            # **A permanent spell does not target.** ``derive_cast_spec`` reads
            # the *card*, so Niambi, Esteemed Speaker's "when this creature
            # enters, return another target creature you control" comes back as
            # a creature spec — but that is the ETB trigger's target, chosen
            # when the trigger goes on the stack (CR 603.3d), long after this
            # spell was announced. Gating the cast on it refuses to cast the
            # creature at all. An Aura *is* targeted (CR 115.1b) and its enchant
            # target has its own arm in ``_validate_cast_targets``.
            return None
        program = compile_card_oracle(card)
        if program.modes:
            # A modal spell's spec is the *first* mode's, and the caller chose
            # another: Healing Salve's mode 0 targets a player and its mode 1 a
            # creature, so gating mode 1 against mode 0's enumeration refuses a
            # legal cast. The chosen mode's own targets are checked by the arms
            # in ``_validate_cast_targets``, which is handed the mode index.
            return None
        spec = derive_cast_spec(card, program, from_zone=from_zone)
        if spec is None or spec.get("kind") in _UNCHECKED_CAST_TARGET_KINDS:
            return None
        if spec_roles(spec):
            # A spell naming several targets of *different* kinds (Glyph of
            # Delusion's Wall and the creature that Wall blocked) has one spec
            # per role and a relation between them. ``_validate_cast_targets``
            # already checks the whole announcement through
            # ``_role_targets_legal``; one flat enumeration here would compare
            # the second target against the first role's list and refuse a
            # legal cast.
            return None
        named_ids = [pid for pid in (target_permanent_ids or []) if isinstance(pid, int)]
        indices = (
            [i for i in target_permanent_index if isinstance(i, int)]
            if isinstance(target_permanent_index, list)
            else ([target_permanent_index] if isinstance(target_permanent_index, int) else [])
        )
        # CR 601.2c's *count*, for the one shape that has one (see the
        # docstring). Above the "nothing was named" return below, because
        # naming nothing is precisely one of the announcements this refuses —
        # and above the graveyard branch, which no cost-sized announcement
        # reaches.
        required = cost_target_count(spec.get("cost_targets"), optional_cost_payments)
        if required is not None:
            # Ids are the precise channel and indices the legacy one; a seat is
            # part of an index's identity and no part of an id's, which is why
            # the two are counted in their own vocabulary rather than mixed.
            chosen_keys: list = (
                named_ids or [(target_player_index, index) for index in indices]
            )
            if len(chosen_keys) != required:
                return (
                    f"{card.name} needs {required} target"
                    + ("s" if required != 1 else "")
                    + f", not {len(chosen_keys)}"
                )
            if spec.get("distinct_targets") and len(set(chosen_keys)) != required:
                # The printed "another" (CR 601.2c): two instances of the word
                # "target" may name one object *unless* something forbids it,
                # and this sentence does. Refused at the announcement rather
                # than deduplicated at resolution, which would quietly destroy
                # fewer permanents than the caster paid for.
                return f"{card.name} needs {required} different targets"
        if spec.get("kind") == GRAVEYARD_TARGET_KIND:
            # A named graveyard slot, checked against the ``graveyard``-kind
            # entries the same enumeration offers the picker — the one zone
            # where the per-kind arms in ``_validate_cast_targets`` cannot be
            # relied on, because they key on the *primary* instruction kind and
            # a spell whose graveyard targeting sits inside a ``sequence``
            # (Fungal Rebirth, Experimental Overload) reaches no arm at all: an
            # announcement naming an opponent's pile was accepted and
            # ``graveyard_target_seat`` then silently re-pointed it at the
            # caster's own. Same seat semantics as the activation twin above —
            # a bare index carries no seat, so a named seat narrows the
            # comparison and an unnamed one is legal on any pile the
            # enumeration offers. Ids are not read here: a card in a graveyard
            # is not a permanent (CR 115.2) and has no ``permanent_id``.
            if not indices:
                # CR 601.2c gates what was *named*; an untargeted cast resolves
                # its own pick and the "does any legal target exist?" half
                # stays the per-kind arms' question, as everywhere else here.
                return None
            valid = self._enumerate_targets(caster_index, card, spec, for_cast=True)
            legal_slots = {
                (t["seat"], t["index"]) for t in valid
                if t.get("kind") == "graveyard" and t.get("index") is not None
            }
            seats = (
                [target_player_index] if target_player_index is not None
                else list(range(len(self.players)))
            )
            for index in indices:
                if not any((seat, index) in legal_slots for seat in seats):
                    return f"no valid target for {card.name}"
            return None
        if not named_ids and not indices:
            return None
        valid = self._enumerate_targets(caster_index, card, spec, for_cast=True)
        legal = {
            (t["seat"], t["index"]) for t in valid
            if t.get("kind") == "permanent" and t.get("index") is not None
        }
        refused = f"no valid target for {card.name}"
        chosen: list = []
        for permanent_id in named_ids:
            target = self.permanent_by_id(permanent_id)
            if target is None:
                return refused
            slot = (self.controller_index_of(target), self.battlefield_index_of(target))
            if slot not in legal:
                return refused
            chosen.append(target)
        if spec.get("same_controller") and len(chosen) > 1:
            # "Choose two target creatures **controlled by the same opponent**."
            # (Retribution, CR 601.2c.) A relation between the targets, so it
            # cannot be part of the per-candidate enumeration above — that one
            # answers "is each of these a legal target", and two creatures each
            # controlled by a *different* opponent both pass it. Asked here,
            # over the whole announcement, and only where the caster named more
            # than one: a single named target trivially shares a controller
            # with itself and refusing on a half-made announcement would refuse
            # a legal cast.
            seats = {self.controller_index_of(perm) for perm in chosen}
            if len(seats) != 1 or None in seats:
                return refused
        if named_ids:
            # Ids are the precise answer; an index beside them is the same
            # choice said twice, and re-checking it would ask about whatever
            # now sits in that slot.
            return None
        seats = (
            [target_player_index] if target_player_index is not None
            else list(range(len(self.players)))
        )
        for index in indices:
            if not any((seat, index) in legal for seat in seats):
                return refused
        return None

    def illegal_targets_refusal(self, item) -> str | None:
        """CR 608.2b: whether *item* must leave the stack without resolving.

        The other end of :meth:`activation_target_refusal`. That one asks
        "may this be announced?" (CR 601.2c/602.2b) before a cost is paid;
        this asks "are the targets it announced still legal?" at the moment it
        would resolve, and the rule is all-or-nothing — if **every** target,
        for every instance of the word "target", is illegal, the object does
        not resolve at all. Returns the reason, or None to resolve normally.

        This is not the same as a handler finding nothing to do. Each handler
        already re-checks its own target and skips its own effect, which is
        CR 608.2b's *last* sentence ("illegal targets won't be affected by
        parts of the effect for which they're illegal") — and with a per-handler
        answer, everything printed **after** that sentence still ran. Divine
        Offering ("Destroy target artifact. You gain life equal to its mana
        value") gained the life for destroying nothing, which is the rule's own
        worked example inverted (CR 608.2b's Sorin's Thirst: "Its controller
        doesn't gain any life"). The check has to be about the object, so it
        lives here and runs once, above the instructions.

        **Targets are read by identity, never by index.** The ids are what
        ``_stack_push_object`` stamped as the object was announced, for the
        reason it stamps them: a slot renumbers while the object waits, and an
        index that has come to mean a different permanent would answer this
        question about the wrong one.

        One deliberate exclusion, because the engine cannot answer
        "all targets" for it rather than because the rule stops:

        * **A spell that can target a player** — "any target", a divided one,
          a player-targeted one. A seat and a *chosen player* reach a stack
          item through the same ``target_player_index`` field, so a Fireball
          split between a creature and its controller is indistinguishable from
          one aimed at the creature alone; the creature dying would then read
          as "every target is illegal" when the player is still a legal one.

        **A graveyard target is answered here too, in its answerable half.**
        The stamp ``_stack_push_object`` recorded (``GraveyardTarget``) is the
        chosen card's identity, and a stamp ``graveyard_index_of`` can no
        longer resolve — no copy of that card left in that pile — is a target
        the data model can establish is *gone*, so it counts as illegal like a
        departed permanent does. The **ambiguous** half stays out on purpose:
        two copies of one card in one graveyard are literally one
        ``CardDefinition``, so while any copy survives the stamp still
        resolves (clamped to the last surviving copy) and the target is legal
        — the engine cannot know *which* copy left, and a fizzle there would
        be a guess dressed as a rule.
        """
        card = item.card
        if item.ability_instruction is not None:
            # **Spells only, and the reason is a different bug.** A spell's
            # targets are a player's choice, made at announcement through
            # ``cast_target_refusal`` against the enumerated legal ones, so an
            # id recorded on a spell is a choice that was legal when it was
            # made and this rule is exactly the question to ask of it later.
            #
            # A triggered ability's are stamped at its fire site, and the death
            # sweep enqueues a dies-trigger *while the dying permanent is still
            # listed* (``_destroy_swept_permanents``) — so Blazing Effigy's
            # "it deals 3 damage to target creature" records the dying Effigy
            # itself, a permanent CR 603.3d would never have offered. Asking
            # 608.2b of that id counters an ability the engine mis-targeted and
            # reports it as a rules-correct fizzle, which buries the targeting
            # bug under a rule. The fire sites have to choose targets after the
            # permanent has left before this can widen; see ROADMAP.
            return None
        if card.primary_type not in ("instant", "sorcery"):
            # The same reason the announcement gate is instants and sorceries
            # only: a permanent spell's derived spec belongs to a triggered
            # ability that has not been put on the stack yet, so an id stamped
            # beside it says nothing about what *this* object targets. An Aura
            # whose enchant target has left is CR 608.2b too, and today it
            # enters attached to nothing and is binned by CR 704.5m one sweep
            # later — the same destination by a different rule, so moving it is
            # a decision for the round that can verify it.
            return None
        spec = derive_cast_spec(card, compile_card_oracle(card))
        if spec is None or spec.get("kind") in _UNFIZZLABLE_TARGET_KINDS:
            # Either the spell does not target at all — a creature spell whose
            # caller passed a stray index still gets an id stamped, and
            # countering it would be inventing a target the card never printed
            # — or its target may be a player, above.
            return None

        legality: list[bool] = []
        ids = item.target_permanent_id
        for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
            if not isinstance(permanent_id, int):
                continue
            target = self.permanent_by_id(permanent_id)
            legality.append(
                target is not None
                and self.is_on_battlefield(target)
                # CR 608.2b's "other changes to the game state": protection or
                # shroud gained in response is the rule's own second example,
                # and it is the same predicate the cast gate asked.
                and self._can_be_targeted(
                    target, card, caster_index=item.caster_index,
                )
            )
        stamps = item.target_graveyard_card
        for stamp in (stamps if isinstance(stamps, list) else [stamps]):
            if stamp is None:
                continue
            # The stamp resolving to no slot means no copy of the chosen card
            # remains in that graveyard — the unambiguous "gone", per the
            # docstring above. While a copy survives, `graveyard_index_of`
            # answers a slot (clamping where it must) and the target is legal.
            legality.append(self.graveyard_index_of(stamp) is not None)
        if item.target_stack_item is not None:
            # A countered or already-resolved spell has left the zone it was
            # targeted in, which is CR 608.2b's first sentence.
            legality.append(any(obj is item.target_stack_item for obj in self.stack))

        if not legality or any(legality):
            return None
        return f"{card.name} was removed from the stack: every target is illegal (608.2b)"

    # -- Target enumeration ------------------------------------------------
    def _enumerate_targets(
        self, caster_index: int, card: CardDefinition, spec: dict, *, for_cast: bool,
        ability_instruction=None, source_permanent=None, ability_source=None,
    ) -> list[dict]:
        kind = spec["kind"]
        if kind in ("none", "modal"):
            return []
        # "…players and permanents can't be the targets of spells or activated
        # abilities." (Peace Talks.) CR 115.1 with nothing left to choose, so
        # the answer is the empty list and every gate above already knows what
        # to do with it — the picker offers nothing, `cast_target_refusal`
        # declines the announcement (CR 601.2c) and
        # `activation_target_refusal` declines the activation (CR 602.2b) with
        # nothing paid.
        #
        # Here rather than in ``_can_be_targeted``: that predicate is asked
        # about a **permanent** and would leave the player half unenforced, and
        # it cannot tell an activated ability from a triggered one, which this
        # sentence separates. Everything reaching this function is a spell
        # (``for_cast``) or an activated ability's picker; a trigger chooses its
        # targets at its fire site and is untouched, which is what the card
        # says.
        #
        # A **cost** payment is not a target (CR 601.2b vs 601.2c), and the
        # spec says so — the same flag the seat loop below reads — so a
        # sacrifice cost keeps enumerating while the ban is up.
        if self.targeting_bans and not spec.get("sacrifice_cost"):
            return []
        # "…**defending player controls**" (Floral Spuzzem, Kukemssa Pirates,
        # Yare). Not relative to the seat choosing but to a combat, and which
        # combat depends on who is asking: a *trigger* names the one it fired
        # in, which may be over by the time it resolves, so the announcement
        # freezes the seat and passes it on the spec. A **spell** has no such
        # record -- it is being cast right now -- so the seat is the live
        # combat's, through the one reader that asks CR 506.2's strict
        # question. Outside combat there is no defending player at all, so the
        # card has no legal target, which is the answer rather than a fallback.
        #
        # Resolved once, here, because the phrase is read twice below: as a
        # flag on the seat loop, and inside the printed noun phrase every
        # candidate goes through.
        defending_seat = spec.get("defending_player_index")
        if defending_seat is None:
            defending_seat = self.defending_player_index_now()
        # "…**that player** controls", resolved the same way one record over.
        # A modal spell's chooser supplies the seat on the spec (CR 700.2e) and
        # a trigger's fire site froze one; a **spell** printing the phrase in
        # its own text has neither, and the only sentence its pronoun can point
        # back at is the timing clause above it — "Cast this spell only during
        # an opponent's turn. Tap target creature that player controls."
        # (Delirium). The table that owns that phrase is what answers, so the
        # picker and the timing gate cannot disagree about which player the
        # card is talking about.
        that_player_seat = spec.get("that_player_index")
        if that_player_seat is None:
            that_player_seat = timing_fixed_seat(self, caster_index, card)
        if kind == "hand_card":
            return self._enumerate_cost_hand_cards(
                caster_index, card, spec, for_cast=for_cast
            )
        if kind == "graveyard_creature":
            return self._enumerate_graveyard_creatures(caster_index, spec)
        if kind == "stack":
            return self._enumerate_stack_targets(
                caster_index, card, spec,
                source=ability_source or source_permanent,
            )
        if kind == "spell_or_permanent":
            # Lace recolor: legal on any permanent on the battlefield or any spell
            # on the stack. Enumerate both and concatenate. Unsubstantiate narrows
            # the permanent half to creatures via `permanent_kind`.
            perms = self._enumerate_targets(
                caster_index, card, {**spec, "kind": spec.get("permanent_kind", "permanent")},
                for_cast=for_cast, ability_instruction=ability_instruction,
                ability_source=ability_source,
            )
            return perms + self._enumerate_stack_targets(caster_index, card, spec)

        targets: list[dict] = []
        # Player faces are legal for player-targeted, "any target", and divided
        # spells — but not a divided land selection (Volcanic Eruption's Mountains).
        if (
            kind in ("player", "any", "divided", "player_or_planeswalker")
            # "…among any number of **target creatures**" (Fire Covenant) — the
            # divided sibling of the land narrowing beside it. Without the noun,
            # a player's face was offered as a legal target for a spell that
            # names none.
            and not spec.get("land_filter")
            and not spec.get("creatures_only")
        ):
            for seat in range(len(self.players)):
                # "target opponent" (Word of Command) can't be the caster's own seat.
                if spec.get("opponents_only") and seat == caster_index:
                    continue
                # "target player **who attacked this turn**" (Fire and
                # Brimstone). The record is on the seat, not on its creatures:
                # a player who attacked and then lost the attacker still
                # attacked, and reading the board would forget them.
                if (
                    spec.get("attacked_this_turn")
                    and not self.players[seat].attacked_this_turn
                ):
                    continue
                # "target opponent **previously dealt damage by it**" (Diseased
                # Vermin). The record is on the *source permanent*, not on the
                # seat — "whom has this creature hurt" — so this is the one
                # player narrowing that needs the ability's source, and with no
                # source in hand the clause admits nobody rather than everybody:
                # an unenforceable restriction offered as satisfied is the
                # silent direction (CR 601.2c).
                if spec.get("damaged_by_source"):
                    from .damage_events import seats_dealt_damage_by

                    if ability_source is None:
                        continue
                    if seat not in seats_dealt_damage_by(ability_source):
                        continue
                targets.append({"kind": "player", "seat": seat})
            if kind == "player":
                return targets

        casting_aura = "aura" in _type_line(card)
        # **A cost payment is not a target** (CR 601.2b vs 601.2c), so none of
        # the targeting legality below applies to it: protection, shroud and
        # hexproof stop a permanent being *targeted*, and a player may always
        # sacrifice their own. The payment paths have always known this — a
        # White Knight (protection from black) is a legal payment for Sacrifice
        # and the engine takes it happily — while this enumerator refused to
        # offer one, so the answer depended on whether you were a person or a
        # script. That is the picker/resolution disagreement the round-48 guard
        # exists for, arriving through the cost field instead of the target one.
        paying_a_cost = bool(spec.get("sacrifice_cost"))
        for seat, player in enumerate(self.players):
            # A sacrifice cost (Sacrifice) only offers the caster's own creatures.
            if spec.get("own_only") and seat != caster_index:
                continue
            # "…an opponent controls" — the activator's own permanents are not
            # legal answers. The same seat test as `own_only` one line up, in
            # the other direction.
            if spec.get("opponent_only") and seat == caster_index:
                continue
            # "…**defending player controls**" (Floral Spuzzem, Yare). Not
            # relative to the seat choosing but to a combat, and which combat
            # depends on who is asking: a *trigger* names the one it fired in,
            # which may be over by the time it resolves, so the announcement
            # freezes the seat and passes it on the spec. A **spell** has no
            # such record — it is being cast right now — so the seat is the
            # live combat's, through the engine's one reader.
            #
            # The supplied seat wins wherever there is one, which is what keeps
            # a trigger reading its own combat rather than whatever is
            # happening when it resolves. And a flag with no seat and no combat
            # still offers nothing rather than everything: outside combat there
            # is no defending player (CR 506.2), so the card has no legal
            # target, which is the answer rather than a fallback.
            if spec.get("defending_player_only") and seat != defending_seat:
                continue
            # "…**that player** controls" (Fatal Lore). The same arrangement one
            # record over: CR 700.2e's mode choice froze the seat, and the
            # caller holding that record supplies it beside the flag. A flag
            # with no seat offers nothing, for the reason above — this one would
            # otherwise widen to every creature in the game.
            if spec.get("that_player_only") and seat != that_player_seat:
                continue
            for idx, perm in enumerate(player.battlefield):
                if not self._permanent_matches_target_kind(perm, kind, spec, casting_aura):
                    continue
                # "Sacrifice **another** …" — the source cannot pay for itself.
                if spec.get("exclude_source") and perm is source_permanent:
                    continue
                # "target creature **you cast this turn**" (Cycle of Life).
                # CR 701.5a's cast, asked through ``subject_matches`` -- the
                # one reader of a printed noun phrase -- so the picker and
                # the resolution cannot disagree about which creatures answer
                # it. Here rather than in ``_permanent_matches_target_kind``
                # because the phrase names a *seat*, and that method is
                # handed no observer to compare one against.
                if spec.get("cast_by_you_this_turn") and not subject_matches(
                    self, perm, {"cast_by_you_this_turn": True},
                    observer=caster_index, source=source_permanent,
                ):
                    continue
                # "…to **another** target creature" on an Aura (Farrel's
                # Mantle): the creature excluded is the one the source is
                # attached to, which is the one that will deal the damage.
                if spec.get("exclude_attached"):
                    from .handlers._common import attached_host

                    if perm is attached_host(self, source_permanent):
                        continue
                # The three combat *relations* a target description can print.
                # Both are asked through ``subject_matches`` — the one reader of
                # what a printed noun phrase means — with the observer and
                # source this loop holds, so the list the picker offers and the
                # set the handler affects are decided by the same function.
                # A flag with nothing to answer it against offers nothing, which
                # is the direction that cannot widen a target description.
                if (
                    spec.get("blocked_by_source")
                    or spec.get("blocking_source")
                    or spec.get("attacking_you")
                    or spec.get("attacked_you_this_turn")
                ):
                    relation = {
                        key: True
                        for key in (
                            "blocked_by_source", "blocking_source", "attacking_you",
                            "attacked_you_this_turn",
                        )
                        if spec.get(key)
                    }
                    if not subject_matches(
                        self, perm, relation,
                        observer=caster_index,
                        source=ability_source or source_permanent,
                    ):
                        continue
                # Whatever the printed noun phrase says beyond its head noun
                # ("a creature **with defender**", Portcullis Vine). The same
                # matcher the payment path runs, so the list offered here and
                # the list accepted there are the same list — a picker offering
                # an ineligible permanent would have its answer silently
                # replaced by the deterministic pick.
                if not subject_matches(
                    self, perm, spec.get("filter"), defending=defending_seat
                ):
                    continue
                if not paying_a_cost:
                    if for_cast:
                        ok, _ = self._validate_cast_targets(
                            card, caster_index,
                            target_player_index=seat, target_permanent_index=idx,
                        )
                        if not ok:
                            continue
                    else:
                        # The spec goes with the object. ``ability_source``
                        # says an *ability* is choosing; the spec says what that
                        # one ability announced, which is what Wall of Shadows'
                        # "abilities that can target only Walls" asks about and
                        # which the source object alone cannot answer.
                        if not self._can_be_targeted(
                            perm, card, caster_index=caster_index,
                            ability_source=ability_source, source_spec=spec,
                        ):
                            continue
                        # Apply the activated ability's own target restriction (e.g.
                        # Royal Assassin's tapped-only, Nettling Imp's non-Wall) so it
                        # offers only what it could legally affect at resolution.
                        if ability_instruction is not None and not self._ability_target_legal(
                            ability_instruction, perm,
                            candidate_seat=seat, controller_index=caster_index,
                            source_permanent=source_permanent,
                            defending=defending_seat,
                            that_player=that_player_seat,
                        ):
                            continue
                targets.append({
                    "kind": "permanent",
                    "seat": seat,
                    "index": idx,
                    "key": f"{seat}-{idx}",
                    "name": perm.card.name,
                })
        # Circle of Protection: the chosen source may also be a spell of the named
        # color on the stack — fold those into the same target list.
        if spec.get("also_stack"):
            targets += self._enumerate_stack_targets(
                caster_index,
                card,
                {
                    "stack_color_filter": spec.get("color_filter"),
                    "stack_any_colors": spec.get("any_colors"),
                },
            )
        return targets

    def _ability_target_legal(
        self, instruction, perm: Permanent, *,
        candidate_seat=None, controller_index=None, source_permanent=None,
        defending: int | None = None,
        that_player: int | None = None,
    ) -> bool:
        """Whether *perm* satisfies an activated ability instruction's own target
        restriction (beyond the text-derived kind).

        *defending* is CR 506.2's seat, resolved by the caller and handed down
        for the generic tail's ``subject_matches`` -- a printed "defending
        player controls" is a narrowing like any other and must be tested, not
        dropped, at the one place that decides what a picker offers.

        *that_player* is CR 603.10's seat, travelling for exactly that reason
        one phrase over: "target creature or planeswalker **that player**
        controls" (Chandra's Incinerator) is a narrowing ``subject_matches``
        refuses outright unless it is given the seat, and refusing is what an
        empty picker looks like. The caller is the only holder -- the seat was
        frozen into the trigger's context by the fire site -- so it is handed
        down rather than re-derived, which is what keeps the picker and the
        resolution naming one player.
        """
        instruction = _targeting_step(instruction) or instruction
        if instruction.kind == "destroy_target_permanent":
            return self._destroy_target_legal(instruction.payload, perm)
        if instruction.kind == "mark_non_wall_target_to_attack":
            # The whole noun phrase, not its first two words: "the active
            # player has controlled continuously since the beginning of the
            # turn" narrows it further, and the picker offering a creature the
            # handler will refuse is the two-readers failure this gate exists
            # to prevent. One reader answers both.
            from .handlers.combat import forced_attacker_is_legal

            return forced_attacker_is_legal(self, perm)
        if instruction.kind == "grant_flying_and_delayed_destruction":
            # Stone Giant: "Target creature you control with toughness less than
            # this creature's power." Only the activating player's creatures with
            # toughness below the source's power are legal.
            if candidate_seat is not None and controller_index is not None and candidate_seat != controller_index:
                return False
            if source_permanent is not None and perm.effective_toughness >= source_permanent.effective_power:
                return False
            return perm.is_creature
        if instruction.kind == "set_base_pt_target_until_eot" and instruction.payload.get("exclude_self"):
            # Sorceress Queen: "Target creature other than this creature."
            return source_permanent is None or perm is not source_permanent
        if instruction.kind == "set_source_base_pt_from_target":
            # Sentinel: "target creature blocking or blocked by this creature";
            # Sworn Defender: "…blocking or being blocked by this creature"
            # — the same in-combat relation the handler re-checks at resolution
            # (CR 608.2b), asked here so the ability is refused with nothing
            # paid when no such creature exists (CR 602.2b via 601.2c) and the
            # picker offers exactly what the effect can read.
            if not perm.is_creature:
                return False
            if instruction.payload.get("in_combat_with_source"):
                return source_permanent is not None and any(
                    perm is opponent
                    for opponent in self.creatures_in_combat_with(source_permanent)
                )
            return True
        if instruction.kind == "steal_creature_while_tapped_and_weaker":
            # Old Man of the Sea: only creatures at or below its own power.
            if not perm.is_creature:
                return False
            return source_permanent is None or perm.effective_power <= source_permanent.effective_power
        if instruction.kind == "steal_target_linked_to_source":
            # Willow Satyr's "target legendary creature" / Rubinia Soulsinger's
            # "target creature" — the same payload filter the handler tests at
            # resolution, asked here so the picker offers exactly what the
            # resolution will accept.
            #
            # **Seasinger's "whose controller controls an Island" is dropped
            # here**, and swapping this to ``subject_matches`` is not the fix:
            # this same arm serves Orcish Squatters' "target land **defending
            # player** controls", a seat that belongs to the combat rather than
            # to the permanent, and ``subject_matches`` refuses that key
            # outright — so the swap trades a widened picker for an empty one.
            # The two phrases want different readers; see the W1G2 report.
            return permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "grant_regeneration_to_target_creature":
            # Elephant Graveyard's "target Elephant" — the same subtype filter
            # _grant_regeneration_shield enforces at resolution. Death Ward's
            # payload is empty, so every creature passes.
            return perm.is_creature and permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "produce_mana_instead":
            # Quarum Trench Gnomes' "target Plains" — the same subtype filter
            # the handler tests at resolution, asked here so the ability is
            # refused with nothing paid when no such land exists (CR 602.2b via
            # 601.2c) and the picker offers exactly what the swap can reach.
            targets = instruction.payload.get("targets") or {}
            return permanent_matches_filter(perm, targets.get("filter") or {})
        if instruction.kind == "tap_target_permanent":
            # Ali Baba's "target Wall" (and any other parsed tap-target filter);
            # Icy Manipulator's payload is empty, so everything passes.
            #
            # Through ``subject_matches``, **not** the pure matcher. Three of
            # the keys this family's payloads carry are questions only the game
            # can answer — a keyword is layer 6, "you don't control" is a seat,
            # "that's attacking you" is a combat record — and the pure matcher
            # ignores every one of them rather than refusing. Ignored, the
            # printed narrowing is enforced by nobody: Flood tapped a flier,
            # Ice Floe tapped a creature attacking somebody else, Shacklegeist
            # tapped its own controller's creature, and Storm Elemental named
            # a ground creature. All four paid the cost, resolved, and tapped
            # nothing, because the *handler* still reads the filter — which is
            # the shape that makes this silent.
            return subject_matches(
                self, perm, instruction.payload,
                observer=controller_index, source=source_permanent,
            )
        if instruction.kind == "attach_source_to_target":
            # An equip ability (CR 702.6a). The picker's own_only flag has
            # already kept it to the activator's creatures; what is left is the
            # printed narrowing (CR 702.6c's "legendary creature") and whether
            # the Equipment may legally equip this creature at all — protection
            # from its colour (702.16d), the Equipment itself (301.5c). Asked of
            # the same predicate the resolution asks, so a creature offered here
            # is one the attach then lands on.
            # ``attachment_refusal``, not ``equip_refusal``: CR 701.3's action
            # is asked of whichever kind of Attachment printed the ability, and
            # an Aura's legality is its enchant clause (CR 702.5), not
            # CR 301.5's. Asking the Equipment predicate of an Aura refused
            # every host and emptied the picker.
            from .equipment import attachment_refusal

            if not permanent_matches_filter(perm, instruction.payload):
                return False
            # The printed narrowing lives on the ``targets`` filter as well as
            # on the payload root — "other than enchanted creature" (Kjeldoran
            # Pride) is a relative key, which ``permanent_matches_filter`` (the
            # pure half) cannot answer at all. So it is asked of
            # ``subject_matches``, the half that has the game and the source
            # (imported at module scope, not here: a second, function-level
            # import of a module-level name turns it local for the *whole*
            # function and breaks every other branch that reads it).
            described = (instruction.payload.get("targets") or {}).get("filter") or {}
            if described and not subject_matches(
                self, perm, described, observer=controller_index,
                source=source_permanent,
            ):
                return False
            return (
                source_permanent is None
                or attachment_refusal(self, source_permanent, perm) is None
            )
        if instruction.kind == "add_counter_to_target":
            # Tempered Veteran's "target creature with a +1/+1 counter on it" —
            # the same filter the handler enforces at resolution, so the picker
            # offers exactly what the ability could affect. Most counter
            # placements carry an empty filter and every creature passes.
            targets = instruction.payload.get("targets") or {}
            if not perm.is_creature or not permanent_matches_filter(
                perm, targets.get("filter") or {}
            ):
                return False
            # "…on target creature **blocking or blocked by this creature**"
            # (Lesser Werewolf) — the same in-combat relation Sentinel's rewrite
            # carries a dozen lines above, asked here so the ability is refused
            # with nothing paid when no such creature exists (CR 602.2b via
            # 601.2c) and the picker offers exactly what the effect can reach.
            if instruction.payload.get("in_combat_with_source"):
                return source_permanent is not None and any(
                    perm is other
                    for other in self.creatures_in_combat_with(source_permanent)
                )
            return True
        # **The generic tail, and the reason it is not another branch.**
        # Every branch above says the same sentence in its own words: "apply the
        # filter this instruction's payload already carries". A kind absent from
        # the chain fell through to a bare ``return True``, and that is not a
        # missing feature — it is the printed narrowing *dropped at the picker*,
        # silently and in the player's favour. Karakas offered every creature
        # for "target **legendary** creature", Grapeshot Catapult every creature
        # for "target creature **with flying**", Mishra's Factory every creature
        # for "target **Assembly-Worker**"; each of them a shipped card whose
        # ability worked more often than it reads.
        #
        # It is safe as a default rather than as an opt-in list because the
        # compiler will not admit a narrowed line at all unless every key of its
        # filter is in ``TESTABLE_SUBJECT_FILTER_KEYS`` (see
        # ``engine/subject_filters.py``). So a filter that reaches here is one
        # ``subject_matches`` answers in full — and the branches above survive
        # only where the restriction is *not* in the filter (an in-combat
        # relation, the source's own power, the equip legality).
        #
        # ``subject_matches`` rather than ``permanent_matches_filter``: the
        # relative keys are exactly the ones a picker can answer and a pure
        # matcher cannot — "you control" is the activating seat, "another" is
        # the source — and both are already in this method's hands.
        #
        # A description whose slots are *differently* restricted carries one
        # filter per slot, and the picker enumerates one legal set for all of
        # them — so a permanent is offered when **some** slot admits it, never
        # only when every slot does. Garruk, Savage Herald's -2 is the case:
        # slot one is "creature you control", slot two is any creature, and
        # intersecting them would hide every opponent's creature from a bite
        # that is allowed to name one. Per-slot legality stays the handler's.
        targets = instruction.payload.get("targets") or {}
        slot_filters = targets.get("filters")
        if isinstance(slot_filters, list) and len(slot_filters) > 1:
            return any(
                subject_matches(
                    self, perm, slot or {},
                    observer=controller_index, source=source_permanent,
                    defending=defending, that_player=that_player,
                )
                for slot in slot_filters
            )
        described = targets.get("filter")
        if described:
            return subject_matches(
                self, perm, described,
                observer=controller_index, source=source_permanent,
                defending=defending, that_player=that_player,
            )
        return True

    def _permanent_matches_target_kind(self, perm: Permanent, kind: str, spec: dict, casting_aura: bool) -> bool:
        # Effective type line so copies match by their copied types — a Copy
        # Artifact copying a Mox is an "Artifact Enchantment" and must be a
        # legal target both as an artifact and as an enchantment.
        type_line = perm.effective_card.type_line.lower()
        # "…**that isn't enchanted**" (Time Elemental). Asked before the kind
        # switch because the restriction is not about the head noun: the card
        # prints it on "permanent", and a card printing it on "creature" would
        # want the same answer. The pure matcher answers it, so the picker and
        # the handler's ``subject_matches`` call cannot disagree.
        if spec.get("not_enchanted") and not permanent_matches_filter(
            perm, {"not_enchanted": True}
        ):
            return False
        # "…**target enchanted creature**" (Ramses Overdark), the positive twin
        # and asked in the same place for the same reason: the restriction is
        # not about the head noun, and the picker must offer exactly what the
        # handler's matcher would accept — an unenchanted creature offered here
        # is a tap paid for a destroy that then fizzles.
        if spec.get("enchanted_only") and not permanent_matches_filter(
            perm, {"enchanted_only": True}
        ):
            return False
        # **Colour is not about the head noun.** "Target **black** creature"
        # (Exorcist, Spinal Villain) restricts exactly what "target **blue**
        # permanent" (Flash Flood) does, so it is asked once, before the switch,
        # for the reason the two tests above it are: a restriction asked inside
        # one branch is a restriction the other branches drop. It lived in the
        # ``permanent`` branch alone, so a colour-narrowed *creature* target was
        # offered in every colour by any caller with no instruction to delegate
        # to — a cast, a reflexive trigger (CR 603.12) and a trigger choosing
        # its own target all enumerate without one.
        #
        # Layer 5, not the printed line. Deathlace makes a Grizzly Bears black;
        # the *resolution* accepted it and this enumerator did not, so the
        # picker offered nothing while a script could kill it — one question
        # about one permanent with two answers.
        color_filter = spec.get("color_filter")
        if color_filter and color_filter not in perm.effective_colors:
            return False
        # "a black **or red** source of your choice" — the disjunction
        # ``ObjectFilter.any_colors`` spells the same way, asked of the same
        # layer-5 answer as the single-colour test above.
        any_colors = spec.get("any_colors")
        if any_colors and not any(
            colour in perm.effective_colors for colour in any_colors
        ):
            return False
        # "Enchant creature **without flying**" (Roots). Asked here, before the
        # switch, for the same reason the colour tests above it are: an
        # exclusion asked inside one branch is an exclusion every other branch
        # drops, and CR 702.5's [quality] can narrow any of the six enchant
        # nouns. Layer 6, through the same ``has_keyword`` the cast gate asks
        # (``stack/casting.permanent_matches_enchant_noun``) — one reading, so
        # the picker cannot offer a host the cast then refuses.
        without_keyword = spec.get("without_keyword")
        if without_keyword and self._has_keyword(perm, without_keyword):
            return False
        if kind == "player_or_planeswalker":
            # "Target player or planeswalker" (Chandra's Magmutt): the only
            # permanents in the union are planeswalkers — the player faces were
            # already added by the seat loop above.
            return perm.has_type("planeswalker")
        if kind == "planeswalker":
            # "target planeswalker" alone (Sparkhunter Masticore), with no player
            # face in the union. Through `has_type` rather than the printed line,
            # because a planeswalker is a computed type like any other (CR 613
            # layer 4).
            return perm.has_type("planeswalker")
        if kind in ("creature", "any", "divided"):
            # Volcanic Eruption: a divided spell that targets Mountains, not creatures.
            land_filter = spec.get("land_filter")
            if land_filter:
                if perm.card.primary_type != "land":
                    return False
                # CR 305.7: setting a land's subtype replaces its old ones, so
                # a Mountain turned into an Island is NOT a legal "target
                # Mountain". Matching printed-or-override made it both.
                return perm.has_type(land_filter)
            # is_creature so animated lands (Kormus Bell / Living Lands) are legal
            # targets for creature-targeting spells, abilities, and Auras.
            # CR 115.4: "any target" also admits planeswalkers.
            if not perm.is_creature:
                if kind == "any" and perm.has_type("planeswalker"):
                    return True
                return False
            if spec.get("enchant_wall"):
                return perm.has_type("wall")
            # Forcefield: only unblocked attacking creatures are legal choices.
            if spec.get("unblocked_attacker") and not (perm.attacking and not perm.blocked):
                return False
            # Singing Tree: only currently-attacking creatures are legal choices.
            if spec.get("attacking_only") and not perm.attacking:
                return False
            # Righteousness, Sorrow's Path: only creatures that are currently
            # blocking are legal choices. The narrower half of the `any_states`
            # union below, asked of the same `state_holds` table so a picker and
            # a resolution cannot disagree about what "blocking" means. Enforced
            # here as well as at resolution because CR 602.2b refuses an
            # activation outright when no legal target exists — the cast side
            # reached the same answer through its own `_validate_cast_targets`
            # probe, and an *ability* narrowed this way had nothing at all.
            if spec.get("blocking_only") and not state_holds(perm, "blocking"):
                return False
            # "target **blocked** attacking creature" (General Jarkeld). The
            # other end of the same relation, asked exactly as
            # `permanent_matches_filter` asks it so the picker and the
            # resolution cannot disagree — CR 509.1h's blocked creature is an
            # attacking one that has blockers declared for it.
            if spec.get("blocked_only") and not (
                getattr(perm, "attacking", False) and getattr(perm, "blocked", False)
            ):
                return False
            # The Legends pinger cycle: "target attacking or blocking creature".
            # Enforced here as well as at resolution, because CR 602.2b refuses
            # the activation outright when no legal target exists — a pinger
            # with nothing in combat to shoot must cost nothing rather than
            # resolve at whatever the picker happened to offer.
            any_states = spec.get("any_states")
            if any_states and not any(
                state_holds(perm, word) for word in any_states
            ):
                return False
            # "…creatures **without flying**" (Rock Slide). Asked of layer 6
            # through the same accessor `flying_only` beside it uses, so a
            # creature *granted* flying is excluded exactly as a printed flyer
            # is (CR 613.1f) and one that lost it is offered. Enforced here as
            # well as at resolution, for `blocked_only`'s reason: a narrowing
            # the picker does not apply is one CR 601.2c then admits.
            if any(
                self._has_keyword(perm, str(word))
                for word in spec.get("without_keywords") or ()
            ):
                return False
            # Island of Wak-Wak: only flying creatures are legal choices.
            if spec.get("flying_only") and not self._has_keyword(perm, "flying"):
                return False
            # Ali Baba: only Walls are legal choices.
            if spec.get("wall_only") and not perm.has_type("wall"):
                return False
            return True
        if kind == "artifact":
            if "artifact" not in type_line:
                return False
            # Guardian Beast: noncreature artifacts it protects can't be enchanted.
            if casting_aura and self._untapped_artifact_protector_active(perm):
                return False
            return True
        if kind == "land":
            if perm.card.primary_type != "land":
                return False
            if casting_aura and _cant_be_enchanted_by_auras(perm):
                return False
            if spec.get("exclude_swamp"):
                # Same CR 305.7 point: a Swamp turned into an Island is no
                # longer a Swamp, so "target non-Swamp land" may target it.
                if perm.has_type("swamp"):
                    return False
            return True
        if kind == "permanent":
            # Colour is settled above the switch; what is left here is the one
            # narrowing only this branch has.
            if spec.get("enchant_enchantment"):
                return "enchantment" in type_line
            return True
        return False

    def _enumerate_cost_hand_cards(
        self, caster_index: int, card: CardDefinition, spec: dict | None = None,
        *, for_cast: bool,
    ) -> list[dict]:
        """The cards that may pay a "discard a card" cost.

        **What is withheld is the whole difference between the two callers.**
        Casting from the hand withholds the spell: CR 601.2a puts it on the
        stack before its costs are paid, so it is not in the hand to be
        discarded (with two copies in hand the *other* is a legal payment, so
        exactly one occurrence goes — the one the hand lookup will cast).
        Casting from anywhere else withholds nothing, for the same reason
        activating does not: the object on the stack came from another zone, so
        a copy sitting in hand is an ordinary card like any other.

        A hint, not the authority: both payment paths re-check the answer on the
        way back in, so a client that offers a whole hand cannot turn the cost
        into "discard nothing".
        """
        hand = self.players[caster_index].hand
        # …and only when the hand is the zone the spell left. A cast from the
        # graveyard (Demonic Embrace) put nothing of the caster's hand on the
        # stack, so a second copy held there is an ordinary card and a legal
        # payment; withholding it would hide the only discard a one-card hand
        # can make.
        leaves_hand = (spec or {}).get("cast_zone", "hand") == "hand"
        spell_index = (
            next((i for i, held in enumerate(hand) if held.name == card.name), None)
            if for_cast and leaves_hand
            else None
        )
        # "Discard a **land card or Shrine card**" (Sanctum of Shattered
        # Heights). The narrowing is applied with the same reader the charger
        # uses, so the picker cannot offer a card the payment then refuses —
        # which is the failure this enumerator exists to prevent, and which the
        # graveyard picker below already had to be fixed for.
        alternatives = (spec or {}).get("filters") or ()
        return [
            {"kind": "hand_card", "seat": caster_index, "hand_index": index, "name": held.name}
            for index, held in enumerate(hand)
            if index != spell_index and card_matches_any(held, alternatives)
        ]

    def _enumerate_graveyard_creatures(self, caster_index: int, spec: dict) -> list[dict]:
        targets: list[dict] = []
        # Reconstruction returns an *artifact* card, Raise Dead a creature card,
        # Chandra a red instant or sorcery. One template with the type as data,
        # and one predicate shared with the cast-time re-check and the handler
        # (`engine/handlers/_common.py`) — a picker that offers what
        # resolution then refuses is the bug this module exists to prevent, and
        # it was live: the re-check asked only "is it a creature card?".

        def eligible(card) -> bool:
            return graveyard_card_matches(spec, card)

        for seat, player in enumerate(self.players):
            if spec.get("own_graveyard_only") and seat != caster_index:
                continue
            # "from **an opponent's** graveyard" (Misinformation) — CR 115.4's
            # own-seat exclusion applied to the *pile* the cards are chosen
            # from. The mirror of the scope above and offered for the same
            # reason: a picker that ignored the printed word would let the
            # caster reach into their own graveyard, which is a different card.
            if spec.get("opponent_graveyard_only") and seat == caster_index:
                continue
            for idx, card in enumerate(player.graveyard):
                if eligible(card):
                    targets.append({"kind": "graveyard", "seat": seat, "index": idx, "name": card.name})
        return targets

    def _enumerate_stack_targets(
        self, caster_index: int, card: CardDefinition, spec: dict, source=None
    ) -> list[dict]:
        """The spells on the stack this spec may point at.

        *caster_index* is the seat doing the pointing, needed because a
        narrowing can be *relative* to it ("that targets a permanent **you**
        control"). It is the same seat ``subject_matches`` calls the observer,
        and CR 109.5 is why it is the counter's controller rather than the
        controller of the spell being looked at.

        *source* is the ability's own permanent, for the one narrowing that is
        an identity rather than a description: "…that targets **this creature**"
        (Mistfolk). A spell is offered only while it is still pointing at that
        permanent, which is what keeps the {U} from being paid for nothing.
        """
        targets: list[dict] = []
        color_filter = spec.get("stack_color_filter")
        instant_sorcery_only = spec.get("stack_instant_sorcery_only")
        # "Counter target **activated ability** from an artifact source" (Rust,
        # Ayesha Tanaka). A spec that asks for abilities offers abilities and
        # nothing else: an ability is not a spell (CR 113.7a) and the two are
        # never interchangeable targets, so this is a different list rather than
        # a wider one.
        ability_kinds = spec.get("stack_ability_kinds")
        if ability_kinds:
            return self._enumerate_stack_ability_targets(spec, ability_kinds)
        depth = len(self.stack)
        for i, item in enumerate(self.stack):
            # Only spells are legal targets — activated/triggered abilities on the
            # stack (which carry an ability_instruction) can't be countered/copied.
            if getattr(item, "ability_instruction", None) is not None:
                continue
            item_card = getattr(item, "card", None)
            if item_card is None:
                continue
            if instant_sorcery_only and item_card.primary_type not in ("instant", "sorcery"):
                continue
            # Miscast: "target instant or sorcery spell" — the union the
            # compiled counter carries, tested here so the picker offers only
            # what the handler would counter.
            stack_card_types = spec.get("stack_card_types")
            if stack_card_types and item_card.primary_type not in stack_card_types:
                continue
            # "target instant or **Aura** spell" (Avoid Fate, Ring of
            # Immortals): the same cross-axis union the handler tests, asked
            # through the same reader, so the picker offers exactly what the
            # counter would counter.
            any_classes = spec.get("stack_any_classes")
            if any_classes:
                from .handlers.stack import _spell_is_one_of_classes

                if not _spell_is_one_of_classes(
                    item_card, [tuple(entry) for entry in any_classes]
                ):
                    continue
            # "…that targets a permanent you control" — asked of the recorded
            # targets of the spell being offered, against the seat whose spell
            # or ability is doing the countering.
            targets_filter = spec.get("stack_targets_filter")
            targets_source = source if spec.get("stack_targets_source") else None
            if targets_filter or targets_source is not None:
                from .handlers.stack import _spell_targets_matching

                if not _spell_targets_matching(
                    self, item, dict(targets_filter or {}), caster_index,
                    source=targets_source,
                ):
                    continue
            # "…**with a single target** [if that target is you]" (Deflection,
            # Reflecting Mirror — CR 115.7a / CR 115.9a). Asked through the one
            # reader the retarget handler asks at resolution, against the same
            # seat every other narrowing here is measured against (CR 109.5) —
            # so a spell the effect could not actually re-aim is never offered,
            # and the mana it would cost is never paid for nothing.
            #
            # A spell whose target set the engine cannot establish answers None
            # and is simply not offered: under-offering is a narrower card,
            # over-offering is a card redirecting spells it was never allowed to.
            #
            # The count and the "is you" are **two** gates because two cards
            # print them separately: Deflection carries only the first.
            if spec.get("stack_single_target"):
                from .targeting import single_spell_target

                chosen = single_spell_target(self, item)
                if chosen is None:
                    continue
                single_target_is = spec.get("stack_single_target_is")
                if single_target_is is not None and not (
                    single_target_is == "you"
                    and chosen.get("kind") == "player"
                    and chosen.get("seat") == caster_index
                ):
                    continue
                # "…and **that target is a creature**" (Meddle). The object half
                # of the same question, asked through `is_creature` — CR 613's
                # answer rather than the printed type line, so an animated land
                # a spell is aimed at is a creature here exactly as it is
                # everywhere else. A permanent that has left is not one.
                wanted_type = spec.get("stack_single_target_type")
                if wanted_type is not None:
                    if chosen.get("kind") != "permanent":
                        continue
                    aimed = self.permanent_by_id(chosen.get("permanent_id"))
                    if aimed is None or not aimed.is_creature:
                        continue
            if color_filter and color_filter not in self._stack_item_colors(item):
                continue
            stack_any_colors = spec.get("stack_any_colors")
            if stack_any_colors:
                item_colors = self._stack_item_colors(item)
                if not any(colour in item_colors for colour in stack_any_colors):
                    continue
            # The UI (and the cast/activate action) index the stack top-first, the
            # reverse of the engine's bottom-first list — emit the top-first index.
            targets.append({"kind": "stack", "stack_index": depth - 1 - i, "name": item_card.name})
        return targets

    def _enumerate_stack_ability_targets(
        self, spec: dict, ability_kinds: list[str]
    ) -> list[dict]:
        """The **abilities** on the stack this spec may point at (CR 113.7a).

        Its own enumeration rather than a widening of the spell one above: an
        ability has no card of its own, so every narrowing a counterspell asks
        of a spell — colour, card type, what it targets — is a question this
        list cannot be asked, and the two it *is* asked (which kind of ability,
        and what kind of permanent it came from) mean nothing to a spell.

        Both are answered through the handler's own readers
        (``_stack_ability_kind``, ``_spell_is_one_of``), so an ability offered
        here is one ``counter_stack_ability`` would counter. Offering one it
        would refuse is not a cosmetic slip: the activation cost is paid before
        the counter resolves, so the tap buys nothing and nothing on screen says
        why.

        A mana ability is never here to be excluded (CR 605.3a: it does not use
        the stack), which is what the printed reminder text says.
        """
        from .handlers.stack import _spell_is_one_of, _stack_ability_kind

        source_types = tuple(spec.get("stack_ability_source_types") or ())
        depth = len(self.stack)
        targets: list[dict] = []
        for i, item in enumerate(self.stack):
            if getattr(item, "ability_instruction", None) is None:
                continue
            kind = _stack_ability_kind(item)
            if kind is None or kind not in ability_kinds:
                continue
            if source_types:
                source = item.source_permanent
                if source is None or not _spell_is_one_of(
                    source.effective_card, source_types
                ):
                    continue
            item_card = getattr(item, "card", None)
            name = item_card.name if item_card is not None else "ability"
            # Top-first, the convention the spell enumeration above emits and
            # the cast/activate action resolves by.
            targets.append({
                "kind": "stack",
                "stack_index": depth - 1 - i,
                "name": f"{name}'s {kind} ability",
            })
        return targets


#: The payload keys a composed instruction nests its steps under, in the order
#: :func:`engine.targeting._from_instructions` reads them. Held to that order on
#: purpose: the picker's *kind* comes from there and its *restriction* comes from
#: here, and two walks that disagreed would offer a target the resolution then
#: declines — the two-readers failure this file exists to prevent.
_COMPOSED_STEP_KEYS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "unless_player_pays": ("unpaid",),
    # An offer's *declined* branch is read last and is read at all for
    # CR 601.2c's reason: Arcum's Whistle chooses its creature as the ability is
    # activated, before anybody is offered the payment.
    "may": ("action", "then", "otherwise"),
}


def _targeting_step(instruction):
    """The instruction inside *instruction* that actually names a target, or
    None when *instruction* is not a composition.

    An ability whose whole effect sits behind an offer or a condition carries
    its printed target restriction on the *inner* step, and the enumerator is
    handed the outer one. Without this, Arcum's Whistle's "target non-Wall
    creature the active player has controlled continuously since the beginning
    of the turn" was a noun phrase the picker never asked about: it offered
    every creature on the board, Walls and new arrivals included, and the
    handler then refused them — a restriction enforced by nothing, which is
    this file's own failure mode.
    """
    keys = _COMPOSED_STEP_KEYS.get(instruction.kind)
    if keys is None:
        return None
    for key in keys:
        for step in instruction.payload.get(key) or ():
            found = _targeting_step(step)
            if found is not None:
                return found
            if step.kind not in _COMPOSED_STEP_KEYS:
                return step
    return None
