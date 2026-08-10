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

**The cast-time half no longer reads oracle text.** ``cast_target_spec`` asks
``engine/targeting.py``, which derives the whole spec — kind and flags — from
the compiled program, so there is one parse of a card and nothing to keep in
sync. What is left here is the *enumeration*: given a spec, which permanents,
players, graveyard cards and stack items satisfy it.

Activation is still classified from text by the ``_activated_*`` cascade below.
It is the same shadow-parser shape and the same migration applies — an
activated ability's compiled instruction already narrows the enumeration
(``_FILTERABLE_ABILITY_KINDS``), but the *kind* still comes from the line.
"""

import re
from types import SimpleNamespace

from .handlers._common import permanent_matches_filter
from .models import CardDefinition, Permanent
from .oracle import compile_card_oracle, expand_modal_activated_lines
from .targeting import derive_cast_spec

# An oracle line that begins with a mana/tap cost followed by a colon is an
# activated ability ("{T}: ..."), not a cast-time effect. The cost may mix
# symbols with prose ("{T}, Sacrifice a creature:", "{2}, {T}, Discard the
# last card you drew this turn:"), so after the leading symbol accept anything
# up to the colon — barring a period, which would mean the colon belongs to a
# later sentence rather than to a cost.
_ACTIVATED_LINE_RE = re.compile(r"^\s*\{[^}]+\}[^:.]*:")
# "target land" plus qualified variants ("target non-Swamp land").
_TARGET_LAND_RE = re.compile(r"target (?:[\w-]+ )*land\b")
_COLOR_WORD_TO_SYMBOL = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


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


# The colour a counterspell *ability* is restricted to (Deathgrip, Lifeforce).
# The cast-time counterspells read this off their instruction's `color_filter`
# payload instead; this is what remains until activation migrates too.
def _stack_spell_color_filter(card: CardDefinition) -> str | None:
    m = re.search(r"counter target (\w+) spell", (card.oracle_text or "").lower())
    if not m:
        return None
    return _COLOR_WORD_TO_SYMBOL.get(m.group(1))


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
        # "target creature ... can't be blocked", etc.). "target attacking
        # creature" (Singing Tree) doesn't contain "target creature" as a
        # contiguous substring, so it needs its own check.
        if "target creature" in line or "target attacking creature" in line:
            return True
    return False


def _activated_requires_attacking_creature(card: CardDefinition) -> bool:
    """Singing Tree: "Target attacking creature has base power 0 until end
    of turn." — restricts legal targets to currently-attacking creatures."""
    return any("target attacking creature" in line for line in _activated_lines(card))


def _activated_requires_flying_creature(card: CardDefinition) -> bool:
    """Island of Wak-Wak: "Target creature with flying has base power 0
    until end of turn." — restricts legal targets to fliers."""
    return any("target creature with flying" in line for line in _activated_lines(card))


def _activated_requires_wall(card: CardDefinition) -> bool:
    """Ali Baba: "{R}: Tap target Wall." — restricts legal targets to Walls."""
    return any(re.search(r"\btarget wall\b", line) for line in _activated_lines(card))


def _cant_be_enchanted_by_auras(perm) -> bool:
    """Aura-derived or flagged; one question, both sources."""
    from .auras import aura_restriction_active

    return bool(perm.metadata.get("cant_be_enchanted_by_auras")) or aura_restriction_active(
        perm, "cant_be_enchanted_by_auras"
    )


def _activated_requires_aura_on_land(card: CardDefinition) -> bool:
    """Pyramids mode 1: "Destroy target Aura attached to a land." Must be
    recognized before the land classifier, whose regex would otherwise read
    "...a land" as a land target."""
    return any("target aura attached to a land" in line for line in _activated_lines(card))


def _activated_requires_sacrifice_creature(card: CardDefinition) -> bool:
    """Diamond Valley: "{T}, Sacrifice a creature: …" — the "creature" chosen
    is the caster's own, sacrificed as (part of) the cost, mirroring the
    cast-side "as an additional cost to cast this spell, sacrifice a
    creature" handling."""
    return any("sacrifice a creature" in line for line in _activated_lines(card))


