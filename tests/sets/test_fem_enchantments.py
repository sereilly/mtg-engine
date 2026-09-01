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
