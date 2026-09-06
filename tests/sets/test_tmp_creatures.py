"""Tempest creatures.

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


# --- W1G4: triggered abilities the engine had never fired ---

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent


def _w1g4_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _w1g4_perm(card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g4_upkeep(board, opposing=()):
    p1 = PlayerState(name="P1", battlefield=list(board))
    p2 = PlayerState(name="P2", battlefield=list(opposing))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return game, p1, p2


# -- Kezzerdrix -------------------------------------------------------------


def test_kezzerdrix_burns_you_while_your_opponents_have_no_creatures(set_pool):
    """"At the beginning of your upkeep, if your opponents control no
    creatures, this creature deals 4 damage to you."

    CR 603.4 over a per-seat board count. "Your opponents" is CR 102.2/102.3's
    set — every player who is not you — which is the same set "each opponent"
    already names, so it is a spelling rather than a fourth referent.
    """
    game, p1, _ = _w1g4_upkeep([_w1g4_perm(set_pool("TMP")["Kezzerdrix"])])

    assert p1.life == 16


def test_kezzerdrix_is_silent_while_an_opponent_has_a_creature(set_pool):
    game, p1, _ = _w1g4_upkeep(
        [_w1g4_perm(set_pool("TMP")["Kezzerdrix"])],
        [_w1g4_perm(_w1g4_lea()["Grizzly Bears"])],
    )

    assert p1.life == 20


def test_kezzerdrix_ignores_creatures_you_control(set_pool):
    """The clause names *your opponents*' boards, so your own creature does not
    switch it off — the narrowing a seat-blind board count would drop.
    """
    game, p1, _ = _w1g4_upkeep([
        _w1g4_perm(set_pool("TMP")["Kezzerdrix"]),
        _w1g4_perm(_w1g4_lea()["Grizzly Bears"]),
    ])

    assert p1.life == 16


# -- Flailing Drake ---------------------------------------------------------


def _w1g4_to_blockers(game, attackers):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, attackers)
    assert ok, msg
    game.advance_combat_phase()   # declare blockers


def _w1g4_block(attacker_board, blocker_board):
    p1 = PlayerState(name="P1", battlefield=list(attacker_board))
    p2 = PlayerState(name="P2", battlefield=list(blocker_board))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    return game


def test_flailing_drake_pumps_the_creature_that_blocked_it(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature, that
    creature gets +1/+1 until end of turn."

    CR 509.3d: the printed narrowing ("by a creature") is what makes the event
    bind exactly one creature, so "that creature" names it. The handler this
    reaches (``pump_block_pair``) is the one ``engine/flanking.py`` builds by
    hand for CR 702.25a; until this round the printed sentence had no road to
    it and the card compiled to nothing.
    """
    drake = _w1g4_perm(set_pool("TMP")["Flailing Drake"])
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    _w1g4_block([drake], [gargoyle])

    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (3, 3)


def test_flailing_drake_pumps_the_creature_it_blocks(set_pool):
    """The *blocks* half of the same event, and the half a fall-through gets
    backwards: on that half the stack item's target is the Drake itself, so a
    reading that took the target would pump the Drake and leave the creature it
    blocked alone.
    """
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    drake = _w1g4_perm(set_pool("TMP")["Flailing Drake"])
    _w1g4_block([gargoyle], [drake])

    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (3, 3)
    assert (drake.effective_power, drake.effective_toughness) == (2, 3)


# -- Bellowing Fiend --------------------------------------------------------


def _w1g4_through_combat_damage(game):
    game._settle()
    game.advance_combat_phase()   # combat damage
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()


def test_bellowing_fiend_burns_the_damaged_creatures_controller(set_pool):
    """"Whenever this creature deals damage to a creature, this creature deals
    3 damage to that creature's controller and 3 damage to you."

    Two pieces the pool had neither of: a damage trigger whose *recipient* is a
    noun phrase rather than a seat word, and a "that creature" naming the
    **damaged** end of the event. The damager here is spelled "this creature",
    so the pronoun can only be the other end — read as the damager's (which is
    what every other card printing the phrase means) the Fiend would burn its
    own controller twice and leave the opponent untouched.
    """
    fiend = _w1g4_perm(set_pool("TMP")["Bellowing Fiend"])
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    game = _w1g4_block([fiend], [gargoyle])
    _w1g4_through_combat_damage(game)

    assert game.players[1].life == 17
    assert game.players[0].life == 17


def test_bellowing_fiend_is_silent_on_damage_to_a_player(set_pool):
    """The recipient narrowing, in the direction that matters: "to a creature"
    is not "to anything". Dropped, an unblocked swing would burn both players
    for 3 on top of the combat damage.
    """
    fiend = _w1g4_perm(set_pool("TMP")["Bellowing Fiend"])
    p1 = PlayerState(name="P1", battlefield=[fiend])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    _w1g4_through_combat_damage(game)

    assert game.players[0].life == 20
    assert game.players[1].life == 17


