"""Payload shapes and small values every lowering family needs.

The bottom of the lowering layer. Target descriptions, filter payloads, amount
encoding, the `_is_source` / `_is_you` subject predicates, and two values that
are here for a specific reason rather than by taxonomy: `_full_mana_payload`
(with `_MANA_KEYS`) and `_REST_OF_TURN`.

Those two were the *only* references crossing between lowering families — an
"unless they pay" cost is wanted by damage, the board and cards; a
rest-of-turn duration by damage and combat. A fragment several families need is
not one family's property, and leaving it in one is what couples the rest to it.

`GRAMMAR_ONLY_PAYLOAD_KEYS` is here too, since it describes payloads rather
than any one effect. So is `_back_reference_payload`, for the same reason the
two above are: "that much" is a fragment life, damage and cards all read, and
what it points at is one question with one answer — a family deciding it alone
would be a family deciding it differently.
"""

import dataclasses
from .. import ast
from ..errors import LoweringError


def _filter_payload(filt: ast.ObjectFilter) -> dict[str, object]:
    """A filter's payload, refusing shapes no handler implements."""
    payload = filt.to_payload()
    if "type_filter_all" in payload:
        raise LoweringError(
            "no handler matches a permanent that is several types at once", node=filt
        )
    # `to_payload` cannot express a zone, so every handler reached through here
    # searches the battlefield. Emitting a graveyard-scoped filter as a plain
    # one would point the handler — and engine/targeting.py's picker — at the
    # wrong zone entirely, so the whole line is refused instead. Effects that
    # genuinely move cards between zones read the filter directly.
    if filt.zone != "battlefield" or filt.is_card:
        raise LoweringError(
            f"no handler reads a filter scoped to the {filt.zone}", node=filt
        )
    if filt.mana_value is not None and "mana_value" not in payload:
        # ``to_payload`` emits a literal mana-value bound and
        # ``permanent_matches_filter`` tests it; a *variable* bound ("mana
        # value X") has no payload form yet, and dropping it would widen the
        # effect to every mana value — so the line refuses instead.
        raise LoweringError("a variable mana-value bound has no payload form", node=filt)
    return payload


#: The ``ObjectFilter`` fields ``to_payload`` actually reads. A narrowing
#: outside this set has no payload form at all, so it does not survive the trip
#: to the dispatcher — and the caller's "are all these keys testable?" check
#: cannot see the difference, because what is missing left no key behind.
#: Round 68 hit the same thing on the lowering side and paired the payload gate
#: with ``_restrictions_beyond`` over the AST; this is that pairing on the
#: *trigger* side, where the consequence is a condition that announces itself on
#: a strictly larger set than the card prints.
_PAYLOAD_HONOURED_FILTER_FIELDS = frozenset({
    "card_types", "type_match", "subtypes", "colors", "excluded_colors",
    "excluded_types", "excluded_subtypes", "with_keywords", "without_keywords",
    "controller", "tapped", "attacking", "blocking", "other_than_source",
    "nontoken", "named", "their_choice", "mana_value", "power", "toughness",
    "colored", "with_plus1_counter",
})


def _restrictions_beyond(
    filt: ast.ObjectFilter, honoured: frozenset[str]
) -> tuple[str, ...]:
    """Names of *filt*'s non-default fields that *honoured* does not cover.

    Written against the dataclass rather than a hand-listed tuple of the fields
    known today: a restriction added to ``ObjectFilter`` later is then refused
    by default, instead of being quietly ignored by every lowering that was
    written before it existed. Silently widening an effect is the failure mode
    worth engineering against — a card that refuses is visibly unsupported.
    """
    default = ast.ObjectFilter()
    return tuple(
        field.name
        for field in dataclasses.fields(filt)
        if field.name not in honoured
        and getattr(filt, field.name) != getattr(default, field.name)
    )


