"""A spell cast **out of a graveyard** that targets a card **in a graveyard**.

CR 601.2a: to cast a spell "the player announces that they are casting the
spell. That card … moves from where it is to the stack." CR 601.2c chooses its
targets two steps later. So a card being cast from a graveyard is not a card
in that graveyard by the time anything is chosen — and the slot a target is
named by is a slot in the pile the caster was *looking at*, with the spell
still in it.

Flashback (CR 702.34) is what made this an everyday cast rather than a corner
of Yawgmoth's Will, and driving Odyssey's flashback cards found both halves
wrong in the shipped engine:

* **the slot** — the announced index was read after the spell had left the
  pile, so every slot above the spell's own named the next card up: Morgue
  Theft flashed back from under two creature cards returned the other one,
  and a slot past the shortened end named nothing and fell back to the first
  legal card. Raise Dead under Yawgmoth's Will did the same from the day both
  were in the pool;
* **the spell itself** — offered by its own picker and accepted by every gate:
  Coffin Purge alone in a graveyard was announced at itself, paid for and
  resolved having exiled nothing, and Regrowth under Yawgmoth's Will could be
  aimed at the Regrowth being cast.

The census below casts every card in the pool whose announcement names a
graveyard card out of a graveyard, at a slot above its own, and reads the
target back off the stack object. The two tests under it are the census
validated backwards: with each fix switched off, it names the cards.

Also here, because it arrived with the same card family: the graveyard exile
sweep's "**target player** … from their graveyard" form (Tombfire, Mudhole).
"""
from __future__ import annotations

from functools import lru_cache

import pytest

import engine.legality_cast_spec as legality_cast_spec
import engine.legality_enumeration as legality_enumeration
from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import grant_permission
from engine.mixins.stack.casting import SpellCastingMixin
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle
from engine.targeting import (CAST_FROM_GRAVEYARD, GRAVEYARD_TARGET_KIND,
                              derive_cast_spec)


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


@lru_cache(maxsize=None)
def _bait() -> tuple:
    """One card of every kind a graveyard-target phrase in the pool narrows
    by: each card type, a basic land, an Aura, a blue creature, a Mercenary."""
    by_name = _pool()
    mercenary = next(
        card for card in by_name.values()
        if "Mercenary" in card.type_line and card.primary_type == "creature"
    )
    return tuple(by_name[name] for name in (
        "Grizzly Bears", "Sol Ring", "Lightning Bolt", "Mind Rot", "Forest",
        "Crusade", "Holy Strength", "Prodigal Sorcerer",
    )) + (mercenary,)


def _population() -> list[tuple]:
    """``(card as held, face cast, mode index)`` for every castable card in
    the pool whose announcement names a card in a graveyard — a spell, one
    mode of a modal spell, or a permanent whose entry trigger's target is
    named as it is cast."""
    found = []
    for card in _pool().values():
        for face in (faces.face_cards(card) or [card]):
            if face.primary_type == "land":
                continue
            program = compile_card_oracle(face)
            if not program.supported:
                continue
            for mode in (range(len(program.modes)) if program.modes else (None,)):
                spec = derive_cast_spec(face, program, mode_index=mode)
                if spec is not None and spec.get("kind") == GRAVEYARD_TARGET_KIND:
                    found.append((card, face, mode))
    return found


def _board(held) -> tuple[Game, int]:
    """Seat 0's graveyard is bait, the card, bait — so there is something
    legal on either side of it — under a grant opening that graveyard.
    Returns the game and the slot the card sits in."""
    bait = list(_bait())
    game = Game(players=[
        PlayerState(name="P1", graveyard=bait + [held] + bait),
        PlayerState(name="P2", graveyard=list(bait)),
    ])
    game.enforce_mana_costs = False
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    return game, len(bait)


def _announcements(spec: dict, offered: list[dict]) -> list[dict]:
    """Ways to name *offered* (slots of one pile) for *spec*: one slot, then
    as many as a counted phrase prints, with the X that many needs."""
    seat = offered[0]["seat"]
    slots = [entry["index"] for entry in offered]
    several = spec.get("count") or spec.get("max_targets")
    tries = [{"target_player_index": seat, "target_permanent_index": slots[0]}]
    for size in dict.fromkeys(
        n for n in (several, 2, 3) if isinstance(n, int) and 1 < n <= len(slots)
    ):
        tries.append({
            "target_player_index": seat,
            "target_permanent_index": slots[:size], "x_value": size,
        })
    tries.append({
        "target_player_index": seat, "target_permanent_index": slots[:1], "x_value": 1,
    })
    return tries


