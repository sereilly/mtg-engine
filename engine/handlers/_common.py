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
from ..oracle_types import BLOCK_PAIR_SUBJECT, SUBJECT_FROM_TRIGGER
from ..models import Permanent, PlayerState
from ..search_filters import name_key


def attached_host(game: "Game", source: "Permanent | None") -> "Permanent | None":
    """The permanent *source* is attached to — or, when *source* has already
    left mid-resolution, the one it was last attached to (CR 603.10 last-known
    information) — provided that host is still on the battlefield.

    Cocoon is why the fallback exists: "…sacrifice it, put a +1/+1 counter on
    enchanted creature, and that creature gains flying" removes the Aura in
    the very resolution whose later steps name the enchanted creature, and
    ``detach_aura`` has already cleared the live record by then.
    """
    if source is None:
        return None
    host = source.metadata.get("attached_to") or source.metadata.get("last_attached_to")
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
        if times is None:
            raise ValueError(f"unreadable amount payload {raw!r}")
        return int(times) * max(0, x_value or 0)
    return max(0, x_value or 0) if raw == "x" else int(raw)




def count_from_payload(
    game: "Game", context: "OracleExecutionContext", spec: dict,
    instruction: "OracleInstruction | None" = None,
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
    characteristic = spec.get("object_characteristic")
    if isinstance(characteristic, dict):
        return _characteristic_of_object(game, context, characteristic, instruction)
    scope = spec.get("owner", "you")
    if scope == "you":
        owner = context.caster
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
    return evaluate_count(
        game, owner, spec,
        exclude=context.source_permanent, source=context.source_permanent,
    )


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
    from ..damage_ledger import damage_dealt_to_permanent, source_name_of

    base = max(0, int(query.get("base", 0) or 0))
    source = context.source_permanent
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
    multiplier = int(spec.get("multiplier", 1) or 1)
    total = total * multiplier
    rounding = spec.get("half")
    if rounding is None:
        return total
    return -(-total // 2) if rounding == "up" else total // 2


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
    # "the number of Auras **attached to it**" (Rabid Wombat). Not a scan of a
    # zone: what is attached to a permanent is a record kept on that permanent,
    # which is also why the owner scope above does not apply — an opponent's
    # Aura on your creature is attached to your creature and the sentence says
    # nothing about who controls it. A spec carrying the key with no source to
    # resolve it counts nothing, and the lowering refuses every referent but
    # this one so that cannot arrive from a card.
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
        seat = game.players.index(owner)
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
        matched = [
            perm for perm in game.controlled_by(seat)
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
    cards = getattr(owner, zone, None)
    if cards is None:
        return 0
    matched_cards = [card for card in cards if _card_matches_filter(card, filt)]
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


def _card_matches_filter(card, filt: dict) -> bool:
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
    if wanted_supertypes:
        held = printed_supertypes(card.type_line)
        if not all(word in held for word in wanted_supertypes):
            return False
    # "creature cards **with mana value 3 or less**" (Idol of Endurance). Mana
    # value is one of the few characteristics a card has *everywhere* — CR 202.3
    # computes it from the printed mana cost, so unlike power or a keyword it
    # needs no battlefield object to be asked of. Same bound reader the permanent
    # matcher uses, so "3 or less" means one thing in both zones.
    if not _comparison_holds(filt.get("mana_value"), int(getattr(card, "cmc", 0) or 0)):
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

    return game._mark_damage_on_permanent(perm, amount, source=source, then=finish, asks=asks)


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
    if card_types and card.primary_type not in card_types:
        return False
    color = spec.get("graveyard_color_filter")
    if color and color not in card.colors:
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
    if wanted_supertypes:
        held = printed_supertypes(perm.effective_card.type_line)
        if not all(word in held for word in wanted_supertypes):
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
    1. Otherwise, if ``index`` is a valid index into ``player``'s battlefield and
       that permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).

    Step 0 is *additive*: when the id no longer resolves — the target died, or
    changed controller — this falls through to exactly the index behaviour it
    has always had, rather than inventing a fizzle the rest of the engine is not
    yet written for. So the id can only turn a wrong answer into a right one.
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if game is not None and isinstance(permanent_id, int) and player is not None:
        chosen = game.permanent_by_id(permanent_id)
        # Scoped to *player* on purpose: the callers pass the battlefield the
        # target was chosen from ("a creature you control", "target artifact an
        # opponent controls"), and widening that here would be a targeting
        # change wearing an identity change's clothes.
        if chosen is not None and game.controls(player, chosen) and predicate(chosen):
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
        if not role_relation_holds(role, earlier, perm):
            return False
        resolved.append(perm)
    return bool(roles)


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
