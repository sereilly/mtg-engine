"""Urza's Saga artifacts.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: Chimeric Staff — an X/X body with a duration ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g3a_staff(set_pool):
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    staff = Permanent(card=set_pool("USG")["Chimeric Staff"])
    game._put_permanent_onto_battlefield(0, staff, None)
    staff.metadata["summoning_sickness_turn"] = -99
    return game, staff


def test_chimeric_staff_is_the_size_the_activation_paid_for(set_pool):
    """"{X}: This artifact becomes an X/X Construct artifact creature until end
    of turn."

    The only card in the group whose body prints a *variable* size, and the
    only one with a duration. Two activations at different X are asserted
    rather than one, because a body that resolved X to zero or to a constant
    would look right at whichever number the test happened to pick.
    """
    game, staff = _g3a_staff(set_pool)
    assert not staff.is_creature

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=4)
    resolve_stack(game)

    assert staff.is_creature
    assert staff.has_type("artifact"), "CR 205.1b: it is still an artifact"
    assert staff.has_type("construct")
    assert (staff.effective_power, staff.effective_toughness) == (4, 4)

    game.activate_permanent_ability(0, "Chimeric Staff", x_value=1)
    resolve_stack(game)
    assert (staff.effective_power, staff.effective_toughness) == (1, 1)


def test_chimeric_staff_stops_being_a_creature_at_cleanup(set_pool):
    """The duration, which every other card in this group lacks.

    "Until end of turn" is the difference between the Staff and the Veiled
    cycle, and it is the half a record written on the wrong key would lose:
    the animation would last for ever and the artifact would keep attacking
    on turns its controller never paid for.
    """
    game, staff = _g3a_staff(set_pool)
    game.activate_permanent_ability(0, "Chimeric Staff", x_value=3)
    resolve_stack(game)
    assert staff.is_creature

    game.resolve_cleanup_step(0)

    assert not staff.is_creature
    assert staff.has_type("artifact")

# --- W1G5: the two artifacts that reported supported and did nothing ---
from engine import Game, PlayerState
from engine.enter_effects import LIFE_PAID_AS_ENTERED
from engine.models import Permanent
from engine.named_counters import add_counters
from tests.helpers import _mk_creature_card, resolve_stack


def _g5a_game(*, interactive=()):
    """Two seats, no mana enforcement, and which of them answers prompts.

    Prefixed and ending on ``return game, p1, p2`` for the reason SET_PLAYBOOK.md
    gives: a helper whose last lines match another group's is spliced by a
    mechanical union onto the wrong signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _g5a_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def test_w1g5_phyrexian_processor_makes_a_token_the_size_of_the_life_it_ate(set_pool):
    """{4}, {T}: Create an X/X black Phyrexian Minion creature token, where X is
    the life paid as this artifact entered.

    Not a count of anything and not a recompute: the number was chosen once as
    a CR 614.1c entry replacement, and every activation afterwards reads the
    same one.
    """
    game, p1, _p2 = _g5a_game(interactive=(0,))
    processor = _g5a_put(game, 0, set_pool("USG")["Phyrexian Processor"])
    assert game.confirm_number_choice(0, 4), "the entry payment is announced"
    assert p1.life == 16
    assert processor.metadata[LIFE_PAID_AS_ENTERED] == 4

    assert game.activate_permanent_ability(0, "Phyrexian Processor").supported
    resolve_stack(game)
    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 1
    assert (tokens[0].effective_power, tokens[0].effective_toughness) == (4, 4)
    assert "Phyrexian Minion" in tokens[0].card.type_line


