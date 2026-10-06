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

**No parse-side mirror**, and no single module to mirror: a gain and a loss are
each one branch of the verb table in ``effects/characteristics.py``
(``_parse_gains``, ``_parse_loses``), the exchange and the set are sentences in
``effects/game.py``, and a payment is a price ``prices.py`` reads. Three parse
homes for one lowering family, asymmetric for the reason ``tokens``, ``zones``,
``types``, ``destruction`` and ``counter_removal`` already record: the guard
fired on the lowering.
"""

import dataclasses

from ...oracle_types import (COUNTERED_SPELL_CONTROLLER, LAST_TARGET_CONTROLLER,
                             LAST_TARGET_OWNER, MANA_PAID_BY_SEAT,
                             OracleInstruction, SECRET_NUMBERS_BY_SEAT,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT)
from .. import ast
from ..errors import LoweringError
from ._seats import _player_recipient
from ._amounts import halved_count_spec, seat_scoped_count_spec, x_offset_amount
from ._common import (
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
)
from ._counted_life import (
    _life_gain_cap_payload,
    lower_counted_gain,
    lower_per_each_gain,
)
from ._events import (
    _DEFENDING_PLAYER_EVENTS,
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
#: card's tie sentence folded in — every player whose number is the least.
#: ``handlers/control_flow._offered_seats`` answers both.
_REVEALED_FEWEST_SEATS = frozenset({"revealed_fewest", "each_revealed_fewest"})


def _lower_gain_life(
    node: ast.GainLife,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    recipient = "caster" if node.player.kind == "you" else "target"
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
                raise LoweringError(
                    '"its controller" names the object an earlier step of this '
                    "effect chose, and no step here recorded one",
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

def _lower_lose_life(
    node: ast.LoseLife,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
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
    if node.player.kind in _REVEALED_FEWEST_SEATS:
        if SECRET_NUMBERS_BY_SEAT not in produced:
            raise LoweringError(
                '"the player who revealed the fewest" with no step of this '
                "effect that had the players reveal anything",
                node=node,
            )
        inner = _lower_lose_life(
            dataclasses.replace(node, player=ast.PlayerRef("that_player")),
            None, produced, None,
        )
        return (
            OracleInstruction(
                "for_each", "",
                {"iterator": {"players": node.player.kind}, "effect": inner},
            ),
        )
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
    if halved is not None:
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
    # "…for each creature card in their graveyard" (Liliana, Death Mage) — the
    # loss is multiplied by a zone count of the losing player's.
    if node.per_each is not None:
        filt = node.per_each
        if node.player.kind != "target_opponent" or filt.zone != "graveyard":
            raise LoweringError(
                "the per-each life loss reads a target opponent's graveyard", node=node
            )
        payload["per_each"] = {
            "zone": "graveyard",
            "owner": (filt.zone_owner.kind if filt.zone_owner else "owner"),
            "card_types": list(filt.card_types),
        }
        # The narrowing, for the reason the plain branch below records it: the
        # gate above admits only "target opponent", so a bare `player` spec
        # offered the ability's own controller (CR 102.2/102.3).
        _describe_targets(payload, node.player)
        return (OracleInstruction("target_loses_life", "", payload),)
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
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "each_opponent":
        payload["recipient"] = "each_opponent"
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "each_player":
        # "Each player loses 2 life." (Bad Deal) — caster included, CR 120.3
        # plain, same handler with one more recipient key.
        payload["recipient"] = "each_player"
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
    make, and ``handlers/control_flow._action_is_takeable`` is where that is
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
