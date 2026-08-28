"""Per-card tests for Legends' enchantments, round 36 onward.

`test_legends_enchantments.py` reached 2,549 of the 2,600-line guard, so this
round's card starts a second file rather than pushing it over — the same split
`test_legends_instants_round_35_onward.py` already made.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _takklemaggot(set_pool):
    """Takklemaggot on an opponent's 1/1, with a creature on each side to move
    to. Returns (game, aura, host, spare, mine)."""
    aura = Permanent(card=set_pool("LEG")["Takklemaggot"])
    mine = Permanent(card=_creature("Mine", 4, 4))
    host = Permanent(card=_creature("Host", 1, 1))
    spare = Permanent(card=_creature("Spare", 3, 3))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[aura, mine]),
        PlayerState(name="P1", battlefield=[host, spare]),
    ])
    game._sync_control()
    attach_aura(aura, host)
    # The seat the trigger asks is the dead creature's controller; making it
    # interactive is what turns the pick into a prompt the test can answer,
    # rather than the deterministic default headless play takes.
    game.interactive_seats = {1}
    return game, aura, host, spare, mine


def _kill_the_host(game, host):
    host.damage_marked = 99
    game.check_state_based_actions()


def test_takklemaggot_is_supported(set_pool):
    assert compile_card_oracle(set_pool("LEG")["Takklemaggot"]).supported


def test_takklemaggot_asks_the_dead_creatures_controller(set_pool):
    """"That creature's controller chooses..." — CR 601.2c does not make the
    choice the ability's controller's, and the seat is the one the death event
    froze: by the time the trigger resolves the creature is a card in a
    graveyard, and a graveyard card has no controller (CR 108.4a)."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)

    pending = game.pending_choices_of("permanent_choice")
    assert len(pending) == 1
    assert pending[0].player_index == 1
    # "If they don't" is a branch the card prints, so the seat may decline.
    assert pending[0].data["optional"]


def test_takklemaggot_returns_attached_to_the_creature_chosen(set_pool):
    """"If the player does, return this card to the battlefield **under your
    control** attached to that creature." The Aura comes back under the
    trigger's controller, not the chooser's, and it is legally attached — so
    CR 704.5m leaves it alone."""
    game, _aura, host, spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    choice = game.pending_choices_of("permanent_choice")[0]
    assert game.confirm_permanent_choice(1, spare.permanent_id)

    returned = next(p for p in game.all_permanents() if p.card.name == "Takklemaggot")
    assert returned.metadata["attached_to"] is spare
    assert game.controller_index_of(returned) == 0
    game.check_state_based_actions()
    assert game.is_on_battlefield(returned)
    assert choice not in game.pending_choices


def test_takklemaggot_reattached_resumes_its_upkeep_counter(set_pool):
    """The returning Aura is an ordinary Aura again: its printed upkeep trigger
    fires on the *new* host's controller's upkeep."""
    game, _aura, host, spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, spare.permanent_id)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    while game.stack:
        game.resolve_top_of_stack()

    assert spare.effective_toughness == 2


def test_takklemaggot_declined_returns_as_a_non_aura_enchantment(set_pool):
    """"If they don't, return this card ... as a non-Aura enchantment. It loses
    'enchant creature' ..." — CR 613 layer 4 takes the subtype and layer 6
    (CR 613.1f) takes the ability, so the CR 704.5m sweep does not see an Aura
    attached to nothing and the permanent stays on the battlefield."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    # Declining is a legal answer, and only because the card printed a branch
    # for it.
    assert game.confirm_permanent_choice(1, None)

    returned = next(p for p in game.all_permanents() if p.card.name == "Takklemaggot")
    assert game.controller_index_of(returned) == 0
    assert not returned.has_type("aura")
    assert returned.has_type("enchantment")
    assert "Enchant creature" not in returned.effective_card.oracle_text
    assert "Enchant" not in returned.effective_card.keywords
    game.check_state_based_actions()
    assert game.is_on_battlefield(returned), "704.5m has no Aura to bin"


def test_takklemaggot_declined_pings_the_player_who_declined(set_pool):
    """The granted quote's "that player" is the seat the trigger asked, and the
    trigger fires on that seat's upkeep alone."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, None)

    for seat in (0, 1):
        game.active_player_index = seat
        game.resolve_upkeep(seat)
        while game.stack:
            game.resolve_top_of_stack()

    assert [player.life for player in game.players] == [20, 19]


