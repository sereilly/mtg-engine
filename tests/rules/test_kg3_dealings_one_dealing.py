"""One spell or ability dealing damage to several recipients at once is one
event, read from the end each trigger names (CR 603.2c, CR 608.2f).

``engine/simultaneous_damage.py`` states the reading and its sources. kg3
`events` made the combat damage step and the sweeps one dealing; these are the
boards the rest of the engine dealt chunk by chunk, each with a trigger naming
one end of the event watching:

* a printed sentence the lowering split ("…2 damage to any target and 3 damage
  to you"): Spirit Link on Orcish Artillery gained 2 and then 3;
* a divided Fireball, "each of two target creatures", "each player", "each
  opponent": Justice ("If a single source does damage to multiple targets at
  once, Justice will add up all the damage done and deal damage to the
  source's controller at one time", 2004-10-04) dealt its damage once per
  recipient;
* a CR 616.1e question in the middle of a divided Fireball: the dealing stays
  open across the answer, and Justice adds up what was dealt either side of it;
* the delayed ones (CR 603.7): Vigorous Charge and Spiritualize per chunk of a
  creature's combat damage, Glyph of Life per attacker dealing damage to its
  Wall at once — and its "that much" is only what the attacking creatures
  dealt (CR 120.9);
* lifelink: one life-gain event per source per dealing (CR 702.15e; Ajani's
  Pridemate's ruling, 2024-11-08), where the combat dealing gained once per
  *controller*.

Validated backwards on 7d311d9f: every board here fails there (two triggers,
or four, where one is the rule; one life-gain event for two lifelinkers).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.shields import add_shield, make_counting_pool, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _creature(name: str, power: int, toughness: int, *, keywords=(),
              subtype: str = "Test", colors=()) -> CardDefinition:
    type_line = f"Creature — {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="\n".join(keywords), colors=tuple(colors),
        color_identity=tuple(colors), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _table(seats: int = 2, *, interactive=()) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _lines(game: Game, text: str) -> list[str]:
    return [line for line in game.log if text in line]


def _combat(game: Game, attackers, blocks, *, bands=None) -> None:
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(a) for a in attackers],
        defending_player_index=1, bands=bands,
    )
    assert ok, why
    resolve_stack(game)
    game._set_phase_and_step("combat", "declare_blockers")
    ok, why = game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)]
        for blocker, attacker in blocks
    })
    assert ok, why
    resolve_stack(game)
    game._set_phase_and_step("combat", "combat_damage")
    ok, why = game.resolve_all_combat_damage(0)
    assert ok, why


# ---------------------------------------------------------------------------
# A split sentence
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.2c", "608.2f")
@pytest.mark.parametrize("interactive", [(), (0,)], ids=["default", "interactive"])
def test_spirit_link_on_orcish_artillery_gains_the_sentence_once(interactive):
    """The entry's board: "{T}: This creature deals 2 damage to any target and
    3 damage to you." is one event, so "whenever enchanted creature deals
    damage, you gain that much life" triggers once, for 5. On the base it
    gained 2 and then 3."""
    game = _table(interactive=interactive)
    artillery = _put(game, 0, _POOL["Orcish Artillery"])
    attach_aura(_put(game, 0, _POOL["Spirit Link"]), artillery)
    game._sync_control()

    result = game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1)
    assert result.supported, result.details
    resolve_stack(game)

    assert _lines(game, "from Spirit Link") == ["P0 gained 5 life from Spirit Link (17 -> 22)"]
    assert (game.players[0].life, game.players[1].life) == (22, 18)
    assert game.simultaneous_damage is None


# ---------------------------------------------------------------------------
# The loops in handlers/damage.py
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.2c", "608.2f", "601.2d")
def test_justice_adds_up_a_divided_fireball_once():
    """Fireball for 4, divided evenly between a creature and its controller:
    2 and 2, one event — one Justice trigger for 4."""
    game = _table()
    _put(game, 1, _POOL["Justice"])
    bear = _put(game, 1, _creature("Test Bear", 2, 2))
    game.players[0].hand.append(_POOL["Fireball"])
    game._sync_control()

    result = game.cast_from_hand(
        0, "Fireball", x_value=4,
        divided_targets=[(1, None), (1, game.battlefield_index_of(bear))],
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert _lines(game, "Justice dealt") == ["Justice dealt 4 damage to P0"]
    assert game.players[0].life == 16


def _jagged_lightning(game: Game) -> int:
    first = _put(game, 1, _creature("Test Ogre A", 4, 4))
    second = _put(game, 1, _creature("Test Ogre B", 4, 4))
    game.players[0].hand.append(_POOL["Jagged Lightning"])
    game._sync_control()
    result = game.cast_from_hand(
        0, "Jagged Lightning",
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    )
    assert result.supported, result.details
    return 6


def _flame_rift(game: Game) -> int:
    game.players[0].hand.append(_POOL["Flame Rift"])
    result = game.cast_from_hand(0, "Flame Rift")
    assert result.supported, result.details
    return 8


def _sizzle(game: Game) -> int:
    game.players[0].hand.append(_POOL["Sizzle"])
    result = game.cast_from_hand(0, "Sizzle", target_player_index=1)
    assert result.supported, result.details
    return 6


@pytest.mark.cr("603.2c", "608.2f")
@pytest.mark.parametrize("cast,seats", [
    (_jagged_lightning, 2),   # "each of two target creatures"
    (_flame_rift, 2),         # "each player"
    (_sizzle, 3),             # "each opponent", two of them
], ids=["each_of_two_targets", "each_player", "each_opponent"])
def test_justice_adds_up_one_spell_dealing_to_each(cast, seats):
    """One red spell dealing damage to every member of a set at once: one
    Justice trigger, for the total. Fiery Confluence's ruling (2015-11-04)
    calls one "deals 2 damage to each opponent" mode "a separate
    damage-dealing event" — one event, however many opponents."""
    game = _table(seats)
    _put(game, seats - 1, _POOL["Justice"])
    game._sync_control()
    total = cast(game)
    resolve_stack(game)
    assert _lines(game, "Justice dealt") == [f"Justice dealt {total} damage to P0"]


