"""CR 616.1e's ``effect_order`` option names the card that generates the
effect — for the effects whose record kept no card.

    616.1 If two or more replacement and/or prevention effects are attempting
    to modify the way an event affects an object or player, the affected
    object's controller (or its owner if it has no controller) or the affected
    player chooses one to apply, following the steps listed below.

The ``logs`` round made every registration of both registries carry a
``sources=`` reader, and ``effect_ordering.option_text`` writes the option
"<effect> (<source>)". Five records kept nothing for that reader to name, so
the option was the bare label — one effect that does what another does read
the same, with no card to tell them apart:

* the would-die marker ``exile_if_dies_this_turn`` — Disintegrate's own, and
  the rider Runesword's creature carries onto what it damages
  (``damage_events._apply_dealer_riders``);
* Dreams of the Dead's ``EXILE_ON_LEAVING_BATTLEFIELD``;
* Yawgmoth's Will's seat marker ``exile_cards_bound_for_graveyard_this_turn``;
* the land-mana substitution, whose ``swapped_production`` answered with a
  symbol and not with what said so;
* Forcefield's shield (``make_capped_source`` / ``make_capped_charge``), the
  one shield ``handlers/prevention`` armed without its card's name — found by
  the census, not named by the entry.

Each marker now holds the name of the card whose effect wrote it
(``replacements.zone_changes.recorded_name``), the substitution carries its
``source``, and Forcefield's shield its ``source_name``.

The census: the registrations' ``sources`` readers read structurally (none
answers nothing by construction, over every registration of both
registries), and each record driven on a board. Where the engine puts the
choice to a person — Forcefield beside a prevention pool in a combat damage
step, Yawgmoth's Will beside a bought-back spell — the prompt is asked and
answered. ``would_die``, ``would_leave_battlefield`` and
``land_mana_produced`` are never asked (``apply_replacements`` is handed no
``restart`` there, and the last two have one registration each), so for
those the option the order would offer is read off the live event.

Backwards, on the base (8e42acee + the static split): the structural census
names three registrations, and every board's option is the bare label.
"""
from __future__ import annotations

import ast
import inspect
from functools import lru_cache
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cast_costs import buyback_cost
from engine.effect_ordering import option_text
from engine.land_mana_swaps import swapped_symbol
from engine.models import Permanent
from engine.prevention.registry import PREVENTION_EFFECTS
from engine.replacements import REPLACEMENTS
from engine.shields import add_shield, make_numeric_pool
from tests.helpers import resolve_stack

_C = {card.name: card for card in load_catalog()}


def _registrations():
    return (
        [(kind, c) for kind, entries in REPLACEMENTS.items() for c in entries]
        + [("damage", c) for c in PREVENTION_EFFECTS]
    )


def _registration(kind: str, key: str):
    found = [c for k, c in _registrations() if k == kind and c.key == key]
    assert len(found) == 1, (kind, key, found)
    return found[0]


@lru_cache(maxsize=None)
def _module_tree(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def _own_returns(node) -> list:
    """The values *node* returns — not those of a function nested in it."""
    if isinstance(node, ast.Lambda):
        return [node.body]
    found, pending = [], list(ast.iter_child_nodes(node))
    while pending:
        child = pending.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Return):
            found.append(child.value)
        pending.extend(ast.iter_child_nodes(child))
    return found


def _answers_nothing_by_construction(reader) -> bool:
    """Whether every ``return`` of *reader* is an empty list or tuple literal
    (or a lambda whose body is one) — a reader that names nothing for any
    event its ``applies`` admits. Found in its module's own tree by its first
    line, so a lambda written inside a decorator call is read too."""
    path = inspect.getsourcefile(reader)
    line = reader.__code__.co_firstlineno
    nodes = [
        node for node in ast.walk(_module_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.Lambda))
        and (min((d.lineno for d in getattr(node, "decorator_list", ())), default=node.lineno)
             == line or node.lineno == line)
        and (not isinstance(node, ast.FunctionDef) or node.name == reader.__name__)
    ]
    assert nodes, (reader.__qualname__, path, line)
    returned = _own_returns(nodes[0])
    return bool(returned) and all(
        isinstance(value, (ast.List, ast.Tuple)) and not value.elts
        for value in returned
    )


@pytest.mark.cr("616.1", "616.1e")
def test_no_registration_reads_its_sources_as_nothing_by_construction():
    """Over every registration of both registries: a ``sources`` reader that
    returns an empty list on every path names no card for any event — the
    shape two readers had on the base (``_marker_sources``, read by two
    registrations, and ``_land_mana_substitution_sources``)."""
    rows = _registrations()
    assert len(rows) >= 90, len(rows)
    examined = 0
    nameless = []
    for kind, candidate in rows:
        reader = candidate.sources
        assert callable(reader), (kind, candidate.key)
        examined += 1
        if _answers_nothing_by_construction(reader):
            nameless.append((kind, candidate.key, reader.__qualname__))
    assert examined >= 90, examined
    assert not nameless, nameless


