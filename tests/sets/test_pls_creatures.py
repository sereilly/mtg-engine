"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: two kickers ---
# The five Battlemages ("Kicker {1}{G} and/or {2}{U}", one entry trigger per
# cost — CR 702.33b, CR 702.33f), and the twelve supported-on-arrival cards
# this group drove: Waterspout Elemental, and the ten gating creatures ("When
# this creature enters, return a <colour> or <colour> creature you control to
# its owner's hand."). Ertai's Trickery, the twelfth, is an instant.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.ai_policy import choose_cast_action as _w1g2_choose_cast_action
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.cast_costs import KICKED as _W1G2_KICKED
from engine.cast_costs import KICKED_WITH as _W1G2_KICKED_WITH
from engine.cast_costs import kicked as _w1g2_kicked
from engine.cast_costs import kicker_costs as _w1g2_kicker_costs
from engine.cast_timing import casts_at_instant_speed as _w1g2_instant_speed
from engine.control import change_control as _w1g2_change_control
from engine.mana_payment import mana_cost_from_symbols as _w1g2_symbols
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}

#: The sets a bystander is looked for in, Planeshift first.
_W1G2_SETS = ("PLS", "LEA", "INV", "VIS", "USG", "UDS", "TMP", "PCY")


def _w1g2_named(set_pool, name):
    """*name* out of whichever set prints it — a Battlemage's victims are
    Alpha's, a kicked spell is Invasion's."""
    for code in _W1G2_SETS:
        card = set_pool(code).get(name)
        if card is not None:
            return card
    raise KeyError(name)  # _w1g2_named


def _w1g2_duel(set_pool, hand, *, pool=None, humans=(), their_hand=()):
    """Two seats in a game that **charges mana** — a kicker is a price, and a
    rig that waives mana cannot tell a kicked cast from a free one. Seat 0
    holds *hand*; *humans* are the seats that are asked rather than defaulted."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Mage", library=[forest] * 12,
            hand=[_w1g2_named(set_pool, name) for name in hand],
        ),
        _W1G2PlayerState(
            "Rival", library=[forest] * 12,
            hand=[_w1g2_named(set_pool, name) for name in their_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(humans)
    game.players[0].mana_pool.update(_W1G2_RICH if pool is None else pool)
    return game  # _w1g2_duel


def _w1g2_put(game, set_pool, seat, name):
    permanent = _W1G2Permanent(card=_w1g2_named(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g2_put


def _w1g2_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g2_floating


def _w1g2_price(printed: str) -> int:
    return sum((_w1g2_symbols(printed) or {}).values())  # _w1g2_price


def _w1g2_cast(game, name, kick=(), **announced):
    """Cast *name* from seat 0 paying the kicker costs in *kick*, resolve it,
    answer what a headless seat is left owing, and return the permanent."""
    result = game.queue_from_hand(
        0, name,
        optional_cost_payments={key: 1 for key in kick} or None, **announced,
    )
    assert result.supported, result
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return next(
        (p for p in game.controlled_by(0) if p.card.name == name), None
    )  # _w1g2_cast


def _w1g2_names(game, seat):
    return [p.card.name for p in game.controlled_by(seat)]  # _w1g2_names


def _w1g2_until_asked(game, limit=8):
    """Resolve stack objects until somebody is owed a prompt (or the stack is
    empty): a human seat's view of a resolution."""
    for _ in range(limit):
        if game.pending_choices or not game.stack:
            return
        game.resolve_top_of_stack()  # _w1g2_until_asked


#: The five Battlemages: name, first kicker cost, second kicker cost.
_W1G2_BATTLEMAGES = [
    ("Sunscape Battlemage", "{1}{G}", "{2}{U}"),
    ("Stormscape Battlemage", "{W}", "{2}{B}"),
    ("Nightscape Battlemage", "{2}{U}", "{2}{R}"),
    ("Thunderscape Battlemage", "{1}{B}", "{G}"),
    ("Thornscape Battlemage", "{R}", "{W}"),
]


@_w1g2_pytest.mark.parametrize("name,first,second", _W1G2_BATTLEMAGES)
def test_w1g2_a_battlemage_offers_two_kickers_and_pays_for_the_ones_it_takes(
    set_pool, name, first, second
):
    """CR 702.33b: "Kicker [cost 1] and/or [cost 2]" is two kicker abilities.
    Each is its own offer, each is charged only when taken, and the cast
    remembers *which* — on the stack item, then on the permanent."""
    card = set_pool("PLS")[name]
    assert _w1g2_kicker_costs(card.oracle_text) == (first, second)

    offers = _w1g2_duel(set_pool, [name]).cast_cost_offers(0, card)
    assert [(o["symbols"], o["label"], o["max_times"]) for o in offers] == [
        (first, "kicker", 1), (second, "kicker", 1),
    ]

    for taken in ((), (first,), (second,), (first, second)):
        game = _w1g2_duel(set_pool, [name])
        # Something for a kicked trigger to hit that is not the Battlemage: a
        # mandatory "destroy target nonblack creature" with no other creature
        # in play has to take its own source (the test after next).
        _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        before = _w1g2_floating(game)
        result = game.queue_from_hand(
            0, name, optional_cost_payments={key: 1 for key in taken} or None
        )
        assert result.supported, (taken, result)
        item = next(i for i in game.stack if i.card is card)
        assert _w1g2_kicked(card, item.choices) is bool(taken)
        assert before - _w1g2_floating(game) == _w1g2_price(card.mana_cost) + sum(
            _w1g2_price(key) for key in taken
        ), taken
        _w1g2_resolve_stack(game)
        game.auto_resolve_pending_choices()
        mage = next(p for p in game.controlled_by(0) if p.card is card)
        assert bool(mage.metadata.get(_W1G2_KICKED)) is bool(taken)
        assert tuple(mage.metadata.get(_W1G2_KICKED_WITH) or ()) == taken
        assert (f"Mage kicked {name}" in game.log) is bool(taken)


