"""Champions of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# "Whenever you cast a Spirit or Arcane spell, <effect>" — the cast trigger
# narrowed by a union of a creature type (Spirit, CR 205.3m) and a spell type
# (Arcane, CR 205.3k) — and every effect the set hangs on it; Kitsune
# Riftwalker's "Protection from Spirits and from Arcane". Thief of Hope's
# trigger is driven on an invented one-line card: its soulshift line is W1G3's.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import CardDefinition as _W1G4Card
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                interactive=False):
    """A two-seat game on Alice's first main phase, Alice's permanents
    *mine*, Bob's *theirs*, mana costs off."""
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    placed = (
        [_w1g4_put(game, 0, card) for card in mine],
        [_w1g4_put(game, 1, card) for card in theirs],
    )
    game.start_turn(0)
    _w1g4_settle(game)
    return game, placed[0], placed[1]


def _w1g4_cast(game, seat, name, **announced):
    assert game.queue_from_hand(seat, name, **announced).supported, game.log[-5:]


def _w1g4_target(permanent):
    """An answer to a ``trigger_target`` prompt naming *permanent*."""
    return lambda game, choice: game.confirm_trigger_target(
        choice.player_index, permanent_id=permanent.permanent_id,
    )


def _w1g4_may(accept):
    return lambda game, choice: game.confirm_optional_pay(choice.player_index, accept=accept)


def _w1g4_arcane(set_pool):
    """Reach Through Mists — {U} Instant — Arcane, "Draw a card."."""
    return set_pool("CHK")["Reach Through Mists"]


@_w1g4_pytest.mark.parametrize("spell, seat, grows", [
    (("CHK", "Reach Through Mists"), 0, True),     # an Arcane instant
    (("CHK", "Kami of the Hunt"), 0, True),        # a Spirit creature spell
    (("LGN", "Mistform Ultimus"), 0, True),        # every creature type (CR 604.3)
    (("LEA", "Grizzly Bears"), 0, False),          # a Bear spell is neither
    (("LEA", "Giant Growth"), 0, False),           # an instant that is not Arcane
    (("CHK", "Reach Through Mists"), 1, False),    # an opponent's Arcane: not "you cast"
])
def test_w1g4_kami_of_the_hunt_grows_on_your_spirit_or_arcane_spells(
    set_pool, spell, seat, grows,
):
    """"Whenever you cast a Spirit or Arcane spell, this creature gets +1/+1
    until end of turn." One union over two subtype lists: a spell answers
    when it has either subtype, and Mistform Ultimus's CDA works on the
    stack."""
    code, name = spell
    game, (kami,), _ = _w1g4_table(set_pool, mine=[set_pool("CHK")["Kami of the Hunt"]])
    game.players[seat].hand.append(set_pool(code)[name])
    announced = {}
    if name == "Giant Growth":
        announced["target_permanent_ids"] = [kami.permanent_id]
    _w1g4_cast(game, seat, name, **announced)
    _w1g4_settle(game)
    bonus = 3 if name == "Giant Growth" else 0
    expected = (3 + bonus, 3 + bonus) if grows else (2 + bonus, 2 + bonus)
    assert (kami.effective_power, kami.effective_toughness) == expected, game.log


