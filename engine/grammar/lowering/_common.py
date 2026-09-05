"""Payload shapes and small values every lowering family needs.

The bottom of the lowering layer. Target descriptions, amount encoding, the
`_is_source` / `_is_you` subject predicates, and two values that are here for a
specific reason rather than by taxonomy: `_full_mana_payload` (with
`_MANA_KEYS`) and `_REST_OF_TURN`.

What a *filter* means is `_filters` beside this file, which crossed the
thousand-line guard at Visions' Phase 0. The split is by question: this module
is what a **target description** looks like, that one is which narrowings of a
noun phrase survive into a payload at all. Every name it defines is re-exported
below, so no family imports it directly.

Those two were the *only* references crossing between lowering families — an
"unless they pay" cost is wanted by damage, the board and cards; a
rest-of-turn duration by damage and combat. A fragment several families need is
not one family's property, and leaving it in one is what couples the rest to it.

`GRAMMAR_ONLY_PAYLOAD_KEYS` is here too, since it describes payloads rather
than any one effect.

What a *trigger's* back-reference names — "that much", "that player", the tables
keyed by condition kind — was here for the same reason and is now `_events`
beside this file, which crossed the thousand-line guard. The split is by
question: this module is the shape a payload takes, that one is what the firing
event froze.
"""

import dataclasses

from .. import ast
from ..errors import LoweringError

from ._filters import (_PAYLOAD_HONOURED_FILTER_FIELDS, _filter_payload,
                       _restrictions_beyond, chargeable_card_filter,
                       chargeable_tap_filter, dropped_narrowings,
                       is_mana_value_x, refuse_untestable,
                       testable_filter_payload)


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


def divided_target_description(
    type_filter: str, *, max_targets: int | None = None
) -> dict[str, object]:
    """The ``targets`` description a distributed effect carries (CR 601.2d).

    Here rather than in the family that builds it because four readers share
    the shape and none of them is a lowering: the casting path's announcement
    gate, ``targeting.py``'s picker, ``divided_damage.divided_description`` and
    the handler. A second spelling of these keys is a picker that offers what
    the gate refuses.

    *max_targets* is CR 601.2c's printed ceiling on a variable target count
    ("among **one or two** target creatures") and is omitted entirely when the
    card prints "any number of" — an absent key is the unbounded sentence, so a
    reader written before the bound existed keeps meaning what it meant.
    """
    described: dict[str, object] = {
        "quantifier": "divided",
        "kind": "divided",
        "division": "chosen",
        "filter": {"type_filter": type_filter},
    }
    if max_targets is not None:
        described["max_targets"] = max_targets
    return described


def _describe_targets(
    payload: dict[str, object],
    recipient: ast.Recipient,
    *,
    carried_separately: frozenset[str] = frozenset(),
) -> None:
    """Record what *recipient* refers to on *payload*, if it names a target.

    *carried_separately* travels through to ``_filter_payload``: a lowering that
    lifts a narrowing out of the filter into its own key has to say so **here**
    too, or the description it builds of the same noun phrase refuses the phrase
    the instruction beside it accepts.
    """
    described = _targets_payload(recipient, carried_separately=carried_separately)
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
        # or none (CR 601.2c). "X target lands" (Candelabra of Tawnos) carries
        # the string instead: the number is the announced X, resolved where
        # every other computed amount is, and a literal 0 here would show a
        # picker that offers nothing.
        "count": "x" if recipient.count_from_x else recipient.count,
    }
    if recipient.quantifier in ("one_or_more", "any_number"):
        # No printed maximum, so the cap is however many legal targets there
        # are — a number that only exists once the picker has enumerated them
        # (engine/legality.py fills it in as an ordinary `max_targets`). A
        # `count` of 0 here would otherwise read as "no targets" and show a
        # picker that offers nothing.
        #
        # Both quantifiers, because the maximum is the same question for each.
        # Their *minimum* is not — "any number of" (Energy Arc) may name none
        # and "one or more" (Heaven's Gate and its four colour siblings) may
        # not — and nothing here or downstream carries a floor: there is no
        # `min_targets` in the engine, so the five "one or more" cards already
        # shipped may legally be cast naming nothing. That is a pre-existing
        # looseness this widening inherits rather than one it introduces, and
        # it is the only shape where "any number of" is not simply the more
        # permissive twin.
        payload["targets"]["unbounded"] = True


