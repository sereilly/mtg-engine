"""CR 613.7 and 613.8 in layer 4 — type effects in both arrival orders, measured.

Layer 5 ordered its channels by constants (``test_color_effects_timestamp_order``).
Layer 4 has the same *shape*, but it is not the same defect, because most
layer-4 effects **add** a type and additions commute. Order decides only where
one effect *sets* or *removes* — and where one effect's **scope is a type**,
which is the thing layer 5 does not have: "All Mountains are Plains" reaches
whatever is a Mountain *when it applies*, so another effect that makes or
unmakes Mountains changes what it applies to, and CR 613.8 moves it behind
that effect whichever is older.

The census below is every such meeting the pool can arrange, each through the
engine's own cast, activation and entry paths, and each read **the moment the
resolution or the entry choice finishes** — no further refresh, no state-based
pass. The expected value of every row is derived from the rule cited beside
it, never from the engine:

* **timestamp order between two effects that both set** (CR 613.7): a
  land-type static against a turn-long change, an Aura, or another land-type
  static it does not depend on (Blood Moon; Celestial Dawn; Blanket of Night's
  addition; Kavu Recluse; Evil Presence);
* **a land-type set leaves a creature type alone** (CR 305.7, CR 205.1a's
  "subtypes from the appropriate set");
* **a creature-type set against an addition** (Conspiracy; Dub);
* **dependency** (CR 613.8a–b), where the older effect waits for the newer:

  - Conversion on Blood Moon, on Phantasmal Terrain and on Illusionary
    Terrain — anything that makes a land a Mountain;
  - Kormus Bell and Living Lands on whatever makes a land a Swamp or a Forest
    (Evil Presence, Blanket of Night, Cyclopean Tomb's mire counter, Kavu
    Recluse);
  - Dralnu's Crusade on Conspiracy, in both directions (the Goblin it makes
    and the Goblin it unmakes);
  - Conspiracy on whatever makes a permanent a creature — Mishra's Factory's
    animation, Animate Land, Natural Affinity, Living Terrain, Living Lands,
    Titania's Song, Opalescence, Karn — and on Soul Sculptor, which makes one
    stop being a creature;
  - Opalescence on Soul Sculptor, which makes a permanent an enchantment;
  - Titania's Song on Soul Sculptor, which makes one stop being an artifact;

* **a dependency loop is timestamp order** (CR 613.8b's last sentence):
  Conversion beside an Illusionary Terrain that turns Plains into Mountains;
* **a supertype** an effect added or removed against the static that removes
  it, and against the opposite one-shot (Arcum's Weathervane; Melting) —
  CR 613.7b: each activation is its own effect with its own timestamp;
* **a card-type set after an addition** (CR 205.1a): Soul Sculptor after Karn,
  Titania's Song, Animate Artifact or Ashnod's Transmogrant.

``_W2G4_WERE_WRONG`` names the three the round that started this census fixed,
and ``_OI_WERE_WRONG`` the rows that failed on the tree before the board-wide
layer-4 pass (``engine/type_statics.py``) and the type write API
(``engine/type_changes.py``) — measured there with this file's own cases.

One pairing the census can arrange is deliberately **not** in it, because the
engine still answers it by the printed type line rather than by the rule:
Titania's Song's "each *noncreature* artifact" against the effects that make an
artifact a creature (Karn, Xenic Poltergeist, Animate Artifact). The type line
comes out the same either way — an artifact creature — and what differs is
whether the Song strips the artifact's abilities, which is layer 6 reading the
Song's layer-4 reach (CR 613.6). The round's report carries its parts.
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
                elif choice.kind == "land_type_choice" and "land_type" in answers:
                    # Phantasmal Terrain's "choose a basic land type".
                    assert game.confirm_land_type(
                        choice.player_index, answers["land_type"],
                    )
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


def _oi_two_statics(first, second, want, **answers):
    """Two board-wide statics arrive in this order over a Mishra's Factory."""
    def case(b):
        land = b.enter("Mishra's Factory")
        b.cast(first, **answers)
        b.cast(second, **answers)
        return want, _w2g4_types(land)[1]
    return case


