"""Scourge creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Morph's third half: morph costs that are not mana (CR 702.37e pays "that
# cost", whatever it is), "whenever a permanent is turned face up", Exiled
# Doomsayer's tax on morph costs, Mischievous Quanar's copy. Every test drives
# the special action through ``take_permanent_special_action`` — the seam the
# web and the AI share — and reads the board, the zones, life and the log.

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.card_loader import load_catalog as _w1g5_load_catalog
from engine.face_down import (face_down_card as _w1g5_face_down_card,
                              face_up_morph_cost as _w1g5_face_up_morph_cost,
                              is_face_down as _w1g5_is_face_down,
                              turn_face_up as _w1g5_turn_face_up)
from engine.models import Permanent as _W1G5Permanent
from engine.named_counters import counters_on as _w1g5_counters_on
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.special_actions import (
    available_permanent_special_actions as _w1g5_offers,
    permanent_special_action_refusal as _w1g5_refusal,
    take_permanent_special_action as _w1g5_take,
)
from engine.text_changes import change_creature_word as _w1g5_change_creature_word
from tests.helpers import resolve_stack as _w1g5_resolve_stack

_W1G5_CATALOG = {card.name: card for card in _w1g5_load_catalog()}


def _w1g5_permanent(card, *, face_down=False):
    permanent = _W1G5Permanent(
        card=_w1g5_face_down_card(card) if face_down else card,
    )
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5_game(mine=(), theirs=(), hand=(), *, interactive=(), active=0):
    """A two-seat main phase with seat *active* holding priority, mana costs
    enforced (the special action pays through the board, CR 702.37e)."""
    p1 = _W1G5PlayerState(name="A", hand=list(hand), battlefield=list(mine),
                          library=[_W1G5_CATALOG["Island"]] * 10)
    p2 = _W1G5PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G5_CATALOG["Island"]] * 10)
    game = _W1G5Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(active)
    return game, p1, p2


def _w1g5_lands(name, count):
    return [_w1g5_permanent(_W1G5_CATALOG[name]) for _ in range(count)]


def _w1g5_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


# ---- non-mana morph costs (CR 702.37e) -----------------------------------


def test_w1g5_the_four_non_mana_morph_costs_are_read_as_printed(set_pool):
    """Each card's morph line compiles, and the cost a face-down copy would
    be turned up for is the printed one — the special action's offer names it
    and nothing else. Mana-only morphs are unchanged."""
    scg = set_pool("SCG")
    printed = {
        "Zombie Cutthroat": "Pay 5 life",
        "Skirk Volcanist": "Sacrifice two Mountains",
        "Raven Guild Initiate": "Return a Bird you control to its owner's hand",
        "Putrid Raptor": "Discard a Zombie card",
        "Scornful Egotist": "{U}",
    }
    for name, cost in printed.items():
        assert _w1g5_compile(scg[name]).supported, name
        assert _w1g5_face_up_morph_cost(
            _w1g5_permanent(scg[name], face_down=True)
        ) == cost


def test_w1g5_zombie_cutthroat_pays_five_life_and_not_with_four(set_pool):
    cutthroat = _w1g5_permanent(set_pool("SCG")["Zombie Cutthroat"], face_down=True)
    game, p1, _p2 = _w1g5_game([cutthroat])
    (offer,) = _w1g5_offers(game, 0)
    assert offer["morph_cost"] == "Pay 5 life" and offer["pay_life"] == 5

    assert _w1g5_take(game, 0, cutthroat, "turn_face_up") is None
    assert p1.life == 15 and cutthroat.card.name == "Zombie Cutthroat"
    assert "A paid 5 life to turn a face-down creature face up" in game.log

    # CR 119.4 / 601.2h: four life cannot pay five — refused, nothing paid,
    # and not offered.
    hidden = _w1g5_permanent(set_pool("SCG")["Zombie Cutthroat"], face_down=True)
    game, p1, _p2 = _w1g5_game([hidden])
    p1.life = 4
    assert "cannot pay 5 life with 4 remaining" in _w1g5_take(
        game, 0, hidden, "turn_face_up"
    )
    assert p1.life == 4 and _w1g5_is_face_down(hidden)
    assert _w1g5_offers(game, 0) == []


def test_w1g5_raven_guild_initiate_returns_the_bird_its_controller_names(set_pool):
    scg = set_pool("SCG")
    initiate = _w1g5_permanent(scg["Raven Guild Initiate"], face_down=True)
    farseer = _w1g5_permanent(scg["Aven Farseer"])        # a Bird
    liberator = _w1g5_permanent(scg["Aven Liberator"])    # a Bird
    bears = _w1g5_permanent(_W1G5_CATALOG["Grizzly Bears"])
    game, p1, _p2 = _w1g5_game([initiate, farseer, liberator, bears])
    (offer,) = _w1g5_offers(game, 0)
    choices = {c["permanent_id"] for c in offer["cost_permanents"]["choices"]}
    # The face-down Initiate has no creature types (CR 708.2): it is no Bird.
    assert choices == {farseer.permanent_id, liberator.permanent_id}
    assert offer["cost_permanents"]["verb"] == "return"

    # A named non-Bird is refused with nothing spent; the named Bird returns.
    refused = _w1g5_take(game, 0, initiate, "turn_face_up",
                         cost_permanent_ids=[bears.permanent_id])
    assert refused is not None and _w1g5_is_face_down(initiate)
    assert _w1g5_take(game, 0, initiate, "turn_face_up",
                      cost_permanent_ids=[liberator.permanent_id]) is None
    assert [card.name for card in p1.hand] == ["Aven Liberator"]
    assert "Aven Farseer" in _w1g5_names(game, 0)
    assert initiate.card.name == "Raven Guild Initiate"


def test_w1g5_raven_guild_initiate_cannot_turn_up_with_no_bird(set_pool):
    initiate = _w1g5_permanent(set_pool("SCG")["Raven Guild Initiate"], face_down=True)
    game, _p1, _p2 = _w1g5_game([initiate, *_w1g5_lands("Island", 3)])
    assert "no Bird to return" in _w1g5_refusal(game, 0, initiate, "turn_face_up")
    assert _w1g5_offers(game, 0) == []


def test_w1g5_putrid_raptor_discards_the_zombie_card_named(set_pool):
    scg = set_pool("SCG")
    raptor = _w1g5_permanent(scg["Putrid Raptor"], face_down=True)
    island, zombie = _W1G5_CATALOG["Island"], scg["Zombie Cutthroat"]
    game, p1, _p2 = _w1g5_game([raptor], hand=[island, zombie])
    (offer,) = _w1g5_offers(game, 0)
    assert offer["cost_hand_choices"] == [{"hand_index": 1, "name": "Zombie Cutthroat"}]

    # The Island is no Zombie card: refused, nothing discarded.
    assert _w1g5_take(game, 0, raptor, "turn_face_up", cost_hand_index=0) is not None
    assert len(p1.hand) == 2 and _w1g5_is_face_down(raptor)
    assert _w1g5_take(game, 0, raptor, "turn_face_up", cost_hand_index=1) is None
    assert [card.name for card in p1.hand] == ["Island"]
    assert [card.name for card in p1.graveyard] == ["Zombie Cutthroat"]
    assert raptor.card.name == "Putrid Raptor"


def test_w1g5_putrid_raptor_a_text_change_on_the_face_down_card_changes_its_price(set_pool):
    """The 2004-10-04 ruling: "You can use a text-changing effect that changes
    creature types on this card while is it face down to change Zombie to
    something else. This will change the type of card you have to discard to
    turn it face up." (CR 708.8: the effect still applies face up, and CR
    702.37e asks what the morph cost would be face up.)"""
    scg = set_pool("SCG")
    raptor = _w1g5_permanent(scg["Putrid Raptor"], face_down=True)
    zombie, goblin = scg["Zombie Cutthroat"], scg["Skirk Volcanist"]
    game, p1, _p2 = _w1g5_game([raptor], hand=[zombie, goblin])
    assert _w1g5_change_creature_word(raptor, "zombie", "goblin")
    assert _w1g5_face_up_morph_cost(raptor) == "Discard a Goblin card"
    (offer,) = _w1g5_offers(game, 0)
    assert [c["name"] for c in offer["cost_hand_choices"]] == ["Skirk Volcanist"]
    assert _w1g5_take(game, 0, raptor, "turn_face_up") is None
    assert [card.name for card in p1.graveyard] == ["Skirk Volcanist"]


def test_w1g5_skirk_volcanist_sacrifices_the_two_mountains_named(set_pool):
    volcanist = _w1g5_permanent(set_pool("SCG")["Skirk Volcanist"], face_down=True)
    m1, m2, m3 = _w1g5_lands("Mountain", 3)
    game, p1, _p2 = _w1g5_game([volcanist, m1, m2, m3])
    (offer,) = _w1g5_offers(game, 0)
    assert offer["cost_permanents"]["count"] == 2
    # Partial payment is no payment (CR 601.2h).
    assert _w1g5_take(game, 0, volcanist, "turn_face_up",
                      cost_permanent_ids=[m1.permanent_id]) is not None
    assert _w1g5_take(game, 0, volcanist, "turn_face_up",
                      cost_permanent_ids=[m1.permanent_id, m3.permanent_id]) is None
    assert [permanent for permanent in game.controlled_by(0)
            if permanent.card.name == "Mountain"] == [m2]
    assert [card.name for card in p1.graveyard] == ["Mountain", "Mountain"]


def test_w1g5_skirk_volcanist_with_one_mountain_stays_face_down(set_pool):
    volcanist = _w1g5_permanent(set_pool("SCG")["Skirk Volcanist"], face_down=True)
    game, _p1, _p2 = _w1g5_game([volcanist, *_w1g5_lands("Mountain", 1)])
    assert "to sacrifice" in _w1g5_refusal(game, 0, volcanist, "turn_face_up")
    assert _w1g5_offers(game, 0) == []


@_w1g5_pytest.mark.parametrize("interactive", [False, True])
def test_w1g5_skirk_volcanists_face_up_trigger_divides_three_damage(set_pool, interactive):
    """"When this creature is turned face up, it deals 3 damage divided as you
    choose among one, two, or three target creatures" — a division announced
    by a trigger (CR 601.2d through 603.3d). A person divides it; a default
    seat takes the engine's split."""
    volcanist = _w1g5_permanent(set_pool("SCG")["Skirk Volcanist"], face_down=True)
    giant, bears = (_w1g5_permanent(_W1G5_CATALOG["Hill Giant"]),
                    _w1g5_permanent(_W1G5_CATALOG["Grizzly Bears"]))
    game, _p1, p2 = _w1g5_game(
        [volcanist, *_w1g5_lands("Mountain", 2)], [giant, bears],
        interactive=(0,) if interactive else (),
    )
    assert _w1g5_take(game, 0, volcanist, "turn_face_up") is None
    if interactive:
        prompt = game.pending_choice_of("trigger_target", 0)
        assert prompt is not None and prompt.data.get("division_total") == 3
        assert game.confirm_trigger_target(
            0, permanent_ids=[giant.permanent_id], amounts=[3],
        )
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    damaged = sum(1 for line in game.log if line.startswith("Skirk Volcanist dealt"))
    assert damaged >= 1
    if interactive:
        assert giant not in list(game.controlled_by(1))
        assert any(p is bears for p in game.controlled_by(1))


