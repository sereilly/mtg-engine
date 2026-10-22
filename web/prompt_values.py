"""Renderers for the prompts answered with a value: a colour, a type, a
word, a body, a number, a payment or a yes.

One renderer per kind of prompt (``web/prompt_registry.py`` says what a
renderer is handed, ``web/prompts.py`` how its payload is shown, gated and
answered): "as this enters, choose …" and the other colour, type and word
choices, how many and how much (a bid, a secret number, "any amount"), mana
paid from the board, the "you may pay" offers and the wording they are shown
in, and the CR 614 replacement offers with CR 616.1e's choice of which effect
applies first.
"""

from __future__ import annotations

import re

from engine.grammar.phrases import BASIC_LAND_WORDS
from engine.grammar.vocabulary import CREATURE_TYPES, LAND_TYPES
from engine.mana_payment import mana_cost_label
from engine.pending_choices import public_data

from .prompt_registry import PromptContext, prompt_renderer


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


@prompt_renderer("entry_discard_toll")
def _entry_discard_toll(ctx: PromptContext, choices: list) -> dict:
    """Mox Diamond: which card in hand pays for the entry, or none of them.

    The offered slots are the hand indices the printed phrase admits, so the
    picker cannot show a card the answer path would refuse (idiom 9), and the
    cards themselves are serialized from the hand for the visual picker.
    """
    choice = choices[0]
    player = ctx.game.players[choice.player_index]
    indices = [i for i in (choice.data.get("hand_indices") or []) if 0 <= i < len(player.hand)]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data["permanent"].card.name,
        "hand_indices": indices,
        "cards": [ctx.serialize_card(player.hand[i]) for i in indices],
    }


@prompt_renderer("draw_becomes_counter")
def _draw_becomes_counter(ctx: PromptContext, choices: list) -> dict:
    """Pursuit of Knowledge: take the counter, or take the draw.

    One offer at a time - the replacement arms one per draw - with how many are
    still queued behind it, exactly as the redirect above reports.
    """
    choice = choices[0]
    source = ctx.game.permanent_by_id(int(choice.data["source_id"]))
    return {
        "player_seat": choice.player_index,
        "counter": choice.data["counter"],
        "source_name": source.card.name if source is not None else "",
        "options": list(choice.options),
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }


@prompt_renderer("reveal_until_kind_draw")
def _reveal_until_kind_draw(ctx: PromptContext, choices: list) -> dict:
    """Abundance: reveal until a nonland card, until a land card, or just draw.

    One offer at a time - the replacement arms one per draw - with how many are
    still queued behind it, exactly as the counter offer above reports. The
    option labels come off the choice rather than being spelled here, so what
    the client shows and what the resolver accepts are one list.
    """
    choice = choices[0]
    source = ctx.game.permanent_by_id(int(choice.data["source_id"]))
    return {
        "player_seat": choice.player_index,
        "source_name": source.card.name if source is not None else "",
        "options": list(choice.options),
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }


@prompt_renderer("skip_draw")
def _skip_draw(ctx: PromptContext, choices: list) -> dict:
    """Obstinate Familiar: draw the card, or skip that draw.

    The Abundance offer's shape one option shorter, and for its reasons: one
    offer at a time (the replacement arms one per draw) with how many are
    queued behind it, and the labels come off the choice so what the client
    shows and what the resolver accepts are one list. ``library_size`` rides
    along because it is the whole decision — skipping matters when the next
    draw would be from an empty library — and a seat always knows the size of
    its own library.
    """
    choice = choices[0]
    source = ctx.game.permanent_by_id(int(choice.data["source_id"]))
    return {
        "player_seat": choice.player_index,
        "source_name": source.card.name if source is not None else "",
        "options": list(choice.options),
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
        "library_size": len(ctx.game.players[choice.player_index].library),
    }


