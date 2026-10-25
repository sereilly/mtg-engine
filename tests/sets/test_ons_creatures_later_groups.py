"""Onslaught creatures (legendary ones too) — wave 1's groups W1G3 to W1G13.

The set prints 174 creatures; W1G1 (morph) and W1G2 (face-down) write in
`test_ons_creatures.py`, every later group here, so neither file reaches the
2,600-line cap mid-wave.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: cycling triggers on creatures, and the cycling creatures --------
#
# Krosan Tusker's "When you cycle this card" is the cycled card's own trigger
# (CR 702.29c), asked of the card in the graveyard; Fleeting Aven's "Whenever
# a player cycles a card" is a permanent watching the table. Both announced
# where the cycling ability's discard is paid
# (`CardActivationMixin._announce_cycle`).
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=()):
    """Alice (seat 0, active) holding *hand* over *library* (top first) and
    five Plains; Bob holding *opponent_hand*."""
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand],
        library=[ons[name] for name in library] + [filler] * 5,
    )
    bob = PlayerState(
        name="Bob", hand=[ons[name] for name in opponent_hand],
        library=[filler] * 5,
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g3_krosan_tusker_cycled_searches_before_it_draws(set_pool):
    """"When you cycle this card, you may search your library for a basic land
    card, reveal that card, put it into your hand, then shuffle. (Do this
    before you draw.)" The library's top card is Wellwisher, a creature; the
    search takes the Forest from under it, and only then is a card drawn."""
    game, alice, _bob = _w1g3_table(
        set_pool, "Krosan Tusker", library=("Wellwisher", "Forest"),
    )
    game.enforce_mana_costs = True
    alice.mana_pool.update({"C": 2, "G": 1})

    assert game.activate_from_hand(0, "Krosan Tusker").supported
    assert not any(alice.mana_pool.values())
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == ["Forest"], "searched, not yet drawn"
    assert len(alice.library) == 6
    assert any("revealed Forest" in line for line in game.log)
    resolve_stack(game)
    assert len(alice.hand) == 2 and len(alice.library) == 5
    assert [c.name for c in alice.graveyard] == ["Krosan Tusker"]


def test_w1g3_krosan_tusker_is_supported_and_cycles_only_from_hand(set_pool):
    """The creature compiles now that its cycle trigger does; on the
    battlefield it is a 6/5 with no cycling to reach (CR 702.29b / 113.6j),
    and another card's cycle is not its own."""
    tusker = set_pool("ONS")["Krosan Tusker"]
    program = compile_card_oracle(tusker)
    assert program.supported, program.reason
    assert usable_activated_abilities(program) == []

    game, alice, _bob = _w1g3_table(set_pool, "Lay Waste")
    beast = _w1g3_put(game, 0, tusker)
    assert (beast.effective_power, beast.effective_toughness) == (6, 5)
    assert not game.activate_permanent_ability(0, "Krosan Tusker").supported
    assert game.activate_from_hand(0, "Lay Waste").supported
    assert [item.card.name for item in game.stack] == ["Lay Waste"]
    resolve_stack(game)