# ---- Exiled Doomsayer: "All morph costs cost {2} more." ------------------


def test_w1g5_exiled_doomsayer_taxes_a_mana_morph_cost_two(set_pool):
    scg = set_pool("SCG")
    egotist = _w1g5_permanent(scg["Scornful Egotist"], face_down=True)
    doomsayer = _w1g5_permanent(scg["Exiled Doomsayer"])
    # Morph {U} plus {2}: two Islands are not enough, three are.
    game, _p1, _p2 = _w1g5_game([egotist, *_w1g5_lands("Island", 2)], [doomsayer])
    assert "can't pay" in _w1g5_refusal(game, 0, egotist, "turn_face_up")
    game, _p1, _p2 = _w1g5_game([egotist, *_w1g5_lands("Island", 3)], [doomsayer])
    assert _w1g5_take(game, 0, egotist, "turn_face_up") is None
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name == "Island")


def test_w1g5_exiled_doomsayer_makes_a_life_cost_a_mixed_one_and_two_stack(set_pool):
    """Zombie Cutthroat under a Doomsayer pays 5 life *and* {2}; under two of
    them, {4} (CR 601.2f: each increase applies)."""
    scg = set_pool("SCG")
    cutthroat = _w1g5_permanent(scg["Zombie Cutthroat"], face_down=True)
    game, p1, _p2 = _w1g5_game(
        [cutthroat, *_w1g5_lands("Swamp", 1)], [_w1g5_permanent(scg["Exiled Doomsayer"])],
    )
    assert _w1g5_refusal(game, 0, cutthroat, "turn_face_up") is not None
    assert p1.life == 20

    cutthroat = _w1g5_permanent(scg["Zombie Cutthroat"], face_down=True)
    game, p1, _p2 = _w1g5_game(
        [cutthroat, *_w1g5_lands("Swamp", 4)],
        [_w1g5_permanent(scg["Exiled Doomsayer"]),
         _w1g5_permanent(scg["Exiled Doomsayer"])],
    )
    assert _w1g5_take(game, 0, cutthroat, "turn_face_up") is None
    assert p1.life == 15
    assert sum(p.tapped for p in game.controlled_by(0)) == 4


