"""``<statement>. If <condition>, <that statement over again> instead.``

"You gain 4 life. If a creature died this turn, you gain 8 life **instead**."
(Life Goes On.) "Target creature gets +2/+2 until end of turn. If this spell
was kicked, that creature gets +5/+5 until end of turn **instead**." (Explosive
Growth.) The second sentence does not follow the first, it *replaces* it —
CR 608.2c's later text modifying the meaning of earlier text — so the pair
folds into one ``ast.Conditional`` with the second sentence on ``then`` and the
first demoted to ``otherwise``. Read as two steps, Life Goes On gains 12.

**This is the "instead" with no "would" in it.** "If a card *would* be put into
your graveyard, exile it instead" names an event and is CR 614.1a's
replacement; those are read where their sentence is (``if_openings``, and the
two riders ``riders._parse_exile_instead_rider`` and
``pronouns._parse_exile_instead_of_leaving_rider``, both of which the sentence
loop tries ahead of this one). Here the word replaces a *sentence*, on a
condition that is simply true or false as the line resolves.

A branch reader, so ``control_flow``'s by family — it writes the same
``Conditional.otherwise`` that module's ``_attach_otherwise`` does, from the
other end — and it lived there from Nemesis' Phase 0 until Invasion's, when it
was pre-split out between that set's first two waves with ``control_flow`` four
lines under the thousand-line guard. The seam is what its arms are. Every
branch left there is a **free sentence** hung on something the line had
already asked: an offer taken or declined, an action that happened or could
not, the arm a conditional has not yet got. None of them requires its branch
to be the same kind of sentence as the step it hangs on, and none calls the
condition parser — of the two branch modules this is now the only one that
imports ``_parse_condition``. The two arms here are **one action printed
twice**, of which exactly one ever runs: the replacement must parse to the
same node type as the sentence it replaces (``_REPLACEABLE``), and where it
names its subject by pointing back — "it", "that creature", "that player",
"that permanent or player" — the antecedent is the replaced sentence's own
subject, so that the spell still announces one target whichever arm resolves
(CR 601.2c). That agreement between the arms is most of this file and it is
the half that grows: both helpers and three of the six replaceable kinds
arrived in Invasion's first wave, 115 of the 169 lines that moved.

The helpers stay with the rider rather than joining ``sentence_rebinding``,
whose question ("which target the sentence itself announced does this word
name?") they also answer. They are the second half of the rider's own table —
for each kind in ``_REPLACEABLE``, which field says whom it is done to — and
one of them answers by **refusing the rider**, which is an admission decision
of this production rather than a rewrite applied after it. A rebinder with no
such tie (``sentence_rebinding._bind_that_creature_after_enchanted``, which
left ``control_flow`` at the same split) went there.

**No mirror name to reuse**, for the reason ``if_openings`` gives:
``ast.Conditional`` is lowered inline by ``statement_dispatch`` as an
``if_then``, not by a lowering family, so the lowering side has no module for
this to be the twin of. The name says what the file reads.

Beside ``control_flow`` rather than under it: neither imports the other. Above
``statements``, whose ``parse_statement`` it re-enters for the replacement, and
below ``sequences``, whose sentence loop is its only caller.
"""

from __future__ import annotations

from dataclasses import replace

from . import ast
from .conditions import _parse_condition
from .errors import GrammarError
from .statements import parse_statement
from .stream import TokenStream


