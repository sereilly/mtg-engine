"""**Another player's** library, opened by somebody who is not its owner —
searched ("Search target player's library for three cards and exile them. Then
that player shuffles.") or looked at off the top ("Look at the top five cards
of target player's library. You may then have that player shuffle that
library.").

A floor under two families, and it took them one at a time. The search's half
was pre-split out of ``effects/search.py`` at the Phase 0 before Invasion, when
that module sat 29 lines under the thousand-line guard with a wave of parallel
groups about to land tutors in it; the look's half followed out of
``effects/library.py`` at the Phase 0 before Odyssey, with that module 21
under. In between this was a single-importer floor, for ``_strips``' reason and
``lowering/_recipients``' before it — ``search`` was the only module that asked
— and its first line said "Searching". Two families ask now, each for the one
production here that is its own. It could not be a family in any case: the
words "search" and "look" each keep one entry point
(``_parse_search_library``, ``_parse_look_at_hand``), and a family may not be
called from another one.

**The seam is the same fork in both entry points: the possessive behind the
verb.** ``search`` reads "search" and then "your" or "their", which is the
searcher's own library and everything left there, and anything else is this.
``library`` reads "look at the top N cards of" and then "your", which is
everything left *there* — "the pick, the bottoming, the cast-zone rider — is
only ever about your own library", in that branch's own words — and anything
else is this. Both sides had already said the two are different cards rather
than two wordings: the tutor's docstring ("the engine's search flow only ever
opens the searcher's own library, so 'search target player's library' is a
different card"), :class:`ast.SearchPlayerLibrary` ("two seats are involved
rather than one") and :class:`ast.LookTopPickToHand`, whose ``pile_owner`` is
whose library it is "when that is not the looker's own". Two seats is the whole
subject here: whose library is opened is not who chooses (CR 608.2c), not
necessarily whose battlefield a find lands on (Bribery, CR 110.2a), and it *is*
who shuffles — which the look prints outright ("have **that player** shuffle
**that library**").

The call graph agreed before each cut was made. The search production calls
nothing left in ``search`` and only the entry point calls it; it reads no zone
through ``phrases._parse_zone``, which has no reading for the possessive it
needs; and it was the **only** reader of ``_strips``, so that floor is imported
from here now and ``search`` no longer imports it. ``_strips``' docstring
called itself a floor under ``search`` whose two halves "share the printed word
'Search' and no vocabulary whatsoever" — true against the tutor, and not
against this production, which reads ``Search <player>'s`` before handing the
strip the player and ends on the same "and exile them. Then that player
shuffles". The strip was always a branch of this reader. It stays its own
module, because what that docstring says about a multi-zone strip by a recorded
name is as true against a one-library search as against the tutor.

The look's tail is called from ``library._parse_look_statement`` and from
nowhere else, calls :func:`_accept_that_library` below it and nothing left
behind, and reads no parser at all: the node package and the token stream are
everything it imports. The two halves share this module's subject and no
reader — neither calls the other, and the strip is the search's alone.

Both are halves that had been growing. The search was 63 lines when ``search``
left ``library`` and 136 when it came here, each of the three sets before
adding a destination or a spelling (Bribery, Rootwater Thief, Denying Wind).
The look's tail printed one offer and prints five: the shuffle (Visions), the
rearrangement (Natural Selection, Portent), the one card bottomed (Coral
Fighters, Precognition), any number of them bottomed (Ransack) and a pick taken
out of somebody else's pile (Sealed Fate).

**Not every look across two seats is read here.** Tahngarth's Glare and
Phyrexian Portal have another player look through *your* library, and both stay
in ``library``: their looker is the printed subject, so they are reached from
``player_verbs`` and never pass the fork this floor is cut on.

No mirror name to reuse. ``lowering/search.py`` lowers the search's node beside
the tutor's and has never split, ``lowering/library.py`` lowers the look's two
beside every other look's, and all three nodes sit in ``ast/library.py``; the
name is the two productions' own (``_parse_search_other_library``,
``_parse_look_other_library_tail``).
"""


