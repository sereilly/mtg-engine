"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# The Nightmares: an entry exile linked to leaving (CR 607.2a, 610.3). Each
# card is cast through the real path and its leaving half driven by Swords to
# Plowshares; each is also killed with its entry trigger on the stack, where
# the leave trigger resolves first and returns nothing and the entry trigger
# then exiles for good (the Worldgorger Dragon / Wormfang Drake rulings,
# 2022-12-08).

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.linked_exile import linked_entries as _w1g4_linked_entries
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(set_pool, name):
    for code in ("JUD", "LEA", "ODY", "TOR", "ICE"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_game(set_pool, *, hand=(), opp_hand=(), interactive=()):
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    p0 = _W1G4PlayerState(
        name="P0", hand=[card(n) for n in hand], library=[card("Island")] * 5,
    )
    p1 = _W1G4PlayerState(
        name="P1", hand=[card(n) for n in opp_hand], library=[card("Forest")] * 5,
    )
    game = _W1G4Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_put(game, set_pool, seat, name):
    permanent = _W1G4Permanent(card=_w1g4_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g4_resolve_stack(game)
    return permanent


def _w1g4_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g4_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def _w1g4_drain(game):
    for _ in range(6):
        _w1g4_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g4_swords(game, set_pool, victim):
    """Exile *victim* with Swords to Plowshares, dealt into seat 0's hand here
    so a test's hand is only the cards it is about."""
    game.players[0].hand.append(set_pool("LEA")["Swords to Plowshares"])
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g4_drain(game)


# --- Wormfang Newt / Turtle: "exile a land you control" --------------------


@_w1g4_pytest.mark.parametrize("name", ["Wormfang Newt", "Wormfang Turtle"])
def test_w1g4_a_land_nightmare_exiles_a_land_and_gives_it_back_untapped(set_pool, name):
    game = _w1g4_game(set_pool, hand=[name])
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    plains.tapped = True
    game.cast_from_hand(0, name)
    _w1g4_drain(game)

    # One of *its controller's* lands, chosen as the trigger resolved: the
    # opponent's Forest is never a candidate.
    p0 = game.players[0]
    assert [c.name for c in p0.exile] == ["Plains"], game.log[-6:]
    assert _w1g4_names(game, 0) == sorted(["Island", name])
    assert _w1g4_names(game, 1) == ["Forest"]
    nightmare = _w1g4_named(game, 0, name)
    assert [e["card"].name for e in _w1g4_linked_entries(nightmare)] == ["Plains"]

    _w1g4_swords(game, set_pool, nightmare)

    # "Return the exiled card to the battlefield under its owner's control" —
    # a new object (CR 400.7): untapped, and not the permanent that left.
    returned = _w1g4_named(game, 0, "Plains")
    assert returned is not plains and not returned.tapped
    assert [c.name for c in p0.exile] == [name]


def test_w1g4_wormfang_newt_asks_its_controller_which_land(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"], interactive=(0,))
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    island = _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()  # the creature spell
    game.resolve_top_of_stack()  # its entry trigger, which stops to ask

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    assert choice.player_index == 0
    # Only lands its controller controls: not the Newt, not the Forest.
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Plains", "Island",
    }
    assert game.confirm_permanent_choice(0, island.permanent_id)
    _w1g4_drain(game)

    assert [c.name for c in game.players[0].exile] == ["Island"]
    assert game.is_on_battlefield(plains)


def test_w1g4_wormfang_newt_with_no_land_exiles_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(0, "Wormfang Newt")
    _w1g4_drain(game)

    assert game.players[0].exile == [] and game.players[1].exile == []
    assert _w1g4_names(game, 1) == ["Forest"]
    assert "Wormfang Newt: there is no permanent it could choose" in game.log


def test_w1g4_wormfang_newt_killed_in_response_exiles_its_land_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 0, "Plains")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()
    newt = _w1g4_named(game, 0, "Wormfang Newt")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g4_swords(game, set_pool, newt)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled the Plains, and nothing is left that will return it.
    assert sorted(c.name for c in game.players[0].exile) == ["Plains", "Wormfang Newt"]
    assert _w1g4_names(game, 0) == []


# --- Wormfang Drake: "sacrifice it unless you exile a creature you control
# other than this creature" -------------------------------------------------


def test_w1g4_wormfang_drake_exiles_a_creature_and_returns_it_when_it_leaves(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.cast_from_hand(0, "Wormfang Drake")
    _w1g4_drain(game)

    # A seat nobody asks pays the toll: the Bears go, the Drake stays.
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"], game.log[-6:]
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert [e["card"].name for e in _w1g4_linked_entries(drake)] == ["Grizzly Bears"]

    _w1g4_swords(game, set_pool, drake)

    returned = _w1g4_named(game, 0, "Grizzly Bears")
    assert returned is not bears
    assert [c.name for c in game.players[0].exile] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_alone_is_sacrificed_without_an_offer(set_pool):
    # "If you don't control any other creatures as the enters-the-battlefield
    # ability resolves, you must sacrifice Wormfang Drake." (2022-12-08.) An
    # interactive seat, so an offer — had one been made — would be left owed.
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    _w1g4_put(game, set_pool, 1, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()

    assert not game.pending_choices
    assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]
    # The opponent's creature was never a price the Drake's controller pays.
    assert _w1g4_names(game, 1) == ["Grizzly Bears"]


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_wormfang_drake_offers_its_controller_the_price(set_pool, accept):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    assert game.waiting_prompt().kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=accept)
    if accept:
        # Which creature is the next question, and only the Bears answer it:
        # "other than this creature".
        choice = game.waiting_prompt()
        assert choice.kind == "permanent_choice"
        assert [p.card.name for p in game.live_permanent_choices(choice)] == [
            "Grizzly Bears",
        ]
        assert game.confirm_permanent_choice(0, bears.permanent_id)
    _w1g4_drain(game)

    if accept:
        assert _w1g4_names(game, 0) == ["Wormfang Drake"]
        assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    else:
        assert _w1g4_names(game, 0) == ["Grizzly Bears"]
        assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_killed_in_response_exiles_the_price_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert game.stack

    _w1g4_swords(game, set_pool, drake)

    # "If you exile a creature you control, it will be exiled indefinitely.
    # Wormfang Drake won't return it." (2022-12-08.)
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Wormfang Drake",
    ]
    assert _w1g4_names(game, 0) == []


