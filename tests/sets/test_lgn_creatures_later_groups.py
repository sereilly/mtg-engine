"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Libraries, graveyards and exile: a two-card search, a three-zone search for
# a named card, a chosen-type graveyard shuffle, a revealed top card put onto
# the battlefield by type, a dies trigger that exiles itself and returns
# targets, and an exile of every creature until the next end step.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve


def _w1g6_card(set_pool, name):
    for code in ("LGN", "ONS", "LEA", "7ED"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_game(set_pool, *, library=(), opp_library=(), interactive=False):
    """Two seats in seat 0's precombat main phase, mana costs off."""
    me = _w1g6_PlayerState(
        name="Me", library=[_w1g6_card(set_pool, n) for n in library],
    )
    opp = _w1g6_PlayerState(
        name="Opp",
        library=[_w1g6_card(set_pool, n) for n in (opp_library or ["Forest"] * 5)],
    )
    game = _w1g6_Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game, me, opp


def _w1g6_put(game, seat, set_pool, name):
    perm = _w1g6_Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# --- Corpse Harvester -------------------------------------------------------


def _w1g6_harvester(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool,
        library=["Forest", "Withered Wretch", "Forest", "Swamp", "Grizzly Bears"],
        interactive=interactive,
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Corpse Harvester")).supported
    _w1g6_put(game, 0, set_pool, "Corpse Harvester")
    fodder = _w1g6_put(game, 0, set_pool, "Grizzly Bears")
    result = game.activate_permanent_ability(
        0, "Corpse Harvester", cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result.details
    assert [c.name for c in me.graveyard] == ["Grizzly Bears"], "the sacrifice is paid"
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, me


def test_w1g6_corpse_harvester_finds_a_zombie_and_a_swamp_and_reveals_them(set_pool):
    """"Search your library for a Zombie card and a Swamp card, reveal them,
    put them into your hand, then shuffle." Answered as an interactive seat:
    one pick per printed description, both shown to the table (CR 701.20)."""
    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    # A pick that fills the Swamp slot with a Forest is no answer.
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Forest")},
    ])
    # Nor are two cards for one description (the Bears is not a Zombie).
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Grizzly Bears")},
    ])
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Swamp")},
    ])
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]
    assert sorted(c.name for c in me.library) == ["Forest", "Forest", "Grizzly Bears"]
    assert any(e["cards"] == ["Withered Wretch", "Swamp"] for e in game.reveal_events)
    assert "Me revealed Withered Wretch, Swamp" in game.log


def test_w1g6_corpse_harvester_default_seat_finds_both_and_may_find_one(set_pool):
    """A default seat takes both finds; the ruling (2004-10-04) lets a player
    find fewer, which an interactive seat states with one pick."""
    game, me = _w1g6_harvester(set_pool, interactive=False)
    game.auto_resolve_pending_choices()
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]

    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": library.index("Swamp")}],
    )
    _w1g6_resolve(game)
    assert [c.name for c in me.hand] == ["Swamp"]


# --- Elvish Soultiller ------------------------------------------------------


