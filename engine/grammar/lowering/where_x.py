"""What defines the X a sentence's ``where`` clause names (CR 608.2).

Split out of ``lower`` when that module reached the thousand-line guard, and
the split needed one change to be legal: the four productions it held then each
began by calling ``lower_statement`` on the sentence the clause wraps, which
would be an *upward* import from here. The caller lowers that sentence and
passes the result in as *inner*.

That inversion is not a workaround, it is the honest shape. Every one of these
does the same two things to an already-lowered sentence — check that it reads an
X at all, then stamp the definition onto it — and none of them cares how the
sentence was lowered. What differs between them is only *what is counted*.

**And what is counted is read off the game or off a record, of which only the
first is here.** A count of a zone and the arithmetic over it, the counters on
the source, a characteristic of the object the sentence named: each is answered
by looking at the game as the clause resolves, and each is below. A definition
answered by a *record* of something already done — what an earlier step of the
same effect wrote down, what a cost ate, what the turn tallied, what was paid
as the source entered — is ``_record_definitions``, pre-split from here at the
Phase 0 before Odyssey along the line ``conditions`` and ``_record_conditions``
had already taken. :func:`lower_where_x` hands every clause down to it once,
ahead of its own readings, and that module's docstring has the measurements. A
new definition goes to whichever half its answer comes from.

The definition is stamped rather than folded into the amounts because the count
is taken at **resolution**: a permanent entering between the trigger and its
resolution changes the answer, so lowering cannot know it.
``engine/mixins/oracle_instructions.py`` resolves it at the single dispatch
point, which is what lets one clause serve every effect family.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction, X_FROM_COUNT
from .. import ast
from ..errors import LoweringError
from ._amounts import (TARGET_OPPONENT_SCOPE, count_filter_on_frozen_seat,
                       count_filter_on_targeted_seat, counted_definition_spec)
from ._amounts import _mentions_x, _stamp_x_from_count
from ._events import (CAST_SPELL_EVENTS, _EVENT_QUANTITIES, _EVENT_SUBJECT_PLAYERS,
                      EVENT_SUBJECT_PLAYER)
from ._record_definitions import lower_record_definition


#: The events whose firing is a life gain and that freeze how much — the
#: bound "the amount of life you gained" reads (``_EVENT_QUANTITIES``).
_LIFE_GAINED_EVENTS = frozenset({"you_gain_life", "player_gains_life"})


def _lower_chosen_x_ceiling(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    event: str | None,
) -> tuple[OracleInstruction, ...]:
    """"…you may pay {X}, **where X is less than or equal to** the amount of
    life you gained. If you do, draw X cards." (Well of Lost Dreams.)

    CR 107.3f: no cost defines this X, so its controller chooses it as they
    pay — the ``each_player_pays_any_mana`` payment the bare "you may pay {X}"
    already lowers to, every step behind it reading the paid amount as X. The
    clause bounds that choice, so it rides the payment as ``at_most`` (a count
    spec the handler evaluates as it arms the prompt) and stamps nothing.

    Refused unless the sentence *is* that payment — a ceiling over anything
    else would bound nothing — and unless the bound is the firing gain under
    an event that froze one: an unrecorded bound reads as zero, and the offer
    would be a {0} payment on a card reporting supported.
    """
    bound = node.definition.bound
    key = _EVENT_QUANTITIES.get(event or "") if event in _LIFE_GAINED_EVENTS else None
    if bound != ast.EachLifeGained(per=1) or key is None:
        raise LoweringError(
            "a chosen X is bounded only by the life the firing gain recorded",
            node=node,
        )
    if (
        node.as_cast
        or not inner
        or inner[0].kind != "each_player_pays_any_mana"
        or inner[0].payload.get("actor") != "you"
    ):
        raise LoweringError(
            "a ceiling on X bounds the X its controller chooses as they pay it",
            node=node,
        )
    payment = OracleInstruction(
        inner[0].kind, inner[0].value,
        {**inner[0].payload, "at_most": {"trigger_record": key}},
    )
    return (payment,) + inner[1:]

def _round_every_x_spec(
    instructions: tuple[OracleInstruction, ...], rounding: str, divisor: int
) -> tuple[OracleInstruction, ...]:
    """Add the halving to every ``x_from_count`` spec *instructions* carries.

    The mirror of :func:`_stamp_x_from_count`, and it recurses the same way and
    for the same reason: a wrapper carries its steps in its payload, so touching
    the top level alone would halve the outer instruction's X and leave the
    nested ones reading the whole number.

    ``divide_by`` is omitted at 2 so every spec written before fractions existed
    stays byte-identical -- the rule ``ast.Half`` states for its own field.
    """
    stamped = []
    for instruction in instructions:
        payload = dict(instruction.payload)
        spec = payload.get(X_FROM_COUNT)
        if isinstance(spec, dict):
            spec = dict(spec)
            spec["half"] = rounding
            if divisor != 2:
                spec["divide_by"] = divisor
            payload[X_FROM_COUNT] = spec
        for key in ("steps", "then", "else", "otherwise", "action"):
            nested = payload.get(key)
            if (
                isinstance(nested, tuple) and nested
                and isinstance(nested[0], OracleInstruction)
            ):
                payload[key] = _round_every_x_spec(nested, rounding, divisor)
        stamped.append(
            OracleInstruction(instruction.kind, instruction.value, payload)
        )
    return tuple(stamped)


def lower_where_x(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of <filter>" over a whole sentence.

    The definition is stamped onto the lowered instructions rather than folded
    into their amounts, because the count is taken **at resolution** (CR 608.2):
    a Shrine entering between the trigger and its resolution changes the answer,
    so lowering cannot know it. ``engine/mixins/oracle_instructions.py``
    resolves it into the context's X at the single dispatch point, which is what
    lets one clause serve every effect family instead of one.
    """
    # "…where X is **half** the creature's power, rounded down." (Catacomb
    # Dragon.) The halving rides on the *spec* rather than on the definition —
    # `_scaled` is the one place that applies it, so every definition below
    # gets it without knowing it can, exactly as the multiplier and the offset
    # already do. Unwrapped here rather than dispatched on, because it is not a
    # definition at all: it is an arithmetic over whichever one follows.
    # CR 601.2b: "…**as you cast this spell**" (Reap). The definition is the
    # same one every branch below reads; what the words change is *when* it is
    # asked, and only a count of a zone can be asked early. Every other channel
    # here answers out of the resolution's own scratchpad or off what a cost
    # ate — a back-reference, a death record, a payment characteristic — and
    # none of those exists while the spell is being announced, so freezing one
    # at the announcement would freeze a zero. Refused rather than approximated,
    # because a card whose X is announced and whose X is counted are different
    # cards.
    if isinstance(node.definition, ast.ChosenXAtMost):
        return _lower_chosen_x_ceiling(node, inner, event)
    if node.as_cast and not _is_cast_time_countable(node.definition):
        raise LoweringError(
            "only a count of a zone can be taken as a spell is cast", node=node
        )
    if isinstance(node.definition, ast.Half):
        halved = lower_where_x(
            dataclasses.replace(node, definition=node.definition.of),
            inner, produced, event=event,
        )
        return _round_every_x_spec(
            halved, node.definition.rounding, node.definition.divisor
        )
    # A definition answered by a **record** of something already done — what a
    # step of this effect wrote down, what a cost ate, what the turn tallied,
    # what was paid as the source entered — is ``_record_definitions``'. Handed
    # down here, where the first of those readings always was; every branch on
    # either side answers a node class no other does, so the order between the
    # two halves decides nothing.
    recorded = lower_record_definition(node, inner, produced, event)
    if recorded is not None:
        return recorded
    if isinstance(node.definition, ast.CharacteristicOfSubject):
        return _lower_where_x_characteristic(node, inner, produced, event)
    counter_spec = _source_counter_spec(node.definition)
    if counter_spec is not None:
        return _lower_where_x_counters(node, inner, counter_spec)
    # An aggregate over a set — a count, a maximum, the colours among — and the
    # printed arithmetic on it: "…**twice** the number of …" (Jovial Evil),
    # "…**2 plus** the number of cards named ~ in all graveyards" (Kindle),
    # "…the number of cards in your hand **minus the number of cards in that
    # player's hand**" (Bulwark). Read by ``_amounts.counted_definition_spec``,
    # the one reader the ``Pump`` form asks too: this arm used to unwrap the
    # arithmetic itself and then demand a plain count, while that form read
    # three aggregates and none of the arithmetic — so which definitions a card
    # could print depended on which sentence it printed them in. A `Times` or a
    # `Plus` over anything that reader does not aggregate (a death history, a
    # mana value) comes back None and falls to the refusal below rather than
    # silently losing the "twice".
    #
    # What stays here is what only this caller knows — the sentence, so "that
    # player" in the counted phrase is moved onto the seat it named
    # (``_count_filter_for``) before the count is described.
    spec = counted_definition_spec(
        node.definition, node,
        rewrite=lambda filt: _count_filter_for(filt, inner, node, event),
        event=event,
    )
    if spec is None:
        raise LoweringError("only a count can define X in a where-clause", node=node)
    if not _mentions_x(inner):
        # The clause defined an X the sentence never used, which means one of
        # them was misread. Refusing keeps that loud instead of executing the
        # sentence with the definition quietly discarded.
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    if node.as_cast:
        # And **whose** board, which is the half a cast-time count has to settle
        # that a resolution-time one does not. At the announcement nothing has
        # chosen a player: this engine's cast wire carries one
        # ``target_player_index``, and for a spell whose targets sit in a
        # graveyard that field already means *which pile*, so a count scoped to
        # "target player" would read a seat nobody named. The three scopes below
        # need no announcement — the caster, the whole board, and CR 102.3's
        # first living opponent — and every other one refuses the line rather
        # than counting a board the caster did not pick. A restriction the
        # support gate reads too: the card is unsupported, not admitted with the
        # wrong seat counted.
        if spec.get("owner") not in ("you", "all", TARGET_OPPONENT_SCOPE):
            raise LoweringError(
                "a count taken as a spell is cast must name a seat the "
                "announcement can resolve",
                node=node,
            )
        # CR 601.2b. The key the cast path reads to take this count at the
        # announcement and the resolution reads to know it must **not** take it
        # again — one flag for both halves, so "when is this counted?" has one
        # answer rather than a cast-time table and a resolution-time table free
        # to disagree. Written last so every spec on a clause without the words
        # stays byte-identical.
        spec["as_cast"] = True
    return _stamp_x_from_count(inner, spec)


