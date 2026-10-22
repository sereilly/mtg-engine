"""CR 613.1f over CR 613.7: "loses all abilities" is ordered by timestamp.

An effect that takes every ability from a permanent is a layer-6 effect like
any grant, and layer 6 is applied in timestamp order. So it takes what the
permanent has **when it applies** — the printed abilities and every ability an
older effect granted — and an ability a *newer* effect grants is applied after
it and stays.

The engine had the loss and no order. ``Permanent.effective_card`` struck the
printed text and then appended every granted line of any age; layer 6 removed
the printed keywords at timestamp 0 and so reached no grant at all; the
protection reader asked nothing. A creature given flying and then Humbled
still flew, an Aura attached before a Humility went on granting, and Energy
Flux's upkeep sacrifice survived a Titania's Song that arrived after it. The
activation door erred the other way: it refused every ability of a permanent a
board-wide static had stripped, the ones granted afterwards included.

**The census.** Four cards in the pool take all abilities (Humility, Titania's
Song, Humble, Soul Sculptor). Against each, every pool card that grants the
subject an ability — found by *doing it*: the card is cast, or its ability
activated, at the subject, and what the subject gained is the difference in
its keyword set, its protection and its effective text — in both orders:

* grant, then the loss: nothing the grant gave may remain;
* the loss, then the grant: everything it gave must be there, and a granted
  activated ability must be on the list and through the door.

Measured over the whole pool (604 pairs) on the tree before the fix: 537
grants outlived a later loss, 2 later grants lost their keyword word (Rapid
Fire's rampage, Jabari's Banner's flanking) and 10 later-granted activated
abilities were refused at the door. The committed run samples the granters —
the full walk is a minute — and pins one card per channel so the sample can
never miss a way an ability is granted.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import auras_attached_to
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.global_statics import global_statics_applying_to
from engine.keywords import (ability_effects, derived_ability_lines,
                             derived_grants, granted_ability_lines)
from engine.layer_bridge import computed_abilities
from engine.models import CardDefinition, Permanent, _abilities_stripped
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

#: Each effect that takes all abilities: how it is applied, and the subject it
#: is aimed at — one that prints an ability of its own, so the loss is visible.
REMOVERS = {
    "Humility": ("permanent", "Prodigal Sorcerer"),
    "Titania's Song": ("permanent", "Rod of Ruin"),
    "Humble": ("spell", "Prodigal Sorcerer"),
    "Soul Sculptor": ("ability", "Prodigal Sorcerer"),
}

#: One granter per channel an ability arrives on, always examined: a spell's
#: keyword (``grant_keyword``), an Aura's keyword, an Aura's quoted ability
#: (triggered, and activated — the door's case), a board-wide static's quoted
#: ability, a noncreature lord's keyword, a line-derived keyword granted by a
#: spell and by an ability, an Aura's protection, an ability's protection.
PINNED = (
    "Jump", "Fishliver Oil", "Pendrell Flux", "Hermetic Study", "Energy Flux",
    "Fervor", "Rapid Fire", "Jabari's Banner", "Black Ward", "Mother of Runes",
)

#: Every STRIDE-th granter beside the pinned ones.
STRIDE = 6

_GRANT_WORDS = re.compile(r"\b(has|have|gains?)\b", re.I)


@pytest.fixture(scope="module")
def _by_name():
    """Every card by name — and each half of a split card by its own, which is
    the name it is cast by (CR 709.3a) and the text that compiles."""
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


def _put(game, by_name, name, seat=0):
    permanent = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._recompute_continuous_effects()
    return permanent


def _fingerprint(game, permanent):
    """Everything *permanent* has that an effect could have given it: its
    keyword set, what it has protection from, and its effective text."""
    game._recompute_continuous_effects()
    lines = tuple(
        # A quoted grant names its granter by id ("…the permanent with id 7
        # that granted this ability"), and each arm is a fresh game.
        re.sub(r"\bid \d+", "id N", line)
        for line in (permanent.effective_card.oracle_text or "").split("\n")
        if line
    )
    words = set(computed_abilities(permanent))
    words |= {
        f"protection:{kind}:{value}"
        for kind, value in game._protection_qualities(permanent)
    }
    return frozenset(words), lines


def _records(permanent):
    """What is recorded on *permanent* as granted, channel by channel — the
    witness that a grant made after the loss *landed* at all (a creature Aura
    cannot be cast on what Soul Sculptor made an enchantment)."""
    return (
        sum(1 for entry in ability_effects(permanent) if entry["grant"]),
        tuple(
            id(aura) for aura in auras_attached_to(permanent)
            if not _abilities_stripped(aura)
        ),
        derived_grants(permanent),
        derived_ability_lines(permanent),
        granted_ability_lines(permanent),
        tuple(
            static.grants_ability
            for static in global_statics_applying_to(permanent)
            if static.grants_ability
        ),
        tuple(sorted(
            key for key in permanent.metadata if key.startswith("protection_from_")
        )),
    )


def _cast(game, by_name, name, target=None) -> bool:
    # The whole card is what a hand holds; a half is cast out of it by name.
    card = whole_card(by_name[name])
    game.players[0].hand.append(card)
    kwargs = {}
    if target is not None:
        kwargs["target_permanent_ids"] = [target.permanent_id]
    result = game.cast_from_hand(0, name, **kwargs)
    if not result.supported:
        game.take_card_from_hand(game.players[0], card)
        return False
    resolve_stack(game)
    game._recompute_continuous_effects()
    return True


def _activate(game, permanent, target, ability_index=0) -> bool:
    result = game.queue_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=ability_index,
        target_permanent_ids=[target.permanent_id],
    )
    if not result.supported:
        return False
    resolve_stack(game)
    game._recompute_continuous_effects()
    return True


def _apply_remover(game, by_name, name, subject) -> bool:
    how, _subject = REMOVERS[name]
    if how == "permanent":
        return _cast(game, by_name, name)
    if how == "spell":
        return _cast(game, by_name, name, subject)
    return _activate(game, _put(game, by_name, name), subject)


def _is_spell(card) -> bool:
    types = card.type_line.lower()
    return "instant" in types or "sorcery" in types


def _apply_grant(game, by_name, card, subject, how) -> bool:
    if how[0] == "cast":
        aimed = _is_spell(card) or "aura" in card.type_line.lower()
        return _cast(game, by_name, card.name, subject if aimed else None)
    return _activate(game, _put(game, by_name, card.name), subject, how[1])


def _ways(card):
    """Every way *card* could grant something: cast it, or activate each of
    its abilities at the subject."""
    found = [("cast",)]
    if not _is_spell(card):
        usable = usable_activated_abilities(compile_card_oracle(card))
        found.extend(("activate", index) for index in range(len(usable)))
    return found


def _granters(by_name, names=None):
    if names is not None:
        return [by_name[name] for name in names]
    found = sorted(
        (
            card for card in compilation_units(by_name.values())
            if _GRANT_WORDS.search(card.oracle_text or "")
            and card.name not in REMOVERS
            and compile_card_oracle(card).supported
        ),
        key=lambda card: card.name,
    )
    sampled = {card.name for card in found[::STRIDE]} | set(PINNED)
    return [card for card in found if card.name in sampled]


def _grants_an_activated_ability(lines) -> bool:
    if not lines:
        return False
    probe = CardDefinition(
        name="Granted", mana_cost="", cmc=0.0, type_line="Creature",
        oracle_text="\n".join(lines), colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={},
    )
    return bool(usable_activated_abilities(compile_card_oracle(probe)))


def _census(by_name, names=None):
    counts: Counter = Counter()
    kept, taken, door, printed = [], [], [], []
    for remover, (_how, subject_name) in REMOVERS.items():
        for card in _granters(by_name, names):
            for how in _ways(card):
                # What the grant gives the subject, with nothing else going on.
                game = _new_game(by_name)
                subject = _put(game, by_name, subject_name)
                before = _fingerprint(game, subject)
                if not _apply_grant(game, by_name, card, subject, how):
                    continue
                if not game.is_on_battlefield(subject):
                    continue
                after = _fingerprint(game, subject)
                words = after[0] - before[0]
                lines = tuple(line for line in after[1] if line not in before[1])
                if not words and not lines:
                    continue
                counts["pairs"] += 1
                row = (remover, card.name, how)

                # The grant, then the loss: the grant is older and goes.
                game = _new_game(by_name)
                subject = _put(game, by_name, subject_name)
                if (
                    _apply_grant(game, by_name, card, subject, how)
                    and _apply_remover(game, by_name, remover, subject)
                    and game.is_on_battlefield(subject)
                    and _abilities_stripped(subject)
                ):
                    now = _fingerprint(game, subject)
                    counts["grant_first"] += 1
                    survived = (words & now[0]) | {l for l in lines if l in now[1]}
                    if survived:
                        kept.append((*row, sorted(survived)))
                    if any(line in now[1] for line in before[1]):
                        printed.append((*row, "grant first"))
                    if game.usable_abilities_of(subject):
                        door.append((*row, "an ability is still listed"))

                # The loss, then the grant: the grant is newer and stays.
                game = _new_game(by_name)
                subject = _put(game, by_name, subject_name)
                if not (
                    _apply_remover(game, by_name, remover, subject)
                    and game.is_on_battlefield(subject)
                    and _abilities_stripped(subject)
                ):
                    continue
                recorded = _records(subject)
                if not (
                    _apply_grant(game, by_name, card, subject, how)
                    and game.is_on_battlefield(subject)
                    and _abilities_stripped(subject)
                    and _records(subject) != recorded
                ):
                    continue
                now = _fingerprint(game, subject)
                counts["loss_first"] += 1
                missing = (words - now[0]) | {l for l in lines if l not in now[1]}
                if missing:
                    taken.append((*row, sorted(missing)))
                if any(line in now[1] for line in before[1]):
                    printed.append((*row, "loss first"))
                if _grants_an_activated_ability(lines):
                    counts["door"] += 1
                    if (
                        not game.usable_abilities_of(subject)
                        or game.lost_abilities_refusal(subject) is not None
                    ):
                        door.append((*row, "the granted ability is refused"))
    return counts, kept, taken, door, printed


@pytest.mark.cr("613.1f", "613.7a", "613.7b", "613.7e")
def test_every_grant_is_ordered_against_every_loss_of_all_abilities(_by_name):
    counts, kept, taken, door, printed = _census(_by_name)

    # Floors: a sweep that reaches nothing passes. Measured 129 / 121 / 79 / 9
    # on the pool this was written against, and 107 / 99 / 65 / 6 once
    # Apocalypse and Odyssey moved which granters the stride samples.
    assert counts["pairs"] >= 95, counts
    assert counts["grant_first"] >= 88, counts
    assert counts["loss_first"] >= 58, counts
    assert counts["door"] >= 5, counts
    assert kept == [], f"an older grant outlived the loss: {kept[:20]}"
    assert taken == [], f"a newer grant was taken by the loss: {taken[:20]}"
    assert door == [], f"the door and the lists disagree: {door[:20]}"
    assert printed == [], f"a printed ability survived the loss: {printed[:20]}"


@pytest.mark.cr("613.7")
def test_the_census_names_a_loss_that_has_no_place_in_the_order(_by_name, monkeypatch):
    """Backwards: put the loss before everything, which is what it was — a
    strike of the printed text with every granted ability appended after it.
    The census then names each channel's pinned card as outliving the loss."""
    import engine.keywords
    import engine.layer_bridge
    import engine.mixins.protection

    real = engine.keywords.abilities_lost_at

    def unordered(permanent, **known):
        # `known` is what a caller already derived (`board_statics`, from
        # `Permanent._folded_card`), passed through so the stub answers the
        # same question the real function was asked.
        return None if real(permanent, **known) is None else -1

    for module in (
        engine.keywords, engine.layer_bridge, engine.mixins.protection
    ):
        monkeypatch.setattr(module, "abilities_lost_at", unordered)

    _counts, kept, _taken, _door, _printed = _census(_by_name, PINNED)

    outlived = {(remover, name) for remover, name, _how, _what in kept}
    for name in ("Jump", "Fishliver Oil", "Pendrell Flux", "Fervor", "Black Ward",
                 "Rapid Fire", "Mother of Runes"):
        assert ("Humility", name) in outlived, (name, sorted(outlived))
        # (Humble is white, and what the Mother gives by default is protection
        # from white: the spell cannot be aimed at all.)
        if name != "Mother of Runes":
            assert ("Humble", name) in outlived, (name, sorted(outlived))
    assert ("Titania's Song", "Energy Flux") in outlived


