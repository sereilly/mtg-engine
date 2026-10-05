"""Invasion creatures.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: kicker ---
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.mana_payment import mana_cost_from_symbols as _w1g1_symbols
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import _mk_card as _w1g1_mk_card
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, pool=None, library=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (INV names)
    with *pool* already floating. Costs are enforced because a kicker is a
    price: a rig that waives mana cannot tell a kicked cast from a free one."""
    inv = set_pool("INV")
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=list(library) or [forest] * 10,
        hand=[inv[name] for name in hand],
    )
    theirs = _W1G1PlayerState("Bystander", library=[forest] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    return game  # _w1g1_duel


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g1_put


def _w1g1_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g1_floating


def _w1g1_price(printed: str) -> int:
    return sum((_w1g1_symbols(printed) or {}).values())  # _w1g1_price


def _w1g1_cast(game, name, *, kick=None, **announced):
    """Cast *name* from seat 0, kicked for *kick* (the offer's key) or not, and
    resolve it. Returns the permanent it became, or None."""
    result = game.cast_from_hand(
        0, name, optional_cost_payments={kick: 1} if kick else None, **announced
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    return next(
        (p for p in game.controlled_by(0) if p.card.name == name), None
    )  # _w1g1_cast


#: The twelve "If this creature was kicked, it enters with <N> +1/+1 counters
#: on it [and with <ability>]" creatures: name, printed body, kicked body, and
#: the keyword the kicked one additionally has.
_W1G1_COUNTER_KICKERS = [
    ("Ardent Soldier", (1, 2), (2, 3), None),
    ("Benalish Lancer", (2, 2), (4, 4), "first strike"),
    ("Prison Barricade", (1, 3), (2, 4), None),
    ("Faerie Squadron", (1, 1), (3, 3), "flying"),
    ("Vodalian Serpent", (2, 2), (6, 6), None),
    ("Duskwalker", (1, 1), (3, 3), "fear"),
    ("Urborg Skeleton", (0, 1), (1, 2), None),
    ("Kavu Aggressor", (3, 2), (4, 3), None),
    ("Pouncing Kavu", (1, 1), (3, 3), "haste"),
    ("Kavu Titan", (2, 2), (5, 5), "trample"),
    ("Llanowar Elite", (1, 1), (6, 6), None),
    ("Pincer Spider", (2, 3), (3, 4), None),
]


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_an_unkicked_creature_is_the_printed_body(
    set_pool, name, printed, kicked, keyword
):
    """Cast for its mana cost alone: the printed body, no counters, the mana
    cost and nothing more spent — and **not** the keyword the kicked one gets.
    That last half is a real failure this round found: the word sits in a
    static line, the printed-ability scan read it, and every unkicked Faerie
    Squadron flew."""
    card = set_pool("INV")[name]
    game = _w1g1_duel(set_pool, [name])
    before = _w1g1_floating(game)
    creature = _w1g1_cast(game, name)

    assert (creature.effective_power, creature.effective_toughness) == printed
    assert int(creature.metadata.get("plus_counters", 0)) == 0
    assert not creature.metadata.get(_W1G1_KICKED)
    assert before - _w1g1_floating(game) == _w1g1_price(card.mana_cost)
    if keyword is not None:
        assert not game._has_keyword(creature, keyword)


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_a_kicked_creature_enters_with_its_counters(
    set_pool, name, printed, kicked, keyword
):
    """CR 702.33a/d + CR 614.1c: the kicker is paid on top of the mana cost,
    and the creature enters with the printed number of +1/+1 counters (real
    counters, not a pump) and whatever "and with" names."""
    card = set_pool("INV")[name]
    kicker = _w1g1_kicker_cost(card.oracle_text)
    assert kicker is not None
    game = _w1g1_duel(set_pool, [name])
    before = _w1g1_floating(game)
    creature = _w1g1_cast(game, name, kick=kicker)

    assert (creature.effective_power, creature.effective_toughness) == kicked
    assert int(creature.metadata.get("plus_counters", 0)) == kicked[0] - printed[0]
    assert before - _w1g1_floating(game) == (
        _w1g1_price(card.mana_cost) + _w1g1_price(kicker)
    )
    assert f"Kicker kicked {name}" in game.log
    if keyword is not None:
        assert game._has_keyword(creature, keyword)


@_w1g1_pytest.mark.parametrize("name,printed,kicked,keyword", _W1G1_COUNTER_KICKERS)
def test_w1g1_a_creature_nothing_cast_was_not_kicked(
    set_pool, name, printed, kicked, keyword
):
    """Put onto the battlefield without being cast (a reanimation, a blink):
    no cast, so no CR 601.2b, so not kicked — the printed body."""
    game = _w1g1_duel(set_pool, [])
    creature = _w1g1_put(game, 0, set_pool("INV")[name])
    assert (creature.effective_power, creature.effective_toughness) == printed
    if keyword is not None:
        assert not game._has_keyword(creature, keyword)


def test_w1g1_a_kicker_the_pool_cannot_pay_is_refused_with_nothing_spent(set_pool):
    """CR 601.2h: Faerie Squadron is {U} with kicker {3}{U}. Two blue mana pays
    the creature and not the kicked creature, and a refused cast spends none."""
    game = _w1g1_duel(set_pool, ["Faerie Squadron"], pool={"U": 2})
    refused = game.cast_from_hand(
        0, "Faerie Squadron", optional_cost_payments={"{3}{U}": 1}
    )
    assert not refused.supported
    assert _w1g1_floating(game) == 2
    assert [c.name for c in game.players[0].hand] == ["Faerie Squadron"]
    assert not list(game.controlled_by(0))


def test_w1g1_the_kicker_is_offered_by_name_and_priced_against_the_pool(set_pool):
    """The browser's cast-offer prompt is built from `cast_cost_offers`: the
    price is labelled with the keyword, and `max_times` says whether the pool
    in front of the player can pay it on top of the spell."""
    card = set_pool("INV")["Kavu Titan"]
    rich = _w1g1_duel(set_pool, ["Kavu Titan"])
    poor = _w1g1_duel(set_pool, ["Kavu Titan"], pool={"G": 2})
    [offer] = rich.cast_cost_offers(0, card)
    assert (offer["symbols"], offer["label"], offer["max_times"]) == (
        "{2}{G}", "kicker", 1,
    )
    [offer] = poor.cast_cost_offers(0, card)
    assert offer["max_times"] == 0


def test_w1g1_a_granted_keyword_is_an_ability_not_part_of_the_card(set_pool):
    """Kavu Titan's trample is granted at layer 6 with no duration, so it lasts
    past the turn it entered — and is still a *grant*: it sits in the ability
    record, which is what lets a later removal take it and leave the counters."""
    game = _w1g1_duel(set_pool, ["Kavu Titan"])
    titan = _w1g1_cast(game, "Kavu Titan", kick="{2}{G}")
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert game._has_keyword(titan, "trample")
    assert "trample" not in {k.lower() for k in titan.card.keywords}


def test_w1g1_prison_barricade_attacks_only_when_it_was_kicked(set_pool):
    """Defender stops the printed Wall; the kicked one is granted "This
    creature can attack as though it didn't have defender." — and still *has*
    defender (CR 609.4: an "as though" lifts the one restriction it names)."""
    for kick, may_attack in ((None, False), ("{1}{W}", True)):
        game = _w1g1_duel(set_pool, ["Prison Barricade"])
        wall = _w1g1_cast(game, "Prison Barricade", kick=kick)
        wall.metadata["summoning_sickness_turn"] = -99
        assert game.can_attack(wall, 1) is may_attack
        assert game._has_keyword(wall, "defender")


#: The five Emissaries: name, kicker, the spec kind a kicked cast asks for,
#: the LEA/INV card to aim at, and where that card must end up.
_W1G1_EMISSARIES = [
    ("Benalish Emissary", "{1}{G}", "Forest", "graveyard"),
    ("Tolarian Emissary", "{1}{W}", "Saproling Infestation", "graveyard"),
    ("Urborg Emissary", "{1}{U}", "Grizzly Bears", "hand"),
    ("Shivan Emissary", "{1}{B}", "Grizzly Bears", "graveyard"),
    ("Verduran Emissary", "{1}{R}", "Sol Ring", "graveyard"),
]


def _w1g1_victim_card(set_pool, name):
    return set_pool("INV").get(name) or set_pool("LEA")[name]  # _w1g1_victim_card


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_a_kicked_emissary_does_its_entry_effect(
    set_pool, name, kicker, victim, ends_in
):
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))
    if name in ("Shivan Emissary", "Verduran Emissary"):
        # "It can't be regenerated.": a shield must not save it. (The other
        # two destroyers print no such rider, and a shield would.)
        target.regeneration_shield = 1
    _w1g1_cast(game, name, kick=kicker, target_permanent_ids=[target.permanent_id])

    assert not game.is_on_battlefield(target)
    pile = getattr(game.players[1], ends_in)
    assert [card.name for card in pile] == [victim]


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_an_unkicked_emissary_does_nothing_on_entry(
    set_pool, name, kicker, victim, ends_in
):
    """CR 603.4: the intervening "if it was kicked" is false, so the ability
    does not trigger — even when the caster named the very target a kicked
    cast would have hit. Nothing goes on the stack and nothing is touched."""
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))
    result = game.queue_from_hand(0, name, target_permanent_ids=[target.permanent_id])
    assert result.supported, result
    assert game.resolve_top_of_stack()

    assert game.stack == []
    assert game.is_on_battlefield(target)
    assert any(p.card.name == name for p in game.controlled_by(0))


