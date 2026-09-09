"""Every sentence whose printed first word is "If", and which one means it.

Nine of the ten productions here are not conditionals at all. "If target Plains
is tapped for mana, it produces colorless mana instead of white mana" (Quarum
Trench Gnomes) tests nothing when the ability resolves — the arm is a standing
change to what a land will produce later. "If a card would be put into your
graveyard from anywhere this turn, exile that card instead" (Yawgmoth's Will)
is CR 614's replacement, which is about what *would* happen rather than about
what is true. "If the top card of target player's graveyard is a creature card,
put that card on top of that player's library" (Guiding Spirit) names one card
in both halves, so split into a condition and an arm neither half can say which
card it means. Each of them wears the word the intervening-if wears, and the
generic ``if <condition>, <statement>`` at the bottom of this file is the one
that means it.

So the file *is* the ordering. Every production above the last refuses without
consuming, and the last is the fall-through the other nine exist to get in
front of — which is why the generic conditional came with them rather than
staying behind. Cutting above it would have put one ordering in two files and
left neither able to state it.

Split out of ``statements`` at Urza's Legacy's Phase 0, when that module stood
14 lines under the thousand-line guard with five parallel groups about to add
sentence openings to ``_parse_statement_body``. The seam is one the cascade had
already drawn for itself — a contiguous run of ten branches, every one about a
sentence opening on "if", and nothing between them was — and ``statements``
reads no ``if`` opener at all now, which is what makes this a subject rather
than a chunk.

**There is no mirror name to reuse.** ``conditions`` is the *event* half and is
spoken for on every side already (``conditions`` here, ``ast/conditions.py``,
``lowering/conditions.py``); ``ast.Conditional`` is lowered inline by
``statement_dispatch`` rather than by a family; and ``control_flow``, the
mirror word for the ``if_then`` wrapper these lower through, is the branch
reader one layer *above* ``statements`` and so cannot be imported from below
it. The name says what the file reads instead of borrowing a word already
spoken for — ``static_lines``' answer to the same problem.

Below ``statements``, which hands down ``parse_statement`` rather than being
imported back: the inversion ``subject_verb``, ``delayed``,
``sentence_clauses`` and ``leading_iteration`` all make.
"""

from __future__ import annotations

from . import ast
from .conditions import _parse_condition
from .effects import (_parse_bound_targeting_prevention,
                      _parse_damage_dealt_riders,
                      _parse_optional_damage_redirect,
                      _parse_produces_instead,
                      _parse_tapper_produces_instead,
                      parse_graveyard_top_to_library)
from .effects.exile import (_parse_bin_unplayed_exiled_card,
                            parse_exile_graveyard_arrivals_this_turn)
from .effects.stack import _parse_conditional_retarget
from .errors import GrammarError
from .rebinding import (rebind_player_pronoun_to_condition_target,
                        rebind_pronoun_to_condition_target)
from .stream import TokenStream


