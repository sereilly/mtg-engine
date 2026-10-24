"""What the AI does with three Judgment cards whose value no standing reads.

``ai_rehearsal.seat_standing`` counts life, a hand and a board. Three of
Judgment's odd ones trade in what it does not count, and each was played
against its own seat in seeded games until the policy was told:

* **Quiet Speculation** puts cards *with flashback* into the named player's
  graveyard — spells its owner may then cast from there (CR 702.34a). The
  seat tie-break aimed it at the opponent, handing them three spells.
* **Balthor the Defiled** exiles itself to return every black and red
  creature card from **each** graveyard: activated with nothing in its
  controller's pile, it is a creature thrown away, and with more in an
  opponent's it is their reanimation.
* **Morality Shift** exchanges graveyard and library: cast with the smaller
  pile in the graveyard it leaves the caster fewer cards to draw (CR 704.5b).

Each answer is read off the compiled program, never off a name; these tests
drive the policy's own choosers.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_policy import choose_cast_action
from engine.ai_target_sides import cast_helps_the_player_it_names, spell_seat_side
from engine.models import Permanent


def _table(set_pool, *, hand=(), graveyards=((), ()), libraries=None):
    pool = {**set_pool("LEA"), **set_pool("ODY"), **set_pool("JUD")}
    island = pool["Island"]
    libraries = libraries or ([island] * 10, [island] * 10)
    game = Game(players=[
        PlayerState(
            name=f"P{seat}", life=20,
            library=[pool[name] if isinstance(name, str) else name for name in libraries[seat]],
            graveyard=[pool[name] for name in graveyards[seat]],
            hand=[pool[name] for name in (hand if seat == 0 else ())],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game, pool


def _put(game, card, seat):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_quiet_speculation_is_aimed_at_its_own_caster(set_pool):
    """Binning cards with flashback is a gift to the player named, so the seat
    side is the caster's own — and a seat holding it, with flashback cards in
    its library, names itself."""
    card = set_pool("JUD")["Quiet Speculation"]
    assert cast_helps_the_player_it_names(card)
    assert spell_seat_side(card) == "you"

    game, pool = _table(
        set_pool, hand=("Quiet Speculation",),
        libraries=(
            ["Firebolt", "Island", "Moment's Peace", "Island"],
            ["Firebolt", "Island", "Moment's Peace", "Island"],
        ),
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Quiet Speculation"
    assert action.target_player_index == 0


def test_balthor_is_not_activated_for_nothing_or_for_the_opponent(set_pool):
    """With nothing black or red in either graveyard, and with more of them in
    the opponent's than in its own, the seat keeps Balthor; with the larger
    share its own, it activates him."""
    empty, pool = _table(set_pool)
    _put(empty, pool["Balthor the Defiled"], 0)
    assert choose_activation_action(empty, 0) is None

    theirs, pool = _table(
        set_pool, graveyards=(("Black Knight",), ("Hill Giant", "Scathe Zombies")),
    )
    _put(theirs, pool["Balthor the Defiled"], 0)
    assert choose_activation_action(theirs, 0) is None

    mine, pool = _table(
        set_pool, graveyards=(("Black Knight", "Hill Giant"), ("Scathe Zombies",)),
    )
    _put(mine, pool["Balthor the Defiled"], 0)
    action = choose_activation_action(mine, 0)
    assert action is not None and action.permanent_name == "Balthor the Defiled"


def test_morality_shift_waits_for_the_larger_graveyard(set_pool):
    """Two cards in the graveyard and ten in the library: not cast. Twelve in
    the graveyard and three in the library: cast."""
    small, _ = _table(
        set_pool, hand=("Morality Shift",),
        graveyards=(("Hill Giant", "Black Knight"), ()),
    )
    assert choose_cast_action(small, 0) is None

    large, pool = _table(
        set_pool, hand=("Morality Shift",),
        graveyards=((("Hill Giant",) * 6 + ("Black Knight",) * 6), ()),
        libraries=(["Island"] * 3, ["Island"] * 10),
    )
    action = choose_cast_action(large, 0)
    assert action is not None and action.card_name == "Morality Shift"
