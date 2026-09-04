"""Per-card tests for Legends' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from tests.helpers import _mk_card


# ---------------------------------------------------------------------------
# Syphon Soul (round 20) — "each other player", and the life the sweep produced
# ---------------------------------------------------------------------------


def _syphon(set_pool, seats: int):
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [set_pool("LEG")["Syphon Soul"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def test_syphon_soul_burns_the_opponent_and_gains_that_much(set_pool):
    """The duel reading: 2 damage to the one other player, 2 life back."""
    game, players = _syphon(set_pool, 2)

    result = game.cast_from_hand(0, "Syphon Soul")

    assert result.supported, result.details
    assert players[1].life == 18
    assert players[0].life == 22, game.log


def test_the_life_gained_is_the_total_damage_the_sweep_dealt(set_pool):
    """"Equal to the damage dealt this way" is about the whole effect, not
    about one event: three seats means two damage events and four life. A
    back-reference that read only the last one would gain 2 here and pass the
    duel test above, which is why the multiplayer board is the real check."""
    game, players = _syphon(set_pool, 3)

    result = game.cast_from_hand(0, "Syphon Soul")

    assert result.supported, result.details
    assert [p.life for p in players] == [24, 18, 18], game.log


def test_syphon_soul_never_damages_its_own_caster(set_pool):
    """"Each **other** player" excludes the controller — the seat that gains
    the life. Read as "each player" the caster would take 2 and net +2."""
    game, players = _syphon(set_pool, 3)

    game.cast_from_hand(0, "Syphon Soul")

    assert players[0].life == 24


# ---------------------------------------------------------------------------
# Jovial Evil (round 20) — a count on the targeted player's board, doubled
# ---------------------------------------------------------------------------


def _jovial(set_pool, victim_names: list[str]):
    from engine.models import Permanent

    leg, lea = set_pool("LEG"), set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[leg["Jovial Evil"]], life=20)
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=lea[name]) for name in victim_names],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_jovial_evil_deals_twice_the_white_creatures_that_player_controls(set_pool):
    """Two white creatures and one green one: X is 2, the damage is 4."""
    game, p1, p2 = _jovial(
        set_pool, ["Savannah Lions", "Benalish Hero", "Grizzly Bears"]
    )

    result = game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert result.supported, result.details
    assert p2.life == 16, game.log


def test_the_multiplier_is_not_a_second_name_for_the_count(set_pool):
    """The control on "twice": one white creature is 2 damage, not 1. A parse
    that consumed the word and lowered a plain count would pass every test that
    happens to stand on an even board."""
    game, p1, p2 = _jovial(set_pool, ["Savannah Lions"])

    game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert p2.life == 18, game.log


def test_the_count_is_taken_on_the_targeted_players_board(set_pool):
    """"That player controls" is the opponent the spell targeted, not the
    caster: a count taken on the wrong battlefield reads the caster's white
    creatures and deals nothing here."""
    from engine.models import Permanent

    game, p1, p2 = _jovial(set_pool, [])
    p1.battlefield = [Permanent(card=set_pool("LEA")["Savannah Lions"])]

    game.cast_from_hand(0, "Jovial Evil", target_player_index=1)

    assert p2.life == 20, game.log
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Cleanse (round 20) — the colour a type-keyed sweep used to drop
# ---------------------------------------------------------------------------


def test_cleanse_destroys_only_the_black_creatures(set_pool):
    """"Destroy all **black** creatures" compiled onto `destroy_all_creatures`,
    whose payload is empty and whose scope is its own kind — so the colour was
    dropped and Cleanse wiped the board. A sweep that names a narrowing the
    handler cannot carry is a card that does strictly more than it prints."""
    from engine.models import Permanent

    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Cleanse"]])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Bog Wraith"]),      # black
        Permanent(card=lea["Grizzly Bears"]),   # green
    ])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Cleanse")

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Grizzly Bears"], game.log


# ---------------------------------------------------------------------------
# Hellfire (round 20) — "X plus 3", where X is what the sweep just killed
# ---------------------------------------------------------------------------


def _hellfire(set_pool, mine: list[str], theirs: list[str]):
    from engine.models import Permanent

    lea = set_pool("LEA")
    p1 = PlayerState(
        name="P1", life=20, hand=[set_pool("LEG")["Hellfire"]],
        battlefield=[Permanent(card=lea[name]) for name in mine],
    )
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=lea[name]) for name in theirs],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_hellfire_spares_the_black_creatures_and_burns_for_the_rest_plus_three(set_pool):
    """Three nonblack creatures die, so X is 3 and the caster takes 6. The
    black Wraith is untouched — and is also not counted."""
    game, p1, p2 = _hellfire(
        set_pool, ["Savannah Lions"], ["Bog Wraith", "Grizzly Bears", "Hill Giant"]
    )

    result = game.cast_from_hand(0, "Hellfire")

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Bog Wraith"], game.log
    assert p1.battlefield == []
    assert p1.life == 14, game.log


def test_the_three_is_dealt_even_when_nothing_died(set_pool):
    """"X plus 3" on an empty board is 3, not 0 — the control on folding the
    constant into the count, and on a count that silently answered zero."""
    game, p1, p2 = _hellfire(set_pool, [], ["Bog Wraith"])

    game.cast_from_hand(0, "Hellfire")

    assert [p.card.name for p in p2.battlefield] == ["Bog Wraith"]
    assert p1.life == 17, game.log


def test_the_damage_counts_the_deaths_rather_than_the_survivors(set_pool):
    """"Creatures that died this way" is the opposite set from the noun phrase
    read plainly: one nonblack creature beside two black ones is 1 + 3 = 4, and
    a count taken off the board afterwards would read 2 and deal 5."""
    game, p1, p2 = _hellfire(
        set_pool, [], ["Bog Wraith", "Scathe Zombies", "Grizzly Bears"]
    )

    game.cast_from_hand(0, "Hellfire")

    assert sorted(p.card.name for p in p2.battlefield) == [
        "Bog Wraith", "Scathe Zombies",
    ]
    assert p1.life == 16, game.log


# ---------------------------------------------------------------------------
# Winds of Change (round 21) — "each player shuffles the cards from their hand
# into their library, then draws that many cards". CR 701.19, CR 121.
# ---------------------------------------------------------------------------


def _blank(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def _winds(set_pool, first_hand: int, second_hand: int):
    p1 = PlayerState(
        name="P1",
        hand=[set_pool("LEG")["Winds of Change"]]
        + [_blank(f"A{i}") for i in range(first_hand)],
        library=[_blank(f"L{i}") for i in range(20)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[_blank(f"B{i}") for i in range(second_hand)],
        library=[_blank(f"M{i}") for i in range(20)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_every_hand_is_refilled_to_the_size_it_had(set_pool):
    """"That many" is each player's own hand size, not the caster's — two seats
    with different hands each end with what they started with."""
    game, p1, p2 = _winds(set_pool, first_hand=2, second_hand=5)

    result = game.cast_from_hand(0, "Winds of Change")
    game._settle()

    assert result.supported, result.details
    # The spell itself left the hand to go on the stack, so P1 shuffled 2.
    assert len(p1.hand) == 2, game.log
    assert len(p2.hand) == 5, game.log


def test_the_old_hands_went_into_the_libraries_rather_than_away(set_pool):
    """A shuffle-into is a move, and the cards have to still be there — a
    handler that cleared the hand and drew would pass every count above."""
    game, p1, p2 = _winds(set_pool, first_hand=2, second_hand=5)

    game.cast_from_hand(0, "Winds of Change")
    game._settle()

    everywhere = {card.name for card in p1.hand + p1.library}
    assert {"A0", "A1"} <= everywhere, game.log
    assert len(p1.library) == 20
    assert len(p2.library) == 20


def test_an_empty_hand_still_shuffles_the_library_and_draws_nothing(set_pool):
    """Zero is a number, and the shuffle is not conditional on it: the seat with
    nothing in hand shuffles its library all the same (that is the printed
    action), and draws none — the library keeps every card it had."""
    game, p1, p2 = _winds(set_pool, first_hand=0, second_hand=0)
    before = sorted(card.name for card in p2.library)

    game.cast_from_hand(0, "Winds of Change")
    game._settle()

    assert p2.hand == []
    assert sorted(card.name for card in p2.library) == before, game.log
    assert len(p2.library) == 20


# ---------------------------------------------------------------------------
# Visions (round 21) — look at the top five cards of a library you do not own,
# then offer its owner's shuffle. CR 701.19.
# ---------------------------------------------------------------------------


def _visions(set_pool, library: int = 8):
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Visions"]])
    p2 = PlayerState(name="P2", library=[_blank(f"L{i}") for i in range(library)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, p1, p2


def test_visions_shows_the_caster_the_top_five_of_the_target_s_library(set_pool):
    """The prompt is raised in front of the *caster* and reads the *target's*
    library — the two seats a look at someone else's deck can confuse."""
    game, p1, p2 = _visions(set_pool)

    result = game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    pending = game.pending_reorder_library
    assert pending is not None, game.log
    assert pending["caster_index"] == 0
    assert pending["target_index"] == 1
    assert pending["top_count"] == 5
    assert pending["may_shuffle"] is True