def test_w1g2_two_kickers_are_priced_as_a_sum_not_one_at_a_time(set_pool):
    """Sunscape Battlemage is {2}{W} with kickers {1}{G} and {2}{U}: eight mana
    for everything. Seven pays for either kicker and not for both, the offer
    prompt says so once one is taken, and a cast that announces both anyway is
    refused with nothing spent (CR 601.2h)."""
    card = set_pool("PLS")["Sunscape Battlemage"]
    seven = {"W": 1, "G": 1, "U": 1, "R": 4}
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"], pool=seven)

    assert [o["max_times"] for o in game.cast_cost_offers(0, card)] == [1, 1]
    after_green = game.cast_cost_offers(0, card, taken={"{1}{G}": 1})
    assert [(o["symbols"], o["max_times"]) for o in after_green] == [
        ("{1}{G}", 1), ("{2}{U}", 0),
    ]

    refused = game.queue_from_hand(
        0, "Sunscape Battlemage",
        optional_cost_payments={"{1}{G}": 1, "{2}{U}": 1},
    )
    assert not refused.supported
    assert _w1g2_floating(game) == 7
    assert [c.name for c in game.players[0].hand] == ["Sunscape Battlemage"]

    eight = _w1g2_duel(
        set_pool, ["Sunscape Battlemage"], pool={**seven, "R": 5}
    )
    mage = _w1g2_cast(eight, "Sunscape Battlemage", kick=("{1}{G}", "{2}{U}"))
    assert mage is not None and _w1g2_floating(eight) == 0


@_w1g2_pytest.mark.parametrize("name,first,second", _W1G2_BATTLEMAGES)
def test_w1g2_a_battlemage_nothing_cast_was_kicked_with_nothing(
    set_pool, name, first, second
):
    """CR 400.7 / CR 702.33d: put onto the battlefield without being cast — a
    reanimation, a blink — there was no CR 601.2b, so neither "if" holds.
    Nothing triggers, nothing is asked, and the board is untouched."""
    game = _w1g2_duel(set_pool, [], humans=(0,))
    board = [
        _w1g2_put(game, set_pool, 1, victim) for victim in
        ("Serra Angel", "Grizzly Bears", "Forest", "Sol Ring", "Castle")
    ]
    mage = _w1g2_put(game, set_pool, 0, name)

    assert not mage.metadata.get(_W1G2_KICKED)
    assert not mage.metadata.get(_W1G2_KICKED_WITH)
    assert game.stack == [] and game.pending_choices == []
    assert all(game.is_on_battlefield(permanent) for permanent in board)
    assert (game.players[0].life, len(game.players[0].hand)) == (20, 0)


def test_w1g2_sunscape_battlemage_each_kicker_buys_its_own_trigger(set_pool):
    """"…if it was kicked with its {1}{G} kicker, destroy target creature with
    flying." / "…with its {2}{U} kicker, draw two cards." CR 702.33f: each
    ability is linked to one cost, so each combination does exactly its own."""
    outcomes = {}
    for taken in ((), ("{1}{G}",), ("{2}{U}",), ("{1}{G}", "{2}{U}")):
        game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
        angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
        bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        named = {"target_permanent_ids": [angel.permanent_id]} if "{1}{G}" in taken else {}
        _w1g2_cast(game, "Sunscape Battlemage", kick=taken, **named)
        assert game.is_on_battlefield(bears)
        outcomes[taken] = (game.is_on_battlefield(angel), len(game.players[0].hand))

    assert outcomes == {
        (): (True, 0),
        ("{1}{G}",): (False, 0),
        ("{2}{U}",): (True, 2),
        ("{1}{G}", "{2}{U}"): (False, 2),
    }


def test_w1g2_sunscape_battlemage_the_wrong_kicker_does_not_destroy(set_pool):
    """The question is *which* kicker. A cast that paid {2}{U} and named a
    flier anyway draws its two cards and destroys nothing: the destroy is the
    {1}{G} trigger's, and that trigger did not trigger (CR 603.4)."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    _w1g2_cast(
        game, "Sunscape Battlemage", kick=("{2}{U}",),
        target_permanent_ids=[angel.permanent_id],
    )
    assert game.is_on_battlefield(angel)
    assert len(game.players[0].hand) == 2
    assert game.players[1].graveyard == []


def test_w1g2_sunscape_battlemage_destroys_only_a_flier(set_pool):
    """"Destroy target creature **with flying**": the picker offers the fliers
    on either side and nothing else."""
    card = set_pool("PLS")["Sunscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
    for seat, name in ((1, "Serra Angel"), (1, "Grizzly Bears"), (0, "Air Elemental")):
        _w1g2_put(game, set_pool, seat, name)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{1}{G}": 1})
    assert sorted(entry["name"] for entry in spec["valid_targets"]) == [
        "Air Elemental", "Serra Angel",
    ]


def test_w1g2_stormscape_battlemage_gains_life_and_buries_a_nonblack_creature(set_pool):
    """{W}: "you gain 3 life" — *you*, whoever the other trigger is aimed at.
    {2}{B}: "destroy target nonblack creature. That creature can't be
    regenerated." — a regeneration shield does not save it."""
    outcomes = {}
    for taken in (("{W}",), ("{2}{B}",), ("{W}", "{2}{B}")):
        game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
        bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        bears.regeneration_shield = 1
        named = {"target_permanent_ids": [bears.permanent_id]} if "{2}{B}" in taken else {}
        _w1g2_cast(game, "Stormscape Battlemage", kick=taken, **named)
        outcomes[taken] = (
            game.players[0].life, game.players[1].life,
            [card.name for card in game.players[1].graveyard],
        )

    assert outcomes == {
        ("{W}",): (23, 20, []),
        ("{2}{B}",): (20, 20, ["Grizzly Bears"]),
        ("{W}", "{2}{B}"): (23, 20, ["Grizzly Bears"]),
    }


