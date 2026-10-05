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


# --- W1G4: colour census ---
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_table(seats=2):
    """*seats* players, seat 0 active, mana costs off — the census's own rig."""
    w1g4_census_game = _W1G4Game(
        players=[_W1G4PlayerState(name=f"W1G4-{index}") for index in range(seats)]
    )
    w1g4_census_game.enforce_mana_costs = False
    w1g4_census_game.active_player_index = 0
    return w1g4_census_game


def _w1g4_enter(game, seat, card, *, sick=False):
    """*card* onto *seat*'s battlefield through the real entry seam.

    Summoning sickness is cleared afterwards unless *sick* asks to keep it —
    the entry rewrites the stamp, so it has to be written second.
    """
    w1g4_entered = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_entered, None)
    if not sick:
        w1g4_entered.metadata["summoning_sickness_turn"] = -99
    game.check_state_based_actions()
    return w1g4_entered


def _w1g4_size(permanent):
    """Computed power and toughness, as the pair the assertions compare."""
    w1g4_power = permanent.effective_power
    return (w1g4_power, permanent.effective_toughness)


def _w1g4_declare(game, attackers):
    """Declare *attackers* (permanents of seat 0) at seat 1; the engine's answer."""
    game._set_phase_and_step("combat", "declare_attackers")
    w1g4_slots = [game.battlefield_index_of(attacker) for attacker in attackers]
    return game.declare_attackers(0, w1g4_slots, defending_player_index=1)


def _w1g4_block(game, blocks):
    """Declare *blocks* — ``(blocker, attacker)`` pairs — for seat 1 and drain
    the stack; the engine's answer to the declaration."""
    game._set_phase_and_step("combat", "declare_blockers")
    w1g4_assignment = {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)]
        for blocker, attacker in blocks
    }
    w1g4_answer = game.declare_blockers(1, w1g4_assignment)
    _w1g4_resolve(game)
    return w1g4_answer


_W1G4_DJINNS = [
    # name, printed size, an off-colour LEA creature, an on-colour LEA creature
    ("Ruham Djinn", (5, 5), "Grizzly Bears", "Savannah Lions"),
    ("Zanam Djinn", (5, 6), "Grizzly Bears", "Merfolk of the Pearl Trident"),
    ("Goham Djinn", (5, 5), "Grizzly Bears", "Scathe Zombies"),
    ("Halam Djinn", (6, 5), "Grizzly Bears", "Mons's Goblin Raiders"),
    ("Sulam Djinn", (6, 6), "Savannah Lions", "Grizzly Bears"),
]


@_w1g4_pytest.mark.parametrize("name, printed, other, same", _W1G4_DJINNS)
def test_w1g4_a_djinn_shrinks_while_its_colour_leads_or_ties(
    set_pool, name, printed, other, same
):
    """"This creature gets -2/-2 as long as <colour> is the most common color
    among all permanents or is tied for most common."

    The Djinn is itself one of "all permanents", so alone it is the most common
    colour and is small; one off-colour creature is a **tie** (still small, the
    printed "or is tied"); two outnumber it and it is full size; an on-colour
    creature on the *opponent's* side ties it back down, because the census is
    of every battlefield. Lands and a Mox are permanents with no colour and move
    nothing.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    small = (printed[0] - 2, printed[1] - 2)
    game = _w1g4_table()
    djinn = _w1g4_enter(game, 0, inv[name])
    assert _w1g4_size(djinn) == small, "alone, its own colour is the most common"

    first = _w1g4_enter(game, 1, lea[other])
    assert _w1g4_size(djinn) == small, "one each is tied for most common"

    _w1g4_enter(game, 0, lea[other])
    assert _w1g4_size(djinn) == printed, "outnumbered two to one"

    for colourless in ("Plains", "Forest", "Mox Pearl"):
        _w1g4_enter(game, 0, lea[colourless])
    assert _w1g4_size(djinn) == printed, "a colourless permanent counts for no colour"

    _w1g4_enter(game, 1, lea[same])
    assert _w1g4_size(djinn) == small, "an opponent's creature of its colour ties it"

    game.remove_from_battlefield(first)
    game.check_state_based_actions()
    assert _w1g4_size(djinn) == small, "two to one in its favour is a lead"


def test_w1g4_the_census_counts_a_gold_card_once_per_colour_and_reads_the_layers(set_pool):
    """CR 105.2: a multicoloured permanent is one object *of* several colours,
    so it adds one to each. And the colour is the computed one (CR 613 layer 5):
    a Bear a Purelace has turned white is counted as white.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_table()
    ruham = _w1g4_enter(game, 0, inv["Ruham Djinn"])
    sulam = _w1g4_enter(game, 1, inv["Sulam Djinn"])
    bear = _w1g4_enter(game, 1, lea["Grizzly Bears"])
    # W1, G2.
    assert _w1g4_size(ruham) == (5, 5) and _w1g4_size(sulam) == (4, 4)

    knight = _w1g4_enter(game, 0, inv["Llanowar Knight"])  # green and white
    # W2, G3: the gold card raised both, so green still leads.
    assert set(game._effective_colors(knight)) == {"G", "W"}
    assert _w1g4_size(ruham) == (5, 5) and _w1g4_size(sulam) == (4, 4)

    game.players[0].hand.append(lea["Purelace"])
    assert game.cast_from_hand(
        0, "Purelace", target_player_index=1,
        target_permanent_ids=[bear.permanent_id],
    ).supported
    _w1g4_resolve(game)
    game.check_state_based_actions()
    # W3, G2: the recoloured Bear moved from one tally to the other.
    assert _w1g4_size(ruham) == (3, 3) and _w1g4_size(sulam) == (6, 6)


def test_w1g4_no_colour_is_most_common_on_a_colourless_board(set_pool):
    """With no coloured permanent there is no most common colour — not a
    five-way tie at zero. Asked of the census directly, because a Djinn on the
    battlefield is itself a coloured permanent and can never see this board;
    the two spells can (their own card is on the stack, not the battlefield).
    """
    from engine.color_census import (color_is_most_common, most_common_colors,
                                     shares_most_common_color)

    lea = set_pool("LEA")
    game = _w1g4_table()
    mox = _w1g4_enter(game, 0, lea["Mox Pearl"])
    _w1g4_enter(game, 1, lea["Island"])
    assert most_common_colors(game) == frozenset()
    assert not any(color_is_most_common(game, color) for color in "WUBRG")
    assert not shares_most_common_color(game, mox)

    lions = _w1g4_enter(game, 1, lea["Savannah Lions"])
    bear = _w1g4_enter(game, 0, lea["Grizzly Bears"])
    assert most_common_colors(game) == frozenset({"W", "G"})
    assert color_is_most_common(game, "W") and not color_is_most_common(
        game, "W", tied=False
    ), "'but isn't tied' is the strict reading Call to Arms prints"
    assert shares_most_common_color(game, lions) and shares_most_common_color(game, bear)
    assert not shares_most_common_color(game, mox)


