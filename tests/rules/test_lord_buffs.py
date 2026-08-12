"""CR 611.3 / 613 — a lord's continuous buff to other creatures.

``_recalculate_lord_buffs`` reads ``engine/lord_buffs.py`` and honours every
field of it: who is buffed (colour, subtype, "other", controller scope, and a
state qualifier) and what they get (a layer-7c P/T delta, layer-6 keyword
abilities, and a granted activated ability).

The cards are here for the CR citations, but the *properties* are pinned with
invented cards wherever the point is that the template generalizes. Two real
bugs fell out of the migration and each has a test below: an untapped-only
anthem that survived its own creature tapping, and a colour anthem that never
reached an animated land because the consumer read the printed type line
instead of asking layer 4.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.text_changes import change_land_word


def _card(name: str, type_line: str, oracle_text: str, *, colors=(), power="2",
          toughness="2") -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = power, toughness
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw=raw,
    )


def _game(*battlefields) -> tuple[Game, list[PlayerState]]:
    players = [
        PlayerState(name=f"P{index + 1}", battlefield=list(perms), life=20)
        for index, perms in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game, players


# An invented lord with every parameter set differently from any printed card,
# so nothing here can pass by matching one card's numbers.
KOBOLD_CHIEFTAIN = _card(
    "Kobold Chieftain", "Creature — Kobold",
    "Other Kobolds get +2/+1 and have forestwalk.", colors=("R",),
    power="1", toughness="1",
)
KOBOLD = _card("Kobold Warren-Runner", "Creature — Kobold", "", colors=("R",),
               power="1", toughness="1")


# ---------------------------------------------------------------------------
# The whole filter, on a card the engine has never seen
# ---------------------------------------------------------------------------


@pytest.mark.cr("611.3a", "613.4c", "613.1f")
def test_an_invented_lord_buffs_its_subtype_and_grants_its_keyword():
    other = Permanent(card=KOBOLD)
    chieftain = Permanent(card=KOBOLD_CHIEFTAIN)
    _game([chieftain, other])

    assert (other.effective_power, other.effective_toughness) == (3, 2)
    assert other.has_keyword("forestwalk")


@pytest.mark.cr("613.4c")
def test_other_excludes_the_lord_itself():
    """CR 613 does not exempt a static ability's own source; "Other" does. A
    consumer that ignored the word would make the Chieftain a 3/2."""
    chieftain = Permanent(card=KOBOLD_CHIEFTAIN)
    _game([chieftain])

    assert (chieftain.effective_power, chieftain.effective_toughness) == (1, 1)
    assert not chieftain.has_keyword("forestwalk")


@pytest.mark.cr("613.4c")
def test_a_creature_of_another_subtype_is_untouched():
    bystander = _card("Wandering Ox", "Creature — Ox", "", colors=("G",))
    ox = Permanent(card=bystander)
    _game([Permanent(card=KOBOLD_CHIEFTAIN), ox])

    assert (ox.effective_power, ox.effective_toughness) == (2, 2)
    assert not ox.has_keyword("forestwalk")


@pytest.mark.cr("611.3b")
def test_the_buff_and_the_grant_end_when_the_lord_leaves():
    """Removal is the absence of a contribution — there is no remembered delta
    to subtract, so nothing can fall out of step with what was added."""
    other = Permanent(card=KOBOLD)
    chieftain = Permanent(card=KOBOLD_CHIEFTAIN)
    game, players = _game([chieftain, other])
    assert other.has_keyword("forestwalk")

    players[0].battlefield.remove(chieftain)
    game._recompute_continuous_effects()

    assert (other.effective_power, other.effective_toughness) == (1, 1)
    assert not other.has_keyword("forestwalk")


@pytest.mark.cr("611.3c")
def test_a_creature_entering_later_gets_the_buff_immediately():
    chieftain = Permanent(card=KOBOLD_CHIEFTAIN)
    game, players = _game([chieftain])

    late = Permanent(card=KOBOLD)
    players[0].battlefield.append(late)
    game._recompute_continuous_effects()

    assert (late.effective_power, late.effective_toughness) == (3, 2)


@pytest.mark.cr("613.4c")
def test_controller_scope_is_honoured_in_both_directions():
    """"Creatures you control" reaches only its controller; without those words
    the anthem reaches every player (Bad Moon, Crusade)."""
    mine = Permanent(card=_card("Mine", "Creature — Soldier", "", colors=("W",)))
    theirs = Permanent(card=_card("Theirs", "Creature — Soldier", "", colors=("W",)))
    scoped = _card("Invented Banner", "Enchantment", "Creatures you control get +1/+1.")
    _game([mine, Permanent(card=scoped)], [theirs])

    assert mine.effective_power == 3
    assert theirs.effective_power == 2

    everyone = Permanent(card=_card("Invented Anthem", "Enchantment",
                                    "White creatures get +1/+1."))
    other_mine = Permanent(card=_card("Mine2", "Creature — Soldier", "", colors=("W",)))
    other_theirs = Permanent(card=_card("Theirs2", "Creature — Soldier", "", colors=("W",)))
    _game([other_mine, everyone], [other_theirs])

    assert other_mine.effective_power == 3
    assert other_theirs.effective_power == 3


@pytest.mark.cr("613.4c")
def test_a_colour_anthem_reaches_only_that_colour():
    white = Permanent(card=_card("White One", "Creature — Soldier", "", colors=("W",)))
    black = Permanent(card=_card("Black One", "Creature — Zombie", "", colors=("B",)))
    _game([white, black, Permanent(card=_card(
        "Invented Anthem", "Enchantment", "White creatures get +1/+1."))])

    assert white.effective_power == 3
    assert black.effective_power == 2


@pytest.mark.cr("613.4c")
def test_the_opponent_scope_reaches_every_other_seat_and_none_of_your_own():
    """"Creatures your opponents control get -1/-0" (Waker of Waves). Read as
    the everyone-else default it would shrink the source's own side too, which
    is why the scope is spelled out in the consumer rather than folded in."""
    mine = Permanent(card=_card("Mine", "Creature — Soldier", ""))
    theirs = Permanent(card=_card("Theirs", "Creature — Soldier", ""))
    source = Permanent(card=_card(
        "Invented Drowner", "Creature — Whale",
        "Creatures your opponents control get -1/-0.", power="7", toughness="7",
    ))
    game, players = _game([mine, source], [theirs])

    assert (theirs.effective_power, theirs.effective_toughness) == (1, 2)
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert source.effective_power == 7, "the source is on its controller's side"

    players[0].battlefield.remove(source)
    game._recompute_continuous_effects()
    assert theirs.effective_power == 2, "CR 611.3b: removal is the absent contribution"


@pytest.mark.cr("613.4c", "704.5f")
def test_a_negative_anthem_is_the_same_contribution_with_the_printed_sign():
    """"Other creatures get -1/-1" (Kaervek, the Spiteful) is one more reading
    of the template, not a new family — and a creature it empties dies to the
    ordinary state-based action, on every recompute, with no delta to unwind
    when the lord leaves."""
    debuffer = Permanent(card=_card(
        "Invented Tyrant", "Creature — Kobold", "Other creatures get -1/-1.",
        power="3", toughness="3",
    ))
    sturdy = Permanent(card=KOBOLD)
    game, players = _game([debuffer, sturdy])

    assert (debuffer.effective_power, debuffer.effective_toughness) == (3, 3)
    assert (sturdy.effective_power, sturdy.effective_toughness) == (0, 0)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(sturdy)

    players[0].battlefield.remove(debuffer)
    game._recompute_continuous_effects()
    survivor = Permanent(card=KOBOLD)
    players[0].battlefield.append(survivor)
    game._recompute_continuous_effects()
    assert (survivor.effective_power, survivor.effective_toughness) == (1, 1)


# ---------------------------------------------------------------------------
# The qualifiers the old consumer dropped
# ---------------------------------------------------------------------------


def _combat_game(attacker_battlefield, defender_battlefield=()):
    game, players = _game(attacker_battlefield, defender_battlefield)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    return game, players


@pytest.mark.cr("611.3a", "613.4c")
def test_an_untapped_only_anthem_ends_the_moment_its_creature_taps(cards):
    """**A bug the migration exposed.** Castle's "Untapped creatures you control
    get +0/+2" was contributed at *recompute* time, and nothing recomputes when
    a creature taps — so a 2/2 attacking under Castle stayed a 2/4 for the whole
    declare-attackers step, which is where priority is held and where blocks are
    decided. CR 611.3a: the ability applies at any given moment to whatever its
    text indicates.
    """
    bear = Permanent(card=cards["Grizzly Bears"])
    bear.metadata["summoning_sickness_turn"] = -99
    game, _ = _combat_game([bear, Permanent(card=cards["Castle"])])
    assert bear.effective_toughness == 4

    ok, why = game.declare_attackers(0, [0])
    assert ok, why
    assert bear.tapped
    assert bear.effective_toughness == 2, "Castle must not buff a tapped creature"


@pytest.mark.cr("611.3a", "613.4c")
def test_an_attacking_only_anthem_applies_only_while_attacking(cards):
    bear = Permanent(card=cards["Grizzly Bears"])
    bear.metadata["summoning_sickness_turn"] = -99
    game, _ = _combat_game([bear, Permanent(card=cards["Orcish Oriflamme"])])
    assert bear.effective_power == 2

    game.declare_attackers(0, [0])
    assert bear.effective_power == 3


@pytest.mark.cr("509.1a", "613.4c")
def test_a_blocking_only_anthem_applies_only_while_blocking(cards):
    """No printed permanent in the pool has this qualifier, which is exactly why
    it needs an invented one: a filter field nothing exercises is a field that
    quietly stops working."""
    attacker = Permanent(card=cards["Grizzly Bears"])
    attacker.metadata["summoning_sickness_turn"] = -99
    blocker = Permanent(card=cards["Hill Giant"])
    rampart = Permanent(card=_card("Invented Rampart", "Enchantment",
                                   "Blocking creatures you control get +0/+3."))
    game, _ = _combat_game([attacker], [blocker, rampart])
    assert blocker.effective_toughness == 3

    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0})

    assert blocker.effective_toughness == 6


# ---------------------------------------------------------------------------
# CR 613.1 — the layers run in order, and the consumer must ask them
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1d", "613.4c")
def test_an_anthem_reaches_a_land_animated_in_layer_4(cards):
    """**A bug the migration exposed.** Kormus Bell makes every Swamp a 1/1
    black creature (layer 4), and Bad Moon gives black creatures +1/+1 (layer
    7c) — 613.1 applies 4 before 7, so the Swamp is a 2/2. The consumer skipped
    it on ``card.primary_type != "creature"``: the printed type line, which
    layer 4 is precisely what overrides.
    """
    swamp = Permanent(card=cards["Swamp"])
    _game([swamp, Permanent(card=cards["Kormus Bell"]), Permanent(card=cards["Bad Moon"])])

    assert swamp.is_creature
    assert (swamp.effective_power, swamp.effective_toughness) == (2, 2)


@pytest.mark.cr("613.1f", "702.14b")
def test_a_reader_of_the_granted_keyword_asks_layer_6(cards):
    """Island Sanctuary lets through fliers and islandwalkers only. It read a
    ``has_islandwalk`` metadata flag plus the printed keyword list, so it saw
    exactly the routes to the ability someone had told it about — while the
    lord's grant is a layer-6 effect like any other."""
    merfolk = Permanent(card=cards["Merfolk of the Pearl Trident"])
    merfolk.metadata["summoning_sickness_turn"] = -99
    lord = Permanent(card=cards["Lord of Atlantis"])
    game, players = _game([merfolk, lord], [])
    players[1].island_sanctuary_protected = True

    assert merfolk.has_keyword("islandwalk")
    assert game.can_attack(merfolk, defending_player_index=1) is True

    players[0].battlefield.remove(lord)
    game._recompute_continuous_effects()
    assert game.can_attack(merfolk, defending_player_index=1) is False


