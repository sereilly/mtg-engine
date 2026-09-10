"""Urza's Destiny instants.

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


# --- W1G2: name-matched search, graveyards and libraries ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.fixture
def _g2i_lea(set_pool):
    """One Alpha card by name — the piles these instants read need several
    copies of one card, which the UDS pool can supply but not readably."""
    return lambda name: set_pool("LEA")[name]


def _g2i_seats(*players):
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def test_scour_strips_every_copy_of_the_enchantment_it_exiles(set_pool, _g2i_lea):
    """Eradicate's sentence over enchantments — one production, one word
    apart, so the test that matters is that the *noun* did not leak."""
    aura = _g2i_lea("Animate Dead")
    salve = _g2i_lea("Healing Salve")
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Scour"]]),
        PlayerState(
            name="G2i-B", battlefield=[Permanent(card=aura)],
            hand=[aura, salve], graveyard=[aura], library=[aura, salve],
        ),
    )
    assert game.queue_from_hand(
        0, "Scour", target_player_index=1, target_permanent_index=0,
    ).details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    assert [p.card.name for p in victim.battlefield] == []
    assert sorted(c.name for c in victim.exile) == ["Animate Dead"] * 4
    assert sorted(c.name for c in victim.hand) == ["Healing Salve"]
    assert sorted(c.name for c in victim.library) == ["Healing Salve"]


def test_quash_exiles_the_countered_card_and_its_copies(set_pool, _g2i_lea):
    """"Counter target instant or sorcery spell. Search its controller's
    graveyard, hand, and library for all cards with the same name as that
    spell and exile them."

    The countered card is in the graveyard by the time the search runs
    (CR 701.6a), so it is one of the copies the strip takes — which is the
    thing a test written from the printed sentence alone would get wrong.
    """
    bolt = _g2i_lea("Lightning Bolt")
    salve = _g2i_lea("Healing Salve")
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Quash"]]),
        PlayerState(
            name="G2i-B", hand=[bolt, salve], graveyard=[bolt, salve],
            library=[bolt, salve],
        ),
    )
    assert game.queue_from_hand(1, "Lightning Bolt").details == "queued"
    assert game.queue_from_hand(0, "Quash", target_stack_index=0).details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    # The one in the graveyard, the one in the library, and the one it
    # countered — which is in the graveyard by then. The hand's copy is the one
    # that was cast, so three is every copy that existed when the search ran.
    assert sorted(c.name for c in victim.exile) == ["Lightning Bolt"] * 3
    assert sorted(c.name for c in victim.hand) == ["Healing Salve"]
    assert sorted(c.name for c in victim.graveyard) == ["Healing Salve"]
    assert sorted(c.name for c in victim.library) == ["Healing Salve"]


def test_rapid_decay_exiles_cards_of_any_type_from_one_pile(set_pool, _g2i_lea):
    """"Exile up to three target cards from a single graveyard."

    "Cards", with no type named — and that is the whole test. The pile the
    engine offers is read by ``graveyard_card_matches``, whose *unnarrowed*
    default is "creature card", so a lowering that simply left the type key off
    narrowed a sentence that narrows nothing: against a graveyard of lands and
    spells this reported that no graveyard held a card it could exile.
    """
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Rapid Decay"]]),
        PlayerState(
            name="G2i-B",
            graveyard=[
                _g2i_lea("Mountain"), _g2i_lea("Lightning Bolt"),
                _g2i_lea("Black Lotus"), _g2i_lea("Island"),
            ],
        ),
    )
    assert game.queue_from_hand(0, "Rapid Decay").details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    assert len(victim.exile) == 3, [c.name for c in victim.exile]
    assert len(victim.graveyard) == 1
    # One pile only: the caster's own graveyard is untouched.
    assert game.players[0].exile == []


def test_rapid_decay_still_reads_a_graveyard_with_no_creature_in_it(set_pool, _g2i_lea):
    """The regression above stated as the case that used to fail outright.

    Every card in the pile is a land; the sentence names cards, so all of them
    are legal choices and the spell has a pile to open.
    """
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Rapid Decay"]]),
        PlayerState(
            name="G2i-B",
            graveyard=[_g2i_lea("Mountain"), _g2i_lea("Island")],
        ),
    )
    assert game.queue_from_hand(0, "Rapid Decay").details == "queued"
    resolve_stack(game)
    assert sorted(c.name for c in game.players[1].exile) == ["Island", "Mountain"]


# --- W1G1: reveal any number of cards in your hand ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_scent_duel(set_pool, catalog_by_name, scent, hand):
    """Alice holding *scent* plus *hand*, against Bob.

    The Scents are the five Seers' abilities printed as spells — the same two
    sentences with no activation cost in front of them — so these tests are the
    other half of the group's claim: the reveal and the count it records belong
    to the *sentence*, not to what put it on the stack.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    alice.hand = [set_pool("UDS")[scent]] + [
        catalog_by_name[name] for name in hand
    ]
    return game, alice, bob


