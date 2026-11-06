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
#
# Storm (CR 702.40, ``engine/storm.py``) on the four storm sorceries, Mind's
# Desire's "until end of turn, you may play that card without paying its mana
# cost" (a cast *and* a land play out of exile), and the drive list's three
# sorceries.

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game
from engine import PlayerState as _w1g1_PlayerState
from engine.cast_permissions import permission_for as _w1g1_permission_for
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_card(set_pool, name):
    """A card by name, from Scourge first and Alpha for the fillers."""
    scg = set_pool("SCG")
    return scg[name] if name in scg else set_pool("LEA")[name]


def _w1g1_table(set_pool, hand=(), *, mine=(), theirs=(), library=None,
                interactive=()):
    card = lambda name: _w1g1_card(set_pool, name)  # noqa: E731
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
        ),
        _w1g1_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g1_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g1_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g1_cast_fillers(game, count):
    for _ in range(count):
        result = game.queue_from_hand(0, "Dark Ritual")
        assert result.supported, result.details
        _w1g1_resolve_stack(game)


def _w1g1_settle(game):
    """Drain the stack and every queued headless decision (a search)."""
    for _ in range(10):
        _w1g1_resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_dragonstorm_puts_a_dragon_onto_the_battlefield_per_copy(set_pool, before):
    library = ["Shivan Dragon"] * 5 + ["Craw Wurm", "Forest"] * 3
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Dragonstorm"], library=library,
    )
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Dragonstorm").supported
    _w1g1_settle(game)
    dragons = [
        permanent for permanent in game.controlled_by(game.players[0])
        if permanent.card.name == "Shivan Dragon"
    ]
    assert len(dragons) == before + 1
    assert not any(
        permanent.card.name == "Craw Wurm"
        for permanent in game.controlled_by(game.players[0])
    )


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_tendrils_of_agony_drains_two_per_copy(set_pool, before):
    game, _, _ = _w1g1_table(set_pool, ["Dark Ritual"] * before + ["Tendrils of Agony"])
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Tendrils of Agony", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    drained = 2 * (before + 1)
    assert [player.life for player in game.players] == [20 + drained, 20 - drained]


def test_w1g1_temporal_fissure_copies_each_bounce_another_permanent(set_pool):
    game, _, theirs = _w1g1_table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Temporal Fissure"],
        theirs=["Grizzly Bears", "Craw Wurm", "Forest"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 2)
    assert game.queue_from_hand(
        0, "Temporal Fissure", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    assert game.confirm_copy_spell_target(0, permanent_id=theirs[1].permanent_id)
    assert game.confirm_copy_spell_target(0, permanent_id=theirs[2].permanent_id)
    _w1g1_resolve_stack(game)
    assert list(game.controlled_by(game.players[1])) == []
    assert sorted(card.name for card in game.players[1].hand) == [
        "Craw Wurm", "Forest", "Grizzly Bears",
    ]


def test_w1g1_minds_desire_casts_the_exiled_card_for_free(set_pool):
    """A spell exiled by Mind's Desire is cast without paying its mana cost:
    Craw Wurm's {4}{G}{G} out of a board of six Islands, nothing tapped."""
    game, islands, _ = _w1g1_table(
        set_pool, ["Mind's Desire"], mine=["Island"] * 6, library=["Craw Wurm"] * 6,
    )
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    wurm = game.players[0].exile[-1]
    assert wurm.name == "Craw Wurm"
    assert _w1g1_permission_for(game, 0, wurm, "exile") is not None
    game.enforce_mana_costs = True
    result = game.queue_from_hand(0, "Craw Wurm", from_zone="exile")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(game.players[0])].count("Craw Wurm") == 1
    assert not any(island.tapped for island in islands)


def test_w1g1_minds_desire_plays_an_exiled_land_with_the_land_drop(set_pool):
    """"Play" covers a land (CR 305.1): the exiled Forest is played, and the
    land drop it uses is the turn's (CR 305.2) — the one in hand is refused."""
    game, _, _ = _w1g1_table(
        set_pool, ["Mind's Desire", "Swamp"], library=["Forest"] * 6,
    )
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    game.enforce_mana_costs = True
    assert game.cast_from_hand(0, "Forest", from_zone="exile").supported
    assert game.players[0].exile == []
    assert not game.cast_from_hand(0, "Swamp").supported


