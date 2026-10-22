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

One family of meetings is below the census rather than in it, because the type
line cannot tell its answers apart: Titania's Song's "each *noncreature*
artifact" against the effects that make an artifact a creature (Karn, Animate
Artifact). The artifact is an artifact creature either way; what differs is
whether the Song *reached* it, and so whether it lost its abilities — layer 6
reading the Song's layer-4 reach (CR 613.6). Those are asserted on the
abilities, in ``test_oi_the_song_…``.
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


@pytest.mark.cr("613.8a", "613.8b", "613.6")
@pytest.mark.parametrize("order, song_reaches", [
    (("Animate Artifact", "Titania's Song"), False),
    (("Titania's Song", "Animate Artifact"), True),
])
def test_oi_the_song_and_animate_artifact_are_a_loop_the_older_one_wins(
    catalog_by_name, set_pool, order, song_reaches,
):
    """Titania's Song reaches "each **noncreature** artifact"; Animate Artifact
    applies "as long as enchanted artifact **isn't a creature**". Each makes
    the artifact a creature, so each changes whether the other applies: a
    dependency loop, which CR 613.8b applies in timestamp order. The older one
    animates the Howling Mine and the younger finds a creature and does
    nothing.

    The type line is the same either way. What differs is the rest of the
    Song's sentence — "loses all abilities" — which CR 613.6 applies in layer 6
    to the set of objects layer 4 found: the Mine keeps its ability under an
    Animate Artifact that was there first, and loses it under a Song that was.
    Both scopes read the printed type line, so the Song always applied."""
    from engine.global_statics import removes_all_abilities

    b = _W2G4Board(catalog_by_name, set_pool)
    mine = b.enter("Howling Mine")
    for name in order:
        b.cast(name, at=mine if name == "Animate Artifact" else None)

    assert _w2g4_types(mine)[0] == ["artifact", "creature"]
    assert removes_all_abilities(mine) is song_reaches
    assert ("draws an additional card" in mine.effective_card.oracle_text) is (
        not song_reaches
    )
    # Its mana value either way: both effects set the same body (layer 7b).
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


@pytest.mark.cr("613.8a", "613.6", "514.2")
def test_oi_the_song_passes_by_an_artifact_karn_already_animated(
    catalog_by_name, set_pool,
):
    """Karn makes a Howling Mine an artifact creature until end of turn; then
    Titania's Song arrives. The Song depends on Karn's effect (CR 613.8a) — it
    is what stops the Mine being a noncreature artifact — so it applies after
    it and does not reach the Mine, which keeps its ability for the turn. At
    cleanup Karn's effect ends (CR 514.2) and the Song takes the Mine after
    all."""
    from engine.global_statics import removes_all_abilities

    b = _W2G4Board(catalog_by_name, set_pool)
    karn, mine = b.enter("Karn, Silver Golem"), b.enter("Howling Mine")
    b.activate(karn, 0, at=mine)
    b.cast("Titania's Song")

    assert _w2g4_types(mine)[0] == ["artifact", "creature"]
    assert not removes_all_abilities(mine)
    assert "draws an additional card" in mine.effective_card.oracle_text
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)

    b.game.resolve_cleanup_step(0)
    assert _w2g4_types(mine)[0] == ["artifact", "creature"]
    assert removes_all_abilities(mine)
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


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


# ---------------------------------------------------------------------------
# An animation is stamped as it is created (CR 613.7b)
# ---------------------------------------------------------------------------
#
# ``handlers/board_misc._animation_record`` is the one writer of an animation,
# and it stamped only the records that *replace* the printed types (the Opal,
# Hidden, Veiled and Lurking enchantments). An addition — Mishra's Factory, a
# land Natural Affinity woke, Jade Statue — read as timestamp 0, on the
# argument that additions commute. With each other they do; with an effect
# that **sets** the card types they do not, and an addition older than
# everything was applied before the set whichever came first.


def _j6_animating_ability(perm):
    """The index of *perm*'s ability whose instruction animates something."""
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(perm.effective_card)
    return next(
        index for index, ability in enumerate(program.activated_abilities)
        if ability.instruction is not None
        and any(
            step.kind.startswith("animate_")
            for step in _j6_steps(ability.instruction)
        )
    )


def _j6_steps(instruction):
    yield instruction
    for value in (instruction.payload or {}).values():
        nested = value if isinstance(value, (list, tuple)) else (value,)
        for item in nested:
            if hasattr(item, "kind") and hasattr(item, "payload"):
                yield from _j6_steps(item)


def _j6_factory(b):
    factory = b.enter("Mishra's Factory")
    b.activate(factory, _j6_animating_ability(factory))
    return factory, "animate_until_end_of_turn"


def _j6_stones(b):
    stones = b.enter("Stalking Stones")
    b.activate(stones, _j6_animating_ability(stones))
    return stones, "animate_indefinitely"


