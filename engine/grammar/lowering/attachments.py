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
from ._common import (_describe_targets, _filter_payload, _is_source, _is_target,
                      _restrictions_beyond)
from ._amounts import count_spec
from ._events import (CHOSEN_PERMANENT as _ATTACH_HOST_KEY,
                      CHOSEN_PLAYER, _EVENT_SUBJECT_CONTROLLERS,
                      _EVENT_SUBJECT_PLAYERS, _RECORDED_PERMANENTS)


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
    than a pick between two. The same two questions ``counters.py`` asks of the
    identical pronoun for Bogardan Phoenix, and the same answer: a step that put
    a permanent onto the battlefield is what changes what the word means.
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
    if isinstance(node.subject, ast.TargetSpec) and _is_target(node.subject):
        return _lower_attach_chosen(node)
    if not isinstance(node.subject, ast.TargetSpec) or not _is_source(node.subject):
        raise LoweringError(
            "no handler attaches anything but the source itself", node=node
        )
    recorded = _lower_attach_to_recorded(node, produced)
    if recorded is not None:
        return recorded
    if not isinstance(node.host, ast.TargetSpec) or not _is_target(node.host):
        raise LoweringError("attach needs one chosen permanent to attach to", node=node)
    payload = _filter_payload(node.host.filter)
    _describe_targets(payload, node.host)
    return (OracleInstruction("attach_source_to_target", "", payload),)


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
        computed["count_from"] = _side_spec(_excess_left(spec.count_amount, node), node)
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
    at activation, so ``legality.activation_target_refusal`` can decline an
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
    node: ast.ChoosePermanent, produced: frozenset[str] = frozenset()
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
    if node.chooser.kind not in _CHOOSER_SEATS:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to choose a permanent", node=node
        )
    described = node.spec.filter
    scoped: dict[str, object] = {}
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
    if described.controller is not None:
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
    seat = _CHOOSER_SEATS[node.chooser.kind]
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
    return (OracleInstruction("choose_permanent", "", payload),)


#: The two chooser words that are *announced* rather than resolved at
#: resolution, and the picker each one means. A description written here for
#: the reason every other ``targets`` payload in this package is written where
#: it is: ``targeting._from_targets_payload`` reads it, and an ability that
#: names a target and describes none derives no picker at all.
_ANNOUNCED_CHOOSERS: dict[str, dict] = {
    "target_player": {"quantifier": "target", "kind": "player"},
    "target_opponent": {
        "quantifier": "target", "kind": "player", "opponents_only": True,
    },
}


#: Which printed subjects a choice prompt can actually be aimed at. "That
#: creature's controller" is the seat the firing event named, which only an
#: event that froze one can answer — so the lowering names the word and the
#: handler resolves it, rather than either of them guessing a default.
_CHOOSER_SEATS = {
    "you": "you",
    "that_player": "event_subject_controller",
    "target_player": "target",
    # "**Target opponent** chooses any number of creatures they control."
    # (Oracle en-Vec.) The *announced* seat, not "whichever opponent is left":
    # the word "target" is CR 601.2c/602.2b, and the caster picks which player
    # is asked as the ability goes on the stack.
    #
    # This row read ``"opponent"`` — the same answer the untargeted phrase
    # below gets — with a note arguing that which of the two a sentence prints
    # "changes nothing about who is asked". In a duel it does not. At three
    # seats it is the whole of the choice, and ``picker_sweep`` says so
    # outright: an activated ability that prints "target" and derives no picker
    # is the Roots class. Nothing in the pool printed the phrase until now,
    # which is why the collapse survived.
    "target_opponent": "target",
    # "**Defending player** chooses an untapped creature they control."
    # (Crashing Boars.) CR 506.2's seat, which only a trigger that froze one can
    # answer: the ability resolves after the declare-attackers step, and a
    # combat with several defenders (CR 802) has a defending player *per
    # attacking creature* — so the seat is read out of the trigger's own
    # context, under the key every combat fire site already stamps, rather than
    # re-derived from a board the resolution has already changed.
    "defending_player": "trigger_defending_player",
    # "**An opponent** chooses target creature they control." (Echo Chamber.)
    # The row where the *chooser* is not announced: no "target opponent" here,
    # so ``_chooser_seat`` answers with the first live opponent rather than
    # reading a seat off the announcement, and it is this row's narrowing at
    # three seats, not the targeted row's above.
    #
    # **The rule it narrows is CR 602.3, and this comment used to name the wrong
    # one.** It read "the rules would have the *controller* choose (CR 601.2c
    # does not apply, so it is an ordinary choice made on resolution)". Both
    # halves are about a different sentence than the one printed here: the card
    # says an opponent chooses, and CR 602.3 is the rule that has room for
    # exactly that — "some abilities specify that one of their controller's
    # opponents does something the controller would normally do while it's being
    # activated, such as choose a mode or choose targets. In these cases, the
    # opponent does so when the ability's controller normally would do so." So
    # CR 601.2c *does* apply; 602.3 only moves who answers it.
    #
    # What is really narrowed here is **which** opponent: the ability's
    # controller chooses that, and this takes the first live one. What was
    # narrowed as well — and is now fixed — is that a printed "target" carries
    # CR 601.2c's legality with it, so the ability cannot be activated when the
    # chooser has nothing to choose (``legality._announced_choice_refusal``).
    # What is still narrowed is the *timing*: the pick happens as the ability
    # resolves rather than in its announcement, so nothing can be held in
    # response to it. ROADMAP.md carries that with what closing it needs.
    "opponent": "opponent",
}
