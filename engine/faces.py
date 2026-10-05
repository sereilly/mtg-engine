"""A card with more than one face (CR 709: split cards).

The pool's first multi-face layout, and the seam every later one is meant to
land on. The whole design is one sentence: **a face is a card**. Each face of a
multi-face card is derived, once, as a ``CardDefinition`` of its own — its own
name, mana cost, mana value, colours, type line and rules text — and *that* is
the object the compiler reads and the stack holds.

Why that shape and not a face index beside the card:

* **CR 709.3b gives it away.** "While on the stack, only the characteristics of
  the half being cast exist." Every reader of a spell — a counterspell's filter,
  ``_stack_item_colors``, a mana-value comparison, the serializer — already
  takes ``item.card`` and reads its fields. If the card *is* the half, all of
  them are right without learning anything; a face index is a second fact each
  of them has to remember to consult, and forgetting it is silent.
* **The compiler already knows how to read a card.** A half is a normal-layout
  card whose name is its own ("Assault deals 2 damage to any target" is a
  self-reference to the *half's* name), so ``compile_card_oracle`` reads it with
  no face-aware path at all and caches one program per half.
* **CR 709.4 is the other direction, and it is one function.** Everywhere but
  the stack the card is the whole card, with both names, the combined cost and
  every type. So a half that leaves the stack becomes its whole card again —
  :func:`whole_card`, asked at the zone seams (``put_card_into_hand`` /
  ``_library`` / ``_graveyard``, ``_bin_spell_card``) rather than at each of the
  places a spell's card can be sent.

What a reader has to learn is therefore small and loud: *a multi-face card is
not itself castable*. ``compile_card_oracle`` hands back a program with no
instructions for the whole card (it has no text of its own to compile), the
cast path refuses a whole split card naming its halves (CR 709.3 — the player
chooses), and anything that wants "the spells this card can be cast as" asks
:func:`castable_faces`.

**Casting is by name, and a split card has two** (CR 709.4a). The engine and
the wire both name a spell by its card name, so a half is cast by *its* name:
``cast_from_hand(seat, "Assault")`` finds the Assault // Battery in hand and
puts Assault on the stack. :func:`spell_named` is that lookup, and every site
that used to compare ``card.name == card_name`` to find the card being cast
asks it instead.

Out of scope, deliberately, and each would be its own layout entry here: fuse
(CR 702.102, both halves on the stack as one spell with the combined
characteristics), split *permanents* (CR 709.5's shared type line and locked
halves), and every other multi-face layout (flip, transform, modal DFC,
adventure, meld). ``CAST_FACE_LAYOUTS`` is where the next one is admitted.
"""

from __future__ import annotations

import dataclasses
import re

from .models import CardDefinition

#: Layouts whose faces are each a spell the player chooses between as the card
#: is cast (CR 709.3). The compiler's ``SUPPORTED_LAYOUTS`` admits exactly these
#: on top of the single-face ones, so a layout listed here is a claim that the
#: cast path, the zone seams and the instruments all read its faces.
CAST_FACE_LAYOUTS = frozenset({"split"})

_SYMBOL = re.compile(r"\{([^}]+)\}")
_COLOR_ORDER = "WUBRG"


def _mana_value(mana_cost: str) -> float:
    """CR 202.3 off a printed cost: digits count themselves, X counts zero
    everywhere but the stack (CR 107.3g), a hybrid symbol counts its larger
    half (CR 202.3f) and every other symbol counts one."""
    total = 0
    for symbol in _SYMBOL.findall(mana_cost or ""):
        parts = symbol.upper().split("/")
        best = 0
        for part in parts:
            if part.isdigit():
                best = max(best, int(part))
            elif part in ("X", "Y", "Z"):
                best = max(best, 0)
            elif part == "P":
                continue
            else:
                best = max(best, 1)
        total += best
    return float(total)


def _cost_colors(mana_cost: str) -> tuple[str, ...]:
    """CR 202.2: an object is the colour of each mana symbol in its cost."""
    found = set()
    for symbol in _SYMBOL.findall(mana_cost or ""):
        for part in symbol.upper().split("/"):
            if part in _COLOR_ORDER:
                found.add(part)
    return tuple(color for color in _COLOR_ORDER if color in found)


