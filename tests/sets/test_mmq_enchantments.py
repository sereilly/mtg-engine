"""Mercadian Masques enchantments, Auras included.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: upkeep, end-step and enters-the-battlefield triggers ---
#
# Four enchantments, two of them Auras whose trigger names a seat the Aura's
# own controller is not. Both Auras were refused on a back-reference the
# lowering could not resolve rather than on anything the parser could not read.

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from tests.helpers import _nosick, resolve_stack


def _g4e_card(name, type_line, power=None, toughness=None):
    """A filler card; a P/T pair makes it a creature the layers can read."""
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
        power=power, toughness=toughness,
    )


def _g4e_duel(set_pool):
    """Two seats with cost enforcement off, and MMQ's pool keyed by name."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4e_drain(game):
    """Resolve the stack and then answer the offers a trigger left behind."""
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()
    return game.log


def test_ley_line_asks_the_seat_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** may put a
    +1/+1 counter on target creature **of their choice**."

    Both halves name the same seat and neither is the enchantment's controller:
    the offer is made to the seat the upkeep froze, and the pick is armed on
    that same seat.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Ley Line"]))
    mine = _nosick(Permanent(card=_g4e_card("Mine", "Creature - Bear", "2", "2")))
    p1.battlefield.append(mine)
    game._sync_control()

    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()
    resolve_stack(game)
    offers = [
        (choice.kind, choice.player_index) for choice in game.pending_choices
    ]
    assert offers == [("optional_pay", 1)]
    game.auto_resolve_pending_choices()
    game._settle()

    assert mine.effective_power == 3


def test_ley_line_places_nothing_on_a_creatureless_board(set_pool):
    """The pick has no candidate, so the offer buys nothing - and the ability
    still resolves rather than raising."""
    game, p1, _p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Ley Line"]))
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Ley Line"]


def test_insubordination_burns_a_controller_who_stayed_home(set_pool):
    """"At the beginning of the end step of enchanted creature's controller,
    this Aura deals 2 damage to **that player** unless **that creature**
    attacked this turn."

    Two back-references in one sentence, and they name different objects: the
    seat is the one the end step froze, the creature is the Aura's host.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)

    game.active_player_index = 1
    game.resolve_end_step(1)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 18)


def test_insubordination_spares_a_creature_that_attacked(set_pool):
    """The "unless" is an ordinary condition on the effect, not CR 603.4's
    intervening if - so the ability triggers either way and does nothing here.

    Read against the Aura instead of its host the clause would be false on
    every end step (an enchantment never attacks) and the damage would land
    whatever the creature did.
    """
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)
    victim.metadata["attacked_this_turn"] = True

    game.active_player_index = 1
    game.resolve_end_step(1)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 20)


def test_insubordination_is_silent_on_its_own_controllers_end_step(set_pool):
    """The condition names the *host's* controller, which is not the seat
    holding the Aura - the card is printed to go on an opponent's creature."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=by_name["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)

    game.active_player_index = 0
    game.resolve_end_step(0)
    _g4e_drain(game)

    assert (p1.life, p2.life) == (20, 20)


def test_unnatural_hunger_deals_the_hosts_power(set_pool):
    """"...deals damage equal to **that creature's power**" - a live read of
    the attached permanent (CR 613 makes power computed), not a number any fire
    site had to freeze."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    host = _nosick(Permanent(card=_g4e_card("Host", "Creature - Bear", "4", "4")))
    p2.battlefield.append(host)
    aura = Permanent(card=by_name["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4e_drain(game)

    assert p2.life == 16
    assert [perm.card.name for perm in p2.battlefield] == ["Host"]


def test_unnatural_hungers_another_means_another_than_the_host(set_pool):
    """"...unless they sacrifice **another** creature of their choice." The
    antecedent is the enchanted creature, not the ability's source: an Aura is
    not a creature, so excluding the source rules out nothing and the host
    would be offered as its own way out of the damage."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    host = _nosick(Permanent(card=_g4e_card("Host", "Creature - Bear", "4", "4")))
    p2.battlefield.append(host)
    spare = _nosick(Permanent(card=_g4e_card("Spare", "Creature - Bear", "1", "1")))
    p2.battlefield.append(spare)
    aura = Permanent(card=by_name["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4e_drain(game)

    assert p2.life == 20
    assert [perm.card.name for perm in p2.battlefield] == ["Host"]


def test_game_preserve_puts_every_revealed_creature_under_its_owner(set_pool):
    """"...put those cards onto the battlefield **under their owners'
    control**." CR 110.2a: an effect that puts an object onto the battlefield puts
    it under the instructed player's control *unless the effect states
    otherwise*, and this sentence is that statement - which is why the reveal
    records ``{seat: card}`` rather than a flat list."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Game Preserve"]))
    p1.library = [_g4e_card("A1", "Creature - Bear", "2", "2"),
                  _g4e_card("A2", "Creature - Bear", "2", "2")]
    p2.library = [_g4e_card("B1", "Creature - Bear", "2", "2"),
                  _g4e_card("B2", "Creature - Bear", "2", "2")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Game Preserve", "A1"]
    assert [perm.card.name for perm in p2.battlefield] == ["B1"]
    assert [card.name for card in p1.library] == ["A2"]
    assert [card.name for card in p2.library] == ["B2"]


def test_one_noncreature_card_stops_game_preserve_entirely(set_pool):
    """"**all** cards revealed this way" - a universal over every seat's
    reveal, so one land on top of one library keeps everything where it is.
    CR 701.20a moved nothing, so the cards stay on top of their libraries."""
    game, p1, p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Game Preserve"]))
    p1.library = [_g4e_card("A1", "Creature - Bear", "2", "2")]
    p2.library = [_g4e_card("Ritual", "Sorcery")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4e_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Game Preserve"]
    assert [card.name for card in p1.library] == ["A1"]
    assert [card.name for card in p2.library] == ["Ritual"]


def test_foster_digs_to_the_first_creature_card(set_pool):
    """"...reveal cards from the top of your library until you reveal a
    creature card. Put that card into your hand and **the rest** into your
    graveyard." A fourth printed spelling of "all other cards revealed this
    way", and the whole of what stood between this card and the production."""
    game, p1, _p2, by_name = _g4e_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Foster"]))
    victim = _nosick(Permanent(card=_g4e_card("Victim", "Creature - Bear", "2", "2")))
    p1.battlefield.append(victim)
    p1.library = [
        _g4e_card("S3", "Sorcery"),
        _g4e_card("Target", "Creature - Bear", "2", "2"),
        _g4e_card("S2", "Sorcery"),
    ]
    p1.mana_pool["G"] = 3
    game._sync_control()
    game.sacrifice_permanent(victim)
    _g4e_drain(game)

    assert [card.name for card in p1.hand] == ["Target"]
    assert [card.name for card in p1.graveyard] == ["Victim", "S3"]
    assert [card.name for card in p1.library] == ["S2"]
