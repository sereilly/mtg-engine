"""Nemesis sorceries.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent


def _w1g5_pack_hunt(set_pool, library, *, targets=("Mogg Toady",)):
    """Pack Hunt in seat 0's hand, *targets* on seat 1's battlefield in order.
    W1G5's own."""
    nem = set_pool("NEM")
    me = _W1G5PlayerState(name="W1G5-A", hand=[nem["Pack Hunt"]], library=list(library))
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    pool = {**set_pool("LEA"), **nem}
    for name in targets:
        game._put_permanent_onto_battlefield(1, _W1G5Permanent(card=pool[name]), None)
    game.auto_resolve_pending_choices()
    return game, me


def test_w1g5_pack_hunt_finds_up_to_three_of_the_targets_name(set_pool):
    """"Search your library for up to three cards with the same name as target
    creature, reveal them, put them into your hand, then shuffle."

    Four Mogg Toadies in the library and three are taken; the Forest is refused
    as an answer, because the name is the target's and the search asks it.
    """
    nem, lea = set_pool("NEM"), set_pool("LEA")
    toady = nem["Mogg Toady"]
    game, me = _w1g5_pack_hunt(
        set_pool, [toady, lea["Forest"], toady, nem["Wild Mammoth"], toady, toady],
    )
    assert game.cast_target_spec(0, nem["Pack Hunt"])["kind"] == "creature"
    assert game.cast_from_hand(
        0, "Pack Hunt", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_top_of_stack()

    search = game.pending_choice_of("search_library", 0)
    assert search.data["restrictions"]["named"] == "Mogg Toady"
    assert search.data["count"] == 3 and search.data["up_to"]
    assert not game.confirm_search_library_picks(0, [{"zone": "library", "index": 1}])
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 2, 4)]
    )
    game._settle()

    assert [c.name for c in me.hand] == ["Mogg Toady"] * 3
    assert sorted(c.name for c in me.library) == ["Forest", "Mogg Toady", "Wild Mammoth"]
    assert [c.name for c in me.graveyard] == ["Pack Hunt"]


