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


# --- G2: self-clocks, delayed self-sacrifice and card-flow order ---

from unittest.mock import patch

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g2_kites_board(set_pool):
    """Goblin Kites, a 1/1 it can lift and a 3/3 it cannot."""
    lea = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    kites = Permanent(card=set_pool("FEM")["Goblin Kites"])
    small = Permanent(card=lea["Mons's Goblin Raiders"])   # 1/1
    big = Permanent(card=lea["Hill Giant"])                # 3/3
    for permanent in (kites, small, big):
        permanent.metadata["summoning_sickness_turn"] = -99
    player = PlayerState(name="P1", battlefield=[kites, small, big])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._settle()
    return game, player, kites, small, big


def _g2_fly(game, kites, rider, *, win):
    """Activate the Kites on *rider* with the end step's flip forced.

    ``engine.handlers._common`` is where ``flip_coin`` draws from, so patching
    ``random.random`` on it is patching the one module object every reader of
    the RNG shares -- and the draw still happens, which patching ``flip_coin``
    itself would skip.
    """
    with patch(
        "engine.handlers._common.random.random", return_value=0.0 if win else 0.99
    ):
        result = game.activate_permanent_ability(
            0, "Goblin Kites",
            permanent_index=game.battlefield_index_of(kites),
            target_player_index=0,
            target_permanent_index=game.battlefield_index_of(rider),
        )
        while game.stack:
            game.resolve_top_of_stack()
        game._settle()
        game.resolve_end_step(0)
        while game.stack:
            game.resolve_top_of_stack()
        game._settle()
    return result


def test_goblin_kites_lifts_a_small_creature_and_drops_it_on_a_lost_flip(set_pool):
    """"{R}: Target creature you control with toughness 2 or less gains flying
    until end of turn. Flip a coin at the beginning of the next end step. If you
    lose the flip, sacrifice that creature."

    The last two printed sentences are one delayed triggered ability (CR 603.7):
    the flip happens at the end step and so does everything hanging off it. A
    conditional performed *now* would read a flip that had not happened.
    """
    game, player, kites, small, _big = _g2_kites_board(set_pool)

    _g2_fly(game, kites, small, win=False)

    assert [c.name for c in player.graveyard] == ["Mons's Goblin Raiders"]
    assert sorted(p.card.name for p in player.battlefield) == [
        "Goblin Kites", "Hill Giant",
    ]


def test_goblin_kites_keeps_the_creature_on_a_won_flip(set_pool):
    """The other face of CR 705.2. A card that only ever lost would be a
    strictly worse one, and a delayed ability that dropped its condition would
    be exactly that."""
    game, player, kites, small, _big = _g2_kites_board(set_pool)

    _g2_fly(game, kites, small, win=True)

    assert player.graveyard == []
    assert sorted(p.card.name for p in player.battlefield) == [
        "Goblin Kites", "Hill Giant", "Mons's Goblin Raiders",
    ]


def test_goblin_kites_grants_flying_before_the_end_step_arrives(set_pool):
    """The first sentence is immediate. Checked separately from the drop,
    because a card that only sacrificed things would pass the tests above."""
    game, _player, kites, small, _big = _g2_kites_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Goblin Kites",
        permanent_index=game.battlefield_index_of(kites),
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(small),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert small.has_keyword("flying")
    assert [entry.event for entry in game.delayed_triggers] == ["next_end_step"]
    assert game.delayed_triggers[0].bound_permanent_id == small.permanent_id


def test_goblin_kites_refuses_a_creature_the_phrase_excludes(set_pool):
    """"...with toughness 2 or less" is a narrowing on the *target*, so it is
    enforced where CR 602.2b puts it: at activation, with nothing paid. A
    grant whose noun phrase never reached the picker would lift a 3/3 and put
    it at risk of a coin flip the card never offered it."""
    game, _player, kites, _small, big = _g2_kites_board(set_pool)

    ability = compile_card_oracle(kites.card).activated_abilities[0]
    refusal = game.activation_target_refusal(
        0, kites, ability,
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(big),
    )
    assert refusal is not None

    result = game.activate_permanent_ability(
        0, "Goblin Kites",
        permanent_index=game.battlefield_index_of(kites),
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(big),
    )
    assert not result.supported
    assert not big.has_keyword("flying")
    assert game.delayed_triggers == []
# --- G1: counters as named state ---
#
# The enchantment half of the round whose creatures are in
# ``test_fem_creatures.py``. Tidal Influence is Homarid's sentence with the
# subject and the affected set changed, which is why they were implemented
# together: one condition production reads both.

from engine import Game
from engine.auras import attach_aura
from engine.cast_restrictions import check_cast_timing
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from tests.helpers import _nosick as _g1e_nosick


