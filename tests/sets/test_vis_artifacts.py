"""Per-card tests for Visions' artifacts (artifact creatures included).

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained blocks, each headed
``# --- W<wave>G<n>: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block and puts **its own imports at
the top of its own block**, not in a shared header. That is deliberate. The
mechanical merge for this file is "take ours, append the branch's block", and a
branch that added an import to a shared header loses it in exactly that move —
a ``NameError`` at collection, found only after the merge is committed. A
self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations


# --- W1G5: the Chimera cycle (CR 122.1, CR 611.2b) ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

#: The four Chimeras print one sentence with one keyword changed, which is the
#: whole reason they are one production rather than four hooks.
CHIMERAS = {
    "Brass-Talon Chimera": "first strike",
    "Iron-Heart Chimera": "vigilance",
    "Lead-Belly Chimera": "trample",
    "Tin-Wing Chimera": "flying",
}


def _g5_board(set_pool, *creatures):
    """A board of the named VIS/LEA cards on seat 0, all able to act."""
    vis = set_pool("VIS")
    lea = set_pool("LEA")
    permanents = [
        Permanent(card=(vis[name] if name in vis else lea[name]))
        for name in creatures
    ]
    game = Game(players=[
        PlayerState(name="P1", battlefield=permanents, library=[lea["Island"]] * 8),
        PlayerState(name="P2", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    for permanent in permanents:
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanents


@pytest.mark.parametrize("name,keyword", sorted(CHIMERAS.items()))
def test_every_chimera_compiles_its_sacrifice_ability(set_pool, name, keyword):
    """One sentence with one word changed, so the fourth one comes for free.

    The refusal was a *lowering* one and not a parse one: the placement branch
    in ``lowering/counters.py`` listed the fields it would honour and left
    ``subtypes`` off, while ``to_payload`` emits it as ``subtype_filter`` and
    ``permanent_matches_filter`` tests it — a false refusal of a phrase the
    payload carries perfectly well.
    """
    program = compile_card_oracle(set_pool("VIS")[name])
    assert program.supported, program.reason

    sacrifices = [
        ability for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(sacrifices) == 1
    steps = sacrifices[0].instruction.payload["steps"]
    assert steps[0].kind == "add_counter_to_target"
    assert steps[0].payload["counter"] == "+2/+2"
    # The printed creature type survives as payload, which is what makes this a
    # production rather than four hooks: the word is data.
    for step in steps:
        assert step.payload["targets"]["filter"] == {
            "type_filter": "creature", "subtype_filter": "chimera",
        }
    # The keyword rides the payload where the pool has a generic grant, and
    # rides the *kind* where it has a dedicated one — flying is the engine's
    # one keyword with its own handler.
    assert keyword in str(steps[1].payload) or keyword in steps[1].kind


@pytest.mark.parametrize("name,keyword", sorted(CHIMERAS.items()))
def test_a_chimera_picker_offers_only_chimeras(set_pool, name, keyword):
    """The activation picker and the resolution have to agree on the noun
    phrase, or the player announces a target the effect then declines."""
    program = compile_card_oracle(set_pool("VIS")[name])
    ability = next(
        a for a in program.activated_abilities if a.cost.sacrifice_self
    )
    assert derive_activation_spec(ability) == {
        "kind": "creature", "filter": {"subtype_filter": "chimera"},
    }


def test_a_chimera_pumps_and_arms_another_chimera_indefinitely(set_pool):
    """The Rock Hydra test. Brass-Talon sacrifices itself, Tin-Wing takes the
    +2/+2 counter and first strike, and the grant survives the turn because
    "(This effect lasts indefinitely.)" is a *reminder* (CR 207.2) of what a
    continuous effect with no printed duration already means (CR 611.2b) —
    which is why nothing was built for it: the lexer strips the parenthetical
    and ``Duration()`` lowers to ``duration: None``.
    """
    game, (brass, tin, bear) = _g5_board(
        set_pool, "Brass-Talon Chimera", "Tin-Wing Chimera", "Grizzly Bears",
    )

    result = game.activate_permanent_ability(
        0, "Brass-Talon Chimera",
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(tin),
    )
    assert result.supported
    game.resolve_stack()

    assert (tin.effective_power, tin.effective_toughness) == (4, 4)
    assert tin.has_keyword("first strike")
    # The bystander took nothing: the counter and the keyword both read the
    # printed noun phrase, not the first creature a scan reaches.
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert not bear.has_keyword("first strike")
    assert not game.is_on_battlefield(brass)

    # Indefinitely: two turn boundaries later it is still a 4/4 first-striker.
    game.start_turn(1)
    game.resolve_stack()
    game.start_turn(0)
    game.resolve_stack()
    assert (tin.effective_power, tin.effective_toughness) == (4, 4)
    assert tin.has_keyword("first strike")


def test_a_chimera_refuses_to_activate_with_no_chimera_to_aim_at(set_pool):
    """CR 602.2b/601.2c: a mandatory object target that cannot be filled is
    refused with nothing paid, rather than activated onto a bystander. Written
    as the refusal half of the production, because a placement that admitted
    every creature would pass every positive case above."""
    game, (brass, bear) = _g5_board(
        set_pool, "Brass-Talon Chimera", "Grizzly Bears",
    )

    result = game.activate_permanent_ability(
        0, "Brass-Talon Chimera",
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(bear),
    )

    assert not result.supported
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert not bear.has_keyword("first strike")
    # Nothing was paid: the Chimera is still on the battlefield.
    assert game.is_on_battlefield(brass)


def test_the_counter_placement_still_refuses_a_narrowing_it_cannot_test(set_pool):
    """The allow-set was widened by exactly two fields, so a phrase outside it
    still refuses rather than being silently dropped — which is the direction
    ``_restrictions_beyond`` exists to fail in."""
    from engine.grammar import lower_ability, parse_line
    from engine.grammar.errors import LoweringError

    with pytest.raises(LoweringError, match="lands on a creature"):
        lower_ability(parse_line(
            "put a +2/+2 counter on target tapped chimera creature"
        ))


# --- W1G5: a look, a price and the card it turned up (Wand of Denial) ---

from engine.oracle import compile_card_oracle as _g5w_compile


def test_wand_of_denial_bins_only_a_nonland_and_only_if_paid_for(set_pool):
    """"{T}: Look at the top card of target player's library. If it's a nonland
    card, you may pay 2 life. If you do, put it into that player's graveyard."

    Four gaps in one line, three of them in the *parse*: "if it's a **nonland**
    card" is Wand of Ith's "if it isn't a land card" with the negation inside
    the noun phrase, and only one spelling was read; "you may pay **2 life**"
    is a price with no mana in it, which the mana reader refuses outright; and
    "put **it** into that player's graveyard" names the card the look turned up,
    where the production beside it moves the ability's own source. The fourth is
    that the look recorded nothing, so even a parsed pronoun had no producer.
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = _g5w_compile(vis["Wand of Denial"])
    assert program.supported, program.reason
    steps = program.activated_abilities[0].instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "look_at_target_library_top", "if_then",
    ]
    assert steps[1].payload["condition"]["excluded_types"] == ["land"]
    offer = steps[1].payload["then"][0]
    assert offer.kind == "may" and offer.payload["life_cost"] == 2
    assert offer.payload["then"][0].kind == "bin_revealed_card"

    def play(top, *, pay):
        wand = Permanent(card=vis["Wand of Denial"])
        game = Game(players=[
            PlayerState(name="P1", battlefield=[wand], library=[lea["Island"]] * 4),
            PlayerState(name="P2", library=[top, lea["Forest"], lea["Swamp"]]),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game._settle()
        wand.metadata["summoning_sickness_turn"] = -99
        assert game.activate_permanent_ability(
            0, "Wand of Denial", target_player_index=1,
        ).supported
        game.resolve_stack()
        for _ in range(4):
            if not game.pending_choices:
                break
            pending = game.pending_choices[0]
            if pending.kind == "reorder_library":
                game.confirm_reorder_library(
                    0, list(range(pending.data["top_count"])), False,
                )
            else:
                game.resolve_pending_choice(pending.kind, 0, accept=pay)
            game.resolve_stack()
        return game

    paid = play(lea["Black Lotus"], pay=True)
    assert paid.players[0].life == 18
    assert [c.name for c in paid.players[1].graveyard] == ["Black Lotus"]

    declined = play(lea["Black Lotus"], pay=False)
    assert declined.players[0].life == 20
    assert declined.players[1].graveyard == []

    # A land on top is not offered at all: the price is behind the printed
    # exclusion, not beside it.
    land = play(lea["Mountain"], pay=True)
    assert land.players[0].life == 20
    assert land.players[1].graveyard == []
    assert land.players[1].library[0].name == "Mountain"
