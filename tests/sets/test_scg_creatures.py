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
#
# Ancient Ooze's CR 604.3 total ("the total mana value of other creatures you
# control", ``evaluate_count``'s ``total_mana_value``), Kurgadon's cast
# trigger by mana value (``cast_mana_value``), and the drive list: Fierce
# Empath, Vengeful Dead, Consumptive Goo.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.face_down import face_down_card as _w1g4_face_down
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from engine.tokens import make_token_card as _w1g4_token
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_table(set_pool, hand=(), *, library=None, interactive=False):
    lea = set_pool("LEA")
    alice = _W1G4PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) if library is not None else [lea["Island"]] * 8,
    )
    bob = _W1G4PlayerState(name="Bob", library=[lea["Island"]] * 8)
    game = _W1G4Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    _w1g4_resolve_stack(game)
    return permanent


def _w1g4_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g4_ancient_ooze_is_the_total_mana_value_of_your_other_creatures(set_pool):
    """Bears (2) and Hill Giant (4) are 6; the 2004-10-04 ruling's token and
    face-down creature add 0; the Ooze leaves itself out ("other"), the
    noncreature Iceberg is not a creature, and the opponent's Shivan Dragon is
    not "you control"."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool)
    ooze = _w1g4_put(game, 0, set_pool("SCG")["Ancient Ooze"])
    for card in (
        lea["Grizzly Bears"], lea["Hill Giant"], set_pool("ICE")["Iceberg"],
        _w1g4_face_down(lea["Shivan Dragon"]),
        _w1g4_token("Soldier", 1, 1, "Token Creature — Soldier"),
    ):
        _w1g4_put(game, 0, card)
    _w1g4_put(game, 1, lea["Shivan Dragon"])
    game.check_state_based_actions()
    assert _w1g4_pt(ooze) == (6, 6), game.log


def test_w1g4_ancient_ooze_is_recomputed_as_the_board_changes(set_pool):
    """CR 604.3 applies continuously: a creature leaving shrinks it, and alone
    it is 0/0 and dies to CR 704.5f."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool)
    ooze = _w1g4_put(game, 0, set_pool("SCG")["Ancient Ooze"])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g4_put(game, 0, lea["Hill Giant"])
    game.check_state_based_actions()
    assert _w1g4_pt(ooze) == (6, 6)
    game.remove_from_battlefield(giant)
    game.check_state_based_actions()
    assert _w1g4_pt(ooze) == (2, 2)
    game.remove_from_battlefield(bears)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(ooze), game.log
    assert [card.name for card in game.players[0].graveyard][-1] == "Ancient Ooze"


def _w1g4_kurgadon_casts(set_pool, spell, *, x_value=None, seat=0):
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool)
    kurgadon = _w1g4_put(game, 0, set_pool("SCG")["Kurgadon"])
    game.players[seat].hand.append(lea[spell])
    game.active_player_index = seat
    announced = {} if x_value is None else {"x_value": x_value}
    assert game.queue_from_hand(seat, spell, **announced).supported
    _w1g4_resolve_stack(game)
    return game, kurgadon


@_w1g4_pytest.mark.parametrize("spell, x_value, seat, counters", [
    ("Shivan Dragon", None, 0, 3),     # a creature spell, mana value 6
    ("Lord of the Pit", None, 0, 3),   # 7
    ("Sengir Vampire", None, 0, 0),    # 5
    ("Rock Hydra", 4, 0, 3),           # {X}{R}{R}, X=4: 6 on the stack
    ("Rock Hydra", 3, 0, 0),           # X=3: 5
    ("Shivan Dragon", None, 1, 0),     # an opponent's cast is not "you cast"
])
def test_w1g4_kurgadon_grows_on_your_six_drop_creature_spells(
    set_pool, spell, x_value, seat, counters,
):
    """"Whenever you cast a creature spell with mana value 6 or greater, put
    three +1/+1 counters on this creature." CR 202.3b: an X in a spell's cost
    is its announced value on the stack."""
    game, kurgadon = _w1g4_kurgadon_casts(set_pool, spell, x_value=x_value, seat=seat)
    assert _w1g4_pt(kurgadon) == (3 + counters, 3 + counters), game.log


