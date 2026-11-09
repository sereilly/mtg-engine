"""Mirrodin creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def test_w1g1_loxodon_punisher_grows_with_each_equipment_and_shrinks_when_one_moves(set_pool):
    """'This creature gets +2/+2 for each Equipment attached to it.' Equipped
    twice through the real equip ability, then one Equipment moves away."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    island = lea["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    def put(card):
        permanent = _W1G1Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        game._settle()
        return permanent

    def equip(gear, creature):
        result = game.activate_permanent_ability(
            0, gear.card.name, permanent_index=game.battlefield_index_of(gear),
            target_permanent_ids=[creature.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        game._settle()

    punisher = put(mrd["Loxodon Punisher"])
    bears = put(lea["Grizzly Bears"])
    scimitar = put(mrd["Leonin Scimitar"])
    splitter = put(mrd["Bonesplitter"])
    assert (punisher.effective_power, punisher.effective_toughness) == (2, 2)
    equip(scimitar, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (5, 5)
    equip(splitter, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (9, 7)
    equip(scimitar, bears)
    assert (punisher.effective_power, punisher.effective_toughness) == (6, 4)

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_table(set_pool, hand=(), mine=()):
    """Seat 0's turn, mana costs enforced (affinity changes a price), every
    permanent past summoning sickness."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd[n] for n in hand]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = 0
    w1g3_row = []
    for w1g3_name in mine:
        w1g3_perm = _W1G3Permanent(card=mrd[w1g3_name])
        w1g3_game._put_permanent_onto_battlefield(0, w1g3_perm, None)
        w1g3_perm.metadata["summoning_sickness_turn"] = -99
        w1g3_row.append(w1g3_perm)
    return w1g3_game, w1g3_row  # _w1g3_table


def _w1g3_tap_blue(game, count):
    """Tap *count* of seat 0's Seats of the Synod for {U}."""
    w1g3_lands = [
        p for p in game.controlled_by(0)
        if p.card.name == "Seat of the Synod" and not p.tapped
    ][:count]
    assert len(w1g3_lands) == count
    for w1g3_land in w1g3_lands:
        assert game.tap_land_for_mana(
            0, w1g3_land.card.name, "U", permanent_id=w1g3_land.permanent_id,
        )  # _w1g3_tap_blue


def test_w1g3_broodstar_costs_what_its_artifacts_leave_and_counts_them(set_pool):
    """"Affinity for artifacts" and "Broodstar's power and toughness are each
    equal to the number of artifacts you control" (CR 604.3). Printed
    {8}{U}{U}: eight artifact lands take the {8} off, two of them pay
    {U}{U}, and Broodstar enters an 8/8 flier — it is not an artifact itself.
    The CDA recounts continuously: an artifact entering makes it 9/9, three
    sacrificed make it 6/6. Seven artifacts would have left {1}{U}{U}."""
    broodstar = set_pool("MRD")["Broodstar"]
    game, mine = _w1g3_table(
        set_pool, hand=["Broodstar"], mine=["Seat of the Synod"] * 8,
    )
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (0, 2)
    _w1g3_tap_blue(game, 2)
    cast = game.cast_from_hand(0, "Broodstar")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    star = next(p for p in game.controlled_by(0) if p.card.name == "Broodstar")
    assert (star.effective_power, star.effective_toughness) == (8, 8)
    assert game._has_keyword(star, "flying")
    assert sum(game.players[0].mana_pool.values()) == 0

    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("MRD")["Frogmite"]), None
    )
    assert (star.effective_power, star.effective_toughness) == (9, 9)
    game.sacrifice_permanents(mine[:3])
    # CR 704.3: the state check before anyone next receives priority is where
    # the board's continuous effects are recomputed (CR 611.3a).
    game.check_state_based_actions()
    assert (star.effective_power, star.effective_toughness) == (6, 6)

    game, _mine = _w1g3_table(set_pool, mine=["Seat of the Synod"] * 7)
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (1, 2)


def test_w1g3_somber_hoverguard_flies_in_for_one_blue(set_pool):
    """Printed {5}{U}; five artifact lands leave {U}, one of them pays it, and
    a 3/2 flier enters. Four lands leave {1}{U}, which one land cannot pay."""
    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 5,
    )
    _w1g3_tap_blue(game, 1)
    cast = game.cast_from_hand(0, "Somber Hoverguard")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    drone = next(
        p for p in game.controlled_by(0) if p.card.name == "Somber Hoverguard"
    )
    assert (drone.effective_power, drone.effective_toughness) == (3, 2)
    assert game._has_keyword(drone, "flying")

    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 4,
    )
    _w1g3_tap_blue(game, 1)
    refused = game.cast_from_hand(0, "Somber Hoverguard")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Somber Hoverguard"]