# --- Wormfang Crab: "an opponent chooses a permanent you control other than
# this creature and exiles it" ----------------------------------------------


def test_w1g4_wormfang_crab_s_opponent_picks_from_the_crab_controller_s_board(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Crab"], interactive=(1,))
    _w1g4_put(game, set_pool, 0, "Plains")
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    _w1g4_put(game, set_pool, 1, "Forest")
    game.queue_from_hand(0, "Wormfang Crab")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    # The *opponent* is asked, about the Crab controller's permanents other
    # than the Crab — never their own Forest.
    assert choice.player_index == 1
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Plains", "Grizzly Bears",
    }
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g4_drain(game)

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    crab = _w1g4_named(game, 0, "Wormfang Crab")
    assert [e["card"].name for e in _w1g4_linked_entries(crab)] == ["Grizzly Bears"]

    _w1g4_swords(game, set_pool, crab)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Plains"]
    assert [c.name for c in game.players[0].exile] == ["Wormfang Crab"]


def test_w1g4_wormfang_crab_alone_exiles_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Crab"])
    _w1g4_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(0, "Wormfang Crab")
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Wormfang Crab"]
    assert _w1g4_names(game, 1) == ["Forest"]
    assert game.players[0].exile == [] and game.players[1].exile == []


# --- Worldgorger Dragon: "exile all other permanents you control" ----------


def _w1g4_gorger_board(set_pool, *, opp_creatures=(), interactive=()):
    from engine.aura_attachment import attach_aura

    game = _w1g4_game(set_pool, hand=["Worldgorger Dragon"], interactive=interactive)
    _w1g4_put(game, set_pool, 0, "Plains")
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    aura = _w1g4_put(game, set_pool, 0, "Holy Strength")
    attach_aura(aura, bears)
    for name in opp_creatures:
        _w1g4_put(game, set_pool, 1, name)
    _w1g4_put(game, set_pool, 1, "Forest")
    return game


def _w1g4_aura_host(game, name):
    aura = next(p for p in game.all_permanents() if p.card.name == name)
    host = aura.metadata.get("attached_to")
    return None if host is None else host.card.name


def test_w1g4_worldgorger_dragon_exiles_only_its_controller_s_other_permanents(set_pool):
    game = _w1g4_gorger_board(set_pool, opp_creatures=["Hill Giant"])
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Worldgorger Dragon"]
    assert _w1g4_names(game, 1) == ["Forest", "Hill Giant"]
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    assert sorted(e["card"].name for e in _w1g4_linked_entries(dragon)) == [
        "Grizzly Bears", "Holy Strength", "Plains",
    ]

    _w1g4_swords(game, set_pool, dragon)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Holy Strength", "Plains"]
    # The Aura may not enchant the Bears, which enter at the same time; the
    # Hill Giant was already there and is the one legal host — an opponent's
    # permanent, which the ruling allows (2022-12-08).
    assert _w1g4_aura_host(game, "Holy Strength") == "Hill Giant"
    assert game.players[0].exile == [game.players[0].exile[0]]
    assert game.players[0].exile[0].name == "Worldgorger Dragon"


