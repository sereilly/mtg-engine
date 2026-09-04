"""Tests for Magic: The Gathering Comprehensive Rules Section 119.

Covers:
  119.7  — an effect saying a player can't gain life, and the three things the
           rule says follow from it: an exchange that would raise that player
           doesn't happen, and a replacement effect over the banned gain
           "won't do anything"
  101.2  — the "can't" effect takes precedence over the effect that would gain
  701.12a/c — an exchange of life totals is one action made of gains and losses

These pin the *derivation* from oracle text
(``engine/life_prohibitions.py``), so most of them use invented card names: a
test naming Forsaken Wastes could pass against a table keyed by "Forsaken
Wastes", and the whole point of a text-keyed table is that a card the engine
has never seen works from its printed template. The real card is covered by
``tests/sets/test_mir_enchantments_wave_two.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.life_prohibitions import life_gain_ban_line, life_gain_banned
from engine.models import CardDefinition, Permanent


def _enchantment(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Enchantment"},
    )


def _game(p0=(), p1=(), libraries=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(p0), library=list(libraries)),
        PlayerState(name="P2", battlefield=list(p1)),
    ])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game


# --- the reading -----------------------------------------------------------

@pytest.mark.cr("119.7")
def test_119_7_the_three_printed_subjects_are_payload():
    """"Players can't gain life" and its two narrowed spellings are one
    sentence with the seat scope as data — a card printing either needs no
    code."""
    assert life_gain_ban_line("Players can't gain life.") == "each_player"
    assert life_gain_ban_line("Each player can't gain life.") == "each_player"
    assert life_gain_ban_line("You can't gain life.") == "you"
    assert life_gain_ban_line("Your opponents can't gain life.") == "opponents"
    assert life_gain_ban_line("Opponents can't gain life.") == "opponents"


@pytest.mark.cr("119.7")
def test_119_7_the_sentence_is_claimed_whole_or_not_at_all():
    """A prefix match would claim a line this module enforces only half of.

    The negative cases are the point: each of these is a real rule that is
    *not* this one, and admitting any of them would report a card supported
    with its actual sentence doing nothing.
    """
    for line in (
        "Players can't gain life this turn.",
        "Players can't gain life or lose life.",
        "Players can't lose life.",
        "Creatures can't gain life.",
        "Players can't gain life unless they control a Swamp.",
        "If a player would gain life, that player gains no life instead.",
    ):
        assert life_gain_ban_line(line) is None, line


@pytest.mark.cr("119.7")
def test_119_7_who_is_banned_depends_on_who_controls_the_permanent():
    """"Your opponents can't gain life" is one seat's sentence about the
    others; "Players can't gain life" is everybody's, its own controller
    included. Reading only the gaining player's own permanents would make the
    unnarrowed one a one-sided card."""
    both = _game(p0=[Permanent(card=_enchantment("Test Lock", "Players can't gain life."))])
    assert life_gain_banned(both, both.players[0]) is True
    assert life_gain_banned(both, both.players[1]) is True

    one_way = _game(
        p0=[Permanent(card=_enchantment("Test Grudge", "Your opponents can't gain life."))]
    )
    assert life_gain_banned(one_way, one_way.players[0]) is False
    assert life_gain_banned(one_way, one_way.players[1]) is True

    self_ban = _game(
        p0=[Permanent(card=_enchantment("Test Penance", "You can't gain life."))]
    )
    assert life_gain_banned(self_ban, self_ban.players[0]) is True
    assert life_gain_banned(self_ban, self_ban.players[1]) is False


# --- the seam --------------------------------------------------------------

@pytest.mark.cr("101.2")
def test_101_2_the_cant_effect_beats_the_effect_that_would_gain():
    """CR 101.2's precedence, at the one seam every life gain passes through.

    Two numbers, not one: the life total is unchanged **and** nothing was
    recorded as gained, because "you gained N life this turn" asks about life
    that actually arrived.
    """
    game = _game(p0=[Permanent(card=_enchantment("Test Lock", "Players can't gain life."))])
    game._gain_life(game.players[1], 7, "a test")

    assert game.players[1].life == 20
    assert game.players[1].life_gained_this_turn == 0
    assert any("can't gain life" in line for line in game.log)


@pytest.mark.cr("119.7")
def test_119_7_the_ban_ends_with_the_permanent():
    """A continuous effect, not a flag: nothing is stamped on the player, so
    the lock lifts the moment the permanent stops being on the battlefield."""
    lock = Permanent(card=_enchantment("Test Lock", "Players can't gain life."))
    game = _game(p0=[lock])

    game._gain_life(game.players[0], 3, "a test")
    assert game.players[0].life == 20

    game.remove_from_battlefield(lock)
    game._gain_life(game.players[0], 3, "a test")
    assert game.players[0].life == 23


@pytest.mark.cr("119.7")
def test_119_7_a_replacement_over_a_banned_gain_does_nothing():
    """"…a replacement effect that would replace a life gain event affecting
    that player won't do anything." (CR 119.7, last sentence.)

    Lich turns a life gain into a draw. Under the ban there is no life gain
    event to replace, so no cards are drawn — which is why the ban is asked
    *before* CR 616.1's contention set rather than registered inside it: as one
    candidate among several the affected player could have taken Lich's draw
    first.
    """
    lea = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    lich = Permanent(card=lea["Lich"])
    lock = Permanent(card=_enchantment("Test Lock", "Players can't gain life."))
    library = [lea["Forest"]] * 5

    unlocked = _game(p0=[lich], libraries=library)
    unlocked._gain_life(unlocked.players[0], 3, "a test")
    assert len(unlocked.players[0].hand) == 3, "control: Lich draws that many"

    locked = _game(
        p0=[Permanent(card=lea["Lich"]), lock], libraries=library,
    )
    locked._gain_life(locked.players[0], 3, "a test")
    assert locked.players[0].hand == []
    assert locked.players[0].life == 20


@pytest.mark.cr("701.12a")
@pytest.mark.cr("119.7")
def test_119_7_an_exchange_that_would_raise_a_banned_player_does_not_happen():
    """"…that player can't make an exchange such that the player's life total
    would become higher; in that case, the exchange won't happen."

    The **whole** exchange, because CR 701.12a makes it one action. Moving only
    the falling half would turn Mirror Universe into a one-way donation, which
    is the direction a half-applied rule always fails in.
    """
    pool = {c.name: c for c in load_cards(manifest_set_path("LEG"))}
    for with_lock in (False, True):
        board = [Permanent(card=pool["Mirror Universe"])]
        if with_lock:
            board.append(
                Permanent(card=_enchantment("Test Lock", "Players can't gain life."))
            )
        game = _game(p0=board)
        game.players[0].life, game.players[1].life = 5, 20
        game.current_step = "upkeep"
        game.active_player_index = 0
        game.players[0].battlefield[0].summoning_sick = False

        game.activate_permanent_ability(0, "Mirror Universe", target_player_index=1)
        game._settle()

        totals = (game.players[0].life, game.players[1].life)
        assert totals == ((5, 20) if with_lock else (20, 5))


@pytest.mark.cr("119.5")
def test_119_5_setting_a_life_total_upward_is_a_gain_and_is_banned():
    """"If an effect sets a player's life total to a specific number, the
    player gains or loses the necessary amount of life" — so the rising half is
    a gain like any other and the ban takes it. The falling half is untouched,
    which is the same rule read the other way round.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction

    card = _enchantment("Test Setter", "Each player's life total becomes 10.")
    game = _game(p0=[Permanent(card=_enchantment("Test Lock", "Players can't gain life."))])
    game.players[0].life, game.players[1].life = 5, 25
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=card,
    )
    EFFECT_HANDLERS["set_life_total"](
        game, OracleInstruction("set_life_total", "", {"amount": 10,
                                                       "recipient": "each_player"}),
        context,
    )

    assert game.players[0].life == 5, "the rise is a gain, and gains are banned"
    assert game.players[1].life == 10, "the fall is not a gain"
