"""Planeshift artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: damage and the odd ones ---
#
# Skyship Weatherlight arrived *supported* with its second ability hollow, and
# the hole was two layers deep. The activated line had no production ("Choose a
# card at random that was exiled with <this>. Put that card into its owner's
# hand."), and beneath it the entry trigger never wrote the CR 607.2a link the
# line reads: the exile search recorded a pile on its permanent only when the
# pile was printed face down (Mangara's Tome).

import random as _w1g8a_random  # noqa: E402

from engine import Game as _w1g8a_Game, PlayerState as _w1g8a_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8a_load,  # noqa: E402
                                manifest_set_path as _w1g8a_path)
from engine.linked_exile import linked_entries as _w1g8a_linked  # noqa: E402
from engine.models import (CardDefinition as _w1g8a_Card,  # noqa: E402
                           Permanent as _w1g8a_Permanent)
from engine.oracle import compile_card_oracle as _w1g8a_compile  # noqa: E402
from engine.targeting import derive_activation_spec as _w1g8a_activation_spec  # noqa: E402

from tests.helpers import resolve_stack as _w1g8a_resolve_stack  # noqa: E402


def _w1g8a_lea():
    return {card.name: card for card in _w1g8a_load(_w1g8a_path("LEA"))}


def _w1g8a_library(lea):
    """Two creatures, two artifacts and three cards that are neither."""
    return [
        lea[name] for name in (
            "Hill Giant", "Island", "Sol Ring", "Lightning Bolt",
            "Grizzly Bears", "Island", "Juggernaut",
        )
    ]  # W1G8 artifacts: a library to search


def _w1g8a_game(hand, library, *, interactive=()):
    filler = _w1g8a_Card(
        name="Filler", mana_cost="{3}", cmc=3.0, type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Filler", "type_line": "Sorcery"},
    )
    game = _w1g8a_Game(players=[
        _w1g8a_Player(name="P0", hand=list(hand), library=list(library)),
        _w1g8a_Player(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # W1G8 artifacts: the game


def _w1g8a_launch(game):
    """Cast the Weatherlight and answer its entry search the headless way."""
    cast = game.cast_from_hand(0, "Skyship Weatherlight")
    assert cast.supported, cast.details
    _w1g8a_resolve_stack(game)
    game.auto_resolve_pending_choices()
    ship = next(
        perm for perm in game.controlled_by(0)
        if perm.card.name == "Skyship Weatherlight"
    )
    ship.metadata["summoning_sickness_turn"] = -99
    return ship  # W1G8 artifacts: the ship


def _w1g8a_activate(game, ship):
    ship.tapped = False
    used = game.activate_permanent_ability(
        0, "Skyship Weatherlight", ability_index=0
    )
    assert used.supported, used.details
    _w1g8a_resolve_stack(game)  # W1G8 artifacts: one activation


def test_w1g8_skyship_weatherlight_has_no_hollow_ability(set_pool):
    """Both abilities compile to an instruction, and the second targets
    nothing — the card is picked at random, not chosen (CR 115.1)."""
    program = _w1g8a_compile(set_pool("PLS")["Skyship Weatherlight"])

    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.supported and ability.instruction is not None
    assert ability.instruction.payload == {
        "zone": "hand", "one_of": True, "at_random": True,
    }
    assert ability.cost.requires_tap and ability.cost.mana["generic"] == 4
    assert _w1g8a_activation_spec(ability) is None
    (trigger,) = program.triggered_abilities
    assert trigger.instruction is not None


def test_w1g8_skyship_weatherlight_links_what_its_entry_exiled(set_pool):
    """The entry search exiles artifact and/or creature cards and nothing else,
    shuffles, and records the pile *on the Weatherlight* — which is the only
    thing its second ability can read."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea)
    )

    ship = _w1g8a_launch(game)

    exiled = sorted(card.name for card in game.players[0].exile)
    assert exiled == ["Grizzly Bears", "Hill Giant", "Juggernaut", "Sol Ring"]
    assert sorted(entry["card"].name for entry in _w1g8a_linked(ship)) == exiled
    assert not any(entry.get("face_down") for entry in _w1g8a_linked(ship)), (
        "the cards are exiled face up"
    )
    assert sorted(card.name for card in game.players[0].library) == [
        "Island", "Island", "Lightning Bolt",
    ]


