"""CR 613.8a over CR 613.6: a lord that has lost all its abilities gives
nothing — neither its +1/+1 nor its keyword — whichever arrived first.

    Goblin King: Other Goblins get +1/+1 and have mountainwalk.
    Humility:    All creatures lose all abilities and have base power and
                 toughness 1/1.

The King's effect has a part in layer 6 (the keyword) and a part in layer 7c
(the +1/+1). CR 613.6 says an effect that has **started** to apply in one
layer goes on applying in the later ones "even if the ability generating the
effect is removed during this process" — which is how a Kormus Bell that
Titania's Song has stripped still makes Swamps creatures: it started in
layer 4, before layer 6 took anything.

**The decision this file holds.** That sentence does not rescue the King's
+1/+1, in either timestamp order, and it is a reading of the rule rather than
a quoted ruling:

* The two effects meet in layer 6. Applying Humility's removes the King's
  ability, which is "the existence of the first effect" (CR 613.8a), so the
  King's grant **depends on** Humility's removal and "waits to apply until
  just after" it (CR 613.8b) — whichever is older. Once it has been applied
  there is no ability and no effect: the grant never starts.
* So nothing "started to apply" for CR 613.6 to carry into layer 7c, and by
  7c the ability is gone. A lord whose whole effect is 7c never reaches the
  question: layer 6 is simply earlier.

The other reading — an older King applies its layer-6 half first, loses the
keyword to Humility, and keeps the +1/+1 by CR 613.6 — is timestamp order
without the dependency, and CR 613.8 says dependency "will override the
timestamp system". ``_refresh_global_statics`` already decides a board-wide
static whose whole effect is layer 6 or later the same way (Energy Flux under
Opalescence and Humility).

A lord that is **not** stripped is the other case, and ordinary timestamps:
its keyword grant goes if it is older than the loss
(``test_loses_all_abilities_timestamp_order.py``) and its +1/+1, layer 7c,
applies over Humility's 7b whichever arrived first.

**The census.** A *lord-shaped* source is found by doing it: a permanent is
put beside a panel no tribe, colour or card type misses, and it is one if any
member's size, keywords, protection or text moves and none's type or colour
does (one that moves a type or a colour starts in layer 4 or 5 and is CR
613.6's, held by ``test_type_effects_timestamp_order.py`` and
``test_color_effects_timestamp_order.py``). Each is then
stripped by every effect that can strip it — Humility for a creature and,
under Opalescence, for an enchantment; Titania's Song for an artifact; Humble
and Soul Sculptor aimed at a creature — in both orders, and the panel is
compared with the same board holding the source's **blank twin**, the same
card with no text. Anything a panel member has beside the stripped source and
not beside the twin leaked out of an ability that is not there.

Over the whole pool: 115 lord-shaped sources, 98 of them wholly layer 6 or
later, 284 (source, loss, order) cases, **0 leaks** on the tree this round
started from — the lord pass already read the stripped card. What the census
buys is that it stays so; the test below it shows the other reading is one
the census names. The committed run takes the pinned sources and every third
of the rest.
"""

from __future__ import annotations

import dataclasses
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import whole_card
from engine.grammar.vocabulary import CREATURE_TYPES
from engine.layer_bridge import (computed_abilities, computed_colors,
                                 computed_types)
from engine.models import CardDefinition, Permanent, _abilities_stripped
from tests.helpers import _nosick, resolve_stack


def _mk(name, type_line, colors=(), power="2", toughness="2"):
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw={}, power=power, toughness=toughness,
    )


_EVERY_TYPE = " ".join(word.title() for word in sorted(CREATURE_TYPES))

#: A panel a lord of any tribe, colour or card type reaches some member of.
PANEL = (
    _mk("Omni", "Creature — " + _EVERY_TYPE, ("W", "U", "B", "R", "G")),
    _mk("Omni Artifact", "Artifact Creature — " + _EVERY_TYPE),
    _mk("Mono W", "Creature — Soldier", ("W",)),
    _mk("Mono U", "Creature — Merfolk", ("U",)),
    _mk("Mono B", "Creature — Zombie", ("B",)),
    _mk("Mono R", "Creature — Goblin", ("R",)),
    _mk("Mono G", "Creature — Elf", ("G",)),
    _mk("Plain Artifact", "Artifact", (), None, None),
    _mk("Plain Enchantment", "Enchantment", ("W",), None, None),
    _mk("Plain Land", "Land — Forest Swamp", (), None, None),
)

