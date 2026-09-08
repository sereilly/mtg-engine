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
