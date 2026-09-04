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


# --- W1G3: damage / prevention / life ---

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_tap_all(game, player, lands, color):
    for land in lands:
        assert game.tap_land_for_mana(
            0, land.card.name, color,
            permanent_index=player.battlefield.index(land),
        )


def _w1g3_hellkite_board(set_pool, land_name, land_count):
    pool = set_pool("MIR")
    hellkite = _W1G3Permanent(card=pool["Crimson Hellkite"])
    lands = [_W1G3Permanent(card=pool[land_name]) for _ in range(land_count)]
    victim = _W1G3Permanent(card=pool["Wild Elephant"])       # 3/3
    p1 = _W1G3PlayerState(name="P1", battlefield=[hellkite, *lands],
                          library=[pool[land_name]] * 10, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[victim],
                          library=[pool[land_name]] * 10, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.start_turn(0)
    _w1g3_tap_all(game, p1, lands, "R" if land_name == "Mountain" else "G")
    return game, hellkite, victim


def test_crimson_hellkite_spends_red_mana_on_x(set_pool):
    """"{X}, {T}: This creature deals X damage to target creature. **Spend only
    red mana on X.**"

    The whole line refused to parse before this round, so the ability did not
    exist. Two halves land together, because a restriction the grammar consumes
    and nothing charges is an ability that works more often than the card
    allows: the sentence is claimed, and the X pips are charged as {R}.
    """
    game, hellkite, victim = _w1g3_hellkite_board(set_pool, "Mountain", 2)

    result = game.activate_permanent_ability(
        0, "Crimson Hellkite", x_value=2,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert victim.damage_marked == 2
    assert hellkite.tapped


def test_crimson_hellkite_refuses_to_pay_x_from_the_wrong_colour(set_pool):
    """The other direction, without which the test above passes for an ability
    that charges X as generic mana — which is every colour at once."""
    game, hellkite, victim = _w1g3_hellkite_board(set_pool, "Forest", 2)

    result = game.activate_permanent_ability(
        0, "Crimson Hellkite", x_value=2,
        target_player_index=1, target_permanent_index=0,
    )

    assert not result.supported, (
        "two Forests paid an X the card says only red mana may pay "
        f"— log: {game.log}"
    )
    assert victim.damage_marked == 0
    assert not hellkite.tapped, "CR 602.2b: nothing is paid by a refused activation"


def test_burning_palm_efreet_grounds_the_creature_it_damaged(set_pool):
    """"{1}{R}{R}: This creature deals 2 damage to target creature with flying
    **and that creature loses flying** until end of turn."

    Vertigo prints the identical two clauses with a full stop between them and
    has played correctly since Ice Age: the sentence loop probes the pronoun
    rider between sentences. Joined with "and" the conjunction loop never
    reaches it, so "that creature" fell through to the bare-noun reading and
    the lowering refused — one printed word from a card that works.

    The keyword is gone from the creature that was damaged, and the ability
    picked its target once: both instructions carry the same description.
    """
    pool = set_pool("MIR")
    efreet = _W1G3Permanent(card=pool["Burning Palm Efreet"])
    drake = _W1G3Permanent(card=pool["Azimaet Drake"])        # 1/3 flier
    wyvern = _W1G3Permanent(card=pool["Cerulean Wyvern"])     # 3/3 flier
    p1 = _W1G3PlayerState(name="P1", battlefield=[efreet], life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[drake, wyvern], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.activate_permanent_ability(
        0, "Burning Palm Efreet",
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert drake.damage_marked == 2
    assert not drake.has_keyword("flying"), (
        f"the loss missed the creature the ability damaged: {game.log}"
    )
    assert wyvern.damage_marked == 0
    assert wyvern.has_keyword("flying"), "one target, not every flier"


def test_abyssal_hunter_bites_the_creature_it_tapped(set_pool):
    """"{B}, {T}: Tap target creature. This creature deals damage equal to its
    power **to that creature**."

    The same cross-clause pronoun one node type over, and the same one-word
    difference: Tracker and Karplusan Yeti print "…equal to its power to
    **target** creature" and have worked since Ice Age, while this card names
    the creature the sentence in front of it chose and refused at lowering for
    want of a producer for ``its_power``.

    A second creature on the board makes the test about the *binding*: only the
    tapped one is bitten, so the ability did not fall through to whatever the
    resolution context was carrying.
    """
    pool = set_pool("MIR")
    hunter = _W1G3Permanent(card=pool["Abyssal Hunter"])
    victim = _W1G3Permanent(card=pool["Wild Elephant"])       # 3/3
    bystander = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(name="P1", battlefield=[hunter], life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[victim, bystander], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.activate_permanent_ability(
        0, "Abyssal Hunter",
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert victim.tapped
    assert victim.damage_marked == hunter.effective_power > 0
    assert not bystander.tapped
    assert bystander.damage_marked == 0


def test_floodgate_sacrifices_itself_the_moment_it_has_flying(set_pool):
    """"When this creature has flying, sacrifice it." (CR 603.8.)

    The fifth state trigger in the state-based sweep and the keyword twin of
    Phyrexian Devourer's power threshold — swept rather than fired from a call
    site, because a keyword can arrive from an Aura, an Equipment, a board-wide
    static or a layer effect ending, and a list of those sites goes stale.
    """
    pool = set_pool("MIR")
    gate = _W1G3Permanent(card=pool["Floodgate"])
    p1 = _W1G3PlayerState(name="P1", battlefield=[gate], life=20)
    p2 = _W1G3PlayerState(name="P2", life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game._settle()
    assert game.is_on_battlefield(gate), "a Wall without flying stays"

    from engine.keywords import grant_keyword

    grant_keyword(gate, "flying", duration="end_of_turn")
    game._settle()

    assert not game.is_on_battlefield(gate), (
        f"the state trigger never fired: {game.log}"
    )


def test_floodgate_counts_islands_when_it_leaves(set_pool):
    """"When this creature leaves the battlefield, it deals damage to each
    nonblue creature without flying equal to **half the number of Islands you
    control, rounded down**."

    A *counted* sweep, which both sweep lowerings refused outright ("a creature
    sweep cannot carry a computed damage amount"). The refusal was about the
    amount reaching the handler — and `x_from_count` is substituted into the
    resolution's X at the single dispatch point, before any handler runs, so a
    sweep asking for "x" gets the number exactly as a single recipient does.

    The three creatures separate the three narrowings: blue is spared, a flier
    is spared, and the ground non-blue creature takes half of five Islands.
    """
    pool = set_pool("MIR")
    gate = _W1G3Permanent(card=pool["Floodgate"])
    islands = [_W1G3Permanent(card=pool["Island"]) for _ in range(5)]
    ground = _W1G3Permanent(card=pool["Zhalfirin Commander"])   # white, no flying
    flier = _W1G3Permanent(card=pool["Cerulean Wyvern"])        # blue flier
    blue_ground = _W1G3Permanent(card=pool["Wall of Corpses"])  # black wall
    p1 = _W1G3PlayerState(name="P1", battlefield=[gate, *islands], life=20)
    p2 = _W1G3PlayerState(
        name="P2", battlefield=[ground, flier, blue_ground], life=20
    )
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.sacrifice_permanent(gate)
    game._settle()

    assert ground.damage_marked == 2, f"half of five Islands: {game.log}"
    assert flier.damage_marked == 0, "flying is spared"
    assert blue_ground.damage_marked == 2, "black is not blue"


# --- W1G1: the combat family ---
#
# Cards whose refusal sat in a combat gate rather than in a production: the two
# printed *restriction* tables (`engine/combat_restrictions.py`,
# `engine/activation_restrictions.py`), the block relations, and the flanking
# leftovers round 1 named. Each section below names the card and the layer that
# was missing.

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g1_vanilla(
    name: str, power: int, toughness: int, text: str = "",
    subtype: str = "Test", colors: tuple = (),
) -> CardDefinition:
    """A creature carrying only its numbers.

    Invented rather than pulled from the pool: every test below is about a
    relation between two creatures, and a pool creature would bring its own
    printed line along with the answer.
    """
    type_line = f"Creature - {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=text, colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g1_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g1_game(mine, theirs, active: int = 0) -> Game:
    """A two-seat game stopped at the declare-attackers step of *active*'s turn."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(active)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    return game


# --- Shauku, Endbringer: a restriction qualified by the *shared* zone ---


def test_shauku_alone_on_the_battlefield_may_attack(set_pool):
    """"Shauku can't attack **if there's another creature on the
    battlefield**."

    The qualifier is what makes the card playable at all, and reading "another"
    as an article would have grounded it permanently -- so the empty-board case
    is the one that proves the word survived the parse.
    """
    shauku = _w1g1_nosick(Permanent(card=set_pool("MIR")["Shauku, Endbringer"]))
    game = _w1g1_game([shauku], [])

    assert game.can_attack(shauku, 1)
    assert game.declare_attackers(0, [0])[0]


@pytest.mark.parametrize("side", ["mine", "theirs"])
def test_shauku_is_grounded_by_any_other_creature(set_pool, side):
    """CR 403.1 makes the battlefield one shared zone, so the clause is not a
    question about either player's board -- an opponent's creature stops Shauku
    exactly as its own controller's does. That is the reading the seat-scoped
    "as long as ... controls" qualifier could not have expressed."""
    shauku = _w1g1_nosick(Permanent(card=set_pool("MIR")["Shauku, Endbringer"]))
    other = Permanent(card=_w1g1_vanilla("Bystander", 1, 1))
    game = _w1g1_game(
        [shauku, other] if side == "mine" else [shauku],
        [] if side == "mine" else [other],
    )

    assert not game.can_attack(shauku, 1)
    ok, reason = game.declare_attackers(0, [0])
    assert not ok and "Shauku" in reason


def test_shauku_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Shauku, Endbringer"])
    assert program.supported, program.reason
    condition = next(
        i.payload["condition"] for i in program.instructions
        if i.kind == "cant_attack"
    )
    # "Another" reaches the matcher as the key every other reader of a noun
    # phrase already tests, rather than as a spelling only this table knows.
    assert condition["subject"]["exclude_self"] is True
    assert condition["who"] == "anyone"


# --- Ekundu Cyclops: a CR 508.1d requirement conditional on the declaration ---


def test_ekundu_cyclops_may_attack_alone(set_pool):
    """"**If a creature you control attacks**, this creature also attacks if
    able."

    "Also" is what says the condition names another creature. Read as including
    the Cyclops itself the requirement would be self-satisfying, which is a
    different card -- so the lone declaration is legal and nothing forces it.
    """
    cyclops = _w1g1_nosick(Permanent(card=set_pool("MIR")["Ekundu Cyclops"]))
    bear = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Bear", 2, 2)))
    game = _w1g1_game([cyclops, bear], [])

    assert game.declare_attackers(0, [0])[0]


def test_ekundu_cyclops_must_join_a_declaration(set_pool):
    """The requirement is about the *set*, not about the creature: a Bear
    attacking alone is an illegal declaration while the Cyclops could attack,
    which is why this cannot live in the per-creature ``_must_attack_if_able``
    predicate."""
    cyclops = _w1g1_nosick(Permanent(card=set_pool("MIR")["Ekundu Cyclops"]))
    bear = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Bear", 2, 2)))
    game = _w1g1_game([cyclops, bear], [])

    ok, reason = game.declare_attackers(0, [1])
    assert not ok and "Ekundu Cyclops" in reason

    game = _w1g1_game(
        [_w1g1_nosick(Permanent(card=set_pool("MIR")["Ekundu Cyclops"])),
         _w1g1_nosick(Permanent(card=_w1g1_vanilla("Bear", 2, 2)))], [],
    )
    assert game.declare_attackers(0, [0, 1])[0]


def test_ekundu_cyclops_is_not_required_when_it_cannot_attack(set_pool):
    """CR 508.1d obeys a requirement only so far as it is able: a tapped
    Cyclops cannot attack, so the Bear's declaration stands."""
    cyclops = _w1g1_nosick(Permanent(card=set_pool("MIR")["Ekundu Cyclops"]))
    bear = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Bear", 2, 2)))
    game = _w1g1_game([cyclops, bear], [])
    # After the untap step, or CR 502.1 would have undone it.
    cyclops.tapped = True

    assert game.declare_attackers(0, [1])[0]


def test_ekundu_cyclops_is_not_required_by_an_opponents_attack(set_pool):
    """"A creature **you control**" is CR 109.5's seat -- the controller of the
    printed line, not whoever happens to be attacking. The Cyclops's own
    controller declaring nobody leaves it free."""
    cyclops = _w1g1_nosick(Permanent(card=set_pool("MIR")["Ekundu Cyclops"]))
    raider = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Raider", 2, 2)))
    game = _w1g1_game([raider], [cyclops], active=0)

    assert game.declare_attackers(0, [0])[0]


# --- Sawback Manticore: a CR 602.5 clause about the source's combat role ---


def test_sawback_manticore_refuses_while_out_of_combat(set_pool):
    """"Activate only **if this creature is attacking or blocking**."

    The distinction from the phase clause beside it (Jade Statue's "only during
    combat") is the whole point: a Manticore sitting at home during somebody
    else's combat is in the combat phase and is in neither role. Driven with a
    legal target on the board, so the refusal that fires is this one rather
    than the target gate.
    """
    manticore = _w1g1_nosick(Permanent(card=set_pool("MIR")["Sawback Manticore"]))
    raider = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Raider", 4, 4)))
    game = _w1g1_game([raider], [manticore], active=0)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]

    result = game.activate_permanent_ability(
        1, "Sawback Manticore", permanent_index=0,
        target_player_index=0, target_permanent_index=0, ability_index=1,
    )
    assert not result.supported
    assert "not attacking or blocking" in result.details


def test_sawback_manticore_pings_while_attacking(set_pool):
    """And the same ability, once the source is in a role. The second
    activation is refused by the "and only once each turn" conjunct, which
    ``_conjuncts`` splits off -- proof that admitting the new clause did not
    swallow the one beside it.
    """
    manticore = _w1g1_nosick(Permanent(card=set_pool("MIR")["Sawback Manticore"]))
    wall = Permanent(card=_w1g1_vanilla("Blocker", 4, 4))
    game = _w1g1_game([manticore], [wall])
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    def ping():
        return game.activate_permanent_ability(
            0, "Sawback Manticore", permanent_index=0,
            target_player_index=1, target_permanent_index=0, ability_index=1,
        )

    result = ping()
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    assert any("dealt 2 damage to Blocker" in line for line in game.log)

    assert "only once each turn" in ping().details


# --- Barbed-Back Wurm and Urborg Panther: the block relation, both spellings ---


def _w1g1_blocked(set_pool, attacker_name: str, colors: tuple = ("G",)):
    """*attacker_name* attacking, blocked by the first of two identical
    creatures.

    Two on the far side on purpose, and identical: one blocked and one did not,
    and *nothing about either creature* tells them apart. A dropped relation
    therefore shows up as the bystander being reachable, which is the only way
    to see it -- a differently-shaped bystander would be excluded by its shape.
    """
    attacker = _w1g1_nosick(Permanent(card=set_pool("MIR")[attacker_name]))
    others = [
        Permanent(card=_w1g1_vanilla(name, 5, 5, colors=colors))
        for name in ("Blocker", "Bystander")
    ]
    game = _w1g1_game([attacker], others)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    return game, attacker, others


def test_barbed_back_wurm_shrinks_only_a_green_blocker(set_pool):
    """"{B}: Target **green** creature blocking this creature gets -1/-1."

    "Blocking this creature" is ``blocked_by_source`` read from the other end,
    and it was the one relative narrowing with no payload form -- so the whole
    ability refused. It has one now, tested by the same ``subject_matches`` its
    mirror goes through, and the colour rides beside it like any other key.
    """
    program = compile_card_oracle(set_pool("MIR")["Barbed-Back Wurm"])
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    described = ability.instruction.payload["targets"]["filter"]
    assert described["blocking_source"] is True
    assert described["color_filter"] == "G"


def test_barbed_back_wurm_offers_only_the_creature_in_front_of_it(set_pool):
    """The picker and the resolution are the same list.

    Both halves matter and each was broken on its own: the enumerator offered
    every creature on the board without the flag, and the pump handler dropped
    the relation at resolution because it asked the *pure* matcher.
    """
    game, wurm, others = _w1g1_blocked(set_pool, "Barbed-Back Wurm")
    blocker, bystander = others

    result = game.activate_permanent_ability(
        0, "Barbed-Back Wurm", permanent_index=0,
        target_player_index=1, target_permanent_index=1,
    )
    assert not result.supported, "the bystander is not blocking this creature"

    result = game.activate_permanent_ability(
        0, "Barbed-Back Wurm", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    assert (blocker.effective_power, blocker.effective_toughness) == (4, 4)
    assert (bystander.effective_power, bystander.effective_toughness) == (5, 5)


def test_urborg_panther_binds_its_pronoun_to_its_own_source(set_pool):
    """"Destroy target creature blocking **it**."

    Nothing is printed after the word, so the noun parser reads a
    back-reference -- and under an activated ability whose whole effect is this
    one statement there is nothing earlier for it to name. The pronoun is
    rebound onto the source where the sentence is in view, which is the same
    rewrite Johtull Wurm's "for each creature blocking it" already needed.
    """
    program = compile_card_oracle(set_pool("MIR")["Urborg Panther"])
    assert program.supported, program.reason
    destroy = program.activated_abilities[0].instruction
    assert destroy.kind == "destroy_target_permanent"
    assert destroy.payload["targets"]["filter"]["blocking_source"] is True
    assert "blocking_bound_target" not in destroy.payload["targets"]["filter"]


def test_a_bare_spell_line_keeps_refusing_the_pronoun(set_pool):
    """The rewrite is narrow on purpose. A spell's own source is a card on the
    stack, which blocks nothing, so "Destroy target creature blocking it" as a
    whole printed line still has no referent and still refuses."""
    from engine.grammar import compile_line

    result = compile_line("Destroy target creature blocking it.", card_name="Test")
    assert result.parsed and not result.lowered


def test_urborg_panther_destroys_the_creature_blocking_it(set_pool):
    game, panther, others = _w1g1_blocked(set_pool, "Urborg Panther")
    blocker, bystander = others

    result = game.activate_permanent_ability(
        0, "Urborg Panther", permanent_index=0,
        target_player_index=1, target_permanent_index=0, ability_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)


def test_urborg_panther_charges_all_three_sacrifices(set_pool):
    """"Sacrifice a creature named Feral Shadow, a creature named
    Breathstealer, **and this creature**."

    Three objects under one printed verb, which is two more than the
    single-object delimiter could see: it stopped at the first comma, read the
    Shadow and missed both the Breathstealer and the source. A cost charged as
    one third of what the card prints is an ability activated for less than it
    says, so the list is read by the grammar *and* by the charger, and capped at
    what the three cost fields can hold.
    """
    pool = set_pool("MIR")
    panther = _w1g1_nosick(Permanent(card=pool["Urborg Panther"]))
    shadow = _w1g1_nosick(Permanent(card=pool["Feral Shadow"]))
    breathstealer = _w1g1_nosick(Permanent(card=pool["Breathstealer"]))
    library = [pool["Spirit of the Night"], _w1g1_vanilla("Filler", 1, 1)]
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[panther, shadow, breathstealer],
            library=list(library),
        ),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        0, "Urborg Panther", permanent_index=0, ability_index=1
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert {card.name for card in game.players[0].graveyard} == {
        "Urborg Panther", "Feral Shadow", "Breathstealer",
    }

    index = next(
        i for i, card in enumerate(game.players[0].library)
        if card.name == "Spirit of the Night"
    )
    assert game.confirm_search_library(0, index)
    game._settle()
    assert [perm.card.name for perm in game.players[0].battlefield] == [
        "Spirit of the Night"
    ]


def test_urborg_panther_pays_nothing_when_a_piece_is_missing(set_pool):
    """CR 601.2h: the whole cost is unpayable, so the activation is refused with
    nothing sacrificed -- not the Shadow eaten for an ability that then cannot
    finish."""
    pool = set_pool("MIR")
    panther = _w1g1_nosick(Permanent(card=pool["Urborg Panther"]))
    shadow = _w1g1_nosick(Permanent(card=pool["Feral Shadow"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[panther, shadow],
                    library=[pool["Spirit of the Night"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        0, "Urborg Panther", permanent_index=0, ability_index=1
    )
    assert not result.supported
    assert {perm.card.name for perm in game.players[0].battlefield} == {
        "Urborg Panther", "Feral Shadow",
    }


def test_a_card_name_stops_at_a_list_separator(set_pool):
    """The bug the three-object cost exposed, which has nothing to do with
    sacrifice: a comma inside a name is the one a legendary title carries, and
    the scan ran through this one to the next "and". The first cost object came
    back asking for a card literally named "Feral Shadow, a creature named
    Breathstealer" -- a filter matching nothing, so the cost was admitted and
    could never be paid."""
    from engine.oracle import parse_activated_ability_cost

    cost = parse_activated_ability_cost(
        set_pool("MIR")["Urborg Panther"].oracle_text.splitlines()[1]
    )
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature", "named": "feral shadow",
    }
    assert cost.sacrifice_also_filter == {
        "type_filter": "creature", "named": "breathstealer",
    }


# --- Wave Elemental and Telim'Tor: a keyword narrowing on a multi-target ---


def test_wave_elemental_taps_the_ground_and_not_the_sky(set_pool):
    """"Tap up to three target creatures **without flying**."

    The several-target arm gated on a hand-listed three fields written against
    a handler that asked the *pure* matcher, so a layer-6 question refused --
    one the sweep arm directly above it has answered since it was written. Both
    ask ``subject_matches`` now and both gate on what it can test.
    """
    elemental = _w1g1_nosick(Permanent(card=set_pool("MIR")["Wave Elemental"]))
    ground = [
        Permanent(card=_w1g1_vanilla(f"Footman{i}", 2, 2)) for i in range(3)
    ]
    flier = Permanent(
        card=CardDefinition(
            name="Skyguard", mana_cost="", cmc=0.0, type_line="Creature - Test",
            oracle_text="Flying", colors=(), color_identity=(),
            keywords=("Flying",), produced_mana=(),
            raw={"name": "Skyguard", "type_line": "Creature - Test",
                 "power": "2", "toughness": "2"},
        )
    )
    game = Game(players=[
        PlayerState(name="P1", battlefield=[elemental]),
        PlayerState(name="P2", battlefield=[*ground, flier]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        0, "Wave Elemental", permanent_index=0, target_player_index=1,
        target_permanent_ids=[
            ground[0].permanent_id, ground[1].permanent_id, flier.permanent_id
        ],
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert [perm.tapped for perm in ground] == [True, True, False]
    assert not flier.tapped, "the printed narrowing must not be dropped"


def test_telim_tor_pumps_only_the_flankers(set_pool):
    """"Whenever Telim'Tor attacks, all attacking creatures **with flanking**
    get +1/+1 until end of turn."

    The one card round 1 named and did not buy: the global buff's narrowing
    vocabulary is hand-listed, and a keyword was not on the list. Asked of layer
    6 (CR 613.1f), so a creature an Aura gave flanking is in the set -- which is
    the whole reason ``keywords.LINE_DERIVED_KEYWORDS`` puts the word back when
    it grants the line.
    """
    pool = set_pool("MIR")
    telim = _w1g1_nosick(Permanent(card=pool["Telim'Tor"]))
    askari = _w1g1_nosick(Permanent(card=pool["Searing Spear Askari"]))
    plain = _w1g1_nosick(Permanent(card=_w1g1_vanilla("Footman", 2, 2)))
    game = _w1g1_game([telim, askari, plain], [])

    before = {
        perm.card.name: (perm.effective_power, perm.effective_toughness)
        for perm in (telim, askari, plain)
    }
    assert game.declare_attackers(0, [0, 1, 2])[0]
    game.resolve_stack()
    game._settle()

    assert (telim.effective_power, telim.effective_toughness) == (
        before["Telim'Tor"][0] + 1, before["Telim'Tor"][1] + 1,
    )
    assert (askari.effective_power, askari.effective_toughness) == (
        before["Searing Spear Askari"][0] + 1,
        before["Searing Spear Askari"][1] + 1,
    )
    assert (plain.effective_power, plain.effective_toughness) == before["Footman"]


def test_a_keyword_the_engine_does_not_implement_refuses_the_anthem(set_pool):
    """The gate that comes with the narrowing. ``_has_keyword`` answers no for
    a word no behaviour is registered under, so a filter naming one is not
    refused anywhere -- it is silently inert, and an inert *positive* filter
    matches nothing at all. That is a buff the card reports as supported and
    which reaches nobody, so the line refuses instead."""
    from engine.grammar import compile_line

    result = compile_line(
        "Creatures with shadow get +1/+1 until end of turn.", card_name="Test"
    )
    assert result.parsed and not result.lowered
    assert "shadow" in result.failure_reason


# --- Catacomb Dragon: a halved characteristic in a where-clause ---


def test_catacomb_dragon_halves_the_blockers_power(set_pool):
    """"…gets -X/-0 until end of turn, where X is **half the creature's power,
    rounded down**."

    Two pieces the where-clause had neither of: an arithmetic over a
    *characteristic* rather than over a count, and the definite-article
    possessive ("**the** creature's power" beside the demonstrative one it
    already read). The halving rides on the count spec like the multiplier and
    the offset, so `_scaled` applies it -- which is also where the bug was: the
    characteristic branch was the one computed quantity that never reached that
    function at all.
    """
    dragon = _w1g1_nosick(Permanent(card=set_pool("MIR")["Catacomb Dragon"]))
    blocker = Permanent(
        card=CardDefinition(
            name="Longbowman", mana_cost="", cmc=0.0, type_line="Creature - Test",
            oracle_text="Reach", colors=(), color_identity=(), keywords=("Reach",),
            produced_mana=(),
            raw={"name": "Longbowman", "type_line": "Creature - Test",
                 "power": "7", "toughness": "7"},
        )
    )
    game = _w1g1_game([dragon], [blocker])
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    assert len(game.stack) == 1, "the -X/-0 waits on the stack (CR 603.3)"

    game.resolve_stack()
    game._settle()

    # 7 // 2 == 3, rounded down as printed.
    assert (blocker.effective_power, blocker.effective_toughness) == (4, 7)


def test_catacomb_dragon_reads_the_printed_exclusions(set_pool):
    """"…blocked by a **nonartifact, non-Dragon** creature."

    The comma bound on a trigger's subject group is load-bearing -- a condition
    ends at one -- and this is the one printed shape where a comma falls
    *inside* the noun phrase. The delimiter stopped at the first one, so the
    whole condition went unread and the card refused with every line
    grammar-clean, which is the refusal no census can attribute to a clause.
    """
    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Catacomb Dragon"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.payload["blocker_filter"] == {
        "type_filter": "creature",
        "exclude_types": ["artifact"],
        "exclude_subtypes": ["dragon"],
    }

    for type_line in ("Artifact Creature - Golem", "Creature - Dragon"):
        dragon = _w1g1_nosick(Permanent(card=pool["Catacomb Dragon"]))
        exempt = Permanent(
            card=CardDefinition(
                name="Exempt", mana_cost="", cmc=0.0, type_line=type_line,
                oracle_text="Reach", colors=(), color_identity=(),
                keywords=("Reach",), produced_mana=(),
                raw={"name": "Exempt", "type_line": type_line,
                     "power": "4", "toughness": "4"},
            )
        )
        game = _w1g1_game([dragon], [exempt])
        assert game.declare_attackers(0, [0])[0]
        game.advance_combat_phase()
        assert game.declare_blockers(1, {0: 0})[0]

        assert not game.stack, f"{type_line} is excluded by the printed phrase"
        game._settle()
        assert (exempt.effective_power, exempt.effective_toughness) == (4, 4)


def test_a_halved_where_clause_must_print_its_rounding(set_pool):
    """CR 107.1b gives no default. A sentence that halves always says which
    way, so one that does not is a sentence this is misreading -- and guessing
    "down" would be a silent arithmetic choice on a number the card never
    printed."""
    from engine.grammar import compile_line

    result = compile_line(
        "Target creature gets -X/-0 until end of turn, "
        "where X is half that creature's power.",
        card_name="Test",
    )
    assert not result.parsed
    assert "rounding" in result.failure_reason


# --- Kukemssa Pirates: "defending player controls" on a steal ---


def _w1g1_artifact(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _w1g1_unblocked_attack(set_pool, extra_own_artifact: bool = False):
    """Kukemssa Pirates attacking unblocked, with its trigger on the stack
    resolved and its offer waiting."""
    pirates = _w1g1_nosick(Permanent(card=set_pool("MIR")["Kukemssa Pirates"]))
    mine = [Permanent(card=_w1g1_artifact("My Bauble"))] if extra_own_artifact else []
    theirs = Permanent(card=_w1g1_artifact("Their Relic"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[pirates, *mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    game.advance_combat_phase()
    game.resolve_stack()
    return game, pirates, theirs


def test_kukemssa_pirates_offers_only_the_defenders_artifact(set_pool):
    """"…target artifact **defending player controls**".

    The permanent steal refused the seat outright: `object_only_filter` was
    asked with nothing carried, so every "gain control of target X <seat>
    controls" in the pool was unsupported for a narrowing the picker was
    already carrying out for the *linked* durations beside it.
    """
    program = compile_card_oracle(set_pool("MIR")["Kukemssa Pirates"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    steal, rider = trigger.instruction.payload["action"] + trigger.instruction.payload["then"]
    assert steal.kind == "gain_control_of_target"
    assert steal.payload["controller"] == "defending_player"
    assert rider.kind == "assign_no_combat_damage_until_eot"


def test_kukemssa_pirates_steals_when_the_offer_is_taken(set_pool):
    """And the offer, taken. The trigger names its target as it goes on the
    stack (CR 603.3d), which is what the seat had to reach: without it the
    picker offered nothing and the ability left the stack under CR 603.3c."""
    from engine.combat_assignment import ASSIGNS_NO_COMBAT_DAMAGE

    game, pirates, relic = _w1g1_unblocked_attack(set_pool, extra_own_artifact=True)
    (offer,) = game.pending_optional_pays

    assert game.confirm_optional_pay(offer["player_index"], accept=True)
    game.resolve_stack()
    game._settle()

    assert game.controls(0, relic)
    assert pirates.metadata.get(ASSIGNS_NO_COMBAT_DAMAGE)


def test_kukemssa_pirates_declined_steals_nothing_and_hits(set_pool):
    """The decline branch. "If you do" is what pairs the rider to the steal, so
    a declined offer leaves the attacker assigning its damage normally."""
    from engine.combat_assignment import ASSIGNS_NO_COMBAT_DAMAGE

    game, pirates, relic = _w1g1_unblocked_attack(set_pool)
    (offer,) = game.pending_optional_pays

    assert game.confirm_optional_pay(offer["player_index"], accept=False)
    game.resolve_stack()
    game._settle()

    assert game.controls(1, relic)
    assert not pirates.metadata.get(ASSIGNS_NO_COMBAT_DAMAGE)
