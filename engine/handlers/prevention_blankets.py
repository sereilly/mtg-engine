"""Arming the **blanket** shields (CR 615): "Prevent all damage that would be dealt…".

The handler twin of ``engine/grammar/lowering/_blankets.py``, and cut on that
module's line: a blanket has **no charges**, so it stands for its whole window
however much it absorbs, where ``prevention.py``'s pool is spent by points
(CR 615.7) and its next-instance shield by instances (CR 615.8). Each handler
here arms one for the turn (or the combat) and records what it answers to,
rechecked when the damage would be dealt (CR 615.9): a class of sources
(Al-abara's Carpet, Snag, Prismatic Strands) or of recipients (Sivvi's Ruse);
one object on either end of the event — dealt **to** it (Glyph of Destruction,
Maze of Ith's both ways, Redeem's list, Energy Arc's record), dealt **by** it
(Horn of Deafening, Serene Sunset, Feint with its blockers), dealt by a spell
(Hidden Retreat, Hallow) or by whatever targets it (Silhouette); and a source of
your choice (Samite Ministration, Protective Sphere, Mourner's Shield,
Shieldmage Advocate, Rith's Charm), whose choice is read by
``handlers/prevention.chosen_shield_source`` like every other "source of your
choice".

Split out of ``prevention.py`` at the pre-Fifth-Dawn split round, which kept the
shields that are spent. The table-wide combat blankets (Fog) are ``combat.py``'s,
and the statics a permanent prints are ``engine/prevention/``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..shields import (
    add_shield,
    make_chosen_source_blanket,
    make_recipient_class_shield,
    make_subject_shield,
    make_targeting_source_shield,
)
from ._targets import (bound_permanent, names_a_target_list,
                       recorded_permanent_ids, resolve_target_permanent,
                       resolve_target_permanents)
from .prevention import (_shield_target, chosen_shield_source,
                         default_damage_source)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_chosen_source_blanket_shield")
def grant_chosen_source_blanket_shield(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Samite Ministration: "Prevent all damage that would be dealt to you this
    turn by a source of your choice. Whenever damage from a black or red source
    is prevented this way this turn, you gain that much life." Protective
    Sphere: the same shield, "…that shares a color with the mana spent on this
    activation cost."

    The choice its one-shot siblings make — a permanent on any battlefield or a
    spell on the stack, read by the one reader of the phrase
    (``chosen_shield_source``) — and then the difference: the shield is never
    used up, so it is **never armed without a source**. A seat that named none
    takes the stated default (``default_damage_source``); with no source on the
    table at all the effect does nothing, which is CR 609.7a's own outcome when
    there is nothing to choose.

    ``source_shares_spent_mana_color`` reads CR 107.4's symbols out of the
    payment the activation measured (``choices["mana_spent_for_cost"]``): the
    five colours among them are the property the shield records and rechecks
    (CR 609.7b). Colorless or generic-only payment records none — and then the
    shield is not armed at all, because a property no source can have is a
    shield that prevents nothing ("Colorless mana prevents no damage").
    """
    from ..object_colors import ALL_COLORS

    caster = context.caster
    granted_by = context.card.name if context.card else None
    seat = game.players.index(caster) if caster in game.players else None
    colors: tuple[str, ...] = ()
    if instruction.payload.get("source_shares_exiled_card_color"):
        # "…that shares a color with the exiled card." (Mourner's Shield.) The
        # imprinted card's colours (CR 607.2a), off the source's linked exile —
        # read even once the source has left, the record being the object's.
        # None exiled, or a colourless card: no source can share a colour, and
        # the shield is not armed, the spent-mana branch's reasoning below.
        from ..mana_could_produce import exiled_card_colors

        exiled = exiled_card_colors(game, context.source_permanent)
        colors = tuple(symbol for symbol in ALL_COLORS if symbol in exiled)
        if not colors:
            game.log.append(
                f"{granted_by}: no colored card is exiled with it, so no damage "
                "is prevented"
            )
            return True, "resolved"
    elif instruction.payload.get("source_shares_spent_mana_color"):
        spent = (context.choices or {}).get("mana_spent_for_cost") or {}
        colors = tuple(
            symbol for symbol in ALL_COLORS if int(spent.get(symbol, 0) or 0) > 0
        )
        if not colors:
            game.log.append(
                f"{granted_by}: no colored mana was spent, so no damage is "
                "prevented"
            )
            return True, "resolved"
    chosen = chosen_shield_source(game, context)
    if chosen is None and seat is not None:
        chosen = default_damage_source(game, seat, colors=colors)
    if chosen is None or seat is None:
        game.log.append(f"{granted_by}: no source of damage to choose")
        return True, "resolved"
    # "Prevent all damage that would be dealt to **any target** this turn by a
    # source of your choice." (Shieldmage Advocate.) The shield stands around
    # the announced player or permanent (CR 615.1), read through the reader
    # Circle of Despair's any-target shield uses — a permanent first, then the
    # player — and the source comes from the announcement's own source field,
    # never from the target channel the recipient spent. A recipient gone by
    # now is CR 608.2b's illegal target and is not protected; nothing else is.
    if instruction.payload.get("recipient") == "target":
        # "Any target" admits a player (CR 115.4) — spelled ``any_target`` on
        # the description's quantifier, which survives the description becoming
        # one role of an announcement (its ``kind`` is then ``roles``).
        described = instruction.payload.get("targets") or {}
        protected = _shield_target(
            game, context,
            allow_player=described.get("kind") == "any"
            or described.get("quantifier") == "any_target",
        )
        if protected is None:
            game.log.append(f"{granted_by}: nothing is there to protect")
            return True, "resolved"
        add_shield(protected, make_chosen_source_blanket(
            chosen, seat, granted_by, colors=colors,
        ))
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{granted_by}: all damage {getattr(source_card, 'name', 'a source')} "
            f"would deal to {getattr(protected, 'name', None) or protected.card.name} "
            "this turn will be prevented"
        )
        return True, "resolved"
    # "Prevent all damage a source of your choice would deal this turn."
    # (Rith's Charm.) No recipient printed, so the same shield reaches every
    # recipient that source would damage — the flag, not a second shield.
    any_recipient = bool(instruction.payload.get("any_recipient"))
    add_shield(caster, make_chosen_source_blanket(
        chosen, seat, granted_by, colors=colors,
        rider_colors=tuple(instruction.payload.get("rider_colors") or ()),
        any_recipient=any_recipient,
    ))
    source_card = getattr(chosen, "card", chosen)
    game.log.append(
        f"{caster.name} will prevent all damage "
        f"{getattr(source_card, 'name', 'a source')} would deal "
        f"{'' if any_recipient else 'them '}this turn"
        + (
            (
                " while it shares a color with the exiled card"
                if instruction.payload.get("source_shares_exiled_card_color")
                else " while it shares a color with the mana spent"
            ) + f" ({'/'.join(colors)})"
            if colors else ""
        )
        + f" ({granted_by})"
    )
    return True, "resolved"


