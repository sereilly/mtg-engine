"""The mutable mirror of ``ast.ObjectFilter``, and the copy out of it.

Two objects and one subject. ``_FilterDraft`` is what a noun phrase accumulates
into while it is being read, and :func:`_build_object_filter` is the
hand-written copy that freezes it — and they are one module because they are one
**bug**. The filter is frozen and the draft is not, the field lists are written
twice, and a field that is on one and not the other loses a printed narrowing
without a word: the phrase parses, the card compiles, and the effect reaches a
strictly larger set than the card prints. Nothing in this repo can see that.
``--hollow-lines`` only finds a line that produced no ability part and
``parse_coverage`` only asks whether *something* claimed the sentence, so the
guard over the pair (``test_every_filter_draft_field_is_carried_into_the_object_filter``
and its sibling) is the only instrument there is. A guard over two halves wants
them in one file.

Split out of ``nouns.py`` at Exodus’ second wave, when the paragraph
recording why the draft is ``slots=True`` took that module four lines past the
thousand-line guard. The cut is the one ``nouns``’ own title draws: that file
is "what a printed noun phrase *describes*", the reading of words off a stream,
and neither object here reads a token. The draft is not even ``nouns``’
property — five modules write onto it (``nouns``, ``postmodifiers``, ``zones``,
``seat_relations``, ``histories``), each taking it as a parameter, which is
exactly the shape SET_PLAYBOOK.md gives for a thing that belongs below the
family that happens to have declared it.

It is the bottom of the parse side, under ``readers``: it reads ``ast`` and the
dataclass machinery and nothing else, and nothing here is a production.
``nouns`` re-exports both names so every existing caller keeps its import,
exactly as it re-exports ``readers`` and ``bounds``.

No mirror name to reuse. ``ast/_references.py`` holds the ``ObjectFilter`` this
mirrors and ``ast/_payloads.py`` holds the other direction out of it
(``to_payload``), so the two words already spoken for on that side are the
frozen node and its payload; the *draft* is a parse-side object with no AST twin
at all, and the repo has called it "the draft" since ``postmodifiers`` was cut
out of this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast









@dataclass(slots=True)
class _FilterDraft:
    """The half-built filter a noun phrase accumulates, one field per
    restriction the phrase can print.

    Mutable, and a mirror of the frozen `ast.ObjectFilter` it becomes. It
    exists because `parse_object_filter` reads a phrase in sections — a head
    noun, then leading adjectives, then trailing postmodifiers — and each
    section may set any of them. Passing forty-seven locals between those
    sections is what kept them in one 795-line function; passing one draft
    is what lets the postmodifiers live in their own module.

    No `build()` here on purpose: the sole caller constructs the
    `ObjectFilter` itself, because several fields are massaged on the way
    out (tuples from lists, a zone dropped when it is the default) and a
    builder would be a second place that knows those rules.

    ``slots=True`` is the point of this being a class at all, and it is load
    bearing. Five modules write onto this draft — `nouns`, `postmodifiers`,
    `zones`, `seat_relations`, `histories` — and on a plain dataclass a write to
    a field it does not declare *succeeds*: Python makes the attribute,
    `_build_object_filter` below never looks for it, and the narrowing is gone.
    Nothing raises and nothing fails; the phrase simply reads as **wider than
    the card prints**, which is the failure direction no instrument in this repo
    can see. `--hollow-lines` only finds a line that produced no ability part
    and `parse_coverage` only asks whether *something* claimed the sentence, so
    a dropped "that are enchanted" reports a fully supported card that sweeps
    the board. With slots the same write is an `AttributeError` at the line that
    made the mistake. The two fields whose comments below record having been
    lost this way, `enchanted_only` and `colored`, are what it costs when it is
    absent.
    """

    card_types: list[str] = field(default_factory=list)
    supertypes: list[str] = field(default_factory=list)
    subtypes: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    excluded_colors: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    excluded_subtypes: list[str] = field(default_factory=list)
    excluded_supertypes: list[str] = field(default_factory=list)
    with_keywords: list[str] = field(default_factory=list)
    without_keywords: list[str] = field(default_factory=list)
    controller: str | None = None
    owned_by: str | None = None
    owner_or_controller: str | None = None
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    any_states: tuple[str, ...] = field(default_factory=tuple)
    blocking_source: bool = False
    blocking_attached_host: bool = False
    blocked_or_was_blocked_this_turn: bool = False
    blocking_target: ast.ObjectFilter | None = None
    blocking_bound_target: bool = False
    blocked_by_bound_object: bool = False
    in_combat_with_bound_object: bool = False
    blocked_by_target_object: ast.ObjectFilter | None = None
    blocked_by_source: bool = False
    # "…creatures **that blocked this creature this turn**" (Joven's Ferrets)
    # — see the field of the same name on ``ast.ObjectFilter``.
    blocked_source_this_turn: bool = False
    tapped_to_pay_for_source_this_turn: bool = False
    #: "…other than enchanted creature" (Kjeldoran Pride). The Aura's host
    #: excluded by identity, which ``other_than_source`` cannot say: the
    #: source is the Aura, and no creature is ever it.
    other_than_attached_host: bool = False
    banded_with_source: bool = False
    attacking_you: bool = False
    # "…creature **that attacked you this turn**" (Jabari's Influence) — see
    # the field of the same name on ``ast.ObjectFilter``.
    attacked_you_this_turn: bool = False
    power: ast.Comparison | None = None
    mana_value: ast.Comparison | None = None
    #: See ``ast.ObjectFilter.mana_value_at_most_counters``.
    mana_value_at_most_counters: str | None = None
    #: See ``ast.ObjectFilter.mana_value_equals_source_counters``.
    mana_value_equals_source_counters: str | None = None
    #: See ``ast.ObjectFilter.power_at_most_source_counters``.
    power_at_most_source_counters: str | None = None
    #: See ``ast.ObjectFilter.power_greater_than_cards_in_hand``.
    power_greater_than_cards_in_hand: str | None = None
    toughness: ast.Comparison | None = None
    # "…with power equal to or greater than the enchanted creature's toughness"
    # (Ironclaw Curse) — see ``ast.SourceRelativeComparison``.
    characteristic_vs_source: "ast.SourceRelativeComparison | None" = None
    other_than_source: bool = False
    is_source: bool = False
    is_enchanted: bool = False
    not_enchanted: bool = False
    #: "…**that are enchanted**" (Song of Serenity) — see
    #: ``ast.ObjectFilter.enchanted_only``. Set by the postmodifier reader, and
    #: it has to be declared here *and* copied out below: this draft is an
    #: ordinary dataclass, so writing a field it does not declare succeeds and
    #: is then dropped on the floor when the filter is built — the phrase reads
    #: as unnarrowed and the card sweeps every creature on the board.
    enchanted_only: bool = False
    is_card: bool = False
    with_plus1_counter: bool = False
    # "with a <kind> counter on it" (Bounty Hunter) — see
    # ``ast.ObjectFilter.with_named_counter``.
    with_named_counter: str | None = None
    nontoken: bool = False
    # "that's one or more colors" (Ugin, the Spirit Dragon's −X) — see the
    # field of the same name on ``ast.ObjectFilter``. Declared here because
    # the postmodifier that reads the phrase wrote a *bare local* instead: an
    # undeclared draft attribute is dropped by the builder below, and a bare
    # local is dropped before it even gets that far, so the guard on this
    # mirror could not see it either.
    colored: bool = False
    # "permanents **of the chosen color**" (Psychic Allergy) — see
    # ``ast.ObjectFilter.chosen_color``.
    chosen_color: bool = False
    #: See ``ast.ObjectFilter.chosen_keyword``.
    chosen_keyword: bool = False
    # "Creatures **of the chosen type**" (An-Zerrin Ruins) — see the field of
    # the same name on ``ast.ObjectFilter``.
    chosen_creature_type: bool = False
    #: See ``ast.ObjectFilter.creature_type_of_your_choice``.
    creature_type_of_your_choice: bool = False
    # "…all cards **of that color**" (Persecute) — see the field of the same
    # name on ``ast.ObjectFilter``.
    color_chosen_this_way: bool = False
    # "Each **land** of the chosen type" (Shimmer) — see the field of the same
    # name on ``ast.ObjectFilter``.
    chosen_land_type: bool = False
    # "…that didn't attack this turn" / "…that couldn't attack" — see
    # ``ast.ObjectFilter``.
    attacked_this_turn: bool | None = None
    could_attack_this_turn: bool | None = None
    # "…**you cast this turn**" — see ``ast.ObjectFilter``.
    cast_by_you_this_turn: bool = False
    # "…except for creatures the player hasn't controlled continuously since
    # the beginning of the turn" (Total War) — see ``ast.ObjectFilter``.
    controlled_since_turn_start: bool | None = None
    token_only: bool = False
    their_choice: bool = False
    chosen_by_opponent: bool = False
    not_chosen_this_way: bool = False
    # "…**on the battlefield**" (An-Havva Constable) — see
    # ``ast.ObjectFilter.on_the_battlefield``.
    on_the_battlefield: bool = False
    named: str | None = None
    #: See ``ast.ObjectFilter.not_named`` / ``not_named_source`` /
    #: ``with_protection_from``.
    not_named: str | None = None
    not_named_source: bool = False
    with_protection_from: str | None = None
    # "…with a name originally printed in the <Set> expansion" -- see
    # ``ast.ObjectFilter.original_expansion``.
    original_expansion: str | None = None
    attached_to: str | None = None
    attached_to_filter: ast.ObjectFilter | None = None
    attached_to_target: ast.ObjectFilter | None = None
    # "…**whose controller controls an Island**" (Seasinger) — see
    # ``ast.ObjectFilter``.
    controller_controls: ast.ObjectFilter | None = None
    of_bound_type: bool = False
    # Five relative narrowings the postmodifier scan writes. Declared here like
    # every other field rather than defaulted onto the instance mid-parse, which
    # is where they used to live: two conventions for "a field of the draft" is
    # one convention too many, and only a declared field can be checked against
    # what `_build_object_filter` copies.
    not_ability_targeted_by_same_name: bool = False
    # Three narrowings Eye of Singularity prints -- see the fields of the same
    # names on ``ast.ObjectFilter``.
    shares_name_with_another: bool = False
    name_from_event: bool = False
    excluded_basic_lands: bool = False
    created_with_source: bool = False
    #: See ``ast.ObjectFilter.put_onto_battlefield_by_source``.
    put_onto_battlefield_by_source: bool = False
    in_combat_with_source: bool = False
    was_dealt_damage_this_turn: bool = False
    dealt_damage_to_source_this_turn: bool = False
    zone: str = "battlefield"
    zone_owner: ast.PlayerRef | None = None
    saw_head: bool = False
    type_match: str = "any"
    subtype_match: str = "any"
    any_classes: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    targets_object: ast.ObjectFilter | None = None
    target_count: int | None = None


def _build_object_filter(d: "_FilterDraft") -> ast.ObjectFilter:
    """*d* as the frozen filter it becomes.

    A free function rather than a method on the draft, and rather than the
    inline expression it used to be: the mirror is hand-written, so a field the
    postmodifier parsers set and this does not copy is **silently dropped** — a
    draft is an ordinary dataclass, so the assignment succeeds, the phrase
    parses, and the restriction vanishes. "target creature it's blocking" was
    written that way and dropped its whole relation.

    Naming it is what lets `tests/engine/test_grammar_parser.py` build an empty
    draft and check that every declared field arrives, which no reading of an
    inline expression could do.
    """
    return ast.ObjectFilter(
        card_types=tuple(d.card_types),
        type_match=d.type_match,
        subtype_match=d.subtype_match,
        supertypes=tuple(d.supertypes),
        subtypes=tuple(d.subtypes),
        colors=tuple(d.colors),
        excluded_colors=tuple(d.excluded_colors),
        excluded_types=tuple(d.excluded_types),
        excluded_subtypes=tuple(d.excluded_subtypes),
        excluded_supertypes=tuple(d.excluded_supertypes),
        with_keywords=tuple(d.with_keywords),
        without_keywords=tuple(d.without_keywords),
        not_ability_targeted_by_same_name=d.not_ability_targeted_by_same_name,
        shares_name_with_another=d.shares_name_with_another,
        name_from_event=d.name_from_event,
        excluded_basic_lands=d.excluded_basic_lands,
        any_classes=d.any_classes,
        targets_object=d.targets_object,
        target_count=d.target_count,
        created_with_source=d.created_with_source,
        put_onto_battlefield_by_source=d.put_onto_battlefield_by_source,
        controller=d.controller,
        owner=d.owned_by,
        owner_or_controller=d.owner_or_controller,
        tapped=d.tapped,
        attacking=d.attacking,
        blocking=d.blocking,
        any_states=d.any_states,
        blocking_source=d.blocking_source,
        blocking_attached_host=d.blocking_attached_host,
        blocked_or_was_blocked_this_turn=d.blocked_or_was_blocked_this_turn,
        blocking_target=d.blocking_target,
        blocking_bound_target=d.blocking_bound_target,
        blocked_by_bound_object=d.blocked_by_bound_object,
        in_combat_with_bound_object=d.in_combat_with_bound_object,
        blocked_by_target_object=d.blocked_by_target_object,
        blocked_by_source=d.blocked_by_source,
        blocked_source_this_turn=d.blocked_source_this_turn,
        tapped_to_pay_for_source_this_turn=d.tapped_to_pay_for_source_this_turn,
        other_than_attached_host=d.other_than_attached_host,
        banded_with_source=d.banded_with_source,
        attacking_you=d.attacking_you,
        attacked_you_this_turn=d.attacked_you_this_turn,
        blocked=d.blocked,
        power=d.power,
        toughness=d.toughness,
        mana_value=d.mana_value,
        mana_value_at_most_counters=d.mana_value_at_most_counters,
        mana_value_equals_source_counters=d.mana_value_equals_source_counters,
        power_at_most_source_counters=d.power_at_most_source_counters,
        power_greater_than_cards_in_hand=d.power_greater_than_cards_in_hand,
        zone=d.zone,
        zone_owner=d.zone_owner,
        is_card=d.is_card,
        with_plus1_counter=d.with_plus1_counter,
        with_named_counter=d.with_named_counter,
        nontoken=d.nontoken,
        colored=d.colored,
        chosen_color=d.chosen_color,
        chosen_keyword=d.chosen_keyword,
        chosen_creature_type=d.chosen_creature_type,
        creature_type_of_your_choice=d.creature_type_of_your_choice,
        color_chosen_this_way=d.color_chosen_this_way,
        chosen_land_type=d.chosen_land_type,
        attacked_this_turn=d.attacked_this_turn,
        could_attack_this_turn=d.could_attack_this_turn,
        cast_by_you_this_turn=d.cast_by_you_this_turn,
        controlled_since_turn_start=d.controlled_since_turn_start,
        token_only=d.token_only,
        their_choice=d.their_choice,
        named=d.named,
        not_named=d.not_named,
        not_named_source=d.not_named_source,
        with_protection_from=d.with_protection_from,
        original_expansion=d.original_expansion,
        other_than_source=d.other_than_source,
        is_source=d.is_source,
        is_enchanted=d.is_enchanted,
        not_enchanted=d.not_enchanted,
        enchanted_only=d.enchanted_only,
        attached_to=d.attached_to,
        attached_to_filter=d.attached_to_filter,
        attached_to_target=d.attached_to_target,
        controller_controls=d.controller_controls,
        of_bound_type=d.of_bound_type,
        in_combat_with_source=d.in_combat_with_source,
        was_dealt_damage_this_turn=d.was_dealt_damage_this_turn,
        chosen_by_opponent=d.chosen_by_opponent,
        not_chosen_this_way=d.not_chosen_this_way,
        on_the_battlefield=d.on_the_battlefield,
        dealt_damage_to_source_this_turn=d.dealt_damage_to_source_this_turn,
        characteristic_vs_source=d.characteristic_vs_source,
    )
