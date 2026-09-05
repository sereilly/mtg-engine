"""Per-card tests for Visions' instants.

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
from engine.models import CardDefinition, Permanent
from engine.divided_damage import DIVIDED_TARGETS
from engine.game_types import OracleExecutionContext
from engine.oracle import compile_card_oracle
from engine.shields import shields_on
from tests.helpers import _damage_dealt, _nosick
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from engine.card_loader import load_cards as _w2g1_load, manifest_set_path as _w2g1_path
from engine.oracle import compile_card_oracle as _w2g1_compile
from engine.alternative_costs import alternative_cost_for_line as _w2g1_alt_line
from engine.cast_costs import additional_cost_for_line as _w2g1_add_line
from engine import Game as _W2G5Game, PlayerState as _W2G5Player
from engine.grammar import compile_line as _w2g5_compile
from engine.grammar.errors import GrammarError as _W2G5GrammarError
from engine.grammar.parser import parse_line as _w2g5_parse
from engine.oracle import compile_card_oracle as _w2g5_program

def _w1g2_game(*battlefields):
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(bf))
        for i, bf in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    return game
def _w1g2_creature(name: str, keywords=()) -> CardDefinition:
    text = "\n".join(k.title() for k in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(
            k.title() for k in keywords
        ),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    )
def _w1g2_tide_board(set_pool):
    """A phaser and a plain creature out; a third creature already phased out."""
    phaser = Permanent(card=_w1g2_creature("Phaser", keywords=("phasing",)))
    plain = Permanent(card=_w1g2_creature("Plain"))
    away = Permanent(card=_w1g2_creature("Away"))
    game = _w1g2_game([phaser, plain], [])
    game.players[0].phased_out.append(away)
    away.metadata["phased_out"] = True
    game.players[0].hand = [set_pool("VIS")["Time and Tide"]]
    game._recompute_continuous_effects()
    return game, phaser, plain, away
def test_time_and_tide_swaps_both_sets_of_creatures(set_pool):
    """"Simultaneously, all phased-out creatures phase in and all creatures
    with phasing phase out." (CR 702.26.)"""
    game, phaser, plain, away = _w1g2_tide_board(set_pool)

    result = game.cast_from_hand(0, "Time and Tide")
    assert result.supported, result.details
    game.resolve_stack()

    assert game.is_on_battlefield(away), "the phased-out creature came back"
    assert not game.is_on_battlefield(phaser), "the phaser went away"
    assert game.is_on_battlefield(plain), "no phasing, so it stayed"
def test_time_and_tide_reads_both_sets_before_it_applies_either(set_pool):
    """The printed adverb, and the only thing it buys.

    A creature with phasing that is *already* phased out comes back — and must
    not be swept straight out again by the sentence's other half, which read the
    board before it arrived. Applying the two halves in order gets this wrong in
    a way nothing else would notice: the creature simply never returns.
    """
    game, phaser, _plain, _away = _w1g2_tide_board(set_pool)
    # Send the phaser away first, so the incoming half is what brings it back.
    game.phase_out_permanent(phaser)
    assert phaser in game.players[0].phased_out

    game.cast_from_hand(0, "Time and Tide")
    game.resolve_stack()

    assert game.is_on_battlefield(phaser), (
        "it was phased out when the sets were read, so it phases in and stays"
    )
def test_solfatara_stops_its_target_playing_a_land_this_turn(set_pool):
    """"Target player can't play lands this turn." (CR 305.1.)

    The card reported **supported** before this round on its second line alone
    ("Draw a card at the beginning of the next turn's upkeep"), which is what
    made it invisible to the census: a card is supported when any of its lines
    is. Its first line produced no instruction at all, so it also had no cast
    picker — the client sent a bare cast and the engine refused it.
    """
    game = _w1g2_game([], [])
    game.players[0].hand = [set_pool("VIS")["Solfatara"]]
    game.players[1].hand = [set_pool("LEA")["Forest"]]
    assert game._may_play_another_land(1)

    result = game.cast_from_hand(0, "Solfatara", target_player_index=1)
    assert result.supported, result.details
    game.resolve_stack()

    assert not game._may_play_another_land(1)
    assert game._may_play_another_land(0), "only the target"
def test_solfatara_s_prohibition_ends_with_the_turn(set_pool):
    """"…**this turn**." The record is cleared at the turn boundary, beside the
    land-drop count it modifies."""
    game = _w1g2_game([], [])
    game.players[0].hand = [set_pool("VIS")["Solfatara"]]
    game.cast_from_hand(0, "Solfatara", target_player_index=1)
    game.resolve_stack()
    assert not game._may_play_another_land(1)

    game.start_turn(1)

    assert game._may_play_another_land(1)
