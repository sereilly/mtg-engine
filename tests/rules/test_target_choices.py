"""Tests for Magic: The Gathering Comprehensive Rules Section 115 (targets) —
choosing them, counting them and changing them.

Covers:
  601.2c / 602.2b / 603.3d — a spell, an activated ability and a triggered
           ability each choose their targets as they go on the stack, and
           "a player chooses one or more targets" is announced exactly once for
           each
  115.6  — an object that may choose zero targets is targeted only if it chose
           one or more
  115.1b — an Aura spell is always targeted
  115.7a — a changed target must be another legal target, and a change is all
           of the targets or none of them
  115.7e / 115.3 — only the final set is judged; one instance of "target" names
           each object once
  115.7f — a division survives the change
  115.5  — an object on the stack is not a legal target for itself
  603.2  — a permanent chosen late (by a trigger's own prompt, by a retarget)
           still "becomes the target"
  603.10 — the trigger looks back at the object the targets were chosen for
  707.10 — a copy inherits its targets and chose none

Invented card names throughout, deliberately, for the reason
``test_becomes_target_triggers.py`` gives: every card here is read from a
printed template, so a test naming Psychic Battle could pass against a table
keyed by the name. "Test Arbiter" is that card's text under another name — and
its last sentence names *itself*, which is the only name the sentence can be
held to. Psychic Battle's own tests are in ``tests/sets/``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.stack_targets import (TARGETS_CHOSEN_ITEM, change_options,
                                  change_slots, chosen_targets)

from tests.helpers import _nosick, resolve_stack


def _card(name, type_line, text="", cmc=0, mana_cost="", power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(cmc), type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


_ARBITER_TEXT = (
    "Whenever a player chooses one or more targets, each player reveals the "
    "top card of their library. The player who reveals the card with the "
    "greatest mana value may change the target or targets. If two or more "
    "cards are tied for greatest, the target or targets remain unchanged. "
    "Changing targets this way doesn't trigger abilities of permanents named "
    "Test Arbiter."
)

_CARDS = {
    card.name: card
    for card in (
        _card("Test Arbiter", "Enchantment", _ARBITER_TEXT, 5, "{3}{U}{U}"),
        _card("Test Shock", "Instant", "Test Shock deals 2 damage to any target.", 1, "{R}"),
        _card("Test Growth", "Instant", "Target creature gets +3/+3 until end of turn.", 1, "{G}"),
        _card("Test Recall", "Instant", "Return two target creatures to their owners' hands.", 3, "{1}{U}{U}"),
        _card("Test Surge", "Sorcery", "Tap up to three target creatures.", 2, "{1}{U}"),
        _card("Test Arc", "Sorcery", "Test Arc deals 3 damage divided as you choose among one, two, or three targets.", 3, "{2}{R}"),
        _card("Test Counter", "Instant", "Counter target spell.", 2, "{U}{U}"),
        _card("Test Deflect", "Instant", "Change the target of target spell with a single target.", 4, "{3}{U}"),
        _card("Test Aura", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +1/+2.", 1, "{W}"),
        _card("Test Sweep", "Sorcery", "Destroy all creatures.", 4, "{2}{W}{W}"),
        _card("Test Charm", "Instant", "Choose one —\n• Target creature gets +2/+2 until end of turn.\n• You gain 4 life.", 1, "{G}"),
        _card("Test Duo", "Instant", "Destroy target artifact and target enchantment.", 3, "{1}{G}{W}"),
        _card("Test Pinger", "Creature — Wizard", "{T}: Test Pinger deals 1 damage to any target.", 3, "{2}{U}", 1, 1),
        _card("Test Assassin", "Creature — Assassin", "{T}: Destroy target tapped creature.", 3, "{1}{B}{B}", 1, 1),
        _card("Test Bouncer", "Creature — Jellyfish", "When Test Bouncer enters the battlefield, return target creature to its owner's hand.", 3, "{2}{U}", 2, 2),
        _card("Test Ghost", "Creature — Spirit", "When Test Ghost becomes the target of a spell or ability, sacrifice it.", 2, "{1}{B}", 2, 1),
        _card("Test Bear", "Creature — Bear", "", 2, "{1}{G}", 2, 2),
        _card("Test Ogre", "Creature — Ogre", "", 3, "{2}{R}", 3, 3),
        _card("Test Wall", "Creature — Wall", "", 1, "{W}", 0, 4),
        _card("Test Relic", "Artifact", "", 1, "{1}"),
        # What a library shows: one card of each mana value the tests compare.
        _card("Test Land", "Land"),
        _card("Test Six", "Sorcery", "Draw a card.", 6, "{5}{U}"),
    )
}

_LEA = None


def _lea():
    global _LEA
    if _LEA is None:
        _LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    return _LEA


def _table(*, seats=2, tops=None, hands=None, boards=None, interactive=(), arbiters=(0,)):
    """A table with a Test Arbiter per entry of *arbiters*.

    ``tops[i]`` is the card on top of seat *i*'s library (the whole library is
    that card, so a reveal after a draw shows it too); ``None`` is an empty
    library. Returns the game and every permanent keyed by (seat, name).
    """
    tops = tops or ["Test Land"] * seats
    hands = hands or [[] for _ in range(seats)]
    boards = boards or [[] for _ in range(seats)]
    players, placed = [], {}
    for seat in range(seats):
        battlefield = []
        names = list(boards[seat]) + ["Test Arbiter"] * list(arbiters).count(seat)
        for name in names:
            permanent = _nosick(Permanent(card=_CARDS[name]))
            battlefield.append(permanent)
            placed.setdefault((seat, name), []).append(permanent)
        players.append(PlayerState(
            name=f"P{seat}", life=20, battlefield=battlefield,
            hand=[_CARDS.get(name) or _lea()[name] for name in hands[seat]],
            library=[_CARDS[tops[seat]]] * 6 if tops[seat] else [],
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    resolve_stack(game)
    return game, placed


def _arbiter_triggers(game):
    """The Test Arbiter abilities on the stack, bottom first."""
    return [
        item for item in game.stack
        if item.is_ability and item.card.name == "Test Arbiter"
    ]


def _options(game):
    """The retarget prompt's live options as (position, kind, option)."""
    choice = game.pending_choice_of("retarget_choice")
    assert choice is not None, f"no retarget prompt; owed {[c.kind for c in game.pending_choices]}"
    return choice, [
        (position, choice.data["options"][position])
        for position in game.live_retarget_choices(choice)
    ]


