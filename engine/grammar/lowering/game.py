"""Lowering tokens, life, and whole-game effects.

Token creation (paired with the generic `create_token` instruction kind, so a
token-making card is a production plus a lowering and never a bespoke handler),
life gain and loss, extra turns, and winning or losing the game.

Grouped as "the game and its players" rather than "the board": none of these
changes what a permanent is, and all of them change the state a player is in.
"""

from ...oracle_types import OracleInstruction, X_FROM_COUNT
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ...tokens import default_token_name
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _back_reference_payload,
    count_spec,
    halved_count_spec,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
)


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------


def _lower_gain_life(
    node: ast.GainLife,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    recipient = "caster" if node.player.kind == "you" else "target"
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
    ):
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from_trigger": "dead_power", "recipient": "caster"},
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
    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount), "recipient": recipient,
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
    if node.per_each is not None:
        filt = node.per_each
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


def _title(words: str) -> str:
    """Title-case a lexed vocabulary word, preserving multiword entries."""
    return " ".join(part.capitalize() for part in words.split())


def _lower_create_copy_token(
    node: ast.CreateCopyToken,
) -> tuple[OracleInstruction, ...]:
    """"Create a token that's a copy of target creature you control."
    (Sublime Epiphany.)

    The filter is carried, not collapsed: "**you control**" is half the card,
    and a copy token made from an opponent's creature is a different and much
    better spell. Checked against what the resolver can test, the same gate
    every targeted effect goes through — a phrase the matcher cannot answer
    would be a restriction the handler silently ignores.
    """
    if node.subject.quantifier != "target":
        raise LoweringError("the copy token copies a chosen permanent", node=node)
    payload: dict[str, object] = {"count": _amount_payload(node.count)}
    described = _filter_payload(node.subject.filter)
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if leftover:
        raise LoweringError(
            "the copy token cannot test this restriction: " + ", ".join(sorted(leftover)),
            node=node,
        )
    if described:
        payload["filter"] = described
    _describe_targets(payload, node.subject)
    return (OracleInstruction("create_copy_token", "", payload),)


