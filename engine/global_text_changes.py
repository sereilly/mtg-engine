"""Board-wide text changes (CR 612, layer 3): a static ability that rewrites
the text of **every** spell and permanent.

"All instances of color words in the text of spells and permanents are
changed to the chosen color word." (Swirl the Mists.) The single-object text
changes (Sleight of Mind, Magical Hack, Crystal Spray) are one-shot effects an
instruction records on its target (``engine/text_changes.py``); this one is a
static ability of a permanent, so it applies to whatever is a spell or a
permanent for as long as its source is on the battlefield — "Swirl the Mists'
ability also affects spells that are cast and permanents that enter after
Swirl the Mists enters" and "This effect lasts as long as Swirl the Mists is
on the battlefield. It ends as soon as Swirl the Mists leaves the
battlefield." (Rulings 2004-12-01.)

**Written as records, kept in step with the board.** Every reader of what an
object says already asks one fold — ``Permanent.effective_card`` for a
permanent, ``text_changes.spell_text_card`` for a spell — over the records in
``TEXT_CHANGE_EFFECTS`` / ``StackItem.text_change_effects``. So the static's
effect is one :data:`~engine.text_changes.COLOR_WORD_ALL` record per source on
each of them, carrying the source's ``permanent_id`` (:data:`SOURCE_KEY`), the
chosen word and the source's timestamp (CR 613.7a: a static ability's effect
has its object's timestamp), which orders it against every one-shot change by
CR 613.7. :func:`sync_board_text_changes` is the one writer: it runs at the
start of the board-wide pass (``BoardStaticsMixin._refresh_global_statics`` —
layer 3 ahead of the pass's layer 4, and the pass an entering permanent is
folded through, CR 614.12) and as a spell is put on the stack
(``_stack_push_object``), and it rewrites a holder's board records to exactly
the board's — so a source that left takes its records with it and one that
entered adds its own. A record carried from a spell onto the permanent it
became (``carry_spell_text_changes``) is the same record, and the next pass
leaves it as it is.

One reader of the printed line (:func:`all_color_words_line`) for every
caller: the parse claim, the support gate, the coverage channel and the
writer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .text_changes import (ALL_WORDS, COLOR_WORD_ALL, COLOR_WORDS,
                           TEXT_CHANGE_EFFECTS)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent


#: Swirl the Mists' second line, in full.
ALL_COLOR_WORDS_TEXT = (
    "all instances of color words in the text of spells and permanents are "
    "changed to the chosen color word"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use
#: for the line.
BOARD_TEXT_CHANGE_CLAIM = "board_text_change"

#: The record key naming the permanent whose static ability wrote a record —
#: what tells a board-written record from a one-shot one, and what the writer
#: keeps in step with the board.
SOURCE_KEY = "source_id"

#: Where the source's chosen colour is (``entry_choices.CHOSEN_COLOR_KEY``,
#: the record "As this enchantment enters, choose a color word" writes — a
#: mana symbol). Spelled here so this module imports nothing that imports it.
_CHOSEN_COLOR_KEY = "chosen_color"


def all_color_words_line(line: str) -> bool:
    """Whether *line* is, in full, Swirl the Mists' board-wide change."""
    return (
        " ".join((line or "").split()).strip().lower().rstrip(".")
        == ALL_COLOR_WORDS_TEXT
    )


def _prints_the_change(permanent: "Permanent") -> bool:
    """Whether *permanent*, as layers 1 and 3 leave it, prints the line. A
    substring test first: nearly every permanent on nearly every board says
    nothing about colour words."""
    text = permanent.effective_card.oracle_text or ""
    if "color words" not in text:
        return False
    return any(all_color_words_line(line) for line in text.splitlines())


