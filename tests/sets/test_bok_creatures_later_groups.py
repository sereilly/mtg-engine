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
