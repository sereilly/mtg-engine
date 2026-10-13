"""Odyssey enchantments — wave 2, group 4: Karmic Justice.

    Whenever a spell or ability an opponent controls destroys a noncreature
    permanent you control, you may destroy target permanent that opponent
    controls.

One card, and nothing it needed was about the card: destroying a permanent had
to become an event that says who caused it (``engine/destruction_events.py``).
The seam's own tests — the census over every destroy path in the pool, the
guards, the sites that went round it — are in
``tests/regressions/test_ody_w2g4_destroy_seam.py``. What is here is the card,
driven through its whole text the way a game drives it.

Its rulings (Scryfall, both 2023-09-01):

* "Spells and abilities that cause you to sacrifice permanents will not cause
  Karmic Justice's ability to trigger."
* "If a spell or ability an opponent controls destroys Karmic Justice, Karmic
  Justice's ability will trigger."

Every board below is real cards out of their own sets; the only invented
objects are the plainest victims a test could not otherwise have (an
indestructible artifact, a creature with a regeneration shield on it).
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

_HOMES = {
    "Karmic Justice": "ODY", "Tremble": "ODY",
    "Disenchant": "LEA", "Tranquility": "LEA", "Wrath of God": "LEA",
    "Armageddon": "LEA", "Living Lands": "LEA", "Sol Ring": "LEA",
    "Crusade": "LEA", "Bad Moon": "LEA", "Island": "LEA", "Forest": "LEA",
    "Grizzly Bears": "LEA", "Nevinyrral's Disk": "LEA", "Mox Pearl": "LEA",
    "Steal Artifact": "LEA", "Lightning Bolt": "LEA", "Stone Rain": "LEA",
    "Purify": "ULG", "Yawgmoth's Agenda": "INV", "Vindicate": "APC",
    "Uktabi Orangutan": "VIS", "Cleansing": "DRK",
}

_TEXT = (
    "Whenever a spell or ability an opponent controls destroys a noncreature "
    "permanent you control, you may destroy target permanent that opponent "
    "controls."
)


def _card(set_pool, name: str):
    return set_pool(_HOMES[name])[name]


def _table(set_pool, *, seats: int = 2, interactive=()) -> Game:
    forest = _card(set_pool, "Forest")
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[forest] * 12) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _put(game, set_pool, seat: int, card) -> Permanent:
    perm = Permanent(card=_card(set_pool, card) if isinstance(card, str) else card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _cast(game, set_pool, seat: int, name: str, **announcement):
    game.players[seat].hand.append(_card(set_pool, name))
    game.active_player_index = seat
    result = game.queue_from_hand(seat, name, **announcement)
    assert result.supported, result.details
    return result


def _justice_triggers(game) -> list:
    return [
        item for item in game.stack
        if item.is_ability and item.card.name == "Karmic Justice"
    ]


def _names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _settle(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


# --- what it compiles to ---------------------------------------------------------


def test_karmic_justice_is_a_destroyed_trigger_with_both_narrowings_as_payload(set_pool):
    """The condition is CR 701.8's event; whose spell did it and what was
    destroyed are data on it, and the effect's "that opponent" is the seat the
    event froze — nothing here is a kind per card."""
    card = _card(set_pool, "Karmic Justice")
    assert card.oracle_text == _TEXT
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "permanent_destroyed"
    assert trigger.condition.payload == {
        "destroyed_cause": "an opponent",
        "destroyed_filter": {"exclude_types": ["creature"], "controller": "you"},
    }
    assert trigger.instruction.kind == "may"
    (destroy,) = trigger.instruction.payload["action"]
    assert destroy.kind == "destroy_target_permanent"
    assert destroy.payload["targets"]["filter"] == {"controller": "that_player"}


# --- an opponent's spell ---------------------------------------------------------


def test_an_opponents_disenchant_on_your_artifact_triggers_it(set_pool):
    """The whole card, as two people play it. The trigger goes on the stack
    once Disenchant has finished; its target is chosen *then*, out of the
    permanents the Disenchant's caster controls and nobody else's; and "you
    may" is asked as it resolves."""
    game = _table(set_pool, interactive=(0, 1))
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    mine = _put(game, set_pool, 0, "Grizzly Bears")
    theirs = _put(game, set_pool, 1, "Grizzly Bears")
    mox = _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    assert _justice_triggers(game) == []          # nothing has been destroyed yet
    assert game.resolve_top_of_stack(pause_for_choices=True)

    assert _names(game.players[0].graveyard) == ["Sol Ring"]
    (trigger,) = _justice_triggers(game)
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("trigger_target", 0)
    assert {entry["permanent_id"] for entry in choice.data["targets"]} == {
        theirs.permanent_id, mox.permanent_id,
    }
    # Its own controller's permanent is not one "that opponent controls".
    assert not game.confirm_trigger_target(0, permanent_id=mine.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=mox.permanent_id)
    assert trigger.target_permanent_id == mox.permanent_id

    assert game.resolve_top_of_stack(pause_for_choices=True)
    (offer,) = game.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 0)
    assert game.is_on_battlefield(mox)            # "may": nothing until it is taken
    assert game.confirm_optional_pay(0, accept=True)
    _settle(game)

    assert not game.is_on_battlefield(mox)
    assert _names(game.players[1].graveyard) == ["Disenchant", "Mox Pearl"]
    assert game.is_on_battlefield(theirs) and game.is_on_battlefield(mine)