def _w1g6_soultiller_dies(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool, library=["Forest"] * 3, interactive=interactive,
    )
    me.graveyard.extend(
        _w1g6_card(set_pool, name) for name in (
            "Elvish Warrior", "Llanowar Elves", "Goblin Sky Raider", "Forest",
            "Llanowar Elves",
        )
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Elvish Soultiller")).supported
    soultiller = _w1g6_put(game, 0, set_pool, "Elvish Soultiller")
    game.sacrifice_permanent(soultiller)
    assert [item.card.name for item in game.stack] == ["Elvish Soultiller"]
    return game, me


def test_w1g6_elvish_soultiller_shuffles_back_only_the_chosen_type(set_pool):
    """"When this creature dies, choose a creature type. Shuffle all creature
    cards of that type from your graveyard into your library." Answered as an
    interactive seat with Goblin: the Goblin goes, the Elves and the land
    stay — the narrowing is the chosen word, not every creature card."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=True)
    game.resolve_top_of_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "creature_type_choice"
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.graveyard) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Llanowar Elves",
        "Llanowar Elves",
    ]
    assert sorted(c.name for c in me.library) == [
        "Forest", "Forest", "Forest", "Goblin Sky Raider",
    ]
    assert "Me shuffled 1 card(s) from their graveyard into their library" in game.log


def test_w1g6_elvish_soultiller_default_names_its_own_commonest_graveyard_type(set_pool):
    """A seat nobody asks names the type its own graveyard holds most of —
    the shuffle is a gift to the chooser — and the Soultiller, an Elf
    Mutant already in the graveyard, goes back with the Elves."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=False)
    _w1g6_resolve(game)
    assert "Elvish Soultiller: chose elf" in game.log
    assert sorted(c.name for c in me.graveyard) == ["Forest", "Goblin Sky Raider"]
    assert sorted(c.name for c in me.library) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Forest", "Forest",
        "Llanowar Elves", "Llanowar Elves",
    ]


# --- Skirk Drill Sergeant ---------------------------------------------------


def _w1g6_sergeant(set_pool, top, *, interactive, dying="Goblin Sky Raider", seat=0):
    """A Sergeant and three Mountains; *dying* (seat *seat*'s) is sacrificed
    with *top* on top of the Sergeant controller's library. Costs enforced."""
    game, me, opp = _w1g6_game(
        set_pool, library=[top, "Forest", "Forest"], interactive=interactive,
    )
    game.enforce_mana_costs = True
    assert _w1g6_compile(_w1g6_card(set_pool, "Skirk Drill Sergeant")).supported
    for _ in range(3):
        _w1g6_put(game, 0, set_pool, "Mountain")
    sergeant = _w1g6_put(game, 0, set_pool, "Skirk Drill Sergeant")
    victim = sergeant if dying == "Skirk Drill Sergeant" else _w1g6_put(
        game, seat, set_pool, dying,
    )
    game.sacrifice_permanent(victim)
    assert [item.card.name for item in game.stack] == ["Skirk Drill Sergeant"]
    return game, me


def test_w1g6_skirk_drill_sergeant_puts_a_revealed_goblin_onto_the_battlefield(set_pool):
    """"Whenever this creature or another Goblin dies, you may pay {2}{R}. If
    you do, reveal the top card of your library. If it's a Goblin permanent
    card, put it onto the battlefield." Paid as an interactive seat: the three
    Mountains tap and the Goblin on top enters."""
    game, me = _w1g6_sergeant(set_pool, "Goblin Sky Raider", interactive=True)
    _w1g6_resolve(game)
    (offer,) = game.pending_choices
    assert offer.kind == "optional_pay" and offer.data["cost"] == {"R": 1, "generic": 2}
    assert game.confirm_optional_pay(0)
    _w1g6_resolve(game)
    assert "Me revealed Goblin Sky Raider from the top of their library" in game.log
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Goblin Sky Raider", "Mountain", "Mountain", "Mountain",
        "Skirk Drill Sergeant",
    ]
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert [c.name for c in me.library] == ["Forest", "Forest"]


def test_w1g6_skirk_drill_sergeant_bins_a_card_that_is_not_a_goblin(set_pool):
    """A creature card that is not a Goblin is no "Goblin permanent card": it
    goes into the graveyard ("Otherwise, put it into your graveyard") — the
    subtype is tested, not merely the creature type it implies."""
    game, me = _w1g6_sergeant(set_pool, "Grizzly Bears", interactive=False)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert "Me revealed Grizzly Bears from the top of their library" in game.log
    assert sorted(c.name for c in me.graveyard) == ["Goblin Sky Raider", "Grizzly Bears"]
    assert not any(p.card.name == "Grizzly Bears" for p in game.all_permanents())


