"""Mirrodin creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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
# Equipment from the creature's side ("As long as this creature is
# equipped", Auriok Steelshaper's equip discount, Vulshok Battlemaster) and
# the "becomes blocked" creatures (Ogre Leadfoot, Groffskithur), each driven
# through the engine's own activation, cast and combat entry points.
import dataclasses as _w1g2_dataclasses

from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.keywords import grant_protection_flag as _w1g2_grant_protection
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState
from engine.oracle import compile_card_oracle as _w1g2_compile

from tests.helpers import _mk_creature_card as _w1g2_creature_card
from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand=(), enforce=False):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = enforce
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
    _w1g2_resolve_stack(game)
    return permanent


def _w1g2_equip(game, seat, equipment, creature):
    """Activate *equipment*'s equip ability onto *creature* and resolve it."""
    result = game.activate_permanent_ability(
        seat, equipment.card.name,
        permanent_index=game.battlefield_index_of(equipment),
        target_permanent_ids=[creature.permanent_id],
    )
    _w1g2_resolve_stack(game)
    return result


def _w1g2_equip_price(game, seat, equipment) -> int:
    """The mana the equip ability charges, from the one charger every reader
    asks (``Game.activation_mana_charge``)."""
    ability = _w1g2_compile(equipment.card).activated_abilities[0]
    charge = game.activation_mana_charge(seat, equipment, ability)
    assert not isinstance(charge, str), charge
    return sum(charge[0].values())


def test_w1g2_skyhunter_cub_flies_exactly_while_equipped(set_pool):
    """"As long as this creature is equipped, it gets +1/+1 and has flying."
    CR 301.5a: equipped means an Equipment is attached. The bonus turns on as
    the equip ability resolves and off as the Equipment moves to another
    creature, and an Aura (enchanted, not equipped) does not turn it on."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool)
    cub = _w1g2_put(game, 0, mrd["Skyhunter Cub"])
    bear = _w1g2_put(game, 0, lea["Grizzly Bears"])
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    assert (cub.effective_power, cub.effective_toughness) == (2, 2)
    assert not cub.has_keyword("flying")

    holy = _w1g2_put(game, 0, lea["Holy Strength"])
    _w1g2_attach_aura(holy, cub)
    game._recompute_continuous_effects()
    assert not cub.has_keyword("flying"), "an Aura does not equip"
    assert (cub.effective_power, cub.effective_toughness) == (3, 4)

    _w1g2_equip(game, 0, scimitar, cub)
    assert scimitar.metadata.get("attached_to") is cub
    # Printed 2/2, Holy Strength +1/+2, Scimitar +1/+1, the Cub's own +1/+1.
    assert (cub.effective_power, cub.effective_toughness) == (5, 6)
    assert cub.has_keyword("flying")

    _w1g2_equip(game, 0, scimitar, bear)
    assert scimitar.metadata.get("attached_to") is bear
    assert (cub.effective_power, cub.effective_toughness) == (3, 4)
    assert not cub.has_keyword("flying")


def test_w1g2_leonin_den_guard_attacks_without_tapping_while_equipped(set_pool):
    """"As long as this creature is equipped, it gets +1/+1 and has
    vigilance." Unequipped it taps to attack; equipped it does not (CR
    702.20b) and is a 3/5 with Leonin Scimitar's +1/+1 and its own."""
    mrd = set_pool("MRD")
    game, _alice, _bob = _w1g2_table(set_pool)
    guard = _w1g2_put(game, 0, mrd["Leonin Den-Guard"])
    _w1g2_declare_attack(game, 0)
    assert guard.tapped, "unequipped, the Den-Guard has no vigilance"

    game, _alice, _bob = _w1g2_table(set_pool)
    guard = _w1g2_put(game, 0, mrd["Leonin Den-Guard"])
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    _w1g2_equip(game, 0, scimitar, guard)
    assert (guard.effective_power, guard.effective_toughness) == (3, 5)
    _w1g2_declare_attack(game, 0)
    assert guard.attacking and not guard.tapped


