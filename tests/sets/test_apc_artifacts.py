"""Apocalypse artifacts (artifact creatures included).

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

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4a_Game, PlayerState as _w1g4a_Player  # noqa: E402
from engine.models import Permanent as _w1g4a_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4a_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4a_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order — one pool per card.
_W1G4A_POOLS = ("APC", "LEA", "ATQ", "7ED", "MIR")


def _w1g4a_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4A_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 artifacts: no pool here prints that name


def _w1g4a_table(set_pool, *, mine=(), theirs=(), hand0=(), hand1=(), lib0=(),
                 lib1=(), interactive=()):
    """A duel with seat 0 in its precombat main phase and costs not enforced."""
    def cards(names):
        return [_w1g4a_card(set_pool, name) for name in names]

    board0 = [_w1g4a_Permanent(card=card) for card in cards(mine)]
    board1 = [_w1g4a_Permanent(card=card) for card in cards(theirs)]
    game = _w1g4a_Game(players=[
        _w1g4a_Player(name="P0", battlefield=board0, hand=cards(hand0),
                      library=cards(lib0)),
        _w1g4a_Player(name="P1", battlefield=board1, hand=cards(hand1),
                      library=cards(lib1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0, board1  # W1G4 artifacts: the table


def _w1g4a_names(cards):
    return [card.name for card in cards]  # W1G4 artifacts: a zone, by name


# -- Dragon Arch -------------------------------------------------------------

#: One colour, two colours, three colours, and two colours on a card that is
#: no creature.
_W1G4A_ARCH_HAND = ["Hill Giant", "Spiritmonger", "Lightning Angel", "Vindicate"]


def test_w1g4_dragon_arch_puts_a_multicolored_creature_card_onto_the_battlefield(set_pool):
    """"{2}, {T}: You may put a multicolored creature card from your hand onto
    the battlefield." CR 105.2b: two or more colours. A one-colour creature is
    not offered and neither is a gold sorcery; the card picked enters under its
    owner's control and the Arch is tapped for it."""
    arch = _w1g4a_card(set_pool, "Dragon Arch")
    assert _w1g4a_compile(arch).supported
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Dragon Arch"], hand0=_W1G4A_ARCH_HAND, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Dragon Arch", ability_index=0).supported
    assert mine[0].tapped
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True)

    (pick,) = game.pending_choices
    assert pick.kind == "put_from_hand_choice"
    assert game.live_put_from_hand_choices(pick) == [1, 2]
    assert not game.confirm_put_from_hand_choice(0, 0), "Hill Giant is one colour"
    assert not game.confirm_put_from_hand_choice(0, 3), "Vindicate is no creature"
    assert game.confirm_put_from_hand_choice(0, 2)
    _w1g4a_resolve_stack(game)
    game._settle()

    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Dragon Arch", "Lightning Angel",
    ]
    assert _w1g4a_names(game.players[0].hand) == ["Hill Giant", "Spiritmonger", "Vindicate"]
    assert "P0 put Lightning Angel onto the battlefield (Dragon Arch)" in game.log


def test_w1g4_dragon_arch_is_an_offer_its_controller_may_decline(set_pool):
    """The ruling: "Putting the card onto the battlefield is optional. When the
    ability resolves, you can choose not to." The cost is spent either way."""
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Dragon Arch"], hand0=_W1G4A_ARCH_HAND, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Dragon Arch", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=False)
    _w1g4a_resolve_stack(game)

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Dragon Arch"]
    assert mine[0].tapped
    assert _w1g4a_names(game.players[0].hand) == _W1G4A_ARCH_HAND
    assert game.pending_choices == []


