"""Lowering what the ``becomes`` verb produces.

Animation ("becomes a 2/2 creature"), a gained card type ("becomes an artifact
in addition to its other types"), a supertype ("becomes snow"), a basic land
type ("becomes a Swamp") — CR 205, CR 613 layer 4.

**The colour change is next door, in `colors.py`.** It moved in here when
`effects/types.py` was written — one production parses all five `becomes`
branches, and the argument was that the module reading a sentence and the
module lowering it should share a name — and this docstring listed it as "CR
105 and layer 5 and … here anyway". It left at 1,010 lines, the round "target
spell or permanent" stopped being read as "target permanent", along the line
the paragraph below already draws between what colour a permanent is and what
it **is**. So the family is named for the verb less one branch: what is left is
the four CR 205 lowerings, and the mirror with the parse side is a production
whose fifth branch lowers one module over (`test_grammar_layering` records it).

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

from ...oracle_types import CHOSEN_CREATURE_TYPE_THIS_WAY, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import untestable_filter_keys
from ._common import (_check_grantable, _describe_several_targets,
                      _describe_targets, _filter_payload, _is_source,
                      _is_target, _names_several_targets)
from ._events import _EVENT_SUBJECT_OBJECTS
from ..vocabulary import BASIC_LAND_WORDS


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
        # "…becomes a 3/6 Golem artifact creature **until end of combat**."
        # (Jade Statue.) A third kind for the reason there are two: the
        # window is which sweep can see the record, and a kind whose name
        # says one window while writing a record another sweep clears is a
        # lie no reader can see.
        #
        # **The keyword and colour halves refuse here.** The end-of-combat
        # sweep clears the animation record and the persistent P/T channel
        # and nothing else; a granted keyword or a colour override would
        # outlive the body it belongs to, which is a permanent left green,
        # or flying, after it has stopped being a creature. No card in the
        # pool prints either with this window, so the refusal costs nothing
        # and closes the near miss rather than shipping the leak.
        if node.until_end_of_combat:
            if node.keywords or node.colors or node.granted_ability_lines:
                raise LoweringError(
                    "the end-of-combat sweep ends an animation's body and "
                    "nothing it grants",
                    node=node,
                )
            kind = "animate_self_until_end_of_combat"
        else:
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
        if node.pt_from_triggering_spell or node.protection_from_triggering_spell:
            # Both read the spell a *trigger* fired on, and a sweep of a
            # described set is printed on no trigger in this pool. Refusing
            # names the missing piece; admitting it would animate the board at
            # 0/0 with no protection, which is a card doing strictly less than
            # it prints.
            raise LoweringError(
                "an animation sweep has no triggering spell to read", node=node
            )
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
    # "…a 3/3 Knight creature **with first strike**" (Opal Champion), "…a 2/1
    # red Warrior creature **with first strike**" (Ghitu Encampment). The words
    # go onto CR 613 layer 6 through `layer_bridge`'s animation collector, which
    # is the same channel a printed "gains first strike" writes — so they pass
    # the same gate, and for the reason `_check_grantable` states: a word with no
    # behaviour behind it is a grant of nothing, and inside a creature body it
    # is a grant of nothing that reads as having worked. The parse side admits
    # any keyword the catalog holds; this is what decides which of them the
    # engine can actually give.
    for keyword in node.keywords:
        _check_grantable(keyword, node)
    payload: dict[str, object] = {
        "power": node.power,
        "toughness": node.toughness,
        "subtypes": list(node.subtypes),
        "keywords": list(node.keywords),
        "card_types": list(node.card_types),
    }
    if node.colors:
        payload["colors"] = list(node.colors)
    if node.pt_from_triggering_spell:
        # "…an Illusion creature with power and toughness each equal to that
        # spell’s mana value." (Veiled Sentry.) The size is the *event’s*, so
        # it travels as the count spec every other resolution-time quantity
        # uses (`handlers/_common.count_from_payload`) rather than as a second
        # vocabulary only the animation understands — `triggering_spell` is the
        # object the cast fire site froze on the trigger’s context.
        payload["pt_count"] = {
            "object_characteristic": {
                "object": "triggering_spell",
                "characteristic": "mana_value",
                "offset": 0,
            }
        }
    if node.protection_from_triggering_spell:
        # "…with protection from each of that spell’s colors." (Opal Titan.)
        # A flag, because the colours are not on the card: CR 105.2 makes them
        # a characteristic of the spell, read at resolution off the same frozen
        # record the size above reads.
        payload["protection_from_triggering_spell_colors"] = True
    if node.granted_ability_lines:
        # "…a 4/4 Serpent creature **with "This creature can't attack unless
        # defending player controls an Island.""** (Veiled Serpent.) Carried,
        # never dropped: the quoted sentence is half of what the permanent
        # becomes, and an animation that granted the body and not the ability
        # is the silent narrowing this package refuses by construction. The
        # handler puts it on `engine/keywords.grant_ability_line`, which
        # ``effective_card`` folds back into the text the compiler reads.
        payload["granted_ability_lines"] = list(node.granted_ability_lines)
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
    if node.replaces_types:
        # "{0}: This permanent becomes an enchantment." (Opal Acrolith,
        # Hidden Stag's second line.) CR 205.1a's *replacement*, which is a
        # different record from the gain below and so a different kind: the
        # gain joins a type to whatever the permanent already had, and this one
        # says what it now is — the two cannot share a handler without a flag
        # deciding which of two channels to write, which is the shape this
        # package spells as two kinds.
        #
        from ...event_durations import EVENT_DURATION_KINDS

        if node.duration.kind is not None and node.duration.kind not in EVENT_DURATION_KINDS:
            # No *turn-step* sweep clears this channel — every duration in
            # ``_GAINED_TYPE_DURATIONS`` has one for the **gain**, and none of
            # them touches a replacement — so those windows would be a
            # replacement that never ends. The event-ended windows do have one
            # (`engine/event_durations.clear_set_card_types`), which is the
            # whole of why they are admitted and the others are not.
            raise LoweringError(
                f"no sweep ends a card-type replacement at {node.duration.kind}",
                node=node,
            )
        payload: dict[str, object] = {"card_types": list(node.card_types)}
        # Written only for a window that has one, so every payload compiled
        # before this duration existed stays the two-key dict it was.
        if node.duration.kind is not None:
            payload["duration"] = node.duration.kind
        if _is_source(node.subject):
            return (OracleInstruction("set_card_types_self", "", payload),)
        # "**Target creature** becomes an enchantment …" (Soul Sculptor.) The
        # same CR 205.1a replacement pointed somewhere else, and a different
        # kind for the reason the replacement is a different kind from the gain:
        # this one has a target to resolve and a picker to describe, and a flag
        # deciding which of two subjects a handler reads is the shape this
        # package spells as two kinds.
        if _is_target(node.subject):
            _describe_targets(payload, node.subject)
            return (OracleInstruction("set_card_types_target", "", payload),)
        raise LoweringError(
            "a card-type replacement names the ability's own source or a "
            "chosen target",
            node=node,
        )
    # The *gain* channel's own windows, asked after the replacement branch
    # above has answered for its own: the two write different records and are
    # swept by different code, so one duration table cannot speak for both — a
    # replacement admits exactly the event-ended windows
    # `engine/event_durations.py` ends, and this admits exactly the turn-step
    # ones the gained-type sweeps run.
    if node.duration.kind not in _GAINED_TYPE_DURATIONS:
        raise LoweringError(
            f"no handler holds a gained type for {node.duration.kind}", node=node
        )
    payload = {
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
#: "Until this creature leaves the battlefield" (Gaea's Liege, Graceful
#: Antelope) is the leaving transition's: the contribution is keyed on the
#: source and marked as ending with it, and ``remove_all_from_battlefield``
#: drops it whichever way the source goes.
_LAND_TYPE_DURATIONS = frozenset({
    None, "until_controllers_next_untap_step", "until_end_of_turn",
    "until_source_leaves",
})


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
    # "**X target lands** become Forests until end of turn." (Deepwood Elder.)
    # The several-target reading of the same sentence, opted into here the way
    # `_describe_several_targets` requires — the handler resolves a list, so
    # saying so is what stops the picker offering a second choice nothing
    # collects. Refused for the *choose a land type* form: Jinx's prompt is
    # armed for one land by its permanent id, and a list of lands would need a
    # prompt per land or a prompt that answers for all of them, neither of which
    # any card prints.
    several = _names_several_targets(node.subject)
    if not (_is_target(node.subject) or several):
        raise LoweringError(
            "a land-type change names one target land", node=node
        )
    if several and node.land_type == ast.CHOSEN_LAND_TYPE:
        raise LoweringError(
            "a chosen land type is asked of one land at a time", node=node
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
    if node.options:
        # "…becomes **a Plains or an Island**" (Tundra Kavu). The choice above
        # with the list the sentence narrows it to, carried so the prompt
        # offers exactly these and the resolver refuses any other (CR 608.2d).
        # Emitted only when the card prints alternatives, so every "the basic
        # land type of your choice" keeps a byte-identical payload.
        #
        # Basic land types only: the answer travels on the prompt Jinx's
        # choice uses, whose wire field is CR 305.6's five, so a printed
        # alternative outside them is one no seat could name — refused here
        # rather than offered and then unanswerable.
        if not named and all(option in BASIC_LAND_WORDS for option in node.options):
            payload["land_type_options"] = list(node.options)
        else:
            raise LoweringError(
                "a choice between printed land types is among basic land types",
                node=node,
            )
    if several:
        _describe_several_targets(payload, node.subject)
    else:
        _describe_targets(payload, node.subject)
    return (OracleInstruction("change_land_type_until", "", payload),)


def _lower_become_that_type(
    node: ast.BecomeThatType, produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Choose a creature type other than Wall. **Target creature becomes that
    type until end of turn.**" (Unnatural Selection.)

    CR 205.1a's subtype *set*: the chosen creature type replaces the creature
    types the permanent had, and leaves every other subtype alone (an animated
    Forest made a Goblin is still a Forest) — a layer-4 record with a
    timestamp, written by ``type_changes.gain_types``.

    Three refusals, each a way the sentence would otherwise mean something it
    does not say:

    * **"that type" needs a producer.** The words name whatever a "Choose a
      creature type" step of this same effect recorded; with none the handler
      would read an empty record for ever on a card reporting supported.
    * **one targeted creature.** The noun phrase is what the picker offers and
      the handler re-asks, so it is described; a set ("all creatures become
      that type") is a different write nothing here performs.
    * **until end of turn.** The only window with a sweep behind this record
      (the cleanup step ends a gained type by its ``duration``); any other,
      and the absent one, would be a creature type that never comes off.
    """
    if CHOSEN_CREATURE_TYPE_THIS_WAY not in produced:
        raise LoweringError(
            "'that type' names a type no step of this effect chose", node=node
        )
    if not _is_target(node.subject):
        raise LoweringError(
            "a chosen creature type is set on one target creature", node=node
        )
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "no sweep ends a creature-type change at "
            f"{node.duration.kind or 'no duration'}",
            node=node,
        )
    payload: dict[str, object] = {
        "subtype_from": CHOSEN_CREATURE_TYPE_THIS_WAY,
        "duration": "until_end_of_turn",
    }
    _describe_targets(payload, node.subject)
    described = (payload.get("targets") or {}).get("filter") or {}
    if described.get("type_filter") != "creature":
        # The record replaces *creature* types, so the phrase has to name a
        # creature: "target permanent becomes that type" would hand a land a
        # creature type and take nothing a land has away.
        raise LoweringError(
            "a creature type is set on a creature", node=node
        )
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "nothing tests this narrowing of the creature: "
            + ", ".join(sorted(untestable)),
            node=node,
        )
    return (OracleInstruction("set_target_creature_type", "", payload),)


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