def test_w1g6_skirk_drill_sergeant_declined_reveals_nothing(set_pool):
    """Declining the {2}{R} reveals nothing and moves nothing: "If you do"
    guards the reveal and both destinations behind it."""
    game, me = _w1g6_sergeant(set_pool, "Goblin Sky Raider", interactive=True)
    _w1g6_resolve(game)
    assert game.confirm_optional_pay(0, accept=False)
    _w1g6_resolve(game)
    assert [c.name for c in me.library] == ["Goblin Sky Raider", "Forest", "Forest"]
    assert not any("revealed" in line for line in game.log)
    assert not any(p.tapped for p in game.controlled_by(0))


@_w1g6_pytest.mark.parametrize("dying, seat", [
    ("Skirk Drill Sergeant", 0), ("Goblin Sky Raider", 1),
])
def test_w1g6_skirk_drill_sergeant_triggers_on_itself_and_on_any_goblin(set_pool, dying, seat):
    """"This creature or another Goblin": the Sergeant's own death triggers it
    (leaves-the-battlefield abilities look back, CR 603.10a), and so does an
    opponent's Goblin — the printed noun names no controller."""
    game, me = _w1g6_sergeant(
        set_pool, "Goblin Sky Raider", interactive=False, dying=dying, seat=seat,
    )
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert any(
        p.card.name == "Goblin Sky Raider" for p in game.controlled_by(0)
    ), game.log[-6:]
    assert [c.name for c in me.library] == ["Forest", "Forest"]


# --- Dark Supplicant --------------------------------------------------------


def _w1g6_supplicant(set_pool, where, *, interactive, monkeypatch=None):
    """Scion of Darkness in *where*; the Supplicant activated, three Clerics
    sacrificed. Returns the game, seat 0 and the shuffles counted."""
    game, me, _opp = _w1g6_game(
        set_pool, library=["Forest", "Island", "Swamp"], interactive=interactive,
    )
    scion = _w1g6_card(set_pool, "Scion of Darkness")
    {"hand": me.hand, "graveyard": me.graveyard, "library": me.library}[where].append(scion)
    shuffles = []
    if monkeypatch is not None:
        monkeypatch.setattr(
            "engine.mixins.stack.choices.search.random.shuffle",
            lambda pile: shuffles.append(len(pile)),
        )
    assert _w1g6_compile(_w1g6_card(set_pool, "Dark Supplicant")).supported
    _w1g6_put(game, 0, set_pool, "Dark Supplicant")
    clerics = [
        _w1g6_put(game, 0, set_pool, name)
        for name in ("Blood Celebrant", "Earthblighter", "Deathmark Prelate")
    ]
    result = game.activate_permanent_ability(
        0, "Dark Supplicant", cost_permanent_ids=[p.permanent_id for p in clerics],
    )
    assert result.supported, result.details
    assert {"Blood Celebrant", "Earthblighter", "Deathmark Prelate"} <= {
        c.name for c in me.graveyard
    }
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    assert tuple(choice.data["zones"]) == ("library", "graveyard", "hand")
    return game, me, scion, shuffles


@_w1g6_pytest.mark.parametrize("where", ["hand", "graveyard"])
def test_w1g6_dark_supplicant_finds_the_scion_in_hand_or_graveyard(set_pool, where, monkeypatch):
    """"Search your graveyard, hand, and/or library for a card named Scion of
    Darkness and put it onto the battlefield. If you search your library this
    way, shuffle." Answered as an interactive seat naming the zone the Scion
    is in: it enters, and the library — not searched — is not shuffled (the
    ruling, 2004-10-04: "You only shuffle your library if you choose to search
    it")."""
    game, me, scion, shuffles = _w1g6_supplicant(
        set_pool, where, interactive=True, monkeypatch=monkeypatch,
    )
    pile = {"hand": me.hand, "graveyard": me.graveyard}[where]
    index = next(i for i, card in enumerate(pile) if card is scion)
    # A pick that names a zone the card is not in finds a different card,
    # which the name refuses.
    other = "graveyard" if where == "hand" else "hand"
    if len({"hand": me.hand, "graveyard": me.graveyard}[other]) > index:
        assert not game.confirm_search_library(0, index, other)
    assert not game.confirm_search_library(0, 0, "exile"), "never armed for exile"
    assert game.confirm_search_library(0, index, where)
    _w1g6_resolve(game)
    assert any(p.card is scion for p in game.controlled_by(0))
    assert scion not in me.hand and scion not in me.graveyard
    assert [c.name for c in me.library] == ["Forest", "Island", "Swamp"]
    assert shuffles == []
    assert f"Me searched {where} and put Scion of Darkness onto the battlefield" in game.log


