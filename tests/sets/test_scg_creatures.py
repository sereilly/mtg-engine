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
#
# Typecycling (CR 702.29e-f): Scourge's seven creatures that search for a land
# type instead of drawing. The keyword's own rules tests are in
# tests/rules/test_scg_w1g2_typecycling.py; these drive each printed card.
import pytest as _w1g2_pytest
from fastapi.testclient import TestClient as _W1G2TestClient

from engine import Game as _W1G2Game
from engine.activation_zones import HAND as _W1G2_HAND
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import usable_activated_abilities as _w1g2_usable

from tests.helpers import resolve_stack as _w1g2_resolve_stack

#: Each typecycler and the land type its search names.
_W1G2_TYPECYCLERS = {
    "Chartooth Cougar": "Mountain",
    "Elvish Aberration": "Forest",
    "Eternal Dragon": "Plains",
    "Noble Templar": "Plains",
    "Shoreline Ranger": "Island",
    "Twisted Abomination": "Swamp",
    "Wirewood Guardian": "Forest",
}


def _w1g2_table(set_pool, hand, library, *, interactive=False, mana=None):
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=list(library))
    bob = _W1G2PlayerState(name="Bob", library=[set_pool("LEA")["Island"]] * 5)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    alice.mana_pool.update(mana or {"C": 2})
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_basics(set_pool):
    lea = set_pool("LEA")
    return [lea["Grizzly Bears"]] + [
        lea[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    ]


@_w1g2_pytest.mark.parametrize("name", sorted(_W1G2_TYPECYCLERS))
def test_w1g2_each_typecycler_finds_a_card_of_its_type(set_pool, name):
    """"[Type]cycling {2}": pay {2}, discard the card, search for a card of the
    type, reveal it, put it into the hand, shuffle (CR 702.29e). The card is
    cycled (CR 702.29f), so the log says so."""
    wanted = _W1G2_TYPECYCLERS[name]
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")[name]], _w1g2_basics(set_pool),
    )

    result = game.activate_from_hand(0, name)
    assert result.supported, result.details
    assert [c.name for c in alice.graveyard] == [name]
    assert not any(alice.mana_pool.values()), "the {2} was paid"
    assert f"Alice cycled {name}" in game.log
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == [wanted]
    assert len(alice.library) == 5 and wanted not in [c.name for c in alice.library]
    assert any(f"revealed {wanted}" in line for line in game.log)


def test_w1g2_a_typecycle_can_be_stifled_and_the_card_stays_cycled(set_pool):
    """2009-02-01: "Mountaincycling is an activated ability. Effects that
    interact with activated abilities (such as Stifle …) will interact with
    Mountaincycling." The search is countered; the discard was the cost, so
    the card stays in the graveyard and nothing is found."""
    scg = set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [scg["Chartooth Cougar"]], _w1g2_basics(set_pool),
    )
    bob.hand.append(scg["Stifle"])
    bob.mana_pool["U"] = 1

    assert game.activate_from_hand(0, "Chartooth Cougar").supported
    (search,) = game.stack
    assert game.queue_from_hand(1, "Stifle", target_stack_index=0).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert not any(item is search for item in game.stack)
    assert alice.hand == [] and len(alice.library) == 6
    assert [c.name for c in alice.graveyard] == ["Chartooth Cougar"]
    assert [c.name for c in bob.graveyard] == ["Stifle"]


def test_w1g2_a_typecycler_cannot_be_activated_without_its_two(set_pool):
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Noble Templar"]], _w1g2_basics(set_pool),
        mana={"W": 1},
    )
    result = game.activate_from_hand(0, "Noble Templar")
    assert not result.supported
    assert [c.name for c in alice.hand] == ["Noble Templar"]
    assert alice.graveyard == [] and game.stack == []