def _lower_create_token(
    node: ast.CreateToken, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Create a 1/1 colorless Insect artifact creature token with flying named
    Wasp." (The Hive.)

    ``create_token`` builds the token's ``CardDefinition`` from the payload
    (engine/tokens.py), so this is pure characteristic transcription: the type
    line is re-rendered in the order the card printed it, and each optional key
    is emitted only when the card states it — matching the legacy rule, whose
    Hive payload carries no ``colors`` entry for a colourless token and no
    ``count`` for a single one.

    An unnamed token takes its CR 111.4 name — its subtype(s) plus the word
    "Token" ("Dwarf Berserker Token") — through ``default_token_name``, the
    one naming rule every token maker shares. Two shapes still refuse rather
    than guess:

    * **A token with neither a printed name nor a subtype.** CR 111.4 has
      nothing to build a name from.
    * **A token with no creature type at all.** ``make_token_card`` always
      builds a creature card, and a type line with no card types would come out
      as a bare subtype the loader could not classify.
    """
    # A *predefined* token (CR 111.10) is named, typed and worded by the table
    # in `engine/tokens.py`, so it needs none of the transcription below — and
    # it has no P/T, which every check below assumes.
    if node.oracle_text is not None:
        payload: dict[str, object] = {
            "name": node.name,
            "type_line": (
                " ".join(_title(w) for w in node.types)
                + (" — " + " ".join(_title(w) for w in node.subtypes) if node.subtypes else "")
            ),
            "oracle_text": node.oracle_text,
        }
        if node.colors:
            payload["colors"] = node.colors
        _stamp_token_count(payload, node)
        return (OracleInstruction("create_token", "", payload),)
    if "creature" not in node.types:
        raise LoweringError("make_token_card only builds creature tokens", node=node)
    if node.counted_pt is None and (node.power is None or node.toughness is None):
        raise LoweringError("a creature token has a printed power/toughness", node=node)
    if node.name:
        name = _title(node.name)
    elif node.subtypes:
        name = default_token_name(node.subtypes)
    else:
        raise LoweringError(
            "a token with neither a printed name nor a subtype has no CR 111.4 "
            "name to take",
            node=node,
        )

    type_line = " ".join(_title(word) for word in node.types)
    if node.subtypes:
        type_line += " — " + " ".join(_title(word) for word in node.subtypes)

    payload: dict[str, object] = {
        "name": name,
        # "Create an **X/X** … token, where X is the number of …" (Experimental
        # Overload). The where-clause wrapping this sentence stamps the count
        # onto the instruction and the executor resolves it into the context's
        # X before the handler runs — so the payload says "x" and the handler
        # reads a number, exactly as a pump or a counted damage does. Both
        # halves, because the production admitted them only as the *same*
        # variable.
        "power": "x" if node.counted_pt is not None else node.power,
        "toughness": "x" if node.counted_pt is not None else node.toughness,
        "type_line": type_line,
    }
    if node.colors:
        payload["colors"] = node.colors
    if node.keywords:
        payload["keywords"] = tuple(_title(word) for word in node.keywords)
    # Printed abilities in quotes. Gated on the compiler being able to read
    # them: a token carrying an ability nothing implements is a token that
    # silently lacks it, which is exactly the shape the support gate exists to
    # refuse — and it is refused *here*, so the whole card reports unsupported
    # rather than the token arriving half-built.
    if node.granted_lines:
        from ...tokens import token_line_supported

        for line in node.granted_lines:
            if not token_line_supported(line):
                raise LoweringError(
                    f"nothing implements the token's ability {line!r}", node=node
                )
        payload["oracle_text"] = chr(10).join(node.granted_lines)
    if node.recipient_players:
        payload["recipient_players"] = node.recipient_players
    count = _stamp_token_count(payload, node)
    # "…that are tapped and attacking" (Basri Ket): entry state the handler
    # stamps as the tokens arrive.
    if node.tapped:
        payload["tapped"] = True
    if node.attacking:
        payload["attacking"] = True
    if node.recipient is not None:
        # "Its controller creates …" (Angelic Ascension, Secure the Scene):
        # the token goes to the controller the exile step of this same effect
        # recorded — so that step must exist, exactly as "that much" demands
        # its damage producer.
        if node.recipient not in produced:
            raise LoweringError(
                "back-reference to the exiled permanent's controller with no "
                "exile in this effect",
                node=node,
            )
        payload["recipient"] = node.recipient
    return (OracleInstruction("create_token", "", payload),)


def _lower_create_emblem(node: ast.CreateEmblem) -> tuple[OracleInstruction, ...]:
    """"You get an emblem with "<ability>"." (CR 114.2.) The text is the whole
    payload; the compiler's planeswalker gate has already verified it reads as
    a supported triggered ability before any card carrying it can compile."""
    return (OracleInstruction("create_emblem", "", {"text": node.text}),)


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


# Trigger events after which "that player" names the controller of the object
# the event was about, frozen into the trigger's context by the fire site.
_EVENT_SUBJECT_CONTROLLERS: frozenset[str] = frozenset({
    "creature_opponent_controls_dies",   # Massacre Wurm — the dead creature's
    "creature_becomes_blocked",          # Gloom Sower — the blocker's
})


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
        payload: dict[str, object] = {"amount": "x", X_FROM_COUNT: halved}
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
    raise LoweringError(f"unsupported life-loss target {node.player.kind!r}", node=node)


def _stamp_token_count(payload: dict, node: "ast.CreateToken"):
    """Record how many tokens to make, and return it.

    Three shapes, and they are three because the *number* comes from three
    different places: a printed count, the firing event's own tally, and a
    history of what died. Shared between the predefined and transcribed token
    branches so a count added to one is a count the other gets too.
    """
    if isinstance(node.per_death, ast.DiedThisTurn):
        # "…for each nontoken creature that died this turn" (Gadrak). A tally
        # rather than a scan: the creatures counted are exactly the ones no
        # battlefield still holds. Which tally is decided by the phrase — the
        # engine keeps a nontoken one beside the game-wide one, because a token
        # dying is a real creature death and a *different* number.
        filt = node.per_death.filter
        leftover = _restrictions_beyond(filt, frozenset({"card_types", "nontoken"}))
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the death tally counts creatures and nothing narrower", node=node
            )
        history = (
            "nontoken_creatures_died_this_turn" if filt.nontoken
            else "creatures_died_this_turn"
        )
        if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
            raise LoweringError(
                "a per-death token count multiplies one token, not several",
                node=node,
            )
        payload["count"] = {"history": history}
        return payload["count"]
    if isinstance(node.count, ast.ThatMuch):
        # "create that many … tokens" — the count is the firing event's own
        # number (a delayed attack trigger's matching attackers), recorded by
        # the firing site in the resolution scratchpad.
        payload["count"] = "trigger_count"
        return "trigger_count"
    count = _amount_payload(node.count)
    if count != 1:
        payload["count"] = count
    return count
