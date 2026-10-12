"""Apocalypse enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.control import change_control as _w1g2_change_control
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand=(), mana=None, opp_hand=(), opp_mana=None):
    """A two-seat game with mana costs enforced. *hand* names Apocalypse cards
    (or Alpha ones); *opp_hand* is Alpha."""
    lea, apc = set_pool("LEA"), set_pool("APC")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[apc[name] if name in apc else lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (enchantments)


def _w1g2_put(game, set_pool, seat, name, code="LEA"):
    """*name* onto *seat*'s battlefield, able to act this turn."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (enchantments)


def _w1g2_slot(game, seat, permanent):
    return list(game.controlled_by(seat)).index(permanent)  # _w1g2_slot (enchantments)


# Bloodfire Infusion ---------------------------------------------------------


def _w1g2_infused(set_pool, extra_hand=(), extra_mana=None):
    """Bloodfire Infusion cast onto the caster's Hill Giant and resolved, with
    one {R} left for its ability. Across the table: a 0/8 Wall of Stone and a
    Hill Giant. Returns ``(game, aura, host, wall, their_giant)``."""
    game = _w1g2_table(
        set_pool, ["Bloodfire Infusion", *extra_hand],
        {"R": 4, **(extra_mana or {})},
    )
    host = _w1g2_put(game, set_pool, 0, "Hill Giant")
    wall = _w1g2_put(game, set_pool, 1, "Wall of Stone")
    their_giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    result = game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Bloodfire Infusion")
    return game, aura, host, wall, their_giant  # _w1g2_infused


def test_w1g2_bloodfire_infusion_enchants_only_a_creature_its_caster_controls(set_pool):
    """"Enchant creature you control": the picker offers the caster's own
    creatures, and an opponent's creature is refused with nothing spent."""
    game = _w1g2_table(set_pool, ["Bloodfire Infusion"], {"R": 3})
    mine = _w1g2_put(game, set_pool, 0, "Hill Giant")
    theirs = _w1g2_put(game, set_pool, 1, "Hill Giant")
    spec = game.cast_target_spec(0, set_pool("APC")["Bloodfire Infusion"])
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [(0, "Hill Giant")]

    refused = game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 3

    assert game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[mine.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    (aura,) = [p for p in game.controlled_by(0) if p.card.name == "Bloodfire Infusion"]
    assert aura.metadata.get("attached_to") is mine


def test_w1g2_bloodfire_infusion_deals_the_sacrificed_creatures_power_to_each_creature(
    set_pool,
):
    """"{R}, Sacrifice enchanted creature: This Aura deals damage equal to the
    sacrificed creature's power to each creature." The host is paid as the
    cost, the Aura follows it to the graveyard as a state-based action
    (CR 704.5m) with its ability still on the stack (CR 113.7a), and the
    ability then deals 3 — the Hill Giant's power — to every creature on both
    sides. This card arrived dealing 0: the host was sacrificed and never
    recorded."""
    game, aura, host, wall, their_giant = _w1g2_infused(set_pool)
    mine = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    queued = game.queue_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )
    assert queued.supported, queued.details
    assert "Caster sacrificed Hill Giant to activate Bloodfire Infusion" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(aura)
    assert [item.card.name for item in game.stack] == ["Bloodfire Infusion"]

    _w1g2_resolve_stack(game)
    assert (mine.damage_marked, wall.damage_marked, their_giant.damage_marked) == (3, 3, 3)
    game.check_state_based_actions()

    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Bloodfire Infusion", "Grizzly Bears", "Hill Giant",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(wall)
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g2_bloodfire_infusion_reads_the_power_the_creature_last_had(set_pool):
    """CR 608.2h: last known information. A Giant Growth on the host makes it
    6/6, and the 6 is what each creature is dealt — off the permanent as it
    last existed, not off the card in the graveyard."""
    game, aura, host, wall, _their_giant = _w1g2_infused(
        set_pool, extra_hand=["Giant Growth"], extra_mana={"G": 1},
    )
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[host.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert host.effective_power == 6

    result = game.activate_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )

    assert result.supported, result.details
    assert wall.damage_marked == 6


def test_w1g2_bloodfire_infusion_refused_activation_sacrifices_nothing(set_pool):
    """Without {R} the ability is refused and the whole cost with it: the
    enchanted creature is still there, still enchanted."""
    game, aura, host, wall, _their_giant = _w1g2_infused(set_pool)
    game.players[0].mana_pool["R"] = 0

    result = game.activate_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )

    assert not result.supported
    assert game.is_on_battlefield(host) and game.is_on_battlefield(aura)
    assert aura.metadata.get("attached_to") is host
    assert wall.damage_marked == 0


