"""Parsing **permission** sentences (CR 601.3) — "you may cast/play from …".

Split off ``effects/cards.py`` at Exodus' first wave, when Manabond's
reveal-and-empty template took that module to the thousand-line guard. The name
is not new: ``lowering/permissions.py`` has carried this family since Alliances'
third wave, split out of ``lowering/exile.py`` on the CR's own line —
everything in ``exile`` **moves an object** between zones (CR 406), and a
permission moves nothing at all. It grants a player leave to do something the
rules alone would not allow, and the objects it names are wherever they already
were. So this is the mirror re-forming rather than a new family: one home per
side, under one name.

That is also the line inside ``cards``. Every other production there is a card
**moving** — drawn, discarded, milled, searched out, revealed — and these two
move nothing: they read who may cast what, out of which zone, for how long. The
call graph had already fallen apart along it. ``_parse_cast_permission`` is
reached from the statement dispatcher and from nothing else, and
``_accept_spell_type_union`` is reached from ``_parse_cast_permission`` and from
nothing else; neither is called by anything left behind, and neither calls
anything left behind.

**And the withholding half arrived at Mercadian Masques' third Phase 0**, when
``effects/game.py`` sat eight lines under the guard. Five productions came over:
"can't play lands" (CR 305.1), "can't cast ⟨types⟩ spells", "can't activate
abilities that aren't mana abilities", the bound-permanent activation ban and
the targeting ban (CR 115.2). They are this file's own question with the sign
flipped — who may do what — and ``game``'s docstring had never listed them,
which is the tell that they were somebody else's subject sitting in the nearest
module.

They are **not** ``prohibitions``, and that name was the first answer here
before the collision was checked: ``lowering/prohibitions.py`` is "can't be
blocked / can't be regenerated", a restriction on what may be done **to** a
permanent, and naming a second module for what a *player* may not do would put
one word on two subjects in mirror positions — the duplicate-idea hazard, which
no textual guard can see. A permission granted and a permission withheld are
one family, so they get one home.

**Idol of Endurance's grant came home at Prophecy's Phase 0**, from
``paragraphs``, where it had sat beside the Idol's exile since Antiquities.
"You may cast a creature spell from among cards exiled with this artifact" is
one sentence and a CR 601.3 permission — ``ast.CastFromExiledWith`` says so,
``lowering/permissions.py`` had always lowered it, and ``statements`` tries it
immediately in front of :func:`_parse_cast_permission`, as the narrower
spelling of the same grant. ``paragraphs``' docstring opened "every production
here reads *several sentences*"; this read one, and its subject was this
module's. It is imported from here by name rather than through the package's
front door, so its one caller says where it lives.

Every arrival moved byte-identically, so no card's compiled program moves —
which is the only thing a parse-side split can get wrong, and it can get it
wrong only by renaming a lowering **category**. Nothing here has one: a
category names the migration family a *kind* belongs to, and no kind changed
hands.
"""

from ...library_top import REVEALED_TEXT
from .. import ast
from ..errors import GrammarError
from ..lexer import SELF
from ..nouns import parse_object_filter
from ..durations import _parse_duration
from ..phrases import _parse_zone
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES, singular as _singular


def _accept_spell_type_union(stream: TokenStream) -> "tuple[str, ...] | None":
    """``instant and sorcery`` / ``creature`` in front of the word "spells",
    consumed — or None with the cursor where it was.

    A **cross-type union**, which is why it is read here rather than by the
    noun parser: that reader answers "instant and sorcery **cards**" already,
    and the word a permission sentence prints is "spells". CR 112.1 makes a
    spell a card on the stack, so the two nouns name the same characteristics
    and only the zone differs — but a permission's zone is stated separately
    ("from the top of your graveyard"), so folding the two would give the
    sentence two answers about where the card is.

    Both joining words are read. "Instant **and** sorcery spells" is a union
    despite the conjunction (no spell is both), exactly as "instant **or**
    sorcery card" is, and refusing one spelling would refuse the card that
    prints it for a grammatical accident.
    """
    mark = stream.mark()
    found: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or _singular(word) not in CARD_TYPES:
            break
        found.append(_singular(word))
        stream.advance()
        if stream.accept_word("and", "or"):
            continue
        break
    if not found or not stream.accept_word("spells"):
        stream.reset(mark)
        return None
    return tuple(found)