@pytest.mark.parametrize("cycler", [0, 1])
def test_w1g3_fleeting_aven_returns_to_hand_when_anyone_cycles(set_pool, cycler):
    """"Whenever a player cycles a card, return this creature to its owner's
    hand." — its controller's cycle or its opponent's, before the draw."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste", opponent_hand=["Swat"])
    aven = _w1g3_put(game, 0, set_pool("ONS")["Fleeting Aven"])
    name = "Lay Waste" if cycler == 0 else "Swat"
    cycling_player = game.players[cycler]

    assert game.activate_from_hand(cycler, name).supported
    assert game.stack[-1].card.name == "Fleeting Aven"
    assert game.resolve_top_of_stack()
    assert not game.is_on_battlefield(aven)
    assert "Fleeting Aven" in [c.name for c in alice.hand]
    assert "Plains" not in [c.name for c in cycling_player.hand], "not drawn yet"
    resolve_stack(game)
    assert "Plains" in [c.name for c in cycling_player.hand]


#: The Onslaught creatures that print cycling and nothing triggering on it,
#: with the mana their cycling cost takes from the pool.
_W1G3_PLAIN_CYCLING_CREATURES = {
    "Barkhide Mauler": {"C": 2},
    "Disciple of Grace": {"C": 2},
    "Disciple of Malice": {"C": 2},
    "Slipstream Eel": {"C": 1, "U": 1},
    "Undead Gladiator": {"C": 1, "B": 1},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_CREATURES))
def test_w1g3_a_cycling_creature_cycles_from_hand_and_never_from_play(set_pool, name):
    """From a hand: the printed cycling cost, the card to the graveyard, one
    card drawn. On the battlefield (CR 702.29b): the ability still exists, and
    nothing can activate it (CR 113.6j)."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    cycling = [
        a for a in usable_activated_abilities(program, zone=HAND)
        if a.source_line.endswith("Discard this card: Draw a card.")
    ]
    assert len(cycling) == 1
    assert cycling[0] not in usable_activated_abilities(program)

    game, alice, _bob = _w1g3_table(set_pool, name)
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_CREATURES[name])
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]

    game, alice, _bob = _w1g3_table(set_pool)
    _w1g3_put(game, 0, card)
    library = len(alice.library)
    game.activate_permanent_ability(0, name)
    resolve_stack(game)
    assert len(alice.library) == library and alice.hand == []
    assert alice.graveyard == []

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# --- W1G13: each player, and graveyards --------------------------------------
from engine import Game as _w1g13_Game
from engine.models import Permanent as _w1g13_Permanent
from engine.models import PlayerState as _w1g13_PlayerState

from tests.helpers import _mk_creature_card as _w1g13_creature
from tests.helpers import resolve_stack as _w1g13_resolve_stack


def _w1g13_table(set_pool, hands=None, *, interactive=(), seats=3):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g13_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[ons["Plains"]] * 5,
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g13_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g13_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_entrails_feaster_exiles_from_any_graveyard_it_names(set_pool):
    """"At the beginning of your upkeep, you may exile a creature card from a
    graveyard. If you do, put a +1/+1 counter on this creature." Any pile:
    the controller names Cara's graveyard and the creature card in it, never
    the land beside it, and the Feaster grows."""
    game = _w1g13_table(set_pool, interactive={0})
    alice, bob, cara = game.players
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    cara.graveyard.extend([set_pool("ONS")["Plains"], _w1g13_creature("Cara's Giant", 3, 3)])
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=True)
    pile = game.pending_choice_of("graveyard_pile_choice", 0)
    assert pile is not None and sorted(pile.data["seats"]) == [1, 2]
    assert game.confirm_graveyard_pile_choice(0, 2)
    assert game.confirm_graveyard_exile_pick(0, [1])
    _w1g13_resolve_stack(game)
    assert [c.name for c in cara.exile] == ["Cara's Giant"]
    assert [c.name for c in cara.graveyard] == ["Plains"]
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]
    assert (feaster.effective_power, feaster.effective_toughness) == (2, 2)
    assert not feaster.tapped


def test_w1g13_entrails_feaster_taps_when_it_does_not_exile(set_pool):
    """"If you don't, tap this creature." Declining taps it; and with no
    creature card in any graveyard there is nothing to exile, so the offer is
    never made and it taps all the same."""
    game = _w1g13_table(set_pool, interactive={0})
    bob = game.players[1]
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=False)
    _w1g13_resolve_stack(game)
    assert feaster.tapped and feaster.effective_power == 1
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]

    game = _w1g13_table(set_pool)
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    game.players[1].graveyard.append(set_pool("ONS")["Plains"])
    game.resolve_upkeep(0)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.pending_choices == []
    assert feaster.tapped and feaster.effective_power == 1


