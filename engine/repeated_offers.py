"""What a repeated round of offers is made of (CR 101.4).

"Starting with you, each player may put a permanent card from their hand onto
the battlefield. Repeat this process until no one puts a card onto the
battlefield." (Eureka.) One *round* is the offer made to every seat in turn; the
process repeats for as long as a round is taken by anybody.

That termination is only decidable if the offered act says whether it happened.
An act nobody can decline never ends the loop, and an act that declines silently
ends it after one round however many seats took it — so the kinds that may be
repeated this way are named here, once, and both readers ask this table:

* ``engine/grammar/lowering/game.py`` refuses to compile a repeat clause over
  anything else, so a card printing one is unsupported rather than looping;
* ``engine/handlers/control_flow.py`` counts the records under
  :data:`OFFER_TAKEN_RESULTS` to decide whether the round happens again.

A list of kinds rather than a predicate on the handler because the record is a
*contract* between the two — a handler that stops writing it would leave a loop
that runs exactly once, with nothing failing.
"""

from __future__ import annotations

#: The scratchpad key an offered act appends to when a seat takes it. One list
#: on ``OracleExecutionContext.results``, shared by every seat of the round
#: because they share the context the round was entered with.
OFFER_TAKEN_RESULTS = "_offers_taken"

#: The instruction kinds a repeated round may offer. Each one arms its seat a
#: prompt that can be declined and appends to ``OFFER_TAKEN_RESULTS`` when it is
#: not.
REPEATABLE_OFFERS = frozenset({"put_chosen_card_from_hand_onto_battlefield"})

__all__ = ["OFFER_TAKEN_RESULTS", "REPEATABLE_OFFERS"]
