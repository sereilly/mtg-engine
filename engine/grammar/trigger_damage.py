"""The **damage** event a trigger clause names — CR 120.4b, both its ends.

"Whenever <someone> deals [combat|noncombat] damage [to <someone>]": who dealt
it (the source itself, the permanent an Aura enchants, any source a player
controls, or a printed noun phrase) and who took it (a seat word, a noun
phrase, or a union of the two in either printed order).

The fifth split off ``triggers`` and the fifth along a line the family already
had — one production reading one event, with the phrase tables it walks already
one module further down in ``trigger_tables``. It went when Flesh Reaver's
recipient union took ``triggers`` two lines past the thousand-line guard, and
it is the module the *next* damage-recipient spelling lands in too, which is
the point of cutting here rather than shaving the comment that crossed the
line.

The trigger *word* is a parameter rather than a literal, for
``trigger_casts``' reason: CR 603.1 makes "when" and "whenever" one kind of
ability, and every fire site in this engine reads the kind.

Below ``triggers``, which asks it and is never imported back, and above
``phrases``, whose subject-filter reader both halves of the event use. It
reaches no word table ``triggers`` owns — the two it needs are
``trigger_tables``', already below both.

No mirror name to reuse. ``lowering/damage.py`` is a whole family on the other
side and is about the *effect* a sentence performs; this reads the condition
that fires one, which is the split ``trigger_casts`` already made against
``lowering/cards.py``.
"""

from __future__ import annotations

from . import ast
from .lexer import SELF
from .phrases import parse_subject_filter_at
from .stream import TokenStream
from .trigger_tables import _DAMAGE_RECIPIENTS, _DAMAGER_NOUNS


#: The bare seat words a damage recipient may end with, where the noun phrase
#: in front of them already carried the article ("a creature **or opponent**",
#: Flesh Reaver). Held to the words ``engine/oracle.py``'s
#: ``damage_recipient_seat_after`` alternation names: a word consumed here that
#: the condition table cannot test is a trigger firing on damage the card
#: narrows away.
_SUFFIX_RECIPIENT_SEATS = ("opponent", "you")


