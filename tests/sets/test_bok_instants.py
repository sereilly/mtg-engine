"""Betrayers of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.
#
# Splice onto Arcane with a cost that is not mana (CR 702.47a: Hundred-Talon
# Strike, Horobi's Whisper, Roar of Jukai, Torrent of Stone, Veil of Secrecy),
# each spliced onto a real Arcane host (Champions of Kamigawa's Glacial Ray)
# and paid as the spell is cast (CR 601.2h); Goryo's Vengeance's legendary
# reanimation; Minamo's Meddling's spliced names. The rules of the payment
# itself (exclusive payers, the spell's own costs beside its splice costs)
# are ``tests/rules/test_bok_w1g3_splice_costs.py``.

from engine import Game as _w1g3_Game
from engine import PlayerState as _w1g3_PlayerState
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import declare_attack as _w1g3_declare_attack
from tests.helpers import settle as _w1g3_settle

#: Where each card the section names is looked up, in order.
_W1G3_SETS = ("BOK", "CHK", "LEA")


def _w1g3_card(set_pool, name):
    for code in _W1G3_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
                opponent_hand=()):
    """A two-seat table on seat 0's first main phase, costs not enforced (the
    splice costs that are not mana are charged all the same)."""
    cards = lambda names: [_w1g3_card(set_pool, n) for n in names]  # noqa: E731
    island = _w1g3_card(set_pool, "Island")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState("A", hand=cards(hand), library=[island] * 10,
                          graveyard=cards(graveyard)),
        _w1g3_PlayerState("B", hand=cards(opponent_hand), library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g3_Permanent(card=_w1g3_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g3_settle(game)
    return game, placed[0], placed[1]


def _w1g3_names(cards):
    return [card.name for card in cards]


def test_w1g3_hundred_talon_strike_taps_the_white_creature_named_to_splice_it(set_pool):
    game, (lions, knight, bears), (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Hundred-Talon Strike"],
        mine=["Savannah Lions", "White Knight", "Grizzly Bears"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [bears.permanent_id],
            "cost_permanent_ids": [knight.permanent_id],
        }],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    # The named white creature paid; the other one did not.
    assert knight.tapped and not lions.tapped and not bears.tapped
    assert giant.damage_marked == 2
    assert bears.effective_power == 3 and game._has_keyword(bears, "first strike")
    # The spliced card was revealed and stays in hand (CR 702.47a).
    assert _w1g3_names(game.players[0].hand) == ["Hundred-Talon Strike"]
    assert any("tapped White Knight to splice Hundred-Talon Strike" in line for line in game.log)


def test_w1g3_hundred_talon_strike_without_a_white_creature_is_refused_with_nothing_spent(set_pool):
    game, (bears,), (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Hundred-Talon Strike"],
        mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert not result.supported
    assert "Hundred-Talon Strike can't be spliced onto Glacial Ray" in result.details
    assert _w1g3_names(game.players[0].hand) == ["Glacial Ray", "Hundred-Talon Strike"]
    assert not bears.tapped and giant.damage_marked == 0


def test_w1g3_horobis_whisper_exiles_the_four_named_cards_and_destroys(set_pool):
    game, _mine, (giant, knight) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Horobi's Whisper"], mine=["Swamp"],
        theirs=["Hill Giant", "Black Knight"],
        graveyard=["Island", "Lightning Bolt", "Grizzly Bears", "Hill Giant", "Mountain"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[knight.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [giant.permanent_id],
            "cost_graveyard_indices": [0, 2, 3, 4],
        }],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    caster = game.players[0]
    assert _w1g3_names(caster.exile) == ["Island", "Grizzly Bears", "Hill Giant", "Mountain"]
    assert _w1g3_names(caster.graveyard) == ["Lightning Bolt", "Glacial Ray"]
    # "If you control a Swamp, destroy target nonblack creature."
    assert not game.is_on_battlefield(giant)
    assert "Horobi's Whisper" in _w1g3_names(caster.hand)


def test_w1g3_horobis_whisper_cannot_be_spliced_with_three_cards_in_the_graveyard(set_pool):
    game, _mine, (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Horobi's Whisper"], mine=["Swamp"],
        theirs=["Hill Giant"], graveyard=["Island", "Lightning Bolt", "Mountain"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [giant.permanent_id]}],
    )
    assert not result.supported
    assert len(game.players[0].graveyard) == 3 and not game.players[0].exile


def test_w1g3_roar_of_jukai_pumps_each_blocked_creature_and_its_splice_feeds_an_opponent(set_pool):
    game, (forest, bears, giant), (wall,) = _w1g3_table(
        set_pool, hand=["Roar of Jukai", "Glacial Ray", "Roar of Jukai"],
        mine=["Forest", "Grizzly Bears", "Hill Giant"], theirs=["Wall of Stone"],
    )
    # The Bears are blocked by the Wall; the Giant is not.
    _w1g3_declare_attack(game, 0, blocks={0: 1})
    assert bears.blocked and not giant.blocked
    result = game.cast_from_hand(0, "Roar of Jukai")
    assert result.supported, result.details
    _w1g3_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert wall.effective_toughness == 8
    # Spliced onto Glacial Ray, its cost is an opponent's 5 life (CR 702.47a).
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[wall.permanent_id],
        splice_cards=[{"hand_index": 1}],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    assert game.players[1].life == 25
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert wall.damage_marked == 2


def test_w1g3_torrent_of_stone_sacrifices_the_two_named_mountains(set_pool):
    game, (first, second, third), (giant, bears) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Torrent of Stone"],
        mine=["Mountain", "Mountain", "Mountain"], theirs=["Hill Giant", "Grizzly Bears"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[bears.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [giant.permanent_id],
            "cost_permanent_ids": [first.permanent_id, third.permanent_id],
        }],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    assert [perm is second for perm in game.controlled_by(0)] == [True]
    assert _w1g3_names(game.players[0].graveyard).count("Mountain") == 2
    assert not game.is_on_battlefield(giant) and not game.is_on_battlefield(bears)


def test_w1g3_torrent_of_stone_with_one_mountain_named_is_refused(set_pool):
    game, (first, _second), (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Torrent of Stone"],
        mine=["Mountain", "Mountain"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id], splice_cards=[{
            "hand_index": 1, "target_permanent_ids": [giant.permanent_id],
            "cost_permanent_ids": [first.permanent_id],
        }],
    )
    # CR 601.2h: "Partial payments are not allowed."
    assert not result.supported and "each named once" in result.details
    assert len(list(game.controlled_by(0))) == 2


def test_w1g3_veil_of_secrecy_returns_the_blue_creature_and_hides_its_target(set_pool):
    game, (merfolk, bears), (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Veil of Secrecy"],
        mine=["Merfolk of the Pearl Trident", "Grizzly Bears"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    assert not game.is_on_battlefield(merfolk)
    assert _w1g3_names(game.players[0].hand) == ["Veil of Secrecy", "Merfolk of the Pearl Trident"]
    assert game._has_keyword(bears, "shroud") and game.is_unblockable(bears)


def test_w1g3_goryos_vengeance_reanimates_a_legendary_creature_until_the_end_step(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Goryo's Vengeance"],
        graveyard=["Hill Giant", "Hikari, Twilight Guardian"],
    )
    spec = game.cast_target_spec(0, game.players[0].hand[0], from_zone="hand")
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Hikari, Twilight Guardian"]
    refused = game.cast_from_hand(0, "Goryo's Vengeance", target_graveyard_indices=[0])
    assert not refused.supported
    result = game.cast_from_hand(0, "Goryo's Vengeance", target_graveyard_indices=[1])
    assert result.supported, result.details
    _w1g3_settle(game)
    (hikari,) = game.controlled_by(0)
    assert hikari.card.name == "Hikari, Twilight Guardian"
    assert game._has_keyword(hikari, "haste")
    game.resolve_end_step(0)
    _w1g3_settle(game)
    assert not list(game.controlled_by(0))
    assert _w1g3_names(game.players[0].exile) == ["Hikari, Twilight Guardian"]


def test_w1g3_goryos_vengeance_spliced_creature_that_left_is_not_exiled(set_pool):
    """The 2018-12-07 ruling: "If the returned creature leaves the battlefield
    before the end step, it will remain in its current zone." Spliced onto
    Glacial Ray, the gained text is the host's (CR 702.47c)."""
    game, _mine, (giant,) = _w1g3_table(
        set_pool, hand=["Glacial Ray", "Goryo's Vengeance"], theirs=["Hill Giant"],
        graveyard=["Hikari, Twilight Guardian"],
    )
    result = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[giant.permanent_id],
        splice_cards=[{"hand_index": 1, "target_graveyard_indices": [0]}],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    (hikari,) = game.controlled_by(0)
    assert any("Glacial Ray returned Hikari" in line for line in game.log)
    from engine.handlers._common import return_permanent_to_owners_hand

    return_permanent_to_owners_hand(game, hikari, game.players[0])
    game.resolve_end_step(0)
    _w1g3_settle(game)
    assert "Hikari, Twilight Guardian" in _w1g3_names(game.players[0].hand)
    assert not game.players[0].exile


