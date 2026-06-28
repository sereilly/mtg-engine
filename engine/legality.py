from __future__ import annotations

"""Authoritative legality queries for the web UI.

The browser used to re-derive which creatures may attack, which blocks are legal,
and which permanents/players are legal targets for a spell or ability by parsing
oracle text client-side. That duplicated engine rules and drifted from them. This
module centralises those queries on the backend so the server is the single source
of truth: it computes the legal choices and the web layer ships them to the
frontend (see ``web/app.py`` serialization), which only renders and validates
clicks against the supplied lists.

Two concerns live here:

* Combat legality — ``legal_attacker_indices`` / ``legal_blocker_assignments``
  mirror the acceptance checks in the declare-attackers/blockers steps so the UI
  offers exactly the assignments the engine would accept.
* Target legality — ``cast_target_spec`` / ``activation_target_spec`` classify
  what a spell/ability targets and enumerate every legal target, gating spell
  targets through the engine's own ``_validate_cast_targets`` so protection,
  colour/type filters, and shroud are enforced identically to resolution.

The target-kind classification mirrors the (now-removed) client cascades exactly;
keep the two ``_CAST`` / ``_ACTIVATED`` orderings faithful to the engine's parse
rules when adding cards.
"""

import re

from .models import CardDefinition, Permanent
from .mixins.stack_casting import aura_enchant_noun
from .oracle import compile_card_oracle

# An oracle line that begins with a mana/tap cost followed by a colon is an
# activated ability ("{T}: ..."), not a cast-time effect.
_ACTIVATED_LINE_RE = re.compile(r"^\s*(\{[^}]+\}[,\s]*)+:")
# "target land" plus qualified variants ("target non-Swamp land").
_TARGET_LAND_RE = re.compile(r"target (?:[\w-]+ )*land\b")
_COLOR_WORD_TO_SYMBOL = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


def _oracle_lines(card: CardDefinition) -> list[str]:
    return (card.oracle_text or "").split("\n")


def _cast_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that are *not* activated abilities (cast effects)."""
    return [line.lower() for line in _oracle_lines(card) if not _ACTIVATED_LINE_RE.match(line)]


def _activated_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that *are* activated abilities."""
    return [line.lower() for line in _oracle_lines(card) if _ACTIVATED_LINE_RE.match(line)]


def _type_line(card: CardDefinition) -> str:
    return (card.type_line or "").lower()


# ---------------------------------------------------------------------------
# Cast-time target classification (mirrors the client cardRequiresTarget* cascade)
# ---------------------------------------------------------------------------

def _reanimates_own_graveyard_only(card: CardDefinition) -> bool:
    return "your graveyard" in (card.oracle_text or "").lower()


def _cast_requires_graveyard_creature(card: CardDefinition) -> bool:
    text = (card.oracle_text or "").lower()
    if "enchant creature card in a graveyard" in text:
        return True
    if "target creature card" in text and "graveyard" in text:
        return True
    return False


def _cast_requires_graveyard_card(card: CardDefinition) -> bool:
    """Regrowth: "Return target card from your graveyard to your hand." Targets any
    card in a graveyard, not just a creature card."""
    text = (card.oracle_text or "").lower()
    return "target card from your graveyard" in text or (
        "target card" in text and "graveyard" in text and "creature card" not in text
    )


def _cast_requires_land(card: CardDefinition) -> bool:
    return any("target land" in t or "enchant land" in t for t in _cast_lines(card))


def _cast_requires_artifact(card: CardDefinition) -> bool:
    for t in _cast_lines(card):
        if "enchant artifact" in t:
            return True
        # "target artifact, creature, or land" (Twiddle) is any permanent, not an
        # artifact-only target — let it fall through to the permanent classification.
        if "target artifact, creature, or land" in t:
            continue
        if "target artifact" in t and "artifact or enchantment" not in t:
            return True
    return False


def _cast_offers_copy_creature(card: CardDefinition) -> bool:
    return "enter as a copy of any creature on the battlefield" in (card.oracle_text or "").lower()


def _cast_offers_copy_artifact(card: CardDefinition) -> bool:
    return "enter as a copy of any artifact on the battlefield" in (card.oracle_text or "").lower()


