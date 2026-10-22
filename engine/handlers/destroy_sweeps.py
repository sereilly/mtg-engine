"""Destroying a set the sentence **describes**: "destroy all …" (CR 701.8).

The handler twin of ``engine/grammar/lowering/_destroy_sweeps.py``, and its
axis: nothing is targeted and nobody picks, so every permanent the printed noun
phrase names is destroyed — by card type (the five "destroy all <types>" kinds,
one body between them), by filter (``destroy_all_matching``: the narrowings the
matcher can test, a block relation, an attachment), by land type
(``destroy_all_lands_of_type``), and the creatures that stood in combat with a
dying source (Abu Ja'far).

Split out of ``destruction.py`` at the 2,000-line cap's split round, along the
line the grammar had already drawn. ``destruction.py`` keeps every handler that
destroys, sacrifices or exiles **one** object or a chosen list of them — by
target, by binding, by reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..static_bonuses import singular_land_type
from ..models import Permanent
from ..object_colors import share_a_color
from ..oracle_types import (EVENT_SUBJECT_LAST_KNOWN, OracleInstruction,
                            PER_OBJECT_SEAT_RECORDS)
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


# "Destroy all <types>" — one sweep, parameterised by the types it names and
# whether regeneration may replace the destruction.
#
# These were four handlers with the same three lines of body, differing only in
# those two values, and adding "destroy all artifacts" (Shatterstorm) would have
# made a fifth. The kinds stay distinct because the compiler, the grammar's
# lowering table and the behaviour snapshots all key on them; only the bodies
# are shared.
#
# Types are read through has_type/is_creature (CR 613 layer 4), so a Copy
# Artifact copy counts as both its types and an animated land counts as a
# creature.
#
# **Regeneration is allowed for all five**, and the column is kept only so the
# table still says so out loud. Lands and enchantments read ``False`` here from
# the consolidation onward — inherited from two Alpha-era handlers written when
# "regenerate" was a thing creatures did. CR 701.19a makes it a replacement on
# *a permanent's* destruction, and a land or an enchantment is often a creature
# too: a Spawning Pool or a Mishra's Factory animated in response to
# Armageddon, an enchantment under Opalescence wearing a Regeneration. Each was
# destroyed through its shield, on seven shipped cards that say nothing about
# regeneration (Armageddon, Impending Disaster; Tranquility, Hush, Essence
# Filter, Multani's Decree, Reverent Silence), and Desolation Angel's two arms
# — one this sweep, one the filtered one below — disagreed about the same
# land. "They can't be regenerated" is the card's to say, and it arrives as
# ``bypass_regeneration`` (Catastrophe).
_SWEEP_TYPES: dict[str, tuple[tuple[str, ...], bool]] = {
    # kind -> (types any of which qualifies, regeneration allowed)
    "destroy_all_creatures": (("creature",), True),
    "destroy_all_artifacts": (("artifact",), True),
    "destroy_all_enchantments": (("enchantment",), True),
    "destroy_all_lands": (("land",), True),
    "destroy_all_artifacts_creatures_enchantments": (
        ("artifact", "creature", "enchantment"),
        True,
    ),
}


def _sweep_by_type(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    types, regeneration_allowed = _SWEEP_TYPES[instruction.kind]
    # "They can't be regenerated" on a card whose family normally allows it.
    if instruction.payload.get("bypass_regeneration"):
        regeneration_allowed = False

    def _matches(perm: Permanent) -> bool:
        return any(
            perm.is_creature if name == "creature" else perm.has_type(name)
            for name in types
        )

    # Who controlled each victim, read **before** the sweep (CR 608.2h /
    # CR 400.7): a later "for each … destroyed this way, its controller …"
    # asks about a permanent that is a card in a graveyard by then.
    controllers = {
        perm.permanent_id: seat
        for player in game.players
        for perm in game.controlled_by(player)
        if _matches(perm)
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    died: list[Permanent] = []
    for player in game.players:
        died.extend(game._destroy_swept_permanents(
            player, _matches, allow_regeneration=regeneration_allowed
        ))
    # "…where X is the number of creatures that **died this way**" (Hellfire).
    # What actually died, not what the sweep aimed at: a regenerated or
    # indestructible permanent is still there, and CR 701.8c is explicit that
    # a replaced destruction is not a death.
    #
    # The **objects** ride beside the number, and did not until this round —
    # these five sweeps recorded the count alone. `_lower_for_each_destroyed`
    # gates on the count being produced, so "Destroy all creatures. For each
    # creature that died this way, …" over one of them compiled *supported* and
    # then iterated an empty list. `destroy_all_matching` beside them has
    # recorded both since Glyph of Reincarnation; the difference was invisible
    # because no printed card had asked yet.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = {
        perm.permanent_id: controllers[perm.permanent_id]
        for perm in died
        if perm.permanent_id in controllers
    }
    game.log.append(f"All {', '.join(types)}s were destroyed")
    return True, "resolved"


for _kind in _SWEEP_TYPES:
    effect_handler(_kind)(_sweep_by_type)


@effect_handler("destroy_creatures_in_combat_with_source")
def destroy_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Abu Ja'far: "When this creature dies, destroy all creatures blocking or
    blocked by it. They can't be regenerated."

    The source is already in the graveyard by the time this resolves, so the
    victims are captured at fire time (CR 603.10 last-known information) and
    passed in ``trigger_context["combat_opponents"]``. Each is destroyed only
    if it is still on a battlefield — one that died to combat damage in the
    same event is simply skipped."""
    bypass_regen = instruction.payload.get("bypass_regeneration", False)
    victims = (context.trigger_context or {}).get("combat_opponents")
    if victims is None and context.source_permanent is not None:
        # No capture (an ability invoked outside the death trigger): fall back
        # to whatever combat relationship the source still has.
        victims = game.creatures_in_combat_with(context.source_permanent)
    victims = list(victims or ())
    destroyed_names: list[str] = []
    for player in game.players:
        destroyed = game._destroy_swept_permanents(
            player,
            lambda p: any(p is victim for victim in victims),
            allow_regeneration=not bypass_regen,
        )
        destroyed_names.extend(perm.card.name for perm in destroyed)
    if destroyed_names:
        game.log.append(
            f"{context.card.name} destroyed {', '.join(destroyed_names)} "
            "(blocking or blocked by it)"
        )
    else:
        game.log.append(f"{context.card.name}: no creatures were blocking or blocked by it")
    return True, "resolved"


