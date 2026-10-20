"""What ``Permanent.effective_card`` and the CR 613 accessors beside it cost a read.

Two simulated Mirage games read ``effective_card`` 4.5 million times and layer 4
780,000 times. Each ``effective_card`` read ran five function-level import
statements (31 million import resolutions in all, the largest single cost after
the reads themselves) and then folded a dozen metadata channels that, for 94% of
the reads, were all empty; each layer-4 read seeded a whole characteristics
state and collected effects from fifteen channels that were almost always empty
too. None of that is a rules question, and all of it is held here:

* **No accessor read runs an import statement.** The accessors read the modules
  that load after ``models`` through ``engine/late_modules.py``, and the
  modules that load before through ordinary top-level imports. Counted on a
  board that populates every channel, with ``builtins.__import__`` replaced —
  CPython calls a replaced ``__import__`` for every import statement, so the
  count is of statements executed, which is what cost the time.
* **The answer without the fold is the fold's answer.** ``effective_card``
  returns the printed card without folding when every channel
  ``models.fold_channels`` names is empty, and ``layer_bridge.computed_types`` /
  ``computed_supertypes`` answer from the printed line when every channel
  ``layer_bridge.TYPE_EFFECT_CHANNELS`` names is. That is exact only while each
  tuple names every key its fold reads, so each fold is run over a metadata
  dict that records every key read, and the checking mode
  (``engine/fast_paths.py``) compares every shortcut answer on the board with
  the full computation.
"""

from __future__ import annotations

import builtins
from collections import Counter
from types import SimpleNamespace

import pytest

from engine import Game, PlayerState, fast_paths, layer_bridge, models, target_immunity
from engine.auras import attach_aura
from engine.card_loader import load_catalog
from engine.copies import become_copy
from engine.global_statics import record_stack_statics
from engine.handlers.board_misc import _animation_record, _record_set_card_types
from engine.keywords import (grant_ability_line, remove_ability_keyword,
                             remove_ability_line, remove_all_abilities)
from engine.land_types import change_land_type
from engine.models import Permanent
from engine.stack_statics import stack_static_grants
from engine.text_changes import change_color_word
from engine.type_changes import gain_types, lose_types

ACCESSORS = {
    "effective_card": lambda permanent: permanent.effective_card,
    "card_before_layer_6": lambda permanent: permanent.card_before_layer_6,
    "card_through_layer_3": lambda permanent: permanent.card_through_layer_3,
    "has_type": lambda permanent: permanent.has_type("creature"),
    "is_creature": lambda permanent: permanent.is_creature,
    "has_supertype": lambda permanent: permanent.has_supertype("legendary"),
    "effective_supertypes": lambda permanent: permanent.effective_supertypes,
    "basic_land_types": lambda permanent: permanent.basic_land_types,
    "effective_colors": lambda permanent: permanent.effective_colors,
    "has_keyword": lambda permanent: permanent.has_keyword("flying"),
    "effective_power": lambda permanent: permanent.effective_power,
    "effective_toughness": lambda permanent: permanent.effective_toughness,
}

