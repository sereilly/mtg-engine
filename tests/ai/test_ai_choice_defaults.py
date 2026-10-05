"""Choices an AI seat made that aimed at the wrong thing — each one legal, each
one a card spent on nothing or on the seat's own board.

Three of them, found the same way (a seat nobody asks takes the *first* legal
answer, and the first legal answer is on its own side of the table):

* "a source of your choice" named the caster's own first land;
* a permanent's enters-the-battlefield trigger, whose target this engine names
  as the permanent is cast, had no side at all — so Nekrataal destroyed its
  controller's creature;
* "choose a card name" named a card out of the opponents' graveyards for a
  card that then looks in the chooser's own hand.

Which cards each rule reaches is derived from the compiled program and held
here against the pool, with a floor on how many were examined.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _cast_candidate, choose_activation_action, tap_planned_lands
from engine.ai_valuation import chosen_name_own_zone, entry_trigger_target_side
from engine.faces import castable_faces
from engine.mixins.stack import aura_enchant_noun
from engine.models import Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.targeting import derive_activation_spec, derive_cast_spec
from tests.helpers import _mk_card, resolve_stack

_W2G6_LANDS = ["Plains", "Island", "Swamp", "Mountain", "Forest"] * 3


def _w2g6_game(cards, hand=(), mine=(), theirs=(), *, lands=_W2G6_LANDS) -> Game:
    me = PlayerState(
        name="Me",
        hand=[cards[name] if isinstance(name, str) else name for name in hand],
        battlefield=[Permanent(card=cards[name]) for name in (*lands, *mine)],
        library=[cards["Forest"]] * 10,
    )
    you = PlayerState(
        name="You",
        battlefield=[Permanent(card=cards[name]) for name in theirs],
        library=[cards["Forest"]] * 10,
    )
    game = Game(players=[me, you], enforce_mana_costs=True)
    game._sync_control()
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def _w2g6_named(game: Game, action) -> tuple[int, str] | None:
    """``(controller seat, name)`` of the permanent *action* names, or None."""
    if action.target_permanent_ids:
        found = game.find_permanent_by_id(action.target_permanent_ids[0])
        return None if found is None else (found[0], found[1].card.name)
    index = action.target_permanent_index
    if isinstance(index, int):
        permanent = game.permanent_at(action.target_player_index, index)
        return None if permanent is None else (action.target_player_index, permanent.card.name)
    return None


def _w2g6_cast(game: Game, action):
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
        x_value=action.x_value,
        optional_cost_payments=action.optional_cost_payments,
    )
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


@pytest.fixture(scope="module")
def _w2g6_pool(catalog, catalog_by_name, set_cards):
    """The shipped pool and Invasion (measured today, shipped later), by name."""
    cards = dict(catalog_by_name)
    for card in set_cards("INV"):
        cards.setdefault(card.name, card)
    return cards


# --- "a source of your choice" --------------------------------------------------


def test_w2g6_a_chosen_source_is_an_opposing_creature_not_the_casters_land(_w2g6_pool):
    """Every spell whose cast names "a source of your choice" (CR 609.7a):
    Reverse Damage, Eye for an Eye, Shadowbane, Reflect Damage, Invulnerability
    and Samite Ministration. Each named the caster's own first land. The
    answer is `handlers/prevention.default_damage_source`'s — the opposing
    creature most likely to deal damage — and with no opposing creature the
    card is kept."""
    spells = []
    for whole in _w2g6_pool.values():
        for card in castable_faces(whole):
            program = compile_card_oracle(card)
            if not program.supported or card.primary_type not in ("instant", "sorcery"):
                continue
            spec = derive_cast_spec(card, program)
            if isinstance(spec, dict) and spec.get("source_of_choice"):
                spells.append(card)
    assert len(spells) >= 6, [card.name for card in spells]
    assert {"Reverse Damage", "Eye for an Eye", "Shadowbane", "Reflect Damage",
            "Invulnerability"} <= {card.name for card in spells}

    for card in spells:
        game = _w2g6_game(
            _w2g6_pool, [card], mine=["Grizzly Bears"],
            theirs=["Forest", "Grizzly Bears", "Hill Giant", "Sol Ring"],
        )
        action = _cast_candidate(game, 0, card, 0)
        assert action is not None, card.name
        assert _w2g6_named(game, action) == (1, "Hill Giant"), card.name

        nothing_to_fear = _w2g6_game(
            _w2g6_pool, [card], mine=["Grizzly Bears"], theirs=["Forest", "Sol Ring"],
        )
        assert _cast_candidate(nothing_to_fear, 0, card, 0) is None, card.name


def test_w2g6_an_activated_shield_is_not_raised_against_its_own_controller(_w2g6_pool):
    """The activated half of the same phrase. A shield's category reads "you",
    so the chooser took the activator's own largest creature as the source to
    be shielded *from* — Bone Mask, Dark Sphere, Kithkin Armor, Pentagram of
    the Ages, Protective Sphere, Righteous Aura."""
    examined = 0
    for card, program in compiled_units(_w2g6_pool.values()):
        if not program.supported or card.primary_type in ("instant", "sorcery"):
            continue
        if not any(
            isinstance(spec := derive_activation_spec(ability), dict)
            and spec.get("source_of_choice")
            for ability in program.activated_abilities
        ):
            continue
        game = _w2g6_game(
            _w2g6_pool, mine=[card.name, "Grizzly Bears"],
            theirs=["Forest", "Shivan Dragon", "Hill Giant", "Black Knight"],
        )
        action = choose_activation_action(game, 0)
        if action is None or action.permanent_name != card.name:
            continue
        examined += 1
        index = action.target_permanent_index
        assert isinstance(index, int), card.name
        named = game.permanent_at(action.target_player_index, index)
        assert (action.target_player_index, named.card.name) == (1, "Shivan Dragon"), card.name

    assert examined >= 6, f"only {examined} activated source-of-choice shields were proposed"


# --- a permanent's entry trigger -----------------------------------------------


def test_w2g6_an_entry_triggers_target_is_on_the_side_the_effect_wants(_w2g6_pool):
    """Every permanent spell whose enters-the-battlefield trigger names an
    object target, on a board where both seats hold everything it could name:
    the seat the AI aims at is the one the effect is for. Eighteen of them —
    Nekrataal, Man-o'-War, Avalanche Riders, Uktabi Orangutan, Bone Shredder,
    the five Emissaries, … — were aimed at the caster's own permanents."""
    board = ["Grizzly Bears", "Hill Giant", "Sol Ring", "Castle", "Black Knight",
             "Wall of Wood", "Scryb Sprites"]
    examined, sided, wrong = 0, 0, []
    for whole in _w2g6_pool.values():
        for card in castable_faces(whole):
            types = (card.type_line or "").lower()
            if "instant" in types or "sorcery" in types or "land" in types:
                continue
            program = compile_card_oracle(card)
            if not program.supported or aura_enchant_noun(card) is not None:
                continue
            spec = derive_cast_spec(card, program)
            if not isinstance(spec, dict) or spec.get("kind") in (
                None, "none", "modal", "player", "stack", "graveyard_creature", "hand_card",
            ):
                continue
            if any(spec.get(key) for key in ("sacrifice_cost", "discard_cost", "exile_cost", "optional")):
                continue
            examined += 1
            wanted = entry_trigger_target_side(card)
            game = _w2g6_game(_w2g6_pool, [whole], mine=board, theirs=["Forest"] * 3 + board)
            action = _cast_candidate(game, 0, card, 0)
            named = None if action is None else _w2g6_named(game, action)
            if wanted is None or named is None:
                continue
            sided += 1
            if (named[0] == 0) != (wanted == "you"):
                wrong.append((card.name, wanted, named))

    assert examined >= 30, f"only {examined} entry-trigger targets examined"
    assert sided >= 22, f"only {sided} of them had both a side and a named permanent"
    assert not wrong, wrong