_REMINDER_TEXT = re.compile(r"\([^)]*\)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_OFFER_WORD = re.compile(r"\b(?:unless|may)\b", re.IGNORECASE)
#: "At the beginning of your upkeep, " / "When this creature dies, ": the
#: trigger a sentence opens with, which is not part of either answer.
_TRIGGER_OPENING = re.compile(r"^(?:at|when|whenever)\b[^,]*,\s*", re.IGNORECASE)


def _offer_source_card(data: dict):
    """The card an offer or a number was asked by, as its text reads now: the
    source permanent through ``effective_card`` (CR 612 - a text change is the
    text), else the resolving spell."""
    permanent = data.get("_source_permanent") or data.get("permanent")
    card = getattr(permanent, "effective_card", None)
    if card is None:
        card = getattr(data.get("_context"), "card", None)
    return card


def _offer_sentences(text: str) -> list[str]:
    """The sentences of *text* that make an offer ("…unless…" / "…may…"),
    reminder text dropped, in printed order."""
    return [
        sentence.strip()
        for line in text.split("\n")
        for sentence in _SENTENCE_END.split(_REMINDER_TEXT.sub("", line).strip())
        if sentence.strip() and _OFFER_WORD.search(sentence)
    ]


def offer_wording(data: dict) -> dict:
    """What a prompt with no words of its own can say: the printed sentence
    it was armed by, and for "X unless Y" which half each answer is.

    An offer priced in mana or life says so (``prompt``: "Pay {2}?"). One
    priced in an *action* said nothing - Blazing Salvo's payload is a card
    name and four zeroes, and the browser showed "you may apply this optional
    effect. Do it?" over a choice between 3 damage to a creature and 5 to its
    controller's face. The engine knows the instructions and not their
    English; the card does, so the sentence is read off it:

    * ``card_text`` - the one sentence of the source that makes an offer
      ("…unless…" / "…may…"), or the whole text when that is not exactly one
      sentence, so nothing is guessed between two offers on one card — unless
      the printed line that armed this offer (the context's ``ability_text``)
      holds exactly one of them, which is then this offer's;
    * ``accept_text`` / ``decline_text`` - the halves of "X unless Y", which
      is the form where "yes" is the *second* clause and so the one a bare
      Yes / No gets backwards. Absent for "you may …", where yes is the
      sentence.

    A reading of printed text for a label, never a rule: nothing dispatches on
    it, and the answer is the same index whatever the words say.
    """
    card = _offer_source_card(data)
    text = getattr(card, "oracle_text", "") or ""
    if not text:
        return {}
    offers = _offer_sentences(text)
    if len(offers) != 1:
        # Two offers on one card are told apart by the ability that made this
        # one, which is not a guess: Gurzigost's upkeep toll ("…sacrifice this
        # creature unless you put two cards from your graveyard on the bottom
        # of your library") and its activated "You may have this creature
        # assign its combat damage …" both read the whole two-sentence text,
        # so a person could not tell which was being asked. The resolving
        # context carries the printed line (``ability_text``); an offer
        # sentence of the card that is in that line, and only one, is this
        # offer's. Anything else — no line, a line with two offers, a line a
        # text change has rewritten — is the whole text, as before.
        line = getattr(data.get("_context"), "ability_text", "") or ""
        own = [sentence for sentence in _offer_sentences(line) if sentence in offers]
        if len(own) != 1:
            return {"card_text": text}
        offers = own
    sentence = offers[0]
    wording = {"card_text": sentence}
    head, found, tail = sentence.rstrip(".").partition(" unless ")
    if found and head and tail:
        wording["decline_text"] = _TRIGGER_OPENING.sub("", head, count=1)
        wording["accept_text"] = tail
    return wording


@prompt_renderer("optional_pay")
def _optional_pay(ctx: PromptContext, choices: list) -> dict:
    """The colour rods and friends: a seat can owe several at once.

    An offer the engine gave a ``prompt`` (a mana or life price, Tainted
    Pact's named card) is sent as it is; one it gave none carries the printed
    sentence instead (:func:`offer_wording`).
    """
    return {"pending": [
        {
            **public_data(choice),
            "player_index": choice.player_index,
            **({} if choice.data.get("prompt") else offer_wording(choice.data)),
            # Whether "yes" would be accepted as the board stands: the price
            # from the pool plus the lands the engine taps for a payer. False
            # is not "cannot pay" — the seat may hold mana the plan does not
            # tap (a Sol Ring, a filter land), and may tap it and answer again
            # — it is "tap for it first": an accept now is a 400 that keeps
            # the offer (`Game.seat_answers_for_itself`). The engine's own
            # reader, so the button and the answer cannot disagree.
            "payable": ctx.game._player_can_pay_optional(
                ctx.game.players[choice.player_index], choice.data
            ),
        }
        for choice in choices
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


@prompt_renderer("mana_color_choice")
def _mana_color_choice(ctx: PromptContext, choices: list) -> dict:
    """"Add N mana of any one color" (Carpet of Flowers, Sanctum of Fruitful
    Harvest), resolving with nobody having named a colour.

    ``colors`` is the set the *clause* offers, read off the arming rather than
    assumed to be the five colours of CR 106.1b's six mana types: "any color
    that a land an opponent controls
    could produce" was narrowed when the ability began resolving, and a picker
    showing a colour the answer path would refuse is the drift idiom 9 is about.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "amount": int(data.get("amount", 0) or 0),
        "colors": [str(c).upper() for c in (data.get("colors") or ())],
        "default_color": data.get("default_color"),
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


@prompt_renderer("pay_any_amount")
def _pay_any_amount(ctx: PromptContext, choices: list) -> dict:
    """Liege of the Hollows: how much mana this seat may pay, and what it can.

    "Any amount" prints no ceiling at all, so unlike every other numbered
    prompt here the range comes from the **board**: the seat's floating mana
    plus its untapped mana lands, which is what
    ``mana_payment.plan_payment`` will accept when the answer comes back. Asked
    of the same reader the resolver uses — an offer the engine would refuse is
    not an offer.
    """
    from engine.mana_payment import generic_cost, plan_payment

    choice = choices[0]
    seat = choice.player_index
    player = ctx.game.players[seat]
    lands = ctx.game.payment_lands(seat)
    affordable = 0
    # Walk up rather than compute: `plan_payment` is the one answer to "can
    # this be paid", and a second arithmetic here is a second answer. The
    # ceiling is bounded by the pool plus the lands, so the loop is short.
    limit = sum(max(0, int(v)) for v in player.mana_pool.values()) + len(lands)
    for amount in range(1, limit + 1):
        if plan_payment(
            player.mana_pool, lands, generic_cost(amount),
            produces=ctx.game._land_payment_colors,
        ) is None:
            break
        affordable = amount
    return {
        "player_seat": seat,
        "card_name": choice.data.get("card_name", ""),
        "minimum": 0,
        "maximum": affordable,
        "options": list(range(0, affordable + 1)),
        # The printed "may": paying nothing is the answer that changes least,
        # and it is what a seat nobody asks takes.
        "default": 0,
    }


@prompt_renderer("secret_number")
def _secret_number(ctx: PromptContext, choices: list) -> dict:
    """Goblin Game: the number this seat names in secret.

    **Only what the seat already knows.** The payload is built from the
    viewer's own choice — the printed floor and its own life total — and from
    nothing else on the queue: ``visible_choices`` hands a renderer the
    viewer's prompts alone, the kind is not ``spectator_visible``, and the
    scratchpad the answers go into rides the choice under an engine-private key
    this never reads. So a seat still choosing is sent the same thing whether
    or not anybody else has answered, which is the card.

    The buttons stop at the seat's own life total and the engine does **not**,
    for ``_bid_life``'s reason one prompt up: the card prints no ceiling and
    the number is a loss, so naming more than a life total is legal and
    lethal. ``maximum`` stays None in the payload because the rule has none
    (CR 107.1).
    """
    choice = choices[0]
    low = int(choice.data.get("minimum", 0))
    life = int(ctx.game.players[choice.player_index].life)
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "minimum": low,
        "maximum": None,
        "life": life,
        "options": list(range(low, max(low, life) + 1)),
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
    """"Choose a number between 0 and 7" (Shapeshifter) — and "choose a number
    **greater than 0**" (Scrying Glass), which prints no ceiling at all.

    ``maximum`` is None for the open form, and it stays None in the payload
    because the *rule* has no ceiling: CR 107.1 puts no upper bound on a number
    a player may choose, and ``_resolve_number_choice`` accepts any answer above
    the floor. What needs a bound is the **offer**, since a list of options is
    how this prompt is shown and an empty one is a prompt armed and never
    displayed.

    So the offer's ceiling comes from the board, exactly as ``pay_any_amount``'s
    does one prompt over: the largest hand at the table, because every open
    "choose a number" in this pool is matched against a count of cards in one
    (Scrying Glass), and a number above the biggest hand cannot be matched by
    any of them. A one-card span is the floor, so the picker always offers
    something even with every hand empty.
    """
    data = choices[0].data
    low = int(data["minimum"])
    printed_high = data.get("maximum")
    if printed_high is None:
        span = max(1, max((len(p.hand) for p in ctx.game.players), default=1))
        offered_high = low + span
    else:
        offered_high = int(printed_high)
    return {
        "card_name": data["card_name"],
        "minimum": low,
        "maximum": None if printed_high is None else offered_high,
        "options": list(range(low, offered_high + 1)),
        "default": int(data.get("default_number", low)),
        # What the number is *for*. The payload is a range and a card name,
        # and "Rites of Initiation: choose a number between 0 and 4" does not
        # say that the number is how many cards leave the hand at random. The
        # card says it, so its text rides along (``offer_wording``'s reader of
        # the source) for the prompt to quote.
        "card_text": getattr(_offer_source_card(data), "oracle_text", "") or "",
    }


@prompt_renderer("land_type_choice")
def _land_type_choice(ctx: PromptContext, choices: list) -> dict:
    return {
        "card_name": choices[0].data["card_name"],
        # The five, or the list the sentence narrowed them to ("becomes a
        # Plains or an Island", Tundra Kavu) — read through the resolver's own
        # reader, so the picker cannot offer a type the answer path refuses.
        "options": list(ctx.game.land_type_choice_options(choices[0])),
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
    # "…and 1 life" (Mundungu) is part of the price, not an alternative to it,
    # so it is appended to the one label rather than offered beside it. A payer
    # shown only the mana would agree to a cost the engine then also charges in
    # life, which is the same "cheaper than it prints" the cast path guards.
    life = int(data.get("life", 0) or 0)
    return {
        "card_name": data["card_name"],
        "amount": int(data["amount"]),
        "cost": " or ".join(mana_cost_label(cost) for cost in costs)
        + (f" and {life} life" if life else ""),
        "life": life,
        "spell_name": target_item.card.name if target_item is not None else None,
        # Whether "pay" would be accepted as the board stands — the pool plus
        # the lands the engine taps for a payer. False means "tap for it
        # first": the payer may hold mana the plan does not tap (a Sol Ring, a
        # filter land), and an accept sent now is a 400 that keeps this prompt
        # rather than a counter. See `Game.mana_payment_is_payable`.
        "payable": ctx.game.mana_payment_is_payable(choices[0]),
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


@prompt_renderer("repeat_process")
def _repeat_process(ctx: PromptContext, choices: list) -> dict:
    """Forbidden Ritual: whether the controller runs the printed process again.

    Nothing but the card name and the seat, deliberately: "any number of times"
    names no stake and no count, so there is no number to show that would not be
    a number this renderer invented.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
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
    # "…choose **black or red**" / "…choose **Island or Swamp**" (Mangara's
    # Equity, Roots of Life). Two shapes of this prompt whose *offer* the
    # sentence prints rather than a catalog. The list is on the arming and is
    # the same one `_entry_choice_option_allowed` refuses to go outside, so the
    # picker cannot show a word the answer path would decline (idiom 9); with
    # no such list the catalog bounds the answer, which is every other arming.
    printed_options = [str(option) for option in (data.get("entry_choice_options") or ())]
    return {
        "card_name": data["card_name"],
        "needs_color": needs_color,
        "opponents": [
            {"seat": seat, "name": ctx.game.players[seat].name}
            for seat in (data.get("opponents") or ())
        ],
        "default_seat": data.get("default_seat"),
        "default_color": data.get("default_color"),
        "colors": (
            (printed_options or ["W", "U", "B", "R", "G"]) if needs_color else []
        ),
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
            (printed_options or sorted(LAND_TYPES))
            if data.get("needs_land_type") else []
        ),
        "default_land_type": data.get("default_land_type"),
    }


@prompt_renderer("land_type_swap")
def _land_type_swap(ctx: PromptContext, choices: list) -> dict:
    """"Choose a land type and a basic land type." (Vision Charm.)

    Two catalogs rather than one, because the printed adjective differs between
    the halves — all of CR 205.3i's types for the first, the five basics for the
    second — and the resolver checks each answer against its own. Offered from
    the same constants the resolver checks against (idiom 9), so the picker
    cannot show a word the answer path would decline.
    """
    data = choices[0].data
    basics = list(BASIC_LAND_WORDS)
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "from_options": basics if data.get("first_basic") else sorted(LAND_TYPES),
        "to_options": basics if data.get("second_basic") else sorted(LAND_TYPES),
        "default_from": data.get("default_from"),
        "default_to": data.get("default_to"),
    }


@prompt_renderer("card_type_choice")
def _card_type_choice(ctx: PromptContext, choices: list) -> dict:
    """"…chooses artifact, creature, land, or non-Aura enchantment."
    (Teferi's Realm.)

    The offered list comes from the *card* rather than from a catalog, so it
    travels on the arming and is handed straight to the client — the same list
    the resolver refuses to go outside (idiom 9), so the picker cannot show an
    option the answer path would decline. There is no catalog to fall back to
    that would be right: "every card type" includes instant, which no permanent
    is.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        "options": [str(option) for option in (data.get("options") or ())],
        "default_card_type": data.get("default_card_type"),
        # What naming a type *does*, when the arming site can say it for every
        # card that reaches it. The kind stopped being one card's the moment a
        # second thing armed it: Storage Matrix asks the same question during
        # the untap step and spends the answer quite differently, so the client
        # cannot carry one sentence for all of them. Absent from
        # ``choose_card_type``'s two arming branches, which serve Teferi's Realm
        # and Turnabout from one place and would have to name a card to tell
        # them apart — those fall back to the client's generic wording.
        "detail": data.get("detail"),
    }


@prompt_renderer("creature_type_choice")
def _creature_type_choice(ctx: PromptContext, choices: list) -> dict:
    """"Destroy all creatures **of the creature type of your choice**."
    (Extinction.)

    The offered list is CR 205.3m's whole catalog rather than the types in play,
    because the rule bounds the choice by the catalog and not by any board — and
    it is the same constant the resolver checks the answer against (idiom 9), so
    the picker cannot show a word the answer path would refuse.

    The default travels beside it: the handler already recorded it, so a seat
    that dismisses the prompt has the answer the sweep will use rather than
    none.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        # …less a printed "other than Wall" (Unnatural Selection), through the
        # resolver's own reader.
        "creature_types": sorted(ctx.game.creature_type_choice_options(choices[0])),
        "default_creature_type": data.get("default_creature_type"),
    }


