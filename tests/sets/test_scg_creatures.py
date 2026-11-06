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
#
# Cost reductions keyed by what the spell is (CR 601.2f): the five creature-
# type Warchiefs, Krosan Drover's mana value, Mistform Warchief's shared type,
# Edgewalker's coloured reduction that does not spill (CR 118.7b/c switched
# off), and Rock Jockey's two prohibitions. Every cast below is a real cast
# with mana enforced and exactly the reduced price floating, so "it worked" is
# the pool emptying and the card on the board; the table's own readings of
# invented sentences are tests/rules/test_scg_w1g3_cost_reductions.py.
import pytest as _w1g3_pytest

from engine import Game as _W1G3Game
from engine import ai_cast_gates as _w1g3_ai_cast_gates
from engine import ai_casts as _w1g3_ai_casts
from engine.ai_payment import _cost_for as _w1g3_cost_for
from engine.ai_payment import tap_planned_lands as _w1g3_tap_planned_lands
from engine.models import Permanent as _W1G3Permanent
from engine.models import PlayerState as _W1G3PlayerState
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_table(catalog_by_name, *, interactive=False):
    """Seat 0 active in its precombat main phase with mana enforced."""
    library = [catalog_by_name["Grizzly Bears"]] * 10
    game = _W1G3Game(players=[
        _W1G3PlayerState(name="Alice", library=list(library)),
        _W1G3PlayerState(name="Bob", library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return game


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cast(game, card, mana, *, seat=0, **announce):
    """Cast *card* from *seat*'s hand with exactly *mana* floating; the result
    and what is left of the pool."""
    player = game.players[seat]
    player.hand.append(card)
    player.mana_pool.clear()
    player.mana_pool.update(mana)
    result = game.cast_from_hand(seat, card.name, **announce)
    return result, {k: v for k, v in player.mana_pool.items() if v}


def _w1g3_on_board(game, name, seat=0):
    return [p for p in game.controlled_by(seat) if p.card.name == name]


def _w1g3_slot(game, permanent, seat=0):
    """*permanent*'s battlefield slot, by identity — what a combat declaration
    names."""
    return next(
        i for i, perm in enumerate(game.players[seat].battlefield) if perm is permanent
    )


#: (reducer, discount, a spell of its type and the mana that pays it reduced,
#: a spell of another type at the same discount).
_W1G3_TYPED = [
    ("Daru Warchief", "Glory Seeker", {"W": 1}, "Grizzly Bears", {"G": 1}),
    ("Goblin Warchief", "Goblin Hero", {"R": 1, "C": 1}, "Grizzly Bears", {"G": 1}),
    ("Krosan Warchief", "Garruk's Gorehorn", {"G": 1, "C": 3}, "Grizzly Bears", {"G": 1}),
    ("Undead Warchief", "Scathe Zombies", {"B": 1, "C": 1}, "Grizzly Bears", {"G": 1}),
    ("Dragonspeaker Shaman", "Shivan Dragon", {"R": 2, "C": 2}, "Craw Wurm", {"G": 2, "C": 2}),
]


@_w1g3_pytest.mark.parametrize("reducer,typed,typed_mana,other,other_mana", _W1G3_TYPED)
def test_w1g3_a_type_warchief_discounts_its_type_and_nothing_else(
    set_pool, catalog_by_name, reducer, typed, typed_mana, other, other_mana,
):
    """"Goblin spells you cast cost {1} less to cast." The spell of the type
    resolves off the reduced price with nothing left over; a spell of any
    other type at the same discount is refused with the pool untouched; and an
    opponent's copy discounts nothing ("you cast", CR 109.5). Before this round
    the sentence read as "spells you cast" — every spell discounted — and only
    the card's being unsupported kept that off a board."""
    scg = set_pool("SCG")
    assert _w1g3_compile(scg[reducer]).supported
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, scg[reducer])

    result, left = _w1g3_cast(game, catalog_by_name[typed], typed_mana)
    assert result.supported, result.details
    assert left == {}
    assert f"{typed} costs less to cast ({reducer})" in game.log
    _w1g3_resolve_stack(game)
    assert _w1g3_on_board(game, typed)

    refused, left = _w1g3_cast(game, catalog_by_name[other], other_mana)
    assert not refused.supported and "insufficient mana" in refused.details
    assert left == other_mana
    assert catalog_by_name[other] in game.players[0].hand

    theirs = _w1g3_table(catalog_by_name)
    _w1g3_put(theirs, 1, scg[reducer])
    refused, left = _w1g3_cast(theirs, catalog_by_name[typed], typed_mana)
    assert not refused.supported and left == typed_mana


def test_w1g3_the_warchiefs_lords_ride_beside_their_reductions(set_pool, catalog_by_name):
    """Each Warchief's second line compiles and plays: Daru Warchief's Soldiers
    get +1/+2, Undead Warchief's Zombies +2/+1, Goblin Warchief's Goblins have
    haste — and a creature of another type is untouched by all three."""
    scg = set_pool("SCG")
    game = _w1g3_table(catalog_by_name)
    for name in ("Daru Warchief", "Undead Warchief", "Goblin Warchief"):
        _w1g3_put(game, 0, scg[name])
    seeker = _w1g3_put(game, 0, catalog_by_name["Glory Seeker"])
    zombies = _w1g3_put(game, 0, catalog_by_name["Scathe Zombies"])
    hero = _w1g3_put(game, 0, catalog_by_name["Goblin Hero"])
    bears = _w1g3_put(game, 0, catalog_by_name["Grizzly Bears"])
    game._recompute_continuous_effects()
    assert (seeker.effective_power, seeker.effective_toughness) == (3, 4)
    assert (zombies.effective_power, zombies.effective_toughness) == (4, 3)
    assert game._has_keyword(hero, "haste")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(bears, "haste")


def test_w1g3_goblin_warchief_takes_only_generic_mana_off(set_pool, catalog_by_name):
    """Goblin Warchief's ruling (2018-04-27): "reduces only generic mana in the
    cost of Goblin spells you cast. For example, it doesn't reduce the cost of
    Skirk Prospector below {R}." (CR 118.7a.) A {R} Goblin is refused with an
    empty pool and cast for its {R}; and the Goblin cast this turn has haste and
    attacks."""
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Goblin Warchief"])
    raiders = catalog_by_name["Mons's Goblin Raiders"]
    refused, _left = _w1g3_cast(game, raiders, {})
    assert not refused.supported
    result, left = _w1g3_cast(game, raiders, {"R": 1})
    assert result.supported and left == {}
    _w1g3_resolve_stack(game)
    (fresh,) = _w1g3_on_board(game, "Mons's Goblin Raiders")
    game._set_phase_and_step("combat", "declare_attackers")
    slot = _w1g3_slot(game, fresh)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why


def test_w1g3_a_face_down_goblin_is_no_goblin_but_the_three_is_still_reduced(
    set_pool, catalog_by_name,
):
    """CR 708.4 / 702.37c: a card cast face down is a 2/2 with no subtypes
    before it is put on the stack, and "any effects … that would apply to
    casting an object with these characteristics … are applied" — so Goblin
    Warchief does not discount a face-down Skirk Marauder ({3}: two floating is
    refused, three pays it), while a reduction that names a face-down spell
    (Dream Chisel) applies to the {3} alternative cost (CR 601.2f, 118.9d)
    beside the Warchief that does not."""
    marauder = catalog_by_name["Skirk Marauder"]
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Goblin Warchief"])
    refused, left = _w1g3_cast(game, marauder, {"C": 2}, alternative_cost=True)
    assert not refused.supported and left == {"C": 2}
    result, left = _w1g3_cast(game, marauder, {"C": 3}, alternative_cost=True)
    assert result.supported, result.details
    assert left == {}
    assert not any("(Goblin Warchief)" in line for line in game.log)

    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Goblin Warchief"])
    _w1g3_put(game, 0, catalog_by_name["Dream Chisel"])
    result, left = _w1g3_cast(game, marauder, {"C": 2}, alternative_cost=True)
    assert result.supported, result.details
    assert left == {}
    assert "Face-down creature costs less to cast (Dream Chisel)" in game.log


def test_w1g3_krosan_drover_reads_the_mana_value_on_the_stack(set_pool, catalog_by_name):
    """"Creature spells you cast with mana value 6 or greater cost {2} less to
    cast." Craw Wurm (6) pays {2}{G}{G}; Durkwood Boars (5) and Pyramids (an
    artifact of 6) are refused at the price the discount would have made.
    Krakilin ({X}{G}{G}) has mana value X + 2 on the stack (CR 202.3e):
    announced at X=4 it is discounted and enters with four counters, and the
    AI's price for the same announcement agrees."""
    drover = set_pool("SCG")["Krosan Drover"]
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, drover)
    result, left = _w1g3_cast(game, catalog_by_name["Craw Wurm"], {"G": 2, "C": 2})
    assert result.supported and left == {}
    _w1g3_resolve_stack(game)
    assert _w1g3_on_board(game, "Craw Wurm")
    for name, mana in (("Durkwood Boars", {"G": 1, "C": 2}), ("Pyramids", {"C": 4})):
        refused, left = _w1g3_cast(game, catalog_by_name[name], mana)
        assert not refused.supported and "insufficient mana" in refused.details, name
        assert left == mana, name

    krakilin = catalog_by_name["Krakilin"]
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, drover)
    assert _w1g3_cost_for(game, game.players[0], krakilin, 4)["generic"] == 2
    assert _w1g3_cost_for(game, game.players[0], krakilin, 3)["generic"] == 3
    result, left = _w1g3_cast(game, krakilin, {"G": 2, "C": 2}, x_value=4)
    assert result.supported, result.details
    assert left == {}
    assert "Krakilin costs less to cast at X=4 (Krosan Drover)" in game.log
    _w1g3_resolve_stack(game)
    (beast,) = _w1g3_on_board(game, "Krakilin")
    assert (beast.effective_power, beast.effective_toughness) == (4, 4)

    # X=3 is mana value 5: no discount, so {3}{G}{G} is owed and four is short.
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, drover)
    refused, left = _w1g3_cast(game, krakilin, {"G": 2, "C": 2}, x_value=3)
    assert not refused.supported and left == {"G": 2, "C": 2}