def test_takklemaggot_declined_keeps_pinging_each_upkeep(set_pool):
    """CR 603.3: the granted trigger is an ability of the permanent, not a
    one-shot the return performed."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, None)

    for _ in range(3):
        game.active_player_index = 1
        game.resolve_upkeep(1)
        while game.stack:
            game.resolve_top_of_stack()

    assert game.players[1].life == 17


def test_takklemaggot_offers_only_creatures_it_could_enchant(set_pool):
    """"...a creature that this card could enchant" is CR 303.4j asked of the
    card in the graveyard, through the same predicate the attach re-asks — so a
    permanent that is not a creature is never offered."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)
    rock = Permanent(card=CardDefinition(
        name="Rock", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Rock", "type_line": "Artifact"},
    ))
    game.players[1].battlefield.append(rock)
    game._sync_control()

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    choice = game.pending_choices_of("permanent_choice")[0]

    offered = {p.card.name for p in game.live_permanent_choices(choice)}
    assert offered == {"Mine", "Spare"}


# ---------------------------------------------------------------------------
# Phase 4 promotion — two Auras whose only ability compiled to nothing.
#
# Both reported *supported*: Dream Coat on its enchant line, Equinox on an
# `engine/auras.py` claim entry naming code that had been deleted. That entry is
# the shape `support_report.py --hollow-lines` warns about in its footer — a
# line leaning on a registry the compiler cannot see — and the only way to tell
# a live registry from a stale claim is to give the behaviour a game.
# ---------------------------------------------------------------------------


def _p4_aura_game(aura, host, **player_kwargs):
    """*aura* attached to *host*, both under P1, with costs off."""
    aura.metadata["summoning_sickness_turn"] = -99
    host.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[host, aura], **player_kwargs)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(aura, host)
    return game, p1, p2


def test_dream_coat_recolours_the_creature_it_enchants(set_pool):
    """"{0}: Enchanted creature becomes the color or colors of your choice."

    The subject is the Aura's own host (CR 303.4), not a target — read as one
    the sentence refused and the ability compiled to nothing, so activating it
    logged "ability not implemented".
    """
    from engine.layer_bridge import computed_colors

    coat = Permanent(card=set_pool("LEG")["Dream Coat"])
    bear = Permanent(card=_creature("Bear", 2, 2))
    game, p1, _ = _p4_aura_game(coat, bear)

    result = game.activate_permanent_ability(
        0, "Dream Coat", permanent_index=1, mana_color="U"
    )
    game._settle()

    assert result.supported
    assert computed_colors(bear) == {"U"}, "a colour replacement, not an addition"


def test_dream_coat_can_make_its_host_several_colours(set_pool):
    """"the color **or colors** of your choice" — CR 105.2 makes an object of
    two colours one object, and the plural is a wider offer than Alchor's
    Tomb's singular. Answering it with one colour would be a narrowing the card
    does not print, so the write takes a set."""
    from engine.layer_bridge import computed_colors

    coat = Permanent(card=set_pool("LEG")["Dream Coat"])
    bear = Permanent(card=_creature("Bear", 2, 2))
    game, p1, _ = _p4_aura_game(coat, bear)

    # The set arrives on the same channel one colour does; the wire carries one
    # symbol today, so this is the layer's half of the answer.
    bear.metadata["color_override"] = ("W", "U")

    assert computed_colors(bear) == {"W", "U"}


def test_equinox_grants_its_land_the_printed_counter_ability(set_pool):
    """'Enchanted land has "{T}: Counter target spell if it would destroy a
    land you control."'

    A whole printed *ability* granted to the host, so what the host gains is the
    **line** and the compiler is what turns a line into an ability. The claim
    table said "granted activated/triggered ability — _apply_aura_effect" and
    that function no longer existed, so the land gained nothing at all.
    """
    equinox = Permanent(card=set_pool("LEG")["Equinox"])
    forest = Permanent(card=_p4_land())
    _game, _p1, _p2 = _p4_aura_game(equinox, forest)

    program = compile_card_oracle(forest.effective_card)
    granted = [a for a in program.activated_abilities if "counter" in a.source_line]

    assert len(granted) == 1
    assert granted[0].supported, (
        "a granted line the compiler cannot read is the same hollow shape as "
        "a grant nothing makes"
    )


def test_the_granted_ability_goes_away_with_the_aura(set_pool):
    """Derived, not recorded (CR 611.3b): detaching contributes nothing, so
    there is no delta for anything to remember to undo."""
    equinox = Permanent(card=set_pool("LEG")["Equinox"])
    forest = Permanent(card=_p4_land())
    _game, _p1, _p2 = _p4_aura_game(equinox, forest)

    from engine.auras import detach_aura

    detach_aura(equinox, forest)

    program = compile_card_oracle(forest.effective_card)
    assert not [a for a in program.activated_abilities if "counter" in a.source_line]


def _p4_land(name: str = "Wood") -> CardDefinition:
    """A land with no text of its own, so what it can do is what Equinox grants.

    Invented rather than borrowed from another set's pool: Legends prints no
    basic land, and a per-set file reaching into a second set's pool is reaching
    past the convention for a prop.
    """
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Land", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Land"},
    )