def test_w1g4_tsabos_assassin_destroys_only_a_creature_of_a_leading_colour(set_pool):
    """"{T}: Destroy target creature if it shares a color with the most common
    color among all permanents or a color tied for most common. A creature
    destroyed this way can't be regenerated."

    The picker offers every creature — the clause is a condition on the effect,
    not a targeting restriction — and the ability resolves and does nothing to
    one of a trailing colour. A leading one dies through its regeneration
    shield.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    inv, lea = set_pool("INV"), set_pool("LEA")
    ability = compile_card_oracle(inv["Tsabo's Assassin"]).activated_abilities[0]
    assert derive_activation_spec(ability) == {"kind": "creature"}

    game = _w1g4_table()
    assassin = _w1g4_enter(game, 0, inv["Tsabo's Assassin"])   # black
    _w1g4_enter(game, 0, lea["Scathe Zombies"])                # black: B2
    bear = _w1g4_enter(game, 1, lea["Grizzly Bears"])          # G1
    zombies = _w1g4_enter(game, 1, lea["Scathe Zombies"])      # B3
    zombies.regeneration_shield = 1

    assert game.activate_permanent_ability(
        0, "Tsabo's Assassin", target_permanent_ids=[bear.permanent_id]
    ).supported
    _w1g4_resolve(game)
    assert assassin.tapped
    assert game.is_on_battlefield(bear), "green trails black, so nothing happens"

    game.become_untapped(assassin)
    assert game.activate_permanent_ability(
        0, "Tsabo's Assassin", target_permanent_ids=[zombies.permanent_id]
    ).supported
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(zombies), "black leads"
    assert zombies.regeneration_shield == 1, "the shield was not applied (CR 701.19c)"
    assert [card.name for card in game.players[1].graveyard] == ["Scathe Zombies"]


def test_w1g4_the_kavus_ask_about_every_opponents_creatures_and_nobody_elses(set_pool):
    """"…as long as **no opponent** controls a white or blue creature."

    Your own white creature does not count, an opponent's green one does not
    count, and a white *or* a blue one each switch the bonus off — and it comes
    back by itself when that creature leaves (CR 611.3a). Kavu Runner's haste is
    asked where it matters: it may attack the turn it arrives.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_table()
    skittish = _w1g4_enter(game, 0, inv["Skittish Kavu"])
    runner = _w1g4_enter(game, 0, inv["Kavu Runner"], sick=True)
    assert _w1g4_size(skittish) == (2, 2)
    assert game._has_keyword(runner, "haste")
    assert game.can_attack(runner, 1)

    _w1g4_enter(game, 0, lea["Savannah Lions"])
    _w1g4_enter(game, 1, lea["Grizzly Bears"])
    assert _w1g4_size(skittish) == (2, 2), "yours, and an opponent's green one"
    assert game._has_keyword(runner, "haste")

    for colour_card in ("Savannah Lions", "Merfolk of the Pearl Trident"):
        theirs = _w1g4_enter(game, 1, lea[colour_card])
        assert _w1g4_size(skittish) == (1, 1), colour_card
        assert not game._has_keyword(runner, "haste"), colour_card
        assert not game.can_attack(runner, 1), "summoning sick without haste"
        game.remove_from_battlefield(theirs)
        game.check_state_based_actions()
        assert _w1g4_size(skittish) == (2, 2)
        assert game._has_keyword(runner, "haste")


def test_w1g4_no_opponent_means_every_opponent_at_a_table_of_three(set_pool):
    """"No opponent controls …" is one statement about all of them, where "an
    opponent controls no …" would be true the moment one of two has an empty
    board. Only a third seat can tell the two apart.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_table(seats=3)
    skittish = _w1g4_enter(game, 0, inv["Skittish Kavu"])
    assert _w1g4_size(skittish) == (2, 2)
    _w1g4_enter(game, 2, lea["Savannah Lions"])
    assert _w1g4_size(skittish) == (1, 1), (
        "seat 1 controls no white or blue creature, but seat 2 does"
    )


def test_w1g4_scarred_puma_needs_a_black_or_green_creature_attacking_beside_it(set_pool):
    """"This creature can't attack unless a black or green creature also
    attacks." (CR 508.1c — a restriction the *declaration* answers.)

    Alone, beside a white creature, beside a second (red) Puma, and with a
    green creature that stays home, the declaration is refused whole; with the
    green one declared too it is legal. An opponent's black creature is not
    attacking and escorts nobody.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")

    def _board(*others, theirs=()):
        game = _w1g4_table()
        puma = _w1g4_enter(game, 0, inv["Scarred Puma"])
        mine = [_w1g4_enter(game, 0, card) for card in others]
        for card in theirs:
            _w1g4_enter(game, 1, card)
        return game, puma, mine

    game, puma, _ = _board()
    refused, why = _w1g4_declare(game, [puma])
    assert not refused and "Scarred Puma" in why

    game, puma, mine = _board(lea["Savannah Lions"])
    assert not _w1g4_declare(game, [puma, mine[0]])[0]

    game, puma, mine = _board(inv["Scarred Puma"])
    assert not _w1g4_declare(game, [puma, mine[0]])[0], "a red Puma is no escort"

    game, puma, mine = _board(lea["Grizzly Bears"])
    assert not _w1g4_declare(game, [puma])[0], "the Bear is home, not attacking"

    game, puma, _ = _board(theirs=[lea["Scathe Zombies"]])
    assert not _w1g4_declare(game, [puma])[0], "the opponent's creature isn't attacking"

    for escort in ("Grizzly Bears", "Scathe Zombies"):
        game, puma, mine = _board(lea[escort])
        assert _w1g4_declare(game, [puma, mine[0]])[0], escort
        assert puma.attacking and mine[0].attacking


def test_w1g4_the_ai_leaves_an_unescorted_puma_at_home(set_pool):
    """The AI builds its set from the per-creature predicate and prunes it with
    the declaration's own refusal — so beside a white creature it attacks with
    that creature alone rather than proposing a set the engine refuses whole,
    and beside a green one it sends both.
    """
    from engine.ai_policy import choose_attackers

    inv, lea = set_pool("INV"), set_pool("LEA")
    for escort, expected in (("Savannah Lions", {"Savannah Lions"}),
                             ("Grizzly Bears", {"Scarred Puma", "Grizzly Bears"})):
        game = _w1g4_table()
        _w1g4_enter(game, 0, inv["Scarred Puma"])
        _w1g4_enter(game, 0, lea[escort])
        game._set_phase_and_step("combat", "declare_attackers")
        proposed = choose_attackers(game, 0)
        names = {game.players[0].battlefield[slot].card.name for slot in proposed}
        assert names == expected
        assert game.declare_attackers(0, proposed, defending_player_index=1)[0]


@_w1g4_pytest.mark.parametrize(
    "name, victim, bystander",
    [
        ("Phyrexian Reaper", "Grizzly Bears", "Savannah Lions"),
        # The Slayer flies, so its blockers do too: a white flier and a blue one.
        ("Phyrexian Slayer", "Serra Angel", "Air Elemental"),
    ],
)
def test_w1g4_the_phyrexian_destroys_the_blocker_of_its_colour_and_no_other(
    set_pool, name, victim, bystander
):
    """"Whenever this creature becomes blocked by a green [white] creature,
    destroy that creature. It can't be regenerated."

    CR 509.3d: one trigger per blocker the phrase admits. Double-blocked by one
    creature of the colour and one not, exactly one ability goes on the stack
    and exactly the right creature dies — through its regeneration shield.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_table()
    phyrexian = _w1g4_enter(game, 0, inv[name])
    doomed = _w1g4_enter(game, 1, lea[victim])
    spared = _w1g4_enter(game, 1, lea[bystander])
    doomed.regeneration_shield = 1

    assert _w1g4_declare(game, [phyrexian])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {
        game.battlefield_index_of(doomed): [game.battlefield_index_of(phyrexian)],
        game.battlefield_index_of(spared): [game.battlefield_index_of(phyrexian)],
    })[0]
    assert [item.card.name for item in game.stack] == [name]
    _w1g4_resolve(game)

    assert not game.is_on_battlefield(doomed)
    assert doomed.regeneration_shield == 1, "can't be regenerated"
    assert game.is_on_battlefield(spared)
    assert game.is_on_battlefield(phyrexian)


def test_w1g4_a_reaper_blocked_by_no_green_creature_or_itself_blocking_does_nothing(set_pool):
    """The narrowing is on the trigger, so a white blocker puts nothing on the
    stack at all; and "becomes blocked" is the attacker's event — a Reaper that
    *blocks* a green creature has no trigger to fire.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_table()
    reaper = _w1g4_enter(game, 0, inv["Phyrexian Reaper"])
    lions = _w1g4_enter(game, 1, lea["Savannah Lions"])
    assert _w1g4_declare(game, [reaper])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {
        game.battlefield_index_of(lions): [game.battlefield_index_of(reaper)]
    })[0]
    assert game.stack == []
    assert game.is_on_battlefield(lions)

    game = _w1g4_table()
    bear = _w1g4_enter(game, 0, lea["Grizzly Bears"])
    reaper = _w1g4_enter(game, 1, inv["Phyrexian Reaper"])
    assert _w1g4_declare(game, [bear])[0]
    assert _w1g4_block(game, [(reaper, bear)])[0]
    assert game.is_on_battlefield(bear), "it blocked; it did not become blocked"