def _j6_statue(b):
    statue = b.enter("Jade Statue")
    game = b.game
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat: "activate only during combat"
    b.activate(statue, _j6_animating_ability(statue))
    return statue, "animate_until_end_of_combat"


def _j6_animate_land(b):
    forest = b.enter("Forest")
    b.cast("Animate Land", at=forest)
    return forest, "animate_until_end_of_turn"


def _j6_druid(b):
    druid, forest = b.enter("Quirion Druid"), b.enter("Forest")
    b.activate(druid, _j6_animating_ability(druid), at=forest)
    return forest, "animate_indefinitely"


def _j6_affinity(b):
    forest = b.enter("Forest")
    b.cast("Natural Affinity")
    return forest, "animate_until_end_of_turn"


#: Every instruction kind that writes an animation record, with the card that
#: makes one here. (``animate_all_lands`` is a static — Kormus Bell — and is
#: placed by the board-wide pass, not recorded.)
_J6_ANIMATIONS = {
    "animate_self_until_eot": _j6_factory,
    "animate_self_indefinitely": _j6_stones,
    "animate_self_until_end_of_combat": _j6_statue,
    "animate_target_until_eot": _j6_animate_land,
    "animate_target_indefinitely": _j6_druid,
    "animate_matching_until_eot": _j6_affinity,
}


@pytest.mark.cr("613.7b")
@pytest.mark.parametrize("kind", sorted(_J6_ANIMATIONS))
def test_j6_an_animation_is_stamped_as_it_is_created(catalog_by_name, set_pool, kind):
    """Each kind of animation, made through the engine: the record carries the
    clock's stamp for the moment it resolved, and the layer-4 effect the
    collector builds from it is ordered by that stamp."""
    from engine.continuous import next_timestamp
    from engine.layer_bridge import collect_own_type_effects

    b = _W2G4Board(catalog_by_name, set_pool)
    before = next_timestamp()
    subject, key = _J6_ANIMATIONS[kind](b)
    after = next_timestamp()

    assert subject.is_creature
    record = subject.metadata[key]
    assert not record.get("replaces_types"), "an addition"
    assert before < record["timestamp"] < after
    (effect,) = [
        effect for effect in collect_own_type_effects(subject, id(subject))
        if effect.label == f"animated ({key})"
    ]
    assert effect.timestamp == record["timestamp"]


@pytest.mark.cr("613.7b")
def test_j6_every_animation_writing_kind_in_the_pool_is_stamped_here():
    """The floor on the other axis: a seventh kind of animation the pool
    compiles and no row above makes would be a record nothing has watched
    being stamped."""
    import dataclasses

    from engine.card_loader import load_cards, manifest_set_paths
    from engine.handlers.registry import EFFECT_HANDLERS
    from engine.oracle import compiled_units
    from engine.oracle_types import OracleInstruction

    def walk(value, seen):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, OracleInstruction):
            yield value
            yield from walk(value.payload, seen)
        elif isinstance(value, dict):
            for item in value.values():
                yield from walk(item, seen)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from walk(item, seen)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field in dataclasses.fields(value):
                yield from walk(getattr(value, field.name), seen)

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    found = {}
    for card, program in compiled_units(pool.values()):
        for instruction in walk(program, set()):
            kind = instruction.kind
            if kind.startswith("animate_") and kind in EFFECT_HANDLERS:
                found.setdefault(kind, set()).add(card.name)
    assert set(found) == set(_J6_ANIMATIONS), sorted(set(found) ^ set(_J6_ANIMATIONS))
    assert len(pool) >= 4700, len(pool)
    assert sum(len(cards) for cards in found.values()) >= 40, {
        kind: len(cards) for kind, cards in found.items()
    }


@pytest.mark.cr("613.7", "613.7b", "205.1a", "205.1b")
def test_j6_an_addition_made_after_a_card_type_set_is_applied_after_it(
    catalog_by_name, set_pool,
):
    """Soul Sculptor makes a Grizzly Bears an enchantment and nothing else
    (CR 205.1a); an animation created *afterwards* adds "creature" on top of
    that (CR 205.1b), because it is the later effect (CR 613.7).

    No two cards in the pool can arrange it — what animates is aimed at a land
    or an artifact, and the Sculptor's permanent is neither — so the second
    effect is written by the animation's own writer rather than by a card.
    The other order is a row of the census above ("karn>soul_sculptor" and its
    three neighbours), driven by cards: the set is later and the permanent is
    an enchantment only."""
    from engine.handlers.board_misc import ANIMATE_UNTIL_EOT, _animation_record

    b = _W2G4Board(catalog_by_name, set_pool)
    sculptor, bears = b.enter("Soul Sculptor"), b.enter("Grizzly Bears")
    b.activate(sculptor, 0, at=bears)
    assert _w2g4_types(bears)[0] == ["enchantment"]

    bears.metadata[ANIMATE_UNTIL_EOT] = _animation_record({"subtypes": ["ape"]})
    b.game._recompute_continuous_effects()
    # (The set took the Bears' subtypes with its card types; "bear" is gone.)
    assert _w2g4_types(bears)[:2] == (["creature", "enchantment"], ["ape"])

    b.game.resolve_cleanup_step(0)
    assert _w2g4_types(bears)[0] == ["enchantment"]


