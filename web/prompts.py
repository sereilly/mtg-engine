"""Rendering, gating and auto-answering the prompts a seat owes.

``engine/pending_choices.py`` is the registry: one :class:`ChoiceSpec` per kind
of interactive decision, saying how it is answered, what a non-interactive seat
does instead, which action answers it and what message refuses everything else.
This module is the web half — one renderer per kind, and the three loops that
used to be three hand-written cascades in ``app.py``, one branch per prompt:

* :func:`render_prompts`     — the payload the board UI reads, per viewer
* :func:`blocking_prompt`    — the prompt that refuses an action, if any
* :func:`auto_resolve_ai_prompts` — every AI-owned prompt takes its default

Those three plus the registry's ``resolve``/``default`` are the five parts a
prompt needs. They used to be five unrelated edits; a prompt with any of them
missing looked fine until it was played (Primal Clay shipped with three
missing). ``tests/engine/test_pending_choices.py`` now fails if a kind is
registered with no renderer, or armed with no spec.

Renderers take the *list* of that kind's currently visible choices, because a
seat can owe several of the same prompt at once (the colour rods) and the board
shows them as one panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.grammar.phrases import BASIC_LAND_WORDS
from engine.grammar.vocabulary import CREATURE_TYPES, LAND_TYPES
from engine.mana_payment import mana_cost_label
from engine.pending_choices import CHOICE_SPECS, public_data
from engine.search_filters import search_matches, searched_seat


@dataclass(frozen=True)
class PromptContext:
    """What a renderer is allowed to reach for.

    Passed in rather than imported so this module has no cycle back into
    ``app.py``, and so what the presentation layer depends on stays visible.
    """

    game: Any
    viewer_seat: int | None
    serialize_card: Callable[[Any], dict]
    seat_type: Callable[[int], str]


Renderer = Callable[[PromptContext, list], "dict | None"]

PROMPT_RENDERERS: dict[str, Renderer] = {}


def prompt_renderer(kind: str) -> Callable[[Renderer], Renderer]:
    """Register the renderer for one kind of prompt.

    The kind must already be registered in the engine — a renderer for a prompt
    nothing arms is dead code that reads like coverage.
    """

    def decorator(fn: Renderer) -> Renderer:
        if kind not in CHOICE_SPECS:
            raise ValueError(f"no pending choice registered for prompt {kind!r}")
        if kind in PROMPT_RENDERERS:
            raise ValueError(f"prompt {kind!r} already rendered by {PROMPT_RENDERERS[kind].__name__}")
        PROMPT_RENDERERS[kind] = fn
        return fn

    return decorator


# ---------------------------------------------------------------------------
# The three loops
# ---------------------------------------------------------------------------

def visible_choices(ctx: PromptContext, spec) -> list:
    """The choices of *spec*'s kind this viewer may see.

    A prompt belongs to the seat that owes it. A seatless viewer (a spectator,
    or the single-payload API) sees only the kinds marked ``spectator_visible``,
    and an AI seat's prompt is hidden unless the kind says otherwise — the AI
    answers it itself, so showing it would be a prompt nobody can act on.
    """
    out = []
    for kind_spec, choice in ctx.game.iter_pending_prompts():
        if kind_spec is not spec:
            continue
        if ctx.viewer_seat is None:
            if not spec.spectator_visible:
                continue
        elif ctx.viewer_seat != choice.player_index:
            continue
        if spec.hidden_for_ai and ctx.seat_type(choice.player_index) == "ai":
            continue
        if not spec.open_for(ctx.game, choice):
            continue
        out.append(choice)
    return out


def render_prompts(ctx: PromptContext) -> dict:
    """``{prompt_key: payload or None}`` for every registered kind.

    Every key is always present, so the board UI never has to tell "no prompt"
    from "this build doesn't know that prompt".
    """
    payloads: dict[str, dict | None] = {}
    for kind, spec in CHOICE_SPECS.items():
        choices = visible_choices(ctx, spec)
        renderer = PROMPT_RENDERERS.get(kind)
        payloads[spec.prompt_key] = renderer(ctx, choices) if (choices and renderer) else None
    return payloads


def blocking_prompt(game, seat: int, action: str, exempt_actions: frozenset[str]) -> tuple[Any, Any] | None:
    """The first prompt that refuses *action* from *seat*, as ``(spec, choice)``.

    A kind with no ``blocked_detail`` never refuses anything: it is a
    notification, or a decision the rest of the game can carry on around.
    """
    for spec, choice in game.iter_pending_prompts():
        if spec.blocked_detail is None:
            continue
        if not spec.blocks_every_seat and choice.player_index != seat:
            continue
        if not spec.open_for(game, choice):
            continue
        if action in exempt_actions or action == spec.action or action in spec.also_answers:
            continue
        return spec, choice
    return None


def auto_resolve_ai_prompts(game, seat_type: Callable[[int], str]) -> None:
    """Take the default on every prompt owed by an AI seat.

    Generic over the queue, so a new prompt is covered the moment it is
    registered. That matters more than it sounds: a prompt with no auto-answer
    does not misbehave, it *stalls the game forever* on an AI seat, and only in
    a session where that card happens to be drawn.
    """
    # Answering one prompt can arm the next (a search that finds a card that
    # discards), so drain until nothing AI-owned is left. The bound is a
    # backstop against a default that fails to clear its own prompt.
    for _ in range(100):
        target = next(
            (
                choice
                for _spec, choice in game.iter_pending_prompts()
                if seat_type(choice.player_index) == "ai"
            ),
            None,
        )
        if target is None:
            return
        game.auto_resolve_choice(target)


# ---------------------------------------------------------------------------
# Renderers, one per kind
# ---------------------------------------------------------------------------

@prompt_renderer("effect_order")
def _effect_order(ctx: PromptContext, choices: list) -> dict:
    """CR 616.1e: which of the effects attempting to modify one event applies
    first. The options are labelled with the effects themselves, in the order
    the engine would take by default, so the first option is "whatever would
    have happened anyway"."""
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "event_kind": choice.data["event_kind"],
        "options": list(choice.data["options"]),
    }


@prompt_renderer("search_library")
def _search_library(ctx: PromptContext, choices: list) -> dict:
    """The cards the search may look at, and which of them it may find.

    Additive on purpose: ``cards`` stays the caster's library in library order,
    so a client written before restrictions existed still renders. The
    restriction arrives beside it as the indices that satisfy it — the client
    greys out the rest — and the engine re-checks the answer regardless,
    because this payload is a hint and not a permission.
    """
    choice = choices[0]
    # The searched zone's owner, which is the chooser for every card but
    # Reincarnation — see `engine.search_filters.searched_seat`. Offering the
    # chooser's own graveyard there would show a picker full of cards the
    # engine then refuses.
    caster = ctx.game.players[searched_seat(choice.data, choice.player_index)]
    zones = tuple(choice.data.get("zones", ("library",)))
    destinations = list(choice.data.get("destinations") or ())
    payload = {
        "caster_seat": choice.player_index,
        "count": choice.data["count"],
        "card_type": choice.data["card_type"],
        "card_name": choice.data.get("card_name", ""),
        "zones": list(zones),
        # Where the find actually goes. The dialog wrote "into your hand" into
        # its own copy, so Sanctum of All — "…and put it onto the battlefield" —
        # offered an "Add to Hand" button for a card that was never going there,
        # and Fabled Passage's tapped land said nothing about being tapped. The
        # engine has known since the search was armed; this is it saying so.
        "destination": choice.data.get("destination", "hand"),
        "enters_tapped": bool(choice.data.get("enters_tapped")),
        # The library half, and *only* when the search was armed to look there.
        # A search of the graveyard alone (Recall's "return a card from your
        # graveyard to your hand") looks in a zone that is already public, and
        # sending the library beside it would put a hidden zone on screen with
        # every card in it marked legal — the engine refuses such a pick, so the
        # player would be shown a face-up library and a button that does
        # nothing. `zones` has said which zones since searches grew a second
        # one; this is the payload reading it.
        "cards": (
            [ctx.serialize_card(card) for card in caster.library]
            if "library" in zones else []
        ),
        "legal_indices": (
            [
                index for index, card in enumerate(caster.library)
                if search_matches(card, choice.data)
            ]
            if "library" in zones else []
        ),
    }
    # A counted search ("up to two basic land cards", Cultivate) is answered
    # whole: the client multi-selects up to `max_picks` and sends one pick
    # list. The printed slots ride along so the dialog can say where the finds
    # will go; which find fills which slot is the `search_destination` prompt.
    if len(destinations) > 1:
        payload["multi"] = True
        payload["max_picks"] = len(destinations)
        payload["destinations"] = destinations
        payload["tapped"] = list(choice.data.get("tapped") or ())
        payload["up_to"] = bool(choice.data.get("up_to"))
    if "graveyard" in zones:
        payload["graveyard_cards"] = [
            ctx.serialize_card(card) for card in caster.graveyard
        ]
        payload["legal_graveyard_indices"] = [
            index for index, card in enumerate(caster.graveyard)
            if search_matches(card, choice.data)
        ]
    return payload


