"""Lowering token and emblem creation (CR 111, CR 114).

Split out of ``lowering/game.py`` when Fallen Empires took that module to
1,006 — and, like every other cap breach in that wave, by additions that
merely summed rather than by one change. The line is the one CR draws and
the one ``engine/tokens.py`` already draws one package over: a token is an
**object the game creates** (CR 111.1), where everything left in ``game``
changes the state a *player* is in — life, extra turns, winning, losing,
ante. The two halves share ``_stamp_token_count``, which comes across whole
because both token branches read it and nothing else does.

**No parse-side mirror**, for the reason `zones`, `types`, `destruction` and
`counter_removal` already record: ``effects/game.py`` reads a token line as
one production over a shared body vocabulary and is nowhere near the cap.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ...tokens import default_token_name
from .. import ast
from ..errors import LoweringError
from ._common import (_amount_payload, _describe_targets, _filter_payload,
                      _restrictions_beyond)


def _title(words: str) -> str:
    """Title-case a lexed vocabulary word, preserving multiword entries."""
    return " ".join(part.capitalize() for part in words.split())


def _lower_create_copy_token(
    node: ast.CreateCopyToken,
) -> tuple[OracleInstruction, ...]:
    """"Create a token that's a copy of target creature you control."
    (Sublime Epiphany.)

    The filter is carried, not collapsed: "**you control**" is half the card,
    and a copy token made from an opponent's creature is a different and much
    better spell. Checked against what the resolver can test, the same gate
    every targeted effect goes through — a phrase the matcher cannot answer
    would be a restriction the handler silently ignores.
    """
    if node.subject.quantifier != "target":
        raise LoweringError("the copy token copies a chosen permanent", node=node)
    payload: dict[str, object] = {"count": _amount_payload(node.count)}
    described = _filter_payload(node.subject.filter)
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if leftover:
        raise LoweringError(
            "the copy token cannot test this restriction: " + ", ".join(sorted(leftover)),
            node=node,
        )
    if described:
        payload["filter"] = described
    _describe_targets(payload, node.subject)
    return (OracleInstruction("create_copy_token", "", payload),)


def _lower_create_token(
    node: ast.CreateToken, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Create a 1/1 colorless Insect artifact creature token with flying named
    Wasp." (The Hive.)

    ``create_token`` builds the token's ``CardDefinition`` from the payload
    (engine/tokens.py), so this is pure characteristic transcription: the type
    line is re-rendered in the order the card printed it, and each optional key
    is emitted only when the card states it — matching the legacy rule, whose
    Hive payload carries no ``colors`` entry for a colourless token and no
    ``count`` for a single one.

    An unnamed token takes its CR 111.4 name — its subtype(s) plus the word
    "Token" ("Dwarf Berserker Token") — through ``default_token_name``, the
    one naming rule every token maker shares. Two shapes still refuse rather
    than guess:

    * **A token with neither a printed name nor a subtype.** CR 111.4 has
      nothing to build a name from.
    * **A token with no creature type at all.** ``make_token_card`` always
      builds a creature card, and a type line with no card types would come out
      as a bare subtype the loader could not classify.
    """
    # A *predefined* token (CR 111.10) is named, typed and worded by the table
    # in `engine/tokens.py`, so it needs none of the transcription below — and
    # it has no P/T, which every check below assumes.
    if node.oracle_text is not None:
        payload: dict[str, object] = {
            "name": node.name,
            "type_line": (
                " ".join(_title(w) for w in node.types)
                + (" — " + " ".join(_title(w) for w in node.subtypes) if node.subtypes else "")
            ),
            "oracle_text": node.oracle_text,
        }
        if node.colors:
            payload["colors"] = node.colors
        _stamp_token_count(payload, node)
        return (OracleInstruction("create_token", "", payload),)
    if "creature" not in node.types:
        raise LoweringError("make_token_card only builds creature tokens", node=node)
    if node.counted_pt is None and (node.power is None or node.toughness is None):
        raise LoweringError("a creature token has a printed power/toughness", node=node)
    if node.name:
        name = _title(node.name)
    elif node.subtypes:
        name = default_token_name(node.subtypes)
    else:
        raise LoweringError(
            "a token with neither a printed name nor a subtype has no CR 111.4 "
            "name to take",
            node=node,
        )

    # CR 205.4a — supertypes first, then the card types. Rendered rather than
    # dropped because ``CardDefinition.is_legendary`` reads the type line, and
    # the legend rule (CR 704.5j) reads that.
    type_line = " ".join(_title(word) for word in node.supertypes + node.types)
    if node.subtypes:
        type_line += " — " + " ".join(_title(word) for word in node.subtypes)

    payload: dict[str, object] = {
        "name": name,
        # "Create an **X/X** … token, where X is the number of …" (Experimental
        # Overload). The where-clause wrapping this sentence stamps the count
        # onto the instruction and the executor resolves it into the context's
        # X before the handler runs — so the payload says "x" and the handler
        # reads a number, exactly as a pump or a counted damage does. Both
        # halves, because the production admitted them only as the *same*
        # variable.
        "power": "x" if node.counted_pt is not None else node.power,
        "toughness": "x" if node.counted_pt is not None else node.toughness,
        "type_line": type_line,
    }
    if node.colors:
        payload["colors"] = node.colors
    if node.keywords:
        payload["keywords"] = tuple(_title(word) for word in node.keywords)
    # Printed abilities in quotes. Gated on the compiler being able to read
    # them: a token carrying an ability nothing implements is a token that
    # silently lacks it, which is exactly the shape the support gate exists to
    # refuse — and it is refused *here*, so the whole card reports unsupported
    # rather than the token arriving half-built.
    if node.granted_lines:
        from ...tokens import token_line_supported

        for line in node.granted_lines:
            if not token_line_supported(line):
                raise LoweringError(
                    f"nothing implements the token's ability {line!r}", node=node
                )
        payload["oracle_text"] = chr(10).join(node.granted_lines)
    if node.recipient_players:
        payload["recipient_players"] = node.recipient_players
    count = _stamp_token_count(payload, node)
    # "…that are tapped and attacking" (Basri Ket): entry state the handler
    # stamps as the tokens arrive.
    if node.tapped:
        payload["tapped"] = True
    if node.attacking:
        payload["attacking"] = True
    if node.recipient is not None:
        # "Its controller creates …" (Angelic Ascension, Secure the Scene):
        # the token goes to the controller the exile step of this same effect
        # recorded — so that step must exist, exactly as "that much" demands
        # its damage producer.
        if node.recipient not in produced:
            raise LoweringError(
                "back-reference to the exiled permanent's controller with no "
                "exile in this effect",
                node=node,
            )
        payload["recipient"] = node.recipient
    return (OracleInstruction("create_token", "", payload),)