def test_w1g4_worldgorger_dragon_leaves_an_aura_with_no_host_in_exile(set_pool):
    game = _w1g4_gorger_board(set_pool)
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Worldgorger Dragon"))

    # "If the Aura can't legally be attached to anything, it stays exiled."
    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Plains"]
    assert sorted(c.name for c in game.players[0].exile) == [
        "Holy Strength", "Worldgorger Dragon",
    ]
    # Not binned by CR 704.5m as an unattached Aura: it never entered.
    assert [c.name for c in game.players[0].graveyard] == ["Swords to Plowshares"]


def test_w1g4_worldgorger_dragon_asks_where_a_returning_aura_goes(set_pool):
    game = _w1g4_gorger_board(
        set_pool, opp_creatures=["Hill Giant", "Gray Ogre"], interactive=(0,),
    )
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    game.players[0].hand.append(set_pool("LEA")["Swords to Plowshares"])
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[dragon.permanent_id],
    )
    game.resolve_top_of_stack()  # Swords; the leave trigger goes on the stack
    game.resolve_top_of_stack()  # the leave trigger, which stops to ask

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Hill Giant", "Gray Ogre",
    }
    # Nothing has returned while the question is owed: the cards enter together.
    assert _w1g4_names(game, 0) == []
    ogre = _w1g4_named(game, 1, "Gray Ogre")
    assert game.confirm_permanent_choice(0, ogre.permanent_id)
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Holy Strength", "Plains"]
    assert _w1g4_aura_host(game, "Holy Strength") == "Gray Ogre"


def test_w1g4_worldgorger_dragon_killed_in_response_exiles_for_good(set_pool):
    game = _w1g4_gorger_board(set_pool, opp_creatures=["Hill Giant"])
    game.queue_from_hand(0, "Worldgorger Dragon")
    game.resolve_top_of_stack()
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    assert game.stack

    _w1g4_swords(game, set_pool, dragon)

    # "It won't return anything. Then the enters-the-battlefield ability will
    # exile all other permanents you control indefinitely." (2022-12-08.)
    assert _w1g4_names(game, 0) == []
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Holy Strength", "Plains", "Worldgorger Dragon",
    ]
    assert _w1g4_names(game, 1) == ["Forest", "Hill Giant"]


# --- Soulgorger Orgg: "you lose all but 1 life" / "you gain life equal to the
# life you lost when it entered" (CR 607.1) ---------------------------------


