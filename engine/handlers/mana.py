from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler
from ._common import count_from_payload, resolve_amount

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("drain_target_lands_mana")
def drain_target_lands_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    # Tap each of target's untapped lands and collect the mana they would produce
    mana_gained: dict[str, int] = {}
    for perm in game.controlled_by(target):
        if perm.card.primary_type != "land" or perm.tapped:
            continue
        game.become_tapped(perm)
        if perm.card.produced_mana:
            sym = perm.card.produced_mana[0].upper()
        else:
            symbols = perm.basic_land_mana
            sym = symbols[0] if symbols else "C"
        mana_gained[sym] = mana_gained.get(sym, 0) + 1
    # Drain any existing unspent mana from target's pool too
    for sym in ("W", "U", "B", "R", "G", "C"):
        pool_amount = target.mana_pool.get(sym, 0)
        if pool_amount > 0:
            mana_gained[sym] = mana_gained.get(sym, 0) + pool_amount
            target.mana_pool[sym] = 0
    # Add all drained mana to caster
    for sym, amount_gained in mana_gained.items():
        caster.mana_pool[sym] = caster.mana_pool.get(sym, 0) + amount_gained
    total = sum(mana_gained.values())
    game.log.append(f"{card.name} drained {total} mana from {target.name}")
    return True, "resolved"


_COLOR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _resolved_spend_only(context, spend_only):
    """*spend_only* with the object it names filled in, or unchanged.

    "Spend this mana only to cast **the last card exiled with this artifact**"
    (Ice Cauldron) restricts the mana to one card rather than to a class of
    them, and a restricted bucket is keyed by a string — so the card is named in
    the key, and the naming has to happen *here*, when the mana is made: that is
    the only moment anything knows which card the words point at.

    The record is the linked exile (CR 610.3), read off the permanent the phrase
    names. A source with nothing exiled leaves the key parameterless, which
    ``restriction_admits`` refuses outright — mana nobody can spend, which is
    the honest reading of a Cauldron that noted mana and exiled nothing.
    """
    from ..restricted_mana import PARAMETER

    if spend_only != "last_card_exiled_with_source":
        return spend_only
    from ..linked_exile import linked_entries

    entries = linked_entries(context.source_permanent)
    last = entries[-1]["card"] if entries else None
    return f"{spend_only}{PARAMETER}{getattr(last, 'name', '')}"


def _mana_bucket(caster, spend_only) -> dict:
    """Where a produced mana lands: the pool, or a restricted bucket.

    "Spend this mana only to pay cumulative upkeep costs." (Adarkar Unicorn.)
    The restricted buckets are ``engine/restricted_mana.py``'s, merged into a
    payment only by the purposes the clause admits, and emptied at the same step
    boundary the pool is.

    One function because four branches of ``add_mana_from_text`` now ask the
    question. The ``pips_choice`` branch used to answer it by not asking — it
    wrote straight into ``mana_pool`` while its lowering was already carrying
    ``spend_only`` — so a printed "Add {B} or {R}. Spend this mana only to …"
    would have made unrestricted mana. Nothing in the pool prints that pair
    today, which is exactly why the miss was invisible.
    """
    if spend_only:
        return caster.restricted_mana.setdefault(str(spend_only), {})
    return caster.mana_pool


def _restriction_suffix(spend_only) -> str:
    """The log's note that the mana just made is restricted, or "" when not."""
    return f" (spendable only on {spend_only})" if spend_only else ""


def _pick_mana_alternative(alternatives, context) -> tuple:
    """Which written-out quantity of a printed "or" the seat takes.

    ``mana_alternative`` on the resolution's choices names an index when
    something asked; with nothing asked the **largest** alternative is taken,
    ties going to the one printed first.

    That default is a real choice rather than a guess. The alternatives of an
    "Add A or B" carry no cost between them and land in the same pool under the
    same restriction, and this engine has no mana burn (CR 500.4 empties an
    unspent pool with no penalty), so more mana of the same kind is never worse
    than less — Adarkar Unicorn's {C}{U} strictly contains its {U}. Taking the
    first printed instead, which is what the single-symbol branch above does,
    would hand a non-interactive seat the smaller half of every such card.
    """
    chosen = (context.choices or {}).get("mana_alternative")
    if isinstance(chosen, int) and 0 <= chosen < len(alternatives):
        return tuple(alternatives[chosen])
    best = max(
        range(len(alternatives)),
        key=lambda index: sum(int(count) for _symbol, count in alternatives[index]),
    )
    return tuple(alternatives[best])