@_w1g1_pytest.mark.parametrize("before", [1, 2])
def test_w1g1_minds_desire_copies_each_exile_and_grant_their_own_card(set_pool, before):
    """Each storm copy shuffles, exiles the top card and grants its own play
    (the brief's "storm copies each exile and grant their own card")."""
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Mind's Desire"],
        library=["Grizzly Bears"] * 8,
    )
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    exiled = list(game.players[0].exile)
    assert len(exiled) == before + 1
    for _ in exiled:
        assert game.queue_from_hand(0, "Grizzly Bears", from_zone="exile").supported
        _w1g1_resolve_stack(game)
    assert game.players[0].exile == []
    assert [p.card.name for p in game.controlled_by(game.players[0])] == (
        ["Grizzly Bears"] * (before + 1)
    )


def test_w1g1_minds_desire_card_left_unplayed_stays_exiled(set_pool):
    """2004-10-04: "If the card is not played by end of turn, it remains
    exiled until end of game." The permission ends at cleanup (CR 514.2)."""
    game, _, _ = _w1g1_table(set_pool, ["Mind's Desire"], library=["Craw Wurm"] * 6)
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    wurm = game.players[0].exile[-1]
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert _w1g1_permission_for(game, 0, wurm, "exile") is None
    assert [card.name for card in game.players[0].exile] == ["Craw Wurm"]
    game.start_next_turn()
    game.start_next_turn()
    assert not game.queue_from_hand(0, "Craw Wurm", from_zone="exile").supported


# -- The drive list: Scourge sorceries supported on arrival -----------------


def test_w1g1_skulltap_sacrifices_the_named_creature_and_draws_two(set_pool):
    game, (bears, elves), _ = _w1g1_table(
        set_pool, ["Skulltap"], mine=["Grizzly Bears", "Llanowar Elves"],
    )
    result = game.queue_from_hand(0, "Skulltap", cost_permanent_ids=[elves.permanent_id])
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Grizzly Bears"]
    assert len(game.players[0].hand) == 2
    # No creature, no cast (2013-04-15: "you cannot cast it without
    # sacrificing a creature").
    game, _, _ = _w1g1_table(set_pool, ["Skulltap"])
    assert not game.queue_from_hand(0, "Skulltap").supported


