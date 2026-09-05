"""Visions enchantments and Auras.

Split by the printed type of the card each test names
(``tests/sets/README.md``).
"""

from __future__ import annotations
from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.models import CardDefinition, Permanent
from tests.helpers import _nosick
import pytest
from engine import Game as _W2G1eGame, PlayerState as _W2G1ePlayerState
from engine.models import Permanent as _W2G1ePermanent
from engine.card_loader import load_cards as _w2g1e_load, manifest_set_path as _w2g1e_path
from engine.grammar import parse_line as _w2g1e_parse
from engine.grammar.errors import GrammarError as _W2G1eGrammarError
from engine.models import CardDefinition as _W2G1eCardDefinition
from engine.oracle import compile_card_oracle as _w2g1e_compile
from engine import Game as _W2G5EGame, PlayerState as _W2G5EPlayer
from engine.models import Permanent as _W2G5EPermanent
from engine.oracle import compile_card_oracle as _w2g5e_program

def _rig():
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, alice, bob
def _enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent
def test_flooded_shoreline_charges_both_islands_before_it_bounces(set_pool, catalog_by_name):
    """"{U}{U}, Return two Islands you control to their owner's hand: Return
    target creature to its owner's hand."

    The cost is the half nothing charged: the effect ("return target creature")
    has been readable since Unsummon, so an activation with the cost dropped
    would be a free Boomerang every turn. Two Islands leave, and the third is
    what proves the count rather than the whole board is what was taken.
    """
    game, alice, bob = _rig()
    for _ in range(3):
        _enters(game, 0, catalog_by_name["Island"])
    _enters(game, 0, set_pool("VIS")["Flooded Shoreline"])
    _enters(game, 1, catalog_by_name["Grizzly Bears"])

    result = game.activate_permanent_ability(
        0, "Flooded Shoreline", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is True
    assert [p.card.name for p in alice.battlefield] == ["Island", "Flooded Shoreline"]
    assert [card.name for card in alice.hand] == ["Island", "Island"]
    assert bob.battlefield == []
    assert [card.name for card in bob.hand] == ["Grizzly Bears"]
def test_flooded_shoreline_is_refused_with_one_island(set_pool, catalog_by_name):
    """CR 601.2h: partial payments are not allowed.

    One Island is not half a cost — the activation is refused with nothing
    spent, rather than eating the one Island and bouncing anyway.
    """
    game, alice, bob = _rig()
    _enters(game, 0, catalog_by_name["Island"])
    _enters(game, 0, set_pool("VIS")["Flooded Shoreline"])
    bear = _enters(game, 1, catalog_by_name["Grizzly Bears"])

    result = game.activate_permanent_ability(
        0, "Flooded Shoreline", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is False
    assert [p.card.name for p in alice.battlefield] == ["Island", "Flooded Shoreline"]
    assert alice.hand == []
    assert game.is_on_battlefield(bear)
def test_sun_clasp_buffs_and_then_bounces_the_creature_it_enchants(set_pool, catalog_by_name):
    """"Enchanted creature gets +1/+3." / "{W}: Return enchanted creature to
    its owner's hand."

    The Aura's own attachment, named rather than chosen (CR 303.4b), so the
    bounce reaches an opponent's creature without targeting it. And the Aura
    goes with it: CR 704.5m bins an Aura attached to nothing.
    """
    game, alice, bob = _rig()
    bear = _enters(game, 1, catalog_by_name["Grizzly Bears"])
    clasp = _enters(game, 0, set_pool("VIS")["Sun Clasp"])
    attach_aura(clasp, bear)

    assert (bear.effective_power, bear.effective_toughness) == (3, 5)

    result = game.activate_permanent_ability(0, "Sun Clasp")

    assert result.supported is True
    assert bob.battlefield == []
    assert [card.name for card in bob.hand] == ["Grizzly Bears"]
    assert alice.battlefield == [], "the Aura followed it (704.5m)"
    assert [card.name for card in alice.graveyard] == ["Sun Clasp"]
def test_sun_clasp_claims_every_printed_line(set_pool):
    """Both effect lines compile, not just the +1/+3.

    An Aura is supported when the gate can read its effects, and the P/T grant
    alone used to be enough to make the card look done while the activated
    ability had nothing behind it.
    """
    program = compile_card_oracle(set_pool("VIS")["Sun Clasp"])

    assert program.supported is True
    assert len(program.activated_abilities) == 1
    ability = program.activated_abilities[0]
    assert ability.supported is True
    assert ability.instruction.kind == "return_attached_permanent_to_hand"
def _w1g2_game(*battlefields):
    """One seat per positional argument, each a list of permanents."""
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(bf))
        for i, bf in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    return game
def _w1g2_bear(name: str = "Bear") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )
def _w1g2_vanishing(set_pool):
    aura = Permanent(card=set_pool("VIS")["Vanishing"])
    host = Permanent(card=_w1g2_bear())
    game = _w1g2_game([host, aura], [])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    return game, aura, host