def _answer_permanent(game, permanent):
    choice, options = _options(game)
    position = next(
        position for position, option in options
        if option.get("permanent_id") == permanent.permanent_id
    )
    assert game.confirm_retarget_choice(choice.player_index, position)


def _answer_kind(game, kind, seat=None):
    choice, options = _options(game)
    position = next(
        position for position, option in options
        if option.get("kind") == kind and (seat is None or option.get("seat") == seat)
    )
    assert game.confirm_retarget_choice(choice.player_index, position)


# ---------------------------------------------------------------------------
# Choosing: one announcement per object, and only for an object that chose
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2c", "603.10")
def test_a_spells_targets_trigger_once_and_the_trigger_names_that_spell():
    """"The player announces their choice of an appropriate object or player
    for each target the spell requires." The ability triggers once, goes on
    the stack above the spell — so it resolves first — and what it looks back
    at is that very stack object, by identity."""
    game, placed = _table(hands=[["Test Shock"], []], boards=[[], ["Test Bear"]])
    bear = placed[(1, "Test Bear")][0]

    assert game.queue_from_hand(0, "Test Shock", target_permanent_ids=[bear.permanent_id]).supported

    triggers = _arbiter_triggers(game)
    assert len(triggers) == 1
    assert game.stack[-1] is triggers[0], "the trigger resolves before the spell"
    shock = game.stack[0]
    assert shock.card.name == "Test Shock"
    assert triggers[0].trigger_context[TARGETS_CHOSEN_ITEM] is shock


