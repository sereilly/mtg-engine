"""Odyssey sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.cast_permissions import (expire_end_of_turn as _w1g3_expire_end_of_turn,
                                     playable_from_zones as _w1g3_playable_from_zones)
from engine.mana_payment import mana_cost_from_symbols as _w1g3_mana_cost_from_symbols
from engine.models import Permanent as _w1g3_Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve_stack

# Flashback (CR 702.34): every Odyssey sorcery printing it, the one that grants
# it (Recoup) and the one that names it (Tombfire). Each flashback card is cast
# **twice** — from a hand for its mana cost, from a graveyard for its flashback
# cost — with mana enforced and exactly that cost in the pool, and is held to
# doing the same thing both times and to ending up in the right pile: its
# owner's graveyard after the first, exile after the second. The keyword's own
# rules (who may cast it, every way off the stack, cost changes) are
# tests/rules/test_flashback.py; these say what each *card* does.


def _w1g3_game() -> _w1g3_Game:
    game = _w1g3_Game(players=[_w1g3_PlayerState(name="P1"), _w1g3_PlayerState(name="P2")])
    game.enforce_mana_costs = True
    return game


def _w1g3_pay(player, cost: str) -> None:
    """Exactly *cost* in *player*'s pool, the generic part as colourless."""
    pool = {symbol: 0 for symbol in "WUBRGC"}
    for symbol, count in _w1g3_mana_cost_from_symbols(cost).items():
        pool["C" if symbol == "generic" else symbol] += count
    player.mana_pool.update(pool)


def _w1g3_put(game, seat: int, card, *, tapped: bool = False) -> _w1g3_Permanent:
    permanent = _w1g3_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _w1g3_settle(game) -> None:
    _w1g3_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g3_resolve_stack(game)


def _w1g3_zones_holding(game, card) -> list[str]:
    return [
        f"P{seat + 1}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "graveyard", "exile", "library")
        for held in getattr(player, zone) if held is card
    ]


def _w1g3_both_ways(set_pool, name: str, flashback_cost: str, arrange, expect) -> None:
    """Cast *name* from a hand for its mana cost and from a graveyard for
    *flashback_cost*. ``arrange(game, seen)`` builds the board and returns the
    cast's keywords; ``expect(game, seen)`` asserts what the spell did."""
    card = set_pool("ODY")[name]
    for zone, cost, afterwards in (
        ("hand", card.mana_cost, "P1.graveyard"),
        ("graveyard", flashback_cost, "P1.exile"),
    ):
        game, seen = _w1g3_game(), {}
        getattr(game.players[0], zone).append(card)
        keywords = arrange(game, seen) or {}
        _w1g3_pay(game.players[0], cost)
        cast = game.cast_from_hand(0, name, from_zone=zone, **keywords)
        assert cast.supported, (zone, cast.details)
        _w1g3_settle(game)
        assert not any(game.players[0].mana_pool.values()), (zone, f"did not cost {cost}")
        expect(game, seen)
        assert _w1g3_zones_holding(game, card) == [afterwards], zone


def _w1g3_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


