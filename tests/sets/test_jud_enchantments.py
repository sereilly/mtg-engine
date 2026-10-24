"""Judgment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# Auras: a pump with a rider on one line (Cagemail), a pump sized by a live
# count (Exoskeletal Armor), and an Aura that moves on to a host picked at
# random when its creature dies (Infectious Rage). Each Aura is cast through
# the real cast path onto its host and then played: the attack declaration,
# the P/T as graveyards change, the death and the return.

import random as _w1g9_random

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_table(set_pool):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G9Game(players=[
        _W1G9PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g9_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam, not sick."""
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_cast_aura(game, seat, card, host):
    """Cast *card* from *seat*'s hand onto *host* and resolve it."""
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand(seat, card.name, target_permanent_ids=[host.permanent_id])
    assert cast.supported, (cast.details, game.log[-4:])
    _w1g9_resolve_stack(game)
    game._settle()
    return next(p for p in game.all_permanents() if p.card is card)


def _w1g9_bolt(game, set_pool, seat, permanent):
    """Lightning Bolt *permanent* through the real path, the stack drained."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    cast = game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id]
    )
    assert cast.supported, game.log[-3:]
    for _ in range(3):
        _w1g9_resolve_stack(game)
        game._settle()


def _w1g9_attack_with(game, seat, permanent):
    """Declare *permanent* as *seat*'s only attacker; the (ok, why) pair."""
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    slot = next(
        i for i, perm in enumerate(game.players[seat].battlefield) if perm is permanent
    )
    return game.declare_attackers(seat, [slot], defending_player_index=1 - seat)


