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
    _describe_several_targets,
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

    "Prevent all combat damage that would be dealt **by unblocked creatures**
    this turn." (Snag.) The same shield with no recipient printed at all: it
    stops that damage to whoever it was headed for, which is Penance's
    ``any_recipient`` reach on the same seat-held shield. And the printed
    "combat" rides as ``combat_only`` — it was read by the parse and dropped
    here, which no shipped card printed until Snag.

    Four refusals, each a way this sentence could otherwise mean more than it
    says:

    * the recipient must be **you**, or not printed at all. The shield hangs
      off the ability's controller; a shield printed for one creature or for a
      chosen player would be armed on the wrong object.
    * the source must be a *described class*, not a chosen target. A quantifier
      that picks one object is the marker ``prevent_damage_by_target_until_eot``
      leaves, and re-matching a phrase against every source is a different
      shield.
    * every key of the phrase must be one ``subject_matches`` can test. A
      narrowing the matcher cannot answer would be dropped when the damage is
      dealt, which is a shield strictly wider than the card prints.
    * the duration must be this turn, because that is what the sweep gives it.
    """
    any_recipient = node.to is None
    if not any_recipient and not _is_you(node.to):
        raise LoweringError(
            "the source-class shield is armed on its controller, not on a "
            "chosen recipient",
            node=node,
        )
    if any_recipient and (
        node.from_filter is not None
        or node.to_and_by
        or node.dealt_by_others
        or node.unaffected_if_cost_paid is not None
    ):
        raise LoweringError(
            "the recipient-free source-class shield names one described class "
            "of sources and nothing else",
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
    payload: dict[str, object] = {"filter": described}
    # Both emitted only when printed, so Al-abara's Carpet's and Scarecrow's
    # payloads stay byte-identical.
    if any_recipient:
        payload["any_recipient"] = True
    if node.combat_only:
        payload["combat_only"] = True
    return (
        OracleInstruction("grant_source_class_prevention_shield", "", payload),
    )


def _lower_prevent_all_to_class(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """"Prevent all damage that would be dealt this turn to creatures you
    control." (Sivvi's Ruse.)

    :func:`_lower_prevent_from_subject`'s blanket with the printed noun phrase
    on the other end of the event — it names the permanents protected rather
    than the sources stopped — and the non-combat sibling of Pack Leader's
    scoped record below, which is a turn-wide flag the end-of-combat sweep
    clears and so cannot carry a shield that has to outlive combat.

    Every refusal is a way the sentence could otherwise mean more than it says:

    * a source narrowing, a second recipient or a two-way reading have their
      own shields and none of them is this one; armed here they would be
      dropped and the blanket would stop damage the card lets through.
    * the duration is this turn, because that is what the cleanup sweep gives
      a ``Shield``.
    * the phrase must *describe* something — an empty filter is every
      permanent on the battlefield — and every key of it must be one
      ``subject_matches`` can test, since the shield asks the phrase of each
      damaged permanent when the damage would be dealt (CR 615.1).
    """
    if (
        node.dealt_by is not None
        or node.dealt_by_others
        or node.from_filter is not None
        or node.to_and_by
        or node.unaffected_if_cost_paid is not None
    ):
        raise LoweringError(
            "the recipient-class blanket names no source and no second end",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the recipient-class blanket lasts exactly this turn", node=node
        )
    # ``require_narrowing`` (the default) is the empty-filter refusal: a phrase
    # that narrowed nothing would shield every permanent on the battlefield.
    described = testable_filter_payload(
        node.to.filter,
        refusal="the recipient-class blanket cannot test this noun phrase",
        node=node,
    )
    return (
        OracleInstruction(
            "grant_recipient_class_prevention_shield", "", {"filter": described}
        ),
    )


def _lower_chosen_source_blanket(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """"Prevent all damage that would be dealt to you this turn by a source of
    your choice." (Samite Ministration, Protective Sphere.)

    CR 615.8's chosen-source shield with "the next time" taken off: every
    instance the one chosen source would deal this turn, rather than the first.
    Its own instruction rather than a flag on the one-shot's, for the reason
    ``Shield.kind`` exists — a shield that is never used up is consumed by a
    different interceptor in a different band (it is free, so it runs with the
    blankets), and a "lasts all turn" flag ignored by any of the five one-shot
    handlers would arm a shield that prevents one event of a card that prints
    all of them.

    Every part of the sentence is checked, because each is a way it could mean
    more than it says:

    * the recipient is **you** — the shield hangs off the ability's controller,
      and one printed for a chosen target would be armed on the wrong object —
      **or is not printed at all**: "Prevent all damage a source of your choice
      would deal this turn" (Rith's Charm) names only the source, so it stops
      that source's damage to whoever it was headed for. That is Penance's
      ``any_recipient`` reach on the same seat-held shield, and it is carried
      as that flag rather than as a second kind;
    * no colour or type narrows the choice (``from_filter`` is the empty
      phrase). A narrowed one — "a red source of your choice" — is a property
      the shield would have to recheck and this payload carries none;
    * all damage, not combat damage alone, and for exactly this turn: the
      cleanup sweep is what ends a ``Shield``;
    * the rider, if printed, is the conditional life gain and is spelled for a
      shield that lasts the turn ("whenever … this turn"). The one-shot's "if"
      is refused rather than read as the same thing, so the two spellings
      cannot drift into meaning each other's shield.
    """
    if node.from_filter != ast.ObjectFilter():
        raise LoweringError(
            "the chosen-source blanket names no property of its source",
            node=node,
        )
    any_recipient = node.to is None
    if (not any_recipient and not _is_you(node.to)) or node.to_others:
        raise LoweringError(
            "the chosen-source blanket protects its controller, or names no "
            "recipient at all", node=node
        )
    if (
        node.combat_only
        or node.dealt_by is not None
        or node.dealt_by_others
        or node.to_and_by
        or node.from_targeting_source
        or node.unaffected_if_cost_paid is not None
        or node.division is not None
        or node.alternate_amount is not None
        or node.alternate_subject is not None
    ):
        raise LoweringError(
            "the chosen-source blanket stops all of one source's damage and "
            "narrows no further",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the chosen-source blanket lasts exactly this turn", node=node
        )
    payload: dict[str, object] = {}
    if any_recipient:
        # Emitted only when the sentence prints no recipient, so Samite
        # Ministration's and Protective Sphere's payloads stay byte-identical.
        payload["any_recipient"] = True
        if node.prevented_rider is not None:
            # "…you gain that much life" pays the seat the shield protects,
            # and this one protects nobody in particular. No card prints the
            # pair; refusing names it rather than guessing who is paid.
            raise LoweringError(
                "a recipient-free chosen-source blanket carries no rider",
                node=node,
            )
    if node.source_shares_spent_mana_color:
        # "…that shares a color with the mana spent on this activation cost"
        # (Protective Sphere). The colours are read at resolution from the
        # payment the activation measured (``choices["mana_spent_for_cost"]``),
        # so what rides here is only that the shield must be handed them.
        payload["source_shares_spent_mana_color"] = True
    rider = node.prevented_rider
    if rider is not None:
        if (
            rider.effect != "gain_life"
            or not rider.source_colors
            or not rider.repeating
        ):
            raise LoweringError(
                "the chosen-source blanket's rider is the life gain for a "
                "coloured source, printed 'whenever … this turn'",
                node=node,
            )
        payload["rider_colors"] = list(rider.source_colors)
    return (
        OracleInstruction("grant_chosen_source_blanket_shield", "", payload),
    )


def _lower_prevent_all(
    node: ast.PreventDamage,
    produced: frozenset[str] = frozenset(),
    *,
    event: str | None = None,
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
    if node.from_filter is not None:
        # "…by **a source of your choice**" — CR 609.7a's chosen source behind
        # the blanket. Before every branch below, each of which was written for
        # a described or targeted source and reads no choice.
        return _lower_chosen_source_blanket(node)
    if node.source_shares_spent_mana_color:
        raise LoweringError(
            "only a chosen source is narrowed by the mana spent", node=node
        )
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
        if (
            isinstance(node.dealt_by, ast.TargetSpec)
            and not node.dealt_by.targeted
            and node.dealt_by.quantifier in ("all", "each")
        ):
            # "…dealt **by unblocked creatures** this turn" (Snag). A
            # *described* class with no recipient named — the same shield
            # reaching every recipient, rather than the directional one below,
            # which is armed on one chosen object.
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
        # "…prevent all combat damage that would be dealt by **it** this turn."
        # (Ignoble Soldier, under its own becomes-blocked trigger.) The mirror
        # of the pronoun the recipient branch below already admits, and it is
        # read the same way: the pronoun names whatever the sentence in front of
        # it named — the chosen target if the effect chose one, otherwise the
        # ability's own source — and **only the resolution knows which**.
        #
        # Deliberately not folded into ``source_scoped``: the parser sets
        # ``is_source`` on every bare "it" as its default reading (a bare "it"
        # on the *recipient* end carries it too), so the flag is not a claim
        # about this sentence and treating it as one would silence the ability's
        # own permanent on a spell that targeted something else.
        bound_pronoun = (
            isinstance(spec, ast.TargetSpec) and spec.quantifier == "it"
        )
        if not isinstance(spec, ast.TargetSpec) or (
            not source_scoped
            and not bound_pronoun
            and spec.quantifier not in ("target", "that")
        ):
            raise LoweringError(
                "no handler prevents the damage of an untargeted source", node=node
            )
        payload: dict[str, object] = {"combat_only": bool(node.combat_only)}
        if bound_pronoun:
            if _restrictions_beyond(
                spec.filter, frozenset({"card_types", "is_source"})
            ):
                # A pronoun names an object an earlier clause already chose, so
                # a restated adjective has nothing left to narrow — and would be
                # dropped rather than honoured. The bound-object arm below
                # refuses for the same reason. Under a **board-wide** trigger
                # this is also the refusal that catches a rebound pronoun:
                # `grammar/rebinding.py` rewrites "it" into the trigger's own
                # printed subject when that subject is not the source, and a
                # narrowed subject lands here rather than being silently read as
                # one object.
                raise LoweringError(
                    "a bound object carries no narrowing the shield could "
                    "honour", node=node,
                )
            if event is not None and _is_source(spec):
                # "Whenever this creature becomes blocked, prevent all combat
                # damage that would be dealt by **it** this turn." (Ignoble
                # Soldier.) Under a source-scoped trigger the pronoun is the
                # ability's own permanent, and it has to be read *here* rather
                # than left to the resolution: a trigger's stack item carries a
                # bookkeeping target — for `creature_becomes_blocked` that is
                # the **blocker** — so the bound reading below resolves to the
                # creature on the other end of the event and silences it
                # instead. Observed, not assumed: the first run of this card
                # logged "all combat damage Blocker would deal this turn is
                # prevented (Ignoble Soldier)".
                payload["on_source"] = True
                source_scoped = True
            else:
                payload["bound_or_source"] = True
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
        if (
            isinstance(spec, ast.TargetSpec)
            and spec.quantifier == "target"
            and spec.filter.zone == "stack"
        ):
            # "…dealt by **target instant or sorcery spell** this turn."
            # (Hidden Retreat.) The source is a spell, not a permanent, which
            # is why it is a kind of its own and not this payload with a zone
            # on it: a spell is chosen from the stack and is recognised at
            # damage time by the *cast* rather than by the source object — the
            # exact axis ``redirection._lower_spell_damage_redirect`` splits on
            # one family over, and for the same reason (CR 109.5 makes a
            # spell's source its printed card, shared by every copy).
            #
            # Read before the ``targets`` description below, which would put a
            # stack-scoped filter through ``_filter_payload`` and refuse the
            # line at "no handler reads a filter scoped to the stack".
            if not spec.filter.card_types:
                # "target **instant or sorcery** spell". Without a type this
                # reads "target spell", which is a strictly wider card — and
                # the handler tests the chosen spell against this union at
                # resolution (CR 608.2b), so an empty one would admit every
                # spell on the stack.
                raise LoweringError(
                    "this spell shield names no kind of spell", node=node
                )
            if _restrictions_beyond(
                spec.filter, frozenset({"card_types", "zone"})
            ):
                raise LoweringError(
                    "the spell shield narrows its target by type and nothing "
                    "else",
                    node=node,
                )
            if node.combat_only or node.dealt_by_others or payload.get("on_source"):
                raise LoweringError(
                    "a spell's damage is never combat damage and never has a "
                    "second source",
                    node=node,
                )
            return (
                OracleInstruction(
                    "prevent_damage_by_target_spell_until_eot", "",
                    {"card_types": list(spec.filter.card_types)},
                ),
            )
        if spec.quantifier == "target":
            _describe_targets(payload, spec)
        # "…dealt by **that creature** this turn" (Telekinesis): the object the
        # sentence in front of it already targeted, not a second choice — so no
        # ``targets`` description is emitted and the handler shields the
        # ability's one target. A bound object carries no narrowing to honour,
        # which is why a restated adjective refuses rather than being dropped.
        elif not source_scoped and not bound_pronoun and _restrictions_beyond(
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
        # "…to **up to two target creatures**." (Redeem.) A *list* of chosen
        # recipients rather than one, which is the same shield armed several
        # times — so it joins this branch with a several-target description
        # rather than becoming a second kind, exactly as "those creatures"
        # below does for the list an earlier step recorded.
        # "…dealt to and dealt by **this creature** this turn." (Urborg
        # Phantom.) The ability's own source, *named* rather than pronounced —
        # the recipient half of the ``on_source`` reading the directional
        # shield beside this one already takes for Mtenda Lion.
        and node.to.quantifier in (
            "it", "target", "that", "those", "up_to", "this",
        )
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
        if node.to.quantifier == "this":
            # Named, not described and not chosen: "this creature" carries the
            # noun and nothing else, so a restated adjective would be a
            # narrowing of a set with one member in it. And it has to be a
            # payload key rather than the pronoun's fall-through, for the
            # reason the source half states — the handler resolves a *bound*
            # permanent first, and an ability that chose nothing would shield
            # whichever creature that scan reached.
            if not _is_source(node.to) or _restrictions_beyond(
                node.to.filter, frozenset({"card_types", "is_source"})
            ):
                raise LoweringError(
                    "the source shield reads no narrowing beyond the noun",
                    node=node,
                )
            payload["on_source"] = True
            return (
                OracleInstruction(
                    "prevent_damage_to_target_until_eot", "", payload,
                ),
            )
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
        if node.to.quantifier in ("target", "up_to"):
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
            if node.to.quantifier == "up_to":
                # "…to **up to two** target creatures" (Redeem). CR 601.2c's
                # variable target count, and an **opt-in** on this call site:
                # `_describe_several_targets` is what tells the picker to
                # collect a list and the handler to resolve one, and the
                # handler below reads the same description back through
                # `names_a_target_list`. Described with the ordinary reader
                # instead, the picker would offer one creature and the printed
                # "up to two" would be a word nothing carried.
                _describe_several_targets(payload, node.to)
            else:
                _describe_targets(payload, node.to)
        return (
            OracleInstruction(
                "prevent_damage_to_target_until_eot", "", payload,
            ),
        )
    if (
        not node.combat_only
        and isinstance(node.to, ast.TargetSpec)
        and not node.to.targeted
        and node.to.quantifier in ("all", "each")
    ):
        return _lower_prevent_all_to_class(node)
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
