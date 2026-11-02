"""Legions creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# Amplify (CR 702.38) — ``engine/amplify.py`` — and the two lines that read the
# +1/+1 counters it puts there (Canopy Crawler's pump, Embalmed Brawler's life
# loss), with Daru Stinger's and Kilnmouth Dragon's damage beside them. Every
# card is driven through a game: it enters from a hand holding cards that do
# and do not share a creature type with it, and the counters, the hand and the
# log are read afterwards.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.card_loader import load_catalog as _w1g1_load_catalog
from engine.face_down import (face_down_card as _w1g1_face_down_card,
                              is_face_down as _w1g1_is_face_down,
                              morph_cost as _w1g1_morph_cost,
                              turn_face_up as _w1g1_turn_face_up)
from engine.mana_payment import mana_cost_from_symbols as _w1g1_symbols
from engine.special_actions import (
    take_permanent_special_action as _w1g1_take_special_action)
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from engine.targeting import derive_activation_spec as _w1g1_activation_spec
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_CATALOG = {card.name: card for card in _w1g1_load_catalog()}

#: Every Legions card printing amplify, its N, and a hand card of a type it
#: shares — the creature type the reminder text names, so the test below
#: reads the printing it is about.
_W1G1_AMPLIFIERS = {
    "Aven Warhawk": (1, "Wingbeat Warrior"),      # Bird Soldier
    "Canopy Crawler": (1, "Glowering Rogon"),     # Beast
    "Daru Stinger": (1, "Aven Warhawk"),          # Soldier
    "Embalmed Brawler": (1, "Zombie Brute"),      # Zombie
    "Feral Throwback": (2, "Canopy Crawler"),     # Beast
    "Ghastly Remains": (1, "Embalmed Brawler"),   # Zombie
    "Glowering Rogon": (1, "Feral Throwback"),    # Beast
    "Kilnmouth Dragon": (3, "Kilnmouth Dragon"),  # Dragon
    "Zombie Brute": (1, "Ghastly Remains"),       # Zombie
}


def _w1g1_game(mine=(), theirs=(), hand=(), *, interactive=False):
    p1 = _W1G1PlayerState(name="A", hand=list(hand), battlefield=list(mine),
                          library=[_W1G1_CATALOG["Island"]] * 10)
    p2 = _W1G1PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G1_CATALOG["Island"]] * 10)
    game = _W1G1Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g1_permanent(card):
    permanent = _W1G1Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_put_from_hand(game, seat, card):
    """The road an effect takes (Dermoplasm, Tempting Wurm): out of the hand,
    onto the battlefield, no stack — the entry state is the same seam."""
    owner = game.players[seat]
    assert game.take_card_from_hand(owner, card)
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _w1g1_plus1(permanent) -> int:
    return _w1g1_counters_on(permanent, "+1/+1")


@_w1g1_pytest.mark.parametrize("name", sorted(_W1G1_AMPLIFIERS))
def test_w1g1_every_amplifier_reveals_what_shares_a_type_and_enters_bigger(set_pool, name):
    """CR 702.38a for each printing, at a seat nobody asks: every hand card
    sharing a creature type with it is revealed (two here), the others are not,
    and it enters with N +1/+1 counters for each. The revealed cards stay in
    the hand and the log names them."""
    lgn = set_pool("LGN")
    amount, kin = _W1G1_AMPLIFIERS[name]
    card = lgn[name]
    hand = [card, lgn[kin], lgn[kin], _W1G1_CATALOG["Island"], _W1G1_CATALOG["Lightning Bolt"]]
    game, p1, _p2 = _w1g1_game(hand=hand)
    permanent = _w1g1_put_from_hand(game, 0, card)
    _w1g1_resolve_stack(game)
    assert _w1g1_plus1(permanent) == 2 * amount
    assert (permanent.effective_power, permanent.effective_toughness) == (
        card.base_power + 2 * amount, card.base_toughness + 2 * amount,
    )
    assert [c.name for c in p1.hand] == [kin, kin, "Island", "Lightning Bolt"]
    assert f"A revealed {kin}, {kin} for {name}'s amplify" in game.log
    assert game.reveal_events[-1]["cards"] == [kin, kin]
    assert not game.pending_choices


def test_w1g1_a_cast_amplifier_reveals_as_it_resolves(set_pool):
    """The cast road: the spell resolves, the creature enters with its
    counters, and there is nothing on the stack to respond to (CR 614.1c)."""
    lgn = set_pool("LGN")
    game, p1, _p2 = _w1g1_game(hand=[lgn["Kilnmouth Dragon"], lgn["Kilnmouth Dragon"],
                                     _W1G1_CATALOG["Shivan Dragon"]])
    result = game.queue_from_hand(0, "Kilnmouth Dragon")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    (dragon,) = p1.battlefield
    # The other Kilnmouth and the Shivan Dragon: three counters each.
    assert _w1g1_plus1(dragon) == 6
    assert (dragon.effective_power, dragon.effective_toughness) == (11, 11)
    assert not game.stack


def test_w1g1_the_rule_is_share_a_type_not_the_reminder_text(set_pool):
    """The reminder says "for each Bird and/or Soldier card"; CR 702.38a says
    "share a creature type with it". A Bird, a Soldier and a Bird Soldier
    Warrior each count once; a Human Cleric does not."""
    lgn = set_pool("LGN")
    warhawk = lgn["Aven Warhawk"]
    hand = [warhawk, lgn["Sootfeather Flock"], lgn["Daru Stinger"],
            lgn["Wingbeat Warrior"], lgn["Daru Sanctifier"]]
    game, p1, _p2 = _w1g1_game(hand=hand)
    permanent = _w1g1_put_from_hand(game, 0, warhawk)
    assert _w1g1_plus1(permanent) == 3
    assert "Daru Sanctifier" not in game.reveal_events[-1]["cards"]


def test_w1g1_an_interactive_seat_chooses_any_number_and_is_held_to_the_offer(set_pool):
    """"Any number of" is the controller's choice: a person is asked, offered
    only the cards that share a creature type, may reveal fewer than all, and
    an answer naming a card outside the offer — or one card twice — is refused
    with the prompt kept."""
    lgn = set_pool("LGN")
    rogon = lgn["Glowering Rogon"]
    hand = [rogon, lgn["Canopy Crawler"], _W1G1_CATALOG["Island"], lgn["Feral Throwback"]]
    game, p1, _p2 = _w1g1_game(hand=hand, interactive=True)
    result = game.queue_from_hand(0, "Glowering Rogon")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    (choice,) = game.pending_choices_of("entry_reveal", 0)
    # On its way while asked (CR 614.12a), on the battlefield after.
    permanent = choice.data["permanent"]
    assert not p1.battlefield
    assert game._entry_reveal_candidates(choice) == [0, 2]
    assert _w1g1_plus1(permanent) == 0 and game.permanent_is_entering(permanent)

    assert not game.resolve_pending_choice("entry_reveal", 0, hand_indices=[1])
    assert not game.resolve_pending_choice("entry_reveal", 0, hand_indices=[0, 0])
    assert game.pending_choices_of("entry_reveal", 0)

    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[2])
    assert not game.pending_choices_of("entry_reveal", 0)
    assert _w1g1_plus1(permanent) == 1
    assert "A revealed Feral Throwback for Glowering Rogon's amplify" in game.log
    assert [c.name for c in p1.hand] == ["Canopy Crawler", "Island", "Feral Throwback"]


def test_w1g1_a_zero_zero_waits_for_its_reveal_and_dies_to_an_empty_one(set_pool):
    """Ghastly Remains is a 0/0: while its controller is still choosing it has
    not finished entering, so the state-based check leaves it alone; revealing
    nothing is a legal answer, and then it dies (CR 704.5f)."""
    lgn = set_pool("LGN")
    remains = lgn["Ghastly Remains"]
    game, p1, _p2 = _w1g1_game(hand=[remains, lgn["Zombie Brute"]], interactive=True)
    permanent = _w1g1_put_from_hand(game, 0, remains)
    game.check_state_based_actions()
    # On its way (CR 614.12a): on no battlefield, so no 0/0 to sweep.
    assert game.entry_is_awaited(permanent) and not p1.graveyard

    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[])
    assert "A revealed no cards for Ghastly Remains's amplify" in game.log
    game.check_state_based_actions()
    assert not any(p.card.name == "Ghastly Remains" for p in game.controlled_by(0))
    assert [c.name for c in p1.graveyard] == ["Ghastly Remains"]


def test_w1g1_an_empty_hand_asks_nothing(set_pool):
    lgn = set_pool("LGN")
    rogon = lgn["Glowering Rogon"]
    game, _p1, _p2 = _w1g1_game(hand=[rogon, _W1G1_CATALOG["Island"]], interactive=True)
    permanent = _w1g1_put_from_hand(game, 0, rogon)
    assert not game.pending_choices and _w1g1_plus1(permanent) == 0
    assert "A revealed no cards for Glowering Rogon's amplify" in game.log


def test_w1g1_a_copy_amplifies_as_what_it_copied(set_pool):
    """CR 707.2 and 614.12: a Clone entering as a copy of Kilnmouth Dragon has
    the Dragon's amplify 3 and reveals Dragons — not Shapeshifters."""
    lgn = set_pool("LGN")
    clone = _W1G1_CATALOG["Clone"]
    dragon = _w1g1_permanent(lgn["Kilnmouth Dragon"])
    game, p1, _p2 = _w1g1_game(
        mine=[dragon], hand=[clone, _W1G1_CATALOG["Shivan Dragon"], _W1G1_CATALOG["Clone"]],
    )
    copy = _w1g1_put_from_hand(game, 0, clone)
    _w1g1_resolve_stack(game)
    assert copy.effective_card.name == "Kilnmouth Dragon"
    assert _w1g1_plus1(copy) == 3
    assert game.reveal_events[-1]["cards"] == ["Shivan Dragon"]