def test_visions_cannot_rearrange_what_it_looked_at(set_pool):
    """Visions only *looks*. The permission is enforced in the engine rather
    than by hiding the drag handles, so an answer that names another order
    leaves the library exactly as it was."""
    game, p1, p2 = _visions(set_pool)
    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()
    before = [card.name for card in p2.library]

    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0], shuffle=False)

    assert [card.name for card in p2.library] == before, game.log


def test_visions_shuffles_the_library_it_looked_at_when_the_caster_says_so(set_pool):
    """The offer is the second half of the printed sentence, and the library it
    shuffles is the target's — the caster's is untouched."""
    game, p1, p2 = _visions(set_pool)
    p1.library = [_blank(f"K{i}") for i in range(6)]
    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()
    theirs = [card.name for card in p2.library]
    mine = [card.name for card in p1.library]

    assert game.confirm_reorder_library(0, [0, 1, 2, 3, 4], shuffle=True)

    assert sorted(card.name for card in p2.library) == sorted(theirs)
    assert [card.name for card in p2.library] != theirs, game.log
    assert [card.name for card in p1.library] == mine


def test_visions_looks_at_a_short_library_without_reaching_past_it(set_pool):
    """Fewer than five cards is not a failure — the look stops at what is
    there, the way a mill does (CR 704.5b is about drawing, not looking)."""
    game, p1, p2 = _visions(set_pool, library=2)

    game.cast_from_hand(0, "Visions", target_player_index=1)
    game._settle()

    assert game.pending_reorder_library["top_count"] == 2, game.log


# ---------------------------------------------------------------------------
# Energy Tap (round 23) — "Tap target untapped creature you control. If you do,
# add an amount of {C} equal to that creature's mana value."
#
# The new piece is the third referent of the printed "an amount of {SYM} equal
# to …" shape: "that creature" is the permanent an earlier step of this same
# effect recorded, still on the battlefield, so the mana value is read off it
# at resolution instead of remembered as a number.
# ---------------------------------------------------------------------------


def _energy_tap_creature(name: str, cost: str, cmc: float):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost=cost, cmc=cmc, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


def _energy_tap_game(set_pool):
    from engine import Game, PlayerState
    from engine.models import Permanent

    mine = Permanent(card=_energy_tap_creature("Mine", "{2}{G}", 3.0))
    theirs = Permanent(card=_energy_tap_creature("Theirs", "{5}{G}", 6.0))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Energy Tap"]], battlefield=[mine]
    )
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    return game, p1, p2, mine, theirs


