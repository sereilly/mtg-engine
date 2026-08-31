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
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


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
    assert instruction.payload["x_from_count"] == {
        "object_characteristic": {
            "object": "triggering_spell",
            "characteristic": "mana_value",
            "offset": 0,
        }
    }


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


# ---------------------------------------------------------------------------
# Arboria (round 12) — CR 506.3/508.1c, an attack restriction reading per-seat
# last-turn history
# ---------------------------------------------------------------------------


def _arboria_board(set_pool):
    """A bear facing Arboria's controller. Returns (game, bear)."""
    from engine.models import CardDefinition

    bear = Permanent(card=CardDefinition(
        name="Patient Bear", mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Patient Bear", "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    ))
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=set_pool("LEG")["Arboria"])])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    return game, bear


def test_arboria_compiles_supported_with_a_real_instruction(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Arboria"])

    assert program.supported
    assert any(
        i.kind == "cant_attack_unless_defender_acted" for i in program.instructions
    )


def test_arboria_protects_a_player_with_no_last_turn_at_all(set_pool):
    """At the start of the game nobody has a last turn to have acted during,
    which is the card working as printed: under Arboria the first attack waits
    for the defender to have taken — and wasted — a turn."""
    game, bear = _arboria_board(set_pool)

    assert not game.can_attack(bear, 1)


def test_arboria_opens_a_player_who_cast_a_spell_during_their_last_turn(set_pool, lea_by_name):
    game, bear = _arboria_board(set_pool)

    game.start_next_turn()   # P2's turn...
    game.players[1].spells_cast_this_turn.append(lea_by_name["Lightning Bolt"])
    game.start_next_turn()   # ...ends; the fold records the cast

    assert game.can_attack(bear, 1)

    game.start_next_turn()   # P2 takes a quiet turn
    game.start_next_turn()

    assert not game.can_attack(bear, 1), "the record is *their last turn*, not ever"


def test_arboria_opens_a_player_who_put_a_nontoken_permanent_onto_the_battlefield(set_pool):
    """The other half of the unless — a land drop is the everyday case, and it
    goes through the one battlefield entry path the record hangs on."""
    from engine.models import CardDefinition

    game, bear = _arboria_board(set_pool)
    land = Permanent(card=CardDefinition(
        name="Quiet Meadow", mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=("G",),
        raw={"name": "Quiet Meadow", "type_line": "Land"},
    ))

    game.start_next_turn()   # P2's turn
    game._put_permanent_onto_battlefield(1, land, None)
    game.start_next_turn()

    assert game.can_attack(bear, 1)


def test_arboria_ignores_a_token_entering(set_pool):
    """"…a **nontoken** permanent": a token entering keeps the door shut."""
    from engine.tokens import make_token_card

    game, bear = _arboria_board(set_pool)
    token = Permanent(card=make_token_card("Wolf", 2, 2, "Creature — Wolf"))
    token.metadata["is_token"] = True

    game.start_next_turn()
    game._put_permanent_onto_battlefield(1, token, None)
    game.start_next_turn()

    assert not game.can_attack(bear, 1)


def test_arboria_does_not_shield_planeswalkers(set_pool):
    """"Creatures can't attack **a player**" — an attack aimed at a
    planeswalker (CR 508.1b) is not an attack at a player, so Arboria says
    nothing about it."""
    game, bear = _arboria_board(set_pool)

    assert not game.can_attack(bear, 1)
    assert game.can_attack(bear, 1, attacking_planeswalker=True)


# ---------------------------------------------------------------------------
# Round 14 — Storm World: the hand shortfall, on every seat's own upkeep
# ---------------------------------------------------------------------------


def _storm_world(set_pool, lea_by_name, hand_sizes: tuple[int, int]):
    """Storm World on seat 0, with each seat holding *hand_sizes* cards."""
    forest = lea_by_name["Forest"]
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=set_pool("LEG")["Storm World"])],
        hand=[forest] * hand_sizes[0],
        life=20,
    )
    p2 = PlayerState(name="P2", hand=[forest] * hand_sizes[1], life=20)
    return Game(players=[p1, p2]), p1, p2


@pytest.mark.parametrize(
    "held,expected",
    [(0, 16), (1, 17), (3, 19), (4, 20), (6, 20)],
    ids=["empty", "one", "three", "exactly-four", "over-four"],
)
def test_storm_world_deals_the_shortfall_below_four(
    set_pool, lea_by_name, held, expected
):
    """"X is 4 minus the number of cards in their hand" — and it floors at
    zero rather than healing, which is what the two cases at and above four
    are here to pin."""
    game, _p1, p2 = _storm_world(set_pool, lea_by_name, (0, held))

    game.resolve_upkeep(1)
    game.resolve_stack()

    assert p2.life == expected


