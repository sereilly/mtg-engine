"""Per-card tests for Mirage's creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards. Cutting this file when it outgrows the size guard means
cutting at a section boundary, which keeps every section whole and keeps a test
findable from its round.
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