def test_w1g3_ancestral_tribute_counts_the_graveyard_it_is_not_in(set_pool):
    """"You gain 2 life for each card in your graveyard." On the stack it is
    not in the graveyard — cast from hand it has not arrived yet, flashed back
    it has just left — so three other cards are 6 life either way."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[0].graveyard.extend([lea["Forest"], lea["Forest"], lea["Grizzly Bears"]])
        game.players[1].graveyard.append(lea["Forest"])

    def expect(game, seen):
        assert (game.players[0].life, game.players[1].life) == (26, 20)

    _w1g3_both_ways(set_pool, "Ancestral Tribute", "{9}{W}{W}{W}", arrange, expect)


def test_w1g3_the_three_token_sorceries_make_their_token_twice(set_pool):
    for name, flashback_cost, token, stats in (
        ("Call of the Herd", "{3}{G}", "Elephant", (3, 3)),
        ("Chatter of the Squirrel", "{1}{G}", "Squirrel", (1, 1)),
        ("Roar of the Wurm", "{3}{G}", "Wurm", (6, 6)),
    ):
        def expect(game, seen):
            made, = game.controlled_by(0)
            assert token in made.card.type_line and "G" in made.card.colors
            assert (made.effective_power, made.effective_toughness) == stats
            assert not list(game.controlled_by(1))

        _w1g3_both_ways(set_pool, name, flashback_cost, lambda game, seen: None, expect)


def test_w1g3_deep_reconnaissance_fetches_a_basic_land_tapped(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[0].library.extend([lea["Sol Ring"], lea["Bayou"], lea["Forest"], lea["Grizzly Bears"]])

    def expect(game, seen):
        land, = game.controlled_by(0)
        assert land.card.name == "Forest" and land.tapped
        assert _w1g3_names(game.players[0].library) == ["Bayou", "Grizzly Bears", "Sol Ring"]

    _w1g3_both_ways(set_pool, "Deep Reconnaissance", "{4}{G}", arrange, expect)


def test_w1g3_dematerialize_returns_a_permanent_to_its_owner_s_hand(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        ring = _w1g3_put(game, 1, lea["Sol Ring"])
        return {"target_permanent_ids": [ring.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert not list(game.controlled_by(1))
        assert _w1g3_names(game.players[1].hand) == ["Sol Ring"]

    _w1g3_both_ways(set_pool, "Dematerialize", "{5}{U}{U}", arrange, expect)


def test_w1g3_earth_rift_destroys_a_land_and_only_a_land(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        land = _w1g3_put(game, 1, lea["Forest"])
        _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [land.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
        assert _w1g3_names(game.players[1].graveyard) == ["Forest"]

    _w1g3_both_ways(set_pool, "Earth Rift", "{5}{R}{R}", arrange, expect)

    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(set_pool("ODY")["Earth Rift"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    refused = game.cast_from_hand(
        0, "Earth Rift", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=1,
    )
    assert not refused.supported
    assert game.is_on_battlefield(bears)


def test_w1g3_firebolt_deals_2_to_any_target(set_pool):
    lea = set_pool("LEA")

    def at_a_player(game, seen):
        return {"target_player_index": 1}

    _w1g3_both_ways(
        set_pool, "Firebolt", "{4}{R}", at_a_player,
        lambda game, seen: _w1g3_assert_life(game, 20, 18),
    )

    def at_a_creature(game, seen):
        bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [bears.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert not list(game.controlled_by(1))
        assert _w1g3_names(game.players[1].graveyard) == ["Grizzly Bears"]
        _w1g3_assert_life(game, 20, 20)

    _w1g3_both_ways(set_pool, "Firebolt", "{4}{R}", at_a_creature, expect)


def _w1g3_assert_life(game, mine: int, theirs: int) -> None:
    assert (game.players[0].life, game.players[1].life) == (mine, theirs)


def test_w1g3_morbid_hunger_deals_3_and_gains_3(set_pool):
    _w1g3_both_ways(
        set_pool, "Morbid Hunger", "{7}{B}{B}",
        lambda game, seen: {"target_player_index": 1},
        lambda game, seen: _w1g3_assert_life(game, 23, 17),
    )


def test_w1g3_morgue_theft_returns_a_creature_card_from_under_or_over_itself(set_pool):
    """"Return target creature card from your graveyard to your hand." Flashed
    back it is leaving the pile its target is in, so the slot it announces is
    counted with the spell still there (CR 601.2a) — on either side of it."""
    lea = set_pool("LEA")
    theft = set_pool("ODY")["Morgue Theft"]

    def arrange(game, seen):
        # The spell is already in the pile when it is flashed back: put one
        # creature card under it and one over, and name the one over.
        mine = game.players[0].graveyard
        mine.insert(0, lea["Grizzly Bears"])
        mine.extend([lea["Serra Angel"], lea["Sol Ring"]])
        return {"target_player_index": 0, "target_permanent_index": mine.index(lea["Serra Angel"])}

    def expect(game, seen):
        assert _w1g3_names(game.players[0].hand) == ["Serra Angel"]
        assert {"Grizzly Bears", "Sol Ring"} <= set(_w1g3_names(game.players[0].graveyard))

    _w1g3_both_ways(set_pool, "Morgue Theft", "{4}{B}", arrange, expect)

    # Not a noncreature card, and not somebody else's graveyard.
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([theft, lea["Sol Ring"]])
    game.players[1].graveyard.append(lea["Grizzly Bears"])
    offered = game.cast_target_spec(0, theft, from_zone="graveyard")["valid_targets"]
    assert offered == []
    assert not game.cast_from_hand(
        0, "Morgue Theft", from_zone="graveyard",
        target_player_index=0, target_permanent_index=1,
    ).supported


def test_w1g3_reckless_charge_gives_plus_3_and_haste_until_end_of_turn(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"])
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 0}

    def expect(game, seen):
        bears = seen["bears"]
        assert (bears.effective_power, bears.effective_toughness) == (5, 2)
        assert game._has_keyword(bears, "haste")

    _w1g3_both_ways(set_pool, "Reckless Charge", "{2}{R}", arrange, expect)


def test_w1g3_scorching_missile_hits_a_player_and_cannot_be_aimed_at_a_creature(set_pool):
    lea = set_pool("LEA")
    _w1g3_both_ways(
        set_pool, "Scorching Missile", "{9}{R}",
        lambda game, seen: {"target_player_index": 1},
        lambda game, seen: _w1g3_assert_life(game, 20, 16),
    )
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(set_pool("ODY")["Scorching Missile"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    refused = game.cast_from_hand(
        0, "Scorching Missile", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=1,
    )
    assert not refused.supported
    assert bears.damage_marked == 0 and game.players[1].life == 20


def test_w1g3_seize_the_day_untaps_and_adds_a_combat_and_a_main_phase(set_pool):
    """"Untap target creature. After this main phase, there is an additional
    combat phase followed by an additional main phase." Flashed back in that
    second main phase it does it again."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"], tapped=True)
        assert game.extra_phases_remaining() == []
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 0}

    def expect(game, seen):
        assert not seen["bears"].tapped
        assert game.extra_phases_remaining() == ["combat", "postcombat_main"]

    _w1g3_both_ways(set_pool, "Seize the Day", "{2}{R}", arrange, expect)