def _is_cast_time_countable(definition: "ast.Amount") -> bool:
    """Whether *definition* is the plain board count CR 601.2b can freeze.

    The arithmetic wrappers are transparent: "twice the number of …" and
    "2 plus the number of …" are the same count with a factor and a constant
    over it, and both are computable from a board alone. Anything else is a
    record only a resolution holds.
    """
    while True:
        if isinstance(definition, ast.Half):
            definition = definition.of
        elif isinstance(definition, ast.Times):
            definition = definition.of
        elif isinstance(definition, (ast.Plus, ast.Minus)):
            left, right = definition.left, definition.right
            if isinstance(right, ast.Fixed) and not isinstance(left, ast.Fixed):
                definition = left
            elif isinstance(left, ast.Fixed) and not isinstance(right, ast.Fixed):
                definition = right
            else:
                return False
        else:
            return isinstance(definition, ast.CountOf)


def _source_counter_spec(definition: "ast.Amount") -> dict[str, object] | None:
    """The count spec "<n> plus/minus twice the number of <kind> counters on
    <the source>" names, or None when *definition* is something else.

    One reader for the four shapes the arithmetic wrappers make of one printed
    count, because they are one count: the kind is what is being counted and
    the factor and the constant are printed numbers on top of it. Written as an
    unwrapping rather than as four ``isinstance`` arms in the dispatcher above
    so that a shape it cannot take — a multiplier over something else, a
    subtrahend that is itself a count — falls through to the refusal there
    instead of being read as a plain count with its rider dropped.

    The constant is ``plus`` and never ``offset``: ``_scaled`` applies
    ``offset`` *before* the multiplier, so "twice the number … minus 2" written
    that way would be 2N-4.
    """
    factor = 1
    plus = 0
    if isinstance(definition, (ast.Minus, ast.Plus)):
        sign = -1 if isinstance(definition, ast.Minus) else 1
        if not isinstance(definition.right, ast.Fixed):
            return None
        plus = sign * definition.right.value
        definition = definition.left
    if isinstance(definition, ast.Times):
        factor = definition.factor
        definition = definition.of
    spec: dict[str, object]
    if isinstance(definition, ast.CountersOnGranter):
        # "…counters on the permanent with id N that granted this ability"
        # (Archery Training). The same count of the same kind of pile on the
        # object CR 201.5a says the granted ability names; both printed words
        # ride the spec, and ``evaluate_count`` finds the permanent by the id.
        spec = {
            "granter_counters": definition.kind,
            "granter_id": definition.permanent_id,
        }
    elif isinstance(definition, ast.CountersOnSource):
        spec = {"source_counters": definition.kind}
    else:
        return None
    if factor != 1:
        spec["multiplier"] = factor
    if plus:
        spec["plus"] = plus
    return spec


