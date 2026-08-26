"""Lowering the zone changes: where an object goes (CR 400).

Split out of `lowering/board.py` when that file crossed 1,000 lines. A family
rather than an arbitrary cut: everything here answers one question — which zone
does this object end up in — and none of it touches the battlefield state the
rest of `board` is about (tapping, destruction, regeneration, control).

It has no twin in `effects/`, and that is deliberate rather than an oversight.
The parsing side of these templates is small — one `return`/`exile`/`put`
production each, all still in `effects/board.py` — while the lowering side is
where the work is, because every one of them has to decide *which* handler moves
the object and refuse the shapes none of them implement. A near-empty
`effects/zones.py` would buy the symmetry and cost the thing symmetry is for.
"""

from __future__ import annotations

import dataclasses


from ...oracle_types import OracleInstruction
from ...subject_filters import (OBJECT_ONLY_FILTER_KEYS,
                                TESTABLE_SUBJECT_FILTER_KEYS)
from .. import ast
from ..errors import LoweringError
from ._events import (EVENT_SUBJECT_OWNER, _EVENT_SUBJECT_OWNERS,
                      _back_reference_payload)
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    dropped_narrowings,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_target,
    _restrictions_beyond,
    _describe_several_card_targets,
    _describe_several_targets,
    _names_several_targets,
)


# The filter both exile shapes are compared against. Two readers, one
# definition — an equality check written twice is two chances to widen one
# of them.
_EXILED_CREATURE = ast.ObjectFilter(card_types=("creature",))


def _reads_no_return_restriction(filt: ast.ObjectFilter) -> bool:
    """Whether *filt* carries a narrowing none of the zone-change handlers reads.

    All three take their whole instruction from the card: two read an empty
    payload and the third reads one boolean. So any adjective beyond the card
    type is invisible to them, and a filter carrying one has to refuse — "return
    target *black* creature card from your graveyard to your hand" lowered to
    Raise Dead's instruction would happily return a white one.
    """
    tri_state = (filt.tapped, filt.attacking, filt.blocking, filt.blocked)
    return bool(
        filt.supertypes or filt.subtypes or filt.colors or filt.excluded_colors
        or filt.excluded_types or filt.excluded_subtypes or filt.with_keywords
        or filt.without_keywords or filt.controller or filt.power or filt.toughness
        or filt.mana_value or filt.named or filt.other_than_source
        or filt.is_source or filt.is_enchanted
        or any(state is not None for state in tri_state)
    )


def _graveyard_to_hand_payload(filt: ast.ObjectFilter) -> dict[str, object]:
    """The card-type half of a graveyard-to-hand return's payload.

    One function because the one-card and several-card branches have to narrow
    *identically*: the named card type is a filter the handler applies, so it is
    carried rather than collapsed - reading "artifact card" as "any card" would
    let Reconstruction return a creature. A *union* ("instant or sorcery card",
    Shipwreck Dowser) travels as its own additive key, so Raise Dead's payload
    stays byte-identical. Two copies of this is how "up to two target artifact
    cards" ends up returning a creature.
    """
    if len(filt.card_types) > 1:
        return {
            "any_card": False,
            "card_type": None,
            "card_types": list(filt.card_types),
        }
    card_type = filt.card_types[0] if filt.card_types else None
    return {"any_card": card_type is None, "card_type": card_type}