def _parse_cast_permission(stream: TokenStream) -> ast.Statement | None:
    """A sentence granting permission to cast or play from a zone the rules
    alone would not allow (CR 601.3) — see :class:`ast.CastPermission` for the
    printed forms. Returns None quietly on anything else, so "you may pay …"
    and the causative "you may have …" keep their own readings.

    The duration is read in both printed positions — a leading "Until end of
    turn," and a trailing "this turn" — because the two spellings scope the
    permission identically (CR 514.2 ends both at cleanup).

    The **subject** is read too. Almost every printing says "you may", which
    CR 601.3 gives to the ability's controller; Elkin Lair says "**The player**
    may play that card this turn", where the player is whoever the trigger in
    front of it was about. Dropping the printed subject would hand the
    permission to the wrong seat on three upkeeps in four, silently — the grant
    would exist and the card would be playable, just not by the player who
    exiled it.
    """
    mark = stream.mark()
    until_eot = False
    next_upkeep = False
    next_turn = False
    if stream.at_word("until"):
        # Through the shared duration table, so the phrase this sentence may
        # open with is the same set of phrases every other effect reads — a
        # second literal here is how one family comes to accept a wording
        # another refuses. A kind the permission cannot *end* refuses the line
        # rather than being read as the nearest one it can.
        leading = _parse_duration(stream)
        if leading.kind == "until_end_of_turn":
            until_eot = True
        elif leading.kind == "until_your_next_upkeep":
            next_upkeep = True
        elif leading.kind == "until_your_next_turn":
            # "**Until your next turn**, you may play those cards." (Three
            # Wishes.) One step earlier than the upkeep spelling above, and
            # kept apart from it for that reason — see
            # :attr:`ast.CastPermission.until_your_next_turn`.
            next_turn = True
        else:
            stream.reset(mark)
            return None
        stream.accept_punct(",")
    grantee: "ast.PlayerRef | None" = None
    if not stream.accept_phrase("you", "may"):
        # "**The player** may play that card this turn." (Elkin Lair.) Through
        # the shared player-reference parser, which declines without consuming,
        # so a sentence that is not a permission at all still reaches its own
        # refusal site. Only a seat the *firing event* can name is read here:
        # "you" is the branch above, and any other reference would be a
        # permission granted to somebody the resolution cannot identify.
        named = parse_player_ref(stream)
        if named is None or named.kind != "that_player" or not stream.accept_word("may"):
            stream.reset(mark)
            return None
        grantee = named
    if stream.accept_word("play"):
        mode = "play"
    elif stream.accept_word("cast"):
        mode = "cast"
    elif stream.accept_phrase("look", "at"):
        # "You may **look at** it for as long as it remains exiled." (Gustha's
        # Scepter.) The same CR 611.2a permission sentence about a different
        # verb: a card in exile face down is hidden from every player (CR
        # 406.3), so the permission to read one is an effect rather than a
        # courtesy. "at" is consumed here because the verb is two words; the
        # referent and the duration below are shared with the cast readings.
        mode = "look"
    else:
        stream.reset(mark)
        return None

    regrant = False
    while_exiled = False

    def _trailing_duration() -> bool:
        nonlocal until_eot, regrant, while_exiled
        # "…**for as long as it remains exiled**." (Ice Cauldron.) A duration
        # stated as a zone rather than as a moment in the turn, which is why it
        # is not in the shared duration table: that table is read by every
        # effect family and none of the others can end on where a card is.
        # "…**for as long as they remain exiled**" (Three Wishes) is the same
        # duration over a pile rather than over a card. Read here beside the
        # singular rather than as a second production: the plural is the
        # referent's number, and the permission ends on the same event either
        # way.
        if stream.accept_phrase(
            "for", "as", "long", "as", "it", "remains", "exiled"
        ) or stream.accept_phrase(
            "for", "as", "long", "as", "they", "remain", "exiled"
        ):
            while_exiled = True
            return True
        if stream.accept_phrase("this", "turn"):
            until_eot = True
        # "until you exile another card with this <permanent type>" (Furious
        # Rise). The noun is whatever the card is printed as, so it is consumed
        # as a word rather than matched against one spelling — an Artifact
        # printing the same sentence needs no second branch. Every token is
        # consumed or the phrase is not this one, because a half-read duration
        # would leave "with this enchantment" as unaccounted text and fail the
        # whole line.
        elif stream.accept_phrase("until", "you", "exile", "another", "card"):
            if not stream.accept_phrase("with", "this"):
                raise stream.error("expected 'with this <permanent>'")
            if stream.exhausted or stream.at_punct(".", ";"):
                raise stream.error("expected the permanent this sentence is on")
            stream.advance()
            regrant = True
        return True

    # "cards exiled this way" / "them" — both name the cards a step of this
    # same resolution exiled; lowering demands the producer.
    # "cards exiled this way" / "them" / "that card" — all name the cards a step
    # of this same resolution exiled; lowering demands the producer. The
    # singular is the same set with one member in it (Furious Rise exiles the
    # top card, so "that card" is the whole of what was exiled), which is why it
    # is a spelling here rather than a second ``what``.
    if (
        stream.accept_phrase("cards", "exiled", "this", "way")
        or stream.accept_word("them")
        or stream.accept_phrase("that", "card")
        # "**those cards**" (Three Wishes) — the plural of "that card", and the
        # same set: what an earlier step of this resolution exiled. A spelling
        # here rather than a second ``what``, for the singular's stated reason
        # one number over.
        or stream.accept_phrase("those", "cards")
        # The bare pronoun, and only under "look at": a *cast* permission
        # naming "it" would claim any "you may cast it …" sentence in the pool,
        # where this verb has exactly one referent — the card the sentence
        # before it exiled.
        or (mode == "look" and stream.accept_word("it"))
    ):
        # "…**without paying its mana cost**." (Temporal Aperture.) CR 118.9's
        # waiver over a named card, which is the same ``free`` flag the blanket
        # hand waiver below already sets — and required to be read here rather
        # than left as unconsumed text, because a permission that dropped the
        # words would make the player pay for a card the effect gave away.
        # Singular, and beside the plural spelling for the referent's own
        # reason: what differs is the number of cards named, not the rule.
        free = mode != "look" and bool(
            stream.accept_phrase("without", "paying", "its", "mana", "cost")
            or stream.accept_phrase("without", "paying", "their", "mana", "costs")
        )
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="exiled_this_way", grantee=grantee, free=free,
            until_end_of_turn=until_eot,
            until_source_grants_again=regrant,
            until_your_next_upkeep=next_upkeep,
            until_your_next_turn=next_turn,
            while_exiled=while_exiled,
        )
    # "you may **play lands and cast spells** from your graveyard."
    # (Yawgmoth's Will.) Two verbs and two nouns for one permission: CR 305.1
    # plays a land and CR 601.2 casts a spell, and "play" is the word that
    # covers both — which is exactly what ``CastPermission.mode == "play"``
    # already means, so the compound is one grant rather than two.
    #
    # Read here, right after the verb, because it is the *second* verb that
    # makes this sentence itself: every reading below opens on a noun, and the
    # union reader among them would take "lands" and then fail on "and cast".
    # Refuses without consuming, like every arm around it.
    if mode == "play":
        both_mark = stream.mark()
        if stream.accept_phrase("lands", "and", "cast", "spells", "from"):
            zone_of = _parse_zone(stream)
            if zone_of.name in ("graveyard", "exile") and (
                zone_of.owner is not None and zone_of.owner.kind == "you"
            ):
                _trailing_duration()
                return ast.CastPermission(
                    mode="play", what="spells_from_zone", grantee=grantee,
                    card_types=(), zone=zone_of.name, position=None,
                    until_end_of_turn=until_eot,
                    until_your_next_upkeep=next_upkeep,
                    until_your_next_turn=next_turn,
                )
        stream.reset(both_mark)
    # "spells from your hand without paying their mana costs" — a cost waiver.
    # The waiver clause is required: a bare "you may cast spells from your
    # hand" states the rules default and no card prints it.
    if stream.accept_phrase("spells", "from", "your", "hand"):
        if not stream.accept_phrase("without", "paying", "their", "mana", "costs"):
            stream.reset(mark)
            return None
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="spells_from_hand", grantee=grantee,
            until_end_of_turn=until_eot, free=True,
            until_your_next_upkeep=next_upkeep,
            until_your_next_turn=next_turn,
        )
    # A **blanket** grant over a class of spells rather than over named cards:
    # "instant and sorcery spells from the top of your graveyard" (Bosium
    # Strip) and "creature spells this turn as though they had flash" (Winding
    # Canyons). One reader for the noun phrase, because the two sentences print
    # the same union and differ only in what follows it — a zone in one and a
    # timing permission in the other.
    named_types = _accept_spell_type_union(stream)
    if named_types is not None:
        # "…from **the top of** your graveyard." One card, not the pile: read
        # here rather than left to the noun parser because the phrase is a
        # *position* in an ordered zone (CR 400.5) rather than a
        # characteristic, and a permission that dropped it would open the whole
        # graveyard.
        if stream.accept_phrase(
            "from", "the", "top", "of", "your", "graveyard"
        ):
            _trailing_duration()
            return ast.CastPermission(
                mode=mode, what="spells_from_zone", grantee=grantee,
                card_types=named_types, zone="graveyard", position="top",
                until_end_of_turn=until_eot,
                until_your_next_upkeep=next_upkeep,
                until_your_next_turn=next_turn,
            )
        # "…**this turn** as though they had flash." CR 702.8a timing rather
        # than a zone: the duration is printed in front of the permission, so
        # the shared trailing reader runs first and the words after it decide
        # which sentence this is.
        _trailing_duration()
        if stream.accept_phrase("as", "though", "they", "had", "flash"):
            return ast.CastPermission(
                mode=mode, what="spells_at_instant_speed", grantee=grantee,
                card_types=named_types,
                until_end_of_turn=until_eot,
                until_your_next_upkeep=next_upkeep,
                until_your_next_turn=next_turn,
            )
        # A union nothing followed is not this sentence. Reset rather than
        # raise: "you may cast creature spells" alone is not a permission any
        # card prints, and consuming the words would take the line away from
        # whatever production really reads it.
        stream.reset(mark)
        return None
    # "target red instant or sorcery card from your graveyard" — the noun
    # parser reads the zone and its owner onto the filter, and lowering
    # refuses any zone the cast path cannot open.
    spec = parse_target_spec(stream)
    if spec is not None and spec.quantifier == "target":
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="target_card", target=spec, grantee=grantee,
            until_end_of_turn=until_eot,
            until_your_next_upkeep=next_upkeep,
            until_your_next_turn=next_turn,
        )
    stream.reset(mark)
    return None