def test_you_may_means_you_may_not(set_pool):
    game = _table(set_pool, interactive=(0, 1))
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    mox = _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, permanent_id=mox.permanent_id)
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=False)
    _settle(game)

    assert game.is_on_battlefield(mox)
    assert game.stack == []


def test_your_own_disenchant_on_your_artifact_does_not(set_pool):
    """"…a spell or ability **an opponent** controls". The destruction is
    announced all the same — the seam does not know who is watching — and the
    cause it names is the watcher's own seat."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    mox = _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 0, "Disenchant", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()

    assert _names(game.players[0].graveyard) == ["Sol Ring", "Disenchant"]
    assert _justice_triggers(game) == []
    assert game.is_on_battlefield(mox)


def test_an_opponents_ability_counts_as_much_as_a_spell(set_pool):
    """"A spell **or ability**": Uktabi Orangutan's entry trigger is an ability
    its controller controls (CR 109.5)."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Uktabi Orangutan", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()                   # the Orangutan enters
    assert _justice_triggers(game) == []
    game.resolve_top_of_stack()                   # its trigger destroys the Ring

    assert not game.is_on_battlefield(ring)
    (trigger,) = _justice_triggers(game)
    assert trigger.trigger_context["cause_seat"] == 1


def test_the_trigger_with_nothing_to_target_is_removed_from_the_stack(set_pool):
    """CR 603.3d: "If a choice is required when the triggered ability goes on
    the stack but no legal choices can be made for it … the ability is simply
    removed from the stack." The opponent controls nothing."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()

    assert game.stack == []
    assert game.pending_choices == []
    assert any(
        "Karmic Justice's triggered ability was removed from the stack" in line
        and "603.3d" in line
        for line in game.log
    ), game.log


# --- in response to it -----------------------------------------------------------
#
# The ability is a stack object with a target, chosen through its own picker —
# so everything that can happen to a target before it resolves can happen to
# this one, and CR 608.2b is asked of it as the ability resolves.


def _trigger_aimed_at_the_mox(set_pool):
    game = _table(set_pool, interactive=(0, 1))
    justice = _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    mox = _put(game, set_pool, 1, "Mox Pearl")
    island = _put(game, set_pool, 1, "Island")
    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, permanent_id=mox.permanent_id)
    (trigger,) = _justice_triggers(game)
    assert trigger.targets_chosen
    return game, justice, mox, island


@pytest.mark.parametrize("response", ["the target leaves", "the target changes hands"])
def test_a_target_that_is_illegal_by_resolution_is_not_replaced_with_a_bystander(
    set_pool, response,
):
    """CR 608.2b. The Mox is gone, or is no longer one "that opponent
    controls" — the description is re-asked with the seat the event froze —
    so the ability is removed from the stack. The Island beside it was never
    the target and is not destroyed in its place."""
    game, _justice, mox, island = _trigger_aimed_at_the_mox(set_pool)
    if response == "the target leaves":
        game.remove_from_battlefield(mox)
    else:
        game.take_control(mox, 0, source=mox)

    assert game.resolve_top_of_stack(pause_for_choices=True)

    assert game.stack == [] and game.pending_choices == []
    assert game.is_on_battlefield(island)
    assert response == "the target leaves" or game.is_on_battlefield(mox)
    assert any("608.2b" in line for line in game.log), game.log


def test_destroying_karmic_justice_in_response_does_not_stop_its_ability(set_pool):
    """CR 113.7a: "Once activated or triggered, an ability exists on the stack
    independently of its source." """
    game, justice, mox, _island = _trigger_aimed_at_the_mox(set_pool)
    game.remove_from_battlefield(justice)
    game._permanent_to_graveyard(game.players[0], justice)

    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)

    assert not game.is_on_battlefield(mox)


