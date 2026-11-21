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

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
