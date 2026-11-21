"""Betrayers of Kamigawa creatures (legendary ones too).

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


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# The five Patrons (offering, CR 702.48, and each one's second line) and
# Kentaro, the Smiling Cat's granted alternative cost.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.cast_timing import casts_at_instant_speed as _w1g2_instant_speed
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle

_W1G2_FOX_OFFERING = "sacrifice a fox"


def _w1g2_table(set_pool, *, hands=((), ()), mana=False, interactive=()):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, tapped=False):
    permanent = _W1G2Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_names(cards):
    return sorted(card.name for card in cards)


def _w1g2_board(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def test_w1g2_patron_of_the_kitsune_offering_reduces_by_the_foxs_mana_cost(set_pool):
    """Three white mana floating: the Patron's {4}{W}{W} is out of reach, and
    offering Kitsune Blademaster ({2}{W}) takes {2}{W} off it (CR 702.48c:
    generic off generic, white off white) — exactly the three. The Fox is
    sacrificed as the cost is paid (CR 702.48b)."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([bok["Patron of the Kitsune"]], ()), mana=True)
    fox = _w1g2_put(game, chk["Kitsune Blademaster"], 0)
    game.players[0].mana_pool.update({"W": 3})
    refused = game.cast_from_hand(0, "Patron of the Kitsune")
    assert not refused.supported and "insufficient mana" in refused.details
    assert game.is_on_battlefield(fox)
    result = game.cast_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Patron of the Kitsune"]
    assert _w1g2_names(game.players[0].graveyard) == ["Kitsune Blademaster"]
    assert not any(game.players[0].mana_pool.values())
    assert "Patron of the Kitsune costs {2}{W} less to cast (offering Kitsune Blademaster)" in game.log


def test_w1g2_offering_sacrifices_the_fox_the_caster_names(set_pool):
    """Two Foxes; the caster names the cheaper one, so the reduction is {W}
    (Kitsune Diviner) and the Blademaster stays — the permanent the reduction
    is sized by is the permanent sacrificed (CR 702.48b)."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([bok["Patron of the Kitsune"]], ()), mana=True)
    blademaster = _w1g2_put(game, chk["Kitsune Blademaster"], 0)
    diviner = _w1g2_put(game, chk["Kitsune Diviner"], 0)
    game.players[0].mana_pool.update({"W": 5})
    result = game.cast_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
        cost_permanent_ids=[diviner.permanent_id],
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert game.is_on_battlefield(blademaster)
    assert _w1g2_names(game.players[0].graveyard) == ["Kitsune Diviner"]
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_offering_opens_the_instant_window_only_when_paid(set_pool):
    """Bob's Lightning Bolt is on the stack. With a Fox on Alice's side the
    Patron may *begin* to be cast (CR 601.3c), but a cast that declines the
    offering is refused with nothing spent; one that pays it goes on the
    stack above the Bolt and resolves first. With no Fox there is no window."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [bok["Patron of the Kitsune"]], [lea["Lightning Bolt"]],
    ))
    patron = game.players[0].hand[0]
    assert not _w1g2_instant_speed(patron, game, 0)
    fox = _w1g2_put(game, chk["Eight-and-a-Half-Tails"], 0)
    assert _w1g2_instant_speed(patron, game, 0)
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    refused = game.queue_from_hand(0, "Patron of the Kitsune")
    assert not refused.supported and "702.48a" in refused.details
    assert game.is_on_battlefield(fox) and len(game.stack) == 1
    result = game.queue_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
    )
    assert result.supported, result
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Patron of the Kitsune"]
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Patron of the Kitsune"]
    assert game.players[0].life == 17


