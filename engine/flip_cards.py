"""Flip cards (CR 710): Champions of Kamigawa's two-part card frame.

**What a flip card is, here: its top half, everywhere but a flipped
permanent.** CR 710.2: "In every zone other than the battlefield, and also on
the battlefield before the permanent flips, a flip card has only the normal
characteristics of the card." So the card the loader builds for a flip entry
(:func:`loaded_flip_card`) *is* the top half — named "Bushi Tenderfoot", a 1/1
Human Soldier with the top half's text — with the whole card's mana cost and
colours (they are the top half's anyway) and both printed halves kept on
``CardDefinition.faces``. A hand, a library, a graveyard, exile, the stack and
an unflipped permanent all hold that one object, and nothing has to convert it
at a zone seam: CR 710.2's example ("Search your library for a legendary
card" can't find Akki Lavarunner; "Legendary creatures get +2/+2" doesn't
affect it) is true of it before anything here runs.

The card file's name for it — Scryfall's "Bushi Tenderfoot // Kenzo the
Hardhearted" — is how a list writes the card, not its name (CR 710.1a: the top
half "contains the card's normal name"), so it is one of the spellings a
decklist lookup accepts (``faces.name_aliases``) rather than the key.

**Flipping is morph's substitution** (``engine/face_down.py``). Two shapes
were on the table, measured before choosing:

* **A flipped flag beside the card**, read by the layer fold. Every CR 613
  accessor would be right; every *other* reader would not — 1,600-odd sites in
  ``engine/`` and ``web/`` read ``.card.name`` (the log, the serializers, the
  legend rule's name, "named" filters), and each would call a flipped Kenzo
  "Bushi Tenderfoot".
* **The bottom half as the permanent's card** (:func:`flipped_face`): a
  ``CardDefinition`` of the bottom half — its name, text box, type line, power
  and toughness — carrying the top half's mana cost and colours (CR 710.1c),
  derived once per card and with ``face_of`` naming the card it is a face of.
  :func:`flip_permanent` sets ``Permanent.card`` to it and changes nothing
  else: it is the same object, so its counters, damage, Auras, control, P/T
  effects ("any changes to it by external effects will still apply", CR
  710.1c), tapped state and summoning sickness stay where they were. Every
  reader is right at once, and the one thing owed in return is that every
  road off the battlefield puts the *card* into the new zone — which
  ``faces.whole_card`` already answers for a split card's half and a
  face-down object's blank (``face_of``), at each zone funnel.

Chosen: the second, for the face-down module's reason. The departing
permanent keeps the bottom half as its card, so CR 603.10's last-known
information is the flipped object (a flipped Kenzo that dies died as a
legendary Samurai), while the graveyard gets Bushi Tenderfoot (CR 710.4:
"if a flipped permanent leaves the battlefield, it retains no memory of its
status"). A permanent object entering the battlefield again is a new object
and enters unflipped (CR 110.5b; :func:`forget_flip`).

**Status, and copies.** CR 110.5: flipped/unflipped is a *status*, not a
characteristic, so a copy does not copy it (CR 707.2: "status … not copied")
— a Clone of a flipped Kenzo is a Bushi Tenderfoot (``copies.become_copy``
copies :func:`unflipped_card`) — and a flipped permanent's copiable values are
"modified by the copy's status" (CR 707.3): Tomoya the Revealer becoming a
copy of Nezumi Shortfang is Stabwhisker the Odious. The status is held as
:data:`FLIPPED` on the permanent beside the substitution, so a permanent whose
own card is no flip card (a Clone copying Jushi Apprentice that flips through
the copied ability, CR 110.5c's Dimir Doppelganger) is flipped too, and the
copy fold reads it (``copies.copiable_card``).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from .models import CardDefinition, CardFace

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent

#: The layouts read as CR 710 flip cards: a card whose loaded object is its
#: top half (:func:`loaded_flip_card`) and whose bottom half is a permanent's
#: card once it flips. ``oracle.SUPPORTED_LAYOUTS`` admits these beside the
#: single-face ones and ``faces.CAST_FACE_LAYOUTS``.
FLIP_LAYOUTS = frozenset({"flip"})

#: Set on a flipped permanent (CR 110.5): the status, held on the object. For a
#: flip card it rides beside the substitution (its ``card`` is the bottom
#: half); for a permanent whose own card is no flip card it is the whole of
#: the status, read by the copy fold (CR 707.3) — a Clone copying Jushi
#: Apprentice that flips through the copied ability is Tomoya.
FLIPPED = "flipped"


def _face_keywords(keywords, oracle_text: str) -> tuple[str, ...]:
    from .faces import keywords_printed_in

    return keywords_printed_in(keywords, oracle_text)


def loaded_flip_card(card: CardDefinition) -> CardDefinition:
    """The card the loader keeps for a flip entry *card*: its top half (CR
    710.1a, 710.2), with the whole card's cost and colours and both printed
    halves on ``faces``. *card* unchanged when it is no flip entry, or one
    whose ``card_faces`` did not survive (that one reaches the compiler's
    layout gate and is refused, rather than read as a blank vanilla).

    The ingest keeps keywords per card, not per half, and a keyword belongs to
    the half that prints it: Bushi Tenderfoot is not a double striker because
    Kenzo is. ``raw`` mirrors the typed fields, as a split card's halves'
    does, with ``card_faces`` kept for the bottom half to be derived from.
    """
    if card.layout not in FLIP_LAYOUTS or len(card.faces) != 2:
        return card
    top: CardFace = card.faces[0]
    raw = dict(card.raw) if isinstance(card.raw, dict) else {}
    raw.update({
        "name": top.name,
        "type_line": top.type_line,
        "oracle_text": top.oracle_text,
        "power": top.power,
        "toughness": top.toughness,
    })
    return dataclasses.replace(
        card,
        name=top.name,
        type_line=top.type_line,
        oracle_text=top.oracle_text,
        keywords=_face_keywords(card.keywords, top.oracle_text),
        power=top.power,
        toughness=top.toughness,
        raw=raw,
    )


def is_flip_card(card) -> bool:
    """Whether *card* is a flip card as a zone holds it: the top half the
    loader built, with its bottom half still to be derived."""
    return (
        getattr(card, "layout", "normal") in FLIP_LAYOUTS
        and len(getattr(card, "faces", ()) or ()) == 2
        and getattr(card, "face_of", None) is None
    )


def flipped_face(card) -> "CardDefinition | None":
    """The bottom half of flip card *card* as the card a flipped permanent is
    (CR 710.1b, 710.2), or None for any other card.

    Its name, text box, type line, power and toughness are the bottom half's;
    its mana cost, mana value and colours are *card*'s (CR 710.1c: "A flip
    card's color and mana cost don't change if the permanent is flipped"),
    and ``face_of`` names *card*, which is what ``faces.whole_card`` returns
    when it leaves. Its layout is ``normal``: it is one text box, compiled as
    any card is, under its own name — so "Goka deals 4 damage" is a
    self-reference to Goka the Unjust (``engine/self_reference.py``).

    Built once per card **object** and kept on it, ``faces.face_cards``'
    arrangement: a deck repeats one definition per copy, and two flipped
    copies are then one bottom half, as two unflipped ones are one top.
    """
    if not is_flip_card(card):
        return None
    cached = card.__dict__.get("_flipped_face")
    if cached is not None:
        return cached
    bottom: CardFace = card.faces[1]
    raw = dict(card.raw) if isinstance(card.raw, dict) else {}
    printed_keywords = raw.get("keywords")
    keywords = (
        tuple(str(word) for word in printed_keywords)
        if isinstance(printed_keywords, list) else card.keywords
    )
    raw.update({
        "name": bottom.name,
        "type_line": bottom.type_line,
        "oracle_text": bottom.oracle_text,
        "power": bottom.power,
        "toughness": bottom.toughness,
        "layout": "normal",
    })
    raw.pop("card_faces", None)
    face = dataclasses.replace(
        card,
        name=bottom.name,
        type_line=bottom.type_line,
        oracle_text=bottom.oracle_text,
        keywords=_face_keywords(keywords, bottom.oracle_text),
        power=bottom.power,
        toughness=bottom.toughness,
        raw=raw,
        layout="normal",
        faces=(),
        face_of=card,
    )
    # ``faces.face_cards``' trick: a frozen dataclass refuses ``setattr`` but
    # its instance dict is an ordinary dict, and nothing here is a field.
    card.__dict__["_flipped_face"] = face
    return face


def is_flipped_face(card) -> bool:
    """Whether *card* is a flip card's bottom half (:func:`flipped_face`)."""
    parent = getattr(card, "face_of", None)
    return parent is not None and is_flip_card(parent)


