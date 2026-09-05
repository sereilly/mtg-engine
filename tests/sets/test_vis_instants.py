"""Per-card tests for Visions' instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block headed
``# --- W<wave>G<n>: <topic> ---`` and puts **its own imports at the top of its
own block**, not in a shared header. That is deliberate. The mechanical merge
for this file is "take ours, append the branch's block", and a branch that added
an import to a shared header loses it in exactly that move.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations


# --- W1G5: reanimation and the counter that follows it ---

from engine import Game, PlayerState
from engine.oracle import compile_card_oracle


def test_miraculous_recovery_counters_the_permanent_it_made(set_pool):
    """"Return target creature card from your graveyard to the battlefield.
    Put a +1/+1 counter on **it**."

    The pronoun names a permanent that did not exist when the spell was cast —
    the target is a *card in a graveyard* — so the placement reads what the
    reanimation recorded rather than the ability's own target. Substituting the
    earlier sentence's target spec, which the counter rider did
    unconditionally, hands the placement a graveyard-scoped noun phrase and the
    line refuses at "no handler reads a filter scoped to the graveyard". The
    grant rider one function away had taken the right branch since Dreams of
    the Dead, so the same printed shape compiled or refused depending only on
    whether the second sentence said "gains" or "put".
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Miraculous Recovery"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "reanimate_creature", "add_counter_to_target",
    ]
    # The counter reads the reanimation's record, not a target.
    assert steps[1].payload == {
        "counter": "+1/+1", "permanents_from": "reanimated_permanents",
    }

    game = Game(players=[
        PlayerState(
            name="P1", hand=[vis["Miraculous Recovery"]],
            graveyard=[lea["Grizzly Bears"], lea["Black Lotus"]],
            library=[lea["Island"]] * 6,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert game.cast_from_hand(
        0, "Miraculous Recovery", target_player_index=0,
    ).supported
    game.resolve_stack()

    returned = list(game.controlled_by(game.players[0]))
    assert [p.card.name for p in returned] == ["Grizzly Bears"]
    assert (returned[0].effective_power, returned[0].effective_toughness) == (3, 3)
    assert "Grizzly Bears" not in [c.name for c in game.players[0].graveyard]


def test_tithe_offers_the_second_search_only_when_the_condition_holds(set_pool):
    """"Search your library for a Plains card. If target opponent controls more
    lands than you, you may search your library for an additional Plains card.
    Reveal those cards, put them into your hand, then shuffle."

    Three printed sentences and one effect (CR 701.23h), which is why the first
    sentence has no destination clause of its own and the ordinary search
    production refused it at "expected 'put'". The condition and the optional
    second search both already lowered; what was missing was only a reading of
    the three sentences together.

    And a **picker** finding on top of the parse one, in the opposite direction
    from usual: the instance of the word "target" is in the *condition*, so a
    spec derived from the instructions' arms alone was None — the exact value
    the client tests to decide whether to ask for a target.
    """
    from engine.targeting import derive_cast_spec

    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Tithe"])
    assert program.supported, program.reason
    assert derive_cast_spec(vis["Tithe"], program) == {
        "kind": "player", "opponents_only": True,
    }

    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["search_library", "if_then"]
    assert steps[1].payload["condition"]["op"] == "more_than_you"
    assert steps[1].payload["then"][0].kind == "may"

    def rig(opponent_lands):
        from engine.models import Permanent

        game = Game(players=[
            PlayerState(
                name="P1", hand=[vis["Tithe"]],
                library=[lea["Island"], lea["Plains"], lea["Plains"], lea["Forest"]],
            ),
            PlayerState(
                name="P2", library=[lea["Island"]] * 4,
                battlefield=[
                    Permanent(card=lea["Mountain"]) for _ in range(opponent_lands)
                ],
            ),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game._settle()
        return game

    def play(game, *, take_the_offer):
        game.cast_from_hand(0, "Tithe", target_player_index=1)
        game.resolve_stack()
        for _ in range(6):
            if not game.pending_choices:
                break
            pending = game.pending_choices[0]
            if pending.kind == "search_library":
                index = next(
                    (
                        i for i, card in enumerate(game.players[0].library)
                        if card.name == "Plains"
                    ),
                    None,
                )
                if index is None:
                    game.decline_search_library(0)
                else:
                    game.confirm_search_library(0, index)
            else:
                game.resolve_pending_choice(
                    pending.kind, 0, accept=take_the_offer,
                )
            game.resolve_stack()
        return [card.name for card in game.players[0].hand]

    # Behind on lands: the offer is made and taking it finds the second Plains.
    assert play(rig(2), take_the_offer=True) == ["Plains", "Plains"]
    # Declining is a legal answer and leaves the second find unmade.
    assert play(rig(2), take_the_offer=False) == ["Plains"]
    # Ahead on lands: the condition fails and no second offer is even made.
    assert play(rig(0), take_the_offer=True) == ["Plains"]


def test_foreshadow_draws_only_when_the_named_card_is_the_one_milled(set_pool):
    """"Choose a card name, then target opponent mills a card. If a card with
    the chosen name was milled this way, you draw a card."

    A **supported** card no player could cast: its only compiled instruction
    was the delayed draw on the second printed line, so ``derive_cast_spec``
    answered None and the client sent a bare cast the engine then refused. Two
    of its three sentences were unclaimed by ``parse_coverage`` as well, which
    is the pair of instruments that sees this class and the support census that
    does not.

    The name is chosen **before** the mill and the prompt suspends the
    resolution (CR 608.2, CR 117.3b): a seat that saw the milled card before
    naming would be choosing with information the card does not give them.
    """
    from engine.targeting import derive_cast_spec

    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = compile_card_oracle(vis["Foreshadow"])
    assert program.supported, program.reason
    assert derive_cast_spec(vis["Foreshadow"], program) == {
        "kind": "player", "opponents_only": True,
    }
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_card_name", "mill_target_player", "if_then",
    ]
    assert steps[2].payload["condition"] == {"kind": "chosen_name_milled_this_way"}

    def play(guess):
        game = Game(players=[
            PlayerState(
                name="P1", hand=[vis["Foreshadow"]], library=[lea["Island"]] * 6,
            ),
            PlayerState(name="P2", library=[lea["Black Lotus"], lea["Forest"]]),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        assert game.cast_from_hand(
            0, "Foreshadow", target_player_index=1,
        ).supported
        game.resolve_stack()
        pending = game.pending_choices[0]
        assert pending.kind == "choose_card_name"
        # The mill has not happened yet: naming after seeing the card would be
        # a different game.
        assert game.players[1].graveyard == []
        game.confirm_choose_card_name(0, guess)
        game.resolve_stack()
        return game

    hit = play("Black Lotus")
    assert [c.name for c in hit.players[0].hand] == ["Island"]
    assert [c.name for c in hit.players[1].graveyard] == ["Black Lotus"]

    miss = play("Shivan Dragon")
    assert miss.players[0].hand == []
    assert [c.name for c in miss.players[1].graveyard] == ["Black Lotus"]