def _lower_where_x_counters(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...], spec: dict[str, object]
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of +1/+1 counters on it." (Primordial Ooze.)

    Not a count of a *set*, so it carries no filter: a counter is not an object
    and ``evaluate_count`` scans zones for objects. What it names is a number
    sitting on the ability's own source, which only a resolution knows — the
    same thing ``object_characteristic`` is for one named object's power.

    The kind rides the spec, so a card counting a differently-named counter this
    way needs no production. It is stamped like every other definition, so the
    whole sentence — the offer, the payment, and the "if you don't" behind it —
    reads one X.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, spec)


def _names_a_player_target(inner: tuple[OracleInstruction, ...]) -> bool:
    """Whether the lowered sentence chose a *player* as its target.

    Read off the **picker's description** and nothing else. The `recipient`
    key cannot answer it: "deals X damage to target opponent" and "deals X
    damage to that player" (a trigger's upkeep player) both lower to
    `recipient: "target_player"`, because the seat comes off the resolution
    context either way. Only one of them chose a target, and only for that one
    is `context.target` the player the words name — so the description, which
    exists precisely to say a choice was offered, is the honest test.
    """
    for instruction in inner:
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") in (
            "player", "player_or_planeswalker"
        ):
            return True
    return False


#: The zones a printed "their <zone>" names a player's own copy of (CR 400.1).
_PLAYER_ZONES = frozenset({"hand", "graveyard", "library"})


