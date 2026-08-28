"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G1: damage family (The Dark) ---


def test_sorrows_path_burns_its_controller_and_their_creatures_when_tapped(set_pool):
    """"it deals 2 damage to **you and each creature you control**" — one
    printed clause, two kinds of recipient, and no sweep handler that batches
    exactly that set. Lowered as one instruction per recipient; refused
    outright before that, so the whole trigger did nothing."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    mine = Permanent(card=lea["Grizzly Bears"])
    theirs = Permanent(card=lea["Grizzly Bears"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path, mine]
    players[1].battlefield = [theirs]
    game = Game(players=players)
    game._sync_control()

    game.become_tapped(path)
    game._settle()

    assert players[0].life == 18, game.log
    assert mine.damage_marked == 2, game.log
    assert theirs.damage_marked == 0, game.log


def test_sorrows_paths_sweep_reaches_creatures_that_arrived_since(set_pool):
    """The recipients are the printed noun phrase asked at resolution, not a
    list built when the land entered — so a creature that arrived in between is
    damaged and one that left is not."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path]
    game = Game(players=players)
    game._sync_control()

    latecomer = Permanent(card=lea["Hill Giant"])
    players[0].battlefield.append(latecomer)
    game._sync_control()
    game.become_tapped(path)
    game._settle()

    assert latecomer.damage_marked == 2, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _run_upkeep(game: Game, seat: int) -> None:
    """One upkeep step for *seat*, with its triggers resolved off the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


def _safe_haven_holding_a_creature(set_pool):
    """Safe Haven on the battlefield with one creature exiled under it."""
    lea = set_pool("LEA")
    haven = Permanent(card=set_pool("DRK")["Safe Haven"])
    bears = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[haven, bears]),
        PlayerState(name="P2"),
    ])
    game.players[0].mana_pool["C"] = 2
    result = game.activate_permanent_ability(
        0, "Safe Haven", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.reason
    while game.stack:
        game.resolve_top_of_stack()
    return game, haven


def test_safe_haven_exiles_a_creature_with_its_activated_ability(set_pool):
    """"{2}, {T}: Exile target creature you control." The pile the upkeep
    trigger below returns from has to exist before it can be returned."""
    game, _haven = _safe_haven_holding_a_creature(set_pool)

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    assert not [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]


def test_safe_haven_returns_its_exiled_cards_when_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice this land. If you do,
    return each card exiled with this land to the battlefield under its owner's
    control."

    This line compiled to **no instruction** — Safe Haven reported supported and
    exiled creatures forever. Knowledge Vault prints the same linked-pile
    sentence with the other verb ("put all cards exiled with…into"), so both
    spellings are one production now.
    """
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=True)

    assert not game.is_on_battlefield(haven)
    assert not game.players[0].exile
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]


def test_safe_haven_declined_keeps_the_cards_in_exile(set_pool):
    """The offer is a "may": declining leaves the land and the pile alone."""
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=False)

    assert game.is_on_battlefield(haven)
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]

# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _city(set_pool, extra=()):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            _nosick(Permanent(card=pool["City of Shadows"])),
            *[_nosick(Permanent(card=pool[name])) for name in extra],
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, pool


def test_city_of_shadows_eats_a_creature_for_a_storage_counter(set_pool):
    """"{T}, **Exile a creature you control**: Put a storage counter on this
    land."

    The exile is a *cost* (CR 601.2b), so it is charged as the ability is
    activated and nothing about it is a target - protection and shroud have
    nothing to say about what may pay (idiom 10)."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool, extra=["Rag Man"])
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert result.supported, result.details
    assert counters_on(city, "storage") == 1, game.log
    assert [perm.card.name for perm in p1.battlefield] == ["City of Shadows"]
    assert [card.name for card in p1.exile] == ["Rag Man"]


def test_city_of_shadows_cannot_be_activated_with_no_creature(set_pool):
    """The control: with nothing to pay the cost, the ability is not activated
    at all (CR 602.2b) — the land is not even tapped."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert not result.supported
    assert counters_on(city, "storage") == 0
    assert city.tapped is False, game.log


def test_city_of_shadows_taps_for_one_mana_per_storage_counter(set_pool):
    """"{T}: Add {C} **for each storage counter on this land**." Counted off the
    source at resolution, which is what tells it from the batteries' "for each
    counter removed this way" — those are gone by then."""
    from engine.named_counters import add_counters

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]
    add_counters(city, "storage", 3)

    result = game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert result.supported, result.details
    assert p1.mana_pool["C"] == 3, (dict(p1.mana_pool), game.log)


def test_city_of_shadows_with_no_counters_makes_no_mana(set_pool):
    """The control on the multiplier: nothing times a counter is nothing, not
    the flat {C} the pips alone would add."""
    game, p1, p2, pool = _city(set_pool)

    game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert sum(p1.mana_pool.values()) == 0, (dict(p1.mana_pool), game.log)
