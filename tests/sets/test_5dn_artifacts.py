"""Fifth Dawn artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.
#
# Sunburst on a noncreature (CR 702.44a: charge counters), each card cast
# through the real cast path with costs enforced. Six of these arrived
# "supported" entering with no counters at all.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=()):
    """Two seats on seat 0's first main phase, costs enforced."""
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_cast(game, name, pool, **announce):
    game.players[0].mana_pool.update(pool)
    result = game.cast_from_hand(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    _w1g1_settle(game)
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g1_put(game, card, seat):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_activate(game, name, pool=None, **announce):
    if pool:
        game.players[0].mana_pool.update(pool)
    result = game.activate_permanent_ability(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    _w1g1_settle(game)
    return result


def test_w1g1_opaline_bracers_grows_by_its_charge_counters(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Opaline Bracers"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    bracers = _w1g1_cast(game, "Opaline Bracers", {"R": 1, "G": 1, "W": 1, "C": 1})
    assert _w1g1_counters_on(bracers, "charge") == 3
    assert _w1g1_counters_on(bracers, "+1/+1") == 0
    _w1g1_activate(game, "Opaline Bracers", {"C": 2}, target_permanent_ids=[bears.permanent_id])
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g1_baton_of_courage_is_cast_on_the_opponent_s_turn(set_pool):
    """Flash: cast in the opponent's turn with three colours, then a charge
    counter is a +1/+1 for the turn."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Baton of Courage"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    game.start_turn(1)
    _w1g1_settle(game)
    baton = _w1g1_cast(game, "Baton of Courage", {"R": 1, "G": 1, "W": 1})
    assert _w1g1_counters_on(baton, "charge") == 3
    _w1g1_activate(game, "Baton of Courage", target_permanent_ids=[bears.permanent_id])
    assert _w1g1_counters_on(baton, "charge") == 2
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g1_clearwater_goblet_gains_its_charge_counters_each_upkeep(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Clearwater Goblet"]])
    goblet = _w1g1_cast(game, "Clearwater Goblet", {"W": 1, "U": 1, "B": 1, "C": 2})
    assert _w1g1_counters_on(goblet, "charge") == 3
    game.start_turn(1)
    _w1g1_settle(game)
    assert game.players[0].life == 20
    game.start_turn(0)
    _w1g1_settle(game)
    assert game.players[0].life == 23


def test_w1g1_clearwater_goblet_s_gain_is_a_person_s_to_decline(set_pool):
    """"You may": a person is asked (the optional offer) and may say no."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Clearwater Goblet"]])
    game.interactive_seats = {0}
    _w1g1_cast(game, "Clearwater Goblet", {"W": 1, "U": 1, "C": 3})
    game.start_turn(1)
    _w1g1_settle(game)
    game.start_turn(0)
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert game.resolve_pending_choice("optional_pay", 0, accept=False, option=None)
    _w1g1_settle(game)
    assert game.players[0].life == 20


