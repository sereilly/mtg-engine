"""A hand emptying onto a library — the sentences that move cards the other way.

Split from ``cards`` at the thousand-line guard, along the seam that module's
docstring had already implied: what stays in ``cards`` is a card *arriving*
(drawing, milling, searching, revealing) or *leaving for a graveyard*
(discarding), and what left is the one family that moves cards **out of a hand
and into a library** — Brainstorm, Conch Horn, Dream Cache, Stunted Growth,
Jester's Mask, Teferi's Puzzle Box. CR 402 is the zone they all name and
``hand`` is what the rules call it.

Asymmetric, like ``types``, ``exile`` and ``destruction`` before it: the nodes
stay in ``ast/cards.py`` and the lowerings in ``lowering/cards.py``, because the
guard fired on the *productions* and one node in a family of its own with both
of its readers elsewhere is worse than the asymmetry.

The two destination readers are the reason the family is worth naming. Every
production here ends by asking one of them where the cards land, so the top, the
bottom and Dream Cache's either-end offer are decided in one place and cannot
come apart card by card.
"""

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..stream import TokenStream


def _accept_hand_card_count(stream: TokenStream) -> "ast.Amount | None":
    """``two cards`` / ``a card`` — how many leave the hand.

    The noun is required and is what tells this apart from "put **a counter**"
    and "put **that card**": a bare number with nothing after it is not this
    sentence.
    """
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    return count


def _accept_hand_to_library_tail(
    stream: TokenStream, possessive: str, *, ordered: bool = True
) -> bool:
    """``… on top of <possessive> library[ in any order]``, consumed whole.

    Shared by the printed spellings so they cannot come to disagree about the
    destination. Every word is required. Dropping "on top of" would let a
    sentence putting cards on the *bottom* read as this one, and dropping "in
    any order" would silently discard the ordering the card gives the player —
    the rider bug this grammar refuses by construction. The possessive is the
    caller's, because it agrees with the subject the sentence already named:
    "**your** hand … **your** library", "**their** hand … **their** library".

    *ordered* is False where the rider is not printed and could not be, and is
    a parameter rather than an ``accept`` so the two spellings cannot drift into
    each other: a card that prints the words must still have them read. Two
    callers pass it. Jester's Mask ("puts the cards from their hand on top of
    their library") omits the rider over a whole hand; and **one card is not an
    order** — "put a card from your hand on top of your library" (Conch Horn)
    prints no ordering clause because a single card has no order to give, and
    requiring one there refuses the sentence for a word English does not print.
    """
    if not stream.accept_phrase("on", "top", "of", possessive, "library"):
        return False
    return bool(stream.accept_phrase("in", "any", "order")) or not ordered


def _accept_hand_to_library_bottom_tail(stream: TokenStream, possessive: str) -> bool:
    """``… on the bottom of <possessive> library in any order``, consumed whole.

    Teferi's Puzzle Box. The twin of :func:`_accept_hand_to_library_tail` at the
    other end of the library, and a separate reader rather than an alternation
    inside it because the two differ in what they *require*: the top spelling is
    printed over a whole hand with no ordering clause (Jester's Mask), and this
    one is never printed without it — "in any order" is the whole of what the
    player still decides once the card has named the end, so a production that
    let the words be absent would silently drop the only choice the sentence
    offers.

    "**the** bottom" against "top" with no article is the printed wording, not a
    tolerance: reading either article on either end would let a card that
    bottoms compile as one that tops.
    """
    if not stream.accept_phrase("on", "the", "bottom", "of", possessive, "library"):
        return False
    return bool(stream.accept_phrase("in", "any", "order"))


def _accept_hand_to_either_end_tail(stream: TokenStream) -> bool:
    """``… both on top of your library or both on the bottom of your library``.

    Dream Cache, and the whole of what makes it a different card: the end is
    the player's to choose and **both** cards go to the same one, which is what
    the repeated "both" says. Read as one phrase rather than as an alternation
    of two destinations, because a sentence that let the cards go to different
    ends would be a card nobody printed.

    Every word again, for ``_accept_hand_to_library_tail``'s reason: the two
    destinations are the offer, and one dropped would leave the player a choice
    with one option in it.
    """
    return bool(stream.accept_phrase(
        "both", "on", "top", "of", "your", "library",
        "or", "both", "on", "the", "bottom", "of", "your", "library",
    ))


def _orderable(count: "ast.Amount") -> bool:
    """Whether the printed count is one an "in any order" rider can be about.

    One card has no order, so Conch Horn prints none and Brainstorm prints one.
    That is the difference between the two sentences and the only one, so it is
    read off the count rather than made optional: with the rider merely accepted,
    "put two cards from your hand on top of your library" would parse with the
    player's ordering silently dropped, which is the rider bug this file already
    refuses by construction one function up.
    """
    return not (isinstance(count, ast.Fixed) and count.value == 1)


