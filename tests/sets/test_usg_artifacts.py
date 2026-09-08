"""Urza's Saga artifacts.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: Chimeric Staff — an X/X body with a duration ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g3a_staff(set_pool):
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    staff = Permanent(card=set_pool("USG")["Chimeric Staff"])
    game._put_permanent_onto_battlefield(0, staff, None)
    staff.metadata["summoning_sickness_turn"] = -99
    return game, staff


def test_chimeric_staff_is_the_size_the_activation_paid_for(set_pool):
    """"{X}: This artifact becomes an X/X Construct artifact creature until end
    of turn."

    The only card in the group whose body prints a *variable* size, and the
    only one with a duration. Two activations at different X are asserted
    rather than one, because a body that resolved X to zero or to a constant
    would look right at whichever number the test happened to pick.
    """
    game, staff = _g3a_staff(set_pool)
    assert not staff.is_creature

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=4)
    resolve_stack(game)

    assert staff.is_creature
    assert staff.has_type("artifact"), "CR 205.1b: it is still an artifact"
    assert staff.has_type("construct")
    assert (staff.effective_power, staff.effective_toughness) == (4, 4)

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=1)
    resolve_stack(game)
    assert (staff.effective_power, staff.effective_toughness) == (1, 1)


def test_chimeric_staff_stops_being_a_creature_at_cleanup(set_pool):
    """The duration, which every other card in this group lacks.

    "Until end of turn" is the difference between the Staff and the Veiled
    cycle, and it is the half a record written on the wrong key would lose:
    the animation would last for ever and the artifact would keep attacking
    on turns its controller never paid for.
    """
    game, staff = _g3a_staff(set_pool)
    game.activate_permanent_ability(0, "Chimeric Staff", x_value=3)
    resolve_stack(game)
    assert staff.is_creature

    game.resolve_cleanup_step(0)

    assert not staff.is_creature
    assert staff.has_type("artifact")

# --- W1G5: the two artifacts that reported supported and did nothing ---
from engine import Game, PlayerState
from engine.enter_effects import LIFE_PAID_AS_ENTERED
from engine.models import Permanent
from engine.named_counters import add_counters
from tests.helpers import _mk_creature_card, resolve_stack


def _g5a_game(*, interactive=()):
    """Two seats, no mana enforcement, and which of them answers prompts.

    Prefixed and ending on ``return game, p1, p2`` for the reason SET_PLAYBOOK.md
    gives: a helper whose last lines match another group's is spliced by a
    mechanical union onto the wrong signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _g5a_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def test_w1g5_phyrexian_processor_makes_a_token_the_size_of_the_life_it_ate(set_pool):
    """{4}, {T}: Create an X/X black Phyrexian Minion creature token, where X is
    the life paid as this artifact entered.

    Not a count of anything and not a recompute: the number was chosen once as
    a CR 614.1c entry replacement, and every activation afterwards reads the
    same one.
    """
    game, p1, _p2 = _g5a_game(interactive=(0,))
    processor = _g5a_put(game, 0, set_pool("USG")["Phyrexian Processor"])
    assert game.confirm_number_choice(0, 4), "the entry payment is announced"
    assert p1.life == 16
    assert processor.metadata[LIFE_PAID_AS_ENTERED] == 4

    assert game.activate_permanent_ability(0, "Phyrexian Processor").supported
    resolve_stack(game)
    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 1
    assert (tokens[0].effective_power, tokens[0].effective_toughness) == (4, 4)
    assert "Phyrexian Minion" in tokens[0].card.type_line


def test_w1g5_phyrexian_processor_keeps_reading_the_same_number(set_pool):
    """Two activations, one entry payment: the value is fixed as the permanent
    entered, so nothing here recomputes it and the second Minion is the size of
    the first."""
    game, p1, _p2 = _g5a_game(interactive=(0,))
    processor = _g5a_put(game, 0, set_pool("USG")["Phyrexian Processor"])
    game.confirm_number_choice(0, 3)

    for _ in range(2):
        processor.tapped = False
        game.activate_permanent_ability(0, "Phyrexian Processor")
        resolve_stack(game)
    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 2
    assert all(
        (token.effective_power, token.effective_toughness) == (3, 3)
        for token in tokens
    )