@pytest.mark.cr("613.1c")
def test_a_text_change_on_the_lord_moves_the_walk_it_grants(cards):
    """Magical Hack on Goblin King: the land word in its text is replaced, so
    other Goblins get islandwalk instead of mountainwalk (CR 613 layer 3)."""
    king = Permanent(card=cards["Goblin King"])
    change_land_word(king, "mountain", "island")
    goblin = Permanent(card=cards["Mons's Goblin Raiders"])
    _game([king, goblin])

    assert goblin.has_keyword("islandwalk")
    assert not goblin.has_keyword("mountainwalk")


@pytest.mark.cr("611.3a")
def test_a_conditional_anthem_applies_only_while_its_condition_holds(cards, arn_by_name):
    """Jihad's "as long as the chosen player controls a nontoken permanent of
    the chosen color". The condition is derived alongside the filter and
    evaluated on every recompute, so the anthem comes and goes with it.

    Tested apart from the sacrifice trigger on purpose: on the real card the
    condition going false also destroys the enchantment, so the buff would
    vanish either way and a consumer that ignored the condition entirely would
    look correct.
    """
    knight = Permanent(card=cards["White Knight"])
    jihad = Permanent(card=arn_by_name["Jihad"])
    jihad.metadata["chosen_player_index"] = 1
    jihad.metadata["chosen_color"] = "G"
    green = Permanent(card=cards["Grizzly Bears"])
    game, players = _game([knight, jihad], [green])

    assert (knight.effective_power, knight.effective_toughness) == (4, 3)

    players[1].battlefield.remove(green)
    game._recompute_continuous_effects()
    assert (knight.effective_power, knight.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# A granted activated ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("611.3a", "611.3b")
def test_a_granted_activated_ability_arrives_and_leaves_with_its_source(cards):
    zombie = Permanent(card=cards["Scathe Zombies"])
    master = Permanent(card=cards["Zombie Master"])
    game, players = _game([master, zombie])
    assert zombie.metadata.get("granted_regen_ability") is True

    players[0].battlefield.remove(master)
    game._recompute_continuous_effects()
    assert not zombie.metadata.get("granted_regen_ability")


# ---------------------------------------------------------------------------
# CR 611.2c — the spell reading is a different effect and stays one
# ---------------------------------------------------------------------------


@pytest.mark.cr("611.2c")
def test_a_spells_board_buff_locks_its_set_in_at_resolution(cards, arn_by_name):
    """Army of Allah's "Attacking creatures get +2/+0 until end of turn" is a
    one-shot effect: the set of creatures it affects is fixed when it resolves.
    A creature that attacks *afterwards* gets nothing, and the buff does not
    disappear when the board is next recomputed — which is what would happen if
    the two readings of this sentence had been merged onto one instruction.
    """
    attacker = Permanent(card=cards["Grizzly Bears"])
    attacker.metadata["summoning_sickness_turn"] = -99
    latecomer = Permanent(card=cards["Hill Giant"])
    latecomer.metadata["summoning_sickness_turn"] = -99
    game, players = _combat_game([attacker, latecomer])
    players[0].hand.append(arn_by_name["Army of Allah"])

    game.declare_attackers(0, [0])
    game.cast_from_hand(0, "Army of Allah")
    assert attacker.effective_power == 4

    # Recomputing does not take it back: it is not a static ability.
    game._recompute_continuous_effects()
    assert attacker.effective_power == 4
    # And the creature that was not attacking at resolution never joins the set.
    latecomer.attacking = True
    game._recompute_continuous_effects()
    assert latecomer.effective_power == 3
