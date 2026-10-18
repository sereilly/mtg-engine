"""Buyback (CR 702.27a) against everything else that replaces where a resolved
spell's card goes.

    702.27a: "…'If the buyback cost was paid, put this spell into its owner's
    hand instead of into that player's graveyard as it resolves.'"

Three other things can have a say in that move, and buyback stands differently
to each:

* **A replacement of the same event** — the rider a graveyard cast is made
  under ("If a spell cast this way would be put into a graveyard, exile it
  instead", Bösium Strip) and a board-wide "If a card would be put into your
  graveyard from anywhere, exile that card instead" (Forbidden Crypt,
  Yawgmoth's Agenda; Yawgmoth's Will for a turn). CR 616.1: "If two or more
  replacement and/or prevention effects are attempting to modify the way an
  event affects an object or player, the affected object's controller … chooses
  one to apply". Yawgmoth's Will's ruling (Scryfall, 2004-10-04) states the
  case: "If you cast a Buyback spell, then there will be two effects trying to
  replace where the card goes. You get to choose if the Buyback returns the
  card to your hand or the card gets exiled."
* **Flashback** — CR 702.34a: "exile this card instead of putting it
  **anywhere else** any time it would leave the stack." Not a contest.
* **The turn ending** — CR 724.1b exiles the resolving object; the resolution
  buyback's clause is about never finishes.

``_bin_spell_card`` took one boolean for all three and answered the first one
two ways without asking: the rider always won (the tree before this file: every
bought-back spell cast under a rider was **exiled**, its buyback paid for
nothing) and the board-wide effect always lost (every one went to hand and the
seat was never asked). The census below casts every buyback card in the pool,
buyback paid, under each source, twice — a seat that is asked and a seat that
is not — with floors.

The pool is both manifest roles.
"""
from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import buyback_cost
from engine.cast_permissions import grant_permission
from engine.faces import compilation_units
from engine.flashback import granted_cost
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_BAIT_BOARD = (
    "Forest", "Forest", "Island", "Swamp", "Mountain", "Plains",
    "Grizzly Bears", "Grizzly Bears", "Sol Ring",
)
_BAIT_HAND = ("Grizzly Bears", "Black Knight", "Forest", "Island", "Swamp")

#: The sources of a competing replacement: the two riders a cast is made
#: under, and the three board-wide effects on the graveyard seam.
_CONTENDED = ("rider", "Bösium Strip", "Forbidden Crypt", "Yawgmoth's Agenda",
              "Yawgmoth's Will")


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _buyback_cards() -> list:
    return sorted(
        (
            unit for unit in compilation_units(_pool().values())
            if unit.face_of is None and compile_card_oracle(unit).supported
            and buyback_cost(unit.oracle_text or "")
        ),
        key=lambda unit: unit.name,
    )


def _board(card, source: str, *, asked: bool) -> tuple[Game, str]:
    """A board on which *card* can be cast with its buyback paid under
    *source*, and the zone it is cast from."""
    by_name = _pool()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    for name in _BAIT_BOARD:
        for seat in (0, 1):
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    # Something on the other side for "destroy target enchantment" to name
    # that is not the very permanent whose effect is under test.
    game._put_permanent_onto_battlefield(1, Permanent(card=by_name["Castle"]), None)
    for seat in (0, 1):
        game.players[seat].hand.extend(by_name[n] for n in _BAIT_HAND)
        game.players[seat].graveyard.extend(
            by_name[n] for n in ("Grizzly Bears", "Black Knight", "Mind Rot")
        )
        game.players[seat].library.extend([by_name["Forest"]] * 10)
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None

    zone = "hand"
    if source == "rider":
        game.players[0].graveyard.append(card)
        grant_permission(
            game, player_index=0, zone="graveyard", mode="cast", cards=[card],
            duration="end_of_turn", exile_instead=True, source_name="Test Rider",
        )
        zone = "graveyard"
    elif source == "flashback":
        game.players[0].graveyard.append(card)
        grant_permission(
            game, player_index=0, zone="graveyard", mode="cast", cards=[card],
            duration="end_of_turn", exile_instead=True,
            card_types=("instant", "sorcery"),
            cost=granted_cost(card, "mana_cost"), source_name="Test Recoup",
        )
        zone = "graveyard"
    elif source == "Bösium Strip":
        strip = Permanent(card=by_name["Bösium Strip"])
        game._put_permanent_onto_battlefield(0, strip, None)
        strip.metadata["summoning_sickness_turn"] = -99
        game.players[0].graveyard.append(card)
        activated = game.activate_permanent_ability(
            0, "Bösium Strip", permanent_index=next(
                index for index, permanent in enumerate(game.controlled_by(0))
                if permanent is strip
            ),
        )
        assert activated.supported, activated.details
        resolve_stack(game)
        zone = "graveyard"
    elif source in ("Forbidden Crypt", "Yawgmoth's Agenda"):
        game._put_permanent_onto_battlefield(0, Permanent(card=by_name[source]), None)
        game.players[0].hand.append(card)
    elif source == "Yawgmoth's Will":
        game.players[0].hand.append(by_name[source])
        assert game.cast_from_hand(0, source).supported
        game.players[0].hand.append(card)
    else:
        assert source == "none", source
        game.players[0].hand.append(card)
    if asked:
        game.interactive_seats = {0}
    return game, zone


