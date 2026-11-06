"""Scourge instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Storm (CR 702.40, ``engine/storm.py``): a "when you cast this spell" trigger
# that copies the spell once for each other spell cast before it this turn —
# every player's, from any zone, countered or not, and none cast after it.
# Every storm instant is driven at storm counts 0, 1 and 3 where the count is
# what the card's behaviour turns on, as an interactive seat (each copy's new
# target answered, and declined) and as a default one. Then the drive list:
# Scourge instants that compiled supported on arrival and had never been run.

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game
from engine import PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_card(set_pool, name):
    """A card by name, from Scourge first and Alpha for the fillers."""
    scg = set_pool("SCG")
    return scg[name] if name in scg else set_pool("LEA")[name]


def _w1g1_table(set_pool, hand=(), *, opponent_hand=(), mine=(), theirs=(),
                graveyard=(), library=None, interactive=()):
    """Seat 0 (A) to act in its first main phase, mana off unless a test turns
    it on; each named permanent untapped and able to act."""
    card = lambda name: _w1g1_card(set_pool, name)  # noqa: E731
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
            graveyard=[card(n) for n in graveyard],
        ),
        _w1g1_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Forest")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g1_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g1_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g1_cast_fillers(game, seat, count):
    """*count* Dark Rituals from *seat*'s hand, each resolved: spells cast
    this turn before whatever comes next."""
    for _ in range(count):
        result = game.queue_from_hand(seat, "Dark Ritual")
        assert result.supported, result.details
        _w1g1_resolve_stack(game)


def _w1g1_copies(game):
    return [item for item in game.stack if item.is_copy]


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_scattershot_deals_1_for_itself_and_each_spell_before_it(set_pool, before):
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Scattershot"], theirs=["Craw Wurm"],
    )
    _w1g1_cast_fillers(game, 0, before)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    # The storm trigger is on the stack above its spell (CR 603.3).
    assert [item.ability_effect_kind for item in game.stack] == [None, "triggered_copy"]
    _w1g1_resolve_stack(game)
    assert wurm.damage_marked == before + 1
    assert sum("Scattershot copied Scattershot" in line for line in game.log) == before


def test_w1g1_a_spell_cast_in_response_to_storm_is_not_counted(set_pool):
    """2019-06-14 (Wing Shards): "Spells cast after the spell with storm was
    cast but before the storm ability resolves aren't counted." The opponent's
    spell cast *before* Scattershot counts — storm counts every player's."""
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Dark Ritual", "Scattershot"], theirs=["Craw Wurm"],
        opponent_hand=["Dark Ritual", "Giant Growth"],
    )
    _w1g1_cast_fillers(game, 0, 1)
    _w1g1_cast_fillers(game, 1, 1)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    # In response to the trigger: Giant Growth on the Wurm, resolved first.
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[wurm.permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    _w1g1_resolve_stack(game)
    # Two before it (one each), none after: three pings, not four.
    assert wurm.damage_marked == 3
    assert sum("Scattershot copied Scattershot" in line for line in game.log) == 2


def test_w1g1_scattershot_copies_each_take_their_own_new_target(set_pool):
    """2022-12-08: "You may choose new targets for any of the copies. You can
    make different choices for each copy." One prompt per copy, answered one
    way each, and one declined."""
    game, _, bears = _w1g1_table(
        set_pool, ["Dark Ritual"] * 3 + ["Scattershot"],
        theirs=["Grizzly Bears"] * 3, interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, 3)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[bears[0].permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    assert len(_w1g1_copies(game)) == 3
    owed = [choice for choice in game.pending_choices if choice.kind == "copy_spell_target"]
    assert len(owed) == 3
    assert {t["permanent_id"] for t in owed[0].data["targets"]} == {
        bear.permanent_id for bear in bears
    }
    assert game.confirm_copy_spell_target(0, permanent_id=bears[1].permanent_id)
    assert game.confirm_copy_spell_target(0, permanent_id=bears[2].permanent_id)
    # The third keeps the original's target: the offer declined.
    assert game.confirm_copy_spell_target(0, permanent_id=bears[0].permanent_id)
    _w1g1_resolve_stack(game)
    assert [bear.damage_marked for bear in bears] == [2, 1, 1]


def test_w1g1_storm_copies_resolve_after_the_original_is_countered(set_pool):
    """2019-06-14: "The storm ability and the copies it creates all resolve
    before the spell with storm. They resolve even if the spell with storm is
    countered." Countered while its trigger waits: the copies are made from
    the spell as it last existed (CR 608.2h) and still deal their damage."""
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Scattershot"],
        theirs=["Craw Wurm"], opponent_hand=["Counterspell"],
    )
    _w1g1_cast_fillers(game, 0, 2)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    # Counterspell at the Scattershot (engine stack index 0, under its trigger).
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g1_resolve_stack(game)
    assert "Scattershot" in [card.name for card in game.players[0].graveyard]
    assert wurm.damage_marked == 2


def test_w1g1_stifle_counters_the_storm_trigger_and_no_copy_is_made(set_pool):
    """2022-12-08: "The triggered ability that creates the copies can itself be
    countered … If it is countered, no copies will be put onto the stack." The
    storm trigger is a triggered ability on the stack (CR 702.40a), so Stifle's
    picker offers it and Stifle counters it; the spell itself still resolves."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Scattershot"],
        theirs=["Craw Wurm"], opponent_hand=["Stifle"],
    )
    _w1g1_cast_fillers(game, 0, 2)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    stifle = _w1g1_card(set_pool, "Stifle")
    offered = game._enumerate_targets(
        1, stifle, derive_cast_spec(stifle, compile_card_oracle(stifle)), for_cast=True,
    )
    assert [entry["name"] for entry in offered] == ["Scattershot's triggered ability"]
    assert game.queue_from_hand(1, "Stifle", target_stack_index=1).supported
    _w1g1_resolve_stack(game)
    assert not any("Scattershot copied" in line for line in game.log)
    assert wurm.damage_marked == 1


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_astral_steel_copies_pump_the_same_creature_by_default(set_pool, before):
    game, (bears,), _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Astral Steel"], mine=["Grizzly Bears"],
    )
    _w1g1_cast_fillers(game, 0, before)
    assert game.queue_from_hand(
        0, "Astral Steel", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    copies = before + 1
    assert (bears.effective_power, bears.effective_toughness) == (
        2 + copies, 2 + 2 * copies,
    )


def test_w1g1_astral_steel_copy_moved_to_another_creature(set_pool):
    game, (bears, elves), _ = _w1g1_table(
        set_pool, ["Dark Ritual", "Astral Steel"],
        mine=["Grizzly Bears", "Llanowar Elves"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(
        0, "Astral Steel", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    assert game.confirm_copy_spell_target(0, permanent_id=elves.permanent_id)
    _w1g1_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)
    assert (elves.effective_power, elves.effective_toughness) == (2, 3)


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_brain_freeze_mills_three_per_copy(set_pool, before):
    game, _, _ = _w1g1_table(set_pool, ["Dark Ritual"] * before + ["Brain Freeze"])
    _w1g1_cast_fillers(game, 0, before)
    library = len(game.players[1].library)
    assert game.queue_from_hand(0, "Brain Freeze", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert library - len(game.players[1].library) == 3 * (before + 1)
    assert len(game.players[1].graveyard) == 3 * (before + 1)


def test_w1g1_brain_freeze_copy_re_aimed_at_its_caster(set_pool):
    """A player target re-aimed: one copy at the opponent, one at the caster."""
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual", "Brain Freeze"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(0, "Brain Freeze", target_player_index=1).supported
    assert game.resolve_top_of_stack()
    assert game.confirm_copy_spell_target(0, target_seat=0)
    _w1g1_resolve_stack(game)
    assert len(game.players[0].graveyard) == 3 + 2  # milled + Ritual + Freeze
    assert len(game.players[1].graveyard) == 3


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_hunting_pack_makes_a_beast_per_copy(set_pool, before):
    game, _, _ = _w1g1_table(set_pool, ["Dark Ritual"] * before + ["Hunting Pack"])
    _w1g1_cast_fillers(game, 0, before)
    assert game.queue_from_hand(0, "Hunting Pack").supported
    _w1g1_resolve_stack(game)
    beasts = [
        permanent for permanent in game.controlled_by(game.players[0])
        if permanent.card.name == "Beast Token"
    ]
    assert len(beasts) == before + 1
    assert all(
        (beast.effective_power, beast.effective_toughness) == (4, 4)
        for beast in beasts
    )


def test_w1g1_hindering_touch_copies_each_ask_for_two(set_pool):
    """Every copy is its own "counter … unless its controller pays {2}": the
    Giant Growth's controller is asked once per copy, pays the first and
    declines the second, and the Growth is countered."""
    game, _, (bears, *_lands) = _w1g1_table(
        set_pool, ["Dark Ritual", "Hindering Touch"],
        theirs=["Grizzly Bears", "Forest", "Forest", "Forest", "Forest"],
        opponent_hand=["Giant Growth"], interactive=[1],
    )
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Hindering Touch", target_stack_index=0).supported
    assert game.resolve_top_of_stack()
    # Dark Ritual and Giant Growth were cast before it: two copies.
    assert len(_w1g1_copies(game)) == 2
    asked = []
    for answer in (True, False):
        game.resolve_top_of_stack(pause_for_choices=True)
        offer = game.pending_choices[0]
        assert offer.kind == "mana_payment" and offer.player_index == 1
        asked.append(offer.data.get("amount"))
        assert game.confirm_mana_payment(1, pay=answer)
    _w1g1_resolve_stack(game)
    assert asked == [2, 2]
    assert sum(permanent.tapped for permanent in game.controlled_by(game.players[1])) == 2
    assert "Giant Growth" in [card.name for card in game.players[1].graveyard]
    assert bears.effective_power == 2


def test_w1g1_hindering_touch_copy_may_be_re_aimed_at_another_spell(set_pool):
    """A copy whose target is a spell is offered the other spells it could
    have targeted (``retarget_choice`` over CR 115.7's candidates) — never
    itself (CR 115.5), and "keep" beside them."""
    game, _, bears = _w1g1_table(
        set_pool, ["Dark Ritual", "Hindering Touch"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
        opponent_hand=["Giant Growth", "Giant Growth"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, 1)
    for bear in bears:
        assert game.queue_from_hand(
            1, "Giant Growth", target_permanent_ids=[bear.permanent_id]
        ).supported
    first, second = game.stack[0], game.stack[1]
    assert game.queue_from_hand(0, "Hindering Touch", target_stack_index=1).supported
    assert game.resolve_top_of_stack()
    owed = game.pending_choice_of("retarget_choice")
    assert owed is not None and owed.player_index == 0
    names = [option["name"] for option in owed.data["options"]]
    assert names == ["Keep the original's target", "Giant Growth", "Hindering Touch"]
    assert owed.data["options"][1]["_stack_item"] is first
    assert game.confirm_retarget_choice(0, 1)
    # Three spells before it, three copies, each asked in turn: the first is
    # answered, the second is being asked.
    copy = _w1g1_copies(game)[0]
    assert copy.target_stack_item is first
    original = next(item for item in game.stack if item.card.name == "Hindering Touch" and not item.is_copy)
    assert original.target_stack_item is second


@_w1g1_pytest.mark.parametrize("before", [1, 3])
def test_w1g1_reaping_the_graves_copies_each_return_another_card(set_pool, before):
    """Interactive: each copy is re-aimed at a different creature card in the
    graveyard (a graveyard target goes through ``retarget_choice``), so every
    copy returns one."""
    pile = ["Grizzly Bears", "Craw Wurm", "Llanowar Elves", "Hill Giant", "Forest"]
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Reaping the Graves"],
        graveyard=pile, interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, before)
    assert game.queue_from_hand(0, "Reaping the Graves", target_permanent_index=0).supported
    assert game.resolve_top_of_stack()
    for _ in range(before):
        owed = game.pending_choice_of("retarget_choice")
        assert owed is not None
        names = [option["name"] for option in owed.data["options"]]
        assert names[0] == "Keep the original's target"
        assert not any("Forest" in name for name in names)
        # The first card not yet named by the original or an earlier copy.
        taken = {"Grizzly Bears"} | {
            item.target_graveyard_card.card.name
            for item in _w1g1_copies(game)[:-1]
        }
        pick = next(
            position for position, name in enumerate(names)
            if position and name.split(" in ")[0] not in taken
        )
        assert game.confirm_retarget_choice(0, pick)
    _w1g1_resolve_stack(game)
    returned = {card.name for card in game.players[0].hand}
    assert len(returned) == before + 1
    assert "Grizzly Bears" in returned and "Forest" not in returned


def test_w1g1_reaping_the_graves_copies_keep_the_target_for_a_default_seat(set_pool):
    """A seat nobody asks declines CR 707.10c's offer: every copy names the
    original's card, the first to resolve returns it and the rest find their
    target gone (CR 608.2b). The AI's aim is a policy question, left as is."""
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual", "Reaping the Graves"],
        graveyard=["Grizzly Bears", "Craw Wurm"],
    )
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(0, "Reaping the Graves", target_permanent_index=0).supported
    _w1g1_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert any("every target is illegal" in line for line in game.log)


def test_w1g1_a_copys_graveyard_offer_taken_by_default_keeps_the_target(set_pool):
    """An interactive seat's offer answered by the registry's default (a
    drain, an abandoned seat) is declined, as ``copy_spell_target``'s is —
    not re-aimed by Deflection's "aim it where it helps" policy."""
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual", "Reaping the Graves"],
        graveyard=["Grizzly Bears", "Craw Wurm"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(0, "Reaping the Graves", target_permanent_index=0).supported
    assert game.resolve_top_of_stack()
    owed = game.pending_choice_of("retarget_choice")
    assert owed is not None
    game.take_choice_default(owed)
    (copy,) = _w1g1_copies(game)
    assert copy.target_graveyard_card.card.name == "Grizzly Bears"


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_sprouting_vines_searches_once_per_copy(set_pool, before):
    library = ["Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears"] * 2
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Sprouting Vines"], library=library,
    )
    _w1g1_cast_fillers(game, 0, before)
    hand_before = len(game.players[0].hand)
    assert game.queue_from_hand(0, "Sprouting Vines").supported
    _w1g1_resolve_stack(game)
    # A headless search is queued and answered by its default.
    game.auto_resolve_pending_choices()
    found = game.players[0].hand[hand_before - 1:]
    assert len(found) == before + 1
    assert all("Basic Land" in card.type_line for card in found)


def test_w1g1_wing_shards_copies_each_make_the_player_sacrifice_again(set_pool):
    """The defending seat casts it in the declare-blockers step of an attack
    by three: with one spell before it, the attacker sacrifices two of them."""
    game, _, attackers = _w1g1_table(
        set_pool, ["Dark Ritual", "Wing Shards"],
        theirs=["Grizzly Bears", "Hill Giant", "Llanowar Elves"],
    )
    _w1g1_declare_attack(game, 1)
    _w1g1_cast_fillers(game, 0, 1)
    assert game.queue_from_hand(0, "Wing Shards", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    left = [permanent.card.name for permanent in game.controlled_by(game.players[1])]
    assert len(left) == 1
    assert len(game.players[1].graveyard) == 2


# -- The drive list: Scourge instants supported on arrival ------------------


def test_w1g1_metamorphose_puts_a_permanent_on_top_and_offers_the_hand(set_pool):
    """The permanent goes on top of its owner's library; that opponent may put
    an artifact, creature, enchantment or land card from hand onto the
    battlefield — accepted here by an interactive opponent."""
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Metamorphose"], theirs=["Craw Wurm"],
        opponent_hand=["Grizzly Bears", "Giant Growth"], interactive=[1],
    )
    assert game.queue_from_hand(
        0, "Metamorphose", target_permanent_ids=[wurm.permanent_id]
    ).supported
    game.resolve_top_of_stack()
    assert game.players[1].library[0].name == "Craw Wurm"
    offer = game.pending_choices[0]
    assert offer.kind == "optional_pay" and offer.player_index == 1
    assert game.confirm_optional_pay(1, accept=True)
    for _ in range(3):
        if not game.pending_choices:
            break
        choice = game.pending_choices[0]
        assert choice.player_index == 1
        game.take_choice_default(choice)
    _w1g1_resolve_stack(game)
    names = [permanent.card.name for permanent in game.controlled_by(game.players[1])]
    assert names == ["Grizzly Bears"]
    assert [card.name for card in game.players[1].hand] == ["Giant Growth"]


def test_w1g1_recuperate_either_mode(set_pool):
    from tests.helpers import _damage_dealt

    game, (bears,), _ = _w1g1_table(
        set_pool, ["Recuperate", "Recuperate"], mine=["Grizzly Bears"],
    )
    game.players[0].life = 10
    assert game.queue_from_hand(0, "Recuperate", mode_index=0).supported
    _w1g1_resolve_stack(game)
    assert game.players[0].life == 16
    assert game.queue_from_hand(
        0, "Recuperate", mode_index=1, target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    assert _damage_dealt(game, bears, 5) == 0
    assert _damage_dealt(game, bears, 3) == 2


def test_w1g1_carbonize_exiles_the_creature_it_kills(set_pool):
    game, _, (bears,) = _w1g1_table(
        set_pool, ["Carbonize", "Carbonize"], theirs=["Grizzly Bears"],
    )
    assert game.queue_from_hand(
        0, "Carbonize", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert [card.name for card in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == []
    assert game.queue_from_hand(0, "Carbonize", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 17


def test_w1g1_enrage_adds_x_power(set_pool):
    game, (bears,), _ = _w1g1_table(set_pool, ["Enrage"], mine=["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Enrage", x_value=3, target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (5, 2)


def test_w1g1_rain_of_blades_pings_each_attacker_only(set_pool):
    game, (blocker,), attackers = _w1g1_table(
        set_pool, ["Rain of Blades"], mine=["Grizzly Bears"],
        theirs=["Grizzly Bears", "Craw Wurm"],
    )
    _w1g1_declare_attack(game, 1)
    assert game.queue_from_hand(0, "Rain of Blades").supported
    _w1g1_resolve_stack(game)
    assert [attacker.damage_marked for attacker in attackers] == [1, 1]
    assert blocker.damage_marked == 0


def test_w1g1_chill_haunting_pays_with_the_named_graveyard_cards(set_pool):
    """The cast route's ``cost_graveyard_indices``: X = 2 names two creature
    cards out of the caster's graveyard, and the target gets -2/-2."""
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Chill Haunting"], theirs=["Craw Wurm"],
        graveyard=["Grizzly Bears", "Forest", "Llanowar Elves", "Hill Giant"],
    )
    result = game.queue_from_hand(
        0, "Chill Haunting", x_value=2, target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=[3, 0],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [card.name for card in game.players[0].exile] == ["Hill Giant", "Grizzly Bears"]
    assert (wurm.effective_power, wurm.effective_toughness) == (4, 2)
    # A land is not a creature card (CR 601.2h): the cost refuses it.
    game, _, (wurm,) = _w1g1_table(
        set_pool, ["Chill Haunting"], theirs=["Craw Wurm"],
        graveyard=["Grizzly Bears", "Forest"],
    )
    refused = game.queue_from_hand(
        0, "Chill Haunting", x_value=1, target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=[1],
    )
    assert not refused.supported and "CR 601.2h" in refused.details


def test_w1g1_chill_haunting_cast_through_the_web_route(set_pool):
    """The wire half: the cast action carries the graveyard slots and the
    creature target together, and the engine pays with exactly those."""
    from tests.helpers import _resolve_top_stack, client, seat_plays_first
    from web.app import store

    created = client.post("/api/sessions", json={"mode": "human_vs_human"})
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    seat_plays_first(sid)
    game = store.get(sid).game
    game.enforce_mana_costs = False
    scg, lea = set_pool("SCG"), set_pool("LEA")
    game.players[0].hand.append(scg["Chill Haunting"])
    game.players[0].graveyard[:] = [lea["Grizzly Bears"], lea["Forest"], lea["Hill Giant"]]
    wurm = _w1g1_Permanent(card=lea["Craw Wurm"])
    game._put_permanent_onto_battlefield(1, wurm, None)
    if game.current_phase != "precombat_main":
        game._set_phase_and_step("precombat_main", "main")
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Chill Haunting",
        "x_value": 2, "target_permanent_ids": [wurm.permanent_id],
        "cost_graveyard_indices": [2, 0],
    })
    assert response.status_code == 200, response.text
    for _ in range(4):
        if not game.stack:
            break
        _resolve_top_stack(sid, 0)
    assert [card.name for card in game.players[0].exile] == ["Hill Giant", "Grizzly Bears"]
    assert wurm.effective_toughness == 2

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Decree of Savagery's cycle trigger (a printed number of +1/+1 counters on one
# target, refused until this round), and the cycling instants on W1G2's drive
# list (Spark Spray, Wipe Clean).
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, *, interactive=False):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g2_decree_of_savagery_counters_each_creature_you_control(set_pool):
    lea = set_pool("LEA")
    game, _alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Decree of Savagery").supported
    _w1g2_drain(game)
    assert _w1g2_pt(mine) == (6, 6) and _w1g2_pt(theirs) == (2, 2)


def test_w1g2_decree_of_savagery_cycled_puts_four_counters_on_the_target(set_pool):
    """"When you cycle this card, you may put four +1/+1 counters on target
    creature." Compiled to nothing until this round (the count was refused as
    "variable"); the target is chosen as the trigger goes on the stack, by a
    person here, and it may be any creature."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Savagery"]], interactive=True,
    )
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Llanowar Elves"])

    assert game.activate_from_hand(0, "Decree of Savagery").supported
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None
    offered = {t.get("permanent_id") for t in prompt.data["targets"]}
    assert {mine.permanent_id, theirs.permanent_id} <= offered
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=theirs.permanent_id,
    )
    game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, [c.kind for c in game.pending_choices]
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g2_drain(game)
    assert _w1g2_pt(theirs) == (5, 5)
    assert _w1g2_pt(mine) == (2, 2)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_savagery_cycles_with_no_creature_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The trigger is removed (CR 603.3d); the draw
    still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Savagery"]])
    assert game.activate_from_hand(0, "Decree of Savagery").supported
    assert len(game.stack) == 1
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert any("no legal target" in line for line in game.log)


def test_w1g2_spark_spray_deals_one_to_any_target(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Spark Spray"]] * 2)
    elves = _w1g2_put(game, 1, lea["Llanowar Elves"])
    assert game.cast_from_hand(0, "Spark Spray", target_permanent_ids=[elves.permanent_id]).supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(elves)
    assert game.cast_from_hand(0, "Spark Spray", target_player_index=1).supported
    _w1g2_drain(game)
    assert bob.life == 19


def test_w1g2_wipe_clean_exiles_target_enchantment(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [set_pool("SCG")["Wipe Clean"]])
    moon = _w1g2_put(game, 1, lea["Bad Moon"])
    assert game.cast_from_hand(0, "Wipe Clean", target_permanent_ids=[moon.permanent_id]).supported
    _w1g2_drain(game)
    assert not game.is_on_battlefield(moon)
    assert [c.name for c in bob.exile] == ["Bad Moon"] and bob.graveyard == []


def test_w1g2_the_cycling_instants_cycle(set_pool):
    for name in ("Spark Spray", "Wipe Clean"):
        game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")[name]])
        assert game.activate_from_hand(0, name).supported, name
        _w1g2_drain(game)
        assert [c.name for c in alice.hand] == ["Plains"], name

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# "The greatest mana value among permanents you control" as an amount
# (Accelerated Mutation, Reward the Faithful) and as a comparison's bound
# (Dispersal Shield): one aggregate (`ast.GreatestManaValueAmong`,
# `evaluate_count`'s ``greatest_mana_value``), counted at resolution. Reward
# the Faithful is also "any number of target players each …", the Wheel and
# Deal seat loop with the caster admitted.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from engine.targeting import spec_roles as _w1g4_spec_roles
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_table(set_pool, hand, *, players=2):
    lea = set_pool("LEA")
    seats = [
        _W1G4PlayerState(
            name=f"P{seat + 1}", library=[lea["Island"]] * 8,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(players)
    ]
    game = _W1G4Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    _w1g4_resolve_stack(game)
    return permanent


def test_w1g4_accelerated_mutation_pumps_by_the_greatest_mana_value_you_control(set_pool):
    """Shivan Dragon (6) is the greatest among the caster's permanents; the
    opponent's Lord of the Pit (7) is not one "you control"."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Accelerated Mutation"]])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    _w1g4_put(game, 0, lea["Shivan Dragon"])
    _w1g4_put(game, 1, lea["Lord of the Pit"])
    assert game.cast_from_hand(
        0, "Accelerated Mutation", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (8, 8), game.log


def test_w1g4_the_greatest_mana_value_is_counted_as_the_spell_resolves(set_pool):
    """CR 608.2: the count is taken at resolution, so a Shivan Dragon that
    leaves in response leaves the Bears' own 2."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Accelerated Mutation"]])
    bears = _w1g4_put(game, 0, lea["Grizzly Bears"])
    dragon = _w1g4_put(game, 0, lea["Shivan Dragon"])
    assert game.queue_from_hand(
        0, "Accelerated Mutation", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert len(game.stack) == 1
    game.remove_from_battlefield(dragon)
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4), game.log


def _w1g4_shield(set_pool, spell, *, x_value=None, mine=("Grizzly Bears",)):
    """Seat 1 casts *spell* (at seat 0 where it targets a player); seat 0
    answers with Dispersal Shield over a board of *mine*, with a Shivan Dragon
    on seat 1's side that is not "you control"."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Dispersal Shield"]])
    game.players[1].hand.append(lea[spell])
    for name in mine:
        _w1g4_put(game, 0, lea[name])
    _w1g4_put(game, 1, lea["Shivan Dragon"])
    announced = {} if "Creature" in lea[spell].type_line else {"target_player_index": 0}
    if x_value is not None:
        announced["x_value"] = x_value
    assert game.queue_from_hand(1, spell, **announced).supported
    assert game.queue_from_hand(0, "Dispersal Shield", target_stack_index=0).supported
    _w1g4_resolve_stack(game)
    return game


@_w1g4_pytest.mark.parametrize("spell, x_value, mine, countered", [
    ("Lightning Bolt", None, ("Grizzly Bears",), True),     # 1 <= 2
    ("Hill Giant", None, ("Grizzly Bears",), False),        # 4 > 2
    ("Hill Giant", None, ("Grizzly Bears", "Hill Giant"), True),  # 4 <= 4
    # CR 202.3e: on the stack an X in the cost is the announced value.
    ("Fireball", 1, ("Grizzly Bears",), True),              # {X}{R}, X=1: 2
    ("Fireball", 2, ("Grizzly Bears",), False),             # X=2: 3
    # Nothing controlled is a greatest of 0: even a one-drop is greater.
    ("Lightning Bolt", None, (), False),
])
def test_w1g4_dispersal_shield_counters_by_the_two_mana_values(
    set_pool, spell, x_value, mine, countered,
):
    """"Counter target spell if its mana value is less than or equal to the
    greatest mana value among permanents you control." A condition on the
    effect (CR 608.2c), not a targeting restriction: every row is a legal
    announcement, and a row not countered resolves as if the Shield had not
    been cast."""
    game = _w1g4_shield(set_pool, spell, x_value=x_value, mine=mine)
    their_graveyard = [card.name for card in game.players[1].graveyard]
    if countered:
        assert their_graveyard == [spell], game.log
        assert game.players[0].life == 20
        assert any("countered by Dispersal Shield" in line for line in game.log)
    elif "Creature" in set_pool("LEA")[spell].type_line:
        assert spell in [p.card.name for p in game.controlled_by(1)], game.log
    else:
        assert game.players[0].life == 20 - (x_value or 3), game.log


def test_w1g4_dispersal_shield_offers_every_spell(set_pool):
    """The clause does not narrow the target (CR 601.2c reads "target spell"):
    a spell the Shield will not counter is still one the picker offers."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Dispersal Shield"]])
    game.players[1].hand.append(lea["Craw Wurm"])
    assert game.queue_from_hand(1, "Craw Wurm").supported
    spec = game.cast_target_spec(0, set_pool("SCG")["Dispersal Shield"])
    assert spec["requires_target"]
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Craw Wurm"]


@_w1g4_pytest.mark.parametrize("named", [[0], [1], [0, 1], [1, 2], [0, 1, 2], []])
def test_w1g4_reward_the_faithful_heals_exactly_the_named_players(set_pool, named):
    """"Any number of target players each gain life equal to the greatest mana
    value among permanents you control." The caster may be named (CR 115.1a),
    zero players is a legal announcement, and **every** named player gains the
    *caster's* greatest — the third seat's Shivan Dragon (6) is not a
    permanent "you" control, whoever the loop is on (CR 109.5)."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]], players=3)
    _w1g4_put(game, 0, lea["Hill Giant"])        # 4: the caster's greatest
    _w1g4_put(game, 1, lea["Grizzly Bears"])
    _w1g4_put(game, 2, lea["Shivan Dragon"])
    assert game.cast_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    _w1g4_resolve_stack(game)
    assert [player.life for player in game.players] == [
        24 if seat in named else 20 for seat in range(3)
    ], game.log


@_w1g4_pytest.mark.parametrize("named", [[0, 0], [1, 0]])
def test_w1g4_reward_the_faithful_names_each_player_once(set_pool, named):
    """CR 115.3: one player once per printed "target"; and the set is announced
    once, in seat order, rather than once per ordering."""
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]])
    assert not game.cast_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Reward the Faithful"]


def test_w1g4_reward_the_faithful_skips_a_player_that_became_illegal(
    set_pool, catalog_by_name,
):
    """CR 608.2b: of two named players, the one that gained shroud is not
    affected and the other still gains."""
    lea = set_pool("LEA")
    game = _w1g4_table(set_pool, [set_pool("SCG")["Reward the Faithful"]])
    _w1g4_put(game, 0, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Reward the Faithful", target_role_refs=[{"seat": 0}, {"seat": 1}],
    ).supported
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=catalog_by_name["Ivory Mask"]), None,
    )
    _w1g4_resolve_stack(game)
    assert [player.life for player in game.players] == [22, 20], game.log