def test_w1g3_minamos_meddling_discards_every_card_named_like_a_spliced_one(set_pool):
    game, (bears,), _theirs = _w1g3_table(
        set_pool, hand=["Minamo's Meddling"], mine=["Grizzly Bears"],
        opponent_hand=["Reach Through Mists", "Glacial Ray", "Glacial Ray",
                       "Hill Giant", "Glacial Ray"],
    )
    queued = game.queue_from_hand(1, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [bears.permanent_id]},
    ])
    assert queued.supported, queued.details
    result = game.cast_from_hand(0, "Minamo's Meddling", target_stack_index=0)
    assert result.supported, result.details
    _w1g3_settle(game)
    victim = game.players[1]
    # The spliced Glacial Ray stayed in hand (CR 702.47a), so it goes too.
    assert _w1g3_names(victim.hand) == ["Hill Giant"]
    assert _w1g3_names(victim.graveyard) == [
        "Reach Through Mists", "Glacial Ray", "Glacial Ray", "Glacial Ray",
    ]
    assert game.is_on_battlefield(bears)
    assert any("B reveals their hand" in line for line in game.log)


def test_w1g3_minamos_meddling_on_a_spell_nothing_was_spliced_onto_discards_nothing(set_pool):
    game, (bears,), _theirs = _w1g3_table(
        set_pool, hand=["Minamo's Meddling"], mine=["Grizzly Bears"],
        opponent_hand=["Glacial Ray", "Glacial Ray"],
    )
    game.queue_from_hand(1, "Glacial Ray", target_permanent_ids=[bears.permanent_id])
    result = game.cast_from_hand(0, "Minamo's Meddling", target_stack_index=0)
    assert result.supported, result.details
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].hand) == ["Glacial Ray"]
    assert game.is_on_battlefield(bears)


