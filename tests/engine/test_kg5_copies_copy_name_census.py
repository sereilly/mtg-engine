"""Census: what the engine's machinery says about a copy names it by what it
copies (CR 707.2), across the pool.

For each sampled shipped creature, a Clone copies it; for each sampled
noncreature artifact, Sculpting Steel does. The copy then does what the
machinery has a sentence for — each of its activated abilities is activated
while it is summoning sick and again once it is not, it attacks into a
blocker where it is a creature, and a Lightning Bolt is aimed at it — at a
table whose seats are both asked (so every prompt is armed, not defaulted at
arm), and the census reads:

* every **refusal** an activation returns (the activation path's own
  reasons, the cost gate's, the CR 602.5 prohibitions', the {T} symbol's);
* every **offered list** a prompt is armed with: an entry naming the copy by
  id never names it by its printed card;
* every **line the machinery logs about a stack object or a permanent**: the
  ability's lifecycle ("… ability added to stack / resolved / fizzled"), a
  trigger's announcement ("… triggered …"), the state-based actions' lines
  ("… died (704.5g: …)") and the combat declarations' refusals.

None of them may name the copier ("Clone", "Sculpting Steel"). Not in scope,
and left by the census on purpose: the **effect handlers' own sentences**
("Clone dealt 1 damage to P1", "Lightning Bolt dealt 3 damage to Clone"),
which name an ability's source as ``context.card.name`` — the source's
printed card — in some seven hundred places (see the kg5 ``copies`` report).

Backwards: on the round's base every family above named the copier (the
sick activations' "Clone has summoning sickness", "Clone ability added to
stack", "Clone died (704.5g: lethal damage)", the Bolt's target list).
"""

from __future__ import annotations

import functools
import re

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import declare_attack, drive_combat, settle, stable_sample

# One in this many cards of each kind, by name (``stable_sample``); the full
# pass reads every one.
EVERY = 40

#: The machinery's lines about a stack object or a permanent: who the line
#: names is group "who".
MACHINERY_LINES = (
    re.compile(r"^(?P<who>.+?) ability (?:added to stack|resolved|fizzled|is resolving)"),
    re.compile(r"^(?P<who>.+?)(?:'s triggered ability| triggered\b| didn't trigger)"),
    re.compile(
        r"^(?P<who>.+?) (?:died|was destroyed|went to graveyard|left the battlefield"
        r"|put into graveyard|sacrificed|regenerated|was removed from combat"
        r"|became unattached) ?\("
    ),
    re.compile(r"^(?P<who>.+?) (?:died|was destroyed|regenerated|was removed from combat)$"),
)


