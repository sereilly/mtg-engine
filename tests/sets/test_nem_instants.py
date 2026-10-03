"""Nemesis instants.

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
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _w1g3_body(name: str, power: int, toughness: int, *,
               text: str = "", keywords: tuple = ()) -> CardDefinition:
    """An invented creature to point these two instants at."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_duel(mine, theirs, *, hand_of_1=()):
    """Seat 0 holds *mine*, seat 1 holds *theirs* and *hand_of_1*; turn 0 open."""
    attackers = [m if isinstance(m, Permanent) else Permanent(card=m) for m in mine]
    defenders = [t if isinstance(t, Permanent) else Permanent(card=t) for t in theirs]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(attackers)),
        PlayerState(name="P1", battlefield=list(defenders), hand=list(hand_of_1)),
    ])
    game.enforce_mana_costs = False
    for permanent in (*attackers, *defenders):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, attackers, defenders


def _w1g3_walk_combat_to(game, step: str) -> None:
    """Advance the combat phase, draining the stack, until *step* is current."""
    for _ in range(8):
        if game.current_step == step:
            return
        game.advance_combat_phase()
        resolve_stack(game)
    assert game.current_step == step, f"stuck at {game.current_step}"


# --- Off Balance -----------------------------------------------------------
# "Target creature can't attack or block this turn." One subject, two
# one-shot restrictions, each answered at its own step (CR 508.1c, 509.1b).


def test_w1g3_off_balance_stops_its_target_attacking(set_pool):
    game, (bear, other), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2), _w1g3_body("Other", 2, 2)], [],
        hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    result = game.cast_from_hand(
        1, "Off Balance", target_permanent_ids=[bear.permanent_id]
    )
    resolve_stack(game)
    assert result.supported, result.details
    game.advance_combat_phase()
    game.advance_combat_phase()

    refused = game.declare_attackers(0, [0])
    assert not refused[0], refused
    assert game.declare_attackers(0, [1])[0]


def test_w1g3_off_balance_stops_its_target_blocking(set_pool):
    game, (raider,), (wall, other) = _w1g3_duel(
        [_w1g3_body("Raider", 2, 2)],
        [_w1g3_body("Wall", 0, 4), _w1g3_body("Other", 1, 1)],
        hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    game.cast_from_hand(1, "Off Balance", target_permanent_ids=[wall.permanent_id])
    resolve_stack(game)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    assert not game._can_block_attacker(wall, raider)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g3_off_balance_ends_with_the_turn(set_pool):
    game, (bear,), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2)], [], hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    game.cast_from_hand(1, "Off Balance", target_permanent_ids=[bear.permanent_id])
    resolve_stack(game)
    assert bear.metadata.get("cant_block_until_eot")

    game.resolve_cleanup_step(0)

    assert not bear.metadata.get("cant_block_until_eot")
    assert not bear.metadata.get("cant_attack_until_eot_mark")


