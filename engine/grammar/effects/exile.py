"""Cards moving **into and out of exile** (CR 406), and back again.

Split out of ``effects/cards.py`` at Alliances' third wave, when two branches
each grew that module under the 1,000-line guard and the sum crossed it — the
case SET_PLAYBOOK.md tells the integrator to split at rather than carry,
because no single branch is at fault and so no single branch would have split
it.

The name is ``lowering/exile.py``'s, which has been a lowering-only family
since before this file existed: the mirror re-forms rather than forking, which
is the rule ``effects/prevention.py`` and ``effects/counters.py`` were both
written under. What stayed in ``cards`` is what the module's own docstring
claims — a card *moving* between hand, library and graveyard; what came here
names the exile zone, and the two shared no production.

``ast/`` has no ``exile`` for the reason ``zones``, ``library`` and
``permissions`` already record: the guard fires on the readers, and these
nodes sit perfectly well beside the other card nodes.
"""

import dataclasses

from .. import ast
from ..errors import GrammarError
from ..phrases import _accept_self_reference, _parse_zone
from ..readers import _parse_entering_counters
from ..references import parse_player_ref, parse_recipient
from ..vocabulary import CARD_TYPES
from ..stream import TokenStream


def _parse_put_exiled_pile_top_into_hand(
    stream: TokenStream,
) -> "ast.PutExiledPileTopIntoHand | None":
    """``Put the top card of the exiled pile into its owner's hand.``
    (Mangara's Tome.)

    Read before the "that card" production below and refusing without
    consuming, like every other "put" reader here: the two open on the same
    verb and differ from the fourth word on, so the order decides which refusal
    survives rather than which card is read.

    "Its owner's" and "your" are both accepted because they name the same seat
    for every printing in the pool — the pile is made of cards their controller
    searched out of their own library — and refusing the second spelling would
    turn a wording difference into an unsupported card.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "put", "the", "top", "card", "of", "the", "exiled", "pile", "into"
    ):
        stream.reset(mark)
        return None
    if not (
        stream.accept_phrase("its", "owner", "'s", "hand")
        or stream.accept_phrase("your", "hand")
    ):
        stream.reset(mark)
        return None
    return ast.PutExiledPileTopIntoHand()


def _parse_put_exiled_card_into_hand(
    stream: TokenStream,
) -> "ast.PutExiledCardIntoZone | None":
    """``Put that card into your hand.`` (Necropotence.)

    Refuses without consuming, like every other "put" production beside it, so
    the counter reading keeps its own refusal site. "That card" is the one an
    earlier step of this same effect exiled; lowering demands the producer.

    Only the **hand** spelling, and only with "that card" as the referent. The
    node carries a zone now (Grinning Totem prints a graveyard), but widening
    *this* production to match would take "put it into your graveyard" away
    from :func:`_parse_put_source_into_zone`, which is All Hallow's Eve's
    sentence about its own source — one printed clause, two referents, and
    nothing in the words tells them apart. The other destination is read by
    :func:`_parse_bin_unplayed_exiled_card` below, whose condition clause is
    what binds the pronoun.
    """
    mark = stream.mark()
    stream.expect_word("put")
    if not stream.accept_phrase("that", "card", "into"):
        stream.reset(mark)
        return None
    zone = _parse_zone(stream)
    if zone.name != "hand" or zone.owner is None:
        stream.reset(mark)
        return None
    return ast.PutExiledCardIntoZone(zone)


def _parse_bin_unplayed_exiled_card(
    stream: TokenStream,
) -> "ast.PutExiledCardIntoZone | None":
    """``If you haven't played it, put it into its owner's graveyard.``
    (Grinning Totem, inside its delayed ability.)

    The condition and its consequent are **one** production rather than an
    ordinary conditional over a "put" sentence, because the condition is what
    says who "it" is. On its own, "put it into its owner's graveyard" is
    already a sentence this grammar reads — :func:`_parse_put_source_into_zone`
    takes it as the ability moving its own source (All Hallow's Eve) — and
    nothing in the remaining words distinguishes the two readings. Reading them
    together is the only place the pronoun has an antecedent: "you haven't
    played **it**" can only be about a card an earlier step of this same effect
    made playable, which is a card it exiled, and the lowering demands that
    producer.

    ``If the player hasn't played the card, they put it into their graveyard.``
    (Elkin Lair, inside its delayed ability.) The same sentence about a seat the
    trigger named rather than about the ability's controller — and *only* the
    condition and the possessive change, which is why it is a branch here and
    not a production of its own.

    The third printed spelling opens on the verb instead of on the condition and
    is read from the imperative chain — see
    :func:`_parse_bin_unplayed_exiled_cards`.

    Refuses without consuming, beside the other "If …" productions in
    ``statements.py`` and for their reason: every other conditional keeps the
    reading it has.

    The condition is not dropped. It is what the move already *is* — a card the
    player played is not in exile any more, and this instruction only moves a
    card out of exile — so it rides the node as a word rather than as a second
    test, and the handler's log says which case it took.
    """
    mark = stream.mark()
    if stream.accept_word("if"):
        # "you haven't played it" / "the player hasn't played the card". The
        # lexer keeps the contraction whole, so the negation is one word here
        # rather than the two-token spelling a possessive takes ("owner" + "'s")
        # a few lines down. The subject goes through the shared player parser,
        # which declines without consuming — and the *referent* is read the same
        # way whichever subject was printed, because "it" and "the card" name
        # the one thing an earlier step of this effect exiled.
        who = parse_player_ref(stream)
        if who is None or who.kind not in ("you", "that_player"):
            stream.reset(mark)
            return None
        if not stream.accept_word("haven't", "hasn't"):
            stream.reset(mark)
            return None
        if not (
            stream.accept_phrase("played", "it")
            or stream.accept_phrase("played", "the", "card")
        ):
            stream.reset(mark)
            return None
        stream.accept_punct(",")
        # "**they** put it into their graveyard" — the same seat again, named a
        # second time because the clause is a sentence of its own. Consumed and
        # dropped: which player performs the move decides nothing (CR 400.3
        # sends the card to its *owner's* graveyard whoever puts it there), and
        # refusing an unread subject is what the zone below already does.
        if stream.at_word("they", "you") and stream.peek_word(1) in ("put", "puts"):
            stream.advance()
        if not (
            stream.accept_phrase("put", "it", "into")
            or stream.accept_phrase("puts", "it", "into")
        ):
            raise stream.error(
                "expected what happens to the card that was not played"
            )
        return ast.PutExiledCardIntoZone(_bin_zone(stream), only_if_unplayed=True)
    stream.reset(mark)
    return None


def _parse_bin_unplayed_exiled_cards(
    stream: TokenStream,
) -> "ast.PutExiledCardIntoZone | None":
    """``Put any of those cards you didn't play into your graveyard.``
    (Three Wishes, inside its delayed ability.)

    The third printed spelling of :func:`_parse_bin_unplayed_exiled_card`, with
    the condition folded into the object phrase instead of stated in front of
    it, and a pile rather than a card. Its own production because it opens on
    the *verb*: it is reached from the imperative chain, where that one is
    reached from the "If …" gate, and one function would have to be tried from
    both.

    It is the same effect and lowers to the same instruction — what moves is
    whatever is still in exile, which is exactly "the ones you didn't play".

    Every word of the object phrase is required. "Put those cards into your
    graveyard" without it would bin the ones already played, which is a card
    nothing can be played out of at all — and it is the card these same four
    sentences would otherwise compile to.
    """
    mark = stream.mark()
    if not stream.accept_phrase("put", "any", "of", "those", "cards"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_phrase("you", "didn't", "play")
        and stream.accept_word("into")
    ):
        stream.reset(mark)
        return None
    return ast.PutExiledCardIntoZone(_bin_zone(stream), only_if_unplayed=True)


def _bin_zone(stream: TokenStream) -> "ast.Zone":
    """The destination of an unplayed exiled card, including "their graveyard".

    ``_parse_zone`` reads every possessive the pool prints but that one, and
    deliberately raises on an unrecognized one so a distinction cannot be lost
    by omission. "**They** put it into **their** graveyard" (Elkin Lair) is that
    possessive, and it is read here rather than added to the shared fragment
    because what it means is not general: it is the seat the *sentence in front
    of it* named, which only this production knows.

    It resolves to the **owner** either way, and that is CR 400.3 rather than a
    convenience — a card put into a graveyard goes to its owner's, whoever the
    sentence says is doing the putting. So one payload is right for all three
    printings, and the handler that locates the card in whichever exile holds it
    is already binning it into that seat's graveyard.
    """
    mark = stream.mark()
    if stream.accept_word("their"):
        if stream.accept_word("graveyard"):
            return ast.Zone("graveyard", ast.PlayerRef("owner"))
        stream.reset(mark)
    return _parse_zone(stream)


def _parse_exile_bound_card(stream: TokenStream) -> "ast.ExileBoundCard | None":
    """``Exile that card from your graveyard.`` (Necropotence.) /
    ``…exile that card.`` (Purgatory.)

    Refuses without consuming, like the other exile productions beside it, so
    an ordinary exile keeps its own refusal.

    The zone is **optional**, and the lowering is where the difference lands:
    with a zone the sentence names the pile it expects, without one it names
    the pile the firing event already said the card went to. Reading the
    zone-less form here rather than refusing it is safe because "that card" has
    no other referent — the recipient parser one production down reads
    permanents and chosen cards, so an unclaimed "exile that card" fails the
    whole line rather than matching something else.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_phrase("that", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_word("from"):
        return ast.ExileBoundCard(None)
    zone = _parse_zone(stream)
    return ast.ExileBoundCard(zone)


def _parse_exile_cost_sacrifices(stream: TokenStream) -> ast.Statement | None:
    """``Exile this <noun> and those <noun> cards.`` (Sword of the Ages.)

    Returns None quietly on anything else, like the two exile productions
    beside it, so an ordinary exile keeps its own refusal.

    Both halves are required. "Exile this artifact" alone is the source leaving
    the battlefield — a sentence the ordinary production already reads, and a
    different effect from this one, which reaches into a graveyard for a set the
    cost put there. Reading only the first half and stopping is what the
    ordinary production would do, so this is tried in front of it.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the source's own noun ("artifact")
    if not stream.accept_phrase("and", "those"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the sacrificed set's noun ("creature")
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    return ast.ExileCostSacrifices()


def _parse_exile_graveyard(stream: TokenStream) -> ast.Statement | None:
    """``Exile target player's graveyard.`` (Tormod's Crypt.)

    Returns None quietly on anything else, so the ordinary permanent exile keeps
    its own errors. The possessive and the zone noun are both expected: "exile
    target player" is not a sentence, and consuming the player and stopping
    would leave a production that exiles whatever the next reader assumes.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    # "Exile **all graveyards**." (Bazaar of Wonders.) Every pile at once, and
    # read before the possessive because "all" is not a player reference: the
    # reader below would refuse it and the sentence would die at a phrase this
    # production does read.
    if stream.accept_phrase("all", "graveyards"):
        return ast.ExileGraveyard(None)
    player = parse_player_ref(stream)
    if (
        isinstance(player, ast.PlayerRef)
        and player.kind in ("target_player", "target_opponent")
        and stream.accept_word("'s")
        and stream.accept_word("graveyard")
    ):
        return ast.ExileGraveyard(player)
    stream.reset(mark)
    return None


def _parse_put_exiled_with_source(stream: TokenStream) -> ast.Statement | None:
    """``Put all cards exiled with this artifact into their owner's hand.``
    (Knowledge Vault's ``{0}`` ability; its leaves-the-battlefield trigger says
    "exiled with **it** … into their owner's graveyard".)

    Returns None with the cursor untouched on anything else, because every
    other "put …" in the pool is counters or a card from a named zone, and this
    production has to be tried before them without being able to shadow them.

    The self-reference is required and consumed in full: "cards exiled with
    *this artifact*" is CR 610.3's linked pile, and a wording naming another
    permanent would be a different pile this cannot find.
    """
    mark = stream.mark()
    # Two printed verbs for one effect. Knowledge Vault says "**Put all cards**
    # exiled with this artifact **into** their owner's hand"; Safe Haven says
    # "**Return each card** exiled with this land **to** the battlefield under
    # its owner's control". Same linked pile (CR 610.3), same drain, same
    # handler — the difference is which zone the cards are going to and the
    # preposition English wants in front of it.
    names_source = True
    chosen = False
    owned_by_you = False
    others_only = False
    card_type: str | None = None
    if stream.accept_phrase("put", "all", "cards", "exiled", "with"):
        preposition = "into"
    elif stream.accept_phrase(
        "put", "all", "other", "cards", "you", "own", "exiled", "with",
    ):
        # "Put **all other cards you own** exiled with this enchantment into
        # your hand." (Duplicity.) The sweep above with both narrowings the
        # sentence prints, and both are required together because each is a
        # different half of one reading: "other" excludes the cards this same
        # ability exiled a sentence earlier — without it the enchantment hands
        # back what it has just taken away and the card does nothing at all —
        # and "you own" is what stops a player who has taken the enchantment
        # from pulling its previous controller's cards out of exile, exactly as
        # it does on Gustha's Scepter below.
        preposition = "into"
        others_only = True
        owned_by_you = True
    elif stream.accept_phrase("return", "each", "card", "exiled", "with"):
        preposition = "to"
    elif stream.accept_phrase("return", "all", "cards", "exiled", "with"):
        # "Return **all cards** exiled with it to the battlefield under their
        # owners' control." (Wall of Nets.) Safe Haven's sweep with the plural
        # quantifier English wants in front of a plural noun — "each card" and
        # "all cards" name the same pile (CR 610.3 gives the linked ability
        # exactly the objects its twin moved, and there is no subset for a
        # quantifier to pick out) — so it is a spelling of that branch rather
        # than a shape of its own, and it lowers through the same sweep.
        preposition = "to"
    elif stream.accept_phrase("return", "each"):
        # "Return **each creature card** exiled with this artifact to the
        # battlefield under your control." (Cold Storage.) The sweep above with
        # a card type printed on it, read here rather than as an optional word
        # inside that branch so the unnarrowed spelling keeps its exact reading
        # and this one refuses whole: a noun the vocabulary does not know leaves
        # the line unparsed rather than sweeping a pile the card never named.
        noun = stream.peek_word()
        if noun is None or noun not in CARD_TYPES:
            stream.reset(mark)
            return None
        stream.advance()
        if not stream.accept_phrase("card", "exiled", "with"):
            stream.reset(mark)
            return None
        card_type = noun
        preposition = "to"
    elif stream.accept_phrase("return", "a", "card", "you", "own", "exiled", "with"):
        # "…**a card you own** exiled with this artifact to your hand."
        # (Gustha's Scepter.) The same linked pile with a quantifier and a
        # restriction on it: one card, picked by the ability's controller, out
        # of the cards *they* own. Both are required together — "you own"
        # narrows nothing in a sweep, where every card goes to its own owner
        # anyway, and it is the whole of what stops a player who has taken the
        # artifact from pulling its previous controller's cards out of exile.
        preposition = "to"
        chosen = True
        owned_by_you = True
    elif stream.accept_phrase("return", "a", "card", "exiled", "with"):
        # "…**return a card** exiled with this enchantment **to the
        # battlefield**." (Purgatory.) Gustha's Scepter's shape with the "you
        # own" narrowing not printed, which is the whole difference: this pile
        # only ever holds cards its controller owns, because the ability that
        # filled it watches "**your** graveyard", so there is nothing for the
        # narrowing to exclude. Read after that spelling, whose first five
        # words this would otherwise consume before choking on "you".
        preposition = "to"
        chosen = True
    elif stream.accept_phrase("return", "the", "exiled", "card"):
        # "…**the exiled card**…" (Icy Prison). The same linked pile with no
        # possessive on it: CR 610.3 makes the two abilities linked, so "the
        # exiled card" is the one *this* permanent's other ability exiled and
        # can be nothing else. The definite article is doing the work the
        # phrase "exiled with this enchantment" does above, which is why the
        # self-reference below is not required here rather than optional —
        # there is no wording of this spelling that could name another pile.
        preposition = "to"
        names_source = False
    else:
        stream.reset(mark)
        return None
    if names_source and not (
        stream.accept_word("it") or _accept_self_reference(stream)
    ):
        stream.reset(mark)
        return None
    stream.expect_word(preposition)
    zone = _parse_zone(stream)
    # "…**under its owner's control**" (CR 400.3 spelled out, because a
    # battlefield has no possessive of its own to carry it). Read as the zone's
    # owner rather than dropped: the lowering *requires* an owner reference —
    # a linked pile goes to each card's own owner — so silently losing the
    # clause would refuse the line, and consuming it without recording it would
    # let a wording naming one player through.
    if zone.owner is None and zone.name == "battlefield" and (
        stream.accept_phrase("under", "its", "owner", "'s", "control")
        or stream.accept_phrase("under", "their", "owner", "'s", "control")
        # "…under **their owners'** control" (Wall of Nets). The plural
        # possessive, which the lexer keeps as one word because the apostrophe
        # trails the noun rather than separating it from an "s" — so it is a
        # third spelling here rather than a fifth token in the branch above.
        # The same clause and the same seat: CR 400.3 sends each card to its
        # own owner however many owners the pile has.
        or stream.accept_phrase("under", "their", "owners'", "control")
    ):
        zone = ast.Zone(zone.name, ast.PlayerRef("owner"))
    # "…to the battlefield **under your control**" (Cold Storage). CR 110.2a's
    # other seat, read beside the owner spelling above and recorded rather than
    # dropped for that clause's reason: the two name different players, and a
    # sweep that lost the word would hand the cards back to whoever owned them.
    under_your_control = bool(
        zone.owner is None and zone.name == "battlefield"
        and stream.accept_phrase("under", "your", "control")
    )
    return ast.PutExiledWithSource(
        zone, chosen=chosen, owned_by_you=owned_by_you, others_only=others_only,
        card_type=card_type, under_your_control=under_your_control,
    )


def _parse_player_returns_exiled_with_source(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.PutExiledWithSource | None":
    """``returns to the battlefield all cards they own exiled with it`` /
    ``returns to their hand all cards they own exiled with it`` — the verb and
    everything after it, with ``Each player`` already read by the caller.
    (Parallax Wave and Parallax Tide; Parallax Nexus prints the hand.)

    The same CR 607.2a linked pile :func:`_parse_put_exiled_with_source` reads,
    spelled from the other end: the imperative names the pile and says where
    each card goes ("…under **their owners'** control", Wall of Nets), where
    this names every player and has each one return **their own** cards. One
    claim either way — every card in the pile has exactly one owner, so "each
    player … all cards they own" is the whole pile, each card to its own owner —
    which is why it builds the same node with the owner possessive the
    imperative's clause records, and lowers through the same sweep.

    That equivalence holds for **this subject alone**, and the gate is the
    safety. "You return to your hand all cards you own exiled with it" would be
    one seat's share of the pile and the rest left in exile; "target player
    returns …" the same for a chosen seat. Neither is printed, and both decline
    here rather than being read as the sweep.

    The destination is printed in front of the object, the word order
    ``_parse_put_exiled_this_way`` reads for Memory Jar one production down, and
    its possessive must agree with the subject: "their hand" is the returning
    player's, which "they own" makes the card's owner (CR 400.3). A battlefield
    prints none and is nobody's zone (CR 400.1); the card enters under the
    control of the player who put it there (CR 110.2a), who is again its owner.

    Returns None with the cursor unmoved for anything else, so "each player
    returns all creature cards from their graveyard …" (All Hallow's Eve) and
    Memory Jar's "… each card they exiled this way" keep their own readings.
    """
    if player.kind != "each_player":
        return None
    mark = stream.mark()
    if not stream.accept_word("returns", "return"):
        return None
    if not stream.accept_word("to"):
        stream.reset(mark)
        return None
    # The printed possessive, read before ``_parse_zone`` normalises it: that
    # reader folds "your" *and* the subject's own pronoun into one ``you``
    # owner, and for this subject only the second is the returning player's
    # hand — "each player returns to **your** hand …" is every seat handing one
    # player the table's cards.
    possessive = stream.peek_word()
    try:
        zone = _parse_zone(stream, self_possessive=_matching_possessive(player))
    except GrammarError:
        stream.reset(mark)
        return None
    if zone.name == "battlefield":
        if zone.owner is not None:
            stream.reset(mark)
            return None
    elif possessive != _matching_possessive(player):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("all", "cards", "they", "own", "exiled", "with"):
        stream.reset(mark)
        return None
    if not (stream.accept_word("it") or _accept_self_reference(stream)):
        stream.reset(mark)
        return None
    return ast.PutExiledWithSource(ast.Zone(zone.name, ast.PlayerRef("owner")))


#: Where a linked pile may be printed to go back on a library. A closed list
#: for `_REVEAL_DESTINATIONS`' reason one family over: each of these is a
#: position the handler actually reaches, and a word outside it refuses the
#: line rather than lowering onto one nothing places.
_EXILED_PILE_POSITIONS: tuple[str, ...] = ("top", "bottom")


def parse_put_exiled_pile_on_library(
    stream: TokenStream,
) -> "ast.PutExiledPileOnLibrary | None":
    """``Look at the exiled cards and put them on top of your library in any
    order.`` (Scroll Rack.)

    Both clauses in one production, because the look is what makes the order a
    choice: the pile is face down (CR 406.3) and hidden from everybody, so the
    seat arranging it has to be shown it first. Read whole rather than as a
    look with a move behind it — "them" names the pile the look showed, and a
    separate move would have no referent.

    Refuses without consuming, so every other "Look at …" keeps its own reading
    — "look at target player's hand" is one word away from this and is a
    different family entirely.
    """
    mark = stream.mark()
    if not stream.accept_phrase("look", "at", "the", "exiled", "cards"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "put", "them", "on"):
        stream.reset(mark)
        return None
    position = stream.peek_word()
    if position not in _EXILED_PILE_POSITIONS:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("of", "your", "library"):
        stream.reset(mark)
        return None
    # "in any order" is consumed and not recorded, exactly as the counted
    # search's identical clause is: the arranger names the cards in the order
    # they want and that pick order *is* the answer.
    if not stream.accept_phrase("in", "any", "order"):
        stream.reset(mark)
        return None
    return ast.PutExiledPileOnLibrary(position=position)


def _matching_possessive(player: "ast.PlayerRef | None") -> str:
    """The pronoun a sentence uses for **its own subject**.

    "your" when the subject is the resolving player and "their" for anybody
    else — the agreement ``_parse_exile_entire_library`` already enforces one
    module over, and for its stated reason: reading either for either lets
    "each player exiles all creature cards from **your** graveyard" through,
    which is one graveyard and every player, and no card in Magic.
    """
    return "your" if player is None or player.kind == "you" else "their"


def _parse_player_exiles_pile(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.Exile | None":
    """``exiles all creature cards from their graveyard`` (Living Death),
    ``exiles all cards from their hand face down`` (Memory Jar) — the verb and
    everything after it, with the subject already read by the caller.

    The bare imperative ("Exile all creature cards from your graveyard", Zombie
    Mob) has had a production since Mirage and lowers to the same instruction;
    what this adds is the **printed subject**, which CR 608.2c makes the same
    sentence read from the other end. It is not decoration on this shape: the
    subject says whose graveyard is emptied, and — through the per-seat record
    the step writes — whose cards the sentence behind it hands back.

    Narrow on purpose, and the narrowness is the safety. Only a *graveyard card
    sweep* builds an :class:`ast.Exile` carrying an actor, so every other exile
    in the pool keeps a node whose actor is ``None`` and cannot have one
    dropped. The lowering refuses a non-``None`` actor anywhere else in any
    case, which is the second lock on the same door.

    Returns None with the cursor unmoved for anything else, so the two exile
    productions beside it in ``subject_verb`` keep their own sentences and the
    line keeps its own refusal site.
    """
    mark = stream.mark()
    if not stream.accept_word("exiles", "exile"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if not isinstance(subject, ast.TargetSpec):
        stream.reset(mark)
        return None
    filt = subject.filter
    # A pile of *cards* in a graveyard or a hand and nothing else. The noun
    # parser reads "from their graveyard" onto the filter as
    # ``zone``/``zone_owner``, so a phrase that named the battlefield — or a
    # library — comes back here as a different zone and is put back rather than
    # lowered onto a sweep that would read the wrong pile. The two admitted
    # zones lower to two different handlers; which one is the lowering's
    # question, and it refuses anything it has no sweep for.
    if not (filt.is_card and filt.zone in ("graveyard", "hand")):
        stream.reset(mark)
        return None
    # The possessive agrees with the subject, exactly as the library exile one
    # module over demands. "each player … from **their** graveyard" is one
    # claim said twice; the lowering checks the pair against each other rather
    # than trusting either half alone, and this is where the half it checks is
    # read.
    owner = filt.zone_owner
    if owner is None:
        stream.reset(mark)
        return None
    if not subject.quantifier in ("all", "each"):
        stream.reset(mark)
        return None
    if subject.targeted:
        stream.reset(mark)
        return None
    # "…from their hand **face down**." (Memory Jar.) CR 406.3 makes a
    # face-down card in exile hidden from every player, its owner included, so
    # the words are a real difference and not decoration — read here rather
    # than left unconsumed, which is what refused this whole sentence before.
    # The bare imperative one production over reads the same two words onto the
    # same field.
    face_down = bool(stream.accept_phrase("face", "down"))
    return ast.Exile(subject, actor=player, face_down=face_down)


def _parse_player_exiles_target_spell(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.Exile | None":
    """``exiles it with X delay counters on it`` (Ertai's Meddling) — the verb
    and everything after it, with ``Target spell's controller`` already read by
    the caller.

    The **object** of the verb is the sentence's target and it was printed in
    front of the verb: "target" modifies *spell*, so the announcement chooses an
    object on the stack (CR 115.1) and the seat performing the exile is read off
    it (CR 109.5). That is why "it" is not resolved through ``parse_recipient``
    here — the shared reader answers a bare pronoun with the ability's own
    source, which for this sentence is the spell doing the exiling rather than
    the spell being exiled. The subject phrase already said which object the
    pronoun means, so the spec is built from it.

    Gated on that one referent, which is the same narrowness
    :func:`_parse_player_exiles_pile` states about its own: only the
    ``target_spells_controller`` seat carries an object for "it" to name, and
    every other player-subject exile keeps its own reading and its own refusal.

    The counters rider is optional and read through the shared
    ``_parse_entering_counters``, so "…with X delay counters on it" and All
    Hallow's Eve's "…with two scream counters on it" are one printed phrase read
    once (CR 121.2 puts them on as part of the move either way).

    Returns None with the cursor unmoved for anything else.
    """
    if player.kind != "target_spells_controller":
        return None
    mark = stream.mark()
    if not stream.accept_word("exiles", "exile"):
        stream.reset(mark)
        return None
    if not stream.accept_word("it"):
        stream.reset(mark)
        return None
    counters = _parse_entering_counters(stream)
    return ast.Exile(
        # The zone is what says this is a spell rather than a permanent, and it
        # is the same word ``nouns`` writes for "target instant or sorcery
        # **spell**" — so the lowering and the picker read one answer to "what
        # may be chosen here", not two.
        ast.TargetSpec("target", ast.ObjectFilter(zone="stack")),
        actor=player,
        counters=counters,
    )


def _parse_put_exiled_this_way(
    stream: TokenStream, player: "ast.PlayerRef | None" = None
) -> "ast.PutExiledThisWay | None":
    """``puts all cards they exiled this way onto the battlefield`` (Living
    Death), ``returns to their hand each card they exiled this way`` (Memory
    Jar) — the verb and everything after it.

    The back-reference is read here rather than by the shared noun parser for
    the reason every other one in this grammar is: "exiled this way" is not a
    characteristic of a card, it names a *record*, and a filter carrying the
    words would lower through every line that printed them.

    The pronoun in front of the verb's object has to agree with the subject —
    "they" for a named seat, "you" for the unnamed one — because that word is
    the whole of what makes the record per-seat. "Each player … puts all cards
    **you** exiled this way" would be every player handing one seat's pile
    back, once per player.

    Returns None with the cursor unmoved for anything else, so an ordinary
    "puts …" keeps its own reading and its own refusal.
    """
    mark = stream.mark()
    # "**returns** to their hand …" (Memory Jar). One production for both
    # verbs, because a card coming out of exile is one act however the sentence
    # spells it — CR 400.1 moves an object to a zone and "put" and "return"
    # name the same move. A card whose destination is a *hand* is the printing
    # English says "return" for; which destinations have a handler is still the
    # lowering's question.
    if not stream.accept_word("puts", "put", "returns", "return"):
        stream.reset(mark)
        return None
    # "…returns **to their hand** each card they exiled this way." (Memory
    # Jar.) The destination printed in front of the object, which is English
    # rather than a different effect — the same word order ``_parse_return``
    # reads for Remove Enchantments, and refusing it would cost this card its
    # whole sentence over where the preposition sits.
    fronted: "ast.Zone | None" = None
    if stream.at_word("to", "into", "onto"):
        ahead = stream.mark()
        stream.advance()
        try:
            fronted = _parse_zone(
                stream, self_possessive=_matching_possessive(player)
            )
        except GrammarError:
            stream.reset(ahead)
            fronted = None
    subject = parse_recipient(stream)
    if not isinstance(subject, ast.TargetSpec):
        stream.reset(mark)
        return None
    if subject.quantifier not in ("all", "each") or subject.targeted:
        stream.reset(mark)
        return None
    if not subject.filter.is_card:
        stream.reset(mark)
        return None
    pronoun = "you" if player is None or player.kind == "you" else "they"
    if not stream.accept_word(pronoun):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("exiled", "this", "way"):
        stream.reset(mark)
        return None
    if fronted is not None:
        zone = fronted
    else:
        # "**onto** the battlefield" and "**into** their hand" are one
        # preposition to the rules (CR 400.1 moves an object to a zone); which
        # word is printed is which zone follows it. Both are read so a printing
        # that gave the pile back to a hand is this production rather than a
        # second one, and the lowering decides which destinations a handler
        # implements.
        if not stream.accept_word("onto", "into", "to"):
            stream.reset(mark)
            return None
        zone = _parse_zone(
            stream, self_possessive=_matching_possessive(player)
        )
    # The zone the noun phrase carried is the *source* pile, which for this
    # sentence is always exile and is never printed — the record answers it.
    # Stripped before the filter is handed on so the lowering's card gate sees
    # a phrase about characteristics alone.
    default = ast.ObjectFilter()
    described = dataclasses.replace(
        subject.filter, zone=default.zone, zone_owner=default.zone_owner,
    )
    return ast.PutExiledThisWay(zone, described, player)


def parse_exile_graveyard_arrivals_this_turn(
    stream: TokenStream,
) -> "ast.ExileGraveyardArrivalsThisTurn | None":
    """``If a card would be put into <whose> graveyard from anywhere this turn,
    exile that card instead.`` (Yawgmoth's Will.)

    CR 614 created by a **spell**. The unbounded spelling of the same sentence
    is a static ability of a permanent and `engine/replacements.py` reads it
    off that permanent's text; this one names a window, so the effect has to
    leave a record behind and the sentence needs a production.

    Read whole or not at all, and non-consuming on refusal, exactly as every
    other replacement-shaped "If …" reader in `statements.py` is: the words up
    to "this turn" are a prefix of the static sentence the registry claims, and
    a half-read line would take that claim away from it.

    The three printed scopes are read in the same vocabulary
    `replacements.graveyard_exile_scope` uses, so one phrase has one meaning
    across the two readings. Which of them an *effect* can arm is the
    lowering's answer.
    """
    mark = stream.mark()
    if not stream.accept_phrase("if", "a", "card", "would", "be", "put", "into"):
        stream.reset(mark)
        return None
    if stream.accept_word("your"):
        whose = "you"
    elif stream.accept_phrase("an", "opponent", "'s"):
        whose = "opponent"
    elif stream.accept_word("a"):
        whose = "any"
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "graveyard", "from", "anywhere", "this", "turn",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_word("exile"):
        stream.reset(mark)
        return None
    # "…exile **that card** instead" and "…exile **it** instead" are one
    # referent, which is what the static reading's own regex already says.
    if not (stream.accept_phrase("that", "card") or stream.accept_word("it")):
        stream.reset(mark)
        return None
    if not stream.accept_word("instead"):
        stream.reset(mark)
        return None
    return ast.ExileGraveyardArrivalsThisTurn(whose)


def parse_claims_one_exiled_card(
    stream: TokenStream, chooser: "ast.PlayerRef",
) -> "ast.EachPlayerClaimsExiledCard | None":
    """``chooses one of the exiled cards and puts it onto the battlefield
    tapped under their control`` — the verb and its object, without the subject.

    "Exile all nontoken permanents. Starting with you, **each player chooses one
    of the exiled cards and puts it onto the battlefield tapped under their
    control.** Repeat this process until all cards exiled this way have been
    chosen." (Thieves' Auction.)

    "One of the exiled cards" is a **bound reference to a pile an earlier
    sentence made**, which is why it is read here rather than by the noun
    parser: no description of the exile zone is that set — a player's exile also
    holds everything that ever went there by any other route — and the phrase
    names one *shared* pile that shrinks as the seats pick out of it.

    The pick and the put are one act and are read as one sentence, because they
    are: a card chosen and not put anywhere is not something this effect can
    leave behind, and splitting them would leave "it" in the second half naming
    a card no step of the line records.

    "Tapped" and "under their control" are both read rather than assumed. The
    first is the printed entry state and the second is what says the *chooser*
    gets it — an exiled card's owner is somebody else, and a card entering under
    its owner's control instead is the whole difference between this spell and a
    board reset.

    Non-consuming on refusal, like every arm of the ``chooses`` dispatcher that
    calls it.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    if not stream.accept_phrase("one", "of", "the", "exiled", "cards"):
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    if not stream.accept_word("puts", "put"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("it", "onto", "the", "battlefield"):
        stream.reset(mark)
        return None
    # Read, never defaulted: a printing without the word puts the card onto the
    # battlefield untapped, which is a different card and a better one.
    tapped = bool(stream.accept_word("tapped"))
    if not stream.accept_phrase("under", "their", "control"):
        stream.reset(mark)
        return None
    if not (stream.exhausted or stream.at_punct(".", ",")):
        stream.reset(mark)
        return None
    return ast.EachPlayerClaimsExiledCard(chooser=chooser, tapped=tapped)
