"""Regressions: a target that became illegal before the object naming it
resolved (CR 608.2b), on shipped cards.

The pool-wide census is ``tests/engine/test_ability_target_resolution_census.py``.
These are the anecdotes it was written from, one per shape, each asserting what
a game showed:

* **the tail** — Orcish Artillery dealt its 3 damage to its controller for 2
  damage it never dealt;
* **the bystander** — Circle of Despair shielded a *player* when the creature
  it named had left; a Prodigal Sorcerer aimed by a battlefield slot pinged
  whatever slid into it;
* **targetability** — Icy Manipulator tapped an artifact that had gained
  shroud;
* **one of several** — Alexi, Zephyr Mage returned a creature given shroud in
  response beside the one that was still legal, and Reckless Spite destroyed
  the creature given protection from black;
* **the printed exception** — Gilded Drake ("This ability still resolves if
  its target becomes illegal") is the one object the rule does not remove, and
  it exchanged itself for a creature nobody chose.

Every one of these failed on the tree before the gate
(``legality.ability_targets_refusal``) and the blanking
(``legality.blank_illegal_resolution_targets``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.keywords import grant_keyword
from engine.models import Permanent
from tests.helpers import resolve_stack

_REMOVED = "every target is illegal (608.2b)"


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(catalog_by_name, *, hand=(), library=("Forest",) * 6) -> Game:
    """Two seats nobody answers prompts for, costs waived, seat 0 to act."""
    game = Game(players=[
        PlayerState(
            name="P0", hand=[catalog_by_name[name] for name in hand],
            library=[catalog_by_name[name] for name in library],
        ),
        PlayerState(name="P1", library=[catalog_by_name[name] for name in library]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game


def _leave(game, permanent) -> None:
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game.players[seat].graveyard.append(permanent.card)


# ---------------------------------------------------------------------------
# Every target illegal: the ability does not resolve
# ---------------------------------------------------------------------------


def test_orcish_artillery_does_not_shoot_its_controller_for_a_shot_that_never_landed(
    catalog_by_name,
):
    """"{T}: This creature deals 2 damage to any target and 3 damage to you."
    One sentence, one target: with the creature it was aimed at gone, the
    ability does not resolve and the 3 damage is not dealt either."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Orcish Artillery"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Orcish Artillery", target_permanent_ids=[bears.permanent_id],
    ).supported
    _leave(game, bears)
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert [player.life for player in game.players] == [20, 20]


def test_circle_of_despair_does_not_shield_a_player_for_a_creature_that_left(
    catalog_by_name,
):
    """"The next time a source of your choice would deal damage to **any
    target** this turn, prevent that damage." Aimed at a creature that then
    leaves, it used to hand the shield to that creature's controller — a
    player nobody named."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Circle of Despair"])
    _put(game, 0, catalog_by_name["Savannah Lions"])  # the creature it sacrifices
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Circle of Despair", target_permanent_ids=[bears.permanent_id],
    ).supported
    _leave(game, bears)
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert not any("will prevent the next damage" in line for line in game.log), game.log[-4:]


def test_a_target_named_by_slot_is_not_replaced_by_what_slid_into_the_slot(catalog_by_name):
    """The index half of an announcement. Prodigal Sorcerer is aimed at seat
    1's first creature by its battlefield slot; that creature leaves, and the
    Hill Giant behind it becomes slot 0. The id stamped at announcement names
    nothing, and the slot is not consulted in its place."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Prodigal Sorcerer"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _put(game, 1, catalog_by_name["Hill Giant"])

    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1, target_permanent_index=0,
    ).supported
    _leave(game, bears)
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert giant.damage_marked == 0
    assert game.players[1].life == 20