def test_w1g4_a_bare_becomes_blocked_trigger_still_refuses_that_creature():
    """CR 509.3c: "becomes blocked" with no noun phrase fires once however many
    creatures block, so "that creature" names none of them — the immediate
    destroy refuses there exactly as the end-of-combat one always has, rather
    than destroying whichever blocker came first.
    """
    from engine.grammar import compile_line

    bare = compile_line(
        "Whenever this creature becomes blocked, destroy that creature.",
        card_name="Probe",
    )
    assert bare.lowering_error and not bare.instructions
    narrowed = compile_line(
        "Whenever this creature becomes blocked by a Wall, destroy that Wall.",
        card_name="Probe",
    )
    assert narrowed.lowering_error, (
        "a noun that narrows again is a second test the handler does not make"
    )


# --- W1G5: colour relations ---
from engine import Game as _W1G5CGame, PlayerState as _W1G5CPlayer
from engine.models import CardDefinition as _W1G5CCard, Permanent as _W1G5CPermanent
from engine.oracle import compile_card_oracle as _w1g5c_compile
from tests.helpers import _damage_dealt as _w1g5c_damage_dealt
from tests.helpers import resolve_stack as _w1g5c_resolve_stack


def _w1g5_body(name, power, toughness, colors=(), type_line="Creature - Test", text=""):
    """A bare creature for the other side of a fight."""
    return _W1G5CCard(
        name=name, mana_cost="".join("{%s}" % symbol for symbol in colors) or "{3}",
        cmc=3.0, type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G5 creatures: a test body


def _w1g5_duel(mine, theirs, *, active=0):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_W1G5CPermanent(card=card) for card in mine]
    board1 = [_W1G5CPermanent(card=card) for card in theirs]
    filler = _w1g5_body("Filler", 0, 1)
    game = _W1G5CGame(players=[
        _W1G5CPlayer(name="P0", battlefield=board0, library=[filler] * 10),
        _W1G5CPlayer(name="P1", battlefield=board1, library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G5 creatures: the duel


def _w1g5_attack(game, attacker_slot, blocker_slot=None, *, defender=1):
    """The active seat attacks with *attacker_slot*; *defender* blocks it with
    *blocker_slot* or not at all; combat runs to the second main phase."""
    attacker_seat = game.active_player_index
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(attacker_seat, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocks = {} if blocker_slot is None else {blocker_slot: attacker_slot}
    blocked = game.declare_blockers(defender, blocks)
    assert blocked[0], blocked
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5c_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G5: fought


# --- Callous Giant ---------------------------------------------------------
# "If a source would deal 3 or less damage to this creature, prevent that
# damage." A static shield narrowed by the size of the event.


def test_w1g5_callous_giant_shrugs_off_three_and_takes_four(set_pool):
    """The threshold is the card: 1, 2 and 3 are prevented whole, 4 is dealt
    whole — never "all but 3"."""
    giant_card = set_pool("INV")["Callous Giant"]
    assert _w1g5c_compile(giant_card).supported
    game, (giant, other), _ = _w1g5_duel([giant_card, _w1g5_body("Bystander", 2, 2)], [])

    for small in (1, 2, 3):
        assert _w1g5c_damage_dealt(game, giant, small) == 0, small
    assert _w1g5c_damage_dealt(game, giant, 4) == 4
    assert _w1g5c_damage_dealt(game, giant, 9, combat=True) == 9
    # "to **this** creature": nobody else on the board is shielded
    assert _w1g5c_damage_dealt(game, other, 2) == 2
    assert _w1g5c_damage_dealt(game, game.players[0], 2) == 2


def test_w1g5_callous_giant_in_combat(set_pool):
    """Through the combat damage step. Blocking a 3/3 the Giant is unmarked and
    kills it; blocking a 4/4 it takes the four and trades (it is a 4/4)."""
    giant_card = set_pool("INV")["Callous Giant"]
    game, (raider,), (giant,) = _w1g5_duel([_w1g5_body("Raider", 3, 3)], [giant_card])
    _w1g5_attack(game, 0, 0)
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert not game.is_on_battlefield(raider)

    game, (brute,), (giant,) = _w1g5_duel([_w1g5_body("Brute", 4, 4)], [giant_card])
    _w1g5_attack(game, 0, 0)
    assert not game.is_on_battlefield(giant)
    assert not game.is_on_battlefield(brute)


def test_w1g5_callous_giant_judges_each_event_as_it_stands(set_pool):
    """Each source's damage is its own event, so three 3-point hits are three
    prevented events. And CR 616.1f re-asks after every applied effect: five
    damage that a prevention pool has cut to three is three or less by the
    time the Giant's shield is asked, so nothing lands."""
    game, (giant,), _ = _w1g5_duel([set_pool("INV")["Callous Giant"]], [])
    for _ in range(3):
        assert _w1g5c_damage_dealt(game, giant, 3) == 0
    giant.damage_prevention_pool = 2
    assert _w1g5c_damage_dealt(game, giant, 5) == 0
    assert giant.damage_prevention_pool == 0
    # …and a small event is taken whole before the pool is spent on it
    giant.damage_prevention_pool = 2
    assert _w1g5c_damage_dealt(game, giant, 3) == 0
    assert giant.damage_prevention_pool == 2


# --- Urborg Phantom --------------------------------------------------------
# "This creature can't block." / "{U}: Prevent all combat damage that would be
# dealt to and dealt by this creature this turn."


def _w1g5_phantom_shield(game, phantom):
    result = game.activate_permanent_ability(
        game.controller_index_of(phantom), "Urborg Phantom",
        permanent_index=game.battlefield_index_of(phantom),
    )
    assert result.supported, result.details
    _w1g5c_resolve_stack(game)  # W1G5: the Phantom's shield is armed


def test_w1g5_urborg_phantom_cannot_block(set_pool):
    phantom_card = set_pool("INV")["Urborg Phantom"]
    assert _w1g5c_compile(phantom_card).supported
    game, _attackers, (phantom,) = _w1g5_duel([_w1g5_body("Raider", 2, 2)], [phantom_card])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused


def test_w1g5_urborg_phantoms_shield_covers_both_ends_of_its_own_combat(set_pool):
    """Activated, the 3/1 attacks into a 5/5 blocker: it deals nothing and
    takes nothing. Unblocked on another table, the defending player loses no
    life. The shield is on the Phantom and nobody else — the creature beside
    it still deals and takes combat damage — which is the reading a targetless
    ability's fallback scan would have got wrong."""
    phantom_card = set_pool("INV")["Urborg Phantom"]
    game, (phantom, friend), (wall,) = _w1g5_duel(
        [phantom_card, _w1g5_body("Friend", 2, 2)], [_w1g5_body("Wall", 5, 5)]
    )
    _w1g5_phantom_shield(game, phantom)
    assert any(
        "dealt to and dealt by Urborg Phantom this turn is prevented" in line
        for line in game.log
    )
    assert _w1g5c_damage_dealt(game, friend, 2, source=wall, combat=True) == 2
    assert _w1g5c_damage_dealt(game, wall, 2, source=friend, combat=True) == 2
    _w1g5_attack(game, 0, 0)
    assert game.is_on_battlefield(phantom) and phantom.damage_marked == 0
    assert wall.damage_marked == 0

    game, (phantom,), _ = _w1g5_duel([phantom_card], [])
    _w1g5_phantom_shield(game, phantom)
    _w1g5_attack(game, 0)
    assert game.players[1].life == 20


def test_w1g5_urborg_phantoms_shield_is_combat_damage_only_and_ends_with_the_turn(set_pool):
    """The printed "combat" and the printed "this turn", one at a time: a ping
    still kills the shielded 3/1, and after cleanup the shield is gone."""
    phantom_card = set_pool("INV")["Urborg Phantom"]
    game, (phantom,), (wall,) = _w1g5_duel([phantom_card], [_w1g5_body("Wall", 5, 5)])
    _w1g5_phantom_shield(game, phantom)
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall, combat=True) == 0
    assert _w1g5c_damage_dealt(game, wall, 3, source=phantom, combat=True) == 0
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall) == 1

    game.resolve_cleanup_step(0)
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall, combat=True) == 1
    assert _w1g5c_damage_dealt(game, wall, 3, source=phantom, combat=True) == 3


def test_w1g5_urborg_phantom_without_the_shield_is_an_ordinary_attacker(set_pool):
    """The control: unshielded, the same attack deals its 3."""
    game, (phantom,), _ = _w1g5_duel([set_pool("INV")["Urborg Phantom"]], [])
    _w1g5_attack(game, 0)
    assert game.players[1].life == 17


# --- Tsabo Tavoc -----------------------------------------------------------
# "First strike, protection from legendary creatures" /
# "{B}{B}, {T}: Destroy target legendary creature. It can't be regenerated."


def _w1g5_legend(name, power, toughness, text=""):
    return _w1g5_body(
        name, power, toughness, ("G",), type_line="Legendary Creature - Test",
        text=text,
    )  # W1G5: a legendary test creature


def test_w1g5_tsabo_tavoc_is_protected_from_legendary_creatures_and_nothing_else(set_pool):
    """CR 702.16a: the quality is a supertype *and* a type, both of them. A
    legendary creature's damage is prevented (CR 702.16e); a nonlegendary
    creature's is not, and neither is a legendary permanent's that is not a
    creature — "legendary creatures" is one quality, not two."""
    from web.serialization import _effective_keywords

    tsabo_card = set_pool("INV")["Tsabo Tavoc"]
    assert _w1g5c_compile(tsabo_card).supported
    relic = _w1g5_body("Relic", 0, 0, type_line="Legendary Artifact")
    game, (tsabo,), (legend, commoner, artifact) = _w1g5_duel(
        [tsabo_card],
        [_w1g5_legend("Old Hero", 6, 6), _w1g5_body("Commoner", 6, 6), relic],
    )
    assert game._protection_qualities(tsabo) == {("typed", "legendary creature")}
    assert "Protection from legendary creatures" in _effective_keywords(tsabo, game)

    assert _w1g5c_damage_dealt(game, tsabo, 6, source=legend) == 0
    assert _w1g5c_damage_dealt(game, tsabo, 6, source=legend, combat=True) == 0
    assert _w1g5c_damage_dealt(game, tsabo, 6, source=commoner) == 6
    assert _w1g5c_damage_dealt(game, tsabo, 2, source=artifact) == 2


def test_w1g5_tsabo_tavoc_cannot_be_blocked_by_a_legendary_creature(set_pool):
    """CR 702.16f, at the declaration: the legend may not block it and the
    nonlegendary creature beside it may."""
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [set_pool("INV")["Tsabo Tavoc"]],
        [_w1g5_legend("Old Hero", 1, 9), _w1g5_body("Commoner", 1, 9)],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert not game._can_block_attacker(legend, tsabo)
    assert game._can_block_attacker(commoner, tsabo)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g5_tsabo_tavoc_destroys_a_legend_through_regeneration(set_pool):
    """The ability names "target **legendary** creature": the commoner is not a
    legal target, and neither is Tsabo Tavoc itself — its own ability comes
    from a legendary creature, which is what it has protection from
    (CR 702.16b). The legend dies with a regeneration shield up."""
    tsabo_card = set_pool("INV")["Tsabo Tavoc"]
    hero = _w1g5_legend("Old Hero", 3, 3, text="{G}: Regenerate this creature.")
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [tsabo_card], [hero, _w1g5_body("Commoner", 3, 3)]
    )
    # Nothing is paid for an illegal announcement (CR 602.2b): Tsabo Tavoc is
    # still untapped after each refusal.
    for illegal in (tsabo, commoner):
        refused = game.activate_permanent_ability(
            0, "Tsabo Tavoc", permanent_index=0,
            target_player_index=game.controller_index_of(illegal),
            target_permanent_ids=[illegal.permanent_id],
        )
        assert not refused.supported, illegal.card.name
        assert not tsabo.tapped

    shielded = game.activate_permanent_ability(1, "Old Hero", permanent_index=0)
    assert shielded.supported, shielded.details
    _w1g5c_resolve_stack(game)
    result = game.activate_permanent_ability(
        0, "Tsabo Tavoc", permanent_index=0, target_player_index=1,
        target_permanent_ids=[legend.permanent_id],
    )
    assert result.supported, result.details
    _w1g5c_resolve_stack(game)
    assert not game.is_on_battlefield(legend)
    assert game.is_on_battlefield(commoner) and tsabo.tapped