def test_w1g1_a_face_down_creature_has_no_amplify_and_turning_up_is_not_entering(set_pool):
    """CR 708.2: a face-down 2/2 has no abilities, so nothing is revealed as it
    enters; CR 702.37e/708.8: turned face up it does not enter again, so its
    amplify never applies."""
    lgn = set_pool("LGN")
    rogon = lgn["Glowering Rogon"]
    game, p1, _p2 = _w1g1_game(hand=[lgn["Canopy Crawler"]])
    permanent = _W1G1Permanent(card=_w1g1_face_down_card(rogon))
    game._put_permanent_onto_battlefield(0, permanent, None)
    assert _w1g1_plus1(permanent) == 0 and not game.reveal_events
    assert _w1g1_turn_face_up(game, permanent, how="test")
    assert permanent.card is rogon and _w1g1_plus1(permanent) == 0
    assert (permanent.effective_power, permanent.effective_toughness) == (4, 4)
    assert not game.reveal_events and not game.pending_choices


def test_w1g1_under_humility_an_entering_amplifier_has_nothing_to_reveal_for(set_pool):
    """CR 614.12: whether a replacement modifies how a permanent enters is asked
    of the permanent as it will exist on the battlefield — under Humility, a
    1/1 with no abilities, so no amplify."""
    lgn = set_pool("LGN")
    rogon = lgn["Glowering Rogon"]
    humility = _w1g1_permanent(_W1G1_CATALOG["Humility"])
    game, _p1, _p2 = _w1g1_game(mine=[humility], hand=[rogon, lgn["Canopy Crawler"]])
    permanent = _w1g1_put_from_hand(game, 0, rogon)
    assert _w1g1_plus1(permanent) == 0 and not game.reveal_events


def test_w1g1_a_hand_card_conspiracy_retypes_is_revealed_as_that_type(set_pool):
    """The hand is read through the accessor that knows a card off the
    battlefield can have creature types its type line does not print
    (Conspiracy's second sentence; the same one Mistform Ultimus's "every
    creature type" belongs to). Under a Conspiracy naming Beast, a Zombie Brute
    in hand is a Beast and a Glowering Rogon reveals it."""
    lgn = set_pool("LGN")
    rogon = lgn["Glowering Rogon"]
    conspiracy = _w1g1_permanent(_W1G1_CATALOG["Conspiracy"])
    conspiracy.metadata["chosen_creature_type"] = "beast"
    game, p1, _p2 = _w1g1_game(
        mine=[conspiracy], hand=[rogon, lgn["Zombie Brute"], _W1G1_CATALOG["Lightning Bolt"]],
    )
    permanent = _w1g1_put_from_hand(game, 0, rogon)
    assert game.reveal_events[-1]["cards"] == ["Zombie Brute"]
    assert _w1g1_plus1(permanent) == 1


def test_w1g1_cards_entering_together_cannot_reveal_each_other(set_pool):
    """CR 702.38a's last sentence: "You can't reveal this card or any other
    cards that are entering the battlefield at the same time as this card."
    Tempting Wurm's opponent puts Glowering Rogon and Feral Throwback down
    together and keeps Canopy Crawler; each amplify is offered the Crawler that
    stays in the hand and never the creature entering beside it. (Moved out of
    the hand one at a time, the Rogon's reveal offered the Throwback.)"""
    lgn = set_pool("LGN")
    game, _p1, p2 = _w1g1_game(hand=[_W1G1_CATALOG["Tempting Wurm"]])
    p2.hand = [lgn["Glowering Rogon"], lgn["Feral Throwback"], lgn["Canopy Crawler"]]
    game.interactive_seats = {1}
    result = game.queue_from_hand(0, "Tempting Wurm")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert game.resolve_pending_choice("choose_cards_in_hand", 1, hand_indices=[0, 1])
    _w1g1_resolve_stack(game)
    offers = game.pending_choices_of("entry_reveal", 1)
    assert [choice.data["card_name"] for choice in offers] == [
        "Glowering Rogon", "Feral Throwback",
    ]
    for choice in offers:
        assert [p2.hand[i].name for i in game._entry_reveal_candidates(choice)] == [
            "Canopy Crawler",
        ]
    while game.pending_choices_of("entry_reveal", 1):
        assert game.resolve_pending_choice("entry_reveal", 1, hand_indices=[0])
    rogon = next(p for p in game.controlled_by(1) if p.card.name == "Glowering Rogon")
    throwback = next(p for p in game.controlled_by(1) if p.card.name == "Feral Throwback")
    assert (_w1g1_plus1(rogon), _w1g1_plus1(throwback)) == (1, 2)
    assert [c.name for c in p2.hand] == ["Canopy Crawler"]


def test_w1g1_everything_put_down_together_reveals_nothing(set_pool):
    """The same table with nothing kept back: a seat nobody asks puts all three
    Beasts down at once, so not one of them is in the hand to be revealed."""
    lgn = set_pool("LGN")
    game, _p1, p2 = _w1g1_game(hand=[_W1G1_CATALOG["Tempting Wurm"]])
    p2.hand = [lgn["Glowering Rogon"], lgn["Feral Throwback"], lgn["Canopy Crawler"]]
    result = game.queue_from_hand(0, "Tempting Wurm")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    entered = {p.card.name: _w1g1_plus1(p) for p in game.controlled_by(1)}
    assert entered == {"Glowering Rogon": 0, "Feral Throwback": 0, "Canopy Crawler": 0}
    assert not [event for event in game.reveal_events if event["seat"] == 1]


def test_w1g1_two_instances_each_reveal_on_their_own():
    """CR 702.38b: "If a creature has multiple instances of amplify, each one
    works separately." The same Beast is revealed for both."""
    from tests.helpers import _mk_card as _w1g1_mk_card

    twice = _w1g1_mk_card("Twice-Amplified Beast", "Creature — Beast", "Amplify 1\nAmplify 2")
    kin = _w1g1_mk_card("Plain Beast", "Creature — Beast", "")
    game, p1, _p2 = _w1g1_game(hand=[twice, kin])
    permanent = _w1g1_put_from_hand(game, 0, twice)
    assert _w1g1_plus1(permanent) == 3
    assert [event["cards"] for event in game.reveal_events] == [["Plain Beast"], ["Plain Beast"]]


# --- the lines that read the counters -----------------------------------------

