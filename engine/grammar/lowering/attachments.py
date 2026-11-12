"""Lowering for **attaching one permanent to another** (CR 701.3, CR 303.4).

Equip's rewritten ability, Enchantment Alteration's move, and the "<player>
chooses a permanent" pick both of those and Takklemaggot's reattachment share.

Its own family rather than a corner of `board.py`, split off at the
thousand-line guard: an attachment is a *relation between two permanents*, and
every one of these productions is about legality measured across that pair
(CR 303.4j), where the rest of `board.py` lowers effects that act on one
permanent at a time. The two halves shared exactly one name — the scratchpad key
the choice writes — and that already lives in `_events.py`, which is the shape
every other family split on this side has had.

The parse side keeps these in `effects/board.py`: the sentences read like any
other board effect, and `effects/board.py` is nowhere near the cap. The same
asymmetry `zones`, `library` and `prevention` record.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (CHOSEN_THIS_WAY_OBJECTS, PER_OBJECT_SEAT_RECORDS,
                             OracleInstruction)
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_targets, _filter_payload, _is_enchanted,
                      _is_source, _is_target, _restrictions_beyond,
                      describe_independent_target_roles)
from ._amounts import count_spec
from ._events import (CHOSEN_PERMANENT as _ATTACH_HOST_KEY,
                      CHOSEN_PLAYER, EVENT_SUBJECT_PLAYER,
                      _EVENT_SUBJECT_CONTROLLERS, _EVENT_SUBJECT_OBJECTS,
                      _EVENT_SUBJECT_PLAYERS, _RECORDED_PERMANENTS)
from ._piles import one_card_pile_pick
from ._seats import _CHOOSER_SEATS


def _lower_attach_to_recorded(
    node: ast.Attach, produced: frozenset[str]
) -> "tuple[OracleInstruction, ...] | None":
    """The attach whose host an earlier step of this sentence recorded, or None.

    "…**and attach this enchantment to it**." (Necromancy.) The same kind rather
    than a second one, because what the handler does is unchanged — what differs
    is which object it reads, and that is payload: ``host_from`` names the
    scratchpad key, exactly as it does for the chosen-host attach below.

    Two conditions and no guessing. The host must be the bare pronoun — which
    the noun parser reads as the ability's own source, because with nothing
    printed after the word that is the only object a lone sentence could mean —
    carrying no further narrowing this reading would drop; and exactly one
    earlier step must have recorded a permanent, so "it" has one referent rather
    than a pick between two. The same two questions ``_named_counters.py`` asks
    of the identical pronoun for Bogardan Phoenix, and the same answer: a step
    that put a permanent onto the battlefield is what changes what the word
    means.
    """
    host = node.host
    if not isinstance(host, ast.TargetSpec) or host.targeted:
        return None
    if host.quantifier not in ("it", "that"):
        return None
    if _restrictions_beyond(host.filter, frozenset({"card_types", "is_source"})):
        return None
    recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
    if len(recorded) != 1:
        return None
    return (
        OracleInstruction(
            "attach_source_to_target", "", {"host_from": recorded[0]}
        ),
    )


def _lower_attach(
    node: ast.Attach, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Attach this permanent to target creature you control." (CR 702.6a.)

    One handler, ``attach_source_to_target``, and one shape for it: the source
    moves, one chosen permanent receives it. The host filter rides the payload
    exactly as a tap's does — ``type_filter``/``controller`` for the resolution
    to re-check (CR 608.2b), ``targets`` for ``engine/targeting.py`` to build
    the picker from — so CR 702.6c's narrowed equip ("target legendary creature
    you control") costs nothing here. A chosen *subject* ("target Equipment you
    control", Brass Squire) has no handler yet and refuses naming that.

    The host may also be a permanent an **earlier step of this same sentence**
    put onto the battlefield — "Put target creature card from a graveyard onto
    the battlefield under your control **and attach this enchantment to it**"
    (Necromancy). Nothing was chosen: the ability's target is a *card* in a
    graveyard, and the permanent did not exist until that step ran, so the
    record it wrote is the only place the pronoun can be read from. That is why
    this lowering takes ``produced`` at all, and why the branch is gated on one:
    with no such step in front of it, "it" is a back-reference to nothing and
    the line keeps its refusal.
    """
    if (
        isinstance(node.subject, ast.TargetSpec) and _is_target(node.subject)
        and isinstance(node.host, ast.TargetSpec) and _is_target(node.host)
        and node.host.targeted and node.host.quantifier == "target"
    ):
        return _lower_attach_target_to_target(node)
    if isinstance(node.subject, ast.TargetSpec) and _is_target(node.subject):
        return _lower_attach_chosen(node)
    if node.host_it_can_enchant:
        # "…it can enchant" is tested only by the chosen-host pick above,
        # which offers legal hosts and nothing else (CR 303.4j). Anywhere else
        # the words would be read and dropped.
        raise LoweringError(
            "nothing tests that the host is one the attachment can enchant",
            node=node,
        )
    swept = _lower_attach_all_to_source(node)
    if swept is not None:
        return swept
    if not isinstance(node.subject, ast.TargetSpec) or not _is_source(node.subject):
        raise LoweringError(
            "no handler attaches anything but the source itself", node=node
        )
    recorded = _lower_attach_to_recorded(node, produced)
    if recorded is not None:
        return recorded
    if node.chooser is not None:
        return _lower_attach_to_their_choice(node, produced)
    if not isinstance(node.host, ast.TargetSpec) or not _is_target(node.host):
        raise LoweringError("attach needs one chosen permanent to attach to", node=node)
    payload = _filter_payload(node.host.filter)
    _describe_targets(payload, node.host)
    return (OracleInstruction("attach_source_to_target", "", payload),)


