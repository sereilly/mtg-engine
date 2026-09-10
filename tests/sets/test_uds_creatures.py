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


# --- W1G3: being enchanted, and enchantments that become creatures ---

from engine import Game, PlayerState
from engine.auras import attach_aura, auras_attached_to, detach_aura
from engine.equipment import attach_equipment
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g3_vanilla(name: str, power: int, toughness: int) -> CardDefinition:
    """A creature with no text at all, for the boards these four need beside it."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g3_board(set_pool, subject_name, *, extras=()):
    """*subject_name* on seat 0's battlefield with *extras* beside it.

    Returns ``(game, subject, [extra permanents])``. The turn is started and the
    opening priority step closed, so the layer recompute has run once before any
    test reads a characteristic off the board.
    """
    subject = Permanent(card=set_pool("UDS")[subject_name])
    others = [Permanent(card=card) for card in extras]
    game = Game(players=[
        PlayerState(name="P0", battlefield=[subject, *others]),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    for permanent in (subject, *others):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, subject, others


def _g3_recompute(game):
    """Re-derive the two channels a conditional static contributes through."""
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()


# --- Fledgling Osprey ------------------------------------------------------
# "This creature has flying as long as it's enchanted." The condition is a
# state of the permanent itself, so it rides `conditional_static`'s `is_state`
# payload beside "tapped" and "attacking" rather than becoming a kind of its own.


def test_fledgling_osprey_has_no_flying_until_an_aura_arrives(set_pool, catalog_by_name):
    game, osprey, _ = _g3_board(set_pool, "Fledgling Osprey")

    assert not osprey.has_keyword("flying")

    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game.players[0].battlefield.append(aura)
    attach_aura(aura, osprey)
    _g3_recompute(game)

    assert osprey.has_keyword("flying")


def test_fledgling_osprey_loses_flying_when_the_aura_leaves(set_pool, catalog_by_name):
    """CR 611.3b: the condition is re-asked on every recompute, so there is no
    remembered grant to take back."""
    game, osprey, _ = _g3_board(set_pool, "Fledgling Osprey")
    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game.players[0].battlefield.append(aura)
    attach_aura(aura, osprey)
    _g3_recompute(game)
    assert osprey.has_keyword("flying")

    detach_aura(aura, osprey)
    _g3_recompute(game)

    assert not osprey.has_keyword("flying")


def test_fledgling_osprey_is_not_enchanted_by_an_equipment(set_pool, catalog_by_name):
    """CR 301.5f: an Equipment's host is *equipped*, not enchanted — and this
    engine keeps both attachments in one ``attached_auras`` record, so a
    truthiness test on that list would hand out flying for a Short Sword."""
    game, osprey, _ = _g3_board(set_pool, "Fledgling Osprey")
    sword = Permanent(card=catalog_by_name["Short Sword"])
    game.players[0].battlefield.append(sword)
    attach_equipment(game, sword, osprey)
    _g3_recompute(game)

    assert auras_attached_to(osprey) == [sword]
    assert not osprey.has_keyword("flying")


# --- Metathran Elite -------------------------------------------------------
# "This creature can't be blocked as long as it's enchanted." The same condition
# over the effect the block-legality check asks about, which is read when a
# block is declared rather than at a recompute.


def test_metathran_elite_can_be_blocked_while_unenchanted(set_pool):
    game, _elite, _ = _g3_board(set_pool, "Metathran Elite")
    blocker = Permanent(card=_g3_vanilla("Blocker", 2, 2))
    game.players[1].battlefield.append(blocker)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    assert game.declare_blockers(1, {0: 0})[0]


def test_metathran_elite_cannot_be_blocked_while_enchanted(set_pool, catalog_by_name):
    game, elite, _ = _g3_board(set_pool, "Metathran Elite")
    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game.players[0].battlefield.append(aura)
    attach_aura(aura, elite)
    _g3_recompute(game)
    blocker = Permanent(card=_g3_vanilla("Blocker", 2, 2))
    game.players[1].battlefield.append(blocker)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    assert not game.declare_blockers(1, {0: 0})[0]


# --- Thran Golem -----------------------------------------------------------
# "As long as this creature is enchanted, it gets +2/+2 and has flying, first
# strike, and trample." The leading word order, whose effect half wears a
# pronoun — and a three-keyword list, which is one comma more than the
# derivation table's keyword group used to admit.


def test_thran_golem_is_a_plain_3_3_while_unenchanted(set_pool):
    _game, golem, _ = _g3_board(set_pool, "Thran Golem")

    assert (golem.effective_power, golem.effective_toughness) == (3, 3)
    assert not any(
        golem.has_keyword(word) for word in ("flying", "first strike", "trample")
    )


def test_thran_golem_gains_the_whole_printed_list_when_enchanted(
    set_pool, catalog_by_name
):
    game, golem, _ = _g3_board(set_pool, "Thran Golem")
    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game.players[0].battlefield.append(aura)
    attach_aura(aura, golem)
    _g3_recompute(game)

    # +1/+2 from Holy Strength on top of the card's own +2/+2.
    assert (golem.effective_power, golem.effective_toughness) == (6, 7)
    assert all(
        golem.has_keyword(word) for word in ("flying", "first strike", "trample")
    )


def test_thran_golem_carries_every_keyword_it_prints(set_pool):
    """The payload rather than the board: a keyword list the pattern cannot read
    refuses the whole line, so a short list shows up as an unsupported card —
    but a list read and then *truncated* would not."""
    program = compile_card_oracle(set_pool("UDS")["Thran Golem"])

    (static,) = [i for i in program.instructions if i.kind == "conditional_static"]

    assert static.payload["keywords"] == ["flying", "first strike", "trample"]
    assert static.payload["condition"] == {"kind": "is_state", "state": "enchanted"}


# --- Iridescent Drake ------------------------------------------------------
# "When this creature enters, put target Aura card from a graveyard onto the
# battlefield under your control attached to this creature."


def test_iridescent_drake_returns_an_aura_already_attached(set_pool, catalog_by_name):
    game, _subject, _ = _g3_board(set_pool, "Metathran Elite")
    game.players[0].graveyard.append(catalog_by_name["Holy Strength"])
    drake = Permanent(card=set_pool("UDS")["Iridescent Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)

    resolve_stack(game)

    assert [aura.card.name for aura in auras_attached_to(drake)] == ["Holy Strength"]
    assert game.players[0].graveyard == []
    # 2/2 printed, +1/+2 from the Aura it brought back with it.
    assert (drake.effective_power, drake.effective_toughness) == (3, 4)


def test_iridescent_drake_leaves_an_aura_it_cannot_enchant_in_the_graveyard(
    set_pool, catalog_by_name
):
    """CR 303.4g: with no legal object to enchant, the Aura remains where it is.
    Evil Presence says "Enchant land", and a Drake is not one."""
    game, _subject, _ = _g3_board(set_pool, "Metathran Elite")
    game.players[0].graveyard.append(catalog_by_name["Evil Presence"])
    drake = Permanent(card=set_pool("UDS")["Iridescent Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)

    resolve_stack(game)

    assert auras_attached_to(drake) == []
    assert [card.name for card in game.players[0].graveyard] == ["Evil Presence"]


def test_iridescent_drake_ignores_a_creature_card_in_the_graveyard(set_pool):
    """The printed noun is "Aura card". A phrase read and then dropped would
    have reanimated the pile's creature, which is the only reanimation this
    lowering branch used to be able to spell."""
    game, _subject, _ = _g3_board(set_pool, "Metathran Elite")
    game.players[0].graveyard.append(_g3_vanilla("Dead Bear", 2, 2))
    drake = Permanent(card=set_pool("UDS")["Iridescent Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)

    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Dead Bear"]
    assert auras_attached_to(drake) == []
