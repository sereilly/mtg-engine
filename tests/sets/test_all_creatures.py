"""Per-card tests for Alliances' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G2: library-top costs ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_card(name: str, type_line: str, mana_cost: str = "") -> CardDefinition:
    """A vanilla card to stack a library with, invented so the only thing that
    varies between the halves of each pair below is the characteristic under
    test."""
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(len(mana_cost) // 3),
        type_line=type_line, oracle_text="", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w1g2_board(set_pool, name: str, library: list[CardDefinition]):
    """*name* on the battlefield with *library* under it, ready to activate."""
    perm = Permanent(card=set_pool("ALL")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=list(library)),
        PlayerState(name="P2", library=[_w1g2_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


def test_royal_herbalist_exiles_the_top_card_to_gain_a_life(set_pool):
    """"{2}, Exile the top card of your library: You gain 1 life."

    CR 118.1: paying the cost is carrying out the printed action, so the card
    is in exile before the ability is on the stack — and the life arrives
    whatever that card was.
    """
    game, _perm = _w1g2_board(
        set_pool, "Royal Herbalist", [_w1g2_card("Top Card", "Artifact")] * 3
    )
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert result.supported, result.details
    assert len(me.library) == 2, "the cost came off the library on activation"
    assert [card.name for card in me.exile] == ["Top Card"]
    game.resolve_top_of_stack()
    assert me.life == 21


def test_royal_herbalist_cannot_be_activated_with_an_empty_library(set_pool):
    """CR 118.3: a player can't pay a cost without the resources to pay it
    *fully*, so an empty library makes this ability unactivatable — never a
    free one, and never one that exiles nothing and gains the life anyway."""
    game, _perm = _w1g2_board(set_pool, "Royal Herbalist", [])
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert not result.supported
    assert me.life == 20, "nothing was gained"
    assert not game.stack, "the ability never reached the stack"


def test_seasoned_tactician_needs_four_cards_for_its_four_card_cost(set_pool):
    """"{3}, Exile the top four cards of your library: …"

    The counted cost, and CR 118.3's "fully" is the whole of it: three cards
    do not pay a four-card cost, and the three are still there afterwards.
    """
    game, _perm = _w1g2_board(
        set_pool, "Seasoned Tactician", [_w1g2_card("Card", "Artifact")] * 3
    )
    me = game.players[0]
    assert not game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert len(me.library) == 3 and not me.exile

    me.library.append(_w1g2_card("Card", "Artifact"))
    assert game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert not me.library and len(me.exile) == 4


def test_storm_elemental_reads_back_the_card_its_cost_exiled(set_pool):
    """"{U}, Exile the top card of your library: If the exiled card is a snow
    land, this creature gets +1/+1 until end of turn."

    The sentence asks about the card the *cost* ate, which by resolution is in
    exile (CR 608.2h) — so the answer is the record the payment kept, and the
    snow supertype is what it is asked for.
    """
    snow = _w1g2_card("Snowy", "Basic Snow Land - Mountain")
    plain = _w1g2_card("Plain Land", "Basic Land - Mountain")

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [snow, snow])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (4, 5)

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [plain, plain])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (3, 4), (
        "an ordinary land is not a snow land"
    )


def test_chaos_harlequin_branches_on_the_card_its_effect_exiled(set_pool):
    """"{R}: Exile the top card of your library. If that card is a land card,
    this creature gets -4/-0 until end of turn. Otherwise, this creature gets
    +2/+0 until end of turn."

    The exile here is the *effect*, not the cost, and "that card" is the
    pronoun for what the step in front of it moved — the same back-reference
    "it was" spells with a bare pronoun.
    """
    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Plain Land", "Basic Land - Mountain")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (-2, 4)

    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Some Spell", "Artifact")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (4, 4)


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the graveyards these tests build."""
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_krovikan_horror_returns_itself_at_the_end_step(set_pool):
    """CR 113.6b: "if this card is in your graveyard …" is where the card states
    which zone the ability functions in, and CR 404.3's order is what "directly
    above it" reads."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])

    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_w1g5_krovikan_horror_answers_to_an_opponents_end_step(set_pool):
    """"At the beginning of **the** end step" — not "your". CR 513.1 gives every
    turn one end step and this ability names whichever comes next, so the scan
    is unseated where Death Spark's upkeep one is not."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])
    game.active_player_index = 1

    game.resolve_end_step(1)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]


