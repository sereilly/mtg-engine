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


def test_w1g1_isamaru_is_a_legendary_two_two(set_pool):
    """Isamaru, Hound of Konda (drive list): a vanilla legendary 2/2 — and a
    second Isamaru puts one into the graveyard (CR 704.5j)."""
    chk = set_pool("CHK")
    game = _w1g1_table(set_pool)
    first = _w1g1_put(game, chk["Isamaru, Hound of Konda"])
    assert _w1g1_state(first) == ("Isamaru, Hound of Konda", True, 2, 2)
    _w1g1_put(game, chk["Isamaru, Hound of Konda"])
    _w1g1_settle(game)
    on_board = [p for p in game.players[0].battlefield if p.card.name.startswith("Isamaru")]
    assert len(on_board) == 1
    assert [card.name for card in game.players[0].graveyard] == ["Isamaru, Hound of Konda"]

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# Bushido (CR 702.45) on every printing, and the Samurai lines beside it:
# Konda's Hatamoto, Nagao, Takeno, Sensei Golden-Tail, Brothers Yamazaki and
# Samurai of the Pale Curtain. The keyword's rules (both halves, CR 702.45b's
# instances, the response window) are tests/rules/test_chk_w1g2_bushido.py.

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import derive_activation_spec as _w1g2_activation_spec
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=(), hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, sick=False):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def _w1g2_attack(game, seat, attackers, blocks=()):
    """*seat* attacks with *attackers* (permanents); the other seat declares
    *blocks*, ``(blocker, attacker)`` permanent pairs. Leaves the game in
    the declare blockers step with the block triggers on the stack."""
    defender = 1 - seat
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        seat, [game.battlefield_index_of(a) for a in attackers],
        defending_player_index=defender,
    )
    assert ok, why
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    pairs = {
        game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)
        for blocker, attacker in blocks
    }
    ok, why = game.declare_blockers(defender, pairs)
    assert ok, why


def _w1g2_bushido_lines(card):
    return [
        t for t in _w1g2_compile(card).triggered_abilities
        if t.source_line.startswith("bushido ")
    ]


@_w1g2_pytest.mark.parametrize("name, amount", [
    ("Devoted Retainer", 1), ("Kitsune Blademaster", 1),
    ("Samurai of the Pale Curtain", 1), ("Battle-Mad Ronin", 2),
    ("Cursed Ronin", 1), ("Konda's Hatamoto", 1), ("Mothrider Samurai", 1),
    ("Numai Outcast", 2), ("Ronin Houndmaster", 1), ("Samurai Enforcers", 2),
    ("Nezumi Ronin", 1), ("Brothers Yamazaki", 1),
    ("Konda, Lord of Eiganjo", 5), ("Nagao, Bound by Honor", 1),
    ("Takeno, Samurai General", 2), ("Sensei Golden-Tail", 1),
])
def test_w1g2_every_bushido_printing_blocks_bigger_by_its_n(set_pool, name, amount):
    """Each of the sixteen blocks an attacker that would otherwise be too
    big for it, and its bushido makes it +N/+N as the block's trigger
    resolves (CR 702.45a) — read off the board, not off the program."""
    card = set_pool("CHK")[name]
    assert _w1g2_compile(card).supported
    assert len(_w1g2_bushido_lines(card)) == 1
    game = _w1g2_table(set_pool)
    attacker = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 0)
    samurai = _w1g2_put(game, card, 1)
    before = _w1g2_pt(samurai)
    _w1g2_attack(game, 0, [attacker], [(samurai, attacker)])
    assert [item.ability_text for item in game.stack] == [f"bushido {amount}"]
    _w1g2_settle(game)
    assert _w1g2_pt(samurai) == (before[0] + amount, before[1] + amount)
    assert f"{name} gets +{amount}/+{amount} until end of turn" in game.log


def test_w1g2_devoted_retainer_trades_with_a_bear_it_blocks(set_pool):
    """A 1/1 that blocks a Grizzly Bears is a 2/2 by damage, so both die."""
    game = _w1g2_table(set_pool)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    retainer = _w1g2_put(game, set_pool("CHK")["Devoted Retainer"], 1)
    _w1g2_attack(game, 0, [bears], [(retainer, bears)])
    _w1g2_drive_combat(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]
    assert "Devoted Retainer" in [c.name for c in game.players[1].graveyard]


def test_w1g2_samurai_enforcers_bushido_fires_when_it_becomes_blocked(set_pool):
    """The other half of CR 702.45a: the attacker is the one blocked, and a
    4/4 blocked by a Shivan Dragon is a 6/6 by damage — it survives and the
    5/5 dies."""
    game = _w1g2_table(set_pool)
    enforcers = _w1g2_put(game, set_pool("CHK")["Samurai Enforcers"], 0)
    dragon = _w1g2_put(game, set_pool("LEA")["Shivan Dragon"], 1)
    _w1g2_attack(game, 0, [enforcers], [(dragon, enforcers)])
    assert "Samurai Enforcers triggered on becoming blocked (added to stack)" in game.log
    _w1g2_settle(game)
    assert _w1g2_pt(enforcers) == (6, 6)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(enforcers)
    assert "Shivan Dragon" in [c.name for c in game.players[1].graveyard]


def test_w1g2_an_unblocked_samurai_gets_no_bushido(set_pool):
    """Neither half happens: nothing blocks, nothing triggers, and the
    Nezumi Ronin deals its printed 3."""
    game = _w1g2_table(set_pool)
    ronin = _w1g2_put(game, set_pool("CHK")["Nezumi Ronin"], 0)
    _w1g2_attack(game, 0, [ronin], [])
    assert not game.stack
    _w1g2_drive_combat(game)
    assert game.players[1].life == 17


def test_w1g2_kitsune_blademaster_strikes_first_with_its_bushido(set_pool):
    """First strike and bushido 1: the trigger resolves in the declare
    blockers step, before any damage, so the 3/3 first striker kills a Hill
    Giant before it can deal damage back."""
    game = _w1g2_table(set_pool)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    blademaster = _w1g2_put(game, set_pool("CHK")["Kitsune Blademaster"], 1)
    _w1g2_attack(game, 0, [giant], [(blademaster, giant)])
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(blademaster)
    assert blademaster.metadata.get("damage", 0) == 0
    assert "Hill Giant" in [c.name for c in game.players[0].graveyard]


def test_w1g2_battle_mad_ronin_must_attack_and_trades_up(set_pool):
    """"This creature attacks each combat if able": a declaration leaving it
    home is refused. Blocked by a Hill Giant it is a 3/3, and they trade."""
    game = _w1g2_table(set_pool)
    ronin = _w1g2_put(game, set_pool("CHK")["Battle-Mad Ronin"], 0)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(0, [], defending_player_index=1)
    assert not ok
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(ronin)], defending_player_index=1
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(giant): game.battlefield_index_of(ronin)}
    )[0]
    _w1g2_drive_combat(game)
    assert "Battle-Mad Ronin" in [c.name for c in game.players[0].graveyard]
    assert "Hill Giant" in [c.name for c in game.players[1].graveyard]


def test_w1g2_cursed_ronin_pumps_on_top_of_its_bushido(set_pool):
    """"{B}: This creature gets +1/+1 until end of turn" stacks with the
    bushido trigger: two activations and a block make a 1/1 a 4/4."""
    game = _w1g2_table(set_pool)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    ronin = _w1g2_put(game, set_pool("CHK")["Cursed Ronin"], 1)
    _w1g2_attack(game, 0, [giant], [(ronin, giant)])
    _w1g2_settle(game)
    for _ in range(2):
        result = game.activate_permanent_ability(
            1, "Cursed Ronin", permanent_index=game.battlefield_index_of(ronin)
        )
        assert result.supported, result
        _w1g2_settle(game)
    assert _w1g2_pt(ronin) == (4, 4)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(ronin)
    assert "Hill Giant" in [c.name for c in game.players[0].graveyard]


def test_w1g2_numai_outcast_regenerates_for_five_life(set_pool):
    """"{B}, Pay 5 life: Regenerate this creature." The shield is paid for
    in life, and a Craw Wurm's 6 damage to the 3/3 bushido Outcast is
    regenerated away: tapped, removed from combat, alive, 15 life."""
    game = _w1g2_table(set_pool)
    wurm = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 0)
    outcast = _w1g2_put(game, set_pool("CHK")["Numai Outcast"], 1)
    _w1g2_attack(game, 0, [wurm], [(outcast, wurm)])
    _w1g2_settle(game)
    assert _w1g2_pt(outcast) == (3, 3)
    result = game.activate_permanent_ability(
        1, "Numai Outcast", permanent_index=game.battlefield_index_of(outcast)
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert game.players[1].life == 15
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(outcast)
    assert outcast.tapped


def test_w1g2_ronin_houndmaster_attacks_the_turn_it_arrives(set_pool):
    """Haste: a summoning-sick Houndmaster may still be declared."""
    game = _w1g2_table(set_pool)
    hound = _w1g2_put(game, set_pool("CHK")["Ronin Houndmaster"], 0, sick=True)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(hound)], defending_player_index=1
    )
    assert ok, why


