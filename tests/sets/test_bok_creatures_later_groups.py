"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.
#
# Characteristics and numbered keywords: two soulshift instances on one line
# (CR 702.46b), soulshift / bushido X counted, protection from a quality or
# from the colours among your permanents, switching every creature's P/T,
# and a target bounded by an announced X.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_put(game, seat, card, *, sick=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g6_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
                interactive=(), mana=False):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                         library=[lea["Island"]] * 10),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    placed = [_w1g6_put(game, 0, card) for card in mine]
    placed += [_w1g6_put(game, 1, card) for card in theirs]
    game.start_turn(0)
    _w1g6_settle(game)
    return game, placed


def _w1g6_names(cards):
    return sorted(card.name for card in cards)


def test_w1g6_forked_branch_garami_soulshifts_twice(set_pool):
    """"Soulshift 4, soulshift 4": two instances, each its own dies trigger
    (CR 702.46b; the 2005-02-01 ruling: "both soulshift abilities trigger").
    A seat nobody asks names a different Spirit card for each, so both come
    back; Body of Jukai (mana value 9) is never offered."""
    bok = set_pool("BOK")
    game, (garami,) = _w1g6_table(
        set_pool, hand=[set_pool("LEA")["Terror"]], mine=[bok["Forked-Branch Garami"]],
        graveyard=[bok["Gnarled Mass"], bok["Traproot Kami"], bok["Body of Jukai"]],
    )
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[garami.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert sum("Forked-Branch Garami triggered (died)" in line for line in game.log) == 2
    assert _w1g6_names(game.players[0].hand) == ["Gnarled Mass", "Traproot Kami"], game.log
    assert "Body of Jukai" in _w1g6_names(game.players[0].graveyard)


def test_w1g6_forked_branch_garami_each_instance_asks_its_own_target(set_pool):
    """An interactive seat is asked once per instance. Naming the same card
    twice is legal (the ruling: "both abilities can attempt to return just
    one Spirit"), and then the second does not resolve (CR 608.2b)."""
    bok = set_pool("BOK")
    game, (garami,) = _w1g6_table(
        set_pool, hand=[set_pool("LEA")["Terror"]], mine=[bok["Forked-Branch Garami"]],
        graveyard=[bok["Gnarled Mass"], bok["Traproot Kami"]], interactive=(0,),
    )
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[garami.permanent_id],
    ).supported
    asked = 0
    while True:
        prompt = _w1g6_settle(game, defaults=False, answers={
            "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
        })
        if prompt is None:
            break
        assert prompt.kind == "trigger_target", prompt
        assert sorted(t["name"] for t in prompt.data["targets"]) == [
            "Gnarled Mass", "Traproot Kami",
        ]
        mass = next(t for t in prompt.data["targets"] if t["name"] == "Gnarled Mass")
        assert game.confirm_trigger_target(
            0, seat=mass["seat"], graveyard_index=mass["graveyard_index"],
        )
        asked += 1
    assert asked == 2
    assert _w1g6_names(game.players[0].hand) == ["Gnarled Mass"], game.log
    assert "Traproot Kami" in _w1g6_names(game.players[0].graveyard)
    assert any("608.2b" in line for line in game.log), game.log


def test_w1g6_mannichi_switches_every_creature_on_the_battlefield(set_pool):
    """"{1}{R}: Switch each creature's power and toughness until end of
    turn." Every creature on the battlefield as it resolves, both sides
    (CR 611.2c): Mannichi 1/2 becomes 2/1 and Bob's Wall of Stone 0/8 becomes
    8/0 and dies (CR 704.5f). A second activation switches back (the
    2021-03-19 ruling), a creature arriving afterwards is not switched, and
    cleanup ends it."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (mannichi, wall) = _w1g6_table(
        set_pool, mine=[bok["Mannichi, the Fevered Dream"]],
        theirs=[lea["Wall of Stone"]],
    )
    assert game.activate_permanent_ability(0, "Mannichi, the Fevered Dream").supported
    _w1g6_settle(game)
    assert (mannichi.effective_power, mannichi.effective_toughness) == (2, 1)
    assert wall not in game.controlled_by(1), game.log

    late = _w1g6_put(game, 0, lea["Hurloon Minotaur"])
    assert (late.effective_power, late.effective_toughness) == (2, 3)
    assert game.activate_permanent_ability(0, "Mannichi, the Fevered Dream").supported
    _w1g6_settle(game)
    assert (mannichi.effective_power, mannichi.effective_toughness) == (1, 2)
    assert (late.effective_power, late.effective_toughness) == (3, 2)
    assert game.activate_permanent_ability(0, "Mannichi, the Fevered Dream").supported
    _w1g6_settle(game)
    assert (mannichi.effective_power, mannichi.effective_toughness) == (2, 1)
    assert (late.effective_power, late.effective_toughness) == (2, 3)
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert (mannichi.effective_power, mannichi.effective_toughness) == (1, 2)


def test_w1g6_fumiko_blocking_gets_bushido_x_for_the_attackers(set_pool):
    """"Fumiko has bushido X, where X is the number of attacking creatures."
    Bob attacks with Grizzly Bears and Hill Giant (Fumiko compels both:
    "Creatures your opponents control attack each combat if able"); Fumiko
    3/2 blocks the Giant, her bushido trigger resolves with two attackers
    (the ruling: counted as it resolves), and the 5/4 kills the Giant and
    survives its 3 damage."""
    from tests.helpers import declare_attack as _w1g6_declare_attack

    lea = set_pool("LEA")
    game, (fumiko, bears, giant) = _w1g6_table(
        set_pool, mine=[set_pool("BOK")["Fumiko the Lowblood"]],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    _w1g6_declare_attack(game, 1, blocks={0: 1})
    _w1g6_drive_combat(game, through="combat_damage")
    assert any("+2/+2" in line for line in game.log), game.log
    assert giant not in game.controlled_by(1), game.log
    assert fumiko in game.controlled_by(0)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (5, 4)
    assert game.players[0].life == 18  # the unblocked Bears


def test_w1g6_fumiko_compels_only_her_opponents_creatures(set_pool):
    """CR 508.1d: Bob may not leave an untapped, unsick creature home while
    Fumiko is on Alice's side; a summoning-sick one is not compelled (the
    ruling); Alice's own creatures attack only if she wants."""
    lea = set_pool("LEA")
    game, (fumiko, bears, giant) = _w1g6_table(
        set_pool, mine=[set_pool("BOK")["Fumiko the Lowblood"]],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    sick = _w1g6_put(game, 1, lea["Gray Ogre"], sick=True)
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    slots = {perm.card.name: slot for slot, perm in enumerate(game.players[1].battlefield)}
    ok, why = game.declare_attackers(1, [slots["Grizzly Bears"]], 0)
    assert not ok and "Hill Giant" in why
    ok, why = game.declare_attackers(
        1, [slots["Grizzly Bears"], slots["Hill Giant"]], 0,
    )
    assert ok, why

    game, (fumiko,) = _w1g6_table(
        set_pool, mine=[set_pool("BOK")["Fumiko the Lowblood"]],
    )
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [], 1)
    assert ok, why


def test_w1g6_harbinger_of_spring_is_protected_from_non_spirit_creatures(set_pool):
    """"Protection from non-Spirit creatures" (CR 702.16a: a card type with a
    creature type excluded). Bob's Grizzly Bears can't block it (702.16f) and
    its combat damage to a blocking Harbinger is prevented (702.16e); Bob's
    Gnarled Mass, a Spirit, blocks it and its damage is dealt."""
    from tests.helpers import declare_attack as _w1g6_declare_attack

    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (harbinger, bears, mass) = _w1g6_table(
        set_pool, mine=[bok["Harbinger of Spring"]],
        theirs=[lea["Grizzly Bears"], bok["Gnarled Mass"]],
    )
    assert not game._can_block_attacker(bears, harbinger)
    assert game._can_block_attacker(mass, harbinger)

    game, (harbinger, bears) = _w1g6_table(
        set_pool, mine=[bok["Harbinger of Spring"]], theirs=[lea["Grizzly Bears"]],
    )
    _w1g6_declare_attack(game, 1, blocks={0: 0})
    _w1g6_drive_combat(game)
    assert harbinger in game.controlled_by(0), game.log
    assert bears not in game.controlled_by(1), game.log

    game, (harbinger, mass) = _w1g6_table(
        set_pool, mine=[bok["Harbinger of Spring"]], theirs=[bok["Gnarled Mass"]],
    )
    _w1g6_declare_attack(game, 1, blocks={0: 0})
    _w1g6_drive_combat(game)
    assert harbinger not in game.controlled_by(0), game.log