def test_w1g1_misguided_rage_target_player_chooses_the_sacrifice(set_pool):
    game, _, theirs = _w1g1_table(
        set_pool, ["Misguided Rage"], theirs=["Grizzly Bears", "Forest"],
        interactive=[1],
    )
    assert game.queue_from_hand(0, "Misguided Rage", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    owed = game.pending_choices[0]
    assert owed.kind == "sacrifice" and owed.player_index == 1
    game.take_choice_default(owed)
    _w1g1_resolve_stack(game)
    assert len(list(game.controlled_by(game.players[1]))) == 1
    assert len(game.players[1].graveyard) == 1


def test_w1g1_goblin_war_strike_counts_goblins_you_control(set_pool):
    game, _, _ = _w1g1_table(
        set_pool, ["Goblin War Strike"],
        mine=["Goblin King", "Goblin Balloon Brigade", "Grizzly Bears"],
        theirs=["Goblin King"],
    )
    assert game.queue_from_hand(0, "Goblin War Strike", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 18

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
#
# "The greatest mana value among permanents you control" spent by a draw
# (Rush of Knowledge), a damage (Torrent of Fire) and a discard over "any
# number of target players" (Cabal Conditioning); and Final Punishment's "the
# damage already dealt to that player this turn", the turn's damage ledger
# joined on a player's seat.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.face_down import face_down_card as _w1g4_face_down
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from engine.shields import add_shield as _w1g4_add_shield
from engine.shields import make_numeric_pool as _w1g4_numeric_pool
from engine.tokens import make_token_card as _w1g4_token
from tests.helpers import _damage_dealt as _w1g4_damage
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_table(set_pool, hand, *, players=2, held=0):
    lea = set_pool("LEA")
    seats = [
        _W1G4PlayerState(
            name=f"P{seat + 1}", library=[lea["Island"]] * 12,
            hand=list(hand) if seat == 0 else [lea["Forest"]] * held,
        )
        for seat in range(players)
    ]
    game = _W1G4Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    _w1g4_resolve_stack(game)
    return permanent


def _w1g4_drain(game):
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)


def test_w1g4_rush_of_knowledge_draws_the_greatest_mana_value(set_pool):
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Rush of Knowledge"]])
    _w1g4_put(game, 0, lea["Grizzly Bears"])
    _w1g4_put(game, 0, lea["Hill Giant"])
    _w1g4_put(game, 1, lea["Shivan Dragon"])     # not "you control"
    assert game.cast_from_hand(0, "Rush of Knowledge").supported
    _w1g4_drain(game)
    assert len(game.players[0].hand) == 4, game.log
    assert len(game.players[1].hand) == 0


def test_w1g4_a_token_a_face_down_permanent_and_an_x_count_zero(set_pool):
    """CR 202.3: a token's mana cost is empty (CR 111.3), a face-down
    permanent's too (CR 708.2a), and an {X} in a permanent's cost is 0 —
    Rush of Knowledge's 2020-08-07 ruling ("If a permanent on the battlefield
    has {X} in its mana cost, X is considered to be 0"). Iceberg ({X}{U}{U})
    is 2 here however much was paid for it; the face-down Shivan Dragon is 0."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Rush of Knowledge"]])
    _w1g4_put(game, 0, set_pool("ICE")["Iceberg"])
    _w1g4_put(game, 0, _w1g4_face_down(lea["Shivan Dragon"]))
    _w1g4_put(game, 0, _w1g4_token("Soldier", 1, 1, "Token Creature — Soldier"))
    assert game.cast_from_hand(0, "Rush of Knowledge").supported
    _w1g4_drain(game)
    assert len(game.players[0].hand) == 2, game.log


def test_w1g4_rush_of_knowledge_with_nothing_controlled_draws_none(set_pool):
    game = _w1g4_table(set_pool, [set_pool("SCG")["Rush of Knowledge"]])
    assert game.cast_from_hand(0, "Rush of Knowledge").supported
    _w1g4_drain(game)
    assert game.players[0].hand == [] and len(game.players[0].library) == 12


@_w1g4_pytest.mark.parametrize("aim", ["player", "creature"])
def test_w1g4_torrent_of_fire_deals_the_greatest_mana_value_to_any_target(set_pool, aim):
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Torrent of Fire"]])
    _w1g4_put(game, 0, lea["Hill Giant"])        # 4
    _w1g4_put(game, 0, lea["Grizzly Bears"])
    wurm = _w1g4_put(game, 1, lea["Craw Wurm"])  # 6/4, and not "you control"
    announced = (
        {"target_player_index": 1} if aim == "player"
        else {"target_permanent_ids": [wurm.permanent_id]}
    )
    assert game.cast_from_hand(0, "Torrent of Fire", **announced).supported
    _w1g4_drain(game)
    game.check_state_based_actions()
    if aim == "player":
        assert game.players[1].life == 16, game.log
        assert game.is_on_battlefield(wurm)
    else:
        assert not game.is_on_battlefield(wurm), game.log
        assert game.players[1].life == 20


def test_w1g4_torrent_of_fire_offers_any_target(set_pool):
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Torrent of Fire"]])
    _w1g4_put(game, 1, lea["Craw Wurm"])
    spec = game.cast_target_spec(0, set_pool("SCG")["Torrent of Fire"])
    assert spec["requires_target"]
    assert spec["kind"] == "any"


@_w1g4_pytest.mark.parametrize("named", [[1], [0, 1], [1, 2], []])
def test_w1g4_cabal_conditioning_each_named_player_discards_the_casters_greatest(
    set_pool, named,
):
    """"Any number of target players each discard a number of cards equal to
    the greatest mana value among permanents you control." The caster's Hill
    Giant (4) sizes every named player's discard, the third seat's Shivan
    Dragon (6) not — "you" is the caster whichever seat the loop is on
    (CR 109.5). The caster may be named (CR 115.1a)."""
    lea = set_pool("LEA")
    game = _w1g4_table(
        set_pool, [set_pool("SCG")["Cabal Conditioning"]] + [lea["Forest"]] * 5,
        players=3, held=6,
    )
    _w1g4_put(game, 0, lea["Hill Giant"])
    _w1g4_put(game, 2, lea["Shivan Dragon"])
    assert game.cast_from_hand(
        0, "Cabal Conditioning", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    _w1g4_drain(game)
    assert [len(player.hand) for player in game.players] == [
        (5 - 4) if 0 in named else 5,
        *((6 - 4) if seat in named else 6 for seat in (1, 2)),
    ], game.log
    assert [len(player.graveyard) for player in game.players] == [
        1 + (4 if 0 in named else 0),
        *(4 if seat in named else 0 for seat in (1, 2)),
    ]


def test_w1g4_cabal_conditioning_asks_each_interactive_seat_in_turn(set_pool):
    """Two people named: each chooses their own discard, the first seat's
    prompt before the second's, and the spell waits for both (CR 608.2)."""
    lea = set_pool("LEA")
    game = _w1g4_table(
        set_pool, [set_pool("SCG")["Cabal Conditioning"]], players=3, held=3,
    )
    game.interactive_seats = {1, 2}
    _w1g4_put(game, 0, lea["Grizzly Bears"])     # 2
    assert game.queue_from_hand(
        0, "Cabal Conditioning", target_role_refs=[{"seat": 1}, {"seat": 2}],
    ).supported
    game.resolve_top_of_stack()
    first = game.pending_choice_of("discard", 1)
    assert first is not None and game.pending_choice_of("discard", 2) is None
    assert game.resolve_pending_choice("discard", 1, hand_indices=[0, 1], to_library=False)
    assert game.pending_choice_of("discard", 2) is not None, game.log
    assert game.resolve_pending_choice("discard", 2, hand_indices=[1, 2], to_library=False)
    _w1g4_resolve_stack(game)
    assert [len(player.hand) for player in game.players] == [0, 1, 1], game.log
    assert [card.name for card in game.players[0].graveyard] == ["Cabal Conditioning"]


def test_w1g4_final_punishment_takes_the_damage_dealt_to_that_player_this_turn(set_pool):
    """Five damage dealt to the target this turn is five life; the three dealt
    to the caster are not this player's history. (The ledger records each
    damage event, CR 120.3; ``_damage_dealt`` runs the event and leaves the
    life total, so the loss below is Final Punishment's alone.)"""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Final Punishment"]])
    giant = _w1g4_put(game, 0, lea["Hill Giant"])
    assert _w1g4_damage(game, game.players[1], 3, source=giant) == 3
    assert _w1g4_damage(game, game.players[1], 2, source=giant) == 2
    assert _w1g4_damage(game, game.players[0], 3, source=giant) == 3
    assert game.cast_from_hand(0, "Final Punishment", target_player_index=1).supported
    _w1g4_drain(game)
    assert [player.life for player in game.players] == [20, 15], game.log


def test_w1g4_final_punishment_counts_no_prevented_damage(set_pool):
    """The 2004-10-04 ruling: "Damage that is prevented does not count toward
    the total." Four damage at a player behind a 3-point shield (CR 615.7) is
    one damage dealt."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Final Punishment"]])
    giant = _w1g4_put(game, 0, lea["Hill Giant"])
    _w1g4_add_shield(game.players[1], _w1g4_numeric_pool(3))
    assert _w1g4_damage(game, game.players[1], 4, source=giant) == 1
    assert game.cast_from_hand(0, "Final Punishment", target_player_index=1).supported
    _w1g4_drain(game)
    assert game.players[1].life == 19, game.log


def test_w1g4_final_punishment_on_a_player_dealt_nothing_does_nothing(set_pool):
    game = _w1g4_table(set_pool, [set_pool("SCG")["Final Punishment"]])
    assert game.cast_from_hand(0, "Final Punishment", target_player_index=1).supported
    _w1g4_drain(game)
    assert [player.life for player in game.players] == [20, 20], game.log

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


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.
#
# Dimensional Breach: "Exile all permanents. For as long as any of those cards
# remain exiled, at the beginning of each player's upkeep, that player returns
# one of the exiled cards they own to the battlefield." Rulings (2004-10-04):
# each player chooses which of their own exiled cards; a returned creature has
# just come under its controller's control; a card that can't legally be
# returned can't be chosen.

import pytest as _w2g1_pytest

from engine import Game as _w2g1_Game
from engine import PlayerState as _w2g1_PlayerState
from engine.delayed_triggers import WHILE_EXILED_THIS_WAY as _w2g1_WHILE_EXILED
from engine.models import Permanent as _w2g1_Permanent
from engine.targeting import derive_cast_spec as _w2g1_derive_cast_spec
from tests.helpers import _nosick as _w2g1_nosick
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_card(set_pool, name):
    """A card by name, from Scourge first and Alpha for the fillers."""
    scg = set_pool("SCG")
    return scg[name] if name in scg else set_pool("LEA")[name]


def _w2g1_breached(set_pool, boards, *, seats=2, interactive=(), before=None):
    """Seat 0 casts Dimensional Breach over *boards* (card names per seat, all
    past summoning sickness) on turn 1, and it resolves. *interactive* seats
    are set after the cast, so the exile itself asks nobody anything;
    *before* is called with the game just before the cast."""
    card = lambda name: _w2g1_card(set_pool, name)  # noqa: E731
    players = [
        _w2g1_PlayerState(f"P{seat}", library=[card("Plains")] * 10)
        for seat in range(seats)
    ]
    players[0].hand.append(card("Dimensional Breach"))
    game = _w2g1_Game(players=players)
    game.enforce_mana_costs = False
    for seat, names in enumerate(boards):
        for name in names:
            game.players[seat].battlefield.append(
                _w2g1_nosick(_w2g1_Permanent(card=card(name)))
            )
    game._recompute_continuous_effects()
    if before is not None:
        before(game)
    game.start_turn(0)
    assert game.cast_from_hand(0, "Dimensional Breach").supported
    _w2g1_resolve_stack(game)
    game.interactive_seats = set(interactive)
    return game


def _w2g1_to_upkeep(game, seat):
    """Begin *seat*'s turn and stop in its upkeep, with what triggered there
    still on the stack (the step's priority window deferred)."""
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)
    game.resolve_upkeep(seat, defer_priority=True)


def _w2g1_breach_triggers(game):
    return [
        item for item in game.stack
        if getattr(item.card, "name", None) == "Dimensional Breach"
    ]


def _w2g1_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def _w2g1_exiled(game, seat):
    return sorted(card.name for card in game.players[seat].exile)


def test_w2g1_dimensional_breach_compiles_one_effect_and_names_no_target(set_pool):
    """The whole card is the spell's effect — the exile and the delayed
    ability behind it — and it targets nothing, so the picker offers a bare
    cast."""
    from engine.oracle import compile_card_oracle

    breach = set_pool("SCG")["Dimensional Breach"]
    program = compile_card_oracle(breach)
    assert program.supported
    (sequence,) = program.instructions
    exile, delay = sequence.payload["steps"]
    assert exile.kind == "exile_all_matching"
    assert delay.payload["event"] == "each_players_upkeep"
    assert delay.payload["duration"] == _w2g1_WHILE_EXILED
    assert delay.payload["once"] is False
    spec = _w2g1_derive_cast_spec(breach, program)
    assert spec is None or not spec.get("targets")


def test_w2g1_breach_exiles_every_permanent_to_its_owners_exile(set_pool):
    """"Exile all permanents": lands, Auras and tokens too, each card to its
    owner's exile (CR 400.3) — the Holy Strength on seat 0's Angel is seat 1's
    card — and a token to nowhere (CR 111.7)."""
    from engine.aura_attachment import attach_aura
    from engine.tokens import make_token_card

    def enchant_and_add_a_token(game):
        angel = next(p for p in game.controlled_by(0) if p.card.name == "Serra Angel")
        aura = _w2g1_Permanent(card=_w2g1_card(set_pool, "Holy Strength"))
        game.players[1].battlefield.append(aura)
        attach_aura(aura, angel)
        token = _w2g1_Permanent(card=make_token_card(
            "Soldier", 1, 1, "Token Creature — Soldier", colors=("W",),
        ))
        token.metadata["is_token"] = True
        game.players[0].battlefield.append(token)
        game._recompute_continuous_effects()

    game = _w2g1_breached(set_pool, [
        ["Plains", "Serra Angel"], ["Swamp", "Hill Giant"],
    ], before=enchant_and_add_a_token)
    assert list(game.all_permanents()) == []
    assert _w2g1_exiled(game, 0) == ["Plains", "Serra Angel"]
    assert _w2g1_exiled(game, 1) == ["Hill Giant", "Holy Strength", "Swamp"]
    # One exile record per card that went there, none for the token.
    assert len(game.exiled_records) == 5
    (entry,) = game.delayed_triggers
    assert entry.event == "each_players_upkeep"
    assert entry.duration == _w2g1_WHILE_EXILED


def test_w2g1_each_upkeep_its_player_returns_one_of_their_own_cards(set_pool):
    """Every player's upkeep, whoever cast it, returns one card **that player
    owns** under their control — never an opponent's — until none of the
    exiled cards remain, and then the ability is gone."""
    game = _w2g1_breached(set_pool, [
        ["Plains", "Serra Angel"], ["Swamp", "Hill Giant"],
    ])
    seen = []
    for seat in (1, 0, 1, 0):
        _w2g1_to_upkeep(game, seat)
        assert len(_w2g1_breach_triggers(game)) == 1
        _w2g1_resolve_stack(game)
        seen.append((seat, _w2g1_names(game, 0), _w2g1_names(game, 1)))
    # The biggest permanent first (the default), each seat its own.
    assert seen == [
        (1, [], ["Hill Giant"]),
        (0, ["Serra Angel"], ["Hill Giant"]),
        (1, ["Serra Angel"], ["Hill Giant", "Swamp"]),
        (0, ["Plains", "Serra Angel"], ["Hill Giant", "Swamp"]),
    ]
    assert game.players[0].exile == [] and game.players[1].exile == []
    # The last card back ends the ability (CR 603.7b, 611.2b): the next upkeep
    # triggers nothing.
    assert game.delayed_triggers == []
    assert any("none of the exiled cards remain exiled" in line for line in game.log)
    _w2g1_to_upkeep(game, 1)
    assert _w2g1_breach_triggers(game) == []


def test_w2g1_a_returned_creature_has_just_come_under_its_controllers_control(set_pool):
    """2004-10-04: "Remember that the returned creature just came under your
    control, so it can't attack until you start a turn with it under your
    control." Returned in its own controller's upkeep, it is summoning sick
    for that whole turn (CR 302.6) and fit to attack on the next."""
    game = _w2g1_breached(set_pool, [["Grizzly Bears"], []])
    _w2g1_to_upkeep(game, 0)
    _w2g1_resolve_stack(game)
    (bears,) = game.controlled_by(0)
    assert bears.card.name == "Grizzly Bears"
    assert game._is_summoning_sick(bears)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [game.battlefield_index_of(bears)], defending_player_index=1,
    )
    assert not ok
    game.start_next_turn()
    game.start_next_turn()
    assert game.active_player_index == 0
    assert not game._is_summoning_sick(bears)


