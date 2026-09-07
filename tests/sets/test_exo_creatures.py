"""Exodus creatures.

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


# --- W1G2: upkeep tolls, an intervening-if over a whole board, and a
# reveal-until ---
#
# Three creatures whose ability is a *decision* rather than an effect.
# Carnophage's toll is the printed currency the trailing-toll production could
# not read (life, where every other price was mana or an action); Zealots
# en-Dal's condition is a universal quantification, read as the count it already
# is; and Avenging Druid's offer is the whole reveal-until procedure, so
# accepting it does all of it and declining does none.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_G2C_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2c_duel():
    """Two seats, costs off, seat 0 active — with an ending of its own so a
    mechanical union cannot splice this body onto another group's signature."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def _g2c_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_carnophage_taps_when_the_life_is_not_paid(set_pool):
    """CR 119.4's currency as a toll's price. The consequence is the *decline*
    branch, so refusing has to tap it — an offer whose penalty went unapplied
    would be a Carnophage that untaps for free."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = {0}
    carnophage = _g2c_put(game, 0, set_pool("EXO")["Carnophage"])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Carnophage", accept=False)
    game._settle()

    assert carnophage.tapped
    assert alice.life == 20


def test_w1g2_carnophage_stays_untapped_for_a_life(set_pool):
    """The other branch, and the one that says the price is really charged."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = {0}
    carnophage = _g2c_put(game, 0, set_pool("EXO")["Carnophage"])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Carnophage", accept=True)
    game._settle()

    assert not carnophage.tapped
    assert alice.life == 19


def test_w1g2_zealots_en_dal_gains_life_on_an_all_white_board(set_pool):
    """CR 603.4's intervening-if. "All nonland permanents you control are white"
    holds when the seat controls no non-white one — the land is excluded by the
    printed word, which is why a Plains does not spoil it."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 0, _G2C_LEA["Plains"])

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 21


def test_w1g2_zealots_en_dal_is_spoiled_by_one_green_creature(set_pool):
    """The condition is universal, so a single non-white nonland permanent
    falsifies it — and the trigger does not fire at all (CR 603.4)."""
    game, alice, _bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 0, _G2C_LEA["Llanowar Elves"])

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 20


def test_w1g2_zealots_en_dal_ignores_an_opponents_green_creature(set_pool):
    """"…you control" is the seat clause, and dropping it would make the card
    unplayable against any green deck."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = set()
    _g2c_put(game, 0, set_pool("EXO")["Zealots en-Dal"])
    _g2c_put(game, 1, _G2C_LEA["Llanowar Elves"])
    assert bob is game.players[1]

    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)

    assert alice.life == 21


def test_w1g2_avenging_druid_ramps_and_bins_what_it_passed(set_pool):
    """The reveal-until run with the *battlefield* as its destination and the
    graveyard as the rest's — both read off the card, because the same sentence
    with "into your hand" is Sacred Guide and a different effect."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = set()
    druid = _g2c_put(game, 0, set_pool("EXO")["Avenging Druid"])
    alice.library.extend([
        _G2C_LEA["Giant Growth"], _G2C_LEA["Lightning Bolt"],
        _G2C_LEA["Forest"], _G2C_LEA["Mountain"],
    ])

    game._deal_damage_to_player(bob, 2, source=druid)
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(alice)) == [
        "Avenging Druid", "Forest",
    ]
    assert [c.name for c in alice.graveyard] == ["Giant Growth", "Lightning Bolt"]
    assert [c.name for c in alice.library] == ["Mountain"]


def test_w1g2_avenging_druid_declined_leaves_the_library_alone(set_pool):
    """"You **may** reveal …" is one offer over the whole procedure, so
    declining reveals nothing — the library is untouched rather than turned
    over and put back."""
    game, alice, bob = _g2c_duel()
    game.interactive_seats = {0}
    druid = _g2c_put(game, 0, set_pool("EXO")["Avenging Druid"])
    alice.library.extend([_G2C_LEA["Giant Growth"], _G2C_LEA["Forest"]])

    game._deal_damage_to_player(bob, 2, source=druid)
    game._settle()
    resolve_stack(game)
    assert game.confirm_optional_pay(0, "Avenging Druid", accept=False)
    game._settle()

    assert [c.name for c in alice.library] == ["Giant Growth", "Forest"]
    assert [p.card.name for p in game.controlled_by(alice)] == ["Avenging Druid"]