def test_w1g2_mothrider_samurai_flies_over_a_ground_blocker(set_pool):
    """Flying beside bushido: a Grizzly Bears cannot block it."""
    game = _w1g2_table(set_pool)
    moth = _w1g2_put(game, set_pool("CHK")["Mothrider Samurai"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(moth)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(moth)}
    )
    assert not ok


def test_w1g2_konda_lord_of_eiganjo_is_indestructible_and_huge_blocking(set_pool):
    """Vigilance, indestructible, bushido 5: a blocked Konda is an 8/8 that
    no damage destroys, and it attacks without tapping."""
    game = _w1g2_table(set_pool)
    konda = _w1g2_put(game, set_pool("CHK")["Konda, Lord of Eiganjo"], 0)
    wurm = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 1)
    _w1g2_attack(game, 0, [konda], [(wurm, konda)])
    assert not konda.tapped
    _w1g2_settle(game)
    assert _w1g2_pt(konda) == (8, 8)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(konda)
    assert "Craw Wurm" in [c.name for c in game.players[1].graveyard]


def test_w1g2_kondas_hatamoto_needs_a_legendary_samurai_of_its_own(set_pool):
    """"As long as you control a legendary Samurai, this creature gets +1/+2
    and has vigilance." Alone it is a 1/2; an opponent's Nagao changes
    nothing; a Nagao of its own makes it a 2/4 with vigilance; a nonlegendary
    Samurai (Devoted Retainer) is not enough."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    hatamoto = _w1g2_put(game, pool["Konda's Hatamoto"], 0)
    assert _w1g2_pt(hatamoto) == (1, 2) and not hatamoto.has_keyword("vigilance")
    _w1g2_put(game, pool["Devoted Retainer"], 0)
    _w1g2_put(game, pool["Nagao, Bound by Honor"], 1)
    assert _w1g2_pt(hatamoto) == (1, 2) and not hatamoto.has_keyword("vigilance")
    nagao = _w1g2_put(game, pool["Nagao, Bound by Honor"], 0)
    assert _w1g2_pt(hatamoto) == (2, 4) and hatamoto.has_keyword("vigilance")
    game.remove_from_battlefield(nagao)
    game._permanent_to_graveyard(game.players[0], nagao)
    _w1g2_settle(game)
    assert _w1g2_pt(hatamoto) == (1, 2)


def test_w1g2_nagao_pumps_its_controllers_samurai_when_it_attacks(set_pool):
    """"Whenever Nagao attacks, Samurai creatures you control get +1/+1 until
    end of turn." Its own Samurai (itself and a Devoted Retainer at home) get
    it; a Grizzly Bears beside them and the opponent's Nezumi Ronin do not;
    it is gone after the turn."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    nagao = _w1g2_put(game, pool["Nagao, Bound by Honor"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, pool["Nezumi Ronin"], 1)
    _w1g2_attack(game, 0, [nagao], [])
    _w1g2_settle(game)
    assert _w1g2_pt(nagao) == (4, 4)
    assert _w1g2_pt(retainer) == (2, 2)
    assert _w1g2_pt(bears) == (2, 2)
    assert _w1g2_pt(theirs) == (3, 1)
    _w1g2_drive_combat(game)
    assert game.resolve_cleanup_step(0)
    assert _w1g2_pt(nagao) == (3, 3) and _w1g2_pt(retainer) == (1, 1)


def test_w1g2_takeno_counts_each_other_samurais_bushido(set_pool):
    """"Each other Samurai creature you control gets +1/+1 for each point of
    bushido it has." Samurai Enforcers (bushido 2) +2/+2, Devoted Retainer
    (bushido 1) +1/+1; Takeno itself, a non-Samurai, and an opponent's
    Samurai get nothing. Takeno leaving takes it all back."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    takeno = _w1g2_put(game, pool["Takeno, Samurai General"], 0)
    enforcers = _w1g2_put(game, pool["Samurai Enforcers"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, pool["Nezumi Ronin"], 1)
    assert _w1g2_pt(takeno) == (3, 3)
    assert _w1g2_pt(enforcers) == (6, 6)
    assert _w1g2_pt(retainer) == (2, 2)
    assert _w1g2_pt(bears) == (2, 2)
    assert _w1g2_pt(theirs) == (3, 1)
    game.remove_from_battlefield(takeno)
    game._permanent_to_graveyard(game.players[0], takeno)
    _w1g2_settle(game)
    assert _w1g2_pt(enforcers) == (4, 4) and _w1g2_pt(retainer) == (1, 1)


def test_w1g2_sensei_golden_tail_trains_a_creature_for_good(set_pool):
    """"Put a training counter on target creature. That creature gains
    bushido 1 and becomes a Samurai in addition to its other creature types.
    Activate only as a sorcery." The picker offers a creature; the Bears gets
    the counter, the keyword (it triggers when it blocks) and the Samurai
    type while staying a Bear — and keeps all of it turns later, because the
    grant has no duration."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    sensei = _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    ability = _w1g2_compile(sensei.effective_card).activated_abilities[0]
    assert _w1g2_activation_spec(ability) == {"kind": "creature"}
    result = game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert bears.metadata.get("training_counters") == 1
    assert bears.has_keyword("bushido")
    assert bears.has_type("samurai") and bears.has_type("bear")
    for seat in (1, 0, 1):
        game.start_turn(seat)
        _w1g2_settle(game)
    assert bears.has_keyword("bushido") and bears.has_type("samurai")
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(bears, giant)])
    assert [item.ability_text for item in game.stack] == ["bushido 1"]
    _w1g2_settle(game)
    assert _w1g2_pt(bears) == (3, 3)


def test_w1g2_sensei_golden_tail_activates_only_as_a_sorcery(set_pool):
    """In combat the activation is refused and nothing is trained."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    game._set_phase_and_step("combat", "declare_attackers")
    result = game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[bears.permanent_id]
    )
    assert not result.supported
    _w1g2_settle(game)
    assert not bears.has_keyword("bushido")


def test_w1g2_sensei_training_a_samurai_stacks_a_second_bushido(set_pool):
    """Trained, a Devoted Retainer has two instances of bushido 1: Takeno
    counts both (+2/+2), and its block puts two triggers on the stack
    (CR 702.45b), a 3/3 becoming a 5/5."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    _w1g2_put(game, pool["Takeno, Samurai General"], 0)
    game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[retainer.permanent_id]
    )
    _w1g2_settle(game)
    assert _w1g2_pt(retainer) == (3, 3)
    game.start_turn(1)
    _w1g2_settle(game)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(retainer, giant)])
    assert [item.ability_text for item in game.stack] == ["bushido 1", "bushido 1"]
    _w1g2_settle(game)
    assert _w1g2_pt(retainer) == (5, 5)