def test_w1g3_mistform_warchief_shares_through_the_layers(set_pool, catalog_by_name):
    """"Creature spells you cast that share a creature type with this creature
    cost {1} less to cast." An Illusion spell is discounted and a Goblin is not;
    after "{T}: This creature becomes the creature type of your choice until
    end of turn" names Goblin (answered as an interactive seat), the Goblin is
    and the Illusion no longer is — the type is *set* (CR 205.1a). Mistform
    Ultimus is every creature type in every zone (CR 604.3) and shares either
    way."""
    lgn = set_pool("LGN")
    game = _w1g3_table(catalog_by_name, interactive=True)
    _w1g3_put(game, 0, set_pool("SCG")["Mistform Warchief"])
    forces, hero = catalog_by_name["Phantasmal Forces"], catalog_by_name["Goblin Hero"]
    result, left = _w1g3_cast(game, forces, {"U": 1, "C": 2})
    assert result.supported and left == {}
    refused, _left = _w1g3_cast(game, hero, {"R": 1, "C": 1})
    assert not refused.supported
    game.players[0].hand.clear()

    used = game.activate_permanent_ability(0, "Mistform Warchief")
    assert used.supported, used.details
    assert [choice.kind for choice in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g3_resolve_stack(game)

    result, left = _w1g3_cast(game, hero, {"R": 1, "C": 1})
    assert result.supported and left == {}
    refused, _left = _w1g3_cast(game, forces, {"U": 1, "C": 2})
    assert not refused.supported
    game.players[0].hand.clear()
    result, left = _w1g3_cast(game, lgn["Mistform Ultimus"], {"U": 1, "C": 2})
    assert result.supported and left == {}


def test_w1g3_mistform_warchief_default_answer_and_discount_agree(set_pool, catalog_by_name):
    """The same activation for a seat nobody asks: whatever type the default
    names, a Goblin spell is discounted exactly when the Warchief became one."""
    game = _w1g3_table(catalog_by_name)
    warchief = _w1g3_put(game, 0, set_pool("SCG")["Mistform Warchief"])
    assert game.activate_permanent_ability(0, "Mistform Warchief").supported
    _w1g3_resolve_stack(game)
    game.auto_resolve_pending_choices()
    became_goblin = warchief.has_type("goblin")
    result, _left = _w1g3_cast(game, catalog_by_name["Goblin Hero"], {"R": 1, "C": 1})
    assert result.supported == became_goblin


def test_w1g3_edgewalker_takes_only_coloured_mana_off(set_pool, catalog_by_name):
    """"Cleric spells you cast cost {W}{B} less to cast. This effect reduces
    only the amount of colored mana you pay." The printed example — a {1}{W}
    Cleric costs {1} — is Samite Healer; Keepers of the Faith ({1}{W}{W}) pays
    {1}{W}; Marble Priest ({5}, a Cleric with no coloured pip) still pays all
    five, where CR 118.7b would have spilled {2} onto generic; a Bear is not a
    Cleric. Two Edgewalkers are cumulative (2004-10-04): Keepers then pays {1},
    and a third Edgewalker ({1}{W}{B}, a Cleric) pays {1}."""
    edgewalker = set_pool("SCG")["Edgewalker"]
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, edgewalker)
    for name, mana in (("Samite Healer", {"C": 1}),
                       ("Keepers of the Faith", {"W": 1, "C": 1}),
                       ("Marble Priest", {"C": 5})):
        result, left = _w1g3_cast(game, catalog_by_name[name], mana)
        assert result.supported, (name, result.details)
        assert left == {}, name
    for name, mana in (("Marble Priest", {"C": 3}), ("Grizzly Bears", {"C": 1})):
        refused, left = _w1g3_cast(game, catalog_by_name[name], mana)
        assert not refused.supported and left == mana, name
        game.players[0].hand.clear()

    _w1g3_put(game, 0, edgewalker)
    for card, mana in ((catalog_by_name["Keepers of the Faith"], {"C": 1}),
                       (edgewalker, {"C": 1})):
        result, left = _w1g3_cast(game, card, mana)
        assert result.supported, (card.name, result.details)
        assert left == {}