def _w1g3_board(set_pool, mine=(), theirs=(), graveyard=(), interactive=()):
    """Costs not enforced (these drives are about what an ability does), every
    permanent untapped and past summoning sickness, the state checked once."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")

    def w1g3_card(name):
        return mrd[name] if name in mrd else lea[name]

    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", graveyard=[w1g3_card(n) for n in graveyard]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set(interactive)
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in ((0, mine), (1, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=w1g3_card(w1g3_name))
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_perm.tapped = False
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    w1g3_game.check_state_based_actions()
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_board


def _w1g3_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # _w1g3_pt


def test_w1g3_the_nim_count_their_controllers_artifacts(set_pool):
    """"This creature gets +1/+0 for each artifact you control." Two artifacts
    on their side (an Ornithopter and an artifact land), three on the other
    side that count for nothing: Lasher 3/1, Shrieker 2/1 with flying,
    Devourer 6/1, Shambler 4/1."""
    game, mine, _theirs = _w1g3_board(
        set_pool,
        mine=["Nim Lasher", "Nim Shrieker", "Nim Devourer", "Nim Shambler",
              "Ornithopter", "Seat of the Synod"],
        theirs=["Ornithopter"] * 3,
    )
    assert [_w1g3_pt(p) for p in mine[:4]] == [(3, 1), (2, 1), (6, 1), (4, 1)]
    assert game._has_keyword(mine[1], "flying")


def test_w1g3_nim_shambler_regenerates_off_a_sacrificed_creature(set_pool):
    """"Sacrifice a creature: Regenerate this creature." The Bears pay; the
    shield then replaces the Shambler's destruction by lethal damage — it
    stays, tapped and with its damage removed (CR 701.19a)."""
    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Nim Shambler", "Grizzly Bears"],
    )
    shambler, bears = mine
    activated = game.activate_permanent_ability(
        0, "Nim Shambler", cost_permanent_ids=[bears.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    assert not game.is_on_battlefield(bears)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    game.active_player_index = 1
    bolt = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[shambler.permanent_id])
    assert bolt.supported, bolt.details
    _w1g3_resolve(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(shambler) and shambler.tapped
    assert "Nim Shambler" not in [c.name for c in game.players[0].graveyard]


def test_w1g3_nim_devourer_returns_from_the_graveyard_in_upkeep_only(set_pool):
    """"{B}{B}: Return this card from your graveyard to the battlefield, then
    sacrifice a creature. Activate only during your upkeep." CR 113.6m: the
    ability works from the graveyard, where its first step moves the card
    from. It was refused there ("does not function from a graveyard") and
    offered on the battlefield, because the zone was stamped on the return
    step inside a "then" sequence and read off the top alone (MRD W1G3).

    Outside the upkeep it is refused by its own restriction; in the upkeep
    the Devourer returns and a creature is sacrificed — an interactive seat
    is asked which, and may name the Devourer itself, which goes back to the
    graveyard. On the battlefield the ability is not offered at all."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities

    program = compile_card_oracle(set_pool("MRD")["Nim Devourer"])
    assert usable_activated_abilities(program) == []
    assert len(usable_activated_abilities(program, zone="graveyard")) == 1

    game, _mine, _theirs = _w1g3_board(
        set_pool, mine=["Grizzly Bears"], graveyard=["Nim Devourer"],
    )
    game.current_turn_phase, game.current_step = "precombat_main", "main"
    refused = game.activate_from_graveyard(0, "Nim Devourer")
    assert not refused.supported and "upkeep" in refused.details
    assert [c.name for c in game.players[0].graveyard] == ["Nim Devourer"]

    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    activated = game.activate_from_graveyard(0, "Nim Devourer")
    assert activated.supported, activated.details
    _w1g3_resolve(game)
    assert "Nim Devourer returned from the graveyard to the battlefield" in game.log
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Nim Devourer"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears"]

    game, mine, _theirs = _w1g3_board(
        set_pool, mine=["Grizzly Bears"], graveyard=["Nim Devourer"],
        interactive=[0],
    )
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    assert game.activate_from_graveyard(0, "Nim Devourer").supported
    _w1g3_resolve(game)
    prompt = game.pending_sacrifice_state()
    assert prompt is not None and len(prompt["valid_indices"]) == 2
    devourer = next(p for p in game.controlled_by(0) if p.card.name == "Nim Devourer")
    assert game.confirm_sacrifice(0, permanent_ids=[devourer.permanent_id])
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Nim Devourer"]