@pytest.mark.cr("616.1e", "603.2c", "608.2f")
def test_a_question_mid_fireball_keeps_the_dealing_open_across_the_answer():
    """Fireball for 6, divided between P1 — holding two one-point prevention
    shields, two effects for one event (CR 616.1e) — and P2. P1 is asked
    first, and until P1 answers nothing has been dealt and Justice has not
    triggered: the dealing waits with the loop. Answered, both shields apply
    in turn (CR 616.1f) and P1 is dealt 1; P2's 3 follows, and Justice adds
    up the 4 dealt as one damage event — on the base it triggered for 1, then
    for 3."""
    game = _table(3, interactive=(1,))
    shielded = game.players[1]
    add_shield(shielded, make_numeric_pool(1, source_name="Test Pool A"))
    add_shield(shielded, make_counting_pool(1, "+1/+1", source_name="Test Pool B"))
    _put(game, 2, _POOL["Justice"])
    game.players[0].hand.append(_POOL["Fireball"])
    game._sync_control()

    result = game.cast_from_hand(
        0, "Fireball", x_value=6, divided_targets=[(1, None), (2, None)],
    )
    assert result.supported, result.details
    assert game.pending_choices_of("effect_order", 1), "the shielded seat is asked"
    assert game.simultaneous_damage is not None, "the dealing is open across the question"
    assert game.players[2].life == 20 and not _lines(game, "Justice dealt")

    assert game.resolve_pending_choice("effect_order", 1, option_index=0)
    resolve_stack(game)

    assert (shielded.life, game.players[2].life) == (19, 17)
    assert _lines(game, "Justice dealt") == ["Justice dealt 4 damage to P0"]
    assert game.simultaneous_damage is None
    assert game.resume_stack == [] and not game.effect_suspended


# ---------------------------------------------------------------------------
# Delayed triggers (CR 603.7)
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.7", "603.2c", "120.9")
def test_glyph_of_life_counts_what_the_attacking_creatures_dealt_at_once():
    """"Whenever that creature is dealt damage by an attacking creature this
    turn, you gain that much life." Two banded attackers (2/2 and 3/3) blocked
    by the Wall deal it 5 at once: one trigger, for the 5 the attacking
    creatures dealt (CR 120.9). On the base: 2, then 3."""
    game = _table()
    wall = _put(game, 1, _creature("Test Wall", 0, 8, keywords=("Defender",), subtype="Wall"))
    first = _put(game, 0, _creature("Test Bander A", 2, 2, keywords=("Banding",)))
    second = _put(game, 0, _creature("Test Bander B", 3, 3, keywords=("Banding",)))
    game.players[1].hand.append(_POOL["Glyph of Life"])
    game._sync_control()
    result = game.cast_from_hand(1, "Glyph of Life", target_permanent_ids=[wall.permanent_id])
    assert result.supported, result.details
    resolve_stack(game)

    _combat(game, [first, second], [(wall, first)], bands=[[
        game.battlefield_index_of(first), game.battlefield_index_of(second),
    ]])
    assert wall.damage_marked == 5
    resolve_stack(game)

    assert _lines(game, "from Glyph of Life") == ["P1 gained 5 life from Glyph of Life (20 -> 25)"]


