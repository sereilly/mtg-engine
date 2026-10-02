"""Lowering exile (CR 406): the objects a spell puts *outside* the game state.

Split out of `lowering/zones.py` at the thousand-line guard, the round two
branches both added to it. A family rather than an arbitrary cut, on the same
reasoning the parent file gives for its own split from `board`: exile is the one
zone whose lowering has to decide not just *where* an object goes but whether it
comes back, under what event, and carrying what with it — the until-leaves and
until-untaps forms, and the fused shapes that pair an exile with something done
to its controller. None of that touches the hand/library/battlefield movement
the rest of `zones` reads.

Like its parent it has no twin in `effects/`, and for the same stated reason:
the parse side is one `exile` production in `effects/board.py`, while the work
here is choosing among handlers and refusing the shapes none of them implement.

Three blocks have left since, and the sentence above named the first two before
they did: `linked_exile` took the pile that is already in exile and
`permissions` took what may be cast out of it, so the clause about the
linked-exile record is one this file no longer answers. What is left is the half
that *moves an object into* the zone — and `_bound_exiles` took the half of that
which needs no picker at all, every reading whose object was fixed by an earlier
step or by the firing event before the sentence ran. Everything below chooses
its object out of the game and carries a filter payload to a handler; nothing
below reads a record.
"""

from __future__ import annotations

import dataclasses
from ...oracle_types import OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS, card_only_filter
from .. import ast
from ..errors import LoweringError
from ._bound_exiles import (_entering_counter_payload, lower_pronoun_exile,
                            lower_restated_noun_exile)
from ._events import EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS
from ._piles import _sweep_graveyard_actor
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, _amount_payload,
    _describe_several_targets, _describe_targets, _filter_payload,
    _names_several_targets, _restrictions_beyond, dropped_narrowings,
)


_EXILED_CREATURE = ast.ObjectFilter(card_types=("creature",))

#: Whose graveyard a counted exile may read, by the printed referent's kind.
#: Idiom 2 as a set rather than a fall-through: the handler resolves exactly
#: these, and a referent it cannot name would be dropped and the pile taken
#: from whoever the resolution happened to be carrying.
#: "you" joined it for Midnight Ritual — "Exile X target creature cards from
#: **your** graveyard" — the first printing of this shape whose pile is the
#: caster's own. That is what makes the pick *announceable*: the seat is known
#: when the spell goes on the stack, so ``targeting`` derives a picker for it
#: and the cards are named at CR 601.2c, where the other two piles' are chosen
#: as the ability resolves for the reason stated at the branch below.
_GRAVEYARD_PILE_SEATS = frozenset({"defending_player", "you"})

#: The pile "from **a single** graveyard" names (Ebony Charm): not a seat the
#: sentence prints but one the chooser picks as the spell resolves. It is a
#: *value* of the same payload key rather than a second key, because everything
#: downstream — the candidate rule, the count ceiling, the answer's re-check —
#: is identical once the seat is known; only how the seat is arrived at differs.
#: It is not in the set above for exactly that reason: nothing the parse can
#: read names it, so it cannot arrive by the same route.
_CHOSEN_GRAVEYARD_PILE = "chosen"


def _is_hand_card_exile(subject: "ast.Recipient") -> bool:
    """Whether *subject* is the "a card from your hand" noun phrase.

    Read twice — once by the face-down guard at the top of :func:`_lower_exile`
    and once by the branch that dispatches to
    :func:`_lower_exile_card_from_hand` — so the two cannot disagree about
    which sentence the rider is legal on.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and not subject.targeted
        and subject.filter.zone == "hand"
        and subject.filter.is_card
    )


#: The quantifiers a *pile* out of a hand may be printed with, and what each
#: one means to the handler. "All" (Duplicity) chooses nothing and takes the
#: whole hand; "any number of" (Scroll Rack) is a pick, and zero of them is a
#: legal answer. Two words, one instruction: what the exile does to the pile is
#: identical, and a second kind would be a second place to remember that a pile
#: out of a hand has to be recorded on the exiling permanent.
_HAND_PILE_QUANTIFIERS: dict[str, str] = {"all": "all", "any_number": "any_number"}


def _is_hand_pile_exile(subject: "ast.Recipient") -> bool:
    """Whether *subject* is the "**all** / **any number of** cards from your
    hand" noun phrase — a pile rather than the single card above.

    Beside :func:`_is_hand_card_exile` and read in the same two places, for
    that function's reason: the face-down guard and the dispatch branch cannot
    be allowed to disagree about which sentence CR 406.3's rider is legal on.
    Widening that guard is the whole of what Duplicity needed from this file —
    it had been written when the *only* face-down exile out of a hand was a
    single chosen card.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in _HAND_PILE_QUANTIFIERS
        and not subject.targeted
        and subject.filter.zone == "hand"
        and subject.filter.is_card
    )


