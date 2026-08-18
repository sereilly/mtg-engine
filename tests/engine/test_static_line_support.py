"""Guard: a permanent's static line must be backed by something.

``_is_supported_static_creature_line`` decides whether a permanent's static text
counts as supported. It matches its whitelist literals with ``startswith``,
while the tables that actually *dispatch* those lines are anchored — so a line
can be admitted by a literal shorter than itself, match no dispatch pattern,
and fall through to a bare ``static_line``: the card reports `supported` and the
ability silently does nothing.

That is not hypothetical. Three shipped that way and were found by audit:

  * "can't attack unless defending player controls a <non-Island>" — gate
    matched the prefix "this creature can't attack", dispatch was anchored on
    Island, creature attacked freely.
  * "can't block creatures with power <not 2> or greater" — same shape, with
    the threshold baked into the instruction kind.
  * "As long as you control a Swamp, this creature gets +1/+1" — the *leading*
    word order was a gate literal but the dispatch regex only handled the
    trailing one, so the bonus never applied.

The sibling guard (``test_no_hollow_support.py``) checks instants and sorceries
by requiring a registered handler, and explicitly excludes permanents because
they legitimately work through statics, auras, layers and the text-keyed step
tables. This is the permanent-shaped version of the same property: a line is
acceptable when a derivation table claims it, or when it is listed below with
the code that carries it out.

Adding a card whose static line is admitted but implemented nowhere fails here.
If the line really is handled outside the instruction pipeline, add it to
``IMPLEMENTED_ELSEWHERE`` **naming the code** — the point of the entry is that
someone checked.
"""

import pytest

from engine.card_loader import load_catalog
from engine.characteristic_defining import dynamic_pt_for
from engine.combat_restrictions import combat_restriction_for
from engine.cost_modifiers import cost_modifier_claims_line
from engine.land_play_allowance import land_play_line
from engine.lord_buffs import lord_buff_for
from engine.global_statics import global_static_for
from engine.library_top import library_top_line
from engine.replacements import replacement_claims_line
from engine.oracle import (
    _is_supported_static_creature_line,
    compile_card_oracle,
    normalize_creature_line,
)
from engine.static_bonuses import static_bonus_for

# Distinctive prefix of the normalized line -> where the behavior lives.
# Every entry below was verified against the named code, not assumed.
IMPLEMENTED_ELSEWHERE: dict[str, str] = {
    "damage that would reduce your life total to less than 1":
        "replacements.py:_floor_life_at_one (Ali from Cairo)",
    "this creature doesn't untap during your untap step":
        "phases/untap_step.py via untap_restrictions.SELF_DOESNT_UNTAP_PHRASE",
    "you may choose not to untap this creature":
        "phases/untap_step.py via untap_restrictions.SELF_MAY_KEEP_TAPPED_PHRASE",
    "as long as this creature is attacking, prevent all damage deserts":
        "replacements.py:_prevent_desert_damage (Camel)",
    "prevent all damage that would be dealt to this creature by deserts":
        "replacements.py:_prevent_desert_damage (Desert Nomads)",
    "at end of combat, if this creature attacked or blocked":
        "phases/end_of_combat_step.py (Clockwork Beast)",
    "this creature enters with seven +1/+0 counters":
        "enter_effects.ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS",
    "this creature enters with x +1/+1 counters":
        "enter_effects.ENTERS_WITH_X_PLUS_1_1_COUNTERS",
    "you may have this creature enter as a copy":
        "enter_effects.COPY_CREATURE_ON_ENTER (Clone, Vesuvan Doppelganger)",
    "as long as this creature is untapped, noncreature artifacts":
        "mixins/effects.py:_untapped_artifact_protector_active (Guardian Beast)",
    "for each 1 damage that would be dealt to this creature":
        "prevention.py (Rock Hydra's +1/+1 counter shield)",
    "remove a corpse counter from this creature":
        "handlers/board_misc.py, reached as an activated ability (Scavenging Ghoul)",
    "this creature can block an additional creature":
        "phases/declare_blockers_step.py:_max_blocks_for (Two-Headed Giant of Foriys)",
    "as long as this creature is untapped, all damage that would be dealt to you":
        "phases/combat_damage_step.py (Veteran Bodyguard)",
    "as this creature enters, it becomes your choice of":
        "enter_effects.choosable_bodies, applied by "
        "permanent_state._apply_chosen_body (Primal Clay)",
    "protection from ":
        "handlers/_common.py protection checks",
}


