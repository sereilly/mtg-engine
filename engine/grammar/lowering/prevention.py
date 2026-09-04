"""Lowering the CR 615 prevention shields.

Split out of ``damage`` the round Feint's two-source shield pushed that module
past the thousand-line guard. A family rather than an arbitrary cut, and the
parse side's own reasoning is what says so: ``effects/damage.py`` keeps
prevention because the two halves *parse* the same recipient and duration
vocabulary. Lowering shares none of that — a damage lowering asks which handler
deals how much to whom, a prevention lowering asks which shield records what
and for how long — and this module reads not one helper from the one it left.

The same shape ``zones``, ``library`` and ``mana`` have on this side: a lowering
half that outgrew its parse half. If ``effects/damage.py`` ever splits, reuse
this name so the mirror re-forms instead of forking.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import object_only_filter
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ._events import _RECORDED_PERMANENTS
from ._common import (
    _REST_OF_COMBAT,
    _REST_OF_TURN,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    _is_enchanted,
    _is_source,
    _is_you,
)


def _lower_prevent_half(node: ast.PreventDamage) -> tuple[OracleInstruction, ...]:
    """"The next time a source of your choice would deal damage to you this
    turn, prevent half that damage, rounded down." (Dark Sphere.)

    Its own instruction rather than a flag on the whole-instance shield, for the
    reason the two Circle shapes are two: what the shield absorbs is the axis
    the handler differs on, and a "half" flag ignored by a handler written for
    the whole instance would prevent twice what the card prints.

    Everything the sentence fixes is checked, because each part is a way this
    could mean something larger: the shield protects its controller (a shield on
    a chosen target is a different card), it records no colour or type (a
    narrowed shield is strictly smaller), and the halved quantity is the event
    itself rather than any counted amount.
    """
    assert isinstance(node.amount, ast.Half)
    if not isinstance(node.amount.of, ast.ThatMuch) or node.amount.of.source is not None:
        raise LoweringError("only 'half that damage' is halved by a shield", node=node)
    if not _is_you(node.to):
        raise LoweringError("a halving shield only protects its controller", node=node)
    if node.from_filter is None or node.from_filter != ast.ObjectFilter():
        raise LoweringError("no halving shield narrows which source it answers", node=node)
    if node.combat_only or node.dealt_by is not None or node.dealt_by_others:
        raise LoweringError("no halving shield is scoped to a named source", node=node)
    return (
        OracleInstruction(
            "grant_half_prevention_shield", "", {"half": node.amount.rounding}
        ),
    )


def _alternate_amount(node: ast.PreventDamage) -> dict | None:
    """The second size Elvish Healer's rider gives its shield, or None.

    ``{"filter": …, "amount": N}`` — the printed noun phrase the recipient is
    tested against and how much the shield holds when it answers. Both halves
    or neither: a filter with no amount is a sentence that prevents nothing and
    an amount with no filter is one that always applies, and either alone would
    be a shield of the wrong size rather than a refusal.

    The filter is held to what ``subject_matches`` can test, like every other
    printed noun phrase that reaches a handler: a narrowing the matcher would
    drop is a shield that takes the *larger* size for every recipient.
    """
    if node.alternate_amount is None and node.alternate_subject is None:
        return None
    if node.alternate_amount is None or node.alternate_subject is None:
        raise LoweringError(
            "a second shield size needs both the condition and the amount",
            node=node,
        )
    larger = _amount_payload(node.alternate_amount)
    if not isinstance(larger, int) or larger <= 0:
        raise LoweringError("a second shield size is a printed number", node=node)
    described = _filter_payload(node.alternate_subject)
    if not described or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the shield cannot test the noun phrase that sizes it", node=node
        )
    return {"filter": described, "amount": larger}


def _lower_prevent_damage(
    node: ast.PreventDamage, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Prevent the next N damage …" and the Circle-of-Protection shield.

    One handler, `grant_prevention_shield`, with the recipient encoded as two
    booleans it reads. They are not interchangeable: `to_self` shields the
    ability's controller, `to_source` the permanent the ability is on, and
    neither shields a chosen target — so the recipient decides the payload
    rather than being dropped.
    """
    recipient = node.to
    # A printed "by X **and** Y" reaches exactly one branch below. Refused here
    # for everything else rather than in each of them, because the failure this
    # guards is a *silent* one: every branch written before the conjunction
    # existed reads `dealt_by` alone, so a shield printed over two sources would
    # arm over the first and report the card supported.
    if node.dealt_by_others and not isinstance(node.amount, ast.AllOf):
        raise LoweringError(
            "no counted shield covers more than one source", node=node
        )
    # "…**If it's a green creature, prevent the next 2 damage instead.**"
    # (Elvish Healer.) Refused for every shape but the counted shield below,
    # and refused here rather than in each branch, because the failure it
    # guards is the silent one: every branch was written before the rider
    # existed and reads none of it, so a Circle or a blanket printed with a
    # second size would arm at the smaller one and report the card supported.
    alternate = _alternate_amount(node)
    if alternate is not None and (
        not isinstance(node.amount, ast.Fixed)
        or node.combat_only
        or node.from_filter is not None
        or node.dealt_by is not None
    ):
        raise LoweringError(
            "only a counted shield takes a second size", node=node
        )
    # CR 615.5's additional effect ("…**You gain life equal to the damage
    # prevented this way.**"). Exactly one shape below reads it — the
    # unnarrowed chosen-source shield — and it is refused here for every other,
    # rather than in each of them, because every branch was written before the
    # rider existed and reads none of it: a Circle or a blanket printed with one
    # would arm without it and report the card supported. The dropped-rider
    # class, in the direction that quietly does less than the card says.
    if node.to_others and (
        node.from_filter != ast.ObjectFilter()
        or not isinstance(node.amount, ast.Fixed)
        or node.combat_only
        or node.dealt_by is not None
        or not _is_you(node.to)
    ):
        # "…to **you and/or creatures you control**" reaches exactly one shield
        # below. Refused here rather than in each branch for the reason the
        # rider is: every other branch was written before a shield covered more
        # than one recipient, so one printed over a Circle or a blanket would
        # arm on the player alone and report the card supported.
        raise LoweringError(
            "only the unnarrowed chosen-source shield covers more than one "
            "recipient",
            node=node,
        )
    if node.prevented_rider is not None and (
        node.from_filter != ast.ObjectFilter()
        or not isinstance(node.amount, ast.Fixed)
        or node.combat_only
        or node.dealt_by is not None
    ):
        raise LoweringError(
            "only the unnarrowed chosen-source shield carries an effect after "
            "the prevention",
            node=node,
        )
    # "…prevent **half** that damage, rounded down." (Dark Sphere.) Read before
    # the source-scoped branch below, which counts a shield in whole instances
    # and would arm one that prevents the lot.
    if isinstance(node.amount, ast.Half):
        return _lower_prevent_half(node)
    if isinstance(node.amount, ast.AllOf):
        return _lower_prevent_all(node, produced)
    if node.combat_only:
        # Only the blanket form above has a combat-scoped handler.
        # `grant_prevention_shield` counts damage of any kind, so lowering a
        # "prevent the next N combat damage" onto it would also eat N damage
        # from a burn spell.
        raise LoweringError("no counted shield is scoped to combat damage", node=node)
    if node.from_filter is not None:
        # Colour-scoped whole-instance shield. The handler keys on the colour;
        # a shield against an uncoloured "source of your choice" (Reverse
        # Damage) is a different handler entirely, so refuse rather than emit a
        # colourless Circle of Protection.
        colours = node.from_filter.colors
        card_types = node.from_filter.card_types
        if node.from_filter.is_source:
            # "The next time **this creature** would deal damage to you this
            # turn, prevent that damage." (Mercenaries.) The source is the
            # permanent the ability is on, so nothing is chosen and nothing is
            # rechecked as a property — which is why it is a payload flag on the
            # whole-instance shield rather than a Circle keyed on "creature".
            # Read **before** the axis check below, which would see the printed
            # noun as a card type and arm a shield against every creature on the
            # board.
            return _lower_named_source_shield(node)
        # "…a source of your choice…", with no property recorded at all
        # (Pentagram of the Ages). CR 615.8's plain sentence, and the one every
        # other branch here is a narrowing of — the pool printed the colour, the
        # card type, the fraction and the life-gain rider before it printed the
        # rule, so the unnarrowed form arrived last and refused as "no handler".
        # Read before the axis check below, which reads an empty filter as *no*
        # axis rather than as the whole class of sources.
        if node.from_filter == ast.ObjectFilter():
            if not _is_you(recipient):
                raise LoweringError(
                    "a chosen-source shield only protects its controller", node=node
                )
            if not isinstance(node.amount, ast.Fixed) or node.amount.value != 1:
                # "Prevent the next N damage … from a source of your choice" is
                # a point pool, not a whole instance; this handler spends the
                # shield on the event whatever its size, so a counted amount
                # would prevent more than the card prints.
                raise LoweringError(
                    "an unnarrowed chosen-source shield prevents the whole "
                    "instance, not a counted amount",
                    node=node,
                )
            # CR 615.5's additional effect. Its own instruction per rider
            # rather than a payload flag, because ``Shield.kind`` names the
            # *interceptor* that consumes the shield — and what happens after
            # the absorption is what that interceptor does. Reverse Damage
            # reached `grant_reverse_damage_shield` through a name-keyed hook
            # until this round; the same instruction is what the production
            # emits, so the card's compiled program is unchanged and only the
            # hook is gone.
            if node.to_others:
                return _lower_team_shield(node)
            rider_kinds = {
                "gain_life": "grant_reverse_damage_shield",
                "exile_from_library": "grant_exile_prevention_shield",
            }
            if node.prevented_rider is not None:
                if node.prevented_rider.source_colors:
                    # A conditional rider on a shield that covers one recipient
                    # is a card nobody has printed; the two unconditional ones
                    # have interceptors that pay unconditionally, and one handed
                    # a condition would ignore it.
                    raise LoweringError(
                        "only the team shield's rider is conditional", node=node
                    )
                return (
                    OracleInstruction(
                        rider_kinds[node.prevented_rider.effect], "", {}
                    ),
                )
            return (OracleInstruction("grant_whole_prevention_shield", "", {}),)
        # "…a source of your choice **of the chosen color**" (Prismatic
        # Circle). The colour axis with the value deferred: what the shield
        # records is not in the sentence, it is what the permanent chose as it
        # entered (CR 614.1c), so the handler reads it off the source at
        # resolution and arms nothing when nothing was recorded — the reading
        # ``prevention._resolved_chosen_color`` already takes for the static
        # half of the same phrase.
        #
        # Read before the axis check below, which sees neither a colour nor a
        # card type and would call this shield unnarrowed.
        if node.from_filter.chosen_color:
            if _restrictions_beyond(
                node.from_filter, frozenset({"chosen_color"})
            ):
                raise LoweringError(
                    "a chosen-colour shield records no second property",
                    node=node,
                )
            if not _is_you(recipient):
                raise LoweringError(
                    "colour-scoped shields only protect their controller",
                    node=node,
                )
            return (
                OracleInstruction(
                    "grant_prevention_shield", "",
                    {
                        "amount": 1,
                        "protection_kind": "color",
                        "prevention_color_chosen": True,
                    },
                ),
            )
        # Exactly one *axis* — a shield records one property and CR 615.9
        # rechecks that property — but the colour axis may name several values
        # ("a black **or red** source of your choice", Greater Realm of
        # Preservation), which is one shield a source of either colour spends.
        if len(card_types) > 1 or bool(colours) == bool(card_types):
            raise LoweringError("no handler for this source-scoped shield", node=node)
        if not _is_you(recipient):
            raise LoweringError("colour-scoped shields only protect their controller", node=node)
        if card_types:
            # Circle of Protection: Artifacts. Same instruction, same handler,
            # same band — the shield records a card type where the colour
            # Circles record a colour, and CR 615.9 rechecks whichever one it
            # holds.
            return (
                OracleInstruction(
                    "grant_prevention_shield", "",
                    {
                        "amount": 1,
                        "protection_kind": "source_type",
                        "prevention_source_type": card_types[0],
                    },
                ),
            )
        payload: dict[str, object] = {"amount": 1, "protection_kind": "color"}
        if len(colours) == 1:
            payload["prevention_color"] = colours[0]
        else:
            # Its own key rather than a list under the singular name, for the
            # reason ``ObjectFilter``'s ``any_colors`` is its own key: three
            # readers already take ``prevention_color`` to be one colour
            # symbol, and a second type under one name is how two readers come
            # to disagree.
            payload["prevention_colors"] = list(colours)
        return (OracleInstruction("grant_prevention_shield", "", payload),)

    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount),
        "to_self": bool(_is_you(recipient)),
        "to_source": bool(_is_source(recipient)),
    }
    if alternate is not None:
        payload["amount_if"] = alternate
    # "…dealt to **enchanted creature** this turn." (Fylgja.) A fourth
    # recipient, in the same shape as the three booleans above rather than as a
    # kind of its own, because CR 615.1's shield goes around one object either
    # way and only the lookup differs: `to_source` is the permanent the ability
    # is on, this is the permanent that one is attached to.
    #
    # An Aura's *static* grants are derived by engine/auras.py; this is an
    # activated ability the Aura prints, so it resolves here like any other and
    # the host is found from the source at resolution.
    if _is_enchanted(recipient):
        leftover = _restrictions_beyond(
            recipient.filter, frozenset({"card_types", "is_enchanted"})
        )
        if leftover:
            raise LoweringError(
                "a shield on the enchanted permanent cannot narrow by: "
                + ", ".join(leftover),
                node=node,
            )
        payload["to_attached"] = True
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    if payload["to_self"] or payload["to_source"]:
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    # A chosen recipient. The handler's last branch calls
    # `apply_prevention_shield(game, target, target_permanent_index, …)`, which
    # shields the chosen *permanent* when one was picked and the chosen
    # *player* when none was — so "to target player" and "to target creature"
    # are the same instruction, and both are honoured. A quantifier other than
    # "target"/"any target" is not: nothing enumerates a shield per member of a
    # set.
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind not in ("target_player", "target_opponent"):
            raise LoweringError("no handler for this prevention recipient", node=node)
        _describe_targets(payload, recipient)
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    if not isinstance(recipient, ast.TargetSpec) or recipient.quantifier not in ("target", "any_target"):
        raise LoweringError("no handler for this prevention recipient", node=node)
    _describe_targets(payload, recipient)
    return (OracleInstruction("grant_prevention_shield", "", payload),)