def test_w1g1_canopy_crawler_pumps_by_its_counters_counted_on_resolution(set_pool):
    """"{T}: Target creature gets +1/+1 until end of turn for each +1/+1 counter
    on this creature." The card's ruling (2004-10-04): "The number of +1/+1
    counters for the ability is checked when the ability resolves." So a
    counter added in response raises the pump; it ends at end of turn."""
    lgn = set_pool("LGN")
    crawler_card = lgn["Canopy Crawler"]
    bears = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, p1, _p2 = _w1g1_game(mine=[bears], hand=[crawler_card, lgn["Glowering Rogon"]])
    crawler = _w1g1_put_from_hand(game, 0, crawler_card)
    crawler.metadata["summoning_sickness_turn"] = -99
    assert _w1g1_plus1(crawler) == 1
    spec = _w1g1_activation_spec(_w1g1_compile(crawler.effective_card).activated_abilities[0])
    assert spec == {"kind": "creature"}, spec
    # Announced and paid, and left on the stack the way a client's activation
    # is, so something can happen before it resolves.
    result = game.queue_permanent_ability(
        0, "Canopy Crawler", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    assert crawler.tapped and game.stack
    game.place_plus1_counters(crawler, 1)   # in response: now two
    _w1g1_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def test_w1g1_embalmed_brawler_costs_life_per_counter_when_it_attacks(set_pool):
    """"Whenever this creature attacks or blocks, you lose 1 life for each
    +1/+1 counter on it." Two Zombies revealed, two counters, two life."""
    lgn = set_pool("LGN")
    brawler_card = lgn["Embalmed Brawler"]
    game, p1, _p2 = _w1g1_game(hand=[brawler_card, lgn["Zombie Brute"], lgn["Ghastly Remains"]])
    brawler = _w1g1_put_from_hand(game, 0, brawler_card)
    assert _w1g1_plus1(brawler) == 2
    _w1g1_declare_attack(game, 0)
    _w1g1_resolve_stack(game)
    assert p1.life == 18
    assert any("Embalmed Brawler" in line and "life" in line for line in game.log)


def test_w1g1_embalmed_brawler_costs_life_when_it_blocks_too(set_pool):
    lgn = set_pool("LGN")
    brawler = _w1g1_permanent(lgn["Embalmed Brawler"])
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, p1, p2 = _w1g1_game(mine=[brawler], theirs=[attacker])
    game.place_plus1_counters(brawler, 3)
    _w1g1_declare_attack(game, 1, blocks={0: 0})
    _w1g1_resolve_stack(game)
    assert p1.life == 17


def test_w1g1_embalmed_brawler_with_no_counters_costs_nothing(set_pool):
    lgn = set_pool("LGN")
    game, p1, _p2 = _w1g1_game(hand=[lgn["Embalmed Brawler"]])
    brawler = _w1g1_put_from_hand(game, 0, lgn["Embalmed Brawler"])
    assert _w1g1_plus1(brawler) == 0
    _w1g1_declare_attack(game, 0)
    _w1g1_resolve_stack(game)
    assert p1.life == 20


def test_w1g1_daru_stinger_deals_its_counters_to_an_attacker_only(set_pool):
    """"{T}: This creature deals damage equal to the number of +1/+1 counters on
    it to target attacking or blocking creature." The picker names only
    creatures in combat; amplified by two Soldiers, it kills a 2/2 attacker."""
    lgn = set_pool("LGN")
    stinger_card = lgn["Daru Stinger"]
    attacker = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    idle = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    game, p1, p2 = _w1g1_game(theirs=[attacker], hand=[stinger_card, lgn["Aven Warhawk"],
                                                       lgn["Wingbeat Warrior"]])
    stinger = _w1g1_put_from_hand(game, 0, stinger_card)
    stinger.metadata["summoning_sickness_turn"] = -99
    assert _w1g1_plus1(stinger) == 2
    spec = _w1g1_activation_spec(_w1g1_compile(stinger.effective_card).activated_abilities[0])
    assert spec == {"kind": "creature", "any_states": ["attacking", "blocking"]}, spec
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    p2.battlefield.append(idle)
    game._sync_control()
    refused = game.activate_permanent_ability(
        0, "Daru Stinger", target_player_index=1, target_permanent_ids=[idle.permanent_id],
    )
    assert not refused.supported
    result = game.activate_permanent_ability(
        0, "Daru Stinger", target_player_index=1, target_permanent_ids=[attacker.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert not any(p is attacker for p in game.controlled_by(1))
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]


def test_w1g1_kilnmouth_dragon_deals_its_counters_to_a_player(set_pool):
    """"{T}: This creature deals damage equal to the number of +1/+1 counters
    on it to any target." One Dragon revealed: three counters, three damage."""
    lgn = set_pool("LGN")
    dragon_card = lgn["Kilnmouth Dragon"]
    game, _p1, p2 = _w1g1_game(hand=[dragon_card, _W1G1_CATALOG["Shivan Dragon"]])
    dragon = _w1g1_put_from_hand(game, 0, dragon_card)
    dragon.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(0, "Kilnmouth Dragon", target_player_index=1)
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert p2.life == 17


@_w1g1_pytest.mark.parametrize("interactive", [False, True])
def test_w1g1_ghastly_remains_buys_itself_back_from_the_graveyard(set_pool, interactive):
    """"At the beginning of your upkeep, if this card is in your graveyard, you
    may pay {B}{B}{B}. If you do, return it to your hand." Compiled on arrival;
    driven here: in the graveyard at the upkeep with three Swamps, the offer is
    paid — by a person answering yes, and by a seat nobody asks — and the card
    comes back to the hand."""
    lgn = set_pool("LGN")
    remains = lgn["Ghastly Remains"]
    swamps = [_w1g1_permanent(_W1G1_CATALOG["Swamp"]) for _ in range(3)]
    game, p1, _p2 = _w1g1_game(mine=swamps, interactive=interactive)
    p1.graveyard.append(remains)
    game.enforce_mana_costs = True
    game.turn = 2
    game.start_turn(0)
    (offer,) = game.pending_choices_of("optional_pay", 0)
    assert offer.data["cost"] == {"B": 3}
    if interactive:
        assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    else:
        game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)
    assert any(c.name == "Ghastly Remains" for c in p1.hand), game.log[-10:]
    assert not any(c.name == "Ghastly Remains" for c in p1.graveyard)
    assert all(swamp.tapped for swamp in swamps)


# --- supported on arrival: the morph cards in this family, driven --------------
#
# Each is cast face down for {3}, turned face up for exactly its printed morph
# cost by the CR 702.37e special action, and its "When this creature is turned
# face up" trigger (CR 708.8: it does not enter, so nothing else fires) resolved
# against a board that gives its target somewhere to land.


def _w1g1_pool_for(cost: str) -> dict:
    pool: dict = {}
    for symbol, count in _w1g1_symbols(cost).items():
        key = "C" if symbol == "generic" else symbol
        pool[key] = pool.get(key, 0) + count
    return pool


def _w1g1_cast_down(game, seat, name, card):
    player = game.players[seat]
    player.hand.append(card)
    player.mana_pool.update({"C": 3})
    result = game.queue_from_hand(seat, name, alternative_cost=True)
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    (permanent,) = [p for p in game.controlled_by(seat) if _w1g1_is_face_down(p)]
    assert (permanent.effective_power, permanent.effective_toughness) == (2, 2)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_turn_up(game, seat, permanent, card):
    player = game.players[seat]
    game.priority_player_index = seat
    player.mana_pool.update(_w1g1_pool_for(_w1g1_morph_cost(card)))
    refusal = _w1g1_take_special_action(game, seat, permanent, "turn_face_up")
    assert refusal is None, refusal
    assert sum(player.mana_pool.values()) == 0, "paid exactly its morph cost"
    assert permanent.card is card and not _w1g1_is_face_down(permanent)
    return permanent


def _w1g1_cast_down_and_turn_up(game, seat, name, card):
    return _w1g1_turn_up(game, seat, _w1g1_cast_down(game, seat, name, card), card)


def _w1g1_morph_board():
    bears = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    moon = _w1g1_permanent(_W1G1_CATALOG["Bad Moon"])
    mountain = _w1g1_permanent(_W1G1_CATALOG["Mountain"])
    game, p1, p2 = _w1g1_game(theirs=[bears, moon, mountain])
    game.enforce_mana_costs = True
    return game, p1, p2, bears, moon, mountain


def test_w1g1_aphetto_exterminator_shrinks_a_creature_by_three(set_pool):
    game, _p1, p2, bears, _moon, _mountain = _w1g1_morph_board()
    _w1g1_cast_down_and_turn_up(game, 0, "Aphetto Exterminator", set_pool("LGN")["Aphetto Exterminator"])
    _w1g1_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (-1, -1)
    game.check_state_based_actions()
    assert not any(p is bears for p in game.controlled_by(1))
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]


def test_w1g1_daru_sanctifier_destroys_an_enchantment(set_pool):
    game, _p1, p2, _bears, moon, _mountain = _w1g1_morph_board()
    _w1g1_cast_down_and_turn_up(game, 0, "Daru Sanctifier", set_pool("LGN")["Daru Sanctifier"])
    _w1g1_resolve_stack(game)
    assert not any(p is moon for p in game.controlled_by(1))
    assert [c.name for c in p2.graveyard] == ["Bad Moon"]


def test_w1g1_nantuko_vigilante_destroys_an_artifact_or_enchantment(set_pool):
    game, _p1, p2, _bears, _moon, _mountain = _w1g1_morph_board()
    _w1g1_cast_down_and_turn_up(game, 0, "Nantuko Vigilante", set_pool("LGN")["Nantuko Vigilante"])
    _w1g1_resolve_stack(game)
    assert [c.name for c in p2.graveyard] == ["Bad Moon"]


