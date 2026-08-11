"""The battlefield: destruction, bouncing, tapping, control.

Return-to-zone, destroy, tap/untap, gain control, and `_parse_that_object` —
the back-reference a delayed effect uses to name the permanent its trigger
bound ("destroy *that creature* at end of combat").

These productions read a zone through `phrases._parse_zone`; they do not define
one, because "search your library" needs the same fragment and neither family
should own the other's vocabulary.
"""

from .. import ast
from ..nouns import (parse_recipient)
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES)
from ..phrases import _parse_zone


def _parse_gain_control(stream: TokenStream) -> ast.GainControl | None:
    """``Gain control of <subject> for as long as you control this <permanent>.``

    Returns None — cursor untouched — unless the line really opens "gain
    control": "gains flying", "you gain 3 life" and "gains control of this
    creature" (Ghazbán Ogre, whose subject comes first) all begin with the same
    verb and are read elsewhere.

    The duration clause is *required*, and only the one shape a handler
    implements is admitted. An untimed "gain control of target creature" is a
    permanent control change; a differently-timed one (Old Man of the Sea's two
    conditions) reverts on things nothing here watches. Both would be this
    production's sentence with the ending changed, so both have to fail rather
    than borrow the linked duration.
    """
    mark = stream.mark()
    stream.expect_word("gain")
    if not stream.accept_word("control"):
        stream.reset(mark)
        return None
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to gain control of")
    if not stream.accept_phrase("for", "as", "long", "as", "you", "control", "this"):
        raise stream.error(
            "no handler for a control change without the source-linked duration"
        )
    # The noun after "this" names the source's own type and adds nothing the
    # payload carries, but it still has to be consumed for the line to be
    # accounted for in full.
    if stream.peek_word() is None:
        raise stream.error("expected the permanent the control change is linked to")
    stream.advance()
    return ast.GainControl(subject, "while_you_control_source")


def _parse_return(stream: TokenStream) -> ast.Statement:
    """``Return <objects> [from <zone>] to <zone>`` (CR 400.7).

    One production for Raise Dead, Regrowth, Resurrection and Unsummon, which
    the legacy registry needed three separately-ordered substring rules for —
    and which it told apart by probing for ``"creature card" not in text``. The
    source zone rides on the noun phrase (``engine/grammar/nouns.py``), because
    "target creature card from your graveyard" is one noun phrase; the
    destination is parsed here.
    """
    stream.expect_word("return")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to return")
    if not stream.accept_word("to"):
        raise stream.error("expected a destination zone after 'return'")
    destination = _parse_zone(stream)

    from_zone: ast.Zone | None = None
    if isinstance(subject, ast.TargetSpec) and subject.filter.zone != "battlefield":
        from_zone = ast.Zone(subject.filter.zone, subject.filter.zone_owner)
    return ast.ReturnToZone(subject, destination, from_zone)


def _parse_destroy(stream: TokenStream) -> ast.Statement:
    """``destroy <objects> [. It can't be regenerated.]``

    One production covers "destroy target creature", "destroy all lands",
    "destroy target tapped creature", and "destroy all Plains" — the
    distinction lives in the noun phrase's quantifier and filter. The legacy
    registry needed five separate rules with hand-ordered precedence numbers to
    keep "destroy all creatures" from being eaten by "destroy target".
    """
    stream.expect_word("destroy")
    subject = _parse_that_object(stream) or parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to destroy")

    # "…at end of combat" (CR 603.7). Only this one delay: a destruction
    # deferred to the next end step is a different handler, so leaving those
    # tokens unconsumed is what keeps Stone Giant and Nettling Imp failing
    # loudly instead of being destroyed a step early.
    delay = "end_of_combat" if stream.accept_phrase("at", "end", "of", "combat") else ""

    no_regen = False
    mark = stream.mark()
    stream.accept_punct(".", ",")
    if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
        "they", "can't", "be", "regenerated"
    ):
        no_regen = True
    else:
        stream.reset(mark)
    return ast.Destroy(subject, no_regen=no_regen, delay=delay)


def _parse_that_object(stream: TokenStream) -> ast.TargetSpec | None:
    """``that <card type>`` — the object a trigger already named.

    Not a target: the trigger bound it when it fired, so nothing is chosen on
    resolution. It gets its own quantifier rather than being read as an ordinary
    noun phrase, so a lowering written for "target creature" can never receive
    it — the two reach completely different handlers, and the ones that take a
    bound object read it out of the trigger's context instead of the payload.

    Deliberately local to the destroy production. The phrase turns up all over
    the pool ("tap that creature", "that player discards"), and teaching the
    shared noun parser to claim it would let every one of those lines lower
    through a filter naming a card type nobody bound.
    """
    mark = stream.mark()
    if not stream.accept_word("that"):
        return None
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.TargetSpec("that", ast.ObjectFilter(card_types=(noun,)))


def _parse_tap_untap(stream: TokenStream) -> ast.Statement:
    """``tap <objects>`` / ``untap <objects>`` / ``tap or untap <objects>``.

    The disjunction (Twiddle) is read here rather than as two statements joined
    by "or": both directions act on the *same* chosen target and only one of
    them happens, so a ``Conjunction`` would tap the permanent and then untap
    it. Only "tap or untap" is a disjunction — "untap or tap" is not printed on
    any card, and inventing it would accept text no card carries.
    """
    verb = stream.expect_word("tap", "untap").text
    either_way = False
    if verb == "tap":
        mark = stream.mark()
        if stream.accept_word("or") and stream.accept_word("untap"):
            either_way = True
        else:
            stream.reset(mark)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error(f"expected something to {verb}")
    if either_way:
        return ast.TapOrUntap(subject)
    return ast.Tap(subject) if verb == "tap" else ast.Untap(subject)