#: A printed relation whose *other end is itself a target*, and the key the
#: dependent role carries to say which role answers it.
#:
#: "target creature that **target Wall** blocked this turn" (Glyph of Delusion)
#: names two targets of different kinds in one noun phrase: the creature the
#: effect acts on, and the Wall whose block record decides which creatures are
#: legal at all. The relation cannot be a plain filter key — ``subject_matches``
#: answers about one permanent, and this one is answered by a *record on the
#: other target* — so the two are described as ordered **roles** instead
#: (:func:`describe_target_roles`), and this table is what makes that shape
#: general: a second such relation is a row here, not a second builder.
#: Keyed by the ``ObjectFilter`` field, valued by the *name* the other end takes
#: as a role and the key the dependent role points back with.
DEPENDENT_TARGET_RELATIONS: dict[str, tuple[str, str]] = {
    "blocked_by_target_object": ("blocker", "blocked_by_role"),
}

#: The role name of the object a roles description's effect actually acts on.
#: One name, read by the lowering that builds the description, by
#: ``engine/targeting.py``'s spec, by ``engine/legality.py``'s enumerator and by
#: the handler at resolution — so "which of the two did the player pick for the
#: counters?" has one answer rather than four positional conventions.
PRIMARY_TARGET_ROLE = "subject"


def describe_target_roles(
    payload: dict[str, object], recipient: ast.TargetSpec
) -> bool:
    """Describe *recipient* as ordered target **roles**, or return False.

    True when the noun phrase named a second target inside itself — one of
    :data:`DEPENDENT_TARGET_RELATIONS` — and the description was written onto
    *payload*; False when it did not, so the caller falls through to the
    ordinary one-target description it already had.

    **The roles are listed in dependency order, not printed order.** Glyph of
    Delusion prints the creature first and the Wall second, but which creatures
    are legal at all is decided by the Wall's block record, so the Wall is role
    0 and the creature role 1. That order is the whole wire convention: the
    picker walks the roles in it, the caster's answers travel in it, and
    ``engine/legality.py`` enumerates role *n* only with roles 0…n-1 already
    settled. Describing them in printed order would ask the caster for a
    creature before anything could say which creatures the card allows.
    """
    filt = recipient.filter
    relation = next(
        (
            field
            for field in DEPENDENT_TARGET_RELATIONS
            if getattr(filt, field, None) is not None
            and not isinstance(getattr(filt, field), bool)
        ),
        None,
    )
    if relation is None:
        return False
    role_name, role_key = DEPENDENT_TARGET_RELATIONS[relation]
    inner = getattr(filt, relation)
    inner_payload = _filter_payload(inner)
    subject_payload = _filter_payload(
        filt, carried_separately=frozenset({relation})
    )
    if not inner_payload or not subject_payload:
        raise LoweringError(
            "a target role with no narrowing would offer every permanent",
            node=recipient,
        )
    payload["targets"] = {
        "kind": "roles",
        "roles": [
            {
                "role": role_name,
                "kind": "object",
                "count": 1,
                "filter": inner_payload,
            },
            {
                "role": PRIMARY_TARGET_ROLE,
                "kind": "object",
                "count": 1,
                "filter": subject_payload,
                role_key: role_name,
            },
        ],
    }
    return True


