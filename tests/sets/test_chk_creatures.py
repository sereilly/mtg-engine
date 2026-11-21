"""Champions of Kamigawa creatures (legendary ones too).

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


# Flip cards (CR 710). A flip card is its top half everywhere but a flipped
# permanent (``engine/flip_cards.py``); each test casts or places the card,
# drives its flip condition through the real engine, and reads the board.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.flip_cards import is_flipped as _w1g1_is_flipped
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import add_counters as _w1g1_add_counters
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import drive_combat as _w1g1_drive_combat
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat=0):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_activate(game, permanent, seat=0, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    _w1g1_settle(game)
    return result


def _w1g1_state(permanent):
    card = permanent.effective_card
    return (
        card.name, card.is_legendary,
        permanent.effective_power, permanent.effective_toughness,
    )


def test_w1g1_jushi_apprentice_flips_at_nine_cards_and_tomoya_draws_that_many(set_pool):
    """{2}{U}, {T}: Draw a card. If you have nine or more cards in hand, flip
    this creature. Below nine nothing flips; at nine it is Tomoya the
    Revealer — the bottom half's name, legendary type line and 2/3 (CR
    710.1b), still blue with the card's mana cost (CR 710.1c), and the +1/+1
    counter put on it before the flip still applies (an external effect)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Island"]] * 7)
    jushi = _w1g1_put(game, chk["Jushi Apprentice"])
    assert _w1g1_state(jushi) == ("Jushi Apprentice", False, 1, 2)
    _w1g1_add_counters(jushi, "+1/+1", 1)
    _w1g1_activate(game, jushi)
    assert len(game.players[0].hand) == 8 and not _w1g1_is_flipped(jushi)
    jushi.tapped = False
    _w1g1_activate(game, jushi)
    assert len(game.players[0].hand) == 9 and _w1g1_is_flipped(jushi)
    assert _w1g1_state(jushi) == ("Tomoya the Revealer", True, 3, 4)
    assert jushi.card.mana_cost == "{1}{U}" and game._effective_colors(jushi) == {"U"}
    assert "Jushi Apprentice flipped: it is Tomoya the Revealer" in game.log
    # {3}{U}{U}, {T}: Target player draws X cards, where X is the number of
    # cards in your hand.
    jushi.tapped = False
    before = len(game.players[1].hand)
    _w1g1_activate(game, jushi, target_player_index=1)
    assert len(game.players[1].hand) == before + 9


def test_w1g1_a_flipped_flip_card_leaves_as_its_top_half(set_pool):
    """CR 710.4: a flipped permanent that leaves the battlefield retains no
    memory of its status. Bounced, Tomoya is a Jushi Apprentice in the hand —
    named Jushi Apprentice, not legendary — and cast again it enters
    unflipped (CR 110.5b). Destroyed, the graveyard holds Jushi Apprentice."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Island"]] * 8)
    jushi = _w1g1_put(game, chk["Jushi Apprentice"])
    _w1g1_activate(game, jushi)
    assert _w1g1_is_flipped(jushi)
    game.remove_from_battlefield(jushi)
    game.put_card_into_hand(0, jushi.card, from_battlefield=jushi)
    held = next(card for card in game.players[0].hand if card.layout == "flip")
    assert (held.name, held.is_legendary) == ("Jushi Apprentice", False)
    assert game.cast_from_hand(0, "Jushi Apprentice").supported
    _w1g1_settle(game)
    again = next(p for p in game.all_permanents() if p.card is held)
    assert not _w1g1_is_flipped(again)
    assert _w1g1_state(again) == ("Jushi Apprentice", False, 1, 2)
    again.metadata["summoning_sickness_turn"] = -99
    _w1g1_activate(game, again)
    assert _w1g1_is_flipped(again)
    game.remove_from_battlefield(again)
    game.put_card_into_graveyard(0, again.card, from_battlefield=again)
    assert [card.name for card in game.players[0].graveyard] == ["Jushi Apprentice"]


def test_w1g1_the_legend_rule_sees_a_flipped_permanent_only(set_pool):
    """CR 704.5j asks the flipped permanent's characteristics: two unflipped
    Jushi Apprentices are not legendary and both stay; once each flips, the
    two Tomoyas are legendary with one name, and one is put into the
    graveyard — as Jushi Apprentice (CR 710.4)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Island"]] * 8)
    first = _w1g1_put(game, chk["Jushi Apprentice"])
    second = _w1g1_put(game, chk["Jushi Apprentice"])
    _w1g1_settle(game)
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    _w1g1_activate(game, first)
    assert _w1g1_is_flipped(first) and game.is_on_battlefield(second)
    game.players[0].hand.append(lea["Island"])
    _w1g1_activate(game, second)
    on_board = [p for p in (first, second) if game.is_on_battlefield(p)]
    assert len(on_board) == 1 and _w1g1_is_flipped(on_board[0])
    assert [card.name for card in game.players[0].graveyard] == ["Jushi Apprentice"]


