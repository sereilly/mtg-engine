"""Per-card tests for The Dark's sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import random

from engine import Game, PlayerState
from engine.models import Permanent


# --- G1: damage family (The Dark) ---


def _cast_from(set_pool, name: str, *, seats: int = 2):
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [set_pool("DRK")[name]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def test_eternal_flame_halves_only_the_damage_it_deals_its_caster(set_pool):
    """"X damage to target opponent … and half X damage, rounded up, to you,
    where X is the number of Mountains you control." Three Mountains is 3 to
    the opponent and 2 to the caster — one where-clause, spent twice, and only
    one of the two halved."""
    game, players = _cast_from(set_pool, "Eternal Flame")
    lea = set_pool("LEA")
    players[0].battlefield = [Permanent(card=lea["Mountain"]) for _ in range(3)]
    game._sync_control()

    result = game.cast_from_hand(0, "Eternal Flame", target_player_index=1)

    assert result.supported, result.details
    assert players[1].life == 17, game.log
    assert players[0].life == 18, game.log


def test_eternal_flame_with_no_mountains_deals_nothing_either_way(set_pool):
    """The where-clause is counted at resolution (CR 608.2), and an X of 0 is
    an event CR 120.8 says never happens — on both halves."""
    game, players = _cast_from(set_pool, "Eternal Flame")

    game.cast_from_hand(0, "Eternal Flame", target_player_index=1)

    assert [p.life for p in players] == [20, 20], game.log


def test_eternal_flame_offers_no_seat_but_the_opponent(set_pool):
    """"target **opponent** or planeswalker" is the "target player or
    planeswalker" union with the caster's own seat struck out (CR 115.4). The
    narrowing used to be dropped when the "or planeswalker" half was read, so
    the picker offered the caster.

    Asked of the picker rather than of a cast: a spell that can target a player
    is one of the shapes `legality.cast_target_refusal` deliberately declines
    today (ROADMAP.md), so the enumeration is where the narrowing bites.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    game, players = _cast_from(set_pool, "Eternal Flame", seats=3)
    card = set_pool("DRK")["Eternal Flame"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec is not None and spec["kind"] == "player_or_planeswalker"
    offered = game._enumerate_targets(0, card, spec, for_cast=True)

    assert sorted(entry["seat"] for entry in offered) == [1, 2], offered


def test_ashes_to_ashes_exiles_both_creatures_and_burns_its_caster(set_pool):
    """"Exile **two target** nonartifact creatures." A one-target reading exiled
    the first and dropped the second while the card reported supported."""
    game, players = _cast_from(set_pool, "Ashes to Ashes")
    lea = set_pool("LEA")
    players[1].battlefield = [
        Permanent(card=lea["Grizzly Bears"]), Permanent(card=lea["Savannah Lions"])
    ]
    game._sync_control()
    ids = [perm.permanent_id for perm in players[1].battlefield]

    result = game.cast_from_hand(0, "Ashes to Ashes", target_permanent_ids=ids)

    assert result.supported, result.details
    assert players[1].battlefield == [], game.log
    assert sorted(card.name for card in players[1].exile) == [
        "Grizzly Bears", "Savannah Lions"
    ]
    assert players[0].life == 15, game.log


def test_ashes_to_ashes_will_not_exile_an_artifact_creature(set_pool):
    """"nonartifact" is a narrowing the picker enforces; without it the spell
    is a strictly larger removal."""
    game, players = _cast_from(set_pool, "Ashes to Ashes")
    atq = set_pool("ATQ")
    players[1].battlefield = [
        Permanent(card=atq["Clay Statue"]), Permanent(card=atq["Clay Statue"])
    ]
    game._sync_control()
    ids = [perm.permanent_id for perm in players[1].battlefield]

    game.cast_from_hand(0, "Ashes to Ashes", target_permanent_ids=ids)

    assert len(players[1].battlefield) == 2, game.log
    assert players[1].exile == []


def test_inquisition_damage_is_the_white_cards_in_the_revealed_hand(set_pool):
    """"damage to that player equal to the number of **white** cards in their
    hand" — the colour is read off the printed mana cost (CR 202.2), which a
    card in a hand has as much as one on the battlefield."""
    game, players = _cast_from(set_pool, "Inquisition")
    lea = set_pool("LEA")
    players[1].hand = [
        lea["Savannah Lions"], lea["Healing Salve"],   # white
        lea["Grizzly Bears"], lea["Mountain"],         # not
    ]

    result = game.cast_from_hand(0, "Inquisition", target_player_index=1)

    assert result.supported, result.details
    assert players[1].life == 18, game.log


def test_inquisition_reveals_the_hand_it_counts(set_pool):
    """The first sentence is what makes the count public (CR 701.20). It is a
    real step, not decoration: the log names the cards."""
    game, players = _cast_from(set_pool, "Inquisition")
    players[1].hand = [set_pool("LEA")["Savannah Lions"]]

    game.cast_from_hand(0, "Inquisition", target_player_index=1)

    assert any("revealed their hand" in line for line in game.log), game.log


def test_inquisition_counts_the_targeted_players_hand_not_the_casters(set_pool):
    """"their hand" is the revealed one. Counted on the caster's hand instead,
    a white-heavy caster would burn an opponent holding nothing."""
    game, players = _cast_from(set_pool, "Inquisition")
    players[0].hand.extend([set_pool("LEA")["Savannah Lions"]] * 3)

    game.cast_from_hand(0, "Inquisition", target_player_index=1)

    assert players[1].life == 20, game.log


def test_mana_clash_repeats_until_both_coins_come_up_heads(set_pool):
    """The third sentence is the effect: the loop runs until *both* coins are
    heads on the same flip, so the log's last round is the only one with no
    damage in it. Seeded, because the RNG is the module-level one a simulation
    seeds (CR 705.1)."""
    game, players = _cast_from(set_pool, "Mana Clash")
    random.seed(10)

    result = game.cast_from_hand(0, "Mana Clash", target_player_index=1)

    assert result.supported, result.details
    rounds = [line for line in game.log if "flipped" in line]
    assert rounds, game.log
    assert "heads" in rounds[-1].split("flipped")[1]
    assert "heads" in rounds[-1].split("flipped")[2]
    assert players[0].life + players[1].life < 40, game.log


def test_mana_clash_damages_only_the_seat_whose_coin_came_up_tails(set_pool):
    """Two coins a round, one per player — "both players' coins". One flip read
    twice would make the two seats always take damage together."""
    game, players = _cast_from(set_pool, "Mana Clash")
    random.seed(3)

    game.cast_from_hand(0, "Mana Clash", target_player_index=1)

    tails = [line for line in game.log if "flipped" in line]
    caster_tails = sum(1 for line in tails if "tails" in line.split("flipped")[1])
    opponent_tails = sum(1 for line in tails if "tails" in line.split("flipped")[2])
    assert 20 - players[0].life == caster_tails, game.log
    assert 20 - players[1].life == opponent_tails, game.log