def test_w1g6_empty_shrine_kannushi_is_protected_from_its_sides_colours(set_pool):
    """"This creature has protection from each color among permanents you
    control" (CR 702.16i over its controller's board, read now): white for
    itself; black once Black Knight is beside it, so Terror can't target it
    (702.16b) while Lightning Bolt can; Bob's black creature can't block it.
    Black Knight gone, Terror can target it again."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (kannushi, knight, bobs_knight) = _w1g6_table(
        set_pool, hand=[lea["Terror"], lea["Terror"], lea["Lightning Bolt"]],
        mine=[bok["Empty-Shrine Kannushi"], lea["Black Knight"]],
        theirs=[lea["Black Knight"]],
    )
    assert {value for kind, value in game._protection_qualities(kannushi)} == {"W", "B"}
    assert not game._can_block_attacker(bobs_knight, kannushi)
    refused = game.cast_from_hand(
        0, "Terror", target_permanent_ids=[kannushi.permanent_id],
    )
    assert not refused.supported
    # Black Knight has protection from white; Lightning Bolt kills it.
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[knight.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert knight not in game.controlled_by(0)
    assert {value for kind, value in game._protection_qualities(kannushi)} == {"W"}
    assert game._can_block_attacker(bobs_knight, kannushi)
    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[kannushi.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert kannushi not in game.controlled_by(0), game.log


def test_w1g6_minamo_sightbender_reads_the_announced_x(set_pool):
    """"{X}, {T}: Target creature with power X or less can't be blocked this
    turn." X is announced before the target (CR 601.2b/602.2b): X=2 cannot
    name Hill Giant (power 3) and the refusal pays nothing; it names Grizzly
    Bears, which Bob's Wall of Stone then cannot block."""
    from tests.helpers import declare_attack as _w1g6_declare_attack

    lea = set_pool("LEA")
    game, (minamo, bears, giant, wall) = _w1g6_table(
        set_pool, mine=[set_pool("BOK")["Minamo Sightbender"], lea["Grizzly Bears"],
                        lea["Hill Giant"]],
        theirs=[lea["Wall of Stone"]],
    )
    refused = game.activate_permanent_ability(
        0, "Minamo Sightbender", x_value=2, target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported and not minamo.tapped
    assert game.activate_permanent_ability(
        0, "Minamo Sightbender", x_value=2, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert minamo.tapped
    assert not game._can_block_attacker(wall, bears)
    assert game._can_block_attacker(wall, giant)


def test_w1g6_minamo_sightbender_target_grown_past_x_is_illegal(set_pool):
    """The bound is re-asked with the announced X as the ability resolves
    (CR 608.2b): Giant Growth on the Bears in response makes it a 5/5, the
    ability is removed from the stack, and the Bears can still be blocked."""
    lea = set_pool("LEA")
    game, (minamo, bears, wall) = _w1g6_table(
        set_pool, hand=[lea["Giant Growth"]],
        mine=[set_pool("BOK")["Minamo Sightbender"], lea["Grizzly Bears"]],
        theirs=[lea["Wall of Stone"]],
    )
    assert game.queue_permanent_ability(
        0, "Minamo Sightbender", x_value=2, target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert bears.effective_power == 5
    assert any("608.2b" in line for line in game.log), game.log
    assert game._can_block_attacker(wall, bears)


def test_w1g6_quillmane_baku_bounces_up_to_the_counters_removed(set_pool):
    """"{1}, {T}, Remove X ki counters from this creature: Return target
    creature with mana value X or less to its owner's hand." With three ki
    counters: X=2 cannot name Hill Giant (mana value 4); it bounces Bob's
    Grizzly Bears and leaves one counter. X=4 is more counters than it has."""
    from engine.named_counters import add_counters as _w1g6_add
    from engine.named_counters import counters_on as _w1g6_on

    lea = set_pool("LEA")
    game, (baku, bears, giant) = _w1g6_table(
        set_pool, mine=[set_pool("BOK")["Quillmane Baku"]],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    _w1g6_add(baku, "ki", 3)
    assert not game.activate_permanent_ability(
        0, "Quillmane Baku", x_value=4, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert not game.activate_permanent_ability(
        0, "Quillmane Baku", x_value=2, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert _w1g6_on(baku, "ki") == 3 and not baku.tapped
    assert game.activate_permanent_ability(
        0, "Quillmane Baku", x_value=2, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
    assert giant in game.controlled_by(1)
    assert _w1g6_on(baku, "ki") == 1 and baku.tapped


def test_w1g6_quillmane_baku_collects_ki_from_spirit_spells(set_pool):
    """"Whenever you cast a Spirit or Arcane spell, you may put a ki counter
    on this creature": casting Gnarled Mass (a Spirit) offers it."""
    from engine.named_counters import counters_on as _w1g6_on

    bok = set_pool("BOK")
    game, (baku,) = _w1g6_table(
        set_pool, hand=[bok["Gnarled Mass"]], mine=[bok["Quillmane Baku"]],
    )
    assert game.queue_from_hand(0, "Gnarled Mass").supported
    _w1g6_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert _w1g6_on(baku, "ki") == 1, game.log

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g7_ishi_ishi_shoots_the_opponent_who_casts_a_spirit_or_arcane_spell(set_pool):
    """Whenever an opponent casts a Spirit or Arcane spell, Ishi-Ishi deals 2
    damage to that player. An Arcane instant and a Spirit creature spell each
    cost their caster 2; a spell that is neither costs nothing, and neither
    does Ishi-Ishi's own controller's Spirit (the trigger is "an opponent")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool,
        hand=[chk["Kami of the Hunt"]],
        opponent_hand=[chk["Glacial Ray"], lea["Lightning Bolt"], chk["Kami of the Hunt"]],
    )
    _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        1, "Glacial Ray", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [20, 18]
    assert "Ishi-Ishi, Akki Crackshot dealt 2 damage to P1" in game.log
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    # Its controller's own Spirit spell is no opponent's.
    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    game.start_turn(1)
    _w1g7_settle(game)
    assert game.cast_from_hand(1, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 16]


def _w1g7_activate(game, permanent, seat, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    return result


def test_w1g7_shimmering_glasskite_counters_only_the_first_targeting_each_turn(set_pool):
    """Whenever this creature becomes the target of a spell or ability for the
    first time each turn, counter that spell or ability. The opponent's first
    Lightning Bolt at it is countered (the Bolt goes to the graveyard, the
    Glasskite takes no damage); a second targeting the same turn — an
    activated ability — resolves. The count is swept in the cleanup step, so
    next turn's first targeting is countered again."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    glass = _w1g7_put(game, bok["Shimmering Glasskite"])
    sorcerer = _w1g7_put(game, lea["Prodigal Sorcerer"], seat=1)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Shimmering Glasskite and moved to graveyard" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt"]
    _w1g7_activate(game, sorcerer, 1, target_permanent_ids=[glass.permanent_id])
    _w1g7_settle(game)
    assert "Prodigal Sorcerer dealt 1 damage to Shimmering Glasskite" in game.log
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    sorcerer.tapped = False
    _w1g7_activate(game, sorcerer, 1, target_permanent_ids=[glass.permanent_id])
    _w1g7_settle(game)
    assert game.log.count("Shimmering Glasskite countered Prodigal Sorcerer's ability") == 1
    assert glass.damage_marked == 0


def test_w1g7_jetting_glasskite_counters_its_controllers_own_spell_and_a_trigger(set_pool):
    """"That spell or ability" is whichever targeted it first, whoever controls
    it: its own controller's Giant Growth is countered (no +3/+3). On the next
    turn the first targeting is an opponent's **triggered** ability —
    Flametongue Kavu's entry trigger, "it deals 4 damage to target creature" —
    and the trigger is countered (CR 701.6a: an ability has no card to bin)."""
    bok, lea, pls = set_pool("BOK"), set_pool("LEA"), set_pool("PLS")
    game = _w1g7_table(
        set_pool, hand=[lea["Giant Growth"]], opponent_hand=[pls["Flametongue Kavu"]],
    )
    glass = _w1g7_put(game, bok["Jetting Glasskite"])
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert glass.effective_power == 4
    assert "Giant Growth was countered by Jetting Glasskite and moved to graveyard" in game.log
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    assert game.cast_from_hand(
        1, "Flametongue Kavu", target_permanent_ids=[glass.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Jetting Glasskite countered Flametongue Kavu's ability" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0


def test_w1g7_kira_grants_each_creature_its_own_first_time_counter(set_pool):
    """Creatures you control have the Glasskite's trigger. A Grizzly Bears
    under Kira counters the first Bolt at it; a Glasskite under Kira holds the
    ability twice (printed and granted), both trigger, the first counters and
    the second finds nothing to counter — and a person is not asked to order
    two instances of one ability (the granted line is recorded lowercase)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool, opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
        interactive=(0,),
    )
    _w1g7_put(game, bok["Kira, Great Glass-Spinner"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    glass = _w1g7_put(game, bok["Shimmering Glasskite"])
    game._recompute_continuous_effects()
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Grizzly Bears and moved to graveyard" in game.log
    assert game.is_on_battlefield(bears)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[glass.permanent_id]
    ).supported
    assert not [c for c in game.pending_choices if c.kind == "order_triggers"]
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Shimmering Glasskite and moved to graveyard" in game.log
    assert game.is_on_battlefield(glass) and glass.damage_marked == 0


def test_w1g7_kira_arriving_after_a_creature_was_targeted_counters_nothing_that_turn(set_pool):
    """"For the first time each turn" is the creature's history, kept whatever
    it said: a Grizzly Bears targeted by its controller's Giant Growth before
    Kira arrived has had its first time, so the opponent's Bolt that turn
    resolves. Kira itself, never targeted, still counters its own first."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool, hand=[lea["Giant Growth"], bok["Kira, Great Glass-Spinner"]],
        opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert bears.effective_power == 5
    assert game.cast_from_hand(0, "Kira, Great Glass-Spinner").supported
    _w1g7_settle(game)
    (kira,) = [p for p in game.all_permanents() if p.card.name.startswith("Kira")]
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt dealt 3 damage to Grizzly Bears" in game.log
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[kira.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert "Lightning Bolt was countered by Kira, Great Glass-Spinner and moved to graveyard" in game.log
    assert game.is_on_battlefield(kira)

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (declare_attack as _w1g8_declare_attack,
                           drive_combat as _w1g8_drive_combat,
                           settle as _w1g8_settle,
                           stock_libraries as _w1g8_stock_libraries)

_W1G8_KEPT = "kept_until_end_of_turn"


def _w1g8_table(*boards):
    """A two-seat game, libraries stocked, mana costs enforced; *boards* is a
    list of cards per seat, each put onto the battlefield untouched by
    summoning sickness."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0"), _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game.enforce_mana_costs = True
    placed = []
    for seat, cards in enumerate(boards):
        for each in cards:
            permanent = _w1g8_Permanent(card=each)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    game._sync_control()
    game.active_player_index = 0
    return game, placed


def _w1g8_kept(game, seat):
    return dict(game.players[seat].restricted_mana.get(_W1G8_KEPT, {}))


def _w1g8_to_main(game, seat):
    """Run *seat*'s beginning phase — untap, upkeep, draw — and enter its
    precombat main phase."""
    game.active_player_index = seat
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)
    game.resolve_upkeep(seat)
    _w1g8_settle(game)
    game.resolve_draw_step(seat)
    _w1g8_settle(game)
    game.enter_next_turn_phase("beginning")


def test_w1g8_springcaller_mana_stays_through_the_turn_and_is_spent_last(set_pool):
    """"At the beginning of your upkeep, add {G}. Until end of turn, you don't
    lose this mana as steps and phases end." Made in the upkeep, kept through
    the draw step's end (CR 500.5's emptying excepted for this unit), still
    there in the main phase; a Forest's {G} beside it is the one a {G} spell
    spends (CR 601.2h: the payer keeps the mana that stays), and the kept {G}
    survives the main phase's end, the combat and the end step, and empties
    as the cleanup step ends (CR 514.2 ended the effect as it began)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (_, forest) = _w1g8_table([bok["Sakura-Tribe Springcaller"], lea["Forest"]], [])
    game.players[0].hand.append(lea["Llanowar Elves"])
    _w1g8_to_main(game, 0)
    assert game.current_step == "precombat_main"
    assert _w1g8_kept(game, 0) == {"G": 1}
    assert game.players[0].mana_pool["G"] == 0
    assert "Sakura-Tribe Springcaller produced {G} (kept until end of turn)" in game.log

    game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    cast = game.cast_from_hand(0, "Llanowar Elves")
    _w1g8_settle(game)
    assert cast.supported, cast.details
    assert any(p.card.name == "Llanowar Elves" for p in game.players[0].battlefield)
    assert game.players[0].mana_pool["G"] == 0
    assert _w1g8_kept(game, 0) == {"G": 1}, "the Forest's {G} paid; the kept one stays"

    game.enter_next_turn_phase("precombat_main")
    game.enter_next_turn_phase("combat")
    game.enter_next_turn_phase("postcombat_main")
    assert _w1g8_kept(game, 0) == {"G": 1}
    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert _w1g8_kept(game, 0) == {"G": 1}
    game.resolve_cleanup_step(0)
    assert not any(_w1g8_kept(game, 0).values())


def test_w1g8_kept_mana_pays_an_activation_and_an_effects_tax(set_pool):
    """Kept mana is plain mana that stays: it pays an activated ability (a
    payment with a purpose) and an effect-collected "unless … pays" (a payment
    with none, CR 605.3a's road) — Springcaller's {G} into a later step."""
    from engine.restricted_mana import mana_bucket, take_from_pool

    game, _ = _w1g8_table([], [])
    player = game.players[0]
    mana_bucket(player, _W1G8_KEPT)["G"] = 2
    player.mana_pool["G"] = 1
    # The payer's order: the open pool before the kept bucket.
    assert take_from_pool(player, None, "G", 2) == 0
    assert player.mana_pool["G"] == 0 and _w1g8_kept(game, 0) == {"G": 1}
    plan = game.effect_payment_plan(player, {"generic": 1})
    assert plan is not None and not plan.tapped
    assert game._pay_planned_cost(player, lambda: game.effect_payment_plan(player, {"generic": 1}))
    assert not any(_w1g8_kept(game, 0).values())


def test_w1g8_shizuko_feeds_each_player_in_their_own_upkeep(set_pool):
    """"At the beginning of each player's upkeep, that player adds {G}{G}{G}.
    Until end of turn, they don't lose this mana as steps and phases end."
    The mana goes to the player whose upkeep it is — the opponent included —
    and stays into that player's main phase."""
    bok = set_pool("BOK")
    game, _ = _w1g8_table([bok["Shizuko, Caller of Autumn"]], [])
    _w1g8_to_main(game, 1)
    assert _w1g8_kept(game, 1) == {"G": 3}
    assert not any(_w1g8_kept(game, 0).values())
    assert "Shizuko, Caller of Autumn: P1 added 3 mana (kept until end of turn)" in game.log


def test_w1g8_sakiko_adds_that_much_green_per_creature_dealing_combat_damage(set_pool):
    """"Whenever a creature you control deals combat damage to a player, add
    that much {G}." One trigger per creature, each sized by the damage that
    creature dealt (the event's own number, CR 120.4b); the mana stays into
    the postcombat main phase."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (sakiko, _, _) = _w1g8_table(
        [bok["Sakiko, Mother of Summer"], lea["Grizzly Bears"], lea["Hill Giant"]], [],
    )
    game.enforce_mana_costs = False
    sakiko.tapped = True   # stays home: two attackers, 2 and 3 damage
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 15
    assert _w1g8_kept(game, 0) == {"G": 5}
    assert "Sakiko, Mother of Summer produced {G}{G}{G} (kept until end of turn)" in game.log
    assert "Sakiko, Mother of Summer produced {G}{G} (kept until end of turn)" in game.log
    assert game.current_step == "postcombat_main"


def _w1g8_accept(game, choice):
    game.confirm_optional_pay(choice.player_index, accept=True)


def _w1g8_decline(game, choice):
    game.confirm_optional_pay(choice.player_index, accept=False)


def test_w1g8_blademane_baku_gets_two_power_per_counter_its_cost_removed(set_pool):
    """"{1}, Remove X ki counters from this creature: For each counter
    removed, this creature gets +2/+0 until end of turn." Two Spirit casts,
    the person at seat 0 taking the first ki counter and declining nothing
    the second time; X=2 is paid and the Baku is 5/1 (1 + 2×2), the counters
    gone; X=1 on a fresh counter is +2 more, and the pump ends at cleanup."""
    from engine.named_counters import counters_on

    bok = set_pool("BOK")
    game, (blade,) = _w1g8_table([bok["Blademane Baku"]], [])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._set_phase_and_step("precombat_main", "precombat_main")
    for answer in (_w1g8_accept, _w1g8_accept, _w1g8_decline):
        game.players[0].hand.append(bok["Petalmane Baku"])
        assert game.cast_from_hand(0, "Petalmane Baku").supported
        _w1g8_settle(game, answers={"optional_pay": answer})
    assert counters_on(blade, "ki") == 2, "two taken, one declined"

    pumped = game.activate_permanent_ability(0, "Blademane Baku", x_value=2)
    _w1g8_settle(game)
    assert pumped.supported, pumped.details
    assert counters_on(blade, "ki") == 0
    assert (blade.effective_power, blade.effective_toughness) == (5, 1)
    assert "Blademane Baku gets +4/+0 until end of turn" in game.log
    # No counter left: X=1 is unpayable and refused with nothing paid.
    refused = game.activate_permanent_ability(0, "Blademane Baku", x_value=1)
    assert not refused.supported
    assert blade.effective_power == 5
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert blade.effective_power == 1


def test_w1g8_the_wire_bounds_a_removal_x_by_the_counters_held(set_pool):
    """A person's X prompt for "{1}, Remove X ki counters from this
    creature: …" is sized by the server (``web/offers.ability_x_payable``):
    the counters the Baku holds bound it whatever the mana says, and
    ``counter_bound`` names the store; with {1} unpayable nothing is."""
    from engine.named_counters import add_counters
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities
    from web.offers import ability_x_payable

    bok = set_pool("BOK")
    game, (blade,) = _w1g8_table([bok["Blademane Baku"]], [])
    add_counters(blade, "ki", 2)
    (ability,) = usable_activated_abilities(compile_card_oracle(blade.card))
    game.players[0].mana_pool["C"] = 5
    payable = ability_x_payable(game, 0, blade, ability)
    assert payable["pool"] == 2 and payable["board"] == 2
    assert payable["counter_bound"] == {"kind": "ki", "count": 2}
    game.players[0].mana_pool["C"] = 0
    payable = ability_x_payable(game, 0, blade, ability)
    assert payable["pool"] == 0 and payable["board"] == 0


def test_w1g8_for_each_counter_removed_needs_a_removal_cost():
    """The leading "For each counter removed," counts the ability's own
    removal cost; on an ability whose cost removes nothing the words name
    nothing, and the line refuses rather than pumping by zero."""
    from engine.grammar import compile_line

    line = "For each counter removed, this creature gets +2/+0 until end of turn."
    assert compile_line("{1}, Remove X ki counters from this creature: " + line).instructions
    assert not compile_line("{1}: " + line).instructions


def test_w1g8_the_ai_announces_a_removal_x_and_never_one_it_cannot_pay(set_pool):
    """The ki Baku's "Remove X ki counters" is an X the activator announces
    (CR 107.3a via 602.2b). Skullmane Baku with two counters is proposed at
    X=2 on the 2/2 it kills; Waxmane Baku, whose X sizes its target list, is
    declined rather than proposed for an X of 0 and refused (the base's
    activation-cost census red)."""
    from engine.ai_abilities import choose_activation_action
    from engine.named_counters import add_counters

    bok, lea = set_pool("BOK"), set_pool("LEA")
    for name, expected in (("Skullmane Baku", 2), ("Waxmane Baku", None)):
        game, (baku, *_rest) = _w1g8_table(
            [bok[name]] + [lea["Forest"]] * 3, [lea["Grizzly Bears"]],
        )
        game.interactive_seats = set()
        game._set_phase_and_step("precombat_main", "precombat_main")
        add_counters(baku, "ki", 2)
        action = choose_activation_action(game, 0)
        if expected is None:
            assert action is None or action.permanent_name != name
            continue
        assert action is not None and action.permanent_name == name
        assert action.x_value == expected
        bears = game.players[1].battlefield[0]
        assert action.target_permanent_ids == [bears.permanent_id]


def _w1g8_upkeep(game, seat=0):
    game.active_player_index = seat
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)
    game.resolve_upkeep(seat)


def test_w1g8_chisei_is_sacrificed_unless_a_counter_comes_off_your_permanent(set_pool):
    """"At the beginning of your upkeep, sacrifice Chisei unless you remove a
    counter from a permanent you control." With no counter on anything its
    controller controls the price cannot be paid and Chisei goes (the
    opponent's ki counters are no resource of theirs); with one, the counter
    comes off and Chisei stays."""
    from engine.named_counters import add_counters, counters_on

    bok = set_pool("BOK")
    game, (chisei, theirs) = _w1g8_table(
        [bok["Chisei, Heart of Oceans"]], [bok["Petalmane Baku"]],
    )
    add_counters(theirs, "ki", 2)
    _w1g8_upkeep(game)
    _w1g8_settle(game)
    assert not any(p is chisei for p in game.players[0].battlefield)
    assert chisei.card in game.players[0].graveyard
    assert counters_on(theirs, "ki") == 2

    game, (chisei, baku, theirs) = _w1g8_table(
        [bok["Chisei, Heart of Oceans"], bok["Petalmane Baku"]], [bok["Petalmane Baku"]],
    )
    add_counters(baku, "ki", 2)
    add_counters(theirs, "ki", 2)
    _w1g8_upkeep(game)
    _w1g8_settle(game)
    assert any(p is chisei for p in game.players[0].battlefield)
    assert (counters_on(baku, "ki"), counters_on(theirs, "ki")) == (1, 2)
    assert "Chisei, Heart of Oceans removed a ki counter from Petalmane Baku" in game.log


def test_w1g8_chisei_asks_a_person_whether_and_from_which_permanent(set_pool):
    """The interactive seat is offered the price (``optional_pay``) and, taking
    it, picks the permanent (``permanent_choice``) among its own that hold a
    counter — here the Baku Altar, not the Baku. Declining sacrifices Chisei."""
    from engine.named_counters import add_counters, counters_on

    bok = set_pool("BOK")
    for take in (True, False):
        game, (chisei, baku, altar, bare) = _w1g8_table([
            bok["Chisei, Heart of Oceans"], bok["Petalmane Baku"],
            bok["Baku Altar"], bok["Skullmane Baku"],
        ], [])
        add_counters(baku, "ki", 2)
        add_counters(altar, "ki", 1)
        game.interactive_seats = {0}
        _w1g8_upkeep(game)
        owed = _w1g8_settle(game, defaults=False)
        assert owed is not None and owed.kind == "optional_pay"
        game.confirm_optional_pay(0, accept=take)
        if not take:
            _w1g8_settle(game)
            assert not any(p is chisei for p in game.players[0].battlefield)
            continue
        owed = _w1g8_settle(game, defaults=False)
        assert owed is not None and owed.kind == "permanent_choice"
        offered = {p.permanent_id for p in game.live_permanent_choices(owed)}
        assert offered == {baku.permanent_id, altar.permanent_id}, "only what holds a counter"
        assert game.confirm_permanent_choice(0, altar.permanent_id)
        _w1g8_settle(game)
        assert any(p is chisei for p in game.players[0].battlefield)
        assert (counters_on(baku, "ki"), counters_on(altar, "ki")) == (2, 0)


def _w1g8_flipped(bok, name):
    """*name* on seat 0's battlefield, two Spirit casts taking a ki counter
    each, then the end step's "you may flip it" accepted (CR 710)."""
    from engine.named_counters import counters_on

    game, (flip,) = _w1g8_table([bok[name]], [])
    game.enforce_mana_costs = False
    game._set_phase_and_step("precombat_main", "precombat_main")
    for _ in range(2):
        game.players[0].hand.append(bok["Petalmane Baku"])
        assert game.cast_from_hand(0, "Petalmane Baku").supported
        _w1g8_settle(game, answers={"optional_pay": _w1g8_accept})
    assert counters_on(flip, "ki") == 2
    game.resolve_end_step(0)
    _w1g8_settle(game, answers={"optional_pay": _w1g8_accept})
    game.resolve_cleanup_step(0)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, flip


def test_w1g8_the_ki_flip_cards_flip_and_their_bottom_halves_work(set_pool):
    """The five ki flip cards: two Spirit casts, two ki counters, flipped at
    the end step, and each bottom half's ki ability spends a counter and does
    what it prints — Kaiso's prevention (a Lightning Bolt into the shielded
    creature), Scarmaker's fear, Azamuki's control until end of turn, Ichiga's
    +2/+2 (and trample)."""
    from engine.named_counters import counters_on

    bok, lea = set_pool("BOK"), set_pool("LEA")

    game, kaiso = _w1g8_flipped(bok, "Faithful Squire")
    assert kaiso.card.name == "Kaiso, Memory of Loyalty" and kaiso.has_keyword("flying")
    bears = _w1g8_Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    assert game.activate_permanent_ability(
        0, kaiso.card.name, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_settle(game)
    game.players[0].hand.append(lea["Lightning Bolt"])
    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    _w1g8_settle(game)
    assert game.is_on_battlefield(bears) and counters_on(kaiso, "ki") == 1

    game, scarmaker = _w1g8_flipped(bok, "Hired Muscle")
    assert scarmaker.card.name == "Scarmaker"
    assert game.activate_permanent_ability(
        0, "Scarmaker", target_permanent_ids=[scarmaker.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert scarmaker.has_keyword("fear")

    game, azamuki = _w1g8_flipped(bok, "Cunning Bandit")
    assert azamuki.card.name == "Azamuki, Treachery Incarnate"
    ogre = _w1g8_Permanent(card=lea["Gray Ogre"])
    game._put_permanent_onto_battlefield(1, ogre, None)
    game._sync_control()
    assert game.activate_permanent_ability(
        0, azamuki.card.name, target_permanent_ids=[ogre.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert game.controller_index_of(ogre) == 0
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert game.controller_index_of(ogre) == 1

    game, ichiga = _w1g8_flipped(bok, "Budoka Pupil")
    assert ichiga.card.name == "Ichiga, Who Topples Oaks" and ichiga.has_keyword("trample")
    assert game.activate_permanent_ability(
        0, ichiga.card.name, target_permanent_ids=[ichiga.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (ichiga.effective_power, ichiga.effective_toughness) == (6, 5)


def test_w1g8_jaraku_counters_a_spell_unless_its_controller_pays_two(set_pool):
    """Callow Jushi flipped: "Remove a ki counter from Jaraku: Counter target
    spell unless its controller pays {2}." A caster with no mana left loses
    the spell; one with two untapped Forests pays and keeps it."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    for forests, countered in ((0, True), (2, False)):
        game, jaraku = _w1g8_flipped(bok, "Callow Jushi")
        assert jaraku.card.name == "Jaraku the Interloper"
        game.enforce_mana_costs = True
        for _ in range(forests):
            land = _w1g8_Permanent(card=lea["Forest"])
            game._put_permanent_onto_battlefield(1, land, None)
        game._sync_control()
        game.players[1].hand.append(lea["Grizzly Bears"])
        game.players[1].mana_pool["G"] = 2
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Grizzly Bears").supported
        assert game.activate_permanent_ability(
            0, "Jaraku the Interloper", target_stack_index=0,
        ).supported
        _w1g8_settle(game)
        bears_out = any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1))
        assert bears_out is not countered
        assert ("Grizzly Bears" in [c.name for c in game.players[1].graveyard]) is countered


def test_w1g8_jaraku_asks_the_spells_controller_whether_to_pay(set_pool):
    """Both seats interactive. Jaraku's activation is offered the spell its
    picker lists and accepted at it (the activation gate and the picker on one
    list, ``derive_activation_spec``); the spell's controller, who can pay
    {2} off two Forests, is asked (``mana_payment``) — declining loses the
    spell, paying keeps it — and the ki counter is spent either way."""
    from engine.named_counters import counters_on

    lea = set_pool("LEA")
    bok = set_pool("BOK")
    for pay in (False, True):
        game, jaraku = _w1g8_flipped(bok, "Callow Jushi")
        game.enforce_mana_costs = True
        game.interactive_seats = {0, 1}
        for _ in range(2):
            game._put_permanent_onto_battlefield(
                1, _w1g8_Permanent(card=lea["Forest"]), None,
            )
        game._sync_control()
        game.players[1].hand.append(lea["Grizzly Bears"])
        game.players[1].mana_pool["G"] = 2
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Grizzly Bears").supported
        before = counters_on(jaraku, "ki")
        assert game.activate_permanent_ability(
            0, "Jaraku the Interloper", target_stack_index=0,
        ).supported
        assert counters_on(jaraku, "ki") == before - 1
        owed = _w1g8_settle(game, defaults=False)
        assert owed is not None and owed.kind == "mana_payment"
        assert owed.player_index == 1 and owed.data["amount"] == 2
        assert game.confirm_mana_payment(1, pay)
        _w1g8_settle(game)
        bears_out = any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1))
        assert bears_out is pay
        assert ("Grizzly Bears" in [c.name for c in game.players[1].graveyard]) is not pay


def test_w1g8_the_ki_baku_spend_x_counters_on_x(set_pool):
    """Petalmane, Skullmane and Waxmane Baku with three ki counters each, X=2:
    {G}{G} added; a 3/3 at 1/1; two creatures tapped — one counter left on
    each."""
    from engine.named_counters import add_counters, counters_on

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (petal, skull, wax, giant, bears, ogre) = _w1g8_table(
        [bok["Petalmane Baku"], bok["Skullmane Baku"], bok["Waxmane Baku"]],
        [lea["Hill Giant"], lea["Grizzly Bears"], lea["Gray Ogre"]],
    )
    game.enforce_mana_costs = False
    game._set_phase_and_step("precombat_main", "precombat_main")
    for baku in (petal, skull, wax):
        add_counters(baku, "ki", 3)
    assert game.activate_permanent_ability(
        0, "Petalmane Baku", x_value=2, mana_color="G",
    ).supported
    _w1g8_settle(game)
    assert game.players[0].mana_pool["G"] == 2
    assert game.activate_permanent_ability(
        0, "Skullmane Baku", x_value=2, target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    assert game.activate_permanent_ability(
        0, "Waxmane Baku", x_value=2,
        target_permanent_ids=[bears.permanent_id, ogre.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert bears.tapped and ogre.tapped and not giant.tapped
    assert [counters_on(b, "ki") for b in (petal, skull, wax)] == [1, 1, 1]


def test_w1g8_the_kept_sentence_names_the_pool_it_keeps():
    """"…**you** don't lose this mana" after "that player adds", or "**they**"
    after a bare "Add", names a pool the mana did not go into: refused, never
    kept in the wrong pool."""
    from engine.grammar import compile_line

    kept = "Until end of turn, {} don't lose this mana as steps and phases end."
    good = compile_line(
        "At the beginning of each player's upkeep, that player adds {G}{G}{G}. "
        + kept.format("they")
    )
    assert good.instructions[0].payload["spend_only"] == _W1G8_KEPT
    for line in (
        "At the beginning of each player's upkeep, that player adds {G}{G}{G}. "
        + kept.format("you"),
        "At the beginning of your upkeep, add {G}. " + kept.format("they"),
    ):
        assert not compile_line(line).instructions, line

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("BOK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_marauder_attacks(set_pool, theirs=(), interactive=()):
    """Alice's Ogre Marauder declared attacking Bob (CR 508.1), its trigger
    on the stack; returns ``(game, marauder, bob's permanents)``."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", library=[card("Forest")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = []
    for seat, name in [(0, "Ogre Marauder"), *((1, n) for n in theirs)]:
        permanent = _W1G9Permanent(card=card(name))
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    return game, placed[0], placed[1:]


def _w1g9_slot(game, permanent):
    seat = game.controller_index_of(permanent)
    return [p.permanent_id for p in game.players[seat].battlefield].index(
        permanent.permanent_id
    )


# Ogre Marauder: "Whenever this creature attacks, it gains 'this creature
# can't be blocked' until end of turn unless defending player sacrifices a
# creature of their choice." CR 118.12a's toll, offered to the seat the attack
# froze (CR 506.2), who performs the sacrifice themselves.


def test_w1g9_ogre_marauder_defender_sacrifices_a_creature_of_their_choice(set_pool):
    """Bob, asked as a person, pays the toll and picks his Hill Giant out of
    two creatures; the Marauder stays blockable and his Bears blocks it."""
    game, marauder, (bears, giant) = _w1g9_marauder_attacks(
        set_pool, theirs=["Grizzly Bears", "Hill Giant"], interactive=(1,),
    )
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("optional_pay", 1)
    game.confirm_optional_pay(1, accept=True)
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("sacrifice", 1)
    assert game.confirm_sacrifice(1, permanent_ids=[giant.permanent_id])
    _w1g9_settle(game)
    assert [c.name for c in game.players[1].graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(bears)
    assert game.players[0].graveyard == []
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {_w1g9_slot(game, bears): _w1g9_slot(game, marauder)})
    assert ok, why


def test_w1g9_ogre_marauder_declined_toll_makes_it_unblockable(set_pool):
    """Bob declines: nothing is sacrificed and the Marauder gains "this
    creature can't be blocked" — his Bears may not block it."""
    game, marauder, (bears,) = _w1g9_marauder_attacks(
        set_pool, theirs=["Grizzly Bears"], interactive=(1,),
    )
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("optional_pay", 1)
    game.confirm_optional_pay(1, accept=False)
    _w1g9_settle(game)
    assert game.is_on_battlefield(bears)
    assert "This creature can't be blocked" in marauder.effective_card.oracle_text
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {_w1g9_slot(game, bears): _w1g9_slot(game, marauder)})
    assert not ok


def test_w1g9_ogre_marauder_defender_with_no_creature_cannot_pay(set_pool):
    """2005-02-01 ruling: the defender must sacrifice a creature "or Ogre
    Marauder can't be blocked for the rest of the turn". With no creature the
    toll cannot be paid and nothing is asked: the Marauder is unblockable,
    and the damage lands."""
    game, marauder, _ = _w1g9_marauder_attacks(set_pool, interactive=(1,))
    assert _w1g9_settle(game, defaults=False) is None
    assert "This creature can't be blocked" in marauder.effective_card.oracle_text
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g9_drive_combat(game)
    assert game.players[1].life == 17

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

from engine import Game as _W1G10Game
from engine.models import Permanent as _W1G10Permanent
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_game(*, mine=(), hand=(), library=(), graveyard=(), theirs=(),
                opponent_hand=(), opponent_library=None, island=None):
    """Alice's first main phase, costs off, both seats headless."""
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name="Alice", hand=list(hand), library=list(library),
            graveyard=list(graveyard),
            battlefield=[_W1G10Permanent(card=c) for c in mine],
        ),
        _W1G10PlayerState(
            name="Bob", hand=list(opponent_hand),
            battlefield=[_W1G10Permanent(card=c) for c in theirs],
            library=list(opponent_library if opponent_library is not None
                         else [island] * 10),
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    for perm in game.all_permanents():
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def _w1g10_tallowisp_game(set_pool):
    bok, lea, leg = set_pool("BOK"), set_pool("LEA"), set_pool("LEG")
    library = [lea["Wild Growth"], lea["Animate Dead"], leg["Cocoon"],
               lea["Holy Strength"], lea["Island"]]
    return _w1g10_game(
        mine=[bok["Tallowisp"]], hand=[bok["Bile Urchin"], lea["Grizzly Bears"]],
        library=library, island=lea["Island"],
    )


def test_w1g10_tallowisp_finds_only_an_aura_with_enchant_creature(set_pool):
    """Tallowisp: "Whenever you cast a Spirit or Arcane spell, you may search
    your library for an Aura card with enchant creature, reveal it, put it
    into your hand, then shuffle." Asked of a person: Bile Urchin (a Spirit)
    triggers it; the search refuses Wild Growth (enchant land), Animate Dead
    ("enchant creature card in a graveyard") and Cocoon ("enchant creature you
    control") — CR 702.5a's ability is its whole subject — and takes Holy
    Strength."""
    game = _w1g10_tallowisp_game(set_pool)
    game.interactive_seats = {0}
    alice = game.players[0]
    assert game.cast_from_hand(0, "Bile Urchin").supported
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "search_library"
    names = [card.name for card in alice.library]
    for refused in ("Wild Growth", "Animate Dead", "Cocoon", "Island"):
        assert not game.confirm_search_library(0, names.index(refused)), refused
    assert game.confirm_search_library(0, names.index("Holy Strength"))
    _w1g10_settle(game)
    assert sorted(card.name for card in alice.hand) == ["Grizzly Bears", "Holy Strength"]
    assert len(alice.library) == 4


def test_w1g10_tallowisp_ignores_a_spell_that_is_neither_spirit_nor_arcane(set_pool):
    """A Grizzly Bears is no Spirit: nothing triggers. A headless seat takes
    the offer on Bile Urchin and finds the one legal Aura."""
    game = _w1g10_tallowisp_game(set_pool)
    alice = game.players[0]
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Bile Urchin"]
    assert len(alice.library) == 5
    assert game.cast_from_hand(0, "Bile Urchin").supported
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Holy Strength"]


def _w1g10_tomorrow_game(set_pool, library_names):
    bok, lea = set_pool("BOK"), set_pool("LEA")
    return _w1g10_game(
        mine=[bok["Tomorrow, Azami's Familiar"]],
        library=[lea[name] for name in library_names], island=lea["Island"],
    )


def test_w1g10_tomorrow_replaces_each_draw_with_a_look_and_a_keep(set_pool):
    """Tomorrow, Azami's Familiar: "If you would draw a card, look at the top
    three cards of your library instead. Put one of those cards into your hand
    and the rest on the bottom of your library in any order." Two draws, asked
    of a person, are two looks in turn (2005-02-01): Alice keeps the Hill Giant
    of the first three and orders the other two onto the bottom; the second
    look is of the new top three, and the second draw waited for the first."""
    game = _w1g10_tomorrow_game(set_pool, [
        "Grizzly Bears", "Hill Giant", "Island", "Forest", "Lightning Bolt", "Dark Ritual",
    ])
    game.interactive_seats = {0}
    alice = game.players[0]
    drawn_before = list(alice.cards_drawn_this_turn)
    assert game._draw_with_replacements(alice, 2) == 0
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "look_top_pick" and owed.data["top_count"] == 3
    assert alice.hand == []
    assert game.confirm_look_top_pick(0, 1)
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "reorder_library" and owed.data["position"] == "bottom"
    assert game.confirm_reorder_library(0, [1, 0])
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "look_top_pick"
    assert [card.name for card in alice.library[:3]] == ["Forest", "Lightning Bolt", "Dark Ritual"]
    assert game.confirm_look_top_pick(0, 2)
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Hill Giant", "Dark Ritual"]
    assert [card.name for card in alice.library] == [
        "Island", "Grizzly Bears", "Forest", "Lightning Bolt",
    ]
    # Not a draw: nothing was drawn, so no draw trigger has anything to see.
    assert alice.cards_drawn_this_turn == drawn_before
    assert not any("Hill Giant" in line or "Dark Ritual" in line for line in game.log)


def test_w1g10_tomorrow_on_a_short_library_and_an_empty_one(set_pool):
    """Fewer than three cards: one is kept and the rest put back; no cards:
    nothing happens, and the player does not lose for drawing from an empty
    library while Tomorrow applies (2005-02-01) — the draw step's draw is
    replaced too."""
    game = _w1g10_tomorrow_game(set_pool, ["Grizzly Bears"])
    alice = game.players[0]
    assert [card.name for card in alice.hand] == []
    assert game._draw_with_replacements(alice, 1) == 0
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Grizzly Bears"]
    assert alice.library == []
    assert game._draw_with_replacements(alice, 3) == 0
    _w1g10_settle(game)
    game.check_state_based_actions()
    assert not alice.lost and not game.is_game_over()
    assert any("has no card to look at instead of drawing" in line for line in game.log)


def test_w1g10_tomorrow_replaces_the_draw_step_draw(set_pool):
    """The draw step's draw (CR 504.1) is a draw like any other: a headless
    seat keeps a card of the top three, the rest go to the bottom."""
    game = _w1g10_tomorrow_game(set_pool, [
        "Grizzly Bears", "Hill Giant", "Island", "Forest",
    ])
    alice = game.players[0]
    hand_before, library_before = len(alice.hand), len(alice.library)
    game.turn = 3  # not the first turn's skipped draw (CR 103.8a)
    game.resolve_draw_step(0)
    _w1g10_settle(game)
    assert len(alice.hand) == hand_before + 1
    assert len(alice.library) == library_before - 1
    assert any("instead of drawing (Tomorrow, Azami's Familiar)" in line for line in game.log)


def _w1g10_toshiro_game(set_pool, *, graveyard=("Lightning Bolt",)):
    bok, lea = set_pool("BOK"), set_pool("LEA")
    return _w1g10_game(
        mine=[bok["Toshiro Umezawa"]], hand=[lea["Terror"]],
        graveyard=[lea[name] for name in graveyard],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]], island=lea["Island"],
    )


def _w1g10_graveyard_slot(owed, name, game, seat=0):
    """The offered target slot naming the card *name* in *seat*'s graveyard."""
    pile = game.players[seat].graveyard
    return next(
        target["graveyard_index"] for target in owed.data["targets"]
        if target.get("kind") == "graveyard" and target.get("seat") == seat
        and pile[target["graveyard_index"]].name == name
    )


def test_w1g10_toshiro_casts_an_instant_from_the_graveyard_as_it_resolves(set_pool):
    """Toshiro Umezawa: "Whenever a creature an opponent controls dies, you may
    cast target instant card from your graveyard. If that spell would be put
    into a graveyard, exile it instead." Asked of a person. The Terror that
    killed the Bears is already in the graveyard when the trigger chooses its
    target (the 2011-01-01 ruling), beside the Lightning Bolt; Alice targets
    the Bolt. The cast is made during the trigger's resolution (CR 608.2g):
    the ability is still on the stack while the offer is owed, the Bolt goes
    above it, kills the Hill Giant and is exiled instead of going to the
    graveyard. The Giant's death triggers Toshiro again; Alice declines, and
    the Terror stays where it is."""
    game = _w1g10_toshiro_game(set_pool)
    alice, bob = game.players
    bears, giant = game.controlled_by(1)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "trigger_target"
    offered = sorted(alice.graveyard[t["graveyard_index"]].name for t in owed.data["targets"])
    assert offered == ["Lightning Bolt", "Terror"]
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_index=_w1g10_graveyard_slot(owed, "Lightning Bolt", game),
    )
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "copy_cast" and owed.data["card_name"] == "Lightning Bolt"
    assert [item.card.name for item in game.stack] == ["Toshiro Umezawa"]
    assert game.confirm_copy_cast(0, True, target_permanent_ids=[giant.permanent_id])
    assert [item.card.name for item in game.stack][-1] == "Lightning Bolt"
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "trigger_target"
    assert [card.name for card in alice.exile] == ["Lightning Bolt"]
    assert [card.name for card in bob.graveyard] == ["Grizzly Bears", "Hill Giant"]
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_index=_w1g10_graveyard_slot(owed, "Terror", game),
    )
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "copy_cast"
    assert game.confirm_copy_cast(0, False)
    _w1g10_settle(game)
    assert [card.name for card in alice.graveyard] == ["Terror"]
    assert game.stack == []


def test_w1g10_toshiros_cast_pays_the_mana_cost_and_is_not_kept_for_later(set_pool):
    """"You must still pay the mana cost" (2005-02-01): a headless seat with no
    untapped land cannot pay for the Bolt and casts nothing — and the offer is
    not a lasting permission (CR 608.2g): once the trigger has resolved, the
    Bolt cannot be cast from the graveyard later. With a Mountain untapped,
    the Bolt is cast, the Mountain paying for it."""
    lea = set_pool("LEA")
    game = _w1g10_toshiro_game(set_pool)
    alice = game.players[0]
    bears, giant = game.controlled_by(1)
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    game.enforce_mana_costs = True
    _w1g10_settle(game)
    assert "Lightning Bolt" in [card.name for card in alice.graveyard]
    assert game.is_on_battlefield(giant)
    assert not game.cast_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_permanent_ids=[giant.permanent_id],
    ).supported
    game._put_permanent_onto_battlefield(0, _W1G10Permanent(card=lea["Mountain"]), None)
    game._sync_control()
    game.enforce_mana_costs = False
    alice.hand.append(lea["Terror"])
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id]).supported
    game.enforce_mana_costs = True
    _w1g10_settle(game)
    assert [card.name for card in alice.exile] == ["Lightning Bolt"]
    land = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert land.tapped


def _w1g10_shirei_game(set_pool, *, theirs=("Grizzly Bears",)):
    bok, lea = set_pool("BOK"), set_pool("LEA")
    return _w1g10_game(
        mine=[bok["Shirei, Shizo's Caretaker"], lea["Llanowar Elves"], lea["Hill Giant"]],
        hand=[lea["Lightning Bolt"], lea["Lightning Bolt"], lea["Lightning Bolt"]],
        theirs=[lea[name] for name in theirs], island=lea["Island"],
    )


def _w1g10_bolt(game, permanent):
    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id]).supported
    _w1g10_settle(game)


def test_w1g10_shirei_returns_a_small_creature_at_the_next_end_step(set_pool):
    """Shirei, Shizo's Caretaker: "Whenever a creature with power 1 or less is
    put into your graveyard from the battlefield, you may return that card to
    the battlefield at the beginning of the next end step if Shirei is still
    on the battlefield." Asked of a person: the Llanowar Elves (1/1) dies and
    nothing returns until the end step begins; there Alice is asked and says
    yes. The Hill Giant (3/3) and Bob's Bears (his graveyard, not hers)
    trigger nothing."""
    game = _w1g10_shirei_game(set_pool)
    alice, bob = game.players
    _shirei, elves, giant = game.controlled_by(0)
    (bears,) = game.controlled_by(1)
    game.interactive_seats = {0}
    _w1g10_bolt(game, elves)
    _w1g10_bolt(game, giant)
    _w1g10_bolt(game, bears)
    assert sorted(card.name for card in alice.graveyard) == [
        "Hill Giant", "Lightning Bolt", "Lightning Bolt", "Lightning Bolt", "Llanowar Elves",
    ]
    assert [card.name for card in bob.graveyard] == ["Grizzly Bears"]
    game.resolve_end_step(0)
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    _w1g10_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Llanowar Elves", "Shirei, Shizo's Caretaker",
    ]
    assert "Hill Giant" in [card.name for card in alice.graveyard]
    assert "Grizzly Bears" in [card.name for card in bob.graveyard]


def test_w1g10_shirei_gone_before_the_end_step_returns_nothing(set_pool):
    """The condition is the delayed ability's, asked as it resolves: Shirei
    killed after the Elves died (but before the end step) means the Elves stay
    in the graveyard. Shirei itself is a 2/2, so its own death returns
    nothing either."""
    game = _w1g10_shirei_game(set_pool)
    alice = game.players[0]
    shirei, elves, _giant = game.controlled_by(0)
    _w1g10_bolt(game, elves)
    _w1g10_bolt(game, shirei)
    game.resolve_end_step(0)
    _w1g10_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Hill Giant"]
    assert "Llanowar Elves" in [card.name for card in alice.graveyard]

# ==== end w1g10 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.
#
# Kodama of the Center Tree's soulshift X, counted as the ability triggers
# and looking back at the board its death left (CR 702.46a, 603.10a,
# 603.3d), and Takeno, Samurai General counting Fumiko the Lowblood's
# bushido X (CR 702.45a, 613.4c).
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.bushido import bushido_points as _w2g1_bushido_points
from engine.keywords import remove_all_abilities as _w2g1_remove_all_abilities
from engine.models import Permanent as _W2G1Permanent
from tests.helpers import declare_attack as _w2g1_declare_attack
from tests.helpers import drive_combat as _w2g1_drive_combat
from tests.helpers import settle as _w2g1_settle

_W2G1_KODAMA = "Kodama of the Center Tree"


def _w2g1_put(game, seat, card):
    permanent = _W2G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w2g1_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
                interactive=()):
    """Alice (seat 0) with *mine* on the battlefield, *graveyard* in her
    graveyard and *hand* in hand; Bob with *theirs*. Costs are not charged."""
    lea = set_pool("LEA")
    game = _W2G1Game(players=[
        _W2G1PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                         library=[lea["Island"]] * 10),
        _W2G1PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = [_w2g1_put(game, 0, card) for card in mine]
    placed += [_w2g1_put(game, 1, card) for card in theirs]
    game.start_turn(0)
    _w2g1_settle(game)
    return game, placed


def _w2g1_spirits(set_pool, *names):
    chk, lea, bok = set_pool("CHK"), set_pool("LEA"), set_pool("BOK")
    return [
        chk[name] if name in chk else bok[name] if name in bok else lea[name]
        for name in names
    ]


def _w2g1_names(cards):
    return sorted(card.name for card in cards)


def _w2g1_accept(game, _choice):
    return game.confirm_optional_pay(0, accept=True)


def _w2g1_offered(prompt):
    assert prompt is not None and prompt.kind == "trigger_target", prompt
    return sorted(target["name"] for target in prompt.data["targets"])


def _w2g1_name(game, prompt, name):
    target = next(t for t in prompt.data["targets"] if t["name"] == name)
    assert game.confirm_trigger_target(
        0, seat=target["seat"], graveyard_index=target["graveyard_index"],
    )


def test_w2g1_kodama_alone_soulshifts_one(set_pool):
    """Kodama alone: X is 1 ("Soulshift X includes Kodama of the Center
    Tree. So, X is always at least 1", 2005-02-01). A person is offered the
    mana value 1 Spirit and not the 2; the default seat returns it too."""
    lea = set_pool("LEA")
    kodama_card, = _w2g1_spirits(set_pool, _W2G1_KODAMA)
    for interactive in ((0,), ()):
        game, (kodama,) = _w2g1_table(
            set_pool, hand=[lea["Terror"]], mine=[kodama_card],
            graveyard=_w2g1_spirits(set_pool, "Lantern Kami", "Kami of Ancient Law"),
            interactive=interactive,
        )
        assert (kodama.effective_power, kodama.effective_toughness) == (1, 1)
        assert game.queue_from_hand(
            0, "Terror", target_permanent_ids=[kodama.permanent_id],
        ).supported
        if interactive:
            prompt = _w2g1_settle(game, defaults=False)
            assert _w2g1_offered(prompt) == ["Lantern Kami"], game.log
            assert [item.x_value for item in game.stack] == [1]
            _w2g1_name(game, prompt, "Lantern Kami")
        _w2g1_settle(game, answers={"optional_pay": _w2g1_accept})
        assert _w2g1_names(game.players[0].hand) == ["Lantern Kami"], game.log
        assert "Kami of Ancient Law" in _w2g1_names(game.players[0].graveyard)


def test_w2g1_kodama_with_four_other_spirits_can_return_itself(set_pool):
    """Kodama and four other Spirits; Kodama dies alone. X is 5, and its
    mana value is 5: "Kodama of the Center Tree can return itself to its
    owner's hand if you control five or more Spirits" (2005-02-01)."""
    lea = set_pool("LEA")
    game, (kodama, *_others) = _w2g1_table(
        set_pool, hand=[lea["Terror"]],
        mine=_w2g1_spirits(
            set_pool, _W2G1_KODAMA, "Lantern Kami", "Will-o'-the-Wisp",
            "Wandering Ones", "Hana Kami",
        ),
        interactive=(0,),
    )
    assert (kodama.effective_power, kodama.effective_toughness) == (5, 5)
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[kodama.permanent_id],
    ).supported
    prompt = _w2g1_settle(game, defaults=False)
    assert _w2g1_offered(prompt) == [_W2G1_KODAMA], game.log
    _w2g1_name(game, prompt, _W2G1_KODAMA)
    _w2g1_settle(game, answers={"optional_pay": _w2g1_accept})
    assert _w2g1_names(game.players[0].hand) == [_W2G1_KODAMA], game.log


def test_w2g1_kodama_counts_every_spirit_a_wrath_took_beside_it(set_pool):
    """Wrath of God takes Kodama and two Spirits at once: each was there
    immediately before the event (CR 603.10a), so X is 3 — Gnarled Mass
    (mana value 3) is offered, Kodama (5) is not — though nothing is left
    on the battlefield to count when the ability is put on the stack."""
    lea = set_pool("LEA")
    game, _placed = _w2g1_table(
        set_pool, hand=[lea["Wrath of God"]],
        mine=_w2g1_spirits(set_pool, _W2G1_KODAMA, "Lantern Kami", "Wandering Ones"),
        graveyard=_w2g1_spirits(set_pool, "Gnarled Mass"),
        interactive=(0,),
    )
    assert game.queue_from_hand(0, "Wrath of God").supported
    prompt = _w2g1_settle(game, defaults=False)
    assert _w2g1_offered(prompt) == [
        "Gnarled Mass", "Lantern Kami", "Wandering Ones",
    ], game.log
    assert [item.x_value for item in game.stack] == [3]
    _w2g1_name(game, prompt, "Gnarled Mass")
    _w2g1_settle(game, answers={"optional_pay": _w2g1_accept})
    assert _w2g1_names(game.players[0].hand) == ["Gnarled Mass"], game.log
    assert not list(game.controlled_by(0))


def test_w2g1_kodama_beside_another_soulshift_creature_each_its_own_x(set_pool):
    """Kodama and Thief of Hope (soulshift 2) die to one Wrath beside a
    third Spirit: two triggers, Kodama's X 3 and the Thief's printed 2, and
    the seat nobody asks names a different card for each (W1G6's pair fix
    still holds), so both come back."""
    lea = set_pool("LEA")
    game, _placed = _w2g1_table(
        set_pool, hand=[lea["Wrath of God"]],
        mine=_w2g1_spirits(set_pool, _W2G1_KODAMA, "Thief of Hope", "Lantern Kami"),
        graveyard=_w2g1_spirits(set_pool, "Gnarled Mass", "Kami of Ancient Law"),
    )
    assert game.queue_from_hand(0, "Wrath of God").supported
    _w2g1_settle(game)
    assert sum("triggered (died)" in line for line in game.log) == 2, game.log
    assert _w2g1_names(game.players[0].hand) == [
        "Gnarled Mass", "Kami of Ancient Law",
    ], game.log


def test_w2g1_kodama_x_stays_what_it_was_as_it_triggered(set_pool):
    """The X is taken as the ability triggers and rides the stack object
    (CR 603.3d chose the target with it): two Spirits Bolted in response
    leave no Spirit to count at resolution, and Gnarled Mass (mana value 3)
    still comes back — recounted, it would be refused (CR 608.2b)."""
    lea = set_pool("LEA")
    game, (kodama, lantern, ones) = _w2g1_table(
        set_pool, hand=[lea["Terror"], lea["Lightning Bolt"], lea["Lightning Bolt"]],
        mine=_w2g1_spirits(set_pool, _W2G1_KODAMA, "Lantern Kami", "Wandering Ones"),
        graveyard=_w2g1_spirits(set_pool, "Gnarled Mass"),
        interactive=(0,),
    )
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[kodama.permanent_id],
    ).supported
    prompt = _w2g1_settle(game, defaults=False)
    assert _w2g1_offered(prompt) == ["Gnarled Mass"], game.log
    _w2g1_name(game, prompt, "Gnarled Mass")
    for spirit in (lantern, ones):
        assert game.queue_from_hand(
            0, "Lightning Bolt", target_permanent_ids=[spirit.permanent_id],
        ).supported
    assert [item.x_value for item in game.stack][:1] == [3]
    _w2g1_settle(game, answers={"optional_pay": _w2g1_accept})
    assert not list(game.controlled_by(0))
    assert _w2g1_names(game.players[0].hand) == ["Gnarled Mass"], game.log


def test_w2g1_kodama_sacrificed_as_a_cost_counts_itself(set_pool):
    """Sacrificed to pay Sacrifice's additional cost, Kodama is off the
    battlefield before its trigger is put on the stack — held until the cast
    is announced (CR 117.2a) — and still counts itself: X is 2 beside one
    Spirit, so the mana value 2 Spirit is offered and the 3 is not."""
    lea = set_pool("LEA")
    game, (kodama, _lantern) = _w2g1_table(
        set_pool, hand=[lea["Sacrifice"]],
        mine=_w2g1_spirits(set_pool, _W2G1_KODAMA, "Lantern Kami"),
        graveyard=_w2g1_spirits(set_pool, "Gnarled Mass", "Kami of Ancient Law"),
        interactive=(0,),
    )
    assert game.queue_from_hand(
        0, "Sacrifice", cost_permanent_ids=[kodama.permanent_id],
    ).supported
    prompt = _w2g1_settle(game, defaults=False)
    assert _w2g1_offered(prompt) == ["Kami of Ancient Law"], game.log
    _w2g1_name(game, prompt, "Kami of Ancient Law")
    _w2g1_settle(game, answers={"optional_pay": _w2g1_accept})
    assert _w2g1_names(game.players[0].hand) == ["Kami of Ancient Law"], game.log


def test_w2g1_kodama_put_into_the_graveyard_by_the_legend_rule(set_pool):
    """A second Kodama: the legend rule puts one into the graveyard
    (CR 704.5j). Immediately before, its controller had both Kodamas and a
    Lantern Kami: X is 3, and Gnarled Mass comes back."""
    kodama_card, lantern = _w2g1_spirits(set_pool, _W2G1_KODAMA, "Lantern Kami")
    game, _placed = _w2g1_table(
        set_pool, mine=[kodama_card, lantern],
        graveyard=_w2g1_spirits(set_pool, "Gnarled Mass", "Kami of Ancient Law"),
    )
    _w2g1_put(game, 0, kodama_card)
    _w2g1_settle(game)
    assert any("704.5j" in line for line in game.log), game.log
    assert _w2g1_names(game.players[0].hand) == ["Gnarled Mass"], game.log


def _w2g1_takeno_table(set_pool, attackers):
    lea = set_pool("LEA")
    game, (_takeno, fumiko, *_bobs) = _w2g1_table(
        set_pool,
        mine=[set_pool("CHK")["Takeno, Samurai General"],
              set_pool("BOK")["Fumiko the Lowblood"]],
        theirs=[lea[name] for name in attackers],
    )
    return game, fumiko


def test_w2g1_takeno_counts_fumikos_bushido_x(set_pool):
    """Takeno: "Each other Samurai creature you control gets +1/+1 for each
    point of bushido it has." Fumiko has bushido X, X the number of
    attacking creatures (CR 702.45a), counted as Takeno's layer-7c effect is
    applied (CR 613.4c): a 3/2 with none attacking, 5/4 with two, 6/5 with
    three."""
    game, fumiko = _w2g1_takeno_table(set_pool, ["Grizzly Bears", "Hill Giant"])
    assert (fumiko.effective_power, fumiko.effective_toughness) == (3, 2)
    game.start_turn(1)
    _w2g1_settle(game)
    _w2g1_declare_attack(game, 1)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (5, 4), game.log
    assert _w2g1_bushido_points(fumiko.effective_card, game=game, permanent=fumiko) == 2

    game, fumiko = _w2g1_takeno_table(
        set_pool, ["Grizzly Bears", "Hill Giant", "Gray Ogre"],
    )
    game.start_turn(1)
    _w2g1_settle(game)
    _w2g1_declare_attack(game, 1)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (6, 5), game.log
    _w2g1_drive_combat(game)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (3, 2), game.log


def test_w2g1_takeno_beside_a_blocking_fumiko(set_pool):
    """Fumiko blocks Hill Giant with two attackers: her bushido trigger gives
    +2/+2 until end of turn and Takeno +2/+2 more while both attack; the
    Giant dies, one attacker is left, and Takeno's share follows it to +1/+1.
    After combat the trigger's +2/+2 is all that is left."""
    game, fumiko = _w2g1_takeno_table(set_pool, ["Grizzly Bears", "Hill Giant"])
    game.start_turn(1)
    _w2g1_settle(game)
    _w2g1_declare_attack(game, 1, blocks={1: 1})
    _w2g1_settle(game)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (7, 6), game.log
    _w2g1_drive_combat(game, through="combat_damage")
    assert "Hill Giant" in _w2g1_names(game.players[1].graveyard), game.log
    assert (fumiko.effective_power, fumiko.effective_toughness) == (6, 5), game.log
    _w2g1_drive_combat(game)
    assert (fumiko.effective_power, fumiko.effective_toughness) == (5, 4), game.log


def test_w2g1_fumiko_without_her_abilities_has_no_bushido_to_count(set_pool):
    """A Fumiko that lost all abilities has no bushido X (CR 613.1f), so
    Takeno counts no points for her however many creatures attack."""
    game, fumiko = _w2g1_takeno_table(set_pool, ["Grizzly Bears", "Hill Giant"])
    game.start_turn(1)
    _w2g1_settle(game)
    _w2g1_declare_attack(game, 1)
    assert _w2g1_bushido_points(fumiko.effective_card, game=game, permanent=fumiko) == 2
    _w2g1_remove_all_abilities(fumiko, duration="end_of_turn")
    assert _w2g1_bushido_points(fumiko.effective_card, game=game, permanent=fumiko) == 0
    # Without a game there is no board to count the X off.
    assert _w2g1_bushido_points(set_pool("BOK")["Fumiko the Lowblood"]) == 0

# ==== end W2G1 ======================================================
