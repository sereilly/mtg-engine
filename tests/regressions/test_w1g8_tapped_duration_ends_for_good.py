"""A "for as long as this <permanent> remains tapped" effect ends for good
when its source untaps (CR 611.2b).

"…it doesn't start and immediately stop again, and it doesn't last forever."
Before Onslaught's W1G8 round the effect was a record on the source that the
recompute contributed *while the source was tapped* — and nothing ever removed
it. So the effect came back to life the next time the source tapped for any
reason: Ashnod's Battle Gear tapped by an Icy Manipulator gave its old target
+2/-2 again, and a Courier that attacked handed its old target the bonus back.
The record is now ended at the one place a permanent becomes untapped
(``Game.become_untapped`` → ``source_tapped_effects.end_effects_while_tapped``).

The census is derived, not listed: every card in both manifest roles whose
compiled activated ability carries one of the while-tapped kinds is put on a
board, activated at the creature its own picker offers, untapped, tapped again
— and must have given nothing back. Validated backwards against a tree with the
untap seam's call removed: every card below fails there.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

#: The kinds whose effect lasts while the source stays tapped.
_WHILE_TAPPED_KINDS = frozenset({
    "pump_target_while_source_tapped",
    "buff_creatures_global_while_source_tapped",
    "grant_target_keyword_while_source_tapped",
})

#: Bait for every picker: a creature of each type a printed "target <type>
#: creature" in this family names, read off the pool by name only as board
#: furniture (never as dispatch). Big toughness first, so a -2 toughness
#: (Ashnod's Battle Gear) does not kill the creature it is measured on.
_BAIT = (
    "Craw Wurm", "Glory Seeker", "Aphetto Grifter", "Gangrenous Goliath",
    "Skirk Prospector", "Wirewood Elf",
)


def _kinds(instruction) -> set[str]:
    found = {instruction.kind}
    for step in instruction.payload.get("steps") or ():
        found |= _kinds(step)
    return found


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


def _census(pool) -> list[tuple[str, int]]:
    found = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if _kinds(ability.instruction) & _WHILE_TAPPED_KINDS:
                found.append((name, index))
    return found


_POOL = _pool()
_CARDS = _census(_POOL)


def test_the_census_reaches_the_family():
    """A floor on what was examined: the five Couriers and the Antiquities /
    Urza's block artifacts at least."""
    names = {name for name, _ in _CARDS}
    assert len(names) >= 10, names
    assert {"Pearlspear Courier", "Ashnod's Battle Gear", "Thran Weaponry"} <= names


def _state(game, perm) -> tuple:
    game._recompute_continuous_effects()
    granted = tuple(
        word for word in ("vigilance", "shroud", "fear", "haste", "trample")
        if game._has_keyword(perm, word)
    )
    return perm.effective_power, perm.effective_toughness, granted


@pytest.mark.parametrize("name,index", _CARDS, ids=[name for name, _ in _CARDS])
def test_the_effect_does_not_come_back_when_the_source_taps_again(name, index):
    source = _nosick(Permanent(card=_POOL[name]))
    bait = [_nosick(Permanent(card=_POOL[card])) for card in _BAIT]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source, *bait]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()
    ability = usable_activated_abilities(compile_card_oracle(source.card))[index]
    spec = derive_activation_spec(ability)
    target = None
    if spec is not None:
        offered = [
            game.players[found["seat"]].battlefield[found["index"]]
            for found in game._enumerate_targets(0, source.card, spec, for_cast=False)
            if found["kind"] == "permanent"
        ]
        target = next(perm for perm in offered if perm is not source)
    measured = target if target is not None else bait[0]
    before = _state(game, measured)

    kwargs = {"ability_index": index}
    if target is not None:
        kwargs.update(
            target_player_index=game.controller_index_of(target),
            target_permanent_ids=[target.permanent_id],
        )
    result = game.activate_permanent_ability(0, name, **kwargs)
    assert result.supported, result.details
    resolve_stack(game)
    assert source.tapped
    during = _state(game, measured)
    assert during != before, f"{name} did nothing to {measured.card.name}"

    assert game.become_untapped(source)
    assert _state(game, measured) == before, "ended the moment the source untapped"
    game.become_tapped(source)
    assert _state(game, measured) == before, (
        f"{name}'s effect came back when its source tapped again"
    )