def _j6_clay_and_conspiracy(conspiracy_first):
    """Primal Clay entering as "a 1/6 **Wall** artifact creature with
    defender", beside a Conspiracy naming Elf. What an "as this enters" choice
    made the Clay is part of its copiable values (CR 613.2a, CR 707.2), where
    layer 4 starts — so "Creatures you control are the chosen type" replaces
    the Wall with the rest of its creature types whichever arrived first."""
    def case(b):
        def clay():
            perm = Permanent(card=b.card("Primal Clay"))
            b.game._put_permanent_onto_battlefield(0, perm, None)
            (prompt,) = [c for c in b.game.pending_choices if c.kind == "body_choice"]
            wall = next(
                index for index, option in enumerate(prompt.data["options"])
                if "wall" in [word.lower() for word in option.get("subtypes") or ()]
            )
            assert b.game.confirm_enter_body_choice(0, wall)
            return perm

        if conspiracy_first:
            b.cast("Conspiracy", creature_type="elf")
            subject = clay()
        else:
            subject = clay()
            assert "wall" in _w2g4_types(subject)[1]
            b.cast("Conspiracy", creature_type="elf")
        assert (subject.effective_power, subject.effective_toughness) == (1, 6)
        return (["artifact", "creature"], ["elf"]), _w2g4_types(subject)[:2]
    return case


_J6_CASES = {
    "conspiracy>primal_clay": _j6_clay_and_conspiracy(True),
    "primal_clay>conspiracy": _j6_clay_and_conspiracy(False),
}


@pytest.mark.cr("613.2a", "613.2c", "707.2", "613.8a")
@pytest.mark.parametrize("name", sorted(_J6_CASES))
def test_j6_type_effects_meet_in_the_order_the_rules_give(
    catalog_by_name, set_pool, name,
):
    want, got = _J6_CASES[name](_W2G4Board(catalog_by_name, set_pool))
    assert got == want, name


# ---------------------------------------------------------------------------
# Objects that enter together are stamped in APNAP order (CR 613.7m)
# ---------------------------------------------------------------------------
#
# "If two or more objects would receive a timestamp simultaneously, such as by
# entering a zone simultaneously … their relative timestamps are determined in
# APNAP order. Objects controlled by the active player … have an earlier
# relative timestamp in the order of that player's choice, followed by each
# other player in turn order."
#
# A permanent is stamped as it enters, so a handler that puts several players'
# cards onto the battlefield at once stamps them in the order its loop walks
# the seats. Six cards in the pool do that. Four walked the seats in APNAP
# order already; Living Death and Game Preserve walked ``range(len(players))``,
# which is APNAP only while seat 0 is the active player.

_J6_CREATURES = ("Grizzly Bears", "Hill Giant", "Savannah Lions", "Scryb Sprites")


def _j6_table(catalog_by_name, seats, active):
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game  # _j6_table


def _j6_drain(game):
    """Resolve everything, each seat answering what it is asked by default."""
    for _ in range(60):
        if game.stack:
            game.resolve_top_of_stack()
        for choice in list(game.pending_choices):
            game.auto_resolve_pending_choices(choice.player_index, kinds=[choice.kind])
        if not game.stack and not game.pending_choices:
            return
    raise AssertionError([c.kind for c in game.pending_choices])  # _j6_drain


def _j6_cast_mass_entry(game, card, seat):
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand(seat, card.name)
    assert cast.supported, cast.details
    _j6_drain(game)  # _j6_cast_mass_entry


def _j6_graveyards_of_creatures(game, card):
    for seat, player in enumerate(game.players):
        player.graveyard += [card(_J6_CREATURES[(seat + k) % 4]) for k in range(2)]


def _j6_twilights_call(game, card, seat):
    _j6_graveyards_of_creatures(game, card)
    _j6_cast_mass_entry(game, card("Twilight's Call"), seat)


def _j6_living_death(game, card, seat):
    _j6_graveyards_of_creatures(game, card)
    _j6_cast_mass_entry(game, card("Living Death"), seat)


def _j6_planar_birth(game, card, seat):
    for player in game.players:
        player.graveyard += [card("Forest"), card("Island")]
    _j6_cast_mass_entry(game, card("Planar Birth"), seat)


def _j6_stronghold_gambit(game, card, seat):
    for player in game.players:
        player.hand.append(card("Grizzly Bears"))
    _j6_cast_mass_entry(game, card("Stronghold Gambit"), seat)