def _w1g4_terror(game, set_pool, victim):
    """Destroy *victim* with Terror (cast by seat 1, so no life of seat 0's
    moves with it)."""
    game.players[1].hand.append(set_pool("LEA")["Terror"])
    result = game.queue_from_hand(
        1, "Terror", target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g4_drain(game)


def test_w1g4_soulgorger_orgg_takes_all_but_1_life_and_gives_it_back(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1, game.log[-4:]

    # The number is the one the entry took, not a recount: life gained since
    # is kept, and the 19 comes back on top of it.
    game._gain_life(p0, 5, "test")
    assert p0.life == 6
    _w1g4_terror(game, set_pool, _w1g4_named(game, 0, "Soulgorger Orgg"))

    assert p0.life == 25
    assert [c.name for c in p0.graveyard] == ["Soulgorger Orgg"]


def test_w1g4_soulgorger_orgg_at_1_life_takes_nothing_and_returns_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    p0.life = 1
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1

    _w1g4_terror(game, set_pool, _w1g4_named(game, 0, "Soulgorger Orgg"))
    assert p0.life == 1


def test_w1g4_soulgorger_orgg_killed_in_response_keeps_the_life_lost(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    game.queue_from_hand(0, "Soulgorger Orgg")
    game.resolve_top_of_stack()
    orgg = _w1g4_named(game, 0, "Soulgorger Orgg")
    assert game.stack and p0.life == 20

    _w1g4_terror(game, set_pool, orgg)

    # The leave trigger resolved first, with nothing noted to give back; the
    # entry trigger then took all but 1, and nothing is left to return it.
    assert p0.life == 1


def test_w1g4_a_returned_soulgorger_orgg_is_a_new_object_with_no_note(set_pool):
    # CR 400.7: the Orgg that comes back remembers nothing. Two of them on one
    # battlefield each give back only what their own entry took.
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg", "Soulgorger Orgg"])
    p0 = game.players[0]
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    first = _w1g4_named(game, 0, "Soulgorger Orgg")
    game._gain_life(p0, 9, "test")  # 10
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1
    second = next(
        p for p in game.controlled_by(0)
        if p.card.name == "Soulgorger Orgg" and p is not first
    )

    _w1g4_terror(game, set_pool, second)
    assert p0.life == 10
    _w1g4_terror(game, set_pool, first)
    assert p0.life == 29


# --- Sutured Ghoul: "As this creature enters, exile any number of creature
# cards from your graveyard. / …power is equal to the total power of the
# exiled cards …" (CR 614.1c, 604.3, 607.2b) --------------------------------


def _w1g4_ghoul_game(set_pool, graveyard, *, interactive=(), opp_graveyard=()):
    game = _w1g4_game(set_pool, hand=["Sutured Ghoul"], interactive=interactive)
    game.players[0].graveyard = [_w1g4_card(set_pool, n) for n in graveyard]
    game.players[1].graveyard = [_w1g4_card(set_pool, n) for n in opp_graveyard]
    return game


def _w1g4_pt(perm):
    return (perm.effective_power, perm.effective_toughness)


def test_w1g4_sutured_ghoul_is_the_sum_of_the_creature_cards_it_exiles(set_pool):
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Lightning Bolt", "Hill Giant"],
    )
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)

    p0 = game.players[0]
    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    # A seat nobody asks exiles every creature card, and only creature cards.
    assert sorted(c.name for c in p0.exile) == ["Grizzly Bears", "Hill Giant"]
    assert [c.name for c in p0.graveyard] == ["Lightning Bolt"]
    assert _w1g4_pt(ghoul) == (5, 5)
    assert sorted(e["card"].name for e in _w1g4_linked_entries(ghoul)) == [
        "Grizzly Bears", "Hill Giant",
    ]


def test_w1g4_sutured_ghoul_asks_which_cards_and_any_number_includes_some(set_pool):
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Hill Giant", "Lightning Bolt"], interactive=(0,),
    )
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "entry_exile"
    # The creature cards only: slot 0 and slot 1, never the Bolt.
    assert game._entry_exile_candidates(choice) == [0, 1]
    # More picks than there are candidates is refused, and the prompt stays.
    assert not game.resolve_pending_choice(
        "entry_exile", 0,
        picks=[{"index": 0, "counter": None}, {"index": 1, "counter": None},
               {"index": 2, "counter": None}],
    )
    assert game.resolve_pending_choice(
        "entry_exile", 0, picks=[{"index": 1, "counter": None}],
    )
    _w1g4_drain(game)

    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    assert [c.name for c in game.players[0].exile] == ["Hill Giant"]
    assert _w1g4_pt(ghoul) == (3, 3)


def test_w1g4_sutured_ghoul_exiling_nothing_is_a_0_0_that_dies(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Grizzly Bears"], interactive=(0,))
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("entry_exile", 0, picks=[])
    _w1g4_drain(game)
    game.check_state_based_actions()

    p0 = game.players[0]
    assert _w1g4_names(game, 0) == []
    assert sorted(c.name for c in p0.graveyard) == ["Grizzly Bears", "Sutured Ghoul"]


def test_w1g4_sutured_ghoul_with_an_empty_graveyard_asks_nothing(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Lightning Bolt"], interactive=(0,))
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()

    assert not game.pending_choices
    game.check_state_based_actions()
    assert [c.name for c in game.players[0].graveyard] == [
        "Lightning Bolt", "Sutured Ghoul",
    ]


def test_w1g4_sutured_ghoul_counts_an_exiled_cards_cda_as_it_changes(set_pool):
    # "If Dungrove Elder is exiled this way, its power and toughness while it's
    # in exile are equal to the number of Forests you control, and Sutured
    # Ghoul's power and toughness will change as [that] number … changes."
    # (2011-09-22.) Lhurgoyf in exile counts the creature cards in all
    # graveyards: one in the opponent's at first.
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Lhurgoyf"], opp_graveyard=["Hill Giant"],
    )
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)
    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    # Bears 2/2 + Lhurgoyf 1/2 (one creature card in a graveyard).
    assert _w1g4_pt(ghoul) == (3, 4)

    game.players[1].graveyard.append(_w1g4_card(set_pool, "Gray Ogre"))
    game._recompute_continuous_effects()
    assert _w1g4_pt(ghoul) == (4, 5)


