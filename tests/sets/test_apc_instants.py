"""Apocalypse instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.grammar import compile_line as _w1g7_compile_line
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_instant_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt one of these cards arms is *queued* rather than answered by its own
    default — a headless probe cannot tell "nobody was asked" from "nobody was
    there to ask"."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def _w1g7_instant_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_bolt_at_seat_zero(game, catalog_by_name):
    """Seat 1 puts a Lightning Bolt on the stack aimed at seat 0."""
    game.players[1].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game.stack[-1]


# -- Evasive Action ----------------------------------------------------------


def test_evasive_action_prices_the_toll_at_one_per_basic_land_type(
    set_pool, catalog_by_name
):
    """"Domain — Counter target spell unless its controller pays {1} **for each
    basic land type among lands you control**." Three types is {3}, asked of
    the spell's controller, and a board that cannot cover it loses the spell."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(2)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    assert game.queue_from_hand(0, "Evasive Action", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    owed = game.pending_mana_payment
    assert owed is not None and owed["player_index"] == 1 and owed["amount"] == 3
    assert "Evasive Action: B must pay {3} or Lightning Bolt is countered" in game.log
    # Two Mountains cannot make three mana: saying yes is still a counter.
    assert game.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 20
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert [land.tapped for land in mountains] == [False, False]
    assert any("Lightning Bolt was countered by Evasive Action" in line for line in game.log)


def test_evasive_action_lets_a_paid_spell_resolve(set_pool, catalog_by_name):
    """The other answer: {3} paid from three lands, and the Bolt lands."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(3)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 17
    assert all(land.tapped for land in mountains)
    assert "B paid {3}; Lightning Bolt is not countered" in game.log


@_w1g7_pytest.mark.parametrize(
    "lands, owed",
    [
        # Types, not lands: two Islands are one type, and a Tropical Island is
        # an Island and a Forest (CR 305.6) — two types among three lands.
        (("Island", "Island", "Tropical Island"), 2),
        (("Island", "Swamp", "Mountain", "Forest", "Plains", "Plains"), 5),
        (("Island",), 1),
    ],
)
def test_evasive_action_counts_basic_land_types_not_lands(
    set_pool, catalog_by_name, lands, owed
):
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in lands:
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    # The *spell's* controller's lands are not counted, whatever they are.
    for name in ("Swamp", "Mountain", "Forest", "Plains"):
        _w1g7_instant_put(game, 1, catalog_by_name[name])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.pending_mana_payment["amount"] == owed


def test_evasive_action_with_no_basic_land_type_counters_nothing(
    set_pool, catalog_by_name
):
    """A domain of zero is a price of {0}, which every board covers: no prompt
    is armed and the spell resolves. A nonbasic land with no basic land type
    (Mishra's Factory) contributes nothing."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    _w1g7_instant_put(game, 0, catalog_by_name["Mishra's Factory"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert game.pending_mana_payment is None
    assert p0.life == 17
    assert "B pays {0}; Lightning Bolt is not countered by Evasive Action" in game.log


def test_evasive_action_needs_a_spell_to_name(set_pool):
    """CR 601.2c: with nothing on the stack there is no target, and the cast is
    refused with the card still in hand."""
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Evasive Action"]]

    result = game.cast_from_hand(0, "Evasive Action")

    assert not result.supported
    assert [card.name for card in p0.hand] == ["Evasive Action"]


def test_a_counted_counter_price_refuses_what_the_flow_cannot_charge():
    """The production's refusals. "Beyond the first" is a discount the payment
    never takes, and a coloured rate times a count is arithmetic the prompt
    does not do — each must leave its line unsupported rather than charge the
    wrong number."""
    discounted = _w1g7_compile_line(
        "Counter target spell unless its controller pays {1} for each creature "
        "you control beyond the first."
    )
    assert discounted.parse_error == "no counter price discounts the first counted object"

    coloured = _w1g7_compile_line(
        "Counter target spell unless its controller pays {U} for each basic "
        "land type among lands you control."
    )
    assert coloured.parsed and not coloured.usable
    assert coloured.lowering_error == "only a printed generic cost is paid per counted object"


# -- Jaded Response ----------------------------------------------------------


@_w1g7_pytest.mark.parametrize(
    "mine, theirs, countered",
    [
        # A red creature of the caster's shares red with the Bolt.
        ("Goblin Balloon Brigade", None, True),
        # A blue one shares nothing with it.
        ("Prodigal Sorcerer", None, False),
        # "A creature **you control**": the opponent's red creature is nobody's
        # business here.
        (None, "Goblin Balloon Brigade", False),
        # CR 105.2c: a colourless object shares a colour with nothing.
        ("Ornithopter", None, False),
        (None, None, False),
    ],
)
def test_jaded_response_counters_only_a_spell_sharing_a_color_with_your_creature(
    set_pool, catalog_by_name, mine, theirs, countered
):
    """"Counter target spell **if it shares a color with a creature you
    control**." Asserted on the life total: a counter that fired without its
    condition, or a condition that never held, both read wrong here."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    if mine:
        _w1g7_instant_put(game, 0, catalog_by_name[mine])
    if theirs:
        _w1g7_instant_put(game, 1, catalog_by_name[theirs])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    # "Target spell" is the whole of the targeting restriction (CR 608.2b), so
    # the Bolt is a legal target whether or not the condition will hold.
    offered = game.cast_target_spec(0, set_pool("APC")["Jaded Response"])
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Lightning Bolt"]
    assert game.cast_from_hand(0, "Jaded Response", target_stack_index=0).supported
    _w1g7_resolve_stack(game)

    assert p0.life == (20 if countered else 17)
    assert [card.name for card in p0.graveyard] == ["Jaded Response"]
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert countered == any(
        "Lightning Bolt was countered by Jaded Response" in line for line in game.log
    )


def test_jaded_response_reads_the_colors_as_it_resolves(set_pool, catalog_by_name):
    """The card's ruling: "It does not check colors until it resolves" (CR
    608.2c). The red creature that made the cast worthwhile leaves in response,
    and the Bolt is no longer a spell this counters."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    goblin = _w1g7_instant_put(game, 0, catalog_by_name["Goblin Balloon Brigade"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert game.queue_from_hand(0, "Jaded Response", target_stack_index=0).supported
    game.remove_from_battlefield(goblin)
    _w1g7_resolve_stack(game)

    assert p0.life == 17