def test_w1g2_shoreline_ranger_offers_a_person_only_island_cards(set_pool):
    """2009-02-01 rulings on the cycle: "You can choose to find any card with
    the … land type, including nonbasic lands." Tundra is a Plains Island; a
    Plains alone is not an answer."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Shoreline Ranger"]],
        [lea["Plains"], lea["Tundra"], lea["Island"]], interactive=True,
    )
    assert game.activate_from_hand(0, "Shoreline Ranger").supported
    game.resolve_top_of_stack()
    search = game.pending_choice_of("search_library", 0)
    assert search is not None
    assert search.data["restrictions"] == {"subtypes": ["island"]}

    names = [c.name for c in alice.library]
    assert not game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Plains"), zone="library",
    )
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Tundra"), zone="library",
    )
    _w1g2_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Tundra"]


def test_w1g2_eternal_dragon_plainscycles_and_comes_back_in_your_upkeep(set_pool):
    """"{3}{W}{W}: Return this card from your graveyard to your hand. Activate
    only during your upkeep." The cycle puts it in the graveyard (CR 702.29e),
    the upkeep brings it back, and outside the upkeep it stays."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Eternal Dragon"]], [lea["Plains"], lea["Swamp"]],
    )
    assert game.activate_from_hand(0, "Eternal Dragon").supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Plains"]
    assert [c.name for c in alice.graveyard] == ["Eternal Dragon"]

    alice.mana_pool.update({"W": 2, "C": 3})
    game.current_step = "draw"
    refused = game.activate_from_graveyard(0, "Eternal Dragon")
    assert not refused.supported, "only during your upkeep"
    assert [c.name for c in alice.graveyard] == ["Eternal Dragon"]

    game.current_step = "upkeep"
    assert game.activate_from_graveyard(0, "Eternal Dragon").supported
    _w1g2_resolve_stack(game)
    assert sorted(c.name for c in alice.hand) == ["Eternal Dragon", "Plains"]
    assert alice.graveyard == []


def test_w1g2_twisted_abomination_regenerates_and_cannot_swampcycle_from_play(set_pool):
    """On the battlefield the swampcycling ability exists but cannot be
    activated (CR 702.29b, 113.6j); "{B}: Regenerate this creature" can."""
    scg = set_pool("SCG")
    program = _w1g2_compile(scg["Twisted Abomination"])
    assert [a.instruction.kind for a in _w1g2_usable(program, zone=_W1G2_HAND)] == [
        "search_library"
    ]
    game, alice, bob = _w1g2_table(set_pool, [], _w1g2_basics(set_pool), mana={"B": 1})
    abomination = _w1g2_put(game, 0, scg["Twisted Abomination"])
    assert [a.instruction.kind for a in game.usable_abilities_of(abomination)] == [
        "grant_regeneration_to_self"
    ]
    assert game.activate_permanent_ability(
        0, "Twisted Abomination",
        permanent_index=game.battlefield_index_of(abomination), ability_index=0,
    ).supported
    _w1g2_resolve_stack(game)
    died = game._destroy_swept_permanents(alice, lambda perm: perm is abomination)
    assert died == [] and game.is_on_battlefield(abomination)
    assert abomination.tapped, "regeneration taps it (CR 701.19a)"


def test_w1g2_the_wire_labels_a_typecycling_button_with_its_printed_line(set_pool):
    """The hand-ability offer names the line as printed — "Plainscycling {2}",
    not the search the rewrite made of it — so the client's existing cycling
    button reads it; the search is the existing ``search_library`` prompt."""
    from web.app import app as _w1g2_app
    from web.app import store as _w1g2_store

    client = _W1G2TestClient(_w1g2_app)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = _w1g2_store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    templar = set_pool("SCG")["Noble Templar"]
    game.players[0].hand.append(templar)
    game.players[0].mana_pool["W"] = 2

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = [e for e in state["hand_abilities"] if e["name"] == "Noble Templar"]
    assert entry["text"].startswith("Plainscycling {2}")
    assert entry["payable"] is True and entry["prohibited"] is None

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
    (offer,) = _w1g5_offers(game, 0)
    assert offer["morph_cost"] == "{U}" and offer["morph_cost_modifier"] == 2
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
#
# Dragons: Bladewing's Thrall's graveyard trigger (it compiled supported and
# never fired — the offer wrapping its return hid CR 113.6m's zone from the
# graveyard scan), Bladewing the Risen's "target Dragon permanent card".

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("SCG", "LEA", "ONS", "LGN"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_table(set_pool, *, graveyard=(), hand=(), interactive=()):
    me = _W1G6PlayerState(
        name="Me",
        graveyard=[_w1g6_card(set_pool, n) for n in graveyard],
        hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Swamp")] * 8,
    )
    opp = _W1G6PlayerState(name="Opp", library=[_w1g6_card(set_pool, "Forest")] * 8)
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game


def _w1g6_enter(game, set_pool, seat, name):
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_settle(game):
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)


def _w1g6_named(game, seat, name):
    return [p for p in game.controlled_by(seat) if p.card.name == name]