def test_w1g3_a_reduced_goblin_is_proposed_and_paid_by_the_ai_from_lands(
    set_pool, catalog_by_name,
):
    """The AI's price is the reduced one (``ai_payment._cost_for``, the cast
    path's three readers): with Goblin Warchief out and two Mountains, Goblin
    Hero ({2}{R}) is proposed, and the cast it proposes taps both Mountains."""
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Goblin Warchief"])
    mountains = [_w1g3_put(game, 0, catalog_by_name["Mountain"]) for _ in range(2)]
    hero = catalog_by_name["Goblin Hero"]
    game.players[0].hand.append(hero)
    assert _w1g3_cost_for(game, game.players[0], hero, None) == {
        "W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "generic": 1,
    }
    assert _w1g3_ai_cast_gates._can_cast_with_targets(game, 0, hero)
    action = _w1g3_ai_casts._cast_candidate(game, 0, hero, 0)
    assert action is not None
    _w1g3_tap_planned_lands(game, 0, action)
    assert all(m.tapped for m in mountains)
    assert game.cast_from_hand(0, "Goblin Hero").supported
    _w1g3_resolve_stack(game)
    assert _w1g3_on_board(game, "Goblin Hero")
    assert not any(game.players[0].mana_pool.values())

    # Without the Warchief the same two Mountains do not pay for it.
    bare = _w1g3_table(catalog_by_name)
    for _ in range(2):
        _w1g3_put(bare, 0, catalog_by_name["Mountain"])
    bare.players[0].hand.append(hero)
    assert _w1g3_ai_casts._cast_candidate(bare, 0, hero, 0) is None


