"""Counter **placements** (CR 122): a marker put on an object.

+1/+1 and -1/-1 counters on a target, several targets, the source, an Aura's
host, a permanent an earlier step bound, every creature a phrase names
(Basri's Solidarity, Misfortune), one per creature that died this turn;
loyalty counters (CR 306.5c); and the **named** counters a card's own text
gives a meaning to (corpse, glyph, …) on the source, a target, an Aura's
host or the creatures in combat with the source. The P/T a counter
may carry is a consequence the layers compute, not this effect.

The handler twin of ``engine/grammar/lowering/counters.py`` (with
``_plus_one_counters``, ``_named_counters`` and ``_counter_stores`` beside it),
and gathered from the two modules that had grown a half each: the +1/+1 and
loyalty placements from ``pump.py``, the named ones from ``board_misc.py``.
Removing a counter is ``counter_removal``'s.

Created at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..oracle_types import (ATTACHED_PERMANENT_CONTROLLER,
                            COUNTERS_PLACED_THIS_WAY)
from ._amounts import resolve_amount, count_from_payload
from ._filters import permanent_matches_filter
from ._targets import (divided_target_permanent, recorded_permanent_ids,
                       attached_host, frozen_that_player_seat,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def place_loyalty_counters(permanent, count: int) -> int:
    """Put *count* loyalty counters on *permanent*; return the new total.

    CR 306.5c: a planeswalker's loyalty **is** its loyalty counters, so this is
    the one key damage marks against and a loyalty cost pays from. One function
    because there is now more than one way a counter arrives — the ability's own
    source, and a permanent its controller chose.
    """
    loyalty = int(permanent.metadata.get("loyalty_counters", 0)) + count
    permanent.metadata["loyalty_counters"] = loyalty
    return loyalty


@effect_handler("add_loyalty_counters")
def add_loyalty_counters(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a loyalty counter on Garruk." (Garruk, Unleashed's −2.) Loyalty on
    the battlefield IS its loyalty counters (CR 306.5c), the same key damage
    and loyalty costs adjust. The source may already have left — a walker that
    paid itself to 0 dies before its ability resolves — in which case the
    counter lands on nothing (CR 608.2b handles the analogous target)."""
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: its source has left, no loyalty added")
        return True, "resolved"
    count = int(instruction.payload.get("count", 1))
    total = place_loyalty_counters(source, count)
    game.log.append(
        f"{context.card.name}: {count} loyalty counter(s) added (now {total})"
    )
    return True, "resolved"