@effect_handler("grant_source_class_prevention_shield")
def grant_source_class_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Al-abara's Carpet: "Prevent all damage that would be dealt to you this
    turn by attacking creatures without flying."

    One :class:`~engine.shields.Shield` on the ability's controller carrying the
    printed noun phrase, so this needs no field on ``PlayerState`` and no
    clearing line in a turn step — the sweep reads its ``lifetime``.

    The *set* of sources is deliberately not captured: the phrase is re-matched
    when damage would be dealt (CR 615.9), so a creature that attacks after this
    resolves is covered and one that gains flying in the meantime is not.
    """
    caster = context.caster
    printed = instruction.payload.get("filter")
    seat = game.players.index(caster)
    source_name = context.card.name if context.card else None
    # "Prevent all damage that sources of **the color of your choice** would
    # deal this turn." (Prismatic Strands.) The colour the step in front of
    # this one asked for (CR 608.2d), read out of the scratchpad as every
    # other "of the color of your choice" sweep reads it — and **no colour
    # means no shield**: an unanswered choice read as "no narrowing" would
    # prevent every source's damage. With no noun filter printed ("sources"),
    # the colour is the whole narrowing and answers for spells too.
    colors: tuple[str, ...] = ()
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen_color = context.results.get(str(color_key))
        if not chosen_color:
            game.log.append(
                f"{source_name}: no colour was chosen, so nothing is prevented"
            )
            return True, "resolved"
        colors = (str(chosen_color),)
    described = None if printed is None else dict(printed)
    if described is None and not colors:
        # Every lowering of this kind writes one or the other; a payload with
        # neither would be a shield against every source on the table.
        game.log.append(f"{source_name}: the shield names no sources")
        return True, "resolved"
    # "Prevent all combat damage that would be dealt **by unblocked creatures**
    # this turn." (Snag.) The same shield with no recipient printed: it still
    # hangs off the caster's seat, which is where the cleanup sweep finds it,
    # and `prevention.shields._table_shields` is what lets every damaged object reach
    # it — the arrangement Penance's colour shield already has.
    any_recipient = bool(instruction.payload.get("any_recipient"))
    combat_only = bool(instruction.payload.get("combat_only"))
    add_shield(caster, make_subject_shield(
        described, seat, source_name,
        any_recipient=any_recipient, combat_only=combat_only, colors=colors,
    ))
    damage = "combat damage" if combat_only else "damage"
    if colors and described is None:
        from ..grammar.vocabulary import COLOR_WORDS

        word = next(
            (w for w, symbol in COLOR_WORDS.items() if symbol == colors[0]),
            colors[0],
        )
        game.log.append(
            f"{source_name}: all {damage} {word} sources would deal this turn "
            "is prevented"
        )
    elif any_recipient:
        game.log.append(
            f"{source_name}: all {damage} that would be dealt by matching "
            "sources this turn is prevented"
        )
    else:
        game.log.append(
            f"{caster.name} is shielded this turn from {damage} dealt by "
            f"matching sources ({source_name})"
        )
    return True, "resolved"


@effect_handler("grant_recipient_class_prevention_shield")
def grant_recipient_class_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sivvi's Ruse: "Prevent all damage that would be dealt this turn to
    creatures you control."

    :func:`grant_source_class_prevention_shield`'s sentence with the printed
    phrase on the *recipient* end: one blanket :class:`~engine.shields.Shield`
    on the caster's seat that answers every source and covers whichever
    permanents the phrase names when the damage would be dealt (CR 615.1 —
    shields "aren't locked in ahead of time"). So a creature that enters after
    this resolved is covered, and one an opponent has taken is not.

    The seat is captured for the phrase's sake: "creatures **you** control" is
    the controller of this spell or ability (CR 109.5), even if the board
    changes hands afterwards. The seat itself is *not* shielded — the sentence
    never names it — which is what ``spares_holder`` on the shield says.
    """
    caster = context.caster
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(caster)
    source_name = context.card.name if context.card else None
    add_shield(caster, make_recipient_class_shield(described, seat, source_name))
    game.log.append(
        f"{source_name}: all damage that would be dealt this turn to matching "
        f"permanents is prevented"
    )
    return True, "resolved"