def test_w2g6_a_removal_creature_is_cast_at_the_opponent_or_kept(_w2g6_pool):
    """Nekrataal: "When this creature enters, destroy target nonartifact,
    nonblack creature." Cast, it kills the opponent's creature; with only the
    caster's own to name it is not proposed — CR 603.3d would make the trigger
    take the one legal target there is."""
    game = _w2g6_game(_w2g6_pool, ["Nekrataal"], mine=["Grizzly Bears"], theirs=["Hill Giant"])
    action = _cast_candidate(game, 0, _w2g6_pool["Nekrataal"], 0)
    assert _w2g6_named(game, action) == (1, "Hill Giant")
    assert _w2g6_cast(game, action).supported
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert sorted(
        p.card.name for p in game.controlled_by(0) if not p.has_type("land")
    ) == ["Grizzly Bears", "Nekrataal"]

    alone = _w2g6_game(_w2g6_pool, ["Nekrataal"], mine=["Grizzly Bears"])
    assert _cast_candidate(alone, 0, _w2g6_pool["Nekrataal"], 0) is None


def test_w2g6_a_kicker_is_not_paid_to_destroy_the_casters_own_enchantment(_w2g6_pool):
    """W1G1's Tolarian Emissary. The headless default was not the fault: it
    prefers an opponent's enchantment and takes the caster's own only when
    CR 603.3d leaves nothing else. The *proposer* named the caster's Castle
    with an opponent's Crusade on the table, and kicked to do it. Now the
    kicked half is aimed across the table, and with nothing there the creature
    is cast unkicked."""
    emissary = _w2g6_pool["Tolarian Emissary"]
    both = _w2g6_game(_w2g6_pool, [emissary], mine=["Castle"], theirs=["Crusade"])
    action = _cast_candidate(both, 0, emissary, 0)
    assert action.optional_cost_payments and _w2g6_named(both, action) == (1, "Crusade")
    assert _w2g6_cast(both, action).supported
    assert [card.name for card in both.players[1].graveyard] == ["Crusade"]
    assert both.players[0].graveyard == []

    mine_only = _w2g6_game(_w2g6_pool, [emissary], mine=["Castle"])
    action = _cast_candidate(mine_only, 0, emissary, 0)
    assert action is not None and action.optional_cost_payments is None
    assert _w2g6_cast(mine_only, action).supported
    assert mine_only.players[0].graveyard == []
    assert "Castle" in [p.card.name for p in mine_only.controlled_by(0)]


