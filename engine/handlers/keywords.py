"""A **keyword or ability granted** by a resolving effect (CR 613.1f, layer 6):
"gains flying until end of turn", "creatures you control gain trample", "that
creature gains "<ability>"", on a target, the source, an Aura's host, a block
pair, the creatures in combat with the source, or every creature a phrase
names.

Two readers every grant shares, because two questions are one each:
:func:`grant_lifetime` (how long the grant lasts — the duration the card
printed, never a blanket "until end of turn") and :func:`granted_target` /
:func:`granted_target_legal` (whether the target the grant was announced at
still answers the printed noun phrase, CR 608.2b). :func:`_grant_one_keyword`
puts one keyword where layer 6 reads it, a protection quality included.

The handler twin of ``engine/grammar/lowering/keywords.py`` and
``granted_abilities.py``. The loss of a keyword or of every ability is
``keyword_removal``'s, which reads the two shared readers from here.

Split out of ``pump.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..combat_assignment import MAY_ASSIGN_AS_UNBLOCKED
from ..destruction_events import mark_delayed_destruction
from ..models import Permanent
from ..keywords import grant_keyword, grant_protection_flag, remove_keyword
from ._amounts import resolve_amount
from ._filters import permanent_matches_filter
from ._targets import (recorded_permanent_ids, bound_permanent,
                       block_pair_permanents, attached_host,
                       resolve_target_permanent, resolve_target_permanents,
                       resolve_target_slots)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_team_keyword_until_eot")
def grant_team_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures you control gain flying until end of turn." (Basri, Devoted
    Paladin's −6.) The affected set locks in at resolution (CR 611.2c), which
    is why this walks the board now instead of contributing a derived buff.

    ``every_permanent`` widens the same grant to the whole board (Heroic
    Intervention's "Permanents you control gain hexproof and indestructible"):
    both keywords are asked of the permanent, not of the creature — hexproof is
    read by ``_can_be_targeted`` and indestructible by ``_is_indestructible``,
    neither of which cares what type it is — so the only thing that changes is
    who is in the loop."""
    from ..subject_filters import subject_matches

    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    # "**Attacking** creatures gain trample until end of turn" (Stampede). Two
    # payload keys the plain "creatures you control" printing does not carry:
    # the narrowing, and the fact that the sentence named no controller at all.
    # Stampede is castable by the *defending* player, so a grant scoped to the
    # caster's board would reach none of the creatures it names.
    described = instruction.payload.get("filter")
    seats = (
        range(len(game.players))
        if instruction.payload.get("every_seat")
        else (caster_index,)
    )
    # "creatures you control **blocking that creature** gain first strike until
    # end of turn" (Tidal Flats). A relation to the object the loop around this
    # sentence bound rather than a characteristic of the blocker, so it is read
    # off the combat maps here — through the one reader of the relation, and
    # once, before the board walk. CR 611.2c: the set is fixed now, so a
    # creature that starts blocking later is not in it.
    blockers: list | None = None
    if instruction.payload.get("blocking_bound_target"):
        blocked = bound_permanent(game, context)
        blockers = list(game.creatures_blocking(blocked)) if blocked is not None else []
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for seat in seats:
        for perm in game.controlled_by(seat):
            if not every_permanent and not perm.is_creature:
                continue
            if blockers is not None and not any(perm is one for one in blockers):
                continue
            # Through the one reader of what a printed noun phrase means, with the
            # caster as observer (CR 109.5), so "attacking" here and "attacking" on
            # the P/T half of the very same sentence are one question.
            if described and not subject_matches(
                game, perm, described, observer=caster_index,
                source=context.source_permanent,
            ):
                continue
            for keyword in keywords:
                # Through the one seam, so a team grant puts a keyword where its
                # reader looks for the same reasons a single-target grant does.
                _grant_one_keyword(game, perm, keyword, context, lifetime)
            granted += 1
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {granted} {noun} gain "
        f"{', '.join(_named_set_keywords(game, keywords, context))}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_keyword_to_block_pair")