def test_w1g2_auriok_steelshaper_discounts_its_controllers_equip_costs(set_pool):
    """"Equip costs you pay cost {1} less." CR 702.6a makes equip an
    activated ability and CR 602.2b its activation cost the 601.2f cost a
    reduction applies to: Leonin Scimitar's Equip {1} is free and resolves
    from an empty pool, Vulshok Battlegear's {3} costs {2}, and the
    opponent's equip is not discounted ("you pay")."""
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g2_table(set_pool, enforce=True)
    _w1g2_put(game, 0, mrd["Auriok Steelshaper"])
    knight = _w1g2_put(game, 0, mrd["Skyhunter Cub"])
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    battlegear = _w1g2_put(game, 0, mrd["Vulshok Battlegear"])
    assert _w1g2_equip_price(game, 0, scimitar) == 0
    assert _w1g2_equip_price(game, 0, battlegear) == 2

    assert not any(alice.mana_pool.values())
    result = _w1g2_equip(game, 0, scimitar, knight)
    assert scimitar.metadata.get("attached_to") is knight, result
    assert any("cheapened by Auriok Steelshaper" in line for line in game.log)

    bobs_scimitar = _w1g2_put(game, 1, mrd["Leonin Scimitar"])
    assert _w1g2_equip_price(game, 1, bobs_scimitar) == 1


def test_w1g2_auriok_steelshaper_discount_is_only_for_equip_abilities(set_pool):
    """The discount names the keyword (CR 702.6a's rewrite run backwards,
    ``equipment.is_equip_ability``): an ability printing the same words
    without the word "Equip" is not an equip ability and pays in full; and
    with the Steelshaper gone the Scimitar pays its {1} again."""
    mrd = set_pool("MRD")
    game, _alice, _bob = _w1g2_table(set_pool, enforce=True)
    steelshaper = _w1g2_put(game, 0, mrd["Auriok Steelshaper"])
    lookalike = _w1g2_put(game, 0, _w1g2_dataclasses.replace(
        mrd["Leonin Scimitar"], name="Test Unkeyworded Scimitar",
        oracle_text=(
            "Equipped creature gets +1/+1.\n"
            "{1}: Attach this permanent to target creature you control. "
            "Activate only as a sorcery."
        ),
    ))
    assert _w1g2_equip_price(game, 0, lookalike) == 1
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    assert _w1g2_equip_price(game, 0, scimitar) == 0
    game.remove_from_battlefield(steelshaper)
    assert _w1g2_equip_price(game, 0, scimitar) == 1


