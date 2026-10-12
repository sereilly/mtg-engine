"""Odyssey instants.

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
from engine.mana_payment import mana_cost_from_symbols as _w1g3_mana_cost_from_symbols
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import (_damage_dealt as _w1g3_damage_dealt,
                           resolve_stack as _w1g3_resolve_stack)

# Flashback (CR 702.34): the eleven Odyssey instants printing it. Each is cast
# **twice** — from a hand for its mana cost, from a graveyard for its flashback
# cost — with mana enforced and exactly that cost in the pool, and is held to
# doing the same thing both times and to ending up in the right pile: its
# owner's graveyard after the first, exile after the second. The keyword's own
# rules are tests/rules/test_flashback.py; these say what each *card* does.


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


def test_w1g3_bash_to_bits_destroys_an_artifact_and_only_an_artifact(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        ring = _w1g3_put(game, 1, lea["Sol Ring"])
        _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [ring.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
        assert _w1g3_names(game.players[1].graveyard) == ["Sol Ring"]

    _w1g3_both_ways(set_pool, "Bash to Bits", "{4}{R}{R}", arrange, expect)

    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(set_pool("ODY")["Bash to Bits"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    assert not game.cast_from_hand(
        0, "Bash to Bits", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=1,
    ).supported
    assert game.is_on_battlefield(bears)


def test_w1g3_the_two_token_instants_make_their_token_twice(set_pool):
    for name, flashback_cost, token, stats in (
        ("Beast Attack", "{2}{G}{G}{G}", "Beast", (4, 4)),
        ("Elephant Ambush", "{6}{G}{G}", "Elephant", (3, 3)),
    ):
        def expect(game, seen):
            made, = game.controlled_by(0)
            assert token in made.card.type_line and "G" in made.card.colors
            assert (made.effective_power, made.effective_toughness) == stats

        _w1g3_both_ways(set_pool, name, flashback_cost, lambda game, seen: None, expect)


def test_w1g3_coffin_purge_exiles_a_card_from_either_graveyard(set_pool):
    """"Exile target card from a graveyard." — anybody's, and flashed back out
    of its own caster's pile it still finds the card it named there."""
    lea = set_pool("LEA")

    def theirs(game, seen):
        game.players[1].graveyard.extend([lea["Forest"], lea["Grizzly Bears"]])
        return {"target_player_index": 1, "target_permanent_index": 1}

    def expect_theirs(game, seen):
        assert _w1g3_names(game.players[1].exile) == ["Grizzly Bears"]
        assert _w1g3_names(game.players[1].graveyard) == ["Forest"]

    _w1g3_both_ways(set_pool, "Coffin Purge", "{B}", theirs, expect_theirs)

    def mine(game, seen):
        # Above the spell in its own pile, when it is cast from there.
        pile = game.players[0].graveyard
        pile.extend([lea["Forest"], lea["Grizzly Bears"]])
        return {"target_player_index": 0, "target_permanent_index": len(pile) - 1}

    def expect_mine(game, seen):
        assert "Grizzly Bears" in _w1g3_names(game.players[0].exile)
        assert "Forest" in _w1g3_names(game.players[0].graveyard)
        assert "Forest" not in _w1g3_names(game.players[0].exile)

    _w1g3_both_ways(set_pool, "Coffin Purge", "{B}", mine, expect_mine)


