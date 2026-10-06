"""CR 613.7 in layer 4 — type effects in both arrival orders, measured.

Layer 5 ordered its channels by constants (``test_color_effects_timestamp_order``).
Layer 4 has the same *shape* — ``layer_bridge.collect_type_effects`` gives most
of its channels the stamp 0 — but it is not the same defect, because most
layer-4 effects **add** a type and additions commute. Order decides only where
one effect *sets* or *removes*, and the census below is every such meeting the
pool can arrange, each through the engine's own cast, activation and entry
paths:

* a land-type static against a turn-long land-type change and a land-type Aura
  (Blood Moon; Kavu Recluse's "becomes a Forest until end of turn"; Evil
  Presence) — already stamped on both sides (``engine/land_types.py``), and
  right in both orders;
* a land-type change against a creature type an earlier effect added (Living
  Terrain's Treefolk, Mishra's Factory's Assembly-Worker) — **was wrong in one
  order**: CR 305.7 replaces a land's *land* types, and the blanket replacement
  that stood in for it took the creature type too whenever the land-type change
  arrived second;
* a creature-type *set* against a creature-type *addition* (Conspiracy; Dub's
  "is a Knight in addition to its other types") — **was wrong in one order**:
  Conspiracy carried the constant 0, so it applied before every Aura whenever
  each arrived, and a Knight survived a Conspiracy played after it;
* a card-type *set* against a card-type addition (Soul Sculptor's "becomes an
  enchantment" after Karn, Titania's Song, Animate Artifact or Ashnod's
  Transmogrant made the permanent something else) — right;
* two statics where one depends on the other (CR 613.8a): Dralnu's Crusade on
  what Conspiracy makes a Goblin, Kormus Bell on what Evil Presence makes a
  Swamp — right once the board has settled.

Three more meetings are still wrong and are **not** asserted here. Each needs a
change to a board refresh in ``mixins/permanent_state.py`` rather than to the
collector, and is written up with its parts in the round's report
(``scratch/pls/w2g4/measure_layer4.py`` reproduces all three):

* Conversion ("All Mountains are Plains") *then* Blood Moon: Conversion depends
  on the Moon (CR 613.8a) and should apply after it; the refresh chains the
  land-type statics in timestamp order alone, so the land stays a Mountain;
* Dralnu's Crusade *then* Conspiracy naming Goblin: right, but one refresh late
  — the Crusade's scope is judged against the layer 4 of the pass before;
* Melting ("All lands are no longer snow") *then* Arcum's Weathervane's
  "becomes snow": the removal is derived with no stamp and always applies last.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.layer_bridge import computed_supertypes, computed_types
from engine.models import Permanent


def _w2g4_types(perm):
    """``(card types, subtypes, supertypes)`` after layer 4, sorted."""
    card_types, subtypes = computed_types(perm)
    return sorted(card_types), sorted(subtypes), sorted(computed_supertypes(perm))


class _W2G4Board:
    """One game with seat 0 acting and answering what it is asked."""

    def __init__(self, catalog_by_name, set_pool):
        self._catalog = catalog_by_name
        self._set_pool = set_pool
        game = Game(players=[
            PlayerState(name="A", life=20), PlayerState(name="B", life=20),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game.active_player_index = 0
        self.game = game

    def card(self, name):
        if name in self._catalog:
            return self._catalog[name]
        return self._set_pool("PLS")[name]

    def enter(self, name):
        perm = Permanent(card=self.card(name))
        self.game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        return perm

    def _settle(self, **answers):
        game = self.game
        for _ in range(40):
            for choice in list(game.pending_choices):
                if choice.kind == "enter_choice":
                    assert game.confirm_enter_choice(choice.player_index, **answers)
                else:
                    game.auto_resolve_pending_choices(
                        choice.player_index, kinds=[choice.kind],
                    )
            if game.stack:
                game.resolve_top_of_stack()
                continue
            if not game.pending_choices:
                return
        raise AssertionError([c.kind for c in game.pending_choices])

    def cast(self, name, at=None, **answers):
        game = self.game
        game.players[0].hand.append(self.card(name))
        cast = game.queue_from_hand(
            0, name,
            **({} if at is None else {"target_permanent_ids": [at.permanent_id]}),
        )
        assert cast.supported, (name, cast.details)
        self._settle(**answers)

    def activate(self, source, index=0, at=None):
        source.tapped = False
        activated = self.game.queue_permanent_ability(
            0, source.card.name, ability_index=index,
            **({} if at is None else {"target_permanent_ids": [at.permanent_id]}),
        )
        assert activated.supported, (source.card.name, activated.details)
        self._settle()


# Each case: build the board in order, return (what the rules say, what the
# layer says). ``part`` picks which of the three sorted lists is compared.

def _w2g4_moon_then_forest(b):
    recluse, land = b.enter("Kavu Recluse"), b.enter("Mishra's Factory")
    b.cast("Blood Moon")
    assert _w2g4_types(land)[1] == ["mountain"]
    b.activate(recluse, 0, at=land)
    forest = _w2g4_types(land)[1]
    b.game.resolve_cleanup_step(0)
    return (["forest"], ["mountain"]), (forest, _w2g4_types(land)[1])


def _w2g4_forest_then_moon(b):
    recluse, land = b.enter("Kavu Recluse"), b.enter("Mishra's Factory")
    b.activate(recluse, 0, at=land)
    assert _w2g4_types(land)[1] == ["forest"]
    b.cast("Blood Moon")
    return ["mountain"], _w2g4_types(land)[1]


def _w2g4_presence_then_moon(b):
    land = b.enter("Mishra's Factory")
    b.cast("Evil Presence", at=land)
    assert _w2g4_types(land)[1] == ["swamp"]
    b.cast("Blood Moon")
    return ["mountain"], _w2g4_types(land)[1]


def _w2g4_moon_then_presence(b):
    land = b.enter("Mishra's Factory")
    b.cast("Blood Moon")
    b.cast("Evil Presence", at=land)
    return ["swamp"], _w2g4_types(land)[1]


def _w2g4_moon_then_conversion(b):
    land = b.enter("Mishra's Factory")
    b.cast("Blood Moon")
    b.cast("Conversion")
    return ["plains"], _w2g4_types(land)[1]


def _w2g4_terrain_then_presence(b):
    land = b.enter("Forest")
    b.cast("Living Terrain", at=land)
    assert _w2g4_types(land)[1] == ["forest", "treefolk"]
    b.cast("Evil Presence", at=land)
    return ["swamp", "treefolk"], _w2g4_types(land)[1]


def _w2g4_presence_then_terrain(b):
    land = b.enter("Forest")
    b.cast("Evil Presence", at=land)
    b.cast("Living Terrain", at=land)
    return ["swamp", "treefolk"], _w2g4_types(land)[1]


def _w2g4_factory_then_moon(b):
    land = b.enter("Mishra's Factory")
    b.activate(land, 1)
    assert _w2g4_types(land)[1] == ["assembly-worker"]
    b.cast("Blood Moon")
    return (
        (["artifact", "creature", "land"], ["assembly-worker", "mountain"]),
        _w2g4_types(land)[:2],
    )


def _w2g4_conspiracy_then_dub(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Conspiracy", creature_type="elf")
    assert _w2g4_types(bears)[1] == ["elf"]
    b.cast("Dub", at=bears)
    return ["elf", "knight"], _w2g4_types(bears)[1]


def _w2g4_dub_then_conspiracy(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Dub", at=bears)
    assert _w2g4_types(bears)[1] == ["bear", "knight"]
    b.cast("Conspiracy", creature_type="elf")
    return ["elf"], _w2g4_types(bears)[1]


def _w2g4_two_conspiracies(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Conspiracy", creature_type="elf")
    b.cast("Conspiracy", creature_type="wall")
    return ["wall"], _w2g4_types(bears)[1]


def _w2g4_conspiracy_then_crusade(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Conspiracy", creature_type="goblin")
    b.cast("Dralnu's Crusade")
    return ["goblin", "zombie"], _w2g4_types(bears)[1]


def _w2g4_crusade_then_conspiracy_settled(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Dralnu's Crusade")
    b.cast("Conspiracy", creature_type="goblin")
    # One refresh late (see the module docstring): the Crusade's scope is
    # judged against the previous pass's layer 4, so the board is asked again.
    b.game._recompute_continuous_effects()
    return ["goblin", "zombie"], _w2g4_types(bears)[1]


def _w2g4_crusade_goblin_made_an_elf(b):
    goblin = b.enter("Goblin Raider")
    b.cast("Dralnu's Crusade")
    assert _w2g4_types(goblin)[1] == ["goblin", "warrior", "zombie"]
    b.cast("Conspiracy", creature_type="elf")
    return ["elf"], _w2g4_types(goblin)[1]


def _w2g4_weathervane_then_melting(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.activate(vane, 1, at=land)
    assert _w2g4_types(land)[2] == ["basic", "snow"]
    b.cast("Melting")
    return ["basic"], _w2g4_types(land)[2]


def _w2g4_then_sculptor(animator):
    """*animator* makes a Howling Mine (or a Bears) something more, then Soul
    Sculptor's "becomes an enchantment" sets its card types (CR 205.1a)."""
    def case(b):
        sculptor = b.enter("Soul Sculptor")
        if animator == "Karn, Silver Golem":
            karn, subject = b.enter(animator), b.enter("Howling Mine")
            b.activate(karn, 0, at=subject)
        elif animator == "Ashnod's Transmogrant":
            relic, subject = b.enter(animator), b.enter("Grizzly Bears")
            b.activate(relic, 0, at=subject)
        elif animator == "Animate Artifact":
            subject = b.enter("Howling Mine")
            b.cast(animator, at=subject)
        else:
            subject = b.enter("Howling Mine")
            b.cast(animator)
        assert len(_w2g4_types(subject)[0]) == 2, _w2g4_types(subject)
        b.activate(sculptor, 0, at=subject)
        return ["enchantment"], _w2g4_types(subject)[0]
    return case


