"""Regressions: two printed targets were a ceiling, not a count.

Found by driving Apocalypse's Consume Strength — "Target creature gets +2/+2
until end of turn. **Another** target creature gets -2/-2 until end of turn."
— which arrived "supported" and was castable naming **one** creature: a
three-mana +2/+2 with its second sentence optional. Steal Strength (the same
sentence, shipped), Rookie Mistake and Deadshot did the same.

Two printed instances of the word "target" are two targets (CR 601.2c): "The
player announces their choice of an appropriate object or player for **each**
target the spell requires." ``legality.exact_target_count`` counted an
announcement only against a description whose quantifier is ``exactly`` ("two
target creatures"), and a *slot list* — one filter per printed instance —
carries ``target``. So its count was only ever a maximum.

The picker had the same gap from the other side: ``exact_targets`` was absent
from the spec, so a browser's confirm button accepted one target too. Both now
ask ``targeting.slot_list_is_exact``. A list with a slot the card lets the
caster leave empty (Primal Might's "up to one target creature you don't
control") answers False to both and may still name fewer.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.target_descriptions import slot_list_is_exact
from tests.helpers import resolve_stack

#: Both manifest roles, first printing wins. Consume Strength is Apocalypse's,
#: measured as this is written; the rest are shipped.
_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

#: In a fixed order — a parametrize list must collect the same way in every
#: worker.
_TWO_SLOT_SPELLS = ["Consume Strength", "Deadshot", "Rookie Mistake", "Steal Strength"]


def _table(spell: str):
    """*spell* in the caster's hand, and a creature on each side of the table."""
    game = Game(players=[
        PlayerState("Caster", library=[_POOL["Forest"]] * 5, hand=[_POOL[spell]]),
        PlayerState("Opponent", library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    mine = Permanent(card=_POOL["Hill Giant"])
    game._put_permanent_onto_battlefield(0, mine, None)
    theirs = Permanent(card=_POOL["Craw Wurm"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    return game, mine, theirs


@pytest.mark.parametrize("spell", _TWO_SLOT_SPELLS)
def test_a_two_slot_spell_cannot_be_cast_naming_one_target(spell):
    """The driven report, as a test: one named target is refused with the card
    still in hand, and the same announcement with both is accepted."""
    game, mine, theirs = _table(spell)

    short = game.cast_from_hand(0, spell, target_permanent_ids=[mine.permanent_id])

    assert not short.supported
    assert short.details == f"{spell} needs 2 targets, not 1"
    assert [card.name for card in game.players[0].hand] == [spell]
    assert not game.stack

    full = game.cast_from_hand(
        0, spell, target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    resolve_stack(game)
    assert full.supported, full.details
    assert not game.players[0].hand


@pytest.mark.parametrize("spell", _TWO_SLOT_SPELLS)
def test_the_picker_asks_for_both_slots_too(spell):
    """The gate and the picker are one answer: the spec the browser's confirm
    reads says the count is exact, and with a single creature on the whole
    table the spell is not castable at all."""
    game, mine, theirs = _table(spell)

    spec = game.cast_target_spec(0, _POOL[spell])
    assert spec.get("exact_targets") is True and spec.get("max_targets") == 2
    assert game.no_legal_cast_target_refusal(0, _POOL[spell]) is None

    game.remove_from_battlefield(theirs)
    assert game.no_legal_cast_target_refusal(0, _POOL[spell]) is not None


def test_an_optional_slot_may_still_be_left_empty():
    """Primal Might: "Target creature you control gets +X/+X until end of
    turn. Then it fights **up to one** target creature you don't control."
    CR 601.2c lets the second slot go unnamed, so one target is a whole
    announcement and the spec does not claim an exact count."""
    game, mine, _theirs = _table("Primal Might")

    spec = game.cast_target_spec(0, _POOL["Primal Might"])
    assert not spec.get("exact_targets")

    result = game.cast_from_hand(
        0, "Primal Might", x_value=1, target_permanent_ids=[mine.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert (mine.effective_power, mine.effective_toughness) == (4, 4)


def _slot_lists(card) -> list[dict]:
    """Every multi-slot ``targets`` description in *card*'s compiled spell."""
    found: list[dict] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            described = payload.get("targets")
            if isinstance(described, dict) and isinstance(described.get("filters"), list):
                found.append(described)
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(compile_card_oracle(card).instructions)
    return found


def test_every_exact_slot_list_in_the_pool_is_counted_by_the_cast_gate():
    """Pool-wide, both manifest roles. Wherever the picker's predicate says a
    spell's slot list is exact, a cast naming only its first slot is refused —
    by the count gate, or by the roles walk for a list whose slots differ.
    Floored, because a sweep that examines nothing proves nothing."""
    examined = []
    for name in sorted(_POOL):
        card = _POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        if not any(slot_list_is_exact(described) for described in _slot_lists(card)):
            continue
        game, mine, _theirs = _table(name)
        examined.append(name)
        result = game.cast_from_hand(
            0, name, x_value=1, target_permanent_ids=[mine.permanent_id],
        )
        assert not result.supported, name
        assert [held.name for held in game.players[0].hand] == [name], name

    assert set(_TWO_SLOT_SPELLS) <= set(examined)
    assert len(examined) >= 6, examined