def test_w1g1_shaleskin_plower_destroys_a_land(set_pool):
    game, _p1, p2, _bears, _moon, _mountain = _w1g1_morph_board()
    _w1g1_cast_down_and_turn_up(game, 0, "Shaleskin Plower", set_pool("LGN")["Shaleskin Plower"])
    _w1g1_resolve_stack(game)
    assert [c.name for c in p2.graveyard] == ["Mountain"]


def test_w1g1_echo_tracer_returns_a_creature_to_its_owners_hand(set_pool):
    game, _p1, p2, bears, _moon, _mountain = _w1g1_morph_board()
    _w1g1_cast_down_and_turn_up(game, 0, "Echo Tracer", set_pool("LGN")["Echo Tracer"])
    _w1g1_resolve_stack(game)
    assert not any(p is bears for p in game.controlled_by(1))
    assert [c.name for c in p2.hand] == ["Grizzly Bears"]


def test_w1g1_skirk_marauder_deals_two_damage_to_a_player(set_pool):
    """Asked as a person, so the target is the one named: the opponent."""
    game, _p1, p2, _bears, _moon, _mountain = _w1g1_morph_board()
    game.interactive_seats = {0}
    _w1g1_cast_down_and_turn_up(game, 0, "Skirk Marauder", set_pool("LGN")["Skirk Marauder"])
    assert game.confirm_trigger_target(0, seat=1)
    _w1g1_resolve_stack(game)
    assert p2.life == 18


def test_w1g1_patron_of_the_wild_pumps_a_creature(set_pool):
    game, _p1, _p2, _bears, _moon, _mountain = _w1g1_morph_board()
    patron = _w1g1_cast_down_and_turn_up(game, 0, "Patron of the Wild", set_pool("LGN")["Patron of the Wild"])
    _w1g1_resolve_stack(game)
    assert (patron.effective_power, patron.effective_toughness) == (4, 4)


def test_w1g1_wingbeat_warrior_grants_first_strike(set_pool):
    game, _p1, _p2, _bears, _moon, _mountain = _w1g1_morph_board()
    warrior = _w1g1_cast_down_and_turn_up(game, 0, "Wingbeat Warrior", set_pool("LGN")["Wingbeat Warrior"])
    _w1g1_resolve_stack(game)
    assert warrior.has_keyword("first strike") and warrior.has_keyword("flying")


def test_w1g1_defender_of_the_order_pumps_its_side(set_pool):
    game, p1, _p2, _bears, _moon, _mountain = _w1g1_morph_board()
    ally = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    p1.battlefield.append(ally)
    game._sync_control()
    defender = _w1g1_cast_down_and_turn_up(game, 0, "Defender of the Order", set_pool("LGN")["Defender of the Order"])
    _w1g1_resolve_stack(game)
    assert (defender.effective_power, defender.effective_toughness) == (2, 6)
    assert (ally.effective_power, ally.effective_toughness) == (2, 4)


def test_w1g1_skinthinner_names_only_a_nonblack_creature_that_cannot_regenerate(set_pool):
    """"…destroy target nonblack creature. It can't be regenerated." Asked as a
    person: a black creature is refused as the target, and the regeneration
    shield on the green one does not save it."""
    lgn = set_pool("LGN")
    bears = _w1g1_permanent(_W1G1_CATALOG["Grizzly Bears"])
    zombies = _w1g1_permanent(_W1G1_CATALOG["Scathe Zombies"])
    game, _p1, p2 = _w1g1_game(theirs=[bears, zombies], interactive=True)
    game.enforce_mana_costs = True
    bears.regeneration_shield = 1
    _w1g1_cast_down_and_turn_up(game, 0, "Skinthinner", lgn["Skinthinner"])
    assert game.pending_choices_of("trigger_target", 0)
    assert not game.confirm_trigger_target(0, permanent_id=zombies.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id)
    _w1g1_resolve_stack(game)
    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
    assert any(p is zombies for p in game.controlled_by(1))


def test_w1g1_skinthinner_turned_up_with_only_shielded_targets_leaves_the_stack(set_pool):
    """White Knight has protection from black and Black Knight is black, so the
    face-up trigger has no legal target and is removed (CR 603.3d)."""
    game, _p1, p2 = _w1g1_game(theirs=[_w1g1_permanent(_W1G1_CATALOG["White Knight"]),
                                       _w1g1_permanent(_W1G1_CATALOG["Black Knight"])])
    game.enforce_mana_costs = True
    _w1g1_cast_down_and_turn_up(game, 0, "Skinthinner", set_pool("LGN")["Skinthinner"])
    assert not game.stack and not p2.graveyard
    assert any("no legal target" in line for line in game.log)


@_w1g1_pytest.mark.parametrize("name, keyword", [
    ("Branchsnap Lorian", "trample"), ("Rockshard Elemental", "double strike"),
    ("Sootfeather Flock", "flying"),
])
def test_w1g1_a_keyword_morph_has_its_keyword_only_face_up(set_pool, name, keyword):
    card = set_pool("LGN")[name]
    game, _p1, _p2 = _w1g1_game()
    game.enforce_mana_costs = True
    down = _w1g1_cast_down(game, 0, name, card)
    assert not down.has_keyword(keyword)
    _w1g1_turn_up(game, 0, down, card)
    assert down.has_keyword(keyword)
    assert (down.effective_power, down.effective_toughness) == (card.base_power, card.base_toughness)


@_w1g1_pytest.mark.parametrize("pays", [True, False])
def test_w1g1_krosan_cloudscraper_is_kept_only_by_paying_its_upkeep(set_pool, pays):
    """"At the beginning of your upkeep, sacrifice this creature unless you pay
    {G}{G}." Turned face up for {7}{G}{G}, it is a 13/13; at the next upkeep a
    person pays with two Forests and keeps it, or declines and loses it."""
    card = set_pool("LGN")["Krosan Cloudscraper"]
    forests = [_w1g1_permanent(_W1G1_CATALOG["Forest"]) for _ in range(2)]
    game, _p1, _p2 = _w1g1_game(mine=forests, interactive=True)
    game.enforce_mana_costs = True
    scraper = _w1g1_cast_down_and_turn_up(game, 0, "Krosan Cloudscraper", card)
    assert (scraper.effective_power, scraper.effective_toughness) == (13, 13)
    game.turn = 2
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    # The upkeep's pay-or-sacrifice is answered through the step's own answer
    # map (``resolve_upkeep``'s ``human_choices``, what the web layer sends).
    game.resolve_upkeep(0, human_choices={scraper.permanent_id: pays})
    _w1g1_resolve_stack(game)
    assert any(p is scraper for p in game.controlled_by(0)) is pays
    assert all(forest.tapped for forest in forests) is pays


# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Provoke (CR 702.39) and the cards that print or grant it. The rule's own
# clauses (the "may", "this combat", CR 702.39b, the multiplayer defending
# player) are tested once in tests/rules/test_lgn_w1g2_provoke.py; each test
# here is what one card adds to them, driven through a real combat.

from engine import PlayerState as _w1g2_PlayerState
from engine.ai_declarations import choose_combat_blockers as _w1g2_choose_blockers
from engine.combat_permissions import (
    MUST_BLOCK_ATTACKERS_THIS_COMBAT as _W1G2_PROVOKED,
)
from engine.game import Game as _w1g2_Game
from engine.models import CardDefinition as _w1g2_CardDefinition
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile

from tests.helpers import (_mk_creature_card as _w1g2_creature,
                           _nosick as _w1g2_nosick,
                           resolve_stack as _w1g2_resolve_stack)


def _w1g2_typed(name, type_line, power, toughness, oracle_text=""):
    return _w1g2_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g2_table(attackers, defenders, *, interactive=(), tapped=(), sick=()):
    """*attackers* on seat 0, *defenders* on seat 1, at seat 0's
    declare-attackers step. *tapped* are defender slots; *sick* are attacker
    slots that arrived this turn (CR 302.6)."""
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(name="P0", library=[_w1g2_creature("Filler", 1, 1)] * 3),
        _w1g2_PlayerState(name="P1", library=[_w1g2_creature("Filler", 1, 1)] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    mine = []
    for slot, card in enumerate(attackers):
        perm = _w1g2_Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        if slot not in sick:
            _w1g2_nosick(perm)
        mine.append(perm)
    theirs = []
    for slot, card in enumerate(defenders):
        perm = _w1g2_Permanent(card=card)
        game._put_permanent_onto_battlefield(1, perm, None)
        perm.tapped = slot in tapped
        theirs.append(perm)
    _w1g2_resolve_stack(game)
    game.start_turn(0)
    for slot in sick:
        mine[slot].metadata["summoning_sickness_turn"] = game.turn
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game, mine, theirs


def _w1g2_provoke(game, target, *, accept=True):
    """Seat 0 (interactive) names *target* for the one provoke on the stack
    and answers the "may"."""
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=target.permanent_id
    )
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=accept)
    _w1g2_resolve_stack(game)