# --- the cards, one board each -------------------------------------------


@pytest.mark.cr("613.1f", "613.7b")
def test_jump_then_humble_does_not_fly_and_humble_then_jump_does(_by_name):
    """Two resolved spells, ordered by when each resolved (CR 613.7b)."""
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Jump", bears)
    assert game._has_keyword(bears, "flying")
    assert _cast(game, _by_name, "Humble", bears)
    assert not game._has_keyword(bears, "flying")
    assert (bears.effective_power, bears.effective_toughness) == (0, 1)

    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Humble", bears)
    assert _cast(game, _by_name, "Jump", bears)
    assert game._has_keyword(bears, "flying")
    assert (bears.effective_power, bears.effective_toughness) == (0, 1)


@pytest.mark.cr("613.1f", "613.7a", "613.7e")
def test_an_aura_older_than_humility_grants_nothing_and_a_newer_one_does(_by_name):
    """A static ability's effect has its object's timestamp, and an Aura's is
    the moment it became attached."""
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Fishliver Oil", bears)
    assert game._has_keyword(bears, "islandwalk")
    assert _cast(game, _by_name, "Humility")
    assert not game._has_keyword(bears, "islandwalk")
    # …and the Aura is still attached: nothing was undone, only ordered.
    assert [aura.card.name for aura in auras_attached_to(bears)] == ["Fishliver Oil"]

    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Humility")
    assert _cast(game, _by_name, "Fishliver Oil", bears)
    assert game._has_keyword(bears, "islandwalk")

    # The Humility leaving gives the older Aura's grant back (CR 611.3b).
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Fishliver Oil", bears)
    assert _cast(game, _by_name, "Humility")
    humility = next(p for p in game.all_permanents() if p.card.name == "Humility")
    game.remove_from_battlefield(humility)
    game._recompute_continuous_effects()
    assert game._has_keyword(bears, "islandwalk")