def test_w1g2_a_mandatory_target_can_be_the_battlemage_itself(set_pool):
    """A trigger's target is not optional (CR 603.3d): Stormscape Battlemage is
    blue, so with no other nonblack creature anywhere its own {2}{B} trigger
    has exactly one legal target, and takes it. Legal, and a reason the AI
    does not pay {2}{B} onto that board — it pays {W} alone."""
    game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
    _w1g2_put(game, set_pool, 1, "Black Knight")
    assert _w1g2_cast(game, "Stormscape Battlemage", kick=("{2}{B}",)) is None
    assert [c.name for c in game.players[0].graveyard] == ["Stormscape Battlemage"]

    seven = ["Island"] * 3 + ["Plains"] + ["Swamp"] * 3
    _game, action = _w1g2_ai_table(
        set_pool, "Stormscape Battlemage", seven, theirs=["Black Knight"]
    )
    assert action.optional_cost_payments == {"{W}": 1}


def test_w1g2_stormscape_battlemage_cannot_be_aimed_at_a_black_creature(set_pool):
    """"Destroy target **nonblack** creature." The picker never offers the
    black one, and a cast that names it anyway destroys nothing."""
    card = set_pool("PLS")["Stormscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{2}{B}": 1})
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]

    _w1g2_cast(
        game, "Stormscape Battlemage", kick=("{2}{B}",),
        target_permanent_ids=[knight.permanent_id],
    )
    assert game.is_on_battlefield(knight) and game.is_on_battlefield(bears)


