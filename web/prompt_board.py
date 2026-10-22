"""Renderers for the prompts answered with permanents, players, spells or
abilities.

One renderer per kind of prompt (``web/prompt_registry.py`` says what a
renderer is handed, ``web/prompts.py`` how its payload is shown, gated and
answered): a trigger's target, mode and order (CR 603.3b–d), a copied or
retargeted spell's new targets, a modal spell's modes, permanents to tap,
untap, sacrifice or keep (Balance's lists among them), a permanent, several or
a player chosen as an effect resolves, damage aimed at any target, and a spell
cast by a prompt rather than from a hand.
"""

from __future__ import annotations

from engine.faces import face_cards
from engine.grammar.vocabulary import display_type_word
from engine.trigger_order import live_trigger_indices, trigger_card

from .prompt_registry import PromptContext, prompt_renderer


@prompt_renderer("trigger_target")
def _trigger_target(ctx: PromptContext, choices: list) -> dict:
    """"…you may destroy target artifact defending player controls." (Floral
    Spuzzem.) "…target opponent mills two cards." (Teferi's Tutelage.)

    CR 603.3d: a triggered ability chooses its targets as it is put on the
    stack, so the candidates were enumerated *then* and are replayed here. The
    same shape as the reflexive prompt below and for the same reason — an
    answer naming something the picker never offered is refused rather than
    quietly performed.

    A candidate is a permanent or a **player's face**, and it says which: an
    "any target" trigger (Pitchburn Devils) offers both in one list, so the
    client cannot tell them apart by which fields happen to be filled in. A
    player carries a seat and no id; a permanent carries both, because the id is
    the identity and the seat is where to draw the highlight.

    …or a **card in a graveyard** (Gravedigger, Karmic Guide), the third
    shape: whose pile, which slot of it, and the card's name — a graveyard is
    a public zone and its cards have no id, so the pile and the slot are the
    whole address, exactly as the cast picker's ``graveyard`` entries give it.

    And a **spell** ("When this creature enters, counter target spell", Mystic
    Snake). A spell has no id, so a ``stack`` candidate carries its position in
    the stack as the client is shown it — ``stack_index``, topmost being 0, the
    convention a cast's ``target_stack_index`` already uses — read off the
    stack as it stands now rather than as it stood when the prompt was armed.
    The answer is checked against the object, not the number
    (``Game.trigger_target_stack_item``).
    """
    choice = choices[0]
    depth = len(ctx.game.stack)
    positions = {id(item): position for position, item in enumerate(ctx.game.stack)}
    candidates = []
    for target in choice.data.get("targets") or ():
        if target.get("kind") == "stack":
            position = positions.get(id(target.get("stack_item")))
            if position is None:
                continue
            candidates.append({
                "kind": "stack",
                "stack_index": depth - 1 - position,
                "seat": target.get("seat"),
                "name": target.get("name"),
            })
            continue
        if target.get("kind") == "graveyard":
            candidates.append({
                "kind": "graveyard",
                "seat": target.get("seat"),
                "graveyard_index": target.get("graveyard_index"),
                "name": target.get("name"),
            })
            continue
        candidates.append({
            "kind": target.get("kind", "permanent"),
            "seat": target.get("seat"),
            "index": target.get("permanent_index"),
            "id": target.get("permanent_id"),
            "name": target.get("name"),
        })
    payload = {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": candidates,
    }
    # "Up to two target creatures" (Basri's Acolyte, Cho-Arrim Bruiser): how
    # many the answer may name. Sent for ``modal_mode_targets``' reason — the
    # client cannot derive a ceiling smaller than the candidate list — and
    # absent for an ability that prints one target, so that prompt is the
    # payload it always was.
    if int(choice.data.get("max_targets") or 1) > 1:
        payload["max_targets"] = int(choice.data["max_targets"])
    # "**Up to** one target creature" (Barrin, Tolarian Archmage): naming
    # nobody is one of the answers (CR 601.2c), and the client offers it only
    # when told. Absent for an ability that owes its target, as above.
    if choice.data.get("up_to"):
        payload["up_to"] = True
    # "Distribute three -1/-1 counters among one, two, or three target
    # creatures" (Shambling Swarm): CR 601.2d's total and who divides it, the
    # two fields a divided spell's picker reads (``division_total``,
    # ``division``). Absent for every trigger that divides nothing.
    if choice.data.get("division_total") is not None:
        payload["division_total"] = int(choice.data["division_total"])
        payload["division"] = choice.data.get("division")
    # "Exile **two** target lands" (Petradon): a printed count with no "up to"
    # is owed whole (CR 601.2c), so the answer must name exactly
    # ``max_targets`` and the engine refuses a shorter one. Sent so the client
    # can hold its Confirm until the count is met; absent everywhere else.
    if choice.data.get("exact_targets"):
        payload["exact_targets"] = True
    # "Exile up to two target cards **from a single graveyard**" (Gravegouger):
    # several ``graveyard`` candidates, all of one answer in one pile. The
    # client keeps a selection inside the pile its first card came from and
    # sends ``target_seat`` with ``graveyard_indices`` — the flag the cast
    # picker's spec already carries for the same sentence on a spell
    # (``targeting.SINGLE_GRAVEYARD``). Absent everywhere else.
    if choice.data.get("single_graveyard") and payload.get("max_targets"):
        payload["single_graveyard"] = True
    return payload


