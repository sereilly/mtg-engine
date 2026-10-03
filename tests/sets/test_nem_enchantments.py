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
