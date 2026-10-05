"""Lowering the shuffles: a library put back into a random order (CR 701.24).

Cut out of `lowering/zones.py` at Urza's Destiny's wave-1 **integration**, on
nobody's branch — two groups' additions to that module merely summed and took
it fourteen lines past the thousand-line guard. The seam is the one `zones`
already drew in prose: everything left there answers "which zone does this
object end up in", and a shuffle answers "what order is this library in now",
which is a different question about a zone nothing moved into.

Five shapes, and the axis between them is *what* is being shuffled in:
a graveyard (Feldon's Cane), the source itself from a trigger that has already
killed it, a chosen permanent (Rishadan Pawnshop, which arrived after this
paragraph said four), a hand (Winds of Change), and nothing at all — the bare
"Then that player shuffles" every search and strip ends with.

`_SHUFFLE_LIBRARY_PLAYERS` travels with them; `_REVEAL_TOP_PLAYERS`, its
identical twin, deliberately does not. The two frozensets hold the same four
seats for the same reason and are still two facts — a reveal opens a library
and a shuffle reorders one — so collapsing them would be a coincidence written
down as a rule.

No parse-side twin: the shuffle productions are spread across
`effects/library.py`, `effects/zones.py` and `effects/search.py`, none of which
is near its guard. That is the ordinary shape here rather than a fork —
`zones`, `library`, `mana` and `redirection` are all lowering families whose
parse halves stayed small.

The AST twin arrived at Planeshift's Phase 0: `ast/shuffles.py` holds the five
nodes lowered here and no other, cut out of `ast/board.py` under this module's
name. All five are *built* in `effects/zones.py`; what `effects/library.py` and
`effects/search.py` read is the word, inside a look or a search that ends with
one.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _describe_targets, _restrictions_beyond
from ._piles import _chosen_graveyard_cards



#: The seats a bare shuffle can name. "You" is the imperative's subject; the
#: other three are a player an earlier sentence of the same effect chose, which
#: the handler reads off the resolution's target. A reference outside this — an
#: "each opponent", say — is a loop the handler does not have, and a shuffle
#: taken on one library while the card names several is the direction nothing
#: crashes and the card is quietly a different card.
_SHUFFLE_LIBRARY_PLAYERS = frozenset(
    {"you", "that_player", "target_player", "target_opponent"}
)


def _lower_shuffle_graveyard_into_library(
    node: ast.ShuffleGraveyardIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Feldon's Cane. Whose graveyard is on the payload even though only one
    value is printed today — the alternative is a kind that would have to be
    replaced the first time a card says "target player's".

    "Shuffle **all creature cards** from your graveyard into your library."
    (Barishi.) The narrowed pile, on the key ``graveyard_card_matches``
    already reads — the same predicate the graveyard-to-hand returns ask, so
    "creature card" means one thing in this engine wherever it is printed. Only
    a phrase that predicate can test is admitted: the alternative is a filter
    parsed and dropped, which for this sentence is a card shuffling its owner's
    lands and spells back in as well.
    """
    payload: dict[str, object] = {"whose": node.whose.kind}
    if node.chosen is not None:
        # "**Target player shuffles up to three target cards** from their
        # graveyard into their library." (Gaea's Blessing.) The moving subset
        # chosen rather than described, with the payload half
        # ``put_graveyard_cards_on_library_top`` builds for the identical noun
        # phrase one destination over. ``graveyard_owner`` is the chosen seat
        # rather than the printed pronoun: CR 404.1 makes that seat's library
        # the only one those cards can be shuffled into.
        if node.whose.kind != "target_player":
            raise LoweringError(
                "a chosen-card graveyard shuffle names the player it targets",
                node=node,
            )
        payload["whose"] = payload["graveyard_owner"] = "target_player"
        payload.update(_chosen_graveyard_cards(node.chosen.filter, node.chosen, node))
        return (OracleInstruction("shuffle_graveyard_into_library", "", payload),)
    if node.cards is not None:
        filt = node.cards
        # Read field by field rather than through ``_filter_payload``, which
        # speaks the *battlefield* matcher's key names and refuses a
        # graveyard-scoped phrase outright. The reader here is
        # ``graveyard_card_matches``, whose keys these are — the same predicate
        # the graveyard-to-hand returns ask, so "creature card" means one thing
        # in this engine wherever it is printed.
        unread = _restrictions_beyond(
            filt,
            frozenset({"is_card", "zone", "zone_owner", "card_types",
                       "supertypes", "subtypes", "colors"}),
        )
        if unread:
            raise LoweringError(
                "the graveyard shuffle cannot narrow by: " + ", ".join(unread),
                node=node,
            )
        cards: dict[str, object] = {}
        if len(filt.card_types) > 1:
            cards["card_types"] = list(filt.card_types)
        elif filt.card_types:
            cards["card_type"] = filt.card_types[0]
        if filt.subtypes:
            cards["graveyard_subtypes"] = list(filt.subtypes)
        if filt.colors:
            cards["graveyard_colors"] = list(filt.colors)
        if filt.supertypes:
            cards["supertypes"] = list(filt.supertypes)
        if not cards:
            raise LoweringError(
                "the graveyard shuffle's noun phrase narrows nothing at all",
                node=node,
            )
        payload["cards"] = cards
    return (
        OracleInstruction("shuffle_graveyard_into_library", "", payload),
    )


