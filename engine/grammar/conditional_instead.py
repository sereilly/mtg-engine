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
the half that grows.

**One reader of that agreement, and one answer to a mismatch.** Invasion's
first wave wrote it twice, in two groups, disjoint by node type —
``_rebind_replacement_recipient`` for a ``DealDamage`` ("…deals 4 damage to
**it** instead", Lightning Dart), which left a back-reference it could not
place *as written*, and ``_instead_inherits_subject`` for the kinds in
``_INSTEAD_SUBJECT_FIELDS``, which *refused the rider*. The merge kept both in
sequence and the second wave folded them on Urza's Rage, which needed the one
cell neither had: a ``DealDamage`` whose replacement says "that permanent or
player". There is one table now (``DealDamage`` is a row of it) and one
function, and the mismatch rule is the second reader's: **a back-reference
that cannot name the replaced sentence's subject refuses the rider.** Leaving
it as written was never a reading — the word then meant whatever the lowering
made of a bare pronoun, which for "it" is the ability's own source, and a
replacement arm that pumps or burns the source is a different card compiled
supported. See ``_instead_subject`` for the one case where the printed word is
kept, and why that is agreement rather than a mismatch.

The helper stays with the rider rather than joining ``sentence_rebinding``,
whose question ("which target the sentence itself announced does this word
name?") it also answers — and whose own answer to "does this bare *that
<noun>* restate that target?" it now **shares**
(``sentence_rebinding.restates_target``; the three spellings of that test
disagreed until the same fold). It is the second half of the rider's own
table — for each kind in ``_REPLACEABLE``, which field says whom it is done
to — and it answers by **refusing the rider**, which is an admission decision
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
from .sentence_rebinding import restates_target
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
    last = steps[-1] if steps else None
    last_guard, replaced = _guarded(last)
    if not isinstance(replaced, _REPLACEABLE):
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
    # "…, **instead** it deals 10 damage to that permanent or player" (Urza's
    # Rage). The word in front of the sentence it marks rather than behind it:
    # the same pair, and required exactly once — below — so neither spelling
    # can be read with the word missing or doubled.
    fronted = bool(stream.accept_word("instead"))
    try:
        replacement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if type(replacement) is not type(replaced):
        stream.reset(mark)
        return False
    # "Counter target spell **if its mana value is 2 or less**. If this spell
    # was kicked, counter that spell **if its mana value is 4 or less**
    # instead." (Prohibit, Overload.) The replaced sentence carries a trailing
    # condition of its own, so the replacement must carry one too — and one of
    # the same kind, for `_REPLACEABLE`'s reason one level in: a guard of
    # another kind would be a different sentence standing in for this one. The
    # sentence loop is what reads a trailing "if" (it modifies a whole
    # sentence, so no production owns it), and `parse_statement` above never
    # reaches that loop; read here, it is the same reader at the same position.
    guard = None
    if last_guard is not None:
        if not stream.accept_word("if"):
            stream.reset(mark)
            return False
        try:
            guard = _parse_condition(stream)
        except GrammarError:
            stream.reset(mark)
            return False
        if type(guard) is not type(last_guard):
            stream.reset(mark)
            return False
    if fronted == bool(stream.accept_word("instead")):
        stream.reset(mark)
        return False
    replacement = _instead_inherits_subject(replaced, replacement)
    if replacement is None:
        stream.reset(mark)
        return False
    if guard is not None:
        replacement = ast.Conditional(guard, replacement)
    steps[-1] = ast.Conditional(condition, then=replacement, otherwise=last)
    return True


#: The statement kinds the rider can replace. `AddMana` joined `GainLife` for
#: the Antiquities land cycle -- "{T}: Add {C}. If you control an Urza's
#: Power-Plant and an Urza's Tower, add {C}{C} instead." -- which is the same
#: sentence pair with a different verb. `DealDamage` joined them for Gangrenous
#: Zombies -- "…deals 1 damage to each creature and each player. If you control
#: a snow Swamp, this creature deals 2 damage to each creature and each player
#: instead." The replacement must be the *same* kind as what it replaces, so
#: widening the set cannot let one kind silently stand in for another.
#:
#: `Discard`, `Pump` and `PreventDamage` joined them for Invasion's kicker
#: spells -- "Target player discards a card. If this spell was kicked, **that
#: player** discards three cards instead." (Hypnotic Cloud), "Target creature
#: gets +2/+2 until end of turn. If this spell was kicked, **that creature**
#: gets +5/+5 until end of turn instead." (Explosive Growth), "Prevent the next
#: 2 damage that would be dealt to any target this turn. If this spell was
#: kicked, prevent the next 4 damage that would be dealt to **that permanent or
#: player** this turn instead." (Orim's Touch) -- and `CounterSpell` and
#: `Destroy` a wave later for Prohibit and Overload. All but the first two name
#: *whom*, and the second sentence names them by pointing back at the first:
#: see `_INSTEAD_SUBJECT_FIELDS`.
_REPLACEABLE = (
    ast.GainLife, ast.AddMana, ast.DealDamage,
    ast.Discard, ast.Pump, ast.PreventDamage,
    ast.CounterSpell, ast.Destroy,
)


def _guarded(statement):
    """``(guard, action)`` for a sentence that ends in its own "if", else
    ``(None, statement)``.

    "Destroy target artifact **if its mana value is 2 or less**" is a
    :class:`ast.Conditional` with one arm, built by the sentence loop from the
    trailing clause. The rider replaces the *action* and re-reads the guard,
    so it needs the two apart. A conditional that already has a second arm, or
    whose body sits on the false branch ("unless"), is some other sentence and
    is handed back whole -- where its type is not one the rider replaces.
    """
    if (
        isinstance(statement, ast.Conditional)
        and statement.otherwise is None
        and not statement.negated
    ):
        return statement.condition, statement.then
    return None, statement


#: Which field of each replaceable statement says *whom* it is done to -- the
#: rider's second table, one row per kind whose "instead" sentence can point
#: back at the first one's subject. `GainLife` and `AddMana` have none: every
#: card that prints the pair says "you" and the mana outright.
#:
#: `DealDamage` names a *tuple* (its recipients) where the rest name one
#: subject; `_instead_inherits_subject` reads either through one comparison,
#: position by position.
_INSTEAD_SUBJECT_FIELDS = {
    ast.Discard: "player",
    ast.Pump: "subject",
    ast.PreventDamage: "to",
    ast.DealDamage: "recipients",
    ast.CounterSpell: "subject",
    ast.Destroy: "subject",
}

#: The object back-references: a pronoun, a demonstrative, and the marker
#: ``parse_recipient`` reads for "that permanent or player".
_BACK_REFERENCES = ("it", "that", "permanent_or_player")

#: The quantifiers under which an unannounced subject is still **one object**
#: the surrounding ability already has in hand -- its own source, or what its
#: trigger's event named.
_ONE_UNANNOUNCED_OBJECT = ("this", "it", "that")


def _points_back(named) -> bool:
    """Whether *named* names its object by pointing at an earlier one."""
    if isinstance(named, ast.PlayerRef):
        return named.kind == "that_player"
    return (
        isinstance(named, ast.TargetSpec)
        and not named.targeted
        and named.quantifier in _BACK_REFERENCES
    )


def _instead_subject(named, original):
    """What *named* means in a sentence replacing one whose subject is
    *original* -- or None when it cannot mean that subject.

    Only one of the two sentences ever runs (the pair folds to a
    ``Conditional``), so a back-reference in the second has nothing recorded
    in front of it to bind to: its antecedent is the *sentence it replaces*,
    never an earlier step's result. Four answers, in order:

    * **Named outright** ("…deals 2 damage to each creature and each player
      instead", Gangrenous Zombies) -- kept as written.
    * **The identical words** ("that creature" in both sentences of a
      trigger's effect) -- kept: whatever binds the first binds the second.
    * **An announced target, or a seat, it can name** -- it takes that
      subject, target and all, which is also what CR 601.2c needs: the spell
      names one object whichever arm resolves. "That player" after a player;
      "it" after any one target; "that <noun>" after a target that must be one
      (``sentence_rebinding.restates_target``); "that permanent or player"
      after "any target".
    * **"It" after one object the sentence did not announce** -- its own
      source, or the event's subject. Kept as written, and this is agreement
      rather than a tolerated mismatch: nothing in the pair chose an object,
      so the pronoun is the one every other sentence of that ability prints
      and the rebinders that own it read it here as they do there.

    Anything else is a word pointing at something the replaced sentence did
    not name -- a creature after a player, "that creature" after "target
    artifact or creature", "it" after "each creature" -- and refuses.
    """
    if not _points_back(named) or named == original:
        return named
    if isinstance(named, ast.PlayerRef):
        if isinstance(original, ast.PlayerRef) and original.kind != "that_player":
            return original
        return None
    if not isinstance(original, ast.TargetSpec):
        return None
    announced = original.targeted and original.count == 1
    if named.quantifier == "permanent_or_player":
        return original if announced and original.quantifier == "any_target" else None
    if named.quantifier == "it":
        if announced:
            return original
        if not original.targeted and original.quantifier in _ONE_UNANNOUNCED_OBJECT:
            return named
        return None
    return original if announced and restates_target(named, original) else None


def _instead_inherits_subject(replaced, replacement):
    """*replacement* with every back-reference to *replaced*'s subject
    resolved, or None when one points at something *replaced* did not name.

    "…**that player** discards three cards instead" (Hypnotic Cloud),
    "…deals 4 damage to **it** instead" (Lightning Dart), "…it deals 10 damage
    to **that permanent or player**" (Urza's Rage), "…counter **that spell** if
    its mana value is 4 or less instead" (Prohibit). One reader for every
    kind in ``_INSTEAD_SUBJECT_FIELDS``; ``_instead_subject`` is what each
    word means and what a mismatch does.

    A kind with no row names no subject a second sentence could point back
    at, and is passed through.
    """
    field = _INSTEAD_SUBJECT_FIELDS.get(type(replaced))
    if field is None:
        return replacement
    named, original = getattr(replacement, field), getattr(replaced, field)
    if not isinstance(named, tuple):
        resolved = _instead_subject(named, original)
        if resolved is None:
            return None
        return replacement if resolved is named else replace(replacement, **{field: resolved})
    # A recipient list, compared position by position. A list of another
    # length restates nothing position by position, so it is legal only when
    # no word in it points back.
    if len(named) != len(original):
        return None if any(_points_back(each) for each in named) else replacement
    resolved = tuple(_instead_subject(n, o) for n, o in zip(named, original))
    if any(each is None for each in resolved):
        return None
    if all(a is b for a, b in zip(resolved, named)):
        return replacement
    return replace(replacement, **{field: resolved})