def test_w1g2_nightscape_battlemage_returns_up_to_two_nonblack_creatures(set_pool):
    """{2}{U}: "return **up to two** target nonblack creatures to their owners'
    hands." Two are named — one on each side — and each goes to its own
    owner's hand. The black creature is never offered, and no land is touched
    (that is the other kicker's trigger)."""
    card = set_pool("PLS")["Nightscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    mine = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    spec = game.cast_target_spec(0, card, optional_cost_payments={"{2}{U}": 1})
    assert (spec["kind"], spec["max_targets"]) == ("creature", 2)
    assert "exact_targets" not in spec
    assert sorted(entry["name"] for entry in spec["valid_targets"]) == [
        "Grizzly Bears", "Serra Angel",
    ]

    _w1g2_cast(
        game, "Nightscape Battlemage", kick=("{2}{U}",),
        target_permanent_ids=[angel.permanent_id, mine.permanent_id],
    )
    assert [c.name for c in game.players[1].hand] == ["Serra Angel"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert game.is_on_battlefield(knight) and game.is_on_battlefield(forest)


def test_w1g2_nightscape_battlemage_destroys_a_land(set_pool):
    """{2}{R}: "destroy target land." Nothing is returned to a hand."""
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    _w1g2_cast(
        game, "Nightscape Battlemage", kick=("{2}{R}",),
        target_permanent_ids=[forest.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]
    assert game.is_on_battlefield(angel) and game.players[1].hand == []


def test_w1g2_a_both_kicked_battlemage_asks_for_the_second_triggers_target(set_pool):
    """One cast carries one set of target fields, and they are the *first*
    trigger's. Nightscape Battlemage kicked both ways with two creatures named
    returns them — and "destroy target land" then goes on the stack and asks
    its controller, where it used to be handed the two creatures and report
    its target gone (CR 603.3d)."""
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"], humans=(0,))
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    mountain = _w1g2_put(game, set_pool, 0, "Mountain")

    result = game.queue_from_hand(
        0, "Nightscape Battlemage",
        optional_cost_payments={"{2}{U}": 1, "{2}{R}": 1},
        target_permanent_ids=[angel.permanent_id, bears.permanent_id],
    )
    assert result.supported, result
    _w1g2_until_asked(game)

    assert sorted(c.name for c in game.players[1].hand) == [
        "Grizzly Bears", "Serra Angel",
    ]
    (asked,) = game.pending_choices
    assert (asked.kind, asked.player_index) == ("trigger_target", 0)
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Forest", "Mountain"]
    assert game.is_on_battlefield(forest) and game.is_on_battlefield(mountain)

    assert game.confirm_trigger_target(0, permanent_id=forest.permanent_id)
    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(forest) and game.is_on_battlefield(mountain)


def test_w1g2_thunderscape_battlemage_discard_and_enchantment(set_pool):
    """{1}{B}: "target player discards two cards." {G}: "destroy target
    enchantment." Each alone does its own half and nothing of the other."""
    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage"],
        their_hand=["Forest", "Forest", "Grizzly Bears"],
    )
    castle = _w1g2_put(game, set_pool, 1, "Castle")
    _w1g2_cast(game, "Thunderscape Battlemage", kick=("{1}{B}",), target_player_index=1)
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2
    assert game.is_on_battlefield(castle)

    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage"],
        their_hand=["Forest", "Forest", "Grizzly Bears"],
    )
    castle = _w1g2_put(game, set_pool, 1, "Castle")
    _w1g2_cast(
        game, "Thunderscape Battlemage", kick=("{G}",),
        target_permanent_ids=[castle.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Castle"]
    assert len(game.players[1].hand) == 3


def test_w1g2_a_trigger_is_never_handed_another_triggers_target(set_pool):
    """The defect the both-kicked cast exposed. Thunderscape Battlemage kicked
    both ways with the discard aimed at **its own controller**: the enchantment
    trigger was handed that seat, fell to the handler's board scan and
    destroyed the caster's own Crusade. It is asked instead — both
    enchantments on offer — and nothing is destroyed until it is answered."""
    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage", "Forest", "Forest", "Forest"],
        humans=(0,),
    )
    crusade = _w1g2_put(game, set_pool, 0, "Crusade")
    castle = _w1g2_put(game, set_pool, 1, "Castle")

    result = game.queue_from_hand(
        0, "Thunderscape Battlemage",
        optional_cost_payments={"{1}{B}": 1, "{G}": 1}, target_player_index=0,
    )
    assert result.supported, result
    _w1g2_until_asked(game)

    assert game.is_on_battlefield(crusade) and game.is_on_battlefield(castle)
    kinds = sorted((choice.kind, choice.player_index) for choice in game.pending_choices)
    assert kinds == [("discard", 0), ("trigger_target", 0)]
    asked = next(c for c in game.pending_choices if c.kind == "trigger_target")
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Castle", "Crusade"]

    assert game.confirm_trigger_target(0, permanent_id=castle.permanent_id)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert game.is_on_battlefield(crusade) and not game.is_on_battlefield(castle)
    assert len(game.players[0].hand) == 1


def test_w1g2_thornscape_battlemage_two_damage_and_an_artifact(set_pool):
    """{R}: "it deals 2 damage to any target" — a face or a creature. {W}:
    "destroy target artifact.\""""
    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    _w1g2_cast(game, "Thornscape Battlemage", kick=("{R}",), target_player_index=1)
    assert game.players[1].life == 18 and game.is_on_battlefield(ring)

    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    _w1g2_cast(
        game, "Thornscape Battlemage", kick=("{R}",),
        target_permanent_ids=[bears.permanent_id],
    )
    game.check_state_based_actions()
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert game.players[1].life == 20

    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    _w1g2_cast(
        game, "Thornscape Battlemage", kick=("{W}",),
        target_permanent_ids=[ring.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Sol Ring"]
    assert game.players[1].life == 20


def test_w1g2_a_both_kicked_battlemage_puts_two_triggers_on_the_stack(set_pool):
    """With nothing named at cast, CR 603.3d has both choices to make:
    Thornscape Battlemage's two triggers are two stack objects, a human seat
    is asked for each with that trigger's own candidates, and each answer is
    the one that resolves."""
    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"], humans=(0,))
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    pearl = _w1g2_put(game, set_pool, 0, "Mox Pearl")

    result = game.queue_from_hand(
        0, "Thornscape Battlemage", optional_cost_payments={"{R}": 1, "{W}": 1}
    )
    assert result.supported, result
    assert game.resolve_top_of_stack()

    assert len(game.stack) == 2
    damage, destroy = game.pending_choices
    assert (damage.kind, destroy.kind) == ("trigger_target", "trigger_target")
    assert sorted(t["name"] for t in damage.data["targets"]) == [
        "Black Knight", "Mage", "Rival", "Thornscape Battlemage",
    ]
    assert sorted(t["name"] for t in destroy.data["targets"]) == [
        "Mox Pearl", "Sol Ring",
    ]

    assert game.confirm_trigger_target(0, permanent_id=knight.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=ring.permanent_id)
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Black Knight", "Sol Ring",
    ]
    assert game.is_on_battlefield(pearl)
    assert [p.life for p in game.players] == [20, 20]


#: What the cast's picker asks for under each announcement: the *first*
#: trigger that announcement fires and that has a target (CR 702.33g).
_W1G2_PICKERS = [
    ("Sunscape Battlemage", (), "none"),
    ("Sunscape Battlemage", ("{1}{G}",), "creature"),
    ("Sunscape Battlemage", ("{2}{U}",), "none"),
    ("Sunscape Battlemage", ("{1}{G}", "{2}{U}"), "creature"),
    ("Stormscape Battlemage", ("{W}",), "none"),
    ("Stormscape Battlemage", ("{2}{B}",), "creature"),
    ("Nightscape Battlemage", ("{2}{U}",), "creature"),
    ("Nightscape Battlemage", ("{2}{R}",), "land"),
    ("Nightscape Battlemage", ("{2}{U}", "{2}{R}"), "creature"),
    ("Thunderscape Battlemage", ("{1}{B}",), "player"),
    ("Thunderscape Battlemage", ("{G}",), "permanent"),
    ("Thunderscape Battlemage", ("{1}{B}", "{G}"), "player"),
    ("Thornscape Battlemage", ("{R}",), "any"),
    ("Thornscape Battlemage", ("{W}",), "artifact"),
    ("Thornscape Battlemage", ("{R}", "{W}"), "any"),
]


@_w1g2_pytest.mark.parametrize("name,taken,kind", _W1G2_PICKERS)
def test_w1g2_a_battlemage_names_a_target_only_for_the_kicker_it_paid(
    set_pool, name, taken, kind
):
    """CR 702.33g: "the spell's controller chooses those targets only if that
    spell was kicked" — and with two kickers, only if it was kicked with the
    one the target belongs to."""
    card = set_pool("PLS")[name]
    game = _w1g2_duel(set_pool, [name])
    spec = game.cast_target_spec(
        0, card, optional_cost_payments={key: 1 for key in taken}
    )
    assert spec["kind"] == kind
    assert spec["requires_target"] is (kind != "none")


def test_w1g2_a_recast_battlemage_forgets_how_it_was_kicked(set_pool):
    """CR 400.7: the Battlemage that drew two cards, returned to its owner's
    hand and cast again for its mana cost alone is a new object that was
    kicked with nothing — no stamp, and no second pair of cards."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage", "Unsummon"])
    mage = _w1g2_cast(game, "Sunscape Battlemage", kick=("{2}{U}",))
    assert mage.metadata.get(_W1G2_KICKED_WITH) == ("{2}{U}",)
    drawn = [c for c in game.players[0].hand if c.name != "Unsummon"]
    assert len(drawn) == 2

    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[mage.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert "Sunscape Battlemage" in [c.name for c in game.players[0].hand]

    again = _w1g2_cast(game, "Sunscape Battlemage")
    assert again is not mage
    assert not again.metadata.get(_W1G2_KICKED)
    assert not again.metadata.get(_W1G2_KICKED_WITH)
    assert len(game.players[0].hand) == 2


def test_w1g2_a_clone_of_a_kicked_battlemage_was_kicked_with_nothing(set_pool):
    """A Clone that enters as a copy of a both-kicked Sunscape Battlemage has
    the Battlemage's two entry triggers (CR 707.5) and was cast as a *Clone*,
    which prints no kicker: neither "if" holds, so it draws nothing."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage", "Clone"])
    mage = _w1g2_cast(game, "Sunscape Battlemage", kick=("{1}{G}", "{2}{U}"))
    held = len(game.players[0].hand)

    result = game.queue_from_hand(
        0, "Clone", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[mage.permanent_id],
    )
    assert result.supported, result
    _w1g2_resolve_stack(game)
    clone = next(p for p in game.controlled_by(0) if p is not mage)

    assert clone.effective_card.name == "Sunscape Battlemage"
    assert not clone.metadata.get(_W1G2_KICKED_WITH)
    assert len(game.players[0].hand) == held - 1
    assert game.stack == []


def test_w1g2_either_kicker_alone_is_a_kicked_spell_to_everything_else(set_pool):
    """CR 702.33d: "any of that spell's kicker costs". Saproling Infestation's
    "whenever a player kicks a spell" sees a Battlemage that paid only its
    *second* kicker, and does not see an unkicked one."""
    for taken, tokens in (((), 0), (("{2}{U}",), 1), (("{1}{G}",), 1)):
        game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
        _w1g2_put(game, set_pool, 1, "Saproling Infestation")
        _w1g2_cast(game, "Sunscape Battlemage", kick=taken)
        saprolings = [
            p for p in game.controlled_by(1) if p.metadata.get("is_token")
        ]
        assert len(saprolings) == tokens, taken


def _w1g2_ai_table(set_pool, name, lands, mine=(), theirs=()):
    """Seat 0 is an AI holding *name* with *lands* untapped and nothing
    floating; returns the game and what it would cast."""
    game = _w1g2_duel(set_pool, [name], pool={})
    for land in lands:
        _w1g2_put(game, set_pool, 0, land)
    for seat, names in ((0, mine), (1, theirs)):
        for permanent in names:
            _w1g2_put(game, set_pool, seat, permanent)
    return game, _w1g2_choose_cast_action(game, 0)  # _w1g2_ai_table


def test_w1g2_the_ai_kicks_what_it_can_pay_for_and_has_a_target_for(set_pool):
    """The stated policy, per kicker. Eight lands and an opposing flier: both.
    The same lands and the only flier its own: the draw alone. Five lands that
    make no blue and no flier to hit: the plain 2/2."""
    wwwgguuu = ["Plains"] * 3 + ["Forest"] * 2 + ["Island"] * 3
    _game, both = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", wwwgguuu, theirs=["Serra Angel"]
    )
    assert both.optional_cost_payments == {"{1}{G}": 1, "{2}{U}": 1}
    assert len(both.land_tap_indices) == 8

    _game, draw = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", wwwgguuu, mine=["Serra Angel"]
    )
    assert draw.optional_cost_payments == {"{2}{U}": 1}

    _game, plain = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", ["Plains"] * 3 + ["Forest"] * 2,
        theirs=["Grizzly Bears"],
    )
    assert (plain.card_name, plain.optional_cost_payments) == (
        "Sunscape Battlemage", None,
    )


