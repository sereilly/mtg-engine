"""Lowering the loops: one sentence performed once per member of a set.

Split out of `control_flow.py` at the thousand-line guard, along the line that
module's own docstring already drew. `control_flow` is named after the
*composers* — `sequence`, `may`, `one_of` — the shapes that decide **whether**
and **in what order** a sentence runs. A loop decides **how many times**, and
what it iterates is a set: seats (CR 101.4's turn order), permanents the board
holds when the ability resolves (CR 611.2c), or a number an earlier step
recorded.

That is one question with one answer — "what is the set?" — and every function
here is a different reading of it, which is why they lower onto one `for_each`
instruction with different iterator payloads. Nothing here reads an offer and
nothing in `control_flow` reads a set, so the split is along a real boundary
rather than a size.

Each takes its body **already lowered**: `lower.py` reads the sentence inside
the loop, exactly as it does for the composers next door, so this module needs
no parser handed down. The one exception is the per-death counter loop at the
bottom, whose two handlers read the death count out of the trigger's own
context and take nothing from a payload — so its body is checked rather than
lowered, and it is `lower.py`'s fall-through for `ForEach`.

It arrived here from `lowering/counters.py` at Alliances' wave 3, when that
module reached the size guard. That is the mirror re-forming rather than a new
boundary: it is a `for_each` lowering and the other three already lived here,
so "which set does this sentence repeat over?" is answered in one module again.
What it repeats *is* a counter placement, which is exactly why it could sit in
either — and `lower.py` dispatching `ForEach` is what decides, since a family
named for the loop is the one that owns every reading of the loop.

Two more came home from `lowering/hand.py` at Prophecy's Phase 0, by the same
rule: the per-shortfall loop (Truce), which is the life-lost loop's twin and
reads no hand, and "for each of those cards / creatures", whose three records
are a hand pick, a targeting choice and a sweep's destroyed set — two of them no
hand step writes. The hand pick's key is in `_record_keys`, so the step that
writes it and the loop here that reads it still spell it once.
"""

from __future__ import annotations

from ...oracle_types import CHOSEN_TARGET_PERMANENTS, OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload
from ._events import _COUNTERS_PLACED_THIS_WAY
from ._cost_records import optional_cost_key
from ._record_keys import CHOSEN_HAND_CARDS_RESULT


def _lower_for_each_player(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each player,** this enchantment deals 1 damage to that player
    unless they pay {B} or {3}." (Lim-Dûl's Hex.)

    A loop over *seats* rather than over objects. The same ``for_each`` the
    object loops lower onto, with the seat set as the iterator — and the
    handler binds each seat as "that player" while its iteration runs, which is
    what the printed back-reference means and the only way one sentence can
    name a different player each time round.

    Refused for any other player reference: "for each opponent" is a real set
    and lowers here too, but a reference naming *one* seat is not a loop at all
    and would repeat the sentence once against a seat nobody chose.
    """
    if node.iterator.kind not in _LOOPED_SEAT_SETS:
        raise LoweringError(
            f"no loop repeats an effect over the {node.iterator.kind}", node=node
        )
    if not inner:
        raise LoweringError("a per-player loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"players": node.iterator.kind}, "effect": inner},
        ),
    )


#: The player references that name a *set* of seats a loop can walk. The same
#: two ``handlers/control_flow._offered_seats`` enumerates, and deliberately no
#: more: a reference naming one seat is not a loop.
_LOOPED_SEAT_SETS = frozenset({"each_player", "each_opponent"})


def _lower_for_each_matching(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each attacking creature without flying,** its controller may pay
    {1}." (Tidal Flats.) "**For each attacking red creature,** prevent all
    combat damage that would be dealt by that creature this turn unless its
    controller pays {2}{R}." (Heroism.)

    A loop over what the **board** holds when the ability resolves — the fourth
    kind of iterator beside the recorded sets, the count and the seats, and the
    one the handler has always had a branch for and nothing could reach.

    The filter is the whole iterator payload, which is what the handler matches
    each permanent against; every key in it therefore has to be one
    ``subject_matches`` answers, or the loop would run over a strictly larger
    set than the phrase names — "creature **without flying**" is a layer-6
    question (CR 613.1f), and a loop that dropped it would offer Tidal Flats'
    toll to every attacker including the fliers it is printed to let through.
    """
    described = _filter_payload(node.iterator)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the loop cannot test this restriction", node=node
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction("for_each", "", {"iterator": described, "effect": inner}),
    )


