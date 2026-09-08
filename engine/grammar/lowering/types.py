"""Lowering what the ``becomes`` verb produces.

Animation ("becomes a 2/2 creature"), a gained card type ("becomes an artifact
in addition to its other types"), a supertype ("becomes snow"), a basic land
type ("becomes a Swamp") — CR 205, CR 613 layer 4 — and the colour change
("becomes white until end of turn", the Lace cycle), which is CR 105 and layer
5 and is here anyway.

**The colour lowering moved in when `effects/types.py` was written.** It is a
branch of the one production that parses all five, and the module that reads a
sentence and the module that lowers it should be able to be named the same
thing; leaving `_lower_become_color` behind in `characteristics` would have put
one production's five branches in two lowering families and made the mirror a
half-truth. The family is therefore named for the *verb* rather than for the
layer — which is what the parse side was always named for, since only what
follows "becomes" tells the five apart.

Split out of `characteristics.py` at 982 of the thousand-line cap, the round a
targeted land animation and a targeted land-type change landed together. The
line is the CR's own and it is the line `engine/land_types.py`,
`engine/land_animation.py` and `engine/keywords.py` already draw one package
over: CR 208 is how *big* a permanent is (layer 7), CR 105 what colour it is
(layer 5), CR 612 what its text says (layer 3) — and CR 205 is what it **is**.
The two halves share no helper; everything either uses is in `_common`.

No longer asymmetric: this docstring used to argue that "a near-empty
`effects/types.py` would buy back the symmetry and cost the thing symmetry is
for", which was true of a near-empty file and stopped being true when
`effects/characteristics.py` reached 985 of the cap. The `becomes` cluster is
316 lines of parsing on its own and now has its own module; the prediction was
about a size and the size changed.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import untestable_filter_keys
from ...oracle_types import BLOCK_PAIR_SUBJECT, SUBJECT_FROM_TRIGGER
from ._common import (_describe_several_targets, _describe_targets,
                      _filter_payload, _is_enchanted, _is_source, _is_target,
                      _names_several_targets)
from ._events import _EVENT_SUBJECT_OBJECTS, binds_block_pair


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
        # "{6}: This land becomes a 3/3 Elemental artifact creature that's
        # still a land. (This effect lasts indefinitely.)" (Stalking Stones.)
        # CR 611.2a: a continuous effect from a resolving ability with no
        # stated duration lasts as long as the game does, so the record has to
        # outlive the cleanup sweep — its own kind for the reason the targeted
        # pair are two kinds, that a kind whose name says "until_eot" writing a
        # record nothing sweeps is a lie a reader has no way to see.
        kind = (
            "animate_self_until_eot" if node.until_end_of_turn
            else "animate_self_indefinitely"
        )
        return (OracleInstruction(kind, "", _animation_payload(node)),)
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

    ``colors`` is "…a 2/2 **green** creature" (Quirion Druid), CR 613 layer 5 of
    the same sentence. Emitted **only when the sentence named one**, so every
    animation payload written before this key existed is byte-identical — the
    absence means "the sentence said nothing about colour", which is not the
    same claim as "no colours" (CR 105.2c's colourless), and a key that was
    always present could not tell the two apart.
    """
    payload: dict[str, object] = {
        "power": node.power,
        "toughness": node.toughness,
        "subtypes": list(node.subtypes),
        "keywords": list(node.keywords),
        "card_types": list(node.card_types),
    }
    if node.colors:
        payload["colors"] = list(node.colors)
    if node.replaces_types:
        # CR 205.1a's default, printed by saying nothing (Opal Gargoyle). Only
        # emitted when the node claims it, for ``colors``' reason one clause
        # up: every animation payload written before this key existed is
        # byte-identical, and the absence means "the sentence kept the printed
        # types", which is exactly what those cards' retention clauses said.
        payload["replaces_types"] = True
    return payload


#: Durations a gained type may carry. "Permanently" is the absent kind, which
#: is what Ashnod's Transmogrant prints — the creature stays an artifact long
#: after the Transmogrant has been sacrificed.
_GAINED_TYPE_DURATIONS = frozenset({None, "until_end_of_turn", "until_your_next_upkeep"})


