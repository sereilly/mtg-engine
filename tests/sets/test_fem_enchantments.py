"""Per-card tests for Fallen Empires' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G5: prices offered to a player, prevention and control ---
from engine import Game, PlayerState
from engine.models import Permanent


def _g5_ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _heroism_board(set_pool, *, floating=None):
    """P2 attacks with a red Hill Giant; P1 holds Heroism and a white creature
    to feed it."""
    giant = _g5_ready(Permanent(card=set_pool("LEA")["Hill Giant"]))
    heroism = Permanent(card=set_pool("FEM")["Heroism"])
    lion = _g5_ready(Permanent(card=set_pool("LEA")["Savannah Lions"]))
    p1 = PlayerState(name="P1", battlefield=[heroism, lion])
    p2 = PlayerState(name="P2", battlefield=[giant])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    if floating:
        p2.mana_pool.update(floating)
    return game, giant, lion


def _through_combat_damage(game: Game) -> None:
    game.auto_resolve_pending_choices()
    game.advance_combat_phase()   # declare blockers
    game.advance_combat_phase()   # combat damage


def test_heroism_fogs_an_attacker_whose_controller_cannot_pay(set_pool):
    """"Sacrifice a white creature: For each attacking red creature, prevent
    all combat damage that would be dealt by that creature this turn unless its
    controller pays {2}{R}."

    The loop runs over the board, the offer is made to each attacker's own
    controller, and the *unpaid* branch is the shield.
    """
    game, giant, lion = _heroism_board(set_pool)

    assert game.activate_permanent_ability(0, "Heroism").supported, game.log
    assert not any(p is lion for p in game.players[0].battlefield), (
        "the coloured, typed sacrifice is the cost"
    )
    _through_combat_damage(game)

    assert game.players[0].life == 20, game.log


def test_heroism_lets_a_paid_attacker_through(set_pool):
    """The other branch, and the one that proves the offer is a decision:
    {2}{R} buys the damage back."""
    game, giant, _lion = _heroism_board(set_pool, floating={"R": 1, "C": 2})

    game.activate_permanent_ability(0, "Heroism")
    _through_combat_damage(game)

    assert game.players[0].life == 17, game.log


def test_heroism_leaves_an_attacker_of_the_wrong_colour_alone(set_pool):
    """"For each attacking **red** creature" - the loop's noun phrase is the
    whole of what it reaches, so a white attacker is neither offered the price
    nor shielded."""
    lions = _g5_ready(Permanent(card=set_pool("LEA")["Savannah Lions"]))   # 2/1 white
    heroism = Permanent(card=set_pool("FEM")["Heroism"])
    fodder = _g5_ready(Permanent(card=set_pool("LEA")["Pearled Unicorn"]))
    p1 = PlayerState(name="P1", battlefield=[heroism, fodder])
    p2 = PlayerState(name="P2", battlefield=[lions])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(1, [0])

    game.activate_permanent_ability(0, "Heroism")
    _through_combat_damage(game)

    assert game.players[0].life == 18, game.log


def _tidal_flats_board(set_pool, *, flying=False, floating=None):
    attacker = _g5_ready(Permanent(
        card=set_pool("LEA")["Serra Angel" if flying else "Hill Giant"]
    ))
    flats = Permanent(card=set_pool("FEM")["Tidal Flats"])
    # A flier can only be blocked by one (CR 509.1b), so the blocker matches
    # the attacker - the question under test is whether the *offer* is made,
    # and a board where no block is legal could not tell the two apart.
    blocker = _g5_ready(Permanent(
        card=set_pool("LEA")["Serra Angel" if flying else "Grizzly Bears"]
    ))
    p1 = PlayerState(name="P1", battlefield=[flats, blocker])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {1: 0})[0]
    if floating:
        p2.mana_pool.update(floating)
    return game, attacker, blocker


def test_tidal_flats_gives_first_strike_when_the_attacker_declines_to_pay(set_pool):
    """"{U}{U}: For each attacking creature without flying, its controller may
    pay {1}. If that player doesn't, creatures you control blocking that
    creature gain first strike until end of turn."

    The same loop Heroism runs, with the work on the decline branch - and the
    grant reaches the blockers of *that* attacker, read off the combat maps.
    """
    game, attacker, blocker = _tidal_flats_board(set_pool)

    assert game.activate_permanent_ability(0, "Tidal Flats").supported, game.log
    game.auto_resolve_pending_choices()

    assert game._has_keyword(blocker, "first strike"), game.log
    assert not game._has_keyword(attacker, "first strike")


def test_tidal_flats_grants_nothing_when_the_attacker_pays(set_pool):
    """{1} out of a floating pool is the whole difference between the two
    branches - and a non-interactive seat pays a toll it can afford, which is
    the stated default rather than a fallback."""
    game, _attacker, blocker = _tidal_flats_board(set_pool, floating={"C": 1})

    game.activate_permanent_ability(0, "Tidal Flats")
    game.auto_resolve_pending_choices()

    assert not game._has_keyword(blocker, "first strike"), game.log


def test_tidal_flats_never_offers_a_flier_the_price(set_pool):
    """"...creature **without flying**" is a layer-6 question (CR 613.1f), so a
    loop that dropped it would toll every attacker - and grant first strike
    against the fliers the card is printed to let past."""
    game, _angel, blocker = _tidal_flats_board(set_pool, flying=True)

    game.activate_permanent_ability(0, "Tidal Flats")
    game.auto_resolve_pending_choices()

    assert not game._has_keyword(blocker, "first strike"), game.log


def _chant_board(set_pool, chant: str, land: str, *, creatures: int = 1):
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=set_pool("FEM")[chant])])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=set_pool("LEA")["Grizzly Bears"]) for _ in range(creatures)
        ],
        hand=[set_pool("LEA")[land]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game.cast_from_hand(1, land, target_player_index=1)
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    return game


def test_thelons_chant_takes_a_counter_from_the_player_who_played_the_swamp(set_pool):
    """"Whenever a player puts a Swamp onto the battlefield, this enchantment
    deals 3 damage to that player unless the player puts a -1/-1 counter on a
    creature they control."

    "That player" is the seat the *entering permanent* belongs to, frozen by
    the one seam every entry path passes through - not a target this ability
    chose.
    """
    game = _chant_board(set_pool, "Thelon's Chant", "Swamp")
    bear = next(p for p in game.players[1].battlefield if p.is_creature)

    assert game.players[1].life == 20, game.log
    assert (bear.effective_power, bear.effective_toughness) == (1, 1), game.log


def test_thelons_chant_deals_the_damage_when_there_is_no_creature_to_shrink(set_pool):
    """An offer whose price the seat cannot pay is never made, so the penalty
    applies - and the ability has to *resolve* to apply it, which it would not
    if the counter placement were read as a target it announced (CR 603.3c)."""
    game = _chant_board(set_pool, "Thelon's Chant", "Swamp", creatures=0)

    assert game.players[1].life == 17, game.log


def test_tourachs_chant_reads_they_as_the_same_referent_the_player_names(set_pool):
    """The two Chants are one sentence with the land type changed - and with
    "the player" and "they" spelling one referent two ways. A reader that took
    them for different seats would put the counter on the wrong board."""
    game = _chant_board(set_pool, "Tourach's Chant", "Forest")
    bear = next(p for p in game.players[1].battlefield if p.is_creature)

    assert game.players[1].life == 20
    assert (bear.effective_power, bear.effective_toughness) == (1, 1), game.log


def test_a_chant_ignores_the_other_chants_land_type(set_pool):
    """The land type is the trigger's noun phrase, so a Forest is not a Swamp."""
    game = _chant_board(set_pool, "Thelon's Chant", "Forest")
    bear = next(p for p in game.players[1].battlefield if p.is_creature)

    assert game.players[1].life == 20
    assert (bear.effective_power, bear.effective_toughness) == (2, 2), game.log


def test_a_chant_fires_on_its_own_controllers_land_too(set_pool):
    """"Whenever **a player** puts a Swamp onto the battlefield" - every seat,
    the enchantment's own controller included."""
    chant = Permanent(card=set_pool("FEM")["Thelon's Chant"])
    p1 = PlayerState(name="P1", battlefield=[chant],
                     hand=[set_pool("LEA")["Swamp"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    # The turn is opened past the upkeep on purpose. The Chant's *other* line -
    # "at the beginning of your upkeep, sacrifice this enchantment unless you
    # pay {G}" - fires before the land drop on its controller's own turn, and
    # `can_pay_upkeep_mana` covers a coloured pip out of floating mana alone,
    # so a board with a Forest on it still loses the card under test.
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")

    game.cast_from_hand(0, "Swamp", target_player_index=0)
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()

    assert game.players[0].life == 17, game.log
# --- end G5 ---
