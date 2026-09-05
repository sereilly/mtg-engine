"""The branches of an offer, and the clauses that fold into one.

"You may pay {1}. **If you do**, …", "…**If you can't**, …", "…**When you do**,
…", "**Otherwise**, …". Each of these is a *branch* of the sentence before it
rather than a sentence of its own: CR 601.2b's optional cost and CR 603.12's
reflexive trigger both hang a consequence off a decision, and a branch parsed as
a step would run whether or not the decision went that way — which is Blood
Lust giving a creature +8 power and killing it, and Delif's Cone marking a
creature that never attacked.

Split out of ``riders.py`` at the thousand-line guard, along the boundary that
module already drew: everything here answers "which branch of the offer before
it does this clause belong to", where the rest of ``riders`` answers "what does
this clause say about the step before it". The name is the one
``lowering/control_flow.py`` has carried since the ``may`` / ``if_then``
wrappers went there, so the mirror re-forms rather than forking — these
productions are exactly what lowers through it.

Beside ``riders`` rather than under it: neither imports the other, and both sit
above ``statements``, which hands both of them ``parse_statement``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
from .errors import GrammarError
from .nouns import parse_object_filter
from .rebinding import (rebind_pronoun_to_condition_target,
                        rebind_pronoun_to_delay_target)
from .statements import parse_statement
from .stream import TokenStream


def _attach_otherwise(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """``Otherwise, <statement>.`` after a conditional sentence (Blood Lust).

    The second arm of the sentence before it, not a step of its own: run as a
    step it would happen *as well as* the arm that already ran, and Blood Lust
    would give a 5-toughness creature +8 power and kill it.

    A :class:`ast.Conditional` or a :class:`ast.May`, in either case only when
    it has no second arm yet. The offer's negative branch is the same field
    whichever word the card prints for it — "If you don't, …" and "Otherwise, …"
    are one sentence (Spitting Slug prints the second) — so folding this onto
    the offer is reading it, not reinterpreting it. A second "Otherwise" after
    the first is a card this cannot read, and it refuses rather than
    overwriting the arm it read first.

    The pronoun in a conditional's arm is rebound the same way the first arm's
    was, and from the same condition — both arms of one sentence say "it" about
    the same creature, and rebinding only the arm that happened to be parsed
    inside ``parse_statement`` would leave this one pumping the spell on the
    stack. An offer has no condition to rebind against: what its "otherwise"
    arm is about is whatever that arm names for itself.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, (ast.Conditional, ast.May)) or last.otherwise is not None:
        return False
    mark = stream.mark()
    if not stream.accept_word("otherwise"):
        return False
    stream.accept_punct(",")
    try:
        arm = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if isinstance(last, ast.May):
        steps[-1] = dataclasses.replace(last, otherwise=arm)
        return True
    steps[-1] = dataclasses.replace(
        last,
        otherwise=rebind_pronoun_to_condition_target(last.condition, arm),
    )
    return True
def _choice_step_index(steps: list[ast.Statement]) -> int | None:
    """Where the choice a following "If the player does/don't" refers back to is.

    The chooser is a seat the sentence *asked something of*, and one step in
    this grammar does that without being an offer: ``ChoosePermanent``. Located
    by walking back past the branch already folded onto it, so the second rider
    of a pair finds the same step the first one did.

    Returns None when no such step precedes, which is what keeps the pronoun
    from being read as "you" on a line that never asked anybody anything.
    """
    for index in range(len(steps) - 1, -1, -1):
        step = steps[index]
        if isinstance(step, ast.ChoosePermanent):
            return index
        if isinstance(step, ast.Conditional) and isinstance(
            step.condition, ast.ItHappened
        ):
            continue
        return None
    return None


def _sacrifice_noun(statement) -> "ast.ObjectFilter | None":
    """The noun phrase a ``Sacrifice`` statement names, or None for anything
    else. The step a "…sacrifice a <noun> this way" rider is measured against."""
    if isinstance(statement, ast.Sacrifice) and isinstance(
        statement.subject, ast.TargetSpec
    ):
        return statement.subject.filter
    return None