def test_w1g1_engineered_explosives_x_buys_colors_not_counters(set_pool):
    """The rulings (2020-08-07): X lets more colours be spent, and the counters
    are the colours — X=3 paid with two colours and a colourless is two. The
    sacrifice reads the counters the Explosives left with (CR 608.2h)."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Engineered Explosives"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    explosives = _w1g1_cast(
        game, "Engineered Explosives", {"U": 1, "B": 1, "C": 1}, x_value=3,
    )
    assert _w1g1_counters_on(explosives, "charge") == 2
    _w1g1_activate(game, "Engineered Explosives", {"C": 2})
    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(giant)


def test_w1g1_engineered_explosives_at_zero_destroys_mana_value_zero(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Engineered Explosives"]])
    lotus = _w1g1_put(game, lea["Black Lotus"], 1)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    explosives = _w1g1_cast(game, "Engineered Explosives", {}, x_value=0)
    assert _w1g1_counters_on(explosives, "charge") == 0
    _w1g1_activate(game, "Engineered Explosives", {"C": 2})
    assert not game.is_on_battlefield(lotus)
    assert game.is_on_battlefield(bears)


def test_w1g1_heliophial_deals_the_counters_it_was_sacrificed_with(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Heliophial"]])
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    heliophial = _w1g1_cast(game, "Heliophial", {"W": 1, "U": 1, "B": 1, "C": 2})
    assert _w1g1_counters_on(heliophial, "charge") == 3
    _w1g1_activate(game, "Heliophial", {"C": 2}, target_permanent_ids=[giant.permanent_id])
    assert any("Heliophial dealt 3 damage to Hill Giant" in line for line in game.log)
    assert not game.is_on_battlefield(giant)


def test_w1g1_infused_arrows_shrinks_by_the_counters_it_removes(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Infused Arrows"]])
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    arrows = _w1g1_cast(game, "Infused Arrows", {"W": 1, "U": 1, "B": 1, "C": 1})
    assert _w1g1_counters_on(arrows, "charge") == 3
    _w1g1_activate(game, "Infused Arrows", target_permanent_ids=[giant.permanent_id], x_value=2)
    assert _w1g1_counters_on(arrows, "charge") == 1
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)


def test_w1g1_pentad_prism_makes_a_mana_per_charge_counter_and_stays(set_pool):
    """Once it has run out of charge counters it remains on the battlefield
    (2020-08-07)."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Pentad Prism"]])
    prism = _w1g1_cast(game, "Pentad Prism", {"R": 1, "G": 1})
    assert _w1g1_counters_on(prism, "charge") == 2
    _w1g1_activate(game, "Pentad Prism", mana_color="U")
    _w1g1_activate(game, "Pentad Prism", mana_color="B")
    assert game.players[0].mana_pool.get("U") == 1
    assert game.players[0].mana_pool.get("B") == 1
    refused = game.activate_permanent_ability(0, "Pentad Prism", mana_color="W")
    assert not refused.supported
    assert game.is_on_battlefield(prism)

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine import ai_simulator as _w1g2_ai_simulator
from engine.ai_policy import choose_cast_action as _w1g2_choose_cast_action
from engine.ai_policy import choose_land_drop as _w1g2_choose_land_drop
from engine.cast_permissions import playable_from_zones as _w1g2_playable_from_zones
from engine.cast_timing import casts_at_instant_speed as _w1g2_casts_at_instant_speed
from engine.cost_modifiers import cast_mana_charge as _w1g2_cast_mana_charge
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle

_W1G2_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g2_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=(),
                graveyard=(), mana=True):
    """Two seats on seat 0's first main phase; *mine* / *theirs* placed, not
    summoning sick."""
    lea = set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                         library=[lea["Island"]] * 12),
        _W1G2PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 12),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set()
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G2Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    _w1g2_settle(game)
    return game


def _w1g2_basics(set_pool, names=_W1G2_BASICS):
    lea = set_pool("LEA")
    return [lea[name] for name in names]


def _w1g2_tap_lands(game, seat=0):
    for permanent in list(game.controlled_by(seat)):
        if permanent.has_type("land") and not permanent.tapped:
            refused = game.tap_land_for_mana_or_refusal(
                seat, permanent.card.name, permanent_id=permanent.permanent_id,
            )
            assert refused is None, refused


def _w1g2_names(game, seat):
    return [permanent.card.name for permanent in game.controlled_by(seat)]


def _w1g2_charge(game, seat, card):
    return {k: v for k, v in _w1g2_cast_mana_charge(game, seat, card).items() if v}


# --- Fist of Suns ----------------------------------------------------------

def test_w1g2_fist_of_suns_casts_its_controllers_six_drop_for_wubrg(set_pool):
    """"You may pay {W}{U}{B}{R}{G} rather than pay the mana cost for spells
    you cast." Craw Wurm ({4}{G}{G}) off five lands of five colours."""
    fist = set_pool("5DN")["Fist of Suns"]
    wurm = set_pool("LEA")["Craw Wurm"]
    game = _w1g2_table(set_pool, hand=[wurm], mine=[fist, *_w1g2_basics(set_pool)])
    (offer,) = game.cast_cost_offers(0, wurm, spell_hand_index=0)
    assert offer["label"] == "pay {W}{U}{B}{R}{G}"
    assert offer["granted_by"] == "Fist of Suns"
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, "Craw Wurm", alternative_cost=True)

    assert result.supported, result.details
    assert "Craw Wurm" in _w1g2_names(game, 0)
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_fist_of_suns_offers_nothing_to_its_controllers_opponent(set_pool):
    """"…for spells **you** cast" (CR 109.5): Bob's Craw Wurm under Alice's
    Fist has no alternative cost, and announcing one is refused."""
    fist = set_pool("5DN")["Fist of Suns"]
    wurm = set_pool("LEA")["Craw Wurm"]
    game = _w1g2_table(set_pool, opponent_hand=[wurm], mine=[fist],
                       theirs=_w1g2_basics(set_pool))
    assert game.applicable_alternative_costs(1, wurm) == ()
    assert game.cast_cost_offers(1, wurm, spell_hand_index=0) == []
    _w1g2_tap_lands(game, seat=1)

    result = game.cast_from_hand(1, "Craw Wurm", alternative_cost=True)

    assert not result.supported
    assert [held.name for held in game.players[1].hand] == ["Craw Wurm"]


