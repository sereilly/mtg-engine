"""Lowering destruction: CR 701.7, and the delayed and conditional forms of it.

Split out of ``board`` at the thousand-line guard — a cap neither parallel
branch crossed alone, which is what made the boundary visible: one added an
activated ability's delayed destroy and the other a per-payer sweep, and both
are destruction rather than board changes generally.

The line is the CR's own keyword action. Destroying a permanent (CR 701.7) is
not sacrificing one (CR 701.17), regenerating one (CR 701.15), phasing one out
(CR 702.26) or exchanging control of one, and those are what ``board`` keeps.
The two halves share no name in either direction — checked at the split rather
than assumed — so this is a family boundary and not a size cut.
"""

import dataclasses

from ...oracle_types import (CHOSEN_THIS_WAY_OBJECTS, CHOSEN_TARGET_PERMANENTS,
                             COST_TARGET_BASE, COST_TARGET_PER,
                             OracleInstruction)
from ...subject_filters import (
    OBJECT_ONLY_FILTER_KEYS, TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter,
    untestable_filter_keys,
)
from .. import ast
from ..errors import LoweringError
from ._common import (describe_independent_target_roles, _describe_several_targets,
                      _describe_targets, _filter_payload, _is_source, _is_target,
                      _names_several_targets, _restrictions_beyond,
                      is_mana_value_x)
from ._records import optional_cost_key
from ._events import (_RECORDED_PERMANENTS, _EVENT_SUBJECT_PLAYERS,
                      EVENT_SUBJECT_PLAYER, binds_block_pair, names_attached_permanent,
                      CHOSEN_PERMANENT, _BOUND_OBJECT_DELAYED_EVENTS)


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


# Trigger events whose fire site stamps the object the event was about onto the
# stack item, so an effect may say "that <noun>" and mean it.


