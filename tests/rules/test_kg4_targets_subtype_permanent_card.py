""""<Subtype> permanent card" is CR 110.4a's union narrowed by the subtype —
not "<Subtype> creature card" (CR 110.4a, 205.3m, 308.2).

    110.4a The term "permanent card" is used to refer to a card that could be
    put onto the battlefield. Specifically, it means an artifact, battle,
    creature, enchantment, land, or planeswalker card.

    205.3m Creatures and kindreds share their lists of subtypes; these
    subtypes are called creature types.

``nouns.parse_object_filter`` recorded the six types only for a *bare*
"permanent card" and left "a Goblin permanent card" to the creature-subtype
implication, so thirty cards (twenty-eight shipped) searched, put from hand,
revealed and reanimated "a <Subtype> creature card". Exact on a pool with no
Kindred card, narrower on one: a Kindred Enchantment — Dragon is a Dragon
permanent card and no creature card. The pool has no Kindred card yet, so the
board is an invented one, driven down each card's own road:

* from the hand — Goblin Wizard (``put_chosen_card_from_hand_onto_battlefield``,
  Goblin Lackey's, Willow Priestess's and Didgeridoo's instruction);
* from the library — Moggcatcher (``search_library``, the Rebel and
  Mercenary searchers', Seahunter's, Skyshroud Poacher's, Zirilan's and
  Dragonstorm's);
* the revealed top card — Skirk Drill Sergeant (``revealed_card_is``);
* from the graveyard — Bladewing the Risen (``reanimate_creature``) and
  Celestial Gatekeeper (``choose_target_cards`` / ``reanimate_announced_cards``).

Each beside the real pool's own answer: a creature card of the subtype is
still a legal choice, and a Kindred *instant* of the subtype (no permanent
card) and a plain noncreature card are not.

Measured backwards on 313bd09d: every Kindred permanent below was refused.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _kindred(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


GOBLIN_IDOL = _kindred("Test Goblin Idol", "Kindred Artifact — Goblin")
GOBLIN_TRICK = _kindred("Test Goblin Trick", "Kindred Instant — Goblin")
DRAGON_SHRINE = _kindred("Test Dragon Shrine", "Kindred Enchantment — Dragon")
DRAGON_BREATH = _kindred("Test Dragon Breath", "Kindred Instant — Dragon")
CLERIC_SHRINE = _kindred("Test Cleric Shrine", "Kindred Enchantment — Cleric")
BIRD_TRICK = _kindred("Test Bird Trick", "Kindred Sorcery — Bird")


def _table(*, mine=(), hand=(), library=(), graveyard=(), interactive=True) -> Game:
    game = Game(players=[
        PlayerState("P0", hand=list(hand),
                    library=list(library) or [_POOL["Island"]] * 5,
                    graveyard=list(graveyard)),
        PlayerState("P1", library=[_POOL["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    for name in mine:
        game._put_permanent_onto_battlefield(0, Permanent(card=_POOL[name]), None)
    game.start_turn(0)
    game._close_current_priority_step()
    for permanent in game.controlled_by(0):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.interactive_seats = {0} if interactive else set()
    return game


def _names(cards) -> set[str]:
    return {card.name for card in cards}


def _battlefield(game: Game) -> set[str]:
    return {perm.card.name for perm in game.controlled_by(0)}


def _accept_may(game: Game) -> None:
    """Answer a "you may" the resolution asked seat 0, if it asked one."""
    for kind in ("optional_effect", "may_choice", "optional_pay"):
        choice = game.pending_choice_of(kind, 0) if hasattr(game, "pending_choice_of") else None
        if choice is not None:
            if kind == "optional_pay":
                assert game.confirm_optional_pay(0, accept=True)
            else:
                assert game.resolve_pending_choice(kind, 0, accept=True)
            return


# --- from the hand -----------------------------------------------------------


@pytest.mark.cr("110.4a", "205.3m", "308.2")
def test_goblin_wizard_offers_a_kindred_goblin_artifact_from_the_hand():
    hand = [GOBLIN_IDOL, GOBLIN_TRICK, _POOL["Raging Goblin"], _POOL["Grizzly Bears"],
            _POOL["Jayemdae Tome"]]
    game = _table(mine=["Goblin Wizard"], hand=hand)
    assert game.queue_permanent_ability(0, "Goblin Wizard", ability_index=0).supported, game.log[-4:]
    game.resolve_top_of_stack()
    _accept_may(game)
    choice = game.pending_choice_of("put_from_hand_choice", 0)
    assert choice is not None, ([c.kind for c in game.pending_choices], game.log[-4:])
    hand_now = game.players[0].hand
    offered = {hand_now[slot].name for slot in game.live_put_from_hand_choices(choice)}
    assert offered == {"Test Goblin Idol", "Raging Goblin"}, offered
    assert game.confirm_put_from_hand_choice(0, hand_now.index(GOBLIN_IDOL))
    resolve_stack(game)
    assert "Test Goblin Idol" in _battlefield(game), game.log[-6:]


# --- from the library --------------------------------------------------------


def _moggcatcher(library) -> Game:
    game = _table(mine=["Moggcatcher"], library=library)
    assert game.queue_permanent_ability(0, "Moggcatcher", ability_index=0).supported, game.log[-4:]
    game.resolve_top_of_stack()
    assert game.pending_choice_of("search_library", 0) is not None, game.log[-4:]
    return game


def _pick(game: Game, name: str) -> bool:
    names = [card.name for card in game.players[0].library]
    return game.resolve_pending_choice(
        "search_library", 0, library_index=names.index(name), zone="library",
    )


@pytest.mark.cr("110.4a", "205.3m", "701.23a")
def test_moggcatcher_finds_a_kindred_goblin_artifact():
    game = _moggcatcher([GOBLIN_TRICK, _POOL["Grizzly Bears"], _POOL["Jayemdae Tome"],
                         GOBLIN_IDOL, _POOL["Raging Goblin"]])
    assert not _pick(game, "Test Goblin Trick"), "a Kindred instant is no permanent card"
    assert not _pick(game, "Grizzly Bears"), "a creature card that is no Goblin"
    assert not _pick(game, "Jayemdae Tome"), "a noncreature, non-Kindred card"
    assert _pick(game, "Test Goblin Idol"), game.log[-4:]
    resolve_stack(game)
    assert "Test Goblin Idol" in _battlefield(game), game.log[-6:]


@pytest.mark.cr("110.4a", "701.23a")
def test_moggcatcher_still_finds_a_goblin_creature_card():
    game = _moggcatcher([GOBLIN_TRICK, _POOL["Raging Goblin"]])
    assert _pick(game, "Raging Goblin"), game.log[-4:]
    resolve_stack(game)
    assert "Raging Goblin" in _battlefield(game), game.log[-6:]


# --- the revealed top card ---------------------------------------------------


@pytest.mark.cr("110.4a", "205.3m")
@pytest.mark.parametrize("top, enters", [
    (GOBLIN_IDOL, True), (GOBLIN_TRICK, False), ("Raging Goblin", True),
])
def test_skirk_drill_sergeant_puts_a_revealed_goblin_permanent_card_onto_the_battlefield(top, enters):
    top = _POOL[top] if isinstance(top, str) else top
    game = _table(mine=["Skirk Drill Sergeant", "Goblin Balloon Brigade", "Mountain", "Mountain", "Mountain"],
                  hand=[_POOL["Terror"]], library=[top, _POOL["Island"]])
    brigade = next(p for p in game.controlled_by(0) if p.card.name == "Goblin Balloon Brigade")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[brigade.permanent_id]).supported
    for _ in range(6):
        if game.pending_choice_of("optional_pay", 0) is not None:
            assert game.confirm_optional_pay(0, accept=True), game.log[-4:]
        if not game.stack and not game.pending_choices:
            break
        resolve_stack(game)
    assert any("reveal" in line and top.name in line for line in game.log), game.log[-8:]
    assert (top.name in _battlefield(game)) is enters, game.log[-8:]
    if not enters:
        assert top in game.players[0].graveyard, game.log[-8:]


# --- from the graveyard ------------------------------------------------------


@pytest.mark.cr("110.4a", "205.3m", "308.2")
@pytest.mark.parametrize("graveyard, returned", [
    ((DRAGON_BREATH, DRAGON_SHRINE), "Test Dragon Shrine"),
    ((DRAGON_BREATH, "Shivan Dragon"), "Shivan Dragon"),
    ((DRAGON_BREATH, "Jayemdae Tome"), None),
])
def test_bladewing_returns_a_dragon_permanent_card(graveyard, returned):
    pile = [_POOL[card] if isinstance(card, str) else card for card in graveyard]
    game = _table(graveyard=pile, interactive=False)
    game._put_permanent_onto_battlefield(0, Permanent(card=_POOL["Bladewing the Risen"]), None)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    on_field = _battlefield(game) - {"Bladewing the Risen"}
    assert on_field == ({returned} if returned else set()), game.log[-6:]
    assert DRAGON_BREATH in game.players[0].graveyard, game.log[-6:]


@pytest.mark.cr("110.4a", "205.3m", "308.2")
def test_celestial_gatekeeper_returns_kindred_and_creature_bird_and_cleric_cards():
    pile = [BIRD_TRICK, CLERIC_SHRINE, _POOL["Birds of Paradise"], _POOL["Jayemdae Tome"]]
    game = _table(mine=["Celestial Gatekeeper"], hand=[_POOL["Terror"]],
                  graveyard=pile, interactive=False)
    gatekeeper = next(p for p in game.controlled_by(0) if p.card.name == "Celestial Gatekeeper")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[gatekeeper.permanent_id]).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert _battlefield(game) == {"Test Cleric Shrine", "Birds of Paradise"}, game.log[-8:]
    assert _names(game.players[0].graveyard) >= {"Test Bird Trick", "Jayemdae Tome"}, game.log[-8:]
