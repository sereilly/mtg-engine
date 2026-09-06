"""Tempest instants.

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


# --- W1G1: shadow (CR 702.28) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_cast(spell, caster_board, opponent_board, *, target_index):
    """Cast *spell* from hand at ``caster_board[target_index]`` and resolve it."""
    p0 = PlayerState(
        name="P0",
        battlefield=[_nosick(Permanent(card=c)) for c in caster_board],
        life=20, hand=[spell], library=[spell] * 3,
    )
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=c)) for c in opponent_board],
        life=20,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.cast_from_hand(
        0, spell.name, target_permanent_index=target_index, target_player_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    return game, p0, p1


def test_w1g1_shadow_rift_grants_shadow_and_draws(set_pool):
    """"Target creature gains shadow until end of turn. Draw a card."

    Shadow Rift **compiled and reported supported before this round**, on its
    second sentence alone: the grant produced no instruction at all, so the card
    drew a card and did nothing else, and `picker_sweep` reported it as the
    Roots class because a program with no targeting instruction derives no cast
    picker. That was one failure with two symptoms, not two failures — the
    picker finding cleared the moment the grant lowered.

    Driven through a game rather than asserted off the program for that exact
    reason: the compiled instruction is what was missing, and asserting its
    presence is a weaker claim than asserting the block it changes.
    """
    tmp = set_pool("TMP")
    rift = tmp["Shadow Rift"]
    assert [i.kind for i in compile_card_oracle(rift).instructions] == [
        "grant_target_keyword_until_eot", "draw_controller_cards",
    ]

    game, p0, p1 = _w1g1_cast(
        rift, [tmp["Trained Armodon"]], [tmp["Trained Armodon"]], target_index=0
    )
    attacker = p0.battlefield[0]
    blocker = p1.battlefield[0]

    assert game._has_keyword(attacker, "shadow")
    assert not game._can_block_attacker(blocker, attacker)
    assert len(p0.hand) == 1, "the second sentence still draws"


def test_w1g1_reality_anchor_takes_shadow_away(set_pool):
    """"Target creature loses shadow until end of turn. Draw a card."

    The mirror of Shadow Rift and the same pre-round defect: supported on the
    draw, the removal producing nothing. Aimed at a *printed* shadow creature,
    because that is the use the card is printed for — the Soltari attacker is
    made blockable, which is a change no assertion about the instruction list
    would have caught if the layer-6 removal had failed to reach the block gate.
    """
    tmp = set_pool("TMP")
    anchor = tmp["Reality Anchor"]
    assert [i.kind for i in compile_card_oracle(anchor).instructions] == [
        "remove_target_keyword_until_eot", "draw_controller_cards",
    ]

    game, p0, p1 = _w1g1_cast(
        anchor, [tmp["Soltari Foot Soldier"]], [tmp["Trained Armodon"]],
        target_index=0,
    )
    attacker = p0.battlefield[0]
    blocker = p1.battlefield[0]

    assert not game._has_keyword(attacker, "shadow")
    assert game._can_block_attacker(blocker, attacker)
    assert len(p0.hand) == 1


def test_w1g1_reality_anchor_also_frees_a_shadow_creature_to_block(set_pool):
    """The *other* half of what Reality Anchor does, which is the half CR
    702.28b's second prohibition creates.

    Losing shadow does not only make a creature blockable; it makes it able to
    block. An engine that implemented shadow as one-way evasion would pass the
    test above and fail this one, and the card would be doing half its job with
    nothing red.
    """
    tmp = set_pool("TMP")
    game, p0, p1 = _w1g1_cast(
        tmp["Reality Anchor"], [tmp["Soltari Foot Soldier"]],
        [tmp["Trained Armodon"]], target_index=0,
    )
    soltari = p0.battlefield[0]
    ordinary_attacker = p1.battlefield[0]

    assert game._can_block_attacker(soltari, ordinary_attacker)


# --- W1G1: the removal handler's missing noun phrase ---


def test_w1g1_reality_anchor_will_not_strip_a_noncreature(set_pool):
    """Found by driving eight AI games, not by any census.

    `remove_target_keyword_until_eot` resolved with `predicate=lambda p: True`
    — "the damage target may be a planeswalker, so no creature predicate" — and
    read the printed noun phrase not at all. So when the AI named a *player*
    where the spell wants a creature, the fallback scan took whatever permanent
    it reached first and **Reality Anchor stripped shadow from a Circle of
    Protection**. Its grant twin was fixed for exactly this a set earlier and
    has `granted_target_legal`; the removal twin kept its own reading, which is
    the "two handlers for one printed sentence" shape that helper's docstring
    is about.

    Two rigs, because the fallback scan is legitimate and only its *blindness*
    was the bug: with a legal creature on the board the scan should find it,
    and with none it should find nothing rather than settle for an enchantment.
    The illegal permanent is placed **first** in both, so a scan that ignores
    the phrase reaches it before anything else.
    """
    tmp = set_pool("TMP")

    def cast_with_no_permanent_named(battlefield):
        p0 = PlayerState(
            name="P0",
            battlefield=[_nosick(Permanent(card=tmp[name])) for name in battlefield],
            life=20, hand=[tmp["Reality Anchor"]],
            library=[tmp["Trained Armodon"]] * 4,
        )
        game = Game(players=[p0, PlayerState(name="P1", life=20)])
        game.enforce_mana_costs = False
        game._sync_control()
        # The shape the AI produced: a player named, no permanent.
        game.cast_from_hand(0, "Reality Anchor", target_player_index=0)
        while game.stack:
            game.resolve_top_of_stack()
        return game, p0

    # No creature at all: the enchantment must not be taken as a substitute.
    game, _ = cast_with_no_permanent_named(["Circle of Protection: Shadow"])
    assert any("no valid target to strip" in line for line in game.log)
    assert not any("Circle of Protection: Shadow loses" in line for line in game.log)

    # A creature behind it: the scan finds the creature, not the enchantment.
    game, p0 = cast_with_no_permanent_named(
        ["Circle of Protection: Shadow", "Soltari Foot Soldier"]
    )
    soltari = p0.battlefield[1]
    assert not game._has_keyword(soltari, "shadow")
    assert any("Soltari Foot Soldier loses shadow" in line for line in game.log)


# --- W1G2: buyback (CR 702.27) ---
import pytest

from engine import Game, PlayerState
from engine.cast_costs import (BUYBACK_RULES_TEXT, additional_costs,
                               buyback_cost, buyback_paid, expand_buyback_line,
                               is_buyback_line, unread_cost_sentence)
from engine.models import Permanent
from engine.oracle import compile_card_oracle, expand_card_lines


def _g2_rig(set_pool, card_name, **pool):
    """One seat holding *card_name* with *pool* already in its mana pool.

    The pool rather than lands, because casting spends the pool (CR 106.4) and
    a rig that tapped lands would be exercising the mana planner instead.
    """
    caster = PlayerState(name="A", hand=[set_pool("TMP")[card_name]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    for symbol, count in pool.items():
        caster.mana_pool[symbol] = count
    game._settle()
    return game, caster


def test_g2_every_buyback_line_in_the_set_is_rewritten_into_its_cost(set_cards):
    """CR 702.27a's first static ability, on all twelve.

    Derived from the set rather than listed, so a thirteenth buyback card
    ingested later is covered by whoever ingests it rather than by whoever
    remembers this test.
    """
    printed = [
        card for card in set_cards("TMP")
        if any(is_buyback_line(line) for line in card.oracle_text.split("\n"))
    ]
    assert len(printed) == 12, [c.name for c in printed]
    for card in printed:
        cost = buyback_cost(card.oracle_text)
        assert cost is not None, card.name
        assert BUYBACK_RULES_TEXT.format(cost=cost) in expand_card_lines(card)
        offers = [
            offer
            for entry in additional_costs(card)
            for offer in entry.optional_mana
        ]
        assert [o.symbols for o in offers] == [cost], card.name
        assert not any(o.repeatable for o in offers), (
            f"{card.name}: buyback is paid once, never CR 601.2b's "
            "'any number of times'"
        )


def test_g2_a_buyback_card_still_reports_supported_for_its_effect(set_pool):
    """The rewrite must not cost a card its support: the sentence it produces is
    a *cost*, so the compiler skips it and the effect line is still what makes
    the card supported."""
    program = compile_card_oracle(set_pool("TMP")["Capsize"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["bounce_target_creature"]


def test_g2_declining_buyback_puts_capsize_in_the_graveyard(set_pool, catalog_by_name):
    game, caster = _g2_rig(set_pool, "Capsize", U=3)
    bear = Permanent(card=catalog_by_name["Grizzly Bears"])
    game.players[1].battlefield.append(bear)
    game._settle()

    result = game.cast_from_hand(
        0, "Capsize", target_player_index=1,
        target_permanent_ids=[bear.permanent_id],
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in caster.graveyard] == ["Capsize"]
    assert caster.hand == []
    assert sum(caster.mana_pool.values()) == 0, "the printed {1}{U}{U} and no more"


def test_g2_paying_buyback_returns_capsize_to_its_owners_hand(set_pool, catalog_by_name):
    """The half no other instrument can see. Capsize compiled, reported
    supported and bounced a permanent before this round; what it did not do was
    offer the price or come back, so it was a strictly weaker card and silently
    so."""
    game, caster = _g2_rig(set_pool, "Capsize", U=6)
    bear = Permanent(card=catalog_by_name["Grizzly Bears"])
    game.players[1].battlefield.append(bear)
    game._settle()

    result = game.cast_from_hand(
        0, "Capsize", target_player_index=1,
        target_permanent_ids=[bear.permanent_id],
        optional_cost_payments={"{3}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in caster.hand] == ["Capsize"]
    assert caster.graveyard == []
    assert sum(caster.mana_pool.values()) == 0, "{1}{U}{U} plus the buyback {3}"
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"], (
        "the effect still happens; buyback replaces only where the card goes"
    )


def test_g2_capsize_can_be_cast_again_from_the_hand_it_came_back_to(
    set_pool, catalog_by_name
):
    """The engine the card is: paid twice, it bounces twice off one copy."""
    game, caster = _g2_rig(set_pool, "Capsize", U=12)
    for _ in range(2):
        game.players[1].battlefield.append(
            Permanent(card=catalog_by_name["Grizzly Bears"])
        )
    game._settle()

    for _ in range(2):
        victim = game.players[1].battlefield[0]
        result = game.cast_from_hand(
            0, "Capsize", target_player_index=1,
            target_permanent_ids=[victim.permanent_id],
            optional_cost_payments={"{3}": 1},
        )
        assert result.supported, result.details
        game._settle()
        game.resolve_top_of_stack()
        game._settle()

    assert [c.name for c in caster.hand] == ["Capsize"]
    assert game.players[1].battlefield == []
    assert len(game.players[1].hand) == 2


def test_g2_buyback_is_refused_when_the_pool_cannot_pay_it(set_pool):
    """CR 601.2h: an unpayable announcement refuses the cast, and refuses it
    before anything is spent — the spell stays in hand with the pool intact."""
    game, caster = _g2_rig(set_pool, "Whispers of the Muse", U=1)
    caster.library = [set_pool("TMP")["Capsize"]]
    game._settle()

    result = game.cast_from_hand(
        0, "Whispers of the Muse", optional_cost_payments={"{5}": 1},
    )
    game._settle()

    assert not result.supported
    assert [c.name for c in caster.hand] == ["Whispers of the Muse"]
    assert sum(caster.mana_pool.values()) == 1


def test_g2_whispers_of_the_muse_draws_and_returns(set_pool):
    game, caster = _g2_rig(set_pool, "Whispers of the Muse", U=6)
    caster.library = [set_pool("TMP")["Capsize"]]
    game._settle()

    result = game.cast_from_hand(
        0, "Whispers of the Muse", optional_cost_payments={"{5}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert sorted(c.name for c in caster.hand) == ["Capsize", "Whispers of the Muse"]
    assert caster.graveyard == []


def test_g2_worthy_cause_charges_its_sacrifice_and_its_buyback(
    set_pool, catalog_by_name
):
    """The one card in the set printing buyback *and* another additional cost.
    Both are read off one card, and the optional one does not swallow the
    mandatory one."""
    card = set_pool("TMP")["Worthy Cause"]
    described = [entry.describe() for entry in additional_costs(card)]
    assert described == ["you may pay {2}", "sacrifice a creature"]

    game, caster = _g2_rig(set_pool, "Worthy Cause", W=3)
    caster.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))
    game._settle()

    result = game.cast_from_hand(
        0, "Worthy Cause", optional_cost_payments={"{2}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert caster.battlefield == [], "the sacrifice was still charged"
    assert [c.name for c in caster.hand] == ["Worthy Cause"]


def test_g2_an_unreadable_buyback_line_makes_the_card_unsupported():
    """The gate, tested with an invented printing rather than a real card: a
    buyback whose cost this file cannot read must refuse the card, because the
    alternative is a spell cast at its printed mana cost with the price nobody
    was offered."""
    assert unread_cost_sentence("Buyback-Sacrifice a creature.") == (
        "buyback-sacrifice a creature"
    )
    assert expand_buyback_line("Buyback-Sacrifice a creature.") is None
    assert unread_cost_sentence("Buyback {3}") is None, (
        "a readable one is claimed, not refused"
    )


@pytest.mark.parametrize("choices", [None, {}, {"additional_costs_paid": {}},
                                     {"additional_costs_paid": {"{3}": 0}}])
def test_g2_an_unpaid_or_absent_announcement_reads_back_as_declined(
    set_pool, choices
):
    """Every shape of "nothing was announced" is a decline. The read-back is
    asked at *every* spell's resolution, so the answer for a card printing no
    buyback at all has to be False rather than an exception."""
    assert not buyback_paid(set_pool("TMP")["Capsize"], choices)
    assert not buyback_paid(set_pool("TMP")["Reality Anchor"], choices)
    assert not buyback_paid(
        set_pool("TMP")["Reality Anchor"],
        {"additional_costs_paid": {"{3}": 1}},
    ), "a card printing no buyback is never bought back by somebody else's key"


# --- W1G2: Whim of Volrath — a text change with a printed duration (CR 612) ---
from engine.card_loader import load_cards as _w1g2_load
from engine.card_loader import manifest_set_path as _w1g2_path
from engine.text_changes import UNTIL_END_OF_TURN, text_changes

_W1G2_LEA = {card.name: card for card in _w1g2_load(_w1g2_path("LEA"))}
_W1G2_MIR = {card.name: card for card in _w1g2_load(_w1g2_path("MIR"))}


def _g2_text_change(spell, *, old="W", new="U"):
    """Cast *spell* at a Black Knight and answer any vocabulary prompt.

    Black Knight is the subject because its "Protection from white" is a colour
    word in its *rules text* — so the rewrite is visible through
    ``effective_card`` (CR 613 layer 3) rather than only in a record.
    """
    caster = PlayerState(name="A", hand=[spell])
    holder = PlayerState(name="B")
    game = Game(players=[caster, holder])
    game.enforce_mana_costs = False
    knight = Permanent(card=_W1G2_LEA["Black Knight"])
    holder.battlefield.append(knight)
    game._settle()

    result = game.cast_from_hand(
        0, spell.name, target_player_index=1, target_permanent_index=0,
        target_permanent_ids=[knight.permanent_id],
        old_color=old, new_color=new,
    )
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()
    for choice in list(game.pending_choices):
        game.confirm_text_change_vocabulary(choice.player_index, "color_word")
        game._settle()
    return game, knight, result


def test_g2_whim_of_volrath_is_mind_bend_with_a_duration(set_pool):
    """The union vocabulary already existed (Mind Bend, MIR). What Whim of
    Volrath adds is the *duration*, which is why it is a field on the node and
    a key on the payload rather than a second instruction kind."""
    program = compile_card_oracle(set_pool("TMP")["Whim of Volrath"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["mark_text_modified"]
    assert program.instructions[0].payload == {
        "mode": "color_word_or_land_type", "duration": "until_end_of_turn",
    }
    assert compile_card_oracle(_W1G2_MIR["Mind Bend"]).instructions[0].payload == {
        "mode": "color_word_or_land_type",
    }, "the durationless printing keeps the payload it always had"


def test_g2_whim_of_volrath_rewrites_the_word_and_the_cleanup_puts_it_back(set_pool):
    game, knight, result = _g2_text_change(set_pool("TMP")["Whim of Volrath"])

    assert result.supported, result.details
    assert "protection from blue" in knight.effective_card.oracle_text.lower()
    assert [
        (c["from"], c["to"], c.get("duration")) for c in text_changes(knight)
    ] == [("white", "blue", UNTIL_END_OF_TURN)]

    game.resolve_cleanup_step(0)
    game._settle()

    assert text_changes(knight) == ()
    assert "protection from white" in knight.effective_card.oracle_text.lower(), (
        "dropping the contribution is the reversion (CR 611.3b) — nothing was "
        "stashed and nothing is restored"
    )


def test_g2_the_cleanup_keeps_a_text_change_printed_without_a_duration():
    """The half a plain `_EOT_METADATA_KEYS` entry would have got wrong: the key
    holds records of two lifetimes, and popping it whole would end Mind Bend's
    indefinite rewrite with the turn."""
    game, knight, result = _g2_text_change(_W1G2_MIR["Mind Bend"])

    assert result.supported, result.details
    assert [c.get("duration") for c in text_changes(knight)] == [None]

    game.resolve_cleanup_step(0)
    game._settle()

    assert [c.get("duration") for c in text_changes(knight)] == [None]
    assert "protection from blue" in knight.effective_card.oracle_text.lower()


def test_g2_both_lifetimes_on_one_permanent_end_separately(set_pool):
    """Mind Bend first, then Whim of Volrath: the cleanup drops one record and
    keeps the other, and what the permanent reads afterwards is whatever
    contributions remain.

    Neither swap names blue, and that is not incidental: Whim of Volrath is a
    **blue** spell, so rewriting Black Knight's protection to blue would make it
    an illegal target for the second cast (CR 702.16b). The engine refuses that
    correctly, which is how this test first failed.
    """
    caster = PlayerState(
        name="A",
        hand=[_W1G2_MIR["Mind Bend"], set_pool("TMP")["Whim of Volrath"]],
    )
    holder = PlayerState(name="B")
    game = Game(players=[caster, holder])
    game.enforce_mana_costs = False
    knight = Permanent(card=_W1G2_LEA["Black Knight"])
    holder.battlefield.append(knight)
    game._settle()

    for name, old, new in (("Mind Bend", "W", "G"), ("Whim of Volrath", "G", "R")):
        cast = game.cast_from_hand(
            0, name, target_player_index=1, target_permanent_index=0,
            target_permanent_ids=[knight.permanent_id],
            old_color=old, new_color=new,
        )
        assert cast.supported, f"{name}: {cast.details}"
        game._settle()
        while game.stack:
            game.resolve_top_of_stack()
            game._settle()
        for choice in list(game.pending_choices):
            game.confirm_text_change_vocabulary(choice.player_index, "color_word")
            game._settle()

    assert "protection from red" in knight.effective_card.oracle_text.lower()

    game.resolve_cleanup_step(0)
    game._settle()

    assert [c.get("duration") for c in text_changes(knight)] == [None]
    assert "protection from green" in knight.effective_card.oracle_text.lower(), (
        "Mind Bend's white->green is still there; only Whim's green->red ended"
    )


# --- W1G5: Interdict counters an ability and shuts the permanent down ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.spell_prohibitions import clear_turn_spell_prohibitions
from engine.targeting import derive_cast_spec

_W1G5_PINGER = "{T}: This creature deals 1 damage to any target."


def _w1g5i_pinger(name):
    raw = {"name": name, "type_line": "Creature — Wizard", "power": "1", "toughness": "1"}
    return CardDefinition(
        name=name, mana_cost="", type_line="Creature — Wizard",
        oracle_text=_W1G5_PINGER, cmc=0.0, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw, power="1", toughness="1",
    )


def _w1g5i_board(set_pool):
    pinger = Permanent(card=_w1g5i_pinger("Pinger"))
    spare = Permanent(card=_w1g5i_pinger("Spare"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("TMP")["Interdict"]]),
        PlayerState(name="P2", battlefield=[pinger, spare]),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for permanent in (pinger, spare):
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, pinger, spare


def test_w1g5_interdict_counters_an_ability_and_bans_its_source(set_pool):
    """"Counter target activated ability from an artifact, creature,
    enchantment, or land. That permanent's activated abilities can't be
    activated this turn."

    Both sentences, because either alone is a card doing half its job: the
    counter is what the spell targets, and the ban is a *back-reference* to the
    permanent behind the ability — an object nothing else can name once the
    ability has left the stack (CR 113.7a).

    The spare permanent is the narrowing: CR 602.5c bans one permanent's
    abilities, not its controller's, and a ban recorded per seat would shut
    that one down too.
    """
    game, pinger, _spare = _w1g5i_board(set_pool)

    assert game.queue_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported
    assert len(game.stack) == 1

    result = game.cast_from_hand(0, "Interdict", target_stack_index=0)
    assert result.supported, result.details
    while game.stack:
        game.resolve_top_of_stack()

    assert game.players[0].life == 20, "the ability was countered"

    pinger.tapped = False
    refused = game.activate_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    )
    assert not refused.supported, "the source is shut down for the turn"

    allowed = game.activate_permanent_ability(
        1, "Spare", permanent_index=1, ability_index=0, target_player_index=0,
    )
    assert allowed.supported, "only that permanent, not its controller"


def test_w1g5_interdicts_ban_ends_with_the_turn(set_pool):
    """"…this turn." The record is armed on the game and dropped at the turn
    boundary, which is the whole reason the lowering refuses any other window:
    a longer one would be a ban nothing lifts."""
    game, pinger, _spare = _w1g5i_board(set_pool)

    assert game.queue_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported
    game.cast_from_hand(0, "Interdict", target_stack_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    clear_turn_spell_prohibitions(game)
    pinger.tapped = False
    assert game.activate_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported, game.log


def test_w1g5_interdict_offers_a_picker_over_the_four_printed_types(set_pool):
    """`picker_sweep`'s Roots-class finding: the text names a choice and the
    derivation offered none, so the client sent a bare cast the engine then
    refused. All four printed types ride the spec — a list read as one type
    would offer the caster fewer abilities than the card admits."""
    card = set_pool("TMP")["Interdict"]
    spec = derive_cast_spec(card, compile_card_oracle(card))
    assert spec == {
        "kind": "stack",
        "stack_ability_kinds": ["activated"],
        "stack_ability_source_types": ["artifact", "creature", "enchantment", "land"],
    }


# --- W2G5: Reckless Spite — the printed-number twin of Dregs of Sorrow -----

from engine import Game as _W2G5Game, PlayerState as _W2G5PlayerState
from engine.models import Permanent as _W2G5Permanent
from engine.oracle import compile_card_oracle as _w2g5_compile
from engine.targeting import derive_cast_spec as _w2g5_cast_spec


def _w2g5_duel(set_pool, spell, victims):
    pool = set_pool("TMP")
    lands = set_pool("LEA")
    p1 = _W2G5PlayerState(
        name="P1", hand=[pool[spell]], life=20, library=[lands["Forest"]] * 12,
    )
    p2 = _W2G5PlayerState(
        name="P2", life=20,
        battlefield=[_W2G5Permanent(card=pool[name]) for name in victims],
    )
    game = _W2G5Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p1, p2


def test_w2g5_reckless_spite_destroys_two_nonblack_creatures_and_costs_5_life(set_pool):
    """"Destroy two target nonblack creatures. You lose 5 life."

    One piece for two cards: Dregs of Sorrow's X and this card's printed two
    are the same ``_names_several_targets`` shape, so the same whitelist
    refused both and one entry cleared both.
    """
    game, caster, defender = _w2g5_duel(
        set_pool, "Reckless Spite",
        ["Horned Turtle", "Trained Armodon", "Blood Pet"],
    )

    result = game.cast_from_hand(
        0, "Reckless Spite",
        target_player_index=1, target_permanent_index=[0, 1],
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert [p.card.name for p in defender.battlefield] == ["Blood Pet"]
    # The life loss is the caster's own, not the defender's.
    assert (caster.life, defender.life) == (15, 20)


def test_w2g5_reckless_spite_refuses_a_black_creature_with_nothing_spent(set_pool):
    """CR 601.2c, and the reason the refusal has to land at the announcement:
    the rider is a *cost to the caster*. Accepted and then dropped at
    resolution, this spell would have taken the 5 life for destroying one
    creature instead of two."""
    game, caster, defender = _w2g5_duel(
        set_pool, "Reckless Spite", ["Horned Turtle", "Blood Pet"],
    )

    refused = game.cast_from_hand(
        0, "Reckless Spite",
        target_player_index=1, target_permanent_index=[0, 1],
    )

    assert not refused.supported, "Blood Pet is black (CR 202.2)"
    assert caster.life == 20, "a refused announcement pays nothing"
    assert len(defender.battlefield) == 2


def test_w2g5_reckless_spite_carries_its_printed_count_and_its_exclusion(set_pool):
    """Both halves of the announcement ride one spec: how many the caster names
    (CR 601.2c's fixed number) and what each of them may be."""
    card = set_pool("TMP")["Reckless Spite"]
    spec = _w2g5_cast_spec(card, _w2g5_compile(card))

    assert spec == {
        "kind": "creature",
        "max_targets": 2,
        "exact_targets": True,
        "filter": {"exclude_colors": ["B"]},
    }


# --- W2G2: Respite, and the per-each life gain's fold (CR 107.3) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


def test_w2g2_respite_gains_one_life_per_attacker_and_fogs(set_pool):
    """``Prevent all combat damage that would be dealt this turn. You gain 1
    life for each attacking creature.``

    The count is the round's point. CR 508.1a puts every attacker on the
    **active** player's battlefield, so the seat casting the fog controls none
    of them — the hand-built battlefield branch this fold removed scanned
    ``controlled_by(gainer)`` and would have answered zero.
    """
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    for name in ("Bear A", "Bear B", "Bear C"):
        p0.battlefield.append(_nosick(Permanent(card=_mk_creature_card(name, 2, 2))))
    p1.hand.append(set_pool("TMP")["Respite"])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1, 2], 1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]

    before = p1.life
    assert game.cast_from_hand(1, "Respite").supported
    while game.stack:
        game.resolve_top_of_stack()
    assert p1.life == before + 3, game.log
    game.advance_combat_phase()
    assert p1.life == before + 3, "the fog is the other half of the same card"


def test_w2g2_aven_gagglemaster_still_counts_its_fliers(catalog_by_name):
    """The card the fold had to keep working. Its ``with_keywords`` narrowing
    was the one thing the general counter refused — ``evaluate_count`` asked
    the *pure* matcher, which cannot answer layer 6 — so the battlefield scan
    now goes through ``subject_matches`` like every other reader of a printed
    noun phrase. Two fliers on the board: the Hawk and the Gagglemaster."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p0.hand.append(catalog_by_name["Aven Gagglemaster"])
    p0.battlefield.append(
        _nosick(Permanent(card=_mk_creature_card("Hawk", 1, 1, "Flying")))
    )
    p0.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Ox", 2, 2))))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    before = p0.life
    assert game.cast_from_hand(0, "Aven Gagglemaster").supported
    while game.stack:
        game.resolve_top_of_stack()
    assert p0.life == before + 4, game.log


def test_w2g2_respite_is_supported(set_pool):
    assert compile_card_oracle(set_pool("TMP")["Respite"]).supported