@prompt_renderer("search_destination")
def _search_destination(ctx: PromptContext, choices: list) -> dict:
    """A counted search's "which found card goes where" (Cultivate): the found
    cards, already out of the searched zones and revealed if the card said to,
    and the printed slots each can fill. One slot per card, distinct — the
    engine re-checks the mapping."""
    choice = choices[0]
    return {
        "caster_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "cards": [
            ctx.serialize_card(card) for card in choice.data.get("_cards") or ()
        ],
        "slots": list(choice.data.get("slots") or ()),
    }


@prompt_renderer("look_top_pick")
def _look_top_pick(ctx: PromptContext, choices: list) -> dict:
    """See the Truth's pick: the looked-at top cards, keep one, the rest go to
    the bottom. Only the owner sees the card faces."""
    choice = choices[0]
    # Whose library is drawn, through the same reader the engine offers and
    # resolves with: Sealed Fate looks through the *opponent's* pile while the
    # caster answers, and a renderer reading the answering seat would show the
    # chooser their own library and then exile a card out of somebody else's.
    pile_seat = ctx.game.look_top_pile_index(choice)
    caster = ctx.game.players[pile_seat]
    top_count = min(int(choice.data.get("top_count", 0)), len(caster.library))
    return {
        "caster_seat": choice.player_index,
        "pile_seat": pile_seat,
        "top_count": top_count,
        "card_name": choice.data.get("card_name", ""),
        "cards": [ctx.serialize_card(card) for card in owner.library[:top_count]],
    }


@prompt_renderer("name_then_reveal_top")
def _name_then_reveal_top(ctx: PromptContext, choices: list) -> dict:
    """Petra Sphinx's "choose a card name".

    No suggestion list at all, and that is the rule rather than a gap: the
    chooser is guessing at the top of their **own** library, so a list built
    over what they can see would either be useless (their graveyard) or would
    hand them the answer (their library). CR 202.1 lets them name any card, and
    the engine accepts whatever they type.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "match_zone": choice.data.get("match_zone", "hand"),
        "miss_zone": choice.data.get("miss_zone", "graveyard"),
    }


@prompt_renderer("graveyard_pick_for_price")
def _graveyard_pick_for_price(ctx: PromptContext, choices: list) -> dict:
    """Forgotten Lore's "target opponent chooses a card in your graveyard".

    A graveyard is a public zone (CR 400.2), so the cards this offers are ones
    the chooser may already look at — the list is the whole zone minus the
    picks the loop has already made, which is exactly the printed exclusion.
    """
    choice = choices[0]
    owner_index = int(choice.data.get("owner_index", 0))
    graveyard = ctx.game.players[owner_index].graveyard
    legal = [i for i in (choice.data.get("legal_indices") or []) if i < len(graveyard)]
    return {
        "player_seat": choice.player_index,
        "owner_seat": owner_index,
        "card_name": choice.data.get("card_name", ""),
        "options": [
            {"index": index, "card": ctx.serialize_card(graveyard[index])}
            for index in legal
        ],
    }


@prompt_renderer("name_then_consult")
def _name_then_consult(ctx: PromptContext, choices: list) -> dict:
    """Demonic Consultation's "choose a card name".

    No suggestion list, for Petra Sphinx's reason turned around: the cards this
    will reveal are in the chooser's **own** library, and a list built over it
    would hand them the order they are betting against. How many cards the
    exile costs *is* shown — it is the printed number and the whole risk.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "exile_count": choice.data.get("exile_count", 0),
    }


@prompt_renderer("name_and_random_reveal")
def _name_and_random_reveal(ctx: PromptContext, choices: list) -> dict:
    """Nebuchadnezzar's "choose a card name".

    No suggestion list, for the reason Petra Sphinx's has none: the cards this
    will reveal are in the opponent's hand, which the chooser may not look at
    (CR 400.2), and a list drawn from anywhere else would be a list of the
    wrong cards. CR 202.1 lets them name any card and the engine accepts
    whatever they type.

    How many will be revealed *is* shown — it is the X they announced, and it
    is what makes the guess worth taking.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "target_seat": choice.data.get("target_seat"),
        "count": choice.data.get("count", 0),
        "zone": choice.data.get("zone", "hand"),
    }


# Zones whose contents every player may look at (CR 400.2): what a prompt may
# list to a seat other than the zone's owner.
_PUBLIC_ZONES = frozenset({"graveyard", "exile", "battlefield", "ante", "command_zone"})


@prompt_renderer("name_and_strip")
def _name_and_strip(ctx: PromptContext, choices: list) -> dict:
    """Necromentia's "choose a card name".

    The names offered are the ones in the searched player's **public** zones
    among the ones the card searches — the graveyard, for Necromentia. The card
    also searches the hand and the library, and the choice record lists those
    zones too (the search needs them), but the chooser is not entitled to see
    either, so they are never read here: a suggestion list built over the
    library is the opponent's decklist. For the same reason the record's
    ``default_name`` — the commonest card over every searched zone, which is
    the *AI's* stated policy — is not forwarded. The list is a convenience and
    never the rule: CR 202.1 lets a player name any card at all, the engine
    accepts a name outside the list, and only the printed basic-land
    restriction is enforced.
    """
    choice = choices[0]
    target = ctx.game.players[choice.data["target_seat"]]
    public_zones = [
        zone for zone in (choice.data.get("zones") or ())
        if zone in _PUBLIC_ZONES
    ]
    seen = sorted({
        card.name
        for zone in public_zones
        for card in getattr(target, zone, [])
        if "basic" not in (card.type_line or "").lower()
    })
    return {
        "caster_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "target_seat": choice.data["target_seat"],
        "suggestions": seen,
    }


@prompt_renderer("trigger_target")
def _trigger_target(ctx: PromptContext, choices: list) -> dict:
    """"…you may destroy target artifact defending player controls." (Floral
    Spuzzem.)

    CR 603.3d: a triggered ability chooses its targets as it is put on the
    stack, so the candidates were enumerated *then* and are replayed here. The
    same shape as the reflexive prompt below and for the same reason — an
    answer naming something the picker never offered is refused rather than
    quietly performed.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": [
            {
                "seat": target.get("seat"),
                "index": target.get("permanent_index"),
                "id": target.get("permanent_id"),
                "name": target.get("name"),
            }
            for target in choice.data.get("targets") or ()
        ],
    }