def test_w2g1_a_card_that_leaves_exile_another_way_stops_counting(set_pool):
    """A card taken out of exile by anything else is gone from the pile, and
    the same card exiled again is a new object (CR 400.7, 406.7) that is not
    "one of those cards": seat 1 is offered nothing and it stays in exile."""
    game = _w2g1_breached(set_pool, [["Plains"], ["Hill Giant"]])
    giant = game.players[1].exile[0]
    assert game.take_card_from_exile(game.players[1], giant)
    game.players[1].exile.append(giant)
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert _w2g1_names(game, 1) == []
    assert _w2g1_exiled(game, 1) == ["Hill Giant"]
    assert any("P1 has no exiled card to return" in line for line in game.log)
    # Seat 0's Plains still counts, so the ability lasts.
    assert len(game.delayed_triggers) == 1


def test_w2g1_the_ability_ends_the_moment_its_last_card_leaves_exile(set_pool):
    """The duration is a state, ended where it stops holding: the last of the
    cards leaving exile by another route ends the ability on the spot, not at
    the next upkeep."""
    game = _w2g1_breached(set_pool, [["Plains"], []])
    assert len(game.delayed_triggers) == 1
    assert game.take_card_from_exile(game.players[0], game.players[0].exile[0])
    assert game.delayed_triggers == []
    _w2g1_to_upkeep(game, 1)
    assert _w2g1_breach_triggers(game) == []


