"""Pronoun rebinding: which object a bare "it" in an effect actually names.

``parse_recipient`` reads a bare "it" as the ability's own source, which is what
the word means on every line whose sentence names nothing else. Two productions
*do* name something else — a trigger whose condition describes the object, and a
conditional whose condition announces a target — and this is where the pronoun
is pointed at it.

Its own module rather than more of ``triggers``: only one of the two rebinders
is about a trigger, and the walk underneath is about the shape of the AST rather
than about either. It sits below ``triggers`` in the layer order because it
imports nothing but ``ast`` — a rebinder that needed a production would be
rebinding by a list of the productions that admit a pronoun, which is the
per-node table the walk exists to avoid.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast


def _walk_specs(node, rewrite):
    """*node* with ``rewrite`` applied to every :class:`ast.TargetSpec` in it.

    A structural walk rather than a per-node table: a pronoun can sit anywhere
    a recipient can, and a list of the productions that admit one goes stale
    the way every fire-site list in this engine has. The walk is shared by both
    rebinders below because it is the whole of what they have in common — what
    a pronoun *becomes* is the only thing that differs, and that is the
    callback.
    """
    if isinstance(node, ast.TargetSpec):
        rewritten = rewrite(node)
        if rewritten is not None:
            return rewritten
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rebound
            for field in dataclasses.fields(node)
            for rebound in (_walk_specs(getattr(node, field.name), rewrite),)
            if rebound is not getattr(node, field.name)
        }
        return replace(node, **changes) if changes else node
    # Tuples and lists alike: the AST is all-tuple today, and a walk that knew
    # only about tuples would step over the first list field somebody adds
    # without saying so — a pronoun quietly left pointing at the wrong object,
    # which is the exact failure this function exists to prevent.
    if isinstance(node, (tuple, list)):
        walked = [_walk_specs(item, rewrite) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


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


def _rebound(node, subject: ast.ObjectFilter):
    """*node* with every bare pronoun rebound to *subject*, or *node* itself."""
    def _rewrite(spec: ast.TargetSpec) -> ast.TargetSpec | None:
        if spec.quantifier == "it" and spec.filter.is_source:
            return replace(spec, filter=subject)
        return None

    return _walk_specs(node, _rewrite)


def rebind_pronoun_to_event_subject(
    event: ast.TriggerEvent, statement: ast.Statement
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
    """
    subject = event.subject
    if not isinstance(subject, ast.ObjectFilter) or subject.is_source:
        return statement
    return _rebound(statement, subject)


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