def _lower_attach_target_to_target(node: ast.Attach) -> tuple[OracleInstruction, ...]:
    """"Attach **target Equipment** you control **to target creature** you
    control." (Auriok Windwalker.) "Attach target Equipment to target
    creature." (Magnetic Theft.)

    CR 701.3 with *both* ends announced: two targeted phrases of one
    announcement, of two different kinds, so they are described as the
    ordered roles Fumarole's "target creature and target land" already is
    (``describe_independent_target_roles``) — the picker asks for the
    Equipment and then the creature (CR 601.2c), the cast and activation gates
    re-walk the same description, and the handler reads each role back by name
    and re-asks both at resolution (CR 608.2b).

    Every printed narrowing rides its role's filter, so Windwalker's two "you
    control" are enforced and Magnetic Theft, printing neither, may put one
    player's Equipment on another's creature without changing who controls it
    (its 2004-12-01 ruling; CR 301.5d). Whether the Equipment can actually
    equip the creature — CR 301.5c's animated Equipment, protection, Goblin
    Brawler — is not a targeting question: both are legal targets and the
    Equipment simply doesn't move (CR 301.5b, 701.3b), which
    ``equipment.attach_equipment`` answers at resolution.

    Only an Equipment moves this way. An Aura that changed hosts here would
    want CR 303.4j's enchant legality offered by the host's picker, which these
    roles do not carry, so any other moved noun refuses.
    """
    subject, host = node.subject, node.host
    assert isinstance(subject, ast.TargetSpec) and isinstance(host, ast.TargetSpec)
    if node.host_it_can_enchant or node.chooser is not None or node.optional:
        raise LoweringError(
            "an attach between two targets reads no enchant clause, chooser "
            "or decline",
            node=node,
        )
    if tuple(subject.filter.subtypes) != ("equipment",) or subject.filter.card_types:
        raise LoweringError(
            "only a targeted Equipment is moved onto a second target", node=node
        )
    payload: dict[str, object] = {}
    describe_independent_target_roles(payload, (subject, host))
    for role in payload["targets"]["roles"]:
        untestable = untestable_filter_keys(role["filter"])
        if untestable:
            raise LoweringError(
                "the attach cannot test " + ", ".join(sorted(untestable)),
                node=node,
            )
    return (OracleInstruction("attach_target_to_target", "", payload),)


def _lower_attach_all_to_source(
    node: ast.Attach,
) -> "tuple[OracleInstruction, ...] | None":
    """"When this creature enters, **attach all Equipment on the battlefield
    to it**." (Vulshok Battlemaster.) Or None for any other attach.

    The keyword action (CR 701.3) with the two ends the other way round from
    equip: what moves is a *described set* swept off every battlefield, and
    what receives it is the ability's own source. One instruction,
    ``attach_all_to_source``, whose payload is the set's filter — asked of
    each permanent through ``subject_matches``, so every key must be one that
    predicate tests or the line refuses naming it. Each member moves by
    ``equipment.attach_equipment``, which asks its own legality: an Equipment
    that cannot equip the source does not move and is not unattached
    (Battlemaster ruling, 2004-12-01), and nothing changes control (CR
    701.3a; CR 301.5d).
    """
    subject, host = node.subject, node.host
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
    ):
        return None
    if not (isinstance(host, ast.TargetSpec) and _is_source(host) and not host.targeted):
        raise LoweringError(
            "a swept set is attached only to the ability's own source", node=node
        )
    if node.host_it_can_enchant or node.chooser is not None:
        raise LoweringError(
            "the attach-all reads no host legality clause and no chooser",
            node=node,
        )
    filt = subject.filter
    # "…**on the battlefield**": the scope is nobody (CR 403.1), which is what
    # the handler's sweep already is — every battlefield, narrowed by seat only
    # where the phrase prints a controller. The exile sweep's reading, and its
    # one refusal: a printed seat beside it would be two answers.
    if filt.on_the_battlefield:
        if filt.controller is not None:
            raise LoweringError(
                "an attach-all scoped to nobody cannot also name a controller",
                node=node,
            )
        filt = dataclasses.replace(filt, on_the_battlefield=False)
    payload = _filter_payload(filt)
    untestable = untestable_filter_keys(payload)
    if untestable:
        raise LoweringError(
            "the attach-all cannot test " + ", ".join(sorted(untestable)),
            node=node,
        )
    return (OracleInstruction("attach_all_to_source", "", payload),)


