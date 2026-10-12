"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(), their_hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(their_library), hand=list(their_hand), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Bearscape, Screams of the Damned ---------------------------------------
# Driven: the Atog-style graveyard exile costs on two enchantments.

def test_w1g6_bearscape_makes_a_bear_for_two_cards_and_nothing_for_one(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(mine=[ody["Bearscape"]], yard=[lea["Forest"]] * 3)
    game.start_turn(0)

    made = game.activate_permanent_ability(0, "Bearscape")

    assert made.supported, made.details
    assert len(game.players[0].graveyard) == 1 and len(game.players[0].exile) == 2
    bear = next(p for p in game.controlled_by(0) if p.card.name != "Bearscape")
    assert "Bear" in bear.card.type_line and "Creature" in bear.card.type_line
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert tuple(bear.card.colors) == ("G",)

    refused = game.activate_permanent_ability(0, "Bearscape")
    assert not refused.supported
    assert len(game.players[0].graveyard) == 1
    assert len(list(game.controlled_by(0))) == 2


def test_w1g6_screams_of_the_damned_pings_everything_for_one_card(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Screams of the Damned"], lea["Grizzly Bears"]],
        theirs=[lea["Birds of Paradise"], lea["Hill Giant"]],
        yard=[lea["Forest"]],
    )
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Screams of the Damned")
    game.check_state_based_actions()

    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "exile") == ["Forest"]
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert _w1g6_names(game, 1) == ["Hill Giant"]  # the 0/1 Birds died
    assert _w1g6_named(game, 0, "Grizzly Bears").damage_marked == 1

    # An empty graveyard cannot pay, and nothing is dealt.
    refused = game.activate_permanent_ability(0, "Screams of the Damned")
    assert not refused.supported
    assert (game.players[0].life, game.players[1].life) == (19, 19)


# --- Holistic Wisdom --------------------------------------------------------
# "{2}, Exile a card from your hand: Return target card from your graveyard to
# your hand if it shares a card type with the card exiled this way." The
# target is any card (CR 601.2c precedes the cost, CR 601.2h); the comparison
# is made as the ability resolves, between two cards' printed types.

def _w1g6_wisdom(set_pool, hand, yard):
    ody = set_pool("ODY")
    game = _w1g6_game(mine=[ody["Holistic Wisdom"]], hand=hand, yard=yard)
    game.start_turn(0)
    return game  # _w1g6_wisdom


@_w1g6_pytest.mark.parametrize(
    "exiled, wanted, returned",
    [
        ("Grizzly Bears", "Craw Wurm", True),        # creature / creature
        ("Grizzly Bears", "Lightning Bolt", False),  # creature / instant
        ("Forest", "Island", True),                  # land / land
        ("Ornithopter", "Sol Ring", True),           # artifact creature / artifact
        ("Ornithopter", "Craw Wurm", True),          # artifact creature / creature
        ("Sol Ring", "Craw Wurm", False),            # artifact / creature
    ],
)
def test_w1g6_holistic_wisdom_returns_a_card_that_shares_a_type(
    set_pool, exiled, wanted, returned
):
    lea = set_pool("LEA")
    cards = {**lea, "Ornithopter": set_pool("ATQ")["Ornithopter"]}
    game = _w1g6_wisdom(
        set_pool, hand=[cards[exiled]], yard=[lea["Mountain"], cards[wanted]],
    )

    used = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=1,
        cost_hand_index=0,
    )

    # The cost is paid either way: the card from hand is exiled.
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "exile") == [exiled]
    assert _w1g6_pile(game.players[0], "hand") == ([wanted] if returned else [])
    assert _w1g6_pile(game.players[0]) == (
        ["Mountain"] if returned else ["Mountain", wanted]
    )


def test_w1g6_holistic_wisdom_refusals_pay_nothing(set_pool):
    lea = set_pool("LEA")
    # An empty hand cannot pay.
    game = _w1g6_wisdom(set_pool, hand=[], yard=[lea["Craw Wurm"]])
    refused = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=0
    )
    assert not refused.supported and _w1g6_pile(game.players[0]) == ["Craw Wurm"]

    # No card in your graveyard: nothing to target, and the hand is not eaten.
    game = _w1g6_wisdom(set_pool, hand=[lea["Grizzly Bears"]], yard=[])
    refused = game.activate_permanent_ability(0, "Holistic Wisdom", cost_hand_index=0)
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Grizzly Bears"]

    # An opponent's graveyard is not yours.
    game = _w1g6_game(
        mine=[set_pool("ODY")["Holistic Wisdom"]], hand=[lea["Grizzly Bears"]],
        their_yard=[lea["Craw Wurm"]],
    )
    game.start_turn(0)
    refused = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=1, target_permanent_index=0,
        cost_hand_index=0,
    )
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Grizzly Bears"]


