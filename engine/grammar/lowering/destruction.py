"""Lowering destruction: CR 701.8, and the delayed and conditional forms of it.

Split out of ``board`` at the thousand-line guard — a cap neither parallel
branch crossed alone, which is what made the boundary visible: one added an
activated ability's delayed destroy and the other a per-payer sweep, and both
are destruction rather than board changes generally.

The line is the CR's own keyword action. Destroying a permanent (CR 701.8) is
not sacrificing one (CR 701.21), regenerating one (CR 701.19), phasing one out
(CR 702.26) or exchanging control of one, and those are what ``board`` keeps.
The two halves share no name in either direction — checked at the split rather
than assumed — so this is a family boundary and not a size cut.
"""

import dataclasses

from ...oracle_types import (CHOSEN_THIS_WAY_OBJECTS, CHOSEN_TARGET_PERMANENTS,
                             OracleInstruction)
from ...subject_filters import (
    object_only_filter, untestable_filter_keys
)
from .. import ast
from ..errors import LoweringError
from ._common import (
    describe_independent_target_roles, _describe_several_targets,
    _describe_targets, _filter_payload, _is_source, _names_several_targets,
    _restrictions_beyond, is_mana_value_x, SEVERAL_DESTROY_NARROWINGS,
    split_creature_type_choice, testable_filter_payload
)
from ._events import (ATTACHED_PERMANENT_CONTROLLER, LAST_TARGET_NAME, _EVENT_STAMPED_TARGET_OBJECTS, _EVENT_SUBJECT_OBJECTS, _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_NAMES, EVENT_SUBJECT_PLAYER, ROLE_NAMES_BLOCK_PARTNER, names_attached_permanent, CHOSEN_PERMANENT)
from ._delays import (_DELAYED_AGENT_EVENTS, _BOUND_OBJECT_DELAYED_EVENTS)
from ._superlatives import superlative_pick


#: Where a chosen attachment host is recorded for the step behind it to read.
#: One name in one place, because the two instructions the lowering emits have
#: to agree about it and a literal written twice is two chances to disagree.


# ---------------------------------------------------------------------------
# Destruction, tapping, zones
# ---------------------------------------------------------------------------

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