def test_w1g1_student_of_elements_flips_when_it_has_flying(set_pool):
    """When this creature has flying, flip it (a state trigger, CR 603.8).
    Given flying until end of turn by Jump, it flips into Tobita, Master of
    Winds — "Creatures you control have flying" — and stays flipped after the
    Jump wears off (CR 710.4), every creature its controller has flying."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Jump"]])
    student = _w1g1_put(game, chk["Student of Elements"])
    bears = _w1g1_put(game, lea["Grizzly Bears"])
    assert not _w1g1_is_flipped(student)
    assert game.cast_from_hand(0, "Jump", target_permanent_ids=[student.permanent_id]).supported
    _w1g1_settle(game)
    assert _w1g1_is_flipped(student)
    assert _w1g1_state(student) == ("Tobita, Master of Winds", True, 3, 3)
    game.resolve_cleanup_step(0)
    assert _w1g1_is_flipped(student)
    assert game._has_keyword(student, "flying") and game._has_keyword(bears, "flying")


def test_w1g1_kitsune_mystic_flips_at_the_end_step_with_two_auras(set_pool):
    """At the beginning of the end step, if this creature is enchanted by two
    or more Auras, flip it (CR 603.4's intervening-if). One Aura at the end
    step: no flip. Two: it is Autumn-Tail, Kitsune Sage, a 4/5 with both Auras
    still on it (CR 710.1c: external effects still apply)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Holy Strength"], lea["Holy Strength"]])
    mystic = _w1g1_put(game, chk["Kitsune Mystic"])
    assert game.cast_from_hand(
        0, "Holy Strength", target_permanent_ids=[mystic.permanent_id],
    ).supported
    _w1g1_settle(game)
    game.resolve_end_step(0)
    _w1g1_settle(game)
    assert not _w1g1_is_flipped(mystic)
    assert game.cast_from_hand(
        0, "Holy Strength", target_permanent_ids=[mystic.permanent_id],
    ).supported
    _w1g1_settle(game)
    game.resolve_end_step(0)
    _w1g1_settle(game)
    assert _w1g1_is_flipped(mystic)
    # 4/5 printed, +1/+2 from each Holy Strength.
    assert _w1g1_state(mystic) == ("Autumn-Tail, Kitsune Sage", True, 6, 9)


def test_w1g1_autumn_tail_moves_an_aura_to_another_creature(set_pool):
    """Autumn-Tail, Kitsune Sage: {1}: Attach target Aura attached to a
    creature to another creature (Crown of the Ages' line, CR 701.3)."""
    from engine.aura_attachment import auras_attached_to
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Holy Strength"]])
    mystic = _w1g1_put(game, chk["Kitsune Mystic"])
    bears = _w1g1_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        0, "Holy Strength", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g1_settle(game)
    aura = next(iter(auras_attached_to(bears)))
    flip_permanent(game, mystic)
    _w1g1_activate(game, mystic, target_permanent_ids=[aura.permanent_id])
    assert list(auras_attached_to(bears)) == []
    assert list(auras_attached_to(mystic)) == [aura]
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g1_nezumi_graverobber_flips_on_the_last_card_of_a_graveyard(set_pool):
    """{1}{B}: Exile target card from an opponent's graveyard. If no cards are
    in that graveyard, flip this creature. Two cards: the first exile leaves
    one, no flip; the second empties the pile and it is Nighteyes the
    Desecrator. The activator's own graveyard is never offered."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    game.players[1].graveyard[:] = [lea["Grizzly Bears"], lea["Giant Spider"]]
    game.players[0].graveyard[:] = [lea["Craw Wurm"]]
    robber = _w1g1_put(game, chk["Nezumi Graverobber"])
    ability = compile_card_oracle(robber.card).activated_abilities[0]
    spec = derive_activation_spec(ability)
    assert "opponent_graveyard_only" in repr(spec), spec
    _w1g1_activate(game, robber, target_player_index=1, target_graveyard_indices=[0])
    assert [c.name for c in game.players[1].graveyard] == ["Giant Spider"]
    assert not _w1g1_is_flipped(robber)
    _w1g1_activate(game, robber, target_player_index=1, target_graveyard_indices=[0])
    assert game.players[1].graveyard == []
    assert _w1g1_is_flipped(robber)
    assert _w1g1_state(robber) == ("Nighteyes the Desecrator", True, 4, 2)
    assert [c.name for c in game.players[0].graveyard] == ["Craw Wurm"]


def test_w1g1_nezumi_graverobber_takes_nothing_from_its_own_graveyard(set_pool):
    """An announcement naming the activator's own pile names no card the
    sentence can take: it is refused, or resolves exiling nothing — either
    way the activator's card stays and nothing flips."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    game.players[0].graveyard[:] = [lea["Craw Wurm"]]
    robber = _w1g1_put(game, chk["Nezumi Graverobber"])
    game.activate_permanent_ability(
        0, "Nezumi Graverobber", permanent_index=game.battlefield_index_of(robber),
        target_player_index=0, target_graveyard_indices=[0],
    )
    _w1g1_settle(game)
    assert [c.name for c in game.players[0].graveyard] == ["Craw Wurm"]
    assert not _w1g1_is_flipped(robber)


def test_w1g1_nighteyes_reanimates_a_creature_card_from_any_graveyard(set_pool):
    """Nighteyes the Desecrator: {4}{B}: Put target creature card from a
    graveyard onto the battlefield under your control. Its picker offers the
    creature cards in both graveyards (``any_graveyard``) and no land; a card
    from the opponent's pile arrives under its controller, and one from its
    own pile returns too."""
    from engine.flip_cards import flip_permanent
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    game.players[1].graveyard[:] = [lea["Forest"], lea["Craw Wurm"]]
    game.players[0].graveyard[:] = [lea["Grizzly Bears"]]
    robber = _w1g1_put(game, chk["Nezumi Graverobber"])
    flip_permanent(game, robber)
    ability = compile_card_oracle(robber.card).activated_abilities[0]
    spec = derive_activation_spec(ability)
    assert "own_graveyard_only" not in repr(spec), spec
    refused = game.activate_permanent_ability(
        0, robber.card.name, permanent_index=game.battlefield_index_of(robber),
        target_player_index=1, target_graveyard_indices=[0],
    )
    assert not refused.supported, "a land card is no creature card"
    _w1g1_activate(game, robber, target_player_index=1, target_graveyard_indices=[1])
    wurm = next(p for p in game.all_permanents() if p.card.name == "Craw Wurm")
    assert game.controller_index_of(wurm) == 0
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]
    robber.tapped = False
    _w1g1_activate(game, robber, target_player_index=0, target_graveyard_indices=[0])
    assert any(p.card.name == "Grizzly Bears" for p in game.players[0].battlefield)


