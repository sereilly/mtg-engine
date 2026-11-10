"""Mirrodin instants, the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_derive_cast_spec
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def test_w1g6_forge_armor_puts_the_sacrificed_artifact_s_mana_value_in_counters(
    set_pool,
):
    """"As an additional cost to cast this spell, sacrifice an artifact." /
    "Put X +1/+1 counters on target creature, where X is the sacrificed
    artifact's mana value."

    The artifact named for the cost is the one paid (CR 601.2h), and its mana
    value — read off what the cost ate, not off the board — is how many
    counters land: Oblivion Stone ({3}) makes a 1/1 Myr a 4/4, while the cheaper
    artifact beside it is kept.
    """
    pool = set_pool("MRD")
    card = pool["Forge Armor"]
    program = _w1g6_compile(card)
    assert program.supported, program.reason
    assert _w1g6_derive_cast_spec(card, program) == {
        "kind": "creature",
        "cost_spec": {"kind": "artifact", "own_only": True, "sacrifice_cost": True},
    }

    stone = _w1g6_Permanent(card=pool["Oblivion Stone"])      # mana value 3
    chalice = _w1g6_Permanent(card=pool["Chalice of the Void"])  # mana value 0
    myr = _w1g6_Permanent(card=pool["Leaden Myr"])            # a 1/1
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=[stone, chalice, myr],
                          hand=[card]),
        _w1g6_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.queue_from_hand(
        0, "Forge Armor",
        cost_permanent_ids=[stone.permanent_id],
        target_permanent_ids=[myr.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(stone)
    assert game.is_on_battlefield(chalice)
    _w1g6_resolve_stack(game)

    assert myr.metadata.get("plus_counters") == 3
    assert (myr.effective_power, myr.effective_toughness) == (4, 4)

# ==== end W1G6 ======================================================


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
from engine.models import PlayerState as _W1G11PlayerState

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, hand, *, library=(), bob_library=()):
    lea = set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) or [lea["Plains"]] * 6,
    )
    bob = _W1G11PlayerState(
        name="Bob", library=list(bob_library) or [lea["Island"]] * 6,
    )
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def test_w1g11_spoils_of_the_vault_digs_to_the_name_and_pays_a_life_per_exile(set_pool):
    """A person names Shivan Dragon, three cards down: three exiled, 3 life."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Swamp"], lea["Plains"], lea["Shivan Dragon"],
               lea["Forest"]]
    game, alice, _bob = _w1g11_table(set_pool, [mrd["Spoils of the Vault"]],
                                     library=library)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    assert not game.resolve_top_of_stack(), "held for the name (CR 608.2)"
    (choice,) = [c for c in game.pending_choices if c.kind == "name_then_consult"]
    assert choice.player_index == 0
    assert game.confirm_name_then_consult(0, "Shivan Dragon")
    _w1g11_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Shivan Dragon"]
    assert sorted(c.name for c in alice.exile) == ["Island", "Plains", "Swamp"]
    assert [c.name for c in alice.library] == ["Forest"]
    assert alice.life == 20 - 3
    assert [c.name for c in alice.graveyard] == ["Spoils of the Vault"]