def test_w1g2_bloodfire_infusion_falls_off_a_creature_its_controller_lost(set_pool):
    """The card's ruling: "If this card is ever on a creature you don't
    control, it is put into the graveyard as a State-Based Action."
    (CR 704.5m: the Aura no longer enchants what its enchant ability names.)"""
    game, aura, host, _wall, _their_giant = _w1g2_infused(set_pool)

    _w1g2_change_control(host, 1, source="a control effect")
    game._sync_control()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(aura)
    assert [card.name for card in game.players[0].graveyard] == ["Bloodfire Infusion"]
    assert game.controller_index_of(host) == 1


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_bloodfire_infusion_and_its_neighbours_through_whole_games():
    """Bloodfire Infusion and four of this group's spells pinned into both
    decks of three simulated games. They are cast and resolve, none is refused
    at the cast or the activation gate, and none leaves a step owing a prompt.
    (Apocalypse is a measured set, so other cards' unsupported casts are in the
    report; only these cards' lines are read.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Bloodfire Infusion", "Captain's Maneuver", "Consume Strength",
        "Strength of Night", "Aether Mutation",
    ]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("APC", include_measured=True)],
        games=3, seed=1337, max_turns=22, required_cards=names,
    )

    assert report.games_completed == 3
    resolved = sorted(
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    )
    assert len(resolved) >= 3, resolved
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        key for key in report.refused_activations if key.split(":")[0] in names
    ] == []
    assert [
        issue.message for issue in report.issues
        if any(name in issue.message for name in names)
    ] == []
    w1g2_owing = [
        key for key in report.steps_left_owing if any(name in str(key) for name in names)
    ]
    assert w1g2_owing == [], report.steps_left_owing


# Martyrs' Tomb --------------------------------------------------------------


def test_w1g2_martyrs_tomb_trades_two_life_for_one_point_of_prevention(set_pool):
    """"Pay 2 life: Prevent the next 1 damage that would be dealt to target
    creature this turn." Twice for 4 life: a Lightning Bolt at the Bears has 2
    of its 3 prevented and the Bears survive with 1 marked."""
    game = _w1g2_table(set_pool, opp_hand=["Lightning Bolt"], opp_mana={"R": 1})
    tomb = _w1g2_put(game, set_pool, 0, "Martyrs' Tomb", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    for _ in range(2):
        result = game.activate_permanent_ability(
            0, "Martyrs' Tomb", permanent_index=_w1g2_slot(game, 0, tomb),
            target_permanent_ids=[bears.permanent_id],
        )
        assert result.supported, result.details
    assert game.players[0].life == 16

    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()

    assert "Prevented 2 damage to Grizzly Bears" in game.log
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears)


def test_w1g2_martyrs_tomb_cost_and_target_are_both_enforced(set_pool):
    """CR 119.4: a player can pay life only if their total is at least the
    payment — at 1 life the ability is refused and the life is kept; at 2 it
    is paid and its controller is at 0. And "target creature" is not a land:
    that activation is refused before the life is paid."""
    game = _w1g2_table(set_pool)
    tomb = _w1g2_put(game, set_pool, 0, "Martyrs' Tomb", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    land = _w1g2_put(game, set_pool, 0, "Forest")
    slot = _w1g2_slot(game, 0, tomb)

    assert not game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[land.permanent_id],
    ).supported
    assert game.players[0].life == 20

    game.players[0].life = 1
    assert not game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[0].life == 1

    game.players[0].life = 2
    assert game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[0].life == 0

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4e_Game, PlayerState as _w1g4e_Player  # noqa: E402
from engine.grammar import compile_line as _w1g4e_compile_line  # noqa: E402
from engine.models import Permanent as _w1g4e_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4e_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4e_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order — one pool per card.
_W1G4E_POOLS = ("APC", "LEA", "USG")


def _w1g4e_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4E_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 enchantments: no pool here prints that name


def _w1g4e_table(set_pool, *, mine=(), theirs=(), hand0=(), lib0=(), lib1=(),
                 interactive=(), unsick=True):
    """A duel with seat 0 in its precombat main phase and costs not enforced."""
    def cards(names):
        return [_w1g4e_card(set_pool, name) for name in names]

    board0 = [_w1g4e_Permanent(card=card) for card in cards(mine)]
    board1 = [_w1g4e_Permanent(card=card) for card in cards(theirs)]
    game = _w1g4e_Game(players=[
        _w1g4e_Player(name="P0", battlefield=board0, hand=cards(hand0),
                      library=cards(lib0)),
        _w1g4e_Player(name="P1", battlefield=board1, library=cards(lib1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    if unsick:
        for permanent in board0 + board1:
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0, board1  # W1G4 enchantments: the table


def _w1g4e_names(cards):
    return [card.name for card in cards]  # W1G4 enchantments: a zone, by name


# -- Wild Research -----------------------------------------------------------

_W1G4E_RESEARCH_LIBRARY = [
    "Forest", "Pacifism", "Counterspell", "Island", "Circle of Protection: Red",
]


def test_w1g4_wild_research_tutors_an_enchantment_then_discards_at_random(set_pool):
    """"{1}{W}: Search your library for an enchantment card and reveal that
    card. Put it into your hand, then discard a card at random. Then shuffle."

    The find is in hand **before** the discard is made, so it is one of the
    cards the random discard may take: three cards in hand when the one is
    chosen, two afterwards. An instant is not an enchantment card.
    """
    research = _w1g4e_card(set_pool, "Wild Research")
    assert _w1g4e_compile(research).supported
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], hand0=["Grizzly Bears", "Hill Giant"],
        lib0=_W1G4E_RESEARCH_LIBRARY, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=0).supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert (prompt["count"], prompt["card_type"], prompt["reveal"]) == (1, "enchantment", True)
    assert _w1g4e_names(game.players[0].graveyard) == [], "no discard before the find"
    assert not game.confirm_search_library(0, 2), "Counterspell is an instant"
    assert not game.confirm_search_library(0, 0), "Forest is a land"
    assert game.confirm_search_library(0, 1)
    _w1g4e_resolve_stack(game)

    hand = _w1g4e_names(game.players[0].hand)
    discarded = _w1g4e_names(game.players[0].graveyard)
    assert len(hand) == 2 and len(discarded) == 1
    assert sorted(hand + discarded) == ["Grizzly Bears", "Hill Giant", "Pacifism"]
    assert game.reveal_events[-1]["cards"] == ["Pacifism"]
    assert sorted(_w1g4e_names(game.players[0].library)) == sorted(
        ["Forest", "Counterspell", "Island", "Circle of Protection: Red"]
    )
    log = "\n".join(game.log)
    assert log.index("put Pacifism into hand") < log.index("discarded 1 cards at random")


def test_w1g4_wild_researchs_blue_ability_finds_an_instant(set_pool):
    """"{1}{U}: Search your library for an **instant** card…" — the second
    ability, and a different find: the enchantments are refused here."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], lib0=_W1G4E_RESEARCH_LIBRARY,
        interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=1).supported
    game.resolve_top_of_stack()

    assert game.pending_search_library["card_type"] == "instant"
    assert not game.confirm_search_library(0, 1), "Pacifism is an enchantment"
    assert game.confirm_search_library(0, 2)
    _w1g4e_resolve_stack(game)

    assert game.players[0].hand == [], "the only card in hand was the one found"
    assert _w1g4e_names(game.players[0].graveyard) == ["Counterspell"]