def _oi_conversion_and_a_made_mountain(maker, conversion_first):
    """Conversion beside the effect that makes a Forest a Mountain. Conversion
    depends on it (CR 613.8a), so the Forest is a Plains in both orders."""
    def case(b):
        land = b.enter("Forest")

        def make():
            if maker == "Phantasmal Terrain":
                b.cast(maker, at=land, land_type="mountain")
            else:
                b.cast(maker, land_types=("forest", "mountain"))

        if conversion_first:
            b.cast("Conversion")
            make()
        else:
            make()
            assert _w2g4_types(land)[1] == ["mountain"], _w2g4_types(land)
            b.cast("Conversion")
        return ["plains"], _w2g4_types(land)[1]
    return case


def _oi_dependency_loop(conversion_first):
    """"All Mountains are Plains" beside "basic Plains are Mountains": each
    changes what the other applies to, which is a dependency loop, and
    CR 613.8b applies a loop's effects in timestamp order. So the *later* one
    has the last word over both lands."""
    def case(b):
        mountain, plains = b.enter("Mountain"), b.enter("Plains")
        if conversion_first:
            b.cast("Conversion")
            b.cast("Illusionary Terrain", land_types=("plains", "mountain"))
            want = (["mountain"], ["mountain"])
        else:
            b.cast("Illusionary Terrain", land_types=("plains", "mountain"))
            b.cast("Conversion")
            want = (["plains"], ["plains"])
        return want, (_w2g4_types(mountain)[1], _w2g4_types(plains)[1])
    return case


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


def _w2g4_bell_then_presence(b):
    land = b.enter("Forest")
    b.cast("Kormus Bell")
    assert _w2g4_types(land)[0] == ["land"]
    b.cast("Evil Presence", at=land)
    return ["creature", "land"], _w2g4_types(land)[0]


def _oi_presence_then_bell(b):
    land = b.enter("Forest")
    b.cast("Evil Presence", at=land)
    b.cast("Kormus Bell")
    return ["creature", "land"], _w2g4_types(land)[0]


def _oi_bell_and_blanket(bell_first):
    """Kormus Bell animates Swamps; Blanket of Night makes every land one. The
    Bell depends on the Blanket (CR 613.8a) and reaches the Forest either way."""
    def case(b):
        land = b.enter("Forest")
        for name in (
            ("Kormus Bell", "Blanket of Night") if bell_first
            else ("Blanket of Night", "Kormus Bell")
        ):
            b.cast(name)
        return (["creature", "land"], ["forest", "swamp"]), _w2g4_types(land)[:2]
    return case


def _oi_bell_and_tomb(bell_first):
    """Cyclopean Tomb's mire counter makes a Forest a Swamp "for as long as it
    has a mire counter on it"; Kormus Bell animates Swamps. The Bell depends
    on the counter's effect (CR 613.8a)."""
    def case(b):
        tomb, land = b.enter("Cyclopean Tomb"), b.enter("Forest")
        # "Activate only during your upkeep."
        b.game.current_step = "upkeep"
        if bell_first:
            b.cast("Kormus Bell")
            b.activate(tomb, 0, at=land)
        else:
            b.activate(tomb, 0, at=land)
            b.cast("Kormus Bell")
        return (["creature", "land"], ["swamp"]), _w2g4_types(land)[:2]
    return case


def _oi_living_lands_then_forest(b):
    recluse, land = b.enter("Kavu Recluse"), b.enter("Mishra's Factory")
    b.cast("Living Lands")
    assert _w2g4_types(land)[0] == ["land"]
    b.activate(recluse, 0, at=land)
    during = _w2g4_types(land)[0]
    b.game.resolve_cleanup_step(0)
    return (["creature", "land"], ["land"]), (during, _w2g4_types(land)[0])


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


def _oi_crusade_then_conspiracy(b):
    bears = b.enter("Grizzly Bears")
    b.cast("Dralnu's Crusade")
    b.cast("Conspiracy", creature_type="goblin")
    # No recompute here. This case asked the board again before reading it
    # ("one refresh late"); the Crusade now finds the Goblin in the same pass
    # that Conspiracy makes it, and answering the entry choice is what
    # recomputes the board.
    return ["goblin", "zombie"], _w2g4_types(bears)[1]


def _w2g4_crusade_goblin_made_an_elf(b):
    goblin = b.enter("Goblin Raider")
    b.cast("Dralnu's Crusade")
    assert _w2g4_types(goblin)[1] == ["goblin", "warrior", "zombie"]
    b.cast("Conspiracy", creature_type="elf")
    return ["elf"], _w2g4_types(goblin)[1]


def _oi_elf_conspiracy_then_crusade(b):
    goblin = b.enter("Goblin Raider")
    b.cast("Conspiracy", creature_type="elf")
    b.cast("Dralnu's Crusade")
    return ["elf"], _w2g4_types(goblin)[1]


