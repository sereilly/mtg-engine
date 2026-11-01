"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# --- W1G7: players and odd ends ----------------------------------------------
from engine import Game as _w1g7_Game
from engine.models import Permanent as _w1g7_Permanent
from engine.models import PlayerState as _w1g7_PlayerState

from tests.helpers import _nosick as _w1g7_nosick
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


#: Where a W1G7 test finds a card by name: Legions first, then Alpha (the
#: lands and the old regulars), then Arabian Nights (Old Man of the Sea).
_W1G7_SETS = ("LGN", "LEA", "ARN")


def _w1g7_card(set_pool, name):
    """A card by name from the first of :data:`_W1G7_SETS` that prints it."""
    for code in _W1G7_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g7_table(set_pool, hands=None, *, libraries=None, seats=2, interactive=()):
    """A *seats*-player table, Alice active, costs unenforced."""
    hands = hands or {}
    libraries = libraries or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g7_PlayerState(
            name=name,
            hand=[_w1g7_card(set_pool, c) for c in hands.get(seat, ())],
            library=[
                _w1g7_card(set_pool, c)
                for c in libraries.get(seat, ["Plains"] * 8)
            ],
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g7_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g7_put(game, set_pool, seat, name, *, tapped=False):
    """Put *name* onto *seat*'s battlefield by an effect (never cast)."""
    permanent = _w1g7_Permanent(card=_w1g7_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve_stack(game)
    _w1g7_nosick(permanent)
    permanent.tapped = tapped
    return permanent


def _w1g7_finish_combat(game):
    """Step from declare-blockers through the damage, draining each trigger."""
    for _ in range(12):
        _w1g7_resolve_stack(game)
        if game.current_phase != "combat" or game.pending_choices:
            return
        game.advance_combat_phase()


def _w1g7_names(cards):
    return [card.name for card in cards]


# --- Phage the Untouchable ----------------------------------------------------


def test_w1g7_phage_cast_from_a_hand_keeps_its_controller_in_the_game(set_pool):
    """"When Phage enters, if you didn't cast it from your hand, you lose the
    game." Cast from Alice's hand, the intervening-if (CR 603.4) is false when
    the permanent enters, so nothing triggers and nobody loses."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    assert _w1g7_names(p.card for p in game.controlled_by(0)) == ["Phage the Untouchable"]
    assert not game.players[0].lost
    assert any("didn't trigger" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_put_onto_the_battlefield_loses_the_game(set_pool):
    """The ruling (2004-10-04): "Putting it onto the battlefield from your
    hand using a spell or ability will cause you to lose the game." A Phage
    that was never cast has no cast stamp, so its controller loses."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Phage the Untouchable")
    assert game.players[0].lost
    assert not game.players[1].lost
    assert any("Alice lost the game" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_destroys_what_it_damages_past_regeneration(set_pool):
    """"Whenever Phage deals combat damage to a creature, destroy that
    creature. It can't be regenerated." Drudge Skeletons with two shields
    spends one on the lethal combat damage and the second cannot save it from
    the trigger; a Wall of Stone that survives the damage is destroyed too."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    skeletons = _w1g7_put(game, set_pool, 1, "Drudge Skeletons")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    for _ in range(2):
        assert game.activate_permanent_ability(
            1, "Drudge Skeletons",
            permanent_index=game.battlefield_index_of(skeletons),
        ).supported
        _w1g7_resolve_stack(game)
    _w1g7_finish_combat(game)
    assert "Drudge Skeletons regenerated" in game.log
    assert "Phage the Untouchable destroyed Drudge Skeletons" in game.log
    assert _w1g7_names(game.players[1].graveyard) == ["Drudge Skeletons"]

    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_put(game, set_pool, 1, "Wall of Stone")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_finish_combat(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Wall of Stone"]
    assert not game.players[1].lost


def test_w1g7_phage_unblocked_makes_the_damaged_player_lose(set_pool):
    """"Whenever Phage deals combat damage to a player, that player loses the
    game." Bob takes four and loses; Alice, who cast Phage, does not."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 16
    assert game.players[1].lost
    assert not game.players[0].lost


# --- Riptide Mangler ----------------------------------------------------------


def test_w1g7_riptide_mangler_takes_a_targets_power_and_keeps_it(set_pool):
    """"{1}{U}: This creature's base power becomes equal to target creature's
    power. (This effect lasts indefinitely.)" Layer 7b (CR 613.4b): the 0/3
    becomes 6/3 off a Craw Wurm, toughness untouched; a Giant Growth applies on
    top (the 2015-02-25 ruling); a second activation overwrites the first
    (the other 2015-02-25 ruling); and the write outlasts the turn's
    cleanup."""
    game = _w1g7_table(set_pool, hands={0: ["Giant Growth"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (6, 3)
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)

    assert game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[mangler.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (9, 6)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (5, 6)

    game.resolve_cleanup_step(0)
    assert (mangler.effective_power, mangler.effective_toughness) == (2, 3)


def test_w1g7_riptide_mangler_fizzles_when_its_target_leaves(set_pool):
    """CR 608.2b: the Wurm exiled in response leaves the ability with no legal
    target, so it does nothing — the Mangler stays 0/3 rather than reading the
    power of a creature that is gone."""
    game = _w1g7_table(set_pool, hands={0: ["Swords to Plowshares"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)
    assert any("every target is illegal" in line for line in game.log)


# --- Seedborn Muse ------------------------------------------------------------


def _w1g7_tapped(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.tapped)


def test_w1g7_seedborn_muse_untaps_its_controllers_board_in_the_other_step(set_pool):
    """"Untap all permanents you control during each other player's untap
    step." In Bob's untap step Alice untaps everything, including a Basalt
    Monolith ("doesn't untap during your untap step") and a Sunstrike
    Legionnaire ("doesn't untap during your untap step") — the 2004-10-04
    ruling: a restriction printed about its controller's step does not bind
    this one. Bob's own Winter Orb caps *his* step at one land and does not
    touch Alice's lands, which untap in a step that is not hers. In Alice's
    own step the Monolith and the Legionnaire stay tapped and the Orb caps
    her lands at one."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 1, "Grizzly Bears", tapped=True)
    for name in ("Seedborn Muse", "Basalt Monolith", "Sunstrike Legionnaire",
                 "Forest", "Forest"):
        _w1g7_put(game, set_pool, 0, name, tapped=True)
    _w1g7_put(game, set_pool, 1, "Winter Orb")
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Island"], "Winter Orb still caps Bob's own step"
    assert (
        "Alice untapped 5 permanent(s) during Bob's untap step (Seedborn Muse)"
        in game.log
    )

    for permanent in game.controlled_by(0):
        permanent.tapped = True
    game.active_player_index = 0
    game.resolve_untap_step(0)
    assert _w1g7_tapped(game, 0) == [
        "Basalt Monolith", "Forest", "Sunstrike Legionnaire",
    ]


def test_w1g7_seedborn_muse_gives_old_man_of_the_sea_no_choice(set_pool):
    """The 2007-07-15 ruling: "You have no choice about what untaps." Alice's
    Old Man of the Sea ("You may choose not to untap this creature during your
    untap step") untaps in Bob's step with nobody asked — even with both seats
    interactive — and the Grizzly Bears it held go back to Bob."""
    game = _w1g7_table(set_pool, interactive={0, 1})
    _w1g7_put(game, set_pool, 0, "Seedborn Muse")
    old_man = _w1g7_put(game, set_pool, 0, "Old Man of the Sea")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert game.queue_permanent_ability(
        0, "Old Man of the Sea", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert game.controller_index_of(bears) == 0 and old_man.tapped

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert game.pending_choices == []
    assert not old_man.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g7_seedborn_muse_does_nothing_in_a_skipped_step_or_its_own(set_pool):
    """A skipped untap step (Stasis, CR 500.11) is not an untap step at all,
    so the Muse has none to act in. At three seats it acts in each other
    player's step and in no one else's favour: in Cara's step Alice untaps,
    Bob — who has no Muse — does not."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Stasis")
    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == ["Seedborn Muse"]

    game = _w1g7_table(set_pool, seats=3)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Forest", tapped=True)
    _w1g7_put(game, set_pool, 2, "Forest", tapped=True)
    game.active_player_index = 2
    game.resolve_untap_step(2)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Forest"]
    assert _w1g7_tapped(game, 2) == []


# --- Goblin Assassin ----------------------------------------------------------


def _w1g7_rig_coins(monkeypatch, faces):
    """Each flip the handler makes, in order: True is heads."""
    queue = list(faces)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: queue.pop(0)
    )
    return queue


def _w1g7_board(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g7_goblin_assassin_tails_sacrifices_heads_does_not(set_pool, monkeypatch):
    """"Whenever this creature or another Goblin enters, each player flips a
    coin. Each player whose coin comes up tails sacrifices a creature of their
    choice." Alice's coin comes up heads and Bob's tails: only Bob gives up a
    creature (the cheaper, by the nobody-asked default), and nobody wins or
    loses a flip (the 2004-10-04 ruling) — the log names faces, not wins."""
    coins = _w1g7_rig_coins(monkeypatch, [True, False])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == []
    assert _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Craw Wurm"]
    assert "Goblin Assassin: Alice flipped heads" in game.log
    assert "Goblin Assassin: Bob flipped tails" in game.log
    assert not any("won the coin flip" in line for line in game.log)


def test_w1g7_goblin_assassin_asks_each_tails_seat_which_creature(set_pool, monkeypatch):
    """Both coins tails, both seats interactive: each is asked for a creature
    of their choice, and each answer is what goes. Alice may give up the
    Assassin itself."""
    _w1g7_rig_coins(monkeypatch, [False, False])
    game = _w1g7_table(
        set_pool, hands={0: ["Goblin Assassin"]}, interactive={0, 1},
    )
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    game.resolve_top_of_stack()
    assert not game.resolve_top_of_stack(), "the trigger waits for its answers"
    assert sorted(c.player_index for c in game.pending_choices if c.kind == "sacrifice") == [0, 1]
    assassin = next(
        p for p in game.controlled_by(0) if p.card.name == "Goblin Assassin"
    )
    wurm = next(p for p in game.controlled_by(1) if p.card.name == "Craw Wurm")
    assert game.confirm_sacrifice(0, [game.battlefield_index_of(assassin)])
    assert game.confirm_sacrifice(1, [game.battlefield_index_of(wurm)])
    _w1g7_resolve_stack(game)
    assert _w1g7_board(game, 0) == ["Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Grizzly Bears"]


def test_w1g7_goblin_assassin_hears_another_goblin_and_no_one_else(set_pool, monkeypatch):
    """Another Goblin entering (Mons's Goblin Raiders) fires it again; a Craw
    Wurm entering fires nothing — no coin is drawn for it."""
    coins = _w1g7_rig_coins(monkeypatch, [True, True])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == [] and _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]

    coins.extend([False, True])
    _w1g7_put(game, set_pool, 0, "Mons's Goblin Raiders")
    assert coins == []
    assert len(game.players[0].graveyard) == 1
    assert len(_w1g7_board(game, 0)) == 2

    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert _w1g7_board(game, 1) == ["Craw Wurm"]


# --- Hollow Specter -----------------------------------------------------------

_W1G7_BOB_HAND = ["Lightning Bolt", "Plains", "Shivan Dragon", "Island", "Giant Growth"]


def _w1g7_specter_hits(set_pool, bob_hand, swamps, *, interactive):
    """Alice's Hollow Specter connects with Bob; returns the game with the
    trigger's resolution started and held on Alice's prompt. Alice must be
    interactive: a seat nobody asks is answered as the trigger resolves."""
    game = _w1g7_table(set_pool, hands={1: bob_hand}, interactive=interactive)
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(swamps):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    for _ in range(6):
        if game.stack:
            break
        game.advance_combat_phase()
    assert [item.card.name for item in game.stack] == ["Hollow Specter"]
    game.resolve_top_of_stack()
    return game


def test_w1g7_hollow_specter_x_paid_then_shown_then_picked(set_pool):
    """"…you may pay {X}. If you do, that player reveals X cards from their
    hand and you choose one of them. That player discards that card." The
    ruling (2004-10-04): "You decide on the value of X and pay {X} during
    resolution." Alice names 2 and two Swamps tap; Bob picks the two he shows
    (CR 608.2c); Alice may take only one of those, and Bob discards it."""
    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.players[1].life == 18
    assert game.pending_choice_of("pay_any_amount", 0) is not None
    assert not game.confirm_pay_any_amount(0, 4), "three Swamps cannot pay {4}"
    assert game.confirm_pay_any_amount(0, 2)
    tapped = [p for p in game.controlled_by(0) if p.tapped and p.card.name == "Swamp"]
    assert len(tapped) == 2
    shown = game.pending_choice_of("choose_cards_in_hand", 1)
    assert shown is not None and shown.data["count"] == 2
    assert game.confirm_choose_cards_in_hand(1, [1, 2])
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [1, 2]
    assert not game.confirm_revealed_hand_pick(0, 0), "Lightning Bolt was never shown"
    assert game.confirm_revealed_hand_pick(0, 2)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == [
        "Lightning Bolt", "Plains", "Island", "Giant Growth",
    ]
    assert game.stack == [] and game.pending_choices == []


def test_w1g7_hollow_specter_x_past_the_hand_shows_it_all(set_pool):
    """X larger than Bob's hand reveals every card he has (CR 608.2's as much
    as possible) and nobody asks him which; Alice picks among them."""
    game = _w1g7_specter_hits(
        set_pool, ["Plains", "Shivan Dragon"], 4, interactive={0},
    )
    assert game.confirm_pay_any_amount(0, 4)
    assert game.pending_choice_of("choose_cards_in_hand", 1) is None
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [0, 1]
    assert game.confirm_revealed_hand_pick(0, 1)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == ["Plains"]


def test_w1g7_hollow_specter_x_zero_discards_nothing(set_pool):
    """The ruling (2004-10-04): "X can be zero, but then that player discards
    nothing." A seat nobody asks pays nothing — the stated default of the
    any-amount payment — and Bob keeps his hand; so does an interactive Alice
    who names 0."""
    game = _w1g7_table(set_pool, hands={1: _W1G7_BOB_HAND})
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(3):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 18
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert "Alice paid no mana" in game.log

    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.confirm_pay_any_amount(0, 0)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert not any(p.tapped for p in game.controlled_by(0) if p.card.name == "Swamp")

# ==== end W1G7 ======================================================