def _cast_requires_creature(card: CardDefinition) -> bool:
    if "enchant creature card in a graveyard" in (card.oracle_text or "").lower():
        return False
    for t in _cast_lines(card):
        if "target creature card" in t:
            continue
        if "enchant creature" in t or "enchant wall" in t:
            return True
        if "destroy target" in t and (re.search(r"\bcreature\b", t) or re.search(r"\bwall\b", t)):
            return True
        if "target creature gets" in t or "target creature gains" in t:
            return True
        if "target blocking creature" in t:
            return True
        if "regenerate target creature" in t:
            return True
        if "exile target creature" in t:
            return True
        if "damage to target creature" in t:
            return True
        if "return target creature" in t:
            return True
        # Catch-all for any other "target creature" spell (Blaze of Glory's "target
        # creature ... can block", False Orders' "remove target creature from
        # combat", …). "target creature card" was already skipped above.
        if "target creature" in t and "target artifact, creature, or land" not in t:
            return True
    return False


def _cast_requires_permanent(card: CardDefinition) -> bool:
    for t in _cast_lines(card):
        if "target spell or permanent" in t:
            return True
        # "target artifact, creature, or land" (Twiddle) is any permanent.
        if "target artifact, creature, or land" in t:
            return True
        if "target permanent" in t and "target land" not in t and "target creature" not in t:
            return True
        if "destroy target artifact or enchantment" in t:
            return True
        if "enchant enchantment" in t:
            return True
    return False


def _cast_requires_spell_or_permanent(card: CardDefinition) -> bool:
    # The "lace" recolor spells ("Target spell or permanent becomes <color>") may
    # target either a permanent on the battlefield or a spell on the stack. The
    # text-change spells ("change the text of target spell or permanent") keep the
    # plain "permanent" classification — their own flows handle them.
    return any("target spell or permanent becomes" in t for t in _cast_lines(card))


def _cast_requires_stack_spell(card: CardDefinition) -> bool:
    for t in _cast_lines(card):
        if "counter target" in t or ("copy target" in t and "spell" in t):
            return True
    return False


def _cast_requires_divided(card: CardDefinition) -> bool:
    t = (card.oracle_text or "").lower()
    return "divided" in t and "among any number of targets" in t


def _cast_requires_any(card: CardDefinition) -> bool:
    return any("any target" in t for t in _cast_lines(card))


def _cast_requires_player(card: CardDefinition) -> bool:
    return any("target player" in t for t in _cast_lines(card))


def _stack_spell_color_filter(card: CardDefinition) -> str | None:
    m = re.search(r"counter target (\w+) spell", (card.oracle_text or "").lower())
    if not m:
        return None
    return _COLOR_WORD_TO_SYMBOL.get(m.group(1))


def _stack_instant_sorcery_only(card: CardDefinition) -> bool:
    return "copy target instant or sorcery spell" in (card.oracle_text or "").lower()


def _land_excludes_swamp(card: CardDefinition) -> bool:
    return "non-swamp land" in (card.oracle_text or "").lower()


def _cast_requires_target_mountains(card: CardDefinition) -> bool:
    # Volcanic Eruption: "Destroy X target Mountains." The controller picks the X
    # Mountains to destroy (X = how many are chosen).
    t = (card.oracle_text or "").lower()
    return "destroy" in t and "target mountain" in t


def _classify_cast(card: CardDefinition) -> dict:
    """Return ``{"kind": ..., **flags}`` for the spell's cast-time target, mirroring
    the client cascade order. Modal "Choose one —" spells are reported as ``modal``
    so the UI runs its mode-choice flow (each mode carries its own spec)."""
    if _cast_requires_graveyard_card(card):
        return {"kind": "graveyard_creature", "own_graveyard_only": True, "any_card": True}
    if _cast_requires_graveyard_creature(card):
        return {"kind": "graveyard_creature", "own_graveyard_only": _reanimates_own_graveyard_only(card)}
    if _cast_requires_target_mountains(card):
        # A multi-target land selection: the player picks the Mountains and X equals
        # the number chosen, so the divided flow skips its separate X prompt.
        return {"kind": "divided", "land_filter": "mountain", "x_equals_targets": True}
    if _cast_requires_land(card):
        return {"kind": "land", "exclude_swamp": _land_excludes_swamp(card)}
    if _cast_requires_artifact(card):
        return {"kind": "artifact"}
    if _cast_offers_copy_creature(card):
        return {"kind": "creature", "optional": True}
    if _cast_offers_copy_artifact(card):
        return {"kind": "artifact", "optional": True}
    if _cast_requires_creature(card):
        return {"kind": "creature", "enchant_wall": "enchant wall" in (card.oracle_text or "").lower()}
    if _cast_requires_spell_or_permanent(card):
        return {"kind": "spell_or_permanent"}
    if _cast_requires_permanent(card):
        return {"kind": "permanent", "enchant_enchantment": "enchant enchantment" in (card.oracle_text or "").lower()}
    if _cast_requires_stack_spell(card):
        return {
            "kind": "stack",
            "stack_color_filter": _stack_spell_color_filter(card),
            "stack_instant_sorcery_only": _stack_instant_sorcery_only(card),
        }
    if _cast_requires_divided(card):
        return {"kind": "divided"}
    if _cast_requires_any(card):
        return {"kind": "any"}
    if _cast_requires_player(card):
        return {"kind": "player"}
    return {"kind": "none"}