# The drive list: Arcane instants supported on arrival, each given a game.


def test_w1g3_vital_surge_spliced_charges_its_mana_and_gains_three(set_pool):
    game, (bears,), _theirs = _w1g3_table(
        set_pool, hand=["Unchecked Growth", "Vital Surge"], mine=["Grizzly Bears"],
    )
    game.enforce_mana_costs = True
    pool = game.players[0].mana_pool
    pool["G"] = 4
    short = game.cast_from_hand(
        0, "Unchecked Growth", target_permanent_ids=[bears.permanent_id],
        splice_cards=[{"hand_index": 1}],
    )
    assert not short.supported and "splicing Vital Surge" in short.details
    # Read off the seat again: the refusal takes the attempt back, the pool
    # included (CR 733.1).
    pool = game.players[0].mana_pool
    assert pool["G"] == 4
    pool["G"] = 5
    paid = game.cast_from_hand(
        0, "Unchecked Growth", target_permanent_ids=[bears.permanent_id],
        splice_cards=[{"hand_index": 1}],
    )
    assert paid.supported, paid.details
    _w1g3_settle(game)
    assert game.players[0].life == 23 and game.players[0].mana_pool["G"] == 0
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    # Not a Spirit: no trample from the second sentence.
    assert not game._has_keyword(bears, "trample")
    assert _w1g3_names(game.players[0].hand) == ["Vital Surge"]