# --- what is and is not a destruction of a noncreature permanent -------------------


def test_a_sweep_over_creatures_does_not_and_an_animated_land_is_a_creature(set_pool):
    """Wrath of God over a Grizzly Bears and a Forest that Living Lands has
    made a 1/1: both are creatures **at the moment they are destroyed**
    (CR 603.10a looks back at the permanent as it last existed on the
    battlefield, and its types there are CR 613's), so neither is a
    "noncreature permanent"."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Living Lands")
    forest = _put(game, set_pool, 0, "Forest")
    island = _put(game, set_pool, 0, "Island")
    _put(game, set_pool, 0, "Grizzly Bears")
    _put(game, set_pool, 1, "Mox Pearl")
    assert forest.is_creature and not island.is_creature

    _cast(game, set_pool, 1, "Wrath of God")
    game.resolve_top_of_stack()

    assert _names(game.players[0].graveyard) == ["Forest", "Grizzly Bears"]
    assert _justice_triggers(game) == []


def test_the_same_forest_destroyed_as_a_land_is_still_a_creature(set_pool):
    """Armageddon takes the animated Forest and the plain Island together. The
    Island is a noncreature permanent and triggers it; the Forest is a land
    that is a creature, and does not — once, not twice."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Living Lands")
    _put(game, set_pool, 0, "Forest")
    _put(game, set_pool, 0, "Island")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Armageddon")
    game.resolve_top_of_stack()

    assert _names(game.players[0].graveyard) == ["Forest", "Island"]
    (trigger,) = _justice_triggers(game)
    assert trigger.trigger_context["event_subject_name"] == "Island"


def test_a_sacrifice_does_not_trigger_it(set_pool):
    """Its first ruling. Tremble — "Each player sacrifices a land of their
    choice" — is an opponent's spell putting your land into your graveyard,
    and CR 701.21a: "Sacrificing a permanent doesn't destroy it"."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Island")
    _put(game, set_pool, 1, "Island")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Tremble")
    _settle(game)

    assert _names(game.players[0].graveyard) == ["Island"]
    assert not any("Karmic Justice" in line for line in game.log), game.log


def test_an_indestructible_permanent_was_not_destroyed(set_pool):
    """CR 702.12b: "A permanent with indestructible can't be destroyed." The
    Disenchant resolves and nothing happens to it — so nothing is announced."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    relic = _put(game, set_pool, 0, dataclasses.replace(
        _mk_card(
            name="Unbreakable Relic", type_line="Artifact",
            oracle_text="Indestructible",
        ),
        keywords=("Indestructible",),
    ))
    _put(game, set_pool, 1, "Mox Pearl")
    assert game._is_indestructible(relic)

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[relic.permanent_id])
    game.resolve_top_of_stack()

    assert game.is_on_battlefield(relic)
    assert _justice_triggers(game) == []


