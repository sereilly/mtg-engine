"""Per-card tests for Limited Edition Alpha's sorcery cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle  # W4G3
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


# --- W3G3: X spells, multiple targets, damage sources ---
def _drain_life_game(set_pool, *, victim_life=20, creature=None):
    pool = set_pool("LEA")
    p0 = PlayerState(name="P0", hand=[pool["Drain Life"]], life=20)
    p1 = PlayerState(
        name="P1", life=victim_life,
        battlefield=[Permanent(card=pool[creature])] if creature else [],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p0, p1


def test_drain_life_gains_no_more_than_the_creatures_toughness(set_pool):
    """"You gain life equal to the damage dealt, **but not more life than** …
    the creature's toughness."

    The cap is the second half of the printed sentence and nothing applied it:
    the handler gained the damage dealt, and its own docstring claimed to be
    capping by toughness while the code did no such thing. Six damage at a 2/2
    gained six life.
    """
    game, p0, _p1 = _drain_life_game(set_pool, creature="Grizzly Bears")

    result = game.cast_from_hand(
        0, "Drain Life", x_value=6, target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game._settle()

    assert p0.life == 22, "six damage on a 2/2 gains two"


def test_drain_life_gains_no_more_than_the_life_total_before_the_damage(set_pool):
    """The player half of the same cap, and the reason it is read *before*: the
    damage is exactly what changes the number the card measures against."""
    game, p0, p1 = _drain_life_game(set_pool, victim_life=3)

    assert game.cast_from_hand(
        0, "Drain Life", x_value=6, target_player_index=1,
    ).supported
    game._settle()

    assert p0.life == 23, "the victim had three life to drain"
    assert p1.life == -3, "the damage itself is not capped — only the life gain"


def test_drain_life_still_gains_the_whole_amount_when_nothing_caps_it(set_pool):
    """The boundary the two caps need: with a big enough victim the gain is the
    damage dealt, so the tests above are measuring a cap rather than a
    coincidence."""
    game, p0, _p1 = _drain_life_game(set_pool, victim_life=20)

    assert game.cast_from_hand(0, "Drain Life", x_value=6, target_player_index=1).supported
    game._settle()

    assert p0.life == 26
# --- end W3G3 ---


# --- W4G3: Drain Life's sentence is a production, not a name ---
def test_drain_life_no_longer_needs_a_name_keyed_hook(set_pool):
    """"Drain Life deals X damage to any target. You gain life equal to the
    damage dealt, but not more life than the player's life total before the
    damage was dealt, the planeswalker's loyalty before the damage was dealt, or
    the creature's toughness."

    Soul Burn (ICE) prints the same sentence with one term more, which is the
    proof the shape is a template and not a card — the entry bar `card_hooks`
    states. So the sentence became a production, the hook went, and the fused
    ``deal_damage_and_gain_life`` kind it was the only producer of went with it.

    The compiled program is **not** byte-identical, and could not be: the hook
    minted one fused instruction where the production composes two — a
    ``deal_damage`` that records what it dealt and a ``target_gains_life`` that
    reads the record back and caps it. That is the composition
    ``handlers/control_flow`` exists for, and it is what lets the cap limit the
    life gained while leaving the damage dealt whole. The behaviour is pinned by
    the four tests above this block, which predate the change and still pass.
    """
    from engine import card_hooks

    assert "Drain Life" not in card_hooks.CARD_LINE_INSTRUCTIONS
    assert not any(
        "drain life" in line
        for lines in card_hooks.CARD_LINE_INSTRUCTIONS.values()
        for line in lines
    )

    program = compile_card_oracle(set_pool("LEA")["Drain Life"])
    assert program.supported
    (effect,) = [i for i in program.instructions if i.kind != "spell_pattern"]
    assert effect.kind == "sequence"
    damage, gain = effect.payload["steps"]
    assert (damage.kind, gain.kind) == ("deal_damage", "target_gains_life")
    # One term fewer than Soul Burn's, because Drain Life prints one fewer.
    assert gain.payload["capped_by"] == [
        {"kind": "recipient_capacity",
         "recipients": ["player", "planeswalker", "creature"]},
    ]


def test_drain_life_gains_nothing_from_a_target_that_is_already_gone(set_pool):
    """CR 608.2b: the only target is illegal by resolution, so nothing happens
    — and "you gain life equal to the damage dealt" is part of that nothing.

    The composed program is where this could have gone wrong: the gain is its
    own instruction now, so it runs whether or not the damage did. It reads a
    record the fizzled damage never wrote, and an absent record is zero.
    """
    pool = set_pool("LEA")
    victim = Permanent(card=pool["Grizzly Bears"])
    p0 = PlayerState(name="P0", hand=[pool["Drain Life"]], life=20)
    p1 = PlayerState(name="P1", life=20, battlefield=[victim])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.queue_from_hand(
        0, "Drain Life", x_value=6,
        target_player_index=1, target_permanent_index=0,
    ).supported
    game.remove_from_battlefield(victim)
    game._settle()

    assert p0.life == 20, "no damage dealt, so no life gained"
    assert p1.life == 20, "and the face is never the fallback for a gone target"
# --- end W4G3 ---


# --- Volcanic Eruption: the hook retired onto Avalanche's production ---------

def test_volcanic_eruption_compiles_through_the_grammar(set_pool):
    """The last name-keyed hook in ICE's era pool is retired: the destroy is
    Avalanche's production one noun over, and the aftermath damage reads the
    destroy step's own record ("put into a graveyard this way" is CR 700.4's
    "died", spelled from the graveyard's side)."""
    prog = compile_card_oracle(set_pool("LEA")["Volcanic Eruption"])
    assert prog.supported
    kinds = [step.kind for step in prog.instructions[0].payload["steps"]]
    assert kinds == [
        "destroy_target_permanent", "deal_damage_each_creature_and_player",
    ]
    sweep = prog.instructions[0].payload["steps"][1]
    assert sweep.payload == {"amount_from": "destroyed_this_way"}