def chargeable_card_filter(filt: ast.ObjectFilter) -> dict | None:
    """The payload a printed **card** noun phrase means, or None to refuse it.

    The one gate both readers of a card phrase run through — the grammar, which
    decides whether to admit "Discard a land card or Shrine card" as a cost, and
    ``engine/oracle.py``, which reads the same clause into the cost that is
    actually charged. Two readers of one phrase drift, and the direction a cost
    drifts in is a cost charged more widely than the card prints; they do not
    drift when the answer comes from here.

    Three refusals, and each is a way the phrase could otherwise be silently
    widened:

    * no printed "card" — "discard a land" is a phrase about permanents, and the
      card matcher answers a different question about a different kind of object;
    * a restriction with no payload key at all, so it would leave nothing behind
      for the key check to see ("a **legendary** card" reduces to "a card");
    * a payload key ``_card_matches_filter`` cannot answer, which would be
      dropped where it is tested.

    ``to_payload`` directly rather than ``_filter_payload``: that wrapper refuses
    a card-scoped filter on purpose, because every handler it feeds searches the
    battlefield. Here the card scope is the point.
    """
    from ...subject_filters import card_only_filter

    if not filt.is_card:
        return None
    # ``is_card`` is read on the line above rather than dropped, so it counts as
    # honoured in the sense this check means.
    if _restrictions_beyond(filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card"}):
        return None
    return card_only_filter(filt.to_payload())


# Payload keys no EFFECT_HANDLERS entry reads. They are additive *descriptions*
# of what a line targets, kept so the engine can answer "what does this spell
# target?" from the compiled program instead of re-reading oracle text
# (engine/targeting.py replacing engine/legality.py) — they decide which
# permanents the picker offers, not what the resolution does.
#
# They existed to be subtracted: the grammar-vs-legacy differential compared
# payloads with these removed, since a key the legacy rules never produced would
# otherwise have read as a divergence on every migrated card. That comparison is
# gone, and so is the subtraction everywhere it mattered —
# scripts/parse_coverage.py's deletion probe now compares whole payloads, which
# is what makes it able to see "target **attacking** creature" differing from
# "target creature". What is left is engine.grammar.behavioural_payload, used by
# the lowering goldens.
GRAMMAR_ONLY_PAYLOAD_KEYS = frozenset({"targets"})


def _describe_targets(payload: dict[str, object], recipient: ast.Recipient) -> None:
    """Record what *recipient* refers to on *payload*, if it names a target."""
    described = _targets_payload(recipient)
    if described is not None:
        payload["targets"] = described


def _targets_only(recipient: ast.Recipient) -> dict[str, object]:
    """A payload carrying nothing but the target description — for handlers
    whose behaviour takes no filter but whose *card* still targets."""
    payload: dict[str, object] = {}
    _describe_targets(payload, recipient)
    return payload


def _describe_several_targets(payload: dict[str, object], recipient: ast.TargetSpec) -> None:
    """Record an "up to N target …" description, N > 1, on *payload*.

    Separate from :func:`_describe_targets` and opted into per call site, which
    is the whole safety of it. Most lowerings emit an instruction whose handler
    resolves exactly one permanent; if the ordinary description quietly admitted
    several, ``engine/targeting.py`` would raise a two-target picker in front of
    a one-target handler and the second choice would be collected and dropped.
    So a lowering says "my handler reads a list" by calling *this*, and
    :func:`_names_several_targets` keeps refusing everywhere else.
    """
    if not recipient.targeted:
        # "Up to four lands" (Rewind) prints no "target": nothing is chosen at
        # cast, so describing it here would raise a cast-time picker in front
        # of a choice CR says is made on resolution.
        raise LoweringError(
            "this 'up to N' names no targets; the choice belongs to resolution",
            node=recipient,
        )
    payload["targets"] = {
        "quantifier": recipient.quantifier,
        "kind": "object",
        "filter": _filter_payload(recipient.filter),
        # The maximum, not the count chosen — "up to two" may legally name one
        # or none (CR 601.2c).
        "count": recipient.count,
    }


def _describe_several_card_targets(
    payload: dict[str, object], recipient: ast.TargetSpec
) -> None:
    """Record an "up to N target <type> card(s)" description, N > 1, where the
    targets are **cards in another zone** rather than permanents.

    A sibling of :func:`_describe_several_targets` rather than a branch in it,
    because the two cannot share a body: that one describes its filter through
    :func:`_filter_payload`, which **refuses** a card or a non-battlefield zone
    outright, and for a good reason - a filter payload has no way to say "in
    your graveyard", so emitting one would point the picker at the battlefield
    for an effect that reads a graveyard.

    The shared *key* is deliberate: ``targets["count"] > 1`` is the one query
    that finds every several-target instruction in a compiled program
    (``engine/ai_valuation.py`` walks for exactly that), so a card-shaped one
    filed under a different key would be invisible to it.
    """
    if not recipient.targeted:
        raise LoweringError(
            "this 'up to N' names no targets; the choice belongs to resolution",
            node=recipient,
        )
    payload["targets"] = {
        "quantifier": recipient.quantifier,
        "kind": "card",
        # No filter, deliberately. What the cards may be is already on the
        # instruction's own payload, which is what the handler and the spec
        # function both read; a second copy here could disagree with it, and
        # nothing would say which one won.
        #
        # The maximum, not the count chosen - "up to two" may legally name one
        # or none (CR 601.2c).
        "count": recipient.count,
    }


def _targets_payload(recipient: ast.Recipient) -> dict[str, object] | None:
    """A description of what *recipient* refers to, for engine/targeting.py.

    Only the shapes that name a cast-time target are described. "You" and
    "each player" are not targets at all (CR 115.10b), so they get no entry
    rather than a misleading one.
    """
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind == "target_player":
            if recipient.or_planeswalker:
                # "target player or planeswalker" — one chosen slot answered by
                # a player face or a planeswalker permanent, the "any target"
                # resolution shape minus the creature half.
                return {"quantifier": "target", "kind": "player_or_planeswalker"}
            return {"quantifier": "target", "kind": "player"}
        if recipient.kind == "target_opponent":
            # "Target opponent" is a player target the caster's own seat cannot
            # answer (CR 115.4) — the same flag the phase-out sweep and Word of
            # Command's spec carry, so every player picker reads one vocabulary.
            return {"quantifier": "target", "kind": "player", "opponents_only": True}
        return None
    if not isinstance(recipient, ast.TargetSpec):
        return None
    if recipient.quantifier == "any_target":
        return {"quantifier": "any_target", "kind": "any"}
    if not _is_target(recipient):
        return None
    filt = recipient.filter
    if recipient.distinct_from_prior:
        # "**Another** target creature" as the *only* chosen object of its
        # sentence (Selfless Savior). The word names a distinctness — CR 601.2c
        # lets two instances of "target" name the same object unless something
        # forbids it — and the referent it must differ from is whatever the
        # sentence chose earlier. Here nothing did: this description is reached
        # only from a statement whose targets are this one, because the
        # multi-clause case is refused above it (`_refuse_unfused_distinctness`)
        # and the two lowerings that can honour a per-clause distinctness
        # (`_fused_two_target_pump`, `target_bites_target`) build their own
        # description and never call this. So the only object left in the
        # sentence for "another" to exclude is the ability's source (CR 109.5),
        # which is exactly what `other_than_source` says — the same restriction
        # printed a second way, and the spelling `parse_target_spec` already
        # produces for "up to two **other** target creatures".
        #
        # Written as a filter rewrite rather than a payload key so it goes
        # through `_filter_payload` like every other narrowing, and so the picker
        # (`_narrowing_flags` -> `exclude_source`) and the handlers read one key.
        filt = dataclasses.replace(filt, other_than_source=True)
    # The quantifier is carried rather than written as the constant "target":
    # "up to one target creature" may legally choose nothing (CR 601.2c) while
    # a plain "target" must be answered, and a picker reading this key can tell
    # them apart. Collapsing both would make the description lie.
    return {
        "quantifier": recipient.quantifier,
        "kind": "object",
        "filter": _filter_payload(filt),
    }


def _amount_payload(amount: ast.Amount) -> int | str:
    """Legacy payloads carry a plain int, or the string "x" for a variable."""
    if isinstance(amount, ast.Fixed):
        return amount.value
    if isinstance(amount, ast.Var):
        return amount.name
    raise LoweringError(f"unsupported quantity {type(amount).__name__}", node=amount)


# What a bare "that much" names when the effect is a *triggered ability*: the
# quantity the firing event carried, frozen into the trigger's context by the
# fire site. Keyed by trigger-condition kind, and deliberately a table rather
# than a rule — an event either carries a number or it does not, and a kind
# absent here refuses the back-reference instead of reading a zero out of an
# empty context. (El-Hajjâj's "whenever this creature deals damage, you gain
# that much life" is still not here: its fire site records the amount under a
# different key, so claiming its line would retire a hook onto a handler
# reading the wrong name — a change to make deliberately rather than by adding
# a row.)
_EVENT_QUANTITIES: dict[str, str] = {
    "you_gain_life": "life_gained",
    # "Whenever this creature **is dealt damage**, it deals that much damage to
    # target opponent." (Brash Taunter.) The number is frozen by the fire site,
    # because by resolution the marked damage may have been added to or wiped.
    "creature_dealt_damage": "damage_dealt",
}

# The scratchpad keys that are *quantities*. `lower._PRODUCES` also records
# things no amount can read — a controller's seat, a list of exiled cards — so
# a bare back-reference resolves against this narrower set. A producer added
# there and not here fails safe: the bare reading refuses rather than reading a
# number out of something that is not one.
_PRODUCED_QUANTITIES: frozenset[str] = frozenset({"damage_dealt"})


def _back_reference_payload(
    amount: ast.ThatMuch,
    produced: frozenset[str],
    event: str | None,
) -> dict[str, object]:
    """Where a handler should read *amount* from, as payload keys.

    ``amount_from`` is a key in this resolution's scratchpad (an earlier step of
    the same effect recorded it); ``amount_from_trigger`` is a key in the firing
    event's captured context. Which one applies is decided here, once, rather
    than by each effect family guessing — reading a trigger's number out of the
    scratchpad silently yields zero, which is the failure this refuses on
    behalf of every caller.
    """
    if amount.source is not None:
        # The words named the producer ("equal to the damage dealt"), so a step
        # of this same effect has to have recorded it.
        if amount.source in produced:
            return {"amount_from": amount.source}
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this effect",
            node=amount,
        )
    key = _EVENT_QUANTITIES.get(event or "")
    if key is not None:
        return {"amount_from_trigger": key}
    within = tuple(sorted(produced & _PRODUCED_QUANTITIES))
    if len(within) == 1:
        return {"amount_from": within[0]}
    raise LoweringError(
        "bare back-reference with no producer in this effect and no quantity "
        "on its trigger",
        node=amount,
    )