def test_w1g1_nezumi_shortfang_flips_when_the_opponent_is_emptied(set_pool):
    """{1}{B}, {T}: Target opponent discards a card. Then if that player has
    no cards in hand, flip this creature. Two cards: one discard, no flip;
    the second leaves them empty-handed and it is Stabwhisker the Odious."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(
        set_pool, opponent_hand=[lea["Grizzly Bears"], lea["Giant Spider"]],
    )
    shortfang = _w1g1_put(game, chk["Nezumi Shortfang"])
    _w1g1_activate(game, shortfang, target_player_index=1)
    assert len(game.players[1].hand) == 1 and not _w1g1_is_flipped(shortfang)
    shortfang.tapped = False
    _w1g1_activate(game, shortfang, target_player_index=1)
    assert game.players[1].hand == [] and _w1g1_is_flipped(shortfang)
    assert _w1g1_state(shortfang) == ("Stabwhisker the Odious", True, 3, 3)


def test_w1g1_stabwhisker_drains_one_per_card_short_of_three(set_pool):
    """Stabwhisker the Odious: At the beginning of each opponent's upkeep,
    that player loses 1 life for each card fewer than three in their hand.
    The upkeep comes before the draw: an empty hand is three short, three
    cards none, and its controller's own upkeep costs nothing."""
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    stabwhisker = _w1g1_put(game, chk["Nezumi Shortfang"])
    flip_permanent(game, stabwhisker)
    game.players[1].hand[:] = []
    game.start_turn(1)
    _w1g1_settle(game)
    assert game.players[1].life == 17
    game.players[0].hand[:] = []
    game.start_turn(0)
    _w1g1_settle(game)
    assert game.players[0].life == 20
    game.players[1].hand[:] = [lea["Island"]] * 3
    game.start_turn(1)
    _w1g1_settle(game)
    assert game.players[1].life == 17