@pytest.mark.cr("602.2b")
def test_an_activated_abilitys_target_triggers_it():
    """"Those rules apply to activating an ability just as they apply to
    casting a spell" — CR 601.2c's choice among them."""
    game, placed = _table(boards=[["Test Pinger"], ["Test Bear"]])
    bear = placed[(1, "Test Bear")][0]

    result = game.queue_permanent_ability(
        0, "Test Pinger", target_permanent_ids=[bear.permanent_id]
    )

    assert result.supported, result.details
    triggers = _arbiter_triggers(game)
    assert len(triggers) == 1
    chosen = triggers[0].trigger_context[TARGETS_CHOSEN_ITEM]
    assert chosen.is_ability and chosen.card.name == "Test Pinger"


@pytest.mark.cr("603.3d")
@pytest.mark.parametrize("interactive", [(), (0,)], ids=["default-at-arm", "asked"])
def test_a_triggered_abilitys_target_triggers_it_once_however_it_is_answered(interactive):
    """"The remainder of the process for putting a triggered ability on the
    stack is identical to the process for casting a spell listed in rules
    601.2c–d." A seat the engine plays answers as the ability is pushed and a
    player answers a prompt later; either way there is one choice and one
    trigger — and none before the choice is made."""
    game, placed = _table(boards=[[], ["Test Bear"]], interactive=interactive)
    bear = placed[(1, "Test Bear")][0]
    bouncer = Permanent(card=_CARDS["Test Bouncer"])
    # Put onto the battlefield without being cast: nobody announced a target
    # for the entry trigger, so it goes on the stack and chooses its own.
    game._put_permanent_onto_battlefield(0, bouncer, 0)

    if interactive:
        assert game.pending_choice_of("trigger_target") is not None
        assert _arbiter_triggers(game) == [], "nothing has been chosen yet"
        assert game.confirm_trigger_target(0, permanent_id=bear.permanent_id)

    triggers = _arbiter_triggers(game)
    assert len(triggers) == 1
    chosen = triggers[0].trigger_context[TARGETS_CHOSEN_ITEM]
    assert chosen.card.name == "Test Bouncer" and chosen.is_ability
    assert [target.kind for target in chosen_targets(game, chosen)] == ["permanent"]


@pytest.mark.cr("115.6")
def test_an_object_that_chose_no_targets_is_not_targeted():
    """"A spell or ability that requires targets may allow zero targets to be
    chosen. Such a spell or ability … is targeted only if one or more targets
    have been chosen for it." A sweep, an "up to three" naming nobody and a
    modal spell's untargeted mode each choose none."""
    game, placed = _table(
        hands=[["Test Sweep", "Test Surge", "Test Charm"], []],
        boards=[["Test Bear"], ["Test Bear"]],
    )

    assert game.queue_from_hand(0, "Test Surge").supported
    assert game.queue_from_hand(0, "Test Charm", mode_index=1).supported
    assert game.queue_from_hand(0, "Test Sweep").supported

    assert _arbiter_triggers(game) == []
    assert [chosen_targets(game, item) for item in game.stack] == [(), (), ()]


@pytest.mark.cr("115.6", "115.8")
def test_the_same_objects_trigger_once_they_do_choose():
    """The other half of the test above, on the same two cards: "up to three"
    naming one creature, and the modal spell's targeted mode."""
    game, placed = _table(
        hands=[["Test Surge", "Test Charm"], []],
        boards=[["Test Bear"], ["Test Bear"]],
    )
    theirs, mine = placed[(1, "Test Bear")][0], placed[(0, "Test Bear")][0]

    assert game.queue_from_hand(0, "Test Surge", target_permanent_ids=[theirs.permanent_id]).supported
    assert len(_arbiter_triggers(game)) == 1
    assert game.queue_from_hand(
        0, "Test Charm", mode_index=0, target_permanent_ids=[mine.permanent_id]
    ).supported
    assert len(_arbiter_triggers(game)) == 2