def test_w1g5_exiled_doomsayer_does_not_tax_the_face_down_cast(set_pool):
    """"(This doesn't affect the cost to cast creature spells face down.)"
    The {3} alternative cost (CR 702.37a) is a cast's; the Doomsayer taxes the
    special action's price alone — its own and its opponents'."""
    scg = set_pool("SCG")
    game, p1, _p2 = _w1g5_game(
        [_w1g5_permanent(scg["Exiled Doomsayer"])], hand=[scg["Zombie Cutthroat"]],
    )
    p1.mana_pool.update({"C": 3})
    result = game.queue_from_hand(0, "Zombie Cutthroat", alternative_cost=True)
    assert result.supported, result.details
    assert sum(p1.mana_pool.values()) == 0
    _w1g5_resolve_stack(game)
    (face_down,) = [p for p in game.controlled_by(0) if _w1g5_is_face_down(p)]
    # Its own controller's morph costs are taxed too: "all" morph costs.
    assert _w1g5_refusal(game, 0, face_down, "turn_face_up") is not None


# ---- "Whenever a permanent is turned face up" ----------------------------


def _w1g5_watchers(set_pool):
    scg = set_pool("SCG")
    return (_w1g5_permanent(scg["Aphetto Runecaster"]),
            _w1g5_permanent(scg["Aven Farseer"]),
            _w1g5_permanent(scg["Bonethorn Valesk"]))