def describe_independent_target_roles(
    payload: dict[str, object], specs: "tuple[ast.TargetSpec, ...]"
) -> None:
    """Describe several targeted phrases of **one** announcement as ordered roles.

    "Destroy target creature **and target land**." (Fumarole.) The sibling of
    :func:`describe_target_roles` with the dependency taken out: there the
    second slot's legal set is decided by what was chosen for the first, and
    here the two phrases narrow nothing but themselves. Same shape, because it
    is the same question — a spell whose slots are *differently* restricted, so
    the picker has to walk them in order and ask for each one separately
    (CR 601.2c chooses every target as part of one announcement).

    The role name is the printed noun, which is what the picker shows the
    caster ("Choose the land for Fumarole (2 of 2)"). Two slots naming the same
    noun refuse: "target creature and target creature" is "two target
    creatures", a homogeneous count this shape would describe as two pickers
    over one list and then be unable to tell apart at resolution.

    A phrase with no type at all refuses for the same reason
    :func:`describe_target_roles` refuses an unnarrowed role — a slot offering
    every permanent is a slot the caster cannot be asked a meaningful question
    about, and its name would collide with the next such slot.
    """
    roles: list[dict[str, object]] = []
    for spec in specs:
        filter_payload = _filter_payload(spec.filter)
        # "Destroy target **Plains** and target white creature." (Reign of
        # Chaos.) The printed noun of a slot is not always a card type: a
        # subtype names one just as well, and it is the word the caster is
        # asked for. The type is preferred where both are printed ("target
        # Griffin **creature**"), because that is the head of the phrase.
        #
        # A fallback rather than a second reader: the role name is only ever a
        # label and a key, and every narrowing the slot enforces is in the
        # filter beside it — which ``subject_matches`` tests by subtype exactly
        # as it tests by type.
        noun = filter_payload.get("type_filter") or filter_payload.get(
            "subtype_filter"
        )
        if not isinstance(noun, str):
            raise LoweringError(
                "a target role needs a printed noun to be asked for", node=spec
            )
        if any(role["role"] == noun for role in roles):
            raise LoweringError(
                f"two target roles both named {noun!r}", node=spec
            )
        roles.append({
            "role": noun,
            "kind": "object",
            "count": 1,
            "filter": filter_payload,
        })
    payload["targets"] = {"kind": "roles", "roles": roles}


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


def _targets_payload(
    recipient: ast.Recipient,
    *,
    carried_separately: frozenset[str] = frozenset(),
) -> dict[str, object] | None:
    """A description of what *recipient* refers to, for engine/targeting.py.

    Only the shapes that name a cast-time target are described. "You" and
    "each player" are not targets at all (CR 115.10b), so they get no entry
    rather than a misleading one.
    """
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind == "target_player":
            if recipient.attacked_this_turn:
                # "…**who attacked this turn**" (Fire and Brimstone). Carried
                # into the description the picker reads, because the picker is
                # what enforces it (engine/legality.py's seat loop). A
                # restriction the enumerator never sees is a restriction nobody
                # applies — and unenforced, the card hits any seat at all, which
                # is wrong in the caster's favour and silent.
                return {
                    "quantifier": "target", "kind": "player",
                    "attacked_this_turn": True,
                }
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
            #
            # "…**or planeswalker**" (Eternal Flame) widens the same slot the
            # same way it widens "target player" above, and the narrowing
            # survives it: the union is "a seat that is not mine, or a
            # planeswalker". A shared `player` answer dropped the word, which
            # silently deleted the planeswalker half of the card — the picker
            # offers exactly what this describes.
            described: dict[str, object] = {
                "quantifier": "target",
                "kind": (
                    "player_or_planeswalker" if recipient.or_planeswalker
                    else "player"
                ),
                "opponents_only": True,
            }
            if recipient.damaged_by_source:
                # "…**previously dealt damage by it**" (Diseased Vermin), for
                # the reason the attack narrowing one arm up is carried: the
                # picker enforces it, and a restriction the enumerator never
                # sees lets the ability hit any opponent at all.
                described["damaged_by_source"] = True
            return described
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
        "filter": _filter_payload(filt, carried_separately=carried_separately),
    }


def _amount_payload(amount: ast.Amount) -> int | str:
    """Legacy payloads carry a plain int, or the string "x" for a variable."""
    if isinstance(amount, ast.Fixed):
        return amount.value
    if isinstance(amount, ast.Var):
        return amount.name
    raise LoweringError(f"unsupported quantity {type(amount).__name__}", node=amount)