def test_a_regenerated_permanent_was_not_destroyed(set_pool):
    """CR 701.8c: "A regeneration effect replaces a destruction event." Vindicate
    ("Destroy target permanent") on an artifact with a regeneration shield:
    the shield is spent, the artifact stays, and nothing was destroyed."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    ring.regeneration_shield = 1
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Vindicate", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()

    assert game.is_on_battlefield(ring)
    assert ring.regeneration_shield == 0
    assert _justice_triggers(game) == []


def test_a_land_whose_destruction_was_replaced_was_not_destroyed(set_pool):
    """Pyramids: "The next time target land would be destroyed this turn,
    remove all damage marked on it instead." The third thing that replaces a
    destruction, and the same answer as the other two: the Stone Rain
    resolves, the Island stays, and nothing was destroyed. (The shield is set
    as the Pyramids' ability sets it; that ability has its own tests.)"""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    island = _put(game, set_pool, 0, "Island")
    island.metadata["land_destruction_shield_this_turn"] = True
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Stone Rain", target_permanent_ids=[island.permanent_id])
    game.resolve_top_of_stack()

    assert game.is_on_battlefield(island)
    assert "land_destruction_shield_this_turn" not in island.metadata
    assert _justice_triggers(game) == []


def test_a_destroyed_permanent_that_was_exiled_instead_was_still_destroyed(set_pool):
    """Yawgmoth's Agenda: "If a card would be put into your graveyard from
    anywhere, exile it instead." The Sol Ring never reaches a graveyard and
    was destroyed all the same — Fumigate's ruling (2024-11-08) counts
    "creatures destroyed this way … even if they're put into a zone other than
    a graveyard", and Rest in Peace's (2018-03-16) has a destroyed Rest in
    Peace "exiled"."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Yawgmoth's Agenda")
    ring = _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()

    assert game.players[0].graveyard == []
    assert _names(game.players[0].exile) == ["Sol Ring"]
    assert len(_justice_triggers(game)) == 1


def test_lethal_damage_is_a_destruction_no_spell_or_ability_performs(set_pool):
    """An opponent's Lightning Bolt on a land Living Lands animated — a
    noncreature card that is a creature, so the test below is about the
    *cause*: the Bolt deals damage and a state-based action destroys
    (CR 704.5g). No spell or ability destroyed anything, so a trigger that
    watches for one is silent whatever it watches."""
    game = _table(set_pool)
    watcher = _put(game, set_pool, 0, _mk_card(
        name="Test Vigil", type_line="Enchantment",
        oracle_text=(
            "Whenever a spell or ability an opponent controls destroys a "
            "permanent you control, you gain 1 life."
        ),
    ))
    _put(game, set_pool, 0, "Living Lands")
    forest = _put(game, set_pool, 0, "Forest")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Lightning Bolt", target_permanent_ids=[forest.permanent_id])
    game.resolve_top_of_stack()
    game.check_state_based_actions()
    _settle(game)

    assert not game.is_on_battlefield(forest)
    assert any("704.5g" in line for line in game.log), game.log
    assert game.players[0].life == 20
    assert watcher.card.name not in " ".join(game.log)


# --- the watcher leaving with what it watches (its second ruling) -------------------


def test_karmic_justice_destroyed_by_an_opponents_spell_triggers(set_pool):
    """Its second ruling, on its own."""
    game = _table(set_pool)
    justice = _put(game, set_pool, 0, "Karmic Justice")
    mox = _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[justice.permanent_id])
    game.resolve_top_of_stack()

    assert _names(game.players[0].graveyard) == ["Karmic Justice"]
    (trigger,) = _justice_triggers(game)
    assert trigger.target_permanent_id == mox.permanent_id
    _settle(game)
    assert not game.is_on_battlefield(mox)


def test_destroyed_alongside_it_triggers_once_for_each_itself_included(set_pool):
    """Tranquility takes Karmic Justice and a Crusade together, and an
    opposing Bad Moon with them. Two triggers — the Justice saw itself go and
    saw the Crusade go (CR 603.10a) — and both choose **after** the sweep, so
    neither can name the Bad Moon the same spell destroyed."""
    game = _table(set_pool, interactive=(0, 1))
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Crusade")
    _put(game, set_pool, 0, "Grizzly Bears")
    _put(game, set_pool, 1, "Bad Moon")
    island = _put(game, set_pool, 1, "Island")
    bears = _put(game, set_pool, 1, "Grizzly Bears")

    _cast(game, set_pool, 1, "Tranquility")
    assert game.resolve_top_of_stack(pause_for_choices=True)

    assert sorted(_names(game.players[0].graveyard)) == ["Crusade", "Karmic Justice"]
    assert len(_justice_triggers(game)) == 2
    assert sorted(
        item.trigger_context["event_subject_name"] for item in _justice_triggers(game)
    ) == ["Crusade", "Karmic Justice"]
    for choice in game.pending_choices:
        assert choice.kind == "trigger_target"
        assert {entry["permanent_id"] for entry in choice.data["targets"]} == {
            island.permanent_id, bears.permanent_id,
        }


def test_a_sweep_that_takes_its_victims_one_at_a_time_is_still_one_event(set_pool):
    """Purify ("Destroy all artifacts and enchantments") reaches the same seam
    by another road: its handler destroys each matching permanent in turn, so
    Karmic Justice is off the battlefield before the Sol Ring and the Crusade
    go. It was destroyed in the same event and looks back at all of it — three
    triggers, where a scan of the battlefield alone would find one."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 0, "Crusade")
    _put(game, set_pool, 1, "Island")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Purify")
    game.resolve_top_of_stack()

    assert sorted(_names(game.players[0].graveyard)) == [
        "Crusade", "Karmic Justice", "Sol Ring",
    ]
    assert sorted(
        item.trigger_context["event_subject_name"] for item in _justice_triggers(game)
    ) == ["Crusade", "Karmic Justice", "Sol Ring"]


def test_a_later_sentence_is_a_later_event_and_a_departed_justice_does_not_see_it(set_pool):
    """The look back is across one simultaneous destruction, not across a
    turn: a Karmic Justice destroyed by one spell is in the graveyard when the
    next one destroys the Sol Ring, and triggers for the first alone."""
    game = _table(set_pool)
    justice = _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 1, "Island")
    _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[justice.permanent_id])
    game.resolve_top_of_stack()
    assert len(_justice_triggers(game)) == 1
    _settle(game)

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()
    assert not game.is_on_battlefield(ring)
    assert _justice_triggers(game) == []


