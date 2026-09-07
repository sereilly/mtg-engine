"""Payload shapes and small values every lowering family needs.

The bottom of the lowering layer. Amount encoding, the `_is_source` / `_is_you`
subject predicates, and two values that are here for a specific reason rather
than by taxonomy: `_full_mana_payload` (with `_MANA_KEYS`) and `_REST_OF_TURN`.

What a *filter* means is `_filters` beside this file, which crossed the
thousand-line guard at Visions' Phase 0, and what a sentence **points at** is
`_targets`, which is where this module's own target descriptions went when it
crossed the same guard at Tempest's Phase 0. The three splits are all by
question: that one is which narrowings of a noun phrase survive into a payload
at all, `_targets` is CR 601.2's announcement, and what is left here is the
shape a payload takes. Every name they define is re-exported below, so no family
imports either directly.

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


from .. import ast
from ..errors import LoweringError

from ._filters import (_PAYLOAD_HONOURED_FILTER_FIELDS, _filter_payload,
                       _restrictions_beyond, chargeable_card_filter,
                       chargeable_tap_filter, dropped_narrowings,
                       graveyard_position_payload, is_mana_value_x,
                       refuse_untestable, testable_filter_payload)
# Re-exported for the families that read them; `_targets` holds the definitions.
# Three of its names are deliberately *not* here — `DEPENDENT_TARGET_RELATIONS`,
# `_targeted_specs` and `card_divided_target_description` have no reader outside
# that module, and a re-export nobody pulls through is the dead binding
# `test_import_hygiene` exists to catch.
from ._targets import (PRIMARY_TARGET_ROLE, SEVERAL_DESTROY_NARROWINGS,
                       _describe_several_card_targets,
                       _describe_several_targets, _describe_targets, _is_target,
                       _names_several_targets, _refuse_unfused_distinctness,
                       _targets_only, _targets_payload,
                       card_divided_each_description,
                       card_divided_shares_payload, describe_target_roles,
                       describe_independent_target_roles,
                       divided_target_description)


def split_creature_type_choice(described: dict) -> tuple[tuple, dict, dict]:
    """*described* with "of the creature type of your choice" turned into the
    steps that answer it: the instructions to run first, and the payload the
    caller should carry.

    CR 608.2d: the choice is announced while the effect is applied, by the
    controller of the spell — so it is a *step*, not a characteristic, and it
    goes in front of the sentence that spends it exactly as ``choose_opponent``
    goes in front of the hand-over that reads the seat. A handler that stopped
    to ask could not also finish the sentence.

    Three things come back: the instructions to run first, the filter with the
    phrase taken out, and the keys the caller must **add after its testability
    gate**. ``subtype_filter_from`` names the scratchpad slot the choosing step
    writes and is resolved by the handler, not by the matcher — so it is carried
    separately for the reason ``exile_all_matching``'s ``mana_value`` is: a key
    no matcher answers must not be put to a gate that asks whether every key is
    answerable. Naming the slot rather than hard-coding it is what lets a second
    card put the choice in a different sentence of the same effect.

    An untouched filter comes back with an empty prelude and no extra keys, so
    every caller can ask unconditionally.
    """
    if not described.get("creature_type_of_your_choice"):
        return (), described, {}
    from ...oracle_types import (CHOSEN_CREATURE_TYPE_THIS_WAY,
                                 OracleInstruction)

    rest = {
        key: value for key, value in described.items()
        if key != "creature_type_of_your_choice"
    }
    prelude = (
        OracleInstruction(
            "choose_creature_type", "",
            {"result_key": CHOSEN_CREATURE_TYPE_THIS_WAY},
        ),
    )
    return prelude, rest, {"subtype_filter_from": CHOSEN_CREATURE_TYPE_THIS_WAY}


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


# Both halves of the keyword family read these — the grant in
# `keywords.py` and the removal in `keyword_removal.py` — so they sit on
# the floor rather than in either, which is the rule a fragment two
# families need has followed since `phrases`.
def _is_landwalk(keyword: str) -> bool:
    """Whether *keyword* is a landwalk the engine enforces.

    Asked beside :data:`IMPLEMENTED_KEYWORDS` rather than folded into it,
    because CR 702.14a builds a landwalk's **name** out of a printed quality —
    "islandwalk", "snow forestwalk", "nonbasic landwalk" — so the set of names
    is open and no frozenset can hold it. `engine/landwalk.py` is the reader
    that decides whether a quality is one the block check can test, and it is
    already the gate `engine/oracle.py` asks about a printed keyword *line*.
    A grant asking a different question is how "gains landwalk of the chosen
    type" comes to work for five types and refuse the other thirteen.
    """
    from ...landwalk import is_landwalk

    return is_landwalk(keyword)


def _refuse_bare_chosen_ability(node) -> None:
    """A "gains it" / "loses it" that reached an ordinary lowering.

    The pronoun names the keyword an activation chose, and only the two-clause
    *move* it is printed in (``_fused_two_target_keyword_move``) knows how to
    spend it — that fuser reads both halves before either is lowered. Anything
    else arriving here carries an empty keyword tuple, which every branch below
    would happily turn into a grant of nothing.
    """
    if getattr(node, "chosen_ability", False):
        raise LoweringError(
            'a "gains it" naming the chosen ability is read by the keyword '
            "move that prints it, not on its own",
            node=node,
        )
