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


# --- W1G4: eight new trigger conditions and what announces them ---
import pytest

from engine import Game
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g4_card(name: str, type_line: str = "Creature - Test", power="1", toughness="1",
             oracle_text: str = "", colors=()) -> CardDefinition:
    """A plain fixture card, with a colour and a printed type line together."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=colors, color_identity=colors,
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": power, "toughness": toughness},
    )


def _g4_duel(library: int = 9) -> Game:
    """Two seats with stocked libraries and mana enforcement off."""
    seats = [
        PlayerState(name=name,
                    library=[_g4_card(f"{name}-lib{i}") for i in range(library)],
                    hand=[], battlefield=[])
        for name in ("A", "B")
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def _g4_settle(game: Game, *, accept: bool = True) -> None:
    """Resolve the stack and answer every optional offer it queues.

    A "may" is answered by a prompt on the pending-choice queue (CR 603.5: the
    choice is made as the ability resolves), and answering one can arm another —
    Rayne's second sentence is a second offer behind the first. So this
    alternates rather than draining once, and it is bounded rather than a
    ``while``, which is the hazard ``resolve_stack`` documents.
    """
    for _ in range(8):
        resolve_stack(game)
        owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
        if not owed:
            return
        for choice in owed:
            game.resolve_pending_choice(
                choice.kind, choice.player_index, accept=accept
            )


def _g4_uds(set_pool, name: str) -> CardDefinition:
    return set_pool("UDS")[name]


@pytest.mark.parametrize("name", [
    "Goblin Marshal", "Hunting Moa", "Phyrexian Negator",
    "Telepathic Spies", "Rayne, Academy Chancellor",
])
def test_w1g4_creatures_compile_supported(set_pool, name):
    assert compile_card_oracle(_g4_uds(set_pool, name)).supported


def test_goblin_marshal_makes_goblins_when_it_enters(set_pool):
    game = _g4_duel()
    marshal = Permanent(card=_g4_uds(set_pool, "Goblin Marshal"))
    game._put_permanent_onto_battlefield(0, marshal, None)
    _g4_settle(game)
    tokens = [p for p in list(game.controlled_by(0)) if p.card.name == "Goblin Token"]
    assert len(tokens) == 2


def test_goblin_marshal_makes_goblins_when_it_dies(set_pool):
    """The **other** half of one printed condition (CR 603.1b).

    The entry half is carried out inline and this half goes on the stack
    (CR 603.3), which is why ``enters_or_dies`` is one kind named at two fire
    sites rather than a compiler alias for either one.
    """
    game = _g4_duel()
    marshal = Permanent(card=_g4_uds(set_pool, "Goblin Marshal"))
    game.players[0].battlefield.append(marshal)
    game._sync_control()
    game._permanent_to_graveyard(game.players[0], marshal)
    _g4_settle(game)
    tokens = [p for p in list(game.controlled_by(0)) if p.card.name == "Goblin Token"]
    assert len(tokens) == 2


@pytest.mark.parametrize("half", ["enters", "dies"])
def test_hunting_moa_counters_a_creature_on_both_halves(set_pool, half):
    game = _g4_duel()
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    moa = Permanent(card=_g4_uds(set_pool, "Hunting Moa"))
    if half == "enters":
        game._put_permanent_onto_battlefield(0, moa, 0)
    else:
        game.players[0].battlefield.append(moa)
        game._sync_control()
        game._permanent_to_graveyard(game.players[0], moa)
    _g4_settle(game)
    assert bear.metadata.get("plus_counters") == 1


@pytest.mark.parametrize("dealt,expected", [(1, 1), (2, 2), (3, 3)])
def test_phyrexian_negator_sacrifices_that_many(set_pool, dealt, expected):
    """"…sacrifice **that many** permanents" is the damage the event carried.

    Parametrized over three amounts because the whole claim is that the number
    is the event's rather than a printed one: a lowering that emitted a fixed
    count would pass at exactly one of these.
    """
    game = _g4_duel()
    negator = Permanent(card=_g4_uds(set_pool, "Phyrexian Negator"))
    game.players[0].battlefield.append(negator)
    for index in range(5):
        game.players[0].battlefield.append(Permanent(card=_g4_card(f"G4 Chaff{index}")))
    game._sync_control()
    before = len(list(game.controlled_by(0)))
    game._fire_dealt_damage_triggers(negator, dealt)
    for _ in range(10):
        resolve_stack(game)
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    assert before - len(list(game.controlled_by(0))) == expected


def test_telepathic_spies_reads_an_opponents_hand(set_pool):
    game = _g4_duel()
    game.players[1].hand.extend([_g4_card("G4 Held1"), _g4_card("G4 Held2")])
    spies = Permanent(card=_g4_uds(set_pool, "Telepathic Spies"))
    game._put_permanent_onto_battlefield(0, spies, 1)
    _g4_settle(game)
    reveal = next(c for c in game.pending_choices if c.kind == "hand_reveal")
    assert reveal.player_index == 0
    assert reveal.data["target_index"] == 1
    assert sorted(reveal.data["card_names"]) == ["G4 Held1", "G4 Held2"]


def test_telepathic_spies_carries_the_opponent_only_narrowing(set_pool):
    """CR 115.4 through the payload: "target **opponent**" carries
    ``opponents_only``, and the picker is what refuses the caster's own seat.

    The lowering that admits the word is only correct because the flag survives
    into the payload — a reading that dropped it would offer the caster their
    own hand, which is the failure the old refusal stood in for.
    """
    program = compile_card_oracle(_g4_uds(set_pool, "Telepathic Spies"))
    instruction = program.triggered_abilities[0].instruction
    assert instruction.payload["targets"]["opponents_only"] is True


def _g4_rayne_board(set_pool, *, enchanted: bool = False):
    game = _g4_duel()
    rayne = Permanent(card=_g4_uds(set_pool, "Rayne, Academy Chancellor"))
    game.players[0].battlefield.append(rayne)
    if enchanted:
        aura = Permanent(card=_g4_card("G4 Aura", "Enchantment - Aura",
                                       oracle_text="Enchant creature"))
        game.players[0].battlefield.append(aura)
        attach_aura(aura, rayne)
    game._sync_control()
    return game, rayne


_G4_BOLT = "G4 Bolt deals 3 damage to target player."
_G4_ZAP = "G4 Zap deals 2 damage to target creature."


def test_rayne_draws_when_an_opponent_targets_you(set_pool):
    """The **player** half of CR 603.2's "becomes the target of".

    Nothing announced a targeted seat before this card: the targeting
    announcement looped permanents alone, so the condition could compile
    perfectly and never fire on half of what it names.
    """
    game, _rayne = _g4_rayne_board(set_pool)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 1


def test_rayne_draws_when_an_opponent_targets_your_permanent(set_pool):
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    game.players[1].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        1, "G4 Zap", target_player_index=0,
        target_permanent_index=game.players[0].battlefield.index(bear),
    )
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 1


def test_rayne_ignores_a_spell_its_own_controller_cast(set_pool):
    """"…an **opponent** controls" (CR 109.5). Dropped, Rayne would draw off
    every spell its controller aimed at their own board."""
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    game.players[0].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        0, "G4 Zap", target_player_index=0,
        target_permanent_index=game.players[0].battlefield.index(bear),
    )
    _g4_settle(game)
    # One card left the hand to be cast and none was drawn.
    assert len(game.players[0].hand) == before - 1


def test_rayne_ignores_an_opponent_targeting_their_own_permanent(set_pool):
    """"…**you or a permanent you control**". The seat narrowing is on the
    *targeted* object, not on the spell alone."""
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[1].battlefield.append(bear)
    game._sync_control()
    game.players[1].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        1, "G4 Zap", target_player_index=1,
        target_permanent_index=game.players[1].battlefield.index(bear),
    )
    _g4_settle(game)
    assert len(game.players[0].hand) == before


def test_rayne_draws_a_second_card_while_enchanted(set_pool):
    """CR 303.4b: the permanent an Aura is attached to is *enchanted*."""
    game, _rayne = _g4_rayne_board(set_pool, enchanted=True)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 2


def test_rayne_draws_nothing_when_the_offer_is_declined(set_pool):
    """CR 603.5: the ability triggers and goes on the stack either way; the
    choice belongs to the resolution."""
    game, _rayne = _g4_rayne_board(set_pool, enchanted=True)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game, accept=False)
    assert len(game.players[0].hand) == before


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g5_creature_combat(blocker: Permanent, attackers: list[Permanent]) -> Game:
    """A combat with *attackers* declared and *blocker* facing them all.

    Stops at the declare-blockers step so the caller can make the declaration
    itself, which is the whole subject of this block's one creature.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers)),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, list(range(len(attackers))), 1)
    assert declared, why
    game.advance_combat_phase()
    return game