def _was_blocked_by(candidate: Permanent, blocker_id: int) -> bool:
    """Was *candidate* blocked by ``blocker_id`` this turn?

    CR 509.1a's relation read **off the candidate**, not off the blocker. The
    two directions of the pair are written together by
    ``declare_blockers_step._record_block_history``, so either end answers — but
    only this end survives the blocker leaving the battlefield, and the blocker
    leaving is the ordinary way Glyph of Doom is played: the Wall blocks, the
    delayed ability waits for the end of combat, and combat damage kills the
    Wall in between. Reading the record off the Wall answered "the creature
    whose blocks it names is gone" and destroyed nothing, on the card's own main
    line.

    ``blocked_ids`` beside it stays as it is: Glyph of Reincarnation names a
    Wall it *targets*, so CR 608.2b has already required that Wall to still be
    there, and that branch reads a second record (which seat controlled each
    attacker) that has no mirror.
    """
    return blocker_id in set(
        candidate.metadata.get("blocked_by_blocker_ids_this_turn") or ()
    )


def _stood_opposite(candidate: Permanent, other_id: int) -> bool:
    """Was *candidate* on the other side of a block from ``other_id`` this turn?

    CR 509.1a's relation read in both directions, off the pair of records
    ``declare_blockers_step`` writes when a block is declared: a blocker names
    the attackers it blocked, and an attacker names the blockers that blocked
    it. Both live on the *candidate*, which is what lets the question be asked
    after the creature on the other side has died.
    """
    return other_id in set(
        candidate.metadata.get("blocked_attacker_ids_this_turn") or ()
    ) or other_id in set(
        candidate.metadata.get("blocked_by_blocker_ids_this_turn") or ()
    )