def test_w1g1_akki_lavarunner_flips_after_hitting_an_opponent(set_pool):
    """Haste. Whenever this creature deals damage to an opponent, flip it.
    It attacks the turn it arrives, connects, and is Tok-Tok, Volcano Born:
    a legendary 2/2 with protection from red."""
    chk = set_pool("CHK")
    game = _w1g1_table(set_pool)
    akki = _W1G1Permanent(card=chk["Akki Lavarunner"])
    game._put_permanent_onto_battlefield(0, akki, None)
    _w1g1_settle(game)
    assert game._has_keyword(akki, "haste")
    _w1g1_declare_attack(game, 0)
    _w1g1_drive_combat(game)
    assert game.players[1].life == 19
    assert _w1g1_is_flipped(akki)
    assert _w1g1_state(akki) == ("Tok-Tok, Volcano Born", True, 2, 2)
    assert game._has_keyword(akki, "protection")


def test_w1g1_tok_tok_adds_one_to_red_damage_to_players_only(set_pool):
    """Tok-Tok, Volcano Born: If a red source would deal damage to a player,
    it deals that much damage plus 1 to that player instead. A Lightning Bolt
    to the opponent is 4; to a creature it is still 3; and Tok-Tok's own
    controller takes the extra point too (the sentence names no seat)."""
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Lightning Bolt"]] * 3)
    toktok = _w1g1_put(game, chk["Akki Lavarunner"])
    flip_permanent(game, toktok)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 1)
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g1_settle(game)
    assert game.players[1].life == 16
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g1_settle(game)
    assert wurm.damage_marked == 3
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g1_settle(game)
    assert game.players[0].life == 16


def test_w1g1_initiate_of_blood_flips_when_its_victim_dies_this_turn(set_pool):
    """{T}: This creature deals 1 damage to target creature that was dealt
    damage this turn. When that creature dies this turn, flip this creature.
    A wounded 2/2 finished by the ping: the delayed trigger flips it into
    Goka the Unjust, whose {T} deals 4 to a creature dealt damage this turn."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    initiate = _w1g1_put(game, chk["Initiate of Blood"])
    sorcerer = _w1g1_put(game, lea["Prodigal Sorcerer"])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    wurm = _w1g1_put(game, lea["Craw Wurm"], 1)
    _w1g1_activate(game, sorcerer, target_permanent_ids=[bears.permanent_id])
    assert bears.damage_marked == 1
    _w1g1_activate(game, initiate, target_permanent_ids=[bears.permanent_id])
    assert not game.is_on_battlefield(bears)
    assert _w1g1_is_flipped(initiate)
    assert _w1g1_state(initiate) == ("Goka the Unjust", True, 4, 4)
    # Goka's own self-reference ("Goka deals 4 damage", CR 201.5c) on a
    # creature dealt damage this turn.
    sorcerer.tapped = False
    _w1g1_activate(game, sorcerer, target_permanent_ids=[wurm.permanent_id])
    initiate.tapped = False
    _w1g1_activate(game, initiate, target_permanent_ids=[wurm.permanent_id])
    assert wurm.damage_marked == 5


def test_w1g1_initiate_of_blood_stays_unflipped_when_the_victim_lives(set_pool):
    """The delayed trigger is about *that* creature dying this turn: a
    creature that survives the ping flips nothing, and another creature
    dying does not either."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Lightning Bolt"]])
    initiate = _w1g1_put(game, chk["Initiate of Blood"])
    sorcerer = _w1g1_put(game, lea["Prodigal Sorcerer"])
    wurm = _w1g1_put(game, lea["Craw Wurm"], 1)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_activate(game, sorcerer, target_permanent_ids=[wurm.permanent_id])
    _w1g1_activate(game, initiate, target_permanent_ids=[wurm.permanent_id])
    assert game.is_on_battlefield(wurm) and not _w1g1_is_flipped(initiate)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g1_settle(game)
    assert not game.is_on_battlefield(bears)
    assert not _w1g1_is_flipped(initiate)


