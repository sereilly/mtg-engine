"""Changing what a spell or an ability on the stack targets (CR 115.7).

Three printed arrangements of the same two restrictions, all building one node.
What they re-aim is an object that has **already chosen** its targets, so each
sentence has to say which objects may be re-aimed and what the one target has to
be — and the picker asks both before the ability is activated at all, which is
why neither half is a ``Condition`` about the board:

    _parse_change_target         "Change the target of target spell with a
                                 single target [if that target is <player>]."
                                 (Reflecting Mirror, Deflection, Divert)
    _accept_targets_only         "…target spell [or ability] that targets only
                                 a player." (Rebound, Silver Wyvern) — the two
                                 restrictions as a relative clause, read by the
                                 production above and by nothing else
    _parse_conditional_retarget  "If target spell has only one target and that
                                 target is a creature, change that spell's
                                 target to another creature." (Meddle) — the
                                 two restrictions as a condition

Split out of ``effects/stack.py`` at Urza's Destiny's Phase 0, when that module
sat **fourteen** lines under the thousand-line guard with a parallel wave about
to land productions in it — the pre-split SET_PLAYBOOK.md asks for rather than a
brief. The seam there was recorded by *omission*: that module's docstring
enumerates its subjects — countering, the two copy templates (CR 707.10), the
modal head (CR 700.2), the closed list of unpaid-cost penalties, the activation
restrictions — and has never named a retarget among them.

The line under it is the CR's own. Everything left in ``stack`` acts on a stack
object as a whole: it counters one, copies one, announces its modes, or prices
the choice not to pay a cost. A retarget leaves the object exactly where it is,
resolving exactly as printed, and changes one of the choices made when it was
announced (CR 601.2c).

The two halves share no name in either direction, checked at the split:
``readers.accept_source_reference_spec`` travelled with these productions
because nothing left behind reads it, and ``parse_target_spec`` and
``parse_player_ref`` are one layer down rather than siblings, so both modules
keep them. There is no import between the two in either direction.

A **parse-only family**, like ``search``, ``reveal``, ``text_changes`` and
``damage_locks`` before it. All three arrangements build one ``ast.ChangeTarget``
— which is what makes them three arrangements rather than three effects — and it
lives in ``ast/stack.py`` beside the counters and the copies and lowers in
``lowering/stack.py`` beside theirs, both a long way from the guard. A
near-empty ``lowering/retargeting.py`` would buy back the symmetry and cost the
thing symmetry is for.
"""

from .. import ast
from ..readers import accept_source_reference_spec
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream


#: The nouns a "that targets only <noun>" clause may name, and what each means
#: to the picker's ``current_target_type``. Closed, for
#: ``_CHANGE_TARGET_NEW_TARGETS``' reason one module over: a noun consumed here
#: and unknown to the gate is a retarget offered every spell on the stack.
#:
#: ``"source"`` is not one of them because it is not a printed noun: "that
#: targets only **this creature**" (Silver Wyvern) names an *identity*, and the
#: word after "this" varies with the card's own type. It is read by
#: ``accept_source_reference_spec`` below and reaches the gate under that name.
_TARGETS_ONLY_NOUNS: frozenset[str] = frozenset({"player", "creature"})


def _accept_targets_only(stream: TokenStream) -> "tuple[str, bool] | None":
    """``target spell [or ability] that targets only <a noun | this creature>``
    — consumed whole as ``(what its one target has to be, whether an ability
    counts)``, or None with the cursor untouched.

    (Rebound: "…target spell that targets only a player.") CR 115.9a's count
    and the shape of the one target, printed as a single relative clause where
    Reflecting Mirror prints them as "with a single target" plus "if that target
    is you" and Meddle prints them as a condition. Three spellings of two
    restrictions, so this produces the very node those two already produce.

    Read here rather than by the shared noun parser, which cannot: its "that
    targets <noun phrase>" postmodifier parses an **object** filter, "only a
    player" is not one, and its failure unwinds the whole target spec — the
    line refused at "expected the spell whose target to change" while naming a
    production that works.

    The noun is checked rather than merely consumed, for the reason
    ``_attach_new_target_bound`` checks its own: a restriction the gate cannot
    ask about would be read and then dropped, and a dropped restriction here is
    an ability that re-aims spells the card never let it touch.
    """
    mark = stream.mark()
    if not stream.accept_phrase("target", "spell"):
        stream.reset(mark)
        return None
    # "target spell **or ability**" (Silver Wyvern). CR 115.7a re-aims any
    # object on the stack that chose targets, and CR 113.7a says an ability is
    # not a spell — so this is a union across two kinds of stack object rather
    # than a wider description of one. Carried as a flag for
    # ``ReturnToZone.also_stack``'s reason: no ``ObjectFilter`` expresses it,
    # because an ability has no card to ask any of the filter's questions of.
    also_ability = bool(stream.accept_phrase("or", "ability"))
    if not stream.accept_phrase("that", "targets", "only"):
        stream.reset(mark)
        return None
    # "…that targets only **this creature**" (Silver Wyvern). Not a noun in the
    # table below: the phrase names the ability's own source, which the gate
    # answers by comparing ``permanent_id`` rather than by asking what type the
    # target is. Read through the grammar's one source reader so a card
    # printing "this permanent" or its own name is the same reference.
    #
    # The **spec** form of that reader, not the predicate, because a bare "it"
    # is a pronoun (``accept_source_reference_spec``'s own note) and nothing
    # earlier in this sentence is an object it could bind to. "This <noun>" and
    # the card's own name keep ``"this"``; the pronoun is refused rather than
    # read as the source.
    probe = stream.mark()
    reference = accept_source_reference_spec(stream)
    if reference is not None and reference.quantifier == "this":
        return "source", also_ability
    stream.reset(probe)
    stream.accept_word("a", "an")
    noun = stream.peek_word()
    if noun not in _TARGETS_ONLY_NOUNS:
        stream.reset(mark)
        return None
    stream.advance()
    return noun, also_ability