#: Every source the pool-wide walk found whose whole effect is layer 6 or
#: later — a creature, an enchantment or an artifact that pumps, grants or
#: takes away. (Seventeen more start in layer 4 or 5.)
LORDS = (
    "Absolute Grace", "Absolute Law", "Acidic Sliver", "Anaba Spirit Crafter",
    "Angel's Trumpet", "Angelic Shield", "Arcades Sabboth", "Armor Sliver",
    "Ascendant Evincar", "Aura Flux", "Aysen Highway", "Bad Moon",
    "Barbed Sliver", "Breath of Dreams", "Call to Arms", "Castle", "Chaosphere",
    "Citanul Hierophants", "Clot Sliver", "Coat of Arms",
    "Concordant Crossroads", "Crusade", "Crystalline Sliver",
    "Death Pit Offering", "Deranged Hermit", "Dread of Night",
    "Eladamri, Lord of Leaves", "Elvish Champion", "Energy Flux",
    "Engineered Plague", "Faerie Noble", "Feline Sovereign", "Fervor",
    "Fires of Yavimaya", "Flowstone Surge", "Fortified Area", "Fountain Watch",
    "Fyndhorn Pollen", "Garruk's Uprising", "Gauntlet of Might",
    "Glorious Anthem", "Goblin King", "Goblin War Drums", "Hanna's Custody",
    "Heart Sliver", "Hibernation Sliver", "Hidden Path", "High Ground",
    "Horned Sliver", "Humility", "Intimidation", "Jacques le Vert", "Jihad",
    "Juniper Order Advocate", "Kaervek, the Spiteful", "Kavu Monarch", "Kaysa",
    "Knighthood", "Kobold Drill Sergeant", "Kobold Overlord",
    "Kobold Taskmaster", "Levitation", "Liliana's Devotee", "Lord of Atlantis",
    "Lord of the Undead", "Lumbering Satyr", "Mindwhip Sliver",
    "Mnemonic Sliver", "Muscle Sliver", "Pack Leader", "Parapet",
    "Pendrell Mists", "Primal Rage", "Retaliation", "Righteous War",
    "Serra's Blessing", "Shimmer", "Soraya the Falconer", "Spectral Guardian",
    "Spidersilk Armor", "Spiritual Asylum", "Sterling Grove",
    "Stronghold Taskmaster", "Sunken City", "Talon Sliver",
    "The Tabernacle at Pendrell Vale", "Thrull Champion", "Tidal Influence",
    "Urborg Shambler", "Vampirism", "Verdeloth the Ancient", "Vibrating Sphere",
    "Victual Sliver", "Vile Consumption", "Waker of Waves", "Winged Sliver",
    "Zombie Master", "Zuberi, Golden Feather",
)

#: Always examined — one per way the buff is derived and per way its source
#: is stripped: a creature lord with both halves, with the keyword alone, with
#: the size alone; an enchantment (stripped under Opalescence) pumping,
#: granting a keyword, granting a quoted ability; an artifact (stripped by
#: Titania's Song); a creature that takes a size away.
PINNED = (
    "Goblin King", "Lord of Atlantis", "Winged Sliver", "Muscle Sliver",
    "Crusade", "Fervor", "Energy Flux", "Castle", "Gauntlet of Might",
    "Coat of Arms", "Kaervek, the Spiteful",
)

STRIDE = 3


@pytest.fixture(scope="module")
def _by_name():
    return {card.name: card for card in load_catalog()}


def _new_game(by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    return permanent


def _panel(game):
    return [_put(game, card) for card in PANEL]


def _late(game, permanents):
    """What layers 6 and 7 give each member: size, keywords, protection, text."""
    game._recompute_continuous_effects()
    return [
        (
            permanent.effective_power, permanent.effective_toughness,
            tuple(sorted(computed_abilities(permanent))),
            tuple(sorted(
                f"{kind}:{value}"
                for kind, value in game._protection_qualities(permanent)
            )),
            tuple(
                line for line in
                (permanent.effective_card.oracle_text or "").split("\n") if line
            ),
        ) if game.is_on_battlefield(permanent) else None
        for permanent in permanents
    ]


def _early(game, permanents):
    """What layers 4 and 5 give each member: types and colours."""
    game._recompute_continuous_effects()
    return [
        (
            tuple(sorted(computed_types(permanent)[0])),
            tuple(sorted(computed_types(permanent)[1])),
            tuple(sorted(computed_colors(permanent))),
        ) if game.is_on_battlefield(permanent) else None
        for permanent in permanents
    ]


def _blank(card):
    return dataclasses.replace(card, oracle_text="", keywords=())


def _lord_shape(by_name, card):
    """``(late, early)``: whether *card* alone moves any panel member's layer
    6/7 reading, and whether it moves any member's layer 4/5 one."""
    base = _new_game(by_name)
    members = _panel(base)
    _put(base, _blank(card))
    without = (_late(base, members), _early(base, members))
    game = _new_game(by_name)
    members = _panel(game)
    source = _put(game, card)
    late, early = _late(game, members), _early(game, members)
    if not game.is_on_battlefield(source):
        return False, False
    return late != without[0], early != without[1]


def _cast(game, by_name, name, target) -> bool:
    card = whole_card(by_name[name])
    game.players[0].hand.append(card)
    result = game.cast_from_hand(0, name, target_permanent_ids=[target.permanent_id])
    if not result.supported:
        game.take_card_from_hand(game.players[0], card)
        return False
    resolve_stack(game)
    return True


def _activate(game, permanent, target) -> bool:
    result = game.queue_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=0, target_permanent_ids=[target.permanent_id],
    )
    if not result.supported:
        return False
    resolve_stack(game)
    return True