def test_w1g4_reward_the_faithful_announces_a_chain_of_player_roles(set_pool):
    """The picker offers a seat per role, the caster's included, each a later
    seat than the last — what the client and the gates read."""
    card = set_pool("SCG")["Reward the Faithful"]
    roles = _w1g4_spec_roles(_w1g4_cast_spec(card, _w1g4_compile(card)))
    assert roles and all(role.get("kind") == "player" for role in roles)
    assert not any(role.get("opponents_only") for role in roles)
    assert all(role.get("optional_role") for role in roles)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState


def test_w1g5_fork_still_makes_its_copy_red(set_pool):
    """Fork's line left its card hook for the production Mischievous Quanar
    earned: the copy of a blue spell is red (CR 707.9b, "except that the copy
    is red"). Moved here from the creatures file: Fork is an instant."""
    lea = set_pool("LEA")
    p1 = _W1G5PlayerState(name="A", hand=[lea["Fork"]], library=[lea["Island"]] * 10)
    p2 = _W1G5PlayerState(name="B", hand=[lea["Ancestral Recall"]],
                          library=[lea["Island"]] * 10)
    game = _W1G5Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(1)
    p2.mana_pool.update({"U": 1})
    assert game.queue_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    game.priority_player_index = 0
    p1.mana_pool.update({"R": 2})
    cast = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert cast.supported, cast.details
    game.resolve_top_of_stack()
    copy = next(item for item in game.stack if item.is_copy)
    assert game._stack_item_colors(copy) == ("R",)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Gilded Light ("You gain shroud until end of turn.", a one-shot player
# keyword grant read by the one targeting reader) and Long-Term Plans (a
# search placed third from the top of the shuffled library).
import pytest as _w1g8_pytest

from engine import Game as _W1G8Game
from engine.models import PlayerState as _W1G8PlayerState
from engine.player_statics import seat_has_player_keyword as _w1g8_has_keyword

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_table(set_pool, hand, *, bob_hand=(), library=None, interactive=False):
    lea = set_pool("LEA")
    alice = _W1G8PlayerState(
        name="Alice", hand=list(hand),
        library=list(library if library is not None else [lea["Plains"]] * 6),
    )
    bob = _W1G8PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G8Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g8_drain(game):
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def test_w1g8_gilded_light_in_response_takes_the_bolt_off_its_caster(set_pool):
    """A Lightning Bolt aimed at Alice; Gilded Light cast in response gives
    her shroud (CR 702.18a: "This permanent or player can't be the target of
    spells or abilities"), so the Bolt's only target is illegal as it
    resolves and it is removed (CR 608.2b)."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Gilded Light"]], bob_hand=[lea["Lightning Bolt"]],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Gilded Light").supported
    _w1g8_drain(game)
    assert alice.life == 20
    assert _w1g8_has_keyword(game, 0, "shroud")
    assert any("every target is illegal" in line for line in game.log)


def test_w1g8_gilded_light_keeps_its_caster_off_every_picker_until_cleanup(set_pool):
    """For the rest of the turn no spell can name Alice — the cast is refused
    for want of a legal target, and Bob's own face is the only player the
    picker offers. The cleanup step ends it (CR 514.2), and the next Bolt
    lands."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    lea = set_pool("LEA")
    bolt = lea["Lightning Bolt"]
    game, alice, bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Gilded Light"]], bob_hand=[bolt, bolt],
    )
    assert game.cast_from_hand(0, "Gilded Light").supported
    _w1g8_drain(game)
    refused = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported
    assert alice.life == 20 and len(bob.hand) == 2
    spec = derive_cast_spec(bolt, compile_card_oracle(bolt))
    offered = game._enumerate_targets(1, bolt, spec, for_cast=True)
    assert {"kind": "player", "seat": 0} not in offered
    assert {"kind": "player", "seat": 1} in offered

    game.resolve_cleanup_step(game.active_player_index)
    assert not _w1g8_has_keyword(game, 0, "shroud")
    # Ended without a trace, so a rehearsal's digest of the seat reads the
    # seat it was before the grant (`player_statics.clear_player_keyword_grants`).
    assert "_player_keyword_grants" not in vars(alice)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_drain(game)
    assert alice.life == 17


