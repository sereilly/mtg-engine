"""Lowering CR 614.9's **counted** redirects: "The next N damage … instead".

Split off ``lowering/redirection.py`` at Nemesis' first wave, when Sivvi's Valor
and Oracle's Attendants took that module past the thousand-line guard. The line
is the one the parse side already draws inside its single production
(``effects/redirection._parse_damage_redirect``): "**Two printed quantities, one
production.** 'All damage …' moves the whole event; '**The next N** damage …'
moves N points and leaves the rest where it was dealt." The quantity rides
``ast.RedirectDamage.amount``, and ``_lower_redirect_damage`` dispatches here the
moment it is not None — read ahead of every branch there, because each of those
was written when there was no number to read and would move a Fireball's twelve.

That is the arrangement ``_blankets`` has with ``prevention`` one family over,
on the same axis: ``_lower_prevent_damage`` hands the sentence down the moment
the printed quantity is ``ast.AllOf``. A floor for ``_blankets``' reason exactly
-- ``redirection`` reads it and it reads nothing back -- and the two functions
moved byte-identically, so no compiled program moves.

What is here is CR 615.7's numeric shield read with CR 614.9's verb: the points
behave as a shield's do (each 1 damage spends 1), but they are **moved** rather
than removed, so the damage is still dealt in full by the same source and only
its recipient changes for the part the pool covers.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (_REST_OF_TURN, _amount_payload, _describe_targets,
                      _filter_payload, _is_source, _names_several_targets)


def _lower_next_damage_redirect(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """"The next N damage that would be dealt to target <noun> this turn is
    dealt to this creature instead." (Daughter of Autumn; Hazduhr the Abbot
    prints ``X`` for N and puts the duration on the other side of the
    recipient, which the one production reads either way.)

    CR 615.7's numeric shield with CR 614.9's verb. The points behave exactly as
    a shield's do — each 1 damage spends 1, and what is left of a larger event
    lands normally — but they are **moved** rather than removed, so the damage
    is still dealt in full by the same source and only its recipient changes for
    the part the pool covers. That difference is why this is a record in
    ``engine/damage_redirects.py`` rather than a ``Shield``: lifelink
    (CR 120.3f), "whenever ~ deals damage" and the dealt-damage ledger all see
    the moved points.

    Every refusal below is a way the sentence could otherwise mean more than it
    says:

    * the protected recipient must be one **chosen** object. The record hangs
      off the recipient it watches, and a class or a bare "you" is a different
      record with a different home (``_lower_optional_class_redirect``).
    * the class must be one ``subject_matches`` can test, because the target is
      re-checked at resolution (CR 608.2b) and a narrowing the matcher would
      drop is a redirect covering strictly more creatures than the card prints.
    * the damage must move onto the permanent whose ability this is. Nothing
      here resolves another taker, and a record pointing nowhere is a redirect
      that silently does nothing at all (CR 614.9).
    * the duration must be this turn, because that is what the sweeps give it;
      and a chosen source, a "next time" bound, an opponent's pick and a combat
      scope all have readings on the blanket redirects above and none here.
    """
    if (
        node.dealt_by is not None
        or node.from_chosen_source
        or node.one_shot
        or node.chooser is not None
        or node.combat_only
        or node.optional
    ):
        raise LoweringError(
            "a counted redirect names no source, no bound, no other chooser "
            "and no combat scope",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if not _is_source(node.new_recipient) and not _is_source(node.to):
        # "The next X damage that would be dealt to **target creature,
        # planeswalker, or player** this turn is dealt to **another target
        # creature, planeswalker, or player** instead." (Captain's Maneuver.)
        # Neither end is the source: both are announced. Read ahead of the
        # branch below, which was reached by every sentence whose *taker* was
        # not the source and never asked what its protected end was — so this
        # one lowered as "the next X damage dealt to **this creature**", armed
        # on a spell's absent permanent, with one target of its two.
        return _lower_next_damage_redirect_between_targets(node)
    if not _is_source(node.new_recipient):
        # "{1}{W}: **The next 1 damage that would be dealt to this creature**
        # this turn **is dealt to any target instead**." (Zhalfirin Crusader.)
        # The same sentence with its two ends swapped: the record still hangs
        # off the recipient it watches and still moves N points, but here the
        # watched recipient is the ability's own source and the *taker* is what
        # the ability chose. One production reads both, because from the
        # quantity onwards they are the identical clause — and one
        # ``DamageRedirect`` carries both, because that record has never cared
        # which end of it was named and which was chosen.
        return _lower_next_damage_redirect_from_source(node)
    if _is_source(node.to):
        # Both ends the source. "The next 1 damage that would be dealt to this
        # creature is dealt to this creature instead" moves nothing and is a
        # sentence no card prints; refusing names it rather than arming a
        # record that redirects a permanent to itself.
        raise LoweringError(
            "a counted redirect moves the damage somewhere else", node=node
        )
    spec = node.to
    # "…dealt to **target creature, planeswalker, or player**" (Martyrdom's
    # granted ability) — CR 115.4's union, which the reference reader gives the
    # same quantifier as the modern "any target" spelling. Admitted beside the
    # narrowed object because a redirect record already lives on "a player *or*
    # a permanent" (``engine/damage_redirects``: CR 615.1's sibling wording),
    # so the union costs the handler one branch and the record nothing.
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier not in ("target", "any_target")
        or _names_several_targets(spec)
    ):
        raise LoweringError(
            "no handler arms a counted redirect on this recipient", node=node
        )
    described = _filter_payload(spec.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    payload: dict[str, object] = {"amount": _amount_payload(node.amount)}
    _describe_targets(payload, spec)
    return (
        OracleInstruction("redirect_next_damage_to_source_until_eot", "", payload),
    )


def _lower_next_damage_redirect_between_targets(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """"The next X damage that would be dealt to target creature, planeswalker,
    or player this turn is dealt to another target creature, planeswalker, or
    player instead." (Captain's Maneuver.)

    The point pool of the two lowerings beside this one with **both** ends
    announced: the record hangs off the first target and points at the second,
    and the ability's own source is neither — which is what lets a spell print
    it, a spell having no permanent to be an end.

    Two instances of CR 115.4's union, so either end may be a player's face or
    a permanent on either battlefield. That is a cross-seat list of chosen
    targets, and ``divided_targets`` is the engine's one channel for one
    (``_targets.card_divided_target_description``): the card prints the count,
    two, nothing is divided — every entry carries the whole pool, which is
    :data:`~engine.divided_damage.EACH` — and the order they are announced in
    is the order the sentence names them, the protected end first. The printed
    "another" is that channel's own rule: no entry may repeat (CR 601.2c).

    Refuses what it would otherwise widen: a narrowed end ("target white
    creature" beside "another target …") has a noun this channel's picker
    cannot ask per slot, and a second end not printed as "another" could be the
    first one named twice — a redirect from a creature to itself.
    """
    from ...divided_damage import EACH
    from ._targets import card_divided_target_description

    for end in (node.to, node.new_recipient):
        if not (
            isinstance(end, ast.TargetSpec)
            and end.quantifier == "any_target"
            and end.targeted
            and not _names_several_targets(end)
            and end.filter == ast.ObjectFilter()
        ):
            raise LoweringError(
                "a counted redirect between two announced targets names "
                "\"any target\" at both ends",
                node=node,
            )
    if node.to.distinct_from_prior or not node.new_recipient.distinct_from_prior:
        raise LoweringError(
            "a counted redirect between two announced targets moves the "
            "damage to *another* target",
            node=node,
        )
    return (
        OracleInstruction(
            "redirect_next_damage_between_targets_until_eot", "",
            {
                "amount": _amount_payload(node.amount),
                "targets": card_divided_target_description(
                    division=EACH, count=2,
                    # Which announced target is which end, in the sentence's
                    # own words and its own order — what the handler reads by
                    # position and a picker has to be able to say.
                    roles=(
                        "target the damage would be dealt to",
                        "target the damage is dealt to instead",
                    ),
                ),
            },
        ),
    )


def _lower_next_damage_redirect_from_source(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """"The next 1 damage that would be dealt to **this creature** this turn is
    dealt to **any target** instead." (Zhalfirin Crusader.)

    :func:`_lower_next_damage_redirect` with the two ends of the event
    exchanged: there the ability's source *takes* the damage and a chosen object
    is protected, here the source is protected and a chosen object takes it.

    Its own instruction rather than a flag, because the two halves of the
    payload change meaning: ``targets`` there describes who is *shielded* and
    the record is armed on it, and ``targets`` here describes who is *hit* and
    the record is armed on the source. A handler reading one payload as the
    other would arm a redirect pointing back at the creature it protects, which
    is a card that silently does nothing at all.

    Two spellings of the taker, and the difference is payload rather than a
    kind. "Any target" (CR 115.4) makes it a player as readily as a permanent,
    and ``DamageRedirect`` has carried both since it was written. A **narrowed
    object** target — "…is dealt to target creature you control instead", the
    sentence the five en-Kor creatures share verbatim — names a permanent and
    only a permanent, so the description rides on ``targets`` and the handler
    re-checks it at resolution (CR 608.2b) the way its twin one function up
    already does. Held to what ``subject_matches`` can test for that twin's
    reason: a narrowing the matcher would drop is a redirect that moves the
    damage onto a creature the card never offered.

    **Both printed quantities.** "The next **1 damage**" is a point pool
    (``amount``); "**The next time** damage would be dealt to this creature this
    turn, that damage is dealt to any target instead" (Mirrorwood Treefolk) is
    CR 615.8's one instance however large it is (``uses``). One instruction and
    one record carry both, because ``DamageRedirect`` has always had both
    counters and the two sentences differ in nothing else — so the instance
    form is read here, by the function whose sentence it is, rather than by a
    module of its own. The checks the counted caller made before handing its
    sentence down are made here for the instance form, which arrives straight
    from the dispatcher.
    """
    if node.amount is None:
        if (
            not node.one_shot
            or node.chooser is not None
            or node.combat_only
            or node.optional
        ):
            raise LoweringError(
                "a redirect off the ability's own source moves a point pool or "
                "the next instance, with no other chooser, combat scope or "
                "offer",
                node=node,
            )
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "a recorded redirect lasts exactly this turn", node=node
            )
    spec = node.new_recipient
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier not in ("target", "any_target")
        or _names_several_targets(spec)
    ):
        raise LoweringError(
            "a counted redirect off the source moves the damage onto one "
            "chosen target",
            node=node,
        )
    # Exactly one of the two counters, so Zhalfirin Crusader's and the en-Kor
    # creatures' payloads stay byte-identical.
    payload: dict[str, object] = (
        {"uses": 1} if node.amount is None
        else {"amount": _amount_payload(node.amount)}
    )
    _describe_targets(payload, spec)
    if spec.quantifier == "target":
        untestable = untestable_filter_keys(
            (payload.get("targets") or {}).get("filter") or {}
        )
        if untestable:
            raise LoweringError(
                "a redirect cannot test " + ", ".join(sorted(untestable)),
                node=node,
            )
    return (
        OracleInstruction(
            "redirect_next_damage_from_source_until_eot", "", payload
        ),
    )