def test_w1g2_fist_of_suns_locks_an_x_spell_at_zero(set_pool):
    """The ruling (2014-02-01): "If you pay {W}{U}{B}{R}{G} rather than pay
    the mana cost of a spell with {X} in its mana cost, the only legal choice
    for X is 0." A Fireball asked for X=3 deals nothing."""
    fist = set_pool("5DN")["Fist of Suns"]
    fireball = set_pool("LEA")["Fireball"]
    game = _w1g2_table(set_pool, hand=[fireball], mine=[fist, *_w1g2_basics(set_pool)])
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(
        0, "Fireball", target_player_index=1, x_value=3, alternative_cost=True,
    )

    assert result.supported, result.details
    assert game.players[1].life == 20
    assert "Fireball dealt 0 damage to Bob" in game.log


def test_w1g2_a_bringer_under_fist_of_suns_is_offered_one_price(set_pool):
    """CR 118.9a: one alternative cost per spell, and the Bringer's printed
    {W}{U}{B}{R}{G} and the Fist's grant are the same price — one offer, and
    a bare announcement takes it."""
    fist = set_pool("5DN")["Fist of Suns"]
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    game = _w1g2_table(set_pool, hand=[red], mine=[fist, *_w1g2_basics(set_pool)])
    assert len(game.cast_cost_offers(0, red, spell_hand_index=0)) == 1
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, "Bringer of the Red Dawn", alternative_cost=True)

    assert result.supported, result.details
    assert "Bringer of the Red Dawn" in _w1g2_names(game, 0)


def test_w1g2_fist_of_suns_prices_a_graveyard_cast_too(set_pool):
    """The grant covers the spells its controller casts from wherever they
    are cast: under Yawgmoth's Agenda, Craw Wurm comes out of the graveyard
    for {W}{U}{B}{R}{G}."""
    fist = set_pool("5DN")["Fist of Suns"]
    agenda = set_pool("INV")["Yawgmoth's Agenda"]
    wurm = set_pool("LEA")["Craw Wurm"]
    game = _w1g2_table(set_pool, graveyard=[wurm],
                       mine=[fist, agenda, *_w1g2_basics(set_pool)])
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, "Craw Wurm", from_zone="graveyard", alternative_cost=True)

    assert result.supported, result.details
    assert "Craw Wurm" in _w1g2_names(game, 0)
    assert game.players[0].graveyard == []


def test_w1g2_a_kicker_is_paid_on_top_of_fist_of_suns(set_pool):
    """The ruling (2004-12-01): "You can pay additional costs, such as
    kicker, in addition to this alternative cost" (CR 118.9d). Benalish
    Lancer kicked costs {W}{U}{B}{R}{G} plus {2}{W}: eight lands pay it and
    it enters with its two +1/+1 counters."""
    fist = set_pool("5DN")["Fist of Suns"]
    lancer = set_pool("INV")["Benalish Lancer"]
    lands = _w1g2_basics(set_pool, _W1G2_BASICS + ("Plains",) * 3)
    game = _w1g2_table(set_pool, hand=[lancer], mine=[fist, *lands])
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(
        0, "Benalish Lancer", alternative_cost=True,
        optional_cost_payments={"{2}{W}": 1},
    )

    assert result.supported, result.details
    _w1g2_settle(game)
    (placed,) = [p for p in game.controlled_by(0) if p.card.name == "Benalish Lancer"]
    assert placed.effective_power == 4
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_the_ai_takes_fist_of_suns_price_off_five_colours(set_pool):
    """Five lands of five colours and a six-drop: the mana cost is out of
    reach and the AI announces the Fist's price."""
    fist = set_pool("5DN")["Fist of Suns"]
    wurm = set_pool("LEA")["Craw Wurm"]
    game = _w1g2_table(set_pool, hand=[wurm], mine=[fist, *_w1g2_basics(set_pool)])

    action = _w1g2_choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Craw Wurm"
    assert action.alternative_cost and len(action.land_tap_indices) == 5