def _lower_unattach(node: ast.Unattach) -> tuple[OracleInstruction, ...]:
    """"Unattach all Equipment from target creature." (Disarm; CR 701.3d.)

    One instruction, ``unattach_all_from_target``: the host is the spell's
    target — its filter on the payload for the resolution to re-check and its
    ``targets`` description for the picker, as a tap's is — and the set that
    comes off it rides ``attachments``, asked of each attachment through
    ``subject_matches``. Only Equipment: CR 701.3d defines "unattach" for an
    Equipment, which stays on the battlefield; an Aura that stops being
    attached is a different event (CR 704.5m puts it in a graveyard), so a
    set that is not Equipment refuses.
    """
    subject, host = node.subject, node.host
    if host is None:
        # "When this Aura enters, **unattach enchanted Equipment**." (Carry
        # Away.) The permanent this Aura is attached to, off whatever it in
        # turn is attached to (CR 701.3d) — an Equipment, for the reason
        # above, and named by the attachment alone: no narrowing beyond the
        # noun is read.
        if not (
            _is_enchanted(subject)
            and not _restrictions_beyond(subject.filter, frozenset({"is_enchanted"}))
        ):
            raise LoweringError(
                "an unattach with no host printed names the enchanted Equipment",
                node=node,
            )
        return (OracleInstruction("unattach_attached_permanent", "", {}),)
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
    ):
        raise LoweringError("only a described set of Equipment is unattached", node=node)
    if "equipment" not in subject.filter.subtypes:
        raise LoweringError(
            "CR 701.3d unattaches Equipment; nothing else stays on the battlefield "
            "unattached",
            node=node,
        )
    if not (isinstance(host, ast.TargetSpec) and _is_target(host)):
        raise LoweringError(
            "the unattach needs one chosen permanent to unattach from", node=node
        )
    attachments = _filter_payload(subject.filter)
    untestable = untestable_filter_keys(attachments)
    if untestable:
        raise LoweringError(
            "the unattach cannot test " + ", ".join(sorted(untestable)), node=node
        )
    payload = _filter_payload(host.filter)
    _describe_targets(payload, host)
    payload["attachments"] = attachments
    return (OracleInstruction("unattach_all_from_target", "", payload),)