def test_w1g2_brothers_yamazaki_two_survive_and_pump_each_other(set_pool):
    """Exactly two on the battlefield: the legend rule does not apply, and
    each is the other's "other creature named Brothers Yamazaki" — 4/3 with
    haste. A third brings the rule back, and its controller keeps one (the
    card's 2013-07-01 ruling); the one left is a bare 2/1."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool)
    first = _w1g2_put(game, brothers, 0, sick=True)
    second = _w1g2_put(game, brothers, 0, sick=True)
    game.check_state_based_actions()
    _w1g2_settle(game)
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    assert _w1g2_pt(first) == (4, 3) and first.has_keyword("haste")
    assert _w1g2_pt(second) == (4, 3) and second.has_keyword("haste")
    _w1g2_put(game, brothers, 0)
    game.check_state_based_actions()
    _w1g2_settle(game)
    left = list(game.controlled_by(0))
    assert len(left) == 1
    assert _w1g2_pt(left[0]) == (2, 1) and not left[0].has_keyword("haste")
    assert [c.name for c in game.players[0].graveyard].count("Brothers Yamazaki") == 2


def test_w1g2_brothers_yamazaki_under_two_controllers_pump_each_other(set_pool):
    """"The two Brothers could be controlled by different players" (the
    card's 2004-12-01 ruling): the static counts the whole battlefield, and
    each buffs the other across the table."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool)
    mine = _w1g2_put(game, brothers, 0)
    theirs = _w1g2_put(game, brothers, 1)
    assert _w1g2_pt(mine) == (4, 3) and _w1g2_pt(theirs) == (4, 3)


def test_w1g2_a_third_brothers_asks_its_controller_which_to_keep(set_pool):
    """At a table a person sits at, the third Brothers arms CR 704.5j's
    prompt over all three; the answer keeps the one named."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool, interactive=(0,))
    _w1g2_put(game, brothers, 0)
    _w1g2_put(game, brothers, 0)
    game.check_state_based_actions()
    assert not game.pending_choices_of("legend_rule", 0)
    # Put down without settling: a settle would answer the prompt by default.
    third = _W1G2Permanent(card=brothers)
    game._put_permanent_onto_battlefield(0, third, None)
    game.check_state_based_actions()
    (choice,) = game.pending_choices_of("legend_rule", 0)
    assert len(choice.data["candidates"]) == 3
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=third.permanent_id)
    _w1g2_settle(game)
    assert list(game.controlled_by(0)) == [third]


def test_w1g2_two_brothers_do_not_exempt_another_legend(set_pool):
    """The exemption is the Brothers' name alone: two Nagaos beside two
    Brothers are still put down to one."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    for name in ("Brothers Yamazaki", "Brothers Yamazaki", "Nagao, Bound by Honor",
                 "Nagao, Bound by Honor"):
        _w1g2_put(game, pool[name], 0)
    game.check_state_based_actions()
    _w1g2_settle(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == ["Brothers Yamazaki", "Brothers Yamazaki", "Nagao, Bound by Honor"]


def test_w1g2_pale_curtain_exiles_a_destroyed_creature_with_no_dies_trigger(set_pool):
    """"If a permanent would be put into a graveyard, exile it instead."
    Onulet ("When Onulet dies, you gain 2 life") shattered with the Samurai
    out: exiled, so it never died and its controller gains nothing. The
    Shatter itself — a spell, not a permanent — goes to the graveyard."""
    game = _w1g2_table(set_pool, hands=([set_pool("2ED")["Shatter"]], ()))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    onulet = _w1g2_put(game, set_pool("ATQ")["Onulet"], 1)
    result = game.cast_from_hand(0, "Shatter", target_permanent_ids=[onulet.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert [c.name for c in game.players[1].exile] == ["Onulet"]
    assert game.players[1].graveyard == []
    assert game.players[1].life == 20
    assert [c.name for c in game.players[0].graveyard] == ["Shatter"]


def test_w1g2_pale_curtain_exiles_itself_and_a_whole_wrath(set_pool):
    """The Samurai is a permanent too, and a Wrath of God's creatures leave
    together: every one, the Samurai included, is exiled."""
    game = _w1g2_table(set_pool, hands=([set_pool("LEA")["Wrath of God"]], ()))
    _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g2_settle(game)
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Samurai of the Pale Curtain"]
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert [c.name for c in game.players[0].graveyard] == ["Wrath of God"]
    assert game.players[1].graveyard == []


def test_w1g2_pale_curtain_exiles_its_own_targeted_destruction(set_pool):
    """Terror on the Samurai itself: it is taken off the battlefield before
    the move, and its own replacement still sends it to exile."""
    game = _w1g2_table(set_pool, hands=((), [set_pool("LEA")["Terror"]]))
    samurai = _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Terror", target_permanent_ids=[samurai.permanent_id]).supported
    _w1g2_settle(game)
    assert [c.name for c in game.players[0].exile] == ["Samurai of the Pale Curtain"]
    assert game.players[0].graveyard == []


def test_w1g2_pale_curtain_reaches_lands_artifacts_and_tokens_not_discards(set_pool):
    """Every kind of permanent: a Stone Rained land and a Snake token killed
    in combat are exiled (the token never dies — no card for anyone's pile),
    while a discarded card is no permanent and is binned as usual."""
    lea = set_pool("LEA")
    game = _w1g2_table(set_pool, hands=([lea["Stone Rain"], lea["Grizzly Bears"]], ()))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    forest = _w1g2_put(game, lea["Forest"], 1)
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[forest.permanent_id]).supported
    _w1g2_settle(game)
    assert [c.name for c in game.players[1].exile] == ["Forest"]
    _w1g2_put(game, set_pool("LEG")["Serpent Generator"], 0)
    assert game.activate_permanent_ability(0, "Serpent Generator").supported
    _w1g2_settle(game)
    (snake,) = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    giant = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(snake, giant)])
    _w1g2_drive_combat(game)
    assert not game.is_on_battlefield(snake)
    assert "Snake Token was exiled instead of being put into a graveyard" in " ".join(game.log)
    game._discard_card(game.players[0], next(
        c for c in game.players[0].hand if c.name == "Grizzly Bears"))
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]


@_w1g2_pytest.mark.parametrize("interactive, pick_curtain", [
    ((), False), ((0,), False), ((0,), True),
])
def test_w1g2_pale_curtain_contends_with_firestorm_phoenix(set_pool, interactive, pick_curtain):
    """Two replacements for one death (CR 616.1): Firestorm Phoenix's "return
    it to its owner's hand instead" and the Samurai's exile. A seat nobody
    asks applies the Phoenix's first — the order its controller would choose,
    and after it nothing is going to a graveyard — and a person is asked
    (``effect_order``) and may name either."""
    game = _w1g2_table(set_pool, interactive=interactive,
                       hands=((), [set_pool("LEA")["Terror"]]))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    phoenix = _w1g2_put(game, set_pool("LEG")["Firestorm Phoenix"], 0)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[phoenix.permanent_id]
    ).supported
    if interactive:
        owed = _w1g2_settle(game, defaults=False)
        assert owed is not None and owed.kind == "effect_order", owed
        options = owed.data["options"]
        wanted = next(
            index for index, label in enumerate(options)
            if ("Exile this permanent" in label) == pick_curtain
        )
        assert game.resolve_pending_choice("effect_order", 0, option_index=wanted)
    _w1g2_settle(game)
    names = lambda zone: [c.name for c in zone]  # noqa: E731
    if pick_curtain:
        assert names(game.players[0].exile) == ["Firestorm Phoenix"]
    else:
        assert names(game.players[0].hand) == ["Firestorm Phoenix"]
        assert names(game.players[0].exile) == []
    assert "Firestorm Phoenix" not in names(game.players[0].graveyard)

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.
import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game
from engine.models import CardDefinition as _w1g3_CardDefinition
from engine.models import Permanent as _w1g3_Permanent
from engine.models import PlayerState as _w1g3_PlayerState
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.soulshift import soulshift_count as _w1g3_soulshift_count

from tests.helpers import _nosick as _w1g3_nosick
from tests.helpers import drive_combat as _w1g3_drive_combat
from tests.helpers import settle as _w1g3_settle

#: Every Champions of Kamigawa creature printing "Soulshift N" — W1G3's eleven
#: and W1G4's Thief of Hope (whose cast trigger is W1G4's; the integrator
#: writes its whole-card test).
_W1G3_SOULSHIFT = (
    "Burr Grafter", "Gibbering Kami", "Hundred-Talon Kami", "Kami of Lunacy",
    "Kami of the Palace Fields", "Rootrunner", "Scuttling Death",
    "Thousand-legged Kami", "Venerable Kumo", "Vine Kami", "He Who Hungers",
)


