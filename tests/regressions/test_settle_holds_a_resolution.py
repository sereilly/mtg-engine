"""Regression: the "cast it and resolve it" entry points never waited.

``tests/regressions/test_resolution_holds_priority.py`` made a resolution that
stops to ask keep its object on the stack. It did so in ``resolve_top_of_stack``
behind ``pause_for_choices``, and exactly two callers ever set that flag — the
priority path (``pass_priority``) and the step drain
(``_resolve_priority_window``). ``Game._settle`` — the loop behind
``cast_from_hand`` and ``activate_permanent_ability`` — did not, whoever was
playing.

So a prompt armed part-way through a resolution reached there was queued against
an **empty stack**. Nothing recorded the object (``_stack_item`` is stamped from
``resolving_stack_item``, which only the pausing path sets), so the object never
came back; ``_release_stack_item`` never ran; CR 704.3's sweep and CR 117.3b's
hand-off were applied to a resolution that had not finished; and for a prompt
that does not suspend the loop, CR 608.2n's bin ran early and put the spell card
in the graveyard with the decision still owed — the same two-zones-at-once shape
``test_held_spell_stays_out_of_the_graveyard.py`` fixed one caller ago.

Measured over the shipped pool at the fix: of the 296 prompt-armings a
resolution makes on this path, **267 across 255 cards** had nothing holding
them, against 29 that structurally cannot have one (a mana ability uses no
stack — CR 605.3a; a mode chosen at announcement records ``_trigger_item``, not
``_stack_item``; a land play puts no object on the stack at all). The priority
path strands exactly those 29 and nothing else, which is what named this loop
as the seam.

Recall is the shipped card the census was found from: "Discard X cards, then
return a card from your graveyard to your hand for each card discarded this
way."
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState


def _duel(pool, hand=(), graveyard=(), *, interactive=(0,)):
    p1 = PlayerState(
        name="P1",
        hand=[pool[n] for n in hand],
        graveyard=[pool[n] for n in graveyard],
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, p1, p2


class TestASpellCastThroughTheConvenienceEntryPoint:
    def test_recall_waits_on_the_stack_for_its_discard(self, catalog_by_name):
        """The card W1G1 reported. ``cast_from_hand`` resolves the spell in one
        call, and the discard it arms is owed by an interactive seat — so the
        spell is still resolving (CR 608.2) and its object stays on the stack."""
        game, p1, _ = _duel(
            catalog_by_name,
            hand=["Recall", "Grizzly Bears", "Grizzly Bears"],
            graveyard=["Healing Salve"],
        )

        game.cast_from_hand(0, "Recall", x_value=1)

        assert [item.card.name for item in game.stack] == ["Recall"]
        owed = game.waiting_prompt()
        assert owed is not None and owed.kind == "discard"
        assert owed.data.get("_stack_item") is game.stack[-1], (
            "the prompt must record the object whose resolution armed it"
        )

    def test_the_log_does_not_claim_the_spell_resolved(self, catalog_by_name):
        game, _, _ = _duel(
            catalog_by_name,
            hand=["Recall", "Grizzly Bears", "Grizzly Bears"],
            graveyard=["Healing Salve"],
        )

        game.cast_from_hand(0, "Recall", x_value=1)

        assert "Recall is resolving, awaiting a choice" in game.log
        assert not any("Recall resolved" in line for line in game.log)

    def test_answering_the_prompt_finishes_the_resolution(self, catalog_by_name):
        """And the object leaves when the last answer lands, not before."""
        game, p1, _ = _duel(
            catalog_by_name,
            hand=["Recall", "Grizzly Bears", "Grizzly Bears"],
            graveyard=["Healing Salve"],
        )
        game.cast_from_hand(0, "Recall", x_value=1)

        game.auto_resolve_pending_choices()

        assert game.stack == []
        assert game.waiting_prompt() is None
        # One card discarded, one card returned for it: the hand is the size it
        # started at, and "Exile Recall" — the sentence *after* the return — ran.
        assert len(p1.hand) == 2
        assert "Recall" in [c.name for c in p1.exile]

    def test_balance_stays_out_of_the_graveyard_while_its_removals_are_owed(
        self, catalog_by_name
    ):
        """CR 608.2n, the half that only a **non-suspending** prompt shows.

        ``balance`` does not suspend the resumable loop, so the bin step ran at
        the end of the instructions rather than being handed to the held object
        — and with nothing held, it ran at all. The card was in the graveyard
        with the sacrifice still on screen.
        """
        game, p1, p2 = _duel(catalog_by_name, hand=["Balance"])
        for _ in range(3):
            p1.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))
        p2.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))

        game.cast_from_hand(0, "Balance")

        assert game.waiting_prompt() is not None, "the removals are owed"
        assert "Balance" not in [c.name for c in p1.graveyard], (
            "CR 608.2n: the card is binned as the *final* part of the resolution"
        )
        assert [item.card.name for item in game.stack] == ["Balance"]


class TestAnAbilityActivatedThroughTheConvenienceEntryPoint:
    def test_disrupting_scepter_waits_for_the_opponents_discard(
        self, catalog_by_name
    ):
        """The shape the browser actually reaches: an AI seat activates through
        ``activate_permanent_ability`` (``web/game_flow.py``) and the prompt
        lands on the **human** seat opposite it."""
        game, p1, p2 = _duel(catalog_by_name, interactive=(1,))
        scepter = Permanent(card=catalog_by_name["Disrupting Scepter"])
        scepter.metadata["summoning_sickness_turn"] = -99
        p1.battlefield.append(scepter)
        p2.hand = [catalog_by_name["Grizzly Bears"]]

        game.activate_permanent_ability(0, "Disrupting Scepter", target_player_index=1)

        owed = game.waiting_prompt()
        assert owed is not None and owed.kind == "discard" and owed.player_index == 1
        assert len(game.stack) == 1, "the ability is still resolving (CR 608.2)"
        assert owed.data.get("_stack_item") is game.stack[-1]


class TestHeadlessPlayIsUntouched:
    """The derivation is ``bool(interactive_seats)``, so a game with nobody to
    stop for resolves exactly as it did — which is what keeps a seeded
    simulation reproducible."""

    def test_no_interactive_seat_drains_as_before(self, catalog_by_name):
        game, p1, _ = _duel(
            catalog_by_name,
            hand=["Recall", "Grizzly Bears", "Grizzly Bears"],
            graveyard=["Healing Salve"],
            interactive=(),
        )

        game.cast_from_hand(0, "Recall", x_value=1)

        assert game.stack == [], "no interactive seat: the object pops as always"
        assert [c.kind for c in game.pending_choices] == ["discard"]

        game.auto_resolve_pending_choices()
        assert len(p1.hand) == 2
        assert "Recall" in [c.name for c in p1.exile]


class TestAnAnsweredPromptLeavesTheQueue:
    """A second, older defect the hold surfaced — and the only reason it was
    ever invisible.

    ``_resolve_pay_any_amount`` never took its own choice off the queue, which
    every sibling resolver in ``mixins/stack/choices.py`` does. The AI and
    headless path hid it: ``auto_resolve_pending_choices`` drops a defaulted
    choice itself. A *confirmed* one stayed queued with ``_answered`` stamped on
    it, and ``waiting_prompt`` reads the queue — so once Liege of the Hollows had
    died and both seats had paid, the game reported a decision nobody owed and
    refused every further action by the seat that had already answered
    (CR 117.3b).

    It reproduces on the engine before this round's change too; what the change
    added was a second symptom — the stack object never released — which is what
    made a test fail on it.
    """

    def _liege_died(self, set_pool):
        wth = set_pool("WTH")
        lea = set_pool("LEA")

        def perm(card):
            p = Permanent(card=card)
            p.metadata["summoning_sickness_turn"] = -99
            return p

        game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.interactive_seats = {0, 1}
        game.active_player_index = 0
        liege = perm(wth["Liege of the Hollows"])
        game.players[0].battlefield.append(liege)
        game.players[0].battlefield.extend(perm(lea["Forest"]) for _ in range(4))
        game.players[1].battlefield.extend(perm(lea["Mountain"]) for _ in range(2))
        game._sync_control()
        for _ in range(4):
            if not game.is_on_battlefield(liege):
                break
            game.players[0].hand = [lea["Lightning Bolt"]]
            game.cast_from_hand(
                0, "Lightning Bolt", target_player_index=0,
                target_permanent_index=game.battlefield_index_of(liege),
            )
        return game

    def test_the_queue_is_empty_once_every_seat_has_paid(self, set_pool):
        game = self._liege_died(set_pool)
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [
            ("pay_any_amount", 0), ("pay_any_amount", 1),
        ]

        assert game.confirm_pay_any_amount(0, 3), game.log
        assert game.confirm_pay_any_amount(1, 2), game.log

        assert game.pending_choices == []
        assert game.waiting_prompt() is None, (
            "the game must not go on waiting for a decision that has been made"
        )
        assert game.stack == []

    def test_a_rejected_answer_still_leaves_the_prompt_owed(self, set_pool):
        """The other direction, so the discard cannot be moved to the caller: a
        board that cannot cover the number is a rejection, and the seat still
        owes its answer."""
        game = self._liege_died(set_pool)

        assert not game.confirm_pay_any_amount(1, 5)
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [
            ("pay_any_amount", 0), ("pay_any_amount", 1),
        ]