def test_w2g1_a_breach_that_exiles_no_card_creates_no_ability(set_pool):
    """CR 611.2b: "If the 'for as long as' duration never starts, the effect
    does nothing." An empty battlefield exiles nothing, so nothing waits."""
    game = _w2g1_breached(set_pool, [[], []])
    assert game.delayed_triggers == []
    assert any("exiled no cards" in line for line in game.log)


def test_w2g1_an_interactive_seat_chooses_which_of_its_cards(set_pool):
    """Each player chooses which one (2004-10-04). The prompt offers the
    seat's own exiled cards only — not seat 0's — refuses an answer outside
    that list, and returns the one chosen."""
    game = _w2g1_breached(
        set_pool, [["Serra Angel"], ["Swamp", "Hill Giant", "Grizzly Bears"]],
        interactive={1},
    )
    _w2g1_to_upkeep(game, 1)
    # The ability runs and stops to ask: it stays on the stack, held, until
    # the seat answers (CR 608.2, 117.3b).
    game.resolve_top_of_stack(pause_for_choices=True)
    assert len(_w2g1_breach_triggers(game)) == 1
    choice = game.pending_choice_of("exiled_card_return", 1)
    assert choice is not None
    records = choice.data["_records"]
    offered = sorted(
        records[i].card.name for i in game.live_exiled_card_return_choices(choice)
    )
    assert offered == ["Grizzly Bears", "Hill Giant", "Swamp"]
    angel = next(i for i, r in enumerate(records) if r.card.name == "Serra Angel")
    assert not game.confirm_exiled_card_return(1, angel)
    swamp = next(i for i, r in enumerate(records) if r.card.name == "Swamp")
    assert game.confirm_exiled_card_return(1, swamp)
    assert game.stack == [] and game.pending_choices == []
    assert _w2g1_names(game, 1) == ["Swamp"]
    assert _w2g1_exiled(game, 1) == ["Grizzly Bears", "Hill Giant"]