def test_w1g4_dragon_arch_finds_nothing_in_a_hand_of_one_coloured_creatures(set_pool):
    """With no multicolored creature card in hand there is nothing to pick, so
    accepting the offer puts nothing anywhere — and a tapped Arch cannot be
    activated a second time."""
    game, _, _ = _w1g4a_table(
        set_pool, mine=["Dragon Arch"], hand0=["Hill Giant", "Vindicate"],
        interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Dragon Arch", ability_index=0).supported
    game.resolve_top_of_stack()
    if game.pending_choices:
        assert game.confirm_optional_pay(0, accept=True)
    _w1g4a_resolve_stack(game)

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Dragon Arch"]
    assert _w1g4a_names(game.players[0].hand) == ["Hill Giant", "Vindicate"]
    assert game.pending_choices == []
    assert "P0 has no card Dragon Arch could put onto the battlefield" in game.log
    again = game.queue_permanent_ability(0, "Dragon Arch", ability_index=0)
    assert not again.supported


# -- Legacy Weapon -----------------------------------------------------------


def _w1g4a_weapon_is_back_in_its_library(game, seat=0):
    """The whole of the replacement, asserted off the zones: the card is in its
    owner's library and in no graveyard, and it was shown on the way."""
    assert "Legacy Weapon" in _w1g4a_names(game.players[seat].library)
    for player in game.players:
        assert "Legacy Weapon" not in _w1g4a_names(player.graveyard)
        assert "Legacy Weapon" not in _w1g4a_names(player.exile)
    assert game.reveal_events[-1] == {
        "id": game.reveal_event_seq, "seat": seat, "cards": ["Legacy Weapon"],
    }
    assert (
        f"Legacy Weapon was revealed and shuffled into P{seat}'s library instead "
        "of going to a graveyard"
    ) in game.log  # W1G4 artifacts: the replacement, start to finish


def test_w1g4_legacy_weapon_destroyed_is_shuffled_into_its_owners_library(set_pool):
    """"If Legacy Weapon would be put into a graveyard from anywhere, reveal
    Legacy Weapon and shuffle it into its owner's library instead." From the
    battlefield: destroyed, and it never reaches the graveyard."""
    assert _w1g4a_compile(_w1g4a_card(set_pool, "Legacy Weapon")).supported
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Legacy Weapon"], hand1=["Shatter"], lib0=["Forest"] * 4,
    )
    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[mine[0].permanent_id]
    ).supported
    _w1g4a_resolve_stack(game)
    game._settle()

    assert game.controlled_by(0) == []
    assert len(game.players[0].library) == 5
    _w1g4a_weapon_is_back_in_its_library(game)


def test_w1g4_legacy_weapon_discarded_is_shuffled_into_its_owners_library(set_pool):
    """From a hand: discarded by an opponent's spell. The other card discarded
    beside it goes to the graveyard as usual."""
    game, _, _ = _w1g4a_table(
        set_pool, hand0=["Legacy Weapon", "Forest"], hand1=["Mind Rot"],
        lib0=["Island"] * 3,
    )
    assert game.cast_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.auto_resolve_pending_choices()
    _w1g4a_resolve_stack(game)

    assert game.players[0].hand == []
    assert _w1g4a_names(game.players[0].graveyard) == ["Forest"]
    assert len(game.players[0].library) == 4
    _w1g4a_weapon_is_back_in_its_library(game)


def test_w1g4_legacy_weapon_milled_is_shuffled_back_into_its_library(set_pool):
    """From a library: milled. The card beside it is put into the graveyard and
    the Weapon is somewhere in what is left."""
    game, _, _ = _w1g4a_table(
        set_pool, theirs=["Millstone"], lib0=["Legacy Weapon", "Forest", "Island"],
    )
    assert game.activate_permanent_ability(
        1, "Millstone", ability_index=0, target_player_index=0
    ).supported
    _w1g4a_resolve_stack(game)

    assert _w1g4a_names(game.players[0].graveyard) == ["Forest"]
    assert sorted(_w1g4a_names(game.players[0].library)) == ["Island", "Legacy Weapon"]
    _w1g4a_weapon_is_back_in_its_library(game)


def test_w1g4_legacy_weapon_countered_is_shuffled_into_its_owners_library(set_pool):
    """From the stack: countered. The spell's card is the card that would have
    been put into the graveyard, and the log no longer says it was."""
    game, _, _ = _w1g4a_table(
        set_pool, hand0=["Legacy Weapon"], hand1=["Counterspell"], lib0=["Forest"] * 3,
    )
    assert game.queue_from_hand(0, "Legacy Weapon").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g4a_resolve_stack(game)

    assert game.controlled_by(0) == [] and game.players[0].hand == []
    assert _w1g4a_names(game.players[1].graveyard) == ["Counterspell"]
    assert len(game.players[0].library) == 4
    _w1g4a_weapon_is_back_in_its_library(game)
    assert not any("Legacy Weapon" in line and "moved to graveyard" in line for line in game.log)


def test_w1g4_legacy_weapon_sacrificed_is_shuffled_into_its_owners_library(set_pool):
    """Paid as a cost: sacrificed to an Atog, which still gets its +2/+2."""
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Legacy Weapon", "Atog"], lib0=["Forest"] * 3,
    )
    weapon, atog = mine
    assert game.activate_permanent_ability(
        0, "Atog", ability_index=0, cost_permanent_ids=[weapon.permanent_id]
    ).supported
    _w1g4a_resolve_stack(game)

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Atog"]
    assert (atog.effective_power, atog.effective_toughness) == (3, 4)
    _w1g4a_weapon_is_back_in_its_library(game)


