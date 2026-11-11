"""Darksteel artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# The one-offs that are artifacts: Auriok Siege Sled's requirement on an
# "artifact creature", and the rest below as they land.
from engine import Game as _W1G9Game
from engine import ai_declarations as _w1g9_ai_declarations
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile

from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=(), library=None, opponent_library=None):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) if library is not None else [lea["Plains"]] * 8,
    )
    bob = _W1G9PlayerState(
        name="Bob",
        library=list(opponent_library) if opponent_library is not None else [lea["Swamp"]] * 8,
    )
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g9_put(game, seat, card, *, sick=False):
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g9_slot(game, seat, permanent):
    return game.players[seat].battlefield.index(permanent)


def _w1g9_attack_with(game, seat, attackers):
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [_w1g9_slot(game, seat, each) for each in attackers]
    ok, why = game.declare_attackers(seat, slots, defending_player_index=1 - seat)
    assert ok, why


def test_w1g9_auriok_siege_sled_compels_the_artifact_creature_it_names(set_pool):
    """"{1}: Target artifact creature blocks this creature this turn if able."
    CR 509.1c: with the requirement on Obsianus Golem, a declaration in which
    the Golem does not block the Sled obeys fewer requirements than it could,
    and is illegal — no block, and the Bears blocking alone, both refused."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sled = dst["Auriok Siege Sled"]
    assert _w1g9_compile(sled).supported
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, sled)
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    bears = _w1g9_put(game, 1, lea["Grizzly Bears"])
    _w1g9_attack_with(game, 0, [attacker])

    refused = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported, "Grizzly Bears is not an artifact creature"
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    sled_slot = _w1g9_slot(game, 0, attacker)
    ai_blocks = _w1g9_ai_declarations.choose_combat_blockers(game, 1)
    assert ai_blocks.get(_w1g9_slot(game, 1, golem)) == sled_slot, ai_blocks
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, bears): sled_slot})[0] is False
    ok, why = game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})
    assert ok, why
    _w1g9_drive_combat(game)
    assert bob.life == 20
    assert game.is_on_battlefield(golem) and game.is_on_battlefield(attacker)


def test_w1g9_auriok_siege_sled_denies_the_artifact_creature_a_block(set_pool):
    """"{1}: Target artifact creature can't block this creature this turn."
    The Golem may not block the Sled; the Sled's damage reaches Bob."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, dst["Auriok Siege Sled"])
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    _w1g9_attack_with(game, 0, [attacker])
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=1, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    sled_slot = _w1g9_slot(game, 0, attacker)
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})[0] is False
    assert game.declare_blockers(1, {})[0]
    _w1g9_drive_combat(game)
    assert bob.life == 17



def _w1g9_names(player):
    return [permanent.card.name for permanent in player.battlefield]


def test_w1g9_genesis_chamber_gives_each_entering_creatures_controller_a_myr(set_pool):
    """"Whenever a nontoken creature enters, if this artifact is untapped, that
    creature's controller creates a 1/1 colorless Myr artifact creature token."
    Alice's Bears give Alice a Myr and Bob's Zombies give Bob one; the Myr
    entering is a token and sets nothing off; tapped, the Chamber does nothing
    (CR 603.4)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    chamber = _w1g9_put(game, 0, dst["Genesis Chamber"])
    alice.hand.extend([lea["Grizzly Bears"], lea["Llanowar Elves"]])
    bob.hand.append(lea["Scathe Zombies"])

    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Genesis Chamber", "Grizzly Bears", "Myr Token"]
    myr = alice.battlefield[2]
    assert (myr.effective_power, myr.effective_toughness) == (1, 1)
    assert myr.has_type("artifact") and myr.has_type("creature")

    game.active_player_index = 1
    assert game.cast_from_hand(1, "Scathe Zombies").supported
    _w1g9_settle(game)
    assert _w1g9_names(bob) == ["Scathe Zombies", "Myr Token"]
    assert _w1g9_names(alice).count("Myr Token") == 1

    chamber.tapped = True
    game.active_player_index = 0
    assert game.cast_from_hand(0, "Llanowar Elves").supported
    _w1g9_settle(game)
    assert _w1g9_names(alice).count("Myr Token") == 1


