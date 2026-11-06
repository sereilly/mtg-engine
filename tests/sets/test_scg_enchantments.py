"""Scourge enchantments, Auras included.

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
#
# Dragons and Auras. The five Dragon Auras' "When a creature with mana value 6
# or greater enters, you may return this card from your graveyard to the
# battlefield attached to that creature": a trigger that functions from a
# graveyard (CR 113.6m), narrowed by the entering creature's mana value, and an
# Aura put onto the battlefield attached to a host the effect names (CR 303.4i:
# not targeted, and it stays in the graveyard when it cannot enchant it).

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("SCG", "LEA", "LEG", "USG", "ONS", "STH", "TMP", "ARN"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_table(set_pool, *, graveyard=(), hand=(), opp_graveyard=(), interactive=()):
    me = _W1G6PlayerState(
        name="Me",
        graveyard=[_w1g6_card(set_pool, n) for n in graveyard],
        hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Island")] * 8,
    )
    opp = _W1G6PlayerState(
        name="Opp",
        graveyard=[_w1g6_card(set_pool, n) for n in opp_graveyard],
        library=[_w1g6_card(set_pool, "Forest")] * 8,
    )
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game


def _w1g6_enter(game, set_pool, seat, name):
    """Put *name* onto the battlefield under *seat* — not cast, so only the
    entry announcement runs (CR 603.6a)."""
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_settle(game):
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)


def _w1g6_attached(game, name):
    return [
        perm.metadata.get("attached_to") for perm in game.all_permanents()
        if perm.card.name == name
    ]


def _w1g6_graveyard(game, seat=0):
    return [card.name for card in game.players[seat].graveyard]


def test_w1g6_dragon_fangs_returns_attached_to_an_entering_six_drop(set_pool):
    """Dragon Fangs in the graveyard, Shivan Dragon (mana value 6) enters: the
    Aura comes back attached to it, and its static is live — 6/6 trample."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Dragon Fangs"]
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Fangs") == [dragon]
    assert "Dragon Fangs" not in _w1g6_graveyard(game)
    assert (dragon.effective_power, dragon.effective_toughness) == (6, 6)
    assert game._has_keyword(dragon, "trample")
    assert "Dragon Fangs attached to Shivan Dragon" in game.log


def test_w1g6_a_small_creature_entering_triggers_no_dragon_aura(set_pool):
    """Grizzly Bears (mana value 2) is not "a creature with mana value 6 or
    greater": nothing triggers from the graveyard."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Scales"])
    _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert not game.stack
    assert _w1g6_graveyard(game) == ["Dragon Scales"]


def test_w1g6_dragon_aura_stays_in_the_graveyard_when_its_host_leaves_first(set_pool):
    """CR 303.4i, in response: the Dragon is destroyed with the trigger on the
    stack, so the effect names a host that is gone and the Aura remains in its
    current zone."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Shadow"], hand=["Terror"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Dragon Shadow"]
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[dragon.permanent_id]
    ).supported
    assert [item.card.name for item in game.stack] == ["Dragon Shadow", "Terror"]
    _w1g6_settle(game)
    assert not game.is_on_battlefield(dragon)
    assert "Dragon Shadow" in _w1g6_graveyard(game)
    assert not _w1g6_attached(game, "Dragon Shadow")
    assert any("stays in the graveyard" in line for line in game.log)