def test_w1g11_spoils_of_the_vault_naming_a_missing_card_exiles_the_library(set_pool):
    """The ruling (2018-12-07): a name the library does not hold exiles the
    library and costs a life for each card."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g11_table(
        set_pool, [mrd["Spoils of the Vault"]], library=[lea["Island"]] * 4,
    )
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    assert not game.resolve_top_of_stack(), "held for the name (CR 608.2)"
    assert game.confirm_name_then_consult(0, "Shivan Dragon")
    _w1g11_resolve_stack(game)
    assert alice.hand == []
    assert alice.library == []
    assert len(alice.exile) == 4
    assert alice.life == 16


def test_w1g11_spoils_of_the_vault_left_to_itself_names_from_its_own_library(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Shivan Dragon"], lea["Shivan Dragon"]]
    game, alice, _bob = _w1g11_table(set_pool, [mrd["Spoils of the Vault"]],
                                     library=library)
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Shivan Dragon"]
    assert [c.name for c in alice.exile] == ["Island"]
    assert alice.life == 19

def _w1g11_reminder_table(set_pool, *, bob_cast=("Shivan Dragon",)):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Shivan Dragon"], lea["Lightning Bolt"],
               lea["Forest"]]
    game, alice, bob = _w1g11_table(set_pool, [mrd["Grim Reminder"]],
                                    library=library)
    bob.spells_cast_this_turn.extend(lea[name] for name in bob_cast)
    return game, alice, bob


def _w1g11_index_of(library, name):
    return next(i for i, card in enumerate(library) if card.name == name)


def test_w1g11_grim_reminder_punishes_the_opponent_who_cast_the_revealed_name(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Grim Reminder").supported
    assert not game.resolve_top_of_stack(), "held for the search"
    (choice,) = [c for c in game.pending_choices if c.kind == "search_library"]
    # A land is not a nonland card: the pick is refused.
    assert not game.confirm_search_library(0, _w1g11_index_of(alice.library, "Island"))
    assert game.confirm_search_library(
        0, _w1g11_index_of(alice.library, "Shivan Dragon"),
    )
    _w1g11_resolve_stack(game)
    assert bob.life == 14
    assert alice.life == 20
    # Revealed, never moved: the Dragon is still in the (shuffled) library.
    assert sorted(c.name for c in alice.library) == [
        "Forest", "Island", "Lightning Bolt", "Shivan Dragon",
    ]
    assert alice.hand == []
    assert any("revealed Shivan Dragon" in line for line in game.log)


def test_w1g11_grim_reminder_revealing_another_name_costs_nobody_life(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Grim Reminder").supported
    game.resolve_top_of_stack()
    assert game.confirm_search_library(
        0, _w1g11_index_of(alice.library, "Lightning Bolt"),
    )
    _w1g11_resolve_stack(game)
    assert bob.life == 20


def test_w1g11_grim_reminder_left_to_itself_shows_a_name_an_opponent_cast(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool, bob_cast=("Lightning Bolt",))
    assert game.cast_from_hand(0, "Grim Reminder").supported
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g11_resolve_stack(game)
    assert bob.life == 14


def test_w1g11_grim_reminder_returns_from_the_graveyard_only_during_upkeep(set_pool):
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool, [])
    alice.graveyard.append(mrd["Grim Reminder"])
    refused = game.activate_from_graveyard(0, "Grim Reminder")
    assert not refused.supported
    game.current_phase = "beginning"
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    result = game.activate_from_graveyard(0, "Grim Reminder")
    assert result.supported, result.details
    _w1g11_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Grim Reminder"]
    assert alice.graveyard == []

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# Awe Strike: CR 615.8's shield keyed on the creature the spell targets, with
# no recipient printed (Penance's reach), and Reverse Damage's CR 615.5 rider
# paid to the caster. The sweep and look-alike boards are in
# tests/rules/test_mrd_w1g12_awe_strike.py.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine import targeting as _w1g12_targeting
from engine.models import Permanent as _w1g12_Permanent
from engine.oracle import compile_card_oracle as _w1g12_compile
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
        ),
        _w1g12_PlayerState("B", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g12_awe_strike_turns_an_unblocked_attackers_damage_into_life(set_pool):
    awe = _w1g12_card(set_pool, "Awe Strike")
    assert _w1g12_targeting.derive_cast_spec(awe, _w1g12_compile(awe)) == {
        "kind": "creature",
    }
    game, _, (wurm,) = _w1g12_table(set_pool, hand=["Awe Strike"], theirs=["Craw Wurm"])
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    game.advance_combat_phase()
    assert game.players[0].life == 26
    assert "A gained 6 life from Awe Strike (20 -> 26)" in game.log


def test_w1g12_awe_strike_on_a_creature_that_leaves_does_nothing(set_pool):
    # CR 608.2b: its only target gone, the spell does nothing, and a Wurm that
    # comes back would be a new object the shield never named (CR 400.7).
    game, _, (wurm,) = _w1g12_table(set_pool, hand=["Awe Strike"], theirs=["Craw Wurm"])
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 20
    assert not any("the next damage" in line for line in game.log)


# Bloodscent: "All creatures able to block target creature this turn do so."
# Lure's CR 509.1c requirement for a turn, marked on the targeted attacker and
# read where Lure's printed and granted channels are, so it binds every
# creature able to block at declaration — one that entered after the spell
# resolved included (CR 611.2c fixes no set for a requirement).


def _w1g12_lured_attack(set_pool):
    game, (wurm,), theirs = _w1g12_table(
        set_pool, hand=["Bloodscent"], mine=["Craw Wurm"],
        theirs=["Grizzly Bears", "Grizzly Bears", "Llanowar Elves"],
    )
    theirs[2].tapped = True  # a tapped creature is not able to block
    assert game.queue_from_hand(
        0, "Bloodscent", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    late = _w1g12_Permanent(card=_w1g12_card(set_pool, "Grizzly Bears"))
    game._put_permanent_onto_battlefield(1, late, None)
    _w1g12_nosick(late)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return game, wurm


def test_w1g12_bloodscent_compels_every_untapped_creature_to_block_it(set_pool):
    game, wurm = _w1g12_lured_attack(set_pool)
    bears = [
        game.battlefield_index_of(p) for p in game.controlled_by(1)
        if p.card.name == "Grizzly Bears"
    ]
    assert len(bears) == 3
    assert sorted(req.blocker for req in game.block_requirements(1)) == sorted(bears)
    assert not game.declare_blockers(1, {})[0]
    assert not game.declare_blockers(1, {bears[0]: 0, bears[1]: 0})[0]
    ok, why = game.declare_blockers(1, {slot: 0 for slot in bears})
    assert ok, why
    game.advance_combat_phase()
    assert game.players[1].life == 20


def test_w1g12_bloodscent_ends_with_the_turn(set_pool):
    game, wurm = _w1g12_lured_attack(set_pool)
    bears = [
        game.battlefield_index_of(p) for p in game.controlled_by(1)
        if p.card.name == "Grizzly Bears"
    ]
    assert game.declare_blockers(1, {slot: 0 for slot in bears})[0]
    assert wurm.metadata.get("must_be_blocked_by_all_until_eot")
    game.resolve_cleanup_step(0)  # CR 514.2
    assert not wurm.metadata.get("must_be_blocked_by_all_until_eot")


# The drive list: Mirrodin instants that compiled supported on arrival.


def test_w1g12_razor_barrier_offers_artifacts_or_a_colour(set_pool):
    for answer, colour, protected_from in (
        (0, None, "protection_from_artifacts"),
        (1, "R", "protection_from_red"),
    ):
        game, (bears,), _ = _w1g12_table(
            set_pool, hand=["Razor Barrier"], mine=["Grizzly Bears"], interactive=(0,),
        )
        assert game.queue_from_hand(
            0, "Razor Barrier", target_permanent_ids=[bears.permanent_id],
        ).supported
        game.resolve_top_of_stack()
        (choice,) = game.pending_choices
        assert choice.kind == "mode_choice"
        assert choice.data["labels"] == [
            "protection from artifacts", "protection from the color of your choice",
        ]
        assert game.resolve_pending_choice("mode_choice", 0, mode_index=answer)
        if colour is not None:
            (pick,) = game.pending_choices
            assert pick.kind == "color_choice"
            assert game.resolve_pending_choice("color_choice", 0, mana_color=colour)
        assert bears.metadata.get(protected_from)
        assert game.players[0].graveyard[-1].name == "Razor Barrier"


def test_w1g12_razor_barrier_targets_only_your_permanent(set_pool):
    game, _, (myr,) = _w1g12_table(set_pool, hand=["Razor Barrier"], theirs=["Alpha Myr"])
    assert not game.queue_from_hand(
        0, "Razor Barrier", target_permanent_ids=[myr.permanent_id],
    ).supported


def test_w1g12_regress_and_altars_light(set_pool):
    game, _, (myr, crusade) = _w1g12_table(
        set_pool, hand=["Regress", "Altar's Light"], theirs=["Alpha Myr", "Crusade"],
    )
    assert game.queue_from_hand(0, "Regress", target_permanent_ids=[myr.permanent_id]).supported
    _w1g12_resolve_stack(game)
    assert [c.name for c in game.players[1].hand] == ["Alpha Myr"]
    assert game.queue_from_hand(
        0, "Altar's Light", target_permanent_ids=[crusade.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Crusade"]
    game, (bears,), _ = _w1g12_table(set_pool, hand=["Altar's Light"], mine=["Grizzly Bears"])
    assert not game.queue_from_hand(
        0, "Altar's Light", target_permanent_ids=[bears.permanent_id],
    ).supported

# ==== end W1G12 ======================================================


# ==== W2G7 ==========================================================
# W2G7's tests go between this line and the "end W2G7" line.
#
# Second Sunrise: "Each player returns to the battlefield all artifact,
# creature, enchantment, and land cards in their graveyard that were put there
# from the battlefield this turn." The sweep reanimation (All Hallow's Eve)
# with No Rest for the Wicked's history lifted beside its filter, answered by
# the record ``Game.put_card_into_graveyard`` keeps.

from engine import Game as _w2g7_Game
from engine import PlayerState as _w2g7_PlayerState
from engine import targeting as _w2g7_targeting
from engine.models import Permanent as _w2g7_Permanent
from engine.oracle import compile_card_oracle as _w2g7_compile
from tests.helpers import _nosick as _w2g7_nosick
from tests.helpers import resolve_stack as _w2g7_resolve_stack


def _w2g7_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w2g7_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=()):
    card = lambda name: _w2g7_card(set_pool, name)  # noqa: E731
    game = _w2g7_Game(players=[
        _w2g7_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
            graveyard=[card(n) for n in graveyard],
        ),
        _w2g7_PlayerState("B", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w2g7_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w2g7_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w2g7_names(cards):
    return sorted(card.name for card in cards)


def test_w2g7_second_sunrise_returns_each_players_permanents_that_died_this_turn(set_pool):
    sunrise = _w2g7_card(set_pool, "Second Sunrise")
    program = _w2g7_compile(sunrise)
    assert program.supported
    # No target, no pick: the client sends a bare cast.
    assert _w2g7_targeting.derive_cast_spec(sunrise, program) is None
    game, mine, _ = _w2g7_table(
        set_pool,
        hand=["Lightning Bolt", "Stone Rain", "Second Sunrise"],
        mine=["Nevinyrral's Disk", "Grizzly Bears", "Bad Moon", "Forest"],
        theirs=["Llanowar Elves"],
        graveyard=["Grizzly Bears", "Tranquility"],
    )
    disk, _, _, forest = mine
    disk.tapped = False
    # A token dies with the rest and is not a card anyone can return (CR 111.7).
    token = _w2g7_Permanent(
        card=_w2g7_card(set_pool, "Grizzly Bears"), metadata={"is_token": True},
    )
    game._put_permanent_onto_battlefield(1, token, None)
    # A creature B owns and A controls dies into B's graveyard (CR 400.3), and B
    # is the player who returns it.
    borrowed = _w2g7_Permanent(
        card=_w2g7_card(set_pool, "Scathe Zombies"),
        metadata={"owner_player_index": 1},
    )
    game._put_permanent_onto_battlefield(0, borrowed, None)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w2g7_resolve_stack(game)
    assert game.queue_from_hand(
        0, "Stone Rain", target_permanent_ids=[forest.permanent_id],
    ).supported
    _w2g7_resolve_stack(game)
    assert game.activate_permanent_ability(0, "Nevinyrral's Disk").supported
    _w2g7_resolve_stack(game)
    game._settle()
    assert not list(game.all_permanents())

    assert game.queue_from_hand(0, "Second Sunrise").supported
    _w2g7_resolve_stack(game)
    game._settle()
    game.auto_resolve_pending_choices()

    # An artifact, a creature, an enchantment and a land, each put into A's
    # graveyard from the battlefield this turn, come back under A.
    assert _w2g7_names(p.card for p in game.controlled_by(0)) == [
        "Bad Moon", "Forest", "Grizzly Bears", "Nevinyrral's Disk",
    ]
    # B's own Elves and the Zombies B owns come back under B; the token is gone.
    assert _w2g7_names(p.card for p in game.controlled_by(1)) == [
        "Llanowar Elves", "Scathe Zombies",
    ]
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())
    # The Bears that was there before the turn, the sorcery from an earlier
    # turn and the spells that resolved this turn stay where they are.
    assert _w2g7_names(game.players[0].graveyard) == [
        "Grizzly Bears", "Lightning Bolt", "Second Sunrise", "Stone Rain",
        "Tranquility",
    ]
    assert game.players[1].graveyard == []
    assert "B returned Scathe Zombies to the battlefield from the graveyard" in game.log
    # "Nevinyrral's Disk enters tapped." It entered.
    returned_disk = next(
        p for p in game.controlled_by(0) if p.card.name == "Nevinyrral's Disk"
    )
    assert returned_disk.tapped


def test_w2g7_second_sunrise_a_card_that_left_the_graveyard_and_came_back_stays(set_pool):
    # CR 400.7: the Bears Raise Dead returns and its owner then discards is a
    # new object that was put into the graveyard from a hand, not from the
    # battlefield — whatever its earlier self did this turn.
    game, (bears,), _ = _w2g7_table(
        set_pool, hand=["Lightning Bolt", "Raise Dead", "Second Sunrise"],
        mine=["Grizzly Bears"],
    )
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w2g7_resolve_stack(game)
    game._settle()
    slot = [c.name for c in game.players[0].graveyard].index("Grizzly Bears")
    assert game.queue_from_hand(
        0, "Raise Dead",
        target_role_refs=[{"graveyard_seat": 0, "graveyard_index": slot}],
    ).supported
    _w2g7_resolve_stack(game)
    returned = next(c for c in game.players[0].hand if c.name == "Grizzly Bears")
    assert game.take_card_from_hand(game.players[0], returned)
    game._discard_card(game.players[0], returned)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]

    assert game.queue_from_hand(0, "Second Sunrise").supported
    _w2g7_resolve_stack(game)
    game._settle()
    assert not list(game.controlled_by(0))
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]
    assert "Second Sunrise: no cards to return" in game.log

def test_w2g7_second_sunrise_tells_two_copies_of_one_card_apart(set_pool):
    # An old Grizzly Bears in the pile and a second one Bolted this turn are
    # two objects (CR 400.7, ``Game.put_card_into_graveyard``): Raise Dead
    # takes back the one that died, and the one left was not put there from
    # the battlefield this turn. They were one object, and Second Sunrise
    # returned the old Bears.
    game, (bears,), _ = _w2g7_table(
        set_pool, hand=["Lightning Bolt", "Raise Dead", "Second Sunrise"],
        mine=["Grizzly Bears"],
    )
    game.put_card_into_graveyard(0, _w2g7_card(set_pool, "Grizzly Bears"))
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w2g7_resolve_stack(game)
    game._settle()
    pile = game.players[0].graveyard
    assert [c.name for c in pile] == ["Grizzly Bears", "Lightning Bolt", "Grizzly Bears"]
    assert pile[0] is not pile[2]
    assert game.queue_from_hand(
        0, "Raise Dead", target_permanent_index=2, target_player_index=0,
    ).supported
    _w2g7_resolve_stack(game)
    assert game.queue_from_hand(0, "Second Sunrise").supported
    _w2g7_resolve_stack(game)
    game._settle()
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].graveyard] == [
        "Grizzly Bears", "Lightning Bolt", "Raise Dead", "Second Sunrise",
    ]

# ==== end W2G7 ======================================================


# ==== W2G5 ==========================================================
# W2G5's tests go between this line and the "end W2G5" line.
#
# The AI pile. Forge Armor: "As an additional cost to cast this spell,
# sacrifice an artifact. Put X +1/+1 counters on target creature, where X is
# the sacrificed artifact's mana value." A seat that named no victim paid with
# the smallest (a Great Furnace, for no counter); the cast chooser now weighs
# each reading the board offers (`ai_casts._cast_naming_its_sacrifice`).

from engine import Game as _w2g5_Game
from engine import PlayerState as _w2g5_PlayerState
from engine.ai_actions import cast_announcement as _w2g5_cast_announcement
from engine.ai_payment import tap_planned_lands as _w2g5_tap_planned_lands
from engine.ai_policy import choose_cast_action as _w2g5_choose_cast_action
from engine.models import Permanent as _w2g5_Permanent
from tests.helpers import _nosick as _w2g5_nosick
from tests.helpers import resolve_stack as _w2g5_resolve_stack


def _w2g5_table(set_pool, mine, *, hand=(), theirs=()):
    """Seat 0 (A) in its first main phase, mana enforced, its lands untapped."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    card = lambda name: mrd[name] if name in mrd else lea[name]  # noqa: E731
    game = _w2g5_Game(players=[
        _w2g5_PlayerState("A", hand=[card(n) for n in hand], library=[card("Plains")] * 10),
        _w2g5_PlayerState("B", library=[card("Plains")] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w2g5_nosick(_w2g5_Permanent(card=card(name)))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    # Every entry offer answered (Solemn Simulacrum's search): a table with
    # a prompt still owed is one no rehearsal can be run on.
    _w2g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.start_turn(0)
    game._settle()
    game.enforce_mana_costs = True
    return game, placed[0], placed[1]


_W2G5_LANDS = ["Mountain", "Mountain", "Mountain", "Swamp"]


def test_w2g5_forge_armor_is_paid_with_the_artifact_it_reads_largest(set_pool):
    game, (furnace, gold_myr, solemn, *_lands), _ = _w2g5_table(
        set_pool, ["Great Furnace", "Gold Myr", "Solemn Simulacrum", *_W2G5_LANDS],
        hand=["Forge Armor"], theirs=["Hill Giant"],
    )
    action = _w2g5_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Forge Armor"
    assert action.cost_permanent_ids == [solemn.permanent_id]
    _w2g5_tap_planned_lands(game, 0, action)
    assert game.cast_from_hand(0, "Forge Armor", **_w2g5_cast_announcement(action)).supported
    _w2g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "A sacrificed Solemn Simulacrum to cast Forge Armor" in game.log
    assert game.is_on_battlefield(furnace)
    # Gold Myr is a 1/1; the Simulacrum's mana value is 4.
    assert (gold_myr.effective_power, gold_myr.effective_toughness) == (5, 5)


def test_w2g5_forge_armor_never_sacrifices_its_own_target(set_pool):
    game, (_furnace, gold_myr, *_lands), _ = _w2g5_table(
        set_pool, ["Great Furnace", "Gold Myr", *_W2G5_LANDS],
        hand=["Forge Armor"], theirs=["Hill Giant"],
    )
    action = _w2g5_choose_cast_action(game, 0)
    # The Myr is the one creature to put counters on, so it cannot also be
    # what pays; the Furnace alone reads 0, and a cast for no counter is not
    # proposed at all.
    assert action is None or gold_myr.permanent_id not in (action.cost_permanent_ids or ())
    assert action is None

# ==== end W2G5 ======================================================