def test_w1g4_wild_research_still_discards_when_it_finds_nothing(set_pool):
    """The ruling: "You do not have to find an enchantment or instant card if
    you do not want to." Failing to find is an answer (CR 701.23b), and the
    discard is not conditional on the find — a card still goes."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], hand0=["Grizzly Bears"],
        lib0=_W1G4E_RESEARCH_LIBRARY, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.decline_search_library(0)
    _w1g4e_resolve_stack(game)

    assert game.players[0].hand == []
    assert _w1g4e_names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert len(game.players[0].library) == len(_W1G4E_RESEARCH_LIBRARY)


def test_w1g4_wild_research_random_discard_comes_off_the_seeded_rng(set_pool):
    """Determinism: the same seed discards the same card, and over many seeds
    every card in the hand — the one just found included — is taken sometimes."""
    import random

    def discarded(seed):
        random.seed(seed)
        game, _, _ = _w1g4e_table(
            set_pool, mine=["Wild Research"], hand0=["Grizzly Bears", "Hill Giant"],
            lib0=["Pacifism"],
        )
        assert game.activate_permanent_ability(
            0, "Wild Research", ability_index=0
        ).supported
        game.auto_resolve_pending_choices()
        _w1g4e_resolve_stack(game)
        (card,) = game.players[0].graveyard
        return card.name  # W1G4 enchantments: what one seed discarded

    assert discarded(7) == discarded(7)
    assert {discarded(seed) for seed in range(24)} == {
        "Grizzly Bears", "Hill Giant", "Pacifism",
    }


def test_w1g4_the_older_tutor_punctuation_is_the_same_tutor_and_still_refuses():
    """The production's two halves. Wild Research's "and reveal that card. Put
    it … then discard a card at random. Then shuffle." lowers to exactly what
    the modern comma spelling does, and the search still refuses a line with
    its shuffle or its destination missing."""
    older = (
        "Search your library for an enchantment card and reveal that card. Put "
        "it into your hand, then discard a card at random. Then shuffle."
    )
    modern = (
        "Search your library for an enchantment card, reveal it, put it into "
        "your hand, discard a card at random, then shuffle."
    )
    assert _w1g4e_compile_line(older).usable
    assert _w1g4e_compile_line(older).instructions == _w1g4e_compile_line(modern).instructions
    assert not _w1g4e_compile_line(older.replace(" Then shuffle.", "")).parsed
    assert not _w1g4e_compile_line(
        "Search your library for an enchantment card and reveal that card. "
        "Then shuffle."
    ).parsed


# -- Symbiotic Deployment ----------------------------------------------------


def test_w1g4_symbiotic_deployment_skips_its_controllers_draw_step_only(set_pool):
    """"Skip your draw step." CR 614.10: the controller's draw step does not
    happen, and the opponent's does."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Symbiotic Deployment"], lib0=["Forest", "Island"],
        lib1=["Swamp", "Plains"],
    )
    game.turn = 3  # past the first turn, whose draw step CR 103.8a skips anyway

    assert game.resolve_draw_step(0) == 0
    assert game.players[0].hand == []
    assert _w1g4e_names(game.players[0].library) == ["Forest", "Island"]
    assert "P0 skips their draw step (Symbiotic Deployment)" in game.log

    assert game.resolve_draw_step(1) == 1
    assert _w1g4e_names(game.players[1].hand) == ["Swamp"]


def test_w1g4_symbiotic_deployment_taps_two_untapped_creatures_to_draw(set_pool):
    """"{1}, Tap two untapped creatures you control: Draw a card." The two
    named are the two tapped — creatures that came in this turn included, since
    the cost is not their own {T} (CR 302.6) — and one card is drawn."""
    game, mine, _ = _w1g4e_table(
        set_pool,
        mine=["Symbiotic Deployment", "Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        lib0=["Forest", "Island"], unsick=False,
    )
    _, bears, giant, elves = mine
    result = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[giant.permanent_id, elves.permanent_id],
    )
    assert result.supported, result.details
    _w1g4e_resolve_stack(game)

    assert (bears.tapped, giant.tapped, elves.tapped) == (False, True, True)
    assert not mine[0].tapped, "the enchantment itself is not tapped"
    assert _w1g4e_names(game.players[0].hand) == ["Forest"]


def test_w1g4_symbiotic_deployment_refuses_a_cost_it_cannot_be_paid(set_pool):
    """A printed cost is paid as printed or not at all: one untapped creature
    is not two, and neither an opponent's creature nor a tapped one of the
    controller's can be named — each refused with nothing tapped and no card
    drawn."""
    game, mine, theirs = _w1g4e_table(
        set_pool,
        mine=["Symbiotic Deployment", "Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        theirs=["Serra Angel"], lib0=["Forest", "Island"],
    )
    _, bears, giant, elves = mine
    theirs_named = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[bears.permanent_id, theirs[0].permanent_id],
    )
    assert not theirs_named.supported
    giant.tapped = True
    tapped_named = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert not tapped_named.supported
    assert (bears.tapped, elves.tapped, theirs[0].tapped) == (False, False, False)
    assert game.players[0].hand == []

    elves.tapped = True
    one_left = game.activate_permanent_ability(0, "Symbiotic Deployment", ability_index=0)
    assert not one_left.supported
    assert "not enough untapped creatures" in one_left.details
    assert not bears.tapped and game.players[0].hand == []


# -- Goblin Trenches ---------------------------------------------------------