def parse_if_opening(
    stream: TokenStream, *, parse_statement
) -> ast.Statement | None:
    """One sentence opening on "if", or ``None`` when this is not one.

    Declines **without consuming** — every branch restores the stream before it
    gives up, the generic conditional included — so the caller's cascade keeps
    every reading it had.
    """
    # "If target Plains is tapped for mana, it produces colorless mana instead
    # of white mana." (Quarum Trench Gnomes.) The printed shape opens like an
    # ordinary conditional, but its "condition" is not one: nothing is tested
    # when the ability resolves, and the arm is a standing change to what the
    # land will produce later. Read before the conditional below, which would
    # take the clause as an intervening-if over a sentence it has no production
    # for — and refuses without consuming, so every other "if" keeps its
    # reading.
    if stream.at_word("if"):
        # "If you haven't played it, put it into its owner's graveyard."
        # (Grinning Totem, inside its delay.) Read here rather than as an
        # ordinary conditional because the condition is what binds the pronoun
        # in its arm: "put it into its owner's graveyard" on its own is All
        # Hallow's Eve's sentence about the ability's own source, and nothing
        # else in the words tells the two referents apart. Refuses without
        # consuming, so every other "If …" keeps its reading.
        binned = _parse_bin_unplayed_exiled_card(stream)
        if binned is not None:
            return binned
        # "If target spell has only one target and that target is a creature,
        # change that spell's target to another creature." (Meddle.) Read here
        # for the reason the two below it are: what looks like a condition is
        # not one — nothing about the *board* is tested, and both halves are
        # questions about the announced target of another object, which the
        # picker has to ask before the spell is cast at all. Refuses without
        # consuming, so every other "If …" keeps its reading.
        retarget = _parse_conditional_retarget(stream)
        if retarget is not None:
            return retarget
        # "If the top card of target player's graveyard is a creature card, put
        # that card on top of that player's library." (Guiding Spirit.) Read
        # here for the two above's reason: the printed "if" is part of the
        # effect rather than a condition over it — both halves name the top card
        # of one graveyard, and split into a condition and an arm neither half
        # can say which card it means. Refuses without consuming, so every other
        # "If …" keeps its reading.
        graveyard_top = parse_graveyard_top_to_library(stream)
        if graveyard_top is not None:
            return graveyard_top
        produces = _parse_produces_instead(stream)
        if produces is not None:
            return produces
        # "…if **you tap** a land you control for mana, it produces {U} instead
        # of any other type." (Deep Water.) "…if **a player taps** a Mountain
        # for mana, that Mountain produces colorless mana instead of any other
        # type." (Chaos Moon.) The active-voice spellings of the same swap,
        # beside it and refusing the same way.
        produces = _parse_tapper_produces_instead(stream)
        if produces is not None:
            return produces

    # "If a card would be put into your graveyard from anywhere this turn,
    # exile that card instead." (Yawgmoth's Will.) A CR 614 replacement a
    # *spell* creates, which is what makes it a production: the unbounded
    # spelling is a permanent's static ability and the registry claims that one
    # off the card's text, where a sorcery is on no battlefield when the
    # replacement is meant to apply. Read here beside the other
    # replacement-shaped "If …" clauses and refusing without consuming, so the
    # registry's line keeps its claim.
    graveyard_exile = parse_exile_graveyard_arrivals_this_turn(stream)
    if graveyard_exile is not None:
        return graveyard_exile

    # "If a spell or ability that targets that creature would cause a source to
    # deal damage to that creature this turn, prevent that damage."
    # (Silhouette.) A *replacement* condition — what would happen, not what is
    # true — so the generic conditional below cannot read it; tried first and
    # refusing without consuming, so every other "If …" is untouched.
    bound_shield = _parse_bound_targeting_prevention(stream)
    if bound_shield is not None:
        return bound_shield

    # "If the creature deals damage to a creature this turn, the creature dealt
    # damage can't be regenerated this turn." (Runesword.) The other side of
    # the same verb, and not a conditional either: the sentence grants a
    # standing property to the creature the ability targeted. Read here, beside
    # the shield above and before the generic conditional, and refusing without
    # consuming.
    dealt_riders = _parse_damage_dealt_riders(stream)
    if dealt_riders is not None:
        return dealt_riders

    # "If damage would be dealt to any creature, you may have that damage dealt
    # to you instead." (Blood of the Martyr.) A replacement condition too, and
    # here for the same reason as the shield above: the generic conditional
    # below tests what is *true* when the sentence resolves, and this one is
    # about what *would happen* later in the turn. Refuses without consuming.
    optional_redirect = _parse_optional_damage_redirect(stream)
    if optional_redirect is not None:
        return optional_redirect

    # "if <condition>, <statement>"
    if stream.at_word("if"):
        mark = stream.mark()
        stream.advance()
        try:
            condition = _parse_condition(stream)
            stream.accept_punct(",")
            then = parse_statement(stream, top_level=False)
            # "If **target creature** has toughness 5 or greater, **it** gets
            # +4/-4…" (Blood Lust). The condition announced the spell's target
            # (CR 601.2c), so the pronoun in the arm names that choice — without
            # this the arm reads "it" as the spell itself and lowers to a pump
            # of a card on the stack, which is a supported card that does
            # nothing.
            # "…is 5 or less, exchange life totals with **that player**"
            # (Psychic Transfer). The same substitution for the *player*
            # pronoun, run after the object one: a condition that announced a
            # targeted seat has chosen it, and "that player" names that choice.
            return ast.Conditional(
                condition,
                rebind_player_pronoun_to_condition_target(
                    condition, rebind_pronoun_to_condition_target(condition, then)
                ),
            )
        except GrammarError:
            stream.reset(mark)
    return None