def test_w1g3_copperhoof_vorrac_counts_untapped_opposing_permanents(set_pool):
    """"This creature gets +1/+1 for each untapped permanent your opponents
    control." Four untapped across the table make a 6/6; one tapped for mana
    makes it 5/5 at the next state check (CR 704.3), and its controller's own
    untapped permanents count for nothing."""
    game, mine, theirs = _w1g3_board(
        set_pool, mine=["Copperhoof Vorrac", "Forest", "Forest"],
        theirs=["Island", "Island", "Grizzly Bears", "Ornithopter"],
    )
    vorrac = mine[0]
    assert _w1g3_pt(vorrac) == (6, 6)
    assert game.tap_land_for_mana(1, "Island", "U", permanent_id=theirs[0].permanent_id)
    game.check_state_based_actions()
    assert _w1g3_pt(vorrac) == (5, 5)


def test_w1g3_the_artifact_eaters_sacrifice_what_they_print(set_pool):
    """Megatog ("Sacrifice an artifact: +3/+3 and trample until end of
    turn"), Krark-Clan Grunt ("+1/+0 and first strike") and Krark-Clan Shaman
    ("1 damage to each creature without flying"): each eats one artifact. The
    Shaman's ping kills the Shaman (it has no flying) and spares a flier; and
    with no artifact left, the Grunt's cost cannot be paid."""
    game, mine, theirs = _w1g3_board(
        set_pool,
        mine=["Megatog", "Krark-Clan Grunt", "Krark-Clan Shaman",
              "Ornithopter", "Ornithopter", "Seat of the Synod"],
        theirs=["Grizzly Bears", "Ornithopter"],
    )
    tog, grunt, shaman, first, second, land = mine
    for w1g3_name, w1g3_fodder in (
        ("Megatog", first), ("Krark-Clan Grunt", second), ("Krark-Clan Shaman", land),
    ):
        activated = game.activate_permanent_ability(
            0, w1g3_name, cost_permanent_ids=[w1g3_fodder.permanent_id],
        )
        assert activated.supported, (w1g3_name, activated.details)
        _w1g3_resolve(game)
        assert not game.is_on_battlefield(w1g3_fodder)
    game.check_state_based_actions()
    assert _w1g3_pt(tog) == (6, 7) and game._has_keyword(tog, "trample")
    assert _w1g3_pt(grunt) == (3, 2) and game._has_keyword(grunt, "first strike")
    assert not game.is_on_battlefield(shaman)
    bears, flier = theirs
    assert game.is_on_battlefield(bears) and bears.damage_marked == 1
    assert game.is_on_battlefield(flier) and flier.damage_marked == 0
    refused = game.activate_permanent_ability(0, "Krark-Clan Grunt")
    assert not refused.supported

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
import pytest
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=(
            [card(n) for n in library] if library is not None
            else [other["Island"]] * 10
        ),
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_until_owed(game, kind, seat=0):
    """Resolve the top of the stack until *kind* is owed by *seat* — the
    interactive seat's turn to answer, which ``resolve_stack`` would answer by
    default."""
    for _ in range(10):
        if game.pending_choice_of(kind, seat) is not None:
            return game.pending_choice_of(kind, seat)
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game.pending_choice_of(kind, seat)


