"""CR 613.4a / 613.4b over CR 613.7: effects that *set* power and toughness.

Layer 7 is applied in sublayers. A characteristic-defining ability's value is
7a; every effect that sets power and/or toughness to a number is 7b, and
within 7b they apply **in timestamp order**, so the newest one is the one a
permanent ends up with. Two things follow that the engine did not do:

* a 7a value loses to any 7b effect, whichever is older (Nightmare under a
  Humility is 1/1 however long the Nightmare has been there);
* two 7b effects are ordered by when each began — a static ability's by its
  object's timestamp (CR 613.7a), a resolved effect's by when it resolved
  (CR 613.7b), an Aura's by when it became attached (CR 613.7e).

The engine had 7b as two metadata slots at two constant timestamps (1 and 2),
a characteristic-defining ability written into the first of them, a static
land animator written into it as well, and every *derived* 7b effect — a
board-wide static's, a gained type's — at the constant 0. So "All creatures …
have base power and toughness 1/1" lost to every slot whenever it arrived, an
until-end-of-turn set beat everything, and of two animators the one listed
first on the battlefield decided the size.

The rulings this reads the rule by (Scryfall ``rulings_uri``, fetched for the
round):

    Overwhelming Splendor, 2017-07-14: "Overwhelming Splendor overwrites all
    previous effects that set a creature's base power and toughness to
    specific values. Any power- or toughness-setting effects that start to
    apply to a creature after Overwhelming Splendor becomes attached to its
    controller will overwrite this effect."

    Opalescence, 2006-02-01: "With a Humility and two Opalescences on the
    battlefield, if Humility has the latest timestamp, then all creatures are
    1/1 with no abilities. If the timestamp order is Opalescence, Humility,
    Opalescence, the second Opalescence is 1/1, and the Humility and first
    Opalescence are 4/4. If Humility has the earliest timestamp, then
    everything is 4/4."

**The census.** A *setter* is found by doing it: a card is put onto the
battlefield, cast at a subject, or one of its abilities is activated at a
subject, and it is a setter if the subject then carries a 7a or 7b effect it
did not carry before. Every two setters that both reach one permanent are
applied in each order — the older one from the other seat's battlefield where
it reaches from there, so that the order the battlefields are walked in is
not the order the effects arrived in — and the base power and toughness must
be the **later** one's, stat by stat. A characteristic-defining ability and
an "as this enters" body (a copiable value, CR 613.2a) lose in both orders.

Measured over the whole pool on the tree before the fix: 81 setters, and of
the contended (pair, order) cases 122 of 570 read the wrong size — 64 on an
animated land, 48 on a creature that defines or chose its own size, 7 on an
artifact, 3 on a creature. The committed run takes the setters from the
pinned list that walk produced rather than walking the pool again (which is
eight minutes), and holds the list to what it finds.

Not reached by this census, because nothing casts or activates them: a
*triggered* ability that sets a size (Wall of Tombstones, Brine Hag, the Opal
enchantments). They write through the same ``pt.set_base_pt``, which is where
the stamp is.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.continuous import Characteristics, apply_layers
from engine.faces import compilation_units, whole_card
from engine.layer_bridge import collect_pt_effects, seed_characteristics
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

#: The permanent each class of setter is aimed at. The land is both a Swamp
#: and a Forest, so that every animator with a land type in its scope reaches
#: it; the second creature is how a setter whose size is printed is told from
#: one whose size is read off its subject.
SUBJECTS = {
    "creature": "Grizzly Bears",
    "creature2": "Craw Wurm",
    "land": "Bayou",
    "artifact": "Rod of Ruin",
    "enchantment": "Crusade",
}

#: Every card the pool-wide walk found setting another permanent's size.
SETTERS = (
    # …an artifact's:
    "Animate Artifact", "Karn's Touch", "Karn, Silver Golem", "Titania's Song",
    "Xenic Poltergeist",
    # …a creature's:
    "Chariot of the Sun", "Humble", "Humility", "Jolrael, Mwonvuli Recluse",
    "Sorceress Queen", "Vhati il-Dal",
    # …an enchantment's:
    "Opalescence",
    # …a land's:
    "Animate Land", "Kormus Bell", "Living Lands", "Living Plane",
    "Living Terrain", "Mishra's Groundbreaker", "Natural Affinity",
    "Natural Emergence", "Nature's Revolt", "Quirion Druid", "Thelonite Druid",
    "Verdant Touch",
)

#: …and a sample of the fifty-odd that set their own: characteristic-defining
#: abilities in each shape the payload has (both stats, power alone, toughness
#: alone, a complement), an "as this enters" body, and a permanent that
#: animates itself for the turn and for good.
SELF_SETTERS = (
    "Nightmare", "Kinetic Augur", "People of the Woods", "Shapeshifter",
    "Serra Avatar", "Primal Clay", "Mishra's Factory", "Treetop Village",
    "Stalking Stones", "Lurking Evil", "Chimeric Idol",
)

FODDER = CardDefinition(
    name="Fodder", mana_cost="{G}", cmc=1.0, type_line="Enchantment",
    oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
    produced_mana=(), raw={},
)


@pytest.fixture(scope="module")
def _by_name():
    catalog = load_catalog()
    named = {card.name: card for card in catalog}
    named.update({unit.name: unit for unit in compilation_units(catalog)})
    return named


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


def _settle(game) -> None:
    """Drain the stack and answer everything owed with its default, so nothing
    an earlier step asked is still pending under the next one — and empty the
    hands, which nothing here wants and one setter counts."""
    for _ in range(20):
        resolve_stack(game)
        owed = (len(game.pending_choices), len(game.pending_replacement_choices))
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
        if not game.stack and owed == (0, 0):
            break
    for player in game.players:
        player.hand.clear()
    game._recompute_continuous_effects()


def _put(game, card, seat=0, *, settle=True):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    if settle:
        _settle(game)
    return permanent


def _cast(game, by_name, name, target=None) -> bool:
    card = whole_card(by_name[name])
    game.players[0].hand.append(card)
    kwargs = {}
    if target is not None:
        kwargs["target_permanent_ids"] = [target.permanent_id]
    result = game.cast_from_hand(0, name, **kwargs)
    if not result.supported:
        if any(held is card for held in game.players[0].hand):
            game.take_card_from_hand(game.players[0], card)
        return False
    _settle(game)
    return True


def _activate(game, permanent, target, ability_index) -> bool:
    kwargs = {}
    if target is not None:
        kwargs["target_permanent_ids"] = [target.permanent_id]
    result = game.queue_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=ability_index, **kwargs,
    )
    if not result.supported:
        return False
    _settle(game)
    return True


def _setter_effects(permanent):
    """Every 7a / 7b effect on *permanent*: (sublayer, power, toughness, label),
    a stat the effect leaves alone reading None."""
    found = []
    for effect in collect_pt_effects(permanent, id(permanent)):
        if effect.sublayer not in ("a", "b"):
            continue
        probe = Characteristics()
        effect.modify(probe)
        found.append((effect.sublayer, probe.power, probe.toughness, effect.label))
    return found


def _base_pt(game, permanent):
    """*permanent*'s power and toughness as layers 7a and 7b leave them."""
    game._recompute_continuous_effects()
    oid = id(permanent)
    state = {oid: seed_characteristics(permanent)}
    apply_layers(
        [e for e in collect_pt_effects(permanent, oid) if e.sublayer in ("a", "b")],
        state,
    )
    return (state[oid].power, state[oid].toughness)