class _Census:
    def __init__(self) -> None:
        self.read_back = 0            # announced a slot above the spell; stamp named that card
        self.unannounced: list[str] = []
        self.offered_itself: list[str] = []
        self.wrong: list[str] = []

    def run(self, only=None) -> "_Census":
        for held, face, mode in _population():
            if only is not None and face.name not in only:
                continue
            label = face.name if mode is None else f"{face.name}#{mode}"
            game, slot = _board(held)
            spec = game.cast_target_spec(0, face, from_zone="graveyard", mode_index=mode)
            offered = [t for t in spec.get("valid_targets") or [] if t.get("kind") == "graveyard"]
            if any(t["seat"] == 0 and t["index"] == slot for t in offered):
                self.offered_itself.append(label)
            # The slots this test is about: in the pile the spell is leaving,
            # above it. Whatever the phrase reads in the other pile is not
            # moved by the cast and is left to the stack-targets census.
            above = [t for t in offered if t["seat"] == 0 and t["index"] > slot]
            if not above:
                continue
            pile = list(game.players[0].graveyard)
            for keywords in _announcements(spec, above):
                game, _ = _board(held)
                before = len(game.stack)
                cast = game.queue_from_hand(
                    0, face.name, from_zone="graveyard", mode_index=mode, **keywords
                )
                if cast.supported and len(game.stack) > before:
                    break
            else:
                self.unannounced.append(f"{label}: {cast.details}")
                continue
            named = keywords["target_permanent_index"]
            named = named if isinstance(named, list) else [named]
            stamps = game.stack[before].target_graveyard_card
            stamps = stamps if isinstance(stamps, list) else [stamps]
            read = [None if stamp is None else stamp.card.name for stamp in stamps]
            wanted = [pile[index].name for index in named]
            if read != wanted or any(s is None or s.seat != 0 for s in stamps):
                self.wrong.append(f"{label}: named {wanted}, the stack holds {read}")
            else:
                self.read_back += 1
        return self


def test_w1g3_a_spell_cast_from_a_graveyard_names_the_card_its_caster_pointed_at():
    census = _Census().run()
    assert not census.wrong, census.wrong
    assert not census.offered_itself, census.offered_itself
    # 64 cards in the pool announce a graveyard card when this was written;
    # the floor is on how many were really cast at a slot above their own and
    # read back.
    assert len(_population()) >= 60
    assert census.read_back >= 55, (census.read_back, census.unannounced)
    assert len(census.unannounced) <= 6, census.unannounced


def test_w1g3_the_census_sees_a_slot_counted_after_the_spell_has_left(monkeypatch):
    """Validated backwards: without the re-count, the census names the cards —
    a shipped one among them, which is what this was before Odyssey."""
    monkeypatch.setattr(
        SpellCastingMixin, "_rebase_graveyard_targets", lambda self, *args: None
    )
    census = _Census().run(only={"Raise Dead", "Regrowth", "Morgue Theft", "Coffin Purge", "Recoup"})
    assert len(census.wrong) == 5, census.wrong
    assert any(line.startswith("Raise Dead:") for line in census.wrong)


def test_w1g3_the_census_sees_a_spell_offered_as_its_own_target(monkeypatch):
    """Validated backwards: with the spec left unmarked, every spell whose
    phrase the card itself answers is offered its own slot."""
    # Both callers' bindings: the enumeration's (a spell's own pile) and the
    # cast spec's (a permanent spell's entry-trigger list).
    for module in (legality_enumeration, legality_cast_spec):
        monkeypatch.setattr(module, "_cast_from_graveyard_slot", lambda *args: None)
    census = _Census().run()
    for name in ("Regrowth", "Coffin Purge", "Recoup", "Elven Cache"):
        assert name in census.offered_itself, (name, census.offered_itself)
    assert len(census.offered_itself) >= 10