@effect_handler("prevent_damage_to_target_until_eot")
def prevent_damage_to_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all damage that would be dealt to it this turn." (Glyph of
    Destruction.)

    The recipient half of ``prevent_damage_by_target_until_eot``, and a separate
    instruction for the reason that one's docstring gives in the other
    direction: a creature that cannot be hurt and a creature that cannot hurt
    anything are different cards, and one flag covering both would make either
    card's creature untouchable in combat.

    "It" is whatever the sentence in front of this one named — the chosen target
    if the spell chose one, and otherwise the ability's own source. The printed
    pronoun cannot say which, so the referent is resolved here where both are
    known rather than guessed at compile time.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention.shields import (COMBAT_SHIELD_BOTH, COMBAT_SHIELD_TO,
                                      add_directional_shield)

    combat_only = bool(instruction.payload.get("combat_only"))
    # "…dealt **to and dealt by** that creature this turn" (Ebony Horse, Maze
    # of Ith). The printed sentence puts one object on both ends of the event,
    # which is a *direction* the shield reader already answers for — so it is
    # this instruction with one payload key rather than a second kind. The word
    # is what separates Maze of Ith from Awe Strike: one creature is harmless
    # as well as unhurt, the other only unhurt.
    both_ends = bool(instruction.payload.get("to_and_by"))
    direction = COMBAT_SHIELD_BOTH if both_ends else COMBAT_SHIELD_TO
    # "…this turn" (Maze of Ith) or "…**this combat**" (Winter's Chill). The
    # window is payload, so the shield ends where the card says rather than
    # where the only sweep that existed happened to run.
    from ..shields import END_OF_COMBAT, END_OF_TURN

    lifetime = (
        END_OF_COMBAT
        if instruction.payload.get("duration") == "end_of_combat"
        else END_OF_TURN
    )

    def arm(permanent) -> None:
        add_directional_shield(
            permanent, direction, combat_only=combat_only, lifetime=lifetime,
        )
        game.log.append(
            f"all {'combat ' if combat_only else ''}damage that would be dealt "
            "to " + ("and dealt by " if both_ends else "")
            + f"{permanent.card.name} "
            + ("this combat" if lifetime == END_OF_COMBAT else "this turn")
            + f" is prevented ({context.card.name})"
        )

    # "Untap any number of target creatures. Prevent all combat damage that
    # would be dealt to and dealt by **those creatures** this turn." (Energy
    # Arc.) A *set* rather than one recipient, and the set is whatever an
    # earlier step of this same effect recorded — CR 611.2c fixed it when the
    # effect began, and the record is the only place it can be read from now.
    # The shield is the same shield armed several times, which is what makes
    # this a payload key rather than a second kind.
    #
    # By id, because a permanent may have left in between: a returning one is a
    # new object (CR 400.7) that this effect never named, so it is simply not
    # shielded. An empty record is a legal outcome — the spell may name no
    # targets at all — not an error.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        recorded = recorded_permanent_ids(context, recorded_key)
        shielded = 0
        for permanent_id in recorded:
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                continue
            arm(permanent)
            shielded += 1
        if not shielded:
            game.log.append(f"{context.card.name}: nothing was left to shield")
        return True, "resolved"
    # "Prevent all damage that would be dealt this turn to **up to two target
    # creatures**." (Redeem.) The same shield armed once per chosen recipient,
    # which is why it is this instruction with a several-target description
    # rather than a second kind — the branch above already arms a set, and the
    # only difference is where the set came from (a record an earlier step
    # wrote, against a list the caster named at announcement).
    #
    # Resolved strictly, never through the singular reader's fallback scan: a
    # per-slot fallback would shield whichever creature the scan reached first
    # for a choice the caster made once, and an empty list is a legal outcome of
    # "up to two" rather than an error (CR 601.2c, CR 608.2b).
    if names_a_target_list(instruction):
        chosen = resolve_target_permanents(
            game, context, predicate=lambda p: p.is_creature,
        )
        for permanent in chosen:
            arm(permanent)
        if not chosen:
            game.log.append(f"{context.card.name}: no creature to shield")
        return True, "resolved"
    if instruction.payload.get("on_source"):
        # "{U}: Prevent all combat damage that would be dealt to and dealt by
        # **this creature** this turn." (Urborg Phantom.) The ability's own
        # source, named rather than chosen — read here instead of through the
        # bound resolution below, whose fallback would shield whichever
        # creature its scan reached first. The twin of the same key on
        # ``prevent_damage_by_target_until_eot``, and it ends the same way: a
        # source that has already left takes no shield and says so (CR 608.2b).
        perm = context.source_permanent
        if perm is None or not game.is_on_battlefield(perm):
            game.log.append(
                f"{context.card.name}: its source is gone, nothing is shielded"
            )
            return True, "resolved"
        arm(perm)
        return True, "resolved"
    # Through the innermost binding, so a shield printed inside a loop is armed
    # on the creature the iteration is on rather than on the first of the
    # resolution's targets (Winter's Chill). Outside a loop `bound_permanent`
    # *is* the target resolution this line has always done.
    perm = bound_permanent(game, context, predicate=lambda p: p.is_creature)
    if perm is None:
        perm = context.source_permanent
    if perm is None:
        game.log.append(f"{context.card.name}: no permanent to shield")
        return True, "resolved"
    arm(perm)
    return True, "resolved"