def _lower_exile_hand_pile(
    node: ast.Exile, subject: ast.TargetSpec
) -> OracleInstruction:
    """"Exile **all** cards from your hand face down." (Duplicity.)
    "Exile **any number of** cards from your hand face down." (Scroll Rack.)

    One instruction for both quantifiers, because what the exile *does* is the
    same: a run of cards leaves a hand and is recorded on the exiling permanent
    (CR 610.3), which is the only place a face-down exile can be recorded at
    all — two copies of one card in a deck are the same ``CardDefinition``
    object, so nothing on the card can say which of them is hidden.

    The narrowing goes through the same ``card_only_filter`` gate the single
    hand pick uses, for its reason: a *card* phrase is answered by a different
    matcher from a permanent phrase, and a key that matcher cannot test would
    be dropped where it is tested — a sweep wider than the card prints.
    """
    filt = subject.filter
    # Who empties the hand and whose hand it is are **one claim said twice**
    # ("each player exiles all cards from **their** hand", Memory Jar), so they
    # are checked against each other rather than either being read alone — the
    # pairing the graveyard sweep in ``_lower_exile`` already makes of the same
    # two words. A pairing this cannot resolve refuses instead of picking a
    # half: "each player exiles all cards from your hand" is one hand and every
    # player, and there is no such card.
    actor = node.actor.kind if node.actor is not None else None
    owner = filt.zone_owner.kind if filt.zone_owner is not None else None
    if actor is None and owner == "you":
        who = "you"
    elif actor == "each_player" and owner in ("owner", "each_player"):
        who = "each_player"
    else:
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
        raise LoweringError("no hand sweep can test this narrowing", node=node)
    payload: dict[str, object] = {
        "quantifier": _HAND_PILE_QUANTIFIERS[subject.quantifier],
    }
    if who != "you":
        if payload["quantifier"] != "all":
            # "Any number of" is a *pick*, and a pick is owed by the seat that
            # makes it. Nothing in the pool asks every player to make one at
            # once, and the queue would have to hold one prompt per seat with
            # the resolution waiting on all of them — refused rather than
            # silently answered for every seat by the caster.
            raise LoweringError(
                "a per-seat hand exile takes the whole hand, not a pick",
                node=node,
            )
        # Emitted only when the card prints a subject, so Duplicity's and
        # Scroll Rack's payloads stay byte-identical and no behaviour signature
        # moves.
        payload["who"] = who
    if described:
        payload["card_filter"] = described
    if node.face_down:
        payload["face_down"] = True
    return OracleInstruction("exile_hand_pile", "", payload)


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
    # The bare sentence is mandatory; ``lowering/control_flow._offered`` turns
    # this back on for the "you may exile …" printing, which is the only node
    # that knows the offer was made. Written down rather than defaulted,
    # because the prompt's *decline* is the difference between Gustha's Scepter
    # exiling a card and its ability resolving having moved nothing.
    payload: dict[str, object] = {"card_filter": described, "optional": False}
    if node.face_down:
        # CR 406.3. Carried into the payload rather than performed here,
        # because the card is not chosen until the prompt is answered — the
        # linked-exile entry the resolver writes is the only place a
        # face-down exile can be recorded (two copies of one card in a deck
        # are the same ``CardDefinition`` object, so nothing on the card can
        # say which one is hidden).
        payload["face_down"] = True
    return OracleInstruction("exile_chosen_card_from_hand", "", payload)