def test_w1g5_a_legendary_creatures_ability_cannot_target_tsabo_tavoc(set_pool):
    """CR 702.16b from the other side: a legendary pinger may not aim at it,
    and the same ability on a nonlegendary creature may."""
    ping = "{T}: This creature deals 1 damage to target creature."
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [set_pool("INV")["Tsabo Tavoc"]],
        [_w1g5_legend("Old Archer", 1, 1, text=ping),
         _w1g5_body("Young Archer", 1, 1, text=ping)],
        active=1,
    )
    refused = game.activate_permanent_ability(
        1, "Old Archer", permanent_index=0, target_player_index=0,
        target_permanent_ids=[tsabo.permanent_id],
    )
    assert not refused.supported, refused.details
    allowed = game.activate_permanent_ability(
        1, "Young Archer", permanent_index=1, target_player_index=0,
        target_permanent_ids=[tsabo.permanent_id],
    )
    assert allowed.supported, allowed.details
    _w1g5c_resolve_stack(game)
    assert tsabo.damage_marked == 1


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.land_types import change_land_type as _w1g3_change_land_type
from engine.models import Permanent as _W1G3Permanent


def _w1g3_board(set_pool, mine=(), theirs=()):
    """A duel with each seat's permanents named in board order. Lands come from
    Alpha — Invasion prints no dual land with two basic land types, and the
    whole question here is which *types* a board holds."""
    w1g3_inv, w1g3_lea = set_pool("INV"), set_pool("LEA")
    w1g3_game = _W1G3Game(
        players=[_W1G3PlayerState(name="W1G3-A"), _W1G3PlayerState(name="W1G3-B")]
    )
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_source = w1g3_inv if w1g3_name in w1g3_inv else w1g3_lea
            w1g3_perm = _W1G3Permanent(card=w1g3_source[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_board (creatures)


def _w1g3_pt(perm):
    return perm.effective_power, perm.effective_toughness  # _w1g3_pt


def test_w1g3_wayfaring_giant_counts_types_not_lands(set_pool):
    """"Domain — This creature gets +1/+1 for each basic land type among lands
    you control." Three Plains are one type; a printed 1/3 with one type is
    2/4, not 4/6."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Plains", "Plains", "Plains"]
    )
    assert _w1g3_pt(mine[0]) == (2, 4)


def test_w1g3_wayfaring_giant_reads_a_dual_land_as_two_types(set_pool):
    """A Tropical Island is a Forest *and* an Island (CR 305.6), so one land
    is worth two — and the Forest beside it adds nothing new."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Tropical Island"]
    )
    giant = mine[0]
    assert _w1g3_pt(giant) == (3, 5)

    forest = _W1G3Permanent(card=set_pool("LEA")["Forest"])
    game._put_permanent_onto_battlefield(0, forest, None)
    assert _w1g3_pt(giant) == (3, 5), "a second Forest is not a second type"

    swamp = _W1G3Permanent(card=set_pool("LEA")["Swamp"])
    game._put_permanent_onto_battlefield(0, swamp, None)
    assert _w1g3_pt(giant) == (4, 6), "the bonus follows the board (layer 7c)"

    game.remove_from_battlefield(swamp)
    game._settle()
    assert _w1g3_pt(giant) == (3, 5), "and shrinks when the type leaves"


