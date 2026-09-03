"""Per-card tests for Mirage's creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards. Cutting this file when it outgrows the size guard means
cutting at a section boundary, which keeps every section whole and keeps a test
findable from its round.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 1: flanking (CR 702.25) ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _r1_vanilla(name: str, power: int, toughness: int) -> CardDefinition:
    """A creature with no abilities at all, for the far side of a block.

    Invented rather than pulled from the pool because flanking's whole question
    is whether the *blocker* has flanking, and a pool creature would bring
    whatever else it prints along with the answer.
    """
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _r1_attack(attacker: Permanent, blockers: list[Permanent]) -> Game:
    """*attacker* on seat 0 attacking seat 1, stopped in declare blockers."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=list(blockers)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare blockers
    return game


def test_flanking_creatures_all_compile_supported(set_pool):
    """The ten cards the keyword buys, as one assertion.

    CR 702.25a *defines* flanking rather than describing it, so the keyword line
    is rewritten into the trigger it already is (`engine/flanking.py`) — the
    shape rampage and cumulative upkeep already use. Nine of these ten refused
    with **every line grammar-clean**: the block was the reminder-text line
    gate, which is why the refusal rollup's site column could not see this
    bucket at all.
    """
    pool = set_pool("MIR")
    flankers = [
        "Femeref Knight", "Mtenda Herder", "Sidar Jabari", "Zhalfirin Commander",
        "Zhalfirin Knight", "Cadaverous Knight", "Burning Shield Askari",
        "Searing Spear Askari", "Jolrael's Centaur",
    ]
    for name in flankers:
        program = compile_card_oracle(pool[name])
        assert program.supported, f"{name}: {program.reason}"
        kinds = [
            trig.instruction.kind
            for trig in program.triggered_abilities
            if trig.instruction is not None
        ]
        assert "pump_block_pair" in kinds, name


def test_zhalfirin_knight_shrinks_the_creature_that_blocks_it(set_pool):
    """The behaviour, given a game.

    The -1/-1 arrives *on resolution*, not as blockers are declared — which is
    the difference from what this engine used to do with the word, and the
    reason the ability can be responded to at all.
    """
    knight = Permanent(card=set_pool("MIR")["Zhalfirin Knight"])
    footman = Permanent(card=_r1_vanilla("Footman", 3, 3))
    game = _r1_attack(knight, [footman])

    assert game.declare_blockers(1, {0: 0})[0]
    assert len(game.stack) == 1
    assert (footman.effective_power, footman.effective_toughness) == (3, 3)

    game.resolve_stack()
    game._settle()

    assert (footman.effective_power, footman.effective_toughness) == (2, 2)


def test_a_flanking_blocker_is_exempt(set_pool):
    """"…blocked by a creature **without flanking**" is a printed noun phrase,
    so it rides the ordinary ``blocker_filter`` payload and is answered through
    CR 613 layer 6 — the same reader every other filtered block trigger uses."""
    pool = set_pool("MIR")
    knight = Permanent(card=pool["Zhalfirin Knight"])
    herder = Permanent(card=pool["Mtenda Herder"])   # 1/1 with flanking
    game = _r1_attack(knight, [herder])

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert (herder.effective_power, herder.effective_toughness) == (1, 1)
    assert herder in game.players[1].battlefield


def test_a_double_block_triggers_once_per_blocker(set_pool):
    """CR 509.3d: the printed narrowing is what makes this per-creature. Both
    blockers shrink, and each ability is its own object on the stack."""
    knight = Permanent(card=set_pool("MIR")["Zhalfirin Knight"])
    first = Permanent(card=_r1_vanilla("Footman", 3, 3))
    second = Permanent(card=_r1_vanilla("Squire", 3, 3))
    game = _r1_attack(knight, [first, second])

    assert game.declare_blockers(1, {0: 0, 1: 0})[0]
    assert len(game.stack) == 2
    game.resolve_stack()
    game._settle()

    assert (first.effective_power, first.effective_toughness) == (2, 2)
    assert (second.effective_power, second.effective_toughness) == (2, 2)


