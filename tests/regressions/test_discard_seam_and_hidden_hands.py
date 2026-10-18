"""A discard is one event, whichever of the engine's paths performs it.

Apocalypse's Dodecapod — "If a spell or ability an opponent controls causes you
to discard this card, put it onto the battlefield … instead" — is a CR 614
replacement on a discard that has to know **who caused it**, so it was driven
against every way a shipped card makes a player discard. Six of those ways
turned out not to be the discard seam at all, or to reach it having lost the
cause:

* **An opponent's pick out of a revealed hand** (Coercion, Mind Warp) asked for
  the cause under the wrong prompt kind and found none, so Psychic Purge's "when
  a spell or ability an opponent controls causes you to discard this card" had
  never fired for one — by a human caster or a default one.
* **The two "…discards it unless they pay N life" branches** (Wand of Ith,
  Sirocco) and **Breathstealer's Crypt's** moved the card to the graveyard
  without announcing a discard, so nothing watching one — Megrim, Psychic
  Purge — heard of it. **Balance's** hand half did the same, and so did
  **Circling Vultures'** special action.

And two shipped cards the same round's hand work read wrong:

* **Memory Jar's face-down hands were face up on the wire** to every viewer.
  The face-down record was linked to the Jar, and the Jar is sacrificed to pay
  for the ability — so the one scan that looks for it, over permanents on the
  battlefield, never found it (CR 406.3).
* **"Each opponent gains that much life" (Grollub) reached one opponent.** The
  quantifier of a life *gain* fell through to a single target, which in a duel
  is the same seat and at three seats is not.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.special_actions import take_special_action
from tests.helpers import resolve_stack

_HOMES = {
    "Forest": "LEA", "Island": "LEA", "Grizzly Bears": "LEA", "Counterspell": "LEA",
    "Terror": "LEA", "Giant Growth": "LEA", "Balance": "LEA", "Megrim": "STH",
    "Shock": "STH", "Coercion": "TMP", "Mind Warp": "ICE", "Psychic Purge": "LEG",
    "Wand of Ith": "DRK", "Sirocco": "MIR", "Breathstealer's Crypt": "VIS",
    "Circling Vultures": "WTH", "Memory Jar": "ULG", "Grollub": "EXO",
    "Dodecapod": "APC",
}


def _card(set_pool, name: str):
    return set_pool(_HOMES[name])[name]


def _table(set_pool, *, seats: int = 2, hand=(), opp_hand=(), library=(),
           interactive=()) -> Game:
    forest = _card(set_pool, "Forest")
    players = [PlayerState(name=f"P{seat}", library=[forest] * 12) for seat in range(seats)]
    players[0].hand = [_card(set_pool, n) for n in hand]
    players[1].hand = [_card(set_pool, n) for n in opp_hand]
    if library:
        players[0].library = [_card(set_pool, n) for n in library]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _put(game, set_pool, seat: int, name: str) -> Permanent:
    perm = Permanent(card=_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _settle(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    resolve_stack(game)


def _exile_on_the_wire(game, viewer, seat: int) -> list:
    from web.serialization import _serialize_player

    payload = _serialize_player(game.players[seat], viewer, seat, game)["exile"]
    return [entry if isinstance(entry, str) else entry["name"] for entry in payload]


# --- the cause of a discard an opponent picked ---------------------------------


@pytest.mark.parametrize("interactive", [(0, 1), ()])
def test_psychic_purge_triggers_when_an_opponents_coercion_takes_it(set_pool, interactive):
    """Coercion's caster chooses the card and its victim discards it: "a spell
    … an opponent controls causes you to discard this card", so its caster
    loses 5. It lost nothing, whoever answered the pick."""
    game = _table(
        set_pool, hand=["Psychic Purge", "Forest"], opp_hand=["Coercion"],
        interactive=interactive,
    )
    assert game.queue_from_hand(1, "Coercion", target_player_index=0).supported
    game.resolve_top_of_stack()
    if interactive:
        assert game.confirm_revealed_hand_pick(1, 0)
    _settle(game)

    assert _names(game.players[0].graveyard) == ["Psychic Purge"]
    assert game.players[1].life == 15, game.log


def test_the_second_card_mind_warp_takes_has_the_same_cause_as_the_first(set_pool):
    """"Choose X cards from it" is a chain of one-card picks, each armed by
    answering the one before — when nothing is resolving any more. The cause
    is carried down the chain, so the Purge taken second still knows who took
    it."""
    game = _table(
        set_pool, hand=["Forest", "Psychic Purge"], opp_hand=["Mind Warp"],
        interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Mind Warp", target_player_index=0, x_value=2).supported
    game.resolve_top_of_stack()
    assert game.confirm_revealed_hand_pick(1, 0)
    (second,) = game.pending_choices
    assert second.data.get("_cause_seat") == 1
    assert game.confirm_revealed_hand_pick(1, 0)
    _settle(game)

    assert game.players[0].hand == []
    assert game.players[1].life == 15, game.log


# --- discards that did not announce themselves -----------------------------------


@pytest.mark.parametrize("held, expected", [
    # Megrim alone: its controller's Wand made an opponent discard.
    ("Grizzly Bears", {"lives": [20, 18], "graveyard": ["Grizzly Bears"], "board": []}),
    # …and the discarded card's own trigger (CR 113.6).
    ("Psychic Purge", {"lives": [15, 18], "graveyard": ["Psychic Purge"], "board": []}),
    # …and its own replacement (CR 614).
    ("Dodecapod", {"lives": [20, 18], "graveyard": [], "board": ["Dodecapod"]}),
])
def test_a_card_discarded_to_wand_of_ith_is_discarded(set_pool, held, expected):
    """"…that player discards it unless they pay 1 life." Declined, that is a
    discard an opponent's ability caused — and it was a bare move to the
    graveyard, made under a context whose controller had been swapped for the
    paying seat."""
    game = _table(set_pool, opp_hand=[held], interactive=(0, 1))
    _put(game, set_pool, 0, "Wand of Ith")
    _put(game, set_pool, 0, "Megrim")
    game.active_player_index = 0

    assert game.activate_permanent_ability(0, "Wand of Ith", target_player_index=1).supported
    (offer,) = game.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 1)
    assert game.confirm_optional_pay(1, accept=False)
    _settle(game)

    assert [p.life for p in game.players] == expected["lives"], game.log
    assert _names(game.players[1].graveyard) == expected["graveyard"]
    assert _names(game.controlled_by(1)) == expected["board"]


def test_a_card_discarded_to_sirocco_is_discarded(set_pool):
    game = _table(
        set_pool, hand=["Sirocco"], opp_hand=["Counterspell", "Forest"],
        interactive=(0, 1),
    )
    _put(game, set_pool, 0, "Megrim")

    assert game.queue_from_hand(0, "Sirocco", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(1, accept=False)
    _settle(game)

    assert _names(game.players[1].graveyard) == ["Counterspell"]
    assert game.players[1].life == 18, game.log


def test_a_card_discarded_to_breathstealers_crypt_is_discarded_and_knows_whose_crypt(
    set_pool,
):
    """"If it's a creature card, that player discards it unless they pay 3
    life." The Crypt's controller is who causes that (CR 109.5) — nobody is
    resolving anything when a draw step's draw is replaced — so an opponent's
    Crypt puts a Dodecapod onto the battlefield and one's own does not."""
    game = _table(set_pool, library=["Grizzly Bears"] * 3, interactive=(0, 1))
    _put(game, set_pool, 1, "Breathstealer's Crypt")
    _put(game, set_pool, 1, "Megrim")
    game._draw_with_replacements(game.players[0], 1)
    assert game.confirm_discard_unless_pay_life(0, accept=False)
    _settle(game)
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert game.players[0].life == 18, game.log

    for crypt_seat, board in ((1, ["Dodecapod"]), (0, ["Breathstealer's Crypt"])):
        game = _table(set_pool, library=["Dodecapod"] * 3, interactive=(0, 1))
        _put(game, set_pool, crypt_seat, "Breathstealer's Crypt")
        game._draw_with_replacements(game.players[0], 1)
        assert game.confirm_discard_unless_pay_life(0, accept=False)
        _settle(game)
        assert _names(game.controlled_by(0)) == board, (crypt_seat, game.log)