def _is_spell(card) -> bool:
    types = card.type_line.lower()
    return "instant" in types or "sorcery" in types


def _is_aura(card) -> bool:
    return "aura" in card.type_line.lower()


def _fresh(by_name, subject_key):
    """A board with something for a count to count and an entry toll to take
    (Natural Emergence returns a red or green enchantment), and the subject."""
    game = _new_game(by_name)
    for seat in (0, 1):
        for name in ("Swamp", "Swamp", "Forest", "Island"):
            _put(game, by_name[name], seat, settle=False)
        _put(game, FODDER, seat, settle=False)
    for player in game.players:
        player.mana_pool.update({symbol: 20 for symbol in "WUBRGC"})
    game._recompute_continuous_effects()
    subject = None
    if subject_key != "self":
        subject = _put(game, by_name[SUBJECTS[subject_key]], 0)
    return game, subject


class _Setter:
    """One way one card sets a size: how it is applied, and to what."""

    def __init__(self, by_name, card, way, subject_key, seat=0):
        self.by_name, self.card, self.way = by_name, card, way
        self.subject_key, self.seat = subject_key, seat
        self.value = None

    def __repr__(self):
        return f"{self.card.name}{list(self.way)}@{self.subject_key}"

    @property
    def key(self):
        return (self.card.name, self.way, self.subject_key)

    @property
    def on_itself(self) -> bool:
        return self.subject_key == "self"

    @property
    def from_the_board(self) -> bool:
        return self.way[0] == "enter" and not self.on_itself

    @property
    def weak(self) -> bool:
        """A characteristic-defining ability or an "as this enters" body: what
        the permanent is from the moment it enters, which every 7b effect is
        applied over."""
        return self.way[0] == "self-enter"

    def apply(self, game, subject):
        """Apply to *subject* (None: a self setter that has yet to enter);
        the subject, or None where it could not be applied."""
        card = self.card
        if self.on_itself:
            if subject is None:
                subject = _put(game, card, 0)
            if not game.is_on_battlefield(subject):
                return None
            if self.way[0] == "self-activate" and not _activate(
                game, subject, None, self.way[1]
            ):
                return None
        elif self.way[0] == "enter":
            if _is_aura(card):
                if not _cast(game, self.by_name, card.name, subject):
                    return None
            elif not game.is_on_battlefield(_put(game, card, self.seat)):
                return None
        elif self.way[0] == "cast":
            if not _cast(game, self.by_name, card.name, subject):
                return None
        else:
            source = _put(game, card, 0)
            if not game.is_on_battlefield(source):
                return None
            if not _activate(game, source, subject, self.way[1]):
                return None
        return subject if game.is_on_battlefield(subject) else None

    def measure(self):
        """What this setter alone writes on its subject, stat by stat."""
        game, subject = _fresh(self.by_name, self.subject_key)
        before = _setter_effects(subject) if subject is not None else []
        subject = self.apply(game, subject)
        if subject is None:
            return None
        new = _setter_effects(subject)
        for entry in before:
            if entry in new:
                new.remove(entry)
        if not new:
            return None
        if len(new) == 1:
            return (new[0][1], new[0][2])
        return _base_pt(game, subject)