def test_icy_manipulator_does_not_tap_an_artifact_that_gained_shroud(catalog_by_name):
    """CR 702.18a: shroud gained in response makes the artifact an illegal
    target, though it is still there and still an artifact — the half no
    handler's own re-check asked."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Icy Manipulator"])
    ring = _put(game, 1, catalog_by_name["Sol Ring"])

    assert game.queue_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[ring.permanent_id],
    ).supported
    grant_keyword(ring, "shroud")
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert not ring.tapped


def test_a_cost_is_not_refunded_when_the_ability_does_not_resolve(catalog_by_name):
    """CR 608.2b removes the ability; it gives nothing back. Icy Manipulator
    stays tapped for the activation that came to nothing."""
    game = _table(catalog_by_name)
    icy = _put(game, 0, catalog_by_name["Icy Manipulator"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[bears.permanent_id],
    ).supported
    _leave(game, bears)
    resolve_stack(game)

    assert icy.tapped
    assert any(_REMOVED in line for line in game.log)


def test_an_ability_whose_target_is_untouched_resolves_as_it_always_did(catalog_by_name):
    """The control. Nothing happens in response and nothing is removed."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Icy Manipulator"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)

    assert bears.tapped
    assert not any("608.2b" in line for line in game.log)


def test_a_bare_activation_still_resolves_on_its_handlers_pick(catalog_by_name):
    """The headless convention is untouched: an activation that named no
    target announced none, so there is nothing for CR 608.2b to judge and the
    handler picks as it always has."""
    game = _table(catalog_by_name)
    _put(game, 0, catalog_by_name["Icy Manipulator"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.activate_permanent_ability(0, "Icy Manipulator").supported

    assert bears.tapped, game.log[-4:]
    assert not any("608.2b" in line for line in game.log)


# ---------------------------------------------------------------------------
# One target of several illegal: it is left alone, and not replaced
# ---------------------------------------------------------------------------


def test_alexi_returns_only_the_creature_that_is_still_a_legal_target(catalog_by_name):
    """"{X}{U}, {T}, Discard two cards: Return X target creatures to their
    owners' hands." X is 2; one of the two gains shroud in response. The
    ability still resolves (one target is legal), the shrouded creature stays
    where it is, and the third creature on that battlefield — which nobody
    named — stays too."""
    game = _table(catalog_by_name, hand=("Forest", "Forest"))
    _put(game, 0, catalog_by_name["Alexi, Zephyr Mage"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _put(game, 1, catalog_by_name["Hill Giant"])
    lions = _put(game, 1, catalog_by_name["Savannah Lions"])

    assert game.queue_permanent_ability(
        0, "Alexi, Zephyr Mage", x_value=2,
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    ).supported
    grant_keyword(bears, "shroud")
    resolve_stack(game)

    assert game.is_on_battlefield(bears), "the illegal target is not affected"
    assert not game.is_on_battlefield(giant), game.log[-4:]
    assert game.is_on_battlefield(lions), "and nothing is returned in its place"
    assert [card.name for card in game.players[1].hand] == ["Hill Giant"]
    assert not any(_REMOVED in line for line in game.log)


def test_reckless_spite_does_not_destroy_the_creature_given_protection(catalog_by_name):
    """"Destroy two target nonblack creatures. You lose 5 life." Two white
    creatures are named and one is given protection from black in response
    (Mother of Runes' whole job). It is no longer a creature a black spell can
    target, so it is not destroyed; the other is, and the life is lost."""
    game = _table(catalog_by_name, hand=("Reckless Spite",))
    lions = _put(game, 1, catalog_by_name["Savannah Lions"])
    pegasus = _put(game, 1, catalog_by_name["Mesa Pegasus"])

    assert game.queue_from_hand(
        0, "Reckless Spite", target_player_index=1,
        target_permanent_ids=[lions.permanent_id, pegasus.permanent_id],
    ).supported
    lions.metadata["protection_from_black"] = True
    resolve_stack(game)
    game.check_state_based_actions()

    assert game.is_on_battlefield(lions), game.log[-4:]
    assert not game.is_on_battlefield(pegasus)
    assert game.players[0].life == 15
    assert not any(_REMOVED in line for line in game.log)


def test_reckless_spite_with_both_targets_protected_is_countered_by_the_rule(catalog_by_name):
    """…and with **both** protected, every target is illegal: the spell does
    not resolve and its controller keeps the 5 life (CR 608.2b's own Sorin's
    Thirst example)."""
    game = _table(catalog_by_name, hand=("Reckless Spite",))
    lions = _put(game, 1, catalog_by_name["Savannah Lions"])
    pegasus = _put(game, 1, catalog_by_name["Mesa Pegasus"])

    assert game.queue_from_hand(
        0, "Reckless Spite", target_player_index=1,
        target_permanent_ids=[lions.permanent_id, pegasus.permanent_id],
    ).supported
    for creature in (lions, pegasus):
        creature.metadata["protection_from_black"] = True
    resolve_stack(game)

    assert game.is_on_battlefield(lions) and game.is_on_battlefield(pegasus)
    assert game.players[0].life == 20
    assert any(_REMOVED in line for line in game.log)


# ---------------------------------------------------------------------------
# "This ability still resolves if its target becomes illegal."
# ---------------------------------------------------------------------------


def _drake_enters(catalog_by_name, *names_for_seat_1):
    """A Gilded Drake is put onto seat 0's battlefield; its entry trigger
    chooses the first creature seat 1 controls and waits on the stack."""
    game = _table(catalog_by_name)
    theirs = [_put(game, 1, catalog_by_name[name]) for name in names_for_seat_1]
    drake = _put(game, 0, catalog_by_name["Gilded Drake"])
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"
    item = game.stack[-1]
    assert item.target_permanent_id == theirs[0].permanent_id, item
    assert item.targets_chosen
    return game, drake, theirs


def test_gilded_drake_is_sacrificed_when_its_target_has_left(catalog_by_name):
    """"…exchange control of this creature and up to one target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice this
    creature. This ability still resolves if its target becomes illegal."

    The sentence waives the fizzle and nothing else: the target is still
    illegal, so no exchange can be made and the Drake is sacrificed. It used
    to trade itself for the Black Knight standing beside the target that had
    left — a creature its controller never chose."""
    game, drake, (bears, knight) = _drake_enters(
        catalog_by_name, "Grizzly Bears", "Black Knight",
    )

    _leave(game, bears)
    resolve_stack(game)

    assert game.controller_index_of(knight) == 1, game.log[-4:]
    assert not game.is_on_battlefield(drake)
    assert [card.name for card in game.players[0].graveyard] == ["Gilded Drake"]
    assert not any(_REMOVED in line for line in game.log), "the printed exception"


def test_gilded_drake_does_not_trade_for_a_creature_that_gained_shroud(catalog_by_name):
    game, drake, (bears,) = _drake_enters(catalog_by_name, "Grizzly Bears")

    grant_keyword(bears, "shroud")
    resolve_stack(game)

    assert game.controller_index_of(bears) == 1, game.log[-4:]
    assert not game.is_on_battlefield(drake)


def test_gilded_drake_still_trades_for_a_legal_target(catalog_by_name):
    """The other direction: nothing in response, and the exchange is made."""
    game, drake, (bears,) = _drake_enters(catalog_by_name, "Grizzly Bears")

    resolve_stack(game)

    assert game.controller_index_of(bears) == 0, game.log[-4:]
    assert game.controller_index_of(drake) == 1


# ---------------------------------------------------------------------------
# A triggered ability: asked where its target was chosen, not where stamped
# ---------------------------------------------------------------------------


def _effigy_dies(catalog_by_name, *, interactive=()):
    """A Blazing Effigy takes lethal damage beside seat 1's Grizzly Bears and
    Hill Giant; its dies-trigger is on the stack."""
    game = _table(catalog_by_name)
    game.interactive_seats = set(interactive)
    effigy = _put(game, 0, catalog_by_name["Blazing Effigy"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _put(game, 1, catalog_by_name["Hill Giant"])
    effigy.damage_marked = 3
    game.check_state_based_actions()
    assert not game.is_on_battlefield(effigy)
    (item,) = [item for item in game.stack if item.card.name == "Blazing Effigy"]
    return game, item, bears, giant


def test_blazing_effigys_dies_trigger_chooses_its_target_and_is_held_to_it(catalog_by_name):
    """"When this creature dies, it deals X damage to **target creature**…"

    ROADMAP declined CR 608.2b for every triggered ability on this card's
    account: the death sweep recorded the dying Effigy itself as the target,
    and asking the rule of that id would have reported a mis-stamp as a
    fizzle. That is no longer what happens — the trigger's own picker treats
    a stamp of its own source as a reference and **chooses** (CR 603.3d), and
    the choice is marked (``StackItem.targets_chosen``). So the rule is asked:
    the chosen Hill Giant leaves in response, and the 3 damage does not go to
    the Grizzly Bears that slid into its slot."""
    game, item, bears, giant = _effigy_dies(catalog_by_name, interactive={0})
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    assert item.targets_chosen and item.target_permanent_id == giant.permanent_id

    _leave(game, giant)
    resolve_stack(game)
    game.check_state_based_actions()

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert game.is_on_battlefield(bears) and bears.damage_marked == 0


def test_blazing_effigys_dies_trigger_still_burns_a_legal_target(catalog_by_name):
    """The other direction, with nobody to ask: the default picks a creature,
    nothing happens in response, and it takes the 3 damage."""
    game, item, bears, giant = _effigy_dies(catalog_by_name)
    assert item.targets_chosen
    chosen = game.permanent_by_id(item.target_permanent_id)
    assert chosen is bears or chosen is giant

    resolve_stack(game)

    assert chosen.damage_marked == 3, game.log[-4:]
    assert not any("608.2b" in line for line in game.log)


def test_a_target_a_fire_site_stamped_is_not_asked_the_rule(catalog_by_name):
    """The bound, pinned: what CR 608.2b may be asked of is a target somebody
    **chose** (``legality.announced_by_a_choice``), and a fire site that hands
    an ability the object its event was about has chosen nothing. The same
    trigger enqueued with a stamped id — the shape every "…that creature" fire
    site builds — is not marked, and the gate declines it: whatever its
    handler does with a stamp that has gone stale, it is not reported as a
    rules-correct fizzle."""
    game = _table(catalog_by_name)
    effigy = _put(game, 0, catalog_by_name["Blazing Effigy"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    from engine.oracle import compile_card_oracle

    (trigger,) = compile_card_oracle(effigy.card).triggered_abilities
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=effigy, instruction=trigger.instruction,
        effect_kind=trigger.effect_kind, ability_text=trigger.source_line,
        target_player_index=1, target_permanent_id=bears.permanent_id,
    )
    (item,) = game.stack
    assert not item.targets_chosen and not item.activated

    _leave(game, bears)

    assert game.illegal_targets_refusal(item) is None
    assert game.blank_illegal_resolution_targets(item) == 0


def test_a_pick_made_at_the_upkeep_prompt_is_a_chosen_target(catalog_by_name):
    """The browser's road for an upkeep trigger that prints a target. The web
    layer collects the pick at the upkeep step's own prompt
    (``get_upkeep_target_triggers``) and hands it to ``resolve_upkeep`` as a
    pre-answer, so the trigger reaches the stack with a target already on it —
    one its own list accepted, which is a choice (CR 603.3d) and is marked as
    one. Erhnam Djinn: "At the beginning of your upkeep, target non-Wall
    creature an opponent controls gains forestwalk until your next upkeep."
    The picked Grizzly Bears leaves in response; the Hill Giant beside it does
    not gain forestwalk in its place."""
    game = _table(catalog_by_name)
    game.interactive_seats = {0}
    djinn = _put(game, 0, catalog_by_name["Erhnam Djinn"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _put(game, 1, catalog_by_name["Hill Giant"])
    offered = [
        entry for entry in game.get_upkeep_target_triggers(0)
        if entry.get("permanent_id") == djinn.permanent_id
    ]
    assert offered, "the upkeep step offers the Djinn's target prompt"

    game.resolve_upkeep(
        0, defer_priority=True,
        trigger_targets={djinn.permanent_id: (1, game.battlefield_index_of(bears))},
    )
    (item,) = [obj for obj in game.stack if obj.card.name == "Erhnam Djinn"]
    assert item.target_permanent_id == bears.permanent_id
    assert item.targets_chosen, "a pick its own list accepted is a chosen target"

    _leave(game, bears)
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log), game.log[-4:]
    assert not game._has_keyword(giant, "forestwalk"), game.log[-4:]
