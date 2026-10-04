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
# Two of its names are deliberately *not* here — `_targeted_specs` and
# `card_divided_target_description` have no reader outside that module, and a
# re-export nobody pulls through is the dead binding `test_import_hygiene`
# exists to catch.
from ._targets import (SEVERAL_DESTROY_NARROWINGS,
                       _describe_several_card_targets,
                       _describe_several_targets, _describe_targets, _is_target,
                       _names_several_targets, _refuse_unfused_distinctness,
                       _targets_only, _targets_payload,
                       card_divided_each_description,
                       card_divided_shares_payload,
                       divided_target_description, _optional_slot_key)
# …and the ordered-roles half of the same subject, from the module it split
# into (`_roles`). Imported from its own home rather than pulled through
# `_targets`, which would be a re-export chain nobody reads the middle of;
# `DEPENDENT_TARGET_RELATIONS` and `describe_sequence_target_roles` stay out
# for the reason above — their readers are that module and `lower` itself.
from ._roles import (PRIMARY_TARGET_ROLE, describe_independent_target_roles,
                     describe_target_roles)


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


def split_color_choice(described: dict) -> tuple[tuple, dict, dict]:
    """*described* with a colour chosen during this resolution lifted out:
    the instructions to run first, the filter without the phrase, and the keys
    the caller adds **after its testability gate**.

    :func:`split_creature_type_choice` one characteristic over, and it reads
    both printed spellings of the one narrowing (CR 608.2d):

    * "…**of the color of your choice**" (Wash Out) — nobody has chosen, so the
      ``choose_color`` step goes in front, asked of the spell's controller
      (``chooser: "you"``, the step every other "of your choice" colour uses);
    * "…**of that color**" (Dromar, the Banisher) — an earlier sentence chose,
      so there is no prelude and only the read.

    Either way the sweep carries ``color_filter_from``, the key Persecute's
    discard already reads, naming the scratchpad slot the choosing step writes.
    A handler with nothing in that slot sweeps **nothing**; read as "no
    narrowing" it would take the board.
    """
    chose_here = bool(described.get("color_of_your_choice"))
    if not chose_here and not described.get("color_chosen_this_way"):
        return (), described, {}
    from ...oracle_types import CHOSEN_COLOR_THIS_WAY, OracleInstruction

    rest = {
        key: value for key, value in described.items()
        if key not in ("color_of_your_choice", "color_chosen_this_way")
    }
    prelude = (
        (OracleInstruction("choose_color", "", {"chooser": "you"}),)
        if chose_here else ()
    )
    return prelude, rest, {"color_filter_from": CHOSEN_COLOR_THIS_WAY}


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


