"""Champions of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
#
# The drive list's instants: Call to Glory and Hold the Line.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def test_w1g2_call_to_glory_untaps_its_side_and_pumps_its_samurai(set_pool):
    """"Untap all creatures you control. Samurai creatures you control get
    +1/+1 until end of turn." The opponent's tapped Samurai stays tapped and
    unpumped; the Bears untaps and stays a 2/2."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([chk["Call to Glory"]], ()))
    retainer = _w1g2_put(game, chk["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, chk["Nezumi Ronin"], 1)
    for permanent in (retainer, bears, theirs):
        permanent.tapped = True
    assert game.cast_from_hand(0, "Call to Glory").supported
    _w1g2_settle(game)
    assert not retainer.tapped and not bears.tapped and theirs.tapped
    assert (retainer.effective_power, retainer.effective_toughness) == (2, 2)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (3, 1)


def test_w1g2_hold_the_line_pumps_only_the_blockers(set_pool):
    """"Blocking creatures get +7/+7 until end of turn." Cast in the declare
    blockers step: the blocking Devoted Retainer (already +1/+1 from bushido)
    is a 9/9, the attackers are untouched."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=((), [chk["Hold the Line"]]))
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    retainer = _w1g2_put(game, chk["Devoted Retainer"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(giant), game.battlefield_index_of(bears)],
        defending_player_index=1,
    )[0]
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(retainer): game.battlefield_index_of(giant)}
    )[0]
    _w1g2_settle(game)
    game.priority_player_index = 1
    assert game.cast_from_hand(1, "Hold the Line").supported
    _w1g2_settle(game)
    assert (retainer.effective_power, retainer.effective_toughness) == (9, 9)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# "Counter target Spirit or Arcane spell." (Hisoka's Defiance) — a subtype
# union with the head noun "spell", read into the ``any_classes`` the
# counter, its picker and the stack enumeration test.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.legality import cast_spec_of as _w1g4_cast_spec
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(1)
    _w1g4_settle(game)
    return game


@_w1g4_pytest.mark.parametrize("code, name", [
    ("CHK", "Reach Through Mists"),    # Instant — Arcane
    ("CHK", "Kami of the Hunt"),       # Creature — Spirit
])
def test_w1g4_hisokas_defiance_counters_a_spirit_or_arcane_spell(set_pool, code, name):
    """Bob casts it on his turn; Alice counters it, and it goes to his
    graveyard without resolving (no card drawn, no Kami on the battlefield)."""
    chk = set_pool("CHK")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]], opponent_hand=[set_pool(code)[name]],
    )
    assert game.queue_from_hand(1, name).supported
    hand_before = len(game.players[1].hand)
    assert game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=0).supported
    _w1g4_settle(game)
    assert name in [card.name for card in game.players[1].graveyard], game.log
    assert not list(game.controlled_by(1))
    assert len(game.players[1].hand) == hand_before


def test_w1g4_hisokas_defiance_offers_only_spirit_and_arcane_spells(set_pool):
    """The picker over a stack of an Arcane instant, a Spirit creature spell
    and a Grizzly Bears spell names the first two and never the Bears — and a
    cast aimed at the Bears is refused."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]],
        opponent_hand=[chk["Reach Through Mists"], chk["Kami of the Hunt"],
                       lea["Grizzly Bears"]],
    )
    for name in ("Reach Through Mists", "Kami of the Hunt", "Grizzly Bears"):
        assert game.queue_from_hand(1, name).supported
    defiance = chk["Hisoka's Defiance"]
    offered = game._enumerate_targets(0, defiance, _w1g4_cast_spec(defiance), for_cast=True)
    assert sorted(o["name"] for o in offered) == ["Kami of the Hunt", "Reach Through Mists"]
    # ``target_stack_index`` indexes the stack bottom-first: 2 is the Bears.
    assert not game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=2).supported
    assert [item.card.name for item in game.stack][-1] == "Grizzly Bears"


# "You may change any targets of target Arcane spell." (Sideswipe, CR 115.7c.)


