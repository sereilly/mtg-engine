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
from engine.auras import attach_aura as _w2g3_attach
from engine.card_loader import load_cards as _w2g3_load, manifest_set_paths as _w2g3_paths
from engine.models import Permanent as _W2G3Permanent
from engine.pt import add_pt_modifier as _w2g3_pump
from engine import Game as _W2G3Game, PlayerState as _W2G3Player
from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.card_loader import load_cards as _w2g2_load
from engine.card_loader import manifest_set_paths as _w2g2_paths
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile
import pytest as _w3g2_pytest
from engine import Game as _W3G2Game, PlayerState as _W3G2Player
from engine.card_loader import (load_cards as _w3g2_load,
                                manifest_set_paths as _w3g2_paths)
from engine.grammar import parse_line as _w3g2_parse
from engine.grammar.errors import GrammarError as _W3G2GrammarError
from engine.grammar.lower import lower_ability as _w3g2_lower
from engine.models import Permanent as _W3G2Permanent
from engine.oracle import compile_card_oracle as _w3g2_compile
import pytest as _w3g1e_pytest  # noqa: E402
from engine import Game as _W3G1eGame, PlayerState as _W3G1ePlayerState  # noqa: E402
from engine.card_loader import (  # noqa: E402
    load_cards as _w3g1e_load, manifest_set_path as _w3g1e_path,
)
from engine.cast_permissions import (  # noqa: E402
    playable_from_zones as _w3g1e_playable,
)
from engine.grammar import (  # noqa: E402
    lower_ability as _w3g1e_lower, parse_line as _w3g1e_parse,
)
from engine.grammar.errors import (  # noqa: E402
    GrammarError as _W3G1eGrammarError, LoweringError as _W3G1eLoweringError,
)
from engine.models import Permanent as _W3G1ePermanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g1e_compile  # noqa: E402
# --- W3G3: Equipoise, a process repeated for a printed list of card types ---
from engine import Game as _W3G3EGame, PlayerState as _W3G3EPlayer
from engine.card_loader import load_cards as _w3g3e_load, manifest_set_path as _w3g3e_path
from engine.models import Permanent as _W3G3EPermanent
from engine.oracle import compile_card_oracle as _w3g3e_compile

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
def _w2g3_rig():
    alice, bob = _W2G3Player(name="Alice"), _W2G3Player(name="Bob")
    game = _W2G3Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob
def _w2g3_enters(game, seat, card):
    """Put *card* onto the battlefield and let its entry triggers resolve.

    Draining the stack is the point rather than a convenience: Eye of
    Singularity's whole second line is a trigger on somebody else's entry, and a
    helper that left it queued would assert about a board the sweep had not
    reached yet.
    """
    permanent = _W2G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    while game.stack:
        game.resolve_top_of_stack()
    return permanent
def _w2g3_board(game):
    return {
        seat: sorted(perm.card.name for perm in player.battlefield)
        for seat, player in enumerate(game.players)
    }
