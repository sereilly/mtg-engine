"""A turn-up from floating mana spends {W}{C}, not {W}{W}, whatever is held:
Legions' browser observation, reproduced and closed.

Legions' Phase 5 saw Liege of the Axe turned face up for {1}{W} from
{W:3, G:4, C:7} floating spend {W}{W} with seven colourless floating, on a
board with an untapped Savannah and other cards held; headless, without the
held cards, it spent {W}{C}. Round kg3 reproduced it with the cards held
(``scratch/kg3/payment/probe_ww.py``, the deck the browser agent played): 3
of 1,192 hands — each holding Akroma, Angel of Wrath ({5}{W}{W}{W}) beside
cheaper cards.

The mechanism was the sparing choice's score (``mana_payment._wants_left``):
the wants were packed **together** in the order listed, each kept if it still
fitted beside those before it. The {C} spend kept Akroma payable, and Akroma,
packed first, crowded out three cheaper cards; the {W} spend made Akroma
unpayable and fitted the three — so the {W}{W} spend scored higher, although
every cost it leaves payable the {W}{C} spend leaves payable too. Wrong: a
richer pool must never score lower. The wants are now packed smallest first.

The census: the board, and every hand of one to seven of the browser deck's
cards in a seeded sample, with and without the Savannah: the turn-up must
spend {W} and {C}, tap nothing, and be accepted. Run backwards (the wants
packed in the order listed) it finds the observation's hands.
"""
from __future__ import annotations

import random
from unittest import mock

from engine import Game, PlayerState, mana_payment
from engine.card_loader import load_catalog
from engine.face_down import face_down_card
from engine.models import Permanent
from engine.special_actions import take_permanent_special_action
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

#: The white, blue, black, red and green creatures the browser agent's decks
#: held (``scratch/lgn/p5/cards.txt``), less those not in the pool.
DECK = tuple(name for name in (
    "Akroma, Angel of Wrath", "Akroma's Devoted", "Aven Redeemer", "Aven Warhawk",
    "Beacon of Destiny", "Celestial Gatekeeper", "Cloudreach Cavalry", "Daru Mender",
    "Daru Sanctifier", "Daru Stinger", "Deftblade Elite", "Essence Sliver",
    "Gempalm Avenger", "Glowrider", "Lowland Tracker", "Planar Guide", "Plated Sliver",
    "Starlight Invoker", "Stoic Champion", "Swooping Talon", "Wall of Hope",
    "Whipgrass Entangler", "White Knight", "Windborn Muse", "Wingbeat Warrior",
    "Earthblighter", "Berserk Murlodont", "Hundroog", "Feral Throwback",
    "Warbreak Trumpeter", "Kilnmouth Dragon", "Phage the Untouchable", "Blade Sliver",
    "Krosan Vorine", "Dreamborn Muse", "Skirk Outrider", "Primal Whisperer",
    "Havoc Demon", "Covert Operative", "Goblin Grappler", "Enormous Baloth",
) if name in _CARDS)

#: The hands the reproduction found spending {W}{W} (with the Savannah).
OBSERVED = (
    ("Earthblighter", "Akroma, Angel of Wrath", "Berserk Murlodont", "Planar Guide", "Hundroog"),
    ("Akroma, Angel of Wrath", "Feral Throwback", "Warbreak Trumpeter", "Kilnmouth Dragon",
     "Phage the Untouchable"),
    ("Blade Sliver", "Krosan Vorine", "Dreamborn Muse", "Skirk Outrider",
     "Akroma, Angel of Wrath", "Primal Whisperer", "Havoc Demon"),
)


def _turn_up(hand, *, savannah: bool):
    me = PlayerState(name="A", library=[_CARDS["Plains"]] * 10)
    game = Game(players=[me, PlayerState(name="B", library=[_CARDS["Plains"]] * 10)])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    liege = _nosick(Permanent(card=face_down_card(_CARDS["Liege of the Axe"])))
    defender = _nosick(Permanent(card=face_down_card(_CARDS["Defender of the Order"])))
    me.battlefield.extend([liege, defender])
    if savannah:
        me.battlefield.append(_nosick(Permanent(card=_CARDS["Savannah"])))
    me.hand = [_CARDS[name] for name in hand]
    game._sync_control()
    me.mana_pool.update({"W": 3, "G": 4, "C": 7})
    game.priority_player_index = 0
    refused = take_permanent_special_action(game, 0, liege, "turn_face_up")
    resolve_stack(game)
    spent = {
        symbol: {"W": 3, "G": 4, "C": 7}.get(symbol, 0) - me.mana_pool.get(symbol, 0)
        for symbol in "WUBRGC"
    }
    tapped = [p.card.name for p in me.battlefield if p.tapped]
    return refused, {s: n for s, n in spent.items() if n}, tapped


def _hands():
    rng = random.Random(7)
    sample = [(name,) for name in DECK]
    sample += [tuple(rng.sample(DECK, size)) for size in (3, 5, 7) for _ in range(40)]
    return [*OBSERVED, *sample]


def _census() -> dict:
    found = {"examined": 0, "odd": []}
    for hand in _hands():
        for savannah in (True, False):
            refused, spent, tapped = _turn_up(hand, savannah=savannah)
            found["examined"] += 1
            if refused or spent != {"W": 1, "C": 1} or tapped:
                found["odd"].append((savannah, hand, refused, spent, tapped))
    return found


def _listed_order(rest, wants):
    """``_wants_left`` as it packed before: in the order listed."""
    together: dict = {}
    packed = cards = 0
    for want, times, tier in wants:
        for _ in range(times):
            trial = dict(together)
            for symbol, amount in want.items():
                trial[symbol] = trial.get(symbol, 0) + amount
            if mana_payment._units_pay(rest, trial):
                together = trial
                packed += 1
                cards += 1 if tier == 0 else 0
    alone = sum(t for w, t, _tier in wants if mana_payment._units_pay(rest, w))
    return (packed, cards, alone)


def test_a_turn_up_from_the_pool_spends_its_colourless_whatever_is_held():
    found = _census()
    assert found["odd"] == [], found["odd"][:5]
    assert found["examined"] >= 300, found["examined"]


def test_the_census_names_the_wants_packed_in_the_order_listed():
    """Backwards: packed in the order listed, the observation's hands spend
    {W}{W} beside the Savannah."""
    mana_payment._choice_scores.cache_clear()
    try:
        with mock.patch.object(mana_payment, "_wants_left", _listed_order):
            odd = [
                hand for hand in OBSERVED
                if _turn_up(hand, savannah=True)[1] == {"W": 2}
            ]
    finally:
        mana_payment._choice_scores.cache_clear()
    assert len(odd) == len(OBSERVED), odd