def test_w1g8_skyship_weatherlight_any_number_is_the_searchers_choice(set_pool):
    """"Any number of": an interactive seat is asked, may take two of the four,
    and may not take a card that is neither an artifact nor a creature."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea),
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Skyship Weatherlight").supported
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    (prompt,) = game.pending_choices_of("search_exile_cards", 0)
    assert prompt.data["card_types"] == ("artifact", "creature")
    library = game.players[0].library

    island = next(i for i, card in enumerate(library) if card.name == "Island")
    assert not game.confirm_search_exile(0, [{"zone": "library", "index": island}])
    picks = [
        {"zone": "library", "index": index}
        for index, card in enumerate(library)
        if card.name in ("Sol Ring", "Juggernaut")
    ]
    assert game.confirm_search_exile(0, picks)
    _w1g8a_resolve_stack(game)

    ship = next(iter(game.controlled_by(0)))
    assert sorted(entry["card"].name for entry in _w1g8a_linked(ship)) == [
        "Juggernaut", "Sol Ring",
    ]
    assert len(game.players[0].library) == 5


def test_w1g8_skyship_weatherlight_returns_one_card_at_random_each_time(set_pool):
    """One card per activation, out of the linked pile and into its owner's
    hand; the rest stay exiled with the ship. Four activations empty the pile
    and a fifth finds nothing."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea)
    )
    ship = _w1g8a_launch(game)
    pile = sorted(card.name for card in game.players[0].exile)

    for expected_left in (3, 2, 1, 0):
        _w1g8a_activate(game, ship)
        assert len(_w1g8a_linked(ship)) == expected_left
        assert len(game.players[0].exile) == expected_left
    assert sorted(card.name for card in game.players[0].hand) == pile
    assert ship.tapped, "{T} is part of the cost"

    _w1g8a_activate(game, ship)
    assert len(game.players[0].hand) == 4
    assert "nothing is exiled with Skyship Weatherlight" in game.log[-2]


def test_w1g8_skyship_weatherlight_picks_through_the_seeded_rng(set_pool):
    """Chance, and reproducible chance: the same seed returns the same card
    (a seeded AI simulation must replay exactly), and over a run of seeds more
    than one card comes back first — it is not "the first entry"."""
    lea = _w1g8a_lea()
    ship_card = set_pool("PLS")["Skyship Weatherlight"]

    def first_pick(seed):
        _w1g8a_random.seed(seed)
        game = _w1g8a_game([ship_card], _w1g8a_library(lea))
        ship = _w1g8a_launch(game)
        _w1g8a_activate(game, ship)
        (card,) = game.players[0].hand
        return card.name

    assert first_pick(11) == first_pick(11)
    assert len({first_pick(seed) for seed in range(12)}) > 1


def test_w1g8_skyship_weatherlight_reads_only_its_own_pile(set_pool):
    """CR 607.2a / CR 400.7: the pile is the cards *this object's* entry
    trigger exiled. A card some other effect exiled is not in it, and a
    Weatherlight that left and came back is a new object with an empty set —
    the old cards stay exiled and nothing can fetch them."""
    lea = _w1g8a_lea()
    ship_card = set_pool("PLS")["Skyship Weatherlight"]
    game = _w1g8a_game([ship_card], [lea["Island"], lea["Sol Ring"]])
    stranger = lea["Juggernaut"]
    game.players[0].exile.append(stranger)

    ship = _w1g8a_launch(game)
    assert [entry["card"].name for entry in _w1g8a_linked(ship)] == ["Sol Ring"]
    _w1g8a_activate(game, ship)
    assert [card.name for card in game.players[0].hand] == ["Sol Ring"]
    _w1g8a_activate(game, ship)
    assert stranger in game.players[0].exile, "never exiled with the ship"

    game = _w1g8a_game([ship_card], [lea["Island"], lea["Sol Ring"]])
    first = _w1g8a_launch(game)
    game.remove_from_battlefield(first)
    returned = _w1g8a_Permanent(card=ship_card)
    game.players[0].battlefield.append(returned)
    game._settle()
    returned.metadata["summoning_sickness_turn"] = -99

    _w1g8a_activate(game, returned)
    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].exile] == ["Sol Ring"]