def test_the_cards_balance_takes_from_a_hand_are_discarded(set_pool):
    """"Players **discard** cards … the same way." Two cards leave the fuller
    hand, and a Megrim across the table deals 2 for each."""
    game = _table(set_pool, hand=["Balance"], opp_hand=["Forest", "Island"])
    _put(game, set_pool, 0, "Megrim")

    assert game.queue_from_hand(0, "Balance").supported
    _settle(game)

    assert game.players[1].hand == []
    assert sorted(_names(game.players[1].graveyard)) == ["Forest", "Island"]
    assert game.players[1].life == 16, game.log


def test_circling_vultures_discarding_itself_is_a_discard(set_pool):
    """CR 116.2e's special action is still CR 701.9a's discard: the opponent's
    Megrim sees it. It uses no stack and is caused by nothing, so the card
    simply goes to the graveyard."""
    game = _table(set_pool, hand=["Circling Vultures"])
    _put(game, set_pool, 1, "Megrim")
    game.priority_player_index = 0

    assert take_special_action(
        game, 0, _card(set_pool, "Circling Vultures"), "discard_from_hand",
    ) is None
    _settle(game)

    assert _names(game.players[0].graveyard) == ["Circling Vultures"]
    assert game.players[0].life == 18, game.log


# --- Memory Jar's hands ------------------------------------------------------------