def test_w1g3_embolden_divides_its_4_points_of_prevention(set_pool):
    """"Prevent the next 4 damage that would be dealt this turn to any number
    of targets, divided as you choose." Three to a creature and one to a
    player, announced from a graveyard as from a hand (CR 601.2d)."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"])
        return {"divided_targets": [
            (0, game.battlefield_index_of(seen["bears"]), 3), (0, None, 1),
        ]}

    def expect(game, seen):
        # Five at the creature is 2 dealt; two at the player is 1 dealt; and
        # the shields are spent, so the next point arrives whole.
        assert _w1g3_damage_dealt(game, seen["bears"], 5) == 2
        assert _w1g3_damage_dealt(game, game.players[0], 2) == 1
        assert _w1g3_damage_dealt(game, game.players[0], 1) == 1
        assert _w1g3_damage_dealt(game, game.players[1], 2) == 2

    _w1g3_both_ways(set_pool, "Embolden", "{1}{W}", arrange, expect)


def test_w1g3_engulfing_flames_deals_1_and_denies_regeneration(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert seen["bears"].damage_marked == 1
        assert seen["bears"].metadata.get("cant_be_regenerated_this_turn") is True

    _w1g3_both_ways(set_pool, "Engulfing Flames", "{3}{R}", arrange, expect)


def test_w1g3_fervent_denial_counters_a_spell_both_times(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[1].hand.append(lea["Grizzly Bears"])
        game.players[1].mana_pool["G"] = 2
        assert game.queue_from_hand(1, "Grizzly Bears").supported
        return {"target_stack_index": 0}

    def expect(game, seen):
        assert not list(game.controlled_by(1))
        assert _w1g3_names(game.players[1].graveyard) == ["Grizzly Bears"]

    _w1g3_both_ways(set_pool, "Fervent Denial", "{5}{U}{U}", arrange, expect)

    # With nothing on the stack there is nothing to name (CR 601.2c).
    game = _w1g3_game()
    game.enforce_mana_costs = False
    denial = set_pool("ODY")["Fervent Denial"]
    game.players[0].graveyard.append(denial)
    assert not game.cast_from_hand(0, "Fervent Denial", from_zone="graveyard").supported
    assert _w1g3_zones_holding(game, denial) == ["P1.graveyard"]


def test_w1g3_howling_gale_hits_the_fliers_and_both_players(set_pool):
    """"…deals 1 damage to each creature with flying and each player."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["angel"] = _w1g3_put(game, 1, lea["Serra Angel"])
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        seen["birds"] = _w1g3_put(game, 0, lea["Birds of Paradise"])

    def expect(game, seen):
        assert (seen["angel"].damage_marked, seen["bears"].damage_marked) == (1, 0)
        assert not game.is_on_battlefield(seen["birds"])     # a 0/1 flier
        assert (game.players[0].life, game.players[1].life) == (19, 19)

    _w1g3_both_ways(set_pool, "Howling Gale", "{1}{G}", arrange, expect)


def test_w1g3_moment_s_peace_prevents_combat_damage_and_no_other(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])

    def expect(game, seen):
        for recipient in (game.players[0], game.players[1], seen["bears"]):
            assert _w1g3_damage_dealt(game, recipient, 3, combat=True) == 0
        assert _w1g3_damage_dealt(game, game.players[0], 3) == 3

    _w1g3_both_ways(set_pool, "Moment's Peace", "{2}{G}", arrange, expect)


def test_w1g3_ray_of_distortion_destroys_an_artifact_or_an_enchantment(set_pool):
    lea = set_pool("LEA")
    for victim in ("Sol Ring", "Crusade"):
        def arrange(game, seen):
            target = _w1g3_put(game, 1, lea[victim])
            _w1g3_put(game, 1, lea["Grizzly Bears"])
            return {"target_permanent_ids": [target.permanent_id], "target_player_index": 1}

        def expect(game, seen):
            assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
            assert _w1g3_names(game.players[1].graveyard) == [victim]

        _w1g3_both_ways(set_pool, "Ray of Distortion", "{4}{W}{W}", arrange, expect)


def test_w1g3_sylvan_might_gives_plus_2_plus_2_and_trample(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"])
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 0}

    def expect(game, seen):
        bears = seen["bears"]
        assert (bears.effective_power, bears.effective_toughness) == (4, 4)
        assert game._has_keyword(bears, "trample")

    _w1g3_both_ways(set_pool, "Sylvan Might", "{2}{G}{G}", arrange, expect)

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