def _w1g3_card(name: str, cost: int, type_line: str = "Creature — Spirit",
               text: str = "", power: str = "1", toughness: str = "1"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return _w1g3_CardDefinition(
        name=name, mana_cost="{%d}" % cost if cost else "", cmc=float(cost),
        type_line=type_line, oracle_text=text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _w1g3_table(mine=(), theirs=(), *, hand=(), graveyard=(), interactive=()):
    land = _w1g3_card("Filler Land", 0, "Land")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P1", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in mine],
            hand=list(hand), graveyard=list(graveyard), library=[land] * 10,
        ),
        _w1g3_PlayerState(
            name="P2", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in theirs],
            library=[land] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game


def _w1g3_names(cards) -> list[str]:
    return [card.name for card in cards]


def _w1g3_on_field(game, seat: int, name: str):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g3_every_soulshift_creature_prints_one_readable_soulshift_line(set_pool):
    pool = set_pool("CHK")
    printed = sorted(
        name for name, card in pool.items()
        if any(_w1g3_soulshift_count(line) for line in (card.oracle_text or "").split("\n"))
    )
    assert set(_W1G3_SOULSHIFT) <= set(printed)
    assert "Thief of Hope" in printed


@_w1g3_pytest.mark.parametrize("name", _W1G3_SOULSHIFT)
def test_w1g3_soulshift_returns_a_spirit_at_its_n_and_not_one_above(set_pool, name):
    """CR 702.46a, on every printed soulshift creature: destroyed by Rend
    Spirit, it returns the Spirit card of mana value N from its graveyard and
    leaves the one of mana value N + 1 (and a non-Spirit of mana value N)."""
    pool = set_pool("CHK")
    card = pool[name]
    assert _w1g3_compile(card).supported, name
    (n,) = [_w1g3_soulshift_count(line) for line in card.oracle_text.split("\n")
            if _w1g3_soulshift_count(line)]
    at_n = _w1g3_card(f"Spirit at {n}", n)
    above = _w1g3_card(f"Spirit at {n + 1}", n + 1)
    bear = _w1g3_card(f"Bear at {n}", n, "Creature — Bear")
    game = _w1g3_table(
        mine=[card], hand=[pool["Rend Spirit"]], graveyard=[above, bear, at_n],
    )
    victim = _w1g3_on_field(game, 0, name)
    assert game.cast_from_hand(0, "Rend Spirit", target_permanent_ids=[victim.permanent_id]).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == [f"Spirit at {n}"], game.log[-8:]
    graveyard = _w1g3_names(game.players[0].graveyard)
    assert name in graveyard and f"Spirit at {n + 1}" in graveyard and f"Bear at {n}" in graveyard


def test_w1g3_burr_grafter_sacrificed_pumps_and_its_soulshift_resolves_first(set_pool):
    """Sacrifice is a cost, so the soulshift trigger goes on the stack above
    the pump (CR 603.3) and resolves first; an interactive seat is offered only
    the Spirit cards of mana value 3 or less and names the one it wants."""
    pool = set_pool("CHK")
    bears = _w1g3_card("Target Bear", 2, "Creature — Bear", power="2", toughness="2")
    game = _w1g3_table(
        mine=[pool["Burr Grafter"]], theirs=[bears],
        graveyard=[pool["Kami of Ancient Law"], pool["Kami of Lunacy"], pool["Hana Kami"]],
        interactive=(0,),
    )
    bear = _w1g3_on_field(game, 1, "Target Bear")
    assert game.activate_permanent_ability(
        0, "Burr Grafter", target_permanent_ids=[bear.permanent_id]
    ).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Hana Kami", "Kami of Ancient Law"]
    hana = next(t for t in asked.data["targets"] if t["name"] == "Hana Kami")
    assert game.confirm_trigger_target(0, seat=hana["seat"], graveyard_index=hana["graveyard_index"])
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert _w1g3_names(game.players[0].hand) == ["Hana Kami"]
    assert bear.effective_power == 4
    returned = next(i for i, line in enumerate(game.log) if "Returned Hana Kami" in line)
    pumped = next(i for i, line in enumerate(game.log) if "+2/+2" in line)
    assert returned < pumped


def test_w1g3_rootrunner_tops_a_land_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    game = _w1g3_table(
        mine=[pool["Rootrunner"]], theirs=[_w1g3_card("Their Land", 0, "Land")],
        graveyard=[pool["Kami of Ancient Law"]],
    )
    land = _w1g3_on_field(game, 1, "Their Land")
    assert game.activate_permanent_ability(
        0, "Rootrunner", target_permanent_ids=[land.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert game.players[1].library[0].name == "Their Land"
    assert _w1g3_names(game.players[0].hand) == ["Kami of Ancient Law"]


def test_w1g3_scuttling_death_shrinks_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    elf = _w1g3_card("Small Elf", 1, "Creature — Elf", power="1", toughness="1")
    game = _w1g3_table(
        mine=[pool["Scuttling Death"]], theirs=[elf],
        graveyard=[pool["Kami of Twisted Reflection"]],
    )
    target = _w1g3_on_field(game, 1, "Small Elf")
    assert game.activate_permanent_ability(
        0, "Scuttling Death", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert "Small Elf" in _w1g3_names(game.players[1].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Twisted Reflection"]


def test_w1g3_thousand_legged_kami_dies_in_combat_and_returns_a_seven_drop_spirit(set_pool):
    """A combat death, the other road to a graveyard: blocked by a creature
    that kills it, it returns Kami of Lunacy (mana value 6, at most 7)."""
    pool = set_pool("CHK")
    wall = _w1g3_card("Big Wall", 4, "Creature — Wall", power="7", toughness="7")
    game = _w1g3_table(
        mine=[pool["Thousand-legged Kami"]], theirs=[wall],
        graveyard=[pool["Kami of Lunacy"]],
    )
    from tests.helpers import declare_attack

    # The only creature on each side: blocker slot 0 blocks attacker slot 0.
    declare_attack(game, 0, blocks={0: 0})
    _w1g3_drive_combat(game)
    _w1g3_settle(game)
    assert "Thousand-legged Kami" in _w1g3_names(game.players[0].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Lunacy"]


def _w1g3_hungers_table(set_pool, *, interactive=()):
    pool = set_pool("CHK")
    bears = _w1g3_card("Their Bear", 2, "Creature — Bear")
    shock = _w1g3_card("Their Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    giant = _w1g3_card("Their Giant", 4, "Creature — Giant", power="3", toughness="3")
    game = _w1g3_table(
        mine=[pool["He Who Hungers"], pool["Kami of Ancient Law"], bears],
        graveyard=[pool["Kami of Twisted Reflection"]], interactive=interactive,
    )
    game.players[1].hand.extend([shock, giant])
    return game


def test_w1g3_he_who_hungers_sacrifices_a_spirit_and_the_activator_picks_the_discard(set_pool):
    """"{1}, Sacrifice a Spirit: Target opponent reveals their hand. You choose
    a card from it. That player discards that card." The interactive
    activator is asked out of the revealed hand and names the Shock."""
    game = _w1g3_hungers_table(set_pool, interactive=(0,))
    kami = _w1g3_on_field(game, 0, "Kami of Ancient Law")
    assert game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[kami.permanent_id],
    ).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "revealed_hand_pick", game.log[-6:]
    assert asked.player_index == 0 and asked.data["victim_index"] == 1
    shock_slot = _w1g3_names(game.players[1].hand).index("Their Shock")
    assert game.confirm_revealed_hand_pick(0, hand_index=shock_slot)
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].hand) == ["Their Giant"]
    assert _w1g3_names(game.players[1].graveyard) == ["Their Shock"]
    assert "Kami of Ancient Law" in _w1g3_names(game.players[0].graveyard)
    assert "He Who Hungers" in [p.card.name for p in game.controlled_by(0)]


def test_w1g3_he_who_hungers_refuses_a_non_spirit_sacrifice_and_an_instant_speed_activation(set_pool):
    game = _w1g3_hungers_table(set_pool)
    bear = _w1g3_on_field(game, 0, "Their Bear")
    refused = game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[bear.permanent_id],
    )
    assert not refused.supported
    assert "Their Bear" in [p.card.name for p in game.controlled_by(0)]
    kami = _w1g3_on_field(game, 0, "Kami of Ancient Law")
    game.active_player_index = 1
    refused = game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[kami.permanent_id],
    )
    assert not refused.supported and "sorcery" in refused.details
    assert len(game.players[1].hand) == 2


def test_w1g3_he_who_hungers_sacrificing_itself_soulshifts(set_pool):
    """It is a Spirit, so it may pay its own cost — and its soulshift 4 then
    returns Kami of Twisted Reflection while the discard still happens."""
    game = _w1g3_hungers_table(set_pool)
    hungers = _w1g3_on_field(game, 0, "He Who Hungers")
    assert game.activate_permanent_ability(
        0, "He Who Hungers", target_player_index=1, cost_permanent_ids=[hungers.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Twisted Reflection"]
    assert len(game.players[1].hand) == 1 and len(game.players[1].graveyard) == 1


_W1G3_ZUBERA = (
    "Ashen-Skin Zubera", "Dripping-Tongue Zubera", "Ember-Fist Zubera",
    "Floating-Dream Zubera", "Silent-Chant Zubera",
)


def _w1g3_zubera_table(set_pool, mine, *, hand=(), interactive=()):
    game = _w1g3_table(mine=mine, hand=hand, interactive=interactive)
    island = _w1g3_card("Filler Island", 0, "Land")
    game.players[0].library = [island] * 20
    game.players[1].hand = [_w1g3_card(f"Their Card {i}", 1, "Instant") for i in range(7)]
    return game


def test_w1g3_five_zubera_swept_together_each_count_all_five(set_pool):
    """"…for each Zubera that died this turn": five die to one Wrath of God
    beside a Bear, and every trigger counts the five (itself included) and not
    the Bear — the opponent discards 5 and takes 5, its controller draws 5,
    gains 10 and makes five 1/1 colorless Spirits."""
    pool = set_pool("CHK")
    bear = _w1g3_card("My Bear", 2, "Creature — Bear")
    game = _w1g3_zubera_table(
        set_pool, [pool[name] for name in _W1G3_ZUBERA] + [bear],
        hand=[set_pool("LEA")["Wrath of God"]],
    )
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g3_settle(game)
    assert game.players[0].life == 30
    assert game.players[1].life == 15
    assert len(game.players[1].hand) == 2
    assert len(game.players[0].hand) == 5
    tokens = list(game.controlled_by(0))
    assert [p.card.name for p in tokens] == ["Spirit Token"] * 5
    assert all(
        p.effective_power == 1 and p.effective_toughness == 1
        and not p.card.colors and p.has_type("creature")
        for p in tokens
    )


def test_w1g3_an_earlier_zubera_death_this_turn_is_counted_by_a_later_one(set_pool):
    pool = set_pool("CHK")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_zubera_table(
        set_pool, [pool["Floating-Dream Zubera"], pool["Silent-Chant Zubera"]],
        hand=[shock, shock],
    )
    dream = _w1g3_on_field(game, 0, "Floating-Dream Zubera")
    chant = _w1g3_on_field(game, 0, "Silent-Chant Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[dream.permanent_id]).supported
    _w1g3_settle(game)
    assert len(game.players[0].hand) == 2  # one Shock left, one card drawn
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[chant.permanent_id]).supported
    _w1g3_settle(game)
    assert game.players[0].life == 24  # 2 life for each of the two Zubera


def test_w1g3_the_zubera_count_is_this_turns(set_pool):
    """A Zubera that died last turn is not counted: the tally resets with the
    turn."""
    pool = set_pool("CHK")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_zubera_table(
        set_pool, [pool["Ashen-Skin Zubera"], pool["Silent-Chant Zubera"]],
        hand=[shock, shock],
    )
    first = _w1g3_on_field(game, 0, "Ashen-Skin Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[first.permanent_id]).supported
    _w1g3_settle(game)
    assert len(game.players[1].hand) == 6
    game.start_turn(1)
    game._settle()
    game.start_turn(0)
    game._settle()
    chant = _w1g3_on_field(game, 0, "Silent-Chant Zubera")
    life = game.players[0].life
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[chant.permanent_id]).supported
    _w1g3_settle(game)
    assert game.players[0].life == life + 2


def test_w1g3_ember_fist_zubera_asks_an_interactive_seat_for_any_target(set_pool):
    pool = set_pool("CHK")
    giant = _w1g3_card("Their Giant", 4, "Creature — Giant", power="3", toughness="1")
    shock = _w1g3_card("Test Shock", 1, "Instant", "This spell deals 2 damage to any target.")
    game = _w1g3_table(mine=[pool["Ember-Fist Zubera"]], theirs=[giant], hand=[shock],
                       interactive=(0,))
    fist = _w1g3_on_field(game, 0, "Ember-Fist Zubera")
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[fist.permanent_id]).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    kinds = {t["kind"] for t in asked.data["targets"]}
    assert kinds == {"player", "permanent"}
    target = _w1g3_on_field(game, 1, "Their Giant")
    assert game.confirm_trigger_target(0, permanent_id=target.permanent_id)
    _w1g3_settle(game)
    assert "Their Giant" in _w1g3_names(game.players[1].graveyard)
    assert game.players[1].life == 20


def _w1g3_iname_table(set_pool, *, interactive=()):
    pool = set_pool("CHK")
    bear = _w1g3_card("Graveyard Bear", 2, "Creature — Bear")
    return _w1g3_table(
        mine=[pool["Iname, Life Aspect"]], hand=[pool["Rend Spirit"]],
        graveyard=[pool["Kami of Ancient Law"], pool["Kami of Lunacy"], bear, pool["Hana Kami"]],
        interactive=interactive,
    )


def _w1g3_kill_iname(game):
    iname = _w1g3_on_field(game, 0, "Iname, Life Aspect")
    assert game.cast_from_hand(0, "Rend Spirit", target_permanent_ids=[iname.permanent_id]).supported


def test_w1g3_iname_life_aspect_exiles_itself_and_returns_the_spirits_it_named(set_pool):
    """"…you may exile it. If you do, return any number of target Spirit cards
    from your graveyard to your hand." The targets are announced as the trigger
    goes on the stack, any number of them (an interactive seat names two of
    the three Spirit cards and not the Bear, which is not offered); the
    exile is the resolution's choice, and then exactly the named cards
    return."""
    game = _w1g3_iname_table(set_pool, interactive=(0,))
    _w1g3_kill_iname(game)
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    offered = {t["name"]: t["graveyard_index"] for t in asked.data["targets"]}
    # The 2004-12-01 ruling: Iname may target itself (to no effect).
    assert set(offered) == {
        "Kami of Ancient Law", "Kami of Lunacy", "Hana Kami", "Iname, Life Aspect",
    }
    assert asked.data.get("max_targets") == 4 and asked.data.get("up_to")
    assert game.confirm_trigger_target(
        0, seat=0,
        graveyard_indices=[offered["Kami of Ancient Law"], offered["Kami of Lunacy"]],
    )
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert sorted(_w1g3_names(game.players[0].hand)) == ["Kami of Ancient Law", "Kami of Lunacy"]
    assert _w1g3_names(game.players[0].exile) == ["Iname, Life Aspect"]
    assert "Hana Kami" in _w1g3_names(game.players[0].graveyard)


def test_w1g3_iname_declining_the_exile_returns_nothing(set_pool):
    game = _w1g3_iname_table(set_pool)
    _w1g3_kill_iname(game)
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=False),
    })
    assert game.players[0].hand == []
    assert "Iname, Life Aspect" in _w1g3_names(game.players[0].graveyard)
    assert game.players[0].exile == []