def _their_zone_on_frozen_seat(filt, inner, event):
    """*filt* with "**their** hand" moved onto the seat the firing event froze.

    "At the beginning of each player's upkeep, that player mills X cards, where
    X is the number of cards in **their** hand." (Dreamborn Muse.) The parse
    reads "their" as the owner word, and an owner the count cannot resolve
    falls back to ``context.target or context.caster`` — which for an upkeep
    trigger that chose nothing is the controller's default opponent, so every
    player milled as many cards as the Muse controller's opponent held. The
    pronoun is the player the sentence is about, and with no player target the
    only one it can be is the seat the event froze (CR 603.10) — the seat
    "that player" in the same sentence already reads.

    Only under an event that froze a seat and only with no player target: a
    targeted sentence ("Target player draws cards equal to the number of cards
    in their hand", Laquatus's Creativity) already reads its target through the
    same fallback, and every other filter comes back unchanged.
    """
    owner = getattr(filt, "zone_owner", None)
    if (
        event in _EVENT_SUBJECT_PLAYERS
        and isinstance(owner, ast.PlayerRef)
        and owner.kind == "owner"
        and filt.zone in _PLAYER_ZONES
        and not _names_a_player_target(inner)
    ):
        return dataclasses.replace(
            filt, zone_owner=ast.PlayerRef(EVENT_SUBJECT_PLAYER)
        )
    return filt


def _count_filter_for(filt, inner: tuple[OracleInstruction, ...], node, event=None):
    """The filter a where-clause's count is taken over, with "that player"
    resolved into a zone owner.

    "…where X is twice the number of white creatures **that player** controls"
    (Jovial Evil): the player is the one the sentence in front of the clause
    targeted, so the count is taken on *their* battlefield. `count_spec`
    refuses a controller narrowing outright — `permanent_matches_filter` cannot
    test a controller, so the key would be handed over and ignored — and the
    fix is to move the restriction to the axis the counter *does* read, which
    is whose zone it scans.

    Admitted only when the sentence actually named a player target. Without
    one, "that player" points at nothing and `count_from_payload` would fall
    back to the caster — counting the wrong board and reporting the card
    supported, which is the failure the refusal exists for.
    """
    if filt.controller != "that_player":
        return _their_zone_on_frozen_seat(filt, inner, event)
    # "At the beginning of each opponent's upkeep, … where X is the number of
    # nontoken permanents of the chosen color **they control**" (Psychic
    # Allergy). Nothing was targeted: the seat is the one the *event* was about,
    # frozen into the trigger's context by the upkeep step (CR 603.10). Which
    # events carry one is `_EVENT_SUBJECT_PLAYERS` — the same table the damage
    # recipient beside it reads, so the count and the damage cannot end up on
    # two different players.
    if not _names_a_player_target(inner):
        # The frozen-seat half lives in the counting floor, which a counter
        # placement reads too ("…for each untapped land that player controls",
        # Mana Cache) — one rewrite, one table of which events froze a seat.
        return count_filter_on_frozen_seat(filt, event, node)
    # …and the targeted half lives there too, since Allied Strategies printed
    # the same binding in the amount position ("a card **for each** … they
    # control"): one rewrite for both spellings of the count.
    return count_filter_on_targeted_seat(filt)