def _split_mana_combination(
    symbols: tuple[str, ...], total: int, chosen: str | None, context
) -> dict:
    """How *total* mana divides among the symbols an "any combination" lists.

    ``mana_combination`` on the resolution's choices is an explicit split, taken
    when it names only listed symbols and adds up to exactly *total* — anything
    else is a split that was not offered, and is discarded rather than
    part-applied.

    With nothing named, every unit takes the seat's chosen colour when that
    colour is one the clause lists (the ``color`` channel a dual land's choice
    already rides), and otherwise the first printed symbol. Both defaults are
    choices the card allows: "any combination" includes every unit being the
    same symbol. What they cannot do is *mix*, which is a narrowing of the
    player's options rather than a widening of the card's — the safe direction,
    and the reason this is a default and not a prompt.
    """
    if total <= 0:
        return {}
    named = (context.choices or {}).get("mana_combination")
    if isinstance(named, dict):
        try:
            wanted = {symbol: int(amount) for symbol, amount in named.items()}
        except (TypeError, ValueError):
            wanted = {}
        split = {
            symbol: amount
            for symbol, amount in wanted.items()
            if symbol in symbols and amount >= 0
        }
        # Accepted whole or not at all: the same keys, no negative unit, and the
        # printed total exactly. A split naming a symbol the clause does not
        # list, or adding up to something else, is a split that was never
        # offered — part-applying it would make mana out of a malformed answer.
        if split == wanted and sum(split.values()) == total:
            return split
    return {chosen if chosen in symbols else symbols[0]: total}


