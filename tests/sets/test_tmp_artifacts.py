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


# --- W2G3: the untap cap and the empty-hand gate ---

from engine import Game, PlayerState
from engine.activation_restrictions import activation_denial
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.untap_restrictions import untap_restriction_for


def _w2g3a_game(*battlefields, catalog=None):
    """A two-seat game with each seat's permanents already down.

    Mana costs off: every test in this block is about a restriction rather
    than about paying for one.
    """
    seats = [
        PlayerState(name=f"P{index + 1}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def test_static_orb_caps_the_untap_step_at_two_permanents(set_pool, catalog_by_name):
    """"Players can't untap more than two **permanents** during their untap
    steps."

    CR 110.1 makes every battlefield object a permanent, so this is not a card
    type and ``Permanent.has_type`` has nothing to answer with — which is why
    the row went unread for the whole of wave 1 and the card reported
    unsupported. The cap is one scope word beside land / creature / artifact,
    and the untap step's per-type machinery does the rest.
    """
    orb = Permanent(card=set_pool("TMP")["Static Orb"])
    lands = [Permanent(card=catalog_by_name["Forest"]) for _ in range(3)]
    bears = [Permanent(card=catalog_by_name["Grizzly Bears"]) for _ in range(2)]
    game = _w2g3a_game([orb] + lands + bears, [])

    for permanent in game.players[0].battlefield:
        permanent.tapped = True
    orb.tapped = False

    assert game.resolve_untap_step(0) == 2, game.log
    # Across *types*, not two of each: the cap names permanents.
    assert sum(1 for p in game.players[0].battlefield if not p.tapped) == 3


def test_static_orb_offers_every_tapped_permanent_as_the_choice(set_pool, catalog_by_name):
    """The cap is a choice the untapping player makes (CR 502.3), so the
    candidate list the browser is offered has to be every tapped permanent —
    not the tapped *lands*, which is what a scope read as a card type would
    have produced.
    """
    orb = Permanent(card=set_pool("TMP")["Static Orb"])
    land = Permanent(card=catalog_by_name["Forest"])
    bear = Permanent(card=catalog_by_name["Grizzly Bears"])
    mox = Permanent(card=catalog_by_name["Mox Jet"])
    game = _w2g3a_game([orb, land, bear, mox], [])
    for permanent in (land, bear, mox):
        permanent.tapped = True

    options = game.get_untap_land_selection_options(0)

    assert options["limits"] == {"permanent": 2}
    assert options["max_count"] == 2
    assert options["candidate_indices"] == [1, 2, 3]


def test_static_orb_stops_restricting_while_it_is_tapped(set_pool, catalog_by_name):
    """"**As long as this artifact is untapped**" — the qualifier the table
    already stripped, kept honest for the new scope."""
    orb = Permanent(card=set_pool("TMP")["Static Orb"])
    lands = [Permanent(card=catalog_by_name["Forest"]) for _ in range(4)]
    game = _w2g3a_game([orb] + lands, [])
    for permanent in game.players[0].battlefield:
        permanent.tapped = True

    assert game.resolve_untap_step(0) == 5, "the Orb was tapped, so nothing capped"


def test_static_orb_and_winter_orb_are_both_read(set_pool, catalog_by_name):
    """Two caps in force at once, one over lands and one over everything. The
    step asks each scope separately, so a land is under both and the tighter
    one is what it obeys."""
    orb = Permanent(card=set_pool("TMP")["Static Orb"])
    winter = Permanent(card=catalog_by_name["Winter Orb"])
    lands = [Permanent(card=catalog_by_name["Forest"]) for _ in range(3)]
    bears = [Permanent(card=catalog_by_name["Grizzly Bears"]) for _ in range(2)]
    game = _w2g3a_game([orb, winter] + lands + bears, [])
    for permanent in game.players[0].battlefield:
        permanent.tapped = True
    orb.tapped = False
    winter.tapped = False

    assert game.resolve_untap_step(0) == 2, "Static Orb's cap over everything"

    untapped = [p.card.name for p in game.players[0].battlefield if not p.tapped]
    assert untapped.count("Forest") == 1, "Winter Orb allows one land"
    assert untapped.count("Grizzly Bears") == 1, "and the second slot went elsewhere"


def test_static_orbs_restriction_is_the_one_the_table_reads(set_pool):
    """The scope word and the number, off the printed line — so a card printed
    "more than three permanents" needs no code."""
    orb = set_pool("TMP")["Static Orb"]
    restriction = untap_restriction_for(orb.oracle_text)

    assert restriction.scope == "permanent"
    assert restriction.limit == 2
    assert restriction.only_while_source_untapped is True
    assert compile_card_oracle(orb).supported


def test_fools_tome_refuses_to_draw_while_you_hold_a_card(set_pool, catalog_by_name):
    """"Activate only if you have no cards in hand."

    The failure this file's own module docstring names: an unenforced
    restriction is not a dead ability, it is one that works more often than the
    card allows. The clause is a row in ``engine/activation_restrictions.py``
    and the support gate reads the same row, so a Tome that could be tapped
    with a hand full of cards would be unsupported rather than silently
    generous.
    """
    tome = Permanent(card=set_pool("TMP")["Fool's Tome"])
    game = _w2g3a_game([tome], [])
    game.players[0].hand = [catalog_by_name["Forest"]]
    game.players[0].library = [catalog_by_name["Island"], catalog_by_name["Plains"]]
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Fool's Tome", permanent_index=0)

    assert not result.supported
    assert "only with no cards in hand" in result.details, (
        "the message names the printed count, not 'that many'"
    )
    assert len(game.players[0].hand) == 1, "nothing was drawn"
    assert not tome.tapped, "and nothing was paid"


def test_fools_tome_draws_with_an_empty_hand(set_pool, catalog_by_name):
    """The other half. A restriction row that answered "no" for every board
    would be this file's failure mode pointed the other way."""
    tome = Permanent(card=set_pool("TMP")["Fool's Tome"])
    game = _w2g3a_game([tome], [])
    game.players[0].library = [catalog_by_name["Island"], catalog_by_name["Plains"]]
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Fool's Tome", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert len(game.players[0].hand) == 1
    assert tome.tapped


def test_the_hand_count_clause_is_one_row_for_both_printings(set_pool, catalog_by_name):
    """Library of Alexandria's "exactly seven" and the Tome's "no" are one
    sentence with the number changed, so they are one row and the number is
    payload — the shape every parameterised row in that table has."""
    tome = Permanent(card=set_pool("TMP")["Fool's Tome"])
    game = _w2g3a_game([tome], [])
    game.players[0].hand = [catalog_by_name["Forest"]] * 7

    assert activation_denial(
        game, 0, tome, "Activate only if you have exactly seven cards in hand."
    ) is None
    assert activation_denial(
        game, 0, tome, "Activate only if you have no cards in hand."
    ) is not None


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
    # And the picker knows the ability targets. A new control-flow wrapper is
    # invisible to `targeting.py`'s unwrap list until somebody adds it, and the
    # failure is the Roots class: the client sends a bare activation and the
    # ability mills whoever the resolution happened to be holding.
    program = compile_card_oracle(set_pool("TMP")["Grindstone"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec is not None and spec.get("kind") == "player"


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


def test_scroll_rack_swaps_the_exiled_pile_for_the_same_number_off_the_top(set_pool):
    """`{1}, {T}: Exile any number of cards from your hand face down. Put that
    many cards from the top of your library into your hand. Then look at the
    exiled cards and put them on top of your library in any order.`

    Three steps and one resolution. The count of the second is the answer to
    the first, so the exile prompt suspends the resolution; the third drains
    the pile back onto the library and hands the order to the same seat.
    """
    from engine.linked_exile import linked_entries

    rack = Permanent(card=set_pool("TMP")["Scroll Rack"])
    hand = [_w2g4_card(f"Hand{i}", "Instant") for i in range(3)]
    library = [_w2g4_card(f"Deck{i}", "Instant") for i in range(5)]
    game = _w2g4_game([rack], p0_hand=hand)
    game.players[0].library = list(library)

    game.activate_permanent_ability(0, "Scroll Rack", ability_index=0)
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("exile_hand_pile_choice")))
    assert [c["name"] for c in
            [{"name": game.players[0].hand[i].name}
             for i in game.live_exile_hand_pile_choices(prompt)]] == [
        "Hand0", "Hand1", "Hand2",
    ]
    assert game.confirm_exile_hand_pile(0, [0, 2])

    # Two exiled, two off the top of the library into the hand.
    assert sorted(c.name for c in game.players[0].hand) == ["Deck0", "Deck1", "Hand1"]
    # The pile went back on top of the library, so the reorder prompt is open
    # over exactly those two.
    assert not linked_entries(rack), "the pile is drained when it goes back"
    reorder = next(iter(game.pending_choices_of("reorder_library")))
    assert reorder.data["top_count"] == 2
    assert [c.name for c in game.players[0].library[:2]] == ["Hand0", "Hand2"]
    assert game.confirm_reorder_library(0, new_order=[1, 0], shuffle=False)
    assert [c.name for c in game.players[0].library] == [
        "Hand2", "Hand0", "Deck2", "Deck3", "Deck4",
    ]


def test_scroll_rack_exiling_none_is_a_legal_answer_that_draws_none(set_pool):
    """"Any number" includes zero, and it is an *answer* rather than a decline:
    the sentence behind it puts that many cards into the hand, so an activation
    that exiles nothing legally does nothing."""
    rack = Permanent(card=set_pool("TMP")["Scroll Rack"])
    hand = [_w2g4_card("Hand0", "Instant")]
    game = _w2g4_game([rack], p0_hand=hand)
    game.players[0].library = [_w2g4_card("Deck0", "Instant")] * 3

    game.activate_permanent_ability(0, "Scroll Rack", ability_index=0)
    game.resolve_top_of_stack()
    assert game.confirm_exile_hand_pile(0, [])

    assert [c.name for c in game.players[0].hand] == ["Hand0"]
    assert len(game.players[0].library) == 3
    assert not game.players[0].exile


def test_scroll_rack_puts_cards_into_hand_without_drawing_them(set_pool):
    """CR 121.3: an effect that says "put the top card of your library into
    your hand" is **not** a draw. The engine's own record of what was drawn
    this turn is the check — a card routed through the draw seam would appear
    in it, and every "whenever you draw" on the board would have fired.
    """
    rack = Permanent(card=set_pool("TMP")["Scroll Rack"])
    game = _w2g4_game([rack], p0_hand=[_w2g4_card("Hand0", "Instant")])
    game.players[0].library = [_w2g4_card("Deck0", "Instant")] * 3

    game.activate_permanent_ability(0, "Scroll Rack", ability_index=0)
    game.resolve_top_of_stack()
    assert game.confirm_exile_hand_pile(0, [0])

    assert [c.name for c in game.players[0].hand] == ["Deck0"]
    assert not game.players[0].cards_drawn_this_turn, (
        "putting a card into a hand is not drawing it"
    )


def test_phyrexian_grimoire_lets_the_opponent_pick_which_card_is_lost(set_pool):
    """`{4}, {T}: Target opponent chooses one of the top two cards of your
    graveyard. Exile that card and put the other one into your hand.`

    CR 404.2 keeps a graveyard in the order cards reached it, newest on top, so
    "the top two" are the *last* two of the pile — the opposite end from a
    library. No reveal happens: CR 400.2 makes a graveyard public and there is
    nothing to show anybody.
    """
    grimoire = Permanent(card=set_pool("TMP")["Phyrexian Grimoire"])
    # The *opponent* chooses, and this prompt takes its default at arm for a
    # non-interactive seat — so seat 1 has to be one for the answer to be asked.
    game = _w2g4_game([grimoire], interactive=(0, 1))
    game.players[0].graveyard = [
        _w2g4_card("Bottom", "Instant"),
        _w2g4_card("Second", "Instant"),
        _w2g4_card("Top", "Instant"),
    ]

    result = game.activate_permanent_ability(
        0, "Phyrexian Grimoire", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("opponent_picks_revealed")))
    assert prompt.player_index == 1, "the *opponent* chooses"
    assert prompt.data["cards"] == ["Top", "Second"]
    assert game.confirm_opponent_picks_revealed(1, 0)

    assert [c.name for c in game.players[0].exile] == ["Top"]
    assert [c.name for c in game.players[0].hand] == ["Second"]
    assert [c.name for c in game.players[0].graveyard] == ["Bottom"]


def test_phyrexian_grimoire_over_one_card_still_moves_it(set_pool):
    """Fewer cards than the printed number is an ordinary board: the pick is
    made from what is there, and with nothing left over the "other one" clause
    moves nothing rather than reaching further down the pile."""
    grimoire = Permanent(card=set_pool("TMP")["Phyrexian Grimoire"])
    game = _w2g4_game([grimoire], interactive=(0, 1))
    game.players[0].graveyard = [_w2g4_card("Only", "Instant")]

    game.activate_permanent_ability(
        0, "Phyrexian Grimoire", ability_index=0, target_player_index=1,
    )
    game.resolve_top_of_stack()
    prompt = next(iter(game.pending_choices_of("opponent_picks_revealed")))
    assert prompt.data["cards"] == ["Only"]
    assert game.confirm_opponent_picks_revealed(1, 0)

    assert [c.name for c in game.players[0].exile] == ["Only"]
    assert not game.players[0].hand


# --- W2G2: Magnetic Web's blocking requirement (CR 509.1c) ---

from engine import Game, PlayerState, ai_policy
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


def _w2g2_web_board(web):
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p0.battlefield.append(_nosick(Permanent(card=web)))
    p0.battlefield.append(
        _nosick(Permanent(card=_mk_creature_card("Magnetized Ogre", 3, 3)))
    )
    p1.battlefield.append(
        _nosick(Permanent(card=_mk_creature_card("Magnetized Wall", 0, 4)))
    )
    p1.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Free Wall", 0, 4))))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    add_counters(p0.battlefield[1], "magnet", 1)
    add_counters(p1.battlefield[0], "magnet", 1)
    return game, p0, p1


def test_w2g2_magnetic_web_compels_the_magnetized_creatures_to_block(set_pool):
    """``Whenever a creature with a magnet counter on it attacks, all creatures
    with magnet counters on them block that creature this turn if able.``

    A sentence that was **claimed by nothing** while the card reported itself
    supported — ``parse_coverage`` was the only instrument that could see it.
    Three pieces behind it: a counter-defined noun phrase
    (``ObjectFilter.with_named_counter``), an unnarrowed block requirement over the
    set it describes, and "that creature" as the attacker the trigger's event
    froze.
    """
    game, p0, p1 = _w2g2_web_board(set_pool("TMP")["Magnetic Web"])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [1], 1)[0]
    while game.stack:
        game.resolve_top_of_stack()

    ogre_id = p0.battlefield[1].permanent_id
    assert p1.battlefield[0].metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] == [ogre_id]
    assert p1.battlefield[1].metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None

    game.advance_combat_phase()
    assert game.declare_blockers(1, {}) == (
        False, "Magnetized Wall must block Magnetized Ogre this turn if able"
    )
    assert game.declare_blockers(1, {1: 1})[0] is False, "the free Wall is not compelled"
    assert game.declare_blockers(1, {0: 1})[0], game.log