def _oi_conspiracy_and_a_made_creature(maker, conspiracy_first, want):
    """Conspiracy beside the effect that makes a noncreature permanent a
    creature. "Creatures you control are the chosen type" depends on it
    (CR 613.8a), so the chosen type replaces the creature types that effect
    brought — in both orders."""
    def case(b):
        if maker == "Mishra's Factory":
            subject = b.enter(maker)
            make = lambda: b.activate(subject, 1)
        elif maker == "Living Terrain":
            subject = b.enter("Forest")
            make = lambda: b.cast(maker, at=subject)
        elif maker == "Animate Land":
            subject = b.enter("Forest")
            make = lambda: b.cast(maker, at=subject)
        elif maker in ("Living Lands", "Natural Affinity"):
            subject = b.enter("Forest")
            make = lambda: b.cast(maker)
        elif maker == "Karn, Silver Golem":
            karn, subject = b.enter(maker), b.enter("Howling Mine")
            make = lambda: b.activate(karn, 0, at=subject)
        elif maker == "Opalescence":
            subject = b.enter("Castle")
            make = lambda: b.cast(maker)
        else:
            subject = b.enter("Howling Mine")
            make = lambda: b.cast(maker)
        if conspiracy_first:
            b.cast("Conspiracy", creature_type="elf")
            make()
        else:
            make()
            b.cast("Conspiracy", creature_type="elf")
        return want, _w2g4_types(subject)[:2]
    return case


def _oi_conspiracy_then_sculptor(b):
    sculptor, bears = b.enter("Soul Sculptor"), b.enter("Grizzly Bears")
    b.cast("Conspiracy", creature_type="elf")
    assert _w2g4_types(bears)[1] == ["elf"]
    b.activate(sculptor, 0, at=bears)
    # CR 205.1a: the creature type goes, and its creature subtypes with it —
    # so Conspiracy, whose scope is "creatures", no longer reaches the Bears.
    return (["enchantment"], []), _w2g4_types(bears)[:2]