def _j6_game_preserve(game, card, seat):
    for player in game.players:
        player.library += [card("Grizzly Bears")] + [card("Forest")] * 6
    game._put_permanent_onto_battlefield(seat, Permanent(card=card("Game Preserve")), None)
    game._j6_already = {id(perm) for perm in game.all_permanents()}
    game.start_turn(seat)
    _j6_drain(game)


#: Each pool card that puts **several players'** cards onto the battlefield at
#: once, by the instruction kind that does it, and how one is made here.
_J6_ENTER_TOGETHER = {
    "Twilight's Call": ("return_all_cards_from_graveyard", _j6_twilights_call),
    "Planar Birth": ("return_all_cards_from_graveyard", _j6_planar_birth),
    "Living Death": ("put_exiled_this_way", _j6_living_death),
    "Stronghold Gambit": ("put_chosen_hand_cards_onto_battlefield", _j6_stronghold_gambit),
    "Game Preserve": ("put_revealed_top_cards_onto_battlefield", _j6_game_preserve),
}

_J6_SEATINGS = [(seats, active) for seats in (2, 3) for active in range(seats)]


@pytest.mark.cr("613.7m", "101.4", "613.7d")
@pytest.mark.parametrize("name", sorted(_J6_ENTER_TOGETHER))
@pytest.mark.parametrize(
    "seats, active", _J6_SEATINGS, ids=[f"{s}p-active{a}" for s, a in _J6_SEATINGS],
)
def test_j6_cards_entering_together_are_stamped_in_apnap_order(
    catalog_by_name, set_pool, name, seats, active,
):
    """The active player's permanents carry the earlier timestamps, then each
    other player's in turn order — whichever seat the active player is on."""
    card = lambda wanted: (  # noqa: E731
        catalog_by_name[wanted] if wanted in catalog_by_name
        else set_pool("PLS")[wanted]
    )
    game = _j6_table(catalog_by_name, seats, active)
    already = {id(perm) for perm in game.all_permanents()}
    _J6_ENTER_TOGETHER[name][1](game, card, active)
    already |= getattr(game, "_j6_already", set())

    entered = sorted(
        (perm.timestamp, seat)
        for seat, perm in game.permanents_with_controller()
        if id(perm) not in already
    )
    by_stamp = [seat for _stamp, seat in entered]
    # The floor: every seat put something onto the battlefield.
    assert set(by_stamp) == set(range(seats)), (name, by_stamp)
    assert game.active_player_index == active
    turn_order = [(seat - active) % seats for seat in by_stamp]
    assert turn_order == sorted(turn_order), (
        f"{name}, active player on seat {active}: entered in seat order "
        f"{by_stamp}, and CR 613.7m stamps the active player's first"
    )


def _j6_looped_entry_handlers():
    """Every handler in ``engine/handlers/`` that puts a permanent onto the
    battlefield from inside a loop — the functions that *can* stamp several
    objects for one event."""
    import ast

    from tests.source_index import REPO_ROOT, source_tree

    found = set()
    for path in sorted((REPO_ROOT / "engine" / "handlers").glob("*.py")):
        tree = source_tree(path)
        parents = {
            child: node for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_put_permanent_onto_battlefield"
            ):
                continue
            looped, cursor = False, node
            while cursor in parents:
                cursor = parents[cursor]
                if isinstance(cursor, (ast.For, ast.While)):
                    looped = True
                if isinstance(cursor, ast.FunctionDef):
                    if looped:
                        found.add(cursor.name)
                    break
    return found  # _j6_looped_entry_handlers


#: The looped entry handlers, each with whose cards one event can put down:
#: "several" is a row of the census above, "one" a single seat's cards — where
#: the order is that player's own choice (see the Replenish test below).
_J6_LOOPED_ENTRY_HANDLERS = {
    # Twilight's Call, Planar Birth. The handler's move is its helper's since
    # Torment's wave 2 (W2G2): every card enters after the last returning
    # Aura's host is chosen (CR 303.4f), so the loop runs in the continuation
    # ``_return_planned_cards`` rather than in the handler's own body.
    "_return_planned_cards": "several",
    "put_exiled_this_way": "several",                   # Living Death
    "put_chosen_hand_cards_onto_battlefield": "several",  # Stronghold Gambit
    "put_revealed_top_cards_onto_battlefield": "several",  # Game Preserve
    "create_token": "one",              # one seat's tokens per instruction
    "reanimate_graveyard_position": "one",              # Bone Dancer
    "reanimate_announced_cards": "one",                 # Victimize
    "put_cards_from_hand_onto_battlefield": "one",      # Manabond, Ugin's −10
    "reanimate_bound_card": "one",                      # one bound card per event
    "_place_sorted_reveal": "one",
    "put_revealed_card_onto_battlefield": "one",        # Call of the Wild
    "put_exiled_cards_into_zone": "one",                # Liberate and its kin
}


