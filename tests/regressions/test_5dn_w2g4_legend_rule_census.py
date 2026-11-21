"""Census: no legendary permanent in the pool is lost to a choice nobody made.

CR 704.5j: "If two or more legendary permanents with the same name are
controlled by the same player, **that player chooses one of them**, and the
rest are put into their owners' graveyards." The state-based check kept the
first and asked nobody (5DN W1G4's report, §4: 227 shipped legendary
permanents). For every legendary permanent card in the pool this puts two
copies under a seat a person sits at and asks two things:

(a) nothing has left by the legend rule before the person answered, and a
    ``legend_rule`` prompt names both copies;
(b) the answer — the second copy, which the old rule always binned — is the
    one that stays, and the first goes to its owner's graveyard.

Validated backwards: with the old sweep put back (keep the first, ask nobody)
the census names every card it examined.

**A card that exempts itself is asked about the board the rule applies to.**
"If there are exactly two permanents named Brothers Yamazaki on the
battlefield, the "legend rule" doesn't apply to them." (CHK.) Two copies of
that card owe nothing, and that is the card working. So the census reads the
exemption off the card's own text (``legend_rule.legend_rule_exemption``, the
reader the rule enforces with — never a list of names), asks (a) and (b) of
the smallest board the exemption does not cover (three Brothers), and asks of
the exempt board that the rule reader agrees it is exempt
(``legend_rule.exempt_from_legend_rule``) and that every copy stays with
nothing owed.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.legend_rule import exempt_from_legend_rule, legend_rule_exemption
from engine.models import Permanent
from engine.mixins import game_ending

#: Measured 2026-11-11 on 5dn/int-w1g5: 227 legendary permanents ship and 222
#: are examined (229 and 224 under MTG_PROMOTE=5DN, with Raksha Golden Cub and
#: Helm of Kaldra). The five another state-based action takes first, on a
#: board holding nothing else: Dakkon Blackblade, Multani and Molimo (a */*
#: counting what is not there, CR 704.5f), Crovax the Cursed (0/0, its
#: entering counters never placed) and Skeleton Ship (no Islands).
_EXAMINED_FLOOR = 220

_PERMANENT_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker", "battle")


def _legendary_permanents() -> list:
    found = []
    for card in load_catalog():
        front = (card.type_line or "").split("//")[0].lower()
        if "legendary" in front and any(word in front for word in _PERMANENT_TYPES):
            found.append(card)
    return found


def _placed(card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    if card.loyalty and str(card.loyalty).isdigit():
        # CR 306.5b: a planeswalker enters with its printed loyalty. Placed
        # directly here, it would otherwise be swept at 0 (CR 704.5i).
        permanent.metadata["loyalty_counters"] = int(card.loyalty)
    return permanent


def _exempt_counts(card) -> frozenset[int]:
    """How many copies of *card* its own text exempts from the legend rule
    ("exactly two permanents named <this card>"), read by the rule's own
    reader. Empty for every card that prints no such sentence."""
    return frozenset(
        count
        for line in (card.oracle_text or "").splitlines()
        if (exemption := legend_rule_exemption(line)) is not None
        for count, name in [exemption]
        if name == card.name.lower()
    )


def _board(card, copies: int) -> tuple[Game, list[Permanent]]:
    placed = [_placed(card) for _ in range(copies)]
    game = Game(
        players=[
            PlayerState(name="P0", battlefield=list(placed)),
            PlayerState(name="P1"),
        ],
        interactive_seats={0},
    )
    return game, placed


def _binned_unasked(game) -> bool:
    return any("704.5j" in str(line) for line in game.log)


def census(cards) -> tuple[int, dict[str, str]]:
    """``(examined, lost)``: how many cards left their copies on the
    battlefield for the legend rule to be asked about, and each card the rule
    failed — its name and what went wrong.

    Two copies, or — for a card that exempts a count of itself — the fewest
    copies (two or more) the exemption does not cover."""
    examined, lost = 0, {}
    for card in cards:
        exempt = _exempt_counts(card)
        copies = next(n for n in range(2, 2 + len(exempt) + 1) if n not in exempt)
        game, placed = _board(card, copies)
        binned_unasked = _binned_unasked(game)
        owed = [c for c in game.pending_choices if c.kind == "legend_rule"]
        if not binned_unasked and not all(game.is_on_battlefield(p) for p in placed):
            continue  # another state-based action took a copy: nothing to ask
        examined += 1
        if binned_unasked:
            lost[card.name] = "a copy left by the legend rule with nobody asked"
            continue
        ids = owed[0].data.get("candidates") if len(owed) == 1 else None
        if ids != [p.permanent_id for p in placed]:
            lost[card.name] = f"owed {[c.data for c in owed]}"
            continue
        kept = placed[-1]
        if not game.resolve_pending_choice("legend_rule", 0, permanent_id=kept.permanent_id):
            lost[card.name] = "the answer naming the last copy was refused"
            continue
        if not game.is_on_battlefield(kept) or any(
            game.is_on_battlefield(p) for p in placed[:-1]
        ):
            lost[card.name] = "the answer is not what stayed"
            continue
        # The exempt board: the rule reader agrees it is exempt, and every
        # copy stays with nothing owed. Under the old sweep a copy is binned
        # here too, and named the way every other card is.
        for count in sorted(exempt):
            game, placed = _board(card, count)
            if _binned_unasked(game):
                lost[card.name] = "a copy left by the legend rule with nobody asked"
            elif not exempt_from_legend_rule(game, card.name):
                lost[card.name] = f"{count} copies are not exempt on the board"
            elif any(c.kind == "legend_rule" for c in game.pending_choices) or not all(
                game.is_on_battlefield(p) for p in placed
            ):
                lost[card.name] = f"{count} exempt copies did not all stay unasked"
    return examined, lost


def test_no_legendary_permanent_is_lost_to_a_choice_nobody_made():
    examined, lost = census(_legendary_permanents())
    assert not lost, lost
    assert examined >= _EXAMINED_FLOOR, examined


def _keep_the_first_and_ask_nobody(game) -> bool:
    """The sweep before 5DN W2G4, verbatim in effect: keep the first, bin the
    rest, ask nobody."""
    changed = False
    for player in game.players:
        by_name: dict[str, list] = {}
        for perm in game.controlled_by(player):
            if perm.has_supertype("legendary"):
                by_name.setdefault(perm.effective_card.name, []).append(perm)
        for name, perms in by_name.items():
            if len(perms) > 1:
                for removed in reversed(perms[1:]):
                    game.remove_from_battlefield(removed)
                    died = game._permanent_to_graveyard(player, removed)
                    game.log.append(
                        f"{name} {'put into graveyard' if died else 'left the battlefield'}"
                        " (704.5j: legend rule)"
                    )
                changed = True
    return changed


def test_with_the_old_sweep_the_census_names_every_card(monkeypatch):
    """Backwards: the defect put back, the census names every card it
    examined, each as a copy binned with nobody asked."""
    monkeypatch.setattr(game_ending, "state_based_legend_rule", _keep_the_first_and_ask_nobody)
    examined, lost = census(_legendary_permanents())
    assert examined >= _EXAMINED_FLOOR, examined
    assert len(lost) == examined
    assert set(lost.values()) == {"a copy left by the legend rule with nobody asked"}