def test_solfatara_offers_a_player_picker(set_pool):
    """The other half of the Roots class. ``derive_cast_spec`` reads the
    *compiled program*, so a line that lowered to nothing left the card with no
    picker — which is the exact value the client tests before asking for a
    target."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("VIS")["Solfatara"]
    spec = derive_cast_spec(card, compile_card_oracle(card))
    assert spec is not None
    assert spec.get("kind") == "player"
def _w1g2_charm_board(set_pool, *, interactive=frozenset()):
    """A Forest for the caster, an Island and a Mountain for the opponent."""
    lea = set_pool("LEA")
    forest = Permanent(card=lea["Forest"])
    island = Permanent(card=lea["Island"])
    mountain = Permanent(card=lea["Mountain"])
    game = _w1g2_game([forest], [island, mountain])
    game.players[0].hand = [set_pool("VIS")["Vision Charm"]]
    game.interactive_seats = set(interactive)
    game._recompute_continuous_effects()
    return game, forest, island, mountain
def test_vision_charm_swaps_every_land_of_the_chosen_type(set_pool):
    """"Choose a land type and a basic land type. Each land of the first chosen
    type becomes the second chosen type until end of turn." (CR 305.7,
    CR 609.3.)

    Two printed sentences and one decision: the second names its parameters by
    ordinal, so neither half is a sentence on its own. The mode was the card's
    only unsupported one — its mill and its "target artifact phases out" already
    worked, which is what the brief's `expected 'card'` refusal was hiding.
    """
    game, forest, island, mountain = _w1g2_charm_board(set_pool, interactive={0})

    result = game.cast_from_hand(0, "Vision Charm", mode_index=1)
    assert result.supported, result.details
    game.resolve_stack()

    assert game.confirm_land_type_swap(0, "island", "forest") is True
    game._settle()

    assert island.basic_land_types == ("forest",), "CR 305.7 replaces, not adds"
    assert forest.basic_land_types == ("forest",)
    assert mountain.basic_land_types == ("mountain",), "only the chosen type"
def test_vision_charm_s_swap_wears_off_in_the_cleanup_step(set_pool):
    """"…**until end of turn**." The duration is read rather than defaulted:
    without the words the change would last as long as the game does
    (CR 611.2), which is a different card."""
    game, _forest, island, _mountain = _w1g2_charm_board(set_pool, interactive={0})
    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()
    game.confirm_land_type_swap(0, "island", "forest")
    assert island.basic_land_types == ("forest",)

    game.resolve_cleanup_step(0)

    assert island.basic_land_types == ("island",)
def test_vision_charm_refuses_a_nonbasic_second_type(set_pool):
    """The two halves draw from different catalogs, and the printed adjective
    says which: "a land type" is all of CR 205.3i's and "a basic land type" is
    the five. An answer outside either is refused rather than repaired."""
    game, _forest, _island, _mountain = _w1g2_charm_board(set_pool, interactive={0})
    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()

    assert game.confirm_land_type_swap(0, "island", "desert") is False, (
        "Desert is a land type but not a basic one"
    )
    assert game.confirm_land_type_swap(0, "wizard", "forest") is False
    assert game.confirm_land_type_swap(0, "island", "forest") is True
def test_vision_charm_takes_a_real_default_for_a_seat_that_is_not_asked(set_pool):
    """A headless or AI seat is never blocked, and never gets "the first word in
    the catalog": the default is the pair that changes the most colours of mana
    on the other side of the table, computed off the board and deterministic so
    a seeded run reproduces."""
    game, forest, island, mountain = _w1g2_charm_board(set_pool)

    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game._settle()

    assert island.basic_land_types == ("forest",)
    assert mountain.basic_land_types == ("mountain",)
    assert forest.basic_land_types == ("forest",)
def test_vision_charm_s_other_two_modes_still_do_what_they_did(set_pool):
    """The mode this round added is the third of three, and the differential's
    reason for existing: a card whose modes are compiled together is a card
    whose other modes a new production can quietly move."""
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("VIS")["Vision Charm"])
    kinds = [mode.instruction.kind for mode in program.modes]
    assert kinds == [
        "mill_target_player",
        "swap_land_types_until_eot",
        "phase_out_target",
    ]
def _w1g3_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game
def _w1g3_bear(name="Bear", power=2, toughness=2, colors=()):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Bear",
        oracle_text="",
        colors=tuple(colors),
        color_identity=tuple(colors),
        keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature — Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )
def _w1g3_flyer(name):
    card = _w1g3_bear(name)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Bird",
        oracle_text="Flying", colors=(), color_identity=(),
        keywords=("flying",), produced_mana=(),
        raw={
            "name": name, "type_line": "Creature — Bird",
            "power": "2", "toughness": "2",
        },
    )
def _w1g3_resolve(game, card, *, caster, target=None, choices=None,
                  source_permanent=None, target_permanent_index=None):
    """Run every instruction of *card*'s compiled program, once."""
    program = compile_card_oracle(card)
    context = OracleExecutionContext(
        card=card, caster=caster, target=target or caster,
        source_permanent=source_permanent,
        target_permanent_index=target_permanent_index,
        choices=choices or {},
    )
    for instruction in program.instructions:
        game._execute_oracle_instruction(instruction, context)
    return context
def test_remedy_splits_its_five_points_the_way_its_caster_announced(set_pool):
    """"Prevent the next 5 damage that would be dealt this turn to any number
    of targets, **divided as you choose**."

    CR 615.7's point pool split across CR 601.2d's announced targets. The test
    is the whole point of the round: the division has to reach the *shields*,
    and a shield armed at the wrong size looks identical to one armed right
    until damage arrives. So each recipient is dealt more than its share and
    what survives is read back.
    """
    game = _w1g3_duel()
    p1, p2 = game.players
    bear = _nosick(Permanent(card=_w1g3_bear()))
    p1.battlefield.append(bear)

    _w1g3_resolve(
        game, set_pool("VIS")["Remedy"], caster=p1,
        choices={DIVIDED_TARGETS: [(0, 0, 3), (1, None, 2)]},
    )

    # 3 points on the bear: a 5-damage hit leaves 2.
    assert _damage_dealt(game, bear, 5) == 2
    # 2 points on the opponent's face: a 5-damage hit leaves 3.
    assert _damage_dealt(game, p2, 5) == 3