def _w1g7_settle(game):
    """Drain the stack and answer, as a headless seat, what a bare table left
    on the queue (an offer made by a trigger that resolved with nobody held)."""
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def test_w1g7_leonin_elder_gains_on_any_artifact_entering(set_pool):
    """"Whenever **an** artifact enters, you may gain 1 life." The condition
    table read only "a"/"another", so the line was no trigger and the Elder
    refused as text too complex. An opponent's artifact counts (no "you
    control"); a nonartifact creature does not."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert p1.life == 21
    assert "P1 gained 1 life from Leonin Elder (20 -> 21)" in game.log

    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert p1.life == 21, "a nonartifact creature is not an artifact"


def test_w1g7_leonin_elder_may_decline(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Ornithopter"], interactive=(0,),
    )
    game.cast_from_hand(0, "Ornithopter")
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    _w1g7_resolve(game)
    assert p1.life == 20


def test_w1g7_vermiculos_grows_per_artifact_this_turn(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vermiculos"], hand=["Ornithopter", "Ornithopter"],
    )
    vermiculos = p1.battlefield[0]
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (5, 5)
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (9, 9)


def test_w1g7_lumengrid_sentinel_taps_on_its_controllers_artifact_only(set_pool):
    """"…an artifact **you control** enters": the narrowing is enforced — the
    opponent's artifact fires nothing — and the seat chooses the target as the
    trigger goes on the stack (CR 603.3d)."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Sentinel"], hand=["Ornithopter"],
        theirs=["Grizzly Bears"], their_hand=["Ornithopter"], interactive=(0,),
    )
    bears = p2.battlefield[0]
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert game.pending_choices == [] and not bears.tapped

    game.cast_from_hand(0, "Ornithopter")
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert "Grizzly Bears" in [t["name"] for t in prompt.data["targets"]]
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id, seat=1)
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g7_resolve(game)
    assert bears.tapped
    assert "Tapped Grizzly Bears" in game.log


def test_w1g7_vedalken_archmage_draws_for_artifact_spells_only(set_pool):
    """"Whenever you cast **an** artifact spell, draw a card." The table's type
    row carried "artifact" and read "a" before it, so no card could reach it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vedalken Archmage"],
        hand=["Ornithopter", "Grizzly Bears"], their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 2, "cast one, drew one"
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "a creature spell is not an artifact spell"
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "an opponent's artifact spell is not yours"

@pytest.mark.parametrize(
    "top,zone",
    [("Ornithopter", "hand"), ("Leonin Elder", "graveyard"), ("Island", "graveyard")],
)
def test_w1g7_neurok_familiar_sorts_the_revealed_card(set_pool, top, zone):
    """"…reveal the top card of your library. If it's an artifact card, put it
    into your hand. **Otherwise, put it into your graveyard.**" The reveal-top
    template knew one "otherwise" (the library's bottom). Ornithopter is an
    *artifact creature* card, which is an artifact card (CR 205.2) — the handler
    asked ``primary_type``, which answers "creature" for it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Neurok Familiar"], library=[top, "Island", "Island"],
    )
    game.cast_from_hand(0, "Neurok Familiar")
    _w1g7_settle(game)
    names = {
        "hand": [c.name for c in p1.hand],
        "graveyard": [c.name for c in p1.graveyard],
    }
    assert names[zone] == [top], game.log
    assert len(p1.library) == 2
    put = "hand" if zone == "hand" else "graveyard"
    assert f"P1 revealed {top} and put it into their {put}" in game.log

@pytest.mark.parametrize("pick,untapped", [("Ornithopter", True), ("Mountain", False)])
def test_w1g7_lumengrid_augur_untaps_when_the_target_discards_an_artifact(
    set_pool, pick, untapped
):
    """"{1}, {T}: Target player draws a card, then discards a card. **If that
    player discards an artifact card this way**, untap this creature." The
    record condition read the narrowed question with "you" as the subject
    only. The target picks (an interactive seat), and the untap waits for the
    answer: it reads which card went, not whether one did."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Augur"], their_hand=["Ornithopter", "Mountain"],
        interactive=(1,),
    )
    augur = game.players[0].battlefield[0]
    result = game.activate_permanent_ability(0, "Lumengrid Augur", target_player_index=1)
    assert result.supported, result.details
    assert augur.tapped
    prompt = _w1g7_until_owed(game, "discard", 1)
    assert prompt is not None, game.log
    assert len(p2.hand) == 3, "drew first"
    index = [c.name for c in p2.hand].index(pick)
    assert game.resolve_pending_choice("discard", 1, hand_indices=[index], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == [pick]
    assert augur.tapped is not untapped
    assert ("Lumengrid Augur untapped" in game.log) is untapped

# ==== end W1G7 ======================================================