# --- Vedalken Orrery -------------------------------------------------------

def test_w1g2_vedalken_orrery_gives_its_controllers_spells_flash_and_no_land(set_pool):
    """"You may cast spells as though they had flash." Every spell its
    controller casts (CR 702.8a) — a creature, a sorcery — and no land, which
    is never cast (CR 305.1); its controller's alone (CR 109.5)."""
    lea = set_pool("LEA")
    orrery = set_pool("5DN")["Vedalken Orrery"]
    game = _w1g2_table(set_pool, mine=[orrery], mana=False)

    assert _w1g2_casts_at_instant_speed(lea["Grizzly Bears"], game, 0)
    assert _w1g2_casts_at_instant_speed(lea["Wrath of God"], game, 0)
    assert not _w1g2_casts_at_instant_speed(lea["Forest"], game, 0)
    assert not _w1g2_casts_at_instant_speed(lea["Grizzly Bears"], game, 1)


def test_w1g2_an_ai_seat_flashes_a_creature_in_at_the_opponents_end_step(set_pool):
    """The ruling (2004-12-01): its controller "can cast nonland artifact,
    creature, enchantment, and sorcery cards any time they could cast an
    instant … including on other players' turns". AI-B holds Grizzly Bears
    through AI-A's turn and casts it in AI-A's end step with the Orrery out —
    and without it, holds it."""
    lea = set_pool("LEA")
    orrery = set_pool("5DN")["Vedalken Orrery"]

    def end_step(with_orrery):
        players = [
            _W1G2PlayerState(name="AI-A", library=[lea["Forest"]] * 8),
            _W1G2PlayerState(name="AI-B", hand=[lea["Grizzly Bears"]],
                             library=[lea["Forest"]] * 8),
        ]
        game = _w1g2_ai_simulator._SimulatedGame(
            players=players, enforce_mana_costs=True,
            prompt_driver=_w1g2_ai_simulator._resolve_pending_choices,
        )
        report = _w1g2_ai_simulator.SimulationReport(
            games_requested=1, games_completed=0, interaction_count=0,
        )
        game.priority_driver = _w1g2_ai_simulator._priority_answerer(game, report, 1, [1])
        game.turn = 3
        game.active_player_index = 0
        board = [lea["Forest"], lea["Forest"]] + ([orrery] if with_orrery else [])
        for card in board:
            permanent = _W1G2Permanent(card=card)
            game._put_permanent_onto_battlefield(1, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
        game._set_phase_and_step("ending", "end")
        game._resolve_priority_window()
        return game

    flashed = end_step(True)
    assert "Grizzly Bears" in _w1g2_names(flashed, 1)
    held = end_step(False)
    assert "Grizzly Bears" not in _w1g2_names(held, 1)
    assert [card.name for card in held.players[1].hand] == ["Grizzly Bears"]


# --- Crucible of Worlds ----------------------------------------------------

def test_w1g2_crucible_of_worlds_plays_a_land_from_the_graveyard_as_the_land_drop(set_pool):
    """"You may play lands from your graveyard." The Forest comes out of the
    graveyard as the turn's land play (CR 305.2) — the second one, the
    Island beside it, is refused — and the Grizzly Bears card stays put."""
    lea = set_pool("LEA")
    crucible = set_pool("5DN")["Crucible of Worlds"]
    # Costs on: the engine holds a land play to CR 305.2 where it enforces costs.
    game = _w1g2_table(set_pool, mine=[crucible],
                       graveyard=[lea["Forest"], lea["Grizzly Bears"], lea["Island"]])
    offered = [entry["name"] for entry in _w1g2_playable_from_zones(game, 0)]
    assert offered == ["Forest", "Island"]

    played = game.cast_from_hand(0, "Forest", from_zone="graveyard")

    assert played.supported, played.details
    assert "Forest" in _w1g2_names(game, 0)
    again = game.cast_from_hand(0, "Island", from_zone="graveyard")
    assert not again.supported
    refused = game.cast_from_hand(0, "Grizzly Bears", from_zone="graveyard")
    assert not refused.supported
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears", "Island"]


def test_w1g2_crucible_of_worlds_opens_only_its_controllers_graveyard(set_pool):
    """"You may" is the Crucible's controller (CR 109.5): Bob's Forest in
    Bob's graveyard is not his to play under Alice's Crucible."""
    lea = set_pool("LEA")
    crucible = set_pool("5DN")["Crucible of Worlds"]
    game = _w1g2_table(set_pool, mine=[crucible], mana=False)
    game.players[1].graveyard.append(lea["Forest"])

    assert _w1g2_playable_from_zones(game, 1) == []


def test_w1g2_the_ai_plays_its_land_drop_out_of_the_graveyard_under_crucible(set_pool):
    """No land in hand, a Forest in the graveyard: the AI's land drop is the
    Forest, played from there."""
    lea = set_pool("LEA")
    crucible = set_pool("5DN")["Crucible of Worlds"]
    game = _w1g2_table(set_pool, hand=[lea["Grizzly Bears"]], mine=[crucible],
                       graveyard=[lea["Forest"]])

    action = _w1g2_choose_land_drop(game, 0)

    assert action is not None and action.card_name == "Forest"
    assert action.from_zone == "graveyard"


# --- Mycosynth Golem -------------------------------------------------------

def test_w1g2_mycosynth_golem_discounts_artifact_creature_spells_and_nothing_else(set_pool):
    """"Artifact creature spells you cast have affinity for artifacts." Three
    artifacts (the Golem and two Ornithopters): Juggernaut ({4}) costs {1};
    Frogmite's own affinity and the granted one both apply (CR 702.41b) and
    it costs nothing; a Sol Ring (an artifact, not a creature) and Grizzly
    Bears (a creature, not an artifact) cost what they print — and Bob's
    Juggernaut is not a spell Alice casts."""
    lea, mrd, atq = set_pool("LEA"), set_pool("MRD"), set_pool("ATQ")
    golem = set_pool("5DN")["Mycosynth Golem"]
    game = _w1g2_table(
        set_pool, mine=[golem, atq["Ornithopter"], atq["Ornithopter"]],
        theirs=[atq["Ornithopter"]],
    )

    assert _w1g2_charge(game, 0, lea["Juggernaut"]) == {"generic": 1}
    assert _w1g2_charge(game, 0, mrd["Frogmite"]) == {}
    assert _w1g2_charge(game, 0, lea["Sol Ring"]) == {"generic": 1}
    assert _w1g2_charge(game, 0, lea["Grizzly Bears"]) == {"generic": 1, "G": 1}
    assert _w1g2_charge(game, 1, lea["Juggernaut"]) == {"generic": 4}


def test_w1g2_two_mycosynth_golems_are_two_instances_of_affinity(set_pool):
    """The ruling (2004-12-01): "Two or more instances of the affinity ability
    are cumulative." Two Golems are two artifacts and two grants: Juggernaut
    ({4}) is {4} less, and a Myr Enforcer ({7}, its own affinity) is free."""
    lea, mrd = set_pool("LEA"), set_pool("MRD")
    golem = set_pool("5DN")["Mycosynth Golem"]
    game = _w1g2_table(set_pool, mine=[golem, golem])

    assert _w1g2_charge(game, 0, lea["Juggernaut"]) == {}
    assert _w1g2_charge(game, 0, mrd["Myr Enforcer"]) == {"generic": 1}


def test_w1g2_a_juggernaut_is_cast_for_one_under_mycosynth_golem(set_pool):
    """The discount is the price the cast path charges, not only the one it
    shows: one Island pays the Juggernaut with three artifacts out."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    golem = set_pool("5DN")["Mycosynth Golem"]
    game = _w1g2_table(
        set_pool, hand=[lea["Juggernaut"]],
        mine=[golem, atq["Ornithopter"], atq["Ornithopter"], lea["Island"]],
    )
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, "Juggernaut")

    assert result.supported, result.details
    assert "Juggernaut" in _w1g2_names(game, 0)
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_mycosynth_golems_own_affinity_counts_the_artifacts_out(set_pool):
    """The Golem's printed "Affinity for artifacts": {11} less one per
    artifact its caster controls — five Ornithopters, {6}."""
    atq = set_pool("ATQ")
    golem = set_pool("5DN")["Mycosynth Golem"]
    game = _w1g2_table(set_pool, mine=[atq["Ornithopter"]] * 5)

    assert _w1g2_charge(game, 0, golem) == {"generic": 6}
# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_station_table(set_pool, *, graveyard, interactive=()):
    """Salvaging Station on seat 0's board, a Grizzly Bears on each side to
    die, and *graveyard* seat 0's."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    station = _W1G3Permanent(card=set_pool("5DN")["Salvaging Station"])
    game._put_permanent_onto_battlefield(0, station, None)
    bears = []
    for seat in (0, 1):
        bear = _W1G3Permanent(card=lea["Grizzly Bears"])
        game._put_permanent_onto_battlefield(seat, bear, None)
        bears.append(bear)
    _w1g3_settle(game)
    return game, station, bears


def _w1g3_bolt(game, set_pool, victim):
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, (result, game.log[-4:])


def test_w1g3_salvaging_station_returns_a_small_noncreature_artifact(set_pool):
    """"{T}: Return target noncreature artifact card with mana value 1 or less
    from your graveyard to the battlefield." The spec carries both narrowings;
    the Ornithopter (an artifact *creature* at 0) and the Rod of Ruin (at 4)
    are refused at announcement (CR 602.2b); the Sol Ring enters, the Station
    taps."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, _bears = _w1g3_station_table(
        set_pool, graveyard=[atq["Ornithopter"], lea["Rod of Ruin"], lea["Sol Ring"]],
    )
    spec = _w1g3_activation_spec(_w1g3_compile(station.card).activated_abilities[0])
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]
    assert spec["graveyard_mana_value"] == {"op": "le", "value": 1}
    assert spec["graveyard_excluded_types"] == ["creature"]

    for slot in (0, 1):
        refused = game.activate_permanent_ability(
            0, "Salvaging Station", target_player_index=0,
            target_graveyard_indices=[slot],
        )
        assert not refused.supported, slot
    assert not station.tapped
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[2],
    ).supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert station.tapped
    assert any(p.card.name == "Sol Ring" for p in alice.battlefield)
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Rod of Ruin"]


def test_w1g3_salvaging_station_untaps_when_a_creature_dies_and_goes_again(set_pool):
    """"Whenever a creature dies, you may untap this artifact." Any creature,
    the opponent's too. Untapped by the death, a bare activation (no slot
    named, as an AI seat makes it) takes the legal Black Lotus — never the
    Ornithopter first in the pile."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, bears = _w1g3_station_table(
        set_pool,
        graveyard=[atq["Ornithopter"], lea["Sol Ring"], lea["Black Lotus"]],
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[1],
    ).supported
    _w1g3_settle(game)
    assert station.tapped

    _w1g3_bolt(game, set_pool, bears[1])
    _w1g3_settle(game)
    assert not station.tapped, game.log[-6:]

    assert game.activate_permanent_ability(0, "Salvaging Station").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert {p.card.name for p in alice.battlefield} >= {"Sol Ring", "Black Lotus"}
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Lightning Bolt"]