def test_w1g1_budoka_gardener_flips_with_ten_lands(set_pool):
    """{T}: You may put a land card from your hand onto the battlefield. If you
    control ten or more lands, flip this creature. Eight lands and a land put
    in: nine, no flip; with ten it flips even when no land is put in
    (2004-12-01 ruling: "it flips if you control ten or more lands as the
    ability resolves, even if you put no land onto the battlefield")."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[lea["Forest"]])
    for _ in range(8):
        _w1g1_put(game, lea["Forest"])
    gardener = _w1g1_put(game, chk["Budoka Gardener"])
    _w1g1_activate(game, gardener)
    lands = [p for p in game.players[0].battlefield if p.card.name == "Forest"]
    assert len(lands) == 9 and not _w1g1_is_flipped(gardener)
    _w1g1_put(game, lea["Forest"])
    gardener.tapped = False
    _w1g1_activate(game, gardener)
    assert _w1g1_is_flipped(gardener)
    assert _w1g1_state(gardener) == ("Dokai, Weaver of Life", True, 3, 3)


def test_w1g1_dokai_makes_an_elemental_as_big_as_your_lands(set_pool):
    """Dokai, Weaver of Life: {4}{G}{G}, {T}: Create an X/X green Elemental
    creature token, where X is the number of lands you control."""
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    for _ in range(7):
        _w1g1_put(game, lea["Forest"])
    dokai = _w1g1_put(game, chk["Budoka Gardener"])
    flip_permanent(game, dokai)
    _w1g1_activate(game, dokai)
    token = next(p for p in game.all_permanents() if "Elemental" in p.card.name)
    assert (token.effective_power, token.effective_toughness) == (7, 7)


def test_w1g1_orochi_eggwatcher_flips_at_ten_creatures(set_pool):
    """{2}{G}, {T}: Create a 1/1 green Snake creature token. If you control ten
    or more creatures, flip this creature. With eight creatures the Snake
    makes nine (with the Eggwatcher: ten) — it flips; Shidako, Broodmistress
    then sacrifices a creature for +3/+3."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    for _ in range(7):
        _w1g1_put(game, lea["Grizzly Bears"])
    egg = _w1g1_put(game, chk["Orochi Eggwatcher"])
    _w1g1_activate(game, egg)
    assert sum(1 for p in game.players[0].battlefield if p.is_creature) == 9
    assert not _w1g1_is_flipped(egg)
    egg.tapped = False
    _w1g1_activate(game, egg)
    assert sum(1 for p in game.players[0].battlefield if p.is_creature) == 10
    assert _w1g1_is_flipped(egg)
    assert _w1g1_state(egg) == ("Shidako, Broodmistress", True, 3, 3)
    snake = next(p for p in game.players[0].battlefield if "Snake" in p.card.name)
    _w1g1_activate(
        game, egg, target_permanent_ids=[egg.permanent_id],
        cost_permanent_ids=[snake.permanent_id],
    )
    assert _w1g1_state(egg) == ("Shidako, Broodmistress", True, 6, 6)
    assert sum(1 for p in game.players[0].battlefield if p.is_creature) == 9

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
