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
    (permanent,) = p1.battlefield
    (choice,) = game.pending_choices_of("entry_reveal", 0)
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
    assert any(p is permanent for p in game.controlled_by(0))

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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================