def _g1e_game(life=20):
    game = Game(
        players=[PlayerState(name="P0", life=life), PlayerState(name="P1", life=life)]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def _g1e_put(game, seat, card):
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _g1e_upkeep(game, seat=0):
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    game._settle()


# -- Tidal Influence -------------------------------------------------------


def _g1e_tide_board(set_pool):
    game = _g1e_game()
    tide = _g1e_put(game, 0, set_pool("FEM")["Tidal Influence"])
    merfolk = _g1e_put(game, 0, set_pool("LEA")["Merfolk of the Pearl Trident"])
    bear = _g1e_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    game._settle()
    return game, tide, merfolk, bear


def test_tidal_influence_swings_every_blue_creature_with_its_tide(set_pool):
    """"As long as there is exactly one tide counter on this enchantment, all
    blue creatures get -2/-0" / "…exactly three… +2/+0."

    The same sentence Homarid prints about itself, aimed at a set of creatures
    instead — so it is the same condition answered by the same evaluator, and
    the anthem holds exactly while the count does.
    """
    game, tide, merfolk, bear = _g1e_tide_board(set_pool)

    assert counters_on(tide, "tide") == 1
    assert merfolk.effective_power == -1, "a 1/1 at -2/-0"
    assert bear.effective_power == 2, "green is not blue"

    _g1e_upkeep(game)
    assert counters_on(tide, "tide") == 2
    assert merfolk.effective_power == 1, "two is neither one nor three"

    _g1e_upkeep(game)
    assert counters_on(tide, "tide") == 3
    assert merfolk.effective_power == 3
    assert bear.effective_power == 2

    _g1e_upkeep(game)
    assert counters_on(tide, "tide") == 0, "four or more empties it (CR 603.8)"
    assert merfolk.effective_power == 1


def test_a_second_tidal_influence_cannot_be_cast(set_pool):
    """"Cast this spell only if no permanents named Tidal Influence are on the
    battlefield." Every battlefield, not just yours — there is one battlefield
    (CR 400.1), and a card that stopped only your own second copy would be a
    strictly weaker card."""
    game, _tide, _merfolk, _bear = _g1e_tide_board(set_pool)
    text = set_pool("FEM")["Tidal Influence"].oracle_text.lower()

    assert check_cast_timing(game, 0, text) is not None, "its controller is stopped"
    assert check_cast_timing(game, 1, text) is not None, "and so is everyone else"


def test_tidal_influence_is_castable_on_an_empty_board(set_pool):
    """The other half of the same restriction: with none out, nothing refuses.
    A gate that always says no is as wrong as one that never does."""
    game = _g1e_game()
    _g1e_put(game, 0, set_pool("LEA")["Merfolk of the Pearl Trident"])
    game._settle()

    text = set_pool("FEM")["Tidal Influence"].oracle_text.lower()
    assert check_cast_timing(game, 0, text) is None


# -- Tourach's Gate --------------------------------------------------------


def _g1e_gate_board(set_pool, *extra):
    game = _g1e_game()
    made = [_g1e_put(game, 0, set_pool("LEA")["Swamp"])]
    for name in extra:
        made.append(_g1e_put(game, 0, set_pool("FEM")[name]))
    gate = _g1e_put(game, 0, set_pool("FEM")["Tourach's Gate"])
    attach_aura(gate, made[0])
    game._settle()
    return (game, gate, *made)


def test_tourachs_gate_winds_itself_down_and_is_sacrificed(set_pool):
    """"At the beginning of your upkeep, remove a time counter from this Aura.
    If there are no time counters on this Aura, sacrifice it."

    One sentence and its consequence: the removal, then a question about what
    the removal left. It enters with none, so a Thrull has to be fed to it
    first.
    """
    game, gate, _land, thrull = _g1e_gate_board(set_pool, "Basal Thrull")
    assert counters_on(gate, "time") == 0

    fed = game.activate_permanent_ability(
        0, "Tourach's Gate", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(thrull)],
    )
    game._settle()
    assert fed.supported, fed.details
    assert counters_on(gate, "time") == 3
    assert not game.is_on_battlefield(thrull), "the cost ate it"

    for expected in (2, 1):
        _g1e_upkeep(game)
        assert counters_on(gate, "time") == expected
        assert game.is_on_battlefield(gate)

    _g1e_upkeep(game)
    assert counters_on(gate, "time") == 0
    assert not game.is_on_battlefield(gate), "the last counter sacrifices it"


def test_the_gate_pumps_the_attackers_by_tapping_its_land(set_pool):
    """"Tap enchanted land: Attacking creatures you control get +2/-1 until end
    of turn."

    The cost taps a permanent that is not the ability's source, so the *land*
    is what has to be untapped — and once it is tapped the printed restriction
    refuses the second activation.
    """
    game, _gate, land = _g1e_gate_board(set_pool)
    bear = _g1e_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    game._settle()
    _g1e_nosick(bear)
    game._set_phase_and_step("combat", "declare_attackers")
    slot = list(game.controlled_by(0)).index(bear)
    assert game.declare_attackers(0, [slot], 1)[0]

    result = game.activate_permanent_ability(0, "Tourach's Gate", ability_index=1)
    game._settle()

    assert result.supported, result.details
    assert land.tapped, "the cost taps the enchanted land, not the Aura"
    assert (bear.effective_power, bear.effective_toughness) == (4, 1)

    again = game.activate_permanent_ability(0, "Tourach's Gate", ability_index=1)
    assert not again.supported, "'Activate only if enchanted land is untapped'"
    assert (bear.effective_power, bear.effective_toughness) == (4, 1), "nothing paid"


