"""Invasion creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour choices ---
# "Choose a color, then …" / "the color of your choice" / "the chosen color".
# CR 608.2d: a colour that is not announced is chosen while the effect is
# applied, and the sentence behind the choice spends it. Three of the five
# dragon legends arrived supported and counted every permanent their controller
# had, because the filter key the count carried was read by nobody.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile


def _w1g6_table(set_pool, mine=(), theirs=(), *, their_hand=(), mana=False):
    """Seat 0 holds *mine*, seat 1 *theirs* (names from INV, else LEA); seat 0
    is interactive and it is seat 0's turn. Returns the game and both lists."""
    inv, lea = set_pool("INV"), set_pool("LEA")

    def w1g6_card(name):
        return inv[name] if name in inv else lea[name]

    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = {0}
    w1g6_game.active_player_index = 0
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=w1g6_card(name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            side.append(perm)
        w1g6_sides.append(side)
    w1g6_game.players[1].hand.extend(w1g6_card(name) for name in their_hand)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_table


def _w1g6_strike(game, colour, *, pay=True):
    """Attack with seat 0's first permanent, unblocked, and answer the dragon's
    trigger: the {2}{C} offer, then the colour. Returns the prompts seen."""
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    w1g6_seen = []
    for _ in range(4):
        game.advance_combat_phase()
        for _ in range(8):
            if game.pending_choices:
                choice = game.pending_choices[0]
                w1g6_seen.append((choice.kind, choice.player_index))
                if choice.kind == "optional_pay":
                    assert game.confirm_optional_pay(0, accept=pay)
                elif choice.kind == "color_choice":
                    assert game.confirm_color_choice(0, colour)
                else:
                    game.auto_resolve_pending_choices()
            elif game.stack:
                game.resolve_top_of_stack()
    return w1g6_seen  # _w1g6_strike


def _w1g6_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g6_names


def test_w1g6_rith_counts_permanents_of_the_chosen_colour_on_every_battlefield(set_pool):
    """"…choose a color, then create a 1/1 green Saproling creature token for
    each permanent of that color." Green is chosen: Rith, the Bears and the
    opponent's Elves are green — three — and the Forests, the Hill Giant and
    the Mountain are not. It made seven (every permanent Rith's controller had)
    while the colour was read by nobody, and would have made two had the count
    stopped at its controller's battlefield (CR 403.1: one shared zone)."""
    game, _mine, _theirs = _w1g6_table(
        set_pool,
        ["Rith, the Awakener", "Forest", "Forest", "Forest", "Grizzly Bears"],
        ["Llanowar Elves", "Hill Giant", "Mountain"], mana=True,
    )
    seen = _w1g6_strike(game, "G")

    assert seen == [("optional_pay", 0), ("color_choice", 0)], seen
    assert _w1g6_names(game, 0).count("Saproling Token") == 3
    assert sum(1 for perm in game.controlled_by(0) if perm.tapped) == 4, "Rith and {2}{G}"


def test_w1g6_rith_makes_nothing_when_the_payment_is_declined(set_pool):
    """"You may pay {2}{G}. **If you do**, …": declined, no colour is asked and
    no token is made."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, ["Rith, the Awakener", "Forest", "Forest", "Forest"], [], mana=True,
    )
    seen = _w1g6_strike(game, "G", pay=False)

    assert seen == [("optional_pay", 0)], seen
    assert "Saproling Token" not in _w1g6_names(game, 0)


def test_w1g6_treva_gains_life_for_each_permanent_of_the_chosen_colour(set_pool):
    """"…you gain 1 life for each permanent of that color." Red is chosen with
    one red permanent on the table — the opponent's Hill Giant — so one life,
    not the five permanents Treva's controller has."""
    game, _mine, _theirs = _w1g6_table(
        set_pool,
        ["Treva, the Renewer", "Plains", "Plains", "Plains", "Grizzly Bears"],
        ["Hill Giant", "Llanowar Elves"], mana=True,
    )
    _w1g6_strike(game, "R")

    assert (game.players[0].life, game.players[1].life) == (21, 14)


def test_w1g6_crosis_purges_the_damaged_players_hand_of_one_colour(set_pool):
    """"…choose a color, then that player reveals their hand and discards all
    cards of that color." The player dealt the damage reveals — never Crosis's
    controller, whose own green card stays — and only the green cards go."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, ["Crosis, the Purger", "Swamp", "Swamp", "Swamp"], [],
        their_hand=["Giant Growth", "Grizzly Bears", "Lightning Bolt", "Forest"],
        mana=True,
    )
    game.players[0].hand.append(set_pool("LEA")["Giant Growth"])
    _w1g6_strike(game, "G")

    assert [card.name for card in game.players[1].hand] == ["Lightning Bolt", "Forest"]
    assert sorted(card.name for card in game.players[1].graveyard) == [
        "Giant Growth", "Grizzly Bears",
    ]
    assert [card.name for card in game.players[0].hand] == ["Giant Growth"]
    assert any(
        line.startswith("B reveals their hand: Giant Growth") for line in game.log
    ), game.log[-8:]


def test_w1g6_darigaaz_burns_for_each_revealed_card_of_the_chosen_colour(set_pool):
    """"…that player reveals their hand and Darigaaz deals damage to the player
    equal to the number of cards of that color revealed this way." Two green
    cards in the revealed hand: 6 combat damage and then 2 more, to the player
    who was hit, with nothing discarded."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, ["Darigaaz, the Igniter", "Mountain", "Mountain", "Mountain"], [],
        their_hand=["Giant Growth", "Grizzly Bears", "Lightning Bolt", "Forest"],
        mana=True,
    )
    _w1g6_strike(game, "G")

    assert (game.players[0].life, game.players[1].life) == (20, 12)
    assert len(game.players[1].hand) == 4