def test_w1g6_bladewings_thrall_returns_when_a_dragon_enters(set_pool):
    """"When a Dragon enters, you may return this card from your graveyard to
    the battlefield." Shivan Dragon enters: the Thrall comes back, and has
    flying while its controller controls a Dragon."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"])
    _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    assert [item.card.name for item in game.stack] == ["Bladewing's Thrall"]
    _w1g6_settle(game)
    (thrall,) = _w1g6_named(game, 0, "Bladewing's Thrall")
    assert not game.players[0].graveyard
    assert game._has_keyword(thrall, "flying")


def test_w1g6_bladewings_thrall_ignores_a_creature_that_is_not_a_dragon(set_pool):
    """The trigger's own noun phrase is asked of the entering permanent from
    the graveyard too — a Grizzly Bears triggers nothing."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"])
    _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert not game.stack
    assert [card.name for card in game.players[0].graveyard] == ["Bladewing's Thrall"]


def test_w1g6_bladewings_thrall_returns_under_its_owner_for_an_opponents_dragon(set_pool):
    """Ruling 2017-11-17: it "triggers even if a Dragon enters the battlefield
    under an opponent's control. The owner of Bladewing's Thrall, not the
    controller of that Dragon, will control Bladewing's Thrall." Asked, and
    declined, it stays."""
    game = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"], interactive={0})
    _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, "Bladewing's Thrall", accept=True)
    _w1g6_resolve_stack(game)
    (thrall,) = _w1g6_named(game, 0, "Bladewing's Thrall")
    # No Dragon of its controller's: no flying.
    assert not game._has_keyword(thrall, "flying")

    declined = _w1g6_table(set_pool, graveyard=["Bladewing's Thrall"], interactive={0})
    _w1g6_enter(declined, set_pool, 0, "Shivan Dragon")
    declined.resolve_top_of_stack()
    assert declined.confirm_optional_pay(0, "Bladewing's Thrall", accept=False)
    _w1g6_resolve_stack(declined)
    assert [card.name for card in declined.players[0].graveyard] == ["Bladewing's Thrall"]


def _w1g6_cast_bladewing(game):
    game._close_current_priority_step()
    assert game.queue_from_hand(0, "Bladewing the Risen").supported


def test_w1g6_bladewing_the_risen_offers_only_a_dragon_permanent_card(set_pool):
    """"…return target Dragon permanent card from your graveyard to the
    battlefield." The picker offers the Shivan Dragon and neither the Grizzly
    Bears nor the Lightning Bolt beside it."""
    game = _w1g6_table(
        set_pool, hand=["Bladewing the Risen"],
        graveyard=["Grizzly Bears", "Shivan Dragon", "Lightning Bolt"],
    )
    spec = game.cast_target_spec(0, _w1g6_card(set_pool, "Bladewing the Risen"))
    assert [t["name"] for t in spec["valid_targets"]] == ["Shivan Dragon"]
    _w1g6_cast_bladewing(game)
    _w1g6_settle(game)
    assert {p.card.name for p in game.controlled_by(0)} == {
        "Bladewing the Risen", "Shivan Dragon",
    }
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g6_bladewing_the_risen_asked_names_its_dragon_and_may_decline(set_pool):
    """An asked seat names the target as the trigger goes on the stack (CR
    603.3d) — offered the Dragon alone — and then answers the "may"."""
    for accept in (True, False):
        game = _w1g6_table(
            set_pool, hand=["Bladewing the Risen"],
            graveyard=["Grizzly Bears", "Shivan Dragon"], interactive={0},
        )
        _w1g6_cast_bladewing(game)
        game.resolve_top_of_stack()
        (choice,) = game.pending_choices
        assert choice.kind == "trigger_target"
        assert [t["name"] for t in choice.data["targets"]] == ["Shivan Dragon"]
        assert game.resolve_pending_choice(
            "trigger_target", 0, seat=0, graveyard_index=1
        )
        game.resolve_top_of_stack()
        assert game.confirm_optional_pay(0, "Bladewing the Risen", accept=accept)
        _w1g6_resolve_stack(game)
        returned = [p.card.name for p in game.controlled_by(0)]
        assert ("Shivan Dragon" in returned) is accept


