"""Renderers for the prompts answered with cards.

One renderer per kind of prompt (``web/prompt_registry.py`` says what a
renderer is handed, ``web/prompts.py`` how its payload is shown, gated and
answered): searching a library or exile, a look at a library's top and the
orders put back on it, cards picked out of a hand, a graveyard, exile or a
pile, separating into piles (CR 700.3), and naming a card and what the name
then does. Each payload says which cards may be picked and how many must be,
in the words of the engine's own candidate list, so the client cannot offer
an answer the resolver will refuse.
"""

from __future__ import annotations

from engine.oracle_types import CLAIMABLE_EXILED_CARDS
from engine.search_filters import search_matches, search_slots, searched_seat

from .prompt_registry import PromptContext, prompt_renderer


_SEARCH_COLOR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}

_SEARCH_COMPARISON_WORDS = {
    "eq": "{value}", "le": "{value} or less", "lt": "less than {value}",
    "ge": "{value} or greater", "gt": "greater than {value}",
}


def search_slot_label(slot: dict) -> str:
    """One printed description of a one-per-description search, in words a
    dialog can put on a slot: "a creature card", "a noncreature, nonland card",
    "a Plains land card".

    *slot* is in ``search_matches``' own vocabulary (``card_type`` /
    ``exclude_types`` / ``restrictions``), which is what the engine tests a
    card against and nothing a player reads. This is presentation only — the
    words are assembled from the keys that predicate honours, in the order a
    card prints them (supertype, colour, subtype, type), and a key this does
    not know adds nothing rather than a guess, so the label can say less than
    the slot tests and never more.
    """
    restrictions = slot.get("restrictions") or {}
    words: list[str] = []
    excluded = [f"non{name}" for name in slot.get("exclude_types") or ()]
    if excluded:
        words.append(", ".join(excluded))
    words.extend(str(word) for word in restrictions.get("supertypes") or ())
    colors = [
        _SEARCH_COLOR_WORDS.get(str(symbol).upper(), str(symbol))
        for symbol in restrictions.get("any_colors") or ()
    ]
    if colors:
        words.append(" or ".join(colors))
    words.extend(str(word).capitalize() for word in restrictions.get("subtypes") or ())
    card_type = slot.get("card_type", "any")
    types = card_type if isinstance(card_type, (list, tuple)) else (card_type,)
    types = [str(name) for name in types if name and name != "any"]
    if types:
        words.append(" or ".join(types))
    words.append("card")
    label = " ".join(words)
    if restrictions.get("named"):
        label += f" named {restrictions['named']}"
    mana_value = restrictions.get("mana_value")
    if isinstance(mana_value, dict) and mana_value.get("op") in _SEARCH_COMPARISON_WORDS:
        label += " with mana value " + _SEARCH_COMPARISON_WORDS[mana_value["op"]].format(
            value=mana_value.get("value")
        )
    article = "an" if label[:1].lower() in "aeiou" else "a"
    return f"{article} {label}"


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
        # **Whose** zones these are, which is not always the seat choosing:
        # Guided Passage's opponent picks out of the caster's library, and the
        # cards go to that library's owner's hand. The dialog said "your
        # library" and "your hand" to whoever was asked.
        "zone_seat": ctx.game.players.index(caster),
        "zone_owner_name": caster.name,
        "count": choice.data["count"],
        "card_type": choice.data["card_type"],
        "card_name": choice.data.get("card_name", ""),
        # CR 701.23d: how many cards this answer **must** name — the engine's
        # own floor. 0 for a search with a stated quality (CR 701.23b: it may
        # fail to find) and for "up to"; 1 for "search your library for a
        # card" while the zone holds one (Demonic Tutor, Entomb), where "fail
        # to find" is not an answer and ``search_library_decline`` is a 400.
        # Sent for every search; the counted branch below sends the same key.
        "min_picks": ctx.game._search_floor(choice),
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
        # Asked the way the resolver asks (``_resolve_search_library_picks``):
        # with the game and the answering seat, so a colour or a creature type
        # a static gives a card outside the battlefield (Celestial Dawn,
        # Conspiracy) is in this list exactly when the answer would be taken.
        "legal_indices": (
            [
                index for index, card in enumerate(caster.library)
                if search_matches(
                    card, choice.data, game=ctx.game, owner=choice.player_index
                )
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
        # CR 701.23d: how many this answer **must** name — the engine's own
        # floor, which is 0 for "up to" and for a search nothing can answer.
        # Sent so the dialog can hold its confirm (and withhold "fail to
        # find") until the answer is one the resolver will take, instead of
        # sending an under-find to be refused whole.
        payload["min_picks"] = ctx.game._search_floor(choice)
    # "a land card **of each basic land type**" (Gaea's Balance); "a creature
    # card, a land card, and a noncreature, nonland card" (Guided Passage). One
    # find per printed description. `legal_indices` is the union of them, which
    # is all a card-at-a-time list can say — two creatures are each legal and
    # together are not an answer — so the descriptions ride beside it, in the
    # engine's own words, for a dialog to label its picks with. Additive like
    # everything else here: the engine checks the answer whole either way.
    #
    # Each description also says **which cards answer it** and what to call
    # it. Which description a pick fills is not readable off the union — a
    # Tropical Island answers the Forest slot and the Island slot — so a dialog
    # that wants to refuse a second creature has to be told per slot, by the
    # one predicate the resolver assigns with (``slot_assignment``).
    described = search_slots(choice.data)
    if described:
        def _answers(slot: dict, cards) -> list[int]:
            return [
                index for index, card in enumerate(cards)
                if search_matches(
                    card, slot, game=ctx.game, owner=choice.player_index
                )
            ]

        payload["one_of_each"] = [
            {
                **dict(slot),
                "label": search_slot_label(slot),
                "legal_indices": (
                    _answers(slot, caster.library) if "library" in zones else []
                ),
                **(
                    {"legal_graveyard_indices": _answers(slot, caster.graveyard)}
                    if "graveyard" in zones else {}
                ),
            }
            for slot in described
        ]
    if "graveyard" in zones:
        payload["graveyard_cards"] = [
            ctx.serialize_card(card) for card in caster.graveyard
        ]
        payload["legal_graveyard_indices"] = [
            index for index, card in enumerate(caster.graveyard)
            if search_matches(
                card, choice.data, game=ctx.game, owner=choice.player_index
            )
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
    # `pile_owner`, not `caster`: the two are the same seat on twelve of the
    # thirteen cards that reach here and are *different* on Sealed Fate, which
    # is the whole reason `look_top_pile_index` exists. The name below used to
    # be `caster` and the line under it read `owner.library` — a `NameError`
    # sitting in a function body, waiting for its line to run. It ran the day a
    # hand-activated Waker of Waves could reach the browser, and it 500s
    # `GET /state` for all thirteen: Orcish Librarian, Diabolic Vision, Browse,
    # Lim-Dul's Vault, Ashnod's Cylix, Ancestral Memories, Preferred Selection,
    # Sealed Fate, Impulse, Ancestral Knowledge, See the Truth, Waker of Waves
    # and Garruk's Harbinger.
    pile_owner = ctx.game.players[pile_seat]
    top_count = min(int(choice.data.get("top_count", 0)), len(pile_owner.library))
    return {
        "caster_seat": choice.player_index,
        "pile_seat": pile_seat,
        "top_count": top_count,
        "card_name": choice.data.get("card_name", ""),
        "cards": [ctx.serialize_card(card) for card in pile_owner.library[:top_count]],
        # What the pick *is*, which the family varies and the prompt has to be
        # able to say: where the chosen card goes, where the rest go, and how
        # many picks are still owed. Sealed Fate exiles from an opponent's
        # pile and Bamboozle bins two of four, and a prompt that could only
        # say "keep one" describes neither.
        "pick_destination": choice.data.get("pick_destination", "hand"),
        "rest_destination": choice.data.get("rest_destination", "library_bottom"),
        "remaining": int(choice.data.get("remaining", 1)),
    }


@prompt_renderer("choose_card_name")
def _choose_card_name(ctx: PromptContext, choices: list) -> dict:
    """Foreshadow's "choose a card name".

    No suggestion list, for the reason Petra Sphinx's below has none: CR 202.1
    lets the chooser name any card at all, and a list built over what they can
    see would either be useless or would hand them the answer — here the answer
    is the top of an opponent's library, which nobody may look at.

    ``card_type`` is the printed *bound* on that freedom — "Choose a
    **creature** card name" (Wood Sage) — and it is carried even though there
    is no list, because it is the one thing about the choice the player has to
    be told: a prompt reading "name a card" under a card that says "name a
    creature card" is a prompt offering more than the card allows. Absent for
    every unbounded naming, so Foreshadow's payload is unchanged.
    """
    choice = choices[0]
    prompt = {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
    }
    if choice.data.get("card_type"):
        prompt["card_type"] = choice.data["card_type"]
    # "…other than a basic land card name" (Desperate Research): the other
    # printed bound, told to the player for the reason the type is.
    if choice.data.get("exclude_basic_land_names"):
        prompt["exclude_basic_land_names"] = True
    return prompt


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


@prompt_renderer("exiled_pile_claim")
def _exiled_pile_claim(ctx: PromptContext, choices: list) -> dict:
    """Thieves' Auction's "each player chooses one of the exiled cards".

    The cards come off the **resolution's own pile** rather than off any zone,
    and that is the whole reason the prompt exists: exile is public (CR 400.2),
    but a player's exile also holds everything that ever went there by any other
    route, and this spell is handing out exactly what it took. The list is
    therefore what is still unclaimed, in the order it is offered, and the index
    a client sends back is an index into *that* — the same list the resolver
    re-checks the answer against (idiom 9), so the picker cannot show a card the
    answer path would decline.

    Re-read on every render rather than snapshotted with the arming: the pile
    shrinks as the seats ahead of this one answer, and a stale list would offer
    a card that has already been taken.
    """
    choice = choices[0]
    context = choice.data.get("_context")
    pile = (context.results.get(CLAIMABLE_EXILED_CARDS) or []) if context else []
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "tapped": bool(choice.data.get("tapped")),
        "options": [
            {"index": index, "card": ctx.serialize_card(card)}
            for index, (_, card) in enumerate(pile)
        ],
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
        # Which end of the library the pile is: "top" for every look-and-put-
        # back, "bottom" for "…and the rest on the bottom of your library in
        # any order" (Goblin Ringleader, CR 401.4). The cards come from the
        # engine's own reader of the pile, so what is drawn here and what an
        # answer permutes cannot be different ends of the deck.
        "position": str(choice.data.get("position", "top")),
        "cards": [
            ctx.serialize_card(card)
            for card in ctx.game.reorder_library_pile(choice)
        ],
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
        # Where the cards the seat does not keep go: "bottom" is a scry
        # (CR 701.22a) and "graveyard" a surveil (CR 701.25a). Sent because
        # the one answer shape serves both and only the words on the prompt
        # can tell the seat which it is deciding.
        "destination": choice.data.get("destination", "bottom"),
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
        # "…choose **up to** X cards from it" (Discordant Dirge). CR 601.2c's
        # ceiling, sent for the reason the discard prompt one renderer down
        # sends its own: the client is what offers the way to stop, and a
        # ceiling only the engine knew about is a prompt the chooser cannot
        # leave.
        "up_to": bool(choice.data.get("up_to")),
        "cards": [ctx.serialize_card(card) for card in victim.hand],
    }


@prompt_renderer("opponent_picks_revealed")
def _opponent_picks_revealed(ctx: PromptContext, choices: list) -> dict:
    """Thran Tome: the *opponent* picks one of the cards the revealer turned up.

    The names as the reveal showed them, in library order, because that is what
    CR 701.20 made public \u2014 and the revealer's seat beside them, since the
    chooser is not the player whose card is about to be binned. Every card is a
    legal answer, so no legality list rides along: the sentence narrows nothing.
    """
    choice = choices[0]
    revealer_seat = int(choice.data.get("revealer_index", 0))
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "revealer_seat": revealer_seat,
        "revealer_name": ctx.game.players[revealer_seat].name,
        "cards": list(choice.data.get("cards") or []),
        "fate": str(choice.data.get("fate", "graveyard")),
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
        # "…on **the bottom** of their library in any order." (Teferi's Puzzle
        # Box.) Which end the cards are headed for, so the client can say so
        # rather than telling the player their first pick goes on top — which
        # on this card is the exact opposite of what happens. A word rather
        # than a second boolean beside `may_choose_end`: those two answer
        # "which end" and "does the player pick it", and one key for both is
        # how a prompt starts lying about one of them.
        "destination": (
            "bottom" if choice.data.get("destination") == "bottom" else "top"
        ),
        "cards": [ctx.serialize_card(card) for card in player.hand],
        # "**Shuffle** a card from your hand into your library."
        # (Lat-Nam's Legacy.) The same decision — which cards leave the hand —
        # with the order stripped out of the answer, because a shuffle destroys
        # it (CR 701.24a). The client says so rather than telling the player the
        # first card they pick goes on top, which on this card is a promise the
        # rules break a moment later.
        "shuffle": bool(choice.data.get("shuffle")),
    }


@prompt_renderer("discard_unless_pay_life")
def _discard_unless_pay_life(ctx: PromptContext, choices: list) -> dict:
    """Breathstealer's Crypt: "that player discards it unless they pay 3 life",
    asked about the card that was just drawn and revealed.

    One offer at a time — the replacement arms it per draw — so the first queued
    choice is the whole prompt. ``life`` travels rather than being a constant
    here, because the number is the printing's and a second card saying it
    differently must not need a second renderer.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "source_name": data.get("source_name", ""),
        "life": int(data.get("life", 0)),
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


@prompt_renderer("exile_hand_pile_choice")
def _exile_hand_pile(ctx: PromptContext, choices: list) -> dict:
    """Scroll Rack: which cards in this seat's hand go under the artifact.

    The candidates come from the engine's own rule, for the reason the single
    pick below gives: the list the seat is shown and the list its answer is
    checked against have to be one list.

    No Decline, and that is the sentence rather than an omission: "exile **any
    number of** cards" is answered with a set, and the empty set is one of the
    answers — a Decline button would be a second spelling of it.
    """
    choice = choices[0]
    owner = ctx.game.players[choice.player_index]
    live = ctx.game.live_exile_hand_pile_choices(choice)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "choices": [
            {"hand_index": index, "name": owner.hand[index].name} for index in live
        ],
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


def _face_up_pile_items(ctx: PromptContext, choice) -> list[dict]:
    """Every object a CR 700.3 split is over, in the order the engine holds
    them — the positions an answer names.

    Face up, to every seat that sees the prompt: these piles are public (the
    cards were revealed, or are permanents, or lie in a graveyard), which is
    the whole difference from the face-down pair above. A permanent carries its
    id so the client can point at the one on the board.
    """
    from engine.piles import item_card

    session = choice.data["_session"]
    group = choice.data["_group"]
    items = []
    for position, item in enumerate(group.items):
        card = item_card(ctx.game, session, group, position)
        entry = {
            "pile_index": position,
            "card": ctx.serialize_card(card) if card is not None else None,
        }
        if session.what == "battlefield":
            entry["permanent_id"] = item
        items.append(entry)
    return items


@prompt_renderer("pile_split")
def _pile_split(ctx: PromptContext, choices: list) -> dict:
    """CR 700.3: this seat separates the listed objects into two piles.

    ``what`` says what kind of object they are (``library_top`` /
    ``graveyard`` / ``battlefield``) and ``owner_name`` whose; the fates ride
    along so the separator can see what each pile is for.
    """
    choice = choices[0]
    session = choice.data["_session"]
    owner = ctx.game.players[int(choice.data["owner_index"])]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "owner_name": owner.name,
        "what": session.what,
        "chosen_fate": session.payload.get("chosen"),
        "other_fate": session.payload.get("other"),
        "cards": _face_up_pile_items(ctx, choice),
    }


@prompt_renderer("pile_choice")
def _pile_choice(ctx: PromptContext, choices: list) -> dict:
    """CR 700.3: this seat chooses one of the two piles somebody separated.

    Both piles in full — positions into the same item list the split named —
    because the chooser is looking at them.
    """
    choice = choices[0]
    session = choice.data["_session"]
    group = choice.data["_group"]
    owner = ctx.game.players[int(choice.data["owner_index"])]
    items = _face_up_pile_items(ctx, choice)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "owner_name": owner.name,
        "what": session.what,
        "chosen_fate": session.payload.get("chosen"),
        "other_fate": session.payload.get("other"),
        "piles": [[items[position] for position in pile] for pile in group.piles],
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
    # "…chooses one card **of each color** from it" (Noxious Vapors). The pick
    # is an assignment to printed slots, so ``count`` alone under-describes it:
    # two red cards are the right number and the wrong answer. The line the
    # panel shows is why the engine would refuse them.
    slots = (choice.data.get("_payload") or {}).get("slots") or ()
    by_color = bool(slots) and all(
        set(slot.get("filter") or {}) == {"color_filter"} for slot in slots
    )
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "count": ctx.game._how_many_cards_to_choose(choice),
        "rule": (
            "one card of each color — a multicolored card counts for one of its colors"
            if by_color else "one card for each kind the card names" if slots else ""
        ),
        # "Reveal **any number of** blue cards in your hand." (Brine Seer and
        # the eleven cards printed with it.) The count above is then a ceiling
        # rather than a debt, and nought is a legal answer — so the board needs
        # both halves or it gates Confirm on a pick the engine would accept.
        # Read off the engine's own predicate, so the offer rendered and the
        # answer checked are one rule.
        "any_number": ctx.game._may_choose_fewer_cards_in_hand(choice),
        # CR 701.20a: the cards become public. The word the panel uses, because
        # "choose" and "reveal" are different promises to the player about what
        # the rest of the table is about to see.
        "verb": (
            "reveal"
            if (choice.data.get("_payload") or {}).get("reveal")
            else "choose"
        ),
        "choices": [
            {"hand_index": index, "name": owner.hand[index].name} for index in live
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
    from engine.handlers._filters import graveyard_card_matches

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

    ``destination`` is where the picked cards go: ``"exile"`` for every
    printed exile, ``"library_bottom"`` for Gurzigost's "put two cards from
    your graveyard on the bottom of your library" — the same question with
    another verb, which the client has to say out loud rather than calling
    every pick an exile.
    """
    choice = choices[0]
    owner_seat = int(choice.data["owner_index"])
    owner = ctx.game.players[owner_seat]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "destination": choice.data.get("destination") or "exile",
        "owner_seat": owner_seat,
        "owner_name": owner.name,
        "count": ctx.game._how_many_graveyard_cards(choice),
        "up_to": bool(choice.data.get("up_to")),
        "legal_indices": ctx.game.live_graveyard_exile_candidates(choice),
        "cards": [ctx.serialize_card(card) for card in owner.graveyard],
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
