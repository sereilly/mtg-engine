"""Combat restrictions (CR 506, 509).

The two printed shapes the engine enforces: "can't attack unless defending
player controls a <land type>" and "can't be blocked by …". The land type and
the power threshold are *captured*, not baked into the production — which is
what lets a second card with the same template arrive needing no parser change
at all.
"""

from .. import ast
from ..stream import TokenStream
from ..phrases import _parse_duration


# The two printed combat restrictions the engine enforces (CR 506, 509). Both
# are already derived from raw text by engine/combat_restrictions.py for the
# legacy path; this production lets the *grammar* claim them, lowering to the
# same instruction kinds with the same payloads so the differential can hold
# the two to agreement.
#
# The land type and the power threshold are captured, not baked into the
# production, for the same reason they are payload rather than kind names: a
# card naming Mountain, or a threshold of 4, is the same restriction.
_BASIC_LAND_WORDS = ("plains", "island", "swamp", "mountain", "forest")


def _parse_cant_attack_or_block(
    stream: TokenStream, subject: ast.Recipient
) -> ast.Statement:
    """``<subject> can't attack unless defending player controls a <land>`` /
    ``<subject> can't block creatures with power N or greater``."""
    # "can't" is peeked, not consumed, so the fallback to _parse_cant_be (which
    # expects to read it itself) sees an untouched stream.
    mark = stream.mark()
    stream.expect_word("can't", "cannot")

    if stream.accept_word("attack"):
        if not stream.accept_phrase("unless", "defending", "player", "controls"):
            raise stream.error("expected 'unless defending player controls'")
        stream.expect_word("a", "an")
        land = stream.peek_word()
        if land not in _BASIC_LAND_WORDS:
            # A nonbasic or unknown type: the enforcing check scopes its search
            # to basic land types, so claiming this would promise more than the
            # engine does.
            raise stream.error("expected a basic land type")
        stream.advance()
        return ast.CombatRestriction(
            subject, "cant_attack_without_land_type", (("land_type", land),)
        )

    if stream.accept_word("block"):
        stream.expect_word("creatures")
        if not stream.accept_phrase("with", "power"):
            raise stream.error("expected 'with power'")
        token = stream.peek()
        if token is None or not token.text.isdigit():
            raise stream.error("expected a power threshold")
        power = token.text
        stream.advance()
        if not stream.accept_phrase("or", "greater"):
            raise stream.error("expected 'or greater'")
        return ast.CombatRestriction(
            subject, "cant_block_power_n_or_greater", (("power", int(power)),)
        )

    stream.reset(mark)
    return _parse_cant_be(stream, subject)


# Participles this production recognizes after "can't be". A closed list, so a
# restriction the grammar has never seen fails in the parser by name instead of
# being read as one of these.
_CANT_BE_ACTIONS = ("regenerated", "blocked")


def _parse_cant_be(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> can't be <participle> [duration]``.

    Note what is deliberately *not* consumed: a trailing exception clause
    ("… except by Walls", "… by Walls"). Those name creatures the restriction
    does not apply to, so swallowing them would turn a conditional restriction
    into an absolute one. Leaving the tokens makes the line fail the
    full-consumption invariant and fall back — Invisibility and Juggernaut stay
    visibly unclaimed rather than quietly becoming unblockable.
    """
    stream.expect_word("can't", "cannot")
    stream.expect_word("be")
    word = stream.peek_word()
    if word not in _CANT_BE_ACTIONS:
        raise stream.error("unrecognized \"can't be\" restriction")
    stream.advance()
    duration = _parse_duration(stream)
    return ast.CantBe(subject, word, duration)