@prompt_renderer("reflexive_target")
def _reflexive_target(ctx: PromptContext, choices: list) -> dict:
    """"When you do, you may tap or untap target creature." (Tolarian Kraken.)

    CR 603.12: the payment created a *new* triggered ability, and this is that
    ability choosing its targets — which is why the candidates were enumerated
    when it was created and are replayed here rather than recomputed. A
    permanent that became legal since is not a legal answer; targets are chosen
    once.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": [
            {
                "seat": target.get("seat"),
                "index": target.get("permanent_index"),
                "id": target.get("permanent_id"),
                "name": target.get("name"),
            }
            for target in choice.data.get("targets") or ()
        ],
    }


@prompt_renderer("copy_spell_target")
def _copy_spell_target(ctx: PromptContext, choices: list) -> dict:
    """"…and may choose a new target for that copy." (Chain Lightning.)

    CR 707.10's offer, made to the copy's controller — who is not the player who
    cast the spell. The candidates were enumerated when the copy was created and
    are replayed here, players and permanents alike, because "any target" is
    both (CR 115.4).
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": [
            {
                "kind": target.get("kind"),
                "seat": target.get("seat"),
                "index": target.get("index"),
                "id": target.get("permanent_id"),
                "name": target.get("name"),
            }
            for target in choice.data.get("targets") or ()
        ],
    }


@prompt_renderer("tap_any_number")
def _tap_any_number(ctx: PromptContext, choices: list) -> dict:
    """"Tap any number of untapped creatures you control." (Siege Striker.)

    Only the seat's *own* creatures, and only ones the phrase still names — the
    engine offers the list through ``live_tap_any_number`` so the prompt and the
    re-check are one rule rather than two copies of it. There is no maximum to
    send: "any number" is bounded by the list itself, which is exactly why the
    quantifier is its own rather than an "up to" with a large count.

    The boost is reported so the player can see what the pick is worth per
    creature; the engine multiplies it by how many they name.
    """
    choice = choices[0]
    candidates = [
        {
            "seat": choice.player_index,
            "index": ctx.game.battlefield_index_of(perm),
            "id": ctx.game.permanent_id_of(perm),
            "name": perm.card.name,
        }
        for perm in ctx.game.live_tap_any_number(choice)
    ]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "power": choice.data.get("power", 0),
        "toughness": choice.data.get("toughness", 0),
        "candidates": candidates,
    }


@prompt_renderer("untap_up_to")
def _untap_up_to(ctx: PromptContext, choices: list) -> dict:
    """"Untap up to four lands." (Rewind): every matching permanent on every
    battlefield, by stable id, multi-select up to the amount. The engine
    re-validates each id, so the candidate list is a hint."""
    from engine.handlers._common import permanent_matches_filter

    from engine.subject_filters import subject_matches

    choice = choices[0]
    filt = dict(choice.data.get("filter") or {})
    observer = choice.data.get("observer")
    candidates = [
        {
            "seat": seat,
            "index": index,
            "id": ctx.game.permanent_id_of(perm),
            "name": perm.card.name,
            "tapped": perm.tapped,
        }
        for seat, player in enumerate(ctx.game.players)
        for index, perm in enumerate(player.battlefield)
        # The same question the engine re-asks when the answer comes back
        # (`_resolve_untap_up_to`), so the list offered and the list accepted
        # cannot disagree: "creatures without flying **they control**" narrows
        # by a keyword and by a seat, neither of which the pure matcher tests.
        if subject_matches(
            ctx.game, perm, filt,
            observer=observer if isinstance(observer, int) else choice.player_index,
        )
    ]
    return {
        "player_seat": choice.player_index,
        "amount": choice.data.get("amount", 0),
        "card_name": choice.data.get("card_name", ""),
        # "…pay {2} for **each** creature chosen this way" (Mudslide): the
        # price of one pick, so the client can show what a selection costs.
        # Absent (empty) for a free untap, which is what Rewind prints.
        "cost_each": dict(choice.data.get("cost_each") or {}),
        "candidates": candidates,
    }


@prompt_renderer("search_exile_cards")
def _search_exile(ctx: PromptContext, choices: list) -> dict:
    """The two-zone exile search (Chandra, Heart of Fire's −9): both zones'
    cards with the indices the restriction admits, multi-select. The engine
    re-checks every pick, so these indices are a hint, not a permission."""
    choice = choices[0]
    caster = ctx.game.players[choice.player_index]
    zones = tuple(choice.data.get("zones", ("graveyard", "library")))

    def _matches(card) -> bool:
        return ctx.game._exile_search_matches(card, choice.data)

    payload = {
        "caster_seat": choice.player_index,
        "zones": list(zones),
        "card_types": list(choice.data.get("card_types") or ()),
        "colors": list(choice.data.get("colors") or ()),
        # "Search your library for **three** cards" (Foresight). None for the
        # "any number of" spelling. The engine refuses a longer answer either
        # way; this is what stops the UI offering a fourth pick that will be
        # rejected whole.
        "maximum": choice.data.get("maximum"),
        "cards": [ctx.serialize_card(card) for card in caster.library],
        "legal_indices": [
            index for index, card in enumerate(caster.library) if _matches(card)
        ],
        "graveyard_cards": [ctx.serialize_card(card) for card in caster.graveyard],
        "legal_graveyard_indices": [
            index for index, card in enumerate(caster.graveyard) if _matches(card)
        ],
    }
    return payload


@prompt_renderer("reorder_library")
def _reorder_library(ctx: PromptContext, choices: list) -> dict:
    choice = choices[0]
    target = ctx.game.players[choice.data["target_index"]]
    top_count = choice.data["top_count"]
    return {
        "caster_seat": choice.player_index,
        "target_seat": choice.data["target_index"],
        "top_count": top_count,
        "may_shuffle": bool(choice.data.get("may_shuffle")),
        # False for a look that only shows the cards (Visions). The engine
        # ignores the order sent for such a prompt either way; this is what
        # stops the UI offering a rearrangement that will not happen.
        "may_reorder": bool(choice.data.get("may_reorder", True)),
        "target_name": target.name,
        "cards": [ctx.serialize_card(card) for card in target.library[:top_count]],
    }


@prompt_renderer("scry")
def _scry(ctx: PromptContext, choices: list) -> dict:
    choice = choices[0]
    # Whose library the cards come off. Absent is the chooser's, which is every
    # scry; Coral Fighters looks at the defending player's, and a renderer that
    # read the chooser's would show the wrong cards for the decision being made.
    owner = ctx.game.players[choice.data.get("library_index", choice.player_index)]
    top_count = choice.data["top_count"]
    return {
        "caster_seat": choice.player_index,
        "library_seat": ctx.game.players.index(owner),
        "card_name": choice.data.get("card_name", ""),
        "top_count": top_count,
        # The printed number, which can exceed top_count on a short library —
        # the prompt still says "Scry 3" when only two cards are there.
        "amount": choice.data["amount"],
        "cards": [ctx.serialize_card(card) for card in owner.library[:top_count]],
    }


@prompt_renderer("revealed_hand_pick")
def _revealed_hand_pick(ctx: PromptContext, choices: list) -> dict:
    """Duress: the *caster* picks out of the victim's revealed hand.

    The whole hand is sent — the card revealed it (CR 701.20), so hiding the
    unpickable cards would show the chooser less than the game does — with the
    legal indices marked so the client can offer only those.
    """
    choice = choices[0]
    victim_seat = int(choice.data["victim_index"])
    victim = ctx.game.players[victim_seat]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name"),
        "victim_seat": victim_seat,
        "victim_name": victim.name,
        "legal_indices": list(choice.data.get("legal_indices") or []),
        "cards": [ctx.serialize_card(card) for card in victim.hand],
    }


