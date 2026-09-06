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


# --- W2G5: a number frozen by the step that moved the card ------------------


def test_w2g5_reanimate_costs_its_target_s_mana_value_in_life(set_pool):
    """"Put target creature card from a graveyard onto the battlefield under
    your control. You lose life equal to **that card's mana value**."

    Three layers were missing and the inherited refusal named none of them
    (it quoted the *second* sentence's first word, which is a probe above the
    real production raising first):

    1. ``that <noun>'s mana value`` admitted card types and subtypes and not
       the word **card** — CR 400.1's word for an object outside the
       battlefield, which is what a sentence following a graveyard phrase
       prints;
    2. ``reanimate_creature`` declared no ``its_mana_value`` producer, so the
       back-reference gate refused the phrase by name;
    3. and ``target_loses_life`` read the *trigger* channel only, so even with
       both of those the card would have lost **zero** life and logged itself
       resolved. Its twin ``target_gains_life`` has read both channels since
       Divine Offering.

    Only a game finds the third, which is why this test is a game.
    """
    pool = set_pool("TMP")
    elemental = set_pool("LEA")["Air Elemental"]   # {3}{U}{U}
    caster = PlayerState(
        name="P1", hand=[pool["Reanimate"]], life=20, graveyard=[elemental],
    )
    game = Game(players=[caster, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Reanimate", target_player_index=0, target_permanent_index=0,
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Air Elemental"]
    assert caster.life == 15, "5 life for a mana value of 5"


def test_w2g5_reanimate_reads_a_graveyard_that_is_not_the_casters(set_pool):
    """"…from **a** graveyard" (not "your graveyard"), so the card comes back
    under the caster's control out of the opponent's pile — and the life paid
    is that card's mana value, not the caster's own creature's."""
    pool = set_pool("TMP")
    caster = PlayerState(name="P1", hand=[pool["Reanimate"]], life=20)
    victim = PlayerState(
        name="P2", life=20, graveyard=[pool["Horned Turtle"]],   # {2}{U}
    )
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Reanimate", target_player_index=1, target_permanent_index=0,
    )
    game.resolve_stack()

    assert [p.card.name for p in caster.battlefield] == ["Horned Turtle"]
    assert caster.life == 17


def test_w2g5_reanimate_with_nothing_to_return_costs_nothing(set_pool):
    """The record is written unconditionally, zero when nothing came back.

    The lowering admitted the phrase on the strength of a producer, so a step
    that sometimes writes nothing would be a reader that sometimes finds
    nothing — and "nothing arrived" has a right answer rather than an absent
    one: CR 608.2b affects no object, so no life is lost.
    """
    pool = set_pool("TMP")
    caster = PlayerState(name="P1", hand=[pool["Reanimate"]], life=20)
    game = Game(players=[caster, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Reanimate", target_player_index=0)
    game.resolve_stack()

    assert caster.battlefield == []
    assert caster.life == 20


# --- W2G3: Time Warp, the extra turn somebody else takes ---

from engine import Game, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w2g3s_game(hands):
    seats = [
        PlayerState(name=f"P{index + 1}", hand=list(cards))
        for index, cards in enumerate(hands)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def test_time_warp_gives_the_extra_turn_to_its_target(set_pool):
    """"**Target player** takes an extra turn after this one." (CR 500.7.)

    The whole difference from Time Walk, which the engine has read since Alpha,
    is which seat gets the turn — and the lowering used to refuse every subject
    but "you" rather than hand a handler the wrong player. It is one payload key
    now, and the handler reads it exactly where it already read the caster.
    """
    game = _w2g3s_game([[set_pool("TMP")["Time Warp"]], []])
    game.start_turn(0)

    result = game.cast_from_hand(0, "Time Warp", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert game.extra_turn_queue == [1]
    assert game._compute_next_active_player() == 1
    assert game.current_turn_is_extra


def test_time_walk_still_chooses_nobody(catalog_by_name):
    """The regression the payload key exists to avoid. "Take an extra turn
    after this one" names no seat, so no picker is derived and the payload
    stays byte-equal with what the pool has always compiled to — a flat
    "this kind targets a player" row would have put a prompt in front of a
    spell whose handler ignores the answer."""
    walk = catalog_by_name["Time Walk"]

    assert derive_cast_spec(walk, compile_card_oracle(walk)) is None

    game = _w2g3s_game([[walk], []])
    game.start_turn(0)
    game.cast_from_hand(0, "Time Walk")
    game._settle()

    assert game.extra_turn_queue == [0]


def test_time_warp_asks_the_caster_to_pick_a_player(set_pool):
    """And the other half: the picker the browser is offered."""
    warp = set_pool("TMP")["Time Warp"]

    assert derive_cast_spec(warp, compile_card_oracle(warp)) == {"kind": "player"}
    assert compile_card_oracle(warp).instructions[0].payload == {"recipient": "target"}


# --- W2G4: searching a library, and the top of it ---

from engine import Game, PlayerState
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle


def _w2g4_duel(*, libraries=((), ()), hands=((), ())):
    """Two seats with the libraries and hands the test names, mana off.

    Mana enforcement is off for the reason every rig in this file has it off:
    what these tests are about is what the effect *does* to a hidden zone, and
    leaving it on would make each of them a test of the mana payment.
    """
    seats = [
        PlayerState(name=f"P{index}", library=list(lib), hand=list(hand))
        for index, (lib, hand) in enumerate(zip(libraries, hands))
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w2g4_card(name, type_line, text="", colors=()):
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": text},
    )


def test_mana_severance_exiles_every_land_the_searcher_names(set_pool):
    """`Search your library for any number of land cards, exile them, then
    shuffle.` — the uncounted spelling of the exile search (CR 701.23b).

    The Rock Hydra test: the search prompt is answered and the lands are read
    out of *exile*, not off a claim that the instruction compiled.
    """
    card = set_pool("TMP")["Mana Severance"]
    forest = _w2g4_card("Forest", "Basic Land — Forest")
    bear = _w2g4_card("Grizzly Bears", "Creature — Bear")
    game = _w2g4_duel(
        libraries=([forest, bear, forest], ()), hands=([card], ()),
    )
    game.cast_from_hand(0, "Mana Severance")
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("search_exile_cards")))
    # Only the two lands are offerable; the bear is not a land card.
    assert prompt.data.get("card_types") == ("land",)
    assert prompt.data.get("maximum") is None, "'any number' prints no ceiling"
    picks = [
        {"zone": "library", "index": index}
        for index, entry in enumerate(game.players[0].library)
        if entry.primary_type == "land"
    ]
    assert game.confirm_search_exile(0, picks)

    assert [c.name for c in game.players[0].exile] == ["Forest", "Forest"]
    assert [c.name for c in game.players[0].library] == ["Grizzly Bears"]


def test_mana_severance_refuses_a_pick_that_is_not_a_land(set_pool):
    """The narrowing is enforced where the answer is validated, not dropped.

    A search that admitted the creature would be a tutor for anything, which is
    the failure this whole family is written to avoid: nothing crashes and the
    card simply does more than it prints.
    """
    card = set_pool("TMP")["Mana Severance"]
    bear = _w2g4_card("Grizzly Bears", "Creature — Bear")
    game = _w2g4_duel(libraries=([bear], ()), hands=([card], ()))
    game.cast_from_hand(0, "Mana Severance")
    game.resolve_top_of_stack()

    assert not game.confirm_search_exile(0, [{"zone": "library", "index": 0}])
    assert not game.players[0].exile


def test_mana_severance_is_not_a_search_a_headless_seat_takes_the_maximum_of(set_pool):
    """The stated default for an "any number" exile search is *take everything*,
    and its own reasoning is "the cards come back castable" — which is a fact
    about the three cards it was written for (Foresight's delayed return,
    Mangara's Tome's recorded pile, Chandra's cast permission) rather than about
    the sentence.

    Mana Severance is the card that separates them: nothing on it reads the pile
    back, so taking the maximum exiles the seat's entire land supply for good.
    A headless seat now fails to find (CR 701.23b), which is legal and is what a
    player would do. Nothing but driving the card finds this — the census, the
    hollow-line report and `parse_coverage` all read it as done.
    """
    from engine.ai_valuation import exiled_search_pile_comes_back

    card = set_pool("TMP")["Mana Severance"]
    assert not exiled_search_pile_comes_back(card)

    forest = _w2g4_card("Forest", "Basic Land — Forest")
    game = _w2g4_duel(libraries=([forest] * 6, ()), hands=([card], ()))
    game.interactive_seats = set()
    game.cast_from_hand(0, "Mana Severance")
    game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()

    assert not game.players[0].exile
    assert len(game.players[0].library) == 6


def test_a_search_whose_pile_comes_back_still_takes_the_maximum(catalog_by_name):
    """The other half, so the change is a *narrowing* and not a reversal.

    Foresight, Mangara's Tome and Chandra's -9 each hand the exiled cards back,
    and the derivation says so off the compiled program — a card printing a new
    "search and exile" with a return behind it is answered right the day it
    lands, and one without is answered right without anybody listing it.
    """
    from engine.ai_valuation import exiled_search_pile_comes_back

    for name in ("Foresight", "Mangara's Tome", "Chandra, Heart of Fire"):
        assert exiled_search_pile_comes_back(catalog_by_name[name]), name


# --- W2G2: damage sized by a creature's own power (CR 119.3) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import _mk_creature_card, _nosick


def _w2g2_spell_board(spell, p0_creatures, p1_creatures):
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p0.hand.append(spell)
    for card in p0_creatures:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_creatures:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, p0, p1


def test_w2g2_repentance_makes_a_creature_kill_itself(set_pool):
    """``Target creature deals damage to itself equal to its power.``

    CR 119.3: the damage is dealt **by the creature**, so the source is the
    permanent and not the sorcery — which is what makes a bite different from
    the generic damage instruction and why it is its own kind.
    """
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Repentance"], [_mk_creature_card("Ogre", 4, 4)], []
    )
    assert game.cast_from_hand(
        0, "Repentance",
        target_player_index=0,
        target_permanent_ids=[p0.battlefield[0].permanent_id],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert list(game.controlled_by(0)) == [], game.log
    assert any("deals 4 damage to itself" in line for line in game.log), game.log


def test_w2g2_repentance_on_a_zero_power_creature_deals_nothing(set_pool):
    """CR 120.8: damage of 0 is not dealt at all, so nothing is marked and the
    Wall survives — the direction a handler that skipped the check would get
    right by accident and the log would get wrong."""
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Repentance"], [_mk_creature_card("Wall", 0, 4)], []
    )
    assert game.cast_from_hand(
        0, "Repentance",
        target_player_index=0,
        target_permanent_ids=[p0.battlefield[0].permanent_id],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert [p.card.name for p in p0.battlefield] == ["Wall"]


def test_w2g2_deadshot_taps_one_target_and_bites_with_it(set_pool):
    """``Tap target creature. It deals damage equal to its power to another
    target creature.`` — the slot-per-clause gap the engine stated in its own
    refusal. Two announced targets (CR 601.2c), the tap on slot 0 and the bite
    from slot 0 to slot 1."""
    deadshot = set_pool("TMP")["Deadshot"]
    program = compile_card_oracle(deadshot)
    assert program.supported
    assert derive_cast_spec(deadshot, program) == {"kind": "creature", "max_targets": 2}

    game, p0, p1 = _w2g2_spell_board(
        deadshot, [_mk_creature_card("Ogre", 4, 4)], [_mk_creature_card("Squire", 1, 2)]
    )
    assert game.cast_from_hand(
        0, "Deadshot",
        target_player_index=0,
        target_permanent_ids=[
            p0.battlefield[0].permanent_id, p1.battlefield[0].permanent_id
        ],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert p0.battlefield[0].tapped, game.log
    assert list(game.controlled_by(1)) == [], game.log


def test_w2g2_deadshots_biter_need_not_be_yours(set_pool):
    """``target_bites_target`` had "you control" spelled into the handler —
    Garruk, Savage Herald's word, not the kind's. Deadshot names anybody's
    creature as the biter, so the slot is tested against its own printed noun
    phrase instead."""
    game, p0, p1 = _w2g2_spell_board(
        set_pool("TMP")["Deadshot"],
        [],
        [_mk_creature_card("Ogre", 4, 4), _mk_creature_card("Squire", 1, 2)],
    )
    assert game.cast_from_hand(
        0, "Deadshot",
        target_player_index=1,
        target_permanent_ids=[
            p1.battlefield[0].permanent_id, p1.battlefield[1].permanent_id
        ],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert [p.card.name for p in p1.battlefield] == ["Ogre"], game.log
    assert p1.battlefield[0].tapped