def _lower_create_emblem(node: ast.CreateEmblem) -> tuple[OracleInstruction, ...]:
    """"You get an emblem with "<ability>"." (CR 114.2.) The text is the whole
    payload; the compiler's planeswalker gate has already verified it reads as
    a supported triggered ability before any card carrying it can compile."""
    return (OracleInstruction("create_emblem", "", {"text": node.text}),)


def _stamp_token_count(payload: dict, node: "ast.CreateToken"):
    """Record how many tokens to make, and return it.

    Three shapes, and they are three because the *number* comes from three
    different places: a printed count, the firing event's own tally, and a
    history of what died. Shared between the predefined and transcribed token
    branches so a count added to one is a count the other gets too.
    """
    if isinstance(node.per_death, ast.DiedThisTurn):
        # "…for each nontoken creature that died this turn" (Gadrak). A tally
        # rather than a scan: the creatures counted are exactly the ones no
        # battlefield still holds. Which tally is decided by the phrase — the
        # engine keeps a nontoken one beside the game-wide one, because a token
        # dying is a real creature death and a *different* number.
        filt = node.per_death.filter
        leftover = _restrictions_beyond(filt, frozenset({"card_types", "nontoken"}))
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the death tally counts creatures and nothing narrower", node=node
            )
        history = (
            "nontoken_creatures_died_this_turn" if filt.nontoken
            else "creatures_died_this_turn"
        )
        if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
            raise LoweringError(
                "a per-death token count multiplies one token, not several",
                node=node,
            )
        payload["count"] = {"history": history}
        return payload["count"]
    if isinstance(node.count, ast.ThatMuch):
        # "create that many … tokens" — the count is the firing event's own
        # number (a delayed attack trigger's matching attackers), recorded by
        # the firing site in the resolution scratchpad.
        payload["count"] = "trigger_count"
        return "trigger_count"
    count = _amount_payload(node.count)
    if count != 1:
        payload["count"] = count
    return count


# ---------------------------------------------------------------------------
# Ante and setting a life total
# ---------------------------------------------------------------------------


#: Which seats a printed player reference names, in the vocabulary every
#: recipient payload in the engine already uses. Shared by the two lowerings
#: below so the ante and the life-total rewrite of one card cannot disagree
#: about who "that player" is.


