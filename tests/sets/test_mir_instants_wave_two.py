"""Per-card tests for Mirage's instants — the wave-2 continuation.

The continuation of `test_mir_instants.py`, opened at wave 3 when that file
stood at 2,495 of the 2,600-line guard: near enough that two more groups'
blocks would sum past it at integration, which is the breach SET_PLAYBOOK.md
tells the integrator to expect and no single branch to be at fault for. Cut at
a **section boundary**, which is what `tests/sets/README.md` asks for past the
printed-type axis — every section here is self-contained and written up in
ROADMAP.md under the round or group that bought it.

The same block convention holds: append a delimited block headed
``# --- W<wave>G<n>: <topic> ---`` with **its own imports at the top of its own
block**, and do not edit this docstring or an earlier block.
"""

from __future__ import annotations


# --- W3G5: Shallow Grave's phantom graveyard picker ---

from engine import Game as _w3g5i_Game, PlayerState as _w3g5i_PlayerState  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g5i_compile  # noqa: E402
from engine.targeting import derive_cast_spec as _w3g5i_cast_spec  # noqa: E402


def _w3g5i_grave_game(set_pool, graveyard=()):
    """Shallow Grave in seat 0's hand, with the named cards in its graveyard."""
    pool = set_pool("MIR")
    game = _w3g5i_Game(players=[
        _w3g5i_PlayerState(
            name="P1",
            hand=[pool["Shallow Grave"]],
            library=[pool["Island"]] * 6,
            graveyard=[pool[name] for name in graveyard],
        ),
        _w3g5i_PlayerState(name="P2", library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_shallow_grave_derives_no_picker_because_it_chooses_nothing(set_pool):
    """"Return **the top** creature card of your graveyard to the battlefield."

    The picker sweep's Cleanse class. The handler says outright that nobody
    chooses — it overwrites whatever index the wire carried and walks the pile
    from the back — and the derivation claimed a ``graveyard_creature`` picker
    anyway. That is the derivation disagreeing with the program it is derived
    from, which is the same failure `_reanimation_spec`'s own docstring already
    records one payload key over.
    """
    pool = set_pool("MIR")
    card = pool["Shallow Grave"]

    assert _w3g5i_cast_spec(card, _w3g5i_compile(card)) is None


def test_shallow_grave_on_an_empty_graveyard_offers_the_client_nothing(set_pool):
    """The consequence the sweep names: a picker the client must fill from an
    empty candidate list is a cast that cannot be made.

    The enumeration is the evidence rather than the spec — it is what the app
    puts in front of the player — so it is asserted here and not only above.
    """
    game = _w3g5i_grave_game(set_pool)
    pool = set_pool("MIR")

    assert game._enumerate_targets(
        0, pool["Shallow Grave"],
        {"kind": "graveyard_creature", "own_graveyard_only": True},
        for_cast=True,
    ) == []


def test_shallow_grave_with_an_empty_graveyard_resolves_to_nothing(set_pool):
    """And the reading that makes the picker wrong rather than merely absent:
    with no creature card the spell resolves having done nothing, which is a
    legal (if wasteful) cast — not a cast the rules refuse."""
    game = _w3g5i_grave_game(set_pool)

    assert game.cast_from_hand(0, "Shallow Grave").supported
    game.resolve_stack()

    assert list(game.controlled_by(0)) == []
    assert "no creature card in the graveyard" in " ".join(game.log)


def test_shallow_grave_takes_the_last_creature_card_added(set_pool):
    """"The top creature card" is CR 404.3's ordering: a graveyard is ordered
    and CR 400.4 appends, so the top card is the most recently added and "the
    top creature card" is the last one of those. Two creature cards with a
    noncreature card on top of them is the board that tells the two readings
    apart."""
    game = _w3g5i_grave_game(
        set_pool, graveyard=("Bay Falcon", "Barbed Foliage", "Mtenda Lion")
    )

    assert game.cast_from_hand(0, "Shallow Grave").supported
    game.resolve_stack()

    assert [p.card.name for p in game.controlled_by(0)] == ["Mtenda Lion"]
    assert [c.name for c in game.players[0].graveyard] == [
        "Bay Falcon", "Barbed Foliage", "Shallow Grave"
    ]
