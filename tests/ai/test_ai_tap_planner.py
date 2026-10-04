"""The AI's land-tapping planner asks the engine what each land makes.

``_plan_land_taps`` used to read each land as one printed symbol
(``produced_mana[0]``) and every executor tapped with the seam's default colour
"G". Measured at NEM: a Forest under Deep Water's swap makes {U}, a Forest
carrying Overlaid Terrain's granted "{T}: Add two mana of any one color" makes
two of any colour, and a dual land can make its second colour — the planner saw
none of it, so the seat held castable spells all game. It now reads
``Game._land_payment_colors`` (the hook the optional-pay planner and the
client's colour prompt read), counts a granted ability's amount, and carries
the colour it planned to the tap (``land_tap_colors`` / ``planned_tap_color``).
"""
from __future__ import annotations

from engine.ai_policy import choose_cast_action, planned_tap_color
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack


def _duel(set_pool, hand, mine):
    lea = set_pool("LEA")
    me = PlayerState(
        name="AI", hand=list(hand), library=[lea["Island"]] * 10,
        battlefield=[_nosick(Permanent(card=card)) for card in mine],
    )
    them = PlayerState(name="Opp", library=[lea["Island"]] * 10)
    game = Game(players=[me, them])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game._settle()
    return game


def _execute(game, action):
    """Tap and cast exactly as the simulator's executor does."""
    for position, slot in enumerate(action.land_tap_indices):
        land = game.permanent_at(0, slot)
        assert game.tap_land_for_mana(
            0, land.card.name, chosen_color=planned_tap_color(action, position),
            permanent_index=slot,
        )
    return game.cast_from_hand(
        0, action.card_name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )


def test_a_seat_wide_swap_is_planned_through(set_pool):
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [set_pool("DRK")["Deep Water"], lea["Forest"], lea["Forest"], lea["Forest"]],
    )
    game.players[0].mana_pool["U"] = 1
    assert game.activate_permanent_ability(0, "Deep Water", permanent_index=0).supported
    resolve_stack(game)

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Prodigal Sorcerer"
    assert action.land_tap_colors == ("U", "U", "U")
    assert _execute(game, action).supported


def test_a_granted_two_mana_ability_is_planned_at_its_amount(set_pool):
    """Two Forests under Overlaid Terrain make four mana between them; read as
    one apiece, a three-drop was out of reach."""
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [set_pool("NEM")["Overlaid Terrain"], lea["Forest"], lea["Forest"]],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Prodigal Sorcerer"
    assert len(action.land_tap_indices) == 2 and action.land_tap_colors[0] == "U"
    assert _execute(game, action).supported
    assert any(p.card.name == "Prodigal Sorcerer" for p in game.controlled_by(0))


def test_a_dual_land_is_asked_for_the_colour_the_plan_counted(set_pool):
    lea = set_pool("LEA")
    game = _duel(set_pool, [lea["Grizzly Bears"]], [lea["Taiga"], lea["Mountain"]])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Grizzly Bears"
    by_land = {
        game.permanent_at(0, slot).card.name: planned_tap_color(action, position)
        for position, slot in enumerate(action.land_tap_indices)
    }
    assert by_land == {"Taiga": "G", "Mountain": "R"}
    assert _execute(game, action).supported


def test_a_board_of_basics_is_planned_exactly_as_before(set_pool):
    """The greedy order is unchanged for single-colour lands: the coloured pip
    first, from the first land that makes it, then the generic in board order."""
    lea = set_pool("LEA")
    game = _duel(
        set_pool, [lea["Prodigal Sorcerer"]],
        [lea["Forest"], lea["Island"], lea["Swamp"], lea["Island"]],
    )

    action = choose_cast_action(game, 0)

    assert action.land_tap_indices == (1, 0, 2)
    assert action.land_tap_colors == ("U", "G", "B")