def _is_source(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_source


def _is_created_token(subject: ast.Recipient) -> bool:
    """Whether *subject* is "that token" — the one an earlier step made."""
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_created_token


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
        # "up to N target …" and "**N** target …" are the same shape to every
        # reader downstream; only the floor differs, and the floor is the
        # picker's business rather than the lowering's. "X target lands" has no
        # printed number at all, so its count is unknown here and it qualifies
        # on the quantifier alone.
        and (
            (subject.quantifier == "up_to" and subject.count > 1)
            or (subject.quantifier == "exactly"
                and (subject.count_from_x or subject.count > 1))
            # "One or more target creatures" prints no number at all, so it
            # qualifies on the quantifier alone — the same way "X target lands"
            # above does, and for the same reason: the count is not knowable
            # here, only that it can exceed one.
            #
            # "**Any number of** target creatures" (Energy Arc) is the same
            # shape one word over. The two differ only in their *floor* — CR
            # 601.2c lets "any number of" name none where "one or more" must
            # name one — and the floor is not what this predicate asks about.
            or subject.quantifier in ("one_or_more", "any_number")
        )
    )


def _is_target(subject: ast.Recipient) -> bool:
    """Whether *subject* names exactly **one** chosen target.

    "Up to one **target**" qualifies: it picks a single target or none, which
    is what every handler reading ``context.target_permanent_id`` already
    does. "Up to two" does not, and must not — see
    :func:`_names_several_targets`. Neither does an "up to one" that prints no
    "target" at all: the parser records the word (``TargetSpec.targeted``)
    because CR 115.1b makes the untargeted spelling a *resolution* choice, and
    answering it with a cast-time picker would be the same wider-than-printed
    reading :func:`_describe_several_targets` refuses for "up to four lands".
    """
    if not isinstance(subject, ast.TargetSpec):
        return False
    if subject.quantifier == "target":
        return True
    return (
        subject.quantifier == "up_to"
        and subject.targeted
        and not _names_several_targets(subject)
    )


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

#: How many cleanup steps a *stated-window* one-shot restriction survives, by
#: printed duration. One is every spelling of "this turn"; two is "this turn
#: and next turn" (Peace Talks). A count rather than a kind per phrase, because
#: what the sweep does with it is subtraction —
#: ``engine/phases/cleanup_step.py``'s ``_turn_expired``.
#:
#: Here rather than in one of the families that reads it: the blanket
#: can't-attack (``lowering/combat.py``) and the targeting ban
#: (``lowering/game.py``) are two families and neither may import the other, so
#: the table sits on the floor they share. Two copies would be two answers to
#: "how long is this turn and next turn", free to differ.
RESTRICTION_TURNS: dict[str, int] = {
    "this_turn": 1,
    "until_end_of_turn": 1,
    "this_turn_and_next_turn": 2,
}

#: The same pair one phase down: "this combat" and "until end of combat" are two
#: printed spellings of CR 511's window, and a shield or a grant that reads one
#: and refuses the other would be a card failing on its printing rather than on
#: its effect. Beside ``_REST_OF_TURN`` and not inside the prevention family,
#: for that constant's own stated reason.
_REST_OF_COMBAT = ("this_combat", "until_end_of_combat")




def _targeted_specs(node: object) -> tuple[ast.TargetSpec, ...]:
    """Every ``TargetSpec`` in *node*'s subtree that prints the word "target".

    Written against the dataclass fields rather than a per-node list, for the
    reason ``_restrictions_beyond`` gives: a statement class added later is then
    covered by default instead of silently answering "no targets here".
    """
    found: list[ast.TargetSpec] = []
    if isinstance(node, ast.TargetSpec):
        if node.targeted:
            found.append(node)
        # A filter carries no recipients, so there is nothing below this.
        return tuple(found)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            found.extend(_targeted_specs(getattr(node, field.name)))
    elif isinstance(node, (tuple, list)):
        for item in node:
            found.extend(_targeted_specs(item))
    return tuple(found)