def _lower_attach_to_their_choice(
    node: ast.Attach, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"That player attaches this Aura to a land of their choice." (Steam
    Vines.) "That land's controller may attach this Aura to a land of their
    choice." (Kudzu.)

    Two steps, for ``_lower_attach_chosen``'s reason exactly: the host is
    picked as the ability resolves — nothing was targeted (CR 115.10), which
    is why Steam Vines' ruling says moving it "does not target the land" and
    Kudzu's says it may land on one that can't be targeted — so it is the
    ``choose_permanent`` every other resolution-time pick is, and the attach
    behind it reads the answer by the key named here. Kudzu was one name-keyed
    line and a prompt of its own for want of exactly this composition.

    **Whose land is not narrowed.** "A land of their choice" is any land the
    Aura could enchant, whoever controls it (Kudzu, 2004-10-04: "You can move
    it to any other player's land") — the card's whole menace. The only test
    is CR 303.4j's, measured against the source: ``legal_host_for_source``.
    The seat asked nobody defaults to a land it does not itself control
    (``default_prefers``), since the Aura destroys what it is on.

    "May" is the pick being declinable (``optional``). Declined, or with no
    land to choose, nothing is recorded, the attach attaches nothing, and the
    Aura — on nothing — is put into its owner's graveyard by CR 704.5m, which
    is what Steam Vines' 2005-08-01 ruling says of that case.
    """
    host = node.host
    assert isinstance(host, ast.TargetSpec) and node.chooser is not None
    pick = _lower_choose_permanent(
        ast.ChoosePermanent(
            node.chooser,
            dataclasses.replace(
                host, filter=dataclasses.replace(host.filter, their_choice=False),
            ),
            optional=node.optional,
            host_for_source=True,
        ),
        produced,
    )
    choose = OracleInstruction(
        pick[0].kind, pick[0].value,
        {
            **pick[0].payload,
            "prompt": "Choose a permanent to attach it to.",
            "default_prefers": "not_the_choosers",
        },
    )
    attach = OracleInstruction(
        "attach_source_to_target", "", {"host_from": _ATTACH_HOST_KEY}
    )
    return (choose, attach)


def _lower_attach_chosen(node: ast.Attach) -> tuple[OracleInstruction, ...]:
    """"Attach target Aura attached to a creature or land to another permanent
    of that type." (Enchantment Alteration, CR 701.3 / 303.4j.)

    Two steps, not one fused kind. The host is *chosen as the spell resolves* —
    the sentence prints no second "target" — so it is a
    ``choose_permanent``, and the attach behind it reads the answer out of the
    resolution's ``results`` by the key named here. Written as a sequence for
    the reason every composite effect in this engine is: a second card that
    chose a permanent and then destroyed it would reuse the first step for
    free, where a ``move_aura_to_chosen_permanent`` kind would buy nothing.

    Both riders the host phrase prints are carried, and neither is dropped:
    "another" is ``exclude_relative_host`` and "of that type" is
    ``shares_type_with_relative_host``. ``of_bound_type`` is stripped off the
    filter *after* being read, because ``_filter_payload`` refuses it by name
    everywhere else — a lowering with no answer for "that type" must not emit a
    filter that quietly means "any type".
    """
    host = node.host
    if not isinstance(host, ast.TargetSpec) or host.quantifier != "a":
        raise LoweringError(
            "a chosen attachment needs one permanent to move onto", node=node
        )
    if host.targeted:
        raise LoweringError(
            "no handler attaches a chosen object to a second target", node=node
        )
    host_filter = dataclasses.replace(host.filter, of_bound_type=False)
    subject_payload = _filter_payload(node.subject.filter)
    _describe_targets(subject_payload, node.subject)
    choose = OracleInstruction("choose_permanent", "", {
        "filter": _filter_payload(host_filter),
        "result_key": _ATTACH_HOST_KEY,
        "prompt": "Choose a permanent to attach it to.",
        # Every narrowing below is stated relative to the chosen *target* — the
        # object being moved — because that is what "another" and "that type"
        # point back at.
        "relative_to": "target",
        "exclude_relative_host": host.distinct_from_prior,
        "shares_type_with_relative_host": host.filter.of_bound_type,
        # CR 303.4j: an Aura that can't legally enchant the permanent doesn't
        # move, so an illegal host is never offered in the first place.
        "legal_host_for_relative": True,
    })
    attach = OracleInstruction("attach_source_to_target", "", dict(
        subject_payload, subject_from="target", host_from=_ATTACH_HOST_KEY,
    ))
    return (choose, attach)


def _excess_left(amount: "ast.Minus", node) -> "ast.ObjectFilter":
    """The larger side of a printed "in excess of", as the noun phrase it counts.

    Two readers rather than one, and each refuses rather than guessing: a
    computed count this could not take apart would become a count of something
    else, and a choice sized from the wrong number takes the wrong permanents.
    """
    if not (
        isinstance(amount, ast.Minus)
        and isinstance(amount.left, ast.CountOf)
        and isinstance(amount.right, ast.CountOf)
    ):
        raise LoweringError("a printed difference counts two sets", node=node)
    return amount.left.filter


def _excess_right(amount: "ast.Minus", node) -> "ast.ObjectFilter":
    """:func:`_excess_left`'s other half — the number the excess is over."""
    _excess_left(amount, node)
    return amount.right.filter


#: Whose battlefield each half of an "in excess of" clause is counted on, as
#: the scope ``count_from_payload`` reads. A *scope* rather than a filter key
#: for ``lower_difference_damage``'s stated reason: nothing downstream tests a
#: controller, so a count narrowed by one is a count taken on the wrong
#: battlefield. Every seat the head clause may name has a row, and a reference
#: without one refuses.
_EXCESS_SCOPES: dict[str, str] = {
    "you": "you",
    "target_player": "target",
    "target_opponent": "target_opponent",
    "that_player": "target",
}


def _side_spec(described: "ast.ObjectFilter", node) -> dict:
    """One half of a printed difference, as a count spec scoped to its seat.

    The controller comes off the filter and goes on as ``owner`` — the same
    move ``lower_difference_damage`` makes for Superior Numbers, and for its
    reason: ``count_spec`` refuses a controller narrowing outright because the
    matcher underneath cannot test one.
    """
    scope = _EXCESS_SCOPES.get(described.controller or "you")
    if scope is None:
        raise LoweringError(
            f"no count reads the {described.controller}'s battlefield", node=node
        )
    spec = count_spec(dataclasses.replace(described, controller=None), node)
    spec["owner"] = scope
    return spec


#: Whose pile a counted choice's possessive names, per chooser. "…chooses a
#: permanent for each card in **their** graveyard": the pronoun agrees with
#: the sentence's subject, so the pile is the chooser's — the seat the
#: count is then taken on. The noun parser reads a bare "their" as ``owner``.
_CHOOSER_PILE_WORDS: frozenset[str] = frozenset({"owner", "that_player"})


def _chooser_pile_count(
    counted: "ast.ObjectFilter", chooser: "ast.PlayerRef", event: str | None, node,
) -> dict:
    """The count spec for "…for each card in their graveyard" behind a choice.

    The pile is the chooser's own, and the scope is the seat that chooser
    resolves to: the ability's controller for "you … your graveyard", the
    seat the firing event froze for "that player … their graveyard". Any
    other pairing names a pile this has no seat for and refuses, because a
    count taken on the wrong player's graveyard is a choice of the wrong size.
    """
    owner = counted.zone_owner.kind if counted.zone_owner is not None else None
    if chooser.kind == "you" and owner == "you":
        return count_spec(counted, node)
    if (
        chooser.kind == "that_player"
        and event in _EVENT_SUBJECT_PLAYERS
        and owner in _CHOOSER_PILE_WORDS
    ):
        spec = count_spec(dataclasses.replace(counted, zone_owner=None), node)
        spec["owner"] = EVENT_SUBJECT_PLAYER
        return spec
    raise LoweringError(
        "a counted choice counts the chooser's own pile", node=node
    )


def _lower_choose_permanents(
    node: ast.ChoosePermanent, produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"that player **chooses up to two Plains**" (Raiding Party.)

    The plural of the pick below, and a different instruction rather than a
    count on it: the answer is a *set*, which is a different shape on the wire,
    in ``results`` and in the default. What the two share is the candidate rule,
    and that already lives in one place.

    Two things the singular does not have to answer. **Where the picks go**: one
    key for the whole resolution, appended to by every iteration and every seat,
    because the sentence that reads it asks about "all Plains that weren't
    chosen this way **by any player**". And **who is asked**: inside "for each
    creature tapped this way, **that player** chooses…" the words name the seat
    an earlier step of this same effect wrote down about the creature the loop
    is on — the third channel ``PER_OBJECT_SEAT_RECORDS`` exists for, and the
    same reading ``lowering/damage.py`` gives the identical printed pronoun
    behind a destroy sweep.

    Gated on ``produced``, so the pronoun is admitted only where a step really
    wrote that record. Without one the words name nobody, and a prompt armed for
    a guessed seat is a decision taken from the wrong player.
    """
    spec = node.spec
    if node.host_for_source or node.optional:
        raise LoweringError(
            "a plural choice reads neither an enchant clause nor a decline",
            node=node,
        )
    described = spec.filter
    computed: dict[str, object] = {}
    if spec.count_amount is not None:
        # "**For each land target player controls in excess of the number you
        # control**, choose a land that player controls." (Equipoise.) How many
        # is a quantity the resolution computes, so it rides the payload as the
        # same ``count_spec`` every other computed number in this engine goes
        # through — one reader, so "the number of lands you control" means here
        # what it means printed anywhere else.
        #
        # It is a **floor as well as a ceiling**: the sentence says how many are
        # chosen, not how many may be. A ceiling alone would let a seat with
        # nothing to gain by it choose none, which is a card that does nothing.
        if isinstance(spec.count_amount, ast.CountOf):
            # "…that player chooses a permanent **for each card in their
            # graveyard**…" (Mist of Stagnation.) One set counted rather than
            # the difference of two, scoped to the seat the possessive names.
            computed["count_from"] = _chooser_pile_count(
                spec.count_amount.filter, node.chooser, event, node
            )
        else:
            computed["count_from"] = _side_spec(
                _excess_left(spec.count_amount, node), node
            )
            computed["count_from"]["minus"] = _side_spec(
                _excess_right(spec.count_amount, node), node
            )
        computed["exact_count"] = True
        # "…a land **that player** controls." The picked-from battlefield is a
        # seat, and ``subject_matches`` refuses a controller it has nobody to
        # compare against — so the narrowing is lifted out of the filter into
        # the ``controlled_by`` key the candidate rule already answers, exactly
        # as the destroy family lifts "of their choice" out of one. Left inside
        # it the phrase would refuse the line; dropped, the choice would be made
        # from every land on the table.
        if described.controller is not None:
            if described.controller != "that_player" or (
                event in _EVENT_SUBJECT_PLAYERS or event in _EVENT_SUBJECT_CONTROLLERS
            ):
                # Under an event that froze a seat, "that player" is that seat
                # and not the resolution's target — a different board, and one
                # the candidate rule has no word for. Refused rather than
                # guessed.
                raise LoweringError(
                    "the choice cannot be scoped to this player's battlefield",
                    node=node,
                )
            computed["controlled_by"] = "target"
            described = dataclasses.replace(described, controller=None)
    # Built in the order it has always been built in, with the computed keys
    # appended: the payload is compared as a *repr* by ``scripts/oracle_diff``,
    # so a key inserted ahead of another moves every card that never printed it
    # — three lines of noise around whatever a round is really about.
    # "**any number of** creatures they control" (Oracle en-Vec): no printed
    # ceiling, so the bound is however many candidates there are. ``unbounded``
    # rather than a very large ``up_to``, because the two differ in exactly what
    # a picker shows — a number, or none at all — and the handler is the only
    # place that knows how many candidates the board has.
    unbounded = spec.quantifier == "any_number"
    if spec.count_amount is None and described.controller is not None:
        # "Target opponent chooses any number of creatures **they control**."
        # (Oracle en-Vec.) "They" is the seat this sentence has already named —
        # the chooser — so the picked-from battlefield and the picking seat are
        # one answer, exactly as the singular pick beside this one resolves Echo
        # Chamber's identical possessive.
        #
        # Lifted out of the filter into the ``controlled_by`` key the candidate
        # rule answers, for that lowering's reason: ``subject_matches`` has
        # nobody to compare a bare "that_player" controller against, so left
        # inside it the phrase offers **nothing** and the card does nothing at
        # all. Any other possessive names a third seat this has no word for and
        # refuses.
        if described.controller != "that_player":
            raise LoweringError(
                "the choice cannot be scoped to this player's battlefield",
                node=node,
            )
        computed["controlled_by"] = "chooser"
        described = dataclasses.replace(described, controller=None)
    payload: dict[str, object] = {
        "filter": _filter_payload(described),
        **(
            {}
            if unbounded or spec.count_amount is not None
            else {"up_to": spec.count}
        ),
        "result_key": CHOSEN_THIS_WAY_OBJECTS,
        "prompt": (
            "Choose any number."
            if unbounded
            else f"Choose up to {spec.count}." if spec.count_amount is None
            else "Choose the permanents."
        ),
        **({"unbounded": True} if unbounded else {}),
        **computed,
    }
    untestable = untestable_filter_keys(payload["filter"])
    if untestable:
        raise LoweringError(
            "the choice cannot test " + ", ".join(sorted(untestable)), node=node
        )
    controller_record = PER_OBJECT_SEAT_RECORDS["controller"]
    if node.chooser.kind == "that_player" and controller_record in produced:
        payload["chooser_seat_record"] = controller_record
    elif node.chooser.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        # "At the beginning of each player's upkeep, **that player** chooses…"
        # (Mist of Stagnation.) The seat the step's announcement froze
        # (CR 603.10) — the singular pick's reading of the same pronoun
        # (Rising Waters), and a different seat every firing.
        payload["chooser"] = EVENT_SUBJECT_PLAYER
    elif node.chooser.kind in _CHOOSER_SEATS and node.chooser.kind != "that_player":
        payload["chooser"] = _CHOOSER_SEATS[node.chooser.kind]
        announced = _ANNOUNCED_CHOOSERS.get(node.chooser.kind)
        if announced is not None:
            # "**Target** opponent chooses…": the seat is announced as the
            # ability is activated (CR 602.2b), so the picker has to be offered
            # one — and ``_chooser_seat`` reads it back off the announcement
            # rather than taking the first opponent there is.
            payload["targets"] = dict(announced)
    else:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to choose permanents", node=node
        )
    return (OracleInstruction("choose_permanents", "", payload),)


def _lower_announced_choice(
    node: ast.ChoosePermanent,
) -> "tuple[OracleInstruction, ...] | None":
    """"**You** choose target creature an opponent controls" (Mogg Assassin).

    CR 601.2c/602.2b: a target is chosen as the spell is cast or the ability is
    activated, by the object's controller — so a sentence naming *that* seat as
    the chooser is the default said out loud, and it lowers to the announcement
    every other "Choose target creature" lowers to (Reincarnation, Glyph of
    Life) rather than to a prompt at resolution.

    Which matters in both directions. The picker offers the printed noun phrase
    at activation, so ``legality_abilities.activation_target_refusal`` can decline an
    ability with no legal target **before the tap cost is paid** — and Mogg
    Assassin taps as its cost, so a refusal after the fact is a real loss. And
    the narrowing a resolution-time prompt could not carry ("an opponent
    controls" is a seat, which ``_lower_choose_permanent`` below refuses
    outright) is an ordinary ``targets`` filter here, read by the enumerator
    every other targeted line goes through.

    None for every other chooser, which keeps the resolution-time reading for
    the seats that really do pick then — an opponent, the seat an event froze,
    the seat this effect chose.
    """
    if node.chooser.kind != "you" or node.optional or node.host_for_source:
        return None
    spec = node.spec
    if not spec.targeted or spec.quantifier != "target" or spec.count != 1:
        return None
    payload: dict[str, object] = {}
    _describe_targets(payload, spec)
    if "targets" not in payload:
        return None
    return (OracleInstruction("choose_target_permanent", "", payload),)


def _lower_choose_permanent(
    node: ast.ChoosePermanent, produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"<player> chooses <noun phrase> that this card could enchant."
    (Takklemaggot.)

    The same instruction Enchantment Alteration's host pick already uses, with
    the two differences the sentence prints carried as payload: **who** chooses
    (CR 601.2c does not make that the controller) and **which Aura** the
    legality is measured against. Enchantment Alteration measures it against
    the Aura it targeted; this card measures it against the ability's own
    source, which by resolution is a card in a graveyard — so the payload names
    the anchor rather than assuming one.
    """
    # "Whenever an artifact, creature, or enchantment enters, **its
    # controller** chooses …" (Confusion in the Ranks.) The controller of the
    # object the firing event was about — the seat ``_chooser_seat``'s
    # ``event_subject_controller`` row reads, frozen by the fire site
    # (CR 603.10). Only under an event that freezes it: anywhere else "its"
    # has no object, and a prompt armed for a guessed seat is a decision taken
    # from the wrong player.
    event_object_chooser = (
        node.chooser.kind == "controller" and event in _EVENT_SUBJECT_CONTROLLERS
    )
    if node.chooser.kind not in _CHOOSER_SEATS and not event_object_chooser:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to choose a permanent", node=node
        )
    described = node.spec.filter
    scoped: dict[str, object] = {}
    if described.controller == "another_player" and node.chooser.kind != "you":
        # "…its controller chooses target permanent **another player
        # controls**" (Confusion in the Ranks): a player other than the
        # *chooser*, which is a seat test against the seat being asked — not
        # the relative comparison ``subject_matches`` makes against the
        # ability's controller, which is a different player whenever the
        # entering permanent is an opponent's. Lifted into the candidate
        # rule's ``not_controlled_by`` for ``controlled_by``'s reason below.
        scoped["not_controlled_by"] = "chooser"
        described = dataclasses.replace(described, controller=None)
    if described.shares_card_type_with_it:
        # "…**that shares a card type with it**": "it" is the object the
        # firing event was about, frozen by id (CR 603.10) — so the anchor is
        # that object and the candidate rule asks CR 205.2a's relation
        # against it. Under any other event the pronoun has no referent.
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"shares a card type with it\" needs a trigger whose event "
                "freezes an object", node=node,
            )
        scoped["relative_to"] = "event_subject"
        scoped["shares_type_with_relative"] = True
        described = dataclasses.replace(described, shares_card_type_with_it=False)
    # "An opponent chooses **target creature they control**." (Echo Chamber.)
    # "Defending player chooses **an untapped creature they control**."
    # (Crashing Boars.) "They" is the seat this sentence has already named — the
    # chooser — so the picked-from battlefield and the picking seat are one
    # answer, exactly as Preacher's "of an opponent's choice **they** control"
    # resolves them in ``lowering/control_changes.py``.
    #
    # Lifted out of the filter into the ``controlled_by`` key the candidate rule
    # answers, for that lowering's reason: ``subject_matches`` has nobody to
    # compare a bare "that_player" controller against, so left inside it the
    # phrase refuses the line and dropped it would offer every creature on the
    # table. Any other possessive names a third seat this has no word for and
    # refuses.
    #
    # Asked of **every** spelling rather than only the targeted one. Which
    # battlefield "they control" names does not depend on whether the word
    # "target" was printed in front of the noun, and the untargeted branch is
    # the one where dropping it costs most: nothing announced the choice, so
    # there is no announcement-time check to catch the widened set either.
    if described.controller == "you":
        # "Choose a permanent **you control**." (Guard Dogs.) The chooser is
        # the effect's own controller, and so is "you" (CR 109.5) — one seat,
        # and the one ``permanent_choice_candidates`` already measures a
        # relative key from. So the word stays in the filter, where
        # ``subject_matches`` answers it against that observer, rather than
        # being lifted into a scope written for a seat the handler has to look
        # up.
        #
        # "**An opponent** chooses a permanent **you control** …" (Wormfang
        # Crab.) The same word with somebody else picking, and the same
        # answer: "you" is still the effect's controller whoever is asked, and
        # the candidate rule measures it from ``context.caster`` — never from
        # the chooser — so the opponent is offered the Crab controller's board.
        # It used to fall to the branch below, which reads every controller
        # word as the chooser's own "they control" and refused this one.
        pass
    elif described.controller is not None:
        if described.controller != "that_player":
            raise LoweringError(
                "the choice cannot be scoped to this player's battlefield",
                node=node,
            )
        scoped["controlled_by"] = "chooser"
        described = dataclasses.replace(described, controller=None)
    announced = _ANNOUNCED_CHOOSERS.get(node.chooser.kind)
    if announced is not None:
        # The singular's half of the plural's announcement above, and the same
        # reason: a printed "target" is a seat the caster chooses.
        scoped["targets"] = dict(announced)
    if node.spec.targeted:
        # "An opponent chooses **target** creature they control." (Echo
        # Chamber.) The word is printed on the *permanent* here, not on the
        # chooser, and CR 602.3 is the rule that makes sense of the pair: an
        # ability may say an opponent does what its controller normally would —
        # choosing targets among them — and "the opponent does so when the
        # ability's controller normally would do so", which CR 601.2c puts at
        # the announcement.
        #
        # This engine still makes the pick at resolution, so the word buys one
        # thing rather than all of it: CR 601.2c's legality. An ability whose
        # announced target has no legal object cannot be activated at all, and
        # without this key nothing could tell that Echo Chamber's {4} and {T}
        # were being paid into a choice with no candidates. The rest of 602.3 —
        # the choice made in the announcement, so it can be responded to and
        # re-checked under CR 608.2b — needs a prompt owed by a seat that is not
        # the activator, which is recorded in ROADMAP.md rather than faked here.
        scoped["announced_target"] = True
    seat = (
        "event_subject_controller" if event_object_chooser
        else _CHOOSER_SEATS[node.chooser.kind]
    )
    if node.chooser.kind == "that_player" and CHOSEN_PLAYER in produced:
        # "You choose target creature an opponent controls, and **that
        # opponent** chooses target creature." (Mogg Assassin.) No event fired —
        # this is an activated ability — so the seat the pronoun names is the
        # one an earlier *step of this same effect* recorded, which is exactly
        # what Retribution's "that player chooses and sacrifices" reads, under
        # the same key and through the same ``_chooser_seat`` row.
        #
        # Gated on ``produced`` rather than tried as a fallback, for the reason
        # ``_lower_choose_permanents`` states about its own pronoun: without a
        # step that really wrote the record the words name nobody, and a prompt
        # armed for a guessed seat is a decision taken from the wrong player.
        # A *trigger* whose fire site froze the seat writes no such record, so
        # its own "that player" keeps the frozen reading.
        seat = "chosen_player"
    # "When this creature enters, **an opponent** chooses a permanent you
    # control …" (Wormfang Crab.) A choice made as the effect is applied, so
    # CR 608.2d has its controller announce the unnamed seat — which opponent —
    # the ``choose_opponent`` step Animal Magnetism and Guided Passage put in
    # front of their own picks, writing the record ``_chooser_seat``'s
    # "chosen_player" row reads. Asked only where there is more than one
    # opponent and a person in the controller's seat; anyone else takes the
    # first opponent. Not for a printed "target" (Echo Chamber): that choice
    # belongs to the announcement (CR 602.3a), its activation gate reads every
    # opponent's board, and the "opponent" chooser's handler names the seat
    # itself (``handlers/player_choices.ask_which_opponent``).
    announces_opponent = (
        node.chooser.kind == "opponent" and not scoped.get("announced_target")
    )
    if announces_opponent:
        seat = "chosen_player"
    payload: dict[str, object] = {
        "filter": _filter_payload(described),
        "result_key": _ATTACH_HOST_KEY,
        "prompt": "Choose a permanent.",
        "chooser": seat,
        "optional": node.optional,
        # Appended rather than inserted, for ``_lower_choose_permanents``'
        # stated reason: the payload is compared as a repr by
        # ``scripts/oracle_diff``, so a key ahead of another moves every card
        # that never printed it.
        **scoped,
    }
    untestable = untestable_filter_keys(payload["filter"])
    if untestable:
        raise LoweringError(
            "the choice cannot test " + ", ".join(sorted(untestable)), node=node
        )
    if node.host_for_source:
        # CR 303.4j, measured against the ability's own source — the same
        # predicate the attach itself re-asks, so an illegal host is never
        # offered and never accepted.
        payload["legal_host_for_source"] = True
    if node.at_random:
        # "Choose a creature **at random** this Aura can enchant." (Infectious
        # Rage.) The handler draws from the candidate list rather than asking,
        # so nothing about a decline or a prompt applies: refused together with
        # them rather than carried as a pair the handler would have to rank.
        if node.optional or "targets" in scoped or scoped.get("announced_target"):
            raise LoweringError(
                "a random pick asks nobody, so it has no decline and no "
                "announced seat",
                node=node,
            )
        payload["at_random"] = True
    if announces_opponent:
        return (
            OracleInstruction(
                "choose_opponent", "",
                {
                    "result_key": CHOSEN_PLAYER,
                    "prompt": "Choose an opponent to choose a permanent.",
                },
            ),
            OracleInstruction("choose_permanent", "", payload),
        )
    return (OracleInstruction("choose_permanent", "", payload),)


#: The two chooser words that are *announced* rather than resolved at
#: resolution, and the picker each one means. A description written here for
#: the reason every other ``targets`` payload in this package is written where
#: it is: ``target_descriptions._from_targets_payload`` reads it, and an ability that
#: names a target and describes none derives no picker at all.
_ANNOUNCED_CHOOSERS: dict[str, dict] = {
    "target_player": {"quantifier": "target", "kind": "player"},
    "target_opponent": {
        "quantifier": "target", "kind": "player", "opponents_only": True,
    },
}


def _lower_choose_graveyard_card(
    node: ast.ChooseGraveyardCard,
) -> tuple[OracleInstruction, ...]:
    """"**Target opponent** chooses an artifact card in their graveyard."
    (Scrounge.)

    ``choose_graveyard_card``: the chooser's pick of one card out of their own
    pile, made as the effect resolves through the graveyard pick prompt, its
    card recorded for the sentence behind it (``CHOSEN_GRAVEYARD_CARD``). The
    narrowing is ``one_card_pile_pick``'s — one card type or none, a colour,
    "other than this card" — so the candidate rule is the graveyard exile
    pick's own, and anything wider refuses.

    Only an **announced** chooser: the seat is a target (CR 601.2c), so the
    picker offers it and ``_chooser_seat`` reads it back. Any other seat would
    need a reader this does not have, and a guessed seat is a decision taken
    from the wrong player.
    """
    announced = _ANNOUNCED_CHOOSERS.get(node.chooser.kind)
    if announced is None:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to choose a card in their "
            "graveyard",
            node=node,
        )
    payload: dict[str, object] = {
        **one_card_pile_pick(node.filter, "chooser", node),
        "chooser": _CHOOSER_SEATS[node.chooser.kind],
        "targets": dict(announced),
    }
    return (OracleInstruction("choose_graveyard_card", "", payload),)
