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
                              turn_face_up as _w1g1_turn_face_up)
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


# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================
