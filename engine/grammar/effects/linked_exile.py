"""A pile that is **already in exile**, and where it goes next (CR 406, CR 610.3).

Split out of ``effects/exile.py`` at the Phase 0 before Odyssey, with that
module 38 lines under the thousand-line guard and a graveyard set's nine groups
about to open on it. The cut is not a new line. The lowering side took it at
Tempest's Phase 0, and ``lowering/linked_exile.py`` wrote it down from both
ends — "`exile` moves an object *into* the exile zone and refuses the shapes no
handler implements, where every production here starts from a pile that is
already there and asks whose it is, where it goes, and what may be done with
it" — while the parse halves of those two subjects simply stayed in one file,
under a first line that named both: "Cards moving **into and out of exile**
(CR 406), and back again."

Three measurements picked the seam, and they agree:

* **The mirror, node by node.** The ten productions here build six nodes —
  ``PutExiledWithSource``, ``PutExiledPileTopIntoHand``,
  ``PutExiledCardIntoZone``, ``PutExiledThisWay``, ``PutExiledPileOnLibrary``
  and ``EachPlayerClaimsExiledCard`` — and ``lowering/linked_exile.py`` lowers
  all six. The six productions left behind build five, and it lowers none.
* **The call graph.** ``effects/exile.py`` had five internal edges and every
  one is inside this half: ``_bin_zone`` under the two "didn't play it"
  readers, ``_matching_possessive`` under the Parallax return and the "exiled
  this way" return, the position list under Scroll Rack's look. Nothing here
  calls anything left there and nothing there calls anything here, which is
  what the family rule requires of two families in one package.
* **Where the module had been growing.** 672 of its 962 lines were this half,
  and so was every one of the 203 it gained after Urza's Legacy — the
  round-robin over a shared pile, the Parallax cycle, Psychic Theft, Skyship
  Weatherlight.

The second is also why the cut is not narrower. "Exiled *with* this permanent"
(CR 610.3's linked pile) and "exiled *this way*" (one resolution's own record)
read as two subjects, and a cut between them would have crossed the one edge
that joins two productions: both agree a possessive with their subject through
``_matching_possessive``. The lowering side keeps the two in one module as
well — what they share is the question, not the record.

The name is ``lowering/linked_exile.py``'s, which is ``engine/linked_exile.py``'s,
so the mirror re-forms rather than forking a third word for one subject.
``ast/`` still has no ``linked_exile``: four of the six nodes are in
``ast/exile.py``, which is cut by subject rather than by reader and argues why
at length, and the other two sit with their subjects in ``ast/library.py`` and
``ast/cards.py``.

Every name here is reached from ``imperative_verbs``, ``player_verbs`` or
``if_openings``, and from no sibling. All of them moved byte-identically, so no
compiled program moved.
"""

import dataclasses

from .. import ast
from ..errors import GrammarError
from ..phrases import _accept_self_reference, _parse_zone
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
        # "…if you haven't **cast** the card" (Psychic Theft) is the same test
        # for a card only castable: it is still in exile exactly when unplayed.
        if not (
            stream.accept_phrase("played", "it")
            or stream.accept_phrase("played", "the", "card")
            or stream.accept_phrase("cast", "it")
            or stream.accept_phrase("cast", "the", "card")
        ):
            stream.reset(mark)
            return None
        stream.accept_punct(",")
        # "…, **return it to its owner's hand**." (Psychic Theft.)
        if stream.accept_phrase("return", "it", "to"):
            return ast.PutExiledCardIntoZone(
                _parse_zone(stream), only_if_unplayed=True
            )
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


def _parse_random_exiled_with_source(
    stream: TokenStream,
) -> "ast.PutExiledWithSource | None":
    """``Choose a card at random that was exiled with <this permanent>. Put
    that card into its owner's hand.`` (Skyship Weatherlight.)

    Two printed sentences and one effect, read together for the reason every
    "choose" in this grammar is: the first performs nothing on its own, and
    "that card" in the second names what the first picked and nothing else.
    The same CR 607.2a linked pile :func:`_parse_put_exiled_with_source` reads
    — one card out of it, as Gustha's Scepter's is, with the pick made by
    nobody.

    Every word is required, the self-reference included: "exiled with" another
    permanent is a pile this cannot find. Returns None with the cursor
    untouched on anything else, so every other "choose" sentence keeps the
    reading it has.
    """
    mark = stream.mark()
    if not (
        stream.accept_phrase(
            "choose", "a", "card", "at", "random", "that", "was", "exiled",
            "with",
        )
        and _accept_self_reference(stream)
        and stream.accept_punct(".")
        and stream.accept_phrase("put", "that", "card", "into")
    ):
        stream.reset(mark)
        return None
    try:
        zone = _parse_zone(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.PutExiledWithSource(zone, chosen=True, at_random=True)


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
#: for `naming._REVEAL_DESTINATIONS`' reason: each of these is a
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
    # "…that player returns **those cards** to their hand." (Suppress.) The
    # same record by its other name: with a seat printed in front of the verb,
    # "those cards" are the ones that seat's earlier step put away, and the
    # lowering's producer gate is what refuses the pronoun where no step of
    # the effect exiled a pile for it to name.
    if (
        player is not None and fronted is None
        and stream.accept_phrase("those", "cards")
    ):
        subject = ast.TargetSpec("all", ast.ObjectFilter(is_card=True))
    else:
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