@pytest.mark.cr("115.1b")
def test_an_aura_spell_is_targeted_though_it_prints_no_target():
    """"Aura spells are always targeted. An Aura's target is specified by its
    enchant keyword ability." """
    game, placed = _table(hands=[["Test Aura"], []], boards=[["Test Bear"], []])
    bear = placed[(0, "Test Bear")][0]

    assert game.queue_from_hand(0, "Test Aura", target_permanent_ids=[bear.permanent_id]).supported

    assert len(_arbiter_triggers(game)) == 1
    aura = game.stack[0]
    assert [t.permanent_id for t in chosen_targets(game, aura)] == [bear.permanent_id]


@pytest.mark.cr("707.10")
def test_a_copy_that_keeps_the_originals_targets_chose_none():
    """"A copy of a spell or ability copies … all decisions made for it,
    including modes, targets". Fork chooses a target (the spell) and triggers;
    the copy it makes was aimed by nobody and does not."""
    game, placed = _table(
        hands=[["Test Shock", "Fork"], []], boards=[[], ["Test Bear"]],
        arbiters=(),
    )
    bear = placed[(1, "Test Bear")][0]
    assert game.queue_from_hand(0, "Test Shock", target_permanent_ids=[bear.permanent_id]).supported
    # The observer arrives only now, so the Shock's own choice is not counted.
    arbiter = _nosick(Permanent(card=_CARDS["Test Arbiter"]))
    game._put_permanent_onto_battlefield(0, arbiter, 0)

    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    assert len(_arbiter_triggers(game)) == 1, "Fork chose a target"
    resolve_stack(game)

    assert bear.damage_marked == 4, "the copy and the original both hit the Bear"
    assert game.players[1].life == 20, "and neither hit its controller"
    # One trigger for Fork's choice and none for the copy: every reveal the
    # log holds belongs to that one resolution.
    reveals = [line for line in game.log if line.startswith("P0 revealed")]
    assert len(reveals) == 1


# ---------------------------------------------------------------------------
# Changing: CR 115.7
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.7a")
def test_a_target_changes_only_to_another_legal_target():
    """"Each target can be changed only to another legal target." For "target
    **tapped** creature" that is the other tapped creatures and nothing else —
    the creature already targeted is not "another", and an untapped one was
    never legal."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        boards=[["Test Assassin", "Test Wall"], ["Test Bear", "Test Ogre"]],
        interactive=(1,),
    )
    bear, ogre = placed[(1, "Test Bear")][0], placed[(1, "Test Ogre")][0]
    wall = placed[(0, "Test Wall")][0]
    bear.tapped = wall.tapped = True

    assert game.activate_permanent_ability(
        0, "Test Assassin", target_permanent_ids=[bear.permanent_id]
    ).supported
    _choice, options = _options(game)

    offered = {option.get("permanent_id") for _pos, option in options if option["kind"] == "permanent"}
    assassin = placed[(0, "Test Assassin")][0]
    # The Wall, and the Assassin itself — tapped for its own cost, so by now a
    # tapped creature like any other. Not the Bear (already the target) and
    # not the untapped Ogre.
    assert offered == {wall.permanent_id, assassin.permanent_id}
    assert ogre.permanent_id not in offered and bear.permanent_id not in offered

    _answer_permanent(game, wall)
    resolve_stack(game)

    assert not game.is_on_battlefield(wall), game.log
    assert game.is_on_battlefield(bear)


@pytest.mark.cr("115.7a")
def test_with_no_other_legal_target_the_target_is_unchanged():
    """"If a target can't be changed to another legal target, the original
    target is unchanged." One tapped creature on the table: nothing is
    offered, and the ability resolves as announced."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        boards=[["Test Assassin"], ["Test Bear"]],
        interactive=(1,),
    )
    bear = placed[(1, "Test Bear")][0]
    bear.tapped = True
    # The Assassin's own tap is what would make it a second tapped creature;
    # give it shroud-by-absence instead: remove it once the ability is queued.
    assert game.queue_permanent_ability(
        0, "Test Assassin", target_permanent_ids=[bear.permanent_id]
    ).supported
    game.remove_from_battlefield(placed[(0, "Test Assassin")][0])

    resolve_stack(game)

    assert game.pending_choice_of("retarget_choice") is None
    assert not game.is_on_battlefield(bear)
    assert any("no other legal targets" in line for line in game.log), game.log