def test_remedy_falls_back_to_an_even_split_when_nobody_announced_one(set_pool):
    """A seat with no way to be asked — the AI, a scripted duel — announces no
    division, and ``engine/divided_damage.py`` gives it the even one. Read here
    rather than trusted, because the fallback lives in the module the burn
    spells share and this is the first shield to use it.
    """
    game = _w1g3_duel()
    p1, p2 = game.players

    _w1g3_resolve(
        game, set_pool("VIS")["Remedy"], caster=p1,
        choices={DIVIDED_TARGETS: [(0, None), (1, None)]},
    )

    assert _damage_dealt(game, p1, 5) == 3
    assert _damage_dealt(game, p2, 5) == 3
def test_honorable_passage_sends_a_red_source_s_damage_back_at_its_controller(set_pool):
    """"…prevent that damage. **If damage from a red source is prevented this
    way, this spell deals that much damage to the source's controller.**"

    Two halves and the second is the card: the shield absorbing is not evidence
    that the rider fired, and the rider firing on a *green* source would be a
    card doing more than it prints. Both are asserted, in one game.
    """
    game = _w1g3_duel()
    p1, p2 = game.players
    red_source = _nosick(Permanent(card=_w1g3_bear("Fire Bear", colors=("R",))))
    p2.battlefield.append(red_source)

    _w1g3_resolve(
        game, set_pool("VIS")["Honorable Passage"], caster=p1, target=p1,
    )
    assert shields_on(p1), "the shield goes around what the spell targeted"

    before = p2.life
    assert _damage_dealt(game, p1, 4, source=red_source) == 0
    assert p2.life == before - 4, "the red source's controller takes it back"
def test_honorable_passage_prevents_a_green_source_and_pays_nobody(set_pool):
    """The condition is rechecked against the source when the damage would be
    dealt (CR 615.9's reading applied to the rider): a source of the wrong
    colour is still *prevented* — the sentence before the condition is
    unconditional — and nobody is dealt anything for it."""
    game = _w1g3_duel()
    p1, p2 = game.players
    green_source = _nosick(Permanent(card=_w1g3_bear("Leaf Bear", colors=("G",))))
    p2.battlefield.append(green_source)

    _w1g3_resolve(
        game, set_pool("VIS")["Honorable Passage"], caster=p1, target=p1,
    )

    before = p2.life
    assert _damage_dealt(game, p1, 4, source=green_source) == 0
    assert p2.life == before
def test_rock_slide_offers_only_creatures_in_combat_and_without_flying(set_pool):
    """"…among any number of target **attacking or blocking creatures without
    flying**."

    The union is the narrowing this round bought, and what it is worth is the
    *picker*: an idle creature and a flying attacker are not legal targets, and
    before ``any_states`` was promised the whole card was refused rather than
    narrowed. Asked of ``legality``, which is the list the engine and the web
    picker both read.
    """
    from engine.targeting import derive_cast_spec

    game = _w1g3_duel()
    p1, p2 = game.players
    attacker = _nosick(Permanent(card=_w1g3_bear("Ground Attacker")))
    idle = _nosick(Permanent(card=_w1g3_bear("Idle Bear")))
    flyer = _nosick(Permanent(card=_w1g3_flyer("Flying Attacker")))
    p2.battlefield.extend([attacker, idle, flyer])
    attacker.attacking = True
    flyer.attacking = True

    rock_slide = set_pool("VIS")["Rock Slide"]
    spec = derive_cast_spec(rock_slide, compile_card_oracle(rock_slide))
    assert spec["kind"] == "divided", "the caster divides X among its targets"

    offered = {
        entry.get("name")
        for entry in game._enumerate_targets(0, rock_slide, spec, for_cast=True)
        if entry.get("name")
    }
    assert "Ground Attacker" in offered
    assert "Idle Bear" not in offered, "not in combat"
    assert "Flying Attacker" not in offered, "in combat, and excluded by name"
def test_rock_slide_divides_x_among_the_creatures_its_caster_named(set_pool):
    """The Rock Hydra step for the other half: the targets are offered, and the
    damage announced for each one is the damage each one takes."""
    game = _w1g3_duel()
    p1, p2 = game.players
    big = _nosick(Permanent(card=_w1g3_bear("Big Attacker", power=1, toughness=5)))
    small = _nosick(Permanent(card=_w1g3_bear("Small Blocker", power=1, toughness=5)))
    p2.battlefield.extend([big, small])
    big.attacking = True
    small.blocking_attacker_index = 0

    _w1g3_resolve(
        game, set_pool("VIS")["Rock Slide"], caster=p1, target=p2,
        choices={DIVIDED_TARGETS: [(1, 0, 3), (1, 1, 1)]},
    )

    assert big.damage_marked == 3
    assert small.damage_marked == 1