def test_w1g2_the_ai_does_not_pay_to_destroy_its_own_permanent(set_pool):
    """The second trigger's target is chosen on the stack, where the choice is
    mandatory — so a seat that pays for it while only its own seat holds a
    legal target must destroy its own. Nightscape Battlemage with every land
    on the table its own does not pay {2}{R}; Thornscape Battlemage with the
    only artifact its own does not pay {W}."""
    nine = ["Swamp"] * 3 + ["Island"] * 3 + ["Mountain"] * 3
    _game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", nine, theirs=["Serra Angel"]
    )
    assert action.optional_cost_payments == {"{2}{U}": 1}

    _game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", nine, theirs=["Serra Angel", "Forest"]
    )
    assert action.optional_cost_payments == {"{2}{U}": 1, "{2}{R}": 1}

    five = ["Forest"] * 3 + ["Mountain", "Plains"]
    _game, action = _w1g2_ai_table(
        set_pool, "Thornscape Battlemage", five, mine=["Sol Ring"]
    )
    assert action.optional_cost_payments == {"{R}": 1}
    _game, action = _w1g2_ai_table(
        set_pool, "Thornscape Battlemage", five, theirs=["Sol Ring"]
    )
    assert action.optional_cost_payments == {"{R}": 1, "{W}": 1}


def test_w1g2_the_ai_aims_a_battlemages_discard_at_an_opponent(set_pool):
    """Thunderscape Battlemage's "target player discards two cards" is the
    cast's seat, and the AI used to give a creature spell's seat to itself."""
    six = ["Mountain"] * 3 + ["Swamp"] * 2 + ["Forest"]
    game, action = _w1g2_ai_table(
        set_pool, "Thunderscape Battlemage", six, theirs=["Castle"]
    )
    assert action.optional_cost_payments == {"{1}{B}": 1, "{G}": 1}
    assert action.target_player_index == 1