# --- W3G4: what the planner counts is what the tap makes ---------------------
#
# Free mana hid every disagreement between `_plan_land_taps` and the tap seam:
# the simulator never paid, so a plan that counted a mana the tap did not make
# cost nothing. Once its games enforced costs, the first re-baseline refused
# 427 casts "insufficient mana" — a storage land with no counter (Sand Silos),
# a painland tapped for its default {C} when the plan counted {U} (Underground
# River), a land whose coloured ability costs mana (Henge of Ramos), Mishra's
# Workshop's artifact-only mana paying for a creature. The web app's AI seat,
# which always enforced costs, had every one of them.

from types import SimpleNamespace as _W3g4Plan

from engine.ai_policy import (_land_mana_is_unplannable as _w3g4_unplannable,
                              _land_symbols as _w3g4_land_symbols,
                              choose_activation_action as _w3g4_choose_activation,
                              tap_planned_lands as _w3g4_tap_planned_lands)
from engine.card_loader import load_cards as _w3g4_load_cards
from engine.card_loader import manifest_set_paths as _w3g4_set_paths
from engine.named_counters import add_counters as _w3g4_add_counters
from engine.named_counters import counters_on as _w3g4_counters_on
from engine.named_counters import remove_counters as _w3g4_remove_counters
from tests.helpers import _mk_card as _w3g4_mk_card
from tests.helpers import _mk_creature_card as _w3g4_mk_creature


def _w3g4_alone(card):
    """*card* alone on the AI's battlefield in its main phase, untapped and
    not summoning sick, costs enforced."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    permanent = game.permanent_at(0, 0)
    if permanent is not None:
        permanent.tapped = False
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanent


def _w3g4_cast(game, action):
    """Pay and cast through the executor the simulator and the web AI share."""
    _w3g4_tap_planned_lands(game, 0, action)
    return game.cast_from_hand(
        0, action.card_name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids, x_value=action.x_value,
    )


def test_every_land_makes_every_symbol_the_planner_counts_it_for():
    """Pool-wide, both manifest roles: each land alone on a board, and for
    every symbol `_land_symbols` says it makes, the shared executor taps it for
    that symbol and the symbol is in the pool. Lands the planner leaves out
    (the seam would refuse them, or their mana is restricted or counted off
    the board) are not asked. Validated backwards: on the tree before this
    change 113 of the 280 symbols checked over 166 lands were not made —
    every painland's colours, every storage and depletion land, Henge of
    Ramos' and the Mercadian lands' five colours, Bazaar of Baghdad's {C}."""
    cards = {}
    for path in _w3g4_set_paths(include_measured=True):
        for card in _w3g4_load_cards(path):
            cards.setdefault(card.name, card)
    examined, checked, unmade = [], 0, []
    for name, card in sorted(cards.items()):
        if card.primary_type != "land":
            continue
        game, land = _w3g4_alone(card)
        if land is None or game.land_mana_tap_refusal(land) is not None:
            continue
        if _w3g4_unplannable(game, land):
            continue
        examined.append(name)
        for symbol in _w3g4_land_symbols(game, land):
            game, land = _w3g4_alone(card)
            _w3g4_tap_planned_lands(
                game, 0, _W3g4Plan(land_tap_indices=(0,), land_tap_colors=(symbol,)),
            )
            checked += 1
            if game.players[0].mana_pool.get(symbol, 0) < 1:
                unmade.append((name, symbol))

    assert len(examined) >= 100 and checked >= 180, (len(examined), checked)
    assert {"Underground River", "Karplusan Forest", "City of Brass", "Taiga"} <= set(examined)
    assert unmade == [], unmade


def test_a_painland_is_tapped_by_the_ability_that_makes_the_colour(set_pool):
    """"{T}: Add {C}." first, "{T}: Add {R} or {G}. This land deals 1 damage to
    you." second: the seam runs the first unless told, so a Grizzly Bears
    planned on a Karplusan Forest's {G} was refused. And a generic pip is paid
    with the painless {C}, not the colour the summary lists first."""
    lea, ice = set_pool("LEA"), set_pool("ICE")
    game = _duel(set_pool, [lea["Grizzly Bears"]], [ice["Karplusan Forest"], lea["Mountain"]])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Grizzly Bears"
    assert _w3g4_cast(game, action).supported, game.log[-4:]
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert game.players[0].life == 19, "the coloured ability's damage was dealt"

    rock = _w3g4_mk_card(name="Plain Rock", mana_cost="{1}", type_line="Artifact")
    game = _duel(set_pool, [rock], [ice["Underground River"]])
    action = choose_cast_action(game, 0)
    assert action is not None and _w3g4_cast(game, action).supported
    assert game.players[0].life == 20, "a generic {1} was paid with the painful colour"


