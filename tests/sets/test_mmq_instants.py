"""Mercadian Masques instants.

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
# CR 118.9's *first* printed spelling -- "You may <action> rather than pay this
# spell's mana cost" -- in the four shapes Mercadian Masques prints it: a
# permanent returned, a creature tapped, life paid, and an **opponent's** life
# gained. Five of these eight cards compiled ``supported`` before this round and
# were castable at full price with the printed alternative ignored -- a debt only
# ``scripts/parse_coverage.py`` could see, because a card is supported when *any*
# of its lines is. So what is asserted here is the board, the life totals and the
# mana pool, never that a sentence parsed.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_table(set_pool, hand, mine=(), theirs=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: every card in this block is about
    not paying a mana cost, and a game that charges none cannot tell a free cast
    from an ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    for name in theirs:
        other.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_alt(game, seat, card, hand_index=0):
    """The alternative-cost offers the picker would show, with payability."""
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(
            seat, card, spell_hand_index=hand_index
        )
        if offer["kind"] == "alternative"
    ]


_G1_ISLAND_SPELLS = [("Gush", 2), ("Thwart", 3), ("Tidal Bore", 1)]


@pytest.mark.parametrize("name,count", _G1_ISLAND_SPELLS)
def test_g1_islands_return_pays_for_the_spell(set_pool, name, count):
    """CR 118.9: "return N Islands you control to their owner's hand".

    The identical clause Infernal Harvest prints as an *additional* cost one
    rule over, so it is read by the same function and enumerated by the same
    candidate scan. The board is what is asserted: exactly N Islands leave, the
    spare land stays, and nothing is spent from the pool.
    """
    pool = set_pool("MMQ")
    card = pool[name]
    # The spare permanent is what proves the payment stopped at the printed
    # count; Tidal Bore needs it to be the creature it taps.
    spare = "Fresh Volunteers" if name == "Tidal Bore" else "Forest"
    game, caster, other = _g1_table(
        set_pool, [name], mine=("Island",) * count + (spare,),
    )
    if name == "Thwart":
        # A spell to counter, **queued** rather than cast: ``cast_from_hand``
        # resolves the stack it just filled, so the card would be gone before
        # Thwart could name it (CR 601.2c) and every assertion below would be
        # green for a reason that has nothing to do with the cost.
        other.hand = [pool["Brainstorm"]]
        other.library = [pool["Island"]] * 5
        other.mana_pool["U"] = 1
        game.queue_from_hand(1, "Brainstorm")
        assert [item.card.name for item in game.stack] == ["Brainstorm"]

    assert _g1_alt(game, 0, card)[0][1] is True

    result = game.cast_from_hand(
        0, name, alternative_cost=True,
        # Thwart names the spell on the stack; Tidal Bore names a creature on
        # the caster's own board.
        target_player_index=1 if name == "Thwart" else 0,
        **({"target_permanent_index": count} if name == "Tidal Bore" else {}),
    )

    assert result.supported, result.details
    assert "returned Island to hand" in "\n".join(game.log)
    assert [perm.card.name for perm in caster.battlefield] == [spare]
    assert [held.name for held in caster.hand].count("Island") == count
    # CR 118.9c: the printed mana cost is untouched; only the payment is.
    assert not any(caster.mana_pool.values())
    assert card.mana_cost


@pytest.mark.parametrize("name,count", _G1_ISLAND_SPELLS)
def test_g1_islands_return_needs_the_printed_count(set_pool, name, count):
    """CR 601.2h / CR 118.3: a cost is paid in full or not at all.

    One Island short is no payment. A gate that asked only whether an Island
    existed would admit the announcement and then charge what was there -- which
    for an alternative cost is a spell cast for nothing, the mana payment having
    already been skipped.
    """
    pool = set_pool("MMQ")
    card = pool[name]
    game, caster, other = _g1_table(
        set_pool, [name],
        mine=("Island",) * (count - 1) + ("Fresh Volunteers",),
    )
    if name == "Thwart":
        # A spell to counter, **queued** rather than cast: ``cast_from_hand``
        # resolves the stack it just filled, so the card would be gone before
        # Thwart could name it (CR 601.2c) and every assertion below would be
        # green for a reason that has nothing to do with the cost.
        other.hand = [pool["Brainstorm"]]
        other.library = [pool["Island"]] * 5
        other.mana_pool["U"] = 1
        game.queue_from_hand(1, "Brainstorm")
        assert [item.card.name for item in game.stack] == ["Brainstorm"]

    offered = _g1_alt(game, 0, card)
    assert len(offered) == 1 and offered[0][1] is False

    result = game.cast_from_hand(
        0, name, alternative_cost=True,
        target_player_index=1 if name == "Thwart" else 0,
        **({"target_permanent_index": count - 1} if name == "Tidal Bore" else {}),
    )

    assert not result.supported
    assert "CR 601.2h" in result.details
    # Nothing was paid at all: CR 601.2e rewinds the whole casting.
    assert len(caster.battlefield) == count
    assert [held.name for held in caster.hand] == [name]


def test_g1_islands_return_will_not_eat_a_forest(set_pool):
    """The printed subtype is charged, not "two lands".

    The refusal also has to *say* Island: ``filter_head_noun`` answers
    "permanent" for a subtype-only phrase, so a message built from it would tell
    a player they are short of permanents while two lands sit on the table.
    """
    card = set_pool("MMQ")["Gush"]
    game, caster, _ = _g1_table(set_pool, ["Gush"], mine=("Forest", "Forest"))

    assert _g1_alt(game, 0, card) == [
        ("return 2 Islands you control to their owner's hand", False)
    ]

    result = game.cast_from_hand(0, "Gush", alternative_cost=True)

    assert not result.supported
    assert "Islands" in result.details
    assert len(caster.battlefield) == 2


def test_g1_gush_draws_after_the_islands_leave(set_pool):
    """The whole card, end to end: two Islands out, two cards in."""
    pool = set_pool("MMQ")
    game, caster, _ = _g1_table(set_pool, ["Gush"], mine=("Island", "Island"))
    caster.library = [pool["Forest"], pool["Island"], pool["Plains"]]

    result = game.cast_from_hand(0, "Gush", alternative_cost=True)
    resolve_stack(game)

    assert result.supported, result.details
    assert caster.battlefield == []
    # The two Islands back in hand, plus the two drawn.
    assert len(caster.hand) == 4
    assert len(caster.library) == 1


_G1_LIFE_SPELLS = [("Rouse", 2), ("Snuff Out", 4)]


@pytest.mark.parametrize("name,life", _G1_LIFE_SPELLS)
def test_g1_life_alternative_is_gated_on_the_printed_swamp(set_pool, name, life):
    """CR 601.2b: "If you control a Swamp" is checked as the spell is cast.

    Both cards read ``supported`` on their *other* line before this round, so
    the sentence naming the price was claimed by nothing and the price was never
    charged. A condition dropped along with it would be the opposite defect and
    just as silent: the discount available on every board.
    """
    card = set_pool("MMQ")[name]

    game, _, _ = _g1_table(set_pool, [name], mine=("Forest",))
    assert _g1_alt(game, 0, card) == []

    game, _, _ = _g1_table(set_pool, [name], mine=("Swamp",))
    assert _g1_alt(game, 0, card) == [("pay %d life" % life, True)]


@pytest.mark.parametrize("name,life", _G1_LIFE_SPELLS)
def test_g1_life_alternative_is_refused_below_the_price(set_pool, name, life):
    """CR 119.4: a player may pay life only down to 0.

    CR 601.2h then makes the unpayable cost an uncastable spell rather than a
    free one -- so the offer is shown and marked unpayable, and the cast is
    refused with the life total untouched.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_table(set_pool, [name], mine=("Swamp",))
    caster.life = life - 1

    assert _g1_alt(game, 0, card) == [("pay %d life" % life, False)]

    result = game.cast_from_hand(0, name, alternative_cost=True)

    assert not result.supported
    assert caster.life == life - 1
    assert [held.name for held in caster.hand] == [name]


