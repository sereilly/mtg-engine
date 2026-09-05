"""Per-card tests for Visions' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. A branch that added an import to a shared header loses it in the
mechanical "take ours, append the branch's block" merge — a ``NameError`` at
collection, found only after the merge is committed. A self-contained block
cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations
from engine import Game, PlayerState
from engine import Game as _W2G1sGame, PlayerState as _W2G1sPlayerState
from engine.models import Permanent as _W2G1sPermanent
from engine.card_loader import load_cards as _w2g1s_load, manifest_set_path as _w2g1s_path
from engine.cast_costs import additional_cost_for_line as _w2g1s_add_line
from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.card_loader import load_cards as _w2g2_load
from engine.card_loader import manifest_set_paths as _w2g2_paths
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile

def _w1g2_game():
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    return game
def test_summer_bloom_grants_three_more_land_drops_this_turn(set_pool):
    """"You may play up to three additional lands this turn." (CR 305.2.)

    Not a ``may`` wrapper: the word is the permission, not an offer taken at
    resolution, and wrapping it would put a yes/no prompt in front of a card
    that prints no decision.
    """
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]

    result = game.cast_from_hand(0, "Summer Bloom")
    assert result.supported, result.details
    game.resolve_stack()

    for played in range(4):
        assert game._may_play_another_land(0), f"land drop {played + 1} of 4"
        game.lands_played_this_turn[0] = played + 1
    assert not game._may_play_another_land(0), "one plus three, and no more"
def test_summer_bloom_grants_nothing_to_the_other_seat(set_pool):
    """"**You** may play…" — CR 109.5's controller, and nobody else."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.lands_played_this_turn[1] = 1
    assert not game._may_play_another_land(1)