def unflipped_card(card):
    """The card a flip card's bottom half *card* is a face of; *card* itself
    otherwise. What a copy of a flipped permanent copies (CR 707.2: status is
    not copied) and what the card is in every other zone (CR 710.4)."""
    return card.face_of if is_flipped_face(card) else card


def flip_text_faces(card) -> tuple:
    """A flip card's two text boxes as cards — itself and its bottom half —
    for a census whose question is about rules text; ``()`` otherwise
    (``faces.text_faces``)."""
    face = flipped_face(card)
    return (card, face) if face is not None else ()


def alternative_name(card) -> "str | None":
    """CR 710.5's alternative name of flip card *card* (or of its bottom
    half's card), or None. "If an effect instructs a player to choose a card
    name and the player wants to choose a flip card's alternative name, the
    player may do so." """
    whole = unflipped_card(card)
    if not is_flip_card(whole):
        return None
    return whole.faces[1].name or None


def is_flipped(permanent) -> bool:
    """Whether *permanent* is flipped (CR 110.5)."""
    if permanent is None:
        return False
    metadata = getattr(permanent, "metadata", None) or {}
    return bool(metadata.get(FLIPPED)) or is_flipped_face(getattr(permanent, "card", None))


def flip_permanent(game: "Game", permanent: "Permanent", *, how: str = "") -> bool:
    """Flip *permanent* (CR 710.2); whether it flipped.

    One-way (CR 710.4): a permanent already flipped stays as it is, and
    nothing happens. A flip card's permanent becomes its bottom half
    (:func:`flipped_face`) — the same object, so everything applied to it
    stays — and any other permanent takes the status alone (CR 110.5c), which
    matters when its copiable values are a flip card's (CR 707.3) and is kept
    "even though that has no relevance" otherwise. The table recomputes what
    the board's statics give it: the bottom half may be a lord (Tobita), or
    legendary where the top was not (CR 704.5j asks next).

    *how* is for the log.
    """
    if permanent is None or is_flipped(permanent):
        return False
    before = permanent.effective_card.name
    face = flipped_face(permanent.card)
    if face is not None:
        permanent.card = face
    permanent.metadata[FLIPPED] = True
    after = permanent.effective_card.name
    game.log.append(
        f"{before} flipped" + (f": it is {after}" if after != before else "")
        + (f" ({how})" if how else "")
    )
    game._recompute_continuous_effects()
    return True