#: "Play with the top card of your library revealed", in the tokens the grammar
#: reads it in — **derived from the implementing module's own sentence**
#: (``engine/library_top.REVEALED_TEXT``) rather than spelled again here.
#:
#: One printed sentence, two front ends: a permanent printing it is a static
#: ``library_top`` reads off that permanent's text and this production never
#: sees, and an ability *granting* it is this production. A second literal is
#: how the two come to disagree, and the direction it disagrees in is a card
#: the support gate claims and the parser refuses.
_TOP_REVEALED_PHRASE = tuple(REVEALED_TEXT.split())


def _parse_play_with_top_revealed(
    stream: TokenStream,
) -> "ast.PlayWithTopRevealed | None":
    """``Play with the top card of your library revealed.`` — the permission as
    an **effect** rather than as a permanent's static ability.

    CR 400.2 makes the top card a public object. Conspicuous Snoop and Field of
    Dreams print the same words as statics, and ``engine/library_top.py`` reads
    those off the permanent for as long as it is there; nothing could *grant*
    the permission until this production existed, because the grammar refused
    the sentence outright ("expected a subject") — the verb is "play", whose
    object is a zone rather than anything a noun reader can take.

    A bare imperative, so its subject is the effect's controller (CR 608.1),
    which is also what the printed "your" says. The durations arrive from the
    clauses in front of the sentence — ``_distribute_duration`` fills the
    swept one and ``_link_leading_duration`` the re-asked one — and the
    lowering refuses a grant that ended up with neither, because an unbounded
    reveal is a different card.

    **Reached from one caller and deliberately not from the sentence reader.**
    ``sentence_clauses._parse_leading_linked_duration`` calls it after
    consuming "for as long as that card remains on top of your library,", and
    nothing else does. The rule is ``_parse_play_with_hand_revealed``'s, one
    zone over: the bare sentence is a *static* another module claims off a
    permanent's printed line (``library_top.library_top_line``), and a
    production the ordinary reader could reach would parse Conspicuous Snoop's
    line and take that claim away — parsed-but-unlowered is still parsed.
    Behind a clause that has already been consumed, the words can only be a
    grant.

    Refuses without consuming even so, so a caller that mis-guesses gets its
    own refusal rather than this one's.
    """
    mark = stream.mark()
    if not stream.accept_phrase(*_TOP_REVEALED_PHRASE):
        stream.reset(mark)
        return None
    return ast.PlayWithTopRevealed(ast.PlayerRef("you"))


