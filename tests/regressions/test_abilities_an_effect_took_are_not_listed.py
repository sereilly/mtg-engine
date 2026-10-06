"""A permanent an effect stripped of its abilities **lists** none.

Two rules take a permanent's activated abilities away without touching its
text: "loses all abilities" (Titania's Song on a noncreature artifact) and
CR 305.7 — a land whose subtype an effect *set* to a basic land type "loses all
abilities generated from its rules text". The activation path has refused both
for a long time; what did not know was every place that **lists** a
permanent's abilities, each of which read the compiled program — the card as
it prints — and asked one of the two rules, or neither:

* the picker (``activation_target_spec``) and the wire's per-ability specs
  described abilities the door refuses, and the client's menu, built from the
  oracle text, offered them: a dead button each;
* the AI's own-seat chooser proposed a stripped artifact's ability every turn
  and was refused every turn; its mana planner counted a Sol Ring that no
  longer had a mana ability.

``Game.lost_abilities_refusal`` is the one predicate — the door's two checks
made one — and ``Game.usable_abilities_of`` the one list that asks it. The
sweeps below hold the list to the door, in both directions, for every land and
every noncreature artifact in the pool that prints an activated ability.

Measured on the tree before this file: 164 lands print an activated ability,
and after their type was set the picker's reading (the effective card's
program) still listed one for **164 of 164**. Of 296 noncreature artifacts
under Titania's Song that reading was already right — ``effective_card`` drops
the text of a permanent that lost all abilities — and the AI's own-seat
chooser, which read the *printed* card, listed one for **296 of 296**.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_activation_action
from engine.card_loader import load_catalog
from engine.land_types import change_land_type
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _printed(card) -> list:
    """What the card's own program lists — the reading every list used."""
    return usable_activated_abilities(compile_card_oracle(card))


