"""Riders: a sentence that modifies the one before it.

A rider is not a step of its own. "If you do, …" branches the decision the
previous sentence offered; "Its controller creates a token" names the permanent
that sentence exiled; "…and it can't be regenerated" narrows the damage it
dealt. Every one of them reads a referent the previous step bound, which is why
they are read by the sentence loop rather than by ``parse_statement``: on their
own they name nothing.

Split out of ``parser.py`` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut — this is the whole of what "a sentence about the
previous sentence" means, and the loop that drives them stays behind in
``parser.py`` with the line-level productions it belongs to.

**Those two paragraphs describe the family, and this file is now a third of
it.** The three verbs in the first one are three questions, and each has its
own module:

    control_flow  *branches* — which arm of the sentence before it a clause
                  is ("If you do, …", "Otherwise, …", "Each opponent who
                  can't …"); and beside it since Invasion's Phase 0,
                  ``conditional_instead``, the one branch whose arm is the
                  sentence before it over again ("If <condition>, … instead")
    pronouns      *names* — what a pronoun or a possessive points back at
                  ("It gains …", "Its controller creates …")
    riders        *narrows* — a flag, a bound or a width folded onto the node
                  the sentence before it parsed to

and the loop that drives all three left ``parser`` for ``sequences``, whose
docstring quotes the sentence above and says what became of it.

So what is here is the third question only, and the test is mechanical: every
reader below either rewrites a step already in ``steps`` or contributes
nothing, and **none appends one**. A clause that needs a step of its own is
either an arm (``control_flow``) or a sentence with a bound subject
(``pronouns``). The first two splits were taken at the thousand-line guard and
each left stragglers of its own subject behind; Nemesis' Phase 0 sent them
after it rather than cutting a fourth module — the two "<possessive>
controller …" riders were the only readers of
``rebinding.statement_bound_target`` left in this file, and the two that went
to ``control_flow`` were the only ones that built an arm or read a "couldn't".
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import PT, SELF
from .nouns import parse_object_filter
from .effects import parse_source_damage_lock
from .delayed import contains_flip, parse_flip_stakes_sentence
from .phrases import _accept_number
from .statements import parse_statement
from .stream import TokenStream
from .bounds import accept_superlative
from .vocabulary import CARD_TYPES
from .vocabulary import singular as _singular


def _superlative_of(step: ast.Statement):
    """The superlative the sentence *step* picks by, or None.

    One reader for both verbs, because the tie-break sentence behind them is
    word-for-word the same and the guard it needs is "was the sentence in front
    of me the pick this describes?". A second copy per family is two answers to
    that question.
    """
    spec = None
    if isinstance(step, ast.Destroy):
        spec = step.subject
    elif isinstance(step, ast.DealDamage) and len(step.recipients) == 1:
        spec = step.recipients[0]
    if isinstance(spec, ast.TargetSpec):
        return spec.filter
    return None


def _attach_superlative_tie_break(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``If two or more <type>s are tied for <extreme> <characteristic>, you
    choose one of them.`` (Purging Scythe, Drop of Honey.)

    CR 608.2d's choice, and it contributes **no step**: the sentence in front
    of it already lowers to a ``choose_permanent`` carrying ``only_on_tie``, so
    what these words say is exactly what that instruction does. A step of its
    own would be a second prompt for one decision.

    That is the whole reason it is a rider rather than a sentence. Read alone it
    names nothing — "them" is a set only the previous sentence describes — which
    is this module's own definition of the word.

    **Guarded on the sentence in front of it, and on three of its words.** The
    previous step must be a pick by *this* superlative, the printed noun must be
    the one that pick describes, and the chooser must be "you" — the seat the
    pick's prompt is armed on. A printing whose halves disagreed would otherwise
    be admitted with the disagreement resolved in favour of whichever sentence
    was read first, which is the ``_parse_pay_or_sacrifice_greatest_mana_value``
    check made across two sentences instead of inside one.

    Refuses without consuming, so an ordinary "If two or more …" conditional
    keeps its own reading.
    """
    if not steps:
        return False
    mark = stream.mark()
    if not stream.accept_phrase("if", "two", "or", "more"):
        stream.reset(mark)
        return False
    noun = stream.peek_word()
    if noun is None or _singular(noun) not in CARD_TYPES:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_phrase("are", "tied", "for"):
        stream.reset(mark)
        return False
    superlative = accept_superlative(stream, article=False)
    if superlative is None:
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    # "**you** choose one of them" — the ability's controller, which is the seat
    # the pick's prompt is armed on. Any other chooser names a player the
    # instruction in front of this one was not built for, and consuming the
    # words would silently give the pick to the wrong seat.
    if not stream.accept_phrase("you", "choose", "one", "of", "them"):
        stream.reset(mark)
        return False
    filt = _superlative_of(steps[-1])
    if (
        filt is None
        or filt.superlative != superlative
        or filt.card_types != (_singular(noun),)
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(".")
    return True


def _parse_exile_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``If that spell would be put into your graveyard, exile it instead.``
    after a cast-permission sentence (Chandra, Flame's Catalyst's −2), and
    ``If a spell cast this way would be put into a graveyard, exile it
    instead.`` after a blanket one (Bösium Strip).

    Folded onto the permission rather than parsed as a step, because it is a
    property of the cast the permission allows — the engine stamps it onto the
    stack object at cast time — and as a standalone sentence "that spell"
    would dangle with nothing binding it.

    **Both subjects, because both permissions exist.** A grant naming one card
    says "that spell"; a grant covering a class of them says "a spell cast this
    way", and the possessive goes with it ("your graveyard" becomes "a
    graveyard", CR 404.1 sending each card to its owner's). The two phrasings
    are one rider and reach one field, so the wording a card happens to print
    is not a difference the engine has.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.CastPermission) or last.what not in (
        "target_card", "spells_from_zone"
    ):
        return False
    mark = stream.mark()
    if not (
        stream.accept_phrase(
            "if", "that", "spell", "would", "be", "put", "into", "your",
            "graveyard",
        )
        or stream.accept_phrase(
            "if", "a", "spell", "cast", "this", "way", "would", "be", "put",
            "into", "a", "graveyard",
        )
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("exile", "it", "instead"):
        stream.reset(mark)
        return False
    steps[-1] = replace(last, exile_instead=True)
    return True


def _attach_spend_only(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "Spend this mana only to …" into the mana production before it.

    A rider and not a step: the sentence adds nothing to the game, it says what
    the *previous* sentence's mana may pay for (CR 106.6). Parsed as its own
    step it would be an effect nothing performs, and the mana would go into the
    unrestricted pool with the restriction reported as understood.

    Which restrictions exist is `engine/restricted_mana.py`'s question, asked
    through its own matcher over the sentence's printed text — the delegation
    round 85 established for a registry-claimed sentence, and for its reason: a
    copy of the phrase here would be free to drift from the predicate that
    enforces it, and mana spent more freely than the card allows is the
    direction that drift goes.
    """
    from ..restricted_mana import mana_restriction_for

    last = steps[-1] if steps else None
    # "At the beginning of your upkeep, **you may** add {C}{C}. This mana can't
    # be spent to cast spells." (Thran Turbine.) The printed offer puts a
    # ``May`` between the rider and the mana it restricts, exactly as a printed
    # condition puts a ``Conditional`` between the no-regeneration rider and
    # its destroy — and through the wrapper for that rider's reason: the offer
    # is folded on by the sentence layer *after* the mana production has
    # finished, so by the time this runs the ``AddMana`` is one level down.
    #
    # Only through a wrapper this can name, and only where the offer's own
    # action is the mana: an offer with a cost or a branch is a different
    # sentence, and reading the rider onto it would restrict mana some other
    # step made.
    inside_may = (
        isinstance(last, ast.May)
        and last.cost is None
        and last.then is None
        and last.otherwise is None
        and last.reflexive is None
        and isinstance(last.action, ast.AddMana)
    )
    # "Add X mana of any one color, **where X is 1 plus the exiled creature's
    # mana value**. Spend this mana only to cast creature spells." (Food Chain,
    # and Metamorphosis one cost-record over.) A second wrapper the sentence
    # layer folds on before this rider runs, for the same reason ``May`` is one:
    # the where-clause is read by the mana production itself and returned around
    # it, so by the time the rider arrives the ``AddMana`` is a level down.
    #
    # Unwrapped and rewrapped rather than given a ``spend_only`` of its own: the
    # restriction is on the mana, and a key on the binder would be a second
    # place to look for it. Without this the whole sentence refused — "expected
    # a subject" on a rider nothing could attach — which is why the pair was a
    # card hook for as long as only one card printed it.
    inside_where_x = (
        isinstance(last, ast.WhereX) and isinstance(last.statement, ast.AddMana)
    )
    if (
        not isinstance(last, ast.AddMana)
        and not inside_may
        and not inside_where_x
    ):
        return False
    mark = stream.mark()
    start = stream.pos
    while not stream.exhausted and not stream.at_punct(".", ";"):
        stream.advance()
    sentence = stream.text_between(start, stream.pos)
    restriction = mana_restriction_for(sentence)
    if restriction is None:
        stream.reset(mark)
        return False
    if inside_may:
        steps[-1] = dataclasses.replace(
            last,
            action=dataclasses.replace(last.action, spend_only=restriction.key),
        )
    elif inside_where_x:
        steps[-1] = dataclasses.replace(
            last,
            statement=dataclasses.replace(last.statement, spend_only=restriction.key),
        )
    else:
        steps[-1] = dataclasses.replace(last, spend_only=restriction.key)
    return True


def _attach_unpaid_penalty(statement: ast.Statement, penalty: str) -> ast.Statement:
    """Fold "If that player doesn't, …" into the "unless … pays" it belongs to.

    Raises when there is no such effect to attach to. A penalty for declining a
    cost that was never offered is not something the grammar can place, and
    consuming the sentence anyway is precisely the dropped-rider bug the
    full-consumption invariant exists to prevent.
    """
    if isinstance(statement, ast.CounterSpell) and statement.unless_pays is not None:
        return ast.CounterSpell(statement.subject, statement.unless_pays, penalty)
    raise GrammarError("an unpaid-cost penalty with no cost to decline")


def _attach_destroyed_this_way(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If this creature is destroyed this way, it deals N damage to you."
    into the destroy-unless-pay before it (Cosmic Horror).

    A rider rather than a step, and for the reason the whole family exists: on
    its own the sentence names nothing. "Destroyed **this way**" is a question
    about what the previous sentence did — a regenerated or indestructible
    creature was not destroyed and takes no damage (CR 701.8c) — and the only
    thing that can answer it is whatever performed the destruction.

    Attaches only to a node that can carry it. A card printing this after
    something else is saying something the grammar cannot place, and consuming
    the sentence anyway is the dropped-rider bug the full-consumption invariant
    exists to prevent — so the near-miss rewinds and the line fails loudly.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.DestroyUnlessPay):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("if", "this"):
        stream.reset(mark)
        return False
    # The noun repeats the subject's own type and carries nothing.
    if stream.peek_word() is None:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_phrase("is", "destroyed", "this", "way"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("it", "deals"):
        stream.reset(mark)
        return False
    # `parse_amount`, not the number-word table: the damage is printed as a
    # digit ("7"), which is a number *token* and not a word.
    amount = parse_amount(stream)
    if not isinstance(amount, ast.Fixed) or not stream.accept_phrase(
        "damage", "to", "you"
    ):
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, damage_if_destroyed=amount.value)
    return True


def _attach_no_regeneration(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "A creature destroyed this way can't be regenerated." into the
    destroy the sentence before it performed (Soul Rend).

    CR 701.19c's rider, which ``_parse_destroy`` already reads when it trails
    the verb directly ("Destroy target creature. It can't be regenerated.").
    Soul Rend prints a **condition** between them — "Destroy target creature
    **if it's white**" — and the sentence layer folds that into a
    ``Conditional`` *after* the destroy production has finished, so by the time
    the rider is printed there is a wrapper in the way and the destroy
    production's own probe has long since rewound.

    So this reaches through the wrapper, and only through one it can name.
    The alternative is what Soul Rend had: the whole line refuses, a
    ``spell_pattern`` whitelist marker claims the card anyway, and it resolves
    doing nothing but drawing the cantrip it also prints.

    The same reader the destroy production uses
    (``_accept_destroyed_this_way_no_regen``), so the two spellings of the
    sentence stay one rule — a second copy here is the two-readings shape this
    grammar keeps removing.
    """
    from .effects.destruction import _accept_destroyed_this_way_no_regen

    last = steps[-1] if steps else None
    if last is None:
        return False
    mark = stream.mark()
    if not _accept_destroyed_this_way_no_regen(stream):
        stream.reset(mark)
        return False
    folded = _with_no_regeneration(last)
    if folded is None:
        # Nothing here destroys anything, so the sentence says something this
        # cannot place — rewound rather than consumed, which is the
        # full-consumption invariant refusing the line loudly instead of
        # dropping a rider.
        stream.reset(mark)
        return False
    steps[-1] = folded
    return True


def _with_no_regeneration(statement: ast.Statement) -> "ast.Statement | None":
    """*statement* with its destruction marked unregenerable, or None.

    Reaches into a ``Conditional``'s arms because that is the only wrapper a
    printed card puts between the verb and this rider — "Destroy target
    creature **if it's white**" — and into both of them, because a card
    printing an "otherwise, destroy …" arm means the rider about either.
    Anything else answers None and the caller rewinds.
    """
    if isinstance(statement, ast.Destroy):
        return dataclasses.replace(statement, no_regen=True)
    if isinstance(statement, ast.OneOf):
        # "Destroy all green creatures **or** all white creatures. They can't
        # be regenerated." (Reign of Terror.) The rider is printed once and is
        # about whichever half the player takes, so it is folded into *every*
        # option that can carry it rather than into the last one parsed — a
        # mode left unmarked would let the creatures it destroys regenerate,
        # which is the half of the card nothing would report.
        folded = tuple(
            _with_no_regeneration(option) or option for option in statement.options
        )
        if folded == statement.options:
            # No option destroys anything, so the rider names nothing here —
            # None rather than a rewrite, and the caller rewinds.
            return None
        return dataclasses.replace(statement, options=folded)
    if isinstance(statement, ast.WhereX):
        # "Destroy up to X target nonblack creatures, **where X is the number of
        # verse counters on this enchantment**. They can't be regenerated."
        # (Vile Requiem.) A second wrapper a printed card puts between the verb
        # and this rider, and the same argument as the conditional below it: the
        # where-clause is folded on by the sentence layer *after* the destroy
        # production has finished, so by the time the rider is read the destroy
        # is one level down and the production's own probe has long since
        # rewound.
        #
        # The card without the where-clause already worked ("Destroy up to two
        # target nonblack creatures. They can't be regenerated."), which is what
        # makes the omission invisible: nothing about the rider changed, only
        # what was printed in front of it.
        inner = _with_no_regeneration(statement.statement)
        if inner is None:
            return None
        return dataclasses.replace(statement, statement=inner)
    if isinstance(statement, ast.Conditional):
        then = _with_no_regeneration(statement.then)
        otherwise = (
            _with_no_regeneration(statement.otherwise)
            if statement.otherwise is not None else None
        )
        if then is None and otherwise is None:
            return None
        return dataclasses.replace(
            statement,
            then=then if then is not None else statement.then,
            otherwise=(
                otherwise if otherwise is not None else statement.otherwise
            ),
        )
    return None


def _attach_tap_when_control_lost(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "When you lose control of the creature, tap it." into the
    :class:`~engine.grammar.ast.GainControl` before it (Ray of Command; Magus of
    the Unseen prints "…of the artifact").

    CR 603.7: a delayed triggered ability created by the resolution, watching
    the very control change the sentence in front of it made. A rider rather
    than a step for the reason every rider here is one — on its own it names no
    object: "the creature" is the one the previous sentence took, and parsed
    alone the pronoun would dangle.

    The repeated noun is **consumed against the card types**, not skipped. A
    sentence naming something the control change never touched would otherwise
    be read as this one and arm a trigger on the wrong object; the closed set is
    what makes that fail loudly instead.
    """
    # The **control change**, wherever in the effect it sits — not `steps[-1]`.
    # Both cards print a sentence between the two ("That creature gains haste
    # until end of turn"), and the first sentence is itself a conjunction, so
    # the change is nested one level down. A rider that read only the last
    # top-level step refused both cards that print it.
    if not any(_finds_gain_control(step) for step in steps):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("when", "you", "lose", "control", "of", "the"):
        stream.reset(mark)
        return False
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        stream.reset(mark)
        return False
    stream.advance()
    stream.accept_punct(",")
    if not stream.accept_phrase("tap", "it"):
        stream.reset(mark)
        return False
    for index, step in enumerate(steps):
        rewritten = _marks_control_change_watched(step)
        if rewritten is not step:
            steps[index] = rewritten
    return True


def _finds_gain_control(node) -> bool:
    """Whether *node* contains a :class:`~engine.grammar.ast.GainControl`."""
    return _marks_control_change_watched(node) is not node


def _marks_control_change_watched(node):
    """*node* with every ``GainControl`` in it marked ``tap_when_lost``.

    A structural walk rather than a per-shape probe, for the reason
    ``rebinding._walk_specs`` is one: the change can be a step, a conjunct or a
    branch, and a list of the shapes it has been seen in goes stale the way
    every fire-site list in this engine has.
    """
    if isinstance(node, ast.GainControl):
        return dataclasses.replace(node, tap_when_lost=True)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rewritten
            for field in dataclasses.fields(node)
            for rewritten in (_marks_control_change_watched(getattr(node, field.name)),)
            if rewritten is not getattr(node, field.name)
        }
        return dataclasses.replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_marks_control_change_watched(item) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def _attach_exchanged_this_way(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If those permanents are exchanged this way, destroy all Auras
    attached to them." into the :class:`~engine.grammar.ast.ExchangeControl`
    before it (Gauntlets of Chaos).

    The same argument as ``_attach_destroyed_this_way`` beside it: "exchanged
    **this way**" is a question about what the previous sentence did, and
    "them" names the two permanents it named. Parsed as its own step the
    sentence would have no permanents at all and would destroy every Aura on
    the board — which is exactly the sweep-lost-its-narrowing shape, so the
    near-miss rewinds and the line refuses rather than being consumed.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ExchangeControl):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "those", "permanents", "are", "exchanged", "this", "way"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "destroy", "all", "auras", "attached", "to", "them"
    ):
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, destroy_attached_auras=True)
    return True


def _attach_source_damage_lock(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If <the source> would deal damage to a creature, that damage can't
    be prevented or dealt instead to another permanent or player." into the
    damage sentence before it (Lava Burst).

    A rider rather than a step: the sentence deals no damage and destroys
    nothing, it says which effects may modify the damage the sentence in front
    of it deals. Parsed as a step it would name no event at all.

    Whippoorwill prints the *other* sentence about the same two registries —
    "Damage that would be dealt to that creature this turn can't be …" — and
    that one is a step, because it arms a marker on a creature that outlives the
    resolution. Keeping them apart is the whole reason this is not the same
    production: read as Whippoorwill's, Lava Burst would lock every later
    source's damage to the same creature for the turn.
    """
    if not steps:
        return False
    mark = stream.mark()
    if not parse_source_damage_lock(stream):
        return False
    try:
        steps[-1] = _attach_riders(
            steps[-1], ast.DamageRiders(unpreventable_to_creature=True)
        )
    except GrammarError:
        stream.reset(mark)
        return False
    return True


def _attach_riders(statement: ast.Statement, riders: ast.DamageRiders) -> ast.Statement:
    """Fold damage riders into the most recent DealDamage of *statement*."""
    if isinstance(statement, ast.DealDamage):
        merged = ast.DamageRiders(
            no_regen=statement.riders.no_regen or riders.no_regen,
            exile_if_dies=statement.riders.exile_if_dies or riders.exile_if_dies,
            divided=statement.riders.divided,
            divided_evenly=statement.riders.divided_evenly,
            rounding=statement.riders.rounding,
            unpreventable_to_creature=(
                statement.riders.unpreventable_to_creature
                or riders.unpreventable_to_creature
            ),
        )
        return ast.DealDamage(
            statement.source, statement.amount, statement.recipients, merged, statement.chooser
        )
    if isinstance(statement, ast.Sequence) and statement.steps:
        steps = list(statement.steps)
        steps[-1] = _attach_riders(steps[-1], riders)
        return ast.Sequence(tuple(steps))
    if isinstance(statement, ast.Conjunction) and statement.effects:
        effects = list(statement.effects)
        effects[0] = _attach_riders(effects[0], riders)
        return ast.Conjunction(tuple(effects))
    raise GrammarError("damage rider with no damage effect to attach to")


# What "The new target must be a <noun>." may bound the choice to. A closed set
# for the reason every other table in this grammar is closed: the sentence is
# not decoration, it is the *only* thing narrowing a choice made at resolution,
# and a noun nothing offers would be consumed here and then ignored there —
# a retarget free to aim at anything the spell could originally have chosen.
#: "creature" joined it with Silver Wyvern. Both halves behind the word were
#: already there — ``_CHANGE_TARGET_NEW_TARGETS`` has admitted it since Meddle
#: and ``_legal_new_targets`` forces the enumeration to creatures for it — so
#: what the frozenset was withholding was the printed sentence, not the
#: behaviour behind it.
_NEW_TARGET_NOUNS = frozenset({"player", "creature"})


def _attach_new_target_bound(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "The new target must be a player." into the retarget before it.

    (Reflecting Mirror.) A rider rather than a step, and a rider rather than a
    field the production reads for itself: it is a whole printed sentence about
    the sentence in front of it, exactly like the counter cap below — the
    previous sentence chose the spell, this one bounds what may replace what
    that spell chose.

    The noun is checked against ``_NEW_TARGET_NOUNS``, not merely consumed. A
    bound the resolution cannot offer has to leave the line refused, because
    consuming it would admit the card with the sentence dropped.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ChangeTarget):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("the", "new", "target", "must", "be"):
        stream.reset(mark)
        return False
    stream.accept_word("a", "an")
    noun = stream.peek_word()
    if noun not in _NEW_TARGET_NOUNS:
        stream.reset(mark)
        return False
    stream.advance()
    steps[-1] = dataclasses.replace(last, new_target=noun)
    return True


def _offered_target_change(step: ast.Statement) -> "ast.ChangeEventTargets | None":
    """The "change the target or targets" *step* offers, or None.

    One guard for the two riders below, because both are sentences about the
    same thing — the change the sentence in front of them offered — and the
    question each has to ask before consuming a word is "was that sentence the
    offer this describes?".
    """
    if isinstance(step, ast.May) and isinstance(step.action, ast.ChangeEventTargets):
        return step.action
    return None


def _attach_tied_reveals_unchanged(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``If two or more cards are tied for greatest, the target or targets
    remain unchanged.`` (Psychic Battle.)

    It contributes **no step and no flag**, for
    :func:`_attach_superlative_tie_break`'s reason one screen up: the offer in
    front of it is made to "the player who reveals the card with the greatest
    mana value", a described seat that is *strict* by construction (a tie names
    nobody — ``handlers/control_flow._revealed_mana_value_leader``), and an
    offer made to nobody changes nothing. So what these words say is exactly
    what that offer already does.

    **Guarded on both halves of the sentence in front of it**: the offer must
    be to that described seat — the only one a "tied for greatest" among
    revealed *cards* can be about — and what it offers must be the change of
    targets this sentence says does not happen. Refuses without consuming, so
    the creature tie-break and the life-total draw keep their own "if two or
    more".
    """
    last = steps[-1] if steps else None
    if _offered_target_change(last) is None:
        return False
    if last.actor.kind != "revealed_greatest_mana_value":
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "two", "or", "more", "cards", "are", "tied", "for", "greatest"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "the", "target", "or", "targets", "remain", "unchanged"
    ):
        stream.reset(mark)
        return False
    return True


def _attach_silent_target_change(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``Changing targets this way doesn't trigger abilities of permanents
    named ~.`` (Psychic Battle.)

    CR 115.7's change is itself a player choosing targets, so without this
    sentence the card would trigger on its own effect — and a second copy on
    the battlefield would trigger on the first one's. Folded onto the change
    the sentence in front of it offered, as a flag the handler passes to the
    announcement it makes.

    The name is the lexer's SELF token and nothing else: the sentence silences
    permanents named for *the card printing it*, which is the one name a card
    can be held to without anything here knowing what it is — the arrangement
    ``postmodifiers`` uses for "another creature named ~" (Goblin Artisans). A
    different card's name behind "named" is a sentence no flag here describes,
    and it refuses.
    """
    last = steps[-1] if steps else None
    change = _offered_target_change(last)
    if change is None:
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "changing", "targets", "this", "way", "doesn't", "trigger",
        "abilities", "of", "permanents", "named",
    ):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != SELF:
        stream.reset(mark)
        return False
    stream.advance()
    steps[-1] = dataclasses.replace(
        last, action=dataclasses.replace(change, silent_for_same_name=True)
    )
    return True


def _attach_counter_cap(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "This ability can't cause the total number of <kind> counters on
    this <noun> to be greater than N." into the placement before it.

    The counter kind is checked against the placement's own, not just consumed:
    a card capping a *different* counter than the one it just placed is saying
    something this rider cannot express, and matching it anyway would cap the
    wrong pile.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.PutCounter):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "this", "ability", "can't", "cause", "the", "total", "number", "of"
    ):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != PT or token.text != last.counter:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_word("counters"):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("on", "this"):
        stream.reset(mark)
        return False
    # The noun is **required**, not merely accepted. Optional, the rider still
    # matched with the word deleted — which the parse-coverage deletion probe
    # reported as a silently ignored word, and it was right: "on this to be
    # greater than four" is not a sentence, and a rule that accepts it is a
    # rule that would accept a cap on some other permanent's counters too.
    if not stream.accept_word(
        "creature", "artifact", "enchantment", "land", "permanent"
    ):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("to", "be", "greater", "than"):
        stream.reset(mark)
        return False
    cap = _accept_number(stream)
    if cap is None:
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, cap=cap)
    return True


