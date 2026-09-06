"""Tempest sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W2G5: the several-target destroy narrowed by a colour exclusion --------

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w2g5_duel(set_pool, spell, victims):
    """*spell* in the caster's hand, *victims* (TMP card names) on P2's board.

    Mana costs off: the point of every test below is the *target* gate, and X
    is announced through ``x_value`` rather than paid for.
    """
    pool = set_pool("TMP")
    lands = set_pool("LEA")
    p1 = PlayerState(
        name="P1", hand=[pool[spell]], life=20, library=[lands["Forest"]] * 12,
    )
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=pool[name]) for name in victims],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p1, p2


def test_w2g5_dregs_of_sorrow_destroys_x_nonblack_creatures_and_draws_x(set_pool):
    """"Destroy X target nonblack creatures. Draw X cards."

    The refusal was exact and the brief's diagnosis of it was not: the engine
    said ``the several-target destroy cannot narrow by: excluded_colors`` and
    the missing piece was **only** the whitelist in the lowering. The matcher,
    the payload key and the one-key demonstration in
    ``tests/engine/test_subject_filters.py`` all already existed.
    """
    game, caster, defender = _w2g5_duel(
        set_pool, "Dregs of Sorrow",
        ["Horned Turtle", "Trained Armodon", "Blood Pet"],
    )

    result = game.cast_from_hand(
        0, "Dregs of Sorrow", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert [p.card.name for p in defender.battlefield] == ["Blood Pet"]
    assert sorted(c.name for c in defender.graveyard) == [
        "Horned Turtle", "Trained Armodon",
    ]
    # X sizes both sentences off the one announcement.
    assert len(caster.hand) == 2


def test_w2g5_dregs_of_sorrow_refuses_a_black_creature_at_announcement(set_pool):
    """CR 601.2c: the named target must be a legal one, and the refusal lands
    before anything is spent.

    This is the half the lowering change alone did **not** buy. A card whose
    second printed sentence makes its program a ``sequence`` reaches no arm of
    ``_validate_cast_targets`` — that is the documented reason
    ``cast_target_refusal`` exists — and that gate reads the *spec*, where the
    colour exclusion was not carried. So the announcement was accepted and the
    resolution silently dropped the slot: fewer creatures destroyed than the X
    that was paid for, refused nowhere.
    """
    game, _caster, defender = _w2g5_duel(
        set_pool, "Dregs of Sorrow", ["Horned Turtle", "Blood Pet"],
    )

    refused = game.cast_from_hand(
        0, "Dregs of Sorrow", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
    )

    assert not refused.supported, "Blood Pet is black (CR 202.2)"
    assert len(defender.battlefield) == 2, "nothing resolves off a refused cast"


def test_w2g5_dregs_of_sorrow_offers_only_the_nonblack_creatures(set_pool):
    """The picker and the gate are one reading — the spec the gate consults is
    the spec the client is handed, so a black creature is never offered."""
    card = set_pool("TMP")["Dregs of Sorrow"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {
        "kind": "creature",
        "x_targets": True,
        "filter": {"exclude_colors": ["B"]},
    }


# --- W2G5: a sweep narrowed by attachment state ----------------------------


def test_w2g5_winds_of_rath_spares_only_the_enchanted(set_pool):
    """"Destroy all creatures that aren't enchanted. They can't be regenerated."

    Two things had to be true and only one was. ``ObjectFilter.not_enchanted``
    has existed since Time Elemental — but only in the **singular** spelling
    ("that isn't enchanted"), so the same restriction on a plural head noun was
    an unread relative clause and the whole line fell. The number of the verb
    is agreement with the noun and says nothing about the restriction, so the
    two spellings are now one branch.

    Driven through a game rather than asserted off the program: a sweep that
    reported the right payload and swept the board anyway is the failure this
    card could have, and only a board shows it. The Aura itself survives —
    it is not a creature — and the regenerator does not, which is the second
    printed sentence doing its work.
    """
    pool = set_pool("TMP")
    bare = Permanent(card=pool["Horned Turtle"])
    enchanted = Permanent(card=pool["Trained Armodon"])
    regenerator = Permanent(card=set_pool("LEA")["Drudge Skeletons"])
    aura = Permanent(card=pool["Giant Strength"])
    caster = PlayerState(name="P1", hand=[pool["Winds of Rath"]], life=20)
    defender = PlayerState(
        name="P2", life=20,
        battlefield=[bare, enchanted, regenerator, aura],
    )
    game = Game(players=[caster, defender])
    game.enforce_mana_costs = False
    game._sync_control()

    from engine.auras import attach_aura

    attach_aura(aura, enchanted)
    regenerator.regeneration_shield = 1

    result = game.cast_from_hand(0, "Winds of Rath")
    game.resolve_stack()

    assert result.supported, result.details
    assert sorted(p.card.name for p in defender.battlefield) == [
        "Giant Strength", "Trained Armodon",
    ]
    assert sorted(c.name for c in defender.graveyard) == [
        "Drudge Skeletons", "Horned Turtle",
    ], "the shield does not save a creature from a no-regeneration sweep"


def test_w2g5_winds_of_rath_reads_the_plural_clause_as_the_singular_one(set_pool):
    """The payload, so the *equality* of the two spellings is asserted and not
    only the behaviour above. Time Elemental's singular clause and this card's
    plural one must reduce to the same key, or the pool has two questions where
    it printed one."""
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability

    plural = lower_ability(parse_line("Destroy all creatures that aren't enchanted."))
    assert plural[0].payload == {"type_filter": "creature", "not_enchanted": True}

    singular = lower_ability(
        parse_line("Destroy target permanent that isn't enchanted.")
    )
    assert singular[0].payload["not_enchanted"] is True

    card = set_pool("TMP")["Winds of Rath"]
    program = compile_card_oracle(card)
    assert program.supported
    assert program.instructions[0].payload == {
        "type_filter": "creature",
        "not_enchanted": True,
        "bypass_regeneration": True,
    }
