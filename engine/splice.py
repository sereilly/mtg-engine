"""Splice onto Arcane (CR 702.47): a static ability that functions from the hand.

CR 702.47a: "'Splice onto [quality] [cost]' means 'You may reveal this card
from your hand as you cast a [quality] spell. If you do, that spell gains the
text of this card's rules text and you pay [cost] as an additional cost to
cast that spell.'" So splice is **cast machinery, not a line**: the printed
line does nothing where it stands (an instant in a hand), and everything it
does happens to *another* spell while that spell is being cast. This module is
the whole of it, built from the stack item outward.

**What the stack item carries.** ``StackItem.spliced`` — one **segment** per
spliced card, in the order its effects happen (CR 702.47b: the caster chooses
the order, and "the effects of the main spell must happen first"). A segment
is itself a :class:`~engine.game_types.StackItem`, never put on the stack,
whose ``card`` is the spell *as its gained text reads* (:func:`spliced_text_card`)
and whose target fields are the targets chosen for that text (CR 702.47d). So
every question the engine already asks of a spell's announcement — the cast
gates (CR 601.2c), the stamp of an index into an id (CR 400.7), CR 608.2b's
"is every target illegal", the blanking of an illegal slot, the re-settled
seat of a target that changed hands, "becomes the target" — is asked of a
segment by the very method that asks it of a spell, unchanged.

**The gained text is the spell's** (CR 702.47c): "The spell has the
characteristics of the main spell, plus the rules text of each of the spliced
cards … Text gained by the spell that refers to a card by name refers to the
spell on the stack". A segment's card is therefore the *host* card — its name,
mana cost, colour, types — with the spliced card's rules text, the spliced
card's name rebound to the host's. Glacial Ray spliced onto Reach Through Mists
reads "Reach Through Mists deals 2 damage to any target.", compiles as a blue
spell's self-reference, and so may target a creature with protection from red
(the rule's own example). The splice line itself is not carried: it is a
static ability that functions only from a hand (CR 702.47a), so on the stack it
would say nothing, and carried it would offer a spell to be spliced onto
itself.

**What the resolver runs.** The main spell's text, then each segment's, in
order, as one resumable resolution (``resolution._resolve_card``) — the
context's *card* is the host card (the object that deals the damage, moves,
is named), its *text card* the segment's. The spliced card itself never moves:
it is revealed and stays in its owner's hand (CR 702.47a's example: "it can
later be cast normally or spliced onto another spell").

**What is lost, and when** (CR 702.47e): nothing is written onto any card, so
"the spell loses any splice changes once it leaves the stack" is the stack item
going away. A **copy** of the spell carries its segments (CR 707.10, and the
2004-12-01 ruling on Uyo, Silent Prophet: "If you copy an Arcane spell that has
cards spliced onto it, you'll copy the spliced text as well as the original
spell text").

**What the cast announces** (CR 601.2b): ``splice_cards``, a list of dicts —
``hand_index`` (the card's place in the caster's hand, as they look at it with
the spell still in it) plus the same target keywords a cast takes
(``target_player_index``, ``target_permanent_ids``, ``target_graveyard_indices``,
``target_stack_index``). A segment that names no target is given the first one
its picker offers, as a bare cast is (``bare_announcements``). Each splice cost
joins the total cost as an additional cost (CR 601.2f), before reductions —
Long-Forgotten Gohei's ruling: "The cost reduction applies to the total cost of
the Arcane spell, including any additional costs from cards spliced onto it."

**What is refused, before anything is paid** (:func:`announce_splices`): a host
that is not of the quality; the spell itself (it is on the stack, not in the
hand — the rulings: "A card with a splice ability can't be spliced onto itself");
a card named twice (CR 702.47b: "You can't splice any one card onto the same
spell more than once"); a card printing no splice; a spliced text whose targets
cannot be chosen (CR 702.47b: "You can't choose to use a splice ability if you
can't make the required choices (targets, etc.) for that card's rules text").
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from .line_normalization import normalize_creature_line

if TYPE_CHECKING:
    from .alternative_costs import AlternativeCost
    from .game import Game
    from .game_types import GraveyardTarget, StackItem
    from .models import CardDefinition, Permanent


#: The splice line as it survives ``normalize_creature_line`` — lowercased,
#: its reminder text gone: "splice onto arcane {1}{r}". The quality is a
#: phrase ("Arcane"; later sets print "Instant or Sorcery"), the cost one run
#: of mana symbols.
_SPLICE_PART = re.compile(
    r"^splice onto (?P<quality>[a-z][a-z ]*?)\s*(?P<cost>(?:\{[^{}]+\})+)$"
)

#: "Splice onto Arcane**—Tap an untapped white creature you control**."
#: (Betrayers of Kamigawa: Hundred-Talon Strike, Horobi's Whisper, Roar of
#: Jukai, Torrent of Stone, Veil of Secrecy.) CR 702.47a's "[cost]" is any
#: cost, and one that is not only mana is printed behind a dash — the
#: arrangement flashback's and morph's readers already take
#: (``flashback._FLASHBACK_COST_LINE``, ``face_down._MORPH_DASH_PART``).
_SPLICE_COST_PART = re.compile(
    r"^splice onto (?P<quality>[a-z][a-z ]*?)\s*[—–-]\s*(?P<cost>.+)$"
)

#: The clause fields a splice price cannot carry, each refused rather than
#: paid wrongly: a card taken from the hand (the hand holds the spliced cards
#: themselves, revealed, and no announcement names which other card pays), an
#: X (nothing announces one for a spliced text, ``_X_WORD``'s reason), the top
#: cards of a graveyard (a position, which two splices' exiles would contend
#: for in an order nothing announces), and a relation to the spell's colour.
#: No splice card prints any of them.
_UNPAYABLE_SPLICE_CLAUSES = (
    "exile_from_hand", "discard_from_hand", "sacrifice_count_x",
    "exile_graveyard_count_x", "exile_graveyard_position",
    "shares_color_with_spell",
)

#: Any line that *is* a splice keyword line, readable or not — the wider shape
#: the support gate asks (:func:`unread_splice_line`), for
#: ``entwine._ENTWINE_SHAPE``'s reason: a splice this module cannot read must be
#: reported as an ability nothing carries out, never dropped while the card's
#: other line keeps it supported.
_SPLICE_SHAPE = re.compile(r"^splice onto\b")

#: The qualities this engine can test a spell for, by the printed word: the
#: spell subtype the host must have. Arcane is the only one Champions of
#: Kamigawa prints (CR 205.3k); "Splice onto Instant or Sorcery" (Modern
#: Horizons) is a card-type quality and is refused until something reads it.
_SUBTYPE_QUALITIES = frozenset({"arcane"})

#: Why a segment's text uses no X: an {X} in a spliced card's text would be
#: the host's X or 0 depending on a rule (CR 107.3) nothing here decides, and
#: no splice card in the pool prints one. Refused at the cast, never guessed.
_X_WORD = re.compile(r"(?<![{\w])X(?![}\w])")


@dataclass(frozen=True)
class SpliceOffer:
    """One printed splice ability: the spell *quality* it splices onto (a
    lowercased subtype), its *cost*'s mana — the printed run ("{1}{R}"), empty
    for a cost with none — and its *price*, the part of the cost that is not
    mana ("Tap an untapped white creature you control"), or None.

    The price is read into the record every printed non-mana cost is read
    into (``alternative_costs.AlternativeCost``, through
    ``alternative_costs._read_cost_clauses`` — flashback's and morph's
    arrangement), so CR 601.2h's gate (``Game._unpayable_alternative_cost``)
    and payer (``Game._pay_alternative_cost``) behind those fields are the
    ones a splice cost is asked and paid through. It is an *additional* cost
    of the spell it is spliced onto (CR 702.47a), not an alternative one: the
    record is shared, the rule is not.
    """

    quality: str
    cost: str
    price: "AlternativeCost | None" = None


def splice_part_offer(part: str) -> SpliceOffer | None:
    """The splice ability one normalized keyword-line *part* states, or None
    for a part that is not one this engine carries out.

    The keyword-line gate's reader (``keyword_lines._argument_keyword_ability``),
    so a splice line is admitted exactly when the cast path can honour it — a
    quality it cannot test or a cost it cannot charge keeps the line refused.
    """
    from .mana_payment import mana_cost_from_symbols

    stripped = (part or "").strip()
    match = _SPLICE_PART.match(stripped)
    if match is None:
        dashed = _SPLICE_COST_PART.match(stripped)
        if dashed is None:
            return None
        quality = dashed.group("quality").strip()
        if quality not in _SUBTYPE_QUALITIES:
            return None
        read = _read_splice_cost(dashed.group("cost"), quality)
        if read is None:
            return None
        cost, price = read
        return SpliceOffer(quality=quality, cost=cost, price=price)
    quality = match.group("quality").strip()
    if quality not in _SUBTYPE_QUALITIES:
        return None
    cost = match.group("cost").upper()
    if mana_cost_from_symbols(cost) is None:
        return None
    return SpliceOffer(quality=quality, cost=cost)


def _read_splice_cost(
    printed: str, quality: str,
) -> "tuple[str, AlternativeCost | None] | None":
    """``(mana, price)`` for a splice cost printed behind a dash — the mana run
    in front ("" for none) and the clauses after it as an
    ``AlternativeCost`` (None for none) — or None when any part of it is one
    the cast path cannot charge.

    Mana first, read as mana; the clauses through
    ``alternative_costs._read_cost_clauses``, the reader morph's
    (``face_down.morph_price``) and flashback's (``flashback._read_cost``)
    costs go through, so "Sacrifice two Mountains" charges one thing wherever
    it is printed. Every clause must read (that reader's all-or-nothing
    rule), none may be one a splice cannot pay
    (:data:`_UNPAYABLE_SPLICE_CLAUSES`), and the price may name at most one
    battlefield payment — the caster names its permanents by id
    (``cost_permanent_ids``), and one list cannot say which permanent pays
    which of two verbs (``Game.alternative_cost_permanent_payment``).
    """
    from .alternative_costs import AlternativeCost, _read_cost_clauses
    from .flashback import _COST_PARTS, _lowered_clauses
    from .mana_payment import mana_cost_from_symbols

    parts = _COST_PARTS.match(_lowered_clauses(printed.strip()))
    if parts is None:
        return None
    mana_text, rest = parts.group("mana"), parts.group("rest")
    if not mana_text and not rest:
        return None
    mana = ""
    if mana_text:
        mana = mana_text.upper()
        if "{X}" in mana or mana_cost_from_symbols(mana) is None:
            return None
    price = None
    if rest:
        fields = _read_cost_clauses(rest.lower())
        if fields is None or any(fields.get(name) for name in _UNPAYABLE_SPLICE_CLAUSES):
            return None
        verbs = sum((
            fields.get("sacrifice_filter") is not None,
            fields.get("return_filter") is not None,
            bool(fields.get("tap_count")),
        ))
        if verbs > 1:
            return None
        price = AlternativeCost(
            f"splice onto {quality}—{printed.strip().lower()}",
            keyword=SPLICE, **fields,
        )
    return mana, price


#: ``AlternativeCost.keyword`` for a splice price: what a refusal calls it
#: ("its splice cost", ``Game._unpayable_alternative_cost``).
SPLICE = "splice"


def is_splice_line(line: str) -> bool:
    """Whether printed *line* is a splice keyword line, readable or not."""
    return _SPLICE_SHAPE.match(normalize_creature_line(line or "")) is not None


@lru_cache(maxsize=None)
def splice_offer(oracle_text: str) -> SpliceOffer | None:
    """The (readable) splice ability *oracle_text* prints, or None.

    Read off the **printed** text, which is what a card in a hand carries.
    Cached because the hand is asked on every cast of an Arcane spell.
    """
    if "plice onto" not in (oracle_text or ""):
        return None
    for line in oracle_text.split("\n"):
        offer = splice_part_offer(normalize_creature_line(line))
        if offer is not None:
            return offer
    return None


def unread_splice_line(oracle_text: str) -> str | None:
    """The first splice line of *oracle_text* this module cannot carry out,
    normalized — or None. The support gate's question (``engine/oracle.py``):
    an instant is supported when any of its lines compiles, so without it a
    splice nothing reads is a keyword silently dropped."""
    if "plice onto" not in (oracle_text or ""):
        return None
    for line in oracle_text.split("\n"):
        normalized = normalize_creature_line(line)
        if _SPLICE_SHAPE.match(normalized) and splice_part_offer(normalized) is None:
            return normalized
    return None


def splice_cost_symbols(offer: SpliceOffer) -> dict[str, int]:
    """*offer*'s cost as the symbol dict a payment reads (``{"generic": 1,
    "R": 1}``)."""
    from .mana_payment import mana_cost_from_symbols

    return dict(mana_cost_from_symbols(offer.cost) or {})


# ---------------------------------------------------------------------------
# The gained text (CR 702.47c)
# ---------------------------------------------------------------------------


def spliced_rules_text(spliced: "CardDefinition", host_name: str) -> str:
    """The rules text *spliced* gives a spell named *host_name*: every line
    but its splice line, with its own name rebound to the spell's
    (CR 702.47c: "Text gained by the spell that refers to a card by name
    refers to the spell on the stack, not the card from which the text was
    copied")."""
    lines = [
        line for line in (spliced.oracle_text or "").split("\n")
        if line.strip() and not is_splice_line(line)
    ]
    text = "\n".join(lines)
    if spliced.name and host_name and spliced.name != host_name:
        text = re.sub(
            rf"(?<![\w']){re.escape(spliced.name)}(?![\w'])", host_name, text,
        )
    return text


#: The spell-with-gained-text cards built so far, by what they are built from
#: — the strings the compiler keys a program by, so one (host, spliced) pair is
#: one object and its program is compiled once. Module-level rather than on
#: the host card's instance dict (``face_down.face_down_card``'s arrangement)
#: because the undo snapshot deep-copies every card, and a cache on the card
#: would be copied with it.
_SPLICED_TEXT_CARDS: dict[tuple, "CardDefinition"] = {}

#: The instance-dict key a spell-with-gained-text card keeps the **spliced**
#: card's name under: its own name is the host's (CR 702.47c), so the card the
#: text came from survives nowhere else. Read by :func:`segment_names`.
_SPLICED_FROM = "_spliced_from"


def spliced_text_card(
    host: "CardDefinition", spliced: "CardDefinition",
) -> "CardDefinition":
    """The spell *host* as the text *spliced* gave it reads (CR 702.47c): the
    host's name, mana cost, colour and types, with *spliced*'s rules text
    (:func:`spliced_rules_text`) and the keywords that text prints.

    What a splice segment's ``card`` is: compiled, it is the program the
    segment resolves; enumerated, its targets are chosen and judged as the
    host spell's (a blue spell may target a creature with protection from
    red). Never put in any zone and never moved.
    """
    key = (
        host.name, host.mana_cost, host.type_line, tuple(host.colors),
        host.oracle_text, spliced.name, spliced.oracle_text,
    )
    built = _SPLICED_TEXT_CARDS.get(key)
    if built is not None:
        return built
    built = dataclasses.replace(
        host,
        oracle_text=spliced_rules_text(spliced, host.name),
        keywords=tuple(word for word in spliced.keywords if word.lower() != "splice"),
        face_of=None,
        face_down_of=None,
    )
    # ``faces.face_cards``' trick: a frozen dataclass refuses ``setattr`` but
    # its instance dict is an ordinary dict, and nothing here is a field.
    built.__dict__[_SPLICED_FROM] = spliced.name
    _SPLICED_TEXT_CARDS[key] = built
    return built


def spliced_from(card) -> "str | None":
    """The name of the card whose text *card* — a segment's — was gained
    from, or None for any other card."""
    return getattr(card, "__dict__", {}).get(_SPLICED_FROM)


# ---------------------------------------------------------------------------
# Who may splice what onto what
# ---------------------------------------------------------------------------


def spell_has_quality(game: "Game", card: "CardDefinition", seat: int, quality: str) -> bool:
    """Whether the spell *card*, cast by *seat*, is a *quality* spell — for
    Arcane, whether it has that subtype (CR 205.3k), through the one reader of
    an off-battlefield object's subtypes
    (``object_creature_types.card_creature_types``)."""
    from .object_creature_types import card_creature_types

    if quality in _SUBTYPE_QUALITIES:
        return quality in card_creature_types(game, card, seat)
    return False


def splice_candidates(
    game: "Game", seat: int, host: "CardDefinition", *,
    spell_hand_index: int | None,
) -> "list[tuple[int, CardDefinition, SpliceOffer]]":
    """``(hand_index, card, offer)`` for every card in *seat*'s hand that may
    be spliced onto the spell *host* — every card but the spell itself
    (*spell_hand_index*, None for a spell cast from elsewhere) printing a
    splice whose quality the host has. What the wire offers and what the cast
    path accepts start from this one list; whether a candidate's targets can
    be chosen is the announcement's own question (:func:`announce_splices`)."""
    hand = game.players[seat].hand
    found = []
    for index, card in enumerate(hand):
        if index == spell_hand_index:
            continue
        offer = splice_offer(card.oracle_text or "")
        if offer is None or not spell_has_quality(game, host, seat, offer.quality):
            continue
        found.append((index, card, offer))
    return found


def spliced_segments(item) -> "tuple[StackItem, ...]":
    """The splice segments *item* carries (``StackItem.spliced``), oldest
    first — empty for every object nothing was spliced onto."""
    return tuple(getattr(item, "spliced", ()) or ())


def segment_names(item) -> list[str]:
    """The names of the cards spliced onto *item*, in order — for a log line
    or the client's stack view."""
    return [
        spliced_from(segment.card) or segment.card.name
        for segment in spliced_segments(item)
    ]


def copied_segments(item, controller_index: int) -> "tuple[StackItem, ...]":
    """*item*'s segments as a **copy** of it carries them (CR 707.10, the Uyo
    ruling): each its own object with its own target lists, so a slot
    CR 608.2b blanks on one is not blanked on the other."""
    from .game_types import (StackItem, as_graveyard_stamps, as_target_ids,
                             as_target_slots)

    return tuple(
        StackItem(
            card=segment.card,
            caster_index=controller_index,
            target_player_index=segment.target_player_index,
            target_permanent_index=as_target_slots(segment.target_permanent_index),
            target_permanent_id=as_target_ids(segment.target_permanent_id),
            target_graveyard_card=as_graveyard_stamps(segment.target_graveyard_card),
            x_value=None,
            target_stack_item=segment.target_stack_item,
            choices=dict(segment.choices),
            is_copy=True,
        )
        for segment in spliced_segments(item)
    )


# ---------------------------------------------------------------------------
# The announcement (CR 601.2b, 601.2c, 601.2f)
# ---------------------------------------------------------------------------


def announce_splices(
    game: "Game", caster_index: int, host: "CardDefinition",
    splice_cards: "list[dict] | None", *, spell_hand_index: int | None,
    spell_graveyard_slot: int | None = None,
) -> "tuple[tuple[StackItem, ...], dict[str, int], list[str], tuple[SplicePayment, ...], str | None]":
    """``(segments, cost, names, payments, refusal)`` for a cast of *host*
    that reveals *splice_cards* (see the module docstring for the shape).

    *segments* are the stack objects' segments, their targets announced,
    defaulted where none was named, judged by the cast's own gates and stamped
    into ids — all before anything is paid, so a sacrifice or a discard the
    cast pays afterwards cannot renumber what they name. *cost* is every splice
    cost's mana summed (CR 601.2f's additional costs), *names* the revealed
    cards in order, and *payments* each splice cost that is not mana with what
    pays it settled (:class:`SplicePayment`, :func:`pay_splice_costs`). A
    refusal leaves nothing written.

    *spell_graveyard_slot* is where the spell sits in its caster's graveyard
    when it is cast from there: CR 601.2a puts it on the stack first, so it
    cannot be one of the cards a splice's graveyard exile takes.
    """
    if not splice_cards:
        return (), {}, [], (), None
    from .bare_announcements import (announced_fields, announced_seat,
                                     default_cast_target, names_an_object)
    from .classifier import classify_card
    from .game_types import StackItem, as_target_ids, as_target_slots
    from .oracle import compile_card_oracle
    from .target_keywords import announced_slot, cast_target_zone

    hand = game.players[caster_index].hand
    taken: set[int] = set()
    segments: list = []
    cost: dict[str, int] = {}
    names: list[str] = []
    # What the splice costs settled so far take (:func:`_settled_price`): one
    # permanent pays one splice cost and one graveyard card one exile, so two
    # Hundred-Talon Strikes want two white creatures, never one tapped twice.
    payments: list[SplicePayment] = []
    claimed: list = []
    claimed_slots: set[int] = set()
    life_claimed = 0
    for entry in splice_cards:
        entry = dict(entry or {})
        hand_index = entry.get("hand_index")
        if isinstance(hand_index, bool) or not isinstance(hand_index, int) or not (
            0 <= hand_index < len(hand)
        ):
            return (), {}, [], (), f"no card in hand at {hand_index!r} to splice onto {host.name}"
        if hand_index == spell_hand_index:
            return (), {}, [], (), (
                f"{host.name} can't be spliced onto itself: it is on the stack, "
                f"not in the hand (CR 702.47a)"
            )
        if hand_index in taken:
            return (), {}, [], (), (
                f"{hand[hand_index].name} can't be spliced onto the same spell "
                f"twice (CR 702.47b)"
            )
        taken.add(hand_index)
        spliced = hand[hand_index]
        offer = splice_offer(spliced.oracle_text or "")
        if offer is None:
            return (), {}, [], (), f"{spliced.name} has no splice ability"
        if not spell_has_quality(game, host, caster_index, offer.quality):
            return (), {}, [], (), (
                f"{spliced.name} splices onto {offer.quality.title()} spells, "
                f"and {host.name} is not one (CR 702.47a)"
            )
        text_card = spliced_text_card(host, spliced)
        program = compile_card_oracle(text_card)
        if not program.supported:
            return (), {}, [], (), (
                f"{spliced.name}'s rules text is not supported: {program.reason}"
            )
        if program.modes:
            return (), {}, [], (), (
                f"{spliced.name}: splicing a modal text is not supported"
            )
        if _X_WORD.search(text_card.oracle_text or ""):
            return (), {}, [], (), f"{spliced.name}: splicing a text with X is not supported"

        # CR 702.47d: "Choose targets for the added text normally (see rule
        # 601.2c)" — so in each zone's own keyword, defaulted and gated
        # exactly as the cast's own announcement is (``_cast_onto_stack``).
        zone = cast_target_zone(text_card)
        seat, slot, keyword_refusal = announced_slot(
            game, zone, name=spliced.name,
            target_player_index=entry.get("target_player_index"),
            target_permanent_ids=entry.get("target_permanent_ids"),
            target_graveyard_indices=entry.get("target_graveyard_indices"),
        )
        if keyword_refusal is not None:
            return (), {}, [], (), keyword_refusal
        ids = None if zone != "battlefield" else entry.get("target_permanent_ids")
        stack_index = entry.get("target_stack_index")
        stack_item = (
            game.stack[stack_index]
            if isinstance(stack_index, int) and 0 <= stack_index < len(game.stack)
            else None
        )
        no_target_answers_x = False
        if not names_an_object(slot, ids, stack_item):
            default, no_target_answers_x = default_cast_target(
                game, caster_index, text_card, named_seat=seat,
                optional_cost_payments={}, x_value=None,
            )
            named = announced_fields(game, default) if default is not None else {}
            if "target_player_index" in named:
                seat = named["target_player_index"]
            if "target_permanent_index" in named:
                slot = named["target_permanent_index"]
            if named.get("target_permanent_ids"):
                ids = named["target_permanent_ids"]
            if named.get("target_stack_item") is not None:
                stack_item = named["target_stack_item"]
        beside = announced_seat(game, caster_index, text_card, seat)
        if beside is not None:
            seat = beside
        refusal = game._mode_target_refusal(
            card=text_card, caster_index=caster_index, chosen_modes=(),
            classification=classify_card(text_card), divided_targets=None,
            from_zone="hand", mode_index=None,
            no_target_answers_x=no_target_answers_x, optional_paid={},
            role_seats=None, target_permanent_ids=ids,
            target_permanent_index=slot, target_player_index=seat,
            target_stack_item=stack_item, x_value=None,
        )
        if refusal is not None:
            return (), {}, [], (), (
                f"{spliced.name} can't be spliced onto {host.name}: "
                f"{refusal.details} (CR 702.47b)"
            )
        # CR 702.47a's "[cost]" when it is not only mana: what pays it is
        # chosen now (CR 601.2b) and held whole (CR 601.2h), out of what the
        # splices before this one have not already claimed.
        payment, price_refusal = _settled_price(
            game, caster_index, host, spliced, offer, entry,
            claimed=claimed, claimed_slots=claimed_slots,
            life_claimed=life_claimed,
            spell_graveyard_slot=spell_graveyard_slot,
        )
        if price_refusal is not None:
            return (), {}, [], (), price_refusal
        if payment is not None:
            payments.append(payment)
            claimed.extend(payment.permanents)
            claimed_slots.update(payment.slots)
            life_claimed += payment.price.pay_life
        segment = StackItem(
            card=text_card,
            caster_index=caster_index,
            target_player_index=seat,
            target_permanent_index=as_target_slots(slot),
            target_permanent_id=as_target_ids(ids),
            x_value=None,
            target_stack_item=stack_item,
        )
        # The index is consumed into an id now, at CR 601.2c, by the push's
        # own stamping: a cost the cast pays below (a sacrifice, a discard)
        # renumbers a battlefield or a graveyard behind it.
        game._stamp_stack_targets(segment)
        segments.append(segment)
        for symbol, count in splice_cost_symbols(offer).items():
            cost[symbol] = cost.get(symbol, 0) + count
        names.append(spliced.name)
    return tuple(segments), cost, names, tuple(payments), None


# ---------------------------------------------------------------------------
# A splice cost that is not mana (CR 702.47a, 601.2b, 601.2h)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplicePayment:
    """One spliced card's splice cost that is not mana, with what pays it
    settled at the announcement (CR 601.2b) — before anything is paid, so the
    CR 601.2h gate counts the objects the payment then takes.

    *permanents* pay its sacrifice, return or tap (by identity; named by the
    caster's ``cost_permanent_ids``, else the deterministic pick every cost's
    default makes), *graveyard* its graveyard exile (stamps, which survive the
    renumbering a spell leaving that pile makes), and *slots* are where those
    cards sat as the caster looked at the pile — what a later splice may no
    longer name.
    """

    name: str
    price: "AlternativeCost"
    permanents: "tuple[Permanent, ...]" = ()
    graveyard: "tuple[GraveyardTarget, ...]" = ()
    slots: "tuple[int, ...]" = ()

    @property
    def verb(self) -> "str | None":
        """The one battlefield payment the price names ("sacrifice",
        "return", "tap"), or None — ``_read_splice_cost`` admits at most one."""
        price = self.price
        if price.sacrifice_filter is not None:
            return "sacrifice"
        if price.return_filter is not None:
            return "return"
        if price.tap_count:
            return "tap"
        return None


def _settled_price(
    game: "Game", caster_index: int, host: "CardDefinition",
    spliced: "CardDefinition", offer: SpliceOffer, entry: dict, *,
    claimed: list, claimed_slots: "set[int]", life_claimed: int,
    spell_graveyard_slot: "int | None",
) -> "tuple[SplicePayment | None, str | None]":
    """``(payment, refusal)`` for *spliced*'s splice cost that is not mana —
    ``(None, None)`` for a cost that is only mana.

    The price is asked CR 601.2h's question through the gate every printed
    non-mana cost goes through (``Game._unpayable_alternative_cost``: the
    Mountains against "Sacrifice two Mountains", an opponent who may gain life
    against "An opponent gains 5 life"), then its objects are chosen out of
    what *claimed* and *claimed_slots* — the splices before it — left: the
    ones the caster named (``cost_permanent_ids``, by id; ``cost_graveyard_indices``,
    by place in the pile with the spell still in it), held to the printed
    count exactly (CR 601.2h: "Partial payments are not allowed"), else the
    deterministic pick. A name that cannot pay is a refusal with nothing
    spent, never a slide onto a neighbour.
    """
    price = offer.price
    named_ids = entry.get("cost_permanent_ids")
    named_slots = entry.get("cost_graveyard_indices")
    head = f"{spliced.name} can't be spliced onto {host.name}"
    if price is None:
        if named_ids or named_slots:
            return None, f"{head}: its splice cost is mana, and names nothing to choose"
        return None, None
    refusal = game._unpayable_alternative_cost(
        caster_index, host, price, spell_hand_index=None,
        spell_graveyard_slot=spell_graveyard_slot, refused_as=head,
    )
    if refusal is not None:
        return None, refusal
    caster = game.players[caster_index]
    if price.pay_life and caster.life < life_claimed + price.pay_life:
        return None, (
            f"{head}: {caster.name} cannot pay {price.pay_life} more life "
            f"with {caster.life - life_claimed} left to pay it (CR 119.4)"
        )
    payment = game.alternative_cost_permanent_payment(price)
    permanents: list = []
    if payment is None:
        if named_ids:
            return None, f"{head}: its splice cost names no permanent to choose"
    else:
        verb, count = payment
        candidates = [
            perm for perm in game._additional_cost_candidates(
                caster_index, price, giving_up=verb,
            )
            if not any(perm is taken for taken in claimed)
        ]
        if named_ids:
            if (
                not isinstance(named_ids, (list, tuple))
                or len(set(named_ids)) != len(named_ids)
                or len(named_ids) != count
            ):
                return None, (
                    f"{head}: its splice cost takes {count} permanent(s) to "
                    f"{verb}, each named once (CR 601.2h)"
                )
            for permanent_id in named_ids:
                found = game.permanent_by_id(permanent_id)
                if found is not None and any(found is taken for taken in claimed):
                    return None, (
                        f"{head}: {found.card.name} already pays another "
                        f"splice cost (CR 601.2h)"
                    )
                if found is None or not any(found is perm for perm in candidates):
                    return None, (
                        f"{head}: the permanent named to {verb} cannot pay "
                        f"its splice cost (CR 601.2h)"
                    )
                permanents.append(found)
        else:
            for _ in range(count):
                available = [
                    perm for perm in candidates
                    if not any(perm is picked for picked in permanents)
                ]
                if not available:
                    return None, (
                        f"{head}: nothing left to {verb} for its splice cost "
                        f"once the other splice costs are paid (CR 601.2h)"
                    )
                permanents.append(game.default_sacrifice_pick(available))
    stamps: list = []
    slots: list[int] = []
    if price.exile_graveyard_filter is not None:
        wanted = price.exiled_from_graveyard(None)
        candidates_slots = [
            slot for slot in game._graveyard_exile_candidates(
                caster_index, price, spell_slot=spell_graveyard_slot,
            )
            if slot not in claimed_slots
        ]
        if named_slots is not None:
            if (
                not isinstance(named_slots, (list, tuple))
                or len(set(named_slots)) != len(named_slots)
                or len(named_slots) != wanted
                or any(
                    isinstance(slot, bool) or slot not in candidates_slots
                    for slot in named_slots
                )
            ):
                return None, (
                    f"{head}: its splice cost exiles {wanted} card(s) from the "
                    f"graveyard, each named once out of the ones it can take "
                    f"(CR 601.2h)"
                )
            slots = list(named_slots)
        else:
            from .ai_prompt_readers import graveyard_price_order

            if len(candidates_slots) < wanted:
                return None, (
                    f"{head}: not enough cards left in the graveyard for its "
                    f"splice cost once the other splice costs are paid "
                    f"(CR 601.2h)"
                )
            slots = list(graveyard_price_order(
                game, caster_index, list(reversed(candidates_slots)),
            ))[:wanted]
        stamps = [game.graveyard_target_at(caster_index, slot) for slot in slots]
    elif named_slots:
        return None, f"{head}: its splice cost exiles nothing from a graveyard"
    return SplicePayment(
        name=spliced.name, price=price, permanents=tuple(permanents),
        graveyard=tuple(stamps), slots=tuple(slots),
    ), None


def pay_splice_costs(game: "Game", caster_index: int, host: "CardDefinition", payments) -> None:
    """Pay each settled splice cost that is not mana (CR 601.2h), through the
    payer every printed non-mana cost is paid through
    (``Game._pay_alternative_cost``): the permanents the announcement settled,
    the graveyard cards it stamped (re-located now — the spell may have left
    that pile), an opponent's life gain through ``Game._gain_life``.

    Paid first of the costs that are not mana — the order CR 601.2h leaves
    free — so the spell's own costs' deterministic picks
    (``_pay_additional_costs``) take from the board the splice costs leave,
    which :func:`splice_cost_conflict` checked could pay them.

    One cost, one event (CR 603.10a): every permanent the splice costs take
    off the battlefield leaves together (``leaving_together``), and a
    returned one's departure with them.
    """
    if not payments:
        return
    with game.entering_together(), game.leaving_together():
        for payment in payments:
            slots = None
            if payment.graveyard:
                slots = [
                    slot for slot in (
                        game.graveyard_index_of(stamp) for stamp in payment.graveyard
                    )
                    if slot is not None
                ]
            game._pay_alternative_cost(
                caster_index, host, payment.price, None,
                named_permanents=list(payment.permanents),
                graveyard_slots=slots,
                paying_for=f"splice {payment.name} onto {host.name}",
            )


def splice_cost_conflict(
    game: "Game", caster_index: int, host: "CardDefinition", payments, *,
    cast_costs=(), optional_paid=None, cost_permanent_ids=None,
    chosen_alternative=None, alternative_permanents=(), imposed=(),
    x_value: "int | None" = None,
) -> "str | None":
    """Why the spell's own costs cannot be paid beside its splice costs, or
    None (CR 601.2h: one total cost, paid whole).

    Each gate asks its own cost of the whole board; this asks the costs
    together. The splice costs are paid first (:func:`pay_splice_costs`), so
    what they sacrifice or return — and, for a price that taps, what they tap
    — is withheld from the spell's own: a permanent the caster named for the
    spell's cost (``cost_permanent_ids``, the alternative cost's named ones)
    or that an imposed sacrifice picked (Drought, *imposed*) may not be one a
    splice cost takes, and a cost that picks by default must still find
    enough once they are gone. Call for Blood's "sacrifice a creature" with
    Veil of Secrecy's "Return a blue creature you control" on a board of one
    blue creature is the case: each gate says yes, and together they cannot
    be paid.

    A spell whose own cost exiles from a graveyard is refused beside a splice
    cost that does: both name cards by their place in one pile, and nothing
    here settles which card pays which (no card prints both).
    """
    from .mixins.stack.cast_additional_costs import optional_cost_taken

    if not payments:
        return None
    gone = [
        perm for payment in payments if payment.verb in ("sacrifice", "return")
        for perm in payment.permanents
    ]
    tapped = [
        perm for payment in payments if payment.verb == "tap"
        for perm in payment.permanents
    ]
    head = f"{host.name} can't be cast with those splices"

    def taken_by_splice(perm, *, tapping: bool = False) -> bool:
        pool = gone + tapped if tapping else gone
        return any(perm is held for held in pool)

    for perm in imposed or ():
        if taken_by_splice(perm):
            return f"{head}: {perm.card.name} is owed to an imposed sacrifice (CR 601.2h)"
    named = [
        game.permanent_by_id(permanent_id)
        for permanent_id in (cost_permanent_ids or ())
        if isinstance(permanent_id, int)
    ]
    for perm in named:
        if perm is not None and taken_by_splice(perm):
            return (
                f"{head}: {perm.card.name} is named for its own cost and for a "
                f"splice cost (CR 601.2h)"
            )
    splices_exile_cards = any(payment.graveyard for payment in payments)
    for cost in cast_costs or ():
        if not optional_cost_taken(cost, optional_paid):
            continue
        if cost.exile_graveyard_filter is not None and splices_exile_cards:
            return (
                f"{head}: its own cost and a splice cost both exile cards from "
                f"the graveyard (not supported)"
            )
        if named:
            continue
        demands = (
            ("sacrifice", cost.sacrifice_filter,
             0 if cost.sacrifice_any_number else cost.sacrifice_count),
            ("return", cost.return_filter, cost.returned_count(x_value)),
            ("exile", cost.exile_filter, 1),
        )
        for verb, described, count in demands:
            if described is None or count <= 0:
                continue
            left = [
                perm for perm in game._additional_cost_candidates(
                    caster_index, cost, giving_up=verb,
                )
                if not taken_by_splice(perm)
            ]
            if len(left) < count:
                return (
                    f"{head}: not enough left to {verb} for its own cost once "
                    f"the splice costs are paid (CR 601.2h)"
                )
    alternative = chosen_alternative
    if alternative is not None:
        if splices_exile_cards and (
            alternative.exile_graveyard_filter is not None
            or alternative.exile_graveyard_position is not None
        ):
            return (
                f"{head}: its alternative cost and a splice cost both exile "
                f"cards from the graveyard (not supported)"
            )
        demand = game.alternative_cost_permanent_payment(alternative, x_value)
        if demand is not None:
            verb, count = demand
            tapping = verb == "tap"
            if alternative_permanents:
                for perm in alternative_permanents:
                    if taken_by_splice(perm, tapping=tapping):
                        return (
                            f"{head}: {perm.card.name} is named for its "
                            f"alternative cost and for a splice cost (CR 601.2h)"
                        )
            else:
                left = [
                    perm for perm in game._additional_cost_candidates(
                        caster_index, alternative, giving_up=verb,
                    )
                    if not taken_by_splice(perm, tapping=tapping)
                ]
                if len(left) < count:
                    return (
                        f"{head}: not enough left to {verb} for its alternative "
                        f"cost once the splice costs are paid (CR 601.2h)"
                    )
    return None


def spliced_steps(
    game: "Game", segments, card: "CardDefinition", caster_index: int, *,
    contexts_run: "list | None" = None, text_change_effects=(),
    cast_from_zone: str = "hand",
) -> list:
    """One resolution step per segment of *segments*, in order — what a spell
    whose printed card is *card*, controlled by *caster_index*, runs after its
    own text (CR 702.47b), each a step of the one resumable resolution
    (``resolution._resolve_card``, and the copy arm beside it).

    Each runs the segment's gained text as *card*'s (CR 702.47c): the
    context's card is the spell's own — the object that deals the damage, is
    moved, is named — and its text card the segment's, under any text change
    made to the spell (CR 612). Its targets are the segment's own, already
    judged by CR 608.2b with the rest of the spell's
    (``legality_resolution.illegal_targets_refusal``); its seat is the one its
    targets name, else the seat a spell that names nobody resolves at. The
    context each ran in is appended to *contexts_run* for the resolution's
    last step to read.
    """
    from .text_changes import spell_text_of

    def step_for(segment):
        def run() -> None:
            seat = game.stack_target_seat(segment)
            if seat is None:
                seat = segment.target_player_index
            if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
                seat = game._spell_default_seat(caster_index) % len(game.players)
            ran = game._apply_spell_text(
                game.players[caster_index],
                game.players[seat],
                card,
                text_card=spell_text_of(segment.card, text_change_effects),
                target_permanent_index=segment.target_permanent_index,
                target_permanent_id=segment.target_permanent_id,
                x_value=None,
                stack_target=segment.target_stack_item,
                cast_from_zone=cast_from_zone,
                choices=dict(segment.choices or {}),
                target_graveyard_card=segment.target_graveyard_card,
            )
            if contexts_run is not None:
                contexts_run.append(ran)
        return run

    return [step_for(segment) for segment in segments or ()]


def spliced_permanents(game: "Game", segments) -> list:
    """The permanents *segments* target, for the taxes scoped to what a spell
    targets (CR 601.2f: "spells that target this creature cost …")."""
    from .game_types import target_ids

    found = []
    for segment in segments:
        for permanent_id in target_ids(segment.target_permanent_id):
            if isinstance(permanent_id, int):
                permanent = game.permanent_by_id(permanent_id)
                if permanent is not None:
                    found.append(permanent)
    return found


__all__ = [
    "SpliceOffer",
    "announce_splices",
    "copied_segments",
    "is_splice_line",
    "segment_names",
    "spell_has_quality",
    "splice_candidates",
    "splice_cost_symbols",
    "splice_offer",
    "splice_part_offer",
    "spliced_permanents",
    "spliced_from",
    "spliced_rules_text",
    "spliced_segments",
    "spliced_steps",
    "spliced_text_card",
    "unread_splice_line",
]