def test_jaded_response_sees_a_spell_an_effect_recolored(set_pool, catalog_by_name):
    """The spell's colour is what it is *on the stack* (CR 613.1): a Bolt a
    Vodalian Mystic has made blue shares blue with a Prodigal Sorcerer, and no
    longer shares red with a Goblin."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    _w1g7_instant_put(game, 0, catalog_by_name["Prodigal Sorcerer"])
    bolt = _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    bolt.choices["color_override"] = "U"
    p0.hand = [set_pool("APC")["Jaded Response"]]

    game.cast_from_hand(0, "Jaded Response", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert p0.life == 20


def test_jaded_response_cannot_be_cast_at_an_empty_stack(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert not game.cast_from_hand(0, "Jaded Response").supported
    assert [card.name for card in p0.hand] == ["Jaded Response"]


def test_a_shared_color_condition_is_asked_of_a_spell_and_refuses_elsewhere():
    """The lowering's refusals: the clause about a targeted *permanent* turns on
    whether an object is one of the things it is compared with, which no card
    prints to rule on; and under a trigger "it" names the event's subject."""
    on_a_permanent = _w1g7_compile_line(
        "Destroy target creature if it shares a color with a creature you control."
    )
    assert on_a_permanent.parsed and not on_a_permanent.usable
    assert "asked of a targeted spell" in on_a_permanent.lowering_error

    under_a_trigger = _w1g7_compile_line(
        "Whenever a player casts a spell, counter it if it shares a color with "
        "a creature you control."
    )
    assert not under_a_trigger.usable

    trailing = _w1g7_compile_line(
        "Counter target spell if it shares a color with a creature you control "
        "and draw a card."
    )
    assert not trailing.parsed


# -- Suffocating Blast (driven, and declined) --------------------------------


