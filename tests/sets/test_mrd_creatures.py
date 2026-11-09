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

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def test_w1g1_loxodon_punisher_grows_with_each_equipment_and_shrinks_when_one_moves(set_pool):
    """'This creature gets +2/+2 for each Equipment attached to it.' Equipped
    twice through the real equip ability, then one Equipment moves away."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    island = lea["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    def put(card):
        permanent = _W1G1Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        game._settle()
        return permanent

    def equip(gear, creature):
        result = game.activate_permanent_ability(
            0, gear.card.name, permanent_index=game.battlefield_index_of(gear),
            target_permanent_ids=[creature.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        game._settle()

    punisher = put(mrd["Loxodon Punisher"])
    bears = put(lea["Grizzly Bears"])
    scimitar = put(mrd["Leonin Scimitar"])
    splitter = put(mrd["Bonesplitter"])
    assert (punisher.effective_power, punisher.effective_toughness) == (2, 2)
    equip(scimitar, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (5, 5)
    equip(splitter, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (9, 7)
    equip(scimitar, bears)
    assert (punisher.effective_power, punisher.effective_toughness) == (6, 4)

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


def test_w1g2_taj_nar_swordsmith_seat_nobody_asks_pays_what_it_can(set_pool):
    """The same trigger for a seat nobody asks: the default pays what the
    board can (``ai_prompts.choose_amount_paid`` — a search widened by X is
    worth every mana, the library being hidden, CR 401.2), so the {2} left
    in the pool fetches the Scimitar. It used to pay nothing and search for
    mana value 0."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool, hand=[mrd["Taj-Nar Swordsmith"]], enforce=True)
    alice.library = [lea["Plains"], mrd["Vulshok Battlegear"], mrd["Leonin Scimitar"], lea["Plains"]]
    alice.mana_pool.update({"W": 1, "C": 5})
    assert game.cast_from_hand(0, "Taj-Nar Swordsmith").supported
    _w1g2_drain(game)
    assert any("Alice paid 2 mana" in line for line in game.log)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Leonin Scimitar", "Taj-Nar Swordsmith",
    ]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_table(set_pool, hand=(), mine=()):
    """Seat 0's turn, mana costs enforced (affinity changes a price), every
    permanent past summoning sickness."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd[n] for n in hand]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = 0
    w1g3_row = []
    for w1g3_name in mine:
        w1g3_perm = _W1G3Permanent(card=mrd[w1g3_name])
        w1g3_game._put_permanent_onto_battlefield(0, w1g3_perm, None)
        w1g3_perm.metadata["summoning_sickness_turn"] = -99
        w1g3_row.append(w1g3_perm)
    return w1g3_game, w1g3_row  # _w1g3_table


def _w1g3_tap_blue(game, count):
    """Tap *count* of seat 0's Seats of the Synod for {U}."""
    w1g3_lands = [
        p for p in game.controlled_by(0)
        if p.card.name == "Seat of the Synod" and not p.tapped
    ][:count]
    assert len(w1g3_lands) == count
    for w1g3_land in w1g3_lands:
        assert game.tap_land_for_mana(
            0, w1g3_land.card.name, "U", permanent_id=w1g3_land.permanent_id,
        )  # _w1g3_tap_blue


def test_w1g3_broodstar_costs_what_its_artifacts_leave_and_counts_them(set_pool):
    """"Affinity for artifacts" and "Broodstar's power and toughness are each
    equal to the number of artifacts you control" (CR 604.3). Printed
    {8}{U}{U}: eight artifact lands take the {8} off, two of them pay
    {U}{U}, and Broodstar enters an 8/8 flier — it is not an artifact itself.
    The CDA recounts continuously: an artifact entering makes it 9/9, three
    sacrificed make it 6/6. Seven artifacts would have left {1}{U}{U}."""
    broodstar = set_pool("MRD")["Broodstar"]
    game, mine = _w1g3_table(
        set_pool, hand=["Broodstar"], mine=["Seat of the Synod"] * 8,
    )
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (0, 2)
    _w1g3_tap_blue(game, 2)
    cast = game.cast_from_hand(0, "Broodstar")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    star = next(p for p in game.controlled_by(0) if p.card.name == "Broodstar")
    assert (star.effective_power, star.effective_toughness) == (8, 8)
    assert game._has_keyword(star, "flying")
    assert sum(game.players[0].mana_pool.values()) == 0

    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("MRD")["Frogmite"]), None
    )
    assert (star.effective_power, star.effective_toughness) == (9, 9)
    game.sacrifice_permanents(mine[:3])
    # CR 704.3: the state check before anyone next receives priority is where
    # the board's continuous effects are recomputed (CR 611.3a).
    game.check_state_based_actions()
    assert (star.effective_power, star.effective_toughness) == (6, 6)

    game, _mine = _w1g3_table(set_pool, mine=["Seat of the Synod"] * 7)
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (1, 2)


