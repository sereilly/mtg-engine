"""Mercadian Masques sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: alternative and additional casting costs ---
# Land Grant, the one card in this pool whose CR 118.9 alternative cost is
# paid by **information**: "If you have no land cards in hand, you may reveal
# your hand rather than pay this spell's mana cost." Both halves are unusual --
# the condition reads a hand rather than a board, and the payment moves nothing
# -- so the two are asserted apart: an offer that appeared on a hand holding a
# land would be a free Rampant Growth, and a payment nobody could see would be
# a free spell with a log line.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_grant_table(set_pool, hand, mine=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: this card is about not paying a
    mana cost, and a game that charges none cannot tell a free cast from an
    ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    caster.library = [pool["Forest"], pool["Plains"], pool["Wild Jhovall"]]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_grant_offers(game, card):
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(0, card, spell_hand_index=0)
        if offer["kind"] == "alternative"
    ]


def test_g1_land_grant_is_free_only_with_no_land_in_hand(set_pool):
    """CR 601.2b: the condition is a **hand**, and it is checked at the cast.

    A card in a hand has no computed characteristics (CR 613.1), so the phrase
    is put to the card matcher rather than to ``subject_matches`` -- a narrowing
    only the permanent matcher could answer would be silently dropped by the
    hand scan, and the offer would stand on a hand the card does not name.
    """
    card = set_pool("MMQ")["Land Grant"]

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Forest"])
    assert _g1_grant_offers(game, card) == []

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Brainstorm"])
    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_offer_survives_an_empty_hand(set_pool):
    """An empty hand holds no land card, so the offer stands and is payable.

    CR 601.2h has no shortfall to find in a reveal: showing nothing is still
    showing what you have. A gate that treated "nothing to reveal" as unpayable
    would refuse the card on exactly the board it is designed for.
    """
    card = set_pool("MMQ")["Land Grant"]
    game, _, _ = _g1_grant_table(set_pool, ["Land Grant"])

    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_reveals_the_hand_and_fetches_for_nothing(set_pool):
    """The whole card: the hand is shown, the Forest arrives, no mana is spent.

    The reveal goes through ``record_reveal`` -- the feed the web layer reads,
    the same seam the ``reveal_hand`` *effect* uses -- rather than a log line
    alone: a reveal the client cannot show is a reveal the opponent has to take
    on trust, and here it is the entire price of the spell.

    The spell is already off the hand when the price is paid (CR 601.2a), so
    what is shown is the hand Land Grant's own condition is about.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Brainstorm", "Wild Jhovall"],
    )

    result = game.cast_from_hand(0, "Land Grant", alternative_cost=True)
    resolve_stack(game)
    # The library search is a queued decision the spell does not wait on, so it
    # is drained the way an AI or headless seat drains one.
    game.auto_resolve_pending_choices(0)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert caster.battlefield == []
    assert "Forest" in [held.name for held in caster.hand]
    revealed = [line for line in game.log if "revealed their hand" in line]
    assert len(revealed) == 1
    assert "Brainstorm" in revealed[0] and "Wild Jhovall" in revealed[0]
    # CR 601.2a: the spell is on the stack and cannot be among what it reveals.
    assert "Land Grant" not in revealed[0].split(": ", 1)[1]