def test_w1g4_kurgadon_ignores_a_six_drop_that_is_not_a_creature(set_pool):
    """Decree of Annihilation is a sorcery with mana value 10: no trigger goes
    on the stack above it."""
    game = _w1g4_table(set_pool)
    _w1g4_put(game, 0, set_pool("SCG")["Kurgadon"])
    decree = set_pool("SCG")["Decree of Annihilation"]
    assert decree.cmc >= 6 and "Creature" not in decree.type_line
    game.players[0].hand.append(decree)
    assert game.queue_from_hand(0, "Decree of Annihilation").supported
    assert [item.card.name for item in game.stack] == ["Decree of Annihilation"], game.log


def test_w1g4_kurgadon_trigger_resolves_before_the_spell(set_pool):
    """The trigger goes on the stack above the spell that fired it (CR 603.3):
    the counters arrive while the Dragon is still a spell."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [lea["Shivan Dragon"]])
    kurgadon = _w1g4_put(game, 0, set_pool("SCG")["Kurgadon"])
    assert game.queue_from_hand(0, "Shivan Dragon").supported
    assert len(game.stack) == 2
    game.resolve_top_of_stack()
    assert _w1g4_pt(kurgadon) == (6, 6)
    assert [item.card.name for item in game.stack] == ["Shivan Dragon"]


# --- the drive list ---------------------------------------------------------


def _w1g4_empath_library(set_pool):
    lea = set_pool("LEA")
    return [lea["Grizzly Bears"], lea["Sengir Vampire"], lea["Shivan Dragon"],
            lea["Island"], lea["Craw Wurm"]]


def test_w1g4_fierce_empath_finds_a_six_drop_creature(set_pool):
    """A seat nobody asks takes the search; what it finds is a creature card
    with mana value 6 or greater — never the five-drop."""
    game = _w1g4_table(
        set_pool, [set_pool("SCG")["Fierce Empath"]],
        library=_w1g4_empath_library(set_pool),
    )
    assert game.queue_from_hand(0, "Fierce Empath").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    found = [card.name for card in game.players[0].hand]
    assert len(found) == 1 and found[0] in ("Shivan Dragon", "Craw Wurm"), game.log
    assert len(game.players[0].library) == 4


def test_w1g4_fierce_empath_offers_a_person_only_the_six_drops(set_pool):
    game = _w1g4_table(
        set_pool, [set_pool("SCG")["Fierce Empath"]],
        library=_w1g4_empath_library(set_pool), interactive=True,
    )
    assert game.queue_from_hand(0, "Fierce Empath").supported
    _w1g4_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0) or game.pending_choice_of("may", 0)
    if offer is not None:
        assert game.resolve_pending_choice(offer.kind, 0, accept=True)
    search = game.pending_choice_of("search_library", 0)
    assert search is not None, [choice.kind for choice in game.pending_choices]
    names = [card.name for card in game.players[0].library]
    # A Sengir Vampire is not a legal pick.
    assert not game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Sengir Vampire"),
    )
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Craw Wurm"),
    )
    _w1g4_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Craw Wurm"], game.log


def test_w1g4_vengeful_dead_drains_for_itself_and_another_zombie(set_pool, catalog_by_name):
    """"Whenever this creature or another Zombie dies, each opponent loses 1
    life." A non-Zombie dying is nothing."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool)
    dead = _w1g4_put(game, 0, set_pool("SCG")["Vengeful Dead"])
    zombie = _w1g4_put(game, 1, catalog_by_name["Scathe Zombies"])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    lives = []
    for permanent in (bears, zombie, dead):
        permanent.damage_marked = 99
        game.check_state_based_actions()
        _w1g4_resolve_stack(game)
        assert not game.is_on_battlefield(permanent)
        lives.append(game.players[1].life)
    assert lives == [20, 19, 18], game.log
    assert game.players[0].life == 20


def test_w1g4_consumptive_goo_shrinks_a_creature_and_grows_itself(set_pool):
    """The 2004-10-04 ruling: aimed at itself it gets both -1/-1 and the
    counter during the resolution, and survives it."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool)
    goo = _w1g4_put(game, 0, set_pool("SCG")["Consumptive Goo"])
    bears = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Consumptive Goo", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_pt(bears) == (1, 1) and _w1g4_pt(goo) == (2, 2), game.log
    assert game.activate_permanent_ability(
        0, "Consumptive Goo", target_permanent_ids=[goo.permanent_id],
    ).supported
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(goo) and _w1g4_pt(goo) == (2, 2), game.log

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

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