def test_w1g5_every_watcher_on_both_sides_sees_a_morph_turned_up(set_pool):
    """Aphetto Runecaster, Aven Farseer and Bonethorn Valesk on B's side watch
    A turn a face-down Woodcloaker up: any permanent, any player's (their
    2007-05-01 ruling). Their triggers and Woodcloaker's own go on the stack
    together, APNAP (CR 603.3b): B's above A's."""
    runecaster, farseer, valesk = _w1g5_watchers(set_pool)
    woodcloaker = _w1g5_permanent(set_pool("SCG")["Woodcloaker"], face_down=True)
    game, p1, p2 = _w1g5_game(
        [woodcloaker, *_w1g5_lands("Forest", 4)], [runecaster, farseer, valesk],
    )
    assert _w1g5_take(game, 0, woodcloaker, "turn_face_up") is None
    assert [item.card.name for item in game.stack] == [
        "Woodcloaker", "Aphetto Runecaster", "Aven Farseer", "Bonethorn Valesk",
    ]
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g5_counters_on(farseer, "+1/+1") == 1
    assert p1.life + p2.life == 39, "Valesk dealt 1 damage to some player"
    assert [card.name for card in p2.hand] == ["Island"], "Runecaster's may draw"


def test_w1g5_runecasters_draw_is_its_controllers_to_decline(set_pool):
    runecaster, _farseer, _valesk = _w1g5_watchers(set_pool)
    woodcloaker = _w1g5_permanent(set_pool("SCG")["Woodcloaker"], face_down=True)
    game, _p1, p2 = _w1g5_game(
        [woodcloaker, *_w1g5_lands("Forest", 4)], [runecaster], interactive=(1,),
    )
    assert _w1g5_take(game, 0, woodcloaker, "turn_face_up") is None
    _w1g5_resolve_stack(game)
    prompt = game.pending_choice_of("optional_pay", 1)
    assert prompt is not None and prompt.data["card_name"] == "Aphetto Runecaster"
    assert game.resolve_pending_choice("optional_pay", 1, accept=False)
    assert p2.hand == []