def test_a_land_whose_colour_costs_mana_is_not_counted_as_that_colour(set_pool):
    """Henge of Ramos: "{T}: Add {C}. {2}, {T}: Add one mana of any color." Its
    summary is five colours and its tap makes {C}; counted as red, the plan
    tapped it for a Shock-shaped pip and the cast was refused."""
    lea = set_pool("LEA")
    henge = set_pool("MMQ")["Henge of Ramos"]
    alone = _duel(set_pool, [lea["Lightning Bolt"]], [henge])
    assert choose_cast_action(alone, 0) is None
    game = _duel(set_pool, [lea["Lightning Bolt"]], [henge, lea["Mountain"]])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Lightning Bolt"
    assert [game.permanent_at(0, slot).card.name for slot in action.land_tap_indices] == ["Mountain"]
    assert _w3g4_cast(game, action).supported


def test_a_land_the_seam_will_not_tap_is_not_planned(set_pool):
    """A storage land with no counter (Sand Silos) and Mishra's Workshop's
    artifact-only mana are not mana for an Unsummon or a creature."""
    lea = set_pool("LEA")
    game = _duel(set_pool, [lea["Unsummon"]], [set_pool("FEM")["Sand Silos"]])
    assert game.land_mana_tap_refusal(game.permanent_at(0, 0)) == "priced_mana_ability"
    assert choose_cast_action(game, 0) is None

    workshop = set_pool("ATQ")["Mishra's Workshop"]
    game = _duel(set_pool, [lea["Grizzly Bears"]], [workshop, lea["Forest"]])
    assert choose_cast_action(game, 0) is None
    game = _duel(set_pool, [lea["Grizzly Bears"]], [workshop, lea["Forest"], lea["Forest"]])
    action = choose_cast_action(game, 0)
    assert action is not None and _w3g4_cast(game, action).supported


def test_detonate_announces_the_x_its_target_fixes(set_pool):
    """"Destroy target artifact with mana value X. … deals X damage to that
    artifact's controller." X was sized as the most the lands could pay and
    the gate refused it against a cheaper artifact — at least 15 times in the
    default seeded ATQ run once costs were enforced. The target's mana value
    is the X, and the cost is planned against it."""
    lea = set_pool("LEA")
    game = _duel(set_pool, [set_pool("ATQ")["Detonate"]], [lea["Mountain"]] * 5)
    game._put_permanent_onto_battlefield(1, Permanent(card=lea["Sol Ring"]), None)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Detonate"
    assert action.x_value == 1 and len(action.land_tap_indices) == 2
    assert _w3g4_cast(game, action).supported
    resolve_stack(game)
    assert [card.name for card in game.players[1].graveyard] == ["Sol Ring"]
    assert game.players[1].life == 19


def test_an_ability_whose_counter_cost_cannot_be_paid_is_not_proposed(set_pool):
    """"{T}, Remove a javelin counter from this creature: …" with none left is
    refused with nothing paid; the chooser proposed it every main phase."""
    lea = set_pool("LEA")
    javelineers = set_pool("FEM")["Icatian Javelineers"]
    game = _duel(set_pool, [], [javelineers, lea["Plains"]])
    game._put_permanent_onto_battlefield(1, Permanent(card=_w3g4_mk_creature("Their Elf", 1, 1)), None)
    thrower = next(p for p in game.controlled_by(0) if p.card.name == "Icatian Javelineers")
    _w3g4_remove_counters(thrower, "javelin", _w3g4_counters_on(thrower, "javelin"))
    assert _w3g4_counters_on(thrower, "javelin") == 0
    assert _w3g4_choose_activation(game, 0) is None
    _w3g4_add_counters(thrower, "javelin", 1)
    action = _w3g4_choose_activation(game, 0)
    assert action is not None and action.permanent_name == "Icatian Javelineers"
