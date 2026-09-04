"""Lowering tokens, life, and whole-game effects.

Token creation (paired with the generic `create_token` instruction kind, so a
token-making card is a production plus a lowering and never a bespoke handler),
life gain and loss, extra turns, and winning or losing the game.

Grouped as "the game and its players" rather than "the board": none of these
changes what a permanent is, and all of them change the state a player is in.
"""

from ...oracle_types import (COUNTERED_SPELL_CONTROLLER, LAST_TARGET_CONTROLLER,
                             OracleInstruction, X_FROM_COUNT,
                             X_FROM_COUNT_PER_RECIPIENT)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._records import optional_cost_key
from ._amounts import count_spec, halved_count_spec, x_offset_amount
from ._common import (
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
)
from ._events import (
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    COUNTED_NUMBER,
    DAMAGE_RECIPIENT,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
)


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------


def _life_gain_cap_payload(
    node: ast.GainLife, produced: frozenset[str]
) -> dict[str, object]:
    """"…but not more than A, B, C, or D" as payload, or ``{}``.

    The three recipient terms fold into one entry carrying *which kinds of
    recipient* they named, because the engine answers them with one number —
    what the damaged object could absorb before the damage — and which of the
    three that number means is a fact about the target, not about the sentence.
    The kinds are kept so a card printing only "the creature's toughness" does
    not cap a gain from damaging a player.

    Refused rather than dropped when nothing in this effect recorded the
    recipient: a cap the handler cannot read would gain the uncapped amount,
    which is the failure this whole clause exists to prevent.
    """
    if not node.capped_by:
        return {}
    if not isinstance(node.amount, ast.ThatMuch):
        raise LoweringError(
            "a capped life gain reads back what an earlier step dealt", node=node,
        )
    terms: list[dict[str, object]] = []
    recipients = tuple(
        cap.recipient for cap in node.capped_by
        if cap.kind == "recipient_capacity" and cap.recipient
    )
    if recipients:
        if DAMAGE_RECIPIENT not in produced:
            raise LoweringError(
                "a cap on the damaged object's life, loyalty or toughness needs "
                "a step of this effect that damaged one",
                node=node,
            )
        terms.append({"kind": "recipient_capacity", "recipients": list(recipients)})
    for cap in node.capped_by:
        if cap.kind == "mana_spent_on_x":
            # "the amount of {B} spent on X" — a fact about the *cast*, carried
            # on the stack item by the payment that chose the split, not about
            # anything an earlier instruction did. So there is no producer to
            # gate on here; a resolution with no such record caps the gain at
            # zero, which is the safe direction.
            terms.append({"kind": "mana_spent_on_x", "symbol": cap.symbol})
    unknown = {cap.kind for cap in node.capped_by} - {
        "recipient_capacity", "mana_spent_on_x",
    }
    if unknown:
        raise LoweringError(
            f"no reader for life-gain cap {sorted(unknown)!r}", node=node,
        )
    return {"capped_by": terms}


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
    # Read here so every branch below is held to it: the only branch that can
    # carry a cap is the back-reference one, and a branch that silently dropped
    # one would gain the uncapped amount.
    cap_payload = _life_gain_cap_payload(node, produced)
    # "…**they** gain 1 life" under "at the beginning of each player's upkeep"
    # (Spiritual Sanctuary). The seat varies per firing, so it is frozen by the
    # fire site and named here; left as the ordinary "target" the gain went to
    # whoever a targetless resolution defaults to, which on the controller's own
    # upkeep was the opponent — the card healing the wrong player.
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        recipient = EVENT_SUBJECT_PLAYER
    # "When this creature dies, you gain life equal to **its** power."
    # (Conclave Mentor.) "It" is the source, which is in a graveyard by the
    # time this resolves — so the amount is last-known information (CR 603.10)
    # frozen by the fire site, exactly as Basri's Lieutenant's counter clause
    # is. Admitted only under a dies trigger, because that is the only event
    # that records it; anywhere else the back-reference still refuses below.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and event == "dies"
        and node.player.kind == "you"
        # This shortcut returns before the back-reference branch below, which
        # is the only one that carries a cap, so it declines a capped gain
        # rather than dropping the cap on the way past.
        and not node.capped_by
    ):
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from_trigger": "dead_power", "recipient": "caster"},
            ),
        )
    # "…you may gain life equal to **its** power" (Delif's Cone), inside a delay
    # whose opener targeted the creature (CR 603.7c) — so "it" is that creature
    # and `rebinding` said so by naming the amount for it. Read live at
    # resolution rather than frozen: the creature is on the battlefield,
    # attacking and unblocked, at the moment this ability resolves.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "bound_power"
    ):
        if node.player.kind != "you" or node.capped_by:
            raise LoweringError(
                "the bound creature's power is gained by the ability's own "
                "controller, uncapped",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from_bound_power": True, "recipient": "caster"},
            ),
        )
    if isinstance(node.amount, ast.SacrificedForCost):
        # "You gain life equal to the sacrificed creature's toughness" (Life
        # Chisel, Diamond Valley). The number is read off the permanent the
        # ability's own cost ate, which the activation path carried forward as
        # last-known information (CR 608.2h) — so the payload names the
        # characteristic and the handler names the channel.
        #
        # Toughness alone, because that is the only characteristic anything
        # reads back off that record today: emitting "power" here would produce
        # an instruction the handler would answer with a zero, which is the
        # silent half of the failure this file refuses on behalf of.
        if node.amount.characteristic != "toughness":
            raise LoweringError(
                "no handler reads the sacrificed permanent's "
                f"{node.amount.characteristic!r}",
                node=node,
            )
        if node.player.kind != "you":
            raise LoweringError(
                "the sacrificed permanent's toughness is gained by the "
                "ability's own controller",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount_from_cost_sacrifice": node.amount.characteristic,
                    "recipient": "caster",
                },
            ),
        )
    if isinstance(node.amount, ast.ThatMuch):
        # "You gain life equal to the damage dealt" — reads the value the
        # preceding damage instruction recorded in the resolution scratchpad,
        # which is what lets the two effects be separate instructions at all.
        # A bare "that much" may instead name the firing event's own quantity;
        # `_back_reference_payload` is the one place that decides which, and
        # refuses when neither offers a number rather than reading a zero.
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    **_back_reference_payload(node.amount, produced, event),
                    "recipient": recipient,
                    **cap_payload,
                },
            ),
        )
    # "You gain life equal to the number of Cats you control." (Rin and Seri.)
    # A counted amount, through the same evaluator every other computed number
    # in the engine uses — the alternative is a second counter with its own
    # spelling of the spec, which is the drift `count_spec` exists to prevent.
    if isinstance(node.amount, ast.CountOf):
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": "x", "recipient": recipient,
                    X_FROM_COUNT: count_spec(node.amount.filter, node),
                },
            ),
        )
    # "You gain **X plus 1** life, where X is the number of green creatures on
    # the battlefield." (An-Havva Inn.) A printed constant on top of the
    # sentence's X, carried on the amount rather than folded into the count that
    # defines it: the where-clause is stamped onto this instruction afterwards
    # and is the same count An-Havva Constable's toughness reads, so a constant
    # added there would belong to the count and change the creature too.
    # `_amount_payload` is deliberately not taught the shape — it feeds fifty
    # callers, several of which compare its result to a number.
    # "You gain 3 life **plus an additional 3 life for each additional {1}{G}
    # you paid**." (Taste of Paradise.) One gain (CR 119.3) whose amount scales
    # with a CR 601.2b payment: the printed base, plus a per-payment step times
    # however many times the caster took the offer. Two instructions would show
    # a life-gain replacement two events where the card prints one.
    #
    # Read before `x_offset_amount` below, which reads the other shape a `Plus`
    # can be (an X with a constant on it) and would refuse this one.
    if (
        isinstance(node.amount, ast.Plus)
        and isinstance(node.amount.right, ast.Times)
        and isinstance(node.amount.right.of, ast.AdditionalCostPaidCount)
    ):
        base = _amount_payload(node.amount.left)
        if not isinstance(base, int):
            raise LoweringError(
                "a payment-scaled life gain starts from a printed number",
                node=node,
            )
        if node.player.kind != "you" or node.capped_by or node.per_each is not None:
            # "You" is the only gainer any card prints this on, and a cap or a
            # second multiplier on top would be arithmetic the handler does not
            # do — refused rather than dropped, which is the direction that
            # gains less than the card says instead of more.
            raise LoweringError(
                "a payment-scaled life gain is the caster's own, uncapped",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": base,
                    "recipient": "caster",
                    "plus_per_cost_paid": {
                        "cost": optional_cost_key(node.amount.right.of.symbols),
                        "each": node.amount.right.factor,
                    },
                },
            ),
        )
    offset = x_offset_amount(node.amount)
    payload: dict[str, object] = {
        "amount": offset if offset is not None else _amount_payload(node.amount),
        "recipient": recipient,
    }
    # "…for each creature you control with flying" (Aven Gagglemaster): a
    # battlefield count of the gainer's own permanents. The honoured fields are
    # exactly what the handler tests; anything else refuses rather than being
    # dropped into a larger gain.
    if isinstance(node.per_each, ast.DiedThisTurn):
        # "…for each creature that died this turn" (Canopy Stalker). A tally,
        # not a scan: the creatures counted are precisely the ones no longer on
        # a battlefield, so there is nothing to filter and the count comes off
        # the game's own record. Game-wide, because the card says "each
        # creature" and not "each creature you control" — the per-seat tally is
        # a different number and answers a different card.
        if node.player.kind != "you":
            raise LoweringError(
                "the per-each life gain is the effect's own controller", node=node
            )
        leftover = _restrictions_beyond(node.per_each.filter, frozenset({"card_types"}))
        if leftover or node.per_each.filter.card_types != ("creature",):
            raise LoweringError(
                "the death tally counts creatures and nothing narrower", node=node
            )
        payload["per_each"] = {"history": "creatures_died_this_turn"}
        return (OracleInstruction("target_gains_life", "", payload),)
    if isinstance(node.per_each, ast.CountersOnSource):
        # "You gain 1 life **for each credit counter on this creature**."
        # (Icatian Moneychanger.) A count of the ability's own source, not of a
        # set of objects — so the payload names the counter word and the
        # handler names the reader, exactly as `deal_damage`'s
        # `amount_from_named_counters` does for the same phrase one family
        # over. The counter word is payload the whole way down, so a card
        # printing any other kind needs nothing here.
        if node.player.kind != "you":
            raise LoweringError(
                "a gain counted off the source's counters is the ability's own "
                "controller's",
                node=node,
            )
        payload["per_each"] = {"counters_on_source": node.per_each.kind}
        return (OracleInstruction("target_gains_life", "", payload),)
    if node.per_each is not None:
        filt = node.per_each
        zone_owner = filt.zone_owner.kind if filt.zone_owner is not None else None
        if node.player.kind == "you" and filt.zone == "graveyard" and (
            zone_owner == "target_opponent"
        ):
            # "For each artifact or creature card in target opponent's
            # graveyard, … you gain 1 life." (Spoils of Evil.) A count out of a
            # chosen player's graveyard, evaluated by `count_from_payload` —
            # the same reader the mana half of this very sentence uses one
            # instruction over, because the two halves are one count and two
            # readings of it are two answers.
            #
            # Held to what a *card* can be asked: a card in a graveyard has no
            # computed characteristics at all (CR 613.1), which is what
            # `card_only_filter` says.
            carried = card_only_filter({
                key: value
                for key, value in filt.to_payload().items()
                if key not in ("zone", "zone_owner", "is_card")
            })
            if carried is None:
                raise LoweringError(
                    "the per-each life gain cannot count this restriction", node=node
                )
            payload["per_each"] = {
                "zone": "graveyard", "owner": "target_opponent", "filter": carried,
            }
            return (OracleInstruction("target_gains_life", "", payload),)
        if node.player.kind != "you" or filt.zone != "battlefield":
            raise LoweringError(
                "the per-each life gain counts the gainer's own battlefield", node=node
            )
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "controller", "with_keywords"})
        )
        if leftover:
            raise LoweringError(
                "the per-each life gain cannot count this restriction: "
                + ", ".join(leftover),
                node=node,
            )
        payload["per_each"] = {
            "zone": "battlefield",
            "controller": filt.controller or "you",
            "card_types": list(filt.card_types),
            "with_keywords": list(filt.with_keywords),
        }
        return (OracleInstruction("target_gains_life", "", payload),)
    _describe_targets(payload, node.player)
    return (OracleInstruction("target_gains_life", "", payload),)