def test_w1g3_iname_may_be_exiled_with_no_target_named(set_pool):
    """The 2004-12-01 ruling: "You can exile the card even if you choose no
    targets." Naming nobody is an answer "any number" allows."""
    game = _w1g3_iname_table(set_pool, interactive=(0,))
    _w1g3_kill_iname(game)
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target"
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[])
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert game.players[0].hand == []
    assert _w1g3_names(game.players[0].exile) == ["Iname, Life Aspect"]


def _w1g3_yosei_table(set_pool, *, interactive=()):
    pool = set_pool("CHK")
    lea = set_pool("LEA")
    theirs = [lea["Hill Giant"], lea["Grizzly Bears"], lea["Forest"], lea["Forest"],
              lea["Mountain"], lea["Island"], lea["Swamp"]]
    return _w1g3_table(
        mine=[pool["Yosei, the Morning Star"], lea["Grizzly Bears"]], theirs=theirs,
        hand=[pool["Rend Spirit"]], interactive=interactive,
    )


def _w1g3_kill(game, name, spell="Rend Spirit"):
    victim = _w1g3_on_field(game, 0, name)
    assert game.cast_from_hand(0, spell, target_permanent_ids=[victim.permanent_id]).supported


def _w1g3_tapped(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.tapped)


def test_w1g3_yosei_announces_a_player_then_up_to_five_of_that_players_permanents(set_pool):
    """"When Yosei dies, target player skips their next untap step. Tap up to
    five target permanents that player controls." Both targets are chosen as
    the trigger goes on the stack (CR 603.3d): an interactive seat is asked
    for the player (and must name one), then offered only that player's
    permanents, up to five; the ones named are tapped and that player's next
    untap step is skipped, so they stay tapped through it."""
    game = _w1g3_yosei_table(set_pool, interactive=(0,))
    _w1g3_kill(game, "Yosei, the Morning Star")
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    assert {t["kind"] for t in asked.data["targets"]} == {"player"}
    assert not asked.data.get("up_to")
    assert game.confirm_trigger_target(0, seat=1)
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    offered = asked.data["targets"]
    assert {t["seat"] for t in offered} == {1} and len(offered) == 7
    assert asked.data.get("max_targets") == 5 and asked.data.get("up_to")
    named = [t["permanent_id"] for t in offered if t["name"] in ("Grizzly Bears", "Forest")]
    assert game.confirm_trigger_target(0, permanent_ids=named)
    _w1g3_settle(game)
    assert _w1g3_tapped(game, 1) == ["Forest", "Forest", "Grizzly Bears"]
    assert _w1g3_tapped(game, 0) == []
    assert game.skip_step_counts == {(1, "untap"): 1}
    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g3_tapped(game, 1) == ["Forest", "Forest", "Grizzly Bears"]
    assert game.skip_step_counts == {}
    game.start_next_turn()
    game.start_next_turn()
    assert _w1g3_tapped(game, 1) == []


def test_w1g3_yosei_at_a_default_seat_taps_five_of_the_opponents_permanents(set_pool):
    game = _w1g3_yosei_table(set_pool)
    _w1g3_kill(game, "Yosei, the Morning Star")
    _w1g3_settle(game)
    assert len(_w1g3_tapped(game, 1)) == 5
    assert _w1g3_tapped(game, 0) == []
    tapped = _w1g3_tapped(game, 1)
    game.start_next_turn()
    assert _w1g3_tapped(game, 1) == tapped


def test_w1g3_yosei_taps_even_when_its_player_becomes_an_illegal_target(set_pool):
    """Yosei's 2017-11-17 ruling: "If the player becomes an illegal target,
    the target permanents are tapped, but the player doesn't skip their untap
    step." Ivory Mask gives that player shroud before the ability resolves."""
    game = _w1g3_yosei_table(set_pool, interactive=(0,))
    _w1g3_kill(game, "Yosei, the Morning Star")
    asked = _w1g3_settle(game, defaults=False)
    assert game.confirm_trigger_target(0, seat=1)
    asked = _w1g3_settle(game, defaults=False)
    named = [t["permanent_id"] for t in asked.data["targets"] if t["name"] == "Hill Giant"]
    assert game.confirm_trigger_target(0, permanent_ids=named)
    mask = _w1g3_Permanent(card=set_pool("MMQ")["Ivory Mask"])
    game._put_permanent_onto_battlefield(1, mask, None)
    game._sync_control()
    _w1g3_settle(game)
    assert _w1g3_tapped(game, 1) == ["Hill Giant"]
    game.start_next_turn()
    assert _w1g3_tapped(game, 1) == []


def test_w1g3_two_yosei_deaths_skip_two_untap_steps(set_pool):
    """The 2017-11-17 ruling: "If more than one effect instructs a player to
    skip their next untap step, such as if Yosei dies more than once in a
    turn, that player skips that many untap steps.\""""
    pool = set_pool("CHK")
    game = _w1g3_yosei_table(set_pool)
    _w1g3_kill(game, "Yosei, the Morning Star")
    _w1g3_settle(game)
    second = _w1g3_nosick(_w1g3_Permanent(card=pool["Yosei, the Morning Star"]))
    game._put_permanent_onto_battlefield(0, second, None)
    game._sync_control()
    game.players[0].hand.append(pool["Rend Spirit"])
    _w1g3_kill(game, "Yosei, the Morning Star")
    _w1g3_settle(game)
    tapped = _w1g3_tapped(game, 1)
    assert len(tapped) == 5
    game.start_next_turn()  # B's first untap step: skipped
    game.start_next_turn()
    game.start_next_turn()  # B's second untap step: skipped
    assert _w1g3_tapped(game, 1) == tapped
    game.start_next_turn()
    game.start_next_turn()  # B's third untap step happens
    assert _w1g3_tapped(game, 1) == []