def _lower_return_to_zone(
    node: ast.ReturnToZone,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Return <object> [from <zone>] to <zone>" — Raise Dead, Regrowth,
    Resurrection and Unsummon.

    The *pair* of zones picks the handler, which is why they are both parsed
    rather than pattern-matched out of the sentence: graveyard→hand,
    graveyard→battlefield and battlefield→owner's hand are three unrelated
    handlers reading three different target indices (a graveyard position, a
    graveyard position, a battlefield position). The legacy rules told them
    apart by substring, and told Raise Dead from Regrowth by probing for
    ``"creature card" not in text`` — which is why "return target artifact card
    from your graveyard to your hand" would have returned a creature.

    Nothing here is described for engine/targeting.py. The `targets` vocabulary
    names battlefield permanents, so describing a graveyard card with it would
    tell the picker to offer creatures in play for a reanimation spell — the
    exact bug the Animate Dead targeting test pins.
    """
    # "Return target spell or creature to its owner's hand." (Unsubstantiate):
    # a spell on the stack goes back to its owner's hand (CR 608.2b never
    # applies — the spell is the target, not a resolver of it), a creature is
    # the ordinary bounce. One instruction; the handler branches on which kind
    # of object was chosen.
    if node.also_stack:
        return (OracleInstruction("return_spell_or_creature_to_hand", "", {}),)
    subject = node.subject
    if node.repetitions is not None:
        # "Return a card from your graveyard to your hand **for each card
        # discarded this way**." (Recall.) A count nobody knows until an earlier
        # step of this resolution has been answered, so the cards cannot be
        # chosen as targets when the spell is cast (CR 601.2c) — they are picked
        # while it resolves, out of the chooser's own graveyard, which is a
        # public zone with nothing for targeting to protect.
        #
        # Admitted in exactly the shape the handler performs, and refused
        # otherwise: a clause that parsed and then lowered onto the single-card
        # return would silently return one card however many were discarded.
        if not (
            isinstance(subject, ast.TargetSpec)
            and not subject.targeted
            and subject.quantifier == "a"
            and subject.count == 1
            and subject.filter.is_card
            and subject.filter.zone == "graveyard"
            and subject.filter.zone_owner is not None
            and subject.filter.zone_owner.kind == "you"
            and node.to.name == "hand"
            and node.to.owner is not None
            and node.to.owner.kind == "you"
        ):
            raise LoweringError(
                "no repeated return handler for this shape", node=node
            )
        if _reads_no_return_restriction(subject.filter):
            raise LoweringError("no return handler honours this restriction", node=node)
        payload: dict[str, object] = dict(_graveyard_to_hand_payload(subject.filter))
        # Where the number comes from, decided in the one place that decides it
        # for every back-reference — and refused outright when no step of this
        # effect records the key, because "for each card discarded this way"
        # with no discard in front of it names nothing at all.
        payload.update(_back_reference_payload(node.repetitions, produced, event))
        return (
            OracleInstruction(
                "return_chosen_cards_from_graveyard_to_hand", "", payload
            ),
        )
    # "Return up to two target creatures to their owners' hands." (Read the
    # Tides' second mode.) Same instruction as the single-target bounce — the
    # effect per creature is identical — described with the several-targets
    # opt-in so the handler resolves a list and the picker collects up to N.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
        and not subject.filter.is_card
        and subject.filter.card_types == ("creature",)
    ):
        several: dict[str, object] = {}
        _describe_several_targets(several, subject)
        return (OracleInstruction("bounce_target_creature", "", several),)
    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The same instruction as the one-card return - the
    # effect per card is identical, and `_graveyard_to_hand_payload` is the same
    # narrowing - plus the several-targets opt-in, which is what says the handler
    # resolves a list and the picker collects up to N.
    #
    # Gated to exactly the shape that handler reads: the caster's own graveyard,
    # their own hand, and nothing `_reads_no_return_restriction` refuses for the
    # one-card path, since the several path reads the same payload keys and no
    # more. "Up to two target **black** creature cards" therefore refuses rather
    # than returning any two.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.from_zone.owner is not None
        and node.from_zone.owner.kind == "you"
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
        and subject.filter.is_card
    ):
        if _reads_no_return_restriction(subject.filter):
            # Raised here rather than left to the generic refusal below, so the
            # named clause says which half is missing: the arity is fine and the
            # adjective is not.
            raise LoweringError("no return handler honours this restriction", node=node)
        several_cards = _graveyard_to_hand_payload(subject.filter)
        _describe_several_card_targets(several_cards, subject)
        return (
            OracleInstruction(
                "return_creature_from_graveyard_to_hand", "", several_cards
            ),
        )
    # "Return **this card** from your graveyard to the battlefield [tapped]."
    # (Silversmote Ghoul; CR 113.6m's own example is Reassembling Skeleton.)
    # Nothing is chosen — the ability names the object it is printed on — so this
    # is not a targeted return and never reaches `_is_target` below.
    #
    # `functions_from` is the load-bearing key and it is *derived*, not declared:
    # CR 113.6m says an ability whose effect moves the object it is on out of a
    # zone functions only in that zone, so the zone the sentence names as the
    # source is the zone the ability works from. The scan in engine/events.py
    # reads that key rather than a list of instruction kinds, for the reason
    # end_step.py's intervening-if gate is keyed on a payload shape: a list is
    # only ever as complete as the last card that touched it.
    if _is_source(subject) and node.from_zone is not None and node.from_zone.name == "graveyard":
        assert isinstance(subject, ast.TargetSpec)
        if node.from_zone.owner is None or node.from_zone.owner.kind != "you":
            raise LoweringError(
                "a card returns itself from its owner's graveyard", node=node
            )
        if node.to.name != "battlefield" or node.to.owner is not None:
            raise LoweringError(
                f"no handler returns a card from the graveyard to the {node.to.name}",
                node=node,
            )
        # Every ObjectFilter field beyond the three the phrase "this card from
        # your graveyard" sets. Written against the dataclass, so a restriction
        # added later refuses rather than being silently dropped.
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_source", "zone", "zone_owner"})
        )
        if leftovers:
            raise LoweringError(
                f"the self-return handler does not honour {leftovers[0]!r}", node=node
            )
        return (
            OracleInstruction(
                "return_self_from_graveyard", "",
                {"tapped": node.entering_tapped, "functions_from": "graveyard"},
            ),
        )
    # "…you may return **an** instant or sorcery card from your graveyard to
    # your hand." (Experimental Overload.) Chosen but not targeted (CR 115.1):
    # the card is in the chooser's own graveyard, so there is nothing for
    # targeting to protect — no shroud, no protection, no "changes target"
    # effect can reach it — and the picker the targeted spelling already uses is
    # the same picker. Admitted only in that shape: a *bare* quantifier over
    # anyone else's zone, or over the battlefield, still refuses.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
        and subject.filter.zone_owner is not None
        and subject.filter.zone_owner.kind == "you"
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
    ):
        if _reads_no_return_restriction(subject.filter):
            raise LoweringError("no return handler honours this restriction", node=node)
        return (
            OracleInstruction(
                "return_creature_from_graveyard_to_hand", "",
                _graveyard_to_hand_payload(subject.filter),
            ),
        )
    # "Return a creature card from **its owner's** graveyard to the battlefield
    # **under the control of that creature's owner**." (Reincarnation.)
    #
    # Both possessives name one player and it is neither of the two a return
    # normally knows: not the chooser (CR 608.2c makes that the ability's
    # controller, who picks the card) and not the card's own owner in the
    # tautological sense (CR 404.2 puts every card in its owner's graveyard, so
    # that reading would admit every graveyard on the table). They name the
    # object *this sentence is about* — the creature the delayed ability was
    # bound to — which is why this shape is admitted only under an event whose
    # fire site actually froze that owner. Under any other trigger the words
    # name a player nobody recorded.
    #
    # It lowers to the ordinary open-zone pick, with the two seats as payload:
    # the picker, the AI and the resolver all read them through
    # `engine.search_filters.searched_seat` / `landing_seat`, so one answer
    # decides whose graveyard is shown and whose battlefield receives.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
        and subject.filter.zone_owner is not None
        and subject.filter.zone_owner.kind == "owner"
        and node.to.name == "battlefield"
        and node.under_control_of is not None
        and node.under_control_of.kind == "owner"
    ):
        if event not in _EVENT_SUBJECT_OWNERS:
            raise LoweringError(
                "\"its owner\" names the object this sentence is about, and no "
                "trigger here recorded one",
                node=node,
            )
        if node.entering_tapped or _reads_no_return_restriction(subject.filter):
            raise LoweringError("no return handler honours this restriction", node=node)
        if len(subject.filter.card_types) != 1:
            raise LoweringError("the graveyard pick reads one card type", node=node)
        return (
            OracleInstruction(
                "search_library", "",
                {
                    "zones": ("graveyard",),
                    "card_type": subject.filter.card_types[0],
                    "destination": "battlefield",
                    "zone_owner": EVENT_SUBJECT_OWNER,
                    "battlefield_owner": EVENT_SUBJECT_OWNER,
                },
            ),
        )
    if not _is_target(subject):
        # "target" and "up to one target" (Liliana, Death Mage's +1) both
        # resolve one chosen object; anything wider has no handler.
        raise LoweringError("no handler for returning a non-targeted object", node=node)
    assert isinstance(subject, ast.TargetSpec)
    filt = subject.filter

    # The blanket refusal is the *graveyard* returns' gate, and only theirs:
    # each of those takes a fixed payload and reads at most a card type, so any
    # adjective beyond it would be invisible to them. The bounce path below
    # gates itself instead, against what ``subject_matches`` can test — a
    # stronger question than a hand-kept list of exceptions to this one, which
    # is what it used to be (``excluded_subtypes``, ``other_than_source``,
    # ``controller``, ``excluded_types``, stripped before asking).
    if node.from_zone is not None and _reads_no_return_restriction(filt):
        raise LoweringError("no return handler honours this restriction", node=node)

    source, destination = node.from_zone, node.to

    if source is not None and source.name == "graveyard":
        # Both graveyard handlers search the caster's own graveyard and nowhere
        # else, so "from a graveyard" is a different card, not a wording of this
        # one.
        if source.owner is None or source.owner.kind != "you":
            raise LoweringError("no handler searches a graveyard but your own", node=node)
        if not filt.is_card:
            raise LoweringError("a graveyard holds cards, not permanents", node=node)

        if destination.name == "hand":
            if destination.owner is None or destination.owner.kind != "you":
                raise LoweringError("this handler returns cards to your own hand", node=node)
            return (
                OracleInstruction(
                    "return_creature_from_graveyard_to_hand",
                    "",
                    _graveyard_to_hand_payload(filt),
                ),
            )

        if destination.name == "battlefield":
            if destination.owner is not None:
                raise LoweringError("no handler for a reanimation under another's control", node=node)
            # `reanimate_creature` only ever puts a creature onto the
            # battlefield. Regrowth's untyped "target card" has no lowering
            # here: claiming it would silently narrow the player's choice.
            if filt.card_types != ("creature",):
                raise LoweringError("the reanimation handler only moves creature cards", node=node)
            return (OracleInstruction("reanimate_creature", "", {}),)

        raise LoweringError(f"no handler moves a card to the {destination.name}", node=node)

    if source is None and destination.name == "hand":
        # A permanent going home. `bounce_target_creature` returns it to its
        # owner's hand by construction, so "to your hand" is a different effect
        # (it matters the moment you have stolen the creature) and refuses.
        if destination.owner is None or destination.owner.kind != "owner":
            # "…to **your** hand" is a different place from "its owner's hand"
            # — the moment you have stolen the permanent, they are two players'
            # hands — so the bounce handler, which always returns a permanent
            # to its owner, cannot carry it.
            #
            # Unless the card says you own it. "Return target permanent you
            # both own and control to your hand" (Obelisk of Undoing) narrows
            # the target to the case where the two hands are the same hand, so
            # the handler is exactly right and the refusal below would be
            # refusing on a distinction the card already made.
            owns_it = (
                isinstance(node.subject, ast.TargetSpec)
                and node.subject.filter is not None
                and node.subject.filter.owner == "you"
            )
            if not (owns_it and destination.owner is not None
                    and destination.owner.kind == "you"):
                raise LoweringError(
                    "the bounce handler returns a permanent to its owner", node=node
                )
        if filt.is_card:
            raise LoweringError("no handler bounces a card that is not in play", node=node)
        # **The printed noun is payload, not a kind.** A bounce returns whatever
        # the phrase named to its owner's hand — a creature (Unsummon), any
        # permanent (Boomerang), an Island (Flash Flood), a nonland permanent
        # (Sublime Epiphany) — and the effect per object is the same one. So
        # what the line has to clear is not "does it say creature?" but "can the
        # narrowing it *does* say be tested?", asked in the two places a filter
        # can go missing:
        #
        # * ``_filter_payload`` refuses a narrowing with no payload form at all,
        #   so it cannot be dropped between the AST and the dispatcher;
        # * ``TESTABLE_SUBJECT_FILTER_KEYS`` refuses one that has a form
        #   ``subject_matches`` cannot answer, so it cannot be dropped between
        #   the dispatcher and the permanent.
        #
        # Everything surviving both is honoured by the same ``subject_matches``
        # the picker, the cast gate and the handler's predicate each ask, which
        # is what lets a phrase nobody wrote a branch for still bounce exactly
        # what it printed. This replaced a hand-kept list of the four narrowings
        # the branch below carried, under which "target permanent" refused for
        # want of an adjective and "target artifact" refused for being the wrong
        # noun.
        # The first half, over the AST: a field ``to_payload`` does not read at
        # all leaves no key for the second half to inspect, so "target
        # **enchanted** creature" would reduce to "target creature" and bounce
        # one that was never enchanted.
        unread = _restrictions_beyond(filt, _PAYLOAD_HONOURED_FILTER_FIELDS)
        if unread:
            raise LoweringError(
                "the bounce handler cannot read " + ", ".join(sorted(unread)),
                node=node,
            )
        bounce_filter = _filter_payload(filt)
        untestable = set(bounce_filter) - TESTABLE_SUBJECT_FILTER_KEYS
        if untestable:
            raise LoweringError(
                "the bounce handler cannot test "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        if bounce_filter == {"type_filter": "creature"}:
            # Unsummon's payload, byte-identical: the bare bounce carries no
            # filter because "creature" is what every reader of this kind
            # already defaults to.
            return (OracleInstruction("bounce_target_creature", "", {}),)
        payload: dict[str, object] = {"filter": bounce_filter}
        _describe_targets(payload, subject)
        return (OracleInstruction("bounce_target_creature", "", payload),)

    raise LoweringError("no handler for this zone change", node=node)

def _lower_exile(node: ast.Exile) -> tuple[OracleInstruction, ...]:
    """"Exile target creature until end of turn." — and nothing else.

    ``exile_target_creature_until_eot`` is the one exile handler that stands on
    its own: it moves the creature to exile and records the return
    (CR 406.1/400.7), so the whole sentence is what it performs. Every part of
    the clause is checked against that rather than dropped —

    * **the duration.** Without it the sentence is a *permanent* exile, which
      this handler does not perform: it would return the creature at cleanup.
    * **the subject.** A chosen creature, not a sweep and not the source: the
      handler resolves one target permanent.

    A duration this file does not implement is refused rather than falling
    through to the permanent exile below. "Exile it until this creature leaves
    the battlefield" is a different effect, and lowering it onto a permanent
    exile would be the loudest possible mis-play: the card would never come
    back.

    With no duration the sentence is a permanent exile, and *which* handler
    performs it is a question about the zone the subject names:

    * **the battlefield** — ``exile_target_permanent``. The permanent leaves
      through ``remove_from_battlefield`` and its card goes to its owner's
      exile (CR 400.3, CR 406.1).
    * **a graveyard** — ``exile_target_graveyard_card``. No permanent is
      involved, so the battlefield-scoped filter payload would point both the
      handler and engine/targeting.py at the wrong zone; ``_filter_payload``
      already refuses that shape, which is why this branch comes first.

    ``exile_creature_gain_life_equal_to_power`` stays unreachable from here: it
    performs *both* halves of Swords to Plowshares' sentence, so a bare
    ``Exile`` lowering onto it would gain life the card never offered.
    """
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        subject = node.subject
        if (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "target"
            and subject.count == 1
            and subject.filter == _EXILED_CREATURE
        ):
            payload: dict[str, object] = {}
            _describe_targets(payload, subject)
            return (OracleInstruction("exile_target_creature_until_eot", "", payload),)
        raise LoweringError(
            "the temporary-exile handler resolves one targeted creature", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler exiles for the duration {node.duration.kind!r}", node=node
        )

    subject = node.subject
    if isinstance(subject, ast.TargetSpec) and subject.quantifier in ("each", "all"):
        # "Exile each permanent with mana value X or less that's one or more
        # colors." (Ugin, the Spirit Dragon's −X.) The payload is hand-rolled:
        # ``to_payload`` cannot carry a *variable* mana-value bound, and
        # dropping the bound would widen the sweep to every mana value.
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError("the exile sweep reads battlefield permanents", node=node)
        payload: dict[str, object] = {}
        # Two keys the ordinary filter payload has no form for, lifted off the
        # filter before the rest of it is read the way every other sweep reads
        # one. ``mana_value`` because the bound may be the spell's **X**, which
        # is not a number until the ability resolves; ``colored`` because
        # "that's one or more colors" is a question about the computed colours
        # rather than about a named one.
        if filt.colored:
            payload["colored_only"] = True
        if filt.mana_value is not None:
            bound = filt.mana_value.value
            payload["mana_value"] = {
                "op": filt.mana_value.op,
                "value": bound.value if isinstance(bound, ast.Fixed) else bound.name,
            }
        rest = dataclasses.replace(filt, colored=False, mana_value=None)
        # Everything else the noun phrase printed — "exile all **Sand
        # Warriors**" (Hazezon Tamar). The sweep used to hand-roll a
        # ``type_filter`` and refuse every other narrowing, which cost Hazezon
        # its second ability; the honest widening is to carry the payload the
        # matcher already answers and refuse only what it cannot test.
        #
        # ``OBJECT_ONLY_FILTER_KEYS``, not the full testable set: the handler
        # sweeps every battlefield with no observer seat and no source
        # permanent, so "you control" and "another" have nothing to be relative
        # to and would be dropped where they are tested.
        narrowings = _filter_payload(rest)
        unusable = sorted(set(narrowings) - OBJECT_ONLY_FILTER_KEYS)
        leftovers = _restrictions_beyond(
            rest, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone"}
        ) + dropped_narrowings(rest, narrowings) + tuple(unusable)
        if leftovers:
            raise LoweringError(
                f"the exile sweep does not honour {leftovers[0]!r}", node=node
            )
        payload.update(narrowings)
        return (OracleInstruction("exile_all_matching", "", payload),)
    if isinstance(subject, ast.TargetSpec) and subject.quantifier == "any_number":
        # "Exile **any number of** tokens created with this creature."
        # (Tetravus.) Not a sweep and not a target: the controller says how
        # many, at resolution (CR 115.1b — nothing is chosen until then), and
        # the sentence after it reads the number back.
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError(
                "the counted exile reads battlefield permanents", node=node
            )
        if not filt.token_only or not filt.created_with_source:
            # Deliberately narrow. The handler resolves the set itself, and the
            # only set it knows how to find is "the tokens this permanent made"
            # — a wider phrase admitted here would be exiled from a list the
            # handler never narrowed.
            raise LoweringError(
                "the counted exile knows only the tokens this permanent created",
                node=node,
            )
        leftovers = _restrictions_beyond(
            filt, frozenset({"token_only", "created_with_source", "zone"})
        )
        if leftovers:
            raise LoweringError(
                f"the counted exile does not honour {leftovers[0]!r}", node=node
            )
        return (OracleInstruction("exile_any_number_of_own_tokens", "", {}),)
    # "Exile it." / "Exile this creature." (Archfiend's Vessel.) The ability's
    # own source, which is not a chosen target at all — nothing is picked, so
    # there is no picker, no legality check and nothing to re-resolve if it has
    # moved. It gets its own instruction kind for that reason rather than a
    # payload flag on the targeted exile: a handler that resolves a target and
    # one that reads ``context.source_permanent`` share no code beyond the move.
    if _is_source(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of the source has no handler", node=node
            )
        return (OracleInstruction("exile_self", "", {}),)
    if (
        not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "target"
        or subject.count != 1
    ):
        # A sweep with no handler and a bare "exile it" are separate effects;
        # only the shapes above are implemented.
        raise LoweringError(
            "only a single chosen permanent or card is exiled", node=node
        )

    filt = subject.filter
    if filt.zone == "graveyard" and filt.is_card:
        if filt.zone_owner is not None or filt.card_types or filt.subtypes or filt.colors:
            # The picker this lowers onto enumerates *any* card in *any*
            # graveyard. Narrowing it is a payload-derived spec, not something
            # to fake by dropping the narrowing here.
            raise LoweringError(
                "no graveyard picker narrows to this card or this player yet",
                node=node,
            )
        return (
            OracleInstruction("exile_target_graveyard_card", "", {"any_card": True}),
        )

    exile_payload = _filter_payload(filt)
    _describe_targets(exile_payload, subject)
    return (OracleInstruction("exile_target_permanent", "", exile_payload),)

def _lower_put_on_library_top(node: ast.PutOnLibraryTop) -> tuple[OracleInstruction, ...]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3.) One chosen battlefield creature; the owner is resolved by
    the handler (CR 400.3), which is why no player rides the payload."""
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier == "any_number"
    ):
        return _lower_graveyard_cards_on_library_top(node)
    if not _is_target(node.target):
        raise LoweringError("the tuck handler resolves one chosen creature", node=node)
    assert isinstance(node.target, ast.TargetSpec)
    filt = node.target.filter
    if filt.card_types != ("creature",) or filt.zone != "battlefield" or filt.is_card:
        raise LoweringError("the tuck handler reads battlefield creatures", node=node)
    payload: dict[str, object] = {}
    _describe_targets(payload, node.target)
    return (OracleInstruction("put_target_on_library_top", "", payload),)


