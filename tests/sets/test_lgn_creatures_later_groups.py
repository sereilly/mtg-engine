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


def _w1g5_bears(game, seat):
    return [
        perm for perm in game.controlled_by(seat) if perm.card.name == "Bear Token"
    ]


def test_w1g5_caller_of_the_claw_counts_the_nontoken_creatures_that_died_yours(
    set_pool,
):
    """"When this creature enters, create a 2/2 green Bear creature token for
    each nontoken creature put into your graveyard from the battlefield this
    turn." Two of Alice's cards die; so do a token of hers (CR 111.7 puts it
    in the graveyard, but it is no card), Bob's creature (Bob's graveyard),
    and Alice's creature that Bob had stolen (Alice's graveyard, CR 400.3).
    The Caller enters: three Bears, each a 2/2 green Bear."""
    from engine.control import change_control

    game, alice, bob, card = _w1g5_table(set_pool, "Caller of the Claw")
    mine = [_w1g5_put(game, 0, card("Birchlore Rangers")) for _ in range(2)]
    token = _w1g5_put(game, 0, card("Wellwisher"))
    token.metadata["is_token"] = True
    bobs = _w1g5_put(game, 1, card("Wellwisher"))
    stolen = _w1g5_put(game, 0, card("Severed Legion"))
    change_control(stolen, 1, source=bobs)
    game._sync_control()
    assert game.controller_index_of(stolen) == 1
    for victim in (*mine, token, stolen, bobs):
        game.sacrifice_permanent(victim)
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 3
    assert alice.creatures_put_into_your_graveyard_this_turn == 4
    assert bob.nontoken_creatures_put_into_your_graveyard_this_turn == 1

    assert game.queue_from_hand(0, "Caller of the Claw").supported
    _w1g5_resolve_stack(game)
    bears = _w1g5_bears(game, 0)
    assert len(bears) == 3
    assert all(
        (bear.effective_power, bear.effective_toughness) == (2, 2)
        and bear.has_type("bear") and "G" in bear.effective_colors
        for bear in bears
    )


def test_w1g5_caller_of_the_claw_counts_this_turn_only(set_pool):
    """The tally is the turn's: a death last turn makes no Bear, and with no
    death this turn the Caller enters alone."""
    game, alice, bob, card = _w1g5_table(set_pool, "Caller of the Claw")
    game.sacrifice_permanent(_w1g5_put(game, 0, card("Birchlore Rangers")))
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 1
    game.start_next_turn()
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 0
    assert game.queue_from_hand(0, "Caller of the Claw").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_bears(game, 0) == []
    assert any(p.card.name == "Caller of the Claw" for p in game.controlled_by(0))


def _w1g5_entangle(game, card, target):
    """Alice's Whipgrass Entangler grants its toll to *target*."""
    result = game.activate_permanent_ability(
        0, "Whipgrass Entangler", target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)


def test_w1g5_whipgrass_entangler_taxes_the_attack_per_cleric(set_pool):
    """"{1}{W}: Until end of turn, target creature gains "This creature can't
    attack or block unless its controller pays {1} for each Cleric on the
    battlefield."" Two Clerics (the Entangler and Bob's own): Bob's Beast owes
    {2} to attack — refused with one land, paid with two. A third Cleric
    arriving before the declaration makes it {3}. Cleanup ends the grant."""
    game, alice, bob, card = _w1g5_table(set_pool)
    game.active_player_index = 1
    _w1g5_put(game, 0, card("Whipgrass Entangler"))
    _w1g5_put(game, 1, card("Daru Mender"))                # a Cleric
    beast = _w1g5_put(game, 1, card("Krosan Tusker"))
    land = _w1g5_put(game, 1, card("Plains"))
    _w1g5_entangle(game, card, beast)
    assert "for each Cleric on the battlefield" in beast.effective_card.oracle_text
    assert game._attack_mana_costs_of(beast, 0) == [{"generic": 2}]

    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, beast)], defending_player_index=0,
    )
    assert not ok and not beast.tapped and not land.tapped, "one land, {2} owed"

    _w1g5_put(game, 1, card("Plains"))
    _w1g5_put(game, 0, card("Daru Sanctifier"))             # a third Cleric
    assert game._attack_mana_costs_of(beast, 0) == [{"generic": 3}]
    _w1g5_put(game, 1, card("Plains"))
    ok, why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, beast)], defending_player_index=0,
    )
    assert ok, why
    assert any("paid {3} to declare attackers" in line for line in game.log)

    game.resolve_cleanup_step(1)
    assert game._attack_mana_costs_of(beast, 0) == []


