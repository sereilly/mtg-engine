"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: tribal statics and counts ---------------------------------------
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine.models import Permanent as _W1G5Permanent
from engine.models import PlayerState as _W1G5PlayerState
from engine.oracle import compile_card_oracle as _w1g5_compile

from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, *hand, opponent_hand=(), interactive=()):
    """Alice (seat 0, active) holding *hand*, Bob holding *opponent_hand*;
    both over five Swamps, mana costs unenforced."""
    lgn = set_pool("LGN")
    ons = set_pool("ONS")

    def card(name):
        return lgn[name] if name in lgn else ons[name]

    filler = ons["Swamp"]
    alice = _W1G5PlayerState(
        name="Alice", hand=[card(name) for name in hand], library=[filler] * 5,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=[card(name) for name in opponent_hand],
        library=[filler] * 5,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, alice, bob, card


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


@_w1g5_pytest.mark.parametrize("interactive", [False, True])
def test_w1g5_gempalm_polluter_drains_by_the_zombies_on_the_whole_battlefield(
    set_pool, interactive,
):
    """"When you cycle this card, you may have target player lose life equal
    to the number of Zombies on the battlefield." Zombies on both sides count
    (two here: one each), an Elf does not, and the count is taken as the
    trigger resolves — after a third Zombie arrived in response. An
    interactive Alice names herself; the default seat names Bob."""
    game, alice, bob, card = _w1g5_table(
        set_pool, "Gempalm Polluter", interactive={0} if interactive else (),
    )
    _w1g5_put(game, 0, card("Severed Legion"))
    _w1g5_put(game, 1, card("Severed Legion"))
    _w1g5_put(game, 1, card("Wellwisher"))
    assert _w1g5_compile(card("Gempalm Polluter")).supported

    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    if interactive:
        assert game.pending_choice_of("trigger_target", 0) is not None
        assert game.confirm_trigger_target(0, seat=0)
    loser = alice if interactive else bob
    # A third Zombie before the trigger resolves: the count is the board's at
    # resolution, not at the cycle.
    _w1g5_put(game, 1, card("Gempalm Polluter"))
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, "the 'you may' is asked"
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert loser.life == 17
    assert (alice if loser is bob else bob).life == 20
    assert any(f"{loser.name} lost 3 life" in line for line in game.log)


def test_w1g5_gempalm_polluter_declined_loses_nothing(set_pool):
    """The "you may" declined: nobody loses life, and the cycling still draws."""
    game, alice, bob, card = _w1g5_table(set_pool, "Gempalm Polluter")
    _w1g5_put(game, 1, card("Severed Legion"))
    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, False, None)
    game.auto_resolve_pending_choices()
    assert (alice.life, bob.life) == (20, 20)
    assert len(alice.hand) == 1


def test_w1g5_noxious_ghoul_shrinks_every_non_zombie_when_a_zombie_enters(
    set_pool,
):
    """"Whenever this creature or another Zombie enters, all non-Zombie
    creatures get -1/-1 until end of turn." Cast, the Ghoul's own entry
    shrinks both sides' non-Zombies (a 1/1 Elf dies) and no Zombie; Bob's
    Zombie entering afterwards fires it again; a non-Zombie entering does
    not; and the shrink ends at cleanup."""
    game, alice, bob, card = _w1g5_table(
        set_pool, "Noxious Ghoul", opponent_hand=("Severed Legion",),
    )
    elf = _w1g5_put(game, 1, card("Birchlore Rangers"))   # 1/1 Elf
    bear = _w1g5_put(game, 0, card("Wellwisher"))          # 1/1 Elf
    hulk = _w1g5_put(game, 1, card("Krosan Tusker"))       # 6/5 Beast
    legion = _w1g5_put(game, 0, card("Severed Legion"))    # 2/2 Zombie

    assert game.queue_from_hand(0, "Noxious Ghoul").supported
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    ghoul = next(p for p in game.controlled_by(0) if p.card.name == "Noxious Ghoul")
    assert not game.is_on_battlefield(elf) and not game.is_on_battlefield(bear)
    assert (hulk.effective_power, hulk.effective_toughness) == (5, 4)
    assert (legion.effective_power, legion.effective_toughness) == (2, 2)
    assert (ghoul.effective_power, ghoul.effective_toughness) == (3, 3)

    # Another Zombie — the opponent's — fires it a second time.
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Severed Legion").supported
    _w1g5_resolve_stack(game)
    assert (hulk.effective_power, hulk.effective_toughness) == (4, 3)
    assert (ghoul.effective_power, ghoul.effective_toughness) == (3, 3)

    # A non-Zombie entering does not.
    _w1g5_put(game, 1, card("Wellwisher"))
    _w1g5_resolve_stack(game)
    assert (hulk.effective_power, hulk.effective_toughness) == (4, 3)

    game.resolve_cleanup_step(1)
    assert (hulk.effective_power, hulk.effective_toughness) == (6, 5)


def _w1g5_slot(game, seat, permanent):
    return next(
        index for index, candidate in enumerate(game.players[seat].battlefield)
        if candidate is permanent
    )