def test_w2g2_magnetic_web_stays_quiet_for_an_unmagnetized_attacker(set_pool):
    """The trigger's own narrowing. Read too widely it would compel a block on
    every attack in the game, which is the direction a dropped filter always
    takes."""
    game, p0, p1 = _w2g2_web_board(set_pool("TMP")["Magnetic Web"])
    p0.battlefield[1].metadata.pop("magnet_counters", None)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [1], 1)[0]
    while game.stack:
        game.resolve_top_of_stack()
    assert p1.battlefield[0].metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0], game.log


def test_w2g2_magnetic_web_is_supported(set_pool):
    assert compile_card_oracle(set_pool("TMP")["Magnetic Web"]).supported


def _w2g2_magnet_attack_board(web):
    """One Web, two magnetized creatures and one without, against a Wall."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p0.battlefield.append(_nosick(Permanent(card=web)))
    p0.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Magnet A", 2, 2))))
    p0.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Magnet B", 2, 2))))
    p0.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Free Bear", 2, 2))))
    p1.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Wall", 0, 4))))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    add_counters(p0.battlefield[1], "magnet", 1)
    add_counters(p0.battlefield[2], "magnet", 1)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game, p0, p1


def test_w2g2_magnetic_web_drags_the_other_magnets_into_the_attack(set_pool):
    """``If a creature with a magnet counter on it attacks, all creatures with
    magnet counters on them attack if able.``

    Ekundu Cyclops' sentence with both halves widened from "this creature" to a
    set — CR 508.1d's requirement with a condition about the *declaration being
    made* rather than about the board, which is why it is checked where the
    declaration is in hand rather than by the per-creature predicate.

    The identity check is what keeps it from being self-satisfying: a lone
    magnetized attacker is the creature its own condition names, so without it
    the requirement would demand a creature attack because it is attacking.
    """
    game, p0, p1 = _w2g2_magnet_attack_board(set_pool("TMP")["Magnetic Web"])
    assert game.declare_attackers(0, [], 1)[0], "the condition is false"
    assert game.declare_attackers(0, [3], 1)[0], "the free Bear triggers nothing"
    assert game.declare_attackers(0, [1], 1) == (
        False, "Magnet B must attack if able"
    )
    assert game.declare_attackers(0, [1, 2], 1)[0], game.log


def test_w2g2_the_ai_declares_a_legal_magnet_attack(set_pool):
    """The AI reads the same predicate the declaration does, so it never
    proposes the half-attack the engine would bounce."""
    game, p0, p1 = _w2g2_magnet_attack_board(set_pool("TMP")["Magnetic Web"])
    chosen = sorted(ai_policy.choose_attackers(game, 0))
    assert game.declare_attackers(0, chosen, 1)[0], (chosen, game.log)


# --- W3G3: Echo Chamber's opponent-made pick and the token behind it ---

from engine import Game, PlayerState
from engine.delayed_triggers import fire_delayed_triggers
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _mk_creature_card, _nosick


def _w3g3_game(p0_permanents, p1_permanents, *, interactive=(0, 1)):
    seats = [
        PlayerState(name="P0", battlefield=list(p0_permanents)),
        PlayerState(name="P1", battlefield=list(p1_permanents)),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game


def test_echo_chamber_copies_the_creature_the_opponent_picked(set_pool):
    """`{4}, {T}: An opponent chooses target creature they control. Create a
    token that's a copy of that creature. That token gains haste until end of
    turn. Exile the token at the beginning of the next end step.`

    Four sentences and four instructions, which is the whole shape of the card:
    the pick belongs to another seat, so it is the ordinary ``choose_permanent``
    prompt; the copy reads what that prompt recorded; the haste grant reads what
    the copy recorded; and the delayed exile reads the token the *permanent*
    made. Nothing here is fused, and nothing here is name-keyed.
    """
    chamber = Permanent(card=set_pool("TMP")["Echo Chamber"])
    theirs = Permanent(card=_mk_creature_card("Bear", 2, 2))
    decoy = Permanent(card=_mk_creature_card("Decoy", 1, 1))
    game = _w3g3_game([chamber], [theirs, decoy])
    _nosick(chamber)

    result = game.activate_permanent_ability(0, "Echo Chamber", ability_index=0)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    # The *opponent* is asked, out of their own battlefield — "they control".
    prompt = next(iter(game.pending_choices_of("permanent_choice")))
    assert prompt.player_index == 1
    offered = {perm.card.name for perm in game.live_permanent_choices(prompt)}
    assert offered == {"Bear", "Decoy"}

    assert game.confirm_permanent_choice(1, game.permanent_id_of(theirs))

    # The token is the caster's, is a copy of what the opponent chose, and has
    # haste — which is the only reason the card is worth activating.
    tokens = [
        perm for perm in game.controlled_by(0)
        if perm.metadata.get("is_token")
    ]
    assert [perm.card.name for perm in tokens] == ["Bear"]
    assert game._has_keyword(tokens[0], "haste")


def test_echo_chamber_offers_no_target_picker(set_pool):
    """The printed word is "target" and the seat that picks is not the ability's
    controller, which CR 601.2c has no room for — so the pick is made at
    resolution, exactly as ``lowering/control_changes.py`` records for Preacher.

    The consequence is asserted rather than assumed: an activation spec here
    would make the *controller* announce the creature, which is the one seat the
    card says must not choose.
    """
    program = compile_card_oracle(set_pool("TMP")["Echo Chamber"])
    ability = program.activated_abilities[0]
    assert derive_activation_spec(ability) is None


def test_echo_chamber_exiles_its_token_at_the_next_end_step(set_pool):
    """"Exile the token at the beginning of the next end step" names the token
    this *permanent* made (``created_with_source``), so the delay survives the
    resolution that armed it."""
    chamber = Permanent(card=set_pool("TMP")["Echo Chamber"])
    theirs = Permanent(card=_mk_creature_card("Bear", 2, 2))
    game = _w3g3_game([chamber], [theirs])
    _nosick(chamber)

    game.activate_permanent_ability(0, "Echo Chamber", ability_index=0)
    game.resolve_top_of_stack()
    game.confirm_permanent_choice(1, game.permanent_id_of(theirs))
    assert any(
        perm.metadata.get("is_token") for perm in game.controlled_by(0)
    )

    fire_delayed_triggers(game, "next_end_step")
    game.resolve_stack()
    assert not [
        perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")
    ], "the token is exiled at the beginning of the next end step"


# --- W3G3: Booby Trap's two-value entry choice, its draw reveals and its trap ---

from engine import Game, PlayerState
from engine.draw_reveals import reveals_every_draw
from engine.enter_effects import enter_effect_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w3g3_trap_card(name, type_line="Creature — Bear"):
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text="",
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": ""},
    )


def _w3g3_trap_game(trap, victim_library, *, interactive=()):
    seats = [
        PlayerState(name="P0", battlefield=[trap]),
        PlayerState(name="P1", library=list(victim_library)),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    game._initialize_permanent_state(trap, 0, target_player_index=1)
    return game


def test_booby_trap_records_both_halves_of_its_entry_choice(set_pool):
    """`As this artifact enters, choose an opponent and a card name other than a
    basic land card name.`

    CR 614.1c: one choice with two answers, so one prompt writes both records —
    the seat under the key every "the chosen player" reads and the name under
    the key every "the chosen name" reads.
    """
    trap = Permanent(card=set_pool("TMP")["Booby Trap"])
    game = _w3g3_trap_game(trap, [_w3g3_trap_card("Elf")], interactive=(0,))

    assert trap.metadata.get("chosen_player_index") == 1
    prompt = next(iter(game.pending_choices_of("enter_choice")))
    assert prompt.data["needs_card_name"] is True
    assert prompt.data["opponents"] == [1]

    assert game.confirm_enter_choice(0, opponent_index=1, card_name="Wildfire")
    assert trap.metadata["chosen_card_name"] == "Wildfire"


def test_booby_trap_refuses_a_basic_land_name(set_pool):
    """"…other than a basic land card name" is the one restriction CR 201.2
    leaves on the choice, and it is refused rather than repaired — quietly
    keeping the default would tell the player they had chosen something they
    had not."""
    trap = Permanent(card=set_pool("TMP")["Booby Trap"])
    game = _w3g3_trap_game(trap, [_w3g3_trap_card("Elf")], interactive=(0,))

    assert not game.confirm_enter_choice(0, opponent_index=1, card_name="Island")
    assert trap.metadata.get("chosen_card_name") != "Island"


def test_booby_trap_reveals_the_chosen_players_draws(set_pool):
    """`The chosen player reveals each card they draw.` — every draw, and the
    seat is the one the *permanent* recorded, so the scan is over the whole
    board rather than over the reader's own permanents."""
    trap = Permanent(card=set_pool("TMP")["Booby Trap"])
    game = _w3g3_trap_game(trap, [_w3g3_trap_card("Elf")])

    assert reveals_every_draw(game, 1) is True
    assert reveals_every_draw(game, 0) is False, "the trap's controller draws in private"

    game._draw_with_replacements(game.players[1], 1)
    assert any("revealed Elf" in line for line in game.log)


