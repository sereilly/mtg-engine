"""A discard paid **as a cost when a spell or ability resolves** is a cost.

CR 118.12: "[A player] may [do something]. If [that player] [does, doesn't],
[effect]." — "The action [do something] is a cost, paid when the spell or
ability resolves." CR 118.12a: "[Do something] unless [a player does
something else]" means "[A player may do something else]. If [that player
doesn't], [do something]." So the discard in "sacrifice this creature unless
you discard a card" (Masticore) is a cost, and two printed conditions that
are about *effects* do not reach it:

* Library of Leng's "If **an effect** causes you to discard a card": "You
  can't use the Library of Leng ability to place a discarded card on top of
  your library when you discard a card as a cost, because costs aren't
  effects" (its 2004-10-04 ruling);
* "a spell or ability an opponent controls **causes** you to discard"
  (Dodecapod's replacement, Psychic Purge's trigger): "Discarding as a cost to
  cast a spell will not trigger the ability. Only discarding as an effect will
  trigger the ability" (Psychic Purge, 2004-10-04).

On the base of round kg5 wave 2 (e245e624c) the seventeen offers whose action
is such a discard compiled to an ordinary ``may`` whose discard the seam took
for an effect's: Masticore's prompt offered Library of Leng's library top,
Balduvian Horde's random discard went on top of the library for a seat nobody
asked, and an opponent's Wrench Mind put a Dodecapod discarded as its artifact
onto the battlefield. Every test marked *backwards* below fails there.

What the mark must not reach is held too: a discard that is an effect behind
an offer ("you may discard any number of land cards. Put that many …",
Nantuko Cultivator; the decline branch of Wrench Mind) is still Library of
Leng's and still Dodecapod's, and a cost discard is still a discard (CR
701.9a — Megrim hears it).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}


def _game(*, hand=(), opponent_hand=(), interactive=()) -> Game:
    game = Game(players=[
        PlayerState("A", hand=[_POOL[n] for n in hand], library=[_POOL["Forest"]] * 8),
        PlayerState("B", hand=[_POOL[n] for n in opponent_hand],
                    library=[_POOL["Forest"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    settle(game)
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    settle(game)
    return permanent


def _to_upkeep(game: Game, seat: int = 0) -> None:
    """The other seat's turn, then *seat*'s, up to its first prompt or rest."""
    game.start_turn(1 - seat)
    settle(game)
    game.start_turn(seat)


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _accept(game, choice):
    assert game.confirm_optional_pay(choice.player_index, accept=True)


def _decline(game, choice):
    assert game.confirm_optional_pay(choice.player_index, accept=False)


# --- Library of Leng does not take a cost ------------------------------------


def test_masticore_s_upkeep_discard_is_not_offered_the_library_top():
    """Backwards: the prompt offered the top, and the answer put the card
    there (the Library's "you may", on a cost)."""
    game = _game(hand=["Grizzly Bears", "Hill Giant"], interactive=(0,))
    _put(game, 0, "Library of Leng")
    _put(game, 0, "Masticore")
    _to_upkeep(game)

    asked = settle(game, answers={"optional_pay": _accept}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert asked.data.get("allow_top_of_library") is False
    assert game.confirm_discard(0, [0], to_library=True)
    settle(game)

    player = game.players[0]
    assert _names(player.graveyard) == ["Grizzly Bears"]
    assert _names(player.library) == ["Forest"] * len(player.library)
    assert any(p.card.name == "Masticore" for p in game.controlled_by(0))
    assert not any("Library of Leng" in line for line in game.log)


def test_balduvian_horde_s_random_discard_goes_to_the_graveyard_under_leng():
    """Backwards: the Library's replacement took the random discard and, for a
    seat nobody asks, put the card on top of the library."""
    game = _game(hand=["Balduvian Horde", "Grizzly Bears"])
    _put(game, 0, "Library of Leng")

    assert game.queue_from_hand(0, "Balduvian Horde").supported
    settle(game)

    player = game.players[0]
    assert _names(player.graveyard) == ["Grizzly Bears"]
    assert player.library[0].name == "Forest"
    assert any(p.card.name == "Balduvian Horde" for p in game.controlled_by(0))
    assert not any("Library of Leng" in line for line in game.log)


def test_coral_net_s_granted_upkeep_discard_is_a_cost_too():
    """The granted ability ("Enchanted creature has 'At the beginning of your
    upkeep, sacrifice this creature unless you discard a card.'") is compiled
    from its quoted text when it is granted — the same offer, the same mark.
    Backwards: its prompt offered the library top."""
    game = _game(hand=["Hill Giant", "Coral Net"], interactive=(0,))
    _put(game, 0, "Library of Leng")
    bears = _put(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Coral Net", target_permanent_ids=[bears.permanent_id],
    ).supported
    settle(game)
    net = next(p for p in game.controlled_by(0) if p.card.name == "Coral Net")
    assert net.metadata.get("attached_to") is bears
    _to_upkeep(game)

    asked = settle(game, answers={"optional_pay": _accept}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert asked.data.get("allow_top_of_library") is False
    assert game.confirm_discard(0, [0], to_library=True)
    settle(game)

    assert _names(game.players[0].graveyard) == ["Hill Giant"]
    assert game.is_on_battlefield(bears)


def test_mishras_war_machine_s_upkeep_discard_is_a_cost():
    """"…deals 3 damage to you unless you discard a card" (the fused upkeep
    kind, not an offer). Backwards: the Library's replacement took it and the
    card went on top of the library."""
    game = _game(hand=["Grizzly Bears"])
    _put(game, 0, "Library of Leng")
    _put(game, 0, "Mishra's War Machine")
    _to_upkeep(game)
    settle(game)

    player = game.players[0]
    assert _names(player.graveyard) == ["Grizzly Bears"]
    assert player.library[0].name == "Forest"
    assert player.life == 20


# --- no opponent's spell causes a cost discard -------------------------------


def test_an_opponent_s_wrench_mind_paid_with_dodecapod_does_not_put_it_onto_the_battlefield():
    """"Target player discards two cards unless they discard an artifact
    card": the artifact discard is the cost. Backwards: Dodecapod entered with
    two counters."""
    game = _game(hand=["Wrench Mind"], opponent_hand=["Dodecapod", "Hill Giant"],
                 interactive=(1,))
    assert game.queue_from_hand(0, "Wrench Mind", target_player_index=1).supported

    asked = settle(game, answers={"optional_pay": _accept}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert asked.player_index == 1
    assert game.confirm_discard(1, [0])
    settle(game)

    opponent = game.players[1]
    assert _names(opponent.graveyard) == ["Dodecapod"]
    assert _names(opponent.hand) == ["Hill Giant"]
    assert not any(p.card.name == "Dodecapod" for p in game.all_permanents())


def test_an_opponent_s_forbidden_ritual_paid_with_dodecapod_does_not_put_it_onto_the_battlefield():
    """"…target opponent loses 2 life unless that player sacrifices a
    permanent of their choice **or discards a card**": the discard is one of
    the two ways to pay the cost (a ``choose_one`` inside the offer).
    Backwards: Dodecapod entered."""
    game = _game(hand=["Forbidden Ritual"], opponent_hand=["Dodecapod"],
                 interactive=(1,))
    _put(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(0, "Forbidden Ritual", target_player_index=1).supported

    def discard_mode(game, choice):
        labels = list(choice.data.get("labels") or ())
        index = next(i for i, label in enumerate(labels) if "discard" in label)
        assert game.resolve_pending_choice("mode_choice", 1, mode_index=index)

    asked = settle(
        game, answers={"optional_pay": _accept, "mode_choice": discard_mode},
        defaults=False,
    )
    assert asked is not None and asked.kind == "discard", asked
    assert game.confirm_discard(1, [0])
    settle(game)

    opponent = game.players[1]
    assert _names(opponent.graveyard) == ["Dodecapod"]
    assert opponent.life == 20
    assert not any(p.card.name == "Dodecapod" for p in game.all_permanents())


def test_wrench_mind_s_decline_branch_is_an_effect_and_dodecapod_still_enters():
    """The other half of the same sentence: declining the artifact discard
    makes the player discard two cards, which **is** the spell's effect — so
    Dodecapod's replacement applies (the control the mark must not reach)."""
    game = _game(hand=["Wrench Mind"], opponent_hand=["Dodecapod", "Hill Giant"],
                 interactive=(1,))
    assert game.queue_from_hand(0, "Wrench Mind", target_player_index=1).supported

    asked = settle(game, answers={"optional_pay": _decline}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert asked.data.get("count") == 2
    assert game.confirm_discard(1, [0, 1])
    settle(game)

    assert any(p.card.name == "Dodecapod" for p in game.controlled_by(1))
    assert _names(game.players[1].graveyard) == ["Hill Giant"]


def test_psychic_purge_discarded_to_pay_chain_of_plasma_s_copy_costs_its_caster_nothing():
    """"Then that player … may discard a card. If the player does, they may
    copy this spell": the discard is CR 118.12's cost. Backwards: Psychic
    Purge's trigger made the Chain's caster lose 5 life."""
    game = _game(hand=["Chain of Plasma"], opponent_hand=["Psychic Purge"],
                 interactive=(1,))
    assert game.queue_from_hand(0, "Chain of Plasma", target_player_index=1).supported

    def decline_copy(game, choice):
        # The nested offer — copy the spell — is declined; only the discard is
        # under test.
        assert game.confirm_optional_pay(1, accept=False)

    asked = settle(game, answers={"optional_pay": _accept}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert game.confirm_discard(1, [0])
    settle(game, answers={"optional_pay": decline_copy})

    assert _names(game.players[1].graveyard) == ["Psychic Purge"]
    assert game.players[1].life == 17
    assert game.players[0].life == 20, game.log[-6:]


# --- what the mark must not reach --------------------------------------------


def test_nantuko_cultivator_s_discard_is_an_effect_and_still_offered_the_library_top():
    """"You may discard any number of land cards. Put that many +1/+1
    counters …" prints no "if you do": the discard is the effect, not a cost,
    and the Library's offer stands."""
    game = _game(hand=["Nantuko Cultivator", "Forest"], interactive=(0,))
    _put(game, 0, "Library of Leng")
    assert game.queue_from_hand(0, "Nantuko Cultivator").supported

    asked = settle(game, answers={"optional_pay": _accept}, defaults=False)
    assert asked is not None and asked.kind == "discard", asked
    assert asked.data.get("allow_top_of_library") is True
    assert not asked.data.get("_as_cost")


def test_a_cost_discard_is_still_a_discard_megrim_hears_it():
    """CR 701.9a: a cost discard is announced like any other — "Whenever an
    opponent discards a card, this enchantment deals 2 damage to that
    player" (Megrim) fires on Masticore's upkeep discard."""
    game = _game(opponent_hand=["Grizzly Bears", "Hill Giant"])
    _put(game, 0, "Megrim")
    _put(game, 1, "Masticore")
    _to_upkeep(game, seat=1)
    settle(game)

    opponent = game.players[1]
    assert len(opponent.graveyard) == 1
    assert opponent.life == 18