def _lower_shuffle_source_into_library(
    node: ast.ShuffleSourceIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """"When this creature dies, shuffle **it** into its owner's library."
    (Alabaster Dragon.)

    The seat is on the payload for ``_lower_shuffle_graveyard_into_library``'s
    reason, and refused when it is not the owner's: CR 404.1 put the card in
    its owner's graveyard, so "its owner's library" is the one library this
    sentence can reach, and a card printing "your library" would be a different
    card the moment a creature changed hands.
    """
    if node.owner.kind != "owner":
        raise LoweringError(
            f"no handler shuffles this card into {node.owner.kind!r}'s library",
            node=node,
        )
    return (
        OracleInstruction("shuffle_source_card_into_library", "", {}),
    )


def _lower_shuffle_target_into_library(
    node: ast.ShuffleTargetIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """"{2}, {T}: Shuffle target nontoken permanent you control into its owner's
    library." (Rishadan Pawnshop.)

    The seat is refused when it is not the owner's, exactly as
    :func:`_lower_shuffle_source_into_library` refuses it and for a reason that
    bites harder here: this sentence names a *controller* ("you control") and a
    different *owner*, so a handler that shuffled into the activator's library
    would move a stolen permanent into the wrong deck.

    The printed noun phrase is described onto the payload rather than checked
    here — ``_describe_targets`` is what the picker enumerates from and what the
    handler re-asks at resolution (CR 608.2b), so a narrowing dropped at either
    end is an ability aimed at a permanent the card excludes. A phrase the
    matcher cannot test refuses at the compiler, which is what
    ``_describe_targets`` and the support gate arrange between them.
    """
    if node.owner.kind != "owner":
        raise LoweringError(
            f"no handler shuffles a permanent into {node.owner.kind!r}'s library",
            node=node,
        )
    if (
        not isinstance(node.target, ast.TargetSpec)
        or not node.target.targeted
        or node.target.quantifier != "target"
    ):
        # Only a chosen single object. Nothing enumerates this move over a set,
        # and a sweep spelled as a target would shuffle away whichever permanent
        # a targetless resolution defaulted to.
        raise LoweringError(
            "a shuffle into a library moves one chosen permanent", node=node
        )
    payload: dict[str, object] = {}
    _describe_targets(payload, node.target)
    return (
        OracleInstruction("shuffle_target_permanent_into_library", "", payload),
    )


def _lower_shuffle_hand_into_library(
    node: ast.ShuffleHandIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Winds of Change.

    Whose hands move is payload, the way the graveyard shuffle above carries
    whose graveyard does — and the draw rides the same instruction rather than
    following it, because the number it draws is the number this move made.
    Only the two subjects the handler loops over are admitted: "target player"
    would name a seat the handler does not resolve, and a subject it cannot
    resolve is a shuffle taken on the wrong library.
    """
    if node.whose.kind not in ("each_player", "you"):
        raise LoweringError(
            f"no handler shuffles {node.whose.kind!r}'s hand into their library",
            node=node,
        )
    if node.any_number:
        # "Shuffle **any number of** cards from your hand into your library,
        # then draw that many cards." (Credit Voucher.) The counted branch below
        # with the number left to the player, so it reaches the same handler and
        # the same prompt — what differs is that the prompt carries a ceiling
        # instead of an exact count.
        #
        # The trailing draw is legal *here* and refused below, and the
        # difference is real rather than an exception: behind a printed number
        # "that many" would be the same number said twice, and behind this one
        # the answer is the only place the number exists at all. So it rides the
        # instruction, exactly as the whole-hand branch's does — the number a
        # draw reads is the number the move made, and nothing else in the
        # sentence knows it.
        if node.then_draw_count is not None:
            raise LoweringError(
                "an open-ended shuffle draws what it moved, not a printed "
                "number",
                node=node,
            )
        if node.with_graveyard:
            raise LoweringError(
                "an open-ended shuffle takes cards from a hand alone", node=node
            )
        if node.whose.kind != "you":
            raise LoweringError(
                "an open-ended shuffle into a library is the controller's own "
                "hand",
                node=node,
            )
        return (
            OracleInstruction(
                "shuffle_hand_cards_into_library", "",
                {"any_number": True, "then_draw": node.then_draw},
            ),
        )
    if node.count is not None:
        # "Shuffle **a card** from your hand into your library."
        # (Lat-Nam's Legacy.) Its own kind rather than a count on the sweep
        # above, because a counted subset of a hidden zone is a *decision*
        # (CR 402.1: only its owner may look) where a whole hand is a move. The
        # handler arms the prompt that asks it; the sweep above has nothing to
        # ask.
        if node.then_draw or node.then_draw_count is not None:
            # "…then draws that many cards" counts what the whole-hand move
            # took. Behind a printed number the phrase would be that number
            # said twice, and no card prints the pair — so it refuses rather
            # than guessing which of the two the sentence meant.
            raise LoweringError(
                "a counted shuffle has no 'that many' to draw", node=node
            )
        if node.whose.kind != "you":
            raise LoweringError(
                "a counted shuffle into a library is the controller's own hand",
                node=node,
            )
        return (
            OracleInstruction(
                "shuffle_hand_cards_into_library", "", {"amount": node.count},
            ),
        )
    return (
        OracleInstruction(
            "shuffle_hand_into_library",
            "",
            {
                "whose": node.whose.kind,
                "then_draw": node.then_draw,
                # "…, **then draws seven cards**." (Time Spiral.) The printed
                # number, beside the flag rather than inside it: the flag means
                # "as many as moved" and this means "this many whatever moved",
                # and a handler handed one for the other draws a hand-sized grip
                # where the card prints a fixed one.
                **(
                    {"then_draw_count": node.then_draw_count}
                    if node.then_draw_count is not None else {}
                ),
                # "…their hand **and graveyard** into their library."
                # (Diminishing Returns.) A second pile in the same move, and a
                # flag on the same instruction rather than a second one for the
                # reason the node records: CR 701.24a shuffles the library once.
                "with_graveyard": node.with_graveyard,
            },
        ),
    )


def _lower_shuffle_library(node: ast.ShuffleLibrary) -> tuple[OracleInstruction, ...]:
    """"Then that player shuffles." (Prophecy.) CR 701.24 with nothing moving.

    Whose library is payload, exactly as the two shuffles above carry whose
    pile moves. ``that_player`` is deliberately **not** described as a target:
    it names a seat an earlier sentence of this same effect already chose, and
    describing it would raise a second picker for a target the spell has.
    """
    if node.whose.kind not in _SHUFFLE_LIBRARY_PLAYERS:
        raise LoweringError(
            f"no handler shuffles {node.whose.kind!r}'s library", node=node
        )
    payload: dict[str, object] = {"whose": node.whose.kind}
    if node.whose.kind in ("target_player", "target_opponent"):
        # A shuffle that *chooses* its player is the one spelling that needs a
        # picker; the sentence naming one an earlier step chose does not.
        _describe_targets(payload, node.whose)
    return (OracleInstruction("shuffle_library", "", payload),)
