"""Stronghold creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: combat restrictions and requirements ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2_creature(name, power, toughness, keywords=()):
    """A creature whose only text is its keyword line, if any."""
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2_combat(mine, theirs) -> Game:
    """A board at the declare-attackers step of seat 0's turn."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_mogg_flunkies_reads_alone_as_a_count_of_one(set_pool):
    """"This creature can't attack or block alone." - CR 506.5's word as a
    number.

    One printed sentence, two prohibitions, and both are the kinds Orcish
    Conscripts' printed count already produces: "alone" is "unless at least one
    other creature attacks/blocks", so the card needs no enforcement site of its
    own. The payload is what says so - a kind pair carrying anything but 1 would
    be a different card.
    """
    program = compile_card_oracle(set_pool("STH")["Mogg Flunkies"])
    assert program.supported, program.reason
    assert [(i.kind, i.payload) for i in program.instructions] == [
        ("cant_attack_unless_others_attack", {"count": 1}),
        ("cant_block_unless_others_block", {"count": 1}),
    ]


def test_mogg_flunkies_needs_company_to_attack_in_a_game(set_pool):
    """The Rock Hydra test on the attack half: CR 508.1c asks its restrictions
    of the **declaration**, so a lone Flunkies makes the whole set illegal and a
    Flunkies with a friend does not."""
    flunkies = _g2_nosick(Permanent(card=set_pool("STH")["Mogg Flunkies"]))
    friend = _g2_nosick(Permanent(card=_g2_creature("Footman", 2, 2)))
    game = _g2_combat([flunkies, friend], [])

    ok, message = game.declare_attackers(0, [0])
    assert not ok and "other attacking creature" in message, message
    # The control: the same declaration with a second attacker in it.
    assert game.declare_attackers(0, [0, 1])[0]


def test_mogg_flunkies_needs_company_to_block_in_a_game(set_pool):
    """And the block half, CR 509.1b, counted across the whole declaration."""
    attacker = _g2_nosick(Permanent(card=_g2_creature("Raider", 2, 2)))
    other = _g2_nosick(Permanent(card=_g2_creature("Rider", 2, 2)))
    flunkies = _g2_nosick(Permanent(card=set_pool("STH")["Mogg Flunkies"]))
    friend = _g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))
    game = _g2_combat([attacker, other], [flunkies, friend])
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()

    ok, message = game.declare_blockers(1, {0: 0})
    assert not ok and "other blocking creature" in message, message
    assert game.declare_blockers(1, {0: 0, 1: 1})[0]


def test_dream_prowler_is_unblockable_only_while_it_attacks_alone(set_pool):
    """"This creature can't be blocked as long as it's attacking alone."

    CR 506.5's condition asked at the declaration rather than materialized on a
    recompute: the same Prowler is blockable the moment a second attacker
    joins, which is the whole of the card.
    """
    prowler = _g2_nosick(Permanent(card=set_pool("STH")["Dream Prowler"]))
    ally = _g2_nosick(Permanent(card=_g2_creature("Footman", 2, 2)))
    blocker = _g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))
    game = _g2_combat([prowler, ally], [blocker])

    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert not game._can_block_attacker(blocker, prowler)
    assert game.is_unblockable(prowler)

    game.combat_attackers[1] = 1
    ally.attacking = True
    assert game._can_block_attacker(blocker, prowler), (
        "with a second attacker declared the Prowler is not attacking alone"
    )
    assert not game.is_unblockable(prowler)


def test_convulsing_licid_stops_its_host_blocking_once_attached(set_pool):
    """"Enchanted creature can't block." - the half of Pacifism's pair the pool
    had never printed on its own.

    Read through the same Aura channel every other attached restriction goes
    through, so it ends when the Licid stops being attached and nothing has to
    undo it.
    """
    from engine.auras import attach_aura

    licid = set_pool("STH")["Convulsing Licid"]
    program = compile_card_oracle(licid)
    assert program.supported, program.reason

    attacker = _g2_nosick(Permanent(card=_g2_creature("Raider", 2, 2)))
    host = _g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))
    worm = _g2_nosick(Permanent(card=licid))
    game = _g2_combat([attacker], [host, worm])
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game._can_block_attacker(host, attacker)

    attach_aura(worm, host)
    assert not game._can_block_attacker(host, attacker)


def test_corrupting_licid_grants_fear_through_the_attachment(set_pool):
    """"Enchanted creature has fear." on a permanent that is not an Aura.

    CR 303.4m: an ability referring to the "enchanted creature" means whatever
    the permanent is attached to, even where that permanent's printed type line
    says Creature. The grant was derived correctly all along; what refused the
    card was the reminder text's full stop behind the sentence (CR 207.2), so
    the assertion here is both halves - the card is supported **and** the
    keyword reaches the host.
    """
    from engine.auras import attach_aura

    licid = set_pool("STH")["Corrupting Licid"]
    assert compile_card_oracle(licid).supported

    host = _g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))
    worm = _g2_nosick(Permanent(card=licid))
    game = _g2_combat([host, worm], [])
    assert not game._has_keyword(host, "fear")

    attach_aura(worm, host)
    assert game._has_keyword(host, "fear")