from .. import ast
from ..amounts import parse_amount
from ..nouns import parse_object_filter
from ..references import parse_player_ref
from ..stream import TokenStream
from ._strips import _accept_strip_cards_with_chosen_name


def _parse_search_other_library(stream: TokenStream) -> ast.Statement:
    """``Search <player>'s library for <count> cards and exile them. Then that
    player shuffles.`` (Jester's Cap.)

    ``Search <player>'s library for <count> cards. That player puts those cards
    into their hand, then shuffles.`` (Jester's Mask.)

    Three things are read rather than skipped, each for the reason the
    own-library production reads its three:

    * **whose library** — the seat the flow opens, which is not the seat that
      chooses (CR 608.2c);
    * **where the finds go** — exile and the searched player's hand are
      different effects. The sentence naming the hand is printed *after* the
      search and is still consumed here, because it is about the cards this
      search found: left to the sequence parser it would run before the prompt
      this arms had been answered, and would have nothing to move.
    * **the shuffle** — CR 701.24 ends a library search with one, so deleting
      the word refuses the line rather than claiming a search that leaves the
      library ordered.
    """
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected whose library is searched")
    # The lexer splits "player's" into "player" + "'s".
    stream.expect_word("'s")
    # "Search that player's **graveyard, hand, and library** for all cards with
    # the same name as the chosen card and exile them." (Lobotomy.) A search
    # across several zones and by a name nothing printed — read here, before
    # the literal "library" this production has always expected, which is the
    # word that failed the line. Non-consuming on refusal, so Jester's Cap and
    # Jester's Mask keep every reading and every refusal site they have.
    stripped = _accept_strip_cards_with_chosen_name(stream, player)
    if stripped is not None:
        return stripped
    stream.expect_word("library")
    stream.expect_word("for")
    # "…for **up to seven** cards" (Denying Wind): a ceiling, not CR 701.23d's
    # find-that-many floor.
    up_to = bool(stream.accept_phrase("up", "to"))
    count = parse_amount(stream)
    if isinstance(count, ast.Fixed) and count.value < 1:
        raise stream.error("expected how many cards the search may find")
    filt = parse_object_filter(stream)
    if not filt.is_card:
        raise stream.error("a library holds cards, not permanents")
    to: ast.Zone | None = None
    under_control_of: ast.PlayerRef | None = None
    if isinstance(count, ast.Fixed) and count.value == 1 and stream.accept_phrase(
        "and", "put", "that", "card", "onto", "the", "battlefield"
    ):
        # "Search **target opponent's** library for a creature card and put that
        # card onto the battlefield **under your control**." (Bribery.) The
        # third destination this production reads, and the first that separates
        # the seat whose library is opened from the seat the find lands under —
        # CR 110.2a's controller, which is what the printed phrase is there to
        # say.
        #
        # The controller is **required**, not optional: CR 110.2 would default
        # it to the spell's controller and so would happen to be right here,
        # but ``search_filters.landing_seat`` does not — its default follows the
        # *zone*, so a phrase consumed into nothing would put the creature back
        # onto the battlefield of the player whose library it came out of. A
        # printed seat read and dropped is the rider bug this grammar refuses by
        # construction, so the words are consumed and checked.
        to = ast.Zone("battlefield")
        if stream.accept_phrase("under", "your", "control"):
            under_control_of = ast.PlayerRef("you")
        elif stream.accept_phrase("under", "the", "control", "of"):
            under_control_of = parse_player_ref(stream)
            if under_control_of is None:
                raise stream.error("expected a player after 'under the control of'")
        else:
            raise stream.error(
                "expected whose battlefield this search's find enters"
            )
    elif stream.accept_phrase("and", "exile", "them"):
        to = ast.Zone("exile")
    elif isinstance(count, ast.Fixed) and count.value == 1 and stream.accept_phrase(
        "and", "exile", "it"
    ):
        # "Search target opponent's library for **a card** and exile **it**."
        # (Grinning Totem.) The plural clause above with one find, and the
        # pronoun is *checked against the count* rather than merely consumed:
        # "for three cards and exile it" is not a sentence any card prints, and
        # admitting it would let a three-card search claim the one-card reading
        # — the same agreement `_parse_search_untap_rider` demands of "that
        # land". The whole difference is a word, so it is a branch here and not
        # a second production.
        to = ast.Zone("exile")
    # "…and exile it**, then the player shuffles**." (Rootwater Thief.) The
    # shuffle clause printed inside the search's own sentence rather than as the
    # next one — the same CR 701.23 tail, so it is read here for exactly the
    # reason the separate-sentence spelling is. The comma spelling needs "then";
    # only a full stop can open the clause bare ("Then that player shuffles.").
    same_sentence = (
        to is not None
        and stream.accept_punct(",")
        and stream.at_word("then")
    )
    if not same_sentence and not stream.accept_punct("."):
        raise stream.error("expected the sentence that ends this search")
    if to is not None:
        # "**Then that player shuffles.**"
        stream.accept_word("then")
        shuffler = parse_player_ref(stream)
        if shuffler is None:
            raise stream.error("expected who shuffles after this search")
        # The shuffler is the player whose library was searched (CR 701.23a)
        # — "that player" / "the player" back-refer to the seat this sentence
        # opened — and a printed seat read and dropped is the rider bug this
        # grammar refuses: a card naming some other shuffler is not this one.
        if shuffler.kind not in ("that_player", player.kind):
            raise stream.error("the searched player is the one who shuffles")
        stream.expect_word("shuffles")
        return ast.SearchPlayerLibrary(
            player, count, filt, to, under_control_of, up_to=up_to
        )
    if up_to:
        raise stream.error("only an exiling search reads 'up to' here")
    # "**That player puts those cards into their hand, then shuffles.**"
    holder = parse_player_ref(stream)
    if holder is None:
        raise stream.error("expected who takes the cards this search found")
    for word in ("puts", "those", "cards", "into"):
        stream.expect_word(word)
    # "into **their** hand" — the possessive names the player this same clause
    # just named. `_parse_zone` has no reading for it (its possessives are
    # "your", "its owner's" and "its controller's"), and widening it there would
    # give every zone destination in the grammar a pronoun with no antecedent.
    stream.expect_word("their")
    stream.expect_word("hand")
    stream.accept_punct(",")
    stream.expect_word("then")
    stream.expect_word("shuffles")
    return ast.SearchPlayerLibrary(player, count, filt, ast.Zone("hand", holder))


