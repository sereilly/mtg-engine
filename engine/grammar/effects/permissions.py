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

Both definitions moved byte-identically, so no card's compiled program moves —
which is the only thing a parse-side split can get wrong, and it can get it
wrong only by renaming a lowering **category**. Nothing here has one: a
category names the migration family a *kind* belongs to, and no kind changed
hands.
"""

from .. import ast
from ..phrases import _parse_duration
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
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="exiled_this_way", grantee=grantee,
            until_end_of_turn=until_eot,
            until_source_grants_again=regrant,
            until_your_next_upkeep=next_upkeep,
            until_your_next_turn=next_turn,
            while_exiled=while_exiled,
        )
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