def _oi_melting_then_freeze(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.cast("Melting")
    b.activate(vane, 1, at=land)
    return ["basic", "snow"], _w2g4_types(land)[2]


def _w2g4_weathervane_then_melting(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.activate(vane, 1, at=land)
    assert _w2g4_types(land)[2] == ["basic", "snow"]
    b.cast("Melting")
    return ["basic"], _w2g4_types(land)[2]


def _oi_thaw_then_freeze(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Snow-Covered Forest")
    b.activate(vane, 0, at=land)
    thawed = _w2g4_types(land)[2]
    b.activate(vane, 1, at=land)
    return (["basic"], ["basic", "snow"]), (thawed, _w2g4_types(land)[2])


def _oi_freeze_then_thaw(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.activate(vane, 1, at=land)
    frozen = _w2g4_types(land)[2]
    b.activate(vane, 0, at=land)
    return (["basic", "snow"], ["basic"]), (frozen, _w2g4_types(land)[2])


def _oi_freeze_thaw_freeze(b):
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.activate(vane, 1, at=land)
    b.activate(vane, 0, at=land)
    b.activate(vane, 1, at=land)
    return ["basic", "snow"], _w2g4_types(land)[2]


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


def _oi_opalescence_and_sculptor(opalescence_first):
    """Soul Sculptor makes a Bears an enchantment; Opalescence makes each other
    non-Aura enchantment a creature as well. Opalescence depends on the
    Sculptor's effect (CR 613.8a), so the Bears is an enchantment creature in
    both orders — and only an enchantment while Opalescence applied first."""
    def case(b):
        sculptor, bears = b.enter("Soul Sculptor"), b.enter("Grizzly Bears")
        if opalescence_first:
            b.cast("Opalescence")
            b.activate(sculptor, 0, at=bears)
        else:
            b.activate(sculptor, 0, at=bears)
            assert _w2g4_types(bears)[0] == ["enchantment"]
            b.cast("Opalescence")
        return ["creature", "enchantment"], _w2g4_types(bears)[0]
    return case


_ELF_LAND = (["creature", "land"], ["elf", "forest"])
_ELF_FACTORY = (["artifact", "creature", "land"], ["elf"])
_ELF_MINE = (["artifact", "creature"], ["elf"])
_ELF_CASTLE = (["creature", "enchantment"], ["elf"])

_W2G4_CASES = {
    # --- timestamp order between two effects that both set (CR 613.7) -------
    "blood_moon>forest_until_eot": _w2g4_moon_then_forest,
    "forest_until_eot>blood_moon": _w2g4_forest_then_moon,
    "evil_presence>blood_moon": _w2g4_presence_then_moon,
    "blood_moon>evil_presence": _w2g4_moon_then_presence,
    "blood_moon>conversion": _oi_two_statics("Blood Moon", "Conversion", ["plains"]),
    "celestial_dawn>blood_moon": _oi_two_statics(
        "Celestial Dawn", "Blood Moon", ["mountain"],
    ),
    "blood_moon>celestial_dawn": _oi_two_statics(
        "Blood Moon", "Celestial Dawn", ["plains"],
    ),
    # "…in addition to its other land types": the Blanket adds, the Moon sets
    # (CR 305.7), so the later Moon takes the Swamp away with the rest.
    "blood_moon>blanket_of_night": _oi_two_statics(
        "Blood Moon", "Blanket of Night", ["mountain", "swamp"],
    ),
    "blanket_of_night>blood_moon": _oi_two_statics(
        "Blanket of Night", "Blood Moon", ["mountain"],
    ),
    "conspiracy>conspiracy": _w2g4_two_conspiracies,
    # --- a land-type set leaves a creature type alone (CR 305.7) ------------
    "living_terrain>evil_presence": _w2g4_terrain_then_presence,
    "evil_presence>living_terrain": _w2g4_presence_then_terrain,
    "mishras_factory>blood_moon": _w2g4_factory_then_moon,
    # --- a creature-type set against an addition (CR 613.7) -----------------
    "conspiracy>dub": _w2g4_conspiracy_then_dub,
    "dub>conspiracy": _w2g4_dub_then_conspiracy,
    # --- dependency: a land-type static on what makes its lands (CR 613.8a) -
    "conversion>blood_moon": _oi_two_statics("Conversion", "Blood Moon", ["plains"]),
    "conversion>phantasmal_terrain": _oi_conversion_and_a_made_mountain(
        "Phantasmal Terrain", True,
    ),
    "phantasmal_terrain>conversion": _oi_conversion_and_a_made_mountain(
        "Phantasmal Terrain", False,
    ),
    "conversion>illusionary_terrain": _oi_conversion_and_a_made_mountain(
        "Illusionary Terrain", True,
    ),
    "illusionary_terrain>conversion": _oi_conversion_and_a_made_mountain(
        "Illusionary Terrain", False,
    ),
    # --- a dependency loop is timestamp order (CR 613.8b) -------------------
    "conversion>illusionary_terrain_loop": _oi_dependency_loop(True),
    "illusionary_terrain_loop>conversion": _oi_dependency_loop(False),
    # --- dependency: a land animator on what makes its lands ----------------
    "kormus_bell>evil_presence": _w2g4_bell_then_presence,
    "evil_presence>kormus_bell": _oi_presence_then_bell,
    "kormus_bell>blanket_of_night": _oi_bell_and_blanket(True),
    "blanket_of_night>kormus_bell": _oi_bell_and_blanket(False),
    "living_lands>forest_until_eot": _oi_living_lands_then_forest,
    "kormus_bell>cyclopean_tomb": _oi_bell_and_tomb(True),
    "cyclopean_tomb>kormus_bell": _oi_bell_and_tomb(False),
    # --- dependency: a type-scoped static on a creature-type set ------------
    "conspiracy>dralnus_crusade": _w2g4_conspiracy_then_crusade,
    "dralnus_crusade>conspiracy": _oi_crusade_then_conspiracy,
    "dralnus_crusade>conspiracy_elsewhere": _w2g4_crusade_goblin_made_an_elf,
    "conspiracy_elsewhere>dralnus_crusade": _oi_elf_conspiracy_then_crusade,
    # --- dependency: Conspiracy on what makes a permanent a creature --------
    "conspiracy>mishras_factory": _oi_conspiracy_and_a_made_creature(
        "Mishra's Factory", True, _ELF_FACTORY,
    ),
    "mishras_factory>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Mishra's Factory", False, _ELF_FACTORY,
    ),
    "conspiracy>living_terrain": _oi_conspiracy_and_a_made_creature(
        "Living Terrain", True, _ELF_LAND,
    ),
    "living_terrain>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Living Terrain", False, _ELF_LAND,
    ),
    "conspiracy>living_lands": _oi_conspiracy_and_a_made_creature(
        "Living Lands", True, _ELF_LAND,
    ),
    "living_lands>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Living Lands", False, _ELF_LAND,
    ),
    # One targeted, one swept — the two turn-long animations of a land.
    "conspiracy>animate_land": _oi_conspiracy_and_a_made_creature(
        "Animate Land", True, _ELF_LAND,
    ),
    "animate_land>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Animate Land", False, _ELF_LAND,
    ),
    "conspiracy>natural_affinity": _oi_conspiracy_and_a_made_creature(
        "Natural Affinity", True, _ELF_LAND,
    ),
    "natural_affinity>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Natural Affinity", False, _ELF_LAND,
    ),
    "conspiracy>titanias_song": _oi_conspiracy_and_a_made_creature(
        "Titania's Song", True, _ELF_MINE,
    ),
    "titanias_song>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Titania's Song", False, _ELF_MINE,
    ),
    "conspiracy>opalescence": _oi_conspiracy_and_a_made_creature(
        "Opalescence", True, _ELF_CASTLE,
    ),
    "opalescence>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Opalescence", False, _ELF_CASTLE,
    ),
    "conspiracy>karn": _oi_conspiracy_and_a_made_creature(
        "Karn, Silver Golem", True, _ELF_MINE,
    ),
    "karn>conspiracy": _oi_conspiracy_and_a_made_creature(
        "Karn, Silver Golem", False, _ELF_MINE,
    ),
    "conspiracy>soul_sculptor": _oi_conspiracy_then_sculptor,
    # --- dependency: Opalescence on what makes a permanent an enchantment ---
    "opalescence>soul_sculptor": _oi_opalescence_and_sculptor(True),
    "soul_sculptor>opalescence": _oi_opalescence_and_sculptor(False),
    # --- a supertype against the static that removes it (CR 613.7) ----------
    "melting>weathervane_freeze": _oi_melting_then_freeze,
    "weathervane>melting": _w2g4_weathervane_then_melting,
    # --- two one-shot supertype changes on one land (CR 613.7b) -------------
    "weathervane_thaw>weathervane_freeze": _oi_thaw_then_freeze,
    "weathervane_freeze>weathervane_thaw": _oi_freeze_then_thaw,
    "weathervane_freeze>thaw>freeze": _oi_freeze_thaw_freeze,
    # --- a card-type set after an addition (CR 205.1a) ----------------------
    "karn>soul_sculptor": _w2g4_then_sculptor("Karn, Silver Golem"),
    "titanias_song>soul_sculptor": _w2g4_then_sculptor("Titania's Song"),
    "animate_artifact>soul_sculptor": _w2g4_then_sculptor("Animate Artifact"),
    "transmogrant>soul_sculptor": _w2g4_then_sculptor("Ashnod's Transmogrant"),
}

