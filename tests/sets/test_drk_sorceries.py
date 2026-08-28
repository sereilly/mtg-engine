"""Per-card tests for The Dark's sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G5: zones and characteristics (The Dark) ---------------------------------


def _two_seats(set_pool, spell: str, *, p1_extra=(), p2_board=(), p2_hand=()):
    pool = set_pool("DRK")
    p1 = PlayerState(name="P1", hand=[pool[spell], *p1_extra])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool[name]) for name in p2_board],
        hand=[pool[name] for name in p2_hand],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_dust_to_dust_exiles_both_named_artifacts(set_pool):
    """"Exile **two** target artifacts." Two slots, both resolved — a lowering
    that dropped the count would exile one and still report the card
    supported."""
    game, p1, p2 = _two_seats(
        set_pool, "Dust to Dust", p2_board=["Fellwar Stone", "Living Armor"],
    )
    ids = [perm.permanent_id for perm in p2.battlefield]

    result = game.cast_from_hand(
        0, "Dust to Dust", target_player_index=1, target_permanent_ids=ids,
    )

    assert result.supported, result.details
    assert p2.battlefield == [], game.log
    assert {card.name for card in p2.exile} == {"Fellwar Stone", "Living Armor"}


def test_dust_to_dust_exiles_only_what_was_named(set_pool):
    """The control on the test above: two targets, not a sweep. It would pass
    against a handler that exiled every artifact on the board, which is what a
    lowering onto the `exile_all_matching` sweep would have produced."""
    game, p1, p2 = _two_seats(
        set_pool,
        "Dust to Dust",
        p2_board=["Fellwar Stone", "Living Armor", "Wand of Ith"],
    )
    named = [perm.permanent_id for perm in p2.battlefield[:2]]

    game.cast_from_hand(
        0, "Dust to Dust", target_player_index=1, target_permanent_ids=named,
    )

    assert [perm.card.name for perm in p2.battlefield] == ["Wand of Ith"], game.log


def test_amnesia_empties_the_hand_of_everything_but_land(set_pool):
    """"…reveals their hand and discards all nonland cards." Nobody chooses, so
    every matching card goes and the lands stay."""
    game, p1, p2 = _two_seats(
        set_pool, "Amnesia", p2_hand=["Fellwar Stone", "City of Shadows", "Rag Man"],
    )

    result = game.cast_from_hand(0, "Amnesia", target_player_index=1)

    assert result.supported, result.details
    assert [card.name for card in p2.hand] == ["City of Shadows"], game.log
    assert {card.name for card in p2.graveyard} == {"Fellwar Stone", "Rag Man"}


def test_amnesia_reveals_the_hand_before_it_empties_it(set_pool):
    """CR 701.16. The reveal is its own step and reaches the feed the client
    reads, not only the prose log — a discard nobody could watch is the half of
    this card that makes it verifiable."""
    game, p1, p2 = _two_seats(set_pool, "Amnesia", p2_hand=["Rag Man"])

    game.cast_from_hand(0, "Amnesia", target_player_index=1)

    revealed = [event for event in game.reveal_events if event["seat"] == 1]
    assert revealed and "Rag Man" in revealed[-1]["cards"], game.reveal_events


def test_martyrs_cry_exiles_the_white_creatures_and_pays_their_controllers(set_pool):
    """"Exile all white creatures. For each creature exiled this way, **its
    controller** draws a card." The draw is owed to the seat that lost the
    creature, which by then is a seat no board read can find."""
    pool = set_pool("DRK")
    white = Permanent(card=pool["Martyr's Cry"])   # placeholder, replaced below
    p1 = PlayerState(name="P1", hand=[pool["Martyr's Cry"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool["Angry Mob"])],
        library=[pool["Rag Man"], pool["Fellwar Stone"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    assert "W" in pool["Angry Mob"].colors, "the fixture needs a white creature"

    result = game.cast_from_hand(0, "Martyr's Cry")

    assert result.supported, result.details
    assert p2.battlefield == [], game.log
    assert len(p2.hand) == 1, game.log
    assert p1.hand == [], "the caster controlled none of them, so draws nothing"


def test_martyrs_cry_leaves_a_creature_of_another_color_alone(set_pool):
    """The control: the sweep is narrowed by colour, and the draw is per
    creature exiled rather than a flat one."""
    pool = set_pool("DRK")
    p1 = PlayerState(name="P1", hand=[pool["Martyr's Cry"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool["Rag Man"])],
        library=[pool["Fellwar Stone"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    assert "W" not in pool["Rag Man"].colors

    game.cast_from_hand(0, "Martyr's Cry")

    assert [perm.card.name for perm in p2.battlefield] == ["Rag Man"]
    assert p2.hand == [], game.log
