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


def _filter_payload(
    filt: ast.ObjectFilter, *, carried_separately: frozenset[str] = frozenset()
) -> dict[str, object]:
    """A filter's payload, refusing shapes no handler implements.

    *carried_separately* names ``ObjectFilter`` fields the caller performs
    itself and therefore excuses from the dropped-narrowing check below — the
    same claim, in the same words, that ``subject_filters.object_only_filter``
    takes. Bronze Tablet's ownership half is the one such site: it lifts
    ``owner`` out of the payload into its own key, because the handler needs the
    ability's controller to answer "an opponent owns" at all. Naming the field
    at the call site is what keeps that from reading as a field nobody honours.

    It excuses ``their_choice`` from the refusal below for the same reason and
    with the same claim: the caller performs the choice rather than testing it.
    """
    payload = filt.to_payload()
    # `to_payload` cannot express a zone, so every handler reached through here
    # searches the battlefield. Emitting a graveyard-scoped filter as a plain
    # one would point the handler — and engine/targeting.py's picker — at the
    # wrong zone entirely, so the whole line is refused instead. Effects that
    # genuinely move cards between zones read the filter directly.
    if filt.zone != "battlefield" or filt.is_card:
        raise LoweringError(
            f"no handler reads a filter scoped to the {filt.zone}", node=filt
        )
    dropped = tuple(
        field for field in dropped_narrowings(filt, payload)
        if field not in carried_separately
    )
    if dropped:
        raise LoweringError(
            f"{', '.join(dropped)} has no payload form here", node=filt
        )
    # "of their choice" says *who picks*. No matcher can test it — it is
    # deliberately outside ``TESTABLE_SUBJECT_FILTER_KEYS`` — so a payload
    # carrying it into a handler is a key nothing reads, and the phrase is then
    # silently the ability's controller picking.
    #
    # ``to_payload`` emits the word precisely so a gate can *see* it, and the
    # gates that look are the ones asking "are all these keys testable?".
    # Several lowerings ask no such gate, which is how The Abyss shipped with
    # ``their_choice`` in its payload and the affected player never asked. So
    # the refusal is here instead, at the one place every filter payload is
    # built: a lowering whose own rule puts the choice somewhere names the
    # field in *carried_separately* and lifts it off (``_lower_sacrifice``,
    # CR 701.21a; the destroy's ``choose_permanent`` decomposition), and
    # everywhere else the word refuses — which is what ``board``'s comment has
    # claimed since Run Afoul landed and nothing enforced.
    if payload.get("their_choice") and "their_choice" not in carried_separately:
        raise LoweringError(
            "'of their choice' has nothing here to ask the player", node=filt
        )
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
    "card_types", "type_match", "subtypes",
    # "all **Sand Warriors**" (Hazezon Tamar) — the conjunction two adjacent
    # subtypes make, which ``to_payload`` emits as ``subtype_filter_all``. It
    # was missing from this set while its two neighbours ``subtypes`` and
    # ``type_match`` were both here, so every lowering that asked
    # ``_restrictions_beyond`` refused a two-subtype noun phrase as an
    # unhonoured field — a false refusal rather than a silent drop, but a
    # refusal of a phrase the payload carries perfectly well.
    "subtype_match",
    "colors", "excluded_colors",
    # "a **black or artifact** creature" (Soldevi Adnate). ``to_payload``
    # emits it unconditionally and ``permanent_matches_filter`` tests it, so
    # it is honoured in exactly the sense ``colors`` beside it is — and left
    # out, every lowering asking ``_restrictions_beyond`` refused a phrase the
    # payload carries perfectly well.
    "any_classes",
    "excluded_types", "excluded_subtypes", "with_keywords", "without_keywords",
    "controller", "tapped", "attacking", "blocking", "other_than_source",
    # "a creature **that has been dealt damage this turn**" (Giant Shark).
    # ``to_payload`` emits it as ``dealt_damage_this_turn``; its agent-naming
    # sibling ``dealt_damage_to_source_this_turn`` is deliberately absent, being
    # a relation no payload key carries.
    "was_dealt_damage_this_turn",
    # ``token_only`` beside ``nontoken``: ``to_payload`` emits both
    # unconditionally and ``permanent_matches_filter`` tests both, so a phrase
    # naming a token ("a Caribou token", Caribou Range) was refused as an
    # unhonoured field while its negation went through.
    "nontoken", "token_only",
    "named", "their_choice", "mana_value", "power", "toughness",
    "colored", "with_plus1_counter", "supertypes", "excluded_supertypes",
    "not_enchanted",
    "enchanted_only",
    # "…tapped this turn to pay for its abilities" (Vodalian War Machine).
    # ``to_payload`` emits it unconditionally and ``subject_matches`` tests it,
    # so it is honoured in the same sense every state word here is — what it
    # additionally needs is the ability's source, which that function takes.
    "tapped_to_pay_for_source_this_turn",
    "other_than_attached_host",
    "attached_to_filter",
    # "…**whose controller controls an Island**" (Seasinger). ``to_payload``
    # emits it unconditionally, and ``subject_filters.subject_matches`` is what
    # answers it — a seat's whole board, so the pure matcher cannot and the
    # gate downstream is what decides whether a given caller may carry it.
    "controller_controls",
    # "all creatures **banded with it**" (Icatian Skirmishers). ``to_payload``
    # emits it unconditionally and ``subject_matches`` tests it, exactly as it
    # does ``blocked_by_source`` — so it is honoured rather than relative.
    "banded_with_source",
    # "target permanent you both **own** and control" (Obelisk of Undoing) /
    # "all Auras **you own** attached to permanents you control" (Remove
    # Enchantments). ``to_payload`` reads it unconditionally. It used to emit
    # only alongside ``controller`` — the one card printing ownership printed
    # both words — and so needed a row in the conditional table below; the
    # second card prints ownership *without* control, and under that pairing
    # its narrowing was dropped rather than refused.
    "owner",
})