#: The three the first round fixed: each failed, in the order named, on the
#: tree before it.
_W2G4_WERE_WRONG = (
    "living_terrain>evil_presence", "mishras_factory>blood_moon", "dub>conspiracy",
)

#: The rows that failed on the tree before ``engine/type_statics.py`` and
#: ``engine/type_changes.py`` — this file's cases, run there. The first three
#: are the meetings the first round measured and left.
_OI_WERE_WRONG = (
    # CR 613.8a: Conversion depends on what makes a Mountain.
    "conversion>blood_moon",
    "conversion>phantasmal_terrain",
    "conversion>illusionary_terrain",
    # CR 613.8a: the Crusade depends on Conspiracy — right, one refresh late.
    "dralnus_crusade>conspiracy",
    # CR 613.7: the static's removal carried no stamp and applied last.
    "melting>weathervane_freeze",
    # CR 613.7b: both one-shot lists applied at 0, additions first.
    "weathervane_thaw>weathervane_freeze",
    "weathervane_freeze>thaw>freeze",
    # CR 613.8a: Conspiracy depends on what makes a creature. (Living
    # Terrain's order was wrong outright; the three animations were right one
    # refresh late — nothing recomputed the board when one resolved.)
    "conspiracy>living_terrain",
    "conspiracy>mishras_factory",
    "conspiracy>animate_land",
    "conspiracy>natural_affinity",
    # CR 613.8a: an animator depends on what makes its land type — likewise
    # right one refresh late.
    "living_lands>forest_until_eot",
    "kormus_bell>cyclopean_tomb",
    # CR 613.8a: Opalescence depends on what makes an enchantment.
    "opalescence>soul_sculptor",
    "soul_sculptor>opalescence",
)