def _lower_where_x_characteristic(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…, where X is **its** mana value." (Great Defender, Subdue, Kry Shield.)

    Stamped like every other where-clause and resolved at the same single
    dispatch point, so the sentence in front of it needs no special case: what
    changes is only *what* is counted. "Its" is the object the sentence already
    named — the resolution reads it off the chosen target, which is the one
    object a resolution can name without a second choice.
    """
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    # "Its" is whatever object the sentence already named, and the sentence
    # names it one of two ways: by targeting a permanent, or by binding the
    # spell its trigger fired on ("Whenever a player casts an instant spell,
    # counter it unless that player pays {X}, where X is **its** mana value").
    # Decided here, where both the definition and the lowered sentence are in
    # hand, rather than by a resolution-time fallback order that would have to
    # guess when a sentence has both.
    referent = node.definition.referent
    if referent is not None and referent.is_source:
        # "…, where X is **this creature's power**" (Auriok Bladewarden's
        # spelling, in a sentence a ``WhereX`` wraps). Not the object the
        # sentence named: the ability's own source, which the resolution holds
        # whether or not it is still on the battlefield (CR 608.2h).
        return _stamp_x_from_count(inner, {"object_characteristic": {
            "object": "source",
            "characteristic": node.definition.characteristic,
            "offset": node.definition.offset,
        }})
    if (
        referent is not None
        and referent.zone == "stack"
        and referent == dataclasses.replace(ast.ObjectFilter(), zone="stack")
    ):
        # "Whenever a player casts a creature spell, … that player creates an
        # X/X white Reflection creature token, where X is the mana value of
        # **that spell**." (Pure Reflection.) The spell is named outright and
        # nothing in the sentence acts on it, so there is no ``bound_to_trigger``
        # step to read the binding off — the firing event is what says which
        # spell. Under any other event "that spell" names nothing frozen, and
        # the resolver would read a zero.
        if event not in CAST_SPELL_EVENTS:
            raise LoweringError(
                "'that spell' names the spell a cast trigger fired on, and "
                "this event freezes none", node=node,
            )
        if node.definition.characteristic != "mana_value":
            raise LoweringError(
                "a spell has no power or toughness to read", node=node
            )
        return _stamp_x_from_count(inner, {"object_characteristic": {
            "object": "triggering_spell",
            "characteristic": "mana_value",
            "offset": node.definition.offset,
        }})
    role = _referent_role(node, inner)
    names_a_spell = any(i.payload.get("bound_to_trigger") for i in inner)
    if names_a_spell and node.definition.characteristic != "mana_value":
        # A spell on the stack has no power or toughness to read (CR 208.1), so
        # a clause asking for one about a bound spell is a misreading of one
        # half or the other. Refused rather than answered with a zero the card
        # never printed.
        raise LoweringError(
            "a spell has no power or toughness to read", node=node
        )
    described: dict[str, object] = {
        "object": "triggering_spell" if names_a_spell else "target",
        "characteristic": node.definition.characteristic,
        "offset": node.definition.offset,
    }
    if role is not None:
        # Which of the sentence's targets the clause reads. Absent for every
        # one-target sentence, so nothing downstream has to special-case the
        # common shape — and *present* whenever the sentence named more than
        # one, because "the target" is not an answer then.
        described["role"] = role
    elif not names_a_spell:
        # CR 608.2h: an object the effect itself has moved answers with its
        # last known information. "Destroy target artifact. … Create X …
        # tokens, where X is **that artifact's** mana value" (Artifact
        # Mutation) is asked of a card in a graveyard, so the clause names the
        # record the step in front of it wrote down — and names one only where
        # a step of this effect really writes it (*produced*), the producer
        # discipline every back-reference follows. The four Mutations asked the
        # battlefield instead, read zero, and made no tokens.
        last_known = next(
            (
                key
                for key in _LAST_KNOWN_RECORDS.get(node.definition.characteristic, ())
                if key in produced
            ),
            None,
        )
        if last_known is not None:
            described["last_known"] = last_known
    return _stamp_x_from_count(inner, {"object_characteristic": described})


#: The record a step leaves of a characteristic of **the object it moved**, by
#: characteristic — a destroy's and a bounce's, the two the pool prints.
_LAST_KNOWN_RECORDS: dict[str, tuple[str, ...]] = {
    "mana_value": ("its_mana_value", "returned_mana_value"),
    "power": ("its_power",),
    "toughness": ("its_toughness",),
}


#: What a role's own key licenses a printed back-reference to call it. "that
#: **blocked** creature" is the only way English has to point at the dependent
#: end of ``blocked_by_role`` without repeating the whole relative clause, and
#: the adjective has no filter payload of its own (``ObjectFilter.blocked`` is
#: deliberately unemitted), so it is matched against the *role* rather than
#: against a permanent. A second dependent relation adds a row.
_ROLE_BACKREFERENCE_ADJECTIVES: dict[str, str] = {"blocked_by_role": "blocked"}


def _target_roles(inner: tuple[OracleInstruction, ...]) -> list[dict]:
    """The ordered target roles the lowered sentence describes, if any."""
    for instruction in inner:
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") == "roles":
            return list(targets.get("roles") or ())
    return []


def _referent_role(node: ast.WhereX, inner: tuple[OracleInstruction, ...]) -> str | None:
    """Which target role "the power of **that blocked creature**" names.

    None when the sentence named one target — "its" and "that creature" can
    only mean that one, and the resolution reads it off the single chosen slot
    as it always has.

    When the sentence named **roles**, a referent is required and must match
    exactly one of them. Both halves refuse rather than guess: a bare "its"
    over two targets of different kinds does not say which, and a referent
    matching both would read a characteristic off whichever slot happened to be
    first. Either way the card would still compile and still look supported,
    which is the failure this refusal exists for.
    """
    referent = node.definition.referent
    roles = _target_roles(inner)
    if not roles:
        if referent is not None and _referent_beyond_backreference(referent):
            raise LoweringError(
                "a where-clause referent this sentence cannot name", node=node
            )
        return None
    if referent is None:
        raise LoweringError(
            "this sentence names two targets, so 'its' does not say which",
            node=node,
        )
    if _referent_beyond_backreference(referent):
        raise LoweringError(
            "a where-clause referent this sentence cannot name", node=node
        )
    matched = [role["role"] for role in roles if _referent_matches_role(referent, role)]
    if len(matched) != 1:
        raise LoweringError(
            "a where-clause referent that names no single target role", node=node
        )
    return matched[0]


#: The referent fields a printed back-reference may set. Anything else is a
#: narrowing the match below cannot read, and reading it as though it were
#: absent would point the clause at a role the card never named.
_REFERENT_FIELDS = frozenset({"card_types", "subtypes", "blocked"})


def _referent_beyond_backreference(referent) -> bool:
    default = ast.ObjectFilter()
    return any(
        field.name not in _REFERENT_FIELDS
        and getattr(referent, field.name) != getattr(default, field.name)
        for field in dataclasses.fields(referent)
    )


def _referent_matches_role(referent, role: dict) -> bool:
    """Whether *referent*'s printed words describe *role* and no other."""
    filt = role.get("filter") or {}
    if tuple(referent.card_types) != (
        (filt["type_filter"],) if isinstance(filt.get("type_filter"), str) else ()
    ):
        return False
    if tuple(referent.subtypes) != (
        (filt["subtype_filter"],) if isinstance(filt.get("subtype_filter"), str) else ()
    ):
        return False
    for key, adjective in _ROLE_BACKREFERENCE_ADJECTIVES.items():
        if bool(getattr(referent, adjective, False)) != bool(role.get(key)):
            return False
    return True
