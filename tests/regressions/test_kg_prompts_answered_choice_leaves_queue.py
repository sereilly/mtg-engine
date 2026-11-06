"""Census: an accepted answer takes its choice off the prompt queue — every kind.

Urza's Destiny (W2G5) found ``_resolve_pay_any_amount`` leaving its own choice
queued once a person had answered it. ``auto_resolve_pending_choices`` drops a
defaulted choice itself, so AI and headless play never saw it; a *confirmed*
one stayed, ``waiting_prompt`` reads the queue, and the game refused every
further action by the seat that had already answered (CR 117.3b) while the
object it belonged to never left the stack (CR 608.2). The round listed
nineteen more kinds "with the same shape" from a reading of the resolvers.

This file is the per-kind probe that entry asked for, run as a game. For every
kind in the registry (``engine/mixins/stack/choices/table.py``) a shipped card
arms the prompt for an **interactive** seat on a real board — one kind,
``graveyard_pile_choice``, no compiled card reaches, and it is driven over the
instruction that does — and the prompt is answered three ways: through the
registry's own answer path (``resolve_pending_choice``, or
``resolve_replacement_choice`` for the CR 614 queue), through
``POST /api/sessions/{id}/action`` (the route a person's click takes), and by
the default an engine-played seat takes (``take_choice_default``). After each
answer it asks:

(a) is the answered choice gone from the queue it was on (or, for the one kind
    that keeps a closed choice queued on purpose, no longer open)?
(b) is the seat that answered refused its next action by the prompt it has
    already answered — on the engine's gate and on the wire?
(c) did whatever the prompt was holding carry on — the object it held left the
    stack or is held by a newer prompt, and the effect the answer was for
    happened (each scenario's ``then``)?

Measured at the base of round ``kg``: nothing wedges, on any kind. The nineteen
were resolvers whose discard is not spelled inside the resolver body — it is in
a helper (``_record_player_choice``, ``_record_cast_choice``), in a module
outside ``choices/`` (``entry_choices.py``, ``effects.py``), or made by the
CR 614 queue before the resolver runs (``resolve_replacement_choice`` pops
first). A probe over every existing test that answers a prompt (1,495 test
items, 78 kinds, 2,281 accepted answers, 2,045 of them an interactive seat's)
found no accepted answer that left its choice open; the only choices left
queued were Word of Command's, closed, by design.

So the guarantee moved into the queue (``PendingChoicesMixin._close_answered_choice``),
and the tests at the bottom validate the census backwards by putting the
original defect back into every kind on the main queue: with the seam switched
off the census names each one, with it on the game goes on.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.mixins.stack.choices.queue import PendingChoicesMixin
from engine.models import Permanent
from engine.pending_choices import CHOICE_SPECS, spec_for
from engine.replacement_choices import CHOICE_RESOLVERS
from web.app import app, store
from web.prompts import blocking_prompt

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def card(name: str):
    return _CARDS[name]


def perm(name: str, *, tapped: bool = False) -> Permanent:
    permanent = Permanent(card=card(name), tapped=tapped)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def duel(
    *,
    hands=((), ()),
    boards=((), ()),
    libraries=None,
    graveyards=None,
    life=None,
    seats: int = 2,
) -> Game:
    """Every seat interactive (the web route makes every human seat so), seat 0
    active in its precombat main phase with priority."""
    def per_seat(given, empty):
        given = tuple(given) if given is not None else ()
        return given + (empty,) * (seats - len(given))

    hands, boards = per_seat(hands, ()), per_seat(boards, ())
    libraries = per_seat(libraries, ("Island",) * 8)
    graveyards = per_seat(graveyards, ())
    life = per_seat(life, 20)
    players = [
        PlayerState(
            name=f"P{seat}",
            life=life[seat],
            hand=[card(n) for n in hands[seat]],
            library=[card(n) for n in libraries[seat]],
            graveyard=[card(n) for n in graveyards[seat]],
            battlefield=[
                entry if isinstance(entry, Permanent) else perm(entry)
                for entry in boards[seat]
            ],
        )
        for seat in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(range(seats))
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def on_board(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def names(cards) -> list[str]:
    return [c.name for c in cards]


# ---------------------------------------------------------------------------
# The scenario table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    """One kind, armed by one card for an interactive seat.

    ``answer`` is the registry's response (the keys the kind's ``resolve`` row
    reads); ``wire`` is what the client's control sends beside ``seat`` and
    ``action``; ``then`` asserts what the answer was for.
    """

    kind: str
    card: str
    arm: Callable[[], Game]
    answer: Callable[[Game, Any], dict]
    wire: Callable[[Game, Any], dict]
    then: Callable[[Game], None] | None = None


SCENARIOS: dict[str, Scenario] = {}


def scenario(kind: str, card_name: str, *, answer, wire, then=None):
    def register(arm):
        assert kind in CHOICE_SPECS, kind
        assert kind not in SCENARIOS, kind
        SCENARIOS[kind] = Scenario(kind, card_name, arm, answer, wire, then)
        return arm
    return register


# -- library ---------------------------------------------------------------

@scenario(
    "hand_to_library", "Brainstorm",
    answer=lambda g, c: {"hand_indices": [0, 1]},
    wire=lambda g, c: {"hand_indices": [0, 1]},
    then=lambda g: _assert(len(g.players[0].hand) == 1 and len(g.players[0].library) == 7),
)
def _brainstorm():
    game = duel(hands=(("Brainstorm",), ()))
    game.cast_from_hand(0, "Brainstorm")
    return game


@scenario(
    "search_library", "Demonic Tutor",
    answer=lambda g, c: {"library_index": _index_of(g, 0, "Grizzly Bears")},
    wire=lambda g, c: {"hand_index": _index_of(g, 0, "Grizzly Bears")},
    then=lambda g: _assert(names(g.players[0].hand) == ["Grizzly Bears"]),
)
def _demonic_tutor():
    game = duel(
        hands=(("Demonic Tutor",), ()),
        libraries=(("Island", "Grizzly Bears", "Island"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Demonic Tutor")
    return game


def _cultivate():
    game = duel(
        hands=(("Cultivate",), ()),
        libraries=(("Forest", "Island", "Grizzly Bears"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Cultivate")
    library = names(game.players[0].library)
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Forest")},
        {"zone": "library", "index": library.index("Island")},
    ])
    return game


scenario(
    "search_destination", "Cultivate",
    answer=lambda g, c: {"assignments": [0, 1]},
    wire=lambda g, c: {"search_assignments": [0, 1]},
    then=lambda g: _assert(
        names(g.players[0].hand) == ["Island"]
        and [p.card.name for p in g.controlled_by(0)] == ["Forest"]
    ),
)(_cultivate)


@scenario(
    "look_top_pick", "Impulse",
    answer=lambda g, c: {"keep_index": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _assert(len(g.players[0].hand) == 1),
)
def _impulse():
    game = duel(
        hands=(("Impulse",), ()),
        libraries=(("Grizzly Bears", "Forest", "Island", "Swamp", "Mountain"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Impulse")
    return game


@scenario(
    "search_exile_cards", "Mana Severance",
    answer=lambda g, c: {"picks": [{"zone": "library", "index": _index_of(g, 0, "Forest")}]},
    wire=lambda g, c: {"search_picks": [{"zone": "library", "index": _index_of(g, 0, "Forest")}]},
    then=lambda g: _assert(names(g.players[0].exile) == ["Forest"]),
)
def _mana_severance():
    game = duel(
        hands=(("Mana Severance",), ()),
        libraries=(("Grizzly Bears", "Forest", "Grizzly Bears"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Mana Severance")
    return game


@scenario(
    "reorder_library", "Portent",
    answer=lambda g, c: {"new_order": [2, 1, 0], "shuffle": False},
    wire=lambda g, c: {"card_order": [2, 1, 0], "shuffle": False},
    then=lambda g: _assert(names(g.players[1].library[:3]) == ["Swamp", "Forest", "Grizzly Bears"]),
)
def _portent():
    game = duel(
        hands=(("Portent",), ()),
        libraries=(("Island",) * 4, ("Grizzly Bears", "Forest", "Swamp", "Island")),
    )
    game.cast_from_hand(0, "Portent", target_player_index=1)
    return game


@scenario(
    "scry", "Opt",
    answer=lambda g, c: {"card_order": [0], "bottom_count": 1},
    wire=lambda g, c: {"card_order": [0], "bottom_count": 1},
    # Scry 1 bottoms the Bears, and "Draw a card." — the step behind the
    # answer — draws the Forest under it.
    then=lambda g: _assert(
        names(g.players[0].hand) == ["Forest"]
        and g.players[0].library[-1].name == "Grizzly Bears"
    ),
)
def _opt():
    game = duel(
        hands=(("Opt",), ()),
        libraries=(("Grizzly Bears", "Forest", "Island"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Opt")
    return game


@scenario(
    "revealed_hand_pick", "Duress",
    answer=lambda g, c: {"hand_index": names(g.players[1].hand).index("Shock")},
    wire=lambda g, c: {"hand_index": names(g.players[1].hand).index("Shock")},
    then=lambda g: _assert(names(g.players[1].graveyard) == ["Shock"]),
)
def _duress():
    game = duel(hands=(("Duress",), ("Grizzly Bears", "Shock", "Forest")))
    game.cast_from_hand(0, "Duress", target_player_index=1)
    return game


def _intuition():
    game = duel(
        hands=(("Intuition",), ()),
        libraries=(("Grizzly Bears", "Shock", "Forest", "Island"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Intuition", target_player_index=1)
    library = names(game.players[0].library)
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index(n)}
        for n in ("Grizzly Bears", "Shock", "Forest")
    ])
    return game


scenario(
    "opponent_picks_revealed", "Intuition",
    answer=lambda g, c: {"index": 0},
    wire=lambda g, c: {"pile_index": 0},
    then=lambda g: _assert(
        len(g.players[0].hand) == 1
        and sorted(names(g.players[0].graveyard)) == sorted(
            {"Grizzly Bears", "Shock", "Forest", "Intuition"} - set(names(g.players[0].hand))
        )
    ),
)(_intuition)


@scenario(
    "discard", "Mind Rot",
    answer=lambda g, c: {"hand_indices": [0, 2], "to_library": False},
    wire=lambda g, c: {"discard_indices": [0, 2]},
    then=lambda g: _assert(
        names(g.players[1].hand) == ["Shock"]
        and sorted(names(g.players[1].graveyard)) == ["Forest", "Grizzly Bears"]
    ),
)
def _mind_rot():
    game = duel(hands=(("Mind Rot",), ("Grizzly Bears", "Shock", "Forest")))
    game.cast_from_hand(0, "Mind Rot", target_player_index=1)
    return game


# -- permanents, colours, payments ----------------------------------------

@scenario(
    "balance", "Balance",
    answer=lambda g, c: {"land_indices": [], "creature_indices": [], "hand_indices": [0, 1]},
    wire=lambda g, c: {"discard_indices": [0, 1]},
    then=lambda g: _assert(g.players[1].hand == [] and "Balance" in names(g.players[0].graveyard)),
)
def _balance():
    game = duel(hands=(("Balance",), ("Grizzly Bears", "Shock")))
    game.cast_from_hand(0, "Balance")
    return game


@scenario(
    "sacrifice", "Diabolic Edict",
    answer=lambda g, c: {"indices": [_slot(g, 1, "Grizzly Bears")]},
    wire=lambda g, c: {"sacrifice_indices": [_slot(g, 1, "Grizzly Bears")]},
    then=lambda g: _assert(
        names(g.players[1].graveyard) == ["Grizzly Bears"]
        and [p.card.name for p in g.controlled_by(1)] == ["Hill Giant"]
    ),
)
def _diabolic_edict():
    game = duel(hands=(("Diabolic Edict",), ()), boards=((), ("Grizzly Bears", "Hill Giant")))
    game.cast_from_hand(0, "Diabolic Edict", target_player_index=1)
    return game


@scenario(
    "mana_color_choice", "Star Compass",
    answer=lambda g, c: {"color": "B"},
    wire=lambda g, c: {"mana_color": "B"},
    then=lambda g: _assert(g.players[0].mana_pool.get("B") == 1),
)
def _star_compass():
    game = duel(boards=(("Island", "Swamp", "Star Compass"), ()))
    compass = on_board(game, 0, "Star Compass")
    game.activate_permanent_ability(
        0, "Star Compass", permanent_index=game.battlefield_index_of(compass),
    )
    return game


def _dream_coat():
    from engine.aura_attachment import attach_aura

    game = duel(boards=(("Grizzly Bears", "Dream Coat"), ()))
    attach_aura(on_board(game, 0, "Dream Coat"), on_board(game, 0, "Grizzly Bears"))
    coat = on_board(game, 0, "Dream Coat")
    game.activate_permanent_ability(0, "Dream Coat", permanent_index=game.battlefield_index_of(coat))
    return game


scenario(
    "color_set_choice", "Dream Coat",
    answer=lambda g, c: {"colors": ["U"]},
    wire=lambda g, c: {"mana_colors": ["U"]},
    then=lambda g: _assert(_colors(on_board(g, 0, "Grizzly Bears")) == {"U"}),
)(_dream_coat)


@scenario(
    "revealed_draw_buyout", "Zur's Weirding",
    answer=lambda g, c: {"accept": True},
    wire=lambda g, c: {"accept": True},
    then=lambda g: _assert(
        g.players[0].hand == [] and names(g.players[0].graveyard) == ["Grizzly Bears"]
        and g.players[1].life == 18
    ),
)
def _zurs_weirding():
    game = duel(boards=(("Zur's Weirding",), ()), libraries=(("Grizzly Bears",) * 3, ("Island",) * 3))
    game._draw_with_replacements(game.players[0], 1)
    return game


@scenario(
    "pay_life_to_save", "Cleansing",
    answer=lambda g, c: {"accept": True},
    wire=lambda g, c: {"accept": True},
    then=lambda g: _assert(sum(p.life for p in g.players) == 39),
)
def _cleansing():
    game = duel(hands=(("Cleansing",), ()), boards=(("Forest",), ()))
    game.cast_from_hand(0, "Cleansing")
    return game


@scenario(
    "optional_pay", "Wooden Sphere",
    answer=lambda g, c: {"accept": True},
    wire=lambda g, c: {"accept": True},
    then=lambda g: _assert(g.players[1].life == 21),
)
def _wooden_sphere():
    game = duel(
        hands=(("Grizzly Bears",), ()),
        boards=((), ("Wooden Sphere", "Forest")),
    )
    game.cast_from_hand(0, "Grizzly Bears")
    return game


@scenario(
    "trigger_target", "Gravedigger",
    answer=lambda g, c: {"seat": 0, "graveyard_index": 0},
    wire=lambda g, c: {"target_seat": 0, "graveyard_index": 0},
    # The announcement is finished: the trigger is on the stack with the card
    # it named, waiting for priority like any other object (CR 603.3d).
    then=lambda g: _assert(
        g.stack and g.stack[-1].is_ability and not g.stack[-1].resolution_held
        and "Gravedigger: targets Grizzly Bears in P0's graveyard" in g.log
    ),
)
def _gravedigger():
    game = duel(hands=(("Gravedigger",), ()), graveyards=(("Grizzly Bears",), ()))
    game.cast_from_hand(0, "Gravedigger")
    return game


@scenario(
    "copy_spell_target", "Fork",
    answer=lambda g, c: {"seat": 1},
    wire=lambda g, c: {"target_seat": 1},
    then=lambda g: _resolved_then(g, lambda: _assert(
        (g.players[0].life, g.players[1].life) == (17, 17)
    )),
)
def _fork():
    game = duel(hands=(("Fork", "Lightning Bolt"), ()))
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Fork", target_stack_index=0)
    return game


@scenario(
    "discard_unless_pay_life", "Breathstealer's Crypt",
    answer=lambda g, c: {"accept": True},
    wire=lambda g, c: {"accept": True},
    then=lambda g: _assert(names(g.players[0].hand) == ["Grizzly Bears"] and g.players[0].life == 17),
)
def _breathstealers_crypt():
    game = duel(
        boards=(("Breathstealer's Crypt",), ()),
        libraries=(("Grizzly Bears",) * 3, ("Island",) * 3),
    )
    game._draw_with_replacements(game.players[0], 1)
    return game


@scenario(
    "hand_reveal", "Glasses of Urza",
    answer=lambda g, c: {},
    wire=lambda g, c: {},
    then=lambda g: _assert(g.pending_hand_reveal is None),
)
def _glasses_of_urza():
    game = duel(boards=(("Glasses of Urza",), ()), hands=((), ("Shock",)))
    glasses = on_board(game, 0, "Glasses of Urza")
    game.activate_permanent_ability(
        0, "Glasses of Urza", permanent_index=game.battlefield_index_of(glasses),
        target_player_index=1,
    )
    return game


@scenario(
    "face_down_look", "(Aven Soulgazer is Onslaught's, measured — its instruction)",
    answer=lambda g, c: {},
    wire=lambda g, c: {},
    then=lambda g: _assert(g.pending_choice_of("face_down_look", 0) is None),
)
def _face_down_look():
    """"Look at target face-down creature." No shipped card prints it — the
    first is Onslaught's Aven Soulgazer, a measured set this pool-wide census
    does not load — so it is driven over the instruction the card lowers to,
    aimed at a face-down Grizzly Bears, the way ``graveyard_pile_choice`` is."""
    from engine.face_down import face_down_card
    from engine.game_types import OracleExecutionContext
    from engine.oracle_types import OracleInstruction

    hidden = Permanent(card=face_down_card(card("Grizzly Bears")))
    hidden.metadata["summoning_sickness_turn"] = -99
    game = duel(boards=(("Craw Wurm",), (hidden,)))
    source = on_board(game, 0, "Craw Wurm")
    instruction = OracleInstruction("look_at_target_face_down", "", {
        "type_filter": "creature", "face_down_only": True,
    })
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=source.card,
        source_permanent=source, target_permanent_id=[hidden.permanent_id],
    )
    game._execute_oracle_instruction(instruction, context)
    return game


@scenario(
    "draw_up_to", "Truce",
    answer=lambda g, c: {"number": 1},
    wire=lambda g, c: {"number": 1},
    # One card fewer than two is 2 life, once the other seat has answered too.
    then=lambda g: _finished_then(g, lambda: _assert(
        len(g.players[0].hand) == 1 and g.players[0].life == 22
    )),
)
def _truce():
    game = duel(hands=(("Truce",), ()))
    game.cast_from_hand(0, "Truce")
    return game


@scenario(
    "pay_any_amount", "Liege of the Hollows",
    answer=lambda g, c: {"amount": 1},
    wire=lambda g, c: {"number": 1},
    # One mana paid, one Squirrel — once the other seat has answered too.
    then=lambda g: _finished_then(g, lambda: _assert(
        sum(1 for p in g.controlled_by(0) if "Squirrel" in p.card.name) == 1
    )),
)
def _liege_of_the_hollows():
    game = duel(
        boards=(("Liege of the Hollows", "Forest"), ("Forest",)),
        hands=(("Terror",), ()),
    )
    game.cast_from_hand(0, "Terror", target_permanent_ids=[
        on_board(game, 0, "Liege of the Hollows").permanent_id
    ])
    return game


@scenario(
    "number_choice", "Shapeshifter",
    answer=lambda g, c: {"number": 5},
    wire=lambda g, c: {"number": 5},
    then=lambda g: _resolved_then(g, lambda: _assert(
        (on_board(g, 0, "Shapeshifter").effective_power,
         on_board(g, 0, "Shapeshifter").effective_toughness) == (5, 2)
    )),
)
def _shapeshifter():
    game = duel(hands=(("Shapeshifter",), ()))
    game.cast_from_hand(0, "Shapeshifter")
    return game


@scenario(
    "secret_number", "Goblin Game",
    answer=lambda g, c: {"number": 1},
    wire=lambda g, c: {"number": 1},
    then=lambda g: _finished_then(g, lambda: _assert(
        g.players[0].life < 20 and "Goblin Game" in names(g.players[0].graveyard)
    )),
)
def _goblin_game():
    game = duel(hands=(("Goblin Game",), ()))
    game.cast_from_hand(0, "Goblin Game")
    return game


@scenario(
    "bid_life", "Illicit Auction",
    answer=lambda g, c: {"number": 1},
    wire=lambda g, c: {"number": 1},
    # The bid stands until the next seat answers: the auction goes round.
    then=lambda g: _assert(g.pending_choice_of("bid_life", 0) is not None and g.players[1].life == 20),
)
def _illicit_auction():
    game = duel(hands=(("Illicit Auction",), ()), boards=((), ("Hill Giant",)))
    game.cast_from_hand(0, "Illicit Auction", target_permanent_ids=[
        on_board(game, 1, "Hill Giant").permanent_id
    ])
    return game


# -- triggers, targets, types ------------------------------------------------

@scenario(
    "order_triggers", "Venerable Monk",
    answer=lambda g, c: {"order": [1, 0]},
    wire=lambda g, c: {"trigger_order": [1, 0]},
    then=lambda g: _resolved_then(g, lambda: _assert(g.players[0].life == 23)),
)
def _venerable_monk_beside_soul_warden():
    game = duel(hands=(("Venerable Monk",), ()), boards=(("Soul Warden",), ()))
    game.cast_from_hand(0, "Venerable Monk")
    return game


def _tolarian_kraken():
    game = duel(boards=(("Tolarian Kraken", "Island"), ("Grizzly Bears",)))
    game._draw_with_replacements(game.players[0], 1)
    game._settle()
    assert game.confirm_optional_pay(0, accept=True)
    return game


def _kraken_taps_the_bears(game):
    assert game.confirm_optional_pay(0, accept=True)
    _assert(on_board(game, 1, "Grizzly Bears").tapped)


scenario(
    "reflexive_target", "Tolarian Kraken",
    answer=lambda g, c: {"permanent_id": on_board(g, 1, "Grizzly Bears").permanent_id},
    wire=lambda g, c: {"target_permanent_id": on_board(g, 1, "Grizzly Bears").permanent_id},
    then=_kraken_taps_the_bears,
)(_tolarian_kraken)


@scenario(
    "land_type_choice", "Phantasmal Terrain",
    answer=lambda g, c: {"land_type": "island"},
    wire=lambda g, c: {"land_type": "island"},
    then=lambda g: _assert(on_board(g, 1, "Forest").basic_land_types == ("island",)),
)
def _phantasmal_terrain():
    game = duel(hands=(("Phantasmal Terrain",), ()), boards=((), ("Forest",)))
    game.cast_from_hand(0, "Phantasmal Terrain", target_permanent_ids=[
        on_board(game, 1, "Forest").permanent_id
    ])
    return game


@scenario(
    "land_type_swap", "Vision Charm",
    answer=lambda g, c: {"from_type": "island", "to_type": "forest"},
    wire=lambda g, c: {"chosen_land_type": "island", "second_land_type": "forest"},
    then=lambda g: _resolved_then(
        g, lambda: _assert(on_board(g, 1, "Island").basic_land_types == ("forest",))
    ),
)
def _vision_charm():
    game = duel(hands=(("Vision Charm",), ()), boards=(("Forest",), ("Island", "Mountain")))
    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    return game


@scenario(
    "card_type_choice", "Blood Oath",
    answer=lambda g, c: {"card_type": "instant"},
    wire=lambda g, c: {"card_type": "instant"},
    then=lambda g: _assert(g.players[1].life == 14),
)
def _blood_oath():
    game = duel(hands=(("Blood Oath",), ("Shock", "Lightning Bolt", "Forest")))
    game.cast_from_hand(0, "Blood Oath", target_player_index=1)
    return game


@scenario(
    "creature_type_choice", "Unnatural Selection",
    answer=lambda g, c: {"creature_type": "goblin"},
    wire=lambda g, c: {"creature_type": "goblin"},
    then=lambda g: _resolved_then(
        g, lambda: _assert("goblin" in _subtypes(on_board(g, 1, "Grizzly Bears")))
    ),
)
def _unnatural_selection():
    game = duel(boards=(("Unnatural Selection",), ("Grizzly Bears",)))
    selection = on_board(game, 0, "Unnatural Selection")
    game.activate_permanent_ability(
        0, "Unnatural Selection", permanent_index=game.battlefield_index_of(selection),
        target_permanent_ids=[on_board(game, 1, "Grizzly Bears").permanent_id],
    )
    return game


@scenario(
    "color_choice", "Mother of Runes",
    answer=lambda g, c: {"mana_color": "R"},
    wire=lambda g, c: {"mana_color": "R"},
    then=lambda g: _assert(g._protection_colors(on_board(g, 0, "Grizzly Bears")) == {"R"}),
)
def _mother_of_runes():
    game = duel(boards=(("Mother of Runes", "Grizzly Bears"), ()))
    mother = on_board(game, 0, "Mother of Runes")
    game.activate_permanent_ability(
        0, "Mother of Runes", permanent_index=game.battlefield_index_of(mother),
        target_permanent_ids=[on_board(game, 0, "Grizzly Bears").permanent_id],
    )
    return game


@scenario(
    "mana_payment", "Power Sink",
    answer=lambda g, c: {"pay": False},
    wire=lambda g, c: {"accept": False},
    # Declined: the spell is countered and its controller's lands are tapped.
    then=lambda g: _assert(
        "Lightning Bolt" in names(g.players[1].graveyard)
        and on_board(g, 1, "Mountain").tapped
    ),
)
def _power_sink():
    game = duel(hands=(("Power Sink",), ("Lightning Bolt",)), boards=((), ("Mountain",)))
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Power Sink", target_stack_index=0, x_value=3)
    return game


@scenario(
    "player_choice", "Guided Passage",
    answer=lambda g, c: {"seat": 2},
    wire=lambda g, c: {"chosen_seat": 2},
    then=lambda g: _assert(any(c.player_index == 2 for c in g.pending_choices)),
)
def _guided_passage():
    game = duel(
        hands=(("Guided Passage",),),
        libraries=(("Grizzly Bears", "Forest", "Shock", "Island"),),
        seats=3,
    )
    game.cast_from_hand(0, "Guided Passage")
    return game


@scenario(
    "cast_choice", "Backdraft",
    answer=lambda g, c: {"cast_index": c.data["options"][1]},
    wire=lambda g, c: {"cast_index": c.data["options"][1]},
    then=lambda g: _assert(g.players[0].life == 19),
)
def _backdraft():
    game = duel(hands=(("Fireball", "Fireball"), ("Backdraft",)))
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=4)
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=2)
    game.cast_from_hand(1, "Backdraft")
    return game


@scenario(
    "madness_cast", "Arrogant Wurm",
    answer=lambda g, c: {"accept": False},
    wire=lambda g, c: {"accept": False},
    then=lambda g: _assert("Arrogant Wurm" in names(g.players[1].graveyard)),
)
def _arrogant_wurm():
    game = duel(hands=(("Mind Rot",), ("Arrogant Wurm",)))
    game.cast_from_hand(0, "Mind Rot", target_player_index=1)
    assert game.confirm_discard(1, [0])
    resolve_until_owed(game, "madness_cast")
    return game


@scenario(
    "retarget_choice", "Deflection",
    answer=lambda g, c: {"target_index": _retarget_to(c, "P1")},
    wire=lambda g, c: {"target_index": _retarget_to(c, "P1")},
    then=lambda g: _resolved_then(g, lambda: _assert(
        g.players[1].life == 17 and g.players[0].life == 20
    )),
)
def _deflection():
    game = duel(hands=(("Deflection",), ("Lightning Bolt",)), boards=((), ("Grizzly Bears",)))
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Deflection", target_stack_index=0)
    return game


@scenario(
    "permanent_choice", "Kudzu",
    answer=lambda g, c: {"permanent_id": on_board(g, 1, "Plains").permanent_id},
    wire=lambda g, c: {"target_permanent_id": on_board(g, 1, "Plains").permanent_id},
    then=lambda g: _assert(
        on_board(g, 0, "Kudzu").metadata.get("attached_to") is on_board(g, 1, "Plains")
    ),
)
def _kudzu():
    from engine.aura_attachment import attach_aura

    game = duel(boards=(("Kudzu",), ("Forest", "Plains")))
    attach_aura(on_board(game, 0, "Kudzu"), on_board(game, 1, "Forest"))
    game.tap_land_for_mana(
        1, "Forest", chosen_color="G", permanent_index=_slot(game, 1, "Forest"),
    )
    resolve_until_owed(game, "permanent_choice")
    return game


@scenario(
    "permanent_set_choice", "Bull Elephant",
    answer=lambda g, c: {"permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Forest")[:2]]},
    wire=lambda g, c: {"target_permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Forest")[:2]]},
    then=lambda g: _assert(names(g.players[0].hand).count("Forest") == 2),
)
def _bull_elephant():
    game = duel(hands=(("Bull Elephant",), ()), boards=(("Forest", "Forest", "Forest"), ()))
    game.cast_from_hand(0, "Bull Elephant")
    # "…sacrifice it unless you return two Forests": the offer first.
    assert game.confirm_optional_pay(0, accept=True)
    return game


@scenario(
    "flip_again", "Game of Chaos",
    answer=lambda g, c: {"accept": False},
    wire=lambda g, c: {"accept": False},
    then=lambda g: _assert(sum(p.life for p in g.players) == 40 and not g.stack),
)
def _game_of_chaos():
    game = duel(hands=(("Game of Chaos",), ()))
    game.cast_from_hand(0, "Game of Chaos", target_player_index=1)
    return game


@scenario(
    "repeat_process", "Forbidden Ritual",
    answer=lambda g, c: {"accept": False},
    wire=lambda g, c: {"accept": False},
    then=lambda g: _assert("Forbidden Ritual" in names(g.players[0].graveyard)),
)
def _forbidden_ritual():
    game = duel(hands=(("Forbidden Ritual",), ()), boards=(("Grizzly Bears", "Hill Giant"), ()))
    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    resolve_until_owed(game, "repeat_process")
    return game


@scenario(
    "exile_from_hand_choice", "Ice Cauldron",
    answer=lambda g, c: {"hand_index": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _assert(names(g.players[0].exile) == ["Shock"]),
)
def _ice_cauldron():
    game = duel(boards=(("Ice Cauldron",), ()), hands=(("Shock",), ()))
    cauldron = on_board(game, 0, "Ice Cauldron")
    game.activate_permanent_ability(
        0, "Ice Cauldron", permanent_index=game.battlefield_index_of(cauldron), x_value=1,
    )
    # "You may exile a nonland card from your hand": the offer, then the pick.
    assert game.confirm_optional_pay(0, accept=True)
    return game


@scenario(
    "exile_hand_pile_choice", "Scroll Rack",
    answer=lambda g, c: {"hand_indices": [0, 1]},
    wire=lambda g, c: {"hand_indices": [0, 1]},
    # The two exiled cards were swapped for the top two, and wait on top of
    # the library for the order the next prompt asks for.
    then=lambda g: _assert(
        names(g.players[0].hand) == ["Grizzly Bears", "Hill Giant"]
        and sorted(names(g.players[0].library[:2])) == ["Forest", "Shock"]
    ),
)
def _scroll_rack():
    game = duel(
        boards=(("Scroll Rack",), ()), hands=(("Shock", "Forest"), ()),
        libraries=(("Grizzly Bears", "Hill Giant", "Island"),),
    )
    rack = on_board(game, 0, "Scroll Rack")
    game.activate_permanent_ability(
        0, "Scroll Rack", permanent_index=game.battlefield_index_of(rack),
    )
    return game


# -- piles, names, hands, graveyards ---------------------------------------

_PORTAL_LIBRARY = (
    "Grizzly Bears", "Shock", "Forest", "Hill Giant", "Island",
    "Lightning Bolt", "Swamp", "Mountain", "Plains", "Giant Growth", "Island", "Island",
)


def _phyrexian_portal(*, split: bool = False, exiled: bool = False):
    game = duel(boards=(("Phyrexian Portal",), ()), libraries=(_PORTAL_LIBRARY,))
    portal = on_board(game, 0, "Phyrexian Portal")
    game.activate_permanent_ability(
        0, "Phyrexian Portal", permanent_index=game.battlefield_index_of(portal),
        target_player_index=1,
    )
    if split:
        assert game.confirm_library_pile_split(1, [0, 1, 2])
    if exiled:
        assert game.confirm_pile_exile_choice(0, 0)
    return game


scenario(
    "library_pile_split", "Phyrexian Portal",
    answer=lambda g, c: {"first_pile": [0, 1, 2]},
    wire=lambda g, c: {"first_pile": [0, 1, 2]},
    then=lambda g: _assert(g.pending_choice_of("pile_exile_choice", 0) is not None),
)(lambda: _phyrexian_portal())

scenario(
    "pile_exile_choice", "Phyrexian Portal",
    answer=lambda g, c: {"pile_index": 0},
    wire=lambda g, c: {"pile_index": 0},
    then=lambda g: _assert(
        names(g.players[0].exile) == ["Grizzly Bears", "Shock", "Forest"]
        and g.pending_choice_of("pile_search", 0) is not None
    ),
)(lambda: _phyrexian_portal(split=True))

scenario(
    "pile_search", "Phyrexian Portal",
    answer=lambda g, c: {"pile_index": 0},
    wire=lambda g, c: {"pile_index": 0},
    then=lambda g: _assert(names(g.players[0].hand) == ["Hill Giant"] and not g.stack),
)(lambda: _phyrexian_portal(split=True, exiled=True))


def _fact_or_fiction(*, split: bool = False):
    game = duel(
        hands=(("Fact or Fiction",), ()),
        libraries=(("Grizzly Bears", "Shock", "Forest", "Hill Giant", "Island", "Swamp"),),
    )
    game.cast_from_hand(0, "Fact or Fiction")
    if split:
        assert game.confirm_pile_split(1, [0, 1])
    return game


scenario(
    "pile_split", "Fact or Fiction",
    answer=lambda g, c: {"first_pile": [0, 1]},
    wire=lambda g, c: {"first_pile": [0, 1]},
    then=lambda g: _assert(g.pending_choice_of("pile_choice", 0) is not None),
)(lambda: _fact_or_fiction())

scenario(
    "pile_choice", "Fact or Fiction",
    answer=lambda g, c: {"pile_index": 0},
    wire=lambda g, c: {"pile_index": 0},
    then=lambda g: _assert(
        names(g.players[0].hand) == ["Grizzly Bears", "Shock"]
        and "Fact or Fiction" in names(g.players[0].graveyard) and not g.stack
    ),
)(lambda: _fact_or_fiction(split=True))


@scenario(
    "library_cycle_offer", "Lim-Dûl's Vault",
    answer=lambda g, c: {"accept": False},
    wire=lambda g, c: {"accept": False},
    then=lambda g: _assert(any(c.kind == "reorder_library" for c in g.pending_choices)),
)
def _lim_duls_vault():
    game = duel(hands=(("Lim-Dûl's Vault",), ()))
    game.cast_from_hand(0, "Lim-Dûl's Vault")
    return game


@scenario(
    "linked_exile_return", "Gustha's Scepter",
    answer=lambda g, c: {"entry_index": 1},
    wire=lambda g, c: {"exile_entry_index": 1},
    then=lambda g: _assert(names(g.players[0].hand) == ["Forest"]),
)
def _gusthas_scepter():
    game = duel(boards=(("Gustha's Scepter",), ()), hands=(("Shock", "Forest"), ()))
    scepter = on_board(game, 0, "Gustha's Scepter")
    for _ in range(2):
        scepter.tapped = False
        game.activate_permanent_ability(
            0, "Gustha's Scepter", permanent_index=game.battlefield_index_of(scepter),
        )
        assert game.confirm_exile_from_hand_choice(0, 0)
    scepter.tapped = False
    game.activate_permanent_ability(
        0, "Gustha's Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=1,
    )
    return game


@scenario(
    "put_from_hand_choice", "Flash",
    answer=lambda g, c: {"hand_index": 0},
    wire=lambda g, c: {"hand_index": 0},
    # It entered, and — nothing paid for it — was sacrificed, as printed.
    then=lambda g: _assert(
        "P0 put Hill Giant onto the battlefield (Flash)" in g.log
        and "Hill Giant" in names(g.players[0].graveyard)
    ),
)
def _flash():
    game = duel(hands=(("Flash", "Hill Giant"), ()))
    game.cast_from_hand(0, "Flash")
    # "You may put a creature card from your hand onto the battlefield": the
    # offer, then which card.
    assert game.confirm_optional_pay(0, accept=True)
    return game


@scenario(
    "text_change_vocabulary", "Mind Bend",
    answer=lambda g, c: {"mode": "land_type"},
    wire=lambda g, c: {"text_change_mode": "land_type"},
    then=lambda g: _assert("Mountains" in on_board(g, 1, "Floodgate").effective_card.oracle_text),
)
def _mind_bend():
    game = duel(hands=(("Mind Bend",), ()), boards=((), ("Floodgate",)))
    game.cast_from_hand(
        0, "Mind Bend", target_permanent_ids=[on_board(game, 1, "Floodgate").permanent_id],
        old_color="U", new_color="R",
    )
    return game


@scenario(
    "aggregate_sacrifice", "Phyrexian Dreadnought",
    answer=lambda g, c: {"permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Craw Wurm")]},
    wire=lambda g, c: {"target_permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Craw Wurm")]},
    then=lambda g: _assert(
        names(g.players[0].graveyard).count("Craw Wurm") == 2
        and any(p.card.name == "Phyrexian Dreadnought" for p in g.controlled_by(0))
    ),
)
def _phyrexian_dreadnought():
    game = duel(
        hands=(("Phyrexian Dreadnought",), ()),
        boards=(("Craw Wurm", "Craw Wurm"), ()),
    )
    game.cast_from_hand(0, "Phyrexian Dreadnought")
    resolve_until_owed(game, "aggregate_sacrifice")
    return game


@scenario(
    "library_end_choice", "Ether Well",
    answer=lambda g, c: {"to_bottom": True},
    wire=lambda g, c: {"to_bottom": True},
    then=lambda g: _assert(g.players[1].library[-1].name == "Hill Giant"),
)
def _ether_well():
    game = duel(hands=(("Ether Well",), ()), boards=((), ("Hill Giant",)))
    game.cast_from_hand(0, "Ether Well", target_permanent_ids=[
        on_board(game, 1, "Hill Giant").permanent_id
    ])
    return game


@scenario(
    "graveyard_pile_choice", "(no shipped card — the handler's resolution-time branch)",
    answer=lambda g, c: {"seat": 1},
    wire=lambda g, c: {"chosen_seat": 1},
    then=lambda g: _assert(g.pending_choice_of("graveyard_exile_pick", 0) is not None),
)
def _graveyard_pile():
    """No compiled card reaches this branch since triggers announce their
    graveyard targets (``test_ody_w2g3_single_graveyard_targets``); it is
    driven over the instruction that does."""
    from engine.game_types import OracleExecutionContext
    from engine.oracle_types import OracleInstruction

    game = duel(graveyards=(("Shock",), ("Lightning Bolt", "Grizzly Bears")), boards=(("Craw Wurm",), ()))
    source = on_board(game, 0, "Craw Wurm")
    instruction = OracleInstruction("exile_cards_from_graveyard", "", {
        "count": 2, "graveyard_owner": "chosen", "up_to": True, "any_card": True,
    })
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=source.card,
        source_permanent=source,
    )
    game._execute_oracle_instruction(instruction, context)
    return game


@scenario(
    "graveyard_exile_pick", "Grave Consequences",
    answer=lambda g, c: {"graveyard_indices": [0]},
    wire=lambda g, c: {"graveyard_indices": [0]},
    then=lambda g: _assert(names(g.players[0].exile) == ["Shock"]),
)
def _grave_consequences():
    game = duel(hands=(("Grave Consequences",), ()), graveyards=(("Shock",), ("Lightning Bolt",)))
    game.cast_from_hand(0, "Grave Consequences")
    return game


@scenario(
    "choose_cards_in_hand", "Noxious Vapors",
    answer=lambda g, c: {"hand_indices": [0, 2]},
    wire=lambda g, c: {"hand_indices": [0, 2]},
    then=lambda g: _assert(
        names(g.players[0].hand) == ["Shock", "Giant Growth"]
        and "Lightning Bolt" in names(g.players[0].graveyard)
    ),
)
def _noxious_vapors():
    game = duel(hands=(("Noxious Vapors", "Shock", "Lightning Bolt", "Giant Growth"), ()))
    game.cast_from_hand(0, "Noxious Vapors")
    return game


@scenario(
    "face_down_cast", "Illusionary Mask",
    answer=lambda g, c: {"hand_index": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _resolved_then(g, lambda: _assert(
        any(p.metadata.get("face_down") for p in g.controlled_by(0))
        and g.players[0].hand == []
    )),
)
def _illusionary_mask():
    game = duel(boards=(("Illusionary Mask",), ()), hands=(("Grizzly Bears",), ()))
    mask = on_board(game, 0, "Illusionary Mask")
    game.activate_permanent_ability(
        0, "Illusionary Mask", permanent_index=game.battlefield_index_of(mask), x_value=2,
    )
    return game


@scenario(
    "word_of_command", "Word of Command",
    answer=lambda g, c: {"hand_index": 0, "defer_resolution": True},
    wire=lambda g, c: {"hand_index": 0},
    # The answer is recorded and the spell waits for a priority round; the next
    # resolution finishes it and the forced card is cast.
    then=lambda g: (
        g.resolve_top_of_stack(pause_for_choices=True),
        _assert(
            "Giant Growth" not in names(g.players[1].hand)
            and "Word of Command" in names(g.players[0].graveyard)
        ),
    ),
)
def _word_of_command():
    game = duel(hands=(("Word of Command",), ("Giant Growth",)), boards=((), ("Grizzly Bears",)))
    game.cast_from_hand(0, "Word of Command", target_player_index=1)
    return game


@scenario(
    "opponent_damage", "Cuombajj Witches",
    answer=lambda g, c: {"target_seat": 0, "target_permanent_index": None},
    wire=lambda g, c: {"target_seat": 0},
    then=lambda g: _resolved_then(g, lambda: _assert(g.players[0].life == 19)),
)
def _cuombajj_witches():
    game = duel(boards=(("Cuombajj Witches",), ()))
    witches = on_board(game, 0, "Cuombajj Witches")
    game.activate_permanent_ability(
        0, "Cuombajj Witches", permanent_index=game.battlefield_index_of(witches),
        target_player_index=1,
    )
    return game


@scenario(
    "name_and_strip", "Necromentia",
    answer=lambda g, c: {"card_name": "Shock"},
    wire=lambda g, c: {"card_name": "Shock"},
    then=lambda g: _assert(names(g.players[1].exile).count("Shock") == 2),
)
def _necromentia():
    game = duel(
        hands=(("Necromentia",), ("Shock",)),
        libraries=((), ("Shock", "Island")), graveyards=((), ("Lightning Bolt",)),
    )
    game.cast_from_hand(0, "Necromentia", target_player_index=1)
    return game


@scenario(
    "choose_card_name", "Wood Sage",
    answer=lambda g, c: {"card_name": "Grizzly Bears"},
    wire=lambda g, c: {"card_name": "Grizzly Bears"},
    then=lambda g: _assert(names(g.players[0].hand) == ["Grizzly Bears"]),
)
def _wood_sage():
    game = duel(
        boards=(("Wood Sage",), ()),
        libraries=(("Grizzly Bears", "Island", "Forest", "Hill Giant", "Swamp"),),
    )
    sage = on_board(game, 0, "Wood Sage")
    game.activate_permanent_ability(0, "Wood Sage", permanent_index=game.battlefield_index_of(sage))
    return game


@scenario(
    "name_then_reveal_top", "Petra Sphinx",
    answer=lambda g, c: {"card_name": "Grizzly Bears"},
    wire=lambda g, c: {"card_name": "Grizzly Bears"},
    then=lambda g: _assert(names(g.players[1].hand) == ["Grizzly Bears"]),
)
def _petra_sphinx():
    game = duel(boards=(("Petra Sphinx",), ()), libraries=((), ("Grizzly Bears", "Island")))
    sphinx = on_board(game, 0, "Petra Sphinx")
    game.activate_permanent_ability(
        0, "Petra Sphinx", permanent_index=game.battlefield_index_of(sphinx), target_player_index=1,
    )
    return game


@scenario(
    "exiled_pile_claim", "Thieves' Auction",
    answer=lambda g, c: {"pile_index": 0},
    wire=lambda g, c: {"pile_index": 0},
    then=lambda g: _assert(
        any(c.kind == "exiled_pile_claim" and c.player_index == 1 for c in g.pending_choices)
    ),
)
def _thieves_auction():
    game = duel(hands=(("Thieves' Auction",), ()), boards=(("Forest",), ("Grizzly Bears", "Island")))
    game.cast_from_hand(0, "Thieves' Auction")
    return game


@scenario(
    "graveyard_pick_for_price", "Forgotten Lore",
    answer=lambda g, c: {"graveyard_index": 0},
    wire=lambda g, c: {"graveyard_index": 0},
    # "You may pay {G}. If you do, repeat this process": the caster's offer.
    then=lambda g: _assert(g.pending_choice_of("optional_pay", 0) is not None),
)
def _forgotten_lore():
    game = duel(hands=(("Forgotten Lore",), ()), graveyards=(("Shock", "Grizzly Bears"), ()))
    game.cast_from_hand(0, "Forgotten Lore", target_player_index=1)
    return game


@scenario(
    "name_then_consult", "Demonic Consultation",
    answer=lambda g, c: {"card_name": "Grizzly Bears"},
    wire=lambda g, c: {"card_name": "Grizzly Bears"},
    then=lambda g: _assert(names(g.players[0].hand) == ["Grizzly Bears"]),
)
def _demonic_consultation():
    game = duel(
        hands=(("Demonic Consultation",), ()),
        libraries=(("Island",) * 6 + ("Forest", "Grizzly Bears", "Swamp"),),
    )
    game.cast_from_hand(0, "Demonic Consultation")
    return game


@scenario(
    "name_and_random_reveal", "Nebuchadnezzar",
    answer=lambda g, c: {"card_name": "Shock"},
    wire=lambda g, c: {"card_name": "Shock"},
    then=lambda g: _assert(names(g.players[1].graveyard) == ["Shock"]),
)
def _nebuchadnezzar():
    game = duel(boards=(("Nebuchadnezzar",), ()), hands=((), ("Shock",)))
    neb = on_board(game, 0, "Nebuchadnezzar")
    game.activate_permanent_ability(
        0, "Nebuchadnezzar", permanent_index=game.battlefield_index_of(neb),
        target_player_index=1, x_value=1,
    )
    return game


# -- combat, entering, modes, outside the game -------------------------------

@scenario(
    "tap_any_number", "Siege Striker",
    answer=lambda g, c: {"permanent_ids": [on_board(g, 0, "Grizzly Bears").permanent_id]},
    wire=lambda g, c: {"target_permanent_ids": [on_board(g, 0, "Grizzly Bears").permanent_id]},
    then=lambda g: _assert(
        on_board(g, 0, "Grizzly Bears").tapped
        and on_board(g, 0, "Siege Striker").effective_power == 2
    ),
)
def _siege_striker():
    game = duel(boards=(("Siege Striker", "Grizzly Bears"), ()))
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [_slot(game, 0, "Siege Striker")], defending_player_index=1)
    assert ok, why
    resolve_until_owed(game, "tap_any_number")
    return game


@scenario(
    "untap_up_to", "Rewind",
    answer=lambda g, c: {"permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Island")]},
    wire=lambda g, c: {"target_permanent_ids": [p.permanent_id for p in _all_named(g, 0, "Island")]},
    then=lambda g: _assert(
        not any(p.tapped for p in _all_named(g, 0, "Island"))
        and "Lightning Bolt" in names(g.players[1].graveyard)
    ),
)
def _rewind():
    game = duel(
        hands=(("Rewind",), ("Lightning Bolt",)),
        boards=((perm("Island", tapped=True), perm("Island", tapped=True)), ()),
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.cast_from_hand(0, "Rewind", target_stack_index=0)
    return game


@scenario(
    "enter_choice", "Runed Halo",
    answer=lambda g, c: {"card_name": "Lightning Bolt"},
    wire=lambda g, c: {"card_name": "Lightning Bolt", "target_seat": 0},
    then=lambda g: _assert(
        on_board(g, 0, "Runed Halo").metadata.get("chosen_card_name") == "Lightning Bolt"
        or "Lightning Bolt" in str(on_board(g, 0, "Runed Halo").metadata)
    ),
)
def _runed_halo():
    game = duel(hands=(("Runed Halo",), ()))
    game.cast_from_hand(0, "Runed Halo")
    return game


@scenario(
    "entry_exile", "Frankenstein's Monster",
    answer=lambda g, c: {"picks": [{"index": 0, "counter": "+2/+0"}, {"index": 1, "counter": "+0/+2"}]},
    wire=lambda g, c: {"entry_exile_picks": [
        {"index": 0, "counter": "+2/+0"}, {"index": 1, "counter": "+0/+2"},
    ]},
    then=lambda g: _assert(
        (on_board(g, 0, "Frankenstein's Monster").effective_power,
         on_board(g, 0, "Frankenstein's Monster").effective_toughness) == (2, 3)
    ),
)
def _frankensteins_monster():
    game = duel(
        hands=(("Frankenstein's Monster",), ()),
        graveyards=(("Grizzly Bears", "Craw Wurm", "Mox Pearl"), ()),
    )
    game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)
    return game


@scenario(
    "entry_reveal", "Glowering Rogon",
    # The hand is Canopy Crawler (a Beast) and an Island once the Rogon has
    # left it, so slot 0 is the one card amplify may reveal.
    answer=lambda g, c: {"hand_indices": [0]},
    wire=lambda g, c: {"hand_indices": [0]},
    then=lambda g: _assert(
        (on_board(g, 0, "Glowering Rogon").effective_power,
         on_board(g, 0, "Glowering Rogon").effective_toughness) == (5, 5)
    ),
)
def _glowering_rogon():
    # Legions is measured when this lands, so its cards are read from the set
    # rather than from the shipped catalog this file's boards are built from.
    from engine.card_loader import load_cards, manifest_set_path

    legions = {c.name: c for c in load_cards(manifest_set_path("LGN", include_measured=True))}
    game = duel(hands=(("Island",), ()))
    game.players[0].hand[:0] = [legions["Glowering Rogon"], legions["Canopy Crawler"]]
    game.cast_from_hand(0, "Glowering Rogon")
    return game


@scenario(
    "body_choice", "Primal Clay",
    answer=lambda g, c: {"option_index": 2},
    wire=lambda g, c: {"hand_index": 2},
    then=lambda g: _assert(
        (on_board(g, 0, "Primal Clay").effective_power,
         on_board(g, 0, "Primal Clay").effective_toughness) == (1, 6)
    ),
)
def _primal_clay():
    game = duel(hands=(("Primal Clay",), ()))
    game.cast_from_hand(0, "Primal Clay")
    return game


def _fatal_lore(*, mode: int | None = None):
    game = duel(hands=(("Fatal Lore",), ()), boards=((), ("Grizzly Bears", "Hill Giant")))
    # Announced the way a client casts (the spell waits on the stack for
    # priority), not through the cast-and-resolve convenience call.
    game.queue_from_hand(0, "Fatal Lore")
    if mode is not None:
        assert game.resolve_pending_choice("opponent_mode_choice", 1, mode_index=mode)
    return game


scenario(
    "opponent_mode_choice", "Fatal Lore",
    answer=lambda g, c: {"mode_index": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _resolved_then(g, lambda: _assert(len(g.players[0].hand) == 3)),
)(lambda: _fatal_lore())

scenario(
    "modal_mode_targets", "Fatal Lore",
    answer=lambda g, c: {"permanent_ids": [on_board(g, 1, "Grizzly Bears").permanent_id]},
    wire=lambda g, c: {"target_permanent_ids": [on_board(g, 1, "Grizzly Bears").permanent_id]},
    then=lambda g: _finished_then(g, lambda: _assert(
        "Grizzly Bears" in names(g.players[1].graveyard)
        and any(p.card.name == "Hill Giant" for p in g.controlled_by(1))
    )),
)(lambda: _fatal_lore(mode=1))


@scenario(
    "mode_choice", "Trufflesnout",
    answer=lambda g, c: {"mode_index": 1},
    wire=lambda g, c: {"hand_index": 1},
    then=lambda g: _resolved_then(g, lambda: _assert(g.players[0].life == 24)),
)
def _trufflesnout():
    game = duel(hands=(("Trufflesnout",), ()))
    game.cast_from_hand(0, "Trufflesnout")
    return game


@scenario(
    "loyalty_recipient", "Liliana's Scrounger",
    answer=lambda g, c: {"permanent_id": on_board(g, 0, "Liliana, Waker of the Dead").permanent_id},
    wire=lambda g, c: {"target_permanent_id": on_board(g, 0, "Liliana, Waker of the Dead").permanent_id},
    then=lambda g: _assert(
        int(on_board(g, 0, "Liliana, Waker of the Dead").metadata.get("loyalty_counters", 0)) == 5
    ),
)
def _lilianas_scrounger():
    def walker(name, loyalty):
        return Permanent(card=card(name), metadata={"loyalty_counters": loyalty})

    game = duel(boards=((
        "Liliana's Scrounger", walker("Liliana, Waker of the Dead", 4),
        walker("Liliana, Death Mage", 2), "Grizzly Bears",
    ), ()))
    game._permanent_to_graveyard(game.players[0], on_board(game, 0, "Grizzly Bears"))
    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, accept=True)
    game._settle()
    return game


def _plus_one_counters(game: Game, seat: int, name: str) -> int:
    from engine.named_counters import counters_on

    return counters_on(on_board(game, seat, name), "+1/+1")


@scenario(
    "counter_distribution", "Forgotten Ancient",
    answer=lambda g, c: {
        "permanent_ids": [on_board(g, 0, "Grizzly Bears").permanent_id],
        "amounts": [2],
    },
    wire=lambda g, c: {"divided_targets": [
        {"seat": 0, "id": on_board(g, 0, "Grizzly Bears").permanent_id, "amount": 2},
    ]},
    then=lambda g: _assert(
        _plus_one_counters(g, 0, "Craw Wurm") + _plus_one_counters(g, 0, "Grizzly Bears")
        == 3
    ),
)
def _forgotten_ancient():
    """"…you may move any number of +1/+1 counters from this creature onto
    other creatures." No shipped card prints it — the first is Scourge's
    Forgotten Ancient, a measured set this pool-wide census does not load — so
    it is driven over the instruction the card lowers to, from a Craw Wurm
    holding three counters, the way ``face_down_look`` is."""
    from engine.game_types import OracleExecutionContext
    from engine.oracle_types import OracleInstruction

    game = duel(boards=(("Craw Wurm", "Grizzly Bears"), ("Grizzly Bears",)))
    source = on_board(game, 0, "Craw Wurm")
    game.place_plus1_counters(source, 3)
    instruction = OracleInstruction("distribute_counters_from_self", "", {
        "counter": "+1/+1",
        "filter": {"type_filter": "creature", "exclude_self": True},
    })
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=source.card,
        source_permanent=source,
    )
    game._execute_oracle_instruction(instruction, context)
    return game


@scenario(
    "keep_permanents", "Cataclysm",
    answer=lambda g, c: {"permanent_ids": [on_board(g, 1, "Grizzly Bears").permanent_id, on_board(g, 1, "Forest").permanent_id]},
    wire=lambda g, c: {"target_permanent_ids": [on_board(g, 1, "Grizzly Bears").permanent_id, on_board(g, 1, "Forest").permanent_id]},
    then=lambda g: _finished_then(g, lambda: _assert(
        sorted(p.card.name for p in g.controlled_by(1)) == ["Forest", "Grizzly Bears"]
    )),
)
def _cataclysm():
    game = duel(
        hands=(("Cataclysm",), ()),
        boards=((), ("Grizzly Bears", "Hill Giant", "Forest", "Island")),
    )
    game.cast_from_hand(0, "Cataclysm")
    return game


@scenario(
    "outside_game_pick", "Living Wish",
    answer=lambda g, c: {"sideboard_index": 0},
    wire=lambda g, c: {"sideboard_index": 0},
    then=lambda g: _assert(names(g.players[0].hand) == ["Grizzly Bears"]),
)
def _living_wish():
    game = duel(hands=(("Living Wish",), ()))
    game.players[0].sideboard = [card("Grizzly Bears"), card("Shock")]
    game.cast_from_hand(0, "Living Wish")
    # "You may reveal a creature or land card you own from outside the game":
    # the offer, then which card.
    assert game.confirm_optional_pay(0, accept=True)
    return game


# -- the CR 614 queue: a replacement suspended on a decision -----------------

def _draw_one(game: Game, seat: int = 0) -> Game:
    game._draw_with_replacements(game.players[seat], 1)
    return game


@scenario(
    "effect_order", "Aladdin's Lamp beside Ring of Ma'rûf",
    answer=lambda g, c: {"option_index": c.data["options"].index("Aladdin's Lamp")},
    wire=lambda g, c: {"option_index": c.data["options"].index("Aladdin's Lamp")},
    then=lambda g: _assert(any(c.kind == "lamp_draw" for c in g.pending_replacement_choices)),
)
def _lamp_and_ring():
    game = _lamp_and_ring_armed()
    return _draw_one(game)


def _lamp_and_ring_armed(*, lamp: bool = True, ring: bool = True) -> Game:
    game = duel(
        boards=(tuple(n for n, on in (("Aladdin's Lamp", lamp), ("Ring of Ma'rûf", ring)) if on), ()),
        libraries=(("Grizzly Bears", "Shock", "Forest", "Island"),),
    )
    game.players[0].sideboard = [card("Hill Giant")]
    for name, on, kwargs in (
        ("Aladdin's Lamp", lamp, {"x_value": 2}),
        ("Ring of Ma'rûf", ring, {}),
    ):
        if on:
            artifact = on_board(game, 0, name)
            game.activate_permanent_ability(
                0, name, permanent_index=game.battlefield_index_of(artifact), **kwargs,
            )
            game._settle()
    return game


@scenario(
    "lamp_draw", "Aladdin's Lamp",
    answer=lambda g, c: {"option": 1},
    wire=lambda g, c: {"hand_index": 1},
    then=lambda g: _assert(names(g.players[0].hand) == ["Shock"]),
)
def _aladdins_lamp():
    return _draw_one(_lamp_and_ring_armed(ring=False))


@scenario(
    "outside_game_draw", "Ring of Ma'rûf",
    answer=lambda g, c: {"option": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _assert(names(g.players[0].hand) == ["Hill Giant"]),
)
def _ring_of_maruf():
    return _draw_one(_lamp_and_ring_armed(lamp=False))


@scenario(
    "skip_draw", "Obstinate Familiar",
    answer=lambda g, c: {"option": 1},
    wire=lambda g, c: {"option_index": 1},
    then=lambda g: _assert(g.players[0].hand == [] and len(g.players[0].library) == 8),
)
def _obstinate_familiar():
    return _draw_one(duel(boards=(("Obstinate Familiar",), ())))


@scenario(
    "reveal_until_kind_draw", "Abundance",
    answer=lambda g, c: {"option": _option(c, "land")},
    wire=lambda g, c: {"option_index": _option(c, "land")},
    then=lambda g: _assert(names(g.players[0].hand) == ["Forest"]),
)
def _abundance():
    return _draw_one(duel(
        boards=(("Abundance",), ()),
        libraries=(("Grizzly Bears", "Shock", "Forest", "Island"),),
    ))


@scenario(
    "draw_becomes_counter", "Pursuit of Knowledge",
    answer=lambda g, c: {"option": _option(c, "counter")},
    wire=lambda g, c: {"take_the_counter": True},
    then=lambda g: _assert(g.players[0].hand == [] and len(g.players[0].library) == 8),
)
def _pursuit_of_knowledge():
    return _draw_one(duel(boards=(("Pursuit of Knowledge",), ())))


@scenario(
    "return_from_graveyard_instead_of_draw", "Forbidden Crypt",
    answer=lambda g, c: {"option": 0},
    wire=lambda g, c: {"hand_index": 0},
    then=lambda g: _assert(len(g.players[0].hand) == 1 and len(g.players[0].library) == 8),
)
def _forbidden_crypt():
    return _draw_one(duel(boards=(("Forbidden Crypt",), ()), graveyards=(("Shock", "Grizzly Bears"),)))


@scenario(
    "leng_discard", "Library of Leng",
    answer=lambda g, c: {"option": _option(c, "library")},
    wire=lambda g, c: {"to_library": True},
    then=lambda g: _assert(g.players[1].library[0].name == "Shock"),
)
def _library_of_leng():
    # At random, so nobody chose the card and the destination is the Library's
    # own question (a chosen discard answers it on the discard prompt).
    game = duel(hands=(("Mind Twist",), ("Shock",)), boards=((), ("Library of Leng",)))
    game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=1)
    return game


@scenario(
    "optional_damage_redirect", "Blood of the Martyr",
    answer=lambda g, c: {"option": _option(c, "you")},
    wire=lambda g, c: {"take_the_damage": True},
    then=lambda g: _assert(
        g.players[0].life == 18 and any(p.card.name == "Grizzly Bears" for p in g.controlled_by(1))
    ),
)
def _blood_of_the_martyr():
    game = duel(hands=(("Blood of the Martyr", "Shock"), ()), boards=((), ("Grizzly Bears",)))
    game.cast_from_hand(0, "Blood of the Martyr")
    game.cast_from_hand(0, "Shock", target_permanent_ids=[
        on_board(game, 1, "Grizzly Bears").permanent_id
    ])
    return game


@scenario(
    "entry_discard_toll", "Mox Diamond",
    answer=lambda g, c: {"option": _option(c, "Forest")},
    wire=lambda g, c: {"hand_index": names(g.players[0].hand).index("Forest")},
    then=lambda g: _assert(
        any(p.card.name == "Mox Diamond" for p in g.controlled_by(0))
        and "Forest" in names(g.players[0].graveyard)
    ),
)
def _mox_diamond():
    game = duel(hands=(("Mox Diamond", "Forest"), ()))
    game.cast_from_hand(0, "Mox Diamond")
    return game


@scenario(
    "commander_zone_change", "Gadrak, the Crown-Scourge (a commander)",
    answer=lambda g, c: {"option": 0},
    wire=lambda g, c: {"to_command_zone": True},
    then=lambda g: _assert(names(g.players[0].command_zone) == ["Gadrak, the Crown-Scourge"]),
)
def _a_commander_dies():
    from engine.commander import COMMANDER

    gadrak = card("Gadrak, the Crown-Scourge")
    game = Game(
        players=[
            PlayerState(name="P0", library=[card("Mountain")] * 8, hand=[card("Terror")]),
            PlayerState(name="P1", library=[card("Mountain")] * 8),
        ],
        commander_variant=COMMANDER,
    )
    game.designate_commander(0, gadrak)
    game.designate_commander(1, card("Azusa, Lost but Seeking"))
    game.players[0].command_zone = [gadrak]
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    game.cast_from_hand(0, gadrak.name, from_zone="command")
    game.cast_from_hand(0, "Terror", target_permanent_ids=[on_board(game, 0, gadrak.name).permanent_id])
    return game


# kg3/ai: Kaboom! names P1 and P1's planeswalker, one player's group, and the
# caster orders them (the 2022-09-09 ruling). The walker is handled first, so
# the first card revealed (Hill Giant, mana value 4) is its damage and the
# second (Shock, 1) is P1's.
@scenario(
    "target_group_order", "Kaboom!",
    answer=lambda g, c: {"order": [1, 0]},
    wire=lambda g, c: {"target_order": [1, 0]},
    then=lambda g: _resolved_then(g, lambda: _assert(g.players[1].life == 19)),
)
def _kaboom_orders_one_players_group():
    from engine.named_counters import add_counters

    walker = perm("Chandra, Heart of Fire")
    add_counters(walker, "loyalty", 5)
    game = duel(
        hands=(("Kaboom!",), ()),
        boards=((), (walker,)),
        libraries=(("Hill Giant", "Shock", "Island"), ("Island",) * 3),
    )
    game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"permanent_id": walker.permanent_id},
    ])
    return game


# ---------------------------------------------------------------------------
# Helpers the table reads
# ---------------------------------------------------------------------------

def _option(choice, label: str) -> int:
    """The index of the replacement option whose label mentions *label*."""
    options = list(getattr(choice, "options", ()) or ())
    exact = [i for i, option in enumerate(options) if str(option).lower() == label.lower()]
    matches = exact or [
        i for i, option in enumerate(options) if label.lower() in str(option).lower()
    ]
    assert matches, (label, options)
    return matches[0]

def resolve_until_owed(game: Game, kind: str | None = None, *, limit: int = 40) -> None:
    """Play the resolution forward until a prompt of *kind* (or, with no kind,
    any prompt) is owed: each earlier prompt takes its own default, one at a
    time, and a stack with nothing owed resolves its top object."""
    for _ in range(limit):
        owed = [choice for _spec, choice in game.iter_pending_prompts()]
        if any(kind is None or choice.kind == kind for choice in owed):
            return
        if owed:
            game.auto_resolve_choice(owed[0])
            continue
        if not game.stack or not game.resolve_top_of_stack(pause_for_choices=True):
            if not any(True for _ in game.iter_pending_prompts()):
                return
    raise AssertionError(f"{kind} was never armed: {game.log[-6:]}")


def _all_named(game: Game, seat: int, name: str) -> list:
    return [p for p in game.controlled_by(seat) if p.card.name == name]


def _retarget_to(choice, label: str) -> int:
    return next(
        index for index, option in enumerate(choice.data.get("options") or choice.data.get("targets") or ())
        if label in str(option)
    )

def _slot(game: Game, seat: int, name: str) -> int:
    return game.battlefield_index_of(on_board(game, seat, name))


def _subtypes(permanent) -> set:
    from engine.layer_bridge import computed_types

    return {subtype.lower() for subtype in computed_types(permanent)[1]}


def _colors(permanent) -> set:
    from engine.layer_bridge import computed_colors

    return set(computed_colors(permanent))


def _finished_then(game: Game, check) -> None:
    """What the answer let happen, once every other seat still owed a part of
    the same resolution has given its default."""
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    _resolved_then(game, check)


def _resolved_then(game: Game, check) -> None:
    """What the answer let happen, once the stack it unblocked has resolved."""
    from tests.helpers import resolve_stack

    resolve_stack(game)
    check()

def _assert(condition: bool) -> None:
    assert condition


def _index_of(game: Game, seat: int, name: str) -> int:
    return names(game.players[seat].library).index(name)


# ---------------------------------------------------------------------------
# What is asked of every answer
# ---------------------------------------------------------------------------

def _owed(game: Game, kind: str):
    """The open choice of *kind* the answer path will take: the oldest one
    owed by an interactive seat, on whichever queue it sits."""
    for spec, choice in game.iter_pending_prompts():
        if (
            spec.kind == kind
            and choice.player_index in game.interactive_seats
            and spec.open_for(game, choice)
        ):
            return choice
    return None


def _queued(game: Game, choice) -> bool:
    return any(c is choice for c in game.pending_choices) or any(
        c is choice for c in game.pending_replacement_choices
    )


def wedges(game: Game, choice, held) -> list[str]:
    """Every way the answered *choice* is still in the game's way."""
    spec = spec_for(choice.kind)
    problems: list[str] = []
    if _queued(game, choice) and spec.open_for(game, choice):
        problems.append("(a) the answered choice is still owed on the queue")
    blocking = blocking_prompt(game, choice.player_index, "pass_priority", frozenset())
    if blocking is not None and blocking[1] is choice:
        problems.append("(b) the seat that answered is refused by the prompt it answered")
    if game.waiting_prompt() is choice:
        problems.append("(b) the game still waits on the answered prompt")
    # A held object with no prompt left about it, open or closed: nothing will
    # ever release it but the priority path's backstop. (Word of Command's
    # closed choice is still *about* its spell — the next pass finishes it.)
    if (
        held is not None
        and any(entry is held for entry in game.stack)
        and held.resolution_held
        and game.waiting_prompt() is None
        and not game.choices_for_stack_item(held)
    ):
        problems.append("(c) the object it held is still on the stack with nothing owed")
    return problems