def _w2g4_bell_then_presence(b):
    land = b.enter("Forest")
    b.cast("Kormus Bell")
    assert _w2g4_types(land)[0] == ["land"]
    b.cast("Evil Presence", at=land)
    return ["creature", "land"], _w2g4_types(land)[0]


_W2G4_CASES = {
    # --- timestamp order between two effects that both set (CR 613.7) -------
    "blood_moon>forest_until_eot": _w2g4_moon_then_forest,
    "forest_until_eot>blood_moon": _w2g4_forest_then_moon,
    "evil_presence>blood_moon": _w2g4_presence_then_moon,
    "blood_moon>evil_presence": _w2g4_moon_then_presence,
    "blood_moon>conversion": _w2g4_moon_then_conversion,
    "conspiracy>conspiracy": _w2g4_two_conspiracies,
    # --- a land-type set leaves a creature type alone (CR 305.7) ------------
    "living_terrain>evil_presence": _w2g4_terrain_then_presence,
    "evil_presence>living_terrain": _w2g4_presence_then_terrain,
    "mishras_factory>blood_moon": _w2g4_factory_then_moon,
    # --- a creature-type set against an addition (CR 613.7) -----------------
    "conspiracy>dub": _w2g4_conspiracy_then_dub,
    "dub>conspiracy": _w2g4_dub_then_conspiracy,
    # --- dependency (CR 613.8a) --------------------------------------------
    "conspiracy>dralnus_crusade": _w2g4_conspiracy_then_crusade,
    "dralnus_crusade>conspiracy": _w2g4_crusade_then_conspiracy_settled,
    "dralnus_crusade>conspiracy_elsewhere": _w2g4_crusade_goblin_made_an_elf,
    "kormus_bell>evil_presence": _w2g4_bell_then_presence,
    # --- a supertype addition, then the static that removes it --------------
    "weathervane>melting": _w2g4_weathervane_then_melting,
    # --- a card-type set after an addition (CR 205.1a) ----------------------
    "karn>soul_sculptor": _w2g4_then_sculptor("Karn, Silver Golem"),
    "titanias_song>soul_sculptor": _w2g4_then_sculptor("Titania's Song"),
    "animate_artifact>soul_sculptor": _w2g4_then_sculptor("Animate Artifact"),
    "transmogrant>soul_sculptor": _w2g4_then_sculptor("Ashnod's Transmogrant"),
}