def test_flanking_kills_an_x_1_blocker(set_pool):
    """CR 704.5f, reached through the ordinary state-based sweep after the
    ability resolves rather than by a ``check_state_based_actions`` call the
    declaration step used to make itself."""
    knight = Permanent(card=set_pool("MIR")["Zhalfirin Knight"])
    weed = Permanent(card=_r1_vanilla("Weed", 1, 1))
    game = _r1_attack(knight, [weed])

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert weed not in game.players[1].battlefield


# --- Round 2: phasing (CR 702.26) ---

def _r2_game(set_pool, *names, hand=(), extra_battlefield=()):
    """One seat's board built from Mirage cards, with a real library.

    Non-interactive, so a prompt an ability arms is visible on
    ``game.pending_choices`` rather than answered for us — which is how the
    discard half of Teferi's Imp is checked below.
    """
    pool = set_pool("MIR")
    island = pool["Island"]
    mine = [Permanent(card=pool[name]) for name in names]
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=mine + list(extra_battlefield),
            hand=[pool[name] for name in hand], library=[island] * 12,
        ),
        PlayerState(name="P2", library=[island] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, mine


def test_sandbar_crocodile_alternates_on_its_own_untap_steps(set_pool):
    """The keyword alone, on the card whose whole text is the keyword.

    CR 702.26a's event runs at *each player's* untap step over the permanents
    **that player** controls, so the opponent's turn leaves it alone.
    """
    game, (croc,) = _r2_game(set_pool, "Sandbar Crocodile")

    game.start_turn(0)
    assert not game.is_on_battlefield(croc)
    game.start_next_turn()
    assert not game.is_on_battlefield(croc)
    game.start_next_turn()
    assert game.is_on_battlefield(croc)


def test_teferis_imp_discards_when_it_phases_out(set_pool):
    """"Whenever this creature phases out, discard a card."

    Announced *before* the permanent leaves the battlefield, which is the whole
    of why this works: the trigger scan reads battlefields, and a permanent that
    has already phased out is on none — so an announcement after the move would
    have watched the Imp's own departure and missed it.
    """
    game, (imp,) = _r2_game(set_pool, "Teferi's Imp", hand=["Island"] * 3)

    game.start_turn(0)
    game.resolve_stack()

    assert not game.is_on_battlefield(imp)
    assert [choice.kind for choice in game.pending_choices] == ["discard"]


def test_teferis_imp_draws_when_it_phases_in(set_pool):
    """The mirror trigger, announced from the other seam."""
    game, (imp,) = _r2_game(set_pool, "Teferi's Imp")

    game.start_turn(0)      # phases out
    game.resolve_stack()
    game.pending_choices.clear()
    game.start_next_turn()  # the opponent's; nothing of ours phases
    before = len(game.players[0].hand)
    game.start_next_turn()  # ours again: phases in, then the draw step
    game.resolve_stack()

    assert game.is_on_battlefield(imp)
    assert len(game.players[0].hand) == before + 2, "the trigger's card and the draw step's"


def test_taniwha_phases_out_only_its_controllers_lands(set_pool):
    """"At the beginning of your upkeep, all lands you control phase out."

    A sweep over a printed noun phrase, so "you control" is payload asked
    through the same matcher the picker would use. Read on the turn Taniwha
    itself phases *in*: on the alternate turn Taniwha is phased out, its upkeep
    trigger does not exist to fire, and the lands stay — which is the card, not
    a gap.
    """
    forest = set_pool("MIR")["Forest"]
    mine = [Permanent(card=forest) for _ in range(2)]
    theirs = [Permanent(card=forest) for _ in range(2)]
    game, (taniwha,) = _r2_game(set_pool, "Taniwha", extra_battlefield=mine)
    game.players[1].battlefield.extend(theirs)

    game.start_turn(0)      # Taniwha phases out; no upkeep trigger
    game.resolve_stack()
    assert all(game.is_on_battlefield(land) for land in mine)

    game.start_next_turn()
    game.start_next_turn()  # ours again: phases in, then the upkeep fires
    game.resolve_stack()

    assert not any(game.is_on_battlefield(land) for land in mine)
    assert all(game.is_on_battlefield(land) for land in theirs)


def test_crystal_golem_phases_itself_out_at_its_end_step(set_pool):
    """"At the beginning of your end step, this creature phases out."

    The source-subject shape, which is the commonest printed phase-out in the
    set and the one the target branch could not read: the sentence names no
    target, so there was nothing to describe.
    """
    game, (golem,) = _r2_game(set_pool, "Crystal Golem")

    game.start_turn(0)
    game.resolve_stack()
    assert game.is_on_battlefield(golem), "no phasing keyword, so the untap step leaves it"

    game.resolve_end_step(0)
    game.resolve_stack()

    assert not game.is_on_battlefield(golem)


# --- Round 6: "gains X and loses Y until end of turn" (CR 613 layer 6) ---

def _r6_activate(set_pool, name: str):
    """*name* on seat 0, with its ability activated and resolved."""
    pool = set_pool("MIR")
    creature = Permanent(card=pool[name])
    creature.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[creature], library=[pool["Island"]] * 5),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.activate_permanent_ability(0, name, permanent_index=0)
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    return game, creature