def test_w1g3_wayfaring_giant_ignores_the_opponents_lands_and_caps_at_five(set_pool):
    """"Lands **you** control": the opponent's five types are worth nothing,
    and your own five are the most there are."""
    five = ["Plains", "Island", "Swamp", "Mountain", "Forest"]
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant"], theirs=five
    )
    assert _w1g3_pt(mine[0]) == (1, 3)

    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", *five, "Tropical Island", "Badlands"]
    )
    assert _w1g3_pt(mine[0]) == (6, 8)


def test_w1g3_wayfaring_giant_counts_the_type_a_land_has_now(set_pool):
    """CR 305.7 / CR 613 layer 4: a land's basic land types are computed. A
    Forest an effect has made a Swamp is a Swamp for domain — so with a Swamp
    already beside it the count *drops* to one, which the printed type line
    would never say."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Wayfaring Giant", "Forest", "Swamp"]
    )
    giant, forest = mine[0], mine[1]
    assert _w1g3_pt(giant) == (3, 5)

    _w1g3_change_land_type(forest, "swamp", source="w1g3-test")
    game._settle()
    assert forest.basic_land_types == ("swamp",)
    assert _w1g3_pt(giant) == (2, 4)


def test_w1g3_kavu_scout_gets_power_only(set_pool):
    """"Domain — This creature gets **+1/+0** for each basic land type among
    lands you control." A printed 0/2: the toughness never moves."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Kavu Scout", "Mountain", "Forest", "Tropical Island"]
    )
    scout = mine[0]
    assert _w1g3_pt(scout) == (3, 2)

    game, mine, _theirs = _w1g3_board(set_pool, mine=["Kavu Scout"])
    assert _w1g3_pt(mine[0]) == (0, 2), "no lands, no domain"