#: Cards whose presence populates a channel the way play does: an Aura with a
#: quoted grant and one with a line-derived keyword (``attached_auras``), a
#: static granting an ability (``global_static_sources``), a lord granting a
#: quoted line (the derived-line channel), a type-setting static (the derived
#: land-type channel), an Aura setting a land's type (the recorded one), a
#: creature with the text of its graveyard's top card (the derived copy), a
#: land animator, a supertype remover, an "as this enters" body, and a
#: board-wide "can't be the targets of" clause for the target checks.
SOURCES = (
    "Hermetic Study", "Agility", "Energy Flux", "Clot Sliver",
    "Blood Moon", "Evil Presence", "Volrath's Shapeshifter", "Living Lands",
    "Melting", "Primal Clay", "Dense Foliage",
)
PANEL = (
    "Grizzly Bears", "Ornithopter", "Sol Ring", "City of Brass", "Tundra",
    "Forest", "Clot Sliver", "Snow-Covered Forest", "Opal Acrolith",
)


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _board(by_name):
    """A board on which every channel of both folds holds something somewhere,
    beside permanents on which none does."""
    game = Game(players=[
        PlayerState(
            name=f"P{seat}", library=[by_name["Island"]] * 12,
            graveyard=[by_name["Grizzly Bears"]],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    panel = {name: _put(game, by_name[name], seat=1) for name in PANEL}
    for name in SOURCES:
        source = _put(game, by_name[name])
        if name == "Evil Presence":
            attach_aura(source, panel["City of Brass"])
            change_land_type(panel["City of Brass"], "swamp", source=source)
        elif "Aura" in source.card.type_line:
            attach_aura(source, panel["Grizzly Bears"])
    # The channels no card on this board fills, through the write API each
    # one's own effect uses.
    clone = _put(game, by_name["Grizzly Bears"], seat=1)
    become_copy(clone, panel["Ornithopter"], label="test copy")
    change_color_word(panel["Clot Sliver"], "B", "W", label="test text change")
    grant_ability_line(clone, "{T}: Draw a card.", duration="end_of_turn")
    remove_ability_line(panel["Tundra"], "({T}: Add {W} or {U}.)")
    remove_ability_keyword(panel["Grizzly Bears"], "flanking", duration="end_of_turn")
    remove_all_abilities(panel["Sol Ring"], duration="end_of_turn")
    gain_types(clone, card_types=("enchantment",), source="test")
    lose_types(panel["Tundra"], supertypes=("basic",), source="test")
    for host, record in (
        ("Ornithopter", "animate_until_end_of_turn"),
        ("Sol Ring", "animate_indefinitely"),
        ("Tundra", "animate_until_end_of_combat"),
    ):
        panel[host].metadata[record] = _animation_record(
            {"subtypes": ["golem"], "card_types": ["artifact"]}
        )
    _record_set_card_types(
        game, panel["Opal Acrolith"],
        SimpleNamespace(payload={"card_types": ["enchantment"]}),
        SimpleNamespace(card=None),
    )
    game._recompute_continuous_effects()
    # …and a spell on the stack granting an ability (CR 113.6b), recorded after
    # the recompute, which would otherwise clear it: there is no spell.
    torrent = by_name["Torrent of Lava"]
    record_stack_statics(panel["Forest"], [
        (static, 0) for static in stack_static_grants(torrent.oracle_text, torrent.name)
    ])
    return game


def _unfilled(game, channels) -> set[str]:
    return set(channels) - {
        key for permanent in game.all_permanents()
        for key in channels if permanent.metadata.get(key)
    }


def _untouched(permanents, channels) -> list:
    return [
        permanent for permanent in permanents
        if not any(permanent.metadata.get(key) for key in channels)
    ]


def test_the_board_fills_every_channel_either_fold_reads(by_name):
    """The floor under everything below: a census over a board where a
    channel is empty everywhere would pass while proving nothing about it."""
    game = _board(by_name)
    assert not _unfilled(game, models.fold_channels())
    assert not _unfilled(game, layer_bridge.TYPE_EFFECT_CHANNELS)
    permanents = list(game.all_permanents())
    assert len(_untouched(permanents, models.fold_channels())) >= 3
    assert len(_untouched(permanents, layer_bridge.TYPE_EFFECT_CHANNELS)) >= 3


class _RecordingDict(dict):
    """A metadata dict that remembers every key read off it."""

    def __init__(self, *args):
        super().__init__(*args)
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


NAMES = ["Grizzly Bears", "Hermetic Study", "City of Brass", "Sol Ring", "Snow-Covered Forest"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("present", [False, True], ids=["absent", "present-but-empty"])
def test_the_fold_reads_no_key_the_shortcut_does_not_name(by_name, name, present):
    """Run ``effective_card``'s fold over a permanent whose every channel is
    empty, recording each metadata key it reads. It must read nothing outside
    ``fold_channels()`` and must come back with the printed card — together,
    exactly the claim the shortcut makes. A channel added to the fold and not
    to the tuple fails here, before any permanent is misread."""
    card = by_name[name]
    channels = models.fold_channels()
    metadata = _RecordingDict({key: [] for key in channels} if present else {})
    permanent = Permanent(card=card, metadata=metadata)
    assert permanent._folded_card() is card
    assert metadata.read, "the fold read nothing at all: the recorder is not wired"
    assert metadata.read <= set(channels), sorted(metadata.read - set(channels))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("present", [False, True], ids=["absent", "present-but-empty"])
def test_layer_4_reads_no_key_its_shortcut_does_not_name(by_name, name, present):
    """The same, for layer 4: both collectors over a permanent whose every
    layer-4 channel is empty find no effect, and read nothing outside
    ``TYPE_EFFECT_CHANNELS`` to find it. The full computation then agrees with
    the shortcut's answer."""
    card = by_name[name]
    channels = layer_bridge.TYPE_EFFECT_CHANNELS
    metadata = _RecordingDict({key: [] for key in channels} if present else {})
    permanent = Permanent(card=card, metadata=metadata)
    assert layer_bridge.collect_type_effects(permanent, id(permanent)) == []
    assert metadata.read, "the collectors read nothing: the recorder is not wired"
    assert metadata.read <= set(channels), sorted(metadata.read - set(channels))
    assert layer_bridge._computed_types_in_full(permanent) == layer_bridge.computed_types(permanent)
    assert (
        layer_bridge._computed_supertypes_in_full(permanent)
        == layer_bridge.computed_supertypes(permanent)
    )


def test_every_shortcut_answer_on_the_board_is_the_full_one(by_name, monkeypatch):
    """The checking mode over the board: every read a shortcut answers is
    computed the long way as well and compared, through every accessor that
    reaches one."""
    permanents = list(_board(by_name).all_permanents())
    unfolded = _untouched(permanents, models.fold_channels())
    untyped = _untouched(permanents, layer_bridge.TYPE_EFFECT_CHANNELS)
    monkeypatch.setattr(fast_paths, "CHECKING", True)
    monkeypatch.setattr(fast_paths, "CHECKED", {})
    for permanent in permanents:
        for read in ACCESSORS.values():
            read(permanent)
    assert len(permanents) >= len(PANEL) + len(SOURCES)
    # Every accessor but ``card_through_layer_3`` (layers 1 and 3, and no
    # further) reaches ``effective_card``; the five layer-4 accessors reach
    # ``computed_types`` or ``computed_supertypes``.
    assert fast_paths.CHECKED["effective_card"] >= len(unfolded) * (len(ACCESSORS) - 1)
    assert (
        fast_paths.CHECKED["computed_types"] + fast_paths.CHECKED["computed_supertypes"]
        >= len(untyped) * 5
    )
    # The line an Aura's line-derived keyword grant turns into is kept per text
    # (Agility's flanking, on the enchanted Bears, which the board then strikes
    # off them again), and every kept answer was read again here.
    assert fast_paths.CHECKED["aura_granted_line_derived_lines"] >= len(ACCESSORS) - 1
    from engine.auras import aura_granted_line_derived_lines

    assert aura_granted_line_derived_lines(by_name["Agility"].oracle_text) == ("Flanking",)

    # The lines a target check reads every permanent's text as, kept per
    # text and name: every creature on the board is untargetable by spells
    # (Dense Foliage), and every kept reading was read again.
    game = _board(by_name)
    for permanent in game.all_permanents():
        classes = target_immunity.board_target_immunity_classes(game, permanent)
        assert bool(classes) == permanent.is_creature, permanent.card.name
    assert fast_paths.CHECKED["target_immunity._lines_of"] >= len(permanents) ** 2


def test_the_checking_mode_names_a_channel_left_out(by_name, monkeypatch):
    """Validated backwards: with ``attached_auras`` dropped from the tuple, an
    enchanted creature reads as its printed card and loses Hermetic Study's
    ability — the silent failure the tuple invites — and the checking mode
    raises on the very read that made it."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    bears = _put(game, by_name["Grizzly Bears"])
    attach_aura(_put(game, by_name["Hermetic Study"]), bears)
    game._recompute_continuous_effects()
    assert [key for key in models.fold_channels() if bears.metadata.get(key)] == [
        "attached_auras"
    ]
    granted = "This creature deals 1 damage to any target"
    assert granted.lower() in bears.effective_card.oracle_text.lower()

    reduced = tuple(key for key in models.fold_channels() if key != "attached_auras")
    monkeypatch.setattr(models, "fold_channels", lambda: reduced)
    assert bears.effective_card is bears.card
    monkeypatch.setattr(fast_paths, "CHECKING", True)
    with pytest.raises(RuntimeError, match="fold_channels"):
        bears.effective_card


def test_the_checking_mode_names_a_layer_4_channel_left_out(by_name, monkeypatch):
    """The same for layer 4: with the land-animation record dropped from the
    tuple, a Forest under Living Lands reads as no creature, and the checking
    mode raises on that read."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    forest = _put(game, by_name["Forest"])
    _put(game, by_name["Living Lands"])
    game._recompute_continuous_effects()
    assert [
        key for key in layer_bridge.TYPE_EFFECT_CHANNELS if forest.metadata.get(key)
    ] == ["land_animated"]
    assert forest.is_creature

    reduced = tuple(
        key for key in layer_bridge.TYPE_EFFECT_CHANNELS if key != "land_animated"
    )
    monkeypatch.setattr(layer_bridge, "TYPE_EFFECT_CHANNELS", reduced)
    assert not forest.is_creature
    monkeypatch.setattr(fast_paths, "CHECKING", True)
    with pytest.raises(RuntimeError, match="computed_types"):
        forest.is_creature


def test_no_accessor_read_runs_an_import_statement(by_name):
    """Every accessor, read twice over the whole board: the first pass is
    allowed to fill a memo (a compile, a cached text reading), the second is
    the steady state a game lives in, and runs no import statement at all.

    On the tree before this test, those 252 reads (21 permanents, twelve
    accessors) ran 3,513 import statements.
    """
    permanents = list(_board(by_name).all_permanents())
    for permanent in permanents:
        for read in ACCESSORS.values():
            read(permanent)

    imports: Counter = Counter()
    real_import = builtins.__import__
    current = [""]

    def counting_import(name, globals=None, locals=None, fromlist=(), level=0):
        imports[(current[0], (globals or {}).get("__name__"), name)] += 1
        return real_import(name, globals, locals, fromlist, level)

    reads: Counter = Counter()
    # Swapped by hand rather than through ``monkeypatch``, whose own restore
    # imports a module and would be counted.
    builtins.__import__ = counting_import
    try:
        for permanent in permanents:
            for label, read in ACCESSORS.items():
                current[0] = label
                read(permanent)
                reads[label] += 1
    finally:
        builtins.__import__ = real_import

    assert len(permanents) >= len(PANEL) + len(SOURCES)
    assert set(reads.values()) == {len(permanents)}, reads
    assert not imports, "\n".join(
        f"{count:>4}  {label}: {importer} imports {name}"
        for (label, importer, name), count in imports.most_common()
    )
