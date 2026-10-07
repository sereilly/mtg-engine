"""CR 608.2b for an Aura spell whose target was a card in a graveyard.

CR 115.1b: "Aura spells are always targeted. An Aura's target is specified by
its enchant keyword ability." For "enchant creature card in a graveyard"
(Animate Dead, Dance of the Dead) that target is a card in a graveyard, chosen
as the spell is cast. CR 608.2b: "A target that's no longer in the zone it was
in when it was targeted is illegal", and a spell whose every target is illegal
"doesn't resolve".

Nothing asked. The resolution has three gates in a row and this object fell
between them: ``illegal_targets_refusal`` answers for instants and sorceries
only, and ``vanished_graveyard_target_refusal`` answered for abilities only.
So the Aura resolved, its attach read the vanished card as "no card was named"
and went looking — and returned the first creature card in its caster's own
graveyard, a card nobody named.

Driven for every Aura in the pool whose cast picker is a graveyard card (found
by its spec), three ways each: undisturbed, with the named card exiled in
response, and with a *different* card leaving from under it so that the slot
renumbers. Validated backwards on the tree before the change: the middle one
returned another card for both Auras.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.targeting import GRAVEYARD_TARGET_KIND, derive_cast_spec
from tests.helpers import resolve_stack

#: Seat B's graveyard: the named card is the Grizzly Bears, third from the
#: bottom, with a creature card on either side of it for a scan to find.
_THEIRS = ("Lightning Bolt", "Hill Giant", "Grizzly Bears", "Serra Angel")
_NAMED = 2
#: …and the caster's own, which is where the scan looked first.
_MINE = ("Craw Wurm",)

#: A floor, because a sweep that reaches nothing passes. Two on the day.
_MIN_AURAS = 2


@pytest.fixture(scope="module")
def _auras(catalog) -> list:
    """Every supported Aura whose cast names a card in a graveyard."""
    found = []
    for card in sorted(compilation_units(catalog), key=lambda entry: entry.name):
        if "Aura" not in (card.type_line or ""):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        spec = derive_cast_spec(card, program) or {}
        if spec.get("kind") == GRAVEYARD_TARGET_KIND:
            found.append(card)
    return found


def _cast(catalog_by_name, aura) -> Game:
    def named(names):
        return [catalog_by_name[name] for name in names]

    game = Game(players=[
        PlayerState("A", library=named(["Forest"]) * 12, hand=[aura], graveyard=named(_MINE)),
        PlayerState("B", library=named(["Forest"]) * 12, graveyard=named(_THEIRS)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    assert game.queue_from_hand(
        0, aura.name, target_player_index=1, target_permanent_index=_NAMED,
    ).supported, aura.name
    return game


def _creatures(game, seat) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


def _yard(game, seat) -> list[str]:
    return [card.name for card in game.players[seat].graveyard]


@pytest.mark.cr("608.2b", "115.1b")
def test_an_aura_spell_whose_graveyard_target_left_does_not_resolve(
    _auras, catalog_by_name,
):
    assert len(_auras) >= _MIN_AURAS, [card.name for card in _auras]
    findings: list[str] = []
    for aura in _auras:
        game = _cast(catalog_by_name, aura)
        exiled = game.players[1].graveyard.pop(_NAMED)
        assert exiled.name == "Grizzly Bears"
        resolve_stack(game)

        if _creatures(game, 0) or _creatures(game, 1):
            findings.append(f"{aura.name}: put {_creatures(game, 0) + _creatures(game, 1)} "
                            "onto the battlefield with its target gone")
        if _yard(game, 0) != [*_MINE, aura.name]:
            findings.append(f"{aura.name}: its caster's graveyard is {_yard(game, 0)}")
        if _yard(game, 1) != ["Lightning Bolt", "Hill Giant", "Serra Angel"]:
            findings.append(f"{aura.name}: the other graveyard is {_yard(game, 1)}")
        if any(p.card is aura for p in game.all_permanents()):
            findings.append(f"{aura.name}: is on the battlefield")
        if not any("no longer in the graveyard (608.2b)" in line for line in game.log):
            findings.append(f"{aura.name}: the log does not say why")
    assert not findings, findings


@pytest.mark.cr("608.2b")
def test_an_aura_spell_still_finds_its_card_when_the_pile_shifts(_auras, catalog_by_name):
    """The control arm, and the half that was already right: a *different*
    card leaving from under the named one renumbers its slot and changes
    nothing about which card was named."""
    assert len(_auras) >= _MIN_AURAS
    for aura in _auras:
        game = _cast(catalog_by_name, aura)
        left = game.players[1].graveyard.pop(0)
        assert left.name == "Lightning Bolt"
        resolve_stack(game)

        assert _creatures(game, 0) == ["Grizzly Bears"], aura.name
        assert _yard(game, 1) == ["Hill Giant", "Serra Angel"], aura.name
        assert _yard(game, 0) == list(_MINE), aura.name


@pytest.mark.cr("115.1b")
def test_an_aura_spell_returns_the_card_it_named(_auras, catalog_by_name):
    """Undisturbed: the named Grizzly Bears, under the caster's control, with
    the Aura on the battlefield beside it."""
    assert len(_auras) >= _MIN_AURAS
    for aura in _auras:
        game = _cast(catalog_by_name, aura)
        resolve_stack(game)

        assert _creatures(game, 0) == ["Grizzly Bears"], aura.name
        assert any(p.card is aura for p in game.controlled_by(0)), aura.name
        assert _yard(game, 1) == ["Lightning Bolt", "Hill Giant", "Serra Angel"], aura.name