def test_w1g2_the_ai_returns_two_opposing_creatures_not_its_own(set_pool):
    """Nightscape Battlemage's "up to two target nonblack creatures", named by
    the AI: both of the opponent's, with two of its own on the table."""
    six = ["Swamp"] * 3 + ["Island"] * 3
    game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", six,
        mine=["Grizzly Bears", "Air Elemental"],
        theirs=["Serra Angel", "Hill Giant"],
    )
    assert action.optional_cost_payments == {"{2}{U}": 1}
    assert action.target_player_index == 1
    named = sorted(
        game.permanent_at(game.players[1], slot).card.name
        for slot in action.target_permanent_index
    )
    assert named == ["Hill Giant", "Serra Angel"]


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_battlemages_through_whole_games():
    """All five pinned into both decks of six simulated games: they are cast,
    several are kicked, and none is ever refused or left owing a prompt as its
    step ends. (The pool is a measured set, so other cards' unsupported casts
    are in the report; only the Battlemages' lines are read. The floors are
    well under what the seed gives today — five cast, eleven kicked — so
    another card becoming castable does not move them.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [name for name, _first, _second in _W1G2_BATTLEMAGES]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("PLS", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 3, sorted(cast)
    kicked = [line for line in report.log_lines if " kicked " in line and "Battlemage" in line]
    assert len(kicked) >= 4, kicked
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if "Battlemage" in i.message] == []
    w1g2_battlemages_left_nothing_owing = not report.steps_left_owing
    assert w1g2_battlemages_left_nothing_owing, report.steps_left_owing


# Waterspout Elemental ------------------------------------------------------


def test_w1g2_waterspout_elemental_kicked_empties_the_board_and_skips_a_turn(set_pool):
    """"When this creature enters, if it was kicked, return all **other**
    creatures to their owners' hands and you skip your next turn." Both halves,
    for the {U}: every creature but the Elemental goes home, and the seat that
    cast it sits out its next turn — the opponent takes two in a row."""
    game = _w1g2_duel(set_pool, ["Waterspout Elemental"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    _w1g2_put(game, set_pool, 1, "Serra Angel")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    before = _w1g2_floating(game)
    elemental = _w1g2_cast(game, "Waterspout Elemental", kick=("{U}",))

    assert before - _w1g2_floating(game) == 6
    assert _w1g2_names(game, 0) == ["Waterspout Elemental"]
    assert _w1g2_names(game, 1) == ["Forest"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].hand] == ["Serra Angel"]
    assert game.is_on_battlefield(elemental) and game.is_on_battlefield(forest)
    assert game._has_keyword(elemental, "flying")

    game.active_player_index = 0
    assert [game.start_next_turn() for _ in range(4)] == [1, 1, 0, 1]


def test_w1g2_waterspout_elemental_unkicked_is_a_five_mana_flier(set_pool):
    """Unkicked, the entry trigger does not trigger (CR 603.4): nothing is
    returned and no turn is skipped."""
    game = _w1g2_duel(set_pool, ["Waterspout Elemental"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    _w1g2_put(game, set_pool, 1, "Serra Angel")
    before = _w1g2_floating(game)
    _w1g2_cast(game, "Waterspout Elemental")

    assert before - _w1g2_floating(game) == 5
    assert _w1g2_names(game, 0) == ["Grizzly Bears", "Waterspout Elemental"]
    assert _w1g2_names(game, 1) == ["Serra Angel"]
    game.active_player_index = 0
    assert [game.start_next_turn() for _ in range(3)] == [1, 0, 1]


# Gating ---------------------------------------------------------------------

#: The ten gating creatures and the two colours each one's entry trigger names.
_W1G2_GATERS = [
    ("Cavern Harpy", "U", "B"),
    ("Fleetfoot Panther", "G", "W"),
    ("Horned Kavu", "R", "G"),
    ("Lava Zombie", "B", "R"),
    ("Marsh Crocodile", "U", "B"),
    ("Razing Snidd", "B", "R"),
    ("Shivan Wurm", "R", "G"),
    ("Silver Drake", "W", "U"),
    ("Sparkcaster", "R", "G"),
    ("Steel Leaf Paladin", "G", "W"),
]

#: A vanilla Alpha creature of each colour, to stand on the board.
_W1G2_OF_COLOR = {
    "W": "Savannah Lions", "U": "Merfolk of the Pearl Trident",
    "B": "Black Knight", "R": "Goblin Balloon Brigade", "G": "Grizzly Bears",
}


def _w1g2_gate_prompt(game):
    """The one gating prompt owed, with the names it offers."""
    asked = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    offered = [p.card.name for p in game.live_permanent_set_choices(asked)]
    return asked, offered  # _w1g2_gate_prompt


@_w1g2_pytest.mark.parametrize("name,one,two", _W1G2_GATERS)
def test_w1g2_a_gater_alone_returns_itself(set_pool, name, one, two):
    """The return is not optional and the creature that asks is itself a legal
    answer — so alone, or beside only creatures of the wrong colours, it is
    the only one, and the card goes back to its owner's hand.

    (Marsh Crocodile's *other* trigger then makes each player discard a card,
    and the Crocodile is the only card its controller holds.)"""
    off = next(c for c in "WUBRG" if c not in (one, two))
    for bystanders in ((), (_W1G2_OF_COLOR[off],)):
        game = _w1g2_duel(set_pool, [name])
        for bystander in bystanders:
            _w1g2_put(game, set_pool, 0, bystander)
        announced = {"target_player_index": 1} if name == "Sparkcaster" else {}
        assert _w1g2_cast(game, name, **announced) is None
        assert _w1g2_names(game, 0) == list(bystanders)
        assert f"{name} returned {name} to hand" in game.log
        mage = game.players[0]
        held = mage.graveyard if name == "Marsh Crocodile" else mage.hand
        assert [c.name for c in held] == [name]


@_w1g2_pytest.mark.parametrize("name,one,two", _W1G2_GATERS)
def test_w1g2_a_gater_asks_which_creature_and_takes_only_a_legal_answer(
    set_pool, name, one, two
):
    """A human seat is *asked*, and offered exactly what the line prints: the
    creatures of either colour it controls, the gater included — not one of
    another colour, not an opponent's. One creature, no fewer and no more."""
    off = next(c for c in "WUBRG" if c not in (one, two))
    game = _w1g2_duel(set_pool, [name], humans=(0,))
    first = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[one])
    second = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[two])
    wrong = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[off])
    theirs = _w1g2_put(game, set_pool, 1, _W1G2_OF_COLOR[two])

    announced = {"target_player_index": 1} if name == "Sparkcaster" else {}
    assert game.queue_from_hand(0, name, **announced).supported
    _w1g2_until_asked(game)
    asked, offered = _w1g2_gate_prompt(game)
    assert asked.player_index == 0
    assert offered == [_W1G2_OF_COLOR[one], _W1G2_OF_COLOR[two], name]

    for illegal in (
        [wrong.permanent_id], [theirs.permanent_id], [],
        [first.permanent_id, second.permanent_id],
    ):
        assert not game.confirm_permanent_set_choice(0, illegal), illegal
    assert not game.confirm_permanent_set_choice(1, [first.permanent_id])

    assert game.confirm_permanent_set_choice(0, [second.permanent_id])
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == [_W1G2_OF_COLOR[two]]
    assert _w1g2_names(game, 0) == [
        _W1G2_OF_COLOR[one], _W1G2_OF_COLOR[off], name,
    ]
    assert game.is_on_battlefield(theirs)