def test_w1g5_krovikan_horror_stays_put_with_nothing_above_it(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would fire. On
    top of the pile there is nothing above it, so nothing fires."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([_w1g5_lea("Grizzly Bears"), horror])

    game.resolve_end_step(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[-1] is horror


def test_w1g5_nether_shadows_deeper_condition_still_reads(set_pool):
    """The three-cards-above spelling is the same clause with a different number,
    and it must keep answering the way it did — Nether Shadow's line is claimed
    by a card hook, and a condition production that changed what "above" means
    would have moved it silently."""
    from engine.graveyard_order import satisfies_above

    bear = _w1g5_lea("Grizzly Bears")
    forest = _w1g5_lea("Forest")
    pile = [set_pool("ALL")["Krovikan Horror"], bear, bear, bear]
    spec = {"card_type": "creature", "count": 3, "op": "ge", "directly": False}
    assert satisfies_above(pile, 0, spec)
    assert not satisfies_above([pile[0], bear, forest], 0, spec)


# --- W2G3: upkeep and counters ---
#
# The pay-or-consequence upkeep family and the counter records behind it.
# Rules-level assertions live in ``tests/rules/test_upkeep_counter_tolls.py``;
# what is here is per card, and each one drives the step that fires it rather
# than reading a compiled program - a registered trigger that never announces
# is what every static instrument reports as success.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.damage_events import deal_damage, seats_dealt_damage_by
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.regeneration import regeneration_replaces_destruction

_W2G3_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g3_perm(card, *, sick: bool = False) -> Permanent:
    perm = Permanent(card=card)
    if not sick:
        perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g3_duel(p1_perms=(), p2_perms=(), *, interactive=None):
    p1 = PlayerState(name="P1", battlefield=list(p1_perms))
    p2 = PlayerState(name="P2", battlefield=list(p2_perms))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive is not None:
        game.interactive_seats = set(interactive)
    return game, p1, p2


def _w2g3_settle(game):
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()


def test_w2g3_varchild_pays_its_upkeep_with_the_opponents_tokens(set_pool):
    """Cumulative upkeep - Have an opponent create a 1/1 red Survivor creature
    token. CR 702.24a's [cost] taken as far as it goes: the payer spends nothing
    at all, and declining still sacrifices the permanent.

    The escalation is the whole card, so the count is asserted across three
    upkeeps rather than once - a cost that failed to scale would look identical
    on the first.
    """
    riders = _w2g3_perm(set_pool("ALL")["Varchild's War-Riders"])
    game, _p1, p2 = _w2g3_duel([riders])
    totals = []
    for _ in range(3):
        game.resolve_upkeep(0)
        _w2g3_settle(game)
        totals.append(len(p2.battlefield))
    assert totals == [1, 3, 6], "one Survivor per age counter, every upkeep"
    assert all(perm.card.name == "Survivor Token" for perm in p2.battlefield)
    assert counters_on(riders, "age") == 3


def test_w2g3_varchild_declined_sacrifices_itself(set_pool):
    riders = _w2g3_perm(set_pool("ALL")["Varchild's War-Riders"])
    game, p1, p2 = _w2g3_duel([riders], interactive={0})

    offered = game.get_upkeep_pay_triggers(0)
    assert [entry["card_name"] for entry in offered] == ["Varchild's War-Riders"]
    assert "Survivor" in offered[0]["cost_label"]

    game.resolve_upkeep(0, human_choices={"Varchild's War-Riders": False})
    _w2g3_settle(game)
    assert p1.battlefield == [] and p2.battlefield == []


def test_w2g3_phantasmal_sphere_grows_and_its_cost_grows_with_it(set_pool):
    """CR 702.24a printed longhand with a +1/+1 counter where the keyword says
    "age": the counter has rules meaning (CR 122.1a), so the creature grows as
    the toll does."""
    sphere = _w2g3_perm(set_pool("ALL")["Phantasmal Sphere"])
    lands = [_w2g3_perm(_W2G3_LEA["Island"]) for _ in range(6)]
    game, _p1, _p2 = _w2g3_duel([sphere] + lands, interactive={0})

    game.resolve_upkeep(0, human_choices={"Phantasmal Sphere": True})
    _w2g3_settle(game)
    assert counters_on(sphere, "+1/+1") == 1
    assert (sphere.effective_power, sphere.effective_toughness) == (1, 2)
    assert sum(1 for land in lands if land.tapped) == 1

    game.resolve_upkeep(0, human_choices={"Phantasmal Sphere": True})
    _w2g3_settle(game)
    assert counters_on(sphere, "+1/+1") == 2
    assert sum(1 for land in lands if land.tapped) == 3, "one, then two"


def test_w2g3_phantasmal_sphere_hands_the_orb_to_an_opponent(set_pool):
    """When this creature leaves the battlefield, target opponent creates an
    X/X blue Orb creature token with flying, where X is the number of +1/+1
    counters on this creature. CR 115.4: the seat is chosen, and it is not the
    caster's."""
    sphere = _w2g3_perm(set_pool("ALL")["Phantasmal Sphere"])
    game, p1, p2 = _w2g3_duel([sphere], interactive={0})
    for _ in range(3):
        game.resolve_upkeep(0, human_choices={"Phantasmal Sphere": False})
        _w2g3_settle(game)
        if sphere not in p1.battlefield:
            break

    assert sphere not in p1.battlefield
    orbs = [perm for perm in p2.battlefield if perm.card.name == "Orb Token"]
    assert len(orbs) == 1, "the token goes to the opponent, not to the caster"
    assert (orbs[0].effective_power, orbs[0].effective_toughness) == (1, 1)
    assert orbs[0].has_keyword("flying")


def test_w2g3_rogue_skycaptain_defects_when_the_wage_is_declined(set_pool):
    """If you do not pay, remove all wage counters from this creature and an
    opponent gains control of it. Both halves, in the order printed: a new
    controller inheriting the escalation is the reason the card says the
    first."""
    captain = _w2g3_perm(set_pool("ALL")["Rogue Skycaptain"])
    game, p1, p2 = _w2g3_duel([captain], interactive={0})

    game.resolve_upkeep(0, human_choices={"Rogue Skycaptain": False})
    _w2g3_settle(game)

    assert counters_on(captain, "wage") == 0
    assert game.controller_index_of(captain) == 1
    assert captain in p2.battlefield and captain not in p1.battlefield


def test_w2g3_rogue_skycaptain_keeps_its_counters_when_paid(set_pool):
    captain = _w2g3_perm(set_pool("ALL")["Rogue Skycaptain"])
    lands = [_w2g3_perm(_W2G3_LEA["Mountain"]) for _ in range(6)]
    game, _p1, _p2 = _w2g3_duel([captain] + lands, interactive={0})

    game.resolve_upkeep(0, human_choices={"Rogue Skycaptain": True})
    _w2g3_settle(game)
    assert counters_on(captain, "wage") == 1
    assert sum(1 for land in lands if land.tapped) == 2

    game.resolve_upkeep(0, human_choices={"Rogue Skycaptain": True})
    _w2g3_settle(game)
    assert counters_on(captain, "wage") == 2
    assert game.controller_index_of(captain) == 0
    assert sum(1 for land in lands if land.tapped) == 6, "two, then four"


def test_w2g3_diseased_vermin_only_reaches_an_opponent_it_has_hurt(set_pool):
    """Deals X damage to target opponent previously dealt damage by it. The
    narrowing is a record on the source, so an opponent it has never hit is not
    a legal target and the upkeep does nothing at all."""
    vermin = _w2g3_perm(set_pool("ALL")["Diseased Vermin"])
    game, _p1, p2 = _w2g3_duel([vermin])
    p2.life = 20

    game.resolve_upkeep(0)
    _w2g3_settle(game)
    assert seats_dealt_damage_by(vermin) == []
    assert p2.life == 20, "nobody has been hurt by it, so nobody is a target"

    deal_damage(
        game, {"recipient": p2, "amount": 1, "source": vermin, "combat": True}
    )
    game._settle()
    assert seats_dealt_damage_by(vermin) == [1]

    game.resolve_upkeep(0)
    _w2g3_settle(game)
    assert p2.life == 19, "one infection counter, one damage"


def test_w2g3_diseased_vermin_scales_with_its_infection_counters(set_pool):
    """X is read off the counters at resolution, not off the printed line.

    The direct deal_damage call is only there to write the history the
    narrowing reads: CR 120.4's second half is the caller's, so no life is lost
    to it and every point below comes from the upkeep.
    """
    vermin = _w2g3_perm(set_pool("ALL")["Diseased Vermin"])
    game, _p1, p2 = _w2g3_duel([vermin])
    p2.life = 20
    deal_damage(
        game, {"recipient": p2, "amount": 1, "source": vermin, "combat": False}
    )
    game._settle()
    add_counters(vermin, "infection", 3)

    game.resolve_upkeep(0)
    _w2g3_settle(game)
    assert p2.life == 20 - 3


def test_w2g3_spiny_starfish_counts_each_regeneration(set_pool):
    """Create a 0/1 blue Starfish creature token for each time it regenerated
    this turn. A count, not a flag: the intervening-if reads the same record
    (CR 603.4)."""
    for regenerations, expected in ((0, 0), (1, 1), (3, 3)):
        fish = _w2g3_perm(set_pool("ALL")["Spiny Starfish"])
        game, p1, _p2 = _w2g3_duel([fish])
        for _ in range(regenerations):
            assert game.activate_permanent_ability(0, "Spiny Starfish").supported
            _w2g3_settle(game)
            assert regeneration_replaces_destruction(game, fish)
            fish.tapped = False
        game.resolve_end_step(0)
        _w2g3_settle(game)
        tokens = [p for p in p1.battlefield if p.card.name == "Starfish Token"]
        assert len(tokens) == expected, f"{regenerations} regenerations"


def test_w2g3_the_regeneration_record_is_swept_with_the_turn(set_pool):
    """"This turn" is the window, and the cleanup sweep is what says so - the
    end step that reads it runs first (CR 514.2)."""
    fish = _w2g3_perm(set_pool("ALL")["Spiny Starfish"])
    game, _p1, _p2 = _w2g3_duel([fish])
    assert game.activate_permanent_ability(0, "Spiny Starfish").supported
    _w2g3_settle(game)
    assert regeneration_replaces_destruction(game, fish)
    assert fish.metadata["regenerated_this_turn"] == 1

    game.resolve_cleanup_step(0)
    assert "regenerated_this_turn" not in fish.metadata


def test_w2g3_fyndhorn_druid_gains_life_only_when_it_was_blocked(set_pool):
    """"...if it was blocked this turn" is CR 509.1a from the attacker's end.
    A Druid that blocked has been in a block and is still not one the sentence
    is about - the two halves of the relation are different records."""
    druid_card = set_pool("ALL")["Fyndhorn Druid"]

    blocked = _w2g3_perm(druid_card)
    game, p1, _p2 = _w2g3_duel([blocked], [_w2g3_perm(_W2G3_LEA["Serra Angel"])])
    game.start_turn(0)
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    game.declare_attackers(0, [0], defending_player_index=1)
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {0: 0})[0]
    game.current_step = "combat_damage"
    p1.life = 20
    game.resolve_combat_damage(0)
    _w2g3_settle(game)
    assert p1.life == 24

    blocker = _w2g3_perm(druid_card)
    game, q1, _q2 = _w2g3_duel([blocker], [_w2g3_perm(_W2G3_LEA["Hill Giant"])])
    game.start_turn(1)
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    game.declare_attackers(1, [0], defending_player_index=0)
    game.current_step = "declare_blockers"
    assert game.declare_blockers(0, {0: 0})[0]
    game.current_step = "combat_damage"
    q1.life = 20
    game.resolve_combat_damage(1)
    _w2g3_settle(game)
    assert q1.graveyard and q1.graveyard[-1].name == "Fyndhorn Druid"
    assert q1.life == 20, "it blocked; it was not blocked"


def test_w2g3_juniper_order_advocate_buffs_only_while_untapped(set_pool):
    """A CR 613 layer-7c anthem hanging on the source's own state, re-derived on
    every recompute - so tapping it takes the bonus away with nothing to undo."""
    advocate = _w2g3_perm(set_pool("ALL")["Juniper Order Advocate"])
    elves = _w2g3_perm(_W2G3_LEA["Llanowar Elves"])
    wall = _w2g3_perm(_W2G3_LEA["Wall of Swords"])
    game, _p1, _p2 = _w2g3_duel([advocate, elves, wall])
    game.start_turn(0)

    assert (elves.effective_power, elves.effective_toughness) == (2, 2)
    assert (wall.effective_power, wall.effective_toughness) == (3, 5), "white"
    assert (advocate.effective_power, advocate.effective_toughness) == (1, 2)

    advocate.tapped = True
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert (elves.effective_power, elves.effective_toughness) == (1, 1)


def test_w2g3_ivory_gargoyle_comes_back_and_costs_a_draw(set_pool):
    """Three of W1G5's four named parts at once: the pronoun naming the
    ability's own card, "under its owner's control" (CR 400.3), and the conjunct
    the delay does not govern - the skip happens now, the return at the end
    step."""
    gargoyle = _w2g3_perm(set_pool("ALL")["Ivory Gargoyle"])
    game, p1, _p2 = _w2g3_duel([gargoyle])
    p1.library = [_W2G3_LEA["Plains"] for _ in range(5)]
    game.turn = 3

    game.sacrifice_permanent(gargoyle)
    _w2g3_settle(game)
    assert game.skip_step_counts == {(0, "draw"): 1}
    assert p1.graveyard and p1.graveyard[-1].name == "Ivory Gargoyle"

    game.resolve_end_step(0)
    _w2g3_settle(game)
    assert [perm.card.name for perm in p1.battlefield] == ["Ivory Gargoyle"]
    assert p1.graveyard == []


def test_w2g3_a_stolen_gargoyle_returns_to_its_owner(set_pool):
    """"Under its owner's control" is not the ability's controller once the
    creature has changed hands - the seat is CR 108.3's, read off the seat the
    permanent entered under."""
    gargoyle = _w2g3_perm(set_pool("ALL")["Ivory Gargoyle"])
    game, p1, p2 = _w2g3_duel([gargoyle])
    thief = _w2g3_perm(_W2G3_LEA["Control Magic"])
    game.take_control(gargoyle, 1, source=thief)
    assert game.controller_index_of(gargoyle) == 1

    game.sacrifice_permanent(gargoyle)
    _w2g3_settle(game)
    game.resolve_end_step(0)
    _w2g3_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Ivory Gargoyle"]
    assert p2.battlefield == []


def test_w2g3_every_group_card_compiles_with_every_line_read(set_pool):
    """The census counts a card supported when any line is claimed, so each of
    these is checked line by line - the failure this catches is a card that
    ships with one ability inert."""
    for name in (
        "Phantasmal Sphere", "Rogue Skycaptain", "Diseased Vermin",
        "Varchild's War-Riders", "Spiny Starfish", "Ivory Gargoyle",
        "Fyndhorn Druid", "Juniper Order Advocate",
    ):
        card = set_pool("ALL")[name]
        program = compile_card_oracle(card)
        assert program.supported, name
        lines = expand_ability_lines(
            card.oracle_text, card_name=card.name
        ).splitlines()
        claimed = len(program.instructions) + len(program.static_lines)
        assert claimed >= len(lines), (name, lines)
        for trigger in program.triggered_abilities:
            assert trigger.supported, (name, trigger.source_line)
