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

# --- G1: the return-to-hand family ---
#
# Imports at the top of this block, so a merge that appends another group's
# block below cannot lose them (SET_PLAYBOOK.md).


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


# --- W1G2: phasing as an effect, and land types ---



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
