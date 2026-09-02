"""Lowering exile (CR 406): the objects a spell puts *outside* the game state.

Split out of `lowering/zones.py` at the thousand-line guard, the round two
branches both added to it. A family rather than an arbitrary cut, on the same
reasoning the parent file gives for its own split from `board`: exile is the one
zone whose lowering has to decide not just *where* an object goes but whether it
comes back, under what event, and carrying what with it — the linked-exile
record (`engine/linked_exile.py`), the until-leaves and until-untaps forms, and
the fused shapes that pair an exile with something done to its controller. None
of that touches the hand/library/battlefield movement the rest of `zones` reads.

Like its parent it has no twin in `effects/`, and for the same stated reason:
the parse side is one `exile` production in `effects/board.py`, while the work
here is choosing among handlers and refusing the shapes none of them implement.
"""

from __future__ import annotations

import dataclasses
from ...oracle_types import OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS, card_only_filter
from .. import ast
from ..errors import LoweringError
from ._events import CREATED_TOKEN, EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, _describe_several_targets, _describe_targets,
    _filter_payload, _is_created_token, _is_source, _names_several_targets,
    _restrictions_beyond, dropped_narrowings,
)


_EXILED_CREATURE = ast.ObjectFilter(card_types=("creature",))

#: Whose graveyard a counted exile may read, by the printed referent's kind.
#: Idiom 2 as a set rather than a fall-through: the handler resolves exactly
#: these, and a referent it cannot name would be dropped and the pile taken
#: from whoever the resolution happened to be carrying.
_GRAVEYARD_PILE_SEATS = frozenset({"defending_player"})


def _lower_exile_card_from_hand(
    node: ast.Exile, subject: ast.TargetSpec
) -> OracleInstruction:
    """"You may exile a nonland card from your hand." (Ice Cauldron.)

    The narrowing is read through ``chargeable_card_filter``'s sibling gate the
    hand pick beside it uses (``lowering/cards.py``'s "choose N cards in your
    hand"), for that function's reason: a *card* phrase is answered by a
    different matcher from a permanent phrase, and a key that matcher cannot
    test would be dropped where it is tested — an exile wider than the card
    prints.
    """
    filt = subject.filter
    if filt.zone_owner is None or filt.zone_owner.kind != "you":
        raise LoweringError("the hand exile reads your own hand", node=node)
    if node.duration.kind is not None or node.counters:
        raise LoweringError(
            "a hand exile carries no duration or counters yet", node=node
        )
    leftover = _restrictions_beyond(
        filt,
        _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"},
    )
    if leftover:
        raise LoweringError(
            f"the hand exile does not honour {leftover[0]!r}", node=node
        )
    payload_filter = filt.to_payload()
    payload_filter.pop("zone", None)
    payload_filter.pop("zone_owner", None)
    described = card_only_filter(payload_filter)
    if described is None:
        raise LoweringError("no hand pick can test this narrowing", node=node)
    return OracleInstruction(
        "exile_chosen_card_from_hand", "", {"card_filter": described}
    )


