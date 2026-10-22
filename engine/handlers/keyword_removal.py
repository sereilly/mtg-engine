"""A keyword or ability **lost** by a resolving effect (CR 613.1f, layer 6):
"loses flying until end of turn", "creatures you control lose …", "loses all
abilities" (Humble), and a printed ability line struck from the source.

The handler twin of ``engine/grammar/lowering/keyword_removal.py``. A removal
is a layer-6 effect with its own timestamp (``engine.keywords.remove_keyword``),
so it beats an older grant and loses to a newer one, and it expires with
everything else that lasts until end of turn. How long it lasts and whether
its target still answers the printed noun phrase are the grants' own two
readers (``keywords.grant_lifetime``, ``keywords.granted_target``), asked the
same way here.

Split out of ``pump.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..keywords import remove_keyword
from ._targets import block_pair_permanents, resolve_target_permanent
from .keywords import (DURATION_WORDS, grant_lifetime, granted_target,
                       granted_target_legal)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("remove_self_ability_text")
def remove_self_ability_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, this creature loses "Prevent all damage that would be
    dealt to this creature."" (Glittering Lion, Glittering Lynx.)

    ``grant_self_ability_text``'s mirror: the removal is recorded on
    ``keywords.REMOVED_ABILITY_LINES`` with the printed duration, and
    ``Permanent.effective_card`` drops the sentence until the sweep that
    duration names gives it back (CR 613.1f). Nothing here knows what the line
    did — the static shield the Lion's text describes is re-derived from that
    text on every damage event, so taking the text away is the whole effect.
    """
    from ..keywords import remove_ability_line

    source_permanent = context.source_permanent
    if source_permanent is None or not game.is_on_battlefield(source_permanent):
        game.log.append(f"{context.card.name}: it is no longer on the battlefield")
        return True, "resolved"
    lifetime = grant_lifetime(game, instruction, context)
    texts = tuple(instruction.payload.get("abilities") or ())
    for text in texts:
        remove_ability_line(source_permanent, text, **lifetime)
    game._recompute_continuous_effects()
    if texts:
        game.log.append(
            f"{source_permanent.card.name} loses "
            + " and ".join(f'"{text}"' for text in texts)
            + DURATION_WORDS.get(lifetime["duration"], "")
            + f" ({context.card.name})"
        )
    return True, "resolved"


def _remove_one_keyword(permanent, keyword: str, *, duration=None, seat=None) -> None:
    """Take one keyword ability away, on the channel its reader looks at.

    The exact mirror of :func:`_grant_one_keyword`, and it has to be: layer 6's
    word set is not where a **line-derived** ability lives (CR 702.23a, CR
    702.25a — the compiler builds the trigger out of the printed keyword line),
    so ``remove_keyword`` there would record a removal and take nothing away.
    ``remove_ability_keyword`` strikes the keyword out of the line instead, and
    ``Permanent.effective_card`` is what applies it.

    Every removal handler in this file routes through here, so which channel a
    word goes on is decided once — the granting side learned that lesson first,
    and a second copy of the decision is how a grant and a removal come to
    disagree about what a permanent says.
    """
    from ..keywords import (LINE_DERIVED_KEYWORDS, keyword_ability_name,
                            remove_ability_keyword)

    if keyword_ability_name(keyword) in LINE_DERIVED_KEYWORDS:
        remove_ability_keyword(permanent, keyword, duration=duration, seat=seat)
        # …**and** the word, which is the half a line-derived keyword needs
        # twice. Striking the line stops the compiler making the trigger; the
        # word is what the *next* creature's "without flanking" filter asks, and
        # an Aura contributes it to layer 6 directly (Agility grants both, from
        # the attach timestamp). So a removal that only struck the line would
        # take Agility's trigger away and leave its enchanted creature still
        # counting as "with flanking" — the two-representations-one-reader bug
        # this engine keeps finding, in a keyword instead of a zone. Recorded
        # second so CR 613.9's ordering is the ordinary one: this removal's
        # timestamp is later than the attach, so it wins until it expires.
        remove_keyword(permanent, keyword, duration=duration, seat=seat)
        return
    remove_keyword(permanent, keyword, duration=duration, seat=seat)