@pytest.mark.cr("613.7m")
def test_j6_every_handler_that_can_enter_several_permanents_is_accounted_for():
    """The floor on the other axis. A handler that puts permanents onto the
    battlefield in a loop is one that stamps several objects for one event; a
    new one has to say whose cards it moves, and if they are several players',
    walk ``Game.apnap_seats`` and be driven above."""
    assert _j6_looped_entry_handlers() == set(_J6_LOOPED_ENTRY_HANDLERS), sorted(
        _j6_looped_entry_handlers() ^ set(_J6_LOOPED_ENTRY_HANDLERS)
    )
    several = {
        _J6_HELPER_KINDS.get(name, name)
        for name, whose in _J6_LOOPED_ENTRY_HANDLERS.items() if whose == "several"
    }
    assert several == {kind for kind, _make in _J6_ENTER_TOGETHER.values()}


#: A looped entry that lives in a handler's helper, by the instruction kind
#: whose handler it is.
_J6_HELPER_KINDS = {"_return_planned_cards": "return_all_cards_from_graveyard"}


def _j6_ordered_static_sources():
    """Every pool permanent card that is the source of a static whose place in
    a timestamp order is observable — layer 4 or layer 5 — by primary type."""
    from engine import auras, global_statics
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.land_animation import LAND_ANIMATION_KIND
    from engine.land_types import STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND
    from engine.oracle import compiled_units

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    board_kinds = {STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND, LAND_ANIMATION_KIND}
    found = {}
    for card, program in compiled_units(pool.values()):
        if card.primary_type in ("instant", "sorcery"):
            continue
        text = card.oracle_text or ""
        static = global_statics.global_static_for(text)
        ordered = any(step.kind in board_kinds for step in program.instructions) or (
            static is not None and (
                global_statics.changes_types(static)
                or static.sets_colors is not None
                or static.sets_chosen_color
            )
        )
        attached = bool(
            auras.aura_animates_artifact(text)
            or auras.aura_color_grants(text)
            or (auras.aura_land_animation(text) or {}).get("colors")
            or auras.aura_type_grants(text)
            or auras.aura_card_type_grants(text)
        )
        if ordered or attached:
            found.setdefault(card.primary_type, set()).add(card.name)
    return len(pool), found  # _j6_ordered_static_sources


@pytest.mark.cr("613.7m", "613.7a")
def test_j6_no_card_that_enters_beside_another_players_carries_an_ordered_static():
    """Why the order above is right and, today, unobservable through a static.
    Every card the pool's cross-player mass entries move is a creature card or
    a basic land card, and no creature or land card is the source of a layer-4
    or layer-5 static — they are enchantments and two artifacts. (The one
    creature here, Transmogrifying Licid, grants its type as an Aura and only
    once it has made itself one.) A Magus of the Moon in the pool is what
    changes that, and it fails here first."""
    pool_size, found = _j6_ordered_static_sources()
    assert found.get("creature") == {"Transmogrifying Licid"}
    assert "land" not in found
    assert found["artifact"] == {"Kormus Bell", "Thran Lens"}
    assert len(found["enchantment"]) >= 22, sorted(found["enchantment"])
    assert pool_size >= 4700, pool_size


@pytest.mark.cr("613.7m", "101.4")
@pytest.mark.parametrize("caster", [0, 1])
def test_j6_show_and_tell_stamps_the_active_players_card_first(
    catalog_by_name, set_pool, caster,
):
    """The one cross-player entry that *can* carry two ordered statics: "Each
    player may put an artifact, creature, enchantment, or land card from their
    hand onto the battlefield." The offers are made in APNAP order and each
    card enters as its offer is taken, so the active player's is the earlier —
    the other player's Darkest Hour is the later effect and the Bears are
    black, on whichever seat the caster sits."""
    card = catalog_by_name.__getitem__
    game = _j6_table(catalog_by_name, 2, caster)
    bears = Permanent(card=card("Grizzly Bears"))
    game._put_permanent_onto_battlefield(caster, bears, None)
    game.players[caster].hand += [card("Thran Lens")]
    game.players[1 - caster].hand += [card("Darkest Hour")]
    _j6_cast_mass_entry(game, card("Show and Tell"), caster)

    lens = next(p for p in game.controlled_by(caster) if p.card.name == "Thran Lens")
    hour = next(p for p in game.controlled_by(1 - caster) if p.card.name == "Darkest Hour")
    assert lens.timestamp < hour.timestamp
    assert sorted(game._effective_colors(bears)) == ["B"]


