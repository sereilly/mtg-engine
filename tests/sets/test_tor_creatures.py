"""Torment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

import pytest as _w1g4_pytest

from engine import Game as _W1g4Game, PlayerState as _W1g4PlayerState
from engine.models import Permanent as _W1g4Permanent
from tests.helpers import (_mk_creature_card as _w1g4_creature,
                           resolve_stack as _w1g4_resolve_stack)


def _w1g4_table(set_pool, *, hand=(), interactive=()):
    """Two seats with Swamps to draw, costs unenforced; *interactive* names
    the seats that are asked rather than defaulted."""
    swamp = set_pool("LEA")["Swamp"]
    game = _W1g4Game(players=[
        _W1g4PlayerState("P1", library=[swamp] * 10, hand=list(hand)),
        _W1g4PlayerState("P2", library=[swamp] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1g4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g4_settle(game):
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()


def _w1g4_owed(game):
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_to_declare_attackers(game):
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            return
    raise AssertionError(f"never reached declare attackers ({game.current_step})")


def _w1g4_four_cards(set_pool):
    lea = set_pool("LEA")
    return [lea["Giant Growth"], lea["Lightning Bolt"], lea["Shivan Dragon"], lea["Swamp"]]


# --- Anurid Scavenger / Gurzigost: a toll paid out of the graveyard ----------

@_w1g4_pytest.mark.parametrize("name, owed", [("Anurid Scavenger", 1), ("Gurzigost", 2)])
def test_w1g4_graveyard_toll_is_paid_by_bottoming_the_printed_count(set_pool, name, owed):
    """"At the beginning of your upkeep, sacrifice this creature unless you put
    a card / two cards from your graveyard on the bottom of your library."

    A seat nobody asks pays the toll (the stated policy for an "unless"), so
    the printed number of cards leaves the graveyard for the library's bottom
    and the creature stays."""
    game = _w1g4_table(set_pool)
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:3]
    me.graveyard = list(pile)
    creature = _w1g4_put(game, 0, set_pool("TOR")[name])

    game.resolve_upkeep(0)
    _w1g4_settle(game)

    assert game.is_on_battlefield(creature)
    assert _w1g4_names(me.graveyard) == _w1g4_names(pile[owed:])
    assert _w1g4_names(me.library[-owed:]) == _w1g4_names(pile[:owed])
    assert len(me.library) == 10 + owed


@_w1g4_pytest.mark.parametrize("name, held", [("Anurid Scavenger", 0), ("Gurzigost", 1)])
def test_w1g4_graveyard_toll_a_pile_short_of_the_count_sacrifices(set_pool, name, held):
    """A graveyard holding fewer cards than the toll prints cannot pay it, so
    the offer is not made and the creature is sacrificed — Gurzigost with one
    card behind it goes, and that card stays where it is."""
    game = _w1g4_table(set_pool)
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:held]
    me.graveyard = list(pile)
    creature = _w1g4_put(game, 0, set_pool("TOR")[name])

    game.resolve_upkeep(0)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(creature)
    assert _w1g4_names(me.graveyard) == _w1g4_names(pile) + [name]
    assert len(me.library) == 10


def test_w1g4_gurzigost_toll_asks_a_person_which_cards_and_their_order(set_pool):
    """An interactive seat is asked whether to pay, then which two cards
    (the graveyard pick, saying where the cards go), then — CR 401.4 — the
    order of the two now on the bottom of the library."""
    game = _w1g4_table(set_pool, interactive=(0,))
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:3]
    me.graveyard = list(pile)
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])

    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()
    assert _w1g4_owed(game) == [("optional_pay", 0)]
    assert game.confirm_optional_pay(0, accept=True)

    (pick,) = game.pending_choices
    assert (pick.kind, pick.data["count"], pick.data["destination"]) == (
        "graveyard_exile_pick", 2, "library_bottom",
    )
    assert game.live_graveyard_exile_candidates(pick) == [0, 1, 2]
    assert not game.confirm_graveyard_exile_pick(0, [0])  # one is not two
    assert game.confirm_graveyard_exile_pick(0, [2, 0])

    assert _w1g4_names(me.graveyard) == ["Lightning Bolt"]
    assert _w1g4_names(me.library[-2:]) == ["Shivan Dragon", "Giant Growth"]
    assert _w1g4_owed(game) == [("reorder_library", 0)]
    assert game.pending_choices[0].data["position"] == "bottom"
    assert game.is_on_battlefield(gurzigost)


def test_w1g4_gurzigost_toll_declined_by_a_person_sacrifices(set_pool):
    game = _w1g4_table(set_pool, interactive=(0,))
    me = game.players[0]
    me.graveyard = _w1g4_four_cards(set_pool)[:3]
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])

    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=False)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(gurzigost)
    assert len(me.graveyard) == 4 and len(me.library) == 10


# --- Gurzigost: its own assignment, chosen as the ability resolves ----------

def _w1g4_gurzigost_into_a_wall(set_pool, *, interactive=(), accept=True, activate=True):
    """Gurzigost (6/8) attacking into a 0/10 wall, its ability activated in
    the declare-attackers step first unless told otherwise."""
    game = _w1g4_table(
        set_pool, hand=[set_pool("LEA")["Giant Growth"]], interactive=interactive,
    )
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])
    wall = _w1g4_put(game, 1, _w1g4_creature("W1G4 Wall", 0, 10))
    _w1g4_to_declare_attackers(game)
    if activate:
        game.activate_permanent_ability(0, "Gurzigost")
        if interactive:
            assert _w1g4_owed(game) == [("optional_pay", 0)]
            assert game.confirm_optional_pay(0, accept=accept)
        _w1g4_settle(game)
        assert _w1g4_names(game.players[0].graveyard) == ["Giant Growth"]  # the discard
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok, why
    game.advance_combat_phase()
    assert game.combat_damage_resolved
    return game, gurzigost, wall


@_w1g4_pytest.mark.parametrize("interactive", [(), (0,)])
def test_w1g4_gurzigost_activated_assigns_its_damage_past_the_blocker(set_pool, interactive):
    """"{G}{G}, Discard a card: You may have this creature assign its combat
    damage this turn as though it weren't blocked." Answered yes as the
    ability resolves — "You decide how it will assign its damage at the time
    the ability resolves." (ruling, 2008-04-01) — so the damage step asks
    nothing more and the 6 goes to the player."""
    game, _gurzigost, wall = _w1g4_gurzigost_into_a_wall(set_pool, interactive=interactive)

    assert game.players[1].life == 14
    assert wall.damage_marked == 0
    assert any("as though it weren't blocked" in line for line in game.log)


def test_w1g4_gurzigost_declined_or_unactivated_hits_its_blocker(set_pool):
    game, gurzigost, wall = _w1g4_gurzigost_into_a_wall(
        set_pool, interactive=(0,), accept=False,
    )
    assert game.players[1].life == 20 and wall.damage_marked == 6

    game, gurzigost, wall = _w1g4_gurzigost_into_a_wall(set_pool, activate=False)
    assert game.players[1].life == 20 and wall.damage_marked == 6


# --- Ichorid: back from the graveyard for another black creature card -------

def _w1g4_ichorid_two_turns(set_pool, graveyard, *, interactive=(), accept=True, pick=0):
    """Ichorid cast with haste, sacrificed at the end step, and its upkeep
    trigger answered at the next upkeep."""
    tor = set_pool("TOR")
    game = _w1g4_table(set_pool, hand=[tor["Ichorid"]], interactive=interactive)
    me = game.players[0]
    me.graveyard = list(graveyard)
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Ichorid").details == "resolved"
    _w1g4_settle(game)
    (ichorid,) = [p for p in game.controlled_by(0) if p.card.name == "Ichorid"]
    assert game.can_attack(ichorid, 1)  # haste

    game.current_step = "end"
    game.resolve_end_step(0)
    _w1g4_settle(game)
    assert not game.is_on_battlefield(ichorid)
    assert me.graveyard[-1].name == "Ichorid"

    if interactive:
        game.resolve_upkeep(0, defer_priority=True)
        game.resolve_top_of_stack()
        if game.pending_choices:
            assert game.confirm_optional_pay(0, accept=accept)
            chosen = next(
                (c for c in game.pending_choices if c.kind == "graveyard_exile_pick"),
                None,
            )
            if chosen is not None:
                live = game.live_graveyard_exile_candidates(chosen)
                assert game.confirm_graveyard_exile_pick(0, [live[pick]])
        _w1g4_settle(game)
    else:
        game.resolve_upkeep(0)
        _w1g4_settle(game)
    return game, me


def test_w1g4_ichorid_returns_by_exiling_another_black_creature_card(set_pool):
    zombies = set_pool("LEA")["Scathe Zombies"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [zombies])

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Scathe Zombies"]
    assert me.graveyard == []


@_w1g4_pytest.mark.parametrize("graveyard", [[], ["Grizzly Bears"], ["Dark Ritual"]])
def test_w1g4_ichorid_stays_without_another_black_creature_card(set_pool, graveyard):
    """Nothing black, nothing a creature, or nothing at all: the only black
    creature card in the pile is Ichorid itself, which "other than this card"
    leaves out — so no offer, and no return."""
    lea = set_pool("LEA")
    game, me = _w1g4_ichorid_two_turns(set_pool, [lea[name] for name in graveyard])

    assert list(game.controlled_by(0)) == []
    assert me.exile == []
    assert _w1g4_names(me.graveyard) == graveyard + ["Ichorid"]


def test_w1g4_ichorid_may_exile_another_ichorid_which_then_cannot_return(set_pool):
    """"If one Ichorid's ability exiles another, the exiled Ichorid's ability
    can't return it to the battlefield." (ruling, 2016-06-08.) Two Ichorids
    in the pile trigger twice; the first exiles the other copy — a second
    copy of the card is not "this card" — and returns, and the second finds
    its card gone."""
    ichorid = set_pool("TOR")["Ichorid"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [ichorid])

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Ichorid"]
    assert me.graveyard == []


def test_w1g4_ichorid_asks_a_person_and_offers_only_black_creatures(set_pool):
    lea = set_pool("LEA")
    pile = [lea["Scathe Zombies"], lea["Grizzly Bears"], lea["Black Knight"]]
    game, me = _w1g4_ichorid_two_turns(set_pool, pile, interactive=(0,), pick=1)

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Black Knight"]
    assert _w1g4_names(me.graveyard) == ["Scathe Zombies", "Grizzly Bears"]


def test_w1g4_ichorid_declined_by_a_person_stays_in_the_graveyard(set_pool):
    zombies = set_pool("LEA")["Scathe Zombies"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [zombies], interactive=(0,), accept=False)

    assert list(game.controlled_by(0)) == []
    assert _w1g4_names(me.graveyard) == ["Scathe Zombies", "Ichorid"]


# --- Carrion Rats / Carrion Wurm: any player may exile from their own pile --

def _w1g4_carrion_attack(set_pool, name, *, mine=(), theirs=(), interactive=(), answers=()):
    """*name* attacking an empty board; each seat's graveyard as given;
    *answers* is ``(seat, accept)`` in the order the prompts are answered."""
    game = _w1g4_table(set_pool, interactive=interactive)
    game.players[0].graveyard = list(mine)
    game.players[1].graveyard = list(theirs)
    attacker = _w1g4_put(game, 0, set_pool("TOR")[name])
    _w1g4_to_declare_attackers(game)
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    if interactive:
        game.resolve_top_of_stack()
        for seat, accept in answers:
            assert game.confirm_optional_pay(seat, accept=accept)
            chosen = next(
                (c for c in game.pending_choices if c.kind == "graveyard_exile_pick"),
                None,
            )
            if chosen is not None:
                assert chosen.player_index == seat
                live = game.live_graveyard_exile_candidates(chosen)
                assert game.confirm_graveyard_exile_pick(seat, live[: chosen.data["count"]])
    _w1g4_settle(game)
    for _ in range(4):
        if game.current_step in ("end_of_combat", "postcombat_main"):
            break
        game.advance_combat_phase()
    assert game.current_step in ("end_of_combat", "postcombat_main")
    assert any("Resolved combat damage" in line for line in game.log)
    return game, attacker


def test_w1g4_carrion_rats_an_opponent_exiles_from_their_graveyard(set_pool):
    """The defending player takes the offer out of *their own* pile, and the
    Rats assign no combat damage. Their controller, asked first, declines: an
    offer whose purchase is its own creature's drawback."""
    pile = _w1g4_four_cards(set_pool)
    game, _rats = _w1g4_carrion_attack(set_pool, "Carrion Rats", mine=pile, theirs=pile)

    assert game.players[1].life == 20
    assert _w1g4_names(game.players[1].exile) == ["Giant Growth"]
    assert game.players[0].exile == []
    assert any("declined Carrion Rats" in line for line in game.log)