def test_w1g3_the_castable_highlight_glows_at_the_reduced_price(set_pool, catalog_by_name):
    """The web's castable highlight prices a cast through the same readers
    (``state_view._card_castable_now`` → ``cost_reduction_for_cast`` →
    ``board_can_pay``): two Mountains glow Goblin Hero under Goblin Warchief
    and Craw Wurm's {4}{G}{G} glows on four Forests under Krosan Drover; neither
    glows without its reducer."""
    from fastapi.testclient import TestClient

    from web.app import app, store
    from web.state_view import _compute_playable_hand_indices

    client = TestClient(app)
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    scg = set_pool("SCG")
    for reducer, land, spell in (
        ("Goblin Warchief", "Mountain", "Goblin Hero"),
        ("Krosan Drover", "Forest", "Craw Wurm"),
    ):
        glows = {}
        for with_reducer in (True, False):
            game = _w1g3_table(catalog_by_name)
            if with_reducer:
                _w1g3_put(game, 0, scg[reducer])
            count = 2 if land == "Mountain" else 4
            for _ in range(count):
                _w1g3_put(game, 0, catalog_by_name[land])
            game.players[0].hand.append(catalog_by_name[spell])
            session.game = game
            session.current_turn = 0
            glows[with_reducer] = 0 in _compute_playable_hand_indices(session, 0)
        assert glows == {True: True, False: False}, (reducer, spell)


def test_w1g3_rock_jockey_cannot_be_cast_after_a_land(set_pool, catalog_by_name):
    """"You can't cast Rock Jockey if you've played a land this turn." (CR
    601.3.) Played, not put: a land drop this turn refuses the cast with
    nothing spent and the AI does not propose it; with no land played it is
    cast. The ruling (2004-10-04) confines it to the card where it could be
    cast from, which a prohibition asked of the card being cast is."""
    jockey = set_pool("SCG")["Rock Jockey"]
    game = _w1g3_table(catalog_by_name)
    game.players[0].hand.append(catalog_by_name["Mountain"])
    assert game.cast_from_hand(0, "Mountain").supported
    refused, left = _w1g3_cast(game, jockey, {"R": 1, "C": 2})
    assert not refused.supported
    assert refused.details == "can't cast Rock Jockey: you've played a land this turn"
    assert left == {"R": 1, "C": 2} and jockey in game.players[0].hand
    assert not _w1g3_ai_cast_gates._can_cast_with_targets(game, 0, jockey)

    # A land an effect put onto the battlefield was not played.
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, catalog_by_name["Mountain"])
    result, left = _w1g3_cast(game, jockey, {"R": 1, "C": 2})
    assert result.supported and left == {}


def test_w1g3_rock_jockey_cast_this_turn_stops_its_controllers_land_drop(
    set_pool, catalog_by_name,
):
    """"You can't play lands if this creature was cast this turn." The Jockey
    cast this turn refuses its controller's land drop and nobody else's; next
    turn the land is played. A Jockey that was put onto the battlefield, not
    cast (CR 701.5a's distinction), takes nothing away."""
    jockey = set_pool("SCG")["Rock Jockey"]
    game = _w1g3_table(catalog_by_name)
    result, _left = _w1g3_cast(game, jockey, {"R": 1, "C": 2})
    assert result.supported
    _w1g3_resolve_stack(game)
    assert _w1g3_on_board(game, "Rock Jockey")
    game.players[0].hand.append(catalog_by_name["Mountain"])
    refused = game.cast_from_hand(0, "Mountain")
    assert not refused.supported
    assert refused.details == "can't play lands: Rock Jockey was cast this turn"
    assert not game._may_play_another_land(0)
    assert game._may_play_another_land(1), "its controller alone"

    game.turn += 1
    assert game._may_play_another_land(0), "this turn alone"

    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, jockey)
    assert game._may_play_another_land(0), "put, not cast"


