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

from .handlers._common import permanent_matches_filter
from .models import CardDefinition, Permanent
from .oracle import compile_card_oracle, expand_modal_activated_lines
from .static_bonuses import conditional_static_holds
from .targeting import (
    derive_activation_spec,
    derive_cast_spec,
    usable_activated_abilities,
)

# An oracle line that begins with a mana/tap cost followed by a colon is an
# activated ability ("{T}: ..."), not a cast-time effect. The cost may mix
# symbols with prose ("{T}, Sacrifice a creature:", "{2}, {T}, Discard the
# last card you drew this turn:"), so after the leading symbol accept anything
# up to the colon — barring a period, which would mean the colon belongs to a
# later sentence rather than to a cost.
_ACTIVATED_LINE_RE = re.compile(r"^\s*\{[^}]+\}[^:.]*:")


def _oracle_lines(card: CardDefinition) -> list[str]:
    # Same modal-activated expansion the compiler applies (Pyramids), so the
    # bullet effects classify as activated-ability lines, not cast effects.
    return expand_modal_activated_lines(card.oracle_text or "").split("\n")


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
    """Aura-derived or flagged; one question, both sources."""
    from .auras import aura_restriction_active

    return bool(perm.metadata.get("cant_be_enchanted_by_auras")) or aura_restriction_active(
        perm, "cant_be_enchanted_by_auras"
    )


# ---------------------------------------------------------------------------
# Activated-ability target classification
# ---------------------------------------------------------------------------