@effect_handler("sacrifice_creature_for_mana")
def sacrifice_creature_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The mana an additional cost's sacrifice buys (Sacrifice, Metamorphosis).

    **The sacrifice is not performed here.** It is the spell's printed
    additional cost, so CR 601.2b/601.2h pay it while the spell is being cast —
    ``engine/cast_costs.py`` reads it and ``queue_from_hand`` performs it, the
    same as for the two cards that print the identical sentence and buy nothing
    with it. What arrives here is what the cost ate, on the stack item, and it
    is off the battlefield by now: its mana value is last-known information
    (CR 608.2h), which the ``Permanent`` object still carries.

    This handler used to sacrifice a creature of its own at resolution. With the
    cost also being paid, that was two creatures for one spell — the reason the
    two halves had to separate in the same round the cost became general.

    Two cards reach it and they differ in three ways, so all three are payload:

    ``color``       the mana symbol produced, or None when the card says "of any
                    one color" and the caster picks (the pick rides
                    ``context.choices["new_color"]``, like the laces' colour).
    ``bonus``       added to the sacrificed creature's mana value — Sacrifice
                    adds 0, Metamorphosis's "1 plus …" adds 1.
    ``spend_only``  the spell type the mana is locked to, or None for unrestricted
                    pool mana. Metamorphosis's "Spend this mana only to cast
                    creature spells" is ``"creature"``.

    All three used to be decided by ``in`` probes against the resolving card's
    own oracle text inside this handler, which made the card's *name* the only
    thing keeping Metamorphosis off Sacrifice's effect — a second parser living
    in a handler, and the exact shape ``engine/parsing/`` was deleted to remove.
    """
    caster = context.caster
    sacrificed_perm = context.choices.get("sacrificed_for_cost")
    if sacrificed_perm is None:
        # The spell reached resolution without its cost having been paid, which
        # the casting gate makes impossible from `queue_from_hand` — a direct
        # handler invocation (a test, a script) is the remaining way in.
        game.log.append(f"{caster.name} sacrificed no creature for {context.card.name}")
        return True, "resolved"
    sacrificed = sacrificed_perm.card
    amount = int(sacrificed.cmc) + int(instruction.payload.get("bonus", 0))
    payload_color = instruction.payload.get("color")
    if payload_color:
        symbol = str(payload_color)
    else:
        # "of any one color": the caster's pick, defaulting to the card's own
        # colour when no choice reached the stack (AI seats, headless scripts).
        symbol = game._normalize_mana_color(context.choices.get("new_color")) or "G"
    color_word = _COLOR_WORDS.get(symbol, symbol)
    spend_only = instruction.payload.get("spend_only")
    if spend_only == "creature":
        # The mana goes into the creature-spells-only bucket, merged into
        # payments by _pay_mana_cost only for creature spells.
        caster.creature_only_mana[symbol] = caster.creature_only_mana.get(symbol, 0) + amount
        game.log.append(
            f"{caster.name} sacrificed {sacrificed.name} for {amount} {color_word} mana "
            "(spendable only on creature spells)"
        )
    else:
        caster.mana_pool[symbol] = caster.mana_pool.get(symbol, 0) + amount
        game.log.append(f"{caster.name} sacrificed {sacrificed.name} for {amount} {color_word} mana")
    return True, "resolved"


@effect_handler("sacrifice_self_for_mana")
def sacrifice_self_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Black Lotus: "{T}, Sacrifice this artifact: Add three mana of any one
    color." The sacrifice is a *cost*, paid by queue_permanent_ability's
    ``sacrifice_self`` branch before this runs — this only adds the mana."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    caster.mana_pool[str(instruction.payload.get("color", "G"))] += resolve_amount(
        instruction.payload.get("amount", 0), context.x_value
    )
    # Belt and braces for callers that reach this handler without going through
    # the cost path (direct handler invocation in tests/scripts). Still on the
    # battlefield means the cost path did not run, and the seam's own None
    # return is the "already paid" case.
    game.sacrifice_permanent(source_permanent)
    game.log.append(f"{card.name} sacrificed for mana")
    return True, "resolved"


@effect_handler("add_mana_from_text")
def add_mana_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Add mana to the controller's pool.

    Prefers a structured ``pips`` payload — ``(("G", 1), ("C", 2))`` — over
    re-reading the clause text. The text path remains for instructions the
    legacy rules produce, which carry the clause rather than what it means; it
    is one of the engine's inline oracle-text probes and goes away with them.
    """
    caster = context.caster
    card = context.card

    # "Add {B} or {R}" — one of the listed symbols, the player's choice
    # (``pips_choice``, its own key so nothing reads it as add-everything).
    # The chosen colour arrives exactly as the any-colour shape's does —
    # injected as ``color`` by the activation path — and is honoured only when
    # it names one of the printed alternatives; otherwise the first printed
    # symbol is the default, so a non-interactive caller still gets one mana
    # and never two.
    # "…add an amount of {C} equal to that spell's mana value." (Mana Drain.)
    # The count is not on the payload: it is whatever the effect that created
    # this delayed ability recorded, frozen into the trigger's context when the
    # ability was created (CR 608.2h). Read before the printed shapes below,
    # which all carry their own number.
    count_key = instruction.payload.get("count_from_trigger")
    if count_key:
        symbol = str(instruction.payload.get("symbol", "C"))
        count = max(0, int((context.trigger_context or {}).get(count_key, 0)))
        if count:
            caster.mana_pool[symbol] = caster.mana_pool.get(symbol, 0) + count
        game.log.append(
            f"{card.name} produced {'{' + symbol + '}' * count}"
            if count else f"{card.name} produced no mana"
        )
        return True, "resolved"

    # "…add an amount of {C} equal to **that creature's** mana value." (Energy
    # Tap.) The creature is the one an earlier step of this same effect
    # recorded — by id, because a permanent may have left in between (CR 400.7)
    # and a slot would by then address whichever creature slid into it. Still
    # on the battlefield, so the number is read now rather than remembered;
    # gone, and the clause adds nothing, which is what "that creature" with no
    # creature means.
    mana_value_key = instruction.payload.get("count_from_mana_value_of")
    if mana_value_key:
        symbol = str(instruction.payload.get("symbol", "C"))
        recorded = (context.results or {}).get(str(mana_value_key)) or ()
        count = 0
        for permanent_id in recorded:
            permanent = game.permanent_by_id(permanent_id)
            if permanent is not None:
                # CR 202.3b — mana value is computed from the mana cost, and
                # `effective_card` is what the permanent's cost *is* after
                # layer 1 (a copy carries the copied cost, not its own).
                count += max(0, int(permanent.effective_card.cmc or 0))
        if count:
            caster.mana_pool[symbol] = caster.mana_pool.get(symbol, 0) + count
        game.log.append(
            f"{card.name} produced {'{' + symbol + '}' * count}"
            if count else f"{card.name} produced no mana"
        )
        return True, "resolved"

    # "Add one mana of this artifact's last noted type." (Jeweled Amulet.)
    # "Add this artifact's last noted type and amount of mana." (Ice Cauldron.)
    # The record an earlier activation of this same permanent wrote, read off
    # the source — a permanent with nothing noted adds nothing at all, which is
    # what the card says: the counter it removes was put there by the very
    # activation that did the noting.
    from_noted = instruction.payload.get("from_noted")
    if from_noted:
        from ..noted_mana import noted_mana

        record = noted_mana(context.source_permanent)
        spend_only = _resolved_spend_only(
            context, instruction.payload.get("spend_only")
        )
        bucket = _mana_bucket(caster, spend_only)
        added = []
        for symbol, count in sorted(record.items()):
            # "…last noted **type**" keeps only the kind: one mana of it,
            # however much was spent. "…**type and amount**" keeps both.
            produced = int(count) if from_noted == "type_and_amount" else 1
            bucket[symbol] = bucket.get(symbol, 0) + produced
            added.append(f"{{{symbol}}}" * produced)
        game.log.append(
            f"{card.name} produced {''.join(added) or 'no mana'}"
            f"{_restriction_suffix(spend_only)}"
        )
        return True, "resolved"

    pips_choice = instruction.payload.get("pips_choice")
    if pips_choice:
        alternatives = [symbol for symbol, _count in pips_choice]
        chosen = game._normalize_mana_color(
            instruction.payload.get("color")
            or (context.choices or {}).get("new_color")
        )
        if chosen not in alternatives:
            chosen = alternatives[0]
        count = next(int(c) for s, c in pips_choice if s == chosen)
        spend_only = instruction.payload.get("spend_only")
        bucket = _mana_bucket(caster, spend_only)
        bucket[chosen] = bucket.get(chosen, 0) + count
        game.log.append(
            f"{card.name} produced {'{' + chosen + '}' * count}"
            f"{_restriction_suffix(spend_only)}"
        )
        return True, "resolved"

    # "Add {U} or {C}{U}." (Adarkar Unicorn.) A choice between *written-out
    # quantities* rather than between colours, which ``pips_choice`` above
    # cannot say — it holds one ``(symbol, count)`` pair per alternative, so
    # "{C} and {U} together" has nowhere to go. Each alternative here is its own
    # pip list and the seat takes one entire.
    alternatives_payload = instruction.payload.get("pips_alternatives")
    if alternatives_payload:
        picked = _pick_mana_alternative(alternatives_payload, context)
        spend_only = instruction.payload.get("spend_only")
        bucket = _mana_bucket(caster, spend_only)
        added: list[str] = []
        for symbol, count in picked:
            bucket[symbol] = bucket.get(symbol, 0) + int(count)
            added.append(f"{{{symbol}}}" * int(count))
        game.log.append(
            f"{card.name} produced {''.join(added)}{_restriction_suffix(spend_only)}"
        )
        return True, "resolved"

    # "Add three mana in any combination of {R} and/or {G}." (Orcish Lumberjack,
    # Burnt Offering.) A fixed *number* of mana, each unit's symbol chosen from
    # the printed list — so the count and the list are payload and the split is
    # the seat's.
    combination = instruction.payload.get("combination")
    if combination:
        total = resolve_amount(
            instruction.payload.get("combination_count", 0), context.x_value
        )
        split = _split_mana_combination(
            tuple(combination),
            total,
            game._normalize_mana_color(
                instruction.payload.get("color")
                or (context.choices or {}).get("new_color")
            ),
            context,
        )
        spend_only = instruction.payload.get("spend_only")
        bucket = _mana_bucket(caster, spend_only)
        added = []
        for symbol in combination:
            produced = int(split.get(symbol, 0))
            if produced:
                bucket[symbol] = bucket.get(symbol, 0) + produced
                added.append(f"{{{symbol}}}" * produced)
        game.log.append(
            f"{card.name} produced {''.join(added) or 'no mana'}"
            f"{_restriction_suffix(spend_only)}"
        )
        return True, "resolved"

    pips = instruction.payload.get("pips")
    if pips:
        # "Add {G} **for each** …" (Leafkin Avenger): the whole clause is
        # multiplied, so the count is applied to every pip rather than to one.
        # Zero matching permanents adds no mana, which is what "for each" of an
        # empty set means.
        per_each = instruction.payload.get("per_each")
        multiplier = (
            count_from_payload(game, context, per_each) if per_each is not None else 1
        )
        # "…add an additional {B} **for each charge counter removed this way**"
        # (the five Mana Batteries). The multiplier is the ability's own cost
        # payment, not a board count: the counters came off as the cost was paid
        # (CR 601.2h) and are gone by now, so the number is the one the
        # activation path recorded. Counting what is still on the artifact would
        # be the exact complement of what the card says.
        #
        # Zero is a real answer — "any number" includes none — and adds only the
        # flat pips the sentence in front of this one already produced.
        if instruction.payload.get("per_each_counter_removed") is not None:
            multiplier = max(0, int((context.choices or {}).get(
                "counters_removed_for_cost", 0
            )))
        # "…for each **storage counter on this land**" (City of Shadows). Read
        # off the source now, not off a payment: these counters are still there,
        # and a land with none produces nothing at all — which is the card, and
        # is why zero is a resolution rather than a miss.
        on_source = instruction.payload.get("per_each_counter_on_source")
        if on_source is not None:
            from ..named_counters import counters_on

            source = context.source_permanent
            multiplier = (
                counters_on(source, str(on_source)) if source is not None else 0
            )
        # "Spend this mana only to cast an instant or sorcery spell." (Vodalian
        # Arcanist.) The mana goes into its own bucket rather than the pool;
        # `_pay_mana_cost` merges a bucket in only for a spell the restriction
        # admits, and every bucket empties at the same step boundary the pool
        # does.
        spend_only = instruction.payload.get("spend_only")
        bucket = (
            caster.restricted_mana.setdefault(str(spend_only), {})
            if spend_only else caster.mana_pool
        )
        added: list[str] = []
        for symbol, count in pips:
            if symbol not in caster.mana_pool:
                continue
            produced = int(count) * multiplier
            bucket[symbol] = bucket.get(symbol, 0) + produced
            added.append(f"{{{symbol}}}" * produced)
        suffix = f" (spendable only on {spend_only} spells)" if spend_only else ""
        game.log.append(f"{card.name} produced {''.join(added)}{suffix}")
        return True, "resolved"

    # "Add N mana of any one color" (Sanctum of Fruitful Harvest, Traitorous
    # Greed). One symbol, N times — "any **one** color" is a single choice for
    # the whole clause, which is why the count multiplies a symbol rather than
    # asking again per mana.
    any_count = instruction.payload.get("any_color_count")
    if any_count is not None:
        # "…where X is the number of Shrines you control" defines X through the
        # one evaluator every computed amount shares, so the same printed clause
        # means the same number here as it does on a pump or a CDA.
        x_value = context.x_value
        x_count = instruction.payload.get("x_from_count")
        if x_count is not None:
            x_value = count_from_payload(game, context, x_count)
        amount = resolve_amount(any_count, x_value)
        symbol = game._normalize_mana_color(
            instruction.payload.get("color")
            or (context.choices or {}).get("new_color")
        ) or "G"
        # "…of any color **that a land an opponent controls could produce**"
        # (Fellwar Stone). The choice is narrowed to that set, re-checked here
        # rather than trusted from the picker (idiom 9) - and with the set empty
        # the ability produces nothing at all, which is the card: an opponent
        # with no lands offers no colour to copy.
        narrowed_to = instruction.payload.get("any_color_from")
        if narrowed_to is not None:
            available = _colors_opponents_lands_produce(game, caster)
            if not available:
                game.log.append(
                    f"{card.name}: no land an opponent controls produces colored mana"
                )
                return True, "resolved"
            if symbol not in available:
                symbol = sorted(available)[0]
        if amount > 0:
            caster.mana_pool[symbol] += amount
        game.log.append(f"{card.name} produced {amount} {symbol} mana")
        return True, "resolved"

    game._add_mana_from_text(
        caster,
        str(instruction.payload.get("oracle_text", card.oracle_text)),
        preferred_color=str(instruction.payload.get("color", "")) or None,
    )
    game.log.append(f"{card.name} produced mana")
    return True, "resolved"


