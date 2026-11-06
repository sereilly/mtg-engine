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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
