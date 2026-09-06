"""Weatherlight artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: dies, enters and leaves triggers ---
from engine import Game, PlayerState
from engine.models import Permanent


def test_straw_golem_watches_the_spell_type_not_just_the_spell(
    set_pool, catalog_by_name
):
    """"**When** an opponent casts a creature spell, sacrifice this creature."

    The grammar could read this clause under "whenever" and not under "when" -
    its whole condition reader lived inside the ``whenever`` branch, and the
    ``when`` branch fell back to a table of fixed phrases that carries no noun
    phrase at all. CR 603.1 makes the two words one kind of ability, so the
    printed word was the only thing keeping the Golem off the board.

    Both halves are asserted: a Golem that sacrificed itself to any spell would
    pass the second one alone.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    golem = Permanent(card=set_pool("WTH")["Straw Golem"])
    game._put_permanent_onto_battlefield(0, golem, None)
    bob.hand[:] = [catalog_by_name["Lightning Bolt"], catalog_by_name["Grizzly Bears"]]

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    while game.stack and not game.waiting_prompt():
        game.resolve_top_of_stack()
    assert golem in alice.battlefield, "a Bolt is not a creature spell"

    game.cast_from_hand(1, "Grizzly Bears")
    while game.stack and not game.waiting_prompt():
        game.resolve_top_of_stack()

    assert alice.battlefield == []
    assert [card.name for card in alice.graveyard] == ["Straw Golem"]


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_furnace(set_pool, victim_graveyard):
    """Phyrexian Furnace on seat 0, with *victim_graveyard* in seat 1's pile.

    Given bottom-first, the order CR 404.1 produces: an arriving card goes on
    top, so the last element is the top card and the first is the bottom one.
    """
    furnace = Permanent(card=set_pool("WTH")["Phyrexian Furnace"])
    furnace.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[furnace],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", graveyard=list(victim_graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, furnace