def _lower_exile_until_leaves_or_untaps(
    node: "ast.ExileUntilLeavesOrUntaps",
) -> tuple[OracleInstruction, ...]:
    """Tawnos's Coffin. Everything the sentence says is fixed by the production
    that read it, so the payload carries only the picker's description."""
    payload: dict[str, object] = {"type_filter": "creature"}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("exile_until_leaves_or_untaps", "", payload),)


def _lower_ownership_exchange_unless_paid(
    node: "ast.OwnershipExchangeUnlessPaid",
) -> tuple[OracleInstruction, ...]:
    """Bronze Tablet. The life total and the target's noun phrase are payload;
    every other word was required by the production that read it."""
    from ...subject_filters import object_only_filter

    described = _filter_payload(node.target, carried_separately=frozenset({"owner"}))
    described.pop("owner", None)
    if object_only_filter(described) is None:
        raise LoweringError(
            "the ownership exchange cannot test that phrase", node=node
        )
    payload: dict[str, object] = {
        "life": node.life,
        # The ownership half is carried separately from the rest of the filter:
        # the picker and the handler both ask `subject_matches`, which needs the
        # ability's controller to answer "an opponent owns" at all.
        "owner": node.target.owner,
        "filter": described,
    }
    _describe_targets(
        payload,
        ast.TargetSpec("target", node.target, targeted=True),
        carried_separately=frozenset({"owner"}),
    )
    return (OracleInstruction("exchange_ownership_unless_paid", "", payload),)