@effect_handler("prevent_damage_by_target_spell_until_eot")
def prevent_damage_by_target_spell_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Hidden Retreat: "Put a card from your hand on top of your library:
    Prevent all damage that would be dealt by target instant or sorcery spell
    this turn."

    The shield hangs off the **stack item**, not off a recipient and not off the
    card, and that is the whole of what makes this card possible — the exact
    reasoning Reverberation's redirect gives one family over. A spell's damage
    source is its printed ``CardDefinition`` (CR 120.7), one object per card and
    handed out once per copy by the deck builder, so a shield matching on the
    source would silence a *second* copy too. A ``StackItem`` is one object per
    cast, and ``prevention.shields._resolving_object_shields`` is where the damage paths
    reach it.

    The chosen spell's type is re-checked here rather than trusted from the
    activation: CR 608.2b asks whether the target is still legal when the
    ability resolves, and a spell that has changed type in between is one this
    card no longer names.
    """
    from ..shields import make_resolving_object_shield

    item = context.stack_target
    card_name = getattr(context.card, "name", "")
    if item is None or not any(entry is item for entry in game.stack):
        game.log.append(
            f"{card_name}: the spell it named is no longer on the stack"
        )
        return True, "resolved"
    wanted = instruction.payload.get("card_types") or ()
    if wanted and getattr(item.card, "primary_type", None) not in wanted:
        game.log.append(
            f"{card_name}: {item.card.name} is no longer the "
            f"{'/'.join(str(t) for t in wanted)} spell it named"
        )
        return True, "resolved"
    # Hallow's "You gain life equal to the damage prevented this way" pays the
    # seat that cast it (CR 109.5), captured now.
    payee = game.players.index(context.caster) if instruction.payload.get("rider") else None
    add_shield(item, make_resolving_object_shield(item.card, card_name or None, payee_seat=payee))
    game.log.append(
        f"{card_name}: damage {item.card.name} would deal this turn is prevented"
    )
    return True, "resolved"


@effect_handler("prevent_damage_by_target_until_eot")
def prevent_damage_by_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all [combat] damage that would be dealt by target creature this
    turn." (Horn of Deafening, Lady Evangela, Kry Shield.)

    The printed word "combat" is payload, not a second kind: with it the shield
    sees combat damage alone, without it (Kry Shield) it sees the creature's
    ping abilities too. Dropping it would make Horn of Deafening the wider card
    it is not.

    A shield on the damage's **source**, not on a recipient: the creature is
    still perfectly able to be dealt combat damage and to die to it. That
    direction is what the marker carries, and it is why this is not Ebony
    Horse's two-way flag with a different name — folding them together would
    make every creature either card touches unkillable in combat.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention.shields import COMBAT_SHIELD_BY, add_directional_shield

    combat_only = bool(instruction.payload.get("combat_only"))
    if names_a_target_list(instruction):
        # "Prevent all combat damage **X target creatures** would deal this
        # turn." (Serene Sunset.) The same shield armed once per chosen
        # source — the recipient half's Redeem branch on this end of the
        # event, and resolved the same strict way: each creature the caster
        # named that is still a legal target (CR 608.2b), never a fallback
        # scan, and an empty list (X = 0) is a legal outcome rather than an
        # error.
        chosen = resolve_target_permanents(
            game, context, predicate=lambda p: p.is_creature,
        )
        for creature in chosen:
            add_directional_shield(creature, COMBAT_SHIELD_BY, combat_only=combat_only)
            game.log.append(
                f"all {'combat ' if combat_only else ''}damage {creature.card.name} "
                f"would deal this turn is prevented ({context.card.name})"
            )
        if not chosen:
            game.log.append(f"{context.card.name}: no creature to silence")
        return True, "resolved"
    # Through the innermost binding, exactly as the recipient half above does
    # and for its reason: "**For each attacking red creature,** prevent all
    # combat damage that would be dealt by **that creature** this turn"
    # (Heroism) names a different creature each time round, and the sentence
    # chooses no target at all — so a read of the resolution's targets would
    # shield whichever creature a fallback happened to find.
    if instruction.payload.get("on_source"):
        # "…dealt by **this creature** this turn" (Mtenda Lion). The ability's
        # own source, named rather than chosen — read here instead of through
        # the bound resolution below, whose fallback is every battlefield and
        # would silence whichever creature its scan reached first. A source
        # that has already left takes no shield and says so, which is CR 608.2b
        # doing as much as it can.
        perm = context.source_permanent
        if perm is None or not game.is_on_battlefield(perm):
            game.log.append(f"{context.card.name}: its source is gone, nothing is silenced")
            return True, "resolved"
    elif instruction.payload.get("bound_or_source"):
        # "…prevent all combat damage that would be dealt by **it** this turn."
        # (Ignoble Soldier.) The pronoun names whatever the sentence in front of
        # it named: the chosen target if the effect chose one, and otherwise the
        # ability's own permanent. Only the resolution knows which, which is why
        # the instruction names neither — the reading the recipient half of this
        # pair has always taken for the same pronoun.
        #
        # With the fallback scan **off**, unlike the bound-object arm below: a
        # targetless trigger has no announced choice at all, so the scan would
        # be the whole battlefield and would silence whichever creature it
        # reached first instead of the creature that became blocked.
        perm = bound_permanent(
            game, context, predicate=lambda p: p.is_creature, fallback_players=(),
        )
        if perm is None:
            perm = context.source_permanent
    else:
        perm = bound_permanent(
            game, context,
            predicate=lambda p: p.is_creature,
            fallback_players=tuple(game.players),
        )
    if perm is None:
        game.log.append(f"{context.card.name}: no creature to silence")
        return True, "resolved"
    shielded = [perm]
    # "…by that creature **and each creature blocking it**." (Feint.) The second
    # printed source is a set named by a combat relation to the first, so it is
    # read from the combat maps at resolution rather than from any description:
    # a creature that started blocking after the spell was cast is one of them
    # (CR 611.2c fixes the set when the effect begins, which is now), and a
    # blocker of a *different* attacker is not.
    if instruction.payload.get("also_blocking_target"):
        for blocker in game.creatures_blocking(perm):
            if not any(blocker is already for already in shielded):
                shielded.append(blocker)
    for creature in shielded:
        add_directional_shield(creature, COMBAT_SHIELD_BY, combat_only=combat_only)
        game.log.append(
            f"all {'combat ' if combat_only else ''}damage {creature.card.name} "
            f"would deal this turn is prevented ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("prevent_damage_from_targeting_sources_until_eot")
def prevent_damage_from_targeting_sources_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Silhouette: "Choose target creature. If a spell or ability that targets
    that creature would cause a source to deal damage to that creature this
    turn, prevent that damage."

    The spell's own chosen creature (CR 601.2c — the first sentence is the
    choosing) carries the shield, so nothing here re-reads the text or picks a
    creature of its own. With the target gone the spell simply does nothing,
    which is CR 608.2b rather than a failure.
    """
    target = resolve_target_permanent(game, context, fallback_players=())
    if target is None:
        game.log.append(f"{context.card.name}: its target is gone")
        return True, "resolved"
    add_shield(
        target,
        make_targeting_source_shield(context.card.name if context.card else None),
    )
    game.log.append(
        f"{target.card.name} is shielded from spells and abilities that target it"
    )
    return True, "resolved"