# ---------------------------------------------------------------------------
# Activated-ability target classification (mirrors the client activatedAbility* cascade)
# ---------------------------------------------------------------------------

def _activated_destroy_permanent_color(card: CardDefinition):
    """Returns a colour symbol, ``None`` (uncoloured "destroy target permanent"),
    or the sentinel ``False`` meaning no such ability exists at all."""
    for line in _activated_lines(card):
        m = re.search(r"destroy target (white|blue|black|red|green)? ?permanent", line)
        if m:
            return _COLOR_WORD_TO_SYMBOL.get(m.group(1)) if m.group(1) else None
    return False


def _activated_color_protection_source(card: CardDefinition):
    """Circle of Protection: "{cost}: The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." Returns the color
    symbol of the source the controller chooses, or None when no such ability."""
    for line in _activated_lines(card):
        m = re.search(r"a (white|blue|black|red|green) source of your choice would deal damage to you", line)
        if m:
            return _COLOR_WORD_TO_SYMBOL.get(m.group(1))
    return None


def _activated_requires_creature(card: CardDefinition) -> bool:
    for line in _activated_lines(card):
        if "target artifact, creature, or land" in line:
            continue  # any-permanent target (Icy Manipulator), handled separately
        if (("destroy target" in line or "choose target" in line)
                and (re.search(r"\bcreature\b", line) or re.search(r"\bwall\b", line))):
            return True
        if "damage to target creature" in line:
            return True
        # Catch-all for any other "target creature" ability (Dwarven Warriors'
        # "target creature ... can't be blocked", etc.).
        if "target creature" in line:
            return True
    return False


def _activated_requires_permanent(card: CardDefinition) -> bool:
    # "Tap target artifact, creature, or land" (Icy Manipulator) targets any
    # permanent; "target permanent" abilities likewise.
    for line in _activated_lines(card):
        if "target artifact, creature, or land" in line:
            return True
        if "target permanent" in line:
            return True
    return False


def _activated_requires_creature_grant(card: CardDefinition) -> bool:
    return any(
        "target creature" in line and ("gains" in line or "gets" in line)
        for line in _activated_lines(card)
    )


def _activated_requires_land(card: CardDefinition) -> bool:
    return any(_TARGET_LAND_RE.search(line) for line in _activated_lines(card))


def _activated_land_excludes_swamp(card: CardDefinition) -> bool:
    return any(_TARGET_LAND_RE.search(line) and "non-swamp land" in line for line in _activated_lines(card))


def _activated_requires_stack_spell(card: CardDefinition) -> bool:
    return any("counter target" in line and "spell" in line for line in _activated_lines(card))


def _activated_requires_any(card: CardDefinition) -> bool:
    return any("any target" in line for line in _activated_lines(card))


def _activated_requires_player(card: CardDefinition) -> bool:
    return any("target player" in line for line in _activated_lines(card))


# Activated-ability instruction kinds whose payload carries a finer target
# restriction than the text-derived kind (a tapped/coloured destroy, a non-Wall
# attack mark). The enumerator gates candidates through these so an ability offers
# exactly what it could legally affect, matching its resolution.
_FILTERABLE_ABILITY_KINDS = {
    "destroy_target_permanent",
    "mark_non_wall_target_to_attack",
    "grant_flying_and_delayed_destruction",
}