def test_scent_of_jasmine_gains_two_life_per_white_card(set_pool, catalog_by_name):
    """"Reveal any number of white cards in your hand. You gain 2 life for each
    card revealed this way."

    Three white cards is six life. The Scent itself is white and in the hand
    when it is cast, but a spell on the stack is not in its owner's hand
    (CR 400.1), so it is not one of the three.
    """
    game, alice, _bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Jasmine",
        ["Healing Salve", "Serra Angel", "Swords to Plowshares", "Lightning Bolt"],
    )
    alice.life = 20

    result = game.cast_from_hand(0, "Scent of Jasmine")
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert alice.life == 26


def test_scent_of_jasmine_with_no_white_card_gains_nothing(set_pool, catalog_by_name):
    """A reveal that showed nothing records a zero rather than nothing at all,
    and the sentence behind it gains zero life.

    The distinction is the point: an *absent* record is a back-reference with
    no producer, which the lowering refuses outright — so a card that resolves
    and gains nothing is the printed behaviour, not a silent miss.
    """
    game, alice, _bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Jasmine",
        ["Lightning Bolt", "Giant Growth"],
    )
    alice.life = 20

    result = game.cast_from_hand(0, "Scent of Jasmine")
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Lightning Bolt", "Giant Growth"]


def test_scent_of_ivy_pumps_by_the_green_cards_shown(set_pool, catalog_by_name):
    """"Target creature gets +X/+X until end of turn, where X is the number of
    cards revealed this way." Three green cards on a 2/2 is a 5/5."""
    game, _alice, bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Ivy",
        ["Giant Growth", "Llanowar Elves", "Regeneration", "Lightning Bolt"],
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)

    result = game.cast_from_hand(
        0, "Scent of Ivy", target_permanent_ids=[bears.permanent_id]
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_scent_of_nightshade_shrinks_by_the_black_cards_shown(
    set_pool, catalog_by_name
):
    """The same clause with the printed sign. One black card is -1/-1, which a
    2/2 survives — the control the death below needs."""
    game, _alice, bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Nightshade",
        ["Dark Ritual", "Lightning Bolt"],
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)

    result = game.cast_from_hand(
        0, "Scent of Nightshade", target_permanent_ids=[bears.permanent_id]
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert (bears.effective_power, bears.effective_toughness) == (1, 1)
    assert not bob.graveyard


def test_scent_of_nightshade_kills_what_it_shrinks_to_nothing(
    set_pool, catalog_by_name
):
    """Two black cards is -2/-2, and CR 704.5b puts a 0-toughness creature in
    its owner's graveyard. The pair with the test above is what shows the
    number moved with the reveal rather than being a printed constant."""
    game, _alice, bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Nightshade",
        ["Dark Ritual", "Terror", "Lightning Bolt"],
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)

    result = game.cast_from_hand(
        0, "Scent of Nightshade", target_permanent_ids=[bears.permanent_id]
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears"]


def test_scent_of_brine_taxes_by_the_blue_cards_shown(set_pool, catalog_by_name):
    """The counter's rate on a spell rather than on an activated ability. Two
    blue cards make the offer {2}, which Bob's two mana covers."""
    game, _alice, bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Brine",
        ["Ancestral Recall", "Unsummon", "Lightning Bolt"],
    )
    bob.hand = [catalog_by_name["Grizzly Bears"]]
    bob.mana_pool["C"] = 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    result = game.cast_from_hand(0, "Scent of Brine", target_stack_index=0)
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_scent_of_brine_counters_what_two_mana_cannot_cover(
    set_pool, catalog_by_name
):
    """Three blue cards make it {3}, and the same two mana no longer covers it.
    The board did not move; the reveal did."""
    game, _alice, bob = _g1_scent_duel(
        set_pool, catalog_by_name, "Scent of Brine",
        ["Ancestral Recall", "Unsummon", "Air Elemental", "Lightning Bolt"],
    )
    bob.hand = [catalog_by_name["Grizzly Bears"]]
    bob.mana_pool["C"] = 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    result = game.cast_from_hand(0, "Scent of Brine", target_stack_index=0)
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears"]