def test_w1g3_somber_hoverguard_flies_in_for_one_blue(set_pool):
    """Printed {5}{U}; five artifact lands leave {U}, one of them pays it, and
    a 3/2 flier enters. Four lands leave {1}{U}, which one land cannot pay."""
    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 5,
    )
    _w1g3_tap_blue(game, 1)
    cast = game.cast_from_hand(0, "Somber Hoverguard")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    drone = next(
        p for p in game.controlled_by(0) if p.card.name == "Somber Hoverguard"
    )
    assert (drone.effective_power, drone.effective_toughness) == (3, 2)
    assert game._has_keyword(drone, "flying")

    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 4,
    )
    _w1g3_tap_blue(game, 1)
    refused = game.cast_from_hand(0, "Somber Hoverguard")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Somber Hoverguard"]


def _w1g3_board(set_pool, mine=(), theirs=(), graveyard=(), interactive=()):
    """Costs not enforced (these drives are about what an ability does), every
    permanent untapped and past summoning sickness, the state checked once."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")

    def w1g3_card(name):
        return mrd[name] if name in mrd else lea[name]

    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", graveyard=[w1g3_card(n) for n in graveyard]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set(interactive)
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in ((0, mine), (1, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=w1g3_card(w1g3_name))
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_perm.tapped = False
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    w1g3_game.check_state_based_actions()
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_board


def _w1g3_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # _w1g3_pt


def test_w1g3_the_nim_count_their_controllers_artifacts(set_pool):
    """"This creature gets +1/+0 for each artifact you control." Two artifacts
    on their side (an Ornithopter and an artifact land), three on the other
    side that count for nothing: Lasher 3/1, Shrieker 2/1 with flying,
    Devourer 6/1, Shambler 4/1."""
    game, mine, _theirs = _w1g3_board(
        set_pool,
        mine=["Nim Lasher", "Nim Shrieker", "Nim Devourer", "Nim Shambler",
              "Ornithopter", "Seat of the Synod"],
        theirs=["Ornithopter"] * 3,
    )
    assert [_w1g3_pt(p) for p in mine[:4]] == [(3, 1), (2, 1), (6, 1), (4, 1)]
    assert game._has_keyword(mine[1], "flying")


def test_w1g3_nim_shambler_regenerates_off_a_sacrificed_creature(set_pool):
    """"Sacrifice a creature: Regenerate this creature." The Bears pay; the
    shield then replaces the Shambler's destruction by lethal damage — it
    stays, tapped and with its damage removed (CR 701.19a)."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Nim Shambler", "Grizzly Bears"],
    )
    shambler, bears = mine
    activated = game.activate_permanent_ability(
        0, "Nim Shambler", cost_permanent_ids=[bears.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    assert not game.is_on_battlefield(bears)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    game.active_player_index = 1
    bolt = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[shambler.permanent_id])
    assert bolt.supported, bolt.details
    _w1g3_resolve(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(shambler) and shambler.tapped
    assert "Nim Shambler" not in [c.name for c in game.players[0].graveyard]


def test_w1g3_nim_devourer_returns_from_the_graveyard_in_upkeep_only(set_pool):
    """"{B}{B}: Return this card from your graveyard to the battlefield, then
    sacrifice a creature. Activate only during your upkeep." CR 113.6m: the
    ability works from the graveyard, where its first step moves the card
    from. It was refused there ("does not function from a graveyard") and
    offered on the battlefield, because the zone was stamped on the return
    step inside a "then" sequence and read off the top alone (MRD W1G3).

    Outside the upkeep it is refused by its own restriction; in the upkeep
    the Devourer returns and a creature is sacrificed — an interactive seat
    is asked which, and may name the Devourer itself, which goes back to the
    graveyard. On the battlefield the ability is not offered at all."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities

    program = compile_card_oracle(set_pool("MRD")["Nim Devourer"])
    assert usable_activated_abilities(program) == []
    assert len(usable_activated_abilities(program, zone="graveyard")) == 1

    game, _mine, _theirs = _w1g3_board(
        set_pool, mine=["Grizzly Bears"], graveyard=["Nim Devourer"],
    )
    game.current_turn_phase, game.current_step = "precombat_main", "main"
    refused = game.activate_from_graveyard(0, "Nim Devourer")
    assert not refused.supported and "upkeep" in refused.details
    assert [c.name for c in game.players[0].graveyard] == ["Nim Devourer"]

    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    activated = game.activate_from_graveyard(0, "Nim Devourer")
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    assert "Nim Devourer returned from the graveyard to the battlefield" in game.log
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Nim Devourer"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears"]

    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Grizzly Bears"], graveyard=["Nim Devourer"],
        interactive=[0],
    )
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    assert game.activate_from_graveyard(0, "Nim Devourer").supported
    _w1g3_resolve(game)
    prompt = game.pending_sacrifice_state()
    assert prompt is not None and len(prompt["valid_indices"]) == 2
    devourer = next(p for p in game.controlled_by(0) if p.card.name == "Nim Devourer")
    assert game.confirm_sacrifice(0, permanent_ids=[devourer.permanent_id])
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Nim Devourer"]


def test_w1g3_copperhoof_vorrac_counts_untapped_opposing_permanents(set_pool):
    """"This creature gets +1/+1 for each untapped permanent your opponents
    control." Four untapped across the table make a 6/6; one tapped for mana
    makes it 5/5 at the next state check (CR 704.3), and its controller's own
    untapped permanents count for nothing."""
    game, mine, theirs = _w1g3_board(
        set_pool, mine=["Copperhoof Vorrac", "Forest", "Forest"],
        theirs=["Island", "Island", "Grizzly Bears", "Ornithopter"],
    )
    vorrac = mine[0]
    assert _w1g3_pt(vorrac) == (6, 6)
    assert game.tap_land_for_mana(1, "Island", "U", permanent_id=theirs[0].permanent_id)
    game.check_state_based_actions()
    assert _w1g3_pt(vorrac) == (5, 5)


def test_w1g3_the_artifact_eaters_sacrifice_what_they_print(set_pool):
    """Megatog ("Sacrifice an artifact: +3/+3 and trample until end of
    turn"), Krark-Clan Grunt ("+1/+0 and first strike") and Krark-Clan Shaman
    ("1 damage to each creature without flying"): each eats one artifact. The
    Shaman's ping kills the Shaman (it has no flying) and spares a flier; and
    with no artifact left, the Grunt's cost cannot be paid."""
    game, mine, theirs = _w1g3_board(
        set_pool,
        mine=["Megatog", "Krark-Clan Grunt", "Krark-Clan Shaman",
              "Ornithopter", "Ornithopter", "Seat of the Synod"],
        theirs=["Grizzly Bears", "Ornithopter"],
    )
    tog, grunt, shaman, first, second, land = mine
    for w1g3_name, w1g3_fodder in (
        ("Megatog", first), ("Krark-Clan Grunt", second), ("Krark-Clan Shaman", land),
    ):
        activated = game.activate_permanent_ability(
            0, w1g3_name, cost_permanent_ids=[w1g3_fodder.permanent_id],
        )
        assert activated.supported, (w1g3_name, activated.details)
        _w1g3_resolve(game)
        assert not game.is_on_battlefield(w1g3_fodder)
    game.check_state_based_actions()
    assert _w1g3_pt(tog) == (6, 7) and game._has_keyword(tog, "trample")
    assert _w1g3_pt(grunt) == (3, 2) and game._has_keyword(grunt, "first strike")
    assert not game.is_on_battlefield(shaman)
    bears, flier = theirs
    assert game.is_on_battlefield(bears) and bears.damage_marked == 1
    assert game.is_on_battlefield(flier) and flier.damage_marked == 0
    refused = game.activate_permanent_ability(0, "Krark-Clan Grunt")
    assert not refused.supported

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_table(set_pool, hand=(), mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", hand=list(hand),
                          library=[lea["Island"]] * 10),
        _w1g6_PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _w1g6_Permanent(card=card)
            permanent.metadata["summoning_sickness_turn"] = -99
            game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return game


def _w1g6_on_board(game, name):
    return [p for p in game.all_permanents() if p.card.name == name]


def test_w1g6_war_elemental_is_sacrificed_on_a_turn_no_opponent_was_damaged(
    set_pool,
):
    """"When this creature enters, sacrifice it unless an opponent was dealt
    damage this turn." Nothing has been dealt: the entry trigger sacrifices
    it."""
    elemental = set_pool("MRD")["War Elemental"]
    game = _w1g6_table(set_pool, hand=[elemental])

    assert game.queue_from_hand(0, "War Elemental").supported
    _w1g6_resolve_stack(game)

    assert not _w1g6_on_board(game, "War Elemental")
    assert "War Elemental" in [c.name for c in game.players[0].graveyard]


@_w1g6_pytest.mark.parametrize("interactive", [False, True])
def test_w1g6_war_elemental_grows_by_each_point_dealt_to_an_opponent(
    set_pool, interactive,
):
    """"Whenever an opponent is dealt damage, put that many +1/+1 counters on
    this creature."

    A Bolt to the face first, so the entry trigger keeps it (the turn's damage
    ledger, not a life total). Then a second Bolt is three counters, and two
    unblocked 2-power attackers dealing damage at once are one trigger for 4
    (the event read from the recipient's side, CR 603.2c) — seven counters in
    all. A Bolt at the Elemental's own controller grows nothing.
    """
    lea = set_pool("LEA")
    elemental = set_pool("MRD")["War Elemental"]
    bolt = lea["Lightning Bolt"]
    game = _w1g6_table(
        set_pool, hand=[bolt, elemental, bolt, bolt],
        mine=[lea["Grizzly Bears"], lea["Savannah Lions"]],
    )
    if interactive:
        game.interactive_seats = {0}

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17

    assert game.queue_from_hand(0, "War Elemental").supported
    _w1g6_resolve_stack(game)
    (war,) = _w1g6_on_board(game, "War Elemental")
    assert war.metadata.get("plus_counters", 0) == 0

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert war.metadata.get("plus_counters") == 3

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 17
    assert war.metadata.get("plus_counters") == 3, "its controller is no opponent"

    war.metadata["summoning_sickness_turn"] = 99   # stays home
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [
        slot for slot, p in enumerate(game.players[0].battlefield)
        if p.card.name in ("Grizzly Bears", "Savannah Lions")
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    for _ in range(4):   # blockers (none), then the damage step
        if game.players[1].life < 14:
            break
        game.advance_combat_phase()
        _w1g6_resolve_stack(game)
    assert game.players[1].life == 10
    assert war.metadata.get("plus_counters") == 7, game.log
    assert sum("War Elemental gets" in line for line in game.log) == 2, (
        "one trigger per dealing, not one per attacker"
    )
    assert (war.effective_power, war.effective_toughness) == (8, 8)


# --- The supported-on-arrival family, driven ---------------------------------


def _w1g6_attack_through(game, names, blocks=None):
    """P1 attacks with the creatures named, P2 blocks as told, and combat runs
    to its end."""
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [
        slot for slot, p in enumerate(game.players[0].battlefield)
        if p.card.name in names
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    _w1g6_resolve_stack(game)
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, dict(blocks or {}))
    assert ok, why
    for _ in range(6):
        _w1g6_resolve_stack(game)
        if game.current_phase != "combat":
            break
        game.advance_combat_phase()
    _w1g6_resolve_stack(game)


@_w1g6_pytest.mark.parametrize("name", [
    "Slith Ascendant", "Slith Bloodletter", "Slith Firewalker", "Slith Predator",
])
def test_w1g6_a_slith_grows_each_time_it_connects(set_pool, name):
    """"Whenever this creature deals combat damage to a player, put a +1/+1
    counter on it." Two unblocked attacks: one counter each, the second hit
    for 2."""
    game = _w1g6_table(set_pool, mine=[set_pool("MRD")[name]])
    (slith,) = _w1g6_on_board(game, name)
    _w1g6_attack_through(game, [name])
    assert slith.metadata.get("plus_counters") == 1
    slith.tapped = False
    _w1g6_attack_through(game, [name])
    assert slith.metadata.get("plus_counters") == 2
    assert game.players[1].life == 20 - 1 - 2


def test_w1g6_slith_predator_grows_from_trample_over_a_chump(set_pool):
    """Slith Predator's trample damage reaching the player is combat damage to
    a player: blocked by a 1/1 with two counters on it, it still grows."""
    from engine.named_counters import add_counters

    lea = set_pool("LEA")
    game = _w1g6_table(
        set_pool, mine=[set_pool("MRD")["Slith Predator"]],
        theirs=[lea["Llanowar Elves"]],
    )
    (predator,) = _w1g6_on_board(game, "Slith Predator")
    add_counters(predator, "+1/+1", 2)
    _w1g6_attack_through(game, ["Slith Predator"], blocks={0: 0})
    assert game.players[1].life == 18
    assert predator.metadata.get("plus_counters") == 3


def test_w1g6_living_hive_makes_an_insect_per_point_dealt(set_pool):
    """"Whenever this creature deals combat damage to a player, create that
    many 1/1 green Insect creature tokens." Six damage, six Insects."""
    game = _w1g6_table(set_pool, mine=[set_pool("MRD")["Living Hive"]])
    _w1g6_attack_through(game, ["Living Hive"])
    insects = _w1g6_on_board(game, "Insect Token")
    assert game.players[1].life == 14
    assert len(insects) == 6
    assert all(
        (t.effective_power, t.effective_toughness) == (1, 1) for t in insects
    )
    assert all(t in game.players[0].battlefield for t in insects)


@_w1g6_pytest.mark.parametrize("interactive", [False, True])
def test_w1g6_wurmskin_forger_divides_as_its_trigger_goes_on_the_stack(
    set_pool, interactive,
):
    """"When this creature enters, distribute three +1/+1 counters among one,
    two, or three target creatures." The division is the entry trigger's,
    chosen as it is put on the stack (CR 603.3d, 601.2d): the creature is cast
    with nothing announced (a cast naming a division is refused — it divides
    nothing), and the trigger asks its controller once. A person names Bears
    2, Giant 1; a seat nobody asks takes the default spread over its own
    side."""
    lea = set_pool("LEA")
    forger = set_pool("MRD")["Wurmskin Forger"]
    game = _w1g6_table(
        set_pool, hand=[forger], mine=[lea["Grizzly Bears"]],
        theirs=[lea["Hill Giant"]],
    )
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    assert derive_cast_spec(forger, compile_card_oracle(forger)) is None
    (bears,) = _w1g6_on_board(game, "Grizzly Bears")
    (giant,) = _w1g6_on_board(game, "Hill Giant")
    refused = game.queue_from_hand(
        0, "Wurmskin Forger",
        divided_targets=[(0, game.battlefield_index_of(bears), 3)],
    )
    assert not refused.supported and "divides nothing" in refused.details
    if interactive:
        game.interactive_seats = {0}

    assert game.queue_from_hand(0, "Wurmskin Forger").supported
    if not interactive:
        _w1g6_resolve_stack(game)
        (entered,) = _w1g6_on_board(game, "Wurmskin Forger")
        placed = [
            p.metadata.get("plus_counters", 0) for p in (bears, giant, entered)
        ]
        assert sum(placed) == 3 and placed[1] == 0, placed
        return
    game.resolve_top_of_stack()
    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert (asked.data["max_targets"], asked.data["division_total"]) == (3, 3)
    assert game.confirm_trigger_target(
        0, permanent_ids=[bears.permanent_id, giant.permanent_id], amounts=[2, 1],
    )
    _w1g6_resolve_stack(game)
    assert bears.metadata.get("plus_counters") == 2
    assert giant.metadata.get("plus_counters") == 1

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
import pytest
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=(
            [card(n) for n in library] if library is not None
            else [other["Island"]] * 10
        ),
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_until_owed(game, kind, seat=0):
    """Resolve the top of the stack until *kind* is owed by *seat* — the
    interactive seat's turn to answer, which ``resolve_stack`` would answer by
    default."""
    for _ in range(10):
        if game.pending_choice_of(kind, seat) is not None:
            return game.pending_choice_of(kind, seat)
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game.pending_choice_of(kind, seat)


def _w1g7_settle(game):
    """Drain the stack and answer, as a headless seat, what a bare table left
    on the queue (an offer made by a trigger that resolved with nobody held)."""
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def test_w1g7_leonin_elder_gains_on_any_artifact_entering(set_pool):
    """"Whenever **an** artifact enters, you may gain 1 life." The condition
    table read only "a"/"another", so the line was no trigger and the Elder
    refused as text too complex. An opponent's artifact counts (no "you
    control"); a nonartifact creature does not."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert p1.life == 21
    assert "P1 gained 1 life from Leonin Elder (20 -> 21)" in game.log

    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert p1.life == 21, "a nonartifact creature is not an artifact"


def test_w1g7_leonin_elder_may_decline(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Ornithopter"], interactive=(0,),
    )
    game.cast_from_hand(0, "Ornithopter")
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    _w1g7_resolve(game)
    assert p1.life == 20


def test_w1g7_vermiculos_grows_per_artifact_this_turn(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vermiculos"], hand=["Ornithopter", "Ornithopter"],
    )
    vermiculos = p1.battlefield[0]
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (5, 5)
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (9, 9)


def test_w1g7_lumengrid_sentinel_taps_on_its_controllers_artifact_only(set_pool):
    """"…an artifact **you control** enters": the narrowing is enforced — the
    opponent's artifact fires nothing — and the seat chooses the target as the
    trigger goes on the stack (CR 603.3d)."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Sentinel"], hand=["Ornithopter"],
        theirs=["Grizzly Bears"], their_hand=["Ornithopter"], interactive=(0,),
    )
    bears = p2.battlefield[0]
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert game.pending_choices == [] and not bears.tapped

    game.cast_from_hand(0, "Ornithopter")
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert "Grizzly Bears" in [t["name"] for t in prompt.data["targets"]]
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id, seat=1)
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g7_resolve(game)
    assert bears.tapped
    assert "Tapped Grizzly Bears" in game.log


def test_w1g7_vedalken_archmage_draws_for_artifact_spells_only(set_pool):
    """"Whenever you cast **an** artifact spell, draw a card." The table's type
    row carried "artifact" and read "a" before it, so no card could reach it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vedalken Archmage"],
        hand=["Ornithopter", "Grizzly Bears"], their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 2, "cast one, drew one"
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "a creature spell is not an artifact spell"
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "an opponent's artifact spell is not yours"

@pytest.mark.parametrize(
    "top,zone",
    [("Ornithopter", "hand"), ("Leonin Elder", "graveyard"), ("Island", "graveyard")],
)
def test_w1g7_neurok_familiar_sorts_the_revealed_card(set_pool, top, zone):
    """"…reveal the top card of your library. If it's an artifact card, put it
    into your hand. **Otherwise, put it into your graveyard.**" The reveal-top
    template knew one "otherwise" (the library's bottom). Ornithopter is an
    *artifact creature* card, which is an artifact card (CR 205.2) — the handler
    asked ``primary_type``, which answers "creature" for it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Neurok Familiar"], library=[top, "Island", "Island"],
    )
    game.cast_from_hand(0, "Neurok Familiar")
    _w1g7_settle(game)
    names = {
        "hand": [c.name for c in p1.hand],
        "graveyard": [c.name for c in p1.graveyard],
    }
    assert names[zone] == [top], game.log
    assert len(p1.library) == 2
    put = "hand" if zone == "hand" else "graveyard"
    assert f"P1 revealed {top} and put it into their {put}" in game.log

@pytest.mark.parametrize("pick,untapped", [("Ornithopter", True), ("Mountain", False)])
def test_w1g7_lumengrid_augur_untaps_when_the_target_discards_an_artifact(
    set_pool, pick, untapped
):
    """"{1}, {T}: Target player draws a card, then discards a card. **If that
    player discards an artifact card this way**, untap this creature." The
    record condition read the narrowed question with "you" as the subject
    only. The target picks (an interactive seat), and the untap waits for the
    answer: it reads which card went, not whether one did."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Augur"], their_hand=["Ornithopter", "Mountain"],
        interactive=(1,),
    )
    augur = game.players[0].battlefield[0]
    result = game.activate_permanent_ability(0, "Lumengrid Augur", target_player_index=1)
    assert result.supported, result.details
    assert augur.tapped
    prompt = _w1g7_until_owed(game, "discard", 1)
    assert prompt is not None, game.log
    assert len(p2.hand) == 3, "drew first"
    index = [c.name for c in p2.hand].index(pick)
    assert game.resolve_pending_choice("discard", 1, hand_indices=[index], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == [pick]
    assert augur.tapped is not untapped
    assert ("Lumengrid Augur untapped" in game.log) is untapped

# ==== end W1G7 ======================================================
