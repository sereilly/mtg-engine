"""Which zone a noun phrase is scoped to, and whose zone it is.

"target creature card **from your graveyard**", "cards **from an opponent's
graveyard**", "a creature card **in a graveyard**". Split out of
`postmodifiers` at the thousand-line guard, along the boundary that module's
own docstring draws in its list of relations: a postmodifier names a relation
to the controller, to another object, **or to a zone**, and this is the last of
the three.

It is a family rather than an arbitrary cut because both halves of the question
are one answer. CR 404.1 puts a card in the graveyard of the player who owns
it, so "an opponent's graveyard" is a restriction on *which pile* and a
statement about *whose* in one phrase — and a reader that took the zone without
the seat would name a pile in the wrong player's zone, which is the silent
wrongness this grammar exists to refuse. Both halves are therefore recorded
together, and a possessive nothing here lists refuses the whole noun phrase.

Below `postmodifiers`, which calls it and is never imported back, and it reaches
nothing above `references`' own floors — `ast` for the player reference and the
vocabularies for the noun after "the graveyard of".

The name is `lowering/zones.py`'s word, and the two are the same subject asked
from opposite ends: that module decides which zone an object **goes to**, this
one reads which zone an object is **already in**. They are in different
packages and neither imports the other, so the mirror re-forms rather than
colliding — the one thing `statics` could not do.
"""

from __future__ import annotations

from . import ast
from .stream import TokenStream
from .vocabulary import CARD_TYPES, CREATURE_TYPES, singular as _singular


# Zones a noun phrase can be scoped to ("target creature card **from your
# graveyard**"). The battlefield is deliberately absent: it is already the
# default, so consuming "from the battlefield" here would leave no trace that
# the phrase had been read at all — exactly the silent-drop this parser exists
# to prevent. A production that needs it should say so explicitly.
_ZONE_NOUNS = frozenset({"graveyard", "hand", "library", "exile"})


def _parse_zone_owner_of(stream: TokenStream) -> "ast.PlayerRef | None":
    """The player named after "from the <zone> **of** …", or None.

    Its own small reader rather than a call into ``references.parse_player_ref``
    because that module sits *above* this one — it reads noun phrases, which are
    built from what this file parses — and the phrases printed in this position
    are not the ones a recipient clause prints. Widening it means adding a
    spelling here, and a spelling nothing lists refuses the whole noun phrase
    rather than silently naming some other player's graveyard.

    "…the graveyard of **the player who controlled that creature the last time
    it became blocked by that Wall**" (Glyph of Reincarnation) is a seat no read
    of the board can answer: control is CR 613 layer 2 and moves, and by the
    time the sentence is read the creature is a card in a graveyard with no
    controller at all. The block seam freezes the seat as the block happens, and
    this referent names that record — "the last time" being exactly the
    overwrite-on-each-block that seam performs. Every word is required, and the
    noun after "by that" is checked rather than skipped: a dropped word here
    leaves a phrase naming some other player, and a reanimation out of the wrong
    graveyard is a different card.
    """
    probe = stream.mark()
    if stream.accept_phrase(
        "the", "player", "who", "controlled", "that", "creature",
        "the", "last", "time", "it", "became", "blocked", "by", "that",
    ):
        noun = stream.peek_word()
        if noun is not None and (
            _singular(noun) in CARD_TYPES or _singular(noun) in CREATURE_TYPES
        ):
            stream.advance()
            return ast.PlayerRef("controller_when_blocked")
    stream.reset(probe)
    return None