def test_suffocating_blast_is_refused_until_a_spell_and_a_creature_can_be_named_together(
    set_pool,
):
    """"Counter target spell and Suffocating Blast deals 3 damage to target
    creature." Two targets in two zones (CR 601.2c announces both), and no
    announcement here carries a stack slot beside a battlefield one. It
    compiled on arrival off its *first* target alone, and driven that was: a
    picker offering the spell and nothing else, the cast accepted with no
    creature on any battlefield, a named artifact dealt the damage, and an
    unnamed creature slot answered by whichever creature the resolver met.

    Refused, by the roles walk that proves the two targets are two, until the
    stack slot exists — a card that reports unsupported naming its clause is
    the honest state for one that cannot be announced."""
    blast = set_pool("APC")["Suffocating Blast"]
    program = _w1g7_compile(blast)

    assert not program.supported
    assert program.instructions == ()

    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [blast]
    assert not game.cast_from_hand(0, "Suffocating Blast").supported
    assert [card.name for card in p0.hand] == ["Suffocating Blast"]


def test_one_target_named_once_beside_a_spell_is_still_one_announcement(catalog_by_name):
    """The refusal's edge: it fires on a spell target *beside another target*,
    never on a counterspell with a second sentence. Every shipped counter that
    goes on to do something keeps the program it had."""
    for name in ("Counterspell", "Memory Lapse", "Exclude", "Absorb", "Undermine"):
        if name in catalog_by_name:
            assert _w1g7_compile(catalog_by_name[name]).supported, name
    plain = _w1g7_compile_line("Counter target spell. Draw a card.")
    assert plain.usable


# -- Shimmering Mirage (driven) ----------------------------------------------


def test_shimmering_mirage_changes_a_land_and_draws_a_card(set_pool, catalog_by_name):
    """"Target land becomes the basic land type of your choice until end of
    turn. / Draw a card." A land is the only thing it may name, the type is
    asked as it resolves, and the turn's end gives the Forest back."""
    game, p0, p1 = _w1g7_instant_duel()
    forest = _w1g7_instant_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    mirage = set_pool("APC")["Shimmering Mirage"]
    p0.hand = [mirage]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, mirage)
    assert offered["kind"] == "land"
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Forest"]
    assert not game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]

    assert game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_land_type_choice["player_index"] == 0
    assert forest.basic_land_types == ("forest",)
    assert game.confirm_land_type(0, "island") is True

    assert forest.basic_land_types == ("island",)
    assert [card.name for card in p0.hand] == ["Island"]
    assert [card.name for card in p0.graveyard] == ["Shimmering Mirage"]
    assert game.stack == []

    game.resolve_cleanup_step(0)
    assert forest.basic_land_types == ("forest",)


def test_shimmering_mirage_with_no_land_to_name_cannot_be_cast(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Shimmering Mirage"]]

    assert not game.cast_from_hand(0, "Shimmering Mirage").supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]


# -- Smash (driven) ----------------------------------------------------------


def test_smash_destroys_the_named_artifact_and_draws_a_card(set_pool, catalog_by_name):
    """"Destroy target artifact. / Draw a card." An artifact creature is an
    artifact (CR 205.2); a creature that is not one is refused at announcement
    with the card still in hand."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    thopter = _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    smash = set_pool("APC")["Smash"]
    p0.hand = [smash]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, smash)
    assert sorted(entry["name"] for entry in offered["valid_targets"]) == [
        "Ornithopter", "Sol Ring",
    ]
    assert not game.cast_from_hand(
        0, "Smash", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Smash"]

    assert game.cast_from_hand(
        0, "Smash", target_permanent_ids=[thopter.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Sol Ring", "Grizzly Bears"]
    assert [card.name for card in p1.graveyard] == ["Ornithopter"]
    assert [card.name for card in p0.hand] == ["Island"]
    assert ring in p1.battlefield


def test_smash_whose_artifact_has_left_draws_nothing(set_pool, catalog_by_name):
    """CR 608.2b: with its only target gone the spell does not resolve — the
    second sentence is not a consolation prize."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    p0.hand = [set_pool("APC")["Smash"]]
    p0.library = [catalog_by_name["Island"]]

    assert game.queue_from_hand(
        0, "Smash", target_permanent_ids=[ring.permanent_id]
    ).supported
    game.remove_from_battlefield(ring)
    _w1g7_resolve_stack(game)

    assert p0.hand == []
    assert [card.name for card in p0.library] == ["Island"]
    # …and it did not go looking for the other artifact.
    assert [perm.card.name for perm in p1.battlefield] == ["Ornithopter"]

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