@_w1g1_pytest.mark.parametrize("name,kicker,victim,ends_in", _W1G1_EMISSARIES)
def test_w1g1_an_emissary_names_a_target_only_when_kicked(
    set_pool, name, kicker, victim, ends_in
):
    """CR 702.33g: "the spell's controller chooses those targets only if that
    spell was kicked." The spec a player is shown asks for nothing until the
    kicker is taken, and then offers exactly the permanent the text names."""
    card = set_pool("INV")[name]
    game = _w1g1_duel(set_pool, [name])
    target = _w1g1_put(game, 1, _w1g1_victim_card(set_pool, victim))

    plain = game.cast_target_spec(0, card)
    assert (plain["kind"], plain["requires_target"]) == ("none", False)
    assert plain["cost_offers"][0]["label"] == "kicker"

    kicked = game.cast_target_spec(0, card, optional_cost_payments={kicker: 1})
    assert kicked["requires_target"]
    assert target.card.name in [entry["name"] for entry in kicked["valid_targets"]]


def test_w1g1_shivan_emissary_cannot_be_aimed_at_a_black_creature(set_pool):
    """"Destroy target **nonblack** creature." The picker never offers the
    black one, and a cast that names it anyway destroys nothing."""
    game = _w1g1_duel(set_pool, ["Shivan Emissary"])
    knight = _w1g1_put(game, 1, set_pool("LEA")["Black Knight"])
    bears = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    spec = game.cast_target_spec(
        0, set_pool("INV")["Shivan Emissary"], optional_cost_payments={"{1}{B}": 1}
    )
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]

    _w1g1_cast(
        game, "Shivan Emissary", kick="{1}{B}",
        target_permanent_ids=[knight.permanent_id],
    )
    assert game.is_on_battlefield(knight) and game.is_on_battlefield(bears)


