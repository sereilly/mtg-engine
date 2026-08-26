"""Per-card tests for Legends' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition


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
