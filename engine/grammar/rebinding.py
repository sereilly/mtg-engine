"""Pronoun rebinding: which object a bare "it" in an effect actually names.

``parse_recipient`` reads a bare "it" as the ability's own source, which is what
the word means on every line whose sentence names nothing else. Some sentences
*do* name something else, and this is where the pronoun is pointed at it.

**This module holds the half whose antecedent is outside the sentence** — a
trigger whose condition describes the object, a firing event that carries it, an
intervening-if that recorded a card. The half whose antecedent is a target the
same sentence announced is ``sentence_rebinding``, one layer up. The split was
made at the thousand-line guard on a seam that was measured rather than
inherited: **no function in either half calls one in the other**, and the whole
edge between them is one name — ``_walk_specs``, the AST walk both rewrite
through. Two readers moved up with their productions for exactly that reason
(``_announced_target`` and ``_names_a_target`` are read by the in-sentence
rebinders and by nothing else); ``statement_bound_target`` and its neighbours
stay here, where the condition-side rebinders and ``pronouns`` / ``riders``
read them. ``PARSE_LAYERS`` carries the argument.

Its own module rather than more of ``triggers``: only one of the rebinders here
is about a trigger, and the walk underneath is about the shape of the AST rather
than about any of them. It sits below ``triggers`` in the layer order because it
reaches no production — a rebinder that needed one would be rebinding by a list
of the productions that admit a pronoun, which is the per-node table the walk
exists to avoid. The one name it takes from further down is a **vocabulary**,
``back_references.COMBAT_ROLES``: the words "the attacking creature" and "the
blocking creature" are read there and resolved here, and spelling them twice is
how the reader and the resolver would come to disagree about which phrase is a
role at all.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
from .back_references import COMBAT_ROLES


def _walk_specs(node, rewrite, kind=ast.TargetSpec):
    """*node* with ``rewrite`` applied to every *kind* node in it.

    A structural walk rather than a per-node table: a pronoun can sit anywhere
    a recipient can, and a list of the productions that admit one goes stale
    the way every fire-site list in this engine has. The walk is shared by both
    rebinders below because it is the whole of what they have in common — what
    a pronoun *becomes* is the only thing that differs, and that is the
    callback.

    *kind* is the node the callback is offered. An object pronoun is an
    :class:`ast.TargetSpec` and a player pronoun is an :class:`ast.PlayerRef`,
    and they sit in the same places for the same reason — so this is a
    parameter rather than a second copy of the walk with one isinstance
    changed.
    """
    if isinstance(node, kind):
        rewritten = rewrite(node)
        if rewritten is not None:
            return rewritten
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_walk_specs(getattr(node, field.name), rewrite, kind),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    # Tuples and lists alike: the AST is all-tuple today, and a walk that knew
    # only about tuples would step over the first list field somebody adds
    # without saying so — a pronoun quietly left pointing at the wrong object,
    # which is the exact failure this function exists to prevent.
    if isinstance(node, (tuple, list)):
        walked = [_walk_specs(item, rewrite, kind) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def _bound_target(statement: ast.Statement, accept) -> "ast.TargetSpec | None":
    """The nearest preceding chosen target *accept* says yes to, or None.

    One walk, asked twice. The pronoun binds to the nearest preceding choice, so
    a Sequence or a Conjunction is searched from its last step; what differs
    between the two readers below is only **which** chosen spec counts, and that
    is the callback. Written as two walks it was two copies of the recursion,
    which is the fork-in-a-fragment shape this package keeps finding: the
    singular reader already carries a case (`DealDamage`'s own recipient tuple)
    that a second copy has no reason to remember.
    """
    if isinstance(statement, ast.Sequence):
        for step in reversed(statement.steps):
            found = _bound_target(step, accept)
            if found is not None:
                return found
        return None
    if isinstance(statement, ast.Conjunction):
        for step in reversed(statement.effects):
            found = _bound_target(step, accept)
            if found is not None:
                return found
        return None
    # "Soul Sear deals 5 damage to target creature or planeswalker. It loses
    # indestructible…" — the damage sentence's chosen recipient is what the
    # pronoun names. Recipients live in their own tuple on DealDamage, which
    # the field scan below cannot see.
    if isinstance(statement, ast.DealDamage):
        for recipient in reversed(statement.recipients):
            if isinstance(recipient, ast.TargetSpec) and accept(recipient):
                return recipient
        return None
    for field_name in ("subject", "target"):
        candidate = getattr(statement, field_name, None)
        if isinstance(candidate, ast.TargetSpec) and accept(candidate):
            return candidate
    return None


def statement_bound_target(statement: ast.Statement) -> "ast.TargetSpec | None":
    """The chosen target a following pronoun sentence refers back to, or None.

    "Put a +1/+1 counter on up to one target creature. **It** gains
    indestructible until end of turn." — the pronoun names the previous
    sentence's target, not the ability's source.

    "Up to one" qualifies and a counted plural does not: every rider reading
    this hands the spec to a lowering that resolves **one** permanent, so a
    two-target spec arriving here would act on two where the pronoun named one.
    The plural has its own reader below.
    """
    return _bound_target(
        statement, lambda spec: spec.quantifier in ("target", "up_to")
    )


def _names_several(spec: "ast.TargetSpec") -> bool:
    """Whether *spec* is a printed choice of **more than one** object.

    The question ``lowering/_targets._names_several_targets`` asks, answered
    again here rather than imported: this module is in the parse half and that
    one in the lowering half, and neither may reach the other. A quantifier
    missing here costs a rebinding rather than widening one — a line refuses,
    which is the safe direction. "One or more" and "any number of" print no
    number and qualify on the quantifier alone; the counted spellings carry
    theirs, and a printed one is not several.
    """
    if not spec.targeted:
        return False
    if spec.quantifier in ("one_or_more", "any_number"):
        return True
    if spec.quantifier not in ("exactly", "up_to"):
        return False
    return bool(spec.count_from_x) or spec.count > 1


def statement_bound_several_targets(
    statement: ast.Statement,
) -> "ast.TargetSpec | None":
    """The **several** chosen targets a following "each of them" refers back to.

    "Untap two target creatures. **Each of them** gets +1/+1 until end of turn."
    (Hope and Glory.) :func:`statement_bound_target`'s plural twin, through the
    same walk with the other half of the quantifiers.
    """
    return _bound_target(statement, _names_several)


def rebind_pronoun_to_condition_target(
    condition: ast.Condition, statement: ast.Statement
) -> ast.Statement:
    """"**If target creature** has toughness 5 or greater, **it** gets +4/-4…"
    (Blood Lust) — the pronoun names the object the *condition* chose.

    The sibling of :func:`rebind_pronoun_to_event_subject`, and the difference
    is what the pronoun stands for. A trigger's condition describes a *set* the
    event picked from, so that one swaps the pronoun's filter and leaves it a
    pronoun. A condition that prints "target" has already chosen one object
    (CR 601.2c), and the arms must resolve to *that* choice rather than to a
    fresh one — so the whole spec is substituted, targeting and all, and the
    single target the spell announced is what both arms move.

    The pronoun and a card naming itself lower to the same spec, so this cannot
    tell them apart. It does not need to: it is called only from the production
    that read a targeting condition, where the ability's own source is a spell
    on the stack and every object reference in the arms is the creature the
    condition named.
    """
    spec = getattr(condition, "subject", None)
    if not isinstance(spec, ast.TargetSpec) or not spec.targeted:
        return statement

    def _rewrite(node: ast.TargetSpec) -> ast.TargetSpec | None:
        if node.quantifier in ("it", "this") and node.filter.is_source:
            return spec
        return None

    return _walk_specs(statement, _rewrite)


def _condition_target_player(condition: ast.Condition) -> "ast.PlayerRef | None":
    """The one *targeted* player a condition names, or None.

    None when it names none and — deliberately — also when it names two: "the
    difference between **your** life total and **target player's**" has exactly
    one, and a clause naming two targeted seats would leave "that player"
    genuinely ambiguous. Refusing there is what keeps the rebinding from
    picking whichever the walk reached first.
    """
    found: list[ast.PlayerRef] = []

    def _collect(ref: ast.PlayerRef):
        if str(ref.kind).startswith("target_"):
            found.append(ref)
        return None

    _walk_specs(condition, _collect, ast.PlayerRef)
    return found[0] if len(found) == 1 else None


def rebind_player_pronoun_to_condition_target(
    condition: ast.Condition, statement: ast.Statement
) -> ast.Statement:
    """"If the difference between your life total and **target player's** life
    total is 5 or less, exchange life totals with **that player**." (Psychic
    Transfer.)

    The player half of :func:`rebind_pronoun_to_condition_target` above, and it
    exists for that function's reason exactly: the condition has already chosen
    a seat (CR 601.2c) and the arm must resolve to *that* choice rather than to
    a fresh one. Left alone, "that player" reaches the lowering as a referent
    no spell froze, and the lowerings that read one refuse the line — which is
    the safe direction and still costs the card.

    Only ``that_player`` is rebound. "You" and "each player" name seats the
    sentence states outright, and a walk that rewrote them would make the
    condition's target stand in for the caster.
    """
    target = _condition_target_player(condition)
    if target is None:
        return statement

    def _rewrite(ref: ast.PlayerRef) -> "ast.PlayerRef | None":
        return target if ref.kind == "that_player" else None

    return _walk_specs(statement, _rewrite, ast.PlayerRef)


def rebind_counter_pronoun_to_bound_target(
    statement: ast.Statement, follow: ast.Statement
) -> ast.Statement:
    """"Gain control of target creature **and put a -1/-0 counter on it**."
    (Jabari's Influence.)

    ``pronouns._parse_pronoun_counter_rider`` is this rule at a **sentence
    boundary** and has been since it was written — its docstring names this
    card. Joined by "and", the conjunction loop in ``statements`` calls
    ``parse_statement`` directly and no rider table is consulted, so the same
    printed clause one punctuation mark over read "it" as the ability's own
    source: on a spell ``add_counter_to_self`` has no permanent and places
    nothing at all, and on a permanent it shrinks the source. Neither raises,
    and the card reports supported either way — which is why this is a
    substitution and not a refusal.

    Only a bare ``it`` is rebound. "This creature" and "that creature" parse to
    their own quantifiers and keep their own referents, and
    :func:`statement_bound_target` only offers a spec the sentence *targeted*
    (CR 601.2c) — so "Sacrifice a creature and put a +1/+1 counter on it" binds
    nothing here and keeps the reading it had.
    """
    if not isinstance(follow, ast.PutCounter):
        return follow
    subject = follow.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "it":
        return follow
    bound = statement_bound_target(statement)
    if bound is None:
        return follow
    return replace(follow, subject=bound)


def _rebound(node, subject: ast.ObjectFilter):
    """*node* with every bare pronoun rebound to *subject*, or *node* itself."""
    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.quantifier == "it" and spec.filter.is_source:
            return replace(spec, filter=subject)
        return None

    return _walk_specs(node, _rewrite)


def intervening_if_names_source(condition) -> bool:
    """Whether an intervening-if printed its own self-reference in full.

    "When an opponent casts a creature spell, **if this permanent is an
    enchantment**, **it** becomes a 2/2 Gargoyle creature with flying." (Opal
    Gargoyle.) The pronoun's antecedent is the nearest noun phrase before it,
    and here that is the "if" clause's subject rather than the trigger's — so
    :func:`rebind_pronoun_to_event_subject` must *not* point the word at the
    spell that was cast, which is what it does for every trigger whose
    condition names an object.

    Only a **printed** self-reference counts. A condition whose own subject is
    the bare pronoun ("…if **it** was blocked this turn", Fyndhorn Druid) has
    already been rebound by this same rule, so the word behind it names
    whatever that one does and nothing here should change it — which is the
    ``quantifier == "this"`` test: ``accept_source_reference_spec`` keeps the
    printed word precisely so this distinction survives to here.
    """
    subject = getattr(condition, "subject", None)
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "this"
        and subject.filter.is_source
    )


def rebind_pronoun_to_event_subject(
    event: ast.TriggerEvent, statement: ast.Statement, *, intervening=None
) -> ast.Statement:
    """"When enchanted land becomes tapped, destroy **it**" (Blight) — the
    pronoun names the object the *condition* was about.

    ``parse_recipient`` reads a bare "it" as the ability's own source, which is
    what it means on every line whose trigger has no other subject to name, and
    on every line with no trigger at all. Where the condition does name one, the
    pronoun is a back-reference to it, and this is the one place both halves of
    the sentence are in hand — the same decision round 8 made for "its", made at
    the same moment for the same reason.

    Only a *bare pronoun* is rebound. A card naming itself mid-sentence ("this
    Aura deals 2 damage to that land's controller", Psychic Venom) is a
    different reference that happens to be spelled with the same filter, and
    rewriting it would aim an Aura's own effect at the permanent it enchants —
    which is why the pronoun carries its own quantifier.

    An event with no subject, or one whose subject *is* the source, leaves the
    statement untouched: there is nothing else for the word to name.

    …and so does an intervening-if that named the source in full — see
    :func:`intervening_if_names_source`, which is the antecedent rule the
    trigger clause loses to whenever the "if" clause sits between them.
    """
    if intervening is not None and intervening_if_names_source(intervening):
        return statement
    subject = event.subject
    if not isinstance(subject, ast.ObjectFilter) or subject.is_source:
        return statement
    return _rebound(statement, subject)


#: For each printed combat role, the trigger events whose **subject** plays it.
#:
#: A role names one member of a combat pair, and a pair has two — so an event
#: answers for exactly one of the words and never for both. Everything not
#: listed leaves the role a role, which every lowering refuses by name.
#:
#: **Which phrase a block event puts on its subject is why this list is so
#: short.** "Whenever this creature becomes blocked **by a creature without
#: flanking**" carries the *blocker* as its subject, not the attacker — so
#: reading "the attacking creature" against it would name the wrong half of the
#: pair, silently. The unions ("attacks or blocks", "blocks or becomes blocked
#: by") are out for the neighbouring reason: their subject is in the combat but
#: which role it plays is not known until the trigger fires.
_ROLE_EVENT_SUBJECTS: dict[str, frozenset[str]] = {
    "attacking": frozenset({
        "creature_attacks",
        "attacks_unblocked",            # Farrel's Mantle
    }),
    "blocking": frozenset({"creature_blocks"}),
}


def rebind_combat_role_to_event_subject(
    event: ast.TriggerEvent, statement: ast.Statement
) -> ast.Statement:
    """"…**the attacking creature** assigns no combat damage this turn."
    (Farrel's Mantle.) The role names the object the trigger's condition was
    about — but only where the condition established that role.

    The sibling of :func:`rebind_pronoun_to_event_subject` and the same rewrite;
    what differs is the gate. A bare "it" is rebound under any event with a
    subject, because the word names whatever the sentence already named. A role
    word says *which* combatant, so it is only the event subject when the event
    is about a creature playing that role — and under any other event it stays a
    role, which every lowering refuses by name (CR 509.1a: a block is a pair, and
    a phrase naming the wrong half of one does not fail loudly on its own).

    Left as a role rather than raising here: this runs over every trigger in the
    pool, and a parse-time refusal would blame the subject for a lowering that
    may yet be written. The refusal that reaches the support report should name
    the effect that could not use the role.
    """
    subject = event.subject
    if not isinstance(subject, ast.ObjectFilter) or subject.is_source:
        return statement
    if not subject.is_enchanted:
        # **The subject has to name one object.** A board-wide condition's
        # subject is a printed noun phrase describing a *set* ("whenever a
        # creature attacks"), and rewriting a role into it would hand the effect
        # a filter where it expects a referent — a destroy that swept every
        # creature the phrase describes rather than the one in the combat.
        # Attachment is the only shape in the pool that names one, and it is the
        # one Farrel's Mantle prints.
        return statement
    roles = {
        role for role in COMBAT_ROLES
        if event.kind in _ROLE_EVENT_SUBJECTS[role]
    }
    if not roles:
        return statement

    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.quantifier in roles:
            return replace(spec, quantifier="it", filter=subject)
        return None

    return _walk_specs(statement, _rewrite)


#: The intervening-if conditions that name a card for a "that card" behind them.
#: A table rather than a shape test, because the question a reader has is "which
#: conditions carry a card?" — and because a second one would be a row here.
_CONDITIONS_NAMING_A_CARD: dict[type, str] = {
    ast.DamagedBySourceDiedThisTurn: "damaged_by_source_died_this_turn",
}


def bind_recorded_card(event_kind: str, condition, statement):
    """*statement* with every bound-card entry told which event recorded it.

    "Put **that card** onto the battlefield under your control" names an object
    the ability did not choose, and the lowering refuses it unless something
    really wrote one down. Under an ordinary trigger that something is the
    trigger's own event — but two printings put it somewhere else, and both are
    facts about the *whole line*, which is why they are read here rather than
    threaded down through the lowering:

    * "…at the beginning of the next end step" (Seraph) makes the entry a
      **delayed** ability. CR 608.2h freezes what the creating ability knew, so
      the card is the death trigger's and not the end step's.
    * "…**if** a creature dealt damage by this creature this turn died"
      (Krovikan Vampire) fires on an end step that records nothing at all. The
      intervening-if is what names the record, so it is what admits the phrase.

    A structural walk, for the reason ``_walk_specs`` above is one: the entry can
    be a step, a conjunct, or the effect of a delay, and a list of the shapes it
    has been seen in goes stale.
    """
    record = _CONDITIONS_NAMING_A_CARD.get(type(condition), event_kind)
    return _stamp_bound_card(statement, record)


def _stamp_bound_card(node, record: str):
    if isinstance(node, ast.PutOntoBattlefield):
        target = node.target
        if (
            isinstance(target, ast.TargetSpec)
            and target.quantifier == "that"
            and target.filter.is_card
            and node.bound_card_from is None
        ):
            return replace(node, bound_card_from=record)
        return node
    # "…**return the first card** to the battlefield under its owner's control
    # at the beginning of the next end step." (Lifeline.) The same move under
    # the other printed verb, so it is the same stamp: CR 400.1 knows only the
    # zone change, and which event recorded the card is a fact about the whole
    # line either way. Without this the delay lowered the inner sentence under
    # ``next_end_step``, whose fire site records nothing, and refused the card
    # for want of the answer this walk exists to supply.
    if isinstance(node, ast.ReturnToZone):
        subject = node.subject
        if (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "that"
            and subject.filter.is_card
            and node.bound_card_from is None
        ):
            return replace(node, bound_card_from=record)
        return node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changed = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if isinstance(value, tuple):
                walked = tuple(_stamp_bound_card(item, record) for item in value)
                if any(a is not b for a, b in zip(walked, value)):
                    changed[field.name] = walked
                continue
            walked = _stamp_bound_card(value, record)
            if walked is not value:
                changed[field.name] = walked
        if changed:
            return replace(node, **changed)
    return node
