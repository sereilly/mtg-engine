"""Weatherlight creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: dies, enters and leaves triggers ---
from engine import Game, PlayerState
from engine.models import Permanent


def _w1g2_rig(interactive=()):
    """A two-seat game with mana costs off.

    ``interactive`` names the seats that are *asked* their prompts. A
    non-interactive seat takes a prompt's default the moment it is armed, so a
    test written without this proves only that the default runs.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, alice, bob


def _w1g2_enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _w1g2_settle(game, limit=30):
    """Resolve the stack, stopping at an owed prompt.

    Never a bare ``while game.stack`` loop: an interactive seat that owes an
    answer holds the stack open (CR 608.2, CR 117.3b) and the loop would spin.
    """
    for _ in range(limit):
        if not game.stack or game.waiting_prompt():
            return
        game.resolve_top_of_stack()


def _w1g2_kill(game, permanent):
    """Lethal damage plus the CR 704.5g sweep - the real death path."""
    permanent.damage_marked = 999
    game.check_state_based_actions()


def _w1g2_names(zone):
    return sorted(getattr(entry, "card", entry).name for entry in zone)


def test_alabaster_dragon_shuffles_its_own_card_into_its_owners_library(
    set_pool, catalog_by_name
):
    """"When this creature dies, shuffle **it** into its owner's library."

    The card, not the permanent: by the time a death trigger resolves the
    Dragon is in a graveyard (CR 603.10), and the sentence names no source zone
    at all, so the handler has to reach whichever zone actually holds it. What
    proves the move happened is the graveyard being *empty* afterwards - a
    handler that appended to the library without removing it would leave two
    Dragons in the game.
    """
    game, alice, _ = _w1g2_rig()
    alice.library[:] = [catalog_by_name["Forest"]] * 3
    dragon = _w1g2_enters(game, 0, set_pool("WTH")["Alabaster Dragon"])

    _w1g2_kill(game, dragon)
    _w1g2_settle(game)

    assert alice.graveyard == []
    assert len(alice.library) == 4
    assert any(card.name == "Alabaster Dragon" for card in alice.library)


def test_barishi_exiles_itself_before_it_shuffles_the_rest_back(
    set_pool, catalog_by_name
):
    """"When this creature dies, exile it, **then** shuffle all creature cards
    from your graveyard into your library."

    The order is the card: exiled first, Barishi is not among the creature
    cards the second half sweeps up, so it does not shuffle itself back in.
    And the noun phrase is a real narrowing - the Lightning Bolt in the same
    graveyard stays there. A filter parsed and dropped would return the whole
    pile, which is a strictly better card.
    """
    game, alice, _ = _w1g2_rig()
    alice.library[:] = [catalog_by_name["Forest"]] * 2
    alice.graveyard[:] = [
        catalog_by_name["Grizzly Bears"],
        catalog_by_name["Lightning Bolt"],
        catalog_by_name["Hurloon Minotaur"],
    ]
    barishi = _w1g2_enters(game, 0, set_pool("WTH")["Barishi"])

    _w1g2_kill(game, barishi)
    _w1g2_settle(game)

    assert _w1g2_names(alice.exile) == ["Barishi"]
    assert _w1g2_names(alice.graveyard) == ["Lightning Bolt"]
    assert _w1g2_names(alice.library) == [
        "Forest", "Forest", "Grizzly Bears", "Hurloon Minotaur",
    ]