def test_w1g8_gilded_light_shields_only_its_caster(set_pool):
    """"You" is the spell's controller (CR 109.5): Bob is still a target."""
    lea = set_pool("LEA")
    game, _alice, bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Gilded Light"], lea["Lightning Bolt"]],
    )
    assert game.cast_from_hand(0, "Gilded Light").supported
    _w1g8_drain(game)
    assert not _w1g8_has_keyword(game, 1, "shroud")
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g8_drain(game)
    assert bob.life == 17


def test_w1g8_gilded_light_still_cycles(set_pool):
    game, alice, _bob = _w1g8_table(set_pool, [set_pool("SCG")["Gilded Light"]])
    assert game.activate_from_hand(0, "Gilded Light").supported
    _w1g8_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert not _w1g8_has_keyword(game, 0, "shroud")


def test_w1g8_long_term_plans_puts_the_find_third_from_the_top(set_pool):
    """The searcher picks Black Lotus as a person; the library is shuffled
    and the Lotus put third from the top — after the shuffle, so the position
    is the card's (the printed order: "then shuffle and put that card")."""
    lea = set_pool("LEA")
    library = [lea[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
    library.append(lea["Black Lotus"])
    game, alice, _bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Long-Term Plans"]], library=library, interactive=True,
    )
    assert game.cast_from_hand(0, "Long-Term Plans").supported
    assert game.pending_choice_of("search_library", 0) is not None
    lotus = [card.name for card in alice.library].index("Black Lotus")
    assert game.resolve_pending_choice("search_library", 0, library_index=lotus)
    _w1g8_drain(game)
    assert len(alice.library) == 6
    assert alice.library[2].name == "Black Lotus"
    assert any("third from the top" in line for line in game.log)
    # The find is not revealed, so the log does not name it (CR 701.20e).
    assert not any("Black Lotus" in line for line in game.log)


@_w1g8_pytest.mark.parametrize("others", [0, 1, 2])
def test_w1g8_long_term_plans_with_a_short_library_puts_it_on_the_bottom(set_pool, others):
    """2004-10-04: "If there are fewer than 3 cards in your library, put the
    card on the bottom of your library." """
    lea = set_pool("LEA")
    game, alice, _bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Long-Term Plans"]],
        library=[lea["Black Lotus"]] + [lea["Plains"]] * others, interactive=True,
    )
    assert game.cast_from_hand(0, "Long-Term Plans").supported
    lotus = [card.name for card in alice.library].index("Black Lotus")
    assert game.resolve_pending_choice("search_library", 0, library_index=lotus)
    _w1g8_drain(game)
    assert [card.name for card in alice.library][-1] == "Black Lotus"
    assert len(alice.library) == others + 1


