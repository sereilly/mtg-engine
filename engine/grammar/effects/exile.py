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

from .. import ast
from ..phrases import _accept_self_reference, _parse_zone
from ..references import parse_player_ref
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
    if stream.accept_phrase("put", "all", "cards", "exiled", "with"):
        preposition = "into"
    elif stream.accept_phrase("return", "each", "card", "exiled", "with"):
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
    ):
        zone = ast.Zone(zone.name, ast.PlayerRef("owner"))
    return ast.PutExiledWithSource(zone, chosen=chosen, owned_by_you=owned_by_you)