def test_w1g4_goblin_trenches_turns_a_land_into_two_goblin_soldiers(set_pool):
    """"{2}, Sacrifice a land: Create two 1/1 red and white Goblin Soldier
    creature tokens." The land named is the land sacrificed, and the tokens are
    both colours and both types."""
    game, mine, _ = _w1g4e_table(
        set_pool, mine=["Goblin Trenches", "Mountain", "Plains", "Grizzly Bears"],
    )
    mountain = mine[1]
    result = game.activate_permanent_ability(
        0, "Goblin Trenches", ability_index=0,
        cost_permanent_ids=[mountain.permanent_id],
    )
    assert result.supported, result.details
    _w1g4e_resolve_stack(game)
    game._settle()

    tokens = [perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")]
    assert len(tokens) == 2
    for token in tokens:
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert token.effective_colors == {"R", "W"}
        assert token.is_creature and token.has_type("goblin") and token.has_type("soldier")
    assert not game.is_on_battlefield(mountain)
    assert game.is_on_battlefield(mine[2]) and game.is_on_battlefield(mine[3])
    assert _w1g4e_names(game.players[0].graveyard) == ["Mountain"]


def test_w1g4_goblin_trenches_sacrifices_a_land_of_its_controllers_or_nothing(set_pool):
    """"Sacrifice a **land**": a creature named for the cost is refused, so is
    the opponent's land, and with no land left the ability cannot be activated
    — no tokens for free in any of the three."""
    game, mine, theirs = _w1g4e_table(
        set_pool, mine=["Goblin Trenches", "Mountain", "Grizzly Bears"],
        theirs=["Forest"],
    )
    for named in (mine[2], theirs[0]):
        refused = game.activate_permanent_ability(
            0, "Goblin Trenches", ability_index=0,
            cost_permanent_ids=[named.permanent_id],
        )
        assert not refused.supported, named.card.name
        assert game.is_on_battlefield(named)
    assert game.activate_permanent_ability(0, "Goblin Trenches", ability_index=0).supported
    _w1g4e_resolve_stack(game)
    landless = game.activate_permanent_ability(0, "Goblin Trenches", ability_index=0)
    assert not landless.supported and "no land available" in landless.details
    assert sum(1 for perm in game.controlled_by(0) if perm.metadata.get("is_token")) == 2
    assert game.is_on_battlefield(theirs[0])


# -- Overgrown Estate --------------------------------------------------------


def test_w1g4_overgrown_estate_trades_a_land_for_three_life(set_pool):
    """"Sacrifice a land: You gain 3 life." No mana and no tap, so every land
    is three life; a creature is not a land, and with none left there is
    nothing to pay with."""
    game, mine, _ = _w1g4e_table(
        set_pool, mine=["Overgrown Estate", "Forest", "Swamp", "Grizzly Bears"],
    )
    not_a_land = game.activate_permanent_ability(
        0, "Overgrown Estate", ability_index=0,
        cost_permanent_ids=[mine[3].permanent_id],
    )
    assert not not_a_land.supported and game.players[0].life == 20

    for expected in (23, 26):
        assert game.activate_permanent_ability(0, "Overgrown Estate", ability_index=0).supported
        _w1g4e_resolve_stack(game)
        assert game.players[0].life == expected
    assert sorted(_w1g4e_names(game.players[0].graveyard)) == ["Forest", "Swamp"]
    assert not mine[0].tapped

    landless = game.activate_permanent_ability(0, "Overgrown Estate", ability_index=0)
    assert not landless.supported and game.players[0].life == 26
    assert game.is_on_battlefield(mine[3])

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5e_Game, PlayerState as _w1g5e_Player
from engine.models import Permanent as _w1g5e_Permanent
from tests.helpers import _mk_card as _w1g5e_mk_card
from tests.helpers import resolve_stack as _w1g5e_resolve_stack

_W1G5E_REQUIRED = "must be chosen as a target if able"


def _w1g5e_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0):
    """Two boards placed and unsick, *active*'s turn begun."""
    board0 = [_w1g5e_Permanent(card=card) for card in mine]
    board1 = [_w1g5e_Permanent(card=card) for card in theirs]
    filler = _w1g5e_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5e_Game(players=[
        _w1g5e_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5e_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 enchantments: the duel


def test_coalition_flag_makes_its_creature_a_flagbearer_and_the_only_target(set_pool):
    """Coalition Flag {W} Aura — "Enchant creature you control / Enchanted
    creature is a Flagbearer. / While an opponent is choosing targets …, that
    player must choose at least one Flagbearer on the battlefield if able."

    The Bears under the Flag are a Flagbearer **and no longer a Bear** (CR
    205.1a: a sentence that sets a subtype without "in addition to its other
    types" replaces the creature types it had). The opponent's Bolt may go
    nowhere else. Disenchant is not bound — the Bears are no legal target for
    it — and with the Flag gone the Bears are Bears and the next Bolt is free."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]],
        hand1=[lea["Lightning Bolt"], lea["Disenchant"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    flag = next(p for p in game.controlled_by(0) if p.card.name == "Coalition Flag")
    assert bears.has_type("flagbearer") and bears.is_creature
    assert not bears.has_type("bear")
    assert lions.has_type("cat") and not lions.has_type("flagbearer")

    offered = game.cast_target_spec(1, lea["Lightning Bolt"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    for announcement in (
        {"target_player_index": 0},
        {"target_permanent_ids": [lions.permanent_id]},
    ):
        refused = game.queue_from_hand(1, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5E_REQUIRED in refused.details, refused
        assert "Coalition Flag" in refused.details

    assert game.cast_from_hand(
        1, "Disenchant", target_permanent_ids=[flag.permanent_id]
    ).supported
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 17


def test_coalition_flag_enchants_only_its_controllers_own_creature(set_pool):
    """"Enchant creature **you control**": the picker offers the caster's own
    creatures, and a cast at an opponent's is refused with the Aura in hand."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"]], hand0=[apc["Coalition Flag"]],
    )
    offered = game.cast_target_spec(0, apc["Coalition Flag"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    refused = game.queue_from_hand(
        0, "Coalition Flag", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Coalition Flag"]


def test_the_flags_own_controller_is_not_bound_by_it(set_pool):
    """"While **an opponent** is choosing targets": the Flag's controller pumps
    their other creature beside the flagged one."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"], lea["Giant Growth"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert (lions.effective_power, lions.effective_toughness) == (5, 4)


def test_shield_of_duty_and_reason_is_protection_from_green_and_from_blue(set_pool):
    """Shield of Duty and Reason {W} Aura: "Enchanted creature has protection
    from green and from blue." Both colours, each doing protection's work: a
    green Giant Growth and a blue Unsummon may not target the creature — its
    own controller's included — a green creature may not block it, and a red
    Bolt still kills it, taking the Aura to the graveyard with it."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Savannah Lions"]], [lea["Grizzly Bears"]],
        hand0=[apc["Shield of Duty and Reason"], lea["Giant Growth"]],
        hand1=[lea["Unsummon"], lea["Lightning Bolt"]],
    )
    lions, green_bears = mine[0], theirs[0]
    assert game.cast_from_hand(
        0, "Shield of Duty and Reason", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert game._protection_qualities(lions) == {("color", "G"), ("color", "U")}

    for seat, spell in ((0, "Giant Growth"), (1, "Unsummon")):
        refused = game.queue_from_hand(seat, spell, target_permanent_ids=[lions.permanent_id])
        assert not refused.supported, (spell, refused)
    assert lions.permanent_id not in [
        game.permanent_at(entry["seat"], entry["index"]).permanent_id
        for entry in game.cast_target_spec(1, lea["Unsummon"])["valid_targets"]
    ]

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(lions)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    declared = game.declare_blockers(1, {
        game.battlefield_index_of(green_bears): [game.battlefield_index_of(lions)],
    })
    assert declared[0] is False, declared

    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id]
    ).supported
    _w1g5e_resolve_stack(game)
    game._settle()
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Savannah Lions", "Shield of Duty and Reason",
    ]