def _ways(card):
    if _is_spell(card):
        return [("cast",)]
    usable = usable_activated_abilities(compile_card_oracle(card))
    return [("enter",)] + [("activate", index) for index in range(len(usable))]


def _discover(by_name, names=SETTERS, self_names=SELF_SETTERS):
    setters = []
    for name in names:
        card = by_name[name]
        for way in _ways(card):
            for subject_key in ("creature", "land", "artifact", "enchantment"):
                # A permanent's static is tried from the *other* seat first.
                seats = (1, 0) if way[0] == "enter" and not _is_aura(card) else (0,)
                for seat in seats:
                    setter = _Setter(by_name, card, way, subject_key, seat)
                    setter.value = setter.measure()
                    if setter.value is not None:
                        setters.append(setter)
                        break
    for name in self_names:
        card = by_name[name]
        entered = _Setter(by_name, card, ("self-enter",), "self")
        entered.value = entered.measure()
        if entered.value is not None:
            setters.append(entered)
        for way in _ways(card)[1:]:
            setter = _Setter(by_name, card, ("self-activate", way[1]), "self")
            setter.value = setter.measure()
            if setter.value is not None and setter.value != entered.value:
                setters.append(setter)
    return setters


def _printed_size_on_creatures(by_name, setter, cache):
    """The size *setter* gives any creature, when it is the same on two: a
    setter scoped to creatures whose size is printed, which therefore reaches
    a land, an artifact or an enchantment something else has made one."""
    if setter.key not in cache:
        values = []
        for key in ("creature", "creature2"):
            values.append(
                _Setter(by_name, setter.card, setter.way, key, setter.seat).measure()
            )
        cache[setter.key] = (
            values[0] if values[0] is not None and values[0] == values[1] else None
        )
    return cache[setter.key]