def test_w1g3_kavu_scout_attacks_for_its_domain(set_pool):
    """Driven through a real combat: the damage dealt is the computed power."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Kavu Scout", "Mountain", "Island", "Swamp", "Plains"]
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    assert game.players[1].life == 16, game.log[-8:]


# --- W1G1: kicker ---
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.mana_payment import mana_cost_from_symbols as _w1g1_symbols
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import _mk_card as _w1g1_mk_card
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, pool=None, library=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (INV names)
    with *pool* already floating. Costs are enforced because a kicker is a
    price: a rig that waives mana cannot tell a kicked cast from a free one."""
    inv = set_pool("INV")
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=list(library) or [forest] * 10,
        hand=[inv[name] for name in hand],
    )
    theirs = _W1G1PlayerState("Bystander", library=[forest] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    return game  # _w1g1_duel


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g1_put


def _w1g1_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g1_floating


def _w1g1_price(printed: str) -> int:
    return sum((_w1g1_symbols(printed) or {}).values())  # _w1g1_price


def _w1g1_cast(game, name, *, kick=None, **announced):
    """Cast *name* from seat 0, kicked for *kick* (the offer's key) or not, and
    resolve it. Returns the permanent it became, or None."""
    result = game.cast_from_hand(
        0, name, optional_cost_payments={kick: 1} if kick else None, **announced
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    return next(
        (p for p in game.controlled_by(0) if p.card.name == name), None
    )  # _w1g1_cast


#: The twelve "If this creature was kicked, it enters with <N> +1/+1 counters
#: on it [and with <ability>]" creatures: name, printed body, kicked body, and
#: the keyword the kicked one additionally has.
_W1G1_COUNTER_KICKERS = [
    ("Ardent Soldier", (1, 2), (2, 3), None),
    ("Benalish Lancer", (2, 2), (4, 4), "first strike"),
    ("Prison Barricade", (1, 3), (2, 4), None),
    ("Faerie Squadron", (1, 1), (3, 3), "flying"),
    ("Vodalian Serpent", (2, 2), (6, 6), None),
    ("Duskwalker", (1, 1), (3, 3), "fear"),
    ("Urborg Skeleton", (0, 1), (1, 2), None),
    ("Kavu Aggressor", (3, 2), (4, 3), None),
    ("Pouncing Kavu", (1, 1), (3, 3), "haste"),
    ("Kavu Titan", (2, 2), (5, 5), "trample"),
    ("Llanowar Elite", (1, 1), (6, 6), None),
    ("Pincer Spider", (2, 3), (3, 4), None),
]


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_an_unkicked_creature_is_the_printed_body(
    set_pool, name, printed, kicked, keyword
):
    """Cast for its mana cost alone: the printed body, no counters, the mana
    cost and nothing more spent — and **not** the keyword the kicked one gets.
    That last half is a real failure this round found: the word sits in a
    static line, the printed-ability scan read it, and every unkicked Faerie
    Squadron flew."""
    card = set_pool("INV")[name]
    game = _w1g1_duel(set_pool, [name])
    before = _w1g1_floating(game)
    creature = _w1g1_cast(game, name)

    assert (creature.effective_power, creature.effective_toughness) == printed
    assert int(creature.metadata.get("plus_counters", 0)) == 0
    assert not creature.metadata.get(_W1G1_KICKED)
    assert before - _w1g1_floating(game) == _w1g1_price(card.mana_cost)
    if keyword is not None:
        assert not game._has_keyword(creature, keyword)


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_a_kicked_creature_enters_with_its_counters(
    set_pool, name, printed, kicked, keyword
):
    """CR 702.33a/d + CR 614.1c: the kicker is paid on top of the mana cost,
    and the creature enters with the printed number of +1/+1 counters (real
    counters, not a pump) and whatever "and with" names."""
    card = set_pool("INV")[name]
    kicker = _w1g1_kicker_cost(card.oracle_text)
    assert kicker is not None
    game = _w1g1_duel(set_pool, [name])
    before = _w1g1_floating(game)
    creature = _w1g1_cast(game, name, kick=kicker)

    assert (creature.effective_power, creature.effective_toughness) == kicked
    assert int(creature.metadata.get("plus_counters", 0)) == kicked[0] - printed[0]
    assert before - _w1g1_floating(game) == (
        _w1g1_price(card.mana_cost) + _w1g1_price(kicker)
    )
    assert f"Kicker kicked {name}" in game.log
    if keyword is not None:
        assert game._has_keyword(creature, keyword)


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_a_creature_nothing_cast_was_not_kicked(
    set_pool, name, printed, kicked, keyword
):
    """Put onto the battlefield without being cast (a reanimation, a blink):
    no cast, so no CR 601.2b, so not kicked — the printed body."""
    game = _w1g1_duel(set_pool, [])
    creature = _w1g1_put(game, 0, set_pool("INV")[name])
    assert (creature.effective_power, creature.effective_toughness) == printed
    if keyword is not None:
        assert not game._has_keyword(creature, keyword)


def test_w1g1_a_kicker_the_pool_cannot_pay_is_refused_with_nothing_spent(set_pool):
    """CR 601.2h: Faerie Squadron is {U} with kicker {3}{U}. Two blue mana pays
    the creature and not the kicked creature, and a refused cast spends none."""
    game = _w1g1_duel(set_pool, ["Faerie Squadron"], pool={"U": 2})
    refused = game.cast_from_hand(
        0, "Faerie Squadron", optional_cost_payments={"{3}{U}": 1}
    )
    assert not refused.supported
    assert _w1g1_floating(game) == 2
    assert [c.name for c in game.players[0].hand] == ["Faerie Squadron"]
    assert not list(game.controlled_by(0))


def test_w1g1_the_kicker_is_offered_by_name_and_priced_against_the_pool(set_pool):
    """The browser's cast-offer prompt is built from `cast_cost_offers`: the
    price is labelled with the keyword, and `max_times` says whether the pool
    in front of the player can pay it on top of the spell."""
    card = set_pool("INV")["Kavu Titan"]
    rich = _w1g1_duel(set_pool, ["Kavu Titan"])
    poor = _w1g1_duel(set_pool, ["Kavu Titan"], pool={"G": 2})
    [offer] = rich.cast_cost_offers(0, card)
    assert (offer["symbols"], offer["label"], offer["max_times"]) == (
        "{2}{G}", "kicker", 1,
    )
    [offer] = poor.cast_cost_offers(0, card)
    assert offer["max_times"] == 0


def test_w1g1_a_granted_keyword_is_an_ability_not_part_of_the_card(set_pool):
    """Kavu Titan's trample is granted at layer 6 with no duration, so it lasts
    past the turn it entered — and is still a *grant*: it sits in the ability
    record, which is what lets a later removal take it and leave the counters."""
    game = _w1g1_duel(set_pool, ["Kavu Titan"])
    titan = _w1g1_cast(game, "Kavu Titan", kick="{2}{G}")
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert game._has_keyword(titan, "trample")
    assert "trample" not in {k.lower() for k in titan.card.keywords}


def test_w1g1_prison_barricade_attacks_only_when_it_was_kicked(set_pool):
    """Defender stops the printed Wall; the kicked one is granted "This
    creature can attack as though it didn't have defender." — and still *has*
    defender (CR 609.4: an "as though" lifts the one restriction it names)."""
    for kick, may_attack in ((None, False), ("{1}{W}", True)):
        game = _w1g1_duel(set_pool, ["Prison Barricade"])
        wall = _w1g1_cast(game, "Prison Barricade", kick=kick)
        wall.metadata["summoning_sickness_turn"] = -99
        assert game.can_attack(wall, 1) is may_attack
        assert game._has_keyword(wall, "defender")


#: The five Emissaries: name, kicker, the spec kind a kicked cast asks for,
#: the LEA/INV card to aim at, and where that card must end up.
_W1G1_EMISSARIES = [
    ("Benalish Emissary", "{1}{G}", "Forest", "graveyard"),
    ("Tolarian Emissary", "{1}{W}", "Saproling Infestation", "graveyard"),
    ("Urborg Emissary", "{1}{U}", "Grizzly Bears", "hand"),
    ("Shivan Emissary", "{1}{B}", "Grizzly Bears", "graveyard"),
    ("Verduran Emissary", "{1}{R}", "Sol Ring", "graveyard"),
]


def _w1g1_victim_card(set_pool, name):
    return set_pool("INV").get(name) or set_pool("LEA")[name]  # _w1g1_victim_card


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_a_kicked_emissary_does_its_entry_effect(
    set_pool, name, kicker, victim, ends_in
):
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))
    if name in ("Shivan Emissary", "Verduran Emissary"):
        # "It can't be regenerated.": a shield must not save it. (The other
        # two destroyers print no such rider, and a shield would.)
        target.regeneration_shield = 1
    _w1g1_cast(game, name, kick=kicker, target_permanent_ids=[target.permanent_id])

    assert not game.is_on_battlefield(target)
    pile = getattr(game.players[1], ends_in)
    assert [card.name for card in pile] == [victim]


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_an_unkicked_emissary_does_nothing_on_entry(
    set_pool, name, kicker, victim, ends_in
):
    """CR 603.4: the intervening "if it was kicked" is false, so the ability
    does not trigger — even when the caster named the very target a kicked
    cast would have hit. Nothing goes on the stack and nothing is touched."""
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))
    result = game.queue_from_hand(0, name, target_permanent_ids=[target.permanent_id])
    assert result.supported, result
    assert game.resolve_top_of_stack()

    assert game.stack == []
    assert game.is_on_battlefield(target)
    assert any(p.card.name == name for p in game.controlled_by(0))


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_an_emissary_names_a_target_only_when_kicked(
    set_pool, name, kicker, victim, ends_in
):
    """CR 702.33g: "the spell's controller chooses those targets only if that
    spell was kicked." The spec a player is shown asks for nothing until the
    kicker is taken, and then offers exactly the permanent the text names."""
    card = set_pool("INV")[name]
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))

    plain = game.cast_target_spec(0, card)
    assert (plain["kind"], plain["requires_target"]) == ("none", False)
    assert plain["cost_offers"][0]["label"] == "kicker"

    kicked = game.cast_target_spec(0, card, optional_cost_payments={kicker: 1})
    assert kicked["requires_target"]
    assert target.card.name in [entry["name"] for entry in kicked["valid_targets"]]


def test_w1g1_shivan_emissary_cannot_be_aimed_at_a_black_creature(set_pool):
    """"Destroy target **nonblack** creature." The picker never offers the
    black one, and a cast that names it anyway destroys nothing."""
    game = _w1g1_duel(set_pool, ["Shivan Emissary"])
    knight = _w1g1_put(game, 1, set_pool("LEA")["Black Knight"])
    bears = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    spec = game.cast_target_spec(
        0, set_pool("INV")["Shivan Emissary"], optional_cost_payments={"{1}{B}": 1}
    )
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]

    _w1g1_cast(
        game, "Shivan Emissary", kick="{1}{B}",
        target_permanent_ids=[knight.permanent_id],
    )
    assert game.is_on_battlefield(knight) and game.is_on_battlefield(bears)


def test_w1g1_a_kicked_emissary_with_no_target_named_chooses_on_the_stack(set_pool):
    """A cast that announced nothing leaves the choice to CR 603.3d: the
    trigger goes on the stack and picks there (a headless seat takes the
    picker's default), rather than resolving against nothing."""
    game = _w1g1_duel(set_pool, ["Verduran Emissary"])
    ring = _w1g1_put(game, 1, set_pool("LEA")["Sol Ring"])
    _w1g1_cast(game, "Verduran Emissary", kick="{1}{R}")
    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[1].graveyard] == ["Sol Ring"]