def _parse_damage_dealt_event(
    stream: TokenStream, word: str
) -> ast.TriggerEvent | None:
    """"Whenever <someone> deals [combat|noncombat] damage [to <someone>]" —
    CR 120.4b's event, whoever dealt it and whoever took it.

    One production for what was five phrase-table entries and two subject-led
    ones, because they are one event asked with different narrowings. Both are
    read here and carried on the node: the damager (the source itself, the
    permanent this Aura enchants, any source a player controls, or a noun
    phrase) and the recipient. `engine/oracle.py`'s table names the same groups,
    and `engine/damage_events.py` announces the event once for all of them.

    Tried before the phrase table, whose remaining entries would claim these
    lines' prefixes, and before the subject-led table, which reads a noun phrase
    speculatively and would take "a creature you control with deathtouch" for an
    attack trigger's subject.
    """
    mark = stream.mark()
    subject: ast.ObjectFilter | None = None
    narrowings: tuple[tuple[str, ast.ObjectFilter], ...] = ()
    # "Whenever **you're dealt damage**, …" (Blood Hound). CR 120.4b's event in
    # the passive voice: the recipient leads and the damager is not printed at
    # all, which is the sentence saying *any* source — the same reading the
    # "a source" branch below gives when a card spells the words out.
    #
    # Read first, and it has to be: the noun parser at the bottom of the chain
    # would take "you" for a damager and then fail on the missing "deals",
    # refusing the line rather than falling through to here. The recipient is
    # consumed and not carried, exactly as the active form's is —
    # `engine/oracle.py`'s row marks the seat and `events._damage_dealt_filter`
    # tests it, which is where every other recipient narrowing is answered.
    passive = stream.mark()
    if stream.accept_word("you're") or (
        stream.accept_word("you") and stream.accept_word("are")
    ):
        if stream.accept_word("dealt"):
            stream.accept_word("combat", "noncombat")
            if stream.accept_word("damage"):
                return ast.TriggerEvent(
                    "damage_dealt", word,
                    subject=ast.ObjectFilter(), narrowings=narrowings,
                )
    stream.reset(passive)
    if stream.at_kind(SELF) or stream.at_word("this"):
        stream.advance()
        if not stream.at_kind(SELF):
            stream.accept_word(*_DAMAGER_NOUNS)
        subject = ast.ObjectFilter(is_source=True)
    elif stream.accept_word("enchanted"):
        if stream.peek_word() is None:
            stream.reset(mark)
            return None
        stream.advance()
        subject = ast.ObjectFilter(is_enchanted=True)
    elif stream.accept_phrase("a", "source", "you", "control"):
        # "A source you control" is a *seat*, not a set of permanents: a spell
        # is a source too, and no ObjectFilter can name one. The narrowing rides
        # the controller field, which is what the dispatcher reads.
        subject = ast.ObjectFilter(controller="you")
    elif stream.accept_phrase("a", "source"):
        # "Whenever **a source** deals damage to this creature" (Crag Saurian).
        # The unnarrowed damager, and an empty filter is exactly that — CR
        # 109.5's word covers a spell and an ability as well as a permanent, so
        # there is nothing here for a noun phrase to describe. Below "a source
        # you control", which is a strict prefix of nothing and would be claimed
        # by this branch if it came first, and above the noun parser, which
        # refuses the bare word and would take the line down with it.
        subject = ast.ObjectFilter()
    else:
        subject = parse_subject_filter_at(stream)
        if subject is None:
            stream.reset(mark)
            return None
        # "…a red creature **or spell** deals damage" (Justice). One object
        # under two nouns; the union narrows the *condition* rather than this
        # node (the division of labour the graveyard clause below states), so
        # all that is owed here is consuming the words — left on the stream the
        # line fails full-token consumption and the card loses the ability.
        spell_union = stream.mark()
        if not (stream.accept_word("or") and stream.accept_word("spell")):
            stream.reset(spell_union)
    if not stream.accept_word("deals"):
        stream.reset(mark)
        return None
    stream.accept_word("combat", "noncombat")
    if not stream.accept_word("damage"):
        stream.reset(mark)
        return None
    if stream.accept_word("to"):
        # "…deals damage **to this creature**" (Crag Saurian). The ability's own
        # source as the *recipient*, read the same way the damager branch at the
        # top of this production reads it: the fixed-word table below names
        # players and planeswalkers, and the noun parser after it refuses "this"
        # outright — so without this branch the words strand the line.
        #
        # Consumed and not carried, exactly as Justice's "or spell" is:
        # `engine/oracle.py`'s table marks the self-reference and
        # `events._damage_dealt_filter` tests it by identity, which is not
        # something an `ObjectFilter` narrowing could say.
        self_recipient = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                if stream.accept_word(*_DAMAGER_NOUNS):
                    return ast.TriggerEvent(
                        "damage_dealt", word, subject=subject,
                        narrowings=narrowings,
                    )
            else:
                return ast.TriggerEvent(
                    "damage_dealt", word, subject=subject, narrowings=narrowings,
                )
            stream.reset(self_recipient)
        for phrase, _recipient in _DAMAGE_RECIPIENTS:
            if stream.accept_phrase(*phrase):
                break
        else:
            # "…deals damage **to a creature**" (Bellowing Fiend). A recipient
            # that is an object rather than a seat: every phrase in the table
            # above names a player or a planeswalker, so a noun phrase has no
            # entry there and cannot get one — the table is fixed words and this
            # is anything the noun parser reads.
            #
            # Carried under the same ``damaged`` stem the union below uses, so
            # the two front ends describe one narrowing one way
            # (``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides``).
            # Returned here rather than falling through, because the union
            # clause below is about a *second* half this branch has already
            # consumed the whole of.
            #
            # A phrase the noun parser refuses still refuses the line, which is
            # the lock this else-branch has always been: a recipient consumed as
            # nothing is a trigger firing on every damage event in the game.
            damaged_only = parse_subject_filter_at(stream)
            if damaged_only is None:
                stream.reset(mark)
                return None
            # "…deals damage to **a creature or opponent**" (Flesh Reaver). The
            # union the branch below reads, printed the other way round — and
            # English drops the second article when it does, which is why the
            # seat word is bare here and carries one there.
            #
            # **Consumed and not carried**, which is where this differs from
            # the seat-first union below and matches Justice's "or spell" above
            # it: `engine/oracle.py`'s condition table is what tests a
            # recipient seat (`damage_recipient_seat_after`), and this node's
            # `narrowings` are noun phrases — a seat is not one, so there is
            # nothing here that could hold it. Left on the stream instead, the
            # line fails full-token consumption and the card loses the ability.
            #
            # All-or-nothing, exactly as the branch below is: an "or" the
            # condition table cannot name rewinds and leaves the line refusing
            # rather than dropping half a printed recipient.
            suffix = stream.mark()
            if stream.accept_word("or") and not stream.accept_word(
                *_SUFFIX_RECIPIENT_SEATS
            ):
                stream.reset(suffix)
            return ast.TriggerEvent(
                "damage_dealt", word, subject=subject,
                narrowings=(("damaged", damaged_only),),
            )
        # "…deals damage to **you or a white creature you control**"
        # (Mangara's Equity). A seat word and a noun phrase naming one
        # recipient between them: the table above matched the seat, and the
        # object half is read here. Left on the stream it fails full-token
        # consumption and the card loses the whole ability, which is what it
        # did.
        #
        # **Carried, not merely consumed**, which is where this differs from
        # Justice's "or spell" above: that word narrows nothing the noun parser
        # reads, and this is a whole printed phrase. `engine/oracle.py`'s table
        # delimits it as a `damaged_subject` group, so the grammar records it
        # under the same stem — a phrase one front end consumed and the other
        # tested is a card whose two halves watch different sets, which is
        # exactly what `test_a_narrowed_trigger_reads_the_same_subject_on_both_sides`
        # is there to catch.
        #
        # All-or-nothing, so "…to you or an opponent" — a union of two seats,
        # which the condition table does not name — rewinds and leaves the line
        # refusing rather than silently dropping the second half.
        union = stream.mark()
        if stream.accept_word("or"):
            damaged = parse_subject_filter_at(stream)
            if damaged is None:
                stream.reset(union)
            else:
                narrowings = (("damaged", damaged),)
    return ast.TriggerEvent(
        "damage_dealt", word, subject=subject, narrowings=narrowings
    )