def test_w1g5_phyrexian_processor_keeps_reading_the_same_number(set_pool):
    """Two activations, one entry payment: the value is fixed as the permanent
    entered, so nothing here recomputes it and the second Minion is the size of
    the first."""
    game, p1, _p2 = _g5a_game(interactive=(0,))
    processor = _g5a_put(game, 0, set_pool("USG")["Phyrexian Processor"])
    game.confirm_number_choice(0, 3)

    for _ in range(2):
        processor.tapped = False
        game.activate_permanent_ability(0, "Phyrexian Processor")
        resolve_stack(game)
    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 2
    assert all(
        (token.effective_power, token.effective_toughness) == (3, 3)
        for token in tokens
    )


def test_w1g5_smokestack_sacrifices_one_permanent_per_soot_counter(set_pool):
    """At the beginning of each player's upkeep, that player sacrifices a
    permanent of their choice for each soot counter on this artifact.

    The count sits on the *source*, so it is the same number whoever the upkeep
    belongs to — read per-payer it would be counted on a permanent that payer
    does not control and answer zero every time.
    """
    game, _p1, p2 = _g5a_game()
    stack = _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    for i in range(4):
        _g5a_put(game, 1, _mk_creature_card("G5 B%d" % i, 1, 1))
    add_counters(stack, "soot", 2)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert len(p2.battlefield) == 2
    assert len(p2.graveyard) == 2


def test_w1g5_smokestack_with_no_soot_counters_asks_for_nothing(set_pool):
    """CR 608.2's "as much as possible" at zero: a seat that owes none is not
    prompted, which is the difference between a Smokestack that has just arrived
    and one that has been ticking."""
    game, _p1, p2 = _g5a_game(interactive=(1,))
    _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    _g5a_put(game, 1, _mk_creature_card("G5 B0", 1, 1))

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert not [c for c in game.pending_choices if c.kind == "sacrifice"]
    assert len(p2.battlefield) == 1


def test_w1g5_smokestack_makes_the_upkeep_player_choose(set_pool):
    """"…that player sacrifices a permanent **of their choice**": the prompt is
    owed by the seat whose upkeep it is, not by the artifact's controller, and
    the game waits while it is owed."""
    game, _p1, p2 = _g5a_game(interactive=(1,))
    stack = _g5a_put(game, 0, set_pool("USG")["Smokestack"])
    for i in range(3):
        _g5a_put(game, 1, _mk_creature_card("G5 B%d" % i, 1, 1))
    add_counters(stack, "soot", 2)

    game.active_player_index = 1
    # No resolve_stack here on purpose: it answers whatever blocks the stack
    # through the registry's own default, which is precisely the prompt this
    # test is about — the helper would settle it out from under the assertions.
    game.resolve_upkeep(1)

    owed = [c for c in game.pending_choices if c.kind == "sacrifice"]
    assert len(owed) == 1
    assert owed[0].player_index == 1, "the upkeep player, not the controller"
    assert owed[0].data["count"] == 2
    assert len(p2.battlefield) == 3, "nothing goes until the choice is answered"


# --- W2G3: per-player upkeep sweeps ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, _mk_creature_card, resolve_stack


def _g3w2a_table():
    """Two seats with mana enforcement off.

    ``_g3w2a_`` prefixed and ending on ``return game, game.players[0],
    game.players[1]`` — SET_PLAYBOOK.md's note about a union splicing one
    helper's body onto another's signature.
    """
    game = Game(players=[PlayerState(name="W2G3A-A"), PlayerState(name="W2G3A-B")])
    game.enforce_mana_costs = False
    return game, game.players[0], game.players[1]