def test_simoon_burns_only_the_opponent_it_named(set_pool):
    """"Simoon deals 1 damage to **each creature target opponent controls**."

    A supported card no player could cast — the picker offered nothing, so the
    client sent a bare cast and the engine refused it (the Roots class). And
    behind that, a second failure the picker finding could not see: the matcher
    read "target opponent" as *any* opponent, so with three seats at the table
    the spell burned two boards where the card names one.

    Three seats, therefore, because two cannot tell the two readings apart.
    """
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    named = _nosick(Permanent(card=_w1g3_bear("Named Opponent's Bear")))
    other = _nosick(Permanent(card=_w1g3_bear("Other Opponent's Bear")))
    mine = _nosick(Permanent(card=_w1g3_bear("My Own Bear")))
    p2.battlefield.append(named)
    p3.battlefield.append(other)
    p1.battlefield.append(mine)

    _w1g3_resolve(game, set_pool("VIS")["Simoon"], caster=p1, target=p2)

    assert named.damage_marked == 1
    assert other.damage_marked == 0, "the opponent the spell did not name"
    assert mine.damage_marked == 0, "and never the caster's own creatures"
def test_simoon_asks_for_the_opponent_it_names(set_pool):
    """The picker half of the same finding, asserted separately: the cast spec
    is a player prompt that excludes the caster (CR 115.4), which is what makes
    the resolution above reachable from a client at all."""
    from engine.targeting import derive_cast_spec

    simoon = set_pool("VIS")["Simoon"]
    spec = derive_cast_spec(simoon, compile_card_oracle(simoon))

    assert spec == {"kind": "player", "opponents_only": True}
