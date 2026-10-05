"""Domain — "the number of basic land types among lands you control".

CR 207.2c's ability word, printed in ten Invasion sentences and in every
sentence position a count can occupy. It is **one aggregate on the count spec**
(``distinct_basic_land_types``), read by one parser entry
(``distinct.parse_counted_objects``), carried on ``ObjectFilter.distinct`` and
lifted by ``lowering/_amounts.count_spec`` — so any sentence that spends a
count through that function reads domain for free.

That is also the way it can fail, and these guards are about the failure
rather than the feature: a sentence that reaches a count position *without*
going through ``count_spec`` would hand the bare filter "lands you control" to
whatever reads it, and a Wayfaring Giant would grow with every Plains. Nothing
crashes and every coverage instrument reads green, so the pool is swept.

Per-card behaviour is in ``tests/sets/test_inv_*.py``; this file is the
pool-wide half and the parts that name no card.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import ast, board_count_spec_for, compile_line
from engine.grammar.errors import LoweringError
from engine.grammar.lowering._amounts import count_spec
from engine.grammar.lowering._common import _filter_payload
from engine.handlers._common import evaluate_count
from engine.land_types import change_land_type
from engine.legality import _activated_lines, _cast_lines
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

DOMAIN = "basic land type among lands you control"
AGGREGATE = "distinct_basic_land_types"


def _specs(value):
    """Every count spec carrying the domain aggregate anywhere under *value*."""
    found = []
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = [getattr(value, field.name) for field in dataclasses.fields(value)]
    if isinstance(value, dict):
        if value.get("aggregate") == AGGREGATE:
            found.append(value)
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_specs(item))
    return found


def _lands(game, seat, lea, *names):
    placed = []
    for name in names:
        perm = Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        placed.append(perm)
    return placed


@pytest.fixture()
def duel():
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


# ---------------------------------------------------------------------------
# The count itself
# ---------------------------------------------------------------------------

_SPEC = {
    "zone": "battlefield", "owner": "you",
    "filter": {"type_filter": "land"}, "aggregate": AGGREGATE,
}


def test_domain_counts_distinct_types_between_zero_and_five(duel, set_pool):
    """CR 305.6: five basic land types. Two Forests are one, a Tropical Island
    is two, and a land with none of them is none."""
    lea = set_pool("LEA")
    me = duel.players[0]
    assert evaluate_count(duel, me, _SPEC) == 0

    _lands(duel, 0, lea, "Forest", "Forest")
    assert evaluate_count(duel, me, _SPEC) == 1

    _lands(duel, 0, lea, "Tropical Island")
    assert evaluate_count(duel, me, _SPEC) == 2

    duel._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("ARN")["Library of Alexandria"]), None
    )
    assert evaluate_count(duel, me, _SPEC) == 2

    _lands(duel, 0, lea, "Plains", "Swamp", "Mountain", "Badlands", "Tundra")
    assert evaluate_count(duel, me, _SPEC) == 5

    assert evaluate_count(duel, duel.players[1], _SPEC) == 0, "lands *you* control"


def test_domain_reads_a_lands_types_through_layer_four(duel, set_pool):
    """CR 305.7: an effect that sets a land's subtype replaces the old one. The
    count asks ``Permanent.basic_land_types`` — the computed answer — so a
    Forest made a Swamp is a Swamp and no longer a Forest, in both directions:
    it can add a type the board lacked and remove the only copy of another."""
    lea = set_pool("LEA")
    me = duel.players[0]
    forest, _island = _lands(duel, 0, lea, "Forest", "Island")
    assert evaluate_count(duel, me, _SPEC) == 2

    change_land_type(forest, "island", source="test")
    assert evaluate_count(duel, me, _SPEC) == 1, "two Islands now"

    change_land_type(forest, "mountain", source="test")
    assert evaluate_count(duel, me, _SPEC) == 2, "an Island and a Mountain"


def test_domain_is_scaled_like_every_other_aggregate(duel, set_pool):
    """One place applies the multiplier and the halving (``_scaled``), so the
    new aggregate must go through it — "twice the number of basic land types"
    is not a number a card may silently halve."""
    _lands(duel, 0, set_pool("LEA"), "Forest", "Island", "Swamp")
    me = duel.players[0]
    assert evaluate_count(duel, me, {**_SPEC, "multiplier": 2}) == 6
    assert evaluate_count(duel, me, {**_SPEC, "half": "down"}) == 1
    assert evaluate_count(duel, me, {**_SPEC, "offset": -1}) == 2


# ---------------------------------------------------------------------------
# Every count position reads it; no other position can
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, kind",
    [
        (f"This creature gets +1/+1 for each {DOMAIN}.", "dynamic_pt_bonus"),
        (f"Enchanted creature gets -1/-1 for each {DOMAIN}.", "dynamic_pt_bonus"),
        (
            f"{{3}}, {{T}}: Target creature gets +1/+1 until end of turn for each {DOMAIN}.",
            "pump_target_creature_until_eot",
        ),
        (f"You gain 2 life for each {DOMAIN}.", "target_gains_life"),
        (
            f"Create a 1/1 blue Bird creature token with flying for each {DOMAIN}.",
            "create_token",
        ),
        (f"Draw a card for each {DOMAIN}.", "draw_controller_cards"),
        (
            "~ deals X damage to any target, where X is the number of basic "
            "land types among lands you control.",
            "deal_damage",
        ),
        (
            "~ deals damage to any target equal to the number of basic land "
            "types among lands you control.",
            "deal_damage",
        ),
        (
            "Target creature gets +X/+X until end of turn, where X is the "
            "number of basic land types among lands you control.",
            "pump_target_creature_until_eot",
        ),
        (
            "Look at the top X cards of your library, where X is the number of "
            "basic land types among lands you control. Put one of those cards "
            "into your hand and the rest on the bottom of your library in any "
            "order.",
            "look_top_pick_to_hand",
        ),
    ],
)
def test_every_count_position_carries_the_domain_aggregate(line, kind):
    """Both inflections ("for each … type", "the number of … types") and every
    family that spends a count. A position that parsed the phrase and lowered a
    plain land count would compile, report supported and count the lands."""
    compiled = compile_line(line.replace("~", "Tribal Flames"), card_name="Tribal Flames")
    assert compiled.failure_reason is None, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.kind == kind
    [spec] = _specs(instruction.payload)
    assert spec["zone"] == "battlefield" and spec["owner"] == "you"
    assert spec["filter"] == {"type_filter": "land"}


@pytest.mark.parametrize(
    "line",
    [
        "Destroy target basic land type among lands you control.",
        "Destroy all basic land types among lands you control.",
        "Tap target basic land type among lands you control.",
        f"Add {{G}} for each {DOMAIN}.",
        "Whenever a basic land type among lands you control dies, draw a card.",
    ],
)
def test_the_phrase_is_refused_outside_a_count(line):
    """The reader is ``parse_counted_objects``, which only a count position
    calls — a target, a sweep and a trigger subject use the plain noun parser
    and stop at "type". Refusing is the loud direction; the quiet one is a
    sweep over "lands you control"."""
    compiled = compile_line(line, card_name="Test")
    assert not compiled.instructions
    assert compiled.failure_reason is not None


def test_a_lowering_that_builds_a_plain_payload_refuses_the_field():
    """The second gate, for a lowering that *is* handed the filter. ``distinct``
    has no ``to_payload`` key, so it is listed in ``CONDITIONALLY_EMITTED_FIELDS``
    and ``_filter_payload`` — the gate in front of every non-count consumer —
    refuses it by name rather than reducing "basic land types among lands" to
    "lands"."""
    described = ast.ObjectFilter(card_types=("land",), controller="you", distinct=AGGREGATE)
    assert "distinct" not in described.to_payload()
    with pytest.raises(LoweringError):
        _filter_payload(described)
    assert count_spec(described, None)["aggregate"] == AGGREGATE


def test_the_count_refuses_what_it_cannot_answer():
    """A card in a graveyard has only a printed type line, which is a different
    question (CR 613 applies to permanents); and two aggregates over one set is
    not a phrase."""
    in_graveyard = ast.ObjectFilter(
        card_types=("land",), zone="graveyard", is_card=True, distinct=AGGREGATE
    )
    with pytest.raises(LoweringError):
        count_spec(in_graveyard, None)
    on_board = ast.ObjectFilter(card_types=("land",), distinct=AGGREGATE)
    with pytest.raises(LoweringError):
        count_spec(on_board, None, aggregate="greatest_power")


# ---------------------------------------------------------------------------
# The census: every supported card printing the phrase carries the aggregate
# ---------------------------------------------------------------------------

def _cards_printing_domain():
    seen: dict[str, object] = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        text = (card.oracle_text or "").lower()
        if "basic land type among" in text or "basic land types among" in text:
            seen.setdefault(card.name, card)
    return list(seen.values())


def _census(cards):
    """``(examined, offenders)`` — the supported cards printing the phrase, and
    those of them whose compiled program holds no domain count anywhere."""
    examined, offenders = [], []
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined.append(card.name)
        carried = _specs([
            program.instructions,
            [ability.instruction for ability in program.activated_abilities],
            [ability.instruction for ability in program.triggered_abilities],
        ])
        if not carried:
            from engine.combat_restrictions import combat_restriction_for
            from engine.oracle_types import strip_ability_word

            carried = [
                found for line in (card.oracle_text or "").splitlines()
                for found in _specs(getattr(combat_restriction_for(
                    strip_ability_word(line).strip().lower().rstrip("."), card.name
                ), "payload", None))
            ]
        if not carried:
            offenders.append(card.name)
    return examined, offenders


def test_every_supported_card_printing_domain_counts_types():
    """The sweep the module docstring promises. A floor on how many it examined,
    because a census over nothing passes: Invasion alone prints the phrase on
    ten cards and all ten are supported."""
    examined, offenders = _census(_cards_printing_domain())
    assert len(examined) >= 10, examined
    assert not offenders, (
        f"{offenders} print 'basic land type(s) among' and compile with no "
        f"{AGGREGATE} count — the phrase was read as a plain land count"
    )


def test_the_census_names_the_defect_on_a_tree_that_has_it(monkeypatch):
    """Validated backwards. With the lift in ``count_spec`` disabled — the one
    line that turns the parsed phrase into the aggregate — every domain card
    still compiles and still reports supported, counting lands. The census must
    name them, or it is a census that cannot see the thing it is for."""
    import sys

    from engine.grammar.lowering import _amounts
    from engine.oracle_types import clear_compilation_caches

    cards = _cards_printing_domain()
    real = _amounts.count_spec

    def land_counting(filt, node, **kwargs):
        if getattr(filt, "distinct", None) is not None:
            filt = dataclasses.replace(filt, distinct=None)
        return real(filt, node, **kwargs)

    # Every module that imported the function by name holds its own reference.
    patched = 0
    for name, module in list(sys.modules.items()):
        if name.startswith("engine.grammar") and getattr(module, "count_spec", None) is real:
            monkeypatch.setattr(module, "count_spec", land_counting)
            patched += 1
    assert patched >= 3, "the lift has several importers; patch them all"
    clear_compilation_caches()
    try:
        examined, offenders = _census(cards)
    finally:
        monkeypatch.undo()
        clear_compilation_caches()
    assert len(examined) >= 10, "the defect leaves every card *supported*"
    assert len(offenders) >= 10, (examined, offenders)
    # …and the swap is put back: the same census is clean again.
    assert _census(cards)[1] == []


# ---------------------------------------------------------------------------
# "of each basic land type" — the abbreviation, on an invented card
# ---------------------------------------------------------------------------

def _invented_sorcery(text):
    return _mk_card(
        name="Territorial Claim", mana_cost="{G}", type_line="Sorcery", oracle_text=text
    )


def test_of_each_basic_land_type_is_five_conjuncts():
    """"A land of each basic land type" is read as what it abbreviates: a
    Plains *and* an Island *and* … — five ``controls`` conditions on the
    existing conjunction, each still a land."""
    compiled = compile_line(
        "You win the game if you control a land of each basic land type.",
        card_name="Territorial Claim",
    )
    assert compiled.failure_reason is None, compiled.failure_reason
    [gate] = compiled.instructions
    condition = gate.payload["condition"]
    assert condition["kind"] == "all_of"
    assert [c["filter"] for c in condition["conditions"]] == [
        {"type_filter": "land", "subtype_filter": name}
        for name in ("plains", "island", "swamp", "mountain", "forest")
    ]
    assert {c["kind"] for c in condition["conditions"]} == {"controls"}


@pytest.mark.parametrize(
    "lands, wins",
    [
        (("Plains", "Island", "Swamp", "Mountain", "Forest"), True),
        # Present is present: three duals and a basic hold all five types.
        (("Tundra", "Badlands", "Forest"), True),
        (("Plains", "Island", "Swamp", "Mountain"), False),
        (("Forest",) * 5, False),
        ((), False),
    ],
)
def test_an_invented_card_wins_on_a_land_of_each_basic_land_type(
    duel, set_pool, lands, wins
):
    """The behaviour test CLAUDE.md asks of a general production: an invented
    card with the printed sentence works. (Coalition Victory itself also needs
    "a creature of each color", which is another group's phrase.)"""
    card = _invented_sorcery(
        "You win the game if you control a land of each basic land type."
    )
    _lands(duel, 0, set_pool("LEA"), *lands)
    # The opponent holding all five is not "you".
    _lands(duel, 1, set_pool("LEA"), "Plains", "Island", "Swamp", "Mountain", "Forest")
    duel.players[0].hand.append(card)
    assert duel.cast_from_hand(0, "Territorial Claim").supported
    resolve_stack(duel)
    won = any("wins the game" in entry for entry in duel.log)
    assert won is wins, duel.log[-3:]


def test_of_each_composes_with_a_second_noun_and_refuses_what_it_cannot_say():
    both = compile_line(
        "You win the game if you control a creature and a land of each basic land type.",
        card_name="Territorial Claim",
    )
    assert both.failure_reason is None
    kinds = [c["filter"] for c in both.instructions[0].payload["condition"]["conditions"]]
    assert kinds[0] == {"type_filter": "creature"} and len(kinds) == 6

    for refused in (
        # A negated or "another" abbreviation is a sentence nothing prints.
        "You win the game if you control no land of each basic land type.",
        "You win the game if you control another land of each basic land type.",
        # Only a characteristic in the table may be distributed.
        "You win the game if you control a land of each mana value.",
    ):
        assert compile_line(refused, card_name="Territorial Claim").failure_reason


# ---------------------------------------------------------------------------
# The string-in door the attack toll uses
# ---------------------------------------------------------------------------

def test_board_count_spec_for_reads_a_count_of_your_own_board():
    spec = board_count_spec_for(
        "the number of basic land types among lands you control"
    )
    assert spec == _SPEC
    assert board_count_spec_for("the number of creatures you control") == {
        "zone": "battlefield", "owner": "you", "filter": {"type_filter": "creature"},
    }


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        # Nothing resolved, so no record, no target, no event and no other seat.
        "the number of cards in your hand",
        "the number of creatures that died this way",
        "the number of lands target opponent controls",
        "the number of creatures on the battlefield",
        "its power",
        "the greatest power among creatures you control",
        # Whole-phrase consumption.
        "the number of lands you control plus garbage",
    ],
)
def test_board_count_spec_for_refuses_what_a_static_cannot_evaluate(phrase):
    assert board_count_spec_for(phrase) is None