@pytest.mark.cr(
    "613.7", "613.7a", "613.7b", "613.8a", "613.8b", "305.7", "205.1a", "205.1b",
    "514.2",
)
@pytest.mark.parametrize("name", sorted(_W2G4_CASES))
def test_w2g4_type_effects_meet_in_the_order_the_rules_give(
    catalog_by_name, set_pool, name,
):
    """*first*>*second*: the two effects arrive in that order and the permanent
    is what CR 613.7 (or, where one depends on the other, CR 613.8) makes it."""
    want, got = _W2G4_CASES[name](_W2G4Board(catalog_by_name, set_pool))
    assert got == want, name


@pytest.mark.cr("613.7", "613.8a")
def test_w2g4_the_type_census_covers_both_orders_of_what_it_fixed():
    """The floor: every pairing a round changed is here, and in both arrival
    orders wherever both can be arranged — so no fix can have been bought by
    breaking the other one."""
    assert set(_W2G4_WERE_WRONG) <= set(_W2G4_CASES)
    assert set(_OI_WERE_WRONG) <= set(_W2G4_CASES)
    for name in (
        "living_terrain>evil_presence", "dub>conspiracy",
        "conversion>blood_moon", "conversion>phantasmal_terrain",
        "conversion>illusionary_terrain", "dralnus_crusade>conspiracy",
        "conspiracy>mishras_factory", "conspiracy>living_terrain",
        "opalescence>soul_sculptor", "weathervane_thaw>weathervane_freeze",
        "conversion>illusionary_terrain_loop",
    ):
        first, second = name.split(">")
        mirror = (
            # The loop's two orders carry the marker on the Terrain's side.
            "illusionary_terrain_loop>conversion"
            if name.endswith("_loop") else f"{second}>{first}"
        )
        assert mirror in _W2G4_CASES, mirror
    # Melting against the Weathervane's freeze, whose mirror keeps the name
    # the first round gave it.
    assert "weathervane>melting" in _W2G4_CASES
    assert len(_W2G4_CASES) >= 61, len(_W2G4_CASES)
    assert len(_OI_WERE_WRONG) == 15


# ---------------------------------------------------------------------------
# What the order is *for*: the board, one layer down
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.8a", "613.8b", "305.6")
def test_oi_conversion_then_blood_moon_taps_a_nonbasic_land_for_white(
    catalog_by_name, set_pool,
):
    """The dependency read where a player meets it: with Conversion out first
    and Blood Moon second, a Mishra's Factory is a Plains (CR 613.8a–b) and so
    taps for {W} (CR 305.6) — it tapped for {R}."""
    b = _W2G4Board(catalog_by_name, set_pool)
    land = b.enter("Mishra's Factory")
    b.cast("Conversion")
    b.cast("Blood Moon")

    assert land.basic_land_types == ("plains",)
    assert land.effective_produced_mana == ("W",)
    b.game.tap_land_for_mana(
        0, "Mishra's Factory", "W", permanent_id=land.permanent_id,
    )
    pool = b.game.players[0].mana_pool
    assert (pool["W"], pool["R"]) == (1, 0)


@pytest.mark.cr("613.8a", "613.6")
def test_oi_the_crusade_reaches_the_goblin_conspiracy_just_made_in_every_layer(
    catalog_by_name, set_pool,
):
    """Dralnu's Crusade is on the battlefield; Conspiracy arrives naming
    Goblin. The Crusade depends on it (CR 613.8a), so the Bears is a Goblin
    *Zombie* the moment the choice is answered — and CR 613.6 keeps the Crusade
    on the same set of objects in its other layers: the Bears is black and gets
    +1/+1. It was a green 2/2 Goblin until something else recomputed the
    board."""
    b = _W2G4Board(catalog_by_name, set_pool)
    bears = b.enter("Grizzly Bears")
    b.cast("Dralnu's Crusade")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    b.cast("Conspiracy", creature_type="goblin")

    assert _w2g4_types(bears)[1] == ["goblin", "zombie"]
    assert b.game._effective_colors(bears) == {"B"}
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