def _lower_for_each_life_lost(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    event: str | None,
) -> tuple[OracleInstruction, ...]:
    """"**For each 1 life you lost,** sacrifice a permanent other than this
    enchantment unless you discard a card." (Oath of Lim-Dûl.)

    A loop whose iterator is a *number*, not a set — so the same ``for_each``
    the three "this way" sets lower onto, with the count coming off the firing
    event's frozen context instead of off the resolution scratchpad.

    Three refusals, each a way the sentence could otherwise mean more than it
    says:

    * the event must be one that freezes a life loss. Under any other trigger
      the phrase names a number nobody recorded, and an unwritten quantity
      reads as zero — a loop that runs no times on a card reporting supported.
    * the unit must be the printed 1. "For each **2** life you lost" is half as
      many repetitions, and the handler divides by nothing.
    * the body must lower to something, for ``_lower_for_each_chosen``'s
      reason: an empty loop is a sentence that reports supported and does not
      run.
    """
    if event != "you_lose_life":
        raise LoweringError(
            f"no event named {event!r} records the life this loop counts",
            node=node,
        )
    if node.iterator.per != 1:
        raise LoweringError(
            "this loop repeats once per 1 life lost, not per "
            f"{node.iterator.per}",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-life loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"repeat_from_trigger": "life_lost"}, "effect": inner},
        ),
    )


def _lower_for_each_short_of_this_way(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each card less than two a player draws this way,** that player
    gains 2 life." (Truce.)

    :func:`_lower_for_each_life_lost`'s twin, and a *nested* loop where that one
    is flat. The sentence names two things at once — "a player" and, inside it,
    a count — so it lowers to a loop over seats (CR 101.4's turn order) with a
    counted repetition inside it. The seat loop is what binds "that player", and
    the inner count is one number per seat, read out of the record the sentence
    in front of it wrote.

    Two refusals, each a way the words could otherwise mean more than they
    say:

    * a step of this same effect must record the count. "This way" is a
      back-reference, and one with no producer names nothing — here it would
      compute the printed base and hand every player the *maximum* life, which
      is the card upside down (idiom 7).
    * the body must lower to something, for :func:`_lower_for_each_chosen`'s
      reason: an empty loop reports supported and does not run.
    """
    record = node.iterator.record
    if record not in produced:
        raise LoweringError(
            f"nothing in this effect records the {record!r} count this loop is "
            "short of",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-shortfall loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # The seats, in turn order, so "that player" names one of them
                # per iteration — the same binding every multi-seat offer makes.
                "iterator": {"players": "each_player"},
                "effect": (
                    OracleInstruction(
                        "for_each", "",
                        {
                            "iterator": {
                                "repeat_from_record": {
                                    "record": record, "base": node.iterator.base,
                                }
                            },
                            "effect": inner,
                        },
                    ),
                ),
            },
        ),
    )


def _lower_for_each_counters_placed(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each +1/+1 counter you put on a creature this way,** remove a
    +1/+1 counter from that creature at the beginning of the next cleanup step."
    (Bounty of the Hunt.)

    A loop over the *counters* an earlier step of this same resolution placed,
    one iteration per counter — so a creature given two of them is iterated
    twice and gets two delayed abilities, which is what makes the removal come
    out even with the placement.

    Refused without the producer, exactly as the three object-shaped "this way"
    windows are: with no earlier placement the words name nothing, and an empty
    loop is a sentence that reports supported and does not run. The printed
    counter kind is not checked against the record here — the record holds
    permanents, not kinds — so the check is that the *same resolution* placed
    counters at all, which is the producer, plus the body, which names the kind
    itself and removes that one.
    """
    if _COUNTERS_PLACED_THIS_WAY not in produced:
        raise LoweringError(
            "'counters put on a creature this way' needs a step of this effect "
            "that put some there",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-counter loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                "iterator": {"produced_by": _COUNTERS_PLACED_THIS_WAY},
                "effect": inner,
            },
        ),
    )


