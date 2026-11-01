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

# --- W1G7: players and odd ends ----------------------------------------------
import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game
from engine.models import Permanent as _w1g7_Permanent
from engine.models import PlayerState as _w1g7_PlayerState

from tests.helpers import _nosick as _w1g7_nosick
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


#: Where a W1G7 test finds a card by name: Legions first, then Alpha (the
#: lands and the old regulars), then Arabian Nights (Old Man of the Sea).
_W1G7_SETS = ("LGN", "LEA", "ARN")


def _w1g7_card(set_pool, name):
    """A card by name from the first of :data:`_W1G7_SETS` that prints it."""
    for code in _W1G7_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g7_table(set_pool, hands=None, *, libraries=None, seats=2, interactive=()):
    """A *seats*-player table, Alice active, costs unenforced."""
    hands = hands or {}
    libraries = libraries or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g7_PlayerState(
            name=name,
            hand=[_w1g7_card(set_pool, c) for c in hands.get(seat, ())],
            library=[
                _w1g7_card(set_pool, c)
                for c in libraries.get(seat, ["Plains"] * 8)
            ],
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g7_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g7_put(game, set_pool, seat, name, *, tapped=False):
    """Put *name* onto *seat*'s battlefield by an effect (never cast)."""
    permanent = _w1g7_Permanent(card=_w1g7_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve_stack(game)
    _w1g7_nosick(permanent)
    permanent.tapped = tapped
    return permanent


def _w1g7_finish_combat(game):
    """Step from declare-blockers through the damage, draining each trigger."""
    for _ in range(12):
        _w1g7_resolve_stack(game)
        if game.current_phase != "combat" or game.pending_choices:
            return
        game.advance_combat_phase()


def _w1g7_names(cards):
    return [card.name for card in cards]


# --- Phage the Untouchable ----------------------------------------------------


def test_w1g7_phage_cast_from_a_hand_keeps_its_controller_in_the_game(set_pool):
    """"When Phage enters, if you didn't cast it from your hand, you lose the
    game." Cast from Alice's hand, the intervening-if (CR 603.4) is false when
    the permanent enters, so nothing triggers and nobody loses."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    assert _w1g7_names(p.card for p in game.controlled_by(0)) == ["Phage the Untouchable"]
    assert not game.players[0].lost
    assert any("didn't trigger" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_put_onto_the_battlefield_loses_the_game(set_pool):
    """The ruling (2004-10-04): "Putting it onto the battlefield from your
    hand using a spell or ability will cause you to lose the game." A Phage
    that was never cast has no cast stamp, so its controller loses."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Phage the Untouchable")
    assert game.players[0].lost
    assert not game.players[1].lost
    assert any("Alice lost the game" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_destroys_what_it_damages_past_regeneration(set_pool):
    """"Whenever Phage deals combat damage to a creature, destroy that
    creature. It can't be regenerated." Drudge Skeletons with two shields
    spends one on the lethal combat damage and the second cannot save it from
    the trigger; a Wall of Stone that survives the damage is destroyed too."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    skeletons = _w1g7_put(game, set_pool, 1, "Drudge Skeletons")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    for _ in range(2):
        assert game.activate_permanent_ability(
            1, "Drudge Skeletons",
            permanent_index=game.battlefield_index_of(skeletons),
        ).supported
        _w1g7_resolve_stack(game)
    _w1g7_finish_combat(game)
    assert "Drudge Skeletons regenerated" in game.log
    assert "Phage the Untouchable destroyed Drudge Skeletons" in game.log
    assert _w1g7_names(game.players[1].graveyard) == ["Drudge Skeletons"]

    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_put(game, set_pool, 1, "Wall of Stone")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_finish_combat(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Wall of Stone"]
    assert not game.players[1].lost


def test_w1g7_phage_unblocked_makes_the_damaged_player_lose(set_pool):
    """"Whenever Phage deals combat damage to a player, that player loses the
    game." Bob takes four and loses; Alice, who cast Phage, does not."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 16
    assert game.players[1].lost
    assert not game.players[0].lost


# --- Riptide Mangler ----------------------------------------------------------


def test_w1g7_riptide_mangler_takes_a_targets_power_and_keeps_it(set_pool):
    """"{1}{U}: This creature's base power becomes equal to target creature's
    power. (This effect lasts indefinitely.)" Layer 7b (CR 613.4b): the 0/3
    becomes 6/3 off a Craw Wurm, toughness untouched; a Giant Growth applies on
    top (the 2015-02-25 ruling); a second activation overwrites the first
    (the other 2015-02-25 ruling); and the write outlasts the turn's
    cleanup."""
    game = _w1g7_table(set_pool, hands={0: ["Giant Growth"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (6, 3)
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)

    assert game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[mangler.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (9, 6)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (5, 6)

    game.resolve_cleanup_step(0)
    assert (mangler.effective_power, mangler.effective_toughness) == (2, 3)


def test_w1g7_riptide_mangler_fizzles_when_its_target_leaves(set_pool):
    """CR 608.2b: the Wurm exiled in response leaves the ability with no legal
    target, so it does nothing — the Mangler stays 0/3 rather than reading the
    power of a creature that is gone."""
    game = _w1g7_table(set_pool, hands={0: ["Swords to Plowshares"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)
    assert any("every target is illegal" in line for line in game.log)


# --- Seedborn Muse ------------------------------------------------------------


def _w1g7_tapped(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.tapped)


def test_w1g7_seedborn_muse_untaps_its_controllers_board_in_the_other_step(set_pool):
    """"Untap all permanents you control during each other player's untap
    step." In Bob's untap step Alice untaps everything, including a Basalt
    Monolith ("doesn't untap during your untap step") and a Sunstrike
    Legionnaire ("doesn't untap during your untap step") — the 2004-10-04
    ruling: a restriction printed about its controller's step does not bind
    this one. Bob's own Winter Orb caps *his* step at one land and does not
    touch Alice's lands, which untap in a step that is not hers. In Alice's
    own step the Monolith and the Legionnaire stay tapped and the Orb caps
    her lands at one."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 1, "Grizzly Bears", tapped=True)
    for name in ("Seedborn Muse", "Basalt Monolith", "Sunstrike Legionnaire",
                 "Forest", "Forest"):
        _w1g7_put(game, set_pool, 0, name, tapped=True)
    _w1g7_put(game, set_pool, 1, "Winter Orb")
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Island"], "Winter Orb still caps Bob's own step"
    assert (
        "Alice untapped 5 permanent(s) during Bob's untap step (Seedborn Muse)"
        in game.log
    )

    for permanent in game.controlled_by(0):
        permanent.tapped = True
    game.active_player_index = 0
    game.resolve_untap_step(0)
    assert _w1g7_tapped(game, 0) == [
        "Basalt Monolith", "Forest", "Sunstrike Legionnaire",
    ]


def test_w1g7_seedborn_muse_gives_old_man_of_the_sea_no_choice(set_pool):
    """The 2007-07-15 ruling: "You have no choice about what untaps." Alice's
    Old Man of the Sea ("You may choose not to untap this creature during your
    untap step") untaps in Bob's step with nobody asked — even with both seats
    interactive — and the Grizzly Bears it held go back to Bob."""
    game = _w1g7_table(set_pool, interactive={0, 1})
    _w1g7_put(game, set_pool, 0, "Seedborn Muse")
    old_man = _w1g7_put(game, set_pool, 0, "Old Man of the Sea")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert game.queue_permanent_ability(
        0, "Old Man of the Sea", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert game.controller_index_of(bears) == 0 and old_man.tapped

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert game.pending_choices == []
    assert not old_man.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g7_seedborn_muse_does_nothing_in_a_skipped_step_or_its_own(set_pool):
    """A skipped untap step (Stasis, CR 500.11) is not an untap step at all,
    so the Muse has none to act in. At three seats it acts in each other
    player's step and in no one else's favour: in Cara's step Alice untaps,
    Bob — who has no Muse — does not."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Stasis")
    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == ["Seedborn Muse"]

    game = _w1g7_table(set_pool, seats=3)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Forest", tapped=True)
    _w1g7_put(game, set_pool, 2, "Forest", tapped=True)
    game.active_player_index = 2
    game.resolve_untap_step(2)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Forest"]
    assert _w1g7_tapped(game, 2) == []


# --- Goblin Assassin ----------------------------------------------------------


def _w1g7_rig_coins(monkeypatch, faces):
    """Each flip the handler makes, in order: True is heads."""
    queue = list(faces)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: queue.pop(0)
    )
    return queue


def _w1g7_board(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g7_goblin_assassin_tails_sacrifices_heads_does_not(set_pool, monkeypatch):
    """"Whenever this creature or another Goblin enters, each player flips a
    coin. Each player whose coin comes up tails sacrifices a creature of their
    choice." Alice's coin comes up heads and Bob's tails: only Bob gives up a
    creature (the cheaper, by the nobody-asked default), and nobody wins or
    loses a flip (the 2004-10-04 ruling) — the log names faces, not wins."""
    coins = _w1g7_rig_coins(monkeypatch, [True, False])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == []
    assert _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Craw Wurm"]
    assert "Goblin Assassin: Alice flipped heads" in game.log
    assert "Goblin Assassin: Bob flipped tails" in game.log
    assert not any("won the coin flip" in line for line in game.log)


def test_w1g7_goblin_assassin_asks_each_tails_seat_which_creature(set_pool, monkeypatch):
    """Both coins tails, both seats interactive: each is asked for a creature
    of their choice, and each answer is what goes. Alice may give up the
    Assassin itself."""
    _w1g7_rig_coins(monkeypatch, [False, False])
    game = _w1g7_table(
        set_pool, hands={0: ["Goblin Assassin"]}, interactive={0, 1},
    )
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    game.resolve_top_of_stack()
    assert not game.resolve_top_of_stack(), "the trigger waits for its answers"
    assert sorted(c.player_index for c in game.pending_choices if c.kind == "sacrifice") == [0, 1]
    assassin = next(
        p for p in game.controlled_by(0) if p.card.name == "Goblin Assassin"
    )
    wurm = next(p for p in game.controlled_by(1) if p.card.name == "Craw Wurm")
    assert game.confirm_sacrifice(0, [game.battlefield_index_of(assassin)])
    assert game.confirm_sacrifice(1, [game.battlefield_index_of(wurm)])
    _w1g7_resolve_stack(game)
    assert _w1g7_board(game, 0) == ["Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Grizzly Bears"]


def test_w1g7_goblin_assassin_hears_another_goblin_and_no_one_else(set_pool, monkeypatch):
    """Another Goblin entering (Mons's Goblin Raiders) fires it again; a Craw
    Wurm entering fires nothing — no coin is drawn for it."""
    coins = _w1g7_rig_coins(monkeypatch, [True, True])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == [] and _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]

    coins.extend([False, True])
    _w1g7_put(game, set_pool, 0, "Mons's Goblin Raiders")
    assert coins == []
    assert len(game.players[0].graveyard) == 1
    assert len(_w1g7_board(game, 0)) == 2

    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert _w1g7_board(game, 1) == ["Craw Wurm"]


# --- Hollow Specter -----------------------------------------------------------

_W1G7_BOB_HAND = ["Lightning Bolt", "Plains", "Shivan Dragon", "Island", "Giant Growth"]


def _w1g7_specter_hits(set_pool, bob_hand, swamps, *, interactive):
    """Alice's Hollow Specter connects with Bob; returns the game with the
    trigger's resolution started and held on Alice's prompt. Alice must be
    interactive: a seat nobody asks is answered as the trigger resolves."""
    game = _w1g7_table(set_pool, hands={1: bob_hand}, interactive=interactive)
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(swamps):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    for _ in range(6):
        if game.stack:
            break
        game.advance_combat_phase()
    assert [item.card.name for item in game.stack] == ["Hollow Specter"]
    game.resolve_top_of_stack()
    return game


def test_w1g7_hollow_specter_x_paid_then_shown_then_picked(set_pool):
    """"…you may pay {X}. If you do, that player reveals X cards from their
    hand and you choose one of them. That player discards that card." The
    ruling (2004-10-04): "You decide on the value of X and pay {X} during
    resolution." Alice names 2 and two Swamps tap; Bob picks the two he shows
    (CR 608.2c); Alice may take only one of those, and Bob discards it."""
    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.players[1].life == 18
    assert game.pending_choice_of("pay_any_amount", 0) is not None
    assert not game.confirm_pay_any_amount(0, 4), "three Swamps cannot pay {4}"
    assert game.confirm_pay_any_amount(0, 2)
    tapped = [p for p in game.controlled_by(0) if p.tapped and p.card.name == "Swamp"]
    assert len(tapped) == 2
    shown = game.pending_choice_of("choose_cards_in_hand", 1)
    assert shown is not None and shown.data["count"] == 2
    assert game.confirm_choose_cards_in_hand(1, [1, 2])
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [1, 2]
    assert not game.confirm_revealed_hand_pick(0, 0), "Lightning Bolt was never shown"
    assert game.confirm_revealed_hand_pick(0, 2)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == [
        "Lightning Bolt", "Plains", "Island", "Giant Growth",
    ]
    assert game.stack == [] and game.pending_choices == []


def test_w1g7_hollow_specter_x_past_the_hand_shows_it_all(set_pool):
    """X larger than Bob's hand reveals every card he has (CR 608.2's as much
    as possible) and nobody asks him which; Alice picks among them."""
    game = _w1g7_specter_hits(
        set_pool, ["Plains", "Shivan Dragon"], 4, interactive={0},
    )
    assert game.confirm_pay_any_amount(0, 4)
    assert game.pending_choice_of("choose_cards_in_hand", 1) is None
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [0, 1]
    assert game.confirm_revealed_hand_pick(0, 1)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == ["Plains"]


def test_w1g7_hollow_specter_x_zero_discards_nothing(set_pool):
    """The ruling (2004-10-04): "X can be zero, but then that player discards
    nothing." A seat nobody asks pays nothing — the stated default of the
    any-amount payment — and Bob keeps his hand; so does an interactive Alice
    who names 0."""
    game = _w1g7_table(set_pool, hands={1: _W1G7_BOB_HAND})
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(3):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 18
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert "Alice paid no mana" in game.log

    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.confirm_pay_any_amount(0, 0)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert not any(p.tapped for p in game.controlled_by(0) if p.card.name == "Swamp")


# --- Drive list: Dreamborn Muse -----------------------------------------------


@_w1g7_pytest.mark.parametrize("controller", [0, 1])
def test_w1g7_dreamborn_muse_mills_each_player_by_their_own_hand(set_pool, controller):
    """"At the beginning of each player's upkeep, that player mills X cards,
    where X is the number of cards in their hand." Alice holds one card and Bob
    three; whoever controls the Muse, Alice mills one in her upkeep and Bob
    three in his. "Their" is the upkeep's player (CR 603.10) — it used to be
    read as the Muse controller's opponent, so both players milled the same
    number."""
    game = _w1g7_table(
        set_pool, hands={0: ["Plains"], 1: ["Island", "Island", "Island"]},
    )
    _w1g7_put(game, set_pool, controller, "Dreamborn Muse")
    for seat in (0, 1):
        game.active_player_index = seat
        game.resolve_upkeep(seat)
        _w1g7_resolve_stack(game)
    assert len(game.players[0].graveyard) == 1
    assert len(game.players[1].graveyard) == 3
    assert len(game.players[0].library) == 7 and len(game.players[1].library) == 5

# ==== end W1G7 ======================================================