def test_w1g1_a_kicked_emissary_with_no_target_named_chooses_on_the_stack(set_pool):
    """A cast that announced nothing leaves the choice to CR 603.3d: the
    trigger goes on the stack and picks there (a headless seat takes the
    picker's default), rather than resolving against nothing."""
    game = _w1g1_duel(set_pool, ["Verduran Emissary"])
    ring = _w1g1_put(game, 1, set_pool("LEA")["Sol Ring"])
    _w1g1_cast(game, "Verduran Emissary", kick="{1}{R}")
    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[1].graveyard] == ["Sol Ring"]


def test_w1g1_skizzik_is_sacrificed_at_the_end_step_unless_it_was_kicked(set_pool):
    """"At the beginning of the end step, if this creature wasn't kicked,
    sacrifice it." The negated condition, asked of the permanent turns after
    the cast is over — so it has to be on the permanent, not on the stack."""
    plain = _w1g1_duel(set_pool, ["Skizzik"])
    _w1g1_cast(plain, "Skizzik")
    plain.resolve_end_step(0)
    _w1g1_resolve_stack(plain)
    assert not list(plain.controlled_by(0))
    assert [card.name for card in plain.players[0].graveyard] == ["Skizzik"]

    kicked = _w1g1_duel(set_pool, ["Skizzik"])
    skizzik = _w1g1_cast(kicked, "Skizzik", kick="{R}")
    for _ in range(3):
        kicked.resolve_end_step(0)
        _w1g1_resolve_stack(kicked)
    assert kicked.is_on_battlefield(skizzik)
    assert kicked.stack == []

    reanimated = _w1g1_duel(set_pool, [])
    _w1g1_put(reanimated, 0, set_pool("INV")["Skizzik"])
    reanimated.resolve_end_step(0)
    _w1g1_resolve_stack(reanimated)
    assert not list(reanimated.controlled_by(0))