def _losses(card):
    """``(remover, helpers, how)`` for every effect that could strip *card*."""
    types = card.type_line.lower()
    if "creature" in types:
        return [("Humility", (), "board"), ("Humble", (), "spell"),
                ("Soul Sculptor", (), "ability")]
    if "artifact" in types:
        return [("Titania's Song", (), "board")]
    if "enchantment" in types and "aura" not in types:
        return [("Humility", ("Opalescence",), "board")]
    return []


def _build(by_name, card, remover, helpers, how, order, *, twin):
    """One board: the panel, the helpers, then the source and its loss in
    *order*. None where the loss did not strip the source."""
    game = _new_game(by_name)
    members = _panel(game)
    for helper in helpers:
        _put(game, by_name[helper])
    game._recompute_continuous_effects()
    source_card = _blank(card) if twin else card

    def lose(source) -> bool:
        if how == "board":
            _put(game, by_name[remover])
            return True
        if how == "spell":
            return _cast(game, by_name, remover, source)
        return _activate(game, _put(game, by_name[remover]), source)

    if order == "source first":
        source = _put(game, source_card)
        game._recompute_continuous_effects()
        if not game.is_on_battlefield(source) or not lose(source):
            return None
    else:
        if how != "board":
            return None
        lose(None)
        source = _put(game, source_card)
    game._recompute_continuous_effects()
    if not game.is_on_battlefield(source):
        return None
    if not twin and not _abilities_stripped(source):
        return None
    return game, members


def _census(by_name, names):
    counts: Counter = Counter()
    leaks = []
    for name in names:
        card = by_name[name]
        late, early = _lord_shape(by_name, card)
        if not late or early:
            continue
        counts["lords"] += 1
        for remover, helpers, how in _losses(card):
            for order in ("source first", "remover first"):
                real = _build(by_name, card, remover, helpers, how, order, twin=False)
                twin = _build(by_name, card, remover, helpers, how, order, twin=True)
                if real is None or twin is None:
                    continue
                counts["cases"] += 1
                counts[order] += 1
                got, want = _late(*real), _late(*twin)
                if got != want:
                    leaks.append((name, remover, order, [
                        (PANEL[i].name, g[:3], w[:3])
                        for i, (g, w) in enumerate(zip(got, want)) if g != w
                    ][:2]))
    return counts, leaks


def _sample():
    return sorted(set(LORDS[::STRIDE]) | set(PINNED))


@pytest.mark.cr("613.1f", "613.6", "613.8a", "613.8b")
def test_no_lord_gives_anything_once_it_has_lost_its_abilities(_by_name):
    counts, leaks = _census(_by_name, _sample())

    # Floors: a sweep that reaches nothing passes. Measured 39 lords and 124
    # cases, 85 with the source older than its loss and 39 with it newer.
    assert counts["lords"] >= 36, counts
    assert counts["cases"] >= 110, counts
    assert counts["source first"] >= 75, counts
    assert counts["remover first"] >= 34, counts
    assert leaks == [], f"an ability that is not there still applied: {leaks[:12]}"


@pytest.mark.cr("613.6", "613.8a")
def test_the_census_names_a_lord_read_through_its_own_loss(_by_name, monkeypatch):
    """Backwards: read a stripped source's text as though layer 6 had not
    taken it — CR 613.6 applied without CR 613.8a's dependency, the reading
    this file decides against. The census names each pinned lord, in both
    orders, and what it names is exactly that reading's board: an older King
    whose Goblins are 2/2 with no mountainwalk."""
    real = Permanent.effective_card.fget

    def through_the_loss(self):
        card = real(self)
        return self.card_through_layer_3 if _abilities_stripped(self) else card

    monkeypatch.setattr(Permanent, "effective_card", property(through_the_loss))
    _counts, leaks = _census(
        _by_name, ("Goblin King", "Lord of Atlantis", "Crusade", "Gauntlet of Might")
    )

    named = {(name, remover, order) for name, remover, order, _what in leaks}
    for lord in ("Goblin King", "Lord of Atlantis", "Crusade"):
        assert (lord, "Humility", "source first") in named, sorted(named)
        assert (lord, "Humility", "remover first") in named, sorted(named)
    assert ("Goblin King", "Humble", "source first") in named
    assert ("Gauntlet of Might", "Titania's Song", "source first") in named
    king = next(
        what for name, remover, order, what in leaks
        if (name, remover, order) == ("Goblin King", "Humility", "source first")
    )
    assert king[0] == ("Omni", (2, 2, ()), (1, 1, ()))