def _lower_for_each_cost_paid(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each additional {1}{R} you paid,** destroy another target
    artifact." (Primitive Justice, Taste of Paradise.)

    :func:`_lower_for_each_life_lost`'s twin, one channel over: a loop whose
    iterator is a number, read off what the *caster announced* as the spell was
    cast (CR 601.2b) rather than off a firing event. It is on the stack item's
    choices because the pool that paid it is empty by resolution (CR 500.5).

    No event gate, deliberately, where the life-lost loop has one: this number
    is recorded by the casting path for every spell that prints an optional
    additional cost, so there is no trigger it could be missing from. What
    there *is* to refuse is a body that lowered to nothing — an empty loop is a
    sentence that reports supported and does not run, this file's standing rule.
    """
    if not inner:
        raise LoweringError("a per-payment loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                "iterator": {
                    "repeat_from_cost": optional_cost_key(node.iterator.symbols)
                },
                "effect": inner,
            },
        ),
    )


# Counter placements repeated once per creature that died this turn, keyed by
# the counter's printed name — the only thing that differs between the two
# cards written this way, and what decides which handler runs. Both handlers
# read the death count from the trigger's own context rather than from the
# payload, so the payloads here are the legacy rules' literals and nothing
# more.
_PER_DEATH_COUNTERS: dict[str, tuple[str, dict[str, object]]] = {
    # Scavenging Ghoul — regeneration fuel, spent by its own activated ability.
    "corpse": ("add_corpse_counters_for_each_creature_died", {}),
    # Khabál Ghoul — P/T counters.
    "+1/+1": ("add_plus1_counters_for_each_creature_died", {"power": 1, "toughness": 1}),
}

# The exact subject both handlers act on. Compared for equality rather than
# probed field by field, so a filter field added to the AST later refuses by
# default instead of being ignored by a lowering written before it existed.
_PER_DEATH_SUBJECT = ast.TargetSpec(
    "this", ast.ObjectFilter(card_types=("creature",), is_source=True)
)

# Both handlers count *every* creature that died, with no narrowing available
# to them, so any filtered set has to refuse rather than over-count.
_ANY_CREATURE_DIED = ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))


def _lower_for_each(node: ast.ForEach) -> tuple[OracleInstruction, ...]:
    """"…put a <kind> counter on this creature for each creature that died this
    turn." (Scavenging Ghoul, Khabál Ghoul.)

    The legacy registry needed a whole-sentence substring rule per card, and the
    +1/+1 one carries a comment saying it must out-rank the plain "put a +1/+1
    counter on this creature" rule — which sits 96,500 order slots away, because
    the two rules are unrelated except that one is a prefix of the other. Losing
    that race would drop the per-death scaling and put down a single counter.
    Here the "for each …" clause is a node, so the two shapes are simply
    different ASTs and there is no race to lose.

    Everything else refuses, because neither handler reads anything from its
    payload: the subject, the multiplier and the counted set are all fixed in
    the handler's own source, so a clause differing in any of them would be
    executed as if it had not.
    """
    if node.iterator != _ANY_CREATURE_DIED:
        raise LoweringError("no handler repeats an effect over this set", node=node)
    placement = node.effect
    if not isinstance(placement, ast.PutCounter):
        raise LoweringError("no handler repeats this effect per death", node=node)
    if placement.subject != _PER_DEATH_SUBJECT:
        raise LoweringError(
            "the per-death counter handlers only ever reach their own source", node=node
        )
    if placement.up_to or placement.count != ast.Fixed(1):
        raise LoweringError("no handler places more than one counter per death", node=node)
    found = _PER_DEATH_COUNTERS.get(placement.counter)
    if found is None:
        raise LoweringError(
            f"no handler places {placement.counter!r} counters per death", node=node
        )
    kind, payload = found
    return (OracleInstruction(kind, "", dict(payload)),)


# ---------------------------------------------------------------------------
# A set an earlier step of the same effect recorded
# ---------------------------------------------------------------------------


def _lower_for_each_destroyed(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each creature that died this way,** <effect>." (Glyph of
    Reincarnation.)

    A loop over the objects an earlier step of *this same effect* destroyed —
    the set behind ``destroyed_this_way``, which the sweep handlers record
    because by the time this runs the board no longer holds it. Here rather
    than beside ``_lower_for_each`` in ``lowering/counters``: that one repeats a
    counter placement a fixed number of times and never looks at what died,
    while this is about the destroy family's own record.

    Refused without a producer, as every back-reference in this grammar is:
    "this way" with no earlier step names nothing at all, and an empty loop is a
    sentence that reports supported and does not run.

    The inner statement arrives already lowered, the way ``lower_where_x``'s
    does and for its reason — nothing here cares how it was lowered, only that
    it is repeated once per object.
    """
    if "destroyed_this_way" not in produced:
        raise LoweringError(
            "'died this way' with no earlier step in this effect that "
            "destroyed anything", node=node,
        )
    filt = node.iterator.filter
    narrowing = filt.to_payload()
    # The narrowing is held to what the *pure* matcher can answer, because that
    # is what the loop uses: the objects are in graveyards by the time this runs,
    # so there is no observer and no board to ask a layer question of, and every
    # key it does answer it answers off last-known information (CR 608.2h).
    #
    # It read the card type alone until Mirage printed "If **a white creature**
    # dies this way" (Cinder Cloud) — a colour is exactly as answerable, and the
    # refusal was a list of one key rather than a statement about the matcher.
    if untestable_filter_keys(narrowing, allowed=OBJECT_ONLY_FILTER_KEYS) or (
        filt.zone != "battlefield"
    ):
        raise LoweringError(
            "'died this way' iterates what the earlier step destroyed and is "
            "narrowed only by what the matcher can ask of an object that has "
            "left", node=node,
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # Named rather than implied: the loop reads the objects an
                # earlier step recorded under this key, and the key is what
                # ties the two halves of the sentence together.
                #
                # The printed card type rides beside it. It is normally a
                # restatement of what the sweep destroyed — "for each
                # **creature** that died this way" after a creature sweep, "for
                # each **land** destroyed this way" after a land sweep — but a
                # restatement is only ever as reliable as the reader that checks
                # it, and the loop applies it to the record rather than
                # assuming the two agree.
                "iterator": {
                    "produced_by": "destroyed_this_way_objects", **narrowing,
                },
                "effect": inner,
            },
        ),
    )