def test_w1g3_off_balance_announces_one_creature_target(set_pool):
    """Two instructions, one target: the picker asks once, for a creature."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("NEM")["Off Balance"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {"kind": "creature"}, spec


# --- Fog Patch -------------------------------------------------------------
# "Cast this spell only during the declare blockers step. / Attacking creatures
# become blocked." CR 509.1h: blocked with no blocker — no combat damage unless
# the creature has trample, which then assigns all of it to the player
# (CR 702.19d) — and the becomes-blocked triggers of the creatures that were
# unblocked fire (CR 509.3c).


def test_w1g3_fog_patch_blocks_every_attacker_including_the_unblockable(set_pool):
    game, (bear, ghost), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2),
         _w1g3_body("Ghost", 3, 3, text="This creature can't be blocked.")],
        [], hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    game.declare_blockers(1, {})

    result = game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)

    assert result.supported, result.details
    assert bear.blocked and ghost.blocked
    _w1g3_walk_combat_to(game, "postcombat_main")
    assert game.players[1].life == 20


def test_w1g3_fog_patch_lets_a_trampler_through_in_full(set_pool):
    game, (trampler,), _ = _w1g3_duel(
        [_w1g3_body("Trampler", 4, 4, text="Trample", keywords=("Trample",))], [],
        hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)
    assert trampler.blocked

    _w1g3_walk_combat_to(game, "postcombat_main")

    assert game.players[1].life == 16


def test_w1g3_fog_patch_fires_becomes_blocked_once_for_the_unblocked(set_pool):
    """Flint Golem was unblocked, so CR 509.3c fires its trigger; the second
    Golem already had a blocker, so becoming blocked again announces nothing."""
    nem = set_pool("NEM")
    game, (free, held), (wall,) = _w1g3_duel(
        [nem["Flint Golem"], nem["Flint Golem"]], [_w1g3_body("Wall", 0, 5)],
        hand_of_1=[nem["Fog Patch"]],
    )
    game.players[1].library = [_w1g3_body(f"Card{i}", 1, 1) for i in range(9)]
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 1})[0]
    resolve_stack(game)
    assert len(game.players[1].library) == 6

    game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)

    assert free.blocked and held.blocked
    assert len(game.players[1].library) == 3
    assert sum(
        "Flint Golem triggered on becoming blocked" in line for line in game.log
    ) == 2


def test_w1g3_fog_patch_cannot_be_cast_before_blockers(set_pool):
    game, _, _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2)], [], hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.active_player_index = 0

    result = game.cast_from_hand(1, "Fog Patch")

    assert result.details != "resolved", result
    assert [card.name for card in game.players[1].hand] == ["Fog Patch"]


def test_w1g3_fog_patch_announces_no_target(set_pool):
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("NEM")["Fog Patch"]

    assert derive_cast_spec(card, compile_card_oracle(card)) is None


# --- W1G2: alternative costs and redirects ---
# Three instants in Nemesis' two alternative-cost cycles, and the effects behind
# them. What is asserted is the board, the life totals and the mana pool — never
# that a sentence parsed: each of these cards could compile ``supported`` and
# still be cast at a price nobody charges, move damage that is not moved, or (as
# Angelic Favor did) exile the wrong object at the end step.
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g2i_table(set_pool, hand, mine=(), theirs=()):
    """Two seats, mana costs **enforced** — every card here is about which
    price is paid, and a game that charges none cannot tell a free cast from an
    ordinary one. Cards are looked up in Nemesis first and then in the base set
    and M21, which hold the basics and the bystanders."""
    pools = (set_pool("NEM"), set_pool("LEA"), set_pool("M21"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [card(name) for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    caster.battlefield.extend(Permanent(card=card(name)) for name in mine)
    other.battlefield.extend(Permanent(card=card(name)) for name in theirs)
    game._sync_control()
    return game, caster, other


def _w1g2i_alternative_offers(game, card):
    """The alternative-cost offers the cast picker shows seat 0, as label and
    payability — what `legality.cast_cost_offers` hands the client."""
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(0, card, spell_hand_index=0)
        if offer["kind"] == "alternative"
    ]


def test_w1g2_angelic_favor_is_cast_only_during_combat(set_pool):
    """"Cast this spell only during combat." (CR 506.7c's window, any step.)

    Refused in the main phase with nothing paid — the creature the alternative
    cost would tap is still untapped — and admitted in the declare attackers
    step.
    """
    game, caster, _ = _w1g2i_table(
        set_pool, ["Angelic Favor"], mine=("Plains", "Grizzly Bears")
    )
    refused = game.cast_from_hand(0, "Angelic Favor", alternative_cost=True)
    assert not refused.supported
    assert not caster.battlefield[1].tapped

    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.cast_from_hand(0, "Angelic Favor", alternative_cost=True).supported


def test_w1g2_angelic_favor_taps_the_chosen_creature_for_a_flying_angel(set_pool):
    """CR 118.9 + CR 601.2b: the alternative cost names *a* creature, so the
    caster chooses which.

    The Hill Giant is the one named here, and it is the one the deterministic
    pick would **not** have taken (it keeps the bigger creature), so a payment
    that ignored the choice would tap the Bears and fail this. Nothing is spent
    from the pool: the mana cost was replaced, not reduced.
    """
    game, caster, _ = _w1g2i_table(
        set_pool, ["Angelic Favor"],
        mine=("Plains", "Grizzly Bears", "Hill Giant"),
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    giant = caster.battlefield[2]

    result = game.cast_from_hand(
        0, "Angelic Favor", alternative_cost=True,
        alternative_cost_permanent_ids=[giant.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert [(p.card.name, p.tapped) for p in caster.battlefield[:3]] == [
        ("Plains", False), ("Grizzly Bears", False), ("Hill Giant", True),
    ]
    angel = caster.battlefield[3]
    assert (angel.card.name, angel.effective_power, angel.effective_toughness) == (
        "Angel Token", 4, 4,
    )
    assert game._has_keyword(angel, "flying")
    assert not any(caster.mana_pool.values())


def test_w1g2_angelic_favor_exiles_the_angel_not_itself(set_pool):
    """"Create a 4/4 … token. **Exile it** at the beginning of the next end
    step."

    The pronoun's antecedent is the token. Read as the ability's source it
    lowered to ``exile_self``, which for an instant meant the end step exiled
    **Angelic Favor out of the graveyard** while the Angel stayed for the rest
    of the game — supported, wrong in the caster's favour, and seen only by
    driving the card to its end step.
    """
    game, caster, _ = _w1g2i_table(
        set_pool, ["Angelic Favor"], mine=("Plains", "Grizzly Bears")
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    game.cast_from_hand(0, "Angelic Favor", alternative_cost=True)
    resolve_stack(game)
    assert "Angel Token" in [p.card.name for p in caster.battlefield]

    game.resolve_end_step(0)
    resolve_stack(game)

    assert [p.card.name for p in caster.battlefield] == ["Plains", "Grizzly Bears"]
    assert [c.name for c in caster.graveyard] == ["Angelic Favor"]
    assert caster.exile == []


def test_w1g2_tap_cost_needs_the_plains_and_takes_a_summoning_sick_creature(set_pool):
    """Two different answers, and they are not one.

    No Plains is **no offer** (CR 601.2b's condition): nothing is shown and the
    alternative cast is refused. With the Plains, a creature that arrived this
    turn can still pay — CR 302.6 forbids a creature's *own* {T} abilities and
    its attacks, and tapping it for another spell's cost is neither.
    """
    card = set_pool("NEM")["Angelic Favor"]
    game, _, _ = _w1g2i_table(
        set_pool, ["Angelic Favor"], mine=("Island", "Grizzly Bears")
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert _w1g2i_alternative_offers(game, card) == []
    assert not game.cast_from_hand(0, "Angelic Favor", alternative_cost=True).supported

    game, caster, _ = _w1g2i_table(
        set_pool, ["Angelic Favor"], mine=("Plains", "Grizzly Bears")
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    bears = caster.battlefield[1]
    bears.metadata["summoning_sickness_turn"] = game.turn
    assert _w1g2i_alternative_offers(game, card) == [
        ("tap an untapped creature you control", True)
    ]
    assert game.cast_from_hand(0, "Angelic Favor", alternative_cost=True).supported
    assert bears.tapped


def test_w1g2_sivvis_valor_moves_every_point_to_the_caster(set_pool):
    """"All damage that would be dealt to target creature this turn is dealt to
    you instead." (CR 614.9.)

    Every source and every event, for the turn: two separate hits from two
    different sources both land on the caster and the creature is unmarked.
    """
    game, caster, other = _w1g2i_table(
        set_pool, ["Sivvi's Valor"],
        mine=("Plains", "Grizzly Bears", "Hill Giant"),
        theirs=("Blood Glutton", "Grizzly Bears"),
    )
    giant = caster.battlefield[2]
    result = game.cast_from_hand(
        0, "Sivvi's Valor", alternative_cost=True,
        target_player_index=0, target_permanent_index=2,
    )
    resolve_stack(game)
    assert result.supported, result.details

    game._mark_damage_on_permanent(giant, 3, source=other.battlefield[1])
    game._mark_damage_on_permanent(giant, 2, source=other.battlefield[1])

    assert giant.damage_marked == 0
    assert caster.life == 15


def test_w1g2_sivvis_valor_damage_is_still_dealt_by_its_source(set_pool):
    """A redirect moves the damage, it does not re-source it: the Blood
    Glutton's controller gains from lifelink (CR 702.15b) for the damage the
    caster took, which a redirect written as a shield plus a fresh damage event
    would have lost."""
    game, caster, other = _w1g2i_table(
        set_pool, ["Sivvi's Valor"],
        mine=("Plains", "Grizzly Bears", "Hill Giant"),
        theirs=("Blood Glutton",),
    )
    giant = caster.battlefield[2]
    game.cast_from_hand(
        0, "Sivvi's Valor", alternative_cost=True,
        target_player_index=0, target_permanent_index=2,
    )
    resolve_stack(game)

    game._mark_damage_on_permanent(giant, 4, source=other.battlefield[0])

    assert (giant.damage_marked, caster.life, other.life) == (0, 16, 24)


def test_w1g2_sivvis_valor_ends_at_cleanup_and_stays_with_its_creature(set_pool):
    """The record lives on the creature, so it goes where the creature goes:
    a copy that re-enters is a new object (CR 400.7) with no record, and the
    cleanup step (CR 514.2) ends the effect on the original."""
    game, caster, other = _w1g2i_table(
        set_pool, ["Sivvi's Valor"],
        mine=("Plains", "Grizzly Bears", "Hill Giant"),
        theirs=("Grizzly Bears",),
    )
    giant = caster.battlefield[2]
    game.cast_from_hand(
        0, "Sivvi's Valor", alternative_cost=True,
        target_player_index=0, target_permanent_index=2,
    )
    resolve_stack(game)
    source = other.battlefield[0]

    fresh = Permanent(card=giant.card)
    caster.battlefield.append(fresh)
    game._sync_control()
    game._mark_damage_on_permanent(fresh, 2, source=source)
    assert (fresh.damage_marked, caster.life) == (2, 20)

    game.resolve_cleanup_step(0)
    game._mark_damage_on_permanent(giant, 1, source=source)
    assert (giant.damage_marked, caster.life) == (1, 20)


def test_w1g2_sivvis_ruse_is_free_only_on_the_printed_board(set_pool):
    """"If an opponent controls a Mountain and you control a Plains, you may
    cast this spell without paying its mana cost." Both clauses, checked at
    CR 601.2b — either missing is no offer, and the mana cost stands."""
    card = set_pool("NEM")["Sivvi's Ruse"]
    for mine, theirs in ((("Plains",), ()), ((), ("Mountain",))):
        game, _, _ = _w1g2i_table(set_pool, ["Sivvi's Ruse"], mine=mine, theirs=theirs)
        assert _w1g2i_alternative_offers(game, card) == []
        assert not game.cast_from_hand(0, "Sivvi's Ruse", alternative_cost=True).supported

    game, caster, _ = _w1g2i_table(
        set_pool, ["Sivvi's Ruse"], mine=("Plains",), theirs=("Mountain",)
    )
    assert _w1g2i_alternative_offers(game, card) == [
        ("cast it without paying its mana cost", True)
    ]
    assert game.cast_from_hand(0, "Sivvi's Ruse", alternative_cost=True).supported
    assert not any(caster.mana_pool.values())


def test_w1g2_sivvis_ruse_shields_your_creatures_and_not_you(set_pool):
    """"Prevent all damage that would be dealt this turn to creatures you
    control."

    The shield hangs off the caster's seat because a class has nothing else to
    hang off, and the seat is exactly what the sentence does not name: damage to
    the caster still lands. An opponent's creature is not "a creature you
    control", and a creature that enters *after* the spell resolved is (CR 615.1:
    a shield watches the event, it is not locked in). Cleanup ends it.
    """
    game, caster, other = _w1g2i_table(
        set_pool, ["Sivvi's Ruse"],
        mine=("Plains", "Grizzly Bears"), theirs=("Mountain", "Hill Giant"),
    )
    game.cast_from_hand(0, "Sivvi's Ruse", alternative_cost=True)
    resolve_stack(game)
    bears, giant = caster.battlefield[1], other.battlefield[1]

    game._mark_damage_on_permanent(bears, 3, source=giant)
    game._deal_damage_to_player(caster, 3, source=giant)
    game._mark_damage_on_permanent(giant, 2, source=bears)
    late = Permanent(card=bears.card)
    caster.battlefield.append(late)
    game._sync_control()
    game._mark_damage_on_permanent(late, 2, source=giant)

    assert (bears.damage_marked, late.damage_marked) == (0, 0)
    assert caster.life == 17
    assert giant.damage_marked == 2

    game.resolve_cleanup_step(0)
    game._mark_damage_on_permanent(bears, 1, source=giant)
    assert bears.damage_marked == 1


# --- W1G4: amounts and bounded targets ---
# Dominate: a target restriction whose bound is the X the same cast announces
# (CR 601.2b announces X before CR 601.2c names the target).
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent


def _w1g4_costed_creature(name, cmc):
    """A 2/2 test creature whose mana value is *cmc*."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="{%d}" % cmc, cmc=float(cmc), type_line=line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": line, "power": "2", "toughness": "2"},
    )


