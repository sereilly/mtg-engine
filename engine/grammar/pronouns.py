"""Riders whose subject is a **pronoun** pointing at the sentence before it.

"Put a +1/+1 counter on up to one target creature. **It** gains indestructible
until end of turn." The pronoun names the previous sentence's chosen object, and
nothing inside one sentence's parse can see back that far — so these read the
statement already parsed, bind to what it chose, and either append a step or
fold into it.

Split out of `riders.py` at the thousand-line guard, along the boundary that
module already drew: everything here answers "what does this pronoun name?".
When it left, the rest of `riders.py` answered "which branch of the sentence
before it does this clause belong to"; that half is `control_flow` now, and
what `riders` keeps is the clause that *narrows* the step before it. None of
the three imports another. The binding these read is
`rebinding.statement_bound_target`, one layer down — and since Nemesis' Phase 0
this is the only one of the three that reads it.

That Phase 0 is when the **possessive** arrived: "**Its controller** creates a
token" and "**That creature's controller** reveals cards …" (the three
functions at the bottom). They had stayed behind in `riders` when this module
left, and they are this module's question word for word — the possessive names
the permanent the sentence before it removed, guarded on the same
`statement_bound_target` as the verb, counter and grant riders above, and each
*appends a step* rather than folding a flag, which nothing left in `riders`
does. The grant rider here had been stepping round them the whole time: it
claims "that creature" only when a grant verb follows, "so 'that creature's
controller …' (a different referent) keeps its own reading".
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from ..oracle_types import LAST_TARGET_CONTROLLER
from . import ast
from .errors import GrammarError
from .lexer import PT, QUOTE
from .nouns import parse_object_filter
from .effects import (_parse_create_token, _parse_gains, _parse_gets,
                      _parse_loses, _parse_put_counter)
from .effects.characteristics import _parse_quoted_abilities
from .phrases import _accept_self_reference
from .rebinding import statement_bound_target as _statement_bound_target
from .rebinding import (statement_bound_several_targets
                        as _statement_bound_several_targets)
from .statements import _parse_condition, _parse_statement_body
from .stream import TokenStream
from .tolls import _accept_trailing_toll
from .vocabulary import CARD_TYPES


_RIDER_FOLDED = ast.RawEffect("rider-folded")


def _parse_pronoun_verb_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Untap that creature.`` after a sentence that chose one.

    The sibling of :func:`_parse_pronoun_grant_rider`: that one binds the
    previous target to a *grant*, this one to a plain imperative verb. "Untap
    that creature" (Traitorous Greed) has no target of its own — the spell chose
    one sentence ago, and re-parsing it as a fresh target would raise a second
    picker for a choice CR 601.2c says was made once.

    Only "untap" today, and one verb at a time deliberately: each imperative has
    to be checked against the shape its handler implements, and a table of verbs
    admitted wholesale would claim sentences nothing performs.
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("untap"):
        return None
    if not (
        stream.accept_phrase("that", "creature")
        or stream.accept_phrase("that", "permanent")
        or stream.accept_word("it")
    ):
        stream.reset(mark)
        return None
    return ast.Untap(target)


def _parse_plural_pronoun_pump_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Each of them gets +N/+N [duration].`` after a sentence that chose
    **several** targets.

    "Untap two target creatures. **Each of them** gets +1/+1 until end of turn."
    (Hope and Glory.) The plural of the "it" the two riders around it bind, and
    it needs its own production for the reason it needs its own antecedent
    reader (:func:`rebinding.statement_bound_several_targets`): "each of them"
    is not a pronoun the subject parser reads at all — the line refused at
    "expected a subject" — and every reader of the singular binding hands its
    spec to a lowering that resolves one permanent.

    Read by parsing the pump with the ordinary production once the pronoun has
    been consumed and the bound spec handed in as its subject, which is the
    counter rider's method next door and for its reason: "+1/+1", "-0/-2", a
    "where X is …" tail and the duration are all things ``_parse_gets`` already
    reads, and a rider that re-spelled the pump would be free to disagree about
    any of them.

    The bound spec **stays a target**, exactly as
    :func:`rebinding.rebind_pump_pronoun_to_sentence_target` keeps its own: CR
    601.2c chose the two creatures once, both steps carry the identical
    ``targets`` payload, and the picker therefore asks once for the spell rather
    than twice.

    "Each" is required and is not decorative. Without a distributive word the
    sentence would be "they get +1/+1", which English also allows and no card in
    this pool prints; admitting a spelling nobody prints is how a production
    comes to claim a sentence it has not been checked against.
    """
    second_pump = _parse_pronoun_pump_rider(stream, steps)
    if second_pump is not None:
        return second_pump
    target = _statement_bound_several_targets(steps[-1]) if steps else None
    if target is None:
        return None
    mark = stream.mark()
    if not stream.accept_phrase("each", "of", "them"):
        return None
    if not stream.at_word("gets", "get"):
        stream.reset(mark)
        return None
    try:
        statement = _parse_gets(stream, target)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(statement, ast.Pump):
        # "Each of them gets a poison counter" would be a pronoun for a set of
        # *players*, which this binding cannot mean — put the words back and let
        # the sentence fail loudly rather than binding it to permanents.
        stream.reset(mark)
        return None
    return statement