def _answer_through_the_engine(game: Game, choice, response: dict) -> bool:
    seat = choice.player_index
    if any(c is choice for c in game.pending_replacement_choices):
        return game.resolve_replacement_choice(seat, response["option"], kind=choice.kind)
    # The answer path takes the oldest choice of the kind the seat owes; the
    # census answers that same one.
    assert game.pending_choice_of(choice.kind, seat) is choice
    return game.resolve_pending_choice(choice.kind, seat, **response)


def _armed(kind: str):
    s = SCENARIOS[kind]
    game = s.arm()
    choice = _owed(game, kind)
    assert choice is not None, (
        f"{kind}: {s.card} did not leave it owed by an interactive seat; "
        f"owed {[c.kind for c in game.pending_choices]}"
        f" + {[c.kind for c in game.pending_replacement_choices]}"
    )
    return s, game, choice


def _session_around(game: Game) -> str:
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 2600,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.pregame_phase = None
    session.current_turn = game.active_player_index
    session.joined_seats = set(range(len(game.players)))
    session.game = game
    return sid


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------

#: Kinds no card in the shipped pool reaches on a board this file can build,
#: each with why. Every registered kind is in exactly one of the two tables.
NOT_ARMED: dict[str, str] = {}

#: A registry that lost its kinds, or a table that lost its scenarios, would
#: pass every check below by examining nothing. Measured at round ``kg``: every
#: registered kind, 90 of 90, is armed by a board here.
_KINDS_FLOOR = 90