def _ability_target_instruction(card: CardDefinition):
    """The activated ability's instruction whose payload restricts its targets,
    or None when no activated ability needs finer-than-kind filtering."""
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = getattr(ability, "instruction", None)
        if instruction is not None and instruction.kind in _FILTERABLE_ABILITY_KINDS:
            return instruction
    return None


def _activated_requires_unblocked_attacker(card: CardDefinition) -> bool:
    # Forcefield: "an unblocked creature of your choice would deal combat damage to
    # you" — the controller picks one of the unblocked attackers.
    return any("unblocked creature of your choice" in line for line in _activated_lines(card))


def _classify_activation(card: CardDefinition) -> dict:
    if _activated_requires_unblocked_attacker(card):
        return {"kind": "creature", "unblocked_attacker": True}
    cop_color = _activated_color_protection_source(card)
    if cop_color is not None:
        # The chosen source can be a permanent of that color on any battlefield, or
        # a spell of that color on the stack. also_stack folds stack spells into the
        # permanent-target prompt (the engine matches prevention by color).
        return {"kind": "permanent", "color_filter": cop_color, "also_stack": True}
    if _activated_requires_creature(card):
        return {"kind": "creature"}
    if _activated_requires_permanent(card):
        return {"kind": "permanent"}
    color = _activated_destroy_permanent_color(card)
    if color is not False:
        return {"kind": "permanent", "color_filter": color}
    if _activated_requires_land(card):
        return {"kind": "land", "exclude_swamp": _activated_land_excludes_swamp(card)}
    if _activated_requires_creature_grant(card):
        return {"kind": "creature"}
    if _activated_requires_stack_spell(card):
        return {"kind": "stack", "stack_color_filter": _stack_spell_color_filter(card)}
    if _activated_requires_any(card):
        return {"kind": "any"}
    if _activated_requires_player(card):
        return {"kind": "player"}
    return {"kind": "none"}