def test_w1g1_thicket_elemental_reveals_until_a_creature_and_shuffles_the_rest(
    set_pool,
):
    """"…reveal cards from the top of your library until you reveal a creature
    card. If you do, put that card onto the battlefield and shuffle all other
    cards revealed this way into your library." Only when kicked."""
    lea = set_pool("LEA")
    stacked = [lea["Forest"], lea["Mountain"], lea["Grizzly Bears"], lea["Island"]]

    kicked = _w1g1_duel(set_pool, ["Thicket Elemental"], library=stacked)
    _w1g1_cast(kicked, "Thicket Elemental", kick="{1}{G}")
    kicked.auto_resolve_pending_choices()
    _w1g1_resolve_stack(kicked)
    assert sorted(p.card.name for p in kicked.controlled_by(0)) == [
        "Grizzly Bears", "Thicket Elemental",
    ]
    # The two lands turned over on the way went back, shuffled in — not binned.
    assert sorted(card.name for card in kicked.players[0].library) == [
        "Forest", "Island", "Mountain",
    ]
    assert kicked.players[0].graveyard == []

    plain = _w1g1_duel(set_pool, ["Thicket Elemental"], library=stacked)
    _w1g1_cast(plain, "Thicket Elemental")
    assert [p.card.name for p in plain.controlled_by(0)] == ["Thicket Elemental"]
    assert [card.name for card in plain.players[0].library] == [
        "Forest", "Mountain", "Grizzly Bears", "Island",
    ]


def test_w1g1_verdeloth_kicked_for_x_makes_x_saprolings(set_pool):
    """Kicker {X}: the X is announced with the kicker (CR 107.3a, an additional
    cost with an {X} in it), paid as generic mana on top of {4}{G}{G}, and read
    by the entry trigger. The tokens are Saprolings, so the anthem beside it
    makes each a 2/2; Verdeloth is a Treefolk but not an *other* one."""
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"])
    before = _w1g1_floating(game)
    verdeloth = _w1g1_cast(game, "Verdeloth the Ancient", kick="{X}", x_value=3)

    assert before - _w1g1_floating(game) == 6 + 3
    saprolings = [p for p in game.controlled_by(0) if p is not verdeloth]
    assert len(saprolings) == 3
    assert {(p.effective_power, p.effective_toughness) for p in saprolings} == {(2, 2)}
    assert (verdeloth.effective_power, verdeloth.effective_toughness) == (4, 7)


def test_w1g1_verdeloth_unkicked_ignores_a_stray_x(set_pool):
    """A declined kicker announces no X (the offer is where the X lives), so a
    number sent with it charges nothing and reaches nothing."""
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"])
    before = _w1g1_floating(game)
    _w1g1_cast(game, "Verdeloth the Ancient", x_value=5)
    assert before - _w1g1_floating(game) == 6
    assert [p.card.name for p in game.controlled_by(0)] == ["Verdeloth the Ancient"]


def test_w1g1_verdeloth_buffs_the_union_once(set_pool):
    """"Saproling creatures **and** other Treefolk creatures get +1/+1" is one
    ability over a union: a creature that is both gets +1/+1, not +2/+2 — and
    an opponent's Treefolk is reached too (the sentence names no controller)."""
    game = _w1g1_duel(set_pool, [])
    _w1g1_put(game, 0, set_pool("INV")["Verdeloth the Ancient"])
    both = _w1g1_put(game, 0, _w1g1_mk_card(
        name="Sapling Elder", type_line="Creature — Treefolk Saproling",
        power=1, toughness=1,
    ))
    treefolk = _w1g1_put(game, 1, _w1g1_mk_card(
        name="Old Oak", type_line="Creature — Treefolk", power=2, toughness=5,
    ))
    bear = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert (both.effective_power, both.effective_toughness) == (2, 2)
    assert (treefolk.effective_power, treefolk.effective_toughness) == (3, 6)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w1g1_an_x_kicker_announces_x_only_once_it_is_taken(set_pool):
    """The spec asks for an X exactly when the kicker is taken, with a ceiling
    the pool can pay: 12 mana less Verdeloth's 6 leaves X at most 6."""
    card = set_pool("INV")["Verdeloth the Ancient"]
    game = _w1g1_duel(set_pool, ["Verdeloth the Ancient"], pool={"G": 12})
    assert "announces_x" not in game.cast_target_spec(0, card)
    taken = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert taken["announces_x"] is True
    assert taken["max_x"] == 6

    refused = game.cast_from_hand(
        0, "Verdeloth the Ancient", optional_cost_payments={"{X}": 1}, x_value=7
    )
    assert not refused.supported
    assert _w1g1_floating(game) == 12


