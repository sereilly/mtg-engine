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
from engine.land_play_allowance import land_play_line
from engine.lord_buffs import lord_buff_for
from engine.ante import is_ante_deck_line
from engine.hand_size import hand_size_line
from engine.untap_restrictions import self_untap_line
from engine.grammar import compile_line
from engine.oracle import (
    _derived_static_claims,
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
    "as long as this creature is attacking, prevent all damage deserts":
        "replacements.py:_prevent_desert_damage (Camel)",
    "prevent all damage that would be dealt to this creature by deserts":
        "replacements.py:_prevent_desert_damage (Desert Nomads)",
    "at end of combat, if this creature attacked or blocked":
        "phases/end_of_combat_step.py (Clockwork Beast)",
    "this creature enters with seven +1/+0 counters":
        "enter_effects.ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS",
    "this creature enters with x +1/+1 counters":
        "enter_effects.enters_with_x_pt_counters",
    "you may have this creature enter as a copy":
        "enter_effects.COPY_CREATURE_ON_ENTER (Clone, Vesuvan Doppelganger)",
    "as long as this creature is untapped, noncreature artifacts":
        "mixins/effects.py:_untapped_artifact_protector_active (Guardian Beast)",
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
        # Fastbond) and "Players can't play lands" (Worms of the Earth) — both
        # dispatched by `mixins/effects.py:_land_play_refusal`, which reads
        # every controlled permanent's own text through the same table the gate
        # asks.
        #
        # Asked as "does the table claim this line", not "does it claim it as
        # an *allowance*". The equality here named one of the table's return
        # values, so when the prohibition was added to the same table this
        # guard reported Worms of the Earth as an unbacked line — while
        # `_land_play_refusal` was refusing land plays perfectly well. A guard
        # that re-spells part of what it checks invents a disagreement and then
        # reports it, which is the most expensive kind of failure because it
        # looks like a finding. The damage rider is still not a claim: it is a
        # trigger the table does not own.
        or land_play_line(normalized) in ("allowance", "prohibition")
        # **Every table the gate itself names**, asked of this one line
        # through `oracle._derived_static_claims` — the same function
        # `_is_supported_static_creature_line`'s siblings ask when they admit a
        # card. Seven arms stood here spelled out by hand (cost_modifiers,
        # replacements, prevention, global_statics, library_top, enter_effects,
        # and the two before them), which made this guard a *second copy* of
        # that list with one reader each: the copy had thirteen tables where the
        # gate had eighteen, so `evasion_negation` (round 27), `target_immunity`
        # (rounds 18/31) and `regeneration` (round 29) were admitted, dispatched
        # and enforced while this test reported all twelve of their lines as
        # implemented nowhere. Every one of them was a false alarm, and a false
        # alarm here is worse than none: it is twelve lines of noise standing in
        # front of the real gap this file exists to catch.
        #
        # `card_name` is deliberately **not** passed. A claim keyed by a card's
        # name (Island Sanctuary's `DRAW_STEP_MODIFIERS` entry) is a claim about
        # the whole card, and letting it answer here would let one hooked line
        # back every other line the card prints. Only the text-derived tables
        # get to answer a question about one line of text.
        or bool(_derived_static_claims(normalized, normalized, None))
        # "The chosen player's maximum hand size is four." (Cursed Rack) — the
        # eleventh derivation table, read by the cleanup step that enforces
        # CR 402.2 and by the gate that admits the line.
        or hand_size_line(normalized)
        # "This artifact doesn't untap during your untap step" / "You may choose
        # not to untap this artifact …" — the twelfth derivation table, and two
        # `IMPLEMENTED_ELSEWHERE` entries retired: those named the *creature*
        # spelling, so the artifact printings were unbacked by this guard while
        # the untap step read them perfectly well.
        or self_untap_line(normalized) is not None
        # "Remove this card from your deck before playing if you're not playing
        # for ante." — the thirteenth, and the only one whose enforcement site
        # is outside the game: CR 113.6a's deck-construction instruction, read
        # by `web/deck_legality.py` off the same constant the gate asks.
        or is_ante_deck_line(normalized)
        # The strongest claim of all, and the last asked: **the grammar lowered
        # this line to an instruction**. "This creature gets +X/+0, where X is
        # the greatest power among creature cards in your graveyard" (Carrion
        # Grub) is a `dynamic_pt_bonus` the parser produces directly, so no
        # derivation table names it and every table above answers no — while the
        # card carries a real instruction a real handler dispatches.
        #
        # Asked last on purpose: a table's claim says *which* code implements
        # the line, which is what the map above this function is for, and an
        # instruction only says that some code does. Both are backing; one is
        # more informative.
        or bool(compile_line(normalized).instructions)
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
        #
        # "…can't block creatures with **flying**" used to stand here; the whole
        # noun phrase is payload now and the blocker gate tests it, so the line
        # is implemented rather than admitted. Its place is taken by the same
        # sentence with a word the gate still cannot answer — a keyword no
        # behaviour is registered under makes the filter inert rather than
        # unreadable, so the restriction would forbid nothing.
        "This creature can't block creatures with shadow.",
        "This creature can't attack unless you control a Wall.",
        # "As long as you control a **Wall**…" and "…a **Zombie**" used to stand
        # here, and both are implemented now: `static_bonuses` reads "you control
        # <noun phrase>" through the grammar's own noun parser, so the condition
        # has a reader and the bonus tracks the board (round ICE 6). What is
        # still unimplemented is a **counted** version of the same clause, which
        # that branch refuses deliberately rather than answering as presence —
        # so the guard keeps its teeth in the shape it was written for.
        "As long as you control two or more Walls, this creature gets +1/+1.",
        "This creature gets +1/+1 as long as you control the most Zombies.",
        # The gate admitted every line starting "other " — a prefix, not a
        # template — so a lord whose effect the engine does not implement
        # reported supported and did nothing. All three of these are the shape
        # engine/lord_buffs.py refuses: an unmodelled effect, an unimplemented
        # keyword and an activated ability at a cost nothing charges.
        #
        # A fourth used to stand here — "…as long as you control two or more
        # Mountains" — because the condition parsed and `conditional_static_holds`
        # asked presence, so the threshold would have been dropped. The
        # evaluator counts now (round 27, for Angelic Voices' "you control **no**
        # nonartifact, nonwhite creatures"), so the line is implemented rather
        # than unimplemented, and the honest place for it is
        # `test_a_counted_anthem_condition_is_evaluated_as_a_count` below.
        "Other Goblins glimmer uncontrollably.",
        "Other Goblins get +1/+1 and have shadow.",
        'Other Zombies have "{5}: Regenerate this permanent."',
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


def test_a_counted_anthem_condition_is_evaluated_as_a_count():
    """"…as long as you control **two or more** Mountains" — the threshold rides
    the payload and is compared, rather than being read as "at least one".

    An invented card, because the point is the template: read as presence the
    buff would appear one Mountain early, which is a condition weaker than
    printed and the exact drop this test used to guard by refusing the line.
    """
    from engine import Game, PlayerState
    from engine.models import CardDefinition, Permanent

    def _card(name: str, type_line: str, text: str = "") -> CardDefinition:
        raw = {"name": name, "type_line": type_line}
        if "Creature" in type_line:
            raw.update(power="2", toughness="2")
        return CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
            colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
            raw=raw,
        )

    lord = Permanent(card=_card(
        "Probe", "Creature — Goblin",
        "Other Goblins get +1/+1 as long as you control two or more Mountains.",
    ))
    program = compile_card_oracle(lord.card)
    assert program.supported, program.reason
    condition = program.instructions[0].payload["condition"]
    assert (condition["count"], condition["op"]) == (2, "ge")

    goblin = Permanent(card=_card("Gob", "Creature — Goblin"))
    seat = PlayerState(name="P1", battlefield=[lord, goblin])
    game = Game(players=[seat, PlayerState(name="P2")])

    def _power() -> int:
        game._recalculate_lord_buffs()
        game._refresh_dynamic_creatures()
        return goblin.effective_power

    assert _power() == 2
    seat.battlefield.append(Permanent(card=_card("Mountain", "Basic Land — Mountain")))
    assert _power() == 2
    seat.battlefield.append(Permanent(card=_card("Mountain", "Basic Land — Mountain")))
    assert _power() == 3
    seat.battlefield.pop()
    assert _power() == 2