def _parse_cast_from_exiled_with(stream: TokenStream) -> ast.Statement | None:
    """``Until end of turn, you may cast a <filter> spell from among cards
    exiled with this <permanent> without paying its mana cost.``
    (Idol of Endurance.)

    The cost waiver is required: without it the permission is a different one
    and strictly weaker, and a card that dropped the words would be cheaper to
    misread than to notice.
    """
    if not stream.accept_phrase("until", "end", "of", "turn"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "may", "cast", "a"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        return None
    # ``parse_object_filter`` reads "creature spell" whole, marking the zone as
    # the stack. Requiring the word back would be asking it twice; requiring the
    # *zone* is what actually distinguishes "cast a creature spell" from a card
    # filter that would name some other zone.
    if filt.zone != "stack":
        return None
    if not stream.accept_phrase("from", "among", "cards", "exiled", "with", "this"):
        return None
    if stream.accept_kind(SELF) is None:
        # The noun is **required**, not merely accepted: without it the sentence
        # still matched and the word could be deleted with no change to what was
        # lowered, which is exactly what the parse-coverage deletion probe is
        # for. A card naming itself gets the SELF token instead.
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "permanent", "land"
        ):
            return None
    if not stream.accept_phrase(
        "without", "paying", "its", "mana", "cost",
    ):
        return None
    return ast.CastFromExiledWith(filt)