def _activated_requires_artifact(card: CardDefinition) -> bool:
    """Aladdin: "{1}{R}{R}, {T}: Gain control of target artifact ..." — mirrors
    the cast-side artifact classifier, including its carve-out for "target
    artifact, creature, or land" (Icy Manipulator), which is an any-permanent
    target rather than an artifact-only one."""
    for line in _activated_lines(card):
        if "target artifact, creature, or land" in line:
            continue
        if "target artifact" in line and "artifact or enchantment" not in line:
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
    "grant_regeneration_to_target_creature",
    "mark_non_wall_target_to_attack",
    "grant_flying_and_delayed_destruction",
    "grant_unblockable_to_low_power_target",
    "set_base_pt_target_until_eot",
    "steal_creature_while_tapped_and_weaker",
    "tap_target_permanent",
}


def _ability_target_instruction(card: CardDefinition):
    """The activated ability's instruction whose payload restricts its targets,
    or None when no activated ability needs finer-than-kind filtering."""
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = getattr(ability, "instruction", None)
        if instruction is not None and instruction.kind in _FILTERABLE_ABILITY_KINDS:
            return instruction
    return None


def _instruction_targets_by_subtype(instruction) -> bool:
    """Whether *instruction* targets creatures named only by subtype — King
    Suleiman's "target Djinn or Efreet", Elephant Graveyard's "target Elephant".
    Such a line never contains the word "creature", so the text classifiers
    can't see the target; the compiled filter can."""
    if instruction is None or not instruction.payload.get("subtype_filter"):
        return False
    # A subtype filter on a non-creature target (a land subtype, say) isn't a
    # creature prompt.
    return instruction.payload.get("type_filter", "creature") == "creature"


def _activated_requires_unblocked_attacker(card: CardDefinition) -> bool:
    # Forcefield: "an unblocked creature of your choice would deal combat damage to
    # you" — the controller picks one of the unblocked attackers.
    return any("unblocked creature of your choice" in line for line in _activated_lines(card))


def _activated_requires_source_and_creature(card: CardDefinition) -> bool:
    # Jade Monolith: "The next time a source of your choice would deal damage to
    # target creature this turn, that source deals that damage to you instead."
    # Two choices: the creature (primary target) and the damage source.
    return any(
        "a source of your choice would deal damage to target creature" in line
        for line in _activated_lines(card)
    )