def test_w1g4_the_trigger_resolves_before_the_spell_that_fired_it(set_pool):
    """CR 603.3: the trigger goes on the stack above the Arcane spell, so the
    pump has happened while Reach Through Mists is still a spell."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kami of the Hunt"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    assert [item.card.name for item in game.stack] == [
        "Reach Through Mists", "Kami of the Hunt",
    ]
    game.resolve_top_of_stack()
    assert kami.effective_power == 3
    assert [item.card.name for item in game.stack] == ["Reach Through Mists"]


def test_w1g4_earthshaker_hits_every_creature_without_flying(set_pool):
    """"…deals 2 damage to each creature without flying": the Bears on both
    sides die, Earthshaker (4/5, no flying) is dealt 2 itself, and the Serra
    Angel is spared."""
    lea = set_pool("LEA")
    game, (shaker, angel, _bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Earthshaker"], lea["Serra Angel"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Earthshaker", "Serra Angel"]
    assert not list(game.controlled_by(1)), game.log
    assert shaker.damage_marked == 2 and angel.damage_marked == 0


def test_w1g4_guardian_of_solitude_gives_its_target_flying_for_the_turn(set_pool):
    """"…target creature gains flying until end of turn", the target chosen by
    an interactive seat as the trigger goes on the stack."""
    lea = set_pool("LEA")
    game, (_guardian, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Guardian of Solitude"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert game._has_keyword(bears, "flying"), game.log
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not game._has_keyword(bears, "flying")


def test_w1g4_horizon_seed_regenerates_its_target(set_pool):
    """"…regenerate target creature": the shield replaces the Bears'
    destruction by a Lightning Bolt's lethal damage (CR 701.19) and taps it."""
    lea = set_pool("LEA")
    game, (_seed, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool), lea["Lightning Bolt"]], interactive=True,
        mine=[set_pool("CHK")["Horizon Seed"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.regeneration_shield == 1, game.log
    _w1g4_cast(game, 0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    _w1g4_settle(game)
    assert game.is_on_battlefield(bears) and bears.tapped, game.log


def test_w1g4_innocence_kami_untaps_itself(set_pool):
    """"…untap this creature" — the {W}, {T} tapper used again the same turn."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], mine=[set_pool("CHK")["Innocence Kami"]],
    )
    kami.tapped = True
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert not kami.tapped, game.log


def test_w1g4_kami_of_fires_roar_stops_its_target_blocking(set_pool):
    """"…target creature can't block this turn": Bob's Bears can no longer
    block the Kami."""
    lea = set_pool("LEA")
    game, (kami,), (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of Fire's Roar"]], theirs=[lea["Grizzly Bears"]],
    )
    assert game._can_block_attacker(bears, kami)
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(bears, kami), game.log


def test_w1g4_kami_of_the_painted_road_takes_protection_from_the_chosen_colour(set_pool):
    """"…gains protection from the color of your choice until end of turn":
    an interactive seat names red, and Lightning Bolt can no longer target it."""
    from engine.legality import cast_spec_of

    lea = set_pool("LEA")
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Painted Road"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "color_choice": lambda g, c: g.confirm_color_choice(c.player_index, "R"),
    })
    assert ("color", "R") in game._protection_qualities(kami), game.log
    bolt = lea["Lightning Bolt"]
    offered = game._enumerate_targets(1, bolt, cast_spec_of(bolt), for_cast=True)
    assert kami.permanent_id not in {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in offered if o.get("kind") == "permanent"
    }


def test_w1g4_kami_of_the_waning_moon_gives_its_target_fear(set_pool):
    """"…target creature gains fear until end of turn": a green Bears can't
    block it, a black creature still can (CR 702.36b)."""
    lea = set_pool("LEA")
    game, (_moon, bears), (their_bears, knight) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Waning Moon"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"], lea["Black Knight"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(their_bears, bears), game.log
    assert game._can_block_attacker(knight, bears)


def test_w1g4_orbweaver_kumo_gains_forestwalk(set_pool):
    """"…this creature gains forestwalk until end of turn": unblockable while
    Bob controls a Forest."""
    lea = set_pool("LEA")
    game, (kumo,), (bears, _forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Orbweaver Kumo"]],
        theirs=[lea["Grizzly Bears"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert game._has_keyword(kumo, "forestwalk"), game.log
    assert not game._can_block_attacker(bears, kumo)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_ore_gorger_may_destroy_a_nonbasic_land(set_pool, accept):
    """"…you may destroy target nonbasic land": the Tundra is the only target
    offered (the basic Forest is not), and declining the "may" spares it."""
    lea = set_pool("LEA")
    game, _, (tundra, forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Ore Gorger"]], theirs=[lea["Tundra"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    prompt = _w1g4_settle(game, defaults=False)
    assert prompt.kind == "trigger_target"
    assert [t["permanent_id"] for t in prompt.data["targets"]] == [tundra.permanent_id]
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(tundra), "optional_pay": _w1g4_may(accept),
    })
    assert game.is_on_battlefield(tundra) is (not accept), game.log
    assert game.is_on_battlefield(forest)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_sire_of_the_storm_may_draw(set_pool, accept):
    """"…you may draw a card" — besides the card Reach Through Mists draws."""
    game, _, _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Sire of the Storm"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(accept)})
    assert len(game.players[0].hand) == (2 if accept else 1), game.log


def test_w1g4_soilshaper_animates_a_land_that_stays_a_land(set_pool):
    """"…target land becomes a 3/3 creature until end of turn. It's still a
    land." — and it is a land again, and only a land, after cleanup."""
    lea = set_pool("LEA")
    game, (_shaper, forest), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soilshaper"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(forest)})
    assert forest.is_creature and forest.has_type("land"), game.log
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not forest.is_creature and forest.has_type("land")


def test_w1g4_soul_of_magma_deals_one_damage_to_its_target(set_pool):
    """"…this creature deals 1 damage to target creature" — the interactive
    seat's choice among every creature, the Kami's own included."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soul of Magma"]], theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.damage_marked == 1, game.log


@_w1g4_pytest.mark.parametrize("start_tapped", [False, True])
def test_w1g4_teller_of_tales_taps_or_untaps_its_target(set_pool, start_tapped):
    """"…you may tap or untap target creature": an untapped Bears is tapped
    and a tapped one untapped (the other answer would change nothing)."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Teller of Tales"]], theirs=[lea["Grizzly Bears"]],
    )
    bears.tapped = start_tapped
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(bears), "optional_pay": _w1g4_may(True),
    })
    assert bears.tapped is (not start_tapped), game.log


