"""Regressions: a where-clause asked the battlefield about a permanent the
same effect had just moved.

Found by driving Apocalypse's Aether Mutation and Death Mutation, both
"supported" on arrival: each resolved its first sentence, made **no tokens**,
and logged nothing wrong. Invasion's Artifact Mutation and Aura Mutation —
shipped — did exactly the same.

"Destroy target artifact. It can't be regenerated. Create X 1/1 green Saproling
creature tokens, where X is **that artifact's** mana value." The where-clause
compiles to an ``object_characteristic`` count over the sentence's target, and
the evaluator resolved that target with ``resolve_target_permanent`` — which
finds permanents on the battlefield. By the time the second sentence runs the
artifact is a card in a graveyard, so the count was zero and the whole second
half of the card did not happen.

CR 608.2h: "if it's no longer in that zone, or if the effect has moved it from
a public zone to a hidden zone, the effect uses the object's last known
information." The step that moved the object already wrote that information
down (``its_mana_value`` for a destroy, ``returned_mana_value`` for a bounce);
the lowering now names the record on the clause, and names one only where a
step of the same effect produces it.

No compiled program moved for any card whose target stays where it is (Subdue,
Kry Shield, Blood Lust, Surge of Strength), which is why no coverage instrument
could see this: every one of them reads the *shape* of a program, and the shape
was right.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.keywords import grant_keyword
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: Both manifest roles, first printing wins — the pool ``oracle_diff`` reads.
#: Aether Mutation and Death Mutation are Apocalypse's, measured as this is
#: written; the other two shipped with Invasion.
_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

#: ``(spell, the permanent it is aimed at, that permanent's mana value)``,
#: in a fixed order — a parametrize list must collect the same way in every
#: worker.
_MUTATIONS = [
    ("Aether Mutation", "Craw Wurm", 6),
    ("Artifact Mutation", "Jayemdae Tome", 4),
    ("Aura Mutation", "Crusade", 2),
    ("Death Mutation", "Craw Wurm", 6),
]


def _table(spell: str, victim: str):
    """*spell* in the caster's hand and *victim* across the table."""
    game = Game(players=[
        PlayerState("Caster", library=[_POOL["Forest"]] * 5, hand=[_POOL[spell]]),
        PlayerState("Opponent", library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    permanent = Permanent(card=_POOL[victim])
    game._put_permanent_onto_battlefield(1, permanent, None)
    return game, permanent


def _saprolings(game) -> int:
    return sum(1 for p in game.controlled_by(0) if p.card.name == "Saproling Token")


@pytest.mark.parametrize("spell, victim, mana_value", _MUTATIONS)
def test_a_mutation_counts_the_mana_value_of_the_permanent_it_removed(
    spell, victim, mana_value,
):
    """The driven report, as a test: the target leaves the battlefield and the
    tokens are still counted off it."""
    game, permanent = _table(spell, victim)

    result = game.cast_from_hand(0, spell, target_permanent_ids=[permanent.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert not game.is_on_battlefield(permanent)
    assert _saprolings(game) == mana_value


def test_a_target_that_stayed_is_still_asked_directly():
    """The record is a fallback, not a replacement: an indestructible creature
    is not destroyed (CR 702.12b), is still on the battlefield, and answers for
    itself."""
    game, wurm = _table("Death Mutation", "Craw Wurm")
    grant_keyword(wurm, "indestructible")

    game.cast_from_hand(0, "Death Mutation", target_permanent_ids=[wurm.permanent_id])
    resolve_stack(game)

    assert game.is_on_battlefield(wurm)
    assert _saprolings(game) == 6


def test_a_target_that_was_gone_before_the_effect_began_counts_for_nothing():
    """Last known information is about an object *the effect* moved. A target
    that left in response is an illegal target (CR 608.2b): the spell does not
    resolve, nothing wrote a record, and no token is made."""
    game, tome = _table("Artifact Mutation", "Jayemdae Tome")
    game.queue_from_hand(0, "Artifact Mutation", target_permanent_ids=[tome.permanent_id])
    game.remove_from_battlefield(tome)

    resolve_stack(game)

    assert _saprolings(game) == 0


def _characteristic_specs(name: str) -> list[dict]:
    """Every ``object_characteristic`` spec in *name*'s compiled spell."""
    found: list[dict] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            spec = payload.get("x_from_count")
            if isinstance(spec, dict) and isinstance(spec.get("object_characteristic"), dict):
                found.append(spec["object_characteristic"])
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(compile_card_oracle(_POOL[name]).instructions)
    return found


def test_the_record_is_named_only_where_a_step_writes_it():
    """The producer discipline: a destroy names ``its_mana_value``, a bounce
    names ``returned_mana_value``, and a sentence whose target goes nowhere
    names nothing at all — so those cards' programs are what they were."""
    for name, record in (
        ("Artifact Mutation", "its_mana_value"),
        ("Aura Mutation", "its_mana_value"),
        ("Death Mutation", "its_mana_value"),
        ("Aether Mutation", "returned_mana_value"),
    ):
        specs = _characteristic_specs(name)
        assert [spec.get("last_known") for spec in specs] == [record], name

    for name in ("Subdue", "Kry Shield", "Blood Lust", "Surge of Strength"):
        specs = _characteristic_specs(name)
        assert specs, name
        assert all("last_known" not in spec for spec in specs), name


#: Step kinds that take their target off the battlefield and record one of its
#: characteristics on the way (``lowering/_records._PRODUCES``).
_MOVING_KINDS = frozenset({"destroy_target_permanent", "bounce_target_creature"})


def test_every_spell_that_measures_a_target_it_moved_names_the_record():
    """Pool-wide, both manifest roles: a spell whose steps move their one
    target and then size something by "that <noun>'s" characteristic must carry
    ``last_known``. A floor on how many were examined, because a sweep that
    reaches none passes on a broken engine."""
    examined = []
    for name in sorted(_POOL):
        card = _POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        steps = [
            step for instruction in program.instructions
            for step in (
                instruction.payload.get("steps") or (instruction,)
                if instruction.kind == "sequence" else (instruction,)
            )
        ]
        for position, step in enumerate(steps):
            spec = (step.payload or {}).get("x_from_count")
            described = spec.get("object_characteristic") if isinstance(spec, dict) else None
            if not isinstance(described, dict) or described.get("object") != "target":
                continue
            if "role" in described:
                continue
            if not any(earlier.kind in _MOVING_KINDS for earlier in steps[:position]):
                continue
            examined.append(name)
            assert described.get("last_known"), name

    assert len(examined) >= 4, examined
