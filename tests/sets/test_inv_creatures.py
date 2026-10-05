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
