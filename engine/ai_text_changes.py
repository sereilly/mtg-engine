"""Which object a "target spell or permanent" cast names, and — for a text
change (CR 612) — which two words it names on it: the AI's half of
``engine/text_changes.py``.

"Change the text of target spell or permanent by replacing all instances of
one color word with another" (Sleight of Mind, Alter Reality), "…one basic
land type with another" (Magical Hack), either (Crystal Spray, and the
permanent-only Mind Bend and Whim of Volrath): the cast announces the two
words, as mana symbols (``queue_from_hand``'s ``old_color`` / ``new_color``).
No AI module supplied them, so an AI seat's cast changed nothing, its
rehearsal read a cast that changed nothing, and the seat never made one; and
the one-object chooser answered the union from its permanent half alone, so
neither a text change nor a Lace was ever aimed at a spell.

Two questions, asked of every object the engine's own enumeration offers:

* **which pairs of words** (:func:`word_pairs`): the word replaced is one the
  object's current text writes (``text_changes.current_text_card`` — a second
  change rewrites what the first wrote; the handler logs "had no effect" for
  any other), the replacement any other word of the vocabulary (the cards'
  ruling: "can't change a word to the same word");
* **what a pair is worth to the caster.** On a spell the rehearsal reads it
  whole — the copy resolves the stack, and "destroy target nonblack
  creature" rewritten to "nonwhite" is a Terror the rules counter (CR 608.2b)
  over the white creature it named. On a permanent most of it is what no
  standing sees (:func:`aimed_worth`): a Circle of Protection's colour, a
  protection, a landwalk, "destroy target black creature" each count what
  the *other* side has of the word, so a word is worth what it is aimed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ai_actions import (
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_spec,
)
from .ai_standing import CARD_WORTH
from .ai_weighed_cast import SPELL_TYPES
from .game import Game
from .models import CardDefinition
from .oracle import compile_card_oracle
from .text_changes import (
    COLOR_WORDS,
    LAND_TYPE_WORDS,
    UNTIL_END_OF_TURN,
    current_text_card,
)

#: The instruction a text change compiles to (``handlers/colors.py``).
TEXT_CHANGE_KIND = "mark_text_modified"

#: The text-change modes whose two words **the cast** announces. Artificial
#: Evolution's creature types are chosen as it resolves (its ruling), by the
#: resolution's own steps, so its cast names an object and nothing else.
ANNOUNCED_MODES = frozenset({"color_word", "land_type", "color_word_or_land_type"})

#: The vocabularies a mode may name its words from.
_VOCABULARIES = {
    "color_word": ("color_word",),
    "land_type": ("land_type",),
    "color_word_or_land_type": ("color_word", "land_type"),
}
_WORDS = {"color_word": COLOR_WORDS, "land_type": LAND_TYPE_WORDS}
_LAND_SYMBOL = {word: symbol for symbol, word in LAND_TYPE_WORDS.items()}

#: What one permanent a word is aimed at is worth to the side it is aimed
#: from: a Circle of Protection: Red facing three red creatures is three of
#: them. A fraction of a card, because a word aims at what a permanent *may*
#: do — the Circle still has to be paid for, the landwalker still has to
#: attack.
AIMED_WORTH = CARD_WORTH / 4

#: How many permanents a text change is rehearsed at once its pairs are
#: ranked: the best pair of each, the largest aims first.
OBJECTS_REHEARSED = 3

#: Below this a text change is not worth a card: what the rehearsal and the
#: aim read together must be a real gain, because every change of a word
#: that is written reads as *a* change (the record on the permanent).
_WORTH_FLOOR = 0.5

_REMINDER = re.compile(r"\([^)]*\)")

#: One pattern per word: bare, plural, "non…" (CR 612's "nonblack" is an
#: instance of "black") or compounded into a landwalk.
_PATTERNS = {
    (vocabulary, symbol): re.compile(rf"(?<![a-z])(?:non)?{word}(?:s|walk)?(?![a-z])")
    for vocabulary, words in _WORDS.items()
    for symbol, word in words.items()
}


@dataclass(frozen=True)
class ObjectChoice:
    """The object a "target spell or permanent" cast names — a permanent
    (``seat``, ``permanent_index``, ``permanent_ids``) or a spell
    (``stack_index``, engine bottom-first) — and for an announced text change
    the two words, as mana symbols (``old_color`` replaced by ``new_color``)."""

    seat: int
    permanent_index: "int | None" = None
    permanent_ids: "list[int] | None" = None
    stack_index: "int | None" = None
    old_color: "str | None" = None
    new_color: "str | None" = None


def _text_change_step(instructions):
    """The first text-change step among *instructions*, nested steps
    included, or None."""
    for instruction in instructions:
        if instruction.kind == TEXT_CHANGE_KIND:
            return instruction
        for key in ("steps", "then", "else", "action", "effect"):
            nested = (instruction.payload or {}).get(key)
            if isinstance(nested, (list, tuple)):
                found = _text_change_step([step for step in nested if hasattr(step, "kind")])
                if found is not None:
                    return found
    return None


def text_change_instruction(card: CardDefinition):
    """*card*'s text-change step as the candidate being built resolves it,
    or None for a card that changes no text."""
    return _text_change_step(_announced_steps(card, compile_card_oracle(card)))


def ability_text_change_mode(instruction) -> "str | None":
    """The mode of an **activated ability**'s text change when its
    activation announces the words (`ANNOUNCED_MODES`, CR 612 through CR
    602.2b: Balduvian Shaman's "replacing all instances of one color word
    with another"), else None — the ability's twin of
    :func:`announced_text_change_mode`."""
    step = _text_change_step([instruction]) if instruction is not None else None
    mode = (step.payload or {}).get("mode") if step is not None else None
    return mode if mode in ANNOUNCED_MODES else None


def announced_text_change_mode(card: CardDefinition) -> "str | None":
    """The mode of *card*'s text change when its cast announces the words
    (`ANNOUNCED_MODES`), else None — and None for a permanent spell, whose
    text change is an ability it has once it is on the battlefield
    (Balduvian Shaman's), never part of its cast."""
    if card.primary_type not in SPELL_TYPES:
        return None
    instruction = text_change_instruction(card)
    mode = (instruction.payload or {}).get("mode") if instruction is not None else None
    return mode if mode in ANNOUNCED_MODES else None


#: A clause about its controller's own side ("Activate only if you control a
#: Swamp", "Black creatures you control get +1/+1"): its words reach what
#: the controller has, not what the other seats have. "Of your choice" and
#: "your opponents" are not about that side.
_OWN_SIDE = re.compile(r"\byou control\b|\byour (?!choice|opponent)\w")
_CLAUSES = re.compile(r"[.\n]")

#: Which side a word is aimed at: the controller's opponents, or the
#: controller's own (`_OWN_SIDE`).
AIMED, OWN = "aimed", "own"


def rules_words(card: CardDefinition) -> frozenset:
    """``(vocabulary, symbol, side)`` for every colour word and basic land
    type *card*'s rules text and keywords write, outside its name (CR 612.2:
    a name is not a word a text change reaches) and its reminder text —
    *side* `OWN` in a clause about its controller's own side, `AIMED`
    otherwise. Its type line is not here: a land's own type is what it is,
    not something it aims at."""
    text = _REMINDER.sub(" ", card.oracle_text or "")
    if card.name:
        text = re.sub(re.escape(card.name), " ", text, flags=re.IGNORECASE)
    clauses = [clause.lower() for clause in _CLAUSES.split(text)]
    clauses += [keyword.lower() for keyword in card.keywords or ()]
    found = set()
    for clause in clauses:
        side = OWN if _OWN_SIDE.search(clause) else AIMED
        found.update(
            (*word, side) for word, pattern in _PATTERNS.items() if pattern.search(clause)
        )
    return frozenset(found)


def _type_line_land_words(card: CardDefinition) -> frozenset:
    type_line = (card.type_line or "").lower()
    return frozenset(
        symbol for symbol in LAND_TYPE_WORDS
        if _PATTERNS[("land_type", symbol)].search(type_line)
    )


class _Census:
    """What each seat has that a word could reach — its permanents of each
    colour and its lands of each basic land type, through the layers — and
    each permanent's words, read once for one decision."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self.counts: dict[tuple, int] = {}
        self._words: dict[int, frozenset] = {}
        for permanent in game.all_permanents():
            seat = game.controller_index_of(permanent)
            keys = [(seat, "color_word", str(symbol).upper()) for symbol in permanent.effective_colors]
            keys += [
                (seat, "land_type", _LAND_SYMBOL[land_type])
                for land_type in permanent.basic_land_types if land_type in _LAND_SYMBOL
            ]
            for key in keys:
                self.counts[key] = self.counts.get(key, 0) + 1

    def presence(self, seat: int, vocabulary: str, symbol: str, retyped=None) -> int:
        """How many of *seat*'s permanents a word of *vocabulary* reaches.
        *retyped* is ``(seat, old symbol, new symbol)``: one of that seat's
        lands read as though its type had been rewritten."""
        count = self.counts.get((seat, vocabulary, symbol), 0)
        if retyped is not None and vocabulary == "land_type" and retyped[0] == seat:
            count += (symbol == retyped[2]) - (symbol == retyped[1])
        return count

    def words_of(self, permanent) -> frozenset:
        key = permanent.permanent_id
        if key not in self._words:
            self._words[key] = rules_words(current_text_card(permanent))
        return self._words[key]


def _aim(census: _Census, caster: int, controller: int, words, retyped=None) -> float:
    """What *words* — on a permanent *controller* controls — reach, for
    *caster*. An `AIMED` word reaches its controller's opponents: on the
    caster's own permanent it is worth what the opponents have of it, on an
    opponent's it costs what the caster has of it. An `OWN` word reaches its
    controller's side: worth what the caster has of it on the caster's own
    permanent, and costing what the opponent has of it on the opponent's."""
    game = census.game
    opponents = [
        other for other in range(len(game.players))
        if other != caster and not game.players[other].lost
    ]
    total = 0.0
    for vocabulary, symbol, side in words:
        if controller == caster:
            seats, sign = (opponents if side == AIMED else [caster]), 1
        else:
            seats, sign = ([caster] if side == AIMED else [controller]), -1
        total += sign * sum(
            census.presence(seat, vocabulary, symbol, retyped) for seat in seats
        )
    return total


def _swapped(words, vocabulary: str, old: str, new: str) -> frozenset:
    return frozenset(
        (vocabulary, new, side) if (kind, symbol) == (vocabulary, old) else (kind, symbol, side)
        for kind, symbol, side in words
    )


def _live_vocabulary(subject, mode: str, old: str) -> "str | None":
    """The vocabulary a change of the symbol *old* rewrites on *subject*:
    the one the mode names, or — "a color word **or** a basic land type" —
    the first whose word is written (``live_text_change_vocabularies``' order,
    which is the order a seat nobody asks answers in)."""
    effective = current_text_card(subject)
    written = " ".join(
        (effective.type_line or "", effective.oracle_text or "", *(effective.keywords or ()))
    ).lower()
    for vocabulary in _VOCABULARIES[mode]:
        if _WORDS[vocabulary][old] in written:
            return vocabulary
    return None


def aimed_worth(
    game: Game, caster: int, permanent, mode: str, old: str, new: str,
    census: "_Census | None" = None,
) -> float:
    """What rewriting *old* to *new* on *permanent* is worth to *caster*,
    beyond anything a standing reads (``ai_standing.seat_standing``): the
    change in what its words are aimed at (:func:`_aim`) — and, where the word
    is a land's own type, the change in what every other permanent's land
    words are aimed at (a swampwalk the opponent's new Swamp now reaches)."""
    vocabulary = _live_vocabulary(permanent, mode, old)
    if vocabulary is None:
        return 0.0
    census = census or _Census(game)
    controller = game.controller_index_of(permanent)
    words = census.words_of(permanent)
    delta = (
        _aim(census, caster, controller, _swapped(words, vocabulary, old, new))
        - _aim(census, caster, controller, words)
    )
    if vocabulary == "land_type" and old in _type_line_land_words(current_text_card(permanent)):
        retyped = (controller, old, new)
        for other in game.all_permanents():
            land_words = frozenset(
                word for word in census.words_of(other) if word[0] == "land_type"
            )
            if other is permanent or not land_words:
                continue
            owner = game.controller_index_of(other)
            delta += (
                _aim(census, caster, owner, land_words, retyped)
                - _aim(census, caster, owner, land_words)
            )
    return AIMED_WORTH * delta


def word_pairs(game: Game, caster: int, subject, mode: str, *, on_stack: bool) -> list[tuple[str, str]]:
    """Every ``(old, new)`` a text change of *mode* could name on *subject*
    and change something: the old word one its current text writes, the new
    any other word. A land of the caster's own is offered no change to its
    type line — what it makes is a price no reading here weighs."""
    effective = current_text_card(subject)
    words = rules_words(effective)
    own = not on_stack and game.controller_index_of(subject) == caster
    type_words = frozenset() if own else _type_line_land_words(effective)
    pairs: list[tuple[str, str]] = []
    for vocabulary in _VOCABULARIES[mode]:
        for old in _WORDS[vocabulary]:
            if not any(word[:2] == (vocabulary, old) for word in words) and not (
                vocabulary == "land_type" and old in type_words
            ):
                continue
            for new in _WORDS[vocabulary]:
                if new != old and (old, new) not in pairs:
                    pairs.append((old, new))
    return pairs


def text_change_worth(
    game: Game, seat: int, card: CardDefinition, announcement: dict,
) -> "tuple[float, float]":
    """``(now, lasting)``: what a cast of *card* with *announcement* is worth
    to *seat* that a standing cannot see — the words a text change rewrites
    on a permanent (:func:`aimed_worth`). Lasting unless the change ends with
    the turn (Crystal Spray, Whim of Volrath). ``(0, 0)`` for every other
    cast, and for a change named on a spell: the rehearsal resolves the spell
    and reads all of that itself."""
    old = (announcement.get("old_color") or "").upper()
    new = (announcement.get("new_color") or "").upper()
    if not old or not new or announcement.get("target_stack_index") is not None:
        return 0.0, 0.0
    mode = announced_text_change_mode(card)
    ids = announcement.get("target_permanent_ids") or ()
    permanent = game.permanent_by_id(ids[0]) if mode is not None and ids else None
    if permanent is None:
        return 0.0, 0.0
    worth = aimed_worth(game, seat, permanent, mode, old, new)
    if (text_change_instruction(card).payload or {}).get("duration") == UNTIL_END_OF_TURN:
        return worth, 0.0
    return worth, worth


def _rehearsed(game: Game, caster: int, card: CardDefinition, announcement: dict):
    """The swing of casting *card* with *announcement*, read through the fight
    where that is the reading — or None when the cast is refused, changes
    nothing, leaves nothing, or cannot be rehearsed."""
    from .ai_scoring import (_leaves_nothing, _rehearse_announcement,
                             _weighed_through_the_fight)

    rehearsal = _weighed_through_the_fight(
        game, caster, card, announcement,
        _rehearse_announcement(game, caster, card, announcement),
    )
    if (
        rehearsal is None or not rehearsal.accepted or not rehearsal.changed
        or _leaves_nothing(rehearsal)
    ):
        return None
    return rehearsal.swing


def _stack_slots(game: Game, entries: list[dict]) -> list[int]:
    """The engine (bottom-first) stack indices among *entries*, topmost first."""
    depth = len(game.stack)
    slots = []
    for entry in entries:
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if 0 <= index < depth and index not in slots:
            slots.append(index)
    return sorted(slots, reverse=True)


def ranked_word_choices(
    game: Game, caster: int, entries: list[dict], mode: str,
) -> "list[ObjectChoice]":
    """The permanents among *entries* (the engine's own enumeration, the
    picker's vocabulary) a text change of *mode* is worth naming, each with
    the pair of words that aims best there (:func:`aimed_worth`), the largest
    aims first — the best :data:`OBJECTS_REHEARSED` of them, for the caller
    to rehearse. Empty when no word on any of them aims at anything.

    One ranking for both ways a text change is announced: a cast
    (:func:`choose_object_or_spell`) and an activated ability
    (``ai_abilities._text_change_activation``: Balduvian Shaman)."""
    census = _Census(game)
    ranked: list[tuple[float, int, ObjectChoice]] = []
    for entry in entries:
        if entry.get("kind") != "permanent":
            continue
        permanent = game.permanent_at(entry["seat"], entry["index"])
        permanent_id = game.permanent_id_of(permanent)
        if not isinstance(permanent_id, int):
            continue
        weighed = [
            (aimed_worth(game, caster, permanent, mode, old, new, census), old, new)
            for old, new in word_pairs(game, caster, permanent, mode, on_stack=False)
        ]
        if not weighed:
            continue
        aim, old, new = max(weighed, key=lambda row: row[0])
        if aim > 0.0:
            ranked.append((aim, -len(ranked), ObjectChoice(
                entry["seat"], entry["index"], [permanent_id], old_color=old, new_color=new,
            )))
    return [
        choice for _aim, _order, choice
        in sorted(ranked, key=lambda row: row[:2], reverse=True)[:OBJECTS_REHEARSED]
    ]


def ability_text_change_worth(
    game: Game, seat: int, instruction, permanent_id: "int | None",
    old: "str | None", new: "str | None",
) -> "tuple[float, float]":
    """``(now, lasting)``: what an activated ability's text change naming
    *old* → *new* on the permanent *permanent_id* is worth to *seat* that a
    standing cannot see (:func:`aimed_worth`) — :func:`text_change_worth`'s
    twin for an ability, read off its *instruction* rather than a card.
    ``(0, 0)`` where no words or no permanent are named."""
    mode = ability_text_change_mode(instruction)
    if mode is None or not old or not new or permanent_id is None:
        return 0.0, 0.0
    permanent = game.permanent_by_id(permanent_id)
    if permanent is None:
        return 0.0, 0.0
    worth = aimed_worth(game, seat, permanent, mode, old.upper(), new.upper())
    step = _text_change_step([instruction])
    if (step.payload or {}).get("duration") == UNTIL_END_OF_TURN:
        return worth, 0.0
    return worth, worth


#: What a text change must be worth, read and aimed together, to be made: the
#: floor a cast is held to (`_WORTH_FLOOR`), named for an ability's chooser.
WORTH_FLOOR = _WORTH_FLOOR


def choose_object_or_spell(
    game: Game, caster: int, card: CardDefinition, preferred_seat: int,
    *, x_value: "int | None" = None,
) -> "ObjectChoice | tuple | None":
    """The object a cast of *card* names where its target may be a spell
    (``spell_or_permanent``: the Laces, the text changers), or whose text
    change announces its words (any target) — an :class:`ObjectChoice`;
    ``()`` when nothing it could name is worth the cast; None for every other
    card, which the one-object chooser answers.

    A text change weighs every object with each pair of words it could name
    there: a spell's by rehearsal, a permanent's ranked by what its words
    aim at and the best few rehearsed with them. A Lace — or a text change
    whose words are chosen as it resolves — weighs the permanent the
    one-object chooser picks against each spell, by rehearsal.
    """
    from .ai_scoring import _announcement
    from .ai_targets import _choose_single_object_target

    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict):
        return None
    mode = announced_text_change_mode(card)
    union = spec.get("kind") == "spell_or_permanent"
    if mode is None and not union:
        return None
    entries = game._enumerate_targets(
        caster, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    stack_slots = _stack_slots(game, entries) if union else []

    def announced(seat, *, index=None, ids=None, stack=None, words=(None, None)):
        return {
            **_announcement(
                card, target=seat, caster=caster, permanent_index=index,
                permanent_ids=ids, x_value=x_value, stack_index=stack,
            ),
            "old_color": words[0], "new_color": words[1],
        }

    best: "list" = []

    def consider(swing, choice) -> None:
        if swing is not None and (not best or swing > best[0]):
            best[:] = [swing, choice]

    if mode is None:
        if not stack_slots:
            # Nothing on the stack to weigh it against: the permanent the
            # one-object chooser names, as it names it.
            return None
        single = _choose_single_object_target(
            game, caster, card, preferred_seat, x_value=x_value,
        )
        if single:
            seat, index, ids = single
            consider(
                _rehearsed(game, caster, card, announced(seat, index=index, ids=ids)),
                ObjectChoice(seat, index, ids),
            )
        for slot in stack_slots:
            seat = game.stack[slot].caster_index
            consider(
                _rehearsed(game, caster, card, announced(seat, stack=slot)),
                ObjectChoice(seat, stack_index=slot),
            )
        return best[1] if best else ()

    for slot in stack_slots:
        item = game.stack[slot]
        for old, new in word_pairs(game, caster, item, mode, on_stack=True):
            consider(
                _rehearsed(game, caster, card, announced(
                    item.caster_index, stack=slot, words=(old, new),
                )),
                ObjectChoice(item.caster_index, stack_index=slot, old_color=old, new_color=new),
            )
    for choice in ranked_word_choices(game, caster, entries, mode):
        consider(
            _rehearsed(game, caster, card, announced(
                choice.seat, index=choice.permanent_index, ids=choice.permanent_ids,
                words=(choice.old_color, choice.new_color),
            )),
            choice,
        )
    if not best or best[0] < _WORTH_FLOOR:
        return ()
    return best[1]


__all__ = [
    "AIMED_WORTH",
    "ANNOUNCED_MODES",
    "ObjectChoice",
    "WORTH_FLOOR",
    "ability_text_change_mode",
    "ability_text_change_worth",
    "aimed_worth",
    "announced_text_change_mode",
    "choose_object_or_spell",
    "ranked_word_choices",
    "rules_words",
    "text_change_instruction",
    "text_change_worth",
    "word_pairs",
]