def test_w1g6_holistic_wisdom_does_nothing_once_its_target_has_left(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_wisdom(
        set_pool, hand=[lea["Grizzly Bears"]],
        yard=[lea["Craw Wurm"], lea["Hill Giant"]],
    )
    queued = game.queue_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=0,
        cost_hand_index=0,
    )
    assert queued.details == "queued"
    game.players[0].graveyard.pop(0)   # the Wurm leaves in response
    _w1g6_resolve_stack(game)

    # CR 608.2b: no other creature card is taken in its place.
    assert _w1g6_pile(game.players[0]) == ["Hill Giant"]
    assert not game.players[0].hand


# --- Gravestorm -------------------------------------------------------------
# "At the beginning of your upkeep, target opponent may exile a card from
# their graveyard. If that player doesn't, you may draw a card." The offer is
# the opponent's, the pile is the opponent's, and the pick is the opponent's.

def _w1g6_gravestorm(set_pool, their_yard):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Gravestorm"]], their_yard=their_yard, yard=[lea["Mountain"]],
        library=[lea["Island"]] * 5,
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    choice = game.pending_choices[0]
    assert choice.kind == "trigger_target" and choice.player_index == 0
    assert game.confirm_trigger_target(0, seat=1)
    game.resolve_top_of_stack()
    return game  # _w1g6_gravestorm


def test_w1g6_gravestorm_the_opponent_exiles_a_card_of_their_choice(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_gravestorm(set_pool, [lea["Forest"], lea["Hill Giant"]])

    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", 1)
    assert game.confirm_optional_pay(1, accept=True)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.player_index, pick.data["owner_index"]) == (
        "graveyard_exile_pick", 1, 1,
    )
    # The pick is the opponent's: the Gravestorm's controller cannot answer it.
    assert not game.confirm_graveyard_exile_pick(0, [1])
    assert game.confirm_graveyard_exile_pick(1, [1])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest"]
    assert _w1g6_pile(game.players[1], "exile") == ["Hill Giant"]
    # The opponent did: no draw is offered, and your own graveyard is untouched.
    assert not game.pending_choices and not game.players[0].hand
    assert _w1g6_pile(game.players[0]) == ["Mountain"]


def test_w1g6_gravestorm_a_declining_opponent_lets_you_draw(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_gravestorm(set_pool, [lea["Forest"]])

    assert game.confirm_optional_pay(1, accept=False)
    draw = game.pending_choices[0]
    assert (draw.kind, draw.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest"] and not game.players[1].exile
    assert _w1g6_pile(game.players[0], "hand") == ["Island"]


def test_w1g6_gravestorm_an_opponent_with_no_graveyard_is_not_asked(set_pool):
    game = _w1g6_gravestorm(set_pool, [])

    # Nothing to exile is not an offer: it goes straight to "you may draw".
    draw = game.pending_choices[0]
    assert (draw.kind, draw.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=False)
    _w1g6_resolve_stack(game)
    assert not game.players[0].hand and len(game.players[0].library) == 5


# --- Pedantic Learning ------------------------------------------------------
# "Whenever a land card is put into your graveyard from your library, you may
# pay {1}. If you do, draw a card." The graveyard seam's one arrival event,
# narrowed three ways as data: what the card is, whose pile, and where from.

def _w1g6_learning(set_pool, library, **extra):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Pedantic Learning"], *extra.pop("mine", ())],
        library=[lea[name] for name in library], **extra,
    )
    game.enforce_mana_costs = True
    game.start_turn(0)
    game.players[0].mana_pool["U"] = 1
    return game  # _w1g6_learning


def _w1g6_learning_triggers(game):
    return [item for item in game.stack if item.card.name == "Pedantic Learning"]


def test_w1g6_pedantic_learning_draws_for_a_land_milled_from_your_library(set_pool):
    from engine.replacements import _mill_cards as _w1g6_mill

    game = _w1g6_learning(set_pool, ["Forest", "Island", "Island"])
    _w1g6_mill(game, game.players[0], 1)

    assert len(_w1g6_learning_triggers(game)) == 1
    _w1g6_resolve_stack(game)
    offer = game.pending_choices_of("optional_pay", 0)[0]
    assert offer.data["cost"] == {"generic": 1}
    assert game.confirm_optional_pay(0, accept=True)
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0], "hand") == ["Island"]
    assert game.players[0].mana_pool["U"] == 0