def _table(*, mine=(), theirs=(), hand0=(), hand1=(), interactive=()):
    game = Game(players=[
        PlayerState(name="P1", hand=[_C[name] for name in hand0],
                    library=[_C["Forest"]] * 8),
        PlayerState(name="P2", hand=[_C[name] for name in hand1],
                    library=[_C["Forest"]] * 8),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_C[name])
            permanent.metadata["summoning_sickness_turn"] = -99
            game._put_permanent_onto_battlefield(seat, permanent, None)
    game.start_turn(0)
    game._close_current_priority_step()
    game.interactive_seats = set(interactive)
    return game


def _on(game, name: str) -> Permanent:
    found = [p for p in game.all_permanents() if p.card.name == name]
    assert len(found) == 1, (name, [p.card.name for p in game.all_permanents()])
    return found[0]


def _effect_order(game, seat: int):
    owed = [c for c in game.pending_choices if c.kind == "effect_order" and c.player_index == seat]
    assert len(owed) == 1, ([c.kind for c in game.pending_choices], game.log[-5:])
    return owed[0]


# --- asked: a prevention shield beside another, in a combat damage step -----


@pytest.mark.cr("616.1e", "615.7", "510.2")
def test_forcefield_beside_a_prevention_pool_names_forcefield():
    """Forcefield's shield against the chosen unblocked attacker and a
    Healing Salve pool, both over the Hill Giant's combat damage to its
    controller. The Forcefield option was "Prevent all but 1 of the chosen
    attacker's combat damage" with nothing beside it."""
    forcefield = Permanent(card=_C["Forcefield"])
    giant = Permanent(card=_C["Hill Giant"])
    giant.metadata["summoning_sickness_turn"] = -99
    attacker = PlayerState(name="Attacker", battlefield=[giant], life=20,
                           library=[_C["Forest"]] * 5)
    defender = PlayerState(name="Defender", battlefield=[forcefield], life=20,
                           library=[_C["Forest"]] * 5)
    game = Game(players=[attacker, defender])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    armed = game.activate_permanent_ability(
        1, "Forcefield", permanent_index=0, target_player_index=0,
        target_permanent_ids=[giant.permanent_id],
    )
    assert armed.supported, armed.details
    resolve_stack(game)
    add_shield(defender, make_numeric_pool(3, "Healing Salve"))
    game.interactive_seats = {1}
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)

    order = _effect_order(game, 1)
    assert order.data["options"] == [
        "Prevent all but 1 of the chosen attacker's combat damage (Forcefield)",
        "Prevent the next N damage (Healing Salve)",
    ], order.data["options"]
    assert any(
        "Defender must choose which effect applies first (Prevent all but 1 of the "
        "chosen attacker's combat damage (Forcefield)" in line for line in game.log
    ), game.log[-3:]
    assert game.resolve_pending_choice("effect_order", 1, option_index=0)
    resolve_stack(game)
    # The cap took the 3 down to 1 and the pool took the 1: nothing landed.
    assert defender.life == 20, game.log[-6:]
    assert "Defender applies Prevent all but 1 of the chosen attacker's combat damage (Forcefield) first" in game.log


# --- asked: a bought-back spell beside Yawgmoth's Will ----------------------


@pytest.mark.cr("616.1", "616.1e", "702.27a")
def test_yawgmoths_will_beside_buyback_names_yawgmoths_will():
    """Yawgmoth's Will's ruling (2004-10-04, Scryfall) names this contest:
    "If you cast a Buyback spell, then there will be two effects trying to
    replace where the card goes. You get to choose…". The exile's option was
    "Exile that card instead of putting it into a graveyard" — the seat's
    marker recorded no card — beside the buyback's. Choosing it, the log line
    names the card too."""
    game = _table(hand0=["Yawgmoth's Will", "Searing Touch"], interactive=(0,))
    assert game.cast_from_hand(0, "Yawgmoth's Will").supported
    resolve_stack(game)
    touch = next(card for card in game.players[0].hand if card.name == "Searing Touch")
    offers = {buyback_cost(touch.oracle_text or ""): 1}
    assert game.queue_from_hand(
        0, "Searing Touch", optional_cost_payments=offers, target_player_index=1,
    ).supported
    for _ in range(6):
        if game.pending_choice_of("effect_order") is not None:
            break
        game.resolve_top_of_stack(pause_for_choices=True)

    order = _effect_order(game, 0)
    options = order.data["options"]
    # The buyback contest writes the graveyard half as "Put <card> into the
    # graveyard, as replaced there (<option>)" — the option is
    # ``option_text``'s, so its source is the last thing it says.
    exile = [option for option in options if "Exile that card instead" in option]
    assert len(exile) == 1 and exile[0].endswith(
        "(Exile that card instead of putting it into a graveyard) (Yawgmoth's Will)"
    ), options
    assert game.resolve_pending_choice(
        "effect_order", 0, option_index=options.index(exile[0]),
    )
    resolve_stack(game)
    assert any(card is touch for card in game.players[0].exile), game.log[-5:]
    assert any(
        line.startswith("Searing Touch was exiled instead of going to P1's graveyard")
        and line.endswith("(Yawgmoth's Will)") for line in game.log
    ), game.log[-5:]


