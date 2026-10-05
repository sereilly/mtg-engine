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
