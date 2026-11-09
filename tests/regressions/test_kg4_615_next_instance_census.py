"""Every source-keyed "the next time … would deal damage" record spends itself
on **one instance** — everything its source deals in one simultaneous dealing.

Until kg4 this was the census of an open question (kg3's
``test_kg3_events_next_instance_open.py``): CR 615.8 says such an effect
prevents "the next instance of damage from that source, regardless of how much
damage that is" and never defines an instance, and no ruling on any
source-keyed card says whether a sweep's several chunks are one. The project
owner settled it (2026-11-07): "CR 615.8 should prevent all damage from damage
instances that affect multiple targets or all creatures." So the instance is
the dealing (``damage_redirects.dealing_moment``): a one-use record spent on a
chunk of a simultaneous dealing opens a ``shields.SharedNextTime``
(``by_source``) there, open for that source's other chunks, and the dealing's
finish closes it (``simultaneous_damage.finish``).

The census is by shape, from the compiled programs: every source-keyed "next
time" line in both manifest roles, and the record its instruction arms —

* a **shield** (``shields.Shield``: ``Shield.spend`` opens the occasion),
* a **redirect** (``damage_redirects.DamageRedirect``: ``DamageRedirect.spend``),
* a **rider** on the source (``engine/next_damage.py``: the dealing's
  ``next_time_riders``),

all three reached by the occasion, or one of two **single-recipient legacy
records** (Jade Monolith's metadata pair, Eye for an Eye's mirror charges),
which are outside it and left (see ``_LEGACY``). A card whose line arms a record
of no known family fails here until it is classified.

And every card a sweep can meet — the source-keyed line whose recipient is not
one object — is named against the board in
``tests/rules/test_kg4_615_next_instance.py`` that drives it.

Validated backwards: on the base (``1198d15e``) every board this census names
fails (``test_kg4_615_next_instance.py``'s docstring), and dropping a kind from
``_FAMILY`` fails the first test here.
"""

from __future__ import annotations

import dataclasses
import re

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction

#: "The next time <a source> would deal [combat] damage <rest>", read off the
#: printed line with reminder text removed. The recipient-keyed template
#: ("the next time damage would be dealt to …") never matches: it has no
#: source before "would deal".
_SOURCE_KEYED = re.compile(
    r"\bthe next time (?!damage\b)(?P<source>[^.,]*?) would deal (?:combat )?damage"
    r"(?P<rest>[^.]*)",
    re.IGNORECASE,
)
#: A recipient that is one object or one player: no sweep can hand it two
#: chunks from one source.
_ONE_RECIPIENT = re.compile(
    r"^ to (?:you|target (?:creature|player)|this creature|that creature)\b(?! and/or)",
    re.IGNORECASE,
)

#: The record each arming instruction kind puts on the table.
_FAMILY = {
    "grant_prevention_shield": "shield",
    "grant_whole_prevention_shield": "shield",
    "grant_half_prevention_shield": "shield",
    "grant_forcefield_shield": "shield",
    "redirect_damage_from_chosen_source_until_eot": "redirect",
    "redirect_damage_from_target_until_eot": "redirect",
    "redirect_source_damage_to_target_until_eot": "redirect",
    "redirect_source_damage_to_you_until_eot": "redirect",
    "redirect_source_class_damage_until_eot": "redirect",
    "redirect_chosen_source_damage_off_target_until_eot": "redirect",
    "double_next_damage_from_chosen_source": "rider",
    "prevent_next_damage_from_chosen_source": "rider",
    "jade_monolith_redirect": "legacy",
    "arm_mirror_damage": "legacy",
}
#: The families whose one-use record shares its instance across a dealing.
_SHARED = {"shield", "redirect", "rider"}
#: The two records outside the occasion, and why each is left: a field named
#: for the card that writes it (``damage_redirects``' docstring), with **one**
#: printed recipient, so it meets a second chunk of one instance only when one
#: dealing hits that recipient twice — a split sentence naming it for both
#: halves. Left for the round that moves them onto ``DamageRedirect``.
_LEGACY = {
    "Jade Monolith": "metadata pair on the one target creature",
    "Eye for an Eye": "PlayerState.mirror_damage_* on the one player",
}