@effect_handler("channel_life_for_mana")
def channel_life_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster.channel_active_until_eot = True
    game.log.append(f"{caster.name} may pay life for {{C}} mana until end of turn (Channel)")
    return True, "resolved"


@effect_handler("swap_controller_land_mana_until_eot")
def swap_controller_land_mana_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Deep Water: "Until end of turn, if you tap a land you control for mana,
    it produces {U} instead of any other type." Chaos Moon's even branch: "…if a
    player taps a Mountain for mana, that Mountain produces colorless mana
    instead of any other type."

    The record goes on the **seat**, not on the lands, which is the whole of
    what separates this from ``produce_mana_instead`` above: the class it names
    includes lands that have not entered yet, and which of them this seat
    controls is answered when each is tapped. See
    ``engine/land_mana_swaps.py`` for why the per-permanent record cannot carry
    either half.

    ``seats: "each"`` is the printed "a player" rather than "you", and it arms
    one record per seat. That is not a convenience: ``swapped_symbol`` asks the
    **land's own controller** for their records — CR 109.5's seat, and the only
    seat a "you" sentence could mean — so a single record on this ability's
    controller would leave every opponent's Mountain producing red on a board
    the card says is colourless.
    """
    from ..land_mana_swaps import LandManaSwap, add_swap

    caster = context.caster
    seats = (
        list(game.players) if instruction.payload.get("seats") == "each" else [caster]
    )
    for player in seats:
        add_swap(
            player,
            LandManaSwap(
                produced=str(instruction.payload.get("produced", "")),
                lands=dict(instruction.payload.get("lands") or {}),
                source_name=getattr(context.card, "name", None),
            ),
        )
    whose = "every player's" if len(seats) > 1 else f"{caster.name}'s"
    game.log.append(
        f"{getattr(context.card, 'name', 'an effect')}: {whose} lands "
        f"produce {{{instruction.payload.get('produced', '')}}} this turn"
    )
    return True, "resolved"


@effect_handler("produce_mana_instead")
def produce_mana_instead(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If target Plains is tapped for mana, it produces colorless mana instead
    of white mana." (Quarum Trench Gnomes.)

    A CR 611.2 continuous effect with no duration — "this effect lasts
    indefinitely" — so it is recorded on the land rather than applied here. The
    record is read by ``Permanent.effective_produced_mana``, the one place the
    engine asks what a land makes, which is why nothing else has to change: the
    tap path, the payment planner, the AI's land read and the web payload all
    go through that property already.

    It dies with the permanent, which is right without any sweep: CR 400.7
    makes a land that leaves and returns a new object, and the effect named the
    old one.
    """
    from ._common import resolve_target_permanent, permanent_matches_filter

    # The filter the lowering recorded for the picker, read here too — the
    # ability's legality gate asks the same question of the same dict, so a
    # land offered at activation is one this resolution accepts.
    filt = (instruction.payload.get("targets") or {}).get("filter") or {}
    replaced = str(instruction.payload.get("replaced", ""))
    produced = str(instruction.payload.get("produced", ""))

    def _eligible(perm) -> bool:
        return permanent_matches_filter(perm, filt)

    target = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_on_invalid_choice=False,
        fallback_players=game.players,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid land target")
        return True, "resolved"
    # Appended rather than assigned: a land pointed at twice carries both
    # swaps, and the order they were created in is the order CR 613.7 applies
    # them in — "produces {C} instead of {W}" and then "produces {G} instead of
    # {C}" is a land that makes green.
    swaps = list(target.metadata.get("produced_mana_swaps", ()))
    swaps.append((replaced, produced))
    target.metadata["produced_mana_swaps"] = tuple(swaps)
    game.log.append(
        f"{context.card.name}: {target.card.name} now produces "
        f"{{{produced}}} instead of {{{replaced}}}"
    )
    return True, "resolved"