def test_w1g6_two_dragon_auras_both_trigger_and_both_attach(set_pool):
    """Two Dragon Auras in the graveyard and one big creature entering: both
    trigger, both come back onto it."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath", "Dragon Wings"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert sorted(item.card.name for item in game.stack) == ["Dragon Breath", "Dragon Wings"]
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Breath") == [dragon]
    assert _w1g6_attached(game, "Dragon Wings") == [dragon]
    assert game._has_keyword(dragon, "haste")


def test_w1g6_an_interactive_seat_is_asked_and_may_decline(set_pool):
    """The return is a "may": an asked seat that declines keeps the Aura in its
    graveyard; one that accepts gets it back attached."""
    for accept in (False, True):
        game = _w1g6_table(set_pool, graveyard=["Dragon Scales"], interactive={0})
        dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
        game.resolve_top_of_stack()
        assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, "Dragon Scales", accept=accept)
        _w1g6_resolve_stack(game)
        if accept:
            assert _w1g6_attached(game, "Dragon Scales") == [dragon]
            assert (dragon.effective_power, dragon.effective_toughness) == (6, 7)
            assert game._has_keyword(dragon, "vigilance")
        else:
            assert _w1g6_graveyard(game) == ["Dragon Scales"]


def test_w1g6_an_opponents_six_drop_triggers_the_owners_aura(set_pool):
    """"A creature … enters" is anyone's. Asked, the owner may put the Aura on
    the opponent's creature — it returns under the owner's control (CR
    108.4a); the AI declines a helpful Aura onto the wrong side."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"], interactive={0})
    dragon = _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, "Dragon Fangs", accept=True)
    _w1g6_resolve_stack(game)
    fangs = next(p for p in game.all_permanents() if p.card.name == "Dragon Fangs")
    assert fangs.metadata.get("attached_to") is dragon
    assert game.controller_index_of(fangs) == 0
    assert game.controller_index_of(dragon) == 1

    ai = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    _w1g6_enter(ai, set_pool, 1, "Shivan Dragon")
    _w1g6_settle(ai)
    assert _w1g6_graveyard(ai) == ["Dragon Fangs"]
    assert any("wrong side" in line for line in ai.log)


def test_w1g6_protection_keeps_the_aura_in_the_graveyard_and_shroud_does_not(set_pool):
    """Ivory Guardians (protection from red) can't be enchanted by Dragon
    Breath (CR 702.16c), so the Aura stays put; Zephid's shroud is no bar,
    because nothing targets (CR 303.4i names the host, CR 115.1)."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath"])
    _w1g6_enter(game, set_pool, 0, "Ivory Guardians")
    _w1g6_settle(game)
    assert _w1g6_graveyard(game) == ["Dragon Breath"]
    assert any("protection" in line for line in game.log)

    game = _w1g6_table(set_pool, graveyard=["Dragon Fangs"])
    zephid = _w1g6_enter(game, set_pool, 0, "Zephid")
    _w1g6_settle(game)
    assert _w1g6_attached(game, "Dragon Fangs") == [zephid]


def test_w1g6_dragon_breaths_firebreathing_pumps_the_creature_it_returned_onto(set_pool):
    """The other lines, driven attached: Dragon Breath's "{R}: Enchanted
    creature gets +1/+0 until end of turn"."""
    game = _w1g6_table(set_pool, graveyard=["Dragon Breath"])
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    _w1g6_settle(game)
    assert game.activate_permanent_ability(0, "Dragon Breath").supported
    _w1g6_resolve_stack(game)
    assert dragon.effective_power == 6


def test_w1g6_dragon_auras_cast_from_the_hand_still_enchant(set_pool):
    """Cast the ordinary way, each Aura's static applies to its target — Dragon
    Shadow's +1/+0 and fear on a Grizzly Bears."""
    game = _w1g6_table(set_pool, hand=["Dragon Shadow"])
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, "Dragon Shadow", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g6_resolve_stack(game)
    assert _w1g6_attached(game, "Dragon Shadow") == [bears]
    assert bears.effective_power == 3
    assert game._has_keyword(bears, "fear")


def _w1g6_enchant(game, aura, host):
    """Cast *aura* from seat 0's hand onto *host* and resolve it."""
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, aura, target_permanent_ids=[host.permanent_id]
    ).supported
    _w1g6_resolve_stack(game)
    (attached,) = [p for p in game.all_permanents() if p.card.name == aura]
    assert attached.metadata.get("attached_to") is host
    return attached