def test_every_kind_is_examined_or_says_why_not():
    assert not set(SCENARIOS) & set(NOT_ARMED)
    missing = set(CHOICE_SPECS) - set(SCENARIOS) - set(NOT_ARMED)
    assert not missing, f"registered kinds with no scenario and no reason: {sorted(missing)}"
    assert len(SCENARIOS) >= _KINDS_FLOOR, len(SCENARIOS)


@pytest.mark.parametrize("kind", sorted(SCENARIOS))
def test_an_answer_through_the_engine_leaves_the_queue(kind):
    s, game, choice = _armed(kind)
    held = choice.data.get("_stack_item")

    assert _answer_through_the_engine(game, choice, s.answer(game, choice)), (
        f"{kind}: the answer was refused"
    )

    assert wedges(game, choice, held) == [], kind
    if s.then is not None:
        s.then(game)


@pytest.mark.parametrize("kind", sorted(SCENARIOS))
def test_an_answer_through_the_route_leaves_the_queue(kind):
    s, game, choice = _armed(kind)
    spec = spec_for(kind)
    seat = choice.player_index
    held = choice.data.get("_stack_item")
    sid = _session_around(game)
    url = f"/api/sessions/{sid}/action"

    # Owed, so it gates: nothing but its answer is taken from that seat.
    if spec.blocked_detail is not None:
        refused = client.post(url, json={"seat": seat, "action": "pass_priority"})
        assert refused.status_code == 400 and refused.json()["detail"] == spec.blocked_detail

    answered = client.post(url, json={"seat": seat, "action": spec.action, **s.wire(game, choice)})
    assert answered.status_code == 200, f"{kind}: {answered.text}"

    assert wedges(game, choice, held) == [], kind
    if s.then is not None:
        s.then(game)

    # (b) on the wire: the seat's next action is not refused by the prompt it
    # has just answered (another prompt it now owes may refuse it — that is a
    # new decision, not this one).
    after = client.post(url, json={"seat": seat, "action": "pass_priority"})
    if after.status_code == 400 and after.json()["detail"] == spec.blocked_detail:
        blocking = blocking_prompt(game, seat, "pass_priority", frozenset())
        assert blocking is not None and blocking[1] is not choice, kind


