"""Searching **another player's** library — "Search target player's library
for three cards and exile them. Then that player shuffles."

A floor under ``effects/search.py``, pre-split out of it at the Phase 0 before
Invasion, when that module sat 29 lines under the thousand-line guard with a
wave of parallel groups about to land tutors in it. A floor rather than a
family for ``_strips``' reason and ``lowering/_recipients``' before it:
``search`` is the only module that asks. It could not be a family in any case —
the word "search" keeps one entry point, ``_parse_search_library``, and a family
may not be called from another one.

**The seam is the first thing that entry point decides.** It reads "search" and
then a possessive: "your" or "their" is the searcher's own library and
everything left in ``search``, and anything else is this. Both sides had already
said the two are different cards rather than two wordings — the tutor's
docstring ("the engine's search flow only ever opens the searcher's own
library, so 'search target player's library' is a different card") and
:class:`ast.SearchPlayerLibrary` ("two seats are involved rather than one").
Two seats is the whole subject here: whose library is opened is not who
chooses (CR 608.2c), not necessarily whose battlefield a find lands on
(Bribery, CR 110.2a), and it *is* who shuffles.

The call graph agreed before the cut was made. The production calls nothing
left in ``search`` and only the entry point calls it; it reads no zone through
``phrases._parse_zone``, which has no reading for the possessive it needs; and
it was the **only** reader of ``_strips``, so that floor is imported from here
now and ``search`` no longer imports it. ``_strips``' docstring called itself a
floor under ``search`` whose two halves "share the printed word 'Search' and no
vocabulary whatsoever" — true against the tutor, and not against this
production, which reads ``Search <player>'s`` before handing the strip the
player and ends on the same "and exile them. Then that player shuffles". The
strip was always a branch of this reader. It stays its own module, because what
that docstring says about a multi-zone strip by a recorded name is as true
against a one-library search as against the tutor.

It is also the half that had been growing: 63 lines when ``search`` left
``library`` and 136 now, with each of the last three sets adding a destination
or a spelling (Bribery, Rootwater Thief, Denying Wind).

No mirror name to reuse. ``lowering/search.py`` lowers this node beside the
tutor's and has never split, and the node sits in ``ast/library.py``; the name
is the production's own.
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
