"""Trigger events — the condition half of a triggered ability line.

The word tables a printed trigger clause is matched against, and the fragment
productions that read one. A production here reads the clause between the
trigger word and the comma and knows nothing about a whole line.

**This family has moved twice, and both moves are the size guard working as
documented.** It started in ``parser.py`` and left when the counters-put-on
production pushed that module past a thousand lines; it lived in ``phrases.py``
until Antiquities' trigger work — a cast-type narrowing, a general
put-into-a-graveyard event, and a compound tap-or-activate event — pushed
*that* module past the same line. The guard's instruction is to split along the
family the new work belongs to rather than raise the number, and by then the
trigger tables and their readers were plainly one family: every table in here
is read only by the productions in here.

Sits between ``phrases`` and ``effects`` in the parse layer order: it reads
``phrases``' shared fragments (durations, numbers, subject filters) and nothing
above.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
from .errors import GrammarError
from .lexer import PT, SELF
from .nouns import parse_object_filter
from .references import parse_target_spec
from .phrases import (
    _accept_number,
    parse_subject_filter_at,
)
from .stream import TokenStream
from .state_triggers import _parse_state_trigger_event
from .trigger_subjects import (
    _accept_ability_activated_tail,
    _parse_ability_activated_event,
    _parse_attached_event,
    _parse_attached_step_event,
    _parse_named_subject_tap_event,
)
from .vocabulary import (
    CARD_TYPES, COLOR_WORDS, CREATURE_TYPES,
    ORDINAL_WORDS,
)
from .trigger_tables import (
    _WHENEVER_EVENTS,
    _FILTERED_EVENTS,
    _SUBJECT_LED_EVENTS,
    _AT_EVENTS,
    _CAST_TYPE_FILTERS,
    _CAST_TYPE_UNIONS,
    _DAMAGE_RECIPIENTS,
    _DAMAGER_NOUNS,
)


_REFUSED = object()


def _accept_ordinal_exclusion(stream: TokenStream, type_word: str):
    """"…other than the **first** <type> spell that player casts each turn".

    The ordinal an opponent-cast trigger exempts, or None when no such clause
    is printed. The type word is repeated by the printed clause and must be the
    one already read: a card exempting a *different* type is not this trigger
    narrowed, it is a trigger this production cannot express, so it refuses.
    """
    mark = stream.mark()
    if not stream.accept_phrase("other", "than", "the"):
        stream.reset(mark)
        return None
    ordinal = stream.peek_word()
    if ordinal is None or ordinal not in ORDINAL_WORDS:
        stream.reset(mark)
        return _REFUSED
    stream.advance()
    if not stream.accept_phrase(
        type_word, "spell", "that", "player", "casts", "each", "turn"
    ):
        stream.reset(mark)
        return _REFUSED
    return ordinal


def accept_event_phrase(stream: TokenStream, phrase: tuple[str, ...]) -> bool:
    """Consume *phrase*, reading a SELF token wherever it spells "this <noun>".

    The tables in this file write the source out the modern way — "this
    creature attacks", "a creature dealt damage by this creature this turn
    dies" — and a pre-Sixth-Edition card says its own name instead, which the
    lexer collapses to one SELF token. Those are the same two words, so a plain
    word-run match reads only one of the two spellings: Axelrod Gunnarson's
    death trigger and Nicol Bolas's damage trigger are Sengir Vampire's and
    Hypnotic Specter's conditions printed the old way, and both front ends
    refused them while the productions that ask ``at_kind(SELF)`` by hand read
    theirs. So the substitution is made here, once, for every entry in every
    table rather than by spelling a second row per card.

    All-or-nothing, like ``accept_phrase``: a partial match leaves the stream
    where it was, because a production that consumed half a phrase would strand
    the rest of the line and break full-token consumption.
    """
    mark = stream.mark()
    index = 0
    while index < len(phrase):
        if (
            phrase[index] == "this"
            and index + 1 < len(phrase)
            and phrase[index + 1] in _DAMAGER_NOUNS
            and stream.at_kind(SELF)
        ):
            stream.advance()
            index += 2
            continue
        if not stream.accept_phrase(phrase[index]):
            stream.reset(mark)
            return False
        index += 1
    return True


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
        for phrase, _recipient in _DAMAGE_RECIPIENTS:
            if stream.accept_phrase(*phrase):
                break
        else:
            # A recipient this production cannot name would be consumed as
            # nothing and the trigger would fire on every damage event the card
            # narrows away. Refuse the line instead.
            stream.reset(mark)
            return None
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


def _accept_land_tapped_for_mana_by_a_player(
    stream: TokenStream,
) -> ast.TriggerEvent | None:
    """``a player taps <land phrase> for mana`` — the event, or None.

    The active-voice spelling of ``land_tapped_for_mana``, which
    ``_WHENEVER_EVENTS`` carries only in its unnarrowed form ("a player taps a
    land for mana", Manabarbs): that table matches literal words and has no
    slot for the noun phrase Winter's Night prints. The same words are already
    read one module up for the *delayed* spelling of this ability
    (``delayed._parse_land_tapped_for_mana``, Chaos Moon's odd branch); this
    reader is its printed-on-a-permanent twin and produces the same subject
    filter, so the fire site tests one narrowing however the ability was made.

    A land, and the parser says so rather than the fire site: the tap seam only
    ever announces a land, so a phrase describing anything else would arm an
    ability that can never fire. Non-consuming on refusal, so every other
    "whenever a player …" opener keeps its reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase("a", "player", "taps"):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        land = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("for", "mana"):
        stream.reset(mark)
        return None
    if land.card_types not in ((), ("land",)) or (
        not land.subtypes and not land.supertypes and land.card_types != ("land",)
    ):
        stream.reset(mark)
        return None
    return ast.TriggerEvent("land_tapped_for_mana", "whenever", subject=land)


def _parse_quantified_tap_event(stream: TokenStream) -> ast.TriggerEvent | None:
    """"Whenever **a Forest an opponent controls** becomes tapped" (Lifetap) /
    "Whenever **a Mountain** is tapped for mana" (Gauntlet of Might).

    The two tapping events whose subject is *quantified* rather than named. The
    literal phrases in ``_WHENEVER_EVENTS`` cover the named subjects ("enchanted
    land", "this land", "a player taps a land"); here the subject is a noun
    phrase, so it is parsed and carried on the event instead of being spelled
    out once per printed land type.

    Tried only after that table, which is what keeps "whenever enchanted land
    becomes tapped" reading as ``enchanted_land_tapped``: ``parse_target_spec``
    would happily claim "enchanted land" as a quantified subject and name a
    condition the legacy table does not, which is precisely the disagreement
    ``test_every_executed_trigger_agrees_with_the_legacy_condition_table``
    exists to catch.
    """
    mark = stream.mark()
    # "Whenever **a player taps a snow land for mana**" (Winter's Night). The
    # active voice of the same event, which ``_WHENEVER_EVENTS`` carries only as
    # a fixed seven-word phrase with no room for a narrowing — so a card that
    # names one falls past the table to here. Read before the passive probe
    # below because "a player" would otherwise be parsed as the tapped subject
    # and the phrase would fail on "taps".
    active = _accept_land_tapped_for_mana_by_a_player(stream)
    if active is not None:
        return active
    spec = parse_target_spec(stream)
    # Only the indefinite "a <filter>" reading. "each"/"all"/"target" would be a
    # different event, and "this"/"enchanted" belong to the table above.
    if spec is not None and spec.quantifier == "a" and spec.filter is not None:
        if stream.accept_phrase("becomes", "tapped"):
            # "…**or a player activates an artifact's ability without {T} in
            # its activation cost**" (Haunting Wind, Powerleech). One printed
            # ability with two trigger events, so one kind — and read here,
            # attached to the tap reading, because the tap clause is its
            # prefix: returning the plain tap event first would leave the
            # second half of the *condition* to be parsed as the effect, and a
            # card whose effect happened to parse anyway would fire on half the
            # events it prints.
            if _accept_ability_activated_tail(stream):
                return ast.TriggerEvent(
                    "permanent_tapped_or_ability_activated",
                    "whenever",
                    subject=spec.filter,
                )
            return ast.TriggerEvent(
                "permanent_becomes_tapped", "whenever", subject=spec.filter
            )
        if stream.accept_phrase("is", "tapped", "for", "mana"):
            return ast.TriggerEvent(
                "land_tapped_for_mana", "whenever", subject=spec.filter
            )
    stream.reset(mark)
    return None


def _accept_unshared_colour(stream: TokenStream) -> ast.ObjectFilter | None:
    """``that doesn't share a color with <noun phrase>``, or None.

    CR 105.2's question asked of two objects at once. The set on the far side is
    read with the ordinary noun parser, so "a creature you control" needs no
    words of its own here and the next card comparing against something else
    gets the phrase for free.
    """
    mark = stream.mark()
    if stream.accept_phrase(
        "that", "doesn't", "share", "a", "color", "with"
    ):
        stream.accept_word("a", "an")
        try:
            return parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
    stream.reset(mark)
    return None


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        # CR 603.8's state trigger, under the other printed word ("Whenever
        # there are four or more tide counters on this creature", Homarid).
        # First, because "there" is not a subject and every branch below this
        # one expects one.
        state = _parse_state_trigger_event(stream, "whenever")
        if state is not None:
            return state
        # "…one or more +1/+1 counters are put on <noun phrase>" (Wildwood
        # Scourge). The subject is parsed as a noun phrase and carried on the
        # event, so the exclusion and the controller scope are data — the same
        # shape the quantified tap events above use.
        mark = stream.mark()
        if stream.accept_phrase("one", "or", "more"):
            token = stream.peek()
            if token is not None and token.kind == PT and token.text == "+1/+1":
                stream.advance()
                if stream.accept_phrase("counters", "are", "put", "on"):
                    # "another" sits where the article does, so it is read here
                    # and folded onto the filter's existing exclusion field —
                    # the idiom `_parse_cost_object` and the condition parser
                    # already use, rather than a noun-parser quantifier that
                    # would change every targeted line in the pool.
                    another = bool(stream.accept_word("another"))
                    subject = parse_target_spec(stream)
                    if subject is not None:
                        filt = subject.filter
                        if another:
                            filt = replace(filt, other_than_source=True)
                        return ast.TriggerEvent(
                            "counters_put_on_creature", "whenever", subject=filt,
                        )
        stream.reset(mark)
        # "…casts a *blue* spell" (the Rod/Cup/Sphere cycle, Freyalise's Charm,
        # Leshrac's Sigil). The colour is part of the condition rather than a
        # per-card hook, which is what lets one dispatcher serve every card
        # written this way — and both printed scopes are read here for the
        # reason the type-word loop below reads both: a scope with no colour
        # reading is a card whose colour word strands the line, and the
        # narrowing itself is already one helper on the dispatch side.
        for scope, opener in (
            ("spell_cast", ("a", "player", "casts", "a")),
            ("opponent_casts_spell", ("an", "opponent", "casts", "a")),
        ):
            mark = stream.mark()
            if stream.accept_phrase(*opener):
                colour = stream.peek_word()
                if colour in COLOR_WORDS:
                    stream.advance()
                    if stream.accept_word("spell"):
                        return ast.TriggerEvent(
                            scope, "whenever",
                            subject=ast.ObjectFilter(colors=(COLOR_WORDS[colour],)),
                        )
            stream.reset(mark)
        # "…casts an **artifact** spell" (Urza's Chalice, Citanul Druid). The
        # type narrowing beside the colour one above, and for the same reason:
        # one dispatcher for every card printed this way. Both scopes are read
        # here because both are printed, and the bare spellings in the phrase
        # table below are strict prefixes of these — so a table entry would
        # claim the shorter reading and strand the type word, which is the
        # failure this whole file orders longest-first to avoid.
        for scope, opener in (
            ("spell_cast", ("a", "player", "casts")),
            ("opponent_casts_spell", ("an", "opponent", "casts")),
        ):
            mark = stream.mark()
            if stream.accept_phrase(*opener) and (
                stream.accept_word("a") or stream.accept_word("an")
            ):
                type_word = stream.peek_word()
                # "…casts a **noncreature** spell" (Mystic Remora). The negated
                # spellings are not card types, so they live in the same table
                # the "you cast" productions below read — asked first, because
                # a scope that knew only `CARD_TYPES` refused the printed word
                # and took the whole line with it. `CARD_TYPES` still answers
                # for the words that table does not carry ("enchantment",
                # "land"), which is why both are consulted rather than one.
                narrowed = _CAST_TYPE_FILTERS.get(type_word or "")
                if narrowed is None and type_word in CARD_TYPES:
                    narrowed = ast.ObjectFilter(card_types=(type_word,))
                if narrowed is not None:
                    stream.advance()
                    if stream.accept_word("spell"):
                        # "…**that doesn't share a color with a creature you
                        # control**" (Invoke Prejudice). A narrowing that
                        # compares the cast spell's colours against a set of
                        # *permanents*, so what follows is a whole noun phrase
                        # naming a different object than the one the trigger
                        # fires on — which is why it rides `narrowings` rather
                        # than the subject. Optional, because the bare form
                        # above is a real card (Citanul Druid); the words are
                        # consumed either way, or the line fails the
                        # full-consumption invariant.
                        unshared = _accept_unshared_colour(stream)
                        # "…**other than the first <type> spell that player
                        # casts each turn**" (Ichneumon Druid). The ordinal
                        # exclusion, read here so the words are consumed —
                        # left to the effect parser they would fail the line,
                        # and skipped they would be a narrowing this front end
                        # dropped while the other kept it.
                        # The clause is *consumed* and not carried: the
                        # condition — this narrowing included — comes from
                        # `engine/oracle.py`'s table, and this side only has to
                        # read the whole line rather than choke on it. The same
                        # split the "if it wasn't sacrificed" qualifier makes
                        # below. A clause it cannot read refuses the line, so
                        # the two front ends cannot end up watching different
                        # sets.
                        if _accept_ordinal_exclusion(stream, type_word) is _REFUSED:
                            stream.reset(mark)
                            break
                        return ast.TriggerEvent(
                            scope, "whenever",
                            subject=narrowed,
                            narrowings=(
                                () if unshared is None
                                else (("unshared_color", unshared),)
                            ),
                        )
            stream.reset(mark)
        # "…you cast a spell that's white, blue, black, or red" (Quirion
        # Dryad): a colour-list narrowing of you_cast_spell. Read before the
        # phrase table, whose bare "you cast a spell" entry is its prefix.
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "a", "spell", "that", "'s"):
            colors: list[str] = []
            while True:
                word = stream.peek_word()
                if word not in COLOR_WORDS:
                    break
                stream.advance()
                colors.append(COLOR_WORDS[word])
                if stream.accept_punct(","):
                    stream.accept_word("or")
                    continue
                if stream.accept_word("or"):
                    continue
                break
            if len(colors) >= 2:
                return ast.TriggerEvent(
                    "you_cast_spell", "whenever",
                    subject=ast.ObjectFilter(colors=tuple(colors)),
                )
        stream.reset(mark)
        # "…you cast a noncreature spell" (Spellgorger Weird): a type
        # narrowing of the same condition. The word list mirrors the oracle
        # table's — only what the cast filter tests may be consumed, so a
        # subtype word ("Dog spell") keeps refusing the line rather than
        # compiling a trigger that fires on every spell. Read before the
        # phrase table, whose bare "you cast a spell" entry is its prefix.
        # "Whenever you cast **your first** instant or sorcery spell **each
        # turn**" (Double Vision). An ordinal: the trigger fires on the first
        # such spell of the turn and on no other, so the count is part of the
        # condition rather than of the effect. Read before the bare forms, whose
        # phrases are its strict prefixes.
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "your", "first"):
            for phrase, narrowed in _CAST_TYPE_UNIONS:
                if stream.accept_phrase(*phrase):
                    if stream.accept_phrase("spell", "each", "turn"):
                        return ast.TriggerEvent(
                            "you_cast_first_spell_each_turn", "whenever",
                            subject=narrowed,
                        )
                    break
            word = stream.peek_word()
            narrowed = _CAST_TYPE_FILTERS.get(word or "")
            if narrowed is not None:
                stream.advance()
                if stream.accept_phrase("spell", "each", "turn"):
                    return ast.TriggerEvent(
                        "you_cast_first_spell_each_turn", "whenever",
                        subject=narrowed,
                    )
        stream.reset(mark)
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "an"):
            for phrase, narrowed in _CAST_TYPE_UNIONS:
                if stream.accept_phrase(*phrase) and stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever", subject=narrowed,
                    )
        stream.reset(mark)
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "a"):
            word = stream.peek_word()
            narrowed = _CAST_TYPE_FILTERS.get(word or "")
            if narrowed is not None:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever", subject=narrowed,
                    )
            # "…you cast a **Dog** spell" (Rin and Seri, Inseparable). A
            # creature subtype, which this production refused until the cast
            # filter learned to test one. Read from the vocabulary rather than a
            # literal list, and *after* the type words above so a card type
            # keeps its own narrowing — "creature" is both a type word and, in
            # no set, a subtype, but the ordering is what guarantees it.
            if word in CREATURE_TYPES:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever",
                        subject=ast.ObjectFilter(subtypes=(word,)),
                    )
        stream.reset(mark)
        # Events whose *subject* is a noun phrase rather than the source. Each
        # is read before the phrase table below, whose bare entry is its strict
        # prefix — matching that first is what left Snarespinner compiled to an
        # unnarrowed "this creature blocks" with its rider on the floor.
        # "Whenever **a player puts a Swamp onto the battlefield**" (Thelon's
        # Chant, Tourach's Chant). The entry event named from the player's side
        # rather than the permanent's — one event, so one kind: whatever put it
        # there, a permanent entering the battlefield is what happened, and the
        # engine announces that once from the seam every entry path goes
        # through. Reading it as a condition of its own would need a second fire
        # site watching the same moment.
        #
        # A production rather than a `_FILTERED_EVENTS` row because the phrase
        # continues *after* the noun ("onto the battlefield"), which that
        # table's rows have no way to consume — and an unconsumed tail fails the
        # line.
        mark = stream.mark()
        if stream.accept_phrase("a", "player", "puts"):
            entering = parse_subject_filter_at(stream)
            if entering is not None and stream.accept_phrase(
                "onto", "the", "battlefield"
            ):
                return ast.TriggerEvent(
                    "matching_permanent_enters", "whenever", subject=entering,
                )
        stream.reset(mark)
        for phrase, kind in _FILTERED_EVENTS:
            mark = stream.mark()
            if accept_event_phrase(stream, phrase):
                # "…becomes blocked by **one or more** Orcs" (Dwarven Soldier).
                # The counted spelling of the same narrowing, read before the
                # quantified one because a bare plural is a different reading of
                # the noun ("Orcs" is a kind, "an Orc" is one of them) and the
                # number in front is what says how many. CR 509.3e is what the
                # count means; `engine/oracle.py`'s table is where it lands as
                # the condition's payload, and this side has only to agree that
                # the words describe a subject.
                counted = stream.mark()
                count = _accept_number(stream)
                if count is not None and stream.accept_phrase("or", "more"):
                    subject = parse_subject_filter_at(stream, plural=True)
                    if subject is not None:
                        return ast.TriggerEvent(kind, "whenever", subject=subject)
                stream.reset(counted)
                subject = parse_subject_filter_at(stream)
                if subject is not None:
                    return ast.TriggerEvent(kind, "whenever", subject=subject)
            stream.reset(mark)
        # The two triggers on the *declaration* (CR 508.1) — how many creatures
        # attacked, which no per-creature event can answer. Both read a printed
        # number, and both are tried before the phrase table below, whose
        # "this creature attacks" entry is the generic reading of the second.
        mark = stream.mark()
        # "Whenever **a player** attacks with one or more creatures" (Total
        # War) — the same declaration asked of every seat instead of the
        # ability's controller, so one kind with the difference in the
        # condition's payload: what differs is the question, not the event.
        if stream.accept_phrase("a", "player", "attacks", "with"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase("or", "more"):
                subject = parse_subject_filter_at(stream, plural=True)
                if subject is not None:
                    return ast.TriggerEvent(
                        "attackers_declared", "whenever", subject=subject
                    )
        stream.reset(mark)
        if stream.accept_phrase("you", "attack", "with"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase("or", "more"):
                # The counted position: a bare plural names a *kind* here, and
                # the number in front of it is what says how many.
                subject = parse_subject_filter_at(stream, plural=True)
                if subject is not None:
                    return ast.TriggerEvent(
                        "attackers_declared", "whenever", subject=subject
                    )
        stream.reset(mark)
        if stream.accept_phrase("this", "creature", "and", "at", "least"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase("other", "creatures", "attack"):
                return ast.TriggerEvent("attackers_declared", "whenever")
        stream.reset(mark)
        # The two named-subject tap events (Artifact Possession, Psychic Venom,
        # City of Brass, Spirit Shackle). Read before the phrase table, whose
        # entries would claim their prefixes.
        # The activation event whose subject is the *ability's* permanent
        # rather than the sentence's opening noun (Imprison). Before the tap
        # productions for the same reason they sit before the phrase table:
        # "a player activates …" would otherwise be read as a quantified
        # subject and named a condition the legacy table does not.
        activated = _parse_ability_activated_event(stream, "whenever")
        if activated is not None:
            return activated
        attached = _parse_attached_event(stream, "whenever")
        if attached is not None:
            return attached
        named_tap = _parse_named_subject_tap_event(stream, "whenever")
        if named_tap is not None:
            return named_tap
        damage = _parse_damage_dealt_event(stream, "whenever")
        if damage is not None:
            return damage
        for kind, phrase in _WHENEVER_EVENTS:
            if accept_event_phrase(stream, phrase):
                return ast.TriggerEvent(kind, "whenever")
        # "Whenever an **artifact you control** is put into a graveyard from
        # the battlefield" (Tablet of Epityr, Urza's Miter). Subject-led, so it
        # sits **after** the phrase table for the reason stated just below: the
        # table holds the specific readings, and "a land is put into a
        # graveyard from the battlefield" is Dingus Egg's own event with its own
        # fire site and its own damage shape. Read first, this production would
        # claim that line as a generic death and Dingus Egg would stop working.
        #
        # The article is consumed here rather than by the noun parser, which
        # refuses "an" as an unknown adjective — the same split the condition
        # parser makes for "you control **a** Swamp".
        grave_mark = stream.mark()
        stream.accept_word("a", "an")
        try:
            dying = parse_object_filter(stream)
        except GrammarError:
            dying = None
        # "…is put into **a**/**your**/**an opponent's** graveyard from the
        # battlefield". Whose graveyard is a narrowing on the condition, which
        # this front end does not carry — `engine/oracle.py`'s table supplies the condition and this
        # one supplies the effect. The word still has to be *consumed* or the
        # line fails full-token consumption and the card loses its ability.
        dying_grave = (
            stream.accept_phrase(
                "is", "put", "into", "a", "graveyard", "from", "the", "battlefield"
            )
            or stream.accept_phrase(
                "is", "put", "into", "your", "graveyard", "from", "the", "battlefield"
            )
            or stream.accept_phrase(
                "is", "put", "into", "an", "opponent", "'s", "graveyard",
                "from", "the", "battlefield"
            )
        )
        if dying is not None and dying_grave:
            # "…**, if it wasn't sacrificed**" (Urza's Miter). CR 603.4's
            # intervening-if, consumed here so the sentence is read whole —
            # left for the effect parser it would be an imperative nobody can
            # perform, and the line would fail on a clause it does understand.
            # The condition's own payload carries it; this side only has to
            # not choke on it.
            qualifier = stream.mark()
            if not (
                stream.accept_punct(",")
                and stream.accept_phrase("if", "it", "wasn't", "sacrificed")
            ):
                stream.reset(qualifier)
            return ast.TriggerEvent("permanent_dies", "whenever", subject=dying)
        stream.reset(grave_mark)
        # "Whenever a creature you control with deathtouch attacks / deals
        # damage to a planeswalker" (Hooded Blightfang): the subject leads, so
        # there is no fixed prefix to key on — the noun phrase is tried and the
        # verb behind it decides whether it was one. *After* the phrase table,
        # because that table's entries are the specific readings: "a land
        # enters" is Ankh of Mishra's own event with its own fire site, and this
        # production would otherwise claim it as a generic entry.
        # "Whenever **one or more** Cats you control deal combat damage to a
        # player" (Feline Sovereign). Counted rather than quantified, which is
        # what the plural subject reading is for — and read before the
        # subject-led table below, whose productions expect the phrase to lead.
        # "Whenever **you reveal a basic land card this way**, draw a card."
        # (Rowen.) The subject is the player and the noun phrase is the *card*
        # revealed, so neither the phrase table (fixed words) nor the
        # subject-led table (the phrase leads) can read it. "This way" is
        # required and is the whole narrowing: it names the reveal the card's
        # own first sentence asks for — see `engine/draw_reveals.py` — where a
        # bare "whenever you reveal a card" would fire on a search, a scry and
        # a hand reveal too.
        reveal_mark = stream.mark()
        if stream.accept_phrase("you", "reveal"):
            revealed = parse_subject_filter_at(stream)
            if revealed is not None and stream.accept_phrase("this", "way"):
                return ast.TriggerEvent(
                    "revealed_drawn_card", "whenever", subject=revealed
                )
        stream.reset(reveal_mark)
        batch_mark = stream.mark()
        if stream.accept_phrase("one", "or", "more"):
            batched = parse_subject_filter_at(stream, plural=True)
            if batched is not None and stream.accept_phrase(
                "deal", "combat", "damage", "to", "a", "player"
            ):
                return ast.TriggerEvent(
                    "one_or_more_deal_combat_damage", "whenever", subject=batched
                )
        stream.reset(batch_mark)
        mark = stream.mark()
        # "Whenever **this creature or** another Rogue you control enters"
        # (Thieves' Guild Enforcer) — the source's own entry spelled out. The
        # subject that follows is the same noun phrase the bare form reads, and
        # the difference is exactly the word "another": with the prefix the
        # source is *included*, so the exclusion the noun parser folds on for
        # "another" has to be undone here rather than left to narrow a set the
        # card widened.
        explicit_self = bool(stream.accept_phrase("this", "creature", "or"))
        subject = parse_subject_filter_at(stream)
        if subject is not None:
            if explicit_self:
                subject = replace(subject, other_than_source=False)
            for phrase, kind in _SUBJECT_LED_EVENTS:
                if stream.accept_phrase(*phrase):
                    # "Whenever a creature attacks **you**" (Barbed Foliage).
                    # CR 508.1a makes attacking a state of the creature and
                    # CR 506.2 makes *whom* it attacks the defending player it
                    # was declared against, so the extra word is a narrowing of
                    # the subject rather than a second event — the same
                    # `attacking_you` field the printed relative clause
                    # ("target creature that's attacking you") already sets, and
                    # answered against the ability's own controller.
                    #
                    # Read here rather than as a second table row because the
                    # row would have to carry a subject rewrite, and a table
                    # whose values are two different kinds of thing stops being
                    # a table. Dropping the word instead would be the silent
                    # widening this whole file is written to avoid: Barbed
                    # Foliage would fire on an attack aimed at somebody else.
                    if kind == "matching_creature_attacks" and stream.accept_word("you"):
                        subject = replace(subject, attacking_you=True)
                    return ast.TriggerEvent(kind, "whenever", subject=subject)
        stream.reset(mark)
        return _parse_quantified_tap_event(stream)
    if stream.accept_word("at"):
        attached_step = _parse_attached_step_event(stream, "at")
        if attached_step is not None:
            return attached_step
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        if accept_event_phrase(stream, ("this", "creature", "dies")):
            return ast.TriggerEvent("dies", "when")
        # CR 700.4: "dies" *means* "is put into a graveyard from the
        # battlefield", so Brood of Cockroaches' long spelling is the same
        # event and not a second one. "Your" graveyard is not a narrowing
        # either — CR 404.1 sends a permanent to its owner's graveyard, and the
        # subject here is the ability's own source, so the possessive can only
        # ever be its controller's on a card that is also its owner's.
        #
        # Read before the state-trigger reader below for the same reason every
        # long phrase in this file is read before a short one: nothing else
        # opens on these words, and a production that got there first would
        # strand the tail.
        if accept_event_phrase(stream, (
            "this", "creature", "is", "put", "into", "your", "graveyard",
            "from", "the", "battlefield",
        )):
            return ast.TriggerEvent("dies", "when")
        state = _parse_state_trigger_event(stream, "when")
        if state is not None:
            return state
        # "**When** enchanted land becomes tapped, destroy it" (Blight). The
        # same event as the whenever spelling — one printed word apart — so it
        # is the same production, asked with the word this branch read.
        named_tap = _parse_named_subject_tap_event(stream, "when")
        if named_tap is not None:
            return named_tap
        # "When you remove the last intervention counter from this enchantment"
        # (Divine Intervention). Read here as well as in `engine/oracle.py`'s
        # table for the reason stated above the threshold trigger: both front
        # ends see the whole line, and a condition only one of them reads leaves
        # the other refusing the effect behind it.
        mark_removal = stream.mark()
        if stream.accept_phrase("you", "remove", "the", "last"):
            kind = stream.peek_word()
            if kind:
                stream.advance()
                if stream.accept_word("counter") and stream.accept_word("from"):
                    if stream.at_kind(SELF) or stream.at_word("this"):
                        stream.advance()
                        stream.accept_word(
                            "artifact", "aura", "creature", "enchantment",
                            "permanent", "land",
                        )
                        return ast.TriggerEvent("last_counter_removed", "when")
        stream.reset(mark_removal)
        # "When the last ore counter **is removed** from this Aura" (Orcish
        # Mine). The passive voice of the branch above and the same event: a
        # counter removal is one event whoever performed it (CR 121.3), and the
        # sweep that announces it reads the record every removal path writes.
        # Read on this front end as well as in `engine/oracle.py`'s table, for
        # the reason the active voice is: a condition only one of them reads
        # leaves the other refusing the effect behind it.
        mark_passive = stream.mark()
        if stream.accept_phrase("the", "last"):
            kind = stream.peek_word()
            if kind:
                stream.advance()
                if stream.accept_word("counter") and stream.accept_phrase(
                    "is", "removed", "from"
                ):
                    if stream.at_kind(SELF) or stream.at_word("this"):
                        stream.advance()
                        stream.accept_word(
                            "artifact", "aura", "creature", "enchantment",
                            "permanent", "land",
                        )
                        return ast.TriggerEvent("last_counter_removed", "when")
        stream.reset(mark_passive)
        # "When a spell or ability an opponent controls causes you to discard
        # this card" (Psychic Purge). Read on both front ends, same reason.
        if stream.accept_phrase(
            "a", "spell", "or", "ability", "an", "opponent", "controls",
            "causes", "you", "to", "discard", "this", "card",
        ):
            return ast.TriggerEvent("discarded_by_opponent_effect", "when")
        # "When **you cast this spell**" (Mana Vortex) — CR 603.6d, an ability
        # that triggers on its own object being cast. Read on this front end
        # too, for the reason every condition above it is: a condition only one
        # of them sees leaves the other refusing the effect behind it.
        if stream.accept_phrase("you", "cast", "this", "spell"):
            return ast.TriggerEvent("self_cast", "when")
        # "When you control **no Islands** / **no Forests**, sacrifice this
        # creature." (Sea Serpent, Island Fish Jasconius; Gorilla Pack in Ice
        # Age.) The negative twin of `controls_matching_permanent` below, and
        # the noun is payload for the same reason it is there: this was a
        # ``no_islands`` kind with the land type welded into the name, so a card
        # printing any other type was a card the engine could not read.
        mark_none = stream.mark()
        if stream.accept_phrase("you", "control", "no"):
            # Plural, because "no" counts: the card prints "no **Islands**",
            # never "no an Island", so the counted-position quantifier is the
            # one to admit.
            described = parse_subject_filter_at(stream, plural=True)
            if described is not None:
                return ast.TriggerEvent(
                    "controls_no_matching", "when", subject=described
                )
        stream.reset(mark_none)
        # "When you control **a Dwarf**" (Goblins of the Flarg). The positive
        # state trigger (CR 603.8), read on this front end too because a
        # condition only one of them sees is a card whose halves watch
        # different sets — the narrowing has to be the same phrase on both.
        mark_controls = stream.mark()
        if stream.accept_phrase("you", "control"):
            controlled = parse_subject_filter_at(stream)
            if controlled is not None:
                return ast.TriggerEvent(
                    "controls_matching_permanent", "when", subject=controlled
                )
            stream.reset(mark_controls)
        # "When **the token** leaves the battlefield, …" (Dance of Many). The
        # CR 603.6c event asked about the token this permanent created rather
        # than about the permanent itself — read on this front end too, because
        # a narrowing only one of them sees is a card whose two halves watch
        # different objects (the pipeline's oldest failure mode).
        if stream.accept_phrase("the", "token", "leaves", "the", "battlefield"):
            return ast.TriggerEvent("created_token_leaves_battlefield", "when")
        # "**When you lose control of this artifact**, …" (Gustha's Scepter).
        # CR 603.10d's event, read on this front end too for the reason the
        # token row above states: a condition only one of them sees is a card
        # whose two halves watch different things. The permanent noun is
        # consumed as a word rather than matched against a spelling, so an
        # enchantment or a creature printing the same sentence needs no branch —
        # and "it" is the same reference one pronoun shorter.
        mark_control = stream.mark()
        if stream.accept_phrase("you", "lose", "control", "of"):
            if stream.accept_word("it"):
                return ast.TriggerEvent("lose_control_of_source", "when")
            if stream.accept_word("this", "the") and not (
                stream.exhausted or stream.at_punct(",", ".")
            ):
                stream.advance()
                return ast.TriggerEvent("lose_control_of_source", "when")
        stream.reset(mark_control)
        mark = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                stream.accept_word("creature", "artifact", "enchantment", "land", "aura")
            if stream.accept_word("enters"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("enters_battlefield", "when")
            if stream.accept_word("leaves"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("leaves_battlefield", "when")
        stream.reset(mark)
        # "**When** this creature blocks" (Elder Land Wurm), "**when** this
        # creature attacks or blocks" (Time Elemental) — events the "whenever"
        # table already names, printed with the one-shot word. CR 603.1 makes
        # the two words one kind of ability; the difference is how often it
        # triggers while it exists, not what triggers it, and every fire site in
        # this engine reads the kind rather than the word. So the *table* is
        # asked here rather than a hand-written subset of it: a branch naming
        # "blocks" alone was why Elder Land Wurm's condition read and Time
        # Elemental's — one printed word longer, and already in the table —
        # did not.
        for kind, phrase in _WHENEVER_EVENTS:
            if accept_event_phrase(stream, phrase):
                return ast.TriggerEvent(kind, "when")
        return None
    return None