@prompt_renderer("discard")
def _discard(ctx: PromptContext, choices: list) -> dict:
    """The whole hand, with the positions that may actually be chosen.

    "Discard a **creature** card" (Crypt Lurker) narrows what pays, so the
    eligible positions ride alongside — the whole hand is still sent, because
    the client draws it and greys out what the phrase does not name. The list
    comes from ``live_discard_candidates``, which is the same rule the engine
    re-checks an answer against: a prompt that offers what the resolution then
    refuses is the mismatch every picker here is arranged to prevent.
    """
    choice = choices[0]
    discarder = ctx.game.players[choice.player_index]
    return {
        "player_seat": choice.player_index,
        "count": choice.data["count"],
        # "Up to" — the count is a ceiling, not a floor, so the client lets the
        # player confirm with fewer (none included).
        "up_to": bool(choice.data.get("up_to")),
        "allow_top_of_library": bool(choice.data.get("allow_top_of_library")),
        "cards": [ctx.serialize_card(card) for card in discarder.hand],
        "eligible": ctx.game.live_discard_candidates(choice),
    }


@prompt_renderer("hand_to_library")
def _hand_to_library(ctx: PromptContext, choices: list) -> dict:
    """The whole hand, and how many of it go back on top of the library.

    Every card is eligible — neither printing narrows what may be chosen — so
    there is no `eligible` list here, unlike the discard prompt beside it. What
    the client does carry is the *order*: the card says "in any order", so the
    sequence the player confirms is the answer, and the first named lands on
    top.
    """
    choice = choices[0]
    player = ctx.game.players[choice.player_index]
    return {
        "player_seat": choice.player_index,
        "count": choice.data["count"],
        # "…both on top of your library **or both on the bottom**" (Dream
        # Cache). Whether the client offers the second button at all, read off
        # the same key the resolver checks the answer against.
        "may_choose_end": choice.data.get("destination") == "either_end",
        "cards": [ctx.serialize_card(card) for card in player.hand],
        # "**Shuffle** a card from your hand into your library."
        # (Lat-Nam's Legacy.) The same decision — which cards leave the hand —
        # with the order stripped out of the answer, because a shuffle destroys
        # it (CR 701.19). The client says so rather than telling the player the
        # first card they pick goes on top, which on this card is a promise the
        # rules break a moment later.
        "shuffle": bool(choice.data.get("shuffle")),
    }


@prompt_renderer("commander_zone_change")
def _commander_zone_change(ctx: PromptContext, choices: list) -> dict:
    """CR 903.9: one commander at a time, naming where it was headed and which
    half of the rule is asking — 903.9a (it died or was exiled) and 903.9b (it
    was about to be bounced or tucked) read very differently to a player."""
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card": ctx.serialize_card(choice.data["card"]),
        "destination": choice.data["destination"],
        "rule": choice.data["rule"],
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }


@prompt_renderer("leng_discard")
def _leng_discard(ctx: PromptContext, choices: list) -> dict:
    """Library of Leng: one card at a time, with how many are still queued."""
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card": ctx.serialize_card(choice.data["card"]),
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }


@prompt_renderer("optional_damage_redirect")
def _optional_damage_redirect(ctx: PromptContext, choices: list) -> dict:
    """Blood of the Martyr: take this creature's damage yourself, or leave it.

    One event at a time, with how many are still queued behind it — a board
    sweep can arm one per creature, and they are answered in the order they
    were dealt.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "amount": choice.data["amount"],
        "from_name": choice.data["from_name"],
        "options": list(choice.options),
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }


@prompt_renderer("balance")
def _balance(ctx: PromptContext, choices: list) -> dict:
    choice = choices[0]
    seat = choice.player_index
    plan = choice.data["plan"]
    player = ctx.game.players[seat]
    return {
        "player_seat": seat,
        "lands_to_sacrifice": plan["lands"],
        "creatures_to_sacrifice": plan["creatures"],
        "cards_to_discard": plan["hand"],
        "lands": [
            {"index": i, **ctx.serialize_card(p.card)}
            for i, p in enumerate(player.battlefield)
            if p.card.primary_type == "land"
        ],
        "creatures": [
            {"index": i, **ctx.serialize_card(p.card)}
            for i, p in enumerate(player.battlefield)
            if p.card.primary_type == "creature"
        ],
        "hand": [ctx.serialize_card(card) for card in player.hand],
    }


@prompt_renderer("sacrifice")
def _sacrifice(ctx: PromptContext, choices: list) -> dict:
    """Every eligible permanent, so the board can list and highlight them."""
    choice = choices[0]
    state = ctx.game._sacrifice_prompt(choice)
    player = ctx.game.players[choice.player_index]
    return {
        "player_seat": choice.player_index,
        "count": state["count"],
        # Whether the count is owed or offered. "Sacrifice any number of
        # untapped Forests" (Wood Elemental) is answered by any subset, none
        # included, and a picker that could only confirm at exactly the ceiling
        # would make the offer a demand.
        "up_to": state["up_to"],
        "reason": state["reason"],
        "permanents": [
            {"index": i, **ctx.serialize_card(player.battlefield[i].card)}
            for i in state["valid_indices"]
        ],
    }


@prompt_renderer("optional_pay")
def _optional_pay(ctx: PromptContext, choices: list) -> dict:
    """The colour rods and friends: a seat can owe several at once."""
    return {"pending": [
        {**public_data(choice), "player_index": choice.player_index} for choice in choices
    ]}


@prompt_renderer("pay_life_to_save")
def _pay_life_to_save(ctx: PromptContext, choices: list) -> dict:
    """Cleansing: "…unless any player pays 1 life", asked about one permanent.

    One offer at a time — the sweep asks each seat in turn about each land — so
    the first queued choice is the whole prompt.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "permanent_id": data.get("permanent_id"),
        "permanent_name": data.get("permanent_name", ""),
        "life": int(data.get("life", 1)),
    }


@prompt_renderer("color_set_choice")
def _color_set_choice(ctx: PromptContext, choices: list) -> dict:
    """Shyft: "you may have this creature become the color or colors of your
    choice." ``several`` is what tells the client whether to let more than one
    be picked — the printed offer, not a UI preference."""
    data = choices[0].data
    permanent = data.get("permanent")
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "permanent_name": getattr(getattr(permanent, "card", None), "name", ""),
        "colors": list(data.get("colors") or []),
        "several": bool(data.get("several")),
    }