def _lower_become_aura(node: ast.BecomeAura) -> tuple[OracleInstruction, ...]:
    """Necromancy's ``it becomes an Aura with "enchant …."``

    One instruction for both halves of the sentence, because the two are one
    thing the permanent becomes: CR 613 layer 4 gives it the Aura subtype and
    layer 6 gives it the enchant ability (CR 702.5) that says what it may be
    attached to. Split in two the type change would land on a permanent whose
    enchant clause nothing had recorded, and CR 704.5m would bin it on the next
    state-based pass — an Aura attached to nothing — half a resolution before
    the sentence behind it attaches it.

    The enchant restriction is carried, never dropped: ``origin`` says the host
    must be a permanent this one put onto the battlefield, which is what
    ``auras.enchant_card_refusal`` tests and what stops the Aura being moved
    onto a creature it never reanimated. The parse admits no other quality, so
    there is no shape here that reaches the handler with a rider nothing reads.

    A Licid prints the same sentence with **no** rider and two extra facts: the
    card type it becomes (CR 205.1a — an "Aura enchantment" stops being a
    creature, where Necromancy's "an Aura" is a subtype an enchantment already
    is) and the ability it loses (CR 613 layer 6). Both ride the payload for
    this file's standing reason — a printed word is data — so the two cards are
    one instruction kind and one handler rather than two of each.

    An unrestricted enchant clause needs no rider *test*, only the noun, and
    ``mixins/stack.permanent_matches_enchant_noun`` is what tests that — the
    same reader every printed ``Enchant <noun>`` line goes through. So the
    refusal here is no longer "the clause has no rider" but "the clause has a
    rider the engine cannot test", which is the shape of every gate in this
    package.
    """
    payload: dict[str, object] = {"noun": node.noun}
    if node.origin_is_source:
        payload["origin"] = "source"
    if node.card_types:
        payload["card_types"] = list(node.card_types)
    if node.loses_own_ability:
        payload["loses_own_ability"] = True
    return (OracleInstruction("become_aura_with_enchant", "", payload),)


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
    if node.replaces_types:
        # "{0}: This permanent becomes an enchantment." (Opal Acrolith,
        # Hidden Stag's second line.) CR 205.1a's *replacement*, which is a
        # different record from the gain below and so a different kind: the
        # gain joins a type to whatever the permanent already had, and this one
        # says what it now is — the two cannot share a handler without a flag
        # deciding which of two channels to write, which is the shape this
        # package spells as two kinds.
        #
        # Only the source, because that is what the pool prints: both cards
        # here name themselves. A target would need a picker this instruction
        # does not describe, so it refuses rather than resolving against
        # whatever the context happened to hold.
        if not _is_source(node.subject):
            raise LoweringError(
                "a card-type replacement names the ability's own source",
                node=node,
            )
        if node.duration.kind is not None:
            # Every duration in ``_GAINED_TYPE_DURATIONS`` has a sweep for the
            # *gain* channel and none of them clears this one, so admitting a
            # window here would be a replacement that never ends.
            raise LoweringError(
                f"no sweep ends a card-type replacement at {node.duration.kind}",
                node=node,
            )
        return (
            OracleInstruction(
                "set_card_types_self", "", {"card_types": list(node.card_types)}
            ),
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


def _lower_become_copy(
    node: ast.BecomeCopy, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"…this creature becomes a copy of that creature, except it has this
    ability." (Unstable Shapeshifter, CR 707.2.)

    Three gates, and each is a refusal rather than a default:

    * the **subject** must be the ability's own source. "Target creature becomes
      a copy of …" is a different card and would need a picker this instruction
      does not describe;
    * the **object** must be the firing event's, and the event must be one that
      freezes it (``_EVENT_SUBJECT_OBJECTS``). Without that the words name
      nothing and the handler would copy whatever the resolution happened to be
      holding — the refusal every other back-reference in this package makes;
    * the noun phrase is carried so the handler can re-check it. It is the same
      filter the trigger's own condition narrowed by, and a copy of a permanent
      that does not answer it is a copy the sentence never described.
    """
    if not getattr(node.subject.filter, "is_source", False):
        raise LoweringError(
            "only the ability's own source becomes a copy this way", node=node
        )
    if node.of.quantifier != "that":
        raise LoweringError(
            "the object copied is the one the firing event bound", node=node
        )
    if event not in _EVENT_SUBJECT_OBJECTS:
        raise LoweringError(
            "\"that\" names the firing event's object, and this event records "
            "none",
            node=node,
        )
    payload: dict[str, object] = {"filter": _filter_payload(node.of.filter)}
    if node.keeps_own_ability:
        # CR 707.9a. Emitted only when the clause is printed, so a plain
        # "becomes a copy of that creature" compiles to the payload it would
        # have had without this field.
        payload["keeps_own_ability"] = True
    return (OracleInstruction("become_copy_of_bound_permanent", "", payload),)


def _lower_become_color(
    node: ast.BecomeColor,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """The Lace cycle, and the five Legends colour spells beside it.

    Two instructions, told apart by the *duration* rather than by the number of
    targets: an indefinite change writes the permanent colour channel and a
    turn-long one writes the until-end-of-turn channel the cleanup step sweeps,
    and layer 5 reads both (`engine/layer_bridge.py`). One handler covers one
    target or several, since a single chosen slot is a list of one.
    """
    if node.color in (ast.CHOSEN_COLOR, ast.CHOSEN_COLORS):
        several = node.color == ast.CHOSEN_COLORS
        if _is_enchanted(node.subject):
            # "Enchanted creature becomes the color or colors of your choice."
            # (Dream Coat.) The Aura's own host rather than a target: an Aura's
            # activated ability acts on what it is attached to (CR 303.4), which
            # is nothing the activator chooses. Read as a target it refused, and
            # the ability compiled to nothing at all.
            if node.duration.kind is not None:
                raise LoweringError(
                    f"no handler recolours for {node.duration.kind!r}", node=node
                )
            return (
                OracleInstruction(
                    "recolor_enchanted_chosen_color", "", {"several": several}
                ),
            )
        if _is_source(node.subject):
            # "You may have **this creature** become the color or colors of your
            # choice." (Shyft.) The third subject the phrase is printed on, and
            # the one nobody chooses at all: an object the sentence names
            # outright. Its own kind rather than the Aura's, because which
            # permanent is recoloured is the whole difference and reading the
            # source off an ``attached_to`` that is never there would recolour
            # nothing.
            #
            # No duration: "(This effect lasts indefinitely.)" is CR 611.2's
            # default said out loud, so a printed one would be a different card.
            if node.duration.kind is not None:
                raise LoweringError(
                    f"no handler recolours for {node.duration.kind!r}", node=node
                )
            return (
                OracleInstruction(
                    "recolor_self_chosen_color", "", {"several": several}
                ),
            )
        # "**Target permanent** becomes the color or colors of your choice."
        # (Prismatic Lace.) The set offer on a chosen object, which is the one
        # of the three subjects that had no path: the Aura's host and the
        # source itself both reached ``arm_color_set_choice`` and a target
        # refused outright. It is the same offer on the same permanent channel
        # — CR 105.2 makes a two-coloured object one object — so ``several``
        # rides the payload here exactly as it does on the two branches above,
        # and the handler asks the same prompt.
        # "Target permanent you control becomes the color of your choice."
        # (Alchor's Tomb.) Its own kind rather than a flag on the lace kind,
        # because the two describe different pickers: a lace targets a spell or
        # a permanent and names its colour in the text, while this one targets
        # whatever its printed noun phrase says and reads the colour back off
        # the choice made when the ability was activated. The noun phrase is
        # described here, so "you control" is enforced by the picker rather
        # than dropped — the lace kind's fixed `spell_or_permanent` spec would
        # have offered every permanent on the board.
        if not isinstance(node.subject, ast.TargetSpec) or not node.subject.targeted:
            raise LoweringError(
                "no handler recolours an object nobody targeted", node=node
            )
        if node.duration.kind is not None:
            raise LoweringError(
                f"no handler recolours for {node.duration.kind!r}", node=node
            )
        payload: dict[str, object] = {}
        if several:
            payload["several"] = True
        _describe_targets(payload, node.subject)
        return (OracleInstruction("recolor_target_chosen_color", "", payload),)
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        # "{2}: **This creature** becomes colorless until end of turn." (Raging
        # Spirit.) The ability's own source, which is not a target and never
        # was — the branch below reads a chosen object, and reading the source
        # as one would recolour whatever the picker happened to offer.
        if _is_source(node.subject):
            return (
                OracleInstruction(
                    "recolor_self_until_eot", "", {"target_color": node.color}
                ),
            )
        if not isinstance(node.subject, ast.TargetSpec) or not node.subject.targeted:
            raise LoweringError(
                "no handler recolours an object nobody targeted", node=node
            )
        payload: dict[str, object] = {"target_color": node.color}
        if _names_several_targets(node.subject):
            _describe_several_targets(payload, node.subject)
        else:
            # "{T}: **Target permanent** becomes colorless until end of turn."
            # (Ersatz Gnomes.) The single-target spelling was described to
            # nobody, so `derive_activation_spec` had no evidence, the picker
            # offered nothing and the ability could not be aimed at all — a
            # supported card no player can use, which is what
            # `scripts/picker_sweep.py` exists to find.
            #
            # The several-target spelling beside it has always been described.
            # The handler reads neither: it resolves through
            # `resolve_target_permanents`, which asks the *context* for what was
            # chosen, so this description is the picker's evidence and nothing
            # else's — which is exactly why its absence was silent.
            #
            # Unlike the durationless Lace branch below, this one can be
            # described: "becomes <colour> until end of turn" is printed about
            # permanents, never about the "spell or permanent" union that
            # branch's comment refuses for.
            _describe_targets(payload, node.subject)
        return (OracleInstruction("recolor_targets_until_eot", "", payload),)
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler recolours for {node.duration.kind!r}", node=node
        )
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
        # "…**that creature** becomes green" (Aisling Leprechaun). Nobody chose
        # it, so there is no target — but a block trigger *bound* it, and under
        # one of those events the pronoun names exactly one creature. The
        # binding travels as payload rather than as a second instruction kind:
        # which object an effect acts on is not a different effect.
        if (
            binds_block_pair(event, event_subject)
            and isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
        ):
            return (
                OracleInstruction(
                    "recolor_target_from_text", "",
                    {
                        "target_color": node.color,
                        SUBJECT_FROM_TRIGGER: BLOCK_PAIR_SUBJECT,
                    },
                ),
            )
        raise LoweringError("no handler for recolouring a non-targeted object", node=node)
    payload: dict[str, object] = {"target_color": node.color}
    if node.subject.filter.zone == "stack":
        # "{T}: Target **spell** becomes colorless." (Ersatz Gnomes.) The
        # printed noun names an object on the stack and nothing else, so the
        # picker is the stack one — the same description ``exile_target_spell``
        # and the counter lowering already emit, rather than a third spelling.
        #
        # Described here so the spec stops coming from the instruction *kind*.
        # ``recolor_target_from_text``'s row in ``targeting._KIND_TO_SPEC`` is
        # ``spell_or_permanent``, which is right for the Lace cycle and wrong
        # for this card by exactly one zone: with no description the shared kind
        # answered for both, and Ersatz Gnomes' ability could be aimed at a
        # permanent the card does not name — an illegal announcement under
        # CR 601.2c that the gate could not catch, because the gate reads the
        # same over-wide list the picker offers.
        payload["targets"] = {"quantifier": "target", "kind": "spell"}
    # Otherwise deliberately *not* described. The Lace cycle targets "spell or
    # permanent" — a union of a stack object and a battlefield object that the
    # `targets` vocabulary cannot express. Emitting the generic object shape
    # would derive "permanent" and drop spells on the stack from the picker, so
    # the description is omitted and legality.py keeps answering
    # `spell_or_permanent` until the vocabulary grows.
    return (OracleInstruction("recolor_target_from_text", "", payload),)


def _lower_land_type_swap(node: ast.LandTypeSwap) -> tuple[OracleInstruction, ...]:
    """Vision Charm's third mode: two chosen land types and a sweep between
    them (CR 305.7, CR 608.2d).

    One instruction, because the choice and the swap are one resolution: the
    answer names the set the sweep reaches, so a pair of instructions would need
    a scratchpad channel between them and a reader that refuses the second
    without the first. The handler arms the prompt, and the *resolver* performs
    the swap — the same arrangement Jinx's single-land version already has.

    Which catalog each half draws from is payload, because that is what the
    printed adjective says: "a land type" is all of CR 205.3i's, "a basic land
    type" is the five.
    """
    return (
        OracleInstruction(
            "swap_land_types_until_eot", "",
            {
                "first_basic": bool(node.first_basic),
                "second_basic": bool(node.second_basic),
            },
        ),
    )