def test_canopy_dragon_gains_one_keyword_and_loses_another(set_pool):
    """"{1}{G}: This creature gains flying and loses trample until end of turn."

    One printed sentence over both halves of layer 6, and the trailing duration
    governs both. Its own parse arm rather than a verb alternative inside the
    grant, because a grant and a removal are opposite contributions to one layer
    (CR 613.4/613.9) — folded together, "loses trample" comes back as a grant of
    it.
    """
    game, dragon = _r6_activate(set_pool, "Canopy Dragon")

    assert game._has_keyword(dragon, "flying")
    assert not game._has_keyword(dragon, "trample")


def test_leering_gargoyle_pumps_and_loses_a_keyword(set_pool):
    """"{T}: This creature gets -2/+2 and loses flying until end of turn." The
    same conjunction with a pump on the left."""
    game, gargoyle = _r6_activate(set_pool, "Leering Gargoyle")

    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (0, 4)
    assert not game._has_keyword(gargoyle, "flying")


def test_the_keyword_comes_back_at_cleanup(set_pool):
    """"Until end of turn" is a real layer-6 record with an expiry, not an edit
    to the printed card — so the cleanup sweep gives the word back."""
    game, gargoyle = _r6_activate(set_pool, "Leering Gargoyle")
    assert not game._has_keyword(gargoyle, "flying")

    game.resolve_cleanup_step(0)

    assert game._has_keyword(gargoyle, "flying")


# --- Round 7: two conditions the tables were built for and never fed ---

from engine.handlers._common import permanent_effective_colors


