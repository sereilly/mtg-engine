"""What a permanent *was* as it left the battlefield (CR 603.10a), through the
layers (CR 613.1d), on every road into the graveyard.

``_move_permanent_to_graveyard`` is the one seam every death passes through,
and it asked "was this a creature?" two ways. The death tallies (Scavenging
Ghoul's count) asked ``is_creature``; the creature-death record — the
``damaged_creatures_that_died_this_turn`` ledger Krovikan Vampire's end-step
condition reads, and every "whenever a creature dies" trigger
(``_fire_creature_dies_triggers``: Soul Net, Sengir Vampire, Fecundity, an
Aura's "when enchanted creature dies") — asked the printed word,
``card.primary_type == "creature"``. So on the base tree a Mishra's Factory, a
Living Lands Forest, an Opalescence enchantment or an Animate Artifact's
artifact died and no Soul Net saw it, and a Clone that had copied a Mishra's
Factory (a land and not a creature, CR 707.2) fired every one of them.

The census below is every subject x every road: 29 rows, 24 of them wrong on
the base tree (``c42aec75``). The roads are the two shapes the seam is reached
in — the permanent still listed as it is moved (the sweeps, the lethal-damage
state-based action, ``sacrifice_permanents``) and already taken off
(``sacrifice_permanent``, ``_destroy_target_permanent``) — because the second
is where a read of a departed object could go stale. It does not: nothing
recomputes an object off the battlefield, so its layer inputs are its last-known
ones.

Beside it, the removal seam's other printed-type read: an Aura's effects end as
it leaves (CR 611.3b), and the seam asked ``"Aura" in perm.card.type_line`` — so a
Licid, which *becomes* an Aura through its own ability on a card printed
"Creature — Licid", was never torn down.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.handlers._common import return_permanent_to_owners_hand
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def by_name():
    catalog = load_catalog()
    named = {card.name: card for card in catalog}
    named.update({unit.name: unit for unit in compilation_units(catalog)})
    return named


def _game(by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, by_name, name, seat=0):
    permanent = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._recompute_continuous_effects()
    return permanent


def _cast(game, by_name, name, target, seat):
    card = whole_card(by_name[name])
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(
        seat, name, target_permanent_ids=[target.permanent_id]
    )
    assert result.supported, (name, result)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()


# --- the subjects: each a permanent of seat 1's -----------------------------


def _animated_factory(game, by_name):
    factory = _put(game, by_name, "Mishra's Factory", 1)
    result = game.activate_permanent_ability(
        1, "Mishra's Factory",
        permanent_index=game.battlefield_index_of(factory), ability_index=1,
    )
    assert result.supported, result
    resolve_stack(game)
    game._recompute_continuous_effects()
    return factory


def _living_lands_forest(game, by_name):
    _put(game, by_name, "Living Lands", 0)
    return _put(game, by_name, "Forest", 1)


def _opalescent_crusade(game, by_name):
    _put(game, by_name, "Opalescence", 0)
    return _put(game, by_name, "Crusade", 1)


def _animated_artifact(game, by_name):
    tome = _put(game, by_name, "Jalum Tome", 1)
    _cast(game, by_name, "Animate Artifact", tome, seat=1)
    return tome


def _clone_of_a_factory(game, by_name):
    factory = _animated_factory(game, by_name)
    _cast(game, by_name, "Clone", factory, seat=1)
    return next(p for p in game.controlled_by(1) if p.card.name == "Clone")


def _bears(game, by_name):
    return _put(game, by_name, "Grizzly Bears", 1)


#: (label, builder, printed "creature", a creature through the layers)
SUBJECTS = [
    ("an animated Mishra's Factory", _animated_factory, False, True),
    ("a Living Lands Forest", _living_lands_forest, False, True),
    ("an Opalescence enchantment", _opalescent_crusade, False, True),
    ("an Animate Artifact artifact", _animated_artifact, False, True),
    ("a Clone of an animated Factory", _clone_of_a_factory, True, False),
    ("Grizzly Bears (the control)", _bears, True, True),
]


# --- the roads ----------------------------------------------------------------


def _lethal_damage(game, subject, vampire):
    game._mark_damage_on_permanent(subject, 7, source=vampire)
    game.check_state_based_actions()


def _sacrifice(game, subject, _vampire):
    game.sacrifice_permanent(subject)


def _sacrifice_together(game, subject, _vampire):
    game.sacrifice_permanents([subject])


def _destroy_sweep(game, subject, _vampire):
    game._destroy_swept_permanents(
        game.players[1], lambda perm: perm is subject, allow_regeneration=False
    )


def _destroy_target(game, subject, _vampire):
    game._destroy_target_permanent(
        game.players[1], {}, game.battlefield_index_of(subject),
        bypass_regeneration=True,
    )


ROADS = [
    ("lethal damage (still listed)", _lethal_damage),
    ("sacrifice_permanent (taken off first)", _sacrifice),
    ("sacrifice_permanents (still listed)", _sacrifice_together),
    ("destroy sweep (still listed)", _destroy_sweep),
    ("destroy target (taken off first)", _destroy_target),
]


def _census(by_name):
    rows = []
    for label, build, printed_creature, layered_creature in SUBJECTS:
        for road_name, road in ROADS:
            game = _game(by_name)
            subject = build(game, by_name)
            # The watchers arrive after the subject, so a Clone has nothing
            # but the Factory to copy.
            vampire = _put(game, by_name, "Krovikan Vampire", 0)
            _put(game, by_name, "Soul Net", 0)
            assert subject.is_creature is layered_creature, label
            assert (subject.card.primary_type == "creature") is printed_creature, label
            if road is _lethal_damage and not layered_creature:
                continue  # only a creature can be dealt damage (CR 120.1)
            damaged = road is _lethal_damage
            if layered_creature and not damaged and subject.effective_toughness > 1:
                game._mark_damage_on_permanent(subject, 1, source=vampire)
                game.check_state_based_actions()
                damaged = True
            stacked = len(game.stack)
            road(game, subject, vampire)
            rows.append({
                "subject": label,
                "road": road_name,
                "was_creature": layered_creature,
                "damaged": damaged,
                "left": not game.is_on_battlefield(subject),
                "soul_net": sum(
                    1 for item in game.stack[stacked:]
                    if item.card.name == "Soul Net"
                ),
                "ledger": [
                    card.name for card in vampire.metadata.get(
                        "damaged_creatures_that_died_this_turn", []
                    )
                ],
            })
    return rows


@pytest.mark.cr("603.10a", "700.4", "613.1d")
def test_every_road_to_the_graveyard_asks_what_the_permanent_was(by_name):
    """"Whenever a creature dies" (Soul Net) and the creature-death ledger
    (Krovikan Vampire) see exactly the permanents that were creatures as they
    left — through the layers, on every road."""
    rows = _census(by_name)
    # The floor: six subjects, five roads, less the one road a non-creature
    # cannot take. A census that built no board finds nothing wrong.
    assert len(rows) == 29, len(rows)
    assert sum(row["was_creature"] for row in rows) == 25
    assert sum(row["damaged"] for row in rows) >= 15
    wrong = [
        row for row in rows
        if not row["left"]
        or row["soul_net"] != (1 if row["was_creature"] else 0)
        or bool(row["ledger"]) != (row["was_creature"] and row["damaged"])
    ]
    assert not wrong, "\n".join(map(str, wrong))


@pytest.mark.cr("603.10a", "603.4", "613.1d")
def test_krovikan_vampire_returns_an_animated_land_it_killed(by_name):
    """"At the beginning of each end step, if a creature dealt damage by this
    creature this turn died, put that card onto the battlefield under your
    control." A Mishra's Factory that was a 2/2 creature when the Vampire's
    damage killed it *was* a creature that died; "that card" is the land card,
    and it comes back as one."""
    game = _game(by_name)
    factory = _animated_factory(game, by_name)
    vampire = _put(game, by_name, "Krovikan Vampire", 0)
    assert factory.is_creature and factory.card.primary_type == "land"

    game._mark_damage_on_permanent(factory, 2, source=vampire)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(factory)
    assert [card.name for card in game.players[1].graveyard] == ["Mishra's Factory"]

    game.resolve_end_step(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    returned = [p for p in game.controlled_by(0) if p.card.name == "Mishra's Factory"]
    assert len(returned) == 1
    assert returned[0].has_type("land") and not returned[0].is_creature
    assert game.players[1].graveyard == []


@pytest.mark.cr("603.10a", "707.2")
def test_a_clone_that_copied_a_land_does_not_die_as_a_creature(by_name):
    """The other direction: a Clone of an animated Mishra's Factory copies the
    printed land (the animation is not a copiable value), so it is a land on a
    card printed "Creature — Shapeshifter". Sacrificing it is no creature's
    death: no Soul Net trigger, and the game-wide tally does not move."""
    game = _game(by_name)
    clone = _clone_of_a_factory(game, by_name)
    _put(game, by_name, "Soul Net", 0)
    assert clone.has_type("land") and not clone.is_creature
    died_before = getattr(game, "creatures_died_this_turn", 0)

    game.sacrifice_permanent(clone)

    assert not game.is_on_battlefield(clone)
    assert not any(item.card.name == "Soul Net" for item in game.stack)
    assert getattr(game, "creatures_died_this_turn", 0) == died_before


# --- the removal seam's Aura read: a Licid ----------------------------------


def _licid_on(by_name, licid_name, host_seat):
    licid = _nosick(Permanent(card=by_name[licid_name]))
    host = _nosick(Permanent(card=by_name["Grizzly Bears"]))
    game = _game(by_name)
    game.players[0].battlefield = [licid] + ([host] if host_seat == 0 else [])
    if host_seat == 1:
        game.players[1].battlefield = [host]
    result = game.activate_permanent_ability(
        0, licid_name, ability_index=0, target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result
    resolve_stack(game)
    game.check_state_based_actions()
    assert licid.has_type("aura") and not licid.is_creature
    assert licid.metadata.get("attached_to") is host
    return game, licid, host


def _destroyed(game, licid):
    game._destroy_target_permanent(
        game.players[0], {}, game.battlefield_index_of(licid),
        bypass_regeneration=True,
    )


def _sacrificed(game, licid):
    game.sacrifice_permanent(licid)


def _bounced(game, licid):
    return_permanent_to_owners_hand(game, licid, fallback_owner=game.players[0])


LEAVES = [("destroyed", _destroyed), ("sacrificed", _sacrificed), ("bounced", _bounced)]


@pytest.mark.cr("611.3b", "613.1d", "303.4")
@pytest.mark.parametrize("road", [road for _name, road in LEAVES],
                         ids=[name for name, _road in LEAVES])
def test_a_licid_that_leaves_stops_granting_flying(by_name, road):
    """"Enchanted creature has flying." (Gliding Licid.) The grant is the
    Aura's while it is attached; once the Licid has left, by any road, the
    host no longer flies."""
    game, licid, host = _licid_on(by_name, "Gliding Licid", host_seat=0)
    assert game._has_keyword(host, "flying")

    road(game, licid)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(licid)
    assert not game._has_keyword(host, "flying")


@pytest.mark.cr("611.3b", "613.1d", "613.1b")
@pytest.mark.parametrize("road", [road for _name, road in LEAVES],
                         ids=[name for name, _road in LEAVES])
def test_a_dominating_licid_that_leaves_gives_the_creature_back(by_name, road):
    """"You control enchanted creature." (Dominating Licid.) A layer-2 effect
    of an Aura ends when the Aura leaves the battlefield."""
    game, licid, host = _licid_on(by_name, "Dominating Licid", host_seat=1)
    assert game.controller_index_of(host) == 0

    road(game, licid)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(licid)
    assert game.controller_index_of(host) == 1