def test_w1g1_skizzik_is_sacrificed_at_the_end_step_unless_it_was_kicked(set_pool):
    """"At the beginning of the end step, if this creature wasn't kicked,
    sacrifice it." The negated condition, asked of the permanent turns after
    the cast is over — so it has to be on the permanent, not on the stack."""
    plain = _w1g1_duel(set_pool, ["Skizzik"])
    _w1g1_cast(plain, "Skizzik")
    plain.resolve_end_step(0)
    _w1g1_resolve_stack(plain)
    assert not list(plain.controlled_by(0))
    assert [card.name for card in plain.players[0].graveyard] == ["Skizzik"]

    kicked = _w1g1_duel(set_pool, ["Skizzik"])
    skizzik = _w1g1_cast(kicked, "Skizzik", kick="{R}")
    for _ in range(3):
        kicked.resolve_end_step(0)
        _w1g1_resolve_stack(kicked)
    assert kicked.is_on_battlefield(skizzik)
    assert kicked.stack == []

    reanimated = _w1g1_duel(set_pool, [])
    _w1g1_put(reanimated, 0, set_pool("INV")["Skizzik"])
    reanimated.resolve_end_step(0)
    _w1g1_resolve_stack(reanimated)
    assert not list(reanimated.controlled_by(0))


def test_w1g1_thicket_elemental_reveals_until_a_creature_and_shuffles_the_rest(
    set_pool,
):
    """"…reveal cards from the top of your library until you reveal a creature
    card. If you do, put that card onto the battlefield and shuffle all other
    cards revealed this way into your library." Only when kicked."""
    lea = set_pool("LEA")
    stacked = [lea["Forest"], lea["Mountain"], lea["Grizzly Bears"], lea["Island"]]

    kicked = _w1g1_duel(set_pool, ["Thicket Elemental"], library=stacked)
    _w1g1_cast(kicked, "Thicket Elemental", kick="{1}{G}")
    kicked.auto_resolve_pending_choices()
    _w1g1_resolve_stack(kicked)
    assert sorted(p.card.name for p in kicked.controlled_by(0)) == [
        "Grizzly Bears", "Thicket Elemental",
    ]
    # The two lands turned over on the way went back, shuffled in — not binned.
    assert sorted(card.name for card in kicked.players[0].library) == [
        "Forest", "Island", "Mountain",
    ]
    assert kicked.players[0].graveyard == []

    plain = _w1g1_duel(set_pool, ["Thicket Elemental"], library=stacked)
    _w1g1_cast(plain, "Thicket Elemental")
    assert [p.card.name for p in plain.controlled_by(0)] == ["Thicket Elemental"]
    assert [card.name for card in plain.players[0].library] == [
        "Forest", "Mountain", "Grizzly Bears", "Island",
    ]


def test_w1g1_verdeloth_kicked_for_x_makes_x_saprolings(set_pool):
    """Kicker {X}: the X is announced with the kicker (CR 107.3a, an additional
    cost with an {X} in it), paid as generic mana on top of {4}{G}{G}, and read
    by the entry trigger. The tokens are Saprolings, so the anthem beside it
    makes each a 2/2; Verdeloth is a Treefolk but not an *other* one."""
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"])
    before = _w1g1_floating(game)
    verdeloth = _w1g1_cast(game, "Verdeloth the Ancient", kick="{X}", x_value=3)

    assert before - _w1g1_floating(game) == 6 + 3
    saprolings = [p for p in game.controlled_by(0) if p is not verdeloth]
    assert len(saprolings) == 3
    assert {(p.effective_power, p.effective_toughness) for p in saprolings} == {(2, 2)}
    assert (verdeloth.effective_power, verdeloth.effective_toughness) == (4, 7)


def test_w1g1_verdeloth_unkicked_ignores_a_stray_x(set_pool):
    """A declined kicker announces no X (the offer is where the X lives), so a
    number sent with it charges nothing and reaches nothing."""
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"])
    before = _w1g1_floating(game)
    _w1g1_cast(game, "Verdeloth the Ancient", x_value=5)
    assert before - _w1g1_floating(game) == 6
    assert [p.card.name for p in game.controlled_by(0)] == ["Verdeloth the Ancient"]


def test_w1g1_verdeloth_buffs_the_union_once(set_pool):
    """"Saproling creatures **and** other Treefolk creatures get +1/+1" is one
    ability over a union: a creature that is both gets +1/+1, not +2/+2 — and
    an opponent's Treefolk is reached too (the sentence names no controller)."""
    game = _w1g1_duel(set_pool, [])
    _w1g1_put(game, 0, set_pool("INV")["Verdeloth the Ancient"])
    both = _w1g1_put(game, 0, _w1g1_mk_card(
        name="Sapling Elder", type_line="Creature — Treefolk Saproling",
        power=1, toughness=1,
    ))
    treefolk = _w1g1_put(game, 1, _w1g1_mk_card(
        name="Old Oak", type_line="Creature — Treefolk", power=2, toughness=5,
    ))
    bear = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert (both.effective_power, both.effective_toughness) == (2, 2)
    assert (treefolk.effective_power, treefolk.effective_toughness) == (3, 6)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w1g1_an_x_kicker_announces_x_only_once_it_is_taken(set_pool):
    """The spec asks for an X exactly when the kicker is taken, with a ceiling
    the pool can pay: 12 mana less Verdeloth's 6 leaves X at most 6."""
    card = set_pool("INV")["Verdeloth the Ancient"]
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"], pool={"G": 12})
    assert "announces_x" not in game.cast_target_spec(0, card)
    taken = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert taken["announces_x"] is True
    assert taken["max_x"] == 6

    refused = game.cast_from_hand(
        0, "Verdeloth the Ancient", optional_cost_payments={"{X}": 1}, x_value=7
    )
    assert not refused.supported
    assert _w1g1_floating(game) == 12


def test_w1g1_kangee_kicked_for_x_gets_x_feathers_and_lifts_other_birds(set_pool):
    """Kicker {X}{2}: {2}{W}{U} + {2} + X. The feather counters size the anthem
    ("for each feather counter on Kangee" — the card naming itself), and Kangee
    is a Bird that is not an *other* Bird."""
    game = _w1g1_duel(set_pool, ["Kangee, Aerie Keeper"])
    bird = _w1g1_put(game, 0, set_pool("LEA")["Birds of Paradise"])
    theirs = _w1g1_put(game, 1, set_pool("LEA")["Birds of Paradise"])
    before = _w1g1_floating(game)
    kangee = _w1g1_cast(game, "Kangee, Aerie Keeper", kick="{X}{2}", x_value=2)

    assert before - _w1g1_floating(game) == 4 + 2 + 2
    assert _w1g1_counters_on(kangee, "feather") == 2
    assert (bird.effective_power, bird.effective_toughness) == (2, 3)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 3)
    assert (kangee.effective_power, kangee.effective_toughness) == (2, 2)


def test_w1g1_kangee_unkicked_has_no_feathers(set_pool):
    game = _w1g1_duel(set_pool, ["Kangee, Aerie Keeper"])
    bird = _w1g1_put(game, 0, set_pool("LEA")["Birds of Paradise"])
    kangee = _w1g1_cast(game, "Kangee, Aerie Keeper")
    assert _w1g1_counters_on(kangee, "feather") == 0
    assert (bird.effective_power, bird.effective_toughness) == (0, 1)


