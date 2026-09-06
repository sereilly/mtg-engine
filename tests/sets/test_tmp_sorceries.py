"""Tempest sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W2G4: searching a library, and the top of it ---

from engine import Game, PlayerState
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle


def _w2g4_duel(*, libraries=((), ()), hands=((), ())):
    """Two seats with the libraries and hands the test names, mana off.

    Mana enforcement is off for the reason every rig in this file has it off:
    what these tests are about is what the effect *does* to a hidden zone, and
    leaving it on would make each of them a test of the mana payment.
    """
    seats = [
        PlayerState(name=f"P{index}", library=list(lib), hand=list(hand))
        for index, (lib, hand) in enumerate(zip(libraries, hands))
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w2g4_card(name, type_line, text="", colors=()):
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": text},
    )


def test_mana_severance_exiles_every_land_the_searcher_names(set_pool):
    """`Search your library for any number of land cards, exile them, then
    shuffle.` — the uncounted spelling of the exile search (CR 701.23b).

    The Rock Hydra test: the search prompt is answered and the lands are read
    out of *exile*, not off a claim that the instruction compiled.
    """
    card = set_pool("TMP")["Mana Severance"]
    forest = _w2g4_card("Forest", "Basic Land — Forest")
    bear = _w2g4_card("Grizzly Bears", "Creature — Bear")
    game = _w2g4_duel(
        libraries=([forest, bear, forest], ()), hands=([card], ()),
    )
    game.cast_from_hand(0, "Mana Severance")
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("search_exile_cards")))
    # Only the two lands are offerable; the bear is not a land card.
    assert prompt.data.get("card_types") == ("land",)
    assert prompt.data.get("maximum") is None, "'any number' prints no ceiling"
    picks = [
        {"zone": "library", "index": index}
        for index, entry in enumerate(game.players[0].library)
        if entry.primary_type == "land"
    ]
    assert game.confirm_search_exile(0, picks)

    assert [c.name for c in game.players[0].exile] == ["Forest", "Forest"]
    assert [c.name for c in game.players[0].library] == ["Grizzly Bears"]


def test_mana_severance_refuses_a_pick_that_is_not_a_land(set_pool):
    """The narrowing is enforced where the answer is validated, not dropped.

    A search that admitted the creature would be a tutor for anything, which is
    the failure this whole family is written to avoid: nothing crashes and the
    card simply does more than it prints.
    """
    card = set_pool("TMP")["Mana Severance"]
    bear = _w2g4_card("Grizzly Bears", "Creature — Bear")
    game = _w2g4_duel(libraries=([bear], ()), hands=([card], ()))
    game.cast_from_hand(0, "Mana Severance")
    game.resolve_top_of_stack()

    assert not game.confirm_search_exile(0, [{"zone": "library", "index": 0}])
    assert not game.players[0].exile