def test_w1g5_the_watchers_see_every_road_up_and_no_road_off(set_pool):
    """An effect turning a permanent face up is the same event (CR 708.7);
    a face-down permanent revealed as it leaves the battlefield is not turned
    face up (CR 708.9)."""
    runecaster, farseer, valesk = _w1g5_watchers(set_pool)
    scg = set_pool("SCG")
    first = _w1g5_permanent(scg["Scornful Egotist"], face_down=True)
    second = _w1g5_permanent(scg["Titanic Bulvox"], face_down=True)
    game, _p1, _p2 = _w1g5_game([first, second], [runecaster, farseer, valesk])
    assert _w1g5_turn_face_up(game, first, how="an effect")
    assert len(game.stack) == 3
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g5_counters_on(farseer, "+1/+1") == 1
    # Leaving face down reveals it (CR 708.9) — it is not turned face up.
    game.sacrifice_permanent(second)
    assert any("revealed" in line for line in game.log)
    assert game.stack == [] and _w1g5_counters_on(farseer, "+1/+1") == 1


# ---- Mischievous Quanar ---------------------------------------------------


def _w1g5_bolt_and_growth(set_pool, *, interactive=()):
    """B casts Lightning Bolt and then Giant Growth at A's Grizzly Bears; A
    holds a face-down Mischievous Quanar and three Islands."""
    quanar = _w1g5_permanent(set_pool("SCG")["Mischievous Quanar"], face_down=True)
    bears = _w1g5_permanent(_W1G5_CATALOG["Grizzly Bears"])
    giant = _w1g5_permanent(_W1G5_CATALOG["Hill Giant"])
    game, p1, p2 = _w1g5_game(
        [quanar, bears, *_w1g5_lands("Island", 3)], [giant],
        interactive=interactive, active=1,
    )
    p2.hand = [_W1G5_CATALOG["Lightning Bolt"], _W1G5_CATALOG["Giant Growth"]]
    p2.mana_pool.update({"R": 1, "G": 1})
    for name in ("Lightning Bolt", "Giant Growth"):
        cast = game.queue_from_hand(1, name, target_player_index=0,
                                    target_permanent_ids=[bears.permanent_id])
        assert cast.supported, cast.details
    game.priority_player_index = 0
    return game, quanar, bears, giant


def test_w1g5_quanar_turned_up_in_response_copies_the_spell_it_targets(set_pool):
    """A person turns Quanar up in response (a special action, CR 116.2b),
    targets the Bolt beneath the Giant Growth (CR 603.3d — the trigger's own
    target, not the top of the stack), and aims the copy at B's Hill Giant
    (CR 707.10c). The copy is the Bolt's colour: Quanar prints no exception."""
    game, quanar, bears, giant = _w1g5_bolt_and_growth(set_pool, interactive=(0,))
    bolt = game.stack[0]
    assert _w1g5_take(game, 0, quanar, "turn_face_up") is None
    assert game.pending_choice_of("trigger_target", 0) is not None
    assert game.confirm_trigger_target(0, stack_item=bolt)
    assert game.stack[-1].target_stack_item is bolt
    game.resolve_top_of_stack()
    assert game.pending_choice_of("copy_spell_target", 0) is not None
    assert game.confirm_copy_spell_target(0, permanent_id=giant.permanent_id)
    copy = next(item for item in game.stack if item.is_copy)
    assert game._stack_item_colors(copy) == ("R",)
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    assert not any(p is giant for p in game.controlled_by(1))
    assert "Mischievous Quanar: targets Lightning Bolt" in game.log