def test_summer_bloom_s_grant_ends_with_the_turn(set_pool):
    """"…**this turn**." The record is cleared at the turn boundary beside the
    per-turn count it adds to."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.start_turn(0)

    game.lands_played_this_turn[0] = 1
    assert not game._may_play_another_land(0)
def test_two_summer_blooms_add_up(set_pool):
    """Two resolutions of one effect grant six, not three: a ceiling the second
    copy merely re-asserted would make it free."""
    game = _w1g2_game()
    bloom = set_pool("VIS")["Summer Bloom"]
    game.players[0].hand = [bloom, bloom]
    for _ in range(2):
        game.cast_from_hand(0, "Summer Bloom")
        game.resolve_stack()

    game.lands_played_this_turn[0] = 6
    assert game._may_play_another_land(0)
    game.lands_played_this_turn[0] = 7
    assert not game._may_play_another_land(0)
_W2G1S_LEA = {c.name: c for c in _w2g1s_load(_w2g1s_path("LEA"))}
def _w2g1s_scene(hand, swamps, opposing=()):
    p1 = _W2G1sPlayerState(name="A", hand=list(hand))
    p2 = _W2G1sPlayerState(name="B")
    game = _W2G1sGame(players=[p1, p2])
    game.enforce_mana_costs = False
    for _ in range(swamps):
        p1.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA["Swamp"]))
    for name in opposing:
        p2.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA[name]))
    return game, p1, p2
def test_infernal_harvest_returns_x_swamps_and_deals_that_much(set_pool):
    """CR 107.3a: an X in an **additional** cost is announced as the spell is
    cast, and Infernal Harvest's printed mana cost has no {X} in it at all —
    this clause is the only place its X lives.

    Before the cost was read the card dealt its damage for {1}{B} with no
    Swamp returned, which is the defect this whole block exists for.
    """
    game, caster, victim = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=3,
        opposing=("Mons's Goblin Raiders", "Hurloon Minotaur"),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=2, divided_targets=[(1, 0), (1, 1)],
    )

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Swamp"]
    assert [c.name for c in caster.hand] == ["Swamp", "Swamp"]
    # 1 damage each: the Goblin dies, the Minotaur survives.
    assert [p.card.name for p in victim.battlefield] == ["Hurloon Minotaur"]
def test_infernal_harvest_refuses_an_x_the_board_cannot_pay(set_pool):
    """CR 601.2h: three Swamps is no payment for an X of four, and the refusal
    costs the caster nothing."""
    game, caster, _ = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=2,
        opposing=("Hurloon Minotaur",),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=3, divided_targets=[(1, 0)],
    )

    assert not result.supported
    assert "CR 601.2h" in result.details
    assert len(caster.battlefield) == 2
    assert [c.name for c in caster.hand] == ["Infernal Harvest"]
def test_the_return_cost_reads_the_printed_destination():
    """The zone is part of the clause: the payment reaches one hand, and a
    sentence naming another destination refuses rather than being charged
    against it."""
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X Swamps you "
        "control to the graveyard."
    ) is None
    # …and an un-narrowed noun phrase is refused for the reason every other
    # counted cost's is: it would let the payment eat anything the caster has.
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X permanents you "
        "control to their owner's hand."
    ) is None

def _w2g2_catalog():
    return {card.name: card for card in _w2g2_load(_w2g2_paths(include_measured=True))}
def _w2g2_slot(player, permanent):
    return next(i for i, perm in enumerate(player.battlefield) if perm is permanent)
def _w2g2_peace_talks_board(set_pool):
    """Two seats, a creature each, and Peace Talks in the first one's hand."""
    catalog = _w2g2_catalog()
    bear = _W2G2Permanent(card=catalog["Grizzly Bears"])
    hill = _W2G2Permanent(card=catalog["Hill Giant"])
    p1 = _W2G2PlayerState(
        name="P1",
        battlefield=[bear],
        hand=[set_pool("VIS")["Peace Talks"], catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    p2 = _W2G2PlayerState(
        name="P2",
        battlefield=[hill],
        hand=[catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    game = _W2G2Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for player in (p1, p2):
        for perm in player.battlefield:
            perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    return game, bear, hill
def _w2g2_end_turn(game):
    seat = game.active_player_index
    game.resolve_end_step(seat)
    game.resolve_cleanup_step(seat)
def _w2g2_to_declare_attackers(game):
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
def test_peace_talks_compiles_both_clauses_over_one_window(set_pool):
    """"This turn and next turn, creatures can't attack, and players and
    permanents can't be the targets of spells or activated abilities."

    One leading duration over two effects, so the window is distributed to
    both. Two instructions rather than one fused kind, because they are
    enforced in two different places (CR 508.1c's declaration and CR 115.1's
    choice) -- and both carry the same two-turn count.
    """
    program = _w2g2_compile(set_pool("VIS")["Peace Talks"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["cant_attack_until_eot", "ban_targeting"]
    assert [step.payload["remaining_turns"] for step in steps] == [2, 2]
def test_peace_talks_stops_attacks_and_targeting_on_the_turn_it_resolves(set_pool):
    """Both clauses, watched as refusals.

    A restriction nothing enforces looks exactly like one that works, so each
    half is checked by an action being declined: a Lightning Bolt that never
    reaches its face, and a declaration the attack gate refuses.
    """
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)

    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported, game.log
    assert game.players[1].life == 20

    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]
def test_peace_talks_still_binds_the_opponent_on_the_next_turn(set_pool):
    """"And next turn" is the half a one-turn sweep would silently drop -- and
    it is the half the caster paid for, because the turn it resolves in is
    their own."""
    game, _bear, hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    _w2g2_end_turn(game)
    game.start_next_turn()

    assert game.active_player_index == 1
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 20
    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(1, [_w2g2_slot(game.players[1], hill)])[0]
def test_peace_talks_ends_after_the_second_cleanup(set_pool):
    """Two cleanups and no more: a window that outlived them would be a
    permanent effect the card never printed, which is the other direction and
    just as silent."""
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    for _ in range(2):
        _w2g2_end_turn(game)
        game.start_next_turn()

    assert game.targeting_bans == []
    assert game.attack_restrictions_until_eot == []
    assert game.active_player_index == 0
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17
    _w2g2_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]
def test_peace_talks_stops_an_aura_spell_too(set_pool):
    """An Aura spell is targeted (CR 115.1b) and its enchant line is the
    target, so the ban reaches it — where a creature spell with an
    enters-the-battlefield trigger is untouched, because that trigger's targets
    are chosen when it goes on the stack (CR 603.3d) and not at the cast.

    The two together are the line: gating a permanent spell on a spec it does
    not own would refuse to cast the creature at all.
    """
    catalog = _w2g2_catalog()
    game, _bear, _hill = _w2g2_peace_talks_board(set_pool)
    game.players[0].hand.extend([catalog["Pacifism"], set_pool("VIS")["Nekrataal"]])
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    aura = game.cast_from_hand(
        0, "Pacifism", target_player_index=1, target_permanent_index=0
    )
    assert not aura.supported, game.log

    assert game.cast_from_hand(0, "Nekrataal").supported, game.log
def test_peace_talks_stops_an_activated_ability_aimed_at_a_face(set_pool):
    """CR 602.2b routes an activation through CR 601.2c, so an ability that
    must choose a target and has none legal cannot be begun.

    Rod of Ruin is the shape the picker-side check cannot see: "deals 1 damage
    to any target" names no permanent when it is aimed at a player, so every
    gate keyed on a named permanent index let it through. A targetless mana
    ability is untouched -- the ban is about being chosen, not about acting.
    """
    catalog = _w2g2_catalog()
    game, _bear, _hill = _w2g2_peace_talks_board(set_pool)
    rod = _W2G2Permanent(card=catalog["Rod of Ruin"])
    birds = _W2G2Permanent(card=catalog["Birds of Paradise"])
    for perm in (rod, birds):
        perm.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(perm)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    refused = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)
    assert not refused.supported, game.log
    assert game.players[1].life == 20

    assert game.activate_permanent_ability(
        0, "Birds of Paradise", mana_color="G"
    ).supported, game.log


# --- W3G3: Forbidden Ritual, a process its controller may run again ---
from engine import Game as _W3G3Game, PlayerState as _W3G3Player
from engine.models import Permanent as _W3G3Permanent
from engine.oracle import compile_card_oracle as _w3g3_compile
from engine.targeting import derive_cast_spec as _w3g3_cast_spec


def _w3g3_game(interactive=()):
    game = _W3G3Game(players=[
        _W3G3Player(name="P1", battlefield=[]),
        _W3G3Player(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w3g3_put(game, seat, card):
    perm = _W3G3Permanent(card=card)
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def _w3g3_kinds(instruction):
    """Every instruction kind inside *instruction*, outermost first."""
    found = [instruction.kind]
    for value in (instruction.payload or {}).values():
        for entry in (value if isinstance(value, (list, tuple)) else ()):
            inner = entry.get("instruction") if isinstance(entry, dict) else entry
            if getattr(inner, "kind", None) is not None:
                found.extend(_w3g3_kinds(inner))
    return found


def test_forbidden_ritual_compiles_the_whole_printed_process(set_pool):
    """"Sacrifice a nontoken permanent. If you do, target opponent loses 2 life
    unless that player sacrifices a permanent of their choice or discards a
    card. You may repeat this process any number of times."

    Three sentences and one instruction, because the repetition is a property
    of the process rather than a step after it — whatever asks "again?" has to
    be holding the round it would run.
    """
    program = _w3g3_compile(set_pool("VIS")["Forbidden Ritual"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "repeat_optional_process"
    kinds = _w3g3_kinds(instruction)
    # The price is a *choice* between two prices, which is the same node
    # "sacrifice a creature or discard a creature card" already produces.
    assert "choose_one" in kinds
    assert kinds.count("sacrifice_matching_permanent") == 2, kinds


def test_forbidden_ritual_offers_the_price_to_the_targeted_opponent(set_pool):
    """CR 601.2b: the seat taking the offer picks which price it pays, and the
    permanent it gives up comes off *its* battlefield (CR 701.21a)."""
    game = _w3g3_game()
    game.players[0].hand = [set_pool("VIS")["Forbidden Ritual"]]
    _w3g3_put(game, 0, set_pool("VIS")["Panther Warriors"])
    theirs = _w3g3_put(game, 1, set_pool("VIS")["Panther Warriors"])

    assert game.cast_from_hand(
        0, "Forbidden Ritual", target_player_index=1
    ).supported, game.log
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    # The caster gave up their own nontoken permanent; the opponent covered the
    # toll out of theirs, so no life was lost.
    assert game.players[0].battlefield == []
    assert theirs not in game.players[1].battlefield
    assert game.players[1].life == 20, game.log


def test_forbidden_ritual_charges_the_life_when_the_price_cannot_be_paid(set_pool):
    """An opponent with an empty board and an empty hand can take neither
    alternative, so the printed penalty stands (CR 601.2h asks what a player is
    *able* to do). The chosen discard was the half nobody gated: an empty hand
    discarded nothing and the offer counted as taken."""
    game = _w3g3_game()
    game.players[0].hand = [set_pool("VIS")["Forbidden Ritual"]]
    _w3g3_put(game, 0, set_pool("VIS")["Panther Warriors"])

    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert game.players[1].life == 18, game.log


def test_forbidden_ritual_asks_the_opponent_which_price_they_pay(set_pool):
    """The offer, the mode choice and the sacrifice all belong to the seat the
    spell targeted. ``_offer_to_seat`` deliberately leaves ``context.caster``
    where it is, so without a chooser on the ``choose_one`` the *caster* would
    pick which price their opponent paid, out of the opponent's own board."""
    game = _w3g3_game(interactive={1})
    game.players[0].hand = [set_pool("VIS")["Forbidden Ritual"]]
    _w3g3_put(game, 0, set_pool("VIS")["Panther Warriors"])
    _w3g3_put(game, 1, set_pool("VIS")["Panther Warriors"])

    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    game.resolve_stack()

    owed = game.pending_choice_of("optional_pay")
    assert owed is not None and owed.player_index == 1, game.pending_choices


def test_forbidden_ritual_repeats_the_whole_process_when_its_caster_says_so(set_pool):
    """"You may repeat this process **any number of times**." One decision per
    round, taken by the spell's controller, with no bound but the answer — so
    two accepted rounds cost two of the caster's permanents and two of the
    opponent's."""
    game = _w3g3_game(interactive={0})
    game.players[0].hand = [set_pool("VIS")["Forbidden Ritual"]]
    for _ in range(3):
        _w3g3_put(game, 0, set_pool("VIS")["Panther Warriors"])
        _w3g3_put(game, 1, set_pool("VIS")["Panther Warriors"])

    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    game.resolve_stack()

    rounds = 0
    while True:
        owed = game.pending_choice_of("sacrifice")
        if owed is not None and owed.player_index == 0:
            assert game.confirm_sacrifice(0, [0]), game.log
            game.auto_resolve_pending_choices(only_player_index=1)
            continue
        again = game.pending_choice_of("repeat_process")
        if again is None:
            break
        assert again.player_index == 0, "the controller decides whether to repeat"
        rounds += 1
        assert game.confirm_repeat_process(0, rounds < 2), game.log
        game.auto_resolve_pending_choices(only_player_index=1)

    assert rounds == 2, game.log
    assert len(game.players[0].battlefield) == 1, game.log
    assert len(game.players[1].battlefield) == 1, game.log
    assert game.players[1].life == 20, game.log
    assert game.stack == [] and game.resume_stack == []


def test_forbidden_ritual_stops_after_one_round_for_a_seat_nobody_asks(set_pool):
    """The stated default is to stop. "Any number of times" has no bound but
    the answer, so a default of "yes" is not a default — it is a game that never
    ends."""
    game = _w3g3_game()
    game.players[0].hand = [set_pool("VIS")["Forbidden Ritual"]]
    for _ in range(3):
        _w3g3_put(game, 0, set_pool("VIS")["Panther Warriors"])

    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert len(game.players[0].battlefield) == 2, game.log


def test_forbidden_ritual_asks_the_client_for_its_opponent(set_pool):
    """The Roots class: the spell's only "target" sits on the offer's *declined*
    branch, three wrappers down. A cast spec of None is the exact value the
    client tests to decide whether to ask for a target, so it would send a bare
    cast and the engine would refuse it."""
    card = set_pool("VIS")["Forbidden Ritual"]
    spec = _w3g3_cast_spec(card, _w3g3_compile(card))
    assert spec is not None and spec.get("kind") == "player", spec