def test_w1g13_gigapede_returns_from_the_graveyard_for_a_discard(set_pool):
    """"At the beginning of your upkeep, if this card is in your graveyard,
    you may discard a card. If you do, return this card to your hand." The
    graveyard-trigger census's red on the ingest was the census, not the card:
    the discard pays, and the Gigapede is in the hand."""
    gigapede = set_pool("ONS")["Gigapede"]
    game = _w1g13_table(set_pool, {0: ["Plains"]}, interactive={0})
    alice = game.players[0]
    alice.graveyard.append(gigapede)
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Gigapede", accept=True)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0], to_library=False,
    )
    _w1g13_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Gigapede"]
    assert [c.name for c in alice.graveyard] == ["Plains"]


def _w1g13_quiet_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game.players[seat].battlefield.append(permanent)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_tempting_wurm_each_opponent_puts_cards_from_their_hand(set_pool):
    """"When this creature enters, each opponent may put any number of
    artifact, creature, enchantment, and/or land cards from their hand onto
    the battlefield." Each opponent in APNAP order, Bob before Cara, offered
    only the four printed types (never the instant), the Wurm's controller
    never asked; the chosen cards enter together under their owners, after
    the last choice, and an Aura enters attached to a creature already there
    (CR 303.4f) — its controller asked which."""
    ons = set_pool("ONS")
    giant = _w1g13_creature("Bob's Giant", 3, 3)
    game = _w1g13_table(
        set_pool,
        {0: ["Tempting Wurm"], 1: [giant, "Pacifism", "Shock", "Forest"],
         2: ["Plains"]},
        interactive={0, 1, 2},
    )
    alice, bob, cara = game.players
    alices = _w1g13_quiet_put(game, 0, _w1g13_creature("Alice's Bear", 2, 2))
    assert game.cast_from_hand(0, "Tempting Wurm").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 1),
    ]
    offered = game.live_choose_cards_in_hand(game.pending_choices[0])
    assert [bob.hand[i].name for i in offered] == ["Bob's Giant", "Pacifism", "Forest"]
    assert game.confirm_choose_cards_in_hand(1, offered)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 2),
    ]
    assert not any(perm.card is giant for perm in game.controlled_by(1)), (
        "nothing enters before the last opponent has chosen"
    )
    assert game.confirm_choose_cards_in_hand(2, [])
    host = game.pending_choice_of("permanent_choice", 1)
    assert host is not None, "Bob chooses what his Pacifism enchants"
    assert game.confirm_permanent_choice(1, alices.permanent_id)
    _w1g13_resolve_stack(game)
    assert sorted(perm.card.name for perm in game.controlled_by(1)) == [
        "Bob's Giant", "Forest", "Pacifism",
    ]
    assert [c.name for c in bob.hand] == ["Shock"]
    pacifism = next(p for p in game.controlled_by(1) if p.card is ons["Pacifism"])
    assert pacifism.metadata.get("attached_to") is alices
    assert [c.name for c in cara.hand] == ["Plains"]
    assert [perm.card.name for perm in game.controlled_by(2)] == []


def test_w1g13_tempting_wurm_an_aura_with_nothing_to_enchant_stays_in_hand(set_pool):
    """CR 303.4g: with no creature already on the battlefield besides the
    Wurm — here none at all once the Wurm is gone — an Aura stays in the hand.
    A seat nobody asks takes every card the sentence offers."""
    ons = set_pool("ONS")
    game = _w1g13_table(set_pool, {0: ["Tempting Wurm"], 1: ["Pacifism", "Forest"]})
    bob = game.players[1]
    assert game.queue_from_hand(0, "Tempting Wurm").supported
    game.resolve_top_of_stack()
    wurm = next(p for p in game.controlled_by(0) if p.card.name == "Tempting Wurm")
    game.remove_from_battlefield(wurm)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Forest"]
    assert [c.name for c in bob.hand] == ["Pacifism"]
    assert any("303.4g" in line for line in game.log)
    assert ons["Pacifism"] in bob.hand

# ==== end W1G13 ======================================================