def test_w1g4_carrion_rats_every_player_is_asked_in_turn(set_pool):
    """Both seats are put the offer, active player first (the Argothian Wurm
    ruling, 2007-02-01, for the same printed shape), and each takes it out of
    their own graveyard."""
    pile = _w1g4_four_cards(set_pool)
    game, _rats = _w1g4_carrion_attack(
        set_pool, "Carrion Rats", mine=pile, theirs=pile,
        interactive=(0, 1), answers=[(0, False), (1, True)],
    )

    assert game.players[1].life == 20
    assert game.players[0].exile == []
    assert len(game.players[1].exile) == 1


def test_w1g4_carrion_rats_with_no_graveyard_cards_deals_its_damage(set_pool):
    game, _rats = _w1g4_carrion_attack(set_pool, "Carrion Rats", interactive=(0, 1))

    assert game.pending_choices == []
    assert game.players[1].life == 18


def test_w1g4_carrion_wurm_owes_three_cards(set_pool):
    """"…exile three cards from their graveyard": a pile of two cannot take
    the offer, and a pile of four gives up exactly three."""
    pile = _w1g4_four_cards(set_pool)
    game, _wurm = _w1g4_carrion_attack(
        set_pool, "Carrion Wurm", theirs=pile[:2], interactive=(1,),
    )
    assert game.players[1].life == 14
    assert len(game.players[1].graveyard) == 2

    game, _wurm = _w1g4_carrion_attack(
        set_pool, "Carrion Wurm", theirs=pile, interactive=(1,), answers=[(1, True)],
    )
    assert game.players[1].life == 20
    assert len(game.players[1].exile) == 3 and len(game.players[1].graveyard) == 1