def test_an_opponents_activated_sweep_triggers_it_for_each_noncreature_permanent(set_pool):
    """Nevinyrral's Disk, activated by an opponent: an ability an opponent
    controls destroys the Justice, a Sol Ring and a Grizzly Bears. Two
    triggers (the creature is not one), and the Disk's own controller's
    artifacts are gone before either chooses."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 0, "Grizzly Bears")
    disk = _put(game, set_pool, 1, "Nevinyrral's Disk")
    disk.tapped = False
    island = _put(game, set_pool, 1, "Island")
    _put(game, set_pool, 1, "Mox Pearl")
    game.active_player_index = 1

    assert game.queue_permanent_ability(1, "Nevinyrral's Disk").supported
    game.resolve_top_of_stack()

    triggers = _justice_triggers(game)
    assert len(triggers) == 2
    assert {item.target_permanent_id for item in triggers} == {island.permanent_id}


# --- "that opponent" -------------------------------------------------------------


def test_at_four_seats_that_opponent_is_the_one_who_did_it(set_pool):
    """"…target permanent **that opponent** controls" — the player whose spell
    destroyed, not any opponent. Seat 2 casts the Disenchant; seats 1 and 3
    have the same board and are offered nothing of."""
    game = _table(set_pool, seats=4, interactive=(0, 1, 2, 3))
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    boards = {
        seat: [_put(game, set_pool, seat, "Mox Pearl"), _put(game, set_pool, seat, "Grizzly Bears")]
        for seat in (1, 2, 3)
    }

    _cast(game, set_pool, 2, "Disenchant", target_permanent_ids=[ring.permanent_id])
    assert game.resolve_top_of_stack(pause_for_choices=True)

    (trigger,) = _justice_triggers(game)
    assert trigger.trigger_context["cause_seat"] == 2
    (choice,) = game.pending_choices
    assert {entry["seat"] for entry in choice.data["targets"]} == {2}
    assert {entry["permanent_id"] for entry in choice.data["targets"]} == {
        perm.permanent_id for perm in boards[2]
    }
    assert not game.confirm_trigger_target(0, permanent_id=boards[1][0].permanent_id)
    assert not game.confirm_trigger_target(0, permanent_id=boards[3][0].permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=boards[2][0].permanent_id)


def test_a_permanent_you_took_is_one_you_control_and_one_they_took_is_not(set_pool):
    """"…a noncreature permanent **you control**" is control at the moment of
    destruction (CR 603.10a), not ownership. Seat 0 holds seat 1's Mox under a
    Steal Artifact, and seat 1 destroys its own card: that is seat 0's
    permanent, and the Justice triggers. Reversed — seat 1 holding seat 0's
    Sol Ring and destroying it — it is not."""
    game = _table(set_pool)
    _put(game, set_pool, 0, "Karmic Justice")
    mox = _put(game, set_pool, 1, "Mox Pearl")
    _put(game, set_pool, 1, "Island")
    game.take_control(mox, 0, source=mox)
    assert game.controller_index_of(mox) == 0

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[mox.permanent_id])
    game.resolve_top_of_stack()
    assert _names(game.players[1].graveyard) == ["Mox Pearl", "Disenchant"]
    assert len(_justice_triggers(game)) == 1
    _settle(game)

    ring = _put(game, set_pool, 0, "Sol Ring")
    game.take_control(ring, 1, source=ring)
    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    game.resolve_top_of_stack()
    assert not game.is_on_battlefield(ring)
    assert _justice_triggers(game) == []


def test_two_karmic_justices_answer_each_other(set_pool):
    """Seat 1's Disenchant destroys seat 0's Sol Ring; seat 0's Justice
    destroys a Mox of seat 1's — and that is an ability an opponent controls
    destroying a noncreature permanent seat 1 controls, so seat 1's own
    Justice triggers in turn."""
    game = _table(set_pool, interactive=(0, 1))
    _put(game, set_pool, 0, "Karmic Justice")
    ring = _put(game, set_pool, 0, "Sol Ring")
    crusade = _put(game, set_pool, 0, "Crusade")
    _put(game, set_pool, 1, "Karmic Justice")
    mox = _put(game, set_pool, 1, "Mox Pearl")

    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, permanent_id=mox.permanent_id)
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)

    assert not game.is_on_battlefield(mox)
    (answer,) = _justice_triggers(game)
    assert answer.caster_index == 1
    assert answer.trigger_context["cause_seat"] == 0
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("trigger_target", 1)
    assert game.confirm_trigger_target(1, permanent_id=crusade.permanent_id)
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=True)
    assert not game.is_on_battlefield(crusade)


# --- nothing here is keyed on the card ----------------------------------------------


@pytest.mark.parametrize("effect, check", [
    ("draw a card.", lambda game: len(game.players[0].hand) == 1),
    ("that player loses 2 life.", lambda game: [p.life for p in game.players] == [20, 18]),
    ("that opponent loses 2 life.", lambda game: [p.life for p in game.players] == [20, 18]),
    ("you gain 3 life.", lambda game: [p.life for p in game.players] == [23, 20]),
])
def test_an_invented_card_with_the_sentence_about_creatures_works_with_no_code(
    set_pool, effect, check,
):
    """"Whenever a spell or ability an opponent controls destroys **a creature**
    you control, …" — no card prints it. The noun phrase and the effect are
    both payload, and "that player" / "that opponent" is the seat the event
    froze: the caster of the Wrath, not a target and not a default."""
    game = _table(set_pool)
    _put(game, set_pool, 0, _mk_card(
        name="Test Requiem", type_line="Enchantment",
        oracle_text=(
            "Whenever a spell or ability an opponent controls destroys a "
            "creature you control, " + effect
        ),
    ))
    _put(game, set_pool, 0, "Grizzly Bears")
    _put(game, set_pool, 0, "Sol Ring")
    _put(game, set_pool, 1, "Grizzly Bears")

    _cast(game, set_pool, 1, "Wrath of God")
    _settle(game)

    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert check(game), game.log

    # …and the artifact beside it is not a creature.
    ring = next(p for p in game.controlled_by(0) if p.card.name == "Sol Ring")
    hand, lives = len(game.players[0].hand), [p.life for p in game.players]
    _cast(game, set_pool, 1, "Disenchant", target_permanent_ids=[ring.permanent_id])
    _settle(game)
    assert not game.is_on_battlefield(ring)
    assert (len(game.players[0].hand), [p.life for p in game.players]) == (hand, lives)


def test_another_keeps_the_watcher_out_of_what_it_watches(set_pool):
    """"…destroys **another** enchantment you control": the noun parser's own
    exclusion, so the watcher's destruction is not one of the events it
    answers to."""
    game = _table(set_pool)
    watcher = _put(game, set_pool, 0, _mk_card(
        name="Test Warden", type_line="Enchantment",
        oracle_text=(
            "Whenever a spell or ability an opponent controls destroys another "
            "enchantment you control, you gain 1 life."
        ),
    ))
    _put(game, set_pool, 0, "Crusade")
    _put(game, set_pool, 1, "Island")

    _cast(game, set_pool, 1, "Tranquility")
    _settle(game)

    assert not game.is_on_battlefield(watcher)
    assert game.players[0].life == 21             # the Crusade, and not itself