def test_g1_snuff_out_destroys_for_four_life_and_no_mana(set_pool):
    """The whole card: 4 life paid, the creature destroyed, the pool untouched."""
    game, caster, other = _g1_table(
        set_pool, ["Snuff Out"], mine=("Swamp",), theirs=("Wild Jhovall",),
    )

    result = game.cast_from_hand(
        0, "Snuff Out", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert caster.life == 16
    assert other.battlefield == []
    assert not any(caster.mana_pool.values())
    assert not caster.battlefield[0].tapped


_G1_TAP_SPELLS = ["Orim's Cure", "Ramosian Rally"]


@pytest.mark.parametrize("name", _G1_TAP_SPELLS)
def test_g1_tap_alternative_needs_a_plains_and_an_untapped_creature(set_pool, name):
    """Two different reasons the offer is not takeable, and they are not one.

    No Plains means there is **no offer** (CR 601.2b's condition); an untappable
    board means the offer exists and cannot be paid (CR 601.2h). Folded
    together, a player is shown a price they are not being offered -- or hidden
    one they are.
    """
    card = set_pool("MMQ")[name]
    label = "tap an untapped creature you control"

    game, _, _ = _g1_table(set_pool, [name], mine=("Mountain", "Fresh Volunteers"))
    assert _g1_alt(game, 0, card) == []

    game, _, _ = _g1_table(set_pool, [name], mine=("Plains",))
    assert _g1_alt(game, 0, card) == [(label, False)]

    game, caster, _ = _g1_table(set_pool, [name], mine=("Plains", "Fresh Volunteers"))
    caster.battlefield[1].tapped = True
    assert _g1_alt(game, 0, card) == [(label, False)]

    caster.battlefield[1].tapped = False
    assert _g1_alt(game, 0, card) == [(label, True)]


@pytest.mark.parametrize("name", _G1_TAP_SPELLS)
def test_g1_tap_alternative_taps_the_creature_not_the_land(set_pool, name):
    """The payment is the printed noun phrase, and the Plains is not it.

    "If you control a Plains" is the *condition*; "tap an untapped creature you
    control" is the *price*. A reader that let the condition's land pay would
    make both cards strictly cheaper than printed on exactly the board they are
    designed for.
    """
    game, caster, _ = _g1_table(
        set_pool, [name], mine=("Plains", "Fresh Volunteers"),
    )

    result = game.cast_from_hand(
        0, name, alternative_cost=True,
        **({"target_player_index": 0} if name == "Orim's Cure" else {}),
    )

    assert result.supported, result.details
    assert [(perm.card.name, perm.tapped) for perm in caster.battlefield] == [
        ("Plains", False), ("Fresh Volunteers", True),
    ]
    assert not any(caster.mana_pool.values())


def test_g1_invigorate_gives_the_life_to_the_opponent(set_pool):
    """CR 118.9's one price in this pool that lands on somebody else.

    Not ``pay_life`` with a sign: CR 119.4 caps what a player may **pay** at
    their own life total and caps nothing about what another may gain, so the
    CR 601.2h gate must not ask the payer's question here. A caster at 1 life
    can still cast Invigorate.
    """
    card = set_pool("MMQ")["Invigorate"]
    game, caster, other = _g1_table(
        set_pool, ["Invigorate"], mine=("Forest", "Fresh Volunteers"),
    )
    caster.life = 1

    assert _g1_alt(game, 0, card) == [("have an opponent gain 3 life", True)]

    result = game.cast_from_hand(
        0, "Invigorate", alternative_cost=True,
        target_player_index=0, target_permanent_index=1,
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert caster.life == 1
    assert other.life == 23
    assert not any(caster.mana_pool.values())


def test_g1_invigorate_needs_the_printed_forest(set_pool):
    """CR 601.2b again: no Forest, no offer -- and the mana cost stands."""
    card = set_pool("MMQ")["Invigorate"]
    game, _, other = _g1_table(
        set_pool, ["Invigorate"], mine=("Island", "Fresh Volunteers"),
    )

    assert _g1_alt(game, 0, card) == []

    result = game.cast_from_hand(0, "Invigorate", alternative_cost=True)

    assert not result.supported
    assert "CR 118.9" in result.details
    assert other.life == 20


def test_g1_invigorate_is_uncastable_when_no_opponent_may_gain_life(set_pool):
    """CR 119.7's last sentence: "a cost that involves having that player gain
    life can't be paid".

    The gate has to know it. Without it the announcement is admitted, the
    payment's ``_gain_life`` logs the prohibition and changes nothing, and the
    spell is cast for **nothing** -- the mana payment having already been
    skipped. That is the exact shape this whole gate exists to prevent, arriving
    through a rule about life rather than a rule about costs.
    """
    pool = set_pool("MMQ")
    game, caster, other = _g1_table(
        set_pool, ["Invigorate"], mine=("Forest", "Fresh Volunteers"),
    )
    # Forsaken Wastes: "Players can't gain life." A board-wide prohibition, so
    # it is put on the *opponent's* side to prove the scan is not one-sided.
    from engine.card_loader import load_cards, manifest_set_path

    wastes = next(
        card for card in load_cards(manifest_set_path("MIR"))
        if card.name == "Forsaken Wastes"
    )
    other.battlefield.append(Permanent(card=wastes))
    game._sync_control()

    assert _g1_alt(game, 0, pool["Invigorate"]) == [
        ("have an opponent gain 3 life", False)
    ]

    result = game.cast_from_hand(
        0, "Invigorate", alternative_cost=True,
        target_player_index=0, target_permanent_index=1,
    )

    assert not result.supported
    assert "CR 119.7" in result.details
    assert other.life == 20
    assert [held.name for held in caster.hand] == ["Invigorate"]


def test_g1_every_mmq_offer_label_names_its_price(set_cards):
    """A prompt label built from ``filter_head_noun`` says "permanent".

    Which was true of every subtype-narrowed offer in the pool: Crash and
    Thunderclap print "sacrifice a Mountain" and the client showed "sacrifice a
    permanent", so a player about to click it could not tell what was going to
    leave. (Fireblast, in the **shipped** pool, read "sacrifice 2 permanents"
    the same way.) Every noun phrase these costs print is a land subtype, and
    the head noun answers "permanent" for all of them.

    Swept over the set rather than asserted per card, because the defect is a
    property of the describer and the next card to print the clause inherits it.
    A label is not a gate -- nothing about payability changes either way -- and
    that is exactly why no other instrument in this repo would have caught it:
    the cost was charged correctly the whole time and simply could not be read.
    """
    from engine.alternative_costs import alternative_costs

    vague = sorted(
        (card.name, cost.describe())
        for card in set_cards("MMQ")
        for cost in alternative_costs(card)
        # "permanent" is honest for a phrase that really names permanents; it is
        # only wrong where the payload carries a subtype the label dropped.
        if "permanent" in cost.describe()
        and (
            (cost.sacrifice_filter or {}).get("subtype_filter")
            or (cost.return_filter or {}).get("subtype_filter")
            or (cost.tap_filter or {}).get("subtype_filter")
        )
    )

    assert vague == []
    # Spelled out so a regression names the card rather than a count.
    pool = {card.name: card for card in set_cards("MMQ")}
    assert alternative_costs(pool["Crash"])[0].describe() == "sacrifice a Mountain"
    assert alternative_costs(pool["Pulverize"])[0].describe() == (
        "sacrifice 2 Mountains"
    )
    assert alternative_costs(pool["Tidal Bore"])[0].describe() == (
        "return an Island you control to its owner's hand"
    )


def test_g1_a_legate_condition_reads_back_with_the_right_article(set_pool):
    """The condition label is what a player is shown, so it has to be English.

    Four of the five Legates name Island, and a bare "a" made two of them read
    "an opponent controls a Island". Trivial, and the reason it is asserted is
    that the labels are the only part of this round a player ever sees.
    """
    from engine.alternative_costs import alternative_costs

    pool = set_pool("MMQ")
    assert alternative_costs(pool["Saprazzan Legate"])[0].condition.describe() == (
        "an opponent controls a Mountain and you control an Island"
    )
    assert alternative_costs(pool["Rushwood Legate"])[0].condition.describe() == (
        "an opponent controls an Island and you control a Forest"
    )
    assert alternative_costs(pool["Land Grant"])[0].condition.describe() == (
        "you have no land cards in hand"
    )


# --- W2G2: libraries and graveyards ---
# Honor the Fallen: the graveyard sweep that reads **all** graveyards, and the
# life it pays for what it took.
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from tests.helpers import resolve_stack

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_sweep_table():
    """A two-seat game, both graveyards empty, mana enforcement off."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]
    # end of _w2g2_sweep_table


def test_w2g2_honor_the_fallen_empties_every_graveyard_and_pays_per_card(set_pool):
    """"Exile all creature cards from **all graveyards**. You gain 1 life for
    each card exiled this way."

    Two gaps in one card. The sweep read "your graveyard" and "each player ...
    their graveyard" and refused the plural pile, though the *return* sweep one
    family over (Planar Birth) had read exactly those words since it was written
    -- a second copy of one fact, now one predicate on the shared floor. And the
    sweep recorded only a per-seat map, so "for each card exiled this way" had
    no producer to read.

    The life is what pins both: three creature cards across two graveyards is
    three life, and the non-creature cards stay where they are.
    """
    pool = set_pool("MMQ")
    game, caster, other = _w2g2_sweep_table()
    caster.graveyard.extend(
        [_W2G2_LEA["Grizzly Bears"], _W2G2_LEA["Lightning Bolt"]]
    )
    other.graveyard.extend([
        _W2G2_LEA["Black Knight"],
        _W2G2_LEA["Llanowar Elves"],
        _W2G2_LEA["Mox Jet"],
    ])
    caster.life = 20
    caster.hand.append(pool["Honor the Fallen"])

    result = game.cast_from_hand(0, "Honor the Fallen")
    resolve_stack(game)

    assert result.supported, result.details
    assert sorted(c.name for c in caster.exile) == ["Grizzly Bears"]
    assert sorted(c.name for c in other.exile) == [
        "Black Knight", "Llanowar Elves",
    ]
    assert [c.name for c in other.graveyard] == ["Mox Jet"]
    assert caster.life == 23
    # end of test_w2g2_honor_the_fallen_empties_every_graveyard_and_pays_per_card


def test_w2g2_honor_the_fallen_gains_nothing_over_empty_graveyards(set_pool):
    """A sweep that took nothing pays nothing.

    The record is seeded before anything moves for exactly this: an *absent*
    scratchpad key is a back-reference with no producer, which is a refusal
    rather than a zero -- so the life clause would have read whatever a ``.get``
    default happened to be.
    """
    pool = set_pool("MMQ")
    game, caster, other = _w2g2_sweep_table()
    other.graveyard.append(_W2G2_LEA["Mox Jet"])
    caster.life = 20
    caster.hand.append(pool["Honor the Fallen"])

    result = game.cast_from_hand(0, "Honor the Fallen")
    resolve_stack(game)

    assert result.supported, result.details
    assert caster.life == 20
    assert [c.name for c in other.graveyard] == ["Mox Jet"]
    # end of test_w2g2_honor_the_fallen_gains_nothing_over_empty_graveyards


# --- W2G4: combat-window instants and a counted sacrifice ---
from engine import Game as _I4Game
from engine import PlayerState as _I4PlayerState
from engine.models import Permanent as _I4Permanent
from tests.helpers import _mk_creature_card as _i4_creature_card
from tests.helpers import resolve_stack as _i4_resolve


def _w2g4_duel(set_pool, hand, mine=(), theirs=()):
    """A duel with *hand* on seat 0 and named permanents on both battlefields.

    Its own helper rather than the sorcery block's, for the file convention's
    reason: a block is self-contained so a mechanical union cannot splice one
    group's helper body onto another's signature.
    """
    pool = set_pool("MMQ")
    caster, other = _I4PlayerState("Caster"), _I4PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = _I4Game(players=[caster, other])
    game.enforce_mana_costs = False
    for perm in mine:
        caster.battlefield.append(
            _I4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    for perm in theirs:
        other.battlefield.append(
            _I4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    game._settle()
    return game, caster, other


def test_w2g4_downfall_scales_off_the_defenders_nonbasic_lands(set_pool):
    """"Each attacking creature gets +1/+0 until end of turn for each nonbasic
    land defending player controls." (Mercadia’s Downfall.)

    Three narrowings, and each has a permanent here that it must exclude:
    *nonbasic* (the defender’s Plains does not count), *defending player’s*
    (the caster’s own nonbasic land does not either), and *attacking* (the
    defender’s creature gets nothing). CR 506.2’s seat is read off the live
    combat, because a spell froze no event to read it from.
    """
    game, _caster, _other = _w2g4_duel(
        set_pool, ["Mercadia's Downfall"],
        mine=[_i4_creature_card("Raider", 2, 2), "Rushwood Grove"],
        theirs=[_i4_creature_card("Guard", 2, 2), "Plains", "Saprazzan Skerry",
                "Henge of Ramos"],
    )
    raider = next(p for p in game.controlled_by(0) if p.card.name == "Raider")
    guard = next(p for p in game.controlled_by(1) if p.card.name == "Guard")
    raider.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    _i4_resolve(game)

    result = game.cast_from_hand(0, "Mercadia's Downfall")
    _i4_resolve(game)

    assert result.supported, result.details
    # Two nonbasic lands on the defender’s side, so +2/+0 — never +3 (both
    # boards’ nonbasics) and never +3 either way round from counting the Plains.
    assert (raider.effective_power, raider.effective_toughness) == (4, 2)
    assert (guard.effective_power, guard.effective_toughness) == (2, 2)


def test_w2g4_downfall_outside_combat_pumps_nobody(set_pool):
    """CR 506.2’s seat exists only inside a combat phase.

    With no combat there is no defending player, so the count is zero — and
    nothing is attacking either. The spell resolves having done nothing rather
    than counting somebody’s lands because a seat had to be guessed, which is
    what a count with no seat does: it guesses the caster.
    """
    game, _caster, _other = _w2g4_duel(
        set_pool, ["Mercadia's Downfall"],
        mine=[_i4_creature_card("Raider", 2, 2), "Rushwood Grove"],
        theirs=["Saprazzan Skerry", "Henge of Ramos"],
    )
    raider = next(p for p in game.controlled_by(0) if p.card.name == "Raider")

    game.cast_from_hand(0, "Mercadia's Downfall")
    _i4_resolve(game)

    assert (raider.effective_power, raider.effective_toughness) == (2, 2)


def test_w2g4_moment_of_silence_skips_the_named_players_combat_phase(set_pool):
    """"Target player skips their next combat phase this turn."
    (Moment of Silence.)

    CR 500.11 and CR 506.1: a *phase*, not a step — the combat phase has five
    steps and none of them is called "combat", so a skip filed in the step
    bucket would be a record nothing ever consumes. The assertion is that the
    turn now runs from the precombat main phase straight to the postcombat one.
    """
    game, _caster, _other = _w2g4_duel(set_pool, ["Moment of Silence"])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")

    result = game.cast_from_hand(0, "Moment of Silence", target_player_index=0)
    _i4_resolve(game)

    assert result.supported, result.details
    assert game.next_unskipped_phase_after("precombat_main") == "postcombat_main"


def test_w2g4_moment_of_silence_leaves_the_other_seats_combat_alone(set_pool):
    """The skip is the *named* seat’s, so the other player’s combat phase runs.

    Keyed on the seat rather than on the phase name alone, which is the whole of
    what this asserts: an unseated record is spent by whichever combat phase
    comes round first, and on the opponent’s turn that is the wrong player’s.
    """
    game, _caster, _other = _w2g4_duel(set_pool, ["Moment of Silence"])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.cast_from_hand(0, "Moment of Silence", target_player_index=1)
    _i4_resolve(game)

    assert game.next_unskipped_phase_after("precombat_main") == "combat"


def test_w2g4_moment_of_silence_expires_with_the_turn(set_pool):
    """"…**this turn**." CR 514.2 closes the window at cleanup.

    Without the stamp the record would wait for the target’s own next turn and
    eat a combat phase the card never named — the direction a missing duration
    always errs in, and one a compiled program cannot show.
    """
    game, _caster, _other = _w2g4_duel(set_pool, ["Moment of Silence"])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.cast_from_hand(0, "Moment of Silence", target_player_index=0)
    _i4_resolve(game)
    assert game.skip_phase_counts

    game.resolve_cleanup_step(0)
    game.turn += 1

    assert not game.skip_phase_counts
    assert game.next_unskipped_phase_after("precombat_main") == "combat"


def test_w2g4_renounce_gains_two_life_per_permanent_sacrificed(set_pool):
    """"Sacrifice any number of permanents. You gain 2 life for each permanent
    sacrificed this way." (Renounce.)

    The number is what the first sentence actually took: "any number" prints no
    count, and by the time the gain runs the permanents are cards in a graveyard
    (CR 400.7) among everything else that ever arrived there. So the count comes
    off the resolution’s own record, and the printed 2 is the *rate* over it.

    The seat is **interactive**, which is what makes this a test of the record
    rather than of a default: "any number" lets a non-interactive seat answer
    none, and a gain that read the printed 2 instead of the count would pass a
    zero-sacrifice board by gaining nothing either. Two of three permanents, so
    the answer is neither the board nor one.
    """
    game, caster, _other = _w2g4_duel(
        set_pool, ["Renounce"],
        mine=["Mountain", "Mountain", _i4_creature_card("Bear", 2, 2)],
    )
    caster.life = 20
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Renounce")
    assert game.pending_sacrifice is not None
    assert game.confirm_sacrifice(0, [0, 2]) is True
    _i4_resolve(game)

    assert result.supported, result.details
    assert len(list(game.controlled_by(0))) == 1
    assert caster.life == 24


def test_w2g4_renounce_sacrificing_one_gains_exactly_two(set_pool):
    """The rate is per permanent, so one sacrifice is 2 life and not 4.

    Beside the test above rather than folded into it: together they pin the
    count as the multiplier. A gain that read the printed 2 as the whole amount
    passes the pair’s first half and fails here.
    """
    game, caster, _other = _w2g4_duel(
        set_pool, ["Renounce"], mine=["Mountain", "Mountain"],
    )
    caster.life = 20
    game.interactive_seats = {0}

    game.cast_from_hand(0, "Renounce")
    assert game.confirm_sacrifice(0, [1]) is True
    _i4_resolve(game)

    assert caster.life == 22


def test_w2g4_renounce_with_an_empty_board_gains_nothing(set_pool):
    """"Any number" includes none, and none is a legal answer.

    Zero is what the record holds and zero is what the rate multiplies — not
    the printed 2, which is what a gain reading the number instead of the count
    would pay out for sacrificing nothing at all.
    """
    game, caster, _other = _w2g4_duel(set_pool, ["Renounce"])
    caster.life = 20

    game.cast_from_hand(0, "Renounce")
    _i4_resolve(game)

    assert caster.life == 20


# --- W3G3: a chosen card type, and a count off the revealed hand ---
# Blood Oath: "Choose a card type. Target opponent reveals their hand. Blood Oath
# deals 3 damage to that player for each card of the chosen type revealed this
# way." Three sentences and one number, and the number is the whole card: a
# filtered count over the *cards* an earlier step of the same resolution
# recorded, times the printed rate. What is asserted below is the life total,
# never that a sentence parsed -- a count that dropped "of the chosen type"
# would still compile, still claim every sentence and still report no hollow
# line, and it would deal for the whole hand.
import pytest as _w3g3_pytest

from engine import Game as _W3G3Game
from engine import PlayerState as _W3G3PlayerState
from engine.models import Permanent as _W3G3Permanent
from tests.helpers import resolve_stack as _w3g3_resolve


def _w3g3_table(set_pool, hand, theirs=(), interactive=()):
    """A duel with Blood Oath in hand and *hand* in the opponent's, returning
    the game and both seats."""
    pool = set_pool("MMQ")
    caster, other = _W3G3PlayerState("Caster"), _W3G3PlayerState("Opponent")
    game = _W3G3Game(players=[caster, other])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    caster.hand = [pool["Blood Oath"]]
    other.hand = [pool[name] for name in hand]
    for name in theirs:
        other.battlefield.append(_W3G3Permanent(card=pool[name]))
    return game, caster, other


@_w3g3_pytest.mark.parametrize(
    "chosen, expected",
    [
        # Two creature cards in a four-card hand: 3 damage each.
        ("creature", 6),
        # One instant.
        ("instant", 3),
        # One land -- and the land is a *card* in a hand, so the count reads the
        # printed type line rather than anything a battlefield could answer.
        ("land", 3),
        # A type the hand does not hold at all. Zero damage is the card working,
        # not the card failing, and it is the reading that separates the filter
        # from a bare count of the hand.
        ("artifact", 0),
    ],
)
def test_w3g3_blood_oath_counts_only_the_chosen_type(set_pool, chosen, expected):
    """CR 608.2d: the type is chosen as the spell resolves, and the sentence
    after it spends the choice.

    The hand is fixed and only the chosen word moves, so what the assertion
    measures is the *filter*: the same four revealed cards pay out four
    different numbers.
    """
    game, _caster, other = _w3g3_table(
        set_pool,
        ["Alabaster Wall", "Charm Peddler", "Disenchant", "Plains"],
        interactive=(0,),
    )
    other.life = 20

    game.cast_from_hand(0, "Blood Oath", target_player_index=1)
    assert game.confirm_card_type_choice(0, chosen) is True
    _w3g3_resolve(game)

    assert other.life == 20 - expected
    assert [card.name for card in other.hand] == [
        "Alabaster Wall", "Charm Peddler", "Disenchant", "Plains"
    ], "revealing a hand moves nothing (CR 701.20a)"


def test_w3g3_blood_oath_offers_every_card_type(set_pool):
    """"Choose a card type" with no printed list is CR 205.2a's whole catalog.

    The offer is asserted rather than the compiled payload, because the offer is
    what a player answers: a prompt bounded by some shorter list would refuse a
    word the card allows, and one bounded by nothing would accept a word that is
    not a card type at all.
    """
    from engine.grammar.vocabulary import CARD_TYPES

    game, _caster, _other = _w3g3_table(set_pool, ["Mountain"], interactive=(0,))

    game.cast_from_hand(0, "Blood Oath", target_player_index=1)
    owed = next(c for c in game.pending_choices if c.kind == "card_type_choice")

    assert set(owed.data["options"]) == set(CARD_TYPES)
    assert game.confirm_card_type_choice(0, "wizard") is False, (
        "a creature type is not a card type"
    )


def test_w3g3_blood_oath_deals_nothing_to_an_empty_hand(set_pool):
    """An opponent holding nothing takes nothing.

    The reveal still records -- an absent record is a back-reference with no
    producer, which is a different thing from a reveal that showed nothing --
    so the damage step reads an empty list and deals zero rather than the
    printed 3.
    """
    game, _caster, other = _w3g3_table(set_pool, [], interactive=(0,))
    other.life = 20

    game.cast_from_hand(0, "Blood Oath", target_player_index=1)
    assert game.confirm_card_type_choice(0, "creature") is True
    _w3g3_resolve(game)

    assert other.life == 20


def test_w3g3_blood_oath_damages_the_player_who_revealed(set_pool):
    """"…to **that player**" is the seat the reveal named, not the caster.

    A recipient key dropped on this branch would leave the damage aimed at
    whatever the resolution was last carrying, which on a spell that targets a
    player is the quiet failure: the number is right and the face is wrong.
    """
    game, caster, other = _w3g3_table(
        set_pool, ["Alabaster Wall", "Charm Peddler"], interactive=(0,),
    )
    caster.life, other.life = 20, 20

    game.cast_from_hand(0, "Blood Oath", target_player_index=1)
    assert game.confirm_card_type_choice(0, "creature") is True
    _w3g3_resolve(game)

    assert (caster.life, other.life) == (20, 14)
