"""Per-card tests for Legends' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition


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


# ---------------------------------------------------------------------------
# Winds of Change (round 21) — "each player shuffles the cards from their hand
# into their library, then draws that many cards". CR 701.19, CR 121.
# ---------------------------------------------------------------------------


def _blank(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def _winds(set_pool, first_hand: int, second_hand: int):
    p1 = PlayerState(
        name="P1",
        hand=[set_pool("LEG")["Winds of Change"]]
        + [_blank(f"A{i}") for i in range(first_hand)],
        library=[_blank(f"L{i}") for i in range(20)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[_blank(f"B{i}") for i in range(second_hand)],
        library=[_blank(f"M{i}") for i in range(20)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_every_hand_is_refilled_to_the_size_it_had(set_pool):
    """"That many" is each player's own hand size, not the caster's — two seats
    with different hands each end with what they started with."""
    game, p1, p2 = _winds(set_pool, first_hand=2, second_hand=5)

    result = game.cast_from_hand(0, "Winds of Change")
    game._settle()

    assert result.supported, result.details
    # The spell itself left the hand to go on the stack, so P1 shuffled 2.
    assert len(p1.hand) == 2, game.log
    assert len(p2.hand) == 5, game.log


def test_the_old_hands_went_into_the_libraries_rather_than_away(set_pool):
    """A shuffle-into is a move, and the cards have to still be there — a
    handler that cleared the hand and drew would pass every count above."""
    game, p1, p2 = _winds(set_pool, first_hand=2, second_hand=5)

    game.cast_from_hand(0, "Winds of Change")
    game._settle()

    everywhere = {card.name for card in p1.hand + p1.library}
    assert {"A0", "A1"} <= everywhere, game.log
    assert len(p1.library) == 20
    assert len(p2.library) == 20


def test_an_empty_hand_still_shuffles_the_library_and_draws_nothing(set_pool):
    """Zero is a number, and the shuffle is not conditional on it: the seat with
    nothing in hand shuffles its library all the same (that is the printed
    action), and draws none — the library keeps every card it had."""
    game, p1, p2 = _winds(set_pool, first_hand=0, second_hand=0)
    before = sorted(card.name for card in p2.library)

    game.cast_from_hand(0, "Winds of Change")
    game._settle()

    assert p2.hand == []
    assert sorted(card.name for card in p2.library) == before, game.log
    assert len(p2.library) == 20


# ---------------------------------------------------------------------------
# Visions (round 21) — look at the top five cards of a library you do not own,
# then offer its owner's shuffle. CR 701.19.
# ---------------------------------------------------------------------------


def _visions(set_pool, library: int = 8):
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Visions"]])
    p2 = PlayerState(name="P2", library=[_blank(f"L{i}") for i in range(library)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, p1, p2


def test_visions_shows_the_caster_the_top_five_of_the_target_s_library(set_pool):
    """The prompt is raised in front of the *caster* and reads the *target's*
    library — the two seats a look at someone else's deck can confuse."""
    game, p1, p2 = _visions(set_pool)

    result = game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    pending = game.pending_reorder_library
    assert pending is not None, game.log
    assert pending["caster_index"] == 0
    assert pending["target_index"] == 1
    assert pending["top_count"] == 5
    assert pending["may_shuffle"] is True


def test_visions_cannot_rearrange_what_it_looked_at(set_pool):
    """Visions only *looks*. The permission is enforced in the engine rather
    than by hiding the drag handles, so an answer that names another order
    leaves the library exactly as it was."""
    game, p1, p2 = _visions(set_pool)
    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()
    before = [card.name for card in p2.library]

    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0], shuffle=False)

    assert [card.name for card in p2.library] == before, game.log


def test_visions_shuffles_the_library_it_looked_at_when_the_caster_says_so(set_pool):
    """The offer is the second half of the printed sentence, and the library it
    shuffles is the target's — the caster's is untouched."""
    game, p1, p2 = _visions(set_pool)
    p1.library = [_blank(f"K{i}") for i in range(6)]
    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()
    theirs = [card.name for card in p2.library]
    mine = [card.name for card in p1.library]

    assert game.confirm_reorder_library(0, [0, 1, 2, 3, 4], shuffle=True)

    assert sorted(card.name for card in p2.library) == sorted(theirs)
    assert [card.name for card in p2.library] != theirs, game.log
    assert [card.name for card in p1.library] == mine


def test_visions_looks_at_a_short_library_without_reaching_past_it(set_pool):
    """Fewer than five cards is not a failure — the look stops at what is
    there, the way a mill does (CR 704.5b is about drawing, not looking)."""
    game, p1, p2 = _visions(set_pool, library=2)

    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()

    assert game.pending_reorder_library["top_count"] == 2, game.log