def _parse_put_hand_cards_on_library(
    stream: TokenStream, player: "ast.PlayerRef | None" = None,
) -> "ast.PutHandCardsOnLibrary | None":
    """``Put two cards from your hand on top of your library in any order.``
    (Brainstorm.)

    The bare imperative, so the player is "you" (CR 608.2: an instruction with
    no printed subject is about the spell's controller). Refuses without
    consuming, because "put" opens a counter, a permanent and three zone moves;
    every one of those keeps the production it already had.

    *player* is the seat a caller has **already read**, printed in the third
    person: "…unless they **put a card from their hand on top of their
    library**" (Tainted Specter), where the toll reader has the payer in hand
    before the verb. One production for both, because the possessives agree
    with the subject and nothing else about the sentence changes — a second
    reader would be a second answer to "where do these cards go", which is the
    fork ``_accept_hand_to_library_tail`` exists to prevent. Dream Cache's
    either-end offer is deliberately *not* offered to a third-person payer: the
    phrase is printed with "your" throughout, so a "their" spelling of it is a
    sentence nobody prints.
    """
    mark = stream.mark()
    possessive = "your" if player is None else "their"
    if not stream.accept_word("put"):
        return None
    count = _accept_hand_card_count(stream)
    if count is None or not stream.accept_phrase("from", possessive, "hand"):
        stream.reset(mark)
        return None
    # Dream Cache's offer, read before the ordinary tail because it opens on a
    # word that one does not ("both") and would otherwise fail the line.
    if player is None and _accept_hand_to_either_end_tail(stream):
        return ast.PutHandCardsOnLibrary(
            ast.PlayerRef("you"), count, destination="either_end"
        )
    if not _accept_hand_to_library_tail(
        stream, possessive, ordered=_orderable(count)
    ):
        stream.reset(mark)
        return None
    return ast.PutHandCardsOnLibrary(player or ast.PlayerRef("you"), count)


def _parse_player_puts_hand_cards_on_library(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.PutHandCardsOnLibrary | None":
    """``<player> chooses three cards from their hand and puts them on top of
    their library in any order.`` (Stunted Growth.)

    One sentence and one action: "chooses … and puts them" names the choice and
    the move the choice is for, which is the same prompt. Reading the halves as
    two steps would leave "them" bound to nothing.

    Refuses without consuming, so "chooses a card name…" (Petra Sphinx) and
    "chooses a creature…" (Takklemaggot) keep their own productions.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    count = _accept_hand_card_count(stream)
    if count is None or not stream.accept_phrase("from", "their", "hand"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "puts", "them"):
        stream.reset(mark)
        return None
    if not _accept_hand_to_library_tail(stream, "their"):
        stream.reset(mark)
        return None
    return ast.PutHandCardsOnLibrary(player, count)


def _parse_player_puts_whole_hand_on_library(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.PutHandCardsOnLibrary | None":
    """``<player> puts the cards from their hand on top of their library.``
    (Jester's Mask.)

    The same move Stunted Growth prints with a number, so the same node — what
    differs is that there is no *choice* of which cards, only of the order they
    land in. Refuses without consuming, so every other "puts" sentence keeps
    the reading it has.
    """
    mark = stream.mark()
    if not stream.accept_word("puts", "put"):
        return None
    # "the cards **from** their hand" (Jester's Mask) and "the cards **in**
    # their hand" (Teferi's Puzzle Box) name the same cards; the preposition is
    # a spelling, so both are read here rather than in two productions.
    if not (
        stream.accept_phrase("the", "cards", "from", "their", "hand")
        or stream.accept_phrase("the", "cards", "in", "their", "hand")
    ):
        stream.reset(mark)
        return None
    # "…on top of their library" (Jester's Mask) prints no ordering clause over
    # a whole hand; "…on the bottom of their library **in any order**"
    # (Teferi's Puzzle Box) does, and the rider is required there for the
    # reason `_accept_hand_to_library_tail` requires it everywhere else — a
    # dropped ordering clause is an ordering the player silently loses.
    destination = "top"
    if _accept_hand_to_library_tail(stream, "their", ordered=False):
        pass
    elif _accept_hand_to_library_bottom_tail(stream, "their"):
        destination = "bottom"
    else:
        stream.reset(mark)
        return None
    # "…, **then draws that many cards**." (Teferi's Puzzle Box.) Read here
    # rather than as the sentence after it: "that many" is the number this step
    # moved, and a draw parsed apart would have no producer to count.
    then_draw = False
    probe = stream.mark()
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "draws", "that", "many", "cards"
    ):
        then_draw = True
    else:
        stream.reset(probe)
    return ast.PutHandCardsOnLibrary(
        player, ast.Fixed(0), whole_hand=True,
        destination=destination, then_draw=then_draw,
    )