def _is_graveyard_pile_exile(subject) -> bool:
    """Whether *subject* is the printed noun phrase "all <cards> from a
    graveyard" — the one exile shape that reads a **subject**.

    Beside ``_is_hand_pile_exile`` and for its reason: the branch that performs
    this shape is a long way down the function, and the rider check that has to
    agree with it is at the top. One predicate so the two cannot come apart.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("each", "all")
        and not subject.targeted
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
    )


def _lower_exile(
    node: ast.Exile,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    event_subject: object | None = None,
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
    # CR 406.3's rider is implemented by exactly one branch below — the pick
    # out of a hand, whose resolver writes the linked-exile entry that records
    # it. Refused up here rather than dropped where it is unread: an exile that
    # silently happened face *up* is the loudest kind of quiet wrong, since
    # every player would then be reading a card the card says nobody may see.
    if node.face_down and not (
        _is_hand_card_exile(node.subject) or _is_hand_pile_exile(node.subject)
    ):
        raise LoweringError(
            "only the hand exile carries a face-down rider", node=node
        )
    # The printed subject is read by exactly one branch below — the graveyard
    # sweep, the only shape in the pool that prints one — and refused up here
    # everywhere else, for the rider above's reason exactly. A dropped actor is
    # not a cosmetic loss: every other exile in this file resolves for the
    # ability's own controller, so "each player exiles …" read without its
    # subject would empty one graveyard where the card empties the table's.
    # "**Target spell's controller** exiles it with X delay counters on it."
    # (Ertai's Meddling.) The second shape in this file whose subject is
    # printed, and the one whose subject *is* the target: the announcement
    # chooses an object on the stack (CR 115.1) and the seat that performs the
    # exile is read off it (CR 109.5), so the actor carries no seat of its own
    # to drop.
    #
    # Read before the guard below, which is written about the graveyard sweep
    # and would otherwise refuse this whole sentence. Every part of the clause
    # is checked here rather than dropped, the way each branch in this file
    # states about its own: an exile that lost its counters is a card whose
    # second ability can never fire.
    if node.actor is not None and node.actor.kind == "target_spells_controller":
        subject = node.subject
        if not (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "target"
            and subject.count == 1
            and subject.filter.zone == "stack"
        ):
            raise LoweringError(
                "a spell's controller exiles the one spell the sentence "
                "targeted", node=node,
            )
        if node.duration.kind is not None or node.face_down or node.same_zone:
            raise LoweringError(
                "the targeted-spell exile carries no duration, face-down "
                "rider or pile", node=node,
            )
        leftovers = _restrictions_beyond(subject.filter, frozenset({"zone"}))
        if leftovers:
            raise LoweringError(
                f"the targeted-spell exile does not honour {leftovers[0]!r}",
                node=node,
            )
        payload: dict[str, object] = {
            # The same description the counterspell lowering writes, because it
            # is the same picker: an object on the stack, never a battlefield
            # permanent. Two spellings of it would be two answers to what may be
            # chosen here.
            "targets": {"quantifier": "target", "kind": "spell"},
        }
        if node.counters:
            payload["counters"] = _entering_counter_payload(node.counters)
        return (OracleInstruction("exile_target_spell", "", payload),)
    if node.actor is not None and not (
        _is_graveyard_pile_exile(node.subject) or _is_hand_pile_exile(node.subject)
    ):
        raise LoweringError("no exile handler names a subject", node=node)
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
    restated = lower_restated_noun_exile(node, subject, event, event_subject)
    if restated is not None:
        return restated
    # "Exile **all** / **any number of** cards from your hand face down."
    # (Duplicity, Scroll Rack.) A pile out of a *hidden* zone, read before both
    # sweep branches below — they are about permanents on a battlefield, and
    # each of them refuses a hand outright, which is where these two lines died.
    if _is_hand_pile_exile(subject):
        return (_lower_exile_hand_pile(node, subject),)
    if isinstance(subject, ast.TargetSpec) and subject.quantifier in ("each", "all"):
        # "Exile each permanent with mana value X or less that's one or more
        # colors." (Ugin, the Spirit Dragon's −X.) The payload is hand-rolled:
        # ``to_payload`` cannot carry a *variable* mana-value bound, and
        # dropping the bound would widen the sweep to every mana value.
        filt = subject.filter
        # "Exile **all creature cards from your graveyard**." (Zombie Mob.) A
        # sweep over a pile of *cards* rather than over the battlefield, so it
        # is its own instruction: CR 613.1 gives a card in a graveyard no
        # computed characteristics at all, and the battlefield sweep below
        # matches with ``subject_matches``, which asks a permanent questions a
        # card cannot answer.
        #
        # The payer's own pile and no other, because that is what the pool
        # prints and because "a graveyard" would need the handler to say which.
        # Everything the phrase narrows by is carried through
        # ``card_only_filter``, the reader a discard cost and a graveyard
        # target already share — a narrowing it cannot answer refuses the line
        # rather than exiling a wider set than the card names.
        if filt.zone == "graveyard" and filt.is_card:
            # Who empties the pile and whose pile it is are **one claim said
            # twice** ("each player … from *their* graveyard"), so they are
            # checked against each other rather than either being read alone —
            # the pairing `_described_returns`' sweep reanimation already makes
            # of the same two words. A pairing this cannot resolve refuses
            # instead
            # of picking a half: "each player exiles all creature cards from
            # your graveyard" is one graveyard and every player, and there is
            # no such card.
            #
            # Asked of ``_piles._sweep_graveyard_actor``, which is where that
            # pairing lives for both families rather than once per family. It
            # was open-coded here, and the copy was missing a row the original
            # had: "from **all graveyards**" — no printed subject, every pile on
            # the table — which is the same set of piles "each player … their
            # graveyard" names and which Planar Birth's *return* sweep has read
            # since it was written. So "exile all creature cards from all
            # graveyards" refused while the identical return lowered, for no
            # reason either sentence prints.
            graveyard_owner = _sweep_graveyard_actor(node, subject)
            if graveyard_owner is None:
                raise LoweringError(
                    "the graveyard exile sweep reads your own pile, "
                    "\"each player … their graveyard\", or \"all graveyards\"",
                    node=node,
                )
            if node.counters:
                raise LoweringError(
                    "a graveyard exile sweep carries no counters", node=node
                )
            default = ast.ObjectFilter()
            described = card_only_filter(
                dataclasses.replace(
                    filt, zone=default.zone, zone_owner=default.zone_owner,
                ).to_payload()
            )
            if described is None:
                raise LoweringError(
                    "the graveyard exile sweep cannot test this restriction on "
                    "a card in a zone",
                    node=node,
                )
            return (
                OracleInstruction(
                    "exile_graveyard_cards", "",
                    {"graveyard_owner": graveyard_owner, "filter": described},
                ),
            )
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
        # ``blocked_by_source`` is named here rather than in
        # ``_PAYLOAD_HONOURED_FILTER_FIELDS``, which is the idiom
        # ``lowering/_filters.py`` states for a relation only some lowerings can
        # carry: ``to_payload`` emits the key and ``subject_matches`` answers
        # it, but only with the ability's **source** in hand — so the lowering
        # that admits it is the one whose handler has one. "Exile all creatures
        # blocked by this creature" (Wall of Nets) is that sentence, and the
        # sweep handler reads its narrowings through ``subject_matches`` with
        # ``context.source_permanent`` for exactly this key's sake. Admitted
        # into the general set instead, every lowering in the package would
        # carry a relation most of their handlers test with the pure matcher,
        # which drops it — and a dropped ``blocked_by_source`` on a sweep is
        # every creature on the table.
        leftovers = _restrictions_beyond(
            rest, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone", "blocked_by_source"}
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
    pronoun = lower_pronoun_exile(node, subject, produced, event)
    if pronoun is not None:
        return pronoun
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
        # "…from **a single** graveyard" (Ebony Charm). The pile is anybody's
        # and the *chooser* names it, which is why the sameness cannot be read
        # off the filter: the filter is asked of one card at a time and this is
        # a restriction on the whole set. It arrives on the node from the parse
        # for that reason, and only where the sentence printed no owner —
        # "…from **defending player's** graveyard **from a single graveyard**"
        # is not a sentence, and admitting both would be two answers to which
        # pile.
        if node.same_zone:
            if owner is not None:
                raise LoweringError(
                    "a single graveyard is the one the chooser names, not a "
                    "printed seat", node=node,
                )
            pile_owner = _CHOSEN_GRAVEYARD_PILE
        elif owner is None or owner.kind not in _GRAVEYARD_PILE_SEATS:
            raise LoweringError(
                "the counted graveyard exile reads one named player's pile",
                node=node,
            )
        else:
            pile_owner = owner.kind
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
            # "Exile **X** target creature cards" (Midnight Ritual). The
            # announced X (CR 601.2b), which is not a number until the spell is
            # on the stack — so it travels as the letter and the handler turns
            # it into one, the arrangement the graveyard *return* already has
            # for Shattered Crypt. Written as ``int(subject.count)``, every X
            # would have arrived as a 0 and the spell would exile nothing.
            "count": "x" if subject.count_from_x else int(subject.count),
            "graveyard_owner": pile_owner,
            # "**up to** two" is a ceiling, and the difference is the whole of
            # what the seat is being asked: a fixed count would make a pile of
            # one card an unanswerable prompt.
            "up_to": subject.quantifier == "up_to",
        }
        if filt.card_types:
            pile["card_type"] = filt.card_types[0]
        else:
            # "Exile up to three target **cards** from a single graveyard."
            # (Ebony Charm's third mode, Rapid Decay.) The unnarrowed phrase,
            # said out loud: ``graveyard_card_matches`` reads an absent
            # ``card_type`` as *creature* — the reanimation Auras' default,
            # since their enchant clause carries no type of its own — so a
            # payload that simply left the key off narrowed a sentence that
            # narrows nothing. Ebony Charm has shipped that way: its third mode
            # offered only creature cards, and against a graveyard of lands and
            # spells reported "no graveyard holds a card it can exile" and
            # exiled nothing at all.
            pile["any_card"] = True
        if pile_owner == "you":
            # The target description, for the one pile whose seat is known at
            # announcement. ``targeting._graveyard_exile_pile_spec`` derives the
            # picker from it and the handler resolves the announced slots. The
            # other two piles carry no description and keep their resolution
            # prompt, so every payload written before this is byte-identical.
            pile["targets"] = {
                "quantifier": subject.quantifier,
                "kind": "card",
                "count": "x" if subject.count_from_x else int(subject.count),
            }
        return (OracleInstruction("exile_cards_from_graveyard", "", pile),)
    # "…**with two delay counters on it**." (Ertai's Meddling.) CR 121.1's
    # counters put on the card as it arrives in exile, which only ``exile_self``
    # performs — it is the one exile that keeps a record for them to sit on
    # (``engine/exiled_records.py``). Every shape below moves a chosen object
    # and keeps no record, so the phrase would be parsed and dropped: the
    # ``Exile`` node carries it (``readers._parse_entering_counters``) and none
    # of the three returns below reads it.
    #
    # Refused rather than ignored, which is the four sibling branches' rule in
    # this same function and the reason each of them states: a card exiled
    # *without* the counters it prints is a card whose second ability can never
    # fire, and nothing downstream would say so. No card in the pool reaches
    # this yet; the first one that does gets a refusal naming the clause instead
    # of a silent half-effect.
    if node.counters:
        raise LoweringError(
            "only a self-exile records the counters a card enters exile with",
            node=node,
        )
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
    if _is_hand_card_exile(subject):
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


def _lower_exile_graveyard_arrivals_this_turn(
    node: ast.ExileGraveyardArrivalsThisTurn,
) -> tuple[OracleInstruction, ...]:
    """"If a card would be put into your graveyard from anywhere this turn,
    exile that card instead." (Yawgmoth's Will.)

    CR 614 for a window rather than for as long as a permanent is on the
    battlefield, so what the effect leaves behind is a per-seat record the
    interceptor reads — the same shape Disintegrate's "if it would die this
    turn, exile it instead" already has, one object wider: a marker a handler
    stamps and a pure predicate asks.

    Only the caster's own graveyard. "An opponent's" and "a" are printed on
    permanents (Leyline of the Void, Rest in Peace) whose static reading
    already implements them, and no card in the pool creates either from an
    effect — so admitting them here would arm a record the interceptor's
    seat comparison has no answer for, which is a replacement applying to the
    wrong pile rather than to none.
    """
    if node.whose != "you":
        raise LoweringError(
            "an effect arms this replacement over its own controller's "
            f"graveyard, not {node.whose!r}'s",
            node=node,
        )
    return (
        OracleInstruction("exile_graveyard_arrivals_this_turn", "", {}),
    )


def _lower_each_player_claims_exiled_card(
    node: "ast.EachPlayerClaimsExiledCard", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Exile all nontoken permanents. **Starting with you, each player chooses
    one of the exiled cards and puts it onto the battlefield tapped under their
    control.**" (Thieves' Auction.)

    One instruction, and the repeat clause behind the sentence is a key on it
    rather than a wrapper around it — ``_lower_repeat_process``'s argument one
    card over: the loop ends when the pile empties, which is something only the
    thing handing out the cards can see, and a round that emptied it part-way
    has to stop mid-round rather than after it.

    Refused without a producer, as every back-reference in this grammar is: "the
    exiled cards" names what a step of *this same effect* exiled, and with no
    such step the words name nothing — a spell that reports supported and hands
    out nothing at all.

    ``until_pile_empty`` is carried even when it is False, because the two
    readings are genuinely different cards: without the clause each seat takes
    exactly one card and the rest stay exiled.
    """
    if EXILED_THIS_WAY_OBJECTS not in produced:
        raise LoweringError(
            "'one of the exiled cards' names what an earlier step of this "
            "effect exiled, and no step of it exiles anything", node=node,
        )
    if node.chooser.kind != "each_player":
        raise LoweringError(
            "a pick out of the exiled pile is made by every seat in turn",
            node=node,
        )
    return (
        OracleInstruction(
            "claim_exiled_cards_in_turn", "",
            {
                # "Starting with you" — CR 101.4 orders a multi-seat decision
                # from the active player and this names the seat that put the
                # effect on the stack. The same seat for a sorcery, not the
                # same rule, which is why the word is carried.
                "claim_order": (
                    node.starting_with.kind if node.starting_with else None
                ),
                "tapped": node.tapped,
                "until_pile_empty": node.until_pile_empty,
            },
        ),
    )