def test_energy_tap_taps_the_creature_and_adds_its_mana_value_in_colourless(set_pool):
    game, p1, _p2, mine, _theirs = _energy_tap_game(set_pool)

    result = game.cast_from_hand(
        0, "Energy Tap", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported is True
    assert mine.tapped is True
    # Three, not one: the amount is the creature's mana value, not the printed
    # symbol's count. A lowering that dropped the "equal to" would add {C}.
    assert p1.mana_pool.get("C", 0) == 3


def test_energy_tap_adds_nothing_when_there_was_nothing_to_tap(set_pool):
    """"If you do" is the tap's own record. With no legal target the tap
    records nothing, the branch does not run, and no mana appears — the failure
    a back-reference with no producer would otherwise hide."""
    game, p1, _p2, mine, _theirs = _energy_tap_game(set_pool)
    mine.tapped = True

    game.cast_from_hand(0, "Energy Tap", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert p1.mana_pool.get("C", 0) == 0


def test_energy_tap_will_not_tap_a_creature_its_caster_does_not_control(set_pool):
    """"…untapped creature **you control**". An unenforced narrowing is the
    quiet failure: the spell would work more often than the card allows."""
    game, p1, _p2, mine, theirs = _energy_tap_game(set_pool)

    game.cast_from_hand(0, "Energy Tap", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert theirs.tapped is False
    assert p1.mana_pool.get("C", 0) != 6


# ---------------------------------------------------------------------------
# Winter Blast (round 23) — "Tap X target creatures. Winter Blast deals 2
# damage to each of those creatures with flying."
#
# The second sentence names no targets at all: its recipients are the set the
# first sentence tapped (CR 611.2c), narrowed by a printed adjective. That
# adjective is the whole point — dropped, the spell would burn every creature
# it tapped.
# ---------------------------------------------------------------------------


def _flier(name: str):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{2}{U}", cmc=3.0, type_line="Creature - Bird",
        oracle_text="Flying", colors=("U",), color_identity=("U",),
        keywords=("Flying",), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bird",
             "power": "1", "toughness": "3"},
    )


def _winter_blast_game(set_pool):
    from engine import Game, PlayerState
    from engine.models import Permanent

    bird = Permanent(card=_flier("Bird"))
    bear = Permanent(card=_energy_tap_creature("Bear", "{1}{G}", 2.0))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Winter Blast"]])
    p2 = PlayerState(name="P2", battlefield=[bird, bear])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    return game, p1, p2, bird, bear


def test_winter_blast_taps_x_creatures_and_burns_only_the_fliers(set_pool):
    game, _p1, _p2, bird, bear = _winter_blast_game(set_pool)

    result = game.cast_from_hand(
        0, "Winter Blast", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
    )
    game._settle()

    assert result.supported is True
    assert bird.tapped is True and bear.tapped is True
    # The adjective, which is the only thing separating the two: a lowering
    # that dropped it would have dealt 2 to the Bear as well.
    assert bird.damage_marked == 2
    assert bear.damage_marked == 0


def test_winter_blast_burns_nothing_it_did_not_tap(set_pool):
    """"Those creatures" is the set the first sentence acted on, not every
    flier on the board — a flier left untapped takes nothing."""
    game, _p1, _p2, bird, bear = _winter_blast_game(set_pool)

    game.cast_from_hand(
        0, "Winter Blast", x_value=1,
        target_player_index=1, target_permanent_index=[1],
    )
    game._settle()

    assert bear.tapped is True
    assert bird.tapped is False
    assert bird.damage_marked == 0


# ---------------------------------------------------------------------------
# Typhoon (round 28) — a count taken once per recipient
# ---------------------------------------------------------------------------


def _r28_basic(subtype: str) -> CardDefinition:
    """A basic land of one type, for boards a test builds by hand."""
    line = f"Basic Land - {subtype}"
    return CardDefinition(
        name=subtype, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": subtype, "type_line": line},
    )


def _r28_typhoon_game(set_pool, islands: list[int]):
    """Seat 0 casts Typhoon; every other seat gets *islands[i]* Islands plus a
    Forest, so a count that ignored the subtype would read one too many."""
    from engine.models import Permanent

    players = []
    for seat, count in enumerate(islands):
        board = [Permanent(card=_r28_basic("Island")) for _ in range(count)]
        board.append(Permanent(card=_r28_basic("Forest")))
        players.append(PlayerState(name=f"P{seat + 1}", life=20, battlefield=board))
    players[0].hand = [set_pool("LEG")["Typhoon"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def test_typhoon_counts_each_opponents_own_islands(set_pool):
    """"…equal to the number of Islands **that player** controls" is one number
    per seat. A single X would have dealt the caster's count to everybody —
    here 5 to each, instead of 1 and 3."""
    game, players = _r28_typhoon_game(set_pool, [5, 1, 3])

    result = game.cast_from_hand(0, "Typhoon")

    assert result.supported, result.details
    assert [p.life for p in players] == [20, 19, 17], game.log


def test_typhoon_never_damages_its_caster(set_pool):
    """"Each opponent" excludes the controller, whose five Islands would
    otherwise be the biggest number on the board."""
    game, players = _r28_typhoon_game(set_pool, [5, 1, 3])

    game.cast_from_hand(0, "Typhoon")

    assert players[0].life == 20


def test_typhoon_deals_nothing_to_an_islandless_opponent(set_pool):
    """CR 120.8: a source that would deal 0 damage deals none at all."""
    game, players = _r28_typhoon_game(set_pool, [2, 0])

    game.cast_from_hand(0, "Typhoon")

    assert players[1].life == 20


# ---------------------------------------------------------------------------
# Part Water (round 28) — "X target creatures gain islandwalk until end of turn"
# ---------------------------------------------------------------------------


def _r28_vanilla(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


def _r28_part_water_game(set_pool, creatures: int):
    from engine.models import Permanent

    mine = [Permanent(card=_r28_vanilla(f"Bear{i}")) for i in range(creatures)]
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Part Water"]], battlefield=mine)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    return game, mine


def test_part_water_grants_islandwalk_to_every_chosen_creature(set_pool):
    """X is three, so the **third** creature has to have it too — the count
    arrives as the string "x" and an `isinstance(int)` test would have granted
    to the first slot alone (the rounds 23 / 27 bug class)."""
    game, mine = _r28_part_water_game(set_pool, 3)

    result = game.cast_from_hand(
        0, "Part Water", x_value=3,
        target_player_index=0, target_permanent_index=[0, 1, 2],
    )
    game._settle()

    assert result.supported is True, result.details
    assert [game._has_keyword(p, "islandwalk") for p in mine] == [True, True, True], game.log


def test_part_water_leaves_the_creatures_it_did_not_name_alone(set_pool):
    """X is one: the two unchosen creatures gain nothing."""
    game, mine = _r28_part_water_game(set_pool, 3)

    game.cast_from_hand(
        0, "Part Water", x_value=1,
        target_player_index=0, target_permanent_index=[1],
    )
    game._settle()

    assert [game._has_keyword(p, "islandwalk") for p in mine] == [False, True, False]


def test_part_water_tells_the_picker_its_count_is_the_announced_x(set_pool):
    """The cast spec has to *say* the count is X, or the browser picker falls
    back to its one-target default and names a single creature for an announced
    X of five — which is what Winter Blast did until this flag existed. There is
    no number to report here (X is announced, not printed), so it is a flag."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    for name in ("Part Water", "Winter Blast"):
        card = set_pool("LEG")[name]
        spec = derive_cast_spec(card, compile_card_oracle(card))
        assert spec == {"kind": "creature", "x_targets": True}, name


# ---------------------------------------------------------------------------
# Recall (round 29) — a discard whose answer is the next step's number
# ---------------------------------------------------------------------------
#
# The card the suspending discard unlocks. "Discard X cards, then return a card
# from your graveyard to your hand for each card discarded this way. Exile
# Recall." is three ordinary instructions in a `sequence`: nothing is fused, and
# the number the second step works from is the answer to the first step's
# prompt (CR 608.2 — the resolution is not over until its last instruction is
# done, so nothing behind the prompt may run before it is answered).


def _r29_recall_game(set_pool, *, hand_extra, graveyard, interactive=(0, 1)):
    """A duel with Recall in P1's hand, plus the cards each half of it needs."""
    pool = set_pool("LEG")
    from tests.helpers import CARDS_BY_NAME

    def _card(name):
        return pool.get(name) or CARDS_BY_NAME[name]

    p1 = PlayerState(
        name="P1",
        hand=[pool["Recall"]] + [_card(n) for n in hand_extra],
        graveyard=[_card(n) for n in graveyard],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    return game, p1, p2


def _r29_cast_recall(game, x_value):
    assert game._cast_onto_stack(0, "Recall", x_value=x_value).supported
    game.priority_player_index = 0
    game.pass_priority(0)
    return game.pass_priority(1)


def test_recall_holds_its_resolution_open_while_the_discard_is_owed(set_pool):
    """The return must not run against the graveyard the discard has not filled
    yet, and the card must not be in exile while the prompt is still on screen
    (CR 608.2n)."""
    game, p1, _p2 = _r29_recall_game(
        set_pool, hand_extra=["Giant Growth", "Healing Salve"], graveyard=["Black Lotus"]
    )

    assert _r29_cast_recall(game, 2) == "awaiting_choice"

    assert [c.kind for c in game.pending_choices] == ["discard"]
    assert [(i.card.name, i.resolution_held) for i in game.stack] == [("Recall", True)]
    assert p1.exile == []
    assert [c.name for c in p1.graveyard] == ["Black Lotus"]


def test_recall_returns_one_card_for_each_card_actually_discarded(set_pool):
    """Two discarded, two returned — and the cards just discarded are legal
    picks, because by then they are in the graveyard."""
    game, p1, _p2 = _r29_recall_game(
        set_pool,
        hand_extra=["Giant Growth", "Healing Salve"],
        graveyard=["Black Lotus", "Mox Ruby"],
    )
    _r29_cast_recall(game, 2)

    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1], to_library=False
    )
    # The next step of the same resolution asks which cards come back.
    choice = game.pending_choices[0]
    assert choice.kind == "search_library"
    assert choice.data["zones"] == ("graveyard",)
    assert len(choice.data["destinations"]) == 2

    assert game.resolve_pending_choice(
        "search_library", 0,
        picks=[{"zone": "graveyard", "index": 0}, {"zone": "graveyard", "index": 1}],
    )

    assert [c.name for c in p1.hand] == ["Black Lotus", "Mox Ruby"]
    assert game.pending_choices == []
    assert game.resume_stack == []


def test_recall_exiles_itself_instead_of_going_to_the_graveyard(set_pool):
    """"Exile Recall." is the last step of the sequence, so it runs after the
    resumption — and CR 608.2n's move is the one that honours it."""
    game, p1, _p2 = _r29_recall_game(
        set_pool, hand_extra=["Giant Growth"], graveyard=["Black Lotus"]
    )
    _r29_cast_recall(game, 1)
    game.resolve_pending_choice("discard", 0, hand_indices=[0], to_library=False)
    # One card to return is the *single-find* spelling of the same prompt — the
    # counted answer is for two slots or more (see `_resolve_search_library`).
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="graveyard"
    )

    assert [c.name for c in p1.exile] == ["Recall"]
    assert "Recall" not in [c.name for c in p1.graveyard]
    assert game.stack == []


def test_recall_for_zero_returns_nothing_and_still_exiles_itself(set_pool):
    """X=0 discards nothing, so "for each card discarded this way" is zero —
    not "one", and not the whole graveyard."""
    game, p1, _p2 = _r29_recall_game(
        set_pool, hand_extra=["Giant Growth"], graveyard=["Black Lotus", "Mox Ruby"]
    )

    _r29_cast_recall(game, 0)

    assert game.pending_choices == []
    assert [c.name for c in p1.hand] == ["Giant Growth"]
    assert [c.name for c in p1.graveyard] == ["Black Lotus", "Mox Ruby"]
    assert [c.name for c in p1.exile] == ["Recall"]


def test_a_non_interactive_seat_answers_both_prompts_and_finishes(set_pool):
    """A suspending prompt nobody answers is a hang, not a test failure: the
    AI drain has to carry the whole resolution through both of Recall's."""
    game, p1, _p2 = _r29_recall_game(
        set_pool,
        hand_extra=["Giant Growth", "Healing Salve"],
        graveyard=["Black Lotus"],
        interactive=(),
    )

    _r29_cast_recall(game, 1)
    for _ in range(6):
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()

    assert game.pending_choices == []
    assert game.stack == []
    assert game.resume_stack == []
    assert game.effect_suspended is False
    assert len(p1.hand) == 2
    assert [c.name for c in p1.exile] == ["Recall"]


# ---------------------------------------------------------------------------
# Falling Star (round 31) — a CR 104.1 flip, simulated
# ---------------------------------------------------------------------------
#
# The card asks a player to flip it onto a table from a height of at least one
# foot. There is no table, so ``engine/dexterity.py`` substitutes a random
# landing on one to three creatures; these tests pin what the substitution is
# allowed to do, not where any particular flip lands. Seeded where a specific
# landing is needed, because the module-level RNG is what
# ``run_ai_simulation`` seeds.


def _r31_sized(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _r31_falling_star(set_pool, board: list[tuple[str, int, int]], *, seats: int = 2):
    """Seat 0 casts Falling Star; *board* is split evenly across the seats, so
    the flip can land on either side — it is not "target creature an opponent
    controls"."""
    from engine.models import Permanent

    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    for i, (name, power, toughness) in enumerate(board):
        players[i % seats].battlefield.append(
            Permanent(card=_r31_sized(name, power, toughness))
        )
    players[0].hand = [set_pool("LEG")["Falling Star"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def _r31_all_creatures(players):
    return [perm for p in players for perm in p.battlefield]


def test_falling_star_lands_on_between_one_and_three_creatures(set_pool):
    """The substitution's whole contract. Run over many seeds rather than one,
    because a single flip cannot distinguish "one to three" from "always two"."""
    import random

    sizes = set()
    for seed in range(40):
        random.seed(seed)
        game, players = _r31_falling_star(
            set_pool, [(f"Bear {i}", 2, 4) for i in range(6)]
        )
        result = game.cast_from_hand(0, "Falling Star")
        assert result.supported, result.details
        hit = [p for p in _r31_all_creatures(players) if p.damage_marked > 0]
        sizes.add(len(hit))

    assert sizes and sizes <= {1, 2, 3}, sizes
    assert sizes == {1, 2, 3}, f"the count should vary across seeds, saw {sizes}"


def test_falling_star_deals_three_and_taps_what_it_hit(set_pool):
    """"deals 3 damage to each creature it lands on. Tap all creatures dealt
    damage by Falling Star." Both halves, and only to what it hit — a creature
    it missed is undamaged *and* untapped."""
    import random

    random.seed(0)
    game, players = _r31_falling_star(
        set_pool, [(f"Bear {i}", 2, 4) for i in range(6)]
    )

    result = game.cast_from_hand(0, "Falling Star")

    assert result.supported, result.details
    hit = [p for p in _r31_all_creatures(players) if p.damage_marked > 0]
    missed = [p for p in _r31_all_creatures(players) if p.damage_marked == 0]
    assert hit, game.log
    assert all(p.damage_marked == 3 for p in hit), [p.damage_marked for p in hit]
    assert all(p.tapped for p in hit), game.log
    assert all(not p.tapped for p in missed), game.log


def test_falling_star_can_land_on_its_casters_own_creatures(set_pool):
    """"each creature it lands on" is every creature on the table. A flip that
    only ever hit the opponent would be a different, much better card."""
    import random

    seats_hit = set()
    for seed in range(40):
        random.seed(seed)
        game, players = _r31_falling_star(
            set_pool, [(f"Bear {i}", 2, 4) for i in range(6)]
        )
        game.cast_from_hand(0, "Falling Star")
        for seat, player in enumerate(players):
            if any(p.damage_marked > 0 for p in player.battlefield):
                seats_hit.add(seat)

    assert seats_hit == {0, 1}, seats_hit


def test_falling_star_kills_what_it_lands_on_when_the_damage_is_lethal(set_pool):
    """Death is the state-based sweep's job, not the handler's (CR 704.5g), so
    a 2/2 hit for 3 is gone by the time the spell has resolved."""
    import random

    random.seed(0)
    game, players = _r31_falling_star(
        set_pool, [(f"Bear {i}", 2, 2) for i in range(6)]
    )
    before = len(_r31_all_creatures(players))

    game.cast_from_hand(0, "Falling Star")

    assert len(_r31_all_creatures(players)) < before, game.log


def test_falling_star_on_an_empty_board_resolves_and_does_nothing(set_pool):
    """A flip with nothing to land on is not an error — the minimum of one is
    clamped to what is actually there."""
    game, players = _r31_falling_star(set_pool, [])

    result = game.cast_from_hand(0, "Falling Star")

    assert result.supported, result.details
    assert all(p.life == 20 for p in players), game.log


# ---------------------------------------------------------------------------
# Juxtapose (round 31) — an exchange whose two sides are chosen, not targeted
# ---------------------------------------------------------------------------


def _r31_jx_game(set_pool, catalog_by_name, first_board, second_board, copies=1):
    """A two-seat board with Juxtapose in hand and the named permanents in play.

    The permanents go on through ``_put_permanent_onto_battlefield`` rather than
    onto the list, so each one records the ``base_controller_index`` a layer-2
    contribution is measured against.
    """
    players = [PlayerState(name="P1"), PlayerState(name="P2")]
    players[0].hand = [set_pool("LEG")["Juxtapose"]] * copies
    game = Game(players=players)
    game.enforce_mana_costs = False
    for seat, names in ((0, first_board), (1, second_board)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=catalog_by_name[name]), None
            )
    return game, players


def _r31_jx_names(game):
    return [[perm.card.name for perm in player.battlefield] for player in game.players]


def test_juxtapose_exchanges_the_greatest_creature_and_then_the_greatest_artifact(
    set_pool, catalog_by_name
):
    """Both halves happen, and each picks the greatest mana value on its own
    side. Hill Giant (4) is P1's greatest creature even though it is not their
    only one, and Mox Pearl is their only artifact."""
    game, _ = _r31_jx_game(
        set_pool, catalog_by_name,
        ["Grizzly Bears", "Hill Giant", "Mox Pearl"],
        ["Scryb Sprites", "Craw Wurm", "Black Lotus", "Icy Manipulator"],
    )

    result = game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    assert result.supported, result.details
    first, second = _r31_jx_names(game)
    assert sorted(first) == sorted(["Grizzly Bears", "Craw Wurm", "Icy Manipulator"])
    assert sorted(second) == sorted(
        ["Scryb Sprites", "Black Lotus", "Hill Giant", "Mox Pearl"]
    ), game.log


def test_a_second_juxtapose_is_unaffected_by_the_first(set_pool, catalog_by_name):
    """The layer-2 contributions are keyed on the *instruction*, not on the
    card, and one cast makes two of them. Keyed on the shared
    ``CardDefinition`` the second exchange of a cast would drop the first
    (``change_control`` keeps one contribution per source), and a second cast
    would then read a board the first had half-recorded. Cast twice, the boards
    swap back and forth exactly."""
    game, _ = _r31_jx_game(
        set_pool, catalog_by_name,
        ["Grizzly Bears", "Hill Giant", "Mox Pearl"],
        ["Scryb Sprites", "Craw Wurm", "Black Lotus", "Icy Manipulator"],
        copies=2,
    )
    game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    first, second = _r31_jx_names(game)
    # Hill Giant is home again; the artifacts traded the other way this time,
    # because the greatest artifact on each side changed hands in the first cast.
    assert "Hill Giant" in first and "Craw Wurm" in second, game.log
    assert "Black Lotus" in first and "Icy Manipulator" in second, game.log


def test_a_side_with_no_permanent_of_that_type_exchanges_nothing_of_it(
    set_pool, catalog_by_name
):
    """CR 701.12a: an exchange one side cannot supply does not happen at all —
    and the *other* type's exchange still does. Half an exchange is a gift."""
    game, _ = _r31_jx_game(
        set_pool, catalog_by_name, ["Grizzly Bears"], ["Craw Wurm", "Black Lotus"]
    )

    game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    first, second = _r31_jx_names(game)
    assert first == ["Craw Wurm"], game.log
    assert sorted(second) == sorted(["Black Lotus", "Grizzly Bears"]), game.log


def test_a_tie_for_greatest_is_broken_by_that_permanents_controller(
    set_pool, catalog_by_name
):
    """"If two or more permanents a player controls are tied for greatest,
    their controller chooses one of them." Black Lotus and Mox Pearl are both
    mana value 0, so the seat holding them picks — a ``permanent_choice``,
    whose non-interactive default is the first live candidate."""
    game, _ = _r31_jx_game(
        set_pool, catalog_by_name,
        ["Icy Manipulator"], ["Black Lotus", "Mox Pearl"],
    )

    game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    first, second = _r31_jx_names(game)
    assert first == ["Black Lotus"], game.log
    assert sorted(second) == sorted(["Mox Pearl", "Icy Manipulator"]), game.log
    assert any("chose Black Lotus" in line for line in game.log), game.log


def test_one_permanent_greatest_in_both_halves_is_exchanged_twice(
    set_pool, catalog_by_name
):
    """An artifact creature is the greatest of both types, so it is exchanged
    and then exchanged back — which is only right if *both* contributions
    survive. One dropped by the other would leave it on the wrong side."""
    game, _ = _r31_jx_game(
        set_pool, catalog_by_name, ["Clockwork Avian"], ["Clay Statue"]
    )

    game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    assert _r31_jx_names(game) == [["Clockwork Avian"], ["Clay Statue"]], game.log


def test_juxtapose_on_an_empty_board_resolves_and_does_nothing(
    set_pool, catalog_by_name
):
    game, players = _r31_jx_game(set_pool, catalog_by_name, [], [])

    result = game.cast_from_hand(0, "Juxtapose", target_player_index=1)

    assert result.supported, result.details
    assert _r31_jx_names(game) == [[], []], game.log


# ---------------------------------------------------------------------------
# Rebirth (round 32) — "Each player may ante the top card of their library.
# If a player does, that player's life total becomes 20."
#
# The card the round-32 refusal removal unlocked. It is the first spell in the
# pool whose *whole* effect is an offer, and the first offer the pool makes to
# more than one seat at once — so each seat gets its own prompt, each answers
# for itself, and the spell stays on the stack until the last of them has.
# ---------------------------------------------------------------------------


def _r32_rebirth_game(set_pool, *, seats: int = 2, lives=None, libraries=None):
    pool = set_pool("LEG")
    players = []
    for i in range(seats):
        size = 3 if libraries is None else libraries[i]
        players.append(
            PlayerState(
                name=f"P{i + 1}",
                life=20 if lives is None else lives[i],
                library=[
                    _mk_card(f"P{i + 1}Card{n}", "Instant", "")
                    for n in range(size)
                ],
            )
        )
    players[0].hand = [pool["Rebirth"]]
    game = Game(players=players, playing_for_ante=True)
    game.enforce_mana_costs = False
    return game, players


def test_rebirth_offers_every_seat_its_own_decision(set_pool):
    """One prompt per player, not one the caster answers for everybody."""
    game, players = _r32_rebirth_game(set_pool, seats=3)

    result = game.cast_from_hand(0, "Rebirth")

    assert result.supported, result.details
    assert sorted(e["player_index"] for e in game.pending_optional_pays) == [0, 1, 2]
    assert all(p.ante == [] for p in players), "nothing happens before the answers"


def test_a_seat_that_accepts_antes_its_own_card_and_goes_to_twenty(set_pool):
    """"That player" is the seat that took the offer — the ante comes off that
    player's own library (CR 407.4) and the life total is that player's."""
    game, players = _r32_rebirth_game(set_pool, lives=[5, 5])

    game.cast_from_hand(0, "Rebirth")
    assert game.confirm_optional_pay(1, accept=True)

    assert [c.name for c in players[1].ante] == ["P2Card0"]
    assert players[1].life == 20
    assert players[0].ante == [] and players[0].life == 5, game.log


def test_a_seat_that_declines_antes_nothing_and_keeps_its_life_total(set_pool):
    game, players = _r32_rebirth_game(set_pool, lives=[30, 30])

    game.cast_from_hand(0, "Rebirth")
    assert game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=True)

    assert players[0].ante == [] and players[0].life == 30
    assert [c.name for c in players[1].ante] == ["P2Card0"]
    # CR 119.5: setting a total above 20 is a *loss* of the difference.
    assert players[1].life == 20, game.log


def test_an_empty_library_is_never_offered_the_ante(set_pool):
    """No top card means no ante to take, and taking the offer anyway would
    hand a player 20 life for an ante that never happened."""
    game, players = _r32_rebirth_game(set_pool, lives=[5, 5], libraries=[3, 0])

    game.cast_from_hand(0, "Rebirth")

    assert [e["player_index"] for e in game.pending_optional_pays] == [0]
    assert players[1].life == 5, game.log


def test_rebirth_holds_the_stack_until_the_last_seat_has_answered(set_pool):
    """CR 608.2 / CR 117.3b: the spell is still resolving while it owes anybody
    a decision, so it stays on the stack and nobody receives priority."""
    game, _ = _r32_rebirth_game(set_pool)
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    assert game.queue_from_hand(0, "Rebirth").supported
    game.start_priority_window(0)

    game.pass_priority(0)
    assert game.pass_priority(1) == "awaiting_choice"

    assert [item.card.name for item in game.stack] == ["Rebirth"]
    assert game.waiting_prompt() is not None
    game.confirm_optional_pay(0, accept=True)
    assert len(game.stack) == 1, "one seat still owes an answer"
    game.confirm_optional_pay(1, accept=False)
    assert game.stack == []
    assert game.waiting_prompt() is None


# ---------------------------------------------------------------------------
# Eureka (round 33) — a round of offers, repeated until nobody takes one
# ---------------------------------------------------------------------------


def _r33_eureka(set_pool, catalog_by_name, hands: list[list[str]], interactive=()):
    """Eureka in seat 0's hand, with each seat holding the named cards."""
    pool = set_pool("LEG")
    players = []
    for index, names in enumerate(hands):
        hand = [catalog_by_name[name] for name in names]
        if index == 0:
            hand = [pool["Eureka"], *hand]
        players.append(
            PlayerState(name=f"P{index + 1}", hand=hand, library=[_mk_card("Filler", "Sorcery")])
        )
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, players


def _r33_names(player) -> list[str]:
    return [permanent.card.name for permanent in player.battlefield]


def test_eureka_empties_every_hand_of_permanents_a_round_at_a_time(set_pool, catalog_by_name):
    """The whole spell against seats that always take the offer.

    Each round is one card per seat, in turn order, and the process repeats
    while anybody is still putting cards down — so two cards in one hand take
    two rounds, not one.
    """
    game, players = _r33_eureka(
        set_pool, catalog_by_name,
        [["Shivan Dragon", "Black Lotus"], ["Serra Angel", "Wall of Stone"]],
    )

    result = game.cast_from_hand(0, "Eureka")

    assert result.supported, result.details
    assert _r33_names(players[0]) == ["Shivan Dragon", "Black Lotus"]
    assert _r33_names(players[1]) == ["Serra Angel", "Wall of Stone"]
    assert players[0].hand == [] and players[1].hand == []
    # Turn order, one card each, twice — not one seat's whole hand and then the
    # other's, which is what a loop per seat rather than a round would give.
    puts = [line for line in game.log if line.endswith("(Eureka)")]
    assert [line.split()[0] for line in puts] == ["P1", "P2", "P1", "P2"], game.log


def test_eureka_leaves_a_nonpermanent_card_in_hand(set_pool, catalog_by_name):
    """"A **permanent** card" is the narrowing, and it is tested rather than
    dropped: a sorcery in hand is never a candidate, so a seat holding nothing
    else is simply never offered anything."""
    game, players = _r33_eureka(
        set_pool, catalog_by_name, [["Shivan Dragon"], ["Lightning Bolt"]],
    )

    game.cast_from_hand(0, "Eureka")

    assert _r33_names(players[1]) == []
    assert [card.name for card in players[1].hand] == ["Lightning Bolt"]


def test_eureka_waits_on_an_interactive_seat_and_answers_both_ways(set_pool, catalog_by_name):
    """The round genuinely stops for a human seat, and both answers are real:
    the first offer is taken, the second declined, and the declining seat keeps
    its card."""
    game, players = _r33_eureka(
        set_pool, catalog_by_name,
        [["Shivan Dragon"], ["Serra Angel"]], interactive={0, 1},
    )

    game.cast_from_hand(0, "Eureka")
    game.resolve_stack()

    first = game.pending_choices[0]
    assert first.kind == "put_from_hand_choice" and first.player_index == 0
    assert game.waiting_prompt() is not None, "the resolution has to wait on the offer"
    game.confirm_put_from_hand_choice(0, game.live_put_from_hand_choices(first)[0])

    # Seat 1 owes the same round's second offer, and the game still waits.
    second = game.pending_choices[0]
    assert second.player_index == 1
    assert game.waiting_prompt() is not None, "a second seat's offer holds the resolution too"
    assert game.confirm_put_from_hand_choice(1, None)

    # Seat 0 took one, so the process repeats — and this time it has nothing
    # left, which ends it.
    while game.pending_choices:
        choice = game.pending_choices[0]
        assert game.confirm_put_from_hand_choice(choice.player_index, None)

    assert _r33_names(players[0]) == ["Shivan Dragon"]
    assert _r33_names(players[1]) == []
    assert [card.name for card in players[1].hand] == ["Serra Angel"]
    assert game.waiting_prompt() is None


def test_eureka_starts_with_its_caster(set_pool, catalog_by_name):
    """"Starting with you" names the first seat asked. Three seats, so the order
    is visible rather than a coincidence of there being two."""
    game, players = _r33_eureka(
        set_pool, catalog_by_name,
        [["Shivan Dragon"], ["Serra Angel"], ["Wall of Stone"]],
    )

    game.cast_from_hand(0, "Eureka")

    puts = [line.split()[0] for line in game.log if line.endswith("(Eureka)")]
    assert puts == ["P1", "P2", "P3"], game.log


# ---------------------------------------------------------------------------
# All Hallow's Eve (round 36) — a sorcery that keeps working from exile
# ---------------------------------------------------------------------------


def _r36_eve(set_pool, catalog_by_name, graveyards, copies=1):
    """A duel with All Hallow's Eve in hand and named creature cards in each
    graveyard."""
    players = [
        PlayerState(
            name=f"P{seat + 1}",
            life=20,
            graveyard=[catalog_by_name[name] for name in names],
            library=[catalog_by_name["Swamp"]] * 10,
        )
        for seat, names in enumerate(graveyards)
    ]
    players[0].hand = [set_pool("LEG")["All Hallow's Eve"]] * copies
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, players


def _r36_creatures(player):
    return sorted(
        perm.card.name for perm in player.battlefield if perm.card.name != "Swamp"
    )


def test_all_hallows_eve_leaves_the_stack_carrying_its_counters(
    set_pool, catalog_by_name
):
    """"Exile All Hallow's Eve **with two scream counters on it**." A card in
    exile is a bare CardDefinition shared by every copy in the catalog, so the
    counters live in the game's exile register — and the rider is read rather
    than shed, which is the whole card."""
    game, players = _r36_eve(set_pool, catalog_by_name, [[], []])

    assert game.cast_from_hand(0, "All Hallow's Eve").supported
    game.resolve_stack()

    assert [card.name for card in players[0].exile] == ["All Hallow's Eve"]
    assert [record.metadata for record in game.exiled_records] == [
        {"scream_counters": 2}
    ]


def test_the_upkeep_trigger_fires_from_exile_one_counter_at_a_time(
    set_pool, catalog_by_name
):
    """The trigger's source is in exile, where there is no permanent to scan —
    and it is "at the beginning of **your** upkeep", so the opponent's turn
    does not move it along."""
    game, players = _r36_eve(set_pool, catalog_by_name, [["Grizzly Bears"], []])
    game.cast_from_hand(0, "All Hallow's Eve")
    game.resolve_stack()

    counters = []
    for _ in range(3):
        game.start_next_turn()
        game.resolve_stack()
        # Copied: the record's metadata is a live dict, and appending the
        # object itself would make every snapshot read as the last one.
        counters.append([dict(record.metadata) for record in game.exiled_records])

    # Opponent's turn, then the controller's — one removal, not two.
    assert counters[0] == [{"scream_counters": 2}]
    assert counters[1] == [{"scream_counters": 1}]
    assert counters[2] == [{"scream_counters": 1}]


def test_the_last_counter_bins_the_card_and_refills_both_graveyards(
    set_pool, catalog_by_name
):
    """"If there are no more scream counters on it, put it into your graveyard
    and **each player** returns all creature cards from their graveyard to the
    battlefield." Each player's own creatures, under their own control — read
    without its subject the sweep would hand the table's graveyards to whoever's
    upkeep it was."""
    game, players = _r36_eve(
        set_pool, catalog_by_name,
        [["Grizzly Bears", "Lightning Bolt"], ["Savannah Lions"]],
    )
    game.cast_from_hand(0, "All Hallow's Eve")
    game.resolve_stack()

    for _ in range(4):
        game.start_next_turn()
        game.resolve_stack()

    assert _r36_creatures(players[0]) == ["Grizzly Bears"]
    assert _r36_creatures(players[1]) == ["Savannah Lions"]
    # The noncreature card stays put, and the sorcery itself lands in the
    # graveyard rather than staying in exile forever.
    assert [card.name for card in players[0].graveyard] == [
        "Lightning Bolt", "All Hallow's Eve",
    ]
    assert players[0].exile == []
    assert game.exiled_records == []


def test_nothing_happens_on_the_upkeep_before_the_last_counter(
    set_pool, catalog_by_name
):
    """The reanimation is inside "if there are no more scream counters on it",
    so the first upkeep removes a counter and does nothing else. A card that
    reanimated on every upkeep would pass the test above."""
    game, players = _r36_eve(set_pool, catalog_by_name, [["Grizzly Bears"], []])
    game.cast_from_hand(0, "All Hallow's Eve")
    game.resolve_stack()

    for _ in range(2):  # the opponent's turn, then the first of the caster's
        game.start_next_turn()
        game.resolve_stack()

    assert _r36_creatures(players[0]) == []
    assert [card.name for card in players[0].graveyard] == ["Grizzly Bears"]


def test_two_copies_in_one_game_keep_their_own_counters(
    set_pool, catalog_by_name
):
    """Two copies of a card are the *same* CardDefinition, so a register keyed
    on the card would merge their counters and take both off with one removal.
    The second copy, cast a turn later, is a turn behind all the way down."""
    game, players = _r36_eve(set_pool, catalog_by_name, [[], []], copies=2)
    game.cast_from_hand(0, "All Hallow's Eve")
    game.resolve_stack()

    game.start_next_turn()  # the opponent's
    game.resolve_stack()
    game.start_next_turn()  # the caster's: the first copy loses a counter
    game.resolve_stack()
    game.cast_from_hand(0, "All Hallow's Eve")
    game.resolve_stack()

    assert [record.metadata for record in game.exiled_records] == [
        {"scream_counters": 1}, {"scream_counters": 2},
    ]

    game.start_next_turn()
    game.resolve_stack()
    game.start_next_turn()  # the caster's again
    game.resolve_stack()

    # The first copy is spent and gone; the second still has one to go.
    assert [record.metadata for record in game.exiled_records] == [
        {"scream_counters": 1}
    ]
    assert [card.name for card in players[0].exile] == ["All Hallow's Eve"]

# Chain Lightning (round 36) — the copy the *damaged* seat pays for and re-aims
# ---------------------------------------------------------------------------


def _r36_chain(set_pool, catalog_by_name, interactive=None):
    """P1 holds Chain Lightning and a Serra Angel; P2 has a Grizzly Bears to be
    shot and two Mountains to pay with.

    The Mountains matter: the offer is made mid-resolution, so its player never
    gets a priority window to make mana — the payment has to come off the board
    (``engine/mana_payment.py``), and untapped lands are the only way to tell
    that it did.
    """
    leg = set_pool("LEG")
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    p1.hand = [leg["Chain Lightning"]]
    p1.battlefield = [Permanent(card=catalog_by_name["Serra Angel"])]
    p2.battlefield = [
        Permanent(card=catalog_by_name["Grizzly Bears"]),
        Permanent(card=catalog_by_name["Mountain"]),
        Permanent(card=catalog_by_name["Mountain"]),
    ]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive is not None:
        game.interactive_seats = interactive
    return game, [p1, p2]


def _r36_mountains(player):
    return [perm for perm in player.battlefield if perm.card.name == "Mountain"]


def test_chain_lightning_deals_its_three_and_offers_the_damaged_seat_the_copy(
    set_pool, catalog_by_name
):
    """The whole card in one pass: shot at an opponent's creature, that
    creature's *controller* is the one offered the {R}{R}."""
    game, players = _r36_chain(set_pool, catalog_by_name, interactive={1})

    result = game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert any("dealt 3 damage to Grizzly Bears" in line for line in game.log), game.log
    offer = game.pending_choice_of("optional_pay", 1)
    assert offer is not None, "the damaged permanent's controller is the payer"
    assert offer.data["cost"] == {"R": 2}


def test_the_payment_taps_the_payers_lands(set_pool, catalog_by_name):
    """"You may pay" inside a resolution gives its player no priority window, so
    an unpaid pool is not the answer — ``plan_payment`` collects from the board.
    The payer is the *opponent*, so a payment that came off the caster's side
    would be invisible in a life total and obvious here."""
    game, players = _r36_chain(set_pool, catalog_by_name, interactive={1})
    game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )

    assert game.confirm_optional_pay(1, accept=True) is True

    assert [perm.tapped for perm in _r36_mountains(players[1])] == [True, True]


def test_the_copy_is_controlled_by_the_payer_and_can_be_aimed_back(
    set_pool, catalog_by_name
):
    """**The test this round exists for.** The copy belongs to the seat that
    paid — not to the caster — and CR 707.10's re-aiming sends it at the caster's
    face for the 3 damage the original never threatened."""
    game, players = _r36_chain(set_pool, catalog_by_name, interactive={1})
    game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )
    game.confirm_optional_pay(1, accept=True)
    assert game.confirm_optional_pay(1, accept=True) is True

    copy = game.stack[-1]
    assert copy.is_copy and copy.caster_index == 1, "the payer controls the copy"

    assert game.confirm_copy_spell_target(1, target_seat=0) is True
    game.resolve_top_of_stack()

    assert players[0].life == 17, game.log
    assert players[1].life == 20, game.log


def test_the_copy_can_be_aimed_at_a_permanent_instead(set_pool, catalog_by_name):
    """"Any target" is a player *or* a permanent (CR 115.4), and both are offered
    — a picker that could only answer with a face would make half the card
    unreachable."""
    game, players = _r36_chain(set_pool, catalog_by_name, interactive={1})
    game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )
    game.confirm_optional_pay(1, accept=True)
    game.confirm_optional_pay(1, accept=True)

    angel = players[0].battlefield[0]
    assert game.confirm_copy_spell_target(1, permanent_id=angel.permanent_id) is True
    game.resolve_top_of_stack()

    assert players[0].life == 20
    assert any("damage to Serra Angel" in line for line in game.log), game.log