def test_storm_world_hits_its_own_controller_too(set_pool, lea_by_name):
    """"Each player's upkeep" includes the controller's. Storm World is
    symmetric, so a version that read the source's controller as the victim
    would look right on the opponent's upkeep and never fire on its own.
    """
    game, p1, p2 = _storm_world(set_pool, lea_by_name, (1, 4))

    game.resolve_upkeep(0)
    game.resolve_stack()

    assert p1.life == 17
    assert p2.life == 20, "only the seat whose upkeep it is"


# ---------------------------------------------------------------------------
# Round 27 — Gravity Sphere. "All creatures lose flying." A board-wide keyword
# *removal* at CR 613 layer 6: the mirror of the anthem's keyword grant, and
# the same derived channel, so the ability comes back when the source leaves
# with nothing to find and undo.
# ---------------------------------------------------------------------------


def _r27_flier(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Bird",
        oracle_text="Flying", colors=("W",), color_identity=("W",),
        keywords=("Flying",), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bird",
             "power": "2", "toughness": "2"},
    )


def _r27_gravity_board(set_pool):
    mine, theirs = Permanent(card=_r27_flier("Mine")), Permanent(card=_r27_flier("Theirs"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Gravity Sphere"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    return Game(players=[p1, p2]), mine, theirs


def test_gravity_sphere_compiles_to_a_board_wide_removal(set_pool):
    """The lost keyword rides the payload rather than being a kind of its own —
    "lose flying" and "lose trample" are one template with the word as data."""
    program = compile_card_oracle(set_pool("LEG")["Gravity Sphere"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["lord_buff"]
    assert program.instructions[0].payload["lost_keywords"] == ["flying"]
    # And nothing on the granting side: a single list would have made "have
    # flying" and "lose flying" the same payload.
    assert not program.instructions[0].payload.get("keywords")


def test_gravity_sphere_takes_flying_from_every_creature(set_pool):
    """"All creatures" is both sides of the table. A removal scoped to its
    controller would be a card Legends did not print."""
    game, mine, theirs = _r27_gravity_board(set_pool)
    assert (mine.has_keyword("flying"), theirs.has_keyword("flying")) == (True, True)

    assert game.cast_from_hand(0, "Gravity Sphere").supported
    game.resolve_top_of_stack()

    assert (mine.has_keyword("flying"), theirs.has_keyword("flying")) == (False, False)


def test_gravity_sphere_gives_flying_back_when_it_leaves(set_pool):
    """CR 611.3b: the removal is derived from the board every recompute, so the
    source leaving ends it. A stored removal would have had to be reversed, and
    a reversal is something a zone change can forget."""
    game, mine, theirs = _r27_gravity_board(set_pool)
    game.cast_from_hand(0, "Gravity Sphere")
    game.resolve_top_of_stack()
    sphere = next(p for p in game.all_permanents() if p.card.name == "Gravity Sphere")

    game.remove_from_battlefield(sphere)
    game._recalculate_lord_buffs()

    assert (mine.has_keyword("flying"), theirs.has_keyword("flying")) == (True, True)


# --- FixA: "of their choice" is the affected player's ---


def _abyss_board(set_pool, seats: int = 2, interactive=frozenset()):
    """The Abyss on seat 0, and two creatures on every other seat.

    Two creatures rather than one, because "of their choice" is only visible
    where there is a choice to make: with one candidate every reading of the
    card — the controller picking, the affected player picking, and the
    resolver picking whatever it finds first — lands on the same permanent.
    """
    leg, lea = set_pool("LEG"), set_pool("LEA")
    # Libraries, because the upkeep this test is about is followed by a draw
    # step: an empty library loses the game (CR 104.3c) and takes the seat's
    # creatures with it, which would answer this question for the wrong reason.
    deck = lambda: [lea["Forest"]] * 5
    players = [PlayerState(
        name="P0", battlefield=[Permanent(card=leg["The Abyss"])], library=deck(),
    )]
    for seat in range(1, seats):
        players.append(PlayerState(name=f"P{seat}", library=deck(), battlefield=[
            _nosick(Permanent(card=lea["Grizzly Bears"])),
            _nosick(Permanent(card=lea["Serra Angel"])),
        ]))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, players


def test_the_abyss_asks_the_player_whose_upkeep_it_is(set_pool):
    """"…of their choice" is not a property of any candidate, so no matcher can
    test it — which is why ``TESTABLE_SUBJECT_FILTER_KEYS`` deliberately omits
    the word. It shipped in the payload of a single-target destroy anyway, where
    nothing read it, and the effect quietly became the *controller's* pick.

    Read now as Preacher's decomposition: a ``choose_permanent`` armed on the
    seat the firing event froze, and a destroy behind it acting on the id that
    prompt recorded.
    """
    program = compile_card_oracle(set_pool("LEG")["The Abyss"])
    assert program.supported, program.reason
    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "upkeep_each"

    steps = trigger.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_permanent", "destroy_target_permanent",
    ]
    choose, destroy = steps
    # Who is asked, and whose battlefield they may pick from: one seat named
    # twice by the card ("**that player** … **their** choice"), so both halves
    # read the same frozen seat rather than two answers free to disagree.
    assert choose.payload["chooser"] == "event_subject_player"
    assert choose.payload["controlled_by"] == "chooser"
    assert destroy.payload["permanents_from"] == choose.payload["result_key"]
    assert destroy.payload["bypass_regeneration"] is True
    # And neither of the two keys nothing could read survives into the payload:
    # "of their choice" is performed by the prompt, and "that player controls"
    # by where the prompt draws its candidates from.
    assert "their_choice" not in choose.payload["filter"]
    assert "controller" not in choose.payload["filter"]
    assert choose.payload["filter"] == {
        "type_filter": "creature", "exclude_types": ["artifact"],
    }


def test_the_abyss_destroys_one_creature_of_the_player_whose_upkeep_it_is(set_pool):
    """Three seats, because two make the bug invisible: the resolver was handed
    the *default opposing seat*, which in a duel is the same player the card
    names and with three seats is not."""
    game, players = _abyss_board(set_pool, seats=3)

    game.start_turn(2)
    game._settle()

    assert [c.name for c in players[2].graveyard] == ["Grizzly Bears"]
    assert players[1].graveyard == []
    assert [p.card.name for p in game.controlled_by(2)] == ["Serra Angel"]


def test_the_abyss_destroys_its_own_controllers_creature_on_their_upkeep(set_pool):
    """"Each player's upkeep" includes the controller's own, and on that upkeep
    "that player" is them. The seat was read off ``context.target`` — never the
    controller — so the World enchantment its owner built a deck around was the
    one player it never touched."""
    leg, lea = set_pool("LEG"), set_pool("LEA")
    mine = _nosick(Permanent(card=lea["Hill Giant"]))
    p0 = PlayerState(name="P0", battlefield=[Permanent(card=leg["The Abyss"]), mine])
    p1 = PlayerState(name="P1", battlefield=[_nosick(Permanent(card=lea["Grizzly Bears"]))])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    game.start_turn(0)
    game._settle()

    assert [c.name for c in p0.graveyard] == ["Hill Giant"]
    assert p1.graveyard == []


def test_the_abyss_prompts_the_affected_player_who_picks(set_pool):
    """The prompt is owed by the seat the card names, not by the ability's
    controller — and the resolution waits for it (CR 608.2)."""
    game, players = _abyss_board(set_pool, seats=2, interactive={0, 1})

    game.start_turn(1)
    game._settle()

    prompt = game.waiting_prompt()
    assert prompt is not None
    assert (prompt.kind, prompt.player_index) == ("permanent_choice", 1)
    offered = game.live_permanent_choices(game.pending_choices[0])
    assert sorted(p.card.name for p in offered) == ["Grizzly Bears", "Serra Angel"]

    angel = next(p for p in offered if p.card.name == "Serra Angel")
    assert game.confirm_permanent_choice(1, angel.permanent_id)
    game._settle()

    # The one they chose, not the one board order would have found first.
    assert [c.name for c in players[1].graveyard] == ["Serra Angel"]


def test_a_non_interactive_seat_takes_the_stated_default(set_pool):
    """``default_at_arm``: an AI or headless seat never queues the prompt, so
    the whole resolution still finishes inline. The stated default is board
    order, which is what keeps a seeded run reproducible."""
    game, players = _abyss_board(set_pool, seats=2)

    game.start_turn(1)
    game._settle()

    assert game.pending_choices == []
    assert [c.name for c in players[1].graveyard] == ["Grizzly Bears"]


def test_the_abyss_never_offers_an_artifact_creature(set_pool):
    """"**Nonartifact** creature" narrows the candidates the prompt lists, so a
    board of nothing but artifact creatures loses nothing at all."""
    leg = set_pool("LEG")
    horse = _nosick(Permanent(card=leg["Bronze Horse"]))
    p0 = PlayerState(name="P0", battlefield=[Permanent(card=leg["The Abyss"])])
    p1 = PlayerState(name="P1", battlefield=[horse])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    game.start_turn(1)
    game._settle()

    assert game.is_on_battlefield(horse)
    assert p1.graveyard == []


def test_the_abyss_ignores_a_regeneration_shield(set_pool):
    """"It can't be regenerated" (CR 701.19c): the shield is not applied. The
    rider rides the *destroy* step of the sequence, which is the step that has
    to know."""
    leg, lea = set_pool("LEG"), set_pool("LEA")
    bears = _nosick(Permanent(card=lea["Grizzly Bears"]))
    bears.regeneration_shield = 1
    p0 = PlayerState(name="P0", battlefield=[Permanent(card=leg["The Abyss"])])
    p1 = PlayerState(name="P1", battlefield=[bears])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    game.start_turn(1)
    game._settle()

    assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]


# --- end FixA ---
