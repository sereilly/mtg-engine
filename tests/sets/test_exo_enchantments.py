"""Exodus enchantments.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: triggers on what a player does ---
#
# Four enchantments whose trigger is somebody *else's* action. What they have in
# common is a seat the firing event names rather than the sentence: Spellshock's
# and Mana Breach's "that player" is whoever cast, and Predatory Hunger's
# trigger fires on an opponent's cast while its effect lands on a creature the
# Aura may not even share a controller with. So every test here checks the seat,
# not only that something happened — reading it off the ability's controller is
# right in a duel by accident half the time.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2_duel():
    """A two-seat game with costs off, seat 0 active. Its own helper and its own
    ending so a mechanical union cannot splice it onto another group's."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def _g2_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_spellshock_burns_the_player_who_cast_the_spell(set_pool):
    """CR 603.10: "that player" is the seat the firing event froze. The
    enchantment is Alice's and the spell is Bob's, so a reading that took the
    ability's controller would burn the wrong player."""
    game, alice, bob = _g2_duel()
    _g2_put(game, 0, set_pool("EXO")["Spellshock"])
    bob.hand.append(_G2_LEA["Lightning Bolt"])

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    resolve_stack(game)

    assert bob.life == 18
    assert alice.life < 20  # Bob's Bolt still resolved at Alice


def test_w1g2_spellshock_burns_its_own_controller_too(set_pool):
    """"Whenever **a player** casts a spell" is unnarrowed (CR 603.2), so the
    enchantment's own controller pays as well — which is what separates this
    condition from the opponent-scoped one Ichneumon Druid prints."""
    game, alice, _bob = _g2_duel()
    _g2_put(game, 0, set_pool("EXO")["Spellshock"])
    alice.hand.append(_G2_LEA["Grizzly Bears"])

    assert game.cast_from_hand(0, "Grizzly Bears").supported
    resolve_stack(game)

    assert alice.life == 18


def test_w1g2_mana_breach_makes_the_caster_return_their_own_land(set_pool):
    """The land comes off the *caster's* battlefield, not the enchantment
    controller's: "a land **they** control" names the seat the cast froze."""
    game, alice, bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Mana Breach"])
    _g2_put(game, 0, _G2_LEA["Mountain"])
    _g2_put(game, 1, _G2_LEA["Forest"])
    bob.hand.append(_G2_LEA["Grizzly Bears"])

    assert game.cast_from_hand(1, "Grizzly Bears").supported
    resolve_stack(game)

    assert [c.name for c in bob.hand] == ["Forest"]
    assert [p.card.name for p in game.controlled_by(bob)] == ["Grizzly Bears"]
    assert [p.card.name for p in game.controlled_by(alice)] == [
        "Mana Breach", "Mountain",
    ]


def test_w1g2_predatory_hunger_counts_only_an_opponents_creature_spells(set_pool):
    """The Aura is Alice's and watches Bob. Her own creature spell must not
    grow the host — the printed narrowing is the whole card."""
    game, alice, bob = _g2_duel()
    hunger = set_pool("EXO")["Predatory Hunger"]
    bears = _g2_put(game, 0, _G2_LEA["Grizzly Bears"])
    aura = _g2_put(game, 0, hunger)
    attach_aura(aura, bears)

    alice.hand.append(_G2_LEA["Hill Giant"])
    assert game.cast_from_hand(0, "Hill Giant").supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    bob.hand.append(_G2_LEA["Hill Giant"])
    assert game.cast_from_hand(1, "Hill Giant").supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g2_manabond_empties_the_hand_onto_the_battlefield(set_pool):
    """"You may reveal your hand and put all land cards from it onto the
    battlefield. **If you do**, discard your hand." Taking the offer is what
    fires the rider (CR 601.2), so the nonland cards go however many lands
    there were."""
    game, alice, _bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Manabond"])
    alice.hand.extend([
        _G2_LEA["Forest"], _G2_LEA["Mountain"], _G2_LEA["Giant Growth"],
    ])

    game.resolve_end_step(0)
    game._settle()
    # The offer outlives the trigger's own resolution, so it is answered here
    # rather than by ``resolve_stack``, which by contract touches only a
    # decision that is *blocking* the stack.
    game.auto_resolve_pending_choices()
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(alice)) == [
        "Forest", "Manabond", "Mountain",
    ]
    assert alice.hand == []
    assert [c.name for c in alice.graveyard] == ["Giant Growth"]


def test_w1g2_manabond_reveals_the_hand_it_discards(set_pool):
    """CR 701.20a shows the hand to every player, which is the price of the
    offer — the lowering used to refuse "you reveal your hand" on the grounds
    that the revealer already sees it, which is true of nobody else at the
    table."""
    game, alice, _bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Manabond"])
    alice.hand.append(_G2_LEA["Giant Growth"])

    game.resolve_end_step(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert any("reveals their hand" in line for line in game.log)
    assert [c.name for c in alice.graveyard] == ["Giant Growth"]


def test_w1g2_pandemonium_is_still_unsupported(set_pool):
    """A decline with its parts named, so the day they land this fails loudly.

    "Whenever a creature enters, that creature's controller may have it deal
    damage equal to its power to any target of their choice." Five pieces:

    1. a parse for "any target **of their choice**" — ``parse_target_spec``
       returns the moment it reads "any target" and the rest is unconsumed;
    2. a **chooser** on a target. Nothing in the engine models a target chosen
       by a seat other than the ability's controller (CR 603.3d), and admitting
       the line without one hands the choice to the Aura-less enchantment's
       controller — a target the card gives to somebody else;
    3. a bite whose **biter** is the entering permanent. ``lowering/_bites.py``
       has four dealers (the source, the attached host, two chosen targets, a
       recorded permanent) and none of them is the object the firing event
       froze, so "have **it** deal damage equal to its power" refuses at
       ``back-reference to 'its_power' with no producer in this effect``;
    4. ``handlers/damage.source_bites_target`` reading that biter —
       ``payload["biter"]`` has exactly one value today, ``"attached"``;
    5. that handler biting a **player**. It resolves its victim through
       ``resolve_target_permanent``, and "any target" (CR 115.4) includes
       players and planeswalkers.
    """
    program = compile_card_oracle(set_pool("EXO")["Pandemonium"])
    assert not program.supported