def accept_zone_scope(stream: TokenStream, d) -> bool | None:
    """Read a `from <zone>` / `in <zone>` scope onto *d*, if one is here.

    True when one was read and the postmodifier loop should carry on;
    False when the words are not a zone scope at all and the loop must stop
    (the cursor is left where it was); None when the cursor was not at
    "from"/"in" and nothing was looked at.

    Three answers rather than two because the caller's loop has three
    outcomes and always did: `continue`, `break`, and fall through to the
    next branch. Collapsing the last two would make a phrase this cannot
    finish fall into the readers behind it, which is how a half-read
    possessive ends up naming somebody else's graveyard.
    """
    if not stream.at_word("from", "in"):
        return None
    # "from your graveyard" / "in a graveyard" — which zone the objects
    # are in, and whose. Both halves are recorded: a handler that only
    # searches the caster's own graveyard must be able to refuse
    # "from a graveyard" rather than search the wrong one.
    probe = stream.mark()
    stream.advance()
    owner: ast.PlayerRef | None = None
    if stream.accept_word("your"):
        owner = ast.PlayerRef("you")
    # "their <zone>", and the spelled-out "that player's <zone>" (Storm
    # Seeker): one node for both, because `parse_player_ref` already reads
    # "they" as an alias of "that player", and a second kind here would be
    # a second answer every count lowering had to learn.
    elif stream.accept_word("their") or stream.accept_phrase("that", "player", "'s"):
        owner = ast.PlayerRef("owner")
    # "from **its owner's** graveyard" (Reincarnation). The same
    # referent `_parse_zone` already reads on the destination side, and
    # the same kind: "the owner of the object this sentence is about".
    # Which object that is depends on the sentence, and is the
    # lowering's question rather than the noun parser's.
    elif stream.accept_phrase("its", "owner", "'s"):
        owner = ast.PlayerRef("owner")
    # "from **target player's** graveyard" (Drafna's Restoration): a
    # chosen player rather than a fixed one, and a *second* target on the
    # same line — the cards are targets too.
    elif stream.accept_phrase("target", "player", "'s"):
        owner = ast.PlayerRef("target_player")
    # "in **target opponent's** graveyard" (Spoils of Evil). The same
    # chosen seat with CR 115.4's own-seat exclusion, and its own kind
    # rather than `target_player`, because that exclusion is the whole
    # difference: read as "target player" the card would let its caster
    # count their own graveyard.
    elif stream.accept_phrase("target", "opponent", "'s"):
        owner = ast.PlayerRef("target_opponent")
    # "from **defending player's** graveyard" (Rysorian Badger). CR
    # 506.2's seat, which the *combat* named rather than the sentence:
    # nothing is chosen, so it is neither of the two target spellings
    # above, and the lowering admits it only under a trigger whose fire
    # site froze one (`_events._DEFENDING_PLAYER_EVENTS`).
    elif stream.accept_phrase("defending", "player", "'s"):
        owner = ast.PlayerRef("defending_player")
    # "from **an opponent's** graveyard" (Misinformation). CR 601.2c
    # chooses nobody here — the *cards* are the targets and the pile is
    # wherever they lie — so it is neither of the two "target" seats
    # above, and it carries the kind ``parse_player_ref`` already gives
    # the bare article one layer up. What it says is a restriction on
    # which piles the cards may be chosen from, which the lowering
    # hands to the picker.
    elif stream.accept_phrase("an", "opponent", "'s"):
        owner = ast.PlayerRef("opponent")
    # "in **the chosen player's** graveyard" (Haunting Apparition). The seat
    # the source picked as it entered (CR 614.1c), recorded on that permanent —
    # so it is a seat nothing about *this* sentence chooses and the reader must
    # be handed the source to resolve it. Its own kind for that reason: read as
    # ``owner`` it would count the pile the cards happen to lie in, which for a
    # graveyard is every seat's, and read as ``you`` it would count the
    # controller's own. ``ast.PlayerRef`` has documented the kind since Lost
    # Order of Jarkeld printed the *battlefield* half of the same possessive.
    elif stream.accept_phrase("the", "chosen", "player", "'s"):
        owner = ast.PlayerRef("chosen_player")
    # "from **a player's** graveyard" (Lodestone Bauble). The same
    # unchosen seat with no exclusion on it, and ``owner`` is exactly
    # what it means: a card in a graveyard is in the graveyard of the
    # player who owns it (CR 404.1), so "a player's graveyard" and "the
    # graveyard of whoever owns these cards" name one pile. The same
    # kind "its owner's" and "their" above already carry, for that
    # reason and not as an alias of convenience.
    elif stream.accept_phrase("a", "player", "'s"):
        owner = ast.PlayerRef("owner")
    else:
        stream.accept_word("a", "an", "the")
    noun = stream.peek_word()
    if noun in _ZONE_NOUNS:
        stream.advance()
        # "from **the graveyard of** <player>" (Glyph of
        # Reincarnation) — the possessive said the other way round.
        # Tried only when the possessive spellings above found nothing,
        # so a phrase naming its owner twice cannot quietly keep the
        # second answer; and the referent has to be one this file
        # reads, because "the graveyard of" followed by words nothing
        # claims names a graveyard that cannot be found.
        if owner is None and stream.accept_word("of"):
            owner = _parse_zone_owner_of(stream)
            if owner is None:
                stream.reset(probe)
                return False
        d.zone = noun
        d.zone_owner = owner
        return True
    stream.reset(probe)
    return False