def _w1g6_pt(perm):
    return perm.effective_power, perm.effective_toughness


# --- Clutch of Undeath ------------------------------------------------------


def test_w1g6_clutch_of_undeath_pumps_a_zombie_and_shrinks_anything_else(set_pool):
    """"Enchanted creature gets +3/+3 as long as it's a Zombie. Otherwise, it
    gets -3/-3." Gravedigger (a Zombie) is 5/5; a Grizzly Bears is -1/-1 and
    dies to the state-based check."""
    game = _w1g6_table(set_pool, hand=["Clutch of Undeath"])
    digger = _w1g6_enter(game, set_pool, 0, "Gravedigger")
    _w1g6_settle(game)
    _w1g6_enchant(game, "Clutch of Undeath", digger)
    assert _w1g6_pt(digger) == (5, 5)

    game = _w1g6_table(set_pool, hand=["Clutch of Undeath"])
    bears = _w1g6_enter(game, set_pool, 1, "Grizzly Bears")
    _w1g6_enchant(game, "Clutch of Undeath", bears)
    assert _w1g6_pt(bears) == (-1, -1)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(bears)
    assert "Clutch of Undeath" in _w1g6_graveyard(game)


def test_w1g6_clutch_of_undeath_switches_arms_when_its_host_becomes_a_zombie(set_pool):
    """The criterion is re-asked through layer 4 (CR 611.3b): a Craw Wurm
    under the Clutch is 3/1, and made a Zombie it is 9/7."""
    from engine.type_changes import gain_types as _w1g6_gain_types

    game = _w1g6_table(set_pool, hand=["Clutch of Undeath"])
    wurm = _w1g6_enter(game, set_pool, 0, "Craw Wurm")
    _w1g6_enchant(game, "Clutch of Undeath", wurm)
    assert _w1g6_pt(wurm) == (3, 1)
    _w1g6_gain_types(wurm, subtypes=["Zombie"], source="test")
    game._recompute_continuous_effects()
    assert _w1g6_pt(wurm) == (9, 7)


# --- Pemmin's Aura ----------------------------------------------------------


def test_w1g6_pemmins_aura_asks_which_pump_as_it_resolves(set_pool):
    """"{1}: Enchanted creature gets +1/-1 or -1/+1 until end of turn." The
    choice is made on resolution (CR 608.2d): an asked seat is offered both
    printed options and gets the one it picks, until end of turn."""
    for pick, expected in ((0, (3, 1)), (1, (1, 3))):
        game = _w1g6_table(set_pool, hand=["Pemmin's Aura"], interactive={0})
        bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
        _w1g6_enchant(game, "Pemmin's Aura", bears)
        assert game.activate_permanent_ability(
            0, "Pemmin's Aura", ability_index=3,
        ).supported
        game.resolve_top_of_stack()
        (choice,) = game.pending_choices
        assert choice.kind == "mode_choice"
        assert choice.data["labels"] == ["+1/-1", "-1/+1"]
        assert game.resolve_pending_choice("mode_choice", 0, mode_index=pick)
        _w1g6_resolve_stack(game)
        assert _w1g6_pt(bears) == expected
        game.resolve_cleanup_step(0)
        assert _w1g6_pt(bears) == (2, 2)


def test_w1g6_pemmins_aura_untaps_and_grants_flying_and_shroud(set_pool):
    """The other three abilities, driven attached: untap, flying, shroud."""
    game = _w1g6_table(set_pool, hand=["Pemmin's Aura"])
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    _w1g6_enchant(game, "Pemmin's Aura", bears)
    bears.tapped = True
    for index in range(3):
        assert game.activate_permanent_ability(
            0, "Pemmin's Aura", ability_index=index,
        ).supported
        _w1g6_resolve_stack(game)
    assert not bears.tapped
    assert game._has_keyword(bears, "flying")
    assert game._has_keyword(bears, "shroud")


# --- Uncontrolled Infestation -----------------------------------------------