def _derived(normalized: str) -> bool:
    """Claimed by a derivation table, which the compiler and the gate share."""
    return (
        dynamic_pt_for(normalized) is not None
        or combat_restriction_for(normalized) is not None
        or static_bonus_for(normalized) is not None
        or lord_buff_for(normalized) is not None
        # "You may play two additional lands on each of your turns" (Azusa,
        # Fastbond) — dispatched by mixins/effects.py:_land_play_allowances,
        # which reads every controlled permanent's own text through the same
        # table the gate asks. Only the permission clause is a claim: the
        # damage rider is a trigger the table does not own.
        or land_play_line(normalized) == "allowance"
        # "White spells cost {3} more to cast" (Gloom), "Creature spells with
        # flying you cast cost {1} less" (Watcher of the Spheres) — dispatched
        # by mixins/stack/casting.py and activation.py through
        # spell_cost_tax / spell_cost_reduction / ability_cost_tax, which read
        # every permanent's own text through the same table the gate asks.
        or cost_modifier_claims_line(normalized)
        # "If you would gain life, draw that many cards instead" (Lich), "…you
        # may put it on top of your library instead" (Library of Leng) —
        # dispatched by engine/replacements.py's interceptors, which self-select
        # on the permanent's own text through the same registry the gate asks.
        # The seventh derivation table, and the last to be asked here: it joined
        # when round 111 widened the creature gate from one hand-copied
        # replacement constant to the whole registry, and these two lines
        # arrived with it.
        or replacement_claims_line(normalized)
        # "All artifacts have …" (Energy Flux), "Creatures you control attack
        # each combat if able" (the Pirate Pursued Whale makes) — dispatched by
        # the CR 613 layer bridge, which appends the granted ability to each
        # affected permanent's effective card. The eighth derivation table, and
        # it reached the creature gate in round 130.
        or global_static_for(normalized) is not None
        # "Play with the top card of your library revealed", "…you may play
        # lands from the top of your library" — dispatched by
        # engine/library_top.py, which reads every controlled permanent's own
        # text through the same table the gate asks. The ninth derivation table.
        or library_top_line(normalized)
    )


def _unbacked_static_lines() -> list[tuple[str, str]]:
    unbacked: list[tuple[str, str]] = []
    for card in load_catalog():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for raw_line in card.oracle_text.split("\n"):
            normalized = normalize_creature_line(raw_line)
            if not normalized or not _is_supported_static_creature_line(raw_line):
                continue
            if _derived(normalized):
                continue
            if any(normalized.startswith(key) for key in IMPLEMENTED_ELSEWHERE):
                continue
            unbacked.append((card.name, normalized))
    return unbacked


def test_every_admitted_static_line_is_backed_by_code():
    unbacked = _unbacked_static_lines()
    assert not unbacked, (
        "static line(s) admitted as supported with nothing implementing them — "
        "the gate matched a whitelist prefix but no dispatch pattern claimed the "
        "line, so the ability silently does nothing:\n"
        + "\n".join(f"  {name}: {line}" for name, line in sorted(set(unbacked)))
    )


def test_the_acknowledgement_list_has_no_dead_entries():
    """An entry that stops matching any card is a stale claim, and a stale claim
    is how a real gap gets hidden: the next card whose line starts with that
    prefix inherits an acknowledgement nobody re-checked."""
    lines = [
        normalize_creature_line(raw_line)
        for card in load_catalog()
        for raw_line in card.oracle_text.split("\n")
        if normalize_creature_line(raw_line)
    ]
    dead = [
        key for key in IMPLEMENTED_ELSEWHERE
        if not any(line.startswith(key) for line in lines)
    ]
    assert not dead, f"acknowledgement entries matching no card: {dead}"


@pytest.mark.parametrize(
    "text",
    [
        # Each of these is a real bug that shipped, in the exact shape the gate
        # admits: a recognized prefix followed by a rider nothing implements.
        "This creature can't block creatures with flying.",
        "This creature can't attack unless you control a Wall.",
        "As long as you control a Wall, this creature gets +1/+1.",
        "This creature gets +1/+1 as long as you control a Zombie.",
        # The gate admitted every line starting "other " — a prefix, not a
        # template — so a lord whose effect the engine does not implement
        # reported supported and did nothing. All four of these are the shape
        # engine/lord_buffs.py refuses: an unmodelled effect, an unimplemented
        # keyword, an activated ability at a cost nothing charges, and an
        # unmodelled "as long as".
        "Other Goblins glimmer uncontrollably.",
        "Other Goblins get +1/+1 and have shadow.",
        'Other Zombies have "{5}: Regenerate this permanent."',
        "Other Goblins get +1/+1 as long as you control a Mountain.",
    ],
)
def test_an_unimplemented_rider_is_reported_unsupported(text):
    """Failing loud is the contract. Each of these is admitted by a whitelist
    prefix; none is implemented; all must be classified unsupported rather than
    compiled to a bare static line."""
    from engine.models import CardDefinition

    card = CardDefinition(
        name="Probe", mana_cost="{1}{B}", cmc=2.0, type_line="Creature — Horror",
        oracle_text=text, colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(),
        raw={"name": "Probe", "type_line": "Creature — Horror",
             "power": "2", "toughness": "2"},
    )
    assert not compile_card_oracle(card).supported