def test_w1g6_darigaaz_deals_nothing_for_a_colour_the_hand_does_not_hold(set_pool):
    """White is chosen and the hand holds none: the reveal happens and the
    count is zero, so only the combat damage was dealt."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, ["Darigaaz, the Igniter", "Mountain", "Mountain", "Mountain"], [],
        their_hand=["Giant Growth", "Lightning Bolt"], mana=True,
    )
    _w1g6_strike(game, "W")

    assert game.players[1].life == 14


def test_w1g6_dromar_returns_every_creature_of_the_chosen_colour(set_pool):
    """"…choose a color, then return all creatures of that color to their
    owners' hands." Green: both players' green creatures go home, the red Giant
    and the (white-blue-black) Dromar stay, and no land moves."""
    game, _mine, _theirs = _w1g6_table(
        set_pool,
        ["Dromar, the Banisher", "Island", "Island", "Island", "Grizzly Bears"],
        ["Llanowar Elves", "Hill Giant", "Forest"], mana=True,
    )
    _w1g6_strike(game, "G")

    assert _w1g6_names(game, 0) == ["Dromar, the Banisher", "Island", "Island", "Island"]
    assert _w1g6_names(game, 1) == ["Forest", "Hill Giant"]
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert [card.name for card in game.players[1].hand] == ["Llanowar Elves"]


@_w1g6_pytest.mark.parametrize("name", ["Kavu Chameleon", "Rainbow Crow"])
def test_w1g6_a_creature_becomes_the_colour_chosen_at_resolution_for_a_turn(set_pool, name):
    """"{G}: This creature becomes the color of your choice until end of turn."
    The colour is asked when the ability resolves (CR 608.2d) — a colour sent
    with the activation is not read — written to the turn-long channel, and
    gone at cleanup."""
    game, mine, _theirs = _w1g6_table(set_pool, [name], [])
    creature = mine[0]
    printed = sorted(game._effective_colors(creature))

    assert game.queue_permanent_ability(0, name, ability_index=0, mana_color="R").supported
    assert sorted(game._effective_colors(creature)) == printed, "nothing yet"
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert game.confirm_color_choice(0, "B")
    assert sorted(game._effective_colors(creature)) == ["B"]

    game.resolve_cleanup_step(0)
    assert sorted(game._effective_colors(creature)) == printed


def test_w1g6_kavu_chameleon_cannot_be_countered(set_pool):
    """"This spell can't be countered." A Counterspell aimed at it resolves and
    does nothing; the same Counterspell stops a Grizzly Bears."""
    lea = set_pool("LEA")
    game, _mine, _theirs = _w1g6_table(set_pool, [], [])
    game.players[0].hand.extend([set_pool("INV")["Kavu Chameleon"], lea["Grizzly Bears"]])
    game.players[1].hand.extend([lea["Counterspell"], lea["Counterspell"]])
    from tests.helpers import resolve_stack

    assert game.queue_from_hand(0, "Kavu Chameleon").supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    resolve_stack(game)
    assert _w1g6_names(game, 0) == ["Kavu Chameleon"]

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    resolve_stack(game)
    assert _w1g6_names(game, 0) == ["Kavu Chameleon"]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]


def _w1g6_cast_golem(set_pool, colour):
    game, _mine, theirs = _w1g6_table(set_pool, [], ["Black Knight"])
    game.players[0].hand.append(set_pool("INV")["Alloy Golem"])
    assert game.queue_from_hand(0, "Alloy Golem").supported
    game.resolve_top_of_stack()
    golem = next(p for p in game.controlled_by(0) if p.card.name == "Alloy Golem")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 0)]
    assert game.confirm_enter_choice(0, mana_color=colour)
    return game, golem, theirs  # _w1g6_cast_golem


def test_w1g6_alloy_golem_is_the_colour_chosen_as_it_entered(set_pool):
    """"As this creature enters, choose a color. / This creature is the chosen
    color. (It's still an artifact.)" Colourless as printed; red once red is
    chosen, and still an artifact creature — a red source a Circle of
    Protection: Red would answer to, and one Terror's "nonartifact" still
    refuses."""
    assert _w1g6_compile(set_pool("INV")["Alloy Golem"]).supported
    game, golem, _theirs = _w1g6_cast_golem(set_pool, "R")

    assert sorted(game._effective_colors(golem)) == ["R"]
    assert golem.has_type("artifact") and golem.is_creature
    assert (golem.effective_power, golem.effective_toughness) == (4, 4)


def test_w1g6_alloy_golems_colour_follows_a_late_answer_and_yields_to_a_later_effect(set_pool):
    """The static is derived from the record on every recompute rather than
    stamped once: a second answer is the colour it then is, and a colour
    change that began after it entered (CR 613.7) wins for as long as it
    lasts."""
    game, golem, _theirs = _w1g6_cast_golem(set_pool, "G")
    assert sorted(game._effective_colors(golem)) == ["G"]

    golem.metadata["chosen_color"] = "W"
    game._recompute_continuous_effects()
    assert sorted(game._effective_colors(golem)) == ["W"]

    golem.metadata["color_override_until_eot"] = "U"
    game._recompute_continuous_effects()
    assert sorted(game._effective_colors(golem)) == ["U"]
    game.resolve_cleanup_step(0)
    assert sorted(game._effective_colors(golem)) == ["W"]