@prompt_renderer("revealed_draw_buyout")
def _revealed_draw_buyout(ctx: PromptContext, choices: list) -> dict:
    """Zur's Weirding: "Then any other player may pay 2 life."

    One offer at a time -- the poll asks each other seat in turn about one
    revealed card -- so the first queued choice is the whole prompt. The card's
    name rides the prompt because the whole decision is about which card it is,
    and the reveal itself is a moment rather than a zone.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "revealed_name": data.get("revealed_name", ""),
        "drawing_player": data.get("drawing_player", ""),
        "life": int(data.get("life", 2)),
    }


@prompt_renderer("hand_reveal")
def _hand_reveal(ctx: PromptContext, choices: list) -> dict:
    choice = choices[0]
    revealed = ctx.game.players[choice.data["target_index"]]
    return {
        "viewer_seat": choice.player_index,
        "target_seat": choice.data["target_index"],
        "target_name": revealed.name,
        "cards": [ctx.serialize_card(card) for card in revealed.hand],
    }


@prompt_renderer("draw_up_to")
def _draw_up_to(ctx: PromptContext, choices: list) -> dict:
    """"Each player may draw up to two cards." (Truce.)

    The answer is a number, so the payload is the range and the library the
    seat would draw from — the same shape ``number_choice`` below takes, with
    the ceiling coming from the card and the default from the engine's stated
    policy for an "up to" (take the maximum, capped by the library so a seat
    does not choose to deck itself).
    """
    choice = choices[0]
    data = choice.data
    high = int(data.get("amount", 0))
    library = len(ctx.game.players[choice.player_index].library)
    return {
        "player_seat": choice.player_index,
        "card_name": data.get("card_name", ""),
        "minimum": 0,
        "maximum": high,
        "options": list(range(0, high + 1)),
        "default": min(high, library),
        "library_size": library,
    }


@prompt_renderer("bid_life")
def _bid_life(ctx: PromptContext, choices: list) -> dict:
    """Illicit Auction: what the standing bid is and what this seat may say.

    The buttons stop at the seat's own life total, and the engine deliberately
    does **not**: the card prints no ceiling and the winner *loses* the life
    rather than paying it, so a bid above a life total is legal and lethal.
    What the offer shows is every bid this seat could survive, which is the
    range a client has any business proposing on its own.
    """
    choice = choices[0]
    data = choice.data
    high = int(data.get("high_bid", 0))
    holder = int(data.get("high_bidder", 0))
    life = ctx.game.players[choice.player_index].life
    return {
        "player_seat": choice.player_index,
        "card_name": data.get("card_name", ""),
        "high_bid": high,
        "high_bidder": holder,
        "high_bidder_name": ctx.game.players[holder].name,
        "minimum": high + 1,
        "life": life,
        "options": list(range(high + 1, life + 1)),
    }


@prompt_renderer("number_choice")
def _number_choice(ctx: PromptContext, choices: list) -> dict:
    data = choices[0].data
    low, high = int(data["minimum"]), int(data["maximum"])
    return {
        "card_name": data["card_name"],
        "minimum": low,
        "maximum": high,
        "options": list(range(low, high + 1)),
        "default": int(data.get("default_number", low)),
    }


@prompt_renderer("land_type_choice")
def _land_type_choice(ctx: PromptContext, choices: list) -> dict:
    return {
        "card_name": choices[0].data["card_name"],
        "options": ["plains", "island", "swamp", "mountain", "forest"],
    }


@prompt_renderer("mana_payment")
def _mana_payment(ctx: PromptContext, choices: list) -> dict:
    data = choices[0].data
    target_item = data.get("stack_item")
    # The cost as the card prints it, beside the total the client has always
    # rendered. `amount` alone cannot say "{B}" — Ayesha Tanaka's prompt read
    # "{1}" — and it cannot say "{B} or {3}" (Thrull Wizard) at all. Which of
    # CR 118.8's alternatives is spent is still the engine's (the first the
    # board covers); the label is so the payer can see what they are agreeing
    # to before they tap.
    costs = ctx.game._mana_payment_costs(data)
    return {
        "card_name": data["card_name"],
        "amount": int(data["amount"]),
        "cost": " or ".join(mana_cost_label(cost) for cost in costs),
        "spell_name": target_item.card.name if target_item is not None else None,
    }


@prompt_renderer("kudzu_reattach")
def _kudzu_reattach(ctx: PromptContext, choices: list) -> dict:
    owner = ctx.game.players[choices[0].player_index]
    return {
        "lands": [
            {"index": i, "name": p.card.name}
            for i, p in enumerate(owner.battlefield)
            if p.card.primary_type == "land"
        ],
    }


@prompt_renderer("face_down_cast")
def _face_down_cast(ctx: PromptContext, choices: list) -> dict:
    choice = choices[0]
    owner = ctx.game.players[choice.player_index]
    max_cmc = int(choice.data.get("max_cmc", 0))
    return {
        "card_name": choice.data["card_name"],
        "max_cmc": max_cmc,
        "choices": [
            {"hand_index": i, "name": c.name, "cmc": int(c.cmc or 0)}
            for i, c in enumerate(owner.hand)
            if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc
        ],
    }


@prompt_renderer("flip_again")
def _flip_again(ctx: PromptContext, choices: list) -> dict:
    """Game of Chaos: whether the player the last flip favoured runs it again.

    ``stake`` is what the *next* round is worth, which is the whole decision —
    the round just played is already paid for.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "stake": int(choice.data.get("stake", 0)),
    }


@prompt_renderer("exile_from_hand_choice")
def _exile_from_hand_choice(ctx: PromptContext, choices: list) -> dict:
    """Ice Cauldron: which card in this seat's hand is exiled under the artifact.

    The candidates come from the engine's own rule, for the reason the pick
    below it gives. ``optional`` is what the sentence said, and it is what
    decides whether the board draws a Decline button: "You **may** exile a
    nonland card from your hand" (Ice Cauldron) may be declined, and "Exile a
    card from your hand face down" (Gustha's Scepter) may not — a seat shown a
    Decline for the second would be offered an answer the engine refuses.
    """
    choice = choices[0]
    owner = ctx.game.players[choice.player_index]
    live = ctx.game.live_exile_from_hand_choices(choice)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "optional": bool(
            (choice.data.get("_payload") or {}).get("optional", True)
        ),
        "choices": [
            {"hand_index": index, "name": owner.hand[index].name} for index in live
        ],
    }


@prompt_renderer("library_pile_split")
def _library_pile_split(ctx: PromptContext, choices: list) -> dict:
    """Phyrexian Portal: the *opponent* divides the ten cards.

    The cards are sent in full, because this seat is looking at them - that is
    what the sentence says, and it is the whole asymmetry of the card. The seat
    that has to choose between the piles gets the renderer below, which sends
    two numbers.
    """
    choice = choices[0]
    owner = ctx.game.players[int(choice.data["owner_index"])]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "owner_name": owner.name,
        "cards": [
            {"pile_index": index, "card": ctx.serialize_card(card)}
            for index, card in enumerate(choice.data.get("_cards") or ())
        ],
    }


@prompt_renderer("pile_exile_choice")
def _pile_exile_choice(ctx: PromptContext, choices: list) -> dict:
    """Phyrexian Portal: which face-down pile is exiled.

    **Sizes only.** The piles are face down (CR 406.3) and this is the seat
    that may not look at them; sending the cards "so the client can grey them
    out" would hand the whole decision away, because a permission only the
    client honours is a rule nothing enforces.
    """
    choice = choices[0]
    piles = list(choice.data.get("_piles") or ())
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "sizes": [len(pile) for pile in piles],
    }