def test_w1g3_skull_fracture_makes_the_target_player_discard(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[1].hand.append(lea["Forest"])
        return {"target_player_index": 1}

    def expect(game, seen):
        assert game.players[1].hand == []
        assert _w1g3_names(game.players[1].graveyard) == ["Forest"]

    _w1g3_both_ways(set_pool, "Skull Fracture", "{3}{B}", arrange, expect)


def test_w1g3_volcanic_spray_spares_the_fliers(set_pool):
    """"…deals 1 damage to each creature without flying and each player."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["angel"] = _w1g3_put(game, 1, lea["Serra Angel"])
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        seen["birds"] = _w1g3_put(game, 0, lea["Birds of Paradise"])

    def expect(game, seen):
        assert (seen["angel"].damage_marked, seen["bears"].damage_marked) == (0, 1)
        assert seen["birds"].damage_marked == 0 and game.is_on_battlefield(seen["birds"])
        _w1g3_assert_life(game, 19, 19)

    _w1g3_both_ways(set_pool, "Volcanic Spray", "{1}{R}", arrange, expect)


def test_w1g3_volley_of_boulders_divides_6_as_announced(set_pool):
    """Flashback {R}{R}{R}{R}{R}{R}: the division (CR 601.2d) is announced from
    a graveyard exactly as it is from a hand."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["angel"] = _w1g3_put(game, 1, lea["Serra Angel"])
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"divided_targets": [
            (1, None, 1),
            (1, game.battlefield_index_of(seen["angel"]), 3),
            (1, game.battlefield_index_of(seen["bears"]), 2),
        ]}

    def expect(game, seen):
        _w1g3_assert_life(game, 20, 19)
        assert seen["angel"].damage_marked == 3 and game.is_on_battlefield(seen["angel"])
        assert not game.is_on_battlefield(seen["bears"])

    _w1g3_both_ways(set_pool, "Volley of Boulders", "{R}{R}{R}{R}{R}{R}", arrange, expect)

    # A division that does not come to 6 is no announcement at all.
    game = _w1g3_game()
    game.enforce_mana_costs = False
    volley = set_pool("ODY")["Volley of Boulders"]
    game.players[0].graveyard.append(volley)
    refused = game.cast_from_hand(
        0, "Volley of Boulders", from_zone="graveyard", divided_targets=[(1, None, 5)],
    )
    assert not refused.supported
    assert _w1g3_zones_holding(game, volley) == ["P1.graveyard"]


