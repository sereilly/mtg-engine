"""Nemesis enchantments, Auras included.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: lands, mana and untapping ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_ench_game(set_pool, seat0, seat1):
    """Two seats with the given permanents and a library each to draw from."""
    island = set_pool("LEA")["Island"]
    players = [
        PlayerState(name="P0", battlefield=list(seat0), library=[island] * 8),
        PlayerState(name="P1", battlefield=list(seat1), library=[island] * 8),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w1g6_ench_take_turn(game, seat):
    """Start *seat*'s turn and settle everything its upkeep put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return seat


def test_rising_waters_locks_lands_and_releases_one_per_upkeep(set_pool):
    """"Lands don't untap during their controllers' untap steps. At the
    beginning of each player's upkeep, that player untaps a land they control."

    Both halves. The lock was the only half that ran: the release lowered to
    nothing, so the card was a harder lock than it prints. The release is the
    *upkeep player's*, not the enchantment's controller's, and a seat that is
    not asked takes a tapped land over an untapped one — untapping an untapped
    land is legal and does nothing.
    """
    waters = Permanent(card=set_pool("NEM")["Rising Waters"])
    ours = [Permanent(card=set_pool("LEA")["Island"]) for _ in range(3)]
    theirs = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(3)]
    game = _w1g6_ench_game(set_pool, [waters, *ours], theirs)
    for land in ours + theirs:
        land.tapped = True
    theirs[0].tapped = False  # first in board order, and already untapped

    _w1g6_ench_take_turn(game, 1)

    assert [land.tapped for land in theirs] == [False, False, True], (
        "the untap step untapped nothing; the upkeep player untapped one "
        "*tapped* land of their own"
    )
    assert all(land.tapped for land in ours), "the other seat's lands stay down"

    _w1g6_ench_take_turn(game, 0)

    assert [land.tapped for land in ours] == [False, True, True]
    assert [land.tapped for land in theirs] == [False, False, True]


def test_rising_waters_asks_the_upkeep_player_which_land(set_pool):
    """An interactive upkeep player is asked, and is offered only their own
    lands — "a land **they** control" — not the enchantment controller's."""
    waters = Permanent(card=set_pool("NEM")["Rising Waters"])
    ours = [Permanent(card=set_pool("LEA")["Island"])]
    theirs = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(2)]
    game = _w1g6_ench_game(set_pool, [waters, *ours], theirs)
    game.interactive_seats = {0, 1}
    for land in ours + theirs:
        land.tapped = True

    game.start_turn(1)
    for _ in range(4):
        if not game.stack or not game.resolve_top_of_stack():
            break

    prompts = [c for c in game.pending_choices if c.kind == "permanent_choice"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    assert prompts[0].player_index == 1
    offered = {perm.permanent_id for perm in game.live_permanent_choices(prompts[0])}
    assert offered == {land.permanent_id for land in theirs}

    assert game.confirm_permanent_choice(1, theirs[1].permanent_id)
    resolve_stack(game)

    assert [land.tapped for land in theirs] == [True, False]
    assert ours[0].tapped


def test_mana_cache_banks_each_players_untapped_lands_for_anyone(set_pool):
    """"At the beginning of each player's end step, put a charge counter on this
    enchantment for each untapped land that player controls. / Remove a charge
    counter from this enchantment: Add {C}. Any player may activate this ability
    but only during their turn before the end step."

    The count is the *end-step player's* untapped lands, not the Cache
    controller's. The mana ability is anybody's, the mana is the activator's,
    it never touches the stack (CR 605.3b), and the window is the activator's
    own turn up to — not including — the end step.
    """
    from engine.named_counters import counters_on

    cache = Permanent(card=set_pool("NEM")["Mana Cache"])
    ours = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(3)]
    theirs = [Permanent(card=set_pool("LEA")["Forest"]) for _ in range(4)]
    game = _w1g6_ench_game(set_pool, [cache, *ours], theirs)
    opponent = game.players[1]

    _w1g6_ench_take_turn(game, 1)
    theirs[0].tapped = True
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert counters_on(cache, "charge") == 3, "P1's three untapped Forests"

    refused = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert not refused.supported, "not during the end step itself"
    assert counters_on(cache, "charge") == 3, "a refused activation pays nothing"

    _w1g6_ench_take_turn(game, 0)
    refused = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert not refused.supported, "not during another player's turn"
    ours[0].tapped = True
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert counters_on(cache, "charge") == 5, "plus P0's two untapped Mountains"

    _w1g6_ench_take_turn(game, 1)
    result = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert result.supported, result.details
    assert not game.stack, "a mana ability does not use the stack"
    assert opponent.mana_pool["C"] == 1, "the mana is the activator's"
    assert game.players[0].mana_pool["C"] == 0
    assert counters_on(cache, "charge") == 4