def test_w1g3_krosan_warchief_regenerates_a_beast_and_offers_only_beasts(
    set_pool, catalog_by_name,
):
    """"{1}{G}: Regenerate target Beast." The picker offers Beasts alone; the
    Warchief — a Beast itself — shields itself and survives a Lightning Bolt
    tapped (CR 701.19), while the unshielded Beast beside it does not."""
    warchief_card = set_pool("SCG")["Krosan Warchief"]
    (ability,) = _w1g3_compile(warchief_card).activated_abilities
    spec = _w1g3_activation_spec(ability)
    assert spec["kind"] == "creature" and spec.get("filter") == {"subtype_filter": "beast"}

    game = _w1g3_table(catalog_by_name)
    warchief = _w1g3_put(game, 0, warchief_card)
    gorehorn = _w1g3_put(game, 0, catalog_by_name["Garruk's Gorehorn"])
    game.players[0].mana_pool.update({"G": 1, "C": 1})
    used = game.activate_permanent_ability(
        0, "Krosan Warchief", target_permanent_ids=[warchief.permanent_id],
        target_player_index=0,
    )
    assert used.supported, used.details
    _w1g3_resolve_stack(game)
    bolt = catalog_by_name["Lightning Bolt"]
    for target in (warchief, gorehorn):
        result, _left = _w1g3_cast(
            game, bolt, {"R": 1}, target_permanent_ids=[target.permanent_id],
            target_player_index=0,
        )
        assert result.supported, result.details
        _w1g3_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Krosan Warchief"]
    assert warchief.tapped


# --- supported on arrival: the family's cards, driven ----------------------


def test_w1g3_siege_gang_commander_under_goblin_warchief(set_pool, catalog_by_name):
    """Siege-Gang Commander ({3}{R}{R}) costs {2}{R}{R} under Goblin Warchief.
    Its three Goblin tokens are made, not cast — no discount is involved —
    and they have haste from the Warchief. "{1}{R}, Sacrifice a Goblin: This
    creature deals 2 damage to any target" sacrifices a token and deals 2."""
    scg = set_pool("SCG")
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, scg["Goblin Warchief"])
    result, left = _w1g3_cast(game, scg["Siege-Gang Commander"], {"R": 2, "C": 2})
    assert result.supported and left == {}
    _w1g3_resolve_stack(game)
    tokens = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    assert len(tokens) == 3
    assert all(t.has_type("goblin") and game._has_keyword(t, "haste") for t in tokens)

    game.players[0].mana_pool.update({"R": 1, "C": 1})
    used = game.activate_permanent_ability(
        0, "Siege-Gang Commander", target_player_index=1,
        cost_permanent_ids=[tokens[0].permanent_id],
    )
    assert used.supported, used.details
    _w1g3_resolve_stack(game)
    assert game.players[1].life == 18
    assert len([p for p in game.controlled_by(0) if p.metadata.get("is_token")]) == 2


def test_w1g3_goblin_brigand_with_haste_must_attack_the_turn_it_arrives(
    set_pool, catalog_by_name,
):
    """Goblin Brigand: "This creature attacks each combat if able." Under Goblin
    Warchief it has haste, so it is able the turn it is cast (CR 508.1d): a
    declaration leaving it home is refused, one sending it is accepted."""
    scg = set_pool("SCG")
    game = _w1g3_table(catalog_by_name)
    warchief = _w1g3_put(game, 0, scg["Goblin Warchief"])
    result, left = _w1g3_cast(game, scg["Goblin Brigand"], {"R": 1})
    assert result.supported and left == {}
    _w1g3_resolve_stack(game)
    (brigand,) = _w1g3_on_board(game, "Goblin Brigand")
    assert game._has_keyword(brigand, "haste")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [_w1g3_slot(game, warchief)], defending_player_index=1,
    )
    assert not ok, "the Brigand must attack"
    ok, why = game.declare_attackers(
        0, [_w1g3_slot(game, brigand)], defending_player_index=1,
    )
    assert ok, why