@effect_handler("destroy_all_matching")
def destroy_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy all Equipment attached to that creature." (Turn to Slag.)

    A sweep over a filter rather than over a card type, so one handler covers
    every narrowing the matcher can test — where the per-scope kinds beside it
    each name one scope.

    ``attached_to`` is resolved **here** rather than by the matcher, for the
    reason the ``controls`` condition resolves "another" here: what an Equipment
    is attached to is a relation, and ``permanent_matches_filter`` answers about
    a permanent alone.

    "That creature" is the spell's own target, and it is still on the
    battlefield: CR 608.2b would have stopped the spell resolving at all if the
    target had become illegal, and CR 704.3 checks state-based actions only when
    a player would receive priority — so a creature this same spell has just
    dealt lethal damage to is *there*, wearing its Equipment, and both are
    destroyed. The host resolving to nothing is the case where it left in
    response to something else, and then there is nothing attached to destroy.
    """
    filters = {
        key: value for key, value in instruction.payload.items()
        if key not in (
            "attached_to", "bypass_regeneration", "targets",
            "blocked_by_bound_object", "blocked_by_target_object",
            "in_combat_with_bound_object",
            # The two halves of "all **other** permanents with **that name**"
            # (Eye of Singularity), both resolved below against the firing
            # event's context — which `subject_matches` never sees.
            "name_from_event", "other_than_event_subject",
            # "…all other creatures that **share a color with it**" (Spreading
            # Plague): the same split one relation over.
            "shares_color_with_event_subject",
            # …and the same comparison against a name this *resolution* wrote
            # down (Wake of Destruction), for the reason its two neighbours are
            # lifted out: `subject_matches` is handed a permanent, a seat and a
            # source, and never the scratchpad.
            "name_from_record",
            # "…**of the creature type of your choice**" (Extinction). A word an
            # earlier step of this same resolution wrote, resolved just below
            # into the ordinary ``subtype_filter`` every matcher already reads.
            "subtype_filter_from",
            # "…with mana value **equal to that number**" (Void). The same
            # arrangement for a *number* an earlier step chose, resolved below
            # into the ordinary ``mana_value`` comparison.
            "mana_value_from",
            # "…**of the color of your choice**" (Root Greevil). The third
            # record, a colour, resolved below into ``color_filter``.
            "color_filter_from",
        )
    }
    # CR 608.2d's choice, spent. The word is read out of the scratchpad rather
    # than off a permanent, because the card that prints this is a sorcery and
    # there is no permanent — which is the whole difference from "of the chosen
    # type" (An-Zerrin Ruins), whose word rides the source's metadata.
    #
    # **No word means no sweep**, and it must: a missing record resolved as "no
    # narrowing" is not a card that does less, it is one that destroys every
    # creature on the table. The same direction ``_resolve_chosen_subtype``
    # takes for its own absent record, reached by refusing here rather than by
    # leaving an unanswerable key in the payload.
    scratch_key = instruction.payload.get("subtype_filter_from")
    if scratch_key is not None:
        chosen = context.results.get(str(scratch_key))
        if not chosen:
            game.log.append(
                f"{context.card.name}: no creature type was chosen"
            )
            return True, "resolved"
        filters["subtype_filter"] = str(chosen)
    # "Destroy all enchantments **of the color of your choice**." (Root
    # Greevil.) CR 608.2d's choice again, a colour this time, read out of the
    # scratchpad the ``choose_color`` step in front wrote and turned into the
    # ordinary ``color_filter`` — which ``subject_matches`` answers through
    # CR 613's layer 5, so an enchantment a Lace turned green is a green
    # enchantment here. The key and the direction are Persecute's discard's:
    # **no colour means no sweep**, because the phrase read as no narrowing is
    # every enchantment on the table.
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen_color = context.results.get(str(color_key))
        if not chosen_color:
            game.log.append(f"{context.card.name}: no colour was chosen")
            return True, "resolved"
        filters["color_filter"] = str(chosen_color)
    # "Choose a number. Destroy all artifacts and creatures with mana value
    # **equal to that number**." (Void.) CR 608.2d's choice one characteristic
    # over, and the same direction on an absent record: no number means no
    # sweep, because the phrase read as no narrowing is every artifact and
    # creature on the table. Zero is a number — it is the answer that takes
    # the tokens — so the test is for the record, not for its truth.
    number_key = instruction.payload.get("mana_value_from")
    if number_key is not None:
        chosen_number = context.results.get(str(number_key))
        if not isinstance(chosen_number, int) or isinstance(chosen_number, bool):
            game.log.append(f"{context.card.name}: no number was chosen")
            return True, "resolved"
        filters["mana_value"] = {"op": "eq", "value": chosen_number}
    # "…all creatures that were blocked by **that creature** this turn."
    # (Glyph of Doom.) A relation, resolved here for the reason `attached_to`
    # below is: the record lives on the blocker the delayed ability was bound
    # to, and `permanent_matches_filter` answers about a permanent alone.
    #
    # An unresolvable bound object ends the resolution rather than falling
    # through — a dropped relation here is not a sweep that does less, it is a
    # sweep that destroys every creature on the battlefield.
    blocked_ids: set[int] | None = None
    blocked_by_blocker_id: int | None = None
    if instruction.payload.get("blocked_by_bound_object"):
        blocked_by_blocker_id = (context.trigger_context or {}).get(
            "bound_permanent_id"
        )
        if blocked_by_blocker_id is None:
            # No binding at all — no creature was named, so no block can be
            # named either. Ending here rather than falling through, for the
            # reason the branches below end: a dropped relation is not a sweep
            # that does less, it is one that takes the board.
            game.log.append(
                f"{context.card.name}: the creature whose blocks it names is gone"
            )
            return True, "resolved"
    # "…all creatures that **blocked or were blocked by** it this turn."
    # (Venomous Breath.) The two-way reading of the same relation, and unlike
    # the one-way branch above it does not need the bound creature to still be
    # there: both halves are answered from a *candidate's* own metadata. That
    # is the only reading that works when the creature the spell named died in
    # the very combat the sentence is about — the ordinary way this card is
    # played, not an edge case.
    #
    # Its own key rather than a widening of `blocked_ids`: the two phrases name
    # different sets, and one field meaning either would leave the sweep
    # guessing which the card printed.
    in_combat_with_id: int | None = None
    if instruction.payload.get("in_combat_with_bound_object"):
        in_combat_with_id = (context.trigger_context or {}).get("bound_permanent_id")
        if in_combat_with_id is None:
            # No binding at all — nothing on the board can stand opposite an
            # object the ability never named. Ending here rather than falling
            # through, for the reason the branch above ends: a dropped relation
            # is not a sweep that does less, it is one that takes the board.
            game.log.append(
                f"{context.card.name}: the creature whose combat it names is gone"
            )
            return True, "resolved"
    # "…all creatures that were blocked by **target Wall** this turn." (Glyph
    # of Reincarnation.) The same record read off a different referent: the
    # blocker is this spell's own target. Resolved by id, never by index — the
    # sweep below removes permanents, and CR 400.7 makes an index meaningless
    # the moment one leaves.
    #
    # The seats frozen beside those ids travel on to the next sentence, which
    # names "the player who controlled that creature the last time it became
    # blocked by that Wall". Read *here*, while the Wall is still the object
    # the spell targeted: once the sweep has run the creatures are cards in a
    # graveyard and nothing on the board can answer the question.
    blocked_controllers: dict[int, int] = {}
    if instruction.payload.get("blocked_by_target_object"):
        blocker = game.permanent_by_id(context.target_permanent_id)
        if blocker is None:
            # CR 608.2b would normally have countered the spell for having no
            # legal target left; a blocker that is nonetheless gone (an ability
            # naming it, a copy resolving late) names no blocks this effect can
            # read. Ending here rather than falling through, for the reason the
            # bound-object branch above ends: the relation is the whole card.
            game.log.append(
                f"{context.card.name}: the creature whose blocks it names is gone"
            )
            return True, "resolved"
        blocked_ids = set(blocker.metadata.get("blocked_attacker_ids_this_turn") or ())
        blocked_controllers = dict(
            blocker.metadata.get("blocked_attacker_controllers_this_turn") or {}
        )
    # "…destroy all other permanents with **that name**." (Eye of Singularity.)
    # CR 201.2's comparison against the permanent whose entry fired the trigger.
    # The name is read from the context the fire site froze rather than from the
    # id beside it: this resolves after the entry, and a permanent that has left
    # by then is a card in another zone the id no longer resolves to (CR 400.7)
    # — while the sentence still names the name the event had (CR 603.10).
    #
    # An unresolvable name ends the resolution, for the reason every relation
    # around it does: a dropped narrowing on a sweep is not a card that does
    # less, it is one that takes the board.
    event_name: str | None = None
    event_subject_id: int | None = None
    # "Destroy target land **and all other lands with the same name as that
    # land**." (Wake of Destruction.) The same comparison against a name this
    # resolution wrote down rather than one a firing event froze: the step in
    # front of this one destroyed the land and recorded what it was called, one
    # line before it left the battlefield (CR 608.2h).
    #
    # A branch beside the trigger reading rather than a second reader of it: the
    # two names live in different places — one in the trigger's frozen context,
    # one in the resolution's scratchpad — and a handler that guessed between
    # them would sweep the board whenever it guessed wrong.
    name_record = instruction.payload.get("name_from_record")
    if name_record is not None:
        event_name = str(context.results.get(name_record) or "").strip() or None
        if event_name is None:
            # The destroy in front chose nothing (its target had left,
            # CR 608.2b), so there is no name for the sweep to compare against
            # and nothing it may take. Ending here for the trigger branch's
            # reason: a dropped narrowing on a sweep destroys every land on the
            # table.
            game.log.append(
                f"{context.card.name}: nothing was destroyed, so no name to match"
            )
            return True, "resolved"
    if instruction.payload.get("name_from_event"):
        tctx = context.trigger_context or {}
        event_name = tctx.get("event_subject_name")
        if not event_name:
            game.log.append(
                f"{context.card.name}: no name for 'that name' to be"
            )
            return True, "resolved"
        # "**Other** permanents" — every one but the permanent the sentence is
        # about. By id rather than by name, because the exclusion is one object
        # and a second copy with the same name is a different permanent that the
        # card destroys (CR 400.7).
        if instruction.payload.get("other_than_event_subject"):
            event_subject_id = tctx.get("event_subject_permanent_id")
    # "…destroy all other creatures **that share a color with it**." (Spreading
    # Plague.) CR 105.2's relation against the permanent the firing event was
    # about. Its colours are read as this resolves, off the object the fire
    # site froze: while the creature is still on the battlefield that is what
    # it is *now* (a Lace cast in response changes who dies), and once it has
    # left the same object is its last-known information (CR 608.2h), which is
    # what the sentence still means by "it".
    #
    # A subject that resolves to nothing, or to a colourless object, ends the
    # resolution with nothing destroyed — and the second is not a refusal, it
    # is the card: CR 105.2c's colourless object shares a colour with nothing,
    # so an artifact creature entering under the Plague kills no one. Both end
    # here rather than falling through, for the reason every relation around
    # this one does: a dropped narrowing on a sweep takes the board.
    shared_colors: frozenset[str] | None = None
    if instruction.payload.get("shares_color_with_event_subject"):
        tctx = context.trigger_context or {}
        entered = tctx.get(EVENT_SUBJECT_LAST_KNOWN)
        if entered is None:
            entered = game.permanent_by_id(tctx.get("event_subject_permanent_id"))
        if entered is None:
            game.log.append(
                f"{context.card.name}: no object for 'it' to share a color with"
            )
            return True, "resolved"
        shared_colors = frozenset(game._effective_colors(entered))
        if not shared_colors:
            context.results["destroyed_this_way"] = 0
            context.results["destroyed_this_way_objects"] = []
            game.log.append(
                f"{context.card.name}: {entered.card.name} is colorless and "
                "shares a color with nothing"
            )
            return True, "resolved"
        if instruction.payload.get("other_than_event_subject"):
            event_subject_id = tctx.get("event_subject_permanent_id")
    attached_to = instruction.payload.get("attached_to")
    host = None
    if attached_to is not None:
        # Every referent the noun parser can produce is answered here. Falling
        # through with `host` still None would drop the relation and sweep every
        # matching permanent on the board, which is the widening this whole
        # payload key exists to prevent — so an unresolvable one ends the
        # resolution instead.
        if attached_to == "target":
            host = game.permanent_by_id(context.target_permanent_id)
        elif attached_to == "source":
            host = context.source_permanent
        if host is None:
            game.log.append(
                f"{context.card.name}: nothing is attached to a permanent that is gone"
            )
            return True, "resolved"
    # Through ``subject_matches`` rather than the pure matcher, for the reason
    # the bounce handler asks it: "all enchantments **you control**" (Remove
    # Enchantments) is a seat comparison no read of the enchantment alone can
    # make, and so is the host phrase inside "Auras attached to permanents you
    # control". The observer is CR 109.5's — the controller of the spell or
    # ability doing the destroying, never whoever controls what it hits.
    #
    # The lowering's gate is the same key set this answers, which is what stops
    # a phrase arriving here that would be dropped: a dropped narrowing on a
    # sweep is not a card that does less, it is one that takes the board.
    # Late import: ``subject_filters`` imports this package's floors, so
    # the edge is taken at call time rather than at module load — the same
    # reason ``bounce_target_creature`` takes it late.
    from ..subject_filters import subject_matches

    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    # "…all untapped non-Wall creatures **that player** controls" (Total War).
    # A seat the firing event picked, not a seat any read of the board can
    # name — so `subject_matches` refuses it outright and says why, and the
    # resolution holding the trigger's context is what answers. Stripped from
    # the filter and asked as its own predicate rather than rewritten into
    # "you": every other key in the phrase is still relative to CR 109.5's
    # observer, and swapping the observer wholesale would re-aim them at
    # whoever attacked.
    #
    # An unresolvable seat ends the resolution, for the reason every relation
    # above ends it: a dropped narrowing on a sweep is not a card that does
    # less, it is one that takes the board.
    # "Destroy all creatures **target player** controls." (Mogg Infestation;
    # Simoon prints the same noun phrase with "opponent" and the damage sweep
    # already hands it over.) A seat *this* resolution chose (CR 601.2c), which
    # no read of a permanent can supply — so it goes to the matcher, which
    # refuses the word without one. Absent it, the phrase fell through the
    # matcher's seat comparisons and the sweep took every creature on the table.
    targeted_seat = (
        game.players.index(context.target)
        if context.target is not None and context.target in game.players
        else None
    )
    attacking_seat: int | None = None
    if filters.get("controller") == "that_player":
        frozen = frozen_that_player_seat(game, context)
        if frozen is None:
            game.log.append(
                f"{context.card.name}: no player for 'that player' to name"
            )
            return True, "resolved"
        attacking_seat = frozen
        filters = {k: v for k, v in filters.items() if k != "controller"}
    matched = [
        perm for perm in game.all_permanents()
        if (
            attacking_seat is None
            or game.controller_index_of(perm) == attacking_seat
        )
        and subject_matches(
            game, perm, filters,
            observer=observer, source=context.source_permanent,
            targeted_player=targeted_seat,
        )
        and (host is None or perm.metadata.get("attached_to") is host)
        and (event_name is None or perm.effective_card.name == event_name)
        and (event_subject_id is None or perm.permanent_id != event_subject_id)
        and (
            shared_colors is None
            or share_a_color(shared_colors, game._effective_colors(perm))
        )
        and (blocked_ids is None or perm.permanent_id in blocked_ids)
        and (
            blocked_by_blocker_id is None
            or _was_blocked_by(perm, blocked_by_blocker_id)
        )
        and (
            in_combat_with_id is None
            or _stood_opposite(perm, in_combat_with_id)
        )
    ]
    if not matched:
        context.results["destroyed_this_way"] = 0
        context.results["destroyed_this_way_objects"] = []
        game.log.append(f"{context.card.name}: nothing to destroy")
        return True, "resolved"
    died: list[Permanent] = []
    for perm in matched:
        seat = game.controller_index_of(perm)
        if seat is None:
            continue
        died.extend(game._destroy_swept_permanents(
            game.players[seat],
            lambda candidate, target=perm: candidate is target,
            allow_regeneration=not instruction.payload.get("bypass_regeneration"),
        ))
    # See `_sweep_by_type`: the record is what died, which is what a later
    # "that died this way" counts. The *objects* ride beside the number for a
    # later sentence that iterates them rather than counting them (Glyph of
    # Reincarnation), and the number is derived from the list so the two
    # records cannot come to disagree.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    # The seat each of them was under when the named blocker blocked it, keyed
    # by the same permanent ids. Recorded only when the sweep read a block
    # relation at all, so no other card carries an empty map it never asked for.
    if blocked_controllers:
        context.results[PER_OBJECT_SEAT_RECORDS["controller_when_blocked"]] = {
            perm.permanent_id: blocked_controllers[perm.permanent_id]
            for perm in died
            if perm.permanent_id in blocked_controllers
        }
    game.log.append(
        f"{context.card.name} destroyed " + ", ".join(p.card.name for p in matched)
    )
    return True, "resolved"


@effect_handler("destroy_all_lands_of_type")
def destroy_all_lands_of_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # "Destroy all Islands" arrives plural; "Destroy all Plains" does not,
    # because Plains is spelled the same either way. Stripping a trailing "s"
    # unconditionally turned it into "plain", which no land has ever been — the
    # old substring match hid that ("plain" is a substring of "plains"), and
    # asking the layer system for an exact subtype does not.
    land_type = singular_land_type(str(instruction.payload.get("land_type", "")))
    # "…**that weren't chosen this way by any player**" (Raiding Party). The
    # complement of a set an earlier step of this same resolution recorded, by
    # stable id: the permanents are still on the battlefield and nothing about
    # them says a player named them, so the record is the only thing that can
    # take them out of the sweep.
    #
    # An absent record spares nothing, which is the reading the words give when
    # no player chose anything — the lowering emits the key only behind a step
    # that writes it, so an empty list here is an answer rather than a gap.
    spared = frozenset(
        perm.permanent_id
        for perm in (
            context.results.get(str(instruction.payload["except_recorded"])) or ()
        )
        if getattr(perm, "permanent_id", None) is not None
    ) if instruction.payload.get("except_recorded") else frozenset()

    def _matches(perm: Permanent) -> bool:
        if not perm.has_type("land"):
            return False
        if perm.permanent_id in spared:
            return False
        # has_type, so CR 305.7 is applied in one place: a land whose subtype
        # was set REPLACES its printed types, and asking the layer system is the
        # only way every reader agrees about that.
        return perm.has_type(land_type)

    # Who controlled each victim, read **before** the sweep (CR 608.2h / CR
    # 400.7): "For each land destroyed this way, this spell deals 1 damage to
    # that land's controller" (Stench of Evil) asks about a permanent that is a
    # card in a graveyard by the time the loop runs, and no board read can
    # answer for it.
    controllers = {
        perm.permanent_id: seat
        for player in game.players
        for perm in game.controlled_by(player)
        if _matches(perm)
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    died: list[Permanent] = []
    for player in game.players:
        died.extend(
            game._destroy_swept_permanents(player, _matches, allow_regeneration=False)
        )
    # The record every other destroy sweep keeps, and this one did not: what a
    # later sentence of the same spell counts or iterates. `destroy_all_lands`
    # and `destroy_all_matching` have written it since Hellfire; the by-type
    # sweep beside them was the sweep that recorded nothing, which is invisible
    # until a card asks — the second sentence reads an empty set and the card
    # reports itself supported having done half of what it says.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = {
        perm.permanent_id: controllers[perm.permanent_id]
        for perm in died
        if perm.permanent_id in controllers
    }
    # Named rather than counted, and never "all": this sweep can now spare
    # what an earlier step recorded (Raiding Party), so a line reading "all
    # Plains were destroyed" would be false in exactly the game the card is
    # about. It was also spelling the plural itself — "All plainss" — because
    # Plains is already plural and nothing can strip an "s" it never added.
    game.log.append(
        f"{context.card.name} destroyed "
        + (", ".join(perm.card.name for perm in died) if died else "nothing")
    )
    return True, "resolved"