def test_w1g5_pack_hunt_may_find_fewer(set_pool):
    """"Up to three" is a ceiling (CR 701.23b): one copy in the library is a
    legal whole answer, and so is none."""
    nem = set_pool("NEM")
    game, me = _w1g5_pack_hunt(set_pool, [nem["Mogg Toady"], nem["Wild Mammoth"]])
    game.cast_from_hand(0, "Pack Hunt", target_player_index=1, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(0, [{"zone": "library", "index": 0}])
    game._settle()
    assert [c.name for c in me.hand] == ["Mogg Toady"]


def test_w1g5_pack_hunt_reads_a_copys_name(set_pool):
    """The name is the target's *current* one (CR 707.2 copies the name): a
    Clone copying Mogg Toady is named Mogg Toady, so that is what the search
    looks for — not "Clone", which is only the printed face."""
    nem = set_pool("NEM")
    game, me = _w1g5_pack_hunt(
        set_pool, [nem["Mogg Toady"], set_pool("LEA")["Clone"]],
        targets=("Mogg Toady", "Clone"),
    )
    (clone,) = [p for p in game.controlled_by(1) if p.card.name == "Clone"]
    assert clone.effective_card.name == "Mogg Toady"
    index = game.battlefield_index_of(clone)
    game.cast_from_hand(
        0, "Pack Hunt", target_player_index=1, target_permanent_index=index
    )
    game.resolve_top_of_stack()
    assert game.pending_choice_of("search_library", 0).data["restrictions"]["named"] == (
        "Mogg Toady"
    )


def _w1g5_gambit(set_pool, a_hand, b_hand, *, interactive=()):
    """Stronghold Gambit cast by seat 0 and resolved as far as it goes.
    Headless seats take the stated default — the first card in hand order.
    W1G5's own."""
    me = _W1G5PlayerState(
        name="W1G5-A", hand=[set_pool("NEM")["Stronghold Gambit"], *a_hand]
    )
    them = _W1G5PlayerState(name="W1G5-B", hand=list(b_hand))
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    assert game.cast_from_hand(0, "Stronghold Gambit").supported
    game.resolve_top_of_stack()
    return game, me, them


def _w1g5_names_on(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g5_stronghold_gambit_lowest_revealed_creature_enters(set_pool):
    """"Each player chooses a card in their hand. Then each player reveals
    their chosen card. The owner of each creature card revealed this way with
    the lowest mana value puts it onto the battlefield."

    Seat 0 shows a two-drop and seat 1 a three-drop: only the two-drop enters,
    under its owner, and the three-drop goes back to being a card in a hand —
    revealed, not spent. Both reveals reach the web layer's feed.
    """
    nem = set_pool("NEM")
    game, me, them = _w1g5_gambit(
        set_pool, [nem["Mogg Toady"], nem["Wild Mammoth"]], [nem["Wild Mammoth"]],
    )
    game._settle()

    assert _w1g5_names_on(game, 0) == ["Mogg Toady"]
    assert _w1g5_names_on(game, 1) == []
    assert [c.name for c in them.hand] == ["Wild Mammoth"]
    assert [c.name for c in me.graveyard] == ["Stronghold Gambit"]
    assert [(e["seat"], e["cards"]) for e in game.reveal_events] == [
        (0, ["Mogg Toady"]), (1, ["Wild Mammoth"]),
    ]


def test_w1g5_stronghold_gambit_ties_all_enter_and_lands_do_not_compete(set_pool):
    """"**Each** creature card … with the lowest mana value": two two-drops
    tie and both enter, each on its owner's side. And a revealed land is not a
    creature card, so its mana value of 0 is not "the lowest" — the Mammoth
    across from it enters alone."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, _, _ = _w1g5_gambit(set_pool, [nem["Mogg Toady"]], [nem["Shrieking Mogg"]])
    game._settle()
    assert _w1g5_names_on(game, 0) == ["Mogg Toady"]
    assert _w1g5_names_on(game, 1) == ["Shrieking Mogg"]

    game, me, _ = _w1g5_gambit(set_pool, [lea["Forest"]], [nem["Wild Mammoth"]])
    game._settle()
    assert _w1g5_names_on(game, 0) == []
    assert [c.name for c in me.hand] == ["Forest"]
    assert _w1g5_names_on(game, 1) == ["Wild Mammoth"]


def test_w1g5_stronghold_gambit_keeps_a_pick_hidden_until_the_reveal(set_pool):
    """CR 101.4a: a card chosen out of a hand may stay face down as it is
    chosen. Seat 1 (headless) has chosen by the time seat 0 is asked, and the
    public log says only *that* it chose — the card is named by the reveal,
    after seat 0 answers. The spell stays on the stack until then (CR 608.2)."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, me, _ = _w1g5_gambit(
        set_pool, [lea["Forest"], nem["Wild Mammoth"]], [nem["Rhox"]], interactive=(0,),
    )
    pick = game.pending_choice_of("choose_cards_in_hand", 0)
    assert pick is not None and game.live_choose_cards_in_hand(pick) == [0, 1]
    assert game.stack, "the sorcery is still resolving"
    assert not any("Rhox" in line for line in game.log), "seat 1's pick is face down"
    assert any("W1G5-B chose 1 card(s)" in line for line in game.log)

    assert game.confirm_choose_cards_in_hand(0, [1])
    game._settle()

    assert any("W1G5-B reveals Rhox" in line for line in game.log)
    assert _w1g5_names_on(game, 0) == ["Wild Mammoth"]
    assert [c.name for c in me.hand] == ["Forest"]


def test_w1g5_stronghold_gambit_waits_for_every_seat_in_any_order(set_pool):
    """Two interactive seats owe a pick at once. The first answer (seat 1's,
    out of turn order) reveals nothing and moves nothing: the sorcery resolves
    only when the last seat has chosen, and then compares both cards."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, me, them = _w1g5_gambit(
        set_pool, [nem["Rhox"], nem["Mogg Toady"]], [nem["Wild Mammoth"], lea["Forest"]],
        interactive=(0, 1),
    )
    owed = sorted(c.player_index for c in game.pending_choices if c.kind == "choose_cards_in_hand")
    assert owed == [0, 1]

    assert game.confirm_choose_cards_in_hand(1, [0])
    assert game.stack and game.reveal_events == [], "nothing is revealed yet"
    assert game.confirm_choose_cards_in_hand(0, [0])
    game._settle()

    assert not game.stack
    assert _w1g5_names_on(game, 1) == ["Wild Mammoth"], "3 beats 6"
    assert sorted(c.name for c in me.hand) == ["Mogg Toady", "Rhox"]


def test_w1g5_stronghold_gambit_an_empty_hand_chooses_nothing(set_pool):
    """A player with no cards in hand makes no choice and reveals nothing; the
    other player's card still competes alone."""
    game, _, _ = _w1g5_gambit(set_pool, [set_pool("NEM")["Wild Mammoth"]], [])
    game._settle()
    assert _w1g5_names_on(game, 0) == ["Wild Mammoth"]
    assert [e["seat"] for e in game.reveal_events] == [0]


# --- W1G2: alternative costs and redirects ---
# Mind Swords and Reverent Silence: one of each of Nemesis' alternative-cost
# shapes that was new to the pool (a sacrifice the caster chooses, a life gain
# handed to *every* other player), and the effects behind them.
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g2s_table(set_pool, hands, boards):
    """One seat per entry in *hands*/*boards*, mana costs **enforced** so a
    free cast and an ordinary one are told apart. Cards come from Nemesis,
    then the base set, M21 and Mirage for the basics and the bystanders."""
    pools = (set_pool("NEM"), set_pool("LEA"), set_pool("M21"), set_pool("MIR"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    players = [PlayerState(f"P{seat}") for seat in range(len(hands))]
    for player, hand, board in zip(players, hands, boards):
        player.hand = [card(name) for name in hand]
        player.battlefield.extend(Permanent(card=card(name)) for name in board)
    game = Game(players=players)
    game.enforce_mana_costs = True
    game._sync_control()
    return game


def test_w1g2_mind_swords_sacrifices_the_creature_the_caster_names(set_pool):
    """CR 601.2b: "sacrifice **a** creature" is the caster's choice of which.

    The Hill Giant is named; the deterministic pick (the smallest) would have
    taken the Bears, so a payment that ignored the announcement fails here. A
    name that cannot pay — the opponent's creature — is refused with nothing
    spent, never slid onto a creature the caster did not name.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords"], []],
        boards=[["Swamp", "Grizzly Bears", "Hill Giant"], ["Grizzly Bears"]],
    )
    caster, other = game.players
    theirs = other.battlefield[0]
    refused = game.cast_from_hand(
        0, "Mind Swords", alternative_cost=True,
        alternative_cost_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert len(caster.battlefield) == 3 and [c.name for c in caster.hand] == ["Mind Swords"]

    giant = caster.battlefield[2]
    result = game.cast_from_hand(
        0, "Mind Swords", alternative_cost=True,
        alternative_cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Swamp", "Grizzly Bears"]
    assert [c.name for c in caster.graveyard] == ["Hill Giant", "Mind Swords"]
    assert not any(caster.mana_pool.values())


def test_w1g2_mind_swords_needs_the_printed_swamp(set_pool):
    """No Swamp is no offer (CR 601.2b), and the mana cost stands."""
    game = _w1g2s_table(
        set_pool, hands=[["Mind Swords"], []],
        boards=[["Island", "Grizzly Bears"], []],
    )
    offers = game.cast_cost_offers(0, set_pool("NEM")["Mind Swords"], spell_hand_index=0)
    assert [o for o in offers if o["kind"] == "alternative"] == []
    assert not game.cast_from_hand(0, "Mind Swords", alternative_cost=True).supported
    assert len(game.players[0].battlefield) == 2


def test_w1g2_mind_swords_each_player_exiles_two_of_their_choice(set_pool):
    """"Each player exiles two cards from their hand."

    Each seat chooses out of its own hidden hand (CR 400.2), in turn order
    (CR 101.4). The interactive seat is asked twice and its answers are the
    cards that leave; the other seat takes the default. A seat holding one card
    exiles that one (CR 608.2: as much as possible). The cards go to exile —
    not to a graveyard, which would be a discard (CR 701.9a) and would fire
    every "whenever a player discards" watcher.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords", "Shock", "Giant Growth", "Forest"], ["Island"]],
        boards=[["Swamp", "Grizzly Bears"], []],
    )
    game.interactive_seats = {0}
    caster, other = game.players

    assert game.cast_from_hand(0, "Mind Swords", alternative_cost=True).supported
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert owed == [("exile_from_hand_choice", 0)] * 2
    assert other.hand == [] and [c.name for c in other.exile] == ["Island"]

    assert game.confirm_exile_from_hand_choice(0, 2)   # Forest
    assert game.confirm_exile_from_hand_choice(0, 0)   # Shock
    resolve_stack(game)

    assert [c.name for c in caster.hand] == ["Giant Growth"]
    assert sorted(c.name for c in caster.exile) == ["Forest", "Shock"]
    assert [c.name for c in caster.graveyard] == ["Grizzly Bears", "Mind Swords"]
    assert game.pending_choices == []


def test_w1g2_mind_swords_pick_is_mandatory(set_pool):
    """The printed sentence is not an offer: the prompt refuses a decline,
    because a decline would be a Mind Swords that exiles nothing."""
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords", "Shock"], []],
        boards=[["Swamp", "Grizzly Bears"], []],
    )
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Mind Swords", alternative_cost=True)

    assert not game.confirm_exile_from_hand_choice(0, None)
    assert game.confirm_exile_from_hand_choice(0, 0)
    assert [c.name for c in game.players[0].exile] == ["Shock"]


def test_w1g2_reverent_silence_hands_every_other_player_six_life(set_pool):
    """"…rather than pay this spell's mana cost, you may have **each other
    player** gain 6 life."

    Invigorate's price paid to every other seat rather than to one: at a
    three-player table both opponents gain and the caster does not. Then the
    spell destroys every enchantment, the caster's own included.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Reverent Silence"], [], []],
        boards=[["Forest", "Pacifism"], ["Pacifism"], []],
    )
    caster, left, right = game.players

    result = game.cast_from_hand(0, "Reverent Silence", alternative_cost=True)
    resolve_stack(game)

    assert result.supported, result.details
    assert (caster.life, left.life, right.life) == (20, 26, 26)
    assert [p.card.name for p in caster.battlefield] == ["Forest"]
    assert left.battlefield == []
    assert not any(caster.mana_pool.values())


def test_w1g2_reverent_silence_is_unpayable_if_any_player_cannot_gain(set_pool):
    """CR 119.7: "a cost that involves having that player gain life can't be
    paid." Every other player is that player here, so one who cannot gain makes
    the whole price unpayable — where Invigorate's caster could hand the life
    to another opponent. Shown, marked unpayable, and refused with nothing
    paid."""
    game = _w1g2s_table(
        set_pool,
        hands=[["Reverent Silence"], []],
        boards=[["Forest"], ["Forsaken Wastes"]],
    )
    offers = game.cast_cost_offers(
        0, set_pool("NEM")["Reverent Silence"], spell_hand_index=0
    )
    assert [(o["label"], o["payable"]) for o in offers if o["kind"] == "alternative"] == [
        ("have each other player gain 6 life", False)
    ]
    refused = game.cast_from_hand(0, "Reverent Silence", alternative_cost=True)
    assert not refused.supported and "CR 119.7" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Reverent Silence"]


# --- W1G4: amounts and bounded targets ---
# Four sorceries whose number or whose target is read off the board: Flowstone
# Slide's announced X signed both ways over a sweep, Rupture's power frozen as
# its own first sentence sacrifices the creature, Stronghold Discipline's one
# count per losing seat, and Topple's superlative as a *target restriction*.
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_sorcery_creature(name, power, toughness, keywords=()):
    """A test creature; keywords are printed as its only line."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="", cmc=0.0, type_line=line,
        oracle_text=", ".join(word.capitalize() for word in keywords),
        colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_sorcery_table(hand, seat0=(), seat1=()):
    """Two seats, costs unenforced, P0 holding *hand* in its main phase."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), hand=list(hand)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_flowstone_slide_pumps_power_and_shrinks_toughness_by_x(set_pool):
    """"All creatures get +X/-X until end of turn."

    Both seats' creatures, X the announced one. A creature whose toughness
    reaches 0 dies to the state-based check (CR 704.5f) — not destruction, so
    nothing could regenerate it. The sweep used to resolve every "x" at 0 when
    no count sized it; it now falls back to the announced X like the targeted
    pumps beside it.
    """
    slide = set_pool("NEM")["Flowstone Slide"]
    small = _W1g4Permanent(card=_w1g4_sorcery_creature("Small 2/2", 2, 2))
    sturdy = _W1g4Permanent(card=_w1g4_sorcery_creature("Sturdy 1/3", 1, 3))
    game = _w1g4_sorcery_table((slide,), (small,), (sturdy,))

    result = game.cast_from_hand(0, "Flowstone Slide", x_value=2)

    assert result.supported, result
    assert not game.is_on_battlefield(small)
    assert "Small 2/2 died (704.5f: toughness 0)" in game.log
    assert (sturdy.effective_power, sturdy.effective_toughness) == (3, 1)


def test_w1g4_rupture_deals_the_sacrificed_creatures_power(set_pool):
    """"Sacrifice a creature. Rupture deals damage equal to that creature's
    power to each creature without flying and each player."

    "That creature" is the one the first sentence sacrificed; by the time the
    damage is dealt it is a card in a graveyard with no computed power at all
    (CR 613.1), so the power is frozen as it is sacrificed (CR 608.2h) — the
    record the destroy step writes for the same words. The flier is spared, the
    caster is hit too.
    """
    rupture = set_pool("NEM")["Rupture"]
    big = _W1g4Permanent(card=_w1g4_sorcery_creature("Big 4/4", 4, 4))
    bird = _W1g4Permanent(card=_w1g4_sorcery_creature("Bird 1/1", 1, 1, ("flying",)))
    ogre = _W1g4Permanent(card=_w1g4_sorcery_creature("Ogre 3/3", 3, 3))
    game = _w1g4_sorcery_table((rupture,), (big,), (bird, ogre))
    assert _w1g4_cast_spec(rupture, _w1g4_compile(rupture)) is None

    result = game.cast_from_hand(0, "Rupture")

    assert result.supported, result
    assert not game.is_on_battlefield(big)
    assert not game.is_on_battlefield(ogre)
    assert game.is_on_battlefield(bird)
    assert (game.players[0].life, game.players[1].life) == (16, 16)


def test_w1g4_rupture_with_nothing_to_sacrifice_deals_nothing(set_pool):
    """No creature sacrificed, so "that creature's power" names nothing and the
    damage is zero rather than a number the card never printed."""
    rupture = set_pool("NEM")["Rupture"]
    ogre = _W1g4Permanent(card=_w1g4_sorcery_creature("Ogre 3/3", 3, 3))
    game = _w1g4_sorcery_table((rupture,), (), (ogre,))

    game.cast_from_hand(0, "Rupture")

    assert game.is_on_battlefield(ogre)
    assert ogre.damage_marked == 0
    assert (game.players[0].life, game.players[1].life) == (20, 20)


def test_w1g4_stronghold_discipline_counts_each_losers_own_creatures(set_pool):
    """"Each player loses 1 life for each creature they control."

    One number per seat, counted on that seat's own battlefield — the
    per-recipient channel the damage sweeps read for "that player controls".
    A single shared count would cost both players the same.
    """
    discipline = set_pool("NEM")["Stronghold Discipline"]
    mine = [_W1g4Permanent(card=_w1g4_sorcery_creature(f"Mine {i}", 1, 1)) for i in range(2)]
    theirs = [_W1g4Permanent(card=_w1g4_sorcery_creature(f"Theirs {i}", 1, 1)) for i in range(3)]
    game = _w1g4_sorcery_table((discipline,), mine, theirs)

    game.cast_from_hand(0, "Stronghold Discipline")

    assert (game.players[0].life, game.players[1].life) == (18, 17)


def test_w1g4_topple_offers_only_the_creatures_tied_for_greatest_power(set_pool):
    """"Exile target creature with the greatest power among creatures on the
    battlefield." CR 601.2c: the superlative is a restriction on what may be
    named, so the picker offers only the tied-greatest — on either battlefield
    — and an announcement naming a smaller creature is refused before the
    spell is paid for."""
    topple = set_pool("NEM")["Topple"]
    mine = _W1g4Permanent(card=_w1g4_sorcery_creature("Mine 4/4", 4, 4))
    rival = _W1g4Permanent(card=_w1g4_sorcery_creature("Rival 4/1", 4, 1))
    small = _W1g4Permanent(card=_w1g4_sorcery_creature("Small 2/2", 2, 2))
    game = _w1g4_sorcery_table((topple,), (mine,), (rival, small))

    offered = {
        entry["name"] for entry in game.cast_target_spec(0, topple)["valid_targets"]
    }
    assert offered == {"Mine 4/4", "Rival 4/1"}
    refused = game.cast_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[small.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(small) and [c.name for c in game.players[0].hand] == ["Topple"]

    game.cast_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[rival.permanent_id],
    )
    assert not game.is_on_battlefield(rival)
    assert [card.name for card in game.players[1].exile] == ["Rival 4/1"]


def test_w1g4_topple_exiles_nothing_once_its_target_is_no_longer_the_greatest(
    set_pool,
):
    """The restriction is asked again at resolution (CR 608.2b): pump a rival
    past the target in response and the target is illegal, so nothing is
    exiled — and in particular not the creature that is now the greatest."""
    from engine.pt import add_pt_modifier

    topple = set_pool("NEM")["Topple"]
    mine = _W1g4Permanent(card=_w1g4_sorcery_creature("Mine 4/4", 4, 4))
    rival = _W1g4Permanent(card=_w1g4_sorcery_creature("Rival 4/1", 4, 1))
    game = _w1g4_sorcery_table((topple,), (mine,), (rival,))

    queued = game.queue_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[rival.permanent_id],
    )
    assert queued.supported, queued
    add_pt_modifier(mine, 1, 0)
    _w1g4_resolve(game)

    assert game.is_on_battlefield(rival) and game.is_on_battlefield(mine)
    assert game.players[0].exile == [] and game.players[1].exile == []
