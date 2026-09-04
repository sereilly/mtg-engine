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


# --- W1G2: end-step counters gated and counted by a turn's history ---
#
# Three creatures whose whole ability is one end-step trigger that puts a
# counter on itself, and whose refusals were three different halves of the same
# sentence: an intervening-if the parser could not read (Wall of Resistance), an
# intervening-if the parser *could* read and nothing evaluated (Discordant
# Spirit), and a "for each" whose set is a per-seat turn history (Asmira).
#
# Every one of them compiles into the end step's catch-all scan, which is
# exactly why each test drives a real turn: a trigger that reports supported and
# fires nowhere looks identical to one that works, from the compiled program.

from engine import Game, PlayerState
from engine.handlers._common import apply_damage_to_creature
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g2_vanilla(name: str) -> CardDefinition:
    """A 2/2 with no text, for a death that is only a death."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _w1g2_board(set_pool, name, *, mine=(), theirs=()):
    """*name* on seat 0's battlefield, turn 0 begun, nobody interactive."""
    subject = Permanent(card=set_pool("MIR")[name])
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[subject] + [Permanent(card=_w1g2_vanilla(n)) for n in mine],
        ),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=_w1g2_vanilla(n)) for n in theirs],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game, subject


def _w1g2_kill(game, seat: int, permanent) -> None:
    """Put *permanent* into its owner's graveyard from the battlefield."""
    game._permanent_to_graveyard(game.players[seat], permanent)
    game.remove_from_battlefield(permanent)


def test_wall_of_resistance_takes_no_counter_without_damage(set_pool):
    """"At the beginning of each end step, **if this creature was dealt damage
    this turn**, put a +0/+1 counter on it."

    CR 603.4: an intervening-if whose condition is false is not a trigger at
    all. The passive voice is the whole of what was missing — the grammar knew
    "if this creature **dealt** damage to a player this turn" (Whirling Dervish)
    and not the other end of the same event.
    """
    program = compile_card_oracle(set_pool("MIR")["Wall of Resistance"])
    assert program.supported, program.reason

    game, wall = _w1g2_board(set_pool, "Wall of Resistance")
    game.resolve_end_step(0)
    game.resolve_stack()

    assert wall.effective_toughness == 3, game.log


def test_wall_of_resistance_takes_a_counter_after_damage(set_pool):
    """The condition reads the record the damage seam already stamps on every
    recipient — the same one the noun phrase "a creature that has been dealt
    damage this turn" (Giant Shark) reads — rather than ``damage_marked``, which
    regeneration and a toughness rewrite each wipe while the damage stays
    dealt."""
    game, wall = _w1g2_board(set_pool, "Wall of Resistance")
    apply_damage_to_creature(game, wall, 1, None)

    game.resolve_end_step(0)
    game.resolve_stack()

    assert wall.effective_toughness == 4, game.log


def test_wall_of_resistance_fires_on_every_players_end_step(set_pool):
    """"**each** end step", not "your end step" — CR 513.1 gives every turn one,
    and the end step's two condition kinds are what tell the scopes apart."""
    game, wall = _w1g2_board(set_pool, "Wall of Resistance")
    apply_damage_to_creature(game, wall, 1, None)

    game.resolve_end_step(1)
    game.resolve_stack()

    assert wall.effective_toughness == 4, game.log


def test_discordant_spirit_counts_the_damage_dealt_to_you(set_pool):
    """"At the beginning of each end step, if it's an opponent's turn, put a
    +1/+1 counter on this creature **for each 1 damage dealt to you this
    turn**."

    The count is the turn's damage ledger, not a life total: a life total is the
    turn's *net*, so a player dealt 3 who then gained 3 has still been dealt 3.
    """
    program = compile_card_oracle(set_pool("MIR")["Discordant Spirit"])
    assert program.supported, program.reason

    game, spirit = _w1g2_board(set_pool, "Discordant Spirit")
    game.start_next_turn()
    assert game.active_player_index == 1
    game._deal_damage_to_player(game.players[0], 3, None)

    game.resolve_end_step(1)
    game.resolve_stack()

    assert (spirit.effective_power, spirit.effective_toughness) == (5, 5), game.log


def test_discordant_spirit_is_silent_on_its_controllers_turn(set_pool):
    """"**if it's an opponent's turn**" — the half nothing evaluated.

    The clause lowered to ``{"kind": "your_turn"}`` before this round, which
    only ``static_bonuses.conditional_static_holds`` answered; reaching
    ``evaluate_condition`` it fell through to False. That is the direction that
    hides, because a trigger which never fires looks exactly like one whose
    condition was correctly false — so this is the assertion that says the gate
    is a gate and not a permanent no.
    """
    game, spirit = _w1g2_board(set_pool, "Discordant Spirit")
    game._deal_damage_to_player(game.players[0], 3, None)

    game.resolve_end_step(0)
    game.resolve_stack()

    assert (spirit.effective_power, spirit.effective_toughness) == (2, 2), game.log