@prompt_renderer("color_choice")
def _color_choice(ctx: PromptContext, choices: list) -> dict:
    """"**Choose a color.**" made while an ability resolves (CR 608.2d) —
    Chromatic Armor's re-choice, Hall of Gemstone's upkeep, Scrying Glass's
    guess.

    The offered list is CR 105.1's five and nothing else, which is the same set
    the resolver normalises the answer against (idiom 9), so the picker cannot
    show a colour the answer path would refuse. Colourless is not on it: CR
    105.2c is the absence of a colour, and "choose a color" names one.

    The default travels beside it — the handler recorded it before arming — so a
    seat that dismisses the prompt has the answer the step behind it will use
    rather than none.
    """
    data = choices[0].data
    return {
        "player_index": choices[0].player_index,
        "card_name": data.get("card_name", ""),
        # The sentence's own narrowing where it printed one ("a color of a
        # permanent you control", Meteor Crater) — the list the resolver holds
        # the answer to — and CR 105.1's five otherwise.
        "colors": list(data.get("colors") or ["W", "U", "B", "R", "G"]),
        "default_color": data.get("default_color"),
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


@prompt_renderer("return_from_graveyard_instead_of_draw")
def _return_from_graveyard_instead_of_draw(ctx: PromptContext, choices: list) -> dict:
    """Forbidden Crypt: the whole graveyard is offered, in its own order, and
    the answer is a position in it. Serialized from the pile rather than from
    the recorded names so the picker shows the cards themselves; ``card_names``
    stays the authoritative order and length, as it is for the two pickers
    below."""
    choice = choices[0]
    names = list(choice.options)
    graveyard = ctx.game.players[choice.player_index].graveyard
    return {
        "card_names": names,
        "cards": [ctx.serialize_card(card) for card in graveyard[: len(names)]],
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