# Activated-ability instruction kinds whose payload carries a finer target
# restriction than the kind alone (a tapped/coloured destroy, a non-Wall attack
# mark). The enumerator gates candidates through these so an ability offers
# exactly what it could legally affect, matching its resolution.
_FILTERABLE_ABILITY_KINDS = {
    "destroy_target_permanent",
    "grant_regeneration_to_target_creature",
    "mark_non_wall_target_to_attack",
    "grant_flying_and_delayed_destruction",
    "grant_unblockable_to_low_power_target",
    "set_base_pt_target_until_eot",
    "steal_creature_while_tapped_and_weaker",
    "tap_target_permanent",
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
_UNDERIVABLE_ABILITY_TARGETS: tuple[tuple[re.Pattern, dict], ...] = (
    (re.compile(r"\buntap target creature\b"), {"kind": "creature"}),
)


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

    def legal_defenders_for_attacker(self, attacker_index: int, permanent_index: int) -> list[int]:
        """Which of ``attacker_index``'s living opponents the creature at
        ``permanent_index`` could legally attack — lets a 3+ player UI offer a
        per-attacker defending-player picker (CR 802.3)."""
        player = self.players[attacker_index]
        if not (0 <= permanent_index < len(player.battlefield)):
            return []
        perm = player.battlefield[permanent_index]
        if not self._is_creature(perm) or perm.tapped or self._is_summoning_sick(perm):
            return []
        return [opp for opp in self.opponents_of(attacker_index) if self.can_attack(perm, opp)]

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
    def cast_target_spec(self, caster_index: int, card: CardDefinition) -> dict:
        """Target spec for casting ``card`` from ``caster_index``'s hand: the target
        kind plus every legal target, enumerated and gated through the engine's own
        cast-target validation so the UI offers exactly what would resolve."""
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
        spec = derive_cast_spec(card, program) or {"kind": "none"}
        spec["requires_target"] = spec["kind"] != "none"
        spec["valid_targets"] = self._enumerate_targets(caster_index, card, spec, for_cast=True)
        return spec

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
        ability_instruction = (
            spec_ability.instruction
            if spec_ability is not None
            and spec_ability.instruction is not None
            and spec_ability.instruction.kind in _FILTERABLE_ABILITY_KINDS
            else None
        )
        spec["requires_target"] = spec["kind"] != "none"
        spec["valid_targets"] = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent,
        )
        # Jade Monolith's second choice — the damage source: any permanent on
        # either battlefield or any spell on the stack.
        if spec.get("requires_source"):
            spec["source_targets"] = self._enumerate_targets(
                controller_index, card, {"kind": "permanent", "also_stack": True},
                for_cast=False,
            )
        return spec

    # -- Target enumeration ------------------------------------------------
    def _enumerate_targets(
        self, caster_index: int, card: CardDefinition, spec: dict, *, for_cast: bool,
        ability_instruction=None, source_permanent=None,
    ) -> list[dict]:
        kind = spec["kind"]
        if kind in ("none", "modal"):
            return []
        if kind == "hand_card":
            return self._enumerate_cost_hand_cards(caster_index, card)
        if kind == "graveyard_creature":
            return self._enumerate_graveyard_creatures(caster_index, spec)
        if kind == "stack":
            return self._enumerate_stack_targets(card, spec)
        if kind == "spell_or_permanent":
            # Lace recolor: legal on any permanent on the battlefield or any spell
            # on the stack. Enumerate both and concatenate. Unsubstantiate narrows
            # the permanent half to creatures via `permanent_kind`.
            perms = self._enumerate_targets(
                caster_index, card, {**spec, "kind": spec.get("permanent_kind", "permanent")},
                for_cast=for_cast, ability_instruction=ability_instruction,
            )
            return perms + self._enumerate_stack_targets(card, spec)

        targets: list[dict] = []
        # Player faces are legal for player-targeted, "any target", and divided
        # spells — but not a divided land selection (Volcanic Eruption's Mountains).
        if kind in ("player", "any", "divided", "player_or_planeswalker") and not spec.get("land_filter"):
            for seat in range(len(self.players)):
                # "target opponent" (Word of Command) can't be the caster's own seat.
                if spec.get("opponents_only") and seat == caster_index:
                    continue
                targets.append({"kind": "player", "seat": seat})
            if kind == "player":
                return targets

        casting_aura = "aura" in _type_line(card)
        for seat, player in enumerate(self.players):
            # A sacrifice cost (Sacrifice) only offers the caster's own creatures.
            if spec.get("own_only") and seat != caster_index:
                continue
            for idx, perm in enumerate(player.battlefield):
                if not self._permanent_matches_target_kind(perm, kind, spec, casting_aura):
                    continue
                if for_cast:
                    ok, _ = self._validate_cast_targets(
                        card, caster_index, target_player_index=seat, target_permanent_index=idx
                    )
                    if not ok:
                        continue
                else:
                    if not self._can_be_targeted(perm, card, caster_index=caster_index):
                        continue
                    # Apply the activated ability's own target restriction (e.g.
                    # Royal Assassin's tapped-only, Nettling Imp's non-Wall) so it
                    # offers only what it could legally affect at resolution.
                    if ability_instruction is not None and not self._ability_target_legal(
                        ability_instruction, perm,
                        candidate_seat=seat, controller_index=caster_index,
                        source_permanent=source_permanent,
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
            targets += self._enumerate_stack_targets(card, {"stack_color_filter": spec.get("color_filter")})
        return targets

    def _ability_target_legal(
        self, instruction, perm: Permanent, *,
        candidate_seat=None, controller_index=None, source_permanent=None,
    ) -> bool:
        """Whether *perm* satisfies an activated ability instruction's own target
        restriction (beyond the text-derived kind)."""
        if instruction.kind == "destroy_target_permanent":
            return self._destroy_target_legal(instruction.payload, perm)
        if instruction.kind == "mark_non_wall_target_to_attack":
            return perm.is_creature and not perm.has_type("wall")
        if instruction.kind == "grant_unblockable_to_low_power_target":
            # Dwarven Warriors: "Target creature with power 2 or less can't be
            # blocked this turn." Only creatures with effective power ≤ 2 are legal,
            # so the UI highlights exactly those.
            return perm.is_creature and perm.effective_power <= 2
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
        if instruction.kind == "steal_creature_while_tapped_and_weaker":
            # Old Man of the Sea: only creatures at or below its own power.
            if not perm.is_creature:
                return False
            return source_permanent is None or perm.effective_power <= source_permanent.effective_power
        if instruction.kind == "grant_regeneration_to_target_creature":
            # Elephant Graveyard's "target Elephant" — the same subtype filter
            # _grant_regeneration_shield enforces at resolution. Death Ward's
            # payload is empty, so every creature passes.
            return perm.is_creature and permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "tap_target_permanent":
            # Ali Baba's "target Wall" (and any other parsed tap-target filter);
            # Icy Manipulator's payload is empty, so everything passes.
            return permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "add_counter_to_target":
            # Tempered Veteran's "target creature with a +1/+1 counter on it" —
            # the same filter the handler enforces at resolution, so the picker
            # offers exactly what the ability could affect. Most counter
            # placements carry an empty filter and every creature passes.
            targets = instruction.payload.get("targets") or {}
            return perm.is_creature and permanent_matches_filter(
                perm, targets.get("filter") or {}
            )
        return True

    def _permanent_matches_target_kind(self, perm: Permanent, kind: str, spec: dict, casting_aura: bool) -> bool:
        # Effective type line so copies match by their copied types — a Copy
        # Artifact copying a Mox is an "Artifact Enchantment" and must be a
        # legal target both as an artifact and as an enchantment.
        type_line = perm.effective_card.type_line.lower()
        if kind == "player_or_planeswalker":
            # "Target player or planeswalker" (Chandra's Magmutt): the only
            # permanents in the union are planeswalkers — the player faces were
            # already added by the seat loop above.
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
                return "wall" in type_line
            # Forcefield: only unblocked attacking creatures are legal choices.
            if spec.get("unblocked_attacker") and not (perm.attacking and not perm.blocked):
                return False
            # Singing Tree: only currently-attacking creatures are legal choices.
            if spec.get("attacking_only") and not perm.attacking:
                return False
            # Island of Wak-Wak: only flying creatures are legal choices.
            if spec.get("flying_only") and not self._has_keyword(perm, "flying"):
                return False
            # Ali Baba: only Walls are legal choices.
            if spec.get("wall_only") and "wall" not in type_line:
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
            color_filter = spec.get("color_filter")
            if color_filter:
                # Layer 5, not the printed line. Deathlace makes a Grizzly Bears
                # black; the *resolution* accepted it and this enumerator did
                # not, so the picker offered nothing while a script could kill
                # it — one question about one permanent with two answers.
                return color_filter in perm.effective_colors
            if spec.get("enchant_enchantment"):
                return "enchantment" in type_line
            return True
        return False

    def _enumerate_cost_hand_cards(self, caster_index: int, card: CardDefinition) -> list[dict]:
        """The cards that may pay a printed "discard a card" additional cost.

        Every card in the caster's hand except the one about to be cast: CR
        601.2a puts the spell on the stack before its costs are paid, so it is
        not there to be discarded. With two copies in hand the *other* one is a
        legal payment, so exactly one occurrence is withheld — the one the hand
        lookup will cast.

        A hint, not the authority: ``_resolve_discard_cost_card`` re-checks the
        answer on the way back in, so a client that offers a whole hand cannot
        turn this into "discard nothing".
        """
        hand = self.players[caster_index].hand
        spell_index = next(
            (i for i, held in enumerate(hand) if held.name == card.name), None
        )
        return [
            {"kind": "hand_card", "seat": caster_index, "hand_index": index, "name": held.name}
            for index, held in enumerate(hand)
            if index != spell_index
        ]

    def _enumerate_graveyard_creatures(self, caster_index: int, spec: dict) -> list[dict]:
        targets: list[dict] = []
        any_card = spec.get("any_card")
        # Reconstruction returns an *artifact* card; Raise Dead a creature card.
        # One template with the type as data, which is why the picker takes it
        # from the spec instead of assuming the creature case.
        #
        # The two branches test differently because their handlers do, and a
        # picker that offers what resolution then refuses is the bug this module
        # exists to prevent. `return_creature_from_graveyard_to_hand` asks
        # whether the type appears in the card's type line, so an Ornithopter —
        # an *artifact* creature — is a legal Reconstruction target (CR 205.2);
        # the reanimators ask `primary_type`, which is narrower.
        card_type = spec.get("card_type")
        # "target red instant or sorcery card" (Chandra, Flame's Catalyst's
        # −2): a *union* of primary types plus a colour, tested exactly as the
        # grant handler tests its choice, so the picker offers what resolution
        # will honour.
        card_types = tuple(spec.get("card_types") or ())
        color_filter = spec.get("graveyard_color_filter")

        def eligible(card) -> bool:
            if card_types and card.primary_type not in card_types:
                return False
            if color_filter and color_filter not in card.colors:
                return False
            if card_types:
                return True
            if any_card:
                return True
            if card_type is not None:
                return card_type in card.type_line.lower()
            return card.primary_type == "creature"

        for seat, player in enumerate(self.players):
            if spec.get("own_graveyard_only") and seat != caster_index:
                continue
            for idx, card in enumerate(player.graveyard):
                if eligible(card):
                    targets.append({"kind": "graveyard", "seat": seat, "index": idx, "name": card.name})
        return targets

    def _enumerate_stack_targets(self, card: CardDefinition, spec: dict) -> list[dict]:
        targets: list[dict] = []
        color_filter = spec.get("stack_color_filter")
        instant_sorcery_only = spec.get("stack_instant_sorcery_only")
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
            if color_filter and color_filter not in self._stack_item_colors(item):
                continue
            # The UI (and the cast/activate action) index the stack top-first, the
            # reverse of the engine's bottom-first list — emit the top-first index.
            targets.append({"kind": "stack", "stack_index": depth - 1 - i, "name": item_card.name})
        return targets