# --- the cards, one board each -------------------------------------------


def _size(game, permanent):
    game._recompute_continuous_effects()
    return (permanent.effective_power, permanent.effective_toughness)


@pytest.mark.cr("613.6", "613.8a", "613.8b")
def test_goblin_king_under_humility_gives_neither_half_in_either_order(_by_name):
    for order in (("Goblin King", "Humility"), ("Humility", "Goblin King")):
        game = _new_game(_by_name)
        raiders = _put(game, _by_name["Mons's Goblin Raiders"])
        placed = {name: _put(game, _by_name[name]) for name in order}
        assert _size(game, raiders) == (1, 1), order
        assert not game._has_keyword(raiders, "mountainwalk"), order
        assert _size(game, placed["Goblin King"]) == (1, 1), order

        # Humility leaving gives both back at once (CR 611.3b).
        game.remove_from_battlefield(placed["Humility"])
        assert _size(game, raiders) == (2, 2), order
        assert game._has_keyword(raiders, "mountainwalk"), order


@pytest.mark.cr("613.8a", "613.7b")
def test_a_humbled_lord_stops_at_once_and_resumes_when_the_turn_ends(_by_name):
    game = _new_game(_by_name)
    lord = _put(game, _by_name["Lord of Atlantis"])
    merfolk = _put(game, _by_name["Merfolk of the Pearl Trident"])
    assert _size(game, merfolk) == (2, 2)
    assert game._has_keyword(merfolk, "islandwalk")

    assert _cast(game, _by_name, "Humble", lord)
    assert _size(game, merfolk) == (1, 1)
    assert not game._has_keyword(merfolk, "islandwalk")

    game.resolve_cleanup_step(0)
    assert _size(game, merfolk) == (2, 2)
    assert game._has_keyword(merfolk, "islandwalk")


@pytest.mark.cr("613.4b", "613.4c")
def test_a_lord_that_is_not_stripped_pumps_over_humility_in_either_order(_by_name):
    """Crusade is an enchantment: Humility does not reach it, its +1/+1 is
    layer 7c and Humility's 1/1 is 7b, so a white creature is 2/2 whichever
    arrived first. Under an Opalescence the Crusade is a creature too, loses
    the ability, and the white creature is 1/1."""
    for order in (("Crusade", "Humility"), ("Humility", "Crusade")):
        game = _new_game(_by_name)
        knight = _put(game, _by_name["White Knight"])
        for name in order:
            _put(game, _by_name[name])
        assert _size(game, knight) == (2, 2), order
        assert not game._has_keyword(knight, "first strike"), order

        _put(game, _by_name["Opalescence"])
        assert _size(game, knight) == (1, 1), order


@pytest.mark.cr("613.7a", "613.6")
def test_a_land_animators_keyword_is_stamped_with_the_animator(_by_name):
    """"Lands you control are 2/2 creatures with first strike." The keyword is
    layer 6 of an effect that started in layer 4 (CR 613.6), at the
    **animator's** timestamp: older than a Humility, the lands lose it; newer,
    they keep it. It was stamped with whichever permanent the pass before it
    had happened to visit last — so with anything newer than the Humility on
    the battlefield, an older Natural Emergence's lands kept first strike."""
    fodder = _mk("Fodder", "Enchantment", ("G",), None, None)

    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, fodder)
    _put(game, _by_name["Natural Emergence"])
    resolve_stack(game)
    assert game._has_keyword(forest, "first strike")
    _put(game, _by_name["Humility"])
    # …and something newer than both, last in the walk.
    _put(game, _by_name["Grizzly Bears"])
    _put(game, _by_name["Goblin King"])
    game._recompute_continuous_effects()
    assert forest.is_creature
    assert not game._has_keyword(forest, "first strike")

    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, fodder)
    _put(game, _by_name["Humility"])
    _put(game, _by_name["Natural Emergence"])
    resolve_stack(game)
    game._recompute_continuous_effects()
    assert game._has_keyword(forest, "first strike")
    assert _size(game, forest) == (2, 2)
