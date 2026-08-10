"""Per-card tests for Limited Edition Alpha's sorcery cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
import json
from web.app import app, store
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)
from tests.sets.lea_helpers import (
    _forest,
    _grizzly,
    _island,
    _mountain,
    _plains,
    _start_session_with_p0_graveyard,
    _swamp,
)


def test_flashfires_destroys_only_plains(all_cards):
    flash = _get(all_cards, "Flashfires")
    plains = _get(all_cards, "Plains")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[flash])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p1.battlefield.append(Permanent(mountain))
    p2.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(mountain))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Flashfires", target_player_index=1)

    assert result.supported
    # Plains should be destroyed on both sides; mountains should remain
    assert all(perm.card.primary_type != "land" or "plains" not in perm.card.type_line.lower() for perm in p1.battlefield)
    assert any("mountain" in perm.card.type_line.lower() for perm in p1.battlefield)
    assert all(perm.card.primary_type != "land" or "plains" not in perm.card.type_line.lower() for perm in p2.battlefield)
    assert any("mountain" in perm.card.type_line.lower() for perm in p2.battlefield)


def test_ice_storm_destroys_selected_target_land(all_cards):
    ice_storm = _get(all_cards, "Ice Storm")
    island = _get(all_cards, "Island")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[ice_storm])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=island))
    p2.battlefield.append(Permanent(card=mountain))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0,
        "Ice Storm",
        target_player_index=1,
        target_permanent_index=1,
    )

    assert result.supported
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Island"
    assert p2.graveyard
    assert p2.graveyard[0].name == "Mountain"


def test_braingeyser_draws_x_cards(all_cards):
    braingeyser = _get(all_cards, "Braingeyser")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[braingeyser])
    p2 = PlayerState(name="P2", library=[island, island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=4)

    assert result.supported
    assert len(p2.hand) == 4


def test_fireball_divides_damage_evenly_rounded_down(all_cards):
    # X damage split evenly (rounded down) among the chosen targets.
    fireball = _get(all_cards, "Fireball")
    a = _mk_card("Grizzly", "Creature — Bear")  # 2/2 default
    b = _mk_card("Hill Giant", "Creature — Giant")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=a), Permanent(card=b)])
    game = Game(players=[p1, p2])

    # X=5 over 2 targets => 2 damage each (rounded down); both 2/2s die.
    result = game.cast_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=5
    )

    assert result.supported
    assert not p2.battlefield


def test_fireball_all_damage_to_a_single_player(all_cards):
    fireball = _get(all_cards, "Fireball")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=6)

    assert result.supported
    assert p2.life == 14


def test_fireball_costs_one_more_for_each_target_beyond_the_first(all_cards):
    # {X}{R}; two targets cost {1} more, so X=4 at two targets needs R+4+1 = 6.
    fireball = _get(all_cards, "Fireball")
    targets = [Permanent(card=_mk_card(f"Goblin{i}", "Creature — Goblin")) for i in range(2)]

    # 6 mana available: cast succeeds and empties the pool.
    p1 = PlayerState(name="P1", hand=[fireball],
                     mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 5})
    p2 = PlayerState(name="P2", battlefield=list(targets))
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    ok = game.queue_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=4
    )
    assert ok.supported
    assert sum(p1.mana_pool.values()) == 0

    # Only 5 mana (R+4): the extra-target tax makes the two-target cast unaffordable.
    p1b = PlayerState(name="P1", hand=[fireball],
                      mana_pool={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 4})
    p2b = PlayerState(
        name="P2",
        battlefield=[Permanent(card=_mk_card(f"Goblin{i}", "Creature — Goblin")) for i in range(2)],
    )
    gameb = Game(players=[p1b, p2b], enforce_mana_costs=True)
    fail = gameb.queue_from_hand(
        0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=4
    )
    assert not fail.supported


def test_wheel_of_fortune_discards_then_draws(all_cards):
    wheel = _get(all_cards, "Wheel of Fortune")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wheel of Fortune", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7


def test_timetwister_resets_and_draws_seven(all_cards):
    twister = _get(all_cards, "Timetwister")
    island = _get(all_cards, "Island")
    bear = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[twister, island], graveyard=[bear], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island], graveyard=[bear], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Timetwister", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7


def test_demonic_tutor_puts_library_card_into_hand(all_cards):
    tutor = _get(all_cards, "Demonic Tutor")
    mountain = _get(all_cards, "Mountain")
    forest = _get(all_cards, "Forest")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[tutor], library=[mountain, forest, island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

    assert result.supported
    assert game.pending_search_library is not None
    assert game.pending_search_library["count"] == 1
    assert game.pending_search_library["card_type"] == "any"

    # Player searches and picks Island (originally at library index 2)
    confirmed = game.confirm_search_library(0, 2)
    assert confirmed
    assert any(card.name == "Island" for card in p1.hand)
    assert game.pending_search_library is None


def test_time_walk_grants_extra_turn(all_cards):
    time_walk = _get(all_cards, "Time Walk")
    p1 = PlayerState(name="P1", hand=[time_walk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Time Walk", target_player_index=0)

    assert result.supported
    assert game.extra_turns.get(0, 0) == 1


def test_balance_equalizes_lands_creatures_and_hand(all_cards):
    balance = _get(all_cards, "Balance")
    plains = _get(all_cards, "Plains")
    bear = _mk_card("Bear", "Creature — Bear")
    elf = _mk_card("Elf", "Creature — Elf")

    p1 = PlayerState(
        name="P1",
        hand=[balance, plains, plains],
        battlefield=[Permanent(card=plains), Permanent(card=plains), Permanent(card=bear)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[plains],
        battlefield=[Permanent(card=plains), Permanent(card=elf), Permanent(card=elf)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Balance", target_player_index=1)
    game.auto_resolve_pending_balance()  # each player chooses; auto for headless

    assert result.supported
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "creature") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "creature") == 1
    assert len(p1.hand) == len(p2.hand)


def test_contract_from_below_discards_hand_then_draws_seven(all_cards):
    contract = _get(all_cards, "Contract from Below")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[contract, island], library=[island] * 10)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Contract from Below", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7


def test_demonic_attorney_antes_top_card_for_each_player(all_cards):
    attorney = _get(all_cards, "Demonic Attorney")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[attorney], library=[island, island])
    p2 = PlayerState(name="P2", library=[island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Attorney", target_player_index=1)

    assert result.supported
    assert len(p1.library) == 1
    assert len(p2.library) == 1


def test_stream_of_life_defaults_to_self_target():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4038,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][1]["life"] == 20
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])


def test_stream_of_life_x_spends_generic_mana_from_pool():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4043,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 1, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["mana_pool"]["B"] == 0


def test_stream_of_life_updates_life_total_and_log_in_response():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4040,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert payload["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in payload["log"])


def test_disintegrate_deals_damage_to_targeted_creature(all_cards):
    """Disintegrate with X=3 targeting a creature should deal 3 damage to that creature."""
    disintegrate = _get(all_cards, "Disintegrate")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[disintegrate])
    p2 = PlayerState(name="P2", battlefield=[bear_perm])
    game = Game(players=[p1, p2])

    initial_life = p2.life
    result = game.cast_from_hand(
        0, "Disintegrate",
        target_player_index=1,
        target_permanent_index=0,
        x_value=3,
    )
    assert result.supported
    # Creature should be gone (dead or exiled after taking 3 damage)
    assert not p2.battlefield, "2/2 creature should be removed after taking 3 damage from Disintegrate"
    # Player life should be unchanged (damage went to creature, not player)
    assert p2.life == initial_life


def test_channel_sets_active_flag_and_use_channel_mana_pays_life(all_cards):
    channel = _get(all_cards, "Channel")
    p1 = PlayerState(name="P1", hand=[channel], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Channel", target_player_index=0)

    assert result.supported
    assert p1.channel_active_until_eot is True

    use_result = game.use_channel_mana(0, 7)
    assert use_result.supported
    assert p1.life == 13
    assert p1.mana_pool["C"] == 7


def test_drain_life_deals_damage_and_caster_gains_life(all_cards):
    # Drain Life: "{X}{1}{B} — Drain Life deals X damage to any target.
    # You gain life equal to the damage dealt."
    drain_life = _get(all_cards, "Drain Life")

    p1 = PlayerState(name="P1", hand=[drain_life], life=15)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Drain Life", target_player_index=1, x_value=3)

    assert result.supported
    assert p2.life == 17  # took 3 damage
    assert p1.life == 18  # gained 3 life


def test_drain_power_steals_mana_from_opponent_lands(all_cards):
    # Drain Power: "{U}{U} — Target player activates a mana ability of each land
    # they control. Then that player loses all unspent mana and you add the mana
    # lost this way."
    drain_power = _get(all_cards, "Drain Power")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[drain_power])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island), Permanent(card=island)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Drain Power", target_player_index=1)

    assert result.supported
    # Both islands are tapped
    assert all(perm.tapped for perm in p2.battlefield)
    # Opponent lost all mana
    assert sum(p2.mana_pool.values()) == 0
    # Caster received 2 blue mana (one per Island)
    assert p1.mana_pool.get("U", 0) == 2


def test_earthquake_damages_all_players_and_non_flying_creatures(all_cards):
    earthquake = _get(all_cards, "Earthquake")
    grizzly = _get(all_cards, "Grizzly Bears")
    serra = _get(all_cards, "Serra Angel")
    # P1 has Earthquake in hand + a non-flying creature
    p1 = PlayerState(name="P1", life=20, hand=[earthquake],
                     battlefield=[Permanent(card=grizzly)])
    # P2 has a flying creature
    p2 = PlayerState(name="P2", life=20, battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthquake", target_player_index=1, x_value=3)

    assert result.supported
    # Both players take 3 damage
    assert p1.life == 17
    assert p2.life == 17
    # Non-flying Grizzly Bears on p1's side takes 3 damage and dies (toughness=2)
    assert all(perm.card.name != "Grizzly Bears" for perm in p1.battlefield)
    assert any(c.name == "Grizzly Bears" for c in p1.graveyard)
    # Flying Serra Angel is unaffected
    assert any(perm.card.name == "Serra Angel" for perm in p2.battlefield)
    assert p2.battlefield[0].damage_marked == 0


def test_fireball_deals_damage(all_cards):
    fireball = _get(all_cards, "Fireball")
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", life=10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=3)

    assert result.supported
    assert p2.life == 7


def test_fireball_targets_single_creature(all_cards):
    fireball = _get(all_cards, "Fireball")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fireball", target_player_index=1, target_permanent_index=0, x_value=3)

    assert result.supported
    # Bear has toughness 2, 3 damage should remove it
    assert not p2.battlefield


def test_fireball_targets_multiple_creatures_divides_damage(all_cards):
    fireball = _get(all_cards, "Fireball")
    bear1 = _mk_card("Bear1", "Creature — Bear")
    bear2 = _mk_card("Bear2", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear1), Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    # Provide both target indices; X=3 should divide as 1 and 1 (rounded down)
    result = game.cast_from_hand(0, "Fireball", target_player_index=1, target_permanent_index=[0, 1], x_value=3)

    assert result.supported
    assert len(p2.battlefield) == 2
    assert p2.battlefield[0].damage_marked == 1
    assert p2.battlefield[1].damage_marked == 1


def test_hurricane_deals_x_damage_to_flying_creatures_and_players(all_cards):
    hurricane = _get(all_cards, "Hurricane")
    serra_angel = _get(all_cards, "Serra Angel")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[hurricane], life=20)
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=serra_angel), Permanent(card=grizzly)],
        life=20,
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Hurricane", target_player_index=1, x_value=3)

    assert result.supported
    assert p1.life == 17  # hurricane hits all players including the caster
    assert p2.life == 17
    angel_perm = p2.battlefield[0]
    bear_perm = p2.battlefield[1]
    assert angel_perm.damage_marked == 3  # Serra Angel has flying — takes damage
    assert bear_perm.damage_marked == 0   # Grizzly Bears has no flying — unaffected


def test_hurricane_kills_small_flying_creature(all_cards):
    hurricane = _get(all_cards, "Hurricane")
    tiny_flyer = CardDefinition(
        name="Tiny Flyer",
        mana_cost="{1}",
        cmc=1.0,
        type_line="Creature — Bird",
        oracle_text="Flying",
        colors=(),
        color_identity=(),
        keywords=("Flying",),
        produced_mana=(),
        raw={"name": "Tiny Flyer", "type_line": "Creature — Bird", "power": "1", "toughness": "1"},
    )

    p1 = PlayerState(name="P1", hand=[hurricane], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=tiny_flyer)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Hurricane", target_player_index=1, x_value=2)

    assert result.supported
    assert p1.life == 18
    assert p2.life == 18
    assert len(p2.battlefield) == 0  # 1/1 flyer killed by 2 damage


def test_mind_twist_discards_x_cards_at_random(all_cards):
    mind_twist = _get(all_cards, "Mind Twist")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[mind_twist])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=2)

    assert result.supported
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2


def test_raise_dead_returns_creature_from_graveyard_to_hand(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert result.supported
    assert any(card.name == "Bear" for card in p1.hand)
    assert not any(card.name == "Bear" for card in p1.graveyard)


def test_raise_dead_cannot_cast_with_empty_graveyard(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert not result.supported


def test_raise_dead_cannot_cast_with_only_non_creatures_in_graveyard(all_cards):
    raise_dead = _get(all_cards, "Raise Dead")
    sorcery = _mk_card("Lightning Bolt", "Sorcery")

    p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[sorcery])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

    assert not result.supported


def test_regrowth_returns_creature_from_graveyard_to_hand(all_cards):
    regrowth = _get(all_cards, "Regrowth")
    bear = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[regrowth], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Regrowth", target_player_index=0)

    assert result.supported
    assert any(card.name == "Dead Bear" for card in p1.hand)
    assert not any(card.name == "Dead Bear" for card in p1.graveyard)


def test_resurrection_returns_creature_from_graveyard_to_battlefield(all_cards):
    resurrection = _get(all_cards, "Resurrection")
    bear = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[resurrection], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Resurrection", target_player_index=0)

    assert result.supported
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)
    assert not any(card.name == "Dead Bear" for card in p1.graveyard)


def test_sinkhole_destroys_target_land(all_cards):
    sinkhole = _get(all_cards, "Sinkhole")
    forest = _mk_card("Forest", "Basic Land - Forest")

    p1 = PlayerState(name="P1", hand=[sinkhole])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sinkhole", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Forest"


def test_stone_rain_destroys_target_land(all_cards):
    stone_rain = _get(all_cards, "Stone Rain")
    mountain = _mk_card("Mountain", "Basic Land - Mountain")

    p1 = PlayerState(name="P1", hand=[stone_rain])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stone Rain", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Mountain"


def test_tranquility_resolves_without_error(all_cards):
    tranquility = _get(all_cards, "Tranquility")
    enchantment = _mk_card("Test Enchant", "Enchantment")

    p1 = PlayerState(name="P1", hand=[tranquility])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=enchantment)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tranquility")

    assert result.supported


def test_tsunami_destroys_all_islands(all_cards):
    tsunami = _get(all_cards, "Tsunami")
    # The real printed cards. This used to fabricate "Basic Land - Islands"
    # (plural) so the engine's substring check would match — a type line no
    # Magic card has ever had, written to fit the implementation rather than
    # the game. The type question now goes through CR 613 layer 4, which asks
    # for the exact subtype.
    island = _get(all_cards, "Island")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", hand=[tsunami])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tsunami")

    assert result.supported
    assert not any(p.card.name == "Island" for p in p2.battlefield)
    assert any(p.card.name == "Forest" for p in p2.battlefield)


def test_volcanic_eruption_resolves_without_error(all_cards):
    eruption = _get(all_cards, "Volcanic Eruption")
    mountain = _mk_card("Mountain", "Basic Land - Mountain")
    p1 = PlayerState(name="P1", hand=[eruption])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Volcanic Eruption", target_player_index=1, x_value=1)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Volcanic Eruption" for c in p1.graveyard)


def test_wrath_of_god_destroys_all_creatures(all_cards):
    wrath = _get(all_cards, "Wrath of God")
    bear1 = _mk_creature_card("Bear A", 2, 2)
    bear2 = _mk_creature_card("Bear B", 2, 2)

    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=bear1)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    assert not any(p.card.primary_type == "creature" for p in p1.battlefield)
    assert not any(p.card.primary_type == "creature" for p in p2.battlefield)
    assert any(c.name == "Bear A" for c in p1.graveyard)
    assert any(c.name == "Bear B" for c in p2.graveyard)


def test_darkpact_exchanges_owned_ante_card_with_top_of_library(all_cards):
    """"You own target card in the ante. Exchange that card with the top card of
    your library." — the anted card comes back to hand and the library's top card
    takes its place in the ante zone (CR 407)."""
    darkpact = _get(all_cards, "Darkpact")
    swamp = _get(all_cards, "Swamp")
    lotus = _get(all_cards, "Black Lotus")
    p1 = PlayerState(name="P1", hand=[darkpact], library=[swamp], ante=[lotus])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Darkpact")

    assert result.supported
    assert not p1.library
    assert [c.name for c in p1.ante] == ["Swamp"]
    assert any(c.name == "Black Lotus" for c in p1.hand)
    assert any(c.name == "Darkpact" for c in p1.graveyard)


def test_darkpact_with_nothing_owned_in_the_ante_does_nothing(all_cards):
    """CR 608.2b: with no card of yours in the ante there is nothing to
    exchange, so the library is left alone."""
    darkpact = _get(all_cards, "Darkpact")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", hand=[darkpact], library=[swamp])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Darkpact")

    assert result.supported
    assert [c.name for c in p1.library] == ["Swamp"]
    assert not p1.ante
