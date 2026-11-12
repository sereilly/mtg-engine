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
  the sweep later tolerates cannot disagree — with one difference, which is the
  rules' own: an Equipment that is a creature has a legal target and simply
  doesn't move (CR 301.5c; the March of the Machines ruling), so the picker and
  the handler's target check ask :func:`equip_target_refusal`, which is this
  predicate whenever the Equipment can equip at all.

* **CR 701.3 says what attaching does**: :func:`attach_equipment` moves the
  Equipment from wherever it is (701.3a), does nothing when it is already there
  (701.3b), and stamps a fresh timestamp on the move (701.3c / 613.7e) so the
  Equipment's bonus orders correctly against other layer-7c effects.

Attachment *state* is the same record an Aura uses — ``attached_to`` on the
attachment, ``attached_auras`` on the host (``engine/aura_attachment.py``) —
and the layer bridge derives the Equipment's P/T grant, keyword grants and
restrictions off its own text exactly as it does an Aura's. CR 301.5f is why
that sharing is correct rather than a shortcut: "equipped creature" means
whatever creature the permanent is attached to, and ``engine/auras.py``'s
templates read both words.

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

from .aura_attachment import attach_aura, auras_attached_to, detach_aura
from .aura_vocabulary import _NOUN, _line_text

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
# "Equip—Pay 3 life." (Nightmare Lash.) CR 702.6a's "[cost]" is any cost, and
# one that is not only mana is printed behind a dash — the arrangement every
# other cost keyword here already reads (``face_down._MORPH_DASH_PART``,
# ``cast_costs``' kicker and buyback, ``flashback``), each with its own pattern
# because each is charged by a different reader. Equip's reader is the
# activated-ability cost parser the rewrite hands the cost to, so admitting the
# dash here admits only what that parser charges: a clause it cannot read
# leaves the expanded ability unsupported, and the Equipment gate in
# ``engine/oracle.py`` refuses the card naming its equip line.
_EQUIP_DASH_LINE = re.compile(r"^equip\s*[—–]\s*(?P<cost>[^{}:]+)$", re.IGNORECASE)
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
    dashed = _EQUIP_DASH_LINE.match(stripped)
    if dashed is not None:
        # The cost as printed, first letter up ("Pay 3 life"), exactly as the
        # rules text writes "[Cost]:" — the same spelling morph's dash cost
        # keeps. Only the bare keyword: CR 702.6c's quality sits before a
        # mana cost in every printing, and a dash after one is not a shape
        # this reads.
        cost = dashed.group("cost").strip()
        return cost[:1].upper() + cost[1:], "creature"
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


def is_equip_ability(card, ability) -> bool:
    """Whether *ability* — a compiled ``ParsedActivatedAbility`` of *card* — is
    an **equip ability** (CR 702.6a).

    The rewrite erases the word, which is what lets every seam an activated
    ability passes through ignore it; a card that asks *about* equip
    abilities ("Equip costs you pay cost {1} less", Auriok Steelshaper) has to
    get the word back. The derivation is the rewrite run backwards, exactly as
    ``cycling.is_cycling_ability`` runs its own: an ability is an equip ability
    when some printed line of its card is an equip line whose
    :func:`expand_equip_line` is that ability's ``source_line``.

    **Not "attaches this permanent to a creature".** An ability printed as
    "{2}: Attach this permanent to target creature you control" without the
    keyword is not an equip ability, and a reduction keyed on the effect would
    discount it.
    """
    return is_equip_ability_text(card, getattr(ability, "source_line", "") or "")


def is_equip_ability_text(card, ability_text: str) -> bool:
    """:func:`is_equip_ability` asked of an ability's line rather than of the
    compiled ability — the form a reader holding only the line has
    (``activation_restrictions.activation_denial``)."""
    wanted = (ability_text or "").strip()
    if not wanted:
        return False
    return any(
        (expand_equip_line(line) or "").strip() == wanted
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    )


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