def test_w1g6_pedantic_learning_triggers_once_per_land_and_pays_each_separately(
    set_pool,
):
    from engine.replacements import _mill_cards as _w1g6_mill

    game = _w1g6_learning(set_pool, ["Forest", "Forest", "Island", "Island"])
    _w1g6_mill(game, game.players[0], 2)
    assert len(_w1g6_learning_triggers(game)) == 2

    for _ in range(4):
        _w1g6_resolve_stack(game)
        offers = game.pending_choices_of("optional_pay", 0)
        if not offers:
            break
        assert game.confirm_optional_pay(0, accept=True)

    # One mana in the pool buys one card, not two.
    assert len(game.players[0].hand) == 1


def test_w1g6_pedantic_learning_ignores_every_other_arrival(set_pool):
    from engine.replacements import _mill_cards as _w1g6_mill

    lea = set_pool("LEA")
    # A nonland card milled.
    game = _w1g6_learning(set_pool, ["Lightning Bolt", "Island"])
    _w1g6_mill(game, game.players[0], 1)
    assert not _w1g6_learning_triggers(game)

    # A land discarded: put into your graveyard, not from your library.
    game = _w1g6_learning(set_pool, ["Island"], hand=[lea["Forest"]])
    game.take_card_from_hand(game.players[0], lea["Forest"])
    game._discard_card(game.players[0], lea["Forest"])
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert not _w1g6_learning_triggers(game)

    # A land sacrificed from the battlefield.
    game = _w1g6_learning(set_pool, ["Island"], mine=[lea["Forest"]])
    game.sacrifice_permanent(_w1g6_named(game, 0, "Forest"))
    assert not _w1g6_learning_triggers(game)

    # An opponent's land milled into the opponent's graveyard.
    game = _w1g6_learning(set_pool, ["Island"], their_library=[lea["Forest"]])
    _w1g6_mill(game, game.players[1], 1)
    assert _w1g6_pile(game.players[1]) == ["Forest"]
    assert not _w1g6_learning_triggers(game)


# --- Traveling Plague -------------------------------------------------------
# "At the beginning of each upkeep, put a plague counter on this Aura. /
# Enchanted creature gets -1/-1 for each plague counter on this Aura. / When
# enchanted creature leaves the battlefield, that creature's controller
# returns this Aura from its owner's graveyard to the battlefield."
# Rulings (Scryfall): "A counter is placed on every player's upkeep" (2004-10-
# 04); "The controller of the dead creature chooses the new creature" (2004-
# 10-04); "The triggered ability returns this card to the battlefield with no
# counters on it" (2005-08-01).

def _w1g6_plague(set_pool, theirs=("Hill Giant", "Grizzly Bears"), mine=("Craw Wurm",)):
    from engine.auras import attach_aura as _w1g6_attach

    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Traveling Plague"], *(lea[name] for name in mine)],
        theirs=[lea[name] for name in theirs],
    )
    game.interactive_seats = {0, 1}
    plague = _w1g6_named(game, 0, "Traveling Plague")
    giant = _w1g6_named(game, 1, "Hill Giant")
    _w1g6_attach(plague, giant)
    return game, plague, giant  # _w1g6_plague


def test_w1g6_traveling_plague_grows_at_every_upkeep_and_shrinks_its_host(set_pool):
    from engine.named_counters import counters_on as _w1g6_counters

    game, plague, giant = _w1g6_plague(set_pool)

    game.start_turn(0)
    _w1g6_resolve_stack(game)
    assert _w1g6_counters(plague, "plague") == 1
    assert (giant.effective_power, giant.effective_toughness) == (2, 2)

    # The opponent's upkeep counts too.
    game.start_turn(1)
    _w1g6_resolve_stack(game)
    assert _w1g6_counters(plague, "plague") == 2
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)