def board_text_change_records(permanents: Iterable["Permanent"]) -> list[dict]:
    """One :data:`~engine.text_changes.COLOR_WORD_ALL` record per permanent
    among *permanents* that prints the line and has chosen its word, oldest
    source first. A source still waiting on its entry choice (CR 614.12a) has
    chosen nothing, and rewrites nothing yet."""
    records: list[dict] = []
    for permanent in permanents:
        if not _prints_the_change(permanent):
            continue
        word = COLOR_WORDS.get(
            str(permanent.metadata.get(_CHOSEN_COLOR_KEY) or "").upper()
        )
        if word is None:
            continue
        records.append({
            "kind": COLOR_WORD_ALL,
            "from": ALL_WORDS,
            "to": word,
            # CR 613.7a: the static ability's effect has its object's
            # timestamp — the one CR 613.7 orders it by among the one-shot
            # changes on each holder.
            "timestamp": int(permanent.timestamp),
            "label": permanent.card.name,
            SOURCE_KEY: permanent.permanent_id,
        })
    return sorted(records, key=lambda record: record["timestamp"])


def _record_list(holder) -> list | None:
    """*holder*'s recorded text changes — a permanent's metadata key, or a
    spell's ``StackItem.text_change_effects`` — or None for an ability on the
    stack (CR 113.3: not a spell, and its text is its source's)."""
    metadata = getattr(holder, "metadata", None)
    if isinstance(metadata, dict):
        return metadata.get(TEXT_CHANGE_EFFECTS)
    if getattr(holder, "is_ability", False):
        return None
    return getattr(holder, "text_change_effects", None)


def _sync_holder(holder, wanted: list[dict]) -> bool:
    """Make *holder*'s board-written records exactly *wanted*, leaving every
    one-shot record where it is. True if anything changed."""
    if getattr(holder, "is_ability", False):
        return False
    held = _record_list(holder) or []
    board = [record for record in held if record.get(SOURCE_KEY) is not None]
    if board == wanted:
        return False
    kept = [record for record in held if record.get(SOURCE_KEY) is None]
    kept.extend(dict(record) for record in wanted)
    metadata = getattr(holder, "metadata", None)
    if isinstance(metadata, dict):
        if kept:
            metadata[TEXT_CHANGE_EFFECTS] = kept
        else:
            # Popped rather than left empty, so the fold's fast path
            # (``models.fold_channel_set``) goes back to skipping it.
            metadata.pop(TEXT_CHANGE_EFFECTS, None)
    else:
        holder.text_change_effects = kept
    return True


def sync_board_text_changes(game, permanents: Iterable["Permanent"]) -> bool:
    """Bring every permanent in *permanents* and every spell on the stack in
    step with the board's text-changing statics. True if any record moved.

    *permanents* is the pass's list — the battlefield, plus a permanent about
    to enter when the pass is folding one (CR 614.12). The sources are asked
    of the same list, so a Swirl that is itself entering rewrites nothing
    until it has chosen its word."""
    permanents = list(permanents)
    wanted = board_text_change_records(permanents)
    moved = False
    for holder in [*permanents, *getattr(game, "stack", ())]:
        moved |= _sync_holder(holder, wanted)
    return moved


def stamp_board_text_changes(game, item) -> bool:
    """Write the board's text-changing statics onto *item*, a spell just put
    on the stack — the moment it becomes a spell (CR 601.2a), so whatever reads
    what it says from then on reads the changed text. True if any record
    moved. An ability is left alone."""
    return _sync_holder(item, board_text_change_records(game.all_permanents()))


def has_board_text_change_source(permanents: Iterable["Permanent"]) -> bool:
    """Whether any of *permanents* prints a board-wide text change — what the
    entering fold asks before running its pass at all."""
    return any(_prints_the_change(permanent) for permanent in permanents)


__all__ = [
    "ALL_COLOR_WORDS_TEXT", "BOARD_TEXT_CHANGE_CLAIM", "SOURCE_KEY",
    "all_color_words_line", "board_text_change_records",
    "has_board_text_change_source", "stamp_board_text_changes",
    "sync_board_text_changes",
]