def _accept_restated_sacrifice(
    stream: TokenStream, offered: "ast.ObjectFilter | None"
) -> "tuple[bool, ast.ObjectFilter | None] | None":
    """``sacrifice <noun phrase> [this way]`` — the rider with its verb spelled
    out instead of said as "do".

    "If you **sacrifice a snow Forest this way**, …" (Gargantuan Gorilla) and
    "If you **sacrifice an Island this way**, …" (Serendib Djinn) are the
    "if you do" rider with the action restated and *narrowed*. The narrowing is
    the whole point: the sacrifice happened, and the branch runs only if what
    went matches the tighter phrase.

    Returns ``(narrowed, filter)``, or None with the cursor untouched.
    ``narrowed`` is False when the phrase merely repeats what the step in front
    of it already said — a plain "if you do" written out longhand, which is how
    "If you **don't sacrifice a Forest**" (Gargantuan Gorilla again) is the
    ordinary decline branch rather than a condition nothing records.

    Any *other* phrase is carried as a filter and tested against what actually
    went. It is deliberately **not** checked for being a subset of the offer's:
    the two are written in different vocabularies — Serendib Djinn offers "a
    land" (a card type) and asks about "an Island" (a subtype) — so a
    syntactic subset test refuses the real card while buying nothing. A phrase
    that is genuinely wider reads literally and is right anyway; one that is
    disjoint is never true, which is also what the card would say.
    """
    if offered is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("sacrifice", "sacrifices"):
        return None
    stream.accept_word("a", "an")
    try:
        named = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # "…this way" is optional because the decline branch cannot print it:
    # nothing was sacrificed, so there is no "way" to point at.
    stream.accept_phrase("this", "way")
    if named == offered:
        return False, None
    return True, named


def _mandatory_named_actor(statement) -> "ast.PlayerRef | None":
    """The seat a **mandatory** action names as its actor, or None.

    "That creature's controller sacrifices it at end of combat" (Basalt Golem)
    names a seat without offering it anything, so "if the player does" has an
    antecedent even though there is no ``May`` in front of it. The rider still
    asks a real question — CR 701.21a's sacrifice does not happen if the
    permanent has already left — which is exactly what ``ItHappened`` tests.

    Read off the statement's own ``player`` field rather than from a list of
    node types: every action in this grammar that names who performs it carries
    the seat there, and a list would go stale the day a second one prints the
    rider.
    """
    player = getattr(statement, "player", None)
    if isinstance(player, ast.PlayerRef) and player.kind != "you":
        return player
    return None