_EVENT_SUBJECT_DESTROY_EVENTS: frozenset[str] = frozenset({
    # Hooded Blightfang: "… deals damage to a planeswalker, destroy **that**
    # planeswalker". The damaged object is what `damage_events._announce`
    # stamps onto the stack item, so "that <noun>" under this event names it.
    # A damage event whose recipient was a player stamps nothing, and the
    # destroy then resolves nothing rather than finding a permanent by index.
    "damage_dealt",
})


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
    if node.delay:
        return _lower_delayed_destroy(node, event, event_subject, produced)
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("destroy needs an object target", node=node)
    spec = node.subject
    filt = spec.filter

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
            if untestable_filter_keys(described):
                raise LoweringError("no sweep handler for this narrowing", node=node)
            _refuse_unfrozen_that_player(described, event, node)
            narrowed_payload = dict(described)
            if node.no_regen:
                narrowed_payload["bypass_regeneration"] = True
            return (
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
    if names_attached_permanent(spec, event):
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
        # "…destroy **that creature**" inside a *delayed* ability (War Barge).
        # The object is the one the creating ability bound (CR 603.7c), carried
        # by id in the trigger's context — never a pick, and never the object
        # the delay *watched*, which for this card is the artifact itself. Its
        # own kind for the reason `destroy_self` and `destroy_attached_permanent`
        # have theirs: routed through the targeted destroy the ability would ask
        # for a choice the card never offered, and then destroy whichever
        # permanent the resolution context happened to carry.
        if event in _BOUND_OBJECT_DELAYED_EVENTS:
            bound_payload = _filter_payload(filt)
            if node.no_regen:
                bound_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_bound_permanent", "", bound_payload),
            )
        if event not in _EVENT_SUBJECT_DESTROY_EVENTS:
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
        leftovers = _restrictions_beyond(
            spec.filter,
            frozenset({
                "card_types", "supertypes", "subtypes", "colors", "controller",
                "other_than_source",
            }),
        )
        if leftovers:
            raise LoweringError(
                "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        several = _filter_payload(spec.filter)
        if set(several) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the several-target destroy cannot test this restriction", node=node
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



#: The filter keys ``destroy_target_permanent``'s several-target branch tests in
#: full, and therefore the only ones a fused announcement may narrow by. The
#: same set the ``_names_several_targets`` branch of :func:`_lower_destroy`
#: states inline, named once because two readings of "what may a list of destroy
#: targets be narrowed by" is one reading too many -- and the direction the
#: second one drifts is a narrowing dropped from a sweep, which destroys
#: permanents the card does not name.
_SEVERAL_DESTROY_NARROWINGS = frozenset({
    "card_types", "supertypes", "subtypes", "colors", "controller",
    "other_than_source",
})


def _repeated_destroy_clause(
    step: ast.Statement,
) -> tuple[str, ast.Destroy, tuple[ast.Statement, ...]] | None:
    """Split "**for each additional {1}{R} you paid,** destroy another target
    artifact[, and <rider>]" into (offer, the destroy, the riders).

    None for any other step, which is how the fuser below declines a sentence it
    does not recognise instead of half-reading one.
    """
    if not isinstance(step, ast.ForEach):
        return None
    if not isinstance(step.iterator, ast.EachAdditionalCostPaid):
        return None
    body = step.effect
    riders: tuple[ast.Statement, ...] = ()
    if isinstance(body, ast.Sequence):
        if not body.steps:
            return None
        body, riders = body.steps[0], body.steps[1:]
    if not isinstance(body, ast.Destroy):
        return None
    return step.iterator.symbols, body, riders


def _fused_cost_repeated_destroys(
    steps: tuple[ast.Statement, ...],
    lower_statement,
) -> tuple[OracleInstruction, ...] | None:
    """"Destroy target artifact. **For each additional {1}{R} you paid, destroy
    another target artifact. For each additional {1}{G} you paid, destroy
    another target artifact, and you gain 1 life.**" (Primitive Justice.)

    One announcement, not three. CR 601.2b announces the optional additional
    costs and CR 601.2c then fixes the number of targets -- so by the time the
    caster is asked what to destroy, the spell wants exactly
    ``1 + n({1}{R}) + n({1}{G})`` artifacts, and the printed "**another**" makes
    them distinct (CR 601.2c: "the same target can't be chosen multiple times
    for any one instance of the word 'target'"). That is a *list*, which
    ``destroy_target_permanent`` has resolved since Avalanche; what is new here
    is only where its length comes from.

    Fusing rather than a slot per clause, for :func:`_fused_two_target_pump`'s
    reason one family over: three targeted destroys lowered as three steps all
    resolve through ``_one_choice``, which reads the *first* entry of the target
    list -- so the card would compile supported and destroy one artifact three
    times. ``_refuse_unfused_distinctness`` refuses exactly that, and says in
    its own docstring that a shape which grows a fused lowering is claimed above
    it and never reaches it. This is that shape.

    **The riders keep their loop and move behind the destroy.** "…, and you gain
    1 life" happens once per {1}{G} paid, so it stays inside a ``for_each`` over
    that offer; what it loses is its position *between* the destroys. Nothing
    can observe the difference: no player receives priority inside a resolution
    (CR 117.3b) and state-based actions are not checked until it ends
    (CR 704.3), so the only ordering a spell's own steps can expose is one step
    reading what an earlier one did -- and a life gain reads no artifact.

    **Destroy only**, though the shape is the verb's to share: this is a several
    -target announcement, and only a handler that resolves a *list* may be given
    one (``_describe_several_targets`` states the rule and
    ``_names_several_targets`` enforces it everywhere else). A second verb is one
    branch here the day its handler reads a list; admitting one now would fuse
    three targets onto a handler that reads the first.

    Refuses rather than declines where the sentence is *nearly* this shape,
    because a decline falls through to the unfused refusal and the card is then
    reported unsupported for the wrong reason:

    * a first clause printing "another" has no prior choice to differ from;
    * a repeated clause that does **not** print it names a target CR 601.2c
      would let collide with the first, which is the silent double destroy;
    * clauses whose noun phrases differ are two announcements rather than one
      list -- one filter cannot describe both, and the picker would offer
      whichever noun the fuse happened to keep.
    """
    if len(steps) < 2:
        return None
    first, rest = steps[0], steps[1:]
    if not isinstance(first, ast.Destroy) or first.delay or first.also_targets:
        return None
    if not _is_target(first.subject):
        return None
    repeats = [_repeated_destroy_clause(step) for step in rest]
    if any(found is None for found in repeats):
        return None
    assert isinstance(first.subject, ast.TargetSpec)
    if first.subject.distinct_from_prior:
        raise LoweringError(
            'the first clause of a sentence cannot name "another" target',
            node=first,
        )
    per_offer: dict[str, int] = {}
    riders: list[OracleInstruction] = []
    for offer, destroy, tail in repeats:
        if destroy.delay or destroy.also_targets or not _is_target(destroy.subject):
            return None
        assert isinstance(destroy.subject, ast.TargetSpec)
        if not destroy.subject.distinct_from_prior:
            raise LoweringError(
                "a destroy repeated per additional payment names a *new* target "
                'only when it prints "another"', node=destroy,
            )
        if (
            destroy.subject.filter != first.subject.filter
            or destroy.no_regen != first.no_regen
        ):
            raise LoweringError(
                "the clauses of one target announcement must name one noun "
                "phrase", node=destroy,
            )
        key = optional_cost_key(offer)
        if key in per_offer:
            # Two clauses reading back one offer would each add to the count
            # while the picker showed one number. ``cast_costs`` refuses the
            # same collision on the announcing side, for the same reason: one
            # key, one count, and no way to say which clause spent it.
            raise LoweringError(
                "one additional cost cannot size two target clauses",
                node=destroy,
            )
        per_offer[key] = 1
        if tail:
            riders.append(
                OracleInstruction(
                    "for_each", "",
                    {
                        "iterator": {"repeat_from_cost": key},
                        "effect": lower_statement(
                            ast.Sequence(tail) if len(tail) > 1 else tail[0],
                            frozenset(), whole_effect=False,
                        ),
                    },
                )
            )
    filt = first.subject.filter
    leftovers = _restrictions_beyond(filt, _SEVERAL_DESTROY_NARROWINGS)
    if leftovers:
        raise LoweringError(
            "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
            node=first,
        )
    described = _filter_payload(filt)
    if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the several-target destroy cannot test this restriction", node=first
        )
    payload: dict[str, object] = dict(described)
    if first.no_regen:
        payload["bypass_regeneration"] = True
    payload["targets"] = {
        "quantifier": first.subject.quantifier,
        "kind": "object",
        "filter": _filter_payload(filt),
        # The size of the announcement as the *arithmetic*, not as a number:
        # what the caster paid is unknown until they announce it, and the
        # picker, the cast gate and the AI all resolve it through one reader
        # (``oracle_types.cost_target_count``).
        "count": {COST_TARGET_BASE: 1, COST_TARGET_PER: per_offer},
        # The printed "another" (CR 601.2c), carried rather than folded into the
        # filter for ``_fused_two_target_pump``'s reason: it is a relation
        # between slots, not a property of one permanent, so
        # ``permanent_matches_filter`` could never test it.
        "distinct": True,
    }
    return (OracleInstruction("destroy_target_permanent", "", payload), *riders)


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