def test_miraculous_recovery_counters_the_permanent_it_made(set_pool):
    """"Return target creature card from your graveyard to the battlefield.
    Put a +1/+1 counter on **it**."

    The pronoun names a permanent that did not exist when the spell was cast —
    the target is a *card in a graveyard* — so the placement reads what the
    reanimation recorded rather than the ability's own target. Substituting the
    earlier sentence's target spec, which the counter rider did
    unconditionally, hands the placement a graveyard-scoped noun phrase and the
    line refuses at "no handler reads a filter scoped to the graveyard". The
    grant rider one function away had taken the right branch since Dreams of
    the Dead, so the same printed shape compiled or refused depending only on
    whether the second sentence said "gains" or "put".
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Miraculous Recovery"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "reanimate_creature", "add_counter_to_target",
    ]
    # The counter reads the reanimation's record, not a target.
    assert steps[1].payload == {
        "counter": "+1/+1", "permanents_from": "reanimated_permanents",
    }

    game = Game(players=[
        PlayerState(
            name="P1", hand=[vis["Miraculous Recovery"]],
            graveyard=[lea["Grizzly Bears"], lea["Black Lotus"]],
            library=[lea["Island"]] * 6,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert game.cast_from_hand(
        0, "Miraculous Recovery", target_player_index=0,
    ).supported
    game.resolve_stack()

    returned = list(game.controlled_by(game.players[0]))
    assert [p.card.name for p in returned] == ["Grizzly Bears"]
    assert (returned[0].effective_power, returned[0].effective_toughness) == (3, 3)
    assert "Grizzly Bears" not in [c.name for c in game.players[0].graveyard]
def test_tithe_offers_the_second_search_only_when_the_condition_holds(set_pool):
    """"Search your library for a Plains card. If target opponent controls more
    lands than you, you may search your library for an additional Plains card.
    Reveal those cards, put them into your hand, then shuffle."

    Three printed sentences and one effect (CR 701.23h), which is why the first
    sentence has no destination clause of its own and the ordinary search
    production refused it at "expected 'put'". The condition and the optional
    second search both already lowered; what was missing was only a reading of
    the three sentences together.

    And a **picker** finding on top of the parse one, in the opposite direction
    from usual: the instance of the word "target" is in the *condition*, so a
    spec derived from the instructions' arms alone was None — the exact value
    the client tests to decide whether to ask for a target.
    """
    from engine.targeting import derive_cast_spec

    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Tithe"])
    assert program.supported, program.reason
    assert derive_cast_spec(vis["Tithe"], program) == {
        "kind": "player", "opponents_only": True,
    }

    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["search_library", "if_then"]
    assert steps[1].payload["condition"]["op"] == "more_than_you"
    assert steps[1].payload["then"][0].kind == "may"

    def rig(opponent_lands):
        from engine.models import Permanent

        game = Game(players=[
            PlayerState(
                name="P1", hand=[vis["Tithe"]],
                library=[lea["Island"], lea["Plains"], lea["Plains"], lea["Forest"]],
            ),
            PlayerState(
                name="P2", library=[lea["Island"]] * 4,
                battlefield=[
                    Permanent(card=lea["Mountain"]) for _ in range(opponent_lands)
                ],
            ),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game._settle()
        return game

    def play(game, *, take_the_offer):
        game.cast_from_hand(0, "Tithe", target_player_index=1)
        game.resolve_stack()
        for _ in range(6):
            if not game.pending_choices:
                break
            pending = game.pending_choices[0]
            if pending.kind == "search_library":
                index = next(
                    (
                        i for i, card in enumerate(game.players[0].library)
                        if card.name == "Plains"
                    ),
                    None,
                )
                if index is None:
                    game.decline_search_library(0)
                else:
                    game.confirm_search_library(0, index)
            else:
                game.resolve_pending_choice(
                    pending.kind, 0, accept=take_the_offer,
                )
            game.resolve_stack()
        return [card.name for card in game.players[0].hand]

    # Behind on lands: the offer is made and taking it finds the second Plains.
    assert play(rig(2), take_the_offer=True) == ["Plains", "Plains"]
    # Declining is a legal answer and leaves the second find unmade.
    assert play(rig(2), take_the_offer=False) == ["Plains"]
    # Ahead on lands: the condition fails and no second offer is even made.
    assert play(rig(0), take_the_offer=True) == ["Plains"]
def test_foreshadow_draws_only_when_the_named_card_is_the_one_milled(set_pool):
    """"Choose a card name, then target opponent mills a card. If a card with
    the chosen name was milled this way, you draw a card."

    A **supported** card no player could cast: its only compiled instruction
    was the delayed draw on the second printed line, so ``derive_cast_spec``
    answered None and the client sent a bare cast the engine then refused. Two
    of its three sentences were unclaimed by ``parse_coverage`` as well, which
    is the pair of instruments that sees this class and the support census that
    does not.

    The name is chosen **before** the mill and the prompt suspends the
    resolution (CR 608.2, CR 117.3b): a seat that saw the milled card before
    naming would be choosing with information the card does not give them.
    """
    from engine.targeting import derive_cast_spec

    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Foreshadow"])
    assert program.supported, program.reason
    assert derive_cast_spec(vis["Foreshadow"], program) == {
        "kind": "player", "opponents_only": True,
    }
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_card_name", "mill_target_player", "if_then",
    ]
    assert steps[2].payload["condition"] == {"kind": "chosen_name_milled_this_way"}

    def play(guess):
        game = Game(players=[
            PlayerState(
                name="P1", hand=[vis["Foreshadow"]], library=[lea["Island"]] * 6,
            ),
            PlayerState(name="P2", library=[lea["Black Lotus"], lea["Forest"]]),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        assert game.cast_from_hand(
            0, "Foreshadow", target_player_index=1,
        ).supported
        game.resolve_stack()
        pending = game.pending_choices[0]
        assert pending.kind == "choose_card_name"
        # The mill has not happened yet: naming after seeing the card would be
        # a different game.
        assert game.players[1].graveyard == []
        game.confirm_choose_card_name(0, guess)
        game.resolve_stack()
        return game

    hit = play("Black Lotus")
    assert [c.name for c in hit.players[0].hand] == ["Island"]
    assert [c.name for c in hit.players[1].graveyard] == ["Black Lotus"]

    miss = play("Shivan Dragon")
    assert miss.players[0].hand == []
    assert [c.name for c in miss.players[1].graveyard] == ["Black Lotus"]
_W2G1_LEA = {c.name: c for c in _w2g1_load(_w2g1_path("LEA"))}
def _w2g1_duel(hand, *, board=(), enforce=True):
    """A duel with *hand* in seat 0 and *board* (LEA card names) under it.

    Costs on by default: the whole subject of this block is which price is
    paid, and a game that enforces none cannot tell two prices apart.
    """
    p1 = _W2G1PlayerState(name="A", hand=list(hand))
    p2 = _W2G1PlayerState(name="B")
    game = _W2G1Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    for name in board:
        p1.battlefield.append(_W2G1Permanent(card=_W2G1_LEA[name]))
    return game, p1, p2
def test_fireblast_is_cast_by_sacrificing_two_mountains(set_pool):
    """CR 118.9's alternative cost, with the price leaving the board.

    Fireblast reported ``supported`` on its damage line for the whole of
    wave 1 and its defining sentence was claimed by nobody — so it was
    castable only for {4}{R}{R}, and the cycle's famous free burn did not
    exist. "The cost parsed" is exactly the evidence that was wrong, so what
    is asserted here is the board.
    """
    card = set_pool("VIS")["Fireblast"]
    game, caster, victim = _w2g1_duel(
        [card], board=("Mountain", "Mountain", "Mountain"),
    )

    result = game.cast_from_hand(
        0, "Fireblast", alternative_cost=True, target_player_index=1,
    )

    assert result.supported, result.details
    assert victim.life == 16
    assert [p.card.name for p in caster.battlefield] == ["Mountain"]
    assert [c.name for c in caster.graveyard].count("Mountain") == 2
    # CR 118.9c: the alternative replaces the *payment*, never the mana cost.
    assert not any(caster.mana_pool.values())
    assert card.mana_cost == "{4}{R}{R}"
def test_fireblast_needs_two_mountains_not_one(set_pool):
    """CR 601.2h: the *count* is what makes this unpayable.

    A gate that asked only whether a Mountain existed would admit the
    announcement and then charge one — a spell cast for nothing, since the
    mana payment has already been skipped.
    """
    card = set_pool("VIS")["Fireblast"]
    game, caster, victim = _w2g1_duel([card], board=("Mountain",))

    result = game.cast_from_hand(
        0, "Fireblast", alternative_cost=True, target_player_index=1,
    )

    assert not result.supported
    assert "CR 601.2h" in result.details
    assert [p.card.name for p in caster.battlefield] == ["Mountain"]
    assert [c.name for c in caster.hand] == ["Fireblast"]
    assert victim.life == 20
def test_fireblast_will_not_eat_two_forests(set_pool):
    """The printed subtype is charged, not "two lands"."""
    card = set_pool("VIS")["Fireblast"]
    game, caster, _ = _w2g1_duel([card], board=("Forest", "Forest"))

    result = game.cast_from_hand(
        0, "Fireblast", alternative_cost=True, target_player_index=1,
    )

    assert not result.supported
    assert len(caster.battlefield) == 2
def test_kaerveks_spite_sacrifices_the_whole_board_and_the_hand(set_pool):
    """CR 601.2b: "sacrifice all permanents you control and discard your hand".

    Both clauses, and neither reaching past the caster: an opponent's board is
    not part of the price (CR 701.21a — a player can't sacrifice a permanent
    they don't control).
    """
    pool = set_pool("VIS")
    game, caster, victim = _w2g1_duel(
        [pool["Kaervek's Spite"], _W2G1_LEA["Black Lotus"], _W2G1_LEA["Counterspell"]],
        board=("Swamp", "Swamp", "Mons's Goblin Raiders"),
        enforce=False,
    )
    victim.battlefield.append(_W2G1Permanent(card=_W2G1_LEA["Forest"]))

    result = game.cast_from_hand(0, "Kaervek's Spite", target_player_index=1)

    assert result.supported, result.details
    assert caster.battlefield == []
    assert caster.hand == []
    assert [p.card.name for p in victim.battlefield] == ["Forest"]
    assert victim.life == 15
    assert {"Swamp", "Mons's Goblin Raiders", "Black Lotus", "Counterspell"} <= {
        c.name for c in caster.graveyard
    }
def test_kaerveks_spite_is_castable_off_an_empty_board(set_pool):
    """"All" of nothing is a payment in full (CR 601.2h), which is why the
    clause is outside the unpayability gate."""
    game, caster, victim = _w2g1_duel(
        [set_pool("VIS")["Kaervek's Spite"]], enforce=False,
    )

    result = game.cast_from_hand(0, "Kaervek's Spite", target_player_index=1)

    assert result.supported, result.details
    assert victim.life == 15
def test_a_cost_clause_nothing_charges_refuses_the_whole_sentence():
    """The all-or-nothing rule, on both tables.

    A clause dropped from an additional cost is a spell cast for less than it
    prints; a clause dropped from an alternative cost is one cast for nothing.
    """
    assert _w2g1_add_line(
        "As an additional cost to cast this spell, sacrifice all permanents "
        "you control and hum a tune."
    ) is None
    assert _w2g1_alt_line(
        "You may sacrifice two Mountains and hum a tune rather than pay this "
        "spell's mana cost."
    ) is None
    # An "all" clause naming somebody else's board is not a payable cost at
    # all (CR 701.21a), so it refuses rather than being charged to the caster.
    assert _w2g1_add_line(
        "As an additional cost to cast this spell, sacrifice all lands your "
        "opponents control."
    ) is None

def _w2g5_duel(caster_hand, victim_hand, victim_library):
    p1 = _W2G5Player(name="P1", hand=list(caster_hand))
    p2 = _W2G5Player(name="P2", hand=list(victim_hand), library=list(victim_library))
    game = _W2G5Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2
def test_desertion_is_supported_and_carries_both_printed_halves(set_pool):
    """The narrowing and the destination are separate payload keys.

    They have to be: the class decides *whether* CR 614.1's replacement applies
    at all, so folding it into the destination would send every countered spell
    to the battlefield instead of the graveyard.
    """
    card = set_pool("VIS")["Desertion"]
    program = _w2g5_program(card)
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "counter_top_stack_spell"
    assert instruction.payload["countered_destination"] == "battlefield_your_control"
    assert instruction.payload["countered_filter"] == {
        "type_filter": ["artifact", "creature"]
    }
def test_desertion_steals_a_countered_creature_spell(set_pool, set_cards):
    lea = {c.name: c for c in set_cards("LEA")}
    desertion = set_pool("VIS")["Desertion"]
    game, p1, p2 = _w2g5_duel([desertion], [lea["Grizzly Bears"]], [lea["Island"]] * 3)

    game.queue_from_hand(1, "Grizzly Bears")
    game.queue_from_hand(0, "Desertion", target_stack_index=0)
    game.resolve_stack()

    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"]
    assert p2.battlefield == []
    assert [c.name for c in p2.graveyard] == []
def test_desertion_steals_a_countered_artifact_spell(set_pool, set_cards):
    """"an artifact **or** creature spell" is a union, so both halves land."""
    lea = {c.name: c for c in set_cards("LEA")}
    desertion = set_pool("VIS")["Desertion"]
    game, p1, p2 = _w2g5_duel([desertion], [lea["Black Lotus"]], [lea["Island"]] * 3)

    game.queue_from_hand(1, "Black Lotus")
    game.queue_from_hand(0, "Desertion", target_stack_index=0)
    game.resolve_stack()

    assert [p.card.name for p in p1.battlefield] == ["Black Lotus"]
def test_desertion_bins_a_countered_spell_outside_the_named_class(set_pool, set_cards):
    """The narrowing is enforced, not decorative.

    An instant is countered and takes CR 701.5a's ordinary graveyard: the
    destination is dropped, never the counter.
    """
    lea = {c.name: c for c in set_cards("LEA")}
    desertion = set_pool("VIS")["Desertion"]
    game, p1, p2 = _w2g5_duel([desertion], [lea["Lightning Bolt"]], [lea["Island"]] * 3)

    game.queue_from_hand(1, "Lightning Bolt")
    game.queue_from_hand(0, "Desertion", target_stack_index=0)
    game.resolve_stack()

    assert p1.battlefield == []
    assert [c.name for c in p2.graveyard] == ["Lightning Bolt"]
    assert p1.life == 20
def test_the_counter_tail_still_reads_its_two_older_spellings():
    """Memory Lapse and Dissipate are unchanged by the third possessive.

    "its owner's" and "that player's" name one seat (CR 404.3); accepting
    either is reading the clause rather than widening it.
    """
    lapse = _w2g5_compile(
        "Counter target spell. If that spell is countered this way, put it on "
        "top of its owner's library instead of into that player's graveyard."
    )
    assert lapse.lowered
    assert lapse.instructions[0].payload["countered_destination"] == "library_top"
    assert "countered_filter" not in lapse.instructions[0].payload

    dissipate = _w2g5_compile(
        "Counter target spell. If that spell is countered this way, exile it "
        "instead of putting it into its owner's graveyard."
    )
    assert dissipate.lowered
    assert dissipate.instructions[0].payload["countered_destination"] == "exile"
def test_a_countered_destination_the_flow_cannot_perform_refuses_the_line():
    """The full-consumption invariant, on the half a card could get wrong.

    Once "countered this way" has matched, a destination no seam performs must
    make the line refuse — silently keeping the graveyard would be the counter
    the card already was, with its whole second sentence gone.
    """
    with __import__("pytest").raises(_W2G5GrammarError):
        _w2g5_parse(
            "Counter target spell. If that spell is countered this way, put it "
            "into its owner's sideboard instead of into that player's graveyard."
        )
def test_a_narrowed_counter_tail_missing_its_replacement_half_refuses():
    """"instead of ..." is what makes this CR 614.1 rather than a second effect."""
    with __import__("pytest").raises(_W2G5GrammarError):
        _w2g5_parse(
            "Counter target spell. If an artifact or creature spell is countered "
            "this way, put that card onto the battlefield under your control."
        )
def test_a_countered_card_put_onto_the_battlefield_must_name_its_controller():
    """CR 110.2's battlefield is shared, so the sentence has to say whose side.

    Without the words the card would arrive under nobody's control, which is
    the one thing the destination cannot leave unstated.
    """
    with __import__("pytest").raises(_W2G5GrammarError):
        _w2g5_parse(
            "Counter target spell. If an artifact or creature spell is countered "
            "this way, put that card onto the battlefield instead of into its "
            "owner's graveyard."
        )


# --- W3G1: Three Wishes, a face-down exile a spell may play out of ---

import pytest as _w3g1_pytest  # noqa: E402
from engine import Game as _W3G1Game, PlayerState as _W3G1PlayerState  # noqa: E402
from engine.card_loader import (  # noqa: E402
    load_cards as _w3g1_load, manifest_set_path as _w3g1_path,
)
from engine.cast_permissions import (  # noqa: E402
    playable_from_zones as _w3g1_playable,
)
from engine.exiled_records import live_records as _w3g1_live  # noqa: E402
from engine.grammar import parse_line as _w3g1_parse  # noqa: E402
from engine.grammar.errors import (  # noqa: E402
    GrammarError as _W3G1GrammarError, LoweringError as _W3G1LoweringError,
)
from engine.grammar import lower_ability as _w3g1_lower  # noqa: E402
from engine.linked_exile import (  # noqa: E402
    face_down_exiled_cards as _w3g1_face_down,
)


@_w3g1_pytest.fixture(scope="module")
def _w3g1_lea():
    return {c.name: c for c in _w3g1_load(_w3g1_path("LEA"))}


def _w3g1_board(set_pool, lea):
    """Three Wishes in seat 0's hand over a library whose top three are known."""
    pool = set_pool("VIS")
    game = _W3G1Game(players=[
        _W3G1PlayerState(
            name="P1", hand=[pool["Three Wishes"]],
            library=[lea["Mountain"], lea["Black Lotus"], lea["Forest"]]
            + [lea["Island"]] * 10,
        ),
        _W3G1PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    # Armed before anything resolves: a headless seat answers its own prompts,
    # so a reading taken without this is a reading of the defaults.
    game.interactive_seats = {0, 1}
    return game


def _w3g1_cast(set_pool, lea):
    game = _w3g1_board(set_pool, lea)
    result = game.cast_from_hand(0, "Three Wishes")
    assert result.supported, result.details
    game.resolve_stack()
    return game


def test_three_wishes_is_supported(set_pool):
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("VIS")["Three Wishes"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "exile_top_of_library",
        "grant_look_at_exiled_cards",
        "grant_cast_permission",
        "create_delayed_trigger",
    ]
    assert steps[2].payload["duration"] == "your_next_turn"


def test_three_wishes_exiles_three_face_down_with_no_permanent_to_hold_it(
    set_pool, _w3g1_lea
):
    """"Exile the top three cards of your library face down."

    An **instant** exiles them, so there is no permanent for the linked-exile
    record to live on — which used to refuse the exile outright and made this
    sentence compile, lower and do nothing. ``engine/exiled_records.py`` is the
    register that answers for an exiler which never becomes a permanent.
    """
    game = _w3g1_cast(set_pool, _w3g1_lea)

    assert [c.name for c in game.players[0].exile] == [
        "Mountain", "Black Lotus", "Forest",
    ]
    records = list(_w3g1_live(game))
    assert [(r.card.name, r.face_down) for r in records] == [
        ("Mountain", True), ("Black Lotus", True), ("Forest", True),
    ]


def test_three_wishes_hides_the_pile_from_everyone_but_its_caster(
    set_pool, _w3g1_lea
):
    """CR 406.3: a card exiled face down is hidden from every player, and "you
    may look at those cards" is the effect that opens it to one of them.

    The two registers answer one question, so the caster sees the pile and the
    opponent does not — with the record on the *game* rather than on a
    permanent, which is the half a spell could not have before.
    """
    game = _w3g1_cast(set_pool, _w3g1_lea)

    # Face down as the rules describe it, with no permission applied.
    assert [c.name for c in _w3g1_face_down(game, 0)] == [
        "Mountain", "Black Lotus", "Forest",
    ]
    # …and to the caster, nothing is hidden.
    assert _w3g1_face_down(game, 0, 0) == []
    assert [c.name for c in _w3g1_face_down(game, 0, 1)] == [
        "Mountain", "Black Lotus", "Forest",
    ]


def test_three_wishes_lets_its_caster_play_a_land_out_of_the_pile(
    set_pool, _w3g1_lea
):
    """CR 701.18b: to *play* a card is to play it as a land or cast it as a
    spell, whichever is appropriate — so the printed "play" has to cover the
    land drop, which a cast-only permission would sit through.
    """
    game = _w3g1_cast(set_pool, _w3g1_lea)
    game.active_player_index = 0

    assert [e["name"] for e in _w3g1_playable(game, 0)] == [
        "Mountain", "Black Lotus", "Forest",
    ]
    # The opponent may play none of them: CR 601.3 grants this to the caster.
    assert _w3g1_playable(game, 1) == []

    result = game.cast_from_hand(0, "Mountain", from_zone="exile")
    assert result.supported, result.details
    assert [p.card.name for p in game.controlled_by(0)] == ["Mountain"]
    # The grant is one use per card, so the other two survive it.
    assert [c.name for c in game.cast_permissions[0].cards] == [
        "Black Lotus", "Forest",
    ]


def test_three_wishes_permission_ends_as_its_casters_next_turn_begins(
    set_pool, _w3g1_lea
):
    """"Until your next turn" — CR 800.4m states the moment: the duration lasts
    until that player's turn would have begun. So an opponent's whole turn is
    inside it and the caster's own turn boundary is what ends it.
    """
    game = _w3g1_cast(set_pool, _w3g1_lea)
    assert game.cast_permissions[0].duration == "your_next_turn"

    game.begin_turn_bookkeeping(1)
    assert len(game.cast_permissions) == 1, "an opponent's turn does not end it"

    game.begin_turn_bookkeeping(0)
    assert game.cast_permissions == []


def test_three_wishes_bins_only_the_cards_that_were_not_played(
    set_pool, _w3g1_lea
):
    """"At the beginning of your next upkeep, put any of those cards you didn't
    play into your graveyard." — a CR 603.7 delayed ability over the pile the
    same resolution exiled.

    "You didn't play" needs no flag: a card that was played is not in exile any
    more, and this instruction only moves cards out of exile.
    """
    game = _w3g1_cast(set_pool, _w3g1_lea)
    game.active_player_index = 0
    assert game.cast_from_hand(0, "Black Lotus", from_zone="exile").supported

    game.begin_turn_bookkeeping(0)
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert game.players[0].exile == []
    assert [c.name for c in game.players[0].graveyard] == [
        "Three Wishes", "Mountain", "Forest",
    ]
    assert [p.card.name for p in game.controlled_by(0)] == ["Black Lotus"]
    # The register drains with the pile: a record left alive would hide the
    # same card the next time anything exiled it.
    assert list(_w3g1_live(game)) == []


def test_a_permission_over_a_pile_needs_a_step_that_exiled_one(set_pool):
    """The producer gate every back-reference here makes: "those cards" with no
    exile in front of it names nothing, and a permission with nothing to permit
    is the sentence read wrong."""
    with _w3g1_pytest.raises(_W3G1LoweringError):
        _w3g1_lower(_w3g1_parse("Until your next turn, you may play those cards."))


def test_a_plural_permission_still_needs_a_printed_duration(set_pool):
    """CR 611.2a: with no stated duration the permission outlives the card that
    granted it. The plural referent changes the number, not that rule."""
    with _w3g1_pytest.raises(_W3G1LoweringError):
        _w3g1_lower(_w3g1_parse(
            "Exile the top three cards of your library. You may play those cards."
        ))


def test_the_unplayed_bin_refuses_without_its_condition(set_pool):
    """"Put any of those cards **you didn't play** into your graveyard."

    Every word of the object phrase is required. Without it the sentence would
    bin the cards already played, which is a card nothing can be played out of
    at all — and the grammar must refuse rather than read the shorter sentence.
    """
    with _w3g1_pytest.raises(_W3G1GrammarError):
        _w3g1_parse(
            "Exile the top three cards of your library face down. "
            "At the beginning of your next upkeep, put any of those cards "
            "into your graveyard."
        )


def test_a_look_permission_is_not_granted_to_another_player(set_pool):
    """The look handler writes the *caster* onto the record, so a printed
    grantee would be read by nobody and the wrong seat would get the look."""
    with _w3g1_pytest.raises((_W3G1GrammarError, _W3G1LoweringError)):
        _w3g1_lower(_w3g1_parse(
            "At the beginning of each player's upkeep, that player exiles a "
            "card at random from their hand. That player may look at that card "
            "for as long as it remains exiled."
        ))
