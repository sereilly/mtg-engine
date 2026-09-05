"""The **blanket** shields (CR 615): "Prevent all damage that would be dealt…".

Split off ``lowering/prevention.py`` at Visions' first wave, the round Remedy's
divided pool and Honorable Passage's reflecting rider took that module past the
thousand-line guard. The line is one ``engine/prevention.py`` already draws in
its order bands, and draws for a reason that decides behaviour: a blanket has
**no charges**, so applying it costs its recipient nothing and it runs before
every consumable shield — where a pool (CR 615.7) is spent by points and a
CR 615.8 shield by instances, and spending one on damage a blanket was going to
stop anyway is the outcome CR 616.1e's default must not pick. Two different
things, ordered apart in the registry, and now lowered apart.

A floor rather than a family, for ``_bound_returns``' reason exactly:
``prevention`` reads it — ``_lower_prevent_damage`` dispatches here the moment
the printed quantity is ``ast.AllOf`` — and it reads nothing back. The
``prevent all damage that would be dealt … by <noun phrase>`` shield came with
it because it is a blanket too (Al-abara's Carpet: no charges, one recorded
property, rechecked at damage time), and it is reached only from inside the
blanket lowering.

Nothing here is a redirect: a blanket removes the damage, and the CR 614
replacements that leave it happening are ``lowering/redirection.py`` one module
over, whose parse half is now ``effects/redirection.py``.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_COMBAT,
    _REST_OF_TURN,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_you,
    _restrictions_beyond,
    testable_filter_payload,
)
from ._events import _RECORDED_PERMANENTS


def _lower_prevent_from_subject(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """"Prevent all damage that would be dealt to you this turn by <noun
    phrase>." (Al-abara's Carpet.)

    Four refusals, each a way this sentence could otherwise mean more than it
    says:

    * the recipient must be **you**. The shield hangs off the ability's
      controller; a shield printed for one creature or for a chosen player
      would be armed on the wrong object.
    * the source must be a *described class*, not a chosen target. A quantifier
      that picks one object is the marker ``prevent_damage_by_target_until_eot``
      leaves, and re-matching a phrase against every source is a different
      shield.
    * every key of the phrase must be one ``subject_matches`` can test. A
      narrowing the matcher cannot answer would be dropped when the damage is
      dealt, which is a shield strictly wider than the card prints.
    * the duration must be this turn, because that is what the sweep gives it.
    """
    if not _is_you(node.to):
        raise LoweringError(
            "the source-class shield is armed on its controller, not on a "
            "chosen recipient",
            node=node,
        )
    spec = node.dealt_by
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.targeted
        or spec.quantifier not in ("all", "each")
    ):
        raise LoweringError(
            "the source-class shield describes its sources rather than choosing "
            "one",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the source-class shield lasts exactly this turn", node=node
        )
    described = testable_filter_payload(
        spec.filter,
        refusal="the source-class shield cannot test this noun phrase",
        node=node,
    )
    return (
        OracleInstruction(
            "grant_source_class_prevention_shield", "", {"filter": described}
        ),
    )


def _lower_prevent_all(
    node: ast.PreventDamage, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Prevent all combat damage that would be dealt this turn." (Fog.)

    ``prevent_all_combat_damage`` sets one turn-wide flag
    (``game.combat_damage_prevented_until_eot``) that
    ``prevention._prevent_all_combat_damage`` reads on every damage event whose
    ``combat`` flag is set. That is the entirety of its contract, and it takes
    an empty payload — so every narrowing the sentence could carry is something
    the handler would ignore, and each one is checked here instead of dropped:

    * not combat-scoped — the flag only sees combat damage, so lowering
      "prevent all damage that would be dealt this turn" onto it would leave
      every burn spell going through while the card reported as supported;
    * a recipient — the flag is global, so a shield written for one creature or
      one player would silently protect the whole table (Desert Nomads);
    * a source filter — same reason, in the other direction;
    * a duration other than this turn — the flag is cleared in the cleanup step,
      so it *is* "this turn" and nothing else.
    """
    if node.from_targeting_source:
        # Silhouette. The shield hangs on the object the spell's first sentence
        # chose, so the recipient must be that bound reference and nothing else:
        # a shield armed on "you" or on a second target would be a different
        # card, and the handler has only the spell's own target to arm on.
        if (
            not isinstance(node.to, ast.TargetSpec)
            or node.to.quantifier != "that"
            or node.dealt_by is not None
            or node.combat_only
        ):
            raise LoweringError(
                "the targeting shield is armed on the object the spell chose",
                node=node,
            )
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "the targeting shield lasts exactly this turn", node=node
            )
        return (
            OracleInstruction(
                "prevent_damage_from_targeting_sources_until_eot", "", {}
            ),
        )
    if node.dealt_by is not None and not node.to_and_by:
        # "…dealt **by** target creature this turn" (Horn of Deafening, Lady
        # Evangela, Kry Shield). A shield on the damage's *source*, which is why
        # it is a different instruction from every branch below: those protect a
        # recipient, and a creature whose damage is prevented is still perfectly
        # able to be dealt damage itself.
        #
        # Read **before** the combat-only gate below, not after: this branch is
        # the one shield whose width is payload, so "prevent all damage that
        # would be dealt this turn by target creature you control" is the same
        # instruction with the flag off rather than a refusal.
        if node.to is not None:
            # "…dealt **to you** this turn **by attacking creatures without
            # flying**" (Al-abara's Carpet). Both ends named, which is a
            # narrower shield than either half — one on the protected player
            # that answers only to sources the printed noun phrase describes.
            return _lower_prevent_from_subject(node)
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "the directional combat shield lasts exactly this turn", node=node
            )
        spec = node.dealt_by
        source_scoped = (
            isinstance(spec, ast.TargetSpec)
            and spec.quantifier == "this"
            and _is_source(spec)
        )
        if not isinstance(spec, ast.TargetSpec) or (
            not source_scoped and spec.quantifier not in ("target", "that")
        ):
            raise LoweringError(
                "no handler prevents the damage of an untargeted source", node=node
            )
        payload: dict[str, object] = {"combat_only": bool(node.combat_only)}
        if source_scoped:
            # "…prevent all combat damage that would be dealt by **this
            # creature** this turn." (Mtenda Lion, under its own attack
            # trigger.) The ability's own source, named by the clause rather
            # than chosen — so it is a payload key and not a fall-through.
            #
            # The fall-through is what makes it one: the handler resolves a
            # *bound* permanent with every battlefield as its fallback, so an
            # ability that chose nothing would shield whichever creature the
            # scan happened to reach first. That is the same silent
            # mis-aiming ``deal_damage``'s "recipient: source" branch is
            # written for, one family over.
            payload["on_source"] = True
        # "…by that creature **and each creature blocking it**." (Feint.) The
        # second conjunct is a set named by a combat relation to the first, so
        # it carries no description of its own and rides as a flag: the handler
        # already has the chosen creature and asks the combat maps from there.
        #
        # Exactly this shape, and nothing wider. Any other conjunct list is a
        # shield over sources this handler would never arm on, and admitting one
        # would prevent the damage of the first source alone while the card read
        # as supported.
        if node.dealt_by_others:
            if len(node.dealt_by_others) != 1:
                raise LoweringError(
                    "no shield covers more than two sources", node=node
                )
            other = node.dealt_by_others[0]
            if (
                not isinstance(other, ast.TargetSpec)
                or other.targeted
                or other.quantifier not in ("all", "each")
                or not other.filter.blocking_bound_target
                or _restrictions_beyond(
                    other.filter, frozenset({"card_types", "blocking_bound_target"})
                )
            ):
                raise LoweringError(
                    "the only second source a shield reads is the creatures "
                    "blocking the first",
                    node=node,
                )
            payload["also_blocking_target"] = True
        if spec.quantifier == "target":
            _describe_targets(payload, spec)
        # "…dealt by **that creature** this turn" (Telekinesis): the object the
        # sentence in front of it already targeted, not a second choice — so no
        # ``targets`` description is emitted and the handler shields the
        # ability's one target. A bound object carries no narrowing to honour,
        # which is why a restated adjective refuses rather than being dropped.
        elif not source_scoped and _restrictions_beyond(
            spec.filter, frozenset({"card_types"})
        ):
            raise LoweringError(
                "a bound object carries no narrowing the shield could honour",
                node=node,
            )
        elif source_scoped and _restrictions_beyond(
            spec.filter, frozenset({"card_types", "is_source"})
        ):
            # The source is named, not described: "this creature" carries the
            # noun and nothing else. A restated adjective would be a narrowing
            # of a set with one member in it, which is a sentence no card
            # prints — so it refuses rather than being dropped, the same rule
            # the bound-object arm above follows.
            raise LoweringError(
                "the source shield reads no narrowing beyond the noun", node=node
            )
        return (
            OracleInstruction("prevent_damage_by_target_until_eot", "", payload),
        )
    # "Prevent all damage that would be dealt to **it** this turn." (Glyph of
    # Destruction.) The mirror of the directional shield above with the other
    # end named: a shield on the *recipient*, which is why it is a second
    # instruction rather than a flag on that one — folding the two together
    # would make every creature either card touches both unkillable and
    # harmless, and the comment on that handler says so.
    #
    # "It" is the object the sentence in front of it named. The parser reads the
    # pronoun as the source, because that is what it means on a permanent's own
    # line; which of the two it is here depends on whether the spell chose a
    # target, and only the resolution knows — so the instruction names neither
    # and the handler asks. The printed "combat" still rides as payload: with it
    # this is Fog for one creature, without it a shield against burn as well.
    #
    # "Target creature" (Indestructible Aura, Awe Strike) is the *same* shield
    # with the referent printed instead of pronounced: the handler already
    # resolves a chosen target first and falls back to the source, so the only
    # difference is whether the instruction carries a target description for the
    # picker. A second kind for the spelled-out noun would be one dispatch
    # branch per pronoun.
    if (
        node.to is not None
        and isinstance(node.to, ast.TargetSpec)
        # "…dealt to **that creature** this turn" (Ebony Horse, Maze of Ith).
        # The bound quantifier reads exactly as Telekinesis' does on the other
        # end of the event: the object the sentence in front of it targeted, so
        # no ``targets`` description is emitted and the handler shields the
        # ability's one target.
        # "…dealt to and dealt by **those creatures** this turn." (Energy
        # Arc.) The plural of the bound reading beside it: the objects an
        # earlier step of this same effect recorded, not a second choice. The
        # branch below reads the record the untap wrote and arms one shield per
        # permanent — the *same* shield, several times, which is what makes it
        # this instruction with a payload key rather than a second kind.
        and node.to.quantifier in ("it", "target", "that", "those")
        and (node.dealt_by is None or node.to_and_by)
    ):
        if node.duration.kind not in _REST_OF_TURN + _REST_OF_COMBAT:
            raise LoweringError(
                "the directional shield lasts this turn or this combat",
                node=node,
            )
        payload: dict[str, object] = {"combat_only": bool(node.combat_only)}
        if node.duration.kind in _REST_OF_COMBAT:
            # "…**this combat**" (Winter's Chill). The narrower window, carried
            # so the end-of-combat sweep can end it: read and dropped, the
            # shield would go on preventing through a second combat phase the
            # card never mentions. The word is the whole difference between
            # this and Maze of Ith's turn-long shield.
            payload["duration"] = "end_of_combat"
        if node.to_and_by:
            # "Prevent all combat damage that would be dealt **to and dealt
            # by** that creature this turn." Both ends of the event, which is
            # one shield rather than two: the flag rides the payload and the
            # handler records the two-way direction the shield reader already
            # answers for. Refused without the printed "combat", because
            # nothing in the pool prints the unscoped two-way form and a shield
            # this wide would also silence the creature's ping abilities.
            if not node.combat_only:
                raise LoweringError(
                    "the two-way shield covers combat damage only", node=node
                )
            payload["to_and_by"] = True
        if node.to.quantifier == "those":
            if _restrictions_beyond(node.to.filter, frozenset({"card_types"})):
                # A bound plural was chosen by the sentence in front of this
                # one, so a restated adjective has nothing left to narrow — and
                # would be dropped rather than honoured. The singular arm below
                # refuses for the same reason.
                raise LoweringError(
                    "a bound plural carries no narrowing the shield could "
                    "honour", node=node,
                )
            recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
            if not recorded:
                raise LoweringError(
                    "\"those creatures\" names objects nothing in this effect "
                    "recorded", node=node,
                )
            if len(recorded) != 1:
                raise LoweringError(
                    "\"those creatures\" is ambiguous: several earlier steps "
                    "recorded objects", node=node,
                )
            payload["permanents_from"] = recorded[0]
            return (
                OracleInstruction(
                    "prevent_damage_to_target_until_eot", "", payload,
                ),
            )
        if node.to.quantifier == "that" and _restrictions_beyond(
            node.to.filter, frozenset({"card_types"})
        ):
            # A bound object was chosen by the sentence in front of this one, so
            # a restated adjective has nothing left to narrow — and would be
            # dropped rather than honoured.
            raise LoweringError(
                "a bound object carries no narrowing the shield could honour",
                node=node,
            )
        if node.to.quantifier == "target":
            # The handler's predicate is `is_creature` and nothing else, so a
            # shield printed over a player or over a narrowed noun phrase would
            # arm on the wrong object — or on none — while the card reported as
            # supported. Both are refused rather than dropped.
            if node.to.filter.card_types != ("creature",) or _restrictions_beyond(
                node.to.filter, frozenset({"card_types"})
            ):
                raise LoweringError(
                    "the directional shield is armed on one unnarrowed target "
                    "creature",
                    node=node,
                )
            _describe_targets(payload, node.to)
        return (
            OracleInstruction(
                "prevent_damage_to_target_until_eot", "", payload,
            ),
        )
    if not node.combat_only:
        raise LoweringError("no handler prevents all damage of every kind", node=node)
    if node.to is not None:
        # "…to Dogs you control" (Pack Leader). A *set* named by a printed noun
        # phrase, which the scoped record can carry and re-match when damage
        # would be dealt; anything else — one player, one creature, a chosen
        # target — is a shield on one recipient and stays refused, because the
        # record covers whoever matches rather than whoever was there.
        if (
            isinstance(node.to, ast.TargetSpec)
            and not node.to.targeted
            and node.to.quantifier in ("all", "each")
            and node.to.filter.controller == "you"
        ):
            if node.duration.kind not in _REST_OF_TURN:
                raise LoweringError(
                    "the scoped combat-damage record lasts exactly this turn",
                    node=node,
                )
            leftover = _restrictions_beyond(
                node.to.filter,
                frozenset({"card_types", "subtypes", "controller", "type_match"}),
            )
            if leftover:
                raise LoweringError(
                    "the scoped prevention cannot narrow by: " + ", ".join(leftover),
                    node=node,
                )
            return (
                OracleInstruction(
                    "prevent_all_combat_damage_to_matching", "",
                    {"filter": _filter_payload(node.to.filter)},
                ),
            )
        raise LoweringError(
            "prevent_all_combat_damage is turn-wide; no handler scopes a blanket "
            "prevention to one recipient",
            node=node,
        )
    if node.from_filter is not None:
        raise LoweringError(
            "no handler scopes a blanket prevention to a source", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the combat-damage flag lasts exactly this turn", node=node
        )
    blanket = OracleInstruction("prevent_all_combat_damage", "", {})
    if node.unaffected_if_cost_paid is None:
        return (blanket,)
    # "…**If this spell's additional cost was paid, this effect doesn't affect
    # combat damage that would be dealt by red creatures.**" (Undergrowth.) One
    # printed prevention with two widths, decided by whether CR 601.2b's
    # optional additional cost was taken — so it lowers to the choice between
    # them rather than to two effects, which would both apply.
    #
    # The narrowing is a *source* description, which is the one thing the
    # blanket flag cannot carry (it is a bool), so the narrow arm gets its own
    # record and its own interceptor. Held to a filter the matcher can actually
    # test: a narrowing nothing tests would be silently dropped, and dropping
    # this one lets the damage the card lets through be prevented after all.
    excluded = node.unaffected_if_cost_paid
    if not isinstance(excluded, ast.ObjectFilter):
        raise LoweringError(
            "the exempted sources are a printed description, not a choice",
            node=node,
        )
    described = object_only_filter(_filter_payload(excluded))
    if described is None:
        raise LoweringError(
            "the exempted sources name a narrowing nothing can test", node=node
        )
    return (
        OracleInstruction(
            "if_then", "",
            {
                "condition": {"kind": "additional_cost_paid"},
                "then": (
                    OracleInstruction(
                        "prevent_all_combat_damage_except_from", "",
                        {"filter": described},
                    ),
                ),
                "else": (blanket,),
            },
        ),
    )
