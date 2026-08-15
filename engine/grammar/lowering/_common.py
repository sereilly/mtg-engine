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
    # The quantifier is carried rather than written as the constant "target":
    # "up to one target creature" may legally choose nothing (CR 601.2c) while
    # a plain "target" must be answered, and a picker reading this key can tell
    # them apart. Collapsing both would make the description lie.
    return {
        "quantifier": recipient.quantifier,
        "kind": "object",
        "filter": _filter_payload(recipient.filter),
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
# that much life" is the next entry this wants; its fire site records the
# amount under a different key, so it is a change to make deliberately rather
# than by adding a row.)
_EVENT_QUANTITIES: dict[str, str] = {
    "you_gain_life": "life_gained",
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