def _accept_that_library(stream: TokenStream) -> bool:
    """Consume a back-reference to the library the look already named.

    Three printed spellings for one thing — "that library", "the library",
    "that player's library" — and Ransack prints two of them in one sentence
    ("on the bottom of **that library** … the rest on top of **the library**").
    Read as one because they are one: the look named the pile, and a sentence
    that meant a *different* library would have to say which.
    """
    if stream.accept_phrase("that", "player", "'s", "library"):
        return True
    return stream.accept_phrase("that", "library") or stream.accept_phrase(
        "the", "library"
    )


def _parse_look_other_library_tail(
    stream: TokenStream, count, owner: ast.PlayerRef
) -> ast.Statement:
    """The rest of "Look at the top five cards of target player's library. You
    may then have that player shuffle that library." (Visions.)

    The shuffle sentence is read here rather than as a statement of its own
    because "that library" is the one the look just named — parsed apart it
    would have to guess a player, and guessing which library gets shuffled is
    the one mistake this card can make. The tail is optional: a card that only
    looks is this same effect without its offer, and refusing it would refuse a
    shape the node already represents.
    """
    mark = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "you", "may", "then", "have", "that", "player", "shuffle", "that", "library"
    ):
        return ast.LookAtLibraryTop(count, owner, may_shuffle=True)
    stream.reset(mark)
    # "**You may put that card on the bottom of that player's library.**"
    # (Coral Fighters.) The other offer this template prints, and the other
    # direction: Visions offers a shuffle, which the looker takes when the top
    # is bad, and this offers the one card itself.
    #
    # "That player" is read as the very player the look named rather than as a
    # fresh reference — parsed apart it would have to guess a seat, which is
    # this production's whole reason for reading the tail at all.
    bottomed = stream.mark()
    if stream.accept_punct("."):
        # "…library. **If you do,** you may put that card on the bottom…"
        # (Precognition.) The join the *optional* printing needs and Coral
        # Fighters' mandatory one does not: there the look always happens, so
        # there is no condition for the offer to hang on. Consumed and dropped
        # rather than modelled, because it states exactly what the enclosing
        # "you may look" already means — the offer behind a look nobody took is
        # an offer over no card, which is what the handler finds anyway.
        if stream.accept_phrase("if", "you", "do"):
            stream.accept_punct(",")
        if stream.accept_phrase(
            "you", "may", "put", "that", "card", "on", "the", "bottom", "of",
            "that", "player", "'s", "library",
        ):
            return ast.LookAtLibraryTop(count, owner, may_bottom=True)
    stream.reset(bottomed)
    # "**Put any number of them on the bottom of that library in any order and
    # the rest on top of the library in any order.**" (Ransack.) The same offer
    # Coral Fighters prints, at a size where the words have to change: with one
    # card looked at there is nothing to count and nothing to order, so that
    # card says "that card" and this one says "any number of them". The
    # decision is one decision either way — which of the looked-at cards go to
    # the bottom, and in what order the rest go back — which is why both reach
    # ``may_bottom`` rather than one of them growing a second flag that lowers
    # to the same instruction.
    counted_bottom = stream.mark()
    if (
        stream.accept_punct(".")
        and stream.accept_phrase(
            "put", "any", "number", "of", "them", "on", "the", "bottom", "of",
        )
        and _accept_that_library(stream)
        and stream.accept_phrase(
            "in", "any", "order", "and", "the", "rest", "on", "top", "of",
        )
        and _accept_that_library(stream)
        and stream.accept_phrase("in", "any", "order")
    ):
        return ast.LookAtLibraryTop(count, owner, may_bottom=True)
    stream.reset(counted_bottom)
    # "**Exile one of those cards and put the rest back on top of that player's
    # library in any order.**" (Sealed Fate.) The look-and-pick template over
    # somebody else's pile: the cards are the opponent's and every decision
    # about them is the caster's, which is the one thing ``looker`` cannot say
    # (there the seat answers both questions at once). So it produces the pick
    # node with ``pile_owner`` set rather than a second node — the procedure is
    # the same one, over a library that is not the chooser's.
    #
    # Every word of both destinations, for this family's standing reason: where
    # the taken card goes and where the rest go are the whole of what separates
    # these cards, and a wording that sorted them elsewhere would be a
    # different card wearing this one's head.
    exiled = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "exile", "one", "of", "those", "cards", "and", "put", "the", "rest",
        "back", "on", "top", "of", "that", "player", "'s", "library",
        "in", "any", "order",
    ):
        return ast.LookTopPickToHand(
            count,
            pick_destination="exile",
            rest_destination="library_top",
            pile_owner=owner,
        )
    stream.reset(exiled)
    # "…, **then put them back in any order**." (Natural Selection, Portent.)
    # The looker rearranges the cards they saw, which is the other handler —
    # and the optional shuffle after it is printed shorter here than Visions
    # prints it, so both spellings are read rather than one being normalized
    # into the other.
    #
    # This was a name-keyed hook on Natural Selection, and Portent prints the
    # identical sentence: `card_hooks`' entry bar is that no second card shares
    # the shape, and a second card did.
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "put", "them", "back", "in", "any", "order"
    ):
        shuffle_mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "you", "may", "have", "that", "player", "shuffle"
        ):
            return ast.LookAtLibraryTop(
                count, owner, may_shuffle=True, may_reorder=True
            )
        stream.reset(shuffle_mark)
        return ast.LookAtLibraryTop(count, owner, may_reorder=True)
    stream.reset(mark)
    return ast.LookAtLibraryTop(count, owner)