def test_w1g3_salvaging_station_untap_is_a_choice_an_asked_seat_may_decline(set_pool):
    """The "may" is asked of an interactive seat, and declined leaves the
    Station tapped."""
    lea = set_pool("LEA")
    game, station, bears = _w1g3_station_table(
        set_pool, graveyard=[lea["Sol Ring"]], interactive={0},
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert station.tapped
    _w1g3_bolt(game, set_pool, bears[0])
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay", game.log[-6:]
    assert asked.data["card_name"] == "Salvaging Station"
    assert game.confirm_optional_pay(0, "Salvaging Station", accept=False)
    _w1g3_settle(game)
    assert station.tapped


def _w1g3_bauble_table(set_pool, graveyard):
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 5,
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g3_settle(game)
    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("5DN")["Conjurer's Bauble"]), None
    )
    _w1g3_settle(game)
    return game


def test_w1g3_conjurers_bauble_draws_over_an_empty_graveyard(set_pool):
    """Drive list (supported on arrival, and wrong): "{T}, Sacrifice this
    artifact: Put **up to one** target card from your graveyard on the bottom
    of your library. Draw a card." CR 601.2c lets the announcement name no
    card, so the Bauble is activatable with nothing in the graveyard, for its
    draw. It was refused ("no valid target") — the lowering dropped "up to"."""
    game = _w1g3_bauble_table(set_pool, graveyard=[])
    result = game.activate_permanent_ability(0, "Conjurer's Bauble")
    assert result.supported, result
    _w1g3_settle(game)
    alice = game.players[0]
    assert [c.name for c in alice.hand] == ["Island"]
    assert [c.name for c in alice.graveyard] == ["Conjurer's Bauble"]


