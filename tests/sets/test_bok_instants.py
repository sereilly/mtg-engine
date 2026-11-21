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