def _parse_change_target(stream: TokenStream) -> "ast.ChangeTarget | None":
    """``Change the target of target spell with a single target [if that target
    is <player>].`` (Reflecting Mirror; Deflection and Divert print the first
    sentence without the "if".)

    CR 115.7a. Returns None **without consuming** when the sentence is one of
    the other two "Change the …" templates — "change the text of" (Magical
    Hack) and "change the base power and toughness of" (Halfdane) open on the
    same two words — so those keep the refusals they have today.

    Two things are required past the verb, and both are the full-consumption
    invariant rather than fussiness:

    * the printed head noun must be **spell**. A bare "spell" is a generic noun
      that leaves no mark on the filter at all (only a *typed* phrase — "target
      instant or sorcery spell" — records ``zone="stack"``), so without this
      guard the word could be deleted with no change to the parse and "target
      permanent with a single target" would reach the same lowering. That is
      the dropped-rider shape, arriving through a word that describes the
      *zone* rather than a rider.
    * "if that target is <player>" is read here rather than left to the
      sentence loop's trailing-``if`` fold, because it is not a condition about
      the board: it asks what the *other* object announced, which no
      ``Condition`` in this grammar can describe, and the picker has to be able
      to ask it before the ability is activated at all.
    """
    mark = stream.mark()
    if not stream.accept_phrase("change", "the", "target", "of"):
        stream.reset(mark)
        return None
    if not (stream.at_word("target") and stream.peek_word(1) == "spell"):
        stream.reset(mark)
        return None
    # "…target spell **that targets only a player**." (Rebound.) The clause
    # spelling of the two restrictions the branch below reads as a noun phrase
    # plus an "if"; the spec is built here for ``_parse_conditional_retarget``'s
    # reason — the count is what the words say and there is nothing else in the
    # phrase for the shared parser to find.
    only = _accept_targets_only(stream)
    if only is not None:
        current_type, also_ability = only
        return ast.ChangeTarget(
            ast.TargetSpec(
                "target",
                ast.ObjectFilter(target_count=1, zone="stack"),
                targeted=True,
            ),
            current_target_type=current_type,
            also_ability=also_ability,
        )
    subject = parse_target_spec(stream)
    if subject is None:
        raise stream.error("expected the spell whose target to change")
    current = None
    if stream.accept_phrase("if", "that", "target", "is"):
        current = parse_player_ref(stream)
        if current is None:
            raise stream.error("expected who that target has to be")
    return ast.ChangeTarget(subject, current_target=current)


def _parse_conditional_retarget(stream: TokenStream) -> "ast.ChangeTarget | None":
    """``If target spell has only one target and that target is a <noun>,
    change that spell's target to another <noun>.`` (Meddle.)

    The same effect as :func:`_parse_change_target` above with the restrictions
    arranged as a condition instead of as a noun phrase, so it produces the same
    node: CR 115.9a's count, the shape the current target has to be, and the
    bound on the new one. Written as its own production rather than folded into
    the sentence loop's trailing-``if``, for the reason that reader gives about
    "if that target is you" — neither half is a question about the board, and
    the picker has to ask both before the spell is cast at all.

    **The two nouns must match.** "…that target is a creature, change that
    spell's target to another **creature**" is one restriction stated twice, and
    a card naming two different nouns would be a retarget whose new target the
    old one's legality says nothing about — refused rather than read as the
    first, which is the direction that re-aims a spell somewhere it may not go.

    Returns None with the cursor untouched for every other sentence opening
    "if", so the ordinary condition reader keeps its own.
    """
    mark = stream.mark()
    if not stream.accept_phrase("if", "target", "spell", "has", "only", "one", "target"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "that", "target", "is", "a"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "change", "that", "spell", "'s", "target", "to", "another"
    ):
        stream.reset(mark)
        return None
    if stream.peek_word() != noun:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.ChangeTarget(
        # The same spec "target spell with a single target" parses to one
        # production up: CR 115.9a's count and nothing else. The zone is not on
        # the filter there either — what says "spell" is the picker the kind
        # table derives, and setting it here would be a narrowing the retarget
        # lowering has never been asked to honour.
        ast.TargetSpec(
            "target", ast.ObjectFilter(target_count=1), targeted=True,
        ),
        current_target_type=noun,
        new_target=noun,
    )