def test_w2g1_a_seat_with_nothing_of_its_own_exiled_is_asked_nothing(set_pool):
    """The ability triggers at every upkeep while any card remains exiled, and
    resolves for a seat that owns none of them by doing nothing — no prompt,
    even for a person."""
    game = _w2g1_breached(set_pool, [["Grizzly Bears", "Plains"], []], interactive={1})
    _w2g1_to_upkeep(game, 1)
    assert len(_w2g1_breach_triggers(game)) == 1
    assert game.resolve_top_of_stack(pause_for_choices=True) is True
    assert game.pending_choices == []
    assert _w2g1_exiled(game, 0) == ["Grizzly Bears", "Plains"]
    assert any("P1 has no exiled card to return" in line for line in game.log)


def test_w2g1_an_aura_chooses_its_host_as_it_returns(set_pool):
    """CR 303.4f: an Aura put onto the battlefield by an effect that names no
    host is attached to what its controller chooses as it enters — here a
    person with two creatures to choose from, who is asked."""
    game = _w2g1_breached(
        set_pool, [["Grizzly Bears", "Hill Giant"], ["Holy Strength"]],
        interactive={1},
    )
    for _ in range(2):
        _w2g1_to_upkeep(game, 0)
        _w2g1_resolve_stack(game)
    assert _w2g1_names(game, 0) == ["Grizzly Bears", "Hill Giant"]
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    _w2g1_to_upkeep(game, 1)
    # The ability runs and stops to ask: it stays on the stack, held, until
    # the seat answers (CR 608.2, 117.3b).
    game.resolve_top_of_stack(pause_for_choices=True)
    assert len(_w2g1_breach_triggers(game)) == 1
    host = game.pending_choice_of("permanent_choice", 1)
    assert host is not None
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w2g1_resolve_stack(game)
    (pacifism,) = game.controlled_by(1)
    assert pacifism.card.name == "Holy Strength"
    assert pacifism.metadata.get("attached_to") is bears
    # …and it works: +1/+2 on the Bears, which seat 1 chose over the Giant.
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)