def test_w1g9_genesis_chamber_tapped_before_resolution_makes_nothing(set_pool):
    """The intervening "if" is asked again on resolution (CR 603.4): the
    Chamber was untapped as the Bears entered and is tapped in response, so the
    trigger resolves and creates nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    chamber = _w1g9_put(game, 0, dst["Genesis Chamber"])
    alice.hand.append(lea["Grizzly Bears"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Genesis Chamber"], game.stack
    chamber.tapped = True
    _w1g9_settle(game)
    assert "Myr Token" not in _w1g9_names(alice)
    assert any("its condition is no longer true" in line for line in game.log)



def test_w1g9_sundering_titan_destroys_a_land_of_each_basic_type_as_it_enters(set_pool):
    """"When this creature enters or leaves the battlefield, choose a land of
    each basic land type, then destroy those lands." A headless controller
    chooses the other seat's lands first and its own only where no other land
    has the type (the ruling, 2020-08-07: "If the only land of a certain type
    is one you control, you must choose it"); Bob's Volcanic Island answers
    Island and Mountain at once ("If a land has more than one basic land type,
    it can be chosen more than once"); no Forest anywhere, so none is chosen."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    alice.hand.append(dst["Sundering Titan"])
    for name in ("Plains", "Swamp", "Mountain"):
        _w1g9_put(game, 0, lea[name])
    _w1g9_put(game, 1, lea["Plains"])
    _w1g9_put(game, 1, set_pool("LEB")["Volcanic Island"])
    assert game.cast_from_hand(0, "Sundering Titan").supported
    _w1g9_settle(game)
    # Bob's Plains, his Volcanic Island for Island and Mountain, Alice's Swamp.
    assert _w1g9_names(alice) == ["Plains", "Mountain", "Sundering Titan"]
    assert _w1g9_names(bob) == []
    assert {"Plains", "Volcanic Island"} == {c.name for c in bob.graveyard}


def test_w1g9_sundering_titan_destroys_again_as_it_leaves(set_pool):
    """The departure half of the same ability (CR 603.1): sacrificed, the
    Titan's controller chooses again and every chosen land is destroyed."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    titan = _w1g9_put(game, 0, dst["Sundering Titan"])
    _w1g9_settle(game)  # its entry finds no land to destroy
    _w1g9_put(game, 0, lea["Island"])
    _w1g9_put(game, 1, lea["Forest"])
    _w1g9_put(game, 1, lea["Forest"])
    game.sacrifice_permanent(titan)
    _w1g9_settle(game)
    assert _w1g9_names(alice) == []
    assert _w1g9_names(bob) == ["Forest"], "one land per type: one Forest of two"


def test_w1g9_sundering_titan_asks_an_interactive_controller_across_both_boards(set_pool):
    """An interactive controller is asked; the candidates are every
    battlefield's lands, and the answer must leave no type it could answer
    unanswered — here Alice destroys her own Plains and spares Bob's."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    game.interactive_seats = {0}
    titan = _w1g9_put(game, 0, dst["Sundering Titan"])
    _w1g9_settle(game)  # its entry finds no land to destroy
    mine = _w1g9_put(game, 0, lea["Plains"])
    theirs = _w1g9_put(game, 1, lea["Plains"])
    swamp = _w1g9_put(game, 1, lea["Swamp"])
    game.sacrifice_permanent(titan)
    owed = _w1g9_settle(game, defaults=False)
    assert owed is not None and owed.kind == "keep_permanents", owed
    assert owed.data["fate"] == "destroy_chosen"
    assert {id(p) for p in game.keep_candidates_of(owed)} == {id(mine), id(theirs), id(swamp)}
    assert not game.confirm_keep_permanents(0, [mine.permanent_id]), "a Swamp is owed"
    assert game.confirm_keep_permanents(0, [mine.permanent_id, swamp.permanent_id])
    _w1g9_settle(game)
    assert _w1g9_names(alice) == [] and _w1g9_names(bob) == ["Plains"]



def test_w1g9_gemini_engine_makes_an_attacking_twin_sacrificed_at_end_of_combat(set_pool):
    """"Whenever this creature attacks, create a colorless Construct artifact
    creature token named Twin that's attacking. Its power is equal to this
    creature's power and its toughness is equal to this creature's toughness.
    Sacrifice the token at end of combat." The Twin "enters as an untapped
    attacking creature" (2004-12-01), deals its 3 beside the Engine's 3, and
    is gone when combat ends (CR 511.2)."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    engine = _w1g9_put(game, 0, dst["Gemini Engine"])
    _w1g9_attack_with(game, 0, [engine])
    _w1g9_settle(game)
    twin = next(p for p in alice.battlefield if p.card.name == "Twin")
    assert twin.metadata.get("is_token") and twin.attacking and not twin.tapped
    assert (twin.effective_power, twin.effective_toughness) == (3, 4)
    assert twin.has_type("artifact") and twin.has_type("creature") and twin.has_type("Construct")
    assert twin.effective_colors in ((), [], set(), frozenset())
    _w1g9_drive_combat(game)
    assert bob.life == 14
    assert _w1g9_names(alice) == ["Gemini Engine"]


def test_w1g9_gemini_engines_twin_copies_the_engines_pt_once(set_pool):
    """The rulings (2004-12-01): with a Glorious Anthem the Engine is 4/5, the
    Twin "starts as a 4/5, and then the Anthem gives it +1/+1, making the Twin
    a 5/6"; and once created, its P/T "won't change if Gemini Engine's power and
    toughness change" — a Giant Growth on the Engine leaves the Twin alone."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    _w1g9_put(game, 0, set_pool("7ED")["Glorious Anthem"])
    engine = _w1g9_put(game, 0, dst["Gemini Engine"])
    alice.hand.append(set_pool("2ED")["Giant Growth"])
    _w1g9_attack_with(game, 0, [engine])
    _w1g9_settle(game)
    twin = next(p for p in alice.battlefield if p.card.name == "Twin")
    assert (engine.effective_power, engine.effective_toughness) == (4, 5)
    assert (twin.effective_power, twin.effective_toughness) == (5, 6)
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[engine.permanent_id]).supported
    _w1g9_settle(game)
    assert engine.effective_power == 7
    assert (twin.effective_power, twin.effective_toughness) == (5, 6)



def _w1g9_dissector_table(set_pool, library_names):
    lea = set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, opponent_library=[lea[name] for name in library_names],
    )
    dissector = _w1g9_put(game, 0, set_pool("DST")["Thought Dissector"])
    return game, alice, bob, dissector