class LegalityMixin:
    """Backend legality queries surfaced to the web UI. Composed onto ``Game``."""

    # -- Combat ------------------------------------------------------------
    def legal_attacker_indices(self, attacker_index: int) -> list[int]:
        """Battlefield indices of creatures that may legally be declared as
        attackers this turn — untapped, not summoning sick, and allowed to attack
        the opponent (mirrors the declare-attackers acceptance checks)."""
        player = self.players[attacker_index]
        opponent_index = 1 - attacker_index
        return [
            idx
            for idx, perm in enumerate(player.battlefield)
            # _is_creature so animated lands (Kormus Bell, Living Lands) are offered.
            if self._is_creature(perm)
            and not perm.tapped
            and not self._is_summoning_sick(perm)
            and self.can_attack(perm, opponent_index)
        ]

    def legal_blocker_assignments(self, defender_index: int) -> list[dict[str, int]]:
        """Every legal ``{"blocker_index", "attacker_index"}`` pair for the
        defending player, mirroring ``declare_blockers`` acceptance (creature,
        untapped, ``_can_block_attacker``, and Raging River pile restrictions)."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return []
        if self.combat_defending_player_index != defender_index:
            return []
        defender = self.players[defender_index]
        attacker_controller = self.players[self.active_player_index]
        pairs: list[dict[str, int]] = []
        for blocker_idx, blocker in enumerate(defender.battlefield):
            if blocker.card.primary_type != "creature" or blocker.tapped:
                continue
            for attacker_idx in self.combat_attackers:
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
        if len(compile_card_oracle(card).modes) >= 2:
            return {"kind": "modal", "requires_target": False, "valid_targets": []}
        spec = _classify_cast(card)
        spec["requires_target"] = spec["kind"] != "none"
        spec["valid_targets"] = self._enumerate_targets(caster_index, card, spec, for_cast=True)
        return spec

    def enumerate_targets_for_kind(self, caster_index: int, card: CardDefinition, kind: str, **flags) -> list[dict]:
        """Enumerate legal targets for a pre-classified target ``kind`` (used by the
        web layer to fill in valid targets for each mode of a modal spell, whose
        kind is derived from the chosen mode's instruction rather than card text)."""
        spec = {"kind": kind, **flags}
        return self._enumerate_targets(caster_index, card, spec, for_cast=False)

    def activation_target_spec(self, controller_index: int, permanent_index: int) -> dict:
        """Target spec for activating the ability of the permanent at
        ``permanent_index`` on ``controller_index``'s battlefield."""
        player = self.players[controller_index]
        if not (0 <= permanent_index < len(player.battlefield)):
            return {"kind": "none", "requires_target": False, "valid_targets": []}
        source_permanent = player.battlefield[permanent_index]
        card = source_permanent.card
        spec = _classify_activation(card)
        spec["requires_target"] = spec["kind"] != "none"
        spec["valid_targets"] = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=_ability_target_instruction(card),
            source_permanent=source_permanent,
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
        if kind == "graveyard_creature":
            return self._enumerate_graveyard_creatures(caster_index, spec)
        if kind == "stack":
            return self._enumerate_stack_targets(card, spec)
        if kind == "spell_or_permanent":
            # Lace recolor: legal on any permanent on the battlefield or any spell
            # on the stack. Enumerate both and concatenate.
            perms = self._enumerate_targets(
                caster_index, card, {**spec, "kind": "permanent"},
                for_cast=for_cast, ability_instruction=ability_instruction,
            )
            return perms + self._enumerate_stack_targets(card, spec)

        targets: list[dict] = []
        # Player faces are legal for player-targeted, "any target", and divided
        # spells — but not a divided land selection (Volcanic Eruption's Mountains).
        if kind in ("player", "any", "divided") and not spec.get("land_filter"):
            for seat in range(len(self.players)):
                targets.append({"kind": "player", "seat": seat})
            if kind == "player":
                return targets

        casting_aura = "aura" in _type_line(card)
        for seat, player in enumerate(self.players):
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
                    if not self._can_be_targeted(perm, card):
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
            return perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
        if instruction.kind == "grant_flying_and_delayed_destruction":
            # Stone Giant: "Target creature you control with toughness less than
            # this creature's power." Only the activating player's creatures with
            # toughness below the source's power are legal.
            if candidate_seat is not None and controller_index is not None and candidate_seat != controller_index:
                return False
            if source_permanent is not None and perm.effective_toughness >= source_permanent.effective_power:
                return False
            return perm.card.primary_type == "creature"
        return True

    def _permanent_matches_target_kind(self, perm: Permanent, kind: str, spec: dict, casting_aura: bool) -> bool:
        type_line = perm.card.type_line.lower()
        if kind in ("creature", "any", "divided"):
            # Volcanic Eruption: a divided spell that targets Mountains, not creatures.
            land_filter = spec.get("land_filter")
            if land_filter:
                if perm.card.primary_type != "land":
                    return False
                override = str(perm.metadata.get("land_type_override", "")).lower()
                return land_filter in type_line or override == land_filter
            if perm.card.primary_type != "creature":
                return False
            if spec.get("enchant_wall"):
                return "wall" in type_line
            # Forcefield: only unblocked attacking creatures are legal choices.
            if spec.get("unblocked_attacker") and not (perm.attacking and not perm.blocked):
                return False
            return True
        if kind == "artifact":
            return "artifact" in type_line
        if kind == "land":
            if perm.card.primary_type != "land":
                return False
            if casting_aura and perm.metadata.get("cant_be_enchanted_by_auras"):
                return False
            if spec.get("exclude_swamp"):
                override = str(perm.metadata.get("land_type_override", "")).lower()
                if "swamp" in type_line or override == "swamp":
                    return False
            return True
        if kind == "permanent":
            color_filter = spec.get("color_filter")
            if color_filter:
                return color_filter in perm.card.colors
            if spec.get("enchant_enchantment"):
                return "enchantment" in type_line
            return True
        return False

    def _enumerate_graveyard_creatures(self, caster_index: int, spec: dict) -> list[dict]:
        targets: list[dict] = []
        any_card = spec.get("any_card")
        for seat, player in enumerate(self.players):
            if spec.get("own_graveyard_only") and seat != caster_index:
                continue
            for idx, card in enumerate(player.graveyard):
                if any_card or card.primary_type == "creature":
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
            if color_filter and color_filter not in self._stack_item_colors(item):
                continue
            # The UI (and the cast/activate action) index the stack top-first, the
            # reverse of the engine's bottom-first list — emit the top-first index.
            targets.append({"kind": "stack", "stack_index": depth - 1 - i, "name": item_card.name})
        return targets