def _lower_extra_turn(node: ast.ExtraTurn) -> tuple[OracleInstruction, ...]:
    """"Take an extra turn after this one." (Time Walk) / "Take two extra
    turns after this one." (Teferi, Master of Time.)

    ``grant_extra_turn`` queues the turns for the effect's *controller*; it
    takes no player argument. A card handing the extra turn to someone else is
    a different effect, so it is refused rather than lowered onto a handler
    that would give the turn to the wrong player. The count rides in the
    payload only when it is not 1, keeping the single-turn payload byte-equal
    with what the pool has always compiled to.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler for {node.player.kind!r} taking an extra turn", node=node
        )
    payload: dict[str, object] = {}
    if node.count != 1:
        payload["count"] = node.count
    return (OracleInstruction("grant_extra_turn", "", payload),)


# Who a "loses the game" sentence names, and the handler that makes that player
# lose. `player_loses_game` and `target_player_loses_game` are the *same*
# function (engine/handlers/life_and_game.py registers both names) and it picks
# the loser off the kind, so the two are not interchangeable: emitting the
# targeted kind for "you lose the game" would kill whoever the spell happened to
# point at.
_LOSE_GAME_KINDS = {
    "you": "player_loses_game",
    "target_player": "target_player_loses_game",
    "target_opponent": "target_player_loses_game",
    # "If you win the flip, **that player** loses the game." (Amulet of Quoz.)
    # The seat the sentence in front of it named, which is the same
    # ``context.target`` the two rows above resolve to — ``player_loses_game``
    # reads that one field, so this is a third spelling of the row rather than
    # a fourth answer.
    "that_player": "target_player_loses_game",
}


def _lower_lose_game(node: ast.LoseGame) -> tuple[OracleInstruction, ...]:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    kind = _LOSE_GAME_KINDS.get(node.player.kind)
    if kind is None:
        raise LoweringError(
            f"no handler makes {node.player.kind!r} lose the game", node=node
        )
    return (OracleInstruction(kind, "", {}),)


def _lower_win_game(node: ast.WinGame) -> tuple[OracleInstruction, ...]:
    """"You win the game." (CR 104.2b.)

    ``player_wins_game`` wins for the effect's *controller* — it marks every
    other player as having lost (104.2a) and takes no player argument. A card
    handing the win to someone else is refused rather than lowered onto a
    handler that would win it for the wrong seat.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler makes {node.player.kind!r} win the game", node=node
        )
    return (OracleInstruction("player_wins_game", "", {}),)


