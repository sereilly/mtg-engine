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