def _classify_activation(card: CardDefinition) -> dict:
    if _activated_requires_unblocked_attacker(card):
        return {"kind": "creature", "unblocked_attacker": True}
    cop_color = _activated_color_protection_source(card)
    if cop_color is not None:
        # The chosen source can be a permanent of that color on any battlefield, or
        # a spell of that color on the stack. also_stack folds stack spells into the
        # permanent-target prompt (the engine matches prevention by color).
        return {"kind": "permanent", "color_filter": cop_color, "also_stack": True}
    if _activated_requires_source_and_creature(card):
        # Before the generic creature check, which would otherwise swallow it.
        return {"kind": "creature", "requires_source": True}
    if _activated_requires_attacking_creature(card):
        # Before the generic creature check, which would otherwise swallow it.
        return {"kind": "creature", "attacking_only": True}
    if _activated_requires_flying_creature(card):
        # Before the generic creature check, which would otherwise swallow it.
        return {"kind": "creature", "flying_only": True}
    if _activated_requires_wall(card):
        # Ali Baba — before the generic creature check.
        return {"kind": "creature", "wall_only": True}
    if _activated_requires_sacrifice_creature(card):
        # Before the generic creature check, which would otherwise swallow it.
        # sacrifice_cost mirrors the cast-side spec so the UI can say
        # "sacrifice" rather than "target" (Diamond Valley).
        return {"kind": "creature", "own_only": True, "sacrifice_cost": True}
    if _activated_requires_creature(card):
        return {"kind": "creature"}
    if _activated_requires_artifact(card):
        # Aladdin — before the permanent classifier, which would otherwise offer
        # every permanent for what is an artifact-only target.
        return {"kind": "artifact"}
    if _activated_requires_aura_on_land(card):
        # Pyramids — before the land classifier. The destroy instruction's
        # attached_to_land filter narrows the enumeration to Auras on lands.
        return {"kind": "permanent"}
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
        return any(
            i.kind == "cant_be_blocked" for i in compile_card_oracle(perm.effective_card).instructions
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
        ``permanent_index`` on ``controller_index``'s battlefield. With
        ``ability_index`` (multi-ability cards whose abilities target
        differently — Pyramids), the spec is computed from that ability's own
        line rather than the whole card."""
        player = self.players[controller_index]
        if not (0 <= permanent_index < len(player.battlefield)):
            return {"kind": "none", "requires_target": False, "valid_targets": []}
        source_permanent = player.battlefield[permanent_index]
        # effective_card so a copy (Clone / Vesuvan Doppelganger) offers the
        # copied creature's activated abilities (CR 707.2).
        card = source_permanent.effective_card
        chosen_ability = None
        if ability_index is not None:
            usable = [
                ab for ab in compile_card_oracle(card).activated_abilities
                if ab.supported and ab.instruction is not None
            ]
            if 0 <= ability_index < len(usable):
                chosen_ability = usable[ability_index]
        if chosen_ability is not None:
            # A stand-in whose oracle text is just this ability's line: every
            # _activated_* classifier reads only oracle_text.
            line_card = SimpleNamespace(
                name=card.name,
                type_line=card.type_line,
                oracle_text=chosen_ability.source_line or "",
            )
            spec = _classify_activation(line_card)
        else:
            spec = _classify_activation(card)
        # A Sleight of Mind text change on this permanent retargets a color-word
        # counter (Lifeforce black -> red), so the UI must offer the new color's
        # spells rather than the printed one's.
        if spec.get("stack_color_filter"):
            spec["stack_color_filter"] = self._remap_color_filter(
                source_permanent, spec["stack_color_filter"]
            )
        if chosen_ability is not None:
            ability_instruction = (
                chosen_ability.instruction
                if chosen_ability.instruction.kind in _FILTERABLE_ABILITY_KINDS
                else None
            )
        else:
            ability_instruction = _ability_target_instruction(card)
        if spec["kind"] == "none" and _instruction_targets_by_subtype(ability_instruction):
            # King Suleiman ("Destroy target Djinn or Efreet"), Elephant Graveyard
            # ("Regenerate target Elephant"): the line names a creature subtype and
            # never the word "creature", so the textual classifiers above see no
            # target at all. The compiled instruction's filters — which are what
            # resolution enforces — do, so the prompt is derived from them and
            # _ability_target_legal narrows the list to the named subtype.
            spec["kind"] = "creature"
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
            return perm.is_creature and "wall" not in perm.card.type_line.lower()
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
        return True

    def _permanent_matches_target_kind(self, perm: Permanent, kind: str, spec: dict, casting_aura: bool) -> bool:
        # Effective type line so copies match by their copied types — a Copy
        # Artifact copying a Mox is an "Artifact Enchantment" and must be a
        # legal target both as an artifact and as an enchantment.
        type_line = perm.effective_card.type_line.lower()
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
            if not perm.is_creature:
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
                return color_filter in perm.card.colors
            if spec.get("enchant_enchantment"):
                return "enchantment" in type_line
            return True
        return False

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

        def eligible(card) -> bool:
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
            if color_filter and color_filter not in self._stack_item_colors(item):
                continue
            # The UI (and the cast/activate action) index the stack top-first, the
            # reverse of the engine's bottom-first list — emit the top-first index.
            targets.append({"kind": "stack", "stack_index": depth - 1 - i, "name": item_card.name})
        return targets