# --- Longhorn Firebeast: any opponent may take 5 to kill it -----------------

def _w1g4_firebeast(set_pool, *, interactive=(), accept=None):
    game = _w1g4_table(
        set_pool, hand=[set_pool("TOR")["Longhorn Firebeast"]], interactive=interactive,
    )
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Longhorn Firebeast").details == "resolved"
    if accept is not None:
        while game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
        assert _w1g4_owed(game) == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)
    _w1g4_settle(game)
    return game


def test_w1g4_longhorn_firebeast_an_opponent_takes_five_to_sacrifice_it(set_pool):
    game = _w1g4_firebeast(set_pool, interactive=(1,), accept=True)

    assert game.players[1].life == 15
    assert list(game.controlled_by(0)) == []
    assert _w1g4_names(game.players[0].graveyard) == ["Longhorn Firebeast"]


def test_w1g4_longhorn_firebeast_declined_stays(set_pool):
    for game in (
        _w1g4_firebeast(set_pool, interactive=(1,), accept=False),
        # A seat nobody asks does not pay 5 life's worth of damage for a 3/2.
        _w1g4_firebeast(set_pool),
    ):
        assert game.players[1].life == 20
        assert [p.card.name for p in game.controlled_by(0)] == ["Longhorn Firebeast"]

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