def attachment_refusal(
    game: "Game", attachment: "Permanent", host: "Permanent"
) -> str | None:
    """Why *attachment* may not become attached to *host*, or None when it may.

    The one question ``attach_source_to_target`` asks — at the picker
    (CR 602.2b) and again at resolution (CR 608.2b) — dispatched on what the
    attaching permanent is, because CR 301.5 and CR 303.4 are different rules
    with different legality:

    * an Equipment attaches by :func:`equip_refusal` (a creature, never itself,
      never through protection);
    * an Aura attaches by ``aura_attachment.aura_attach_refusal``, which reads
    the
      **enchant ability** (CR 702.5) — the noun it names, the seat clause, and
      CR 303.4's protection half.

    Both call sites used to ask ``equip_refusal`` outright, and its
    ``is_equipment`` guard then refused *every* host for an Aura. Kjeldoran
    Pride's "{2}{U}: Attach this Aura to target creature other than enchanted
    creature" is the card that found it: the ability compiled, claimed, reported
    supported, offered an empty picker and moved nothing. An Aura with its own
    attach ability is not an exotic shape — it is CR 701.3 asked by the other
    kind of Attachment.

    **And there is a third case, which is neither.** A Licid is a *creature*
    when its ability is activated and an Aura by the time the attach in the
    sentence behind it resolves — so at the picker (CR 602.2b) the permanent has
    no attachment legality of its own to test. Asking the Equipment predicate
    there refuses every host and empties the picker, which is Kjeldoran Pride's
    bug arriving from the opposite direction; asking the Aura one refuses too,
    for want of an enchant clause the permanent has not been given yet.

    What the *rules* say at that moment is that there is nothing to ask: the
    ability targets "target creature" and CR 303.4j is checked when the Aura
    would actually move, which is at resolution — by which time the type change
    has happened and the Aura arm above answers. So the third arm tests only
    what is true of any attachment at any time (CR 303.4d / 301.5c: never
    itself, and the host has to exist), and leaves the rest to the arm that
    will be right.
    """
    from .aura_attachment import aura_attach_refusal

    if attachment.has_type("aura"):
        return aura_attach_refusal(game, attachment, host)
    if is_equipment(attachment):
        return equip_refusal(game, attachment, host)
    if host is attachment:
        return "a permanent can't attach to itself"
    if host is None or not game.is_on_battlefield(host):
        return "the host is no longer on the battlefield"
    return None


def attachment_target_refusal(
    game: "Game", attachment: "Permanent", host: "Permanent"
) -> str | None:
    """Why *host* may not be **chosen** as the target of *attachment*'s attach
    ability (CR 601.2c via 602.2b), or None when it may — the picker's half of
    :func:`attachment_refusal`, which stays the resolution's half.

    The two are one question except where the *attaching permanent* is the
    problem rather than the host. An Equipment that is a creature can't equip
    (CR 301.5c), but its equip ability still reads "Attach this permanent to
    target creature you control", and nothing about a creature you control
    stopped being that. The March of the Machines ruling (2004-12-01) says it
    in as many words: "You can activate the Equipment's equip ability, but it
    won't do anything." Asking :func:`equip_refusal` here refused every host
    and emptied the picker, so the activation was refused with "no valid
    target" — a smaller game than the printed one, in the direction nobody
    reports. See :func:`equip_target_refusal`.
    """
    if is_equipment(attachment) and not attachment.has_type("aura"):
        return equip_target_refusal(game, attachment, host)
    return attachment_refusal(game, attachment, host)


#: "This creature can't be equipped." (Goblin Brawler.) A restriction the
#: permanent prints about **itself**, the Equipment twin of the Tetravite's
#: "This token can't be enchanted" (``aura_restrictions.self_cant_be_enchanted_line``),
#: and read the same way: anchored on the whole sentence, off the permanent's
#: effective text, so a copy carries it (CR 707.2) and a text change can take it
#: away.
#:
#: **It is not a targeting restriction.** "You can activate an equip ability
#: that targets Goblin Brawler, but the Equipment will fail to move onto it."
#: (Goblin Brawler ruling, 2004-12-01.) CR 301.5b says the same of every
#: attach: "If an effect attempts to attach an Equipment to an object that
#: can't be equipped by it, the Equipment doesn't move." So it is asked by
#: :func:`equip_refusal` — the resolution, the CR 704.5n sweep and the AI's
#: equip planner — and deliberately **not** by :func:`equip_target_refusal`,
#: the picker's half.
_SELF_CANT_BE_EQUIPPED = re.compile(rf"^this (?:token|{_NOUN}) can't be equipped$")


def self_cant_be_equipped_line(line: str) -> bool:
    """Whether one printed line is "this <noun> can't be equipped", in full.

    Read by the support gate, by the grammar's registry claim and by
    :func:`cant_be_equipped_by_own_text`, so what is claimed and what is
    enforced cannot drift.
    """
    return _SELF_CANT_BE_EQUIPPED.match(_line_text(line or "")) is not None


def cant_be_equipped_by_own_text(permanent: "Permanent") -> bool:
    """Whether *permanent*'s own text forbids Equipment attaching to it."""
    card = getattr(permanent, "effective_card", None) or getattr(permanent, "card", None)
    text = getattr(card, "oracle_text", "") or ""
    if "equipped" not in text:
        return False
    return any(self_cant_be_equipped_line(line) for line in text.splitlines())


def equip_target_refusal(
    game: "Game", equipment: "Permanent", creature: "Permanent"
) -> str | None:
    """Why *creature* is not a legal target for *equipment*'s equip ability.

    :func:`equip_refusal` whenever the Equipment can equip at all — a creature
    it may not be attached to (protection, CR 702.16b/d; itself) is a creature
    the ability may not choose, and offering it would be offering an attach
    that lands nowhere — **except** a creature whose own text says it can't be
    equipped, which is a legal target the Equipment then fails to move onto
    (Goblin Brawler ruling, 2004-12-01; CR 301.5b; see
    :data:`_SELF_CANT_BE_EQUIPPED`). When the Equipment is itself a creature (CR 301.5c),
    nothing can be equipped and the target is asked only what the printed
    words ask: a creature, on the battlefield, that the ability's source may
    target (CR 702.16b — an artifact source and a creature with protection
    from artifacts). Itself included: it is a creature its controller
    controls, and the attach that follows does nothing (CR 701.3b) either way.
    """
    if not equipment.is_creature:
        return _equip_refusal(game, equipment, creature, chosen_as_target=True)
    if creature is None or not game.is_on_battlefield(creature):
        return "the equipped creature is no longer on the battlefield"
    if not creature.is_creature:
        return f"{creature.card.name} is not a creature (CR 301.5)"
    if game._is_protected_from(creature, equipment):
        return (
            f"{creature.card.name} has protection from {equipment.card.name} "
            "(CR 702.16b)"
        )
    return None