def _attach_if_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you do, …" / "If you don't, …" into the preceding ``May``.

    These are branches of the optional action, not steps of their own: "You may
    pay {1}. If you do, you gain 1 life." is one decision with a consequence.
    Parsing them as separate sentences would make the life gain unconditional —
    the same class of mistake as treating "you may pay {2}" as a plain cost.
    """
    # "You may draw X cards, where X is …. If you do, discard a card."
    # (Sanctum of Calm Waters.) The where-clause wraps the whole sentence, so
    # the May is one level down — lifted off here and put back on outside the
    # fold, because the definition binds the branch as well as the offer.
    target = steps[-1]
    # "…If that card is returned to its owner's hand this way, you may pay
    # {U}{U}{U}. **If you do**, …" (Puppet Master.) The offer is one level down
    # inside the conditional the previous rider built, and the branch belongs to
    # the offer, not to the conditional: read as a step of its own it would ask
    # whether an `if_then` "happened", which records nothing, and read as a
    # second conditional it would return the Aura whether or not the mana was
    # paid. Unwrapped here and rewrapped below, exactly as the `WhereX` lift
    # beneath it does.
    conditional = target if isinstance(target, ast.Conditional) else None
    if conditional is not None:
        target = conditional.then
    # "…**you may** gain life equal to its power. **If you do**, it assigns no
    # combat damage this turn." (Delif's Cone.) The offer is one level down
    # inside the delayed ability the previous sentence created (CR 603.7), and
    # the branch belongs to the offer rather than to the sentence that armed it:
    # left outside, "if you do" would ask whether *creating the ability*
    # happened — which it always did — and mark a creature that never attacked.
    # Unwrapped here and rewrapped below, exactly as the two lifts around it do.
    delay = target if isinstance(target, ast.CreateDelayedTrigger) else None
    if delay is not None:
        target = delay.effect
    definition = target.definition if isinstance(target, ast.WhereX) else None
    if definition is not None:
        target = target.statement
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    # "If **a player** does, …" (Rebirth) is the same rider under an offer made
    # to more than one seat: the offer is one decision per player, and this asks
    # of each of them whether they took it. The third person is the whole
    # difference, so it is a spelling of the subject rather than a second
    # production — and it is admitted only over a ``May`` whose actor is not
    # "you", where the words have somebody to refer to.
    third_person = False
    # "If **the player** does, …" (Chain Lightning) is the same rider under an
    # offer made to one seat that is not the caster. The definite article is
    # what separates it from "a player": "a" asks *of each* seat a multi-seat
    # offer named, "the" names the single seat the offer already picked — so
    # the two admit under different conditions rather than being spellings of
    # one thing.
    definite = False
    # "If **the player** does, … If **they** don't, …" (Takklemaggot). The seat
    # is the one the sentence before it named — the chooser — so the pronoun
    # refers back exactly as "a player" does under an offer, and it is admitted
    # only over a step that really asked somebody something (checked below).
    #
    # The same two printed words carry both readings, so "the player" raises
    # both flags and what separates them is the sentence in front: with a
    # choice step it is the chooser, without one it is the offer's single seat.
    # A word that can only be the chooser ("they") raises only that flag.
    chooser_person = False
    if stream.accept_word("you"):
        pass
    elif stream.accept_phrase("a", "player"):
        third_person = True
    elif stream.accept_phrase("the", "player"):
        third_person = True
        definite = True
        chooser_person = True
    # "If **that player** does, …" (Farrel's Mantle) is the same rider under an
    # offer made to a seat the *trigger* named — "its controller may have it
    # deal damage …". The demonstrative points at the seat the offer already
    # picked, exactly as the definite article beside it does, so it admits under
    # the same condition; what it is not is the chooser reading, because there
    # is no choice step in front of it to name one.
    elif stream.accept_phrase("that", "player"):
        third_person = True
        definite = True
    elif stream.accept_word("they"):
        third_person = True
        # Anaphoric like "the player" and never distributive: "they" points at
        # the seat the sentence in front of it named, so the referent test below
        # is the definite one. Without this flag the pronoun was refused over an
        # offer made to "that player" — Mind Whip prints exactly that pair ("…
        # **that player** may pay {3}. **If they don't**, …") and the sentence
        # failed at the pronoun, which reads as a missing production rather than
        # as the referent rule it was.
        definite = True
        chooser_person = True
    else:
        stream.reset(mark)
        return False

    # Which verb form the subject takes. "They" is plural however many players
    # it names ("If **they don't**", Takklemaggot), so the person of the subject
    # is not the person of the verb — reading one off the other is what made the
    # pronoun spelling refuse a sentence it had already read the subject of.
    singular = third_person and not stream.at_word("do", "don't")
    # The noun phrase the step in front of this rider sacrifices, if it does —
    # what a rider that spells its verb out is measured against. Read off the
    # already-unwrapped target, so an offer inside a where-clause, a delay or a
    # previous conditional is seen the same way the fold below sees it.
    offered = _sacrifice_noun(
        target.action if isinstance(target, ast.May) else target
    )
    narrowed = None
    if stream.accept_word("does" if singular else "do"):
        declined = False
    elif (
        stream.accept_word("doesn't" if singular else "don't")
        or stream.accept_phrase("does" if singular else "do", "not")
    ):
        declined = True
        # "If you don't **sacrifice a Forest**, …" (Gargantuan Gorilla) — the
        # decline branch with its verb written out. Only the *unnarrowed*
        # restatement reads: nothing was sacrificed, so a tighter phrase would
        # describe a set that cannot exist, and the words are put back rather
        # than dropped.
        restated = _accept_restated_sacrifice(stream, offered)
        if restated is not None and restated[0]:
            stream.reset(mark)
            return False
    else:
        # "If you **sacrifice a snow Forest this way**, …" — the affirmative
        # rider with its verb written out, which is the only form the narrowing
        # can be printed in at all: "if you do" has nowhere to put it.
        restated = _accept_restated_sacrifice(stream, offered)
        if restated is None:
            stream.reset(mark)
            return False
        declined = False
        narrowed = restated[1]
    # "If a player does **either**, destroy this enchantment." (Worms of the
    # Earth.) The word points back at the two alternatives the offer printed, so
    # it is admitted only over an offer that really has two — over a single
    # action it would be naming a choice the card never gave, and dropping it
    # would let the same sentence fold onto an offer of one thing.
    if stream.accept_word("either") and not (
        isinstance(target, ast.May) and isinstance(target.action, ast.OneOf)
    ):
        stream.reset(mark)
        return False

    if chooser_person and _choice_step_index(steps) is not None:
        # A choice the card offers, not a payment: both branches are real, and
        # which one runs is whether anything was chosen. Handled below.
        pass
    elif third_person and definite and _mandatory_named_actor(target) is not None:
        # "That creature's controller **sacrifices** it at end of combat. **If
        # the player does**, …" (Basalt Golem.) The third admission, beside the
        # offer and the choice: an action that is not optional and not the
        # caster's. The rider still asks whether the step took place — a
        # sacrifice of a creature that has already left does not happen — and
        # "the player" names the seat the action itself named, which is the same
        # anaphora the offer reading uses one branch down.
        pass
    elif third_person and not (
        isinstance(target, ast.May)
        and (
            target.actor.kind != "you"
            if definite
            else target.actor.kind not in ("you", "that_player")
        )
    ):
        # Nothing for "a player" to refer back to: the offer named one seat, or
        # there was no offer at all. Refused rather than read as "you", which
        # would put the branch on the caster whoever actually took the action.
        stream.reset(mark)
        return False

    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if delay is not None and delay.target is not None:
        # The branch is a sentence of the delayed ability, so its pronouns name
        # what that ability is about (CR 603.7c) rather than its source — the
        # same rebinding the delay gave the sentence in front of it, applied
        # here because this half arrives a sentence later.
        branch = rebind_pronoun_to_delay_target(delay.target, branch)

    if chooser_person and (choice_at := _choice_step_index(steps)) is not None:
        # "…chooses a creature …. **If the player does**, <A>. **If they
        # don't**, <B>." (Takklemaggot.) One offer with two consequences, so the
        # second rider folds into the conditional the first one built rather
        # than becoming a step whose condition nothing records — and the choice
        # itself is marked optional here, because printing a "don't" branch is
        # the card saying the seat may decline.
        steps[choice_at] = replace(steps[choice_at], optional=True)
        if declined:
            if not (
                isinstance(steps[-1], ast.Conditional)
                and isinstance(steps[-1].condition, ast.ItHappened)
                and steps[-1].otherwise is None
            ):
                stream.reset(mark)
                return False
            steps[-1] = replace(steps[-1], otherwise=branch)
            return True
        steps.append(ast.Conditional(ast.ItHappened(), branch))
        return True

    if not isinstance(target, ast.May):
        if conditional is not None:
            # The unwrapped step was not an offer, so the branch is not the
            # offer's — put the words back and let the ordinary readings have
            # them rather than pairing them with a conditional that records
            # nothing.
            stream.reset(mark)
            return False
        # "Exile it. **If you do**, create a … token." (Archfiend's Vessel.)
        # The preceding action was not optional, so there is no decision to
        # branch on — the branch asks whether the action *took place*, and the
        # pairing with the step before it is made here, where "the step before
        # it" is a fact rather than a guess.
        # "If you **don't**" has no reading here: an action that was not
        # optional has no declining, so the words are refused rather than
        # folded onto a branch that could never be taken.
        if declined:
            stream.reset(mark)
            return False
        rider = ast.Conditional(
            ast.SacrificedThisWay(narrowed) if narrowed is not None
            else ast.ItHappened(),
            branch,
        )
        if delay is not None:
            # "…sacrifices it **at end of combat**. If the player does, they
            # create a … token." (Basalt Golem.) The branch is a sentence of
            # the *delayed* ability — the unwrap above already says so, and the
            # rebinding two paragraphs up acts on it — so it goes back inside
            # rather than beside. Left as a sibling it would run when the
            # trigger resolved, a whole combat before the sacrifice it asks
            # about, and read a record nothing had written.
            #
            # Appended to the delay's own steps rather than nested under a
            # second `Sequence`, so `_lower_steps` sees the sacrifice and the
            # rider as consecutive steps of one effect — which is what lets the
            # rider read what the step in front of it recorded.
            inner = delay.effect
            joined = ast.Sequence(
                (*inner.steps, rider) if isinstance(inner, ast.Sequence)
                else (inner, rider)
            )
            steps[-1] = replace(delay, effect=joined)
            return True
        steps.append(rider)
        return True

    may = target
    # A narrowed affirmative rider is a *conditional inside* the accept branch,
    # not the accept branch itself: the offer can be taken and the branch still
    # not run, because what the player gave up may not have matched the tighter
    # phrase. Folded onto ``then`` unconditionally, Gargantuan Gorilla would
    # gain trample for any Forest.
    accepted = (
        ast.Conditional(ast.SacrificedThisWay(narrowed), branch)
        if narrowed is not None else branch
    )
    # ``replace``, never a field-by-field rebuild. The offer node carries
    # nine fields and this fold is about two of them; naming the rest by hand
    # dropped every one it did not mention, silently — Emberwilde Djinn's
    # "may pay {R}{R} **or 2 life**" parsed its alternative and lost it here,
    # and Winter's Chill's graded outcomes would go the same way the day one
    # of them is printed behind an "if you do". A field added to ``May`` is
    # carried from now on rather than forgotten at the next fold.
    folded = replace(
        may,
        then=accepted if not declined else may.then,
        otherwise=branch if declined else may.otherwise,
    )
    rebuilt = ast.WhereX(folded, definition) if definition is not None else folded
    if delay is not None:
        rebuilt = replace(delay, effect=rebuilt)
    if conditional is not None:
        rebuilt = replace(conditional, then=rebuilt)
    steps[-1] = rebuilt
    return True


def _bind_that_creature_after_enchanted(branch: ast.Statement) -> ast.Statement:
    """*branch* with a "that creature" keyword grant bound to the enchanted
    creature an earlier step of the same branch names.

    "…put a +1/+1 counter on **enchanted creature**, and **that creature**
    gains flying." (Cocoon.) "That creature" restates the step before it, and
    the noun parser must not learn the phrase — every sentence printing those
    words would then lower through a filter naming a creature nobody bound. The
    pairing is made here, where the antecedent is a fact: only a bare "that
    creature" is rewritten, and only when an enchanted-creature step precedes
    it in the same branch.
    """
    def bind(
        statement: ast.Statement, enchanted: ast.TargetSpec | None
    ) -> tuple[ast.Statement, ast.TargetSpec | None]:
        # Sequences nest right-leaning ("A, B, and C" parses as (A, (B, C))),
        # so the walk recurses instead of reading one level of steps.
        if isinstance(statement, ast.Sequence):
            rebuilt = []
            for step in statement.steps:
                step, enchanted = bind(step, enchanted)
                rebuilt.append(step)
            return ast.Sequence(tuple(rebuilt)), enchanted
        if (
            isinstance(statement, ast.GainKeyword)
            and isinstance(statement.subject, ast.TargetSpec)
            and statement.subject.quantifier == "that"
            and statement.subject.filter == ast.ObjectFilter(card_types=("creature",))
            and enchanted is not None
        ):
            return replace(statement, subject=enchanted), enchanted
        subject = getattr(statement, "subject", None)
        if isinstance(subject, ast.TargetSpec) and subject.filter.is_enchanted:
            enchanted = subject
        return statement, enchanted

    bound, _ = bind(branch, None)
    return bound


def _attach_if_that_card_was_returned(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If that card is returned to its owner's hand this way, …" into the
    preceding return.

    (Puppet Master.) The long spelling of "If you do" over a mandatory step:
    the return before it was not a choice, so the branch asks whether it
    actually *took place* — which for a card that was exiled in response, or
    whose owner's hand it never reached, it did not (CR 608.2b). So it folds to
    the same :class:`ast.ItHappened` the short spelling does, and
    ``_lower_steps`` pairs it with the step in front of it and checks that step
    records an answer to read.

    Only a ``ReturnToZone`` is folded onto, the way ``_attach_if_you_cant``
    folds only onto a ``RemoveCounter``: the clause names the return by what it
    did, and a wider fold would pair the words with a step whose "this way"
    nobody records.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ReturnToZone):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "that", "card", "is", "returned", "to", "its", "owner", "'s",
        "hand", "this", "way",
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    steps.append(ast.Conditional(ast.ItHappened(), branch))
    return True
def _attach_if_you_cant(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you can't, …" into the preceding mandatory action.

    "At the beginning of your upkeep, remove a pupa counter from this Aura. If
    you can't, sacrifice it, put a +1/+1 counter on enchanted creature, and
    that creature gains flying." (Cocoon.) The mirror of the un-optional
    "If you do" (``ItHappened``): the action before it was mandatory, so there
    is no decision to branch on — the branch asks whether the action *could be
    performed*, which for a counter removal is whether a counter was there to
    remove. Paired with the step in front of it here, where "the step before
    it" is a fact; the lowering (``_lower_steps``) is what checks that the
    step records an answer to read, exactly as it does for "if you do".

    "At the beginning of your upkeep, sacrifice two Swamps. **If you can't**,
    tap this creature, and …" (Infernal Denizen.) The second producing step this
    rider is printed after, and the same question of it: CR 701.21a makes
    sacrificing a permanent you do not control impossible, so "can't" is a board
    the printed count cannot be paid out of. The sacrifice records the answer
    the way the counter removal does (``_PRODUCES``), which is what keeps this
    fold from being a claim the lowering cannot check.

    Only these two are folded onto: they are the producing steps the pool prints
    this rider after, and a wider fold would pair the words with steps whose
    "can't" nobody records.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, (ast.RemoveCounter, ast.Sacrifice)):
        return False
    mark = stream.mark()
    if not (
        stream.accept_word("if")
        and stream.accept_word("you")
        and stream.accept_word("can't")
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    steps.append(
        ast.Conditional(ast.CouldNot(), _bind_that_creature_after_enchanted(branch))
    )
    return True


def _attach_when_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "When you do, …" into the preceding ``May`` as its reflexive branch.

    One word apart from ``_attach_if_you_do`` and a different rule (CR 603.12):
    "if you do" is the rest of this resolution, "when you do" is a *new*
    triggered ability the payment creates, which chooses its own targets as it is
    created. Tolarian Kraken is the difference — "you may tap or untap target
    creature" has a target the drawing of a card never named, so folded onto the
    ``then`` branch it would run against whatever the producing action happened
    to point at.

    Read as its own production rather than as a flag on the other so that the
    two cannot be conflated by a later edit to either.
    """
    target = steps[-1]
    definition = target.definition if isinstance(target, ast.WhereX) else None
    if definition is not None:
        target = target.statement
    if not isinstance(target, ast.May):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("when", "you", "do"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False

    # ``replace`` for the reason the fold above states: a rebuild that names
    # the fields it keeps forgets every field the node grows afterwards.
    folded = replace(target, reflexive=branch)
    steps[-1] = ast.WhereX(folded, definition) if definition is not None else folded
    return True