@prompt_renderer("pile_search")
def _pile_search(ctx: PromptContext, choices: list) -> dict:
    """Phyrexian Portal: search the pile that was not exiled.

    ``optional`` is CR 701.23b - a player may always fail to find - and it is
    what tells the client to draw the decline. The engine accepts the empty
    answer whether or not the client offers it.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "optional": True,
        "cards": [
            {"pile_index": index, "card": ctx.serialize_card(card)}
            for index, card in enumerate(choice.data.get("_pile") or ())
        ],
    }


@prompt_renderer("library_cycle_offer")
def _library_cycle_offer(ctx: PromptContext, choices: list) -> dict:
    """Lim-Dul's Vault: pay the life again, or stop and shuffle.

    The cards themselves are sent, because looking at them *is* the effect -
    a prompt that asked "pay 1 life again?" without showing what the payment
    already bought would be asking the player to decide blind. They come off
    the top of the chooser's own library, which is where the loop left them.

    ``payable`` is the engine's own CR 119.4 test rather than a second reading
    of the life total, so the button the board draws and the answer the engine
    accepts agree.
    """
    choice = choices[0]
    player = ctx.game.players[choice.player_index]
    count = min(int(choice.data.get("count", 0)), len(player.library))
    life_cost = int(choice.data.get("life_cost", 0))
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "life_cost": life_cost,
        "payable": player.life >= life_cost,
        "cards": [ctx.serialize_card(card) for card in player.library[:count]],
    }


@prompt_renderer("linked_exile_return")
def _linked_exile_return(ctx: PromptContext, choices: list) -> dict:
    """Gustha's Scepter: which card under the artifact comes back to this hand.

    The candidates come from the engine's own rule, for the reason every card
    picker here gives: a list built twice is a list that can be offered wider
    than it is checked. ``entry_index`` addresses the linked-exile *record*
    (CR 610.3) rather than a position in the exile pile, because two copies of
    one card in a deck are the same object there.

    There is no ``optional`` key and no Decline: the sentence is mandatory, and
    the only thing that ends it without a card moving is an empty pile — which
    is a prompt that was never armed with an answer rather than one declined.
    """
    from engine.linked_exile import linked_entries

    choice = choices[0]
    entries = linked_entries(choice.data.get("_source_permanent"))
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "zone": choice.data.get("zone", "hand"),
        "choices": [
            {"entry_index": index, "name": entries[index]["card"].name}
            for index in ctx.game.live_linked_exile_return_choices(choice)
        ],
    }


@prompt_renderer("put_from_hand_choice")
def _put_from_hand_choice(ctx: PromptContext, choices: list) -> dict:
    """Eureka: which card in this seat's hand goes onto the battlefield.

    The candidates come from the engine's own rule, so the list offered and the
    list an answer is checked against are one rule rather than two copies.
    ``optional`` is what the sentence said, and it is what decides whether the
    board draws a Decline button — a seat shown one for a mandatory pick would
    be offered an answer the engine refuses.
    """
    choice = choices[0]
    owner = ctx.game.players[choice.player_index]
    live = ctx.game.live_put_from_hand_choices(choice)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "optional": bool(choice.data.get("optional")),
        "choices": [
            {"hand_index": index, "name": owner.hand[index].name} for index in live
        ],
    }


@prompt_renderer("choose_cards_in_hand")
def _choose_cards_in_hand(ctx: PromptContext, choices: list) -> dict:
    """Sylvan Library: which cards in this seat's hand the next step acts on.

    The candidates come from the engine's own rule, so the list offered and the
    list an answer is checked against are one rule rather than two copies.
    ``count`` is what the seat owes — the printed number, or fewer when the
    hand holds fewer eligible cards (CR 608.2) — so a board cannot enable a
    Confirm on a pick the engine will refuse.
    """
    choice = choices[0]
    owner = ctx.game.players[choice.player_index]
    live = ctx.game.live_choose_cards_in_hand(choice)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "count": ctx.game._how_many_cards_to_choose(choice),
        "choices": [
            {"hand_index": index, "name": owner.hand[index].name} for index in live
        ],
    }


@prompt_renderer("text_change_vocabulary")
def _text_change_vocabulary(ctx: PromptContext, choices: list) -> dict:
    """Mind Bend: "…replacing all instances of one color word with another **or
    one basic land type with another**." Which vocabulary, asked only when both
    would do something.

    The two words were named at the cast and are the same mana symbol read two
    ways — "R" is red and it is Mountain — so what is offered is the *reading*,
    spelled out, rather than a second pair of words to choose.
    """
    # Both tables keyed by mana symbol, from the module that owns them: the
    # grammar's `COLOR_WORDS` is the same pairs inverted.
    from engine.text_changes import COLOR_WORDS, LAND_TYPE_WORDS

    choice = choices[0]
    old_symbol = str(choice.data.get("old_symbol") or "")
    new_symbol = str(choice.data.get("new_symbol") or "")
    words = {"color_word": COLOR_WORDS, "land_type": LAND_TYPE_WORDS}
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "permanent_name": choice.data.get("permanent_name", ""),
        "options": [
            {
                "mode": mode,
                "from": words[mode].get(old_symbol, ""),
                "to": words[mode].get(new_symbol, ""),
            }
            for mode in (choice.data.get("options") or ())
        ],
    }


@prompt_renderer("aggregate_sacrifice")
def _aggregate_sacrifice(ctx: PromptContext, choices: list) -> dict:
    """Phyrexian Dreadnought: "…sacrifice any number of creatures with total
    power 12 or greater."

    Every candidate with what it contributes, because the contribution *is* the
    question — a client that showed names alone could not tell whether a
    selection pays. The floor and the running rule are sent too, and the engine
    re-checks the answer against both, so a client sending a short set cannot
    buy the offer cheaply.
    """
    choice = choices[0]
    payload = dict(choice.data.get("_payload") or {})
    characteristic = str(choice.data.get("characteristic") or "power")
    candidates = ctx.game.aggregate_sacrifice_candidates(
        choice.player_index, payload
    )
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "characteristic": characteristic,
        "at_least": int(choice.data.get("at_least", 0)),
        "choices": [
            {
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
                "amount": ctx.game.aggregate_sacrifice_total(
                    [perm], characteristic
                ),
            }
            for perm in candidates
        ],
    }


@prompt_renderer("library_end_choice")
def _library_end_choice(ctx: PromptContext, choices: list) -> dict:
    """Ether Well: "If that creature is red, you may put it on the bottom of
    its owner's library instead."

    The permanent is still on the battlefield while this is owed — the move is
    what the answer performs — so the card being moved is named rather than
    pointed at by a zone position that does not exist yet.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "moved_name": choice.data.get("moved_name", ""),
        "owner_name": choice.data.get("owner_name", ""),
    }


@prompt_renderer("graveyard_pile_choice")
def _graveyard_pile_choice(ctx: PromptContext, choices: list) -> dict:
    """Ebony Charm: "Exile up to three target cards **from a single
    graveyard**." Which pile, asked before which cards.

    Only piles that still hold a card the printed phrase names are offered, and
    they are re-derived through the engine's own candidate rule rather than sent
    from the armed list — a card can leave a graveyard between the offer and the
    answer, and a pile offered here is one the pick behind it would find empty.
    The count of legal cards travels with each option because that is what the
    choice is actually between.
    """
    choice = choices[0]
    live = ctx.game.live_graveyard_pile_choices(choice)
    payload = dict(choice.data.get("_payload") or {})
    from engine.handlers._common import graveyard_card_matches

    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "options": [
            {
                "seat": seat,
                "name": ctx.game.players[seat].name,
                "legal_cards": sum(
                    1 for card in ctx.game.players[seat].graveyard
                    if graveyard_card_matches(payload, card)
                ),
            }
            for seat in live
        ],
    }


@prompt_renderer("graveyard_exile_pick")
def _graveyard_exile_pick(ctx: PromptContext, choices: list) -> dict:
    """Rysorian Badger: which cards in the defending player's graveyard go.

    The whole pile is sent with the positions the printed noun phrase admits,
    the shape every card picker here takes: the client draws the pile and greys
    out what the phrase does not name, and the engine re-checks the answer
    against the same rule. ``count`` is the ceiling — "up to two" out of a pile
    holding one is one (CR 608.2) — and ``up_to`` is what tells the client an
    empty answer is a legal one.
    """
    choice = choices[0]
    owner_seat = int(choice.data["owner_index"])
    owner = ctx.game.players[owner_seat]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "owner_seat": owner_seat,
        "owner_name": owner.name,
        "count": ctx.game._how_many_graveyard_cards(choice),
        "up_to": bool(choice.data.get("up_to")),
        "legal_indices": ctx.game.live_graveyard_exile_candidates(choice),
        "cards": [ctx.serialize_card(card) for card in owner.graveyard],
    }


@prompt_renderer("word_of_command")
def _word_of_command(ctx: PromptContext, choices: list) -> dict:
    target = ctx.game.players[choices[0].data["target_index"]]
    return {
        "target_name": target.name,
        "choices": [{"hand_index": i, "name": c.name} for i, c in enumerate(target.hand)],
    }


@prompt_renderer("opponent_damage")
def _opponent_damage(ctx: PromptContext, choices: list) -> dict:
    """Cuombajj Witches: "any target", so every player face and every creature."""
    data = choices[0].data
    targets: list[dict] = [
        {"kind": "player", "seat": seat} for seat in range(len(ctx.game.players))
    ]
    for seat, player in enumerate(ctx.game.players):
        for idx, perm in enumerate(player.battlefield):
            if perm.is_creature:
                targets.append(
                    {"kind": "permanent", "seat": seat, "index": idx,
                     "key": f"{seat}-{idx}", "name": perm.card.name}
                )
    return {
        "card_name": data["card_name"],
        "amount": data["amount"],
        "valid_targets": targets,
    }


