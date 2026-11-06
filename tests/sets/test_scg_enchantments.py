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
#
# Decree of Silence: its opponent-cast trigger compiled to nothing until this
# round ("If there are three or more depletion counters on this enchantment"
# was a condition no production read), and its cycle trigger counters a
# spell on the stack.
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, bob_hand, *, active=1):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_depletion(permanent):
    return permanent.metadata.get("depletion_counters", 0)


def test_w1g2_decree_of_silence_counters_each_opponent_spell_and_dies_at_three(set_pool):
    """"Whenever an opponent casts a spell, counter that spell and put a
    depletion counter on this enchantment. If there are three or more
    depletion counters on this enchantment, sacrifice it." Three spells are
    countered; the fourth resolves."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [], [lea["Lightning Bolt"], lea["Lightning Bolt"],
                       lea["Grizzly Bears"], lea["Grizzly Bears"]],
    )
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])

    for count, name in enumerate(("Lightning Bolt", "Lightning Bolt", "Grizzly Bears"), 1):
        assert game.queue_from_hand(1, name, target_player_index=0).supported
        assert game.stack[-1].card.name == "Decree of Silence"
        _w1g2_drain(game)
        assert alice.life == 20
        if count < 3:
            assert _w1g2_depletion(decree) == count
            assert game.is_on_battlefield(decree)
    assert not game.is_on_battlefield(decree)
    assert [c.name for c in alice.graveyard] == ["Decree of Silence"]
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt", "Lightning Bolt", "Grizzly Bears"]

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g2_drain(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_w1g2_decree_of_silence_leaves_its_controllers_spells_alone(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [lea["Lightning Bolt"]], [], active=0)
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    _w1g2_drain(game)
    assert bob.life == 17 and _w1g2_depletion(decree) == 0


def test_w1g2_two_decrees_of_silence_counter_that_spell_and_no_bystander(set_pool):
    """"Counter **that spell**" is the spell the trigger fired on, found by
    identity (CR 603.3's trigger sits above it). Alice bolts Bob; Bob bolts
    back in response and both Decrees trigger. The first counters Bob's bolt;
    the second finds it gone and must not counter Alice's bolt, now the top
    spell — but it still takes its depletion counter."""
    lea, scg = set_pool("LEA"), set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [lea["Lightning Bolt"]], [lea["Lightning Bolt"]], active=0,
    )
    first = _w1g2_put(game, 0, scg["Decree of Silence"])
    second = _w1g2_put(game, 0, scg["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Lightning Bolt", "Decree of Silence", "Decree of Silence",
    ]
    _w1g2_drain(game)
    assert alice.life == 20, "Bob's bolt was countered"
    assert bob.life == 17, "Alice's bolt was not"
    assert (_w1g2_depletion(first), _w1g2_depletion(second)) == (1, 1)


def test_w1g2_decree_of_silence_cycled_counters_target_spell(set_pool):
    """"When you cycle this card, you may counter target spell." Cycled in
    response; the trigger resolves before the cycling draw (2022-12-08)."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Silence"]], [lea["Lightning Bolt"]],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.activate_from_hand(0, "Decree of Silence").supported
    trigger = game.stack[-1]
    assert trigger.ability_text.startswith("When you cycle this card")
    assert trigger.target_stack_item is not None or trigger.targets_chosen
    _w1g2_drain(game)
    assert alice.life == 20
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt"]
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_silence_cycles_with_no_spell_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The draw still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Silence"]], [])
    assert game.activate_from_hand(0, "Decree of Silence").supported
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Fatal Mutation: "When enchanted creature is turned face up, destroy it. It
# can't be regenerated." CR 708.8 lets a face-down creature be enchanted, and
# the Aura stays on as its host turns; the trigger is the host's turn, watched
# from the Aura (``event_filters._turned_face_up_filter``'s ``turned_attached``).

from engine import Game as _W1G5EGame, PlayerState as _W1G5EPlayerState
from engine.card_loader import load_catalog as _w1g5e_load_catalog
from engine.face_down import (face_down_card as _w1g5e_face_down_card,
                              turn_face_up as _w1g5e_turn_face_up)
