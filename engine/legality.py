from __future__ import annotations

"""Authoritative legality queries for the web UI.

The browser used to re-derive which creatures may attack, which blocks are legal,
and which permanents/players are legal targets for a spell or ability by parsing
oracle text client-side. That duplicated engine rules and drifted from them. This
module centralises those queries on the backend so the server is the single source
of truth: it computes the legal choices and the web layer ships them to the
frontend (see ``web/serialization.py``), which only renders and validates
clicks against the supplied lists.

Two concerns:

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
keep in sync. What is left is the *enumeration*: given a spec, which
permanents, players, graveyard cards and stack items satisfy it.

One line shape survives as a text fallback, named and measured in
:data:`_UNDERIVABLE_ABILITY_TARGETS`, because the program genuinely cannot
describe it.

**Where each part lives.** ``LegalityMixin`` here is the combat half; the
target half is six mixins composed onto ``Game`` directly after it, one subject
each, and this module keeps the module-level spec helpers every one of them
reads (the obligation functions, the text fallback, the kind sets):

* ``engine/legality_cast_spec.py`` — what a spell may be announced with: its
  picker (``cast_target_spec``), its X, its optional costs
  (``cast_cost_offers``);
* ``engine/legality_roles.py`` — several targets of different kinds, offered
  and re-checked;
* ``engine/legality_abilities.py`` — an ability's picker and the activation
  gate (``activation_target_refusal``), and a modal trigger's modes;
* ``engine/legality_cast_gates.py`` — the CR 601.2c gates a spell's
  announcement passes (``no_legal_cast_target_refusal``,
  ``cast_target_refusal``) and which modes are announceable;
* ``engine/legality_stack.py`` — targets on the stack, enumerated and gated;
* ``engine/legality_resolution.py`` — CR 608.2b, as an object resolves
  (``illegal_targets_refusal``, ``blank_illegal_resolution_targets``);
* ``engine/legality_enumeration.py`` — the enumeration itself
  (``_enumerate_targets``), the one list every other part compares against.
"""

import re

from .models import CardDefinition, Permanent
from .combat_restrictions import restriction_condition_holds
from .oracle import compile_card_oracle, expand_ability_lines
from .oracle_types import strip_ability_word
from .static_bonuses import conditional_static_holds
from .target_requirements import cast_is_bound
from .targeting import (
    GRAVEYARD_TARGET_KIND,
    SINGLE_GRAVEYARD,
    ROLES_TARGET_KIND,
    _nested_steps,
    activation_target_slot,
    announced_mode_instructions,
    cast_target_slot,
    derive_activation_spec,
    derive_cast_spec,
    derive_instruction_spec,
    slot_list_is_exact,
    spec_is_a_cost,
    spec_roles,
)


def _unnamed_single_pile_refusal(card, spec: dict, seat) -> str | None:
    """Why graveyard slots named for "…target cards from **a single**
    graveyard" may not be accepted without the seat whose graveyard they are
    in, or None.

    The relation across the targets (``targeting.SINGLE_GRAVEYARD``) is held by
    the announcement's own shape: one seat, and slots counted into that seat's
    pile — a split across two graveyards cannot be spelled. What *can* be
    spelled is slots with no seat, and both gates read that as "legal in any
    pile the enumeration offers", so slot 0 could be one player's card and slot
    1 another's while ``Game.graveyard_target_seat`` resolved both out of the
    caster's own. So the pile is part of the announcement here and has to be
    said. Asked by the cast gate and the activation gate alike.
    """
    if spec.get(SINGLE_GRAVEYARD) and seat is None:
        return f"{card.name}: name the graveyard its targets are in"
    return None


def _iter_instruction_tree(instruction):
    """*instruction* and every instruction nested inside it.

    Through ``targeting._nested_steps``, which is the one table saying which
    payload keys a wrapper carries its children under — a second walker beside
    it would answer differently the day a wrapper kind is added, and that table
    exists because exactly that happened to ``if_then``.
    """
    if instruction is None:
        return
    stack = [instruction]
    while stack:
        step = stack.pop()
        yield step
        stack.extend(_nested_steps(step))

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
# "**Put** a -0/-1 counter on this creature:" (Wall of Roots) and "**Put** a
# card from your hand on top of your library:" (Hidden Retreat). The word was
# missing, so both lines read as *cast-time* effects — which is the failure this
# comment describes one paragraph up, found from the other end: Hidden Retreat's
# "target instant or sorcery spell" was read as the enchantment's own cast
# target, so the picker sweep reported a spell with no picker and the cast gate
# would have asked for a target the card does not choose.
_COST_VERBS = (
    r"sacrifice|tap|discard|exile|pay|put|remove|return|reveal|untap"
)
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


def _is_activated_line(line: str) -> bool:
    """Whether a printed line is an activated ability (CR 602.1).

    Asked of the line **without its ability word**. "Domain — {3}, {T}: Target
    creature gets …" (Power Armor) is an activated ability with an italic word
    in front of it, and CR 207.2c gives that word no rules meaning — the
    compiler drops it through the same ``strip_ability_word`` before it
    classifies anything. Asked of the raw line the anchor fails on "Domain",
    the ability reads as a cast-time effect, and the guard asking "does this
    card name a target as it is cast?" answers yes about an artifact that
    chooses nothing until its ability is activated. Power Armor is the first
    card in the pool to print the pair; the other ability words here all sit in
    front of triggers and statics.
    """
    return bool(_ACTIVATED_LINE_RE.match(strip_ability_word(line)))