def test_w1g2_gating_reads_colour_through_the_layers(set_pool):
    """Cavern Harpy asks for "a blue or black creature". A green creature
    turned blue (Thoughtlace) is one; a black creature turned red (Chaoslace)
    is not — the printed colours answer neither question."""
    game = _w1g2_duel(set_pool, ["Thoughtlace", "Cavern Harpy"], humans=(0,))
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Thoughtlace", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert game.queue_from_hand(0, "Cavern Harpy").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Grizzly Bears", "Cavern Harpy"]

    game = _w1g2_duel(set_pool, ["Chaoslace", "Cavern Harpy"], humans=(0,))
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    assert game.queue_from_hand(
        0, "Chaoslace", target_permanent_ids=[knight.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert game.queue_from_hand(0, "Cavern Harpy").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Cavern Harpy"]


def test_w1g2_gating_does_not_target(set_pool):
    """"Return a red or green creature you control" names no target, so shroud
    is no answer to it: Elvish Lookout is offered and goes home."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"], humans=(0,))
    lookout = _w1g2_put(game, set_pool, 0, "Elvish Lookout")
    assert game._has_keyword(lookout, "shroud")
    assert game.queue_from_hand(0, "Horned Kavu").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Elvish Lookout", "Horned Kavu"]
    assert game.confirm_permanent_set_choice(0, [lookout.permanent_id])
    assert [c.name for c in game.players[0].hand] == ["Elvish Lookout"]
    assert _w1g2_names(game, 0) == ["Horned Kavu"]


def test_w1g2_a_gated_creature_goes_to_its_owners_hand(set_pool):
    """"…a creature **you control** to **its owner's** hand": a creature
    taken from the opponent is a legal answer and returns to the opponent."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"], humans=(0,))
    stolen = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    _w1g2_change_control(stolen, 0, source="w1g2")
    assert game.controller_index_of(stolen) == 0
    assert game.queue_from_hand(0, "Horned Kavu").supported
    _w1g2_until_asked(game)
    assert game.confirm_permanent_set_choice(0, [stolen.permanent_id])
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert game.players[0].hand == []
    assert _w1g2_names(game, 0) == ["Horned Kavu"]


def test_w1g2_a_headless_gater_gives_back_its_cheapest_creature_not_its_best(set_pool):
    """A seat nobody asks used to give back whichever legal creature had been
    on the battlefield longest. Craw Wurm, then Llanowar Elves, then Horned
    Kavu: the Elves go home, not the Wurm — and not the Kavu, which is the
    answer that undoes the cast."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"])
    _w1g2_put(game, set_pool, 0, "Craw Wurm")
    _w1g2_put(game, set_pool, 0, "Llanowar Elves")
    _w1g2_cast(game, "Horned Kavu")
    assert [c.name for c in game.players[0].hand] == ["Llanowar Elves"]
    assert _w1g2_names(game, 0) == ["Craw Wurm", "Horned Kavu"]


def test_w1g2_the_ai_holds_a_gater_it_could_only_return(set_pool):
    """Cast with no other red or green creature, Shivan Wurm returns itself
    and the seat has spent five mana on nothing — and proposes it again next
    turn. With one to give back that costs no more than the Wurm, it is cast;
    Horned Kavu is not cast to send a Shivan Wurm home."""
    five = ["Mountain"] * 3 + ["Forest"] * 2
    _game, alone = _w1g2_ai_table(set_pool, "Shivan Wurm", five)
    assert alone is None or alone.card_name != "Shivan Wurm"

    _game, beside_wrong = _w1g2_ai_table(
        set_pool, "Shivan Wurm", five, mine=["Savannah Lions"]
    )
    assert beside_wrong is None or beside_wrong.card_name != "Shivan Wurm"

    _game, with_elves = _w1g2_ai_table(
        set_pool, "Shivan Wurm", five, mine=["Llanowar Elves"]
    )
    assert with_elves.card_name == "Shivan Wurm"

    _game, trade_down = _w1g2_ai_table(
        set_pool, "Horned Kavu", five, mine=["Craw Wurm"]
    )
    assert trade_down is None or trade_down.card_name != "Horned Kavu"


def test_w1g2_cavern_harpy_pays_a_life_to_come_home(set_pool):
    """"Pay 1 life: Return this creature to its owner's hand." Flying, and an
    escape that costs life rather than mana."""
    game = _w1g2_duel(set_pool, [], pool={})
    _w1g2_put(game, set_pool, 0, "Black Knight")
    harpy = _w1g2_put(game, set_pool, 0, "Cavern Harpy")
    game.auto_resolve_pending_choices()
    assert _w1g2_names(game, 0) == ["Cavern Harpy"]
    assert game._has_keyword(harpy, "flying")

    assert game.activate_permanent_ability(0, "Cavern Harpy").supported
    _w1g2_resolve_stack(game)
    assert game.players[0].life == 19
    assert sorted(c.name for c in game.players[0].hand) == [
        "Black Knight", "Cavern Harpy",
    ]
    assert _w1g2_names(game, 0) == []


def test_w1g2_fleetfoot_panther_has_flash_and_the_others_do_not(set_pool):
    """Flash is what makes the Panther's gate a rescue: it may be cast any
    time its controller has priority, and the timing gate the web layer asks
    says so of it and of no other gater."""
    game = _w1g2_duel(set_pool, ["Fleetfoot Panther"])
    lions = _w1g2_put(game, set_pool, 0, "Savannah Lions")
    game.active_player_index = 1
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    for name, _one, _two in _W1G2_GATERS:
        assert _w1g2_instant_speed(set_pool("PLS")[name], game, 0) is (
            name == "Fleetfoot Panther"
        ), name

    panther = _w1g2_cast(game, "Fleetfoot Panther")
    assert (panther.effective_power, panther.effective_toughness) == (3, 4)
    assert [c.name for c in game.players[0].hand] == ["Savannah Lions"]
    assert not game.is_on_battlefield(lions)


def test_w1g2_lava_zombie_pumps_until_end_of_turn(set_pool):
    """"{2}: This creature gets +1/+0 until end of turn.\""""
    game = _w1g2_duel(set_pool, [])
    _w1g2_put(game, set_pool, 0, "Black Knight")
    zombie = _w1g2_put(game, set_pool, 0, "Lava Zombie")
    game.auto_resolve_pending_choices()
    before = _w1g2_floating(game)
    assert game.activate_permanent_ability(0, "Lava Zombie").supported
    _w1g2_resolve_stack(game)
    assert (zombie.effective_power, zombie.effective_toughness) == (5, 3)
    assert before - _w1g2_floating(game) == 2
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert (zombie.effective_power, zombie.effective_toughness) == (4, 3)