def test_w1g1_kangee_kicked_for_x_gets_x_feathers_and_lifts_other_birds(set_pool):
    """Kicker {X}{2}: {2}{W}{U} + {2} + X. The feather counters size the anthem
    ("for each feather counter on Kangee" — the card naming itself), and Kangee
    is a Bird that is not an *other* Bird."""
    game = _w1g1_duel(set_pool, ["Kangee, Aerie Keeper"])
    bird = _w1g1_put(game, 0, set_pool("LEA")["Birds of Paradise"])
    theirs = _w1g1_put(game, 1, set_pool("LEA")["Birds of Paradise"])
    before = _w1g1_floating(game)
    kangee = _w1g1_cast(game, "Kangee, Aerie Keeper", kick="{X}{2}", x_value=2)

    assert before - _w1g1_floating(game) == 4 + 2 + 2
    assert _w1g1_counters_on(kangee, "feather") == 2
    assert (bird.effective_power, bird.effective_toughness) == (2, 3)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 3)
    assert (kangee.effective_power, kangee.effective_toughness) == (2, 2)


def test_w1g1_kangee_unkicked_has_no_feathers(set_pool):
    game = _w1g1_duel(set_pool, ["Kangee, Aerie Keeper"])
    bird = _w1g1_put(game, 0, set_pool("LEA")["Birds of Paradise"])
    kangee = _w1g1_cast(game, "Kangee, Aerie Keeper")
    assert _w1g1_counters_on(kangee, "feather") == 0
    assert (bird.effective_power, bird.effective_toughness) == (0, 1)


def test_w1g1_kavu_aggressor_cannot_block_kicked_or_not(set_pool):
    """The printed restriction is no part of the kicker and survives it."""
    game = _w1g1_duel(set_pool, ["Kavu Aggressor"])
    kavu = _w1g1_cast(game, "Kavu Aggressor", kick="{4}")
    kinds = {i.kind for i in _w1g1_compile(kavu.effective_card).instructions}
    assert "cant_block" in kinds
    attacker = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    assert not game._can_block_attacker(kavu, attacker)


def test_w1g1_the_ai_kicks_when_its_lands_can_pay(set_pool):
    """The stated policy: kick whenever the lands can pay for it on top of the
    spell. Two Forests cast the 2/2; five cast the 5/5 trampler and tap all
    five. An X kicker takes the most the lands allow."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g1_duel(set_pool, ["Kavu Titan"], pool={})
    for _ in range(2):
        _w1g1_put(game, 0, forest)
    plain = _w1g1_choose_cast_action(game, 0)
    assert (plain.card_name, plain.optional_cost_payments) == ("Kavu Titan", None)

    for _ in range(3):
        _w1g1_put(game, 0, forest)
    kicked = _w1g1_choose_cast_action(game, 0)
    assert kicked.optional_cost_payments == {"{2}{G}": 1}
    assert len(kicked.land_tap_indices) == 5

    elder = _w1g1_duel(set_pool, ["Verdeloth the Ancient"], pool={})
    for _ in range(9):
        _w1g1_put(elder, 0, forest)
    sized = _w1g1_choose_cast_action(elder, 0)
    assert (sized.optional_cost_payments, sized.x_value) == ({"{X}": 1}, 3)


def test_w1g1_the_ai_does_not_kick_for_a_half_with_nothing_to_hit(set_pool):
    """Tolarian Emissary's kicker destroys an enchantment. With none anywhere
    the AI casts the flier unkicked; with one on the other side it kicks and
    names it."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Tolarian Emissary"], pool={})
    for name in ("Island", "Island", "Island", "Plains", "Plains"):
        _w1g1_put(game, 0, lea[name])
    plain = _w1g1_choose_cast_action(game, 0)
    assert (plain.card_name, plain.optional_cost_payments) == (
        "Tolarian Emissary", None,
    )

    aura = _w1g1_put(game, 1, set_pool("INV")["Saproling Infestation"])
    kicked = _w1g1_choose_cast_action(game, 0)
    assert kicked.optional_cost_payments == {"{1}{W}": 1}
    assert kicked.target_permanent_ids == [aura.permanent_id]


def test_w1g1_a_copy_of_a_kicked_creature_was_not_kicked(set_pool):
    """Whether a permanent was kicked is a fact about the spell that became it,
    not a copiable value (CR 707.2): a Clone of a kicked Kavu Titan is a 2/2
    with no trample and no counters, beside the 5/5 it copied."""
    game = _w1g1_duel(set_pool, ["Kavu Titan"])
    game.players[0].hand.append(set_pool("LEA")["Clone"])
    titan = _w1g1_cast(game, "Kavu Titan", kick="{2}{G}")
    result = game.cast_from_hand(
        0, "Clone", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[titan.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    clone = next(p for p in game.controlled_by(0) if p is not titan)

    assert clone.effective_card.name == "Kavu Titan"
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)
    assert not game._has_keyword(clone, "trample")
    assert (titan.effective_power, titan.effective_toughness) == (5, 5)
# end of the W1G1 creatures block