def test_coalition_flag_falls_off_a_creature_its_controller_loses(set_pool):
    """"If this card is ever on a creature you don't control, it is put into
    the graveyard as a State-Based Action" (ruling, 2004-10-04; CR 704.5m).
    The opponent's Control Magic has to be aimed at the flagged Bears — the
    only target an Aura spell of theirs may choose — and taking them takes the
    Flag off: the Bears arrive as Bears, and the requirement is gone."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]], hand1=[lea["Control Magic"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    offered = game.cast_target_spec(1, lea["Control Magic"])["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]
    stolen = game.queue_from_hand(1, "Control Magic", target_permanent_ids=[lions.permanent_id])
    assert not stolen.supported and _W1G5E_REQUIRED in stolen.details

    assert game.cast_from_hand(
        1, "Control Magic", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.controller_index_of(bears) == 1
    assert [card.name for card in game.players[0].graveyard] == ["Coalition Flag"]
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert "required_targets" not in game.cast_target_spec(1, lea["Lightning Bolt"])

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack

#: Where the furniture these tests stand beside the Sanctuaries is printed.
#: Apocalypse first, so a name it prints is always its own card.
_W1G6_SETS = ("APC", "LEA", "LEG")


def _w1g6_find(set_pool, name):
    for w1g6_code in _W1G6_SETS:
        w1g6_found = set_pool(w1g6_code).get(name)
        if w1g6_found is not None:
            return w1g6_found
    raise KeyError(name)  # _w1g6_find


def _w1g6_table(set_pool, mine=(), theirs=(), interactive=False):
    """A two-seat table on seat 0's turn with *mine* / *theirs* already on the
    battlefield. Costs are off: every card here acts in an upkeep, for free."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A"), _W1G6PlayerState(name="W1G6-B"),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.active_player_index = 0
    if interactive:
        w1g6_game.interactive_seats.add(0)
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((mine, theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_perm = _W1G6Permanent(card=_w1g6_find(set_pool, w1g6_name))
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_perm.metadata["summoning_sickness_turn"] = -99
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0], w1g6_rows[1]  # _w1g6_table


def _w1g6_upkeep(game, seat=0):
    """Run *seat*'s upkeep step and leave what triggered on the stack; returns
    the names of the sources there."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_upkeep


def _w1g6_enter(game, set_pool, seat, name):
    """Put one more permanent onto *seat*'s battlefield — "in response"."""
    w1g6_new = _W1G6Permanent(card=_w1g6_find(set_pool, name))
    game._put_permanent_onto_battlefield(seat, w1g6_new, None)
    return w1g6_new  # _w1g6_enter


@_w1g6_pytest.mark.parametrize("name", [
    "Ana Sanctuary", "Ceta Sanctuary", "Dega Sanctuary", "Necra Sanctuary",
    "Raka Sanctuary",
])
def test_w1g6_every_sanctuary_compiles_one_gated_two_armed_trigger(set_pool, name):
    """The cycle is one template: an upkeep trigger with an intervening "if"
    over either colour, whose effect is two arms of which exactly one runs.
    Neither arm may be empty — Raka Sanctuary's upgrade arm compiled to no
    instruction at all on arrival and the card still read supported."""
    program = _w1g6_compile(set_pool("APC")[name])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    payload = trigger.instruction.payload
    assert trigger.instruction.kind == "if_then"
    assert len(payload["intervening_if"]["filter"]["any_colors"]) == 2
    assert payload["then"] and payload["else"], payload


# Dega Sanctuary -------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("mine, life", [
    ((), 20),
    # A land has no colour (CR 105.2c), whatever mana it makes.
    (("Swamp",), 20),
    (("Black Knight",), 22),
    (("Goblin King",), 22),
    # Both colours: 4 *instead* — "2 or 4 life, but never 6" (the card's
    # ruling, 2004-10-04).
    (("Black Knight", "Goblin King"), 24),
    # One permanent that is both colours is a black permanent and a red one.
    (("Lady Orca",), 24),
])
def test_w1g6_dega_sanctuary_gains_two_or_four_never_six(set_pool, mine, life):
    game, _mine, _theirs = _w1g6_table(set_pool, mine=("Dega Sanctuary",) + mine)

    triggered = _w1g6_upkeep(game)
    _w1g6_resolve_stack(game)

    assert triggered == (["Dega Sanctuary"] if life > 20 else [])
    assert [player.life for player in game.players] == [life, 20]


def test_w1g6_dega_sanctuary_reads_its_controllers_board_on_their_upkeep(set_pool):
    """"**Your** upkeep", "**you** control": an opponent's black creature is no
    condition, and the opponent's upkeep is no trigger."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Dega Sanctuary"], theirs=["Black Knight", "Goblin King"],
    )
    assert _w1g6_upkeep(game) == []

    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Dega Sanctuary", "Black Knight"],
    )
    assert _w1g6_upkeep(game, seat=1) == []
    assert [player.life for player in game.players] == [20, 20]


# Ana Sanctuary --------------------------------------------------------------


def test_w1g6_ana_sanctuary_asks_for_its_target_as_it_triggers(set_pool):
    """"…target creature gets +1/+1 until end of turn." The target is chosen
    as the trigger goes on the stack (CR 603.3d), from every creature on the
    table and nothing else; the answer is the creature pumped, and the pump
    ends with the turn."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer", "Forest"],
        theirs=["Hill Giant", "Sol Ring"], interactive=True,
    )
    giant = theirs[0]

    assert _w1g6_upkeep(game) == ["Ana Sanctuary"]
    (prompt,) = game.pending_choices
    assert prompt.kind == "trigger_target" and prompt.player_index == 0
    assert [entry["name"] for entry in prompt.data["targets"]] == [
        "Prodigal Sorcerer", "Hill Giant",
    ]
    # A land is not on the list, and naming it is not an answer.
    assert not game.confirm_trigger_target(0, permanent_id=mine[2].permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    _w1g6_resolve_stack(game)

    assert (giant.effective_power, giant.effective_toughness) == (4, 4)
    assert "Ana Sanctuary gives Hill Giant +1/+1 until end of turn" in game.log
    game.resolve_cleanup_step(0)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)


@_w1g6_pytest.mark.parametrize("colours, size", [
    (("Prodigal Sorcerer",), (4, 4)),
    (("Black Knight",), (4, 4)),
    # "+1/+1 or +5/+5, never +6/+6" (the card's ruling, 2004-10-04).
    (("Prodigal Sorcerer", "Black Knight"), (8, 8)),
    (("Sivitri Scarzam",), (8, 8)),
])
def test_w1g6_ana_sanctuary_pumps_by_one_or_by_five(set_pool, colours, size):
    game, mine, theirs = _w1g6_table(
        set_pool, mine=("Ana Sanctuary",) + colours, theirs=["Hill Giant"],
        interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, permanent_id=theirs[0].permanent_id)
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == size