@effect_handler("add_loyalty_counters_to_chosen")
def add_loyalty_counters_to_chosen(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a loyalty counter on a Liliana planeswalker you control."
    (Liliana's Scrounger.)

    No "target" is printed, so nothing was chosen when the ability went on the
    stack (CR 115.10): the controller picks now, out of what the noun phrase
    names *now* — the ``untap_up_to`` shape, not the targeted one. Reading it as
    a target would move the choice to announcement and let the ability be
    countered on resolution (CR 608.2b) when the walker it named has left, where
    the printed card would simply pick another.

    One candidate is not a choice and is applied at once; several arm the
    prompt; none does nothing, because "a Liliana planeswalker you control" can
    name an empty set and the ability still resolves.
    """
    # Imported here rather than at module scope: engine/subject_filters.py
    # imports the handler floors (handlers._filters and the rest), so a
    # module-level import would close the cycle through
    # engine/handlers/__init__.py. Same reason engine/oracle.py imports
    # it inside _resolve_subject_groups.
    from ..subject_filters import subject_matches

    seat = game.players.index(context.caster)
    described = dict(instruction.payload.get("filter") or {})
    count = int(instruction.payload.get("count", 1))
    source = context.source_permanent
    candidates = [
        perm
        for perm in game.all_permanents()
        if subject_matches(game, perm, described, observer=seat, source=source)
    ]
    if not candidates:
        game.log.append(
            f"{context.card.name}: nothing it controls can receive a loyalty counter"
        )
        return True, "resolved"
    if len(candidates) == 1:
        total = place_loyalty_counters(candidates[0], count)
        game.log.append(
            f"{context.card.name}: {count} loyalty counter(s) on "
            f"{candidates[0].card.name} (now {total})"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "loyalty_recipient", seat,
        card_name=context.card.name,
        count=count,
        filter=described,
        _candidates=candidates,
        _source=source,
    )
    return True, "resolved"


@effect_handler("add_power_counters_to_self")
def add_power_counters_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{X}, {T}: Put up to X +1/+0 counters on this creature. This ability
    can't cause the total number of +1/+0 counters on this creature to be
    greater than N." — Clockwork Beast (seven) and Clockwork Avian (four).

    The cap is on the payload. It used to be the constant 7 in this function
    and the word "seven" inside a card-name-keyed hook's dictionary key, which
    is two copies of one number and the reason the Avian needed a second entry
    to say four.
    """
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    amount = instruction.payload.get("amount", 0)
    requested = context.x_value or 0 if amount == "x" else int(amount)
    cap = int(instruction.payload.get("cap", 0))
    current = int(source_permanent.metadata.get("plus_1_0_counters", 0))
    added = min(max(0, requested), max(0, cap - current))
    if added:
        # Through the counter seam rather than the two channels by hand: the
        # cap above reads the record, so a placement that wrote only
        # `power_bonus` would let the ability run past its own limit, and a
        # direct `power_bonus` poke is the P/T write `engine/pt.py` exists to
        # keep in one place.
        game.place_pt_counters(source_permanent, "+1/+0", added)
    game.log.append(f"{card.name} gets {added} +1/+0 counter(s)")
    return True, "resolved"


@effect_handler("add_plus1_counters_for_each_creature_died")
def add_plus1_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Khabál Ghoul: "At the beginning of each end step, put a +1/+1 counter on
    this creature for each creature that died this turn." Resolves off the stack;
    the death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    game.place_plus1_counters(source, count)
    game.log.append(f"{source.card.name} gets {count} +1/+1 counter(s)")
    return True, "resolved"


@effect_handler("add_counter_to_self")
def add_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # "…put **that many** +1/+1 counters on this creature." (Tetravus.) The
    # count is a back-reference to what the step before it recorded; absent, the
    # payload means one, which is what every earlier caller emitted.
    raw_count = instruction.payload.get("count", 1)
    if raw_count == "trigger_count":
        # …and under a *trigger* the number is the firing event's, frozen into
        # the trigger's context by the fire site (CR 603.10). "Whenever you gain
        # life, put that many +1/+1 counters on this creature" (Light of
        # Promise) has no earlier step in its own resolution to have written the
        # scratchpad key below, so it read zero and placed nothing while
        # reporting itself resolved. The lowering says which key when the event
        # has one; without it this stays the scratchpad read Tetravus needs.
        from_trigger = instruction.payload.get("amount_from_trigger")
        if from_trigger is not None:
            count = int(
                (context.trigger_context or {}).get(str(from_trigger), 0) or 0
            )
        else:
            count = int(context.results.get("trigger_count", 0))
    else:
        # "Put **X** +0/+1 counters on this creature" (Necropolis): the count
        # may be the where-clause's X, resolved through the same
        # `context.x_value` every other amount reads.
        #
        # …and that X may be *defined* by a count taken at resolution rather
        # than announced with a cast: "put a +1/+1 counter on this creature
        # **for each 1 damage dealt to you this turn**" (Discordant Spirit).
        # The same `x_from_count` channel the pump handlers at the top of this
        # file read, so one printed clause is one number wherever it is spent.
        x_value = context.x_value
        x_count = instruction.payload.get("x_from_count")
        if x_count is not None:
            x_value = count_from_payload(game, context, x_count)
        count = resolve_amount(raw_count, x_value)
    if count <= 0:
        return True, "resolved"
    # Which CR 122.1a pair. Absent on every payload written before Necropolis,
    # and those all mean the one kind this handler used to place - so the
    # default is the whole of the compatibility, and `place_plus1_counters`
    # stays the path for it because that kind is the one with a CR 614 event
    # and a trigger behind it.
    kind = str(instruction.payload.get("counter", "+1/+1"))
    if kind == "+1/+1":
        game.place_plus1_counters(source_permanent, count)
    else:
        game.place_pt_counters(source_permanent, kind, count)
    game.log.append(
        f"{card.name} gets a {kind} counter" if count == 1
        else f"{card.name} gets {count} {kind} counters"
    )
    return True, "resolved"


@effect_handler("add_pt_counters_to_attached")
def add_pt_counters_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever enchanted creature becomes tapped, put a -0/-2 counter on it."
    (Spirit Shackle.)

    The recipient is the permanent this Aura is attached to — no target was
    chosen, because an Aura's effect on its own host never offers one — and the
    counter's kind is payload, so any CR 122.1a pair the grammar reads lands
    here without a second handler.

    Through ``place_pt_counters``: a counter placed by poking the P/T channels
    is a counter no sweep can find, which is what Unstable Mutation's upkeep
    pass did under a comment promising that 704.5q applied to it.
    """
    attached = attached_host(game, context.source_permanent)
    if attached is None:
        return True, "resolved"
    # The host's seat, recorded for the sentences behind this step: "…deals
    # damage … to **its controller**", "…destroy **that creature**" (Consuming
    # Ferocity). The same record ``destroy_attached_permanent`` writes for
    # Orcish Mine, and written *before* anything else for that handler's
    # reason — CR 608.2h's last-known information, so a host that leaves
    # between the two steps still supplies the seat the sentence names.
    seat = game.controller_index_of(attached)
    if seat is not None:
        context.results[ATTACHED_PERMANENT_CONTROLLER] = seat
    kind = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    placed = game.place_pt_counters(attached, kind, count)
    if placed:
        game.log.append(
            f"{context.card.name}: {attached.card.name} gets "
            + (f"a {kind} counter" if placed == 1 else f"{placed} {kind} counters")
        )
    return True, "resolved"


@effect_handler("add_counter_to_bound_permanent")
def add_counter_to_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…at the beginning of each of your draw steps, put a -1/-1 counter on
    **that creature**." (Giant Oyster.)

    The counter's home is the object the *creating* ability bound (CR 603.7c),
    carried by id in the delayed trigger's context — never a pick. Its own kind
    beside ``add_counter_to_target`` for ``destroy_bound_permanent``'s reason:
    routed through the targeted placement, ``engine/targeting.py`` would raise a
    picker for a choice CR 603.3d says was never offered, and the handler would
    then put the counter on whichever permanent the resolution context happened
    to carry.

    Through ``Game.place_pt_counters``, the one placement seam, so the P/T
    channel and the counter record cannot drift and the CR 704.5q annihilation
    sweep has a counter to find.

    A creature already gone takes no counter, which is CR 608.2b doing as much
    as it can rather than a failure — and a repeating ability keeps waiting,
    because whether it is still armed is its duration's question, not this
    one's.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    kind = str(instruction.payload.get("counter", "+1/+1"))
    how_many = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if how_many <= 0:
        return True, "resolved"
    game.place_pt_counters(victim, kind, how_many)
    game.log.append(
        f"{victim.card.name} gets {how_many} {kind} counter(s) "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("add_counter_to_target")
def add_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on target creature", and on *each of up to N* target
    creatures.

    The kind Dwarven Weaponsmith's hook has always emitted (it resolved to
    nothing before this handler existed) and the grammar now lowers to as well.
    How many targets it takes is payload rather than a second instruction kind,
    because the effect is identical and only the count differs — the same reason
    a combat restriction carries its land type as data.

    The two counts take different resolvers on purpose. One target falls back to
    scanning when the chosen one is gone, which is the behaviour every
    single-target handler in the engine has; several are resolved strictly, so a
    dead target is dropped (CR 608.2b) rather than replaced by whichever creature
    the scan reached first — twice, if two slots decayed.
    """
    card = context.card
    targets = instruction.payload.get("targets") or {}
    maximum = targets.get("count") if isinstance(targets, dict) else None
    # Which CR 122.1a counter this is. Absent on every payload written before
    # Lesser Werewolf, and those all mean the one kind this handler used to
    # place — so the default is the whole of the compatibility, and a card
    # printing "-0/-1" is this instruction with a different word in it.
    kind = str(instruction.payload.get("counter", "+1/+1"))
    # "Put **X** +0/+1 counters on target creature." (Living Armor.) How many of
    # that kind, resolved through the same `context.x_value` every other amount
    # reads — absent on every payload written before it, and 1 is what those
    # have always meant.
    how_many = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if how_many <= 0:
        # A where-clause can define an X of zero (a creature with mana value 0),
        # and CR 122.1 places no counters then. Logged as a resolution rather
        # than a miss: the ability did what it said.
        how_many = 0

    # "Return target creature card from your graveyard to the battlefield. Put
    # a +2/+2 counter on **that creature** …" (Soul Exchange.) No target was
    # chosen either: the ability's target is a *card in a graveyard*, and the
    # permanent this names did not exist when it was announced. So the
    # placement reads what the reanimation recorded, by id — the same
    # ``permanents_from`` channel ``grant_target_ability_text`` reads, because
    # the question is the same one.
    #
    # An empty record is a legal outcome (nothing came back), not an error.
    #
    # **The channel is a sequence, and that is now the channel's own answer.**
    # This handler used to normalise here and say so, calling itself "the local
    # half of a wider question"; the question is settled in
    # ``_targets.recorded_permanent_ids``, which every reader of
    # ``permanents_from`` in the engine now goes through — a producer writing a
    # bare id (a choose-one prompt: Thelon's Chant, Tourach's Chant) and one
    # writing a list (a reanimation, which could return several) reach every
    # reader as the same shape.
    #
    # "…put a +1/+1 counter on **the first creature**" (Infinite Authority) and
    # the chosen-creature toll above used to have a **second, unreachable**
    # block below this one, asking the same key again with the scalar reading:
    # dead the moment this branch grew its `return`, and the second copy of the
    # fact this comment is about.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        placed_on = 0
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            creature = game.permanent_by_id(permanent_id)
            if creature is None:
                # It left between the two steps of one resolution; a returning
                # permanent is a new object (CR 400.7) and is not this one.
                continue
            game.place_pt_counters(creature, kind, how_many)
            placed_on += 1
            game.log.append(
                f"{creature.card.name} gets {how_many} {kind} counter(s) "
                f"({card.name})"
            )
        if not placed_on:
            game.log.append(f"{card.name}: nothing was left to put a counter on")
        return True, "resolved"

    if instruction.payload.get("on_block_pair"):
        # "Whenever this creature becomes blocked by a creature, put a -1/-1
        # counter on **that creature**." (Quagmire Lamprey.) The other half of
        # the block the trigger froze — nothing was chosen (CR 601.2c announces
        # targets when the ability goes on the stack, and on the *blocks* half
        # the stack item's target is the blocking creature itself), so the
        # object is read through the one function that knows how each of the two
        # fire sites binds it. The named-counter handler beside this one reads
        # the same key for the same printed pronoun.
        from ._targets import block_pair_permanents

        wanted = instruction.payload.get("filter") or {}
        creature = next(
            (
                perm for perm in block_pair_permanents(game, context)
                if game.is_on_battlefield(perm)
                and (not wanted or permanent_matches_filter(perm, wanted))
            ),
            None,
        )
        if creature is None:
            game.log.append(f"{card.name}: the creature it names is gone")
            return True, "resolved"
        game.place_pt_counters(creature, kind, how_many)
        game.log.append(
            f"{creature.card.name} gets {how_many} {kind} counter(s) ({card.name})"
        )
        return True, "resolved"

    pair_member = instruction.payload.get("pair_member")
    if pair_member:
        bound = (context.trigger_context or {}).get(
            instruction.payload.get("produced_by")
        ) or {}
        creature = game.permanent_by_id(bound.get("own_id"))
        if creature is None:
            game.log.append(f"{card.name}: the creature it names is gone")
            return True, "no target"
        game.place_pt_counters(creature, kind)
        game.log.append(f"{creature.card.name} gets a {kind} counter ({card.name})")
        return True, "resolved"

    if isinstance(targets, dict) and targets.get("kind") == "divided":
        # "Distribute X +1/+1 counters among any number of target creatures."
        # (Spoils of War.) CR 601.2d's counter half: the caster announced how
        # many go where as part of casting, and the shares travel on the same
        # `divided_targets` list a divided damage spell's do — so the division
        # is `engine/divided_damage.py`'s answer here exactly as it is there.
        #
        # A target that has left keeps its share out of the effect (CR 608.2b);
        # nothing redistributes it, which is why the surviving entries are
        # filtered before the division is read rather than after.
        from ..divided_damage import DIVIDED_TARGETS, EVENLY, divide

        announced = list((context.choices or {}).get(DIVIDED_TARGETS) or ())
        if announced:
            # Each entry is turned into a permanent once, through the seam, and
            # carried as the object from there — an index held across the
            # placement loop would address the wrong creature the moment
            # anything left.
            # By id, not by slot: an index announced under CR 601.2c names
            # whoever holds that slot at *resolution*, and anything leaving
            # renumbers the rest -- so the counters announced against a creature
            # that left were placed on the one that slid into its place.
            chosen_entries = [
                (entry, creature)
                for entry in announced
                for creature in (divided_target_permanent(game, entry),)
                if creature is not None
            ]
            if not chosen_entries:
                # Every announced target has left. CR 608.2b, and the spell
                # still resolves — `illegal_targets_refusal` declines to answer
                # "every target is illegal" for a divided spell, because a
                # player's face reaches the stack item through the same field a
                # permanent's seat does.
                game.log.append(
                    f"{card.name}: every creature it named has left "
                    f"the battlefield (608.2b)"
                )
                return True, "resolved"
            placements = [
                (creature, share)
                for (_entry, creature), (_seat, _index, share) in zip(
                    chosen_entries,
                    divide(
                        how_many,
                        [entry for entry, _creature in chosen_entries],
                        division=targets.get("division", EVENLY),
                    ),
                )
            ]
        else:
            # **No division was announced at all**, which is not the same
            # question and used to be answered as though it were: the branch
            # logged "no creatures were given counters" and reported itself
            # resolved, so Spoils of War, Contagion and Bounty of the Hunt did
            # nothing whenever the caster reached the engine through its older
            # single-target channel — every AI cast, every scripted duel.
            #
            # The named target takes the whole amount, which CR 601.2d allows
            # (one target, receiving all of it) and which is exactly what the
            # divided *damage* twin's fall-through has always done. Announcing
            # nothing at all is refused one step earlier now, at CR 601.2c, so
            # what reaches here is a caster who named a target the older way.
            #
            # No fallback scan: a named creature that has left takes nothing
            # (CR 608.2b), rather than the counters landing on whichever
            # creature a scan reached first — which for a `+1/+1` distribution
            # could be the opponent's.
            filters = targets.get("filter") or {}
            creature = resolve_target_permanent(
                game, context,
                predicate=lambda perm: (
                    perm.is_creature and permanent_matches_filter(perm, filters)
                ),
                fallback_on_invalid_choice=False,
            )
            if creature is None:
                game.log.append(f"{card.name}: no valid creature target")
                return True, "resolved"
            placements = [(creature, how_many)]
        placed_total = 0
        for creature, share in placements:
            if share <= 0:
                continue
            game.place_pt_counters(creature, kind, share)
            placed_total += share
            # "**For each +1/+1 counter you put on a creature this way,** …"
            # (Bounty of the Hunt.) One entry per *counter*, not per creature:
            # a creature given two is named twice and the sentence behind this
            # runs twice about it. Written here because this is the only step
            # that knows the division — the caster announced it as the spell was
            # cast, and a creature's counters afterwards say nothing about which
            # of them this spell put there.
            context.results.setdefault(COUNTERS_PLACED_THIS_WAY, []).extend(
                [creature] * share
            )
            game.log.append(
                f"{creature.card.name} gets {share} {kind} counter(s) ({card.name})"
            )
        if placed_total == 0:
            game.log.append(f"{card.name}: no creatures were given counters")
        return True, "resolved"

    if isinstance(maximum, int) and maximum > 1:
        filters = targets.get("filter") or {}
        # The filter decides which permanents qualify, including "you control" —
        # asking it rather than assuming the caster's side is what keeps
        # "up to two target creatures" (Basri's Aegis, either side) and "up to
        # two other target creatures you control" (Basri's Acolyte) one handler.
        source = context.source_permanent

        def eligible(perm) -> bool:
            if not permanent_matches_filter(perm, filters):
                return False
            # "other" (CR 109.5's exclusion of the source) and "you control" are
            # both outside permanent_matches_filter's vocabulary — it answers
            # about a permanent alone, and these two need the source and the
            # board — so they are asked here rather than widened into it.
            if filters.get("exclude_self") and perm is source:
                return False
            if filters.get("controller") == "you" and not game.controls(context.caster, perm):
                return False
            return True

        chosen = resolve_target_permanents(game, context, predicate=eligible)
        if not chosen:
            # "Up to two" may legally name none, and every named target may have
            # become illegal since (CR 608.2b) — both resolve to nothing here.
            game.log.append(f"{card.name}: no creatures were given counters")
            return True, "resolved"
        for creature in chosen[:maximum]:
            game.place_pt_counters(creature, kind)
            game.log.append(f"{creature.card.name} gets a {kind} counter ({card.name})")
        return True, "resolved"

    filters = instruction.payload.get("targets", {}).get("filter") or {}

    source = context.source_permanent
    in_combat_only = bool(instruction.payload.get("in_combat_with_source"))
    # "…on target creature **that attacked you this turn**" (Jabari's
    # Influence). A record about a *seat*, which the pure matcher below cannot
    # answer — so it rides the instruction like the in-combat relation above
    # and is re-asked here, through the one reader of what a printed noun
    # phrase means. CR 608.2b asks a target's legality again at resolution, and
    # the record outlives combat, so the question is still answerable.
    attacked_you_only = bool(instruction.payload.get("attacked_you_this_turn"))
    from ..subject_filters import subject_matches as _subject_matches

    def counter_target_legal(perm) -> bool:
        # "target creature with a +1/+1 counter on it" (Tempered Veteran): the
        # counter restriction is enforced at resolution too, so the fallback
        # scan can never land on a counterless creature.
        #
        # The seat and identity questions are asked here too, which they were
        # not — the several-target branch fifty lines above asks all three, and
        # the two branches of one handler disagreeing is how Pridemalkin,
        # Invigorating Surge and Basri's Lieutenant all put their "+1/+1 counter
        # on target creature **you control**" onto an opponent's creature.
        if not perm.is_creature or not permanent_matches_filter(perm, filters):
            return False
        # "…blocking or blocked by this creature" (Lesser Werewolf). The
        # relation rides the instruction rather than the filter — no read of the
        # candidate alone can answer it — and is re-checked at resolution as
        # well as at activation, because CR 608.2b asks a target's legality
        # again when the ability resolves.
        if in_combat_only and (
            source is None
            or not any(perm is other for other in game.creatures_in_combat_with(source))
        ):
            return False
        if attacked_you_only and not _subject_matches(
            game, perm, {"attacked_you_this_turn": True},
            observer=game.players.index(context.caster),
        ):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    target_creature = resolve_target_permanent(
        game, context, predicate=counter_target_legal,
        # "…on target creature **blocking or blocked by this creature**"
        # (Lesser Werewolf). A relation the fallback scan cannot re-derive from
        # the filter, so a chosen creature that has left combat makes the
        # ability do nothing (CR 608.2b) rather than land on a bystander.
        fallback_on_invalid_choice=not in_combat_only,
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    if how_many:
        game.place_pt_counters(target_creature, kind, how_many)
        game.log.append(
            f"{target_creature.card.name} gets a {kind} counter ({card.name})"
            if how_many == 1
            else f"{target_creature.card.name} gets {how_many} {kind} counters "
                 f"({card.name})"
        )
    else:
        game.log.append(f"{card.name}: no counters to place")
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) Read *after* the placement, so the one just put down
    # is doubled too — and placed through the same seam, so a Conclave Mentor
    # raises the doubling exactly as it raised the first counter (CR 614).
    if instruction.payload.get("then_double"):
        existing = int(target_creature.metadata.get("plus_counters", 0))
        if existing:
            game.place_plus1_counters(target_creature, existing)
            game.log.append(
                f"{target_creature.card.name}'s +1/+1 counters doubled to "
                f"{target_creature.metadata.get('plus_counters', 0)} ({card.name})"
            )
    return True, "resolved"


@effect_handler("add_counter_to_each_matching")
def add_counter_to_each_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on **each creature you control**" (Basri's
    Solidarity); "put a -1/-1 counter on **each creature that player
    controls**" (Misfortune).

    One handler for both, because the effect is one effect and the printed noun
    phrase is the only difference — which is exactly what a filter payload is
    for. It replaced ``add_counter_to_each_you_control``, a kind whose *name*
    was the scope: a second kind beside it would have been one effect with two
    spellings, and the alternative — passing "that player" to something called
    ``…_you_control`` — is a name that lies.

    The board is read here, as the effect resolves (CR 611.2c), through the
    control seam so a borrowed creature counts and a lost one does not.

    "**That player** controls" is not a seat any read of the board can make —
    ``subject_matches`` refuses it outright and says why — so it is stripped
    from the filter and asked as its own question, of the seat the announcement
    froze (CR 700.2e for a mode an opponent chose, CR 603.10 for a trigger).
    An unresolvable seat **ends** the effect rather than dropping the word: a
    dropped scope on a -1/-1 sweep is not a card that does less, it is one that
    shrinks the caster's own board.
    """
    from ..subject_filters import subject_matches

    card = context.card
    caster = context.caster
    kind = instruction.payload.get("counter", "+1/+1")
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    filters = dict(instruction.payload.get("filter") or {})
    scoped_seat: int | None = None
    if filters.get("controller") == "that_player":
        scoped_seat = frozen_that_player_seat(game, context)
        if scoped_seat is None:
            game.log.append(f"{card.name}: no player for 'that player' to name")
            return True, "resolved"
        del filters["controller"]
    # "…each artifact **target opponent** controls" (Corrosion). The same shape
    # one branch up, and now the same answer: the seat is the one the
    # announcement chose, read off ``context.target`` exactly as
    # ``deal_damage_each_matching`` reads Simoon's. The two sentences differ
    # only in the verb, so a second way of finding the player would be one
    # phrase with two readings.
    #
    # This used to call ``announced_opponent_seat``, which guessed the seat from
    # there being exactly one opponent and refused at three — a placeholder for
    # the announcement, because a *trigger* announced no targets. It does now
    # (CR 603.3d, ``_choose_trigger_targets``), so the placeholder is gone and
    # the card works at any number of seats.
    elif filters.get("controller") in ("target_opponent", "target_player"):
        scoped_seat = (
            game.players.index(context.target)
            if context.target is not None and context.target in game.players
            else None
        )
        if scoped_seat is None:
            game.log.append(
                f"{card.name}: no announced opponent for 'target opponent' to name"
            )
            return True, "resolved"
        del filters["controller"]
    observer = game.players.index(caster) if caster in game.players else None
    source = context.source_permanent
    touched: list[Permanent] = []
    for perm in game.all_permanents():
        if scoped_seat is not None and game.controller_index_of(perm) != scoped_seat:
            continue
        if not subject_matches(
            game, perm, filters, observer=observer, source=source
        ):
            continue
        touched.append(perm)
    # Placed after the scan, not during it: `place_pt_counters` runs the CR 614
    # replacements for a +1/+1 counter, and a replacement that moved a creature
    # would renumber a battlefield this loop was still walking.
    #
    # A **named** counter (Corrosion's rust) goes through the named-counter
    # module instead, which is the whole difference between the two: CR 122.1a's
    # P/T counters change a creature's characteristics and run replacements,
    # where a rust counter is a marker nothing derives anything from until
    # another sentence counts it. One handler for both, because the sweep — what
    # the noun phrase names, and the board being read as the effect resolves —
    # is identical, and a second kind beside this one would be one effect with
    # two spellings.
    from ..named_counters import add_counters
    from ..pt import pt_counter_deltas

    for perm in touched:
        if pt_counter_deltas(kind) is not None:
            game.place_pt_counters(perm, kind, count)
        else:
            add_counters(perm, kind, count)
    if touched:
        game.log.append(
            f"{card.name}: {', '.join(p.card.name for p in touched)} "
            f"each got {count} {kind} counter(s)"
        )
    else:
        game.log.append(f"{card.name}: nothing matched, no counters placed")
    return True, "resolved"


@effect_handler("add_corpse_counters_for_each_creature_died")
def add_corpse_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Scavenging Ghoul: "At the beginning of each end step, put a corpse counter on
    this creature for each creature that died this turn." Resolves off the stack; the
    death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    source.metadata["corpse_counters"] = int(source.metadata.get("corpse_counters", 0)) + count
    game.log.append(f"{source.card.name} gets {count} corpse counter(s)")
    return True, "resolved"


@effect_handler("add_named_counter_to_self")
def add_named_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a soul counter on this Equipment." (Malefic Scythe.)

    CR 122.1: a counter with no rules meaning of its own. What it means is
    whatever the card's *other* lines say about it — here, +1/+1 to the equipped
    creature per counter, read by the layer bridge off this same store. The
    counter is the state; the meaning is elsewhere, which is why this handler
    knows nothing but the word.
    """
    from ..named_counters import add_counters

    source = context.source_permanent
    if source is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    # "Put **X** charge counters on this artifact." (Ventifact Bottle.) The
    # cast's announced X, resolved through the same reader every other
    # amount in this engine uses — a printed number passes through it
    # unchanged, so every payload written before this is untouched.
    raw_count = instruction.payload.get("count", 1)
    from_trigger = instruction.payload.get("amount_from_trigger")
    if raw_count == "trigger_count" and from_trigger is not None:
        # "…put **that many** vitality counters on this Aura." (Living
        # Artifact.) The firing event's number, out of the context its fire
        # site froze (CR 603.10) — the same channel `add_counter_to_self` reads
        # for Light of Promise, and never the resolution scratchpad, which for
        # a sentence with no earlier step of its own is a key nothing writes.
        count = int((context.trigger_context or {}).get(str(from_trigger), 0) or 0)
    else:
        count = resolve_amount(raw_count, context.x_value)
    if count <= 0:
        # X may be announced as zero, which CR 122.1 places no counters for.
        return True, "resolved"
    total = add_counters(source, counter, count)
    # The number actually placed, which a counted placement makes more than one
    # ("…for each untapped land that player controls", Mana Cache) — a log that
    # always said "a" would read three counters as one.
    placed = "a" if count == 1 else str(count)
    plural = "" if count == 1 else "s"
    game.log.append(
        f"{source.card.name} gets {placed} {counter} counter{plural} ({total} total)"
    )
    return True, "resolved"


@effect_handler("add_named_counter_to_target")
def add_named_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a matrix counter on target creature." (Life Matrix.)

    The chosen-permanent twin of ``add_named_counter_to_self``, and the same
    ignorance: the counter's word is payload and what it *means* is whatever the
    card's other lines — here, an ability the same sentence grants — say about
    it.

    The printed noun phrase is enforced here as well as at announcement,
    through ``subject_matches`` rather than a property read, because "you
    control" and "another" are questions about the board rather than about the
    card. A picker and a resolution that disagree are a target the player may
    announce and the effect then declines to affect.
    """
    from ..named_counters import add_counters
    from ..subject_filters import subject_matches
    from ._targets import resolve_role_permanent, roles_still_legal

    from ._filters import permanent_matches_filter

    observer = game.players.index(context.caster)
    source = context.source_permanent
    subject_role = instruction.payload.get("subject_role")
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        # "…return it to the battlefield under your control **and put a death
        # counter on it**." (Bogardan Phoenix.) Nothing was targeted: the
        # permanent did not exist when the trigger went on the stack, and the
        # step in front of this one is the only thing that can say which one it
        # is. The same ``permanents_from`` channel the P/T twin reads, through
        # the one reader that decides its arity.
        #
        # Nothing recorded is a legal outcome (the card was no longer in a
        # graveyard), not an error.
        from ._targets import recorded_permanent_ids

        placed = 0
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            returned = game.permanent_by_id(permanent_id)
            if returned is None:
                continue
            counter = str(instruction.payload.get("counter", ""))
            total = add_counters(
                returned,
                counter,
                resolve_amount(instruction.payload.get("count", 1), context.x_value),
            )
            placed += 1
            game.log.append(
                f"{returned.card.name} gets a {counter} counter ({total} total)"
            )
        if not placed:
            game.log.append(
                f"{context.card.name}: nothing was left to put a counter on"
            )
        return True, "resolved"
    if instruction.payload.get("on_event_subject"):
        # "Whenever a permanent becomes tapped, put a wind counter on **it**."
        # (Freyalise's Winds.) Nothing was chosen: the object is the one the
        # event was about, read by the id the announcement froze (CR 603.10) —
        # by resolution the permanent may have moved, and a board search would
        # find a look-alike. Mine Layer's destroy reads the same key.
        subject_id = (context.trigger_context or {}).get(
            "event_subject_permanent_id"
        )
        target = (
            game.permanent_by_id(subject_id) if subject_id is not None else None
        )
        wanted = instruction.payload.get("filter") or {}
        if target is not None and wanted and not permanent_matches_filter(
            target, wanted
        ):
            target = None
    elif instruction.payload.get("on_block_pair"):
        # "Whenever this creature blocks a creature, put four fungus counters
        # on **that creature**." (Mindbender Spores.) The other half of the
        # block the trigger froze, read through the one function that knows how
        # the two fire sites bind it: on the *blocks* half the stack item's
        # target is the blocker itself, so the ordinary target resolution below
        # would put the counters on the source.
        from ._targets import block_pair_permanents

        wanted = instruction.payload.get("filter") or {}
        target = next(
            (
                perm for perm in block_pair_permanents(game, context)
                if game.is_on_battlefield(perm)
                and (not wanted or permanent_matches_filter(perm, wanted))
            ),
            None,
        )
    elif subject_role is not None:
        # "Put X glyph counters on target creature that target Wall blocked
        # this turn" (Glyph of Delusion). Two targets of different kinds, so
        # which one takes the counters is the *role* the lowering named rather
        # than "the first slot" — and both are re-checked here, because CR
        # 608.2b re-checks every target and the relation between them is a
        # record either of them can take off the battlefield with it.
        target = resolve_role_permanent(
            game, context, instruction.payload, subject_role
        )
        if target is not None and not roles_still_legal(
            game, context, instruction.payload, observer=observer
        ):
            game.log.append(
                f"{context.card.name}: its targets are no longer legal"
            )
            return True, "resolved"
    else:
        filters = (instruction.payload.get("targets") or {}).get("filter") or {}
        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, filters, observer=observer, source=source
            ),
        )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent for a counter")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    total = add_counters(target, counter, count)
    game.log.append(
        f"{target.card.name} gets a {counter} counter ({total} total)"
        f" ({context.card.name})"
    )
    return True, "resolved"


#: The scratchpad key the combat-pair counter placement records its recipients
#: under. Spelled here and again in ``grammar/lowering/_events.py`` rather than
#: imported across the seam — a lowering may not reach into the handlers and a
#: handler may not reach into the grammar, and ``lowering/_records._PRODUCES``
#: is the declaration that holds the two spellings together.
PERMANENTS_GIVEN_COUNTERS = "permanents_given_counters"


@effect_handler("add_named_counter_to_creatures_in_combat_with_source")
def add_named_counter_to_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a paralyzation counter on each creature blocking or blocked by this
    creature." (Dread Wight.)

    The set is a combat relation to the ability's own source (CR 509), read
    from the combat maps rather than from any characteristic of the candidates
    — the same set ``destroy_creatures_in_combat_with_source`` (Abu Ja'far) and
    ``grant_keyword_to_creatures_in_combat_with_source`` (Spitting Slug) act on.

    It **records what it marked**, by id, because every sentence after it on
    this card names that set and none of them can work it out again: the
    trigger resolves during the end-of-combat step, and CR 511.2 removes every
    creature from combat as that step ends — so a second reading of the combat
    maps is a set that may already be empty.
    """
    from ..named_counters import add_counters

    # The relation as the fire site froze it (CR 603.10). Dread Wight's trigger
    # resolves in the priority window at the end of the end-of-combat step, and
    # CR 511.2 has taken every creature out of combat by then — so the combat
    # maps are the wrong place to ask, and the capture is the only right one.
    # The live read stays as the fallback for a source asked outside such a
    # trigger, which is what Spitting Slug's keyword twin does all the time.
    source = context.source_permanent
    victims = (context.trigger_context or {}).get("combat_opponents")
    if victims is None:
        if source is None:
            game.log.append(
                f"{context.card.name}: no source to read the combat from"
            )
            context.results[PERMANENTS_GIVEN_COUNTERS] = ()
            return True, "resolved"
        victims = game.creatures_in_combat_with(source)
    counter = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    marked = []
    for perm in victims:
        # A creature that died to combat damage in the same event is gone; a
        # counter on it would be a counter on nothing, and it must not be
        # recorded for the sentences behind this one either.
        if not game.is_on_battlefield(perm):
            continue
        add_counters(perm, counter, count)
        marked.append(perm)
    # Written whether or not anything was marked: the record is what the
    # sentences behind this one read, and an *absent* key is a back-reference
    # with no producer, which is a different thing from a producer that found
    # nobody.
    context.results[PERMANENTS_GIVEN_COUNTERS] = tuple(
        perm.permanent_id for perm in marked
    )
    game.log.append(
        f"{context.card.name}: {len(marked)} creature(s) in combat with it get "
        f"a {counter} counter"
    )
    return True, "resolved"


@effect_handler("add_named_counter_to_attached")
def add_named_counter_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…tap enchanted creature and put X sleep counters on **it**." (Venarian
    Gold.)

    The named-counter twin of ``add_pt_counters_to_attached``: the recipient is
    the permanent this Aura enchants — no target was chosen — and the counter's
    word is payload. The count may be "x", resolved against the cast's X the
    way every amount path resolves it; Venarian Gold's {X} is stamped on the
    Aura at cast and threaded to its enters trigger by the fire site.
    """
    from ..named_counters import add_counters
    from ._targets import attached_host

    attached = attached_host(game, context.source_permanent)
    if attached is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if count <= 0:
        game.log.append(f"{context.card.name}: no {counter} counters to place")
        return True, "resolved"
    total = add_counters(attached, counter, count)
    game.log.append(
        f"{context.card.name}: {attached.card.name} gets "
        + (f"a {counter} counter" if count == 1 else f"{count} {counter} counters")
        + f" ({total} total)"
    )
    return True, "resolved"