def _is_attached_host_pronoun(subject: ast.Recipient) -> bool:
    """Whether *subject* is "**it**" standing for the attachment's host.

    "When enchanted creature attacks, return **it** and this Aura to their
    owners' hands at end of combat." (Contempt.) ``rebinding`` copies the
    trigger's own subject onto the pronoun, so the "it" of an attached trigger
    arrives carrying ``is_enchanted`` — the same filter "enchanted creature"
    spells in full, which is what makes the two phrases one reading.

    Its own predicate rather than :func:`_is_enchanted` alone because the
    quantifier is what the *bound-object* readers have to see: they claim every
    bare "it" first and then refuse, so a pronoun that names the host has to be
    recognised in front of them, exactly as ``_returns_itself_to_the_battlefield``
    recognises the one that names the source.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and subject.filter.is_enchanted
    )




def _source_return_reach(event: str | None) -> dict[str, object]:
    """The zone payload for "return **this <noun>** to its owner's hand".

    Two sentences, one printed the same way. Puppet Master's is the rider on an
    *immediate* trigger: CR 704.5m has usually swept the Aura into a graveyard
    by the time it resolves, so the handler has to reach that pile — the card
    there is the object the ability is still resolving about.

    Contempt's is the effect of a **delayed** ability a whole combat step later.
    CR 400.7 makes the card in the graveyard a different object from the
    permanent the ability was created about, so reaching it there returns
    something the card does not name: an Aura destroyed in response would come
    back to its owner's hand anyway, which is a strictly better card.

    So the delayed reading says outright which zone it reaches, and the
    immediate one keeps the payload it had — a differential over the pool is
    what says the two sets of cards are the ones this describes.

    The three event names that are *both* a delayed event and a trigger
    condition (``creature_blocks``, ``land_tapped_for_mana``,
    ``you_cast_spell``) are harmless here: under each of them as an immediate
    trigger the source is a permanent on the battlefield, which is the zone
    this payload names.
    """
    from ...delayed_triggers import DELAYED_EVENTS

    return {"from": "battlefield"} if event in DELAYED_EVENTS else {}


def _is_you(recipient: ast.Recipient) -> bool:
    return isinstance(recipient, ast.PlayerRef) and recipient.kind == "you"


# ---------------------------------------------------------------------------
# Power / toughness
# ---------------------------------------------------------------------------


def _signed(amount: ast.Amount, negative: bool) -> int | str | dict:
    """One half of a printed P/T modification, sign and all.

    "Target creature gets **-X**/+X until end of turn." (Belbe's Armor.)
    "All creatures get +X/**-X** until end of turn." (Flowstone Slide.) A
    negated *variable* is ``{"times_x": -1}`` — the shape a "-1/-1 **for
    each** …" repetition already lowers to (``_amounts._per_each_amount``), so
    the sign rides inside the amount and ``resolve_amount`` applies it wherever
    the number is resolved. A separate ``*_negative`` flag beside a bare ``"x"``
    would be honoured only by the handlers taught to read it, and every other
    one would pump by +X — the direction that grows the creature the card
    shrinks. A reader that does ``int()`` on its amount refuses the dict
    loudly instead (the static channels in ``grammar/statics.py`` check
    ``isinstance(..., int)`` and refuse in their own words).
    """
    value = _amount_payload(amount)
    if negative and isinstance(value, int):
        return -value
    if negative:
        return {"times_x": -1}
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


def variable_mana_payload(
    cost: "ast.ManaCost", *, what: str, node: object = None
) -> dict[str, object]:
    """The symbol dict a printed cost becomes, with ``{X}`` left variable.

    ``{X}`` becomes a **generic** pip whose amount is the string ``"x"``, which
    is the one channel every amount in this engine resolves an X through: by the
    time a handler runs, the announced X is on ``context.x_value``. So "you may
    pay {X}" (Primordial Ooze) and "unless their controller pays {X}" (War Tax)
    are ordinary costs with one number read late, not a second prompt.

    A second X refuses: "{X}{X}" would mean twice the announced number and this
    carries the amount once. So does "{X}{2}", which would fold a printed
    constant and a variable into one number the card never named. Nothing in the
    pool prints either, and guessing which reading was meant is exactly what a
    refusal is for.

    Here rather than in one of the families that reads it: the optional payment
    (``lowering/control_flow.py``) and the combat tolls (``lowering/combat.py``)
    are two families and neither may import the other, so the conversion sits on
    the floor they share. Two copies would be two answers to "what does a
    printed {X} become", free to differ — and the one that differed would be a
    cost charged at a number the card never announced.

    *what* names the clause in a refusal, because the two callers describe
    themselves differently and a shared message would name the wrong one.
    """
    pips = dict(cost.pips)
    variable = pips.pop("X", 0)
    if variable > 1:
        raise LoweringError(f"{what} reads one X, not several", node=node)
    if variable and pips.get("generic"):
        raise LoweringError(
            f"{what} cannot mix X with a printed generic cost", node=node
        )
    payload: dict[str, object] = dict(pips)
    if variable:
        payload["generic"] = "x"
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


#: CR 702.14a's family word, which names no land type of its own.
#: Beside :func:`_check_grantable`, its only reader.
LANDWALK = "landwalk"


def _check_grantable(keyword: str, node) -> None:
    """Refuse a grant of a keyword the engine cannot actually give.

    Two questions, and both have to be asked here: whether the *ability* is
    implemented at all (`grant_keyword` will put any word into layer 6, and a
    word with no behaviour behind it is a grant of nothing), and whether the
    keyword's printed argument came with it. "Rampage 2" grants +2/+2 per extra
    blocker; a bare "rampage" names no N, so there is nothing to grant — the
    parser leaves the number optional because a *test* for the ability does not
    want it (CR 702.23a defines the ability, the number parameterises it).

    On the floor beside :func:`_is_landwalk`, and for that helper's stated
    reason: two families read it. ``keywords`` asks it of a printed "gains …"
    and ``types`` asks it of the keyword list inside a **creature body** ("it
    becomes a 3/3 Knight creature with first strike"), which is the same layer-6
    grant written as part of an animation — so a second copy of the gate would
    be a second answer to "may this word be granted?", and the animation is
    exactly the place where a word with no behaviour behind it reads as having
    worked.

    The imports are function-local for :func:`_is_landwalk`'s reason too: this
    module is the bottom of the lowering layer, and `engine/keywords.py` and
    `engine/banding.py` sit underneath the grammar.
    """
    from ...banding import BANDS_WITH_OTHER
    from ...keywords import keyword_ability_name
    from ..vocabulary import IMPLEMENTED_KEYWORDS, NUMERIC_ARGUMENT_KEYWORDS

    name = keyword_ability_name(keyword)
    if name not in IMPLEMENTED_KEYWORDS and not _is_landwalk(keyword):
        raise LoweringError(
            f"granting {keyword!r} needs the keyword implemented", node=node
        )
    # The bare family name, which only a *removal* prints ("loses all 'bands
    # with other' abilities"). CR 702.22b's ability is the word plus a quality;
    # granting the family alone would put a word into layer 6 that names no set
    # of creatures, so the band it created would be one nothing could join —
    # the grant-of-nothing this function exists to refuse, in the one spelling
    # the keyword registry cannot catch, since the family word is what the
    # registry lists.
    if keyword == BANDS_WITH_OTHER:
        raise LoweringError(
            f"granting {keyword!r} needs the quality the band is with", node=node
        )
    # The same shape one family over. CR 702.14a's landwalk is the word plus a
    # land type, so the bare family word names no land and restricts no block
    # (`landwalk_requirement` answers None for it) — granting it would put a
    # word into layer 6 that does nothing. A *removal* of it is a real thing and
    # is what `expand_ability_removal` reads, which is why the refusal is here
    # and not in the registry.
    if keyword == LANDWALK:
        raise LoweringError(
            f"granting {keyword!r} needs the land type it walks", node=node
        )
    if name in NUMERIC_ARGUMENT_KEYWORDS and keyword == name:
        raise LoweringError(
            f"granting {keyword!r} needs the printed number it takes", node=node
        )