# -- Merseine --------------------------------------------------------------


def _g1e_merseine_board(set_pool, enforce=True):
    """Merseine (seat 0's) on an opponent's Grizzly Bears, which costs {1}{G}."""
    game = _g1e_game()
    game.enforce_mana_costs = enforce
    bear = _g1e_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    net = _g1e_put(game, 0, set_pool("FEM")["Merseine"])
    attach_aura(net, bear)
    game._settle()
    return game, net, bear


def test_merseine_holds_the_creature_down_while_a_net_counter_is_on_it(set_pool):
    """"Enchanted creature doesn't untap during its controller's untap step if
    this Aura has a net counter on it."

    The step is printed as the *creature's* controller's and the counter is on
    the *Aura* — a crossing of two axes that the pairing table this replaced
    had no row for, which would have left the restriction unenforced rather
    than merely missing.
    """
    game, net, bear = _g1e_merseine_board(set_pool)
    assert counters_on(net, "net") == 3, "it enters with three"

    bear.tapped = True
    game.resolve_untap_step(1)

    assert bear.tapped, "three net counters, still held"


def test_merseine_lets_go_once_the_last_net_counter_is_paid_off(set_pool):
    """The other side of the same clause: with the counters gone the creature
    untaps normally."""
    game, net, bear = _g1e_merseine_board(set_pool, enforce=False)
    for _ in range(3):
        # Seat 1 is the creature's controller, which is who the card lets pay.
        result = game.activate_permanent_ability(
            1, "Merseine", ability_index=0, source_controller_index=0,
        )
        game._settle()
        assert result.supported, result.details

    assert counters_on(net, "net") == 0
    bear.tapped = True
    game.resolve_untap_step(1)
    assert not bear.tapped


def test_only_the_enchanted_creatures_controller_may_pay_merseine(set_pool):
    """"Only the controller of the enchanted creature may activate this
    ability." A permission is only done when it is enforced in **both**
    directions: this one opens the ability to a seat CR 602.1a closes, and
    closes it to the seat that could already reach it."""
    game, net, _bear = _g1e_merseine_board(set_pool, enforce=False)

    refused = game.activate_permanent_ability(0, "Merseine", ability_index=0)

    assert not refused.supported
    assert "controller of the enchanted" in refused.details
    assert counters_on(net, "net") == 3, "nothing was removed"


def test_merseine_charges_the_enchanted_creatures_own_mana_cost(set_pool):
    """"Pay enchanted creature's mana cost." The symbols are the host's, so
    they cannot be known when the card compiles — and a cost read as zero is an
    ability activated for free, which is what an unread one becomes."""
    game, net, _bear = _g1e_merseine_board(set_pool)

    # Seat 1 controls the creature, so it is the seat the card lets pay — and
    # it is refused here for the *mana*, which is the point: the message has to
    # be about the cost and not about the permission, or the test would pass on
    # a cost nobody charged.
    broke = game.activate_permanent_ability(
        1, "Merseine", ability_index=0, source_controller_index=0,
    )
    assert not broke.supported, "Grizzly Bears costs {1}{G} and the pool is empty"
    assert "insufficient mana" in broke.details, broke.details
    assert counters_on(net, "net") == 3

    game.players[1].mana_pool = {"G": 1, "C": 1}
    paid = game.activate_permanent_ability(
        1, "Merseine", ability_index=0, source_controller_index=0,
    )
    game._settle()

    assert paid.supported, paid.details
    assert counters_on(net, "net") == 2
    assert not any(game.players[1].mana_pool.values()), "{1}{G} was spent"


# --- G4: costs from the board and the graveyard ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g4_game(battlefield, *, graveyard=(), their_graveyard=()):
    p1 = PlayerState(
        name="P1", battlefield=list(battlefield), graveyard=list(graveyard)
    )
    p2 = PlayerState(name="P2", graveyard=list(their_graveyard))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2


def test_goblin_warrens_eats_two_goblins_for_three_tokens(set_pool):
    """"{2}{R}, **Sacrifice two Goblins**: Create three 1/1 red Goblin creature
    tokens."

    A *counted* sacrifice cost. Both Goblins are gone before the ability is on
    the stack (CR 601.2h), and the three tokens arrive after — so the board this
    leaves is two Goblins poorer and three tokens richer, never five creatures.
    """
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    goblins = [
        _g4_nosick(Permanent(card=pool["Goblin Chirurgeon"])) for _ in range(2)
    ]
    game, p1, _p2 = _g4_game([warrens, *goblins])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert sorted(perm.card.name for perm in p1.battlefield) == [
        "Goblin Token", "Goblin Token", "Goblin Token", "Goblin Warrens",
    ]
    assert [card.name for card in p1.graveyard] == [
        "Goblin Chirurgeon", "Goblin Chirurgeon",
    ]


