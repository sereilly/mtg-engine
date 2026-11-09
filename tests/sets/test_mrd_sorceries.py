"""Mirrodin sorceries.

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

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def test_w1g3_thoughtcast_draws_two_for_one_blue_off_four_artifacts(set_pool):
    """"Affinity for artifacts" / "Draw two cards." Printed {4}{U}: four
    artifact lands leave {U}, one pays it, and two cards are drawn. With
    three, it costs {1}{U}, and one land's mana is refused — the keyword the
    card was ingested without is the whole difference."""
    mrd = set_pool("MRD")

    def table(artifacts):
        game = _W1G3Game(players=[
            _W1G3PlayerState(
                name="W1G3-A", hand=[mrd["Thoughtcast"]],
                library=[mrd["Island"]] * 6,
            ),
            _W1G3PlayerState(name="W1G3-B", library=[mrd["Island"]] * 6),
        ])
        game.enforce_mana_costs = True
        game.interactive_seats = set()
        game.active_player_index = 0
        for _ in range(artifacts):
            game._put_permanent_onto_battlefield(
                0, _W1G3Permanent(card=mrd["Seat of the Synod"]), None
            )
        land = next(iter(game.controlled_by(0)))
        assert game.tap_land_for_mana(
            0, land.card.name, "U", permanent_id=land.permanent_id,
        )
        return game

    game = table(4)
    cast = game.cast_from_hand(0, "Thoughtcast")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Island", "Island"]
    assert [c.name for c in game.players[0].graveyard] == ["Thoughtcast"]
    assert sum(game.players[0].mana_pool.values()) == 0

    game = table(3)
    refused = game.cast_from_hand(0, "Thoughtcast")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Thoughtcast"]


def test_w1g3_trash_for_treasure_cannot_target_what_it_sacrifices(set_pool):
    """"As an additional cost to cast this spell, sacrifice an artifact." /
    "Return target artifact card from your graveyard to the battlefield."
    Targets are chosen before costs are paid (CR 601.2c before 601.2h), so
    the sacrificed artifact is never a legal target (its ruling, 2020-08-07):
    with a Myr Enforcer in the graveyard, the Ornithopter is sacrificed and
    the Enforcer returns; with an empty graveyard the spell has no target and
    is not cast, and the Ornithopter stays."""
    mrd = set_pool("MRD")

    def table(graveyard):
        game = _W1G3Game(players=[
            _W1G3PlayerState(
                name="W1G3-A", hand=[mrd["Trash for Treasure"]],
                graveyard=[mrd[n] for n in graveyard],
            ),
            _W1G3PlayerState(name="W1G3-B"),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        game.active_player_index = 0
        thopter = _W1G3Permanent(card=mrd["Ornithopter"])
        game._put_permanent_onto_battlefield(0, thopter, None)
        return game, thopter

    game, thopter = table(["Myr Enforcer"])
    cast = game.cast_from_hand(
        0, "Trash for Treasure", cost_permanent_ids=[thopter.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Myr Enforcer"]
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Ornithopter", "Trash for Treasure",
    ]

    game, thopter = table([])
    refused = game.cast_from_hand(
        0, "Trash for Treasure", cost_permanent_ids=[thopter.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(thopter)
    assert [c.name for c in game.players[0].hand] == ["Trash for Treasure"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# Entwine (CR 702.42) on the sorceries: an entwined cast pays the offer and
# names every mode, which resolve in printed order (CR 702.42b) — one after
# the other, an earlier mode's prompt answered before a later mode runs.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), graveyard=(),
                library=None, opponent_hand=(), interactive=()):
    """Seat 0 (A) to act in its first main phase, mana off unless a test
    turns it on; each named permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
            graveyard=[card(n) for n in graveyard],
        ),
        _w1g4_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Forest")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g4_names(permanents):
    return sorted(p.card.name for p in permanents)


def test_w1g4_one_dozen_eyes_entwined_makes_both_kinds_of_token(set_pool):
    """{5}{G} and the entwine's {G}{G}{G}: a 5/5 Beast and five 1/1 Insects."""
    game, _mine, _theirs = _w1g4_table(set_pool, ["One Dozen Eyes"])
    game.enforce_mana_costs = True
    game.players[0].mana_pool["G"] = 9
    result = game.cast_from_hand(0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1})
    assert result.supported, result.details
    tokens = _w1g4_names(game.players[0].battlefield)
    assert tokens == ["Beast Token"] + ["Insect Token"] * 5, tokens
    assert game.players[0].mana_pool["G"] == 0