def test_w1g5_quanar_on_a_default_seat_copies_and_removed_with_no_spell(set_pool):
    game, quanar, _bears, _giant = _w1g5_bolt_and_growth(set_pool)
    assert _w1g5_take(game, 0, quanar, "turn_face_up") is None
    _w1g5_resolve_stack(game)
    assert any("Mischievous Quanar copied" in line for line in game.log)

    # Nothing to copy: CR 603.3d removes the trigger as it is put on the stack.
    lonely = _w1g5_permanent(set_pool("SCG")["Mischievous Quanar"], face_down=True)
    game, _p1, _p2 = _w1g5_game([lonely, *_w1g5_lands("Island", 3)])
    assert _w1g5_take(game, 0, lonely, "turn_face_up") is None
    assert game.stack == []
    assert not any("copied" in line for line in game.log)


def test_w1g5_quanar_turns_itself_face_down_and_up_again(set_pool):
    """"{3}{U}{U}: Turn this creature face down." Then the special action
    turns it up again for {1}{U}{U}, and its trigger fires again."""
    quanar = _w1g5_permanent(set_pool("SCG")["Mischievous Quanar"])
    game, p1, _p2 = _w1g5_game([quanar, *_w1g5_lands("Island", 3)])
    p1.mana_pool.update({"U": 2, "C": 3})
    result = game.activate_permanent_ability(0, "Mischievous Quanar", ability_index=0)
    assert result.supported, result.details
    _w1g5_resolve_stack(game)
    assert _w1g5_is_face_down(quanar)
    game.start_priority_window(0)
    assert _w1g5_take(game, 0, quanar, "turn_face_up") is None
    assert quanar.card.name == "Mischievous Quanar"
    # Its trigger fired again, and with no spell to copy it was removed as it
    # was put on the stack (CR 603.3d).
    assert "Mischievous Quanar triggered (turned face up)" in game.log
    assert game.stack == []


def test_w1g5_fork_still_makes_its_copy_red(set_pool):
    """Fork's line left its card hook for the production Quanar earned: the
    copy of a blue spell is red (CR 707.9b, "except that the copy is red")."""
    game, p1, p2 = _w1g5_game(hand=[_W1G5_CATALOG["Fork"]], active=1)
    p2.hand = [_W1G5_CATALOG["Ancestral Recall"]]
    p2.mana_pool.update({"U": 1})
    assert game.queue_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    game.priority_player_index = 0
    p1.mana_pool.update({"R": 2})
    cast = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert cast.supported, cast.details
    game.resolve_top_of_stack()
    copy = next(item for item in game.stack if item.is_copy)
    assert game._stack_item_colors(copy) == ("R",)

# ---- the drive list: Scourge morphs supported on arrival -----------------

_W1G5_DRIVE = {
    # name: (land, how many, what turning it up leaves in the log)
    "Aven Liberator": ("Plains", 4, "gains protection from"),
    "Frontline Strategist": ("Plains", 1, "is prevented"),
    "Riptide Survivor": ("Island", 3, "drew 3 card"),
    "Root Elemental": ("Forest", 7, "onto the battlefield (Root Elemental)"),
    "Woodcloaker": ("Forest", 4, "gains trample until end of turn"),
    "Titanic Bulvox": ("Forest", 7, "it is Titanic Bulvox"),
    "Scornful Egotist": ("Island", 1, "it is Scornful Egotist"),
    "Raven Guild Master": ("Island", 4, "it is Raven Guild Master"),
    "Soul Collector": ("Swamp", 3, "it is Soul Collector"),
}


