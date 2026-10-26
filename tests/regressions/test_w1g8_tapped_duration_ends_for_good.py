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

The second census is the same duration on a **control change**, and the half
of CR 611.2b about an effect that never starts: an ability whose source
untapped before it resolved — "even if it becomes tapped again right away"
(Old Man of the Sea, 2009-10-01) — steals nothing. Validated backwards the
same way, against the two steal handlers with the untap seam's mark unread:
all eight cards fail there.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
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
    for card in compilation_units(sorted(pool.values(), key=lambda c: c.name)):
        name = card.name
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


# --- The control family reads the same duration. -----------------------------
#
# "Gain control of target creature … for as long as this creature remains
# tapped" (Old Man of the Sea, Willow Satyr, Rubinia Soulsinger, Seasinger,
# Hivis of the Scale, Helm of Possession, Callous Oppressor). Old Man of the
# Sea's ruling (2009-10-01): "If Old Man of the Sea stops being tapped before
# its ability resolves — even if it becomes tapped again right away — you
# won't gain control of the targeted creature at all." The steal checked only
# whether the source was tapped *at resolution* (Old Man of the Sea's own
# handler checked nothing), so an untap and a re-tap in response stole anyway.
# The untap seam's mark (``source_tapped_effects.SOURCE_UNTAPPED``) is now read
# by both steal handlers.

_STEAL_KINDS = frozenset({
    "steal_target_linked_to_source", "steal_creature_while_tapped_and_weaker",
})


def _steals_while_tapped(ability) -> bool:
    for step in _flat(ability.instruction):
        if step.kind == "steal_creature_while_tapped_and_weaker":
            return True
        if step.kind == "steal_target_linked_to_source" and "source_remains_tapped" in (
            step.payload.get("link_conditions") or ()
        ):
            return True
    return False


def _flat(instruction):
    found = [instruction]
    for step in instruction.payload.get("steps") or ():
        found.extend(_flat(step))
    return found


def _steal_census(pool) -> list[tuple[str, int]]:
    found = []
    for card in compilation_units(sorted(pool.values(), key=lambda c: c.name)):
        name = card.name
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.cost.requires_tap and _steals_while_tapped(ability):
                found.append((name, index))
    return found


_STEALS = _steal_census(_POOL)

_STEAL_BAIT = ("Wirewood Elf", "Kamahl, Fist of Krosa", "Shivan Dragon", "Island")


def test_the_steal_census_reaches_the_family():
    names = {name for name, _ in _STEALS}
    assert len(names) >= 5, names
    assert "Old Man of the Sea" in names


@pytest.mark.parametrize("name,index", _STEALS, ids=[name for name, _ in _STEALS])
def test_a_steal_whose_source_untapped_in_response_never_starts(name, index):
    source = _nosick(Permanent(card=_POOL[name]))
    # The activator's own creature pays Helm of Possession's sacrifice, and its
    # Island keeps Seasinger ("When you control no Islands, sacrifice this
    # creature").
    mine = [_nosick(Permanent(card=_POOL[card])) for card in ("Glory Seeker", "Island")]
    # Something for every printed narrowing in the family to name: a small
    # creature (Old Man of the Sea's power bound), a legendary one (Willow
    # Satyr), a Dragon (Hivis), and an Island beside them (Seasinger's
    # "whose controller controls an Island").
    victims = [_nosick(Permanent(card=_POOL[card])) for card in _STEAL_BAIT]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source, *mine]),
        PlayerState(name="P2", battlefield=list(victims)),
    ])
    game.enforce_mana_costs = False
    # What the source chooses as it enters (Callous Oppressor's creature
    # type), on its defaults.
    game._initialize_permanent_state(source, 0, None)
    _nosick(source)
    game._settle()
    ability = usable_activated_abilities(compile_card_oracle(source.card))[index]
    kwargs = {"ability_index": index}
    if derive_activation_spec(ability) is not None:
        # The picker the web layer and the AI ask, which holds the printed
        # narrowing ("that isn't of the chosen type").
        offered = [
            game.players[found["seat"]].battlefield[found["index"]]
            for found in game.activation_target_spec(
                0, 0, ability_index=index,
            ).get("valid_targets") or ()
            if found["kind"] == "permanent" and found["seat"] == 1
        ]
        assert offered, f"no bait creature answers {name}'s noun phrase"
        target = min(offered, key=lambda perm: perm.effective_power)
        kwargs.update(target_player_index=1, target_permanent_ids=[target.permanent_id])
    # (Preacher's creature is the opponent's pick at resolution, so it names
    # no target here.)
    result = game.queue_permanent_ability(0, name, **kwargs)
    assert result.supported, result.details
    assert source.tapped and game.stack
    assert game.become_untapped(source)
    game.become_tapped(source)
    resolve_stack(game)
    game._recompute_continuous_effects()
    stolen = [perm.card.name for perm in victims if game.controller_index_of(perm) != 1]
    assert not stolen, f"{name} stole {stolen} although it untapped in response"