def _g3w2a_creature(game, seat, name, power, toughness):
    permanent = Permanent(card=_mk_creature_card(name, power, toughness))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def test_w2g3_noetic_scales_bounces_by_that_players_own_hand(set_pool):
    """"At the beginning of each player's upkeep, return to its owner's hand
    each creature that player controls with power greater than the number of
    cards in their hand."

    Two narrowings naming one seat, and it is a seat no read of the board can
    make — the firing event picked it, a different player every upkeep. Read as
    CR 109.5's "your hand" the comparison would be against the artifact
    controller's hand on every turn, which is right on one upkeep in two.

    So the two hands are deliberately different sizes, and the creature that
    survives is the one whose *own controller's* hand is the larger.
    """
    card = set_pool("USG")["Noetic Scales"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2a_table()
    game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    game._sync_control()
    alice.hand = [_mk_card(f"AH{i}", "Basic Land - Forest", "") for i in range(4)]
    bob.hand = [_mk_card("BH0", "Basic Land - Forest", "")]
    _g3w2a_creature(game, 0, "W2G3 Alice Giant", 3, 3)
    _g3w2a_creature(game, 1, "W2G3 Bob Giant", 3, 3)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert [c.name for c in bob.hand] == ["BH0", "W2G3 Bob Giant"], (
        "3 power beats a one-card hand, so Bob's creature comes back"
    )
    assert len(list(game.controlled_by(0))) == 2, (
        "Alice's 3/3 stays: her four-card hand is not the one being compared, "
        "and it is not her upkeep either"
    )


def test_w2g3_noetic_scales_spares_a_creature_under_the_bound(set_pool):
    """The comparison is strict — "greater than" — so a 1-power creature and a
    one-card hand is not a return."""
    game, alice, bob = _g3w2a_table()
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("USG")["Noetic Scales"]), None
    )
    game._sync_control()
    bob.hand = [_mk_card("BH0", "Basic Land - Forest", "")]
    _g3w2a_creature(game, 1, "W2G3 Bob Mouse", 1, 1)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert [c.name for c in bob.hand] == ["BH0"]
    assert len(list(game.controlled_by(1))) == 1


# --- W2G1: Urza's Armor, a static prevention of a fixed number of points ---
from engine import Game as _G1aGame, PlayerState as _G1aPlayerState  # noqa: E402
from engine.damage_events import deal_damage as _g1a_deal  # noqa: E402
from engine.models import Permanent as _G1aPermanent  # noqa: E402