def test_volcanic_eruption_damage_counts_the_graveyard_not_the_announcement(set_pool):
    """"…equal to the number of Mountains **put into a graveyard** this way."

    X = 2 was announced, but one chosen Mountain leaves before resolution — so
    one is destroyed and the damage is 1, not the announced 2 (CR 608.2b drops
    the departed slot; the amount reads the record the destroy step wrote, not
    the X). The retired hook could not get this wrong in the same way because
    it destroyed and counted in one body; the composed program is where the
    two halves could drift, which is what this pins.
    """
    pool = set_pool("LEA")
    m1, m2 = Permanent(card=pool["Mountain"]), Permanent(card=pool["Mountain"])
    bear = Permanent(card=pool["Grizzly Bears"])
    p0 = PlayerState(name="P0", hand=[pool["Volcanic Eruption"]], life=20)
    p1 = PlayerState(name="P1", life=20, battlefield=[m1, m2, bear])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.queue_from_hand(
        0, "Volcanic Eruption", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
        target_permanent_ids=[m1.permanent_id, m2.permanent_id],
    ).supported
    game.remove_from_battlefield(m2)
    game._settle()

    assert m1 not in p1.battlefield, "the surviving slot still resolves"
    assert p0.life == 19 and p1.life == 19, "1 Mountain died, so 1 damage each"
    assert bear in p1.battlefield and bear.damage_marked == 1


def test_armageddon_land_deaths_reach_dingus_egg(set_pool):
    """"Whenever a land is put into a graveyard from the battlefield…" fires
    however the land got there. The announcement was a call inside the
    single-target destroy path (plus a second inside Volcanic Eruption's
    hook), so a board sweep's land deaths reached no Dingus Egg at all — it
    now rides `_permanent_to_graveyard`, the seam every one of them already
    passes through."""
    pool = set_pool("LEA")
    egg = Permanent(card=pool["Dingus Egg"])
    p0 = PlayerState(
        name="P0", hand=[pool["Armageddon"]], life=20,
        battlefield=[egg, Permanent(card=pool["Plains"])],
    )
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=pool["Mountain"]), Permanent(card=pool["Forest"])],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.queue_from_hand(0, "Armageddon").supported
    game._settle()

    assert not any(p.card.primary_type == "land" for p in p0.battlefield)
    assert not p1.battlefield
    # One trigger per dead land, 2 damage each, aimed at that land's
    # controller: P0 lost one land, P1 two.
    assert p0.life == 18, "P0's Plains died under P0's control"
    assert p1.life == 16, "P1's two lands each cost P1 2 life"