def test_w1g6_ana_sanctuary_decides_the_upgrade_as_it_resolves(set_pool):
    """The target is announced with one colour in play; the second arrives in
    response. Which arm runs is asked at resolution (CR 608.2c: the "instead"
    sentence replaces the first as the effect is carried out), so the creature
    already chosen gets +5/+5."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Hill Giant"],
        interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, permanent_id=theirs[0].permanent_id)
    _w1g6_enter(game, set_pool, 0, "Black Knight")
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (8, 8)


def test_w1g6_ana_sanctuary_does_nothing_if_its_condition_is_gone(set_pool):
    """CR 603.4: the intervening "if" is checked again as the ability
    resolves. The only blue permanent leaves in response, and the creature the
    trigger was aimed at is not pumped."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Hill Giant"],
    )
    assert _w1g6_upkeep(game) == ["Ana Sanctuary"]
    game.remove_from_battlefield(mine[1])
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (3, 3)
    assert "Ana Sanctuary ability did nothing: its condition is no longer true" in game.log


def test_w1g6_ana_sanctuary_never_pumps_a_bystander_for_an_illegal_pick(set_pool):
    """The upkeep step also takes a target as an answer in hand
    (``trigger_targets``). A pick the trigger could not have chosen — a land —
    used to be stamped on the stack object anyway, and the pump handler's
    fallback then took the first creature on *that seat's* battlefield: the
    opponent's Hill Giant, which nobody named. It is set aside and the trigger
    chooses for itself, from its own legal list."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Forest", "Hill Giant"],
    )
    sanctuary, sorcerer = mine
    giant = theirs[1]

    game.resolve_upkeep(
        0, defer_priority=True, trigger_targets={sanctuary.permanent_id: (1, 0)},
    )
    _w1g6_resolve_stack(game)

    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert (sorcerer.effective_power, sorcerer.effective_toughness) == (2, 2)

    # …and a pick it could have chosen is the creature pumped.
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Forest", "Hill Giant"],
    )
    game.resolve_upkeep(
        0, defer_priority=True, trigger_targets={mine[0].permanent_id: (1, 1)},
    )
    _w1g6_resolve_stack(game)
    assert (theirs[1].effective_power, theirs[1].effective_toughness) == (4, 4)


def test_w1g6_ana_sanctuary_with_no_creature_to_target_leaves_the_stack(set_pool):
    """The condition holds (Undertow is a blue permanent) and there is no
    creature anywhere: CR 603.3d removes a trigger that cannot choose its
    target."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Ana Sanctuary", "Undertow"])

    assert _w1g6_upkeep(game) == []
    assert (
        "Ana Sanctuary's triggered ability was removed from the stack: "
        "it has no legal target (603.3d)"
    ) in game.log


# Raka Sanctuary -------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("colours, damage", [
    (("White Knight",), 1),
    (("Prodigal Sorcerer",), 1),
    # "1 or 3 damage, but never 4" (the card's ruling, 2004-10-04). This arm
    # dealt nothing at all on arrival: "this enchantment deals 3 damage
    # instead" names no recipient, and it compiled to no instruction.
    (("White Knight", "Prodigal Sorcerer"), 3),
    (("Tobias Andrion",), 3),
])
def test_w1g6_raka_sanctuary_deals_one_or_three_to_the_chosen_creature(
    set_pool, colours, damage,
):
    game, mine, theirs = _w1g6_table(
        set_pool, mine=("Raka Sanctuary",) + colours, theirs=["Craw Wurm"],
        interactive=True,
    )
    wurm = theirs[0]

    assert _w1g6_upkeep(game) == ["Raka Sanctuary"]
    assert game.confirm_trigger_target(0, permanent_id=wurm.permanent_id)
    _w1g6_resolve_stack(game)

    assert wurm.damage_marked == damage
    assert f"Raka Sanctuary dealt {damage} damage to Craw Wurm" in game.log
    assert [player.life for player in game.players] == [20, 20]


def test_w1g6_raka_sanctuarys_three_kills_what_its_one_would_not(set_pool):
    """A headless seat aims the damage at an opponent's creature when there is
    one; three is lethal to a Hill Giant and one is not."""
    for colours, survives in (
        (("White Knight",), True),
        (("White Knight", "Prodigal Sorcerer"), False),
    ):
        game, _mine, theirs = _w1g6_table(
            set_pool, mine=("Raka Sanctuary",) + colours, theirs=["Hill Giant"],
        )
        _w1g6_upkeep(game)
        _w1g6_resolve_stack(game)
        game.check_state_based_actions()

        assert game.is_on_battlefield(theirs[0]) is survives
        assert [card.name for card in game.players[1].graveyard] == (
            [] if survives else ["Hill Giant"]
        )


# Ceta Sanctuary -------------------------------------------------------------


def _w1g6_ceta(set_pool, colours, interactive=False):
    """Ceta Sanctuary beside *colours*, two cards in hand and a library to
    draw from; returns the game after the upkeep trigger has resolved (the
    discard it asks for still owed)."""
    w1g6_game, _w1g6_mine, _w1g6_theirs = _w1g6_table(
        set_pool, mine=("Ceta Sanctuary",) + tuple(colours), interactive=interactive,
    )
    w1g6_player = w1g6_game.players[0]
    w1g6_player.hand = [_w1g6_find(set_pool, "Island"), _w1g6_find(set_pool, "Swamp")]
    w1g6_player.library = [_w1g6_find(set_pool, "Forest")] * 6
    w1g6_triggered = _w1g6_upkeep(w1g6_game)
    _w1g6_resolve_stack(w1g6_game)
    return w1g6_game, w1g6_triggered  # _w1g6_ceta