def _g1a_board(pool, mine=()):
    """One seat holding the artifact, one without. Ends on the control sync,
    this block's own helper tail."""
    game = _G1aGame(players=[
        _G1aPlayerState(name="G1aA", battlefield=list(mine),
                        library=[pool["Remote Isle"]] * 8),
        _G1aPlayerState(name="G1aB", library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_urzas_armor_shaves_one_point_from_every_event(set_pool):
    """"If a source would deal damage to you, prevent 1 of that damage."

    A **prevention** (CR 615.1: the printed verb is "prevent") and not a
    replacement, and a *static* one — never used up, so it applies to every
    event for as long as the artifact is there. Three claims: the point comes
    off, a 1-damage source deals nothing at all (CR 120.8), and "to you" is the
    Armor's controller, so an opponent's face is untouched.
    """
    pool = set_pool("USG")
    armor = _G1aPermanent(card=pool["Urza's Armor"])
    game = _g1a_board(pool, mine=[armor])

    assert _g1a_deal(game, {"recipient": game.players[0], "amount": 3,
                            "source": None}).dealt == 2
    assert _g1a_deal(game, {"recipient": game.players[0], "amount": 1,
                            "source": None}).dealt == 0, (
        "CR 120.8: a source that would deal 0 damage deals none at all"
    )
    assert _g1a_deal(game, {"recipient": game.players[0], "amount": 3,
                            "source": None}).dealt == 2, (
        "a static prevention is never used up"
    )
    assert _g1a_deal(game, {"recipient": game.players[1], "amount": 3,
                            "source": None}).dealt == 3, (
        "'to you' is the Armor's controller"
    )


# --- W2G5: Claws of Gix and Fluctuator — costs charged and costs changed ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5a_slot(game, seat, permanent):
    """*permanent*'s slot in *seat*'s battlefield, for ``cost_permanent_index``."""
    for index, found in enumerate(game.controlled_by(seat)):
        if found is permanent:
            return index
    raise AssertionError("permanent is not on that battlefield")


def _g5a_table(set_pool, *names, seat=0):
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    pool = set_pool("USG")
    made = []
    for name in names:
        perm = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        made.append(perm)
    return game, made


def test_claws_of_gix_eats_the_permanent_the_payer_names(set_pool, catalog_by_name):
    """"{1}, Sacrifice a permanent: You gain 1 life."

    Barrin's cost one card over, and the pair is the whole reason the refusal
    was worth changing rather than hooking: one production, two cards. The
    named permanent is a land, which is what "a permanent" says may pay.
    """
    game, (claws,) = _g5a_table(set_pool, "Claws of Gix")
    swamp = Permanent(card=catalog_by_name["Swamp"])
    game._put_permanent_onto_battlefield(0, swamp, None)
    game.players[0].life = 20

    game.activate_permanent_ability(
        0, "Claws of Gix", cost_permanent_index=_g5a_slot(game, 0, swamp),
    )
    resolve_stack(game)

    assert game.players[0].life == 21
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]


def test_fluctuator_makes_a_printed_cycling_cost_free(set_pool, catalog_by_name):
    """"Cycling abilities you activate cost {2} less to activate."

    CR 702.29a's rewrite erases the word, so the discount has to derive which
    ability was a cycling ability — and it does that by running the rewrite
    backwards over the card's printed lines
    (``engine.cycling.is_cycling_ability``), never off the "Discard this card"
    cost, which Waker of Waves also has and is not cycling.

    Mana costs are *enforced* here, because a discount only means anything
    against a payment: the seat has no mana at all, so an undiscounted
    Cycling {2} would be refused and nothing would be drawn.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = True
    pool = set_pool("USG")
    fluctuator = Permanent(card=pool["Fluctuator"])
    game._put_permanent_onto_battlefield(0, fluctuator, None)
    alice.hand = [pool["Brand"]]
    alice.library = [catalog_by_name["Forest"], catalog_by_name["Forest"]]
    alice.mana_pool = {}

    result = game.activate_from_hand(0, "Brand")

    assert result.supported, game.log[-3:]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Forest"]
    assert [c.name for c in alice.graveyard] == ["Brand"]


def test_a_cycling_cost_is_not_free_without_the_fluctuator(set_pool, catalog_by_name):
    """The control the test above needs: with no discount on the board the same
    activation is refused for want of {2}.

    Without it, a Fluctuator that did nothing would still pass — the engine's
    hand path charged the printed cost *flat* until this group, so "it worked"
    and "the discount was applied" were indistinguishable.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = True
    pool = set_pool("USG")
    alice.hand = [pool["Brand"]]
    alice.library = [catalog_by_name["Forest"], catalog_by_name["Forest"]]
    alice.mana_pool = {}

    result = game.activate_from_hand(0, "Brand")

    assert not result.supported
    assert alice.hand and alice.hand[0].name == "Brand"


def test_fluctuator_leaves_a_non_cycling_hand_ability_alone(catalog_by_name, set_pool):
    """Waker of Waves prints "{1}{U}, Discard this card: …" and is **not** a
    cycling ability (CR 702.29a defines the keyword as one sentence, and this
    is a different one). Keying the discount on the discard cost — the obvious
    shortcut — would have made it free, which is an ability cheaper than the
    card.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = True
    fluctuator = Permanent(card=set_pool("USG")["Fluctuator"])
    game._put_permanent_onto_battlefield(0, fluctuator, None)
    alice.hand = [catalog_by_name["Waker of Waves"]]
    alice.library = [catalog_by_name["Forest"]] * 3
    alice.mana_pool = {}

    result = game.activate_from_hand(0, "Waker of Waves")

    assert not result.supported, "the {1}{U} is still owed"
    assert alice.hand and alice.hand[0].name == "Waker of Waves"


def test_a_cost_modifier_reaches_a_hand_activated_ability(catalog_by_name, set_pool):
    """The live gap this group closed, and the rule that bounds it.

    ``activate_from_hand`` charged ``ability.cost.mana`` flat, so **no** cost
    modifier reached an ability activated from a hand — a tax as much as a
    reduction. CR 601.2f is not about where the ability's source is.

    But CR 109.2 is: "activated abilities of creatures cost {1} less to
    activate" (Heartstone) describes creature *permanents*, and a creature card
    in a hand is not one. So the modifiers that reach a hand are exactly the
    ones whose subject names no object — Fluctuator's, whose subject is the
    **ability**. Both halves are asserted here, because closing the gap without
    the rule made a Heartstone cheapen Waker of Waves.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    pool = set_pool("USG")
    from engine.mixins.stack.activation import hand_activation_cost
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities
    from engine.activation_zones import HAND

    brand = pool["Brand"]
    cycling = usable_activated_abilities(compile_card_oracle(brand), zone=HAND)[0]
    waker = catalog_by_name["Waker of Waves"]
    hand_only = usable_activated_abilities(
        compile_card_oracle(waker), zone=HAND
    )[0]

    assert hand_activation_cost(game, 0, brand, cycling)[0].get("generic") == 2

    # "Activated abilities of **creatures** cost {1} less to activate." A card
    # in a hand is not a creature (CR 109.2), so neither ability moves.
    game._put_permanent_onto_battlefield(
        0, Permanent(card=catalog_by_name["Heartstone"]), None
    )
    assert hand_activation_cost(game, 0, brand, cycling)[0].get("generic") == 2
    assert hand_activation_cost(game, 0, waker, hand_only)[0].get("generic") == 1

    # Fluctuator names an *ability*, not an object, so it reaches the hand.
    fluctuator = Permanent(card=pool["Fluctuator"])
    game._put_permanent_onto_battlefield(0, fluctuator, None)
    assert hand_activation_cost(game, 0, brand, cycling)[0].get("generic") == 0
    assert hand_activation_cost(game, 0, waker, hand_only)[0].get("generic") == 1, (
        "Waker of Waves is not a cycling ability"
    )

    # And the discount is the *controller's* own (CR 109.5): a Fluctuator an
    # opponent controls says "you activate" about that opponent.
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Fluctuator"]), None)
    assert hand_activation_cost(game, 1, brand, cycling)[0].get("generic") == 0
    game.remove_from_battlefield(fluctuator)
    assert hand_activation_cost(game, 0, brand, cycling)[0].get("generic") == 2


# --- W2G2: the graveyard as a zone — Whetstone, Crystal Chimes, Citanul Flute, Lifeline ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2_board(set_pool, name, *, seat=0):
    """Seat *seat* controls *name*, untapped and free to activate. W2G2's own."""
    alice, bob = PlayerState(name="G2-A"), PlayerState(name="G2-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    perm = Permanent(card=set_pool("USG")[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return game, perm


def _g2_kill(game, seat, permanent):
    """Kill *permanent*: file its card, then take the object off the
    battlefield — the order ``_destroy_swept_permanents`` uses, and the order
    the death triggers are announced in. ``_permanent_to_graveyard`` is what
    announces them, and it is called while the permanent is still controlled,
    so a "whenever a creature **you control** dies" observer can still answer
    what it controlled. Removing first silently unfires every such trigger.
    W2G2's own.
    """
    game._permanent_to_graveyard(game.players[seat], permanent)
    game.remove_from_battlefield(permanent)
    resolve_stack(game)


def test_w2g2_whetstone_mills_every_seat_not_a_target(set_pool):
    """"{3}: Each player mills two cards."

    Both libraries are asserted, and they start at different sizes: a mill that
    fell through to ``context.target`` would empty one pile twice as fast and a
    single-library assertion would not notice.
    """
    game, _ = _g2_board(set_pool, "Whetstone")
    filler = set_pool("USG")["Sanctum Custodian"]
    game.players[0].library = [filler] * 6
    game.players[1].library = [filler] * 9

    game.activate_permanent_ability(0, "Whetstone")
    resolve_stack(game)

    assert len(game.players[0].library) == 4
    assert len(game.players[1].library) == 7
    assert len(game.players[0].graveyard) == 2
    assert len(game.players[1].graveyard) == 2


def test_w2g2_crystal_chimes_returns_only_enchantments_and_only_yours(set_pool):
    """"{3}, {T}, Sacrifice this artifact: Return all enchantment cards from
    your graveyard to your hand."

    Three assertions the card would pass with one of its narrowings dropped:
    the creature card stays put (the type filter reaches the sweep), the
    opponent's enchantment stays put (the sweep is one seat's), and the Chimes
    itself is in the graveyard afterwards (the sacrifice cost was paid).
    """
    pool = set_pool("USG")
    game, chimes = _g2_board(set_pool, "Crystal Chimes")
    mine, theirs = game.players
    mine.graveyard = [pool["Sanctum Custodian"], pool["Rune of Protection: Red"]]
    theirs.graveyard = [pool["Rune of Protection: Red"]]

    game.activate_permanent_ability(0, "Crystal Chimes")
    resolve_stack(game)

    assert [c.name for c in mine.hand] == ["Rune of Protection: Red"]
    assert [c.name for c in mine.graveyard] == ["Sanctum Custodian", "Crystal Chimes"]
    assert [c.name for c in theirs.graveyard] == ["Rune of Protection: Red"]
    assert not game.is_on_battlefield(chimes)


def test_w2g2_citanul_flute_finds_only_what_x_paid_for(set_pool):
    """"{X}, {T}: Search your library for a creature card with mana value X or
    less, reveal it, put it into your hand, then shuffle."

    The bound is the ability's own X, which nothing knows until the cost is
    paid — so the armed search is read at two values of X over one library, and
    the seven-drop is admitted by the second and not the first. A search that
    dropped the bound would admit both every time.
    """
    from engine.search_filters import search_matches

    pool = set_pool("USG")
    cheap, dear = pool["Serra Zealot"], pool["Shivan Hellkite"]

    def _admitted(x):
        game, _ = _g2_board(set_pool, "Citanul Flute")
        game.players[0].library = [cheap, dear]
        game.activate_permanent_ability(0, "Citanul Flute", x_value=x)
        prompt = game.pending_choice_of("search_library", 0)
        assert prompt is not None
        payload = {
            "restrictions": prompt.data["restrictions"],
            "card_type": prompt.data["card_type"],
        }
        return [
            c.name for c in game.players[0].library
            if search_matches(c, payload, game=game, owner=0)
        ]

    assert _admitted(1) == [cheap.name]
    assert _admitted(7) == [cheap.name, dear.name]


def test_w2g2_citanul_flute_puts_the_find_in_hand(set_pool):
    """The Rock Hydra half: the search is answered and the card arrives."""
    pool = set_pool("USG")
    game, _ = _g2_board(set_pool, "Citanul Flute")
    wanted = pool["Serra Zealot"]
    game.players[0].library = [wanted, wanted]

    game.activate_permanent_ability(0, "Citanul Flute", x_value=8)
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert [c.name for c in game.players[0].hand] == [wanted.name]
    assert len(game.players[0].library) == 1


def test_w2g2_lifeline_returns_the_dead_creature_at_the_next_end_step(set_pool):
    """"Whenever a creature dies, if another creature is on the battlefield,
    return the first card to the battlefield under its owner's control at the
    beginning of the next end step."

    Three claims: the card comes back at the *end step* and not on death, it
    comes back under its **owner's** control rather than Lifeline's controller's,
    and the intervening-if is real — the survivor is what lets the trigger fire
    at all.
    """
    pool = set_pool("USG")
    game, _ = _g2_board(set_pool, "Lifeline")
    survivor = Permanent(card=pool["Sanctum Custodian"])
    game._put_permanent_onto_battlefield(1, survivor, None)
    victim = Permanent(card=pool["Serra Zealot"])
    game._put_permanent_onto_battlefield(1, victim, None)

    _g2_kill(game, 1, victim)

    assert [c.name for c in game.players[1].graveyard] == ["Serra Zealot"]

    game.resolve_end_step(0)
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(1)] == [
        "Sanctum Custodian", "Serra Zealot",
    ]
    assert not game.players[1].graveyard


def test_w2g2_lifeline_stays_silent_with_no_other_creature(set_pool):
    """CR 603.4's intervening-if. The only creature on the battlefield dies, so
    "another creature is on the battlefield" is false when the trigger would
    fire — and nothing comes back. Without the clause Lifeline would return
    every creature that ever died, which is a different card.
    """
    pool = set_pool("USG")
    game, _ = _g2_board(set_pool, "Lifeline")
    victim = Permanent(card=pool["Serra Zealot"])
    game._put_permanent_onto_battlefield(1, victim, None)

    _g2_kill(game, 1, victim)
    game.resolve_end_step(0)
    resolve_stack(game)

    assert [c.name for c in game.players[1].graveyard] == ["Serra Zealot"]
    assert not list(game.controlled_by(1))


# --- W3G3: Purging Scythe — a superlative recipient and its tie-break ---
from engine import Game, PlayerState
from engine.game_types import Permanent
from tests.helpers import resolve_stack


def _g3_board(set_pool, *, mine=(), theirs=(), interactive=()):
    """A two-seat board with Purging Scythe on seat 0.

    `resolve_upkeep` puts the trigger on the stack and resolves it as far as the
    pick, so a caller inspecting the prompt must not then call `resolve_stack` —
    that answers it with the default and takes the choice away.
    """
    pool = set_pool("USG")
    lea = set_pool("LEA")
    scythe = Permanent(card=pool["Purging Scythe"])
    seat0 = [scythe] + [Permanent(card=lea[name]) for name in mine]
    seat1 = [Permanent(card=lea[name]) for name in theirs]
    game = Game(players=[
        PlayerState(name="P0", battlefield=seat0),
        PlayerState(name="P1", battlefield=seat1),
    ])
    game.interactive_seats = set(interactive)
    return game, scythe


def test_w3g3_purging_scythe_damages_the_least_toughness_creature(set_pool):
    """"…deals 2 damage to the creature with the least toughness." The whole
    board is the set, not this seat's half — and a 1/1 dies while a 3/3 does
    not."""
    game, _ = _g3_board(set_pool, mine=["Hill Giant"], theirs=["Scryb Sprites"])
    sprite = game.players[1].battlefield[0]
    giant = game.players[0].battlefield[1]

    game.resolve_upkeep(0)
    resolve_stack(game)
    game._settle()

    assert [c.name for c in game.players[1].graveyard] == ["Scryb Sprites"]
    assert sprite not in game.players[1].battlefield
    assert giant in game.players[0].battlefield
    assert giant.damage_marked == 0


def test_w3g3_purging_scythe_is_damage_not_destruction(set_pool):
    """Two damage, not a kill: a 2/3 survives with the damage marked on it.

    The difference from Drop of Honey, which prints the same noun phrase under
    "destroy", and the reason the pick is a step both verbs read rather than a
    handler either of them owns.
    """
    game, _ = _g3_board(set_pool, theirs=["Gray Ogre"])   # 2/2
    ogre = game.players[1].battlefield[0]

    game.resolve_upkeep(0)
    resolve_stack(game)
    game._settle()

    assert ogre not in game.players[1].battlefield   # 2 damage on a 2/2
    game2, _ = _g3_board(set_pool, theirs=["Hill Giant"])   # 3/3
    giant = game2.players[1].battlefield[0]
    game2.resolve_upkeep(0)
    resolve_stack(game2)
    game2._settle()
    assert giant in game2.players[1].battlefield
    assert giant.damage_marked == 2


def test_w3g3_purging_scythe_tie_prompts_its_controller(set_pool):
    """"If two or more creatures are tied for least toughness, you choose one of
    them." The generic ``permanent_choice`` prompt — the tie-break sentence
    lowers to no instruction of its own, because ``only_on_tie`` on the pick in
    front of it already is the sentence."""
    game, _ = _g3_board(
        set_pool, mine=["Scryb Sprites"], theirs=["Benalish Hero"],
        interactive=(0,),
    )
    mine = game.players[0].battlefield[1]
    theirs = game.players[1].battlefield[0]

    game.resolve_upkeep(0)

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_choice", 0)
    ]
    offered = game.live_permanent_choices(game.pending_choices[0])
    assert {p.card.name for p in offered} == {"Scryb Sprites", "Benalish Hero"}
    # Nothing is damaged until the controller picks.
    assert mine.damage_marked == 0 and theirs.damage_marked == 0

    assert game.confirm_permanent_choice(0, theirs.permanent_id) is True
    game._settle()
    assert theirs not in game.players[1].battlefield
    assert mine in game.players[0].battlefield


def test_w3g3_purging_scythe_refuses_a_creature_not_tied(set_pool):
    """A creature outside the tie is not an answer, and the prompt stays."""
    game, _ = _g3_board(
        set_pool, mine=["Scryb Sprites"], theirs=["Benalish Hero", "Hill Giant"],
        interactive=(0,),
    )
    giant = game.players[1].battlefield[1]

    game.resolve_upkeep(0)

    assert game.pending_choices
    assert game.confirm_permanent_choice(0, giant.permanent_id) is False
    assert giant in game.players[1].battlefield
    assert game.pending_choices


def test_w3g3_purging_scythe_with_no_creature_does_nothing(set_pool):
    """An empty board is a step that asked for nothing, not a crash."""
    game, scythe = _g3_board(set_pool)

    game.resolve_upkeep(0)
    resolve_stack(game)
    game._settle()

    assert scythe in game.players[0].battlefield
    assert not game.pending_choices


def test_w3g3_superlative_reads_the_computed_toughness(set_pool):
    """CR 613: the extreme is asked *now*. A -1/-1 on the bigger creature makes
    it the smallest, and the pick follows the layer accessor rather than the
    printed number."""
    game, _ = _g3_board(set_pool, mine=["Hill Giant"], theirs=["Gray Ogre"])
    giant = game.players[0].battlefield[1]     # 3/3
    ogre = game.players[1].battlefield[0]      # 2/2
    giant.toughness_bonus -= 2                 # now 3/1, the least toughness

    game.resolve_upkeep(0)
    resolve_stack(game)
    game._settle()

    assert giant not in game.players[0].battlefield
    assert ogre in game.players[1].battlefield


def test_w3g3_a_superlative_the_matcher_cannot_test_refuses(set_pool):
    """The payload key is deliberately outside ``TESTABLE_SUBJECT_FILTER_KEYS``.

    A sweep handed the same noun phrase must **refuse** rather than drop the
    word and burn the whole board — the failure the key set exists to prevent.
    """
    import pytest

    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(parse_line(
            "this artifact deals 2 damage to each creature with the least toughness"
        ))


def test_w3g3_a_tie_break_after_the_wrong_sentence_refuses(set_pool):
    """The rider is guarded on the sentence in front of it.

    A tie-break naming a different characteristic than the pick, or standing
    behind a sentence that picks nothing, fails the whole line loudly instead of
    being consumed and dropped.
    """
    import pytest

    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError

    with pytest.raises(GrammarError):
        parse_line(
            "this artifact deals 2 damage to the creature with the least "
            "toughness. if two or more creatures are tied for least power, "
            "you choose one of them"
        )
    with pytest.raises(GrammarError):
        parse_line(
            "this artifact deals 2 damage to target creature. if two or more "
            "creatures are tied for least toughness, you choose one of them"
        )