def _announce(game, card, zone: str, offers: dict) -> dict:
    spec = game.cast_target_spec(
        0, card, from_zone=zone, optional_cost_payments=offers,
    )
    if spec.get("kind") == "stack":
        game.players[1].hand.append(_pool()["Giant Growth"])
        bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
        spec = game.cast_target_spec(
            0, card, from_zone=zone, optional_cost_payments=offers,
        )
    if spec.get("kind") == "divided":
        return {"divided_targets": [(1, None, int(spec.get("division_total") or 1))]}
    # The opposing side first: a spell aimed at its own caster's Forbidden
    # Crypt removes the effect this census is about before the last step.
    offered = sorted(
        spec.get("valid_targets") or [],
        key=lambda entry: entry.get("kind") != "graveyard" and entry.get("seat") != 1,
    )
    for entry in offered:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            return {
                "target_permanent_ids": [permanent.permanent_id],
                "target_player_index": entry["seat"],
            }
        if kind == "player":
            return {"target_player_index": entry["seat"]}
        if kind == "graveyard":
            return {
                "target_player_index": entry["seat"],
                "target_permanent_index": entry["index"],
            }
        if kind == "stack":
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    return {}


def _where(game, card) -> list[str]:
    """Every zone holding *card* — by identity."""
    found = []
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile", "library"):
            found += [f"P{seat + 1}.{zone}"] * sum(
                1 for held in getattr(player, zone) if held is card
            )
    found += ["stack"] * sum(1 for item in game.stack if item.card is card)
    return found


def _cast_bought_back(card, source: str, *, asked: bool):
    """Cast *card* with its buyback paid and resolve the spell itself.

    ``(game, where the card is, the effect-order prompt owed or None)`` — or
    None when this board cannot cast it that way at all.
    """
    game, zone = _board(card, source, asked=asked)
    offers = {buyback_cost(card.oracle_text or ""): 1}
    try:
        announcement = _announce(game, card, zone, offers)
        queued = game.queue_from_hand(
            0, card.name, from_zone=zone, optional_cost_payments=offers,
            **announcement,
        )
    except Exception:  # noqa: BLE001 - a board that cannot announce the card
        return None
    if not queued.supported:
        return None
    # The interactive path's resolution (``pass_priority``): a prompt a
    # resolution arms keeps the object on the stack until it is answered.
    for _ in range(8):
        if not any(item.card is card for item in game.stack):
            break
        if game.pending_choice_of("effect_order") is not None:
            break
        if not game.resolve_top_of_stack(pause_for_choices=True):
            # Something else the spell asked on its way (a discard, a search):
            # take the registry's default for **that** prompt and carry on.
            # One at a time, and never the effect-order prompt the answer may
            # arm behind it: that one is the subject.
            owed = next(
                (c for c in game.pending_choices if c.kind != "effect_order"), None
            )
            if owed is None:
                break
            game.take_choice_default(owed)
            game.discard_pending_choice(owed)
    return game, _where(game, card), game.pending_choice_of("effect_order")


