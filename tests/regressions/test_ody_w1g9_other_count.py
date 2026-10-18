"""Regression: "…for each **other** <noun>" does not count the permanent the
count is taken for.

``_refresh_dynamic_creatures`` handed ``evaluate_count`` the source and
nothing to leave out, and ``_battlefield_matches`` reads "other" as "skip
*exclude*" - so the word was popped off the filter and dropped. Every static
P/T bonus sized by such a count was one unit too large (or too small):

* Mogg Squad (TMP) "gets -1/-1 for each other creature on the battlefield"
  was 2/2 alone where it prints 3/3;
* Radiant, Archangel (ULG) and Squirrel Mob (ODY) counted themselves;
* Bravado (USG) counted the creature it enchants;
* Ancestral Mask (MMQ) "+2/+2 for each other enchantment" counted itself, so
  it gave +2/+2 with no other enchantment on the battlefield.

Five of the six lines in both manifest roles. The sixth, Vampirism, was right
by two errors cancelling - its host was counted and then took the Aura's own
"Other creatures you control get -1/-1" - and is right for one reason now:
on an Aura "other" is measured from the creature it enchants (and from the
Aura itself, for a noun the Aura is one of).

W1G1 measured the first three and left them; this is that census widened to
every such line, read off the compiled programs so the next card printed
this way joins it unnamed.

One reading is taken on purpose and has no ruling behind it (Scryfall has
none for Ancestral Mask, and the Comprehensive Rules do not define "other"):
both the Aura and its host are left out. They coincide with the printed
reading for every card here; they would part company only for an Ancestral
Mask on an *enchantment creature*, which this does not count.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card


@pytest.fixture(scope="module")
def pool():
    names: dict = {}
    for card in compilation_units(
        load_cards(manifest_set_paths(include_measured=True))
    ):
        names.setdefault(card.name, card)
    return names


def _other_counts(program):
    """``(instruction, count spec)`` for each static P/T line sized by a count
    of "other" permanents: a layer-7c bonus or a characteristic-defining one."""
    for instruction in program.instructions:
        key = {
            "dynamic_pt_bonus": "x_from_count", "dynamic_pt_count": "count_spec",
        }.get(instruction.kind)
        spec = instruction.payload.get(key) or {} if key else {}
        if (spec.get("filter") or {}).get("exclude_self"):
            yield instruction, spec


def _one_of(filt: dict):
    """A card the count's noun phrase describes."""
    keywords = "\n".join(str(k).capitalize() for k in filt.get("with_keywords") or ())
    if filt.get("type_filter") == "creature":
        subtype = str(filt.get("subtype_filter") or "bear").title()
        return _mk_card("Counted", f"Creature - {subtype}", keywords)
    assert filt.get("type_filter") == "enchantment", filt
    return _mk_card("Counted", "Enchantment")


def _rate(amount) -> int:
    if not isinstance(amount, dict):
        return 0
    return int(amount.get("times_x", 0)) * (-1 if amount.get("negative") else 1)


def _measured(card, instruction, spec, others: int) -> tuple:
    """``(what the engine computes, what the card prints)`` with *others*
    more permanents of the counted kind beside it."""
    game = Game(players=[PlayerState("A"), PlayerState("B")])
    permanent = Permanent(card=card)
    if instruction.payload.get("subject") == "attached":
        subject = Permanent(card=_mk_card("Host", "Creature - Host"))
        game._put_permanent_onto_battlefield(0, subject, None)
        game._put_permanent_onto_battlefield(0, permanent, None)
        attach_aura(permanent, subject)
        printed = (2, 2)
    else:
        game._put_permanent_onto_battlefield(0, permanent, None)
        subject = permanent
        printed = (int(card.raw["power"]), int(card.raw["toughness"]))
    for _ in range(others):
        game._put_permanent_onto_battlefield(
            0, Permanent(card=_one_of(spec["filter"])), None
        )
    game._recompute_continuous_effects()
    if instruction.kind == "dynamic_pt_count":
        expected = (others, others)
    else:
        expected = (
            printed[0] + _rate(instruction.payload.get("power")) * others,
            printed[1] + _rate(instruction.payload.get("toughness")) * others,
        )
    return (subject.effective_power, subject.effective_toughness), expected


def test_a_count_of_other_permanents_leaves_out_its_own(pool):
    examined, wrong = 0, []
    for card in pool.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for instruction, spec in _other_counts(program):
            examined += 1
            for others in (0, 2):
                now, printed = _measured(card, instruction, spec, others)
                if now != printed:
                    wrong.append(
                        f"{card.name} with {others} others is {now}, prints {printed}"
                    )
    # Six lines on the day this was written (Vampirism, Mogg Squad, Bravado,
    # Radiant, Ancestral Mask, Squirrel Mob). A walk that found none would
    # pass on any engine.
    assert examined >= 6, examined
    assert wrong == []


def test_an_auras_other_creatures_are_other_than_the_one_it_enchants(pool):
    """The two halves of Vampirism apart, as invented cards - together they
    cancelled, which is how each stayed wrong unseen."""
    def table(text):
        aura = _mk_card("Probe Aura", "Enchantment - Aura", "Enchant creature\n" + text)
        assert compile_card_oracle(aura).supported, text
        game = Game(players=[PlayerState("A"), PlayerState("B")])
        bears = [Permanent(card=pool["Grizzly Bears"]) for _ in range(3)]
        for bear in bears:
            game._put_permanent_onto_battlefield(0, bear, None)
        permanent = Permanent(card=aura)
        game._put_permanent_onto_battlefield(0, permanent, None)
        attach_aura(permanent, bears[0])
        game._recompute_continuous_effects()
        return [(b.effective_power, b.effective_toughness) for b in bears]

    assert table("Other creatures you control get -1/-1.") == [(2, 2), (1, 1), (1, 1)]
    assert table(
        "Enchanted creature gets +1/+1 for each other creature you control."
    ) == [(4, 4), (2, 2), (2, 2)]