def _w1g2_settle(game):
    """Resolve and answer as a seat nobody asks would."""
    for _ in range(10):
        _w1g2_resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


def _w1g2_finish_combat(game):
    """Step through the rest of combat — bounded, so a step that will not
    advance fails the test naming what it waits on instead of hanging it."""
    for _ in range(12):
        if game.current_turn_phase != "combat":
            return
        game.advance_combat_phase()
    raise AssertionError(
        f"combat did not end: step {game.current_step!r}, waiting on "
        f"{game.waiting_prompt()!r}"
    )


def test_w1g2_every_provoke_card_compiles_one_provoke_trigger(set_pool):
    """The seven cards printing the keyword each carry exactly one provoke
    ability (CR 702.39a), and nothing else on them is dropped: the keyword
    line beside it, Deftblade Elite's prevention, Swooping Talon's flying
    toggle and Krosan Vorine's ceiling all compile too."""
    pool = set_pool("LGN")
    for name in ("Brontotherium", "Crested Craghorn", "Deftblade Elite",
                 "Goblin Grappler", "Krosan Vorine", "Lowland Tracker",
                 "Swooping Talon"):
        program = _w1g2_compile(pool[name])
        assert program.supported, (name, program.reason)
        provokes = [t for t in program.triggered_abilities if t.source_line == "provoke"]
        assert len(provokes) == 1, name
        assert provokes[0].condition.kind == "creature_attacks"
    assert [a.instruction.kind for a in _w1g2_compile(pool["Deftblade Elite"]).activated_abilities] == [
        "prevent_damage_to_target_until_eot"
    ]
    assert [a.instruction.kind for a in _w1g2_compile(pool["Swooping Talon"]).activated_abilities] == [
        "remove_self_keyword"
    ]
    assert any(
        i.kind == "cant_be_blocked_by_more_than"
        for i in _w1g2_compile(pool["Krosan Vorine"]).instructions
    )


def test_w1g2_goblin_grappler_drags_a_tapped_blocker_into_the_fight(set_pool):
    """Goblin Grappler, 1/1. Its controller provokes the tapped Bear: the Bear
    untaps and must block, and does — the one way a tapped creature comes to
    block at all."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, (attacker,), (bear,) = _w1g2_table(
        [grappler], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert attacker not in game.players[0].battlefield, "the Bear kills the Grappler"
    assert game.players[1].life == 20


def test_w1g2_goblin_grappler_declines_a_provoke_it_would_lose(set_pool):
    """A seat nobody asks: the Grappler's only target is a 2/2 that would kill
    it, so the "may" is declined — the Bear stays tapped and the Grappler's
    point of damage goes through."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, (attacker,), (bear,) = _w1g2_table(
        [grappler], [_w1g2_creature("Bear", 2, 2)], tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game)
    assert bear.tapped
    assert any("declined Goblin Grappler" in line for line in game.log)
    game.advance_combat_phase()
    assert _w1g2_choose_blockers(game, 1) == {}
    assert game.declare_blockers(1, {})[0]
    _w1g2_finish_combat(game)
    assert game.players[1].life == 19


def test_w1g2_lowland_tracker_provokes_the_creature_its_first_strike_kills(set_pool):
    """Lowland Tracker, 2/2 first strike. A seat nobody asks names the 2/2 —
    first strike kills it before it strikes back — not the 0/4 it cannot hurt
    or the 3/3 that survives. The defending AI obeys the requirement."""
    tracker = set_pool("LGN")["Lowland Tracker"]
    game, (attacker,), (wall, bear, ogre) = _w1g2_table(
        [tracker],
        [_w1g2_creature("Wall", 0, 4), _w1g2_creature("Bear", 2, 2),
         _w1g2_creature("Ogre", 3, 3)],
        tapped=(1,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game)
    assert any("Lowland Tracker: targets Bear" in line for line in game.log)
    assert not bear.tapped
    assert bear.metadata[_W1G2_PROVOKED] == [attacker.permanent_id]
    game.advance_combat_phase()
    blocks = _w1g2_choose_blockers(game, 1)
    assert blocks.get(1) == 0, blocks
    assert game.declare_blockers(1, blocks)[0], game.log
    # The fight the provoke bought, alone: a declaration with the Bear
    # blocking by itself is legal, and first strike kills it before it
    # strikes back.
    game2, (attacker2,), (_w2, bear2, _o2) = _w1g2_table(
        [tracker],
        [_w1g2_creature("Wall", 0, 4), _w1g2_creature("Bear", 2, 2),
         _w1g2_creature("Ogre", 3, 3)],
        tapped=(1,),
    )
    assert game2.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game2)
    game2.advance_combat_phase()
    assert game2.declare_blockers(1, {1: 0})[0], game2.log
    _w1g2_finish_combat(game2)
    assert bear2 not in game2.players[1].battlefield
    assert attacker2 in game2.players[0].battlefield
    assert attacker2.damage_marked == 0, "first strike: the Bear never struck"