def test_asmira_counts_only_deaths_into_her_controllers_graveyard(set_pool):
    """"…put a +1/+1 counter on ~ for each creature put into **your graveyard**
    from the battlefield this turn."

    CR 400.3's seat, not CR 109.5's: the tally is kept for the *owner* of what
    died, so an opponent's creature dying is not one of Asmira's counters — the
    game-wide ``creatures_died_this_turn`` the short spelling reads would have
    given her three here.
    """
    program = compile_card_oracle(set_pool("MIR")["Asmira, Holy Avenger"])
    assert program.supported, program.reason

    game, asmira = _w1g2_board(
        set_pool, "Asmira, Holy Avenger", mine=("Mine A", "Mine B"), theirs=("Theirs",)
    )
    for permanent in list(game.players[0].battlefield[1:]):
        _w1g2_kill(game, 0, permanent)
    _w1g2_kill(game, 1, game.players[1].battlefield[0])

    game.resolve_end_step(0)
    game.resolve_stack()

    assert (asmira.effective_power, asmira.effective_toughness) == (4, 5), game.log


def test_asmiras_tally_resets_with_the_turn(set_pool):
    """"**This turn**" is the window, and a per-turn counter that never resets is
    a bug that shows up only on turn two."""
    game, asmira = _w1g2_board(set_pool, "Asmira, Holy Avenger", mine=("Mine A",))
    _w1g2_kill(game, 0, game.players[0].battlefield[1])
    game.resolve_end_step(0)
    game.resolve_stack()
    assert asmira.effective_power == 3, game.log

    game.start_next_turn()
    assert game.players[0].creatures_put_into_your_graveyard_this_turn == 0
    game.resolve_end_step(1)
    game.resolve_stack()

    assert asmira.effective_power == 3, game.log


# --- W1G2: counters carried into a zone by the move that makes the permanent ---


def test_sand_golem_returns_with_a_counter_at_the_next_end_step(set_pool):
    """"When a spell or ability an opponent controls causes you to discard this
    card, return this card from your graveyard to the battlefield **with a
    +1/+1 counter on it** at the beginning of the next end step."

    Every other half of the sentence already worked — the discard trigger, the
    self-return, the delayed end-step ability. What refused was the counter
    phrase, and only because ``_parse_entering_counters`` read the counter's
    name as a *word*: "scream" is one and "+1/+1" is a ``PT`` token, so the one
    kind the pool prints most was the one kind that reader could not see.

    CR 121.2 puts the counters on as part of the move, which is why they ride
    the return rather than becoming a second instruction: the permanent does not
    exist until the return runs, and nothing behind it could name the object.
    """
    # Stupor is the set's own discard spell, so the whole test stays inside the
    # MIR pool the fixture hands it.
    golem = set_pool("MIR")["Sand Golem"]
    game = Game(players=[
        PlayerState(name="P1", hand=[golem], life=20),
        PlayerState(name="P2", hand=[set_pool("MIR")["Stupor"]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)

    assert compile_card_oracle(golem).supported
    assert game.cast_from_hand(1, "Stupor", target_player_index=0).supported
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert [c.name for c in game.players[0].graveyard] == ["Sand Golem"], game.log

    game.resolve_end_step(1)
    game.resolve_stack()

    returned = game.players[0].battlefield
    assert [p.card.name for p in returned] == ["Sand Golem"], game.log
    # 3/3 printed, so the counter is the whole of the difference.
    assert (returned[0].effective_power, returned[0].effective_toughness) == (4, 4), game.log


# --- W1G2: a search names what it found, and the tail behind it ---


def _w1g2_zirilan(set_pool, library):
    zirilan = Permanent(card=set_pool("MIR")["Zirilan of the Claw"])
    zirilan.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[zirilan],
            library=[set_pool("MIR")[name] for name in library], life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    result = game.activate_permanent_ability(
        0, "Zirilan of the Claw", permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    return game


def test_zirilan_puts_a_dragon_onto_the_battlefield_with_haste(set_pool):
    """"{1}{R}{R}, {T}: Search your library for a Dragon permanent card, put
    that card onto the battlefield, then shuffle. **That Dragon** gains haste
    until end of turn. Exile **it** at the beginning of the next end step."

    Two halves were missing. "That Dragon" names a back-reference by *subtype*
    where the bound-subject reader knew only card types — English distinguishes
    the object by whatever noun does the job, and the search that found it
    required exactly this one. And a search suspends on a prompt, so nothing
    could say which permanent it had placed: the choice resolution now writes
    the id into the resolution's scratchpad, under the same record shape a
    reanimation already uses.
    """
    program = compile_card_oracle(set_pool("MIR")["Zirilan of the Claw"])
    assert program.supported, program.reason

    game = _w1g2_zirilan(set_pool, ["Viashino Warrior", "Volcanic Dragon"])
    found = [p for p in game.players[0].battlefield
             if p.card.name == "Volcanic Dragon"]
    assert found, game.log
    assert game._has_keyword(found[0], "haste"), game.log


def test_zirilan_exiles_the_dragon_at_the_next_end_step(set_pool):
    """The whole point of the card: the Dragon is borrowed, not kept. "It" is
    the permanent the *search* placed — neither a target (nothing was chosen)
    nor the ability's own source, which is Zirilan and would have exiled the
    legend instead."""
    game = _w1g2_zirilan(set_pool, ["Viashino Warrior", "Volcanic Dragon"])
    dragon = next(p for p in game.players[0].battlefield
                  if p.card.name == "Volcanic Dragon")
    armed = [e for e in game.delayed_triggers if e.event == "next_end_step"]
    assert [e.bound_permanent_id for e in armed] == [dragon.permanent_id], game.log

    game.resolve_end_step(0)
    game.resolve_stack()

    standing = [p.card.name for p in game.players[0].battlefield]
    assert standing == ["Zirilan of the Claw"], game.log
    assert [c.name for c in game.players[0].exile] == ["Volcanic Dragon"], game.log
