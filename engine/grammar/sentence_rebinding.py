"""Pronoun rebinding whose antecedent is **in the same sentence**.

The other half of ``rebinding``, split off at the thousand-line guard with the
seam measured rather than inherited: no function here calls one there and none
there calls one here. Every cross-reference between the two groups pointed down
into the readers, and once those were attributed to their callers the whole
edge is **one name** — ``_walk_specs``, the AST walk both halves rewrite
through. The two halves were already independent; only the size guard made
anyone look.

**The seam is where the antecedent lives**, which is also what the function
names have said all along. ``rebinding`` keeps the pronouns whose referent is
*outside* the sentence — a trigger's condition described it
(``rebind_pronoun_to_condition_target``), the firing event carried it
(``rebind_pronoun_to_event_subject``, ``rebind_combat_role_to_event_subject``),
an intervening-if recorded a card (``bind_recorded_card``). Everything here
points a word at a target the **statement itself announced**: the delay's own
opener, the clause in front of it, the previous sentence of the same printed
line, the arm of an alternative.

That difference is not cosmetic. An out-of-sentence antecedent is found by
asking the *condition* — one object, known before the effect is read. An
in-sentence one has to be found by walking the statement that is being rewritten
and deciding **how far** the word reaches, which is why every rebinder below
carries a paragraph about its own narrowness and why
``rebind_pump_pronoun_to_sentence_target`` is the one with a whole-pool
differential behind it: eight shipped cards print a bare "it" after a targeting
sentence and already play correctly, so a walk that rewrote every spec broke
all eight. Narrowness is the recurring design problem of this half and of
neither line of the other, which is the honest reason they are two files.

Above ``rebinding`` in ``PARSE_LAYERS`` because it reads ``_walk_specs`` and
``rebinding`` reads nothing here. Nothing is re-exported from ``rebinding``:
the five callers import from this module directly, because a re-export would be
an *upward* import from the layer below and the guard would refuse it — the one
case where the ``prices`` / ``readers`` arrangement further down the list
cannot be copied.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
# The one name this module takes from the half below it: the walk both
# rewrite through. Measured rather than assumed — the two readers that
# came with these productions (`_announced_target`, `_names_a_target`)
# are read here and nowhere else, so they came too, and the edge between
# the modules is one function wide.
from .rebinding import _walk_specs


def _announced_target(node) -> "ast.TargetSpec | None":
    """The first target *node* announces (CR 601.2c), or None.

    :func:`_names_a_target`'s twin, separate rather than folded into it because
    the two callers want different things: that one asks whether the sentence
    chose anything, this one needs the choice itself.
    """
    if isinstance(node, ast.TargetSpec) and node.targeted:
        return node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            found = _announced_target(getattr(node, field.name))
            if found is not None:
                return found
        return None
    if isinstance(node, (tuple, list)):
        for item in node:
            found = _announced_target(item)
            if found is not None:
                return found
    return None


def _names_a_target(node) -> bool:
    """Whether any part of *node* announces a target (CR 601.2c)."""
    if isinstance(node, ast.TargetSpec) and node.targeted:
        return True
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(
            _names_a_target(getattr(node, field.name))
            for field in dataclasses.fields(node)
        )
    if isinstance(node, (tuple, list)):
        return any(_names_a_target(item) for item in node)
    return False

def rebind_pronoun_to_delay_target(
    chosen: ast.TargetSpec, statement: ast.Statement
) -> ast.Statement:
    """"…when **target creature you control** attacks and isn't blocked, **it**
    assigns no combat damage this turn" (Delif's Cube) — the pronoun names the
    object the *delay's opener* chose (CR 603.7c).

    The fourth rebinder, and the one whose antecedent is neither the ability's
    source nor a trigger's event: a delay's opener may target, and by the time
    the delayed ability fires its source is a different object again — Delif's
    Cube is still on the battlefield and its own sentence says "this artifact"
    in the very next clause. Left as the source-reading pronoun, "it" would name
    the artifact and the card would mark an artifact as assigning no combat
    damage.

    The rebound spec keeps the opener's noun phrase and **stops being a
    target**: CR 601.2c chose the object once, at announcement, and a second
    targeted spec in the effect would ask the picker for it again.

    ``ThatMuch("its_power")`` is rewritten with it — "you may gain life equal to
    **its** power" (Delif's Cone) is the same word about the same object, and an
    amount carries no spec for the walk above to find, so it is named here
    rather than left to a lowering that would have to know it was inside a
    delay.
    """
    bound = replace(chosen, quantifier="that", targeted=False)

    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.quantifier == "it" and spec.filter.is_source:
            return bound
        return None

    rebound = _walk_specs(statement, _rewrite)
    return _rebind_its_power(rebound)


def _rebind_its_power(node):
    """*node* with every ``its power`` back-reference pointed at the bound
    object. The amount twin of the walk above, written against the dataclass
    fields for the reason ``_walk_specs`` is."""
    if isinstance(node, ast.ThatMuch) and node.source == "its_power":
        return replace(node, source="bound_power")
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_rebind_its_power(getattr(node, field.name)),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_rebind_its_power(item) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def rebind_attachment_pronoun_to_sentence_target(statement: ast.Statement) -> ast.Statement:
    """"…and all white Auras you own **attached to it**" (Word of Undoing).

    The third rebinder, and the one whose pronoun sits inside a *filter* rather
    than in a recipient position. ``postmodifiers`` reads "attached to it" as
    the referent ``"source"``, which is what the words mean on Rabid Wombat
    ("gets +2/+2 for each Aura attached to it" — a count clause that chooses
    nothing). In a sentence that has already **targeted** an object, the same
    two words name that object: Word of Undoing returns the creature and the
    Auras on it, and Tawnos's Coffin exiles them.

    So the rebinding is gated on the sentence having a target at all, which is
    also what makes it safe: with nothing chosen there is nothing for the
    pronoun to be pointed at, and the referent stays the source. A card that
    targeted something *and* meant its own attachments would be misread — no
    such card is printed, and it would have to say "attached to this creature"
    to be readable at all, which is a different referent.
    """
    if not _names_a_target(statement):
        return statement

    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.filter.attached_to != "source":
            return None
        return replace(spec, filter=replace(spec.filter, attached_to="target"))

    return _walk_specs(statement, _rewrite)


def _rebind_pump_subject(node, bound: "ast.TargetSpec"):
    """*node* with every bare-pronoun :class:`ast.Pump` subject set to *bound*.

    Deliberately not a :func:`_walk_specs` rewrite over every spec, which is
    what the four rebinders above do. See
    :func:`rebind_pump_pronoun_to_sentence_target` for why this one is narrow.
    """
    if isinstance(node, ast.Pump):
        subject = node.subject
        if (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "it"
            and subject.filter.is_source
            and subject.filter.to_payload() == {}
        ):
            return replace(node, subject=bound)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_rebind_pump_subject(getattr(node, field.name), bound),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_rebind_pump_subject(item, bound) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def rebind_pump_pronoun_to_sentence_target(statement: ast.Statement) -> ast.Statement:
    """"Flip a coin. If you win the flip, **target Orc creature** gets +2/+0
    until end of turn. If you lose the flip, **it** gets -0/-2 until end of
    turn." (Orcish Captain.)

    The fifth rebinder, and the only one whose antecedent sits in a *previous
    sentence of the same printed line*. The four above each have both halves in
    one production's hand — a condition and its arms, a trigger and its event, a
    delay and what it delays, a filter and the sentence around it. A line's
    sentences are parsed independently, so nothing inside the second one can see
    that the first announced a target, and Orcish Captain's losing arm lowered
    to ``pump_self``: the Captain shrank *itself*. A card that compiled
    supported, claimed every printed sentence and carried no hollow line, doing
    something other than what it says — the shape neither ``--hollow-lines`` nor
    ``parse_coverage.py`` can see, because both ask only whether a sentence
    produced *something*.

    **It rewrites one node type, and that narrowness is the whole design.** The
    obvious version of this function walks every spec the way the four above do.
    It is wrong, and a whole-pool differential says so: eight shipped cards —
    Phyrexian Gremlins, Telekinesis, Glyph of Destruction, Whippoorwill, Mole
    Worms, Goblin Sappers, Ice Floe and Elvish Scout — print a bare "it" after a
    targeting sentence and **already play correctly**, because the lowerings
    that receive it (the untap restrictions, the damage shields) each carry
    their own bare-pronoun branch and resolve the ability's target at
    resolution. Handing those a rebound spec breaks all eight: they refuse a
    subject that looks chosen, on the sound reasoning that a second targeted
    spec would ask the picker for a target the card never offered.

    So the engine already has a convention for this pronoun, and it is *read by
    the lowering*, not by the parser. What was missing was one lowering's branch
    — ``_lower_pump`` tests ``filter.is_source`` and cannot tell "it" from
    "this creature", so it fell through to the source. Rebinding the ``Pump``
    subject alone gives that lowering the one thing it could not know, and
    leaves every lowering that had already solved the problem untouched.

    The bound spec **stays a target**: the ability announces one (CR 601.2c) and
    both arms move it, so the two arms carry the identical ``targets`` payload
    and the picker asks once. That is the opposite choice from
    :func:`rebind_pronoun_to_delay_target`, which drops the targeting — a
    delayed ability fires later and its opener already chose.
    """
    if not isinstance(statement, ast.Sequence):
        return statement
    announced: "ast.TargetSpec | None" = None
    steps: list[ast.Statement] = []
    for step in statement.steps:
        if announced is not None:
            step = _rebind_pump_subject(step, announced)
        elif (found := _announced_target(step)) is not None:
            announced = found
        steps.append(step)
    if all(a is b for a, b in zip(steps, statement.steps)):
        return statement
    return replace(statement, steps=tuple(steps))


def _is_clause_back_reference(spec, bound: "ast.TargetSpec") -> bool:
    """Whether *spec* is the bare "that <noun>" naming *bound*.

    Narrow in the same two ways :func:`_rebind_pump_subject` is, and for its
    reason: the quantifier must be the demonstrative, and the noun phrase must
    carry **nothing but its head noun**. "That creature" is a back-reference;
    "that creature you control" is a narrowed one the clause chose for itself,
    and rewriting it would throw the narrowing away.

    Plus a third: the head noun must be one the bound target could be, so a
    clause that chose a land and then talks about a creature keeps its own
    refusal rather than being pointed at the land.
    """
    return (
        isinstance(spec, ast.TargetSpec)
        and spec.quantifier == "that"
        and not spec.targeted
        and set(spec.filter.to_payload()) <= {"type_filter"}
        and spec.filter.card_types == bound.filter.card_types
    )


def _rebind_clause_bound_noun(node, bound: "ast.TargetSpec"):
    """*node* with every bare "that <noun>" back-reference set to *bound*.

    Two node types, listed rather than walked: an :class:`ast.LoseKeyword`
    subject ("…**and that creature** loses flying", Burning Palm Efreet) and an
    :class:`ast.DealDamage` recipient ("…damage equal to its power **to that
    creature**", Abyssal Hunter). Both are the same printed back-reference in
    the same position, and both are the *object* of their clause — which is
    what makes them the pronoun this resolves and not, say, the "that creature"
    a trigger's event bound.

    Not a :func:`_walk_specs` rewrite over every spec, which is what the four
    general rebinders do. See
    :func:`rebind_keyword_loss_pronoun_to_clause_target` for why this one is
    narrow.
    """
    if isinstance(node, ast.CreateDelayedTrigger):
        # "Choose target attacking or blocking creature … This creature deals 2
        # damage to **that creature** at end of combat." (Dwarven Sea Clan.)
        # The same printed words, bound by a different rule: a delayed ability
        # fires later and CR 603.7c makes it *about* the object the creating
        # effect chose, which `rebind_pronoun_to_delay_target` already records
        # by **dropping** the targeting. Rewriting the recipient back into a
        # targeted spec put a picker description on an instruction that runs at
        # end of combat with nobody to ask — the whole-pool differential caught
        # it on the one card in the pool that prints the shape.
        return node
    if isinstance(node, ast.LoseKeyword):
        if _is_clause_back_reference(node.subject, bound):
            return replace(node, subject=bound)
    if isinstance(node, ast.DealDamage) and len(node.recipients) == 1:
        if _is_clause_back_reference(node.recipients[0], bound):
            return replace(node, recipients=(bound,))
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_rebind_clause_bound_noun(getattr(node, field.name), bound),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_rebind_clause_bound_noun(item, bound) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def rebind_keyword_loss_pronoun_to_clause_target(
    statement: ast.Statement,
) -> ast.Statement:
    """"…deals 2 damage to target creature with flying **and that creature loses
    flying** until end of turn." (Burning Palm Efreet); "Tap target creature.
    This creature deals damage equal to its power **to that creature**."
    (Abyssal Hunter.)

    The seventh rebinder, and the only one whose antecedent is a **clause of the
    same sentence**. Vertigo prints those two clauses with a full stop between
    them and has played correctly since Ice Age, because the *sentence* loop
    probes ``pronouns._parse_pronoun_grant_rider`` between sentences and that
    production reads the previous sentence's target. Join the two with "and"
    instead and the conjunction loop in ``statements.py`` never reaches it — so
    "that creature" fell through to the bare-noun reading and the lowering
    refused it, one printed word away from a card that works.

    It cannot be fixed where it is found. ``pronouns`` sits *above*
    ``statements`` in this package's layer order (`test_grammar_layering.py`),
    so the conjunction loop may not call that production; the referent is
    resolved here instead, where every other cross-clause pronoun is, and the
    parser applies it to a whole line's statement.

    Narrow for :func:`rebind_pump_pronoun_to_sentence_target`'s reason and
    demonstrably so: a whole-pool differential over both manifest roles moved
    exactly the cards that print this shape. The bound spec **stays a target** —
    the ability announces one (CR 601.2c) and both clauses act on it, so the two
    instructions carry the identical ``targets`` payload and the picker asks
    once.
    """
    if not isinstance(statement, ast.Sequence):
        return statement
    announced: "ast.TargetSpec | None" = None
    steps: list[ast.Statement] = []
    for step in statement.steps:
        if announced is not None:
            step = _rebind_clause_bound_noun(step, announced)
        elif (found := _announced_target(step)) is not None:
            announced = found
        steps.append(step)
    if all(a is b for a, b in zip(steps, statement.steps)):
        return statement
    return replace(statement, steps=tuple(steps))


def _rebind_source_watching_delay(node, bound: "ast.TargetSpec"):
    """*node* with every source-watching delay's bare pronoun pointed at
    *bound*.

    Narrow on purpose, the way :func:`_rebind_pump_subject` is: it rewrites one
    node type, under one condition, and leaves every other reading of a bare
    pronoun exactly as it was. See
    :func:`rebind_delayed_pronoun_to_sentence_target` for the argument.
    """
    if isinstance(node, ast.CreateDelayedTrigger) and node.watches == "source":
        rebound = _walk_specs(
            node.effect,
            lambda spec: (
                bound
                if spec.quantifier == "it"
                and spec.filter.is_source
                and spec.filter.to_payload() == {}
                else None
            ),
        )
        if rebound is not node.effect:
            # CR 603.7c: the ability is now *about* an object the creating
            # effect chose, which is exactly what ``binds_target`` says — and
            # the opener already granted the permission by naming a different
            # object as the one it watches. Set here rather than left to
            # ``delay_binds_an_object``, which ran on the sentence before the
            # pronoun had an antecedent and could only answer False.
            return replace(node, effect=rebound, binds_target=True)
        return node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_rebind_source_watching_delay(getattr(node, field.name), bound),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_rebind_source_watching_delay(item, bound) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def rebind_delayed_pronoun_to_sentence_target(statement: ast.Statement) -> ast.Statement:
    """"{T}: For as long as this creature remains tapped, **target tapped
    creature** doesn't untap … . When this creature leaves the battlefield or
    becomes untapped, remove all -1/-1 counters from **the creature**."
    (Giant Oyster.)

    The sixth rebinder, and :func:`rebind_pump_pronoun_to_sentence_target`'s
    sibling: the antecedent is in a *previous sentence of the same printed
    line*, which nothing inside the second sentence's parse can see.
    ``parse_recipient`` reads "the creature" as the bare pronoun — the same spec
    a card naming itself produces — so the removal lowered to
    ``remove_all_counters_from_self`` and the Oyster took its own counters off.
    A card that compiles supported, claims every printed sentence and carries no
    hollow line, doing something other than what it says.

    **The gate is the delay saying which object it watches.** A delay whose
    opener names its own source ("when **this creature** leaves the battlefield
    or becomes untapped") has already spent that reference: the sentence behind
    the comma is about something else, or it is about a permanent the opener
    just said had left. Merieke Ri Berit, War Barge and Phantasmal Mount all
    print "that creature" there and are untouched by this; no card in the pool
    prints a bare pronoun under a source-watching delay meaning its own source,
    and a card that did would have to say "this creature" to be readable at
    all — which is a different spec and is not rewritten.

    That narrowness is the whole design, and it is
    :func:`rebind_pump_pronoun_to_sentence_target`'s lesson applied rather than
    re-learned: the obvious version walks every spec in every later sentence,
    and eight shipped cards print a bare "it" after a targeting sentence whose
    lowerings already resolve the ability's target themselves.
    """
    if not isinstance(statement, ast.Sequence):
        return statement
    announced: "ast.TargetSpec | None" = None
    steps: list[ast.Statement] = []
    for step in statement.steps:
        if announced is not None:
            step = _rebind_source_watching_delay(step, announced)
        elif (found := _announced_target(step)) is not None:
            # The bound spec keeps the sentence's noun phrase and **stops being
            # a target**: CR 601.2c chose the object once, when the ability was
            # activated, and a second targeted spec would ask the picker again.
            # The same choice :func:`rebind_pronoun_to_delay_target` makes, and
            # the opposite of the pump one — a delayed ability fires later.
            announced = replace(found, quantifier="that", targeted=False)
        steps.append(step)
    if all(a is b for a, b in zip(steps, statement.steps)):
        return statement
    return replace(statement, steps=tuple(steps))


def _rebind_bound_noun(node, bound: "ast.TargetSpec"):
    """*node* with every bare "that <noun>" spec replaced by *bound*.

    Narrow in the same two ways :func:`_rebind_pump_subject` is, and for its
    reason: the quantifier must be the demonstrative, and the noun phrase must
    carry **nothing but its head noun**. "That creature" is a back-reference;
    "that creature you control" is a narrowed one the sentence chose for
    itself, and rewriting it would throw the narrowing away.
    """
    if (
        isinstance(node, ast.TargetSpec)
        and node.quantifier == "that"
        and not node.targeted
        and node.filter.to_payload() == bound.filter.to_payload()
    ):
        return bound
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_rebind_bound_noun(getattr(node, field.name), bound),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_rebind_bound_noun(item, bound) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def rebind_alternative_pronoun_to_choice_target(node: "ast.OneOf") -> "ast.OneOf":
    """"Put a +1/+1 counter on **target creature** or **that creature** gains
    banding, first strike, or trample." (Nature's Blessing.)

    The sixth rebinder, and the only one whose antecedent is in a *sibling
    alternative*. The alternatives of an :class:`ast.OneOf` are two readings of
    one action (CR 608.2d), so the ability announces its targets once
    (CR 601.2c) and whichever alternative the controller takes acts on them —
    which is exactly what a second targeted spec would break, by asking the
    picker for a target the card never offered. The bound spec therefore stays
    a *target*, the same choice :func:`rebind_pump_pronoun_to_sentence_target`
    makes and the opposite of :func:`rebind_pronoun_to_delay_target`'s.

    Without it the later alternative's subject is a demonstrative nothing
    binds, and the keyword grant behind it refuses with "unsupported
    keyword-grant subject" — a refusal naming the subject rather than the
    binding, which is the shape a reader mistakes for a missing production.

    Only alternatives *after* the one that announced the target are rewritten:
    a demonstrative in front of its antecedent names something earlier in the
    line, which is a different question and has its own rebinders above.
    """
    announced: "ast.TargetSpec | None" = None
    options: list = []
    for option in node.options:
        if announced is not None:
            option = _rebind_bound_noun(option, announced)
        elif (found := _announced_target(option)) is not None:
            announced = found
        options.append(option)
    if all(a is b for a, b in zip(options, node.options)):
        return node
    return replace(node, options=tuple(options))


#: The bare noun an ordinal back-reference may restate. "The first **creature**"
#: and nothing narrower: a restated adjective would be a narrowing the bound
#: object cannot honour, and the walk below leaves such a spec alone so its
#: lowering refuses by name.
_FIRST_CREATURE = ast.ObjectFilter(card_types=("creature",))


def rebind_first_creature_to_damage_source(
    action: ast.Statement, branch: ast.Statement
) -> ast.Statement:
    """"…you may have **it** deal damage equal to its power to target creature.
    If you do, **the first creature** assigns no combat damage this turn."
    (Laccolith Rig.)

    The seventh rebinder, and its antecedent is in the *offer* the branch hangs
    on. The offer names two creatures — the one that deals the damage and the
    one it is dealt to — and the ordinal says which of the two it means by the
    order they were printed in. The first is the damage's source; that is the
    whole of the reading, and it is the same object the bare pronoun in front of
    it named, so the branch's spec becomes that pronoun's spec. Whatever the
    pronoun is then rebound to (the enchanted creature, under an Aura's
    trigger — ``rebinding.rebind_pronoun_to_event_subject``) the ordinal follows
    it for free, because by then it *is* that pronoun.

    Narrow in the two ways every rebinder here is. The offer has to be a damage
    from a single bound object (a pronoun, never a target — a chosen source is a
    second choice the ordinal would quietly take over) to exactly one creature
    recipient, which is the only shape where "first" and "second" are two
    creatures at all. And only the bare "the first creature" is rewritten: a
    narrowed ordinal stays an ordinal, which every lowering but the pair-member
    one refuses by name. Anything else leaves *branch* untouched, so Infinite
    Authority's "the first creature" — a *pair* member its own trigger bound —
    keeps the reading ``lowering/_plus_one_counters`` gives it.
    """
    if not isinstance(action, ast.DealDamage):
        return branch
    source = action.source
    if not (
        isinstance(source, ast.TargetSpec)
        and source.quantifier in ("it", "this")
        and not source.targeted
    ):
        return branch
    recipients = tuple(action.recipients or ())
    if len(recipients) != 1 or not (
        isinstance(recipients[0], ast.TargetSpec)
        and "creature" in recipients[0].filter.card_types
    ):
        return branch

    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.quantifier == "first" and spec.filter == _FIRST_CREATURE:
            return source
        return None

    return _walk_specs(branch, _rewrite)