def test_vampirism_counts_the_board_and_shrinks_everything_else(set_pool, catalog_by_name):
    """"Enchanted creature gets +1/+1 for each other creature you control.
    Other creatures you control get -1/-1."

    Two layer-7c contributions from one Aura, and the first is what was missing:
    the counted grant lowers to ``dynamic_pt_bonus`` carrying
    ``subject: "attached"``, which the P/T refresh lands on the host.

    The host's own arithmetic is what the two sentences agree on. "Other" is
    relative to the object the ability is on (CR 109.5), and Vampirism is not a
    creature -- so the count includes the host and the penalty reaches it too,
    which nets to exactly the reading where both words exclude it. Three
    creatures, one enchanted: 2 + 3 - 1 = 4.
    """
    game, alice, _bob = _w2g3_rig()
    bears = [_w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"]) for _ in range(3)]
    aura = _w2g3_enters(game, 0, set_pool("VIS")["Vampirism"])
    _w2g3_attach(aura, bears[0])
    game._recompute_continuous_effects()

    assert (bears[0].effective_power, bears[0].effective_toughness) == (4, 4)
    assert (bears[1].effective_power, bears[1].effective_toughness) == (1, 1)
    assert (bears[2].effective_power, bears[2].effective_toughness) == (1, 1)

    # A fourth creature moves the count on the next recompute -- the grant is
    # derived, never remembered (CR 613.4b).
    _w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"])
    game._recompute_continuous_effects()
    assert (bears[0].effective_power, bears[0].effective_toughness) == (5, 5)
def test_vampirism_on_an_opponents_creature_counts_the_auras_controller(
    set_pool, catalog_by_name
):
    """CR 109.5: "you" is the controller of the *Aura*, whichever creature it is
    stuck to. So the host grows by the enchanter's board and the enchanter's own
    creatures take the -1/-1 -- the opponent's do not."""
    game, _alice, _bob = _w2g3_rig()
    mine = [_w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"]) for _ in range(2)]
    host = _w2g3_enters(game, 1, catalog_by_name["Grizzly Bears"])
    aura = _w2g3_enters(game, 0, set_pool("VIS")["Vampirism"])
    _w2g3_attach(aura, host)
    game._recompute_continuous_effects()

    assert (host.effective_power, host.effective_toughness) == (4, 4)
    assert all((p.effective_power, p.effective_toughness) == (1, 1) for p in mine)
def test_vampirisms_counted_grant_is_not_also_read_as_a_flat_one(set_pool):
    """The line says "+1/+1 **for each** other creature", and
    ``aura_static_pt_grant``'s pattern matches its prefix.

    Answering there would have added a flat +1/+1 on top of the count the
    layer-7c refresh already contributes -- the enchanted creature one point too
    big in each half, from a reader that never saw the multiplier. Asserted at
    the reader rather than through a board, because that is where the two
    answers would disagree.
    """
    from engine.auras import aura_static_pt_grant

    assert aura_static_pt_grant(set_pool("VIS")["Vampirism"].oracle_text) is None
def test_death_watch_reads_the_creature_as_it_last_existed(set_pool, catalog_by_name):
    """"When enchanted creature dies, its controller loses life equal to its
    power and you gain life equal to its toughness."

    CR 603.10: both numbers are last known information. The creature is pumped
    before it dies, so the printed 3/3 and the frozen 5/7 are different answers
    and only one of them can be read off a graveyard card.

    "Its controller" is the *dead creature's* (CR 109.5 does not reach it -- the
    possessive names the object the event was about), which is the opponent
    here, while "you" is the Aura's controller.
    """
    game, alice, bob = _w2g3_rig()
    victim = _w2g3_enters(game, 1, catalog_by_name["Hill Giant"])
    aura = _w2g3_enters(game, 0, set_pool("VIS")["Death Watch"])
    _w2g3_attach(aura, victim)
    game._recompute_continuous_effects()
    _w2g3_pump(victim, 2, 4, until="end_of_turn")
    game._recompute_continuous_effects()
    assert (victim.effective_power, victim.effective_toughness) == (5, 7)

    game._destroy_swept_permanents(bob, lambda perm: perm is victim)
    while game.stack:
        game.resolve_top_of_stack()

    assert bob.life == 20 - 5
    assert alice.life == 20 + 7
def test_death_watch_on_your_own_creature_charges_you(set_pool, catalog_by_name):
    """The two seats are read separately, so an Aura on your own creature takes
    the life from you and gives it back -- which is the case where a single
    "caster" reading for both halves would have looked right."""
    game, alice, _bob = _w2g3_rig()
    victim = _w2g3_enters(game, 0, catalog_by_name["Hill Giant"])
    aura = _w2g3_enters(game, 0, set_pool("VIS")["Death Watch"])
    _w2g3_attach(aura, victim)
    game._recompute_continuous_effects()

    game._destroy_swept_permanents(alice, lambda perm: perm is victim)
    while game.stack:
        game.resolve_top_of_stack()

    assert alice.life == 20 - 3 + 3
def test_mob_mentality_fires_only_when_every_non_wall_attacks(set_pool, catalog_by_name):
    """"Whenever all non-Wall creatures you control attack, enchanted creature
    gets +X/+0 until end of turn, where X is the number of attacking creatures."

    CR 508.1's declaration, asked as a comparison of two sets rather than as a
    count: a Wall that stays home is not a creature the sentence describes, and
    a Bear that stays home is.
    """
    def _attack(hold_back=False, with_wall=False):
        game, alice, _bob = _w2g3_rig()
        bears = []
        for _ in range(2):
            bear = _w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"])
            bear.metadata["summoning_sickness_turn"] = -99
            bears.append(bear)
        if with_wall:
            wall = _w2g3_enters(game, 0, catalog_by_name["Wall of Stone"])
            wall.metadata["summoning_sickness_turn"] = -99
        aura = _w2g3_enters(game, 0, set_pool("VIS")["Mob Mentality"])
        _w2g3_attach(aura, bears[0])
        game._recompute_continuous_effects()
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.current_step == "declare_attackers"
        attacking = [i for i, perm in enumerate(alice.battlefield) if perm in bears]
        game.declare_attackers(0, attacking[:1] if hold_back else attacking)
        while game.stack:
            game.resolve_top_of_stack()
        game._recompute_continuous_effects()
        return bears[0]

    assert (_attack().effective_power, _attack().effective_toughness) == (4, 2)
    # A Wall is exempt by name, so the sentence is satisfied without it.
    assert _attack(with_wall=True).effective_power == 4
    # A creature the phrase *does* describe staying home is what stops it.
    assert _attack(hold_back=True).effective_power == 2
def test_mob_mentality_grants_trample_while_attached(set_pool, catalog_by_name):
    """The Aura's other line, and the one that says the whole card is read: a
    keyword grant derived from the Aura's text while it is attached, which ends
    by the Aura ceasing to be attached rather than by a remembered delta."""
    from engine.auras import detach_aura

    game, _alice, _bob = _w2g3_rig()
    bear = _w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"])
    aura = _w2g3_enters(game, 0, set_pool("VIS")["Mob Mentality"])
    _w2g3_attach(aura, bear)
    game._recompute_continuous_effects()
    assert bear.has_keyword("trample")

    detach_aura(aura, bear)
    game._recompute_continuous_effects()
    assert not bear.has_keyword("trample")
def test_eye_of_singularity_sweeps_the_duplicates_and_spares_basic_lands(
    set_pool, catalog_by_name
):
    """"When this enchantment enters, destroy each permanent with the same name
    as another permanent, except for basic lands."

    Every copy goes, not all-but-one: the sentence describes each permanent that
    has a twin. The exemption is asserted with *three* Forests across two
    battlefields, which is the set a dropped "except for basic lands" would take.
    """
    game, _alice, _bob = _w2g3_rig()
    _w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"])
    _w2g3_enters(game, 1, catalog_by_name["Grizzly Bears"])
    _w2g3_enters(game, 0, catalog_by_name["Hill Giant"])
    _w2g3_enters(game, 0, catalog_by_name["Forest"])
    _w2g3_enters(game, 0, catalog_by_name["Forest"])
    _w2g3_enters(game, 1, catalog_by_name["Forest"])
    _w2g3_enters(game, 0, catalog_by_name["Mox Pearl"])

    _w2g3_enters(game, 0, set_pool("VIS")["Eye of Singularity"])

    assert _w2g3_board(game) == {
        0: ["Eye of Singularity", "Forest", "Forest", "Hill Giant", "Mox Pearl"],
        1: ["Forest"],
    }
def test_eye_of_singularity_keeps_the_permanent_that_just_entered(
    set_pool, catalog_by_name
):
    """"Whenever a permanent other than a basic land enters, destroy all other
    permanents with that name."

    "Other" is relative to the permanent that entered, not to the Eye -- so the
    newcomer survives and the incumbent dies. A basic land entering fires
    nothing, which is the half the trigger's own noun phrase carries.
    """
    game, _alice, _bob = _w2g3_rig()
    _w2g3_enters(game, 0, set_pool("VIS")["Eye of Singularity"])
    incumbent = _w2g3_enters(game, 0, catalog_by_name["Hill Giant"])
    _w2g3_enters(game, 0, catalog_by_name["Forest"])

    newcomer = _w2g3_enters(game, 1, catalog_by_name["Hill Giant"])
    assert _w2g3_board(game) == {0: ["Eye of Singularity", "Forest"], 1: ["Hill Giant"]}
    assert newcomer in game.players[1].battlefield
    assert incumbent not in game.players[0].battlefield

    # A second Forest is a basic land: the trigger's noun phrase excludes it, so
    # both Forests stay.
    _w2g3_enters(game, 1, catalog_by_name["Forest"])
    assert _w2g3_board(game) == {
        0: ["Eye of Singularity", "Forest"], 1: ["Forest", "Hill Giant"],
    }
def test_eye_of_singularity_sweeps_past_a_regeneration_shield(set_pool, catalog_by_name):
    """"They can't be regenerated." (CR 701.19c.) The rider is on both of the
    card's sentences, and a sweep that dropped it would leave a shielded
    duplicate standing -- which is the whole of what the card is for."""
    game, _alice, _bob = _w2g3_rig()
    first = _w2g3_enters(game, 0, catalog_by_name["Grizzly Bears"])
    second = _w2g3_enters(game, 1, catalog_by_name["Grizzly Bears"])
    for perm in (first, second):
        perm.regeneration_shield = 1

    _w2g3_enters(game, 0, set_pool("VIS")["Eye of Singularity"])

    assert _w2g3_board(game) == {0: ["Eye of Singularity"], 1: []}
    # The shields are still on them, unspent: a sweep that "worked" by burning
    # a shield and then destroying the survivor on a second pass would pass the
    # board check above and fail this one.
    assert (first.regeneration_shield, second.regeneration_shield) == (1, 1)
def _w2g2_catalog():
    return {card.name: card for card in _w2g2_load(_w2g2_paths(include_measured=True))}
def _w2g2_board(*battlefields, hands=None):
    players = [
        _W2G2PlayerState(
            name=f"P{i + 1}",
            battlefield=list(pile),
            hand=list((hands or {}).get(i, [])),
        )
        for i, pile in enumerate(battlefields)
    ]
    game = _W2G2Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for player in players:
        for perm in player.battlefield:
            perm.metadata["summoning_sickness_turn"] = -99
    return game
def _w2g2_slot(player, permanent):
    return next(i for i, perm in enumerate(player.battlefield) if perm is permanent)
def test_city_of_solitude_binds_its_own_controller_on_another_players_turn(set_pool):
    """"Players can cast spells and activate abilities only during their own
    turns."

    The sentence names no seat, so it binds everybody -- the enchantment's
    controller included (CR 601.3, CR 602.5). A gate that exempted the
    controller would be a strictly better card than the one printed, and it
    would be silent about it.
    """
    catalog = _w2g2_catalog()
    city = _W2G2Permanent(card=set_pool("VIS")["City of Solitude"])
    icy = _W2G2Permanent(card=catalog["Icy Manipulator"])
    bear = _W2G2Permanent(card=catalog["Grizzly Bears"])
    game = _w2g2_board([city, icy], [bear], hands={0: [catalog["Lightning Bolt"]]})
    game.start_turn(1)

    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported and "City of Solitude" in refused.details
    assert game.players[1].life == 20, game.log

    refused = game.activate_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, target_permanent_index=0
    )
    assert not refused.supported and "City of Solitude" in refused.details
    assert not bear.tapped, game.log
def test_city_of_solitude_is_a_window_not_a_lock(set_pool):
    """The same seat plays freely on its own turn -- the restriction is when,
    not whether."""
    catalog = _w2g2_catalog()
    city = _W2G2Permanent(card=set_pool("VIS")["City of Solitude"])
    icy = _W2G2Permanent(card=catalog["Icy Manipulator"])
    bear = _W2G2Permanent(card=catalog["Grizzly Bears"])
    game = _w2g2_board([city, icy], [bear], hands={0: [catalog["Lightning Bolt"]]})
    game.start_turn(0)

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.activate_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, target_permanent_index=0
    ).supported
    assert bear.tapped