@effect_handler("grant_spend_mana_as_though")
def grant_spend_mana_as_though(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For one spell this turn, you may spend mana as though it were mana of
    any type to pay that spell's mana cost." (North Star.)

    CR 609.4: nothing about the pool changes and no mana is made. The grant is
    recorded on the player and spent by the payment, which is why it is a list
    of bounded permissions rather than a flag — "one spell" is a printed number
    and the permission runs out.
    """
    caster = context.caster
    caster.spend_mana_as_though_grants.append({
        "spells": max(1, int(instruction.payload.get("spells", 1))),
        "any_type": bool(instruction.payload.get("any_type")),
    })
    breadth = "type" if instruction.payload.get("any_type") else "color"
    game.log.append(
        f"{context.card.name}: {caster.name} may spend mana as though it were "
        f"mana of any {breadth} for {instruction.payload.get('spells', 1)} "
        "spell(s) this turn"
    )
    return True, "resolved"


def _colors_opponents_lands_produce(game, caster) -> frozenset[str]:
    """The colours "a land an opponent controls could produce" names (Fellwar
    Stone).

    Through the control seam, because "controls" is a seat question (CR 109.5)
    and ``player.battlefield`` is only a projection of it - and through
    ``has_type`` for the land test, so an animated land still counts and a
    permanent that stopped being one does not (CR 613 layer 4).

    The per-card answer is ``commander.produced_mana_colors``, which was already
    the engine's one reader of "what colours could this land make". A second
    copy here would be a second answer to one question, and the direction it
    would drift is a Stone that taps for a colour no opponent can make.
    """
    from ..commander import produced_mana_colors

    seat = game.players.index(caster)
    colors: set[str] = set()
    for opponent in game.opponents_of(seat):
        for perm in game.controlled_by(opponent):
            if perm.has_type("land"):
                colors |= produced_mana_colors(perm.effective_card)
    return frozenset(colors)


@effect_handler("note_mana_spent")
def note_mana_spent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Note the type [and amount] of mana spent to pay this activation cost."
    (Jeweled Amulet, Ice Cauldron.)

    Nothing is produced. What the instruction does is copy CR 107.4b's symbols
    out of the payment the activation path measured — the pool before the cost
    minus the pool after it — onto the ability's own source, where "this
    artifact's last noted type" reads it back.

    The record is written even when the payment was empty, because "last noted"
    is a *replacement*: an activation paid for free notes nothing, and the
    adding ability must then add nothing rather than repeat the last one.

    ``with_amount`` is not read here. Both cards note the same symbols; the word
    changes what the *adding* half of the card does with them, which is where
    ``from_noted`` is read. Carrying it on the payload rather than dropping it
    keeps the printed difference visible to anything reading the program.
    """
    from ..noted_mana import note_mana_spent as _record

    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    spent = (context.choices or {}).get("mana_spent_for_cost") or {}
    _record(source, dict(spent))
    game.log.append(
        f"{context.card.name} noted "
        + ("".join(f"{{{sym}}}" * int(n) for sym, n in sorted(spent.items()))
           or "no mana")
    )
    return True, "resolved"
