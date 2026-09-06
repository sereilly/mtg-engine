"""Weatherlight artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: dies, enters and leaves triggers ---
from engine import Game, PlayerState
from engine.models import Permanent


def test_straw_golem_watches_the_spell_type_not_just_the_spell(
    set_pool, catalog_by_name
):
    """"**When** an opponent casts a creature spell, sacrifice this creature."

    The grammar could read this clause under "whenever" and not under "when" -
    its whole condition reader lived inside the ``whenever`` branch, and the
    ``when`` branch fell back to a table of fixed phrases that carries no noun
    phrase at all. CR 603.1 makes the two words one kind of ability, so the
    printed word was the only thing keeping the Golem off the board.

    Both halves are asserted: a Golem that sacrificed itself to any spell would
    pass the second one alone.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    golem = Permanent(card=set_pool("WTH")["Straw Golem"])
    game._put_permanent_onto_battlefield(0, golem, None)
    bob.hand[:] = [catalog_by_name["Lightning Bolt"], catalog_by_name["Grizzly Bears"]]

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    while game.stack and not game.waiting_prompt():
        game.resolve_top_of_stack()
    assert golem in alice.battlefield, "a Bolt is not a creature spell"

    game.cast_from_hand(1, "Grizzly Bears")
    while game.stack and not game.waiting_prompt():
        game.resolve_top_of_stack()

    assert alice.battlefield == []
    assert [card.name for card in alice.graveyard] == ["Straw Golem"]