def _w1g4_instant_table(set_pool, seat1):
    """P0 holding Dominate in its main phase, costs unenforced."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", hand=[set_pool("NEM")["Dominate"]]),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_dominate_refuses_a_target_above_the_announced_x(set_pool):
    """"Gain control of target creature with mana value X or less."

    Announced at X=3, a five-drop is not a legal target and the cast is refused
    before anything is paid (CR 601.2c). Before this, the announcement was
    accepted and the resolution's scan then took a *different* creature that
    did answer the bound — one nobody named.
    """
    cheap = _W1g4Permanent(card=_w1g4_costed_creature("Two Drop", 2))
    pricey = _W1g4Permanent(card=_w1g4_costed_creature("Five Drop", 5))
    game = _w1g4_instant_table(set_pool, (cheap, pricey))

    result = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[pricey.permanent_id], x_value=3,
    )

    assert not result.supported
    assert game.controller_index_of(pricey) == 1
    assert game.controller_index_of(cheap) == 1
    assert [card.name for card in game.players[0].hand] == ["Dominate"]


def test_w1g4_dominate_steals_for_good_within_the_bound(set_pool):
    """X=3 at a two-drop: control changes, and with no duration printed it does
    not end at cleanup (CR 611.2a)."""
    cheap = _W1g4Permanent(card=_w1g4_costed_creature("Two Drop", 2))
    game = _w1g4_instant_table(set_pool, (cheap,))

    result = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[cheap.permanent_id], x_value=3,
    )

    assert result.supported, result
    assert game.controller_index_of(cheap) == 0
    game.start_turn(1)
    assert game.controller_index_of(cheap) == 0


def test_w1g4_dominate_bound_is_inclusive_and_x_is_the_announced_one(set_pool):
    """"X **or less**": a creature whose mana value equals X is legal, one above
    is not — the bound is the announced number, not the mana in the pool."""
    exactly = _W1g4Permanent(card=_w1g4_costed_creature("Three Drop", 3))
    game = _w1g4_instant_table(set_pool, (exactly,))

    low = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[exactly.permanent_id], x_value=2,
    )
    assert not low.supported
    exact = game.cast_from_hand(
        0, "Dominate", target_player_index=1,
        target_permanent_ids=[exactly.permanent_id], x_value=3,
    )
    assert exact.supported, exact
    assert game.controller_index_of(exactly) == 0