def test_an_attack_toll_admits_x_and_its_definition_together_or_not_at_all():
    """``{X}`` with no where-clause is a price nobody can name, and a
    where-clause over a printed number defines an X nothing reads."""
    from engine.combat_restrictions import combat_restriction_for

    stem = (
        "creatures can't attack you unless their controller pays {cost} for "
        "each creature they control that's attacking you"
    )
    counted = combat_restriction_for(
        stem.format(cost="{x}")
        + ", where x is the number of basic land types among lands you control"
    )
    assert counted is not None
    assert counted.payload["mana"] == {"generic": "x"}
    assert counted.payload["x_from_count"] == _SPEC

    printed = combat_restriction_for(stem.format(cost="{2}"))
    assert printed.payload["mana"] == {"generic": 2}
    assert "x_from_count" not in printed.payload, "Koskun Falls is untouched"

    assert combat_restriction_for(stem.format(cost="{x}")) is None
    assert combat_restriction_for(
        stem.format(cost="{2}") + ", where x is the number of lands you control"
    ) is None
    assert combat_restriction_for(
        stem.format(cost="{x}") + ", where x is the number of cards in your hand"
    ) is None


# ---------------------------------------------------------------------------
# An ability word in front of an activated ability (CR 207.2c)
# ---------------------------------------------------------------------------

