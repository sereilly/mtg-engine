"""What a mana-producing ability has already done this turn.

"At the beginning of each of your main phases, **if you haven't added mana with
this ability this turn**, you may add X mana of any one color…" (Carpet of
Flowers.) CR 603.4's intervening-if over a record no board holds: nothing about
the enchantment, the pool or the turn's history says which *ability* the mana
came from, so the ability has to write it down as it resolves.

Both halves live here for the reason every other paired record in this engine
does — ``engine/noted_mana.py`` one clause over, ``ONCE_ONLY_TALLY_MARK`` one
rule over. The write site and the read site have to agree about a string, and a
literal spelled in two files is two chances to disagree; here the disagreement
cannot be written.

**A turn stamp, not a swept flag.** ``begin_turn_bookkeeping`` clears a dozen
per-turn records and every one of them is a chance to forget the thirteenth;
stamping the turn instead makes "this turn" a comparison rather than a sweep,
which is exactly what ``activation_restrictions.ACTIVATION_TALLY_MARK`` does for
CR 602.5's "only once each turn" and for the same reason. A permanent that left
and came back is a new object (CR 400.7) with no metadata, which is also the
rule rather than a shortcut: what returned is a different permanent, so its
ability has added nothing.

**Keyed per permanent, not per printed line**, and that is the one honest
limitation — two Carpets each keep their own record, but a permanent carrying
*two* abilities that both print the clause would count them together. No card
does; ``SourceAbilityActivations`` records the identical trade-off for the
identical reason, and the fix if one is ever printed is the per-line key
``once_only_activations`` already keeps beside it rather than a second store
here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .game import Game

#: Where the record lives on the permanent: ``{record name: turn number}``.
MANA_ADDED_MARK = "mana_added_with_ability"

#: The payload key that tells ``add_mana_from_text`` to write one, and the
#: *name* it writes under. On the instruction rather than inferred from the
#: card, because "with this ability" is a claim about one printed line and only
#: the lowering that read that line knows it was made — every other mana
#: instruction in the pool writes nothing and costs nothing.
MANA_RECORD_PAYLOAD_KEY = "records_mana_added"

#: The one record name the pool prints. A value rather than a bare ``True`` so
#: a second such clause is a second name instead of a second key.
MANA_ADDED_WITH_THIS_ABILITY = "this_ability"


def note_mana_added(game: "Game", source, record: str) -> None:
    """Stamp this turn onto *source*'s record under *record*.

    A source that has left the battlefield writes nothing: there is no object
    for the next check to read it off, and inventing a store would be a record
    about a permanent that no longer exists.
    """
    if source is None or not record:
        return
    stamps = source.metadata.setdefault(MANA_ADDED_MARK, {})
    if isinstance(stamps, dict):
        stamps[str(record)] = game.turn


def added_mana_this_turn(game: "Game", source, record: str) -> bool:
    """Whether *source* has already added mana under *record* this turn."""
    if source is None or not record:
        return False
    stamps = source.metadata.get(MANA_ADDED_MARK)
    if not isinstance(stamps, dict):
        return False
    return stamps.get(str(record)) == game.turn


__all__ = [
    "MANA_ADDED_MARK",
    "MANA_ADDED_WITH_THIS_ABILITY",
    "MANA_RECORD_PAYLOAD_KEY",
    "added_mana_this_turn",
    "note_mana_added",
]
