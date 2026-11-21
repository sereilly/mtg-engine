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

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

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

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