def test_w1g9_cagemail_pumps_its_host_and_forbids_the_attack(set_pool):
    """"Enchanted creature gets +2/+2 and can't attack." Both halves of the one
    line: a 4/4 Grizzly Bears whose attack the declaration refuses, beside an
    unenchanted Bears that may attack — and once the Aura is gone the host is a
    2/2 that may attack again (CR 611.3a: nothing to undo)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    caged = _w1g9_put(game, lea["Grizzly Bears"], 0)
    free = _w1g9_put(game, lea["Grizzly Bears"], 0)
    cagemail = _w1g9_cast_aura(game, 0, jud["Cagemail"], caged)

    assert cagemail.metadata.get("attached_to") is caged
    assert (caged.effective_power, caged.effective_toughness) == (4, 4)
    assert (free.effective_power, free.effective_toughness) == (2, 2)
    assert not game.can_attack(caged, 1)
    assert game.can_attack(free, 1)
    ok, _why = _w1g9_attack_with(game, 0, caged)
    assert not ok, "CR 508.1c: the restriction refuses the declaration itself"

    game._set_phase_and_step("precombat_main", "main")
    game.players[1].hand.append(lea["Disenchant"])
    cast = game.queue_from_hand(1, "Disenchant", target_permanent_ids=[cagemail.permanent_id])
    assert cast.supported, game.log[-3:]
    _w1g9_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(cagemail)
    assert (caged.effective_power, caged.effective_toughness) == (2, 2)
    assert game.can_attack(caged, 1)


def test_w1g9_exoskeletal_armor_recounts_creature_cards_in_every_graveyard(set_pool):
    """"+X/+X, where X is the number of creature cards in all graveyards." The
    ruling (2004-10-04): "The value of X changes as the number of creatures
    cards in graveyards changes." Both graveyards count, a land does not, and a
    creature card leaving a graveyard takes its +1/+1 with it."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    bears = _w1g9_put(game, lea["Grizzly Bears"], 0)
    _w1g9_cast_aura(game, 0, jud["Exoskeletal Armor"], bears)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    assert game.put_card_into_graveyard(0, lea["Hill Giant"])
    assert game.put_card_into_graveyard(1, lea["Craw Wurm"])
    assert game.put_card_into_graveyard(1, lea["Island"])
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)

    # A creature dying adds its card to the count the moment it lands.
    giant = _w1g9_put(game, lea["Hill Giant"], 1)
    _w1g9_bolt(game, set_pool, 0, giant)
    assert "Hill Giant" in [card.name for card in game.players[1].graveyard]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    # …and a card leaving a graveyard takes it away again.
    wurm = game.players[1].graveyard.index(lea["Craw Wurm"])
    game.players[1].graveyard.pop(wurm)
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def _w1g9_rage_board(set_pool, *others):
    """Seat 0's Grizzly Bears under Infectious Rage, *others* on seat 1."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    bears = _w1g9_put(game, lea["Grizzly Bears"], 0)
    placed = [_w1g9_put(game, card, 1) for card in others]
    rage = _w1g9_cast_aura(game, 0, jud["Infectious Rage"], bears)
    return game, bears, rage, placed


def _w1g9_rage_on_board(game):
    return [p for p in game.all_permanents() if p.card.name == "Infectious Rage"]


def test_w1g9_infectious_rage_returns_onto_a_creature_it_can_legally_enchant(set_pool):
    """The host dies and the Aura comes back attached to the one creature it
    can enchant. The rulings (2004-10-04): it is put there "without targeting
    it, so it can be placed on a creature with Shroud", and "you can't place
    this card on a permanent with protection from red" — so with a shroud
    creature and a protection-from-red creature on the board, every seed lands
    it on the shroud one. It comes back under its controller's control
    (CR 110.2a) and pumps its new host."""
    for seed in range(6):
        _w1g9_random.seed(seed)
        game, bears, _rage, (centaur, beasts) = _w1g9_rage_board(
            set_pool,
            set_pool("MIR")["Jolrael's Centaur"],   # 2/2 shroud
            set_pool("LEG")["Beasts of Bogardan"],  # protection from red
        )
        assert (bears.effective_power, bears.effective_toughness) == (4, 1)
        _w1g9_bolt(game, set_pool, 1, bears)

        assert not game.is_on_battlefield(bears)
        (rage,) = _w1g9_rage_on_board(game)
        assert rage.metadata.get("attached_to") is centaur
        assert game.controller_index_of(rage) == 0
        assert (centaur.effective_power, centaur.effective_toughness) == (4, 1)
        assert (beasts.effective_power, beasts.effective_toughness) == (3, 3)
        assert any("at random" in line for line in game.log)


def test_w1g9_infectious_rage_picks_at_random_and_a_seed_reproduces_it(set_pool):
    """"Choose a creature **at random**": nobody picks. With two legal hosts
    the pick moves with the seed — both are reached across a run of seeds,
    which a controller's choice would not do — and the same seed always makes
    the same pick (the module RNG the simulator seeds)."""
    lea = set_pool("LEA")

    def landing(seed):
        _w1g9_random.seed(seed)
        game, bears, _rage, (giant, wurm) = _w1g9_rage_board(
            set_pool, lea["Hill Giant"], lea["Craw Wurm"]
        )
        _w1g9_bolt(game, set_pool, 1, bears)
        (rage,) = _w1g9_rage_on_board(game)
        host = rage.metadata.get("attached_to")
        assert host in (giant, wurm)
        return host.card.name

    picks = [landing(seed) for seed in range(12)]
    assert set(picks) == {"Hill Giant", "Craw Wurm"}, picks
    assert [landing(seed) for seed in range(12)] == picks


def test_w1g9_infectious_rage_with_no_legal_host_stays_in_the_graveyard(set_pool):
    """CR 303.4g: "If an Aura is entering the battlefield and there is no legal
    object or player for it to enchant, the Aura remains in its current zone."
    The only other creature has protection from red, so the Aura stays in its
    owner's graveyard rather than entering attached to nothing."""
    game, bears, _rage, (beasts,) = _w1g9_rage_board(
        set_pool, set_pool("LEG")["Beasts of Bogardan"]
    )
    _w1g9_bolt(game, set_pool, 1, bears)

    assert _w1g9_rage_on_board(game) == []
    assert "Infectious Rage" in [card.name for card in game.players[0].graveyard]
    assert (beasts.effective_power, beasts.effective_toughness) == (3, 3)
    assert not any("returned to the battlefield" in line for line in game.log)

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