@pytest.mark.cr("613.7m")
@pytest.mark.parametrize("first, second, colour", [
    ("Darkest Hour", "Celestial Dawn", ["W"]),
    ("Celestial Dawn", "Darkest Hour", ["B"]),
])
def test_j6_replenish_orders_one_players_enchantments_as_the_graveyard_has_them(
    catalog_by_name, set_pool, first, second, colour,
):
    """The half of CR 613.7m that is **not** done: "in the order of that
    player's choice". Replenish returns one player's enchantments together,
    and two of them can each set a colour — so the order is observable, and it
    is the player's to choose. The engine enters them in graveyard order and
    asks nobody: a legal order, picked for the player.

    Pinned so the day the choice is asked this fails and is rewritten. What
    asking takes: a prompt kind on ``pending_choices`` that orders a set of
    entering permanents (a renderer in ``web/prompt_board.py`` and its client
    half), armed by ``return_all_cards_from_graveyard`` and
    ``put_cards_from_hand_onto_battlefield`` when two or more of one seat's
    cards enter and — to keep it from asking about every pair of Bears — at
    least two of them are sources of an ordered static
    (``_j6_ordered_static_sources`` is that question); and the entries made
    in the answered order."""
    card = catalog_by_name.__getitem__
    game = _j6_table(catalog_by_name, 2, 0)
    bears = Permanent(card=card("Grizzly Bears"))
    game._put_permanent_onto_battlefield(0, bears, None)
    game.players[0].graveyard += [card(first), card(second)]
    _j6_cast_mass_entry(game, card("Replenish"), 0)

    stamps = {
        perm.card.name: perm.timestamp for perm in game.controlled_by(0)
        if perm.card.name in (first, second)
    }
    assert stamps[first] < stamps[second]
    assert sorted(game._effective_colors(bears)) == colour


@pytest.mark.cr("101.4", "613.7m")
def test_j6_apnap_seats_starts_with_the_active_player_and_skips_who_has_left(
    catalog_by_name,
):
    game = _j6_table(catalog_by_name, 4, 2)
    assert game.apnap_seats() == [2, 3, 0, 1]
    assert game.apnap_seats([0, 3]) == [3, 0]
    game.players[3].lost = True
    assert game.apnap_seats() == [2, 0, 1]
    assert game.apnap_seats(include_lost=True) == [2, 3, 0, 1]
    game.active_player_index = 0
    assert game.apnap_seats() == [0, 1, 2]


# ---------------------------------------------------------------------------
# A static whose source loses its abilities (CR 613.1, CR 613.6, CR 613.8a)
# ---------------------------------------------------------------------------
#
# Layer 4, then layer 5, then layer 6 — every time. So an ability that
# generates a type or colour effect is still there when that effect is applied,
# whatever layer 6 then does to it, and CR 613.6 carries the rest of the same
# effect through the later layers "even if the ability generating the effect
# is removed during this process". A static whose *whole* effect is layer 6 or
# later is the opposite case: applying the removal ends it (CR 613.8a, a
# dependency on the effect's existence), so the removal applies first.
#
# The engine read the land-type statics, Melting and the land animators off
# ``Permanent.effective_card`` — the finished text, layer 6's removals struck
# out — so all twelve vanished with their source's abilities; and it read the
# global statics off the printed text, so the four that are all layer 6 went
# on applying from a source that no longer had them.


def _j6_stripped(b, name, witness_name, **answers):
    """*witness_name*, then the static *name*, then its source stripped of
    every ability: an enchantment by Opalescence (a creature now) and
    Humility, an artifact by Titania's Song. Returns the game, the source, the
    witness and what the witness read as before the strip."""
    game = b.game
    witness = b.enter(witness_name)
    alone = (_w2g4_types(witness), sorted(game._effective_colors(witness)))
    source = Permanent(card=b.card(name))
    game._put_permanent_onto_battlefield(0, source, None)
    for choice in list(game.pending_choices):
        assert game.confirm_enter_choice(choice.player_index, **answers), name
    game._recompute_continuous_effects()
    under = (_w2g4_types(witness), sorted(game._effective_colors(witness)))
    if "artifact" in _w2g4_types(source)[0]:
        b.enter("Titania's Song")
    else:
        b.enter("Opalescence")
        b.enter("Humility")
    assert (source.effective_card.oracle_text or "") == "", "the source is stripped"
    return game, source, witness, alone, under  # _j6_stripped


#: Every pool static with a layer-4 or layer-5 part, and a permanent it moves.
_J6_TYPE_AND_COLOUR_STATICS = {
    # read off the source's text by ``_board_type_statics``
    "Blood Moon": ("Tundra", {}),
    "Conversion": ("Mountain", {}),
    "Blanket of Night": ("Forest", {}),
    "Glaciers": ("Mountain", {}),
    "Illusionary Terrain": ("Forest", {"land_types": ["forest", "island"]}),
    "Melting": ("Snow-Covered Forest", {}),
    "Living Lands": ("Forest", {}),
    "Living Plane": ("Forest", {}),
    "Natural Emergence": ("Forest", {}),
    "Nature's Revolt": ("Forest", {}),
    "Celestial Dawn": ("Tundra", {}),
    "Kormus Bell": ("Swamp", {}),
    # a ``global_statics`` row
    "Conspiracy": ("Grizzly Bears", {"creature_type": "elf"}),
    "Dralnu's Crusade": ("Goblin Raider", {}),
    "Darkest Hour": ("Grizzly Bears", {}),
    "Shifting Sky": ("Grizzly Bears", {"mana_color": "U"}),
    "Thran Lens": ("Grizzly Bears", {}),
}