def test_g1_land_grant_still_costs_its_mana_when_a_land_is_held(set_pool):
    """CR 118.9b: the alternative is optional and the printed cost stands.

    Which is exactly what Land Grant did on every board before this round -- the
    line was claimed by nothing, so it was always cast at ``{1}{G}``. The
    regression to watch for is the other direction, and it is the one this
    asserts: with a land in hand the offer is gone and the mana is still spent.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Forest"], mine=("Forest", "Forest"),
    )
    caster.mana_pool["G"] = 1
    caster.mana_pool["C"] = 1

    result = game.cast_from_hand(0, "Land Grant")
    resolve_stack(game)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert not any("revealed their hand" in line for line in game.log)


# --- W2G4: mass effects that count something ---
from engine import Game as _S4Game
from engine import PlayerState as _S4PlayerState
from engine.models import Permanent as _S4Permanent
from tests.helpers import _mk_creature_card as _s4_creature_card
from tests.helpers import resolve_stack as _s4_resolve


def _w2g4_table(set_pool, hand, mine=(), theirs=()):
    """A duel with *hand* on seat 0 and named permanents on both battlefields.

    Mana enforcement off, the house rig: nothing in this block is about paying
    for anything, so a charged cast would only add a way for a test to fail for
    a reason it is not about. A card given as a string comes from the set; one
    given as a `CardDefinition` is a fixture, so a sweep can be aimed at printed
    numbers the set does not happen to contain.
    """
    pool = set_pool("MMQ")
    caster, other = _S4PlayerState("Caster"), _S4PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = _S4Game(players=[caster, other])
    game.enforce_mana_costs = False
    for perm in mine:
        caster.battlefield.append(
            _S4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    for perm in theirs:
        other.battlefield.append(
            _S4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    game._settle()
    return game, caster, other


def test_w2g4_wave_of_reckoning_makes_every_creature_bite_itself(set_pool):
    """"Each creature deals damage to itself equal to its power."
    (Wave of Reckoning.)

    Every creature on the table, not one seat's — and the number is each
    creature's *own* power, so a 4/4 dies and a 1/5 does not. Both boards are
    populated, because a sweep that read one battlefield would pass this test
    with half the board untouched.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Wave of Reckoning"],
        mine=[_s4_creature_card("Bear", 2, 2), _s4_creature_card("Wall", 1, 5)],
        theirs=[_s4_creature_card("Giant", 4, 4)],
    )

    result = game.cast_from_hand(0, "Wave of Reckoning")
    _s4_resolve(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert sorted(p.card.name for p in game.all_permanents()) == ["Wall"]


def test_w2g4_wave_of_reckoning_deals_the_damage_as_the_permanent(set_pool):
    """CR 120.7: each creature is the *source* of the damage it takes.

    Routed through the sorcery instead, a creature with protection from white
    would shrug the whole card off and a lifelinker would gain nothing — so the
    log naming the creature is the observable half of the rule. A zero-power
    creature is not dealt to at all (CR 120.8), which is the other half.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Wave of Reckoning"],
        mine=[_s4_creature_card("Ox", 3, 9), _s4_creature_card("Nought", 0, 4)],
    )

    game.cast_from_hand(0, "Wave of Reckoning")
    _s4_resolve(game)

    board = {p.card.name: p for p in game.all_permanents()}
    assert board["Ox"].damage_marked == 3
    assert board["Nought"].damage_marked == 0
    assert any("Ox (3)" in line for line in game.log)


def test_w2g4_tectonic_break_sacrifices_x_lands_from_each_player(set_pool):
    """"Each player sacrifices X lands of their choice." (Tectonic Break.)

    CR 107.3: X is the announced number, carried as ``"x"`` and resolved at
    resolution. The count is a *flag* rather than a printed 0 or 1 precisely so
    this cannot pass by accident — read as the zero the noun phrase carries,
    each player would sacrifice nothing however large X was.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Tectonic Break"],
        mine=["Mountain", "Mountain", "Mountain"],
        theirs=["Plains", "Plains"],
    )

    result = game.cast_from_hand(0, "Tectonic Break", x_value=2)
    _s4_resolve(game)

    assert result.supported, result.details
    assert len(list(game.controlled_by(0))) == 1
    assert len(list(game.controlled_by(1))) == 0


def test_w2g4_tectonic_break_at_x_zero_takes_nothing(set_pool):
    """An announced X of 0 is a real answer (CR 107.3b) and costs both seats
    nothing — the assertion that the count is resolved rather than defaulted to
    the one every other printed sacrifice carries."""
    game, _caster, _other = _w2g4_table(
        set_pool, ["Tectonic Break"], mine=["Mountain"], theirs=["Plains"],
    )

    game.cast_from_hand(0, "Tectonic Break", x_value=0)
    _s4_resolve(game)

    assert len(list(game.controlled_by(0))) == 1
    assert len(list(game.controlled_by(1))) == 1


def test_w2g4_misstep_holds_down_the_named_players_creatures_only(set_pool):
    """"Creatures target player controls don't untap during that player's next
    untap step." (Misstep.)

    Two narrowings, each asserted against what it excludes: only *creatures*
    (the target's land is untouched) and only the *target's* (the caster's own
    creature unmarked). A sweep handed no seat matches nothing, and one handed
    the wrong seat holds down the caster's own board — so both directions have
    a permanent in this board to catch them.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Misstep"],
        mine=[_s4_creature_card("Mine", 2, 2)],
        theirs=[_s4_creature_card("Theirs", 2, 2), "Plains"],
    )

    result = game.cast_from_hand(0, "Misstep", target_player_index=1)
    _s4_resolve(game)

    assert result.supported, result.details
    assert {
        p.card.name: int(p.metadata.get("skip_next_untap") or 0)
        for p in game.all_permanents()
    } == {"Mine": 0, "Theirs": 1, "Plains": 0}


def test_w2g4_misstep_waits_for_the_named_players_untap_step(set_pool):
    """"…during **that player's** next untap step" — the seat the spell chose,
    frozen as the marker is made (CR 115.4).

    Not "their controller's", which is the elision one word away and the same
    answer until the creature changes hands. The seat is the whole of what this
    asserts, because the marker itself is identical either way — and an unseated
    marker is spent by whichever untap step reaches the permanent first.
    """
    from engine.handlers.tapping import SKIP_NEXT_UNTAP_SEAT

    game, _caster, _other = _w2g4_table(
        set_pool, ["Misstep"], theirs=[_s4_creature_card("Theirs", 2, 2)],
    )
    game.cast_from_hand(0, "Misstep", target_player_index=1)
    _s4_resolve(game)

    marked = next(p for p in game.all_permanents() if p.card.name == "Theirs")
    assert marked.metadata[SKIP_NEXT_UNTAP_SEAT] == 1
