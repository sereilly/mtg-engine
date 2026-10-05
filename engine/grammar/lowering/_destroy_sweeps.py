"""Destroying a set the sentence **describes**: "destroy all …" (CR 701.8).

The question ``_sweeps`` answers for damage, for counters and for exile, asked
of the fourth keyword action: nothing is targeted and nobody picks (CR 115.10a
— an object a spell affects without the word "target" is not one), so every
permanent the printed noun phrase names is destroyed, and the noun phrase *is*
the instruction. ``destruction`` keeps every reading that names **one** object
or a chosen list of them — by superlative, by reference, by target.

**It is a module of its own because of a number, and the number is written
down so nobody re-derives it.** By subject this is ``_sweeps``' fourth verb and
:func:`lower_destroy_sweep` belongs beside ``lower_exile_sweep``. Measured at
Invasion's Phase 0 between waves 1 and 2, that module was 573 lines and this
reading some 420 with its tables and its gate: the sum is the thousand-line
guard itself, on the floor four families would then be growing into. That moves
a cap problem rather than answering one. So it sits beside ``_sweeps`` under
the name the package's prose has always used for it ("the destroy sweep"), and
if ``_sweeps`` is ever cut along its own verbs this is already the destroy
half.

Pre-split out of ``lowering/destruction.py`` at 987 lines, on three wave-1
groups' additions — and two of the three were branches *here* (Spreading
Plague's shared colour; Tsabo's Decree's and Void's recorded type and number).
This is the half that grows with the pool, and the reason is the rule every
branch below restates:

    **A narrowing dropped from a sweep is not a card that does less. It is a
    card that destroys the whole board.**

A sweep's narrowing travels to its handler as filter payload, and the shared
matcher that reads it is handed a permanent, a seat and a source — never a
trigger's context and never a resolution's records. Every relation to one of
those — the object a firing event was about, the object a delayed ability was
bound to, a record an earlier step of the same resolution wrote, this spell's
own target — therefore has no form that matcher can answer, and each is a
**branch that returns before the generic paths**: it lifts its key off the
filter, gates it on the event or the record that makes it answerable, and puts
it back under the key the handler reads. A new printed relation is a new
branch; that is the growth, and it is why the order below is load-bearing
rather than tidy.

:func:`_refuse_unfrozen_that_player` is here because it is this sweep's gate
on the one seat word the matcher refuses by value rather than by key.
``destruction._lower_destroy_of_their_choice`` asks it as well, of the same two
words for the same reason, and imports it from here.

A **floor**, not a family, for ``_sweeps``' reason exactly: ``destruction``
reads it and it reads nothing back — its own imports are the floors beneath it
(``_common``, ``_events``, ``_delays``) and no family at all.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (CHOSEN_CREATURE_TYPE_THIS_WAY,
                             CHOSEN_NUMBER_THIS_WAY, CHOSEN_THIS_WAY_OBJECTS,
                             OracleInstruction)
from ...subject_filters import object_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (
    _filter_payload, _restrictions_beyond, split_color_choice,
    split_creature_type_choice,
)
from ._delays import _BOUND_OBJECT_DELAYED_EVENTS
from ._events import (EVENT_SUBJECT_NAMES, LAST_TARGET_NAME,
                      _EVENT_SUBJECT_OBJECTS, _EVENT_SUBJECT_PLAYERS)


# "Destroy all X" shapes with a dedicated sweep handler.


_DESTROY_ALL_KINDS: dict[tuple[str, ...], str] = {
    ("artifact",): "destroy_all_artifacts",
    ("creature",): "destroy_all_creatures",
    ("enchantment",): "destroy_all_enchantments",
    ("land",): "destroy_all_lands",
    ("artifact", "creature", "enchantment"): "destroy_all_artifacts_creatures_enchantments",
}


_BASIC_LAND_TYPES = frozenset({"plains", "island", "swamp", "mountain", "forest"})


def _refuse_unfrozen_that_player(described: dict, event: str | None, node) -> None:
    """Refuse a sweep narrowed by "**that player** controls" under an event that
    names no player.

    ``controller`` is in :data:`TESTABLE_SUBJECT_FILTER_KEYS`, so the generic
    gate above says yes to the *key* — and ``subject_matches`` then refuses the
    *value*, because "that player" is a seat only the resolution holding the
    trigger's context knows. Put together that is a sweep which compiles, fires
    and destroys nothing, with the card reported supported: the quiet failure
    this whole file is arranged to make loud.

    So the permission is the same one every other back-reference asks for —
    that the firing event froze a seat (:data:`_EVENT_SUBJECT_PLAYERS`). A
    spell, which has no event at all, cannot print the phrase meaningfully and
    is refused here rather than at the table.
    """
    if described.get("controller") != "that_player":
        return
    if event in _EVENT_SUBJECT_PLAYERS:
        return
    raise LoweringError(
        "'that player controls' needs a trigger that froze a seat", node=node
    )


def lower_destroy_sweep(
    node: ast.Destroy,
    subject: ast.TargetSpec,
    event: str | None,
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Destroy **all** / **each** <noun phrase>." — every reading of it.

    Called by ``destruction._lower_destroy`` once the quantifier has said the
    sentence describes its set, and after the two readings that outrank the
    quantifier there (the superlative, which names one object under the same
    "all"; several announced targets). Every path below returns or raises, so
    nothing falls back out into the single-object readings.

    *event* is the **unfiltered** trigger kind and *produced* the records the
    steps in front of this one wrote: between them they are what a relation
    printed in the noun phrase is answerable to, and a branch whose relation
    has neither refuses rather than sweeping without it.

    The order is the contract. The by-type land sweep and the subtype sweep
    come first because a bare subtype has no card type for the later paths to
    key on; then one branch per relation ``_filter_payload`` cannot carry, each
    of which must return before the generic paths see the filter with that
    relation missing; then the narrowed sweep, the type union, and last the
    five kinds whose scope is their own name.
    """
    filt = subject.filter
    # "Destroy all Plains" — a basic land type, not a creature subtype.
    if filt.subtypes and not filt.card_types:
        if len(filt.subtypes) == 1 and filt.subtypes[0] in _BASIC_LAND_TYPES:
            subtype = filt.subtypes[0]
            # The handler keys on the plural form the card prints; Plains is
            # already plural.
            plural = subtype if subtype.endswith("s") else f"{subtype}s"
            # This branch carried **no** leftovers check for as long as it
            # existed, which was safe only while the noun parser could read
            # nothing more than the type word: every card printing it prints
            # a bare "Destroy all Plains". The moment a relative clause
            # became readable it became a dropped rider — a narrowed sweep
            # widening silently back to every land of the type — so the
            # check goes in beside the one narrowing this handler honours.
            narrowed = _restrictions_beyond(
                filt,
                frozenset({"subtypes", "subtype_match", "not_chosen_this_way"}),
            )
            if narrowed:
                raise LoweringError(
                    "the by-type land sweep cannot narrow by: "
                    + ", ".join(narrowed), node=node,
                )
            payload: dict[str, object] = {"land_type": plural}
            if filt.not_chosen_this_way:
                # "…**that weren't chosen this way by any player**"
                # (Raiding Party). The complement of a set an earlier step
                # of this same effect recorded: the record's name travels as
                # payload and the handler subtracts it, because no read of
                # the board can say which Plains somebody named.
                payload["except_recorded"] = CHOSEN_THIS_WAY_OBJECTS
            return (
                OracleInstruction("destroy_all_lands_of_type", "", payload),
            )
        # "Destroy all Equipment attached to that creature." (Turn to
        # Slag.) A sweep over a *narrowed* set rather than a card type, so
        # it carries the filter instead of naming a per-scope handler.
        described = _filter_payload(filt)
        if untestable_filter_keys(described):
            raise LoweringError("no sweep handler for this subtype", node=node)
        if filt.attached_to is not None:
            described["attached_to"] = filt.attached_to
        if node.no_regen:
            described["bypass_regeneration"] = True
        return (OracleInstruction("destroy_all_matching", "", described),)
    # "Destroy all creatures blocking or blocked by it." (Abu Ja'far,
    # printed on a dies trigger; Kjeldoran Frostbeast prints the same
    # sentence on an end-of-combat one.) The relation is the whole
    # sentence, so it must not fall through to the generic creature sweep
    # below — that path keys on card types alone, so the relation would be
    # dropped and the trigger would wipe the board.
    #
    # A production rather than Abu Ja'far's card hook: two cards in the
    # pool print the sentence, and the *only* difference between them is
    # which trigger carries it, which is exactly the "a second card shares
    # the shape" bar `card_hooks` refuses at. The handler was already
    # generic — it reads the combat relationship off the trigger's capture
    # or off the live combat maps — so what the hook was buying was one
    # card's spelling of a template.
    if filt.in_combat_with_source:
        if filt.card_types != ("creature",) or _restrictions_beyond(
            filt, frozenset({"card_types", "in_combat_with_source"})
        ):
            # The handler destroys the whole combat relationship and reads
            # nothing else, so a narrowing beside the relation is one it
            # would silently ignore — and ignoring a narrowing on a *sweep*
            # destroys creatures the card does not name.
            raise LoweringError(
                "the combat-relation sweep destroys the whole relationship "
                "and narrows no further", node=node,
            )
        relation_payload: dict[str, object] = {}
        if node.no_regen:
            relation_payload["bypass_regeneration"] = True
        return (
            OracleInstruction(
                "destroy_creatures_in_combat_with_source", "", relation_payload
            ),
        )
    # "Destroy all creatures that were blocked by that creature this
    # turn." (Glyph of Doom.) A relation to the object the delayed ability
    # was bound to, which `permanent_matches_filter` cannot answer — it is
    # a record on *that* creature, not a characteristic of these — so it
    # travels as its own payload key and the handler resolves it.
    #
    # Refused under any other event, and refused *before* the generic paths
    # below, because `_filter_payload` does not carry the field: falling
    # through would leave the sweep with card types alone and destroy every
    # creature on the battlefield. That is the same shape as the colour
    # dropped from `Destroy all black creatures`, and the reason this
    # branch is a branch rather than a payload key.
    #
    # "Destroy all creatures that **blocked or were blocked by** it this
    # turn." (Venomous Breath.) The two-way reading of the same record,
    # carried on its own key so the handler cannot mistake it for the
    # one-way one — and behind the same event gate, for the same reason.
    for relation in ("blocked_by_bound_object", "in_combat_with_bound_object"):
        if not getattr(filt, relation):
            continue
        if event not in _BOUND_OBJECT_DELAYED_EVENTS:
            raise LoweringError(
                "\"that creature\" names the object a delayed ability was "
                "bound to, and this event binds none", node=node,
            )
        blocked_payload = _filter_payload(
            filt, carried_separately=frozenset({relation})
        )
        if untestable_filter_keys(blocked_payload):
            raise LoweringError("no sweep handler for this narrowing", node=node)
        blocked_payload[relation] = True
        if node.no_regen:
            blocked_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_all_matching", "", blocked_payload),
        )
    # "Destroy all other permanents with **that name**." (Eye of
    # Singularity.) A relation to the object the *firing event* was about,
    # which `subject_matches` cannot answer — it is handed a permanent, a
    # seat and a source, and never the trigger's context — so the key
    # travels to the handler, exactly as the two block relations above do.
    #
    # A branch rather than a payload key for their reason as well:
    # `_filter_payload` does not carry the field, so falling through to the
    # generic paths below would leave the sweep with no narrowing at all and
    # destroy every permanent on the battlefield.
    if filt.name_from_event:
        # "Destroy target land **and all other lands with the same name as
        # that land**." (Wake of Destruction.) The same printed phrase with
        # a different antecedent, and the difference is not in the words: no
        # event fired here at all — "that land" is the *target the sentence
        # in front of this conjunct chose*, which the destroy step records
        # one line before it takes the permanent off the battlefield.
        #
        # Asked before the trigger gate rather than after it, because the
        # record is the *closer* binder: a sweep written under a trigger
        # whose event names an object and preceded by a destroy in the same
        # sentence means the one it just destroyed. Same precedence
        # `lowering/life.py` gives the loop marker over the bare record, one
        # family over.
        if LAST_TARGET_NAME in produced:
            recorded = _filter_payload(
                filt, carried_separately=frozenset({"name_from_event"}),
            )
            # "all **other** lands" — other than the land this sentence
            # already destroyed, which by the time the sweep runs is a card
            # in a graveyard and on nobody's battlefield. Popped rather than
            # dropped, for the trigger branch's reason: the noun parser
            # wrote it as `exclude_self`, where "self" is the *ability's
            # source*, and a sorcery has none — left on the payload it would
            # be a narrowing the sweep silently ignores.
            recorded.pop("exclude_self", None)
            recorded.pop("name_from_event", None)
            if untestable_filter_keys(recorded):
                raise LoweringError(
                    "no sweep handler for this narrowing", node=node
                )
            recorded["name_from_record"] = LAST_TARGET_NAME
            if node.no_regen:
                recorded["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", recorded),
            )
        # The events that freeze a *name* (``EVENT_SUBJECT_NAMES``), not
        # every event that freezes an object: the handler reads
        # ``event_subject_name``, and under a kind that stamps only the id
        # the sentence compiled clean and found nothing to compare against.
        if event not in EVENT_SUBJECT_NAMES:
            raise LoweringError(
                "\"that name\" is the name of the object this "
                "trigger's event was about, and this event records none",
                node=node,
            )
        named_payload = _filter_payload(
            filt, carried_separately=frozenset({"name_from_event"}),
        )
        # "**other** permanents with that name". The determiner is printed
        # about the permanent the sentence is already about — the one that
        # entered — and not about the ability's source, which is the Eye
        # itself and is not a permanent with that name in the first place.
        # So the pronoun is resolved here, where the event is known, rather
        # than left as the `exclude_self` the noun parser wrote: dropped, it
        # would destroy the permanent whose entry fired the trigger.
        other_than_enterer = bool(named_payload.pop("exclude_self", None))
        # Both halves are lifted out before the testability gate and put
        # back after it, the way Bronze Tablet's ownership half is: the gate
        # asks what ``subject_matches`` can answer, and these two are
        # answered by the handler against a context that matcher never sees.
        named_payload.pop("name_from_event", None)
        if untestable_filter_keys(named_payload):
            raise LoweringError("no sweep handler for this narrowing", node=node)
        named_payload["name_from_event"] = True
        if other_than_enterer:
            named_payload["other_than_event_subject"] = True
        if node.no_regen:
            named_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_all_matching", "", named_payload),
        )
    # "Whenever a creature enters, destroy all other creatures **that share
    # a color with it**. They can't be regenerated." (Spreading Plague.)
    # ``name_from_event``'s arrangement one relation over, and a branch for
    # its reason: the handler holds the trigger's context and the matcher
    # never does, so the key is lifted out here and resolved there — and
    # falling through to the generic paths below would leave the sweep with
    # card types alone and destroy every creature on the battlefield.
    #
    # "It" is the object the firing event was about, so the sentence reads
    # only under an event that freezes one (``_EVENT_SUBJECT_OBJECTS``).
    # Under a source-scoped trigger the same pronoun would be the source
    # itself — a different referent nothing prints — and it refuses here
    # rather than being read against an id that was never stamped.
    if filt.shares_color_with_it:
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"shares a color with it\" names the object this "
                "trigger's event was about, and this event records none",
                node=node,
            )
        shared_payload = _filter_payload(filt)
        # "**other** creatures" — other than the creature the sentence is
        # already about, the one that entered, and not the enchantment
        # printing the line (which is not a creature in the first place).
        # Resolved here, where the event is known, exactly as the name
        # sweep above resolves the same word.
        other_than_subject = bool(shared_payload.pop("exclude_self", None))
        shared_payload.pop("shares_color_with_it", None)
        if untestable_filter_keys(shared_payload):
            raise LoweringError("no sweep handler for this narrowing", node=node)
        shared_payload["shares_color_with_event_subject"] = True
        if other_than_subject:
            shared_payload["other_than_event_subject"] = True
        if node.no_regen:
            shared_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_all_matching", "", shared_payload),
        )
    # "Destroy all creatures that were blocked by **target Wall** this
    # turn." (Glyph of Reincarnation.) The sibling of the branch above, and
    # a branch for its reason: the relation has no payload form, so falling
    # through to the generic paths would leave the sweep with card types
    # alone and destroy every creature on the battlefield.
    #
    # What differs is where the blocker comes from. It is this spell's own
    # target, so the noun phrase the relation carries is hoisted into a
    # ``targets`` description — that is the evidence
    # ``engine/targeting.py`` reads to raise a Wall picker, and without it
    # the spell would be cast with nothing chosen and resolve against no
    # blocker at all.
    if filt.blocked_by_target_object is not None:
        blocker = filt.blocked_by_target_object
        blocked_payload = _filter_payload(
            filt, carried_separately=frozenset({"blocked_by_target_object"})
        )
        if untestable_filter_keys(blocked_payload):
            raise LoweringError("no sweep handler for this narrowing", node=node)
        blocker_payload = _filter_payload(blocker)
        if object_only_filter(blocker_payload) is None:
            raise LoweringError(
                "no picker offers a blocker narrowed this way", node=node
            )
        blocked_payload["blocked_by_target_object"] = True
        blocked_payload["targets"] = {
            "kind": "object", "count": 1, "filter": blocker_payload,
        }
        if node.no_regen:
            blocked_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_all_matching", "", blocked_payload),
        )
    if filt.dealt_damage_to_source_this_turn:
        raise LoweringError(
            "a destroy sweep over a source relation stays with its card "
            "hook until the probe review takes it", node=node,
        )
    # "Destroy all **black** creatures." (Cleanse.) / "Destroy all
    # **nonblack** creatures." (Hellfire.) The type-keyed sweeps below take
    # an empty payload and read their scope off their own kind, so every
    # other word of the noun phrase is a key nothing would carry — and a
    # dropped colour here is not a card that does less, it is a card that
    # destroys the whole board. Routed to the filtered sweep instead, which
    # is the same handler "Destroy all Equipment attached to that creature"
    # already uses; refused when the narrowing is one the matcher cannot
    # test, for the reason `object_only_filter` exists.
    #
    # "Choose a creature type. … destroy all creatures **of that type** that
    # player controls." (Tsabo's Decree.) "That type" is the word a sentence
    # in front of this one recorded (CR 608.2d): taken off the filter and
    # carried as the scratchpad slot the handler resolves, the arrangement
    # Outbreak's pump (`lowering/characteristics`) has and the key
    # Extinction's sweep below already reads. Only behind the step that
    # writes it — an unresolved "that type" read as no narrowing is a sweep
    # over every creature on the battlefield.
    bound_type: dict[str, object] = {}
    if filt.of_bound_type:
        if CHOSEN_CREATURE_TYPE_THIS_WAY not in produced:
            raise LoweringError(
                "'of that type' names a creature type no step of this "
                "effect chose", node=node,
            )
        filt = dataclasses.replace(filt, of_bound_type=False)
        bound_type["subtype_filter_from"] = CHOSEN_CREATURE_TYPE_THIS_WAY
    # "Choose a number. Destroy all artifacts and creatures with mana value
    # **equal to that number**." (Void.) The same split one characteristic
    # over: the number is the resolution's, so it travels as the record's
    # name and the handler turns it into the ordinary ``mana_value``
    # comparison. Only behind the step that chose one.
    if filt.mana_value_equals_chosen_number:
        if CHOSEN_NUMBER_THIS_WAY not in produced:
            raise LoweringError(
                "'equal to that number' names a number no step of this "
                "effect chose", node=node,
            )
        filt = dataclasses.replace(filt, mana_value_equals_chosen_number=False)
        bound_type["mana_value_from"] = CHOSEN_NUMBER_THIS_WAY
    described = _filter_payload(filt)
    narrowing = {
        key: value for key, value in described.items()
        if key not in ("type_filter", "type_filter_all")
    }
    if narrowing or bound_type:
        # "Destroy all creatures **of the creature type of your choice**."
        # (Extinction.) CR 608.2d's choice, lifted out of the noun phrase
        # into a step of its own in front of the sweep — the sweep then
        # reads the word back out of the scratchpad rather than testing a
        # narrowing no matcher can answer. Asked before the testability
        # gate below, because with the phrase still in the payload that
        # gate is exactly what refuses the card.
        prelude, described, chosen_type = split_creature_type_choice(described)
        # "Destroy all enchantments **of the color of your choice**." (Root
        # Greevil.) The same lift one characteristic over, through the helper
        # the bounce sweep already uses for it (Wash Out): the ``choose_color``
        # step goes in front — asked as the ability resolves, CR 608.2d — and
        # the sweep reads the colour back out of the scratchpad. "…of that
        # color" behind a sentence that already chose is the same read with no
        # step of its own.
        color_prelude, described, chosen_color = split_color_choice(described)
        prelude = (*prelude, *color_prelude)
        chosen_type = {**chosen_type, **chosen_color}
        if untestable_filter_keys(described):
            raise LoweringError("no sweep handler for this narrowing", node=node)
        # "**Target player** reveals their hand … Then destroy all creatures
        # of that type **that player** controls." (Tsabo's Decree.) In a
        # spell no event froze a seat, and the phrase still has an
        # antecedent: the player an earlier sentence of this same effect
        # *targeted* (CR 601.2c). That is the seat the handler already reads
        # for "target player controls" (Mogg Infestation), so the word is
        # rewritten to it — and only behind a step that recorded a creature
        # type, which is the one shape this sentence has been read in. Every
        # other unfrozen "that player" keeps the refusal below.
        if (
            bound_type
            and event is None
            and described.get("controller") == "that_player"
        ):
            described = {**described, "controller": "target_player"}
        _refuse_unfrozen_that_player(described, event, node)
        narrowed_payload = {**described, **chosen_type, **bound_type}
        if node.no_regen:
            narrowed_payload["bypass_regeneration"] = True
        return (
            *prelude,
            OracleInstruction("destroy_all_matching", "", narrowed_payload),
        )
    kind = _DESTROY_ALL_KINDS.get(tuple(sorted(filt.card_types)))
    if kind is None:
        # A type union no per-scope kind names — "Destroy all artifacts,
        # creatures, and lands" (Jokulhaups). The **filtered** sweep already
        # answers it: `type_filter` takes a list and
        # `permanent_matches_filter` reads one as a union, which is the same
        # question the per-scope kinds ask with the answer baked into the
        # kind. So this routes rather than refuses, and a set printing a
        # fourth union costs no row.
        #
        # The named kinds stay for the unions that have one: the compiler,
        # this table and the behaviour snapshots all key on them, and
        # rewriting a shipped card's instruction kind is a change to what
        # those snapshots describe rather than to what the card does.
        if not filt.card_types:
            raise LoweringError(
                "no sweep handler for this destroy scope", node=node
            )
        union_payload = dict(described)
        if node.no_regen:
            union_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_all_matching", "", union_payload),
        )
    payload = {"bypass_regeneration": True} if node.no_regen else {}
    return (OracleInstruction(kind, "", payload),)