def forget_flip(permanent: "Permanent") -> None:
    """A permanent object entering the battlefield again is a new object
    (CR 400.7) and enters unflipped (CR 110.5b, CR 710.4): its card is its top
    half again and the status is gone.

    *Again* is the word that matters, and the status mark is how it is known:
    a permanent flipped here carries :data:`FLIPPED` (``flip_permanent``
    stamps it on every flip, and no road off the battlefield clears a
    permanent's metadata), so an object that was flipped, left and is coming
    back is unflipped whatever road returns it. An object handed to the entry
    already wearing a bottom half and never flipped here — a census board
    placing each compilation unit as a permanent, a test asking for a
    Shidako, Broodmistress — is not returning from anywhere: it enters as
    the permanent it was built as, flipped, and is stamped so. No game road
    makes one: every zone holds top halves (``faces.whole_card``,
    ``put_card_into_exile``) and a copy copies the unflipped card
    (``copies.become_copy``)."""
    card = getattr(permanent, "card", None)
    if permanent.metadata.pop(FLIPPED, None):
        if is_flipped_face(card):
            permanent.card = card.face_of
        return
    if is_flipped_face(card):
        permanent.metadata[FLIPPED] = True


__all__ = [
    "FLIPPED",
    "FLIP_LAYOUTS",
    "alternative_name",
    "flip_permanent",
    "flip_text_faces",
    "flipped_face",
    "forget_flip",
    "is_flip_card",
    "is_flipped",
    "is_flipped_face",
    "loaded_flip_card",
    "unflipped_card",
]