def test_katabatic_winds_grounds_fliers_and_shuts_off_their_tap_abilities(set_pool):
    """"Creatures with flying can't attack or block, and their activated
    abilities with {T} in their costs can't be activated."

    One printed sentence, three prohibitions, one noun phrase -- so one
    derivation row arms all three and the three enforcement sites read one
    subject. The enchantment sits on the opponent's side here because it also
    prints phasing: on its own controller's untap step it would phase out
    before the first declaration, which is the card working.
    """
    catalog = _w2g2_catalog()
    winds = _W2G2Permanent(card=set_pool("VIS")["Katabatic Winds"])
    flier = _W2G2Permanent(card=catalog["Birds of Paradise"])
    ground = _W2G2Permanent(card=catalog["Grizzly Bears"])
    attacker = _W2G2Permanent(card=catalog["Hill Giant"])

    game = _w2g2_board([flier, ground], [winds])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert not game.declare_attackers(0, [_w2g2_slot(game.players[0], flier)])[0]
    assert game.declare_attackers(0, [_w2g2_slot(game.players[0], ground)])[0]

    blocks = _w2g2_board([flier, ground], [winds, attacker])
    assert not blocks._can_block_attacker(flier, attacker)
    assert blocks._can_block_attacker(ground, attacker)

    taps = _w2g2_board([flier], [winds])
    taps.start_turn(0)
    refused = taps.activate_permanent_ability(0, "Birds of Paradise", mana_color="G")
    assert not refused.supported and "Katabatic Winds" in refused.details
    assert taps.players[0].mana_pool.get("G", 0) == 0