@pytest.mark.parametrize("kind", sorted(SCENARIOS))
def test_the_default_an_engine_played_seat_takes_leaves_the_queue_too(kind):
    """The other answer path: ``take_choice_default``, which an AI seat at a
    human table is answered through (``web/prompts.auto_resolve_ai_prompts``).

    Its callers drop the choice again afterwards — after the object it held
    has already been offered its release — so the guarantee that matters is
    that the default itself leaves nothing owed."""
    _s, game, choice = _armed(kind)
    held = choice.data.get("_stack_item")

    game.take_choice_default(choice)

    assert wedges(game, choice, held) == [], kind


# ---------------------------------------------------------------------------
# The census, validated backwards: the defect re-introduced
# ---------------------------------------------------------------------------

#: The CR 614 queue's kinds. Its answer path (``resolve_replacement_choice``)
#: takes the choice off the queue *before* the resolver runs, so a resolver
#: there cannot leave it behind — there is no discard for it to forget.
_REPLACEMENT_QUEUE = frozenset(CHOICE_RESOLVERS)

#: Word of Command keeps its answered choice queued, closed, on purpose: it is
#: what holds the spell on the stack until the next pass finishes it.
_DESIGNED_HOLDS = frozenset({"word_of_command"})

_FORGETFUL = sorted(set(SCENARIOS) - _REPLACEMENT_QUEUE - _DESIGNED_HOLDS)


