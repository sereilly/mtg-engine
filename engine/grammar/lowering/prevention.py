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
from ..phrases import is_pt_counter
from ..vocabulary import IMPLEMENTED_KEYWORDS
from ._blankets import _lower_prevent_all
from ._events import CHOSEN_DAMAGE_SOURCE
from ._common import (
    _REST_OF_TURN,
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
    testable_filter_payload,
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
    described = testable_filter_payload(
        node.alternate_subject,
        refusal="the shield cannot test the noun phrase that sizes it",
        node=node,
    )
    return {"filter": described, "amount": larger}


def _counted_pool_counter_rider(node: ast.PreventDamage) -> str | None:
    """The counter Temper's CR 615.5 rider places, or None for every other card.

    "Prevent the next X damage that would be dealt to target creature this turn.
    **For each 1 damage prevented this way, put a +1/+1 counter on that
    creature.**"

    The pool's rider rather than the chosen-source shield's, which is the only
    other shape in this file that carries one — so it is read here, in front of
    the refusal every other branch shares, rather than inside the pool's own
    payload: those branches were written before any rider existed and read none
    of it, and one printed on a Circle or a blanket would arm without it and
    report the card supported.

    Every refusal is a way the sentence could otherwise mean more than it says:

    * the shield must be the plain counted pool. A half, a blanket, a
      colour-scoped Circle, a division and a second size all reach a different
      interceptor, and none of them places a counter — the rider would be
      dropped.
    * the counter must be a CR 122.1a power/toughness kind, because that is
      what the interceptor places (``Game.place_pt_counters``). An invented
      counter (CR 122.1's open half) has no reader behind this rider and would
      be a card reporting supported while placing nothing.
    * the rider carries no condition. "If damage from a black source is
      prevented this way" is a property of the source that the interceptor
      would ignore, which is a card paying for damage it never said it would.
    * the shield must go around a **chosen creature**. "That creature" is the
      one the sentence in front named, so a pool armed on a player, on the
      ability's own source or on the permanent it enchants leaves the pronoun
      pointing at nobody — and a counter placed on a player is not a counter
      this engine has.
    """
    rider = node.prevented_rider
    if rider is None or rider.effect != "put_counter":
        return None
    if (
        node.from_filter is not None
        or node.dealt_by is not None
        or node.dealt_by_others
        or node.combat_only
        or node.division is not None
        or node.to_others
        or node.alternate_amount is not None
        or node.alternate_subject is not None
        or rider.source_colors
        or isinstance(node.amount, (ast.AllOf, ast.Half))
    ):
        raise LoweringError(
            "only the plain counted pool places counters for what it prevented",
            node=node,
        )
    if not is_pt_counter(rider.counter):
        raise LoweringError(
            f"nothing places a {rider.counter} counter for damage prevented "
            "this way",
            node=node,
        )
    if (
        not isinstance(node.to, ast.TargetSpec)
        or node.to.quantifier not in ("target", "any_target")
        or "creature" not in node.to.filter.card_types
    ):
        raise LoweringError(
            "the counters go on the creature the shield was announced on",
            node=node,
        )
    return rider.counter


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
    counter_rider = _counted_pool_counter_rider(node)
    if counter_rider is None and node.prevented_rider is not None and (
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
    # "…to any number of targets, **divided as you choose**." (Remedy.) The
    # division reaches exactly one shield below — the counted pool armed on a
    # chosen recipient — and is refused here for every other shape rather than
    # in each of them, for the reason the rider above it is: every branch was
    # written before a shield could be divided and reads none of it, so a
    # Circle or a blanket printed with a division would arm at the full amount
    # on one recipient and report the card supported.
    if node.division is not None and (
        not isinstance(node.amount, ast.Fixed)
        or node.combat_only
        or node.from_filter is not None
        or node.dealt_by is not None
        or node.to_others
        or node.prevented_rider is not None
        or alternate is not None
    ):
        raise LoweringError(
            "only a plain counted shield divides among its recipients", node=node
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
            # "…would deal damage to **any target** this turn, prevent that
            # damage." (Circle of Despair.) CR 615.1 puts a shield around a
            # player or a permanent, and this is the first printing in the pool
            # that names one the ability chooses rather than its controller. The
            # recipient rides as payload and the *targets* description beside it
            # is what makes the picker ask for it — without that the shield
            # would be armed on whichever object a targetless resolution
            # defaults to.
            #
            # Only "any target", and only on the unnarrowed shield: the rider
            # branches below hand their own kinds a recipient they have no
            # reading for, and a colour- or type-scoped shield protecting
            # somebody else is a card nobody prints.
            if (
                isinstance(recipient, ast.TargetSpec)
                and recipient.quantifier == "any_target"
                and not node.to_others
                and isinstance(node.amount, ast.Fixed)
                and node.amount.value == 1
            ):
                payload_for_target: dict[str, object] = {
                    "recipient": "target",
                    "targets": {"quantifier": "any_target", "kind": "any"},
                }
                rider = node.prevented_rider
                if rider is None:
                    return (
                        OracleInstruction(
                            "grant_whole_prevention_shield", "",
                            payload_for_target,
                        ),
                    )
                # "…**If damage from a red source is prevented this way, ~
                # deals that much damage to the source's controller.**"
                # (Honorable Passage.) The one CR 615.5 rider printed on an
                # any-target shield — its own kind rather than a flag, for the
                # reason ``Shield.kind`` exists: it names the interceptor, and
                # what the interceptor does after absorbing is the whole
                # difference between this card and Pentagram of the Ages.
                #
                # The other two riders are refused here rather than mapped:
                # both gain their *controller* something, and this shield can
                # be armed on an opponent's creature, so borrowing either
                # would pay the wrong seat.
                if rider.effect != "damage_source_controller":
                    raise LoweringError(
                        "only the reflecting rider is printed on an "
                        "any-target shield",
                        node=node,
                    )
                payload_for_target["rider_colors"] = list(rider.source_colors)
                return (
                    OracleInstruction(
                        "grant_reflecting_prevention_shield", "",
                        payload_for_target,
                    ),
                )
            # "Sacrifice this Aura: The next time a source of your choice would
            # deal damage to **enchanted creature** this turn, prevent that
            # damage." (Kithkin Armor.) CR 615.1's shield goes around a player
            # *or* a permanent, and the counted pool one function down has read
            # this very recipient since Fylgja — the whole-instance shield had
            # simply never been printed with it, so "a chosen-source shield only
            # protects its controller" was a fact about the pool written as a
            # rule about the engine.
            #
            # Its recipient rides the same ``recipient`` key Circle of Despair's
            # "any target" does, because it is the same question of the same
            # instruction: *which object does this shield go around*. It is
            # deliberately not the counted shield's ``to_attached`` boolean —
            # that kind carries three booleans because it grew one recipient at
            # a time, and a fourth spelling of one key on a second kind is how
            # the two come to disagree.
            #
            # Read **before** the "you" check below rather than as a branch
            # inside it: the sentence names no controller at all, so the check
            # it would otherwise fail is asking the wrong question.
            if _is_enchanted(recipient):
                leftover = _restrictions_beyond(
                    recipient.filter, frozenset({"card_types", "is_enchanted"})
                )
                if leftover:
                    # ``attached_host`` answers *which* permanent, never which
                    # kind of one, so a narrowing past the enchant relation
                    # would be dropped and the shield armed on a host the phrase
                    # excludes. The same refusal the counted shield makes of the
                    # same phrase, in the same words.
                    raise LoweringError(
                        "a shield on the enchanted permanent cannot narrow by: "
                        + ", ".join(leftover),
                        node=node,
                    )
                if node.to_others or node.prevented_rider is not None:
                    # Both riders in the pool gain their *controller* something,
                    # and this shield hangs on a permanent that may be an
                    # opponent's by the time it is spent — borrowing either
                    # would pay the wrong seat, which is the any-target branch's
                    # reason one screen up.
                    raise LoweringError(
                        "no shield on the enchanted permanent carries an "
                        "effect after the prevention",
                        node=node,
                    )
                if not isinstance(node.amount, ast.Fixed) or node.amount.value != 1:
                    raise LoweringError(
                        "an unnarrowed chosen-source shield prevents the whole "
                        "instance, not a counted amount",
                        node=node,
                    )
                return (
                    OracleInstruction(
                        "grant_whole_prevention_shield", "",
                        {"recipient": "attached"},
                    ),
                )
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
                if node.prevented_rider.effect not in rider_kinds:
                    # "…~ deals that much damage to the source's controller"
                    # printed on a shield its caster hangs on *themselves*.
                    # No card prints it, and the reflecting interceptor is
                    # armed by the any-target branch above; refusing names the
                    # gap rather than raising a KeyError two lines down.
                    raise LoweringError(
                        "no shield on its own controller carries this rider",
                        node=node,
                    )
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
        # "The next time a black or red source of your choice would deal damage
        # this turn, prevent that damage." (Penance.) CR 615.8's shield printed
        # with **no recipient**: it is keyed on the source alone and stops that
        # source's next damage to whoever it was headed for. Its own scope key
        # rather than a third value of ``to_self``, because the two are
        # different questions — one names a seat, this names *nobody*, and a
        # reader that had learned only "you or not you" would take the absence
        # for the opponent.
        #
        # Only the colour axis, deliberately. A card type or a keyword shield
        # with no recipient is a printing that does not exist, and admitting one
        # would arm a table-wide shield off a sentence nobody has written.
        any_recipient = recipient is None
        if any_recipient and not colours:
            raise LoweringError(
                "a shield with no recipient records a colour", node=node
            )
        if not any_recipient and not _is_you(recipient):
            raise LoweringError("colour-scoped shields only protect their controller", node=node)
        if card_types and node.from_filter.with_keywords:
            # Circle of Protection: Shadow — "The next time **a creature of
            # your choice with shadow** would deal damage to you this turn,
            # prevent that damage."
            #
            # A *third* narrowing axis beside the colour and the card type, and
            # the reason it is not simply a second key on the branch below:
            # ``prevention_source_type`` is compared with ``source_has_type``,
            # which cannot answer a keyword, so a shield carrying both would
            # have been armed against **every creature source** with the
            # keyword dropped — the dropped-rider class, in the widening
            # direction, on a card whose whole point is the narrowing.
            #
            # The whole noun phrase travels as a ``source_filter`` instead,
            # which ``Shield`` already carries and ``prevention._source_matches``
            # already rechecks (CR 615.9) through ``subject_matches`` — the one
            # answer every reader of a printed noun phrase asks. So a phrase
            # the matcher cannot test refuses here rather than being ignored at
            # damage time.
            described = testable_filter_payload(
                node.from_filter,
                refusal="the shield's source phrase cannot be tested",
                node=node,
            )
            for keyword in node.from_filter.with_keywords:
                if keyword not in IMPLEMENTED_KEYWORDS:
                    # ``subject_matches`` reads a keyword off layer 6, which
                    # answers "no" for every source when nothing implements the
                    # word — so the shield would prevent nothing at all while
                    # the card reported supported. ``with_keywords`` is a
                    # *testable* key, so the check above cannot see this: it
                    # asks whether the matcher can answer the question, not
                    # whether the answer can ever be yes.
                    raise LoweringError(
                        f"the shield cannot test the keyword: {keyword}", node=node
                    )
            return (
                OracleInstruction(
                    "grant_prevention_shield", "",
                    {
                        "amount": 1,
                        "protection_kind": "source_subject",
                        "source_filter": described,
                    },
                ),
            )
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
        if any_recipient:
            payload["prevention_any_recipient"] = True
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
    if counter_rider is not None:
        # CR 615.5's additional effect on the pool: the counters go on as the
        # points are absorbed, not when the spell resolves, so the kind travels
        # with the shield and the interceptor places them. A key on the same
        # instruction rather than a second one, because the two are one effect —
        # `Shield.kind` is what picks the interceptor and this key is what that
        # interceptor is.
        payload["rider_counter"] = counter_rider
    # "…dealt to this creature **by Torrent of Lava** this turn." Whose damage
    # the shield answers to, on the same shield rather than as a kind of its
    # own: CR 615.9 rechecks a *recorded property* against the source when the
    # damage would be dealt, and ``Shield.source_filter`` is already that
    # recheck for every kind — only which property differs, which is payload.
    if node.dealt_by is not None:
        if not isinstance(node.dealt_by, ast.TargetSpec) or node.dealt_by.targeted:
            raise LoweringError(
                "a counted shield's source is described, not chosen", node=node
            )
        payload["source_filter"] = testable_filter_payload(
            node.dealt_by.filter,
            refusal="the shield cannot test the noun phrase naming its source",
            node=node,
        )
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
        if node.division is not None:
            raise LoweringError(
                "a divided shield is split among chosen recipients, not armed "
                "on one named permanent",
                node=node,
            )
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    # "Prevent the next 5 damage that would be dealt this turn to **any number
    # of targets, divided as you choose**." (Remedy.) CR 615.7's point pool
    # split across CR 601.2d's announced targets — the same division a burn
    # spell announces, on the other end of the event, so it travels in the
    # ``targets`` description ``engine/divided_damage.py`` already reads. That
    # module finds the divided step by ``targets["kind"] == "divided"`` and
    # sizes the announcement off ``payload["amount"]``, neither of which is
    # about damage, so the announcement gate, the picker and the AI all cover
    # this card without knowing it exists.
    if node.division is not None:
        if (
            not isinstance(recipient, ast.TargetSpec)
            or recipient.quantifier != "any_number"
        ):
            raise LoweringError(
                "a divided shield is split among any number of chosen "
                "recipients",
                node=node,
            )
        described = testable_filter_payload(
            recipient.filter,
            refusal="a divided shield cannot test the noun phrase it splits "
                    "among",
            node=node,
            require_narrowing=False,
        )
        targets: dict[str, object] = {
            "quantifier": "divided", "kind": "divided",
            "division": node.division,
        }
        if described:
            targets["filter"] = described
        payload["targets"] = targets
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
    described = testable_filter_payload(
        also.filter,
        refusal="the team shield cannot test the noun phrase it also covers",
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


#: Which instruction each printed tail of "the next time <that source> would
#: deal damage this turn, …" becomes (Desperate Gambit). A table rather than a
#: branch, for ``shields.Shield.kind``'s reason: the word the card printed names
#: the *registry* that carries the clause out — CR 614's amount replacement or
#: CR 615's prevention — and a third tail is a row plus the interceptor behind
#: it, refused until both exist.
_NEXT_DAMAGE_INSTRUCTIONS = {
    "double": "double_next_damage_from_chosen_source",
    "prevent": "prevent_next_damage_from_chosen_source",
}


def _lower_choose_damage_source(
    node: ast.ChooseDamageSource,
) -> tuple[OracleInstruction, ...]:
    """"Choose a source you control" (Desperate Gambit) — CR 609.7's source of
    damage, picked as the spell resolves.

    The same ``choose_permanent`` step Enchantment Alteration's host pick and
    Takklemaggot's already use, which is the whole of what this sentence needs:
    a prompt for the effect's controller, a default for a non-interactive seat,
    and the answer written into the resolution scratchpad by ``permanent_id``.
    What differs is only where the answer is sent, and that is payload — see
    ``_records._PRODUCES_FOR_PAYLOAD``, which is what lets the sentences behind
    this one gate on the record actually being written.

    **Permanents only, and that is a real narrowing.** CR 609.7 lets "a source"
    be a spell on the stack too, and the record this arms lives on the chosen
    object's ``metadata`` (``engine/next_damage.py``) — a spell has none of its
    own, only the printed ``CardDefinition`` it shares with every other copy in
    every deck, so a marker written there would double the next damage of three
    other Lightning Bolts. The narrower reading is the one a dropped narrowing
    cannot make wrong.

    The filter is refused if the matcher cannot test it, exactly as every other
    lowering that hands a noun phrase to a choice does: a restriction nothing
    can check is a wider choice than the card prints.
    """
    described = testable_filter_payload(
        node.filter,
        refusal="the source choice cannot test",
        node=node,
        require_narrowing=False,
    )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "filter": described,
                "result_key": CHOSEN_DAMAGE_SOURCE,
                "prompt": "Choose a source you control.",
                "chooser": "you",
            },
        ),
    )


def _lower_chosen_source_next_damage(
    node: ast.ChosenSourceNextDamage, produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"The next time that source would deal damage this turn, it deals double
    that damage instead." / "…, prevent that damage." (Desperate Gambit.)

    Both tails arm a one-shot rider on the source an earlier step of this same
    resolution chose (``engine/next_damage.py``); which registry carries it out
    is the table above.

    **Gated on the choice having a producer**, which is idiom 7 and not a
    formality here: "that source" and "it" name nothing on a board, so without a
    step that recorded one this sentence would compile cleanly and arm a rider on
    nobody — a spell reporting itself resolved and doing nothing, which is the
    failure this grammar refuses loudly.

    The duration must be this turn, because that is exactly what the sweep gives
    it (``mixins/_constants._EOT_METADATA_KEYS``): a rider printed for longer
    would expire early and one printed for less would outlive its sentence.
    """
    kind = _NEXT_DAMAGE_INSTRUCTIONS.get(node.modification)
    if kind is None:  # pragma: no cover - the parser reads only the two tails
        raise LoweringError(
            f"no instruction carries out {node.modification!r}", node=node
        )
    if CHOSEN_DAMAGE_SOURCE not in produced:
        raise LoweringError(
            "nothing in front of this sentence chose the source it names",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a one-shot damage rider lasts exactly this turn", node=node
        )
    return (
        OracleInstruction(kind, "", {"source_from": CHOSEN_DAMAGE_SOURCE}),
    )