def test_w1g3_unchecked_growth_gives_a_spirit_trample(set_pool):
    game, (kami,), _theirs = _w1g3_table(
        set_pool, hand=["Unchecked Growth"], mine=["Kami of Ancient Law"],
    )
    assert game.cast_from_hand(
        0, "Unchecked Growth", target_permanent_ids=[kami.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert kami.effective_power == 6 and game._has_keyword(kami, "trample")


def test_w1g3_ire_of_kaminari_counts_the_arcane_cards_in_its_casters_graveyard(set_pool):
    game, _mine, (giant,) = _w1g3_table(
        set_pool, hand=["Ire of Kaminari"], theirs=["Hill Giant"],
        graveyard=["Glacial Ray", "Reach Through Mists", "Lightning Bolt"],
    )
    assert game.cast_from_hand(
        0, "Ire of Kaminari", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert giant.damage_marked == 2  # two Arcane cards; Lightning Bolt is not


def test_w1g3_first_volley_deals_one_to_the_creature_and_one_to_its_controller(set_pool):
    game, _mine, (bears,) = _w1g3_table(
        set_pool, hand=["First Volley"], theirs=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "First Volley", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert bears.damage_marked == 1 and game.players[1].life == 19


def test_w1g3_stream_of_consciousness_shuffles_up_to_four_chosen_cards_back(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Stream of Consciousness"],
        graveyard=["Glacial Ray", "Hill Giant", "Lightning Bolt", "Island", "Mountain"],
    )
    library_before = len(game.players[0].library)
    assert game.cast_from_hand(
        0, "Stream of Consciousness", target_player_index=0,
        target_graveyard_indices=[0, 1, 2, 3],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].graveyard) == ["Mountain", "Stream of Consciousness"]
    assert len(game.players[0].library) == library_before + 4


def test_w1g3_toils_of_night_and_day_taps_or_untaps_each_target(set_pool):
    game, (bears,), (giant,) = _w1g3_table(
        set_pool, hand=["Toils of Night and Day"], mine=["Grizzly Bears"],
        theirs=["Hill Giant"],
    )
    bears.tapped = True
    game.interactive_seats = {0}
    assert game.queue_from_hand(
        0, "Toils of Night and Day",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    ).supported
    # Each "you may" is asked of the caster: decline the first, take the
    # second.
    asked = []

    def answer(answering, choice):
        asked.append(choice.kind)
        answering.confirm_optional_pay(choice.player_index, accept=len(asked) > 1)

    _w1g3_settle(game, answers={"optional_pay": answer})
    assert asked == ["optional_pay", "optional_pay"]
    assert bears.tapped and giant.tapped


def test_w1g3_terashis_verdict_destroys_an_attacker_with_power_three_or_less(set_pool):
    game, (bears, giant, wurm), _theirs = _w1g3_table(
        set_pool, opponent_hand=["Terashi's Verdict"],
        mine=["Grizzly Bears", "Hill Giant", "Craw Wurm"],
    )
    _w1g3_declare_attack(game, 0)
    spec = game.cast_target_spec(1, game.players[1].hand[0], from_zone="hand")
    assert {entry.get("index") for entry in spec["valid_targets"]} == {0, 1}
    assert not game.cast_from_hand(
        1, "Terashi's Verdict", target_permanent_ids=[wurm.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Terashi's Verdict", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(wurm)

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage: unpreventable damage with a life-gain replacement, damage doubling,
# redirection and two ordered dealings (CR 614, 615). Each test casts the
# spell through the engine's entry point and reads the board after `settle`.

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5_cast(game, seat, name, **announce):
    result = game.cast_from_hand(seat, name, **announce)
    assert result.supported, (result.details, game.log[-6:])
    _w1g5_settle(game)
    return result


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_flames_of_the_blood_hand_unpreventable_and_no_life_gain(
    set_pool, interactive,
):
    """"…deals 4 damage to target player or planeswalker. The damage can't
    be prevented. If that player or that planeswalker's controller would
    gain life this turn, that player gains no life instead." A Circle of
    Protection: Red shield is spent on nothing (CR 615.12) and the player
    takes all 4; their Healing Salve gains them nothing this turn (the
    replacement, CR 614.1a), while the caster's own gain is untouched — and
    next turn the target gains again."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Flames of the Blood Hand"]],
        opponent_hand=[lea["Healing Salve"]] * 3,
    )
    circle = _w1g5_put(game, lea["Circle of Protection: Red"], seat=1)
    result = game.activate_permanent_ability(
        1, circle.card.name, permanent_index=game.battlefield_index_of(circle),
    )
    assert result.supported
    _w1g5_settle(game)
    _w1g5_cast(game, 0, "Flames of the Blood Hand", target_player_index=1)
    assert game.players[1].life == 16, game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 16, game.log
    assert any("gains no life instead (Flames of the Blood Hand)" in line
               for line in game.log), game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=0)
    assert game.players[0].life == 23, game.log
    # CR 514.2: the record ends with the turn's cleanup step.
    game.resolve_cleanup_step(0)
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 19, game.log


def test_w1g5_flames_at_a_planeswalker_replaces_its_controllers_gains(set_pool):
    """Aimed at a planeswalker, the 4 damage is dealt to it — Garruk,
    Unleashed (loyalty 4) dies — and "that planeswalker's controller" is the
    seat whose gains are replaced."""
    bok, lea, m21 = set_pool("BOK"), set_pool("LEA"), set_pool("M21")
    game = _w1g5_table(
        set_pool, hand=[bok["Flames of the Blood Hand"]],
        opponent_hand=[lea["Healing Salve"]],
    )
    walker = _w1g5_put(game, m21["Garruk, Unleashed"], seat=1)
    _w1g5_cast(game, 0, "Flames of the Blood Hand",
               target_permanent_ids=[walker.permanent_id])
    assert game.players[1].life == 20, game.log
    assert not game.is_on_battlefield(walker), game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 20, game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_overblaze_doubles_the_target_permanents_damage_only(
    set_pool, interactive,
):
    """"Each time target permanent would deal damage to a permanent or player
    this turn, it deals double that damage to that permanent or player
    instead." The targeted Prodigal Sorcerer pings for 2, every time this
    turn; a second Sorcerer — the same card, another object — still pings
    for 1 (CR 614). The record ends at cleanup (CR 514.2)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, interactive, hand=[bok["Overblaze"]])
    doubled = _w1g5_put(game, lea["Prodigal Sorcerer"])
    other = _w1g5_put(game, lea["Prodigal Sorcerer"])
    _w1g5_cast(game, 0, "Overblaze", target_permanent_ids=[doubled.permanent_id])

    def ping(sorcerer):
        sorcerer.tapped = False
        result = game.activate_permanent_ability(
            0, sorcerer.card.name,
            permanent_index=game.battlefield_index_of(sorcerer),
            target_player_index=1,
        )
        assert result.supported, result.details
        _w1g5_settle(game)

    ping(doubled)
    assert game.players[1].life == 18, game.log
    ping(other)
    assert game.players[1].life == 17, game.log
    ping(doubled)
    assert game.players[1].life == 15, game.log
    game.resolve_cleanup_step(0)
    ping(doubled)
    assert game.players[1].life == 14, game.log


def test_w1g5_overblaze_spliced_onto_an_arcane_spell(set_pool):
    """Spliced onto Lava Spike (CR 702.47), the spell deals its 3 and arms
    Overblaze's doubling on the permanent the splice targeted — an opposing
    Prodigal Sorcerer, whose ping then deals 2 — and Overblaze stays in
    hand."""
    bok, lea, chk = set_pool("BOK"), set_pool("LEA"), set_pool("CHK")
    game = _w1g5_table(set_pool, hand=[chk["Lava Spike"], bok["Overblaze"]])
    theirs = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_cast(game, 0, "Lava Spike", target_player_index=1, splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [theirs.permanent_id]},
    ])
    assert game.players[1].life == 17, game.log
    assert [card.name for card in game.players[0].hand] == ["Overblaze"]
    result = game.activate_permanent_ability(
        1, theirs.card.name, permanent_index=game.battlefield_index_of(theirs),
        target_player_index=0,
    )
    assert result.supported
    _w1g5_settle(game)
    assert game.players[0].life == 18, game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_aura_barbs_each_enchantment_deals_the_damage(set_pool, interactive):
    """"Each enchantment deals 2 damage to its controller, then each Aura
    attached to a creature deals 2 damage to the creature it's attached to."
    The damage is dealt by the enchantments, not by Aura Barbs (ruling
    2005-02-01): a Circle of Protection: White shield naming Holy Strength
    stops Holy Strength's 2 to its controller and nothing else — the Circle
    of Protection: Red beside it, another white source, still deals its 2 —
    and the red spell itself is no source a white Circle could ever stop.
    Holy Strength, on the opponent's Hill Giant, then deals 2 to the Giant;
    Bad Moon deals 2 to its own controller."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Aura Barbs"], lea["Holy Strength"]],
    )
    white_circle = _w1g5_put(game, lea["Circle of Protection: White"])
    _w1g5_put(game, lea["Circle of Protection: Red"])
    giant = _w1g5_put(game, lea["Hill Giant"], seat=1)
    _w1g5_put(game, lea["Bad Moon"], seat=1)
    _w1g5_cast(game, 0, "Holy Strength", target_permanent_ids=[giant.permanent_id])
    strength = next(
        perm for perm in game.players[0].battlefield
        if perm.card.name == "Holy Strength"
    )
    result = game.activate_permanent_ability(
        0, white_circle.card.name,
        permanent_index=game.battlefield_index_of(white_circle),
        target_permanent_ids=[strength.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    _w1g5_cast(game, 0, "Aura Barbs")
    # Seat 0: three white enchantments deal 2 each; the shielded one is
    # prevented. Seat 1: Bad Moon's 2.
    assert [p.life for p in game.players] == [16, 18], game.log
    assert "Circle of Protection: Red deals 2 damage to P0" in game.log
    assert "Circle of Protection: White deals 2 damage to P0" in game.log
    assert "Holy Strength deals 2 damage to P0" not in game.log
    assert giant.damage_marked == 2 and game.is_on_battlefield(giant), game.log

@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_shining_shoal_moves_x_points_of_the_chosen_source(set_pool, interactive):
    """"The next X damage that a source of your choice would deal to you
    and/or creatures you control this turn is dealt to any target instead."
    Cast for X=3 naming the opponent's Pestilence and aimed at the opponent:
    of Pestilence's sweep, the chunks to the caster, the Bears and the Hill
    Giant — three points — are dealt to the opponent instead ("The redirection
    protects both you and your creatures from the source", ruling
    2005-02-01); the opponent's own Craw Wurm is not protected. The pool is
    spent, so the next sweep lands everywhere. Another source's damage is
    never moved."""
    bok, lea, ed2 = set_pool("BOK"), set_pool("LEA"), set_pool("2ED")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Shining Shoal"]],
        opponent_hand=[lea["Lightning Bolt"]],
    )
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    giant = _w1g5_put(game, lea["Hill Giant"])
    pestilence = _w1g5_put(game, ed2["Pestilence"], seat=1)
    wurm = _w1g5_put(game, lea["Craw Wurm"], seat=1)
    _w1g5_cast(
        game, 0, "Shining Shoal", x_value=3, target_player_index=1,
        chosen_source_seat=1,
        chosen_source_permanent_index=game.battlefield_index_of(pestilence),
    )
    _w1g5_cast(game, 1, "Lightning Bolt", target_player_index=0)
    assert game.players[0].life == 17, game.log

    def sweep():
        result = game.activate_permanent_ability(
            1, pestilence.card.name,
            permanent_index=game.battlefield_index_of(pestilence),
        )
        assert result.supported
        _w1g5_settle(game)

    sweep()
    assert [p.life for p in game.players] == [17, 16], game.log
    assert (bears.damage_marked, giant.damage_marked, wurm.damage_marked) == (0, 0, 1)
    sweep()
    assert [p.life for p in game.players] == [16, 15], game.log
    assert (bears.damage_marked, giant.damage_marked, wurm.damage_marked) == (1, 1, 2)


def test_w1g5_mending_hands_shields_four_points_across_two_bolts(set_pool):
    """"Prevent the next 4 damage that would be dealt to any target this
    turn." (Supported on arrival; driven here.) Two Lightning Bolts at its
    caster: 4 of the 6 are prevented."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, hand=[bok["Mending Hands"]],
        opponent_hand=[lea["Lightning Bolt"]] * 2,
    )
    _w1g5_cast(game, 0, "Mending Hands", target_player_index=0)
    _w1g5_cast(game, 1, "Lightning Bolt", target_player_index=0)
    _w1g5_cast(game, 1, "Lightning Bolt", target_player_index=0)
    assert game.players[0].life == 18, game.log

# ==== end w1g5 ======================================================



# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