def test_spirit_of_the_night_has_first_strike_only_while_attacking(set_pool):
    """"…has first strike as long as it's attacking."

    `conditional_static_holds` has answered ``is_state`` since Snow Devil, but
    that payload only ever arrived from the grammar's *attached* path — an
    Aura's "enchanted creature has first strike as long as it's blocking". The
    same-subject spelling refuses in the grammar with the reason "derived by
    engine/static_bonuses.py", and that table had no row for it: an evaluator
    built at one end and connected at neither.
    """
    pool = set_pool("MIR")
    spirit = Permanent(card=pool["Spirit of the Night"])
    blocker = Permanent(card=_r1_vanilla("Guard", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[spirit]),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    game.enforce_mana_costs = False

    assert not game._has_keyword(spirit, "first strike")

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game._recompute_continuous_effects()

    assert game._has_keyword(spirit, "first strike")


def test_raging_spirit_becomes_colorless_until_end_of_turn(set_pool):
    """"{2}: This creature becomes colorless until end of turn."

    CR 105.2c makes colourless the *absence* of colour, so it cannot ride the
    colour-word table — its values are mana symbols — and the layer-5 channel
    takes the empty set rather than a sixth colour. Which is why the channel's
    reader now tests for None instead of truthiness: an object with no colours
    is a real answer.
    """
    pool = set_pool("MIR")
    spirit = Permanent(card=pool["Raging Spirit"])
    spirit.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[spirit], library=[pool["Island"]] * 5),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert permanent_effective_colors(spirit) == {"R"}

    result = game.activate_permanent_ability(0, "Raging Spirit", permanent_index=0)
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert permanent_effective_colors(spirit) == set()

    game.resolve_cleanup_step(0)
    assert permanent_effective_colors(spirit) == {"R"}


# --- Round 8: a ceiling on how many creatures may block (CR 509.1b) ---

def _r8_attack(set_pool, name: str, blockers: int):
    attacker = Permanent(card=set_pool("MIR")[name])
    blocking = [Permanent(card=_r1_vanilla(f"Guard {i}", 2, 2)) for i in range(blockers)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=blocking),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    return game


def test_stalking_tiger_may_be_blocked_by_one(set_pool):
    """"This creature can't be blocked by more than one creature." The legal
    declaration still is one."""
    game = _r8_attack(set_pool, "Stalking Tiger", 1)

    assert game.declare_blockers(1, {0: 0})[0]


def test_stalking_tiger_refuses_a_double_block(set_pool):
    """The ceiling to the menace floor beside it, and the same reading of
    CR 509.1b/509.1c: a restriction on the finished declaration rather than on
    any single blocker pair, so it is checked over the whole assignment.

    The pattern also has to sit **above** the general "can't be blocked by
    <noun>" row, which reads any bare noun phrase and would have consumed "more
    than one creature" as one — producing a filter matching nothing, so the
    restriction would go inert and the Tiger would be blockable by anything.
    """
    game = _r8_attack(set_pool, "Stalking Tiger", 2)

    ok, message = game.declare_blockers(1, {0: 0, 1: 0})

    assert not ok
    assert "more than 1" in message


# --- Round 10: the block relation, spelled out (CR 509.1a) ---