def _lower_exile_cards_from_hand(
    node: "ast.ExileCardsFromHand", event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"Each player exiles two cards from their hand." (Mind Swords.)

    A pick out of a hidden zone, so each seat makes its own (CR 400.2) in turn
    order (CR 101.4) and the handler arms one prompt per card. The seat and the
    hand are honoured by construction — the actor's own hand is the only one the
    handler reads — and every other key of the phrase must survive
    ``card_only_filter``, because a card in hand has no computed
    characteristics (CR 613.1) and a narrowing only a permanent could answer
    would be dropped by the prompt.

    Every refusal below is a way the sentence could otherwise mean more than it
    says: a seat word the handler does not walk, and a count it cannot name
    before the prompt is armed.
    """
    actor = node.player.kind
    if actor not in ("each_player", "each_opponent"):
        raise LoweringError(
            f"no handler has {actor!r} exile cards from their hand", node=node
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count < 1:
        raise LoweringError("the hand exile names a printed number", node=node)
    leftover = _restrictions_beyond(
        node.filter,
        _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"},
    )
    if leftover:
        raise LoweringError(
            f"the hand exile does not honour {leftover[0]!r}", node=node
        )
    narrowing = node.filter.to_payload()
    narrowing.pop("zone", None)
    narrowing.pop("zone_owner", None)
    described = card_only_filter(narrowing)
    if described is None:
        raise LoweringError("no hand pick can test this narrowing", node=node)
    return (
        OracleInstruction(
            "exile_cards_from_hand", "",
            {"actor": actor, "amount": count, "card_filter": described},
        ),
    )