def test_w1g2_brontotherium_tramples_over_the_creature_it_provoked(set_pool):
    """Brontotherium, 5/3 trample. Provoked, the Bear blocks it; lethal
    damage to the Bear is 2 and the other 3 trample over (CR 702.19b).

    The attacker's seat is a person's, so how much tramples over is its to
    say (CR 510.1c–d, `Game.trample_assignments_to_ask`): it answers
    lethal-then-the-rest."""
    bronto = set_pool("LGN")["Brontotherium"]
    game, (attacker,), (bear,) = _w1g2_table(
        [bronto], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    for _ in range(6):
        if game.trample_assignments_to_ask(0):
            break
        game.advance_combat_phase()
    assert game.trample_assignments_to_ask(0) == [0]
    assert game.resolve_combat_damage(0, attacker_damage={0: {0: 2}})[0]
    _w1g2_finish_combat(game)
    assert bear not in game.players[1].battlefield
    assert game.players[1].life == 17
    assert attacker in game.players[0].battlefield


def test_w1g2_crested_craghorn_provokes_the_turn_it_arrives(set_pool):
    """Crested Craghorn, 4/1 haste: it attacks the turn it enters (CR 702.10b)
    and its provoke triggers like anyone's."""
    craghorn = set_pool("LGN")["Crested Craghorn"]
    game, (attacker,), (bear,) = _w1g2_table(
        [craghorn], [_w1g2_creature("Wall", 0, 3)], interactive=(0, 1), tapped=(0,),
        sick=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0], game.log
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert bear not in game.players[1].battlefield, "4 damage kills the 0/3"


def test_w1g2_deftblade_elite_provokes_and_then_prevents_the_fight(set_pool):
    """Deftblade Elite, 1/1: provoke a 4/4, then "{1}{W}: Prevent all combat
    damage that would be dealt to and dealt by this creature this turn." The
    4/4 is held in the block and neither creature is hurt."""
    elite = set_pool("LGN")["Deftblade Elite"]
    game, (attacker,), (giant,) = _w1g2_table(
        [elite], [_w1g2_creature("Giant", 4, 4)], interactive=(0, 1),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, giant)
    assert game.activate_permanent_ability(0, "Deftblade Elite", ability_index=0).supported
    _w1g2_resolve_stack(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert attacker in game.players[0].battlefield
    assert attacker.damage_marked == 0 and giant.damage_marked == 0
    assert giant in game.players[1].battlefield


def test_w1g2_swooping_talon_compels_only_once_it_lands(set_pool):
    """Swooping Talon, a 2/6 flier. The Bear it provokes cannot block a flier
    (CR 702.9b), so the requirement binds nothing (CR 509.1c) — until "{1}:
    This creature loses flying until end of turn" brings it down, and then
    the Bear must block."""
    talon = set_pool("LGN")["Swooping Talon"]
    game, (attacker,), (bear,) = _w1g2_table(
        [talon], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    assert game.block_requirement_refusal(1, {}) is None, "a flier it cannot block"
    assert game.activate_permanent_ability(0, "Swooping Talon", ability_index=0).supported
    _w1g2_resolve_stack(game)
    assert not game._has_keyword(attacker, "flying")
    game.advance_combat_phase()
    assert game.declare_blockers(1, {}) == (
        False, "Bear must block Swooping Talon this combat if able"
    )
    assert game.declare_blockers(1, {0: 0})[0]


def test_w1g2_krosan_vorine_is_blocked_by_its_provoked_creature_alone(set_pool):
    """Krosan Vorine: provoke, and "This creature can't be blocked by more
    than one creature." The provoked Bear must block it and a second blocker
    may not join — and the defending AI, offered two creatures that both
    like the block, declares the compelled one alone."""
    vorine = set_pool("LGN")["Krosan Vorine"]
    game, (attacker,), (bear, other) = _w1g2_table(
        [vorine], [_w1g2_creature("Bear", 2, 2), _w1g2_creature("Other Bear", 2, 2)],
        interactive=(0,), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0] is False
    assert game.declare_blockers(1, {1: 0})[0] is False, "the Bear is the one owed"
    blocks = _w1g2_choose_blockers(game, 1)
    assert blocks == {0: 0}, blocks
    assert game.declare_blockers(1, blocks)[0], game.log


def test_w1g2_the_ai_respects_a_blocker_ceiling_with_no_requirement(set_pool):
    """Krosan Vorine's ceiling with provoke declined: two Bears that each like
    the block. The AI proposed both, the declaration was refused whole, and
    the seat blocked with nobody (SET_PLAYBOOK's "The AI proposes blocks past
    an attacker's blocker ceiling"); it keeps the better one now."""
    vorine = set_pool("LGN")["Krosan Vorine"]
    game, (attacker,), (bear_a, bear_b) = _w1g2_table(
        [vorine], [_w1g2_creature("Bear A", 2, 2), _w1g2_creature("Bear B", 2, 2)],
        interactive=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear_a, accept=False)
    game.advance_combat_phase()
    assert not game.block_requirements(1)
    blocks = _w1g2_choose_blockers(game, 1)
    assert len(blocks) == 1, blocks
    assert game.declare_blockers(1, blocks)[0], game.log


def test_w1g2_hunter_sliver_gives_every_sliver_provoke(set_pool):
    """Hunter Sliver: "All Sliver creatures have provoke." Itself, another
    Sliver of its controller's and an opponent's Sliver each have the keyword
    and the trigger (CR 613.1f); a non-Sliver does not. The grant is a grant
    of the line, so the Sliver that attacks puts a provoke on the stack."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    mine = _w1g2_typed("Test Sliver", "Creature — Sliver", 2, 2)
    theirs = _w1g2_typed("Their Sliver", "Creature — Sliver", 2, 2)
    game, (lord, sliver, bear), (their_sliver, wall) = _w1g2_table(
        [hunter, mine, _w1g2_creature("Bear", 2, 2)],
        [theirs, _w1g2_creature("Wall", 0, 4)],
        interactive=(0, 1), tapped=(1,),
    )
    game.check_state_based_actions()
    for perm in (lord, sliver, their_sliver):
        assert game._has_keyword(perm, "provoke"), perm.card.name
        assert any(
            t.source_line == "provoke"
            for t in _w1g2_compile(perm.effective_card).triggered_abilities
        ), perm.card.name
    assert not game._has_keyword(bear, "provoke")
    assert game.declare_attackers(0, [1, 2], 1)[0]
    provokes = [item for item in game.stack if item.ability_text == "provoke"]
    assert [item.source_permanent for item in provokes] == [sliver]
    _w1g2_provoke(game, wall)
    assert not wall.tapped
    assert wall.metadata[_W1G2_PROVOKED] == [sliver.permanent_id]


def test_w1g2_hunter_sliver_leaving_takes_provoke_with_it(set_pool):
    """CR 611.3a: the grant applies while Hunter Sliver is on the battlefield
    and stops when it leaves — the Sliver's next attack triggers nothing."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    mine = _w1g2_typed("Test Sliver", "Creature — Sliver", 2, 2)
    game, (lord, sliver), _theirs = _w1g2_table(
        [hunter, mine], [_w1g2_creature("Bear", 2, 2)],
    )
    game.check_state_based_actions()
    assert game._has_keyword(sliver, "provoke")
    game.remove_from_battlefield(lord)
    game.check_state_based_actions()
    assert not game._has_keyword(sliver, "provoke")
    assert game.declare_attackers(0, [0], 1)[0]
    assert not [item for item in game.stack if item.ability_text == "provoke"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# The Slivers: six statics and triggers about every Sliver on the battlefield
# (any controller — "All Slivers", CR 205.3m and each card's 2013-07-01
# ruling), driven on two-seat boards so a grant that reached only its own
# controller's creatures, or a trigger that paid the wrong seat, shows up as a
# number on the other side of the table.
import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import (declare_attack as _w1g3_declare_attack,
                           resolve_stack as _w1g3_resolve_stack)


def _w1g3_card(set_pool, name):
    """A Legions card, else the shipped pool's (the opposing bodies)."""
    lgn = set_pool("LGN")
    if name in lgn:
        return lgn[name]
    for code in ("LEA", "ONS", "M10", "TMP", "4ED"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_board(set_pool, mine, theirs=(), *, interactive=()):
    """Seat 0 controls *mine* and seat 1 *theirs*, none summoning sick, in a
    main phase of seat 0's turn, with the layers recomputed."""
    seats = [_w1g3_PlayerState(name="A"), _w1g3_PlayerState(name="B")]
    game = _w1g3_Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, names in ((seats[0], mine), (seats[1], theirs)):
        for name in names:
            permanent = _w1g3_Permanent(card=_w1g3_card(set_pool, name))
            permanent.metadata["summoning_sickness_turn"] = -99
            seat.battlefield.append(permanent)
    for seat in seats:
        seat.library.extend([_w1g3_card(set_pool, "Grizzly Bears")] * 5)
    game._recompute_continuous_effects()
    return game, seats


def _w1g3_fight(game, attacker_seat, blocks=None, *, answer=None):
    """Declare every untapped creature of *attacker_seat* attacking, *blocks*
    blocking, and play the combat out — answering each prompt an interactive
    seat is owed with *answer* (a callable of the choice) and defaulting the
    rest — then drain the stack."""
    _w1g3_declare_attack(game, attacker_seat, blocks=blocks)
    for _ in range(40):
        if game.current_turn_phase != "combat":
            break
        if game.pending_choices:
            choice = game.pending_choices[0]
            if answer is not None and choice.player_index in game.interactive_seats:
                assert answer(choice), choice.kind
            else:
                game.auto_resolve_pending_choices()
            continue
        game.advance_combat_phase()
    _w1g3_resolve_stack(game)
    while game.pending_choices:
        choice = game.pending_choices[0]
        if answer is not None and choice.player_index in game.interactive_seats:
            assert answer(choice), choice.kind
        else:
            game.auto_resolve_pending_choices()
    _w1g3_resolve_stack(game)


# --- Essence Sliver: "its controller" is the damaging Sliver's -------------


def test_w1g3_essence_sliver_heals_each_slivers_own_controller(set_pool):
    """"Whenever a Sliver deals damage, its controller gains that much life."
    Any damage, to any recipient, by any Sliver — and the life goes to the
    controller of the Sliver that dealt it, not to Essence Sliver's
    controller (who controls the trigger). A's Essence Sliver (4/4 under Blade
    Sliver) hits B for 4; A's Blade Sliver (3/3 under its own +1/+0 and
    Plated's +0/+1) deals 3 to B's blocking Plated Sliver; B's Plated Sliver
    deals 2 back — and B gains that 2."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Essence Sliver", "Blade Sliver"], ["Plated Sliver", "Grizzly Bears"],
    )
    _w1g3_fight(game, 0, blocks={0: 1})
    gains = [line for line in game.log if "life from Essence Sliver" in line]
    assert sorted(gains) == sorted([
        "A gained 4 life from Essence Sliver (20 -> 24)",
        "A gained 3 life from Essence Sliver (24 -> 27)",
        "B gained 2 life from Essence Sliver (16 -> 18)",
    ]), gains
    assert (a.life, b.life) == (27, 18)


def test_w1g3_essence_sliver_ignores_a_non_sliver(set_pool):
    """The damager is narrowed to a Sliver: B's Grizzly Bears hitting A heals
    nobody, while the Essence Sliver blocking it heals A for the 4 it deals."""
    game, (a, b) = _w1g3_board(set_pool, ["Essence Sliver"], ["Grizzly Bears"])
    _w1g3_fight(game, 1, blocks={0: 0})
    assert [line for line in game.log if "life from Essence Sliver" in line] == [
        "A gained 3 life from Essence Sliver (20 -> 23)",
    ]
    assert (a.life, b.life) == (23, 20)


# --- Brood / Synapse Sliver: the Sliver's controller decides and gets it ---


def _w1g3_accept(choice):
    return _w1g3_answer_offer(choice, True)


def _w1g3_decline(choice):
    return _w1g3_answer_offer(choice, False)


def _w1g3_answer_offer(choice, accept):
    return _w1g3_answer_offer.game.resolve_pending_choice(
        choice.kind, choice.player_index, accept=accept,
    )


@_w1g3_pytest.mark.parametrize("interactive", [False, True])
def test_w1g3_brood_sliver_token_goes_to_the_damaging_slivers_controller(
    set_pool, interactive,
):
    """Brood Sliver's 2004-10-04 ruling: "This card's controller controls the
    triggered ability, but the controller of the Sliver that deals damage to a
    player decides whether or not to put the token onto the battlefield under
    their control." A controls Brood Sliver; B's Plated Sliver hits A. The
    offer is B's and so is the token — it went to A before this round."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Brood Sliver"], ["Plated Sliver"],
        interactive={1} if interactive else (),
    )
    _w1g3_answer_offer.game = game
    asked = []

    def answer(choice):
        asked.append((choice.kind, choice.player_index))
        return _w1g3_accept(choice)

    _w1g3_fight(game, 1, answer=answer)
    if interactive:
        assert asked == [("optional_pay", 1)]
    assert [p.card.name for p in a.battlefield] == ["Brood Sliver"]
    assert sorted(p.card.name for p in b.battlefield) == ["Plated Sliver", "Sliver Token"]


def test_w1g3_brood_sliver_declined_makes_no_token(set_pool):
    game, (a, b) = _w1g3_board(
        set_pool, ["Brood Sliver"], ["Plated Sliver"], interactive={1},
    )
    _w1g3_answer_offer.game = game
    _w1g3_fight(game, 1, answer=_w1g3_decline)
    assert [p.card.name for p in game.all_permanents()] == ["Brood Sliver", "Plated Sliver"]


def test_w1g3_synapse_sliver_draws_for_the_damaging_slivers_controller(set_pool):
    """"…its controller may draw a card." B's Sliver hit A, so B draws."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Synapse Sliver"], ["Plated Sliver"], interactive={1},
    )
    _w1g3_answer_offer.game = game
    _w1g3_fight(game, 1, answer=_w1g3_accept)
    assert (len(a.hand), len(b.hand)) == (0, 1)


def test_w1g3_synapse_sliver_draws_its_own_controller_a_card(set_pool):
    """…and A's own Sliver hitting B draws A the card (a default seat)."""
    game, (a, b) = _w1g3_board(set_pool, ["Synapse Sliver"], ["Plated Sliver"])
    _w1g3_fight(game, 0)
    assert (len(a.hand), len(b.hand)) == (1, 0)


# --- Ward Sliver: protection from the colour the lord chose ----------------


def _w1g3_cast_ward_sliver(set_pool, *, interactive, color=None):
    game, seats = _w1g3_board(
        set_pool, ["Blade Sliver"], ["Plated Sliver", "Gray Ogre"],
        interactive={0} if interactive else (),
    )
    seats[0].hand.append(_w1g3_card(set_pool, "Ward Sliver"))
    result = game.queue_from_hand(0, "Ward Sliver")
    assert result.supported, result.details
    for _ in range(10):
        if game.pending_choices:
            choice = game.pending_choices[0]
            assert choice.kind == "enter_choice" and choice.data.get("needs_color")
            assert game.resolve_pending_choice(
                choice.kind, choice.player_index, mana_color=color,
            )
            continue
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game._recompute_continuous_effects()
    return game, seats


def test_w1g3_ward_sliver_grants_every_sliver_protection_from_the_chosen_color(set_pool):
    """CR 702.16 for every Sliver on the battlefield, either side, and for
    nothing else. Interactive: A chooses black, though B's board is red."""
    game, (a, b) = _w1g3_cast_ward_sliver(set_pool, interactive=True, color="B")
    ward = next(p for p in a.battlefield if p.card.name == "Ward Sliver")
    assert ward.metadata["chosen_color"] == "B"
    for permanent in game.all_permanents():
        expected = (
            {("color", "B")} if permanent.card.name.endswith("Sliver") else set()
        )
        assert game._protection_qualities(permanent) == expected, permanent.card.name
    # The lord leaving takes the grant with it (CR 611.3a, derived).
    game.remove_from_battlefield(ward)
    game._recompute_continuous_effects()
    assert all(game._protection_qualities(p) == set() for p in game.all_permanents())


def test_w1g3_ward_sliver_protection_stops_a_red_blocker_and_a_red_spell(set_pool):
    """A non-interactive controller takes the stated default, the colour its
    opponents hold most — red, B's Gray Ogre. Then the protection is the
    rules: Shock can't target a Sliver (CR 702.16b) and Gray Ogre can't block
    one (702.16e)."""
    game, (a, b) = _w1g3_cast_ward_sliver(set_pool, interactive=False)
    ward = next(p for p in a.battlefield if p.card.name == "Ward Sliver")
    assert ward.metadata["chosen_color"] == "R"
    blade = a.battlefield[0]
    assert blade.card.name == "Blade Sliver"
    assert game._protection_qualities(b.battlefield[0]) == {("color", "R")}

    b.hand.append(_w1g3_card(set_pool, "Shock"))
    refused = game.queue_from_hand(1, "Shock", target_permanent_ids=[blade.permanent_id])
    assert not refused.supported
    assert [card.name for card in b.hand] == ["Shock"] and blade.damage_marked == 0

    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ogre_slot = next(i for i, p in enumerate(b.battlefield) if p.card.name == "Gray Ogre")
    ok, _why = game.declare_blockers(1, {ogre_slot: 0})
    assert not ok
    plated_slot = next(i for i, p in enumerate(b.battlefield) if p.card.name == "Plated Sliver")
    ok, why = game.declare_blockers(1, {plated_slot: 0})
    assert ok, why


def test_w1g3_ward_sliver_prevents_the_chosen_colors_damage(set_pool):
    """CR 702.16d: B's red Gray Ogre attacks into A's Blade Sliver, which
    blocks and takes none of the Ogre's 2 — and deals its 3."""
    game, (a, b) = _w1g3_cast_ward_sliver(set_pool, interactive=False)
    blade = a.battlefield[0]
    ogre = next(p for p in b.battlefield if p.card.name == "Gray Ogre")
    plated = next(p for p in b.battlefield if p.card.name == "Plated Sliver")
    plated.tapped = True
    ogre_slot = next(i for i, p in enumerate(b.battlefield) if p is ogre)
    _w1g3_fight(game, 1, blocks={0: ogre_slot})
    assert blade in a.battlefield and blade.damage_marked == 0
    assert ogre not in b.battlefield


# --- Mistform Sliver: a granted type change that adds -------------------


def _w1g3_activate_granted(game, seat, name, *, answer_type=None):
    """Activate the first activated ability of *seat*'s *name* (the grant),
    answering the creature-type prompt with *answer_type* when the seat is
    interactive, defaulting it otherwise; drain the stack."""
    slot = next(
        i for i, p in enumerate(game.players[seat].battlefield) if p.card.name == name
    )
    result = game.activate_permanent_ability(
        seat, name, permanent_index=slot, ability_index=0,
    )
    assert result.supported, result.details
    for _ in range(10):
        if game.pending_choices:
            choice = game.pending_choices[0]
            assert choice.kind == "creature_type_choice", choice.kind
            if choice.player_index in game.interactive_seats:
                assert game.resolve_pending_choice(
                    choice.kind, choice.player_index, creature_type=answer_type,
                )
            else:
                game.auto_resolve_pending_choices()
            continue
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game._recompute_continuous_effects()
    return game.players[seat].battlefield[slot]


def test_w1g3_mistform_sliver_grant_adds_the_chosen_type_and_keeps_sliver(set_pool):
    """"{1}: This permanent becomes the creature type of your choice **in
    addition to its other types** until end of turn." The card's 2004-10-04
    ruling: "Unlike most type changing effects, this one adds a creature type
    instead of replacing existing creature types" — so the Blade Sliver that
    becomes a Goblin is still a Sliver, and still gets the Sliver lords'
    bonuses (its own +1/+0, B's Plated Sliver's +0/+1). The type ends at
    cleanup (CR 514.2)."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Mistform Sliver", "Blade Sliver"], ["Plated Sliver"],
        interactive={0},
    )
    blade = _w1g3_activate_granted(game, 0, "Blade Sliver", answer_type="goblin")
    assert blade.has_type("goblin") and blade.has_type("sliver")
    assert (blade.effective_power, blade.effective_toughness) == (3, 3)
    assert any(
        "Blade Sliver became a Goblin in addition to its other types" in line
        for line in game.log
    )
    mistform = a.battlefield[0]
    assert not mistform.has_type("goblin")
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not blade.has_type("goblin") and blade.has_type("sliver")


def test_w1g3_mistform_sliver_grant_reaches_every_sliver_and_no_other_creature(set_pool):
    """"All Slivers" is every Sliver on the battlefield: B's Plated Sliver has
    the ability and B activates it (a default seat, taking the stated default);
    B's Grizzly Bears has nothing."""
    from engine.oracle import compile_card_oracle

    game, (a, b) = _w1g3_board(
        set_pool, ["Mistform Sliver"], ["Plated Sliver", "Grizzly Bears"],
    )
    bears = b.battlefield[1]
    assert compile_card_oracle(bears.effective_card).activated_abilities == ()
    plated = _w1g3_activate_granted(game, 1, "Plated Sliver")
    gained = [t for t in ("illusion", "goblin", "bear") if plated.has_type(t)]
    assert plated.has_type("sliver") and len(gained) == 1, gained


# --- Shifting Sliver: a board-wide blocker whitelist -----------------------


def _w1g3_block(game, attacker_seat, blocks):
    """Declare every untapped creature of *attacker_seat* attacking and try
    *blocks*; return the defender's (ok, why)."""
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [
        slot for slot, permanent in enumerate(game.players[attacker_seat].battlefield)
        if permanent.is_creature and not permanent.tapped
    ]
    ok, why = game.declare_attackers(
        attacker_seat, attackers, defending_player_index=1 - attacker_seat,
    )
    assert ok, why
    game.advance_combat_phase()
    return game.declare_blockers(1 - attacker_seat, dict(blocks))


def test_w1g3_shifting_sliver_slivers_are_blockable_only_by_slivers(set_pool):
    """"Slivers can't be blocked except by Slivers." CR 509.1b over every
    Sliver on the battlefield: A's Blade Sliver (and Shifting Sliver itself)
    can't be blocked by B's Grizzly Bears, and can be by B's Plated Sliver."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Shifting Sliver", "Blade Sliver"], ["Grizzly Bears", "Plated Sliver"],
    )
    for attacker_slot in (0, 1):
        ok, _why = _w1g3_block(game, 0, {0: attacker_slot})
        assert not ok, attacker_slot
        game, (a, b) = _w1g3_board(
            set_pool, ["Shifting Sliver", "Blade Sliver"],
            ["Grizzly Bears", "Plated Sliver"],
        )
    ok, why = _w1g3_block(game, 0, {1: 1})
    assert ok, why


def test_w1g3_shifting_sliver_reaches_the_opponents_slivers_too(set_pool):
    """The static is about *Slivers*, not "Slivers you control": B's Plated
    Sliver attacking A can't be blocked by A's Grizzly Bears — the Shifting
    Sliver on A's own side makes the opponent's Sliver evasive. A non-Sliver
    attacker is untouched."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Shifting Sliver", "Grizzly Bears"], ["Plated Sliver"],
    )
    ok, _why = _w1g3_block(game, 1, {1: 0})
    assert not ok
    game, (a, b) = _w1g3_board(
        set_pool, ["Shifting Sliver", "Grizzly Bears"], ["Plated Sliver"],
    )
    ok, why = _w1g3_block(game, 1, {0: 0})
    assert ok, why
    game, (a, b) = _w1g3_board(
        set_pool, ["Shifting Sliver", "Grizzly Bears"], ["Hill Giant"],
    )
    ok, why = _w1g3_block(game, 1, {1: 0})
    assert ok, why


def test_w1g3_shifting_sliver_leaves_with_its_source(set_pool):
    """Read off the board on every declaration (CR 611.3a): with Shifting
    Sliver gone, Grizzly Bears blocks Blade Sliver."""
    game, (a, b) = _w1g3_board(
        set_pool, ["Shifting Sliver", "Blade Sliver"], ["Grizzly Bears"],
    )
    game.remove_from_battlefield(a.battlefield[0])
    game._recompute_continuous_effects()
    ok, why = _w1g3_block(game, 0, {0: 0})
    assert ok, why


# --- Quick Sliver: any player's Sliver spells at instant speed -------------


def test_w1g3_quick_sliver_lets_any_player_cast_sliver_spells_at_instant_speed(set_pool):
    """"Any player may cast Sliver spells as though they had flash." Asked of
    ``casts_at_instant_speed``, the one question the web's two timing gates
    and the AI's ask. On A's turn, with A's Quick Sliver out, B may cast a
    Sliver (and so may A, off its own main phase); a Grizzly Bears still waits
    for its owner's main phase; and the permission leaves with the Sliver."""
    from engine.cast_timing import casts_at_instant_speed

    game, (a, b) = _w1g3_board(set_pool, ["Quick Sliver"], ["Grizzly Bears"])
    plated = _w1g3_card(set_pool, "Plated Sliver")
    bears = _w1g3_card(set_pool, "Grizzly Bears")
    game._set_phase_and_step("combat", "declare_attackers")
    assert casts_at_instant_speed(plated, game, 1)
    assert casts_at_instant_speed(plated, game, 0)
    assert not casts_at_instant_speed(bears, game, 1)
    # Quick Sliver's own printed Flash, which needs nobody's permission.
    assert casts_at_instant_speed(_w1g3_card(set_pool, "Quick Sliver"))
    game.remove_from_battlefield(a.battlefield[0])
    assert not casts_at_instant_speed(plated, game, 1)


def test_w1g3_quick_sliver_reads_the_spells_creature_type(set_pool):
    """A Sliver spell is a spell with the Sliver creature type (CR 205.3m):
    Mistform Sliver (an Illusion Sliver) is one; Mistform Seaswift — an
    Illusion with no Sliver in its line — is not."""
    from engine.cast_timing import casts_at_instant_speed

    game, (a, b) = _w1g3_board(set_pool, ["Quick Sliver"])
    game.active_player_index = 1
    assert casts_at_instant_speed(_w1g3_card(set_pool, "Mistform Sliver"), game, 0)
    assert not casts_at_instant_speed(_w1g3_card(set_pool, "Mistform Seaswift"), game, 0)


# --- Root Sliver: Sliver spells can't be countered --------------------------


def _w1g3_counter(set_pool, victim, counter, *, root_on=1):
    """A casts *victim*; B answers with *counter* aimed at it; drain. Root
    Sliver sits on seat *root_on*'s battlefield (None: nowhere)."""
    mine = ["Root Sliver"] if root_on == 0 else []
    theirs = ["Root Sliver"] if root_on == 1 else []
    game, (a, b) = _w1g3_board(set_pool, mine, theirs)
    a.hand.append(_w1g3_card(set_pool, victim))
    b.hand.append(_w1g3_card(set_pool, counter))
    cast = game.queue_from_hand(0, victim)
    assert cast.supported, cast.details
    answer = game.queue_from_hand(1, counter, target_stack_index=0)
    assert answer.supported, answer.details
    _w1g3_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g3_resolve_stack(game)
    return game, a, b


@_w1g3_pytest.mark.parametrize("root_on", [0, 1])
def test_w1g3_root_sliver_makes_every_sliver_spell_uncounterable(set_pool, root_on):
    """CR 101.2: "can't" beats "can". Whoever controls Root Sliver, A's Plated
    Sliver resolves through B's Counterspell — the static names Sliver spells,
    not "Sliver spells you control"."""
    game, a, b = _w1g3_counter(set_pool, "Plated Sliver", "Counterspell", root_on=root_on)
    assert "Plated Sliver" in [p.card.name for p in a.battlefield]
    assert "Counterspell: Plated Sliver can't be countered (Root Sliver)" in game.log


def test_w1g3_root_sliver_leaves_a_non_sliver_counterable(set_pool):
    game, a, b = _w1g3_counter(set_pool, "Grizzly Bears", "Counterspell")
    assert [c.name for c in a.graveyard] == ["Grizzly Bears"]
    assert not a.battlefield


def test_w1g3_root_sliver_spell_itself_cant_be_countered(set_pool):
    """"This spell can't be countered." (CR 113.6g) — with no other Root
    Sliver out."""
    game, a, b = _w1g3_counter(set_pool, "Root Sliver", "Counterspell", root_on=None)
    assert [p.card.name for p in a.battlefield] == ["Root Sliver"]


def test_w1g3_root_sliver_asks_before_an_unless_payment(set_pool):
    """Power Sink's "unless its controller pays X" never asks A to pay for a
    Sliver nothing can counter — the immunity is asked before the toll."""
    game, a, b = _w1g3_counter(set_pool, "Plated Sliver", "Power Sink")
    assert "Plated Sliver" in [p.card.name for p in a.battlefield]
    assert not any("must pay" in line for line in game.log)


# ==== end W1G3 ======================================================