def test_w1g3_conjurers_bauble_naming_no_card_bottoms_none(set_pool):
    """Announced naming no card over a graveyard that holds one, the Bauble
    draws and bottoms nothing — it bottomed the Lightning Bolt anyway, the
    first card in the pile, for a player who had chosen zero. Named, the
    card goes to the bottom."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    game = _w1g3_bauble_table(set_pool, graveyard=[bolt])
    assert game.activate_permanent_ability(
        0, "Conjurer's Bauble", target_player_index=0, target_graveyard_indices=[],
    ).supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert [c.name for c in alice.graveyard] == ["Lightning Bolt", "Conjurer's Bauble"]
    assert [c.name for c in alice.hand] == ["Island"]
    assert alice.library[-1].name == "Island"

    game = _w1g3_bauble_table(set_pool, graveyard=[bolt])
    assert game.activate_permanent_ability(
        0, "Conjurer's Bauble", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert alice.library[-1].name == "Lightning Bolt"
    assert [c.name for c in alice.graveyard] == ["Conjurer's Bauble"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== integrator ====================================================
# Whole-card tests the wave-1 split left to the integrator: a card two groups
# built halves of. Fist of Suns (W1G2) paying for a sunburst spell (W1G1);
# Solarion and Beacon of Immortality join here when W1G7's doubling lands.
from engine import Game as _IntGame, PlayerState as _IntPlayerState
from engine.models import Permanent as _IntPermanent
from engine.named_counters import counters_on as _int_counters_on
from tests.helpers import settle as _int_settle

_INT_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _int_table(set_pool, *, hand=(), mine=()):
    """Two seats on seat 0's first main phase, costs enforced; *mine* placed."""
    lea = set_pool("LEA")
    game = _IntGame(players=[
        _IntPlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 12),
        _IntPlayerState(name="Bob", library=[lea["Island"]] * 12),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for card in mine:
        permanent = _IntPermanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    _int_settle(game)
    return game


def _int_tap_lands(game, seat=0):
    for permanent in list(game.controlled_by(seat)):
        if permanent.has_type("land") and not permanent.tapped:
            refused = game.tap_land_for_mana_or_refusal(
                seat, permanent.card.name, permanent_id=permanent.permanent_id,
            )
            assert refused is None, refused


def test_int_fist_of_suns_wubrg_counts_five_colours_for_sunburst(set_pool):
    """CR 702.44b counts mana spent on an alternative cost: Suntouched Myr
    ({3}, sunburst) cast for Fist of Suns' {W}{U}{B}{R}{G} enters with five
    +1/+1 counters, where its own {3} paid the same way could count three."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _int_table(
        set_pool,
        hand=[fdn["Suntouched Myr"]],
        mine=[fdn["Fist of Suns"], *(lea[name] for name in _INT_BASICS)],
    )
    _int_tap_lands(game)

    result = game.cast_from_hand(0, "Suntouched Myr", alternative_cost=True)
    assert result.supported, (result.details, game.log[-5:])
    _int_settle(game)

    myr = next(p for p in game.controlled_by(0) if p.card.name == "Suntouched Myr")
    assert _int_counters_on(myr, "+1/+1") == 5
    assert (myr.effective_power, myr.effective_toughness) == (5, 5)
    assert not any(game.players[0].mana_pool.values())

# ==== end integrator ================================================