def test_booby_trap_springs_on_the_chosen_name_and_not_before(set_pool):
    """`When the chosen player draws a card with the chosen name, sacrifice this
    artifact. If you do, this artifact deals 10 damage to that player.`

    The Rock Hydra test: the damage is read off a life total, and the *first*
    draw is asserted not to spring it — a trigger with the narrowing dropped
    would fire on any draw at all, which is the failure this card's two records
    exist to prevent.
    """
    trap = Permanent(card=set_pool("TMP")["Booby Trap"])
    game = _w3g3_trap_game(
        trap,
        [_w3g3_trap_card("Elf"), _w3g3_trap_card("Wildfire")],
    )
    trap.metadata["chosen_card_name"] = "Wildfire"

    game._draw_with_replacements(game.players[1], 1)   # Elf
    game.check_state_based_actions()
    game.resolve_stack()
    assert game.players[1].life == 20, "a different card does not spring the trap"
    assert any(p.card.name == "Booby Trap" for p in game.controlled_by(0))

    game._draw_with_replacements(game.players[1], 1)   # Wildfire
    game.check_state_based_actions()
    game.resolve_stack()
    assert game.players[1].life == 10
    assert not [p for p in game.controlled_by(0) if p.card.name == "Booby Trap"]


def test_booby_trap_with_no_name_recorded_never_springs(set_pool):
    """An empty name matches nothing rather than everything: springing on the
    first draw is the opposite of what "nothing was named" means."""
    trap = Permanent(card=set_pool("TMP")["Booby Trap"])
    game = _w3g3_trap_game(trap, [_w3g3_trap_card("Elf")])
    trap.metadata["chosen_card_name"] = ""

    game._draw_with_replacements(game.players[1], 1)
    game.check_state_based_actions()
    game.resolve_stack()
    assert game.players[1].life == 20
    assert any(p.card.name == "Booby Trap" for p in game.controlled_by(0))