def _lower_for_each_chosen(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each of those cards,** <effect>." (Sylvan Library.)
    "**For each of those creatures,** <effect>." (Winter's Chill.)

    The sibling of ``_lower_for_each_destroyed``, and refused the same way: a
    back-reference with no earlier step that made a choice names nothing, and
    an empty loop is a sentence that reports supported and does not run.

    Two records, one clause. Which of them answers is the printed noun: a hand
    spelling reads the cards a "choose two cards in your hand" step recorded,
    and a permanent spelling reads the permanents a "choose X target …"
    sentence did. Reading either as the other walks an empty list, which is a
    sentence that reports supported and does nothing — so the noun decides and
    the missing producer refuses.
    """
    named = node.iterator.subject
    if named is not None:
        # Which record "those" names is decided by what an earlier step of this
        # same effect actually wrote, in the order the phrase can mean them: a
        # step that *chose* permanents is the closer referent (Winter's Chill
        # names its own targets), and a sweep that destroyed some is the other
        # ("Destroy all artifacts. … **each of those artifacts** …", Seeds of
        # Innocence).
        #
        # Read off *produced* rather than fixed by the parse, for the reason
        # every back-reference here is: the printed word is the same either way
        # and only the effect around it can say which set exists. Neither
        # recorded refuses, exactly as before — an empty loop is a sentence that
        # reports supported and does not run.
        record = None
        if CHOSEN_TARGET_PERMANENTS in produced:
            record = CHOSEN_TARGET_PERMANENTS
        elif "destroyed_this_way" in produced:
            record = "destroyed_this_way_objects"
        if record is None:
            raise LoweringError(
                "'those <permanents>' with no earlier step in this effect that "
                "chose or destroyed any",
                node=node,
            )
        if not inner:
            raise LoweringError("a per-permanent loop with no effect in it", node=node)
        # The printed noun rides beside the record's name, exactly as it does
        # for a destruction sweep's loop: "for each of those **creatures**"
        # after a sentence that targeted attacking creatures is a restatement,
        # and a restatement checked is a restatement. ``for_each`` applies it
        # with ``permanent_matches_filter``, so a target that stopped answering
        # the phrase drops out of the loop rather than being acted on.
        return (
            OracleInstruction(
                "for_each", "",
                {
                    "iterator": {
                        "produced_by": record,
                        **_filter_payload(named),
                    },
                    "effect": inner,
                },
            ),
        )
    if CHOSEN_HAND_CARDS_RESULT not in produced:
        raise LoweringError(
            "'those cards' with no earlier step in this effect that chose any",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-card loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"produced_by": CHOSEN_HAND_CARDS_RESULT}, "effect": inner},
        ),
    )
