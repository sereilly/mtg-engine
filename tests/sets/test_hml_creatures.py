"""Per-card tests for Homelands' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G1: untap denial ---

from engine import Game, PlayerState
from engine.damage_events import deal_damage
from engine.game_types import CardDefinition
from engine.models import Permanent


def _g1_creature(name: str, subtype: str = "Test", colors: tuple[str, ...] = ()):
    """A plain 2/5 with a printed subtype, for the noun phrases these cards
    narrow by. Toughness 5 so a blocker survives the combat its own trigger is
    about."""
    type_line = f"Creature - {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "5"},
    )


def _g1_ready(*permanents):
    """Everything in *permanents* able to act this turn (CR 302.6)."""
    for permanent in permanents:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanents


def _g1_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


def _g1_to_declare_attackers(game):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers


def test_reveka_pings_and_holds_itself_down_a_turn(set_pool):
    """"{T}: Reveka deals 2 damage to any target **and doesn't untap during
    your next untap step**."

    One noun phrase printed once and two things said about it, which is the
    tail two pump verbs already carried and this round put on the third. The
    damage half and the restriction half are asserted together: the clause used
    to be unconsumed text, so the whole ability was unsupported rather than
    half-done.
    """
    reveka = Permanent(card=set_pool("HML")["Reveka, Wizard Savant"])
    _g1_ready(reveka)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[reveka]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    result = game.activate_permanent_ability(
        0, "Reveka, Wizard Savant", permanent_index=0, target_player_index=1
    )
    _g1_settle(game)

    assert result.supported, result.details
    assert game.players[1].life == 18
    assert reveka.tapped is True

    game.resolve_untap_step(0)
    assert reveka.tapped is True
    game.resolve_untap_step(0)
    assert reveka.tapped is False


def test_revekas_skipped_untap_is_your_step_and_not_an_opponents(set_pool):
    """"...during **your** next untap step" names a seat, not "its controller's
    next untap step". An opponent's untap step must not spend the restriction,
    because it is not the step the card named."""
    reveka = Permanent(card=set_pool("HML")["Reveka, Wizard Savant"])
    _g1_ready(reveka)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[reveka]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    game.activate_permanent_ability(
        0, "Reveka, Wizard Savant", permanent_index=0, target_player_index=1
    )
    _g1_settle(game)

    game.resolve_untap_step(1)
    assert reveka.metadata.get("skip_next_untap") == 1
    game.resolve_untap_step(0)
    assert reveka.metadata.get("skip_next_untap") is None


def test_spectral_bears_stays_tapped_when_the_defender_is_not_black(set_pool):
    """"Whenever this creature attacks, if defending player controls no black
    nontoken permanents, **it** doesn't untap during your next untap step."

    "It" is the creature the trigger's own condition named - there is no
    earlier sentence for the pronoun to point back at, which is what the
    lowering used to demand. The Bears attack for free and pay for it on the
    way back.
    """
    bears = Permanent(card=set_pool("HML")["Spectral Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]), PlayerState(name="P2"),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert bears.tapped is True
    game.resolve_untap_step(0)
    assert bears.tapped is True
    game.resolve_untap_step(0)
    assert bears.tapped is False


def test_spectral_bears_untaps_normally_against_a_black_permanent(set_pool):
    """The intervening if is the card: one black nontoken permanent on the
    defender's side and the drawback never fires. Asserted beside the row above
    so a trigger that ignored its condition cannot pass on one of them."""
    bears = Permanent(card=set_pool("HML")["Spectral Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=_g1_creature("Bog Rat", colors=("B",)))],
        ),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert bears.metadata.get("skip_next_untap") is None
    game.resolve_untap_step(0)
    assert bears.tapped is False


def test_labyrinth_minotaur_holds_down_what_it_blocks(set_pool):
    """"Whenever this creature blocks a creature, **that creature** doesn't
    untap during its controller's next untap step."

    "That creature" is the *attacker* the trigger bound, which no sentence in
    the line names - so it comes from the block pair rather than from the stack
    item's target. Reading the target on the blocks half would mark the
    Minotaur itself, which is the second assertion below.
    """
    minotaur = Permanent(card=set_pool("HML")["Labyrinth Minotaur"])
    attacker = Permanent(card=_g1_creature("Grey Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[minotaur]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    _g1_settle(game)

    assert attacker.metadata.get("skip_next_untap") == 1
    assert minotaur.metadata.get("skip_next_untap") is None

    attacker.tapped = True
    game.resolve_untap_step(0)
    assert attacker.tapped is True
    game.resolve_untap_step(0)
    assert attacker.tapped is False


def test_labyrinth_minotaur_marks_nobody_when_it_does_not_block(set_pool):
    """No block, no trigger, no marker - the control for the row above, so a
    handler that marked whatever it found on the board cannot pass it."""
    minotaur = Permanent(card=set_pool("HML")["Labyrinth Minotaur"])
    attacker = Permanent(card=_g1_creature("Grey Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[minotaur]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {})[0]
    _g1_settle(game)

    assert attacker.metadata.get("skip_next_untap") is None


def test_jovens_ferrets_taps_only_the_creatures_that_blocked_it(set_pool):
    """"At end of combat, tap all creatures that blocked this creature this
    turn. **They** don't untap during their controller's next untap step."

    Two things at once: a noun phrase narrowed by a block *history* read off
    the record the declare-blockers step stamps, and a plural pronoun naming
    what the sentence in front of it swept. A bystander on the same
    battlefield is the control - a dropped narrowing would tap the board.
    """
    ferrets = Permanent(card=set_pool("HML")["Joven's Ferrets"])
    blocker = Permanent(card=_g1_creature("Wall of Test"))
    bystander = Permanent(card=_g1_creature("Idle Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[ferrets]),
        PlayerState(name="P2", battlefield=[blocker, bystander]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    _g1_settle(game)
    game.advance_combat_phase()   # combat damage
    _g1_settle(game)
    game.advance_combat_phase()   # end of combat
    _g1_settle(game)

    assert blocker.tapped is True
    assert blocker.metadata.get("skip_next_untap") == 1
    assert bystander.tapped is False
    assert bystander.metadata.get("skip_next_untap") is None

    game.resolve_untap_step(1)
    assert blocker.tapped is True
    game.resolve_untap_step(1)
    assert blocker.tapped is False


def test_jovens_ferrets_still_pumps_itself_when_it_attacks(set_pool):
    """Its first line, asserted beside the second so a change to either cannot
    pass on the other: a 1/1 Ferret is a 1/3 for the combat it started."""
    ferrets = Permanent(card=set_pool("HML")["Joven's Ferrets"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[ferrets]), PlayerState(name="P2"),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert ferrets.effective_toughness == 3


def test_samite_alchemist_shields_taps_and_holds_one_creature(set_pool):
    """"{W}{W}, {T}: Prevent the next 4 damage that would be dealt **this turn
    to** target creature you control. Tap that creature. It doesn't untap
    during your next untap step."

    All three sentences about one target. The printed word order puts the
    duration before the recipient, which is the same sentence the modern
    printing spells the other way round - the blanket shield beside it already
    read either, and a numeric one failing on word order was the card lost to a
    printing convention rather than to a missing effect.
    """
    alchemist = Permanent(card=set_pool("HML")["Samite Alchemist"])
    ally = Permanent(card=_g1_creature("Grey Ogre"))
    _g1_ready(alchemist, ally)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[alchemist, ally]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    result = game.activate_permanent_ability(
        0, "Samite Alchemist", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    _g1_settle(game)

    assert result.supported, result.details
    assert ally.damage_prevention_pool == 4
    assert ally.tapped is True

    outcome = deal_damage(game, {"recipient": ally, "amount": 3, "source": None})
    assert outcome.dealt == 0
    assert ally.damage_marked == 0
    assert ally.damage_prevention_pool == 1

    game.resolve_untap_step(0)
    assert ally.tapped is True
    game.resolve_untap_step(0)
    assert ally.tapped is False


def test_samite_alchemist_leaves_an_untargeted_creature_alone(set_pool):
    """The tap and the untap restriction name the creature the *first* sentence
    chose, not a second one - so a bystander on the same battlefield is
    untouched by all three sentences."""
    alchemist = Permanent(card=set_pool("HML")["Samite Alchemist"])
    ally = Permanent(card=_g1_creature("Grey Ogre"))
    bystander = Permanent(card=_g1_creature("Idle Ogre"))
    _g1_ready(alchemist, ally, bystander)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[alchemist, ally, bystander]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    game.activate_permanent_ability(
        0, "Samite Alchemist", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    _g1_settle(game)

    assert bystander.tapped is False
    assert bystander.damage_prevention_pool == 0
    assert bystander.metadata.get("skip_next_untap") is None