def _cast_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that are *not* activated abilities (cast effects).

    Nothing here classifies a cast target from text any more — the complement of
    :func:`_activated_lines` is kept because the guard that replaced the cascade
    needs the same split to ask "does this card name a target as it is cast?",
    and defining it twice is how the two would come to disagree.
    """
    return [line.lower() for line in _oracle_lines(card) if not _is_activated_line(line)]


def _activated_lines(card: CardDefinition) -> list[str]:
    """Lowercased oracle lines that *are* activated abilities."""
    return [line.lower() for line in _oracle_lines(card) if _is_activated_line(line)]


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
# Activated-ability target classification
# ---------------------------------------------------------------------------

# Activated-ability instruction kinds whose payload carries a finer target
# restriction than the kind alone (a tapped/coloured destroy, a non-Wall attack
# mark). The enumerator gates candidates through these so an ability offers
# exactly what it could legally affect, matching its resolution.
def _cast_picker_is_a_target(card: CardDefinition, mode_index: int | None) -> bool:
    """Whether the picker in front of casting *card* (in *mode_index*, for a
    modal spell) chooses a **target** — the printed-word half of
    ``stack_targets``' two-evidence rule, asked before a target requirement is
    applied to it.

    A derived spec alone over-answers: the Circles' "a source of your choice"
    and two graveyard picks derive a picker with no ``source_of_choice`` flag,
    and a requirement read off the spec would demand a Flagbearer be chosen as
    a *source*. An Aura targets by CR 115.1b with no printed word at all; any
    other permanent spell targets nothing (its picker is an entry trigger's).
    """
    from .stack_targets import _spell_names_a_target, names_a_target

    if not cast_is_bound(card):
        return False
    if card.primary_type not in ("instant", "sorcery"):
        return True
    modes = compile_card_oracle(card).modes
    if modes:
        index = 0 if mode_index is None else mode_index
        return 0 <= index < len(modes) and names_a_target(modes[index].label)
    return _spell_names_a_target(card)


def _ability_picker_is_a_target(ability) -> bool:
    """The activation twin of :func:`_cast_picker_is_a_target`: whether
    *ability*'s own printed line says "target" about a choice it makes."""
    from .stack_targets import names_a_target

    return names_a_target(getattr(ability, "source_line", None))


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

    **"Chooses nothing" has two spellings and the scan must treat them alike.**
    ``None`` is "no evidence in the program"; ``{"kind": "none"}`` is the
    derivation saying *positively* that the ability points at nothing (Dream
    Coat's colour, Knight of Dawn's). Returning the second one the moment it is
    seen would end the scan on an ability that chooses nothing — which is the
    thing this loop exists to skip past — so a permanent whose first ability
    recolours itself and whose second destroys a creature would show the
    first's empty prompt. The positive answer is kept and returned only when no
    later ability chooses anything, so it still reaches a caller that asked
    about that one ability alone.
    """
    nothing_to_point_at = None
    for ability in abilities:
        spec = derive_activation_spec(ability)
        if spec is None:
            spec = _fallback_activation_spec(getattr(ability, "source_line", ""))
        if spec is None:
            continue
        if spec.get("kind") == "none":
            if nothing_to_point_at is None:
                nothing_to_point_at = (spec, ability)
            continue
        return _with_dependent_seat_slots(spec, ability), ability
    if nothing_to_point_at is not None:
        return nothing_to_point_at
    return {"kind": "none"}, None


#: Spec kinds whose answer is a **seat**, and so the kinds a later slot can be
#: narrowed *against*. "Any target" and a divided one are deliberately absent:
#: their answer may be an object instead, and a slot narrowed against a seat
#: nobody chose is a restriction with nothing behind it.
_SEAT_ANSWER_SPEC_KINDS = frozenset({"player", "player_or_planeswalker"})

#: Spec kinds whose announced target **may be** a player, and so the kinds for
#: which a seat named with nothing else is the target itself rather than the
#: battlefield a permanent target sits on. Wider than the set above by "any
#: target", whose answer may be a seat or an object.
_SEAT_TARGET_SPEC_KINDS = frozenset({"player", "any", "player_or_planeswalker"})


def _with_dependent_seat_slots(spec: dict, ability) -> dict:
    """*spec* plus the later slots narrowed by the seat it chooses.

    "{B}, {T}: Choose target opponent … **Destroy target nonblack creature that
    player controls**" (Keeper of the Dead). CR 602.2b announces both targets as
    the ability is activated, and the derivation answers with the **first**
    description it finds — so the second slot's board was narrowed by nothing,
    the ability was activatable against an opponent with no nonblack creature,
    and the tap and the mana bought "no valid target permanent found".

    Attached here, in the one funnel the picker (``activation_target_spec``) and
    the announcement gate (``activation_target_refusal``) both read, so the two
    cannot come to disagree about which seats are offered — the failure this
    file exists to prevent, and the one a check bolted onto the gate alone would
    have introduced.

    What it carries is each dependent slot's own spec. The seat loop in
    ``_enumerate_targets`` re-asks it per candidate seat, which is the only
    place that can: whether a seat can fill the second slot is a question about
    a board, and no flag on the first slot could hold the answer.

    Only for a spec whose answer **is** a seat, and only for a slot the
    enumerator can actually narrow to one (``that_player_only``). A slot it
    could not narrow would be enumerated as "every permanent in the game", which
    would make every seat pass and the restriction mean nothing — the silent
    widening, arriving through the check meant to remove one.

    *Which* object then fills that slot is still the handler's pick at
    resolution rather than the activator's choice: the roles walk that would
    need is permanent-only, and a seat cannot be a role in it. That remainder is
    SET_PLAYBOOK's Known gaps, not something this quietly covers.
    """
    if not spec or spec.get("kind") not in _SEAT_ANSWER_SPEC_KINDS:
        return spec
    instruction = getattr(ability, "instruction", None)
    if instruction is None:
        return spec
    slots = []
    for step, quantifier in _announced_target_slots(instruction):
        if quantifier != "target":
            continue
        step_spec = derive_instruction_spec([step])
        if step_spec and step_spec.get("that_player_only"):
            slots.append(step_spec)
    if not slots:
        return spec
    return {**spec, "dependent_slots": slots}


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
#: ``prevent_damage_by_target_spell_until_eot`` (Hidden Retreat) is
#: ``counter_stack_ability``'s row again, for a *spell*: the noun phrase goes
#: into ``card_types`` and no ``targets`` description rides beside it, so the
#: card from hand went back on the library with the stack empty.
_QUANTIFIERLESS_TARGET_KINDS = frozenset({
    "grant_banding_to_target", "counter_stack_ability",
    "prevent_damage_by_target_spell_until_eot",
    "reanimate_creature", "reanimate_creature_to_battlefield",
    "reanimate_aura_onto_source",
    "return_creature_from_graveyard_to_hand", "exile_target_graveyard_card",
    "put_graveyard_card_on_library_bottom", "put_graveyard_cards_on_library_top",
})

#: Target kinds ``illegal_targets_refusal`` does not read through its
#: permanent-by-id loop, because a *player* may be among the chosen targets and
#: a player target reaches the stack item through the same field as the seat a
#: permanent target sits on. The four player kinds are answered by
#: ``ResolutionTargetsMixin._player_target_legality``, which asks ``stack_targets`` —
#: the reader that tells the two apart — which targets there are. A **role**
#: of one of these kinds is still declined (Donate's player beside its
#: permanent): a wrong "every target is illegal" there counters a spell that
#: still has a legal target, strictly worse than the rule going unenforced.
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


#: The cast-spec kinds whose target may be **an object on the stack**, and so
#: the kinds :meth:`StackTargetsMixin._offered_stack_targets` answers for. ``stack``
#: is a spell or ability and nothing else; ``spell_or_permanent`` (the Laces,
#: Unsubstantiate) is a spell *or* a battlefield permanent, and only its stack
#: half is asked there.
_STACK_TARGET_KINDS = frozenset({"stack", "spell_or_permanent"})


def _resolution_rechecks_description(spec: dict) -> bool:
    """Whether ``illegal_targets_refusal`` re-asks *spec*'s printed
    description of each surviving permanent target (CR 608.2b).

    Yes for every spec whose targets are battlefield permanents named by id —
    the ones ``Game._described_cast_target_slots`` enumerates. **Wider than**
    ``_UNCHECKED_CAST_TARGET_KINDS`` **by one kind**, ``spell_or_permanent``
    (the Laces, Unsubstantiate): the announcement gate leaves it out because a
    named *index* there may be a stack position, but at resolution the target
    is an id, which names a permanent and nothing else, so the permanent half
    of the description is answerable exactly as for a "permanent" spec.

    No for the shapes the question is not about:

    * a **cost** picker (any of ``targeting.COST_PICKER_FLAGS`` on the spec
      itself) — a payment is not a target (CR 601.2b vs 601.2c), and a
      sacrificed creature has, by design, left the description;
    * a **stack** target — its own branch below, and a spell's type does not
      change on the stack in this pool;
    * a **graveyard** target — a card in a zone has no computed
      characteristics to change (CR 613.1), and the stamp branch below already
      answers its "is it still there?";
    * a **roles** spec — every role carries its own description and relation,
      which ``handlers/_common.roles_still_legal`` re-asks at resolution
      through the same ``ROLE_RELATION_TESTS`` the picker narrowed with. A flat
      enumeration here would compare the second role's target against the
      first role's list.

    A modal spell is asked like any other, about the spec of **the mode that
    was chosen** (``_resolving_announcements``). The one modal shape left out
    is the caller's exclusion rather than this function's — a mode an
    *opponent* chose (CR 700.2e), whose spec needs a seat only the prompt that
    asked for its targets held.
    """
    kind = spec.get("kind")
    if kind in (_UNCHECKED_CAST_TARGET_KINDS - {"spell_or_permanent"}):
        return False
    if kind in (GRAVEYARD_TARGET_KIND, ROLES_TARGET_KIND):
        return False
    if spec_is_a_cost(spec):
        return False
    return True


def _ability_target_quantifiers(instruction) -> list[str]:
    """Every *mandatory-context* ``targets`` quantifier this ability carries.

    The quantifiers alone, for the callers that only need to count the printed
    instances of the word. :func:`_announced_target_slots` is the same walk
    keeping the *instruction* beside each one, for the caller that has to ask a
    later slot a question of its own.

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
    return [quantifier for _instr, quantifier in _announced_target_slots(instruction)]


def _announced_target_slots(instruction) -> list[tuple]:
    """``(instruction, quantifier)`` for every slot CR 601.2c announces.

    One walk, two readers, and the docstring above is its specification —
    :func:`_ability_target_quantifiers` is this function with the instructions
    dropped. Split when a caller needed the slot itself: "Choose target
    opponent … Destroy target nonblack creature **that player** controls"
    (Keeper of the Dead) announces two targets, the second narrowed by the
    first's answer, and asking whether that second slot can be filled means
    deriving a spec from the very instruction that carries it. Counting
    quantifiers cannot say which instruction each came from, and a second walk
    beside this one would be the copy that drifts.
    """
    slots: list[tuple] = []

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
            slots.append((instr, quantifier))
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
            slots.append((instr, "target"))
        for step in payload.get("steps") or ():
            walk(step)
        # …and a **toll's** default half. "Exile this card and target creature
        # **unless that creature's controller pays {2}**" (Carrionette) lowers
        # to a `may` offered to the other player with the effect in
        # ``otherwise``, and that effect is the ability's mainline rather than a
        # conditional branch of it: CR 601.2c announces the target as the
        # ability is activated, and the toll is offered at resolution. Left
        # unwalked the gate saw no mandatory target at all, so the ability was
        # activatable with nothing to aim at — and on Carrionette that exiles
        # the card out of its own graveyard for no effect.
        #
        # Deliberately not ``then``/``else``/``action``, which the docstring
        # above excludes and this does not disturb: those are branches of a
        # decision made *during* the resolution, and ``otherwise`` is what the
        # ability does when nobody buys it off. Two cards in the pool carry a
        # target there (Carrionette, Tainted Specter) and both print "unless".
        for step in payload.get("otherwise") or ():
            walk(step)

    walk(instruction)
    return slots


#: Spec kinds :func:`cast_target_obligation` does not answer for, each because
#: another gate already owns CR 601.2c's "can it be announced at all?" for it:
#: ``none`` / ``modal`` / ``hand_card`` choose no target; a **roles**
#: announcement is checked whole by ``_validate_cast_targets`` (which refuses a
#: cast naming fewer objects than the spell has roles); a **divided** spell
#: naming nothing is CR 601.2d's refusal in ``queue_from_hand``.
_UNOBLIGED_CAST_KINDS = frozenset({
    "none", "modal", "hand_card", ROLES_TARGET_KIND, "divided",
})

#: Spec flags that mean the picker is **not a target** (CR 115.1): a *source of
#: your choice* is chosen, not targeted (CR 609.7a) — Reverse Damage, Eye for an
#: Eye; ``optional`` is Clone's "you may have this enter as a copy". A cost is
#: asked through :func:`targeting.spec_is_a_cost` beside these.
_UNTARGETED_SPEC_FLAGS = ("source_of_choice", "requires_source", "optional")

#: The printed quantifiers that let an announcement name **nobody** (CR 601.2c:
#: "up to one target" and "any number of target" are legal at zero).
_ZERO_TARGET_QUANTIFIERS = frozenset({"up_to", "any_number"})


def _inside_an_offer(instructions, wanted) -> bool:
    """Whether *wanted* sits on the taken branch of a ``may`` in *instructions*.

    Asked only of a slot that carries **no** printed quantifier, where it is
    the one piece of evidence that separates two sentences the lowering gives a
    single kind: "Return target instant or sorcery card from your graveyard to
    your hand" (Relearn) and "…Then you **may** return an instant or sorcery
    card from your graveyard to your hand" (Experimental Overload). The first
    targets. The second chooses at resolution and targets nothing, so an empty
    graveyard does not make it uncastable — and the engine's standing
    approximation (it asks for the card as the spell is cast) must not be
    promoted into a rule the card does not print.

    A slot that *does* carry a quantifier is never asked: "You may tap or untap
    **target** creature" (Twiddle) is an offer about a target CR 601.2c has
    already chosen.
    """
    for instruction in instructions:
        for step in _iter_instruction_tree(instruction):
            if step.kind != "may":
                continue
            offered = tuple(step.payload.get("action") or ())
            if any(
                inner is wanted
                for branch in offered
                for inner in _iter_instruction_tree(branch)
            ):
                return True
    return False


def cast_target_obligation(
    card: CardDefinition, program, *,
    optional_cost_payments: dict | None = None,
    x_value: int | None = None,
    mode_index: int | None = None,
) -> dict | None:
    """The spec of the target an instant or sorcery **must** announce as it is
    cast (CR 601.2c), or None when it may be announced naming none.

    The one definition of "this spell needs a target", read by the cast path
    (:meth:`CastTargetGatesMixin.no_legal_cast_target_refusal`), by the AI's proposal
    filter and by the web's castable highlight. It was three: the cast path
    asked a per-kind arm in ``_validate_cast_targets`` (so a spell whose first
    instruction is a ``sequence``, a ``may`` or an ``if_then`` reached no arm
    and was castable at nothing), the AI asked "is every quantifier in the
    program an *up to*?", and the browser asked whether its picker was empty.

    The answer is **one slot's** — the slot ``derive_cast_spec`` describes,
    through :func:`targeting.cast_target_slot` — and it is that slot's own
    printed quantifier:

    * "target", a printed count ("two target creatures"), "one or more
      target", "any target" — one must be named, so one must exist;
    * "up to N target", "any number of target" — zero is a legal announcement;
    * "**X** target creatures" — obliged only once the caster has announced an
      X of one or more (CR 601.2b precedes 601.2c, and X may be zero);
    * no quantifier at all (the kinds whose noun phrase is lowered into the
      payload rather than into a ``targets`` description: a bounce, a
      graveyard return, a Lace) — obliged, *unless* the slot is a choice the
      spell merely offers (:func:`_inside_an_offer`).

    **A modal spell answers for the mode it was announced with** (CR 601.2b
    chooses the mode before CR 601.2c chooses the targets): *mode_index* picks
    the steps through :func:`targeting.announced_mode_instructions`, and a cast
    naming no mode is the mode-0 cast it resolves as. This function used to
    answer None for every modal spell — "its spec is mode 0's whichever mode
    was chosen; the chosen mode's arm in ``_validate_cast_targets`` judges it"
    — and the arms name eleven instruction kinds, so 18 of the pool's 46
    mandatory object-targeting modes were castable with no legal target
    anywhere (Chaos Charm's "1 damage to target creature" on an empty board,
    Treva's Charm's "exile target attacking creature" outside combat).

    Not answered where **an opponent** chooses the mode (CR 700.2e): the caster
    names no target as it casts, and ``arm_modal_mode_targets`` asks once the
    mode is known. Nor for the kinds in :data:`_UNOBLIGED_CAST_KINDS`.
    *optional_cost_payments* is CR 601.2b's answer so far, for CR 702.33g: a
    kicked-only target is a target only of a spell that was kicked.
    """
    if program.modes and program.mode_chooser is not None:
        return None
    slot = cast_target_slot(
        card, program, optional_cost_payments=optional_cost_payments,
        mode_index=mode_index,
    )
    if slot is None:
        return None
    spec, instruction = slot
    if spec.get("kind") in _UNOBLIGED_CAST_KINDS:
        return None
    if spec_is_a_cost(spec) or any(spec.get(flag) for flag in _UNTARGETED_SPEC_FLAGS):
        return None
    unnamed = _slot_may_name_nobody(instruction, x_value)
    if unnamed is None:
        if _inside_an_offer(
            announced_mode_instructions(program, mode_index), instruction
        ):
            return None
        return spec
    return None if unnamed else spec


def _slot_may_name_nobody(instruction, x_value: int | None) -> bool | None:
    """Whether the target slot *instruction* carries may be announced naming
    nobody (CR 601.2c) — True, False, or None when the slot prints no
    quantifier at all and so says neither.

    True for "up to N target" and "any number of target", and for "**X**
    target" until the caster has announced an X of one or more (CR 601.2b comes
    first, and X may be zero). False for every other printed quantifier: the
    bare word, a printed count, "one or more".
    """
    described = (getattr(instruction, "payload", None) or {}).get("targets")
    quantifier = described.get("quantifier") if isinstance(described, dict) else None
    if quantifier is None:
        return None
    if quantifier in _ZERO_TARGET_QUANTIFIERS:
        return True
    if described.get("count") == "x":
        return not (isinstance(x_value, int) and x_value >= 1)
    return False


def exact_target_count(spec: dict | None, instruction, x_value: int | None) -> int | None:
    """How many targets the slot *instruction* carries **must** name (CR
    601.2c), or None when it prints no exact number.

    "Exile **two** target artifacts" (Dust to Dust) — two, not "up to two".
    "Tap **X** target creatures" (Winter Blast) — X, once X is a number: CR
    601.2b announces it first, so *x_value* None means "not announced yet" and
    answers None rather than guessing a count the caster never named.

    The grammar has told "exactly" from "up to" since it parsed them and the
    spec carries it to the picker (``exact_targets``), where the browser's
    confirm has always waited for the printed number. The engine's own gate
    did not: a count was a ceiling the announcement could fall short of, so
    "two target creatures" was castable naming one — 15 of 15 measured — and
    Malicious Advice at X=3 naming two tapped two and charged 3 life.

    None for the shapes another gate counts: a **roles** list
    (``_validate_cast_targets`` counts roles), a **cost-sized** list
    (``cast_target_refusal`` counts payments) and a **divided** one
    (``division_refusal``). And None for a count of one — the bare word
    "target" — whose unnamed announcement is not refused but answered: it
    names the picker's first entry (``engine/bare_announcements.py``).
    """
    if not spec or spec_roles(spec) or spec.get("cost_targets"):
        return None
    if spec.get("kind") == "divided" or spec.get("division"):
        return None
    described = (getattr(instruction, "payload", None) or {}).get("targets")
    if not isinstance(described, dict):
        return None
    # "Target creature gets +2/+2 until end of turn. **Another** target
    # creature gets -2/-2 until end of turn." (Consume Strength, Steal
    # Strength, Rookie Mistake; Deadshot prints it over a tap and a bite.) Two
    # printed instances of the bare word "target", so two targets — as exact a
    # number as "two target creatures", spelled a different way. This asked
    # only for the quantifier ``exactly``, a slot list carries ``target``, and
    # its slots were a ceiling the announcement could fall short of: each of
    # those four was castable naming one creature, which made the drawback half
    # of the card optional. ``targeting.slot_list_is_exact`` is the question the
    # picker's ``exact_targets`` flag asks too; a list with an "up to one" slot
    # in it (Primal Might) may legally name fewer and answers False to both.
    if described.get("quantifier") != "exactly" and not slot_list_is_exact(described):
        return None
    count = described.get("count")
    if isinstance(count, bool):
        return None
    if isinstance(count, int):
        return count if count >= 2 else None
    if count == "x":
        if not isinstance(x_value, int) or isinstance(x_value, bool):
            return None
        return max(0, x_value)
    return None


def cast_may_name_no_target(
    card: CardDefinition, program, *, x_value: int | None = None,
    mode_index: int | None = None,
) -> bool:
    """Whether an instant or sorcery's target may legally be left unnamed —
    the positive half of :func:`cast_target_obligation`, for the per-kind arms
    in ``_validate_cast_targets``.

    Those arms each end in "…and with nothing named, some legal target must
    exist", written for the one-target spell each was written about. Asked of
    "Tap **up to three** target creatures" (Tidal Surge), "Destroy **any number
    of** target creatures" (Phyrexian Purge) or "Return **X** target creatures"
    (Aether Tide) it refuses an announcement CR 601.2c allows: zero targets is
    a legal number of them. Seven shipped spells were uncastable at an empty
    board for it, and the AI — whose own reader knew "up to" — proposed one of
    them every turn and was refused every turn.

    True only on printed evidence (:func:`_slot_may_name_nobody`); a slot with
    no quantifier and a spell with no target both answer False, which leaves
    each arm exactly as strict as it was. A modal spell is asked about the
    mode it was announced with (*mode_index*): "Return **up to two** target
    creatures to their owners' hands" (Read the Tides' second mode) answered
    False here for being modal, and was uncastable at a board with no creature.
    """
    slot = cast_target_slot(card, program, mode_index=mode_index)
    if slot is None:
        return False
    return _slot_may_name_nobody(slot[1], x_value) is True


#: Spec kinds :func:`activation_target_obligation` does not answer for:
#: ``none`` / ``modal`` / ``hand_card`` choose no target, and a **divided**
#: announcement is CR 601.2d's (``divided_damage.division_refusal``, asked in
#: ``_activate_onto_stack`` beside the target gate).
_UNOBLIGED_ACTIVATION_KINDS = frozenset({"none", "modal", "hand_card", "divided"})

#: Spec flags that make an activation's picker **a choice and not a target**
#: (CR 115.1): "a source of your choice" (CR 609.7a) and an ``optional`` one.
#: ``also_stack`` is the same answer by another flag: only a chosen source is
#: offered spells on the stack beside permanents (the colour Circles carry it
#: and no ``source_of_choice``). Narrower than :data:`_UNTARGETED_SPEC_FLAGS`
#: by one flag on purpose — ``requires_source`` says a source is chosen *as
#: well*, and the spec it rides is a real target's (Jade Monolith's "target
#: creature").
_CHOSEN_NOT_TARGETED_FLAGS = ("source_of_choice", "also_stack", "optional")


def spec_chooses_a_source(spec: dict | None) -> bool:
    """Whether *spec*'s picker is CR 609.7a's **"a source of your choice"**:
    the flag itself, or ``also_stack``, which only a chosen source carries
    (the colour Circles carry it and no ``source_of_choice``).

    One reader for the two places that have to agree about it, because they
    disagreed in opposite directions: the **picker** treated a chosen source
    as a target and withheld one with shroud, hexproof or protection from the
    choosing card (Circle of Protection: Black, a white enchantment, was not
    offered a Black Knight), while the **gate** did not look at a named
    source at all. ``optional`` is not this — Clone's copy is a different
    choice, made on the cast side.
    """
    return bool(spec) and bool(spec.get("source_of_choice") or spec.get("also_stack"))


def activation_target_obligation(ability, *, x_value: int | None = None) -> dict | None:
    """The spec of the target an activated ability **must** announce as it is
    activated (CR 602.2b, through CR 601.2c), or None when it may be activated
    naming none.

    :func:`cast_target_obligation`'s twin, and the **one** definition of "this
    ability owes a target": read by the activation gate
    (:meth:`AbilityTargetsMixin.activation_target_refusal`), by the wire
    (:meth:`AbilityTargetsMixin.unannounced_activation_target`, which is what stops
    ``web/actions.py`` accepting an activation no browser can send) and through
    the gate by the AI's two activation choosers.

    The answer is the picker's own slot — :func:`targeting.
    activation_target_slot`, the instruction ``derive_activation_spec``
    describes — and that slot's printed quantifier:

    * "target", a printed count, "any target" — one must be named, so one
      must exist;
    * **no quantifier at all** (a kind whose noun phrase is lowered into the
      payload, or into nothing, rather than into a ``targets`` description) —
      owed where the ability's own line prints the word
      (``stack_targets.names_a_target``, the reader that decides what a stack
      object's targets *were*, so "owes a target" and "chose a target" are one
      opinion). A picker the line never calls a target is a choice: "an
      unblocked creature **of your choice**" (Forcefield), "an artifact source
      of your choice" (Circle of Protection: Artifacts);
    * "up to N target", "any number of target" — zero is a legal announcement;
    * "**X** target lands" (Candelabra of Tawnos) — obliged only once the
      activation has announced an X of one or more (CR 601.2b precedes 601.2c).

    **"No quantifier at all" is the half this replaced a walk for.** The gate
    used to ask ``_ability_target_quantifiers``: every ``targets`` description
    in the unconditional steps, plus a hand-kept list of kinds whose noun
    phrase is lowered somewhere else. A lowering that wrote neither was an
    ability the gate thought owed nothing — about fifty of them (a bounce, a
    base-P/T set, "you may tap or untap target creature", a land-type change,
    "target opponent gains control of this artifact") could be activated with
    nothing to aim at, and paid for, or aimed at an opponent's Island. The
    picker is the evidence instead, so the next lowering cannot forget: an
    ability that derives one owes what it asks for unless its slot, its spec's
    flags or its own printed line says otherwise.

    **A target in a conditional sentence is owed too.** "Flip a coin. If you
    win the flip, draw a card. If you lose the flip, counter **target**
    artifact spell you control" (Goblin Artisans); "If this creature is
    tapped, exile **target** creature card from a graveyard" (Eater of the
    Dead). CR 601.2c: a spell or ability "may require some targets only if an
    alternative or additional cost … or a particular mode was chosen for it" —
    a condition asked at resolution is neither, so the target is announced as
    the ability is activated and the ability cannot be activated without one.
    The walk skipped ``then``/``else`` on purpose and recorded it as a
    pool-wide decision still to be made; the cast side had made it already
    (:func:`cast_target_obligation` reads both arms), and one ability, one
    question is what makes it here.
    """
    spec, _ = _activation_spec([ability])
    if spec.get("kind") in _UNOBLIGED_ACTIVATION_KINDS:
        return None
    if spec_is_a_cost(spec) or any(spec.get(flag) for flag in _CHOSEN_NOT_TARGETED_FLAGS):
        return None
    slot = activation_target_slot(ability)
    if slot is None:
        return None
    unnamed = _slot_may_name_nobody(slot[1], x_value)
    if unnamed is True:
        return None
    if unnamed is None:
        from .stack_targets import names_a_target

        if not names_a_target(getattr(ability, "source_line", None)):
            return None
    return spec


def announced_by_a_choice(item) -> bool:
    """Whether the **ability** *item*'s recorded targets are an announcement a
    player made — the bound on everything CR 608.2b asks of an ability.

    An activated ability's are (CR 602.2b; ``StackItem.activated``), and so
    are a triggered ability's where CR 603.3d's picker chose them
    (``StackItem.targets_chosen``). A target a **fire site** stamped is not,
    and neither is a default the picker took while a permanent was on its way
    to a graveyard: the death sweep announces a dies-trigger while the dying
    permanent is still listed, so the id on the item may be one nobody could
    have chosen, and asking the rule of it would report the engine's own
    mis-targeting as a fizzle. One predicate for the gate and for the
    per-target blanking, so the two cannot disagree about which abilities are
    judged.
    """
    return bool(
        getattr(item, "activated", False) or getattr(item, "targets_chosen", False)
    )


class LegalityMixin:
    """Backend legality queries surfaced to the web UI: combat legality here,
    target legality in the mixins beside it (see this module's docstring).
    Composed onto ``Game``."""

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
        # "Enchanted creature can't be blocked." (Cloak of Mists.) The attached
        # channel, asked beside the printed one below because the blocker gate
        # asks both -- and this predicate exists to agree with that gate. A
        # creature it will refuse every blocker on and this does not tag is the
        # UI promising a block the step then rejects.
        from .auras import attached_combat_restrictions

        if any(
            restriction.kind == "cant_be_blocked"
            for restriction in attached_combat_restrictions(perm)
        ):
            return True
        seat = self.controller_index_of(perm)
        return any(
            # "This creature can't be blocked **as long as defending player
            # controls an artifact**." (Bouncing Beebles.) The clause can carry
            # a condition, so the kind alone is not the answer — asked through
            # the same reader the declare-blockers gate uses, with the same two
            # seats, because a creature this tags and that gate would let a
            # blocker onto is the UI *forbidding* a legal block. "Defending
            # player" is the seat this creature was declared attacking
            # (CR 508.1a), which the permanent records; a creature not attacking
            # has none, and the condition then answers False — the direction
            # that shows a block rather than promising one.
            (
                i.kind == "cant_be_blocked"
                and restriction_condition_holds(
                    self,
                    i.payload.get("condition"),
                    observer=seat,
                    defender=perm.defending_player_index,
                    source=perm,
                )
            )
            # "…as long as it's attacking alone" (Dream Prowler): CR 506.5's
            # condition, asked of the board rather than of a payload, so the
            # tag comes and goes with the declaration exactly as the blocker
            # gate's answer does. Read here too because a creature the gate
            # will refuse every blocker on is what this predicate is *for* —
            # the two answering differently is the UI promising a block the
            # step then rejects.
            or (
                i.kind == "cant_be_blocked_while_attacking_alone"
                and self.creature_attacking_alone(perm)
            )
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


def _single_target_is(game, chosen: dict, wanted: str, source=None) -> bool:
    """Whether the one thing a stack object is aimed at is a *wanted*.

    "…and **that target is a creature**" (Meddle), "…that targets only **a
    player**" (Rebound), "…that targets only **this creature**" (Silver
    Wyvern). One reader because both ends of the question ask it — the picker,
    before the ability is activated, and ``_retarget_subject`` at resolution,
    where CR 608.2b asks it again about an object that may have been re-aimed in
    between. It was the picker's alone, so Meddle's restriction was checked when
    the spell was cast and never afterwards.

    ``creature`` is CR 613's answer rather than the printed type line, so an
    animated land a spell is aimed at is a creature here exactly as it is
    everywhere else; a permanent that has left is not one. ``player`` is the
    face half of the same question, and a seat that has lost is still the seat
    the spell named — CR 115.7a's legality is asked of the *new* target.

    ``source`` is the third and it is not a *type* at all: "this creature" is an
    identity, so the answer is ``permanent_id`` against the retargeting
    ability's own permanent and nothing about what either of them is. *source*
    is that permanent, handed down by whichever end is asking — the picker holds
    it as the ability's source and the resolution holds it on the context. With
    no source there is no identity to compare, so the answer is False: an
    ability whose own permanent has left the battlefield re-aims nothing, which
    is CR 608.2b's reading and not a fallback to "any creature".

    A word this cannot answer is False, never True: an unrecognised bound must
    narrow to nothing rather than to everything.
    """
    if wanted == "player":
        return chosen.get("kind") == "player"
    if wanted == "creature":
        if chosen.get("kind") != "permanent":
            return False
        aimed = game.permanent_by_id(chosen.get("permanent_id"))
        return aimed is not None and aimed.is_creature
    if wanted == "source":
        if chosen.get("kind") != "permanent" or source is None:
            return False
        aimed = game.permanent_by_id(chosen.get("permanent_id"))
        return aimed is not None and aimed is source
    return False


#: Cast specs that name no object or player for a targeting ban to bite on, so a
#: spell carrying one is castable under CR 113.3c's prohibition. "none" targets
#: nothing; "modal" picks its mode before its targets; "hand_card", "stack" and
#: "spell_or_permanent" name something that is not a permanent or a player on
#: the battlefield.
_UNBANNABLE_CAST_KINDS = frozenset({
    "none", "modal", "hand_card", "stack", "spell_or_permanent",
})


def targeting_ban_refusal(game, card, *, from_zone: str = "hand") -> str | None:
    """Why *card* cannot be cast while a targeting ban stands, or ``None``.

    "This turn and next turn, ... players and permanents can't be the targets of
    spells or activated abilities" (Peace Talks). CR 113.3c: the prohibition is
    on spells and activated abilities, so a spell that targets a permanent or a
    player has no legal target while one is up.

    **One predicate, two readers.** The cast path asks it to refuse, and
    ``ai_policy._can_cast_with_targets`` asks it before proposing — because a
    refused cast costs nothing and breaks no rule, and a seat that re-proposes
    the same card every turn does nothing until the ban expires. That is what
    ``simulate_ai_games.py``'s ``refused_casts`` counts, and Visions' Phase 5
    run counted thirty of them across eight games. Written here rather than
    copied into the policy for the reason the three sibling bans above it are:
    two readers of one gate drift, and this one drifts towards a cast the AI
    offers and the engine declines.
    """
    if not game.targeting_bans:
        return None
    if card.primary_type not in ("instant", "sorcery") and "aura" not in (
        card.type_line or ""
    ).lower():
        return None
    from .oracle import compile_card_oracle
    from .targeting import derive_cast_spec

    spec = derive_cast_spec(card, compile_card_oracle(card), from_zone=from_zone)
    if spec is None or spec.get("kind") in _UNBANNABLE_CAST_KINDS:
        return None
    source_name = game.targeting_bans[-1].get("source_name", "an effect")
    return (
        f"{card.name} has no legal target: nothing can be targeted "
        f"({source_name})"
    )
