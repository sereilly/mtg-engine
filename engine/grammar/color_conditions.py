"""Conditions about **colour** — which colour leads the board, and whether the
object an effect targets shares one.

"…as long as **white is the most common color among all permanents** or is
tied for most common" (the Invasion Djinns); "Destroy target creature **if it
shares a color with the most common color among all permanents** or a color
tied for most common" (Tsabo's Assassin); "…**if it shares a color with that
permanent**" (Guard Dogs); "Counter target spell **if it shares a color with a
creature you control**" (Jaded Response); "…**unless either one is a color the
other isn't**" (Dead Ringers). CR 105.2 makes an object's colours a set, and
every clause here asks about that set: against the census of the whole
battlefield (``engine/color_census.py``), or against another object's
(``engine/object_colors.py``) — the two engine modules ``CLAUDE.md`` files as
one entry, "colour as a relation and as a count".

Pre-split out of ``condition_counts`` at Torment's Phase 0, when that module
sat 43 lines under the thousand-line guard with threshold — "seven or more
cards are in your graveyard", a count — the spine of the set about to arrive.
Nothing handed a seam down, so it was measured:

* **The block was closed.** ``_accept_color_census_condition`` and the pronoun
  reader it calls had one caller, the head of ``accept_counted_condition``,
  and called nothing else in that module; ``accept_target_pronoun`` read the
  card-type table, which nothing else there read.
* **It was the one part whose subject was not a count.** That module asks
  "how many?" of a set and files every question asked of *one object* with the
  dispatcher's half. The census is a count, but of the reader's five clauses
  only the Djinns' asks it alone: the other four ask a colour of the object the
  guarded effect targets, which is one object by any reading.
* **It was the part that grew, and it grew alone.** Invasion's census, then
  Planeshift's Guard Dogs and Apocalypse's Dead Ringers and Jaded Response —
  one asker a set — and the last three of those commits touched nothing else in
  the module. The same four commits grew the six branches that lower these
  nodes, and on that side too nothing else but the referent question Dead
  Ringers needed: the seam was already drawn on both sides.

The census did not stay behind with the counts because it cannot be parted
from the relations: "it shares a color with" opens Tsabo's Assassin, Guard Dogs
and Jaded Response alike, and the comment at Guard Dogs' branch below says why
one reader of those words is what keeps "it" one object.

A clause reader's contract, the one ``condition_clauses`` states: it reads a
sentence to its end and returns the node, or returns None with the cursor
where it found it. The dispatcher in ``conditions`` calls it at the point the
block stood — immediately before ``accept_counted_condition``, whose first act
it was — so the order the grammar tries its clauses in is unchanged, and the
counted reader begins where it always did.

The name is the mirror's: ``lowering/_color_conditions.py`` took the lowering
branches in the same commit (these five nodes and Hydroblast's "if it's red",
whose parse stays in ``record_conditions`` as an arm of the "it's" branch), the
arrangement ``record_conditions`` and ``lowering/_record_conditions.py``
already have. The nodes stay in ``ast/conditions.py``. Below ``conditions``,
which calls it and is never imported back, and independent of
``condition_counts``.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import CARD_TYPES, COLOR_WORDS


#: The set a colour census is taken over, as printed. One phrase today — "among
#: all permanents" is every permanent on the battlefield, either seat's, tokens
#: and lands included — and required whole: a narrower set ("among nontoken
#: permanents the chosen player controls", Call to Arms) is a different count
#: with a different answer, and this reader must refuse it rather than answer
#: it about the whole board.
_CENSUS_SCOPE: tuple[str, ...] = ("among", "all", "permanents")

#: The two tails of "<colour> is the most common color …", as ``(words, tied)``.
#: Both required — the bare superlative says nothing about a level board, and
#: the two tails are opposite answers there.
_CENSUS_TIE_TAILS: tuple[tuple[tuple[str, ...], bool], ...] = (
    (("or", "is", "tied", "for", "most", "common"), True),
    (("but", "isn't", "tied", "for", "most", "common"), False),
)


def accept_target_pronoun(stream: TokenStream) -> bool:
    """``it`` / ``that <noun>`` naming the object the guarded effect targets.

    "Destroy target creature if **it** shares a color with …" (Tsabo's
    Assassin) and "Return target permanent to its owner's hand if **that
    permanent** shares a color with …" (Barrin's Unmaking) are one referent in
    two spellings: the repeated noun restates what the effect in front already
    chose, which is the arrangement ``record_conditions`` keeps for "that land
    was nonbasic". Which object that is — a permanent, a spell — is the
    lowering's question (``pronoun_target_referent``), asked beside the effect.

    Consumes nothing unless one of the two is there.
    """
    if stream.accept_word("it"):
        return True
    mark = stream.mark()
    if stream.accept_word("that"):
        noun = stream.peek_word()
        if noun == "permanent" or noun in CARD_TYPES:
            stream.advance()
            return True
    stream.reset(mark)
    return False


def _accept_color_census_condition(stream: TokenStream) -> "ast.Condition | None":
    """A question about **the most common color among all permanents**, or
    None with the cursor untouched.

    Two printed askers of one count (``engine/color_census.py``):

    * "**white is** the most common color among all permanents **or is tied
      for most common**" — the five Invasion Djinns. A printed colour against
      the census.
    * "**it shares a color with** the most common color among all permanents
      **or a color tied for most common**" — Tsabo's Assassin, Barrin's
      Unmaking. The effect's own target against the census.

    Every word is required in both. The scope is what the count is *of*, and
    the tail is what the card says about a level board; a reader that stopped
    at the superlative would be picking one of those for the card.
    """
    # "…unless **either one is a color the other isn't**." (Dead Ringers.) The
    # relation with a target on *both* sides — the pair the guarded effect
    # announced — so it names neither and the lowering checks there are two.
    # Whole or not at all: every word is the clause, and the phrase opens on a
    # word no other condition here reads.
    if stream.accept_phrase(
        "either", "one", "is", "a", "color", "the", "other", "isn't",
    ):
        return ast.TargetsDifferInColor()
    mark = stream.mark()
    colour = stream.peek_word()
    if colour in COLOR_WORDS and stream.peek_word(1) == "is":
        stream.advance(2)
        if stream.accept_phrase("the", "most", "common", "color", *_CENSUS_SCOPE):
            for tail, tied in _CENSUS_TIE_TAILS:
                if stream.accept_phrase(*tail):
                    return ast.ColorIsMostCommon(COLOR_WORDS[colour], tied=tied)
        stream.reset(mark)
        return None
    if accept_target_pronoun(stream) and stream.accept_phrase(
        "shares", "a", "color", "with",
    ):
        if stream.accept_phrase(
            "the", "most", "common", "color",
            *_CENSUS_SCOPE, "or", "a", "color", "tied", "for", "most", "common",
        ):
            return ast.SharesMostCommonColor()
        # "…if it shares a color with **that permanent**" (Guard Dogs). The
        # same relation with one object on the far side instead of the census:
        # the permanent an earlier sentence of this effect chose. Read here
        # because the two clauses share every word up to this one, and a second
        # reader of "it shares a color with" would be a second opinion about
        # which object "it" is.
        if stream.accept_phrase("that", "permanent"):
            return ast.SharesColorWithChosenPermanent()
        # "…if it shares a color with **a creature you control**" (Jaded
        # Response). The relation once more, with a described set on the far
        # side: any permanent the noun phrase admits. Read last, because the
        # two clauses above open on "the" and "that", which no object phrase
        # behind an article does — and read whole, by the noun reader, or the
        # sentence is not this one: a phrase that left words behind it would be
        # a narrowing consumed and dropped.
        if stream.accept_word("a", "an"):
            try:
                matching = parse_object_filter(stream)
            except GrammarError:
                matching = None
            if matching is not None and (
                stream.exhausted or stream.at_punct(".", ",")
            ):
                return ast.SharesColorWithMatching(matching)
    stream.reset(mark)
    return None