def _lower_destroy(
    node: ast.Destroy,
    event: str | None = None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("destroy needs an object target", node=node)
    spec = node.subject
    filt = spec.filter

    # "…that share a color with **it**" (Spreading Plague) is read by the
    # sweep branch below and by nothing else in this function: a *target*
    # narrowed by a relation to the firing event's object would need the
    # picker and the CR 608.2b recheck to hold the trigger's context, and
    # neither does. Refused up here so the single-target tail cannot carry the
    # key into a payload no matcher reads.
    if filt.shares_color_with_it and spec.quantifier not in ("all", "each"):
        raise LoweringError(
            "only a sweep reads 'shares a color with it'", node=node
        )

    # "Destroy **the creature with the least power**. It can't be regenerated."
    # (Drop of Honey.) Purging Scythe prints the same noun phrase under a damage
    # verb one family over, which is why the pick is a floor both read
    # (``_superlatives``) rather than a branch in either. Above every sweep
    # below, because "all" is the quantifier the definite article gives a
    # described phrase and this one names **one** object — falling through, the
    # word is refused by name at the key gate, which is the safe direction but
    # not the card.
    pick = superlative_pick(spec, node=node, verb="destroy")
    if pick is not None:
        if node.also_targets or node.delay:
            raise LoweringError(
                "a superlative destroy carries no second target and no delay",
                node=node,
            )
        step, key = pick
        destroy_payload: dict[str, object] = {"permanents_from": key}
        if node.no_regen:
            destroy_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("sequence", "", {"steps": (
                step,
                OracleInstruction(
                    "destroy_target_permanent", "", destroy_payload
                ),
            )}),
        )

    if node.also_targets:
        # "Destroy target creature **and target land**." (Fumarole.) Several
        # targeted phrases of one announcement, described as ordered roles so
        # the picker asks for each in turn (CR 601.2c). One instruction, because
        # one announcement — see ``ast.Destroy.also_targets``.
        #
        # Above every branch below, and carrying **no** top-level filter keys:
        # those describe one target, and a payload holding both would let the
        # single-target tail read the first role's noun as though it were the
        # whole spell.
        payload: dict[str, object] = {}
        if node.no_regen:
            payload["bypass_regeneration"] = True
        describe_independent_target_roles(payload, (spec, *node.also_targets))
        return (OracleInstruction("destroy_target_permanent", "", payload),)

    if spec.quantifier in ("all", "each"):
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
        described = _filter_payload(filt)
        narrowing = {
            key: value for key, value in described.items()
            if key not in ("type_filter", "type_filter_all")
        }
        if narrowing:
            # "Destroy all creatures **of the creature type of your choice**."
            # (Extinction.) CR 608.2d's choice, lifted out of the noun phrase
            # into a step of its own in front of the sweep — the sweep then
            # reads the word back out of the scratchpad rather than testing a
            # narrowing no matcher can answer. Asked before the testability
            # gate below, because with the phrase still in the payload that
            # gate is exactly what refuses the card.
            prelude, described, chosen_type = split_creature_type_choice(described)
            if untestable_filter_keys(described):
                raise LoweringError("no sweep handler for this narrowing", node=node)
            _refuse_unfrozen_that_player(described, event, node)
            narrowed_payload = {**described, **chosen_type}
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

    # "Destroy **it**", where the sentence's "it" is the permanent this Aura
    # enchants (Blight: "When enchanted land becomes tapped, destroy it"), and
    # the equivalent spelling that names it outright. Its own handler for the
    # reason `untap_enchanted_creature` and
    # `grant_regeneration_to_enchanted_creature` have theirs: the subject is
    # known from the source's own attachment, so routing it through the
    # targeted destroy would ask for a pick the card never offers — and would
    # find a permanent by index on whichever battlefield the context happened
    # to carry.
    #
    # "…destroy **that land**" (Erosion) is the same referent spelled with the
    # noun repeated instead of the pronoun, and only under an event whose
    # condition already named it -- see `names_attached_permanent`. Asked here,
    # above the "that" branch below, because that branch reads the *firing
    # event's* object and would destroy whatever the fire site had stamped.
    # "When **enchanted creature** becomes the target of a spell or ability,
    # destroy **that creature**." (Spinal Graft.) The same referent again, under
    # a condition kind that is *also* printed about the source itself — so the
    # event's own subject is what says which, and it is passed rather than
    # inferred from the kind.
    if names_attached_permanent(spec, event, event_subject):
        attached_payload: dict[str, object] = {}
        if node.no_regen:
            attached_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_attached_permanent", "", attached_payload),
        )

    # "**Destroy this Aura.**" (Imprison.) The sentence names its own source —
    # the SELF token, or "this <type>" where the type is the source's own — so
    # like the attached destroy above it chooses nothing and there is nothing
    # for a picker to offer. Its own handler rather than the targeted one for
    # exactly that reason: routed through `destroy_target_permanent` the
    # ability would ask for a pick the card never printed and then destroy
    # whichever permanent the resolution context happened to carry.
    #
    # Above the "that" branch below, and not folded into it: "that creature" is
    # the object a trigger's *event* was about and only exists under an event
    # that recorded one, while "this Aura" is the ability's source and is
    # answerable under every event and none.
    if _is_source(spec):
        self_payload: dict[str, object] = {}
        if node.no_regen:
            self_payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_self", "", self_payload),)

    # "Whenever a Djinn or Efreet enters, **destroy it**." (Suleiman's Legacy.)
    # A bare pronoun that `rebinding.rebind_pronoun_to_event_subject` has already
    # pointed at the trigger's own subject — which is what makes the filter
    # non-source here, and so what tells this apart from the `_is_source` branch
    # above: an "it" the rebinder left alone is still the ability's own source
    # and is destroyed by `destroy_self`.
    #
    # Its own kind rather than the targeted destroy, for `destroy_self`'s and
    # `destroy_bound_permanent`'s reason: the card offered no choice (CR 603.3d),
    # so routing it through the picker would ask for one and then destroy
    # whichever permanent the resolution context happened to carry.
    #
    # Admitted only under an event whose fire site freezes the object, because
    # everywhere else the pronoun has no referent at all.
    if spec.quantifier == "it" and not spec.filter.is_source:
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"it\" names the firing event's object, and this event "
                "records none",
                node=node,
            )
        subject_payload: dict[str, object] = {}
        if node.no_regen:
            subject_payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_event_subject", "", subject_payload),)

    # "…destroy **the blocking creature**." / "…destroy **the attacking
    # creature**." (No Quarter.) A printed *combat role*, which is how a
    # board-wide block trigger names the half of the pair its own condition did
    # not describe — the ability's source is in no combat at all, so neither
    # "this creature" nor "that creature" is available to it.
    #
    # Gated on the event, and the gate is the whole of the card's correctness:
    # a role names the partner under exactly one of the two block events, and
    # under the other one it names the creature the firing is *about*. Read
    # ungated, "destroy the blocking creature" under a blocks trigger would
    # destroy the attacker.
    #
    # Its own kind rather than the targeted destroy, for `destroy_self`'s
    # reason two branches up: the card offered no choice (CR 603.3d), so the
    # picker would ask for one.
    if spec.quantifier in ROLE_NAMES_BLOCK_PARTNER:
        if event not in ROLE_NAMES_BLOCK_PARTNER[spec.quantifier]:
            raise LoweringError(
                f"\"the {spec.quantifier} creature\" names the other half of a "
                "block, and this event announces none it is that half of",
                node=node,
            )
        if filt.card_types not in ((), ("creature",)) or _restrictions_beyond(
            filt, frozenset({"card_types"})
        ):
            # The role *is* the reference; a narrowing on top of it would be a
            # second choice the sentence never offers, and dropped it would
            # destroy a creature the card did not name.
            raise LoweringError(
                "a creature named by its combat role carries no narrowing the "
                "destroy could honour",
                node=node,
            )
        partner_payload: dict[str, object] = {}
        if node.no_regen:
            partner_payload["bypass_regeneration"] = True
        return (
            OracleInstruction(
                "destroy_block_pair_partner", "", partner_payload
            ),
        )

    # "If you win the flip, destroy **the creature you chose**. If you lose the
    # flip, destroy **the creature your opponent chose**." (Mogg Assassin.) Two
    # back-references to two *different* choosers' picks, and which record each
    # names follows from how this engine models the two choices rather than from
    # anything about this card:
    #
    # * the ability's controller picks at **announcement** (CR 601.2c), so
    #   "you chose" is the ``choose_target_permanent`` step's record;
    # * any other seat picks at **resolution**, through the ordinary
    #   ``choose_permanent`` prompt, so "your opponent chose" is that step's.
    #
    # Both gated on the record really having been written, which is the rule
    # every back-reference in this package follows: without the step in front of
    # it the words name nothing, and a destroy reading an empty record is a card
    # that compiles clean and destroys nothing.
    if spec.quantifier in _CHOSEN_BY_RECORDS:
        record = _CHOSEN_BY_RECORDS[spec.quantifier]
        if record not in produced:
            raise LoweringError(
                f"back-reference to {record!r} with no producer in this effect",
                node=node,
            )
        if _restrictions_beyond(filt, frozenset({"card_types"})):
            # The noun restates what was chosen; it does not narrow it. A phrase
            # carrying anything more would be describing a *different* object,
            # and the record cannot be re-filtered — the pick is already made.
            raise LoweringError(
                "a chosen object carries no narrowing the destroy could honour",
                node=node,
            )
        chosen_payload: dict[str, object] = {"permanents_from": record}
        if node.no_regen:
            chosen_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_target_permanent", "", chosen_payload),
        )

    # "Whenever enchanted creature deals damage to a creature, destroy **the
    # other creature**." (Venomous Fangs.) English's "other" contrasts with the
    # nearest antecedent noun phrase, and a damage event has exactly two objects
    # -- the trigger's own condition named the damager, so the word names the one
    # that took it. Which is the same object "that <noun>" names under this
    # event, and it rides the same instruction and the same
    # ``target_permanent_id`` the fire site stamps.
    #
    # A branch of its own rather than a second word on the "that" guard below,
    # because that guard opens onto four readings this word does not have: the
    # attachment record, the two delayed-agent tables and the event subject. "The
    # other" under a *delayed* ability is Infinite Authority's, and
    # ``lowering/delayed.py`` already reads it there.
    #
    # Gated on ``_EVENT_STAMPED_TARGET_OBJECTS`` exactly as that branch is, and
    # for its reason: under any other event there is no second object for the
    # word to contrast with, and a destroy reading an unstamped id would resolve
    # nothing while the card reported supported.
    if spec.quantifier == "other":
        if event not in _EVENT_STAMPED_TARGET_OBJECTS:
            raise LoweringError(
                "\"the other creature\" names the second object of the firing "
                "event, and this event announces only one",
                node=node,
            )
        if _restrictions_beyond(filt, frozenset({"card_types"})):
            # The noun restates the object the event already named; a narrowing
            # on top of it would be a second choice the sentence never offers,
            # and dropped it would destroy a permanent the card did not name.
            raise LoweringError(
                "\"the other creature\" carries no narrowing the destroy could "
                "honour",
                node=node,
            )
        other_payload = _filter_payload(filt)
        if node.no_regen:
            other_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_target_permanent", "", other_payload),
        )

    # "…destroy **that planeswalker**." (Hooded Blightfang.) "That" is not a
    # target the card ever asked for — it is the object the trigger's event was
    # about, which the fire site stamps onto the stack item by permanent id. So
    # this rides the ordinary destroy handler and simply does not describe a
    # cast-time target: `_describe_targets` below would raise a picker for a
    # choice CR 603.3d says was never offered. Admitted only under the events
    # whose fire site records one, because everywhere else "that" has no
    # referent and a bare destroy would hit whatever the context happened to
    # hold.
    if spec.quantifier == "that":
        # "…then destroy **that creature** and it can't be regenerated."
        # (Consuming Ferocity.) The permanent the Aura is attached to, named
        # "enchanted creature" by the step in front of this one — so it is the
        # ordinary attached destroy, and the only thing that makes the pronoun
        # readable is that record. Checked rather than assumed: with no such
        # step the words name nothing, and a destroy that reached the
        # attachment anyway would be reading a card that never said
        # "enchanted".
        #
        # Ahead of the delayed and event-subject branches below because it is
        # the narrower question: those ask what a *trigger* recorded, and this
        # asks what an earlier step of this same effect did (CR 608.2h).
        if ATTACHED_PERMANENT_CONTROLLER in produced:
            attached_payload: dict[str, object] = {}
            if node.no_regen:
                attached_payload["bypass_regeneration"] = True
            return (
                OracleInstruction(
                    "destroy_attached_permanent", "", attached_payload
                ),
            )
        # "…destroy **that creature**" inside a *delayed* ability (War Barge).
        # The object is the one the creating ability bound (CR 603.7c), carried
        # by id in the trigger's context — never a pick, and never the object
        # the delay *watched*, which for this card is the artifact itself. Its
        # own kind for the reason `destroy_self` and `destroy_attached_permanent`
        # have theirs: routed through the targeted destroy the ability would ask
        # for a choice the card never offered, and then destroy whichever
        # permanent the resolution context happened to carry.
        # "Whenever target creature deals combat damage to a non-Wall creature
        # this turn, destroy **that non-Wall creature**." (Acidic Dagger.) The
        # event has two objects and the words name the *other* one: the entry is
        # bound to the creature that dealt the damage, and the phrase restates
        # the one that took it. Read before the bound branch below, which would
        # destroy the Dagger's own target — the creature its controller aimed
        # the ability at, which is the opposite of what the card does.
        if event in _DELAYED_AGENT_EVENTS:
            agent_payload = _filter_payload(filt)
            if node.no_regen:
                agent_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_delayed_agent", "", agent_payload),
            )
        if event in _BOUND_OBJECT_DELAYED_EVENTS:
            bound_payload = _filter_payload(filt)
            if node.no_regen:
                bound_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_bound_permanent", "", bound_payload),
            )
        if event not in _EVENT_STAMPED_TARGET_OBJECTS:
            raise LoweringError(
                "\"that\" names the firing event's object, and this event records none",
                node=node,
            )
        payload = _filter_payload(filt)
        if node.no_regen:
            payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_target_permanent", "", payload),)

    # "Destroy X target snow lands." (Avalanche.) "Up to two target creatures"
    # is the same shape with a printed number instead of an announced one, and
    # both are what `_names_several_targets` names: a chosen *list*, not a
    # chosen permanent.
    #
    # This branch is why "up to two" used to fall through to the single-target
    # path below and emit an instruction with **no target description at all** —
    # `_targets_payload` refuses a several-target spec, so `_describe_targets`
    # added nothing, the picker had nothing to read, and the card would have
    # destroyed one permanent of the two it names. No card in the pool prints
    # it, which is the only reason that was latent rather than live.
    #
    # Gated to a filter `destroy_target_permanent`'s list branch answers in
    # full, exactly as the untap beside it is: a narrowing dropped from a
    # several-target destroy is not a spell that does less, it is one that
    # destroys the wrong permanents.
    if _names_several_targets(spec):
        leftovers = _restrictions_beyond(spec.filter, SEVERAL_DESTROY_NARROWINGS)
        if leftovers:
            raise LoweringError(
                "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        several = testable_filter_payload(
            spec.filter,
            refusal="the several-target destroy cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        if node.no_regen:
            several["bypass_regeneration"] = True
        _describe_several_targets(several, spec)
        return (OracleInstruction("destroy_target_permanent", "", several),)

    if spec.quantifier not in ("target", "up_to"):
        raise LoweringError("unsupported destroy quantifier", node=node)

    if filt.their_choice:
        return _lower_destroy_of_their_choice(node, spec, event)

    # "Destroy target artifact **with mana value X**." (Detonate.) The bound is
    # the X chosen on the cast, so it has no literal to ride the payload as an
    # ordinary narrowing — it is split off into a flag the legality check reads
    # against that X, exactly as Spell Blast's counter does. Splitting it out
    # rather than leaving it on the filter is what keeps `_filter_payload` free
    # to go on refusing every *other* variable bound.
    mv_equals_x = is_mana_value_x(filt.mana_value)
    if mv_equals_x:
        # Off the *spec* as well as the local filter: `_describe_targets` below
        # builds the picker's description from the spec's own filter, so a copy
        # left behind there would refuse the line at that call instead.
        filt = dataclasses.replace(filt, mana_value=None)
        spec = dataclasses.replace(spec, filter=filt)
    payload = _filter_payload(filt)
    if mv_equals_x:
        payload["mv_equals_x"] = True
    if node.no_regen:
        payload["bypass_regeneration"] = True
    _describe_targets(payload, spec)
    return (OracleInstruction("destroy_target_permanent", "", payload),)



#: Which scratchpad record each "the <noun> <somebody> chose" phrase names.
#:
#: Two entries and they are not two cards: they are this engine's two ways of
#: making a choice, named by the seat that made it. ``back_references`` reads
#: the printed clause into the quantifier; this says what the quantifier means.
_CHOSEN_BY_RECORDS: dict[str, str] = {
    "chosen_by_you": CHOSEN_TARGET_PERMANENTS,
    "chosen_by_opponent": CHOSEN_PERMANENT,
}


def _lower_destroy_of_their_choice(
    node: ast.Destroy, spec: ast.TargetSpec, event: str | None
) -> tuple[OracleInstruction, ...]:
    """"…destroy target nonartifact creature **that player controls of their
    choice**." (The Abyss.)

    Preacher's decomposition, and for Preacher's reason: the pick belongs to a
    seat that is not the ability's controller, so it is the ordinary
    ``choose_permanent`` prompt — armed on that seat, answered into the
    resolution's scratchpad — and the destroy behind it reads the recorded id
    through ``permanents_from`` instead of a target. Both halves already exist;
    what is new is only the pairing, exactly as it was there.

    A deliberate, recorded deviation from CR 603.3d, the same one Preacher's
    branch in ``control_changes`` documents: the printed word is "target", and a
    triggered ability's targets are chosen as it is *put on the stack*. This
    engine announces an upkeep trigger's targets from one seat, so the affected
    player's pick is made at resolution instead. What that costs is the CR
    608.2b re-check and shroud on the picked creature; what the alternative
    costs is a second seat inside the upkeep step's announcement.

    Three refusals, and each is a way the phrase could otherwise mean something
    the card does not print:

    * a quantifier other than "target" — "of their choice" names one pick, and
      the prompt records one id;
    * a controller other than "that player" — "their" is a pronoun, and the
      only player this sentence has already named is the one the condition did;
    * an event that froze no seat, which is :func:`_refuse_unfrozen_that_player`
      one branch over: with no seat there is nobody to ask, and a prompt armed
      on nobody is an effect that silently does not happen.
    """
    filt = spec.filter
    if spec.quantifier != "target":
        raise LoweringError(
            "'of their choice' names one permanent to destroy", node=node
        )
    described = _filter_payload(
        filt, carried_separately=frozenset({"their_choice"})
    )
    _refuse_unfrozen_that_player(described, event, node)
    if described.get("controller") != "that_player":
        raise LoweringError(
            "'of their choice' names no player this destroy can ask", node=node
        )
    # Both lifted, not carried. Who picks is the prompt's own seat and no
    # candidate can be asked whether it is "of their choice"; whose creatures
    # may be picked is the prompt's ``controlled_by``, because
    # ``subject_matches`` refuses ``that_player`` outright — the seat is known
    # only to the resolution holding the trigger's context, which is where the
    # prompt is armed. Left in the payload either one would be a key the
    # candidate rule cannot test, which is the whole point of the gate below.
    described.pop("their_choice", None)
    described.pop("controller", None)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the destroy prompt cannot test this restriction", node=node
        )
    destroy_payload: dict[str, object] = {"permanents_from": CHOSEN_PERMANENT}
    if node.no_regen:
        destroy_payload["bypass_regeneration"] = True
    return (
        OracleInstruction("sequence", "", {"steps": (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": CHOSEN_PERMANENT,
                    # "**That player** … of **their** choice": one seat named
                    # twice, so the prompt is armed on the seat the firing
                    # event froze and the candidates come from that same seat's
                    # battlefield. `controlled_by` is what makes the second
                    # half a seat question rather than a filter key — the
                    # matcher answers "you control" relative to the *ability's*
                    # controller, which is the wrong player here.
                    "chooser": EVENT_SUBJECT_PLAYER,
                    "controlled_by": "chooser",
                    "filter": described,
                    "prompt": "Choose a creature you control to be destroyed.",
                },
            ),
            OracleInstruction("destroy_target_permanent", "", destroy_payload),
        )}),
    )