@_w1g6_pytest.mark.parametrize("colours, drawn", [
    (("Hill Giant",), 1),
    (("Grizzly Bears",), 1),
    # "One or two cards, but never three" (the card's ruling, 2004-10-04).
    (("Hill Giant", "Grizzly Bears"), 2),
    (("Jerrard of the Closed Fist",), 2),
])
def test_w1g6_ceta_sanctuary_draws_one_or_two_then_discards_one(set_pool, colours, drawn):
    """"…draw a card, then discard a card. If you control a red permanent and
    a green permanent, **instead** draw two cards, then discard a card." The
    whole first sentence is what the second replaces: one loot, of one size."""
    game, triggered = _w1g6_ceta(set_pool, colours, interactive=True)
    player = game.players[0]

    assert triggered == ["Ceta Sanctuary"]
    assert len(player.hand) == 2 + drawn and len(player.library) == 6 - drawn
    assert f"Ceta Sanctuary: W1G6-A drew {drawn} card(s)" in game.log
    # The discard is the player's to choose, and exactly one is owed.
    (prompt,) = game.pending_choices
    assert prompt.kind == "discard" and prompt.data["count"] == 1
    assert game.confirm_discard(0, [0])
    assert [card.name for card in player.graveyard] == ["Island"]
    assert len(player.hand) == 1 + drawn
    assert not game.pending_choices


def test_w1g6_ceta_sanctuary_without_red_or_green_does_not_trigger(set_pool):
    game, triggered = _w1g6_ceta(set_pool, ("Prodigal Sorcerer", "Forest"))

    assert triggered == []
    assert len(game.players[0].hand) == 2 and len(game.players[0].library) == 6


# Necra Sanctuary ------------------------------------------------------------


def test_w1g6_necra_sanctuary_asks_which_player_and_may_name_its_own(set_pool):
    """"…target player loses 1 life." Any player, the controller included; the
    choice is made as the trigger goes on the stack."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Necra Sanctuary", "Grizzly Bears"], interactive=True,
    )
    assert _w1g6_upkeep(game) == ["Necra Sanctuary"]
    (prompt,) = game.pending_choices
    assert [(entry["kind"], entry["seat"]) for entry in prompt.data["targets"]] == [
        ("player", 0), ("player", 1),
    ]
    assert game.confirm_trigger_target(0, seat=0)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [19, 20]


@_w1g6_pytest.mark.parametrize("colours, lost", [
    (("Grizzly Bears",), 1),
    (("White Knight",), 1),
    # "0, 1, or 3 life, but never 4" (the card's ruling, 2004-10-04).
    (("Grizzly Bears", "White Knight"), 3),
    # "One permanent that is both white and green will cause the player to be
    # affected by the lose 3 life portion." (The same ruling.)
    (("Jasmine Boreal",), 3),
])
def test_w1g6_necra_sanctuary_costs_the_chosen_player_one_or_three(set_pool, colours, lost):
    """"…**that player** loses 3 life instead": the upgrade lands on the player
    the first sentence targeted, and only one of the two sentences happens."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=("Necra Sanctuary",) + colours, interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, seat=1)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [20, 20 - lost]
    assert f"Necra Sanctuary: W1G6-B lost {lost} life (20 -> {20 - lost})" in game.log


