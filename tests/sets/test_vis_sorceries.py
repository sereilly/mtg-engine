"""Per-card tests for Visions' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. A branch that added an import to a shared header loses it in the
mechanical "take ours, append the branch's block" merge — a ``NameError`` at
collection, found only after the merge is committed. A self-contained block
cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations
from engine import Game, PlayerState
from engine import Game as _W2G1sGame, PlayerState as _W2G1sPlayerState
from engine.models import Permanent as _W2G1sPermanent
from engine.card_loader import load_cards as _w2g1s_load, manifest_set_path as _w2g1s_path
from engine.cast_costs import additional_cost_for_line as _w2g1s_add_line
from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.card_loader import load_cards as _w2g2_load
from engine.card_loader import manifest_set_paths as _w2g2_paths
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile
# --- W3G4: Relentless Assault and CR 500.8's extra phases ---
import pytest as _w3g4_pytest
from engine import Game as _W3G4Game, PlayerState as _W3G4PlayerState
from engine.grammar import parse_line as _w3g4_parse_line
from engine.grammar.errors import GrammarError as _W3G4GrammarError
from engine.models import CardDefinition as _W3G4CardDefinition, Permanent as _W3G4Permanent
from engine.oracle import compile_card_oracle as _w3g4_compile
import pytest as _w3g2_pytest
from engine import Game as _W3G2sGame, PlayerState as _W3G2sPlayer
from engine.card_loader import (load_cards as _w3g2s_load,
                                manifest_set_paths as _w3g2s_paths)
from engine.grammar import parse_line as _w3g2s_parse
from engine.grammar.errors import (GrammarError as _W3G2sGrammarError,
                                   LoweringError as _W3G2sLoweringError)
from engine.grammar.lower import lower_ability as _w3g2s_lower
from engine.models import Permanent as _W3G2sPermanent
from engine.oracle import compile_card_oracle as _w3g2s_compile

def _w1g2_game():
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    return game
def test_summer_bloom_grants_three_more_land_drops_this_turn(set_pool):
    """"You may play up to three additional lands this turn." (CR 305.2.)

    Not a ``may`` wrapper: the word is the permission, not an offer taken at
    resolution, and wrapping it would put a yes/no prompt in front of a card
    that prints no decision.
    """
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]

    result = game.cast_from_hand(0, "Summer Bloom")
    assert result.supported, result.details
    game.resolve_stack()

    for played in range(4):
        assert game._may_play_another_land(0), f"land drop {played + 1} of 4"
        game.lands_played_this_turn[0] = played + 1
    assert not game._may_play_another_land(0), "one plus three, and no more"
def test_summer_bloom_grants_nothing_to_the_other_seat(set_pool):
    """"**You** may play…" — CR 109.5's controller, and nobody else."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.lands_played_this_turn[1] = 1
    assert not game._may_play_another_land(1)
