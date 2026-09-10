"""Urza's Destiny creatures.

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

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: reveal any number of cards in your hand ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


def _g1_seer_board(set_pool, catalog_by_name, seer, hand, *, interactive=False):
    """Alice with *seer* untapped on the battlefield and *hand* in hand.

    The hand is named by card, out of the whole deduped pool, because the
    printed noun phrases these twelve cards carry ("blue cards", "artifact
    cards") need colours and types Urza's Destiny does not conveniently print
    in one place.

    *interactive* is what decides whether the pick is **asked**: the choice is
    registered ``default_at_arm``, so a headless seat reveals every eligible
    card where the effect stands and an interactive one is queued a prompt.
    Both are exercised below, because the default is what AI and simulation
    play get and nothing else would ever run it.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    permanent = Permanent(card=set_pool("UDS")[seer])
    game._put_permanent_onto_battlefield(0, permanent, None)
    _nosick(permanent)
    alice.hand = [catalog_by_name[name] for name in hand]
    return game, alice, bob, permanent


def test_metalworker_adds_two_colorless_for_every_artifact_it_shows(
    set_pool, catalog_by_name
):
    """"{T}: Reveal any number of artifact cards in your hand. Add {C}{C} for
    each card revealed this way."

    The whole group in one card: a reveal that records how many cards it
    showed, and a sentence behind it that spends the count. Three artifacts
    revealed is six mana, not two, because the printed pips are a rate.
    """
    game, alice, _bob, _metalworker = _g1_seer_board(
        set_pool, catalog_by_name, "Metalworker",
        ["Black Lotus", "Mox Pearl", "Sol Ring", "Forest", "Lightning Bolt"],
    )

    result = game.activate_permanent_ability(0, "Metalworker")
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert alice.mana_pool.get("C") == 6


def test_metalworker_offers_only_the_artifact_cards_in_the_hand(
    set_pool, catalog_by_name
):
    """The printed noun phrase is what the seat is *offered*, not a check run
    afterwards.

    An offer wider than the phrase is a card that reports supported and cheats:
    a Metalworker that listed the Forest and the Lightning Bolt would make six
    mana off two artifacts. Read off the engine's own candidate rule, which is
    the same rule an answer is checked against.
    """
    game, alice, _bob, _metalworker = _g1_seer_board(
        set_pool, catalog_by_name, "Metalworker",
        ["Black Lotus", "Forest", "Sol Ring", "Lightning Bolt"],
        interactive=True,
    )

    game.activate_permanent_ability(0, "Metalworker")

    choice = game.pending_choice_of("choose_cards_in_hand")
    assert choice is not None
    offered = [alice.hand[i].name for i in game.live_choose_cards_in_hand(choice)]
    assert offered == ["Black Lotus", "Sol Ring"]


def test_metalworker_may_reveal_fewer_than_every_eligible_card(
    set_pool, catalog_by_name
):
    """"**Any number of**" makes the candidate count a ceiling, not a debt.

    An interactive seat that shows one of its three artifacts gets two mana.
    The count Sylvan Library's prompt owes is exact; this one's is not, and a
    Confirm gated on the exact number would refuse every honest answer.
    """
    game, alice, _bob, _metalworker = _g1_seer_board(
        set_pool, catalog_by_name, "Metalworker",
        ["Black Lotus", "Mox Pearl", "Sol Ring"],
        interactive=True,
    )

    game.activate_permanent_ability(0, "Metalworker")
    assert game.confirm_choose_cards_in_hand(0, [1])
    resolve_stack(game)

    assert alice.mana_pool.get("C") == 2


def test_metalworker_may_reveal_nothing_at_all(set_pool, catalog_by_name):
    """Nought is a legal answer to "any number", and it is not a refusal: the
    ability resolves, the record is written as zero and the sentence behind it
    spends nothing.

    Its own test because the record's *absence* is a different thing — a
    back-reference with no producer, which the lowering refuses outright — and
    the two are indistinguishable from the mana pool alone.
    """
    game, alice, _bob, _metalworker = _g1_seer_board(
        set_pool, catalog_by_name, "Metalworker",
        ["Black Lotus", "Sol Ring"],
        interactive=True,
    )

    game.activate_permanent_ability(0, "Metalworker")
    assert game.confirm_choose_cards_in_hand(0, [])
    resolve_stack(game)

    assert alice.mana_pool.get("C", 0) == 0
    assert not alice.graveyard, "revealing moves nothing (CR 701.20b)"
    assert len(alice.hand) == 2


def test_metalworker_holding_no_artifact_asks_nothing_and_adds_nothing(
    set_pool, catalog_by_name
):
    """An empty candidate set answers itself: there is nothing to ask, so no
    prompt is queued even for an interactive seat and the resolution finishes
    where it stands rather than waiting on a decision with one answer."""
    game, alice, _bob, _metalworker = _g1_seer_board(
        set_pool, catalog_by_name, "Metalworker",
        ["Forest", "Lightning Bolt"],
        interactive=True,
    )

    game.activate_permanent_ability(0, "Metalworker")
    resolve_stack(game)

    assert game.pending_choices == []
    assert alice.mana_pool.get("C", 0) == 0


def test_jasmine_seer_gains_two_life_for_every_white_card_shown(
    set_pool, catalog_by_name
):
    """"You gain **2** life for each card revealed this way."

    The printed number is a rate over the count, which the life family refused
    outright until this card: it read the clause only over a printed 1, so
    Jasmine Seer's sentence failed the line rather than gaining one life where
    the card says two. Two white cards is four life.
    """
    game, alice, _bob, _seer = _g1_seer_board(
        set_pool, catalog_by_name, "Jasmine Seer",
        ["Healing Salve", "Serra Angel", "Lightning Bolt"],
    )
    alice.life = 20

    result = game.activate_permanent_ability(0, "Jasmine Seer")
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert alice.life == 24


def test_cinder_seer_deals_one_damage_for_every_red_card_shown(
    set_pool, catalog_by_name
):
    """"…deals X damage to any target, **where X is the number of cards
    revealed this way**."

    The where-clause reading of the same record: a definition that is a plain
    number rather than a count of any zone, which is why it needs a producer in
    the same effect and refuses without one.
    """
    game, _alice, bob, _seer = _g1_seer_board(
        set_pool, catalog_by_name, "Cinder Seer",
        ["Lightning Bolt", "Shivan Dragon", "Disintegrate", "Healing Salve"],
    )
    bob.life = 20

    result = game.activate_permanent_ability(0, "Cinder Seer", target_player_index=1)
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert bob.life == 17


def test_ivy_seer_pumps_by_the_number_of_green_cards_shown(
    set_pool, catalog_by_name
):
    """"Target creature gets +X/+X until end of turn, where X is the number of
    cards revealed this way." Two green cards is +2/+2 on a 2/2."""
    game, _alice, _bob, _seer = _g1_seer_board(
        set_pool, catalog_by_name, "Ivy Seer",
        ["Giant Growth", "Llanowar Elves", "Lightning Bolt"],
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)

    result = game.activate_permanent_ability(
        # The seat as well as the id: an activation's announcement resolves its
        # object against one named battlefield, so an id alone lands on the
        # opponent's — which here holds nothing, and the pump falls back to
        # scanning and finds the Seer itself.
        0, "Ivy Seer", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def test_nightshade_seer_shrinks_by_the_number_of_black_cards_shown(
    set_pool, catalog_by_name
):
    """The same clause with the sign the card prints. Two black cards is -2/-2,
    which the state-based sweep then kills a 2/2 for (CR 704.5b)."""
    game, _alice, bob, _seer = _g1_seer_board(
        set_pool, catalog_by_name, "Nightshade Seer",
        ["Dark Ritual", "Terror", "Lightning Bolt"],
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)

    result = game.activate_permanent_ability(
        0, "Nightshade Seer", target_permanent_ids=[bears.permanent_id]
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears"]


def _g1_brine_seer_against_a_queued_spell(set_pool, catalog_by_name, blue, mana):
    """Alice's Brine Seer aimed at a spell Bob has on the stack.

    *blue* is how many blue cards Alice holds to reveal and *mana* how much Bob
    has to pay with, which between them are the whole card: the price is one
    per card shown, so the same board answers differently for a different
    reveal. The Seer's hand carries one red card throughout, so "blue cards" is
    doing work rather than meaning "the hand".
    """
    hand = ["Ancestral Recall", "Air Elemental", "Unsummon"][:blue]
    game, _alice, bob, _seer = _g1_seer_board(
        set_pool, catalog_by_name, "Brine Seer", hand + ["Lightning Bolt"],
    )
    bob.hand = [catalog_by_name["Grizzly Bears"]]
    bob.mana_pool["C"] = mana
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    result = game.activate_permanent_ability(0, "Brine Seer", target_stack_index=0)
    assert result.supported, game.log[-3:]
    resolve_stack(game)
    return game, bob


def test_brine_seer_charges_one_for_every_blue_card_shown(set_pool, catalog_by_name):
    """"Counter target spell unless its controller pays {1} **for each card
    revealed this way**."

    The printed cost is a rate, and the number is not knowable when the line is
    lowered — the reveal has not happened yet. So the multiplier travels to the
    counter flow as the record's name and the price is taken at resolution
    (CR 608.2). Three blue cards make the offer {3}, which three mana covers.
    """
    game, bob = _g1_brine_seer_against_a_queued_spell(
        set_pool, catalog_by_name, blue=3, mana=3
    )

    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert not bob.graveyard


def test_brine_seer_counters_a_spell_its_controller_cannot_afford(
    set_pool, catalog_by_name
):
    """The control the test above needs: two mana against three blue cards is
    not enough, and the spell is countered.

    Without it a Seer whose multiplier was silently dropped would still pass —
    {1} is covered by any board at all, so "it worked" and "the count was
    spent" are indistinguishable from the surviving spell alone.
    """
    game, bob = _g1_brine_seer_against_a_queued_spell(
        set_pool, catalog_by_name, blue=3, mana=2
    )

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears"]


def test_brine_seer_showing_one_blue_card_charges_only_one(set_pool, catalog_by_name):
    """The other end of the rate: the same two mana that lost the spell above
    keeps it when the Seer shows a single card. The price moved with the
    reveal, which is the only thing that could have changed it."""
    game, bob = _g1_brine_seer_against_a_queued_spell(
        set_pool, catalog_by_name, blue=1, mana=2
    )

    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert not bob.graveyard
