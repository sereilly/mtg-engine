"""Parsing "separate … into two piles" — CR 700.3.

Every production here reads a **whole paragraph**: the sentence that makes the
piles and every sentence that says what becomes of them. "The pile of that
player's choice", "the other" and "the chosen piles" name what the first
sentence made, so read apart the later sentences dangle a referent nothing
binds — the reason Phyrexian Portal's face-down procedure is one production in
``effects/library.py``, stated there and true here.

What differs between the six printings is exactly four things, and each is
read into :class:`ast.SeparateIntoPiles` as a word rather than as a kind: what
is separated (an ordinary noun phrase, read by the ordinary noun parser), who
separates, who chooses, and the two fates. The fates are a closed list — each
is something ``engine/piles.py`` performs — so a printing that sent a pile
somewhere else refuses here rather than lowering onto a move nothing makes.

Both entry points decline **without consuming** until the words "into two
piles" have been read; past them the paragraph is this module's and a tail it
cannot finish is a refusal naming the sentence, never a partial reading.
"""

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..references import parse_target_spec
from ..stream import TokenStream


def _accept_into_two_piles(stream: TokenStream) -> bool:
    return stream.accept_phrase("into", "two", "piles")


def _same_objects(stream: TokenStream, separated: "ast.ObjectFilter") -> None:
    """Read the noun a fate sentence repeats, and hold it to the piles'.

    "Destroy all **creatures** in the pile …" behind "Separate all creatures
    …". The noun adds nothing — a pile holds only what was separated into it —
    but a sentence that named something *else* ("destroy all lands in the
    pile") would be a different card, so it is compared rather than skipped.
    """
    spec = parse_target_spec(stream)
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier != "all"
        or spec.filter.card_types != separated.card_types
    ):
        raise stream.error("expected the separated objects named again")


def _whose(separated: "ast.ObjectFilter") -> str:
    """The seat word a separated noun phrase prints, or "" when it prints none.

    "…target player controls" / "…that player controls" for permanents, and the
    possessive of the zone for cards ("in **your** graveyard"). Read here so the
    node carries the word; the lowering is what refuses one it has no seat for.
    """
    if separated.zone == "graveyard":
        owner = separated.zone_owner
        return owner.kind if owner is not None else ""
    return separated.controller or ""


def _parse_fates(
    stream: TokenStream, separated: "ast.ObjectFilter"
) -> tuple[str, str, str | None, bool]:
    """``(chooser, chosen_fate, other_fate, no_regeneration)`` for the
    sentences behind "…into two piles." where one pair of piles was made.
    """
    if not stream.accept_punct("."):
        raise stream.error("expected what becomes of the piles")
    # "Exile the pile of an opponent's choice and return the other to the
    # battlefield." (Death or Glory.)
    if stream.accept_phrase(
        "exile", "the", "pile", "of", "an", "opponent", "'s", "choice",
    ):
        if not stream.accept_phrase(
            "and", "return", "the", "other", "to", "the", "battlefield",
        ):
            raise stream.error("expected where the other pile goes")
        return "an_opponent", "exile", "battlefield", False
    # "Destroy all creatures in the pile of that player's choice. They can't be
    # regenerated." (Do or Die.)
    if stream.accept_word("destroy"):
        _same_objects(stream, separated)
        if not stream.accept_phrase(
            "in", "the", "pile", "of", "that", "player", "'s", "choice",
        ):
            raise stream.error("expected whose choice the destroyed pile is")
        no_regeneration = False
        mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "they", "can't", "be", "regenerated",
        ):
            no_regeneration = True
        else:
            stream.reset(mark)
        return "owner", "destroy", None, no_regeneration
    # "Only creatures in the pile of their choice can attack this turn."
    # (Fight or Flight.)
    if stream.accept_word("only"):
        _same_objects(stream, separated)
        if not stream.accept_phrase(
            "in", "the", "pile", "of", "their", "choice", "can", "attack",
            "this", "turn",
        ):
            raise stream.error("expected 'in the pile of their choice can attack this turn'")
        return "owner", "only_attackers", None, False
    raise stream.error("expected what becomes of the piles")