def _forgetful(kind: str):
    """*kind*'s spec with Urza's Destiny's defect put back: its resolver applies
    the answer and leaves its own choice where it was on the queue."""
    spec = CHOICE_SPECS[kind]

    def resolve(game, choice, response):
        position = next(
            (i for i, queued in enumerate(game.pending_choices) if queued is choice), None
        )
        accepted = spec.resolve(game, choice, response)
        if accepted and position is not None and not _queued(game, choice):
            game.pending_choices.insert(min(position, len(game.pending_choices)), choice)
        return accepted

    return dataclasses.replace(spec, resolve=resolve)


@pytest.mark.parametrize("kind", _FORGETFUL)
def test_with_the_seam_switched_off_the_census_names_a_resolver_that_forgets(kind, monkeypatch):
    """The census can see the defect: switch the queue's own close off, make
    the kind's resolver forget its choice, and the very checks above name it."""
    monkeypatch.setitem(CHOICE_SPECS, kind, _forgetful(kind))
    monkeypatch.setattr(PendingChoicesMixin, "_close_answered_choice", lambda self, choice: None)
    s, game, choice = _armed(kind)
    held = choice.data.get("_stack_item")

    assert _answer_through_the_engine(game, choice, s.answer(game, choice))

    found = wedges(game, choice, held)
    assert any(problem.startswith("(a)") for problem in found), (kind, found)
    # The refusal shows once nothing newer stands in front of it: an answer
    # that armed the next prompt of the same resolution (Scroll Rack's order,
    # the Kraken's "you may") is asked first, and the stale one waits behind
    # it. A notification (``hand_reveal``) refuses nothing either way.
    others = [c for _spec, c in game.iter_pending_prompts() if c is not choice]
    if spec_for(kind).blocked_detail is not None and not others:
        assert any(problem.startswith("(b)") for problem in found), (kind, found)


