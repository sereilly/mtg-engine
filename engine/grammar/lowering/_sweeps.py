"""Damage over a set the sentence **describes** rather than chooses.

CR 611.2c's set: nothing is targeted, nobody picks, and every permanent the
printed noun phrase names is dealt to — fixed when the effect begins. That is a
different question from CR 115's targeting, and it is the one question this
module answers.

A **floor**, not a family, for ``_amounts``' reason exactly: ``damage.py``
imports it and it imports nothing back, and inside ``lowering/`` a module a
family reads cannot itself be one.

Split out when ``lowering/damage.py`` reached the thousand-line guard, and the
split is what made the shape one shape again. It was *already* half-exiled:
``_lower_described_set_damage`` sat in ``_common`` — the module every family
reads, for payload shapes and small values — with a comment saying it was there
because ``damage.py`` was full, while the ``each`` spelling of the same clause
stayed inline in ``damage.py``. So one printed idiom had two lowerings in two
files, and they had already drifted: the inline one checked the head noun and
then *stripped* it, which is why Pyroclasm dealt its 2 to every land on the
table (see :func:`lower_each_matching_damage`).

:func:`_sweep_kind` followed at Mirage's second-wave integration, when
``damage.py`` reached the guard again with no branch at fault. It was the last
of the half-exile: two docstrings here already named it as the thing consulted
*before* the payload-carrying sweep below, and the module that documents a
decision is the module that should hold it. It is the same question this file
answers — which printed recipient set is one batch — asked of the three sets
that earned a fused kind of their own.

:func:`lower_counter_sweep` followed at Visions' first wave, when
``lowering/counters.py`` reached the guard. It is the same question again asked
of a *counter* instead of damage — "put a +1/+1 counter on **each** creature you
control" describes its set exactly as "deals 2 damage to each creature" does,
nothing is targeted and nobody picks — so it lands here under the family name
the mirror already carries rather than forking a third home for one printed
idiom. Public rather than module-private now that it crosses a module line;
``counters.py`` is still its only caller.

:func:`lower_exile_sweep` followed at Prophecy's second wave, when
``lowering/exile.py`` sat thirty lines under the guard with Dual Nature's two
"exile all tokens …" sentences to land. The same question a third time, asked
of CR 406's keyword action: "exile all Sand Warriors" picks nothing and names
nobody, and the exile family keeps every reading that does.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS, card_only_filter
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, dropped_narrowings,
    _restrictions_beyond,
    _filter_payload, refuse_untestable,
                      testable_filter_payload)
from ._events import EVENT_SUBJECT_NAMES
from ._piles import _sweep_graveyard_actor


def describes_a_swept_set(node: ast.DealDamage) -> bool:
    """Whether *node*'s recipients are one described set rather than a choice.

    One definition, asked twice: by the gate that refuses a per-recipient
    multiplier on any other shape, and by the branch that honours one. Two
    spellings of "is this the sweep?" is how a gate and its dispatch come to
    disagree, which for a multiplier means a rider refused in one place and
    dropped in the other.
    """
    return (
        len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.TargetSpec)
        and node.recipients[0].quantifier == "each"
        and not node.recipients[0].targeted
    )


def refuse_unswept_multiplier(node: ast.DealDamage) -> None:
    """Refuse "…for each <objects>" on a damage clause that cannot apply it.

    The multiplier is a rider on the printed amount, and a rider reaching a
    branch that does not read it is *dropped* — here that is Baki's Curse
    dealing a flat 2 to the whole board while reporting itself supported, which
    is the one outcome this engine ranks below being unsupported. Only the
    described-set sweep multiplies per recipient, so every other shape refuses
    at the top of the lowering rather than each branch remembering to.
    """
    if node.per_each is not None and not describes_a_swept_set(node):
        raise LoweringError(
            "no damage handler multiplies this clause per recipient", node=node
        )


def _per_recipient_multiplier(node: ast.DealDamage) -> dict:
    """"…for each **Aura attached to that creature**." (Baki's Curse.)

    A count taken once per member of the swept set, so it travels on its own
    payload key rather than as an ``x_from_count``: that key holds **one**
    number for the whole resolution, and a per-recipient multiplier folded into
    it would deal every creature the count taken off whichever one was read
    first — five creatures, one Aura between them, ten damage each.

    "That creature" is the recipient. The noun parser records the referent as
    ``target``, because a back-reference to the sentence's object is normally a
    target; a described set is the one shape where that object is *many*, and
    the handler resolves the relation against each of them in turn. It is
    rewritten to ``source`` on the way into ``count_spec`` because that is
    ``evaluate_count``'s own name for "the permanent this spec's relations
    resolve against" — and the handler passes the struck permanent as exactly
    that. Rewritten rather than given a fourth referent word, so the evaluator
    keeps one vocabulary and ``count_spec`` needs no branch.

    Only an attachment count is admitted. A phrase naming any other set would
    be counted once for the whole sweep, off a spec whose owner scope this
    strips — a number with no relation to the recipient at all.
    """
    filt = node.per_each
    if filt.attached_to != "target":
        raise LoweringError(
            "no damage handler counts this set per recipient", node=node
        )
    spec = count_spec(dataclasses.replace(filt, attached_to="source"), node)
    # The owner scope is dead on an attachment count — ``evaluate_count`` reads
    # the record kept on the permanent rather than scanning a battlefield — and
    # leaving it saying "you" would state a claim the card does not make: an
    # opponent's Aura on your creature is attached to your creature.
    spec.pop("owner", None)
    return spec


def lower_each_matching_damage(
    node: ast.DealDamage,
    recipient: ast.TargetSpec,
    amount,
    computed: bool,
) -> tuple[OracleInstruction, ...]:
    """"…deals 2 damage to **each creature you control**" (Sorrow's Path),
    "…to **each creature**" (Pyroclasm), "…to each creature **for each Aura
    attached to that creature**" (Baki's Curse).

    A creature sweep narrowed by a printed noun phrase, which is what
    ``_sweep_kind``'s three fused kinds each are with the narrowing baked into
    the kind's name. Here the narrowing is payload, so a card printing a
    different one needs no code — and the fused kinds keep their cards because
    ``_sweep_kind`` is consulted first.

    Creatures only, checked rather than assumed: CR 120.1a says damage cannot be
    dealt to an object that is not a battle, a creature or a planeswalker, so a
    sweep written over "each permanent" would mark damage nothing could ever
    read.

    **And the word stays in the payload.** It used to be checked here and then
    stripped, while ``deal_damage_each_matching`` walks ``all_permanents()`` and
    asks only what the payload says — so Pyroclasm dealt its 2 to every Mountain
    on the table and Sorrow's Path to every permanent its controller had.
    Nothing failed, because CR 704.5g only buries a *creature* with lethal
    damage; the damage simply sat unread. It still stamped the "was dealt damage
    this turn" record a printed noun phrase can test (Giant Shark) and still
    spent any prevention shield the land carried. The gate and the sweep were
    reading two different clauses, which is the shape this file exists to keep
    to one.
    """
    if recipient.filter.card_types != ("creature",):
        raise LoweringError(
            "only a creature sweep is damaged by the printed noun phrase",
            node=node,
        )
    if computed:
        raise LoweringError(
            "a creature sweep cannot carry a computed damage amount", node=node
        )
    # Idiom 2: a restriction the matcher cannot test is one the handler would
    # silently ignore, which widens the sweep rather than narrowing it — every
    # creature on the board instead of the printed set.
    described = testable_filter_payload(
        recipient.filter,
        refusal="the creature sweep cannot test this restriction",
        node=node,
        require_narrowing=False,
    )
    payload: dict[str, object] = {"amount": amount, "filter": described}
    if node.per_each is not None:
        payload["per_recipient_count"] = _per_recipient_multiplier(node)
    return (OracleInstruction("deal_damage_each_matching", "", payload),)


def lower_counted_sweep_damage(
    node: ast.DealDamage, recipient: ast.TargetSpec, *, multiplier: int = 1
) -> tuple[OracleInstruction, ...]:
    """"…it deals damage to **each nonblue creature without flying** equal to
    half the number of Islands you control, rounded down." (Floodgate.)

    The two sweeps above with a *counted* amount instead of a printed one. Both
    of them refuse one outright ("a creature sweep cannot carry a computed
    damage amount"), and that refusal was about the amount reaching the handler:
    they emit ``amount`` as a literal and ``deal_damage_each_matching`` resolves
    it against ``context.x_value``.

    Which is exactly the channel a count already travels on.
    ``X_FROM_COUNT`` is evaluated at the single dispatch point
    (``mixins/oracle_instructions``) and substituted into the context's X
    *before* any handler runs, so a sweep asking for ``"x"`` gets the number the
    same way every counted single-recipient damage does — one number for the
    whole resolution, which is what CR 611.2c's fixed set wants.

    The set's own refusals are the two sweeps' unchanged: creatures only
    (CR 120.1a — damage marked on anything else is never read), and every key of
    the printed noun phrase testable by ``subject_matches``, because a narrowing
    the matcher drops burns a strictly larger board than the card prints.
    """
    assert isinstance(node.amount, ast.CountOf)
    if node.per_each is not None or node.riders != ast.DamageRiders():
        raise LoweringError(
            "a counted sweep carries no multiplier and no riders", node=node
        )
    if recipient.filter.card_types != ("creature",):
        raise LoweringError(
            "only a creature sweep is damaged by the printed noun phrase",
            node=node,
        )
    described = testable_filter_payload(
        recipient.filter,
        refusal="the damage sweep cannot narrow by",
        node=node,
        require_narrowing=False,
    )
    from ...oracle_types import X_FROM_COUNT

    return (
        OracleInstruction(
            "deal_damage_each_matching", "",
            {
                "amount": "x",
                "filter": described,
                X_FROM_COUNT: count_spec(
                    node.amount.filter, node, multiplier=multiplier
                ),
            },
        ),
    )


def lower_described_set_damage(
    node, recipient, amount, computed: bool
) -> tuple[OracleInstruction, ...]:
    """"…deals 1 damage to each **Goblin** creature." (Goblin Shrine.)

    The same set as :func:`lower_each_matching_damage` reached by the other
    quantifier — "all" as well as "each" — and with no head-noun requirement,
    which is the one thing that keeps it separate: this one is where a sweep
    over a noun phrase that is not "creature" lands, and it refuses the printed
    quantifiers it does not recognise rather than guessing.

    Every refusal below is the same rule: a narrowing the matcher cannot test
    would be *dropped*, and a dropped narrowing on a sweep burns a strictly
    larger part of the board than the card prints.
    """
    if recipient.quantifier not in ("all", "each") or recipient.targeted:
        raise LoweringError("unsupported damage target quantifier", node=node)
    if computed:
        raise LoweringError(
            "a described-set damage sweep cannot carry a computed amount",
            node=node,
        )
    described = testable_filter_payload(
        recipient.filter,
        refusal="the damage sweep cannot narrow by",
        node=node,
        require_narrowing=False,
    )
    return (
        OracleInstruction(
            "deal_damage_each_matching", "", {"amount": amount, "filter": described}
        ),
    )


#: What each fused sweep kind can say about its creatures, as ``ObjectFilter``
#: fields. The kind's *name* is the whole narrowing — there is no filter payload
#: on any of them — so a printed word outside its row would be read here and
#: then dropped, and the card would deal to a strictly larger board than it
#: names. Disorder is the card that made that visible: "each **white** creature
#: and each player who controls a white creature" fused happily and burned every
#: creature on the table.
_SWEEP_NARROWINGS: dict[str, frozenset[str]] = {
    "earthquake_damage": frozenset({"card_types", "without_keywords"}),
    "hurricane_damage": frozenset({"card_types", "with_keywords"}),
    "deal_damage_each_creature_and_player": frozenset({"card_types"}),
    "deal_damage_each_attacking_creature": frozenset({"card_types", "attacking"}),
}


def _sweep_kind(recipients: tuple[ast.Recipient, ...]) -> str | None:
    """Recognize the board-sweep damage shapes as their dedicated handlers.

    These are genuinely different effects, not riders: they damage every player
    *and* a filtered set of creatures as one state-based-action batch.

    None means "no fused kind says this", which is not a refusal — the caller
    falls through to ``_conjuncts.lower_split_recipients``, one instruction per
    recipient, which carries every narrowing as payload. So the checks below
    cost a card nothing; what they buy is that a word these kinds cannot say
    never reaches one of them.
    """
    hits_players = [
        r for r in recipients
        if isinstance(r, ast.PlayerRef) and r.kind in ("each_player", "each_opponent")
    ]
    # A **narrowed** seat set is not the seat set these kinds damage: every one
    # of them hits every player, and a printed relative clause ("each player
    # **who controls a white creature**", Disorder) would be dropped on the way
    # in. The split lowering below carries it, so this is a fall-through and not
    # a refusal.
    if any(
        getattr(seats, "did", None) is not None
        or getattr(seats, "controls", None) is not None
        or getattr(seats, "compared", None) is not None
        for seats in hits_players
    ):
        return None
    creature_specs = [
        r for r in recipients
        if isinstance(r, ast.TargetSpec) and r.quantifier == "each"
    ]
    if len(creature_specs) != 1:
        return None
    filt = creature_specs[0].filter
    if filt.card_types != ("creature",):
        return None

    if hits_players:
        if filt.without_keywords == ("flying",):
            return _if_says_it_all("earthquake_damage", filt)
        if filt.with_keywords == ("flying",):
            return _if_says_it_all("hurricane_damage", filt)
        if not filt.with_keywords and not filt.without_keywords:
            return _if_says_it_all("deal_damage_each_creature_and_player", filt)
        return None
    if filt.attacking and not filt.with_keywords and not filt.without_keywords:
        return _if_says_it_all("deal_damage_each_attacking_creature", filt)
    return None


def _if_says_it_all(kind: str, filt: ast.ObjectFilter) -> str | None:
    """*kind*, or None when the printed phrase says more than its name can.

    The fused kinds carry no filter payload, so this is the one place a word
    they cannot express can be caught — and catching it is a fall-through to
    the split lowering, never a lost card.
    """
    return None if _restrictions_beyond(filt, _SWEEP_NARROWINGS[kind]) else kind


def lower_counter_sweep(node: ast.PutCounter) -> tuple[OracleInstruction, ...]:
    """"Put a <pair> counter on **each** <noun phrase>." (Basri's Solidarity,
    Misfortune.)

    The set is a *description*, so nothing is targeted and nothing is chosen —
    the handler reads the board as the effect resolves (CR 611.2c) and places
    the counter on every permanent the phrase matches. Which is why the printed
    noun phrase travels as a filter the shared matcher tests, rather than being
    baked into the handler's own name: a kind called
    ``add_counter_to_each_you_control`` cannot honestly carry "each creature
    **that player** controls", and a second kind beside it would be one effect
    with two spellings.

    Every refusal below is a way the sentence could otherwise reach more
    permanents than it names:

    * the counter must be a CR 122.1a P/T pair, because ``place_pt_counters``
      derives the P/T from the counter's own name and has nowhere to put one
      that has none;
    * the count must be a printed number, since nothing resolves an X over a
      swept set;
    * every narrowing must be one ``subject_matches`` can *test*. A key it
      would ignore is a counter on strictly more permanents than the card
      names, and on a -1/-1 sweep that is the board.

    "**that player** controls" is the one narrowing the matcher refuses outright
    rather than ignores (it names a seat no read of a board can make), so it is
    carried through to the handler, which answers it from the seat the
    announcement froze — the same split ``destroy_all_matching`` already makes
    of the same two words.
    """
    # A named counter ("put a **rust** counter on each artifact target opponent
    # controls", Corrosion) is the same sweep one counter kind over: the handler
    # places it through `engine/named_counters.py` where a P/T pair goes through
    # `place_pt_counters`, and nothing else about the sentence changes. The
    # refusal that used to stand here was about the *placer* rather than about
    # the sentence, so it is gone rather than widened.
    if not isinstance(node.count, ast.Fixed) or node.count.value < 1:
        raise LoweringError("a swept counter count is a printed number", node=node)
    described = _filter_payload(node.subject.filter)
    seat_scoped = described.get("controller") == "that_player"
    testable = dict(described)
    if seat_scoped:
        testable.pop("controller")
    refuse_untestable(
        testable, refusal="a counter sweep cannot narrow by", node=node
    )
    payload: dict[str, object] = {"counter": node.counter, "filter": described}
    if node.count.value != 1:
        payload["count"] = node.count.value
    return (OracleInstruction("add_counter_to_each_matching", "", payload),)


def lower_exile_sweep(
    node: ast.Exile, subject: ast.TargetSpec, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Exile **all** / **each** <noun phrase>." — the exile over a set the
    sentence *describes* (CR 611.2c), on the battlefield or in a graveyard.

    Moved here from ``lowering/exile.py`` at Prophecy's second wave, when that
    module sat thirty lines under the guard with Dual Nature's two sweeps to
    land in it. ``exile`` keeps every reading that picks its object; this is
    the one that picks nothing, which is the question this module answers for
    damage and for counters already.
    """
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
    # "…exile all tokens **with the same name as that creature**." (Dual
    # Nature.) CR 201.2's comparison against the object the trigger's event was
    # about — which has left the battlefield by the time this resolves, so the
    # name is the one the fire site froze, and the handler compares against it
    # rather than handing ``subject_matches`` a key it never sees. Lifted off
    # the filter for ``mana_value``'s reason above and put back as its own key.
    #
    # Gated on the events that freeze a *name*, not merely an object: under any
    # other event the words name a string nobody wrote down, and the honest
    # answer is a refusal rather than a sweep with its narrowing missing — the
    # same gate the destroy sweep reads for Eye of Singularity's "that name".
    if filt.name_from_event:
        if event not in EVENT_SUBJECT_NAMES:
            raise LoweringError(
                "\"that creature's name\" is the name of the object this "
                "trigger's event was about, and this event freezes none",
                node=node,
            )
        payload["name_from_event"] = True
    rest = dataclasses.replace(
        filt, colored=False, mana_value=None, name_from_event=False,
    )
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
    #
    # ``created_with_source`` beside it, for its reason exactly: "When this
    # enchantment leaves the battlefield, exile all tokens **created with this
    # enchantment**." (Dual Nature.) The record is the maker's id stamped on
    # each token, and the handler hands ``subject_matches`` the ability's
    # source — which under a leaves-the-battlefield trigger is the departed
    # permanent, still carrying the id its tokens were stamped with (CR 603.10a
    # looks back in time; CR 400.7 is why it is an id and not an identity). A
    # spell has no source, and the key then matches nothing rather than every
    # token on the table.
    leftovers = _restrictions_beyond(
        rest,
        _PAYLOAD_HONOURED_FILTER_FIELDS
        | {"zone", "blocked_by_source", "created_with_source"},
    ) + dropped_narrowings(rest, narrowings) + tuple(unusable)
    if leftovers:
        raise LoweringError(
            f"the exile sweep does not honour {leftovers[0]!r}", node=node
        )
    payload.update(narrowings)
    return (OracleInstruction("exile_all_matching", "", payload),)
