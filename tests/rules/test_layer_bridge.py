"""The layer system must reproduce the engine's existing P/T results.

``engine/layer_bridge.py`` recomputes power and toughness through CR 613's
layers and sublayers instead of the hand-ordered property in
``engine/models.py``. Before the property can be replaced, the two have to
agree — on every permanent the test suite produces, not just on the cases
someone thought to write down.

That is what the differential below does: it exercises the channel
combinations the engine actually uses and asserts both paths give the same
answer. The individual cases double as documentation of what each channel is.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from engine.copies import EXCEPT_COLOR, become_copy
from engine.land_types import change_land_type
from engine.layer_bridge import computed_pt
from engine.models import CardDefinition, Permanent


def _creature(power: str = "2", toughness: str = "2") -> CardDefinition:
    return CardDefinition(
        name="Test Creature", mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Test Creature", "type_line": "Creature — Test",
             "power": power, "toughness": toughness},
        power=power, toughness=toughness,
    )


def _reference_pt(perm: Permanent) -> tuple[int, int]:
    """The hand-ordered computation the layer system replaced, kept verbatim.

    ``Permanent.effective_power`` now goes through the layer engine, so
    comparing against it would compare the new implementation with itself. This
    is the old one, preserved so the differential keeps meaning something:
    7d switch → 7b set (until-end-of-turn beating permanent) → 7c additive.

    One channel was *renamed* under it rather than reimplemented:
    ``attacking_buff_power`` was the only state-qualified buff the engine could
    express, and it is now one entry in ``lord_buff_while`` alongside the
    untapped one Castle needs. The arithmetic below — including the bug on the
    switch branch — is unchanged, which is the whole point of keeping it.
    """
    meta = perm.metadata

    def _qualified(stat: str) -> int:
        index = 0 if stat == "power" else 1
        return int((meta.get("lord_buff_while") or {}).get(("attacking",), (0, 0))[index])

    def _base(key: str) -> int:
        card = perm.card
        value = card.base_power if key == "power" else card.base_toughness
        return value if value is not None else 0

    def _mods(stat: str) -> int:
        bonus = perm.power_bonus if stat == "power" else perm.toughness_bonus
        return (
            bonus
            + int(meta.get(f"static_buff_{stat}", 0))
            + int(meta.get(f"derived_buff_{stat}", 0))
        )

    def _one(stat: str, *, include_attacking: bool) -> int:
        if f"absolute_{stat}_until_eot" in meta:
            base = int(meta[f"absolute_{stat}_until_eot"])
        elif f"absolute_{stat}" in meta:
            base = int(meta[f"absolute_{stat}"])
        else:
            base = _base(stat)
        total = base + _mods(stat)
        if include_attacking and perm.attacking:
            total += _qualified(stat)
        return total

    if meta.get("pt_switched"):
        # The old code swapped which stat it read but did not carry the
        # attacking-only buffs across the switch.
        return (_one("toughness", include_attacking=False),
                _one("power", include_attacking=False))
    return (_one("power", include_attacking=True), _one("toughness", include_attacking=True))


def _both(perm: Permanent) -> tuple[tuple[int, int], tuple[int, int]]:
    return _reference_pt(perm), computed_pt(perm)


@pytest.mark.cr("613.4")
def test_printed_values_agree():
    perm = Permanent(card=_creature("3", "4"))
    current, layered = _both(perm)
    assert current == layered == (3, 4)


@pytest.mark.cr("613.4c")
def test_counters_agree():
    perm = Permanent(card=_creature())
    perm.power_bonus, perm.toughness_bonus = 2, 3
    current, layered = _both(perm)
    assert current == layered == (4, 5)


@pytest.mark.cr("613.4b", "613.4c")
def test_set_then_modify_agrees():
    perm = Permanent(card=_creature())
    perm.metadata["absolute_power"] = 0
    perm.metadata["absolute_toughness"] = 2
    perm.power_bonus = 1
    perm.toughness_bonus = 1
    current, layered = _both(perm)
    # 7b sets 0/2, then 7c adds +1/+1 on top of the new base — not of the
    # printed 2/2.
    assert current == layered == (1, 3)


@pytest.mark.cr("613.4b")
def test_until_end_of_turn_set_outranks_the_permanent_one():
    perm = Permanent(card=_creature())
    perm.metadata["absolute_power"] = 5
    perm.metadata["absolute_toughness"] = 5
    perm.metadata["absolute_power_until_eot"] = 0
    perm.metadata["absolute_toughness_until_eot"] = 1
    current, layered = _both(perm)
    assert current == layered == (0, 1)


@pytest.mark.cr("613.4d")
def test_switch_agrees():
    perm = Permanent(card=_creature("1", "4"))
    perm.metadata["pt_switched"] = True
    current, layered = _both(perm)
    assert current == layered == (4, 1)


@pytest.mark.cr("613.4c", "613.4d")
def test_switch_after_modification_agrees():
    perm = Permanent(card=_creature("1", "4"))
    perm.power_bonus = 3
    perm.metadata["pt_switched"] = True
    current, layered = _both(perm)
    assert current == layered


@pytest.mark.cr("613.4c")
def test_every_modification_channel_agrees():
    perm = Permanent(card=_creature())
    perm.power_bonus, perm.toughness_bonus = 1, 1
    perm.metadata["static_buff_power"] = 2
    perm.metadata["static_buff_toughness"] = 2
    perm.metadata["derived_buff_power"] = 3
    perm.metadata["derived_buff_toughness"] = 3
    current, layered = _both(perm)
    assert current == layered == (8, 8)


@pytest.mark.cr("613.4c")
def test_attacking_only_buffs_agree_in_both_states():
    for attacking in (False, True):
        perm = Permanent(card=_creature())
        perm.attacking = attacking
        perm.metadata["lord_buff_while"] = {("attacking",): (2, 1)}
        current, layered = _both(perm)
        assert current == layered, f"disagreed while attacking={attacking}"


@pytest.mark.cr("613.4c", "611.3a")
def test_an_untapped_only_buff_is_evaluated_when_pt_is_read():
    """Castle's "Untapped creatures you control get +0/+2". The qualifier is
    checked here rather than when the board was last recomputed, so a creature
    that taps — by attacking, or for a cost — loses the bonus at once. It used
    to be contributed unconditionally at recompute time, which left an attacking
    creature holding +0/+2 until the next state-based-action check."""
    perm = Permanent(card=_creature())
    perm.metadata["lord_buff_while"] = {("untapped",): (0, 2)}
    assert computed_pt(perm) == (2, 4)

    perm.tapped = True
    assert computed_pt(perm) == (2, 2)


@pytest.mark.cr("613.4a")
def test_a_variable_printed_stat_is_not_read_as_zero():
    """"*" power is supplied by a characteristic-defining ability in 7a. The
    seed must leave it unset rather than defaulting to 0."""
    from engine.layer_bridge import seed_characteristics

    perm = Permanent(card=_creature("*", "*"))
    seeded = seed_characteristics(perm)
    assert seeded.power is None and seeded.toughness is None


@pytest.mark.cr("613.4")
def test_channel_combinations_agree_exhaustively():
    """Every combination of the channels, so agreement is not an artifact of
    the cases someone happened to write."""
    options = {
        "power_bonus": (0, 2),
        "absolute_power": (None, 0),
        "absolute_power_until_eot": (None, 4),
        "static_buff_power": (0, 1),
        "derived_buff_power": (0, 3),
        "pt_switched": (False, True),
    }
    keys = list(options)
    for combo in itertools.product(*(options[k] for k in keys)):
        settings = dict(zip(keys, combo))
        perm = Permanent(card=_creature("2", "5"))
        perm.power_bonus = settings.pop("power_bonus")
        for key, value in settings.items():
            if value not in (None, False):
                perm.metadata[key] = value
        current, layered = _both(perm)
        assert current == layered, f"disagreed for {settings}"


@pytest.mark.cr("613.4c", "613.4d")
def test_switching_carries_the_attacking_buff_across():
    """A case where the layer system is *right* and the old code was wrong.

    613.4d says the switch takes the values as they stand — after 7c, which
    includes an attacking-only anthem. The hand-ordered code swapped which stat
    it read but dropped the attacking buff on that path, so a switched attacker
    under Orcish Oriflamme lost the bonus.
    """
    perm = Permanent(card=_creature("1", "4"))
    perm.attacking = True
    perm.metadata["lord_buff_while"] = {("attacking",): (2, 0)}
    perm.metadata["pt_switched"] = True

    reference = _reference_pt(perm)
    layered = computed_pt(perm)
    # Printed 1/4, +2/+0 while attacking → 3/4, switched → 4/3.
    assert layered == (4, 3)
    assert reference == (4, 1), "the old path dropped the attacking buff"


# ---------------------------------------------------------------------------
# Layer 4 — type-changing
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1d")
def test_animating_a_land_makes_it_a_creature():
    """Kormus Bell / Living Lands / Jade Statue. Animation is a layer-4 type
    change, not a special case in whatever happens to ask."""
    land = CardDefinition(
        name="Swamp", mana_cost="", cmc=0.0, type_line="Basic Land — Swamp",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=("B",),
        raw={"name": "Swamp", "type_line": "Basic Land — Swamp"},
    )
    perm = Permanent(card=land)
    assert perm.is_creature is False

    perm.metadata["land_animated"] = True
    assert perm.is_creature is True
    assert perm.has_type("creature") is True
    # It is still a land (613.1d adds the type; it does not replace it).
    assert perm.has_type("land") is True


@pytest.mark.cr("613.1d")
def test_a_basic_land_type_change_replaces_the_subtype():
    """Evil Presence / Phantasmal Terrain: "enchanted land is a Swamp" replaces
    the land's types rather than adding to them, which is why it cannot share a
    channel with animation."""
    forest = CardDefinition(
        name="Forest", mana_cost="", cmc=0.0, type_line="Basic Land — Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=("G",),
        raw={"name": "Forest", "type_line": "Basic Land — Forest"},
    )
    perm = Permanent(card=forest)
    assert perm.has_type("forest") is True

    change_land_type(perm, "swamp", source="test")
    assert perm.has_type("swamp") is True
    assert perm.has_type("forest") is False


# ---------------------------------------------------------------------------
# Layer 5 — colour-changing
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1e")
def test_a_colour_override_replaces_the_printed_colour():
    card = CardDefinition(
        name="Test", mana_cost="", cmc=0.0, type_line="Creature — Test", oracle_text="",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Test", "type_line": "Creature — Test", "power": "2", "toughness": "2"},
        power="2", toughness="2",
    )
    perm = Permanent(card=card)
    assert perm.effective_colors == {"G"}

    perm.metadata["color_override"] = "R"
    assert perm.effective_colors == {"R"}


@pytest.mark.cr("613.2c", "707.2a", "707.9c")
def test_a_copys_colours_are_settled_in_layer_one_not_layer_five():
    """A copy's colours are a *copiable value*, so they arrive in the seed.

    This test used to assert the opposite — that ``copied_colors`` applied as a
    layer-5 effect and that an absent record left the printed colour — which is
    what made Vesuvan Doppelganger's exception unwriteable: "keeps its own
    colour" and "the copied artifact had no colours to record" were the same
    state. Under layer 1 the two are different contributions, and both are
    checked here.
    """
    doppelganger = CardDefinition(
        name="Doppelganger", mana_cost="{3}{U}", cmc=4.0, type_line="Creature — Shapeshifter",
        oracle_text="", colors=("U",), color_identity=("U",), keywords=(), produced_mana=(),
        raw={"name": "Doppelganger", "type_line": "Creature — Shapeshifter",
             "power": "0", "toughness": "0"},
        power="0", toughness="0",
    )
    perm = Permanent(card=doppelganger)
    assert perm.effective_colors == {"U"}

    green = Permanent(
        card=dataclasses.replace(_creature("6", "4"), colors=("G",), color_identity=("G",))
    )

    # Clone: every copiable value, colour included.
    clone = Permanent(card=doppelganger)
    become_copy(clone, green)
    assert clone.effective_colors == {"G"}
    assert (clone.effective_power, clone.effective_toughness) == (6, 4)

    # Vesuvan Doppelganger: everything except colour (CR 707.9c), so the blue
    # derived from its own mana cost is retained *by the fold*, positively.
    vesuvan = Permanent(card=doppelganger)
    become_copy(vesuvan, green, copies=EXCEPT_COLOR)
    assert vesuvan.effective_colors == {"U"}
    assert (vesuvan.effective_power, vesuvan.effective_toughness) == (6, 4)

    # A copy of a colourless object is colourless — not "kept its own colour
    # because nothing was recorded", which is what the stamped model gave.
    colourless = Permanent(card=_creature("1", "1"))
    copy = Permanent(card=doppelganger)
    become_copy(copy, colourless)
    assert copy.effective_colors == set()


@pytest.mark.cr("613.4")
def test_every_pool_creature_agrees(catalog):
    """The whole card pool at rest: printed values and any characteristic
    already stamped on a fresh permanent."""
    for card in catalog:
        if card.primary_type != "creature":
            continue
        perm = Permanent(card=card)
        current, layered = _both(perm)
        assert current == layered, f"{card.name} disagreed: {current} vs {layered}"