@prompt_renderer("enter_choice")
def _enter_choice(ctx: PromptContext, choices: list) -> dict:
    """The "as this enters, choose …" prompt, in all six of its shapes.

    Every key is read with ``.get``, and that is not defensive style: the
    armings do not all pass the same fields. Runed Halo's card-name arming
    passes ``needs_card_name`` and nothing else, so ``data["needs_color"]``
    raised ``KeyError`` and the whole state payload 500'd for any interactive
    seat that resolved it — the prompt could not be shown, so the choice could
    not be answered and the game could not go on. One arming forgetting a key a
    renderer subscripts is a shape no test of the *engine* can see, which is why
    the guard beside this one renders every kind's own data.
    """
    data = choices[0].data
    needs_color = bool(data.get("needs_color"))
    return {
        "card_name": data["card_name"],
        "needs_color": needs_color,
        "opponents": [
            {"seat": seat, "name": ctx.game.players[seat].name}
            for seat in (data.get("opponents") or ())
        ],
        "default_seat": data.get("default_seat"),
        "default_color": data.get("default_color"),
        "colors": ["W", "U", "B", "R", "G"] if needs_color else [],
        # "…choose a card name." (Runed Halo.) A name rather than a quality:
        # CR 202.1 lets a player name any card, so the offered list is what the
        # chooser can actually see rather than a catalog, and the answer is not
        # checked against it.
        "needs_card_name": bool(data.get("needs_card_name")),
        "card_names": list(data.get("choices") or ()),
        "default_chosen_card_name": data.get("default_card_name"),
        # "…choose two basic land types." (Illusionary Terrain.) A fourth shape
        # of this one prompt: an ordered pair out of CR 205.3i's five, with no
        # seat and no colour. The offered list is the vocabulary the resolver
        # checks against, asked of the same constant, so the picker cannot
        # offer a word the answer path would refuse (idiom 9).
        "needs_land_types": bool(data.get("needs_land_types")),
        "land_types": list(BASIC_LAND_WORDS) if data.get("needs_land_types") else [],
        "default_land_types": list(data.get("default_land_types") or ()),
        # "…choose a creature type." (An-Zerrin Ruins.) A fifth shape of this
        # one prompt: one word out of CR 205.3m's catalog, with no seat and no
        # colour. The offered list is the whole vocabulary rather than the
        # types in play, because the rule bounds the choice by the catalog and
        # not by any board — and it is the same catalog the resolver checks the
        # answer against, so the picker cannot offer a word the answer path
        # would refuse (idiom 9).
        "needs_creature_type": bool(data.get("needs_creature_type")),
        "creature_types": (
            sorted(CREATURE_TYPES) if data.get("needs_creature_type") else []
        ),
        "default_creature_type": data.get("default_creature_type"),
        # "…choose a land type." (Shimmer.) A sixth shape of this one prompt:
        # one word out of CR 205.3i's catalog, with no seat and no colour, and
        # the *whole* catalog rather than the five basics the ordered pair
        # above draws from. Offered from the same vocabulary the resolver
        # checks the answer against (idiom 9).
        "needs_land_type": bool(data.get("needs_land_type")),
        "chosen_land_types": (
            sorted(LAND_TYPES) if data.get("needs_land_type") else []
        ),
        "default_land_type": data.get("default_land_type"),
    }


@prompt_renderer("entry_exile")
def _entry_exile(ctx: PromptContext, choices: list) -> dict:
    """The entry cost paid out of a graveyard (Frankenstein's Monster): the
    chooser's whole graveyard with the positions the printed noun phrase admits,
    how many of them the cost is, and the counter kinds each exiled card may
    buy.

    ``legal_indices`` is the engine's own candidate list, asked of the same
    method the answer is re-checked against - so the picker cannot offer a card
    the answer path would refuse (idiom 9). The graveyard is a public zone
    (CR 400.2), which is why the whole pile is serialized rather than only the
    legal slots: a player choosing which creatures to give up is reading the
    order they went in.
    """
    choice = choices[0]
    player = ctx.game.players[choice.player_index]
    return {
        "caster_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "count": int(choice.data.get("count", 0)),
        "counters": list(choice.data.get("counters") or ()),
        "cards": [ctx.serialize_card(card) for card in player.graveyard],
        "legal_indices": ctx.game._entry_exile_candidates(choice),
    }


@prompt_renderer("body_choice")
def _body_choice(ctx: PromptContext, choices: list) -> dict:
    """Primal Clay: "it becomes your choice of <body>". The first printed body
    is already applied, so the prompt offers to replace it."""
    data = choices[0].data
    return {
        "card_name": data["card_name"],
        "options": [
            {
                "index": i,
                "power": body["power"],
                "toughness": body["toughness"],
                "keyword": body.get("keyword"),
            }
            for i, body in enumerate(data["options"])
        ],
    }


@prompt_renderer("mode_choice")
def _mode_choice(ctx: PromptContext, choices: list) -> dict:
    """A modal ability's "Choose one -" (Relic Bind, Trufflesnout, Elder
    Gargaroth): the offered mode labels, answered by index.

    A mode that targets carries its own candidates, because CR 700.2b and
    CR 601.2c make the mode and its target one announcement - the player who
    picks the mode picks its target in the same breath, and the modes of one
    ability may target quite different things (CR 115.8). The candidates are
    the engine's own offered list, so the picker cannot offer what the answer
    path would refuse; a permanent rides its stable ``id`` alongside the
    ``seat``/``index`` the canvas addresses it by.

    ``targets`` is absent for a mode that chooses nothing, and for every mode
    of a ``choose_one`` nested inside a running resolution, which announces no
    targets at all.
    """
    choice = choices[0]
    data = choice.data
    options = tuple(data.get("_options") or ())
    modes = []
    for index, label in enumerate(data.get("labels") or []):
        entry = {"index": index, "label": label}
        option = options[index] if index < len(options) else None
        if option is not None and option["spec"].get("requires_target"):
            entry["targets"] = [
                _mode_target_view(ctx, candidate)
                for candidate in option.get("valid_targets") or []
            ]
        modes.append(entry)
    return {
        "player_seat": choice.player_index,
        "card_name": data["card_name"],
        "modes": modes,
    }


@prompt_renderer("opponent_mode_choice")
def _opponent_mode_choice(ctx: PromptContext, choices: list) -> dict:
    """"An opponent chooses one -" (CR 700.2e): the modes of a spell **somebody
    else** cast, offered to the player who has to pick one.

    The labels and nothing else. Its twin above carries each mode's candidates
    because the seat that picks the mode also picks its target in the same
    announcement (CR 601.2c); here those are two different players, so the
    targets are asked for *after* this answer, through
    ``modal_mode_targets`` below, and there is nothing to offer beside the
    label.
    """
    choice = choices[0]
    data = choice.data
    return {
        "player_seat": choice.player_index,
        "card_name": data["card_name"],
        "modes": [
            {"index": index, "label": label}
            for index, label in enumerate(data.get("labels") or [])
        ],
    }


@prompt_renderer("modal_mode_targets")
def _modal_mode_targets(ctx: PromptContext, choices: list) -> dict:
    """The targets of the mode an opponent chose (Fatal Lore), offered to the
    **caster** — the other half of ``opponent_mode_choice`` above.

    Rendered from the list the engine froze when it armed the prompt rather
    than from a live board read: targets are chosen once, at announcement
    (CR 601.2c), and the answer is checked against that same list. A renderer
    that re-enumerated would offer a permanent the engine would then refuse.

    ``max_targets`` is sent for ``permanent_set_choice``'s reason — the client
    cannot derive a ceiling that is smaller than the candidate list, and "up to
    two" is what the card printed.
    """
    choice = choices[0]
    data = choice.data
    return {
        "player_seat": choice.player_index,
        "card_name": data.get("card_name", ""),
        "mode_label": data.get("mode_label", ""),
        "max_targets": int(data.get("max_targets", 1)),
        "candidates": [
            {
                "seat": entry["seat"],
                "index": entry["permanent_index"],
                "id": entry["permanent_id"],
                "name": entry["name"],
            }
            for entry in (data.get("targets") or ())
        ],
    }