def test_booby_trap_claims_every_printed_line(set_pool):
    """Three sentences, three readers: the entry pair, the draw-reveal table and
    the trigger. A card supported on one of them while another is unread is the
    debt `parse_coverage` exists to find, and it is checked here per card."""
    card = set_pool("TMP")["Booby Trap"]
    program = compile_card_oracle(card)
    assert program.supported
    assert enter_effect_line(
        "As this artifact enters, choose an opponent and a card name other "
        "than a basic land card name.", card.name,
    ) == "chooses an opponent and a card name as it enters"
    assert [t.condition.kind for t in program.triggered_abilities] == ["draws_card"]
# --- W3G4: Excavator (a keyword whose word the cost decides) ---

import pytest as _w3g4a_pytest

from engine import Game as _W3G4aGame
from engine import PlayerState as _W3G4aPlayerState
from engine.card_loader import load_cards as _w3g4a_load_cards
from engine.card_loader import manifest_set_paths as _w3g4a_manifest_set_paths
from engine.models import Permanent as _W3G4aPermanent
from engine.oracle import compile_card_oracle as _w3g4a_compile
from tests.helpers import _mk_card as _w3g4a_mk_card
from tests.helpers import _nosick as _w3g4a_nosick


@_w3g4a_pytest.fixture(scope="module")
def _w3g4a_basics():
    """The basic lands, which Tempest does not print — from the shipped pool the
    manifest already resolves, never a spelled-out card file."""
    return {
        card.name: card
        for card in _w3g4a_load_cards(_w3g4a_manifest_set_paths())
        if card.name in ("Island", "Forest", "Plains")
    }