def test_w1g3_wirewood_symbiote_returns_an_elf_to_untap_once_a_turn(
    set_pool, catalog_by_name,
):
    """"Return an Elf you control to its owner's hand: Untap target creature.
    Activate only once each turn." The Elf goes home and the target untaps; a
    second activation the same turn is refused."""
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Wirewood Symbiote"])
    elves = [_w1g3_put(game, 0, catalog_by_name["Llanowar Elves"]) for _ in range(2)]
    tapped = _w1g3_put(game, 0, catalog_by_name["Grizzly Bears"])
    tapped.tapped = True
    used = game.activate_permanent_ability(
        0, "Wirewood Symbiote", target_permanent_ids=[tapped.permanent_id],
        target_player_index=0, cost_permanent_ids=[elves[0].permanent_id],
    )
    assert used.supported, used.details
    _w1g3_resolve_stack(game)
    assert not tapped.tapped
    assert [c.name for c in game.players[0].hand] == ["Llanowar Elves"]
    tapped.tapped = True
    again = game.activate_permanent_ability(
        0, "Wirewood Symbiote", target_permanent_ids=[tapped.permanent_id],
        target_player_index=0, cost_permanent_ids=[elves[1].permanent_id],
    )
    assert not again.supported
    assert tapped.tapped and elves[1] in game.controlled_by(0)


def test_w1g3_cabal_interrogator_makes_a_revealed_card_discarded(set_pool, catalog_by_name):
    """"{X}{B}, {T}: Target player reveals X cards from their hand and you choose
    one of them. That player discards that card. Activate only as a sorcery."
    At X=2 the opponent discards one card, at sorcery speed only."""
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Cabal Interrogator"])
    game.players[1].hand.extend(
        [catalog_by_name["Lightning Bolt"], catalog_by_name["Grizzly Bears"],
         catalog_by_name["Forest"]]
    )
    game.players[0].mana_pool.update({"B": 1, "C": 2})
    used = game.activate_permanent_ability(
        0, "Cabal Interrogator", target_player_index=1, x_value=2,
    )
    assert used.supported, used.details
    _w1g3_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g3_resolve_stack(game)
    assert len(game.players[1].hand) == 2
    assert len(game.players[1].graveyard) == 1
    assert game.players[1].graveyard[0].name in ("Lightning Bolt", "Grizzly Bears", "Forest")

    # Sorcery speed: on the opponent's turn the ability is refused.
    game = _w1g3_table(catalog_by_name)
    _w1g3_put(game, 0, set_pool("SCG")["Cabal Interrogator"])
    game.players[1].hand.append(catalog_by_name["Forest"])
    game.active_player_index = 1
    game.start_priority_window(0)
    game.players[0].mana_pool.update({"B": 1, "C": 1})
    refused = game.activate_permanent_ability(
        0, "Cabal Interrogator", target_player_index=1, x_value=1,
    )
    assert not refused.supported

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

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.damage_redirects import redirects_on as _w1g7_redirects_on
from engine.face_down import (is_face_down as _w1g7_is_face_down,
                              morph_cost as _w1g7_morph_cost)
from engine.mana_payment import mana_cost_from_symbols as _w1g7_symbols
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.special_actions import (
    take_permanent_special_action as _w1g7_take_special_action)
from engine.targeting import derive_instruction_spec as _w1g7_instruction_spec
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_perm(card):
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_game(mine=(), theirs=(), *, hand=(), their_hand=()):
    me = _W1G7PlayerState(
        name="P0", battlefield=[_w1g7_perm(c) for c in mine], hand=list(hand), life=20,
    )
    them = _W1G7PlayerState(
        name="P1", battlefield=[_w1g7_perm(c) for c in theirs],
        hand=list(their_hand), life=20,
    )
    game = _W1G7Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    return game


def _w1g7_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Goblin Psychopath -------------------------------------------------------
#
# "Whenever this creature attacks or blocks, flip a coin. If you lose the flip,
# the next time it would deal combat damage this turn, it deals that damage to
# you instead." A CR 614.9 redirect of its own next combat damage to anyone,
# armed on resolution (ruling 2004-10-04: "resolves before combat damage is
# assigned"). The flip is the engine's (``handlers/_common.flip_coin``),
# fixed here through the module ``control_flow`` reads it from.


def _w1g7_flip(monkeypatch, won):
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: won
    )


def _w1g7_psychopath_attacks(set_pool, monkeypatch, *, won, blockers=(), blocks=None):
    _w1g7_flip(monkeypatch, won)
    game = _w1g7_game(mine=[set_pool("SCG")["Goblin Psychopath"]], theirs=list(blockers))
    _w1g7_declare_attack(game, 0, blocks=blocks or {})
    _w1g7_resolve_stack(game)
    return game


def test_w1g7_goblin_psychopath_losing_the_flip_hits_its_controller(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    assert any("lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 15 and game.players[1].life == 20
    assert any(
        "5 damage to P1 is dealt to P0 instead (Goblin Psychopath)" in line
        for line in game.log
    )


def test_w1g7_goblin_psychopath_winning_the_flip_deals_its_damage(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=True)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 15


def test_w1g7_goblin_psychopath_one_time_covers_every_blocker(set_pool, monkeypatch):
    """"The next time" is one time (CR 510.2: combat damage is dealt at once):
    blocked by two, both blockers' shares go to its controller."""
    pool = set_pool("2ED")
    game = _w1g7_psychopath_attacks(
        set_pool, monkeypatch, won=False,
        blockers=(pool["Grizzly Bears"], pool["Hill Giant"]), blocks={0: 0, 1: 0},
    )
    game.advance_combat_phase()
    assert game.current_step == "combat_damage"
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 3}})
    assert ok, why
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == 15
    assert [c.name for c in game.players[1].graveyard] == []
    assert [c.name for c in game.players[0].graveyard] == ["Goblin Psychopath"]
    # The time is over once the step's dealing is (``end_simultaneous_redirects``).
    assert _w1g7_redirects_on(game.players[0]) == []