def test_phyrexian_furnace_exiles_the_bottom_card_of_the_targeted_pile(set_pool):
    """"{T}: Exile the bottom card of target player's graveyard."

    The ability reported ``supported`` and compiled to **nothing** before this
    round — a hollow line, a parse-coverage finding and a picker finding at
    once. Both ends matter: the *bottom* of the pile (CR 404.1's oldest card,
    index 0) and the pile of the seat the ability targets.
    """
    game, _furnace = _w1g1_furnace(set_pool, [
        _w1g1_card("Oldest", "Creature — Bear"),
        _w1g1_card("Middle", "Land"),
        _w1g1_card("Newest", "Land"),
    ])
    them = game.players[1]
    result = game.activate_permanent_ability(
        0, "Phyrexian Furnace", target_player_index=1, ability_index=0
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert [card.name for card in them.exile] == ["Oldest"]
    assert [card.name for card in them.graveyard] == ["Middle", "Newest"]


def test_phyrexian_furnace_asks_for_a_player_and_not_for_a_card(set_pool):
    """The pile is chosen (CR 115.1) and the card in it is not: the order is
    public and fixed, so "the bottom card" has one answer once the seat is
    known. A card picker here would offer a choice the sentence does not make.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    program = compile_card_oracle(set_pool("WTH")["Phyrexian Furnace"])
    first = program.activated_abilities[0]
    assert first.instruction is not None, "the line is no longer hollow"
    assert derive_activation_spec(first) == {"kind": "player"}


def test_phyrexian_furnace_on_an_empty_pile_resolves_and_exiles_nothing(set_pool):
    """An effect is not a cost. CR 608.2 finishes what it can, so an empty
    graveyard exiles nothing and the ability still resolves — where the *cost*
    reading of the same phrase (Necratog) refuses instead, under CR 118.3."""
    game, _furnace = _w1g1_furnace(set_pool, [])
    result = game.activate_permanent_ability(
        0, "Phyrexian Furnace", target_player_index=1, ability_index=0
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert game.players[1].exile == []


# --- W1G4: animation and printed prohibitions ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt


def _w1g4a_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4a_game(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_bubble_matrix_shields_every_creature_and_no_player(set_pool):
    """"Prevent all damage that would be dealt to creatures." — CR 615.1.

    The recipient is a described *set of permanents* rather than a player, which
    is what makes it a different reader from Glacial Chasm's "dealt to you" one
    row up: a player has no characteristics to match. The sentence narrows by
    nothing, so it reaches both seats — and it says nothing about players, so a
    face still takes the damage. Both halves are asserted, because a shield that
    covered players too would pass the first.
    """
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([matrix, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 0
    assert _damage_dealt(game, game.players[1], 3) == 3


def test_inner_sanctum_shields_only_its_controllers_creatures(set_pool):
    """The same shield with "you control" on the noun phrase (CR 109.5).

    One row for both cards, so the narrowing has to be *honoured* rather than
    merely carried — dropped, Inner Sanctum is a Bubble Matrix, which is the
    direction a prevention fails silently in.
    """
    sanctum = Permanent(card=set_pool("WTH")["Inner Sanctum"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([sanctum, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 3


def test_the_matrix_stops_shielding_when_it_leaves(set_pool):
    """A static ability ends with its source (CR 611.2), and nothing is swept:
    the next event asks the board again."""
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    game = _w1g4a_game([matrix, mine], [])
    assert _damage_dealt(game, mine, 3) == 0
    game.remove_from_battlefield(matrix)
    assert _damage_dealt(game, mine, 3) == 3


def test_the_shield_is_claimed_by_the_reader_that_applies_it(set_pool):
    """The gate and the interceptor are one function, so a card cannot be
    admitted with its only line doing nothing — and the two singular
    self-references the source-narrowed readers own must keep refusing here."""
    from engine.prevention import prevent_all_to_matching

    assert compile_card_oracle(set_pool("WTH")["Bubble Matrix"]).supported
    assert compile_card_oracle(set_pool("WTH")["Inner Sanctum"]).supported
    for owned_elsewhere in (
        "Prevent all damage that would be dealt to this creature.",
        "Prevent all damage that would be dealt to enchanted creature.",
        "Prevent all damage that would be dealt to you.",
        "Prevent all damage that would be dealt to this creature by artifact sources.",
    ):
        assert prevent_all_to_matching(owned_elsewhere) is None, owned_elsewhere


def _w1g4a_board(perms) -> Game:
    game = _w1g4a_game(perms, [])
    game.start_turn(0)
    return game


def test_chimeric_sphere_animates_itself_and_stays_an_artifact(set_pool):
    """"Until end of turn, this artifact becomes a 2/1 Construct artifact
    creature with flying." — CR 205.1b and CR 613 layers 4, 6 and 7b.

    The clause-less form of the animation: no "in addition to its other types"
    and no "It's still a land", because the printed body already names the
    permanent's own card type. The production admits it on exactly that
    arithmetic, so the artifact type is asserted here rather than assumed —
    an animation that replaced the types would leave a permanent no Shatter
    could reach.
    """
    sphere = Permanent(card=set_pool("WTH")["Chimeric Sphere"])
    game = _w1g4a_board([sphere])
    assert not sphere.is_creature

    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert sphere.is_creature
    assert (sphere.effective_power, sphere.effective_toughness) == (2, 1)
    assert game._has_keyword(sphere, "flying")
    assert sphere.has_type("construct")
    assert sphere.has_type("artifact")


def test_chimeric_spheres_second_body_takes_the_flying_back_off(set_pool):
    """"…becomes a 3/2 Construct artifact creature **and loses flying**."

    The conjunct is the whole point of the card's second ability rather than a
    restatement of the default: the *first* ability gave the Sphere flying, and
    CR 613 layer 6 settles the two by timestamp. Both abilities are activated in
    order here, because the removal is only observable against the grant.
    """
    sphere = Permanent(card=set_pool("WTH")["Chimeric Sphere"])
    game = _w1g4a_board([sphere])
    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert game._has_keyword(sphere, "flying")

    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=1
    ).supported
    game._recompute_continuous_effects()
    assert (sphere.effective_power, sphere.effective_toughness) == (3, 2)
    assert not game._has_keyword(sphere, "flying")
    assert sphere.has_type("artifact")


def test_xanthic_statue_animates_with_its_printed_keyword(set_pool):
    """The same production one card over, with a different body — which is what
    makes it a production rather than two entries."""
    statue = Permanent(card=set_pool("WTH")["Xanthic Statue"])
    game = _w1g4a_board([statue])
    assert not statue.is_creature

    assert game.activate_permanent_ability(
        0, "Xanthic Statue", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert (statue.effective_power, statue.effective_toughness) == (8, 8)
    assert game._has_keyword(statue, "trample")
    assert statue.has_type("golem")
    assert statue.has_type("artifact")


def test_thran_forge_pumps_and_adds_the_type_to_one_target(set_pool):
    """"…target nonartifact creature gets +1/+0 **and becomes an artifact in
    addition to its other types**." — CR 205.1b's *addition*, joined to a pump.

    Two effect families in one sentence over one printed noun phrase, which is
    why the join lives in `grammar/conjuncts.py`: `effects/characteristics.py`
    may not import `effects/types.py`.
    """
    forge = Permanent(card=set_pool("WTH")["Thran Forge"])
    victim = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    game = _w1g4a_board([forge, victim])

    assert game.activate_permanent_ability(
        0, "Thran Forge", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    ).supported
    game._recompute_continuous_effects()
    assert (victim.effective_power, victim.effective_toughness) == (3, 2)
    assert victim.has_type("artifact")
    # "In addition to its other types" — the creature type survives, which is
    # the difference between this clause and the animation two tests up.
    assert victim.is_creature


def test_thran_forge_refuses_an_artifact_creature(set_pool):
    """The printed "nonartifact" is enforced, not merely carried.

    The activation is refused with nothing spent (CR 602.2b), which is the half
    of the narrowing the engine answers. The *picker* is the other half and it
    is unnarrowed today — `derive_activation_spec` answers a bare
    `{"kind": "creature"}` for every activated pump in the pool, this card
    included — so a client would offer the target and the engine would decline
    it. That is a pool-wide gap rather than this card's, and this test pins the
    half that is enforced so a later round can tighten the other.
    """
    artifact_creature = CardDefinition(
        name="Clockwork Test", mana_cost="", cmc=0.0,
        type_line="Artifact Creature - Test", oracle_text="", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Clockwork Test", "type_line": "Artifact Creature - Test",
             "power": "2", "toughness": "2"},
    )
    forge = Permanent(card=set_pool("WTH")["Thran Forge"])
    victim = Permanent(card=artifact_creature)
    game = _w1g4a_board([forge, victim])

    result = game.activate_permanent_ability(
        0, "Thran Forge", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    assert not result.supported
    assert (victim.effective_power, victim.effective_toughness) == (2, 2)


def test_an_animation_that_drops_a_type_still_refuses(set_pool):
    """The refusal test for the clause-less form, written before the gate is
    trusted.

    "Target land becomes a 4/4 creature until end of turn" names no land in its
    body, so replacement and addition are *not* the same permanent — the land
    would stop being a land. The engine has no CR 205.1b type removal, so the
    line has to keep refusing rather than be admitted under an adding record.
    """
    from engine.grammar import compile_line

    assert compile_line(
        "Until end of turn, this artifact becomes a 2/1 Construct artifact "
        "creature with flying."
    ).instructions
    for dropped in (
        "Target land becomes a 4/4 creature until end of turn.",
        "This land becomes a 2/2 Assembly-Worker artifact creature until end of turn.",
    ):
        assert not compile_line(dropped).instructions, dropped


# --- W1G5: each player, in parallel ---
from engine import Game, PlayerState
from engine.models import Permanent as _W1G5aPermanent
from engine.oracle import compile_card_oracle as _w1g5a_compile


def _w1g5a_well(set_pool):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[], library=[set_pool("LEA")["Island"]] * 10),
        PlayerState(name="P2", battlefield=[], library=[set_pool("LEA")["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    well = _W1G5aPermanent(card=set_pool("WTH")["Well of Knowledge"])
    game.players[0].battlefield.append(well)
    game._sync_control()
    return game


def _w1g5a_try(game, seat, step, active):
    """Activate the Well from *seat* in *step* of *active*'s turn."""
    game.current_step = step
    game.active_player_index = active
    before = len(game.players[seat].hand)
    result = game._activate_onto_stack(
        seat, "Well of Knowledge", source_controller_index=0,
    )
    game.resolve_stack()
    return result, len(game.players[seat].hand) - before


def test_well_of_knowledge_is_open_to_everyone_on_their_own_draw_step(set_pool):
    """"{2}: Draw a card. Any player may activate this ability but only during
    their draw step."

    Two claims in one sentence and `engine/activation_permissions.py` already
    carried the first: "any player may activate this ability" is a row there,
    read by the reachability check, the API and the client, and
    `permission_clause_readable` already split the "but only …" tail off to
    `activation_restrictions.py`. What was missing was the tail's row — so the
    card was unsupported, which is the safe direction: an unenforced timing
    clause is an ability that works more often than the card allows.

    "Their" is the *activating* seat. `_activate_onto_stack` takes its
    ``controller_index`` as the activator (CR 602.1a's controller of the
    ability) and names whose battlefield holds the permanent separately, so the
    seat comparison in the predicate is already the right one.
    """
    program = _w1g5a_compile(set_pool("WTH")["Well of Knowledge"])
    assert program.supported, program.reason

    game = _w1g5a_well(set_pool)
    # Its own controller, outside a draw step.
    refused, drew = _w1g5a_try(game, 0, "main1", 0)
    assert not refused.supported and drew == 0, refused.details
    # Its own controller, in their draw step.
    allowed, drew = _w1g5a_try(game, 0, "draw", 0)
    assert allowed.supported and drew == 1, allowed.details
    # An opponent, in *somebody else's* draw step: reachable, but not now.
    refused, drew = _w1g5a_try(game, 1, "draw", 0)
    assert not refused.supported and drew == 0, refused.details
    # The same opponent, in their own draw step.
    allowed, drew = _w1g5a_try(game, 1, "draw", 1)
    assert allowed.supported and drew == 1, allowed.details
    # And the controller is shut out of the opponent's draw step in turn — the
    # permission widens who may reach the ability, it does not widen when.
    refused, drew = _w1g5a_try(game, 0, "draw", 1)
    assert not refused.supported and drew == 0, refused.details