@pytest.mark.cr("616.1", "616.1e", "702.27a")
@pytest.mark.parametrize("source", _CONTENDED)
def test_buyback_and_an_exile_instead_are_the_controllers_choice(source):
    cards = _buyback_cards()
    examined = 0
    not_asked, wrong_default, wrong_hand, wrong_exile, moved_early = [], [], [], [], []
    for card in cards:
        # A seat nobody asks takes the buyback it paid for.
        unasked = _cast_bought_back(card, source, asked=False)
        if unasked is None:
            continue
        examined += 1
        _game, where, prompt = unasked
        if where != ["P1.hand"] or prompt is not None:
            wrong_default.append(f"{card.name}: {where}")

        # A seat that is asked is asked — with nothing moved yet.
        for option, expected, bucket in ((0, ["P1.hand"], wrong_hand),
                                         (1, ["P1.exile"], wrong_exile)):
            game, where, prompt = _cast_bought_back(card, source, asked=True)
            if prompt is None:
                not_asked.append(f"{card.name}: {where}")
                break
            if where != ["stack"] or game.waiting_prompt is None:
                moved_early.append(f"{card.name}: {where}")
            assert prompt.player_index == 0
            assert prompt.data["event_kind"] == "bought_back_spell"
            assert len(prompt.data["options"]) >= 2
            assert prompt.data["options"][0].startswith("Buyback")
            assert game.resolve_pending_choice("effect_order", 0, option_index=option)
            if _where(game, card) != expected or game.pending_choice_of("effect_order"):
                bucket.append(f"{card.name}: {_where(game, card)}")

    assert not wrong_default, f"a seat not asked did not buy it back: {wrong_default}"
    assert not not_asked, f"a seat that should choose was not asked: {not_asked}"
    assert not moved_early, f"the card moved before the answer: {moved_early}"
    assert not wrong_hand, f"chose buyback, card went elsewhere: {wrong_hand}"
    assert not wrong_exile, f"chose the exile, card went elsewhere: {wrong_exile}"
    # Measured: 28 buyback cards, every one castable on this board with its
    # buyback paid, under every source.
    assert len(cards) >= 28, len(cards)
    assert examined >= 28, examined


@pytest.mark.cr("702.34a", "702.27a")
def test_a_flashed_back_spell_is_exiled_whatever_else_was_paid_and_nobody_is_asked():
    cards = _buyback_cards()
    examined, wrong = 0, []
    for card in cards:
        for asked in (False, True):
            result = _cast_bought_back(card, "flashback", asked=asked)
            if result is None:
                continue
            examined += 1
            _game, where, prompt = result
            if where != ["P1.exile"] or prompt is not None:
                wrong.append(f"{card.name} (asked={asked}): {where}")
    assert not wrong, wrong
    assert examined >= 56, examined


@pytest.mark.cr("702.27a")
def test_with_nothing_else_in_contention_a_bought_back_spell_goes_to_hand_unasked():
    cards = _buyback_cards()
    examined, wrong = 0, []
    for card in cards:
        result = _cast_bought_back(card, "none", asked=True)
        if result is None:
            continue
        examined += 1
        _game, where, prompt = result
        if where != ["P1.hand"] or prompt is not None:
            wrong.append(f"{card.name}: {where}")
    assert not wrong, wrong
    assert examined >= 28, examined


@pytest.mark.cr("724.1b", "702.27a")
def test_a_turn_that_ended_exiles_the_resolving_spell_buyback_or_not():
    """CR 724.1b is not a replacement effect, so CR 616.1 has nothing to ask:
    the bin site says which exile this is (``exile_is_final``)."""
    capsize = _pool()["Capsize"]
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.interactive_seats = {0}
    game._bin_spell_card(
        game.players[0], capsize, exile_instead=True, verb="resolved",
        hand_instead=True, exile_is_final=True, chooser_index=0,
    )
    assert _where(game, capsize) == ["P1.exile"]
    assert game.pending_choice_of("effect_order") is None


@pytest.mark.cr("702.27a")
def test_a_countered_bought_back_spell_is_not_bought_back():
    """"As it resolves": a spell that does not resolve goes where any other
    would — its owner's graveyard, or exile under the rider."""
    by_name = _pool()
    for source, expected in (("none", ["P1.graveyard"]), ("rider", ["P1.exile"])):
        game, zone = _board(by_name["Capsize"], source, asked=True)
        ring = next(p for p in game.controlled_by(1) if p.card.name == "Sol Ring")
        assert game.queue_from_hand(
            0, "Capsize", from_zone=zone, optional_cost_payments={"{3}": 1},
            target_permanent_ids=[ring.permanent_id], target_player_index=1,
        ).supported
        game.players[1].hand.append(by_name["Counterspell"])
        assert game.cast_from_hand(
            1, "Counterspell", target_stack_index=len(game.stack) - 1,
        ).supported
        assert _where(game, by_name["Capsize"]) == expected, source
        assert game.pending_choice_of("effect_order") is None