@pytest.mark.cr("115.7a")
def test_every_target_changes_or_none_does():
    """"If all the targets aren't changed to other legal targets, none of them
    are changed." Two targets and exactly one other creature: no complete
    change exists, so nothing is offered and both original targets resolve."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Recall"], []],
        boards=[[], ["Test Bear", "Test Ogre"]],
        interactive=(1,),
        arbiters=(0,),
    )
    bear, ogre = placed[(1, "Test Bear")][0], placed[(1, "Test Ogre")][0]

    assert game.queue_from_hand(
        0, "Test Recall", target_permanent_ids=[bear.permanent_id, ogre.permanent_id]
    ).supported
    recall = game.stack[0]
    slots = change_slots(game, recall)
    # Each slot's only "other" creature is its partner, and exchanging the two
    # *is* a complete change (CR 115.7e judges the final set) — so take the
    # partner away for one of them and nothing is left.
    assert [len(slot.candidates) for slot in slots] == [1, 1]
    assert len(change_options(slots, [])) == 1

    game.remove_from_battlefield(ogre)
    assert change_options(change_slots(game, recall), []) == []
    resolve_stack(game)

    assert game.pending_choice_of("retarget_choice") is None
    assert [c.name for c in game.players[1].hand] == ["Test Bear"]


@pytest.mark.cr("115.7e", "115.3")
def test_two_targets_may_be_exchanged_but_not_doubled():
    """"Only the final set of targets is evaluated" — so each of two targets
    may become the other — and "the same target can't be chosen multiple times
    for any one instance of the word 'target'": once the first slot takes a
    creature, the second is not offered it."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Recall"], []],
        boards=[["Test Wall"], ["Test Bear", "Test Ogre"]],
        interactive=(1,),
    )
    bear, ogre = placed[(1, "Test Bear")][0], placed[(1, "Test Ogre")][0]
    wall = placed[(0, "Test Wall")][0]

    assert game.cast_from_hand(
        0, "Test Recall", target_permanent_ids=[bear.permanent_id, ogre.permanent_id]
    ).supported
    _choice, first = _options(game)
    assert {o.get("permanent_id") for _p, o in first if o["kind"] == "permanent"} == {
        ogre.permanent_id, wall.permanent_id,
    }
    _answer_permanent(game, wall)
    # The Wall is taken, so the Ogre's slot has one legal answer left — the
    # Bear, which is "another" target for *that* slot — and a choice with one
    # answer is not asked. Declining is no longer on offer mid-change either.
    assert game.pending_choice_of("retarget_choice") is None
    resolve_stack(game)

    assert [c.name for c in game.players[0].hand] == ["Test Wall"]
    assert [c.name for c in game.players[1].hand] == ["Test Bear"]
    assert game.is_on_battlefield(ogre)