def _p4_spell(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}{R}", cmc=3.0, type_line="Sorcery",
        oracle_text=text, colors=("R",), color_identity=("R",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Sorcery", "oracle_text": text},
    )


def _p4_equinox_board(set_pool, spell):
    """P1's enchanted land, with *spell* in P2's hand."""
    equinox = Permanent(card=set_pool("LEG")["Equinox"])
    forest = Permanent(card=_p4_land())
    forest.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[forest, equinox])
    p2 = PlayerState(name="P2", hand=[spell])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(equinox, forest)
    return game, p1, p2, forest


def test_equinox_counters_a_spell_that_would_destroy_a_land(set_pool):
    """The condition is asked of the *chosen spell's own effect* at resolution
    (CR 608.2), which nothing on the stack item records — so it is answered by
    reading that spell's compiled program."""
    game, p1, p2, forest = _p4_equinox_board(
        set_pool, _p4_spell("Stone Rain", "Destroy target land.")
    )

    game.queue_from_hand(1, "Stone Rain", target_player_index=0, target_permanent_index=0)
    result = game.activate_permanent_ability(
        0, "Wood", target_player_index=1, ability_index=0, target_stack_index=0
    )
    game.resolve_stack()

    assert result.supported
    assert forest in p1.battlefield
    assert [c.name for c in p2.graveyard] == ["Stone Rain"]


def test_equinox_counters_a_land_sweep_too(set_pool):
    """"Destroy all lands" names no target, so the question is only whether the
    ability's controller has a land — the sweep half of the same condition."""
    game, p1, p2, forest = _p4_equinox_board(
        set_pool, _p4_spell("Armageddon", "Destroy all lands.")
    )

    game.queue_from_hand(1, "Armageddon", target_player_index=0)
    result = game.activate_permanent_ability(
        0, "Wood", target_player_index=1, ability_index=0, target_stack_index=0
    )
    game.resolve_stack()

    assert result.supported
    assert forest in p1.battlefield


def test_equinox_declines_a_spell_that_would_not(set_pool):
    """The condition is the whole card. A counter that fired regardless would
    be a free Counterspell on every land — the direction nothing crashes and
    the card is simply wrong."""
    game, p1, p2, forest = _p4_equinox_board(
        set_pool,
        _p4_spell("Bolt", "Bolt deals 3 damage to any target."),
    )

    game.queue_from_hand(1, "Bolt", target_player_index=0)
    result = game.activate_permanent_ability(
        0, "Wood", target_player_index=1, ability_index=0, target_stack_index=0
    )
    game.resolve_stack()

    assert result.supported, "the ability resolves; it simply counters nothing"
    assert any(
        "would not destroy a land you control" in line for line in game.log
    ), "the refusal is logged rather than silent"


# --- Sylvan Library: the duplicate-copy hand removal ---


def test_sylvan_library_puts_back_one_copy_not_every_copy(set_pool, catalog_by_name):
    """Regression: identical cards in hand, one put on the library, and the
    rest ceased to exist.

    A hand is a ``list[CardDefinition]`` and a deck repeats one immutable
    definition per copy — ``web/deck_builder.py`` does
    ``deck.extend([card] * count)`` — so every Forest in a hand is the *same
    object*. ``put_iterated_card_on_library`` removed the chosen card with
    ``[c for c in player.hand if c is not card]``, an identity test that is
    right about which object and wrong about how many: it removed all of them
    and then put exactly one back. ``engine/phases/upkeep_step.py`` documents
    the same class found in a graveyard (Nether Shadow: five cards in, four
    out); this is the hand's copy of it, and ``Game.take_card_from_hand`` is
    now the one way to do it.

    Life is set to 3 so the mode default cannot afford "pay 4 life" and takes
    the library branch instead — without that the branch never runs and this
    test passes over the bug, which is how it was first written.
    """
    from engine.game import Game
    from engine.models import Permanent, PlayerState

    pool = set_pool("LEG")
    forest = catalog_by_name["Forest"]
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 3

    library = Permanent(card=pool["Sylvan Library"])
    p1.battlefield.append(library)
    game._initialize_permanent_state(library, 0, None)

    p1.life = 3
    p1.hand = [forest]
    p1.library = [forest, forest, forest, pool["Rust"], pool["Backfire"]]
    before = len(p1.hand) + len(p1.library)

    game.resolve_draw_step(0)
    game.auto_resolve_pending_choices()

    assert any(
        "put Forest on top of their library" in line for line in game.log
    ), "the library branch has to run, or this test asserts nothing"
    after = len(p1.hand) + len(p1.library)
    assert after == before, (
        f"cards left the game: hand+library held {before} before the trigger "
        f"and {after} after"
    )
    assert sum(1 for c in p1.hand + p1.library if c is forest) == 4