def parse_separate_into_piles(stream: TokenStream) -> "ast.Statement | None":
    """``Separate all <objects> into two piles. <fates>`` — or None, unconsumed.

    ``Separate all creatures target player controls into two piles. Destroy all
    creatures in the pile of that player's choice. They can't be regenerated.``
    (Do or Die.)

    ``Separate all creature cards in your graveyard into two piles. Exile the
    pile of an opponent's choice and return the other to the battlefield.``
    (Death or Glory.)

    ``…separate all creatures that player controls into two piles. Only
    creatures in the pile of their choice can attack this turn.`` (Fight or
    Flight.)

    ``For each defending player, separate all creatures that player controls
    into two piles and that player chooses one. Only creatures in the chosen
    piles can block this turn.`` (Stand or Fall.)

    The imperative has no printed subject, so CR 608.2c makes its controller
    the one who separates. Whose objects they are is the noun phrase's own
    ``controller`` word and is read off the filter by the lowering.
    """
    mark = stream.mark()
    per_defender = stream.accept_phrase("for", "each", "defending", "player")
    if per_defender:
        stream.accept_punct(",")
    if not stream.accept_word("separate"):
        stream.reset(mark)
        return None
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier != "all"
        or not _accept_into_two_piles(stream)
    ):
        stream.reset(mark)
        return None
    separated = spec.filter
    what = "graveyard" if separated.zone == "graveyard" else "battlefield"
    if per_defender:
        # "…and that player chooses one. Only creatures in the chosen piles can
        # block this turn." The choice is printed inside the first sentence
        # here, so the fate sentence names "the chosen piles" — plural, one per
        # defending player.
        if not stream.accept_phrase("and", "that", "player", "chooses", "one"):
            raise stream.error("expected 'and that player chooses one'")
        if not stream.accept_punct("."):
            raise stream.error("expected what becomes of the chosen piles")
        stream.expect_word("only")
        _same_objects(stream, separated)
        if not stream.accept_phrase(
            "in", "the", "chosen", "piles", "can", "block", "this", "turn",
        ):
            raise stream.error("expected 'in the chosen piles can block this turn'")
        return ast.SeparateIntoPiles(
            what=what, whose="each_defending_player", separator="you",
            chooser="owner", chosen_fate="only_blockers", filter=separated,
        )
    chooser, chosen_fate, other_fate, no_regeneration = _parse_fates(
        stream, separated,
    )
    return ast.SeparateIntoPiles(
        what=what, whose=_whose(separated), separator="you", chooser=chooser,
        chosen_fate=chosen_fate, other_fate=other_fate, filter=separated,
        no_regeneration=no_regeneration,
    )


def parse_each_player_separates(stream: TokenStream) -> "ast.Statement | None":
    """``Each player separates all nontoken lands they control into two piles.
    For each player, one of their piles is chosen by one of their opponents of
    their choice. Destroy all lands in the chosen piles. Tap all lands in the
    other piles.`` (Bend or Break) — or None, unconsumed.

    The only printing where the separator is not the controller: every player
    separates their **own**, and every player then picks which opponent
    chooses between their piles. Four sentences and one effect — the last two
    are simultaneous over every player's piles, which is why the fates are
    fields of the one node rather than two sweeps behind it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("each", "player", "separates"):
        return None
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier != "all"
        or not _accept_into_two_piles(stream)
    ):
        stream.reset(mark)
        return None
    separated = spec.filter
    if not stream.accept_punct("."):
        raise stream.error("expected who chooses each player's pile")
    if not stream.accept_phrase("for", "each", "player"):
        raise stream.error("expected 'for each player'")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "one", "of", "their", "piles", "is", "chosen", "by", "one", "of",
        "their", "opponents", "of", "their", "choice",
    ):
        raise stream.error("expected who chooses each player's pile")
    if not stream.accept_punct("."):
        raise stream.error("expected what becomes of the chosen piles")
    stream.expect_word("destroy")
    _same_objects(stream, separated)
    if not stream.accept_phrase("in", "the", "chosen", "piles"):
        raise stream.error("expected 'in the chosen piles'")
    if not stream.accept_punct("."):
        raise stream.error("expected what becomes of the other piles")
    stream.expect_word("tap")
    _same_objects(stream, separated)
    if not stream.accept_phrase("in", "the", "other", "piles"):
        raise stream.error("expected 'in the other piles'")
    return ast.SeparateIntoPiles(
        what="battlefield", whose="each_player", separator="owner",
        chooser="owner_opponent", chosen_fate="destroy", other_fate="tap",
        filter=separated,
    )


def parse_reveal_top_and_separate(stream: TokenStream) -> "ast.Statement | None":
    """``Reveal the top five cards of your library. An opponent separates those
    cards into two piles. Put one pile into your hand and the other into your
    graveyard.`` (Fact or Fiction) — or None, unconsumed.

    Tried before the reveal-top production, which reads the same four opening
    words and stops at the count: this declines without consuming on any other
    reveal, so every one of them keeps the reading it has.

    "Put **one pile**" names nobody, so CR 608.2c gives the choice to the
    spell's controller; "an opponent" is theirs to pick too (CR 608.2d), which
    the lowering states as a step of its own.
    """
    mark = stream.mark()
    if not stream.accept_phrase("reveal", "the", "top"):
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("cards", "of", "your", "library"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "an", "opponent", "separates", "those", "cards",
    ) or not _accept_into_two_piles(stream):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        raise stream.error("expected what becomes of the piles")
    if not stream.accept_phrase(
        "put", "one", "pile", "into", "your", "hand", "and", "the", "other",
        "into", "your", "graveyard",
    ):
        raise stream.error(
            "expected 'put one pile into your hand and the other into your graveyard'"
        )
    return ast.SeparateIntoPiles(
        what="library_top", whose="you", separator="an_opponent",
        chooser="you", chosen_fate="hand", other_fate="graveyard", count=count,
    )