def test_w1g4_sutured_ghoul_leaving_leaves_its_cards_in_exile(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Grizzly Bears", "Hill Giant"])
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)
    p0 = game.players[0]
    life_before = p0.life
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Sutured Ghoul"))

    # Nothing prints a return: the cards stay exiled beside it. Swords reads
    # the Ghoul's power as it left (5), last-known information.
    assert sorted(c.name for c in p0.exile) == [
        "Grizzly Bears", "Hill Giant", "Sutured Ghoul",
    ]
    assert p0.life == life_before + 5


# --- The drive list: supported on arrival, given a game --------------------


def _w1g4_next_actives(game, count):
    seats = []
    for _ in range(count):
        seats.append(game.start_next_turn())
        _w1g4_drain(game)
    return seats


def test_w1g4_wormfang_manta_that_stays_skips_its_controller_s_next_turn(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)

    assert _w1g4_next_actives(game, 4) == [1, 1, 0, 1]


def test_w1g4_wormfang_manta_gone_the_same_turn_skips_the_extra_turn(set_pool):
    # CR 614.10: "skip your next turn" replaces the next turn its player would
    # take, and CR 500.7 puts the extra turn directly after this one — so the
    # skip eats the extra turn and the opponent plays next. It used to take the
    # extra turn at once and skip the controller's next *normal* turn: the same
    # count of turns, one of them moved ahead of the opponent's.
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Manta"))

    assert _w1g4_next_actives(game, 4) == [1, 0, 1, 0]
    assert "P0 skips the extra turn (CR 614.10)" in game.log


def test_w1g4_wormfang_manta_gone_after_the_skip_gives_an_extra_turn(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)
    assert _w1g4_next_actives(game, 2) == [1, 1]  # P0's turn was skipped

    # During the opponent's turn: "you take an extra turn after this one".
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Manta"))
    assert _w1g4_next_actives(game, 3) == [0, 0, 1]


def test_w1g4_wormfang_behemoth_holds_its_controller_s_hand_until_it_leaves(set_pool):
    game = _w1g4_game(
        set_pool, hand=["Wormfang Behemoth", "Grizzly Bears", "Lightning Bolt"],
    )
    game.cast_from_hand(0, "Wormfang Behemoth")
    _w1g4_drain(game)
    p0 = game.players[0]
    assert p0.hand == []
    assert sorted(c.name for c in p0.exile) == ["Grizzly Bears", "Lightning Bolt"]

    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Behemoth"))

    assert sorted(c.name for c in p0.hand) == ["Grizzly Bears", "Lightning Bolt"]
    assert [c.name for c in p0.exile] == ["Wormfang Behemoth"]


def test_w1g4_anurid_brushhopper_comes_back_out_of_exile_at_the_end_step(set_pool):
    # Supported on arrival and never seen to work: the delayed return looked
    # for the card on the battlefield and in the graveyards, logged "no longer
    # in a graveyard", and left the Brushhopper in exile for good.
    game = _w1g4_game(
        set_pool, hand=["Grizzly Bears", "Lightning Bolt", "Hill Giant"],
    )
    game.start_turn(0)
    hopper = _w1g4_put(game, set_pool, 0, "Anurid Brushhopper")
    hopper.tapped = True
    hopper.damage_marked = 2
    result = game.activate_permanent_ability(0, "Anurid Brushhopper")
    assert result.supported, result.details
    _w1g4_drain(game)

    p0 = game.players[0]
    assert len(p0.hand) == 1 and len(p0.graveyard) == 2
    assert [c.name for c in p0.exile] == ["Anurid Brushhopper"]

    game.resolve_end_step(0)
    _w1g4_drain(game)

    back = _w1g4_named(game, 0, "Anurid Brushhopper")
    # A new object (CR 400.7): untapped, no damage, a fresh id.
    assert back is not hopper and not back.tapped and back.damage_marked == 0
    assert p0.exile == []


def test_w1g4_anurid_brushhopper_needs_two_cards_to_discard(set_pool):
    game = _w1g4_game(set_pool, hand=["Grizzly Bears"])
    game.start_turn(0)
    _w1g4_put(game, set_pool, 0, "Anurid Brushhopper")
    result = game.activate_permanent_ability(0, "Anurid Brushhopper")

    assert not result.supported
    assert _w1g4_names(game, 0) == ["Anurid Brushhopper"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