def _lower_delayed_destroy(
    node: ast.Destroy,
    event: str | None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"…destroy that creature at end of combat." (Thicket Basilisk, Cockatrice.)

    The handler destroys the creature this one blocked or was blocked by, which
    is a fact only the trigger knows — so the *event* is checked as strictly as
    the subject is. Under any other trigger the same sentence names a creature
    nobody recorded, and the handler would destroy nothing while the card
    reported as supported.

    **The other printing of the same delay is an activated ability's tail**:
    "Target creature you control can't be blocked this turn. Destroy it and
    this creature at end of combat." (Goblin Sappers.) No trigger has fired, so
    there is no pair to read — the sentence names what the step in front of it
    chose, and what it lowers to is CR 603.7's delayed ability rather than the
    block-pair handler. Read first, because its two subjects ("it", the source)
    are ones the pair reading refuses anyway, and refusing them here with the
    producer named is the more useful failure.
    """
    delayed = _lower_activated_delayed_destroy(node, produced)
    if delayed is not None:
        return delayed
    if not binds_block_pair(event, event_subject):
        raise LoweringError(
            "a delayed destroy at end of combat only has a handler on a "
            "blocks-or-blocked trigger that names one creature",
            node=node,
        )
    spec = node.subject
    # "that creature" (Thicket Basilisk) and "**the other** creature" (Infinite
    # Authority) are one referent under this event: the pair has two members,
    # the ability's own creature is one of them, and both spellings name the
    # one `block_pair_permanents` returns. The ordinal is admitted only here,
    # where a pair is what the trigger bound.
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("that", "other"):
        raise LoweringError(
            "the end-of-combat destroy acts on the creature the trigger bound", node=node
        )
    filt = spec.filter
    if filt.card_types != ("creature",) or _restrictions_beyond(
        filt, frozenset({"card_types", "subtypes"})
    ):
        raise LoweringError("no delayed-destroy handler narrows what it destroys", node=node)
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration", node=node
        )
    # "destroy that **Wall**" (Battering Ram). The trigger that fired already
    # required a Wall, so the noun re-states what was bound rather than choosing
    # again — but it rides the payload and the handler tests it anyway, because
    # a word consumed and never read is a word that could be deleted.
    payload: dict[str, object] = {}
    if filt.subtypes:
        payload["subtype_filter"] = filt.subtypes[0]
    return (OracleInstruction("delayed_destroy_blocked_or_blocker", "", payload),)


def _lower_activated_delayed_destroy(
    node: ast.Destroy, produced: frozenset[str]
) -> tuple[OracleInstruction, ...] | None:
    """"…Destroy it [and this creature] at end of combat." (Goblin Sappers.)

    Returns None — the caller falls through to the block-pair reading — unless
    the subject is one of the two this shape names.

    **"It" is gated on a producer**, and that gate is the whole of the card's
    correctness. `parse_recipient` reads a bare "it" as the ability's own
    source, so with nothing recorded the Sappers' first ability would arm two
    delayed destructions of the Sappers and never touch the creature it made
    unblockable — a card that compiles, resolves, logs, and does the wrong
    thing. The producer is the record the step in front wrote
    (`_RECORDED_PERMANENTS`); the entry then binds the ability's chosen target,
    which for a one-target ability is the same permanent by construction.

    **"This creature" needs no producer** and takes no binding: CR 603.7d
    freezes the creating ability's source into the entry, and `destroy_self`
    reads it back. That is why the two subjects lower to two different inner
    instructions rather than one with a flag — an entry that bound nothing and
    then destroyed "the bound object" would destroy nothing at all.

    `no_regen` refuses, for `_lower_delayed_destroy`'s reason one screen down:
    neither inner handler is asked to bypass regeneration here, and a clause
    read and dropped is a creature that regenerates from a card that says it
    cannot.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec):
        return None
    # "…**destroy that creature** at end of combat." (Winter's Chill.) The
    # third subject this shape names, and the one a loop supplies: the sentence
    # sits inside "for each of those creatures", so it is about the creature the
    # iteration is on and there is no block pair to read. Gated on the producer
    # for the "it" branch's reason — with no earlier step that chose a set of
    # permanents the words name nothing, and the block-pair reading below is the
    # better refusal for the cards that really are about a pair.
    if spec.quantifier == "that" and CHOSEN_TARGET_PERMANENTS in produced:
        if _restrictions_beyond(spec.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound creature carries no narrowing the destroy could honour",
                node=node,
            )
        if node.no_regen:
            raise LoweringError(
                "the end-of-combat destroy handler does not bypass regeneration",
                node=node,
            )
        return (
            OracleInstruction("create_delayed_trigger", "", {
                "event": "next_end_of_combat",
                "instruction": OracleInstruction("destroy_bound_permanent", "", {}),
                "once": True,
                "duration": "end_of_turn",
                "binds_target": True,
            }),
        )
    # The pronoun is read **before** the self-reference, and the order is the
    # card: `parse_recipient` gives a bare "it" the same `is_source` filter a
    # card naming itself gets, and tells them apart by the quantifier alone. Put
    # the other way round, "Destroy it and this creature" arms two destructions
    # of the Sappers and leaves the unblockable creature alone — the card
    # compiling, resolving, logging, and doing the wrong thing.
    if spec.quantifier == "it":
        if not spec.filter.is_source:
            # A rebound pronoun (an "it" the parser pointed at a trigger's
            # event subject) is not this shape: the referent is the event's,
            # not an earlier step's.
            return None
        if _RECORDED_PERMANENTS.isdisjoint(produced):
            raise LoweringError(
                "\"it\" names the permanent an earlier step of this effect "
                "chose, and no step here recorded one",
                node=node,
            )
        inner = OracleInstruction("destroy_bound_permanent", "", {})
    elif _is_source(spec):
        inner = OracleInstruction("destroy_self", "", {})
    else:
        return None
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration",
            node=node,
        )
    return (
        OracleInstruction("create_delayed_trigger", "", {
            "event": "next_end_of_combat",
            "instruction": inner,
            # CR 603.7b: "at end of combat" names one moment, so the ability
            # fires once and expires with the turn if that moment never comes.
            "once": True,
            "duration": "end_of_turn",
            **({"binds_target": True} if inner.kind == "destroy_bound_permanent" else {}),
        }),
    )