def _w1g6_infested(set_pool, *, tapped=False):
    game = _w1g6_table(set_pool, hand=["Uncontrolled Infestation", "Twiddle"])
    city = _W1G6Permanent(card=_w1g6_card(set_pool, "City of Brass"), tapped=tapped)
    forest = _W1G6Permanent(card=_w1g6_card(set_pool, "Forest"))
    game.players[1].battlefield.extend([city, forest])
    game._sync_control()
    return game, city, forest


def test_w1g6_uncontrolled_infestation_enchants_only_a_nonbasic_land(set_pool):
    """"Enchant nonbasic land": the picker offers the City of Brass and not
    the Forest, and a cast naming the Forest is refused (CR 601.2c)."""
    game, city, forest = _w1g6_infested(set_pool)
    card = _w1g6_card(set_pool, "Uncontrolled Infestation")
    spec = game.cast_target_spec(0, card)
    assert [t["name"] for t in spec["valid_targets"]] == ["City of Brass"]
    game._close_current_priority_step()
    refused = game.queue_from_hand(
        0, "Uncontrolled Infestation", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    _w1g6_enchant(game, "Uncontrolled Infestation", city)


def test_w1g6_uncontrolled_infestation_destroys_the_land_tapped_for_mana(set_pool):
    """"When enchanted land becomes tapped, destroy it" — and tapping for mana
    is becoming tapped (CR 106.12's event, every road)."""
    game, city, _forest = _w1g6_infested(set_pool)
    _w1g6_enchant(game, "Uncontrolled Infestation", city)
    assert game.tap_land_for_mana(
        1, "City of Brass", chosen_color="R", permanent_id=city.permanent_id,
    )
    _w1g6_settle(game)
    assert not game.is_on_battlefield(city)
    assert "City of Brass" in _w1g6_graveyard(game, 1)


def test_w1g6_uncontrolled_infestation_on_a_tapped_land_waits_for_the_next_tap(set_pool):
    """Ruling 2004-10-04: "It only triggers if the land becomes tapped after
    this Aura is on it. Attaching it to a tapped land will not destroy the
    land until the next time the land is untapped and then tapped again." —
    and an effect's tap (Twiddle) is a tap too."""
    game, city, _forest = _w1g6_infested(set_pool, tapped=True)
    _w1g6_enchant(game, "Uncontrolled Infestation", city)
    assert game.is_on_battlefield(city)
    assert city.tapped
    city.tapped = False
    assert game.queue_from_hand(
        0, "Twiddle", target_permanent_ids=[city.permanent_id]
    ).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(city)


def test_w1g6_uncontrolled_infestation_falls_off_a_land_that_becomes_basic(set_pool):
    """The supertype half of the enchant clause is enforced by the CR 704.5m
    sweep as well as the cast, through layer 4: made basic, the City is no
    longer a legal host and the Aura goes to the graveyard."""
    from engine.type_changes import gain_types as _w1g6_gain_types

    game, city, _forest = _w1g6_infested(set_pool)
    aura = _w1g6_enchant(game, "Uncontrolled Infestation", city)
    _w1g6_gain_types(city, supertypes=["Basic"], source="test")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(aura)
    assert "Uncontrolled Infestation" in _w1g6_graveyard(game)
    assert game.is_on_battlefield(city)


# --- Alpha Status (a red on the base) ---------------------------------------


def test_w1g6_alpha_status_counts_each_other_creature_sharing_a_type_once(set_pool):
    """"+2/+2 for each other creature on the battlefield that shares a
    creature type with it" — "it" is the enchanted creature. An Elf Warrior
    beside an Elf Druid, a Human Soldier, an opponent's Goblin Warrior and a
    Bear: two share a type, +4/+4. A second Elf Warrior shares both and is
    counted once (ruling 2004-10-04): +6/+6. It compiled supported and gave
    +0/+0 on every board, the "it" bound to nothing."""
    game = _w1g6_table(set_pool, hand=["Alpha Status"])
    host = _w1g6_enter(game, set_pool, 0, "Elvish Warrior")
    for seat, name in ((0, "Wirewood Elf"), (0, "Glory Seeker"),
                       (1, "Goblin Sky Raider"), (1, "Grizzly Bears")):
        _w1g6_enter(game, set_pool, seat, name)
    _w1g6_settle(game)
    _w1g6_enchant(game, "Alpha Status", host)
    assert _w1g6_pt(host) == (2 + 4, 3 + 4)
    _w1g6_enter(game, set_pool, 1, "Elvish Warrior")
    game._recompute_continuous_effects()
    assert _w1g6_pt(host) == (2 + 6, 3 + 6)


# --- Day of the Dragons (a red on the base) ---------------------------------


def test_w1g6_day_of_the_dragons_makes_a_dragon_for_each_creature_it_exiled(set_pool):
    """"Exile all creatures you control. Then create that many 5/5 red Dragon
    creature tokens with flying." Two creatures and a token of the caster's,
    one of the opponent's: three Dragons (ruling 2017-11-17: "Token creatures
    will count"). Leaving, it sacrifices the Dragons and returns the two
    nontoken cards. The count read a key nothing in the trigger wrote, and it
    made no Dragons at all."""
    from engine.tokens import make_token_card as _w1g6_make_token_card

    game = _w1g6_table(set_pool, hand=["Day of the Dragons", "Disenchant"])
    _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    _w1g6_enter(game, set_pool, 0, "Craw Wurm")
    token = _W1G6Permanent(card=_w1g6_make_token_card(
        name="Soldier Token", power=1, toughness=1, type_line="Creature — Soldier",
    ))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    theirs = _w1g6_enter(game, set_pool, 1, "Grizzly Bears")
    _w1g6_settle(game)
    game._close_current_priority_step()
    assert game.queue_from_hand(0, "Day of the Dragons").supported
    _w1g6_settle(game)
    dragons = [p for p in game.controlled_by(0) if p.card.name == "Dragon Token"]
    assert len(dragons) == 3
    assert all(_w1g6_pt(d) == (5, 5) and game._has_keyword(d, "flying") for d in dragons)
    assert game.is_on_battlefield(theirs)
    assert sorted(c.name for c in game.players[0].exile) == ["Craw Wurm", "Grizzly Bears"]

    day = next(p for p in game.all_permanents() if p.card.name == "Day of the Dragons")
    assert game.queue_from_hand(
        0, "Disenchant", target_permanent_ids=[day.permanent_id]
    ).supported
    _w1g6_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Craw Wurm", "Grizzly Bears",
    ]
    assert not game.players[0].exile