def _overlay(newer, older):
    return tuple(n if n is not None else o for n, o in zip(newer, older))


def _pair(by_name, first, second, subject_key):
    game, subject = _fresh(by_name, subject_key)
    for setter in (first, second):
        if subject is None and not setter.on_itself:
            # A board-wide setter ahead of a subject that has yet to enter.
            if not setter.from_the_board:
                return None
            if not game.is_on_battlefield(_put(game, setter.card, setter.seat)):
                return None
            continue
        subject = setter.apply(game, subject)
        if subject is None:
            return None
    if subject is None or not game.is_on_battlefield(subject):
        return None
    return game, subject


def _census(by_name, names=SETTERS, self_names=SELF_SETTERS):
    setters = _discover(by_name, names, self_names)
    counts: Counter = Counter()
    wrong = []
    cache: dict = {}
    by_subject: dict = {}
    for setter in setters:
        by_subject.setdefault(setter.subject_key, []).append(setter)
    on_creatures = [
        setter for setter in by_subject.get("creature", ())
        if _printed_size_on_creatures(by_name, setter, cache) is not None
    ]

    def value_on(setter, subject_key):
        if setter.subject_key == subject_key:
            return setter.value
        return _printed_size_on_creatures(by_name, setter, cache)

    seen = set()
    for subject_key, own in by_subject.items():
        others = list(own) if subject_key != "self" else []
        if subject_key != "creature":
            others = others + on_creatures
        for a in own:
            for b in others:
                if a.card.name == b.card.name:
                    continue
                for first, second in ((a, b), (b, a)):
                    if (first.key, second.key, subject_key) in seen:
                        continue
                    seen.add((first.key, second.key, subject_key))
                    made = _pair(by_name, first, second, subject_key)
                    if made is None:
                        continue
                    game, subject = made
                    if not subject.is_creature:
                        continue
                    v_first = value_on(first, subject_key)
                    v_second = value_on(second, subject_key)
                    if v_first is None or v_second is None:
                        continue
                    printed = (
                        subject.effective_card.base_power,
                        subject.effective_card.base_toughness,
                    )
                    if _overlay(v_first, printed) == _overlay(v_second, printed):
                        continue
                    if second.weak:
                        expected = _overlay(v_first, _overlay(v_second, printed))
                    else:
                        expected = _overlay(v_second, _overlay(v_first, printed))
                    counts["cases"] += 1
                    counts[subject_key] += 1
                    got = _base_pt(game, subject)
                    if got != expected:
                        wrong.append((subject_key, repr(first), repr(second), got, expected))
    return setters, counts, wrong


