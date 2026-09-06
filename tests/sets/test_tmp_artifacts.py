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
    assert "cards in hand" in result.details
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