def test_w1g6_dark_supplicant_default_seat_finds_it_in_the_library_and_shuffles(set_pool, monkeypatch):
    """A seat nobody asks finds the Scion wherever it is — here the library,
    which it searched, so the library is shuffled."""
    game, me, scion, shuffles = _w1g6_supplicant(
        set_pool, "library", interactive=False, monkeypatch=monkeypatch,
    )
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert any(p.card is scion for p in game.controlled_by(0))
    assert sorted(c.name for c in me.library) == ["Forest", "Island", "Swamp"]
    assert shuffles == [3]


def test_w1g6_dark_supplicant_hand_pick_takes_one_copy(set_pool):
    """Two Scions in hand (one ``CardDefinition`` object, as every deck holds
    copies): a hand find takes exactly one through the hand seam."""
    game, me, scion, _ = _w1g6_supplicant(set_pool, "hand", interactive=True)
    me.hand.append(scion)
    assert game.confirm_search_library(0, 0, "hand")
    _w1g6_resolve(game)
    assert [c.name for c in me.hand] == ["Scion of Darkness"]
    assert sum(p.card is scion for p in game.controlled_by(0)) == 1


def test_w1g6_dark_supplicant_needs_three_clerics(set_pool):
    """"Sacrifice three Clerics": with only one other Cleric there are two in
    all (the Supplicant is a Human Cleric itself), the cost cannot be paid,
    and nothing is sacrificed or searched — the refusal is the result's, not
    the log's (``engine/refusals.py``)."""
    game, me, _opp = _w1g6_game(set_pool, library=["Forest"])
    supplicant = _w1g6_put(game, 0, set_pool, "Dark Supplicant")
    cleric = _w1g6_put(game, 0, set_pool, "Blood Celebrant")
    result = game.activate_permanent_ability(
        0, "Dark Supplicant",
        cost_permanent_ids=[cleric.permanent_id, supplicant.permanent_id],
    )
    assert not result.supported, result.details
    assert me.graveyard == [] and game.pending_choices == []
    assert not supplicant.tapped


# --- Celestial Gatekeeper ---------------------------------------------------