@pytest.mark.cr("613.4a", "613.4b", "613.7a", "613.7b", "613.7e")
def test_every_pair_of_size_setting_effects_ends_at_the_newer_one(_by_name):
    setters, counts, wrong = _census(_by_name)

    # The pinned lists are what the pool-wide walk found; a name that no
    # longer sets anything has rotted out of the census without a failure.
    found = {setter.card.name for setter in setters}
    assert set(SETTERS) | set(SELF_SETTERS) <= found, sorted(
        (set(SETTERS) | set(SELF_SETTERS)) - found
    )
    # Floors: a sweep that reaches nothing passes. Measured 334 cases: 192 on
    # the land, 74 on a permanent that sets its own size, 37 on the artifact,
    # 23 on the creature, 8 on the enchantment.
    assert counts["cases"] >= 300, counts
    assert counts["land"] >= 170, counts
    assert counts["self"] >= 60, counts
    assert counts["artifact"] >= 30, counts
    assert counts["creature"] >= 20, counts
    assert counts["enchantment"] >= 6, counts
    assert wrong == [], f"the older size-setting effect won: {wrong[:20]}"


@pytest.mark.cr("613.7")
def test_the_census_names_a_layer_7b_with_no_timestamps(_by_name, monkeypatch):
    """Backwards: give every size-setting effect the place it used to have —
    the two slots at 1 and 2, a land animator's and a characteristic-defining
    ability's in the first slot, everything derived at 0. The census then names
    the meetings the round was opened for.

    (Not the stale count a Nightmare kept under a Humility, nor the first of
    two animators deciding a land: those were a 7a value sitting in a slot
    nothing cleared and one slot with two writers, which no timestamp brings
    back. The pool-wide walk named both on the tree before the fix.)"""
    import engine.layer_bridge as layer_bridge

    real = layer_bridge.set_pt

    def unstamped(target, power, toughness, *, timestamp, from_cda=False, label=""):
        if label == "set_until_eot":
            timestamp = 2
        elif label == "set" or label.startswith("land animation") or from_cda:
            timestamp = 1
        elif not label.startswith("animated:"):
            timestamp = 0
        return real(target, power, toughness, timestamp=timestamp, label=label)

    monkeypatch.setattr(layer_bridge, "set_pt", unstamped)
    _setters, _counts, wrong = _census(
        _by_name,
        ("Humility", "Humble", "Natural Emergence", "Nature's Revolt",
         "Living Terrain", "Animate Artifact"),
        ("Primal Clay",),
    )

    named = {(first, second) for _key, first, second, _got, _want in wrong}
    for pair in (
        ("Natural Emergence['enter']@land", "Humility['enter']@creature"),
        ("Nature's Revolt['enter']@land", "Humility['enter']@creature"),
        ("Primal Clay['self-enter']@self", "Humility['enter']@creature"),
        ("Humble['cast']@creature", "Humility['enter']@creature"),
        ("Animate Artifact['enter']@artifact", "Humility['enter']@creature"),
        ("Living Terrain['enter']@land", "Natural Emergence['enter']@land"),
    ):
        assert pair in named, (pair, sorted(named)[:40])


# --- the cards, one board each -------------------------------------------


def _board(by_name, *names, seats=None):
    """Put *names* onto the battlefield in order; ``{name: permanent}``."""
    game = _new_game(by_name)
    placed = {}
    for index, name in enumerate(names):
        seat = (seats or {}).get(name, 0)
        placed.setdefault(name, _put(game, by_name[name], seat))
        if name in placed and placed[name] is None:
            placed[name] = _put(game, by_name[name], seat)
    return game, placed


def _size(game, permanent):
    game._recompute_continuous_effects()
    return (permanent.effective_power, permanent.effective_toughness)


