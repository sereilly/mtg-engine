"""Per-card tests for Homelands' artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W2G5: cast locks, cost taxes and the tail ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.tokens import make_token_card


def _w2g5_chime_board(set_pool, catalog_by_name):
    """A Chime, three other Homelands permanents across both seats, one
    permanent from another set, and a token.

    Both seats, because the sweep names no controller; three printed types,
    because "nontoken permanent" is not "creature"; and the token, because
    CR 111.1 is the one word of the noun phrase that is not a card type.
    """
    hml = set_pool("HML")
    chime = Permanent(card=hml["Apocalypse Chime"])
    gnomes = Permanent(card=hml["Clockwork Gnomes"])
    castle = Permanent(card=hml["Castle Sengir"])
    ban = Permanent(card=hml["Feroz's Ban"])
    bystander = Permanent(card=catalog_by_name["Grizzly Bears"])
    token = Permanent(card=make_token_card("Goblin", 1, 1, "Creature — Goblin"))
    token.metadata["is_token"] = True
    p1 = PlayerState(name="P1", battlefield=[chime, gnomes, bystander, token])
    p2 = PlayerState(name="P2", battlefield=[castle, ban])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, chime


def test_apocalypse_chime_reads_the_phrase_as_a_noun_phrase_not_a_card(set_pool):
    """Golgothian Sylex's sentence and this one differ in the **verb**, not in
    the subject — so what they share is a noun-phrase rider, and the Chime is
    the ordinary "Destroy all …" production wearing it.

    The instruction is the generic sweep, which is the whole point: the phrase
    now composes with any verb instead of buying one production its one card.
    """
    program = compile_card_oracle(set_pool("HML")["Apocalypse Chime"])
    (ability,) = program.activated_abilities

    assert ability.instruction.kind == "destroy_all_matching"
    assert ability.instruction.payload["original_expansion"] == "hml"
    assert ability.instruction.payload["nontoken"] is True
    assert ability.instruction.payload["bypass_regeneration"] is True


def test_apocalypse_chime_destroys_every_nontoken_homelands_permanent(
    set_pool, catalog_by_name
):
    game, _ = _w2g5_chime_board(set_pool, catalog_by_name)

    game.activate_permanent_ability(0, "Apocalypse Chime")
    game._settle()

    names = {perm.card.name for perm in game.all_permanents()}
    assert "Clockwork Gnomes" not in names
    assert "Castle Sengir" not in names, "a land, and on the other seat's side"
    assert "Feroz's Ban" not in names, "an artifact, not only creatures"
    assert "Apocalypse Chime" not in names, (
        "the Chime is a Homelands card too — and it sacrificed itself to pay"
    )


def test_apocalypse_chime_spares_a_card_from_another_set_and_a_token(
    set_pool, catalog_by_name
):
    """The two halves of the noun phrase the sweep must not drop: the expansion
    and CR 111.1's "nontoken"."""
    game, _ = _w2g5_chime_board(set_pool, catalog_by_name)

    game.activate_permanent_ability(0, "Apocalypse Chime")
    game._settle()

    names = {perm.card.name for perm in game.all_permanents()}
    assert "Grizzly Bears" in names
    assert "Goblin" in names


def test_apocalypse_chime_beats_a_regeneration_shield(set_pool, catalog_by_name):
    """"They can't be regenerated." The trailing sentence is a rider on the
    destruction, and a rider that parsed and was dropped is the bug class the
    full-consumption invariant exists for — it would read as a card that works.
    """
    game, _ = _w2g5_chime_board(set_pool, catalog_by_name)
    gnomes = next(
        perm for perm in game.all_permanents()
        if perm.card.name == "Clockwork Gnomes"
    )
    gnomes.regeneration_shield = 1

    game.activate_permanent_ability(0, "Apocalypse Chime")
    game._settle()

    assert "Clockwork Gnomes" not in {
        perm.card.name for perm in game.all_permanents()
    }


