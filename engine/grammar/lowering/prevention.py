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
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ._common import (
    _REST_OF_TURN,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    _is_source,
    _is_you,
)


def _lower_prevent_damage(node: ast.PreventDamage) -> tuple[OracleInstruction, ...]:
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
    if isinstance(node.amount, ast.AllOf):
        return _lower_prevent_all(node)
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


def _lower_prevent_all(node: ast.PreventDamage) -> tuple[OracleInstruction, ...]:
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
    if node.dealt_by is not None:
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
        and node.to.quantifier in ("it", "target")
        and node.dealt_by is None
    ):
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "the directional shield lasts exactly this turn", node=node
            )
        payload: dict[str, object] = {"combat_only": bool(node.combat_only)}
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
    return (OracleInstruction("prevent_all_combat_damage", "", {}),)