@prompt_renderer("order_triggers")
def _order_triggers(ctx: PromptContext, choices: list) -> dict:
    """CR 603.3b: the triggered abilities a seat put on the stack together,
    **top first** — the first one listed resolves first — for the seat to put
    in the order it chooses.

    Each entry keeps its ``index`` into the offered list, which is what the
    answer (``order_triggers_confirm``'s ``trigger_order``) is written in; one
    that has left the stack meanwhile (a target prompt answered with nothing
    legal, CR 603.3d) is not shown and not owed. ``source_id`` is the
    permanent the ability came from, for the board to point at; two abilities
    of one card are told apart by their ``text``.
    """
    choice = choices[0]
    offered = list(choice.data.get("triggers") or ())
    items = tuple(choice.data.get("_trigger_items") or ())
    triggers = []
    for index in live_trigger_indices(ctx.game, choice):
        entry = offered[index]
        triggers.append({
            "index": index,
            "card_name": entry.get("card_name", ""),
            "text": entry.get("text", ""),
            "source_id": entry.get("source_id"),
            "card": ctx.serialize_card(trigger_card(items[index])),
        })
    return {"player_seat": choice.player_index, "triggers": triggers}


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


@prompt_renderer("word_of_command")
def _word_of_command(ctx: PromptContext, choices: list) -> dict:
    target = ctx.game.players[choices[0].data["target_index"]]
    return {
        "target_name": target.name,
        # A split card lists its halves: the caster chooses which one the
        # target casts (CR 709.3, CR 723.5) and answers with that half's name.
        "choices": [
            {
                "hand_index": i, "name": c.name,
                **(
                    {"faces": [
                        {"name": face.name, "mana_cost": face.mana_cost,
                         "oracle_text": face.oracle_text}
                        for face in face_cards(c)
                    ]}
                    if face_cards(c) else {}
                ),
            }
            for i, c in enumerate(target.hand)
        ],
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

    ``targets`` is absent for a mode that chooses nothing, and for every
    alternative of a ``choose_one`` asked inside a running resolution (CR
    608.2d — a nested "or", or a whole unmodal "A or B" ability such as
    Urborg's), which announces no targets at all.
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

    ``at_least`` is sent for the same reason, one bound over: a printed count
    is a floor as well ("return **two** Forests", Bull Elephant; "choose **the
    same number**", Cultural Exchange), the engine refuses an answer under it,
    and until this the client was told only the ceiling — so a person could
    confirm too few, be refused, and not know by how many. Zero for every
    prompt that prints no floor.
    """
    choice = choices[0]
    live = {id(perm) for perm in ctx.game.live_permanent_set_choices(choice)}
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "prompt": choice.data.get("prompt", ""),
        "up_to": int(choice.data.get("up_to", 1)),
        "at_least": int(choice.data.get("at_least", 0) or 0),
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


def _keep_slot_noun(described: dict) -> str:
    """The noun one keep slot printed, for the modal's label.

    The **narrowest** one: Global Ruin's five slots are "a land of each basic
    land type", so each is a land *and* one named type, and a label reading the
    card type alone told the player to keep "1 land, 1 land, 1 land, 1 land,
    1 land" while the engine refused any answer holding two Plains. A label
    decides nothing, but one that contradicts the check behind it leaves a
    refused answer unexplained. Cataclysm's slots name no subtype and read
    exactly as they did.
    """
    subtype = described.get("subtype_filter")
    if isinstance(subtype, str) and subtype:
        return display_type_word(subtype)
    return str(described.get("type_filter", "permanent"))


@prompt_renderer("keep_permanents")
def _keep_permanents(ctx: PromptContext, choices: list) -> dict:
    """Cataclysm and Limited Resources: which of this seat's own permanents
    survive, chosen as the effect resolves.

    The candidate list is re-derived through the engine's own pool rule rather
    than frozen when the prompt was armed, which is what the two permanent
    pickers beside it do and for their reason: the answer is checked against
    that same rule, so the list offered and the list accepted cannot disagree.

    ``keep_count`` is sent because the client cannot derive it. The *most* a
    seat may choose is the size of a maximum matching between their permanents
    and the printed slots (CR 609.3), which is a number only the engine can
    compute - two artifact creatures fill an artifact slot and a creature slot
    at once, where two plain artifacts fill one. ``slots`` rides along so the
    modal can say what the keeps *are*.

    ``keep_fewest`` is the other end of the range, and is there because one
    permanent may be chosen for several slots (the rulings of Cataclysm, Global
    Ruin and Planar Overlay all say so): a Tropical Island alone answers Forest
    and Island. Each slot carries ``need`` — how many of the seat's permanents
    must be chosen for it, zero where the seat holds none — and each candidate
    ``fills``, the slots it may stand for, so the modal can label a dual land
    with both its types and hold the confirm button until every slot is
    answered. The engine re-checks the answer either way.

    ``fate`` is sent only when the prompt carries one — Planar Overlay's
    "Return those lands to their owners' hands", where what the seat picks is
    what *leaves*. The modal words the choice from it, and the candidates are
    narrowed to permanents that fill some slot: under the default fate a land
    no slot names is still worth showing (it is about to be sacrificed), and
    under this one it is a card the player can click and never legally choose.
    """
    choice = choices[0]
    live = ctx.game.keep_choice_candidates(
        choice.player_index, choice.data.get("pool") or {}
    )
    slot_filters = ctx.game._keep_slot_filters(choice.data.get("slots"))
    fate = choice.data.get("fate")
    extra: dict = {}
    if fate is not None:
        extra["fate"] = fate
        live = [
            perm for perm in live
            if ctx.game._match_keeps([perm], slot_filters)
        ]
    printed = list(choice.data.get("slots") or ())
    needs = ctx.game.keep_slot_needs(live, printed)
    return {
        **extra,
        "player_seat": choice.player_index,
        "card_name": choice.data.get("reason", ""),
        "keep_count": len(ctx.game._match_keeps(live, slot_filters)),
        "keep_fewest": len(ctx.game.fewest_keeps(live, printed)),
        "slots": [
            {
                "count": int(slot.get("count", 0)),
                "type": _keep_slot_noun(slot.get("filter") or {}),
                "need": need,
            }
            for slot, (_described, need) in zip(printed, needs)
        ],
        "candidates": [
            {
                "seat": choice.player_index,
                "index": index,
                "id": ctx.game.permanent_id_of(perm),
                "name": perm.card.name,
                "fills": ctx.game.keep_slots_answered_by(perm, printed),
            }
            for index, perm in enumerate(ctx.game.players[choice.player_index].battlefield)
            if any(perm is candidate for candidate in live)
        ],
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


@prompt_renderer("madness_cast")
def _madness_cast(ctx: PromptContext, choices: list) -> dict:
    """Madness (CR 702.35a): the card just discarded is in exile, and its
    owner may cast it now for its madness cost or put it into their graveyard.

    The cast is the client's ordinary cast dialog, sent as
    ``madness_cast_confirm`` with ``accept: true`` and the cast's fields;
    declining is the same action with ``accept: false``. The card's ``ways``
    in the exile zone payload carry the price, because the offer is a stored
    permission while it stands (``engine/madness.py``). Mana is paid by
    tapping first: ``tap`` and ``activate`` answer this prompt too."""
    choice = choices[0]
    card = choice.data.get("_card")
    exile = ctx.game.players[choice.player_index].exile
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "cost": choice.data.get("cost", ""),
        # Where the card is, so the client can open its cast dialog on it.
        "exile_index": next(
            (index for index, held in enumerate(exile) if held is card), None
        ),
        "prompt": (
            f"Cast {choice.data.get('card_name', 'the exiled card')} for its "
            f"madness cost {choice.data.get('cost', '')}, or put it into your "
            f"graveyard?"
        ),
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
