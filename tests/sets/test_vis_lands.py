"""Visions lands.

Split from ``test_vis_creatures.py`` by the printed type of the card each test
names (``tests/sets/README.md``).
"""

from __future__ import annotations
import pytest
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

# --- G1: the return-to-hand family ---
#
# Imports at the top of this block, so a merge that appends another group's
# block below cannot lose them (SET_PLAYBOOK.md, "give every group's test block
# its own imports").



def _rig():
    """A two-seat game with mana enforcement off, seat 0 interactive.

    Interactive on purpose: the prompts this family arms take their default at
    arm time for a non-interactive seat, so a headless rig answers its own
    questions and a test written against it proves only that the default runs.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, alice, bob


def _enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _names(permanents):
    return [permanent.card.name for permanent in permanents]


def test_coral_atoll_returns_an_untapped_island_and_stays(set_pool, catalog_by_name):
    """"When this land enters, sacrifice it unless you return an untapped
    Island you control to its owner's hand." (Coral Atoll and its four
    siblings.)

    The whole cycle prints one sentence with the basic type changed, so this
    test is the cycle's — the parametrized case below is what says so.
    """
    game, alice, _ = _rig()
    first = _enters(game, 0, catalog_by_name["Island"])
    second = _enters(game, 0, catalog_by_name["Island"])
    atoll = _enters(game, 0, set_pool("VIS")["Coral Atoll"])

    assert game.confirm_optional_pay(0, accept=True) is True
    # The price is a *choice*: the seat names which Island, and the prompt is
    # still owed until it does.
    assert game.confirm_permanent_set_choice(0, [second.permanent_id]) is True

    assert _names(alice.battlefield) == ["Island", "Coral Atoll"]
    assert alice.battlefield[0] is first
    assert [card.name for card in alice.hand] == ["Island"]
    assert game.is_on_battlefield(atoll)


@pytest.mark.parametrize(
    "land,basic",
    [
        ("Coral Atoll", "Island"),
        ("Dormant Volcano", "Mountain"),
        ("Everglades", "Swamp"),
        ("Jungle Basin", "Forest"),
        ("Karoo", "Plains"),
    ],
)
def test_the_karoo_cycle_is_sacrificed_with_no_untapped_basic(
    set_pool, catalog_by_name, land, basic
):
    """A *tapped* basic of the printed type does not pay the price.

    The word "untapped" is the narrowing that makes this cycle a real cost, and
    a production that consumed it without honouring it would keep every one of
    these lands on a board that could not pay — which is the direction a
    dropped rider always fails in.
    """
    game, alice, _ = _rig()
    tapped = _enters(game, 0, catalog_by_name[basic])
    game.become_tapped(tapped)
    _enters(game, 0, set_pool("VIS")[land])

    # No offer was made at all: `_action_is_takeable` found nothing the price
    # could be paid with, so the decline branch ran without asking.
    assert game.pending_choices == []
    assert _names(alice.battlefield) == [basic]
    assert [card.name for card in alice.graveyard] == [land]


def test_undiscovered_paradise_returns_itself_instead_of_untapping(set_pool, catalog_by_name):
    """"{T}: Add one mana of any color. During your next untap step, as you
    untap your permanents, return this land to its owner's hand."

    Three things have to be true at once and only a game shows it: the mana
    arrives, the land does **not** untap, and it is in a hand afterwards. A
    delayed triggered ability would get the first and the third right and the
    second wrong — the untap step gives nobody priority (CR 502.4), so it would
    fire at the upkeep with the land already untapped.
    """
    game, alice, _ = _rig()
    other = _enters(game, 0, catalog_by_name["Forest"])
    game.become_tapped(other)
    paradise = _enters(game, 0, set_pool("VIS")["Undiscovered Paradise"])
    paradise.metadata["summoning_sickness_turn"] = -99

    result = game.activate_permanent_ability(0, "Undiscovered Paradise", mana_color="U")
    assert result.supported is True
    assert alice.mana_pool["U"] == 1
    assert paradise.tapped is True

    game.turn = 3
    game.resolve_untap_step(0)

    assert _names(alice.battlefield) == ["Forest"]
    assert alice.battlefield[0].tapped is False, "everything else still untaps"
    assert [card.name for card in alice.hand] == ["Undiscovered Paradise"]


def test_undiscovered_paradise_is_one_untap_step_only(set_pool, catalog_by_name):
    """The marker names *one* step (CR 611.2a).

    An untap step that is not the one the ability named leaves it alone, so a
    land whose ability was never activated untaps like any other — the check
    that the marker is a record rather than a property of the card.
    """
    game, alice, _ = _rig()
    paradise = _enters(game, 0, set_pool("VIS")["Undiscovered Paradise"])
    game.become_tapped(paradise)

    game.turn = 3
    game.resolve_untap_step(0)

    assert _names(alice.battlefield) == ["Undiscovered Paradise"]
    assert paradise.tapped is False
    assert alice.hand == []


def test_the_karoo_cycle_carries_no_instruction_less_ability(set_pool):
    """Every printed line of the cycle compiles to something.

    The five lands reported ``supported`` from the day they were ingested — a
    land with a mana ability is supported whatever else it says — while the
    sentence that gates them produced no instruction at all. Only
    ``--hollow-lines`` could see it, and this is that report as an assertion.
    """
    pool = set_pool("VIS")
    for name in ("Coral Atoll", "Dormant Volcano", "Everglades", "Jungle Basin", "Karoo"):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        assert len(program.triggered_abilities) == 1, name
        trigger = program.triggered_abilities[0]
        assert trigger.supported is True, name
        assert trigger.instruction is not None, name
        assert trigger.instruction.kind == "may", name


# --- W1G5: the pronoun's type test (Griffin Canyon) ---



def _g5_canyon(set_pool):
    """Griffin Canyon, a tapped Griffin and a bystander, all able to act."""
    vis, mir, lea = set_pool("VIS"), set_pool("MIR"), set_pool("LEA")
    canyon = Permanent(card=vis["Griffin Canyon"])
    griffin = Permanent(card=mir["Ekundu Griffin"])
    bystander = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[canyon, griffin, bystander],
            library=[lea["Island"]] * 6,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    for permanent in (canyon, griffin, bystander):
        permanent.metadata["summoning_sickness_turn"] = -99
    griffin.tapped = True
    return game, canyon, griffin, bystander


def test_griffin_canyons_second_ability_is_no_longer_hollow(set_pool):
    """"{T}: Untap target Griffin. If it's a creature, it gets +1/+1 until end
    of turn."

    The card reported **supported** on its mana ability alone while this line
    produced no instruction at all and the activation picker offered nothing —
    two independent failures on one line, and only ``--hollow-lines`` and
    ``picker_sweep.py`` could see either.

    The refusal was in the *lowering*: "if it's a creature" parses as the clause
    Track Down prints, which asks about a card an earlier sentence revealed, and
    with no reveal in front of it the condition rightly refused. The parse
    cannot tell the two apart — Prophecy prints "reveal the top card …, if it's
    a land" and this prints "untap target Griffin, if it's a creature" — so what
    separates them is the *producer*, which is only in view at lowering.
    """
    program = compile_card_oracle(set_pool("VIS")["Griffin Canyon"])
    untap = [
        ability for ability in program.activated_abilities
        if "untap" in ability.normalized_effect
    ]
    assert len(untap) == 1
    assert untap[0].supported, untap[0].normalized_effect
    assert untap[0].instruction is not None

    steps = untap[0].instruction.payload["steps"]
    assert steps[0].kind == "untap_target_permanent"
    assert steps[1].payload["condition"] == {
        "kind": "target_is_type", "card_types": ["creature"],
        "type_match": "any", "negated": False, "target": "permanent",
    }

    # The picker half. This was `None`, which is the exact value the client
    # tests to decide whether to ask for a target — the Roots class.
    assert derive_activation_spec(untap[0]) == {
        "kind": "creature", "filter": {"subtype_filter": "griffin"},
    }


def test_griffin_canyon_untaps_and_pumps_the_griffin_it_named(set_pool):
    """The Rock Hydra test: drive it and read the board."""
    game, _canyon, griffin, bystander = _g5_canyon(set_pool)

    result = game.activate_permanent_ability(
        0, "Griffin Canyon", ability_index=1,
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(griffin),
    )
    assert result.supported
    game.resolve_stack()

    assert not griffin.tapped
    assert (griffin.effective_power, griffin.effective_toughness) == (3, 3)
    # The bystander is not a Griffin and took nothing.
    assert (bystander.effective_power, bystander.effective_toughness) == (2, 2)


def test_the_canyons_mana_ability_still_works(set_pool):
    """The line that made the card read "supported" while the other did
    nothing. It is still the first ability and it still adds {C}."""
    program = compile_card_oracle(set_pool("VIS")["Griffin Canyon"])
    assert program.activated_abilities[0].instruction.payload == {
        "pips": (("C", 1),),
    }