def test_katabatic_winds_leaves_the_grounded_alone(set_pool):
    """The narrowing is the card. A restriction that dropped "with flying"
    would ground the whole board and shut off every tap ability there is --
    over-restriction, exactly as silent as the widening this family usually
    guards against."""
    catalog = _w2g2_catalog()
    winds = _W2G2Permanent(card=set_pool("VIS")["Katabatic Winds"])
    llanowar = _W2G2Permanent(card=catalog["Llanowar Elves"])
    game = _w2g2_board([llanowar], [winds])
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Llanowar Elves", mana_color="G"
    ).supported, game.log
def test_righteous_war_protects_only_the_creatures_its_controller_has(set_pool):
    """"White creatures you control have protection from black." / "Black
    creatures you control have protection from white."

    Two lines, two anthems, one derivation. Both halves are a layer-6 grant
    whose *parameter* is a colour, which is why protection travels on its own
    field rather than in the keyword list: "protection" names a quality and a
    keyword list has nowhere to put one.
    """
    catalog = _w2g2_catalog()
    war = _W2G2Permanent(card=set_pool("VIS")["Righteous War"])
    mine_white = _W2G2Permanent(card=catalog["Savannah Lions"])
    mine_black = _W2G2Permanent(card=catalog["Bog Wraith"])
    theirs_white = _W2G2Permanent(card=catalog["Savannah Lions"])
    game = _w2g2_board([war, mine_white, mine_black], [theirs_white])

    program = _w2g2_compile(set_pool("VIS")["Righteous War"])
    assert program.supported, program.reason
    assert [i.payload.get("protection_from") for i in program.instructions] == [
        ["black"], ["white"],
    ]

    assert ("color", "B") in game._protection_qualities(mine_white)
    assert ("color", "W") in game._protection_qualities(mine_black)
    assert game._protection_qualities(theirs_white) == set()
def test_righteous_war_stops_a_black_spell_targeting_a_white_creature(set_pool):
    """CR 702.16b is what the grant then does, and it is what a player sees.

    Watching the refusal is the point: a grant that reached the metadata and no
    gate would look exactly like one that worked.
    """
    catalog = _w2g2_catalog()
    war = _W2G2Permanent(card=set_pool("VIS")["Righteous War"])
    lions = _W2G2Permanent(card=catalog["Savannah Lions"])
    game = _w2g2_board([war, lions], [])
    game.players[1].hand = [catalog["Dark Banishing"]]
    game.players[1].library = [catalog["Swamp"]] * 20
    game.start_turn(1)

    assert not game._can_be_targeted(
        lions, catalog["Dark Banishing"], caster_index=1
    ), game.log
_W3G2_POOL: dict = {}
for _w3g2_path in _w3g2_paths(include_measured=True):
    for _w3g2_card in _w3g2_load(_w3g2_path):
        _W3G2_POOL.setdefault(_w3g2_card.name, _w3g2_card)
def _w3g2_perm(name: str) -> "_W3G2Permanent":
    return _W3G2Permanent(card=_W3G2_POOL[name])