# --- The drive list: Auras supported on arrival -----------------------------


def _w1g6_attach(game, set_pool, seat, aura, host):
    """Put *aura* onto the battlefield under *seat* attached to *host*."""
    from engine.aura_attachment import attach_aura as _w1g6_attach_aura

    permanent = _W1G6Permanent(card=_w1g6_card(set_pool, aura))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g6_attach_aura(permanent, host)
    game._recompute_continuous_effects()
    return permanent


def test_w1g6_extra_arms_has_the_attacker_deal_two_to_any_target(set_pool):
    """"Whenever enchanted creature attacks, it deals 2 damage to any target."
    The creature is the source, not the Aura."""
    game = _w1g6_table(set_pool)
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    _w1g6_attach(game, set_pool, 0, "Extra Arms", bears)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    assert [item.card.name for item in game.stack] == ["Extra Arms"]
    _w1g6_settle(game)
    assert game.players[1].life == 18
    assert any("Grizzly Bears dealt 2 damage" in line for line in game.log)


def test_w1g6_frozen_solid_keeps_its_host_tapped_and_destroys_it_when_dealt_damage(set_pool):
    """It doesn't untap in its controller's untap step, and a Shock that
    leaves a Hill Giant alive destroys it all the same."""
    game = _w1g6_table(set_pool, hand=["Shock"])
    giant = _w1g6_enter(game, set_pool, 0, "Hill Giant")
    _w1g6_attach(game, set_pool, 1, "Frozen Solid", giant)
    giant.tapped = True
    game.start_turn(0)
    assert giant.tapped
    _w1g6_settle(game)
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, "Shock", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(giant)
    assert "Frozen Solid destroyed Hill Giant" in game.log


