"""Tempest artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: the hollow lines, counter-removal costs and the linked pile ---

from engine import Game, PlayerState
from engine.linked_exile import link_exiled_card, linked_entries
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _w1g5_game(*battlefields):
    """A two-seat game with each seat's permanents already on the battlefield.

    Mana costs off, which is the standard rig: what these tests are about is
    the *counter-removal* half of the cost, and leaving mana enforcement on
    would make every one of them a test of the mana payment instead.
    """
    seats = [
        PlayerState(name=f"P{index + 1}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w1g5_card(name, type_line, text="", power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def test_w1g5_essence_bottle_gains_two_life_per_counter_the_cost_removed(set_pool):
    """"{T}, Remove all elixir counters from this artifact: You gain 2 life for
    each elixir counter removed this way."

    The number is the *cost's*, not the board's: CR 601.2h takes the counters
    off before the ability is on the stack, so by resolution the artifact holds
    none and a board read would gain nothing on every activation.
    """
    bottle = Permanent(card=set_pool("TMP")["Essence Bottle"])
    game = _w1g5_game([bottle], [])
    add_counters(bottle, "elixir", 3)

    result = game.activate_permanent_ability(0, "Essence Bottle", ability_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert game.players[0].life == 26, game.log
    assert counters_on(bottle, "elixir") == 0, "the cost took every counter"


def test_w1g5_essence_bottle_with_no_counters_still_activates(set_pool):
    """Removing all of zero counters removes zero. CR 601.2h forbids only what
    *cannot* be done, so the cost is payable on an empty artifact and the
    ability resolves having gained no life — where a fixed count ("remove a
    counter") would make the ability unactivatable."""
    bottle = Permanent(card=set_pool("TMP")["Essence Bottle"])
    game = _w1g5_game([bottle], [])

    result = game.activate_permanent_ability(0, "Essence Bottle", ability_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert game.players[0].life == 20, game.log


def test_w1g5_essence_bottles_removal_is_charged_as_a_cost(set_pool):
    """The cost clause reaches the charged ``ActivatedAbilityCost``.

    Asserted on the cost rather than only through the life gained, because the
    failure this guards is silent in the other direction: with no row for
    "remove **all**", the clause matched nothing at all and the ability was
    activatable for free, forever, with its counters untouched.
    """
    program = compile_card_oracle(set_pool("TMP")["Essence Bottle"])
    cost = program.activated_abilities[1].cost
    assert (cost.remove_counter, cost.remove_counter_count) == ("elixir", "all")


def test_w1g5_torture_chamber_deals_damage_equal_to_the_counters_it_removed(set_pool):
    """"{1}, {T}, Remove all pain counters from this artifact: It deals damage
    to target creature equal to the number of pain counters removed this way."

    The same record as Essence Bottle's read by a different family, which is
    the point of the shared production: one printed phrase, three sentences
    that spend it.
    """
    chamber = Permanent(card=set_pool("TMP")["Torture Chamber"])
    victim = Permanent(card=_w1g5_card("Ogre", "Creature — Ogre", power=3, toughness=6))
    game = _w1g5_game([chamber], [victim])
    add_counters(chamber, "pain", 4)

    result = game.activate_permanent_ability(
        0, "Torture Chamber", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert victim.damage_marked == 4, game.log
    assert counters_on(chamber, "pain") == 0


def test_w1g5_torture_chamber_offers_a_picker_for_its_target(set_pool):
    """`picker_sweep` flagged it as "says 'target', derivation offers no
    picker" — which was the hollow line seen from the other end: the ability
    compiled to nothing, so `derive_activation_spec` had no program to read.
    Fixing the line fixes the picker, and this is the assertion that says so.
    """
    program = compile_card_oracle(set_pool("TMP")["Torture Chamber"])
    ability = program.activated_abilities[0]
    assert ability.instruction is not None, "the line is no longer hollow"
    assert derive_activation_spec(ability) == {"kind": "creature"}


def test_w1g5_cold_storage_returns_only_the_creature_cards_it_exiled(set_pool):
    """"Sacrifice this artifact: Return each creature card exiled with this
    artifact to the battlefield under your control."

    Three printed facts, and each is a way the card could quietly do less:
    the pile is the *linked* one (CR 610.3), only **creature** cards come back,
    and they arrive under the ability's controller rather than their owner
    (CR 110.2a) — while ownership itself never moves (CR 108.3).
    """
    storage = Permanent(card=set_pool("TMP")["Cold Storage"])
    game = _w1g5_game([storage], [])
    bear = _w1g5_card("Bear", "Creature — Bear", power=2, toughness=2)
    relic = _w1g5_card("Relic", "Artifact")
    game.players[1].exile.append(bear)
    link_exiled_card(storage, bear, 1)
    game.players[0].exile.append(relic)
    link_exiled_card(storage, relic, 0)

    result = game.activate_permanent_ability(0, "Cold Storage", ability_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    returned = [perm for perm in game.controlled_by(0) if perm.card.name == "Bear"]
    assert returned, game.log
    assert game.controller_index_of(returned[0]) == 0, "under *your* control"
    assert game.owner_index_of(returned[0]) == 1, "CR 108.3: ownership never moves"
    assert [entry["card"].name for entry in linked_entries(storage)] == ["Relic"], (
        "the artifact the sentence does not name stays exiled with the pile"
    )


# --- W2G4: naming a card, and reading the name back ---

import random as _w2g4_random

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _w2g4_card(name, type_line, text="", power=None, toughness=None):
    raw = {"name": name, "type_line": type_line, "oracle_text": text}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w2g4_game(p0_permanents, *, p0_hand=(), interactive=(0,)):
    seats = [
        PlayerState(name="P0", battlefield=list(p0_permanents), hand=list(p0_hand)),
        PlayerState(name="P1"),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game


def test_cursed_scroll_hits_when_the_random_reveal_matches_the_name(set_pool):
    """`{3}, {T}: Choose a card name, then reveal a card at random from your
    hand. If that card has the chosen name, this artifact deals 2 damage to any
    target.`

    Three steps, one resolution: the name is recorded, the reveal picks a card
    nobody chose, and the condition compares the two. Every card in the hand is
    the named one here, so the randomness cannot decide the outcome.
    """
    scroll = Permanent(card=set_pool("TMP")["Cursed Scroll"])
    bolt = _w2g4_card("Shock", "Instant")
    game = _w2g4_game([scroll], p0_hand=[bolt, bolt, bolt])

    result = game.activate_permanent_ability(
        0, "Cursed Scroll", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert game.confirm_choose_card_name(0, "Shock")
    assert game.players[1].life == 18


def test_cursed_scroll_misses_when_the_revealed_card_is_not_the_named_one(set_pool):
    """The condition is a real comparison, not a rider that always fires — a
    hand holding nothing the seat named deals no damage at all."""
    scroll = Permanent(card=set_pool("TMP")["Cursed Scroll"])
    bolt = _w2g4_card("Shock", "Instant")
    game = _w2g4_game([scroll], p0_hand=[bolt, bolt])

    game.activate_permanent_ability(
        0, "Cursed Scroll", ability_index=0, target_player_index=1,
    )
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "Lightning Bolt")

    assert game.players[1].life == 20


def test_cursed_scroll_with_an_empty_hand_reveals_nothing_and_misses(set_pool):
    """An empty hand reveals no card (CR 608.2, as much as possible), and the
    condition reads that as False rather than as a match against nothing."""
    scroll = Permanent(card=set_pool("TMP")["Cursed Scroll"])
    game = _w2g4_game([scroll])

    game.activate_permanent_ability(
        0, "Cursed Scroll", ability_index=0, target_player_index=1,
    )
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "Shock")

    assert game.players[1].life == 20


def test_cursed_scroll_offers_any_target_at_activation(set_pool):
    """The damage is the *conditional* half of the ability, so the picker has
    to offer its target when the ability is activated (CR 601.2c / 115.1c) —
    long before anybody knows whether the reveal will match."""
    program = compile_card_oracle(set_pool("TMP")["Cursed Scroll"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec is not None, "the picker has no idea what this ability targets"
    assert spec.get("kind") == "any"


def test_altar_of_dementia_mills_the_power_of_the_creature_the_cost_ate(set_pool):
    """`Sacrifice a creature: Target player mills cards equal to the sacrificed
    creature's power.`

    The number is the *cost's*, and by resolution the creature is in a
    graveyard with no characteristics at all (CR 613.1) — so it is read off the
    record the activation kept (CR 601.2h, CR 608.2h). Two creatures of
    different sizes are on the board, so a handler reading "a creature" rather
    than "the one the cost ate" would mill the wrong number.
    """
    altar = Permanent(card=set_pool("TMP")["Altar of Dementia"])
    big = Permanent(card=_w2g4_card("Ogre", "Creature — Ogre", power=4, toughness=4))
    small = Permanent(card=_w2g4_card("Rat", "Creature — Rat", power=1, toughness=1))
    game = _w2g4_game([altar, big, small])
    game.players[1].library = [_w2g4_card("Mountain", "Basic Land — Mountain")] * 10

    result = game.activate_permanent_ability(
        0, "Altar of Dementia", ability_index=0,
        target_player_index=1,
        # A battlefield *slot*, which is what this parameter is: the Ogre is
        # the second permanent P0 controls.
        cost_permanent_index=1,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert len(game.players[1].graveyard) == 4, "four, the Ogre's power"
    # And the cost was actually charged: wave 1 found two artifacts whose
    # non-mana activation cost was parsed and collected by nobody.
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Altar of Dementia", "Rat",
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Ogre"]


def test_altar_of_dementia_mills_nothing_for_a_zero_power_sacrifice(set_pool):
    """A 0-power creature mills nothing rather than falling back to a printed
    number — there is no printed number, and a handler that read one would have
    had to invent it."""
    altar = Permanent(card=set_pool("TMP")["Altar of Dementia"])
    wall = Permanent(card=_w2g4_card("Wall", "Creature — Wall", power=0, toughness=4))
    game = _w2g4_game([altar, wall])
    game.players[1].library = [_w2g4_card("Mountain", "Basic Land — Mountain")] * 5

    game.activate_permanent_ability(
        0, "Altar of Dementia", ability_index=0, target_player_index=1,
        cost_permanent_index=1,
    )
    game.resolve_top_of_stack()

    assert not game.players[1].graveyard


def _w2g4_coloured(name, color):
    return CardDefinition(
        name=name, mana_cost="", type_line="Creature — Bear", oracle_text="",
        cmc=0.0, colors=(color,), color_identity=(color,), keywords=(),
        produced_mana=(), power="2", toughness="2",
        raw={"name": name, "type_line": "Creature — Bear"},
    )


def test_grindstone_repeats_while_the_two_milled_cards_share_a_colour(set_pool):
    """`{3}, {T}: Target player mills two cards. If two cards that share a
    color were milled this way, repeat this process.`

    The loop is the card. Four black cards on top of six colourless ones: two
    rounds of two black cards, then a round of two colourless ones that stops
    it. Six cards milled, four left.
    """
    grindstone = Permanent(card=set_pool("TMP")["Grindstone"])
    game = _w2g4_game([grindstone])
    black = _w2g4_coloured("Bog Imp", "B")
    plain = _w2g4_card("Ornithopter", "Artifact Creature — Thopter",
                       power=0, toughness=2)
    game.players[1].library = [black] * 4 + [plain] * 6

    result = game.activate_permanent_ability(
        0, "Grindstone", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert len(game.players[1].graveyard) == 6
    assert len(game.players[1].library) == 4


def test_grindstone_stops_on_two_colourless_cards(set_pool):
    """Colourless cards share no colour with anything, which is the card's
    famous stop — and the reason the test is over `colors`, not over sameness:
    two Ornithopters are the same card and still do not share a colour."""
    grindstone = Permanent(card=set_pool("TMP")["Grindstone"])
    game = _w2g4_game([grindstone])
    plain = _w2g4_card("Ornithopter", "Artifact Creature — Thopter",
                       power=0, toughness=2)
    game.players[1].library = [plain] * 10

    game.activate_permanent_ability(
        0, "Grindstone", ability_index=0, target_player_index=1,
    )
    game.resolve_top_of_stack()

    assert len(game.players[1].graveyard) == 2, "one round and no more"


def test_grindstone_empties_a_library_of_one_colour_and_terminates(set_pool):
    """An all-black library is the loop's worst case, and it terminates because
    an empty library mills nothing — the round writes an empty record and the
    condition reads it as False.

    This is the test that would hang if `resets` were dropped or if the
    stopping condition read the graveyard rather than the round's own record.
    """
    grindstone = Permanent(card=set_pool("TMP")["Grindstone"])
    game = _w2g4_game([grindstone])
    game.players[1].library = [_w2g4_coloured("Bog Imp", "B")] * 9

    game.activate_permanent_ability(
        0, "Grindstone", ability_index=0, target_player_index=1,
    )
    game.resolve_top_of_stack()

    assert not game.players[1].library
    assert len(game.players[1].graveyard) == 9