def test_w1g7_goblin_psychopath_blocking_and_losing_sends_its_damage_home(
    set_pool, monkeypatch
):
    _w1g7_flip(monkeypatch, False)
    giant = set_pool("2ED")["Hill Giant"]
    game = _w1g7_game(mine=[giant], theirs=[set_pool("SCG")["Goblin Psychopath"]])
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_resolve_stack(game)
    assert any("Goblin Psychopath: lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    # Its 5 went to its own controller; the Giant's 3 still landed on it.
    assert game.players[1].life == 15
    assert _w1g7_named(game, 0, "Hill Giant").damage_marked == 0
    assert _w1g7_named(game, 1, "Goblin Psychopath").damage_marked == 3


def test_w1g7_goblin_psychopath_gone_before_damage_hurts_nobody(set_pool, monkeypatch):
    """The ruling's point: the trigger resolves first, "This gives you a chance
    to possibly get rid of it before it hurts you." Removed from the battlefield
    after the flip, it deals no damage and the record moves none."""
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    psychopath = _w1g7_named(game, 0, "Goblin Psychopath")
    game.players[0].hand.append(set_pool("2ED")["Unsummon"])
    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[psychopath.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 20


def test_w1g7_goblin_psychopath_compiles_its_whole_line(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Goblin Psychopath"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported
    steps = trigger.instruction.payload["steps"]
    assert [s.kind for s in steps] == ["flip_coin", "if_then"]
    (redirect,) = steps[1].payload["then"]
    assert redirect.payload == {"protects": "any", "combat_only": True, "uses": 1}
    # It targets nothing, so nothing is asked of the picker.
    assert _w1g7_instruction_spec([trigger.instruction]) is None


# --- Karona's Zealot ---------------------------------------------------------
#
# "When this creature is turned face up, all damage that would be dealt to it
# this turn is dealt to target creature instead." Rulings (2018-03-16): a target
# that has left or stopped being a creature takes nothing — later damage stays
# on the Zealot — and the damaged permanent's controller orders replacements.


def _w1g7_turn_up_zealot(set_pool, game, seat=0):
    zealot = set_pool("SCG")["Karona's Zealot"]
    player = game.players[seat]
    player.hand.append(zealot)
    game.enforce_mana_costs = True
    player.mana_pool.update({"C": 3})
    assert game.queue_from_hand(seat, "Karona's Zealot", alternative_cost=True).supported
    _w1g7_resolve_stack(game)
    (permanent,) = [p for p in game.controlled_by(seat) if _w1g7_is_face_down(p)]
    permanent.metadata["summoning_sickness_turn"] = -99
    for symbol, count in _w1g7_symbols(_w1g7_morph_cost(zealot)).items():
        key = "C" if symbol == "generic" else symbol
        player.mana_pool[key] = player.mana_pool.get(key, 0) + count
    game.priority_player_index = seat
    assert _w1g7_take_special_action(game, seat, permanent, "turn_face_up") is None
    assert sum(player.mana_pool.values()) == 0
    game.enforce_mana_costs = False
    return permanent


def _w1g7_bolt(set_pool, game, target, seat=1):
    game.players[seat].hand.append(set_pool("2ED")["Lightning Bolt"])
    assert game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()


def test_w1g7_karonas_zealot_moves_all_its_damage_this_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"], pool["Wall of Stone"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    (trigger,) = [item for item in game.stack if item.card.name == "Karona's Zealot"]
    wall = _w1g7_named(game, 1, "Wall of Stone")
    # The trigger's target, named by id as an announcement names it.
    trigger.target_permanent_id = [wall.permanent_id]
    _w1g7_resolve_stack(game)
    assert any(
        "all damage that would be dealt to Karona's Zealot this turn is dealt to "
        "Wall of Stone instead" in line for line in game.log
    )
    # Every instance this turn, not the next one: two Bolts, both moved.
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 3
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 6


def test_w1g7_karonas_zealot_target_gone_leaves_the_damage_on_it(set_pool):
    """The ruling's example: the 1/1 took the first 3 and died; the next 3 has
    nowhere to go and is dealt to the Zealot (CR 614.9)."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0
    assert "Grizzly Bears" in [c.name for c in game.players[1].graveyard]
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_redirect_ends_with_the_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    assert _w1g7_redirects_on(zealot)
    game.resolve_cleanup_step(0)
    assert _w1g7_redirects_on(zealot) == []
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_targets_a_creature(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Karona's Zealot"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported and trigger.condition.kind == "turned_face_up"
    spec = _w1g7_instruction_spec([trigger.instruction])
    assert spec is not None and spec.get("kind") == "creature", spec


@_w1g7_pytest.mark.parametrize("asked", [False, True], ids=["default", "asked"])
def test_w1g7_karonas_zealot_beside_a_shield_its_controller_orders(set_pool, asked):
    """CR 616.1: a prevention shield on the Zealot and its redirect contend over
    one Bolt, and the Zealot's controller chooses (ruling 2018-03-16). A seat
    nobody asks moves the damage first (redirects sit ahead of the shields,
    ``replacements/registry.py``); one that is asked may spend the shield."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]], hand=[pool["Healing Salve"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    giant = _w1g7_named(game, 1, "Hill Giant")
    assert game.queue_from_hand(
        0, "Healing Salve", mode_index=1, target_permanent_ids=[zealot.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    if asked:
        game.interactive_seats = {0}
    game.players[1].hand.append(pool["Lightning Bolt"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[zealot.permanent_id]
    ).supported
    if not asked:
        _w1g7_resolve_stack(game)
        assert zealot.damage_marked == 0 and giant.damage_marked == 3
        return
    game.resolve_top_of_stack()
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert order.player_index == 0 and len(order.data["options"]) == 2
    keys = list(order.data["_keys"])
    shield_first = next(
        i for i, key in enumerate(keys) if key != "_apply_recorded_redirect"
    )
    assert "_apply_recorded_redirect" in keys
    assert game.resolve_pending_choice("effect_order", 0, option_index=shield_first)
    _w1g7_resolve_stack(game)
    assert zealot.damage_marked == 0 and giant.damage_marked == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Xantid Swarm: "Whenever this creature attacks, defending player can't cast
# spells this turn." The seat the attack froze (CR 506.2, 603.10), through
# the cast-prohibition table every cast path asks.
from engine import Game as _W1G8Game
from engine.cast_prohibitions import cast_prohibition as _w1g8_cast_prohibition
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_combat(set_pool, attackers, *, seats=2, hands=None):
    """*attackers* on seat 0, every seat holding *hands*[seat], at seat 0's
    declare-attackers step."""
    lea = set_pool("LEA")
    players = [
        _W1G8PlayerState(
            name=f"P{seat}", hand=list((hands or {}).get(seat, ())),
            library=[lea["Plains"]] * 5,
        )
        for seat in range(seats)
    ]
    game = _W1G8Game(players=players)
    game.enforce_mana_costs = False
    mine = []
    for card in attackers:
        perm = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        mine.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game, mine


def test_w1g8_xantid_swarm_stops_the_defending_player_casting_this_turn(set_pool):
    """Before the trigger resolves the defender may still cast (2016-06-08:
    "The defending player may cast spells before Xantid Swarm's triggered
    ability resolves."); once it has, every spell is refused — an instant in
    combat and a creature later — while the attacker casts freely."""
    lea = set_pool("LEA")
    growth = lea["Giant Growth"]
    game, (swarm,) = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"]],
        hands={0: [growth], 1: [growth, growth, lea["Grizzly Bears"]]},
    )
    bears = _W1G8Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    assert game.declare_attackers(0, [0], 1)[0]
    assert [item.card.name for item in game.stack] == ["Xantid Swarm"]
    # In response: allowed.
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    assert any("P1 can't cast any spells this turn (Xantid Swarm)" in line for line in game.log)

    refused = game.cast_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert "can't cast any spells this turn" in refused.details
    prohibited = _w1g8_cast_prohibition(game, 1, lea["Grizzly Bears"])
    assert prohibited is not None and prohibited.kind == "casting_forbidden_this_turn"
    assert len(game.players[1].hand) == 2
    # The attacker is not bound.
    assert _w1g8_cast_prohibition(game, 0, growth) is None
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[swarm.permanent_id]).supported


def test_w1g8_xantid_swarm_binds_only_the_player_it_attacked(set_pool):
    """2016-06-08: "In a multiplayer game, only the player Xantid Swarm
    attacked is affected. Other defending players may cast spells." Swarm at
    P2, a Bear at P1: only P2 is stopped."""
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"], lea["Grizzly Bears"]], seats=3,
    )
    ok, why = game.declare_attackers(0, [0, 1], attacker_targets={0: 2, 1: 1})
    assert ok, why
    _w1g8_resolve_stack(game)
    growth = lea["Giant Growth"]
    assert _w1g8_cast_prohibition(game, 2, growth) is not None
    assert _w1g8_cast_prohibition(game, 1, growth) is None
    assert _w1g8_cast_prohibition(game, 0, growth) is None


def test_w1g8_xantid_swarm_ban_ends_with_the_turn(set_pool):
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(set_pool, [set_pool("SCG")["Xantid Swarm"]])
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g8_resolve_stack(game)
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is not None
    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