def test_w1g2_auriok_steelshaper_lord_holds_while_it_is_equipped(set_pool):
    """"As long as this creature is equipped, each creature you control
    that's a Soldier or a Knight gets +1/+1." One set, either type — a
    Soldier Knight is buffed once (CR 611.3a) — your creatures only, and only
    while the Steelshaper itself wears an Equipment."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool)
    steelshaper = _w1g2_put(game, 0, mrd["Auriok Steelshaper"])   # Human Soldier
    cub = _w1g2_put(game, 0, mrd["Skyhunter Cub"])                # Cat Knight
    den_guard = _w1g2_put(game, 0, mrd["Leonin Den-Guard"])       # Cat Soldier
    bear = _w1g2_put(game, 0, lea["Grizzly Bears"])
    both = _w1g2_put(game, 0, _w1g2_dataclasses.replace(
        _w1g2_creature_card("Test Soldier Knight", 1, 1),
        type_line="Creature — Soldier Knight",
    ))
    bobs_soldier = _w1g2_put(game, 1, mrd["Leonin Den-Guard"])
    baseline = {
        p.permanent_id: (p.effective_power, p.effective_toughness)
        for p in (steelshaper, cub, den_guard, bear, both, bobs_soldier)
    }

    def delta(permanent):
        before = baseline[permanent.permanent_id]
        return (permanent.effective_power - before[0],
                permanent.effective_toughness - before[1])

    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    assert delta(cub) == (0, 0), "unequipped, no lord"
    _w1g2_equip(game, 0, scimitar, steelshaper)
    assert delta(steelshaper) == (2, 2)      # the Scimitar and its own lord
    assert delta(cub) == (1, 1)
    assert delta(den_guard) == (1, 1)
    assert delta(both) == (1, 1), "a Soldier Knight is one member of the set"
    assert delta(bear) == (0, 0)
    assert delta(bobs_soldier) == (0, 0)

    _w1g2_equip(game, 0, scimitar, bear)
    assert delta(cub) == (0, 0) and delta(den_guard) == (0, 0)
    assert delta(steelshaper) == (0, 0)
    assert delta(bear) == (1, 1)             # the Scimitar alone


def test_w1g2_vulshok_battlemaster_takes_every_equipment_on_the_battlefield(set_pool):
    """"When this creature enters, attach all Equipment on the battlefield to
    it." Rulings (2004-12-01): every Equipment moves whether or not it was
    attached, "Other players' Equipment is moved onto the Battlemaster as well
    as your own. This doesn't change who controls the Equipment". The entry
    trigger is a stack object (CR 603.3), driven through a real cast."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool, hand=[mrd["Vulshok Battlemaster"]])
    bear = _w1g2_put(game, 0, lea["Grizzly Bears"])
    bobs_bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    bonesplitter = _w1g2_put(game, 0, mrd["Bonesplitter"])
    bobs_battlegear = _w1g2_put(game, 1, mrd["Vulshok Battlegear"])
    _w1g2_attach_aura(bonesplitter, bear)
    _w1g2_attach_aura(bobs_battlegear, bobs_bear)
    game._recompute_continuous_effects()

    result = game.cast_from_hand(0, "Vulshok Battlemaster")
    assert result.supported, result
    _w1g2_resolve_stack(game)
    battlemaster = next(
        p for p in game.controlled_by(0) if p.card.name == "Vulshok Battlemaster"
    )
    for equipment in (scimitar, bonesplitter, bobs_battlegear):
        assert equipment.metadata.get("attached_to") is battlemaster, equipment.card.name
    assert game.controller_index_of(bobs_battlegear) == 1
    # Printed 2/2 + Scimitar +1/+1 + Bonesplitter +2/+0 + Battlegear +3/+3.
    assert (battlemaster.effective_power, battlemaster.effective_toughness) == (8, 6)
    assert (bear.effective_power, bobs_bear.effective_power) == (2, 2)
    # Bob still controls the Battlegear, so its equip ability is his to move.
    assert _w1g2_equip(game, 1, bobs_battlegear, bobs_bear) is not None