def _parse_pronoun_pump_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """A **second pump** on what the pump before it named, read off that pump.

    "Target creature gets +1/+1 until end of turn. **That creature gets an
    additional +4/+4** until end of turn unless any player pays {2}." (Wild
    Might.) "Creatures you control get +0/+1 until end of turn. **They get an
    additional +0/+2** until end of turn unless any player pays {2}." (Rhystic
    Shield.) The pronoun names the previous pump's subject — one chosen target
    ("that creature", "it") or the set a sweep named ("they", "those
    creatures") — and the new pump is given that subject, a copy of it: the
    same ``targets`` payload, so CR 601.2c's one choice is asked once, and for
    a sweep the same noun phrase, which is the same set (CR 611.2c fixes both
    when the effects begin, in the same resolution).

    Read here, beside the plural rider whose method it shares (the ordinary
    ``_parse_gets`` with the bound subject handed in), and only after a
    ``Pump``: "an additional" is what that antecedent licenses, and without it
    "they" is a player word. The trailing toll is read too, because a rider is
    parsed outside ``parse_statement`` and the toll is the whole point of these
    two cards.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.Pump) or not isinstance(last.subject, ast.TargetSpec):
        return None
    bound = last.subject
    mark = stream.mark()
    if bound.quantifier == "target" and bound.targeted:
        named = stream.accept_word("it") or stream.accept_phrase("that", "creature")
    elif bound.quantifier in ("all", "each"):
        named = stream.accept_word("they") or stream.accept_phrase("those", "creatures")
    else:
        return None
    if not named or not stream.at_word("gets", "get"):
        stream.reset(mark)
        return None
    try:
        pump = _parse_gets(stream, bound, additional=True)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(pump, ast.Pump):
        stream.reset(mark)
        return None
    return _accept_trailing_toll(_parse_statement_body, stream, pump) or pump


def _parse_pronoun_counter_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Put a -1/-0 counter on it.`` after a sentence that chose an object.

    Jabari's Influence prints it joined by "and": "Gain control of target
    nonartifact, nonblack creature that attacked you this turn **and put a
    -1/-0 counter on it**." The counter goes on the creature the first half
    took, not on the ability's own source — and that is what the sentence did
    before this rider, because ``parse_recipient`` reads a bare "it" as the
    source on every line whose sentence names nothing else.

    Silent both ways, which is why it is a rider rather than a refusal: on a
    spell ``add_counter_to_self`` has no permanent and places nothing, and on a
    permanent it shrinks the ability's own source. Neither raises.

    Read by parsing the sentence with the ordinary counter production and then
    substituting the subject, rather than by a second copy of that production:
    "up to two", "for each …" and the doubling rider are all things it already
    reads, and a rider that re-spelled the placement would be free to disagree
    about any of them. ``quantifier == "it"`` is what says the subject was the
    bare pronoun — "this creature" and "that creature" parse to their own
    quantifiers and keep their own referents.
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None or not stream.at_word("put"):
        return None
    mark = stream.mark()
    try:
        statement = _parse_put_counter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    subject = getattr(statement, "subject", None)
    if (
        not isinstance(statement, ast.PutCounter)
        or not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "it"
    ):
        stream.reset(mark)
        return None
    # "Return target creature card from your graveyard to the battlefield. Put
    # a +1/+1 counter on **it**." (Miraculous Recovery.) A move that *creates*
    # the permanent the pronoun names hands over the bound marker instead of its
    # own target spec — the sentence in front chose a card in a *graveyard*, and
    # substituting that spec here gives the placement a graveyard-scoped noun
    # phrase for a permanent that did not exist when the choice was made. The
    # grant rider one function down has taken this branch since Dreams of the
    # Dead; this one substituted unconditionally, so the same printed shape
    # refused at "no handler reads a filter scoped to the graveyard" depending
    # only on whether the second sentence said "gains" or "put".
    #
    # See :func:`_creates_the_permanent_it_names` — and note the referent is the
    # *same* one Soul Exchange's "that creature" already names, so the lowering
    # reads the reanimation's own record and nothing new is invented for it.
    return replace(statement, subject=(
        ast.TargetSpec("that", ast.ObjectFilter(card_types=("creature",)))
        if _creates_the_permanent_it_names(steps[-1]) else target
    ))


def _creates_the_permanent_it_names(statement: ast.Statement) -> bool:
    """Whether *statement* puts a card onto the battlefield, so that a pronoun
    after it names a **permanent that did not exist** when the choice was made.

    "Return target white or black creature card from your graveyard to the
    battlefield. **That creature** gains "Cumulative upkeep {2}."" (Dreams of
    the Dead.) What the sentence before it chose is a *card in a graveyard*;
    what this one talks about is the permanent that arrived. Reusing the
    previous target spec — which every other pronoun rider does, and rightly —
    would hand the grant a graveyard-scoped noun phrase, and there is no such
    permanent to grant to.

    So the pronoun is left as the bare bound marker and the lowering points it
    at what the move *recorded*, the way every other back-reference to an
    earlier step's objects is resolved.
    """
    return (
        isinstance(statement, ast.ReturnToZone)
        and statement.from_zone is not None
        and statement.from_zone.name == "graveyard"
        and statement.to.name == "battlefield"
    )


def _parse_pronoun_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``It gains <keywords> [duration].`` after a sentence that chose a target.

    Re-uses the previous sentence's own :class:`ast.TargetSpec` as the grant's
    subject, so both instructions describe — and resolve — the same choice.
    Without this the sentence parses on its own with "it" read as the source,
    which is the trigger-remainder reading and grants the ability's *source*
    the keyword (Basri Ket +1 would make Basri indestructible, not the
    creature).
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None:
        return None
    mark = stream.mark()
    # "It gains …" / "That permanent loses …" (Soul Sear) — two spellings of
    # the same back-reference. The noun spelling is only claimed when a
    # grant/loss verb follows, so "that creature's controller …" (a different
    # referent) keeps its own reading.
    if not stream.accept_word("it"):
        if not stream.accept_word("that"):
            return None
        if not stream.accept_word("creature", "permanent", "planeswalker"):
            stream.reset(mark)
            return None
        if not stream.at_word("gains", "gain", "loses", "lose"):
            stream.reset(mark)
            return None
    # "It loses indestructible until end of turn." (Soul Sear) — the negative
    # half of the same pronoun binding: the previous sentence's target loses a
    # keyword, not the ability's source.
    if stream.at_word("loses", "lose"):
        try:
            loss = _parse_loses(stream, target)
        except GrammarError:
            stream.reset(mark)
            return None
        if not isinstance(loss, ast.LoseKeyword):
            # "It loses 2 life" would be a pronoun for a player, which this
            # binding cannot mean — leave the sentence to fail loudly.
            stream.reset(mark)
            return None
        return loss
    if not stream.at_word("gains", "gain"):
        stream.reset(mark)
        return None
    # A move that *creates* the permanent the pronoun names hands over the bound
    # marker instead of its own target spec — see
    # :func:`_creates_the_permanent_it_names`.
    subject = (
        ast.TargetSpec("that", ast.ObjectFilter(card_types=("creature",)))
        if _creates_the_permanent_it_names(steps[-1]) else target
    )
    try:
        grant = _parse_gains(stream, subject)
    except GrammarError:
        stream.reset(mark)
        return None
    # "Put target creature card from a graveyard onto the battlefield under
    # your control. It gains haste." (Liliana, Waker of the Dead's emblem.)
    # A durationless grant to a reanimated card folds into the reanimation —
    # the permanent does not exist until that step runs, so a separate grant
    # instruction would have nothing to grant to.
    if (
        isinstance(grant, ast.GainKeyword)
        and grant.duration.kind is None
        and isinstance(steps[-1], ast.PutOntoBattlefield)
    ):
        steps[-1] = replace(steps[-1], gains=steps[-1].gains + grant.keywords)
        return _RIDER_FOLDED
    return grant


def _parse_conditional_pronoun_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If <condition>, it gains <keywords> [duration].`` after a sentence that
    chose a target.

    "Target creature gains first strike until end of turn. **If it doesn't have
    rampage, that creature gains rampage 2 until end of turn.**" (Rapid Fire.)

    Its own rider rather than a branch of the sentence parser, for the reason
    :func:`_parse_pronoun_grant_rider` exists at all: the pronoun names the
    sentence *before* this one, and nothing inside a single sentence's parse can
    see back that far. Read without the binding, "that creature" is a subject
    nobody chose and the whole line refuses.

    The grant half is delegated to that function rather than re-implemented, so
    the two spellings of the pronoun, the loss half and the reanimation fold all
    stay in one place. Only the condition is read here.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    grant = _parse_pronoun_grant_rider(stream, steps)
    # `_RIDER_FOLDED` means the grant merged into the previous step, which a
    # conditional cannot do — the merge would run the grant unconditionally.
    if grant is None or grant is _RIDER_FOLDED:
        stream.reset(mark)
        return None
    return ast.Conditional(condition, grant)


def _parse_conditional_quoted_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If it doesn't have "<ability>," it gains that ability.`` after a
    sentence that chose a target.

    "{T}: Put a music counter on target creature. **If it doesn't have "At the
    beginning of your upkeep, destroy this creature unless you pay {1} for each
    music counter on it," it gains that ability.**" (Musician.)

    The quoted twin of :func:`_parse_conditional_pronoun_grant_rider`, and its
    own reader for two reasons that reader cannot absorb:

    * the condition tests a whole printed *ability* rather than a keyword, so
      the generic condition parser has nothing to read it with;
    * the arm says "that ability" — a back-reference to the sentence inside the
      condition, which no independently parsed grant could name.

    Both halves therefore come out of one production, and the result is a single
    grant carrying the condition as ``only_if_absent`` rather than a
    :class:`ast.Conditional` over a condition nothing else prints. The two are
    the same statement: the test is about the very ability being granted, and
    splitting them would be two readings of one quote that could disagree about
    which sentence was meant.
    """
    if not steps:
        return None
    target = _statement_bound_target(steps[-1])
    if target is None:
        return None
    mark = stream.mark()
    if not stream.accept_phrase("if", "it", "doesn't", "have"):
        return None
    if not stream.at_kind(QUOTE):
        stream.reset(mark)
        return None
    try:
        abilities, self_name = _parse_quoted_abilities(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("it", "gains", "that", "ability"):
        stream.reset(mark)
        return None
    return ast.GainAbilityText(
        target, abilities, self_name=self_name, only_if_absent=True
    )


def _returned_permanent_step(statement: ast.Statement) -> ast.ReturnToZone | None:
    """The battlefield return a following "It loses …" sentence is about.

    Walks the branch a preceding rider folded, because that is where the return
    ends up: "If they don't, return this card … as a non-Aura enchantment. It
    loses …" (Takklemaggot) prints the second sentence outside the conditional
    and means it inside.
    """
    if isinstance(statement, ast.Conditional):
        for branch in (statement.otherwise, statement.then):
            if branch is None:
                continue
            found = _returned_permanent_step(branch)
            if found is not None:
                return found
        return None
    if isinstance(statement, ast.ReturnToZone) and statement.to.name == "battlefield":
        return statement
    return None


def _replace_returned_permanent_step(
    statement: ast.Statement, updated: ast.ReturnToZone
) -> ast.Statement:
    """*statement* with its battlefield return swapped for *updated*."""
    if isinstance(statement, ast.Conditional):
        for field_name in ("otherwise", "then"):
            branch = getattr(statement, field_name)
            if branch is not None and _returned_permanent_step(branch) is not None:
                return replace(statement, **{
                    field_name: _replace_returned_permanent_step(branch, updated)
                })
        return statement
    return updated


def _attach_returned_text_change(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold ``It loses "A" [and gains "B"].`` into the return before it.

    "…return this card to the battlefield under your control as a non-Aura
    enchantment. **It loses "enchant creature" and gains "…"**."
    (Takklemaggot.) CR 613.1f layer 6 on the permanent the sentence before it
    created — and that permanent is a new object (CR 400.7), so no reference
    reaches it and nothing but the move itself can be told about it. Hence a
    rider onto the move rather than a step of its own, the same shape every
    other fold on this page has.

    Only quoted *text* is read here. "It loses flying" is a keyword loss with a
    reader of its own (:func:`_parse_pronoun_grant_rider`), and claiming it here
    would give one sentence two readings.
    """
    if not steps:
        return False
    target = _returned_permanent_step(steps[-1])
    if target is None:
        return False
    mark = stream.mark()
    if not stream.accept_word("it"):
        return False
    losing: tuple[str, ...] = ()
    gaining: tuple[str, ...] = ()
    try:
        if stream.accept_word("loses", "lose"):
            if not stream.at_kind(PT) and stream.at_kind(QUOTE):
                losing, _ = _parse_quoted_abilities(stream)
            else:
                stream.reset(mark)
                return False
            if stream.accept_word("and") and stream.accept_word("gains", "gain"):
                gaining, _ = _parse_quoted_abilities(stream)
        elif stream.accept_word("gains", "gain") and stream.at_kind(QUOTE):
            gaining, _ = _parse_quoted_abilities(stream)
        else:
            stream.reset(mark)
            return False
    except GrammarError:
        stream.reset(mark)
        return False
    steps[-1] = _replace_returned_permanent_step(
        steps[-1],
        replace(
            target,
            losing_abilities=target.losing_abilities + losing,
            gaining_abilities=target.gaining_abilities + gaining,
        ),
    )
    return True


def _attach_sacrifice_when_control_lost(
    stream: TokenStream, steps: list
) -> bool:
    """Fold "Sacrifice the creature when you lose control of this creature."
    into the battlefield entry before it (Seraph, Krovikan Vampire).

    CR 603.7's delayed triggered ability, watching a control change the sentence
    in front of it has not made yet: the permanent it is about is the one that
    entry is about to create, which is exactly why it is a rider and not a step.
    Parsed alone, "the creature" names nothing at all.

    Both printings are read: Krovikan Vampire says "Sacrifice **it**" and Seraph
    "Sacrifice **the creature**", and the pronoun and the repeated noun are one
    referent (idiom 20) — the pair ``lowering/control_changes`` and
    ``lowering/stack`` already read together. The noun is consumed against the
    card types rather than skipped, the discipline
    ``riders._attach_tap_when_control_lost`` states: a sentence naming something
    the entry never made would otherwise be read as this one.

    "…of **this** creature" is the ability's own source, and only that spelling
    is admitted. A control change about any other object is one the sweep in
    ``engine/linked_sacrifice.py`` has no record to check, so the words stay
    unconsumed and the line fails loudly.

    Marked wherever the entry sits, through a structural walk, because Seraph
    prints it *inside* a delayed ability ("…at the beginning of the next end
    step") and Krovikan Vampire does not.
    """
    if not any(_finds_battlefield_entry(step) for step in steps):
        return False
    mark = stream.mark()
    if not stream.accept_word("sacrifice"):
        stream.reset(mark)
        return False
    if not stream.accept_word("it"):
        if not stream.accept_word("the"):
            stream.reset(mark)
            return False
        noun = stream.peek_word()
        if noun is None or noun not in CARD_TYPES:
            stream.reset(mark)
            return False
        stream.advance()
    if not stream.accept_phrase("when", "you", "lose", "control", "of"):
        stream.reset(mark)
        return False
    if not _accept_self_reference(stream):
        stream.reset(mark)
        return False
    for index, step in enumerate(steps):
        steps[index] = _marks_entry_watched(step)
    return True


def _finds_battlefield_entry(node) -> bool:
    """Whether *node* contains a :class:`ast.PutOntoBattlefield`."""
    return _marks_entry_watched(node) is not node


def _marks_entry_watched(node):
    """*node* with every ``PutOntoBattlefield`` in it marked.

    A structural walk rather than a per-shape probe, for
    ``riders._marks_control_change_watched``'s reason: the entry can be a step,
    a conjunct, or the effect of a delayed ability, and a list of the shapes it
    has been seen in goes stale the way every fire-site list in this engine has.
    """
    if isinstance(node, ast.PutOntoBattlefield):
        return replace(node, sacrifice_when_control_lost=True)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changed = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if isinstance(value, tuple):
                walked = tuple(_marks_entry_watched(item) for item in value)
                if any(a is not b for a, b in zip(walked, value)):
                    changed[field.name] = walked
                continue
            walked = _marks_entry_watched(value)
            if walked is not value:
                changed[field.name] = walked
        if changed:
            return replace(node, **changed)
    return node


def _parse_exile_instead_of_leaving_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If the creature would leave the battlefield, exile it instead of
    putting it anywhere else.`` (Dreams of the Dead.)

    A pronoun rider like the grants above: "the creature" is the permanent an
    earlier sentence of the same ability put onto the battlefield, and nothing
    inside this sentence's own parse can see back that far.

    It **folds into that move** rather than becoming a step, the way the
    durationless keyword grant after a reanimation already does and for the
    same reason: the permanent does not exist until the move runs, so a
    separate step would have nothing to arm — and what it arms is not a target
    anything chose, because this ability's target is a *card* in a graveyard.
    Returns :data:`_RIDER_FOLDED` when it merges.

    **Every word of the tail is consumed literally**, and each is load-bearing:

    * "would leave the battlefield" is the whole event. Read as "would die" it
      would be a strictly *smaller* effect — a death is one of the ways a
      permanent leaves — and this clause is a drawback, so the smaller reading
      is the one that hands the player a card better than the one printed.
    * "instead of putting it anywhere else" is what says the exile replaces
      **every** destination. A production that still matched with those words
      deleted would be claiming a sentence it had not read, which is what the
      parse-coverage deletion probe reports.

    Returns None with the cursor untouched on anything else, so an ordinary
    conditional keeps its own reading.
    """
    index = next(
        (
            i for i in range(len(steps) - 1, -1, -1)
            if _creates_the_permanent_it_names(steps[i])
        ),
        None,
    )
    if index is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    # The printed noun, not a bare pronoun: the card says "the creature". Any
    # other noun is a sentence about something else and must not be read as
    # this one.
    if not stream.accept_word("the"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("would", "leave", "the", "battlefield"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "exile", "it", "instead", "of", "putting", "it", "anywhere", "else"
    ):
        stream.reset(mark)
        return None
    steps[index] = replace(steps[index], exile_on_leave=True)
    return _RIDER_FOLDED


def _accept_removed_permanents_controller(stream: TokenStream) -> bool:
    """The possessive naming the controller of the permanent the sentence in
    front of this one removed — ``that creature's controller`` or ``its
    controller`` — consumed, or False with the cursor untouched.

    **One reader, because it was two.** Transmogrify prints "that creature's
    controller" and Polymorph prints "its controller" for the same seat, and the
    reveal rider below reads both; the token rider above read only the second,
    so Ovinomancer's "That creature's controller creates a 0/1 green Sheep
    creature token" refused a phrase the module three functions down already
    knew. A fork in a *fragment* is only ever found by whoever extends it, which
    is what makes the extension the moment to collapse it.

    Neither spelling is a difference in what the card does, so normalising at
    one end would be the same card twice.
    """
    return bool(
        stream.accept_phrase("that", "creature", "'s", "controller")
        or stream.accept_phrase("its", "controller")
    )


def _parse_its_controller_creates_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Its controller creates a <token>.`` after a sentence that chose a
    target (Angelic Ascension, Secure the Scene — both after an exile), and
    ``That creature's controller creates a <token>.`` after a destroy
    (Ovinomancer).

    Both possessives name the previous sentence's chosen permanent, which is
    gone by the time the token arrives — so the token rides the controller that
    step recorded, and the lowering demands that producer. Parsed as its own
    sentence, either phrase would name nobody at all.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not _accept_removed_permanents_controller(stream):
        return None
    if not stream.at_word("creates"):
        stream.reset(mark)
        return None
    try:
        token = _parse_create_token(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    assert isinstance(token, ast.CreateToken)
    return replace(token, recipient=LAST_TARGET_CONTROLLER)


def _parse_that_controller_reveals_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``That creature's controller reveals cards from the top of their library
    until they reveal a creature card. That player puts that card onto the
    battlefield, then shuffles the rest into their library.`` (Transmogrify.)

    ``Its controller reveals cards from the top of their library until they
    reveal a creature card. The player puts that card onto the battlefield,
    then shuffles all other cards revealed this way into their library.``
    (Polymorph, behind a destroy rather than an exile.)

    The same shape as the "its controller creates a token" rider beside it, and
    for the same reason: "that creature" names the permanent the previous
    sentence removed, which is gone by the time this runs, so the library read
    rides the controller that step recorded. Parsed as its own sentence it names
    nobody.

    All three sentences are consumed here. They describe one procedure over one
    revealed pile — "that card" is what the reveal stopped on and "the rest" is
    exactly what it turned over first — so parsed apart the last two would
    dangle referents nothing binds.

    **Three phrases have two printed spellings each**, and each pair is read
    rather than normalized at one end: the possessive that names the removed
    permanent (``_accept_removed_permanents_controller``), the article in front
    of the seat
    ("that player" / "the player") and the words for the cards the reveal
    turned over first ("the rest" / "all other cards revealed this way"). None
    of the three is a difference in what the card does — Polymorph and
    Transmogrify are the same procedure — so a second production for them
    would be the same card twice.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not _accept_removed_permanents_controller(stream):
        return None
    if not stream.accept_phrase(
        "reveals", "cards", "from", "the", "top", "of", "their", "library",
        "until", "they", "reveal",
    ):
        stream.reset(mark)
        return None
    try:
        stream.accept_word("a", "an")
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not filt.is_card:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # Every word of the destination and of what happens to the rest. A card
    # that milled the pile instead of shuffling it back is a different card, and
    # the difference does not show until this sentence.
    if not (
        stream.accept_phrase(
            "that", "player", "puts", "that", "card", "onto", "the", "battlefield",
        )
        or stream.accept_phrase(
            "the", "player", "puts", "that", "card", "onto", "the", "battlefield",
        )
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_word("then"):
        stream.reset(mark)
        return None
    if not stream.accept_word("shuffles"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_phrase("the", "rest")
        or stream.accept_phrase("all", "other", "cards", "revealed", "this", "way")
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("into", "their", "library"):
        stream.reset(mark)
        return None
    return ast.RevealUntil(LAST_TARGET_CONTROLLER, filt)
