"""Census: a target named **without an id** is held to the picker's list.

CR 601.2c: "The player announces their choice of an appropriate object or
player for each target the spell requires." ``legality.cast_target_refusal``
compared a named *permanent* and a named graveyard slot with the list
``_enumerate_targets`` hands the picker, and compared nothing else. Two
channels carry a target with no ``permanent_id`` and were read by nobody:

* **a seat** — ``target_player_index`` is a chosen player in one arrangement
  and the battlefield a permanent sits on in another, which is why the gate
  left it alone. So every narrowing a player phrase prints was the picker's
  and nobody else's: "target **opponent**" was castable at the caster (Duress,
  Coercion, Bribery, Word of Command: 34 shipped spells), and a player with
  shroud (Ivory Mask, CR 702.18a) or one who had left the game could be named
  by any of the 181 spells in the pool that can target a player. Lightning
  Bolt dealt its 3 from behind the Mask.
* **a divided list** (CR 601.2d) — each entry is a target, a face where its
  slot is None, and the cast path only bounds-checked it: "divided as you
  choose among any number of target **creatures**" was announceable at a
  Forest, at a creature with protection from the spell's colour, or at a face.

Each sweep below names, in turn, **everything** its channel can name on four
tables — a plain one, one where each seat in turn has shroud, and a three-seat
one with a player gone — and requires the two halves of one statement: what the
picker offers is accepted (the control arm, which is what stops a gate that
refuses everything from passing), and what it does not offer is refused.

Validated backwards on the tree before the gate: 591 of 774 unoffered seats
accepted across 181 cards, and 1,115 of 1,283 unoffered division entries
across 19. The activation side was closed a round earlier
(``activation_target_refusal``'s ``names_a_seat``) and is pinned here at 0 of
696, because it is the same statement and nothing else in the suite makes it
over the pool.

The floors are what stop a later filter from making a sweep pass by examining
nothing.
"""

from __future__ import annotations

from functools import lru_cache

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

_PLAYER_KINDS = frozenset({"player", "any", "player_or_planeswalker", "divided"})
SCENARIOS = ("plain", "opponent_shroud", "caster_shroud", "three_seats_one_lost")

_BOARD = ("Grizzly Bears", "Black Knight", "Forest", "Island", "Sol Ring", "Castle")
_YARD = ("Hill Giant", "Lightning Bolt", "Ornithopter", "Holy Strength", "Swamp")
_HAND = ("Scryb Sprites", "Mountain", "Giant Growth")
_LIBRARY = (
    "Forest", "Craw Wurm", "Plains", "Counterspell", "Mox Pearl", "Swamp",
    "Mountain", "Island", "Serra Angel", "Terror",
)

# 199 announcements on 181 cards; 768 unoffered seats and 999 offered ones over
# the four tables (October 2026). Floors, not equalities: the pool grows.
_MIN_ANNOUNCEMENTS = 190
_MIN_UNOFFERED_SEATS = 720
_MIN_OFFERED_SEATS = 940
_MIN_UNOFFERED_ENTRIES = 1150
_MIN_OFFERED_ENTRIES = 1000
_MIN_ABILITIES = 170
_MIN_UNOFFERED_ABILITY_SEATS = 640
_MIN_OFFERED_ABILITY_SEATS = 600


@lru_cache(maxsize=1)
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _guard(name: str, text: str) -> CardDefinition:
    kind = "Artifact Creature — Golem"
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0, type_line=kind, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": kind, "power": "3", "toughness": "3"},
    )


#: Permanents a division must not be announced at, beside the lands and the
#: enchantment already on the table: shroud, and protection from each colour.
_GUARDED = tuple(
    _guard(f"Census {label}", text)
    for label, text in (
        ("Shroud", "Shroud"),
        ("Pro White", "Protection from white"),
        ("Pro Blue", "Protection from blue"),
        ("Pro Black", "Protection from black"),
        ("Pro Red", "Protection from red"),
        ("Pro Green", "Protection from green"),
    )
)


