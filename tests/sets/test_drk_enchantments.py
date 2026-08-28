"""Per-card tests for The Dark's enchantments.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on


# --- G3: upkeep and land denial (The Dark) ---


def _run_upkeep(game: Game, seat: int) -> None:
    """One upkeep step for *seat*, with its triggers resolved off the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


def test_fasting_accrues_a_hunger_counter_each_upkeep_and_dies_at_five(set_pool):
    """"…put a hunger counter on this enchantment. Then destroy this enchantment
    if it has five or more hunger counters on it."

    This whole line compiled to **no instruction at all** — a card reporting
    supported whose upkeep trigger did nothing — because the trailing "if …"
    was unconsumed text. The counter and the threshold are both checked here:
    a threshold read as an equality would still pass at five, so the four
    upkeeps before it are the control.
    """
    fasting = Permanent(card=set_pool("DRK")["Fasting"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[fasting]), PlayerState(name="P2"),
    ])

    for expected in (1, 2, 3, 4):
        _run_upkeep(game, 0)
        assert game.is_on_battlefield(fasting)
        assert counters_on(fasting, "hunger") == expected

    _run_upkeep(game, 0)
    assert not game.is_on_battlefield(fasting)


def test_psychic_allergy_chooses_a_colour_as_it_enters(set_pool):
    """"As this enchantment enters, choose a color."

    The colour half of Jihad's entry line with no opponent beside it, so no
    seat is recorded at all. The headless default is the colour the opponents
    hold most of among nontoken permanents — a colour nobody controls would
    make the card inert, which is a legal choice no player would make.
    """
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])       # green
    wall = Permanent(card=lea["Wall of Wood"])         # green
    knight = Permanent(card=lea["White Knight"])       # white
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("DRK")["Psychic Allergy"]]),
        PlayerState(name="P2", battlefield=[bears, wall, knight]),
    ])

    assert game.cast_from_hand(0, "Psychic Allergy").supported
    allergy = next(p for p in game.all_permanents() if p.card.name == "Psychic Allergy")
    assert allergy.metadata["chosen_color"] == "G"


def test_psychic_allergy_pings_each_opponent_for_their_chosen_colour(set_pool):
    """"At the beginning of each **opponent's** upkeep, this enchantment deals X
    damage to that player, where X is the number of nontoken permanents of the
    chosen color **they** control."

    Three things the card says and this checks: the trigger fires on the
    opponent's upkeep and not the controller's, the count is taken on *that*
    player's battlefield, and the colour is the one recorded on the source as
    it entered — not a colour anything in the sentence names.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    bears = Permanent(card=lea["Grizzly Bears"])       # green, counts
    wall = Permanent(card=lea["Wall of Wood"])         # green, counts
    knight = Permanent(card=lea["White Knight"])       # white, does not
    mine = Permanent(card=lea["Grizzly Bears"])        # green but *mine*
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, mine]),
        PlayerState(name="P2", battlefield=[bears, wall, knight]),
    ])

    _run_upkeep(game, 1)

    assert game.players[1].life == 18
    assert game.players[0].life == 20


def test_psychic_allergy_lets_its_controller_sacrifice_two_islands(set_pool):
    """"At the beginning of your upkeep, destroy this enchantment unless you
    sacrifice two Islands."

    The alternative is decomposed to the `May` the sacrifice twin already uses,
    so accepting really pays the printed cost — two Islands, not one.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    islands = [Permanent(card=lea["Island"]) for _ in range(3)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, *islands]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Psychic Allergy", accept=True)

    assert game.is_on_battlefield(allergy)
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_psychic_allergy_is_destroyed_when_the_islands_are_not_paid(set_pool):
    """The other arm of the same sentence: declining destroys it."""
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    islands = [Permanent(card=lea["Island"]) for _ in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, *islands]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Psychic Allergy", accept=False)

    assert not game.is_on_battlefield(allergy)
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 2


def test_psychic_allergy_with_one_island_is_never_offered_the_payment(set_pool):
    """"…unless you **sacrifice two Islands**" with one Island on the board.

    A cost a player cannot pay is not an offer (``_action_is_takeable`` counts
    the printed number), so the enchantment simply goes — rather than the
    controller taking the offer, sacrificing one Island and keeping it.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    island = Permanent(card=lea["Island"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, island]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)

    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.is_on_battlefield(allergy)
    assert game.is_on_battlefield(island)


def test_season_of_the_witch_costs_two_life_each_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice this enchantment unless you
    pay 2 life."

    The mana spelling of this sentence was fused into an upkeep-registry kind;
    a *life* payment has no such handler, so it is decomposed into the `May`
    the counted-sacrifice alternative already uses — and CR 118.8's "only with
    a life total at least the amount" comes with it for free.
    """
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season]), PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Season of the Witch", accept=True)

    assert game.is_on_battlefield(season)
    assert game.players[0].life == 18


def test_season_of_the_witch_is_sacrificed_when_the_life_is_not_paid(set_pool):
    """The other arm: declining sacrifices it, and costs no life."""
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season]), PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Season of the Witch", accept=False)

    assert not game.is_on_battlefield(season)
    assert game.players[0].life == 20


def test_season_of_the_witch_destroys_the_creatures_that_stayed_home(set_pool):
    """"At the beginning of the end step, destroy all untapped creatures that
    didn't attack this turn, except for creatures that couldn't attack."

    The exception is the whole difficulty: "couldn't attack" is a question
    about the declare-attackers step, not about the end step — a Wall is still
    untapped and still idle when the trigger resolves. The answer is frozen at
    CR 508.1's turn-based action, so all four rows below are decided by one
    record taken at the right moment.
    """
    lea = set_pool("LEA")
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    attacker = Permanent(card=lea["Grizzly Bears"])
    idler = Permanent(card=lea["Hill Giant"])
    wall = Permanent(card=lea["Wall of Wood"])       # defender: couldn't attack
    theirs = Permanent(card=lea["Hill Giant"])       # not their turn to attack
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season, attacker, idler, wall]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game._enter_combat_step("declare_attackers")
    ok, _message = game.declare_attackers(0, [1])
    assert ok

    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert game.is_on_battlefield(attacker)   # it attacked
    assert game.is_on_battlefield(wall)       # it couldn't attack
    assert game.is_on_battlefield(theirs)     # not their turn either
    assert not game.is_on_battlefield(idler)  # untapped, able, and stayed home