@pytest.mark.parametrize("kind", _FORGETFUL)
def test_with_the_seam_on_a_resolver_that_forgets_wedges_nothing(kind, monkeypatch):
    """…and the queue closes it: the same forgetful resolver, the seam on, and
    the answer leaves nothing owed and its effect done."""
    monkeypatch.setitem(CHOICE_SPECS, kind, _forgetful(kind))
    s, game, choice = _armed(kind)
    held = choice.data.get("_stack_item")

    assert _answer_through_the_engine(game, choice, s.answer(game, choice))

    assert wedges(game, choice, held) == [], kind
    if s.then is not None:
        s.then(game)


@pytest.mark.parametrize("seam", [False, True], ids=["seam-off", "seam-on"])
def test_liege_of_the_hollows_on_the_wire_with_and_without_the_seam(seam, monkeypatch):
    """The card the entry was found on, through the route a click takes. With
    the defect put back and the seam off, the seat that has paid is refused its
    next action by "Pay how much mana?" — the report Urza's Destiny filed. With
    the seam on, it is not."""
    # ``_resolve_pay_any_amount`` as Urza's Destiny found it: every step but
    # taking its own choice off the queue.
    monkeypatch.setitem(CHOICE_SPECS, "pay_any_amount", _forgetful("pay_any_amount"))
    if not seam:
        monkeypatch.setattr(PendingChoicesMixin, "_close_answered_choice", lambda self, choice: None)
    s, game, choice = _armed("pay_any_amount")
    spec = spec_for("pay_any_amount")
    seat = choice.player_index
    sid = _session_around(game)
    url = f"/api/sessions/{sid}/action"

    answered = client.post(url, json={"seat": seat, "action": spec.action, **s.wire(game, choice)})
    assert answered.status_code == 200, answered.text
    after = client.post(url, json={"seat": seat, "action": "pass_priority"})

    blocking = blocking_prompt(game, seat, "pass_priority", frozenset())
    refused_by_its_own_answer = (
        after.status_code == 400 and after.json()["detail"] == spec.blocked_detail
        and blocking is not None and blocking[1] is choice
    )
    assert refused_by_its_own_answer is (not seam), after.text