def _names(text: str, copier: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(copier)}(?![\w'])", text) is not None


def _offers_printed(data, copier: str, copy_id: int) -> bool:
    if isinstance(data, dict):
        ident = data.get("permanent_id", data.get("id"))
        if data.get("name") == copier and ident == copy_id:
            return True
        return any(_offers_printed(value, copier, copy_id) for value in data.values())
    if isinstance(data, (list, tuple)):
        return any(_offers_printed(value, copier, copy_id) for value in data)
    return False


@functools.lru_cache(maxsize=1)
def _by_name() -> dict:
    return {card.name: card for card in load_catalog()}


class _Census:
    def __init__(self) -> None:
        self.examined = {"copies": 0, "activations": 0, "prompts": 0, "lines": 0, "bolts": 0}
        self.wrong: list[str] = []

    def table(self, original, copier):
        catalog = _by_name()
        island = catalog["Island"]
        game = Game(players=[
            PlayerState("P0", hand=[catalog[copier], catalog["Lightning Bolt"]], library=[island] * 12),
            PlayerState("P1", library=[island] * 12),
        ])
        game.enforce_mana_costs = False
        for seat, card in ((0, original), (1, catalog["Grizzly Bears"])):
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
        game._sync_control()
        game.start_turn(0)
        game._close_current_priority_step()
        return game

    def run(self, original, copier: str) -> None:
        game = self.table(original, copier)
        source = next((p for p in game.players[0].battlefield if p.card is original), None)
        if source is None:
            return  # gone in its own upkeep (Arcades Sabboth's toll, unpaid)
        result = game.cast_from_hand(
            0, copier, target_player_index=0,
            target_permanent_index=game.battlefield_index_of(source),
        )
        settle(game)
        copy = next((p for p in game.players[0].battlefield if p.card.name == copier), None)
        if not result.supported or copy is None or copy.effective_card.name != original.name:
            return
        self.examined["copies"] += 1
        game.interactive_seats = {0, 1}
        mark = len(game.log)
        armed = game.arm_pending_choice

        def arm(kind, player_index, **data):
            self.examined["prompts"] += 1
            if _offers_printed(data, copier, copy.permanent_id):
                self.wrong.append(f"{original.name}: a {kind} prompt offers the copy as {copier!r}")
            return armed(kind, player_index, **data)

        game.arm_pending_choice = arm

        def activate(index: int) -> None:
            outcome = game.activate_permanent_ability(
                0, copier, permanent_index=game.battlefield_index_of(copy),
                ability_index=index, target_player_index=1,
            )
            self.examined["activations"] += 1
            if not outcome.supported and _names(str(outcome.details), copier):
                self.wrong.append(f"{original.name}: refused as {outcome.details!r}")
            settle(game)

        program = compile_card_oracle(game.playable_card_of(copy))
        for index in range(len(program.activated_abilities)):
            for sick in (True, False):
                if copy not in game.players[0].battlefield:
                    break
                if not sick:
                    copy.metadata["summoning_sickness_turn"] = -99
                    copy.tapped = False
                try:
                    activate(index)
                except (AssertionError, ValueError, KeyError, IndexError):
                    # A target the census could not name, an X it did not
                    # announce: a refusal of the census's own making.
                    pass
        if copy in game.players[0].battlefield and copy.is_creature:
            copy.tapped = False
            copy.metadata["summoning_sickness_turn"] = -99
            for other in game.players[0].battlefield:
                other.tapped = other is not copy
            ok, why = True, ""
            try:
                declare_attack(game, 0, blocks={0: game.battlefield_index_of(copy)})
                drive_combat(game)
            except AssertionError as refused:
                why = str(refused)
                ok = False
            if not ok and _names(why, copier):
                self.wrong.append(f"{original.name}: combat refused as {why!r}")
        if copy in game.players[0].battlefield and any(
            card.name == "Lightning Bolt" for card in game.players[0].hand
        ):
            game.active_player_index = 0
            game.current_turn_phase, game.current_step = "postcombat_main", None
            game.current_phase = "main"
            game.start_priority_window(0)
            targets = game.cast_target_spec(0, next(
                card for card in game.players[0].hand if card.name == "Lightning Bolt"
            )).get("valid_targets") or []
            if _offers_printed(
                [dict(t, id=getattr(game.permanent_at(t["seat"], t["index"]), "permanent_id", None))
                 for t in targets if t.get("kind") == "permanent"],
                copier, copy.permanent_id,
            ):
                self.wrong.append(f"{original.name}: Lightning Bolt offers the copy as {copier!r}")
            game.cast_from_hand(
                0, "Lightning Bolt", target_player_index=0,
                target_permanent_index=game.battlefield_index_of(copy),
            )
            settle(game)
            self.examined["bolts"] += 1
        for line in map(str, game.log[mark:]):
            for pattern in MACHINERY_LINES:
                found = pattern.match(line)
                if found:
                    self.examined["lines"] += 1
                    if _names(found.group("who"), copier):
                        self.wrong.append(f"{original.name}: logged {line!r}")
                    break


def test_the_machinery_names_a_copy_by_what_it_copies():
    census = _Census()
    # A question about permanents, asked of whole cards: a copy copies a
    # permanent (CR 707.2), and no multi-face layout here is one.
    pool = sorted(_by_name().values(), key=lambda card: card.name)
    for card in pool:
        if not stable_sample(card.name, EVERY):
            continue
        if "Creature" in card.type_line:
            census.run(card, "Clone")
        elif "Artifact" in card.type_line:
            census.run(card, "Sculpting Steel")
    examined = census.examined
    # Floors: the sample copied, activated, logged and bolted something.
    assert examined["copies"] >= 40, examined
    assert examined["activations"] >= 20, examined
    assert examined["lines"] >= 40, examined
    assert examined["bolts"] >= 20, examined
    assert not census.wrong, "\n".join(census.wrong[:40])