def _w1g6_gatekeeper_dies(set_pool, *, interactive, also_dying=()):
    """Celestial Gatekeeper (and *also_dying*, in one event) sacrificed over a
    graveyard of two Clerics, a Bird and a Bear.

    Inside ``deferring_triggers`` — the window a cost's sacrifices are paid in
    (Dark Supplicant's "Sacrifice three Clerics") — so the trigger goes on the
    stack once every card of the event is in the graveyard (CR 603.3d). A bare
    simultaneous sweep chooses at the fire site instead, before the later
    cards arrive: measured and reported, not this card's to fix."""
    game, me, _opp = _w1g6_game(set_pool, library=["Forest"] * 3, interactive=interactive)
    me.graveyard.extend(
        _w1g6_card(set_pool, name) for name in (
            "Blood Celebrant", "Grizzly Bears", "Aven Envoy", "Earthblighter",
        )
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Celestial Gatekeeper")).supported
    gatekeeper = _w1g6_put(game, 0, set_pool, "Celestial Gatekeeper")
    others = [_w1g6_put(game, 0, set_pool, name) for name in also_dying]
    with game.deferring_triggers():
        game.sacrifice_permanents([gatekeeper, *others])
    return game, me


def test_w1g6_celestial_gatekeeper_exiles_itself_and_returns_two_birds_or_clerics(set_pool):
    """"When this creature dies, exile it, then return up to two target Bird
    and/or Cleric permanent cards from your graveyard to the battlefield."
    Answered as an interactive seat: the picker offers the Birds and Clerics
    (itself included) and not the Bear; the Gatekeeper is exiled and the two
    chosen enter."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=True)
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target" and choice.data["max_targets"] == 2
    offered = sorted(t["name"] for t in choice.data["targets"])
    assert offered == [
        "Aven Envoy", "Blood Celebrant", "Celestial Gatekeeper", "Earthblighter",
    ]
    names = [c.name for c in me.graveyard]
    bear = names.index("Grizzly Bears")
    assert not game.confirm_trigger_target(
        0, seat=0, graveyard_indices=[names.index("Aven Envoy"), bear],
    ), "the Bear is no Bird or Cleric"
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[
        names.index("Aven Envoy"), names.index("Earthblighter"),
    ])
    _w1g6_resolve(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Aven Envoy", "Earthblighter",
    ]
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]
    assert sorted(c.name for c in me.graveyard) == ["Blood Celebrant", "Grizzly Bears"]


def test_w1g6_celestial_gatekeeper_targeting_itself_is_exiled_not_returned(set_pool):
    """The ruling (2004-10-04): "You can choose to target this card as one of
    the two … If you do, it gets exiled and does not get returned." The other
    target still returns — and is the card it named, not the one that slid
    into its slot when the Gatekeeper left the pile."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=True)
    names = [c.name for c in me.graveyard]
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[
        names.index("Celestial Gatekeeper"), names.index("Aven Envoy"),
    ])
    _w1g6_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Aven Envoy"]
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]


def test_w1g6_celestial_gatekeeper_target_above_it_in_the_pile_survives_the_exile(set_pool):
    """The Gatekeeper and a Cleric die in one event, the Cleric going in after
    it — so the Cleric's slot is above the Gatekeeper's. Exiling the Gatekeeper
    first slides it down one; the return re-locates it from its stamp and
    returns it, rather than reading the stale slot (out of range, or another
    card)."""
    game, me = _w1g6_gatekeeper_dies(
        set_pool, interactive=True, also_dying=["Deathmark Prelate"],
    )
    names = [c.name for c in me.graveyard]
    assert names.index("Deathmark Prelate") > names.index("Celestial Gatekeeper")
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_indices=[names.index("Deathmark Prelate")],
    )
    _w1g6_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Deathmark Prelate"]
    assert "Deathmark Prelate" not in [c.name for c in me.graveyard]