def test_w1g8_long_term_plans_finds_a_card_for_a_seat_nobody_asks(set_pool):
    """The default answer still finds one card and places it third."""
    lea = set_pool("LEA")
    library = [lea["Plains"]] * 5 + [lea["Black Lotus"]]
    game, alice, _bob = _w1g8_table(
        set_pool, [set_pool("SCG")["Long-Term Plans"]], library=library,
    )
    assert game.cast_from_hand(0, "Long-Term Plans").supported
    _w1g8_drain(game)
    assert len(alice.library) == 6
    assert game.pending_choices == []
    assert any("third from the top" in line for line in game.log)

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ======================================================


# ==== W2G2 ==========================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ======================================================


# ==== W2G3 ==========================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ======================================================


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ======================================================


# ==== W2G5 ==========================================================
# W2G5's tests go between this line and the "end W2G5" line.
#
# The deletion probe's Metamorphose finding: "an artifact, creature,
# enchantment, or land card" ignored `or`, which is the list's own
# conjunction — the four nouns are the instruction's type union.

from engine import Game as _W2G5Game, PlayerState as _W2G5PlayerState
from engine.models import Permanent as _W2G5Permanent


def test_w2g5_metamorphose_offers_each_of_its_four_types_and_no_spell(set_pool):
    """"That opponent may put an artifact, creature, enchantment, or land card
    from their hand onto the battlefield." Asked with one card of each type in
    hand beside an instant and a sorcery, the opponent is offered the Sol
    Ring, the Bad Moon, the Holy Strength, the Forest and the Grizzly Bears,
    and neither the Lightning Bolt nor the Wrath of God."""
    lea, scg = set_pool("LEA"), set_pool("SCG")
    opponent_hand = ("Lightning Bolt", "Sol Ring", "Bad Moon", "Forest",
                     "Grizzly Bears", "Wrath of God", "Holy Strength")
    game = _W2G5Game(players=[
        _W2G5PlayerState("A", hand=[scg["Metamorphose"]], library=[lea["Forest"]] * 12),
        _W2G5PlayerState("B", hand=[lea[name] for name in opponent_hand],
                         library=[lea["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    wurm = _W2G5Permanent(card=lea["Craw Wurm"])
    game._put_permanent_onto_battlefield(1, wurm, None)
    game.start_turn(0)
    game._settle()

    assert game.queue_from_hand(
        0, "Metamorphose", target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(1, accept=True)
    (choice,) = game.pending_choices_of("put_from_hand_choice", 1)
    hand = game.players[1].hand

    assert sorted(hand[i].name for i in game.live_put_from_hand_choices(choice)) == [
        "Bad Moon", "Forest", "Grizzly Bears", "Holy Strength", "Sol Ring",
    ]
    assert game.players[1].library[0].name == "Craw Wurm"

# ==== end W2G5 ======================================================
