"""Lowering the effects that change a player's **life total** (CR 119).

Split out of ``lowering/game.py`` when Mirage took that module past a thousand
lines -- the same seam ``tokens`` left through one set earlier, and the same
reason: what is left in ``game`` changes the *state of the game* (an extra
turn, winning, losing, ante, a repeated round of offers, a whole-game damage
history), while these change one number on one player -- a gain and a loss
(CR 119.3), a payment (CR 119.4), a set (CR 119.5) and an exchange
(CR 701.12c).

**Whose life it is**, above all. A gain and a loss name their seat out of the
same tables -- the caster, a chosen player, the controller or owner of what an
earlier step acted on, the seat a firing event froze -- and that is the reason
the two stay in one module: "that player" and "its controller" are one printed
phrase each, and ``_lower_lose_life`` records what two answers to one of them
cost (Forsaken Wastes drained the same seat on both upkeeps).

**How much a gain is** left for ``_counted_life`` at the Phase 0 between
Invasion's waves, 21 lines under the size guard. That was the half that grows
with the pool -- a record, a board count, a rate times a count, one more
printed shape most sets -- and it came apart cleanly because
``_lower_gain_life`` settles its seat before it reads any amount: what is left
of that function is the seat, two questions asked of the floor, and the
printed number neither of them claims.

A loss keeps its amounts here. Every counted branch of ``_lower_lose_life``
names the losing seat as it counts -- whose life is halved, whose battlefield,
whose graveyard -- so there the seat and the size are one reading, not two.

**No parse-side family**, and no single module to mirror: the exchange and the
set are sentences in ``effects/game.py``, a payment is a price ``prices.py``
reads, and a gain and a loss are read by ``effects/_life.py`` — this module's
name on the parse side, but a *floor*, pre-split out of
``effects/characteristics.py`` at the Phase 0 before Torment. "Gains" and
"loses" are each one production there (``_parse_gains``, ``_parse_loses``)
whose verb is read before a life total is the question, and a family may not
call another, so they ask the floor where their life arms used to sit. Three
parse homes for one lowering family, asymmetric for the reason ``tokens``,
``zones``, ``types``, ``destruction`` and ``counter_removal`` already record:
the guard fired on the lowering first.
"""

import dataclasses

from ...oracle_types import (COUNTERED_SPELL_CONTROLLER,
                             DISCARDED_CARDS_BY_SEAT, LAST_TARGET_CONTROLLER,
                             LAST_TARGET_OWNER, LIFE_LOST_WHEN_ENTERED,
                             MANA_PAID_BY_SEAT,
                             OracleInstruction, SECRET_NUMBERS_BY_SEAT,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT)
from .. import ast
from ..errors import LoweringError
from ._seats import _player_recipient
from ._amounts import (count_spec, halved_count_spec, seat_scoped_count_spec,
                       x_offset_amount)
from ._cost_records import cost_record_spec
from ._common import (
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
    player_deed_payload,
)
from ._counted_life import (
    _life_gain_cap_payload,
    lower_counted_gain,
    lower_per_each_gain,
)
from ._events import (
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_QUANTITIES,
    _EVENT_SUBJECT_CONTROLLERS,
    LOOP_BOUND_OBJECT,
    SWEPT_CONTROLLER_SEATS,
    _EVENT_SUBJECT_PLAYERS,
    DAMAGED_PERMANENT_CONTROLLER,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
    damage_trigger_names_damaged_end,
)


#: The events whose firing is a **life gain** and that freeze how much
#: (``_EVENT_QUANTITIES``' ``life_gained``): "whenever you gain life" (Vito)
#: and "whenever a player gains life" (False Cure's delayed ability).
_LIFE_GAINED_EVENTS = frozenset({"you_gain_life", "player_gains_life"})


#: The recipients "loses <a fraction of> their life" has one answer per seat
#: for. A count taken against one of them and applied to all of them is the
#: dropped-rider bug with an arithmetic face, so the fraction travels on the
#: per-recipient channel for these and on the ordinary one for the rest.
_PER_SEAT_LIFE_RECIPIENTS = frozenset({"each_player", "each_opponent"})

#: The back-references that name **one number per seat** — a ``{seat: n}`` map
#: an earlier step of the same effect wrote as each player answered it. "Each
#: player loses life equal to the number of items **they** revealed" (Goblin
#: Game) reads one; "the amount of mana **they** paid this way" is the same
#: shape one prompt over. A loss sized from one travels on the per-recipient
#: channel under ``seat_record`` — the key the token maker already reads the
#: paid map by — because the flat ``amount_from`` channel asks the scratchpad
#: for a single number and would be handed the whole map.
_PER_SEAT_NUMBER_RECORDS = frozenset({SECRET_NUMBERS_BY_SEAT, MANA_PAID_BY_SEAT})

#: The described seats a life loss may name that are answered by the secret
#: numbers: the one player whose number is strictly the least, and — with the
#: card's tie sentence folded in — every player whose number is the least
#: (Goblin Game); and every player whose number is the greatest, ties included
#: ("each player with the highest number", Menacing Ogre).
#: ``handlers/offers._offered_seats`` answers all three.
_REVEALED_NUMBER_SEATS = frozenset({
    "revealed_fewest", "each_revealed_fewest", "each_revealed_highest",
})