def test_w1g3_recoup_gives_a_sorcery_card_flashback_for_its_mana_cost(set_pool):
    """"Target sorcery card in your graveyard gains flashback until end of
    turn. The flashback cost is equal to its mana cost." The card is then cast
    from the graveyard for that cost and exiled, like any flashback cast."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup, wrath = ody["Recoup"], lea["Wrath of God"]
    assert _w1g3_compile(recoup).supported

    game = _w1g3_game()
    game.players[0].hand.append(recoup)
    game.players[0].graveyard.extend([lea["Counterspell"], wrath, lea["Grizzly Bears"]])
    game.players[1].graveyard.append(lea["Armageddon"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    # A sorcery card, in the caster's own graveyard: not the instant beside it
    # and not the opponent's sorcery.
    offered = game.cast_target_spec(0, recoup)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(0, "Wrath of God")]
    assert _w1g3_playable_from_zones(game, 0) == []

    _w1g3_pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_permanent_index=1,
    ).supported
    assert any("Wrath of God gains flashback {2}{W}{W}" in line for line in game.log)
    castable = {entry["name"]: entry for entry in _w1g3_playable_from_zones(game, 0)}
    # Recoup is in the graveyard now with its own printed flashback; the Wrath
    # has the granted one, priced at its mana cost.
    assert castable["Wrath of God"]["cost_mana"] == "{2}{W}{W}"
    assert castable["Recoup"]["cost_mana"] == "{3}{R}"
    assert set(castable) == {"Wrath of God", "Recoup"}

    _w1g3_pay(game.players[0], "{1}{W}{W}")
    short = game.cast_from_hand(0, "Wrath of God", from_zone="graveyard")
    assert not short.supported and "flashback cost ({2}{W}{W})" in short.details
    assert game.is_on_battlefield(bears)
    _w1g3_pay(game.players[0], "{2}{W}{W}")
    assert game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g3_zones_holding(game, wrath) == ["P1.exile"]
    # One card, one grant: used, it is gone.
    assert [entry["name"] for entry in _w1g3_playable_from_zones(game, 0)] == ["Recoup"]


def test_w1g3_recoup_over_an_x_spell_charges_the_x_that_was_announced(set_pool):
    """"(Mana cost includes color.)" — and its {X}: Disintegrate's granted
    flashback cost is {X}{R}, paid at the X the cast announces."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    disintegrate = lea["Disintegrate"]
    game = _w1g3_game()
    game.players[0].hand.append(ody["Recoup"])
    game.players[0].graveyard.append(disintegrate)
    _w1g3_pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0).supported
    granted, = [e for e in _w1g3_playable_from_zones(game, 0) if e["name"] == "Disintegrate"]
    assert granted["cost_mana"] == "{X}{R}"

    _w1g3_pay(game.players[0], "{2}{R}")
    refused = game.cast_from_hand(
        0, "Disintegrate", from_zone="graveyard", target_player_index=1, x_value=3,
    )
    assert not refused.supported and game.players[1].life == 20
    _w1g3_pay(game.players[0], "{3}{R}")
    assert game.cast_from_hand(
        0, "Disintegrate", from_zone="graveyard", target_player_index=1, x_value=3,
    ).supported
    _w1g3_settle(game)
    assert game.players[1].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert _w1g3_zones_holding(game, disintegrate) == ["P1.exile"]


