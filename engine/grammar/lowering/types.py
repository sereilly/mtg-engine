"""Lowering what an object's *type line* says (CR 205, CR 613 layer 4).

Animation ("becomes a 2/2 creature"), a gained card type ("becomes an artifact
in addition to its other types"), a supertype ("becomes snow") and a basic land
type ("becomes a Swamp") — four printed shapes of one layer.

Split out of `characteristics.py` at 982 of the thousand-line cap, the round a
targeted land animation and a targeted land-type change landed together. The
line is the CR's own and it is the line `engine/land_types.py`,
`engine/land_animation.py` and `engine/keywords.py` already draw one package
over: CR 208 is how *big* a permanent is (layer 7), CR 105 what colour it is
(layer 5), CR 612 what its text says (layer 3) — and CR 205 is what it **is**.
The two halves share no helper; everything either uses is in `_common`.

Asymmetric on purpose, like `zones`, `library` and `returns` before it: the
parse side stays in `effects/characteristics.py`, where every one of these is a
branch of one `becomes` production reading one shared duration clause. A
near-empty `effects/types.py` would buy back the symmetry and cost the thing
symmetry is for.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import untestable_filter_keys
from ._common import _describe_targets, _filter_payload, _is_source, _is_target


def _lower_become_creature(
    node: ast.BecomeCreature,
) -> tuple[OracleInstruction, ...]:
    """"…becomes a 3/3 Sphinx creature with flying in addition to its other
    types until end of turn." (Riddleform.) "Target snow land becomes a 2/2
    creature until end of turn. It's still a land." (Balduvian Conjurer.)

    Two instruction kinds for one node, and the difference is which permanent
    holds the record: the animation *is* one metadata entry the layer bridge
    reads (layers 4, 6 and 7b together), so a sentence about the source writes
    it on the source and a sentence about a target writes it on whatever the
    target turned out to be. A quantified subject refuses — "all Forests become
    1/1 creatures" is a board-wide static recomputed every pass
    (`engine/land_animation.py`), not a record stamped once.
    """
    if _is_source(node.subject):
        _refuse_indefinite(node, "a permanent animating itself")
        return (
            OracleInstruction(
                "animate_self_until_eot", "", _animation_payload(node)
            ),
        )
    # "**Forests you control** become 2/3 creatures until end of turn. They're
    # still lands." (Thelonite Druid.) A quantified subject, and a *third*
    # instruction kind rather than a flag on the two above, because what
    # differs is where the record goes: one permanent the sentence named
    # (either of the two above) against every permanent the phrase describes,
    # collected when the ability resolves and fixed then (CR 611.2c).
    #
    # Distinct from ``engine/land_animation.py``, which reads the same words
    # printed as a *static* ability: that one is recomputed from the board on
    # every pass and ends when its source leaves, and this one is a one-shot
    # that ends at cleanup — the same sentence, two durations, two mechanisms.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and node.subject.quantifier in ("all", "each")
    ):
        described = _filter_payload(node.subject.filter)
        if not described or untestable_filter_keys(described):
            # A narrowing the matcher cannot test would be carried and dropped,
            # and a dropped narrowing on a sweep is not an animation that does
            # less — it is one that animates the whole board.
            raise LoweringError(
                "the animation sweep cannot test this noun phrase", node=node
            )
        _refuse_indefinite(node, "an animation sweep")
        payload = _animation_payload(node)
        payload.update(described)
        return (OracleInstruction("animate_matching_until_eot", "", payload),)
    if not _is_target(node.subject):
        raise LoweringError(
            "an animation names the source, one target or a described set",
            node=node,
        )
    payload = _animation_payload(node)
    payload.update(_filter_payload(node.subject.filter))
    _describe_targets(payload, node.subject)
    # "Target land becomes a 3/3 artifact creature that's still a land. (This
    # effect lasts indefinitely.)" (Mishra's Groundbreaker.) CR 611.2a: a
    # continuous effect from a resolving spell or ability with no stated
    # duration lasts as long as the game does, so the *record* has to outlive
    # the cleanup sweep that ends every other animation. Its own kind rather
    # than a flag on the one above, for the reason the three kinds above are
    # three: what differs is which record is written, and a kind whose name says
    # "until_eot" writing a record nothing sweeps would be a lie a reader has no
    # way to see.
    if not node.until_end_of_turn:
        return (OracleInstruction("animate_target_indefinitely", "", payload),)
    return (OracleInstruction("animate_target_until_eot", "", payload),)


def _refuse_indefinite(node: ast.BecomeCreature, what: str) -> None:
    """Refuse an animation with no printed duration that no handler can hold.

    Only the *targeted* animation has an indefinite record behind it
    (``animate_target_indefinitely``); the source and sweep kinds write the
    until-end-of-turn record the cleanup step clears, so admitting one here
    would compile a permanent animation and end it at cleanup — a card doing
    strictly less than it prints, silently. No card in the pool prints either
    shape; the refusal names which piece is missing so the one that does gets a
    round rather than a bug.
    """
    if not node.until_end_of_turn:
        raise LoweringError(
            f"no handler holds an indefinite animation for {what}", node=node
        )


def _animation_payload(node: ast.BecomeCreature) -> dict[str, object]:
    """What the animation record says, shared by both kinds above.

    ``card_types`` is "…a 2/2 Assembly-Worker **artifact** creature" — the types
    the animation adds beside "creature", which the layer-4 collector reads off
    the same record. Balduvian Conjurer's "It's still a land" adds none, and the
    production has already consumed the words; the addition is what the record
    means either way, since nothing is taken away.
    """
    return {
        "power": node.power,
        "toughness": node.toughness,
        "subtypes": list(node.subtypes),
        "keywords": list(node.keywords),
        "card_types": list(node.card_types),
    }


#: Durations a gained type may carry. "Permanently" is the absent kind, which
#: is what Ashnod's Transmogrant prints — the creature stays an artifact long
#: after the Transmogrant has been sacrificed.
_GAINED_TYPE_DURATIONS = frozenset({None, "until_end_of_turn", "until_your_next_upkeep"})


def _lower_gain_type(node: ast.GainType) -> tuple[OracleInstruction, ...]:
    """Ashnod's Transmogrant / Xenic Poltergeist.

    The subject must be a chosen target or the pronoun bound by an earlier
    sentence of the same effect: the handler adds the record to *one* permanent,
    and a quantified subject would name a set it cannot reach.
    """
    if node.duration.kind not in _GAINED_TYPE_DURATIONS:
        raise LoweringError(
            f"no handler holds a gained type for {node.duration.kind}", node=node
        )
    payload: dict[str, object] = {
        "card_types": list(node.card_types),
        "duration": node.duration.kind or "permanent",
        "pt_from_mana_value": bool(node.pt_from_mana_value),
    }
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in ("target", "that"):
        if node.subject.quantifier == "target":
            _describe_targets(payload, node.subject)
        return (OracleInstruction("gain_type", "", payload),)
    raise LoweringError("a gained type needs a single named permanent", node=node)


def _lower_change_supertype(node: ast.ChangeSupertype) -> tuple[OracleInstruction, ...]:
    """Arcum's Weathervane, both abilities.

    One kind for both directions: the supertype and the polarity are payload,
    which is what makes "becomes snow" and "is no longer snow" one handler
    rather than two — and what makes a card printing "becomes legendary" cost
    nothing.

    The duration must be one the handler's channel can hold, and the subject a
    single named permanent, for the reason ``_lower_gain_type`` requires both:
    the record goes on one permanent, and a quantified subject names a set that
    is a *static* ability rather than a one-shot (see
    ``_parse_no_longer_supertype``).
    """
    if node.duration.kind not in _GAINED_TYPE_DURATIONS:
        raise LoweringError(
            f"no handler holds a supertype change for {node.duration.kind}", node=node
        )
    payload: dict[str, object] = {
        "supertype": node.supertype,
        "gained": bool(node.gained),
        "duration": node.duration.kind or "permanent",
    }
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in ("target", "that"):
        if node.subject.quantifier == "target":
            _describe_targets(payload, node.subject)
        return (OracleInstruction("change_supertype", "", payload),)
    raise LoweringError("a supertype change needs a single named permanent", node=node)


#: Durations a *basic land type* change has a sweep for. CR 305.7 replaces the
#: land's subtypes for as long as the effect lasts, so a window nothing ever
#: ends would be a land permanently something else — the direction a dropped
#: duration always fails in. "Until its controller's next untap step" is the
#: one the untap step itself lifts; the absent kind is CR 611.2's
#: "indefinitely", which the recorded contribution already holds.
#: "Until end of turn" (Jinx) is the cleanup step's, swept beside every other
#: until-end-of-turn record; it is admitted here *because* that sweep exists,
#: which is the whole rule this table states.
_LAND_TYPE_DURATIONS = frozenset(
    {None, "until_controllers_next_untap_step", "until_end_of_turn"}
)


def _lower_change_land_type(node: ast.ChangeLandType) -> tuple[OracleInstruction, ...]:
    """"Target land becomes a Swamp until its controller's next untap step."
    (Orcish Farmer.)

    CR 305.7's *replacement* of a land's basic land types, recorded as one
    layer-4 contribution keyed on the source (`engine/land_types.py`) — so the
    land is whatever the remaining contributions say when this one ends, rather
    than whatever was printed on it.

    The land type is payload, so a card printed about a Forest is this
    production. The **duration** is not: a window with no sweep behind it is a
    change that never ends, so a kind absent from the table above refuses.

    "…becomes **the basic land type of your choice**" (Jinx) carries the choice
    as its own boolean and no ``land_type`` at all. The sentinel stops at this
    boundary the way ``CHOSEN_COLOR`` does one family over: a handler reading an
    AST constant would be the dispatch side importing the parser's vocabulary,
    and a payload whose ``land_type`` is the literal string "chosen_land_type"
    is one ``change_land_type`` call away from stamping that on a land.
    """
    if node.duration.kind not in _LAND_TYPE_DURATIONS:
        raise LoweringError(
            f"no sweep ends a land-type change at {node.duration.kind}", node=node
        )
    if not _is_target(node.subject):
        raise LoweringError(
            "a land-type change names one target land", node=node
        )
    # The named type keeps its place at the front of the payload: these dicts
    # are compared by ``repr`` in the behavioural signatures and in the
    # whole-pool differential, so a key that changed position would report every
    # land-type card as moved.
    named = {} if node.land_type == ast.CHOSEN_LAND_TYPE else {
        "land_type": node.land_type
    }
    payload: dict[str, object] = {
        **named,
        "duration": node.duration.kind or "permanent",
        **_filter_payload(node.subject.filter),
    }
    if not named:
        payload["choose_land_type"] = True
    _describe_targets(payload, node.subject)
    return (OracleInstruction("change_land_type_until", "", payload),)