def _lower_exile(
    node: ast.Exile,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
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
    # "When **the creature** dies this turn, exile **the creature**."
    # (Whippoorwill.) Idiom 20's pronoun, inside a delayed ability that bound
    # an object: the words name the creature the *creating* ability targeted,
    # not the ability's own source (CR 603.7d makes the source the Whippoorwill
    # and the sentence is not about it). By the time this fires that creature
    # is a card in a graveyard, so what is exiled is the card — which is why it
    # is its own kind rather than a payload flag on ``exile_self``: one handler
    # moves a permanent off a battlefield and the other moves a card out of a
    # pile, and they share nothing.
    #
    # Read above the source branch below, which cannot tell the two apart: the
    # noun parser collapses "the creature" onto the same bare-pronoun spec "it"
    # produces (quantifier ``it``, ``is_source``), where a card naming itself
    # ("this creature", Archfiend's Vessel) parses to quantifier ``this``. That
    # collapse is why Whippoorwill exiled **itself** whenever its target died —
    # supported, tested by nothing, and invisible to every census in the repo.
    #
    # ``bound_permanent_dies`` alone, not every bound-object delay: it is the
    # one whose fire site records the dead card. Under a leaves-the-battlefield
    # or end-of-combat delay the object may still be on a battlefield, which is
    # a different move and a different handler.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and _is_source(subject)
        and event == "bound_permanent_dies"
    ):
        if node.duration.kind is not None or node.counters:
            raise LoweringError(
                "a bound card's exile carries no duration or counters", node=node
            )
        return (OracleInstruction("exile_bound_card", "", {}),)
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
        # "…**with two scream counters on it**" (All Hallow's Eve). Payload, so
        # the counter word and the number never reach an instruction *kind*;
        # the handler registers the exiled card with them
        # (``engine/exiled_records.py``) and the card's own upkeep trigger
        # reads them back off the register.
        payload: dict = {}
        if node.counters:
            payload["counters"] = {name: count for name, count in node.counters}
        return (OracleInstruction("exile_self", "", payload),)
    # "Exile **that token**…" (Stangg). The token this same effect created,
    # addressed by the id the token maker wrote to the scratchpad — not a
    # chosen target and not the source, so it gets its own kind for the reason
    # ``exile_self`` has one: a handler that reads a recorded id and one that
    # resolves a target share nothing beyond the move.
    #
    # ``produced`` is the whole gate. With no token maker in front of it there
    # is no id to read, and an exile that silently found nothing would be a
    # card that reports itself supported and does nothing.
    if _is_created_token(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of a created token has no handler", node=node
            )
        if CREATED_TOKEN not in produced:
            raise LoweringError(
                "back-reference to a created token with no token maker in "
                "this effect",
                node=node,
            )
        return (OracleInstruction("exile_created_token", "", {}),)
    # "Exile **the token**." (Dance of Many.) The same object one reach
    # further out: the token this *permanent* created, rather than the token
    # this *resolution* created. Dance of Many prints the sentence as an
    # ability of its own, so by the time it fires the scratchpad the branch
    # above reads is long gone — what survives is the record the token maker
    # stamped on the token, which is why this is a payload variant of that
    # kind and not a second kind. There is no `produced` gate for the same
    # reason: the token maker is a different line of the same card, and a
    # permanent that made no token has nothing to exile, which is CR 608.2b.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.filter.created_with_source
        and subject.filter.token_only
        and subject.quantifier == "that"
    ):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of a created token has no handler", node=node
            )
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"token_only", "created_with_source", "zone"})
        )
        if leftovers:
            raise LoweringError(
                f"the created-token exile does not honour {leftovers[0]!r}",
                node=node,
            )
        return (
            OracleInstruction(
                "exile_created_token", "", {"created_with_source": True}
            ),
        )
    # "You may exile **up to two target creature cards from defending player's
    # graveyard**." (Rysorian Badger.) Several cards out of one named pile,
    # which is neither of the two shapes around it: the several-target branch
    # below resolves a list of *permanents*, and the single-card graveyard
    # branch further down reads one card out of whichever pile it finds.
    #
    # A prompt rather than an announced list of targets, and that is a stated
    # deviation rather than an oversight: this engine chooses a triggered
    # ability's targets at resolution (see ROADMAP's CR 608.2b entry — the
    # death sweep's mis-targeting is the reason 603.3d's announcement is not
    # asked of a trigger), and there is no picker in the pool that names two
    # cards in one graveyard. The seat picks as the ability resolves, which is
    # a decision made later than CR 603.3d puts it and by the same player over
    # the same set.
    #
    # Read above the several-target branch, which refuses every non-battlefield
    # phrase outright, and gated on every part of the sentence: which pile,
    # how many, and what kind of card. A dropped narrowing here is a card
    # exiling more, or from somewhere else, than it says.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and subject.filter.zone == "graveyard"
        and subject.filter.is_card
    ):
        filt = subject.filter
        owner = filt.zone_owner
        if owner is None or owner.kind not in _GRAVEYARD_PILE_SEATS:
            raise LoweringError(
                "the counted graveyard exile reads one named player's pile",
                node=node,
            )
        if len(filt.card_types) > 1:
            # A union ("artifact or creature card") is a second shape the
            # prompt's candidate rule would have to learn; until a card prints
            # one it refuses rather than collapsing to the first type.
            raise LoweringError(
                "no graveyard pick reads a union of card types yet", node=node
            )
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "zone", "zone_owner", "is_card"})
        )
        if leftover:
            raise LoweringError(
                f"the counted graveyard exile does not honour {leftover[0]!r}",
                node=node,
            )
        if node.counters:
            raise LoweringError(
                "a counted graveyard exile carries no counters", node=node
            )
        pile: dict[str, object] = {
            "count": int(subject.count),
            "graveyard_owner": owner.kind,
            # "**up to** two" is a ceiling, and the difference is the whole of
            # what the seat is being asked: a fixed count would make a pile of
            # one card an unanswerable prompt.
            "up_to": subject.quantifier == "up_to",
        }
        if filt.card_types:
            pile["card_type"] = filt.card_types[0]
        return (OracleInstruction("exile_cards_from_graveyard", "", pile),)
    # "Exile **two target** nonartifact creatures." (Ashes to Ashes; Dust to
    # Dust prints the same over artifacts.) One announcement collecting several
    # targets, resolved as a list — so it is the same instruction with the
    # several-targets description, not a second kind, exactly as the damage
    # lowering treats Volcanic Salvo. A lowering that dropped ``count`` would
    # exile one of the two and report the card supported.
    #
    # Opted into rather than admitted by the single-target check below, which is
    # the safety `_describe_several_targets` exists for: a handler that resolves
    # one permanent must never be handed a two-target picker. The isinstance is
    # part of the condition rather than an assert behind it, because a non-target
    # subject reaching here is a parse this lowering simply does not read.
    if isinstance(subject, ast.TargetSpec) and _names_several_targets(subject):
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            # Everything below this branch that reads another zone reaches a
            # *card* picker; the list resolver is over permanents, so a
            # graveyard or hand phrase would be collected and then looked for on
            # the battlefield.
            raise LoweringError(
                "only battlefield permanents are exiled several at a time",
                node=node,
            )
        several: dict[str, object] = _filter_payload(filt)
        _describe_several_targets(several, subject)
        return (OracleInstruction("exile_target_permanent", "", several),)
    # "You may exile **a nonland card from your hand**." (Ice Cauldron.) Not a
    # target and not a permanent: the card is chosen on resolution (CR 601.2c
    # names nothing) out of a hidden zone, so the pick is the effect and it is
    # a prompt. Read before the single-target gate below, which is about
    # battlefield permanents and graveyard cards and would refuse this outright.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and not subject.targeted
        and subject.filter.zone == "hand"
        and subject.filter.is_card
    ):
        return (_lower_exile_card_from_hand(node, subject),)
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
        if filt.zone_owner is not None or filt.subtypes or filt.colors:
            # The picker this lowers onto enumerates every graveyard. Whose pile
            # it may read, and a subtype or colour narrowing, are still shapes
            # nothing behind it tests — dropped here they would offer a card the
            # printed line forbids, so they refuse (idiom 2).
            raise LoweringError(
                "no graveyard picker narrows to this card or this player yet",
                node=node,
            )
        if len(filt.card_types) > 1:
            # A *union* ("target artifact or creature card") is a second key
            # shape the picker and the re-check would each have to learn; until
            # a card in the pool prints one from a graveyard it refuses rather
            # than collapsing to the first type.
            raise LoweringError(
                "no graveyard picker reads a union of card types yet", node=node
            )
        if _restrictions_beyond(
            filt, frozenset({"card_types", "zone", "is_card"})
        ):
            raise LoweringError(
                "no graveyard picker narrows to this card or this player yet",
                node=node,
            )
        if filt.card_types:
            # "Exile target **artifact** card from a graveyard." (Grave
            # Robbers.) / "…target **creature** card…" (Eater of the Dead.) The
            # named type is carried, never collapsed: ``card_type`` is the key
            # ``graveyard_card_matches`` tests by containment in the printed
            # type line (CR 205.2, idiom 15), so an artifact creature answers
            # both spellings, and one predicate serves the picker, the
            # activation re-check and the handler.
            return (
                OracleInstruction(
                    "exile_target_graveyard_card",
                    "",
                    {"any_card": False, "card_type": filt.card_types[0]},
                ),
            )
        return (
            OracleInstruction("exile_target_graveyard_card", "", {"any_card": True}),
        )

    exile_payload = _filter_payload(filt)
    _describe_targets(exile_payload, subject)
    return (OracleInstruction("exile_target_permanent", "", exile_payload),)


