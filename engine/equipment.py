"""Equipment (CR 301.5), the equip keyword (CR 702.6) and the attach action
(CR 701.3).

Three rules, one module, because each is written in terms of the others:

* **CR 702.6a defines equip as a rewrite.** "Equip [cost]" *means* "[Cost]:
  Attach this permanent to target creature you control. Activate only as a
  sorcery." So the keyword line is expanded into that text before the compiler
  classifies anything (:func:`expand_equip_lines`), and from there it is an
  ordinary activated ability: the grammar reads the effect, the cost parser
  reads the cost, ``engine/activation_restrictions.py`` enforces the timing,
  ``engine/targeting.py`` derives the picker off the lowered ``targets``
  payload, and the web layer offers it like any other ability. Nothing
  downstream knows the word "equip" — which is the point: a keyword defined as
  a rewrite gets one reader, the rewrite, rather than a second path beside
  every seam an activated ability already passes through.

* **CR 301.5 says what may be equipped**, and :func:`equip_refusal` is the one
  reader of it: a creature only (301.5), never the Equipment itself and never
  from an Equipment that is currently a creature or has lost the subtype
  (301.5c), and never a creature with protection from the Equipment's quality
  (702.16d). The equip handler, the state-based sweep and the target picker all
  ask it, so what the ability may choose, what the resolution accepts and what
  the sweep later tolerates cannot disagree.

* **CR 701.3 says what attaching does**: :func:`attach_equipment` moves the
  Equipment from wherever it is (701.3a), does nothing when it is already there
  (701.3b), and stamps a fresh timestamp on the move (701.3c / 613.7e) so the
  Equipment's bonus orders correctly against other layer-7c effects.

Attachment *state* is the same record an Aura uses — ``attached_to`` on the
attachment, ``attached_auras`` on the host (``engine/auras.py``) — and the
layer bridge derives the Equipment's P/T grant, keyword grants and restrictions
off its own text exactly as it does an Aura's. CR 301.5f is why that sharing is
correct rather than a shortcut: "equipped creature" means whatever creature the
permanent is attached to, and ``engine/auras.py``'s templates read both words.

What differs from an Aura is what happens when the attachment goes wrong. An
Aura attached to nothing legal is put into the graveyard (704.5m); an Equipment
just **becomes unattached and stays** (704.5n, 702.16d). :func:`unattach_illegal_equipment`
is that sweep, called from ``mixins/game_ending.py``. It also forgets an
Equipment that has *left* the battlefield: CR 701.3d counts leaving as becoming
unattached, and a departed Equipment left in its host's ``attached_auras`` list
would keep granting +1/+1 from the graveyard. That is read off the board at the
sweep rather than wired into each zone-change path — a bounce, an exile, a
destroy and a sacrifice are four call sites, and the phasing handler needs the
record to *survive* removal so the Equipment phases back in attached.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .auras import attach_aura, auras_attached_to, detach_aura

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

# "Equip {1}", "Equip {1}{W}", "Equip legendary creature {3}", "Equip Knight
# {1}" (CR 702.6c's "Equip [quality]" / "Equip [quality] creature"). Matched on
# the printed line with its reminder text removed, case-insensitively, and the
# cost is taken from the printed line so a coloured pip keeps its letter.
_EQUIP_LINE = re.compile(
    r"^equip(?:\s+(?P<quality>[a-z][a-z' -]*?))?\s+(?P<cost>(?:\{[^{}]+\})+)$",
    re.IGNORECASE,
)
_REMINDER = re.compile(r"\([^)]*\)")
# Any line that *is* an equip keyword line, readable or not — "Equip
# planeswalker {3}" included. The wider shape is what the support gate asks, so
# a variant the expansion refuses is reported as an unimplemented equip line
# rather than falling through to a gate that never heard of the keyword.
_EQUIP_SHAPE = re.compile(r"^equip\b", re.IGNORECASE)

#: The rules text CR 702.6a gives the keyword. The noun slot is "creature" for
#: the bare keyword and "[quality] creature" for CR 702.6c's narrowed form.
EQUIP_RULES_TEXT = (
    "{cost}: Attach this permanent to target {noun} you control. "
    "Activate only as a sorcery."
)


def equip_line_parts(line: str) -> tuple[str, str] | None:
    """``(cost, noun)`` when *line* is a printed equip keyword line, else None.

    The noun is what the expanded ability targets: "creature" for "Equip {1}",
    "legendary creature" for "Equip legendary creature {3}", "Knight" for
    "Equip Knight {1}". "Equip planeswalker" (CR 702.6e) is refused outright —
    it attaches to a planeswalker *as though it were a creature*, a legality the
    attach path does not model, and admitting it would compile an ability whose
    resolution always declines.
    """
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")
    match = _EQUIP_LINE.match(stripped)
    if match is None:
        return None
    quality = (match.group("quality") or "").strip()
    if quality.lower() == "planeswalker":
        return None
    # "Equip legendary creature {3}" names its noun in full; "Equip Knight {1}"
    # names a subtype and the grammar's noun phrase reads "target Knight you
    # control" as it does on any other card.
    return match.group("cost"), quality or "creature"


def is_equip_line(line: str) -> bool:
    """Whether *line* is a printed equip keyword line, whether or not
    :func:`expand_equip_line` can read it (CR 702.6e's "Equip planeswalker"
    is one it cannot)."""
    stripped = _REMINDER.sub("", line or "").strip()
    return _EQUIP_SHAPE.match(stripped) is not None


def expand_equip_line(line: str) -> str | None:
    """The CR 702.6a rules text for one printed equip line, or None."""
    parts = equip_line_parts(line)
    if parts is None:
        return None
    cost, noun = parts
    return EQUIP_RULES_TEXT.format(cost=cost, noun=noun)


def expand_equip_lines(oracle_text: str) -> str:
    """*oracle_text* with every equip keyword line rewritten to its rules text.

    Text without an equip line is returned unchanged, so applying this to every
    card costs nothing but a scan. Applied by the compiler before any line is
    classified — beside ``expand_modal_activated_lines`` and for the same
    reason: what the compiler reads and what every other reader of a card's
    lines (targeting, parse coverage, hook reliance) reads must be one text.
    """
    if not oracle_text or "quip" not in oracle_text:
        return oracle_text
    lines = oracle_text.split("\n")
    rewritten = [expand_equip_line(line) or line for line in lines]
    return "\n".join(rewritten)


def has_equip_ability(oracle_text: str) -> bool:
    """Whether any printed line of *oracle_text* is an equip keyword line.

    The compiler's shape test for "is this an Equipment": CR 702.6a makes equip
    an ability *of Equipment cards*, and the compiler is not handed the type
    line. A card printing the keyword is gated as an Equipment — every effect
    line claimed, the equip ability itself compiled — in ``engine/oracle.py``.
    Deliberately the wide shape: a variant the expansion cannot read must reach
    that gate and be refused by name, not slip past it.
    """
    return any(is_equip_line(line) for line in (oracle_text or "").split("\n"))


# ---------------------------------------------------------------------------
# What may be equipped (CR 301.5, 702.16d)
# ---------------------------------------------------------------------------


def is_equipment(permanent: "Permanent") -> bool:
    """Whether *permanent* currently has the Equipment subtype (CR 301.5).

    Through the layer system, because CR 301.5c makes losing the subtype a
    thing that can happen: a copy effect or a type change answers here, where
    the printed line would not.
    """
    return permanent.has_type("equipment")


def equipped_creature(equipment: "Permanent") -> "Permanent | None":
    """The creature *equipment* is attached to, or None (CR 301.5a)."""
    return equipment.metadata.get("attached_to")


def equipment_attached_to(permanent: "Permanent") -> list:
    """Every Equipment currently attached to *permanent*."""
    return [
        attachment for attachment in auras_attached_to(permanent)
        if is_equipment(attachment)
    ]


def equip_refusal(game: "Game", equipment: "Permanent", creature: "Permanent") -> str | None:
    """Why *equipment* may not be attached to *creature*, or None when it may.

    One predicate, read by the equip handler at resolution (CR 608.2b), by the
    target picker as the ability is activated (CR 602.2b) and by the state-based
    sweep afterwards (704.5n), so the three cannot drift: a creature the picker
    offers is one the resolution attaches to, and one the sweep then leaves
    alone.

    * CR 301.5 — the host must be a creature; "can't legally be attached to
      anything that isn't a creature".
    * CR 301.5c — an Equipment that is itself a creature can't equip (no card
      in the pool has reconfigure), one that lost the subtype can't, and none
      can equip itself.
    * CR 702.16d — a creature with protection from a quality the Equipment has
      can't be equipped by it. Colours only, as the sweep reads them.
    """
    if creature is equipment:
        return "an Equipment can't equip itself (CR 301.5c)"
    if creature is None or not game.is_on_battlefield(creature):
        return "the equipped creature is no longer on the battlefield"
    if not creature.is_creature:
        return f"{creature.card.name} is not a creature (CR 301.5)"
    if not is_equipment(equipment):
        return f"{equipment.card.name} is no longer an Equipment (CR 301.5c)"
    if equipment.is_creature:
        return f"{equipment.card.name} is a creature and can't equip (CR 301.5c)"
    protection = game._protection_colors(creature)
    if protection and (protection & game._effective_colors(equipment)):
        return (
            f"{creature.card.name} has protection from {equipment.card.name}'s "
            "colour (CR 702.16d)"
        )
    return None


# ---------------------------------------------------------------------------
# Attach and unattach (CR 701.3)
# ---------------------------------------------------------------------------


def attach_equipment(game: "Game", equipment: "Permanent", creature: "Permanent") -> bool:
    """Attach *equipment* to *creature* (CR 701.3a). Returns whether it moved.

    * Already attached to that creature: the effect does nothing (701.3b) —
      in particular no new timestamp, so re-equipping the same creature does
      not reorder the bonus against anything.
    * Attached to something else: it is taken from there first (701.3a says
      "take it from where it currently is"), which 701.3c counts as becoming
      unattached from the old host.
    * Illegal host: it doesn't move (701.3b, 301.5b).

    The record written is the Aura one (``engine/auras.py``), and
    :func:`auras.attach_aura` stamps the fresh timestamp CR 613.7e requires.
    """
    refusal = equip_refusal(game, equipment, creature)
    if refusal is not None:
        game.log.append(f"{equipment.card.name} doesn't move: {refusal}")
        return False
    current = equipped_creature(equipment)
    if current is creature:
        game.log.append(
            f"{equipment.card.name} is already attached to {creature.card.name}"
        )
        return False
    if current is not None:
        detach_aura(equipment, current)
        game.log.append(f"{equipment.card.name} became unattached from {current.card.name}")
    attach_aura(equipment, creature)
    game.log.append(f"{equipment.card.name} is now attached to {creature.card.name}")
    game._recompute_continuous_effects()
    return True


def unattach_equipment(game: "Game", equipment: "Permanent", reason: str) -> bool:
    """Unattach *equipment* from whatever it equips (CR 701.3d). It stays on the
    battlefield; that is the difference from an Aura and the whole of 704.5n."""
    host = equipped_creature(equipment)
    if host is None:
        return False
    detach_aura(equipment, host)
    game.log.append(f"{equipment.card.name} became unattached ({reason})")
    return True


def unattach_illegal_equipment(game: "Game") -> bool:
    """The Equipment half of the state-based sweep. Returns whether anything
    changed, which is what the CR 704.3 fixpoint loop wants to know.

    * CR 704.5n — an Equipment attached to an illegal permanent (one that left
      the battlefield, stopped being a creature, or is the Equipment itself)
      becomes unattached and remains on the battlefield.
    * CR 702.16d — so does one whose equipped creature has protection from its
      colour.
    * CR 301.5c — so does one that became a creature or lost the subtype.
    * CR 701.3d — an Equipment that has *left* the battlefield has become
      unattached, and its former host must stop counting it. Read off the host
      rather than off the zone-change paths (see the module docstring).
    """
    changed = False
    for permanent in list(game.all_permanents()):
        if is_equipment(permanent):
            host = equipped_creature(permanent)
            if host is None:
                continue
            refusal = equip_refusal(game, permanent, host)
            if refusal is not None:
                changed |= unattach_equipment(game, permanent, f"704.5n: {refusal}")
        # The host's side: an Equipment no longer on the battlefield still
        # listed among what is attached to this permanent.
        for attachment in auras_attached_to(permanent):
            if is_equipment(attachment) and not game.is_on_battlefield(attachment):
                detach_aura(attachment, permanent)
                game.log.append(
                    f"{attachment.card.name} became unattached from "
                    f"{permanent.card.name} (701.3d: it left the battlefield)"
                )
                changed = True
    return changed


__all__ = [
    "EQUIP_RULES_TEXT",
    "attach_equipment",
    "equip_line_parts",
    "equip_refusal",
    "equipment_attached_to",
    "equipped_creature",
    "expand_equip_line",
    "expand_equip_lines",
    "has_equip_ability",
    "is_equip_line",
    "is_equipment",
    "unattach_equipment",
    "unattach_illegal_equipment",
]