def _w1g4_put(game, seat, card):
    from engine.models import Permanent

    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_glacial_ray_at_alice(set_pool, *, interactive):
    """Bob's turn: Bob's Glacial Ray (Instant — Arcane, 2 damage to any
    target) aimed at Alice's Grizzly Bears, Sideswipe in Alice's hand."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[chk["Glacial Ray"]],
    )
    game.interactive_seats = {0} if interactive else set()
    mine = _w1g4_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Glacial Ray", target_permanent_ids=[mine.permanent_id],
    ).supported
    return game, mine, theirs


def _w1g4_retarget_to(permanent):
    def answer(game, choice):
        options = choice.data["options"]
        index = next(
            i for i, option in enumerate(options)
            if option.get("permanent_id") == permanent.permanent_id
        )
        assert game.confirm_retarget_choice(choice.player_index, index)
    return answer


def _w1g4_keep(game, choice):
    assert choice.data["options"][0]["kind"] == "keep"
    assert game.confirm_retarget_choice(choice.player_index, 0)


@_w1g4_pytest.mark.parametrize("moved", [True, False])
def test_w1g4_sideswipe_changes_an_arcane_spells_target_or_keeps_it(set_pool, moved):
    """Alice re-aims the Ray at Bob's Bears, or keeps its target: the prompt
    offers "keep" first (CR 115.7c: any number of targets, none included)."""
    game, mine, theirs = _w1g4_glacial_ray_at_alice(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    _w1g4_settle(game, answers={
        "retarget_choice": _w1g4_retarget_to(theirs) if moved else _w1g4_keep,
    })
    assert game.is_on_battlefield(mine) is moved, game.log
    assert game.is_on_battlefield(theirs) is (not moved)


def test_w1g4_sideswipe_from_a_seat_nobody_asks_moves_the_ray_off_its_own_bears(set_pool):
    """A seat nobody asks takes the measured answer: the Ray no longer kills
    Alice's own Bears."""
    game, mine, _theirs = _w1g4_glacial_ray_at_alice(set_pool, interactive=False)
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    _w1g4_settle(game)
    assert game.is_on_battlefield(mine), game.log
    assert any("changed Glacial Ray's target" in line for line in game.log)


def test_w1g4_sideswipe_moves_any_number_of_several_targets(set_pool):
    """Unearthly Blizzard ("Up to three target creatures can't block this
    turn", Arcane) aimed at Alice's Bears and Hill Giant: Alice moves the
    first onto her Serra Angel and keeps the second (CR 115.7c), and the
    second slot is not offered the Angel the first now names (CR 115.3)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[chk["Unearthly Blizzard"]],
    )
    game.interactive_seats = {0}
    bears, giant, angel = (
        _w1g4_put(game, 0, lea[name]) for name in ("Grizzly Bears", "Hill Giant", "Serra Angel")
    )
    attacker = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Unearthly Blizzard", target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    first = _w1g4_settle(game, defaults=False)
    assert first.kind == "retarget_choice"
    _w1g4_retarget_to(angel)(game, first)
    second = _w1g4_settle(game, defaults=False)
    assert angel.permanent_id not in [o.get("permanent_id") for o in second.data["options"]]
    _w1g4_keep(game, second)
    _w1g4_settle(game)
    assert game._can_block_attacker(bears, attacker), game.log
    assert not game._can_block_attacker(giant, attacker)
    assert not game._can_block_attacker(angel, attacker)


def test_w1g4_sideswipe_targets_only_an_arcane_spell(set_pool):
    """Giant Growth is an instant but not Arcane: Sideswipe has nothing to
    target and the cast is refused."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[lea["Giant Growth"]],
    )
    theirs = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[theirs.permanent_id],
    ).supported
    sideswipe = chk["Sideswipe"]
    assert not game._enumerate_targets(0, sideswipe, _w1g4_cast_spec(sideswipe), for_cast=True)
    assert not game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.
#
# Splice onto Arcane (CR 702.47, ``engine/splice.py``): every splice card is
# driven alone and spliced onto a host, and the variable-sacrifice Arcane
# instants are driven with and without what they sacrifice. The splice
# machinery's rules tests are ``tests/rules/test_chk_w1g5_splice.py``.

from engine import Game as _w1g5_Game, PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import settle as _w1g5_settle

#: Where a test's card names are looked up, in order: the set, then the
#: shipped cards the boards borrow.
_W1G5_SETS = ("CHK", "LEA", "DST", "6ED")