def test_wall_of_corpses_destroys_what_it_is_blocking(set_pool):
    """"{B}, Sacrifice this creature: Destroy target creature **this creature is
    blocking**."

    The same relation Goblin Snowman prints as "target creature **it's
    blocking**", written out — and the lexer collapses a card's own name to the
    self-reference, so under a self-scoped ability the two are one referent. The
    parser knew only the pronoun, so the spelled-out form failed the line on
    unconsumed text.
    """
    pool = set_pool("MIR")
    wall = Permanent(card=pool["Wall of Corpses"])
    attacker = Permanent(card=_r1_vanilla("Raider", 3, 3))
    bystander = Permanent(card=_r1_vanilla("Bystander", 3, 3))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, bystander]),
        PlayerState(name="P2", battlefield=[wall], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()

    result = game.activate_permanent_ability(
        1, "Wall of Corpses", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(attacker)
    assert game.is_on_battlefield(bystander), "the relation narrowed the target"


# --- W1G4: the zones / cards / library family ---

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.handlers._common import apply_damage_to_creature as _w1g4_damage
from engine.control import change_control as _w1g4_change_control
from engine.models import Permanent as _W1G4Permanent


def test_gravebane_zombie_goes_on_top_of_its_library_instead_of_dying(set_pool):
    """"If this creature would die, put it on top of its owner's library
    instead." (CR 614.)

    Firestorm Phoenix's replacement one zone over, and the three consequences
    are the ones that make it a replacement rather than a dies-trigger: the
    graveyard stays empty, the game's "creatures died this turn" tally stays at
    zero, and the card is the next one its owner draws.
    """
    pool = set_pool("MIR")
    zombie = _W1G4Permanent(card=pool["Gravebane Zombie"])
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", battlefield=[zombie], library=[pool["Island"]] * 5),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    _w1g4_damage(game, zombie, 5, source=None)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(zombie)
    assert game.players[0].graveyard == []
    assert game.players[0].library[0].name == "Gravebane Zombie"
    assert len(game.players[0].library) == 6
    assert game.creatures_died_this_turn == 0, "a replaced death is not a death"


def test_gravebane_zombie_goes_to_its_owners_library_not_its_controllers(set_pool):
    """CR 400.3: the card goes to its **owner's** library, which is the
    difference a stolen Zombie makes -- and the reason the interceptor asks
    ``owner_index_of`` rather than reading the seat off the payload.
    """
    pool = set_pool("MIR")
    zombie = _W1G4Permanent(card=pool["Gravebane Zombie"])
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", library=[pool["Island"]] * 5),
        _W1G4PlayerState(name="P2", battlefield=[zombie], library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g4_change_control(zombie, 0, source="w1g4-test")
    game._sync_control()
    assert game.controller_index_of(zombie) == 0

    _w1g4_damage(game, zombie, 5, source=None)
    game.check_state_based_actions()

    assert game.players[1].library[0].name == "Gravebane Zombie"
    assert len(game.players[0].library) == 5


def _w1g4_griffin_board(set_pool, graveyard):
    """Mtenda Griffin on seat 0's battlefield, with a graveyard to fish in.

    ``current_step`` is stamped rather than stepped to: the ability's "Activate
    only during your upkeep" clause reads exactly that, and the round is about
    the *target*, not about the turn structure.
    """
    pool = set_pool("MIR")
    griffin = _W1G4Permanent(card=pool["Mtenda Griffin"])
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", battlefield=[griffin],
            graveyard=[pool[n] for n in graveyard],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.current_step = "upkeep"
    return game, griffin


def test_mtenda_griffin_returns_a_griffin_card_and_bounces_itself(set_pool):
    """"{W}, {T}: Return this creature to its owner's hand **and return target
    Griffin card from your graveyard to your hand**."

    The subtype was refused by the graveyard family's blanket "no return
    handler honours this restriction" -- the same gate the reanimation's colour
    was lifted out of a set earlier. It travels as ``graveyard_subtypes`` and is
    tested by the one predicate the picker, the cast gate and the handler share,
    so the card is offered exactly what it may take.
    """
    game, _ = _w1g4_griffin_board(
        set_pool, ("Femeref Scouts", "Mtenda Griffin", "Viashino Warrior")
    )

    result = game.activate_permanent_ability(
        0, "Mtenda Griffin", permanent_index=0, target_permanent_index=1
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert sorted(c.name for c in game.players[0].hand) == [
        "Mtenda Griffin", "Mtenda Griffin",
    ], "the permanent and the graveyard card, one each"
    assert [c.name for c in game.players[0].graveyard] == [
        "Femeref Scouts", "Viashino Warrior",
    ], "exactly one card left the graveyard"
    assert game.players[0].battlefield == []


@_w1g4_pytest.mark.parametrize("slot", [0, 2])
def test_mtenda_griffin_refuses_a_card_that_is_not_a_griffin(set_pool, slot):
    """The narrowing in the direction that matters: a dropped subtype would
    have let the ability fish any creature card out, which is a strictly better
    card than the one printed and nothing on the board would show it."""
    game, _ = _w1g4_griffin_board(
        set_pool, ("Femeref Scouts", "Mtenda Griffin", "Viashino Warrior")
    )

    result = game.activate_permanent_ability(
        0, "Mtenda Griffin", permanent_index=0, target_permanent_index=slot
    )

    assert not result.supported
    assert len(game.players[0].graveyard) == 3
    assert game.players[0].battlefield, "a refused activation pays nothing"


def test_jungle_patrol_sacrifices_its_own_wood_token_for_red_mana(set_pool):
    """"{1}{G}, {T}: Create a 0/1 green Wall creature token with defender named
    Wood." / "**Sacrifice a token named Wood**: Add {R}."

    The second ability was lost to a word in fetched data. Scryfall lists
    "Token" among the supertypes -- a token's printed line really does read
    "Token Creature - Wall" -- so the noun parser ate the singular as an
    adjective and the phrase was left with no head noun, refusing with "expected
    what to sacrifice as a cost". Only the plural ("any number of tokens") ever
    reached CR 111.1's branch. The word is now read there first, and the
    printed *name* is what pins the cost.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", battlefield=[_W1G4Permanent(card=pool["Jungle Patrol"])],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Jungle Patrol", permanent_index=0, ability_index=0
    ).supported
    game.resolve_stack()
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Jungle Patrol", "Wood",
    ]

    result = game.activate_permanent_ability(
        0, "Jungle Patrol", permanent_index=0, ability_index=1
    )

    assert result.supported, result.details
    assert [p.card.name for p in game.players[0].battlefield] == ["Jungle Patrol"]
    assert game.players[0].mana_pool["R"] == 1


def test_jungle_patrol_will_not_eat_a_creature_that_is_not_a_wood_token(set_pool):
    """The name is the narrowing, and a dropped one would let the ability eat
    any creature on the board for {R} -- a strictly better card with nothing on
    the board to show it. CR 602.2b: an unpayable cost refuses the activation
    with nothing spent."""
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1",
            battlefield=[
                _W1G4Permanent(card=pool["Jungle Patrol"]),
                _W1G4Permanent(card=pool["Femeref Scouts"]),
            ],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Jungle Patrol", permanent_index=0, ability_index=1
    )

    assert not result.supported
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Jungle Patrol", "Femeref Scouts",
    ]
    assert game.players[0].mana_pool["R"] == 0


def test_zombie_mob_counts_the_graveyard_before_it_eats_it(set_pool):
    """"This creature enters with a +1/+1 counter on it **for each creature card
    in your graveyard**." / "When this creature enters, exile all creature cards
    from your graveyard."

    Two firsts on one card. The entry counters take their number from a third
    place -- neither the printed line nor the announced X, but the board as the
    permanent enters (CR 608.2) -- and the noun phrase goes through the same
    ``parse_subject_filter`` + ``count_spec`` pair the printed sentence "gets
    +1/+1 for each creature card in your graveyard" already uses, so the two
    count the same set. The sweep is over a pile of *cards*, which the
    battlefield sweep cannot be: CR 613.1 gives a card in a graveyard no
    computed characteristics for ``subject_matches`` to read.

    The order is the assertion. CR 614.1c applies the counters as the permanent
    enters and the trigger resolves afterwards, so the Mob is sized by a
    graveyard it then empties -- and the printed 2/0 is why that matters: with
    no creature card there it enters and dies.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[pool["Zombie Mob"]],
            graveyard=[pool["Femeref Scouts"], pool["Mana Prism"],
                       pool["Viashino Warrior"], pool["Island"]],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(
            name="P2", graveyard=[pool["Femeref Scouts"]],
            library=[pool["Island"]] * 5,
        ),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.cast_from_hand(0, "Zombie Mob").supported
    game.resolve_stack()

    mob = game.players[0].battlefield[0]
    assert (mob.effective_power, mob.effective_toughness) == (4, 2), "2/0 plus two"
    assert [c.name for c in game.players[0].graveyard] == ["Mana Prism", "Island"]
    assert sorted(c.name for c in game.players[0].exile) == [
        "Femeref Scouts", "Viashino Warrior",
    ]
    assert [c.name for c in game.players[1].graveyard] == ["Femeref Scouts"], (
        "'your graveyard' is one pile"
    )