def _is_source(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_source


def _is_enchanted(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_enchanted


def _names_several_targets(subject: ast.Recipient) -> bool:
    """Whether *subject* names more than one chosen target.

    One definition, because "up to two" and "up to four" are the same shape and
    the number is the only thing separating Frost Breath from Twiddle. The
    lowerings that could previously read an ``up_to`` subject dropped ``count``
    on the floor and emitted a single-target instruction — so Rewind untapped
    *one* land of up to four and reported itself supported. A refusal naming
    the gap is the honest answer until a handler resolves a list of targets.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "up_to"
        and subject.count > 1
    )


def _is_target(subject: ast.Recipient) -> bool:
    """Whether *subject* names exactly **one** chosen target.

    "Up to one" qualifies: it picks a single target or none, which is what
    every handler reading ``context.target_permanent_id`` already does. "Up to
    two" does not, and must not — see :func:`_names_several_targets`.
    """
    if not isinstance(subject, ast.TargetSpec):
        return False
    if subject.quantifier == "target":
        return True
    return subject.quantifier == "up_to" and not _names_several_targets(subject)


def _is_you(recipient: ast.Recipient) -> bool:
    return isinstance(recipient, ast.PlayerRef) and recipient.kind == "you"


# ---------------------------------------------------------------------------
# Power / toughness
# ---------------------------------------------------------------------------


def _signed(amount: ast.Amount, negative: bool) -> int | str:
    value = _amount_payload(amount)
    if negative and isinstance(value, int):
        return -value
    if negative:
        raise LoweringError("negative variable pump is not supported", node=amount)
    return value


# A continuous effect with no duration is refused, but *why* differs by subject,
# and the difference is the whole point: for most of these the engine is already
# applying the effect somewhere else, so "waiting on the layers engine" was the
# wrong answer. Naming the real owner is what keeps the backlog honest — and
# what stops someone lowering one of them on the assumption that nothing runs it.
def _durationless_reason(subject) -> str:
    if _is_enchanted(subject):
        # Unreachable in practice: engine/grammar/registries.py claims these
        # lines before any effect production sees them. Kept correct anyway, so
        # a wording that slips past the claim reports the right owner.
        return "an Aura's continuous grant is derived by engine/auras.py"
    return "continuous pump needs the CR 613 layers engine"


_MANA_KEYS = ("W", "U", "B", "R", "G", "C")


def _full_mana_payload(cost: ast.ManaCost) -> dict[str, int]:
    """The mana dict the upkeep handlers read: every colour present, zeroed,
    plus `generic`. They index it directly, so a sparse dict would KeyError."""
    pips = dict(cost.pips)
    payload = {key: int(pips.get(key, 0)) for key in _MANA_KEYS}
    payload["generic"] = int(pips.get("generic", 0))
    return payload

# Durations meaning "for the rest of this turn". Both handlers below set a flag
# listed in engine/mixins/_constants.py's _EOT_METADATA_KEYS, which is cleared
# in the cleanup step — so these two wordings are the same effect, and any other
# duration (or none) is not.
_REST_OF_TURN = ("this_turn", "until_end_of_turn")


# The zones a count can be taken over, and what may narrow it there. On the
# battlefield the ordinary object filter applies, because the counter asks
# `permanent_matches_filter` — the same question every target of the same words
# asks. In any other zone the objects are *cards*, which have no computed
# characteristics at all, so only the printed type union and a card's name are
# testable and anything else refuses rather than being counted as if it were
# not there.
# "the number of cards in their library" (Peer into the Abyss). The evaluator
# reads the zone off the owner by name, so the library needed no counting code —
# only saying so here. It is listed last because it is the one zone whose count a
# player cannot see, which changes nothing about the arithmetic and everything
# about what a *picker* built on the same spec could offer.
_COUNTABLE_ZONES = ("battlefield", "graveyard", "hand", "exile", "library")
_CARD_ZONE_KEYS = frozenset({"type_filter", "named"})


def halved_count_spec(amount: "ast.Amount", node) -> dict | None:
    """The spec for a computed amount that may be halved, or None if it is not one.

    "Half the number of cards in their library" and "half their life" (Peer into
    the Abyss) are the same shape: something the resolution computes, divided,
    and rounded. So the halving rides on the *spec* rather than becoming a second
    amount vocabulary — one evaluator still answers, which is the rule round 64
    wrote down when the pump handler was found carrying its own counter.

    A player's life total is not a pile to scan, so it arrives as a *named* board
    count rather than a filter: ``evaluate_count`` maps the name onto the one
    thing that computes it and answers 0 for a name it has no computation for,
    which is why the name is minted here and nowhere else.
    """
    rounding = None
    if isinstance(amount, ast.Half):
        rounding = amount.rounding
        amount = amount.of
    if isinstance(amount, ast.CountOf):
        spec = count_spec(amount.filter, node)
    elif isinstance(amount, ast.BoardCount) and amount.name == "their_life":
        spec = {"board_count": "their_life", "owner": "target"}
    else:
        return None
    if rounding is not None:
        spec["half"] = rounding
    return spec


def count_spec(filt: "ast.ObjectFilter", node, *, aggregate: str = "count") -> dict:
    """What ``count_from_payload`` needs to take this count at resolution.

    One reader for both callers — the where-clause that *defines* an X and the
    amount that *is* one ("draw cards equal to the number of …"). They ask the
    same question of the same noun phrase, so a restriction one of them refused
    and the other silently dropped would be the same count meaning two things.
    """
    if filt.zone not in _COUNTABLE_ZONES:
        raise LoweringError(f"no count reads the {filt.zone}", node=node)
    payload = dict(filt.to_payload())
    if filt.zone != "battlefield" and set(payload) - _CARD_ZONE_KEYS:
        raise LoweringError(
            f"a {filt.zone} count cannot test {sorted(set(payload) - _CARD_ZONE_KEYS)}",
            node=node,
        )
    # Whose objects are counted is the *zone owner*, and the counter reads it
    # off there. A filter narrowing by controller as well ("the number of
    # Mountains **they** control") is asking a question the count cannot answer
    # — `permanent_matches_filter` does not test a controller, so the key would
    # be handed over and silently ignored, and the count taken on the wrong
    # player's battlefield. Refused rather than dropped.
    controller = payload.pop("controller", None)
    if controller not in (None, "you"):
        raise LoweringError(
            f"a count cannot be narrowed to the {controller}'s permanents", node=node
        )
    spec: dict = {
        "zone": filt.zone,
        "owner": (filt.zone_owner.kind if filt.zone_owner else "you"),
        "filter": payload,
    }
    # Omitted when it is the default, so every spec written before aggregates
    # existed is byte-identical.
    if aggregate != "count":
        spec["aggregate"] = aggregate
    return spec


def _lower_condition(
    condition: ast.Condition, produced: frozenset[str] = frozenset()
) -> dict[str, object]:
    """*produced* names the scratchpad values earlier steps of this same effect
    recorded. It defaults to empty, which is what refuses a coin-flip condition
    on an intervening-if (CR 603.4): that condition is checked when the trigger
    would fire, where no flip of this resolution can have happened yet."""
    if isinstance(condition, ast.CoinFlipResult):
        # A back-reference names its producer or refuses (round 33). Without a
        # flip earlier in the same effect there is nothing to read, and
        # `evaluate_condition` would quietly answer False — so a card printing
        # only "If you win the flip, …" would compile supported and do nothing.
        if "coin_flip" not in produced:
            raise LoweringError(
                "'the flip' with no coin flip before it in this effect",
                node=condition,
            )
        return {"kind": "coin_flip", "won": condition.won}
    if isinstance(condition, ast.RevealedCardIs):
        # The pronoun's referent again, and the same discipline: a reveal
        # earlier in this same effect has to have recorded what it showed, or
        # there is nothing for "it" to name and the branch would answer False
        # forever while the card compiled clean (idiom #7).
        if "revealed_card" not in produced:
            raise LoweringError(
                "'it' with nothing in this effect that revealed a card",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the revealed-card test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.card_types:
            raise LoweringError(
                "'it's …' reads a card's printed type line", node=condition
            )
        return {
            "kind": "revealed_card_is",
            "card_types": list(condition.filter.card_types),
            "type_match": condition.filter.type_match,
        }
    if isinstance(condition, ast.ItWas):
        # The pronoun's referent, resolved here because only here is the
        # sentence in front of it known. One producer answers it today — the
        # card an exile step of this same effect took out of a graveyard — and
        # a second producer means a second key, never this one widened, for the
        # reason `amount_from` and `amount_from_trigger` are two keys.
        if "exiled_cards" not in produced:
            raise LoweringError(
                "'it' with nothing in this effect that named what it moved",
                node=condition,
            )
        leftover = _restrictions_beyond(
            condition.filter, {"card_types", "is_card", "type_match"}
        )
        if leftover:
            raise LoweringError(
                "the last-known-information test cannot ask this of a card: "
                + ", ".join(leftover),
                node=condition,
            )
        if not condition.filter.is_card or not condition.filter.card_types:
            raise LoweringError(
                "'it was …' reads a card's printed type line", node=condition
            )
        return {
            "kind": "exiled_card_was",
            "card_types": list(condition.filter.card_types),
        }
    if isinstance(condition, ast.Controls):
        payload = {
            "kind": "controls",
            "who": condition.who.kind,
            "filter": condition.filter.to_payload(),
        }
        if condition.comparison is not None and isinstance(condition.comparison.value, ast.Fixed):
            payload["count"] = condition.comparison.value.value
            payload["op"] = condition.comparison.op
        if condition.shared_name:
            # The threshold is what the relation is *for*: "permanents with the
            # same name as one another" with no number would be read as
            # "count > 0" downstream and hold for a single permanent, which is
            # the opposite of what the words say. No card prints it that way, so
            # it refuses rather than picking a number the text did not print.
            if "count" not in payload:
                raise LoweringError(
                    "'with the same name as one another' needs the printed "
                    "threshold it qualifies",
                    node=condition,
                )
            payload["shared_name"] = True
        return payload
    if isinstance(condition, ast.IsState):
        return {"kind": "is_state", "state": condition.state, "negated": condition.negated}
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    if isinstance(condition, ast.ReturnedToHandThisTurn):
        return {"kind": "returned_to_hand_this_turn"}
    if isinstance(condition, ast.HadPlus1Counter):
        return {"kind": "had_plus1_counter"}
    if isinstance(condition, ast.LifeGainedThisTurn):
        # The seat rides the payload rather than being baked into the kind, so
        # "if an opponent gained…" is the same condition with a different `who`
        # the day a card prints it.
        return {
            "kind": "life_gained_this_turn",
            "who": condition.who.kind,
            "amount": condition.amount,
        }
    raise LoweringError(f"no lowering for condition {type(condition).__name__}", node=condition)