@effect_handler("remove_target_keyword_until_eot")
def remove_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"It loses indestructible until end of turn." (Soul Sear — the pronoun
    binds the damage sentence's target.) `remove_keyword` puts the removal
    into layer 6, so it beats an older grant by timestamp and expires at
    cleanup with everything else until-end-of-turn."""
    card = context.card
    # **The printed noun phrase, through the reader the grant twin already
    # uses.** This read `predicate=lambda p: True` — "the damage target may be
    # a planeswalker, so no creature predicate" — which is true of Soul Sear
    # and of nothing else that reaches here: the other fifteen printings say
    # "target creature", and an unconditional predicate makes the fallback scan
    # take whatever permanent it reaches first. Reality Anchor stripped shadow
    # from a *Circle of Protection* in an AI game for exactly that reason, the
    # AI having named a player where the spell wants a creature.
    #
    # `granted_target_legal` is the same three questions the grant side asks,
    # and its docstring is this bug found on that side: two handlers for one
    # printed sentence, and the one that kept its own copy was the one that had
    # none. It reads the printed type off the payload, so Soul Sear's
    # planeswalker is still legal and nothing else is.
    target = resolve_target_permanent(
        game, context, predicate=granted_target_legal(game, instruction, context)
    )
    if target is None:
        game.log.append(f"{card.name}: no valid target to strip")
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        _remove_one_keyword(target, keyword, duration="end_of_turn")
    game.log.append(
        f"{target.card.name} loses {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


@effect_handler("remove_target_abilities_until_eot")
def remove_target_abilities_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, target creature **loses all abilities** and has base
    power and toughness 0/1." (Humble; Soul Sculptor prints the clause behind a
    type change.)

    CR 613.1f's blanket removal aimed at one permanent, which is the half of
    that rule the engine had no channel for: Humility and Titania's Song are
    board-wide statics re-derived from a source on every recompute, and there is
    no source here — the spell is in a graveyard the moment it has resolved.

    So the record goes on the creature (``keywords.remove_all_abilities``) and
    ``Permanent.effective_card`` reads it in the same fold that answers the
    static. That is what makes one write reach all four consumers of "what does
    it say?" — the layer-6 keyword set, the activated abilities the picker
    enumerates off the compiled program, the triggered abilities the trigger
    scan reads off the card, and the statics re-derived from its text.

    **Layer 6 is timestamp-ordered (CR 613.3), so an ability granted after this
    survives it**, which is the rule and not an accident of storage: the record
    is a contribution rather than a rewrite, and the fold in ``effective_card``
    applies it before the grants for exactly that reason.

    The printed noun phrase is read through ``granted_target_legal``, the same
    three questions the grant and the keyword removal beside it ask — a
    fallback scan with no predicate is how Reality Anchor stripped shadow from a
    Circle of Protection.
    """
    from ..keywords import remove_all_abilities

    card = context.card
    # Through ``granted_target``, the CR 608.2b resolver, rather than a single
    # pass of the predicate: the removal's own sentence may have changed the
    # target's characteristics one step earlier (Soul Sculptor's type change),
    # and one printed instance of the word "target" is one legality check
    # however many steps the sentence lowers to.
    target = granted_target(game, instruction, context)
    if target is None:
        game.log.append(f"{card.name}: no valid target to strip")
        return True, "resolved"
    # The window is payload, not the kind's name. "Until end of turn" is what
    # Humble prints and what this kind was named for; Soul Sculptor prints one
    # that ends on an **event** instead (CR 611.2a), and the record is what tells
    # the sweep which — so the same instruction covers both and the removal
    # cannot outlive the words that bought it.
    remove_all_abilities(
        target, duration=str(instruction.payload.get("duration") or "end_of_turn")
    )
    # Every characteristic this can move is computed rather than stored, but the
    # derived channels are rebuilt from the board rather than on every read —
    # a lord whose anthem the stripped creature was contributing has to stop
    # contributing it now rather than at the next thing that happens to refresh.
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{target.card.name} loses all abilities ({card.name})"
    )
    return True, "resolved"