@pytest.mark.cr("613.4b", "613.7a")
def test_a_land_animator_and_humility_are_ordered_by_when_each_arrived(_by_name):
    """The meeting the round was opened for. Natural Emergence makes lands
    2/2 creatures and Humility makes creatures 1/1: both layer 7b, both static
    abilities, so the land is the size the newer enchantment says."""
    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, FODDER)
    _put(game, _by_name["Natural Emergence"])
    assert _size(game, forest) == (2, 2)
    _put(game, _by_name["Humility"])
    assert forest.is_creature
    assert _size(game, forest) == (1, 1)

    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, FODDER)
    _put(game, _by_name["Humility"])
    _put(game, _by_name["Natural Emergence"])
    assert _size(game, forest) == (2, 2)

    # …and Humility leaving gives the older animator's size back, with
    # nothing to undo (CR 611.3b).
    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, _by_name["Nature's Revolt"])
    humility = _put(game, _by_name["Humility"])
    assert _size(game, forest) == (1, 1)
    game.remove_from_battlefield(humility)
    assert _size(game, forest) == (2, 2)


@pytest.mark.cr("613.4b", "613.7a")
def test_of_two_land_animators_the_newer_decides_the_size(_by_name):
    """It was the one listed first on the battlefield."""
    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, _by_name["Nature's Revolt"])
    assert _size(game, forest) == (2, 2)
    lands = _put(game, _by_name["Living Lands"])
    assert _size(game, forest) == (1, 1)
    game.remove_from_battlefield(lands)
    assert _size(game, forest) == (2, 2)

    game = _new_game(_by_name)
    forest = _put(game, _by_name["Forest"])
    _put(game, _by_name["Living Lands"])
    _put(game, _by_name["Nature's Revolt"])
    assert _size(game, forest) == (2, 2)


@pytest.mark.cr("613.4a", "613.4b")
def test_a_characteristic_defining_size_loses_to_humility_in_both_orders(_by_name):
    """Layer 7a is applied before 7b whatever the timestamps say — and under
    Humility the ability is gone besides (CR 613.1f). Nightmare kept the count
    it had last been given, because the count was written where "set to 1/1"
    is read."""
    for order in (("Nightmare", "Humility"), ("Humility", "Nightmare")):
        game = _new_game(_by_name)
        for _ in range(3):
            _put(game, _by_name["Swamp"])
        placed = {name: _put(game, _by_name[name]) for name in order}
        nightmare = placed["Nightmare"]
        assert _size(game, nightmare) == (1, 1), order
        # …and it does not start counting again while the Humility is there.
        _put(game, _by_name["Swamp"])
        assert _size(game, nightmare) == (1, 1), order
        game.remove_from_battlefield(placed["Humility"])
        assert _size(game, nightmare) == (4, 4), order


@pytest.mark.cr("613.4a", "613.4b", "613.7b")
def test_a_resolved_set_beats_a_characteristic_defining_size_and_ends(_by_name):
    game = _new_game(_by_name)
    for _ in range(3):
        _put(game, _by_name["Swamp"])
    nightmare = _put(game, _by_name["Nightmare"])
    queen = _put(game, _by_name["Sorceress Queen"])
    assert _size(game, nightmare) == (3, 3)
    assert _activate(game, queen, nightmare, 0)
    assert _size(game, nightmare) == (0, 2)
    # The count goes on underneath: one more Swamp changes nothing this turn…
    _put(game, _by_name["Swamp"])
    assert _size(game, nightmare) == (0, 2)
    # …and is what the creature is once the turn's effect has ended.
    game.resolve_cleanup_step(0)
    assert _size(game, nightmare) == (4, 4)