def _lower_graveyard_cards_on_library_top(
    node: ast.PutOnLibraryTop,
) -> tuple[OracleInstruction, ...]:
    """"Put any number of target artifact cards from target player's graveyard
    on top of their library in any order." (Drafna's Restoration.)

    A different handler from the tuck above, not a count on it: that one moves
    a *permanent* off the battlefield, and this moves **cards** out of a
    graveyard — different zone, different objects, and a graveyard slot is not
    a battlefield slot (CR 400.1).

    Narrowed to exactly what the handler reads. "Their library" and "its
    owner's library" are the same place here (CR 404.1 puts a card in the
    graveyard of the player who owns it), so no player rides the payload; the
    seat comes from the spell's chosen target player.
    """
    subject = node.target
    assert isinstance(subject, ast.TargetSpec)
    filt = subject.filter
    if not subject.targeted:
        raise LoweringError(
            "the graveyard-to-library handler moves chosen cards", node=node
        )
    if not filt.is_card or filt.zone != "graveyard":
        raise LoweringError(
            "the graveyard-to-library handler reads cards in a graveyard", node=node
        )
    if filt.zone_owner is None or filt.zone_owner.kind != "target_player":
        raise LoweringError(
            "the graveyard-to-library handler reads a chosen player's graveyard",
            node=node,
        )
    if len(filt.card_types) != 1:
        raise LoweringError(
            "the graveyard-to-library handler narrows by one card type", node=node
        )
    leftover = _restrictions_beyond(
        filt, frozenset({"card_types", "is_card", "zone", "zone_owner"})
    )
    if leftover:
        raise LoweringError(
            f"the graveyard-to-library handler does not honour {leftover[0]!r}",
            node=node,
        )
    return (
        OracleInstruction(
            "put_graveyard_cards_on_library_top", "",
            {
                "card_type": filt.card_types[0],
                # "In any order" is the printed rider, and it is the *only*
                # thing that says the controller decides the sequence. Recorded
                # rather than consumed: a card printing it and one not printing
                # it are different cards, and the handler reads the order the
                # targets were named in.
                "in_any_order": node.in_any_order,
                # Unbounded rather than a maximum: "any number" prints no
                # ceiling, so the only cap is how many legal targets there are —
                # a number the picker knows and this lowering does not.
                "targets": {"quantifier": "any_number", "kind": "card", "unbounded": True},
            },
        ),
    )


