"""Nemesis enchantments, Auras included.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: combat restrictions and triggers ---

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _w1g3_beast(name: str, power: int, toughness: int, *,
                text: str = "", keywords: tuple = ()) -> CardDefinition:
    """An invented creature for these Auras to sit on or to fight."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


_W1G3_FLIER = dict(text="Flying", keywords=("Flying",))


def _w1g3_enchanted(set_pool, aura_name, host_card, *, host_seat, others):
    """*aura_name* attached to a *host_card* on *host_seat*; *others* is the
    rest of the table as ``{seat: [card, …]}``. Turn 0 begun, layers settled.

    Returns ``(game, aura, host, {seat: [permanents]})``.
    """
    aura = Permanent(card=set_pool("NEM")[aura_name])
    host = Permanent(card=host_card)
    boards = {0: [], 1: []}
    for seat, cards in others.items():
        boards[seat] = [Permanent(card=card) for card in cards]
    boards[host_seat] = [host, aura, *boards[host_seat]]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(boards[0])),
        PlayerState(name="P1", battlefield=list(boards[1])),
    ])
    game.enforce_mana_costs = False
    for permanent in (*boards[0], *boards[1]):
        permanent.metadata["summoning_sickness_turn"] = -99
    attach_aura(aura, host)
    game.start_turn(0)
    game._close_current_priority_step()
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    rest = {
        seat: [p for p in boards[seat] if p is not host and p is not aura]
        for seat in boards
    }
    return game, aura, host, rest