def test_declining_the_payment_taps_nothing_and_makes_no_copy(
    set_pool, catalog_by_name
):
    """The offer is optional in both directions; a decline has no consequence
    printed, so nothing at all should have happened to the payer."""
    game, players = _r36_chain(set_pool, catalog_by_name, interactive={1})
    game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )

    assert game.confirm_optional_pay(1, accept=False) is True

    assert game.stack == []
    assert game.pending_choices == []
    assert [perm.tapped for perm in _r36_mountains(players[1])] == [False, False]


def test_a_non_interactive_payer_answers_every_prompt_itself(
    set_pool, catalog_by_name
):
    """A prompt an AI never answers is a hang, not a failing assertion. The
    stated default for the payment is to spend mana already floating and never
    tap a land for an optional cost, so a seat with two untapped Mountains and
    an empty pool declines — and the drain leaves nothing behind.
    """
    game, players = _r36_chain(set_pool, catalog_by_name)

    result = game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )
    game.auto_resolve_pending_choices()

    assert result.supported, result.details
    assert game.pending_choices == []
    assert game.stack == []
    assert players[0].life == 20


def test_a_non_interactive_payer_with_floating_mana_keeps_the_original_target(
    set_pool, catalog_by_name
):
    """With the mana already floating the default pays — and the copy's target
    default is the one answer that changes nothing (CR 707.10's offer is
    optional, so declining is a real answer and it is this one).

    Aimed at a 4/4 that survives the first 3 damage, so "kept" is observable:
    the copy lands on the same creature and finishes it.
    """
    leg = set_pool("LEG")
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    p1.hand = [leg["Chain Lightning"]]
    p2.battlefield = [Permanent(card=catalog_by_name["Serra Angel"])]
    p2.mana_pool["R"] = 2
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Chain Lightning", target_player_index=1, target_permanent_index=0
    )
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.check_state_based_actions()

    assert p2.mana_pool.get("R", 0) == 0, "the floating mana was spent"
    assert p1.life == 20, "the default is to keep the target, not to re-aim"
    assert p2.battlefield == [], game.log