def test_w1g3_recoup_s_grant_ends_with_the_turn_and_needs_a_sorcery_to_name(set_pool):
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup, wrath = ody["Recoup"], lea["Wrath of God"]
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].hand.append(recoup)
    game.players[0].graveyard.append(lea["Counterspell"])
    refused = game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0)
    assert not refused.supported and recoup in game.players[0].hand

    game.players[0].graveyard.append(wrath)
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=1).supported
    assert "Wrath of God" in [e["name"] for e in _w1g3_playable_from_zones(game, 0)]
    _w1g3_expire_end_of_turn(game)
    assert [e["name"] for e in _w1g3_playable_from_zones(game, 0)] == ["Recoup"]
    assert not game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported


def test_w1g3_recoup_flashed_back_cannot_name_itself(set_pool):
    """Recoup has flashback and is a sorcery card in a graveyard — but not
    while it is being cast out of one (CR 601.2a)."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup = ody["Recoup"]
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(recoup)
    assert game.cast_target_spec(0, recoup, from_zone="graveyard")["valid_targets"] == []
    assert not game.cast_from_hand(
        0, "Recoup", from_zone="graveyard", target_player_index=0, target_permanent_index=0,
    ).supported
    # With a sorcery beside it, it names that one — by the slot it was in while
    # Recoup was still under it.
    game.players[0].graveyard.append(lea["Wrath of God"])
    assert game.cast_from_hand(
        0, "Recoup", from_zone="graveyard", target_player_index=0, target_permanent_index=1,
    ).supported
    assert _w1g3_zones_holding(game, recoup) == ["P1.exile"]
    granted, = [e for e in _w1g3_playable_from_zones(game, 0)]
    assert (granted["name"], granted["cost_mana"]) == ("Wrath of God", "{2}{W}{W}")


def test_w1g3_tombfire_exiles_the_cards_with_flashback_from_one_graveyard(set_pool):
    """"Target player exiles all cards with flashback from their graveyard."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    tombfire = ody["Tombfire"]
    assert _w1g3_compile(tombfire).supported

    def board():
        game = _w1g3_game()
        game.enforce_mana_costs = False
        game.players[0].hand.append(tombfire)
        game.players[0].graveyard.extend([ody["Firebolt"], lea["Forest"]])
        game.players[1].graveyard.extend(
            [ody["Firebolt"], lea["Grizzly Bears"], ody["Recoup"], ody["Roar of the Wurm"], lea["Terror"]]
        )
        return game

    game = board()
    assert [t["seat"] for t in game.cast_target_spec(0, tombfire)["valid_targets"]] == [0, 1]
    assert game.cast_from_hand(0, "Tombfire", target_player_index=1).supported
    assert _w1g3_names(game.players[1].exile) == ["Firebolt", "Recoup", "Roar of the Wurm"]
    assert _w1g3_names(game.players[1].graveyard) == ["Grizzly Bears", "Terror"]
    # The other graveyard was not the one chosen.
    assert _w1g3_names(game.players[0].graveyard) == ["Firebolt", "Forest", "Tombfire"]
    assert game.players[0].exile == []

    game = board()
    assert game.cast_from_hand(0, "Tombfire", target_player_index=0).supported
    assert _w1g3_names(game.players[0].exile) == ["Firebolt"]
    assert "Firebolt" in _w1g3_names(game.players[1].graveyard)


def test_w1g3_tombfire_takes_a_card_recoup_gave_flashback_this_turn(set_pool):
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].hand.extend([ody["Recoup"], ody["Tombfire"]])
    game.players[0].graveyard.extend([lea["Wrath of God"], lea["Armageddon"]])
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0).supported
    assert game.cast_from_hand(0, "Tombfire", target_player_index=0).supported
    # The Wrath (granted) and Recoup itself (printed); not the other sorcery.
    assert _w1g3_names(game.players[0].exile) == ["Recoup", "Wrath of God"]
    assert _w1g3_names(game.players[0].graveyard) == ["Armageddon", "Tombfire"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