@pytest.mark.cr("603.7", "603.2c", "510.2")
def test_vigorous_charge_gains_a_tramplers_whole_combat_damage_once():
    """Kicked Vigorous Charge on a 6/4: blocked by a 2/2, it assigns 2 to the
    blocker and tramples 4 over — one combat damage event, one "whenever that
    creature deals combat damage this turn" trigger, for 6. On the base: 2,
    then 4."""
    game = _table()
    wurm = _put(game, 0, _creature("Test Wurm", 6, 4))
    bears = _put(game, 1, _creature("Test Bears", 2, 2))
    game.players[0].hand.append(_POOL["Vigorous Charge"])
    game._sync_control()
    result = game.cast_from_hand(
        0, "Vigorous Charge", target_permanent_ids=[wurm.permanent_id],
        optional_cost_payments={"{W}": 1},
    )
    assert result.supported, result.details
    resolve_stack(game)

    _combat(game, [wurm], [(bears, wurm)])
    resolve_stack(game)

    assert game.players[1].life == 16
    assert _lines(game, "from Vigorous Charge") == ["P0 gained 6 life from Vigorous Charge (20 -> 26)"]


@pytest.mark.cr("603.7", "603.2c", "510.2")
def test_spiritualize_sees_a_double_blocked_creatures_damage_once():
    """"Until end of turn, whenever target creature deals damage, you gain that
    much life." A 4/4 blocked by two 2/2s deals 2 to each at once: one
    trigger, for 4. On the base: two triggers of 2."""
    game = _table()
    giant = _put(game, 0, _creature("Test Giant", 4, 4))
    first = _put(game, 1, _creature("Test Bears A", 2, 2))
    second = _put(game, 1, _creature("Test Bears B", 2, 2))
    game.players[0].hand.append(_POOL["Spiritualize"])
    game._sync_control()
    result = game.cast_from_hand(0, "Spiritualize", target_permanent_ids=[giant.permanent_id])
    assert result.supported, result.details
    resolve_stack(game)

    _combat(game, [giant], [(first, giant), (second, giant)])
    resolve_stack(game)

    assert _lines(game, "from Spiritualize") == ["P0 gained 4 life from Spiritualize (20 -> 24)"]


# ---------------------------------------------------------------------------
# Lifelink (CR 702.15e)
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.15e", "119.9", "510.2")
def test_two_lifelinkers_are_two_life_gain_events_and_one_is_one():
    """"If multiple sources with lifelink deal damage at the same time, they
    cause separate life gain events" (CR 702.15e), and one lifelinker hitting
    several recipients at once is one (Ajani's Pridemate's ruling,
    2024-11-08). Vito ("whenever you gain life, target opponent loses that
    much life") counts them: two unblocked lifelinkers, two triggers (the
    base gained once for the seat); one lifelinker double-blocked, one."""
    game = _table()
    _put(game, 0, _POOL["Vito, Thorn of the Dusk Rose"])
    first = _put(game, 0, _creature("Test Linker A", 2, 2, keywords=("Lifelink",)))
    second = _put(game, 0, _creature("Test Linker B", 3, 3, keywords=("Lifelink",)))
    _combat(game, [first, second], [])
    resolve_stack(game)
    assert _lines(game, "from lifelink") == [
        "P0 gained 2 life from lifelink (20 -> 22)",
        "P0 gained 3 life from lifelink (22 -> 25)",
    ]
    assert len(_lines(game, "Vito, Thorn of the Dusk Rose: P1 lost")) == 2

    game = _table()
    _put(game, 0, _POOL["Vito, Thorn of the Dusk Rose"])
    linker = _put(game, 0, _creature("Test Linker", 4, 4, keywords=("Lifelink",)))
    blockers = [_put(game, 1, _creature(f"Test Bears {i}", 2, 2)) for i in range(2)]
    _combat(game, [linker], [(blocker, linker) for blocker in blockers])
    resolve_stack(game)
    assert _lines(game, "from lifelink") == ["P0 gained 4 life from lifelink (20 -> 24)"]
    assert len(_lines(game, "Vito, Thorn of the Dusk Rose: P1 lost")) == 1