def equipped_creature(equipment: "Permanent") -> "Permanent | None":
    """The creature *equipment* is attached to, or None (CR 301.5a)."""
    return equipment.metadata.get("attached_to")


def equip_refusal(game: "Game", equipment: "Permanent", creature: "Permanent") -> str | None:
    """Why *equipment* may not be attached to *creature*, or None when it may.

    One predicate, read by ``attach_equipment`` at resolution (CR 608.2b), by
    the target picker as the ability is activated (CR 602.2b, through
    :func:`equip_target_refusal`) and by the state-based sweep afterwards
    (704.5n), so the three cannot drift: a creature the picker offers is one
    the resolution attaches to, and one the sweep then leaves alone — unless
    the Equipment is itself a creature, which no creature it could choose
    would change.

    * CR 301.5 — the host must be a creature; "can't legally be attached to
      anything that isn't a creature".
    * CR 301.5c — an Equipment that is itself a creature can't equip (no card
      in the pool has reconfigure), one that lost the subtype can't, and none
      can equip itself.
    * CR 702.16d — a creature with protection from a quality the Equipment has
      can't be equipped by it. **Every** quality the shield models, not the
      colour slice: every Equipment in this game is an artifact, so a creature
      with "protection from artifacts" (Angelic Curator, Yavimaya Scion) is
      protected from all of them — and a colour-only reading equipped it
      happily. The rule names "a quality"; reading one family of quality is how
      the E in protection's DEBT goes missing for exactly the cards a new
      quality arrives with.
    * CR 301.5b — a creature that can't be equipped by it ("This creature
      can't be equipped", Goblin Brawler) doesn't receive it.
    """
    return _equip_refusal(game, equipment, creature, chosen_as_target=False)


def _equip_refusal(
    game: "Game", equipment: "Permanent", creature: "Permanent", *,
    chosen_as_target: bool,
) -> str | None:
    """:func:`equip_refusal`, with the one clause that is not about choosing a
    target held back when *chosen_as_target* (see :func:`equip_target_refusal`)."""
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
    # Through ``_is_protected_from``, the one reader that asks every quality of
    # the object it is asked about — never a second walk of the quality set here,
    # which is how the blocking half and this half would come to disagree about
    # what an animated artifact land is (a layer-4 type, which ``has_type``
    # answers and a printed type line does not).
    if game._is_protected_from(creature, equipment):
        return (
            f"{creature.card.name} has protection from {equipment.card.name} "
            "(CR 702.16d)"
        )
    if not chosen_as_target and cant_be_equipped_by_own_text(creature):
        return f"{creature.card.name} can't be equipped (CR 301.5b)"
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

    The record written is the Aura one (``engine/aura_attachment.py``), and
    :func:`aura_attachment.attach_aura` stamps the fresh timestamp CR 613.7e
    requires.

    **The legality is asked of whichever kind of Attachment this is.** CR 701.3
    is one action and an Aura can be its subject: Kjeldoran Pride's "{2}{U}:
    Attach this Aura to target creature other than enchanted creature" arrives
    here exactly as an equip ability does. Asking ``equip_refusal`` outright
    refused it on ``is_equipment`` and logged "is no longer an Equipment" about
    a card that never was one — the ability resolved, reported resolved, and
    moved nothing. The function keeps its Equipment-shaped name because that is
    still what nearly every caller is; what it must not keep is an
    Equipment-shaped *rule*.
    """
    refusal = attachment_refusal(game, equipment, creature)
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
        game.log.append(f"{equipment.effective_card.name} became unattached from {current.effective_card.name}")
    attach_aura(equipment, creature)
    game.log.append(f"{equipment.effective_card.name} is now attached to {creature.effective_card.name}")
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
        # Attached to nothing and wearing nothing: neither half below has
        # anything to judge, whatever the permanent is — so the layer-4 read
        # of whether it is an Equipment is spared for nearly every permanent.
        if equipped_creature(permanent) is None and not auras_attached_to(permanent):
            continue
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
    "attachment_target_refusal",
    "cant_be_equipped_by_own_text",
    "equip_line_parts",
    "equip_refusal",
    "equip_target_refusal",
    "equipped_creature",
    "expand_equip_line",
    "expand_equip_lines",
    "has_equip_ability",
    "is_equip_ability",
    "is_equip_ability_text",
    "is_equip_line",
    "is_equipment",
    "self_cant_be_equipped_line",
    "unattach_equipment",
    "unattach_illegal_equipment",
]