# ---------------------------------------------------------------------------
# Psychic Purge (Phase 4 parse-coverage round) — a trigger that works from hand
# ---------------------------------------------------------------------------


def _purge_game(set_pool, catalog_by_name, discard_spell: str):
    """P1 casts *discard_spell* at P2, who holds nothing but Psychic Purge."""
    filler = [_mk_card("Filler")] * 20
    game = Game(players=[
        PlayerState(name="P1", library=list(filler)),
        PlayerState(name="P2", library=list(filler),
                    hand=[set_pool("LEG")["Psychic Purge"]]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.players[0].hand.append(catalog_by_name[discard_spell])
    assert game.queue_from_hand(0, discard_spell, target_player_index=1).supported
    game._settle()
    for _ in range(6):
        if not game.pending_choices:
            break
        game.take_choice_default(game.pending_choices[0])
        game._settle()
    return game


def test_psychic_purge_punishes_the_opponent_who_made_you_discard_it(
    set_pool, catalog_by_name
):
    """"When a spell or ability an opponent controls causes you to discard this
    card, that player loses 5 life." (CR 113.6: a *sorcery* whose ability would
    otherwise function only on the stack, and whose trigger condition can be met
    only in a hand — not CR 113.6d, which is about a modified cost to cast.)

    Nothing announced it before this round — the condition parsed on neither
    front end, so the card was a 1-damage sorcery with a dead second line. The
    announcement lives at the discard seam because that is the only place the
    card being discarded is in view; nothing on the battlefield carries the
    ability, so no board scan would ever find it.
    """
    game = _purge_game(set_pool, catalog_by_name, "Mind Rot")
    assert [c.name for c in game.players[1].graveyard] == ["Psychic Purge"]
    assert game.players[0].life == 15


def test_psychic_purge_stays_quiet_when_you_discard_it_yourself(
    set_pool, catalog_by_name
):
    """"A spell or ability **an opponent controls**" is the whole condition. A
    cleanup-step discard is caused by no spell at all, so the seat that armed
    the discard is nobody and the trigger must not fire — a trigger that fired
    on any discard would drain its own controller."""
    game = Game(players=[
        PlayerState(name="P1"),
        PlayerState(name="P2", hand=[set_pool("LEG")["Psychic Purge"]]),
    ])
    game.enforce_mana_costs = False
    game._discard_card(game.players[1], game.players[1].hand.pop())
    game._settle()
    assert game.players[0].life == 20
    assert game.players[1].life == 20


# --- FixC: a sweep names a class, not a target ---
def _fixc_game(spell, theirs=()):
    """*spell* in seat 0's hand and *theirs* on seat 1's battlefield."""
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p1, p2


def test_cleanse_and_hellfire_name_a_class_and_choose_nobody(set_pool):
    """"Destroy all black creatures" / "destroy all nonblack creatures" —
    CR 115.1a makes a sorcery targeted only where its ability says "target",
    and neither does.

    Both compiled to a sweep whose ``type_filter`` says which creatures it
    affects, and the target derivation read that filter as a picker's: Cleanse
    reported "target creature", so the browser raised a creature prompt and
    **abandoned the cast** when no creature was in play.
    """
    pool = set_pool("LEG")
    for name in ("Cleanse", "Hellfire"):
        game, _p1, _p2 = _fixc_game(pool[name])

        assert game.cast_target_spec(0, pool[name]) == {
            "kind": "none", "requires_target": False, "valid_targets": [],
        }, name


def test_cleanse_sweeps_the_black_creatures_with_nothing_named(set_pool):
    """The colour is the sweep's own description, applied to every creature —
    not a narrowing on a target nobody chose."""
    lea = set_pool("LEA")
    game, _p1, p2 = _fixc_game(
        set_pool("LEG")["Cleanse"], (lea["Scathe Zombies"], lea["Savannah Lions"]),
    )

    result = game.cast_from_hand(0, "Cleanse")
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Savannah Lions"]


def test_cleanse_still_casts_with_no_creature_anywhere(set_pool):
    """The board the defect was actually met on. A sweep with nothing to sweep
    is a legal, resolvable spell — CR 601.2c has no target to announce, so
    there is nothing for an empty candidate list to refuse."""
    game, _p1, _p2 = _fixc_game(set_pool("LEG")["Cleanse"])

    result = game.cast_from_hand(0, "Cleanse")
    game._settle()

    assert result.supported, result.details
    assert game.stack == []


def test_hellfire_pays_its_own_damage_off_the_sweep_it_performed(set_pool):
    """"…deals X plus 3 damage to you, where X is the number of creatures that
    died this way." The second sentence counts the first sentence's sweep, so
    the whole card works off a class it named and an object it never chose."""
    lea = set_pool("LEA")
    game, p1, p2 = _fixc_game(
        set_pool("LEG")["Hellfire"], (lea["Scathe Zombies"], lea["Savannah Lions"]),
    )

    result = game.cast_from_hand(0, "Hellfire")
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Scathe Zombies"]  # black survives
    assert p1.life == 16                                         # X=1, plus 3


def test_hellfire_on_an_empty_board_still_costs_its_caster_three(set_pool):
    """X is 0 and the 3 is not: the sweep hitting nothing is not the spell
    failing, which is the difference a cast the client refused could not make."""
    game, p1, _p2 = _fixc_game(set_pool("LEG")["Hellfire"])

    result = game.cast_from_hand(0, "Hellfire")
    game._settle()

    assert result.supported, result.details
    assert p1.life == 17
# --- end FixC ---