def table(scenario: str, hand_card=None, *, guarded: bool = False) -> Game:
    """A table for *scenario* with *hand_card* in seat 0's hand.

    Something of every kind is on each battlefield and in each graveyard, so a
    spell's additional cost and its other sentences have what they need and a
    refusal is about the target that was named.
    """
    cards = pool()

    def named(names):
        return [cards[name] for name in names]

    seats = 3 if scenario == "three_seats_one_lost" else 2
    players = [
        PlayerState(
            "ABC"[seat], library=named(_LIBRARY) * 2,
            hand=([hand_card] if seat == 0 and hand_card is not None else []) + named(_HAND),
            graveyard=named(_YARD),
        )
        for seat in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat in range(seats):
        for symbol in "WUBRG":
            game.players[seat].mana_pool[symbol] = 20
        for card in named(_BOARD) + (list(_GUARDED) if guarded else []):
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    if scenario == "opponent_shroud":
        game._put_permanent_onto_battlefield(1, Permanent(card=cards["Ivory Mask"]), None)
    if scenario == "caster_shroud":
        game._put_permanent_onto_battlefield(0, Permanent(card=cards["Ivory Mask"]), None)
    if scenario == "three_seats_one_lost":
        game.players[2].lost = True
    return game


def kickers(game: Game, card) -> dict:
    """Every optional additional cost *card* offers, taken once, so a target
    printed only in a kicked part (CR 702.33g) is one the sweep reaches."""
    taken = {}
    for offer in game.cast_cost_offers(0, card, from_zone="hand") or ():
        key = offer.get("key") or offer.get("symbols")
        if key and offer.get("kind") != "alternative":
            taken[key] = 1
    return taken


@lru_cache(maxsize=1)
def player_spell_rows() -> tuple:
    """``(card, mode index, spec kind)`` for every instant or sorcery
    announcement whose target may be a player."""
    rows = []
    for card in sorted(pool().values(), key=lambda entry: entry.name):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if program.modes and program.mode_chooser is not None:
            continue  # CR 700.2e: its targets are named after an opponent's choice
        for mode in (range(len(program.modes)) if program.modes else (None,)):
            spec = derive_cast_spec(card, program, mode_index=mode)
            if spec and spec.get("kind") in _PLAYER_KINDS:
                rows.append((card, mode, spec.get("kind")))
    return tuple(rows)


def cast_keywords(card, mode, payments) -> dict:
    keywords: dict = {}
    if mode is not None:
        keywords["mode_index"] = mode
    if payments:
        keywords["optional_cost_payments"] = payments
    if "{X}" in (card.mana_cost or ""):
        keywords["x_value"] = 1
    return keywords


def offered_seats(spec: dict) -> set:
    return {
        entry.get("seat") for entry in spec.get("valid_targets") or ()
        if entry.get("kind") == "player"
    }


def test_h1_no_cast_accepts_a_seat_its_picker_does_not_offer():
    """CR 601.2c for a named **player**: on every table, a cast naming a seat
    is accepted exactly when the picker offers that seat."""
    rows = player_spell_rows()
    assert len(rows) >= _MIN_ANNOUNCEMENTS, len(rows)
    unoffered = offered = 0
    accepted_illegal: list[str] = []
    refused_legal: dict[str, set] = {}

    for card, mode, kind in rows:
        for scenario in SCENARIOS:
            probe = table(scenario, card)
            payments = kickers(probe, card)
            spec = probe.cast_target_spec(
                0, card, mode_index=mode, optional_cost_payments=payments,
            )
            if spec.get("kind") not in _PLAYER_KINDS:
                continue  # an unkicked cast of a kicked-only target, say
            legal = offered_seats(spec)
            for seat in range(len(probe.players)):
                game = table(scenario, card)
                result = game.queue_from_hand(
                    0, card.name, target_player_index=seat,
                    **cast_keywords(card, mode, payments),
                )
                where = f"{card.name}{'' if mode is None else f' #{mode}'} [{kind}, {scenario}] seat {seat}"
                if seat in legal:
                    offered += 1
                    if not result.supported:
                        refused_legal.setdefault(card.name, set()).add(result.details)
                    continue
                unoffered += 1
                if result.supported:
                    accepted_illegal.append(where)

    assert unoffered >= _MIN_UNOFFERED_SEATS, unoffered
    assert offered >= _MIN_OFFERED_SEATS, offered
    assert not accepted_illegal, (len(accepted_illegal), accepted_illegal[:20])
    # The control arm. A legal seat may still be refused for a reason that is
    # not the seat's — a printed count this one-target announcement misses
    # (Cone of Flame's three), a cost the table cannot pay (Goblin Grenade's
    # Goblin). What it may never be is this gate's own refusal.
    wrongly_refused = {
        name: sorted(reason for reason in reasons if _is_a_target_refusal(reason))
        for name, reasons in refused_legal.items()
        if any(_is_a_target_refusal(reason) for reason in reasons)
    }
    assert not wrongly_refused, wrongly_refused


def _is_a_target_refusal(reason: str) -> bool:
    """Whether *reason* is ``cast_target_refusal`` declining a named target."""
    return reason.startswith("no valid target") or "has to name its target" in reason


def test_h1_no_divided_cast_accepts_an_entry_its_picker_does_not_offer():
    """CR 601.2d through CR 601.2c: each entry of a division is a target, and
    is accepted exactly when the picker offers it — a face or a permanent."""
    unoffered = offered = 0
    accepted_illegal: list[str] = []
    refused_legal: dict[str, set] = {}
    cards_examined = set()

    for card, mode, kind in player_spell_rows():
        if kind != "divided":
            continue
        for scenario in SCENARIOS:
            probe = table(scenario, card, guarded=True)
            spec = probe.cast_target_spec(0, card, mode_index=mode)
            if spec.get("kind") != "divided":
                continue
            cards_examined.add(card.name)
            legal = {
                (entry.get("seat"), entry.get("index") if entry.get("kind") == "permanent" else None)
                for entry in spec.get("valid_targets") or ()
            }
            candidates = [(seat, None) for seat in range(len(probe.players))]
            for seat, player in enumerate(probe.players):
                candidates += [(seat, index) for index in range(len(player.battlefield))]
            for candidate in candidates:
                game = table(scenario, card, guarded=True)
                result = game.queue_from_hand(
                    0, card.name, divided_targets=[candidate],
                    **cast_keywords(card, mode, {}),
                )
                if candidate in legal:
                    offered += 1
                    if not result.supported:
                        refused_legal.setdefault(card.name, set()).add(result.details)
                    continue
                unoffered += 1
                if result.supported:
                    what = (
                        "a face" if candidate[1] is None
                        else probe.players[candidate[0]].battlefield[candidate[1]].card.name
                    )
                    accepted_illegal.append(f"{card.name} [{scenario}] at {what}")

    assert len(cards_examined) >= 18, sorted(cards_examined)
    assert unoffered >= _MIN_UNOFFERED_ENTRIES, unoffered
    assert offered >= _MIN_OFFERED_ENTRIES, offered
    assert not accepted_illegal, (len(accepted_illegal), accepted_illegal[:20])
    # A legal entry refused is refused for the division's own arithmetic: a
    # printed number of targets this one-entry list misses (Cone of Flame's
    # three, Firestorm's X), or an X the table cannot define.
    for name, reasons in refused_legal.items():
        assert all(
            "CR 601.2c" in reason or "CR 601.2d" in reason or "X cannot be determined" in reason
            for reason in reasons
        ), (name, sorted(reasons))


def test_h1_no_activation_accepts_a_seat_its_picker_does_not_offer():
    """CR 602.2b through CR 601.2c: the same statement for an activated
    ability whose target may be a player. Closed a round before this file
    (``activation_target_refusal``); pinned here because it is one rule."""
    abilities = unoffered = offered = 0
    accepted_illegal: list[str] = []

    for card in sorted(pool().values(), key=lambda entry: entry.name):
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or not program.activated_abilities:
            continue
        for scenario in SCENARIOS:
            probe = table(scenario)
            source = Permanent(card=card)
            probe._put_permanent_onto_battlefield(0, source, None)
            if not probe.is_on_battlefield(source):
                continue  # an entry replacement binned it (Kjeldoran Outpost)
            index = probe.battlefield_index_of(source)
            usable = probe.usable_abilities_of(source, card=source.effective_card)
            for ability_index in range(len(usable)):
                spec = probe.activation_target_spec(0, index, ability_index)
                if spec.get("kind") not in _PLAYER_KINDS:
                    continue
                abilities += scenario == "plain"
                legal = offered_seats(spec)
                for seat in range(len(probe.players)):
                    game = table(scenario)
                    permanent = Permanent(card=card)
                    game._put_permanent_onto_battlefield(0, permanent, None)
                    permanent.metadata["summoning_sickness_turn"] = -99
                    result = game.queue_permanent_ability(
                        0, card.name, target_player_index=seat,
                        permanent_index=game.battlefield_index_of(permanent),
                        ability_index=ability_index, x_value=1,
                    )
                    if seat in legal:
                        offered += result.supported
                        continue
                    unoffered += 1
                    if result.supported:
                        accepted_illegal.append(
                            f"{card.name} ability {ability_index} [{scenario}] seat {seat}"
                        )

    assert abilities >= _MIN_ABILITIES, abilities
    assert unoffered >= _MIN_UNOFFERED_ABILITY_SEATS, unoffered
    assert offered >= _MIN_OFFERED_ABILITY_SEATS, offered
    assert not accepted_illegal, (len(accepted_illegal), accepted_illegal[:20])