def test_goblin_warrens_cannot_be_activated_with_one_goblin(set_pool):
    """The control the count exists for. One Goblin is no more a payment of a
    two-Goblin cost than none is (CR 601.2h), so the ability is not activated at
    all (CR 602.2b) — and the lone Goblin is still on the battlefield.

    Without this, a cost that matched a *singular* pattern would have eaten one
    Goblin and made three tokens for it, which is the card at half price."""
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    goblin = _g4_nosick(Permanent(card=pool["Goblin Chirurgeon"]))
    game, p1, _p2 = _g4_game([warrens, goblin])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert not result.supported
    assert [perm.card.name for perm in p1.battlefield] == [
        "Goblin Warrens", "Goblin Chirurgeon",
    ]
    assert p1.graveyard == []


def test_goblin_warrens_will_not_eat_a_creature_that_is_not_a_goblin(set_pool):
    """The noun phrase is a narrowing, not decoration: two Merfolk pay nothing.

    A charger reading "sacrifice two creatures" would have taken them — which is
    the dropped-rider bug with the card still reporting supported."""
    pool = set_pool("FEM")
    warrens = Permanent(card=pool["Goblin Warrens"])
    merfolk = [
        _g4_nosick(Permanent(card=pool["River Merfolk"])) for _ in range(2)
    ]
    game, p1, _p2 = _g4_game([warrens, *merfolk])

    result = game.activate_permanent_ability(0, "Goblin Warrens", permanent_index=0)
    game._settle()

    assert not result.supported
    assert p1.graveyard == []
    assert len(p1.battlefield) == 3


def test_night_soil_exiles_two_creature_cards_for_a_saproling(set_pool):
    """"{1}, **Exile two creature cards from a single graveyard**: Create a 1/1
    green Saproling creature token."

    The cost is paid at activation (CR 602.2b), so the cards are in exile before
    the token is made. Either player's pile may pay it — the phrase names "a"
    graveyard, not "your" one."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, _p2 = _g4_game(
        [soil], graveyard=[lea["Grizzly Bears"], lea["Hurloon Minotaur"]]
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert p1.graveyard == []
    assert sorted(card.name for card in p1.exile) == [
        "Grizzly Bears", "Hurloon Minotaur",
    ]
    assert sorted(perm.card.name for perm in p1.battlefield) == [
        "Night Soil", "Saproling Token",
    ]


def test_night_soil_reaches_an_opponents_graveyard(set_pool):
    """"…from **a** single graveyard" — anybody's. Read as "your graveyard" the
    card would be dead against an empty pile of one's own, which is the ordinary
    way it is played."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, p2 = _g4_game(
        [soil], their_graveyard=[lea["Grizzly Bears"], lea["Hurloon Minotaur"]]
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert p2.graveyard == []
    assert len(p1.exile) == 2
    assert any(perm.card.name == "Saproling Token" for perm in p1.battlefield)


def test_night_soil_will_not_take_one_card_from_each_graveyard(set_pool):
    """"…from **a single** graveyard" is the rider that gets parsed and dropped,
    and dropped it makes the cost strictly cheaper: two piles holding one
    creature card each would pay a cost the card says they cannot.

    Nothing is exiled and no token is made — the ability is not activated at all
    (CR 602.2b)."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, p2 = _g4_game(
        [soil],
        graveyard=[lea["Grizzly Bears"]],
        their_graveyard=[lea["Hurloon Minotaur"]],
    )

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert not result.supported
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]
    assert [card.name for card in p2.graveyard] == ["Hurloon Minotaur"]
    assert p1.exile == []
    assert [perm.card.name for perm in p1.battlefield] == ["Night Soil"]


def test_night_soil_will_not_exile_land_cards(set_pool):
    """"…two **creature** cards". A pile of lands pays nothing, which is what
    tells the narrowing from decoration."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    soil = Permanent(card=pool["Night Soil"])
    game, p1, _p2 = _g4_game([soil], graveyard=[lea["Forest"], lea["Forest"]])

    result = game.activate_permanent_ability(0, "Night Soil", permanent_index=0)
    game._settle()

    assert not result.supported
    assert len(p1.graveyard) == 2
    assert p1.exile == []


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