# --- "choose a card name" --------------------------------------------------------


def test_w2g6_where_a_chosen_name_is_looked_for_is_read_off_the_next_sentence(_w2g6_pool):
    """Four cards choose a card name as a step of their own (the three naming
    paragraphs with whole-effect handlers are not this). Three then look among
    the chooser's own cards; Foreshadow mills an opponent."""
    found = {}
    for card, program in compiled_units(_w2g6_pool.values()):
        roots = [
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
        ]
        for root in roots:
            for step in (root.payload or {}).get("steps") or ():
                if step.kind == "choose_card_name":
                    found[card.name] = chosen_name_own_zone(card, step)
    assert found == {
        "Wood Sage": "library",
        "Desperate Research": "library",
        "Cursed Scroll": "hand",
        "Foreshadow": None,
    }

    invented = _mk_card(
        "Invented Sage", "{G}", "Sorcery",
        "Choose a card name. Reveal the top four cards of your library and put all "
        "of them with that name into your hand. Put the rest into your graveyard.",
    )
    program = compile_card_oracle(invented)
    assert program.supported
    step = program.instructions[0].payload["steps"][0]
    assert chosen_name_own_zone(invented, step) == "library"


def test_w2g6_a_scroll_names_the_card_its_controller_is_holding(_w2g6_pool):
    """Cursed Scroll with one card in hand is a certain hit, and a seat nobody
    asked named a card out of the *opponent's graveyard* — eleven activations
    running in one simulated game, each revealing the same Whim of Volrath."""
    game = _w2g6_game(_w2g6_pool, ["Hill Giant"], mine=["Cursed Scroll"])
    game.players[1].graveyard = [_w2g6_pool["Grizzly Bears"]] * 3
    game.enforce_mana_costs = False
    result = game.activate_permanent_ability(0, "Cursed Scroll", target_player_index=1)
    assert result.supported, result.details
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert any("named Hill Giant" in line for line in game.log), game.log[-8:]
    assert game.players[1].life == 18


def test_w2g6_a_name_looked_for_in_an_opponents_library_is_still_guessed_from_their_graveyard(
    _w2g6_pool,
):
    """Foreshadow is the one the old default was right for, and it does not
    move: an opponent's graveyard is public (CR 400.2) and is the evidence a
    player has of what that library holds."""
    game = _w2g6_game(_w2g6_pool, ["Foreshadow", "Hill Giant"])
    game.players[1].graveyard = [_w2g6_pool["Grizzly Bears"]] * 2
    game.players[1].library = [_w2g6_pool["Grizzly Bears"]] * 5
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Foreshadow", target_player_index=1).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert any("named Grizzly Bears" in line for line in game.log), game.log[-8:]