def _w1g6_plague_kills_its_host(set_pool, **board):
    game, plague, giant = _w1g6_plague(set_pool, **board)
    for seat in (0, 1, 0):
        game.start_turn(seat)
        _w1g6_resolve_stack(game)
    game.check_state_based_actions()
    # The Giant is dead at three counters, the Aura followed it (CR 704.5m),
    # and the return is on the stack.
    assert "Hill Giant" in _w1g6_pile(game.players[1])
    assert _w1g6_pile(game.players[0]) == ["Traveling Plague"]
    assert [item.card.name for item in game.stack] == ["Traveling Plague"]
    game.resolve_top_of_stack()
    return game  # _w1g6_plague_kills_its_host


def test_w1g6_traveling_plague_is_returned_by_the_dead_creatures_controller(set_pool):
    from engine.named_counters import counters_on as _w1g6_counters

    game = _w1g6_plague_kills_its_host(set_pool)

    # The dead creature's controller chooses, not the Aura's.
    choice = game.pending_choices[0]
    assert (choice.kind, choice.player_index) == ("permanent_choice", 1)
    wurm = _w1g6_named(game, 0, "Craw Wurm")
    assert not game.confirm_permanent_choice(0, wurm.permanent_id)
    assert game.confirm_permanent_choice(1, wurm.permanent_id)
    _w1g6_resolve_stack(game)

    # It enters under the control of the player who put it there (CR 110.2a),
    # attached to the creature they chose, as a new object with no counters.
    returned = _w1g6_named(game, 1, "Traveling Plague")
    assert returned.metadata.get("attached_to") is wurm
    assert _w1g6_counters(returned, "plague") == 0
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert not game.players[0].graveyard


def test_w1g6_traveling_plague_stays_in_the_graveyard_with_nothing_to_enchant(
    set_pool,
):
    game = _w1g6_plague_kills_its_host(set_pool, theirs=("Hill Giant",), mine=())

    # CR 303.4g: no legal object to enchant, so the Aura stays where it is.
    _w1g6_resolve_stack(game)
    assert not game.pending_choices
    assert _w1g6_pile(game.players[0]) == ["Traveling Plague"]
    assert _w1g6_names(game, 0) == [] and _w1g6_names(game, 1) == []


def test_w1g6_traveling_plague_follows_a_host_that_left_without_dying(set_pool):
    game, plague, giant = _w1g6_plague(set_pool)
    game.start_turn(0)
    _w1g6_resolve_stack(game)

    # Bounced: "leaves the battlefield" is wider than "dies".
    game.remove_from_battlefield(giant)
    game.put_card_into_hand(game.players[1], giant.card, from_battlefield=giant)
    game.check_state_based_actions()
    assert [item.card.name for item in game.stack] == ["Traveling Plague"]
    game.resolve_top_of_stack()
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g6_resolve_stack(game)

    assert _w1g6_named(game, 1, "Traveling Plague").metadata.get("attached_to") is bears


# --- Malevolent Awakening ---------------------------------------------------
# "{1}{B}{B}, Sacrifice a creature: Return target creature card from your
# graveyard to your hand." Driven. One of the four activations the ingest's
# stack-target guard named: the creature its cost sacrifices is a legal
# re-aim its own picker could not have listed.

def test_w1g6_malevolent_awakening_trades_a_creature_for_a_creature_card(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Malevolent Awakening"], lea["Grizzly Bears"], lea["Hill Giant"]],
        yard=[lea["Craw Wurm"], lea["Forest"]], their_yard=[lea["Shivan Dragon"]],
    )
    game.start_turn(0)
    giant = _w1g6_named(game, 0, "Hill Giant")

    used = game.activate_permanent_ability(
        0, "Malevolent Awakening", target_player_index=0, target_permanent_index=0,
        cost_permanent_ids=[giant.permanent_id],
    )
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "hand") == ["Craw Wurm"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Hill Giant"]
    assert _w1g6_names(game, 0) == ["Grizzly Bears", "Malevolent Awakening"]

    # A land card, and an opponent's creature card, are not legal targets —
    # and a refused activation sacrifices nothing.
    for seat, slot in ((0, 0), (1, 0)):
        refused = game.activate_permanent_ability(
            0, "Malevolent Awakening", target_player_index=seat,
            target_permanent_index=slot,
        )
        assert not refused.supported
    assert _w1g6_names(game, 0) == ["Grizzly Bears", "Malevolent Awakening"]

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
