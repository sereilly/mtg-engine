"""A life gain replaced by nothing at all (CR 614.1a, CR 119.10).

    "If a player would gain life, that player gains no life instead."
    (Sulfuric Vortex.)

**A replacement, not a prohibition**, and the two are different rules with
different consequences in play — which is why this is not a row of
``engine/life_prohibitions.py`` beside Forsaken Wastes' "Players can't gain
life":

* CR 119.7 says of a player who *can't* gain life that "a replacement effect
  that would replace a life gain event affecting that player won't do
  anything". The ban is asked before any replacement is gathered, and Lich's
  "draw that many cards instead" never sees the event.
* This sentence uses "instead" (CR 614.1a), so it **is** one of those
  replacements. Beside Lich it is one of two contenders over one event, and
  CR 616.1 hands the choice to the affected player: they may apply Lich first
  and draw the cards, after which there is no gain left for this to replace
  (CR 614.7). Read as a ban, the Lich player would be denied a choice the rules
  give them.
* CR 119.7's other two clauses — an exchange of life totals that would raise a
  total "won't happen", and "a cost that involves having that player gain life
  can't be paid" — belong to the ban alone. Under this sentence a cost that
  gains life is paid and the gain is replaced; nothing here touches either path.

CR 119.10 is what makes the interceptor's predicate honest: "If [a player] would
gain life" is "if a source would cause [a player] to gain life", and a gain of 0
is no event at all — ``Game._gain_life`` returns before asking anything when the
amount is not positive, so this never replaces a gain that was not going to
happen.

**Who is covered is payload.** The printed subject names the seat scope the way
``life_prohibitions`` reads its subjects, so "If an opponent would gain life,
that player gains no life instead" needs no code; the sentence is anchored
whole, and a line that says more than this is a rule this module does not carry
out.
"""

from __future__ import annotations

import re

from .registry import (LIFE_GAIN_REPLACED_BY_NOTHING, ReplacementOutcome,
                       replacement_effect)

#: Which seats a printed subject covers. The values are scope names, not seat
#: numbers: who "you" and "an opponent" are depends on who controls the
#: permanent, which is the board scan's question rather than the text's.
_SCOPES: dict[str, str] = {
    "a player": "each_player",
    "an opponent": "opponents",
    "you": "you",
}

_NO_LIFE_INSTEAD = re.compile(
    r"^if (?P<subject>a player|an opponent|you) would gain life, "
    r"(?:that player gains|you gain) no life instead$"
)


def gains_no_life_instead_line(line: str) -> str | None:
    """The seat scope *line* replaces life gain for, or None.

    One reader for the interceptor below and the claim
    (``replacements.lines.replacement_claims_line``), so what is replaced and
    what is claimed cannot drift. "You" pairs with "you gain" and the two
    third-person subjects with "that player gains"; a crossed pair is a sentence
    no card prints and stays unmatched.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    text = text.replace("’", "'")
    match = _NO_LIFE_INSTEAD.match(text)
    if match is None:
        return None
    subject = match.group("subject")
    if (subject == "you") != text.endswith("you gain no life instead"):
        return None
    return _SCOPES[subject]


def _replacing_sources(game, payload: dict) -> list:
    """Every permanent whose text replaces *this* gain. Pure.

    Scanned over the whole board, because the printed subject decides the
    reach: "a player" is everybody, the enchantment's own controller included.
    Read off ``effective_card`` (CR 707.2, CR 612.1), so a copy of the
    enchantment replaces too and one whose text was changed does not.
    """
    player = payload["player"]
    found = []
    for seat, permanent in game.permanents_with_controller():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            scope = gains_no_life_instead_line(line)
            if scope is None:
                continue
            controller = game.players[seat]
            if (
                scope == "each_player"
                or (scope == "you" and controller is player)
                or (scope == "opponents" and controller is not player)
            ):
                found.append(permanent)
                break
    return found


def _applies_gains_no_life(game, payload: dict) -> bool:
    return int(payload.get("amount") or 0) > 0 and bool(
        _replacing_sources(game, payload)
    )


@replacement_effect(
    "life_gain", LIFE_GAIN_REPLACED_BY_NOTHING, applies=_applies_gains_no_life,
    label="Gain no life instead",
)
def _gain_no_life_instead(game, payload: dict) -> ReplacementOutcome | None:
    """Sulfuric Vortex: the gain is replaced by no event (CR 614.1a).

    The event is consumed, so nothing is recorded and nothing is announced: a
    life gain that was replaced never happened, which is what keeps "whenever
    you gain life" and "life gained this turn" from seeing it (the same reason
    ``Game._gain_life`` emits only after the replacements).

    Several such permanents are several effects, but each does the same thing
    to the same event and the first consumes it, so one contender stands for
    them all — two identical options would be a CR 616.1e question with no
    difference between its answers.
    """
    player = payload["player"]
    source = _replacing_sources(game, payload)[0]
    origin = f" from {payload['source_name']}" if payload.get("source_name") else ""
    game.log.append(
        f"{player.name} would gain {payload['amount']} life{origin}; gains no "
        f"life instead ({source.card.name})"
    )
    return ReplacementOutcome(replaced=True)


__all__ = ["gains_no_life_instead_line"]