# --- not asked: the option the order would offer, off the live event --------


@pytest.mark.cr("616.1e", "614.1a")
def test_disintegrates_would_die_marker_names_disintegrate():
    """Disintegrate at a Gravebane Zombie: two would-die replacements over the
    Zombie (Disintegrate's exile, the Zombie's own "put it on top of its
    owner's library instead"). The marker the damage left on it names the
    card, and so does the option."""
    game = _table(theirs=["Gravebane Zombie"], hand0=["Disintegrate"])
    zombie = _on(game, "Gravebane Zombie")
    assert game.queue_from_hand(
        0, "Disintegrate", x_value=1, target_permanent_ids=[zombie.permanent_id],
    ).supported
    resolve_stack(game)
    assert zombie.damage_marked == 1 and game.is_on_battlefield(zombie), game.log[-4:]
    event = {"player": game.players[1], "permanent": zombie}
    exile = _registration("would_die", "_exile_instead_of_dying")
    top = _registration("would_die", "_top_of_library_instead_of_dying")
    assert exile.applies(game, event) and top.applies(game, event)
    assert option_text(game, event, exile) == (
        "Exile it instead of putting it into a graveyard (Disintegrate)"
    )
    assert option_text(game, event, top).endswith("(Gravebane Zombie)")


@pytest.mark.cr("616.1e", "614.1a")
def test_runeswords_rider_carries_runeswords_name_onto_what_it_damages():
    """"If a creature dealt damage by the targeted creature would die this
    turn, exile that creature instead." The rider rides the damager and is
    stamped on its victim at the damage seam; the victim's option names
    Runesword, not nothing and not the creature that dealt the damage."""
    game = _table(mine=["Runesword", "Grizzly Bears"], theirs=["Gravebane Zombie"])
    bears = _on(game, "Grizzly Bears")
    bears.attacking = True
    zombie = _on(game, "Gravebane Zombie")
    activated = game.activate_permanent_ability(
        0, "Runesword", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert activated.supported, activated.details
    resolve_stack(game)
    game._mark_damage_on_permanent(zombie, 1, bears)
    event = {"player": game.players[1], "permanent": zombie}
    exile = _registration("would_die", "_exile_instead_of_dying")
    assert exile.applies(game, event), zombie.metadata
    assert option_text(game, event, exile) == (
        "Exile it instead of putting it into a graveyard (Runesword)"
    )


@pytest.mark.cr("616.1e", "614.6")
def test_dreams_of_the_deads_marker_names_dreams_of_the_dead():
    """The creature Dreams of the Dead returns carries "if it would leave the
    battlefield, exile it instead"; the option names the enchantment.
    ``would_leave_battlefield`` has this one registration, so no second effect
    contends with it in this pool."""
    game = _table(mine=["Dreams of the Dead"])
    game.players[0].graveyard.append(_C["Gravebane Zombie"])
    activated = game.activate_permanent_ability(
        0, "Dreams of the Dead", target_player_index=0, target_permanent_index=0,
    )
    assert activated.supported, activated.details
    resolve_stack(game)
    zombie = _on(game, "Gravebane Zombie")
    event = {"player": game.players[0], "permanent": zombie, "destination": "hand"}
    leaving = _registration("would_leave_battlefield", "_exile_instead_of_leaving")
    assert leaving.applies(game, event)
    assert option_text(game, event, leaving) == (
        "Exile it instead of putting it anywhere else (Dreams of the Dead)"
    )


@pytest.mark.cr("616.1e", "106.12b")
def test_a_land_mana_substitution_names_the_permanent_or_the_card_that_armed_it():
    """The static (Infernal Darkness: "If a land is tapped for mana, it
    produces {B} instead of any other type") names the permanent printing it;
    the per-seat record (Deep Water's "{U}: Until end of turn, … it produces
    {U} instead") names the card whose ability armed it. With both, the
    registration stands for two CR 616.1 effects (kg5 ``mana``: its
    ``instances``), each candidate naming its own source, and the registration
    names both in the order they apply — the record last by default, so its
    {U} is the symbol the default answer carries."""
    from engine.replacements.registry import replacement_candidates

    game = _table(mine=["Infernal Darkness", "Forest", "Deep Water"])
    forest = _on(game, "Forest")
    event = {"land": forest, "player": game.players[0]}
    substitution = _registration("land_mana_produced", "_substitute_land_mana")
    assert substitution.applies(game, event)
    assert option_text(game, event, substitution) == (
        "The land produces the named type of mana instead (Infernal Darkness)"
    )
    activated = game.activate_permanent_ability(0, "Deep Water")
    assert activated.supported, activated.details
    resolve_stack(game)
    assert option_text(game, event, substitution) == (
        "The land produces the named type of mana instead (Infernal Darkness, Deep Water)"
    )
    candidates = replacement_candidates("land_mana_produced", game, event)
    assert [option_text(game, event, c) for c in candidates] == [
        "The land produces the named type of mana instead (Infernal Darkness)",
        "The land produces the named type of mana instead (Deep Water)",
    ]
    # …and the symbol the default answer carries is still the record's.
    assert swapped_symbol(game, forest) == "U"
