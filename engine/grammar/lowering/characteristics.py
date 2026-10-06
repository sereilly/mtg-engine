"""Lowering what a permanent is: P/T modifications, a doubling, printed text.

**The list this docstring used to open with is four splits out of date**, and
reading it as the module's seam is how Stronghold's second wave nearly cut in
the wrong place. Counters went to `counters.py` (CR 122 is not a characteristic
at all), keyword grants and removals to `keywords.py`/`keyword_removal.py`
(layer 6), colour and type changes to `types.py` (layers 4 and 5), and base-P/T
*setting* to `base_pt.py` (CR 613.4b, replacing a value rather than modifying
one). Every one of those cuts left the sentence describing it behind, so the
prose kept naming a module that had already gone.

What is actually here is the CR 613 layer-7 **modification**: a pump (7c) in
every printed spelling the pool has, a switch (7d), a power doubling — and
`mark_text_modified`, CR 612's layer-3 rewrite, which is the one thing left that
is not P/T. The fusers that fold a two-clause sentence whose *payoff* is a pump
are not here: a fuser lives with the sequence it folds, which is
`sequences.py`'s own rule and where its twins already were.

A continuous effect with no duration is refused here rather than lowered, and
`_durationless_reason` in `_common` says why per subject: the refusal names
what is missing instead of producing an effect that never ends.

A **fifth** cut followed at Mercadian Masques' first wave, and it is the only
one that took a slice of `_lower_pump` rather than a whole node: every reading
of a pump whose *size is a count* went to `_counted_pumps`, along the line
`_counted_damage` was cut from `damage.py` along — CR 107.2/107.3's, the
counted quantity against the sentence that spends it. `_TARGET_PUMP_DURATIONS`
went with them and is imported back, because a table with a reader on each side
of a cut belongs on the floor rather than in one of the two families.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import (object_only_filter,
                                unimplemented_filter_keywords,
                                untestable_filter_keys)
from .. import ast
from ..errors import LoweringError
from ._amounts import (
    count_spec,
    _per_each_amount,
    _per_each_offset,
    _static_x_amount,
    _x_definition_spec,
)
from ._counted_pumps import _TARGET_PUMP_DURATIONS, lower_counted_pump
from ._events import (binds_block_pair, _EVENT_SUBJECT_OBJECTS,
                      ROLE_NAMES_EVENT_SUBJECT)
from ._common import (
    _describe_several_targets,
    _describe_targets,
    _durationless_reason,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    _signed,
)






#: The ``buff_creatures_global`` payload keys the sweep below writes one at a
#: time, each for one printed narrowing. A description key outside this set has
#: no hand-written test behind it, so it travels as the whole filter and is
#: answered by ``subject_matches`` — see the emit site.
#:
#: A *set of description keys*, not of payload keys: the two spellings differ
#: (``card_types`` reaches the payload as ``type_filter``), and it is the
#: description this is subtracted from.
_GLOBAL_BUFF_PAYLOAD_KEYS = frozenset({
    "type_filter", "color_filter", "exclude_colors", "subtype_filter",
    "exclude_types", "with_keywords", "attacking_only", "blocking_only",
    "controller", "exclude_self",
})




def _lower_pump(
    node: ast.Pump,
    event: str | None = None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """The printed P/T modification, and which permanent it lands on.

    *event* and *event_subject* are the firing trigger's kind and its printed
    narrowing, for the one subject that is neither the source, a target, a host
    nor a class: the other half of a block the trigger bound. They default to
    None so the static reading in ``statics.py`` — which has no trigger at all
    — is unchanged, and so is every caller that never had one.
    """
    # A pump whose **size is a count** — every printed spelling of it,
    # in `_counted_pumps`. Head of this branch list rather than one of its
    # arms: the count is what decides which handler the sentence reaches
    # at all (a continuous `dynamic_pt_bonus`, a one-shot `pump_self`, the
    # team buff, the bound target, the event's own subject), so a reading
    # placed after the subject branches below would be a counted pump
    # sized by its printed number alone.
    counted = lower_counted_pump(node, event)
    if counted is not None:
        return counted
    if node.duration.kind is None:
        # "This creature gets +X/+0, where X is the greatest power among
        # creature cards in your graveyard." (Carrion Grub.) A pump with no
        # duration is a *continuous* effect, which is why the general case
        # refuses — but one on the ability's own source, with its size computed
        # from a spec the shared evaluator reads, is exactly the CR 613 layer 7c
        # contribution the P/T refresh already rebuilds every recompute
        # (engine/mixins/permanent_state.py). What made it unreachable was not
        # the layer, it was having no way to say how big it is.
        if node.x_definition is not None and _is_source(node.subject):
            return (
                OracleInstruction("dynamic_pt_bonus", "", {
                    "power": _static_x_amount(node.power, node.power_negative, node),
                    "toughness": _static_x_amount(
                        node.toughness, node.toughness_negative, node
                    ),
                    "x_from_count": _x_definition_spec(node.x_definition, node),
                }),
            )
        # "{1}{R}: This creature gets +2/+0 …" (Goblin Ski Patrol) — a
        # *resolved* ability's modification with no duration printed, which
        # CR 611.2a makes one that lasts indefinitely. It is not the continuous
        # effect the refusal below is about: a static ability contributes
        # afresh on every layer recompute and is refused one layer up
        # (`_lower_static_ability`), while this is a one-shot the persistent
        # 7c channel already holds — the same channel a +1/+1 counter writes to,
        # and the one `engine/pt.py` documents as "one-shot modifications that
        # stay until something removes them".
        #
        # Only on the ability's own source. A durationless pump on a *target* or
        # on a class is the same rule and would be lowered the same way, but no
        # card in the pool prints one, and a branch with nothing behind it is a
        # claim nothing checks.
        if _is_source(node.subject):
            return (
                OracleInstruction("pump_self", "", {
                    "power": _signed(node.power, node.power_negative),
                    "toughness": _signed(node.toughness, node.toughness_negative),
                    # Named rather than left absent: every payload written
                    # before this branch means end of turn, so the handler's
                    # default has to stay that, and an indefinite one has to say
                    # so out loud.
                    "duration": "indefinite",
                }),
            )
        raise LoweringError(_durationless_reason(node.subject), node=node)

    if node.x_definition is not None:
        # "gets -X/-X until end of turn, where X is the number of cards in
        # your graveyard" (Liliana, Waker of the Dead). X is defined by a
        # count, so the payload carries what to count and the handler computes
        # it at resolution; the sign travels separately because _signed cannot
        # negate a variable.
        # "…**it** gets +X/+0 until end of turn, where X is the number of other
        # attacking creatures." (Alpine Houndmaster.) The subject is the
        # ability's own source, not a chosen target — a temporary pump on the
        # source is what `pump_self` already does, and what was missing was only
        # a way to say how big it is. Its own kind rather than a flag, for the
        # reason the base-P/T pair is two kinds: one asks a picker which
        # permanent and the other asks the context for the source.
        on_source = _is_source(node.subject)
        # "…**That creature** gets +0/+X until end of turn, where X is its mana
        # value." (Kry Shield.) The bound object the sentence in front of it
        # already targeted, not a second choice — so no ``targets`` description
        # is emitted and the handler acts on the ability's one target, the way
        # ``gain_type`` reads the same pronoun. A bound object carries no
        # narrowing to honour, so a restated adjective refuses rather than being
        # dropped.
        bound = (
            isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
            and not _restrictions_beyond(node.subject.filter, frozenset({"card_types"}))
        )
        # "**Enchanted creature** gets +X/+0 until end of turn, where X is the
        # number of attacking creatures." (Mob Mentality.) A fourth subject and
        # the one an Aura prints: the boost lands on the permanent this one is
        # attached to, which ``pump_enchanted_creature`` already finds, and what
        # was missing was only a way to say how big it is — the same
        # ``x_from_count`` spec the three subjects below carry.
        on_attached = _is_enchanted(node.subject)
        if not on_source and not on_attached and not bound and not _is_target(node.subject):
            raise LoweringError("a where-clause pump needs a single target", node=node)
        # Whichever definition the clause carried — a count, a maximum, or a
        # characteristic of the object the sentence named. Through the one spec
        # builder rather than a type test here, which is what kept "where X is
        # its mana value" out of a sentence that reads a where-clause perfectly
        # well; `_x_definition_spec` refuses what it cannot build.
        # ``recorded=produced``: this branch has a *duration*, so the count is
        # taken once when the ability resolves and the resolution's own
        # scratchpad is there to be read — and what it may read is exactly what
        # a step of this effect wrote. The durationless branch above passes
        # nothing, which refuses the shape outright — see
        # ``_x_definition_spec``.
        definition_spec = _x_definition_spec(
            node.x_definition, node, recorded=produced
        )
        # Only the characteristics the card writes as X are variable: "+X/+0"
        # pumps power alone, so the literal half stays literal.
        payload: dict[str, object] = {
            "power": "x" if isinstance(node.power, ast.Var) else _signed(
                node.power, node.power_negative
            ),
            "toughness": "x" if isinstance(node.toughness, ast.Var) else _signed(
                node.toughness, node.toughness_negative
            ),
            "power_negative": node.power_negative,
            "toughness_negative": node.toughness_negative,
            # The one spec every reader of a computed amount agrees on. The
            # graveyard-only restriction that stood here was the handler's own
            # counter talking; with the shared evaluator behind it, the zone is
            # data like everything else.
            "x_from_count": definition_spec,
        }
        if on_source:
            # ``pump_self`` already boosts the source until end of turn; what was
            # missing was a way to say how big, which is the same
            # ``x_from_count`` spec every other computed amount carries. A second
            # kind would be the same handler with the number arriving by a
            # different road.
            return (OracleInstruction("pump_self", "", payload),)
        if on_attached:
            # The same argument one subject over: the handler already knows
            # which permanent, and the spec is the one every computed amount
            # shares — so the count is resolved by the same evaluator whether
            # the sentence was printed about a source, a target or a host.
            return (OracleInstruction("pump_enchanted_creature", "", payload),)
        assert isinstance(node.subject, ast.TargetSpec)
        if not bound:
            _describe_targets(payload, node.subject)
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    power = _signed(node.power, node.power_negative)
    toughness = _signed(node.toughness, node.toughness_negative)

    if _is_enchanted(node.subject):
        return (
            OracleInstruction(
                "pump_enchanted_creature", "", {"power": power, "toughness": toughness}
            ),
        )
    if _is_source(node.subject):
        return (OracleInstruction("pump_self", "", {"power": power, "toughness": toughness}),)
    # "Whenever this creature blocks or becomes blocked by a creature, **that
    # creature** gets +1/+1 until end of turn." (Flailing Drake.) The other half
    # of the block the trigger fired on — named by the ids the fire site
    # recorded rather than by anything the creature carries, which is why the
    # relation is the whole instruction and nothing is described for a picker.
    #
    # ``pump_block_pair`` is the handler ``engine/flanking.py`` already builds by
    # hand (CR 702.25a); until this branch the *printed* sentence had no road to
    # it, so a card saying in words what flanking says in a keyword compiled to
    # nothing.
    #
    # ``binds_block_pair`` is what admits it, never the kind alone: CR
    # 509.3c/509.3d make a *bare* block trigger fire once with several creatures
    # in hand and no way to say which "that creature" is, so the printed
    # narrowing is the whole difference. Read **before** the target-shaped
    # branch below, and that order is the card: on the *blocks* half of the
    # event the stack item's target is the blocking creature itself (the fire
    # site puts it there so a self-affecting trigger can find itself), so the
    # fall-through would pump the Drake and leave the creature it blocked alone.
    #
    # "…**the other creature**" is the same referent under a different printed
    # word, exactly as ``lowering/keywords.py`` and ``lowering/destruction.py``
    # already read the pair's two spellings as one — and the ordinal is admitted
    # only here, where a pair is what the trigger bound.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("that", "other")
        and binds_block_pair(event, event_subject)
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the block-pair pump reads the creature its trigger already "
                "named and nothing narrower",
                node=node,
            )
        pair_duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
        if pair_duration is None:
            raise LoweringError(
                f"no sweep ends a block pair's pump at {node.duration.kind}",
                node=node,
            )
        pair_payload: dict[str, object] = {"power": power, "toughness": toughness}
        if pair_duration != "end_of_turn":
            pair_payload["duration"] = pair_duration
        return (OracleInstruction("pump_block_pair", "", pair_payload),)
    # The **other** creature in a board-wide combat event: the one the firing
    # is about rather than its partner.
    #
    # "Whenever a creature attacks you, **it** gets -1/-0 until end of turn."
    # (Briar Patch) prints the bare pronoun; "Whenever a creature blocks a black
    # or red creature, **the blocking creature** gets +1/+1 until end of turn."
    # (Righteous Indignation) prints the combat role. One referent, two printed
    # words, so one branch — the split is which table answers "is that word this
    # event's subject", and both answer off a stamp the fire site really makes
    # (``event_subject_permanent_id``).
    #
    # Neither word can be rewritten at parse time the way an attached subject's
    # is: a board-wide condition's subject describes a **set**, so
    # ``rebind_pronoun_to_event_subject`` leaves the pronoun alone and the
    # referent has to be resolved from the announcement instead
    # (``pump_event_subject``, which re-checks the printed noun phrase at
    # resolution).
    #
    # Read after the block-pair branch above, and the order is the card: under a
    # *blocks* event "that creature" is the partner and "the blocking creature"
    # is the subject, and the two branches must not compete for one word.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and (
            (
                node.subject.quantifier == "it"
                and not node.subject.filter.is_source
                and event in _EVENT_SUBJECT_OBJECTS
            )
            or (
                node.subject.quantifier in ROLE_NAMES_EVENT_SUBJECT
                and event in ROLE_NAMES_EVENT_SUBJECT[node.subject.quantifier]
            )
        )
    ):
        subject_duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
        if subject_duration is None:
            raise LoweringError(
                f"no sweep ends an event subject's pump at {node.duration.kind}",
                node=node,
            )
        described = _filter_payload(node.subject.filter)
        if object_only_filter(described) is None:
            # The printed noun phrase restates the trigger's own narrowing, so
            # it is carried and re-checked rather than dropped — a word consumed
            # and never read is a word that could be deleted with no change to
            # what the card does.
            raise LoweringError(
                "the event subject's pump carries a restriction the resolution "
                "cannot test", node=node,
            )
        subject_payload: dict[str, object] = {
            "power": power, "toughness": toughness,
            "duration": subject_duration,
        }
        if described:
            subject_payload["filter"] = described
        return (OracleInstruction("pump_event_subject", "", subject_payload),)
    # "**Two target creatures** each get +2/+2 until end of turn." (Symbiosis.)
    # One printed boost over several chosen objects, which is the pump twin of
    # the keyword grant's own several-target branch ("X target creatures gain
    # islandwalk", Part Water) and takes the same route: one description with a
    # count, and a handler that resolves the list.
    #
    # A branch of its own rather than a widening of ``_is_target`` below,
    # because that predicate is what keeps every *other* pump lowering honest —
    # a lowering that admitted several targets and then emitted a one-target
    # instruction would collect the second choice and drop it, which is the
    # ``_names_several_targets`` docstring's Rewind. So the widening is opted
    # into here, by the one lowering whose handler now reads a list.
    #
    # ``_describe_several_targets`` refuses a phrase that prints no "target"
    # (CR 115.10: "up to two creatures" is chosen at resolution, not at
    # announcement), so an untargeted plural still falls through to the class
    # reading below rather than raising a picker in front of it.
    if (
        _names_several_targets(node.subject)
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.targeted
    ):
        several: dict[str, object] = {"power": power, "toughness": toughness}
        several["blocking_only"] = bool(node.subject.filter.blocking)
        _describe_several_targets(several, node.subject)
        duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
        if duration is None:
            raise LoweringError(
                f"no sweep ends a target's pump at {node.duration.kind}", node=node
            )
        if duration != "end_of_turn":
            several["duration"] = duration
        return (
            OracleInstruction("pump_target_creature_until_eot", "", several),
        )
    if _is_target(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        payload: dict[str, object] = {"power": power, "toughness": toughness}
        payload["blocking_only"] = bool(node.subject.filter.blocking)
        _describe_targets(payload, node.subject)
        if node.duration.kind == "while_source_tapped":
            # Its own kind rather than a flag on the until-end-of-turn one:
            # that handler writes a delta the cleanup step subtracts, and this
            # effect must not be written as a delta at all — it is rebuilt from
            # the source's record on every recompute, so it ends the instant
            # the source untaps rather than at the next cleanup.
            return (
                OracleInstruction("pump_target_while_source_tapped", "", payload),
            )
        # Which sweep takes the boost back. Only the durations
        # ``pt.TEMPORARY_PT_CHANNELS`` has a channel for are admitted: every
        # other one used to fall through to the end-of-turn kind with no trace
        # in the payload that a word had been read, so "until end of combat"
        # (Glyph of Destruction) lasted a whole turn and "until your next
        # upkeep" (Gabriel Angelfire) lasted until this one ended.
        duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
        if duration is None:
            raise LoweringError(
                f"no sweep ends a target's pump at {node.duration.kind}", node=node
            )
        if duration != "end_of_turn":
            payload["duration"] = duration
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    # "White creatures get +1/+1", "Attacking creatures get +2/+0 until end of turn"
    #
    # ``each`` beside ``all``: "**Each** creature blocking this creature gets
    # -1/-1 until end of turn" (Knight of Valor) is the same sentence with the
    # same quantifier reading — CR 611.2c fixes the set at resolution either
    # way — and it is the pair every other sweep in this package already
    # accepts (`destruction`, `keywords`, `tapping`, `board`, `counters`, …).
    # Read as `all` alone, the printed word cost the card its support while an
    # identically-meaning sentence one word over compiled.
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in (
        "all", "each"
    ):
        filt = node.subject.filter
        if filt.card_types != ("creature",):
            raise LoweringError("global buff on a non-creature scope", node=node)
        # "Choose a creature type. All creatures **of that type** get -1/-1
        # until end of turn." (Outbreak.) "That type" is the word the sentence
        # in front of this one recorded (CR 608.2d), taken off the filter and
        # carried as the scratchpad slot the handler resolves — the
        # ``subtype_filter_from`` key Extinction's sweep already reads. Only
        # with that step in this same effect: with no producer the words name
        # nothing, and an unresolved "that type" read as no narrowing is a
        # sweep over every creature on the battlefield.
        bound_type: dict[str, object] = {}
        if filt.of_bound_type:
            from ...oracle_types import CHOSEN_CREATURE_TYPE_THIS_WAY

            if CHOSEN_CREATURE_TYPE_THIS_WAY not in produced:
                raise LoweringError(
                    "'of that type' names a creature type no step of this "
                    "effect chose", node=node,
                )
            filt = dataclasses.replace(filt, of_bound_type=False)
            bound_type["subtype_filter_from"] = CHOSEN_CREATURE_TYPE_THIS_WAY
        leftover = _restrictions_beyond(
            filt,
            frozenset({
                "card_types", "colors", "excluded_colors", "controller",
                "attacking", "blocking", "other_than_source", "subtypes",
                "excluded_types",
                # "all attacking creatures **with flanking**" (Telim'Tor),
                # "Creatures **with flying** get +1/+0" (Aether Storm's
                # neighbours). A layer-6 question (CR 613.1f), so a creature
                # *granted* the word is in the set and a printed one that lost
                # it is not -- which is exactly why it cannot be answered off
                # the printed keyword list and has to reach the handler as
                # payload.
                "with_keywords",
                # "Each creature **without flanking** …" (Knight of Valor). The
                # negative twin of the key above and the same layer-6 question
                # (CR 613.1f) read the other way: a creature *granted* the word
                # is out of the set and one that lost it is in, so it cannot be
                # answered off the printed keyword list either.
                "without_keywords",
                # "…**blocking this creature**" (Knight of Valor). A relation to
                # the ability's own source rather than a characteristic, which
                # is why it reaches the handler as payload and is tested through
                # ``subject_matches`` with the source in hand — the same key
                # ``tap_creatures_blocking_target``'s sibling above already
                # reads, here on a sweep instead of a target.
                "blocking_source",
            }),
        )
        if leftover:
            raise LoweringError(
                "the global buff cannot narrow by: " + ", ".join(leftover), node=node
            )
        payload = {"power": power, "toughness": toughness}
        # "…**for each attacking creature other than Márton Stromgald**". The
        # printed P/T sizes one repetition and the count multiplies it, exactly
        # as it does on the two source-shaped branches above — the same
        # `times_x` amount and the same shared count spec, so one printed clause
        # means one number wherever it is printed. The whole set is fixed at
        # resolution (CR 611.2c), which is what makes a one-shot buff the right
        # handler for it.
        if node.per_each is not None:
            payload["power"] = _per_each_amount(node.power, node.power_negative, node)
            payload["toughness"] = _per_each_amount(
                node.toughness, node.toughness_negative, node
            )
            payload["x_from_count"] = count_spec(
                node.per_each, node, offset=_per_each_offset(node)
            )
        if filt.colors:
            payload["color"] = filt.colors[0]
        # "**Nonwhite** creatures get -1/-1 until end of turn." (Holy Light.)
        # The negative twin of the colour above, and it must be carried rather
        # than dropped for the reason every refusal in this file names: an
        # ignored exclusion is a strictly wider sweep than the card prints, and
        # here it is the sweep that debuffs the caster's own white team. A
        # colourless creature is nonwhite (CR 105.2c), which falls out of
        # testing membership rather than absence.
        if filt.excluded_colors:
            payload["exclude_colors"] = list(filt.excluded_colors)

        # "Other **Orc** creatures get +1/+1 until end of turn." (Orc General.)
        # The subtype is payload, tested through ``has_type`` like every other
        # type question in this handler, so a card naming another tribe needs
        # nothing here. It is a list because the noun phrase already reads a
        # union ("Djinn or Efreet"), and the alternatives are OR'd exactly as
        # the permanent matcher OR's them.
        if filt.subtypes:
            payload["subtypes"] = list(filt.subtypes)
        # "…all attacking creatures **with flanking** get +1/+1 until end of
        # turn." (Telim'Tor.) Carried rather than dropped for this file's
        # standing reason: an ignored narrowing is a strictly wider sweep than
        # the card prints -- here Telim'Tor pumping the defending player's
        # blockers is not on the table, but it would pump every attacker in a
        # multiplayer combat. The word is validated against
        # ``IMPLEMENTED_KEYWORDS`` because a word no behaviour is registered
        # under makes ``_has_keyword`` answer no for everything, which turns
        # the buff into a no-op the card reports as supported.
        if filt.with_keywords:
            # Imported at module scope beside ``untestable_filter_keys``. It
            # used to be a function-level import here, which made the name
            # *local to this whole function* — so the same validation added
            # for the negative form below raised UnboundLocalError on every
            # card that narrows by a keyword it does not also print positively.
            unknown = unimplemented_filter_keywords(
                {"with_keywords": list(filt.with_keywords)}
            )
            if unknown:
                raise LoweringError(
                    "the global buff cannot test the keyword(s): "
                    + ", ".join(sorted(unknown)),
                    node=node,
                )
            payload["with_keywords"] = list(filt.with_keywords)
        # "**Nonartifact** creatures get -1/-1 until end of turn." (Stench of
        # Decay.) The type twin of ``exclude_colors`` above, and it is the same
        # argument for carrying it: the noun phrase already read the exclusion,
        # and dropping it here is a strictly wider sweep than the card prints —
        # here one that also shrinks the caster's own artifact creatures.
        # Tested through ``has_type`` rather than the printed type line, so a
        # creature *animated* into an artifact escapes and one that stopped
        # being one is caught (CR 613 layer 4).
        if filt.excluded_types:
            payload["exclude_types"] = list(filt.excluded_types)
        payload["all"] = filt.controller != "you"
        # "**Other** creatures you control get +1/+0" (Bolt Hound). Dropped, the
        # Hound buffed itself as well: a strictly better card than the one
        # printed. Emitted only when set, so every payload written before this
        # key existed is byte-identical.
        if filt.other_than_source:
            payload["exclude_self"] = True
        # "Creatures your opponents control get -2/-2 until end of turn"
        # (Massacre Wurm's entry). `all` cannot say this: it means "every
        # player's", which would debuff the caster's own board too. Emitted
        # only when the scope is opponents, so every payload written before
        # this key existed is byte-identical.
        if filt.controller == "opponent":
            payload["opponents_only"] = True
        if filt.attacking:
            payload["attacking_only"] = True
        if filt.blocking:
            payload["blocking_only"] = True
        # Everything above names one payload key per printed narrowing, which is
        # what keeps every payload this branch has ever written byte-identical.
        # A narrowing with no key of its own rides the *description* instead and
        # the handler tests it with ``subject_matches`` — the pattern
        # ``_team_removal_payload`` one family over already uses, and emitted
        # only when there is something to carry, so no existing card's program
        # moves.
        described = _filter_payload(filt)
        if set(described) - _GLOBAL_BUFF_PAYLOAD_KEYS:
            if untestable_filter_keys(described):
                raise LoweringError(
                    "the global buff cannot test: "
                    + ", ".join(sorted(untestable_filter_keys(described))),
                    node=node,
                )
            # The same validation the ``with_keywords`` branch above performs,
            # and the **negative** form is the urgent half: ``_has_keyword``
            # answers "no" for a word no behaviour is registered under, so
            # "creatures with shadow" would shrink to nothing (a card doing
            # less than it says) while "creatures **without** shadow" widens to
            # the entire board. A sweep that reaches strictly more permanents
            # than the card prints is the one thing this package must never
            # emit, so it refuses the line instead.
            unknown = unimplemented_filter_keywords(described)
            if unknown:
                raise LoweringError(
                    "the global buff cannot test the keyword(s): "
                    + ", ".join(sorted(unknown)),
                    node=node,
                )
            payload["filter"] = described
        if bound_type:
            if node.duration.kind == "while_source_tapped":
                # A recompute rebuilt from the source's record has no
                # resolution scratchpad to read the chosen word back out of.
                raise LoweringError(
                    "a continuous buff cannot read a word this resolution chose",
                    node=node,
                )
            payload.update(bound_type)
        if node.duration.kind == "while_source_tapped":
            # "All creatures get +2/+2 **for as long as this artifact remains
            # tapped**." (Thran Weaponry.) The global twin of
            # `pump_target_while_source_tapped` above, and its own kind for that
            # branch's reason exactly: `buff_creatures_global` walks the board
            # once and stamps a temporary delta a sweep subtracts, and this
            # effect must not be a delta at all — it is rebuilt from the
            # source's record on every recompute, so it ends the instant the
            # source untaps and *survives* every cleanup until it does.
            #
            # Both halves were wrong before this kind existed, and in opposite
            # directions: the duration was dropped, so the payload defaulted to
            # end-of-turn. The buff outlived the artifact untapping, and died at
            # the cleanup step of a card whose *other* printed line — "You may
            # choose not to untap this artifact during your untap step" — exists
            # so that it does not.
            return (
                OracleInstruction(
                    "buff_creatures_global_while_source_tapped", "", payload
                ),
            )
        return (OracleInstruction("buff_creatures_global", "", payload),)

    raise LoweringError("unsupported pump subject", node=node)


def _lower_double_power(node: ast.DoublePower) -> tuple[OracleInstruction, ...]:
    """"Double the power of target creature until end of turn." (Unleash Fury.)

    The duration is required, and required to be this one: a *permanent*
    doubling is a continuous effect the layer system would have to own, and
    reading it as an until-end-of-turn boost would give the card back at
    cleanup something it never said it would.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless power doubling is a continuous effect, which needs "
            "the CR 613 layers engine",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError("power doubling on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    payload: dict[str, object] = {}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("double_target_power_until_eot", "", payload),)


def _lower_switch_pt(node: ast.SwitchPT) -> tuple[OracleInstruction, ...]:
    """``Switch target creature's power and toughness until end of turn.``
    (Transmutation.)

    The duration is required and required to be this one for the reason the
    power doubling's is: the 7d flag is swept by the cleanup step
    (``_EOT_METADATA_KEYS``), so a durationless switch would silently end with
    the turn anyway — a card printed without the clause needs the layer system
    to hold the effect, not this instruction.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless power/toughness switch is a continuous effect, "
            "which needs the CR 613 layers engine",
            node=node,
        )
    payload: dict[str, object] = {}
    if _is_source(node.subject):
        return (OracleInstruction("switch_self_pt_until_eot", "", payload),)
    if not _is_target(node.subject):
        raise LoweringError(
            "no handler switches the power and toughness of this subject", node=node
        )
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("switch_target_pt_until_eot", "", payload),)




def _lower_change_text(node: ast.ChangeText) -> tuple[OracleInstruction, ...]:
    """``Change the text of target spell or permanent …`` (CR 612).

    For the Lace cycle's own wording no ``targets`` description is emitted: the
    vocabulary has no way to say "a spell on the stack *or* a permanent", so
    describing it at all would drop one of the two zones from the picker, and
    ``engine/legality.py`` keeps answering ``spell_or_permanent``.

    A **narrowed** subject is the opposite case. "Change the text of target
    white enchantment you control that doesn't have cumulative upkeep"
    (Balduvian Shaman) names a set of permanents and nothing on the stack, so
    the description is what carries the printed restriction to the picker and
    to the resolution check. Left off, the ability would have read as the Lace
    cycle's and been aimable at any permanent on the board — a restriction the
    card prints and nothing enforces.

    The **duration** is on the payload only when the card prints one. Every
    reader before Whim of Volrath treats a recorded text change as permanent,
    so an absent key is the reading those three cards already have, byte for
    byte. Any duration but "until end of turn" refuses: the cleanup step is what
    ends one (``end_until_eot_text_changes``), so a record stamped with a
    duration nothing sweeps would be an effect printed to end and lasting the
    rest of the game — the widening direction.
    """
    if not _is_target(node.subject):
        raise LoweringError("a text change has to name what it changes", node=node)
    payload: dict[str, object] = {"mode": node.mode}
    if node.duration.kind is not None:
        if node.duration.kind not in ("until_end_of_turn", "this_turn"):
            raise LoweringError(
                "no sweep ends a text change with this duration", node=node
            )
        payload["duration"] = "until_end_of_turn"
    assert isinstance(node.subject, ast.TargetSpec)
    if _filter_payload(node.subject.filter):
        _describe_targets(payload, node.subject)
    return (OracleInstruction("mark_text_modified", "", payload),)