def test_wall_of_glare_blocks_three_attackers_at_once(set_pool):
    """"This creature can block any number of creatures."

    CR 509.1a gives a blocker **one** attacker unless something says otherwise,
    and the ceiling that lifts it was a substring scan for the *other* printed
    spelling ("can block an additional creature"): read against "any number" it
    answers zero, so the card would have been admitted blocking exactly one.

    Three attackers rather than two, so the reading cannot be an off-by-one:
    a grant of "one additional" would take two and refuse the third.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Wall of Glare"])
    assert program.supported, program.reason

    bear = set_pool("LEA")["Grizzly Bears"]
    wall = Permanent(card=pool["Wall of Glare"])
    game = _g5_creature_combat(wall, [Permanent(card=bear) for _ in range(3)])
    assert game._max_blocks_for(wall) >= 3, game._max_blocks_for(wall)

    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why


def test_an_ordinary_wall_still_blocks_only_one(set_pool):
    """The ceiling stays where CR 509.1a puts it for a creature printing none.

    The direction a table like this fails in is upward — a claim keyed loosely
    enough to match Wall of Glare would match every Wall in the pool — so the
    refusal is asserted beside the permission rather than assumed.
    """
    lea = set_pool("LEA")
    wall = Permanent(card=lea["Wall of Wood"])
    game = _g5_creature_combat(wall, [Permanent(card=lea["Grizzly Bears"])] * 2)
    assert game._max_blocks_for(wall) == 1

    blocked, why = game.declare_blockers(1, {0: [0, 1]})
    assert not blocked, why


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