def test_w1g6_guilty_conscience_deals_its_host_what_it_dealt(set_pool):
    """"Whenever enchanted creature deals damage, this Aura deals that much
    damage to that creature." Unblocked, a Grizzly Bears deals 2 to the
    defending player and is dealt 2 back — and dies."""
    from tests.helpers import declare_attack as _w1g6_declare_attack

    game = _w1g6_table(set_pool)
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    _w1g6_attach(game, set_pool, 1, "Guilty Conscience", bears)
    _w1g6_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g6_settle(game)
    game.check_state_based_actions()
    assert game.players[1].life == 18
    assert not game.is_on_battlefield(bears)


def test_w1g6_lingering_death_sacrifices_at_its_hosts_controllers_end_step(set_pool):
    """At the end step of the enchanted creature's controller — not the Aura's
    controller's — that player sacrifices it."""
    game = _w1g6_table(set_pool)
    bears = _w1g6_enter(game, set_pool, 1, "Grizzly Bears")
    _w1g6_attach(game, set_pool, 0, "Lingering Death", bears)
    game.resolve_end_step(0)
    _w1g6_settle(game)
    assert game.is_on_battlefield(bears)
    game.resolve_end_step(1)
    _w1g6_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g6_graveyard(game, 1) == ["Grizzly Bears"]


def test_w1g6_one_with_nature_fetches_a_basic_land_tapped_on_combat_damage(set_pool):
    """Combat damage to a player: the may searches for a basic land card and
    puts it onto the battlefield tapped — never the Grizzly Bears beside it."""
    from tests.helpers import declare_attack as _w1g6_declare_attack

    game = _w1g6_table(set_pool)
    game.players[0].library = [
        _w1g6_card(set_pool, "Grizzly Bears"), _w1g6_card(set_pool, "Forest"),
    ]
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    _w1g6_attach(game, set_pool, 0, "One with Nature", bears)
    _w1g6_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g6_settle(game)
    (forest,) = [p for p in game.controlled_by(0) if p.card.name == "Forest"]
    assert forest.tapped
    assert [c.name for c in game.players[0].library] == ["Grizzly Bears"]


def test_w1g6_form_of_the_dragon_sets_life_burns_and_grounds_attackers(set_pool):
    """Each end step — anyone's (ruling 2004-10-04) — its controller's life
    becomes 5, up or down; its upkeep deals 5 to any target; creatures without
    flying can't attack its controller."""
    game = _w1g6_table(set_pool)
    _w1g6_enter(game, set_pool, 0, "Form of the Dragon")
    bears = _w1g6_enter(game, set_pool, 1, "Grizzly Bears")
    djinn = _w1g6_enter(game, set_pool, 1, "Mahamoti Djinn")
    game.players[0].life = 12
    game.resolve_end_step(1)
    _w1g6_settle(game)
    assert game.players[0].life == 5
    game.players[0].life = 2
    game.resolve_end_step(0)
    _w1g6_settle(game)
    assert game.players[0].life == 5
    game.start_turn(0)
    _w1g6_settle(game)
    assert game.players[1].life == 15
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    # Seat 1's battlefield is the Bears (slot 0) and the Djinn (slot 1).
    assert game.players[1].battlefield[0] is bears
    ok, _why = game.declare_attackers(1, [0], defending_player_index=0)
    assert not ok
    assert game.players[1].battlefield[1] is djinn
    ok, why = game.declare_attackers(1, [1], defending_player_index=0)
    assert ok, why

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
