"""Scourge sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# The Decrees' spell halves and cycle triggers (Decree of Pain, Decree of
# Annihilation, Decree of Justice) and the cycling sorceries on W1G2's drive
# list (Break Asunder, Claws of Wirewood, Unburden).
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import _mk_creature_card as _w1g2_creature
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, *, bob_hand=(), library=8):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(
        name="Alice", hand=list(hand), library=[lea["Plains"]] * library,
    )
    bob = _W1G2PlayerState(
        name="Bob", hand=list(bob_hand), library=[lea["Island"]] * library,
    )
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()


def test_w1g2_decree_of_pain_destroys_every_creature_unregenerated_and_draws(set_pool):
    """"Destroy all creatures. They can't be regenerated. Draw a card for each
    creature destroyed this way." Until this round the whole spell line was
    refused and the card was supported off its cycling alone — cast, it did
    nothing. A regeneration shield does not save the Abomination; an
    indestructible creature is not destroyed, so it is not counted."""
    scg, lea = set_pool("SCG"), set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool, [scg["Decree of Pain"]])
    _w1g2_put(game, 0, lea["Grizzly Bears"])
    _w1g2_put(game, 1, lea["Grizzly Bears"])
    abomination = _w1g2_put(game, 1, scg["Twisted Abomination"])
    survivor = _w1g2_put(game, 1, _w1g2_creature("Stone Idol", 2, 2, "Indestructible"))
    bob.mana_pool["B"] = 1
    assert game.activate_permanent_ability(
        1, "Twisted Abomination",
        permanent_index=game.battlefield_index_of(abomination), ability_index=0,
    ).supported
    _w1g2_drain(game)

    assert game.cast_from_hand(0, "Decree of Pain").supported
    _w1g2_drain(game)
    assert [p.card.name for p in game.all_permanents()] == ["Stone Idol"]
    assert game.is_on_battlefield(survivor)
    assert sorted(c.name for c in bob.graveyard) == ["Grizzly Bears", "Twisted Abomination"]
    assert [c.name for c in alice.hand] == ["Plains"] * 3, "three creatures died"
    assert [c.name for c in alice.graveyard] == ["Grizzly Bears", "Decree of Pain"]


def test_w1g2_decree_of_pain_with_no_creatures_draws_nothing(set_pool):
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Pain"]])
    assert game.cast_from_hand(0, "Decree of Pain").supported
    _w1g2_drain(game)
    assert alice.hand == [] and len(alice.library) == 8


def test_w1g2_decree_of_pain_cycled_shrinks_every_creature_before_the_draw(set_pool):
    """2022-12-08: "first the cycling ability goes on the stack, then the
    triggered ability goes on the stack on top of it. The triggered ability
    will resolve before you draw a card." -2/-2 to every creature, each side."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Pain"]])
    bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g2_put(game, 1, lea["Hill Giant"])

    assert game.activate_from_hand(0, "Decree of Pain").supported
    assert [i.ability_text.startswith("When you cycle") for i in game.stack] == [False, True]
    assert game.resolve_top_of_stack()
    assert alice.hand == [], "the trigger resolves before the draw"
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    _w1g2_drain(game)
    assert not game.is_on_battlefield(bears)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_annihilation_exiles_three_zones_and_spares_enchantments(set_pool):
    """"Exile all artifacts, creatures, and lands from the battlefield, all
    cards from all graveyards, and all cards from all hands." One sentence,
    three zones — refused whole until this round, and the card supported off
    its cycling. An enchantment stays; the Decree itself is on the stack while
    it resolves, so it is the one card in a graveyard afterwards."""
    scg, lea = set_pool("SCG"), set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [scg["Decree of Annihilation"], lea["Plains"]],
        bob_hand=[lea["Island"], lea["Lightning Bolt"]],
    )
    for card in (lea["Plains"], lea["Sol Ring"], lea["Grizzly Bears"]):
        _w1g2_put(game, 0, card)
    _w1g2_put(game, 1, lea["Island"])
    moon = _w1g2_put(game, 1, lea["Bad Moon"])
    alice.graveyard.append(lea["Lightning Bolt"])
    bob.graveyard.append(lea["Counterspell"])

    assert game.cast_from_hand(0, "Decree of Annihilation").supported
    _w1g2_drain(game)
    assert [p for p in game.all_permanents()] == [moon]
    assert alice.hand == [] and bob.hand == []
    assert [c.name for c in alice.graveyard] == ["Decree of Annihilation"]
    assert bob.graveyard == []
    assert sorted(c.name for c in alice.exile) == [
        "Grizzly Bears", "Lightning Bolt", "Plains", "Plains", "Sol Ring",
    ]
    assert sorted(c.name for c in bob.exile) == [
        "Counterspell", "Island", "Island", "Lightning Bolt",
    ]