def _attach_unaffected_when_cost_paid(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If this spell's additional cost was paid, this effect doesn't
    affect combat damage that would be dealt by red creatures." into the
    prevention before it (Undergrowth).

    A rider rather than a step, and for the reason the whole family exists: on
    its own the sentence names nothing. "**This** effect" is the prevention the
    previous sentence created, and the only thing that can be narrowed is that
    prevention — a second statement would be a second effect, and two blanket
    preventions both applying is the card doing nothing it prints.

    Attaches only to a prevention that has not already been narrowed. A card
    printing this twice is saying something the grammar cannot place, and
    consuming the sentence anyway is the dropped-rider bug the full-consumption
    invariant exists to prevent — so the near-miss rewinds and the line fails
    loudly.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.PreventDamage):
        return False
    if last.unaffected_if_cost_paid is not None:
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "this", "spell", "'s", "additional", "cost", "was", "paid"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "this", "effect", "doesn't", "affect", "combat", "damage",
        "that", "would", "be", "dealt", "by",
    ):
        stream.reset(mark)
        return False
    try:
        excluded = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    steps[-1] = replace(last, unaffected_if_cost_paid=excluded)
    return True


def _attach_flip_stakes_to_loop(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If you win the flip, prevent all combat damage that would be dealt
    by that creature this turn." **into** the loop before it (Fighting Chance).

    "For each blocking creature, flip a coin. If you win the flip, prevent all
    combat damage that would be dealt by that creature this turn." The flip is
    one *per creature* (CR 705.1) and so is what rides on it — "that creature"
    names the member of the loop the flip was made for, and there is no other
    creature it could name.

    So the consequence goes inside the loop's body rather than beside it, which
    is the same structural decision ``statements.py`` already makes for a delay
    printed after a loop ("the delay is printed after the loop but modifies the
    verb inside it"). Left outside, the conditional would ask about *the* flip
    where the loop made one per creature, and the lowering refuses it by name
    ("'the flip' with no coin flip before it in this effect") — so, exactly as
    :func:`delayed.fold_flip_stakes` records for its own position, this can only
    turn a refusal into a card and can never change a reading that already
    worked.

    Attaches only to a loop whose body really flips. A conditional on a flip
    after anything else is a sentence the grammar cannot place, and consuming it
    anyway is the dropped-rider bug the full-consumption invariant exists to
    prevent — so the near-miss rewinds and the line fails loudly.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ForEach) or not contains_flip(last.effect):
        return False
    stakes = parse_flip_stakes_sentence(
        stream, parse_statement, leading_period=False
    )
    if stakes is None:
        return False
    steps[-1] = replace(last, effect=ast.Sequence((last.effect, stakes)))
    return True