def test_w1g4_a_copy_of_an_entwined_spell_is_entwined(set_pool):
    """CR 707.10: a copy copies "all decisions made for it, including modes …
    and additional or alternative costs" (and CR 700.2g, the modes). Fork's
    copy of an entwined One Dozen Eyes makes both kinds of token too."""
    game, _mine, _theirs = _w1g4_table(set_pool, ["One Dozen Eyes", "Fork"])
    queued = game.queue_from_hand(0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1})
    assert queued.supported, queued.details
    forked = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert forked.supported, forked.details
    _w1g4_resolve_stack(game)
    tokens = _w1g4_names(game.players[0].battlefield)
    assert tokens == ["Beast Token"] * 2 + ["Insect Token"] * 10, (tokens, game.log)


def test_w1g4_promise_of_power_entwined_counts_the_cards_it_drew(set_pool):
    """The ruling (2004-12-01): "you draw five cards, then lose five life, then
    put the Demon token onto the battlefield. The five cards you draw count
    toward the Demon's power and toughness.\""""
    game, _mine, _theirs = _w1g4_table(set_pool, ["Promise of Power"])
    result = game.cast_from_hand(0, "Promise of Power", optional_cost_payments={"{4}": 1})
    assert result.supported, result.details
    player = game.players[0]
    assert len(player.hand) == 5 and player.life == 15
    (demon,) = player.battlefield
    assert demon.card.name == "Demon Token"
    assert (demon.effective_power, demon.effective_toughness) == (5, 5)
    assert game._has_keyword(demon, "flying")


def test_w1g4_solar_tide_entwined_sacrifices_two_lands_and_destroys_both_sizes(set_pool):
    game, mine, theirs = _w1g4_table(
        set_pool, ["Solar Tide"], mine=["Plains", "Plains", "Plains", "Grizzly Bears"],
        theirs=["Hill Giant", "Llanowar Elves"],
    )
    result = game.cast_from_hand(0, "Solar Tide", optional_cost_payments={"sacrifice two lands": 1})
    assert result.supported, result.details
    assert not any(game.is_on_battlefield(p) for p in (mine[3], *theirs)), game.log
    assert _w1g4_names(game.players[0].battlefield) == ["Plains"]

    game, _mine, theirs = _w1g4_table(
        set_pool, ["Solar Tide"], mine=["Plains"], theirs=["Hill Giant", "Llanowar Elves"],
    )
    refused = game.cast_from_hand(0, "Solar Tide", optional_cost_payments={"sacrifice two lands": 1})
    assert not refused.supported
    assert all(game.is_on_battlefield(p) for p in theirs)


def test_w1g4_temporal_cascade_entwined_shuffles_then_draws_seven(set_pool):
    """Printed order: every hand and graveyard into its library, then seven
    cards each. The spell itself is not shuffled in (the 2013-07-01 ruling:
    it goes to the graveyard only once it has finished resolving)."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Temporal Cascade", "Hill Giant"], graveyard=["Craw Wurm"],
        opponent_hand=["Grizzly Bears"],
    )
    result = game.cast_from_hand(0, "Temporal Cascade", optional_cost_payments={"{2}": 1})
    assert result.supported, result.details
    for player in game.players:
        assert len(player.hand) == 7, game.log
    caster = game.players[0]
    assert [c.name for c in caster.graveyard] == ["Temporal Cascade"]
    seen = [c.name for c in caster.hand + caster.library]
    assert "Hill Giant" in seen and "Craw Wurm" in seen
    opponent = game.players[1]
    assert "Grizzly Bears" in [c.name for c in opponent.hand + opponent.library]


def test_w1g4_tooth_and_nail_entwined_puts_the_creatures_it_found(set_pool):
    """The second mode waits for the first's search (a resumable loop over the
    modes): the creatures found go to the hand, and only then is the hand
    chosen from — interactive seat answering both prompts."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Tooth and Nail"],
        library=["Craw Wurm", "Forest", "Hill Giant"] + ["Forest"] * 6,
        interactive=(0,),
    )
    result = game.cast_from_hand(0, "Tooth and Nail", optional_cost_payments={"{2}": 1})
    assert result.supported, result.details
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert not game.players[0].battlefield
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0}, {"zone": "library", "index": 2}],
    )
    assert [c.kind for c in game.pending_choices] == ["choose_cards_in_hand"]
    hand = game.players[0].hand
    assert sorted(c.name for c in hand) == ["Craw Wurm", "Hill Giant"]
    assert game.confirm_choose_cards_in_hand(0, [0, 1])
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].battlefield) == ["Craw Wurm", "Hill Giant"], game.log
    assert [c.name for c in game.players[0].graveyard] == ["Tooth and Nail"]