def test_w2g1_an_aura_with_nothing_to_enchant_cannot_be_chosen(set_pool):
    """2004-10-04: "You can't pick a card that can't legally be returned to
    the battlefield." With no creature on the battlefield Holy Strength is not
    offered — the Swamp comes back — and with only Holy Strength left nothing
    does, while the ability waits for it."""
    game = _w2g1_breached(set_pool, [[], ["Holy Strength", "Swamp"]], interactive={1})
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert game.pending_choices == []
    assert _w2g1_names(game, 1) == ["Swamp"]
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert _w2g1_names(game, 1) == ["Swamp"]
    assert _w2g1_exiled(game, 1) == ["Holy Strength"]
    assert len(game.delayed_triggers) == 1


def test_w2g1_four_seats_each_return_their_own_at_their_own_upkeep(set_pool):
    """Three opponents and the caster: each upkeep belongs to one player, and
    "that player" is whoever's upkeep it is — not the controller, and not the
    seat across the table."""
    boards = [["Plains"], ["Swamp"], ["Island"], ["Forest"]]
    game = _w2g1_breached(set_pool, boards, seats=4)
    back: set[int] = set()
    for seat in (1, 2, 3, 0):
        _w2g1_to_upkeep(game, seat)
        (trigger,) = _w2g1_breach_triggers(game)
        assert trigger.about_player_index == seat
        _w2g1_resolve_stack(game)
        back.add(seat)
        assert [_w2g1_names(game, other) for other in range(4)] == [
            boards[other] if other in back else [] for other in range(4)
        ]
    assert game.delayed_triggers == []