@_w1g5_pytest.mark.parametrize("interactive", [False, True])
@_w1g5_pytest.mark.parametrize("name", sorted(_W1G5_DRIVE))
def test_w1g5_every_drive_list_morph_turns_up_through_the_special_action(
    set_pool, name, interactive,
):
    land, count, evidence = _W1G5_DRIVE[name]
    face_down = _w1g5_permanent(set_pool("SCG")[name], face_down=True)
    game, p1, _p2 = _w1g5_game(
        [face_down, _w1g5_permanent(_W1G5_CATALOG["Grizzly Bears"]),
         *_w1g5_lands(land, count)],
        [_w1g5_permanent(_W1G5_CATALOG["Hill Giant"])],
        hand=[_W1G5_CATALOG["Island"], _W1G5_CATALOG["Grizzly Bears"],
              _W1G5_CATALOG["Mountain"]],
        interactive=(0,) if interactive else (),
    )
    assert _w1g5_take(game, 0, face_down, "turn_face_up") is None
    assert face_down.card.name == name
    for _ in range(6):
        game.auto_resolve_pending_choices()
        if not game.stack:
            break
        _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert any(evidence in line for line in game.log), game.log[-6:]


def test_w1g5_soul_collector_takes_what_it_killed_in_combat_and_after(set_pool):
    """"Whenever a creature dealt damage by this creature this turn dies,
    return that card to the battlefield under your control." A combat kill,
    and a creature it damaged in combat that a Shock finishes afterwards."""
    from tests.helpers import declare_attack as _declare_attack

    scg = set_pool("SCG")
    collector = _w1g5_permanent(scg["Soul Collector"])
    giant = _w1g5_permanent(_W1G5_CATALOG["Hill Giant"])
    game, _p1, _p2 = _w1g5_game([collector], [giant])
    _declare_attack(game, 1, blocks={0: 0})
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert "Hill Giant" in _w1g5_names(game, 0)

    collector = _w1g5_permanent(scg["Soul Collector"])
    spider = _w1g5_permanent(_W1G5_CATALOG["Giant Spider"])
    game, p1, _p2 = _w1g5_game([collector], [spider], hand=[_W1G5_CATALOG["Shock"]])
    _declare_attack(game, 1, blocks={0: 0})
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert spider.damage_marked == 3 and "Giant Spider" in _w1g5_names(game, 1)
    game.start_priority_window(1)
    game.priority_player_index = 0
    p1.mana_pool["R"] = 1
    assert game.queue_from_hand(0, "Shock", target_player_index=1,
                                target_permanent_ids=[spider.permanent_id]).supported
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    _w1g5_resolve_stack(game)
    assert "Giant Spider" in _w1g5_names(game, 0)


def test_w1g5_a_face_down_soul_collector_takes_nothing(set_pool):
    """The 2004-10-04 ruling: "The ability only triggers if this card is face
    up at the time the creature is put into the graveyard."
    """
    from tests.helpers import declare_attack as _declare_attack

    collector = _w1g5_permanent(set_pool("SCG")["Soul Collector"], face_down=True)
    elves = _w1g5_permanent(_W1G5_CATALOG["Llanowar Elves"])
    game, _p1, p2 = _w1g5_game([collector], [elves])
    _declare_attack(game, 1, blocks={0: 0})
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert [card.name for card in p2.graveyard] == ["Llanowar Elves"]
    assert _w1g5_names(game, 0) == ["Face-down creature"]


def test_w1g5_frontline_strategist_prevents_non_soldier_combat_damage(set_pool):
    """Turned up before combat: its Soldier self deals 1, the Bears' 2 is
    prevented ("prevent all combat damage non-Soldier creatures would deal
    this turn")."""
    from tests.helpers import declare_attack as _declare_attack

    strategist = _w1g5_permanent(set_pool("SCG")["Frontline Strategist"], face_down=True)
    bears = _w1g5_permanent(_W1G5_CATALOG["Grizzly Bears"])
    game, _p1, p2 = _w1g5_game([strategist, bears, *_w1g5_lands("Plains", 1)])
    assert _w1g5_take(game, 0, strategist, "turn_face_up") is None
    _w1g5_resolve_stack(game)
    _declare_attack(game, 0)
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert p2.life == 19

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