def parse_cant_play_lands(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.CantPlayLands | None":
    """``… can't play lands this turn.`` (Solfatara.) The verb only — the
    subject has already been read by the caller.

    CR 305.1's permission withdrawn from one seat for one turn, and the mirror
    of :func:`parse_extra_land_plays`. Non-consuming on refusal, because the
    ``can't`` dispatcher hands every other sentence on to the combat production
    and a consumed word there would replace its refusal with one naming a verb
    the line never printed.

    The duration is required for the same reason as above: "Players can't play
    lands" (Worms of the Earth) is a permanent's static ability read by
    ``engine/land_play_allowance.py``, and it prints no duration at all.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    mark = stream.mark()
    if not stream.accept_phrase("play", "lands"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind != "this_turn":
        stream.reset(mark)
        return None
    return ast.CantPlayLands(subject, duration)


#: The card types a printed "can't cast <types> spells" may name. The same list
#: ``cast_restrictions._BANNABLE_SPELL_TYPES`` holds one module over, and for
#: that list's reason: what a card may forbid is a card type, and a word outside
#: the type line describes nothing the gate can test.
_BANNABLE_CAST_TYPES = (
    "artifact", "creature", "enchantment", "instant", "sorcery",
    "planeswalker", "battle", "land",
)


def parse_cant_cast_spell_types(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.CantCastSpellTypes | None":
    """``… can't cast <type>[ or <type>]* spells.`` (Abeyance.) The verb only —
    the subject has already been read by the caller.

    CR 601.3's permission withdrawn from one named seat, the resolved-effect
    twin of the three board-scanned bans in ``engine/cast_restrictions.py``.

    Every type must be one the gate can test, and the list must be **exhausted
    by the word "spells"**: a phrase this reader could only half-consume would
    leave the rest as unconsumed text, which is the loud direction, rather than
    a ban narrower than the card prints.

    Non-consuming on refusal, because the ``can't`` dispatcher hands every other
    sentence on to the combat production and a consumed word there would replace
    its refusal with one naming a verb the line never printed — the arrangement
    ``parse_cant_play_lands`` above already documents.

    The **duration** is not read here. Abeyance prints it in front of the whole
    sentence, and ``sentence_clauses._distribute_duration`` attaches a leading
    prefix to the node afterwards; the lowering is what refuses a node that
    still has none, for ``CantPlayLands``' reason — a durationless "can't cast"
    is a permanent's static ability that ``cast_restrictions.py`` already reads.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    mark = stream.mark()
    if not stream.accept_word("cast"):
        stream.reset(mark)
        return None
    # "Target player **can't cast spells this turn**." (Orim's Chant.) The
    # sentence with no type printed at all: every spell, which the node says
    # with an empty type list (see :class:`ast.CantCastSpellTypes`).
    #
    # **The window is required here, in the parse**, where the typed spelling
    # leaves it to the lowering: "Players can't cast spells that share a color
    # with the spell most recently cast this turn" (Mana Maze) opens on these
    # same three words and is a permanent's static ability a derivation table
    # reads. A table is reached only where every production refuses the line
    # in full, so a reading that stopped after "spells" must not be offered
    # for a sentence that goes on — and the trailing duration is what tells
    # the one-shot from the static.
    if stream.accept_word("spells"):
        window = _parse_duration(stream)
        if window.kind != "this_turn":
            stream.reset(mark)
            return None
        return ast.CantCastSpellTypes(subject, (), window)
    types: list[str] = []
    while True:
        word = stream.peek_word()
        if word not in _BANNABLE_CAST_TYPES:
            stream.reset(mark)
            return None
        stream.advance()
        types.append(word)
        if not stream.accept_word("or"):
            break
    if not stream.accept_word("spells"):
        stream.reset(mark)
        return None
    return ast.CantCastSpellTypes(subject, tuple(types))


def parse_cant_activate_nonmana_abilities(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.CantActivateNonManaAbilities | None":
    """``… can't activate abilities that aren't mana abilities.`` (Abeyance.)
    The verb only — the subject has already been read by the caller.

    CR 602.5 for one named seat. Every word of the exception is required: "can't
    activate abilities" with the rest dropped is a prohibition that also stops
    the player tapping a Forest, which is a strictly larger card — and the
    exception names a **rule** (CR 605.1a) rather than a set the card chooses, so
    a different exception is a different sentence and refuses here.

    Non-consuming on refusal, for the reason its sibling above gives.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    mark = stream.mark()
    if stream.accept_phrase(
        "activate", "abilities", "that", "aren't", "mana", "abilities"
    ):
        return ast.CantActivateNonManaAbilities(subject)
    stream.reset(mark)
    return None


def _parse_bound_permanent_activation_ban(
    stream: TokenStream,
) -> "ast.BoundPermanentActivationBan | None":
    """``that permanent's activated abilities can't be activated <duration>``
    (Interdict), or None with the cursor exactly where it was.

    Read whole, with no payload in it, for :func:`_parse_targeting_ban`'s
    reason: every word is the rule. "Activated" is required — a ban with the
    word dropped would stop triggered and static abilities the card leaves
    alone — and the pronoun is required to be "that permanent", the restated
    noun phrase CR 113.7a forces on a spell that targeted an ability, because
    an ability has no card of its own to name.

    Refuses without consuming, so every other sentence opening on "that" keeps
    its reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "that", "permanent", "'s", "activated", "abilities",
        "can't", "be", "activated",
    ):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind == "none":
        # The trailing window is the whole of what makes this liftable; a
        # sentence without one is refused rather than read as "for ever",
        # which is the lowering's rule stated at the parse so the line fails
        # where the words are.
        stream.reset(mark)
        return None
    return ast.BoundPermanentActivationBan(duration)


def _parse_targeting_ban(stream: TokenStream) -> "ast.TargetingBan | None":
    """``players and permanents can't be the targets of spells or activated
    abilities [<duration>]`` (Peace Talks).

    CR 115.1 denied outright for a stated window. Read here rather than by the
    subject-verb table because the sentence's subject is *two* populations at
    once — a player and an object — and that reader carries one subject; a
    production per half would be two rules for one printed clause, and the half
    that arrived second would be free to disagree about the window.

    Refuses without consuming, so every other sentence opening with "players"
    keeps the reading it has. The clause is spelled out whole: this is one
    printed sentence with nothing in it that is payload, and a looser match
    would claim a narrowed printing ("players can't be the targets of **red**
    spells") and then ban more than the card does.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "players", "and", "permanents", "can't", "be", "the", "targets", "of",
        "spells", "or", "activated", "abilities",
    ):
        stream.reset(mark)
        return None
    # The trailing spelling of the window; Peace Talks prints the leading one,
    # which `sentence_clauses._distribute_duration` attaches to this node's
    # field afterwards. Both, because which end a card prints it on is not a
    # difference in the rule.
    return ast.TargetingBan(_parse_duration(stream))