#: ``ObjectFilter`` fields ``to_payload`` emits **conditionally** — set on the
#: AST but not always present in the payload — mapped to the key they emit.
#:
#: The pair is the whole point. ``_restrictions_beyond`` asks "is this field
#: honoured at all?" and answers yes for every one of these, because each is
#: honoured *sometimes*; the payload key check downstream asks "is every key
#: testable?" and sees nothing, because a field that emitted nothing left no key
#: to inspect. A narrowing falls between the two questions and is dropped in
#: silence, which for a filter means an effect reaching further than the card
#: prints.
#:
#: It was a hand-written line for ``mana_value`` alone. ``power`` and
#: ``toughness`` emit under exactly the same condition (a literal bound rides,
#: a variable one does not) and had no such line, so "with power X or greater"
#: dropped its bound; ``supertypes`` joined them in round 108. One table, asked
#: by all three gates, is why the next such field cannot repeat it.
CONDITIONALLY_EMITTED_FIELDS: dict[str, str] = {
    "mana_value": "mana_value",
    "power": "power",
    "toughness": "toughness",
    "supertypes": "supertypes",
    # The two source-relative narrowings ``to_payload`` *never* emits
    # ("blocking or blocked by this creature", "that dealt damage to it this
    # turn"). Listing them here is what makes ``_filter_payload`` refuse the
    # phrase by name everywhere except the one lowering written for it, which
    # strips the field and carries the relation as its own payload key.
    "in_combat_with_source": "in_combat_with_source",
    "dealt_damage_to_source_this_turn": "dealt_damage_to_source_this_turn",
    # "blocking this creature" is **not** here any more. It was, on the
    # reading that no read of the blocker alone can answer the relation — which
    # is true, and is also true of ``blocked_by_source``, which has been an
    # emitted key all along. What separates a relative narrowing that refuses
    # from one that carries is not whether the *pure* matcher can test it but
    # whether ``subject_matches`` can, and that function takes the source. So
    # the field now has a payload form and every lowering carries it, the same
    # way they all carry its mirror.
    # "…that **blocked or were blocked by** it this turn" (Venomous Breath).
    # A history relative to the object a delayed ability was bound to, so it
    # has no ``to_payload`` form for its one-way sibling's reason — listed here
    # so every lowering but the destroy sweep written for it refuses the phrase
    # by name instead of sweeping the board.
    "in_combat_with_bound_object": "in_combat_with_bound_object",
    # "…**that targets a permanent you control**" (Avoid Fate, Ring of
    # Immortals). No ``to_payload`` form: a nested "what did that spell target"
    # phrase is a question about a stack object rather than about a permanent.
    # Listed here so every lowering that builds a payload from a filter refuses
    # it by name, and the one that reads it — the counter lowering — carries it
    # as its own key.
    #
    # ``any_classes`` used to sit here beside it, on the reading that a
    # cross-axis union has no field pair that means it. That is still true of
    # the *pair*, and it is why the union now has a key of its **own**:
    # ``to_payload`` emits it and ``permanent_matches_filter`` tests it, so it
    # is a narrowing every lowering can carry rather than one they must all
    # refuse. Soldevi Adnate's "a black or artifact creature" is the printing
    # that could not be said any other way.
    "targets_object": "targets_object",
    # "…with a single target" (Reflecting Mirror). CR 115.9a's count of what a
    # stack object chose, which has no ``to_payload`` form for the reason
    # ``targets_object`` beside it has none — it is a question about a spell,
    # not about a permanent. Listed here so every lowering that builds a
    # payload from a filter refuses it by name, and the one written for it
    # carries the count as its own key.
    "target_count": "target_count",
    # "another permanent **of that type**" (Enchantment Alteration). Which type
    # "that" is depends on the object the sentence's *other* clause named, so
    # no read of the candidate alone can answer it and there is no payload form.
    # The one admitting lowering strips the field and carries the relation as
    # its own key; every other lowering refuses the phrase by name.
    "of_bound_type": "of_bound_type",
    # "creatures blocking **target attacking creature**" / "each creature
    # blocking **it**" (Feint). The blocked object is not the source, so
    # `blocking_source` above cannot carry it; it is another object *this same
    # sentence* names, which no read of the blocker alone can answer. Listed
    # here for the same reason its three siblings are: every lowering that
    # builds a payload from a filter refuses the phrase by name, and the two
    # written for it carry the relation as their own payload key.
    "blocking_target": "blocking_target",
    "blocking_bound_target": "blocking_bound_target",
    # "…that were blocked by that creature this turn" (Glyph of Doom) / "…by
    # **target Wall** this turn" (Glyph of Reincarnation). The block *history*,
    # in its two referents. Neither has a ``to_payload`` form — the record lives
    # on the blocker, not on the creatures being described — and until now both
    # leaned on the dataclass-wide gates alone, which is the hole this table
    # exists to close: a lowering that builds a payload from the filter and does
    # not know the field drops the relation, and a dropped relation on a destroy
    # sweep is not a card that does less, it is one that takes the board. The
    # two lowerings written for them name them in ``carried_separately``.
    "blocked_by_bound_object": "blocked_by_bound_object",
    "blocked_by_target_object": "blocked_by_target_object",
    # "the number of green creatures **on the battlefield**" (An-Havva
    # Constable, An-Havva Inn). CR 403.1's shared zone, which is a statement
    # about *scope* rather than a characteristic of any object — so
    # ``to_payload`` emits nothing for it, and a lowering that built a payload
    # and did not know the field would scope the set to one seat. That
    # direction is not a card doing less: on a two-player board a count is
    # halved, silently, while the sentence still reports supported. Only
    # ``_amounts.count_spec`` reads it, because it is the one reader with
    # somewhere to put a scope (``owner: "all"``).
    "on_the_battlefield": "on_the_battlefield",
}