def test_the_expansion_phrase_is_read_once_for_both_cards_that_print_it(
    set_pool
):
    """Golgothian Sylex keeps its own production — its verb is passive and no
    other production reads it — but the two now read the printed phrase through
    one scan. Two scans of one sentence are two spellings free to disagree about
    where the set name ends (idiom 36), and the set name is what the sweep is.
    """
    from engine.grammar.lexer import tokenize
    from engine.grammar.names import accept_original_expansion
    from engine.grammar.stream import TokenStream

    def _read(text: str):
        stream = TokenStream(tokenize(text).tokens)
        return accept_original_expansion(stream), stream.exhausted

    assert _read("a name originally printed in the Homelands expansion") == ("hml", True)
    assert _read("a name originally printed in the Antiquities expansion") == ("atq", True)
    # A set the manifest has never heard of refuses rather than sweeping the
    # set the reader guessed.
    assert _read("a name originally printed in the Onslaught expansion")[0] is None

    sylex = compile_card_oracle(set_pool("ATQ")["Golgothian Sylex"])
    (sacrifice,) = sylex.activated_abilities
    assert sacrifice.instruction.payload["set_code"] == "atq"


# --- W2G3: combat restrictions and shroud exceptions ---

from engine import Game, PlayerState
from engine.combat_restrictions import granted_blocker_whitelists
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g3_unsick(permanent: Permanent) -> Permanent:
    permanent.metadata["summoning_sickness_turn"] = -5
    return permanent


def test_jovens_tools_carries_the_printed_blocker_class(set_pool):
    """"{4}, {T}: Target creature can't be blocked this turn except by Walls."

    The class of blocker is payload, not a word in the instruction's name — a
    card printing another subtype is the same restriction. A **list**, because
    the static printing's union ("Walls and/or creatures with flying") is the
    same reader on the other side.
    """
    program = compile_card_oracle(set_pool("HML")["Joven's Tools"])

    assert program.supported, program.reason
    [ability] = program.activated_abilities
    assert ability.instruction.kind == "grant_cant_be_blocked_except_by_until_eot"
    assert ability.instruction.payload["allowed_blockers"] == [
        {"type_filter": "creature", "subtype_filter": "wall"}
    ]


def test_jovens_tools_lets_only_the_named_blockers_through(set_pool):
    """A *whitelist*, not Tower of Coireall's blacklist: everything the sentence
    does not name is illegal, where the blacklist lets the rest of the board
    block. Both are asserted, because a record read as the other one would give
    each card the opposite effect."""
    lea = set_pool("LEA")
    tools = Permanent(card=set_pool("HML")["Joven's Tools"])
    attacker = _w2g3_unsick(Permanent(card=lea["Grizzly Bears"]))
    wall = Permanent(card=lea["Wall of Wood"])
    bear = Permanent(card=lea["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[tools, attacker], library=[lea["Forest"]] * 5)
    p2 = PlayerState(name="P2", battlefield=[wall, bear], library=[lea["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Joven's Tools", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert result.supported, result.details
    assert granted_blocker_whitelists(attacker) == (
        [{"type_filter": "creature", "subtype_filter": "wall"}],
    )

    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()   # declare blockers

    assert game.declare_blockers(1, {0: 1})[0], "a Wall is what the card allows"
    assert not game.declare_blockers(1, {1: 1})[0], "everything else is illegal"


def test_the_jovens_tools_whitelist_ends_with_the_turn(set_pool):
    """"This turn" is the cleanup sweep and nothing else — the record is the
    whole of the effect, so an entry that outlived the turn would be an evasion
    ability nobody granted."""
    lea = set_pool("LEA")
    tools = Permanent(card=set_pool("HML")["Joven's Tools"])
    attacker = _w2g3_unsick(Permanent(card=lea["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[tools, attacker], library=[lea["Forest"]] * 5)
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.activate_permanent_ability(
        0, "Joven's Tools", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert granted_blocker_whitelists(attacker)

    game.resolve_cleanup_step(0)

    assert granted_blocker_whitelists(attacker) == ()