def test_w2g1_the_upkeep_trigger_can_be_stifled_and_the_ability_lasts(set_pool):
    """The upkeep trigger is a triggered ability on the stack (CR 603.7), so
    Stifle counters it: that upkeep returns nothing — but the delayed ability
    itself is not on the stack and keeps waiting, so the next upkeep does."""
    game = _w2g1_breached(set_pool, [["Plains"], ["Hill Giant"]])
    game.players[0].hand.append(set_pool("SCG")["Stifle"])
    _w2g1_to_upkeep(game, 1)
    (trigger,) = _w2g1_breach_triggers(game)
    index = next(i for i, item in enumerate(game.stack) if item is trigger)
    assert game.queue_from_hand(0, "Stifle", target_stack_index=index).supported
    _w2g1_resolve_stack(game)
    assert any("Stifle countered Dimensional Breach" in line for line in game.log)
    assert _w2g1_names(game, 1) == []
    assert len(game.delayed_triggers) == 1
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert _w2g1_names(game, 1) == ["Hill Giant"]


def test_w2g1_a_card_gone_from_exile_in_response_is_not_returned(set_pool):
    """The pile is read as the ability resolves (CR 603.7c, 608.2b): the card
    seat 1 would have taken leaves exile with the trigger on the stack, and
    the other one comes back instead."""
    game = _w2g1_breached(set_pool, [[], ["Swamp", "Hill Giant"]])
    _w2g1_to_upkeep(game, 1)
    assert len(_w2g1_breach_triggers(game)) == 1
    giant = next(c for c in game.players[1].exile if c.name == "Hill Giant")
    assert game.take_card_from_exile(game.players[1], giant)
    game.players[1].graveyard.append(giant)
    _w2g1_resolve_stack(game)
    assert _w2g1_names(game, 1) == ["Swamp"]
    assert game.delayed_triggers == []


def test_w2g1_a_swept_creatures_own_upkeep_trigger_does_not_fire_from_exile(set_pool):
    """The cards wait in the exile register, and a register card's upkeep
    trigger fires only if it functions from exile (CR 113.6k). Juzám Djinn's
    "deals 1 damage to you" is a battlefield ability: exiled by the Breach, it
    deals nothing at its owner's upkeep — and does once it is back."""
    card = lambda name: _w2g1_card(set_pool, name)  # noqa: E731
    players = [
        _w2g1_PlayerState(
            "P0", hand=[card("Dimensional Breach")], library=[card("Plains")] * 10,
        ),
        _w2g1_PlayerState("P1", library=[card("Plains")] * 10),
    ]
    game = _w2g1_Game(players=players)
    game.enforce_mana_costs = False
    for name in ("Swamp", "Plains"):
        game.players[1].battlefield.append(_w2g1_nosick(_w2g1_Permanent(card=card(name))))
    game.players[1].battlefield.append(
        _w2g1_nosick(_w2g1_Permanent(card=set_pool("ARN")["Juzám Djinn"]))
    )
    game._recompute_continuous_effects()
    game.start_turn(0)
    assert game.cast_from_hand(0, "Dimensional Breach").supported
    _w2g1_resolve_stack(game)
    # Seat 1's first upkeep with the Djinn still exiled: it deals nothing
    # (the Djinn is the most valuable card, so it is the one that comes back).
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w2g1_names(game, 1) == ["Juzám Djinn"]
    # Back on the battlefield its own trigger works again.
    _w2g1_to_upkeep(game, 1)
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 19


@_w2g1_pytest.mark.full
def test_w2g1_the_seeded_games_cast_the_breach_and_hand_cards_back(set_pool):
    """The AI simulator over Scourge with Dimensional Breach pinned: it is
    cast, the upkeeps after it hand cards back to their owners, and the
    ability ends once the last one is home (floors, never counts)."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        manifest_set_path("SCG", include_measured=True), games=4, seed=7,
        max_turns=18, required_cards=["Dimensional Breach"],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    assert not report.issues
    lines = report.log_lines
    assert any("cast Dimensional Breach" in line for line in lines)
    assert any("exiled" in line and "Dimensional Breach" in line for line in lines)
    assert any(
        "returned" in line and "(Dimensional Breach)" in line for line in lines
    )
    assert any("none of the exiled cards remain exiled" in line for line in lines)

# ==== end W2G1 ======================================================


# ==== W2G2 ==========================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ======================================================


# ==== W2G3 ==========================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ======================================================


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ======================================================


# ==== W2G5 ==========================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ======================================================