def test_w1g4_tooth_and_nail_entwined_headless(set_pool):
    """The same cast for a seat nobody asks: the defaults find two creature
    cards and put them onto the battlefield."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Tooth and Nail"],
        library=["Craw Wurm", "Forest", "Hill Giant"] + ["Forest"] * 6,
    )
    result = game.cast_from_hand(0, "Tooth and Nail", optional_cost_payments={"{2}": 1})
    assert result.supported, result.details
    # The search suspends the resolution (it holds the spell off the stack)
    # even for a seat nobody asks; its default answer is what carries on.
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[0].battlefield) == ["Craw Wurm", "Hill Giant"], game.log
    assert [c.name for c in game.players[0].graveyard] == ["Tooth and Nail"]


def test_w1g4_journey_of_discovery_entwined_finds_lands_and_plays_them(set_pool):
    """Two basic lands into the hand, then two land plays beyond the turn's
    one: three lands played this turn."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Journey of Discovery", "Swamp"],
        library=["Plains", "Grizzly Bears", "Island"] + ["Hill Giant"] * 6,
    )
    result = game.cast_from_hand(
        0, "Journey of Discovery", optional_cost_payments={"{2}{G}": 1},
    )
    assert result.supported, result.details
    game.auto_resolve_pending_choices()
    assert sorted(c.name for c in game.players[0].hand) == ["Island", "Plains", "Swamp"], game.log
    game.enforce_mana_costs = True
    for land in ("Swamp", "Plains", "Island"):
        played = game.cast_from_hand(0, land)
        assert played.supported, (land, played.details)
    assert _w1g4_names(game.players[0].battlefield) == ["Island", "Plains", "Swamp"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from tests.helpers import resolve_stack as _w1g7_resolve


def _w1g7_wrench_mind(set_pool, their_hand, interactive=()):
    mrd, lea = set_pool("MRD"), set_pool("LEA")

    def card(name):
        return mrd[name] if name in mrd else lea[name]

    p1 = _w1g7_PlayerState(
        name="P1", hand=[mrd["Wrench Mind"]], library=[lea["Island"]] * 5,
    )
    p2 = _w1g7_PlayerState(
        name="P2", hand=[card(n) for n in their_hand], library=[lea["Island"]] * 5,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    assert game.cast_from_hand(0, "Wrench Mind", target_player_index=1).supported
    for _ in range(5):
        if not game.stack or game.pending_choices:
            break
        game.resolve_top_of_stack()
    return game, p2


def test_w1g7_wrench_mind_a_headless_target_pays_with_its_artifact(set_pool):
    """"Target player discards two cards unless they discard an artifact
    card." The "you" spelling (Thirst for Knowledge) shipped; the targeted
    player's discard refused any narrowing. One artifact card is the whole
    price, and the default pays it."""
    game, p2 = _w1g7_wrench_mind(set_pool, ["Ornithopter", "Island", "Mountain"])
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == ["Ornithopter"], game.log
    assert sorted(c.name for c in p2.hand) == ["Island", "Mountain"]


def test_w1g7_wrench_mind_without_an_artifact_card_two_go(set_pool):
    """No artifact card in hand: the offer cannot be taken (CR 118.3: a cost
    is paid only with the resources to pay it fully) and two cards go. What
    the takeability check counted was the whole hand, so
    a narrowed price would have been "paid" with nothing."""
    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Grizzly Bears", "Island", "Mountain"], interactive=(1,),
    )
    assert game.pending_choice_of("optional_pay", 1) is None, "no offer to make"
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 2
    assert game.resolve_pending_choice("discard", 1, hand_indices=[1, 2], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.hand] == ["Grizzly Bears"]
    assert len(p2.graveyard) == 2


def test_w1g7_wrench_mind_an_interactive_target_chooses(set_pool):
    """The target is asked; accepting offers only the artifact card, and
    declining asks for two of any."""
    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Ornithopter", "Island", "Mountain"], interactive=(1,),
    )
    assert game.pending_choice_of("optional_pay", 1) is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 1, accept=True)
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 1
    assert [p2.hand[i].name for i in game.live_discard_candidates(prompt)] == ["Ornithopter"]
    assert not game.resolve_pending_choice("discard", 1, hand_indices=[1], to_library=False), (
        "an Island is not an artifact card"
    )
    assert game.resolve_pending_choice("discard", 1, hand_indices=[0], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == ["Ornithopter"]

    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Ornithopter", "Island", "Mountain"], interactive=(1,),
    )
    assert game.resolve_pending_choice("optional_pay", 1, accept=False)
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 2
    assert len(game.live_discard_candidates(prompt)) == 3
    assert game.resolve_pending_choice("discard", 1, hand_indices=[1, 2], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.hand] == ["Ornithopter"]


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

