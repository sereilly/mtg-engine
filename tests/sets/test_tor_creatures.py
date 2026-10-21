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
#
# Linked exile and leaving the battlefield (CR 607.2a): "return the exiled
# cards" in three destinations (Gravegouger, Hypnox, Petradon), Mesmeric
# Fiend's chosen card, and Chainer's reanimation. Each card is driven through
# the real cast / activation / response path, and each "old-style O-Ring"
# card is also killed with its entry trigger on the stack: the leave trigger
# resolves first and returns nothing, then the entry trigger exiles for good
# (Mesmeric Fiend's ruling, 2018-03-16).

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.linked_exile import linked_entries as _w1g3_linked_entries
from engine.models import Permanent as _W1G3Permanent
from engine.object_colors import object_colors as _w1g3_object_colors
from engine.layer_bridge import computed_types as _w1g3_computed_types
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_card(set_pool, name):
    for code in ("TOR", "LEA", "ODY"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_game(set_pool, *, hand=(), opp_hand=(), opp_graveyard=(), graveyard=()):
    card = lambda name: _w1g3_card(set_pool, name)  # noqa: E731
    p0 = _W1G3PlayerState(
        name="P0", hand=[card(n) for n in hand],
        graveyard=[card(n) for n in graveyard],
        library=[card("Swamp")] * 5,
    )
    p1 = _W1G3PlayerState(
        name="P1", hand=[card(n) for n in opp_hand],
        graveyard=[card(n) for n in opp_graveyard],
        library=[card("Forest")] * 5,
    )
    game = _W1G3Game(players=[p0, p1])
    game.enforce_mana_costs = False
    return game


def _w1g3_put(game, set_pool, seat, name):
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_resolve_stack(game)
    return permanent


def _w1g3_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g3_drain(game):
    for _ in range(4):
        _w1g3_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g3_swords_in_response(game, victim):
    """Exile *victim* with Swords to Plowshares while its entry trigger is
    still on the stack — the response CR 603.3 made possible."""
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g3_drain(game)


# --- Gravegouger: "return the exiled cards to their owner's graveyard" -----


def test_w1g3_gravegouger_exiles_two_cards_and_returns_them_when_it_leaves(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears", "Giant Growth"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Gravegouger")
    _w1g3_drain(game)

    assert len(p1.exile) == 2, game.log[-5:]
    assert len(p1.graveyard) == 1
    gouger = _w1g3_named(game, 0, "Gravegouger")
    # CR 607.2a: the two cards are recorded as exiled *with* the Gravegouger.
    assert sorted(e["card"].name for e in _w1g3_linked_entries(gouger)) == sorted(
        c.name for c in p1.exile
    )

    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[gouger.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.graveyard) == [
        "Giant Growth", "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g3_gravegouger_killed_in_response_exiles_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.queue_from_hand(0, "Gravegouger")
    game.resolve_top_of_stack()
    gouger = _w1g3_named(game, 0, "Gravegouger")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g3_swords_in_response(game, gouger)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled both cards, and nothing is left to bring them back.
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Lightning Bolt"]
    assert p1.graveyard == []


# --- Petradon: "…to the battlefield under their owners' control" -----------


def test_w1g3_petradon_exiles_two_lands_and_returns_them_to_their_owners(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]

    petradon = _w1g3_named(game, 0, "Petradon")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[petradon.permanent_id],
    )
    _w1g3_drain(game)

    # Under their owner's control (CR 110.2a), and as new objects (CR 400.7).
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Forest", "Mountain"]
    assert game.players[1].exile == []
    assert all(p.permanent_id not in (forest.permanent_id, mountain.permanent_id)
               for p in game.controlled_by(1))


def test_w1g3_petradon_killed_in_response_keeps_the_lands_exiled(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.queue_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    game.resolve_top_of_stack()
    petradon = _w1g3_named(game, 0, "Petradon")

    _w1g3_swords_in_response(game, petradon)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]


def test_w1g3_petradon_owes_two_targets_or_none(set_pool):
    """"Exile **two** target lands": a printed count with no "up to" is owed
    whole (CR 601.2c). A one-land board offers no legal announcement, so
    CR 603.3d takes the trigger off the stack — it does not exile the one land
    it could reach. A cast naming one land is set aside the same way."""
    game = _w1g3_game(set_pool, hand=["Petradon"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1, target_permanent_ids=[forest.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == ["Forest"]
    assert game.players[1].exile == []
    assert any("needs 2 targets" in line for line in game.log), game.log[-4:]


def test_w1g3_petradon_asked_for_its_targets_takes_exactly_two(set_pool):
    """Put onto the battlefield (nothing announced), a human controller is
    asked: one land is refused, two are the announcement."""
    game = _w1g3_game(set_pool)
    game.interactive_seats = {0}
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    island = _w1g3_put(game, set_pool, 1, "Island")
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, "Petradon"))
    game._put_permanent_onto_battlefield(0, permanent, None)

    (asked,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert asked.data["max_targets"] == 2 and asked.data.get("exact_targets")
    # …and the web layer tells the client so (its Confirm is wave 2's).
    from web.prompts import PromptContext, render_prompts

    shown = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["trigger_target"]
    assert shown["max_targets"] == 2 and shown["exact_targets"] is True
    assert "up_to" not in shown
    assert not game.confirm_trigger_target(0, permanent_id=forest.permanent_id)
    assert not game.confirm_trigger_target(0, permanent_ids=[forest.permanent_id])
    assert game.confirm_trigger_target(
        0, permanent_ids=[forest.permanent_id, island.permanent_id]
    )
    game.interactive_seats = set()
    _w1g3_drain(game)

    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Island"]


# --- Hypnox: "if you cast it from your hand" and the whole hand --------------


def test_w1g3_hypnox_cast_from_hand_exiles_the_hand_and_gives_it_back(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Hypnox", target_player_index=1)
    _w1g3_drain(game)

    assert p1.hand == []
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Island", "Lightning Bolt"]

    hypnox = _w1g3_named(game, 0, "Hypnox")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[hypnox.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Grizzly Bears", "Island", "Lightning Bolt"]


def test_w1g3_hypnox_put_onto_the_battlefield_does_not_trigger(set_pool):
    """CR 603.4: a permanent that was never cast was not cast from a hand."""
    game = _w1g3_game(set_pool, opp_hand=["Lightning Bolt", "Island"])
    _w1g3_put(game, set_pool, 0, "Hypnox")

    assert sorted(c.name for c in game.players[1].hand) == ["Island", "Lightning Bolt"]
    assert any("didn't trigger" in line for line in game.log), game.log[-3:]


def test_w1g3_hypnox_killed_in_response_exiles_the_hand_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island"],
    )
    game.queue_from_hand(0, "Hypnox", target_player_index=1)
    game.resolve_top_of_stack()
    hypnox = _w1g3_named(game, 0, "Hypnox")

    _w1g3_swords_in_response(game, hypnox)

    # The condition is still true as the trigger resolves (it *was* cast from
    # a hand), so the hand is exiled — after the leave trigger found nothing.
    assert game.players[1].hand == []
    assert sorted(c.name for c in game.players[1].exile) == ["Island", "Lightning Bolt"]


# --- Mesmeric Fiend: the chosen card, linked --------------------------------


def test_w1g3_mesmeric_fiend_exiles_a_nonland_card_and_returns_it(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.interactive_seats = {0}
    p1 = game.players[1]
    game.cast_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game._settle()
    (choice,) = [c for c in game.pending_choices if c.kind == "revealed_hand_pick"]
    # Only the nonland card is offered.
    assert [p1.hand[i].name for i in choice.data["legal_indices"]] == ["Lightning Bolt"]
    assert game.confirm_revealed_hand_pick(0, choice.data["legal_indices"][0])

    assert [c.name for c in p1.exile] == ["Lightning Bolt"]
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")
    assert [e["card"].name for e in _w1g3_linked_entries(fiend)] == ["Lightning Bolt"]

    game.interactive_seats = set()
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[fiend.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Island", "Lightning Bolt"]


def test_w1g3_mesmeric_fiend_killed_in_response_exiles_indefinitely(set_pool):
    """The card's ruling (2018-03-16): "its second ability will trigger and do
    nothing. Then its first ability will resolve and exile a nonland card from
    the target opponent's hand indefinitely.\""""
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.queue_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game.resolve_top_of_stack()
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")

    _w1g3_swords_in_response(game, fiend)

    assert [c.name for c in game.players[1].exile] == ["Lightning Bolt"]
    assert [c.name for c in game.players[1].hand] == ["Island"]


# --- Chainer, Dementia Master -------------------------------------------------


def _w1g3_chainer(set_pool, opp_graveyard=("Grizzly Bears",)):
    game = _w1g3_game(set_pool, opp_graveyard=list(opp_graveyard))
    chainer = _w1g3_put(game, set_pool, 0, "Chainer, Dementia Master")
    return game, chainer


def test_w1g3_chainer_reanimates_a_black_nightmare_under_your_control(set_pool):
    game, _chainer = _w1g3_chainer(set_pool)
    life = game.players[0].life
    result = game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, game.log[-3:]
    _w1g3_drain(game)

    assert game.players[0].life == life - 3, "Pay 3 life"
    bears = _w1g3_named(game, 0, "Grizzly Bears")
    # The ruling (2022-12-08): "black only, not black in addition to its other
    # colors … a Nightmare in addition to its other creature types".
    assert set(_w1g3_object_colors(game, bears)) == {"B"}
    _card_types, subtypes = _w1g3_computed_types(bears)
    assert {"bear", "nightmare"} <= set(subtypes)
    # "All Nightmares get +1/+1." — the Nightmares include the reanimated one.
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    # CR 108.3: still its owner's card.
    assert game.owner_index_of(bears) == 1


def test_w1g3_chainer_leaving_exiles_every_nightmare(set_pool):
    game, chainer = _w1g3_chainer(set_pool)
    game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    _w1g3_drain(game)
    _w1g3_put(game, set_pool, 1, "Gravegouger")  # a printed Nightmare
    _w1g3_put(game, set_pool, 1, "Grizzly Bears")  # not one

    game.remove_from_battlefield(chainer)
    game._permanent_to_graveyard(game.players[0], chainer)
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(0)] == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    # Each to its owner's exile (CR 400.3).
    assert sorted(c.name for c in game.players[1].exile) == ["Gravegouger", "Grizzly Bears"]


# --- The drive list: supported on arrival, driven -----------------------------


def test_w1g3_slithery_stalker_gives_back_what_it_exiled(set_pool):
    """The ingest's red census named this card, and the card was right: its
    swampwalk reminder text says "as long as", which the census had read as a
    duration (now stripped, CR 207.2a). Driven both ways round."""
    game = _w1g3_game(set_pool, hand=["Slithery Stalker", "Swords to Plowshares"])
    bears = _w1g3_put(game, set_pool, 1, "Grizzly Bears")
    game.cast_from_hand(
        0, "Slithery Stalker", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g3_drain(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]

    stalker = _w1g3_named(game, 0, "Slithery Stalker")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[stalker.permanent_id],
    )
    _w1g3_drain(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert game.players[1].exile == []


def test_w1g3_laquatus_champion_killed_in_response_gives_the_life_first(set_pool):
    """The ruling (2018-03-16): "the player who gains 6 life is the player who
    was the target of the first ability (or, if that ability is still on the
    stack, the player who is its target)." So the gain resolves first and the
    loss after it."""
    game = _w1g3_game(set_pool, hand=["Laquatus's Champion", "Swords to Plowshares"])
    game.queue_from_hand(0, "Laquatus's Champion", target_player_index=1)
    game.resolve_top_of_stack()
    champion = _w1g3_named(game, 0, "Laquatus's Champion")

    _w1g3_swords_in_response(game, champion)

    gained = next(i for i, line in enumerate(game.log) if "gained 6 life from Laquatus" in line)
    lost = next(i for i, line in enumerate(game.log) if "lost 6 life" in line)
    assert gained < lost
    assert game.players[1].life == 20


def test_w1g3_an_ai_aims_the_champions_life_loss_across_the_table(set_pool):
    """"Target player loses 6 life" names a seat the cast announces, and the
    AI's spell scorer cannot read a trigger: with no side to go on it named its
    own seat and lost the 6 life itself (Soul Scourge the same, for 3).
    ``ai_valuation._SEAT_DENIAL_KINDS`` now files the life loss as a denial."""
    from engine.ai_policy import cast_announcement, choose_cast_action

    for name, amount in (("Laquatus's Champion", 6), ("Soul Scourge", 3)):
        game = _w1g3_game(set_pool, hand=[name])
        game.interactive_seats = set()
        game.active_player_index = 0
        action = choose_cast_action(game, 0)
        assert action is not None and action.card_name == name
        announced = cast_announcement(action)
        assert announced["target_player_index"] == 1, name
        announced.pop("from_zone", None)
        game.cast_from_hand(0, name, **announced)
        _w1g3_drain(game)
        assert [p.life for p in game.players] == [20, 20 - amount], name

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

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_duel(*, hand0=(), hand1=(), bf0=(), bf1=(), library0=None):
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library0) if library0 is not None else [filler] * 10,
            hand=list(hand0),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10, hand=list(hand1),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def test_w1g5_cephalid_vandal_mills_one_more_card_each_upkeep(set_pool):
    """A shred counter each upkeep, then a mill of one card per shred counter:
    1, then 2, then 3 — the count read off the source as the trigger resolves."""
    vandal = set_pool("TOR")["Cephalid Vandal"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(10)]
    game = _w1g5_duel(bf0=[vandal], library0=library)

    milled = []
    for _turn in range(3):
        before = len(game.players[0].graveyard)
        game.start_turn(0)
        _w1g5_resolve_stack(game)
        milled.append(len(game.players[0].graveyard) - before)

    assert milled == [1, 2, 3]
    assert "Cephalid Vandal gets a shred counter (3 total)" in game.log
    assert "A milled 3 card(s)" in game.log


def test_w1g5_pitchstone_wall_returns_the_discarded_card_if_sacrificed(set_pool):
    """Two discards, two triggers. Taking the first offer sacrifices the Wall
    and returns that card; the second finds no Wall to sacrifice ("if you do")
    and returns nothing."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    wall, sludge = tor["Pitchstone Wall"], tor["Mind Sludge"]
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g5_duel(
        hand0=[bolt, bears, forest], hand1=[sludge],
        bf0=[wall], bf1=[lea["Swamp"], lea["Swamp"]],
    )
    game.interactive_seats = {0}

    game.cast_from_hand(1, sludge.name, target_player_index=0)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1], to_library=False,
    )
    assert [item.card.name for item in game.stack] == ["Pitchstone Wall"] * 2
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g5_resolve_stack(game)

    a = game.players[0]
    assert sorted(card.name for card in a.hand) == ["Forest", "Lightning Bolt"]
    assert sorted(card.name for card in a.graveyard) == ["Grizzly Bears", "Pitchstone Wall"]
    assert not list(game.controlled_by(0))


def test_w1g5_pitchstone_wall_declined_returns_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[lea["Lightning Bolt"]], hand1=[tor["Mind Sludge"]],
        bf0=[tor["Pitchstone Wall"]], bf1=[lea["Swamp"]],
    )

    game.cast_from_hand(1, "Mind Sludge", target_player_index=0)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Pitchstone Wall"]


def test_w1g5_pitchstone_wall_ignores_an_opponents_discard(set_pool):
    """"Whenever **you** discard a card": the Wall's controller only."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[tor["Mind Sludge"]], hand1=[lea["Lightning Bolt"]],
        bf0=[tor["Pitchstone Wall"], lea["Swamp"]],
    )

    game.cast_from_hand(0, "Mind Sludge", target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]
    assert not game.stack


def test_w1g5_nantuko_cultivator_counts_and_draws_the_lands_discarded(set_pool):
    """Discard three lands: three +1/+1 counters and three cards. It placed
    none and drew none — the counters read Tetravus's ``trigger_count`` and
    the draw's handler never read ``amount_from`` — and with the counter
    step unreadable the offer could not fold its payoffs, so both ran before
    the discard was even answered."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    forest, island, bolt = lea["Forest"], lea["Island"], lea["Lightning Bolt"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Instant") for i in range(10)]
    game = _w1g5_duel(hand0=[cultivator, forest, forest, island, bolt], library0=library)
    game.interactive_seats = {0}

    game.cast_from_hand(0, cultivator.name)
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    owed = game.pending_choice_of("discard", 0)
    assert owed is not None and owed.data.get("up_to")
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1, 2], to_library=False,
    )
    _w1g5_resolve_stack(game)

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Lightning Bolt", "W1G5 Card 0", "W1G5 Card 1", "W1G5 Card 2",
    ]


def test_w1g5_nantuko_cultivator_declined_places_and_draws_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    game = _w1g5_duel(hand0=[cultivator, lea["Forest"]])

    game.cast_from_hand(0, cultivator.name)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_swarm_table(set_pool, *, humans=()):
    """Shambling Swarm and a Savannah Lions for seat 0, a Grizzly Bears and a
    Hill Giant for seat 1, and a Lightning Bolt in seat 1's hand to kill the
    Swarm with."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", library=[lea["Forest"]] * 10),
        _W1G8Player("B", library=[lea["Forest"]] * 10, hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    placed = {}
    for seat, name, card in (
        (0, "swarm", set_pool("TOR")["Shambling Swarm"]),
        (0, "lions", lea["Savannah Lions"]),
        (1, "bears", lea["Grizzly Bears"]),
        (1, "giant", lea["Hill Giant"]),
    ):
        placed[name] = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, placed[name], None)
    return game, placed


def _w1g8_bolt_the_swarm(game, swarm):
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[swarm.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)


def _w1g8_body(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g8_shambling_swarm_dies_and_a_seat_nobody_asks_spreads_its_counters(set_pool):
    """"When this creature dies, distribute three -1/-1 counters among one,
    two, or three target creatures." It compiled, reported supported and
    announced nothing: the handler found one creature on its own and put all
    three counters on it, and a person was never asked. A seat nobody asks
    now announces as a divided spell is proposed — the opponent's creatures,
    spread — and the shares come back at the next end step."""
    game, placed = _w1g8_swarm_table(set_pool)
    _w1g8_bolt_the_swarm(game, placed["swarm"])

    assert "Shambling Swarm: targets Grizzly Bears (2), Hill Giant (1)" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(placed["bears"]), "2/2 with two -1/-1 counters"
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert _w1g8_body(placed["lions"]) == (2, 1), "its controller's own is spared"

    # One delayed removal per counter, each bound to its own creature; the
    # Bears' two find nothing (CR 400.7), the Giant's one finds the Giant.
    assert sorted(t.bound_permanent_id for t in game.delayed_triggers) == sorted([
        placed["bears"].permanent_id, placed["bears"].permanent_id,
        placed["giant"].permanent_id,
    ])
    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (3, 3)
    assert placed["giant"].metadata.get("minus_counters", 0) == 0
    assert not game.delayed_triggers


def test_w1g8_shambling_swarm_asks_its_controller_for_the_division(set_pool):
    """A person is asked which creatures **and** how the three counters are
    divided among them (CR 603.3d, CR 601.2d) — and the dying Swarm itself is
    not on offer, because the ability goes on the stack after it has died.
    Two targets are 2+1 or 1+2, which is the announcer's choice: an answer
    leaving it out is refused, and so is one that does not total three."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    assert bolt.supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert (asked.data["max_targets"], asked.data["division_total"]) == (3, 3)
    assert asked.data["division"] == "chosen"
    offered = {t["permanent_id"] for t in asked.data["targets"]}
    assert placed["swarm"].permanent_id not in offered
    assert offered == {
        placed[name].permanent_id for name in ("lions", "bears", "giant")
    }

    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert not game.confirm_trigger_target(0, permanent_ids=pair), "2+1 or 1+2?"
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 1])
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[3, 0])
    assert not game.confirm_trigger_target(0, permanent_ids=[]), "one or more"
    assert game.pending_choices == [asked]

    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 2])
    _w1g8_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g8_body(placed["bears"]) == (1, 1)
    assert _w1g8_body(placed["giant"]) == (1, 1)

    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["bears"]) == (2, 2)
    assert _w1g8_body(placed["giant"]) == (3, 3)


def test_w1g8_shambling_swarm_forced_divisions_need_no_amounts(set_pool):
    """One target takes all three and three targets take one apiece — no
    choice is left to make, so an answer naming either needs no division."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    assert game.confirm_trigger_target(0, permanent_id=placed["giant"].permanent_id)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (0, 0)
    assert _w1g8_body(placed["bears"]) == (2, 2)


def test_w1g8_shambling_swarm_keeps_a_departed_targets_share_out(set_pool):
    """CR 608.2b: a target that has left is illegal and its share goes
    nowhere — the survivor keeps exactly what was announced for it, and the
    ability still resolves for it."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.players[0].hand.append(set_pool("LEA")["Unsummon"])
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[2, 1])

    # In response, the Bears go back to their owner's hand.
    bounce = game.cast_from_hand(
        0, "Unsummon", target_player_index=1,
        target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert bounce.supported, bounce.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert placed["giant"].metadata.get("minus_counters") == 1


def _w1g8_cast_firecat(set_pool, monkeypatch, coins):
    """Crazed Firecat cast and resolved with the flips scripted, entry
    trigger and all."""
    script = iter(coins)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda: next(script)
    )
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Crazed Firecat"]]),
        _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    result = game.cast_from_hand(0, "Crazed Firecat")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)
    (firecat,) = game.controlled_by(0)
    return game, firecat


def test_w1g8_crazed_firecat_counts_the_flips_it_won(monkeypatch, set_pool):
    """"When this creature enters, flip a coin until you lose a flip. Put a
    +1/+1 counter on this creature for each flip you won." Won, won, lost:
    two counters, and the losing flip ends the run (the scripted coin has no
    fourth face to give)."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [True, True, False])
    assert _w1g8_body(firecat) == (6, 6)
    assert firecat.metadata.get("plus_counters") == 2
    assert "Crazed Firecat: won 2 flip(s) before losing one" in game.log


def test_w1g8_crazed_firecat_that_loses_the_first_flip_gets_nothing(monkeypatch, set_pool):
    """The losing flip is not a flip won: lose the first and the Firecat is
    its printed 4/4."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [False])
    assert _w1g8_body(firecat) == (4, 4)
    assert not firecat.metadata.get("plus_counters")


def test_w1g8_for_each_flip_you_won_names_a_run_or_nothing():
    """The count is the run's record, read through the producer gate every
    back-reference passes: with no run of flips in front of it the words name
    nothing, and the line refuses rather than placing zero counters."""
    from engine.grammar import compile_line

    lone = compile_line(
        "When this creature enters, put a +1/+1 counter on this creature for "
        "each flip you won."
    )
    assert not lone.usable and lone.lowering_error

# ==== end W1G8 ======================================================