def _face_keywords(card: CardDefinition, oracle_text: str) -> tuple[str, ...]:
    """The whole card's ingested keywords that this face's text prints.

    The ingest keeps keywords per card, not per face, and a keyword belongs to
    the half that prints it — a card whose one half has flash does not give the
    other half flash.
    """
    lowered = oracle_text.lower()
    return tuple(
        keyword for keyword in card.keywords
        if re.search(rf"\b{re.escape(keyword.lower())}\b", lowered)
    )


def is_multi_face(card) -> bool:
    """Whether *card* is a whole card whose faces are cast separately."""
    return (
        getattr(card, "layout", "normal") in CAST_FACE_LAYOUTS
        and bool(getattr(card, "faces", ()))
    )


def face_cards(card) -> tuple[CardDefinition, ...]:
    """Each face of a multi-face *card* as a card of its own; ``()`` otherwise.

    Built once per card **object** and kept on it, so the halves have the same
    identity every time they are asked for — a deck repeats one immutable
    definition per copy, and a stack item compared by identity must find the
    same half the cast path put there.
    """
    if not is_multi_face(card):
        return ()
    cached = card.__dict__.get("_face_cards")
    if cached is not None:
        return cached
    raw_faces = card.raw.get("card_faces") if isinstance(card.raw, dict) else None
    built = []
    for index, face in enumerate(card.faces):
        colors = _cost_colors(face.mana_cost)
        cmc = _mana_value(face.mana_cost)
        raw = dict(card.raw) if isinstance(card.raw, dict) else {}
        raw.pop("card_faces", None)
        if isinstance(raw_faces, list) and index < len(raw_faces):
            raw.update(raw_faces[index])
        raw.update({
            "name": face.name,
            "mana_cost": face.mana_cost,
            "cmc": cmc,
            "type_line": face.type_line,
            "oracle_text": face.oracle_text,
            "colors": list(colors),
            "layout": "normal",
        })
        built.append(
            dataclasses.replace(
                card,
                name=face.name,
                mana_cost=face.mana_cost,
                cmc=cmc,
                type_line=face.type_line,
                oracle_text=face.oracle_text,
                colors=colors,
                keywords=_face_keywords(card, face.oracle_text),
                raw=raw,
                power=face.power,
                toughness=face.toughness,
                layout="normal",
                faces=(),
                face_of=card,
            )
        )
    result = tuple(built)
    # ``cached_property``'s own trick: a frozen dataclass refuses ``setattr``
    # but its instance dict is an ordinary dict, and nothing here is a field —
    # so equality, ``replace`` and the repr never see it.
    card.__dict__["_face_cards"] = result
    return result


def is_face(card) -> bool:
    """Whether *card* is one face of a multi-face card (a split card's half)."""
    return getattr(card, "face_of", None) is not None


def whole_card(card):
    """The card *card* is a face of, or *card* itself (CR 709.4).

    What every zone but the stack holds. Asked wherever a spell's card is put
    somewhere, so a half never sits in a hand, a library, a graveyard or exile.
    """
    parent = getattr(card, "face_of", None)
    return parent if parent is not None else card


def castable_faces(card) -> tuple:
    """The spells *card* can be cast as (CR 709.3): its faces if it has them,
    and otherwise the card itself. Never empty."""
    return face_cards(card) or (card,)


def compilation_units(cards) -> list:
    """*cards* as the cards whose **text compiles**: each single-face card
    itself, and each face of a multi-face card in its place (CR 709.3a).

    The one iterator for a census whose question is about rules text — what a
    line parses to, which instructions a program holds, what an ability is
    labelled, which picker a target derives, whether a printed phrase is
    enforced. A split card handed to such a census *whole* has an empty text
    box and a program with no instructions, so the census examines it, finds
    nothing, and reports the card clean: blind, not red. ``for card in
    catalog`` is the loop that does that; ``for card in
    compilation_units(catalog)`` is its replacement.

    Not for a question about a **card** — a deck slot, a draw, a verification
    row, a colour identity, the supported verdict a player is shown — which is
    asked of the whole card (CR 709.4). ``tests/engine/test_face_blind_guards.py``
    holds the tests and scripts to the distinction.

    A list, in pool order with a card's faces in printed order, so a caller can
    index or count it. A face's ``name`` is the half's own; :func:`unit_label`
    spells it with its card for a message.
    """
    return [unit for card in cards for unit in castable_faces(card)]