#: The recipients "loses <a fraction of> their life" has one answer per seat
#: for. A count taken against one of them and applied to all of them is the
#: dropped-rider bug with an arithmetic face, so the fraction travels on the
#: per-recipient channel for these and on the ordinary one for the rest.
_PER_SEAT_LIFE_RECIPIENTS = frozenset({"each_player", "each_opponent"})


def _lower_lose_life(
    node: ast.LoseLife,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    # "Whenever you gain life, target opponent loses **that much** life."
    # (Vito, Thorn of the Dusk Rose.) The number is the life-gain event's, not
    # anything this effect computed, so it arrives as a trigger-context key
    # rather than as an amount. Resolved before the payload is built, because
    # an amount and a back-reference are alternatives — carrying both would let
    # a handler read whichever it happened to check first.
    # "…and loses **half their life**" (Peer into the Abyss): a number the
    # resolution computes, travelling on the same spec a counted amount does.
    halved = (
        halved_count_spec(node.amount, node)
        if isinstance(node.amount, ast.Half)
        else None
    )
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
        return (OracleInstruction("target_loses_life", "", payload),)
    # "**That player**" after an event that was *about an object*: the object's
    # controller. Massacre Wurm's dead creature is in a graveyard by the time
    # the trigger resolves and Gloom Sower's blocker may have left combat, so
    # neither seat survives a board read — the fire site freezes it (CR 603.10),
    # exactly as Basri's Lieutenant's counter clause and Conclave Mentor's power
    # are frozen. Which events carry a subject is a table rather than a rule,
    # for the reason `_EVENT_QUANTITIES` is: an event either had one or it did
    # not. Anywhere else "that player" is the ordinary chosen target below.
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
    # The same table and the same key the offer above it (line 108) already
    # reads for the same printed word, which is what makes the miss visible
    # in hindsight — one module, one phrase, two answers.
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        payload["recipient"] = EVENT_SUBJECT_PLAYER
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind in ("target_player", "target_opponent", "that_player"):
        return (OracleInstruction("target_loses_life", "", payload),)
    # "Destroy target creature. Its controller loses 2 life." (Liliana, Death
    # Mage's −3.) The controller of the previous step's target — recorded by
    # the destroy handler in the resolution scratchpad, because by the time
    # this instruction runs the permanent is gone (CR 608.2h, last-known
    # information).
    if node.player.kind == "controller":
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


_ANTE_RECIPIENTS: dict[str, str] = {
    "you": "caster",
    "each_player": "each_player",
    "that_player": "that_player",
}


def _player_recipient(player: ast.PlayerRef, node) -> str:
    recipient = _ANTE_RECIPIENTS.get(player.kind)
    if recipient is None:
        raise LoweringError(
            f"no seat is named by {player.kind!r} here", node=node
        )
    return recipient


def _lower_ante(node: ast.Ante) -> tuple[OracleInstruction, ...]:
    """"Ante the top card of your library." (CR 407.)

    One instruction for both printed shapes; who antes is payload. Demonic
    Attorney's every-seat sweep and Rebirth's per-seat offer differ only in the
    recipient key, which is exactly the difference the card prints.
    """
    return (
        OracleInstruction(
            "ante_top_card", "", {"players": _player_recipient(node.player, node)}
        ),
    )


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
    return (
        OracleInstruction(
            "exchange_life_totals", "", {"recipient": "target"}
        ),
    )


def _lower_set_life_total(node: ast.SetLifeTotal) -> tuple[OracleInstruction, ...]:
    """"That player's life total becomes 20." (Rebirth.)

    CR 119.5 makes this a gain or a loss of the difference, so the handler works
    out the direction; the payload carries the printed *result*, which is all
    the card says.
    """
    return (
        OracleInstruction(
            "set_life_total", "",
            {
                "recipient": _player_recipient(node.player, node),
                "amount": _amount_payload(node.amount),
            },
        ),
    )


# ---------------------------------------------------------------------------
# A round of offers, repeated
# ---------------------------------------------------------------------------


def _lower_repeat_process(node: ast.RepeatProcess, lower) -> tuple[OracleInstruction, ...]:
    """"Starting with you, each player may put a permanent card from their hand
    onto the battlefield. Repeat this process until no one puts a card onto the
    battlefield." (Eureka.)

    The offer and the repetition are one instruction, because the repetition is
    a property of the round rather than a step after it: what ends the loop is a
    whole round nobody took, which only the thing running the round can see.

    *lower* is the statement lowering, handed in rather than imported — this
    module sits below the dispatcher that owns it (see ``engine/ARCHITECTURE.md``
    on taking the recursion back as a parameter).

    Everything about the offer is checked rather than assumed. A cost, an
    if-you-do branch or a decline branch would each be a printed clause this
    instruction has nowhere to put; an act outside ``REPEATABLE_OFFERS`` has no
    record saying whether a seat took it, so the loop could not end on anything
    but its first round.
    """
    from ...repeated_offers import REPEATABLE_OFFERS

    offer = node.round
    if not isinstance(offer, ast.May) or offer.action is None:
        raise LoweringError("'repeat this process' repeats an offer", node=node)
    if offer.cost is not None or offer.then or offer.otherwise or offer.reflexive:
        raise LoweringError(
            "no handler repeats an offer carrying branches of its own", node=node
        )
    if offer.actor.kind != "each_player":
        raise LoweringError(
            "a repeated round is offered to every seat", node=node
        )
    steps = lower(offer.action, frozenset(), whole_effect=False)
    if len(steps) != 1:
        raise LoweringError("no handler repeats more than one act per seat", node=node)
    step = steps[0]
    if step.kind not in REPEATABLE_OFFERS:
        raise LoweringError(
            f"{step.kind!r} records nothing about whether a seat took it, so a "
            "round of it could never be the last one",
            node=node,
        )
    return (
        OracleInstruction(
            "repeat_offer_round", "",
            {
                "actor": offer.actor.kind,
                # "Starting with you" — CR 101.4's default is the active player,
                # and this says the seat that put the effect on the stack. The
                # same seat for a sorcery, not the same rule.
                "offer_order": offer.starting_with.kind if offer.starting_with else None,
                "action": (
                    OracleInstruction(
                        step.kind, step.value, {**step.payload, "optional": True}
                    ),
                ),
            },
        ),
    )


def _lower_pay_life(node: ast.PayLife) -> tuple[OracleInstruction, ...]:
    """"Pay 4 life." (Sylvan Library.) CR 118.8.

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


# ---------------------------------------------------------------------------
# Damage whose shape is a whole-game process rather than an event
# ---------------------------------------------------------------------------
#
# Two sentences that print the word "damage" and share nothing with the damage
# family's vocabulary: neither reads a recipient noun phrase, a duration or a
# rider. Mana Clash is an *unbounded repeat* (CR 705) whose rounds are the
# effect, and The Fallen's recipients are a ledger kept for the whole game
# rather than a set any board can be asked for. They came here the round
# ``lowering/damage.py`` went back over the thousand-line guard, on the line
# this module is already cut on: the game and its players, rather than one
# event on the board.

#: The recipient classes the history handler resolves. "player" and "creature"
#: parse — the phrase reads the same on any of them — and refuse here, because
#: the record holds seats and permanent ids and nothing has been written that
#: turns those into a living creature or a non-opponent seat. A class admitted
#: without a resolver would name nobody and deal nothing, on a card reporting
#: itself supported.
_HISTORY_RECIPIENTS = frozenset({"opponent", "planeswalker"})


def _lower_coin_flip_stakes_loop(
    node: ast.CoinFlipStakesLoop,
) -> tuple[OracleInstruction, ...]:
    """Game of Chaos's whole paragraph as one instruction.

    Not composed out of ``flip_coin`` and two conditionals, which is how Bottle
    of Suleiman's two branches are built: those branches are the end of the
    effect, and these two each end in an *offer to run the paragraph again* —
    made to a different player depending on which branch ran, at a stake the
    round after it doubles. Nothing in the composed shape can carry either
    fact, and a lowering that dropped them would compile a card that flips once
    for one life.

    The stake must be a printed number: it is doubled by the round behind it, so
    an announced X would be a quantity resolved once and then scaled by a
    handler that never saw the announcement.
    """
    if not isinstance(node.stake, ast.Fixed):
        raise LoweringError("a doubling stake is a printed number", node=node)
    return (
        OracleInstruction(
            "coin_flip_stakes_loop", "",
            {
                "stake": int(node.stake.value),
                "doubling": bool(node.doubling),
                # "…and **target opponent** loses N life". The production reads
                # those two words as fixed text, so the target was consumed and
                # then dropped: the handler asks ``context.target`` for the seat
                # it stakes against, and nothing described the choice, so the
                # picker never ran and a free-for-all staked whichever opponent
                # the resolution happened to carry. One target, chosen at
                # announcement (CR 601.2c), described here the way every other
                # target is.
                "targets": {
                    "quantifier": "target", "kind": "player",
                    "opponents_only": True,
                },
            },
        ),
    )


def _lower_coin_flip_damage_loop(
    node: ast.CoinFlipDamageLoop,
) -> tuple[OracleInstruction, ...]:
    """Mana Clash's whole paragraph (CR 705).

    One instruction, because the loop is the effect: a flip, a reading of both
    coins, and a repeat that depends on both. Composed out of `flip_coin` and
    `if_then` it would be a *fixed* number of rounds, since nothing in the
    control-flow vocabulary repeats — and the printed sentence is unbounded.

    Only the amount is payload; who flips and which face is punished are the
    process itself.
    """
    return (
        OracleInstruction(
            "coin_flip_damage_loop", "",
            {
                "amount": _amount_payload(node.amount),
                # The opponent is chosen when the spell is cast (CR 601.2c), so
                # the picker has to be raised from the compiled program like any
                # other target.
                "targets": {
                    "quantifier": "target", "kind": "player", "opponents_only": True,
                },
            },
        ),
    )


def _lower_damage_this_game_history(
    node: ast.DamageThoseDamagedThisGame,
) -> tuple[OracleInstruction, ...]:
    """"…deals 1 damage to each opponent and planeswalker it has dealt damage to
    this game." (The Fallen.)

    The recipients are a record on the source, not a set on any board, so the
    payload carries only how much and which classes of the record to reach for.
    """
    unknown = sorted(set(node.classes) - _HISTORY_RECIPIENTS)
    if unknown:
        raise LoweringError(
            "no handler reaches the damaged-this-game " + ", ".join(unknown),
            node=node,
        )
    return (
        OracleInstruction(
            "deal_damage_to_those_damaged_this_game", "",
            {"amount": _amount_payload(node.amount), "classes": list(node.classes)},
        ),
    )


def _lower_count_objects(node: ast.CountObjects) -> tuple[OracleInstruction, ...]:
    """"Count the number of permanents." (Chaos Moon.)

    Nothing happens on any board: the whole of what the step does is write
    CR 107.1's number into the resolution scratchpad under
    ``COUNTED_NUMBER``, which ``_records._PRODUCES`` declares and the
    "if the number is odd" condition behind it reads. The same shape
    ``flip_coin`` and ``choose_player_who_cast`` have, and for their reason —
    what the value is *for* is the next sentence, not this one.

    What is counted travels as a filter payload, so a card counting something
    narrower than the whole board is this production with a different noun
    phrase. It is held to what ``subject_matches`` can test, for the reason
    every filter in this engine is: a restriction the matcher drops is a count
    over strictly more objects than the card names, and the number it produces
    then decides a branch.
    """
    from ...subject_filters import untestable_filter_keys

    described = _filter_payload(node.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a count cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction(
            "count_objects", "", {"filter": described, "result_key": COUNTED_NUMBER}
        ),
    )


def _lower_skip_step(node: "ast.SkipStep") -> tuple[OracleInstruction, ...]:
    """"You skip your next draw step." (Ivory Gargoyle.)

    The seat is on the payload, not implied: ``Game.skip_next_step`` is keyed by
    step name and a skip with no seat is consumed by whichever player's step
    comes round first (CR 500.7 — the step belongs to a turn, and a turn belongs
    to a player).

    Only "you" today. Every other player reference the grammar can read names a
    seat this instruction would have to resolve at *resolution* rather than at
    lowering, and no card in the pool prints one — so it refuses by name rather
    than silently skipping the controller's step.
    """
    who = getattr(node.subject, "kind", None)
    if who != "you":
        raise LoweringError(
            f"no handler skips a step for {who!r}", node=node
        )
    return (
        OracleInstruction(
            "skip_next_step", "",
            {"step": node.step, "seat": "you", "count": int(node.count)},
        ),
    )