def _lower_for_each_destroyed(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each creature that died this way,** <effect>." (Glyph of
    Reincarnation.)

    A loop over the objects an earlier step of *this same effect* destroyed —
    the set behind ``destroyed_this_way``, which the sweep handlers record
    because by the time this runs the board no longer holds it. Here rather
    than beside ``_lower_for_each`` in ``lowering/counters``: that one repeats a
    counter placement a fixed number of times and never looks at what died,
    while this is about the destroy family's own record.

    Refused without a producer, as every back-reference in this grammar is:
    "this way" with no earlier step names nothing at all, and an empty loop is a
    sentence that reports supported and does not run.

    The inner statement arrives already lowered, the way ``lower_where_x``'s
    does and for its reason — nothing here cares how it was lowered, only that
    it is repeated once per object.
    """
    if "destroyed_this_way" not in produced:
        raise LoweringError(
            "'died this way' with no earlier step in this effect that "
            "destroyed anything", node=node,
        )
    filt = node.iterator.filter
    narrowing = filt.to_payload()
    # The narrowing is held to what the *pure* matcher can answer, because that
    # is what the loop uses: the objects are in graveyards by the time this runs,
    # so there is no observer and no board to ask a layer question of, and every
    # key it does answer it answers off last-known information (CR 608.2h).
    #
    # It read the card type alone until Mirage printed "If **a white creature**
    # dies this way" (Cinder Cloud) — a colour is exactly as answerable, and the
    # refusal was a list of one key rather than a statement about the matcher.
    if untestable_filter_keys(narrowing, allowed=OBJECT_ONLY_FILTER_KEYS) or (
        filt.zone != "battlefield"
    ):
        raise LoweringError(
            "'died this way' iterates what the earlier step destroyed and is "
            "narrowed only by what the matcher can ask of an object that has "
            "left", node=node,
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # Named rather than implied: the loop reads the objects an
                # earlier step recorded under this key, and the key is what
                # ties the two halves of the sentence together.
                #
                # The printed card type rides beside it. It is normally a
                # restatement of what the sweep destroyed — "for each
                # **creature** that died this way" after a creature sweep, "for
                # each **land** destroyed this way" after a land sweep — but a
                # restatement is only ever as reliable as the reader that checks
                # it, and the loop applies it to the record rather than
                # assuming the two agree.
                "iterator": {
                    "produced_by": "destroyed_this_way_objects", **narrowing,
                },
                "effect": inner,
            },
        ),
    )
