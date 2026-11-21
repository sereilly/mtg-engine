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
import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game
from engine.models import CardDefinition as _w1g3_CardDefinition
from engine.models import Permanent as _w1g3_Permanent
from engine.models import PlayerState as _w1g3_PlayerState
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.soulshift import soulshift_count as _w1g3_soulshift_count

from tests.helpers import _nosick as _w1g3_nosick
from tests.helpers import drive_combat as _w1g3_drive_combat
from tests.helpers import settle as _w1g3_settle

#: Every Champions of Kamigawa creature printing "Soulshift N" — W1G3's eleven
#: and W1G4's Thief of Hope (whose cast trigger is W1G4's; the integrator
#: writes its whole-card test).
_W1G3_SOULSHIFT = (
    "Burr Grafter", "Gibbering Kami", "Hundred-Talon Kami", "Kami of Lunacy",
    "Kami of the Palace Fields", "Rootrunner", "Scuttling Death",
    "Thousand-legged Kami", "Venerable Kumo", "Vine Kami", "He Who Hungers",
)


def _w1g3_card(name: str, cost: int, type_line: str = "Creature — Spirit",
               text: str = "", power: str = "1", toughness: str = "1"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return _w1g3_CardDefinition(
        name=name, mana_cost="{%d}" % cost if cost else "", cmc=float(cost),
        type_line=type_line, oracle_text=text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _w1g3_table(mine=(), theirs=(), *, hand=(), graveyard=(), interactive=()):
    land = _w1g3_card("Filler Land", 0, "Land")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P1", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in mine],
            hand=list(hand), graveyard=list(graveyard), library=[land] * 10,
        ),
        _w1g3_PlayerState(
            name="P2", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in theirs],
            library=[land] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game


def _w1g3_names(cards) -> list[str]:
    return [card.name for card in cards]


def _w1g3_on_field(game, seat: int, name: str):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g3_every_soulshift_creature_prints_one_readable_soulshift_line(set_pool):
    pool = set_pool("CHK")
    printed = sorted(
        name for name, card in pool.items()
        if any(_w1g3_soulshift_count(line) for line in (card.oracle_text or "").split("\n"))
    )
    assert set(_W1G3_SOULSHIFT) <= set(printed)
    assert "Thief of Hope" in printed


@_w1g3_pytest.mark.parametrize("name", _W1G3_SOULSHIFT)
def test_w1g3_soulshift_returns_a_spirit_at_its_n_and_not_one_above(set_pool, name):
    """CR 702.46a, on every printed soulshift creature: destroyed by Rend
    Spirit, it returns the Spirit card of mana value N from its graveyard and
    leaves the one of mana value N + 1 (and a non-Spirit of mana value N)."""
    pool = set_pool("CHK")
    card = pool[name]
    assert _w1g3_compile(card).supported, name
    (n,) = [_w1g3_soulshift_count(line) for line in card.oracle_text.split("\n")
            if _w1g3_soulshift_count(line)]
    at_n = _w1g3_card(f"Spirit at {n}", n)
    above = _w1g3_card(f"Spirit at {n + 1}", n + 1)
    bear = _w1g3_card(f"Bear at {n}", n, "Creature — Bear")
    game = _w1g3_table(
        mine=[card], hand=[pool["Rend Spirit"]], graveyard=[above, bear, at_n],
    )
    victim = _w1g3_on_field(game, 0, name)
    assert game.cast_from_hand(0, "Rend Spirit", target_permanent_ids=[victim.permanent_id]).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == [f"Spirit at {n}"], game.log[-8:]
    graveyard = _w1g3_names(game.players[0].graveyard)
    assert name in graveyard and f"Spirit at {n + 1}" in graveyard and f"Bear at {n}" in graveyard


def test_w1g3_burr_grafter_sacrificed_pumps_and_its_soulshift_resolves_first(set_pool):
    """Sacrifice is a cost, so the soulshift trigger goes on the stack above
    the pump (CR 603.3) and resolves first; an interactive seat is offered only
    the Spirit cards of mana value 3 or less and names the one it wants."""
    pool = set_pool("CHK")
    bears = _w1g3_card("Target Bear", 2, "Creature — Bear", power="2", toughness="2")
    game = _w1g3_table(
        mine=[pool["Burr Grafter"]], theirs=[bears],
        graveyard=[pool["Kami of Ancient Law"], pool["Kami of Lunacy"], pool["Hana Kami"]],
        interactive=(0,),
    )
    bear = _w1g3_on_field(game, 1, "Target Bear")
    assert game.activate_permanent_ability(
        0, "Burr Grafter", target_permanent_ids=[bear.permanent_id]
    ).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Hana Kami", "Kami of Ancient Law"]
    hana = next(t for t in asked.data["targets"] if t["name"] == "Hana Kami")
    assert game.confirm_trigger_target(0, seat=hana["seat"], graveyard_index=hana["graveyard_index"])
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert _w1g3_names(game.players[0].hand) == ["Hana Kami"]
    assert bear.effective_power == 4
    returned = next(i for i, line in enumerate(game.log) if "Returned Hana Kami" in line)
    pumped = next(i for i, line in enumerate(game.log) if "+2/+2" in line)
    assert returned < pumped


def test_w1g3_rootrunner_tops_a_land_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    game = _w1g3_table(
        mine=[pool["Rootrunner"]], theirs=[_w1g3_card("Their Land", 0, "Land")],
        graveyard=[pool["Kami of Ancient Law"]],
    )
    land = _w1g3_on_field(game, 1, "Their Land")
    assert game.activate_permanent_ability(
        0, "Rootrunner", target_permanent_ids=[land.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert game.players[1].library[0].name == "Their Land"
    assert _w1g3_names(game.players[0].hand) == ["Kami of Ancient Law"]


def test_w1g3_scuttling_death_shrinks_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    elf = _w1g3_card("Small Elf", 1, "Creature — Elf", power="1", toughness="1")
    game = _w1g3_table(
        mine=[pool["Scuttling Death"]], theirs=[elf],
        graveyard=[pool["Kami of Twisted Reflection"]],
    )
    target = _w1g3_on_field(game, 1, "Small Elf")
    assert game.activate_permanent_ability(
        0, "Scuttling Death", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert "Small Elf" in _w1g3_names(game.players[1].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Twisted Reflection"]


def test_w1g3_thousand_legged_kami_dies_in_combat_and_returns_a_seven_drop_spirit(set_pool):
    """A combat death, the other road to a graveyard: blocked by a creature
    that kills it, it returns Kami of Lunacy (mana value 6, at most 7)."""
    pool = set_pool("CHK")
    wall = _w1g3_card("Big Wall", 4, "Creature — Wall", power="7", toughness="7")
    game = _w1g3_table(
        mine=[pool["Thousand-legged Kami"]], theirs=[wall],
        graveyard=[pool["Kami of Lunacy"]],
    )
    from tests.helpers import declare_attack

    # The only creature on each side: blocker slot 0 blocks attacker slot 0.
    declare_attack(game, 0, blocks={0: 0})
    _w1g3_drive_combat(game)
    _w1g3_settle(game)
    assert "Thousand-legged Kami" in _w1g3_names(game.players[0].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Lunacy"]


def _w1g3_hungers_table(set_pool, *, interactive=()):
    pool = set_pool("CHK")
    bears = _w1g3_card("Their Bear", 2, "Creature — Bear")
    shock = _w1g3_card("Their Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    giant = _w1g3_card("Their Giant", 4, "Creature — Giant", power="3", toughness="3")
    game = _w1g3_table(
        mine=[pool["He Who Hungers"], pool["Kami of Ancient Law"], bears],
        graveyard=[pool["Kami of Twisted Reflection"]], interactive=interactive,
    )
    game.players[1].hand.extend([shock, giant])
    return game


def test_w1g3_he_who_hungers_sacrifices_a_spirit_and_the_activator_picks_the_discard(set_pool):
    """"{1}, Sacrifice a Spirit: Target opponent reveals their hand. You choose
    a card from it. That player discards that card." The interactive
    activator is asked out of the revealed hand and names the Shock."""
    game = _w1g3_hungers_table(set_pool, interactive=(0,))
    kami = _w1g3_on_field(game, 0, "Kami of Ancient Law")
    assert game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[kami.permanent_id],
    ).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "revealed_hand_pick", game.log[-6:]
    assert asked.player_index == 0 and asked.data["victim_index"] == 1
    shock_slot = _w1g3_names(game.players[1].hand).index("Their Shock")
    assert game.confirm_revealed_hand_pick(0, hand_index=shock_slot)
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].hand) == ["Their Giant"]
    assert _w1g3_names(game.players[1].graveyard) == ["Their Shock"]
    assert "Kami of Ancient Law" in _w1g3_names(game.players[0].graveyard)
    assert "He Who Hungers" in [p.card.name for p in game.controlled_by(0)]


def test_w1g3_he_who_hungers_refuses_a_non_spirit_sacrifice_and_an_instant_speed_activation(set_pool):
    game = _w1g3_hungers_table(set_pool)
    bear = _w1g3_on_field(game, 0, "Their Bear")
    refused = game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[bear.permanent_id],
    )
    assert not refused.supported
    assert "Their Bear" in [p.card.name for p in game.controlled_by(0)]
    kami = _w1g3_on_field(game, 0, "Kami of Ancient Law")
    game.active_player_index = 1
    refused = game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[kami.permanent_id],
    )
    assert not refused.supported and "sorcery" in refused.details
    assert len(game.players[1].hand) == 2


def test_w1g3_he_who_hungers_sacrificing_itself_soulshifts(set_pool):
    """It is a Spirit, so it may pay its own cost — and its soulshift 4 then
    returns Kami of Twisted Reflection while the discard still happens."""
    game = _w1g3_hungers_table(set_pool)
    hungers = _w1g3_on_field(game, 0, "He Who Hungers")
    assert game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[hungers.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Twisted Reflection"]
    assert len(game.players[1].hand) == 1 and len(game.players[1].graveyard) == 1


_W1G3_ZUBERA = (
    "Ashen-Skin Zubera", "Dripping-Tongue Zubera", "Ember-Fist Zubera",
    "Floating-Dream Zubera", "Silent-Chant Zubera",
)


def _w1g3_zubera_table(set_pool, mine, *, hand=(), interactive=()):
    game = _w1g3_table(mine=mine, hand=hand, interactive=interactive)
    island = _w1g3_card("Filler Island", 0, "Land")
    game.players[0].library = [island] * 20
    game.players[1].hand = [_w1g3_card(f"Their Card {i}", 1, "Instant") for i in range(7)]
    return game


def test_w1g3_five_zubera_swept_together_each_count_all_five(set_pool):
    """"…for each Zubera that died this turn": five die to one Wrath of God
    beside a Bear, and every trigger counts the five (itself included) and not
    the Bear — the opponent discards 5 and takes 5, its controller draws 5,
    gains 10 and makes five 1/1 colorless Spirits."""
    pool = set_pool("CHK")
    bear = _w1g3_card("My Bear", 2, "Creature — Bear")
    game = _w1g3_zubera_table(
        set_pool, [pool[name] for name in _W1G3_ZUBERA] + [bear],
        hand=[set_pool("LEA")["Wrath of God"]],
    )
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g3_settle(game)
    assert game.players[0].life == 30
    assert game.players[1].life == 15
    assert len(game.players[1].hand) == 2
    assert len(game.players[0].hand) == 5
    tokens = list(game.controlled_by(0))
    assert [p.card.name for p in tokens] == ["Spirit Token"] * 5
    assert all(
        p.effective_power == 1 and p.effective_toughness == 1
        and not p.card.colors and p.has_type("creature")
        for p in tokens
    )


def test_w1g3_an_earlier_zubera_death_this_turn_is_counted_by_a_later_one(set_pool):
    pool = set_pool("CHK")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_zubera_table(
        set_pool, [pool["Floating-Dream Zubera"], pool["Silent-Chant Zubera"]],
        hand=[shock, shock],
    )
    dream = _w1g3_on_field(game, 0, "Floating-Dream Zubera")
    chant = _w1g3_on_field(game, 0, "Silent-Chant Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[dream.permanent_id]).supported
    _w1g3_settle(game)
    assert len(game.players[0].hand) == 2  # one Shock left, one card drawn
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[chant.permanent_id]).supported
    _w1g3_settle(game)
    assert game.players[0].life == 24  # 2 life for each of the two Zubera


def test_w1g3_the_zubera_count_is_this_turns(set_pool):
    """A Zubera that died last turn is not counted: the tally resets with the
    turn."""
    pool = set_pool("CHK")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_zubera_table(
        set_pool, [pool["Ashen-Skin Zubera"], pool["Silent-Chant Zubera"]],
        hand=[shock, shock],
    )
    first = _w1g3_on_field(game, 0, "Ashen-Skin Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[first.permanent_id]).supported
    _w1g3_settle(game)
    assert len(game.players[1].hand) == 6
    game.start_turn(1)
    game._settle()
    game.start_turn(0)
    game._settle()
    chant = _w1g3_on_field(game, 0, "Silent-Chant Zubera")
    life = game.players[0].life
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[chant.permanent_id]).supported
    _w1g3_settle(game)
    assert game.players[0].life == life + 2


def test_w1g3_ember_fist_zubera_asks_an_interactive_seat_for_any_target(set_pool):
    pool = set_pool("CHK")
    giant = _w1g3_card("Their Giant", 4, "Creature — Giant", power="3", toughness="1")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_table(mine=[pool["Ember-Fist Zubera"]], theirs=[giant], hand=[shock],
                       interactive=(0,))
    fist = _w1g3_on_field(game, 0, "Ember-Fist Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[fist.permanent_id]).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    kinds = {t["kind"] for t in asked.data["targets"]}
    assert kinds == {"player", "permanent"}
    target = _w1g3_on_field(game, 1, "Their Giant")
    assert game.confirm_trigger_target(0, permanent_id=target.permanent_id)
    _w1g3_settle(game)
    assert "Their Giant" in _w1g3_names(game.players[1].graveyard)
    assert game.players[1].life == 20


def _w1g3_iname_table(set_pool, *, interactive=()):
    pool = set_pool("CHK")
    bear = _w1g3_card("Graveyard Bear", 2, "Creature — Bear")
    return _w1g3_table(
        mine=[pool["Iname, Life Aspect"]], hand=[pool["Rend Spirit"]],
        graveyard=[pool["Kami of Ancient Law"], pool["Kami of Lunacy"], bear, pool["Hana Kami"]],
        interactive=interactive,
    )


def _w1g3_kill_iname(game):
    iname = _w1g3_on_field(game, 0, "Iname, Life Aspect")
    assert game.cast_from_hand(0, "Rend Spirit", target_permanent_ids=[iname.permanent_id]).supported


def test_w1g3_iname_life_aspect_exiles_itself_and_returns_the_spirits_it_named(set_pool):
    """"…you may exile it. If you do, return any number of target Spirit cards
    from your graveyard to your hand." The targets are announced as the trigger
    goes on the stack, any number of them (an interactive seat names two of
    the three Spirit cards and not the Bear, which is not offered); the
    exile is the resolution's choice, and then exactly the named cards
    return."""
    game = _w1g3_iname_table(set_pool, interactive=(0,))
    _w1g3_kill_iname(game)
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    offered = {t["name"]: t["graveyard_index"] for t in asked.data["targets"]}
    # The 2004-12-01 ruling: Iname may target itself (to no effect).
    assert set(offered) == {
        "Kami of Ancient Law", "Kami of Lunacy", "Hana Kami", "Iname, Life Aspect",
    }
    assert asked.data.get("max_targets") == 4 and asked.data.get("up_to")
    assert game.confirm_trigger_target(
        0, seat=0,
        graveyard_indices=[offered["Kami of Ancient Law"], offered["Kami of Lunacy"]],
    )
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert sorted(_w1g3_names(game.players[0].hand)) == ["Kami of Ancient Law", "Kami of Lunacy"]
    assert _w1g3_names(game.players[0].exile) == ["Iname, Life Aspect"]
    assert "Hana Kami" in _w1g3_names(game.players[0].graveyard)


def test_w1g3_iname_declining_the_exile_returns_nothing(set_pool):
    game = _w1g3_iname_table(set_pool)
    _w1g3_kill_iname(game)
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=False),
    })
    assert game.players[0].hand == []
    assert "Iname, Life Aspect" in _w1g3_names(game.players[0].graveyard)
    assert game.players[0].exile == []


def test_w1g3_iname_may_be_exiled_with_no_target_named(set_pool):
    """The 2004-12-01 ruling: "You can exile the card even if you choose no
    targets." Naming nobody is an answer "any number" allows."""
    game = _w1g3_iname_table(set_pool, interactive=(0,))
    _w1g3_kill_iname(game)
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target"
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[])
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert game.players[0].hand == []
    assert _w1g3_names(game.players[0].exile) == ["Iname, Life Aspect"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