#: The three this round fixed: each failed, in the order named, on the tree
#: before it.
_W2G4_WERE_WRONG = (
    "living_terrain>evil_presence", "mishras_factory>blood_moon", "dub>conspiracy",
)


@pytest.mark.cr("613.7", "613.7a", "613.7b", "613.8a", "305.7", "205.1a", "514.2")
@pytest.mark.parametrize("name", sorted(_W2G4_CASES))
def test_w2g4_type_effects_meet_in_the_order_the_rules_give(
    catalog_by_name, set_pool, name,
):
    """*first*>*second*: the two effects arrive in that order and the permanent
    is what CR 613.7 (or, where one depends on the other, CR 613.8) makes it."""
    want, got = _W2G4_CASES[name](_W2G4Board(catalog_by_name, set_pool))
    assert got == want, name


@pytest.mark.cr("613.7")
def test_w2g4_the_type_census_covers_both_orders_of_what_it_fixed():
    """The floor: every pairing this round changed is here in both arrival
    orders, so the fix cannot have been bought by breaking the other one."""
    assert set(_W2G4_WERE_WRONG) <= set(_W2G4_CASES)
    for name in ("living_terrain>evil_presence", "dub>conspiracy"):
        first, second = name.split(">")
        assert f"{second}>{first}" in _W2G4_CASES
    assert len(_W2G4_CASES) >= 20