def test_w1g4_a_stolen_legacy_weapon_goes_to_its_owners_library(set_pool):
    """"Its **owner's** library" (CR 400.3): destroyed under an opponent's
    control, it is shuffled into the library it came from."""
    from engine.control import change_control

    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Legacy Weapon"], hand1=["Shatter"],
        lib0=["Forest"] * 2, lib1=["Island"] * 2,
    )
    weapon = mine[0]
    change_control(weapon, 1, source="test")
    game._sync_control()
    assert game.controller_index_of(weapon) == 1

    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[weapon.permanent_id]
    ).supported
    _w1g4a_resolve_stack(game)
    game._settle()

    assert _w1g4a_names(game.players[1].library) == ["Island", "Island"]
    assert len(game.players[0].library) == 3
    _w1g4a_weapon_is_back_in_its_library(game, seat=0)


def test_w1g4_a_copy_of_legacy_weapon_shuffles_its_own_card_away(set_pool):
    """The sentence is the object's as it last existed (CR 613, CR 707.2): a
    Copy Artifact that *is* a Legacy Weapon has it, so when the legend rule
    puts one of the two into a graveyard the card that is shuffled into the
    library is the Copy Artifact — the printed Weapon stays where it was."""
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Legacy Weapon"], hand0=["Copy Artifact"], lib0=["Forest"] * 3,
    )
    assert game.cast_from_hand(
        0, "Copy Artifact", target_permanent_ids=[mine[0].permanent_id]
    ).supported
    game.auto_resolve_pending_choices()
    _w1g4a_resolve_stack(game)
    game._settle()

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Legacy Weapon"]
    assert sorted(_w1g4a_names(game.players[0].library)) == [
        "Copy Artifact", "Forest", "Forest", "Forest",
    ]
    assert game.players[0].graveyard == []
    assert (
        "Copy Artifact was revealed and shuffled into P0's library instead of "
        "going to a graveyard"
    ) in game.log


def test_w1g4_another_cards_exile_replacement_takes_the_weapon_first(set_pool):
    """Two replacements on one event (CR 616.1; the rule's own example is this
    pair). A seat that is not asked takes the engine's default order, in which
    Forbidden Crypt's exile goes first — and an exiled card was never put into
    a graveyard, so the Weapon's own sentence has nothing left to replace."""
    game, mine, _ = _w1g4a_table(
        set_pool, mine=["Legacy Weapon", "Forbidden Crypt"], hand1=["Shatter"],
        lib0=["Forest"] * 3,
    )
    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[mine[0].permanent_id]
    ).supported
    _w1g4a_resolve_stack(game)
    game._settle()

    assert _w1g4a_names(game.players[0].exile) == ["Legacy Weapon"]
    assert _w1g4a_names(game.players[0].library) == ["Forest"] * 3
    assert game.players[0].graveyard == []


def test_w1g4_legacy_weapon_exiles_the_permanent_it_is_aimed_at(set_pool):
    """"{W}{U}{B}{R}{G}: Exile target permanent." Any permanent — a land as
    readily as a creature — and the one named is the one exiled, to its owner's
    exile; the bystander beside it stays."""
    game, mine, theirs = _w1g4a_table(
        set_pool, mine=["Legacy Weapon"], theirs=["Serra Angel", "Island"],
    )
    island = theirs[1]
    result = game.activate_permanent_ability(
        0, "Legacy Weapon", ability_index=0, target_permanent_ids=[island.permanent_id],
    )
    assert result.supported, result.details
    _w1g4a_resolve_stack(game)

    assert not game.is_on_battlefield(island)
    assert game.is_on_battlefield(theirs[0]) and game.is_on_battlefield(mine[0])
    assert _w1g4a_names(game.players[1].exile) == ["Island"]
    assert game.players[1].graveyard == []


def test_w1g4_legacy_weapons_exile_costs_one_mana_of_each_colour(set_pool):
    """The cost enforced: five lands of five colours pay it, and with the
    Forest already tapped the ability is refused and nothing is exiled."""
    game, mine, theirs = _w1g4a_table(
        set_pool,
        mine=["Legacy Weapon", "Plains", "Island", "Swamp", "Mountain", "Forest"],
        theirs=["Serra Angel"],
    )
    game.enforce_mana_costs = True
    angel = theirs[0]

    def aim():
        return game.activate_permanent_ability(
            0, "Legacy Weapon", ability_index=0,
            target_permanent_ids=[angel.permanent_id],
        )  # W1G4 artifacts: the Weapon aimed at the Angel

    for land, color in zip(mine[1:5], "WUBR"):
        assert game.tap_land_for_mana(
            0, land.card.name, color, permanent_id=land.permanent_id
        )
    short = aim()
    assert not short.supported, "four colours are not five"
    assert game.is_on_battlefield(angel)
    assert sum(game.players[0].mana_pool.values()) == 4, "nothing was spent"

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[5].permanent_id)
    paid = aim()
    assert paid.supported, paid.details
    _w1g4a_resolve_stack(game)
    assert not game.is_on_battlefield(angel)
    assert sum(game.players[0].mana_pool.values()) == 0
    assert _w1g4a_names(game.players[1].exile) == ["Serra Angel"]

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