def _lower_put_onto_battlefield(node: ast.PutOntoBattlefield) -> tuple[OracleInstruction, ...]:
    """The two "put … onto the battlefield" shapes the pool prints:

    * "Put up to seven permanent cards from your hand onto the battlefield."
      (Ugin, the Spirit Dragon's −10) — an up-to-N sweep of the caster's own
      hand, chosen by its controller.
    * "Put target creature card from a graveyard onto the battlefield under
      your control." (Liliana, Waker of the Dead's emblem) — a one-card
      reanimation from any graveyard, with any granted keywords riding along
      ("It gains haste.").
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec):
        raise LoweringError("no handler puts that onto the battlefield", node=node)
    filt = target.filter
    if filt.zone == "hand":
        if filt.zone_owner is None or filt.zone_owner.kind != "you":
            raise LoweringError("only your own hand has a handler here", node=node)
        if target.quantifier != "up_to" or not filt.is_card:
            raise LoweringError("the from-hand handler reads 'up to N … cards'", node=node)
        return (
            OracleInstruction(
                "put_cards_from_hand_onto_battlefield",
                "",
                {
                    "count": target.count,
                    "card_types": list(filt.card_types),
                    # An empty type list with is_card means "permanent cards" —
                    # the handler holds the CR 110.4 list of permanent types.
                    "permanents_only": not filt.card_types,
                },
            ),
        )
    if filt.zone == "graveyard":
        if not _is_target(target) or not filt.is_card:
            raise LoweringError("the reanimation handler reads one chosen card", node=node)
        if filt.card_types != ("creature",):
            raise LoweringError("the reanimation handler only moves creature cards", node=node)
        return (
            OracleInstruction(
                "reanimate_creature",
                "",
                {
                    # "from a graveyard" (no owner) widens the search to every
                    # player's graveyard; "under your control" is CR 400.3's
                    # exception spelled out, honored by the handler.
                    "any_graveyard": filt.zone_owner is None,
                    "under_your_control": node.under_your_control,
                    "gains": list(node.gains),
                },
            ),
        )
    raise LoweringError("no handler for this battlefield entry", node=node)

def _fused_exile_then_controller_life(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Exile target creature. Its controller gains life equal to its power."
    (Swords to Plowshares.)

    Fused because the handler is: it pops the creature off the battlefield and
    reads ``effective_power`` from the object it just removed, which no pair of
    independent instructions can do — the second one would be looking for a
    permanent that is no longer there. Every part of the shape is checked
    against what that handler implements, so a card exiling something else, or
    paying the life to someone else, falls through and is refused by
    :func:`_lower_exile` rather than borrowing this.

    Returning None rather than raising leaves a near miss to be reported
    against the effect it actually failed on.
    """
    if len(steps) != 2:
        return None
    exile, gain = steps
    if not isinstance(exile, ast.Exile) or not isinstance(gain, ast.GainLife):
        return None
    subject = exile.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "target":
        return None
    if subject.filter != _EXILED_CREATURE:
        return None
    if gain.player.kind != "controller":
        return None
    if gain.amount != ast.ThatMuch("its_power"):
        return None
    return (OracleInstruction("exile_creature_gain_life_equal_to_power", "", {}),)


