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

    assert any("reveals their hand" in line for line in game.log), game.log


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


# --- H2: land denial and prohibitions (The Dark) ---


def test_cleansing_destroys_only_the_lands_nobody_paid_for(set_pool):
    """"For each land, destroy that land unless any player pays 1 life."

    The offer is per land and it goes round every seat, so both branches are in
    one cast: P1 buys its three Forests back at 1 life apiece, and P2's Swamp
    is destroyed because the seat that would want it cannot pay — the stated
    default never pays a seat down to nothing, and P1 will not spend life on
    somebody else's land.
    """
    game, players = _cast_from(set_pool, "Cleansing")
    lea = set_pool("LEA")
    players[0].battlefield = [Permanent(card=lea["Forest"]) for _ in range(3)]
    players[1].battlefield = [Permanent(card=lea["Swamp"])]
    players[1].life = 1
    game._sync_control()

    result = game.cast_from_hand(0, "Cleansing")

    assert result.supported, result.details
    assert len(players[0].battlefield) == 3, game.log
    assert players[1].battlefield == [], game.log
    assert players[1].graveyard[-1].name == "Swamp"
    # Three lands saved at 1 life apiece; the seat that could not pay paid
    # nothing.
    assert players[0].life == 17, game.log
    assert players[1].life == 1, game.log

# --- H4: per-seat damage state (The Dark) ---


def _resolve_with_prompts(game: Game) -> None:
    """Resolve the stack, answering every non-interactive seat's prompt as it
    is armed — what the game loop does for an AI or headless seat."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            game.resolve_top_of_stack()
        else:
            return


def test_mind_bomb_damages_each_player_by_what_that_player_kept(set_pool):
    """"Each player may discard up to three cards. Mind Bomb deals damage to
    each player equal to 3 minus the number of cards they discarded this way."

    Two seats, two different discards, two different numbers — which is the
    whole card. A single ``discarded_count`` for the resolution would let the
    seat that answered last decide everybody's damage.
    """
    game, players = _cast_from(set_pool, "Mind Bomb")
    lea = set_pool("LEA")
    # Three to give up, so the stated "up to N" policy takes all three.
    players[0].hand += [lea["Mountain"] for _ in range(3)]
    # One to give up, so this seat can only pay one of its three.
    players[1].hand = [lea["Island"]]

    result = game.cast_from_hand(0, "Mind Bomb")
    _resolve_with_prompts(game)

    assert result.supported, result.details
    assert players[0].life == 20, game.log
    assert players[1].life == 18, game.log
    assert players[0].hand == [] and players[1].hand == []


def test_mind_bomb_deals_the_printed_three_when_nobody_can_discard(set_pool):
    """3 minus nothing is 3. A seat with an empty hand is recorded as having
    discarded zero rather than left out of the record — a missing seat and a
    seat that discarded nothing are the same number, and it must be the one the
    card prints."""
    game, players = _cast_from(set_pool, "Mind Bomb")

    game.cast_from_hand(0, "Mind Bomb")
    _resolve_with_prompts(game)

    assert players[0].life == 17, game.log
    assert players[1].life == 17, game.log


# --- FixC: a sweep names a class, not a target ---
def _fixc_game(spell, theirs=()):
    """*spell* in seat 0's hand and *theirs* on seat 1's battlefield."""
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p1, p2


def test_tivadars_crusade_names_the_goblins_rather_than_one_of_them(set_pool):
    """"Destroy all Goblins." CR 115.1a: targeted only if the ability says
    "target", and it does not.

    The sweep's subtype rode a ``creature`` type_filter, which the target
    derivation read as a picker — so the browser asked for a creature and
    **refused the cast outright** when there was none to offer, which is
    exactly the board a player empties the Goblins from and then tries again.
    """
    lea = set_pool("LEA")
    game, _p1, p2 = _fixc_game(
        set_pool("DRK")["Tivadar's Crusade"],
        (lea["Goblin Balloon Brigade"], lea["Scathe Zombies"]),
    )

    assert game.cast_target_spec(0, set_pool("DRK")["Tivadar's Crusade"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Tivadar's Crusade")
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Scathe Zombies"]


def test_tivadars_crusade_casts_with_no_goblin_in_play(set_pool):
    """The board where the picker had nothing to offer and the client gave
    up. Nothing is destroyed and the spell still resolves."""
    game, _p1, _p2 = _fixc_game(set_pool("DRK")["Tivadar's Crusade"])

    result = game.cast_from_hand(0, "Tivadar's Crusade")
    game._settle()

    assert result.supported, result.details
    assert game.stack == []


def test_martyrs_cry_exiles_the_class_and_asks_for_nobody(set_pool):
    """"Exile all white creatures. For each creature exiled this way, its
    controller draws a card." The second sentence counts what the first swept,
    so nothing in the card is ever pointed at."""
    lea = set_pool("LEA")
    game, _p1, p2 = _fixc_game(
        set_pool("DRK")["Martyr's Cry"],
        (lea["Savannah Lions"], lea["Scathe Zombies"]),
    )

    assert game.cast_target_spec(0, set_pool("DRK")["Martyr's Cry"])[
        "requires_target"
    ] is False

    result = game.cast_from_hand(0, "Martyr's Cry")
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Scathe Zombies"]
    assert [c.name for c in p2.exile] == ["Savannah Lions"]
# --- end FixC ---