# --- W1G3's drive list: supported on arrival, driven here ------------------

_W1G3_DRAGONS = (
    "Jugan, the Rising Star", "Keiga, the Tide Star", "Kokusho, the Evening Star",
    "Ryusei, the Falling Star", "Yosei, the Morning Star",
)


def _w1g3_dragon_table(set_pool, mine, *, hand):
    lea = set_pool("LEA")
    return _w1g3_table(
        mine=mine, theirs=[lea["Hill Giant"], lea["Serra Angel"], lea["Forest"]], hand=hand,
    )


def test_w1g3_each_dragon_alone(set_pool):
    """Each Dragon destroyed by Rend Spirit, its dies trigger seen through:
    Jugan's five counters land on the Bear, Keiga steals the Hill Giant,
    Kokusho drains 5, Ryusei kills every creature without flying (the Bear and
    the Giant, not the Angel), Yosei taps the opponent's permanents."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    from engine.named_counters import counters_on as _counters_on

    outcomes = {}
    for name in _W1G3_DRAGONS:
        game = _w1g3_dragon_table(
            set_pool, [chk[name], lea["Grizzly Bears"]], hand=[chk["Rend Spirit"]],
        )
        _w1g3_kill(game, name)
        _w1g3_settle(game)
        outcomes[name] = game
    jugan = outcomes["Jugan, the Rising Star"]
    assert _counters_on(_w1g3_on_field(jugan, 0, "Grizzly Bears"), "+1/+1") == 5
    keiga = outcomes["Keiga, the Tide Star"]
    assert "Hill Giant" in [p.card.name for p in keiga.controlled_by(0)]
    kokusho = outcomes["Kokusho, the Evening Star"]
    assert (kokusho.players[0].life, kokusho.players[1].life) == (25, 15)
    ryusei = outcomes["Ryusei, the Falling Star"]
    assert [p.card.name for p in ryusei.controlled_by(0)] == []
    assert sorted(p.card.name for p in ryusei.controlled_by(1)) == ["Forest", "Serra Angel"]
    yosei = outcomes["Yosei, the Morning Star"]
    assert _w1g3_tapped(yosei, 1) == ["Forest", "Hill Giant", "Serra Angel"]


def test_w1g3_the_dragons_and_deathcurse_ogre_swept_together(set_pool):
    """All five Dragons and Deathcurse Ogre die to one Wrath of God. Every
    trigger chooses its targets once the sweep is over (CR 603.3d): Keiga and
    Jugan find no creature and are removed, Yosei names the opponent and their
    two Forests, and the rest resolve in the order they were put on the stack
    (last pushed first): the Ogre, Yosei, Ryusei (nothing left to hit),
    Kokusho."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g3_table(
        mine=[chk[name] for name in _W1G3_DRAGONS] + [chk["Deathcurse Ogre"]],
        theirs=[lea["Hill Giant"], lea["Serra Angel"], lea["Forest"], lea["Forest"]],
        hand=[lea["Wrath of God"]],
    )
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g3_settle(game)
    assert (game.players[0].life, game.players[1].life) == (22, 12)
    assert _w1g3_tapped(game, 1) == ["Forest", "Forest"]
    removed = [line for line in game.log if "was removed from the stack" in line]
    assert len(removed) == 2 and any("Keiga" in line for line in removed)
    assert any("Jugan" in line for line in removed)
    resolved = [
        line.split(" ability resolved")[0] for line in game.log if line.endswith("ability resolved")
    ]
    assert resolved == [
        "Deathcurse Ogre", "Yosei, the Morning Star", "Ryusei, the Falling Star",
        "Kokusho, the Evening Star",
    ]


def test_w1g3_ryusei_dying_to_hideous_laughter_strikes_the_survivors_without_flying(set_pool):
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g3_table(
        mine=[chk["Ryusei, the Falling Star"], lea["Grizzly Bears"]],
        theirs=[lea["Hill Giant"], lea["Serra Angel"], lea["Llanowar Elves"], lea["Craw Wurm"]],
        hand=[chk["Hideous Laughter"]],
    )
    _w1g3_on_field(game, 0, "Ryusei, the Falling Star").damage_marked = 3
    assert game.cast_from_hand(0, "Hideous Laughter").supported
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Serra Angel"]
    assert "Craw Wurm" in _w1g3_names(game.players[1].graveyard)


def test_w1g3_deathcurse_ogre_drains_each_player(set_pool):
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g3_table(mine=[chk["Deathcurse Ogre"]], hand=[lea["Lightning Bolt"]])
    _w1g3_kill(game, "Deathcurse Ogre", spell="Lightning Bolt")
    _w1g3_settle(game)
    assert (game.players[0].life, game.players[1].life) == (17, 17)


def test_w1g3_iname_death_aspect_puts_spirit_cards_into_the_graveyard(set_pool):
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g3_table(hand=[chk["Iname, Death Aspect"]])
    game.players[0].library = [
        chk["Kami of Ancient Law"], lea["Forest"], chk["Hana Kami"], lea["Island"],
    ]
    assert game.cast_from_hand(0, "Iname, Death Aspect").supported
    _w1g3_settle(game)
    assert sorted(_w1g3_names(game.players[0].graveyard)) == ["Hana Kami", "Kami of Ancient Law"]
    assert sorted(_w1g3_names(game.players[0].library)) == ["Forest", "Island"]


def test_w1g3_the_sacrifice_kami(set_pool):
    """Hana Kami returns an Arcane card (not a Bolt), Kami of Ancient Law
    destroys an enchantment, Kami of Twisted Reflection bounces only its own
    side's creature, Pain Kami deals X, Hearth Kami destroys an artifact of
    mana value X and refuses another X; Rend Spirit refuses a non-Spirit."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g3_table(
        mine=[chk["Hana Kami"]], graveyard=[chk["Glacial Ray"], lea["Lightning Bolt"]],
    )
    assert game.activate_permanent_ability(0, "Hana Kami").supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == ["Glacial Ray"]

    game = _w1g3_table(mine=[chk["Kami of Ancient Law"]], theirs=[lea["Crusade"]])
    crusade = _w1g3_on_field(game, 1, "Crusade")
    assert game.activate_permanent_ability(
        0, "Kami of Ancient Law", target_permanent_ids=[crusade.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].graveyard) == ["Crusade"]

    game = _w1g3_table(
        mine=[chk["Kami of Twisted Reflection"], lea["Grizzly Bears"]], theirs=[lea["Hill Giant"]],
    )
    giant = _w1g3_on_field(game, 1, "Hill Giant")
    assert not game.activate_permanent_ability(
        0, "Kami of Twisted Reflection", target_permanent_ids=[giant.permanent_id]
    ).supported
    bears = _w1g3_on_field(game, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(
        0, "Kami of Twisted Reflection", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == ["Grizzly Bears"]

    game = _w1g3_table(mine=[chk["Pain Kami"]], theirs=[lea["Hill Giant"]])
    giant = _w1g3_on_field(game, 1, "Hill Giant")
    assert game.activate_permanent_ability(
        0, "Pain Kami", target_permanent_ids=[giant.permanent_id], x_value=3,
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].graveyard) == ["Hill Giant"]

    game = _w1g3_table(mine=[chk["Hearth Kami"]], theirs=[lea["Jayemdae Tome"], lea["Sol Ring"]])
    tome = _w1g3_on_field(game, 1, "Jayemdae Tome")
    assert not game.activate_permanent_ability(
        0, "Hearth Kami", target_permanent_ids=[tome.permanent_id], x_value=1,
    ).supported
    assert game.activate_permanent_ability(
        0, "Hearth Kami", target_permanent_ids=[tome.permanent_id], x_value=4,
    ).supported
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Sol Ring"]

    game = _w1g3_table(theirs=[chk["Lantern Kami"], lea["Grizzly Bears"]],
                       hand=[chk["Rend Spirit"], chk["Rend Spirit"]])
    assert not game.cast_from_hand(
        0, "Rend Spirit", target_permanent_ids=[_w1g3_on_field(game, 1, "Grizzly Bears").permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Rend Spirit", target_permanent_ids=[_w1g3_on_field(game, 1, "Lantern Kami").permanent_id]
    ).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[1].graveyard) == ["Lantern Kami"]


@_w1g3_pytest.mark.parametrize("name, keyword", [
    ("Lantern Kami", "flying"), ("Moss Kami", "trample"),
    ("Kodama of the North Tree", "shroud"), ("Kami of Old Stone", None),
    ("River Kaijin", None), ("Wandering Ones", None),
])
def test_w1g3_the_plain_spirits_attack_for_their_power(set_pool, name, keyword):
    """The keyword-only and vanilla Spirits: cast from a hand, then an
    unblocked attack deals their power (Kodama's shroud refuses a Bolt)."""
    chk = set_pool("CHK")
    card = chk[name]
    game = _w1g3_table(hand=[card])
    assert game.cast_from_hand(0, name).supported
    _w1g3_settle(game)
    permanent = _w1g3_on_field(game, 0, name)
    if keyword:
        assert game._has_keyword(permanent, keyword)
    if keyword == "shroud":
        bolt = _w1g3_card("Test Bolt", 1, "Instant", "This spell deals 3 damage to any target.")
        game.players[1].hand.append(bolt)
        assert not game.cast_from_hand(
            1, "Test Bolt", target_permanent_ids=[permanent.permanent_id]
        ).supported
    from tests.helpers import declare_attack

    declare_attack(game, 0)
    _w1g3_drive_combat(game)
    assert game.players[1].life == 20 - int(card.power)

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# "Whenever you cast a Spirit or Arcane spell, <effect>" — the cast trigger
# narrowed by a union of a creature type (Spirit, CR 205.3m) and a spell type
# (Arcane, CR 205.3k) — and every effect the set hangs on it; Kitsune
# Riftwalker's "Protection from Spirits and from Arcane". Thief of Hope's
# trigger is driven on an invented one-line card: its soulshift line is W1G3's.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import CardDefinition as _W1G4Card
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                interactive=False):
    """A two-seat game on Alice's first main phase, Alice's permanents
    *mine*, Bob's *theirs*, mana costs off."""
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    placed = (
        [_w1g4_put(game, 0, card) for card in mine],
        [_w1g4_put(game, 1, card) for card in theirs],
    )
    game.start_turn(0)
    _w1g4_settle(game)
    return game, placed[0], placed[1]


