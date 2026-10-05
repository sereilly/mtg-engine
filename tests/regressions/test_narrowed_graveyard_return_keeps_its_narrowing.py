"""Regression: "return target **Zombie** card from your graveyard" returned a
Grizzly Bears.

``return_creature_from_graveyard_to_hand`` honours an announced graveyard slot
when the card in it is eligible. When no slot was announced — a bare
activation, an AI seat, an entry trigger nothing chose a target for, which is
the *ordinary* cast of a creature with one — or when the announced card has
gone, the handler falls back to a scan. For a payload naming plain
``card_type: "creature"`` that scan was ``Game._return_creature_from_graveyard``:
the first creature card in the pile, whatever the printed phrase narrowed it
to.

Four cards lived it, three of them shipped, and nothing could see any of them:
each compiled ``supported`` with its narrowing in the payload, the picker
offered exactly the right cards, and the announcement gate refused a wrong one.
Only casting the card with a non-matching creature card lying *ahead* of the
right one shows the wrong card coming back.

* Mtenda Griffin (Mirage) — "target **Griffin** card"
* Strongarm Thug (Mercadian Masques) — "target **Mercenary** card"
* Crypt Angel (Invasion) — "target **blue or red** creature card"
* Lord of the Undead (Planeshift) — "target **Zombie** card", driven in
  ``tests/sets/test_pls_creatures.py``, which is where this was found.

What this does **not** fix, and is not trying to: with the announced card gone
the handler still looks for *another* eligible card rather than doing nothing
(CR 608.2b). That is the graveyard-target half of the resolution re-check
ROADMAP.md records as its own round, and it is every graveyard return in the
pool rather than these four. What changed here is only that the card it finds
is one the sentence could have named.
"""

from __future__ import annotations

from collections import Counter

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers.zones import _GRAVEYARD_NARROWING_KEYS
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _graveyard_game(catalog_by_name, *, hand=(), board=(), graveyard=()):
    """Seat 0 with *hand*, *board* and *graveyard* (in that order, so the first
    name is the card a bare scan reaches first). Nobody is interactive."""
    game = Game(players=[
        PlayerState(
            name="A", hand=[catalog_by_name[name] for name in hand],
            battlefield=[Permanent(card=catalog_by_name[name]) for name in board],
            graveyard=[catalog_by_name[name] for name in graveyard],
            library=[catalog_by_name["Forest"]] * 5,
        ),
        PlayerState(name="B", library=[catalog_by_name["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._sync_control()
    for permanent in game.players[0].battlefield:
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, game.players[0]


def _settle(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def test_crypt_angel_returns_a_blue_or_red_creature_card_not_the_green_one(catalog_by_name):
    """"When this creature enters, return target **blue or red** creature card
    from your graveyard to your hand." Cast with nothing announced, the green
    Bears lying ahead of the blue Sorcerer."""
    game, player = _graveyard_game(
        catalog_by_name, hand=["Crypt Angel"],
        graveyard=["Grizzly Bears", "Prodigal Sorcerer"],
    )

    assert game.cast_from_hand(0, "Crypt Angel").supported
    _settle(game)

    assert [card.name for card in player.hand] == ["Prodigal Sorcerer"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_strongarm_thug_returns_a_mercenary_card_not_the_bear(catalog_by_name):
    """"When this creature enters, you may return target **Mercenary** card
    from your graveyard to your hand." """
    game, player = _graveyard_game(
        catalog_by_name, hand=["Strongarm Thug"],
        graveyard=["Grizzly Bears", "Mercenaries"],
    )

    assert game.cast_from_hand(0, "Strongarm Thug").supported
    _settle(game)

    assert [card.name for card in player.hand] == ["Mercenaries"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_strongarm_thug_returns_nothing_when_no_mercenary_is_there(catalog_by_name):
    """The other half: with only a Bear in the pile there is no card the
    sentence names, and none comes back."""
    game, player = _graveyard_game(
        catalog_by_name, hand=["Strongarm Thug"], graveyard=["Grizzly Bears"],
    )

    assert game.cast_from_hand(0, "Strongarm Thug").supported
    _settle(game)

    assert not player.hand
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_mtenda_griffin_returns_a_griffin_card_not_the_bear(catalog_by_name):
    """"{W}, {T}: Return this creature to its owner's hand and return target
    **Griffin** card from your graveyard to your hand. Activate only during
    your upkeep." Both Griffins end in the hand — the one that paid and the one
    it fetched — and the Bears stay."""
    game, player = _graveyard_game(
        catalog_by_name, board=["Mtenda Griffin"],
        graveyard=["Grizzly Bears", "Mtenda Griffin"],
    )
    game.current_turn_phase, game.current_step = "beginning", "upkeep"

    result = game.activate_permanent_ability(0, "Mtenda Griffin")
    _settle(game)

    assert result.supported, result.details
    assert [card.name for card in player.hand] == ["Mtenda Griffin", "Mtenda Griffin"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


#: Every payload key the kind carries in the pool that is **not** a narrowing
#: of which card may be taken: the type itself, the announcement's description,
#: the zone's scope, the printed "another" (a slot, answered by
#: ``excluded_graveyard_slot``) and the announced X.
_NOT_A_NARROWING = frozenset({
    "any_card", "card_type", "card_types", "targets", "any_graveyard",
    "exclude_source_card", "x_from_count",
})


def _returns_in(instruction, found):
    if instruction is None:
        return
    if instruction.kind == "return_creature_from_graveyard_to_hand":
        found.append(instruction)
    for value in instruction.payload.values():
        if isinstance(value, tuple):
            for item in value:
                if hasattr(item, "kind"):
                    _returns_in(item, found)
        elif hasattr(value, "kind"):
            _returns_in(value, found)


def test_every_key_a_graveyard_return_carries_is_one_its_fallback_reads():
    """The ratchet, over both manifest roles. Every payload key this kind
    carries anywhere in the pool is either known not to narrow the card, or is
    in the set the handler's fallback routes on — so a *new* narrowing key
    arrives here as a failure rather than as a fifth card returning the wrong
    creature.

    Validated backwards: with ``graveyard_subtypes`` taken out of the handler's
    set this names Lord of the Undead, Mtenda Griffin and Strongarm Thug, which
    is the defect as it stood. Carried with a floor on what it examined.
    """
    cards = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    keys: Counter = Counter()
    carriers: dict[str, set[str]] = {}
    examined = 0
    for card in cards:
        program = compile_card_oracle(card)
        found: list = []
        for root in (*program.instructions, *(mode.instruction for mode in program.modes)):
            _returns_in(root, found)
        for instruction in found:
            examined += 1
            for key in instruction.payload:
                keys[key] += 1
                carriers.setdefault(key, set()).add(card.name)

    assert examined >= 40, examined
    unread = {
        key: sorted(carriers[key]) for key in keys
        if key not in _NOT_A_NARROWING and key not in _GRAVEYARD_NARROWING_KEYS
    }
    assert unread == {}
    # …and the narrowing keys really are in the pool, so the set is not vacuous.
    assert carriers.get("graveyard_subtypes", set()) >= {
        "Lord of the Undead", "Mtenda Griffin", "Strongarm Thug",
    }
    assert "Crypt Angel" in carriers.get("graveyard_colors", set())
