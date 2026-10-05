"""Split cards — CR 709.

The pool's first multi-face layout, and the rule is two sentences pulling in
opposite directions. **On the stack** only the half being cast exists
(CR 709.3b): its name, its mana cost, its colour, its type, its text. **Every-
where else** the card is both halves at once (CR 709.4): two names, the
combined cost, every colour and every type. And through all of it there is one
card (CR 709.2).

``engine/faces.py`` makes the first true by construction — each half is derived
as a card of its own and *that* is what the stack holds, so every reader of a
spell is right without learning anything — and the second by one question,
``whole_card``, asked at the zone seams. These tests drive real casts through a
real ``Game`` and then read the zones, because both halves of that design fail
silently: a half left in a graveyard is still a card with a name, and a whole
card on the stack still resolves (doing nothing).

The fixtures are **invented** split cards rather than Invasion's five, so what
is asserted is the layout and not five cards; the per-card tests are in
``tests/sets/test_inv_instants.py`` / ``test_inv_sorceries.py``. One of them
pairs an instant with a sorcery, which no Invasion card does, because the two
halves' types have to be told apart for CR 709.3a to mean anything.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.exiled_records import live_records
from engine.faces import (card_names, castable_faces, face_cards, has_name,
                          is_face, spell_named, whole_card)
from engine.models import CardDefinition, CardFace, Permanent, PlayerState
from engine.search_filters import card_colors, card_has_type
from engine.targeting import stack_object_mana_value

from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _split(left: CardFace, right: CardFace, *, colors, cmc) -> CardDefinition:
    """A split card as the loader builds one: empty text box, both costs
    spelled into ``mana_cost``, the combined colours and mana value on top."""
    return CardDefinition(
        name=f"{left.name} // {right.name}",
        mana_cost=f"{left.mana_cost} // {right.mana_cost}",
        cmc=cmc,
        type_line=f"{left.type_line} // {right.type_line}",
        oracle_text="",
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={},
        layout="split",
        faces=(left, right),
    )


#: A red instant and a green sorcery on one card. Different colours, different
#: costs, different types, one targeted and one not — every axis CR 709.3a's
#: "only the chosen half is evaluated" can be asked along.
BURN_GROW = _split(
    CardFace("Burn", "{R}", "Instant", "Burn deals 2 damage to any target."),
    CardFace("Grow", "{3}{G}", "Sorcery", "Create a 3/3 green Elephant creature token."),
    colors=("G", "R"), cmc=5.0,
)

#: One half that needs a target the board may not have, one that needs none.
SMASH_THINK = _split(
    CardFace("Smash", "{1}{R}", "Instant", "Destroy target artifact."),
    CardFace("Think", "{1}{U}", "Instant", "Draw a card."),
    colors=("R", "U"), cmc=4.0,
)


def _duel(*, enforce: bool = False):
    filler = _POOL["Forest"]
    game = Game(players=[
        PlayerState(name="P0", library=[filler] * 10),
        PlayerState(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = enforce
    return game, game.players[0], game.players[1]


def _cards_outside_the_stack(game):
    """Every card object in a zone that is not the stack."""
    for player in game.players:
        for zone in (
            player.hand, player.library, player.graveyard, player.exile,
            player.ante, player.command_zone, player.sideboard,
        ):
            yield from zone
    for permanent in game.all_permanents():
        yield permanent.card


def _no_half_is_loose(game) -> bool:
    return not any(is_face(card) for card in _cards_outside_the_stack(game))


# ---------------------------------------------------------------------------
# CR 709.1 / 709.2 — two halves, one card
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.1", "709.2")
def test_a_split_card_is_one_card_with_two_castable_halves():
    halves = face_cards(BURN_GROW)
    assert [half.name for half in halves] == ["Burn", "Grow"]
    assert castable_faces(BURN_GROW) == halves
    # Each half is the card it is on the stack: its own cost, mana value,
    # colour and type, and it knows the card it is half of.
    burn, grow = halves
    assert (burn.mana_cost, burn.cmc, burn.colors, burn.type_line) == (
        "{R}", 1.0, ("R",), "Instant",
    )
    assert (grow.mana_cost, grow.cmc, grow.colors, grow.type_line) == (
        "{3}{G}", 4.0, ("G",), "Sorcery",
    )
    assert whole_card(burn) is BURN_GROW and whole_card(grow) is BURN_GROW
    assert whole_card(BURN_GROW) is BURN_GROW
    # The halves are the same objects every time they are asked for: a stack
    # item is compared by identity, and a deck repeats one definition per copy.
    assert face_cards(BURN_GROW)[0] is burn
    # A card with one face is its own only castable face.
    bolt = _POOL["Lightning Bolt"]
    assert face_cards(bolt) == () and castable_faces(bolt) == (bolt,)


@pytest.mark.cr("709.2")
def test_casting_a_half_takes_one_card_from_the_hand_and_returns_one_card():
    """"A player who has drawn or discarded a split card has drawn or discarded
    one card, not two" — and one who cast a half has spent one. Two copies in
    hand are the same Python object (a deck repeats one definition), which is
    the arrangement that deletes cards when a removal is spelled by identity."""
    game, p0, p1 = _duel()
    p0.hand.extend([BURN_GROW, BURN_GROW])

    result = game.cast_from_hand(0, "Burn", target_player_index=1)

    assert result.supported, result.details
    assert p1.life == 18
    assert p0.hand == [BURN_GROW], "exactly one copy left the hand"
    assert len(p0.graveyard) == 1 and p0.graveyard[0] is BURN_GROW
    assert _no_half_is_loose(game)


# ---------------------------------------------------------------------------
# CR 709.3 / 709.3a — the half is chosen as it is cast, and only it is judged
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.3")
def test_a_split_card_named_whole_is_refused_and_nothing_is_spent():
    """The player chooses a half *before* it goes on the stack, so a cast that
    names none is not a cast. Refused rather than defaulted: any deterministic
    pick is the engine casting a different spell from the one that was meant."""
    game, p0, p1 = _duel(enforce=True)
    p0.hand.append(BURN_GROW)
    p0.mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Burn // Grow", target_player_index=1)

    assert not result.supported
    assert "Burn or Grow" in result.details and "709.3" in result.details
    assert p0.hand == [BURN_GROW] and game.stack == []
    assert p0.mana_pool["R"] == 1 and p1.life == 20


@pytest.mark.cr("709.3")
def test_a_half_is_cast_by_its_own_name():
    assert spell_named(BURN_GROW, "Grow") is face_cards(BURN_GROW)[1]
    assert spell_named(BURN_GROW, "Burn // Grow") is None
    assert spell_named(BURN_GROW, "Shock") is None

    game, p0, _p1 = _duel()
    p0.hand.append(BURN_GROW)
    assert game.cast_from_hand(0, "Grow").supported
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Elephant Token"]


@pytest.mark.cr("709.3a", "601.2h")
def test_only_the_chosen_halfs_cost_is_paid():
    """Burn is {R} and Grow is {3}{G}. A pool holding one green mana casts
    neither — not Burn, whose price is red, and not Grow, which costs four —
    and one holding {R} casts Burn and is charged exactly that."""
    game, p0, p1 = _duel(enforce=True)
    p0.hand.append(BURN_GROW)
    p0.mana_pool["G"] = 1

    assert not game.cast_from_hand(0, "Burn", target_player_index=1).supported
    assert not game.cast_from_hand(0, "Grow").supported
    assert p0.hand == [BURN_GROW] and p0.mana_pool["G"] == 1

    p0.mana_pool["R"] = 1
    assert game.cast_from_hand(0, "Burn", target_player_index=1).supported
    assert p1.life == 18
    assert (p0.mana_pool["R"], p0.mana_pool["G"]) == (0, 1)


@pytest.mark.cr("709.3a", "601.2f")
def test_a_cost_increase_applies_to_the_half_it_describes():
    """"Red spells cost {2} more to cast." (Chill.) The card in hand is red
    *and* green (CR 709.4b); the spell is one or the other (CR 709.3b), and the
    tax is on the spell."""
    game, p0, _p1 = _duel(enforce=True)
    game._put_permanent_onto_battlefield(1, Permanent(card=_POOL["Chill"]), None)
    p0.hand.extend([BURN_GROW, BURN_GROW])

    p0.mana_pool["R"] = 1
    assert not game.cast_from_hand(0, "Burn", target_player_index=1).supported
    p0.mana_pool["R"] = 3
    assert game.cast_from_hand(0, "Burn", target_player_index=1).supported
    assert p0.mana_pool["R"] == 0, "{R} plus Chill's {2}"

    p0.mana_pool["G"] = 4
    assert game.cast_from_hand(0, "Grow").supported, "green is not taxed"
    assert p0.mana_pool["G"] == 0


@pytest.mark.cr("709.3a", "601.2c")
def test_only_the_chosen_halfs_targets_are_required():
    """With no artifact on the battlefield Smash has no legal target and cannot
    be cast; Think, on the same card, needs none."""
    game, p0, _p1 = _duel()
    p0.hand.append(SMASH_THINK)

    assert game.cast_target_spec(0, SMASH_THINK)["kind"] == "faces"
    smash, think = face_cards(SMASH_THINK)
    assert game.cast_target_spec(0, smash)["valid_targets"] == []
    refused = game.cast_from_hand(0, "Smash")
    assert not refused.supported and p0.hand == [SMASH_THINK]

    before = len(p0.hand)
    assert game.cast_from_hand(0, "Think").supported
    assert len(p0.hand) == before, "one card cast, one card drawn"
    assert p0.graveyard == [SMASH_THINK]


# ---------------------------------------------------------------------------
# CR 709.3b — on the stack, only the half exists
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.3b")
def test_on_the_stack_only_the_cast_halfs_characteristics_exist():
    game, p0, _p1 = _duel()
    p0.hand.append(BURN_GROW)
    assert game.queue_from_hand(0, "Burn", target_player_index=1).supported

    spell = game.stack[-1]
    assert spell.card.name == "Burn"
    assert tuple(game._stack_item_colors(spell)) == ("R",), "not green"
    assert stack_object_mana_value(spell) == 1, "not 5"
    assert card_has_type(spell.card, "instant")
    assert not card_has_type(spell.card, "sorcery")
    assert spell.card.oracle_text == "Burn deals 2 damage to any target."
    # ...and the spell record every "you've cast a red spell this turn" reads
    # holds the half too.
    assert [card.name for card in p0.spells_cast_this_turn] == ["Burn"]


@pytest.mark.cr("709.3b")
def test_a_colour_keyed_counterspell_sees_the_half_not_the_card():
    """"Counter target red spell." (Blue Elemental Blast's first mode.) Burn is
    a red spell and a legal target; Grow, cast off the same red-and-green card,
    is a green spell and is not."""
    blast = _POOL["Blue Elemental Blast"]

    game, p0, p1 = _duel()
    p0.hand.append(BURN_GROW)
    p1.hand.append(blast)
    game.queue_from_hand(0, "Burn", target_player_index=1)
    assert game.queue_from_hand(1, blast.name, target_stack_index=0, mode_index=0).supported
    resolve_stack(game)
    assert p1.life == 20, "Burn was countered"
    assert p0.graveyard == [BURN_GROW]

    game, p0, p1 = _duel()
    p0.hand.append(BURN_GROW)
    p1.hand.append(blast)
    game.queue_from_hand(0, "Grow")
    refused = game.queue_from_hand(1, blast.name, target_stack_index=0, mode_index=0)
    assert not refused.supported, "a green spell is no target for it"
    resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Elephant Token"]


# ---------------------------------------------------------------------------
# CR 709.4 — everywhere else, both halves at once
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.4", "709.4b", "709.4c")
def test_off_the_stack_the_card_has_the_combined_characteristics():
    """Red and green, mana value 5, an instant and a sorcery — whatever reads a
    card in a hand, a library or a graveyard reads all of it."""
    game, p0, _p1 = _duel()
    p0.hand.append(BURN_GROW)

    assert set(card_colors(BURN_GROW, game=game, owner=p0)) == {"R", "G"}
    assert BURN_GROW.cmc == 5.0
    assert card_has_type(BURN_GROW, "instant") and card_has_type(BURN_GROW, "sorcery")
    # CR 709.4b's last sentence: an effect reading the *symbols* sees them all.
    from engine.mana_payment import mana_cost_from_symbols

    assert mana_cost_from_symbols(BURN_GROW.mana_cost) == {"R": 1, "generic": 3, "G": 1}


@pytest.mark.cr("709.4a")
def test_a_split_card_has_both_names_and_the_stack_object_has_one():
    assert card_names(BURN_GROW) == ("Burn", "Grow")
    assert has_name(BURN_GROW, "Burn") and has_name(BURN_GROW, "Grow")
    assert not has_name(BURN_GROW, "Shock")
    # The half on the stack is called what it is called and nothing else.
    burn = face_cards(BURN_GROW)[0]
    assert card_names(burn) == ("Burn",) and not has_name(burn, "Grow")


@pytest.mark.cr("709.4", "608.2n")
def test_a_resolved_half_goes_to_the_graveyard_as_the_whole_card():
    game, p0, _p1 = _duel()
    p0.hand.append(BURN_GROW)
    game.cast_from_hand(0, "Grow")
    assert len(p0.graveyard) == 1 and p0.graveyard[0] is BURN_GROW
    assert _no_half_is_loose(game)


@pytest.mark.cr("709.4", "701.6a")
@pytest.mark.parametrize(
    "answer, zone",
    [
        ("Counterspell", "graveyard"),
        ("Memory Lapse", "library"),
        ("Dissipate", "exile"),
        ("Unsubstantiate", "hand"),
    ],
)
def test_a_half_leaving_the_stack_any_other_way_is_the_whole_card_again(answer, zone):
    """Countered into a graveyard, put on top of a library, exiled, returned to
    a hand: four destinations, four pieces of code, and in every one the object
    that arrives is the card with both halves on it — never the half."""
    game, p0, p1 = _duel()
    p0.hand.append(BURN_GROW)
    p1.hand.append(_POOL[answer])
    game.queue_from_hand(0, "Burn", target_player_index=1)
    assert game.queue_from_hand(1, answer, target_stack_index=0).supported
    resolve_stack(game)

    assert p1.life == 20, "Burn never resolved"
    pile = getattr(p0, zone)
    arrived = pile[0] if zone == "library" else pile[-1]
    assert arrived is BURN_GROW
    assert sum(1 for card in _cards_outside_the_stack(game) if card is BURN_GROW) == 1
    assert _no_half_is_loose(game)


@pytest.mark.cr("709.4", "709.3b", "707.10")
def test_a_half_exiled_and_put_back_as_a_copy_of_the_spell_is_that_half():
    """"Target spell's controller exiles it with X delay counters on it. … the
    player puts it onto the stack as a copy of the original spell." (Ertai's
    Meddling.) The card in exile is the whole card (CR 709.4); the copy has the
    characteristics of the *spell* (CR 707.10), which were one half's
    (CR 709.3b) — so it is Burn that comes back, aimed where Burn was aimed."""
    game, p0, p1 = _duel()
    p0.hand.append(BURN_GROW)
    p1.hand.append(_POOL["Ertai's Meddling"])
    game.queue_from_hand(0, "Burn", target_player_index=1)
    assert game.queue_from_hand(
        1, "Ertai's Meddling", target_stack_index=0, x_value=1,
    ).supported
    resolve_stack(game)

    assert p0.exile == [BURN_GROW] and p1.life == 20
    record = next(iter(live_records(game)))
    assert record.card is BURN_GROW
    assert record.announcement.face_name == "Burn"

    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()

    assert p0.exile == []
    assert p1.life == 18, "the copy was Burn and kept Burn's target"
    assert p0.graveyard == [BURN_GROW]
    assert _no_half_is_loose(game)


@pytest.mark.cr("709.4a")
@pytest.mark.parametrize("named, hit", [("Burn", True), ("Grow", True), ("Shock", False)])
def test_a_chosen_card_name_matches_a_split_card_by_either_half(named, hit):
    """"Target player chooses a card name, then reveals the top card of their
    library. If that card has the chosen name, that player puts it into their
    hand." (Petra Sphinx.) "An object has the chosen name if one of its names
    is the chosen name" — so naming either half of the split card on top is a
    hit, and it arrives as the one card it is."""
    sphinx = Permanent(card=_POOL["Petra Sphinx"])
    chooser = PlayerState(name="P0", library=[BURN_GROW, _POOL["Forest"]])
    game = Game(players=[chooser, PlayerState(name="P1", battlefield=[sphinx])])
    game.start_turn(1)

    assert game.activate_permanent_ability(
        1, "Petra Sphinx", target_player_index=0,
    ).supported
    game._settle()
    assert game.confirm_name_then_reveal_top(0, named)

    assert chooser.hand == ([BURN_GROW] if hit else [])
    assert chooser.graveyard == ([] if hit else [BURN_GROW])


@pytest.mark.cr("709.4a")
def test_every_chosen_name_comparison_over_a_zone_asks_for_either_name():
    """The census behind the test above: Petra Sphinx is one of six places a
    chosen card name is compared against cards in a hand, a library or a
    graveyard, and the other five are reached by other cards."""
    import inspect

    from engine.handlers import zones
    from engine.mixins.stack import choices

    # The census half: every chosen-name comparison over a zone asks
    # ``has_name``. A raw ``card.name == named`` matches neither half's name
    # against "Burn // Grow" and so misses a card the rule says is named that.
    for module in (zones, choices):
        source = inspect.getsource(module)
        assert ".name == named" not in source, module.__name__
        assert ".name != named" not in source, module.__name__


# ---------------------------------------------------------------------------
# W2G4 — CR 709.3 under another player's control (CR 723.5)
# ---------------------------------------------------------------------------
#
# Word of Command forces the target to play a card the caster chose from their
# hand. For a split card "which card" is half an answer: CR 709.3 has the
# player casting choose the half, and CR 723.5 hands every choice the
# controlled player would make to the player controlling them. The forced cast
# used to name the whole card, which names no spell, so it was refused with
# "choose which half" and nothing was played — the choice had no channel.


def _w2g4_command(game, p0, p1, held):
    p0.hand.append(_POOL["Word of Command"])
    p1.hand.extend(held)
    assert game.cast_from_hand(0, "Word of Command", target_player_index=1).supported
    pending = game.pending_word_of_command
    assert pending is not None
    return pending


@pytest.mark.cr("709.3", "723.5")
def test_w2g4_the_controller_names_the_half_a_forced_split_card_is_cast_as():
    game, p0, p1 = _duel()
    _w2g4_command(game, p0, p1, [BURN_GROW])

    # Burn: the target's own instant, turned on them (the forced spell's target
    # defaults to the forced player).
    assert game.confirm_word_of_command(0, 0, spell_name="Burn") is True
    assert p1.life == 18 and p0.life == 20
    assert p1.hand == [] and BURN_GROW in p1.graveyard
    assert _no_half_is_loose(game)
    assert any("forced to play Burn" in line for line in game.log)
    assert game.pending_word_of_command is None


@pytest.mark.cr("709.3", "723.5")
def test_w2g4_the_other_half_is_the_other_spell():
    game, p0, p1 = _duel()
    _w2g4_command(game, p0, p1, [BURN_GROW])

    assert game.confirm_word_of_command(0, 0, spell_name="Grow") is True
    assert p1.life == 20, "Grow deals no damage — the half was not defaulted to the first"
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Elephant Token"]
    assert BURN_GROW in p1.graveyard and _no_half_is_loose(game)


@pytest.mark.cr("709.3")
def test_w2g4_a_forced_split_card_named_whole_is_not_an_answer():
    """No half named, or a name that is neither half: the prompt stays owed and
    nothing is played. There is no pick the engine could make here that is not
    the engine choosing for the caster."""
    game, p0, p1 = _duel()
    _w2g4_command(game, p0, p1, [BURN_GROW, _POOL["Lightning Bolt"]])

    for bad in (None, "Burn // Grow", "Lightning Bolt"):
        assert game.confirm_word_of_command(0, 0, spell_name=bad) is False
        assert game.pending_word_of_command is not None
        assert p1.hand == [BURN_GROW, _POOL["Lightning Bolt"]] and p1.life == 20

    # A card with one face needs no half, and a name sent with it is ignored.
    assert game.confirm_word_of_command(0, 1, spell_name="Burn") is True
    assert p1.life == 17 and p1.hand == [BURN_GROW]


@pytest.mark.cr("709.3", "723.5")
def test_w2g4_a_deferred_choice_remembers_the_half_across_a_priority_round():
    """The interactive path records the choice and lets the spell wait on the
    stack; the half has to wait with it."""
    game, p0, p1 = _duel()
    p0.hand.append(_POOL["Word of Command"])
    p1.hand.extend([_POOL["Forest"], BURN_GROW])
    game.interactive_seats = {0, 1}
    assert game.queue_from_hand(0, "Word of Command", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.pending_word_of_command is not None

    assert game.confirm_word_of_command(0, 1, defer_resolution=True) is False
    assert game.confirm_word_of_command(0, 1, defer_resolution=True, spell_name="Grow") is True
    assert BURN_GROW in p1.hand, "recorded, not yet played"

    # The target's hand changes while the spell waits: the card is re-found by
    # name and still cast as the half that was chosen.
    game.take_card_from_hand(p1, _POOL["Forest"])
    game.interactive_seats = set()
    resolve_stack(game)

    assert [perm.card.name for perm in game.controlled_by(1)] == ["Elephant Token"]
    assert p1.life == 20 and BURN_GROW in p1.graveyard
    assert _no_half_is_loose(game)


@pytest.mark.cr("709.3")
def test_w2g4_a_seat_that_is_not_asked_forces_the_first_half():
    """The default answer is the first card in the hand; for a split card it is
    that card's first half — the same deterministic default one level down,
    rather than a forced cast that names no spell and plays nothing."""
    game, p0, p1 = _duel()
    game.interactive_seats = {1}  # the caster's seat is not interactive
    p0.hand.append(_POOL["Word of Command"])
    p1.hand.append(BURN_GROW)

    assert game.cast_from_hand(0, "Word of Command", target_player_index=1).supported
    resolve_stack(game)

    assert game.pending_word_of_command is None
    assert p1.life == 18 and BURN_GROW in p1.graveyard
    assert not any("choose which half" in line for line in game.log)


# ---------------------------------------------------------------------------
# W2G4 — a permission scoped by a spell's characteristics judges the half
# ---------------------------------------------------------------------------
#
# CR 709.3a: "Only the chosen half is evaluated to see if it can be cast", and
# CR 709.3b: the spell has only that half's characteristics. A cast permission
# has two kinds of scope. *Which object* it covers — the card a grant named,
# the top card of a pile — is asked of the card as its zone holds it, whole.
# *What kind of spell* it covers — "instant spells with mana value 2 or less",
# "instant and sorcery spells" — is asked of the spell, and for a split card
# that is the half. Both were asked of the whole card, so Burn // Grow was a
# five-mana instant-and-sorcery to every such permission: too expensive for a
# waiver its one-mana half is entitled to, and a sorcery to a permission that
# names sorceries while the half being cast is an instant.
#
# No card in the pool prints a split card beside one of these today — which is
# why the fixtures are invented, and why nothing had failed.


def _w2g4_waiver(card_type: str, mana_value: int) -> CardDefinition:
    """Aluren's sentence with its two parameters turned
    (``cast_permissions.board_free_cast_line`` reads both as payload)."""
    return CardDefinition(
        name=f"Free {card_type.title()} Charter",
        mana_cost="{2}{G}{G}",
        cmc=4.0,
        type_line="Enchantment",
        oracle_text=(
            f"Any player may cast {card_type} spells with mana value {mana_value} "
            "or less without paying their mana costs and as though they had flash."
        ),
        colors=("G",),
        color_identity=("G",),
        keywords=(),
        produced_mana=(),
        raw={},
    )


def _w2g4_charter_game(charter):
    game, p0, p1 = _duel(enforce=True)
    game._put_permanent_onto_battlefield(1, Permanent(card=charter), None)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    p0.hand.append(BURN_GROW)
    return game, p0, p1


@pytest.mark.cr("709.3a", "709.3b")
def test_w2g4_a_mana_value_waiver_reads_the_halfs_mana_value():
    """Burn is an instant with mana value 1. The card it is half of has mana
    value 5 everywhere but the stack (CR 709.4b) — and the stack is where a
    spell is."""
    game, p0, p1 = _w2g4_charter_game(_w2g4_waiver("instant", 2))
    assert p0.mana_pool.get("R", 0) == 0 and not list(game.controlled_by(0))

    cast = game.queue_from_hand(0, "Burn", target_player_index=1)
    assert cast.supported, cast.details
    resolve_stack(game)
    assert p1.life == 18 and BURN_GROW in p0.graveyard


@pytest.mark.cr("709.3a", "709.3b")
def test_w2g4_a_waiver_for_another_type_does_not_reach_the_half():
    """The mirror, and the one that was wrong in the caster's favour: a waiver
    for *sorcery* spells of mana value 5 or less covered the whole card (a
    sorcery, mana value 5) and so made Burn — an instant — free."""
    game, p0, p1 = _w2g4_charter_game(_w2g4_waiver("sorcery", 5))

    burn = game.queue_from_hand(0, "Burn", target_player_index=1)
    assert not burn.supported, "Burn is not a sorcery spell; nothing waives its cost"
    assert p1.life == 20 and p0.hand == [BURN_GROW] and not game.stack

    # Grow *is* a sorcery of mana value 4, and the same waiver is its.
    grow = game.queue_from_hand(0, "Grow")
    assert grow.supported, grow.details
    resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Elephant Token"]


@pytest.mark.cr("709.3a", "709.3b")
def test_w2g4_a_typed_zone_permission_covers_the_half_of_that_type_only():
    """"You may cast instant spells from your graveyard": the card in the
    graveyard is an instant *and* a sorcery (CR 709.4c), the spell cast out of
    it is one or the other, and the permission is about the spell."""
    from engine.cast_permissions import grant_permission, playable_from_zones

    game, p0, p1 = _duel()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    p0.graveyard.append(BURN_GROW)
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        card_types=("instant",), duration="end_of_turn", source_name="Test Grant",
    )

    # Offered — one half is castable — and offered once, as the card.
    offered = [entry for entry in playable_from_zones(game, 0) if entry["zone"] == "graveyard"]
    assert [entry["name"] for entry in offered] == ["Burn // Grow"]

    grow = game.queue_from_hand(0, "Grow", from_zone="graveyard")
    assert not grow.supported and BURN_GROW in p0.graveyard and not game.stack

    burn = game.queue_from_hand(0, "Burn", from_zone="graveyard", target_player_index=1)
    assert burn.supported, burn.details
    assert game.stack[-1].card.name == "Burn" and BURN_GROW not in p0.graveyard
    resolve_stack(game)
    assert p1.life == 18 and _no_half_is_loose(game)


# ---------------------------------------------------------------------------
# W2G4 — what a mixed split card is, outside the stack (CR 709.4c)
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.4c")
def test_w2g4_a_mixed_split_card_has_both_types_and_one_primary_type():
    """``primary_type`` picks one type by the order of a list and answers
    "instant" for an Instant // Sorcery card. That is a *display* bucket — the
    deck builder's and the report's — and every reader that asks what a card
    in a zone **is** goes through ``card_has_type``, which answers for both.
    Pinned here because the two are easy to confuse, and the day a reader asks
    ``primary_type == "sorcery"`` of a card in a graveyard it will miss this
    one. (``tests/engine/test_face_blind_guards.py`` holds the same line for
    compiled text.)"""
    assert BURN_GROW.primary_type == "instant"
    assert card_has_type(BURN_GROW, "instant") and card_has_type(BURN_GROW, "sorcery")
    burn, grow = face_cards(BURN_GROW)
    assert (burn.primary_type, grow.primary_type) == ("instant", "sorcery")
    assert not card_has_type(burn, "sorcery") and not card_has_type(grow, "instant")
    # Where the one-type answer would do damage is the timing gate, and that
    # reads the half: ``tests/ui/test_split_cards_ui_api.py`` casts Quick and
    # is refused Slow on the opponent's turn.