def _game_with(by_name, *names):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    permanents = []
    for name in names:
        permanent = Permanent(card=by_name[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanents.append(_nosick(permanent))
    return game, permanents


def _list_and_door(game, permanent, reason: str) -> tuple[bool, list[int]]:
    """``(listed, accepted)``: whether any list still carries an ability of
    *permanent*, and which printed ability indices the door let through."""
    slot = game.battlefield_index_of(permanent)
    printed = _printed(permanent.card)
    listed = bool(game.usable_abilities_of(permanent)) or (
        game.activation_target_spec(0, slot).get("kind") != "none"
    )
    accepted = []
    for index in range(len(printed)):
        result = game.queue_permanent_ability(
            0, permanent.card.name, permanent_index=slot, ability_index=index,
        )
        if result.supported or reason not in result.details:
            accepted.append(index)
    return listed, accepted


def _land_sweep(catalog, by_name):
    """Every land printing an activated ability, its type set to Mountain."""
    examined = 0
    listed: list[str] = []
    accepted: list[tuple] = []
    for card in catalog:
        if card.primary_type != "land" or not _printed(card):
            continue
        game, (land,) = _game_with(by_name, card.name)
        if not game.is_on_battlefield(land):
            continue
        assert game.usable_abilities_of(land) == _printed(land.effective_card)
        change_land_type(land, "mountain", source="test")
        game._recompute_continuous_effects()
        examined += 1
        still_listed, let_through = _list_and_door(game, land, "305.7")
        if still_listed:
            listed.append(card.name)
        if let_through:
            accepted.append((card.name, let_through))
    return examined, listed, accepted


def _artifact_sweep(catalog, by_name):
    """Every noncreature artifact printing an activated ability, under
    Titania's Song ("Each noncreature artifact loses all abilities …")."""
    examined = 0
    listed: list[str] = []
    accepted: list[tuple] = []
    for card in catalog:
        types = card.type_line.lower().split("—")[0]
        if "artifact" not in types or "creature" in types or "land" in types:
            continue
        if not _printed(card):
            continue
        game, (artifact, _song) = _game_with(by_name, card.name, "Titania's Song")
        game._recompute_continuous_effects()
        if not game.is_on_battlefield(artifact):
            continue
        examined += 1
        still_listed, let_through = _list_and_door(
            game, artifact, "has lost all abilities"
        )
        if still_listed:
            listed.append(card.name)
        if let_through:
            accepted.append((card.name, let_through))
    return examined, listed, accepted


def test_a_land_whose_type_was_set_lists_no_ability_and_the_door_agrees(
    _catalog, _by_name
):
    examined, listed, accepted = _land_sweep(_catalog, _by_name)

    assert examined >= 140, f"only {examined} lands examined"
    assert listed == [], f"CR 305.7: still listed after the type was set: {listed[:20]}"
    assert accepted == [], f"…and the door let these through: {accepted[:20]}"


def test_an_artifact_that_lost_all_abilities_lists_none_and_the_door_agrees(
    _catalog, _by_name
):
    examined, listed, accepted = _artifact_sweep(_catalog, _by_name)

    assert examined >= 250, f"only {examined} artifacts examined"
    assert listed == [], f"still listed under Titania's Song: {listed[:20]}"
    assert accepted == [], f"…and the door let these through: {accepted[:20]}"


def test_the_land_sweep_finds_a_list_that_reads_the_program(
    _catalog, _by_name, monkeypatch
):
    """Backwards: a list that reads the land's program off the card as it
    prints, whatever the board did to the land's type. The sweep then names
    every land it examines.

    This patched in the *effective* card's program — the list as the picker
    and the wire read it — and that reading was the one that lied. It is the
    right one now: ``Permanent.effective_card`` strikes the text of a land
    whose type an effect set (CR 305.7), exactly as it has for a permanent
    that lost all abilities, so a list built from it names nothing and could
    no longer stand in for the defect. The printed card's program is what a
    list that forgets the rule reads, as in the artifact twin below."""
    monkeypatch.setattr(
        Game, "usable_abilities_of",
        lambda self, permanent, *, card=None: usable_activated_abilities(
            compile_card_oracle(permanent.card)
        ),
    )
    examined, listed, _accepted = _land_sweep(_catalog, _by_name)

    assert "Mishra's Factory" in listed and len(listed) == examined


def test_the_artifact_sweep_finds_a_list_that_reads_the_printed_card(
    _catalog, _by_name, monkeypatch
):
    """Backwards, for the other rule. ``effective_card`` already drops the
    text of a permanent that lost all abilities, so the effective program was
    never the list that lied here; the **printed** card's was, and that is
    what the AI's own-seat chooser compiled."""
    monkeypatch.setattr(
        Game, "usable_abilities_of",
        lambda self, permanent, *, card=None: usable_activated_abilities(
            compile_card_oracle(permanent.card)
        ),
    )
    examined, listed, _accepted = _artifact_sweep(_catalog, _by_name)

    assert "Jayemdae Tome" in listed and len(listed) == examined


def test_mishras_factory_under_blood_moon_is_a_mountain_and_nothing_else(_by_name):
    """"Nonbasic lands are Mountains." The Factory taps for {R} — the mana
    ability of its new type, CR 305.7's other half — and has no ability to
    animate itself with, on any list."""
    game, (factory, _moon) = _game_with(_by_name, "Mishra's Factory", "Blood Moon")
    game._recompute_continuous_effects()

    assert len(_printed(factory.card)) == 3
    assert game.usable_abilities_of(factory) == []
    assert game.lost_abilities_refusal(factory) == (
        "Mishra's Factory lost its abilities when its land type was set (CR 305.7)"
    )
    spec = game.activation_target_spec(0, 0)
    assert spec["kind"] == "none" and spec["valid_targets"] == []

    assert game.tap_land_for_mana(0, "Mishra's Factory", chosen_color="R", permanent_index=0)
    assert factory.tapped and game.players[0].mana_pool.get("R") == 1


def test_the_ai_does_not_propose_an_ability_the_board_took_away(_by_name, monkeypatch):
    """"{4}, {T}: Draw a card." (Jayemdae Tome.) Under Titania's Song the Tome
    is a 4/4 with no abilities; the own-seat chooser read the card's program
    and proposed the draw, which the engine refused, every turn."""
    game, (tome, _song) = _game_with(_by_name, "Jayemdae Tome", "Titania's Song")
    game._recompute_continuous_effects()

    assert choose_activation_action(game, 0) is None

    monkeypatch.setattr(Game, "lost_abilities_refusal", lambda self, permanent: None)
    proposed = choose_activation_action(game, 0)

    assert proposed is not None and proposed.permanent_name == "Jayemdae Tome"