# --- G3: combat triggers, block restrictions and damage substitution ---
from engine.auras import attach_aura
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _g3_mantle_board(set_pool):
    """Farrel's Mantle on a 2/2 attacker, with two creatures to aim at.

    Seat 0 is interactive so the two decisions the trigger owes — its target
    and the offer to the enchanted creature's controller — *queue* rather than
    taking their defaults, which is also what makes combat wait for them
    (CR 608.2).
    """
    pool = set_pool("FEM")
    # A creature with no abilities of its own, deliberately: Farrel's Zealot
    # prints the *same* trigger condition, and two triggers owing two targets
    # would make the prompt this test reads ambiguous.
    attacker = Permanent(card=pool["Vodalian Soldiers"])     # 1/2, vanilla
    mantle = Permanent(card=pool["Farrel's Mantle"])
    victim = Permanent(card=pool["Icatian Phalanx"])         # 2/4
    bystander = Permanent(card=pool["Icatian Infantry"])     # 1/1
    game = Game(players=[
        PlayerState(name="P0", life=20, battlefield=[attacker, mantle]),
        PlayerState(name="P1", life=20, battlefield=[victim, bystander]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    attach_aura(mantle, attacker)
    game._settle()
    game.start_turn(0)
    for perm in (attacker, victim, bystander):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, attacker, mantle, victim, bystander


def _g3_mantle_combat(game):
    """Attack unblocked and stop where blocks lock — CR 509.1h, which is where
    "attacks and isn't blocked" is announced."""
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {})[0]
    game._settle()
    game.advance_combat_phase()   # blocks lock; the trigger fires
    game._settle()
    for _ in range(len(game.stack) + 8):
        if not game.stack or not game.resolve_top_of_stack():
            break
    game._settle()


def _g3_finish_mantle_combat(game):
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break
    game.check_state_based_actions()


def test_g3_farrels_mantle_enchant_clause_offers_a_creature(set_pool):
    """The Aura's ``Enchant creature`` line is what the *cast* picker reads.

    Asserted on its own because the failure has no other symptom: a clause that
    derived ``kind: "none"`` would leave the client with nothing to ask for and
    the Aura uncastable in the app, while every compile-time instrument still
    reported the card supported.
    """
    card = set_pool("FEM")["Farrel's Mantle"]
    program = compile_card_oracle(card)

    assert program.supported
    assert derive_cast_spec(card, program) == {"kind": "creature"}


def test_g3_farrels_mantle_trades_combat_damage_for_a_bite(set_pool):
    """"…its controller may have it deal damage equal to its **power plus 2**
    to another target creature. If that player does, the attacking creature
    assigns no combat damage this turn."

    Every clause is measured by something it changed: the 1/2 deals **3** (the
    printed constant is carried, not dropped), the creature it bites is not
    itself ("another"), and the defending player's life is untouched — which is
    the only evidence the substitution ran, since nothing is prevented and no
    shield is spent.
    """
    game, attacker, mantle, victim, bystander = _g3_mantle_board(set_pool)

    pending = list(game.pending_choices_of("trigger_target"))
    assert pending == [], "the target is chosen when the trigger is put on the stack"

    _g3_mantle_combat(game)
    owed = list(game.pending_choices_of("trigger_target", 0))
    assert len(owed) == 1, game.log
    offered = {t["permanent_id"] for t in owed[0].data["targets"]}
    assert victim.permanent_id in offered
    assert attacker.permanent_id not in offered, (
        "\"another target creature\" excludes the creature dealing the damage"
    )
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()

    assert game.confirm_optional_pay(0, "Farrel's Mantle", accept=True), game.log
    _g3_finish_mantle_combat(game)

    assert victim.damage_marked == 3, game.log
    assert game.players[1].life == 20, game.log


def test_g3_declining_the_mantle_leaves_the_attack_alone(set_pool):
    """"If that player does" — the other half. Nothing bitten, so the rider
    never runs and the 1/2 connects for one."""
    game, attacker, mantle, victim, bystander = _g3_mantle_board(set_pool)

    _g3_mantle_combat(game)
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()
    assert game.confirm_optional_pay(0, "Farrel's Mantle", accept=False), game.log
    _g3_finish_mantle_combat(game)

    assert victim.damage_marked == 0
    assert game.players[1].life == 19, game.log


# --- G6: Raiding Party ---

from engine import Game as _G6Game, PlayerState as _G6PlayerState
from engine.card_loader import load_cards as _g6_load_cards
from engine.card_loader import manifest_set_path as _g6_manifest_set_path
from engine.models import Permanent as _G6Permanent
from engine.oracle import compile_card_oracle as _g6_compile
from engine.targeting import derive_cast_spec as _g6_derive_cast_spec


def _g6_lea():
    return {card.name: card for card in _g6_load_cards(_g6_manifest_set_path("LEA"))}


def _g6_board(set_pool, *, interactive=(0, 1)):
    """Raiding Party, an Orc to eat, two white creatures, and four Plains.

    Two Plains on each battlefield, because "chooses up to two Plains" names no
    controller and the sweep behind it names none either — a board where every
    Plains belonged to one seat could not tell a picker that dropped the words
    from one that read them.
    """
    fem, lea = set_pool("FEM"), _g6_lea()
    party = _G6Permanent(card=fem["Raiding Party"])
    orc = _G6Permanent(card=fem["Brassclaw Orcs"])
    mine_a = _G6Permanent(card=fem["Icatian Infantry"])       # white
    mine_b = _G6Permanent(card=fem["Icatian Scout"])          # white
    red = _G6Permanent(card=fem["Brassclaw Orcs"])            # not white
    my_plains = [_G6Permanent(card=lea["Plains"]) for _ in range(2)]
    theirs = _G6Permanent(card=fem["Icatian Priest"])         # white
    their_plains = [_G6Permanent(card=lea["Plains"]) for _ in range(2)]
    forest = _G6Permanent(card=lea["Forest"])
    mine = [party, orc, mine_a, mine_b, red, *my_plains]
    yours = [theirs, *their_plains, forest]
    for permanent in mine + yours:
        permanent.metadata["summoning_sickness_turn"] = -99
    game = _G6Game(players=[
        _G6PlayerState(name="P1", battlefield=mine),
        _G6PlayerState(name="P2", battlefield=yours),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game, {
        "party": party, "orc": orc, "mine_a": mine_a, "mine_b": mine_b,
        "red": red, "theirs": theirs, "forest": forest,
        "my_plains": my_plains, "their_plains": their_plains,
    }


def _g6_raid(game, board):
    """Sacrifice the Orc to put the ability on the stack and start resolving."""
    controlled = list(game.controlled_by(0))
    return game.activate_permanent_ability(
        0, "Raiding Party", cost_permanent_index=controlled.index(board["orc"])
    )


def _g6_owed(game, kind):
    return [c for c in game.pending_choices if c.kind == kind]


def test_g6_raiding_party_is_supported_whole(set_pool):
    """Both printed lines, and the count that says so is the ability's own.

    A card is supported when *any* of its lines is, so the assertion that
    matters is on the activated ability rather than on the card: line 1 alone
    made this card report supported for a whole round while the ability behind
    the colon compiled to nothing.
    """
    program = _g6_compile(set_pool("FEM")["Raiding Party"])

    assert program.supported
    assert [a.supported for a in program.activated_abilities] == [True]
    steps = program.activated_abilities[0].instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "tap_any_number_matching", "for_each", "destroy_all_lands_of_type",
    ], steps


def test_g6_a_white_spell_cannot_target_raiding_party(set_pool):
    """"can't be the target of **white spells**" — a class of spell named by
    its colour, which the immunity table had no axis for.

    Asked of the picker and of the cast gate, which are the two places CR
    601.2c is enforced: Disenchant destroys target enchantment and is white, so
    an unread colour word is a Raiding Party that dies to it.
    """
    game, board = _g6_board(set_pool)
    disenchant = _g6_lea()["Disenchant"]
    game.players[1].hand = [disenchant]
    spec = _g6_derive_cast_spec(disenchant, _g6_compile(disenchant))

    offered = game._enumerate_targets(1, disenchant, spec, for_cast=True)
    # By slot, which is what an entry carries — there is no ``permanent_id`` key
    # on it, and a membership test against one would pass over any list at all.
    party_slot = (
        game.controller_index_of(board["party"]),
        game.battlefield_index_of(board["party"]),
    )
    assert party_slot not in {
        (entry["seat"], entry["index"]) for entry in offered
    }, offered

    result = game.cast_from_hand(
        1, "Disenchant", target_permanent_ids=[board["party"].permanent_id]
    )
    assert not result.supported, result.details
    assert game.is_on_battlefield(board["party"]), game.log
    # Refused at announcement (CR 601.2c), not countered on resolution
    # (CR 608.2b): the difference is a card, and it is the whole of what the
    # `is_creature` test in `_validate_cast_targets` used to cost.
    assert [c.name for c in game.players[1].hand] == ["Disenchant"], game.log


def test_g6_a_green_spell_may_still_target_raiding_party(set_pool):
    """The other half, and the one that says the clause is a *narrowed* shroud
    rather than shroud: Desert Twister destroys target permanent and is green,
    so nothing stops it."""
    game, board = _g6_board(set_pool)
    game.players[1].hand = [set_pool("ARN")["Desert Twister"]]

    result = game.cast_from_hand(
        1, "Desert Twister", target_permanent_ids=[board["party"].permanent_id]
    )
    game._settle()

    assert result.supported, result.details
    assert not game.is_on_battlefield(board["party"]), game.log


def test_g6_an_ability_from_a_white_source_cannot_target_raiding_party(set_pool):
    """"…**or abilities from white sources**" — the second conjunct, and the one
    the reader in ``auras.py`` could not have seen: it answered only for an
    Aura's attachment, and this clause is printed about the permanent itself.

    Arenson's Aura is a white enchantment whose activated ability destroys
    target enchantment, so it is the whole question in one card. The colourless
    Despotic Scepter beside it is the control: the clause names white sources,
    not every source.
    """
    game, board = _g6_board(set_pool)
    ice = set_pool("ICE")
    white_source = _G6Permanent(card=ice["Arenson's Aura"])
    colorless_source = _G6Permanent(card=set_pool("ATQ")["Candelabra of Tawnos"])
    game.players[1].battlefield.extend([white_source, colorless_source])
    game._sync_control()

    assert not game._can_be_targeted(
        board["party"], white_source.card, caster_index=1,
        ability_source=white_source,
    )
    assert game._can_be_targeted(
        board["party"], colorless_source.card, caster_index=1,
        ability_source=colorless_source,
    )


def test_g6_each_tap_buys_two_plains_choices_and_no_tap_buys_none(set_pool):
    """"Each player may tap any number of untapped white creatures they control.
    For each creature tapped this way, that player chooses up to two Plains."

    The arithmetic is the card: two creatures tapped is **two** choice prompts,
    and a seat that taps nothing is asked nothing. Both halves in one test,
    because they are one claim — the loop runs once per creature the record
    holds, and a loop that walked seats or the board instead would get exactly
    one of them wrong.

    CR 101.4 / CR 608.2e: the taps are offered in turn order from the active
    player, and only once every seat has answered does the second action begin.
    """
    game, board = _g6_board(set_pool)
    _g6_raid(game, board)
    game._settle()

    owed = _g6_owed(game, "tap_any_number")
    assert [c.player_index for c in owed] == [0], (
        "one seat at a time, active player first (CR 101.4)"
    )
    offered = {p.card.name for p in game.live_tap_any_number(owed[0])}
    assert offered == {"Icatian Infantry", "Icatian Scout"}, (
        "'untapped **white** creatures **they control**' — not the Orc beside "
        f"them and not the opponent's Priest: {offered}"
    )
    assert not _g6_owed(game, "permanent_set_choice"), (
        "the Plains choices wait until every seat has tapped (CR 608.2e)"
    )

    assert game.confirm_tap_any_number(
        0, [board["mine_a"].permanent_id, board["mine_b"].permanent_id]
    )
    game._settle()
    assert game.confirm_tap_any_number(1, []), "'any number' includes none"
    game._settle()

    choices = _g6_owed(game, "permanent_set_choice")
    assert [c.player_index for c in choices] == [0], (
        "two creatures tapped by seat 0 and none by seat 1: seat 1 chooses "
        f"nothing at all — {[(c.player_index, c.data['up_to']) for c in choices]}"
    )
    assert choices[0].data["up_to"] == 2
    # Answering the first arms the second: one prompt per creature, and both
    # belong to the seat that tapped it.
    assert game.confirm_permanent_set_choice(0, [])
    game._settle()
    second = _g6_owed(game, "permanent_set_choice")
    assert [c.player_index for c in second] == [0], game.log
    assert game.confirm_permanent_set_choice(0, [])
    game._settle()
    assert not _g6_owed(game, "permanent_set_choice"), (
        "two creatures, two choices, and no third"
    )


def test_g6_chosen_plains_survive_and_the_rest_are_destroyed(set_pool):
    """"Then destroy all Plains that weren't chosen this way by any player."

    The picks are unrestricted by controller and accumulate across prompts, so
    the test names one Plains on each battlefield from two different choices and
    checks that both survive while their neighbours die. A sweep that dropped
    the relative clause destroys all four; one that kept only the last answer
    destroys three.
    """
    game, board = _g6_board(set_pool)
    _g6_raid(game, board)
    game._settle()

    assert game.confirm_tap_any_number(
        0, [board["mine_a"].permanent_id, board["mine_b"].permanent_id]
    )
    game._settle()
    assert game.confirm_tap_any_number(1, [board["theirs"].permanent_id])
    game._settle()

    saved = [board["my_plains"][0], board["their_plains"][0]]
    doomed = [board["my_plains"][1], board["their_plains"][1]]
    picks = [
        [board["my_plains"][0].permanent_id],
        [board["their_plains"][0].permanent_id],
        [],
    ]
    for wanted in picks:
        owed = _g6_owed(game, "permanent_set_choice")
        assert owed, game.log
        assert game.confirm_permanent_set_choice(owed[0].player_index, wanted)
        game._settle()

    assert not _g6_owed(game, "permanent_set_choice"), game.log
    assert all(game.is_on_battlefield(p) for p in saved), game.log
    assert not any(game.is_on_battlefield(p) for p in doomed), game.log
    assert game.is_on_battlefield(board["forest"]), "only Plains are swept"


def test_g6_the_offer_holds_the_ability_open_until_it_is_answered(set_pool):
    """CR 608.2 / CR 117.3b: nothing behind a prompt runs until it is answered.

    The evidence is the board rather than a flag — with the first tap still
    owed, every Plains is still there. A sweep that ran ahead of the answers
    would destroy all four, because nothing had been chosen yet.
    """
    game, board = _g6_board(set_pool)
    _g6_raid(game, board)
    game._settle()

    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "tap_any_number"
    every_plains = board["my_plains"] + board["their_plains"]
    assert all(game.is_on_battlefield(p) for p in every_plains), game.log


def test_g6_a_non_interactive_seat_takes_its_stated_default(set_pool):
    """Both defaults are decisions, and both are exercised here.

    A seat nobody can ask **taps everything eligible that is not attacking**
    and then **saves its own Plains first**, so a board where every seat is
    non-interactive resolves with every Plains its controller could cover still
    standing. That is the policy, not an accident: each tap buys two Plains, and
    a default that picked an opponent's would be answering for the wrong player.
    """
    game, board = _g6_board(set_pool, interactive=())
    result = _g6_raid(game, board)
    game._settle()

    assert result.supported, result.details
    assert not game.pending_choices, "a headless game never blocks on this card"
    assert board["mine_a"].tapped and board["mine_b"].tapped
    assert board["theirs"].tapped
    assert not board["red"].tapped, "the Orc is not white"
    every_plains = board["my_plains"] + board["their_plains"]
    assert all(game.is_on_battlefield(p) for p in every_plains), game.log


def test_g6_a_default_never_spends_a_pick_on_an_opponents_plains(set_pool):
    """The half of the default that is a decision rather than an ordering.

    P2 is the only non-interactive seat and controls **one** Plains against a
    ceiling of two, so its default has a pick left over. It leaves it unspent:
    the chosen Plains are the ones that survive, so a leftover pick handed to an
    opponent is a gift the card never asked anyone to make. "Own first, then
    others to fill the ceiling" would save one of P1's here, and P1 chose
    nothing at all.
    """
    game, board = _g6_board(set_pool, interactive=(0,))
    game.remove_from_battlefield(board["their_plains"][1])
    game._settle()
    _g6_raid(game, board)
    game._settle()

    assert game.confirm_tap_any_number(0, []), "P1 declines the offer"
    game._settle()

    assert not game.pending_choices, "a non-interactive seat never queues this"
    assert game.is_on_battlefield(board["their_plains"][0]), (
        "P2's default tapped its Priest and saved the one Plains it controls"
    )
    assert not any(game.is_on_battlefield(p) for p in board["my_plains"]), (
        "P2 had a pick to spare and did not spend it on P1's Plains"
    )


def test_g6_a_seat_that_taps_nothing_saves_nothing(set_pool):
    """The card's whole point, stated as one game: the seat that declines the
    offer has no Plains choices and loses every Plains it controls.

    The opposite of the default test above, and the reason that one is not
    enough on its own — a default that tapped nothing would pass it by
    accident."""
    game, board = _g6_board(set_pool)
    _g6_raid(game, board)
    game._settle()

    assert game.confirm_tap_any_number(0, [board["mine_a"].permanent_id])
    game._settle()
    assert game.confirm_tap_any_number(1, [])
    game._settle()

    owed = _g6_owed(game, "permanent_set_choice")
    assert [c.player_index for c in owed] == [0], game.log
    assert game.confirm_permanent_set_choice(
        0, [p.permanent_id for p in board["my_plains"]]
    )
    game._settle()

    assert all(game.is_on_battlefield(p) for p in board["my_plains"]), game.log
    assert not any(
        game.is_on_battlefield(p) for p in board["their_plains"]
    ), "P2 tapped nothing, so P2 chose nothing, so P2's Plains all die"


def test_g6_the_pick_is_capped_and_checked_against_what_was_offered(set_pool):
    """"up to **two**" is a ceiling the engine enforces, not a hint the client
    is trusted with. A third Plains, or a permanent that is not one, is refused
    whole — the prompt stays owed rather than recording part of the answer."""
    game, board = _g6_board(set_pool)
    _g6_raid(game, board)
    game._settle()
    assert game.confirm_tap_any_number(0, [board["mine_a"].permanent_id])
    game._settle()
    assert game.confirm_tap_any_number(1, [])
    game._settle()

    owed = _g6_owed(game, "permanent_set_choice")[0]
    three = [
        board["my_plains"][0].permanent_id,
        board["my_plains"][1].permanent_id,
        board["their_plains"][0].permanent_id,
    ]
    assert not game.confirm_permanent_set_choice(0, three)
    assert not game.confirm_permanent_set_choice(0, [board["forest"].permanent_id])
    assert _g6_owed(game, "permanent_set_choice") == [owed], (
        "a refused answer leaves the prompt owed"
    )


def test_g6_the_tap_prompt_records_only_what_it_tapped(set_pool):
    """"tapped this way" is not "tapped".

    A Plains and a white creature are tapped *before* the ability is activated;
    neither may reach the loop. The record is the only thing that can tell them
    apart, which is why this window needs one at all — unlike a destroy sweep,
    its objects never leave the battlefield for the board to stop knowing about.
    """
    game, board = _g6_board(set_pool)
    game.become_tapped(board["mine_b"])
    game.become_tapped(board["my_plains"][0])
    _g6_raid(game, board)
    game._settle()

    owed = _g6_owed(game, "tap_any_number")[0]
    assert {p.card.name for p in game.live_tap_any_number(owed)} == {
        "Icatian Infantry"
    }, "'**untapped** white creatures' — the tapped Scout is not offered"
    assert game.confirm_tap_any_number(0, [board["mine_a"].permanent_id])
    game._settle()
    assert game.confirm_tap_any_number(1, [])
    game._settle()

    assert len(_g6_owed(game, "permanent_set_choice")) == 1, (
        "one creature tapped this way, so one choice — not one per tapped "
        f"creature on the board: {game.log}"
    )