def test_w1g2_vulshok_battlemaster_leaves_an_equipment_that_cannot_equip_it(set_pool):
    """The ruling's other half (2004-12-01): "If an Equipment can't equip
    Vulshok Battlemaster, it isn't attached to the Battlemaster, and it
    doesn't become unattached." Protection from artifacts granted while the
    entry trigger waits (CR 702.16d) — the response window CR 603.3 opens."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool, hand=[mrd["Vulshok Battlemaster"]])
    bear = _w1g2_put(game, 0, lea["Grizzly Bears"])
    scimitar = _w1g2_put(game, 0, mrd["Leonin Scimitar"])
    _w1g2_attach_aura(scimitar, bear)
    game._recompute_continuous_effects()
    queued = game.queue_from_hand(0, "Vulshok Battlemaster")
    assert queued.supported, queued.details
    game.resolve_top_of_stack()
    battlemaster = next(
        p for p in game.controlled_by(0) if p.card.name == "Vulshok Battlemaster"
    )
    assert [item.card.name for item in game.stack] == ["Vulshok Battlemaster"]
    _w1g2_grant_protection(battlemaster, "artifacts")
    _w1g2_resolve_stack(game)
    assert scimitar.metadata.get("attached_to") is bear
    assert any("Leonin Scimitar doesn't move" in line for line in game.log)


def test_w1g2_ogre_leadfoot_destroys_only_an_artifact_creature_blocking_it(set_pool):
    """"Whenever this creature becomes blocked by an artifact creature,
    destroy that creature." The narrowing is the trigger's: a nonartifact
    blocker does not trigger it (the line compiled as a bare "becomes
    blocked" and destroyed any blocker)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool)
    _w1g2_put(game, 0, mrd["Ogre Leadfoot"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    assert not any(item.card.name == "Ogre Leadfoot" for item in game.stack)
    _w1g2_resolve_stack(game)
    assert game.is_on_battlefield(bears)

    game, _alice, bob = _w1g2_table(set_pool)
    ogre = _w1g2_put(game, 0, mrd["Ogre Leadfoot"])
    ram = _w1g2_put(game, 1, mrd["Rustspore Ram"])          # Artifact Creature
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    assert any(item.card.name == "Ogre Leadfoot" for item in game.stack)
    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(ram)
    assert [card.name for card in bob.graveyard] == ["Rustspore Ram"]
    assert game.is_on_battlefield(ogre)


def _w1g2_groffskithur_combat(set_pool, graveyard, *, interactive):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool)
    alice.graveyard = list(graveyard)
    _w1g2_put(game, 0, mrd["Groffskithur"])
    _w1g2_put(game, 1, lea["Grizzly Bears"])
    if interactive:
        game.interactive_seats = {0}
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            _w1g2_resolve_stack(game)
        else:
            break
    return game, alice


def test_w1g2_groffskithur_returns_a_card_named_groffskithur(set_pool):
    """"Whenever this creature becomes blocked, you may return target card
    named Groffskithur from your graveyard to your hand." The name is a
    filter (CR 201.2): with another card beside it in the graveyard only the
    Groffskithur comes back, for a seat nobody asks and an interactive one."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for interactive in (False, True):
        game, alice = _w1g2_groffskithur_combat(
            set_pool, [lea["Grizzly Bears"], mrd["Groffskithur"]],
            interactive=interactive,
        )
        assert [card.name for card in alice.hand] == ["Groffskithur"], interactive
        assert [card.name for card in alice.graveyard] == ["Grizzly Bears"]


def test_w1g2_groffskithur_with_no_groffskithur_in_the_graveyard_returns_nothing(set_pool):
    """With only another card in the graveyard there is no legal target, so
    nothing comes back (CR 603.3d) — never the card that is there."""
    lea = set_pool("LEA")
    game, alice = _w1g2_groffskithur_combat(
        set_pool, [lea["Grizzly Bears"]], interactive=False,
    )
    assert alice.hand == []
    assert [card.name for card in alice.graveyard] == ["Grizzly Bears"]


def test_w1g2_groffskithur_picker_offers_only_the_named_card(set_pool):
    """The graveyard picker is derived from the compiled payload: the name
    rides it (``graveyard_named``), so a client offering targets is offered
    the Groffskithur and not the Bears beside it."""
    from engine.payload_target_specs import _graveyard_return_spec

    program = _w1g2_compile(set_pool("MRD")["Groffskithur"])
    step = program.triggered_abilities[0].instruction.payload["action"][0]
    spec = _graveyard_return_spec(step.payload)
    assert spec["graveyard_named"] == "groffskithur"
    from engine.handlers._filters import graveyard_card_matches

    lea, mrd = set_pool("LEA"), set_pool("MRD")
    assert graveyard_card_matches(spec, mrd["Groffskithur"])
    assert not graveyard_card_matches(spec, lea["Grizzly Bears"])


def _w1g2_drain(game):
    """Answer what blocks the game and drain the stack, until nothing does."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            _w1g2_resolve_stack(game)
        else:
            return


def test_w1g2_taj_nar_swordsmith_pays_x_and_fetches_an_equipment_of_that_value(set_pool):
    """Drive list: "When this creature enters, you may pay {X}. If you do,
    search your library for an Equipment card with mana value X or less, put
    that card onto the battlefield, then shuffle." A person pays X = 2 from
    the pool through the ``pay_any_amount`` prompt; the search is held to
    Equipment of mana value 2 or less (Leonin Scimitar, not the three-mana
    Battlegear), and the card enters the battlefield."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool, hand=[mrd["Taj-Nar Swordsmith"]], enforce=True)
    alice.library = [lea["Plains"], mrd["Vulshok Battlegear"], mrd["Leonin Scimitar"], lea["Plains"]]
    alice.mana_pool.update({"W": 1, "C": 5})
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Taj-Nar Swordsmith").supported
    for _ in range(5):
        kinds = [choice.kind for choice in game.pending_choices]
        if "pay_any_amount" in kinds:
            assert game.confirm_pay_any_amount(0, 2)
        elif kinds:
            break
        elif game.stack:
            game.resolve_top_of_stack()
    assert [choice.kind for choice in game.pending_choices] == ["search_library"]
    assert game.pending_choices[0].data["restrictions"]["mana_value"] == {"op": "le", "value": 2}
    _w1g2_drain(game)
    on_board = sorted(p.card.name for p in game.controlled_by(0))
    assert on_board == ["Leonin Scimitar", "Taj-Nar Swordsmith"]
    assert sum(alice.mana_pool.values()) == 0, "{3}{W} for the creature, {2} for X"
    assert sorted(c.name for c in alice.library) == ["Plains", "Plains", "Vulshok Battlegear"]


def test_w1g2_slith_strider_draws_when_blocked_and_grows_on_player_damage(set_pool):
    """Drive list: "Whenever this creature becomes blocked, draw a card."
    and "Whenever this creature deals combat damage to a player, put a +1/+1
    counter on it." """
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool)
    _w1g2_put(game, 0, mrd["Slith Strider"])
    _w1g2_put(game, 1, lea["Grizzly Bears"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]

    game, alice, bob = _w1g2_table(set_pool)
    strider = _w1g2_put(game, 0, mrd["Slith Strider"])
    _w1g2_declare_attack(game, 0)
    _w1g2_drain(game)
    assert alice.hand == [], "unblocked, it does not draw"
    game.advance_combat_phase()
    _w1g2_drain(game)
    assert bob.life == 19
    assert (strider.effective_power, strider.effective_toughness) == (2, 2)


def test_w1g2_psychic_membrane_may_draw_when_it_blocks(set_pool):
    """Drive list: "Defender / Whenever this creature blocks, you may draw a
    card." The Wall's controller draws as it blocks (the headless seat takes
    the offer), and it cannot attack (CR 702.3b)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool)
    _w1g2_put(game, 0, lea["Grizzly Bears"])
    membrane = _w1g2_put(game, 1, mrd["Psychic Membrane"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    _w1g2_drain(game)
    assert [c.name for c in bob.hand] == ["Island"]
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(1, [game.battlefield_index_of(membrane)], defending_player_index=0)
    assert not ok, "defender: it can't attack"


def test_w1g2_the_ai_equips_for_the_price_steelshaper_leaves(set_pool):
    """The AI's planner prices an activation through the engine's charger
    (``Game.activation_mana_charge``), not the printed cost: with Auriok
    Steelshaper out and no land to tap, Leonin Scimitar's equip costs {0} and
    the AI proposes it; without the Steelshaper the same board offers no
    equip at all, because {1} cannot be paid."""
    from engine.ai_abilities import choose_activation_action

    mrd = set_pool("MRD")
    for with_steelshaper in (True, False):
        game, _alice, _bob = _w1g2_table(set_pool, enforce=True)
        if with_steelshaper:
            _w1g2_put(game, 0, mrd["Auriok Steelshaper"])
        _w1g2_put(game, 0, mrd["Leonin Den-Guard"])
        _w1g2_put(game, 0, mrd["Leonin Scimitar"])
        action = choose_activation_action(game, 0)
        proposed = action is not None and action.permanent_name == "Leonin Scimitar"
        assert proposed is with_steelshaper, (with_steelshaper, action)
        if proposed:
            assert action.land_tap_indices == ()

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