def _mode_target_view(ctx: PromptContext, candidate: dict) -> dict:
    """One candidate of one mode, as the client picks it."""
    if candidate.get("kind") != "permanent":
        seat = candidate.get("seat")
        return {
            "kind": "player",
            "seat": seat,
            "name": ctx.game.players[seat].name,
        }
    permanent = ctx.game.permanent_at(candidate["seat"], candidate["index"])
    return {
        "kind": "permanent",
        "seat": candidate["seat"],
        "index": candidate["index"],
        "id": None if permanent is None else permanent.permanent_id,
        "name": candidate.get("name"),
    }


@prompt_renderer("loyalty_recipient")
def _loyalty_recipient(ctx: PromptContext, choices: list) -> dict:
    """Liliana's Scrounger: which of the permanents the printed noun phrase
    names gets the loyalty counter.

    The candidates come from the engine's own liveness rule, so the list offered
    and the list the answer is checked against cannot drift. ``seat``/``index``
    ride alongside the stable ``id`` for the canvas, which addresses a card by
    its slot; the engine answers on the id.
    """
    choice = choices[0]
    live = {id(perm) for perm in ctx.game.live_loyalty_recipients(choice)}
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "count": choice.data.get("count", 1),
        "candidates": [
            {
                "seat": seat,
                "index": index,
                "id": ctx.game.permanent_id_of(perm),
                "name": perm.card.name,
                "loyalty": int(perm.metadata.get("loyalty_counters", 0)),
            }
            for seat, player in enumerate(ctx.game.players)
            for index, perm in enumerate(player.battlefield)
            if id(perm) in live
        ],
    }


@prompt_renderer("permanent_choice")
def _permanent_choice(ctx: PromptContext, choices: list) -> dict:
    """"…to another permanent of that type" (Enchantment Alteration): the
    permanent this seat picks as the spell resolves.

    The candidates come from the engine's own liveness rule, so the list offered
    and the list the answer is checked against are one rule rather than two
    copies. ``seat``/``index`` ride alongside the stable ``id`` for the canvas,
    which addresses a card by its slot; the engine answers on the id.
    """
    choice = choices[0]
    live = {id(perm) for perm in ctx.game.live_permanent_choices(choice)}
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "prompt": choice.data.get("prompt", ""),
        # Whether the seat may answer with nothing. The client needs it to know
        # whether to offer a decline, and the engine re-checks it — a client
        # that declined a mandatory choice would otherwise skip a branch the
        # card does not have.
        "optional": bool(choice.data.get("optional")),
        "candidates": [
            {
                "seat": seat,
                "index": index,
                "id": ctx.game.permanent_id_of(perm),
                "name": perm.card.name,
            }
            for seat, player in enumerate(ctx.game.players)
            for index, perm in enumerate(player.battlefield)
            if id(perm) in live
        ],
    }


@prompt_renderer("permanent_set_choice")
def _permanent_set_choice(ctx: PromptContext, choices: list) -> dict:
    """"…chooses up to two Plains" (Raiding Party): the permanents this seat
    picks as the ability resolves, multi-select up to a printed ceiling.

    The plural of ``permanent_choice`` above and rendered the same way, off the
    engine's own liveness rule — the list offered and the list the answer is
    checked against are one rule rather than two copies. ``up_to`` is sent
    because the client cannot derive it: unlike the tap prompt beside it, the
    ceiling is smaller than the candidate list and is what the card printed.
    """
    choice = choices[0]
    live = {id(perm) for perm in ctx.game.live_permanent_set_choices(choice)}
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "prompt": choice.data.get("prompt", ""),
        "up_to": int(choice.data.get("up_to", 1)),
        "candidates": [
            {
                "seat": seat,
                "index": index,
                "id": ctx.game.permanent_id_of(perm),
                "name": perm.card.name,
            }
            for seat, player in enumerate(ctx.game.players)
            for index, perm in enumerate(player.battlefield)
            if id(perm) in live
        ],
    }


@prompt_renderer("least_power_choice")
def _least_power_choice(ctx: PromptContext, choices: list) -> dict:
    data = choices[0].data
    return {
        "card_name": data["card_name"],
        "candidates": [dict(entry) for entry in data["candidates"]],
    }


@prompt_renderer("player_choice")
def _player_choice(ctx: PromptContext, choices: list) -> dict:
    """Backdraft: "Choose a player who cast one or more sorcery spells this
    turn." The seats are re-derived through the engine's own liveness test, so
    a player who has left the game since the prompt was armed is not offered."""
    choice = choices[0]
    live = ctx.game.live_player_choices(choice)
    return {
        "card_name": choice.data.get("card_name", ""),
        "prompt": choice.data.get("prompt", "Choose a player."),
        "options": [
            {"seat": seat, "name": ctx.game.players[seat].name} for seat in live
        ],
    }


@prompt_renderer("cast_choice")
def _cast_choice(ctx: PromptContext, choices: list) -> dict:
    """Backdraft: "…one of those sorcery spells this turn." Each option carries
    what that cast dealt, which is what the choice is actually between — and is
    public information, since the damage was dealt in the open."""
    data = choices[0].data
    options = list(data.get("options") or ())
    names = list(data.get("names") or ())
    damages = list(data.get("damages") or ())
    return {
        "card_name": data.get("card_name", ""),
        "prompt": data.get("prompt", "Choose a spell."),
        "options": [
            {
                "index": index,
                "name": names[position] if position < len(names) else "",
                "damage": damages[position] if position < len(damages) else 0,
            }
            for position, index in enumerate(options)
        ],
    }


@prompt_renderer("retarget_choice")
def _retarget_choice(ctx: PromptContext, choices: list) -> dict:
    """Deflection: "Change the target of target spell with a single target."

    The candidates are re-derived through the engine's own liveness test, so a
    creature that has died or a player who has left since the prompt was armed
    is not offered — and the position each option carries is its position in the
    armed list, which is what the answer names."""
    choice = choices[0]
    data = choice.data
    options = list(data.get("options") or ())
    return {
        "card_name": data.get("card_name", ""),
        "prompt": data.get("prompt", "Choose a new target."),
        "options": [
            {
                "index": position,
                "name": options[position].get("name", ""),
                "kind": options[position].get("kind", ""),
            }
            for position in ctx.game.live_retarget_choices(choice)
        ],
    }


@prompt_renderer("lamp_draw")
def _lamp_draw(ctx: PromptContext, choices: list) -> dict:
    """Aladdin's Lamp: the looked-at cards are still on top of the library until
    the choice is confirmed, so serialize them from there for the visual picker.
    ``card_names`` stays the authoritative order and length."""
    choice = choices[0]
    names = list(choice.options)
    library = ctx.game.players[choice.player_index].library
    return {
        "card_names": names,
        "cards": [ctx.serialize_card(card) for card in library[: len(names)]],
    }


@prompt_renderer("outside_game_draw")
def _outside_game_draw(ctx: PromptContext, choices: list) -> dict:
    """Ring of Ma'rûf: the offered cards can be a subset of the sideboard (CR
    407.3 keeps ante cards out of a non-ante game), so follow the recorded
    positions rather than assuming the names are a prefix of it."""
    choice = choices[0]
    names = list(choice.options)
    sideboard = ctx.game.players[choice.player_index].sideboard
    offered = choice.data.get("sideboard_indices") or list(range(len(names)))
    return {
        "card_names": names,
        "cards": [
            ctx.serialize_card(sideboard[i]) for i in offered if 0 <= i < len(sideboard)
        ],
    }