def is_mana_value_x(comparison: "ast.Comparison | None") -> bool:
    """Whether a mana-value bound is the printed **X** — "with mana value X"
    (Spell Blast, Detonate) rather than "with mana value 3 or less" (Eliminate).

    One reading of the phrase, two lowerings that do different things with it:
    the counter flow refuses everything else, the destroy flow lets a literal
    bound ride the payload as an ordinary narrowing. The difference is what each
    handler can ask, so it stays in each; what "X" *is* is one question and lives
    here.
    """
    return (
        comparison is not None
        and comparison.op == "eq"
        and isinstance(comparison.value, ast.Var)
    )


def dropped_narrowings(
    filt: ast.ObjectFilter, payload: dict[str, object]
) -> tuple[str, ...]:
    """Names of *filt*'s set narrowings that left no key in *payload*."""
    return tuple(
        field
        for field, key in CONDITIONALLY_EMITTED_FIELDS.items()
        if getattr(filt, field) and key not in payload
    )


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
    payload = filt.to_payload()
    if dropped_narrowings(filt, payload):
        return None
    return card_only_filter(payload)


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

#: The same pair one phase down: "this combat" and "until end of combat" are two
#: printed spellings of CR 511's window, and a shield or a grant that reads one
#: and refuses the other would be a card failing on its printing rather than on
#: its effect. Beside ``_REST_OF_TURN`` and not inside the prevention family,
#: for that constant's own stated reason.
_REST_OF_COMBAT = ("this_combat", "until_end_of_combat")


def chargeable_tap_filter(filt: "ast.ObjectFilter") -> dict | None:
    """The payload a "Tap N <noun phrase>" cost charges, or None to refuse it.

    The one gate both readers of the clause run through — the grammar, which
    admits the line, and ``engine/oracle.py``, which reads what is actually
    charged. Two readers of one phrase drift, and the direction a cost drifts in
    is a cost nobody pays.

    "You control" is carried rather than tested: the charger scans the
    activating seat's own battlefield, so the phrase would be no narrowing at all
    there — but a phrase the charger silently agrees with is still a phrase it
    did not read, which is why it is named here instead of ignored. Everything
    else has to be answerable about a permanent alone.
    """
    from ...subject_filters import object_only_filter

    if filt.controller not in (None, "you"):
        return None
    # "**Untapped** Spirits" is carried, not tested, and for a reason stronger
    # than the controller's: a cost that taps a permanent can only ever be paid
    # with an untapped one, so the charger performs the word by construction.
    # `to_payload` has no key for it either — the payload says `tapped_only` for
    # True and nothing at all for False — so a filter carrying it would silently
    # reduce to the unnarrowed phrase, which is the case this names rather than
    # drops.
    if filt.tapped is True:
        return None
    payload = _filter_payload(filt)
    return object_only_filter(
        payload, carried_separately=frozenset({"controller", "tapped_only"})
    )


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