@pytest.mark.cr("115.7f")
def test_the_division_stays_with_the_slot_it_was_announced_for():
    """"When changing targets … for that spell or ability, the original
    division can't be changed." 2 and 1 announced; the 2 follows the first
    target to a face and the 1 follows the second to a creature."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Arc"], []],
        boards=[["Test Ogre"], ["Test Bear", "Test Wall"]],
        interactive=(1,),
    )
    bear, wall = placed[(1, "Test Bear")][0], placed[(1, "Test Wall")][0]
    ogre = placed[(0, "Test Ogre")][0]

    assert game.cast_from_hand(
        0, "Test Arc",
        divided_targets=[
            (1, game.battlefield_index_of(bear), 2),
            (1, game.battlefield_index_of(wall), 1),
        ],
    ).supported
    _answer_kind(game, "player", seat=0)
    _answer_permanent(game, ogre)
    resolve_stack(game)

    assert game.players[0].life == 18
    assert ogre.damage_marked == 1
    assert bear.damage_marked == 0 and wall.damage_marked == 0


@pytest.mark.cr("115.5")
def test_a_spell_cannot_be_re_aimed_at_itself():
    """"A spell or ability on the stack is an illegal target for itself."
    A counterspell pointing at the only other spell has nowhere else to go —
    the trigger above it is an ability, and the counterspell is itself."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Shock"], ["Test Counter"]],
        interactive=(1,),
    )
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    # Let the Shock's own trigger finish first (P1 keeps the target).
    game._settle()
    _answer_kind(game, "keep")
    assert game.queue_from_hand(1, "Test Counter", target_stack_index=0).supported

    counter = next(item for item in game.stack if item.card.name == "Test Counter")
    slots = change_slots(game, counter)
    assert [len(slot.candidates) for slot in slots] == [0]


@pytest.mark.cr("115.5", "115.7a")
def test_a_counterspell_moves_to_another_spell_when_there_is_one():
    """…and with a second spell on the stack that is the one legal change."""
    game, placed = _table(
        tops=["Test Six", "Test Land"],
        hands=[["Test Shock", "Test Growth"], ["Test Counter"]],
        boards=[["Test Bear"], []],
        interactive=(0,),
        arbiters=(),
    )
    bear = placed[(0, "Test Bear")][0]
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    assert game.queue_from_hand(0, "Test Growth", target_permanent_ids=[bear.permanent_id]).supported
    arbiter = _nosick(Permanent(card=_CARDS["Test Arbiter"]))
    game._put_permanent_onto_battlefield(1, arbiter, 1)
    growth = game.stack[-1]
    # The engine's stack index counts from the bottom: the Shock is 0.
    assert game.queue_from_hand(1, "Test Counter", target_stack_index=1).supported
    counter = game.stack[-2]
    assert counter.target_stack_item is growth

    game._settle()
    _choice, options = _options(game)
    assert [o["kind"] for _p, o in options] == ["keep", "stack"]
    _answer_kind(game, "stack")
    resolve_stack(game)

    assert game.players[1].life == 20, "the Shock was countered instead"
    assert bear.effective_power == 5, "the Growth resolved"