@effect_handler("remove_team_keyword_until_eot")
def remove_team_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"All creatures lose flying until end of turn." (Whiteout.)

    The mirror of ``grant_team_keyword_until_eot`` and deliberately its shape:
    the affected set locks in at resolution (CR 611.2c), so this walks the board
    now rather than contributing a derived effect, and the same three payload
    keys say how wide it reaches. ``remove_keyword`` writes into layer 6, so a
    creature granted flying *later* in the turn keeps it — the timestamp
    decides, not this handler.
    """
    from ..subject_filters import subject_matches

    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    described = instruction.payload.get("filter")
    seats = (
        range(len(game.players))
        if instruction.payload.get("every_seat")
        else (caster_index,)
    )
    lifetime = grant_lifetime(game, instruction, context)
    stripped = 0
    for seat in seats:
        for perm in game.controlled_by(seat):
            if not every_permanent and not perm.is_creature:
                continue
            if described and not subject_matches(
                game, perm, described, observer=caster_index,
                source=context.source_permanent,
            ):
                continue
            for keyword in keywords:
                _remove_one_keyword(perm, keyword, **lifetime)
            stripped += 1
    game._recompute_continuous_effects()
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {stripped} {noun} lose {', '.join(keywords)}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("remove_self_keyword")
def remove_self_keyword(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature blocks, it loses defender." (Elder Land Wurm.)

    The durationless mirror of ``remove_target_keyword_until_eot``: one layer-6
    removal on the ability's own source, with no expiry stamped on it, so the
    cleanup sweep leaves it alone and the word stays gone. Losing defender
    mid-combat is exactly why the removal has to be a real layer-6 record
    rather than a printed-keyword edit — the creature is already blocking, and
    every later read of "can it attack" asks the layers.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    keywords = tuple(instruction.payload.get("keywords") or ())
    # "…loses flying **until end of turn**" (Leering Gargoyle, Canopy Dragon).
    # Absent means no expiry, which is what every payload written before this
    # key meant and what Elder Land Wurm's defender loss still means.
    duration = instruction.payload.get("duration")
    for keyword in keywords:
        _remove_one_keyword(source_permanent, keyword, duration=duration)
    game._recompute_continuous_effects()
    game.log.append(
        f"{source_permanent.card.name} loses {' and '.join(keywords)}"
        + (" until end of turn" if duration == "end_of_turn" else "")
    )
    return True, "resolved"


@effect_handler("remove_keyword_from_block_pair")
def remove_keyword_from_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever this creature blocks or becomes blocked by a creature, **that
    creature** loses first strike until end of turn." (Talruum Champion.)

    The exact mirror of ``keywords.grant_keyword_to_block_pair``, and it reads the
    pair through the same ``block_pair_permanents`` — the one function that
    knows the two fire sites bind "that creature" differently. Reaching for the
    stack item's target instead would name the *Champion* on the blocks half of
    the event, which is a card that strips its own first strike and leaves the
    creature it blocked with theirs.

    The removal goes through the same layer-6 seam the grant does
    (``_remove_one_keyword``), so it composes with grants by timestamp
    (CR 613.1f) rather than fighting a flag — which is what makes the interaction
    with the Champion's own printed first strike a rules question the layer
    system answers rather than an ordering this handler has to get right.
    """
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    removed = 0
    for perm in block_pair_permanents(game, context):
        for keyword in keywords:
            _remove_one_keyword(perm, keyword, **lifetime)
        removed += 1
    game._recompute_continuous_effects()
    if not removed:
        game.log.append(f"{context.card.name}: no creature in the block pair")
        return True, "no target"
    game.log.append(
        f"{context.card.name}: {removed} creature(s) lose {', '.join(keywords)}"
    )
    return True, "resolved"


@effect_handler("remove_event_subject_keyword")
def remove_event_subject_keyword(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature attacks you, **it** loses flanking until end of
    turn." (Barbed Foliage.)

    ``remove_target_keyword_until_eot``'s subject read off the *event* instead
    of off a target: the trigger chose nothing, so the object is the one the
    fire site froze (CR 603.10) — by id, because by resolution the attacker may
    have left and a board search would find a look-alike.

    The printed filter is re-checked here rather than trusted from the
    announcement, for the reason every other rebound subject is: the words the
    lowering carried are the words that have to hold when the ability resolves.
    """
    from ..subject_filters import subject_matches

    bound = (context.trigger_context or {}).get("event_subject_permanent_id")
    victim = game.permanent_by_id(bound) if isinstance(bound, int) else None
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    caster_index = game.players.index(context.caster)
    described = instruction.payload.get("filter")
    if described and not subject_matches(
        game, victim, described, observer=caster_index,
        source=context.source_permanent,
    ):
        game.log.append(
            f"{context.card.name}: {victim.card.name} no longer answers the clause"
        )
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    duration = instruction.payload.get("duration")
    for keyword in keywords:
        _remove_one_keyword(victim, keyword, duration=duration)
    game._recompute_continuous_effects()
    game.log.append(
        f"{victim.card.name} loses {' and '.join(keywords)}"
        + (" until end of turn" if duration == "end_of_turn" else "")
        + f" ({context.card.name})"
    )
    return True, "resolved"