def test_w1g4_thief_of_hopes_trigger_drains_its_target_opponent(set_pool):
    """Thief of Hope's first line on an invented card (its soulshift line is
    W1G3's): "…target opponent loses 1 life and you gain 1 life"."""
    thief = _W1G4Card(
        name="Invented Thief", mana_cost="{2}{B}", cmc=3.0,
        type_line="Creature — Spirit",
        oracle_text=(
            "Whenever you cast a Spirit or Arcane spell, target opponent "
            "loses 1 life and you gain 1 life."
        ),
        colors=("B",), color_identity=("B",), keywords=(), produced_mana=(),
        raw={"name": "Invented Thief", "type_line": "Creature — Spirit",
             "power": "2", "toughness": "2"},
    )
    game, _, _ = _w1g4_table(set_pool, hand=[_w1g4_arcane(set_pool)], mine=[thief])
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.life for p in game.players] == [21, 19], game.log


def test_w1g4_hikari_leaves_before_the_spell_and_comes_back_at_the_end_step(set_pool):
    """"…you may exile Hikari. If you do, return it … at the beginning of the
    next end step." The 2004-12-01 ruling: "it leaves the battlefield before
    the spell that triggered it resolves its ability, so it will be unaffected
    by that spell" — a Kodama's Might aimed at it has no target left, and the
    Hikari that returns is a new object (CR 400.7), a plain 4/4."""
    chk = set_pool("CHK")
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[chk["Kodama's Might"]],
        mine=[chk["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Kodama's Might", target_permanent_ids=[hikari.permanent_id])
    _w1g4_settle(game)
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].exile] == ["Hikari, Twilight Guardian"]
    game.resolve_end_step(0)
    _w1g4_settle(game)
    (back,) = list(game.controlled_by(0))
    assert back.card.name == "Hikari, Twilight Guardian" and back is not hikari
    assert (back.effective_power, back.effective_toughness) == (4, 4), game.log
    assert not game.players[0].exile


def test_w1g4_hikari_may_stay(set_pool):
    """The 2004-12-01 ruling: "You may choose not to exile Hikari."."""
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(False)})
    assert game.is_on_battlefield(hikari) and not game.players[0].exile, game.log


def test_w1g4_kodama_of_the_south_tree_pumps_each_other_creature_you_control(set_pool):
    """"…each other creature you control gets +1/+1 and gains trample until
    end of turn" — not the Kodama, not Bob's creatures."""
    lea = set_pool("LEA")
    game, (kodama, bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kodama of the South Tree"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3), game.log
    assert game._has_keyword(bears, "trample")
    assert (kodama.effective_power, kodama.effective_toughness) == (4, 4)
    assert not game._has_keyword(kodama, "trample")
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(their_bears, "trample")


def test_w1g4_kitsune_riftwalker_has_protection_from_spirits_and_arcane(set_pool):
    """"Protection from Spirits and from Arcane" (CR 702.16): Rend Flesh, an
    Arcane instant, can't target it (it can target the Bears beside it), and a
    Spirit can't block it (CR 702.16f) while the Bears can."""
    from engine.legality import cast_spec_of

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game, (fox, bears), (kami, their_bears) = _w1g4_table(
        set_pool, mine=[chk["Kitsune Riftwalker"], lea["Grizzly Bears"]],
        theirs=[chk["Kami of the Hunt"], lea["Grizzly Bears"]],
    )
    rend = chk["Rend Flesh"]
    offered = {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in game._enumerate_targets(1, rend, cast_spec_of(rend), for_cast=True)
        if o.get("kind") == "permanent"
    }
    assert fox.permanent_id not in offered
    assert bears.permanent_id in offered
    assert not game._can_block_attacker(kami, fox)
    assert game._can_block_attacker(their_bears, fox)

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