@pytest.mark.cr("613.7", "613.7a", "613.7b", "205.4a")
def test_oi_a_land_frozen_under_melting_is_snow_and_reads_as_snow(
    catalog_by_name, set_pool,
):
    """Melting's "All lands are no longer snow" has its enchantment's
    timestamp (CR 613.7a); Arcum's Weathervane's "becomes snow" is created
    later (CR 613.7b) and applies last. The land is snow to every reader — the
    supertype, the type line a player is shown, and the Weathervane's own
    "target snow land"."""
    from engine.layer_bridge import displayed_type_line

    b = _W2G4Board(catalog_by_name, set_pool)
    vane, land = b.enter("Arcum's Weathervane"), b.enter("Forest")
    b.cast("Melting")
    b.activate(vane, 1, at=land)

    assert land.has_supertype("snow")
    assert displayed_type_line(land) == "Basic Snow Land — Forest"
    # …and the thaw can find it again: "Target snow land is no longer snow".
    b.activate(vane, 0, at=land)
    assert not land.has_supertype("snow")
    assert displayed_type_line(land) == "Basic Land — Forest"


@pytest.mark.cr("613.8a", "613.6")
def test_oi_opalescence_gives_a_sculpted_creature_its_mana_value_as_a_body(
    catalog_by_name, set_pool,
):
    """Soul Sculptor makes a Grizzly Bears an enchantment; Opalescence, which
    was already out, depends on that (CR 613.8a) and makes it a creature again
    — with base power and toughness equal to its mana value, the same static's
    layer-7b half on the same object (CR 613.6). It was an enchantment with no
    body at all, under an Opalescence that says every other non-Aura
    enchantment is a creature."""
    b = _W2G4Board(catalog_by_name, set_pool)
    sculptor, bears = b.enter("Soul Sculptor"), b.enter("Grizzly Bears")
    b.cast("Opalescence")
    b.activate(sculptor, 0, at=bears)

    assert bears.is_creature and bears.has_type("enchantment")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# CR 613.8b–c: the walk itself — loops end, and the order is re-asked
# ---------------------------------------------------------------------------


def _oi_static(name, text):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )


def _oi_board(catalog_by_name, statics, lands):
    """A battlefield built in this order: the statics, oldest first, then the
    lands. ``Permanent.timestamp`` is stamped at construction, so the order
    the list is written in is the order of arrival (CR 613.7d)."""
    sources = [Permanent(card=card) for card in statics]
    permanents = [Permanent(card=catalog_by_name[name]) for name in lands]
    game = Game(players=[
        PlayerState(name="A", battlefield=sources),
        PlayerState(name="B", battlefield=permanents),
    ])
    game.enforce_mana_costs = False
    return game, permanents


@pytest.mark.cr("613.8b")
@pytest.mark.parametrize("rotation", [0, 1, 2])
def test_oi_a_three_static_dependency_loop_ends_in_timestamp_order(
    catalog_by_name, rotation, monkeypatch,
):
    """Mountains are Plains, Plains are Islands, Islands are Mountains: each
    static changes what the next applies to, all the way round — a dependency
    loop of three. CR 613.8b: "this rule is ignored and the effects in the
    dependency loop are applied in timestamp order", so the three chain
    oldest-first and every land ends as whatever the **youngest** makes.

    And it ends. The walk applies one effect per step whatever depends on
    what, so it takes exactly as many steps as there are effects — counted
    here, because a loop is the one board on which a fixed-point search would
    not stop."""
    from engine import type_statics

    ring = [
        _oi_static("Flatten", "All Mountains are Plains."),
        _oi_static("Flood", "All Plains are Islands."),
        _oi_static("Upheave", "All Islands are Mountains."),
    ]
    order = ring[rotation:] + ring[:rotation]
    game, lands = _oi_board(catalog_by_name, order, ["Mountain", "Plains", "Island"])

    steps = []
    real = type_statics._next_step
    monkeypatch.setattr(
        type_statics, "_next_step",
        lambda remaining, *rest: steps.append(len(remaining)) or real(remaining, *rest),
    )
    game._refresh_global_statics(list(game.all_permanents()))

    made_by_youngest = {"Flatten": "plains", "Flood": "island", "Upheave": "mountain"}
    want = made_by_youngest[order[-1].name]
    assert [land.basic_land_types for land in lands] == [(want,)] * 3
    # Three statics and no other layer-4 effect on the board: three steps, the
    # list one shorter each time.
    assert steps == [3, 2, 1]