def _w1g4_cast(game, seat, name, **announced):
    assert game.queue_from_hand(seat, name, **announced).supported, game.log[-5:]


def _w1g4_target(permanent):
    """An answer to a ``trigger_target`` prompt naming *permanent*."""
    return lambda game, choice: game.confirm_trigger_target(
        choice.player_index, permanent_id=permanent.permanent_id,
    )


def _w1g4_may(accept):
    return lambda game, choice: game.confirm_optional_pay(choice.player_index, accept=accept)


def _w1g4_arcane(set_pool):
    """Reach Through Mists — {U} Instant — Arcane, "Draw a card."."""
    return set_pool("CHK")["Reach Through Mists"]


@_w1g4_pytest.mark.parametrize("spell, seat, grows", [
    (("CHK", "Reach Through Mists"), 0, True),     # an Arcane instant
    (("CHK", "Kami of the Hunt"), 0, True),        # a Spirit creature spell
    (("LGN", "Mistform Ultimus"), 0, True),        # every creature type (CR 604.3)
    (("LEA", "Grizzly Bears"), 0, False),          # a Bear spell is neither
    (("LEA", "Giant Growth"), 0, False),           # an instant that is not Arcane
    (("CHK", "Reach Through Mists"), 1, False),    # an opponent's Arcane: not "you cast"
])
def test_w1g4_kami_of_the_hunt_grows_on_your_spirit_or_arcane_spells(
    set_pool, spell, seat, grows,
):
    """"Whenever you cast a Spirit or Arcane spell, this creature gets +1/+1
    until end of turn." One union over two subtype lists: a spell answers
    when it has either subtype, and Mistform Ultimus's CDA works on the
    stack."""
    code, name = spell
    game, (kami,), _ = _w1g4_table(set_pool, mine=[set_pool("CHK")["Kami of the Hunt"]])
    game.players[seat].hand.append(set_pool(code)[name])
    announced = {}
    if name == "Giant Growth":
        announced["target_permanent_ids"] = [kami.permanent_id]
    _w1g4_cast(game, seat, name, **announced)
    _w1g4_settle(game)
    bonus = 3 if name == "Giant Growth" else 0
    expected = (3 + bonus, 3 + bonus) if grows else (2 + bonus, 2 + bonus)
    assert (kami.effective_power, kami.effective_toughness) == expected, game.log


def test_w1g4_the_trigger_resolves_before_the_spell_that_fired_it(set_pool):
    """CR 603.3: the trigger goes on the stack above the Arcane spell, so the
    pump has happened while Reach Through Mists is still a spell."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kami of the Hunt"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    assert [item.card.name for item in game.stack] == [
        "Reach Through Mists", "Kami of the Hunt",
    ]
    game.resolve_top_of_stack()
    assert kami.effective_power == 3
    assert [item.card.name for item in game.stack] == ["Reach Through Mists"]


def test_w1g4_earthshaker_hits_every_creature_without_flying(set_pool):
    """"…deals 2 damage to each creature without flying": the Bears on both
    sides die, Earthshaker (4/5, no flying) is dealt 2 itself, and the Serra
    Angel is spared."""
    lea = set_pool("LEA")
    game, (shaker, angel, _bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Earthshaker"], lea["Serra Angel"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Earthshaker", "Serra Angel"]
    assert not list(game.controlled_by(1)), game.log
    assert shaker.damage_marked == 2 and angel.damage_marked == 0


def test_w1g4_guardian_of_solitude_gives_its_target_flying_for_the_turn(set_pool):
    """"…target creature gains flying until end of turn", the target chosen by
    an interactive seat as the trigger goes on the stack."""
    lea = set_pool("LEA")
    game, (_guardian, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Guardian of Solitude"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert game._has_keyword(bears, "flying"), game.log
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not game._has_keyword(bears, "flying")


def test_w1g4_horizon_seed_regenerates_its_target(set_pool):
    """"…regenerate target creature": the shield replaces the Bears'
    destruction by a Lightning Bolt's lethal damage (CR 701.19) and taps it."""
    lea = set_pool("LEA")
    game, (_seed, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool), lea["Lightning Bolt"]], interactive=True,
        mine=[set_pool("CHK")["Horizon Seed"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.regeneration_shield == 1, game.log
    _w1g4_cast(game, 0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    _w1g4_settle(game)
    assert game.is_on_battlefield(bears) and bears.tapped, game.log


def test_w1g4_innocence_kami_untaps_itself(set_pool):
    """"…untap this creature" — the {W}, {T} tapper used again the same turn."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], mine=[set_pool("CHK")["Innocence Kami"]],
    )
    kami.tapped = True
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert not kami.tapped, game.log


def test_w1g4_kami_of_fires_roar_stops_its_target_blocking(set_pool):
    """"…target creature can't block this turn": Bob's Bears can no longer
    block the Kami."""
    lea = set_pool("LEA")
    game, (kami,), (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of Fire's Roar"]], theirs=[lea["Grizzly Bears"]],
    )
    assert game._can_block_attacker(bears, kami)
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(bears, kami), game.log


def test_w1g4_kami_of_the_painted_road_takes_protection_from_the_chosen_colour(set_pool):
    """"…gains protection from the color of your choice until end of turn":
    an interactive seat names red, and Lightning Bolt can no longer target it."""
    from engine.legality import cast_spec_of

    lea = set_pool("LEA")
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Painted Road"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "color_choice": lambda g, c: g.confirm_color_choice(c.player_index, "R"),
    })
    assert ("color", "R") in game._protection_qualities(kami), game.log
    bolt = lea["Lightning Bolt"]
    offered = game._enumerate_targets(1, bolt, cast_spec_of(bolt), for_cast=True)
    assert kami.permanent_id not in {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in offered if o.get("kind") == "permanent"
    }


def test_w1g4_kami_of_the_waning_moon_gives_its_target_fear(set_pool):
    """"…target creature gains fear until end of turn": a green Bears can't
    block it, a black creature still can (CR 702.36b)."""
    lea = set_pool("LEA")
    game, (_moon, bears), (their_bears, knight) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Waning Moon"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"], lea["Black Knight"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(their_bears, bears), game.log
    assert game._can_block_attacker(knight, bears)


def test_w1g4_orbweaver_kumo_gains_forestwalk(set_pool):
    """"…this creature gains forestwalk until end of turn": unblockable while
    Bob controls a Forest."""
    lea = set_pool("LEA")
    game, (kumo,), (bears, _forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Orbweaver Kumo"]],
        theirs=[lea["Grizzly Bears"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert game._has_keyword(kumo, "forestwalk"), game.log
    assert not game._can_block_attacker(bears, kumo)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_ore_gorger_may_destroy_a_nonbasic_land(set_pool, accept):
    """"…you may destroy target nonbasic land": the Tundra is the only target
    offered (the basic Forest is not), and declining the "may" spares it."""
    lea = set_pool("LEA")
    game, _, (tundra, forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Ore Gorger"]], theirs=[lea["Tundra"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    prompt = _w1g4_settle(game, defaults=False)
    assert prompt.kind == "trigger_target"
    assert [t["permanent_id"] for t in prompt.data["targets"]] == [tundra.permanent_id]
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(tundra), "optional_pay": _w1g4_may(accept),
    })
    assert game.is_on_battlefield(tundra) is (not accept), game.log
    assert game.is_on_battlefield(forest)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_sire_of_the_storm_may_draw(set_pool, accept):
    """"…you may draw a card" — besides the card Reach Through Mists draws."""
    game, _, _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Sire of the Storm"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(accept)})
    assert len(game.players[0].hand) == (2 if accept else 1), game.log


def test_w1g4_soilshaper_animates_a_land_that_stays_a_land(set_pool):
    """"…target land becomes a 3/3 creature until end of turn. It's still a
    land." — and it is a land again, and only a land, after cleanup."""
    lea = set_pool("LEA")
    game, (_shaper, forest), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soilshaper"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(forest)})
    assert forest.is_creature and forest.has_type("land"), game.log
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not forest.is_creature and forest.has_type("land")


def test_w1g4_soul_of_magma_deals_one_damage_to_its_target(set_pool):
    """"…this creature deals 1 damage to target creature" — the interactive
    seat's choice among every creature, the Kami's own included."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soul of Magma"]], theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.damage_marked == 1, game.log


@_w1g4_pytest.mark.parametrize("start_tapped", [False, True])
def test_w1g4_teller_of_tales_taps_or_untaps_its_target(set_pool, start_tapped):
    """"…you may tap or untap target creature": an untapped Bears is tapped
    and a tapped one untapped (the other answer would change nothing)."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Teller of Tales"]], theirs=[lea["Grizzly Bears"]],
    )
    bears.tapped = start_tapped
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(bears), "optional_pay": _w1g4_may(True),
    })
    assert bears.tapped is (not start_tapped), game.log