def test_w1g2_patron_of_the_akki_attack_pumps_every_creature_you_control(set_pool):
    """"Whenever Patron of the Akki attacks, creatures you control get +2/+0
    until end of turn" — the Patron and the Bears it attacks beside; the
    opponent's creature is untouched."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from tests.helpers import declare_attack as _w1g2_declare_attack

    game = _w1g2_table(set_pool)
    patron = _w1g2_put(game, bok["Patron of the Akki"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_declare_attack(game, 0)
    _w1g2_settle(game)
    assert (patron.effective_power, bears.effective_power) == (7, 4)
    assert theirs.effective_power == 3


def test_w1g2_patron_of_the_kitsune_gains_a_life_for_each_attacker_either_side(set_pool):
    """Ruling 2005-02-01: "You may gain life when any creatures are declared
    as attackers, not just for attacking creatures you control" — Bob's two
    attackers give Alice 2 life, answered by default."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from tests.helpers import declare_attack as _w1g2_declare_attack

    game = _w1g2_table(set_pool)
    _w1g2_put(game, bok["Patron of the Kitsune"], 0)
    _w1g2_put(game, lea["Grizzly Bears"], 1)
    _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_declare_attack(game, 1)
    _w1g2_settle(game)
    assert game.players[0].life == 22


def test_w1g2_patron_of_the_moon_puts_up_to_two_lands_tapped(set_pool):
    """"{1}: Put up to two land cards from your hand onto the battlefield
    tapped." A person picks one of the three lands (the instant is never
    offered) and it enters tapped; a seat nobody sits in puts two."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    hand = [lea["Forest"], lea["Island"], lea["Swamp"], lea["Giant Growth"]]
    game = _w1g2_table(set_pool, hands=(hand, ()), interactive=(0,))
    patron = _w1g2_put(game, bok["Patron of the Moon"], 0)
    assert game.activate_permanent_ability(
        0, "Patron of the Moon", permanent_index=game.battlefield_index_of(patron),
    ).supported
    owed = _w1g2_settle(game, defaults=False)
    assert owed is not None and owed.kind == "choose_cards_in_hand"
    offered = sorted(game.players[0].hand[i].name for i in game.live_choose_cards_in_hand(owed))
    assert offered == ["Forest", "Island", "Swamp"]
    island = next(i for i, c in enumerate(game.players[0].hand) if c.name == "Island")
    assert game.confirm_choose_cards_in_hand(0, [island])
    _w1g2_settle(game)
    (entered,) = [perm for perm in game.controlled_by(0) if perm.card.name == "Island"]
    assert entered.tapped
    assert _w1g2_names(game.players[0].hand) == ["Forest", "Giant Growth", "Swamp"]

    game = _w1g2_table(set_pool, hands=(hand, ()))
    patron = _w1g2_put(game, bok["Patron of the Moon"], 0)
    assert game.activate_permanent_ability(
        0, "Patron of the Moon", permanent_index=game.battlefield_index_of(patron),
    ).supported
    _w1g2_settle(game)
    lands = [perm for perm in game.controlled_by(0) if perm.has_type("land")]
    assert len(lands) == 2 and all(perm.tapped for perm in lands)
    assert len(game.players[0].hand) == 2


def test_w1g2_patron_of_the_nezumi_drains_the_owner_of_each_permanent(set_pool):
    """Wrath of God takes the Patron, Alice's Bears and Bob's two creatures:
    Bob loses 2 (ruling 2005-02-01: it triggers even dying beside the
    others), Alice nothing. Then Alice's stolen Grizzly Bears goes to Bob's
    graveyard and Bob — "that player", its owner — loses 1, not the thief."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=([lea["Wrath of God"]], ()))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    _w1g2_put(game, lea["Grizzly Bears"], 0)
    _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_put(game, lea["Grizzly Bears"], 1)
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g2_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 18)

    game = _w1g2_table(set_pool, hands=([lea["Control Magic"], lea["Terror"]], ()))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    stolen = _w1g2_put(game, lea["Grizzly Bears"], 1)
    assert game.cast_from_hand(
        0, "Control Magic", target_permanent_ids=[stolen.permanent_id],
    ).supported
    _w1g2_settle(game)
    assert game.controller_index_of(stolen) == 0
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[stolen.permanent_id]).supported
    _w1g2_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 19)


