"""Shared helpers for effect handlers.

The leading underscore keeps this module out of the handler-registry import
pattern in ``engine/handlers/__init__.py`` — it registers no handlers, it only
hosts logic the registered handlers share.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Sequence


if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle_types import OracleInstruction
from ..layer_bridge import printed_shape, printed_supertypes
from ..oracle_types import (BLOCK_PAIR_SUBJECT, SACRIFICED_CARDS_BY_SEAT,
                           SUBJECT_FROM_TRIGGER)
from ..models import Permanent, PlayerState
from ..search_filters import card_has_type, name_key


def return_permanent_to_owners_hand(game, permanent, fallback_owner=None):
    """Take one permanent off the battlefield into its owner's hand (CR 400.3).

    The whole of what "return <permanent> to its owner's hand" *does*, in one
    place, because five callers perform it and each of them used to spell it
    out: the single bounce, the several-targets bounce, the sweep, the chosen
    bounce and the untap-step replacement. Three spellings of one move is three
    chances for one of them to forget the ledger.

    ``permanents_to_hand_this_turn`` is only bumped when the card actually
    arrived. ``put_card_into_hand`` answers False for a token ceasing to exist
    (CR 111.7), for a commander diverted to the command zone (CR 903.9b) and for
    a CR 614 replacement sending the card somewhere else — and "a permanent was
    put into your hand from the battlefield this turn" (Barrin) is false in
    every one of them.

    *fallback_owner* is the seat used when CR 108.3's owner cannot be derived,
    which for a permanent on the battlefield is nothing that happens — it is
    there so a caller that has an obvious answer states it rather than the
    helper inventing one.

    Returns the player whose hand it went to, which every caller logs.
    """
    owner_idx = game.owner_index_of(permanent)
    owner = game.players[owner_idx] if owner_idx is not None else fallback_owner
    if owner is None:
        owner = game.players[0]
    arrived = game.put_card_into_hand(
        owner, permanent.card, from_battlefield=permanent
    )
    if arrived and owner_idx is not None:
        game.permanents_to_hand_this_turn[owner_idx] = (
            game.permanents_to_hand_this_turn.get(owner_idx, 0) + 1
        )
    game.remove_from_battlefield(permanent)
    return owner


def attached_host(
    game: "Game", source: "Permanent | None", *, last_known: bool = True
) -> "Permanent | None":
    """The permanent *source* is attached to — or, when *source* has already
    left mid-resolution, the one it was last attached to (CR 603.10 last-known
    information) — provided that host is still on the battlefield.

    Cocoon is why the fallback exists: "…sacrifice it, put a +1/+1 counter on
    enchanted creature, and that creature gains flying" removes the Aura in
    the very resolution whose later steps name the enchanted creature, and
    ``detach_aura`` has already cleared the live record by then.

    ``last_known=False`` drops that fallback, and a **continuous** effect must
    pass it. CR 603.10 is about an ability that has already begun resolving;
    CR 611.3b says a continuous effect applies only while its criteria are met,
    and "the Aura is attached to it" is one of them. An Equipment that
    unattaches stays on the battlefield (CR 704.5n) with the record still on
    it, so a recompute reading last-known information would keep buffing the
    creature it used to be on — forever, and with nothing to undo.
    """
    if source is None:
        return None
    host = source.metadata.get("attached_to")
    if host is None and last_known:
        host = source.metadata.get("last_attached_to")
    if host is None or not game.is_on_battlefield(host):
        return None
    return host


def resolve_amount(raw: object, x_value: int | None) -> int:
    """Numeric value of a parsed amount payload; ``"x"`` resolves to the cast's
    X (never negative)."""
    # ``{"times_x": n}`` — "gets +2/+2 **for each** Aura attached to it" (Rabid
    # Wombat). The printed number is the size of one repetition, so the amount
    # is that number times the count. Its own shape rather than a factor on the
    # count spec, because one spec may feed two halves scaled differently.
    if isinstance(raw, dict):
        times = raw.get("times_x")
        if times is not None:
            return int(times) * max(0, x_value or 0)
        # ``{"plus_x": n}`` — "You gain **X plus 1** life" (An-Havva Inn). The
        # constant the sentence prints on top of its X, and the mirror of the
        # multiplier above: applied here, where every amount is resolved, so
        # there is no second site at which it could be honoured or forgotten.
        # Floored after the addition rather than before it, because the floor
        # belongs to the whole quantity — the card gains 1 with nothing on the
        # board, which is exactly what it prints.
        base = raw.get("plus_x")
        if base is not None:
            return max(0, int(base) + max(0, x_value or 0))
        raise ValueError(f"unreadable amount payload {raw!r}")
    return max(0, x_value or 0) if raw == "x" else int(raw)




def count_from_payload(
    game: "Game", context: "OracleExecutionContext", spec: dict,
    instruction: "OracleInstruction | None" = None,
    *,
    source: "Permanent | None" = None,
) -> int:
    """Evaluate an ``x_from_count`` spec at *resolution*.

    ``owner`` names whose zone is read — "you" is the effect's controller,
    "target" the player it points at — which is the only thing a resolution
    knows that a continuous recompute does not. Everything else is
    :func:`evaluate_count`.

    A resolution also knows the ability's **source**, which is the other thing a
    continuous recompute does not: "the number of **other** attacking creatures"
    (Alpine Houndmaster) excludes it, and `permanent_matches_filter` cannot —
    that is an identity comparison, not a property of a permanent.
    """
    # "…where X is **its** mana value" — a characteristic of one named object
    # rather than a count of a set, so it is answered here, where the context
    # knows which object the sentence named. `evaluate_count` is owner-scoped
    # and could not: a mana value belongs to a permanent, not to a player.
    # "…where X is the number of creatures that **died this way**" (Hellfire).
    # The count is one earlier step's result rather than anything on a board, so
    # it is read out of the resolution scratchpad — the same place "you gain
    # that much life" reads. `evaluate_count` could not answer it: it scans a
    # zone for a set that, by the time this is asked, is precisely the set that
    # is no longer there.
    back_reference = spec.get("back_reference")
    if back_reference is not None:
        # Scaled like every other aggregate below. "…equal to **half** the
        # damage dealt by one of those sorcery spells this turn, rounded down"
        # (Backdraft) is the first back-reference the pool halves, and a
        # rounding honoured at five return sites and forgotten at the sixth is
        # the dropped-rider bug this helper exists to make impossible. Every
        # earlier producer carries neither key, so `_scaled` is the identity
        # for all of them.
        return max(0, _scaled(int(context.results.get(back_reference, 0) or 0), spec))
    # "…for each **creature card** put into your graveyard this way" (Song of
    # Blood). The branch above one question over: that one reads a record that
    # is already a number, and this reads a record of the *cards themselves* and
    # asks how many of them the printed noun phrase names. A count could not
    # answer it — four cards were milled and the sentence is about the creatures
    # among them — which is why the mill records the list.
    #
    # Off the record and never off the graveyard: the pile also holds everything
    # that arrived by any other route, and the words say "this way". Matched
    # against each card's *printed* characteristics, because a card in a zone
    # has no computed ones (CR 613.1) — the same restriction
    # ``chargeable_card_filter`` puts on the lowering that wrote this spec.
    #
    # A delayed ability reads it through the very same channel: what the
    # creating resolution knew is handed back as ``captured_results``
    # (CR 608.2h), so the number is the one frozen when the spell resolved
    # however many attacks later the ability fires.
    recorded_cards = spec.get("recorded_cards")
    if recorded_cards is not None:
        described = spec.get("filter") or {}
        return max(0, _scaled(sum(
            1 for card in (context.results.get(str(recorded_cards)) or ())
            if _card_matches_filter(card, described)
        ), spec))
    # "…where X is the number of **+1/+1 counters on it**" (Primordial Ooze).
    # Counters sitting on the ability's own source: not a set of objects in any
    # zone, so `evaluate_count` has nothing to scan for it. The kind is data,
    # and `counters_on` is the one reader that knows whether it means the P/T
    # channel or a store the card invented (CR 122.1).
    # "…where X is the total power of the creatures sacrificed this way"
    # (Sword of the Ages). Not a set in any zone either: the creatures paid this
    # ability's cost (CR 601.2h) and are cards in a graveyard by now, so the sum
    # is over what the activation recorded — their last power on the
    # battlefield (CR 608.2h). A cost that ate nothing sums to zero, which is
    # what "any number of creatures" and none of them means.
    if spec.get("cost_sacrifices_power"):
        sacrificed = (context.choices or {}).get("sacrificed_set_for_cost") or ()
        return max(0, sum(max(0, perm.effective_power) for perm in sacrificed))
    counters = spec.get("source_counters")
    if counters is not None:
        source = context.source_permanent
        if source is None:
            return 0
        from ..named_counters import counters_on

        return counters_on(source, str(counters))
    # "…where X is 3 plus the amount of damage dealt to this creature this turn
    # by other sources named ~" (Blazing Effigy). A *history* rather than
    # anything on a board: `evaluate_count` scans zones, and the creature this
    # asks about is in a graveyard by the time a dies-trigger asks — with the
    # damage marked on it wiped when it left (CR 400.7).
    ledger_query = spec.get("damage_ledger")
    if isinstance(ledger_query, dict):
        return _damage_dealt_this_turn(game, context, ledger_query)
    # "…where X is **the exiled card's mana value**" (Necropolis). What the
    # ability's own cost ate, read off the record the activation path kept
    # (CR 608.2h) — asked before every board-scanning branch below, because
    # nothing on a board answers it.
    cost_exile = spec.get("cost_exile_characteristic")
    if cost_exile is not None:
        exiled = (context.choices or {}).get("exiled_for_cost")
        if exiled is None:
            return 0
        if cost_exile == "mana_value":
            return max(0, int(getattr(exiled, "cmc", 0) or 0))
        return 0
    # "…where X is **the sacrificed creature's mana value**" (Burnt Offering).
    # The branch above one zone over: what the spell's own additional cost ate
    # (CR 601.2b), off the record the payment path kept. The channel carries a
    # `Permanent`, so the mana value is read through its card.
    cost_sacrifice = spec.get("cost_sacrifice_characteristic")
    if cost_sacrifice is not None:
        sacrificed = (context.choices or {}).get("sacrificed_for_cost")
        card = getattr(sacrificed, "card", None) or sacrificed
        if card is None:
            return 0
        if cost_sacrifice == "mana_value":
            return max(0, _scaled(int(getattr(card, "cmc", 0) or 0), spec))
        # "…equal to half **the sacrificed creature's power**, rounded down"
        # (Freyalise Supplicant). The *effective* P/T the permanent last had on
        # the battlefield (CR 608.2h), read off the `Permanent` the payment path
        # recorded rather than off its card — the same read `target_gains_life`
        # has made for Life Chisel's toughness since that card landed, which is
        # why this is one more characteristic on an existing channel and not a
        # second channel. Read off `sacrificed`, not `card`: the printed numbers
        # are the card's and the computed ones are the permanent's.
        if cost_sacrifice in ("power", "toughness"):
            last_known = getattr(sacrificed, f"effective_{cost_sacrifice}", None)
            return max(0, _scaled(int(last_known or 0), spec))
        return 0
    # "…deals damage equal to **the tapped creature's power**" (Unerring
    # Sling). The channel beside the sacrifice above, with one difference that
    # matters: the creature is still on the battlefield, so this is a plain read
    # rather than last-known information — and it is read off the `Permanent`
    # for the numbers layer 7 computes, exactly as the sacrifice branch does.
    cost_tap = spec.get("cost_tap_characteristic")
    if cost_tap is not None:
        tapped = (context.choices or {}).get("tapped_for_cost")
        if tapped is None:
            return 0
        if cost_tap == "mana_value":
            card = getattr(tapped, "card", None) or tapped
            return max(0, _scaled(int(getattr(card, "cmc", 0) or 0), spec))
        if cost_tap in ("power", "toughness"):
            value = getattr(tapped, f"effective_{cost_tap}", None)
            return max(0, _scaled(int(value or 0), spec))
        return 0
    characteristic = spec.get("object_characteristic")
    if isinstance(characteristic, dict):
        # Scaled here, like every aggregate below: "…where X is **half** the
        # creature's power, rounded down" (Catacomb Dragon) puts the halving on
        # *this* spec, and this was the one computed quantity that never
        # reached `_scaled` at all. A scaling honoured at some return sites and
        # forgotten at others is the dropped-rider bug with an arithmetic face,
        # which is the reason that function exists.
        return _scaled(
            _characteristic_of_object(game, context, characteristic, instruction),
            spec,
        )
    scope = spec.get("owner", "you")
    if scope == "you":
        owner = context.caster
    elif scope == "target_opponent":
        # "…the number of creatures **target opponent** controls" (Superior
        # Numbers). The spell names two targets of different kinds and the
        # client picks only the object, so the seat arrives as the resolution's
        # default rather than as an announcement — right in a two-player game,
        # where CR 601.2c leaves the caster no other legal choice. What this
        # branch adds over the plain "target" scope beside it is CR 102.3: a
        # player is never their own opponent, so a default that landed on the
        # caster is not an answer, and the first living opponent is.
        chosen = context.target
        if chosen is None or chosen is context.caster:
            seats = game.opponents_of(game.players.index(context.caster))
            chosen = game.players[seats[0]] if seats else context.caster
        owner = chosen
    elif scope == "event_subject_player":
        # "At the beginning of each opponent's upkeep, … the number of …
        # **they control**" (Psychic Allergy). Nobody chose this seat, so
        # `context.target` is empty — the seat is the one the firing event was
        # about, frozen into the trigger's context (CR 603.10) by the upkeep
        # step. The same key the damage recipient beside it reads, so the count
        # and the damage can never land on two different players.
        seat = (context.trigger_context or {}).get("event_subject_player")
        owner = (
            game.players[seat]
            if isinstance(seat, int) and 0 <= seat < len(game.players)
            else context.caster
        )
    else:
        owner = context.target or context.caster
    # "…for each creature blocking **it**" (Barreling Attack), where "it" is
    # the creature the same sentence is pumping rather than the ability's own
    # source — a spell's source is a card on the stack and blocks nothing. The
    # caller that knows which object the sentence named passes it; everybody
    # else keeps the source, which is what the relation has always meant.
    #
    # ``exclude`` is deliberately left as the source: it implements the printed
    # word "other" (CR 109.5's own object), which is a different question from
    # what the relation is measured against.
    counted = evaluate_count(
        game, owner, spec,
        exclude=context.source_permanent,
        source=context.source_permanent if source is None else source,
    )
    # "…**in excess of** the number of …" (Superior Numbers). The subtrahend is
    # an ordinary count spec of its own, evaluated by re-entering here rather
    # than inside `evaluate_count`: that function takes one already-resolved
    # owner, and the whole content of the phrase is that the two halves are
    # counted on *different* seats. Clamped at zero, which is what "in excess
    # of" says (`ast.Minus`) and what every other subtraction in the pool does.
    subtrahend = spec.get("minus")
    if isinstance(subtrahend, dict):
        return max(0, counted - count_from_payload(
            game, context, subtrahend, instruction, source=source,
        ))
    return counted


def _damage_dealt_this_turn(game, context, query: dict) -> int:
    """How much damage the turn's ledger recorded, as one clause narrowed it.

    ``base`` is the constant the clause printed in front of the history
    ("**3 plus** …"), and it is paid whatever the history says — including when
    the source is gone and the history cannot be read at all. That is the
    honest reading of the card: Blazing Effigy deals 3 with nothing else on the
    board, and a reader that returned 0 for a missing source would turn its
    printed floor into a silent nothing.

    The name compared against is the source's *own* — the SELF token the clause
    printed — so no card name reaches this file.
    """
    from ..damage_ledger import (
        damage_dealt_to_permanent, damage_dealt_to_seat, source_name_of,
    )

    base = max(0, int(query.get("base", 0) or 0))
    source = context.source_permanent
    if query.get("recipient") == "you":
        # "…for each 1 damage **dealt to you** this turn." (Discordant Spirit.)
        # The same history and the same window as the permanent read below, over
        # the ledger's other recipient field — "you" being CR 109.5's controller
        # of the ability, which is ``context.caster`` for a trigger as much as
        # for a spell. No source narrowing: the clause prints none, and the
        # ``source_name`` default that Blazing Effigy needs would count only the
        # Spirit's own damage, which is none.
        seat = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        return max(0, base + damage_dealt_to_seat(game, seat))
    if query.get("recipient") != "source" or source is None:
        return base
    permanent_id = getattr(source, "permanent_id", None)
    wanted_name = source_name_of(source) if query.get("source_name") == "self" else None
    total = damage_dealt_to_permanent(
        game,
        permanent_id,
        source_name=wanted_name,
        # CR 109.5's "**other** sources": an identity comparison against the
        # ability's own source, which no property of a damage entry can make.
        exclude_source_permanent_id=permanent_id if query.get("others_only") else None,
    )
    return max(0, base + total)


def _characteristic_of_object(
    game: "Game", context: "OracleExecutionContext", spec: dict,
    instruction: "OracleInstruction | None" = None,
) -> int:
    """"…where X is **its** mana value" / "**its toughness minus 1**" — one
    named object's characteristic, plus whatever constant the clause printed.

    Not a count of a set, so it is answered here where the context knows which
    object the sentence named; :func:`evaluate_count` is owner-scoped and could
    not — a toughness belongs to a permanent, not to a player.

    The three characteristics are one lookup because the clause reads them the
    same way. Where they differ is *what* answers: CR 202.3 makes mana value a
    characteristic of the card, unaffected by anything on the battlefield, so
    it comes off the printed cost; CR 613 makes power and toughness computed,
    so they come through the layer accessors and a pumped creature answers with
    the number it currently has.

    The offset is applied before the floor, so "its toughness minus 1" on a 0/1
    is 0 rather than -1 — an amount is never negative here, and the sign a
    pump prints travels separately.

    The multiplier and the halving are **not** applied here. They ride the
    *outer* spec — "half the creature's power, rounded down" (Catacomb Dragon)
    is `{"object_characteristic": {…}, "half": "down"}` — and the offset above
    rides the inner one, so a `_scaled` call taken with this function's own
    argument would read the wrong dict and apply the offset twice. The caller
    scales, which is where every other aggregate is scaled too.
    """
    offset = int(spec.get("offset", 0) or 0)
    name = spec.get("characteristic", "mana_value")
    if spec.get("object") == "triggering_spell":
        # The spell the trigger's condition bound, carried on the event by the
        # cast fire site. Read here rather than off the stack top: by the time
        # the trigger resolves, anything could be above the spell that caused
        # it, and the stack top is a different object.
        cast_card = (context.trigger_context or {}).get("cast_card")
        if cast_card is None:
            return 0
        return max(0, int(getattr(cast_card, "cmc", 0) or 0) + offset)
    # "…where X is the power of **that blocked creature**" (Glyph of Delusion).
    # A sentence naming two targets of different kinds cannot be asked for "the
    # target": the clause said which, the lowering matched the printed words to
    # a role, and this reads that role's own slot. Absent for every one-target
    # sentence, which keeps the common path exactly as it was.
    role = spec.get("role")
    if role is not None:
        perm = resolve_role_permanent(
            game, context, (instruction.payload if instruction is not None else {}), role
        )
        if perm is None:
            return 0
    else:
        perm = resolve_target_permanent(
            game, context, predicate=lambda p: True, fallback_on_invalid_choice=False
        )
        if perm is None:
            return 0
    if name == "power":
        value = int(perm.effective_power)
    elif name == "toughness":
        value = int(perm.effective_toughness)
    else:
        value = int(getattr(perm.card, "cmc", 0) or 0)
    return max(0, value + offset)


def _scaled(total: int, spec: dict) -> int:
    """*total*, multiplied and halved as the spec says.

    "Round up **each time**" (Peer into the Abyss) is per calculation rather than
    once over the sentence, which is why the rounding is a property of each
    computed spec instead of the card — and the multiplier ("twice the number of
    white creatures that player controls", Jovial Evil) rides the same spec for
    the same reason. One place applies both, so every aggregate below scales
    without knowing it can: a factor honoured at one of the six return sites and
    forgotten at the other five is the dropped-rider bug with an arithmetic face.
    """
    # "…for each creature blocking it **beyond the first**" (Johtull Wurm; the
    # same words CR 702.23a gives rampage). Discounted before the multiplier,
    # because the phrase narrows *the set being counted* and the multiplier
    # sizes one repetition of it — and floored at zero, because a single
    # blocker means no repetitions rather than a negative one.
    total = max(0, total + int(spec.get("offset", 0) or 0))
    multiplier = int(spec.get("multiplier", 1) or 1)
    total = total * multiplier
    rounding = spec.get("half")
    if rounding is None:
        return total
    # "a third of their life" (Pox) is the same arithmetic with a different
    # denominator, so it is the same key with a number beside it rather than a
    # second rounding channel. Absent means 2, which keeps every spec written
    # before fractions existed byte-identical.
    divisor = max(1, int(spec.get("divide_by", 2) or 2))
    return -(-total // divisor) if rounding == "up" else total // divisor


def _resolve_chosen_color(filt: dict, source) -> dict:
    """*filt* with a ``chosen_color`` narrowing turned into a colour key.

    The colour a card chose as it entered (CR 614.1c) is recorded on the
    permanent, not in the sentence — so a noun phrase saying "of the chosen
    color" can only be answered by a reader holding that permanent. Callers
    without one leave the key in place and ``permanent_matches_filter`` refuses
    every permanent, which is the safe direction: a dropped narrowing would
    count (or destroy) the whole board.
    """
    if not filt.get("chosen_color"):
        return filt
    color = getattr(source, "metadata", {}).get("chosen_color") if source else None
    if not color:
        return filt
    resolved = dict(filt)
    resolved.pop("chosen_color", None)
    resolved["color_filter"] = color
    return resolved


#: The two narrowings "of the chosen type" can be, and where each one's word is
#: recorded on the source. Both are CR 614.1c choices made as the permanent
#: entered and both resolve to ``subtype_filter``; what separates them is the
#: *catalog* the word came from, which the sentence spells in its head noun —
#: CR 205.3m's creature types for An-Zerrin Ruins, CR 205.3i's land types for
#: Shimmer. One resolver rather than two, because two would be one idea spelled
#: twice with a metadata key changed.
_CHOSEN_SUBTYPE_KEYS = ("chosen_creature_type", "chosen_land_type")


def _resolve_chosen_subtype(filt: dict, source) -> dict:
    """*filt* with a "of the chosen type" narrowing turned into a subtype key.

    The type a card chose as it entered (CR 614.1c) is recorded on the
    permanent, not in the sentence — so "of the chosen type" can only be
    answered by a reader holding that permanent. The sibling of
    :func:`_resolve_chosen_color` one characteristic over, and it resolves the
    same way: into the ordinary key every matcher already reads, which for a
    subtype is ``subtype_filter`` and so goes through CR 613 layer 4 like any
    other type question.

    Callers without a source leave the key in place and
    ``permanent_matches_filter`` refuses every permanent, which is the safe
    direction: a dropped narrowing would hold the whole board down.
    """
    for key in _CHOSEN_SUBTYPE_KEYS:
        if not filt.get(key):
            continue
        word = getattr(source, "metadata", {}).get(key) if source else None
        if not word:
            continue
        resolved = dict(filt)
        resolved.pop(key, None)
        resolved["subtype_filter"] = word
        return resolved
    return filt


#: "…**that player** chooses artifact, creature, land, or non-Aura enchantment.
#: All nontoken permanents **of that type** phase out." (Teferi's Realm.) The
#: record the first sentence writes and the second reads, on the ability's own
#: source — the same place the CR 614.1c entry choices record theirs, so one
#: reader answers both.
#:
#: A **card type** rather than a subtype, which is why it is its own key and its
#: own resolver: CR 205.2's types and CR 205.3's subtypes are different halves of
#: the type line and land in different payload keys.
CHOSEN_CARD_TYPE = "chosen_card_type"

#: The printed options that name a type **and** a subtype to exclude, mapped to
#: the subtype. "Non-Aura enchantment" is Teferi's Realm's fourth option and the
#: only one in the pool; a card offering "non-Equipment artifact" would add a
#: row and nothing else.
#:
#: A table rather than a parse of the recorded string at read time, because the
#: string is what a *player* answered with: a prompt that accepted any
#: "non-<word> <type>" would let a seat invent an option the card never offered.
_QUALIFIED_CARD_TYPE_OPTIONS: dict[str, tuple[str, str]] = {
    "non-aura enchantment": ("enchantment", "aura"),
}


def chosen_card_type_filter(word: str) -> dict | None:
    """The filter keys the printed option *word* means, or None if it is not one.

    One function, read by the choice resolver (which validates an answer) and by
    :func:`_resolve_chosen_card_type` below (which applies it) — so what a player
    may choose and what the sweep then reaches cannot disagree.
    """
    from ..grammar.vocabulary import CARD_TYPES

    word = str(word or "").strip().lower()
    qualified = _QUALIFIED_CARD_TYPE_OPTIONS.get(word)
    if qualified is not None:
        card_type, excluded = qualified
        return {"type_filter": card_type, "exclude_subtypes": [excluded]}
    if word in CARD_TYPES:
        return {"type_filter": word}
    return None


def _resolve_chosen_card_type(filt: dict, source) -> dict:
    """*filt* with "of that type" turned into the ordinary type keys.

    The sibling of :func:`_resolve_chosen_subtype` one half of the type line
    over. Same contract in both directions: a caller with no source, or a source
    that has not chosen, leaves the key in place and ``permanent_matches_filter``
    refuses every permanent — which for a sweep that phases out the board is the
    only safe direction.
    """
    if not filt.get(CHOSEN_CARD_TYPE):
        return filt
    word = getattr(source, "metadata", {}).get(CHOSEN_CARD_TYPE) if source else None
    resolved_keys = chosen_card_type_filter(word) if word else None
    if resolved_keys is None:
        return filt
    resolved = dict(filt)
    resolved.pop(CHOSEN_CARD_TYPE, None)
    resolved.update(resolved_keys)
    return resolved


def evaluate_count(
    game: "Game", owner: "PlayerState", spec: dict, *, exclude=None, source=None
) -> int:
    """How much the amount a card *computes* currently is, for a named owner.

    CR 608.2: a where-clause is not announced with the spell, it is counted when
    the effect happens — and CR 604.3's characteristic-defining version is
    recounted continuously, which is the same question asked at a different
    moment. **One evaluator for both**, because the alternative is what this
    replaced: the pump handler carried its own graveyard counter under its own
    spelling of the spec (``card_types`` where every other reader says
    ``filter``), so "the number of creature cards in your graveyard" meant two
    things depending on which sentence it was printed in.

    ``filter`` is the ordinary object filter every other consumer agrees on, and
    ``aggregate`` says what to do with the objects it names — count them, or
    take the greatest power among them (Carrion Grub). An aggregate this does
    not know returns 0 rather than guessing, and the lowerings refuse it long
    before that.
    """
    # A count of a *history* rather than of a zone: the creatures counted are
    # exactly the ones no longer on the battlefield, so there is nothing to
    # scan. Per seat, because the game-wide tally cannot answer "under your
    # control" (round 14).
    history = spec.get("history")
    if history == "creatures_died_under_your_control":
        return int(getattr(owner, "creatures_died_under_your_control_this_turn", 0))
    if history == "creatures_into_your_graveyard":
        # "…for each creature put into **your graveyard** from the battlefield
        # this turn" (Asmira, Holy Avenger). The same window and the same event
        # as the row above, tallied for CR 400.3's owner instead of CR 109.5's
        # controller — one creature stolen and killed counts for one seat here
        # and for the other seat there, which is what the two printed phrases
        # say. Not a read of the pile: a token was in it for no time at all
        # (CR 111.7) and anything since could have moved a card out.
        return int(getattr(owner, "creatures_put_into_your_graveyard_this_turn", 0))
    if history is not None:
        return 0
    # A *named* board count rather than a count of objects in a zone: a player's
    # life total is not a pile to scan. Named for the reason `BoardCount` gives —
    # the lowering maps a name onto the one thing that computes exactly it, and a
    # name with no computation never reaches here.
    board_count = spec.get("board_count")
    if board_count is not None:
        return _scaled(int(owner.life) if board_count == "their_life" else 0, spec)
    filt = dict(spec.get("filter") or {})
    aggregate = spec.get("aggregate", "count")
    zone = spec.get("zone", "battlefield")
    # "the number of green creature cards in **the chosen player's** graveyard"
    # (Haunting Apparition). The seat was picked as *source* entered (CR 614.1c)
    # and is recorded on that permanent, so it is resolved here — where the
    # source is in hand — into the ``owner`` every branch below already reads.
    # One resolution site rather than a branch in each: the battlefield scan
    # takes its seat from ``game.players.index(owner)`` and the zone scan reads
    # the pile off ``owner`` directly, so a key honoured in one of them and
    # forgotten in the other would count the controller's own graveyard on one
    # sentence and the chosen player's on another.
    #
    # No record is a source still entering — the choice is part of arriving —
    # and an empty *count* is the honest answer for it, exactly as the
    # battlefield tally beside this one answers an empty board. Through
    # ``_scaled``, not a bare ``0``: the printed constant is part of the
    # sentence's arithmetic and not part of the pile, so Haunting Apparition is
    # 1/2 while it is still choosing rather than a 0/2 that dies on arrival.
    if spec.get("owner") == "chosen_player":
        chosen_seat = (
            source.metadata.get("chosen_player_index") if source is not None else None
        )
        if not isinstance(chosen_seat, int) or not (0 <= chosen_seat < len(game.players)):
            return _scaled(0, spec)
        owner = game.players[chosen_seat]
    # "the number of Auras **attached to it**" (Rabid Wombat). Not a scan of a
    # zone: what is attached to a permanent is a record kept on that permanent,
    # which is also why the owner scope above does not apply — an opponent's
    # Aura on your creature is attached to your creature and the sentence says
    # nothing about who controls it. A spec carrying the key with no source to
    # resolve it counts nothing, and the lowering refuses every referent but
    # this one so that cannot arrive from a card.
    # "…for each creature **blocking it**" (Johtull Wurm). A relation to one
    # named permanent rather than a property of each creature counted, so it is
    # resolved here beside `attached_to` and for that key's reason — and, like
    # it, it settles which pile is read: a blocker sits on the *defending*
    # player's battlefield, which the owner scope would have got wrong.
    # `creatures_blocking` is the same reader the damage step uses, so
    # band-propagated blocks (CR 702.22h) are counted once and not twice.
    if spec.get("blocking_source"):
        if source is None:
            return 0
        return _scaled(
            len([
                blocker for blocker in game.creatures_blocking(source)
                if permanent_matches_filter(blocker, filt)
            ]),
            spec,
        )
    attached_to = spec.get("attached_to")
    if attached_to is not None:
        if attached_to != "source" or source is None:
            return 0
        from ..auras import auras_attached_to

        return _scaled(
            len([
                attachment for attachment in auras_attached_to(source)
                if permanent_matches_filter(attachment, filt)
            ]),
            spec,
        )
    if zone == "battlefield":
        # "…the number of green creatures **on the battlefield**" (An-Havva
        # Constable, An-Havva Inn). CR 403.1 makes the battlefield one zone
        # shared by every player, so a phrase that scopes to it scopes to
        # nobody — the same ``owner: "all"`` the graveyard branch below already
        # answers for "in all graveyards" (Lhurgoyf), which is why it is one
        # more zone reading that key rather than a second key meaning it.
        # Through the control seam, because "on the battlefield" is every
        # permanent in play and `all_permanents` is the one answer to that.
        every_seat = spec.get("owner") == "all"
        seat = None if every_seat else game.players.index(owner)
        # "**Other** …" (CR 109.5) is an identity comparison against the ability's
        # own source, which the matcher deliberately does not answer — it is
        # about one permanent alone. A spec carrying the key with no source to
        # compare against counts nothing extra rather than silently dropping it:
        # the caller that has a source passes one, and the continuous recompute
        # that does not never produces the key.
        skip = exclude if filt.pop("exclude_self", False) else None
        # "permanents **of the chosen color**" (Psychic Allergy). The colour was
        # picked as *source* entered (CR 614.1c) and lives on that permanent, so
        # it is resolved here — where the source is in hand — into the ordinary
        # colour key every matcher already reads. `permanent_matches_filter`
        # refuses the unresolved key outright, so a caller with no source
        # counts nothing rather than counting the whole board.
        filt = _resolve_chosen_color(filt, source)
        # "creatures **of the chosen type**" (An-Zerrin Ruins), the same
        # resolution one line up for the same reason: the type was picked as
        # *source* entered and lives on that permanent, and the pure matcher
        # refuses the unresolved key so a caller with no source counts nothing.
        filt = _resolve_chosen_subtype(filt, source)
        scanned = game.all_permanents() if every_seat else game.controlled_by(seat)
        matched = [
            perm for perm in scanned
            if perm is not skip and permanent_matches_filter(perm, filt)
        ]
        if aggregate == "greatest_power":
            return _scaled(max((perm.effective_power for perm in matched), default=0), spec)
        if aggregate == "distinct_colors":
            # "for each color among permanents you control" (Chromatic Orrery).
            # Through the layer-aware accessor, because a permanent's colour is
            # computed (CR 613 layer 5) — a Mox that a text change made blue is
            # blue here. Colourless contributes nothing: CR 105.1 says
            # colourless is not a colour, so a board of artifacts draws nothing.
            seen: set[str] = set()
            for perm in matched:
                seen.update(permanent_effective_colors(perm))
            return _scaled(len(seen), spec)
        return _scaled(len(matched), spec)
    # "the number of creature cards in **all graveyards**" (Lhurgoyf). Every
    # player's copy of the zone rather than one player's, which is a property of
    # the printed phrase and so rides the spec — the same key that already says
    # "your graveyard". A caller that names no owner still gets the one it
    # passed, so nothing that worked changes.
    if spec.get("owner") == "all":
        piles = [getattr(player, zone, None) for player in game.players]
        cards = [card for pile in piles if pile is not None for card in pile]
    else:
        cards = getattr(owner, zone, None)
    if cards is None:
        return 0
    matched_cards = [
        card for card in cards
        if _card_matches_filter(card, filt, game=game, owner=owner)
    ]
    if aggregate == "greatest_power":
        # The *printed* power, because a card outside the battlefield has no
        # computed characteristics at all (CR 613 applies to permanents). A
        # creature card with a characteristic-defining power has none here
        # either, which is CR 604.3's own answer: its P/T is 0 in every zone but
        # the battlefield.
        return _scaled(
            max((_printed_power(card) for card in matched_cards), default=0), spec
        )
    return _scaled(len(matched_cards), spec)


def _printed_power(card) -> int:
    try:
        return int(card.power)
    except (TypeError, ValueError):
        return 0


def _zone_card_colors(card, *, game=None, owner=None) -> tuple[str, ...]:
    """The colours of a card in a zone, for the three keys below.

    One call rather than three, because the three keys are three readings of
    one fact and the version of this matcher that spelled it three times had
    already drifted once -- ``exclude_colors`` re-fetched the attribute where
    its two neighbours had cached it.
    """
    from ..object_colors import card_colors

    return tuple(card_colors(game, card, owner))


def _card_matches_filter(card, filt: dict, *, game=None, owner=None) -> bool:
    """Whether a *card* — not a permanent — answers a filter payload.

    A card in a zone has no computed characteristics, so the shared matcher
    (which asks ``has_type`` of a battlefield object) cannot answer here. Only
    what is printed on the card is testable — its type line and its name — and
    ``engine/subject_filters.py``'s ``CARD_ONLY_FILTER_KEYS`` is the list of
    exactly which keys that comes to. The lowerings refuse anything else rather
    than counting it as if it were not there.

    Types and subtypes both come off the printed line through the *same* reader
    the layer seed uses. The type test used to ask ``primary_type``, which
    collapses a multi-type line to one word — so "Artifact Creature — Construct"
    is a creature there but not an artifact, and "discard an artifact card"
    would have refused a card printed as one. CR 205.2a: a card has **every**
    type printed on it. No card in the pool asks the question the difference
    changes, which is why this is a widening of the reader rather than a fix
    with a card behind it.
    """
    types, subtypes = printed_shape(card)
    wanted = filt.get("type_filter")
    wanted_types = tuple(wanted) if isinstance(wanted, (list, tuple)) else ((wanted,) if wanted else ())
    if wanted_types and not any(t in types for t in wanted_types):
        return False
    # "Discard a **Shrine** card" (Sanctum of Shattered Heights). A subtype is
    # its own key, OR'd across alternatives exactly as the permanent matcher
    # OR's them, because "Djinn or Efreet" is one phrase either way.
    wanted_sub = filt.get("subtype_filter")
    wanted_subtypes = (
        tuple(wanted_sub) if isinstance(wanted_sub, (list, tuple))
        else ((wanted_sub,) if wanted_sub else ())
    )
    if wanted_subtypes and not any(s in subtypes for s in wanted_subtypes):
        return False
    # The conjunction spelling, AND'd — see `subtype_filter_all` in
    # permanent_matches_filter.
    wanted_all_subtypes = filt.get("subtype_filter_all") or ()
    if wanted_all_subtypes and not all(s in subtypes for s in wanted_all_subtypes):
        return False
    # "**nonland** card" (Amnesia). The negative of the test above, off the same
    # printed line and OR'd the same way: a card naming *any* excluded type is
    # out, which is what "noncreature, nonland" means when both are printed.
    excluded = filt.get("exclude_types") or ()
    if excluded and any(name in types for name in excluded):
        return False
    # The card-level twin of `type_filter_all`: "an **artifact creature** card".
    # Off the printed type line, which for a card in a zone is the whole of
    # what there is (CR 613.1).
    wanted_all_types = filt.get("type_filter_all") or ()
    if wanted_all_types:
        printed = (card.type_line or "").lower()
        if not all(name in printed for name in wanted_all_types):
            return False
    # "Discard a **legendary** card" (Niambi, Esteemed Speaker). Off the printed
    # line, which for a card in a zone is the whole of what there is (CR 613.1).
    wanted_supertypes = filt.get("supertypes") or ()
    excluded_supertypes = filt.get("exclude_supertypes") or ()
    if wanted_supertypes or excluded_supertypes:
        held = printed_supertypes(card.type_line)
        if not all(word in held for word in wanted_supertypes):
            return False
        if any(word in held for word in excluded_supertypes):
            return False
    # "…**except for basic lands**" / "…**other than a basic land**" (Eye of
    # Singularity prints both). The *pair* — CR 205.4a's Basic supertype and
    # the land card type — rather than the supertype alone: an exclusion by
    # supertype would be a different sentence, and the only reason it happens
    # to name the same cards today is that no printed non-land carries Basic.
    # Read off the printed line, which is what every other type read in this
    # pure matcher does.
    if filt.get("exclude_basic_lands"):
        printed_line = (card.type_line or "").lower()
        if "land" in printed_line and "basic" in printed_supertypes(card.type_line):
            return False
    # "creature cards **with mana value 3 or less**" (Idol of Endurance). Mana
    # value is one of the few characteristics a card has *everywhere* — CR 202.3
    # computes it from the printed mana cost, so unlike power or a keyword it
    # needs no battlefield object to be asked of. Same bound reader the permanent
    # matcher uses, so "3 or less" means one thing in both zones.
    if not _comparison_holds(filt.get("mana_value"), int(getattr(card, "cmc", 0) or 0)):
        return False
    # "the number of **white** cards in their hand" (Inquisition); "**white**
    # cards in their graveyards" (Nameless Race). The printed colours
    # (CR 202.2, derived from the mana cost) unless a board-wide static says
    # otherwise -- "the same is true for ... nonland cards you own that aren't
    # on the battlefield" (Celestial Dawn) is the one thing in the pool that
    # makes an off-battlefield colour more than what is printed, and it is a
    # property of a *seat*, so a caller that cannot say whose card this is gets
    # the printed answer it always got.
    colors = _zone_card_colors(card, game=game, owner=owner)
    color_filter = filt.get("color_filter")
    if color_filter and color_filter not in colors:
        return False
    # "…discard a **red or green** card" (Surge of Strength). The union
    # spelling of the key above — one filter carrying several colours, which is
    # how the noun parser reads a shared-head disjunction ("red or green card"
    # is one noun phrase, not two) — OR'd exactly as the permanent matcher OR's
    # it. Off the same printed colours and for the same reason (CR 202.2).
    any_colors = filt.get("any_colors")
    if any_colors and not any(color in colors for color in any_colors):
        return False
    # "a **nonblack** card" (Krovikan Sorcerer). The negative of the test above,
    # off the same printed colours, and OR'd the same way a type exclusion is: a
    # card carrying *any* excluded colour is out, which is what "nonblack,
    # nonred" would mean printed together.
    excluded_colors = filt.get("exclude_colors") or ()
    if excluded_colors and any(color in colors for color in excluded_colors):
        return False
    named = filt.get("named")
    # Through `name_key`, so the parser's rendering of a legendary name
    # ("chandra , flame 's catalyst") and Oracle's spelling of it compare equal —
    # the same reduction a search's named restriction already uses.
    return not named or name_key(card.name) == name_key(str(named))


def flip_coin(win_probability: float = 0.5) -> bool:
    """Flip a coin, returning True on a win (CR 705). Draws from the module-level
    RNG that ``run_ai_simulation`` seeds, so a given seed replays identically."""
    return random.random() < win_probability


def resolve_own_combatant(
    game: Game,
    context: OracleExecutionContext,
) -> tuple[PlayerState, int, Permanent] | None:
    """Resolve a trigger fired *on a permanent about itself* — the shape combat
    triggers use, where ``_fire_creature_attacks_triggers`` /
    ``_fire_creature_blocks_triggers`` thread the permanent's own controller and
    battlefield index through ``target``/``target_permanent_index``. Returns
    ``(controller, index, permanent)``, or ``None`` if the context no longer
    points at a live permanent (already left combat/the battlefield).

    An attack trigger is the clearest case for identity: it is put on the stack
    during declare-attackers and resolves after every other trigger above it,
    any of which may have destroyed a creature and shifted the attacker's slot.
    The index is still returned, because callers report it — but it is
    *re-derived* from the permanent the id found, never carried."""
    controller = context.target
    if controller is None:
        return None
    permanent_id = context.target_permanent_id
    if isinstance(permanent_id, int):
        found = game.permanent_by_id(permanent_id)
        if found is not None and game.controls(controller, found):
            index = game.battlefield_index_of(found)
            if index is not None:
                return controller, index, found
    idx = context.target_permanent_index
    if not isinstance(idx, int) or not (0 <= idx < len(controller.battlefield)):
        return None
    return controller, idx, controller.battlefield[idx]


def apply_temp_pt_boost(
    perm: Permanent, power: int = 0, toughness: int = 0, *, until: str = "end_of_turn"
) -> None:
    """Apply a P/T change that ends at *until* and track it so that duration's
    sweep can remove it. Thin wrapper over the single P/T write API in
    engine/pt.py; *until* names a channel in ``pt.TEMPORARY_PT_CHANNELS``."""
    from ..pt import add_pt_modifier

    add_pt_modifier(perm, power, toughness, until=until)


def apply_damage_to_creature(
    game: Game,
    perm: Permanent,
    amount: int,
    source,
    log_message: Callable[[int], str] | None = None,
    then: Callable[[int], None] | None = None,
    asks: bool = False,
    unpreventable: bool = False,
) -> int:
    """Mark non-combat damage on a single creature and fire its "dealt damage"
    triggers.

    Destruction is not this function's job: lethal damage is a state-based
    action (CR 704.5g, regeneration replacing it per CR 701.19), checked in
    ``check_state_based_actions``. Handlers used to have to call the sweep by
    hand at nine separate sites, and any new damage effect that forgot left a
    lethally damaged creature alive.

    ``log_message`` receives the damage actually dealt, and ``then`` is anything
    further the caller would do with it. Both run *inside* the damage event, not
    after it: the event can stop to ask the affected player which effect applies
    first (CR 616.1e), and while it waits there is nothing to report. Returns
    the amount dealt, which is 0 while suspended."""

    def finish(dealt: int) -> None:
        if log_message is not None:
            game.log.append(log_message(dealt))
        if dealt > 0:
            # Not gated on survival. "Whenever this creature is dealt damage"
            # triggers on the damage (CR 603.2), and whether the creature dies
            # is a state-based action that has not run yet — so the guard that
            # stood here (`damage_marked < effective_toughness`) was reading a
            # rule that does not exist. Harmless for Fungusaur, whose counter on
            # a dying creature does nothing anyway; wrong for Brash Taunter,
            # which is *indestructible* and reflects every point it takes.
            game._fire_dealt_damage_triggers(perm, dealt)
        if then is not None:
            then(dealt)

    return game._mark_damage_on_permanent(
        perm, amount, source=source, then=finish, asks=asks,
        unpreventable=unpreventable,
    )


def permanent_effective_colors(perm: Permanent) -> set[str]:
    """The color symbols a permanent currently has.

    Computed through the layer system, so a colour override (the laces) is an
    ordinary layer-5 continuous effect rather than a step in a precedence chain
    written out by hand — and a copy's colours arrive in layer 1 before it, as
    the copiable value CR 707.2a says they are.
    """
    return perm.effective_colors


def graveyard_card_matches(spec: dict, card) -> bool:
    """Whether *card* is a legal choice for a graveyard target described by
    *spec* — or by an instruction payload, which carries the same key names
    because the spec is derived from it.

    ``permanent_matches_filter``'s sibling one zone over, and here for the same
    reason: **one predicate, three readers.** The picker that offers the card,
    the cast-time re-check that admits it (idiom #9) and the handler that takes
    it were three copies, and they disagreed. The re-check asked only "is it a
    creature card?", so Reconstruction — "Return target **artifact** card from
    your graveyard to your hand" — refused every artifact its own picker
    offered, and with no creature in the pile could not be cast at all.

    The narrowed type is containment in the printed type line rather than
    ``primary_type``, because CR 205.2 makes an Ornithopter an artifact card
    *and* a creature card. The bare case keeps ``primary_type``, which is what
    the reanimation handlers ask of the card they put onto the battlefield.
    """
    card_types = tuple(spec.get("card_types") or ())
    # Through ``card_has_type``, not ``primary_type``: a card has **every** type
    # its line names (CR 205.2, idiom 15), so an Artifact Creature answers "an
    # artifact card" and "a creature card" both. ``primary_type`` picks one of
    # them by the order of a list, which is the reading the singular branch
    # below already stopped making - and the union was the last reader in this
    # function still making it. No shipped card exercises the difference today
    # (every union in the pool is instant/sorcery), which is exactly why it
    # would have gone on being wrong.
    if card_types and not any(card_has_type(card, name) for name in card_types):
        return False
    # "target **white or black** creature card" (Dreams of the Dead). A union:
    # the card answers when it is any one of the printed colours. It was a
    # single symbol read as ``colors[0]`` off a phrase that could name several,
    # so a two-colour phrase offered one colour and silently refused the other —
    # the narrowing this predicate exists to keep honest, in the direction that
    # takes cards away from the player.
    colors = spec.get("graveyard_colors")
    if colors and not any(color in card.colors for color in colors):
        return False
    # "target **Griffin** card" (Mtenda Griffin). Off the printed type line,
    # which for a card outside the battlefield is the whole of what there is
    # (CR 613.1) -- the same reader ``card_matches_filter`` uses for the
    # identical phrase in a hand. OR'd across alternatives, because "Djinn or
    # Efreet" is one phrase wherever it is printed.
    wanted_subtypes = tuple(spec.get("graveyard_subtypes") or ())
    if wanted_subtypes:
        held = printed_shape(card)[1]
        if not any(word in held for word in wanted_subtypes):
            return False
    # "up to four target **basic** land cards from a player's graveyard"
    # (Lodestone Bauble). Read off the printed type line, which for a card in a
    # graveyard is the whole of what there is (CR 613.1) — the same reader and
    # the same rule ``card_matches_filter`` above uses for the identical phrase
    # in a hand. Asked *after* the type and colour tests and before the
    # any-card exit, because a supertype narrows a phrase that already names a
    # type ("basic **land** cards") and is not an alternative to naming one.
    wanted_supertypes = tuple(spec.get("supertypes") or ())
    if wanted_supertypes:
        held = printed_supertypes(card.type_line)
        if not all(word in held for word in wanted_supertypes):
            return False
    if card_types or spec.get("any_card"):
        return True
    card_type = spec.get("card_type")
    if card_type is not None:
        return card_type in card.type_line.lower()
    return card.primary_type == "creature"


#: What each printed state adjective asks of a permanent. One table, because
#: the union above and the singular narrowings below it are the same words —
#: two readers would be two answers to "is this creature blocking?".
_STATE_TESTS = {
    "tapped": lambda perm: bool(perm.tapped),
    "untapped": lambda perm: not perm.tapped,
    "attacking": lambda perm: bool(perm.attacking),
    "blocking": lambda perm: perm.blocking_attacker_index is not None,
    "blocked": lambda perm: bool(perm.blocked),
    "unblocked": lambda perm: not perm.blocked,
}


def permanent_state_holds(perm, state: str) -> bool:
    """Whether the printed state word *state* is true of *perm* right now.

    The one reader of :data:`_STATE_TESTS` for callers holding a **state name**
    rather than a filter payload — a condition's "as long as it's blocking"
    (Snow Devil) and an intervening-if's "if it's tapped". Those used to read
    ``getattr(perm, state)``, which is right for ``tapped`` and ``attacking``
    and silently False forever for ``blocking``: a permanent has no such field,
    it has ``blocking_attacker_index``. A condition that can only be false is a
    static that never applies and a card that reports supported.

    ``attacked_this_turn`` is here too, and for the same reason — it is a mark
    in metadata, not a field — routed to the reader beside the stamp so this
    does not become a second place that knows the key.
    """
    from ..turn_state import BLOCKED_BY_BLOCKER_IDS_KEY, attacked_this_turn

    if state == "attacked_this_turn":
        return attacked_this_turn(perm)
    if state == "was_blocked_this_turn":
        # "When this creature dies, **if it was blocked this turn**, you gain 4
        # life." (Fyndhorn Druid.) A window of one turn, so it cannot be the
        # present-tense ``blocked`` above: that flag is the current combat's,
        # cleared when combat ends, and a creature killed in the second main
        # phase was still blocked this turn. The record is the pair list the
        # declare-blockers step writes and the cleanup step sweeps — the same
        # one "blocked or was blocked by" reads, so one block is one fact.
        #
        # Only the blockers' side. "Was blocked" is CR 509.1a from the
        # attacker's end, and the other list on the same permanent is the
        # attackers it blocked — reading both would make every Wall that
        # blocked answer yes to a sentence about being blocked.
        return bool(perm.metadata.get(BLOCKED_BY_BLOCKER_IDS_KEY))
    if state == "regenerated_this_turn":
        # "…**if this creature regenerated this turn**" (Spiny Starfish). The
        # record is a count, and this reading is the presence half of it — the
        # same key the token count reads, so "did it?" and "how many times?"
        # cannot come apart.
        from ..regeneration import REGENERATED_THIS_TURN

        return int(perm.metadata.get(REGENERATED_THIS_TURN, 0)) > 0
    if state == "was_dealt_damage_this_turn":
        # "At the beginning of each end step, **if this creature was dealt
        # damage this turn**, put a +0/+1 counter on it." (Wall of Resistance.)
        # The same key ``dealt_damage_this_turn`` reads as a *filter* on a
        # candidate (Giant Shark), read here as a question about one named
        # permanent — one record, so a Wall that was pinged and a Shark's
        # blocker cannot disagree about what "was dealt damage" means.
        #
        # Not ``damage_marked``: regeneration (CR 701.19a) and a toughness
        # rewrite each wipe that while the damage stays dealt, and the Wall's
        # counter is owed either way.
        return bool(perm.metadata.get("was_dealt_damage_this_turn"))
    test = _STATE_TESTS.get(state)
    # A word with no test behind it must not read as False: that is a condition
    # nobody answered wearing the answer "no". Every producer of a state name is
    # held to this table, so an unknown word is a bug, not a board state.
    if test is None:
        raise KeyError(f"no permanent-state test for {state!r}")
    return bool(test(perm))


def unblocked_attacker(perm) -> bool:
    """CR 509.1h — *perm* is an attacking creature nothing was declared to block.

    The one reading of the printed word, shared by the filter key below and by
    ``engine/replacements.py``'s source classes. An attacker with a blocker
    declared for it **is** a blocked creature and stays one even if every
    blocker leaves combat, so a trampler's excess damage to the player is not
    dealt "by an unblocked creature" — which is why this reads the permanent's
    own combat state rather than which loop the combat step is in. A creature
    not attacking at all is neither blocked nor unblocked, so it answers False
    here and to ``blocked_only`` alike.
    """
    return bool(getattr(perm, "attacking", False)) and not bool(
        getattr(perm, "blocked", False)
    )


def state_holds(perm: Permanent, word: str) -> bool:
    """Whether the printed state adjective *word* is true of *perm*.

    An unknown word answers False rather than True: a union nobody can test
    must narrow to nothing rather than admit everything, which for a *target*
    restriction is the direction that offers an illegal choice.
    """
    test = _STATE_TESTS.get(word)
    return bool(test and test(perm))


def permanent_matches_filter(perm: Permanent, payload: dict) -> bool:
    """Whether *perm* satisfies a target-filter payload (the key vocabulary
    produced by ``engine.grammar.ast.ObjectFilter.to_payload``:
    type/subtype/color filters, tapped_only, exclusions).

    Uses has_type/is_creature/effective colors so copies keep all their types
    (a Copy Artifact copy is an Artifact Enchantment), animated lands count as
    creatures, and color overrides are honored. Shared by destroy-target
    resolution, cast validation, and the legality enumerator so they can never
    disagree about what a filter means.
    """
    # "of the chosen color" (Psychic Allergy) names a colour recorded on the
    # *source* permanent (CR 614.1c), which this function does not have — it is
    # the pure half, about one permanent alone. Refusing rather than ignoring is
    # the direction that cannot widen an effect: `evaluate_count` and
    # `subject_filters.subject_matches` both hold a source and resolve the key
    # into `color_filter` before asking, so the key only survives to here when
    # nobody could answer it.
    if payload.get("chosen_color"):
        return False
    # "of the chosen type" (An-Zerrin Ruins) — the same recorded choice one
    # characteristic over, refused here for the identical reason: the record
    # lives on the *source*, this function is the pure half, and ignoring the
    # key would widen "creatures of the chosen type" to every creature.
    if payload.get("chosen_creature_type") or payload.get("chosen_land_type"):
        return False
    # "All nontoken permanents **of that type**" (Teferi's Realm) — the same
    # recorded choice on the other half of the type line, refused here for the
    # identical reason. Ignoring it would phase out *every* nontoken permanent
    # on the board rather than one type's.
    if payload.get(CHOSEN_CARD_TYPE):
        return False
    # "…creature **that attacked you this turn**" (Jabari's Influence). The
    # record names a *seat*, and this function has no observer — it is the pure
    # half, about one permanent alone. Refused rather than ignored for the
    # reason above it: ignoring would offer every creature that attacked
    # anybody, which in a duel is right by coincidence and wrong the moment a
    # third seat is at the table. ``subject_matches`` holds the observer and
    # answers it.
    if payload.get("attacked_you_this_turn"):
        return False
    # "creatures that didn't attack this turn" / "…except for creatures that
    # couldn't attack" (Season of the Witch). Both are per-turn records stamped
    # on the permanent itself — the first by the declaration, the second by the
    # declare-attackers step's turn-based action (CR 508.1) — so the pure
    # matcher answers them. Read at the sweep rather than re-derived: by the
    # end step a creature may have untapped or lost its restriction, and the
    # question is about the combat, not about now.
    if payload.get("attacked_this_turn") and not perm.metadata.get("attacked_this_turn"):
        return False
    if payload.get("not_attacked_this_turn") and perm.metadata.get("attacked_this_turn"):
        return False
    if payload.get("could_attack_this_turn") and not perm.metadata.get(
        "could_attack_this_turn"
    ):
        return False
    type_filter = payload.get("type_filter")
    subtype_filter = payload.get("subtype_filter")
    color_filter = payload.get("color_filter")
    tapped_only = payload.get("tapped_only", False)
    exclude_colors = payload.get("exclude_colors") or []
    exclude_types = payload.get("exclude_types") or []

    # "target **attacking or blocking** creature" (the four Legends pingers),
    # "**tapped or blocking**" (Tetsuo Umezawa). Answerable purely: "attacking"
    # is a field and CR 509.1a makes "blocking" one too — a creature is blocking
    # once it has been *declared* as a blocker, which is exactly what
    # `blocking_attacker_index` records. `state_holds` is the same test
    # `layer_bridge._QUALIFIER_HOLDS` uses, so a conditional buff and a target
    # restriction cannot disagree about what a state word means.
    any_states = payload.get("any_states")
    if any_states and not any(state_holds(perm, word) for word in any_states):
        return False

    # "target **attacking** creature" (Disharmony). The narrower half of the
    # union above, asked of the same field so a target restriction and the
    # picker cannot disagree about what "attacking" means.
    if payload.get("attacking_only") and not perm.attacking:
        return False

    # "target **blocking** creature" (Righteousness), "two target blocking
    # creatures …" (Sorrow's Path). The other half of the union above, asked of
    # the same ``state_holds`` table — the noun parser has produced this key
    # since the state adjectives were read, and until it was answered here the
    # narrowing was carried by the payload and tested by nothing that reads a
    # filter: ``subject_matches`` dropped it, so a role's re-check at CR 608.2b
    # and the picker both admitted a creature that is not blocking at all.
    if payload.get("blocking_only") and not state_holds(perm, "blocking"):
        return False

    # "target **nonattacking, nonblocking** creature" (Unlikely Alliance). The
    # same two readings negated, and asked through the same accessors so the
    # positive and negative halves of one word cannot come to disagree. A
    # creature in neither role is what the card names — not "any creature",
    # which is what these keys being unanswered would have meant.
    if payload.get("not_attacking") and perm.attacking:
        return False
    if payload.get("not_blocking") and state_holds(perm, "blocking"):
        return False

    # "…by **unblocked** creatures" / "**blocked** creature". CR 509.1h's pair,
    # asked through the one reading above so a redirect's source class, a
    # target restriction and the picker cannot disagree about the word.
    if payload.get("unblocked_only") and not unblocked_attacker(perm):
        return False
    if payload.get("blocked_only") and not (
        getattr(perm, "attacking", False) and getattr(perm, "blocked", False)
    ):
        return False

    # "a creature **that has been dealt damage this turn**" (Giant Shark). A
    # record stamped by `damage_events.deal_damage`, not a read of
    # ``damage_marked``: marked damage is what is *left* on the creature, and
    # regeneration (CR 701.19a) and a toughness rewrite both wipe it while the
    # damage stays dealt. Swept with the turn.
    if payload.get("dealt_damage_this_turn") and not perm.metadata.get(
        "was_dealt_damage_this_turn"
    ):
        return False

    # "target Aura attached to a **land**" (Pyramids) / "…to a **creature or
    # land**" (Enchantment Alteration). *What* the host is, as a nested noun
    # phrase rather than the tuple of card types this was: the printed host is
    # payload data, and a card narrowing its host any other way would otherwise
    # have needed a second key. Recursion, not a second rule — a host is a
    # permanent, so the question asked of it is this same question.
    #
    # The pure half answers only what a host can answer alone; a nested phrase
    # with a seat in it ("permanents **you control**") is
    # ``subject_filters.subject_matches``'s, which recurses with the observer it
    # has. This function never sees one, because the lowering that admits such a
    # phrase routes its sweep through the observed matcher.
    attached_host = payload.get("attached_to_filter")
    if attached_host:
        attached = perm.metadata.get("attached_to")
        if attached is None or not permanent_matches_filter(attached, attached_host):
            return False

    # "target permanent **that isn't enchanted**" (Time Elemental) — CR 303.4a.
    # The attachment record this engine keeps is shared with Equipment
    # (CR 301.5f attaches both the same way), so the *Aura subtype* is what is
    # asked: an equipped creature is not an enchanted one, and answering off the
    # bare list would have made Time Elemental refuse to bounce it.
    if payload.get("not_enchanted"):
        if any(
            attached.has_type("aura")
            for attached in (perm.metadata.get("attached_auras") or [])
        ):
            return False

    # "destroy **target enchanted** creature" (Ramses Overdark) — the positive
    # half, asked exactly as its negation above is: an Aura attached, not merely
    # something attached, because this engine shares the attachment record with
    # Equipment (CR 301.5f) and an equipped creature is not an enchanted one.
    if payload.get("enchanted_only"):
        if not any(
            attached.has_type("aura")
            for attached in (perm.metadata.get("attached_auras") or [])
        ):
            return False

    def _has_type(name: str) -> bool:
        # is_creature (not the printed line) so animated lands count.
        return perm.is_creature if name == "creature" else perm.has_type(name)

    # "a **black or artifact** creature" (Soldevi Adnate). A union across two
    # *axes* — CR 105 colour against CR 205.2 card type — which the keys below
    # cannot express because the engine ANDs them: `colors` plus `card_types`
    # describes a black creature that is *also* an artifact, which is not what
    # any of these cards print. Each alternative carries the axis it was read
    # on, so nothing here has to guess which vocabulary a bare word came from.
    #
    # ANDed against the head noun rather than replacing it: the phrase is "a
    # creature that is black or an artifact", so `card_types` above still has
    # to hold. The stack half of this key (`handlers/stack._spell_is_one_of
    # _classes`, "instant or Aura spell") empties `card_types` instead, which
    # is the same AND with nothing on the left.
    any_classes = payload.get("any_classes")
    if any_classes:
        def _class_holds(entry) -> bool:
            axis, name = entry[0], entry[1]
            if axis == "color":
                # CR 613 layer 5's answer, not the printed one — the same
                # accessor `color_filter` below is answered with, so a
                # recoloured permanent cannot match one key and miss the other.
                return name in permanent_effective_colors(perm)
            if axis == "card_type":
                return _has_type(name)
            if axis == "subtype":
                return perm.has_type(name)
            # An axis nothing here reads must refuse rather than be ignored:
            # a dropped alternative widens the union to everything.
            return False

        if not any(_class_holds(entry) for entry in any_classes):
            return False

    if type_filter:
        if type_filter == "artifact_or_enchantment":
            if not (perm.has_type("artifact") or perm.has_type("enchantment")):
                return False
        elif isinstance(type_filter, (list, tuple)):
            # A type union ("target artifact, creature, or land") — any match
            # qualifies.
            if not any(_has_type(name) for name in type_filter):
                return False
        elif not _has_type(type_filter):
            return False
    if subtype_filter:
        # A single subtype string, or several OR'd alternatives ("Djinn or
        # Efreet") as a list — any one matching is enough.
        #
        # has_type, not the printed type line: a land turned into a Swamp by
        # Magical Hack / Phantasmal Terrain / Evil Presence IS a Swamp under CR
        # 613 layer 4, and this function promises destroy-target resolution,
        # cast validation and the legality enumerator can never disagree about
        # what a filter means. Reading the printed line made it disagree with
        # layer 4 — the divergence is unreachable in the current pool (no card
        # here filters on a basic land subtype) but reachable the moment one
        # ships.
        subtypes = [subtype_filter] if isinstance(subtype_filter, str) else subtype_filter
        if not any(perm.has_type(s) for s in subtypes):
            return False
    # "an **Urza's Power-Plant**" — a conjunction of subtypes, the same
    # distinction `type_filter_all` draws for card types and for the same
    # reason. "Urza's Mine", "Urza's Power-Plant" and "Urza's Tower" are each
    # two land types (CR 205.3i), so OR'ing them would make any one of the three
    # satisfy all three and the assembly would complete on a single land.
    subtype_filter_all = payload.get("subtype_filter_all")
    if subtype_filter_all:
        if not all(perm.has_type(s) for s in subtype_filter_all):
            return False
    # "target **artifact creature**" — one permanent that is both types, as
    # against "target artifact, creature, or land", which is a union. The
    # grammar has drawn this distinction since it had a `type_match` field; it
    # emitted `type_filter_all` and lowering refused the line, because no
    # matcher answered it. This is that matcher.
    type_filter_all = payload.get("type_filter_all")
    if type_filter_all:
        if not all(_has_type(name) for name in type_filter_all):
            return False
    if tapped_only and not perm.tapped:
        return False
    colors = permanent_effective_colors(perm)
    if color_filter and color_filter not in colors:
        return False
    # "a green or white creature": any one of them is enough, and a gold
    # green-and-white creature answers both — CR 105.2b, a colour is a property
    # an object has rather than a category it is sorted into.
    any_colors = payload.get("any_colors")
    if any_colors and not any(color in colors for color in any_colors):
        return False
    if exclude_colors and any(c in colors for c in exclude_colors):
        return False
    if exclude_types and any(perm.has_type(t) for t in exclude_types):
        return False
    # "non-Spirit creature" (Roaming Ghostlight). has_type, like the positive
    # subtype test above, so a granted or layer-4 subtype excludes too.
    exclude_subtypes = payload.get("exclude_subtypes") or []
    if exclude_subtypes and any(perm.has_type(s) for s in exclude_subtypes):
        return False
    # "with mana value 3 or less" (Eliminate). CR 202.3: a permanent's mana
    # value comes from its mana cost — the ingested cmc; a token's is 0.
    if not _comparison_holds(payload.get("mana_value"),
                             int(getattr(perm.effective_card, "cmc", 0) or 0)):
        return False
    # "…each artifact **with mana value less than or equal to the number of rust
    # counters on it**" (Corrosion). Both halves come off the permanent in hand,
    # which is what makes this a filter key rather than an amount: an amount is
    # answered from the resolving effect's context, and the number here is
    # different for every object the sweep looks at.
    at_most_counters = payload.get("mana_value_at_most_counters")
    if at_most_counters is not None:
        from ..named_counters import counters_on

        if int(getattr(perm.effective_card, "cmc", 0) or 0) > counters_on(
            perm, str(at_most_counters)
        ):
            return False
    # "with power 4 or greater" (Turret Ogre's intervening-if): the
    # layer-computed stats, so a pumped 2/2 qualifies while it is pumped.
    if not _comparison_holds(payload.get("power"), perm.effective_power):
        return False
    if not _comparison_holds(payload.get("toughness"), perm.effective_toughness):
        return False
    # "with a +1/+1 counter on it" (Tempered Veteran). Asks the counter
    # *record*, not the P/T bonus — a Giant Growth also writes power_bonus, and
    # reading the bonus as the counter would let it qualify.
    if payload.get("with_plus1_counter") and int(perm.metadata.get("plus_counters", 0)) <= 0:
        return False
    # "an **untapped** creature" (Enthralling Hold). The twin of ``tapped_only``
    # and a separate key for the reason stated on ``to_payload``.
    if payload.get("untapped_only") and perm.tapped:
        return False
    # "target **legendary** creature". CR 205.4: a supertype sits on the type
    # line, and nothing in layers 4-6 computes one here — so the answer is the
    # line the permanent *effectively* has, which folds in a copy (layer 1) and
    # a text change (layer 3). ``perm.card`` would be the printed face and would
    # miss both.
    wanted_supertypes = payload.get("supertypes") or ()
    excluded_supertypes = payload.get("exclude_supertypes") or ()
    if wanted_supertypes or excluded_supertypes:
        # Through ``has_supertype``, which computes layer 4 — not off the
        # effective type line. The line is the *seed*: Arcum's Weathervane makes
        # a Plains snow and unmakes a snow land, so "a snow land" has to be the
        # computed answer for the same reason "a creature" is.
        held = perm.effective_supertypes
        if not all(word in held for word in wanted_supertypes):
            return False
        # "target **nonsnow** land" (Hallowed Ground). The negative of the key
        # above, off the same answer and for the same reason.
        if any(word in held for word in excluded_supertypes):
            return False
    # "…**except for basic lands**" / "…**other than a basic land**" (Eye of
    # Singularity prints both). The *pair* — CR 205.4a's Basic supertype and
    # the land card type — rather than the supertype alone: excluding the
    # supertype is a different sentence, and the only reason it names the same
    # cards today is that no printed non-land carries Basic. Both halves are
    # computed (layer 4) for the reason the block above computes its supertype:
    # Kormus Bell's animated Swamp is still a basic land, and a land whose type
    # an effect rewrote is whatever the layers say it is.
    if payload.get("exclude_basic_lands"):
        if perm.has_type("land") and "basic" in perm.effective_supertypes:
            return False
    # "nontoken permanent" (Lich). CR 111.1: not a card type, so it is its own
    # key rather than an ``exclude_types`` entry.
    # "…any number of **tokens**" (Tetravus). The positive of the restriction
    # below, read off the same record.
    if payload.get("token_only") and not perm.metadata.get("is_token", False):
        return False
    if payload.get("nontoken") and perm.metadata.get("is_token", False):
        return False
    # "named <card>" — through `name_key`, so the parser's rendering of the name
    # and Oracle's spelling of it compare equal. The *effective* card, because a
    # Clone's name is the name it copied (CR 707.2).
    named = payload.get("named")
    if named and name_key(perm.effective_card.name) != name_key(str(named)):
        return False
    # "…with a name originally printed in the <Set> expansion" (Apocalypse
    # Chime, Golgothian Sylex). ``original_printing`` is ``printings[0]`` -- the
    # first set the card appeared in -- and not whichever set happened to load
    # first; that distinction is the whole content of the word "originally".
    #
    # ``effective_card``, because CR 206.3 spells each of these three cards out
    # as a list of **names** ("those names are Abbey Gargoyles; Abbey Matron;
    # …"). So the question is whether *this object's* name is one of them, and a
    # copy's name is the name it copied (CR 707.2, layer 1). Reading the printed
    # face asks where the physical card came from, which is a different question
    # — and the one Golgothian Sylex was answering when it left a Copy Artifact
    # named Su-Chi standing.
    expansion = payload.get("original_expansion")
    if expansion and str(perm.effective_card.original_printing or "").lower() != str(
        expansion
    ).lower():
        return False
    return True


def _comparison_holds(comparison: dict | None, actual: int) -> bool:
    """Whether *actual* satisfies a lowered ``{op, value}`` bound (absent means
    unrestricted)."""
    if not comparison:
        return True
    bound = int(comparison.get("value", 0))
    op = comparison.get("op")
    if op == "le":
        return actual <= bound
    if op == "lt":
        return actual < bound
    if op == "ge":
        return actual >= bound
    if op == "gt":
        return actual > bound
    if op == "eq":
        return actual == bound
    return False


def pick_target_permanent(
    player: PlayerState | None,
    index: int | None,
    *,
    game: Game | None = None,
    permanent_id: object = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Core "honor the chosen target, else fall back" resolution.

    0. If ``permanent_id`` still names a permanent *player* controls and it
       passes ``predicate``, that is the target. This is the stable answer: the
       id was recorded when the target was chosen (CR 601.2c) and means the same
       permanent however the battlefield has been renumbered since.
    0b. If ``permanent_id`` was recorded and now names **no permanent at all**,
       the target is gone (CR 608.2b) and the answer is None. Nothing below is
       consulted — see the asymmetry below for why this one case fizzles.
    1. Otherwise, if ``index`` is a valid index into ``player``'s battlefield and
       that permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).

    Step 0 is *additive* in one direction only, and the asymmetry is the point.
    An id that resolves to a permanent this caller cannot use — it changed
    controller, or stopped being a creature — falls through to the index
    behaviour this function has always had, rather than inventing a fizzle the
    rest of the engine is not yet written for. Those are questions about a
    permanent that still exists, and the engine has no answer for them yet.

    An id that resolves to **nothing** is a different question, and it has an
    answer. The recorded id is the choice (CR 601.2c/602.2b); CR 400.7 makes a
    permanent that has left the battlefield a *new object* if it ever comes
    back, so there is no permanent anywhere that the choice can still mean. The
    index cannot be it either: the slot renumbered when the chosen permanent
    left, so ``battlefield[index]`` is by construction a permanent nobody
    chose, and the fallback scan is one nobody even looked at. This is
    CR 608.2b at the resolver — "the target is gone" — and it is the only shape
    where the fallback can be shown to be wrong rather than merely unsupported.

    So: **an id that was recorded and no longer resolves is a fizzle; an id
    that was never recorded is not.** A targetless activation stamps no id
    (``permanent_ids_at`` maps a missing slot to None) and keeps the fallback —
    which is what ``handlers/destruction.arm_self_action_at_next_end_step``
    asks by hand for Goblin Ski Patrol, and what every caller that resolves a
    "this permanent" pronoun off the context relies on.
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if game is not None and isinstance(permanent_id, int) and player is not None:
        chosen = game.permanent_by_id(permanent_id)
        if chosen is None:
            # CR 608.2b/400.7: a choice was recorded and its object has left.
            # Sandals of Abdallah watched whatever slid into the dead
            # creature's slot and the islandwalk landed there too; War Barge,
            # Runesword, the two Kjeldoran guards, Phantasmal Mount, Goblin
            # Sappers, Whippoorwill and Merieke Ri Berit all read the same
            # resolver. The spells are already refused above the instructions
            # (``legality.illegal_targets_refusal``); an activated ability has
            # no such gate, so the fizzle has to be here.
            return None
        # Scoped to *player* on purpose: the callers pass the battlefield the
        # target was chosen from ("a creature you control", "target artifact an
        # opponent controls"), and widening that here would be a targeting
        # change wearing an identity change's clothes.
        if game.controls(player, chosen) and predicate(chosen):
            return chosen
    explicit = isinstance(index, int)
    if explicit and player is not None and 0 <= index < len(player.battlefield):
        candidate = player.battlefield[index]
        if predicate(candidate):
            return candidate
    if explicit and not fallback_on_invalid_choice:
        return None
    if fallback_players is None:
        fallback_players = (player,) if player is not None else ()
    for scan in fallback_players:
        found = next((p for p in scan.battlefield if predicate(p)), None)
        if found is not None:
            return found
    return None


def block_pair_permanents(game, context) -> list:
    """The creature(s) a block trigger's "that creature" names.

    One reader for both halves, because the two fire sites bind it differently
    and the difference is not the effect's business. On the *becomes blocked*
    half the blocker is the stack item's target. On the *blocks* half the target
    is the blocking creature itself — the fire site needs it there so a
    self-affecting trigger (Ydwen Efreet) can find itself — and the creatures the
    firing is about ride ``blocked_permanent_ids``, by stable id because a
    removal renumbers every later slot (CR 400.7).

    Reading the target on the blocks half is the bug this function exists to
    stop: the card would name *itself*, destroying or recolouring the blocker
    instead of what it blocked, and the trigger would still look as though it
    resolved.
    """
    blocked_ids = (context.trigger_context or {}).get("blocked_permanent_ids") or ()
    if blocked_ids:
        return [
            perm
            for perm in (game.permanent_by_id(pid) for pid in blocked_ids)
            if perm is not None
        ]
    victim = resolve_target_permanent(game, context, fallback_players=())
    return [victim] if victim is not None else []


def roles_still_legal(
    game: Game, context: OracleExecutionContext, payload: dict, *, observer: int
) -> bool:
    """CR 608.2b for a several-**role** spell: is every role still legal?

    Asked once, at resolution, of every role the instruction describes - its
    printed noun phrase through the same ``subject_matches`` the picker
    enumerated with, and its dependency through the same
    ``ROLE_RELATION_TESTS`` the picker narrowed with. Two readers of one table
    rather than a second re-check written by hand, which is the arrangement
    this engine keeps finding on the wrong side of.

    The relation is what makes the re-check necessary at all. A one-target
    spell whose target left is handled by the resolver returning None; a roles
    spell can have both targets present and the *relation between them* gone -
    the Wall left and came back, so CR 400.7 made it a new object with no
    block record, and the creature the caster named is no longer one it
    blocked.
    """
    from ..subject_filters import subject_matches
    from ..targeting import role_dependency, role_relation_holds

    targets = (payload or {}).get("targets") or {}
    roles = list(targets.get("roles") or ())
    resolved: list = []
    for role in roles:
        perm = resolve_role_permanent(game, context, payload, role.get("role"))
        if perm is None or not game.is_on_battlefield(perm):
            return False
        if not subject_matches(
            game, perm, role.get("filter") or {}, observer=observer,
            source=context.source_permanent,
        ):
            return False
        _relation, depends_on = role_dependency(role)
        earlier = next(
            (
                candidate for candidate, entry in zip(resolved, roles)
                if entry.get("role") == depends_on
            ),
            None,
        )
        if not role_relation_holds(role, earlier, perm, game):
            return False
        resolved.append(perm)
    return bool(roles)


#: The context keys a fire site freezes "that player" under, in the order this
#: reads them. Two, because two kinds of event name a player directly: one whose
#: *subject is a seat* ("each player's upkeep", "an opponent draws a card",
#: "a player attacks") and one whose subject is a **damage event**, whose seat
#: the announcement has always called ``defending_player_index``. A firing
#: stamps one or the other, never both, so the order is a lookup and not a
#: precedence.
#:
#: One table because "that player" is one printed phrase. Before this it was
#: three handlers each hardcoding whichever key its own card happened to
#: freeze, which is why the fourth — the targeted destroy, The Abyss and Feline
#: Sovereign — could be written with **neither** and nobody noticed: there was
#: no one place the omission was visible.
_THAT_PLAYER_CONTEXT_KEYS: tuple[str, ...] = (
    "event_subject_player",
    "defending_player_index",
)


def frozen_that_player_seat(game: Game, context: OracleExecutionContext) -> int | None:
    """The seat a printed "**that player**" names, or ``None`` if none was frozen.

    ``subject_matches`` refuses ``controller: "that_player"`` outright and says
    why: it is not a seat any read of the board can make, because it names a
    player the *event* picked. The resolution holding the trigger's context is
    the only place that seat exists (CR 603.10), so this is where the phrase is
    answered — and a caller that gets ``None`` must end the effect rather than
    drop the narrowing, since a dropped seat on a destroy is not a card that
    does less, it is one that reaches the wrong battlefield.
    """
    frozen = context.trigger_context or {}
    for key in _THAT_PLAYER_CONTEXT_KEYS:
        seat = frozen.get(key)
        if isinstance(seat, int) and 0 <= seat < len(game.players):
            return seat
    # A **spell** has no firing event, so there is nothing frozen to read — and
    # the pronoun still has an antecedent: the sentence in front of it. "Cast
    # this spell only during an opponent's turn. Tap target creature **that
    # player** controls." (Delirium.) The timing clause is the only thing in
    # that card naming a player, and the table that owns the phrase is what
    # answers — the same table the picker asks, so what a player was offered and
    # what the resolution acts on cannot disagree.
    from ..cast_restrictions import timing_fixed_seat

    caster = context.caster
    if caster in game.players and context.card is not None:
        return timing_fixed_seat(game, game.players.index(caster), context.card)
    return None

def announced_opponent_seat(game: Game, context: OracleExecutionContext) -> int | None:
    """The seat a printed "**target opponent**" names, or ``None``.

    ``subject_matches`` answers ``controller: "target_opponent"`` from the seat
    the announcement froze and refuses when the caller cannot supply one — a
    caller that cannot say *which* opponent was named must narrow to nothing
    rather than to everyone, which is the difference between Simoon burning the
    board the card names and burning every board at a three-seat table.

    A **spell** supplies it from its picker. A *triggered* ability does not:
    announcing a trigger's targets is a round this engine has not taken
    (ROADMAP, "a triggered ability's targets"), so Corrosion's upkeep trigger
    reaches the same key with nothing frozen.

    One case needs no announcement and is exact rather than permissive: with a
    single opponent the target has exactly one legal candidate, so the choice is
    **forced** (CR 601.2c still makes it; there is nothing to choose between).
    With two or more there is a real choice and nothing has made it, so this
    returns ``None`` and the caller ends the effect — the deferred round showing
    through honestly, rather than a card quietly reaching a battlefield it does
    not name.
    """
    # Deliberately *not* `_THAT_PLAYER_CONTEXT_KEYS`. Those name the seat an
    # event picked — for an upkeep trigger, the player whose upkeep it is, which
    # is the ability's own controller and the exact opposite of the seat this
    # phrase names. Reusing them put Corrosion's rust counters on the caster's
    # own board and matched nothing, which is how the reuse was found.
    caster = context.caster
    if caster not in game.players:
        return None
    observer = game.players.index(caster)
    opponents = [
        seat
        for seat in range(len(game.players))
        if seat != observer and not game.players[seat].lost
    ]
    return opponents[0] if len(opponents) == 1 else None



def resolve_role_permanent(
    game: Game,
    context: OracleExecutionContext,
    payload: dict,
    role: str,
) -> "Permanent | None":
    """The permanent chosen for one **role** of a several-role spell.

    A roles spell (Glyph of Delusion) carries its chosen targets as one
    positional list in *dependency* order, and this is the one place a role's
    name is turned back into its slot - through ``payload_role_slot``, reading
    the same ``targets`` description the picker and the cast gate read. A
    handler that counted slots by hand would be a second convention, and the
    two would disagree the first time a card printed its roles in a different
    order from the one it depends on.

    Strict, and deliberately so: by id, and with no fallback scan. The singular
    resolver's "hit something rather than fizzle" is right for a spell with one
    target and wrong here - a role that no longer resolves is CR 608.2b's
    illegal target, and falling back would point the effect at a permanent the
    caster never chose *for that role*. The index form beside the ids answers a
    caller that has one seat in hand (a test, the AI); the wire always sends
    ids, because the roles of one spell may sit on two battlefields.
    """
    from ..targeting import payload_role_slot

    slot = payload_role_slot(payload, role)
    if slot is None:
        return None
    ids = context.target_permanent_id
    if isinstance(ids, list) and 0 <= slot < len(ids) and isinstance(ids[slot], int):
        return game.permanent_by_id(ids[slot])
    indices = context.target_permanent_index
    if isinstance(indices, list) and 0 <= slot < len(indices):
        return game.permanent_at(game.players.index(context.target), indices[slot])
    return None


def recorded_permanent_ids(context, key) -> tuple[int, ...]:
    """Every permanent id an earlier step of this resolution recorded under *key*.

    **The ``permanents_from`` channel's arity, decided in one place.** That
    payload key names a scratchpad record, and its twenty producers disagreed
    about shape: a reanimation, a sweep and a tap write a *list* of ids, while a
    choose-one prompt and a targeting steal write a bare id. Twenty reader sites
    across eight ``handlers/`` files each made their own assumption, and two of
    them — ``pump.add_counter_to_target`` and ``prevention``'s shield grant —
    had grown a local normalisation whose own comment called itself "the local
    half of a wider question". Nothing was broken, but only because no
    list-producer happened to feed a scalar reader; three sets in a row added
    producers and left the question open, and by Alliances the readers were no
    longer a list anybody could hold in their head while adding one.

    So the channel is **always a sequence**, read here and nowhere else. A
    producer that writes a bare id is read as a sequence of one, which is what
    every iterating reader already assumed and what the two local normalisations
    already did — this is those two, promoted to the channel's definition rather
    than added to as a third.

    An absent record is an empty sequence: a step that recorded nothing is a
    legal outcome (the seat had no creature, the reanimation found no card), not
    an error.
    """
    if key is None:
        return ()
    recorded = (getattr(context, "results", None) or {}).get(str(key))
    if recorded is None:
        return ()
    if isinstance(recorded, int):
        return (recorded,)
    return tuple(
        entry for entry in recorded if isinstance(entry, int)
    )


def one_recorded_permanent_id(context, key) -> int | None:
    """The single permanent id recorded under *key*, or None.

    The half of :func:`recorded_permanent_ids` a sentence about **one** object
    needs — "destroy that creature", "gain control of it", "sacrifice it". Those
    readers used to take the record raw and index nothing, so a list-shaped
    producer would have reached them as an unhashable id and raised; that was
    the failure this channel had been carrying, latent, since Fallen Empires.

    It asserts rather than picking: a reader written for one object that is
    handed two has been fed by a producer it was never paired with, and choosing
    the first would be the effect acting on whichever object happened to be
    recorded first. That is the direction this repo refuses everywhere else.
    """
    recorded = recorded_permanent_ids(context, key)
    if not recorded:
        return None
    assert len(recorded) == 1, (
        f"'permanents_from' record {key!r} holds {len(recorded)} permanents "
        "where this sentence names one"
    )
    return recorded[0]


def resolve_target_permanent(
    game: Game,
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Resolve the permanent a spell or ability acts on — the context-based
    wrapper over :func:`pick_target_permanent` (see it for the semantics).

    Takes the game because identity is a *board* question: the id on the context
    means nothing without something to resolve it against. Every handler already
    receives the game as its first argument, so this reads the same way the
    handler signature does."""
    return pick_target_permanent(
        player if player is not None else context.target,
        _one_choice(context.target_permanent_index),
        game=game,
        permanent_id=_one_choice(context.target_permanent_id),
        predicate=predicate,
        fallback_players=fallback_players,
        fallback_on_invalid_choice=fallback_on_invalid_choice,
    )


def bound_permanent(
    game: Game,
    context: OracleExecutionContext,
    *,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: "Sequence[PlayerState] | None" = None,
) -> Permanent | None:
    """The permanent a sentence's back-reference names — "that creature", "it",
    "its controller" — resolved against the **innermost** binding.

    Two bindings can be in scope at once, and the printed pronoun cannot say
    which. A spell or ability binds the target it chose (CR 601.2c), and a
    ``for_each`` running over permanents binds the object of the iteration it is
    in the middle of. Inside a loop the loop wins, because that is what the loop
    is: "Choose X target attacking creatures. **For each of those creatures**,
    its controller may pay {1} … destroy **that creature** at end of combat"
    (Winter's Chill) names a different creature each time round, and the
    resolution's own target list is *all* of them.

    Outside a loop this is exactly :func:`resolve_target_permanent`, which is
    why it is a wrapper rather than a second reader: every caller that already
    resolved a target keeps doing so, and the only thing that changes is that
    the loop's object is asked about first.

    ``iteration_target`` is not always a permanent — a loop may walk cards in a
    hand (Sylvan Library) — so the id is what qualifies it, never the mere
    presence of an item.
    """
    iterated = context.iteration_target
    if getattr(iterated, "permanent_id", None) is not None:
        if predicate is None or predicate(iterated):
            return iterated
        return None
    return resolve_target_permanent(
        game, context, predicate=predicate, fallback_on_invalid_choice=False,
        fallback_players=fallback_players,
    )


def _one_choice(chosen: object) -> object:
    """The first entry of a multi-target choice, or *chosen* unchanged.

    A single-target handler must never be handed a list: ``pick_target_permanent``
    would fail ``isinstance(index, int)``, fall through to its scan, and hit the
    first creature on the battlefield instead of a chosen one. Reading the first
    entry keeps a handler that was only ever written for one target pointed at a
    target the player actually named — the lowering is what decides whether a
    several-target line reaches such a handler at all, and it refuses.
    """
    if isinstance(chosen, list):
        return chosen[0] if chosen else None
    return chosen


def resolve_target_permanents(
    game: Game,
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
) -> list[Permanent]:
    """Every permanent a several-target spell or ability named (CR 115.1c).

    The plural of :func:`resolve_target_permanent`, and deliberately *not* built
    on it: the singular one falls back to scanning the battlefield when a chosen
    target no longer resolves, which is right for one target ("hit something
    rather than fizzle") and wrong for several — a fallback per slot would turn
    "up to two target creatures" into two counters on the same creature the
    moment one target died.

    So each slot is resolved strictly, by id first and index second, and a slot
    that no longer answers is simply dropped: CR 608.2b says an illegal target is
    not affected while the rest of the effect still happens. Duplicates are
    dropped by identity for the same reason — two slots that decayed onto one
    permanent would double an effect the player only chose once.

    Returns [] when nothing was chosen, which is a legal outcome of "up to N".
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    owner = player if player is not None else context.target
    indices = _as_slots(context.target_permanent_index)
    ids = _as_slots(context.target_permanent_id)
    # Positional pairing: `permanent_ids_at` keeps a slot that did not resolve as
    # None rather than dropping it, so the two lists stay the same length and
    # index k means the same choice in both.
    found: list[Permanent] = []
    for slot in range(max(len(indices), len(ids))):
        permanent_id = ids[slot] if slot < len(ids) else None
        index = indices[slot] if slot < len(indices) else None
        chosen = None
        if game is not None and isinstance(permanent_id, int):
            candidate = game.permanent_by_id(permanent_id)
            # No seat check on this branch. An id *is* the identity (CR 400.7),
            # so asking which battlefield it sits on is the index model showing
            # through — and it is wrong for a description whose slots are on two
            # boards ("target creature you control … another target creature").
            # What restricts a slot is its own filter, which the caller's
            # predicate carries; the index fallback below keeps the seat because
            # a bare index means nothing without one.
            if candidate is not None and predicate(candidate):
                chosen = candidate
        if chosen is None and isinstance(index, int) and owner is not None:
            # Through the seam, not a raw subscript: the id above is the stable
            # answer and this is only the fallback for a choice made before ids
            # existed on the wire, so it has no business opening a second way to
            # read a battlefield.
            candidate = game.permanent_at(owner, index)
            if candidate is not None and predicate(candidate):
                chosen = candidate
        if chosen is not None and not any(chosen is seen for seen in found):
            found.append(chosen)
    return found


def resolve_target_slots(
    game: Game,
    context: OracleExecutionContext,
    count: int,
    *,
    player: PlayerState | None = None,
) -> list[Permanent | None]:
    """The permanent each of *count* chosen slots names, **positionally**.

    The difference from :func:`resolve_target_permanents` is the whole reason
    this exists: that one *compacts*. It drops a slot that no longer answers and
    dedupes by identity, so a caller reading ``chosen[0]`` and ``chosen[1]``
    reads the wrong slot the moment the first target has left — slot 1's
    permanent slides into position 0. That is safe only where the two slots are
    disjointly filtered (Primal Might's "you control" / "you don't control"
    reject the impostor) and unsafe wherever they are not: Rookie Mistake's slots
    are both a bare "target creature", so a decayed first slot would hand the
    *second* creature the first slot's +0/+2.

    So this pads: slot k is index k, or None. Nothing is deduped here either —
    "another" is a *printed* restriction, and a caller that has one enforces it
    where it can say which of the two slots to drop (the later one, CR 608.2b).
    No fallback scan, for the reason `resolve_target_permanents` documents.
    """
    ids = _as_slots(context.target_permanent_id)
    indices = _as_slots(context.target_permanent_index)
    owner = player if player is not None else context.target
    found: list[Permanent | None] = []
    for slot in range(count):
        permanent_id = ids[slot] if slot < len(ids) else None
        chosen = None
        if isinstance(permanent_id, int):
            # No seat check: an id *is* the identity (CR 400.7), and a pair of
            # slots may sit on two battlefields.
            chosen = game.permanent_by_id(permanent_id)
        if chosen is None:
            index = indices[slot] if slot < len(indices) else None
            if isinstance(index, int) and owner is not None:
                chosen = game.permanent_at(owner, index)
        found.append(chosen)
    return found


def _as_slots(chosen: object) -> list:
    """A chosen-target field as a list of slots, whatever shape it arrived in."""
    if isinstance(chosen, list):
        return list(chosen)
    return [] if chosen is None else [chosen]


def seats_matching_deed(game, context, seats, deed) -> list:
    """*seats*, narrowed to the ones a ``who <did …>`` clause names.

    "…each player **who tapped a land for mana this turn** sacrifices a land of
    their choice. … deals 2 damage to each player **who sacrificed a Plains
    this way**." (Desolation.) One reader for both sentences, so the two halves
    of that card cannot disagree about which seats "who" introduced — and the
    same reader the lowering's ``player_deed_payload`` is the parse-side half
    of.

    ``None`` is no clause printed, which leaves the list exactly as it was.

    A kind this cannot answer returns **no seats** rather than all of them. It
    is not reachable — the lowering refuses an unknown kind, so nothing
    compiles one — but a narrowing that fails open is a sentence acting on
    every player at the table, and the direction to fail in is the one where a
    bug does nothing rather than everything.
    """
    if not deed:
        return list(seats)
    kind = deed.get("kind")
    if kind == "tapped_land_for_mana_this_turn":
        # The seat's own per-turn record, written at the one tap-for-mana seam
        # (``mixins/turn_management.tap_land_for_mana``) and cleared with the
        # rest of the turn histories. Never a read of the board: a land that
        # untapped, left, or was tapped again for something that is not mana
        # would answer the wrong question, and CR 106.11's mana is long gone by
        # the end step this asks in.
        return [
            seat for seat in seats
            if getattr(game.players[seat], "tapped_land_for_mana_this_turn", False)
        ]
    if kind == "sacrificed_this_way":
        # The seat-keyed record an earlier step of this same resolution wrote
        # (``SACRIFICED_CARDS_BY_SEAT``). Never a read of a graveyard: the pile
        # holds whatever else has gone there, and the words say "this way".
        # Compared against each card's *printed* characteristics, because a card
        # in a graveyard has no computed ones (CR 613.1) — the same restriction
        # ``card_only_filter`` puts on the lowering that built this payload.
        by_seat = (context.results or {}).get(SACRIFICED_CARDS_BY_SEAT) or {}
        described = deed.get("filter") or {}
        return [
            seat for seat in seats
            if any(
                _card_matches_filter(card, described)
                for card in (by_seat.get(seat) or ())
            )
        ]
    return []