def test_w1g2_marsh_crocodile_makes_each_player_discard(set_pool):
    """Two entry triggers: the gate, and "each player discards a card" — each
    seat choosing its own."""
    game = _w1g2_duel(
        set_pool, ["Marsh Crocodile", "Forest", "Island"], humans=(0, 1),
        their_hand=["Grizzly Bears", "Forest"],
    )
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    assert game.queue_from_hand(0, "Marsh Crocodile").supported
    _w1g2_until_asked(game)
    assert sorted((c.kind, c.player_index) for c in game.pending_choices) == [
        ("discard", 0), ("discard", 1), ("permanent_set_choice", 0),
    ]
    assert game.confirm_permanent_set_choice(0, [knight.permanent_id])
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == ["Marsh Crocodile"]
    assert len(game.players[0].graveyard) == 1
    assert len(game.players[1].graveyard) == 1 and len(game.players[1].hand) == 1
    assert "Black Knight" in [c.name for c in game.players[0].hand]


def test_w1g2_razing_snidd_makes_each_player_sacrifice_a_land(set_pool):
    """"Each player sacrifices a land **of their choice**": a prompt for each
    seat, over that seat's own lands."""
    game = _w1g2_duel(set_pool, ["Razing Snidd"], humans=(0, 1))
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    for seat in (0, 1):
        _w1g2_put(game, set_pool, seat, "Swamp")
        _w1g2_put(game, set_pool, seat, "Mountain")
    assert game.queue_from_hand(0, "Razing Snidd").supported
    _w1g2_until_asked(game)
    assert sorted((c.kind, c.player_index) for c in game.pending_choices) == [
        ("permanent_set_choice", 0), ("sacrifice", 0), ("sacrifice", 1),
    ]
    assert game.confirm_permanent_set_choice(0, [knight.permanent_id])
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    for seat in (0, 1):
        lands = [p for p in game.controlled_by(seat) if p.has_type("land")]
        assert len(lands) == 1, seat
        assert len([c for c in game.players[seat].graveyard if "Land" in c.type_line]) == 1
    snidd = next(p for p in game.controlled_by(0) if p.card.name == "Razing Snidd")
    assert (snidd.effective_power, snidd.effective_toughness) == (3, 3)


def test_w1g2_sparkcaster_pings_a_player_as_it_gates(set_pool):
    """"…it deals 1 damage to target player or planeswalker" beside the gate:
    the named player takes one, and the gate is still answered."""
    game = _w1g2_duel(set_pool, ["Sparkcaster"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    caster = _w1g2_cast(game, "Sparkcaster", target_player_index=1)
    assert [p.life for p in game.players] == [20, 19]
    assert (caster.effective_power, caster.effective_toughness) == (5, 3)
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]


@_w1g2_pytest.mark.parametrize("name,keyword,body", [
    ("Shivan Wurm", "trample", (7, 7)),
    ("Silver Drake", "flying", (3, 3)),
    ("Steel Leaf Paladin", "first strike", (4, 4)),
    ("Horned Kavu", None, (3, 4)),
])
def test_w1g2_a_gater_that_stays_is_the_printed_body(set_pool, name, keyword, body):
    """With another creature to give back, the gater stays: its printed body
    and its printed keyword, at a discount the returned creature paid for."""
    colours = next((one, two) for gater, one, two in _W1G2_GATERS if gater == name)
    game = _w1g2_duel(set_pool, [name])
    _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[colours[0]])
    gater = _w1g2_cast(game, name)
    assert (gater.effective_power, gater.effective_toughness) == body
    if keyword is not None:
        assert game._has_keyword(gater, keyword)
    assert [c.name for c in game.players[0].hand] == [_W1G2_OF_COLOR[colours[0]]]


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_gaters_without_bouncing_them_back(set_pool):
    """All ten pinned into both decks of six simulated games. Before this
    round 112 of 127 gating triggers returned the creature that had just been
    cast; now a gater is cast when there is something cheaper to give back,
    and none ever returns itself. (Floors well under today's seven cast and
    thirty-odd gates, for the Battlemage run's reason.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [name for name, _one, _two in _W1G2_GATERS]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("PLS", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    assert report.games_completed == 6
    cast = [
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    ]
    assert len(cast) >= 4, cast
    gated = [
        line for line in report.log_lines
        if " to hand" in line and any(f"{name} returned " in line for name in names)
    ]
    assert len(gated) >= 8
    undone = [
        line for line in gated
        if any(f"{name} returned {name} to hand" in line for name in names)
    ]
    assert undone == []
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if any(n in i.message for n in names)] == []
    w1g2_gaters_left_nothing_owing = not report.steps_left_owing
    assert w1g2_gaters_left_nothing_owing, report.steps_left_owing
# end of the W1G2 creatures block
