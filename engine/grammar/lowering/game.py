"""Lowering tokens, life, and whole-game effects.

Token creation (paired with the generic `create_token` instruction kind, so a
token-making card is a production plus a lowering and never a bespoke handler),
life gain and loss, extra turns, and winning or losing the game.

Grouped as "the game and its players" rather than "the board": none of these
changes what a permanent is, and all of them change the state a player is in.
"""

from ...oracle_types import OracleInstruction
from ...tokens import default_token_name
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _describe_targets,
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
                {"amount_from": "dead_power", "recipient": "caster"},
            ),
        )
    if isinstance(node.amount, ast.ThatMuch):
        # "You gain life equal to the damage dealt" — reads the value the
        # preceding damage instruction recorded in the resolution scratchpad,
        # which is what lets the two effects be separate instructions at all.
        #
        # That only holds when the producer is in *this* resolution. On a
        # triggered ability ("Whenever this creature deals damage, you gain that
        # much life") the amount comes from the trigger's captured event, which
        # is a different mechanism — so refuse rather than read an empty
        # scratchpad and silently gain 0 life.
        if node.amount.source not in produced:
            raise LoweringError(
                f"back-reference to {node.amount.source!r} with no producer in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from": node.amount.source, "recipient": recipient},
            ),
        )
    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount), "recipient": recipient,
    }
    # "…for each creature you control with flying" (Aven Gagglemaster): a
    # battlefield count of the gainer's own permanents. The honoured fields are
    # exactly what the handler tests; anything else refuses rather than being
    # dropped into a larger gain.
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
    if "creature" not in node.types:
        raise LoweringError("make_token_card only builds creature tokens", node=node)
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
        "power": node.power,
        "toughness": node.toughness,
        "type_line": type_line,
    }
    if node.colors:
        payload["colors"] = node.colors
    if node.keywords:
        payload["keywords"] = tuple(_title(word) for word in node.keywords)
    if isinstance(node.count, ast.ThatMuch):
        # "create that many … tokens" — the count is the firing event's own
        # number (a delayed attack trigger's matching attackers), recorded by
        # the firing site in the resolution scratchpad.
        payload["count"] = "trigger_count"
        count = "trigger_count"
    else:
        count = _amount_payload(node.count)
        if count != 1:
            payload["count"] = count
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


def _lower_lose_life(node: ast.LoseLife) -> tuple[OracleInstruction, ...]:
    payload: dict[str, object] = {"amount": _amount_payload(node.amount)}
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