def test_vanishing_phases_out_the_creature_it_enchants(set_pool):
    """"{U}{U}: Enchanted creature phases out." (CR 702.26.)

    The subject is neither a target nor the ability's source — it is the Aura's
    own attachment — which is the branch the phase-out lowering did not have, so
    the card reported "unimplemented aura effect" for its whole activated
    ability.
    """
    game, aura, host = _w1g2_vanishing(set_pool)

    result = game.activate_permanent_ability(0, "Vanishing", permanent_index=1)
    game._settle()

    assert result.supported, result.details
    assert not game.is_on_battlefield(host)
    assert host in game.players[0].phased_out
def test_vanishing_phases_out_with_its_host_and_stays_attached(set_pool):
    """CR 702.26d: the Auras attached to a permanent phase out with it, and
    CR 702.26b says none of it is a zone change.

    The engine's one removal transition detaches an Aura, because for every
    *other* way a permanent leaves that is exactly right (CR 611.3). A phase-out
    took the same path, so Vanishing arrived back on the battlefield enchanting
    nothing — and CR 704.5m would then bin it, every single activation.
    """
    game, aura, host = _w1g2_vanishing(set_pool)

    game.activate_permanent_ability(0, "Vanishing", permanent_index=1)
    game._settle()

    assert aura in game.players[0].phased_out, "CR 702.26d: it goes with the host"
    assert aura.metadata.get("attached_to") is host, "and it stays attached"

    game.resolve_phasing_for(0)

    assert game.is_on_battlefield(host) and game.is_on_battlefield(aura)
    assert aura.metadata.get("attached_to") is host
    assert host in (aura.metadata.get("attached_to"),)