def test_w1g5_frenetic_raptor_grounds_every_beast_as_a_blocker(set_pool):
    """"Beasts can't block." Every Beast on every battlefield — the Raptor
    itself, Alice's other Beast, and Bob's — and nothing else: Alice's Elf
    blocks as usual."""
    game, alice, bob, card = _w1g5_table(set_pool)
    raptor = _w1g5_put(game, 0, card("Frenetic Raptor"))
    tusker = _w1g5_put(game, 0, card("Krosan Tusker"))     # Boar Beast
    elf = _w1g5_put(game, 0, card("Birchlore Rangers"))
    attacker = _w1g5_put(game, 1, card("Wellwisher"))
    bobs_beast = _w1g5_put(game, 1, card("Krosan Tusker"))

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, attacker)], defending_player_index=0,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    for beast in (raptor, tusker):
        assert not game._can_block_attacker(beast, attacker)
    assert game._can_block_attacker(elf, attacker)
    assert not game._can_block_attacker(bobs_beast, attacker), "any controller"
    ok, _why = game.declare_blockers(
        0, {_w1g5_slot(game, 0, tusker): _w1g5_slot(game, 1, attacker)},
    )
    assert not ok, "the Beast's block is refused"
    ok, why = game.declare_blockers(
        0, {_w1g5_slot(game, 0, elf): _w1g5_slot(game, 1, attacker)},
    )
    assert ok, why

    # The Raptor gone, the Beasts block again (a static, CR 611.3a).
    game.remove_from_battlefield(raptor)
    assert game._can_block_attacker(tusker, attacker)


def test_w1g5_a_one_word_creature_type_subject_cannot_attack():
    """The attack twin of the Raptor's row: "Beasts can't attack." on an
    invented card grounds a Beast attacker and no other."""
    beast = _w1g5_mk_card("Test Beast", "Creature — Beast", power=2, toughness=2)
    elf = _w1g5_mk_card("Test Elf", "Creature — Elf", power=2, toughness=2)
    warden = _w1g5_mk_card(
        "Beast Warden", "Creature — Human", "Beasts can't attack.",
        power=1, toughness=1,
    )
    assert _w1g5_compile(warden).supported
    game = _W1G5Game(players=[_W1G5PlayerState(name="A"), _W1G5PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    attacker_beast = _w1g5_put(game, 0, beast)
    attacker_elf = _w1g5_put(game, 0, elf)
    _w1g5_put(game, 1, warden)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker_beast)], defending_player_index=1,
    )
    assert not ok
    ok, why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker_elf)], defending_player_index=1,
    )
    assert ok, why


def test_w1g5_berserk_murlodont_pumps_each_blocked_beast_by_its_blockers(
    set_pool,
):
    """"Whenever a Beast becomes blocked, it gets +1/+1 until end of turn for
    each creature blocking it." Alice attacks with a Beast blocked by two, the
    Murlodont (a Beast) blocked by one, and an Elf blocked by one: the Beast
    gets +2/+2, the Murlodont +1/+1, the Elf nothing — one trigger per
    blocked Beast (CR 509.3c), sized by its own blockers."""
    from tests.helpers import declare_attack

    game, alice, bob, card = _w1g5_table(set_pool)
    murlodont = _w1g5_put(game, 0, card("Berserk Murlodont"))   # 3/3
    tusker = _w1g5_put(game, 0, card("Krosan Tusker"))          # 6/5
    elf = _w1g5_put(game, 0, card("Birchlore Rangers"))         # 1/1
    walls = [_w1g5_put(game, 1, card("Severed Legion")) for _ in range(4)]

    def slot(perm):
        seat = 0 if perm in (murlodont, tusker, elf) else 1
        return _w1g5_slot(game, seat, perm)

    declare_attack(game, 0, blocks={
        slot(walls[0]): slot(tusker), slot(walls[1]): slot(tusker),
        slot(walls[2]): slot(murlodont), slot(walls[3]): slot(elf),
    })
    triggers = [item for item in game.stack if item.card.name == "Berserk Murlodont"]
    assert len(triggers) == 2, [item.ability_text for item in game.stack]
    _w1g5_resolve_stack(game)
    assert (tusker.effective_power, tusker.effective_toughness) == (8, 7)
    assert (murlodont.effective_power, murlodont.effective_toughness) == (4, 4)
    assert (elf.effective_power, elf.effective_toughness) == (1, 1)
    assert any("gives Krosan Tusker +2/+2" in line for line in game.log)


def test_w1g5_berserk_murlodont_watches_the_opponents_beasts_too(set_pool):
    """"A Beast" is any controller's: Bob's Beast, blocked by Alice's two
    creatures, is pumped by Alice's Murlodont."""
    from tests.helpers import declare_attack

    game, alice, bob, card = _w1g5_table(set_pool)
    _w1g5_put(game, 0, card("Berserk Murlodont"))
    blockers = [_w1g5_put(game, 0, card("Birchlore Rangers")) for _ in range(2)]
    for perm in game.controlled_by(0):
        perm.tapped = perm not in blockers
    beast = _w1g5_put(game, 1, card("Krosan Tusker"))
    declare_attack(game, 1, blocks={
        _w1g5_slot(game, 0, blockers[0]): _w1g5_slot(game, 1, beast),
        _w1g5_slot(game, 0, blockers[1]): _w1g5_slot(game, 1, beast),
    })
    _w1g5_resolve_stack(game)
    assert (beast.effective_power, beast.effective_toughness) == (8, 7)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