def test_w1g5_whipgrass_entangler_taxes_the_block_too(set_pool):
    """The same grant's block half: Bob's creature owes {2} to block Alice's
    attacker — refused with no land, accepted and charged with two
    Plains. Its toll is the creature's alone: Bob's other creature blocks
    free."""
    game, alice, bob, card = _w1g5_table(set_pool)
    _w1g5_put(game, 0, card("Whipgrass Entangler")).tapped = True
    attacker = _w1g5_put(game, 0, card("Krosan Tusker"))
    _w1g5_put(game, 1, card("Daru Mender")).tapped = True    # Bob's Cleric
    taxed = _w1g5_put(game, 1, card("Wellwisher"))
    free = _w1g5_put(game, 1, card("Birchlore Rangers"))
    _w1g5_entangle(game, card, taxed)
    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker)], defending_player_index=1,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert game._block_mana_costs_of(taxed, attacker) == [{"generic": 2}]
    assert game._block_mana_costs_of(free, attacker) == []
    ok, _why = game.declare_blockers(
        1, {_w1g5_slot(game, 1, taxed): _w1g5_slot(game, 0, attacker)},
    )
    assert not ok, "no mana for the {2}"
    lands = [_w1g5_put(game, 1, card("Plains")) for _ in range(2)]
    ok, why = game.declare_blockers(
        1, {_w1g5_slot(game, 1, taxed): _w1g5_slot(game, 0, attacker)},
    )
    assert ok, why
    assert all(land.tapped for land in lands)


# --- W1G5: Mistform Ultimus, every creature type in every zone -------------
#
# "Mistform Ultimus is every creature type (even if this card isn't on the
# battlefield)." A characteristic-defining ability (CR 604.3; changeling's
# CR 702.73a), read off the card's own text by the one type parse both the
# off-battlefield answer and the layer seed share
# (`layer_bridge._printed_shape`).


def test_w1g5_mistform_ultimus_is_supported_and_shows_its_printed_line(set_pool):
    """The line is claimed, and the board shows "Legendary Creature —
    Illusion", not three hundred words."""
    from engine.layer_bridge import displayed_type_line

    ultimus = set_pool("LGN")["Mistform Ultimus"]
    program = _w1g5_compile(ultimus)
    assert program.supported, program.reason
    game, alice, bob, card = _w1g5_table(set_pool)
    permanent = _w1g5_put(game, 0, ultimus)
    assert displayed_type_line(permanent) == "Legendary Creature — Illusion"
    for word in ("illusion", "goblin", "zombie", "beast", "sliver", "cleric"):
        assert permanent.has_type(word), word
    assert not permanent.has_type("forest"), "a creature type, not a land type"


def test_w1g5_mistform_ultimus_is_every_type_in_the_library_and_graveyard(
    set_pool,
):
    """Off the battlefield (CR 604.3): Goblin Matron's "search your library
    for a Goblin card" finds it, Lord of the Undead's "target Zombie card from
    your graveyard" returns it, and Soulless One counts it among "Zombie cards
    in all graveyards"."""
    ultimus = set_pool("LGN")["Mistform Ultimus"]
    game, alice, bob, card = _w1g5_table(set_pool)
    alice.hand = [set_pool("USG")["Goblin Matron"]]
    alice.library = [ultimus] + alice.library
    assert game.queue_from_hand(0, "Goblin Matron").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Mistform Ultimus"]
    assert any("put Mistform Ultimus into hand" in line for line in game.log)

    game, alice, bob, card = _w1g5_table(set_pool)
    alice.graveyard = [ultimus]
    soulless = _w1g5_put(game, 0, set_pool("ONS")["Soulless One"])
    game._refresh_dynamic_creatures()
    assert (soulless.effective_power, soulless.effective_toughness) == (2, 2)
    _w1g5_put(game, 0, set_pool("PLS")["Lord of the Undead"])
    assert game.activate_permanent_ability(0, "Lord of the Undead").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Mistform Ultimus"]


