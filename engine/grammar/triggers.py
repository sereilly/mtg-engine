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

from dataclasses import replace

from . import ast
from .errors import GrammarError
from .lexer import PT, SELF
from .nouns import parse_object_filter
from .references import parse_target_spec
from .phrases import (
    _accept_number,
    _identifies_one_object,
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
from .trigger_casts import _parse_cast_event
from .trigger_tables import (
    _WHENEVER_EVENTS,
    _BARE_BOARD_WIDE_BLOCK_EVENTS,
    _BOARD_WIDE_BLOCK_EVENTS,
    _FILTERED_EVENTS,
    _SUBJECT_LED_EVENTS,
    _AT_EVENTS,
    _DAMAGE_RECIPIENTS,
    _DAMAGER_NOUNS,
)



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


def _accept_land_tapped_for_mana_by_a_player(
    stream: TokenStream,
) -> ast.TriggerEvent | None:
    """``a player taps <land phrase> for mana`` — the event, or None.

    The active-voice spelling of ``land_tapped_for_mana``, which
    ``_WHENEVER_EVENTS`` carries only in its unnarrowed form ("a player taps a
    land for mana", Manabarbs): that table matches literal words and has no
    slot for the noun phrase Winter's Night prints. The same words are already
    read one module up for the *delayed* spelling of this ability
    (``delay_openers._parse_land_tapped_for_mana``, Chaos Moon's odd branch); this
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




def _parse_matched_event(
    stream: TokenStream, word: str
) -> "ast.TriggerEvent | None":
    """The condition clause after a trigger word, whichever word was printed.

    **The word is not part of the event.** CR 603.1 makes "when" and "whenever"
    one kind of triggered ability; the difference is how often it triggers
    while it exists, and every fire site in this engine reads the condition's
    *kind*. This body used to sit inside the ``whenever`` branch, so the whole
    of it — every narrowed cast, every subject-led entry, every quantified noun
    phrase — was unreachable from a card that printed the other word. Two
    Weatherlight cards found it: "**When** another creature enters" (Timid
    Drake) and "**When** an opponent casts a creature spell" (Straw Golem) were
    both refused while the same clauses under "whenever" were read, and
    ``engine/oracle.py``'s regex table reads both words for either — so what
    the two front ends disagreed about was not the condition but which cards
    have one at all.

    The ``when`` branch keeps its own readers in front of this, because they
    are the specific ones: "this creature dies" and the state triggers are
    printed with that word, and the phrase table this ends with would not have
    reached them any faster.
    """

    # CR 603.8's state trigger, under the other printed word ("Whenever
    # there are four or more tide counters on this creature", Homarid).
    # First, because "there" is not a subject and every branch below this
    # one expects one.
    state = _parse_state_trigger_event(stream, word)
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
                        "counters_put_on_creature", word, subject=filt,
                    )
    stream.reset(mark)
    cast = _parse_cast_event(stream, word)
    if cast is not None:
        return cast
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
                "matching_permanent_enters", word, subject=entering,
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
                    return ast.TriggerEvent(kind, word, subject=subject)
            stream.reset(counted)
            subject = parse_subject_filter_at(stream)
            if subject is not None:
                return ast.TriggerEvent(kind, word, subject=subject)
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
                    "attackers_declared", word, subject=subject
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
                    "attackers_declared", word, subject=subject
                )
    stream.reset(mark)
    # "Whenever **all** non-Wall creatures you control attack" (Mob
    # Mentality). The declaration again, asked as a comparison of two sets
    # rather than as a count — and printed in the other word order, with
    # the verb after the noun phrase instead of before it. The verb is
    # required, so a sentence that merely opens "all <noun phrase>" leaves
    # its tokens unconsumed and falls through rather than being claimed as
    # a trigger on a combat it never mentions.
    if stream.accept_word("all"):
        subject = parse_subject_filter_at(stream, plural=True)
        if subject is not None and stream.accept_word("attack"):
            return ast.TriggerEvent(
                "attackers_declared", word, subject=subject
            )
    stream.reset(mark)
    # "Whenever **one or more creatures attack you**." (Orim's Prayer.) The
    # declaration read from CR 506.2's defending side, and the third printed
    # word order for it: the count comes first, the noun phrase second and the
    # verb last. "you" is required — without it the sentence is a declaration
    # nobody in particular is defending against, which is a different trigger,
    # and leaving the word unread is the silent widening this table's
    # neighbours already document.
    count = _accept_number(stream)
    if count is not None and stream.accept_phrase("or", "more"):
        subject = parse_subject_filter_at(stream, plural=True)
        if subject is not None and stream.accept_phrase("attack", "you"):
            return ast.TriggerEvent("attackers_declared", word, subject=subject)
    stream.reset(mark)
    if stream.accept_phrase("this", "creature", "and", "at", "least"):
        count = _accept_number(stream)
        if count is not None and stream.accept_phrase("other", "creatures", "attack"):
            return ast.TriggerEvent("attackers_declared", word)
    stream.reset(mark)
    # The two named-subject tap events (Artifact Possession, Psychic Venom,
    # City of Brass, Spirit Shackle). Read before the phrase table, whose
    # entries would claim their prefixes.
    # The activation event whose subject is the *ability's* permanent
    # rather than the sentence's opening noun (Imprison). Before the tap
    # productions for the same reason they sit before the phrase table:
    # "a player activates …" would otherwise be read as a quantified
    # subject and named a condition the legacy table does not.
    activated = _parse_ability_activated_event(stream, word)
    if activated is not None:
        return activated
    attached = _parse_attached_event(stream, word)
    if attached is not None:
        return attached
    named_tap = _parse_named_subject_tap_event(stream, word)
    if named_tap is not None:
        return named_tap
    damage = _parse_damage_dealt_event(stream, word)
    if damage is not None:
        return damage
    for kind, phrase in _WHENEVER_EVENTS:
        if accept_event_phrase(stream, phrase):
            return ast.TriggerEvent(kind, word)
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
    # "Whenever **a spell or ability an opponent controls causes** a land to be
    # put into your graveyard from the battlefield" (Sacred Ground). The same
    # event with a causation clause in front of it, so the words are consumed
    # here and the narrowing rides `engine/oracle.py`'s condition payload —
    # exactly as "whose graveyard" does below. Consumed rather than skipped: a
    # production must take every token of its line or refuse it.
    caused = stream.accept_phrase(
        "a", "spell", "or", "ability", "an", "opponent", "controls", "causes"
    )
    # "When **the** creature put onto the battlefield with this enchantment
    # dies" (Diabolic Servitude). The definite article beside the indefinite
    # ones, read for ``phrases.parse_subject_filter_at``'s reason and under its
    # guard: "the" names one described object, so the description behind it has
    # to identify one. A bare "the creature" would otherwise read as "a
    # creature" and the trigger would watch every creature on the table.
    definite = bool(stream.accept_word("the")) if not stream.at_word(
        "a", "an"
    ) else False
    stream.accept_word("a", "an")
    try:
        dying = parse_object_filter(stream)
    except GrammarError:
        dying = None
    if definite and (dying is None or not _identifies_one_object(dying)):
        dying = None
    # "…is put into **a**/**your**/**an opponent's** graveyard from the
    # battlefield". Whose graveyard is a narrowing on the condition, which
    # this front end does not carry — `engine/oracle.py`'s table supplies the condition and this
    # one supplies the effect. The word still has to be *consumed* or the
    # line fails full-token consumption and the card loses its ability.
    dying_grave = (
        # "…**to be** put into your graveyard…" — the infinitive the causation
        # clause above puts the verb into. One reading of one event, so it is a
        # spelling here rather than a production of its own.
        (
            caused
            and (
                stream.accept_phrase(
                    "to", "be", "put", "into", "a", "graveyard", "from", "the",
                    "battlefield",
                )
                or stream.accept_phrase(
                    "to", "be", "put", "into", "your", "graveyard", "from",
                    "the", "battlefield",
                )
                or stream.accept_phrase(
                    "to", "be", "put", "into", "an", "opponent", "'s",
                    "graveyard", "from", "the", "battlefield",
                )
            )
        )
        or stream.accept_phrase(
            "is", "put", "into", "a", "graveyard", "from", "the", "battlefield"
        )
        or stream.accept_phrase(
            "is", "put", "into", "your", "graveyard", "from", "the", "battlefield"
        )
        or stream.accept_phrase(
            "is", "put", "into", "an", "opponent", "'s", "graveyard",
            "from", "the", "battlefield"
        )
        # CR 700.4: "dies" **means** "is put into a graveyard from the
        # battlefield". "Whenever a creature **with shadow** dies" (Dauthi
        # Ghoul) is the same event as the three spellings above with the rule's
        # own shorthand, so it belongs in this production rather than in one of
        # its own — a second production reading a second spelling of one event
        # is how the two come to carry different narrowings.
        #
        # Safe *here* rather than earlier because this production already sits
        # after the phrase table (see the comment above it): every fixed-word
        # death this front end knows — "this creature dies", "equipped creature
        # dies", "a creature you control dies" — is claimed there and never
        # reaches the noun parser above.
        or stream.accept_word("dies")
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
        return ast.TriggerEvent("permanent_dies", word, subject=dying)
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
                "revealed_drawn_card", word, subject=revealed
            )
    stream.reset(reveal_mark)
    batch_mark = stream.mark()
    if stream.accept_phrase("one", "or", "more"):
        batched = parse_subject_filter_at(stream, plural=True)
        if batched is not None and stream.accept_phrase(
            "deal", "combat", "damage", "to", "a", "player"
        ):
            return ast.TriggerEvent(
                "one_or_more_deal_combat_damage", word, subject=batched
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
        # "Whenever **a creature** becomes blocked by **a creature with lesser
        # power**" (No Quarter). A second noun phrase after the verb, which the
        # table loop below cannot read — so it is a production, and it is tried
        # first because its verbs are ones that loop has no row for and a
        # sentence it half-read would fail on the tail.
        pair = _accept_board_wide_block_event(stream, word, subject)
        if pair is not None:
            return pair
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
                return ast.TriggerEvent(kind, word, subject=subject)
    stream.reset(mark)
    return _parse_quantified_tap_event(stream)


def _accept_board_wide_block_event(
    stream: TokenStream, word: str, combatant: "ast.ObjectFilter"
) -> "ast.TriggerEvent | None":
    """``<noun phrase> becomes blocked by <noun phrase>`` and its blocking twin,
    with the *combatant* noun phrase already read.

    No Quarter's two lines, and the whole of what makes them board-wide: the
    creature the event is about is a printed phrase rather than "this creature"
    or "enchanted creature", so the source is in no combat at all and both
    halves of CR 509.1a's pair have to be described.

    **Which phrase is the subject is the convention, not a choice.** The
    source-scoped rows one table up put the *partner* on ``subject`` — "whenever
    this creature becomes blocked by a creature without flanking" carries the
    blocker there — so these do too, and the combatant travels as the
    ``combatant`` narrowing under the same stem
    ``engine/oracle.py``'s ``combatant_subject`` group gives it.
    ``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides`` is what
    holds the two front ends to that pairing.

    Refuses without consuming when the words after the noun phrase are anything
    else, so the subject-led table behind it is untouched.
    """
    for phrase, kind in _BOARD_WIDE_BLOCK_EVENTS:
        mark = stream.mark()
        if not stream.accept_phrase(*phrase):
            continue
        partner = parse_subject_filter_at(stream)
        if partner is not None:
            return ast.TriggerEvent(
                kind, word, subject=partner,
                narrowings=(("combatant", combatant),),
            )
        stream.reset(mark)
    # "Whenever **a creature** blocks, …" (Heat of Battle); "Whenever **a
    # Sliver** becomes blocked, …" (Spined Sliver). The same two events with no
    # partner phrase, which is CR 509.3c/509.3d's other half rather than a
    # missing narrowing — see :data:`_BARE_BOARD_WIDE_BLOCK_EVENTS`.
    #
    # The combatant goes on ``subject`` and carries no ``combatant`` narrowing
    # beside it, because with no second phrase there is nothing to tell apart:
    # the table's own ``combatant_subject`` group is then the *only* filter the
    # condition carries, so the two front ends pair it as the subject.
    for phrase, kind in _BARE_BOARD_WIDE_BLOCK_EVENTS:
        mark = stream.mark()
        if stream.accept_phrase(*phrase):
            return ast.TriggerEvent(kind, word, subject=combatant)
        stream.reset(mark)
    return None


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        return _parse_matched_event(stream, "whenever")
    if stream.accept_word("at"):
        attached_step = _parse_attached_step_event(stream, "at")
        if attached_step is not None:
            return attached_step
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        # "…dies **during combat**" (Mongrel Pack). Read before the bare
        # spelling it extends, for this file's standing ordering rule: matched
        # there, the two extra words are left on the stream and the line fails
        # full-token consumption — which is the *safe* half of the failure. The
        # unsafe half is on the regex side, where an unanchored bare row reads
        # them as nothing at all.
        #
        # The narrowing itself is `engine/oracle.py`'s payload and the death
        # fire site's to enforce; what is owed here is reading the same
        # sentence, so a line one front end claims is not a card the other
        # refuses.
        if accept_event_phrase(stream, ("this", "creature", "dies", "during", "combat")):
            return ast.TriggerEvent("dies", "when")
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
        #
        # The permanent noun and the article are both read rather than fixed.
        # Lich prints "**this enchantment** … into **a** graveyard", and with
        # neither spelling here the subject-led death production below claimed
        # it as `permanent_dies` — a *different* fire site, watching every
        # permanent that matches a filter rather than this one's own death.
        # CR 404.1 sends a permanent to its owner's graveyard, so "a" and
        # "your" name one pile for a card its controller owns.
        for noun in _DAMAGER_NOUNS:
            for article in ("your", "a"):
                if accept_event_phrase(stream, (
                    "this", noun, "is", "put", "into", article, "graveyard",
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
        # "**When** enchanted creature is dealt damage, destroy it." (Mortal
        # Wound.) Blight's argument one production over, and the asymmetry it
        # closes was invisible from either side alone: `engine/oracle.py`'s
        # table reads this condition under **both** printed words — it falls
        # back to the whenever table for any "when" line — while this front end
        # read it under one. So the condition parsed, the *effect* behind it
        # did not, and the card compiled with a trigger whose clause had no
        # instruction. CR 603.1 makes the two words one kind of ability; how
        # often it triggers while it exists is not something a fire site reads.
        attached = _parse_attached_event(stream, "when")
        if attached is not None:
            return attached
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
        # counter removal is one event whoever performed it (CR 122.1), and the
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
        # "When **this card is put into your graveyard from your library**"
        # (Gaea's Blessing). CR 113.6k: a trigger condition that cannot trigger
        # from the battlefield functions in every zone it can trigger from, and
        # this one names a move a permanent cannot make — so it watches the
        # card wherever it is. Read on this front end too, for the reason every
        # condition around it is: a condition only one of them sees leaves the
        # other refusing the effect behind it.
        if stream.accept_phrase(
            "this", "card", "is", "put", "into", "your", "graveyard",
            "from", "your", "library",
        ):
            return ast.TriggerEvent(
                "self_put_into_graveyard_from_library", "when"
            )
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
        # "When **an opponent** controls a creature with power 4 or greater"
        # (Hidden Predators) is the same condition asked of another seat, and
        # the seat is payload on ``engine/oracle.py``'s row rather than a kind
        # of its own; this side has only to read the words. Both spellings in
        # one branch, so a card printing either gets the same noun parser.
        mark_controls = stream.mark()
        if stream.accept_phrase("you", "control") or stream.accept_phrase(
            "an", "opponent", "controls"
        ):
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
        # branch already reads, printed with the one-shot word. CR 603.1 makes
        # the two words one kind of ability; the difference is how often it
        # triggers while it exists, not what triggers it, and every fire site in
        # this engine reads the kind rather than the word.
        #
        # So the **whole** reader is asked here rather than a hand-written
        # subset of it. It used to be the phrase table alone, which is one
        # subset smaller than the last one this line held ("blocks", which was
        # why Elder Land Wurm's condition read and Time Elemental's did not) —
        # and every clause that carries a *noun phrase* was still out of reach:
        # a narrowed cast, a subject-led entry, a quantified tap. Timid Drake
        # ("When another creature enters") and Straw Golem ("When an opponent
        # casts a creature spell") are the two Weatherlight cards that name it,
        # and `engine/oracle.py`'s regex table reads both words for either — so
        # the disagreement was never about the condition, only about which
        # cards have one.
        return _parse_matched_event(stream, "when")
    return None