from engine.game import Game as _W1G11Game
from engine.models import Permanent as _W1G11Permanent
from engine.models import PlayerState as _W1G11PlayerState

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_gambit_table(set_pool, monkeypatch, coins, *, interactive):
    import engine.handlers.coin_runs as _w1g11_coin_runs

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=[mrd["Fiery Gambit"]], library=[lea["Island"]] * 12,
    )
    bob = _W1G11PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    dragon = _W1G11Permanent(card=lea["Shivan Dragon"])
    game._put_permanent_onto_battlefield(1, dragon, None)
    land = _W1G11Permanent(card=lea["Mountain"], tapped=True)
    game._put_permanent_onto_battlefield(0, land, None)
    queue = list(coins)
    monkeypatch.setattr(
        _w1g11_coin_runs, "flip_coin", lambda win_probability=0.5: queue.pop(0),
    )
    return game, alice, bob, dragon, land


def _w1g11_cast_gambit(game, dragon):
    assert game.cast_from_hand(
        0, "Fiery Gambit", target_permanent_ids=[dragon.permanent_id],
    ).supported


def test_w1g11_fiery_gambit_three_wins_does_everything(set_pool, monkeypatch):
    """The ruling (2004-12-01): three wins is 3 to the creature, 6 to each
    opponent, nine cards and the lands untapped."""
    game, alice, bob, dragon, land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True, True, True], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    for _ in range(2):
        (offer,) = [c for c in game.pending_choices if c.kind == "flip_again"]
        assert offer.player_index == 0
        assert game.confirm_flip_again(0, True)
    (offer,) = [c for c in game.pending_choices if c.kind == "flip_again"]
    assert offer.data["flips_won"] == 3
    assert game.confirm_flip_again(0, False)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 14
    assert len(alice.hand) == 9
    assert not land.tapped


def test_w1g11_fiery_gambit_stopping_after_one_win_burns_the_creature(set_pool, monkeypatch):
    game, alice, bob, dragon, _land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    assert game.confirm_flip_again(0, False)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 20
    assert alice.hand == []


def test_w1g11_fiery_gambit_a_lost_flip_voids_two_wins(set_pool, monkeypatch):
    """"If you lose a flip, Fiery Gambit has no effect" — even after two wins."""
    game, alice, bob, dragon, land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True, True, False], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    assert game.confirm_flip_again(0, True)
    assert game.confirm_flip_again(0, True)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 0
    assert bob.life == 20
    assert alice.hand == []
    assert land.tapped
    assert any("has no effect" in line for line in game.log)


def test_w1g11_fiery_gambit_left_to_itself_flips_once_and_stops(set_pool, monkeypatch):
    game, alice, bob, dragon, _land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True], interactive=False,
    )
    _w1g11_cast_gambit(game, dragon)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 20

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# The drive list: Mirrodin sorceries that compiled supported on arrival.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_table(set_pool, *, hand=(), theirs=()):
    mrd = set_pool("MRD")
    card = lambda name: mrd[name] if name in mrd else set_pool("LEA")[name]  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState("A", hand=[card(n) for n in hand], library=[card("Forest")] * 12),
        _w1g12_PlayerState("B", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    placed = []
    for name in theirs:
        permanent = _w1g12_Permanent(card=card(name))
        game._put_permanent_onto_battlefield(1, permanent, None)
        placed.append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed


def test_w1g12_deconstruct_destroys_an_artifact_and_adds_ggg(set_pool):
    game, (myr,) = _w1g12_table(set_pool, hand=["Deconstruct"], theirs=["Alpha Myr"])
    assert game.queue_from_hand(0, "Deconstruct", target_permanent_ids=[myr.permanent_id]).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(myr)
    assert game.players[0].mana_pool["G"] == 3


def test_w1g12_molten_rain_burns_only_for_a_nonbasic_land(set_pool):
    game, (seat, mountain) = _w1g12_table(
        set_pool, hand=["Molten Rain", "Molten Rain"],
        theirs=["Seat of the Synod", "Mountain"],
    )
    assert game.queue_from_hand(0, "Molten Rain", target_permanent_ids=[seat.permanent_id]).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(seat) and game.players[1].life == 18
    assert game.queue_from_hand(
        0, "Molten Rain", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    assert not game.is_on_battlefield(mountain) and game.players[1].life == 18

# ==== end W1G12 ======================================================
