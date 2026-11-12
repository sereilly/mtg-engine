"""Fifth Dawn artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.linked_exile import face_down_exiled_cards as _w1g5_face_down
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_card(set_pool, name):
    for code in ("5DN", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), opponent_hand=(),
                interactive=()):
    """Costs not enforced, every permanent past summoning sickness, seat 0
    active in its first main phase. Cards from Fifth Dawn, else Alpha."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A",
                         hand=[_w1g5_card(set_pool, n) for n in hand],
                         library=[_w1g5_card(set_pool, "Island")] * 10),
        _W1G5PlayerState(name="W1G5-B",
                         hand=[_w1g5_card(set_pool, n) for n in opponent_hand],
                         library=[_w1g5_card(set_pool, "Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G5Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g5_settle(game)
    return game, rows[0], rows[1]  # _w1g5_table


def _w1g5_shackle(set_pool, *, islands=2, theirs=("Grizzly Bears", "Craw Wurm"), **kwargs):
    game, mine, theirs = _w1g5_table(
        set_pool, mine=["Vedalken Shackles"] + ["Island"] * islands,
        theirs=list(theirs), **kwargs,
    )
    return game, mine[0], mine[1:], theirs


def test_w1g5_vedalken_shackles_steals_only_a_creature_within_your_island_count(set_pool):
    """"{2}, {T}: Gain control of target creature with power less than or
    equal to the number of Islands you control for as long as this artifact
    remains tapped." With two Islands the Craw Wurm (6) cannot be named and
    nothing is paid finding out; the Grizzly Bears (2) are taken."""
    game, shackles, _islands, (bears, wurm) = _w1g5_shackle(set_pool)
    refused = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[wurm.permanent_id]
    )
    assert not refused.supported
    assert not shackles.tapped, "a refused activation pays nothing"
    taken = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    )
    assert taken.supported, taken.details
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    assert game.controller_index_of(wurm) == 1
    assert shackles.tapped


def test_w1g5_vedalken_shackles_keeps_a_creature_that_grows_past_the_count(set_pool):
    """The ruling (2004-12-01): "The creature's power and the number of
    Islands you control matter only when the ability is activated and when it
    resolves. After that, only the fact that Vedalken Shackles remains tapped
    matters." Giant Growth on the stolen Bears changes nothing."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(
        set_pool, opponent_hand=["Giant Growth"],
    )
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    grown = game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert grown.supported, grown.details
    _w1g5_settle(game)
    assert bears.effective_power == 5
    assert game.controller_index_of(bears) == 0


def test_w1g5_vedalken_shackles_counts_your_islands_as_it_resolves(set_pool):
    """CR 608.2b: the bound is asked again on resolution. An Island leaving
    in response leaves one, the Bears' 2 power is past it, and the ability does
    nothing."""
    game, _shackles, islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    assert game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.remove_from_battlefield(islands[0])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untapped_in_response_steals_nothing(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles becomes untapped before
    its ability resolves, you won't gain control of the creature." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    assert game.become_untapped(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untap_choice_is_the_whole_card(set_pool):
    """"You may choose not to untap this artifact during your untap step."
    The choice is offered at seat 0's untap step; a seat nobody sits in keeps
    the Shackles tapped while the steal is live, and choosing to untap it
    (the person's answer, ``keep_tapped_ids=[]``) gives the Bears back —
    as does the Shackles leaving the battlefield (the ruling: "it's no longer
    tapped, so the control-changing effect ends")."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0

    assert [entry["id"] for entry in game.get_optional_untap_permanents(0)] == [
        shackles.permanent_id
    ]
    game.start_turn(1)
    _w1g5_settle(game)
    game.start_turn(0)
    _w1g5_settle(game)
    assert shackles.tapped, "headless play keeps a live steal"
    assert game.controller_index_of(bears) == 0

    game.start_turn(1)
    _w1g5_settle(game)
    game.resolve_untap_step(0, keep_tapped_ids=[])
    _w1g5_settle(game)
    assert not shackles.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_leaving_ends_the_steal(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles leaves the battlefield,
    it's no longer tapped, so the control-changing effect ends." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    game.remove_from_battlefield(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def _w1g5_egg(set_pool, hand, *, pick=None, interactive=()):
    """Seat 0 casts Summoner's Egg holding *hand*; with *pick* (seat 0
    interactive) it takes the imprint offer and exiles that card by name.
    Returns ``(game, egg)`` with the Egg on the battlefield."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, hand=["Summoner's Egg", *hand], opponent_hand=["Disenchant"],
        interactive=interactive,
    )
    assert game.queue_from_hand(0, "Summoner's Egg").supported
    answers = {}
    if pick is not None:
        hand_of = game.players[0].hand
        answers = {
            "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
            "exile_from_hand_choice": lambda g, c: g.confirm_exile_from_hand_choice(
                c.player_index,
                next(i for i, card in enumerate(hand_of) if card.name == pick),
            ),
        }
    _w1g5_settle(game, answers=answers)
    egg = next(
        p for p in game.controlled_by(game.players[0]) if p.card.name == "Summoner's Egg"
    )
    return game, egg


def _w1g5_disenchant(game, permanent):
    game.active_player_index = 1
    cast = game.queue_from_hand(1, "Disenchant", target_permanent_ids=[permanent.permanent_id])
    assert cast.supported, cast.details
    _w1g5_settle(game)


def test_w1g5_summoners_egg_hatches_the_imprinted_creature_when_it_dies(set_pool):
    """"Imprint — When this creature enters, you may exile a card from your
    hand face down. When this creature dies, turn the exiled card face up. If
    it's a creature card, put it onto the battlefield under your control."
    The Craw Wurm is exiled face down — hidden from every seat, its owner
    included (CR 406.3; the ruling: "you can't look at the card once it's
    imprinted"), and unnamed in the log — and enters when the Egg dies."""
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm", "Lightning Bolt"], pick="Craw Wurm", interactive=(0,),
    )
    wurm = _w1g5_card(set_pool, "Craw Wurm")
    assert [c.name for c in _w1g5_face_down(game, 0, 0)] == ["Craw Wurm"]
    assert [c.name for c in _w1g5_face_down(game, 0, 1)] == ["Craw Wurm"]
    assert not any("Craw Wurm" in line for line in game.log)
    _w1g5_disenchant(game, egg)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Craw Wurm"]
    assert all(card is not wurm for card in game.players[0].exile)
    assert "Summoner's Egg turns Craw Wurm face up in exile" in game.log


def test_w1g5_summoners_egg_leaves_a_noncreature_card_exiled_face_up(set_pool):
    """The ruling (2004-12-01): "If the card is not a creature card when it's
    turned face up, it remains exiled face up." """
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm", "Lightning Bolt"], pick="Lightning Bolt", interactive=(0,),
    )
    _w1g5_disenchant(game, egg)
    assert list(game.controlled_by(game.players[0])) == []
    assert [c.name for c in game.players[0].exile] == ["Lightning Bolt"]
    assert _w1g5_face_down(game, 0) == []
    assert "no creature card is exiled with Summoner's Egg" in game.log


def test_w1g5_summoners_egg_leaving_without_dying_keeps_the_card_face_down(set_pool):
    """Only "dies" turns the card up: an Egg returned to its owner's hand
    leaves its imprint exiled face down for good (CR 406.3 has no ending)."""
    game, egg = _w1g5_egg(
        set_pool, ["Craw Wurm"], pick="Craw Wurm", interactive=(0,),
    )
    game.remove_from_battlefield(egg)
    game.players[0].hand.append(egg.card)
    _w1g5_settle(game)
    assert [c.name for c in _w1g5_face_down(game, 0)] == ["Craw Wurm"]
    assert list(game.controlled_by(game.players[0])) == []


def test_w1g5_summoners_egg_seat_nobody_asks_imprints_its_best_creature(set_pool):
    """A seat nobody asks takes the offer and imprints the most expensive
    creature card — the one the dies trigger would hatch — not the cheapest
    card in hand (``ai_prompt_readers.linked_exile_returns_to_battlefield``)."""
    game, egg = _w1g5_egg(set_pool, ["Lightning Bolt", "Grizzly Bears", "Craw Wurm"])
    assert [c.name for c in _w1g5_face_down(game, 0)] == ["Craw Wurm"]
    _w1g5_disenchant(game, egg)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Craw Wurm"]

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