def test_w1g6_celestial_gatekeeper_default_seat_returns_two(set_pool):
    """A seat nobody asks names two of the Birds and Clerics as the trigger
    goes on the stack (CR 603.3d) and both return; the Gatekeeper is exiled."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=False)
    _w1g6_resolve(game)
    returned = [p.card.name for p in game.controlled_by(0)]
    assert len(returned) == 2
    assert set(returned) <= {"Aven Envoy", "Blood Celebrant", "Earthblighter"}
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]



# --- Planar Guide -----------------------------------------------------------


def _w1g6_planar_guide_board(set_pool):
    """Seat 0: the Guide, a Bears wearing Holy Strength with a +1/+1 counter,
    a Monk ("When this creature enters, you gain 2 life"), a token and a
    Forest. Seat 1: a face-down Krosan Colossus, and a Hill Giant seat 0 has
    stolen. Returns the game and the pieces by name."""
    from engine.control import change_control
    from engine.face_down import turn_face_down
    from engine.aura_attachment import attach_aura
    from engine.named_counters import add_counters
    from engine.tokens import make_token_card

    game, me, opp = _w1g6_game(set_pool, library=["Forest"] * 5)
    assert _w1g6_compile(_w1g6_card(set_pool, "Planar Guide")).supported
    board = {
        name: _w1g6_put(game, 0, set_pool, name)
        for name in ("Planar Guide", "Grizzly Bears", "Venerable Monk", "Forest")
    }
    aura = _w1g6_put(game, 0, set_pool, "Holy Strength")
    attach_aura(aura, board["Grizzly Bears"])
    add_counters(board["Grizzly Bears"], "+1/+1", 1)
    token = _w1g6_Permanent(card=make_token_card("Soldier", 1, 1, "Token Creature — Soldier"))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    colossus = _w1g6_put(game, 1, set_pool, "Krosan Colossus")
    assert turn_face_down(game, colossus)
    giant = _w1g6_put(game, 1, set_pool, "Hill Giant")
    change_control(giant, 0, source=board["Planar Guide"])
    game._recompute_continuous_effects()
    assert game.controller_index_of(giant) == 0
    board.update(token=token, colossus=colossus, giant=giant, aura=aura)
    return game, me, opp, board


def test_w1g6_planar_guide_exiles_every_creature_and_returns_them_at_end_step(set_pool):
    """"{3}{W}, Exile this creature: Exile all creatures. At the beginning of
    the next end step, return those cards to the battlefield under their
    owners' control." Its rulings (2004-10-04, 2005-08-01): the Aura goes to
    the graveyard and the counter is gone, the token does not return, "enters"
    abilities trigger, a face-down creature returns face up — and each card
    comes back under its **owner's** control, so the stolen Giant goes home.
    The Guide, exiled to pay the cost, is not one of "those cards"."""
    game, me, opp, board = _w1g6_planar_guide_board(set_pool)
    result = game.activate_permanent_ability(0, "Planar Guide")
    assert result.supported, result.details
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    assert sorted(c.name for c in me.exile) == [
        "Grizzly Bears", "Planar Guide", "Venerable Monk",
    ]
    # The face-down creature is exiled as the card it is (CR 708.9), not as
    # the blank 2/2 it was on the battlefield.
    assert sorted(c.name for c in opp.exile) == ["Hill Giant", "Krosan Colossus"]
    assert [c.name for c in me.graveyard] == ["Holy Strength"]
    life = me.life

    game.resolve_end_step(0)
    _w1g6_resolve(game)
    mine = sorted(p.card.name for p in game.controlled_by(0))
    theirs = sorted(p.card.name for p in game.controlled_by(1))
    assert mine == ["Forest", "Grizzly Bears", "Venerable Monk"]
    assert theirs == ["Hill Giant", "Krosan Colossus"]
    assert [c.name for c in me.exile] == ["Planar Guide"] and opp.exile == []
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    colossus = next(p for p in game.controlled_by(1) if p.card.name == "Krosan Colossus")
    assert colossus.effective_power == 9, "face up, a new object (CR 400.7)"
    assert me.life == life + 2, "the Monk's entry trigger"
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())
    assert (
        "Grizzly Bears, Venerable Monk returned to the battlefield under Me's "
        "control; Krosan Colossus, Hill Giant returned to the battlefield under "
        "Opp's control (Planar Guide)"
    ) in game.log


def test_w1g6_planar_guide_activated_in_the_end_step_returns_at_the_next_one(set_pool):
    """The ruling (2004-10-04): "If the ability is activated during the End
    step, then the creatures do not return until the End step of the
    following turn." The beginning of this end step has passed, so the
    delayed ability waits for the next one there is."""
    game, me, opp, board = _w1g6_planar_guide_board(set_pool)
    game.resolve_end_step(0)
    _w1g6_resolve(game)
    assert game.activate_permanent_ability(0, "Planar Guide").supported
    _w1g6_resolve(game)
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    assert game.start_next_turn() == 1
    _w1g6_resolve(game)
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    game.resolve_end_step(1)
    _w1g6_resolve(game)
    assert sorted(p.card.name for p in game.all_permanents()) == [
        "Forest", "Grizzly Bears", "Hill Giant", "Krosan Colossus",
        "Venerable Monk",
    ]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