def _lower_team_shield(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """Shadowbane: "The next time a source of your choice would deal damage to
    **you and/or creatures you control** this turn, prevent that damage. If
    damage from a black source is prevented this way, you gain that much life."

    CR 615.8's whole-instance shield over a player *and* a printed set of
    permanents. Its own instruction rather than a flag on the single-recipient
    one, because ``Shield.kind`` names the interceptor that consumes the shield
    and this one is found by a different route: a phrase has no object to hang a
    record on, so it lives on the seat and is matched against each damaged
    permanent (``prevention._class_shields``).

    Every part of the sentence is checked, because each is a way it could mean
    more:

    * exactly one further recipient, and it must be a described set rather than
      a chosen one — nothing enumerates a shield per member of a target list.
    * the phrase must be one ``subject_matches`` can test in full. A narrowing
      the matcher drops is a shield covering strictly more permanents than the
      card names.
    * the rider, if printed, must be one the interceptor performs. Its condition
      is a property of the *source*, so it rides beside the shield's own rather
      than inside it: this card prevents every colour's damage and pays for one.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    if len(node.to_others) != 1:
        raise LoweringError(
            "no shield covers a player and more than one printed set", node=node
        )
    also = node.to_others[0]
    if (
        not isinstance(also, ast.TargetSpec)
        or also.quantifier not in ("all", "each")
        or also.targeted
    ):
        raise LoweringError(
            "the second recipient of a team shield is a described set, not a "
            "chosen one",
            node=node,
        )
    described = _filter_payload(also.filter)
    if not described or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the team shield cannot test the noun phrase it also covers",
            node=node,
        )
    payload: dict[str, object] = {"recipients": described}
    rider = node.prevented_rider
    if rider is not None:
        if rider.effect != "gain_life":
            raise LoweringError(
                "the team shield's interceptor gains life and nothing else",
                node=node,
            )
        payload["rider_colors"] = list(rider.source_colors)
    return (OracleInstruction("grant_team_prevention_shield", "", payload),)


def _lower_named_source_shield(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """Mercenaries: "{3}: The next time this creature would deal damage to you
    this turn, prevent that damage."

    ``grant_whole_prevention_shield`` with one payload key rather than a kind of
    its own: CR 615.8's whole-instance shield is what it arms either way, and
    the only difference is where the source comes from — a chosen object for
    Pentagram of the Ages, and the ability's own permanent here.

    "You" is the **activator**, not the permanent's controller, and on this card
    that is the whole point: the ability is printed beside "Any player may
    activate this ability", so the seat that pays is the seat that is shielded
    (CR 109.5). The handler arms on ``context.caster``, which is that seat.

    Four refusals, each a way the sentence could otherwise mean more:

    * the recipient must be the ability's controller. There is no handler that
      arms this shield on a chosen object, and a shield armed on the wrong
      recipient absorbs damage the card never covered.
    * exactly one instance. "Prevent the next N damage … " from a named source
      is a point pool, and this handler spends the shield on the event whatever
      its size.
    * the source must carry no narrowing beyond naming itself. A restated
      adjective has nothing left to narrow and would be dropped.
    * the duration must be this turn, because that is what the sweep gives it.
    """
    if not _is_you(node.to):
        raise LoweringError(
            "a named-source shield only protects the seat that activated it",
            node=node,
        )
    if not isinstance(node.amount, ast.Fixed) or node.amount.value != 1:
        raise LoweringError(
            "a named-source shield prevents the whole instance, not a counted "
            "amount",
            node=node,
        )
    if _restrictions_beyond(
        node.from_filter, frozenset({"card_types", "is_source"})
    ):
        raise LoweringError(
            "the ability's own source carries no narrowing the shield could "
            "honour",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the named-source shield lasts exactly this turn", node=node
        )
    if node.combat_only or node.dealt_by is not None or node.dealt_by_others:
        raise LoweringError(
            "no named-source shield is scoped to combat or to a second source",
            node=node,
        )
    return (
        OracleInstruction("grant_whole_prevention_shield", "", {"from_source": True}),
    )


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
    described = _filter_payload(spec.filter)
    if not described or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the source-class shield cannot test this noun phrase", node=node
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
        if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("target", "that"):
            raise LoweringError(
                "no handler prevents the damage of an untargeted source", node=node
            )
        payload: dict[str, object] = {"combat_only": bool(node.combat_only)}
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
        elif _restrictions_beyond(spec.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the shield could honour",
                node=node,
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


# ---------------------------------------------------------------------------
# The lock (CR 615.1 / CR 614.9's negative)
# ---------------------------------------------------------------------------
#
# "…can't be prevented or dealt instead to another permanent or player" is not
# a damage clause at all: it is a sentence about the two registries that modify
# one, and it lowers to a mark the shields and the redirects both read. It came
# here rather than staying in ``damage`` the round that module went back over
# the thousand-line guard, along the line this module was already cut on — a
# damage lowering asks which handler deals how much to whom, and this one asks
# what may modify that. Whether a redirect is the other half of what it locks is
# a fact about the *handler*; the sentence is one clause with one instruction,
# so splitting it across two families would give it two homes and no owner.

def _lower_damage_cant_be_prevented(
    node: ast.DamageCantBePreventedOrRedirected,
) -> tuple[OracleInstruction, ...]:
    """"Damage that would be dealt to that creature this turn can't be
    prevented or dealt instead to another permanent or player." (Whippoorwill.)

    Two refusals, each a way the sentence could otherwise reach further than it
    says:

    * the subject must be the object the sentence in front of it chose. A
      described set would be a lock over permanents nobody picked, and the
      handler has only the ability's own target to mark.
    * the duration must be this turn, because that is what the sweep gives it.
      A lock nothing ends is a creature no shield may ever protect.
    """
    subject = node.subject
    if (
        not isinstance(subject, ast.TargetSpec)
        or subject.quantifier not in ("that", "it")
        or _restrictions_beyond(subject.filter, frozenset({"card_types"}))
    ):
        raise LoweringError(
            "the damage lock is armed on the creature the previous sentence "
            "chose",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("the damage lock lasts exactly this turn", node=node)
    return (OracleInstruction("lock_damage_to_target", "", {}),)


def _lower_damage_becomes_counter_removal(
    node: "ast.DamageBecomesCounterRemoval",
) -> tuple[OracleInstruction, ...]:
    """"For each 1 damage that would be dealt to you until your next upkeep,
    you remove an echo counter from this enchantment instead." (Soul Echo.)

    Two refusals, and each is a way the sentence could otherwise cover more
    than it says.

    The player is the ability's **controller**. CR 109.5 makes "you" the
    ability's controller wherever it is printed, and this sentence is offered
    to an *opponent* — so reading the seat off the offer would arm the
    replacement over the wrong player's life total, which is the whole card
    inverted.

    The duration is required and is "until your next upkeep" alone. It is what
    the sweep at the top of the upkeep step keys on; a replacement armed with
    no duration is one nothing ever takes away, and the card would replace
    every point of damage its controller was ever dealt.
    """
    if node.recipient.kind != "you":
        raise LoweringError(
            "the counter-removal replacement covers the ability's controller",
            node=node,
        )
    if node.duration.kind != "until_your_next_upkeep":
        raise LoweringError(
            "a counter-removal replacement lasts until your next upkeep",
            node=node,
        )
    return (
        OracleInstruction(
            "arm_damage_to_counter_removal", "", {"counter": node.counter},
        ),
    )