def test_timid_drake_does_not_bounce_itself_when_it_enters(set_pool, catalog_by_name):
    """"When **another** creature enters, return this creature to its owner's
    hand."

    The word is the whole card. ``engine/oracle.py``'s table read the line as
    ``enters_battlefield`` - the source's own entry - so the Drake bounced
    itself the turn it arrived and never fired again: an ability firing on the
    wrong event, which reads to every census as implemented. Both halves are
    asserted here because either alone passes on the broken reading.
    """
    game, alice, _ = _w1g2_rig()
    drake = _w1g2_enters(game, 0, set_pool("WTH")["Timid Drake"])
    _w1g2_settle(game)

    assert drake in alice.battlefield, "its own entry is not another creature's"
    assert alice.hand == []

    _w1g2_enters(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g2_settle(game)

    assert alice.battlefield == []
    assert _w1g2_names(alice.hand) == ["Timid Drake"]


def test_thundermare_leaves_itself_untapped(set_pool, catalog_by_name):
    """"When this creature enters, tap all **other** creatures."

    "Other" reaches the sweep as ``exclude_self`` and is tested against the
    ability's own source, which the handler already passes. Dropped, the
    Thundermare taps itself and attacks into nothing - the difference between
    the card and a strictly worse one. Both battlefields are swept: the phrase
    names no controller.
    """
    game, alice, bob = _w1g2_rig()
    mine = _w1g2_enters(game, 0, catalog_by_name["Grizzly Bears"])
    theirs = _w1g2_enters(game, 1, catalog_by_name["Hurloon Minotaur"])
    mare = _w1g2_enters(game, 0, set_pool("WTH")["Thundermare"])

    _w1g2_settle(game)

    assert mine.tapped and theirs.tapped
    assert not mare.tapped


def test_cinder_wall_destroys_itself_at_end_of_combat(set_pool, catalog_by_name):
    """"When this creature blocks, destroy **it** at end of combat."

    Under a trigger whose condition names no other object, "it" is the
    ability's own source - which is what the *immediate* destroy already read
    and only the delayed one refused. The Wall survives its block (3/3 against
    a 1/1) and dies to CR 603.7's delayed ability instead, which is the whole
    point of the card.
    """
    wall = Permanent(card=set_pool("WTH")["Cinder Wall"])
    attacker = Permanent(card=catalog_by_name["Mons's Goblin Raiders"])
    alice = PlayerState(name="Alice", battlefield=[attacker])
    bob = PlayerState(name="Bob", battlefield=[wall])
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game._settle()
    attacker.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: [0]})[0]
    _w1g2_settle(game)
    assert wall in bob.battlefield, "the destruction is delayed, not immediate"

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game.check_state_based_actions()
    assert wall in bob.battlefield, "a 1/1 does not kill a 3/3"

    game.end_combat()
    _w1g2_settle(game)
    game.check_state_based_actions()

    assert wall not in bob.battlefield
    assert _w1g2_names(bob.graveyard) == ["Cinder Wall"]


def test_sage_owl_rearranges_the_top_four_of_its_own_library(set_pool, catalog_by_name):
    """"When this creature enters, look at the top four cards of your library,
    then put them back in any order."

    Nothing is drawn and nothing is bottomed: the whole effect is the order,
    so the library's *size* is the check that no card moved zones and the
    order is the check that the prompt did anything at all. Seat 0 is
    interactive, or the default would answer for it.
    """
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.library[:] = [
        catalog_by_name[name]
        for name in ("Forest", "Mountain", "Plains", "Island", "Swamp")
    ]
    _w1g2_enters(game, 0, set_pool("WTH")["Sage Owl"])
    _w1g2_settle(game)

    assert game.pending_reorder_library == {
        "target_index": 0, "top_count": 4, "may_shuffle": False,
        "_cause_seat": 0, "caster_index": 0,
    }
    assert game.confirm_reorder_library(0, [3, 2, 1, 0]) is True
    assert [card.name for card in alice.library] == [
        "Island", "Plains", "Mountain", "Forest", "Swamp",
    ]


def test_harvest_wurm_is_sacrificed_when_the_graveyard_has_no_basic_land(
    set_pool, catalog_by_name
):
    """"When this creature enters, sacrifice it **unless you return a basic
    land card** from your graveyard to your hand."

    Two narrowings, and the card is wrong without either. A Bayou is a land
    card and not a *basic* one, so the price cannot be paid - and an offer that
    could be accepted anyway would return nothing, count as paid and leave the
    Wurm on the battlefield for free, which is the shape CR 601.2h's "able to"
    exists to refuse.
    """
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.graveyard[:] = [catalog_by_name["Bayou"]]
    _w1g2_enters(game, 0, set_pool("WTH")["Harvest Wurm"])
    _w1g2_settle(game)

    assert game.pending_choices == [], "an offer nobody can take is never made"
    assert alice.battlefield == []
    assert _w1g2_names(alice.graveyard) == ["Bayou", "Harvest Wurm"]


def test_harvest_wurm_pays_with_a_basic_land_from_the_graveyard(
    set_pool, catalog_by_name
):
    """The other half of the same sentence: with a Forest in the graveyard the
    price is payable, and paying it keeps the Wurm."""
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.graveyard[:] = [catalog_by_name["Forest"], catalog_by_name["Grizzly Bears"]]
    wurm = _w1g2_enters(game, 0, set_pool("WTH")["Harvest Wurm"])
    _w1g2_settle(game)

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True) is True
    _w1g2_settle(game)

    assert wurm in alice.battlefield
    assert _w1g2_names(alice.hand) == ["Forest"]
    assert _w1g2_names(alice.graveyard) == ["Grizzly Bears"]
