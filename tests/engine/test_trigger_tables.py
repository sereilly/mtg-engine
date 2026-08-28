"""Guards against first-match-wins shadowing in the trigger-condition tables.

The tables in engine/oracle.py are matched with an unanchored ``re.match`` in
listed order, so a pattern that is a strict prefix of a later pattern's
canonical text silently swallows it (this happened to
``creature_attacks_or_blocks`` and ``creature_deals_damage_to_opponent``). Each
pattern gets a canonical example text here; every earlier pattern must fail to
match every later pattern's example.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards
from engine.oracle import (
    AT_TRIGGER_PATTERNS,
    WHEN_TRIGGER_PATTERNS,
    WHENEVER_TRIGGER_PATTERNS,
    compile_card_oracle,
)

from tests.helpers import _mk_creature_card
from tests.helpers import LEA_PATH

# Canonical oracle-text (normalized) example for every trigger-condition kind.
# When adding a pattern to a table, add its example here — the shadowing test
# fails otherwise.
#
# A kind may carry **several** examples, as a tuple: one printed wording per
# pattern that names it ("whenever a creature you control dies" and the
# explicit-self spelling Basri's Lieutenant prints). Without that, a second
# spelling would be untested by the shadowing guard — the lookup is by kind,
# so it would only ever see the first.
EXAMPLE_TEXTS: dict[str, str | tuple[str, ...]] = {
    # whenever
    "land_dies": "whenever a land is put into a graveyard from the battlefield",
    # The general reading of the same event, narrowed by a printed noun phrase
    # (Tablet of Epityr). Its own kind rather than a widening of land_dies,
    # which keeps its dedicated dispatcher and Dingus Egg's damage shape.
    "permanent_dies": (
        "whenever an artifact you control is put into a graveyard from the battlefield"
    ),
    # Both printed spellings, because the kind is in both tables: "whenever" for
    # an Equipment (Malefic Scythe) and "when" for an Aura (Creature Bond). One
    # example would leave the other table's pattern unexercised.
    "attached_creature_dies": (
        "whenever equipped creature dies, put a soul counter on this equipment.",
        "when enchanted creature dies, this aura deals damage equal to that "
        "creature's toughness to the creature's controller.",
    ),
    "creature_dies": "whenever a creature dies",
    # CR 120.4b's event, once. Every printed narrowing of it is a named group
    # on one pattern, so each spelling is checked against every earlier pattern
    # of every other kind — which is the whole reason a kind may hold several
    # examples.
    "damage_dealt": (
        "whenever this creature deals damage",
        "whenever this creature deals damage to a player",
        "whenever this creature deals damage to an opponent",
        "whenever this creature deals combat damage to a player",
        "whenever this creature deals combat damage to a player or planeswalker",
        "whenever enchanted creature deals damage to you",
        "whenever a source you control deals noncombat damage to an opponent",
        "whenever a creature you control with deathtouch deals damage to a planeswalker",
    ),
    "creature_you_control_dies": (
        "whenever a creature you control dies",
        "whenever this creature or another creature you control dies",
    ),
    "creature_opponent_controls_dies": "whenever a creature an opponent controls dies",
    "creature_blocks_or_blocked_by": "whenever this creature blocks or becomes blocked by a non-wall creature",
    "attacks_unblocked": "whenever this creature attacks and isn't blocked",
    "creature_attacks": "whenever this creature attacks",
    # A narrowed spelling beside its bare one: the subject filter is what makes
    # the pair two different firings (CR 509.3c/509.3d), so both are checked
    # against every earlier pattern of every other kind.
    "matching_creature_attacks": "whenever a creature you control with deathtouch attacks",
    # Three spellings, one kind: the bare event, the narrowed one whose subject
    # filter makes it fire per blocked attacker, and the one-shot trigger word
    # Elder Land Wurm prints — which is a row in the "when" table and needs an
    # example that table would be asked about.
    "creature_blocks": (
        "whenever this creature blocks",
        "whenever this creature blocks a creature with flying",
        "when this creature blocks, it loses defender.",
    ),
    "creature_becomes_blocked": (
        "whenever this creature becomes blocked",
        "whenever this creature becomes blocked by a creature",
    ),
    "creature_attacks_or_blocks": "whenever this creature attacks or blocks",
    "creature_dealt_damage": "whenever this creature is dealt damage",
    "creature_dealt_damage_by_self_dies": "whenever a creature dealt damage by this creature this turn dies",
    # One kind, four printed subjects: a quantified class (Lifetap), the
    # source itself (City of Brass), the permanent this one is attached to
    # (Spirit Shackle) and that same subject with the one-shot trigger word
    # (Blight), which is the row the "when" table carries.
    "permanent_becomes_tapped": (
        "whenever a forest an opponent controls becomes tapped",
        "whenever this land becomes tapped",
        "whenever enchanted creature becomes tapped",
        "when enchanted land becomes tapped",
    ),
    # One printed ability with two trigger events (Haunting Wind).
    "permanent_tapped_or_ability_activated": (
        "whenever an artifact becomes tapped or a player activates an "
        "artifact's ability without {t} in its activation cost"
    ),
    # The activation event on its own, with no tap event joined to it
    # (Imprison) — a different condition from the compound row above, and the
    # printed "with {t}" is the whole difference.
    "nonmana_ability_activated": (
        "whenever a player activates an ability of enchanted creature with "
        "{t} in its activation cost that isn't a mana ability"
    ),
    "land_tapped_for_mana": "whenever a player taps a land for mana",
    "spell_cast": "whenever a player casts a spell",
    "opponent_casts_spell": "whenever an opponent casts a spell",
    "you_cast_spell": "whenever you cast a spell",
    "opponent_attackers_declared": "whenever an opponent attacks with creatures",
    "opponent_casts_nth_spell_each_turn":
        "whenever an opponent casts their second spell each turn",
    "permanent_becomes_untapped": (
        "whenever this creature becomes untapped",
        "whenever this artifact becomes untapped",
        "whenever this permanent becomes untapped",
    ),
    "counters_reach_threshold":
        "when there are four or more page counters on this artifact",
    # Two rows share this kind — the union narrowing and the single-type one —
    # so both spellings are named, which is what the "one entry may hold
    # several" shape above exists for.
    "you_cast_first_spell_each_turn": (
        "whenever you cast your first instant or sorcery spell each turn",
        "whenever you cast your first creature spell each turn",
    ),
    "enchantment_cast": "whenever you cast an enchantment spell",
    "land_enters": "whenever a land enters the battlefield",
    "matching_permanent_enters": (
        "whenever a creature you control with power 4 or greater enters"
    ),
    "one_or_more_attack": "whenever one or more creatures you control attack",
    # Both printed seats, because one pattern names both and the narrowing is
    # payload: an example per spelling is what the shadowing guard needs to see
    # each of them checked against every earlier pattern.
    "draws_card": (
        "whenever you draw a card",
        "whenever an opponent draws a card",
    ),
    "you_activate_loyalty_ability": (
        "whenever you activate a loyalty ability of a chandra planeswalker"
    ),
    "draws_second_card": "whenever you draw your second card each turn",
    "you_gain_life": "whenever you gain life",
    "you_sacrifice_permanent": "whenever you sacrifice a permanent",
    # Two rows, one kind: the event is the attack declaration and what differs
    # is what the card asks about it.
    "attackers_declared": (
        "whenever you attack with two or more creatures with flying",
        "whenever this creature and at least two other creatures attack",
    ),
    "counters_put_on_creature": (
        "whenever one or more +1/+1 counters are put on another non-hydra "
        "creature you control"
    ),
    # The batched form: one trigger however many creatures dealt the damage,
    # fired once per player damaged — which is the difference from the
    # per-attacker condition, not a wording of it.
    "one_or_more_deal_combat_damage":
        "whenever one or more Cats you control deal combat damage to a player",
    # Both wordings, because the narrowing is data on one condition: the
    # unnarrowed form fires on anyone's spell and the narrowed one only on an
    # opponent's, and a table holding just one of them would let the other drift.
    "self_becomes_target": (
        "whenever this creature becomes the target of a spell or ability",
        "whenever this creature becomes the target of a spell or ability "
        "an opponent controls",
    ),
    # when
    "enters_battlefield": "when this creature enters the battlefield",
    "leaves_battlefield": "when this creature leaves the battlefield",
    # Dance of Many: the same event asked about the token this permanent
    # created. Its own kind because the relation is what the fire site
    # dispatches on — the ability is the enchantment's and the event is the
    # token's.
    "created_token_leaves_battlefield": "when the token leaves the battlefield",
    "dies": "when this creature dies",
    "becomes_target": "when this creature becomes the target of a spell",
    # Legends' two, added at its promotion. Both are announced away from a call
    # site — the first from the record `named_counters.remove_counters` writes
    # (removal has four sites), the second from the discard seam, which is the
    # only place a card's own from-hand trigger (CR 113.6d) is in view.
    "last_counter_removed":
        "when you remove the last intervention counter from this enchantment",
    "discarded_by_opponent_effect":
        "when a spell or ability an opponent controls causes you to discard this card",
    "no_islands": "when you control no islands",
    "no_lands_anywhere": "when there are no lands on the battlefield",
    "self_cast": "when you cast this spell",
    "no_lands": "when you control no lands",
    "controls_matching_permanent": "when you control a dwarf",
    # at
    "upkeep_self": "at the beginning of your upkeep",
    "upkeep_each": "at the beginning of each upkeep",
    "upkeep_enchanted_controller": "at the beginning of the upkeep of enchanted creature's controller",
    "upkeep_chosen": "at the beginning of the chosen player's upkeep",
    "draw_step_self": "at the beginning of your draw step",
    "draw_step_each": "at the beginning of each player's draw step",
    "end_step": "at the beginning of the end step",
    # The scope narrowing, its own kind for the same reason combat_your_turn is:
    # the dispatch reads the difference.
    "end_step_self": "at the beginning of your end step",
    # Both spellings, because both tables carry both: the M21 Shrines print
    # "first" and modern templating prints "precombat".
    "main_phase_first": (
        "at the beginning of your first main phase",
        "at the beginning of your precombat main phase",
    ),
    "combat_your_turn": "at the beginning of combat on your turn",
    "combat": "at the beginning of combat",
    # CR 511.1 — the end of combat step (The Wretched).
    "end_of_combat": (
        "at end of combat, gain control of all creatures blocking this "
        "creature for as long as you control this creature"
    ),
}

_TABLES = [
    ("whenever", WHENEVER_TRIGGER_PATTERNS),
    ("when", WHEN_TRIGGER_PATTERNS),
    ("at", AT_TRIGGER_PATTERNS),
]


def _examples(kind: str) -> tuple[str, ...]:
    """Every canonical text for *kind* — one entry may hold several."""
    found = EXAMPLE_TEXTS.get(kind)
    if found is None:
        return ()
    return (found,) if isinstance(found, str) else tuple(found)


def _examples_in(table_name: str, kind: str) -> tuple[str, ...]:
    """*kind*'s canonical texts that this table would actually be asked about.

    ``_parse_trigger_condition`` routes a line to one table by its printed
    trigger word — "whenever " first, then "when ", then "at " — so an example
    of one word says nothing about a table keyed on another. Checking every
    example against every table conflated the two the moment a kind was printed
    with both words: `permanent_becomes_tapped` is spelled "whenever" on three
    cards and "when" on Blight, and the unfiltered guard demanded that the
    "when" table hold a pattern for Lifetap's wording — a row no card would
    ever reach.
    """
    prefix = f"{table_name} "
    return tuple(
        example for example in _examples(kind)
        if example.startswith(prefix)
        and not (table_name == "when" and example.startswith("whenever "))
    )


def test_every_pattern_has_an_example():
    """Every (table, kind) pair needs an example *that table* would be asked
    about — a kind listed in the "when" table with only "whenever" examples has
    a row nothing here exercises."""
    missing = [
        f"{table_name}:{kind}"
        for table_name, table in _TABLES
        for kind, _ in table
        if not _examples_in(table_name, kind)
    ]
    assert not missing, f"add canonical examples for: {missing}"


def test_every_example_matches_its_own_pattern():
    """Each trigger kind's canonical example must be matched by at least one of
    that kind's patterns.

    A kind can have several patterns — a narrowed form and its general one, as
    with "casts a *blue* spell" ahead of "casts a spell". Requiring every
    pattern to match the one example would make that impossible; requiring at
    least one keeps the guard's real purpose, which is that no kind is
    unreachable.
    """
    for table_name, table in _TABLES:
        patterns_by_kind: dict[str, list] = {}
        for kind, pattern in table:
            patterns_by_kind.setdefault(kind, []).append(pattern)
        for kind, patterns in patterns_by_kind.items():
            for example in _examples_in(table_name, kind):
                assert any(re.match(pattern, example) for pattern in patterns), (
                    f"{kind}: canonical example {example!r} matches none of its patterns"
                )


@pytest.mark.parametrize("table_name,table", _TABLES)
def test_no_pattern_shadows_a_later_one(table_name, table):
    """An earlier pattern must never match a later pattern's canonical text —
    otherwise the later (more specific) pattern is dead code.

    Same-kind pairs are exempt, and only those: shadowing is harmful because
    the swallowed text compiles to a *different* condition than it names, and
    two patterns producing one kind produce one answer. Two spellings of one
    kind still have to earn their place — every example is checked against
    every earlier pattern of every *other* kind.
    """
    for i, (early_kind, early_pattern) in enumerate(table):
        for later_kind, _ in table[i + 1:]:
            if later_kind == early_kind:
                continue
            for example in _examples_in(table_name, later_kind):
                assert not re.match(early_pattern, example), (
                    f"{table_name}: pattern {early_kind!r} shadows {later_kind!r} "
                    f"(matches its example {example!r}); move the specific pattern first"
                )


# --- regression: the two shadows found in the LEA-era table -----------------

def test_attacks_or_blocks_compiles_to_specific_kind():
    card = _mk_creature_card(
        "Shadow Test", 1, 1,
        "Whenever this creature attacks or blocks, it gets +1/+0 until end of turn.",
    )
    program = compile_card_oracle(card)
    kinds = [ta.condition.kind for ta in program.triggered_abilities]
    assert "creature_attacks_or_blocks" in kinds
    assert "creature_attacks" not in kinds


def test_hypnotic_specter_keeps_its_recipient_narrowing():
    """One kind for the whole "deals damage" family, so what used to be checked
    as a *kind* is checked as payload: the card says "to an opponent" and the
    dispatcher must be told so."""
    cards = {c.name: c for c in load_cards(LEA_PATH)}
    program = compile_card_oracle(cards["Hypnotic Specter"])
    conditions = [ta.condition for ta in program.triggered_abilities]
    assert [c.kind for c in conditions] == ["damage_dealt"]
    assert conditions[0].payload == {
        "damager_self": "this creature", "damage_recipient": "an opponent",
    }


# --- a card that names itself is printing the modern condition --------------

@pytest.mark.parametrize("condition", [
    "Whenever a creature dealt damage by {self} this turn dies",
    "Whenever {self} deals damage to an opponent",
    "Whenever {self} attacks",
    "When {self} dies",
])
def test_a_self_named_condition_reads_as_its_modern_spelling(condition):
    """Pre-Sixth-Edition templating writes the source as the card's own name:
    "Whenever a creature dealt damage by **Axelrod Gunnarson** this turn
    dies". That is the same condition modern templating spells "this creature",
    and both front ends have to agree — the lexer collapses the name to one
    SELF token for the grammar, and the pattern tables read a collapsed copy of
    the line.

    Read as two different conditions, one front end refuses the card and the
    stricter of them wins: every Legends creature that names itself in a
    trigger reported "text too complex" for an event this engine announces.
    """
    modern = _mk_creature_card(
        "Old One", 2, 2, f"{condition.format(self='this creature')}, you gain 1 life."
    )
    legacy = _mk_creature_card(
        "Old One", 2, 2, f"{condition.format(self='Old One')}, you gain 1 life."
    )

    modern_program = compile_card_oracle(modern)
    legacy_program = compile_card_oracle(legacy)

    assert modern_program.supported, modern_program.reason
    assert legacy_program.supported, legacy_program.reason
    assert (
        [ta.condition.kind for ta in legacy_program.triggered_abilities]
        == [ta.condition.kind for ta in modern_program.triggered_abilities]
    )