def test_an_ability_word_does_not_make_an_activated_line_a_cast_line():
    """"Domain — {3}, {T}: Target creature gets …" is an activated ability. The
    cast/activated split used to ask the raw line, so the italic word in front
    of the cost made it a cast-time effect and the artifact appeared to target
    a creature as it was cast."""
    card = _mk_card(
        name="Test Armor", mana_cost="{4}", type_line="Artifact",
        oracle_text=(
            "Domain — {3}, {T}: Target creature gets +1/+1 until end of turn.\n"
            "Landfall — Whenever a land you control enters, you gain 1 life."
        ),
    )
    assert len(_activated_lines(card)) == 1
    assert _activated_lines(card)[0].startswith("domain")
    assert [line.split(" — ")[0] for line in _cast_lines(card)] == ["landfall"]


# ---------------------------------------------------------------------------
# The keep prompt's label
# ---------------------------------------------------------------------------

def test_a_keep_slot_is_labelled_by_its_narrowest_noun():
    """Global Ruin's five slots are each "a land" and one basic land type. A
    label reading the card type alone showed five identical "land" keeps while
    the engine refused two Plains."""
    from web.prompts import _keep_slot_noun

    assert _keep_slot_noun({"type_filter": "land", "subtype_filter": "plains"}) == "Plains"
    assert _keep_slot_noun({"type_filter": "artifact"}) == "artifact"
    assert _keep_slot_noun({}) == "permanent"