from engine.models import Permanent as _W1G5EPermanent
from engine.special_actions import take_permanent_special_action as _w1g5e_take
from tests.helpers import resolve_stack as _w1g5e_resolve_stack

_W1G5E_CATALOG = {card.name: card for card in _w1g5e_load_catalog()}


def _w1g5e_permanent(card, *, face_down=False):
    permanent = _W1G5EPermanent(
        card=_w1g5e_face_down_card(card) if face_down else card,
    )
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5e_mutated(set_pool, host_name="Woodcloaker", *, extra_mine=()):
    """A's face-down *host_name* with four Forests; B enchants it with Fatal
    Mutation, cast through the engine (B holds a Swamp's {B} in its pool)."""
    scg = set_pool("SCG")
    host = _w1g5e_permanent(scg[host_name], face_down=True)
    forests = [_w1g5e_permanent(_W1G5E_CATALOG["Forest"]) for _ in range(4)]
    p1 = _W1G5EPlayerState(name="A", battlefield=[host, *forests, *extra_mine],
                           library=[_W1G5E_CATALOG["Island"]] * 10)
    p2 = _W1G5EPlayerState(name="B", hand=[scg["Fatal Mutation"]],
                           library=[_W1G5E_CATALOG["Island"]] * 10)
    game = _W1G5EGame(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(1)
    p2.mana_pool["B"] = 1
    cast = game.queue_from_hand(1, "Fatal Mutation", target_player_index=0,
                                target_permanent_ids=[host.permanent_id])
    assert cast.supported, cast.details
    _w1g5e_resolve_stack(game)
    aura = next(p for p in game.controlled_by(1) if p.card.name == "Fatal Mutation")
    assert aura.metadata.get("attached_to") is host
    game.active_player_index = 0
    game.start_priority_window(0)
    return game, host, aura


def test_w1g5_fatal_mutation_destroys_its_host_as_it_turns_up_unregenerated(set_pool):
    game, host, aura = _w1g5e_mutated(set_pool)
    host.regeneration_shield = 1
    assert _w1g5e_take(game, 0, host, "turn_face_up") is None
    # APNAP (CR 603.3b): B's Mutation above A's own Woodcloaker trigger.
    assert [item.card.name for item in game.stack] == ["Woodcloaker", "Fatal Mutation"]
    _w1g5e_resolve_stack(game)
    game.check_state_based_actions()
    a, b = game.players
    assert [card.name for card in a.graveyard] == ["Woodcloaker"]
    assert [card.name for card in b.graveyard] == ["Fatal Mutation"]
    assert "Fatal Mutation destroyed Woodcloaker" in game.log


def test_w1g5_fatal_mutation_answers_an_effect_turning_its_host_up(set_pool):
    """Any road up is the event (CR 708.7): an effect's turn (Ixidor's
    reading) sets it off as the special action does."""
    game, host, _aura = _w1g5e_mutated(set_pool, "Titanic Bulvox")
    assert _w1g5e_turn_face_up(game, host, how="an effect")
    assert [item.card.name for item in game.stack] == ["Fatal Mutation"]
    _w1g5e_resolve_stack(game)
    assert "Titanic Bulvox" in [card.name for card in game.players[0].graveyard]


def test_w1g5_fatal_mutation_ignores_another_permanent_turning_up(set_pool):
    """The Aura watches its own host, by identity — another face-down creature
    turned up beside it sets nothing off."""
    other = _w1g5e_permanent(set_pool("SCG")["Scornful Egotist"], face_down=True)
    game, host, _aura = _w1g5e_mutated(set_pool, extra_mine=(other,))
    assert _w1g5e_turn_face_up(game, other, how="an effect")
    assert game.stack == []
    assert any(p is host for p in game.controlled_by(0))

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

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.linked_exile import linked_entries as _w1g7_linked_entries
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_perm(card):
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_game(mine=(), theirs=(), *, library=None, hand=(), their_hand=()):
    library = list(library) if library is not None else []
    me = _W1G7PlayerState(
        name="P0", battlefield=[_w1g7_perm(c) for c in mine],
        library=list(library), hand=list(hand), life=20,
    )
    them = _W1G7PlayerState(
        name="P1", battlefield=[_w1g7_perm(c) for c in theirs],
        library=list(library), hand=list(their_hand), life=20,
    )
    game = _W1G7Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    return game


def _w1g7_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Sulfuric Vortex -------------------------------------------------------
#
# "If a player would gain life, that player gains no life instead." A CR 614
# replacement (614.1a), not CR 119.7's "can't gain life": the gain is replaced
# by nothing, so nothing is recorded or announced — and beside Lich's own
# replacement the gaining player chooses which applies (CR 616.1e).


def test_w1g7_sulfuric_vortex_replaces_every_players_life_gain(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    game = _w1g7_game(theirs=[vortex], hand=[nectar], their_hand=[nectar])
    me, them = game.players

    assert game.queue_from_hand(0, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    # "A player": the opponent of the Vortex's controller…
    assert me.life == 20 and me.life_gained_this_turn == 0
    assert any(
        "P0 would gain 4 life from Sacred Nectar; gains no life instead (Sulfuric Vortex)"
        in line for line in game.log
    )
    # …and its controller alike.
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    assert them.life == 20 and them.life_gained_this_turn == 0


def test_w1g7_sulfuric_vortex_deals_two_to_each_player_in_their_upkeep(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    forest = set_pool("2ED")["Forest"]
    game = _w1g7_game(mine=[vortex], library=[forest] * 6)
    game.turn = 2
    game.start_turn(0)
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 18 and game.players[1].life == 20
    game.start_turn(1)
    _w1g7_resolve_stack(game)
    assert game.players[1].life == 18


def test_w1g7_sulfuric_vortex_beside_lich_a_seat_nobody_asks_draws(set_pool):
    """CR 616.1e's default: both replacements consume the gain and the gaining
    player would take Lich's cards over nothing. A ban (Forsaken Wastes, CR
    119.7) would stop Lich too — which is the difference the card's wording
    makes."""
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    lich = set_pool("2ED")["Lich"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    forest = set_pool("2ED")["Forest"]
    game = _w1g7_game(mine=[lich, vortex], library=[forest] * 8, hand=[nectar])
    me = game.players[0]
    assert game.queue_from_hand(0, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    assert len(me.hand) == 4 and len(me.library) == 4
    assert me.life == 20 and me.life_gained_this_turn == 0


def test_w1g7_sulfuric_vortex_beside_lich_asks_the_gaining_player(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    lich = set_pool("2ED")["Lich"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    forest = set_pool("2ED")["Forest"]
    for pick, cards in (("Gain no life instead", 0), ("Lich", 4)):
        game = _w1g7_game(mine=[lich, vortex], library=[forest] * 8, hand=[nectar])
        game.interactive_seats = {0}
        me = game.players[0]
        assert game.queue_from_hand(0, "Sacred Nectar").supported
        game.resolve_top_of_stack()
        (asked,) = [c for c in game.pending_choices if c.kind == "effect_order"]
        assert asked.player_index == 0
        assert set(asked.data["options"]) == {"Lich", "Gain no life instead"}
        # Nothing has happened while the question is owed (CR 616.1).
        assert me.hand == [] and me.life == 20
        assert game.resolve_pending_choice(
            "effect_order", 0, option_index=asked.data["options"].index(pick)
        )
        _w1g7_resolve_stack(game)
        assert len(me.hand) == cards, pick
        assert me.life == 20 and me.life_gained_this_turn == 0
        assert not game.stack and not game.pending_choices


# --- Parallel Thoughts -------------------------------------------------------
#
# The entry trigger exiles seven cards in a face-down pile linked to the
# enchantment (CR 607.2a); "If you would draw a card, you may instead put the
# top card of the pile you exiled into your hand." Rulings (2004-10-04): fewer
# than seven exiles them all; an empty pile may still be "taken" from, which
# skips the draw; nobody may look at the face-down cards.


def _w1g7_thoughts_in_play(set_pool, library, *, interactive=False):
    thoughts = set_pool("SCG")["Parallel Thoughts"]
    game = _w1g7_game(library=library, hand=[thoughts])
    if interactive:
        game.interactive_seats = {0}
    assert game.queue_from_hand(0, "Parallel Thoughts").supported
    _w1g7_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, _w1g7_named(game, 0, "Parallel Thoughts")


def test_w1g7_parallel_thoughts_exiles_seven_face_down_and_hides_them(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 4 + [pool["Hill Giant"]] * 6
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library)
    me = game.players[0]
    pile = _w1g7_linked_entries(thoughts)
    assert len(pile) == 7 and all(entry.get("face_down") for entry in pile)
    assert len(me.exile) == 7 and len(me.library) == 3
    # game.log is every seat's: the find is a count, not a list of names.
    searched = [line for line in game.log if "searched library and exiled" in line]
    assert searched == ["P0 searched library and exiled 7 card(s) face down"]


def test_w1g7_parallel_thoughts_with_fewer_than_seven_exiles_them_all(set_pool):
    pool = set_pool("2ED")
    game, thoughts = _w1g7_thoughts_in_play(set_pool, [pool["Hill Giant"]] * 4)
    assert len(_w1g7_linked_entries(thoughts)) == 4
    assert game.players[0].library == []


def test_w1g7_parallel_thoughts_takes_the_pile_for_a_seat_nobody_asks(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 3 + [pool["Hill Giant"]] * 7
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library)
    me = game.players[0]
    library_before = list(me.library)
    pile_cards = [entry["card"] for entry in _w1g7_linked_entries(thoughts)]

    game.players[0].hand.append(set_pool("6ED")["Inspiration"])
    assert game.queue_from_hand(0, "Inspiration", target_player_index=0).supported
    _w1g7_resolve_stack(game)

    # Two draws replaced, one at a time (CR 121.2): the pile's top two came
    # to hand, the library is untouched, and neither was a draw.
    assert me.hand == pile_cards[:2]
    assert me.library == library_before
    assert len(_w1g7_linked_entries(thoughts)) == 5 and len(me.exile) == 5
    assert me.cards_drawn_this_turn == []
    took = [line for line in game.log if "goes from the exiled pile" in line]
    assert took == ["Parallel Thoughts: the top card goes from the exiled pile to P0's hand"] * 2


def test_w1g7_parallel_thoughts_asks_an_interactive_seat_each_draw(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 3 + [pool["Hill Giant"]] * 7
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library, interactive=True)
    me = game.players[0]
    pile_top = _w1g7_linked_entries(thoughts)[0]["card"]
    library_top = me.library[0]

    assert game._draw_with_replacements(me, 2) == 0
    (offer,) = game.pending_replacement_choices
    assert offer.kind == "pile_top_draw" and offer.player_index == 0
    # The offer names the pile, never the card in it.
    assert offer.options == (
        "draw the card", "put the top card of the exiled pile into your hand",
    )
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    # The second draw is its own offer, made once the first is decided.
    (second,) = game.pending_replacement_choices
    assert second.kind == "pile_top_draw"
    assert game.confirm_pile_top_draw(0, take_from_pile=False)
    assert game.pending_replacement_choices == []
    assert me.hand == [pile_top, library_top]
    assert me.cards_drawn_this_turn == [library_top]
    assert len(_w1g7_linked_entries(thoughts)) == 6


def test_w1g7_parallel_thoughts_empty_pile_skips_the_draw(set_pool):
    """"You can choose to take the top card from the pile (and not draw) even
    if there are no cards in the pile." A seat nobody asks does so only where
    the draw would come from an empty library."""
    pool = set_pool("2ED")
    thoughts = set_pool("SCG")["Parallel Thoughts"]
    # Asked: an empty pile, taken — nothing is drawn and nothing arrives.
    game = _w1g7_game(mine=[thoughts], library=[pool["Forest"]] * 3)
    game.interactive_seats = {0}
    me = game.players[0]
    game._draw_with_replacements(me, 1)
    (offer,) = game.pending_replacement_choices
    assert offer.options[1].endswith("(the pile is empty)")
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    assert me.hand == [] and len(me.library) == 3
    assert any("the exiled pile is empty" in line for line in game.log)
    # Not asked, a library to draw from: the draw.
    game = _w1g7_game(mine=[thoughts], library=[pool["Forest"]] * 3)
    game._draw_with_replacements(game.players[0], 1)
    assert game.players[0].hand == [pool["Forest"]]
    # Not asked, an empty library: the skip, and no loss (CR 704.5b).
    game = _w1g7_game(mine=[thoughts], library=[])
    game._draw_with_replacements(game.players[0], 1)
    game.check_state_based_actions()
    assert not game.players[0].lost


def test_w1g7_parallel_thoughts_contends_with_another_draw_replacement(set_pool):
    """CR 616.1e: beside Obstinate Familiar's optional skip, the drawing player
    chooses which applies first — and the declined one is offered after."""
    pool = set_pool("2ED")
    thoughts = _w1g7_perm(set_pool("SCG")["Parallel Thoughts"])
    familiar = set_pool("ODY")["Obstinate Familiar"]
    game = _w1g7_game(mine=[familiar], library=[pool["Forest"]] * 3)
    game.players[0].battlefield.append(thoughts)
    hill_giant = pool["Hill Giant"]
    game.players[0].exile.append(hill_giant)
    from engine.linked_exile import link_exiled_card

    link_exiled_card(thoughts, hill_giant, 0, face_down=True)
    game.interactive_seats = {0}
    me = game.players[0]
    game._draw_with_replacements(me, 1)
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    pick = order.data["options"].index(
        "Put the top card of the exiled pile into your hand instead"
    )
    assert game.resolve_pending_choice("effect_order", 0, option_index=pick)
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    assert me.hand == [hill_giant] and len(me.library) == 3
    assert game.pending_replacement_choices == [] and game.pending_choices == []


# --- Upwelling --------------------------------------------------------------
#
# "Players don't lose unspent mana as steps and phases end." CR 500.5's
# emptying switched off while it is on the battlefield; ruling 2009-10-01:
# "once it leaves the battlefield, they have until the end of the current step
# (or phase) to use the mana before it disappears."


def test_w1g7_upwelling_keeps_every_players_mana_until_it_leaves(set_pool):
    upwelling = set_pool("SCG")["Upwelling"]
    pool = set_pool("2ED")
    disenchant = pool["Disenchant"]
    game = _w1g7_game(
        mine=[upwelling], library=[pool["Forest"]] * 8, their_hand=[disenchant],
    )
    game.turn = 2
    me, them = game.players
    me.mana_pool["G"] = 3
    them.mana_pool["R"] = 1
    # Through P0's end and cleanup steps and P1's whole beginning phase.
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    game.start_next_turn()
    assert game.active_player_index == 1
    assert me.mana_pool["G"] == 3 and them.mana_pool["R"] == 1

    # Gone in P1's main phase: the mana stays until that phase ends…
    assert game.queue_from_hand(
        1, "Disenchant",
        target_permanent_ids=[_w1g7_named(game, 0, "Upwelling").permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert [c.name for c in me.graveyard] == ["Upwelling"]
    assert me.mana_pool["G"] == 3
    # …and empties as it ends.
    game._on_step_or_phase_end("precombat_main", "precombat_main")
    assert me.mana_pool["G"] == 0 and them.mana_pool["R"] == 0


def test_w1g7_upwelling_mana_pays_for_a_spell_a_step_later(set_pool):
    upwelling = set_pool("SCG")["Upwelling"]
    pool = set_pool("2ED")
    game = _w1g7_game(mine=[upwelling], library=[pool["Forest"]] * 8,
                      hand=[pool["Grizzly Bears"]])
    game.enforce_mana_costs = True
    me = game.players[0]
    me.mana_pool["G"] = 2
    game._on_step_or_phase_end("precombat_main", "precombat_main")
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g7_resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert me.mana_pool["G"] == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Grip of Chaos: "Whenever a spell or ability is put onto the stack, if it has
# a single target, reselect its target at random. (Select from among all legal
# targets.)" A new event (`Game.announce_put_onto_stack`), CR 603.4's
# intervening-if over CR 115.9a's count, and Psychic Battle's change of the
# event's object made by the seeded RNG.
import random as _w1g8_random

from engine import Game as _W1G8Game
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_table(set_pool, hand=(), *, bob_hand=(), interactive=False):
    lea = set_pool("LEA")
    alice = _W1G8PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G8PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G8Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g8_put(game, seat, card):
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g8_drain(game):
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_grip_triggers(game):
    return [
        item for item in game.stack
        if item.card.name == "Grip of Chaos" and item.ability_kind == "triggered"
    ]


def _w1g8_bolt_outcome(game, alice, bob, bears, elves):
    """Where the Bolt's 3 damage went."""
    if bears.damage_marked == 3:
        return "bears"
    if elves.damage_marked == 3:
        return "elves"
    if alice.life == 17:
        return "alice"
    if bob.life == 17:
        return "bob"
    return None


def test_w1g8_grip_of_chaos_reselects_a_single_target_among_every_legal_one(set_pool):
    """Each seeded game puts Grip's trigger above a Lightning Bolt aimed at
    Bob's Bears; as it resolves, the Bolt's target is drawn from every legal
    target — both players and both creatures — and the original is one of the
    answers (2004-10-04: "it may still choose the original one"). Over a dozen
    seeds every answer is legal, the original is kept at least once and the
    Bolt is moved at least once; one seed always gives one answer."""
    lea = set_pool("LEA")
    outcomes = []
    for seed in range(12):
        game, alice, bob = _w1g8_table(set_pool, [lea["Lightning Bolt"]])
        _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        elves = _w1g8_put(game, 0, lea["Llanowar Elves"])
        assert game.queue_from_hand(
            0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        # The Bolt keeps its target until the trigger resolves (2004-10-04).
        assert len(_w1g8_grip_triggers(game)) == 1
        assert game.stack[0].target_permanent_id == [bears.permanent_id]
        _w1g8_random.seed(seed)
        _w1g8_drain(game)
        outcomes.append(_w1g8_bolt_outcome(game, alice, bob, bears, elves))
    assert None not in outcomes
    assert "bears" in outcomes
    assert set(outcomes) - {"bears"}

    again = []
    for _ in range(2):
        game, alice, bob = _w1g8_table(set_pool, [lea["Lightning Bolt"]])
        _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        elves = _w1g8_put(game, 0, lea["Llanowar Elves"])
        game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
        _w1g8_random.seed(7)
        _w1g8_drain(game)
        again.append(_w1g8_bolt_outcome(game, alice, bob, bears, elves))
    assert again[0] == again[1]


def test_w1g8_grip_of_chaos_keeps_a_target_with_no_other_legal_one(set_pool):
    """2004-10-04: "If there are no other legal targets, it keeps its
    target." Terror's only legal creature is the one it named."""
    lea = set_pool("LEA")
    game, _alice, _bob = _w1g8_table(set_pool, [lea["Terror"]])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_drain(game)
    assert not game.is_on_battlefield(bears)
    assert any("has no other legal target" in line for line in game.log)


def test_w1g8_grip_of_chaos_reselects_among_the_targets_legal_as_it_resolves(set_pool):
    """2004-10-04: "You determine the new target when this ability resolves,
    at which time the set of legal targets may have changed." Alice gains
    shroud in response (Gilded Light, which targets nothing and so is not
    reselected itself): no seed sends Bob's Bolt at her."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    for seed in range(8):
        game, alice, bob = _w1g8_table(
            set_pool, [scg["Gilded Light"]], bob_hand=[lea["Lightning Bolt"]],
        )
        _w1g8_put(game, 0, scg["Grip of Chaos"])
        bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        assert game.queue_from_hand(0, "Gilded Light").supported
        assert len(_w1g8_grip_triggers(game)) == 1
        _w1g8_random.seed(seed)
        _w1g8_drain(game)
        assert alice.life == 20, seed
        assert bears.damage_marked == 3 or bob.life == 17


def test_w1g8_grip_of_chaos_ignores_what_has_no_single_target(set_pool):
    """An untargeted spell, a spell with two targets and Grip's own trigger do
    not set it off (CR 603.4: the condition is false, so it never triggers) —
    which is also why two Grips do not loop. One target of an "up to two"
    does."""
    lea = set_pool("LEA")
    lead_astray = set_pool("JUD")["Lead Astray"]
    game, _alice, _bob = _w1g8_table(set_pool, [lea["Wrath of God"], lead_astray, lead_astray])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    elves = _w1g8_put(game, 1, lea["Llanowar Elves"])
    assert game.queue_from_hand(0, "Wrath of God").supported
    assert _w1g8_grip_triggers(game) == []
    game.stack.clear()
    assert game.queue_from_hand(
        0, "Lead Astray", target_permanent_ids=[bears.permanent_id, elves.permanent_id],
    ).supported
    assert _w1g8_grip_triggers(game) == []
    game.stack.clear()
    assert game.queue_from_hand(
        0, "Lead Astray", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert len(_w1g8_grip_triggers(game)) == 2
    _w1g8_drain(game)
    assert game.stack == []


def test_w1g8_grip_of_chaos_reaches_an_activated_ability(set_pool):
    """"…a spell **or ability**": Prodigal Sorcerer's ping is put onto the
    stack with one target and is reselected like a spell."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g8_table(set_pool)
    _w1g8_put(game, 0, set_pool("SCG")["Grip of Chaos"])
    _w1g8_put(game, 0, lea["Prodigal Sorcerer"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id], ability_index=0,
    ).supported
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_random.seed(1)
    _w1g8_drain(game)
    assert any("Prodigal Sorcerer" in line and "Grip of Chaos" in line for line in game.log)
    assert bears.damage_marked + (20 - alice.life) + (20 - bob.life) + sum(
        perm.damage_marked for perm in game.controlled_by(0)
    ) == 1


def test_w1g8_grip_of_chaos_trigger_can_be_stifled(set_pool):
    """The reselection is a triggered ability on the stack (the third
    ruling), so Stifle counters it and the Bolt keeps its target. Stifle has a
    single target itself, so it sets Grip off too — and the only other legal
    target for it is nothing, so that trigger keeps it."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    game, _alice, bob = _w1g8_table(
        set_pool, [lea["Lightning Bolt"]], bob_hand=[scg["Stifle"]],
    )
    _w1g8_put(game, 0, scg["Grip of Chaos"])
    bears = _w1g8_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    # Bottom-first: the Bolt is 0, Grip's trigger 1.
    assert game.queue_from_hand(1, "Stifle", target_stack_index=1).supported
    assert len(_w1g8_grip_triggers(game)) == 2
    _w1g8_random.seed(0)
    _w1g8_drain(game)
    assert bears.damage_marked == 3
    assert any("Stifle countered Grip of Chaos" in line for line in game.log)


def test_w1g8_grip_of_chaos_hears_a_trigger_whose_target_a_person_chose(set_pool):
    """A triggered ability is put onto the stack once its controller names
    its target (CR 603.3d): Decree of Savagery's cycle trigger, aimed by a
    person, sets Grip off only after the answer — and Grip moves the four
    counters among the creatures."""
    lea = set_pool("LEA")
    scg = set_pool("SCG")
    game, _alice, _bob = _w1g8_table(set_pool, [scg["Decree of Savagery"]], interactive=True)
    _w1g8_put(game, 0, scg["Grip of Chaos"])
    mine = _w1g8_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g8_put(game, 1, lea["Llanowar Elves"])
    assert game.activate_from_hand(0, "Decree of Savagery").supported
    assert game.pending_choice_of("trigger_target", 0) is not None
    assert _w1g8_grip_triggers(game) == []
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=theirs.permanent_id,
    )
    assert len(_w1g8_grip_triggers(game)) == 1
    _w1g8_random.seed(2)
    _w1g8_drain(game)
    assert any("Grip of Chaos" in line and "Decree of Savagery" in line for line in game.log)

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Faces of the Past's choice made as its death trigger resolves, read off the
# dead creature as it last existed; Unspeakable Symbol (supported on arrival)
# driven.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import counters_on as _w1g9_counters_on
from engine.type_changes import gain_types as _w1g9_gain_types
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_permanent(card, *, tapped=False):
    permanent = _W1G9Permanent(card=card, tapped=tapped)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_game(mine=(), theirs=(), *, interactive=False):
    p1 = _W1G9PlayerState(name="A", battlefield=list(mine),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g9_elf_board(set_pool, *, interactive):
    """Faces of the Past and an Elf on seat 0; on seat 1 an untapped Elf, a
    tapped Elf and an untapped Bear."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    untapped_elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    tapped_elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"], tapped=True)
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game(
        [faces, dying], [untapped_elf, tapped_elf, bear], interactive=interactive,
    )
    return game, dying, untapped_elf, tapped_elf, bear


@_w1g9_pytest.mark.parametrize("mode", [0, 1])
def test_w1g9_faces_of_the_past_asks_tap_or_untap_as_it_resolves(set_pool, mode):
    """"Whenever a creature dies, tap all untapped creatures that share a
    creature type with it or untap all tapped creatures that share a creature
    type with it." The 2004-10-04 rulings: the choice is made on resolution,
    and it is all of one or all of the other. An Elf dies: tapping taps the
    untapped Elf, untapping untaps the tapped one, and the Bear (no shared
    type) is never touched."""
    game, dying, untapped_elf, tapped_elf, bear = _w1g9_elf_board(set_pool, interactive=True)
    game.sacrifice_permanent(dying)
    assert [item.card.name for item in game.stack] == ["Faces of the Past"]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [item.card.name for item in game.stack] == ["Faces of the Past"], (
        "held on the stack for the choice (CR 608.2)"
    )
    (choice,) = game.pending_choices_of("mode_choice", 0)
    assert len(choice.data["labels"]) == 2
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode)
    _w1g9_resolve_stack(game)
    if mode == 0:
        assert untapped_elf.tapped and tapped_elf.tapped
    else:
        assert not untapped_elf.tapped and not tapped_elf.tapped
    assert not bear.tapped
    assert not game.stack and not game.pending_choices


def test_w1g9_faces_of_the_past_default_taps(set_pool):
    """A seat nobody asks takes the first printed alternative, the tap."""
    game, dying, untapped_elf, tapped_elf, bear = _w1g9_elf_board(set_pool, interactive=False)
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert untapped_elf.tapped and tapped_elf.tapped and not bear.tapped
    assert any(
        'Faces of the Past: chose "tap all untapped creatures' in line for line in game.log
    )


def test_w1g9_faces_of_the_past_reads_the_dead_creatures_last_known_types(set_pool):
    """"It" is the creature that died, as it last existed on the battlefield
    (CR 608.2h): a Bear an effect had made a Goblin dies a Goblin, so the
    Goblin is tapped and the other Bear is not."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    _w1g9_gain_types(
        dying, subtypes=["goblin"], source="test", duration="permanent",
        replaces_creature_types=True,
    )
    goblin = _w1g9_permanent(_W1G9_CATALOG["Raging Goblin"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([faces, dying], [goblin, bear])
    assert dying.has_type("goblin") and not dying.has_type("bear")
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert goblin.tapped
    assert not bear.tapped


def test_w1g9_faces_of_the_past_with_nobody_of_the_type_turns_nothing(set_pool):
    """A creature that shares a type with nothing on the battlefield taps
    nothing — the relation is never dropped into "every creature"."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    game, _p1, _p2 = _w1g9_game([faces, dying], [elf])
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert not elf.tapped
    assert any("Faces of the Past: nothing to tap or untap" in line for line in game.log)


# --- Supported on arrival, driven: Unspeakable Symbol ---------------------------


def test_w1g9_unspeakable_symbol_buys_a_counter_with_three_life(set_pool):
    """"Pay 3 life: Put a +1/+1 counter on target creature." Paid at 20, and
    refused at 2 life (CR 119.4) with nothing paid."""
    symbol = _w1g9_permanent(set_pool("SCG")["Unspeakable Symbol"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, p1, _p2 = _w1g9_game([symbol, bear])
    result = game.activate_permanent_ability(
        0, "Unspeakable Symbol", ability_index=0, target_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert p1.life == 17 and _w1g9_counters_on(bear, "+1/+1") == 1
    p1.life = 2
    refused = game.activate_permanent_ability(
        0, "Unspeakable Symbol", ability_index=0, target_permanent_ids=[bear.permanent_id],
    )
    assert not refused.supported
    assert p1.life == 2 and _w1g9_counters_on(bear, "+1/+1") == 1

# ==== end W1G9 ======================================================