#: The twelve that vanished with their source's abilities on the tree before.
_J6_VANISHED = (
    "Blood Moon", "Conversion", "Blanket of Night", "Glaciers",
    "Illusionary Terrain", "Melting", "Living Lands", "Living Plane",
    "Natural Emergence", "Nature's Revolt", "Celestial Dawn", "Kormus Bell",
)


@pytest.mark.cr("613.1d", "613.1e", "613.1f", "613.6")
@pytest.mark.parametrize("name", sorted(_J6_TYPE_AND_COLOUR_STATICS))
def test_j6_a_type_or_colour_static_outlives_its_sources_abilities(
    catalog_by_name, set_pool, name,
):
    """The static's source is a creature with no abilities, and the permanent
    it reached is exactly what it was: layers 4 and 5 were applied before
    layer 6 took the ability away."""
    witness_name, answers = _J6_TYPE_AND_COLOUR_STATICS[name]
    b = _W2G4Board(catalog_by_name, set_pool)
    _game, _source, witness, alone, under = _j6_stripped(
        b, name, witness_name, **answers
    )
    assert under != alone, f"{name} does something to a {witness_name}"
    after = (_w2g4_types(witness), sorted(b.game._effective_colors(witness)))
    assert after == under, f"{name} lost its abilities and its effect with them"


@pytest.mark.cr("613.6")
def test_j6_the_stripped_source_census_covers_every_type_static_the_pass_gathers():
    """The floor: every pool card that compiles one of the three instruction
    kinds ``_board_type_statics`` reads off a source's text is a row above."""
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.land_animation import LAND_ANIMATION_KIND
    from engine.land_types import STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND
    from engine.oracle import compiled_units

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    kinds = {STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND, LAND_ANIMATION_KIND}
    gathered = {
        card.name for card, program in compiled_units(pool.values())
        if any(step.kind in kinds for step in program.instructions)
    }
    assert gathered == set(_J6_VANISHED), sorted(gathered ^ set(_J6_VANISHED))
    assert set(_J6_VANISHED) <= set(_J6_TYPE_AND_COLOUR_STATICS)
    assert len(pool) >= 4700, len(pool)


@pytest.mark.cr("613.6", "613.4b")
def test_j6_kormus_bell_under_titanias_song_still_wakes_the_swamps(
    catalog_by_name, set_pool,
):
    """All three layers of one effect, in the cards' words: "All Swamps are
    1/1 black creatures that are still lands." Titania's Song takes the Bell's
    abilities (and makes it a 4/4); the Swamp is still a creature (layer 4),
    still black (layer 5) and still 1/1 (layer 7b)."""
    b = _W2G4Board(catalog_by_name, set_pool)
    game, bell, swamp, _alone, _under = _j6_stripped(b, "Kormus Bell", "Swamp")
    assert bell.is_creature and (bell.effective_power, bell.effective_toughness) == (4, 4)
    assert swamp.is_creature
    assert sorted(game._effective_colors(swamp)) == ["B"]
    assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)


@pytest.mark.cr("613.1e", "613.1f")
def test_j6_alloy_golem_under_humility_is_still_the_colour_it_chose(
    catalog_by_name, set_pool,
):
    """"This creature is the chosen color." A layer-5 effect of an ability
    layer 6 removes afterwards — the Golem is a 1/1 with no abilities, and
    red. It read as colourless: the colour stood down "once its abilities are
    gone", and at layer 5 they are not."""
    b = _W2G4Board(catalog_by_name, set_pool)
    golem = Permanent(card=b.card("Alloy Golem"))
    b.game._put_permanent_onto_battlefield(0, golem, None)
    assert b.game.confirm_enter_choice(0, mana_color="R")
    b.game._recompute_continuous_effects()
    assert sorted(b.game._effective_colors(golem)) == ["R"]

    for order in ("after", "before"):
        humility = b.enter("Humility")
        assert (golem.effective_card.oracle_text or "") == ""
        assert (golem.effective_power, golem.effective_toughness) == (1, 1)
        assert sorted(b.game._effective_colors(golem)) == ["R"], order
        b.game.remove_from_battlefield(humility)
        b.game._recompute_continuous_effects()


#: The pool's global statics whose whole effect is layer 6: an ability granted
#: to a class of permanents, read off the witness's own text.
_J6_LAYER_6_STATICS = {
    "Energy Flux": ("Sol Ring", "sacrifice this artifact unless you pay"),
    "Aura Flux": ("Castle", "sacrifice this enchantment unless you pay"),
    "Breath of Dreams": ("Grizzly Bears", "cumulative upkeep {1}"),
    "High Ground": ("Grizzly Bears", "can block an additional creature"),
}