def test_duct_crawler_denies_one_pairing_and_not_every_block(set_pool):
    """"{1}{R}: Target creature can't block this creature this turn."

    CR 509.1b narrowed to one named attacker, which is what separates it from
    Panic's blanket: the marked creature may still block anything else. The
    denial is recorded by ``permanent_id``, so the control below - a second
    attacker the same blocker faces - is the assertion that matters.
    """
    crawler = _g2_nosick(Permanent(card=set_pool("STH")["Duct Crawler"]))
    other = _g2_nosick(Permanent(card=_g2_creature("Raider", 2, 2)))
    blocker = _g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))
    game = _g2_combat([crawler, other], [blocker])

    result = game.activate_permanent_ability(
        0, "Duct Crawler",
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()

    assert not game._can_block_attacker(blocker, crawler)
    assert game._can_block_attacker(blocker, other), (
        "the denial names one attacker, not every block"
    )


def test_walking_dream_untaps_until_an_opponent_holds_two_creatures(set_pool):
    """"...doesn't untap during your untap step if an opponent controls two or
    more creatures."

    The condition is re-asked every untap step, which is the whole difference
    from the loose substring reading that would have frozen the Dream the
    moment the line was printed.
    """
    dream = _g2_nosick(Permanent(card=set_pool("STH")["Walking Dream"]))
    assert compile_card_oracle(dream.card).supported
    theirs = [_g2_nosick(Permanent(card=_g2_creature("Guard", 2, 2)))]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[dream]),
        PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    dream.tapped = True
    game.start_turn(0)
    assert not dream.tapped, "one opposing creature is under the threshold"

    theirs.append(_g2_nosick(Permanent(card=_g2_creature("Rider", 2, 2))))
    dream.tapped = True
    game.start_turn(0)
    assert dream.tapped, "two opposing creatures hold it down"


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g3_creature(name, power, toughness, text="") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_combat(attackers, defenders, *, blocks):
    """A game run to the declare-blockers step with *blocks* declared.

    ``blocks`` is the ``{blocker index: attacker index}`` map ``declare_blockers``
    takes. Seat 0 attacks; seat 1 blocks.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers)),
        PlayerState(name="P2", battlefield=list(defenders)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (*attackers, *defenders):
        perm.summoning_sick = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, list(range(len(attackers))))[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, dict(blocks))[0]
    game.resolve_stack()
    return game


def _w1g3_run_out_combat(game):
    """Every remaining combat step, resolving what each one puts on the stack."""
    for _ in range(4):
        game.advance_combat_phase()
        game.resolve_stack()


def test_lowland_basilisk_destroys_what_it_damaged_at_end_of_combat(set_pool):
    """"Whenever this creature deals damage to a creature, destroy that
    creature at end of combat."

    The pronoun is the *damaged* end of the event, not the damager: a permanent
    spells itself "this creature", so the only other creature the sentence has
    is the one it hit. `damage_events._announce` stamps that permanent's id onto
    the stack item, which is what the delayed ability binds — and the creature
    survives the combat damage step, so nothing but the delay destroys it.
    """
    basilisk = Permanent(card=set_pool("STH")["Lowland Basilisk"])
    wall = Permanent(card=_w1g3_creature("Stone Wall", 0, 9))
    game = _w1g3_combat([basilisk], [wall], blocks={0: 0})

    assert [p.card.name for p in game.players[1].battlefield] == ["Stone Wall"]
    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[1].battlefield] == [], game.log
    assert [c.name for c in game.players[1].graveyard] == ["Stone Wall"], game.log


def test_lowland_basilisk_leaves_a_creature_it_did_not_damage_alone(set_pool):
    """The delay is bound to one permanent by id (CR 603.7c), so a second
    creature on the same battlefield is untouched — the failure a sweep-shaped
    reading of "that creature" would produce."""
    basilisk = Permanent(card=set_pool("STH")["Lowland Basilisk"])
    wall = Permanent(card=_w1g3_creature("Stone Wall", 0, 9))
    bystander = Permanent(card=_w1g3_creature("Bystander", 1, 1))
    game = _w1g3_combat([basilisk], [wall, bystander], blocks={0: 0})

    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[1].battlefield] == ["Bystander"], game.log


def test_wall_of_tears_bounces_what_it_blocked_at_end_of_combat(set_pool):
    """"Whenever this creature blocks a creature, return that creature to its
    owner's hand at end of combat."

    The referent is the *blocked* attacker. A block announcement records the
    pair under `blocked_permanent_ids` and makes the stack item's target the
    blocker itself — so the delayed ability binds through the block pair, not
    through the target, or the Wall would bounce itself.
    """
    wall = Permanent(card=set_pool("STH")["Wall of Tears"])
    attacker = Permanent(card=_w1g3_creature("Charging Bull", 3, 3))
    game = _w1g3_combat([attacker], [wall], blocks={0: 0})

    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[0].battlefield] == [], game.log
    assert [c.name for c in game.players[0].hand] == ["Charging Bull"], game.log
    assert [p.card.name for p in game.players[1].battlefield] == ["Wall of Tears"], game.log


def test_wall_of_tears_does_not_bounce_itself(set_pool):
    """The negative case is the one that finds the bug: `binds_target` under a
    blocks trigger resolves the *blocker*, which is the Wall."""
    wall = Permanent(card=set_pool("STH")["Wall of Tears"])
    attacker = Permanent(card=_w1g3_creature("Charging Bull", 1, 1))
    game = _w1g3_combat([attacker], [wall], blocks={0: 0})

    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == attacker.permanent_id, game.log
    assert entry.bound_permanent_id != wall.permanent_id