_RULES = "tests/rules/test_kg4_615_next_instance.py"
#: Each card a sweep can meet, and the board that drives it.
_DRIVEN = {
    "Pilgrim of Justice": "test_pilgrim_of_justice_stops_a_red_sweep_whole_then_the_next_is_dealt",
    "Pilgrim of Virtue": "test_penance_and_pilgrim_of_virtue_stop_a_black_sweep_whole",
    "Penance": "test_penance_and_pilgrim_of_virtue_stop_a_black_sweep_whole",
    "Shadowbane": "test_shadowbane_stops_a_black_sweep_at_you_and_your_creatures_and_gains_the_total_once",
    "Reflect Damage": "test_reflect_damage_sends_a_whole_sweep_to_its_sources_controller",
    "Desperate Gambit": "test_desperate_gambit_doubles_or_prevents_every_chunk_of_a_sweep",
    "Impulsive Maneuvers": "test_impulsive_maneuvers_on_an_attacker_blocked_by_two",
    "Goblin Psychopath": "test_goblin_psychopath_lost_flip_sends_both_blockers_damage_to_you",
    # "…to any target", "…to enchanted creature": one announced recipient,
    # which one dealing reaches twice only through a split sentence at it.
    "Circle of Despair": "test_a_one_recipient_shield_takes_both_chunks_of_a_split_sentence_at_it",
    "Honorable Passage": "test_a_one_recipient_shield_takes_both_chunks_of_a_split_sentence_at_it",
    "Martyr's Cause": "test_a_one_recipient_shield_takes_both_chunks_of_a_split_sentence_at_it",
    "Sanctum Guardian": "test_a_one_recipient_shield_takes_both_chunks_of_a_split_sentence_at_it",
    "Kithkin Armor": "test_a_one_recipient_shield_takes_both_chunks_of_a_split_sentence_at_it",
    # "…to an opponent": the opponent it attacks, one combat chunk a step; the
    # redirect family's occasion is Reflect Damage's.
    "Soltari Guerrillas": "test_reflect_damage_sends_a_whole_sweep_to_its_sources_controller",
    # Mirrodin, W1G12. "The next time target creature would deal damage this
    # turn, prevent that damage. You gain life …": an announced source and no
    # recipient, so a double block hands it two chunks of one dealing. A
    # board in another module is named "<path>::<board>".
    "Awe Strike": "tests/rules/test_mrd_w1g12_awe_strike.py::"
                  "test_awe_strike_prevents_a_double_blocked_attackers_whole_dealing",
}

#: Source-keyed "next time" cards in both roles when this was written (53).
_POPULATION_FLOOR = 50


def _instructions(value):
    """Every instruction reachable from *value*: a program, an ability, a
    step's payload, a branch."""
    if isinstance(value, OracleInstruction):
        yield value
        yield from _instructions(dict(value.payload or {}))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _instructions(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _instructions(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from _instructions(getattr(value, item.name))


#: A granted ability's quoted text.
_GRANTED = re.compile(r'has "([^"]*\bthe next time\b[^"]*)"', re.IGNORECASE)


def _families(program) -> set:
    return {
        _FAMILY[instruction.kind]
        for instruction in _instructions(program)
        if instruction.kind in _FAMILY
    }


def _population():
    """{card name: (printed line, the families its program arms, reaches
    several recipients)} for every source-keyed "next time" line."""
    found: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if card.name in found:
            continue
        for line in (card.oracle_text or "").split("\n"):
            printed = re.sub(r"\([^)]*\)", "", line)
            matches = list(_SOURCE_KEYED.finditer(printed))
            if not matches:
                continue
            families = _families(compile_card_oracle(card))
            granted = _GRANTED.search(printed)
            if not families and granted:
                # "Enchanted creature has \"{T}: The next time …\"" (Samite
                # Blessing): the ability is the creature's while the Aura is
                # attached (``Permanent.effective_card``), compiled from the
                # quoted text as the creature's own line.
                families = _families(compile_card_oracle(dataclasses.replace(
                    card, name=f"{card.name} (granted)",
                    type_line="Creature — Test", oracle_text=granted.group(1),
                )))
            several = any(not _ONE_RECIPIENT.match(m.group("rest")) for m in matches)
            found[card.name] = (printed.strip(), families, several)
            break
    return found


def test_every_source_keyed_next_time_arms_a_record_the_dealing_reaches():
    """By shape: each line's compiled program arms a shield, a redirect or a
    rider — the three records whose one-use form shares its instance across
    a dealing — or one of the two named single-recipient legacy records."""
    population = _population()
    assert len(population) >= _POPULATION_FLOOR, len(population)
    unknown = sorted(name for name, (_, families, _) in population.items() if not families)
    assert unknown == [], (
        "a source-keyed 'next time' line arms a record this census does not "
        f"know (classify its instruction kind in _FAMILY): {unknown}"
    )
    outside = {
        name: line for name, (line, families, _) in population.items()
        if not families & _SHARED
    }
    assert set(outside) == set(_LEGACY), outside
    for name in _LEGACY:
        line, _families, several = population[name]
        assert not several, (
            f"{name}'s legacy record now reaches several recipients: {line}"
        )


def test_the_cards_a_sweep_can_meet_are_each_driven():
    """Every source-keyed line whose recipient is not one object is named
    against the board that drives it, and that board exists."""
    import importlib

    population = _population()
    meets = {name for name, (_, _, several) in population.items() if several}
    assert len(meets) >= len(_DRIVEN) - 2, meets
    assert sorted(meets - set(_DRIVEN)) == [], (
        "a source-keyed 'next time' a sweep can meet is driven by no board: "
        f"{sorted(meets - set(_DRIVEN))}"
    )
    assert sorted(set(_DRIVEN) - meets) == [], (
        f"no longer in the pool, or no longer reaching several recipients: "
        f"{sorted(set(_DRIVEN) - meets)}"
    )
    def found(board: str) -> bool:
        path, _, name = board.rpartition("::")
        module = importlib.import_module(
            (path or _RULES).removesuffix(".py").replace("/", ".")
        )
        return hasattr(module, name)

    missing = sorted({board for board in _DRIVEN.values() if not found(board)})
    assert missing == [], missing