# -- Spike Drone ------------------------------------------------------------


def test_spike_drone_enters_with_its_counter(set_pool):
    """"This creature enters with a +1/+1 counter on it."

    CR 121.6 — an *entry* replacement, not a trigger, and the template
    `engine/enter_effects.py` has read since Triskelion. What it could not read
    was the number printed as an article and the noun printed singular, so a
    0/0 Spike that is 1/1 on the table was unsupported.
    """
    p1 = PlayerState(name="P1", hand=[set_pool("TMP")["Spike Drone"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.cast_from_hand(0, "Spike Drone")
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    drone = next(p for p in p1.battlefield if p.card.name == "Spike Drone")
    assert drone.metadata["plus_counters"] == 1
    assert (drone.effective_power, drone.effective_toughness) == (1, 1)


# -- Dirtcowl Wurm ----------------------------------------------------------


def _w1g4_land_play(set_pool, land_seat):
    wurm = _w1g4_perm(set_pool("TMP")["Dirtcowl Wurm"])
    p1 = PlayerState(name="P1", battlefield=[wurm])
    p2 = PlayerState(name="P2")
    [p1, p2][land_seat].hand.append(_w1g4_lea()["Forest"])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(land_seat)
    game._settle()
    game.cast_from_hand(land_seat, "Forest")
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return wurm


def test_dirtcowl_wurm_grows_when_an_opponent_plays_a_land(set_pool):
    """"Whenever an opponent plays a land, put a +1/+1 counter on this
    creature."

    CR 305.1: playing a land is a special action that uses no stack, so it is
    neither a cast nor necessarily an *entry* — the `land_enters` event beside
    it fires for a land that arrives by any route. Two events, and the card
    prints one of them.
    """
    wurm = _w1g4_land_play(set_pool, 1)

    assert (wurm.effective_power, wurm.effective_toughness) == (4, 5)


def test_dirtcowl_wurm_ignores_its_own_controllers_land(set_pool):
    """The printed seat, enforced. Dropped, the Wurm grows on every land drop
    in the game — an ability that works more often than the card allows.
    """
    wurm = _w1g4_land_play(set_pool, 0)

    assert (wurm.effective_power, wurm.effective_toughness) == (3, 4)


# -- Mongrel Pack -----------------------------------------------------------


def _w1g4_dogs(player):
    return sum(1 for p in player.battlefield if p.card.name == "Dog Token")


def test_mongrel_pack_makes_dogs_for_a_death_during_combat(set_pool):
    """"When this creature dies during combat, create four 1/1 green Dog
    creature tokens." (CR 506.1's phase, asked of the death.)
    """
    pack = _w1g4_perm(set_pool("TMP")["Mongrel Pack"])
    p1 = PlayerState(name="P1", battlefield=[pack])
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[])])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    pack.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g4_dogs(p1) == 4


def test_mongrel_pack_makes_no_dogs_for_a_death_outside_combat(set_pool):
    """The narrowing, in the direction the compiler could not see: both front
    ends read "during combat" and the *bare* regex row would have swallowed the
    words unread, leaving a card that makes four Dogs whenever it dies at all.
    """
    pack = _w1g4_perm(set_pool("TMP")["Mongrel Pack"])
    p1 = PlayerState(name="P1", battlefield=[pack])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    assert game.current_turn_phase != "combat"
    pack.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g4_dogs(p1) == 0


# -- Fugitive Druid ---------------------------------------------------------


def _w1g4_target_druid(set_pool, spell_name):
    lea = _w1g4_lea()
    druid = _w1g4_perm(set_pool("TMP")["Fugitive Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid], library=[lea["Forest"]] * 10)
    p2 = PlayerState(name="P2", hand=[lea[spell_name]], library=[lea["Forest"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._settle()
    game.cast_from_hand(
        1, spell_name, target_player_index=0, target_permanent_index=0,
    )
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return p1


def test_fugitive_druid_draws_for_an_aura_spell(set_pool):
    """"Whenever this creature becomes the target of an Aura spell, you draw a
    card."

    CR 603.2's targeting announcement, narrowed by the *class* of spell — an
    axis the becomes-target table already had two entries on ("a spell", "an
    ability"). What it could not say was which kind of spell, so the card had
    no reading at all rather than a wrong one.
    """
    p1 = _w1g4_target_druid(set_pool, "Firebreathing")

    assert len(p1.hand) == 1


def test_fugitive_druid_is_silent_for_a_non_aura_spell(set_pool):
    """The narrowing, enforced against the spell's own printed subtype — a
    spell on the stack is not a permanent, so the layer system has no answer
    and the printed face is the whole of what is testable. Dropped, the Druid
    draws for every spell aimed at it.
    """
    p1 = _w1g4_target_druid(set_pool, "Lightning Bolt")

    assert len(p1.hand) == 0