def test_w1g6_bladewing_the_risen_does_nothing_when_its_target_leaves_first(set_pool):
    """CR 608.2b in response: the targeted Dragon card leaves the graveyard
    with the trigger on the stack, so the trigger has no legal target and
    nothing comes back — and no other card is taken in its place."""
    game = _w1g6_table(
        set_pool, hand=["Bladewing the Risen"],
        graveyard=["Shivan Dragon", "Shivan Dragon"],
    )
    _w1g6_cast_bladewing(game)
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Bladewing the Risen"]
    pile = game.players[0].graveyard
    game.players[0].exile.append(pile.pop(0))
    game.players[0].exile.append(pile.pop(0))
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Bladewing the Risen"]


def test_w1g6_bladewing_the_risen_pumps_dragon_creatures(set_pool):
    """"{B}{R}: Dragon creatures get +1/+1 until end of turn" — every Dragon,
    the opponent's too, and nothing else; gone at cleanup."""
    game = _w1g6_table(set_pool)
    bladewing = _w1g6_enter(game, set_pool, 0, "Bladewing the Risen")
    _w1g6_settle(game)
    theirs = _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    bears = _w1g6_enter(game, set_pool, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(0, "Bladewing the Risen").supported
    _w1g6_resolve_stack(game)
    assert (bladewing.effective_power, bladewing.effective_toughness) == (5, 5)
    assert (theirs.effective_power, theirs.effective_toughness) == (6, 6)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    game.resolve_cleanup_step(0)
    assert (theirs.effective_power, theirs.effective_toughness) == (5, 5)


# --- The drive list: Dragons supported on arrival ---------------------------


def test_w1g6_dragon_tyrant_is_kept_for_four_red_and_sacrificed_without(set_pool):
    """"At the beginning of your upkeep, sacrifice this creature unless you
    pay {R}{R}{R}{R}": four Mountains pay it, none cannot. It has flying,
    trample and double strike, and "{R}: +1/+0" pumps it."""
    for mountains in (4, 0):
        game = _w1g6_table(set_pool)
        tyrant = _w1g6_enter(game, set_pool, 0, "Dragon Tyrant")
        lands = [_w1g6_enter(game, set_pool, 0, "Mountain") for _ in range(mountains)]
        game.enforce_mana_costs = True
        game.start_turn(0)
        _w1g6_settle(game)
        assert game.is_on_battlefield(tyrant) is bool(mountains)
        assert all(land.tapped for land in lands)
    game = _w1g6_table(set_pool)
    tyrant = _w1g6_enter(game, set_pool, 0, "Dragon Tyrant")
    assert all(
        game._has_keyword(tyrant, word)
        for word in ("flying", "trample", "double strike")
    )
    assert game.activate_permanent_ability(0, "Dragon Tyrant").supported
    _w1g6_resolve_stack(game)
    assert tyrant.effective_power == 7


def test_w1g6_dragon_mage_wheels_both_hands_on_combat_damage(set_pool):
    """"Whenever this creature deals combat damage to a player, each player
    discards their hand, then draws seven cards." """
    from tests.helpers import declare_attack as _w1g6_declare_attack

    game = _w1g6_table(set_pool, hand=["Lightning Bolt", "Swamp"])
    game.players[1].hand = [_w1g6_card(set_pool, "Forest")]
    _w1g6_enter(game, set_pool, 0, "Dragon Mage")
    _w1g6_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g6_settle(game)
    assert game.players[1].life == 15
    assert len(game.players[0].hand) == 7 and len(game.players[1].hand) == 7
    assert sorted(c.name for c in game.players[0].graveyard) == ["Lightning Bolt", "Swamp"]
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]


def test_w1g6_dragonstalker_blocks_a_dragon_unharmed_and_dragons_cannot_block_it(set_pool):
    """"Protection from Dragons" (CR 702.16): blocking a Shivan Dragon it is
    dealt nothing and deals its 3, and a Dragon cannot block it."""
    game = _w1g6_table(set_pool)
    stalker = _w1g6_enter(game, set_pool, 1, "Dragonstalker")
    dragon = _w1g6_enter(game, set_pool, 0, "Shivan Dragon")
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    _w1g6_settle(game)
    assert game.is_on_battlefield(stalker) and stalker.damage_marked == 0
    assert dragon.damage_marked == 3

    game = _w1g6_table(set_pool)
    _w1g6_enter(game, set_pool, 0, "Dragonstalker")
    _w1g6_enter(game, set_pool, 1, "Shivan Dragon")
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "cannot block" in why

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