def _w1g3_attack_with(game, slots):
    """Declare seat 0's *slots* as attackers and stop at declare blockers."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    outcome = game.declare_attackers(0, list(slots))
    assert outcome[0], outcome
    game.advance_combat_phase()


# --- Air Bladder -----------------------------------------------------------
# "Enchanted creature has flying. / Enchanted creature can block only creatures
# with flying." Shacklegeist's restriction printed on an Aura about its host.


def test_w1g3_air_bladder_grants_flying(set_pool):
    _game, _aura, host, _ = _w1g3_enchanted(
        set_pool, "Air Bladder", _w1g3_beast("Host", 2, 2), host_seat=1, others={},
    )

    assert host.has_keyword("flying")


def test_w1g3_air_bladder_host_can_block_only_fliers(set_pool):
    game, _aura, host, rest = _w1g3_enchanted(
        set_pool, "Air Bladder", _w1g3_beast("Host", 2, 2), host_seat=1,
        others={0: [_w1g3_beast("Walker", 2, 2), _w1g3_beast("Bird", 1, 1, **_W1G3_FLIER)]},
    )
    walker, bird = rest[0]
    _w1g3_attack_with(game, [0, 1])

    assert not game._can_block_attacker(host, walker)
    assert game._can_block_attacker(host, bird)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {0: 1})[0]


def test_w1g3_air_bladder_restriction_leaves_with_the_aura(set_pool):
    game, aura, host, rest = _w1g3_enchanted(
        set_pool, "Air Bladder", _w1g3_beast("Host", 2, 2), host_seat=1,
        others={0: [_w1g3_beast("Walker", 2, 2)]},
    )
    (walker,) = rest[0]
    _w1g3_attack_with(game, [0])
    assert not game._can_block_attacker(host, walker)

    detach_aura(aura, host)

    assert game._can_block_attacker(host, walker)


# --- Treetop Bracers -------------------------------------------------------
# "Enchanted creature gets +1/+1 and can't be blocked except by creatures with
# flying." Two channels on one line: layer 7c and a CR 509.1b whitelist.


def test_w1g3_treetop_bracers_pumps_its_host(set_pool):
    _game, _aura, host, _ = _w1g3_enchanted(
        set_pool, "Treetop Bracers", _w1g3_beast("Host", 2, 2), host_seat=0, others={},
    )

    assert (host.effective_power, host.effective_toughness) == (3, 3)


def test_w1g3_treetop_bracers_host_is_blockable_only_by_fliers(set_pool):
    game, _aura, host, rest = _w1g3_enchanted(
        set_pool, "Treetop Bracers", _w1g3_beast("Host", 2, 2), host_seat=0,
        others={1: [
            _w1g3_beast("Ground", 3, 3),
            _w1g3_beast("Bird", 1, 1, **_W1G3_FLIER),
            _w1g3_beast("Spider", 1, 4, text="Reach", keywords=("Reach",)),
        ]},
    )
    ground, bird, spider = rest[1]
    _w1g3_attack_with(game, [0])

    assert not game._can_block_attacker(ground, host)
    # The printed whitelist names flying alone — reach is flying's own
    # reminder text, not this card's.
    assert not game._can_block_attacker(spider, host)
    assert game._can_block_attacker(bird, host)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g3_treetop_bracers_host_hits_for_the_pumped_power(set_pool):
    game, _aura, _host, rest = _w1g3_enchanted(
        set_pool, "Treetop Bracers", _w1g3_beast("Host", 2, 2), host_seat=0,
        others={1: [_w1g3_beast("Ground", 3, 3)]},
    )
    _w1g3_attack_with(game, [0])
    game.declare_blockers(1, {})
    for _ in range(4):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        resolve_stack(game)

    assert game.players[1].life == 17


# --- Laccolith Rig ---------------------------------------------------------
# "Whenever enchanted creature becomes blocked, you may have it deal damage
# equal to its power to target creature. If you do, the first creature assigns
# no combat damage this turn." The damage is the enchanted creature's, and
# "the first creature" is that same creature.


def test_w1g3_laccolith_rig_has_its_host_deal_the_damage(set_pool):
    game, _aura, host, rest = _w1g3_enchanted(
        set_pool, "Laccolith Rig", _w1g3_beast("Host", 3, 3), host_seat=0,
        others={1: [_w1g3_beast("Blocker", 2, 2), _w1g3_beast("Bystander", 3, 3)]},
    )
    blocker, bystander = rest[1]
    game.interactive_seats = {0}
    _w1g3_attack_with(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]

    assert game.confirm_trigger_target(0, permanent_id=bystander.permanent_id)
    resolve_stack(game)
    assert game.confirm_optional_pay(0, accept=True)
    resolve_stack(game)

    assert "Host deals 3 damage to Bystander" in game.log
    assert host.metadata.get("assigns_no_combat_damage_until_eot")
    # The mark is on the creature, so the combat damage it would have dealt
    # to its blocker never happens.
    for _ in range(4):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        resolve_stack(game)
    assert game.is_on_battlefield(blocker)
    assert blocker.damage_marked == 0


def test_w1g3_laccolith_rig_declined_leaves_combat_damage_alone(set_pool):
    game, _aura, host, rest = _w1g3_enchanted(
        set_pool, "Laccolith Rig", _w1g3_beast("Host", 3, 3), host_seat=0,
        others={1: [_w1g3_beast("Blocker", 2, 2)]},
    )
    (blocker,) = rest[1]
    game.interactive_seats = {0}
    _w1g3_attack_with(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    assert game.confirm_trigger_target(0, permanent_id=blocker.permanent_id)
    resolve_stack(game)
    assert game.confirm_optional_pay(0, accept=False)
    resolve_stack(game)

    assert not host.metadata.get("assigns_no_combat_damage_until_eot")
    for _ in range(4):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        resolve_stack(game)
    assert not game.is_on_battlefield(blocker)


def test_w1g3_laccolith_rig_is_silent_while_its_host_is_unblocked(set_pool):
    game, _aura, _host, _ = _w1g3_enchanted(
        set_pool, "Laccolith Rig", _w1g3_beast("Host", 3, 3), host_seat=0, others={},
    )
    _w1g3_attack_with(game, [0])
    game.declare_blockers(1, {})

    assert not game.stack
    assert not any("Laccolith Rig triggered" in line for line in game.log)


# --- W1G2: alternative costs and redirects ---
# Lashknife: an Aura whose alternative cost (CR 118.9) taps a creature. The
# Aura gate (`engine/auras.py`) refused the card on that line before this round
# — "unimplemented aura effect" — because it read the cost sentence as an effect
# the Aura has while attached.
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g2e_table(set_pool, hand, mine=()):
    """Two seats, mana costs **enforced**: the card is about which price is
    paid. Basics and bystanders come from the base set."""
    pools = (set_pool("NEM"), set_pool("LEA"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [card(name) for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    caster.battlefield.extend(Permanent(card=card(name)) for name in mine)
    game._sync_control()
    return game, caster


def test_w1g2_lashknife_taps_the_named_creature_and_grants_first_strike(set_pool):
    """The whole card: a Plains on the board, the Hill Giant named to pay, the
    Bears enchanted. The deterministic pick would have tapped the Bears (it
    keeps the bigger creature), so a payment that ignored the choice fails
    here; and the first strike is read through the layer accessor, so it is
    the Aura's static and not a flag the cast left behind."""
    game, caster = _w1g2e_table(
        set_pool, ["Lashknife"], mine=("Plains", "Grizzly Bears", "Hill Giant")
    )
    bears, giant = caster.battlefield[1], caster.battlefield[2]

    result = game.cast_from_hand(
        0, "Lashknife", alternative_cost=True,
        target_player_index=0, target_permanent_index=1,
        alternative_cost_permanent_ids=[giant.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert (bears.tapped, giant.tapped) == (False, True)
    assert game._has_keyword(bears, "first strike")
    assert not game._has_keyword(giant, "first strike")
    assert not any(caster.mana_pool.values())


def test_w1g2_lashknife_offers_only_creatures_that_can_pay(set_pool):
    """What the cast picker offers is the list the payment takes from: an
    untapped creature the caster controls. The tapped Bears and the Plains are
    not offered, and a name outside the list is refused with nothing paid."""
    game, caster = _w1g2e_table(
        set_pool, ["Lashknife"], mine=("Plains", "Grizzly Bears", "Hill Giant")
    )
    caster.battlefield[1].tapped = True
    giant = caster.battlefield[2]

    offers = game.cast_cost_offers(0, set_pool("NEM")["Lashknife"], spell_hand_index=0)
    (offer,) = [o for o in offers if o["kind"] == "alternative"]
    assert offer["payable"] and offer["permanent_verb"] == "tap"
    assert offer["permanent_choices"] == [
        {"id": giant.permanent_id, "name": "Hill Giant"}
    ]

    plains = caster.battlefield[0]
    refused = game.cast_from_hand(
        0, "Lashknife", alternative_cost=True,
        target_player_index=0, target_permanent_index=2,
        alternative_cost_permanent_ids=[plains.permanent_id],
    )
    assert not refused.supported
    assert not giant.tapped and [c.name for c in caster.hand] == ["Lashknife"]


# --- W1G6: lands, mana and untapping ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_ench_game(set_pool, seat0, seat1):
    """Two seats with the given permanents and a library each to draw from."""
    island = set_pool("LEA")["Island"]
    players = [
        PlayerState(name="P0", battlefield=list(seat0), library=[island] * 8),
        PlayerState(name="P1", battlefield=list(seat1), library=[island] * 8),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w1g6_ench_take_turn(game, seat):
    """Start *seat*'s turn and settle everything its upkeep put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return seat


def test_rising_waters_locks_lands_and_releases_one_per_upkeep(set_pool):
    """"Lands don't untap during their controllers' untap steps. At the
    beginning of each player's upkeep, that player untaps a land they control."

    Both halves. The lock was the only half that ran: the release lowered to
    nothing, so the card was a harder lock than it prints. The release is the
    *upkeep player's*, not the enchantment's controller's, and a seat that is
    not asked takes a tapped land over an untapped one — untapping an untapped
    land is legal and does nothing.
    """
    waters = Permanent(card=set_pool("NEM")["Rising Waters"])
    ours = [Permanent(card=set_pool("LEA")["Island"]) for _ in range(3)]
    theirs = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(3)]
    game = _w1g6_ench_game(set_pool, [waters, *ours], theirs)
    for land in ours + theirs:
        land.tapped = True
    theirs[0].tapped = False  # first in board order, and already untapped

    _w1g6_ench_take_turn(game, 1)

    assert [land.tapped for land in theirs] == [False, False, True], (
        "the untap step untapped nothing; the upkeep player untapped one "
        "*tapped* land of their own"
    )
    assert all(land.tapped for land in ours), "the other seat's lands stay down"

    _w1g6_ench_take_turn(game, 0)

    assert [land.tapped for land in ours] == [False, True, True]
    assert [land.tapped for land in theirs] == [False, False, True]


def test_rising_waters_asks_the_upkeep_player_which_land(set_pool):
    """An interactive upkeep player is asked, and is offered only their own
    lands — "a land **they** control" — not the enchantment controller's."""
    waters = Permanent(card=set_pool("NEM")["Rising Waters"])
    ours = [Permanent(card=set_pool("LEA")["Island"])]
    theirs = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(2)]
    game = _w1g6_ench_game(set_pool, [waters, *ours], theirs)
    game.interactive_seats = {0, 1}
    for land in ours + theirs:
        land.tapped = True

    game.start_turn(1)
    for _ in range(4):
        if not game.stack or not game.resolve_top_of_stack():
            break

    prompts = [c for c in game.pending_choices if c.kind == "permanent_choice"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    assert prompts[0].player_index == 1
    offered = {perm.permanent_id for perm in game.live_permanent_choices(prompts[0])}
    assert offered == {land.permanent_id for land in theirs}

    assert game.confirm_permanent_choice(1, theirs[1].permanent_id)
    resolve_stack(game)

    assert [land.tapped for land in theirs] == [True, False]
    assert ours[0].tapped


def test_mana_cache_banks_each_players_untapped_lands_for_anyone(set_pool):
    """"At the beginning of each player's end step, put a charge counter on this
    enchantment for each untapped land that player controls. / Remove a charge
    counter from this enchantment: Add {C}. Any player may activate this ability
    but only during their turn before the end step."

    The count is the *end-step player's* untapped lands, not the Cache
    controller's. The mana ability is anybody's, the mana is the activator's,
    it never touches the stack (CR 605.3b), and the window is the activator's
    own turn up to — not including — the end step.
    """
    from engine.named_counters import counters_on

    cache = Permanent(card=set_pool("NEM")["Mana Cache"])
    ours = [Permanent(card=set_pool("LEA")["Mountain"]) for _ in range(3)]
    theirs = [Permanent(card=set_pool("LEA")["Forest"]) for _ in range(4)]
    game = _w1g6_ench_game(set_pool, [cache, *ours], theirs)
    opponent = game.players[1]

    _w1g6_ench_take_turn(game, 1)
    theirs[0].tapped = True
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert counters_on(cache, "charge") == 3, "P1's three untapped Forests"

    refused = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert not refused.supported, "not during the end step itself"
    assert counters_on(cache, "charge") == 3, "a refused activation pays nothing"

    _w1g6_ench_take_turn(game, 0)
    refused = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert not refused.supported, "not during another player's turn"
    ours[0].tapped = True
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert counters_on(cache, "charge") == 5, "plus P0's two untapped Mountains"

    _w1g6_ench_take_turn(game, 1)
    result = game.activate_permanent_ability(
        1, "Mana Cache", ability_index=0, source_controller_index=0
    )
    assert result.supported, result.details
    assert not game.stack, "a mana ability does not use the stack"
    assert opponent.mana_pool["C"] == 1, "the mana is the activator's"
    assert game.players[0].mana_pool["C"] == 0
    assert counters_on(cache, "charge") == 4


def test_overlaid_terrain_trades_your_lands_for_two_mana_lands(set_pool):
    """"As this enchantment enters, sacrifice all lands you control. / Lands you
    control have "{T}: Add two mana of any one color.""

    The sacrifice is the entering seat's lands, all of them and nothing else
    (CR 614.1c — as it enters). The grant is a real activated mana ability of
    each land that seat controls, including one played afterwards, read through
    ``effective_card``; tapping it makes two mana of the colour asked for, and
    the planner and the client are told the land can make any colour. The
    opponent's lands are untouched, and the grant goes with the enchantment.
    """
    from web.serialization import _offered_mana

    lea = set_pool("LEA")
    ours = [Permanent(card=lea["Forest"]) for _ in range(4)]
    bears = Permanent(card=lea["Grizzly Bears"])
    theirs = Permanent(card=lea["Mountain"])
    game = _w1g6_ench_game(set_pool, [*ours, bears], [theirs])
    game.enforce_mana_costs = True
    me = game.players[0]
    me.hand.extend([set_pool("NEM")["Overlaid Terrain"], lea["Forest"]])
    _w1g6_ench_take_turn(game, 0)
    for land in ours:
        assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=land.permanent_id)

    assert game.cast_from_hand(0, "Overlaid Terrain").supported
    resolve_stack(game)

    board = [perm.card.name for perm in game.controlled_by(0)]
    assert board == ["Grizzly Bears", "Overlaid Terrain"], board
    assert [card.name for card in me.graveyard].count("Forest") == 4
    assert game.controller_index_of(theirs) == 1, "only the lands *you* control"

    assert game.cast_from_hand(0, "Forest").supported
    forest = next(p for p in game.controlled_by(0) if p.card.name == "Forest")
    assert game._land_payment_colors(forest) == ("W", "U", "B", "R", "G")
    assert _offered_mana(game, forest) == ("W", "U", "B", "R", "G")
    assert game._land_payment_colors(theirs) == ("R",)
    assert game.tap_land_for_mana(0, "Forest", "U", permanent_id=forest.permanent_id)
    assert me.mana_pool["U"] == 2 and me.mana_pool["G"] == 0

    terrain = next(
        p for p in game.controlled_by(0) if p.card.name == "Overlaid Terrain"
    )
    game.sacrifice_permanent(terrain)
    game._settle()
    assert "two mana of any one color" not in forest.effective_card.oracle_text
    assert game._land_payment_colors(forest) == ("G",)


# --- W1G1: fading ---
# Fading (CR 702.32) is the rewrite in `engine/fading.py`; its rules tests are
# tests/rules/test_fading.py. These drive the Nemesis enchantments that print it.
from engine import Game as _W1G1EGame
from engine.models import Permanent as _W1G1EPermanent
from engine.models import PlayerState as _W1G1EPlayerState
from engine.named_counters import counters_on as _w1g1e_counters_on
from engine.oracle import compile_card_oracle as _w1g1e_compile

from tests.helpers import resolve_stack as _w1g1e_resolve_stack


def _w1g1e_duel() -> "_W1G1EGame":
    game = _W1G1EGame(players=[
        _W1G1EPlayerState(name="P1", life=20), _W1G1EPlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game


def _w1g1e_dementia_on(game, set_pool, host_name: str):
    """Parallax Dementia cast from P1's hand onto P2's *host_name*."""
    nem = set_pool("NEM")
    host = _W1G1EPermanent(card=nem[host_name])
    game._put_permanent_onto_battlefield(1, host, None)
    game.players[0].hand = [nem["Parallax Dementia"]]
    assert game.cast_from_hand(
        0, "Parallax Dementia", target_player_index=1, target_permanent_index=0,
    ).supported
    _w1g1e_resolve_stack(game)
    [aura] = [p for p in game.players[0].battlefield
              if p.card.name == "Parallax Dementia"]
    return aura, host


def _w1g1e_upkeep(game, seat: int) -> None:
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_upkeep(seat)
    _w1g1e_resolve_stack(game)


def test_w1g1_parallax_dementia_is_an_aura_the_gate_admits(set_pool):
    """It was refused as "unimplemented aura effect: fading 1" — the Aura gate
    reads every line, and the keyword line was one nothing claimed. After the
    rewrite each of its five lines is a claimed one."""
    program = _w1g1e_compile(set_pool("NEM")["Parallax Dementia"])

    assert program.supported, program.reason
    assert sorted(t.condition.kind for t in program.triggered_abilities) == [
        "leaves_battlefield", "upkeep_self",
    ]


def test_w1g1_parallax_dementia_pumps_then_fades_and_takes_its_creature_with_it(set_pool):
    """"Fading 1", "+3/+2", and "When this Aura leaves the battlefield, destroy
    enchanted creature." The creature is a 5/4 for one upkeep of its
    controller's; at the second the Aura finds no counter, is sacrificed, and
    its leave trigger destroys the creature it *was* attached to (CR 608.2h —
    the Aura's teardown has detached it by then)."""
    game = _w1g1e_duel()
    aura, host = _w1g1e_dementia_on(game, set_pool, "Skyshroud Ridgeback")

    assert _w1g1e_counters_on(aura, "fade") == 1
    assert (host.effective_power, host.effective_toughness) == (5, 5)

    _w1g1e_upkeep(game, 1)
    _w1g1e_upkeep(game, 0)
    assert _w1g1e_counters_on(aura, "fade") == 0
    assert game.is_on_battlefield(aura) and game.is_on_battlefield(host)

    _w1g1e_upkeep(game, 1)
    _w1g1e_upkeep(game, 0)

    assert not game.is_on_battlefield(aura)
    assert not game.is_on_battlefield(host)
    assert [c.name for c in game.players[0].graveyard] == ["Parallax Dementia"]
    assert [c.name for c in game.players[1].graveyard] == ["Skyshroud Ridgeback"]
    assert "Parallax Dementia destroyed Skyshroud Ridgeback" in game.log


def test_w1g1_parallax_dementias_creature_cannot_be_regenerated(set_pool):
    """"That creature can't be regenerated." A regeneration shield on the host
    is armed, and the creature goes to the graveyard anyway with it unspent."""
    game = _w1g1e_duel()
    aura, host = _w1g1e_dementia_on(game, set_pool, "Skyshroud Ridgeback")
    host.regeneration_shield = 1

    game.remove_from_battlefield(aura)
    game._permanent_to_graveyard(game.players[0], aura)
    _w1g1e_resolve_stack(game)

    assert not game.is_on_battlefield(host)
    assert [c.name for c in game.players[1].graveyard] == ["Skyshroud Ridgeback"]


def _w1g1e_burst(game, seat: int = 0, set_pool=None):
    burst = _W1G1EPermanent(card=set_pool("NEM")["Saproling Burst"])
    game._put_permanent_onto_battlefield(seat, burst, None)
    return burst


def _w1g1e_saprolings(game) -> list:
    return [p for p in game.all_permanents() if "Saproling" in p.card.type_line]


def test_w1g1_saproling_burst_makes_saprolings_as_big_as_its_counters(set_pool):
    """"Remove a fade counter from this enchantment: Create a green Saproling
    creature token. It has "This token's power and toughness are each equal to
    the number of fade counters on Saproling Burst."" The token is defined by
    the Burst's pile *continuously* (CR 604.3): each one made is as big as the
    pile it leaves behind, and every one shrinks with the next counter that
    goes — by activation or by fading."""
    game = _w1g1e_duel()
    burst = _w1g1e_burst(game, set_pool=set_pool)
    assert _w1g1e_counters_on(burst, "fade") == 7

    assert game.activate_permanent_ability(0, "Saproling Burst").supported
    _w1g1e_resolve_stack(game)
    [first] = _w1g1e_saprolings(game)
    assert (first.effective_power, first.effective_toughness) == (6, 6)
    assert first.card.colors == ("G",)

    assert game.activate_permanent_ability(0, "Saproling Burst").supported
    _w1g1e_resolve_stack(game)
    assert [(s.effective_power, s.effective_toughness)
            for s in _w1g1e_saprolings(game)] == [(5, 5), (5, 5)]

    _w1g1e_upkeep(game, 1)
    _w1g1e_upkeep(game, 0)
    game.check_state_based_actions()
    assert [(s.effective_power, s.effective_toughness)
            for s in _w1g1e_saprolings(game)] == [(4, 4), (4, 4)]


def test_w1g1_saproling_burst_cannot_make_a_token_with_no_counter_left(set_pool):
    """The cost is charged: seven counters are seven Saprolings, and the
    eighth activation is refused with nothing made — the last one made
    arriving as a 0/0 that the state-based check removes."""
    game = _w1g1e_duel()
    burst = _w1g1e_burst(game, set_pool=set_pool)

    for _ in range(7):
        assert game.activate_permanent_ability(0, "Saproling Burst").supported
        _w1g1e_resolve_stack(game)
    game.check_state_based_actions()

    assert _w1g1e_counters_on(burst, "fade") == 0
    assert _w1g1e_saprolings(game) == []
    assert not game.activate_permanent_ability(0, "Saproling Burst").supported


def test_w1g1_each_saproling_counts_the_burst_that_made_it(set_pool):
    """"…fade counters on **Saproling Burst**" names the token's maker, not
    every Burst on the table: a second Burst's pile does not size the first
    one's Saprolings. The name becomes the relation the token's id stamp
    records, so two Bursts with different piles make different-sized tokens."""
    game = _w1g1e_duel()
    first = _w1g1e_burst(game, set_pool=set_pool)
    second = _w1g1e_burst(game, set_pool=set_pool)
    for _ in range(3):
        game.activate_permanent_ability(
            0, "Saproling Burst", permanent_index=game.battlefield_index_of(second),
        )
        _w1g1e_resolve_stack(game)
    game.activate_permanent_ability(
        0, "Saproling Burst", permanent_index=game.battlefield_index_of(first),
    )
    _w1g1e_resolve_stack(game)

    assert (_w1g1e_counters_on(first, "fade"), _w1g1e_counters_on(second, "fade")) == (6, 4)
    sizes = sorted(s.effective_power for s in _w1g1e_saprolings(game))
    assert sizes == [4, 4, 4, 6]


def test_w1g1_a_saproling_whose_burst_has_left_is_a_0_0(set_pool):
    """With the Burst gone there is no pile to count, so the tokens are 0/0
    and the state-based check removes them (CR 704.5f) — before the Burst's
    own leave trigger has even resolved."""
    game = _w1g1e_duel()
    burst = _w1g1e_burst(game, set_pool=set_pool)
    game.activate_permanent_ability(0, "Saproling Burst")
    _w1g1e_resolve_stack(game)
    [token] = _w1g1e_saprolings(game)

    game.remove_from_battlefield(burst)
    game._permanent_to_graveyard(game.players[0], burst)
    game.check_state_based_actions()

    assert [item.card.name for item in game.stack] == ["Saproling Burst"]
    assert not game.is_on_battlefield(token)


def test_w1g1_saproling_burst_destroys_its_tokens_and_they_cant_regenerate(set_pool):
    """"When this enchantment leaves the battlefield, destroy all tokens
    created with this enchantment. They can't be regenerated." An anthem keeps
    the Saproling at 1/1 once its pile is gone, so it is the trigger — not the
    0/0 check — that has to take it, and a regeneration shield does not save
    it. A token some other card made is not one created with *this* Burst."""
    game = _w1g1e_duel()
    anthem = _W1G1EPermanent(card=set_pool("USG")["Glorious Anthem"])
    game._put_permanent_onto_battlefield(0, anthem, None)
    burst = _w1g1e_burst(game, set_pool=set_pool)
    game.activate_permanent_ability(0, "Saproling Burst")
    _w1g1e_resolve_stack(game)
    [token] = _w1g1e_saprolings(game)
    token.regeneration_shield = 1

    game.remove_from_battlefield(burst)
    game._permanent_to_graveyard(game.players[0], burst)
    game.check_state_based_actions()
    assert game.is_on_battlefield(token), "1/1 under the anthem with the pile gone"
    _w1g1e_resolve_stack(game)

    assert not game.is_on_battlefield(token)
    assert token.regeneration_shield == 1, "the shield was never asked"
    assert any("Saproling Burst destroyed Saproling" in line for line in game.log)

# --- end W1G1 ---