def test_w1g5_mistform_ultimus_is_every_type_as_a_spell(set_pool):
    """On the stack: Rin and Seri's "Whenever you cast a Dog spell" and
    "…a Cat spell" both fire for the one cast."""
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    _w1g5_put(game, 0, set_pool("M21")["Rin and Seri, Inseparable"])
    assert game.queue_from_hand(0, "Mistform Ultimus").supported
    assert sorted(
        item.ability_text[:27] for item in game.stack if item.ability_text
    ) == ["Whenever you cast a Cat spe", "Whenever you cast a Dog spe"]
    _w1g5_resolve_stack(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert "Cat Token" in names and "Dog Token" in names


def test_w1g5_mistform_ultimus_in_hand_shares_every_creature_type(set_pool):
    """The hand reader amplify and "share a creature type" ask
    (`object_creature_types.creature_types`) answers every type for the card
    in hand — and a Conspiracy naming Goblin replaces them (CR 205.1a), so the
    card is then a Goblin and nothing else."""
    from engine.object_creature_types import creature_types

    ultimus = set_pool("LGN")["Mistform Ultimus"]
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    held = creature_types(game, ultimus, 0)
    assert {"beast", "bird", "soldier", "zombie", "dragon"} <= held
    conspiracy = _w1g5_put(game, 0, set_pool("MMQ")["Conspiracy"])
    game.auto_resolve_pending_choices()
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    assert creature_types(game, ultimus, 0) == frozenset({"goblin"})
    assert creature_types(game, ultimus, 1) >= {"zombie"}, "Bob's seat: no Conspiracy"


def test_w1g5_mistform_ultimus_loses_its_types_to_a_type_setting_effect(
    set_pool,
):
    """The card's rulings (2006-09-25): an effect that makes it another type
    replaces every creature type — Mistform Wakecaster's "Each creature you
    control becomes that type until end of turn" makes it an Advisor and
    nothing else, shown so — and an effect removing its abilities does not
    (layer 4 before layer 6): under Humility it is still a Goblin. Face down
    it has no types at all (CR 708.2)."""
    from engine.face_down import turn_face_down
    from engine.layer_bridge import displayed_type_line

    game, alice, bob, card = _w1g5_table(set_pool)
    ultimus = _w1g5_put(game, 0, card("Mistform Ultimus"))
    _w1g5_put(game, 0, card("Mistform Wakecaster"))
    assert game.activate_permanent_ability(
        0, "Mistform Wakecaster", ability_index=1,
    ).supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    chosen = next(
        word for word in ("advisor", "goblin", "zombie") if ultimus.has_type(word)
    )
    assert sum(ultimus.has_type(w) for w in ("advisor", "goblin", "zombie")) == 1
    assert not ultimus.has_type("illusion")
    assert displayed_type_line(ultimus).lower() == f"legendary creature — {chosen}"
    game.resolve_cleanup_step(0)
    assert ultimus.has_type("goblin") and ultimus.has_type("zombie")

    _w1g5_put(game, 1, set_pool("TMP")["Humility"])
    game._refresh_dynamic_creatures()
    assert ultimus.effective_card.oracle_text == ""
    assert ultimus.has_type("goblin") and ultimus.has_type("zombie")
    assert (ultimus.effective_power, ultimus.effective_toughness) == (1, 1)

    game, alice, bob, card = _w1g5_table(set_pool)
    hidden = _w1g5_put(game, 0, card("Mistform Ultimus"))
    assert turn_face_down(game, hidden)
    assert not hidden.has_type("goblin") and not hidden.has_type("illusion")


def test_w1g5_mistform_ultimus_answers_this_groups_tribal_cards(set_pool):
    """On the board it is a Zombie, a Beast and a Cleric: Noxious Ghoul fires
    as it enters and spares it; Frenetic Raptor grounds it; Gempalm
    Polluter and Whipgrass Entangler count it."""
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    _w1g5_put(game, 0, card("Noxious Ghoul"))
    _w1g5_resolve_stack(game)
    bystander = _w1g5_put(game, 1, card("Krosan Tusker"))
    assert game.queue_from_hand(0, "Mistform Ultimus").supported
    _w1g5_resolve_stack(game)
    ultimus = next(
        p for p in game.controlled_by(0) if p.card.name == "Mistform Ultimus"
    )
    assert (bystander.effective_power, bystander.effective_toughness) == (5, 4)
    assert (ultimus.effective_power, ultimus.effective_toughness) == (3, 3)

    _w1g5_put(game, 1, card("Frenetic Raptor"))
    attacker = _w1g5_put(game, 1, card("Wellwisher"))
    assert not game._can_block_attacker(ultimus, attacker)

    whip = _w1g5_put(game, 0, card("Whipgrass Entangler"))
    assert game.activate_permanent_ability(
        0, "Whipgrass Entangler", target_permanent_ids=[attacker.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game._attack_mana_costs_of(attacker, 0) == [{"generic": 2}], (
        "the Entangler and the Ultimus are the Clerics"
    )
    assert whip.has_type("cleric")


# --- W1G5's drive list: the tribal cards that compiled on arrival ----------


@_w1g5_pytest.mark.parametrize("with_ultimus", [False, True])
def test_w1g5_tribal_statics_and_counts_see_mistform_ultimus(
    set_pool, with_ultimus,
):
    """Cloudreach Cavalry ("As long as you control a Bird") and Skirk Outrider
    ("…a Beast") switch on with the Ultimus and not without; Wirewood
    Channeler adds a mana per Elf, Riptide Director draws per Wizard and
    Timberwatch Elf pumps per Elf on the battlefield (Bob's Ultimus counts)."""
    game, alice, bob, card = _w1g5_table(set_pool)
    cavalry = _w1g5_put(game, 0, card("Cloudreach Cavalry"))
    outrider = _w1g5_put(game, 0, card("Skirk Outrider"))
    _w1g5_put(game, 0, card("Wirewood Channeler"))
    _w1g5_put(game, 0, card("Riptide Director"))
    _w1g5_put(game, 0, card("Timberwatch Elf"))
    legion = _w1g5_put(game, 0, card("Severed Legion"))    # 2/2, no Beast
    if with_ultimus:
        _w1g5_put(game, 1, card("Mistform Ultimus"))
        _w1g5_put(game, 0, card("Mistform Ultimus"))
    game._refresh_dynamic_creatures()
    bonus = 2 if with_ultimus else 0
    assert (cavalry.effective_power, cavalry.effective_toughness) == (1 + bonus, 1 + bonus)
    assert game._has_keyword(cavalry, "flying") is with_ultimus
    assert (outrider.effective_power, outrider.effective_toughness) == (2 + bonus, 2 + bonus)
    assert game._has_keyword(outrider, "trample") is with_ultimus

    # The Channeler and Timberwatch Elf, and both Ultimuses where present.
    elves = 2 + (2 if with_ultimus else 0)
    assert game.activate_permanent_ability(0, "Wirewood Channeler").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert sum(alice.mana_pool.values()) == elves

    hand_before = len(alice.hand)
    assert game.activate_permanent_ability(0, "Riptide Director").supported
    _w1g5_resolve_stack(game)
    assert len(alice.hand) - hand_before == (2 if with_ultimus else 1)

    assert game.activate_permanent_ability(
        0, "Timberwatch Elf", target_permanent_ids=[legion.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert legion.effective_power == 2 + elves


@_w1g5_pytest.mark.parametrize("with_ultimus", [False, True])
def test_w1g5_tribal_entry_triggers_and_tap_costs_see_mistform_ultimus(
    set_pool, with_ultimus,
):
    """Totem Speaker ("Whenever a Beast enters, you may gain 3 life") and
    Wirewood Hivemaster ("Whenever another nontoken Elf enters, you may
    create a 1/1 green Insect") both answer the Ultimus entering — and
    neither answers a Human Cleric (Daru Mender) entering. Crookclaw
    Elder's "Tap two untapped Birds you control" can tap the Ultimus as its
    second Bird."""
    entering = "Mistform Ultimus" if with_ultimus else "Daru Mender"
    game, alice, bob, card = _w1g5_table(set_pool, entering)
    _w1g5_put(game, 0, card("Wirewood Hivemaster"))
    _w1g5_put(game, 0, card("Totem Speaker"))     # an Elf: one Insect already
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    def insects():
        return sum(1 for p in game.controlled_by(0) if "Insect" in p.card.name)

    before_life, before_insects = alice.life, insects()
    assert game.queue_from_hand(0, entering).supported
    for _ in range(3):
        _w1g5_resolve_stack(game)
        game.auto_resolve_pending_choices()
    assert alice.life - before_life == (3 if with_ultimus else 0)
    assert insects() - before_insects == (1 if with_ultimus else 0)

    elder = _w1g5_put(game, 0, card("Crookclaw Elder"))
    hand = len(alice.hand)
    result = game.activate_permanent_ability(0, "Crookclaw Elder", ability_index=0)
    _w1g5_resolve_stack(game)
    if with_ultimus:
        assert result.supported and len(alice.hand) == hand + 1
        assert elder.tapped
    else:
        assert not result.supported, "one Bird is not two"

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