def test_summer_bloom_s_grant_ends_with_the_turn(set_pool):
    """"…**this turn**." The record is cleared at the turn boundary beside the
    per-turn count it adds to."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.start_turn(0)

    game.lands_played_this_turn[0] = 1
    assert not game._may_play_another_land(0)
def test_two_summer_blooms_add_up(set_pool):
    """Two resolutions of one effect grant six, not three: a ceiling the second
    copy merely re-asserted would make it free."""
    game = _w1g2_game()
    bloom = set_pool("VIS")["Summer Bloom"]
    game.players[0].hand = [bloom, bloom]
    for _ in range(2):
        game.cast_from_hand(0, "Summer Bloom")
        game.resolve_stack()

    game.lands_played_this_turn[0] = 6
    assert game._may_play_another_land(0)
    game.lands_played_this_turn[0] = 7
    assert not game._may_play_another_land(0)
_W2G1S_LEA = {c.name: c for c in _w2g1s_load(_w2g1s_path("LEA"))}
def _w2g1s_scene(hand, swamps, opposing=()):
    p1 = _W2G1sPlayerState(name="A", hand=list(hand))
    p2 = _W2G1sPlayerState(name="B")
    game = _W2G1sGame(players=[p1, p2])
    game.enforce_mana_costs = False
    for _ in range(swamps):
        p1.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA["Swamp"]))
    for name in opposing:
        p2.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA[name]))
    return game, p1, p2
def test_infernal_harvest_returns_x_swamps_and_deals_that_much(set_pool):
    """CR 107.3a: an X in an **additional** cost is announced as the spell is
    cast, and Infernal Harvest's printed mana cost has no {X} in it at all —
    this clause is the only place its X lives.

    Before the cost was read the card dealt its damage for {1}{B} with no
    Swamp returned, which is the defect this whole block exists for.
    """
    game, caster, victim = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=3,
        opposing=("Mons's Goblin Raiders", "Hurloon Minotaur"),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=2, divided_targets=[(1, 0), (1, 1)],
    )

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Swamp"]
    assert [c.name for c in caster.hand] == ["Swamp", "Swamp"]
    # 1 damage each: the Goblin dies, the Minotaur survives.
    assert [p.card.name for p in victim.battlefield] == ["Hurloon Minotaur"]
def test_infernal_harvest_refuses_an_x_the_board_cannot_pay(set_pool):
    """CR 601.2h: three Swamps is no payment for an X of four, and the refusal
    costs the caster nothing."""
    game, caster, _ = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=2,
        opposing=("Hurloon Minotaur",),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=3, divided_targets=[(1, 0)],
    )

    assert not result.supported
    assert "CR 601.2h" in result.details
    assert len(caster.battlefield) == 2
    assert [c.name for c in caster.hand] == ["Infernal Harvest"]
def test_the_return_cost_reads_the_printed_destination():
    """The zone is part of the clause: the payment reaches one hand, and a
    sentence naming another destination refuses rather than being charged
    against it."""
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X Swamps you "
        "control to the graveyard."
    ) is None
    # …and an un-narrowed noun phrase is refused for the reason every other
    # counted cost's is: it would let the payment eat anything the caster has.
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X permanents you "
        "control to their owner's hand."
    ) is None
def _w2g2_catalog():
    return {card.name: card for card in _w2g2_load(_w2g2_paths(include_measured=True))}
def _w2g2_slot(player, permanent):
    return next(i for i, perm in enumerate(player.battlefield) if perm is permanent)
def _w2g2_peace_talks_board(set_pool):
    """Two seats, a creature each, and Peace Talks in the first one's hand."""
    catalog = _w2g2_catalog()
    bear = _W2G2Permanent(card=catalog["Grizzly Bears"])
    hill = _W2G2Permanent(card=catalog["Hill Giant"])
    p1 = _W2G2PlayerState(
        name="P1",
        battlefield=[bear],
        hand=[set_pool("VIS")["Peace Talks"], catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    p2 = _W2G2PlayerState(
        name="P2",
        battlefield=[hill],
        hand=[catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    game = _W2G2Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for player in (p1, p2):
        for perm in player.battlefield:
            perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    return game, bear, hill
def _w2g2_end_turn(game):
    seat = game.active_player_index
    game.resolve_end_step(seat)
    game.resolve_cleanup_step(seat)
def _w2g2_to_declare_attackers(game):
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
def test_peace_talks_compiles_both_clauses_over_one_window(set_pool):
    """"This turn and next turn, creatures can't attack, and players and
    permanents can't be the targets of spells or activated abilities."

    One leading duration over two effects, so the window is distributed to
    both. Two instructions rather than one fused kind, because they are
    enforced in two different places (CR 508.1c's declaration and CR 115.1's
    choice) -- and both carry the same two-turn count.
    """
    program = _w2g2_compile(set_pool("VIS")["Peace Talks"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["cant_attack_until_eot", "ban_targeting"]
    assert [step.payload["remaining_turns"] for step in steps] == [2, 2]
def test_peace_talks_stops_attacks_and_targeting_on_the_turn_it_resolves(set_pool):
    """Both clauses, watched as refusals.

    A restriction nothing enforces looks exactly like one that works, so each
    half is checked by an action being declined: a Lightning Bolt that never
    reaches its face, and a declaration the attack gate refuses.
    """
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)

    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported, game.log
    assert game.players[1].life == 20

    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]
def test_peace_talks_still_binds_the_opponent_on_the_next_turn(set_pool):
    """"And next turn" is the half a one-turn sweep would silently drop -- and
    it is the half the caster paid for, because the turn it resolves in is
    their own."""
    game, _bear, hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    _w2g2_end_turn(game)
    game.start_next_turn()

    assert game.active_player_index == 1
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 20
    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(1, [_w2g2_slot(game.players[1], hill)])[0]
def test_peace_talks_ends_after_the_second_cleanup(set_pool):
    """Two cleanups and no more: a window that outlived them would be a
    permanent effect the card never printed, which is the other direction and
    just as silent."""
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    for _ in range(2):
        _w2g2_end_turn(game)
        game.start_next_turn()

    assert game.targeting_bans == []
    assert game.attack_restrictions_until_eot == []
    assert game.active_player_index == 0
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17
    _w2g2_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]
def test_peace_talks_stops_an_aura_spell_too(set_pool):
    """An Aura spell is targeted (CR 115.1b) and its enchant line is the
    target, so the ban reaches it — where a creature spell with an
    enters-the-battlefield trigger is untouched, because that trigger's targets
    are chosen when it goes on the stack (CR 603.3d) and not at the cast.

    The two together are the line: gating a permanent spell on a spec it does
    not own would refuse to cast the creature at all.
    """
    catalog = _w2g2_catalog()
    game, _bear, _hill = _w2g2_peace_talks_board(set_pool)
    game.players[0].hand.extend([catalog["Pacifism"], set_pool("VIS")["Nekrataal"]])
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    aura = game.cast_from_hand(
        0, "Pacifism", target_player_index=1, target_permanent_index=0
    )
    assert not aura.supported, game.log

    assert game.cast_from_hand(0, "Nekrataal").supported, game.log
def test_peace_talks_stops_an_activated_ability_aimed_at_a_face(set_pool):
    """CR 602.2b routes an activation through CR 601.2c, so an ability that
    must choose a target and has none legal cannot be begun.

    Rod of Ruin is the shape the picker-side check cannot see: "deals 1 damage
    to any target" names no permanent when it is aimed at a player, so every
    gate keyed on a named permanent index let it through. A targetless mana
    ability is untouched -- the ban is about being chosen, not about acting.
    """
    catalog = _w2g2_catalog()
    game, _bear, _hill = _w2g2_peace_talks_board(set_pool)
    rod = _W2G2Permanent(card=catalog["Rod of Ruin"])
    birds = _W2G2Permanent(card=catalog["Birds of Paradise"])
    for perm in (rod, birds):
        perm.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(perm)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    refused = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)
    assert not refused.supported, game.log
    assert game.players[1].life == 20

    assert game.activate_permanent_ability(
        0, "Birds of Paradise", mana_color="G"
    ).supported, game.log
def _w3g4_bear(name="Grizzly"):
    return _W3G4CardDefinition(
        name=name,
        mana_cost="{1}{G}",
        cmc=2.0,
        type_line="Creature - Bear",
        oracle_text="",
        colors=("G",),
        color_identity=("G",),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear", "power": "2", "toughness": "2"},
    )
def _w3g4_board(set_pool, card_name="Relentless Assault"):
    """A board with one untapped attacker and the named spell in hand."""
    attacker = _W3G4Permanent(card=_w3g4_bear())
    attacker.metadata["summoning_sickness_turn"] = -99
    p1 = _W3G4PlayerState(name="P1", battlefield=[attacker],
                          hand=[set_pool("VIS")[card_name]])
    p2 = _W3G4PlayerState(name="P2", life=40)
    game = _W3G4Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, attacker
def _w3g4_phase_sequence(game, seat=0, limit=60, stop_at=None):
    """Drive the turn through the real steps, recording the phases it takes.

    The Rock Hydra test for a turn-structure change: a compiled program cannot
    show that an extra phase is *taken*, only that it was recorded - which is
    exactly the distinction the engine got wrong before this round. VIS is
    measured, so no running app can put the card on a board; this drives a Game
    directly and reads the sequence of phases out of it. Consecutive steps of
    one phase collapse to one entry, so a repeated phase name in the result is a
    second *phase*, never a second step.
    """
    seen = []

    def note():
        if not seen or seen[-1] != game.current_turn_phase:
            seen.append(game.current_turn_phase)

    note()
    for _ in range(limit):
        phase, step = game.current_turn_phase, game.current_step
        if phase in ("precombat_main", "postcombat_main"):
            game._close_current_priority_step()
            game.enter_next_turn_phase(phase)
        elif phase == "combat":
            if step == "declare_attackers" and not game.combat_attackers_locked:
                ready = [
                    i for i, p in enumerate(game.players[seat].battlefield)
                    if p.is_creature and not p.tapped
                ]
                if ready:
                    game.declare_attackers(seat, ready, 1 - seat)
                else:
                    game.combat_attackers_locked = True
            game.advance_combat_phase()
        elif phase == "ending":
            if step != "end":
                break
            game.close_end_step()
            game.resolve_cleanup_step(seat)
        else:
            break
        note()
        if stop_at is not None and game.current_turn_phase == stop_at:
            break
        if (game.current_turn_phase, game.current_step) == (phase, step):
            break
    return seen
def test_relentless_assault_is_supported(set_pool):
    card = set_pool("VIS")["Relentless Assault"]
    program = _w3g4_compile(card)

    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == ["untap_all_matching", "grant_extra_phases"]
    assert steps[1].payload == {
        "after": "main", "phases": ("combat", "postcombat_main"),
    }
def test_relentless_assault_gives_a_second_combat_phase(set_pool):
    """Cast in the postcombat main phase: the attacker untaps and swings again."""
    game, attacker = _w3g4_board(set_pool)
    game.start_turn(0)

    sequence = _w3g4_phase_sequence(game)

    assert sequence.count("combat") == 1, sequence
    assert game.players[1].life == 38

    game, attacker = _w3g4_board(set_pool)
    game.start_turn(0)
    # Run the turn's own combat first, then cast in the postcombat main phase.
    game._close_current_priority_step()
    game.enter_next_turn_phase("precombat_main")
    _w3g4_phase_sequence(game, stop_at="postcombat_main")
    assert game.current_turn_phase == "postcombat_main"
    assert attacker.tapped
    assert game.cast_from_hand(0, "Relentless Assault").supported, game.log
    game._resolve_priority_window()

    assert not attacker.tapped
    sequence = _w3g4_phase_sequence(game)
    assert "combat" in sequence, sequence
    # Two attacks for two, out of forty.
    assert game.players[1].life == 36, game.log
def test_relentless_assault_cast_precombat_keeps_the_turns_own_combat(set_pool):
    """CR 500.8: the extra phases go *directly after* this main phase.

    The rest of the turn still happens behind them, which is the case a
    phase-name-keyed record could not express - it filed "a main phase after
    combat" and the turn's own combat phase ate it, so the turn lost a combat
    instead of gaining one.
    """
    game, attacker = _w3g4_board(set_pool)
    game.start_turn(0)
    assert game.cast_from_hand(0, "Relentless Assault").supported, game.log
    game._resolve_priority_window()

    assert game.turn_phases_remaining == [
        "combat", "postcombat_main", "combat", "postcombat_main", "ending",
    ]
    phases = _w3g4_phase_sequence(game)
    assert phases.count("combat") == 2, phases
    assert phases.count("postcombat_main") == 2, phases
    assert phases[-1] == "ending"
def test_relentless_assault_refuses_a_sentence_it_cannot_read():
    """The production commits once "after this" matches, so a tail it does not
    know fails the line rather than creating half the printed run."""
    for line in (
        "After this main phase, there is an additional beginning phase.",
        "After this main phase, there is a combat phase.",
        "After this main phase there is an additional combat phase.",
        "After this main phase, there is an additional combat phase followed by.",
        "After this main phase, there is an additional combat phase "
        "followed by an additional main phase and you draw a card.",
    ):
        with _w3g4_pytest.raises(_W3G4GrammarError):
            _w3g4_parse_line(line)
def test_the_extra_phase_production_reads_the_shapes_the_template_prints():
    """One production, not one card: "after this combat phase" and a single
    additional phase are the same sentence with different words."""
    assert _w3g4_parse_line(
        "After this combat phase, there is an additional combat phase."
    )
    assert _w3g4_parse_line(
        "After this phase, there is an additional main phase."
    )

_W3G2S_POOL: dict = {}
for _w3g2s_path in _w3g2s_paths(include_measured=True):
    for _w3g2s_card in _w3g2s_load(_w3g2s_path):
        _W3G2S_POOL.setdefault(_w3g2s_card.name, _w3g2s_card)
def _w3g2s_creature(name: str = "Grizzly Bears") -> "_W3G2sPermanent":
    perm = _W3G2sPermanent(card=_W3G2S_POOL[name])
    perm.metadata["summoning_sickness_turn"] = -99
    return perm
def _w3g2s_cast(library: list[str], creatures: int = 2):
    """Song of Blood cast and resolved, with *creatures* attackers available."""
    game = _W3G2sGame(players=[_W3G2sPlayer(name="P0"), _W3G2sPlayer(name="P1")])
    game.enforce_mana_costs = False
    board = [_w3g2s_creature() for _ in range(creatures)]
    game.players[0].battlefield = list(board)
    game.players[0].hand = [_W3G2S_POOL["Song of Blood"]]
    game.players[0].library = [_W3G2S_POOL[n] for n in library]
    game._sync_control()
    game.active_player_index = 0
    game.cast_from_hand(0, "Song of Blood")
    game.resolve_stack()
    return game, board
def _w3g2s_attack(game, indices):
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    accepted, _ = game.declare_attackers(0, indices, defending_player_index=1)
    assert accepted, game.log
    game.resolve_stack()
def test_w3g2_song_of_blood_compiles_the_second_sentence_as_a_delayed_ability():
    program = _w3g2s_compile(_W3G2S_POOL["Song of Blood"])
    assert program.supported, program.reason
    (sequence,) = program.instructions
    mill, delay = sequence.payload["steps"]
    # One resolution, in printed order — never two card lines. Split apart, the
    # trigger would be an ability of the sorcery rather than something its
    # resolution creates, and the mill whose record it reads would not have
    # happened yet.
    assert mill.kind == "mill_target_player"
    assert mill.payload["amount"] == 4
    assert delay.kind == "create_delayed_trigger"
    assert delay.payload["event"] == "creatures_attack"
    # CR 603.7b: "this turn" is a stated duration, so it fires every time.
    assert delay.payload["once"] is False
    assert delay.payload["duration"] == "end_of_turn"
    assert delay.payload["instruction"].payload["x_from_count"] == {
        "recorded_cards": "milled_this_way",
        "filter": {"type_filter": "creature"},
    }
@_w3g2_pytest.mark.parametrize(
    "library, expected_power",
    [
        (["Grizzly Bears"] * 4 + ["Forest"] * 3, 6),
        (["Grizzly Bears", "Forest", "Grizzly Bears", "Forest", "Forest"], 4),
        (["Forest"] * 6, 2),
    ],
)
def test_w3g2_song_of_blood_sizes_the_pump_by_the_creature_cards_milled(
    library, expected_power
):
    game, board = _w3g2s_cast(library)
    attacker, stayed_home = board
    _w3g2s_attack(game, [0])
    assert attacker.effective_power == expected_power, game.log
    # The boost is the attacker's alone — the trigger fires once per attacking
    # creature, with that creature as its source.
    assert stayed_home.effective_power == 2, game.log
    # A pump, not a counter: toughness is untouched.
    assert attacker.effective_toughness == 2, game.log
def test_w3g2_song_of_blood_pumps_every_attacker_that_turn():
    game, board = _w3g2s_cast(["Grizzly Bears"] * 4 + ["Forest"] * 3, creatures=2)
    _w3g2s_attack(game, [0, 1])
    assert [perm.effective_power for perm in board] == [6, 6], game.log
def test_w3g2_song_of_blood_counts_the_record_and_not_the_graveyard():
    """The pile holds whatever else has gone there; the words say this way."""
    game, board = _w3g2s_cast(["Forest"] * 6)
    # Four creature cards in the graveyard that this spell never milled.
    game.players[0].graveyard.extend([_W3G2S_POOL["Grizzly Bears"]] * 4)
    _w3g2s_attack(game, [0])
    assert board[0].effective_power == 2, game.log
def test_w3g2_song_of_blood_expires_with_the_turn():
    """CR 603.7b's stated duration is "this turn", so the cleanup step is what
    takes the ability away — an attack on a later turn is pumped by nothing."""
    game, board = _w3g2s_cast(["Grizzly Bears"] * 4 + ["Forest"] * 3)
    assert game.delayed_triggers, game.log
    game.resolve_cleanup_step(0)
    assert game.delayed_triggers == [], game.log
    game.begin_turn_bookkeeping(0)
    _w3g2s_attack(game, [0])
    assert board[0].effective_power == 2, game.log
def test_w3g2_a_trailing_delayed_trigger_needs_the_record_it_reads():
    """The two halves meet only at the splitter, so the producer gate lives
    there: a back-reference with no mill in front of it would read an empty
    record and pump nothing while the card reported supported."""
    from engine.oracle import _split_trailing_delayed_trigger

    assert _split_trailing_delayed_trigger(
        "Mill four cards. Whenever a creature attacks this turn, it gets +1/+0 "
        "until end of turn for each creature card put into your graveyard "
        "this way.",
        "Song of Blood",
    ) is not None
    assert _split_trailing_delayed_trigger(
        "Draw a card. Whenever a creature attacks this turn, it gets +1/+0 "
        "until end of turn for each creature card put into your graveyard "
        "this way.",
        None,
    ) is None
    # A head the grammar cannot read is no split either.
    assert _split_trailing_delayed_trigger(
        "Blorp the frobnicator. Whenever a creature attacks this turn, it gets "
        "+1/+0 until end of turn.",
        None,
    ) is None
def test_w3g2_the_milled_count_refuses_what_a_card_record_cannot_answer():
    # "Creature" without the printed word "card" is a phrase about permanents,
    # and a mill puts cards into a graveyard.
    with _w3g2_pytest.raises(_W3G2sLoweringError):
        _w3g2s_lower(_w3g2s_parse(
            "It gets +1/+0 until end of turn for each creature put into your "
            "graveyard this way."
        ))
    # No duration would be a continuous bonus sized by a frozen record.
    with _w3g2_pytest.raises((_W3G2sLoweringError, _W3G2sGrammarError)):
        _w3g2s_lower(_w3g2s_parse(
            "It gets +1/+0 for each creature card put into your graveyard "
            "this way."
        ))
    # A subject that is not the ability's own source has nothing to boost.
    with _w3g2_pytest.raises(_W3G2sLoweringError):
        _w3g2s_lower(_w3g2s_parse(
            "Target creature gets +1/+0 until end of turn for each creature "
            "card put into your graveyard this way."
        ))
def test_w3g2_the_milled_clause_must_consume_its_whole_line():
    for line in (
        "It gets +1/+0 until end of turn for each creature card put into your "
        "graveyard.",
        "It gets +1/+0 until end of turn for each creature card put into a "
        "graveyard this way.",
        "It gets +1/+0 until end of turn for each creature card put into your "
        "graveyard this way and then some.",
    ):
        with _w3g2_pytest.raises(_W3G2sGrammarError):
            _w3g2s_parse(line)
def test_w3g2_battle_cry_still_reads_its_delayed_trigger_whole_line():
    """The splitter is tried *after* the whole-line table, so a card whose
    entire line is the delayed clause keeps the reading it had."""
    program = _w3g2s_compile(_W3G2S_POOL["Battle Cry"])
    assert program.supported, program.reason
    kinds = [instruction.kind for instruction in program.instructions]
    assert kinds == ["untap_all_matching", "create_delayed_trigger"], kinds
