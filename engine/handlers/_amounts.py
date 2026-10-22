"""A printed quantity **counted** at resolution.

"Where X is the number of …", "for each …", "equal to its power", "half the
cards in their hand, rounded up": CR 608.2 counts a where-clause when the effect
happens rather than when the spell is announced, and CR 604.3's
characteristic-defining counts are counted again whenever they are asked.
:func:`evaluate_count` answers a count spec against a board,
:func:`count_from_payload` answers it at resolution — where the context knows
who "you" and "target player" are and what the resolution has recorded —
:func:`per_recipient_amount` gives one number per seat, and
:func:`resolve_amount` reads the plain or X-bearing amount a payload carries.

The handler twin of ``engine/grammar/lowering/_amounts.py``, under its name:
that module decides what a count spec says, and this one what it comes to.

A floor, split out of ``_common`` at the 2,000-line cap's split round, and the
top of the four that module was cut into. It reads ``_chosen`` (a count's "of
that color"), ``_filters`` (what the counted set admits) and ``_targets`` ("its
power" names an object), and none of them reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle_types import OracleInstruction
from ..models import Permanent, PlayerState
from ._chosen import (_resolve_chosen_color, _resolve_chosen_subtype,
                      count_spec_in_resolution,
                      resolve_chosen_card_type_in_resolution)
from ._filters import (_card_matches_filter, permanent_effective_colors,
                       permanent_matches_filter)
from ._targets import (attached_host, defending_player_seat,
                       resolve_role_permanent, resolve_target_permanent)


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
        # ``{"minus_x": n}`` — "…and **5 minus X** damage to that creature's
        # controller" (Liquid Fire). The printed number with the X taken off
        # it, the third arithmetic beside the two above and read here for
        # their reason. Floored at zero: CR 107.1b uses zero where a
        # calculation that determines the result of an effect would be
        # negative, so an X larger than the printed number spends nothing.
        minuend = raw.get("minus_x")
        if minuend is not None:
            return max(0, int(minuend) - max(0, x_value or 0))
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
    # "…where X is the number of cards in your hand **minus the number of cards
    # in that player's hand**." (Bulwark.) A whole second count taken off this
    # one, which is why it is a nested spec rather than another scalar key on
    # this one: both sides are read at resolution, with their own zones and
    # their own owners, and this function is the only thing that can read
    # either.
    #
    # Taken at the top, over the *finished* left-hand value, so every branch
    # below — a board scan, a payment record, a scratchpad read — is subtracted
    # from without knowing it can be. Clamped at zero where every quantity in
    # this engine is (CR 107.1b): a hand smaller than the opponent's deals no
    # damage rather than healing them.
    # "…for each permanent **of that color**" (Rith, the Awakener). CR 608.2d's
    # colour, chosen by the step in front of this one: resolved here, where the
    # resolution is in hand, because `evaluate_count` below is also the CR 604.3
    # recompute's reader and holds no scratchpad.
    spec = count_spec_in_resolution(spec, context)
    # "…choose **X** cards in your hand and discard the rest." (Breakthrough.)
    # The count less the X the cast announced (CR 107.3a) — read off the
    # context before the dispatch point substitutes this spec's own answer for
    # it. Clamped at zero (CR 107.1b): a hand of X or fewer loses nothing.
    if spec.get("minus_announced_x"):
        whole = dict(spec)
        whole.pop("minus_announced_x")
        return max(0, count_from_payload(
            game, context, whole, instruction, source=source,
        ) - max(0, int(context.x_value or 0)))
    subtracted = spec.get("minus_count")
    if isinstance(subtracted, dict):
        whole = dict(spec)
        whole.pop("minus_count")
        return max(0, count_from_payload(
            game, context, whole, instruction, source=source,
        ) - count_from_payload(
            game, context, subtracted, instruction, source=source,
        ))
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
    # "…you gain 2 life for each 1 life **you lost**." (Transcendence.) The
    # branch above one record over: a number the *firing event* carried,
    # frozen into the trigger's context by its fire site, rather than one a
    # step of this resolution wrote. An absent record counts zero, which is
    # the honest answer for an ability resolving with no event behind it.
    trigger_record = spec.get("trigger_record")
    if trigger_record is not None:
        frozen = (context.trigger_context or {}).get(trigger_record, 0)
        return max(0, _scaled(int(frozen or 0), spec))
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
    # "…draws cards equal to **the greatest number of cards a player discarded
    # this way**." (Windfall.) A maximum over a ``{seat: number}`` record an
    # earlier step of this same effect wrote — an aggregate *across* seats,
    # which no zone count can be and no scalar record holds: the flat
    # ``discarded_count`` beside it is the whole resolution's total, and the
    # per-recipient channel would answer one seat at a time. An empty or absent
    # record is zero, which is what "each player discarded nothing" means.
    greatest = spec.get("greatest_per_seat")
    if greatest is not None:
        tallies = context.results.get(str(greatest)) or {}
        values = [
            int(value or 0) for value in
            (tallies.values() if isinstance(tallies, dict) else ())
        ]
        return max(0, _scaled(max(values) if values else 0, spec))
    # "…where X is **the milled card's mana value**" (Infernal Genesis). The
    # printed mana value (CR 202.3; a card in a zone has no computed one) of
    # what the earlier step recorded — nothing milled is zero.
    #
    # "…where X is **the revealed card's mana value**" (Planeswalker's Favor,
    # Scorn). The same read over a record that is *one card* rather than a list
    # of them — ``revealed_card`` is singular because a reveal of one card names
    # one referent. An empty hand revealed nothing, the record is absent, and
    # CR 107.2 makes the number 0.
    recorded_mana_value = spec.get("recorded_card_mana_value")
    if recorded_mana_value is not None:
        recorded = context.results.get(str(recorded_mana_value))
        if recorded is None:
            recorded = ()
        elif not isinstance(recorded, (list, tuple)):
            recorded = (recorded,)
        return max(0, _scaled(sum(
            int(getattr(card, "cmc", 0) or 0) for card in recorded
        ), spec))
    recorded_cards = spec.get("recorded_cards")
    if recorded_cards is not None:
        described = spec.get("filter") or {}
        # "…for each card **of the chosen type** revealed this way" (Blood
        # Oath). CR 608.2d's choice, made by an earlier step of this same
        # resolution and spent here — the same resolution that wrote the record
        # this branch is counting, which is what makes the scratchpad the place
        # to read it. Left untouched by every spec that printed no such phrase,
        # and refusing every card if the key is there with nothing behind it:
        # ``_card_matches_filter`` answers False for an unresolved
        # ``chosen_card_type``, which for a count is the direction that is too
        # small rather than too large.
        described = resolve_chosen_card_type_in_resolution(described, context)
        # "…the number of cards **of that color** revealed this way" (Darigaaz,
        # the Igniter) — the same choice one characteristic over, already
        # resolved by the step at the top of this function when it is carried.
        return max(0, _scaled(sum(
            1 for card in (context.results.get(str(recorded_cards)) or ())
            if _card_matches_filter(card, described)
        ), spec))
    # "…where X is the total power of the creatures sacrificed this way"
    # (Sword of the Ages). Not a set in any zone either: the creatures paid this
    # ability's cost (CR 601.2h) and are cards in a graveyard by now, so the sum
    # is over what the activation recorded — their last power on the
    # battlefield (CR 608.2h). A cost that ate nothing sums to zero, which is
    # what "any number of creatures" and none of them means.
    if spec.get("cost_sacrifices_power"):
        sacrificed = (context.choices or {}).get("sacrificed_set_for_cost") or ()
        return max(0, sum(max(0, perm.effective_power) for perm in sacrificed))
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
            # Through `_scaled`, exactly as its sacrifice twin below already
            # was. This branch returned the bare number, so "1 plus the exiled
            # creature's mana value" (Food Chain) would have added the constant
            # nowhere — the multiplier, the halving and the offset every other
            # count spec carries were all silently dropped on this one channel.
            # Nothing printed the pair while the only card here was Necropolis'
            # unadorned "the exiled card's mana value", which is why the
            # asymmetry cost nothing until it did.
            return max(0, _scaled(int(getattr(exiled, "cmc", 0) or 0), spec))
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
    # "…equal to **the mana value of the discarded card**" (Pyromancy). The
    # fourth payment channel, beside the three above and for their reason: the
    # card was discarded before the ability reached the stack (CR 601.2h), so
    # nothing at resolution can say which of a graveyard's cards it was.
    #
    # The channel is a **list** — both discard-cost spellings feed it, and a
    # cost that discarded a whole hand would put several cards on it — so the
    # sum is what the words mean whatever the cost took: one card is its own
    # mana value, and none is zero rather than a guess. Read off the *card*
    # (CR 202.3): a card in a graveyard has no computed characteristics at all
    # (CR 613.1), which is why the lowering admits mana value and nothing else.
    cost_discard = spec.get("cost_discard_characteristic")
    if cost_discard is not None:
        discarded = (context.choices or {}).get("discarded_for_cost") or []
        if cost_discard != "mana_value":
            return 0
        return max(0, _scaled(
            sum(int(getattr(card, "cmc", 0) or 0) for card in discarded), spec
        ))
    # "…where X is **the number of cards exiled this way**" (Painbringer). How
    # many cards the ability's own cost exiled — the counter channel below one
    # object kind over, and off the same record for its reason: the cards left
    # the graveyard before the ability was on the stack (CR 601.2h), so no
    # zone holds "the cards exiled this way" apart from everything else in
    # exile. An "any number of" that named none is zero.
    if spec.get("cost_exiled_count"):
        exiled_set = (context.choices or {}).get("exiled_set_for_cost") or ()
        return max(0, _scaled(len(exiled_set), spec))
    # "…equal to **the number of pain counters removed this way**" (Torture
    # Chamber); "You gain 2 life **for each elixir counter removed this way**"
    # (Essence Bottle). How many counters the ability's own cost took off,
    # which after CR 601.2h is a number no board holds: the permanent reads
    # zero by the time this resolves, so a store scan would answer the exact
    # complement of what the card says. Off the record the activation kept
    # (CR 608.2h), beside the three payment channels above.
    if spec.get("cost_counters_removed") is not None:
        removed = (context.choices or {}).get("counters_removed_for_cost", 0)
        return max(0, _scaled(int(removed or 0), spec))
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
    if scope in ("you", "opponents"):
        # "…the number of permanents of the chosen color **your opponents
        # control**" (Chameleon Spirit). ``opponents`` widens the *scan*, not
        # the seat: the phrase's "your" is still CR 109.5's, so the seat this
        # resolves is the same one "you control" would resolve to, and
        # `evaluate_count` reads it as the observer the filter's own
        # ``controller`` key is relative to. Landing it on the "target" fallback
        # below would make the observer whichever player the spell happened to
        # point at, and the count would be of the wrong seat's opponents.
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
    elif scope == "defending_player":
        # "…for each nonbasic land **defending player** controls." (Mercadia's
        # Downfall.) CR 506.2's seat, which exists only inside a combat phase
        # and which no read of a permanent can supply — through
        # ``defending_player_seat``, the one reader every other handler already
        # asks, so the count and a damage or a sweep in the same sentence can
        # never land on two different players.
        #
        # A spell asks the *live* combat rather than a frozen record: this
        # sentence is not a trigger, so nothing froze a seat for it, and by the
        # time a combat trick resolves the defending player is exactly the one
        # the board says. No combat, no seat, and the count is zero — which is
        # what "defending player" names outside combat.
        seat = defending_player_seat(game, context)
        if seat is None:
            return 0
        owner = game.players[seat]
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
        effect_spell=resolving_spell_name(context),
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


def per_recipient_amount(game, context, spec: dict, face, *, source=None) -> int:
    """One seat's share of an ``x_from_count_per_recipient`` spec.

    The channel that carries "one number per player" — "the number of Islands
    **that player** controls" (Typhoon), "3 minus the number of cards **they**
    discarded this way" (Mind Bomb), "**that many** cards" after an each-player
    discard (Flux). Four shapes and one reader, because the channel already
    carries four value shapes and this repo has been burned by a channel whose
    producers disagreed about arity (SET_PLAYBOOK's ``permanents_from`` entry).
    ``deal_damage`` spelled three of them inline; a second inline copy in the
    draw handler is how the fourth would have come to mean something else.

    * ``seat_tally_of`` — a ``{permanent_id: seat}`` map an earlier step froze,
      counted for this seat (Builder's Bane).
    * ``resolution_record`` with ``base`` — a printed constant *minus* what
      this seat's answer recorded (Mind Bomb's shortfall).
    * ``seat_record`` — what this seat's answer recorded, plainly (Flux). Its
      own key rather than a ``resolution_record`` with the base left out,
      because that spelling reads ``0 - recorded`` and clamps to zero: a
      shortfall and a tally are opposite arithmetic and one key cannot be both.
    * anything else — an ordinary count spec, evaluated against this seat.

    A seat the record never mentions did nothing, which every one of the four
    reads as zero.
    """
    seat = game.players.index(face)
    # "…the number of creatures **of that color** that player controls"
    # (Searing Rays): the same resolution-scoped colour `count_from_payload`
    # resolves, through the same function.
    spec = count_spec_in_resolution(spec, context)
    tally = spec.get("seat_tally_of")
    if tally is not None:
        recorded = context.results.get(tally) or {}
        return sum(1 for owner in recorded.values() if owner == seat)
    plain = spec.get("seat_record")
    if plain is not None:
        recorded = context.results.get(plain) or {}
        return max(0, int(recorded.get(seat, 0) or 0))
    record = spec.get("resolution_record")
    if record is not None:
        recorded = context.results.get(record) or {}
        return max(0, int(spec.get("base", 0)) - int(recorded.get(seat, 0) or 0))
    return max(0, evaluate_count(
        game, face, spec, exclude=source, source=source,
    ))


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
    if query.get("recipient") == "target":
        # "…equal to the damage already dealt **to it** this turn"
        # (Whipkeeper). The permanent the sentence targeted, by the id the
        # announcement stamped — never a fallback pick: a history read off a
        # creature the player did not choose is a number about somebody else.
        # A target that has left answers with the base, which is nothing.
        aimed = resolve_target_permanent(
            game, context, predicate=lambda p: True,
            fallback_on_invalid_choice=False,
        )
        if aimed is None:
            return base
        return max(0, base + damage_dealt_to_permanent(game, aimed.permanent_id))
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
    if spec.get("object") == "attached":
        # "…deals damage equal to **that creature's power**…" (Unnatural
        # Hunger). The permanent the ability's source is attached to, through
        # the one reader that already answers "what is this Aura on" including
        # the last-known-information case (CR 603.10) — the Aura may have gone
        # to a graveyard between the trigger and its resolution.
        host = attached_host(game, context.source_permanent)
        if host is None:
            return 0
        if name == "power":
            return max(0, int(host.effective_power) + offset)
        if name == "toughness":
            return max(0, int(host.effective_toughness) + offset)
        return max(0, int(getattr(host.card, "cmc", 0) or 0) + offset)
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
            # CR 608.2h: an object the effect itself has moved answers with its
            # last known information. "Destroy target artifact. … where X is
            # that artifact's mana value" (Artifact Mutation) asked the
            # battlefield for an artifact its own first sentence had just
            # destroyed, read zero and made no tokens. The record is the one
            # the lowering found a step of this same effect writing
            # (``where_x._last_known_record``); a target that was gone before
            # the effect began wrote nothing, and still answers zero.
            recorded = (context.results or {}).get(str(spec.get("last_known") or ""))
            if recorded is None or isinstance(recorded, bool):
                return 0
            return max(0, int(recorded) + offset)
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
        return _plus(total, spec)
    # "a third of their life" (Pox) is the same arithmetic with a different
    # denominator, so it is the same key with a number beside it rather than a
    # second rounding channel. Absent means 2, which keeps every spec written
    # before fractions existed byte-identical.
    divisor = max(1, int(spec.get("divide_by", 2) or 2))
    return _plus(-(-total // divisor) if rounding == "up" else total // divisor, spec)


def _plus(total: int, spec: dict) -> int:
    """*total* with the constant a clause printed **after** its multiplier.

    "1 plus twice the number of age counters on it" (Mwonvuli Ooze) and "twice
    the number of age counters on this enchantment minus 2" (Heart of Bogardan)
    are 2N+1 and 2N-2, and neither is expressible as ``offset``: that key is
    applied *before* the multiplier, because the phrase it implements ("beyond
    the first", CR 702.23a) narrows the set being counted rather than shifting
    the product. One number cannot mean both, so this is a second key rather
    than a reinterpretation of the first.

    Not floored here. The floor belongs to whatever spends the number — damage
    and a P/T both clamp, and doing it twice would hide a spec that came out
    negative for the wrong reason.
    """
    return total + int(spec.get("plus", 0) or 0)


def resolving_spell_name(context) -> str | None:
    """The name of the **spell** whose effect *context* is carrying out, or
    None when an ability is resolving.

    "…effects from spells named Flame Burst count it as a card named Flame
    Burst." (Pardic Firecat.) An activated ability carries its printed line, a
    triggered one its event and an ability of a permanent its source; a spell's
    resolution — and its announcement, which is asked the same count for an X
    fixed as it is cast (CR 601.2b) — carries none of the three.
    """
    if (
        context.source_permanent is not None
        or context.ability_text
        or context.trigger_context is not None
    ):
        return None
    return getattr(context.card, "name", None) or None


def _battlefield_matches(
    game: "Game", owner: "PlayerState", spec: dict, filt: dict, *,
    exclude=None, source=None,
) -> "list[Permanent]":
    """The permanents a battlefield count spec names, before any aggregate.

    The scan :func:`evaluate_count` has always made, lifted out so the *set*
    behind a count has a second reader: a count answers how many basic land
    types are among them, and :func:`basic_land_types_among` answers which.
    One scan, so the two cannot disagree about whose board is read or what a
    printed narrowing means.

    *filt* is the spec's filter as the caller has already resolved it; it is
    consumed here (``exclude_self`` is popped), which is what the inline code
    did to the same dict.
    """
    # "…the number of green creatures **on the battlefield**" (An-Havva
    # Constable, An-Havva Inn). CR 403.1 makes the battlefield one zone
    # shared by every player, so a phrase that scopes to it scopes to
    # nobody — the same ``owner: "all"`` the graveyard branch below already
    # answers for "in all graveyards" (Lhurgoyf), which is why it is one
    # more zone reading that key rather than a second key meaning it.
    # Through the control seam, because "on the battlefield" is every
    # permanent in play and `all_permanents` is the one answer to that.
    every_seat = spec.get("owner") == "all"
    # "…the number of permanents of the chosen color **your opponents
    # control**" (Chameleon Spirit). Which piles to scan and whose "you" the
    # filter's seat words mean were one variable here, and this is the scope
    # that needs them to be two: every battlefield is read, and the observer
    # stays the counting seat so the ``controller`` key the lowering left in
    # the payload can be answered by `subject_matches` — the same reader
    # that answers it in every other sentence printing the phrase. ``all``
    # is the scope that really does mean nobody (CR 403.1's shared zone),
    # and it keeps its ``observer=None``.
    opponents_only = spec.get("owner") == "opponents"
    seat = None if every_seat else game.players.index(owner)
    # "**Other** …" (CR 109.5) is an identity comparison against the ability's
    # own source, which the matcher deliberately does not answer — it is
    # about one permanent alone. A spec carrying the key with no source to
    # compare against counts nothing extra rather than silently dropping it:
    # the caller that has a source passes one, and the continuous recompute
    # that does not never produces the key.
    #
    # *exclude* is one permanent or several. An Aura's sentence about its
    # host has two objects "other" may be measured from - "enchanted creature
    # gets +1/+1 for each other **creature**" (Vampirism) leaves out the
    # host, "+2/+2 for each other **enchantment**" (Ancestral Mask) leaves
    # out the Aura - and the caller that knows both passes both.
    skipped: tuple = ()
    if filt.pop("exclude_self", False) and exclude is not None:
        skipped = tuple(exclude) if isinstance(exclude, (tuple, list)) else (exclude,)
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
    scanned = (
        game.all_permanents() if every_seat or opponents_only
        else game.controlled_by(seat)
    )
    # Through ``subject_matches`` rather than the pure half, because the
    # pure half cannot answer a **keyword** (CR 613 layer 6, which needs
    # the game): "you gain 1 life for each creature you control with
    # flying" (Aven Gagglemaster) was countable only by a hand-built
    # payload in `lowering/life.py` that named the key on its own. This is
    # the one place a count decides what a printed noun phrase means, so it
    # asks the one function that answers all of it — the seat scoping the
    # scan is the same seat CR 109.5's "you" names, and it is handed over
    # so a phrase that carries a controller word means what it would mean
    # anywhere else.
    from ..subject_filters import subject_matches

    matched = [
        perm for perm in scanned
        if not any(perm is left_out for left_out in skipped)
        and subject_matches(game, perm, filt, observer=seat, source=source)
    ]
    return matched


def basic_land_types_among(
    game: "Game", owner: "PlayerState", spec: dict, *, source=None
) -> tuple[str, ...]:
    """**Which** basic land types are among the permanents *spec* names — the
    set whose size ``aggregate: distinct_basic_land_types`` counts.

    "For each basic land type among lands you control, this creature has
    landwalk of that type." (Magnigoth Treefolk.) Every other domain card
    spends the number; this one spends the types themselves, so it asks the
    same scan for the set rather than re-deriving it — through the layer-4
    accessor, like the count, because a land's basic land types are computed
    (a Blood Moon or a Phantasmal Terrain changes the answer).

    In CR 305.6's order, which is the accessor's. A spec that is not a
    battlefield count of this aggregate names no such set and answers
    nothing: the direction that cannot invent an ability.
    """
    if (
        spec.get("zone", "battlefield") != "battlefield"
        or spec.get("aggregate") != "distinct_basic_land_types"
    ):
        return ()
    matched = _battlefield_matches(
        game, owner, spec, dict(spec.get("filter") or {}), source=source,
    )
    found: list[str] = []
    for perm in matched:
        for land_type in perm.basic_land_types:
            if land_type not in found:
                found.append(land_type)
    from ..models import _LAND_TYPE_MANA

    return tuple(land_type for land_type in _LAND_TYPE_MANA if land_type in found)


def evaluate_count(
    game: "Game", owner: "PlayerState", spec: dict, *, exclude=None, source=None,
    effect_spell: str | None = None,
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
    # "Each player discards cards **the same way**" (Balancing Act): how many
    # more of the counted things *owner* has than the player with the fewest —
    # the same count taken for every living seat, and this seat's distance
    # from the smallest. Unwrapped first because it is not a count of its own:
    # it is an arithmetic over whichever one follows, asked once per seat.
    if spec.get("excess_over_fewest"):
        plain = {key: value for key, value in spec.items() if key != "excess_over_fewest"}
        fewest = min(
            (
                evaluate_count(
                    game, seat, plain, exclude=exclude, source=source,
                    effect_spell=effect_spell,
                )
                for seat in game.players if not seat.lost
            ),
            default=0,
        )
        mine = evaluate_count(
            game, owner, plain, exclude=exclude, source=source,
            effect_spell=effect_spell,
        )
        return max(0, mine - fewest)
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
    # "…the number of **age counters on it**" (Malignant Growth's draw,
    # Primordial Ooze's where-clause, Revered Unicorn's leave trigger, Mwonvuli
    # Ooze's characteristic-defining P/T). Counters sitting on the ability's own
    # source: not a set of objects in any zone, so there is nothing below to
    # scan for it. The kind is data, and ``counters_on`` is the one reader that
    # knows whether it means the P/T channel or a store the card invented
    # (CR 122.1).
    #
    # Answered **here** rather than in ``count_from_payload`` above, where it
    # used to be: a CR 604.3 recompute reaches this function directly with the
    # permanent it is refreshing as *source* and never passes through a
    # resolution context at all, so a branch up there was unreachable for the
    # one caller that has no context. One evaluator, so the four printed word
    # orders cannot count differently.
    counters = spec.get("source_counters")
    if counters is not None:
        if source is None:
            return 0
        from ..named_counters import counters_on

        return max(0, _scaled(counters_on(source, str(counters)), spec))
    # "…equal to the number of fade counters on **Saproling Burst**." (The
    # Burst's Saproling, whose text names its maker.) The same pile, read off
    # the permanent the token maker stamped as this token's creator — by id,
    # because a Burst that left and came back is a new object (CR 400.7) whose
    # counters are not the ones this token's maker had. A maker that has left
    # the battlefield holds no pile here, so the count is zero and the token is
    # a 0/0, which is what the card's rulings give once the Burst is gone.
    maker_counters = spec.get("creator_counters")
    if maker_counters is not None:
        if source is None or game is None:
            return 0
        from ..named_counters import counters_on
        from ..tokens import CREATED_WITH_PERMANENT_ID

        maker = game.permanent_by_id(source.metadata.get(CREATED_WITH_PERMANENT_ID))
        if maker is None or not game.is_on_battlefield(maker):
            return 0
        return max(0, _scaled(counters_on(maker, str(maker_counters)), spec))
    # "…where X is the number of arrow counters on **Archery Training**." (The
    # ability Archery Training gives the creature it enchants, whose text names
    # the Aura.) The same pile again, on the one permanent CR 201.5a says a
    # granted ability's use of its granter's name means — found by the id
    # ``granted_abilities.bind_granter`` wrote into the sentence as it was
    # folded onto the host. By id for ``creator_counters``' reason: an Aura
    # that left and came back is a new object (CR 400.7) granting a new
    # ability, and an ability already on the stack keeps naming the object that
    # granted it, wherever that object is attached now. One that has left the
    # battlefield holds no pile there, so the count is zero.
    granter_counters = spec.get("granter_counters")
    if granter_counters is not None:
        if game is None:
            return 0
        from ..named_counters import counters_on

        granter = game.permanent_by_id(spec.get("granter_id"))
        if granter is None:
            return 0
        return max(0, _scaled(counters_on(granter, str(granter_counters)), spec))
    # "…where X is **the life paid as this artifact entered**" (Phyrexian
    # Processor). A number the permanent is carrying that is not a pile of
    # counters: it was chosen once as a CR 614.1c entry replacement and is read
    # unchanged however many activations later, so nothing recomputes it and no
    # zone holds a set it could be counted from.
    #
    # Answered here beside the counters, and for their reason: this is the one
    # evaluator both a resolution and a CR 604.3 recompute reach, and a branch
    # one layer up would be unreachable for the caller that has no context.
    # A resolution with no source reads zero rather than guessing — an ability
    # whose permanent has left makes a 0/0 that dies, which is what CR 608.2h's
    # last known information says when nothing was known.
    record = spec.get("source_record")
    if record is not None:
        if source is None:
            return 0
        return max(0, _scaled(int(source.metadata.get(str(record), 0) or 0), spec))
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
        # The scan itself is :func:`_battlefield_matches` — which piles are
        # read, whose "you" the filter's seat words mean, and the resolution
        # of the source's chosen colour and type. Lifted out when the *set*
        # behind a count got a second reader (``basic_land_types_among``).
        matched = _battlefield_matches(
            game, owner, spec, filt, exclude=exclude, source=source,
        )
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
        if aggregate == "distinct_basic_land_types":
            # "…for each basic land type among lands you control" (domain:
            # Wayfaring Giant, Tribal Flames). The *types*, not the lands: two
            # Forests are one and a Tropical Island is two, so the answer is
            # between zero and CR 305.6's five. Through the layer-4 accessor,
            # because a land's basic land types are computed — a Phantasmal
            # Terrain or a Blood Moon changes what is counted, and the printed
            # type line would not know.
            types: set[str] = set()
            for perm in matched:
                types.update(perm.basic_land_types)
            return _scaled(len(types), spec)
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
    # *effect_spell* is the name of the spell whose effect is counting, when
    # one is: "effects from spells named Flame Burst count it as a card named
    # Flame Burst" (Pardic Firecat) is asked of the name test below, with the
    # zone the card is in, and by nobody else — a CR 604.3 recompute passes
    # none and gets CR 201.2a's plain answer.
    matched_cards = [
        card for card in cards
        if _card_matches_filter(
            card, filt, game=game, owner=owner, zone=zone,
            effect_spell=effect_spell,
        )
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