def test_w1g1_kavu_aggressor_cannot_block_kicked_or_not(set_pool):
    """The printed restriction is no part of the kicker and survives it."""
    game = _w1g1_duel(set_pool, ["Kavu Aggressor"])
    kavu = _w1g1_cast(game, "Kavu Aggressor", kick="{4}")
    kinds = {i.kind for i in _w1g1_compile(kavu.effective_card).instructions}
    assert "cant_block" in kinds
    attacker = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    assert not game._can_block_attacker(kavu, attacker)


def test_w1g1_the_ai_kicks_when_its_lands_can_pay(set_pool):
    """The stated policy: kick whenever the lands can pay for it on top of the
    spell. Two Forests cast the 2/2; five cast the 5/5 trampler and tap all
    five. An X kicker takes the most the lands allow."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g1_duel(set_pool, ["Kavu Titan"], pool={})
    for _ in range(2):
        _w1g1_put(game, 0, forest)
    plain = _w1g1_choose_cast_action(game, 0)
    assert (plain.card_name, plain.optional_cost_payments) == ("Kavu Titan", None)

    for _ in range(3):
        _w1g1_put(game, 0, forest)
    kicked = _w1g1_choose_cast_action(game, 0)
    assert kicked.optional_cost_payments == {"{2}{G}": 1}
    assert len(kicked.land_tap_indices) == 5

    elder = _w1g1_duel(set_pool, ["Verdeloth the Ancient"], pool={})
    for _ in range(9):
        _w1g1_put(elder, 0, forest)
    sized = _w1g1_choose_cast_action(elder, 0)
    assert (sized.optional_cost_payments, sized.x_value) == ({"{X}": 1}, 3)


def test_w1g1_the_ai_does_not_kick_for_a_half_with_nothing_to_hit(set_pool):
    """Tolarian Emissary's kicker destroys an enchantment. With none anywhere
    the AI casts the flier unkicked; with one on the other side it kicks and
    names it."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Tolarian Emissary"], pool={})
    for name in ("Island", "Island", "Island", "Plains", "Plains"):
        _w1g1_put(game, 0, lea[name])
    plain = _w1g1_choose_cast_action(game, 0)
    assert (plain.card_name, plain.optional_cost_payments) == (
        "Tolarian Emissary", None,
    )

    aura = _w1g1_put(game, 1, set_pool("INV")["Saproling Infestation"])
    kicked = _w1g1_choose_cast_action(game, 0)
    assert kicked.optional_cost_payments == {"{1}{W}": 1}
    assert kicked.target_permanent_ids == [aura.permanent_id]


def test_w1g1_a_copy_of_a_kicked_creature_was_not_kicked(set_pool):
    """Whether a permanent was kicked is a fact about the spell that became it,
    not a copiable value (CR 707.2): a Clone of a kicked Kavu Titan is a 2/2
    with no trample and no counters, beside the 5/5 it copied."""
    game = _w1g1_duel(set_pool, ["Kavu Titan"])
    game.players[0].hand.append(set_pool("LEA")["Clone"])
    titan = _w1g1_cast(game, "Kavu Titan", kick="{2}{G}")
    result = game.cast_from_hand(
        0, "Clone", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[titan.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    clone = next(p for p in game.controlled_by(0) if p is not titan)

    assert clone.effective_card.name == "Kavu Titan"
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)
    assert not game._has_keyword(clone, "trample")
    assert (titan.effective_power, titan.effective_toughness) == (5, 5)
# end of the W1G1 creatures block


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_creature_duel(set_pool, *, enforce: bool = False):
    """Two non-interactive seats on seat 0's turn."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _w1g8_creature_put(game, card, seat: int):
    """*card* on *seat*'s battlefield, clear of summoning sickness."""
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g8_zombie_in_graveyard(set_pool, *, swamps: int):
    """Pyre Zombie in seat 0's graveyard under a Grizzly Bears, with *swamps*
    untapped Swamps to pay from and costs enforced."""
    game = _w1g8_creature_duel(set_pool, enforce=True)
    lands = [
        _w1g8_creature_put(game, set_pool("LEA")["Swamp"], 0) for _ in range(swamps)
    ]
    game.players[0].graveyard = [
        set_pool("LEA")["Grizzly Bears"], set_pool("INV")["Pyre Zombie"],
    ]
    return game, lands


def test_pyre_zombie_returns_from_the_graveyard_for_one_black_black(set_pool):
    """"At the beginning of your upkeep, if this card is in your graveyard, you
    may pay {1}{B}{B}. If you do, return it to your hand." The ability
    functions from the graveyard (CR 113.6b); three Swamps pay it, and "it" is
    the Zombie — the Grizzly Bears beside it stays."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=3)

    game.resolve_upkeep(0)
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].hand] == ["Pyre Zombie"]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]
    assert all(land.tapped for land in lands)


def test_pyre_zombie_stays_put_when_its_cost_cannot_be_paid(set_pool):
    """"If you do" — two Swamps do not cover {1}{B}{B}, so nothing is paid and
    nothing returns."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=2)

    game.resolve_upkeep(0)
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert game.players[0].hand == []
    assert "Pyre Zombie" in [card.name for card in game.players[0].graveyard]
    assert not any(land.tapped for land in lands)


def test_pyre_zombie_does_nothing_on_an_opponents_upkeep(set_pool):
    """"**your** upkeep": the graveyard's owner's, not each player's."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=3)

    game.resolve_upkeep(1)
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert game.players[0].hand == []
    assert not any(land.tapped for land in lands)


def test_pyre_zombie_is_sacrificed_to_deal_two_damage(set_pool):
    """"{1}{R}{R}, Sacrifice this creature: It deals 2 damage to any target."
    The Zombie goes to its owner's graveyard as the cost and the Grizzly Bears
    takes 2 — lethal — with any target offered by the picker."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    zombie_card = set_pool("INV")["Pyre Zombie"]
    assert derive_activation_spec(
        compile_card_oracle(zombie_card).activated_abilities[0]
    ) == {"kind": "any"}
    game = _w1g8_creature_duel(set_pool)
    zombie = _w1g8_creature_put(game, zombie_card, 0)
    bears = _w1g8_creature_put(game, set_pool("LEA")["Grizzly Bears"], 1)

    assert game.activate_permanent_ability(
        0, "Pyre Zombie", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert not game.is_on_battlefield(zombie)
    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[0].graveyard] == ["Pyre Zombie"]
    assert "Pyre Zombie dealt 2 damage to Grizzly Bears" in game.log


# --- INTEGRATOR: a colour choice is not a target ---
import pytest as _int_c_pytest

from engine.oracle import compile_card_oracle as _int_c_compile
from engine.targeting import derive_activation_spec as _int_c_activation_spec


@_int_c_pytest.mark.parametrize("name", ["Rainbow Crow", "Kavu Chameleon"])
def test_int_becoming_the_color_of_your_choice_points_at_nothing(set_pool, name):
    """"{1}: This creature becomes the color of your choice until end of turn."
    The phrase "of your choice" names a colour, chosen at resolution; the
    permanent is the source. The activation spec says so positively
    (``kind: none``) rather than answering None, which is what the client and
    the activation guard read as a derivation that lost its evidence."""
    program = _int_c_compile(set_pool("INV")[name])
    recolor = next(
        ability for ability in program.activated_abilities
        if "color of your choice" in ability.source_line
    )
    assert _int_c_activation_spec(recolor) == {"kind": "none"}
# --- end INTEGRATOR: a colour choice is not a target ---
