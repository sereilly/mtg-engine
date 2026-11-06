"""Face-down spells and permanents (CR 708), and morph (CR 702.37).

**What a face-down object is, here: a card.** CR 702.37c says it in as many
words — "It becomes a 2/2 face-down creature card with no text, no name, no
subtypes, and no mana cost" — and CR 708.2a lists the same values for every
other way something is turned face down. So a face-down spell's
``StackItem.card`` and a face-down permanent's ``Permanent.card`` **are** that
blank card (:func:`face_down_card`), and the card it hides rides on it as
``CardDefinition.face_down_of``. Two shapes were on the table, and this one was
chosen by counting both sides (the round's commit message has the numbers):

* **A face-down record beside the real card** (a layer-1b channel the fold
  reads) leaves ``perm.card`` the hidden card. Every CR 613 accessor would be
  right, and every *other* reader would not: 1,598 sites in ``engine/`` and
  ``web/`` read ``.card.name``, most of them log lines and serializers, and
  each one would name the hidden card to the whole table the first time the
  creature attacked or was dealt damage.
* **The blank card as the object's card** is fail-closed for all of them at
  once — a log line says "Face-down creature", a serializer sends a 2/2 with
  nothing else, a characteristic read sees CR 708.2a's values — and what it
  owes in return is that every road *off* the battlefield or the stack puts the
  hidden card in the new zone (CR 708.9). Those roads already meet at two
  seams: ``faces.whole_card`` (asked by every zone funnel and by the stack's
  bin, for split cards — CR 709.4 is the same question) and
  ``Game.remove_all_from_battlefield``, the one transition out, which reveals
  a departing face-down permanent (:func:`reveal_departing`).

**The hidden card is what the object's controller may look at** (CR 708.5,
:func:`hidden_card_of`) and what turning it face up restores (CR 708.8,
:func:`turn_face_up`). Turning it face up changes ``Permanent.card`` and
nothing else: it is the same object (CR 400.7 does not apply), so its
counters, damage, Auras, control changes, P/T effects, tapped state and
summoning sickness are all where they were — they live on the permanent, not
on the card.

**What a permanent was as it left** is CR 603.10's last-known information, and
for a face-down permanent that is the blank 2/2: a face-down creature that dies
has no "when this dies" ability and is no Goblin. The departing permanent's
card becomes the hidden card (so whatever reads ``perm.card`` to put it in a
zone gets the real one, revealed), and :data:`copies.FACE_DOWN_AS_IT_LEFT` on
it keeps its characteristics the face-down ones for every reader of the
departed object (``copies.copiable_card``).

Morph is the keyword that casts a card this way. CR 702.37a makes it two
things this engine already has: an **alternative cost** of {3} (CR 118.9,
``engine/alternative_costs.py`` — :func:`morph_alternative_cost`, found by the
one reader every cast question shares, ``Game.applicable_alternative_costs``)
with the face-down status attached, and a **special action** (CR 702.37e,
CR 116.2b) registered on ``engine/special_actions.py``'s permanent seam
(:data:`TURN_FACE_UP`). Its keyword line is admitted by the reader that
charges it (:func:`morph_cost_text`, ``keyword_lines._qualified_keyword_part``),
madness's arrangement.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .copies import FACE_DOWN_AS_IT_LEFT, face_up_copiable_card
from .models import CardDefinition

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .alternative_costs import AlternativeCost
    from .game import Game
    from .models import Permanent

#: The keyword, as :attr:`AlternativeCost.keyword` carries it — what a
#: "morph costs" modifier would be read against
#: (``cost_modifiers.keyword_cost_modifiers``) and what a cast's log names.
MORPH = "morph"

#: The special action CR 702.37e makes of turning a face-down permanent with a
#: morph ability face up (CR 116.2b), as ``special_actions`` registers it.
TURN_FACE_UP = "turn_face_up"

#: The trigger condition kind of "When this creature is turned face up"
#: (Legions, Scourge), announced by :func:`turn_face_up` and by nothing else.
TURNED_FACE_UP = "turned_face_up"

#: The trigger condition kind of "Whenever a permanent is turned face up" and
#: of an Aura's "When enchanted creature is turned face up" (Scourge): the
#: same event watched from anywhere on the board, announced on the event bus by
#: :func:`turn_face_up` beside :data:`TURNED_FACE_UP`.
PERMANENT_TURNED_FACE_UP = "permanent_turned_face_up"

#: Set on a permanent **Illusionary Mask** put face down: the record of which
#: rule turns it face up (CR 708.6, 708.7) — the Mask's "if [it] would assign
#: or deal damage, be dealt damage, or become tapped, instead it's turned face
#: up", which ``EffectsMixin._turn_face_up`` asks at each of those events. Its
#: own key because a morph creature put face down by its own ability is turned
#: up by nothing of the kind. The spelling the Mask has always used.
MASK_FACE_DOWN = "face_down"

#: What the engine calls an object CR 708.2a says has **no name**. A display
#: label, never a name a card can be asked for: nothing in the pool is called
#: this, and nothing in the engine compares a name against it — whether an
#: object is face down is asked of :func:`is_face_down_card`.
FACE_DOWN_NAME = "Face-down creature"

#: CR 708.2a's characteristics: "a 2/2 face-down creature with no text, no
#: name, no subtypes, and no mana cost" — so mana value 0 (CR 202.3a) and, with
#: no mana cost and no colour indicator, colourless (CR 202.2b). No set code,
#: collector number, oracle id or printings either: each of those would tell a
#: serializer which card it is. The face-down **values** with nothing hidden
#: behind them — what a copy of a face-down permanent copies (CR 708.10,
#: CR 707.2) and what a departed one last was.
FACE_DOWN_CHARACTERISTICS = CardDefinition(
    name=FACE_DOWN_NAME,
    mana_cost="",
    cmc=0.0,
    type_line="Creature",
    oracle_text="",
    colors=(),
    color_identity=(),
    keywords=(),
    produced_mana=(),
    raw={
        "name": FACE_DOWN_NAME, "type_line": "Creature", "power": "2",
        "toughness": "2", "layout": "normal",
    },
    power="2",
    toughness="2",
)


def face_down_card(card: CardDefinition) -> CardDefinition:
    """The face-down object *card* becomes (CR 702.37c, CR 708.2a): the blank
    2/2 with *card* hidden behind it.

    Built once per card **object** and kept on it, the arrangement
    ``faces.face_cards`` makes for a split card's halves and for its reason: a
    deck repeats one immutable definition per copy, and the object a stack
    item or a permanent holds should be the same one every time it is asked
    for. Two face-down copies of one card are therefore one blank card, as two
    face-up copies are one definition; what tells the two *objects* apart is
    the permanent (``permanent_id``), never the card.

    A card that is itself face down is returned unchanged (CR 708.2b: "A
    face-down permanent can't be turned face down").
    """
    if card.face_down_of is not None:
        return card
    cached = card.__dict__.get("_face_down_card")
    if cached is not None:
        return cached
    blank = dataclasses.replace(FACE_DOWN_CHARACTERISTICS, face_down_of=card)
    # ``faces.face_cards``' trick: a frozen dataclass refuses ``setattr`` but
    # its instance dict is an ordinary dict, and nothing here is a field.
    card.__dict__["_face_down_card"] = blank
    return blank


def is_face_down_card(card) -> bool:
    """Whether *card* is a face-down object's blank card."""
    return getattr(card, "face_down_of", None) is not None


def hidden_card(card) -> "CardDefinition | None":
    """The card a face-down *card* hides, or None for a face-up one."""
    return getattr(card, "face_down_of", None)


def is_face_down(permanent) -> bool:
    """Whether *permanent* (or a stack object) is face down right now."""
    return is_face_down_card(getattr(permanent, "card", None))


def hidden_card_of(permanent) -> "CardDefinition | None":
    """What a face-down *permanent* (or stack object) is, for the one seat
    CR 708.5 lets look at it — its controller — and for the rules that turn it
    face up. None for a face-up object."""
    return hidden_card(getattr(permanent, "card", None))


def may_look_at(game: "Game", seat: "int | None", obj) -> bool:
    """CR 708.5: "you may look at a face-down spell you control on the stack
    or a face-down permanent you control (even if it's phased out). You can't
    look at … face-down spells or permanents controlled by another player."

    *obj* is a permanent or a stack object. A face-up object is anybody's to
    look at; ``None`` as the seat (a spectator) may look at no face-down one.
    """
    if not is_face_down(obj):
        return True
    if seat is None:
        return False
    if hasattr(obj, "caster_index"):
        return obj.caster_index == seat
    return game.controller_index_of(obj) == seat


# ---------------------------------------------------------------------------
# Morph (CR 702.37): the keyword line and the alternative cost it is
# ---------------------------------------------------------------------------

#: "morph {1}{g}{g}" as a keyword-line part reads after
#: ``normalize_creature_line`` (lowercased, reminder text gone).
_MORPH_PART = re.compile(r"^morph\s+(?P<cost>(?:\{[^{}]+\})+)$")

#: Any line that *is* a morph keyword line, readable or not — the word, then a
#: mana symbol or the dash a non-mana cost is printed behind ("Morph—Reveal a
#: white card", Legions). Megamorph is a different word and does not match.
_MORPH_SHAPE = re.compile(r"^morph\s*(?:[—–-]|\{)", re.IGNORECASE)

#: "Morph—Return a Bird you control to its owner's hand" — the dash a cost
#: that is not only mana is printed behind (CR 702.37a's "[cost]"), the cost
#: kept in its printed case.
_MORPH_DASH_PART = re.compile(r"^morph\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")

#: CR 702.37a's alternative cost, in the rule's own words: what the cost's
#: ``phrase`` is, so a log line or a prompt reads back the rule.
MORPH_RULES_TEXT = (
    "you may cast this card as a 2/2 face-down creature with no text, no "
    "name, no subtypes, and no mana cost by paying {3} rather than paying its "
    "mana cost"
)

#: What casting face down costs: CR 702.37a's "{3}", the same for every card.
MORPH_CAST_COST = "{3}"


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")


def morph_cost_text(part: str) -> str | None:
    """The morph cost one keyword-line *part* prints — mana symbols in upper
    case ("{1}{G}{G}"), or a cost behind a dash as printed ("Pay 5 life") —
    or None when the part is not a morph this engine can charge.

    The keyword-line gate's admission test (``keyword_lines.
    _qualified_keyword_part``), for ``madness.madness_cost_text``'s reason:
    the reader that charges the cost is the one that admits the line
    (:func:`morph_mana`, :func:`morph_price`). A hybrid or Phyrexian symbol
    refuses, and so does a cost behind a dash any clause of which the cost
    reader cannot charge ("Morph—Reveal a white card"), so a card printing one
    stays unsupported naming the line rather than turning face up for
    nothing. Scourge's four ("Pay 5 life", "Sacrifice two Mountains", "Return
    a Bird you control to its owner's hand", "Discard a Zombie card") read.

    An ``{X}`` is admitted (Legions: "Morph {X}{B}{B}", Bane of the Living;
    "Morph {X}{X}{R}", Warbreak Trumpeter): CR 107.3d has the player taking
    the special action choose X "immediately before they pay that cost", and
    the special-action seam announces it (``special_actions.
    take_permanent_special_action``'s ``x_value``) and hands it to the face-up
    triggers, CR 702.37f's "other abilities of that permanent may also refer
    to X".
    """
    stripped = _stripped(part)
    match = _MORPH_PART.match(stripped.lower())
    if match is not None:
        cost = match.group("cost").upper()
        if morph_mana(cost) is None:
            return None
        return cost
    # "Morph—**Pay 5 life**." (Zombie Cutthroat; Scourge prints four such
    # costs.) CR 702.37a's "[cost]" is any cost, and a cost that is not only
    # mana is printed behind a dash. Returned as printed, first letter up —
    # "Pay 5 life" — and admitted only when every clause of it reads
    # (:func:`morph_price`), so "Morph—Reveal a white card" still refuses its
    # line rather than turning face up for nothing.
    dashed = _MORPH_DASH_PART.match(stripped)
    if dashed is None:
        return None
    cost = dashed.group("cost").strip()
    cost = cost[:1].upper() + cost[1:]
    return cost if morph_price(cost) is not None else None


@dataclass(frozen=True)
class MorphPrice:
    """What paying one printed morph cost takes (CR 702.37e: "pay that cost"):
    its mana with each ``{X}`` as 0 (``x_symbols`` says how many — CR 107.3d
    has the taker choose X), and its clauses that are not mana, read into the
    record every printed alternative cost is read into
    (``alternative_costs._read_cost_clauses``), or None for a mana-only cost.
    """

    mana: "dict[str, int]"
    x_symbols: int = 0
    clauses: "AlternativeCost | None" = None


#: The clause fields a morph cost cannot carry: each needs a spell being cast
#: (a colour to share, an X the cast announces, a spell whose effect reads
#: what its cost exiled), and the special action is none of those. A cost
#: printing one refuses its line.
_SPELL_ONLY_CLAUSES = (
    "shares_color_with_spell", "sacrifice_count_x", "exile_graveyard_count_x",
    "exile_graveyard_filter",
)


def morph_price(printed: str | None) -> "MorphPrice | None":
    """The :class:`MorphPrice` of a printed morph cost — "{1}{U}{U}", "Pay 5
    life", "{2}, Sacrifice two Mountains" — or None when any part of it is one
    this engine cannot charge (an unread clause, a hybrid symbol, a clause
    only a cast can pay).

    Mana first, read as mana; whatever follows goes through
    ``alternative_costs._read_cost_clauses``, flashback's arrangement
    (``flashback._read_cost``): what "sacrifice two Mountains" charges is one
    answer whether Fireblast's alternative cost, Lava Dart's flashback or
    Skirk Volcanist's morph prints it, and the gate and payer behind those
    fields already exist (``special_actions`` asks them).
    """
    if not printed:
        return None
    from .alternative_costs import AlternativeCost, _read_cost_clauses
    from .flashback import _COST_PARTS, _lowered_clauses

    parts = _COST_PARTS.match(_lowered_clauses(printed.strip()))
    if parts is None:
        return None
    mana_text, rest = parts.group("mana"), parts.group("rest")
    if not mana_text and not rest:
        return None
    mana: "dict[str, int] | None" = {}
    if mana_text:
        mana = morph_mana(mana_text.upper())
        if mana is None:
            return None
    clauses = None
    if rest:
        fields = _read_cost_clauses(rest.lower())
        if fields is None or any(fields.get(name) for name in _SPELL_ONLY_CLAUSES):
            return None
        clauses = AlternativeCost(f"its morph cost, {printed}", **fields)
    return MorphPrice(
        mana=dict(mana or {}), x_symbols=morph_x_symbols(mana_text), clauses=clauses,
    )


def morph_x_symbols(printed: str | None) -> int:
    """How many ``{X}`` a printed morph cost carries — each is X generic mana
    once X is chosen (CR 107.3d). 0 for a cost with none, or for None."""
    return sum(
        1 for symbol in re.findall(r"\{([^{}]+)\}", printed or "")
        if symbol.upper() == "X"
    )


def morph_mana(printed: str | None, x_value: int = 0) -> "dict[str, int] | None":
    """What paying the printed morph cost *printed* takes with X = *x_value*,
    as the symbol dict every payment reads, or None when a symbol is one this
    engine cannot spend (hybrid, Phyrexian) or nothing is printed.

    CR 107.3d: "If a cost associated with a special action, such as … a morph
    cost, has an {X} or an X in it, the value of X is chosen by the player
    taking the special action immediately before they pay that cost." So each
    ``{X}`` is *x_value* generic mana; ``{}`` is a price of nothing at all
    ("{X}" with X = 0), which a seat may legally choose.
    """
    from .mana_payment import mana_cost_x_as_zero

    if not printed:
        return None
    base = mana_cost_x_as_zero(printed)
    if base is None:
        return None
    variable = morph_x_symbols(printed) * max(0, int(x_value or 0))
    if variable:
        base = {**base, "generic": int(base.get("generic", 0)) + variable}
    return base


def is_morph_line(line: str) -> bool:
    """Whether *line* is a morph keyword line at all, readable or not."""
    return bool(_MORPH_SHAPE.match(_stripped(line)))


def morph_cost(card) -> str | None:
    """*card*'s printed morph cost ("{1}{G}{G}"), or None when it prints no
    morph this engine can charge.

    Read off ``line_rewrites.expand_card_lines``, which is CLAUDE.md's rule
    for every reader of a card's lines.
    """
    if card is None or "morph" not in (card.oracle_text or "").lower():
        return None
    from .line_rewrites import expand_card_lines

    for line in expand_card_lines(card):
        cost = morph_cost_text(line)
        if cost is not None:
            return cost
    return None


def face_up_morph_cost(permanent) -> str | None:
    """The morph cost a face-down *permanent* would have **if it were face
    up** (CR 702.37e), or None.

    Read off its face-up copiable values (``copies.face_up_copiable_card``,
    CR 708.10) rather than off the card it hides: a Clone that copied a morph
    creature and was turned face down (Backslide) hides a Clone, which prints
    no morph, but face up it would be the creature it copied — morph and all.
    A face-down spell, or a permanent with no copy effect, answers off the
    hidden card exactly as before.

    **And with the text changes applied to the permanent** (CR 612, layer 3;
    CR 708.8: "Any effects that have been applied to the face-down permanent
    still apply to the face-up permanent"). Putrid Raptor's ruling
    (2004-10-04): "You can use a text-changing effect that changes creature
    types on this card while is it face down to change Zombie to something
    else. This will change the type of card you have to discard to turn it
    face up." So "Discard a Zombie card" reads "Discard a Goblin card" under
    an Artificial Evolution cast on the face-down creature.
    """
    if hidden_card_of(permanent) is None:
        return None
    if getattr(permanent, "metadata", None) is None:
        return morph_cost(hidden_card_of(permanent))
    from .text_changes import apply_text_changes, text_changes

    return morph_cost(apply_text_changes(
        face_up_copiable_card(permanent), text_changes(permanent),
    ))


def morph_alternative_cost(card) -> "AlternativeCost | None":
    """CR 702.37a's alternative cost, for a card that prints morph: {3}
    rather than its mana cost, as a face-down 2/2 — or None.

    The face-down status is not a field of the cost: it is what the cast path
    does when the announced cost is this one (:func:`is_morph_cost`), which is
    CR 702.37c's order — the card is turned face down as the announcement is
    made, before any characteristic of the spell is read.
    """
    if morph_cost(card) is None:
        return None
    from .alternative_costs import AlternativeCost

    return AlternativeCost(MORPH_RULES_TEXT, mana=MORPH_CAST_COST, keyword=MORPH)


def is_morph_cost(cost) -> bool:
    """Whether *cost* is the alternative cost a morph ability offers."""
    return cost is not None and getattr(cost, "keyword", None) == MORPH


def announced_morph_cost(
    game: "Game", seat: int, card, *, alternative_cost, permission,
    chosen_index: "int | None" = None,
) -> "AlternativeCost | None":
    """The morph cost this cast announces, or None (CR 702.37c, CR 601.2b).

    The cast announces "an alternative cost" (the flag every caller sends,
    ``Game.cast_from_hand(alternative_cost=True)``), and it is a morph cast
    when the one alternative cost this card may be cast for is its morph —
    asked of ``Game.applicable_alternative_costs``, the reader the picker,
    the AI and the payment share. A permission that *requires* a cost of its
    own (flashback, CR 118.9b) is that cast's cost and never a morph
    (CR 118.9a: one alternative cost per spell).

    Asked of the card **as its zone holds it**, before the cast path turns it
    face down: once it is face down it has no text and offers no cost at all.
    """
    if not alternative_cost:
        return None
    if permission is not None and getattr(permission, "cost", None) is not None:
        return None
    if is_face_down_card(card):
        return None
    offered = game.applicable_alternative_costs(seat, card)
    # *chosen_index* is CR 118.9a's choice where several apply (the morph
    # beside Dream Halls' discard); with one offered, naming none is naming it.
    if chosen_index is not None:
        picked = offered[chosen_index] if 0 <= chosen_index < len(offered) else None
    else:
        picked = offered[0] if len(offered) == 1 else None
    return picked if is_morph_cost(picked) else None


def cast_timing_card(
    game: "Game", seat: int, card, *, alternative_cost, permission=None,
    chosen_index: "int | None" = None,
):
    """The object a cast's **timing** is judged by: the face-down 2/2 for a
    morph cast, *card* for every other.

    CR 702.37c: "Any effects or prohibitions that would apply to casting a
    card with these characteristics (and not the face-up card's
    characteristics) are applied to casting this card" (and CR 708.4, CR
    601.3e). A flash grant scoped by type is one of those effects: "Any player
    may cast Sliver spells as though they had flash" (Quick Sliver) covers a
    Sliver cast face up and not the same card cast face down, which has no
    creature types (CR 708.2) — and the card's own printed flash is text the
    face-down spell does not have. The cast path already judges everything
    else by the face-down card (``_cast_onto_stack``); a gate that asks
    :func:`cast_timing.casts_at_instant_speed` *before* the cast is announced
    asks it of what this returns, with the announcement it is gating.
    """
    if announced_morph_cost(
        game, seat, card, alternative_cost=alternative_cost, permission=permission,
        chosen_index=chosen_index,
    ) is not None:
        return face_down_card(card)
    return card


def cast_announces_morph(game: "Game", seat: int, card, action) -> bool:
    """Whether a policy's cast *action* of *card* is a morph cast — the
    question :func:`announced_morph_cost` answers for the cast path, asked
    the same way (an alternative cost announced from the hand, no permission
    requiring a cost of its own). The simulator's ``face_down_casts`` honesty
    count reads it."""
    if not getattr(action, "alternative_cost", False):
        return False
    if getattr(action, "from_zone", "hand") != "hand":
        return False
    return announced_morph_cost(
        game, seat, card, alternative_cost=True, permission=None,
    ) is not None


# ---------------------------------------------------------------------------
# Turning face up (CR 702.37e, 708.7, 708.8) and face down (CR 708.2a/b)
# ---------------------------------------------------------------------------


def turn_face_up(
    game: "Game", permanent: "Permanent", *, how: str = "",
    x_value: "int | None" = None,
) -> bool:
    """Turn *permanent* face up (CR 708.8); whether it was face down.

    "As a face-down permanent is turned face up, its copiable values revert to
    its normal copiable values. Any effects that have been applied to the
    face-down permanent still apply to the face-up permanent. Any abilities
    relating to the permanent entering the battlefield don't trigger and don't
    have any effect, because the permanent has already entered the
    battlefield."

    So the permanent's card becomes the card it hid and nothing else moves:
    it is the same object, with the same id and timestamp. No entry ability is
    asked. The table recomputes what the board's statics give it — the face-up
    card may be a lord, or a creature a lord reaches — and then the "When this
    creature is turned face up" abilities it now has trigger
    (:data:`TURNED_FACE_UP`, CR 603.2: the event happened to an object that
    has them as it happens).

    *how* is for the log ("for its morph cost {1}{G}{G}"). The reveal is public
    (CR 702.37e: "show all players what the permanent's morph cost would be").
    Asked by the morph special action, by Illusionary Mask's replacement, and
    by an effect that turns a permanent face up without paying anything
    (CR 708.7; Ixidor's ruling, 2004-10-04: "its controller does not have to
    pay its Morph cost").

    *x_value* is the X chosen as the morph special action was taken, when its
    morph cost printed one (CR 702.37f: "The value of X in those abilities is
    equal to the value of X chosen as the morph special action was taken"),
    and it is what the face-up triggers resolve "X" as — "all creatures get
    -X/-X" (Bane of the Living), "create X 1/1 red Goblin creature tokens"
    (Warbreak Trumpeter). None everywhere else: an effect that turns the
    permanent face up takes no special action, so no X was chosen and the
    triggers' X is 0.
    """
    real = hidden_card(getattr(permanent, "card", None))
    if real is None:
        return False
    permanent.card = real
    controller = game.controller_index_of(permanent)
    owner = game.players[controller].name if controller is not None else "Its controller"
    game.log.append(
        f"{owner} turned a face-down creature face up: it is {real.name}"
        + (f" ({how})" if how else "")
    )
    game._recompute_continuous_effects()
    _announce_turned_face_up(game, permanent, controller, x_value=x_value)
    return True


def _announce_turned_face_up(
    game: "Game", permanent: "Permanent", controller, *, x_value: "int | None" = None,
) -> None:
    """Put the abilities the turn sets off on the stack (CR 603.3), in one
    CR 603.3b window: the just-turned permanent's own "When this creature is
    turned face up" (:data:`TURNED_FACE_UP`, dispatched here) and every
    permanent's "Whenever a permanent is turned face up" — an Aura's "When
    enchanted creature is turned face up" among them
    (:data:`PERMANENT_TURNED_FACE_UP`, announced here on the event bus and
    narrowed by ``event_filters._turned_face_up_filter``). One window, so the
    two kinds are one batch in APNAP order with each seat ordering its own.

    *x_value* rides each of the permanent's own as the X its text refers to
    (CR 702.37f), as an entry trigger carries its spell's (CR 107.3m); another
    permanent's ability has no X of the morph cost's to refer to."""
    from .events import emit
    from .trigger_utils import matching_triggers

    if controller is None:
        return
    found = list(matching_triggers(
        permanent.effective_card, condition_kinds={TURNED_FACE_UP},
    ))
    with game.putting_triggers_on_stack():
        for trig in found:
            game._enqueue_triggered_ability(
                controller_index=controller,
                source_permanent=permanent,
                instruction=trig.instruction,
                effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                x_value=x_value,
            )
            game.log.append(f"{permanent.card.name} triggered (turned face up)")
        # The permanent turned up is the object the event is about, frozen by
        # id (CR 400.7) for an effect that acts on it, and its controller for
        # one that names them (CR 603.10).
        emit(
            game, PERMANENT_TURNED_FACE_UP,
            subject=permanent,
            about_permanent_id=permanent.permanent_id,
            event_subject_permanent_id=permanent.permanent_id,
            event_subject_controller=controller,
        )


def turn_face_down(game: "Game", permanent: "Permanent") -> bool:
    """Turn a face-up *permanent* face down (CR 708.2a); whether it turned.

    "If a face-up permanent is turned face down by a spell or ability that
    doesn't list any characteristics for that object, it becomes a 2/2
    face-down creature with no text, no name, no subtypes, and no mana cost."
    And CR 708.2b: one already face down stays as it is — "nothing happens".

    The same object, as turning face up is: everything applied to it stays
    (CR 708.8's rule read the other way). Not yet asked by any card in a
    shipped set — Skittish Valesk's "turn this creature face down" is the
    first, and W1G2's — so it is here, beside the rule it is the other half
    of, rather than built for a card that does not exist yet. The log names
    the card that went face down: the table watched it happen.
    """
    card = getattr(permanent, "card", None)
    if card is None or is_face_down_card(card):
        return False
    permanent.card = face_down_card(card)
    game.log.append(f"{card.name} was turned face down")
    game._recompute_continuous_effects()
    return True


def reveal_departing(game: "Game", permanent: "Permanent") -> None:
    """CR 708.9 for a face-down permanent leaving the battlefield: "its owner
    must reveal it to all players as they move it".

    Asked by ``Game.remove_all_from_battlefield`` — the one transition out —
    for every departing permanent that is not merely phasing out (CR 708.5:
    a phased-out face-down permanent is still face down). The permanent's
    card becomes the card it hid, so the zone it is put into gets the real one
    whichever road put it there; :data:`FACE_DOWN_AS_IT_LEFT` keeps the
    departed object's characteristics the face-down ones, which is what it
    last was (CR 603.10). Nothing happens to a face-up permanent.
    """
    real = hidden_card(getattr(permanent, "card", None))
    if real is None:
        return
    permanent.card = real
    permanent.metadata[FACE_DOWN_AS_IT_LEFT] = True
    game.log.append(
        f"The face-down creature leaving the battlefield is revealed: it is "
        f"{real.name} (CR 708.9)"
    )


def revealed_as_it_moves(game: "Game", card, permanent=None):
    """*card*, revealed if it is a face-down object's (CR 708.9) — the seams a
    card enters a zone through ask this before ``faces.whole_card`` turns the
    stand-in into the card it hid, so the move is said in the log.

    *permanent* is the face-down permanent the card belongs to, when the seam
    knows it (``from_battlefield``): a permanent whose card a sweep puts into
    a zone before the battlefield is rebuilt is revealed there and then
    (:func:`reveal_departing`), so the removal that follows does not reveal
    it a second time. Returns *card* unchanged; the caller still asks
    ``whole_card``.
    """
    real = hidden_card(card)
    if real is None:
        return card
    if permanent is not None and hidden_card_of(permanent) is real:
        reveal_departing(game, permanent)
        return card
    game.log.append(f"The face-down spell is revealed as it moves: it is {real.name} (CR 708.9)")
    return card


def forget_face_down_departure(permanent: "Permanent") -> None:
    """Clear a departure's last-known record from a permanent object that is
    entering the battlefield again — it is a new object there (CR 400.7), and
    the face-down values it last had are not its values now."""
    permanent.metadata.pop(FACE_DOWN_AS_IT_LEFT, None)


# ---------------------------------------------------------------------------
# CR 702.37e as a special action (CR 116.2b)
# ---------------------------------------------------------------------------


def _morph_offer(game: "Game", permanent: "Permanent"):
    """The offer a face-down permanent with a morph ability makes to its
    controller: turn it face up for its morph cost (CR 702.37e).

    "If the permanent wouldn't have a morph cost if it were face up, it can't
    be turned face up this way" — read off what it would be face up
    (:func:`face_up_morph_cost`): the hidden card's own text, or what a copy
    effect on it would make it (CR 708.10). A permanent Illusionary Mask put
    face down has no morph cost unless its card prints one, and then this is
    its way up too: the rule is about the card, not about how it came to be
    face down.

    A morph cost printing ``{X}`` is offered at its fixed part, with the count
    of X symbols beside it (``SpecialActionOffer.x_symbols``): the seam adds X
    generic per symbol once the taker has chosen X (CR 107.3d). A cost that is
    not only mana ("Pay 5 life", Scourge) offers its clauses beside the mana
    (``SpecialActionOffer.clauses``), gated and paid by the seam.

    **What the board adds to a morph cost** is applied here, where the price
    is made: "All morph costs cost {2} more. (This doesn't affect the cost to
    cast creature spells face down.)" (Exiled Doomsayer) — read under the
    special action's own kind (:data:`TURN_FACE_UP`) by
    ``cost_modifiers.keyword_cost_modifiers``, never under :data:`MORPH`, the
    {3} face-down cast's, which the reminder text says it leaves alone. The
    increase before the reduction and a reduction off the generic part alone
    (CR 601.2f, 118.7a; ``reduce_cost``), the order the cast path keeps; a
    non-mana cost taxed {2} is a mixed one (pay 5 life *and* {2}).
    """
    from .cost_modifier_lines import CostReduction
    from .cost_modifiers import keyword_cost_modifiers, reduce_cost
    from .special_actions import SpecialActionOffer

    printed = face_up_morph_cost(permanent)
    if printed is None:
        return None
    price = morph_price(printed)
    if price is None:
        return None
    controller = game.controller_index_of(permanent)
    if controller is None:
        return None
    mana = dict(price.mana)
    more, less, _by = keyword_cost_modifiers(game, controller, TURN_FACE_UP)
    if more:
        mana["generic"] = int(mana.get("generic", 0)) + more
    if less:
        mana = {
            symbol: amount
            for symbol, amount in reduce_cost(mana, CostReduction(generic=less)).items()
            if amount
        }
    return SpecialActionOffer(
        seat=controller, mana=mana, x_symbols=price.x_symbols,
        clauses=price.clauses, purpose="turn a face-down creature face up",
    )


def _take_morph(
    game: "Game", seat: int, permanent: "Permanent", *, x_value: int = 0,
) -> None:
    """Turn *permanent* face up, its morph cost already paid by the seam —
    with the X the seam announced, for a cost that printed one (CR 702.37f)."""
    printed = face_up_morph_cost(permanent)
    announces_x = morph_x_symbols(printed) > 0
    how = f"for its morph cost {printed}" + (f" with X = {x_value}" if announces_x else "")
    turn_face_up(game, permanent, how=how, x_value=x_value if announces_x else None)


def _morph_entry_extras(game: "Game", permanent: "Permanent") -> dict:
    """What the client needs to show the offer: the price (CR 702.37e shows
    it to all players as the action is taken; before then the offer is the
    controller's alone, which is who this entry is listed for)."""
    printed = face_up_morph_cost(permanent)
    return {"morph_cost": printed} if printed else {}


def _register() -> None:
    from .special_actions import (PERMANENT_SPECIAL_ACTIONS, PermanentSpecialAction,
                                  register_permanent_special_action)

    if TURN_FACE_UP in PERMANENT_SPECIAL_ACTIONS:
        return
    register_permanent_special_action(PermanentSpecialAction(
        TURN_FACE_UP, _morph_offer, _take_morph, entry_extras=_morph_entry_extras,
    ))


_register()


__all__ = [
    "FACE_DOWN_AS_IT_LEFT",
    "FACE_DOWN_CHARACTERISTICS",
    "FACE_DOWN_NAME",
    "MASK_FACE_DOWN",
    "MORPH",
    "MORPH_CAST_COST",
    "PERMANENT_TURNED_FACE_UP",
    "TURNED_FACE_UP",
    "TURN_FACE_UP",
    "announced_morph_cost",
    "cast_announces_morph",
    "forget_face_down_departure",
    "face_down_card",
    "face_up_morph_cost",
    "hidden_card",
    "hidden_card_of",
    "is_face_down",
    "is_face_down_card",
    "is_morph_cost",
    "is_morph_line",
    "may_look_at",
    "morph_alternative_cost",
    "morph_cost",
    "morph_cost_text",
    "morph_mana",
    "morph_x_symbols",
    "reveal_departing",
    "revealed_as_it_moves",
    "turn_face_down",
    "turn_face_up",
]