def test_w1g5_smokestack_sacrifices_one_permanent_per_soot_counter(set_pool):
    """At the beginning of each player's upkeep, that player sacrifices a
    permanent of their choice for each soot counter on this artifact.

    The count sits on the *source*, so it is the same number whoever the upkeep
    belongs to — read per-payer it would be counted on a permanent that payer
    does not control and answer zero every time.
    """
    game, _p1, p2 = _g5a_game()
    stack = _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    for i in range(4):
        _g5a_put(game, 1, _mk_creature_card("G5 B%d" % i, 1, 1))
    add_counters(stack, "soot", 2)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert len(p2.battlefield) == 2
    assert len(p2.graveyard) == 2


def test_w1g5_smokestack_with_no_soot_counters_asks_for_nothing(set_pool):
    """CR 608.2's "as much as possible" at zero: a seat that owes none is not
    prompted, which is the difference between a Smokestack that has just arrived
    and one that has been ticking."""
    game, _p1, p2 = _g5a_game(interactive=(1,))
    _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    _g5a_put(game, 1, _mk_creature_card("G5 B0", 1, 1))

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert not [c for c in game.pending_choices if c.kind == "sacrifice"]
    assert len(p2.battlefield) == 1


def test_w1g5_smokestack_makes_the_upkeep_player_choose(set_pool):
    """"…that player sacrifices a permanent **of their choice**": the prompt is
    owed by the seat whose upkeep it is, not by the artifact's controller, and
    the game waits while it is owed."""
    game, _p1, p2 = _g5a_game(interactive=(1,))
    stack = _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    for i in range(3):
        _g5a_put(game, 1, _mk_creature_card("G5 B%d" % i, 1, 1))
    add_counters(stack, "soot", 2)

    game.active_player_index = 1
    # No resolve_stack here on purpose: it answers whatever blocks the stack
    # through the registry's own default, which is precisely the prompt this
    # test is about — the helper would settle it out from under the assertions.
    game.resolve_upkeep(1)

    owed = [c for c in game.pending_choices if c.kind == "sacrifice"]
    assert len(owed) == 1
    assert owed[0].player_index == 1, "the upkeep player, not the controller"
    assert owed[0].data["count"] == 2
    assert len(p2.battlefield) == 3, "nothing goes until the choice is answered"


# --- W2G2: the graveyard as a zone — Whetstone, Crystal Chimes, Citanul Flute, Lifeline ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2_board(set_pool, name, *, seat=0):
    """Seat *seat* controls *name*, untapped and free to activate. W2G2's own."""
    alice, bob = PlayerState(name="G2-A"), PlayerState(name="G2-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    perm = Permanent(card=set_pool("USG")[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return game, perm


def test_w2g2_whetstone_mills_every_seat_not_a_target(set_pool):
    """"{3}: Each player mills two cards."

    Both libraries are asserted, and they start at different sizes: a mill that
    fell through to ``context.target`` would empty one pile twice as fast and a
    single-library assertion would not notice.
    """
    game, _ = _g2_board(set_pool, "Whetstone")
    filler = set_pool("USG")["Sanctum Custodian"]
    game.players[0].library = [filler] * 6
    game.players[1].library = [filler] * 9

    game.activate_permanent_ability(0, "Whetstone")
    resolve_stack(game)

    assert len(game.players[0].library) == 4
    assert len(game.players[1].library) == 7
    assert len(game.players[0].graveyard) == 2
    assert len(game.players[1].graveyard) == 2


def test_w2g2_crystal_chimes_returns_only_enchantments_and_only_yours(set_pool):
    """"{3}, {T}, Sacrifice this artifact: Return all enchantment cards from
    your graveyard to your hand."

    Three assertions the card would pass with one of its narrowings dropped:
    the creature card stays put (the type filter reaches the sweep), the
    opponent's enchantment stays put (the sweep is one seat's), and the Chimes
    itself is in the graveyard afterwards (the sacrifice cost was paid).
    """
    pool = set_pool("USG")
    game, chimes = _g2_board(set_pool, "Crystal Chimes")
    mine, theirs = game.players
    mine.graveyard = [pool["Sanctum Custodian"], pool["Rune of Protection: Red"]]
    theirs.graveyard = [pool["Rune of Protection: Red"]]

    game.activate_permanent_ability(0, "Crystal Chimes")
    resolve_stack(game)

    assert [c.name for c in mine.hand] == ["Rune of Protection: Red"]
    assert [c.name for c in mine.graveyard] == ["Sanctum Custodian", "Crystal Chimes"]
    assert [c.name for c in theirs.graveyard] == ["Rune of Protection: Red"]
    assert not game.is_on_battlefield(chimes)