@pytest.mark.cr("613.1f", "613.7e")
def test_an_ability_granted_after_humility_can_be_activated(_by_name):
    """The door: Hermetic Study on a creature under Humility. The Study is
    newer, so its "{T}: This creature deals 1 damage to any target" is the
    creature's — on the list, through the door, and it deals the damage. The
    creature's own ability is not there to be named."""
    game = _new_game(_by_name)
    sorcerer = _put(game, _by_name, "Prodigal Sorcerer")
    assert _cast(game, _by_name, "Humility")
    assert game.usable_abilities_of(sorcerer) == []
    assert "has lost all abilities" in game.lost_abilities_refusal(sorcerer)

    assert _cast(game, _by_name, "Hermetic Study", sorcerer)
    assert len(game.usable_abilities_of(sorcerer)) == 1
    assert game.lost_abilities_refusal(sorcerer) is None
    # Index 1 would be the Sorcerer's own, by a caller counting the printed
    # card plus the grant: refused by name, not answered as something else.
    assert "has lost all abilities" in game.lost_abilities_refusal(sorcerer, 1)

    life = game.players[1].life
    result = game.queue_permanent_ability(
        0, sorcerer.card.name,
        permanent_index=game.battlefield_index_of(sorcerer),
        ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert game.players[1].life == life - 1
    assert sorcerer.tapped

    # The other order: the Study was there first, and Humility takes it.
    game = _new_game(_by_name)
    sorcerer = _put(game, _by_name, "Prodigal Sorcerer")
    assert _cast(game, _by_name, "Hermetic Study", sorcerer)
    assert _cast(game, _by_name, "Humility")
    assert game.usable_abilities_of(sorcerer) == []
    life = game.players[1].life
    result = game.queue_permanent_ability(
        0, sorcerer.card.name,
        permanent_index=game.battlefield_index_of(sorcerer),
        ability_index=0, target_player_index=1,
    )
    assert not result.supported
    assert "has lost all abilities" in result.details
    assert game.players[1].life == life and not sorcerer.tapped


@pytest.mark.cr("613.1f", "613.7a")
def test_energy_flux_and_titanias_song_in_both_orders(_by_name):
    """Two enchantments, ordered by when each entered. Energy Flux first: the
    Song takes the upkeep sacrifice with the Rod's own ability. The Song
    first: the Rod is a 4/4 with one ability, the Flux's."""
    from engine.trigger_utils import iter_triggered_abilities

    def upkeep_abilities(game):
        return list(iter_triggered_abilities(game, condition_kinds={"upkeep_self"}))

    game = _new_game(_by_name)
    rod = _put(game, _by_name, "Rod of Ruin")
    assert _cast(game, _by_name, "Energy Flux")
    assert len(upkeep_abilities(game)) == 1
    assert _cast(game, _by_name, "Titania's Song")
    assert rod.is_creature and (rod.effective_power, rod.effective_toughness) == (4, 4)
    assert rod.effective_card.oracle_text == ""
    assert upkeep_abilities(game) == []

    game = _new_game(_by_name)
    rod = _put(game, _by_name, "Rod of Ruin")
    assert _cast(game, _by_name, "Titania's Song")
    assert _cast(game, _by_name, "Energy Flux")
    assert rod.is_creature
    assert "sacrifice this artifact unless you pay {2}" in rod.effective_card.oracle_text
    assert "deals 1 damage" not in rod.effective_card.oracle_text
    assert len(upkeep_abilities(game)) == 1


@pytest.mark.cr("613.1f", "305.6")
def test_an_animated_land_under_humility_does_not_tap_for_mana(_by_name):
    """The mana ability a basic land type gives is an ability, and Humility
    takes it. The card's ruling of 2007-02-01: "Removes all creature
    abilities. This includes mana abilities. Animated lands will also lose
    the ability to tap for mana." The tap seam's summary path asked nothing,
    so a Forest that Living Lands had made a creature went on tapping."""
    from engine.board_payment import board_can_pay
    from engine.mana_payment import taps_for_payment, untapped_mana_lands

    game = _new_game(_by_name)
    _put(game, _by_name, "Living Lands")
    forest = _put(game, _by_name, "Forest")
    island = _put(game, _by_name, "Island")
    game.enforce_mana_costs = True
    assert forest.is_creature and not island.is_creature
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert game.players[0].mana_pool.get("G", 0) == 1

    game = _new_game(_by_name)
    _put(game, _by_name, "Living Lands")
    forest = _put(game, _by_name, "Forest")
    island = _put(game, _by_name, "Island")
    _put(game, _by_name, "Humility")
    game.enforce_mana_costs = True
    assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert game.land_mana_tap_refusal(forest) == "no_mana_ability"
    assert not taps_for_payment(forest)
    assert not game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert game.players[0].mana_pool.get("G", 0) == 0 and not forest.tapped
    # The Island is no creature, and Humility says nothing of it.
    assert [p.card.name for p in untapped_mana_lands(game.controlled_by(0))] == ["Island"]
    assert board_can_pay(game, 0, {"U": 1}) and not board_can_pay(game, 0, {"G": 1})
    assert game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)


@pytest.mark.cr("613.1f", "613.7e")
def test_a_ward_older_than_humility_protects_nothing(_by_name):
    """Protection is an ability like any other, on a reader of its own."""
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Black Ward", bears)
    assert ("color", "B") in game._protection_qualities(bears)
    assert _cast(game, _by_name, "Humility")
    assert game._protection_qualities(bears) == set()
    # …so a black spell may be aimed at it again (CR 702.16b).
    assert _cast(game, _by_name, "Terror", bears) is False or not game.is_on_battlefield(bears)

    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _cast(game, _by_name, "Humility")
    assert _cast(game, _by_name, "Black Ward", bears)
    assert ("color", "B") in game._protection_qualities(bears)
    assert not _cast(game, _by_name, "Terror", bears)
    assert game.is_on_battlefield(bears)