def test_w1g2_patron_of_the_nezumi_counts_a_token_and_not_a_discarded_card(set_pool):
    """A token Bob sacrifices is put into his graveyard before it ceases to
    exist (CR 111.7), so it is a permanent put there; two cards Mind Twist
    makes him discard never were permanents."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from engine.tokens import make_token_card as _w1g2_token_card

    game = _w1g2_table(set_pool, hands=(
        [lea["Mind Twist"]], [lea["Giant Growth"], lea["Lightning Bolt"]],
    ))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    token = _w1g2_put(game, _w1g2_token_card(
        "Spirit", 1, 1, "Token Creature — Spirit",
    ), 1)
    game.sacrifice_permanent(token)
    _w1g2_settle(game)
    assert game.players[1].life == 19, game.log[-6:]
    assert game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=2).supported
    _w1g2_settle(game)
    assert game.players[1].hand == [] and len(game.players[1].graveyard) == 2
    assert game.players[1].life == 19


def test_w1g2_patron_of_the_orochi_untaps_forests_and_green_creatures_once(set_pool):
    """"{T}: Untap all Forests and all green creatures. Activate only once
    each turn." Both sides' Forests and green creatures untap, a tapped
    Mountain and a tapped red creature stay tapped, and a second activation
    the same turn is refused."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    patron = _w1g2_put(game, bok["Patron of the Orochi"], 0)
    forest = _w1g2_put(game, lea["Forest"], 0, tapped=True)
    their_forest = _w1g2_put(game, lea["Forest"], 1, tapped=True)
    mountain = _w1g2_put(game, lea["Mountain"], 0, tapped=True)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0, tapped=True)
    goblins = _w1g2_put(game, lea["Hill Giant"], 0, tapped=True)
    assert game.activate_permanent_ability(
        0, "Patron of the Orochi", permanent_index=game.battlefield_index_of(patron),
    ).supported
    _w1g2_settle(game)
    assert not forest.tapped and not their_forest.tapped and not bears.tapped
    assert mountain.tapped and goblins.tapped
    # The Patron is green and untapped itself; a second activation is refused.
    assert not patron.tapped
    refused = game.activate_permanent_ability(
        0, "Patron of the Orochi", permanent_index=game.battlefield_index_of(patron),
    )
    assert not refused.supported


def test_w1g2_kentaro_lets_samurai_be_cast_for_generic_mana(set_pool):
    """Kentaro on the battlefield: Kitsune Blademaster ({2}{W}) is cast with
    three red mana as its alternative cost ({X}, X its mana value); a
    non-Samurai is offered nothing, and Bob's Samurai is offered nothing by
    Alice's Kentaro (CR 109.5, "spells you cast")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [chk["Kitsune Blademaster"], lea["Grizzly Bears"]], [chk["Kitsune Blademaster"]],
    ), mana=True)
    _w1g2_put(game, bok["Kentaro, the Smiling Cat"], 0)
    assert game.applicable_alternative_costs(1, game.players[1].hand[0]) == ()
    assert game.applicable_alternative_costs(0, game.players[0].hand[1]) == ()
    (offer,) = [
        entry for entry in game.cast_cost_offers(0, game.players[0].hand[0], spell_hand_index=0)
        if entry["kind"] == "alternative"
    ]
    assert offer["label"] == "pay {3}"
    assert offer["granted_by"] == "Kentaro, the Smiling Cat"
    game.players[0].mana_pool.update({"R": 3})
    assert not game.cast_from_hand(0, "Kitsune Blademaster").supported
    result = game.cast_from_hand(0, "Kitsune Blademaster", alternative_cost=True)
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Kentaro, the Smiling Cat", "Kitsune Blademaster"]
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_kentaro_applies_only_while_on_the_battlefield(set_pool):
    """Ruling 2005-02-01: "Kentaro's ability only applies while Kentaro is on
    the battlefield. You have to pay for Kentaro normally." In hand it grants
    nothing, to itself (a Samurai) or to another Samurai."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=(
        [bok["Kentaro, the Smiling Cat"], chk["Kitsune Blademaster"]], (),
    ), mana=True)
    assert game.applicable_alternative_costs(0, game.players[0].hand[0]) == ()
    assert game.applicable_alternative_costs(0, game.players[0].hand[1]) == ()

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
