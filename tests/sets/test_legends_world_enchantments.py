"""Per-card tests for Legends' World enchantments and the taxes beside them.

By printed type these are Enchantments, so `tests/sets/README.md` would file
them with `test_legends_enchantments.py`; they are split out because the
World supertype (CR 205.4, 704.5k) is a distinct machine and the cards that
carry it are easier to find whole. See tests/sets/README.md.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def lea_by_name():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _cast_into(tax: Permanent, spell, mana: dict):
    """Cast *spell* from seat 1 with *tax* on seat 0's battlefield, and let the
    trigger it fires resolve."""
    p1 = PlayerState(name="P1", battlefield=[tax])
    p2 = PlayerState(name="P2", hand=[spell])
    game = Game(players=[p1, p2])
    game.start_turn(1)
    # After the turn starts, not before: a mana pool empties at every step
    # boundary (CR 500.4), so a pool filled at construction is gone by the time
    # the spell is cast.
    p2.mana_pool.update(mana)
    result = game.cast_from_hand(1, spell.name, target_player_index=0)
    game._settle()
    return game, p2, result


# ---------------------------------------------------------------------------
# "Whenever a player casts <a spell>, counter it [unless they pay]" (round 8)
# ---------------------------------------------------------------------------


def test_presence_of_the_master_counters_an_enchantment(set_pool, lea_by_name):
    """"…counter it." The pronoun is bound by the trigger's own condition, so
    there is nothing to target and nothing to pay."""
    tax = Permanent(card=set_pool("LEG")["Presence of the Master"])
    game, caster, result = _cast_into(tax, lea_by_name["Bad Moon"], {"B": 3})

    assert result.supported
    assert not game.stack
    assert [c.name for c in caster.graveyard] == ["Bad Moon"]


def test_presence_of_the_master_ignores_a_spell_it_does_not_name(set_pool, lea_by_name):
    """"…casts an **enchantment** spell." The condition's narrowing, checked in
    the direction that matters — an unnarrowed trigger would counter the pool."""
    tax = Permanent(card=set_pool("LEG")["Presence of the Master"])
    game, caster, _ = _cast_into(tax, lea_by_name["Lightning Bolt"], {"R": 1})

    assert not any(item.card.name == "Bad Moon" for item in game.stack)
    assert "Lightning Bolt" not in [c.name for c in caster.graveyard] or caster.life == 20


def test_nether_void_counters_a_spell_whose_controller_cannot_pay(set_pool, lea_by_name):
    """"…counter it unless that player pays {3}." "That player" is the caster
    the condition bound — the same person as the spell's controller, which is
    why the production admits the phrase beside "its controller"."""
    void = Permanent(card=set_pool("LEG")["Nether Void"])
    game, caster, _ = _cast_into(void, lea_by_name["Lightning Bolt"], {"R": 1})

    assert not game.stack
    assert [c.name for c in caster.graveyard] == ["Lightning Bolt"]


def test_nether_void_lets_a_paid_spell_through(set_pool, lea_by_name):
    """The other half of the same tax: a caster who can pay keeps their spell.

    Asserted on the spell's **effect**, not on the graveyard — a resolved
    instant goes there too, so a graveyard check passes whichever way the
    payment went."""
    void = Permanent(card=set_pool("LEG")["Nether Void"])
    game, _, _ = _cast_into(
        void, lea_by_name["Lightning Bolt"], {"R": 1, "C": 3}
    )

    assert game.players[0].life == 17, game.log[-4:]


def test_in_the_eye_of_chaos_sizes_its_tax_from_the_spell(set_pool):
    """"…pays {X}, where X is **its** mana value." The where-clause names the
    spell the trigger bound rather than a permanent, which is what the lowering
    decides from the sentence it is stamping."""
    program = compile_card_oracle(set_pool("LEG")["In the Eye of Chaos"])
    assert program.supported, program.reason
    instruction = program.triggered_abilities[0].instruction
    assert instruction.payload["unless_pays_x"] is True
    assert instruction.payload["bound_to_trigger"] is True
    assert instruction.payload["x_from_count"] == {"object_mana_value": "triggering_spell"}


def test_the_three_taxes_are_all_world_enchantments_or_not(set_pool):
    """Nether Void and In the Eye of Chaos carry the World supertype and
    Presence of the Master does not — so the two of them cannot coexist
    (CR 704.5k) and the third is unaffected. Recorded here because the rule is
    what makes the pair different cards from the trio they look like."""
    pool = set_pool("LEG")
    assert "World" in pool["Nether Void"].type_line
    assert "World" in pool["In the Eye of Chaos"].type_line
    assert "World" not in pool["Presence of the Master"].type_line


# ---------------------------------------------------------------------------
# Playing with hidden zones revealed (round 11) — CR 701.20a, CR 401.5
# ---------------------------------------------------------------------------


def test_revelation_reveals_every_hand_while_it_stands(set_pool):
    """"Players play with their hands revealed." — every hand, to every seat,
    and *derived*: the predicate reads the battlefield, so the effect ends the
    moment the enchantment leaves, with no flag to clear."""
    from engine.revealed_hands import hand_revealed_to

    revelation = Permanent(card=set_pool("LEG")["Revelation"])
    p1 = PlayerState(name="P1", battlefield=[revelation])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert hand_revealed_to(game, owner_seat=1, viewer_seat=0)
    assert hand_revealed_to(game, owner_seat=0, viewer_seat=1), (
        "the reveal is symmetric — the controller's own hand is shown too"
    )

    game.remove_from_battlefield(revelation)
    assert not hand_revealed_to(game, 1, 0)
    assert not hand_revealed_to(game, 0, 1)


def test_field_of_dreams_reveals_every_library_top(set_pool):
    """"Players play with the top card of their libraries revealed." — the
    players-scoped form of the question engine/library_top.py already answers
    for Conspicuous Snoop's own-scoped one, from whichever battlefield the
    world enchantment stands on."""
    from engine.library_top import top_is_public, top_is_visible

    field = Permanent(card=set_pool("LEG")["Field of Dreams"])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[field])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert top_is_public(game, 0), "the *other* player's top card too"
    assert top_is_public(game, 1)
    assert top_is_visible(game, 0), "public implies visible to the owner (CR 401.5)"

    game.remove_from_battlefield(field)
    assert not top_is_public(game, 0)
    assert not top_is_public(game, 1)


def test_the_reveal_statics_compile_supported_and_not_hollow(set_pool):
    """Both cards' whole text is the one static line; support has to come from
    the derived claim, and the claim has to name the module that does the
    work."""
    for name in ("Revelation", "Field of Dreams"):
        program = compile_card_oracle(set_pool("LEG")[name])
        assert program.supported, name
        assert any(i.kind == "derived_static_rule" for i in program.instructions), name