def _w3g4a_dig(set_pool, land_card):
    """Excavator, one land to eat, and a Bear to give the walk to."""
    digger = _w3g4a_nosick(_W3G4aPermanent(card=set_pool("TMP")["Excavator"]))
    land = _W3G4aPermanent(card=land_card)
    bear = _w3g4a_nosick(
        _W3G4aPermanent(card=_w3g4a_mk_card("Grizzly", "{1}{G}", "Creature - Bear", ""))
    )
    game = _W3G4aGame(players=[
        _W3G4aPlayerState(name="P1", battlefield=[digger, land, bear]),
        _W3G4aPlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    return game, bear, land


def _w3g4a_activate(game, bear):
    result = game.activate_permanent_ability(
        game_seat := 0, "Excavator", ability_index=0,
        target_player_index=game_seat,
        target_permanent_index=game.battlefield_index_of(bear),
    )
    assert result.supported, result.details
    while game.stack:
        game.resolve_top_of_stack()
    return result


def test_excavator_compiles_with_no_printed_keyword(set_pool):
    """"Target creature gains landwalk of each of the land types of the
    sacrificed land until end of turn."

    The payload carries **no** keyword, and must not: CR 702.14a builds a
    landwalk's name out of a land type, and which land type is a fact about the
    cost that was paid rather than about the sentence. What travels is the name
    of the record the words are built from.
    """
    program = _w3g4a_compile(set_pool("TMP")["Excavator"])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "grant_target_keyword_until_eot"
    assert ability.instruction.payload["keywords"] == ()
    assert ability.instruction.payload["landwalk_from"] == "sacrificed_for_cost"
    # The cost is the other half: a *basic* land, and the tap.
    assert ability.cost.requires_tap is True
    assert ability.cost.sacrifice_filter == {
        "type_filter": "land", "supertypes": ["basic"]
    }


@_w3g4a_pytest.mark.parametrize(
    "land,walk", [("Island", "islandwalk"), ("Forest", "forestwalk")]
)
def test_excavator_grants_the_walk_the_sacrificed_land_names(
    set_pool, _w3g4a_basics, land, walk
):
    """The word follows the land the cost ate, which is the whole card.

    The record is the *cost's* — `sacrificed_for_cost`, written by
    `mixins/stack/activation.py` when the cost is paid. It is last-known
    information (CR 608.2h): by the time this resolves the land is in a
    graveyard, and nothing on the battlefield can say what it was.
    """
    game, bear, sacrificed = _w3g4a_dig(set_pool, _w3g4a_basics[land])
    assert not game._has_keyword(bear, walk)

    _w3g4a_activate(game, bear)

    assert not game.is_on_battlefield(sacrificed)
    assert game._has_keyword(bear, walk)
    # And only that walk: a land names the types it has and no others.
    other = "forestwalk" if walk == "islandwalk" else "islandwalk"
    assert not game._has_keyword(bear, other)


def test_the_granted_walk_actually_restricts_a_block(set_pool, _w3g4a_basics):
    """The Rock Hydra question, asked of the grant: a keyword in layer 6 that
    nothing reads is a card that reports supported and does nothing.

    CR 702.14b/c: the creature can't be blocked as long as the defending player
    controls a land of the named type — so the same blocker answers differently
    on either side of one Island.
    """
    game, bear, _sacrificed = _w3g4a_dig(set_pool, _w3g4a_basics["Island"])
    _w3g4a_activate(game, bear)

    wall = _w3g4a_nosick(
        _W3G4aPermanent(card=_w3g4a_mk_card("Wall", "{1}", "Creature - Wall", ""))
    )
    game.players[1].battlefield = [wall, _W3G4aPermanent(card=_w3g4a_basics["Island"])]
    assert not game._can_block_attacker(wall, bear)

    game.players[1].battlefield = [wall]
    assert game._can_block_attacker(wall, bear)


def test_a_land_with_no_land_type_grants_nothing(set_pool):
    """The direction a missing word must fail in. A land with no subtype names
    no landwalk, so nothing is granted — where a fallback word would be an
    evasion the card never named.

    It cannot be paid for with one (the cost says "a basic land"), so the case
    is reached by handing the handler the record directly, which is exactly
    what a future card printing "the sacrificed land" over a wider cost would
    do.
    """
    from engine.landwalk import landwalk_abilities_of

    colorless = _W3G4aPermanent(
        card=_w3g4a_mk_card("Wastes", "", "Land", "")
    )
    game = _W3G4aGame(players=[
        _W3G4aPlayerState(name="P1", battlefield=[colorless]),
        _W3G4aPlayerState(name="P2"),
    ])
    assert landwalk_abilities_of(colorless) == ()
    # …and a creature is not a land at all.
    bear = _W3G4aPermanent(card=_w3g4a_mk_card("Grizzly", "{1}{G}", "Creature - Bear", ""))
    game.players[0].battlefield.append(bear)
    assert landwalk_abilities_of(bear) == ()


# --- W3G4: Phyrexian Splicer (an ability chosen when the ability is activated) ---


def _w3g4b_creature(name, text):
    from tests.helpers import _mk_card, _nosick
    from engine.models import Permanent

    return _nosick(Permanent(card=_mk_card(name, "{2}", "Creature - Human", text)))


def _w3g4b_board(set_pool):
    from engine import Game, PlayerState
    from engine.models import Permanent
    from tests.helpers import _nosick

    splicer = _nosick(Permanent(card=set_pool("TMP")["Phyrexian Splicer"]))
    flier = _w3g4b_creature("Cloud", "Flying")
    ground = _w3g4b_creature("Grizzly", "")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[splicer, flier, ground]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    return game, splicer, flier, ground


def test_phyrexian_splicer_compiles_with_its_choice_in_the_cost(set_pool):
    """"{2}, {T}, **Choose flying, first strike, trample, or shadow**: …"

    CR 602.1a puts everything before the colon in the activation cost, and
    CR 601.2b (through CR 602.2b) announces the choices there — *before*
    CR 601.2c chooses targets. That ordering is the whole reason the clause is
    read as a cost: the sentence behind it says "target creature with the
    chosen ability", which a word picked at resolution would narrow too late.

    Two readers have to agree about it — the grammar's cost parser gates whether
    the line compiles, and `oracle.parse_activated_ability_cost` produces the
    cost that is charged — so the options are asserted off the compiled cost.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("TMP")["Phyrexian Splicer"])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    assert ability.cost.chosen_keyword_options == (
        "flying", "first strike", "trample", "shadow"
    )
    assert ability.instruction.kind == "move_chosen_keyword_between_targets"
    # One instruction, not a removal and a grant in a sequence: the clauses name
    # different creatures (the printed "another", CR 601.2c) and every
    # one-target handler reads the first entry of the target list.
    targets = ability.instruction.payload["targets"]
    assert targets["count"] == 2 and targets["distinct"] is True
    # The first slot carries the narrowing and the second does not — the card
    # takes the ability from a creature that has it and gives it to any other.
    assert targets["filters"][0]["chosen_keyword"] is True
    assert "chosen_keyword" not in targets["filters"][1]


def test_phyrexian_splicer_moves_the_chosen_ability(set_pool):
    """The whole card, in a game: flying leaves the creature that had it and
    lands on the one that did not."""
    game, _splicer, flier, ground = _w3g4b_board(set_pool)
    assert game._has_keyword(flier, "flying")
    assert not game._has_keyword(ground, "flying")

    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", ability_index=0, chosen_keyword="flying",
        target_permanent_ids=[flier.permanent_id, ground.permanent_id],
    )
    assert result.supported, result.details
    while game.stack:
        game.resolve_top_of_stack()

    assert not game._has_keyword(flier, "flying")
    assert game._has_keyword(ground, "flying")


def test_the_removal_and_the_grant_both_end_with_the_turn(set_pool):
    """One printed duration governs both halves of one sentence (CR 611.2b), so
    the creature that lost the ability has it again at cleanup — a removal given
    no lifetime would be permanent, which the card does not say."""
    game, _splicer, flier, ground = _w3g4b_board(set_pool)
    game.activate_permanent_ability(
        0, "Phyrexian Splicer", ability_index=0, chosen_keyword="flying",
        target_permanent_ids=[flier.permanent_id, ground.permanent_id],
    )
    while game.stack:
        game.resolve_top_of_stack()
    game.resolve_cleanup_step(0)

    assert game._has_keyword(flier, "flying")
    assert not game._has_keyword(ground, "flying")


def test_an_ability_the_card_never_offered_is_refused_with_nothing_paid(set_pool):
    """CR 602.2b: the options are the sentence's, not a catalog's. Refused
    rather than substituted, and refused *before* the cost — the Splicer is
    still untapped."""
    game, splicer, flier, ground = _w3g4b_board(set_pool)
    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", ability_index=0, chosen_keyword="lifelink",
        target_permanent_ids=[flier.permanent_id, ground.permanent_id],
    )
    assert not result.supported
    assert "lifelink" in result.details
    assert not splicer.tapped
    assert game._has_keyword(flier, "flying")


def test_a_seat_that_names_no_ability_takes_the_stated_default(set_pool):
    """The stated policy: the first printed option some creature on the
    battlefield actually has. A real answer rather than the first word, which on
    a board with no first-striker would leave the move with no legal first
    target — and deterministic, which the AI-simulation regressions depend on.
    """
    from engine.handlers._common import CHOSEN_ABILITY

    game, splicer, flier, ground = _w3g4b_board(set_pool)
    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", ability_index=0,
        target_permanent_ids=[flier.permanent_id, ground.permanent_id],
    )
    assert result.supported, result.details
    assert splicer.metadata[CHOSEN_ABILITY] == "flying"
    while game.stack:
        game.resolve_top_of_stack()
    assert game._has_keyword(ground, "flying")


def test_the_picker_offers_the_words_the_card_printed(set_pool):
    """The client asks for the ability before it asks for a target, off the same
    spec the target picker is built from — so the list offered and the list the
    announcement accepts are one list (idiom 9)."""
    game, _splicer, _flier, _ground = _w3g4b_board(set_pool)
    spec = game.activation_target_spec(0, 0)
    assert spec["keyword_options"] == [
        "flying", "first strike", "trample", "shadow"
    ]