def test_w1g9_thought_dissector_takes_the_first_artifact_within_x_cards(set_pool):
    """"{X}, {T}: Target opponent reveals cards from the top of their library
    until an artifact card or X cards are revealed, whichever comes first. If
    an artifact card is revealed this way, put it onto the battlefield under
    your control and sacrifice this artifact. Put the rest of the revealed
    cards into that player's graveyard." X=3: two creatures, then Sol Ring —
    the Ring is Alice's to control and Bob's to own, the creatures are milled,
    and the Dissector is sacrificed."""
    game, alice, bob, dissector = _w1g9_dissector_table(
        set_pool, ["Grizzly Bears", "Llanowar Elves", "Sol Ring", "Forest"],
    )
    from engine.targeting import derive_activation_spec as _spec

    ability = _w1g9_compile(dissector.card).activated_abilities[0]
    assert _spec(ability) == {"kind": "player", "opponents_only": True}
    assert not game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=0, x_value=3,
    ).supported, "an opponent only"
    result = game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=3,
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Sol Ring"]
    assert game.owner_index_of(alice.battlefield[0]) == 1
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears", "Llanowar Elves"]
    assert [c.name for c in bob.library] == ["Forest"]
    assert [c.name for c in alice.graveyard] == ["Thought Dissector"]


def test_w1g9_thought_dissector_stops_after_x_cards_with_no_artifact(set_pool):
    """X=2 runs out first: both creatures go to Bob's graveyard, the Sol Ring
    beneath them stays on top of his library, and nothing is sacrificed."""
    game, alice, bob, dissector = _w1g9_dissector_table(
        set_pool, ["Grizzly Bears", "Llanowar Elves", "Sol Ring", "Forest"],
    )
    assert game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=2,
    ).supported
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Thought Dissector"]
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears", "Llanowar Elves"]
    assert [c.name for c in bob.library] == ["Sol Ring", "Forest"]


def test_w1g9_thought_dissector_gone_in_response_still_delivers_the_artifact(set_pool):
    """The ruling (2004-12-01): "You put the artifact card onto the battlefield
    even if Thought Dissector has already left the battlefield and you can't
    sacrifice it." Sacrificed with the ability on the stack, the Dissector is
    gone, and the Ring still arrives."""
    game, alice, bob, dissector = _w1g9_dissector_table(set_pool, ["Sol Ring"])
    assert game.queue_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=1,
    ).supported
    assert game.stack, "the ability waits on the stack"
    game.sacrifice_permanent(dissector)
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Sol Ring"]
    assert [c.name for c in alice.graveyard] == ["Thought Dissector"]



def test_w1g9_eater_of_days_skips_its_controllers_next_two_turns(set_pool):
    """"When this creature enters, you skip your next two turns." CR 614.10a:
    two "next" skips, each spent on one turn — after Alice's turn the next
    three turns are Bob's, and the fourth is hers."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    alice.hand.append(dst["Eater of Days"])
    assert game.cast_from_hand(0, "Eater of Days").supported
    _w1g9_settle(game)
    assert "Eater of Days" in _w1g9_names(alice)
    assert game.skip_turn_counts.get(0) == 2
    assert any("will skip their next 2 turns" in line for line in game.log)
    assert [game.start_next_turn() for _ in range(4)] == [1, 1, 1, 0], game.log[-12:]
    assert game.skip_turn_counts.get(0, 0) == 0


def test_w1g9_eater_of_days_put_onto_the_battlefield_skips_too(set_pool):
    """The trigger is the entry's, however it entered (CR 603.6a): put onto the
    battlefield by an effect, it still costs two turns; a second Eater stacks
    two more (CR 614.10a: each skip waits for its own turn)."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    _w1g9_put(game, 0, dst["Eater of Days"])
    _w1g9_settle(game)
    _w1g9_put(game, 0, dst["Eater of Days"])
    _w1g9_settle(game)
    assert game.skip_turn_counts.get(0) == 4

# ==== end W1G9 ======================================================