def test_w1g4_thief_of_hopes_trigger_drains_its_target_opponent(set_pool):
    """Thief of Hope's first line on an invented card (its soulshift line is
    W1G3's): "…target opponent loses 1 life and you gain 1 life"."""
    thief = _W1G4Card(
        name="Invented Thief", mana_cost="{2}{B}", cmc=3.0,
        type_line="Creature — Spirit",
        oracle_text=(
            "Whenever you cast a Spirit or Arcane spell, target opponent "
            "loses 1 life and you gain 1 life."
        ),
        colors=("B",), color_identity=("B",), keywords=(), produced_mana=(),
        raw={"name": "Invented Thief", "type_line": "Creature — Spirit",
             "power": "2", "toughness": "2"},
    )
    game, _, _ = _w1g4_table(set_pool, hand=[_w1g4_arcane(set_pool)], mine=[thief])
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.life for p in game.players] == [21, 19], game.log


def test_w1g4_hikari_leaves_before_the_spell_and_comes_back_at_the_end_step(set_pool):
    """"…you may exile Hikari. If you do, return it … at the beginning of the
    next end step." The 2004-12-01 ruling: "it leaves the battlefield before
    the spell that triggered it resolves its ability, so it will be unaffected
    by that spell" — a Kodama's Might aimed at it has no target left, and the
    Hikari that returns is a new object (CR 400.7), a plain 4/4."""
    chk = set_pool("CHK")
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[chk["Kodama's Might"]],
        mine=[chk["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Kodama's Might", target_permanent_ids=[hikari.permanent_id])
    _w1g4_settle(game)
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].exile] == ["Hikari, Twilight Guardian"]
    game.resolve_end_step(0)
    _w1g4_settle(game)
    (back,) = list(game.controlled_by(0))
    assert back.card.name == "Hikari, Twilight Guardian" and back is not hikari
    assert (back.effective_power, back.effective_toughness) == (4, 4), game.log
    assert not game.players[0].exile


def test_w1g4_hikari_may_stay(set_pool):
    """The 2004-12-01 ruling: "You may choose not to exile Hikari."."""
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(False)})
    assert game.is_on_battlefield(hikari) and not game.players[0].exile, game.log


def test_w1g4_kodama_of_the_south_tree_pumps_each_other_creature_you_control(set_pool):
    """"…each other creature you control gets +1/+1 and gains trample until
    end of turn" — not the Kodama, not Bob's creatures."""
    lea = set_pool("LEA")
    game, (kodama, bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kodama of the South Tree"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3), game.log
    assert game._has_keyword(bears, "trample")
    assert (kodama.effective_power, kodama.effective_toughness) == (4, 4)
    assert not game._has_keyword(kodama, "trample")
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(their_bears, "trample")


def test_w1g4_kitsune_riftwalker_has_protection_from_spirits_and_arcane(set_pool):
    """"Protection from Spirits and from Arcane" (CR 702.16): Rend Flesh, an
    Arcane instant, can't target it (it can target the Bears beside it), and a
    Spirit can't block it (CR 702.16f) while the Bears can."""
    from engine.legality import cast_spec_of

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game, (fox, bears), (kami, their_bears) = _w1g4_table(
        set_pool, mine=[chk["Kitsune Riftwalker"], lea["Grizzly Bears"]],
        theirs=[chk["Kami of the Hunt"], lea["Grizzly Bears"]],
    )
    rend = chk["Rend Flesh"]
    offered = {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in game._enumerate_targets(1, rend, cast_spec_of(rend), for_cast=True)
        if o.get("kind") == "permanent"
    }
    assert fox.permanent_id not in offered
    assert bears.permanent_id in offered
    assert not game._can_block_attacker(kami, fox)
    assert game._can_block_attacker(their_bears, fox)

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== integrator ====================================================
# Whole-card tests the wave-1 split left to the integrator: a card two groups
# built halves of. Kenzo the Hardhearted is W1G1's flip face printing W1G2's
# bushido; Thief of Hope is W1G4's cast trigger beside W1G3's soulshift.
from engine import Game as _IntGame, PlayerState as _IntPlayerState
from engine.flip_cards import flip_permanent as _int_flip, is_flipped as _int_is_flipped
from engine.models import Permanent as _IntPermanent
from tests.helpers import (declare_attack as _int_declare_attack,
                           drive_combat as _int_drive_combat, settle as _int_settle)


def _int_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    game = _IntGame(players=[
        _IntPlayerState(name=f"P{seat}", library=[lea["Island"]] * 20,
                        hand=list(hand) if seat == 0 else [])
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _int_settle(game)
    return game


def _int_put(game, card, seat=0):
    permanent = _IntPermanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_int_bushi_tenderfoot_flips_into_kenzo_with_double_strike_and_bushido(set_pool):
    """Bushi Tenderfoot, pumped by Giant Growth and blocked by Llanowar Elves,
    kills the Elves; "When a creature dealt damage by this creature this turn
    dies, flip this creature" flips it (CR 710.2), and the permanent is now
    Kenzo the Hardhearted: legendary, double strike, bushido 2 — W1G2's
    keyword read off the face a flip made current."""
    lea, chk = set_pool("LEA"), set_pool("CHK")
    game = _int_table(set_pool, hand=[lea["Giant Growth"]])
    bushi = _int_put(game, chk["Bushi Tenderfoot"])
    elves = _int_put(game, lea["Llanowar Elves"], seat=1)
    assert not _int_is_flipped(bushi)
    assert not game._has_keyword(bushi, "bushido")
    _int_declare_attack(game, 0, blocks={game.battlefield_index_of(elves): 0})
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[bushi.permanent_id],
    ).supported
    _int_settle(game)
    _int_drive_combat(game)
    assert not game.is_on_battlefield(elves)
    assert _int_is_flipped(bushi)
    kenzo = bushi.effective_card
    assert (kenzo.name, kenzo.is_legendary) == ("Kenzo the Hardhearted", True)
    assert game._has_keyword(bushi, "double strike")
    assert game._has_keyword(bushi, "bushido")


def test_int_kenzo_blocks_with_bushido_two_and_strikes_twice(set_pool):
    """A flipped Kenzo (3/4) blocks a Craw Wurm (6/4): bushido 2 triggers on
    the block (CR 702.45a) and makes it 5/6, and its first-strike half of
    double strike kills the Wurm before it deals damage — Kenzo survives."""
    lea, chk = set_pool("LEA"), set_pool("CHK")
    game = _int_table(set_pool)
    kenzo = _int_put(game, chk["Bushi Tenderfoot"], seat=1)
    assert _int_flip(game, kenzo)
    assert (kenzo.effective_power, kenzo.effective_toughness) == (3, 4)
    wurm = _int_put(game, lea["Craw Wurm"], seat=0)
    _int_declare_attack(game, 0, blocks={game.battlefield_index_of(kenzo): 0})
    assert [item.ability_text for item in game.stack] == ["bushido 2"]
    _int_settle(game)
    assert (kenzo.effective_power, kenzo.effective_toughness) == (5, 6)
    _int_drive_combat(game)
    assert not game.is_on_battlefield(wurm)
    assert game.is_on_battlefield(kenzo)
    assert kenzo.damage_marked == 0


def test_int_thief_of_hope_drains_on_an_arcane_spell_and_soulshifts_when_it_dies(set_pool):
    """Thief of Hope's two halves on one card: casting Reach Through Mists (an
    Arcane instant) drains the opponent for 1 (W1G4's "Whenever you cast a
    Spirit or Arcane spell"); then Lightning Bolt kills it and soulshift 2
    (W1G3's rewrite, CR 702.46a) returns Kami of Ancient Law (a Spirit of mana
    value 2) from the graveyard to hand."""
    lea, chk = set_pool("LEA"), set_pool("CHK")
    game = _int_table(set_pool, hand=[chk["Reach Through Mists"], lea["Lightning Bolt"]])
    game.players[0].graveyard.append(chk["Kami of Ancient Law"])
    thief = _int_put(game, chk["Thief of Hope"])
    assert game.cast_from_hand(0, "Reach Through Mists").supported
    _int_settle(game)
    assert (game.players[0].life, game.players[1].life) == (21, 19)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[thief.permanent_id],
    ).supported
    _int_settle(game)
    assert not game.is_on_battlefield(thief)
    assert "Kami of Ancient Law" in [card.name for card in game.players[0].hand]
    assert "Kami of Ancient Law" not in [card.name for card in game.players[0].graveyard]