def test_w1g2_decree_of_annihilation_cycled_destroys_all_lands(set_pool):
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Annihilation"]])
    _w1g2_put(game, 0, lea["Plains"])
    _w1g2_put(game, 1, lea["Island"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.activate_from_hand(0, "Decree of Annihilation").supported
    _w1g2_drain(game)
    assert [p for p in game.all_permanents()] == [bears]
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_justice_cast_makes_x_angels(set_pool):
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Justice"]])
    assert game.cast_from_hand(0, "Decree of Justice", x_value=2).supported
    _w1g2_drain(game)
    angels = [p for p in game.controlled_by(0)]
    assert [p.card.name for p in angels] == ["Angel Token"] * 2
    assert all(p.has_keyword("flying") for p in angels)
    assert all((p.effective_power, p.effective_toughness) == (4, 4) for p in angels)


def test_w1g2_decree_of_justice_cycled_pays_x_for_soldiers(set_pool):
    """"When you cycle this card, you may pay {X}. If you do, create X 1/1
    white Soldier creature tokens." The X is chosen as the trigger resolves,
    and paid from the lands left after the cycling cost."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Justice"]])
    game.enforce_mana_costs = True
    alice.mana_pool.update({"W": 1, "C": 2})
    for _ in range(3):
        _w1g2_put(game, 0, lea["Plains"])

    assert game.activate_from_hand(0, "Decree of Justice").supported
    _w1g2_drain(game)
    soldiers = [p for p in game.controlled_by(0) if p.card.name == "Soldier Token"]
    assert len(soldiers) == 3
    assert all((p.effective_power, p.effective_toughness) == (1, 1) for p in soldiers)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_break_asunder_destroys_an_artifact_or_enchantment(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Break Asunder"]])
    ring = _w1g2_put(game, 1, lea["Sol Ring"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert not game.cast_from_hand(
        0, "Break Asunder", target_permanent_ids=[bears.permanent_id],
    ).supported, "a creature is not an artifact or enchantment"
    assert game.cast_from_hand(
        0, "Break Asunder", target_permanent_ids=[ring.permanent_id],
    ).supported
    _w1g2_drain(game)
    assert [c.name for c in bob.graveyard] == ["Sol Ring"]


def test_w1g2_claws_of_wirewood_hits_flyers_and_players(set_pool):
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Claws of Wirewood"]])
    angel = _w1g2_put(game, 1, lea["Serra Angel"])
    birds = _w1g2_put(game, 0, lea["Birds of Paradise"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Claws of Wirewood").supported
    _w1g2_drain(game)
    assert (alice.life, bob.life) == (17, 17)
    assert not game.is_on_battlefield(birds)
    assert game.is_on_battlefield(angel) and angel.damage_marked == 3
    assert game.is_on_battlefield(bears) and bears.damage_marked == 0


def test_w1g2_unburden_makes_its_target_discard_two(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Unburden"]],
        bob_hand=[lea["Island"], lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    assert game.cast_from_hand(0, "Unburden", target_player_index=1).supported
    _w1g2_drain(game)
    assert len(bob.hand) == 1 and len(bob.graveyard) == 2


def test_w1g2_the_cycling_sorceries_cycle(set_pool):
    for name in ("Break Asunder", "Claws of Wirewood", "Unburden", "Decree of Justice"):
        game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")[name]])
        assert game.activate_from_hand(0, name).supported, name
        _w1g2_drain(game)
        assert [c.name for c in alice.hand] == ["Plains"], name
        assert [c.name for c in alice.graveyard] == [name], name

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

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