# ---------------------------------------------------------------------------
# "chooses from the …" — Global Ruin's spelling of Cataclysm's "from among the"
# ---------------------------------------------------------------------------

def test_the_bare_from_spelling_is_read_only_in_front_of_an_abbreviated_keep():
    """"Each player chooses **from the** lands they control a land of each
    basic land type" (Global Ruin) drops Cataclysm's "among". Reading the bare
    spelling for *every* keep list would make "among" a word Cataclysm's own
    sentence could lose with no change to its parse — a deletion-probe finding
    on a shipped card — so it is admitted only where it is printed: in front of
    an "of each" keep."""
    tail = ", then sacrifices the rest."
    cataclysm = (
        "Each player chooses from among the permanents they control an "
        "artifact, a creature, an enchantment, and a land" + tail
    )
    assert compile_line(cataclysm, card_name="Test").failure_reason is None
    assert compile_line(
        cataclysm.replace("from among", "from"), card_name="Test"
    ).failure_reason is not None

    ruin = (
        "Each player chooses from the lands they control a land of each basic "
        "land type" + tail
    )
    [keep] = compile_line(ruin, card_name="Test").instructions
    assert keep.kind == "keep_chosen_sacrifice_rest"
    assert keep.payload["pool"] == {"type_filter": "land"}
    assert keep.payload["who"] == "each_player"
    assert [slot["filter"]["subtype_filter"] for slot in keep.payload["slots"]] == [
        "plains", "island", "swamp", "mountain", "forest",
    ]
    assert {slot["count"] for slot in keep.payload["slots"]} == {1}
    # Both spellings of the pool mean the same five keeps.
    [also] = compile_line(ruin.replace("from the", "from among the"), card_name="Test").instructions
    assert also.payload == keep.payload