@pytest.mark.cr("115.7a", "115.3")
def test_an_object_printing_target_twice_is_left_as_announced():
    """Two instances of the word are two descriptions, and each may be changed
    only within its own. This engine keeps one description per announcement,
    so it declines the change — "the targets remain unchanged", which CR 115.7a
    always permits — rather than offer one slot the other's candidates."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Duo"], []],
        boards=[["Test Relic", "Test Relic"], []],
        interactive=(1,),
    )
    relic = placed[(0, "Test Relic")][0]
    arbiter = placed[(0, "Test Arbiter")][0]

    result = game.queue_from_hand(
        0, "Test Duo", target_permanent_ids=[relic.permanent_id, arbiter.permanent_id]
    )
    assert result.supported, result.details
    duo = game.stack[0]
    assert len(chosen_targets(game, duo)) == 2
    assert isinstance(change_slots(game, duo), str)
    assert len(_arbiter_triggers(game)) == 1, "it still chose targets"


# ---------------------------------------------------------------------------
# What a changed or late-chosen target sets off
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.2", "603.3d")
@pytest.mark.parametrize("interactive", [(), (0,)], ids=["default-at-arm", "asked"])
def test_a_target_a_trigger_chose_becomes_the_target(interactive):
    """"Whenever a game event … matches a triggered ability's trigger event,
    that ability automatically triggers." A triggered ability's target is
    chosen after the ability is on the stack in this engine, and the permanent
    it then points at has become the target of an ability all the same."""
    game, placed = _table(boards=[[], ["Test Ghost"]], interactive=interactive, arbiters=())
    ghost = placed[(1, "Test Ghost")][0]
    bouncer = Permanent(card=_CARDS["Test Bouncer"])
    # Put onto the battlefield without being cast: nobody announced a target
    # for the entry trigger, so it goes on the stack and chooses its own.
    game._put_permanent_onto_battlefield(0, bouncer, 0)
    if interactive:
        assert game.confirm_trigger_target(0, permanent_id=ghost.permanent_id)
    resolve_stack(game)

    # Sacrificed by its own trigger, which resolved first — not bounced.
    assert [c.name for c in game.players[1].graveyard] == ["Test Ghost"]
    assert game.players[1].hand == []


@pytest.mark.cr("603.2", "115.7a")
def test_a_permanent_a_spell_is_re_aimed_at_becomes_the_target():
    """The same event reached through CR 115.7a: a retarget moves a spell onto
    a permanent, and that permanent has become the target of a spell."""
    game, placed = _table(
        hands=[["Test Growth"], ["Test Deflect"]],
        boards=[["Test Bear"], ["Test Ghost"]],
        arbiters=(),
    )
    bear, ghost = placed[(0, "Test Bear")][0], placed[(1, "Test Ghost")][0]
    assert game.queue_from_hand(0, "Test Growth", target_permanent_ids=[bear.permanent_id]).supported
    assert game.queue_from_hand(1, "Test Deflect", target_stack_index=0).supported
    resolve_stack(game)

    assert [c.name for c in game.players[1].graveyard if c.name == "Test Ghost"] == ["Test Ghost"]
    assert bear.effective_power == 2, "the Growth left the Bear"


@pytest.mark.cr("115.7a", "601.2c")
def test_a_retarget_is_a_choice_of_targets_and_the_arbiters_own_change_is_silent():
    """A spell re-aimed by another effect has had a target chosen for it, so
    the watcher triggers again. Its **own** change is the one exception it
    prints — "doesn't trigger abilities of permanents named" itself — and that
    covers a second copy of it on the table."""
    game, placed = _table(
        tops=["Test Six", "Test Land"],
        hands=[["Test Shock"], ["Test Deflect"]],
        boards=[["Test Bear"], ["Test Bear"]],
        arbiters=(0, 1),
    )
    theirs = placed[(1, "Test Bear")][0]
    assert game.queue_from_hand(0, "Test Shock", target_permanent_ids=[theirs.permanent_id]).supported
    assert len(_arbiter_triggers(game)) == 2, "one per watcher"
    resolve_stack(game)
    reveals_before = sum(1 for line in game.log if line.startswith("P0 revealed"))
    assert reveals_before == 2

    game.players[0].hand.append(_CARDS["Test Shock"])
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    assert game.queue_from_hand(1, "Test Deflect", target_stack_index=0).supported
    # Shock: 2 triggers. Deflect: 2 triggers. Deflect's re-aim: 2 more. Each
    # trigger reveals once; no change a watcher makes adds any.
    resolve_stack(game)
    reveals = sum(1 for line in game.log if line.startswith("P0 revealed")) - reveals_before
    assert reveals == 6, game.log


@pytest.mark.cr("603.10")
def test_each_trigger_looks_back_at_its_own_look_alike():
    """Two identical spells aimed at one player are *equal* stack objects, so
    the trigger carries the object itself. The first trigger to resolve
    changes its own spell and leaves the other exactly as announced."""
    game, placed = _table(
        tops=["Test Land", "Test Six"],
        hands=[["Test Shock", "Test Shock"], []],
        interactive=(1,),
    )
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    game._settle()
    _answer_kind(game, "keep")
    first = game.stack[0]
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    second = next(item for item in game.stack if item.card.name == "Test Shock" and item is not first)
    assert first == second and first is not second

    game._settle()
    _answer_kind(game, "player", seat=0)
    resolve_stack(game)

    # The second Shock went to P0's face; the first still hit P1.
    assert [player.life for player in game.players] == [18, 18]