def _parse_conditional_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``You gain 4 life. If a creature died this turn, you gain 8 life
    instead.`` (Life Goes On.) ``{T}: Add {C}. If you control an Urza's
    Power-Plant and an Urza's Tower, add {C}{C} instead.`` (Urza's Mine.)

    The second sentence *replaces* the first when its condition holds, so the
    pair folds into one ``Conditional`` — then the bigger gain, otherwise the
    printed base. Parsed apart, the two sentences would gain 12 life on a
    death; the "instead" is the whole content of the sentence, so it is
    required, and only a same-shaped statement may replace the last step.
    """
    # The statement kinds this rider can replace. `AddMana` joins `GainLife`
    # for the Antiquities land cycle — "{T}: Add {C}. If you control an Urza's
    # Power-Plant and an Urza's Tower, add {C}{C} instead." — which is the same
    # sentence pair with a different verb. `DealDamage` joins them for
    # Gangrenous Zombies — "…deals 1 damage to each creature and each player.
    # If you control a snow Swamp, this creature deals 2 damage to each
    # creature and each player instead." — which is the same pair again. The
    # replacement must be the *same* kind as what it replaces (checked below),
    # so widening the set cannot let one kind silently stand in for another.
    #
    # `Discard`, `Pump` and `PreventDamage` join them for the kicker spells --
    # "Target player discards a card. If this spell was kicked, **that player**
    # discards three cards instead." (Hypnotic Cloud), "Target creature gets
    # +2/+2 until end of turn. If this spell was kicked, **that creature** gets
    # +5/+5 until end of turn instead." (Explosive Growth), "Prevent the next 2
    # damage that would be dealt to any target this turn. If this spell was
    # kicked, prevent the next 4 damage that would be dealt to **that permanent
    # or player** this turn instead." (Orim's Touch). These three name *whom*,
    # and the second sentence names them by pointing back at the first -- see
    # `_instead_inherits_subject`.
    _REPLACEABLE = (
        ast.GainLife, ast.AddMana, ast.DealDamage,
        ast.Discard, ast.Pump, ast.PreventDamage,
    )

    last = steps[-1] if steps else None
    if not isinstance(last, _REPLACEABLE):
        return False
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        replacement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if type(replacement) is not type(last) or not stream.accept_word("instead"):
        stream.reset(mark)
        return False
    # Two readers of one idea - the second sentence's back-reference names the
    # first sentence's subject, because only one of the two ever runs - written
    # in the same wave by two groups and disjoint by node type: the first
    # answers for `DealDamage` ("…deals 4 damage to **it** instead", Lightning
    # Dart), the second for the three kinds in `_INSTEAD_SUBJECT_FIELDS`, and
    # each passes the other's kinds through untouched. Kept in sequence rather
    # than folded at the merge, because they differ in what a mismatch does
    # (the first leaves the sentence as written, the second refuses the rider)
    # and choosing between those is a rules reading, not a merge.
    replacement = _rebind_replacement_recipient(replacement, last)
    replacement = _instead_inherits_subject(last, replacement)
    if replacement is None:
        stream.reset(mark)
        return False
    steps[-1] = ast.Conditional(condition, then=replacement, otherwise=last)
    return True


def _rebind_replacement_recipient(replacement, last):
    """*replacement* with a pronoun recipient pointed at *last*'s one target.

    "Lightning Dart deals 1 damage to **target creature**. If that creature is
    white or blue, Lightning Dart deals 4 damage to **it** instead." The second
    sentence replaces the first, so its "it" is the creature the first one
    targeted — the same object, chosen once (CR 601.2c), dealt one amount or
    the other. Written back as the first sentence's own target spec, both arms
    of the ``Conditional`` describe one target: the picker derives one choice
    and whichever arm runs resolves the same permanent.

    Only for the shape that has an answer: one recipient on each side, the
    first a single announced target, the second a bare "it" or a "that <noun>"
    restating it and narrowing nothing. Anything else is returned unchanged and
    refuses where it always did — an "it" with two targets in front of it names
    neither, and a "that" carrying a narrowing of its own is describing some
    other object.
    """
    if not isinstance(replacement, ast.DealDamage):
        return replacement
    if len(replacement.recipients) != 1 or len(last.recipients) != 1:
        return replacement
    named, chosen = replacement.recipients[0], last.recipients[0]
    if not (
        isinstance(named, ast.TargetSpec)
        and isinstance(chosen, ast.TargetSpec)
        and chosen.targeted
        and chosen.count == 1
        and not named.targeted
    ):
        return replacement
    if named.quantifier == "that":
        restated = replace(named.filter, card_types=())
        if restated != ast.ObjectFilter() or not (
            set(named.filter.card_types) <= set(chosen.filter.card_types)
        ):
            return replacement
    elif named.quantifier != "it":
        return replacement
    return replace(replacement, recipients=(chosen,))


#: Which field of each replaceable statement says *whom* it is done to. Only the
#: kinds whose "instead" sentence can point back at the first one's subject;
#: `GainLife`, `AddMana` and `DealDamage` restate theirs in full on every card
#: that prints the pair, and are passed through untouched.
_INSTEAD_SUBJECT_FIELDS = {
    ast.Discard: "player",
    ast.Pump: "subject",
    ast.PreventDamage: "to",
}


def _instead_inherits_subject(last, replacement):
    """*replacement* with a back-reference to *last*'s subject resolved, or
    None when it points at something *last* did not name.

    "…**that player** discards three cards instead": only one of the two
    sentences ever runs (the pair folds to a `Conditional`), so the pronoun in
    the second has nothing recorded in front of it to bind to -- its antecedent
    is the *sentence it replaces*, never an earlier step's result. It therefore
    takes that sentence's own subject, target and all, which is also what
    CR 601.2c needs: the spell names one player whichever arm resolves.

    A replacement that names its subject outright ("target player discards
    three cards instead" -- not printed, and a second target if it were) is
    kept as written. One that points back must agree with what it points at:
    "that player" after a player, "that creature" after the same card type,
    "that permanent or player" after any target. Anything else refuses the
    rider, so a pronoun is never resolved onto a subject of another kind.
    """
    field = _INSTEAD_SUBJECT_FIELDS.get(type(last))
    if field is None:
        return replacement
    named = getattr(replacement, field)
    original = getattr(last, field)
    if isinstance(named, ast.PlayerRef):
        if named.kind != "that_player":
            return replacement
        if isinstance(original, ast.PlayerRef) and original.kind != "that_player":
            return replace(replacement, **{field: original})
        return None
    if isinstance(named, ast.TargetSpec):
        if named.targeted or named.quantifier not in ("that", "permanent_or_player"):
            return replacement
        if not isinstance(original, ast.TargetSpec):
            return None
        if named.quantifier == "permanent_or_player":
            agrees = original.quantifier == "any_target"
        else:
            agrees = named.filter == original.filter
        return replace(replacement, **{field: original}) if agrees else None
    return replacement