def test_w1g6_necra_sanctuary_checks_its_condition_at_both_ends(set_pool):
    """CR 603.4. No green or white permanent: no trigger. One at the trigger
    and none at resolution: the ability does nothing. One at the trigger and
    both at resolution: three, to the player already chosen."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Black Knight"])
    assert _w1g6_upkeep(game) == []

    game, mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Grizzly Bears"])
    assert _w1g6_upkeep(game) == ["Necra Sanctuary"]
    game.remove_from_battlefield(mine[1])
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]
    assert "Necra Sanctuary ability did nothing: its condition is no longer true" in game.log

    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Grizzly Bears"])
    _w1g6_upkeep(game)
    _w1g6_enter(game, set_pool, 0, "White Knight")
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 17]


# Phyrexian Arena ------------------------------------------------------------


def test_w1g6_phyrexian_arena_draws_and_bleeds_on_its_controllers_upkeep(set_pool):
    """"At the beginning of your upkeep, you draw a card and lose 1 life." Both
    halves, once, on its controller's upkeep and not the opponent's."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Phyrexian Arena"])
    for player in game.players:
        player.library = [_w1g6_find(set_pool, "Forest")] * 4

    assert _w1g6_upkeep(game) == ["Phyrexian Arena"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [19, 20]
    assert [len(player.hand) for player in game.players] == [1, 0]
    assert "Phyrexian Arena: W1G6-A lost 1 life (20 -> 19)" in game.log

    assert _w1g6_upkeep(game, seat=1) == []
    assert [player.life for player in game.players] == [19, 20]
    assert [len(player.hand) for player in game.players] == [1, 0]

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests moved whole to test_apc_enchantments_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests moved whole to test_apc_enchantments_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests moved whole to test_apc_enchantments_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

from engine import Game as _w2g3_Game, PlayerState as _w2g3_PlayerState
from engine.models import Permanent as _w2g3_Permanent
from tests.helpers import resolve_stack as _w2g3_resolve_stack

#: Where the borrowed cards were first printed; every other name is Apocalypse's.
_W2G3_SANCTUARY_HOMES = {
    "White Knight": "LEA", "Hill Giant": "LEA", "Grizzly Bears": "LEA", "Forest": "LEA",
}


def _w2g3_sanctuary_upkeep(set_pool):
    """Seat 0 — a person, so CR 603.3d's choice is asked rather than defaulted
    — controls a Raka Sanctuary and a white permanent; seat 1 controls a Hill
    Giant and a Grizzly Bears. Seat 0's upkeep has begun and the Sanctuary's
    trigger is on the stack waiting for its target. Returns the game and seat
    1's two creatures."""
    forest = set_pool("LEA")["Forest"]
    game = _w2g3_Game(players=[
        _w2g3_PlayerState(name="P0", library=[forest] * 6),
        _w2g3_PlayerState(name="P1", library=[forest] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.active_player_index = 0
    placed = []
    for seat, name in (
        (0, "Raka Sanctuary"), (0, "White Knight"), (1, "Hill Giant"), (1, "Grizzly Bears"),
    ):
        perm = _w2g3_Permanent(
            card=set_pool(_W2G3_SANCTUARY_HOMES.get(name, "APC"))[name]
        )
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        placed.append(perm)
    game.resolve_upkeep(0, defer_priority=True)
    return game, placed[2], placed[3]


def test_w2g3_raka_sanctuary_does_not_hit_the_creature_beside_a_target_that_left(set_pool):
    """"…this enchantment deals 1 damage to **target creature**." Its
    controller chooses the Hill Giant as the trigger goes on the stack (CR
    603.3d), and the Giant leaves the battlefield in response. CR 608.2b: the
    one target is illegal, so the ability does not resolve — where it used to
    deal its damage to the Grizzly Bears, which had slid into the Giant's
    battlefield slot and which nobody chose."""
    game, giant, bears = _w2g3_sanctuary_upkeep(set_pool)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)

    game.remove_from_battlefield(giant)
    game.players[1].graveyard.append(giant.card)
    _w2g3_resolve_stack(game)

    assert (
        "Raka Sanctuary ability was removed from the stack: "
        "every target is illegal (608.2b)"
    ) in game.log, game.log[-4:]
    assert bears.damage_marked == 0, game.log[-4:]
    assert not game.stack


def test_w2g3_raka_sanctuary_does_not_hit_a_target_that_gained_protection(set_pool):
    """The same trigger, its chosen target still on the battlefield but given
    protection from red in response (Raka Sanctuary is a red enchantment): not
    a creature the ability could name any more, so not one it damages."""
    assert set_pool("APC")["Raka Sanctuary"].colors == ("R",)
    game, giant, _bears = _w2g3_sanctuary_upkeep(set_pool)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)

    giant.metadata["protection_from_red"] = True
    _w2g3_resolve_stack(game)

    assert giant.damage_marked == 0, game.log[-4:]
    assert any("every target is illegal (608.2b)" in line for line in game.log)


def test_w2g3_raka_sanctuary_still_deals_its_damage_to_a_legal_target(set_pool):
    """The other direction: nothing happens in response, and the chosen
    creature takes the 1 damage one colour buys."""
    game, giant, bears = _w2g3_sanctuary_upkeep(set_pool)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)

    _w2g3_resolve_stack(game)

    assert giant.damage_marked == 1, game.log[-4:]
    assert bears.damage_marked == 0
    assert not any("608.2b" in line for line in game.log)

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.
from engine import Game as _w2g4_Game
from engine import PlayerState as _w2g4_PlayerState
from engine.models import Permanent as _w2g4_Permanent
from tests.helpers import _nosick as _w2g4_nosick
from tests.helpers import resolve_stack as _w2g4_resolve_stack


def _w2g4_enchantment_table(set_pool, catalog_by_name, mine, *, their_hand, interactive=(0,)):
    """Seat 0 controls *mine* (Apocalypse cards first, the pool otherwise) at
    its main phase; seat 1 holds *their_hand*. Mana costs are not enforced
    while the table is laid and the caller turns them on for what it charges."""
    def card(name):
        return set_pool("APC").get(name) or catalog_by_name[name]

    board = [_w2g4_nosick(_w2g4_Permanent(card=card(name))) for name in mine]
    game = _w2g4_Game(players=[
        _w2g4_PlayerState(name="Keeper", battlefield=board,
                          library=[catalog_by_name["Forest"]] * 6),
        _w2g4_PlayerState(name="Caster", hand=[card(name) for name in their_hand],
                          library=[catalog_by_name["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game, board  # W2G4: the enchantment table


def _w2g4_spells(game) -> list:
    return [item for item in game.stack if not item.is_ability]  # W2G4: spells only


# -- item 2: a cast trigger is about the spell that fired it ------------------


def test_w2g4_ice_cave_prices_and_counters_the_spell_its_trigger_fired_on(
    set_pool, catalog_by_name
):
    """"Whenever a player casts a spell, any other player may pay that spell's
    mana cost. If a player does, counter the spell."

    Two Fireballs are one card and two spells — one cast for X=1, one for X=3
    in response. The top trigger is the second Fireball's: the price it offers
    is {3}{R}, paying it taps all four lands, and the Fireball it counters is
    the X=3 one. It used to find the first Fireball by its card: the offer was
    {1}{R} and the spell countered was the wrong one.
    """
    game, board = _w2g4_enchantment_table(
        set_pool, catalog_by_name,
        ["Ice Cave", "Mountain", "Island", "Island", "Island"],
        their_hand=["Fireball", "Fireball"],
    )
    lands = board[1:]
    assert game.queue_from_hand(1, "Fireball", target_player_index=0, x_value=1).supported
    assert game.queue_from_hand(1, "Fireball", target_player_index=0, x_value=3).supported
    small, large = _w2g4_spells(game)
    assert small.card is large.card and (small.x_value, large.x_value) == (1, 3)
    assert [item.card.name for item in game.stack] == [
        "Fireball", "Ice Cave", "Fireball", "Ice Cave",
    ]
    game.enforce_mana_costs = True

    game.resolve_top_of_stack(pause_for_choices=True)
    (asked,) = [choice for choice in game.pending_choices if choice.kind == "optional_pay"]
    assert asked.player_index == 0
    assert asked.data["prompt"] == "Pay {3}{R} (Fireball's mana cost)?"
    assert game.confirm_optional_pay(0, accept=True) is True

    assert all(land.tapped for land in lands)
    assert _w2g4_spells(game) == [small] and _w2g4_spells(game)[0] is small
    assert "Fireball was countered by Ice Cave and moved to graveyard" in game.log

    # The first Fireball's own trigger is still under it, and asks its own
    # price; with every land tapped a yes buys nothing, and it resolves for 1.
    game.resolve_top_of_stack(pause_for_choices=True)
    (asked,) = [choice for choice in game.pending_choices if choice.kind == "optional_pay"]
    assert asked.data["prompt"] == "Pay {1}{R} (Fireball's mana cost)?"
    assert game.confirm_optional_pay(0, accept=False) is True
    game.enforce_mana_costs = False
    _w2g4_resolve_stack(game)
    assert game.players[0].life == 19


def test_w2g4_ice_cave_offers_nothing_once_its_spell_has_left_the_stack(
    set_pool, catalog_by_name
):
    """The second Fireball is countered in response to its own Ice Cave
    trigger. A price nobody can pay is an offer nobody is made (CR 118.6) — and
    the first Fireball, which is the same card, is neither priced nor
    countered in its place."""
    game, board = _w2g4_enchantment_table(
        set_pool, catalog_by_name,
        ["Ice Cave", "Mountain", "Island", "Island", "Island"],
        their_hand=["Fireball", "Fireball"],
    )
    game.queue_from_hand(1, "Fireball", target_player_index=0, x_value=1)
    game.queue_from_hand(1, "Fireball", target_player_index=0, x_value=3)
    small, large = _w2g4_spells(game)
    game.enforce_mana_costs = True

    game.counter_stack_object(large)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.pending_choices == []
    assert _w2g4_spells(game)[0] is small and len(_w2g4_spells(game)) == 1
    assert not any(land.tapped for land in board[1:])

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