@pytest.mark.cr("613.1f", "613.8a", "613.8b")
@pytest.mark.parametrize("name", sorted(_J6_LAYER_6_STATICS))
def test_j6_a_static_that_is_all_layer_6_ends_with_its_sources_abilities(
    catalog_by_name, set_pool, name,
):
    """The other direction. Opalescence makes *name* a creature and Humility
    takes its abilities: the granting effect and the removal are both layer 6,
    and applying the removal would end the grant's existence (CR 613.8a), so
    the removal applies first and nothing is granted — whichever is older."""
    witness_name, granted = _J6_LAYER_6_STATICS[name]

    def has_it(perm):
        return granted in (perm.effective_card.oracle_text or "").lower()

    b = _W2G4Board(catalog_by_name, set_pool)
    witness = b.enter(witness_name)
    source = b.enter(name)
    assert has_it(witness)
    b.enter("Opalescence")
    humility = b.enter("Humility")
    assert (source.effective_card.oracle_text or "") == ""
    assert not has_it(witness), f"{name} has no abilities and went on granting one"

    # …and it grants again the moment it has its abilities back.
    b.game.remove_from_battlefield(humility)
    b.game._recompute_continuous_effects()
    assert has_it(witness)


@pytest.mark.cr("613.6", "613.4b", "613.1f")
def test_j6_humility_still_applies_after_stripping_itself(catalog_by_name, set_pool):
    """The remover is not asked whether it still has its ability. Humility
    under Opalescence is a creature that has lost all abilities — its own
    among them — and every creature is still a 1/1 without any."""
    b = _W2G4Board(catalog_by_name, set_pool)
    sprites = b.enter("Scryb Sprites")
    assert sprites.has_keyword("flying")
    b.enter("Opalescence")
    humility = b.enter("Humility")
    assert humility.is_creature and (humility.effective_card.oracle_text or "") == ""
    assert not sprites.has_keyword("flying")
    assert (sprites.effective_power, sprites.effective_toughness) == (1, 1)


@pytest.mark.cr("613.6", "613.1f")
def test_j6_an_animators_keyword_goes_to_the_lands_the_layer_4_pass_reached(
    catalog_by_name, set_pool,
):
    """"Lands you control are 2/2 creatures **with first strike**." (Natural
    Emergence.) The creature type is layer 4 and the keyword layer 6, and
    CR 613.6 applies the later part "to the same set of objects" the first
    part reached — decided by the board-wide pass and read off the record it
    leaves, not asked again of the finished layer.

    Your Forest has first strike and the opponent's does not, and the record
    names the animator on the one and is absent from the other.

    **The two readings cannot be told apart by any pair of cards**, and that
    is a result rather than a gap. The finished layer differs from the set the
    pass found only if something changes the land's types *after* the
    animator applied — and anything that would change which lands it reaches
    is an effect it depends on (CR 613.8a), so the pass applies that first.
    The last step here is that, on a board built by hand (no pool card sets a
    land's card types without also taking its abilities): a card-type set
    stamped *later* than the animator makes the Forest an enchantment and
    nothing else, the animator waits behind it, and the Forest is neither a
    creature nor a first striker — by the record and by the layer alike. Only
    a dependency loop (CR 613.8b) could part them, and no keyword-carrying
    animator in the pool is in one."""
    from engine.continuous import next_timestamp
    from engine.land_animation import LAND_ANIMATIONS_REACHING
    from engine.layer_bridge import SET_CARD_TYPES

    b = _W2G4Board(catalog_by_name, set_pool)
    game = b.game
    mine = b.enter("Forest")
    theirs = Permanent(card=b.card("Forest"))
    game._put_permanent_onto_battlefield(1, theirs, None)
    emergence = b.enter("Natural Emergence")

    assert mine.is_creature and mine.has_keyword("first strike")
    assert not theirs.is_creature and not theirs.has_keyword("first strike")
    assert [source for source, _a in mine.metadata[LAND_ANIMATIONS_REACHING]] == [emergence]
    assert LAND_ANIMATIONS_REACHING not in theirs.metadata

    mine.metadata[SET_CARD_TYPES] = {
        "card_types": ["enchantment"], "timestamp": next_timestamp(), "source": "test",
    }
    game._recompute_continuous_effects()
    assert _w2g4_types(mine)[0] == ["enchantment"]
    assert not mine.has_keyword("first strike")
    assert LAND_ANIMATIONS_REACHING not in mine.metadata

    del mine.metadata[SET_CARD_TYPES]
    game._recompute_continuous_effects()
    assert mine.is_creature and mine.has_keyword("first strike")
    game.remove_from_battlefield(emergence)
    game._recompute_continuous_effects()
    assert not mine.has_keyword("first strike")
    assert LAND_ANIMATIONS_REACHING not in mine.metadata