def _refuse_unfused_distinctness(steps: tuple[ast.Statement, ...]) -> None:
    """Refuse a multi-clause sentence whose printed "another target" no fuser claimed.

    CR 601.2c lets two instances of the word "target" name the same object unless
    something forbids it, and ``TargetSpec.distinct_from_prior`` is that
    forbidding: "**another** target creature" must differ from the choice the
    sentence already made. Honouring it needs an instruction with a slot per
    clause — ``_fused_two_target_pump`` and ``target_bites_target`` are the two
    that have one — because every other handler resolves through ``_one_choice``
    and would read the *first* chosen permanent for both clauses.

    Reaching ``_lower_steps`` with the word still on a step therefore means two
    things at once: the clauses would land on one permanent, and
    ``_targets_payload`` would read the word as CR 109.5's source exclusion,
    which is a different restriction. Both are the wider-than-printed outcome, so
    the sentence refuses.

    Positioned **after** the fusers on purpose: a shape that grows a fused
    lowering later is claimed above this and never reaches it, so this refusal
    can only shrink as the engine learns more, never has to be edited.

    **The count that matters is of targets, not of clauses.** "This creature
    deals damage equal to its power to **another** target creature. That
    creature deals damage equal to its power to this creature." (Gargantuan
    Gorilla — Tracker's sentence with the word added.) Two clauses and *one*
    target: the second names its subject with a back-reference to what the
    first one chose, so there is no prior choice for "another" to differ from
    and the only object left in the sentence for it to exclude is the ability's
    source, which is CR 109.5 and exactly what ``_targets_payload`` turns it
    into one function above. Refusing on the clause count instead read the
    hazard off the wrong number — the hazard is two pickers reading one answer,
    which needs two printed targets to exist at all.
    """
    targeted = [spec for step in steps for spec in _targeted_specs(step)]
    if len(targeted) < 2:
        return
    for spec in targeted:
        if spec.distinct_from_prior:
            raise LoweringError(
                'a printed "another target" in a multi-clause sentence needs '
                "a lowering with a slot per clause",
                node=spec,
            )


#: What a ``who <did …>`` clause needs to be answerable, per
#: :class:`ast.PlayerDeed` kind: whether the clause names a noun phrase, and
#: what a handler reads the seats out of.
#:
#: A table rather than two branches for this package's usual reason — the rows
#: differ by two values and no structure — and because the *count* is the point:
#: a kind with no row here is one no handler was taught, and the refusal below
#: says so by name instead of letting a narrowing be dropped.
_PLAYER_DEEDS: dict[str, bool] = {
    # "…each player **who tapped a land for mana this turn**" (Desolation).
    # A seat's own per-turn record (``PlayerState``), so no noun phrase: the
    # clause names an action, and "a land" is part of the action's name rather
    # than a set the sentence narrows.
    "tapped_land_for_mana_this_turn": False,
    # "…each player **who sacrificed a Plains this way**" (Desolation). The
    # seat-keyed record an earlier step of this same resolution wrote, and the
    # noun phrase is what decides which of the given-up cards count — so it is
    # required rather than optional, because a "this way" clause with nothing to
    # test would be every seat that sacrificed anything.
    "sacrificed_this_way": True,
}


def player_deed_payload(player, node) -> "dict[str, object] | None":
    """The seat narrowing a ``who <did …>`` clause carries, or None when the
    reference prints no such clause.

    One reader for both of Desolation's sentences — the sacrifice its trigger
    performs and the damage that follows — so what "who" introduces cannot mean
    two things one line apart.

    **Raises rather than returns None** for a clause it cannot express. A seat
    narrowing that reaches a handler as nothing is a sentence acting on *every*
    player, which is silent and in the caster's favour; the whole reason these
    clauses are parsed only where a reader exists is to keep that impossible,
    and this is the second half of the same guarantee.

    The noun phrase is held to ``card_only_filter``: the record is a list of
    cards in a graveyard, which has no computed characteristics at all
    (CR 613.1), so a narrowing outside what a printed card can answer is
    refused instead of being handed to a matcher that would ignore it.
    """
    deed = getattr(player, "did", None)
    if deed is None:
        return None
    from ...subject_filters import card_only_filter

    wants_filter = _PLAYER_DEEDS.get(deed.kind)
    if wants_filter is None:
        raise LoweringError(
            f"no seat record answers {deed.kind!r}", node=node
        )
    payload: dict[str, object] = {"kind": deed.kind}
    if not wants_filter:
        if deed.filter is not None:
            raise LoweringError(
                f"the {deed.kind!r} narrowing names no objects", node=node
            )
        return payload
    if deed.filter is None:
        raise LoweringError(
            f"the {deed.kind!r} narrowing needs the noun phrase it counts",
            node=node,
        )
    described = card_only_filter(_filter_payload(deed.filter))
    if not described:
        raise LoweringError(
            "a seat record cannot test this restriction", node=node
        )
    payload["filter"] = described
    return payload