@pytest.mark.cr("613.2a", "613.4b")
def test_a_body_chosen_as_it_entered_is_under_a_humility(_by_name):
    """CR 613.2a: "'As … enters' … abilities generate copiable effects if they
    set power and toughness". A copiable value is where the layers start, so
    Primal Clay's 3/3 is beneath every 7b effect — written at the place
    copiable values have (``layer_bridge.COPIABLE_VALUE``), not at "now"."""
    from engine.layer_bridge import COPIABLE_VALUE
    from engine.pt import BASE_PT_TIMESTAMP_KEY

    game = _new_game(_by_name)
    clay = _put(game, _by_name["Primal Clay"])
    assert _size(game, clay) == (3, 3)
    assert clay.metadata[BASE_PT_TIMESTAMP_KEY] == COPIABLE_VALUE
    humility = _put(game, _by_name["Humility"])
    assert _size(game, clay) == (1, 1)
    game.remove_from_battlefield(humility)
    assert _size(game, clay) == (3, 3)

    # Entering *under* a Humility it has no "as this enters" ability to apply
    # (CR 614.12), so no body is chosen at all: 1/1 while the Humility is
    # there, and the printed */* once it has gone.
    game = _new_game(_by_name)
    humility = _put(game, _by_name["Humility"])
    clay = _put(game, _by_name["Primal Clay"])
    assert "chosen_body" not in clay.metadata
    assert _size(game, clay) == (1, 1)
    game.remove_from_battlefield(humility)
    assert _size(game, clay) == (0, 0)


@pytest.mark.cr("613.4b", "613.7a", "613.7b")
def test_humble_then_humility_is_one_one_and_humility_then_humble_is_zero_one(
    _by_name,
):
    """A resolved effect against a static ability, by when each began. The
    until-end-of-turn slot used to beat everything."""
    game = _new_game(_by_name)
    bears = _put(game, _by_name["Grizzly Bears"])
    assert _cast(game, _by_name, "Humble", bears)
    assert _size(game, bears) == (0, 1)
    _put(game, _by_name["Humility"])
    assert _size(game, bears) == (1, 1)

    game = _new_game(_by_name)
    bears = _put(game, _by_name["Grizzly Bears"])
    _put(game, _by_name["Humility"])
    assert _cast(game, _by_name, "Humble", bears)
    assert _size(game, bears) == (0, 1)


@pytest.mark.cr("613.4b", "613.7e")
def test_an_aura_that_animates_is_ordered_by_when_it_became_attached(_by_name):
    game = _new_game(_by_name)
    rod = _put(game, _by_name["Rod of Ruin"])
    assert _cast(game, _by_name, "Animate Artifact", rod)
    assert _size(game, rod) == (4, 4)
    _put(game, _by_name["Humility"])
    assert _size(game, rod) == (1, 1)

    game = _new_game(_by_name)
    rod = _put(game, _by_name["Rod of Ruin"])
    _put(game, _by_name["Humility"])
    assert _cast(game, _by_name, "Animate Artifact", rod)
    assert _size(game, rod) == (4, 4)


@pytest.mark.cr("613.4b", "613.6", "613.7a")
def test_humility_and_two_opalescences_in_each_order_the_ruling_gives(_by_name):
    """Opalescence, 2006-02-01 (quoted in the module docstring), with the
    older enchantments on the *other* seat — the two statics came out right
    among themselves only where the order the battlefields are walked in was
    the order the sources entered."""

    def sizes(order):
        game = _new_game(_by_name)
        placed = []
        for index, name in enumerate(order):
            # Oldest on seat 1, so that seat 0's are walked first.
            seat = 1 if index == 0 else 0
            placed.append(_put(game, _by_name[name], seat))
        game._recompute_continuous_effects()
        return [(_size(game, permanent), permanent.is_creature) for permanent in placed]

    # Humility last: every creature is 1/1.
    assert sizes(("Opalescence", "Opalescence", "Humility")) == [
        ((1, 1), True), ((1, 1), True), ((1, 1), True),
    ]
    # Opalescence, Humility, Opalescence: the second Opalescence is 1/1, the
    # Humility and the first Opalescence 4/4.
    assert sizes(("Opalescence", "Humility", "Opalescence")) == [
        ((4, 4), True), ((4, 4), True), ((1, 1), True),
    ]
    # Humility first: everything is 4/4.
    assert sizes(("Humility", "Opalescence", "Opalescence")) == [
        ((4, 4), True), ((4, 4), True), ((4, 4), True),
    ]


