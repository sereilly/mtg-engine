"""Activations the AI never made in Champions of Kamigawa (CHK W1G7, W1G8).

Kiki-Jiki, Mirror Breaker's "{T}: Create a token that's a copy of target
nonlegendary creature you control, except it has haste. Sacrifice it at the
beginning of the next end step." was cast and never activated: the rehearsal
of the activation fought the turn out, the attack policy held the hasty copy
home from any blocker that beat it, and what the copy left behind was a token
sacrificed at the end step — nothing lasting, so nothing proposed. A creature
that leaves before it could block has nothing a block takes from it
(``ai_declarations.leaves_before_it_could_block``), so it attacks.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_declarations import choose_attackers, leaves_before_it_could_block
from engine.models import Permanent
from tests.helpers import settle


def _w2g2_board(mine, theirs=(), *, hand=()) -> Game:
    for perm in (*mine, *theirs):
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine), hand=list(hand), life=20),
        PlayerState(name="P2", battlefield=list(theirs), life=20),
    ])
    game._sync_control()
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game


def _w2g2_to_declare_attackers(game: Game) -> None:
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


def test_kiki_jiki_copies_a_creature_its_copy_attacks_with(set_pool):
    """Against a Craw Wurm that beats a Grizzly Bears, the seat still makes
    the copy: the hasty 2/2 is gone at the end step whatever the Wurm does."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    kiki = Permanent(card=chk["Kiki-Jiki, Mirror Breaker"])
    bears = Permanent(card=lea["Grizzly Bears"])
    game = _w2g2_board([kiki, bears], [Permanent(card=lea["Craw Wurm"])])

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Kiki-Jiki, Mirror Breaker"
    assert action.target_permanent_ids == [bears.permanent_id]


def test_the_hasty_copy_attacks_into_a_blocker_that_beats_it(set_pool):
    """The copy is bound to a sacrifice at the next end step (CR 603.7), so it
    attacks into the Wurm; the Bears it copied, which stays, does not."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    kiki = Permanent(card=chk["Kiki-Jiki, Mirror Breaker"])
    bears = Permanent(card=lea["Grizzly Bears"])
    game = _w2g2_board([kiki, bears], [Permanent(card=lea["Craw Wurm"])])
    result = game.activate_permanent_ability(
        0, "Kiki-Jiki, Mirror Breaker", permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    copy = game.players[0].battlefield[-1]
    assert copy is not bears and copy.card.name == "Grizzly Bears"
    assert leaves_before_it_could_block(game, copy)
    assert not leaves_before_it_could_block(game, bears)

    _w2g2_to_declare_attackers(game)
    chosen = choose_attackers(game, 0)

    slot_of = {id(perm): slot for slot, perm in enumerate(game.players[0].battlefield)}
    assert slot_of[id(copy)] in chosen
    assert slot_of[id(bears)] not in chosen


def test_ball_lightning_attacks_into_a_blocker_that_beats_it(set_pool):
    """A printed "At the beginning of the end step, sacrifice this creature"
    is the same fact: Ball Lightning is gone tonight, so a Colossus of Sardia
    that kills it and lives is no reason to keep it home (on the base it
    stayed home, and a seat that rehearsed casting it read nothing)."""
    lightning = Permanent(card=set_pool("5ED")["Ball Lightning"])
    colossus = Permanent(card=set_pool("ATQ")["Colossus of Sardia"])
    game = _w2g2_board([lightning], [colossus])
    assert leaves_before_it_could_block(game, lightning)
    _w2g2_to_declare_attackers(game)

    assert choose_attackers(game, 0) == [0]


def test_wicked_akuba_drains_in_the_main_phase_after_its_attack(set_pool):
    """Wicked Akuba's "{B}: Target player dealt damage by this creature this
    turn loses 1 life" opens only once it has hit — and the attack that hits
    taps it. The main-phase chooser passed every tapped permanent over whole,
    so the ability was never activated; only its {T} abilities are out of
    reach (CR 602.5a)."""
    from engine.ai_actions import activation_announcement
    from engine.ai_payment import tap_planned_lands
    from tests.helpers import declare_attack, drive_combat

    chk = set_pool("CHK")
    akuba = Permanent(card=chk["Wicked Akuba"])
    swamps = [Permanent(card=chk["Swamp"]) for _ in range(2)]
    game = _w2g2_board([akuba, *swamps])
    game.enforce_mana_costs = True
    declare_attack(game, 0)
    drive_combat(game)
    assert game.current_turn_phase == "postcombat_main"
    assert akuba.tapped and game.players[1].life == 18

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Wicked Akuba"
    assert action.target_player_index == 1
    tap_planned_lands(game, 0, action)
    result = game.activate_permanent_ability(
        0, action.permanent_name, **activation_announcement(action),
    )
    assert result.supported, result.details
    settle(game)
    assert game.players[1].life == 17


def _w2g2_hisoka_board(set_pool, hand):
    lea, chk = set_pool("LEA"), set_pool("CHK")
    cards = {**lea, **chk}
    hisoka = Permanent(card=chk["Hisoka, Minamo Sensei"])
    islands = [Permanent(card=chk["Island"]) for _ in range(3)]
    game = _w2g2_board([hisoka, *islands], hand=[cards[name] for name in hand])
    game.players[1].hand.append(lea["Hill Giant"])
    game.enforce_mana_costs = True
    game.active_player_index = 1
    game.players[1].mana_pool["R"] = 4
    result = game.queue_from_hand(1, "Hill Giant")
    assert result.supported, result.details
    return game


def test_hisoka_discards_the_card_of_the_spells_mana_value(set_pool):
    """"{2}{U}, Discard a card: Counter target spell if it has the same mana
    value as the discarded card." Answering a Hill Giant (4) with a Gray Ogre
    (3) and a Hill Giant in hand, the seat discards its own Giant and the
    spell is countered; the Ogre stays."""
    from engine.ai_actions import activation_announcement
    from engine.ai_payment import tap_planned_lands
    from engine.ai_policy import choose_instant_speed_activation

    game = _w2g2_hisoka_board(set_pool, ["Gray Ogre", "Hill Giant"])

    action = choose_instant_speed_activation(game, 0)

    assert action is not None and action.permanent_name == "Hisoka, Minamo Sensei"
    assert game.players[0].hand[action.cost_hand_index].name == "Hill Giant"
    tap_planned_lands(game, 0, action)
    result = game.queue_permanent_ability(
        0, action.permanent_name, **activation_announcement(action),
    )
    assert result.supported, result.details
    settle(game)
    assert [card.name for card in game.players[0].hand] == ["Gray Ogre"]
    assert "Hill Giant" in [card.name for card in game.players[1].graveyard]
    assert "Hill Giant" not in [p.card.name for p in game.players[1].battlefield]


def test_hisoka_holds_its_hand_with_no_card_of_that_mana_value(set_pool):
    from engine.ai_policy import choose_instant_speed_activation

    game = _w2g2_hisoka_board(set_pool, ["Gray Ogre"])
    action = choose_instant_speed_activation(game, 0)
    assert action is None or action.permanent_name != "Hisoka, Minamo Sensei"