def _all_but_life_kept(amount) -> "int | None":
    """How much life "all but N life" keeps — N — or None for any other amount.

    The parse's reading of "you lose **all but 1 life**" (Soulgorger Orgg):
    ``ast.Minus`` of a printed number from the life-total board count. Any other
    subtraction is somebody else's shape and answers None.
    """
    if (
        isinstance(amount, ast.Minus)
        and amount.left == ast.BoardCount("their_life")
        and isinstance(amount.right, ast.Fixed)
    ):
        return int(amount.right.value)
    return None


def _counts_the_losers_own_pile(player: "ast.PlayerRef", filt) -> bool:
    """Whether a per-card life loss's printed graveyard is **the losing
    seat's own** — the only pile ``target_loses_life`` counts, once per
    victim.

    "…for each card in **their** graveyard" is the loser's whoever loses
    (Guiltfeeder's defender, Grave Consequences' each player, Liliana's target
    opponent); "…in **your** graveyard" is the loser's only when the loser is
    you. Any other owner ("an opponent's graveyard", "all graveyards") is a
    pile the handler has no channel for, and refusing it names the clause
    rather than counting the wrong player's cards.
    """
    owner = getattr(filt.zone_owner, "kind", None)
    if owner in (None, "owner"):
        return True
    return owner == "you" and player.kind == "you"