def _lower_shuffle_graveyard_into_library(
    node: ast.ShuffleGraveyardIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Feldon's Cane. Whose graveyard is on the payload even though only one
    value is printed today — the alternative is a kind that would have to be
    replaced the first time a card says "target player's"."""
    return (
        OracleInstruction(
            "shuffle_graveyard_into_library", "", {"whose": node.whose.kind}
        ),
    )


def _lower_shuffle_hand_into_library(
    node: ast.ShuffleHandIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Winds of Change.

    Whose hands move is payload, the way the graveyard shuffle above carries
    whose graveyard does — and the draw rides the same instruction rather than
    following it, because the number it draws is the number this move made.
    Only the two subjects the handler loops over are admitted: "target player"
    would name a seat the handler does not resolve, and a subject it cannot
    resolve is a shuffle taken on the wrong library.
    """
    if node.whose.kind not in ("each_player", "you"):
        raise LoweringError(
            f"no handler shuffles {node.whose.kind!r}'s hand into their library",
            node=node,
        )
    return (
        OracleInstruction(
            "shuffle_hand_into_library",
            "",
            {"whose": node.whose.kind, "then_draw": node.then_draw},
        ),
    )


def _lower_random_reveal_ownership_exchange(
    node: "ast.RandomRevealOwnershipExchange",
) -> tuple[OracleInstruction, ...]:
    """Tempest Efreet. The life total is payload; the target is the printed
    "target opponent", described the way every other player target is so the
    activation picker and the handler ask one question."""
    return (
        OracleInstruction(
            "random_reveal_ownership_exchange", "",
            {
                "life": node.life,
                "targets": {
                    "quantifier": "target",
                    "kind": "player",
                    "opponents_only": True,
                },
            },
        ),
    )
