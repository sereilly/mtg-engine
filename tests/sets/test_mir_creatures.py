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