def _lower_gain_life(
    node: ast.GainLife,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    recipient = "caster" if node.player.kind == "you" else "target"
    # "**Each player** gains 1 life." (Putrid Warrior.) "…**each opponent**
    # gains that much life." (Grollub.) A *set* of seats, which is the loss's
    # own reading of the same two words one function down — and until Putrid
    # Warrior was driven it was not this function's: the quantifier fell
    # through to "target", so one seat gained and the card compiled supported.
    # In a duel "each opponent" and "the default target" are the same player,
    # which is how Grollub looked right for nine sets; "each player" is wrong
    # at two seats already, because the gain reached one of them.
    if node.player.kind in _PER_SEAT_LIFE_RECIPIENTS:
        recipient = node.player.kind
    # "**Its controller** gains life equal to its mana value." (Illumination.)
    # The controller of the object the previous step acted on, which is neither
    # of the two seats a life gain normally knows — and by the time this runs
    # that object is gone (CR 608.2h): a countered spell is a card in a
    # graveyard, which CR 108.4 gives no controller at all, and a destroyed or
    # exiled permanent is a new object CR 400.7 gives no seat either.
    #
    # It used to fall through to "target", which for a counterspell is the
    # *spell* and for a destroy is whichever player a targetless resolution
    # defaults to. No shipped card took that path — Swords to Plowshares, the
    # pool's only other printing of the sentence, has a fused handler — so it
    # was a hole rather than a bug, and it is closed in the direction that
    # refuses: a step that recorded no seat leaves the clause unlowered and
    # names it, rather than healing somebody the card never mentioned.
    if node.player.kind == "controller":
        # "For each artifact destroyed this way, **its controller** gains life
        # equal to its mana value." (Seeds of Innocence.) Inside an object loop
        # the possessive names the object the *iteration* is on, and the seat
        # comes off the per-object map the sweep froze — the same record and
        # the same reading `_lower_draw` already makes of "its controller
        # draws a card" (Martyr's Cry), one family over.
        #
        # Gated on the loop marker as well as the record, because the record
        # alone is written by any sweep at all: without the marker "Destroy all
        # artifacts. Its controller gains 2 life." would compile to a
        # per-iteration read with no iteration around it, and heal nobody.
        if LOOP_BOUND_OBJECT in produced and SWEPT_CONTROLLER_SEATS in produced:
            recipient = SWEPT_CONTROLLER_SEATS
        else:
            for record in (COUNTERED_SPELL_CONTROLLER, LAST_TARGET_CONTROLLER):
                if record in produced:
                    recipient = record
                    break
            else:
                # "Whenever a Sliver deals damage, **its controller** gains
                # that much life." (Essence Sliver.) With no step in front of
                # the sentence, the possessive names the object the *firing
                # event* was about (CR 603.10) — the damaging Sliver — whose
                # controller the fire site froze. The same last link
                # `cards._lower_draw` asks of the same word ("Whenever a
                # creature with power 4 or greater enters, its controller draws
                # a card", Kavu Lair), off the same table: the trigger's
                # controller is Essence Sliver's, and the life is the Sliver's
                # controller's.
                if event in _EVENT_SUBJECT_CONTROLLERS:
                    recipient = EVENT_SUBJECT_CONTROLLER
                else:
                    raise LoweringError(
                        '"its controller" names the object an earlier step of '
                        "this effect or the firing event chose, and nothing "
                        "here recorded one",
                        node=node,
                    )
    # "Destroy target creature. **Its owner** gains 4 life." (Path of Peace.)
    # CR 108.3's seat, and the branch above's twin in shape and its opposite in
    # answer: the controller is who had the permanent and the owner is whose
    # deck it came from, which differ for every stolen creature — so reading
    # this possessive out of the controller record heals the thief.
    #
    # Gated on a producer for the reason that branch is: a sentence with no step
    # in front of it that chose an object names nobody, and ``recipient`` would
    # otherwise fall through to "target", which for a spell that destroyed
    # something is whichever seat a targetless resolution defaults to. A refusal
    # naming the missing producer is the loud direction.
    if node.player.kind == "owner":
        if LAST_TARGET_OWNER not in produced:
            raise LoweringError(
                '"its owner" names the object an earlier step of this effect '
                "chose, and no step here recorded one",
                node=node,
            )
        recipient = LAST_TARGET_OWNER
    # Read here so every reading below is held to it, the ones `_counted_life`
    # holds included: the only branch that can carry a cap is the
    # back-reference one, and a branch that silently dropped one would gain
    # the uncapped amount.
    cap_payload = _life_gain_cap_payload(node, produced)
    # "…**they** gain 1 life" under "at the beginning of each player's upkeep"
    # (Spiritual Sanctuary). The seat varies per firing, so it is frozen by the
    # fire site and named here; left as the ordinary "target" the gain went to
    # whoever a targetless resolution defaults to, which on the controller's own
    # upkeep was the opponent — the card healing the wrong player.
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        recipient = EVENT_SUBJECT_PLAYER
    # "When this creature leaves the battlefield, you gain life equal to **the
    # life you lost when it entered**." (Soulgorger Orgg.) Not a step of this
    # effect — the number is what the permanent's own entry trigger took,
    # noted on the permanent (``oracle_types.LIFE_LOST_WHEN_ENTERED``; the loss
    # lowering marks it) — so it is read off the source rather than through
    # the back-reference gate below, which would look for a producer in this
    # resolution and refuse. Exactly the printed shape: "you", no cap and no
    # arithmetic on the number, each of which would be a reading nothing here
    # implements.
    if isinstance(node.amount, ast.ThatMuch) and (
        node.amount.source == LIFE_LOST_WHEN_ENTERED
    ):
        if (
            node.amount != ast.ThatMuch(LIFE_LOST_WHEN_ENTERED)
            or node.player.kind != "you"
            or cap_payload
        ):
            raise LoweringError(
                "the life lost when it entered is regained by its controller, "
                "plainly", node=node,
            )
        return (OracleInstruction("target_gains_life", "", {
            "amount_from_source": LIFE_LOST_WHEN_ENTERED, "recipient": "caster",
        }),)
    # **How much** is `_counted_life`'s, asked with the seat settled above. A
    # gain whose size is read off something — a record, a board, a cost, the
    # firing event — answers or refuses there; None means the amount is the
    # printed one and the chain carries on.
    counted = lower_counted_gain(node, recipient, cap_payload, produced, event)
    if counted is not None:
        return counted
    # "You gain **X plus 1** life, where X is the number of green creatures on
    # the battlefield." (An-Havva Inn.) A printed constant on top of the
    # sentence's X, carried on the amount rather than folded into the count that
    # defines it: the where-clause is stamped onto this instruction afterwards
    # and is the same count An-Havva Constable's toughness reads, so a constant
    # added there would belong to the count and change the creature too.
    # `_amount_payload` is deliberately not taught the shape — it feeds fifty
    # callers, several of which compare its result to a number.
    offset = x_offset_amount(node.amount)
    payload: dict[str, object] = {
        "amount": offset if offset is not None else _amount_payload(node.amount),
        "recipient": recipient,
    }
    # A printed rate **for each** of something is `_counted_life`'s too, and
    # asked second because it multiplies the amount built above. None means
    # the sentence printed no multiplier.
    multiplied = lower_per_each_gain(node, payload, recipient, produced, event)
    if multiplied is not None:
        return multiplied
    _describe_targets(payload, node.player)
    return (OracleInstruction("target_gains_life", "", payload),)

#: The ``who <did …>`` kinds whose record only *this* resolution writes, and
#: the producer key each one reads — a clause naming one with nothing in front
#: of it recording it names no seats at all.
_DEED_PRODUCERS = {
    "discarded_this_way": DISCARDED_CARDS_BY_SEAT,
}


def _stamp_loss_deed(payload: dict, node: ast.LoseLife, produced) -> None:
    """"Then **each player who didn't discard a creature card this way** loses
    4 life." (Strongarm Tactics.)

    The seat narrowing the subject printed, carried to the handler that loops
    the seats — the damage family's ``_stamp_recipient_deed``, through the same
    ``player_deed_payload``. A "this way" record needs its producer in front of
    it, for every back-reference's reason."""
    deed = node.player.did
    if deed is None:
        return
    needed = _DEED_PRODUCERS.get(deed.kind)
    if needed is not None and needed not in produced:
        raise LoweringError(
            f"back-reference to {needed!r} with no producer in this effect",
            node=node,
        )
    payload["recipient_did"] = player_deed_payload(node.player, node)


def _lower_lose_life(
    node: ast.LoseLife,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    if node.player.did is not None and node.player.kind not in (
        "each_player", "each_opponent",
    ):
        # A seat narrowing only the two looped subjects carry (below). On any
        # other subject it would reach a handler that never reads it — a loss
        # landing on a seat the clause excludes.
        raise LoweringError(
            "only a looped life loss carries a who-did narrowing", node=node
        )
    # "Whenever you gain life, target opponent loses **that much** life."
    # (Vito, Thorn of the Dusk Rose.) The number is the life-gain event's, not
    # anything this effect computed, so it arrives as a trigger-context key
    # rather than as an amount. Resolved before the payload is built, because
    # an amount and a back-reference are alternatives — carrying both would let
    # a handler read whichever it happened to check first.
    # "**The player who revealed the fewest items** then loses half their
    # life, rounded up." (Goblin Game.) A seat — or, with the tie sentence, a
    # set of them — that only the record an earlier step wrote can name, so it
    # is a loop over that set with the loss inside it: ``for_each`` binds each
    # seat as "that player" in turn, and the body is this same sentence said of
    # that player. Lowered through this function rather than beside it, so
    # every amount a loss can print is an amount this subject can lose.
    #
    # With no event: under a trigger "that player" would be re-read as the
    # seat the firing was about, and the seat here is the loop's.
    if node.player.kind in _REVEALED_NUMBER_SEATS:
        if SECRET_NUMBERS_BY_SEAT not in produced:
            raise LoweringError(
                f"{node.player.kind!r} with no step of this effect that had "
                "the players reveal a number",
                node=node,
            )
        amount = node.amount
        if (
            isinstance(amount, ast.ThatMuch) and amount.source is None
            and not amount.bonus
        ):
            # "Each player with the highest number loses **that much** life."
            # (Menacing Ogre.) The number that put the seat in the set — its
            # own secret number, which is also the highest: the bare
            # back-reference names the comparison the subject was made by.
            amount = ast.ThatMuch(SECRET_NUMBERS_BY_SEAT)
        if (
            isinstance(amount, ast.ThatMuch)
            and amount.source == SECRET_NUMBERS_BY_SEAT and not amount.bonus
        ):
            # Each looped seat's own entry of the map, on the per-recipient
            # channel the "each player" loss above reads it by: the loop binds
            # the seat as the step's target and the channel counts for it.
            inner: tuple[OracleInstruction, ...] = (
                OracleInstruction(
                    "target_loses_life", "",
                    {
                        "amount": "x",
                        X_FROM_COUNT_PER_RECIPIENT: {
                            "seat_record": SECRET_NUMBERS_BY_SEAT,
                        },
                    },
                ),
            )
        else:
            inner = _lower_lose_life(
                dataclasses.replace(
                    node, player=ast.PlayerRef("that_player"), amount=amount,
                ),
                None, produced, None,
            )
        return (
            OracleInstruction(
                "for_each", "",
                {"iterator": {"players": node.player.kind}, "effect": inner},
            ),
        )
    # "When this creature enters, you lose **all but 1 life**." (Soulgorger
    # Orgg.) The loser's own life total less what they keep, so it rides the
    # per-recipient channel whatever the subject is: that channel counts
    # against the seat losing the life (owner-blind by design, see Pox below)
    # and floors the answer at zero (``handlers/_amounts.per_recipient_amount``)
    # — which is ``ast.Minus``'s "never below zero" made true at the one place
    # a negative number would otherwise have *given* life to a player at 0.
    kept = _all_but_life_kept(node.amount)
    # "…and loses **half their life**" (Peer into the Abyss): a number the
    # resolution computes, travelling on the same spec a counted amount does.
    halved = (
        halved_count_spec(node.amount, node)
        if isinstance(node.amount, ast.Half)
        else None
    )
    if halved is not None and halved.get("board_count") == "their_life":
        # **Whose life is halved is the seat losing it.** The parse reads
        # "half **their** life" (Peer into the Abyss) and "half **your** life"
        # (Infernal Contract, Doomsday) with one production and one node, and
        # `halved_count_spec` mints the spec for the printing that was minted
        # first — "target". So a card whose sentence names *you* counted the
        # target's life total instead: Infernal Contract at 7 life against an
        # opponent at 20 cost its controller 10 and killed them, and the two
        # cards read identically at equal life totals, which is why nothing had
        # seen it.
        #
        # The node already carries the answer, because a life loss and the
        # amount that sizes it are one clause: the player who loses the life is
        # the player whose life is halved. So the seat is read off `node.player`
        # rather than left where the spec put it.
        halved = dict(halved)
        halved["owner"] = "you" if node.player.kind == "you" else "target"
    if kept is not None:
        payload = {
            "amount": "x",
            X_FROM_COUNT_PER_RECIPIENT: {
                "board_count": "their_life", "owner": "target", "plus": -kept,
            },
        }
    elif halved is not None:
        # "**Each player** loses a third of their life" (Pox). One number per
        # seat, and `X_FROM_COUNT` is resolved once at the dispatch point
        # against `context.target` — so a multi-seat recipient carrying it would
        # take *one* player's life total and subtract that share from everybody.
        # The per-recipient channel is the one the damage sweeps already use for
        # this exact reason. A single-seat recipient keeps the payload it had.
        # …and only when the count is about the *losing* player. "Each opponent
        # loses X life, where X is the number of Shrines **you** control"
        # (Sanctum of Stone Fangs) is one number by construction, and the
        # per-recipient evaluator is owner-blind — it counts against whichever
        # seat it is handed — so routing that one through here would count each
        # opponent's own Shrines instead.
        key = (
            X_FROM_COUNT_PER_RECIPIENT
            if (
                node.player.kind in _PER_SEAT_LIFE_RECIPIENTS
                and halved.get("owner") == "target"
            )
            else X_FROM_COUNT
        )
        payload: dict[str, object] = {"amount": "x", key: halved}
    elif (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source in _PER_SEAT_NUMBER_RECORDS
    ):
        # "Each player loses life equal to **the number of items they
        # revealed**." (Goblin Game.) One number per seat off a map an earlier
        # step wrote — see ``_PER_SEAT_NUMBER_RECORDS``. Both refusals are ways
        # the words could otherwise name nothing: with no producer the map does
        # not exist, and under a subject that is one seat "they" has nothing to
        # range over.
        if node.amount.source not in produced:
            raise LoweringError(
                f"back-reference to {node.amount.source!r} with no producer "
                "in this effect",
                node=node,
            )
        if node.player.kind not in _PER_SEAT_LIFE_RECIPIENTS:
            raise LoweringError(
                "a recorded per-seat number needs a distributed subject to "
                "be about",
                node=node,
            )
        payload = {
            "amount": "x",
            X_FROM_COUNT_PER_RECIPIENT: {"seat_record": node.amount.source},
        }
    elif (paid := cost_record_spec(node.amount, node)) is not None:
        # "{B}, {T}, Sacrifice a Cleric creature: Target player loses life
        # equal to **the sacrificed creature's power**." (Starlit Sanctum.)
        # The number is a record the ability's own cost kept (CR 608.2h's
        # last-known information for the sacrifice), read through the one
        # helper every other family spends a cost record with — the pump's X,
        # the mill, the damage — so the readable characteristics are that
        # table's and not a third copy. The gain beside this has read the same
        # record since Life Chisel; the loss fell to ``_amount_payload``, which
        # knows no cost record, and refused.
        payload = {"amount": "x", X_FROM_COUNT: paid}
    elif isinstance(node.amount, ast.CountOf):
        # "…you may have target player lose life **equal to the number of
        # Zombies on the battlefield**." (Gempalm Polluter.) The gain's
        # counted amount one verb over (``_counted_life``, Rin and Seri),
        # through the one evaluator — and held to the two boards the per-each
        # loss below admits for the same reason: "you control" and the whole
        # battlefield are one number whoever loses, while a count naming the
        # *losing* seat ("they control") would be counted once against the
        # target and taken from every seat a looped subject names.
        counted = node.amount.filter
        if counted.zone != "battlefield" or not (
            counted.controller == "you"
            or (counted.on_the_battlefield and counted.controller is None)
        ):
            raise LoweringError(
                "a life loss equal to a count reads your battlefield or the "
                "whole of it",
                node=node,
            )
        payload = {"amount": "x", X_FROM_COUNT: count_spec(counted, node)}
    else:
        payload = (
            dict(_back_reference_payload(node.amount, produced, event))
            if isinstance(node.amount, ast.ThatMuch)
            else {"amount": _amount_payload(node.amount)}
        )
    # "Each opponent who can't loses 3 life." (Liliana, Waker of the Dead) —
    # attached by the sentence-loop rider to a preceding each-player discard,
    # whose handler records the players that could not pay. Reading that record
    # is the whole effect, so it is its own kind rather than a flag on the
    # general loss.
    if node.who_could_not is not None:
        if node.who_could_not != "discard" or node.player.kind != "each_opponent":
            raise LoweringError(
                "the could-not rider only reads an each-player discard", node=node
            )
        return (
            OracleInstruction("opponents_who_could_not_discard_lose_life", "", payload),
        )
    # "You lose 2 life **for each creature that died this way**." (Reign of
    # Terror.) The multiplier is one earlier step's result, not a count of any
    # zone — so it reads the record every destroy sweep writes, on the same
    # producer discipline every back-reference in this grammar follows: with
    # nothing recorded in front of it the words name nothing, and a zero is a
    # number the card never printed.
    if isinstance(node.per_each, ast.DiedThisWay):
        if node.player.kind != "you":
            raise LoweringError(
                "the died-this-way life loss is the effect's own controller's",
                node=node,
            )
        if "destroyed_this_way" not in produced:
            raise LoweringError(
                "back-reference to 'destroyed_this_way' with no producer in "
                "this effect",
                node=node,
            )
        # Only the bare noun, exactly as `deal_damage`'s reading of the same
        # printed clause admits: the record is a *number*, so a narrowing
        # beyond the noun is a question nothing can re-ask, and counting as
        # though the narrowing were not there is the dropped-rider bug.
        leftover = _restrictions_beyond(
            node.per_each.filter, frozenset({"card_types"})
        )
        if leftover or node.per_each.filter.zone != "battlefield":
            raise LoweringError(
                "'died this way' counts what the earlier step destroyed and "
                "cannot be narrowed further",
                node=node,
            )
        payload["recipient"] = "caster"
        payload["per_each"] = {"record": "destroyed_this_way"}
        return (OracleInstruction("target_loses_life", "", payload),)
    if isinstance(node.per_each, ast.DiedThisTurn):
        # The sibling spelling the same reader now admits. No card in the pool
        # prints it on a *loss*, and an unread multiplier would lose the
        # printed base once instead of once per death — so it refuses here and
        # names the clause, rather than falling through to the zone-count
        # branch below, which would ask this node for a `zone` it does not have.
        raise LoweringError(
            "no life-loss handler counts the turn's death tally", node=node
        )
    # "Until end of turn, whenever a player gains life, that player loses 2
    # life **for each 1 life they gained**." (False Cure.) Transcendence's
    # count one event over (``_counted_life``'s ``EachLifeLost`` branch): the
    # printed 2 is the rate on ``amount`` and the count is the firing gain,
    # frozen into the trigger's context by the life-gain seam — one loss of
    # the product, not a loss per point. Refused under an event that records
    # no gain and over any unit but 1, for that branch's reasons.
    if isinstance(node.per_each, ast.EachLifeGained):
        key = (
            _EVENT_QUANTITIES.get(event or "")
            if event in _LIFE_GAINED_EVENTS else None
        )
        if key is None:
            raise LoweringError(
                f"no event named {event!r} records the life this loss counts",
                node=node,
            )
        if node.per_each.per != 1 or not isinstance(node.amount, ast.Fixed):
            raise LoweringError(
                "this loss is a printed rate per 1 life gained", node=node,
            )
        payload["per_each"] = {"trigger_record": key}
    # "Each player loses 1 life for each creature **they** control."
    # (Stronghold Discipline.) One number per losing seat, counted on that
    # seat's own battlefield — the per-recipient channel the halved loss above
    # and the damage sweeps already read, with the printed amount as the
    # multiplier. Only for a recipient the handler *loops*: under a single seat
    # "they" has nothing to range over, and the target-opponent graveyard reading
    # below keeps its own payload.
    if (
        node.per_each is not None
        and node.player.kind in _PER_SEAT_LIFE_RECIPIENTS
        and isinstance(node.amount, ast.Fixed)
    ):
        per_seat = seat_scoped_count_spec(
            node.per_each, node, multiplier=node.amount.value
        )
        if per_seat is not None:
            return (
                OracleInstruction("target_loses_life", "", {
                    "amount": "x",
                    X_FROM_COUNT_PER_RECIPIENT: per_seat,
                    "recipient": node.player.kind,
                }),
            )
    # "Target opponent loses 2 life **for each Swamp you control**." (Last
    # Stand.) The count is the effect's controller's own board — one number
    # whoever loses the life, so it is the shared ``x_from_count`` channel with
    # the printed rate as its multiplier and the recipient stays whatever the
    # branches below make of the subject. Only "you control": a phrase naming
    # the *losing* seat is the per-recipient reading above, and one naming no
    # seat at all is a count nothing here scopes.
    #
    # "{T}: Each player loses 1 life for each Zombie **on the battlefield**."
    # (Shepherd of Rot.) CR 403.1's one shared zone — the whole board, which
    # is one number whoever loses, so it is this channel too: ``count_spec``
    # reads the phrase into ``owner: "all"`` exactly as it does for Wellwisher's
    # gain. It fell to the graveyard branch below and refused there, because
    # that branch is the only other reader of a per-each count.
    if (
        isinstance(node.per_each, ast.ObjectFilter)
        and node.per_each.zone == "battlefield"
        and (
            node.per_each.controller == "you"
            or (
                node.per_each.on_the_battlefield
                and node.per_each.controller is None
            )
        )
        and isinstance(node.amount, ast.Fixed)
    ):
        payload = {
            "amount": "x",
            X_FROM_COUNT: count_spec(
                node.per_each, node, multiplier=node.amount.value
            ),
        }
    # "…for each creature card in their graveyard" (Liliana, Death Mage) — the
    # loss is multiplied by a zone count of the losing player's.
    #
    # "Whenever this creature attacks and isn't blocked, **defending player**
    # loses 1 life for each card in their graveyard." (Guiltfeeder.) "…Then
    # **each player** loses 1 life for each card in their graveyard." (Grave
    # Consequences.) The same count for any losing seat: the handler counts
    # each victim's *own* pile, so what the gate holds is that the printed
    # pile **is** the loser's — "their" graveyard, or "your" graveyard when
    # the loser is you. It held a seat instead ("target opponent" only), and
    # that admitted "your graveyard" after a target opponent, which the
    # handler would have counted out of the opponent's pile. The recipient is
    # then whatever the branches below make of the subject, the gate each of
    # them already puts in front of its word ("defending player" only under an
    # event that froze one) included.
    elif node.per_each is not None and not isinstance(
        node.per_each, ast.EachLifeGained
    ):
        filt = node.per_each
        if filt.zone != "graveyard" or not _counts_the_losers_own_pile(
            node.player, filt
        ):
            raise LoweringError(
                "the per-each life loss counts the losing player's own graveyard",
                node=node,
            )
        payload["per_each"] = {
            "zone": "graveyard",
            "owner": (filt.zone_owner.kind if filt.zone_owner else "owner"),
            "card_types": list(filt.card_types),
        }
    # "**That player**" after an event that was *about an object*: the object's
    # controller. Massacre Wurm's dead creature is in a graveyard by the time
    # the trigger resolves and Gloom Sower's blocker may have left combat, so
    # neither seat survives a board read — the fire site freezes it (CR 603.10),
    # exactly as Basri's Lieutenant's counter clause and Conclave Mentor's power
    # are frozen. Which events carry a subject is a table rather than a rule,
    # for the reason `_EVENT_QUANTITIES` is: an event either had one or it did
    # not. Anywhere else "that player" is the ordinary chosen target below.
    #
    # "Whenever **this creature** deals combat damage to a creature, **that
    # creature's controller** loses 2 life" (Death Charmer) names the *other*
    # end of a `damage_dealt` event, which that table answers with the
    # damager's seat — so the Charmer's own controller lost the life. Read
    # first, by the one predicate the damage recipient already asks of the same
    # phrase (`_recipients.py`, Bellowing Fiend), so the two families cannot
    # answer it differently.
    if node.player.kind == "that_player" and damage_trigger_names_damaged_end(
        event, event_subject
    ):
        payload["recipient"] = DAMAGED_PERMANENT_CONTROLLER
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_CONTROLLERS:
        payload["recipient"] = "event_subject_controller"
        return (OracleInstruction("target_loses_life", "", payload),)
    # "**That player**" after an event that was about a **player** rather
    # than an object: the seat whose upkeep, end step or draw it was, frozen
    # by the fire site. This branch was missing, and the fall-through below
    # is what it fell to — the ordinary chosen-target reading, which under a
    # trigger nobody targeted lands on ``context.target``. Forsaken Wastes
    # ("at the beginning of each player's upkeep, that player loses 1 life")
    # therefore drained the *opponent* on both upkeeps and never its own
    # controller: a strictly one-sided card, compiled clean.
    #
    # The same table and the same key `_lower_gain_life` above already reads
    # for the same printed word ("…**they** gain 1 life"), which is what makes
    # the miss visible in hindsight — one module, one phrase, two answers.
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        payload["recipient"] = EVENT_SUBJECT_PLAYER
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind in ("target_player", "target_opponent", "that_player"):
        # **The printed narrowing, recorded.** "Target **opponent** loses 1
        # life" (Ebony Charm, Forbidden Ritual, Vito) reached the picker as a
        # bare instruction kind, and `targeting._KIND_SPECS` answers
        # ``{"kind": "player"}`` for `target_loses_life` — which offers the
        # caster their own face, a live two-player bug (CR 102.2). The
        # description is what every other player picker in the engine reads,
        # and it is `_targets_payload`'s answer rather than a flag invented
        # here, so "target opponent" narrows the same way whichever sentence
        # prints it.
        #
        # "That player" gets no entry, and that is the same function's answer
        # rather than a branch here: the seat was frozen by the firing event
        # and nobody chooses it (CR 115.10b).
        _describe_targets(payload, node.player)
        return (OracleInstruction("target_loses_life", "", payload),)
    # "Destroy target creature. Its controller loses 2 life." (Liliana, Death
    # Mage's −3.) The controller of the previous step's target — recorded by
    # the destroy handler in the resolution scratchpad, because by the time
    # this instruction runs the permanent is gone (CR 608.2h, last-known
    # information).
    if node.player.kind == "controller":
        # "When enchanted creature dies, **its controller** loses life equal to
        # its power." (Death Watch.) Under a trigger nothing targeted, the
        # scratchpad key a destroy step writes was never written — and reading
        # it anyway is a loss aimed at whichever seat an empty record defaults
        # to. The seat the *event* was about is frozen by the fire site
        # (CR 603.10: by resolution the creature is a card in a graveyard, and
        # CR 108.4 gives that no controller at all), which is the same key and
        # the same table "that player" one branch up already reads.
        #
        # The scratchpad record is preferred when a step of this same effect
        # wrote one, so "Destroy target creature. Its controller loses 2 life."
        # keeps the reading it has: inside one resolution the pronoun names
        # what that resolution acted on, not what fired it.
        #
        # "Counter target spell. **Its controller** loses 3 life." (Undermine.)
        # The object the step in front chose is a *spell*, and a spell's seat
        # has its own record (``COUNTERED_SPELL_CONTROLLER`` — a countered
        # spell is a card in a graveyard, which CR 109.4 gives no controller).
        # This branch wrote the permanent record whatever the step in front
        # had produced, so the sentence compiled and read a key only a destroy
        # writes: Undermine shipped and never made anyone lose life. Asked in
        # the order `_lower_gain_life` above already asks for the same word —
        # one module, one phrase, and until now two answers.
        if COUNTERED_SPELL_CONTROLLER in produced:
            payload["recipient"] = COUNTERED_SPELL_CONTROLLER
            return (OracleInstruction("target_loses_life", "", payload),)
        if LAST_TARGET_CONTROLLER not in produced and (
            event in _EVENT_SUBJECT_CONTROLLERS
        ):
            payload["recipient"] = EVENT_SUBJECT_CONTROLLER
            return (OracleInstruction("target_loses_life", "", payload),)
        payload["recipient"] = "last_target_controller"
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "you":
        # "You lose 3 life" (Grim Tutor) — the same recipient key deal_damage
        # and target_gains_life read.
        payload["recipient"] = "caster"
        if event == "enters_battlefield":
            # "…you gain life equal to **the life you lost when it entered**."
            # (Soulgorger Orgg's other ability.) CR 607.1 links the two: the
            # reader refers only to what *this* ability did, and the lowering
            # is the one layer that knows a loss is a permanent's own entry
            # trigger — the handler is handed an instruction, not the ability
            # it came from. So every such loss notes what it took on its
            # source, inert for each card whose other abilities never ask
            # (the linked-exile pile's arrangement: always recorded, read by
            # the card that prints the second half).
            payload["noted_on_source"] = LIFE_LOST_WHEN_ENTERED
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "each_opponent":
        payload["recipient"] = "each_opponent"
        _stamp_loss_deed(payload, node, produced)
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "each_player":
        # "Each player loses 2 life." (Bad Deal) — caster included, CR 120.3
        # plain, same handler with one more recipient key.
        payload["recipient"] = "each_player"
        _stamp_loss_deed(payload, node, produced)
        return (OracleInstruction("target_loses_life", "", payload),)
    # "… and **defending player** loses 2 life." (Keeper of Tresserhorn,
    # Lim-Dûl's Paladin.) CR 506.2's seat, frozen into the trigger's context by
    # the combat fire site — the same gate the discard and the offer already put
    # in front of the phrase, and for the same reason: under any other event
    # nothing recorded a defender, and a life loss aimed at nobody is an effect
    # that compiles clean and silently does not happen.
    if node.player.kind == "defending_player":
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        payload["recipient"] = "defending_player"
        return (OracleInstruction("target_loses_life", "", payload),)
    raise LoweringError(f"unsupported life-loss target {node.player.kind!r}", node=node)

def _lower_exchange_life_totals(
    node: ast.ExchangeLifeTotals,
) -> tuple[OracleInstruction, ...]:
    """"Exchange life totals with target opponent." (Mirror Universe.)

    The exchange is between the ability's controller and one other seat, so the
    payload carries only who the other seat is — CR 701.12c then makes it two
    gains/losses of the difference, which is the handler's business.

    A *targeted* seat only. "Exchange life totals with each opponent" is not an
    exchange any number of players can be in (whose total would each of them
    get?), so the sweeping recipients the rest of this module accepts refuse
    here rather than picking one of them.
    """
    if node.player.kind not in ("target_opponent", "target_player"):
        raise LoweringError(
            f"an exchange of life totals needs one named seat, not "
            f"{node.player.kind!r}",
            node=node,
        )
    payload: dict[str, object] = {"recipient": "target"}
    if node.player.kind == "target_opponent":
        # The printed narrowing, carried the way every other player picker in
        # the engine reads it. `targeting`'s kind table answers a flat
        # ``{"kind": "player"}`` for this kind — right for "target player" and
        # wrong for "target opponent", whose seat can never be the chooser's
        # own (CR 102.2/102.3), so Mirror Universe offered its controller their
        # own life total to swap with themselves.
        #
        # **The opponent spelling only**, and that is not caution: "exchange
        # life totals with **that player**" (Psychic Transfer) reaches this
        # function as ``target_player`` too, because the pronoun is rebound to
        # the seat the *condition* already targeted. Describing that would
        # announce a second target for a seat the spell has already chosen.
        # The narrowing is the thing that was missing; the bare description was
        # not.
        _describe_targets(payload, node.player)
    return (OracleInstruction("exchange_life_totals", "", payload),)

def _lower_set_life_total(node: ast.SetLifeTotal) -> tuple[OracleInstruction, ...]:
    """"That player's life total becomes 20." (Rebirth.)

    CR 119.5 makes this a gain or a loss of the difference, so the handler works
    out the direction; the payload carries the printed *result*, which is all
    the card says.

    "**Target player's** life total becomes 20." (Blessed Wind.) A seat chosen
    as the spell is cast (CR 601.2c), on the ``"target"`` recipient key and the
    description every other player picker in this module reads, so "target
    opponent" would narrow the way Mirror Universe's exchange does. Not a row in
    ``_seats``' ante table: that table is the ante handler's vocabulary too, and
    no ante sentence names a chosen seat.
    """
    if isinstance(node.amount, ast.CountOf):
        # "**Each player's** life total becomes the number of creatures **they**
        # control." (Biorhythm.) One number per seat, counted on that seat's
        # own battlefield: the per-recipient channel the damage sweeps and the
        # life loss already carry it on, through the floor's one reading of
        # "they" (``seat_scoped_count_spec``). Only under the seat-set subject
        # whose handler loops — a count naming no recipient's seat, or a
        # recipient that is one seat, is a sentence nothing here was taught,
        # and it refuses rather than counting somebody's board for everybody.
        per_seat = seat_scoped_count_spec(node.amount.filter, node)
        if per_seat is None or node.player.kind != "each_player":
            raise LoweringError(
                "a life total set to a count is counted per seat over each "
                "player",
                node=node,
            )
        return (
            OracleInstruction(
                "set_life_total", "",
                {
                    "recipient": "each_player",
                    "amount": "x",
                    X_FROM_COUNT_PER_RECIPIENT: per_seat,
                },
            ),
        )
    if node.player.kind in ("target_player", "target_opponent"):
        payload: dict[str, object] = {
            "recipient": "target", "amount": _amount_payload(node.amount),
        }
        _describe_targets(payload, node.player)
        return (OracleInstruction("set_life_total", "", payload),)
    return (
        OracleInstruction(
            "set_life_total", "",
            {
                "recipient": _player_recipient(node.player, node),
                "amount": _amount_payload(node.amount),
            },
        ),
    )

def _lower_pay_life(node: ast.PayLife) -> tuple[OracleInstruction, ...]:
    """"Pay 4 life." (Sylvan Library.) CR 119.4.

    Its own kind rather than a life loss with a flag, for the reason
    ``ast.PayLife`` gives: a payment is something a player has to be *able* to
    make, and ``handlers/offers._action_is_takeable`` is where that is
    asked of every alternative before it is offered. A loss lowered onto the
    same kind would start answering that question about sentences that never
    pose it.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler makes {node.player.kind!r} pay life", node=node
        )
    amount = _amount_payload(node.amount)
    if not isinstance(amount, int) or amount < 0:
        raise LoweringError("a life payment is a printed number", node=node)
    return (OracleInstruction("pay_life", "", {"amount": amount}),)