def test_w1g3_the_mark_is_on_the_announcement_and_not_on_the_resolution():
    """``CAST_FROM_GRAVEYARD`` is set where the caller says which zone the cast
    leaves, and nowhere else: at resolution the spell is on the stack, and a
    *second copy* in the pile is a legal target the re-check must not lose."""
    regrowth = _pool()["Regrowth"]
    program = compile_card_oracle(regrowth)
    assert derive_cast_spec(regrowth, program, from_zone="graveyard")[CAST_FROM_GRAVEYARD]
    assert CAST_FROM_GRAVEYARD not in derive_cast_spec(regrowth, program)
    assert CAST_FROM_GRAVEYARD not in derive_cast_spec(regrowth, program, from_zone="hand")

    # Two copies in the pile: one is cast, naming the other, and resolves.
    game = Game(players=[
        PlayerState(name="P1", graveyard=[regrowth, regrowth]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    offered = game.cast_target_spec(0, regrowth, from_zone="graveyard")["valid_targets"]
    assert [(t["seat"], t["index"]) for t in offered] == [(0, 1)]
    assert game.cast_from_hand(
        0, "Regrowth", from_zone="graveyard", target_player_index=0, target_permanent_index=1,
    ).supported
    # The copy it named came back to hand; the one that was cast is in the
    # graveyard again (an ordinary permission, not a flashback).
    assert [c.name for c in game.players[0].hand] == ["Regrowth"]
    assert [c.name for c in game.players[0].graveyard] == ["Regrowth"]


# ---------------------------------------------------------------------------
# "Target player exiles all … cards from their graveyard"
# ---------------------------------------------------------------------------

def _sweeper(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{B}", cmc=1.0, type_line="Instant", oracle_text=text,
        colors=("B",), color_identity=("B",), keywords=(), produced_mana=(), raw={},
    )


@pytest.mark.parametrize("phrase, taken", [
    ("all land cards", ["Forest"]),
    ("all creature cards", ["Grizzly Bears", "Prodigal Sorcerer"]),
    ("all cards with flashback", ["Firebolt"]),
])
def test_w1g3_a_chosen_player_empties_part_of_their_own_graveyard(phrase, taken):
    """The graveyard exile sweep's third pairing (after "your graveyard" and
    "each player … their graveyard"): one seat the announcement chose, emptying
    its own pile of whatever the noun phrase names."""
    by_name = _pool()
    card = _sweeper("Test Sweep", f"Target player exiles {phrase} from their graveyard.")
    assert compile_card_oracle(card).supported, compile_card_oracle(card).reason
    pile = [by_name[n] for n in ("Forest", "Grizzly Bears", "Firebolt", "Sol Ring", "Prodigal Sorcerer")]
    for chosen in (0, 1):
        game = Game(players=[
            PlayerState(name="P1", hand=[card], graveyard=list(pile)),
            PlayerState(name="P2", graveyard=list(pile)),
        ])
        game.enforce_mana_costs = False
        assert [t["seat"] for t in game.cast_target_spec(0, card)["valid_targets"]] == [0, 1]
        assert game.cast_from_hand(0, "Test Sweep", target_player_index=chosen).supported
        assert sorted(c.name for c in game.players[chosen].exile) == taken
        assert game.players[1 - chosen].exile == []
        assert len(game.players[1 - chosen].graveyard) == len(pile) + (chosen == 1)


def test_w1g3_target_opponent_keeps_its_narrowing_and_a_wrong_possessive_refuses():
    by_name = _pool()
    card = _sweeper("Test Opposing Sweep", "Target opponent exiles all land cards from their graveyard.")
    assert compile_card_oracle(card).supported
    game = Game(players=[
        PlayerState(name="P1", hand=[card], graveyard=[by_name["Forest"]]),
        PlayerState(name="P2", graveyard=[by_name["Forest"]]),
    ])
    game.enforce_mana_costs = False
    assert [t["seat"] for t in game.cast_target_spec(0, card)["valid_targets"]] == [1]
    assert not game.cast_from_hand(0, "Test Opposing Sweep", target_player_index=0).supported
    assert game.cast_from_hand(0, "Test Opposing Sweep", target_player_index=1).supported
    assert [c.name for c in game.players[1].exile] == ["Forest"]
    assert game.players[0].exile == []
    # One player and somebody else's pile is not a sentence any card prints,
    # and a keyword no reader tests on a card in a graveyard is not dropped.
    for unread in (
        "Target player exiles all land cards from your graveyard.",
        "Target player exiles all cards with flying from their graveyard.",
    ):
        assert not compile_card_oracle(_sweeper("Test Unread Sweep", unread)).supported, unread