def test_a_phase_out_fires_no_leaves_the_battlefield_trigger(set_pool):
    """CR 702.26b: "abilities that trigger when a permanent leaves the
    battlefield don't trigger when a permanent phases out."

    Asserted through a card that *has* such an ability rather than through the
    flag that suppresses it: the flag is the mechanism and this is the rule.
    """
    watcher = CardDefinition(
        name="Watcher", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="When this creature leaves the battlefield, you gain 3 life.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Watcher", "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    )
    host = Permanent(card=watcher)
    aura = Permanent(card=set_pool("VIS")["Vanishing"])
    game = _w1g2_game([host, aura], [])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    before = game.players[0].life

    game.activate_permanent_ability(0, "Vanishing", permanent_index=1)
    game._settle()

    assert host in game.players[0].phased_out
    assert game.players[0].life == before, "phasing out is not leaving"
def test_blanket_of_night_adds_swamp_without_taking_the_land_s_own_type(set_pool):
    """"Each land is a Swamp **in addition to its other land types**."

    The rider is what switches CR 305.7 off. Every other board-wide land-type
    static in the pool *replaces* the land's subtypes, so reading this one as
    those would have turned every Island into a Swamp and stopped it making blue
    mana — a strictly harsher card, silently.
    """
    blanket = Permanent(card=set_pool("VIS")["Blanket of Night"])
    island = Permanent(card=set_pool("LEA")["Island"])
    game = _w1g2_game([blanket, island], [])
    game._recompute_continuous_effects()

    assert island.has_type("swamp")
    assert island.has_type("island"), "in addition to its other land types"
def test_blanket_of_night_reaches_every_seat_s_lands(set_pool):
    """"**Each** land" — the sentence narrows by no controller, so an
    opponent's lands are Swamps too."""
    blanket = Permanent(card=set_pool("VIS")["Blanket of Night"])
    forest = Permanent(card=set_pool("LEA")["Forest"])
    game = _w1g2_game([blanket], [forest])
    game._recompute_continuous_effects()

    assert forest.has_type("swamp") and forest.has_type("forest")
def test_blanket_of_night_stops_saying_so_once_it_leaves(set_pool):
    """CR 611.3b: a static's contribution is rebuilt from the board every pass,
    so removal is the absence of a contribution rather than an undo."""
    blanket = Permanent(card=set_pool("VIS")["Blanket of Night"])
    island = Permanent(card=set_pool("LEA")["Island"])
    game = _w1g2_game([blanket, island], [])
    game._recompute_continuous_effects()
    assert island.has_type("swamp")

    game.remove_from_battlefield(blanket)
    game._recompute_continuous_effects()

    assert not island.has_type("swamp")
    assert island.has_type("island")
def _w1g2_realm_board(set_pool, *, interactive=frozenset()):
    """Teferi's Realm out for seat 0, with a creature, a land and an Aura about."""
    from engine.card_loader import load_cards, manifest_set_path

    lea = set_pool("LEA")
    realm = Permanent(card=set_pool("VIS")["Teferi's Realm"])
    mine = Permanent(card=_w1g2_bear("Mine"))
    theirs = Permanent(card=_w1g2_bear("Theirs"))
    forest = Permanent(card=lea["Forest"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[realm, mine], library=[lea["Forest"]] * 5),
        PlayerState(
            name="P2", battlefield=[theirs, forest], library=[lea["Forest"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._recompute_continuous_effects()
    return game, realm, mine, theirs, forest
def test_teferis_realm_phases_out_every_nontoken_permanent_of_the_chosen_type(set_pool):
    """"At the beginning of each player's upkeep, that player chooses artifact,
    creature, land, or non-Aura enchantment. All nontoken permanents of that
    type phase out."

    Two sentences and one ability: the first records a card type on the
    enchantment and the second sweeps the whole board by it. The sweep is
    board-wide — the sentence narrows by no controller — so the chooser's own
    permanents go too.
    """
    game, _realm, mine, theirs, forest = _w1g2_realm_board(
        set_pool, interactive={1}
    )
    game.start_turn(1)

    assert game.confirm_card_type_choice(1, "creature") is True
    game._settle()

    assert mine in game.players[0].phased_out, "the chooser's opponent's creature"
    assert theirs in game.players[1].phased_out, "and the chooser's own"
    assert game.is_on_battlefield(forest), "only the chosen type"
def test_teferis_realm_waits_for_the_answer_before_it_sweeps(set_pool):
    """The reason the choice is its own suspending prompt.

    The sentence that reads the answer is a *one-shot* sweep in the same
    resolution, so an answer arriving after it would change nothing — a prompt
    that lies. ``enter_choice``, whose readers are continuous effects, does not
    suspend and must not start.
    """
    game, _realm, mine, theirs, _forest = _w1g2_realm_board(
        set_pool, interactive={1}
    )
    game.start_turn(1)

    assert game.waiting_prompt, "the resolution is owed a decision (CR 608.2)"
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs), (
        "nothing has been swept yet"
    )

    game.confirm_card_type_choice(1, "creature")
    game._settle()

    assert mine in game.players[0].phased_out
def test_teferis_realm_refuses_a_type_the_card_never_offered(set_pool):
    """The answer is bounded by the *sentence*, not by a catalog. "Instant"
    names a type no permanent has, and "enchantment" would escape the printed
    Aura exclusion — both are refused rather than repaired."""
    game, _realm, _mine, _theirs, _forest = _w1g2_realm_board(
        set_pool, interactive={1}
    )
    game.start_turn(1)

    assert game.confirm_card_type_choice(1, "instant") is False
    assert game.confirm_card_type_choice(1, "enchantment") is False
    assert game.waiting_prompt, "a rejected answer leaves the prompt owed"
    assert game.confirm_card_type_choice(1, "non-aura enchantment") is True
def test_teferis_realm_leaves_an_aura_alone_under_the_non_aura_option(set_pool):
    """"…or **non-Aura** enchantment." The printed exclusion travels with the
    option, so an Aura is not one of the permanents the sweep names — and the
    Realm itself, a plain enchantment, is."""
    from engine.auras import attach_aura

    lea = set_pool("LEA")
    realm = Permanent(card=set_pool("VIS")["Teferi's Realm"])
    host = Permanent(card=_w1g2_bear("Host"))
    aura = Permanent(card=lea["Holy Strength"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[realm], library=[lea["Forest"]] * 5),
        PlayerState(
            name="P2", battlefield=[host, aura], library=[lea["Forest"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    game.start_turn(1)

    assert game.confirm_card_type_choice(1, "non-aura enchantment") is True
    game._settle()

    assert realm in game.players[0].phased_out, "a nontoken enchantment, and not an Aura"
    assert game.is_on_battlefield(aura), "an Aura is excluded by the printed word"
def test_teferis_realm_gives_the_choice_to_the_upkeep_s_player(set_pool):
    """"…**each player's** upkeep, **that player** chooses." The seat the fire
    site froze (CR 603.10) — a different player every turn, and never the
    enchantment's controller except on their own turn."""
    game, _realm, _mine, _theirs, _forest = _w1g2_realm_board(
        set_pool, interactive={0, 1}
    )
    game.start_turn(1)

    assert game.confirm_card_type_choice(0, "creature") is False, "not their upkeep"
    assert game.confirm_card_type_choice(1, "creature") is True
def _w1g3e_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game
def _w1g3e_creature(name="Bear", power=2, toughness=4, colors=()):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )
def test_mortal_wound_destroys_the_creature_the_moment_it_is_dealt_damage(set_pool):
    """"When enchanted creature is dealt damage, destroy it."

    The condition was readable by ``engine/oracle.py``'s table under either
    printed word and by the grammar under only one, so the trigger *parsed* and
    its effect clause did not - the card compiled with a trigger that had no
    instruction behind it. What that costs is exactly this: one point of damage
    on a 2/4 and the creature should die.

    Driven through the stack, because a CR 603.3 trigger resolves off it: a
    trigger that is enqueued and never resolved looks identical to one that
    fires, from anywhere but here.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3e_creature("Doomed Bear")))
    wound = Permanent(card=set_pool("VIS")["Mortal Wound"])
    p2.battlefield.append(victim)
    p1.battlefield.append(wound)
    attach_aura(wound, victim)

    game._mark_damage_on_permanent(victim, 1)
    game._fire_dealt_damage_triggers(victim, 1)
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()

    assert not any(p is victim for p in p2.battlefield)
def test_mortal_wound_leaves_an_undamaged_creature_alone(set_pool):
    """The control. A trigger fired by the attachment rather than by the event
    would kill the creature the moment the Aura landed, which is the failure a
    "does the card work?" test that only ever damages things cannot see."""
    game = _w1g3e_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3e_creature("Healthy Bear")))
    wound = Permanent(card=set_pool("VIS")["Mortal Wound"])
    p2.battlefield.append(victim)
    p1.battlefield.append(wound)
    attach_aura(wound, victim)

    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()

    assert any(p is victim for p in p2.battlefield)
def test_elephant_grass_forbids_a_black_attacker_and_prices_the_rest(set_pool):
    """"Black creatures can't attack you." / "Nonblack creatures can't attack
    you unless their controller pays {2} for each creature they control that's
    attacking you."

    Both sentences were unclaimed on a card that reported supported, which is
    the population ``parse_coverage`` exists to find: the enchantment entered
    play and did nothing at all. Three assertions, because the two sentences
    divide the board three ways - the black attacker is forbidden outright, a
    nonblack one is priced, and neither says anything about attacking anybody
    else.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    grass = Permanent(card=set_pool("VIS")["Elephant Grass"])
    p1.battlefield.append(grass)
    black = _nosick(Permanent(card=_w1g3e_creature("Black Bear", colors=("B",))))
    white = _nosick(Permanent(card=_w1g3e_creature("White Bear", colors=("W",))))
    p2.battlefield.extend([black, white])

    assert not game.can_attack(black, 0), "black creatures can't attack you"
    # The nonblack one is not forbidden - it is priced, and with no mana it
    # cannot pay, so the declaration is refused rather than the creature.
    assert game._attack_mana_costs_of(white, 0) == [{"generic": 2}]
    assert game._attack_mana_costs_of(black, 0) == [], (
        "the toll's noun phrase excludes the colour the other sentence forbids"
    )
def test_elephant_grass_says_nothing_about_attacking_its_opponent(set_pool):
    """"…can't attack **you**" is CR 109.5's "you": the seat controlling the
    enchantment. Read as an unscoped prohibition it would ground the creature
    against every seat at the table, which in a duel is invisible and in a
    free-for-all is three cards' worth of effect."""
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    grass = Permanent(card=set_pool("VIS")["Elephant Grass"])
    p1.battlefield.append(grass)
    black = _nosick(Permanent(card=_w1g3e_creature("Black Bear", colors=("B",))))
    p2.battlefield.append(black)

    assert not game.can_attack(black, 0)
    assert game.can_attack(black, 2), "the third seat is protected by nothing"
def test_heat_wave_forbids_a_blue_blocker_and_charges_the_rest_life(set_pool):
    """"Blue creatures can't block creatures you control." / "Nonblue creatures
    can't block creatures you control unless their controller pays 1 life for
    each blocking creature they control."

    The blocking mirror of Elephant Grass, and both of its sentences were
    unclaimed too. The life toll is the first cost in the combat tables paid in
    something other than mana, so it is read back rather than assumed.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    attacker = _nosick(Permanent(card=_w1g3e_creature("My Attacker")))
    p1.battlefield.extend([wave, attacker])
    blue = _nosick(Permanent(card=_w1g3e_creature("Blue Blocker", colors=("U",))))
    red = _nosick(Permanent(card=_w1g3e_creature("Red Blocker", colors=("R",))))
    p2.battlefield.extend([blue, red])
    attacker.attacking = True

    assert not game._can_block_attacker(blue, attacker)
    assert game._block_life_cost_of(red, attacker) == 1
    assert game._block_life_cost_of(blue, attacker) == 0, (
        "the toll's own noun phrase is **nonblue**, so it says nothing about a "
        "blue creature - which the sentence above has already forbidden "
        "outright. Two sentences, two disjoint sets, and a toll that reached "
        "both would charge for a block the card does not allow at any price"
    )
def test_heat_wave_refuses_a_blocker_its_controller_cannot_pay_for(set_pool):
    """CR 118.4: a player may pay N life only with a life total of at least N.
    Asked at the gate, so an unpayable toll makes the block illegal rather than
    being discovered after CR 509 has locked the declaration in."""
    game = _w1g3e_duel()
    p1, p2 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    attacker = _nosick(Permanent(card=_w1g3e_creature("My Attacker")))
    p1.battlefield.extend([wave, attacker])
    red = _nosick(Permanent(card=_w1g3e_creature("Red Blocker", colors=("R",))))
    p2.battlefield.append(red)
    attacker.attacking = True

    assert game._can_block_attacker(red, attacker)
    p2.life = 0
    assert not game._can_block_attacker(red, attacker)
def test_heat_wave_says_nothing_about_blocking_somebody_else_s_attacker(set_pool):
    """"…can't block creatures **you** control" — CR 109.5 again, on the other
    half of combat. Read with the blocker's seat as the observer this would
    protect the wrong player's creatures, which in a duel is the opposite of
    the printed card."""
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    p1.battlefield.append(wave)
    third_partys_attacker = _nosick(Permanent(card=_w1g3e_creature("Their Attacker")))
    p3.battlefield.append(third_partys_attacker)
    blue = _nosick(Permanent(card=_w1g3e_creature("Blue Blocker", colors=("U",))))
    p2.battlefield.append(blue)
    third_partys_attacker.attacking = True

    assert game._can_block_attacker(blue, third_partys_attacker)
    assert game._block_life_cost_of(blue, third_partys_attacker) == 0
def _w1g4_game() -> Game:
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    return game
def _w1g4_drain(game: Game) -> None:
    for _ in range(20):
        if not game.stack:
            return
        game.resolve_top_of_stack()
    raise AssertionError("the stack never drained")
def _w1g4_creature(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name}, power="2", toughness="2",
    )
def test_suleimans_legacy_destroys_a_djinn_that_enters_later(set_pool):
    """"Whenever a Djinn or Efreet enters, destroy it. It can't be regenerated."

    The second line, and until this round it compiled to no instruction at all -
    the enchantment reported supported on its *first* line and the trigger fired
    into nothing. "It" is the permanent the trigger's own event was about, which
    is what the entry transition now freezes; read as the ability's own source
    (which is what a bare pronoun means everywhere else) the enchantment would
    have destroyed itself.
    """
    game = _w1g4_game()
    legacy = Permanent(card=set_pool("VIS")["Suleiman's Legacy"])
    game.players[0].battlefield.append(legacy)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    djinn = Permanent(card=_w1g4_creature("Bottled Djinn", "Creature - Djinn"))
    game._put_permanent_onto_battlefield(1, djinn, None)
    _w1g4_drain(game)

    assert [p.card.name for p in game.players[1].battlefield] == []
    assert [c.name for c in game.players[1].graveyard] == ["Bottled Djinn"]
    # The enchantment is still there: the pronoun named the enterer, not itself.
    assert game.is_on_battlefield(legacy)
def test_suleimans_legacy_leaves_a_creature_its_trigger_does_not_name(set_pool):
    """The narrowing is the trigger's own subject filter, and a trigger that
    fired on every entry would be a strictly different card."""
    game = _w1g4_game()
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Suleiman's Legacy"])
    )
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    bear = Permanent(card=_w1g4_creature("Grizzly", "Creature - Bear"))
    game._put_permanent_onto_battlefield(1, bear, None)
    _w1g4_drain(game)

    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly"]
def test_suleimans_legacy_carries_the_no_regeneration_rider(set_pool):
    """"It can't be regenerated" is the instruction's ``bypass_regeneration``,
    not a second reading of CR 701.19c - a rider parsed and dropped is a
    destroy a regeneration shield would survive."""
    program = compile_card_oracle(set_pool("VIS")["Suleiman's Legacy"])
    entering = next(
        trigger for trigger in program.triggered_abilities
        if trigger.condition.kind == "matching_permanent_enters"
    )

    assert entering.instruction is not None, "the trigger used to be hollow"
    assert entering.instruction.kind == "destroy_event_subject"
    assert entering.instruction.payload["bypass_regeneration"] is True
def test_a_bare_it_refuses_where_no_event_names_an_object():
    """The refusal side of the same production: "destroy it" is only a
    back-reference where the firing event froze one, and everywhere else the
    pronoun is the ability's own source."""
    from engine.grammar import lower_ability, parse_line
    from engine.grammar.errors import LoweringError

    # A trigger whose fire site freezes no object for the pronoun to name.
    node = parse_line("Whenever a land is tapped for mana, destroy it.")
    with pytest.raises(LoweringError):
        lower_ability(node)
def _w1g4_artifact(name: str, cmc: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{%d}" % cmc, cmc=float(cmc), type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
    )
def test_corrosion_rusts_then_destroys_what_the_rust_has_caught(set_pool):
    """"At the beginning of your upkeep, put a rust counter on each artifact
    target opponent controls. Then destroy each artifact with mana value less
    than or equal to the number of rust counters on it."

    Both halves used to be one instruction-less trigger. The destroy's bound is
    a characteristic of the *same object* the sweep is testing, which is what
    makes it a filter key rather than an amount - and CR's own reading is that a
    mana-value-0 artifact qualifies with no counters at all, which is why the
    sweep is not narrowed to the targeted opponent's board.
    """
    from engine.named_counters import counters_on

    game = _w1g4_game()
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Corrosion"])
    )
    # Corrosion's other upkeep trigger is its cumulative upkeep, and a seat that
    # cannot pay it sacrifices the enchantment in the same step - which then
    # fires the leaves-the-battlefield trigger and clears the counters this test
    # is about. One untapped land is the whole fixture.
    game.players[0].battlefield.append(Permanent(card=CardDefinition(
        name="Swamp", mana_cost="", cmc=0.0, type_line="Basic Land - Swamp",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("B",), raw={"name": "Swamp"},
    )))
    one = Permanent(card=_w1g4_artifact("One", 1))
    two = Permanent(card=_w1g4_artifact("Two", 2))
    game.players[1].battlefield.extend([one, two])
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game.resolve_upkeep(0, defer_priority=True)
    _w1g4_drain(game)

    # One rust counter each: the {1} artifact is caught, the {2} one is not yet.
    assert [p.card.name for p in game.players[1].battlefield] == ["Two"]
    assert counters_on(two, "rust") == 1
    assert [c.name for c in game.players[1].graveyard] == ["One"]
def test_corrosion_takes_its_rust_with_it_when_it_leaves(set_pool):
    """"When this enchantment leaves the battlefield, remove all rust counters
    from all permanents." - the second instruction-less part, and a sweep over a
    described set rather than the ability's own source (which by then is gone)."""
    from engine.named_counters import add_counters, counters_on

    game = _w1g4_game()
    corrosion = Permanent(card=set_pool("VIS")["Corrosion"])
    game.players[0].battlefield.append(corrosion)
    rusted = Permanent(card=_w1g4_artifact("Big", 6))
    game.players[1].battlefield.append(rusted)
    add_counters(rusted, "rust", 3)
    game.begin_turn_bookkeeping(0)

    game.remove_from_battlefield(corrosion)
    _w1g4_drain(game)

    assert counters_on(rusted, "rust") == 0
    assert game.is_on_battlefield(rusted), "the counters go, the artifact stays"
def test_rowen_reveals_the_first_draw_and_pays_for_a_land(set_pool):
    """"Reveal the first card you draw each turn. Whenever you reveal a basic
    land card this way, draw a card."

    One printed paragraph holding a static ability and a triggered one, so the
    compiler had to be taught to split it - gated on the first sentence being a
    static the engine already implements, because the pool holds two *spells*
    whose second sentence opens the same way and is a delayed ability their
    first sentence creates.

    Both directions are asserted: the reveal happens either way (it is not
    conditional), and only a basic land pays the extra card.
    """
    pool = set_pool("VIS")
    plains = CardDefinition(
        name="Plains", mana_cost="", cmc=0.0, type_line="Basic Land - Plains",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("W",), raw={"name": "Plains"},
    )
    ogre = _w1g4_creature("Ogre", "Creature - Ogre")

    def _draw_step(top):
        game = Game(players=[
            PlayerState(name="P0", library=[top] + [ogre] * 5),
            PlayerState(name="P1", library=[ogre] * 5),
        ])
        game.enforce_mana_costs = False
        game.players[0].battlefield.append(Permanent(card=pool["Rowen"]))
        game.turn = 2
        game.begin_turn_bookkeeping(0)
        game.active_player_index = 0
        game.resolve_draw_step(0, defer_priority=True)
        _w1g4_drain(game)
        return game

    game = _draw_step(plains)
    assert [event["cards"] for event in game.reveal_events] == [["Plains"]]
    assert len(game.players[0].hand) == 2, "the basic land bought a second card"

    game = _draw_step(ogre)
    assert [event["cards"] for event in game.reveal_events] == [["Ogre"]]
    assert len(game.players[0].hand) == 1
def test_rowen_does_not_fire_on_an_opponents_first_draw(set_pool):
    """"**You** reveal" is the ability's controller (CR 109.5), and the static
    half is their reveal too - the seat is what the announcement carries."""
    plains = CardDefinition(
        name="Plains", mana_cost="", cmc=0.0, type_line="Basic Land - Plains",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("W",), raw={"name": "Plains"},
    )
    game = Game(players=[
        PlayerState(name="P0", library=[plains] * 5),
        PlayerState(name="P1", library=[plains] * 5),
    ])
    game.enforce_mana_costs = False
    game.players[0].battlefield.append(Permanent(card=set_pool("VIS")["Rowen"]))
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.active_player_index = 1

    game.resolve_draw_step(1, defer_priority=True)
    _w1g4_drain(game)

    assert game.reveal_events == []
    assert len(game.players[1].hand) == 1
_W2G1E_LEA = {c.name: c for c in _w2g1e_load(_w2g1e_path("LEA"))}
def _w2g1e_scene(set_pool, land_name):
    p1, p2 = _W2G1ePlayerState(name="A"), _W2G1ePlayerState(name="B")
    game = _W2G1eGame(players=[p1, p2])
    game.enforce_mana_costs = True
    p1.battlefield.append(
        _W2G1ePermanent(card=set_pool("VIS")["Squandered Resources"])
    )
    p1.battlefield.append(_W2G1ePermanent(card=_W2G1E_LEA[land_name]))
    return game, p1
def test_squandered_resources_adds_what_the_sacrificed_land_could_produce(set_pool):
    """The mana type comes off the land the ability's own **cost** ate.

    That permanent is gone by the time the ability resolves, which is exactly
    what CR 608.2h's last-known information is for — the record is read rather
    than the board re-scanned.
    """
    game, caster = _w2g1e_scene(set_pool, "Badlands")

    result = game.activate_permanent_ability(
        0, "Squandered Resources", cost_permanent_index=1, mana_color="R",
    )

    assert result.supported, result.details
    assert caster.mana_pool["R"] == 1
    assert [p.card.name for p in caster.battlefield] == ["Squandered Resources"]
    assert [c.name for c in caster.graveyard] == ["Badlands"]
def test_squandered_resources_clamps_a_type_the_land_could_not_make(set_pool):
    """CR 609.3: the payer chooses among the types the land could produce, and
    a choice outside that set is not one of them."""
    game, caster = _w2g1e_scene(set_pool, "Badlands")

    game.activate_permanent_ability(
        0, "Squandered Resources", cost_permanent_index=1, mana_color="W",
    )

    assert caster.mana_pool["W"] == 0
    assert caster.mana_pool["B"] == 1
def _w2g1e_card(text):
    return _W2G1eCardDefinition(
        name="W2G1 Probe", mana_cost="{1}", cmc=1.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "W2G1 Probe"},
    )
def test_the_sacrificed_land_phrase_refuses_where_no_cost_sacrifices():
    """A back-reference with no payment behind it names no land, so the line
    refuses at lowering rather than adding a colour off nothing.

    Refused where the *cost* is visible, which the effect production is not:
    the words parse, and what they name is a payment this ability never makes.
    """
    program = _w2g1e_compile(_w2g1e_card(
        "{T}: Add one mana of any type the sacrificed land could produce."
    ))
    assert not program.supported

    # …and a phrase the production does not read refuses in the parse, before
    # any cost is consulted: a production consumes its whole line or raises.
    with pytest.raises(_W2G1eGrammarError):
        _w2g1e_parse("Add one mana of any type the exiled land could produce.")

def _w2g5e_table(set_pool, library, *, interactive=False, life=20):
    crypt = set_pool("VIS")["Breathstealer's Crypt"]
    p1 = _W2G5EPlayer(name="P1")
    p2 = _W2G5EPlayer(name="P2", library=list(library))
    p2.life = life
    game = _W2G5EGame(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {1}
    permanent = _W2G5EPermanent(card=crypt)
    permanent.permanent_id = 1
    p1.battlefield.append(permanent)
    return game, p1, p2
def test_breathstealers_crypt_is_supported(set_pool):
    card = set_pool("VIS")["Breathstealer's Crypt"]
    assert _w2g5e_program(card).supported
def test_the_crypt_still_draws_the_card(set_pool, set_cards):
    """The one draw replacement here that does not consume the draw.

    "instead they draw a card and reveal it" — CR 614.1 replaces the event with
    a modified one, and the modification is a reveal and a rider.
    """
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(set_pool, [lea["Lightning Bolt"]])

    game._draw_with_replacements(p2, 1)

    assert [c.name for c in p2.hand] == ["Lightning Bolt"]
    assert p2.life == 20
    assert game.pending_choices == []
    assert any("drew and revealed Lightning Bolt" in line for line in game.log)
def test_a_drawn_creature_card_is_taxed_and_kept_when_the_life_is_paid(
    set_pool, set_cards
):
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(set_pool, [lea["Grizzly Bears"]])

    game._draw_with_replacements(p2, 1)

    assert [c.name for c in p2.hand] == ["Grizzly Bears"]
    assert p2.life == 17
def test_a_seat_that_cannot_pay_discards_the_card_it_drew(set_pool, set_cards):
    """CR 119.4: a payment of N life needs N life to pay with.

    The stated default never pays a seat down to nothing for one card, so at
    exactly the price the card goes.
    """
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(set_pool, [lea["Grizzly Bears"]], life=3)

    game._draw_with_replacements(p2, 1)

    assert p2.hand == []
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
    assert p2.life == 3
def test_an_interactive_seat_is_asked_rather_than_defaulted(set_pool, set_cards):
    """The prompt has to be armed for a seat that answers its own questions to
    prove nothing — a headless reading only ever shows the default running."""
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(set_pool, [lea["Grizzly Bears"]], interactive=True)

    game._draw_with_replacements(p2, 1)

    assert [c.kind for c in game.pending_choices] == ["discard_unless_pay_life"]
    offer = game.pending_choices[0]
    assert offer.player_index == 1
    assert offer.data["card_name"] == "Grizzly Bears"
    assert offer.data["life"] == 3
    assert p2.life == 20

    game.confirm_discard_unless_pay_life(1, False)

    assert p2.hand == []
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
    assert p2.life == 20
def test_the_draws_queued_behind_the_offer_wait_for_it(set_pool, set_cards):
    """CR 608.2 / CR 121.2. A two-card draw is two events, and the second may
    not arrive while the offer about the first is still open."""
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(
        set_pool, [lea["Grizzly Bears"], lea["Lightning Bolt"]], interactive=True
    )

    game._draw_with_replacements(p2, 2)

    assert [c.name for c in p2.hand] == ["Grizzly Bears"]
    assert [c.kind for c in game.pending_choices] == ["discard_unless_pay_life"]

    game.confirm_discard_unless_pay_life(1, True)

    assert [c.name for c in p2.hand] == ["Grizzly Bears", "Lightning Bolt"]
    assert p2.life == 17
    assert game.pending_choices == []
def test_each_card_of_a_multi_card_draw_gets_its_own_offer(set_pool, set_cards):
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(
        set_pool, [lea["Grizzly Bears"], lea["Grizzly Bears"]]
    )

    game._draw_with_replacements(p2, 2)

    assert [c.name for c in p2.hand] == ["Grizzly Bears", "Grizzly Bears"]
    assert p2.life == 14
def test_the_discard_takes_one_copy_and_not_every_copy(set_pool, set_cards):
    """A hand repeats one immutable ``CardDefinition`` per copy, so filtering a
    hand by identity removes all of them. Three Bears in, two Bears left."""
    lea = {c.name: c for c in set_cards("LEA")}
    game, _, p2 = _w2g5e_table(set_pool, [lea["Grizzly Bears"]], life=1)
    p2.hand = [lea["Grizzly Bears"], lea["Grizzly Bears"]]

    game._draw_with_replacements(p2, 1)

    assert [c.name for c in p2.hand] == ["Grizzly Bears", "Grizzly Bears"]
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