def _w1g5_card(set_pool, name):
    for code in _W1G5_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
                opponent_hand=(), interactive=()):
    """A two-seat game on seat 0's first main phase, costs off, settled."""
    cards = lambda names: [_w1g5_card(set_pool, n) for n in names]  # noqa: E731
    island = _w1g5_card(set_pool, "Island")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState("A", hand=cards(hand), library=[island] * 10,
                          graveyard=cards(graveyard)),
        _w1g5_PlayerState("B", hand=cards(opponent_hand), library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g5_Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def _w1g5_hand(game, seat=0):
    return [card.name for card in game.players[seat].hand]


def _w1g5_accept(game, choice):
    game.confirm_optional_pay(choice.player_index, accept=True)


def test_w1g5_glacial_ray_alone_and_spliced_onto_a_targeted_sorcery(set_pool):
    """Glacial Ray deals 2; spliced onto Lava Spike (a sorcery host with its
    own target) the spell deals Lava Spike's 3 to the player and the gained
    2 to the creature, and the Ray stays in hand."""
    game, _mine, (giant,) = _w1g5_table(
        set_pool, hand=["Glacial Ray", "Lava Spike", "Glacial Ray"], theirs=["Hill Giant"],
    )
    assert game.cast_from_hand(0, "Glacial Ray", target_player_index=1).supported
    _w1g5_settle(game)
    assert game.players[1].life == 18
    result = game.cast_from_hand(0, "Lava Spike", target_player_index=1, splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert game.players[1].life == 15 and giant.damage_marked == 2
    assert "Lava Spike dealt 2 damage to Hill Giant" in game.log
    assert _w1g5_hand(game) == ["Glacial Ray"]


def test_w1g5_kodamas_might_and_lifted_by_clouds_spliced_onto_one_host(set_pool):
    game, (bears,), _theirs = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Kodama's Might", "Lifted by Clouds"],
        mine=["Grizzly Bears"],
    )
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [bears.permanent_id]},
        {"hand_index": 2, "target_permanent_ids": [bears.permanent_id]},
    ])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    assert game._has_keyword(bears, "flying")
    assert sorted(_w1g5_hand(game)) == ["Island", "Kodama's Might", "Lifted by Clouds"]


def test_w1g5_consuming_vortex_and_wear_away_spliced(set_pool):
    game, _mine, (giant, icy) = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Consuming Vortex", "Wear Away"],
        theirs=["Hill Giant", "Icy Manipulator"],
    )
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
        {"hand_index": 2, "target_permanent_ids": [icy.permanent_id]},
    ])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert _w1g5_hand(game, 1) == ["Hill Giant"]
    assert [card.name for card in game.players[1].graveyard] == ["Icy Manipulator"]


def test_w1g5_dampen_thought_spliced_mills_the_player_it_targets(set_pool):
    game, _mine, _theirs = _w1g5_table(set_pool, hand=["Reach Through Mists", "Dampen Thought"])
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_player_index": 1},
    ])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert len(game.players[1].graveyard) == 4 and len(game.players[1].library) == 6
    assert game.players[0].graveyard[-1].name == "Reach Through Mists"


def test_w1g5_desperate_ritual_alone_and_spliced_adds_red_mana(set_pool):
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Desperate Ritual", "Reach Through Mists", "Desperate Ritual"],
    )
    game.cast_from_hand(0, "Desperate Ritual")
    _w1g5_settle(game)
    assert game.players[0].mana_pool["R"] == 3
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[{"hand_index": 1}])
    _w1g5_settle(game)
    assert game.players[0].mana_pool["R"] == 6
    assert "Reach Through Mists produced {R}{R}{R}" in game.log


def test_w1g5_hideous_laughter_spliced_onto_a_sweeper(set_pool):
    game, (bears,), (giant, elves) = _w1g5_table(
        set_pool, hand=["Hideous Laughter", "Cleanfall", "Hideous Laughter"],
        mine=["Grizzly Bears"], theirs=["Hill Giant", "Llanowar Elves"],
    )
    result = game.cast_from_hand(0, "Cleanfall", splice_cards=[{"hand_index": 2}])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert not game.is_on_battlefield(bears) and not game.is_on_battlefield(elves)
    assert game.is_on_battlefield(giant) and giant.effective_toughness == 1


def test_w1g5_strange_inversion_spliced(set_pool):
    game, _mine, (wall,) = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Strange Inversion"], theirs=["Wall of Stone"],
    )
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [wall.permanent_id]},
    ])
    _w1g5_settle(game)
    assert not game.is_on_battlefield(wall)  # 8/0 after the switch


def test_w1g5_soulless_revival_spliced_returns_a_graveyard_creature(set_pool):
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Soulless Revival"],
        graveyard=["Forest", "Grizzly Bears"],
    )
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_graveyard_indices": [1]},
    ])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert "Grizzly Bears" in _w1g5_hand(game)
    assert [card.name for card in game.players[0].graveyard] == ["Forest", "Reach Through Mists"]


def test_w1g5_psychic_puppetry_spliced_taps_or_untaps(set_pool):
    """'You may tap or untap target permanent.' A seat nobody asks takes the
    default (tap); an interactive seat is asked the 'may' (optional_pay)."""
    game, _mine, (giant,) = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Psychic Puppetry"], theirs=["Hill Giant"],
    )
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    _w1g5_settle(game)
    assert giant.tapped
    game, _mine, (giant,) = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Psychic Puppetry"], theirs=["Hill Giant"],
        interactive=(0,),
    )
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    asked = _w1g5_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay"
    game.confirm_optional_pay(0, accept=False)
    _w1g5_settle(game)
    assert not giant.tapped