def test_memory_jars_exiled_hands_are_face_down_to_every_viewer(set_pool):
    """"Each player exiles all cards from their hand **face down**." The Jar
    is in the graveyard by then — it paid for the ability — so the record
    cannot live only on it. Hidden from the opponent, the owner and a
    spectator; returned at the end step; and never named in the log."""
    game = _table(set_pool, hand=["Terror", "Giant Growth"], opp_hand=["Counterspell"])
    _put(game, set_pool, 0, "Memory Jar")

    assert game.activate_permanent_ability(0, "Memory Jar").supported
    _settle(game)
    assert _names(game.players[0].graveyard) == ["Memory Jar"]
    assert _names(game.players[0].exile) == ["Terror", "Giant Growth"]
    for viewer in (0, 1, None):
        assert _exile_on_the_wire(game, viewer, 0) == ["<hidden>", "<hidden>"], viewer
        assert _exile_on_the_wire(game, viewer, 1) == ["<hidden>"], viewer

    game.resolve_end_step(0)
    _settle(game)

    assert _names(game.players[0].hand) == ["Terror", "Giant Growth"]
    assert _names(game.players[1].hand) == ["Counterspell"]
    assert game.players[0].exile == [] and game.players[1].exile == []
    assert len(game.players[0].graveyard) == 8, "the Jar and the seven it drew"
    hidden_names = ("Terror", "Giant Growth", "Counterspell")
    assert [l for l in game.log if any(n in l for n in hidden_names)] == []


# --- each opponent gains ------------------------------------------------------------


@pytest.mark.parametrize("seats, lives", [(2, [20, 22]), (3, [20, 22, 22])])
def test_grollub_pays_each_opponent_the_damage_it_is_dealt(set_pool, seats, lives):
    """"Whenever this creature is dealt damage, **each opponent** gains that
    much life." Shocked for 2, every opponent of its controller gains 2 — at
    three seats the second one used to gain nothing."""
    game = _table(set_pool, seats=seats, opp_hand=["Shock"])
    grollub = _put(game, set_pool, 0, "Grollub")

    assert game.queue_from_hand(1, "Shock", target_permanent_ids=[grollub.permanent_id]).supported
    _settle(game)

    assert [p.life for p in game.players] == lives, game.log
