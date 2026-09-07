"""Exodus lands.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: a land-play trigger that excludes its own arrival ---
#
# "When you play **another** land" is one word away from a card that destroys
# itself the moment it is played: `_process_land_enters` runs before the play is
# announced, so City of Traitors is already on the battlefield and observing
# when its own land drop fires the event. The exclusion is compared by
# ``permanent_id`` rather than by the card, because a deck repeats one immutable
# ``CardDefinition`` per copy — a second City of Traitors is the *same* object
# as the first, and a name or identity test would suppress a trigger the card
# really makes.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from tests.helpers import resolve_stack

_G2L_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2l_duel():
    """Two seats with costs off. Its own name and its own last line, so no
    union can graft another group's body onto this signature."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set()
    return game, game.players[0], game.players[1]


def test_w1g2_city_of_traitors_survives_being_played(set_pool):
    """The word "another" (CR 109.2 — not this object) is the whole of it: the
    land is on the battlefield by the time its own play is announced."""
    game, alice, _bob = _g2l_duel()
    alice.hand.append(set_pool("EXO")["City of Traitors"])

    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(alice)] == ["City of Traitors"]
    assert alice.graveyard == []


def test_w1g2_city_of_traitors_dies_to_the_next_land(set_pool):
    """And the trigger really fires for a land that is not it."""
    game, alice, _bob = _g2l_duel()
    alice.hand.append(set_pool("EXO")["City of Traitors"])
    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    alice.hand.append(_G2L_LEA["Forest"])
    assert game.cast_from_hand(0, "Forest").supported
    game._settle()
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(alice)] == ["Forest"]
    assert [c.name for c in alice.graveyard] == ["City of Traitors"]


def test_w1g2_city_of_traitors_ignores_an_opponents_land(set_pool):
    """"When **you** play another land" — the seat clause the event filter has
    always read, unaffected by the new exclusion beside it."""
    game, alice, bob = _g2l_duel()
    alice.hand.append(set_pool("EXO")["City of Traitors"])
    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    bob.hand.append(_G2L_LEA["Forest"])
    assert game.cast_from_hand(1, "Forest").supported
    game._settle()
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(alice)] == ["City of Traitors"]


def test_w1g2_a_second_city_of_traitors_kills_the_first(set_pool):
    """The reason the exclusion is keyed on ``permanent_id``. Both copies are
    literally one ``CardDefinition``, so a comparison by card — or by name —
    would have the first City spare the second's arrival and sit there."""
    game, alice, _bob = _g2l_duel()
    city = set_pool("EXO")["City of Traitors"]
    alice.hand.append(city)
    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    alice.hand.append(city)
    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(alice)] == ["City of Traitors"]
    assert [c.name for c in alice.graveyard] == ["City of Traitors"]


def test_w1g2_city_of_traitors_taps_for_two_colorless(set_pool):
    """Its second line, which worked before this round and is asserted so a
    change to the first cannot quietly cost it."""
    game, alice, _bob = _g2l_duel()
    alice.hand.append(set_pool("EXO")["City of Traitors"])
    assert game.cast_from_hand(0, "City of Traitors").supported
    game._settle()
    resolve_stack(game)

    city = list(game.controlled_by(alice))[0]
    city.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(0, "City of Traitors").supported
    resolve_stack(game)

    assert alice.mana_pool.get("C") == 2