@pytest.mark.cr("613.4b", "613.7b")
def test_the_write_api_stamps_every_slot_it_writes():
    """The stamp is inside the write (``pt.set_base_pt``), so a handler that
    sets a size cannot forget it — and a later write is later."""
    from engine.pt import BASE_PT_TIMESTAMP_KEY, clear_base_pt, set_base_pt

    card = CardDefinition(
        name="Probe", mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={}, power="2", toughness="2",
    )
    permanent = Permanent(card=card)
    set_base_pt(permanent, 0, 2, until_eot=True)
    first = permanent.metadata[f"{BASE_PT_TIMESTAMP_KEY}_until_eot"]
    assert (permanent.effective_power, permanent.effective_toughness) == (0, 2)
    # A persistent set made afterwards is the newer effect and wins, where
    # the until-end-of-turn slot used to win by being that slot.
    set_base_pt(permanent, 5, 5)
    assert permanent.metadata[BASE_PT_TIMESTAMP_KEY] > first
    assert (permanent.effective_power, permanent.effective_toughness) == (5, 5)
    clear_base_pt(permanent)
    assert BASE_PT_TIMESTAMP_KEY not in permanent.metadata
    assert (permanent.effective_power, permanent.effective_toughness) == (0, 2)
    clear_base_pt(permanent, until_eot=True)
    assert f"{BASE_PT_TIMESTAMP_KEY}_until_eot" not in permanent.metadata
    assert (permanent.effective_power, permanent.effective_toughness) == (2, 2)


@pytest.mark.cr("613.7", "613.8a")
def test_set_effects_apply_in_timestamp_order_whatever_they_overwrite():
    """The layer engine itself, with no card in it. Two effects that set 4/4
    and a newer one that sets 1/1: the answer is 1/1.

    It was 4/4. Whether one effect depends on another (CR 613.8a) is probed by
    asking what each *does* in two states, and a number's action was compared
    as a ``(new value, delta)`` pair — so a set, whose delta moves with
    whatever it overwrites, looked dependent on every effect that changed the
    value. All three being mutually "dependent" is a loop, which falls back to
    timestamp order; but once the first 4/4 had applied the second changed
    nothing, the 1/1 no longer "depended" on it, and the 1/1 was applied
    ahead of an older effect. A set is the same action when it leaves the same
    value."""
    from engine.continuous import modify_pt, scope_only, set_pt

    def after(*effects, printed=(None, None)):
        state = {1: Characteristics(power=printed[0], toughness=printed[1])}
        apply_layers(list(effects), state)
        return (state[1].power, state[1].toughness)

    only = scope_only(1)
    four_old = set_pt(only, 4, 4, timestamp=1, label="older 4/4")
    four_new = set_pt(only, 4, 4, timestamp=2, label="newer 4/4")
    one = set_pt(only, 1, 1, timestamp=3, label="newest 1/1")
    for printed in ((None, None), (2, 2), (4, 4), (1, 1)):
        # In whatever order the collector happened to list them.
        assert after(four_old, four_new, one, printed=printed) == (1, 1), printed
        assert after(one, four_new, four_old, printed=printed) == (1, 1), printed
        assert after(four_new, one, four_old, printed=printed) == (1, 1), printed
    # …the 1/1 in the middle loses to the 4/4 after it and beats the one before.
    middle = set_pt(only, 1, 1, timestamp=2, label="middle 1/1")
    late = set_pt(only, 4, 4, timestamp=3, label="newest 4/4")
    assert after(four_old, middle, late) == (4, 4)
    assert after(late, middle, four_old) == (4, 4)
    # A stat an effect leaves alone keeps whoever set it last.
    power_only = set_pt(only, 7, None, timestamp=4, label="power only")
    assert after(four_old, one, power_only) == (7, 1)
    # …and 7c still applies over all of it, once, whichever came first.
    assert after(modify_pt(only, 1, 1, timestamp=0), four_old, one) == (2, 2)
