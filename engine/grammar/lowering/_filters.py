"""What a printed **noun phrase** becomes as a payload — the filter floor.

Split out of ``_common`` at Visions' Phase 0, when that module reached the
thousand-line guard with five wave branches about to open on it. The seam is
the one ``_common``'s own docstring had already drawn in prose: this module is
what a *filter* means — which ``ObjectFilter`` fields survive the trip to a
handler, which narrowings a payload silently drops, and the two cost gates that
answer "may this phrase be charged?" — where everything left in ``_common`` is
what a *target description* looks like and the small values several families
share.

A floor rather than a family, for ``_primitives``' reason exactly one package
over: ``_common`` reads it and it reads nothing back, and ``_common``
re-exports every name below, so no lowering family imports this module
directly. The pairing that makes the filter gates work — ``_restrictions_beyond``
asking "is this field honoured at all?" against the payload-key check asking "is
every key testable?" — is the reason they are one module: a narrowing that falls
between those two questions is an effect reaching further than the card prints,
and the two halves of that question have never been apart.
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
    # "**attacking or blocking** creatures without flying" (Rock Slide),
    # "**tapped or blocking** creature" (Tetsuo Umezawa). ``to_payload`` emits
    # it unconditionally and ``permanent_matches_filter`` tests it, so it is
    # honoured in exactly the sense the three state fields beside it are — and
    # it is listed for ``any_classes``' reason: it is the *union*, which no
    # pair of those fields can state, so a lowering refusing it as an
    # unhonoured field refuses a phrase the payload carries perfectly well.
    "any_states",
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
    # "…**except for basic lands**" / "…**other than a basic land**" (Eye of
    # Singularity's two lines). ``to_payload`` emits it as
    # ``exclude_basic_lands`` and the pure matcher tests it off the printed type
    # line, so it is honoured in the sense every type word here is.
    "excluded_basic_lands",
    # "…**with the same name as another permanent**" (Eye of Singularity).
    # Emitted unconditionally and answered by ``subject_matches``, which has the
    # board the relation compares against — the same footing
    # ``controller_controls`` below is on.
    "shares_name_with_another",
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
    # "a creature **of the chosen color**" (Mangara's Equity) / "a land **of
    # the chosen type**" (Roots of Life) / "creatures of the chosen type"
    # (An-Zerrin Ruins). CR 614.1c's entry choice, recorded on the source and
    # resolved into an ordinary colour or subtype key by
    # ``handlers/_common._resolve_chosen_color`` / ``_resolve_chosen_subtype``
    # before any matcher is asked - so all three are honoured in exactly the
    # sense ``colors`` and ``subtypes`` above are, and all three are already in
    # ``TESTABLE_SUBJECT_FILTER_KEYS`` because ``subject_matches`` answers them.
    #
    # Left out, every lowering asking ``_restrictions_beyond`` refused a phrase
    # the payload carries perfectly well - the same **false refusal**
    # ``owner``, ``any_classes``, ``token_only`` and ``subtype_match`` above
    # were each added to end. It cost Roots of Life its whole second sentence:
    # the trigger condition's ``_subject`` group is read through
    # ``subject_filter_payload``, which refused here, so "whenever a land of the
    # chosen type an opponent controls becomes tapped" compiled to **no trigger
    # at all** - while the card still reported supported on the life gain
    # behind it and `parse_coverage` still claimed the line.
    #
    # A caller with no source leaves the key in place and
    # ``permanent_matches_filter`` refuses every permanent, which is the
    # direction that cannot widen an effect; a caller naming *cards* is refused
    # outright by ``card_only_filter``, since none of the three is in
    # ``CARD_ONLY_FILTER_KEYS``.
    "chosen_color", "chosen_creature_type", "chosen_land_type",
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


def testable_filter_payload(
    filt: "ast.ObjectFilter",
    *,
    refusal: str,
    node=None,
    allowed: "frozenset[str] | None" = None,
    require_narrowing: bool = True,
) -> dict[str, object]:
    """A printed noun phrase's payload, or a ``LoweringError`` naming why not.

    The two questions a lowering asks of a phrase it is about to hand a
    dispatcher, in the one order that answers them: what does the phrase
    *become* (``_filter_payload``, which refuses a field with no payload form),
    and can whoever receives it **test** every key of what it became
    (``untestable_filter_keys``, which recurses exactly where the matcher does).
    A key that falls between the two is a narrowing dropped in silence, which
    for a filter is an effect reaching further than the card prints.

    Both halves were open-coded. `lowering/prevention.py` alone opened four of
    its lowerings with the same two lines — ``described = _filter_payload(x)``
    then ``if not described or set(described) - TESTABLE_SUBJECT_FILTER_KEYS``
    — and the looser spelling appears across the lowering package in several
    forms. Not a duplicate *definition*, so no merge scan could see it, and
    every copy was correct on the day it was written; what makes it worth
    folding is the direction a drifted copy fails in, and that two of the
    spellings had already drifted. ``set(payload) - TESTABLE_SUBJECT_FILTER_KEYS``
    is a **flat** difference, so a nested phrase ("Auras attached to permanents
    you control") answers "testable" whatever the inner phrase says — the exact
    hole ``untestable_filter_keys`` was written to close one round earlier, in
    modules that then kept the flat form.

    *refusal* is the sentence the card's reader sees, and the untestable keys
    are appended to it: a refusal that names the missing piece is a mechanism
    rather than an absence (SET_PLAYBOOK Phase 3), and every one of the folded
    copies stopped at the prose.

    *require_narrowing* is the ``not described`` half. A shield sized by "if
    it's a green creature" means nothing if the phrase reduces to no keys at
    all, so those callers refuse it; a caller for which the unnarrowed phrase
    is a legitimate reading passes ``False``.
    """
    from ...subject_filters import (TESTABLE_SUBJECT_FILTER_KEYS,
                                    untestable_filter_keys)

    payload = _filter_payload(filt)
    if require_narrowing and not payload:
        raise LoweringError(
            f"{refusal}: the phrase narrows nothing at all", node=node
        )
    untestable = untestable_filter_keys(
        payload, allowed=TESTABLE_SUBJECT_FILTER_KEYS if allowed is None else allowed
    )
    if untestable:
        raise LoweringError(
            f"{refusal}: {', '.join(sorted(untestable))}", node=node
        )
    return payload


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


def split_bound_card_type(filt: "ast.ObjectFilter") -> tuple["ast.ObjectFilter", dict]:
    """*filt* without "of that type", plus the payload keys that phrase means.

    "…that player chooses artifact, creature, land, or non-Aura enchantment.
    All nontoken permanents **of that type** phase out." (Teferi's Realm.) The
    two sentences are one printed ability, and the second's "that" points at the
    first's choice — recorded on the ability's own source, exactly where every
    CR 614.1c entry choice records one.

    Split rather than rewritten in place because ``of_bound_type`` has no
    ``to_payload`` form at all: it is one of the four relations the payload
    table lists precisely so that a lowering with no answer for it refuses by
    name. A lowering that *does* have an answer strips the field and carries the
    relation as its own key, which is what ``lowering/attachments.py`` already
    does for the same field's other reading.

    The same arrangement Hall of Gemstone's two sentences have one
    characteristic over: the reading sentence carries a flag and the handler
    resolves it against the source at resolution. There is no cross-sentence
    check that a choice was really made, and there need not be — a source with
    no record resolves to nothing and the matcher then refuses every permanent,
    which for a sweep is the only safe direction.
    """
    if not filt.of_bound_type:
        return filt, {}
    import dataclasses

    from ...handlers._common import CHOSEN_CARD_TYPE

    return dataclasses.replace(filt, of_bound_type=False), {CHOSEN_CARD_TYPE: True}