def test_w1g5_blessed_breath_spliced_asks_the_colour(set_pool):
    game, (bears,), _theirs = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Blessed Breath"], mine=["Grizzly Bears"],
        opponent_hand=["Shock"], interactive=(0,),
    )
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [bears.permanent_id]},
    ])
    asked = _w1g5_settle(game, defaults=False)
    assert asked is not None and asked.kind == "color_choice"
    assert game.confirm_color_choice(0, "R")
    _w1g5_settle(game)
    assert any("protection from red" in line for line in game.log)
    refused = game.cast_from_hand(1, "Shock", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported


def test_w1g5_candles_glow_gains_its_caster_what_it_prevents(set_pool):
    """'Prevent the next 3 damage that would be dealt to any target this turn.
    You gain life equal to the damage prevented this way.' The caster gains,
    whoever the shield goes around; spliced, the same."""
    game, _mine, (bears,) = _w1g5_table(
        set_pool, hand=["Candles' Glow", "Shock"], theirs=["Grizzly Bears"],
    )
    game.cast_from_hand(0, "Candles' Glow", target_permanent_ids=[bears.permanent_id])
    game.cast_from_hand(0, "Shock", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert bears.damage_marked == 0
    assert (game.players[0].life, game.players[1].life) == (22, 20)
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Candles' Glow"], opponent_hand=["Lightning Bolt"],
    )
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_player_index": 0},
    ])
    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    _w1g5_settle(game)
    assert game.players[0].life == 23  # 3 prevented, 3 gained


def test_w1g5_through_the_breach_and_its_end_step_sacrifice(set_pool):
    game, _mine, _theirs = _w1g5_table(set_pool, hand=["Through the Breach", "Hill Giant"])
    game.cast_from_hand(0, "Through the Breach")
    _w1g5_settle(game)
    giant = next(p for p in game.players[0].battlefield if p.card.name == "Hill Giant")
    assert game._has_keyword(giant, "haste")
    game.resolve_end_step(0)
    _w1g5_settle(game)
    assert not game.is_on_battlefield(giant)
    assert "Hill Giant" in [card.name for card in game.players[0].graveyard]


def test_w1g5_through_the_breach_spliced_asks_and_sacrifices(set_pool):
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Reach Through Mists", "Through the Breach", "Hill Giant"],
        interactive=(0,),
    )
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[{"hand_index": 1}])
    asked = _w1g5_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay"
    _w1g5_settle(game, answers={"optional_pay": _w1g5_accept})
    giant = next(p for p in game.players[0].battlefield if p.card.name == "Hill Giant")
    assert "Through the Breach" in _w1g5_hand(game)
    game.interactive_seats = set()
    game.resolve_end_step(0)
    _w1g5_settle(game)
    assert not game.is_on_battlefield(giant)


def test_w1g5_devouring_rage_counts_the_spirits_its_cost_sacrificed(set_pool):
    """+3/+0, and +3/+0 more for each Spirit sacrificed as the cost
    ('you may sacrifice any number of Spirits', the cast's optional offer)."""
    for sacrificed, power in ((2, 11), (0, 5)):
        game, (bears, *spirits), _theirs = _w1g5_table(
            set_pool, hand=["Devouring Rage"],
            mine=["Grizzly Bears", "Kami of Ancient Law", "Lantern Kami"],
        )
        result = game.cast_from_hand(
            0, "Devouring Rage", target_permanent_ids=[bears.permanent_id],
            cost_permanent_ids=[s.permanent_id for s in spirits[:sacrificed]],
            optional_cost_payments={"sacrifice any number of spirits": 1},
        )
        assert result.supported, result.details
        _w1g5_settle(game)
        assert bears.effective_power == power, sacrificed
        assert len(game.players[0].battlefield) == 3 - sacrificed


def test_w1g5_soulblast_deals_the_total_power_it_sacrificed(set_pool):
    game, mine, (wurm,) = _w1g5_table(
        set_pool, hand=["Soulblast"],
        mine=["Grizzly Bears", "Hill Giant", "Kami of Ancient Law"], theirs=["Craw Wurm"],
    )
    result = game.cast_from_hand(0, "Soulblast", target_permanent_ids=[wurm.permanent_id])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert game.players[0].battlefield == []
    assert not game.is_on_battlefield(wurm)  # 2 + 3 + 2 = 7 damage
    game, _mine, _theirs = _w1g5_table(set_pool, hand=["Soulblast"])
    game.cast_from_hand(0, "Soulblast", target_player_index=1)
    _w1g5_settle(game)
    assert game.players[1].life == 20  # nothing sacrificed, nothing dealt

# ==== end w1g5 ======================================================
