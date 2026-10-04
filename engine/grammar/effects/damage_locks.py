"""The sentences that say a damage event may **not** be modified (CR 615.1's
negative and CR 614.9's).

"Damage that would be dealt to <subject> this turn can't be prevented or dealt
instead to another permanent or player" (Whippoorwill), and the same eleven-word
predicate said of one spell's own damage (Lava Burst).

Split out of ``prevention`` when that module crossed the thousand-line guard on
Soltari Guerrillas' redirect, along the line ``lowering/prevention.py``'s own
section header had already drawn and named: *the lock*. It is not a shield and
not a redirect — it is a sentence **about** the two registries that modify a
damage event, and it lowers to a mark that both of them read. Which is exactly
why it can leave without coupling anything: nothing in ``prevention`` or
``redirection`` calls into here and nothing here calls into either of them, and
the one thing the three had in common — the eleven printed words — is defined
here once and read by both of this module's productions.

A **parse-only family**, like ``search``, ``reveal`` and ``text_changes`` before
it, and for their reason read the other way round: the words are where the work
is. Both sentences below lower to one ``mark_damage_unpreventable``-shaped
instruction apiece, which is nowhere near a module of its own, so a near-empty
``lowering/damage_locks.py`` would buy back the symmetry and cost the thing
symmetry is for. The lowering halves stay beside the shields they forbid.
"""

from .. import ast
from ..readers import accept_source_reference
from ..references import parse_recipient
from ..stream import TokenStream
from ..durations import _parse_duration
from ..phrases import parse_bound_subject


def _parse_damage_cant_be_prevented(
    stream: TokenStream,
) -> "ast.DamageCantBePreventedOrRedirected | None":
    """``Damage that would be dealt to <subject> <duration> can't be prevented
    or dealt instead to another permanent or player.`` (Whippoorwill.)

    Returns None with the cursor untouched for anything else opening with
    "damage", so every other sentence about damage keeps its own reader.

    **Both** halves of the printed clause are required. "Can't be prevented"
    alone is a different, weaker card, and a reader that stopped there would
    leave every redirection working while reporting the line claimed — the
    dropped-rider bug class, in the direction that lets the damage walk away.
    """
    mark = stream.mark()
    if not stream.accept_word("damage"):
        return None
    if not stream.accept_phrase("that", "would", "be", "dealt", "to"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream) or parse_bound_subject(stream)
    if subject is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if not accept_cant_be_prevented_tail(stream):
        stream.reset(mark)
        return None
    return ast.DamageCantBePreventedOrRedirected(subject, duration)


def accept_cant_be_prevented_tail(stream: TokenStream) -> bool:
    """``can't be prevented or dealt instead to another permanent or player``.

    The clause's whole predicate, shared by the two sentences that print it:
    Whippoorwill's, which says it of a creature for a turn, and Lava Burst's
    ``If <source> would deal damage to a creature, that damage …``, which says
    it of one spell's own damage. One reader, because reading eleven words in
    two places is two places for the pair of them to come apart — and it is
    exactly the pair that matters. "Can't be prevented" alone is a weaker card
    whose redirections all still work, so a half-read tail is the dropped-rider
    bug in the direction that lets the damage walk away.

    Consumes nothing unless the whole tail is there; the caller rewinds its own
    opening.
    """
    mark = stream.mark()
    for word in (
        "can't", "be", "prevented", "or", "dealt", "instead", "to", "another",
        "permanent", "or", "player",
    ):
        if not stream.accept_word(word):
            stream.reset(mark)
            return False
    return True


def parse_source_damage_lock(stream: TokenStream) -> bool:
    """``If <the source> would deal damage to a creature, that damage can't be
    prevented or dealt instead to another permanent or player.`` (Lava Burst.)

    True when the whole sentence was read, cursor left after it; False with the
    cursor untouched otherwise.

    The subject must be the ability's **own source**. The clause is a statement
    about which effects may modify this object's damage, and the only damage
    the resolution can mark that way is the damage it is itself dealing — a
    sentence naming some other object would be a lock nothing here can arm, so
    it refuses rather than being read as this one.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    if not accept_source_reference(stream):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("would", "deal", "damage", "to", "a", "creature"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("that", "damage"):
        stream.reset(mark)
        return False
    if not accept_cant_be_prevented_tail(stream):
        stream.reset(mark)
        return False
    return True