def _lower_for_each_exiled(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each creature exiled this way,** <effect>." (Martyr's Cry.)

    The exile family's twin of ``_lower_for_each_destroyed``, here rather than
    beside it for the reason this module exists at all: the set it walks is the
    one ``exile_all_matching`` recorded, and nothing about a destruction
    describes it.

    Refused without a producer, as every back-reference in this grammar is: with
    no earlier step that exiled anything the words name nothing, and an empty
    loop is a sentence that reports supported and does not run.
    """
    if EXILED_THIS_WAY not in produced:
        raise LoweringError(
            "'exiled this way' with no earlier step in this effect that "
            "exiled anything", node=node,
        )
    filt = node.iterator.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "'exiled this way' iterates what the earlier step exiled and "
            "cannot be narrowed further", node=node,
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"produced_by": EXILED_THIS_WAY_OBJECTS}, "effect": inner},
        ),
    )


def _lower_exile_until_leaves_or_untaps(
    node: "ast.ExileUntilLeavesOrUntaps",
) -> tuple[OracleInstruction, ...]:
    """Tawnos's Coffin. Everything the sentence says is fixed by the production
    that read it, so the payload carries only the picker's description."""
    payload: dict[str, object] = {"type_filter": "creature"}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("exile_until_leaves_or_untaps", "", payload),)


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


def _lower_exile_cost_sacrifices(
    node: ast.ExileCostSacrifices,
) -> tuple[OracleInstruction, ...]:
    """"…, then exile this artifact and those creature cards." (Sword of the
    Ages.)

    No payload: what to exile is exactly what the ability's cost sacrificed,
    which only the activation that charged it knows (CR 601.2h) and which it
    records. A filter here would be a second opinion about a set already
    decided.
    """
    return (OracleInstruction("exile_cost_sacrifices", "", {}),)