def grant_keyword_to_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**that creature** gains first strike until end of turn." (Goblin
    Flotilla.)

    The other half of the block the trigger fired on, resolved by the stable ids
    the fire site recorded (CR 509.3f fixes the set at declaration; an id that
    no longer resolves is a creature that left, and one that returns is a new
    object the sentence never named — CR 400.7).

    ``block_pair_permanents`` is the one reader of that pair, shared with the
    delayed destroy above it, so the two halves of a block are named the same
    way whichever verb the card printed. The grant itself goes through the one
    keyword seam, so it composes with every other layer-6 write by timestamp.
    """
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for perm in block_pair_permanents(game, context):
        for keyword in keywords:
            _grant_one_keyword(game, perm, keyword, context, lifetime)
        granted += 1
    if not granted:
        game.log.append(f"{context.card.name}: no creature in the block pair")
        return True, "no target"
    game.log.append(
        f"{context.card.name}: {granted} creature(s) gain "
        f"{', '.join(_named_keywords(keywords, context))}"
    )
    return True, "resolved"


@effect_handler("grant_keyword_to_creatures_in_combat_with_source")
def grant_keyword_to_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each creature blocking or blocked by this creature gains first strike
    until end of turn." (Spitting Slug.)

    The set is a combat relation to the ability's own source (CR 509), read
    from the combat maps rather than from any characteristic of the candidates —
    which is why this is not the team grant above: that one walks the caster's
    board, and the creatures blocking this one are the opponent's.

    Locked in at resolution (CR 611.2c), like every other sweep here: a creature
    that joins the block afterwards is not one this effect named.
    """
    keywords = tuple(instruction.payload.get("keywords") or ())
    source = context.source_permanent
    if source is None:
        game.log.append(f"{context.card.name}: no source to read the combat from")
        return True, "resolved"
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for perm in game.creatures_in_combat_with(source):
        for keyword in keywords:
            # Through the one seam, so the keyword lands where its reader looks.
            _grant_one_keyword(game, perm, keyword, context, lifetime)
        granted += 1
    game.log.append(
        f"{context.card.name}: {granted} creature(s) in combat with it gain "
        + ", ".join(_named_keywords(keywords, context))
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_team_assign_unblocked_until_eot")
def grant_team_assign_unblocked_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Garruk, Savage Herald's −7: creatures you control gain "You may have
    this creature assign its combat damage as though it weren't blocked" until
    end of turn. The combat damage step reads the flag; cleanup clears it (the
    key is in _EOT_METADATA_KEYS)."""
    caster_index = game.players.index(context.caster)
    granted = 0
    for perm in game.controlled_by(caster_index):
        if perm.is_creature:
            perm.metadata[MAY_ASSIGN_AS_UNBLOCKED] = True
            granted += 1
    game.log.append(
        f"{context.card.name}: {granted} creature(s) may assign combat damage as though unblocked"
    )
    return True, "resolved"


@effect_handler("grant_keyword_to_attached")
def grant_keyword_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…and that creature gains flying." (Cocoon's hatch, bound to the
    enchanted creature.)

    A one-shot grant with no printed duration: CR 611.2c makes it last as long
    as the creature, so it is recorded on the *creature* through the layer-6
    write API — never derived from the Aura, which this same resolution has
    just sacrificed. ``attached_host`` supplies the last-known host for
    exactly that reason (CR 603.10).
    """
    host = attached_host(game, context.source_permanent)
    if host is None:
        game.log.append(f"{context.card.name}: nothing is enchanted to grant to")
        return True, "resolved"
    keyword = str(instruction.payload.get("keyword", ""))
    grant_keyword(host, keyword)
    game._refresh_dynamic_creatures()
    game.log.append(f"{context.card.name}: {host.card.name} gains {keyword}")
    return True, "resolved"


def grant_lifetime(game, instruction, context) -> dict:
    """The lifetime this grant printed, as the keyword arguments
    :func:`engine.keywords.grant_keyword` and ``grant_ability_line`` take.

    One reader for every grant handler, because "how long does this last?" is
    one question and a handler that answered it for itself is what let the
    duration collapse in the first place — every one of them passed
    ``until_eot=True`` whatever the card said.

    A seated duration ("until **your** next upkeep") freezes the seat now:
    CR 109.5 makes it the controller of the *ability*, and by the time the
    sweep runs the affected permanent may be controlled by somebody else — or
    be somewhere else entirely.
    """
    from ..keywords import SEATED_GRANT_DURATIONS

    duration = instruction.payload.get("duration")
    lifetime: dict = {"duration": duration}
    if duration in SEATED_GRANT_DURATIONS:
        lifetime["seat"] = game.players.index(context.caster)
    return lifetime


#: How each grant duration reads in the log, so the message says what the card
#: said rather than what the handler used to assume.
DURATION_WORDS = {
    None: "",
    "end_of_turn": " until end of turn",
    "end_of_combat": " until end of combat",
    "your_next_upkeep": " until their next upkeep",
}


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    lifetime = grant_lifetime(game, instruction, context)
    grant_keyword(source_permanent, "flying", **lifetime)
    game.log.append(
        f"{card.name} gains flying" + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


def granted_target_legal(game, instruction, context, *, characteristics=True):
    """The predicate a "target … gains <keyword>" grant resolves through.

    One reader for the printed noun phrase, because there are two handlers for
    one sentence — ``grant_target_flying_until_eot`` and
    ``grant_target_keyword_until_eot`` — and only the second of them asked. The
    first read **no filter at all**, so five shipped cards handed flying to
    whatever the fallback scan reached first: Chariot of the Sun and Krovikan
    Elementalist ("target creature **you control**") could give it to an
    opponent's creature, and Goblin Kites, Phantasmal Mount ("…**with toughness
    2 or less**") and Whalebone Glider ("…**with power 3 or less**") ignored the
    printed bound entirely. A picker and a resolution that disagree are a target
    the player may announce and the effect then declines to affect.

    The three questions are the split ``add_counter_to_target`` already makes:
    ``permanent_matches_filter`` answers about a permanent alone, so "another"
    (CR 109.5's source exclusion) and "you control" (a seat) are asked here.

    *characteristics* is CR 608.2b's "once", and :func:`granted_target` is the
    only caller that turns it off — see there.
    """
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    source = context.source_permanent
    # The printed **type**, from the same payload the rest of the phrase comes
    # from. It used to be the literal question "is it a creature?", which is
    # what every card reaching this helper prints — until the removal twin
    # started reaching it too: Soul Sear's "target creature **or
    # planeswalker**" lowers `type_filter` as a list, and a hardcoded creature
    # floor would decline the planeswalker half of a card that prints it.
    #
    # A floor at all, rather than leaving it to `permanent_matches_filter`
    # below, because *characteristics* switches that check off for CR 608.2b's
    # second pass — and a pass with no floor would scan every permanent on the
    # board.
    printed = filters.get("type_filter") or "creature"
    wanted = (printed,) if isinstance(printed, str) else tuple(printed)

    def legal(perm) -> bool:
        # The type is a characteristic like any other, and CR 608.2b checks
        # them **once**. So the second pass drops this floor with the rest:
        # "Target creature becomes an enchantment **and** loses all abilities"
        # (Soul Sculptor) is one noun phrase and two lowered steps, and the
        # first step is what stops the target being a creature — re-asking the
        # printed type at the second step found nothing and the card stripped
        # no abilities at all, which is Phantasmal Mount's failure exactly, one
        # characteristic over.
        #
        # Safe because ``characteristics=False`` is only ever asked with the
        # fallback scan switched off (:func:`granted_target`), so a pass with no
        # floor can return the permanent the player announced and nothing else.
        if characteristics and not any(perm.has_type(kind) for kind in wanted):
            return False
        if characteristics and not permanent_matches_filter(perm, filters):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    return legal


def granted_target(game, instruction, context):
    """The creature a "target … gains <keyword>" grant lands on.

    Two resolutions, and the second one is CR 608.2b read as the rule is
    written. The check happens **once**, before the first instruction of the
    resolution runs (608.2c: the controller then follows the instructions in
    the order written), and one printed instance of the word "target" is one
    check however many steps the sentence lowers to. Phantasmal Mount is the
    card that proves it: "target creature you control **with toughness 2 or
    less** gets +1/+1 **and** gains flying until end of turn" is one noun
    phrase and two lowered steps, the pump runs first and takes a 2/2 rider to
    toughness 3, and re-asking the printed bound at the second step finds
    nothing — so the card's only ability would grant flying to nobody, on the
    board it was printed for.

    So the **announced** target is asked for first with the scan switched off,
    in full and then with its characteristics settled; only when neither
    answers does the fallback scan run, with the phrase in full. The order is
    the whole of it: ``pick_target_permanent`` is written "honour the choice,
    else scan", and a chosen creature that fails the predicate falls through to
    a scan — which for Phantasmal Mount found the *Mount itself* (a creature
    its controller controls with toughness 2) and flew that instead of the
    rider. A scan is for a seat that named nothing, never a second opinion
    about a seat that did.

    The seat and the identity are asked every time. Those are not
    characteristics an earlier step of the same resolution changes, and they are
    the half a scan gets wrong — which is how ``grant_target_flying_until_eot``
    used to hand flying to whatever it reached first.
    """
    full = granted_target_legal(game, instruction, context)
    named = resolve_target_permanent(
        game, context, predicate=full, fallback_players=(),
    )
    if named is not None:
        return named
    named = resolve_target_permanent(
        game, context,
        predicate=granted_target_legal(
            game, instruction, context, characteristics=False,
        ),
        fallback_players=(),
    )
    if named is not None:
        return named
    return resolve_target_permanent(game, context, predicate=full)


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_creature = granted_target(game, instruction, context)
    if target_creature is not None:
        lifetime = grant_lifetime(game, instruction, context)
        grant_keyword(target_creature, "flying", **lifetime)
        game.log.append(
            f"{target_creature.card.name} gains flying"
            + DURATION_WORDS.get(lifetime["duration"], "")
            + f" from {card.name}"
        )
    return True, "resolved"


@effect_handler("grant_target_keyword_until_eot")
def grant_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature gains <keyword(s)> until end of turn." The payload
    carries the words; the lowering admits only implemented keywords, so a
    grant here always grants behaviour that exists.

    The printed noun phrase is enforced here as well as at announcement. It was
    not: this handler resolved with the default "is it a creature?" predicate and
    read no filter at all, so Ranger's Guile's "target creature **you control**"
    handed +1/+1 and hexproof to an opponent's creature, and Selfless Savior's
    "**another**" excluded nothing. The same three questions
    ``add_counter_to_target``'s several-target branch already asks, for the same
    reason — a picker and a resolution that disagree are a target the player may
    announce and the effect then declines to affect.
    """
    card = context.card
    # "…**That creature** gains haste until end of turn." (Shallow Grave,
    # Zirilan of the Claw.) A set an earlier step of this effect recorded,
    # by id — not a target, so there is no picker and no noun phrase to
    # re-check: CR 611.2c fixed the set when the effect began and the record
    # *is* that set. The same `permanents_from` channel
    # `grant_target_ability_text` below reads, because the question is the
    # same one asked of a keyword instead of a quoted line.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        lifetime = grant_lifetime(game, instruction, context)
        lasting = DURATION_WORDS.get(lifetime["duration"], "")
        granted = 0
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                # It left between the two steps of one resolution; what comes
                # back is a different object (CR 400.7) and is not this one.
                continue
            for keyword in instruction.payload.get("keywords") or ():
                # **lifetime rather than the two keys by name: a seated
                # duration carries a seat and an unseated one carries none, and
                # naming both would ask for a key that is deliberately absent.
                grant_keyword(permanent, keyword, **lifetime)
            granted += 1
            game.log.append(
                f"{permanent.card.name} gains "
                + ", ".join(instruction.payload.get("keywords") or ())
                + lasting
            )
        if not granted:
            game.log.append(f"{card.name}: nothing was left to grant to")
        game._refresh_dynamic_creatures()
        return True, "resolved"
    # The same three questions the flying twin above asks, through the same
    # reader: two handlers for one printed sentence, and the one that kept its
    # own copy was the one that had none.
    grant_target_legal = granted_target_legal(game, instruction, context)

    keywords = tuple(instruction.payload.get("keywords") or ())

    # "…gains **landwalk of each of the land types of the sacrificed land**"
    # (Excavator). The granted words are not printed: CR 702.14a builds the
    # ability's name out of a land type, and which land type is known only once
    # the cost has been paid. The record is the cost's own
    # (``sacrificed_for_cost``), which is last-known information — the land is
    # in a graveyard by now (CR 608.2h) — and the words are built by
    # ``engine/landwalk.py``, the module the block check reads, so a grant and
    # a block cannot disagree about what "islandwalk" means.
    #
    # Nothing recorded, or a record with no land type, grants **nothing**: an
    # empty tuple here is a creature that gained no evasion, where a fallback
    # word would be an evasion the card never named.
    landwalk_record = instruction.payload.get("landwalk_from")
    if landwalk_record is not None:
        from ..landwalk import landwalk_abilities_of

        paid_with = (context.choices or {}).get(str(landwalk_record))
        keywords = landwalk_abilities_of(paid_with) if paid_with is not None else ()
        if not keywords:
            game.log.append(
                f"{card.name}: the land it was paid with names no landwalk"
            )
            return True, "resolved"

    # "**X** target creatures gain islandwalk until end of turn." (Part Water.)
    # The printed count is a *string* until the spell is cast — X is announced,
    # not printed — so it is resolved against the context's X rather than tested
    # with `isinstance(int)`. That test is the exact hole rounds 23 and 27 found
    # in the tap and bounce handlers: it skipped the "x" spelling, fell through
    # to the one-target branch, and affected the first chosen creature while the
    # player watched the rest do nothing.
    lifetime = grant_lifetime(game, instruction, context)
    lasting = DURATION_WORDS.get(lifetime["duration"], "")
    printed_count = (instruction.payload.get("targets") or {}).get("count")
    maximum = (
        resolve_amount(printed_count, context.x_value)
        if printed_count is not None else None
    )
    if isinstance(maximum, int) and maximum > 1:
        chosen = resolve_target_permanents(game, context, predicate=grant_target_legal)
        if not chosen:
            game.log.append(f"{card.name}: no valid creature targets")
            return True, "resolved"
        for permanent in chosen:
            for keyword in keywords:
                _grant_one_keyword(game, permanent, keyword, context, lifetime)
        game.log.append(
            ", ".join(p.card.name for p in chosen)
            + f" gain {' and '.join(_named_keywords(keywords, context))}"
            + f"{lasting} ({card.name})"
        )
        return True, "resolved"

    target_creature = granted_target(game, instruction, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    for keyword in keywords:
        _grant_one_keyword(game, target_creature, keyword, context, lifetime)
    game.log.append(
        f"{target_creature.card.name} gains "
        f"{' and '.join(_named_keywords(keywords, context))}{lasting} ({card.name})"
    )
    return True, "resolved"


@effect_handler("move_chosen_keyword_between_targets")
def move_chosen_keyword_between_targets(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, target creature with the chosen ability loses it and
    another target creature gains it." (Phyrexian Splicer.)

    One instruction rather than a removal and a grant in a ``sequence``, for
    ``pump_targets_until_eot``'s reason: the clauses name **different** chosen
    creatures (the printed "another", CR 601.2c) and every one-target handler
    resolves through ``_one_choice``, which reads the first entry of the list —
    so lowered as two steps the ability would take the word off a creature and
    hand it straight back.

    The word is neither in the payload nor in the sentence: both clauses print
    the pronoun, and what it names is the option the *activation* chose
    (CR 601.2b through CR 602.2b), recorded on the ability's own source. With
    nothing recorded there is no ability to move and the resolution does
    nothing, which is the direction that cannot invent one.

    The two slots are resolved positionally and each is re-checked against its
    own filter, exactly as the pump above does — a slot that has become illegal
    is dropped and the other half still happens (CR 608.2b). The removal is
    given the same end-of-turn lifetime as the grant, so a creature that loses
    flying this way has it again at cleanup: CR 611.2b, and the printed duration
    governs both halves of the one sentence.
    """
    from ..subject_filters import subject_matches
    from ._chosen import CHOSEN_ABILITY

    card = context.card
    source = context.source_permanent
    keyword = (getattr(source, "metadata", {}) or {}).get(CHOSEN_ABILITY)
    if not keyword:
        game.log.append(f"{card.name}: no ability was chosen to move")
        return True, "resolved"
    keyword = str(keyword)
    targets = instruction.payload.get("targets") or {}
    slot_filters = targets.get("filters") or [targets.get("filter") or {}] * 2
    distinct = bool(targets.get("distinct"))
    duration = instruction.payload.get("duration")
    chosen = resolve_target_slots(game, context, 2)

    taken: list[Permanent] = []
    for index, permanent in enumerate(chosen):
        wanted = slot_filters[index] if index < len(slot_filters) else {}
        if permanent is None or not game.is_on_battlefield(permanent):
            game.log.append(f"{card.name}: nothing legal in slot {index + 1}")
            continue
        if not permanent.is_creature:
            game.log.append(f"{card.name}: slot {index + 1} is no longer a creature")
            continue
        # The first slot's phrase is "with the chosen ability", which is a
        # layer-6 question and so is asked of the game rather than of the pure
        # matcher — the same reader the picker used at announcement, so what was
        # offered and what resolves cannot disagree. Re-asked here because
        # CR 608.2b checks legality when the ability begins resolving and the
        # creature may have lost the word in between.
        if not subject_matches(
            game, permanent, wanted,
            observer=game.players.index(context.caster)
            if context.caster in game.players else None,
            source=source,
        ):
            game.log.append(
                f"{card.name}: slot {index + 1} is no longer a legal target"
            )
            continue
        if distinct and any(permanent is seen for seen in taken):
            game.log.append(
                f"{card.name}: slot {index + 1} named the creature slot 1 took"
            )
            continue
        taken.append(permanent)
        if index == 0:
            remove_keyword(permanent, keyword, duration=duration)
            game.log.append(
                f"{permanent.card.name} loses {keyword} until end of turn ({card.name})"
            )
        else:
            grant_keyword(permanent, keyword, duration=duration)
            game.log.append(
                f"{permanent.card.name} gains {keyword} until end of turn ({card.name})"
            )
    game._refresh_dynamic_creatures()
    return True, "resolved"


@effect_handler("grant_self_ability_text")
def grant_self_ability_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"<This permanent> gains "<ability>"." (CR 113.3.)

    The twin of ``grant_self_keyword_until_eot`` for an ability the layer-6
    word set cannot hold. See ``engine/granted_abilities.py``: the grant is the
    printed line, and the compiler is what turns it back into an ability.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    _grant_ability_texts(game, source_permanent, instruction, context)
    return True, "resolved"


@effect_handler("grant_target_ability_text")
def grant_target_ability_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…that creature gains "<ability>"." (Life Matrix.)

    The printed noun phrase is enforced here as well as at announcement, for
    the reason recorded on ``grant_target_keyword_until_eot`` above: a picker
    and a resolution that disagree are a target the player may announce and the
    effect then declines to affect.

    "Each of **those creatures** gains …" (Dread Wight) is the same grant over
    a set an earlier step of this effect recorded, by id — not a target, so
    there is no picker and no noun phrase to re-check: CR 611.2c fixed the set
    when the effect began and the record *is* that set. A permanent that left
    in between is a new object when it returns (CR 400.7) and simply misses the
    grant; an empty record is a legal outcome rather than an error.
    """
    if instruction.payload.get("on_block_pair"):
        # "Whenever this creature blocks a creature, … the creature gains
        # "<ability>"." (Mindbender Spores.) The creature the block trigger
        # froze, read through the one function that knows how the two fire
        # sites bind it — on the *blocks* half the stack item's target is the
        # blocker itself, so the ordinary target resolution below would grant
        # the abilities to the source.
        from ._targets import block_pair_permanents

        granted = 0
        for permanent in block_pair_permanents(game, context):
            if not game.is_on_battlefield(permanent):
                continue
            _grant_ability_texts(game, permanent, instruction, context)
            granted += 1
        if not granted:
            game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        granted = 0
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                continue
            _grant_ability_texts(game, permanent, instruction, context)
            granted += 1
        if not granted:
            game.log.append(f"{context.card.name}: nothing was left to grant to")
        return True, "resolved"
    described = instruction.payload.get("filter")
    if described is not None:
        # "Until end of turn, **creatures you control** gain "{1}: Regenerate
        # this creature."" (Resuscitate.) A described set, so the board is
        # walked now and the members lock in (CR 611.2c) — the mirror of
        # ``grant_team_keyword_until_eot`` above, which is the same layer-6
        # addition with a keyword recorded instead of a line, and it is walked
        # the same way for that reason: one reader of what the printed noun
        # phrase means, with the caster as observer (CR 109.5), so "you
        # control" here and on a keyword grant are one question.
        from ..subject_filters import subject_matches

        caster_index = game.players.index(context.caster)
        seats = (
            range(len(game.players))
            if instruction.payload.get("every_seat")
            else (caster_index,)
        )
        granted = 0
        for seat in seats:
            for permanent in game.controlled_by(seat):
                if not subject_matches(
                    game, permanent, described, observer=caster_index,
                    source=context.source_permanent,
                ):
                    continue
                _grant_ability_texts(game, permanent, instruction, context)
                granted += 1
        game.log.append(
            f"{context.card.name}: {granted} permanent(s) gain "
            + ", ".join(instruction.payload.get("abilities") or ())
        )
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=_target_grant_predicate(game, instruction, context)
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    _grant_ability_texts(game, target_creature, instruction, context)
    return True, "resolved"


def _grant_ability_texts(game, permanent, instruction, context) -> None:
    """Record every quoted ability the instruction grants, in printed order.

    Capitalised on the way in because the channel is folded into the
    permanent's *rules text*, which the UI shows — the same reason the
    line-derived keyword grant capitalises. The compiler normalises it again.
    """
    from ..keywords import grant_ability_line, normalized_ability_line

    lifetime = grant_lifetime(game, instruction, context)
    caster_seat = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    texts = tuple(instruction.payload.get("abilities") or ())
    if instruction.payload.get("only_if_absent"):
        # "If it doesn't have "<ability>," it gains that ability." (Musician.)
        # Asked of the permanent's *effective* text, which is where a grant
        # already made and a printed one both read from — a check against the
        # printed card alone would grant Musician's ability a second time on
        # the second activation, and the creature would then owe the upkeep
        # payment twice for one set of counters.
        present = {
            normalized_ability_line(line)
            for line in (permanent.effective_card.oracle_text or "").splitlines()
        }
        texts = tuple(
            text for text in texts if normalized_ability_line(text) not in present
        )
    # **Whose grant this is** (CR 109.5), recorded on every granted line rather
    # than only on the seated durations `grant_lifetime` answers for. A granted
    # ability can name its granter — "Only you may activate this ability"
    # (Martyrdom) — and by the time anyone asks, the spell that said "you" is a
    # card in a graveyard with no controller (CR 108.4) and the creature may be
    # under somebody else's control, which is exactly the case the sentence is
    # printed for. `_check_duration` accepts a seat beside any duration and the
    # sweeps ignore one they did not ask for, so this costs the existing grants
    # a key and nothing else.
    granting = dict(lifetime)
    if caster_seat is not None:
        granting.setdefault("seat", caster_seat)
    for text in texts:
        line = text.strip()
        if not line:
            continue
        grant_ability_line(permanent, line[:1].upper() + line[1:], **granting)
    if texts:
        lasting = DURATION_WORDS.get(lifetime["duration"], "")
        game.log.append(
            f"{permanent.card.name} gains "
            + " and ".join(f'"{text}"' for text in texts)
            + f"{lasting} ({context.card.name})"
        )


def _target_grant_predicate(game, instruction, context):
    """Which permanents a targeted grant may reach, from its printed filter.

    Split out of ``grant_target_keyword_until_eot`` so the quoted-ability grant
    asks the *same* three questions rather than a second spelling of them: the
    printed filter, CR 109.5's source exclusion, and the seat "you control"
    compares against.

    ``subject_types`` is the printed noun of a grant whose target was chosen by
    the clause in front of it ("that **enchantment** gains …", Balduvian
    Shaman). Every other card printing that shape says "creature", which is why
    the type was assumed rather than read — and an assumed creature is a
    silently empty target set for the first card that says anything else.
    """
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    types = tuple(instruction.payload.get("subject_types") or ()) or ("creature",)
    source = context.source_permanent

    def legal(perm) -> bool:
        if not any(perm.has_type(card_type) for card_type in types):
            return False
        if not permanent_matches_filter(perm, filters):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    return legal


def _grant_one_keyword(game, permanent, keyword: str, context, lifetime=None) -> None:
    """Put one granted keyword where its reader will find it.

    Layer 6 holds a *word*, and "protection from black" is not one — it is the
    keyword `protection` carrying a quality, which `_protection_qualities` reads
    from its own channel. That channel has existed since protection was written,
    with a comment saying no card in the pool used it yet; Feat of Resistance is
    that card.

    "The color of your choice" is *spent* here and asked one step earlier,
    because CR 608.2d makes the choice part of the *resolution*: the lowering
    puts a ``choose_color`` step in front of every grant that prints it, and
    that step records the answer this reads. An unanswered choice grants
    nothing rather than defaulting to a colour: a protection the player did not
    pick is a protection from the wrong things, and doing nothing is the honest
    failure.
    """
    from ..grammar.keywords import (
        CHOSEN_COLOR_PROTECTIONS, PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS)
    from ..keywords import (LINE_DERIVED_KEYWORDS, grant_ability_line,
                            keyword_ability_name)
    from ..oracle_types import CHOSEN_COLOR_THIS_WAY

    # …and layer 6's word-set is not where a *line-derived* ability's reader
    # looks either. CR 702.23a defines "Rampage N" as a triggered ability, so
    # `engine/rampage.py` builds it out of the printed line at compile time —
    # a word in layer 6 would be a grant of nothing. Granting the line is what
    # the permanent now says, and the compiler makes the ability from there.
    # Capitalised because it is folded into the permanent's *printed* rules
    # text, which the UI shows; the compiler lowercases it again.
    # The printed duration, or end of turn for the handlers that have no
    # instruction to read one from (a rider whose whole wording is "until end
    # of turn").
    lifetime = {"duration": "end_of_turn"} if lifetime is None else lifetime
    if keyword_ability_name(keyword) in LINE_DERIVED_KEYWORDS:
        grant_ability_line(permanent, keyword.capitalize(), **lifetime)
        return
    if not keyword.startswith("protection from "):
        grant_keyword(permanent, keyword, **lifetime)
        return
    if keyword == PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS:
        # "…protection from each of **that permanent's colors**" (Samite
        # Elder). CR 702.16g: one protection ability per colour, and which
        # colours is read off the permanent the "Choose target permanent …"
        # step in front recorded — now, as the effect is applied (CR 608.2h),
        # and through layer 5, so a permanent something has recoloured gives
        # protection from the colour it currently is. A colourless one names
        # no colour and grants nothing; so does a record that is missing or
        # whose permanent has left, which is the honest failure rather than a
        # guessed colour.
        for word in _recorded_permanents_color_words(game, context):
            grant_protection_flag(permanent, word)
        return
    if keyword in CHOSEN_COLOR_PROTECTIONS:
        # Three printed phrasings and **one channel**: whichever seat was asked
        # — the controller of this spell or ability for "the color of your
        # choice", the creature's controller for Wishmonger's "its
        # controller's", the "Choose a color." sentence in front for "the
        # chosen color" — the step that asked wrote the answer into this
        # resolution's scratchpad, and only that step writes it.
        #
        # It used to read "your choice" off the announcement
        # (``choices["new_color"]``), the key an any-colour *mana* ability
        # names its colour on. A colour is not something CR 601.2 / 602.2b
        # announce, so an interactive seat was never asked, a client that sent
        # none granted nothing, and the player had to name the colour before
        # the opponent's response rather than after it.
        symbol = game._normalize_mana_color(context.results.get(CHOSEN_COLOR_THIS_WAY))
        if symbol is None:
            game.log.append(
                f"{context.card.name}: no colour was chosen, so nothing is protected from"
            )
            return
        word = _COLOR_SYMBOL_TO_WORD.get(symbol)
    else:
        word = keyword[len("protection from "):].strip()
    if word:
        grant_protection_flag(permanent, word)


_COLOR_SYMBOL_TO_WORD = {
    "W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
}


def _recorded_permanents_color_words(game, context) -> tuple[str, ...]:
    """The colour words of the permanent this resolution's "Choose target
    permanent …" step recorded, in WUBRG order — empty when nothing was
    recorded, the permanent has left, or it is colourless.

    Read through ``Game._effective_colors`` (CR 613 layer 5), never off the
    printed card: "that permanent's colors" are the ones it has as the effect
    is applied.
    """
    from ..oracle_types import CHOSEN_TARGET_PERMANENTS

    recorded = (getattr(context, "results", None) or {}).get(CHOSEN_TARGET_PERMANENTS) or ()
    colors: set[str] = set()
    for permanent_id in recorded:
        chosen = game.permanent_by_id(permanent_id)
        if chosen is not None:
            colors |= set(game._effective_colors(chosen))
    return tuple(
        word for symbol, word in _COLOR_SYMBOL_TO_WORD.items() if symbol in colors
    )  # _recorded_permanents_color_words


def _named_keywords(keywords, context) -> tuple[str, ...]:
    """*keywords* as the log names them: a chosen-colour protection by the
    colour this resolution's choosing step recorded, so the log says
    "protection from red" rather than repeating the printed choice back to the
    player who just made it. Every other keyword is its own word."""
    from ..grammar.keywords import CHOSEN_COLOR_PROTECTIONS
    from ..oracle_types import CHOSEN_COLOR_THIS_WAY

    results = getattr(context, "results", None) or {}
    word = _COLOR_SYMBOL_TO_WORD.get(str(results.get(CHOSEN_COLOR_THIS_WAY) or "").upper())
    return tuple(
        f"protection from {word}" if word and keyword in CHOSEN_COLOR_PROTECTIONS
        else keyword
        for keyword in keywords
    )


def _named_set_keywords(game, keywords, context) -> tuple[str, ...]:
    """:func:`_named_keywords` with a colour *set* spelled out as well: "each of
    that permanent's colors" (Samite Elder) is logged as the protections it
    actually granted — or as no protection at all, for a colourless choice —
    rather than as the printed phrase."""
    from ..grammar.keywords import PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS

    named: list[str] = []
    for keyword in _named_keywords(keywords, context):
        if keyword != PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS:
            named.append(keyword)
            continue
        words = _recorded_permanents_color_words(game, context)
        named.extend(f"protection from {word}" for word in words)
        if not words:
            named.append("no protection (no colour to be protected from)")
    return tuple(named)  # _named_set_keywords


@effect_handler("grant_self_keyword_until_eot")
def grant_self_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature gains <keyword(s)> until end of turn." (Fetid Imp.)"""
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    for keyword in keywords:
        _grant_one_keyword(game, source_permanent, keyword, context, lifetime)
    game.log.append(
        f"{card.name} gains {' and '.join(_named_keywords(keywords, context))}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_enchanted_keyword_until_eot")
def grant_enchanted_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**it** gains trample until end of turn", where "it" is the enchanted
    creature (Bestial Fury).

    ``grant_self_keyword_until_eot``'s subject read off the attachment record
    instead of off the ability's own source — the keyword twin of
    ``pump_enchanted_creature``, and one printed sentence produces both.

    The host comes from ``attached_host`` rather than a raw
    ``metadata["attached_to"]`` read, so a resolution that has already removed
    the Aura still knows whose creature it was (CR 603.10) — the same fallback
    Cocoon needs one family over.
    """
    from ._targets import attached_host

    card = context.card
    enchanted = attached_host(game, context.source_permanent)
    if enchanted is None:
        return False, "aura not attached to a creature"
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    for keyword in keywords:
        _grant_one_keyword(game, enchanted, keyword, context, lifetime)
    game.log.append(
        f"{card.name}: {enchanted.card.name} gains "
        f"{' and '.join(_named_keywords(keywords, context))}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_flying_and_delayed_destruction")
def grant_flying_and_delayed_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _is_legal(perm) -> bool:
        return (
            perm.is_creature
            and perm.effective_toughness < source_permanent.effective_power
        )

    # Honor the player-chosen creature (Stone Giant targets "target creature you
    # control with toughness less than this creature's power"). Fall back to the
    # first legal creature only for AI/untargeted activations — an explicitly
    # chosen illegal target fizzles.
    target_creature = resolve_target_permanent(
        game, context, player=caster, predicate=_is_legal, fallback_on_invalid_choice=False
    )
    if target_creature is not None:
        grant_keyword(target_creature, "flying", duration="end_of_turn")
        mark_delayed_destruction(game, target_creature, "destroy_at_next_end_step")
        game.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
    else:
        game.log.append("No valid target for Stone Giant effect")
    return True, "resolved"