def _w3g2_game(p0_lands, p1_lands, *, interactive=()) -> "_W3G2Game":
    """Desolation on seat 0's battlefield, with the lands each seat holds."""
    game = _W3G2Game(players=[_W3G2Player(name="P0"), _W3G2Player(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.players[0].battlefield = (
        [_w3g2_perm("Desolation")] + [_w3g2_perm(n) for n in p0_lands]
    )
    game.players[1].battlefield = [_w3g2_perm(n) for n in p1_lands]
    game._sync_control()
    game.active_player_index = 0
    return game
def _w3g2_end_step(game: "_W3G2Game") -> "_W3G2Game":
    game.resolve_end_step(0)
    game.resolve_stack()
    return game
def _w3g2_names(game: "_W3G2Game", seat: int) -> list[str]:
    return [perm.card.name for perm in game.players[seat].battlefield]
def test_w3g2_desolation_compiles_both_sentences_as_one_trigger():
    program = _w3g2_compile(_W3G2_POOL["Desolation"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "end_step"
    sacrifice, damage = trigger.instruction.payload["steps"]
    # The narrowing rides the payload of each step — never a kind of its own,
    # and never dropped: a sacrifice with no `who_did` is every seat at the
    # table, which is the failure this card's whole family guards against.
    assert sacrifice.payload["who"] == "each_player"
    assert sacrifice.payload["who_did"] == {
        "kind": "tapped_land_for_mana_this_turn"
    }
    assert damage.payload["recipient"] == "each_player"
    assert damage.payload["recipient_did"] == {
        "kind": "sacrificed_this_way", "filter": {"subtype_filter": "plains"},
    }
def test_w3g2_desolation_asks_only_the_seat_that_tapped_a_land_for_mana():
    game = _w3g2_game(["Plains", "Forest"], ["Plains", "Island"])
    assert game.tap_land_for_mana(0, "Plains"), game.log
    _w3g2_end_step(game)
    # P0 tapped and paid; P1 tapped nothing and keeps both lands.
    assert _w3g2_names(game, 0) == ["Desolation", "Forest"], game.log
    assert _w3g2_names(game, 1) == ["Plains", "Island"], game.log
    assert [p.life for p in game.players] == [18, 20], game.log
def test_w3g2_desolation_damages_only_the_seat_that_gave_up_a_plains():
    # The only land this seat has is a Forest, so it sacrifices — and takes
    # nothing, because the second sentence asks what went and not whether
    # anything did.
    game = _w3g2_game(["Forest"], [])
    assert game.tap_land_for_mana(0, "Forest"), game.log
    _w3g2_end_step(game)
    assert _w3g2_names(game, 0) == ["Desolation"], game.log
    assert [p.life for p in game.players] == [20, 20], game.log
def test_w3g2_desolation_does_nothing_when_nobody_tapped_for_mana():
    game = _w3g2_game(["Plains"], ["Plains"])
    _w3g2_end_step(game)
    assert _w3g2_names(game, 0) == ["Desolation", "Plains"], game.log
    assert _w3g2_names(game, 1) == ["Plains"], game.log
    assert [p.life for p in game.players] == [20, 20], game.log
def test_w3g2_desolation_hits_both_seats_when_both_tapped():
    game = _w3g2_game(["Plains"], ["Plains"])
    assert game.tap_land_for_mana(0, "Plains"), game.log
    assert game.tap_land_for_mana(1, "Plains"), game.log
    _w3g2_end_step(game)
    assert [p.life for p in game.players] == [18, 18], game.log
@_w3g2_pytest.mark.parametrize(
    "picked, expected_life, expected_board",
    [("Plains", 18, ["Desolation", "Forest"]),
     ("Forest", 20, ["Desolation", "Plains"])],
)
def test_w3g2_desolation_reads_an_interactive_seats_own_pick(
    picked, expected_life, expected_board
):
    """The record is written where the sacrifice happens, and the damage step
    resumes behind the prompt — so which land a *human* seat gives up is what
    decides the damage, exactly as the headless default does."""
    game = _w3g2_game(["Plains", "Forest"], [], interactive=(0,))
    assert game.tap_land_for_mana(0, "Forest"), game.log
    _w3g2_end_step(game)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("sacrifice", 0)
    ], game.log
    assert [p.life for p in game.players] == [20, 20], game.log
    index = _w3g2_names(game, 0).index(picked)
    assert game.resolve_pending_choice("sacrifice", 0, indices=[index]), game.log
    assert _w3g2_names(game, 0) == expected_board, game.log
    assert game.players[0].life == expected_life, game.log
def test_w3g2_the_tap_record_forgets_at_the_next_turn():
    game = _w3g2_game(["Plains"], ["Plains"])
    assert game.tap_land_for_mana(0, "Plains"), game.log
    assert game.players[0].tapped_land_for_mana_this_turn
    game.begin_turn_bookkeeping(1)
    assert not any(p.tapped_land_for_mana_this_turn for p in game.players)
def test_w3g2_a_seat_narrowing_no_reader_enforces_refuses_the_line():
    """The clause parses only where a lowering carries it. Under any other verb
    it is put back and the line fails on it — loud, rather than a sentence that
    quietly acts on every player."""
    with _w3g2_pytest.raises(_W3G2GrammarError):
        _w3g2_parse(
            "Each player who tapped a land for mana this turn draws a card."
        )
    with _w3g2_pytest.raises(_W3G2GrammarError):
        _w3g2_parse("Each player who ate a sandwich this turn sacrifices a land.")
    # And the damage recipient takes it only on the seat *sets*: a chosen seat
    # is answered by a picker, which has no record to read.
    with _w3g2_pytest.raises(_W3G2GrammarError):
        _w3g2_parse(
            "This enchantment deals 2 damage to target player who sacrificed "
            "a Plains this way."
        )
def test_w3g2_a_this_way_narrowing_the_card_matcher_cannot_test_refuses():
    """"Who sacrificed …" reads a list of cards in a graveyard, which has no
    computed characteristics (CR 613.1) — so a narrowing outside what a printed
    card answers is refused rather than dropped."""
    from engine.grammar.errors import LoweringError as _W3G2LoweringError

    node = _w3g2_parse(
        "This enchantment deals 2 damage to each player who sacrificed "
        "a tapped creature this way."
    )
    with _w3g2_pytest.raises(_W3G2LoweringError):
        _w3g2_lower(node)
@_w3g1e_pytest.fixture(scope="module")
def _w3g1e_lea():
    return {c.name: c for c in _w3g1e_load(_w3g1e_path("LEA"))}
def _w3g1e_board(set_pool, lea, opponent_hand=("Mox Pearl",)):
    """Elkin Lair under seat 0, with a known card in each hand."""
    pool = set_pool("VIS")
    game = _W3G1eGame(players=[
        _W3G1ePlayerState(
            name="P1", battlefield=[_W3G1ePermanent(card=pool["Elkin Lair"])],
            hand=[lea["Black Lotus"]], library=[lea["Island"]] * 10,
        ),
        _W3G1ePlayerState(
            name="P2", hand=[lea[name] for name in opponent_hand],
            library=[lea["Island"]] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    # Before anything resolves: a headless seat answers its own prompts, and a
    # reading taken without this is a reading of the defaults.
    game.interactive_seats = {0, 1}
    game.active_player_index = 1
    return game
def test_elkin_lair_is_supported(set_pool):
    program = _w3g1e_compile(set_pool("VIS")["Elkin Lair"])
    assert program.supported, program.reason
    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "upkeep_each"
    steps = trigger.instruction.payload["steps"]
    assert [i.kind for i in steps] == [
        "exile_random_card_from_hand",
        "grant_cast_permission",
        "create_delayed_trigger",
    ]
    # Both halves name the seat the firing event froze, not the controller.
    assert steps[0].payload["recipient"] == "event_subject_player"
    assert steps[1].payload["recipient"] == "event_subject_player"
    assert steps[2].payload["event"] == "next_end_step"
def test_elkin_lair_exiles_from_the_upkeep_players_own_hand(set_pool, _w3g1e_lea):
    """"At the beginning of each player's upkeep, **that player** exiles a card
    at random from their hand."

    The seat varies every upkeep, so it is the one the fire site froze
    (CR 603.10) rather than the enchantment's controller — read as the
    controller this would take a card out of seat 0's hand on seat 1's upkeep,
    which is silent, because both readings exile exactly one card.
    """
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.resolve_upkeep(1)
    game.resolve_stack()

    assert game.players[1].hand == []
    assert [c.name for c in game.players[1].exile] == ["Mox Pearl"]
    # Seat 0 kept its own hand: this was not seat 0's upkeep.
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]
    assert game.players[0].exile == []
def test_elkin_lair_permits_the_player_it_exiled_from_and_nobody_else(
    set_pool, _w3g1e_lea
):
    """"**The player** may play that card this turn." — CR 601.3 grants the
    permission to the player the sentence names.

    Read as "you" the enchantment's controller would be allowed to play a card
    out of an opponent's exile, which is a strictly different card and a silent
    one: the grant exists either way.
    """
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.resolve_upkeep(1)
    game.resolve_stack()

    grant = game.cast_permissions[0]
    assert (grant.player_index, grant.zone_seat) == (1, 1)
    assert grant.mode == "play"          # CR 701.18b: a land is played
    assert grant.duration == "end_of_turn"
    assert [e["name"] for e in _w3g1e_playable(game, 1)] == ["Mox Pearl"]
    assert _w3g1e_playable(game, 0) == []

    result = game.cast_from_hand(1, "Mox Pearl", from_zone="exile")
    assert result.supported, result.details
    game.resolve_stack()
    assert [p.card.name for p in game.controlled_by(1)] == ["Mox Pearl"]
def test_elkin_lair_bins_the_card_at_the_next_end_step(set_pool, _w3g1e_lea):
    """"At the beginning of the next end step, if the player hasn't played the
    card, they put it into their graveyard." — CR 603.7's delayed ability.

    "Their graveyard" resolves to the card's owner's, which is CR 400.3 rather
    than a convenience: a card put into a graveyard goes to its owner's whoever
    the sentence says is doing the putting.
    """
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.resolve_upkeep(1)
    game.resolve_stack()

    game.resolve_end_step(1)
    game.resolve_stack()

    assert game.players[1].exile == []
    assert [c.name for c in game.players[1].graveyard] == ["Mox Pearl"]
    assert game.players[0].graveyard == []
def test_elkin_lair_bins_nothing_when_the_card_was_played(set_pool, _w3g1e_lea):
    """The printed condition needs no flag: a card the player played is not in
    exile any more, and the bin only moves cards out of exile."""
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.resolve_upkeep(1)
    game.resolve_stack()
    assert game.cast_from_hand(1, "Mox Pearl", from_zone="exile").supported
    game.resolve_stack()

    game.resolve_end_step(1)
    game.resolve_stack()

    assert game.players[1].graveyard == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Mox Pearl"]
def test_elkin_lair_on_an_empty_hand_exiles_and_permits_nothing(
    set_pool, _w3g1e_lea
):
    """An empty hand is a legal outcome rather than an error, and the two
    sentences behind it must not invent a card to permit."""
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.players[1].hand.clear()
    game.resolve_upkeep(1)
    game.resolve_stack()

    assert game.players[1].exile == []
    assert game.cast_permissions == []
def test_elkin_lair_fires_on_its_own_controllers_upkeep_too(set_pool, _w3g1e_lea):
    """"each player's upkeep" is every seat, the controller's included — the
    seat is payload, not a narrowing to the opponents."""
    game = _w3g1e_board(set_pool, _w3g1e_lea)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert [c.name for c in game.players[0].exile] == ["Black Lotus"]
    assert game.cast_permissions[0].player_index == 0
def test_a_random_hand_exile_needs_an_event_that_names_the_seat(set_pool):
    """"That player exiles a card at random from their hand" on a **spell** has
    no firing event to freeze a seat, so it refuses rather than falling back to
    the caster — the wrong hand is not a smaller effect."""
    with _w3g1e_pytest.raises(_W3G1eLoweringError):
        _w3g1e_lower(_w3g1e_parse(
            "That player exiles a card at random from their hand."
        ))
def test_a_random_hand_exile_must_consume_its_whole_object_phrase(set_pool):
    """The production reads "a card at random from their hand" or refuses. A
    reader that took the verb and shrugged at its object would claim "that
    player exiles all cards from their library" as well."""
    with _w3g1e_pytest.raises(_W3G1eGrammarError):
        _w3g1e_parse(
            "At the beginning of each player's upkeep, that player exiles a "
            "card at random from their graveyard."
        )
def test_the_whole_library_exile_still_reads_its_own_sentence(set_pool):
    """The sibling production under the same verb keeps its reading — neither
    can claim the other, because they differ from the verb's object on."""
    node = _w3g1e_parse(
        "At the beginning of each player's upkeep, that player exiles all "
        "cards from their library."
    )
    assert [i.kind for i in _w3g1e_lower(node)] == ["exile_entire_library"]
def test_a_permission_to_the_player_needs_an_event_that_names_one(set_pool):
    """"The player may play that card this turn" on a spell names nobody the
    resolution can identify, so it refuses rather than granting to the caster."""
    with _w3g1e_pytest.raises((_W3G1eGrammarError, _W3G1eLoweringError)):
        _w3g1e_lower(_w3g1e_parse(
            "Exile the top card of your library. The player may play that "
            "card this turn."
        ))

_W3G3E_LEA = {c.name: c for c in _w3g3e_load(_w3g3e_path("LEA"))}
def _w3g3e_game():
    game = _W3G3EGame(players=[
        _W3G3EPlayer(name="P1", battlefield=[]),
        _W3G3EPlayer(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game
def _w3g3e_put(game, seat, card):
    perm = _W3G3EPermanent(card=card)
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm
def _w3g3e_upkeep(game):
    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
def test_equipoise_repeats_its_process_once_per_printed_card_type(set_pool):
    """"…choose a land that player controls, then the chosen permanents phase
    out. **Repeat this process for artifacts and creatures.**"

    Not a loop: the parameters are printed, so the round is unrolled once per
    type with one word changed. Six instructions, three types, in the order the
    card names them.
    """
    program = _w3g3e_compile(set_pool("VIS")["Equipoise"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    steps = trigger.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_permanents", "phase_out_recorded_permanents",
    ] * 3, [step.kind for step in steps]
    assert [
        step.payload["filter"]["type_filter"]
        for step in steps if step.kind == "choose_permanents"
    ] == ["land", "artifact", "creature"]
def test_equipoise_phases_out_only_the_excess_of_each_type(set_pool):
    """"For each land target player controls **in excess of the number you
    control**" — a difference clamped at zero (CR 107.1b), counted per type.

    Two lands and two creatures more than its controller, and an artifact each,
    so four permanents phase out and the artifact stays.
    """
    game = _w3g3e_game()
    _w3g3e_put(game, 0, set_pool("VIS")["Equipoise"])
    _w3g3e_put(game, 0, _W3G3E_LEA["Forest"])
    _w3g3e_put(game, 0, _W3G3E_LEA["Black Lotus"])
    for name in ("Plains", "Island", "Swamp"):
        _w3g3e_put(game, 1, _W3G3E_LEA[name])
    for name in ("Grizzly Bears", "Hurloon Minotaur"):
        _w3g3e_put(game, 1, _W3G3E_LEA[name])
    _w3g3e_put(game, 1, _W3G3E_LEA["Mox Pearl"])

    _w3g3e_upkeep(game)

    gone = {perm.card.name for perm in game.players[1].phased_out}
    assert len(gone) == 4, game.log
    assert "Mox Pearl" not in gone, "the artifact counts are level"
    assert {perm.card.name for perm in game.players[1].battlefield} == {
        "Swamp", "Mox Pearl",
    }, game.log
    # The chooser's own board is untouched: the phrase names the target's.
    assert game.players[0].phased_out == []
def test_equipoise_does_nothing_when_the_boards_are_level(set_pool):
    """A player with no more of a type than you exceeds you by nothing, and a
    count of nothing is a step that asked for nothing rather than a prompt with
    no answer (CR 608.2h)."""
    game = _w3g3e_game()
    _w3g3e_put(game, 0, set_pool("VIS")["Equipoise"])
    _w3g3e_put(game, 0, _W3G3E_LEA["Forest"])
    _w3g3e_put(game, 1, _W3G3E_LEA["Plains"])

    _w3g3e_upkeep(game)

    assert game.players[1].phased_out == [], game.log
    assert len(game.players[1].battlefield) == 1
def test_equipoise_phases_each_permanent_out_once(set_pool):
    """Every round writes to the one "chosen this way" record, so the creature
    round's sentence names the land round's picks as well — and a phased-out
    permanent is treated as though it does not exist (CR 702.26b), which is
    exactly a permanent this step cannot phase out again. Read without that,
    the same land is pushed onto the phased-out pile three times and phases back
    in as three objects.
    """
    game = _w3g3e_game()
    _w3g3e_put(game, 0, set_pool("VIS")["Equipoise"])
    for name in ("Plains", "Island"):
        _w3g3e_put(game, 1, _W3G3E_LEA[name])

    _w3g3e_upkeep(game)

    names = [perm.card.name for perm in game.players[1].phased_out]
    assert sorted(names) == ["Island", "Plains"], names


# --- W4G1: Necromancy, the enchantment that becomes an Aura ---
from engine import Game as _W4G1Game, PlayerState as _W4G1Player  # noqa: E402
from engine.auras import (  # noqa: E402
    PUT_ONTO_BATTLEFIELD_BY as _W4G1_ORIGIN,
    aura_attach_refusal as _w4g1_attach_refusal,
)
from engine.card_loader import (  # noqa: E402
    load_cards as _w4g1_load, manifest_set_path as _w4g1_path,
)
from engine.grammar import compile_line as _w4g1_compile_line  # noqa: E402
from engine.models import Permanent as _W4G1Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w4g1_compile  # noqa: E402

_W4G1_LEA = {card.name: card for card in _w4g1_load(_w4g1_path("LEA"))}


def _w4g1_game():
    game = _W4G1Game(players=[
        _W4G1Player(name="P1"), _W4G1Player(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def _w4g1_necromancy(set_pool, graveyard_seat=1, creature="Grizzly Bears"):
    """Necromancy resolving its enters trigger with one creature card in a
    graveyard. Returns the game and the Necromancy permanent."""
    game = _w4g1_game()
    if creature is not None:
        game.players[graveyard_seat].graveyard.append(_W4G1_LEA[creature])
    necromancy = _W4G1Permanent(card=set_pool("VIS")["Necromancy"])
    game._put_permanent_onto_battlefield(0, necromancy, None)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()
    return game, necromancy


def test_necromancy_compiles_its_second_line_into_four_steps(set_pool):
    """The printed paragraph is one enters trigger whose effect is three
    sentences plus the delayed ability the last of them creates (CR 603.7).

    Written as the steps rather than as one fused kind, because every one of
    them is a step another card could print on its own: the type change, the
    reanimation, the attach, and the delay.
    """
    program = _w4g1_compile(set_pool("VIS")["Necromancy"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "enters_battlefield"
    steps = trigger.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "become_aura_with_enchant", "reanimate_creature",
        "attach_source_to_target", "create_delayed_trigger",
    ], [step.kind for step in steps]

    # The attach reads the permanent the reanimation made rather than a target:
    # the ability's target is a *card* in a graveyard.
    assert steps[2].payload["host_from"] == "reanimated_permanents"
    delayed = steps[3].payload
    assert delayed["binds_recorded"] == "reanimated_permanents"
    assert delayed["binds_target"] is False
    assert delayed["watches"] == "source"


def test_necromancy_reanimates_the_creature_and_attaches_itself_to_it(set_pool):
    """CR 701.3a: the attach is to the permanent the step in front of it put
    onto the battlefield, and to nothing else — CR 400.7 makes that permanent a
    different object from the card the trigger targeted."""
    game, necromancy = _w4g1_necromancy(set_pool)

    reanimated = next(
        perm for perm in game.players[0].battlefield
        if perm.card.name == "Grizzly Bears"
    )
    assert necromancy.metadata.get("attached_to") is reanimated, game.log
    assert necromancy in game.players[0].battlefield, game.log
    assert game.players[1].graveyard == [], "the card left its owner's graveyard"


def test_necromancy_becomes_an_aura_in_layer_4(set_pool):
    """CR 613.1d: the subtype is a type-changing effect, not a rewritten card —
    so every reader of "is this an Aura?" gets one answer, and the printed type
    line still says what was printed."""
    game, necromancy = _w4g1_necromancy(set_pool)

    assert necromancy.has_type("aura"), game.log
    assert "Aura" not in necromancy.card.type_line


def test_necromancy_sacrifices_the_creature_when_it_leaves(set_pool):
    """CR 603.7c: the delayed ability is about the permanent the resolution
    that created it made, and it is still about that permanent once the
    enchantment has gone. CR 701.21a: sacrificing is not destroying, and the
    card goes to its **owner's** graveyard (CR 400.3) rather than the
    controller's."""
    game, necromancy = _w4g1_necromancy(set_pool)

    game.remove_from_battlefield(necromancy)
    game._permanent_to_graveyard(game.players[0], necromancy)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    assert [perm.card.name for perm in game.players[0].battlefield] == [], game.log
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_necromancy_goes_to_the_graveyard_when_its_creature_leaves(set_pool):
    """CR 704.5m: an Aura attached to nothing is put into its owner's graveyard.
    It is the Aura subtype this permanent *gained* that makes the rule apply to
    it, and the delayed sacrifice behind it then finds the creature already
    gone — which is the ability doing as much as it can (CR 608.2b)."""
    game, necromancy = _w4g1_necromancy(set_pool)
    reanimated = next(
        perm for perm in game.players[0].battlefield
        if perm.card.name == "Grizzly Bears"
    )

    game.remove_from_battlefield(reanimated)
    game._permanent_to_graveyard(game.players[1], reanimated)
    game.check_state_based_actions()
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert necromancy not in game.players[0].battlefield, game.log
    assert "704.5m" in " ".join(game.log)


def test_necromancy_may_not_be_moved_onto_another_creature(set_pool):
    """"enchant creature **put onto the battlefield with Necromancy**" — the
    rider is the whole of what the granted clause adds, and CR 303.4j makes an
    Aura that can't legally enchant a permanent simply not move there
    (Enchantment Alteration). Left unread the clause would be enforced by
    nothing, which is the permissive answer an unknown enchant noun otherwise
    gets."""
    game, necromancy = _w4g1_necromancy(set_pool)
    reanimated = next(
        perm for perm in game.players[0].battlefield
        if perm.card.name == "Grizzly Bears"
    )
    other = _W4G1Permanent(card=_W4G1_LEA["Hill Giant"])
    game._put_permanent_onto_battlefield(0, other, None)

    assert _w4g1_attach_refusal(game, necromancy, reanimated) is None
    assert _w4g1_attach_refusal(game, necromancy, other) is not None
    assert reanimated.metadata.get(_W4G1_ORIGIN) == necromancy.permanent_id
    assert other.metadata.get(_W4G1_ORIGIN) is None


def test_necromancy_with_no_creature_card_anywhere_reanimates_nothing(set_pool):
    """Every step declines rather than reaching for something else: the
    reanimation records nothing, the attach has no host to read, and the
    delayed ability is about no object so none is created."""
    game, necromancy = _w4g1_necromancy(set_pool, creature=None)

    assert necromancy.metadata.get("attached_to") is None, game.log
    assert not game.delayed_triggers, game.delayed_triggers


def test_a_quoted_grant_this_engine_cannot_test_keeps_refusing():
    """The production reads exactly one enchant quality — a head noun plus
    CR 201.5's self-reference — because that is the one
    ``auras.enchant_card_refusal`` can test. Any other quoted clause keeps the
    quote guard's refusal rather than being admitted with its restriction
    dropped, which is the failure a permissive enchant matcher would make
    silent.
    """
    admitted = _w4g1_compile_line(
        'When this enchantment enters, it becomes an Aura with "enchant '
        'creature put onto the battlefield with Necromancy." Draw a card.',
        card_name="Necromancy",
    )
    assert admitted.parse_error is None, admitted.parse_error

    for line in (
        'When this enchantment enters, it becomes an Aura with "enchant '
        'creature you control." Draw a card.',
        'When this enchantment enters, it becomes an Aura with "enchant '
        'creature put onto the battlefield with Animate Dead." Draw a card.',
    ):
        refused = _w4g1_compile_line(line, card_name="Necromancy")
        assert refused.parse_error == "granted ability in quotes", (
            line, refused.parse_error,
        )
