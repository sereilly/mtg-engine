"""Per-card tests for Legends' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState


# ---------------------------------------------------------------------------
# Syphon Soul (round 20) — "each other player", and the life the sweep produced
# ---------------------------------------------------------------------------


def _syphon(set_pool, seats: int):
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [set_pool("LEG")["Syphon Soul"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def test_syphon_soul_burns_the_opponent_and_gains_that_much(set_pool):
    """The duel reading: 2 damage to the one other player, 2 life back."""
    game, players = _syphon(set_pool, 2)

    result = game.cast_from_hand(0, "Syphon Soul")

    assert result.supported, result.details
    assert players[1].life == 18
    assert players[0].life == 22, game.log


def test_the_life_gained_is_the_total_damage_the_sweep_dealt(set_pool):
    """"Equal to the damage dealt this way" is about the whole effect, not
    about one event: three seats means two damage events and four life. A
    back-reference that read only the last one would gain 2 here and pass the
    duel test above, which is why the multiplayer board is the real check."""
    game, players = _syphon(set_pool, 3)

    result = game.cast_from_hand(0, "Syphon Soul")

    assert result.supported, result.details
    assert [p.life for p in players] == [24, 18, 18], game.log


def test_syphon_soul_never_damages_its_own_caster(set_pool):
    """"Each **other** player" excludes the controller — the seat that gains
    the life. Read as "each player" the caster would take 2 and net +2."""
    game, players = _syphon(set_pool, 3)

    game.cast_from_hand(0, "Syphon Soul")

    assert players[0].life == 24


# ---------------------------------------------------------------------------
# Jovial Evil (round 20) — a count on the targeted player's board, doubled
# ---------------------------------------------------------------------------


def _jovial(set_pool, victim_names: list[str]):
    from engine.models import Permanent

    leg, lea = set_pool("LEG"), set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[leg["Jovial Evil"]], life=20)
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=lea[name]) for name in victim_names],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_jovial_evil_deals_twice_the_white_creatures_that_player_controls(set_pool):
    """Two white creatures and one green one: X is 2, the damage is 4."""
    game, p1, p2 = _jovial(
        set_pool, ["Savannah Lions", "Benalish Hero", "Grizzly Bears"]
    )

    result = game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert result.supported, result.details
    assert p2.life == 16, game.log


def test_the_multiplier_is_not_a_second_name_for_the_count(set_pool):
    """The control on "twice": one white creature is 2 damage, not 1. A parse
    that consumed the word and lowered a plain count would pass every test that
    happens to stand on an even board."""
    game, p1, p2 = _jovial(set_pool, ["Savannah Lions"])

    game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert p2.life == 18, game.log


def test_the_count_is_taken_on_the_targeted_players_board(set_pool):
    """"That player controls" is the opponent the spell targeted, not the
    caster: a count taken on the wrong battlefield reads the caster's white
    creatures and deals nothing here."""
    from engine.models import Permanent

    game, p1, p2 = _jovial(set_pool, [])
    p1.battlefield = [Permanent(card=set_pool("LEA")["Savannah Lions"])]

    game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert p2.life == 20, game.log
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Cleanse (round 20) — the colour a type-keyed sweep used to drop
# ---------------------------------------------------------------------------


def test_cleanse_destroys_only_the_black_creatures(set_pool):
    """"Destroy all **black** creatures" compiled onto `destroy_all_creatures`,
    whose payload is empty and whose scope is its own kind — so the colour was
    dropped and Cleanse wiped the board. A sweep that names a narrowing the
    handler cannot carry is a card that does strictly more than it prints."""
    from engine.models import Permanent

    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Cleanse"]])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Bog Wraith"]),      # black
        Permanent(card=lea["Grizzly Bears"]),   # green
    ])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Cleanse")

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Grizzly Bears"], game.log


# ---------------------------------------------------------------------------
# Hellfire (round 20) — "X plus 3", where X is what the sweep just killed
# ---------------------------------------------------------------------------


def _hellfire(set_pool, mine: list[str], theirs: list[str]):
    from engine.models import Permanent

    lea = set_pool("LEA")
    p1 = PlayerState(
        name="P1", life=20, hand=[set_pool("LEG")["Hellfire"]],
        battlefield=[Permanent(card=lea[name]) for name in mine],
    )
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=lea[name]) for name in theirs],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_hellfire_spares_the_black_creatures_and_burns_for_the_rest_plus_three(set_pool):
    """Three nonblack creatures die, so X is 3 and the caster takes 6. The
    black Wraith is untouched — and is also not counted."""
    game, p1, p2 = _hellfire(
        set_pool, ["Savannah Lions"], ["Bog Wraith", "Grizzly Bears", "Hill Giant"]
    )

    result = game.cast_from_hand(0, "Hellfire")

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Bog Wraith"], game.log
    assert p1.battlefield == []
    assert p1.life == 14, game.log


def test_the_three_is_dealt_even_when_nothing_died(set_pool):
    """"X plus 3" on an empty board is 3, not 0 — the control on folding the
    constant into the count, and on a count that silently answered zero."""
    game, p1, p2 = _hellfire(set_pool, [], ["Bog Wraith"])

    game.cast_from_hand(0, "Hellfire")

    assert [p.card.name for p in p2.battlefield] == ["Bog Wraith"]
    assert p1.life == 17, game.log


def test_the_damage_counts_the_deaths_rather_than_the_survivors(set_pool):
    """"Creatures that died this way" is the opposite set from the noun phrase
    read plainly: one nonblack creature beside two black ones is 1 + 3 = 4, and
    a count taken off the board afterwards would read 2 and deal 5."""
    game, p1, p2 = _hellfire(
        set_pool, [], ["Bog Wraith", "Scathe Zombies", "Grizzly Bears"]
    )

    game.cast_from_hand(0, "Hellfire")

    assert sorted(p.card.name for p in p2.battlefield) == [
        "Bog Wraith", "Scathe Zombies",
    ]
    assert p1.life == 16, game.log