@pytest.mark.cr("613.8c")
def test_oi_the_order_is_asked_again_after_every_application(catalog_by_name):
    """CR 613.8c: "After each effect is applied, the order of remaining effects
    is reevaluated and may change if an effect that has not yet been applied
    becomes dependent on … other effects that have not yet been applied."

    Blood Moon (oldest), then "All Plains are Islands", then "All Mountains
    are Plains" (youngest), over a Mishra's Factory. At the start nothing
    depends on anything: the land has no land type, so neither later static
    reaches it and neither can change what the other reaches. A walk that
    fixed its order there would apply the three by timestamp and stop at
    Plains, the second static spent on nothing.

    Once the Moon has applied the land is a Mountain, the third static now
    reaches it — and the second, not yet applied, has *become* dependent on
    the third. It waits, and the land ends an Island."""
    statics = [
        catalog_by_name["Blood Moon"],
        _oi_static("Flood", "All Plains are Islands."),
        _oi_static("Flatten", "All Mountains are Plains."),
    ]
    game, (factory,) = _oi_board(catalog_by_name, statics, ["Mishra's Factory"])
    game._recompute_continuous_effects()

    assert factory.basic_land_types == ("island",), game.log


@pytest.mark.cr("613.8a", "613.8b")
def test_oi_dependency_is_not_followed_through_a_third_effect(catalog_by_name):
    """…and the same three in the other arrival order, where the rule's
    literal reading gives the answer nobody expects. "All Mountains are
    Plains" (oldest) depends on Blood Moon (youngest) and waits. "All Plains
    are Islands", between them, depends on *neither as things stand* —
    applying either one alone changes nothing it reaches (CR 613.8a asks about
    applying "the other", one effect) — so it applies at its own timestamp, to
    nothing. Then the Moon, then the static that waited for it: a Plains, and
    no later effect to carry it on."""
    statics = [
        _oi_static("Flatten", "All Mountains are Plains."),
        _oi_static("Flood", "All Plains are Islands."),
        catalog_by_name["Blood Moon"],
    ]
    game, (factory,) = _oi_board(catalog_by_name, statics, ["Mishra's Factory"])
    game._recompute_continuous_effects()

    assert factory.basic_land_types == ("plains",), game.log


@pytest.mark.cr("613.8a", "613.8b")
def test_oi_a_dependent_static_waits_for_the_whole_board_not_per_land(catalog_by_name):
    """Dependency is a relation between two *effects* (CR 613.8a), not between
    two effects on one land. With Conversion older than Blood Moon:

    * beside a Tundra, Conversion depends on the Moon (it would make the Tundra
      a Mountain), so it waits — and then applies to **every** land it reaches,
      the Taiga included: the Moon made the Taiga a Mountain, Conversion makes
      it a Plains;
    * with no such land — the Taiga is a Mountain before and after the Moon —
      nothing changes what Conversion applies to, there is no dependency, and
      timestamp order stands: Conversion makes the Taiga a Plains and the
      younger Moon makes it a Mountain again.

    One land's presence decides another's type. A per-land walk cannot say
    that, which is why the order is decided for the whole board at once."""
    conversion, moon = catalog_by_name["Conversion"], catalog_by_name["Blood Moon"]

    game, (taiga, tundra) = _oi_board(catalog_by_name, [conversion, moon], ["Taiga", "Tundra"])
    game._recompute_continuous_effects()
    assert (taiga.basic_land_types, tundra.basic_land_types) == (("plains",), ("plains",))

    game, (taiga,) = _oi_board(catalog_by_name, [conversion, moon], ["Taiga"])
    game._recompute_continuous_effects()
    assert taiga.basic_land_types == ("mountain",)


@pytest.mark.cr("613.7a", "613.7d")
def test_oi_a_land_type_static_is_stamped_by_its_permanent(catalog_by_name):
    """CR 613.7a: a static ability's effect has the timestamp of the object it
    is on, which the object received as it entered (CR 613.7d). The land-type
    statics carried a stand-in stamped the first time a refresh saw them; the
    derived contribution now carries ``Permanent.timestamp`` itself, the clock
    every other layer-4 effect is on."""
    from engine.land_types import land_type_changes

    game, (tundra,) = _oi_board(catalog_by_name, [catalog_by_name["Blood Moon"]], ["Tundra"])
    moon = game.players[0].battlefield[0]
    game._recompute_continuous_effects()

    (change,) = land_type_changes(tundra, derived=True)
    assert change["timestamp"] == moon.timestamp
    # …and re-entering is a new object with a new stamp (CR 400.7), which the
    # contribution follows on the next recompute.
    from engine.continuous import next_timestamp

    moon.timestamp = next_timestamp()
    game._recompute_continuous_effects()
    (change,) = land_type_changes(tundra, derived=True)
    assert change["timestamp"] == moon.timestamp