def unit_label(card) -> str:
    """How a report names a compilation unit: a single-face card's name, and
    ``"Assault // Battery [Assault]"`` for a face — the spelling the picker
    sweep and the program differential already use, so one finding reads the
    same in every instrument."""
    parent = getattr(card, "face_of", None)
    name = getattr(card, "name", "")
    return f"{parent.name} [{name}]" if parent is not None else name


def card_names(card) -> tuple[str, ...]:
    """Every name *card* has (CR 709.4a: a split card has two).

    The whole card's printed spelling ("Assault // Battery") is **not** one of
    them: it is how a list writes the card, not something an effect choosing a
    card name can choose.
    """
    names = tuple(face.name for face in face_cards(card))
    return names or (getattr(card, "name", ""),)


def has_name(card, name: str) -> bool:
    """Whether *card* is called *name* — by any of its names (CR 709.4a), or
    by the printed spelling a decklist uses for the whole card."""
    return name == getattr(card, "name", None) or name in card_names(card)


def name_aliases(card) -> tuple[str, ...]:
    """The other spellings a decklist may use for a multi-face *card*; ``()``
    for a single-face card.

    A list writes a split card "Assault // Battery", and an exporter may write
    one slash, no spaces, or just the front half's name. All of them mean the
    one card (CR 709.2), so a name lookup that wants to *find the card* indexes
    these beside its printed name. Not for casting — that is
    :func:`spell_named`, where a half's name means the half.
    """
    names = [face.name for face in face_cards(card)]
    if not names:
        return ()
    return (*names, " / ".join(names), "/".join(names), "//".join(names))


def spell_named(card, name: str):
    """What casting *name* out of *card* puts on the stack, or None.

    The half called *name* for a multi-face card (CR 709.3: the player chooses
    which half as they cast it), the card itself for a single-face card called
    that, and None for anything else — including a split card asked for by its
    whole spelling, which names no half and is therefore not a spell.
    """
    for face in face_cards(card):
        if face.name == name:
            return face
    if is_multi_face(card):
        return None
    return card if getattr(card, "name", None) == name else None


def holds_spell_named(card, name: str) -> bool:
    """Whether *name* names *card* for a cast: one of its castable faces, or —
    so a refusal can say *why* — the whole spelling of a multi-face card."""
    return spell_named(card, name) is not None or (
        is_multi_face(card) and getattr(card, "name", None) == name
    )


def choose_a_face_refusal(card) -> str | None:
    """CR 709.3's refusal for a multi-face card cast with no face named."""
    if not is_multi_face(card):
        return None
    names = " or ".join(card_names(card))
    return (
        f"{card.name} is a split card: choose which half to cast "
        f"({names}) (CR 709.3)"
    )


def combined_oracle_text(card) -> str:
    """Every face's rules text, one face per paragraph headed by its name —
    CR 709.4c's "each ability in the text box of each half", for a reader that
    shows or searches the card rather than executing it. The card's own text
    for a single-face card."""
    faces = face_cards(card)
    if not faces:
        return getattr(card, "oracle_text", "") or ""
    return "\n".join(
        f"{face.name} — {face.oracle_text}" if face.oracle_text else face.name
        for face in faces
    )


__all__ = [
    "CAST_FACE_LAYOUTS",
    "card_names",
    "castable_faces",
    "choose_a_face_refusal",
    "combined_oracle_text",
    "compilation_units",
    "face_cards",
    "has_name",
    "holds_spell_named",
    "is_face",
    "is_multi_face",
    "name_aliases",
    "spell_named",
    "unit_label",
    "whole_card",
]
