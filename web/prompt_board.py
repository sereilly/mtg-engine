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

from collections import Counter

from engine.faces import face_cards
from engine.grammar.vocabulary import display_type_word
from engine.trigger_order import live_trigger_indices, trigger_card

from .prompt_registry import PromptContext, prompt_renderer


def _stack_place(stack_index: int) -> str:
    """Where a stack object is, topmost being 0, in the words the stack is
    read in."""
    if stack_index <= 0:
        return "top of the stack"
    ordinal = stack_index + 1
    if 10 <= ordinal % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(ordinal % 10, "th")
    return f"{ordinal}{suffix} from the top"


def _told_apart_on_the_stack(entries: list[dict]) -> list[dict]:
    """*entries* with each ``stack`` candidate whose name another one shares
    named with its place on the stack as well.

    ``stack_targets.stack_object_label`` says whose a spell is and whether it
    is a copy, which tells most look-alikes apart; two Shocks one player cast
    still read "P2's Shock" twice, and the person choosing between them has
    the stack in front of them, so the prompt says which is which by where
    each sits — now, as it is shown (``stack_index``, topmost 0). Every other
    entry, and every unique name, is left as it was."""
    names = Counter(
        entry.get("name") for entry in entries
        if entry.get("kind") == "stack" and isinstance(entry.get("stack_index"), int)
    )
    for entry in entries:
        if (
            entry.get("kind") == "stack"
            and isinstance(entry.get("stack_index"), int)
            and names[entry.get("name")] > 1
        ):
            entry["name"] = f"{entry.get('name')} ({_stack_place(entry['stack_index'])})"
    return entries


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
        entry = {
            "kind": target.get("kind", "permanent"),
            "seat": target.get("seat"),
            "index": target.get("permanent_index"),
            "id": target.get("permanent_id"),
            "name": target.get("name"),
        }
        # A roles announcement ("target creature you control and target
        # creature an opponent controls", Chromeshell Crab): which role this
        # candidate may fill. Only on such a prompt.
        if target.get("role") is not None:
            entry["role"] = target["role"]
        candidates.append(entry)
    payload = {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": _told_apart_on_the_stack(candidates),
    }
    # A seat that does not control the trigger and is asked for its target
    # anyway: "Whenever a creature enters, **that creature's controller** may
    # have target creature of their choice get -3/-3" (Death Match). The
    # prompt said "Death Match: its triggered ability needs a target" to a
    # player who controls no Death Match. Who controls it and what it says
    # ride beside the candidates — only then, so every other trigger's
    # payload is the one it always was.
    trigger = choice.data.get("_trigger_item")
    controller = getattr(trigger, "caster_index", None)
    if isinstance(controller, int) and controller != choice.player_index:
        payload["controller_seat"] = controller
        payload["controller_name"] = ctx.game.players[controller].name
    # What the trigger says, for every chooser: "Confusion in the Ranks: its
    # triggered ability needs a target" told the player nothing about which
    # permanent it wanted ("target permanent another player controls that
    # shares a card type with it"). The printed line is public (CR 113.2),
    # and the client reads it for the sentence above the candidates.
    if getattr(trigger, "ability_text", None):
        payload["ability_text"] = trigger.ability_text
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
    # "…exchange control of target creature you control and target creature
    # an opponent controls" (Chromeshell Crab's trigger): one answer per role,
    # in this order, sent as ``target_permanent_ids``; each candidate says its
    # ``role``. Absent on every prompt that is not a roles announcement.
    if choice.data.get("roles"):
        payload["roles"] = [dict(role) for role in choice.data["roles"]]
        # The printed line, so the dialog can say what each role is ("target
        # creature **you control** and target creature **an opponent
        # controls**"): a role carries its noun (``kind``) and nothing of the
        # narrowing the candidates were enumerated under.
        if getattr(trigger, "ability_text", None):
            payload["ability_text"] = trigger.ability_text
    # "Exile up to two target cards **from a single graveyard**" (Gravegouger):
    # several ``graveyard`` candidates, all of one answer in one pile. The
    # client keeps a selection inside the pile its first card came from and
    # sends ``target_seat`` with ``graveyard_indices`` — the flag the cast
    # picker's spec already carries for the same sentence on a spell
    # (``target_descriptions.SINGLE_GRAVEYARD``). Absent everywhere else.
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


@prompt_renderer("target_group_order")
def _target_group_order(ctx: PromptContext, choices: list) -> dict:
    """Kaboom!'s ruling: the spell's targets, each player's group in turn
    order, for the caster to order **within** each group ("You choose the
    relative order of targets within that group").

    Each entry keeps its ``index`` into the offered list, which is what the
    answer (``target_group_order_confirm``'s ``target_order``) is written in,
    and its ``group`` (0 is the active player's): an order that moves a
    target out of its group is refused. ``id`` is a planeswalker's permanent,
    for the board to point at; a player has none and carries its ``seat``.
    The order_triggers prompt's widget answers the same shape — a list to put
    in order — within each group.
    """
    choice = choices[0]
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "targets": [
            {
                "index": index,
                "name": entry.get("name", ""),
                "seat": entry.get("seat"),
                "id": entry.get("permanent_id"),
                "group": entry.get("group"),
            }
            for index, entry in enumerate(choice.data.get("targets") or ())
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

    ``current_target`` is the candidate the copy is aimed at now (the
    original's target) — what the "keep" answer (``accept: false``) leaves it
    on — and ``copy_number`` / ``copy_count`` say which of a storm's copies
    this is (2022-12-08: "You can make different choices for each copy").
    Each is sent only when there is one to send.
    """
    choice = choices[0]

    def entry(target: dict) -> dict:
        return {
            "kind": target.get("kind"),
            "seat": target.get("seat"),
            "index": target.get("index"),
            "id": target.get("permanent_id"),
            "name": target.get("name"),
        }

    payload = {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "candidates": [entry(target) for target in choice.data.get("targets") or ()],
        "remaining": sum(1 for c in choices if c.player_index == choice.player_index),
    }
    current = ctx.game.copy_spell_target_current(choice)
    if current is not None:
        payload["current_target"] = entry(current)
    if choice.data.get("copy_count"):
        payload["copy_number"] = int(choice.data["copy_number"])
        payload["copy_count"] = int(choice.data["copy_count"])
    return payload


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
            "name": perm.effective_card.name,
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
            "name": perm.effective_card.name,
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
    """One round of Balance's three — lands, then cards in hand, then
    creatures, each counted as it starts (``Game.begin_balance``).

    The round's permanents are the engine's own list,
    ``Game.balance_candidates``, which is what the answer is checked against:
    layer 4's answer (CR 613.1d), so an animated Mishra's Factory is offered
    with the lands in the first round and with the creatures in the last, an
    Opalescence enchantment with the creatures, and a Clone that copied a
    Forest with the lands. Each is described as it is
    (``describe_permanent``), not as printed. The other round's list is empty:
    only one round is ever being answered.
    """
    choice = choices[0]
    seat = choice.player_index
    plan = choice.data["plan"]
    stage = choice.data.get("stage")
    player = ctx.game.players[seat]

    def offered(round_name: str) -> list:
        if stage != round_name:
            return []
        return [
            {"index": slot, "id": perm.permanent_id, **ctx.describe_permanent(perm)}
            for slot, perm in ctx.game.balance_candidates(seat, round_name)
        ]

    return {
        "player_seat": seat,
        "stage": stage,
        "lands_to_sacrifice": plan["lands"],
        "creatures_to_sacrifice": plan["creatures"],
        "cards_to_discard": plan["hand"],
        "lands": offered("lands"),
        "creatures": offered("creatures"),
        "hand": [ctx.owned_card(card, player) for card in player.hand],
    }


@prompt_renderer("sacrifice")
def _sacrifice(ctx: PromptContext, choices: list) -> dict:
    """Every eligible permanent, so the board can list and highlight them."""
    choice = choices[0]
    state = ctx.game._sacrifice_prompt(choice)
    # What is being sacrificed, where the filter is one card type or subtype
    # and nothing else: Death Cloud's two rounds ("sacrifices X creatures …,
    # then sacrifices X lands") both read "Choose 2 permanent(s)". A filter
    # saying more keeps the generic word — a noun that drops a narrowing
    # would describe more than the highlighted candidates.
    described = choice.data.get("filter") or {}
    noun = (
        {"noun": _keep_slot_noun(described)}
        if described and set(described) <= {"type_filter", "subtype_filter"}
        else {}
    )
    return {
        "player_seat": choice.player_index,
        **noun,
        "count": state["count"],
        # Whether the count is owed or offered. "Sacrifice any number of
        # untapped Forests" (Wood Elemental) is answered by any subset, none
        # included, and a picker that could only confirm at exactly the ceiling
        # would make the offer a demand.
        "up_to": state["up_to"],
        "reason": state["reason"],
        # Each described as it is (CR 613): an animated land in a "sacrifice
        # a creature" list is drawn as the creature it is. ``id`` is the stable
        # address `sacrifice_permanent_ids` answers with; ``index`` stays for
        # the client that still answers by slot.
        "permanents": [
            {"index": i, **ctx.describe_permanent(perm), "id": perm.permanent_id}
            for i in state["valid_indices"]
            if (perm := ctx.game.permanent_at(choice.player_index, i)) is not None
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
                "name": perm.effective_card.name,
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
    """Cuombajj Witches: "any target", so every player face and every creature.

    Each creature carries its ``id``, the address ``opponent_damage_choose``
    answers with (``target_permanent_id``); ``index`` and ``key`` are where it
    is drawn on the board this payload describes, not how it is named back."""
    data = choices[0].data
    targets: list[dict] = [
        {"kind": "player", "seat": seat} for seat in range(len(ctx.game.players))
    ]
    for seat in range(len(ctx.game.players)):
        for perm in ctx.game.controlled_by(seat):
            if perm.is_creature:
                idx = ctx.game.battlefield_index_of(perm)
                targets.append(
                    {"kind": "permanent", "seat": seat, "index": idx,
                     "id": perm.permanent_id,
                     "key": f"{seat}-{idx}", "name": perm.effective_card.name}
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
    payload = {
        "player_seat": choice.player_index,
        "card_name": data["card_name"],
        "modes": modes,
    }
    # What the choice is *for*, where the alternatives say it and their labels
    # alone do not: Fatespinner's "draw step / main phase / combat phase" are
    # the step or phase the chooser skips this turn (``skip_next_step`` /
    # ``skip_next_phase`` alternatives), and "pick a mode" said none of that.
    # ``title`` is the same answer for the panel's heading, which said
    # "Choose one" over it — a heading that names the choice's form (one of
    # several) rather than what is being chosen.
    kinds = {getattr(mode, "kind", None) for mode in data.get("_modes") or ()}
    if kinds and kinds <= {"skip_next_step", "skip_next_phase"}:
        payload["question"] = "Choose the step or phase you skip this turn."
        payload["title"] = "skip a step or phase"
    # …and whose ability makes them choose, when it is not theirs (CR 700.2e's
    # shape on a trigger: "that player chooses", Fatespinner in its opponent's
    # upkeep).
    context = data.get("_context")
    caster = getattr(context, "caster", None)
    controller = next(
        (seat for seat, player in enumerate(ctx.game.players) if player is caster), None,
    )
    if controller is not None and controller != choice.player_index:
        payload["controller_name"] = caster.name
    return payload


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
                "name": perm.effective_card.name,
                "loyalty": int(perm.metadata.get("loyalty_counters", 0)),
            }
            for seat, player in enumerate(ctx.game.players)
            for index, perm in enumerate(player.battlefield)
            if id(perm) in live
        ],
    }


@prompt_renderer("counter_distribution")
def _counter_distribution(ctx: PromptContext, choices: list) -> dict:
    """"…you may move any number of +1/+1 counters from this creature onto
    other creatures." (Forgotten Ancient.) How many counters, and onto which
    of the creatures the printed noun phrase names — the seat may split them
    among several, or move none.

    ``maximum`` is what the source still holds, read now; ``candidates`` come
    from the engine's own liveness rule (``live_counter_distribution``), so the
    list offered and the list the answer is held to are one rule. ``seat`` /
    ``index`` ride beside the stable ``id`` for the canvas, which addresses a
    card by its slot; the answer names each creature by id with its amount
    (``divided_targets``), and the engine refuses a total over ``maximum``.
    """
    choice = choices[0]
    candidates = []
    for perm in ctx.game.live_counter_distribution(choice):
        candidates.append({
            "seat": ctx.game.controller_index_of(perm),
            "index": ctx.game.battlefield_index_of(perm),
            "id": ctx.game.permanent_id_of(perm),
            "name": perm.effective_card.name,
        })
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "counter": choice.data.get("counter", "+1/+1"),
        "source_id": choice.data.get("source_id"),
        "maximum": ctx.game.counter_distribution_maximum(choice),
        "candidates": candidates,
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
                "name": perm.effective_card.name,
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
                "name": perm.effective_card.name,
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
    live = ctx.game.keep_candidates_of(choice)
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
    # Sundering Titan's "a land" reaches every battlefield (``DESTROY_CHOSEN``
    # with ``every_battlefield``): each candidate carries its own seat.
    seats = (
        range(len(ctx.game.players)) if choice.data.get("every_battlefield")
        else (choice.player_index,)
    )
    if choice.data.get("every_battlefield"):
        extra["every_battlefield"] = True
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
                "seat": seat,
                "index": index,
                "id": ctx.game.permanent_id_of(perm),
                "name": perm.effective_card.name,
                "fills": ctx.game.keep_slots_answered_by(perm, printed),
            }
            for seat in seats
            for index, perm in enumerate(ctx.game.players[seat].battlefield)
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


@prompt_renderer("copy_cast")
def _copy_cast(ctx: PromptContext, choices: list) -> dict:
    """CR 707.12: "You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost." (Isochron Scepter.)

    The copy does not exist yet — it is made in exile when the offer is taken
    (``engine/copy_casts.py``) — so the client opens its ordinary cast dialog
    on **the exiled card it copies** (``exile_seat`` / ``exile_index``) for the
    targets, X and mode, and sends them as ``copy_cast_confirm`` with
    ``accept: true``; ``accept: false`` declines, and no copy is made. The
    mana cost is waived; a tap and a mana ability still answer this prompt,
    for an additional cost that wants mana."""
    choice = choices[0]
    card = choice.data.get("_card")
    where = next(
        (
            (seat, index)
            for seat, player in enumerate(ctx.game.players)
            for index, held in enumerate(player.exile)
            if held is card
        ),
        (None, None),
    )
    name = choice.data.get("card_name", "the exiled card")
    # "…you may copy **a** card exiled with this artifact" (Panoptic Mirror):
    # with two imprinted, the offers are queued card by card and the first
    # taken is the one copy (``copy_casts.arm_copy_cast``'s ``one_of``). A
    # person picks the second card by declining the first, so the offer names
    # the cards still to come — without it nothing says a decline is not the
    # end of the choice.
    one_of = choice.data.get("_one_of")
    then_offers = [
        other.data.get("card_name", "")
        for other in choices[1:]
        if one_of is not None and other.data.get("_one_of") is one_of
    ]
    # "…copy an instant or sorcery card **in it**" (Reversal of Fortune): the
    # card copied is in a revealed hand rather than in exile, so its place is
    # that hand's — public since the reveal (CR 701.20b), and the slot the
    # client opens its cast dialog on. Absent for every exiled offer. The
    # card itself rides along (``card``), because an opponent's hand is
    # hidden in every player's view of it and the dialog needs a card to
    # show; its targets come from ``card_target_spec`` by name, as an exiled
    # card of another seat's does.
    hand_of = choice.data.get("_from_hand_of")
    hand_place: dict = {}
    if isinstance(hand_of, int) and 0 <= hand_of < len(ctx.game.players):
        hand_place = {
            "card": ctx.serialize_card(card) if card is not None else None,
            "hand_seat": hand_of,
            "hand_index": next(
                (
                    index for index, held in
                    enumerate(ctx.game.players[hand_of].hand) if held is card
                ),
                None,
            ),
        }
    return {
        "player_seat": choice.player_index,
        "card_name": choice.data.get("card_name", ""),
        "source_name": choice.data.get("source_name", ""),
        **({"then_offers": then_offers} if then_offers else {}),
        "exile_seat": where[0],
        "exile_index": where[1],
        **hand_place,
        "prompt": (
            f"Cast a copy of {name} without paying its mana cost "
            f"({choice.data.get('source_name', '')})?"
        ),
    }


@prompt_renderer("retarget_choice")
def _retarget_choice(ctx: PromptContext, choices: list) -> dict:
    """Deflection: "Change the target of target spell with a single target."

    The candidates are re-derived through the engine's own liveness test, so a
    creature that has died or a player who has left since the prompt was armed
    is not offered — and the position each option carries is its position in the
    armed list, which is what the answer names.

    A permanent also carries its ``id`` and its controller's ``seat``. Without
    them two options could read the same — two face-down creatures are both
    "Face-down creature" (CR 708.2), and a Goblin Grappler on each side is two
    "Goblin Grappler"s — and the person answering could not tell which is
    theirs (Legions' post-promotion pass: Willbender re-aiming a Shock between
    a Dermoplasm and a Willbender, both face down). Both are public: the id is
    on the battlefield payload, and who controls a permanent is in the open.
    The client names a face-down option from its own ``hidden_card`` (CR
    708.5), so only the controller learns what it is."""
    choice = choices[0]
    data = choice.data
    options = list(data.get("options") or ())
    return {
        "card_name": data.get("card_name", ""),
        "prompt": data.get("prompt", "Choose a new target."),
        "options": _told_apart_on_the_stack([
            _retarget_option(ctx, options[position], position)
            for position in ctx.game.live_retarget_choices(choice)
        ]),
    }


def _retarget_option(ctx: PromptContext, option: dict, position: int) -> dict:
    """One ``retarget_choice`` option as the client reads it: its position,
    name and kind, and — for a permanent still on the battlefield — its id and
    the seat that controls it."""
    out = {
        "index": position,
        "name": option.get("name", ""),
        "kind": option.get("kind", ""),
    }
    if option.get("kind") == "permanent":
        permanent = ctx.game.permanent_by_id(option.get("permanent_id"))
        if permanent is not None:
            out["id"] = permanent.permanent_id
            out["seat"] = ctx.game.controller_index_of(permanent)
    # A spell (Psychic Battle's counterspell, Hindering Touch's storm copy):
    # where it is on the stack as the client is shown it — ``stack_index``,
    # topmost 0, the convention ``trigger_target``'s spell candidates use —
    # and whose it is, so two of one name can be told apart and pointed at.
    if option.get("kind") == "stack":
        item = option.get("_stack_item")
        stack = ctx.game.stack
        position = next(
            (place for place, waiting in enumerate(stack) if waiting is item), None
        )
        if position is not None:
            out["stack_index"] = len(stack) - 1 - position
            out["seat"] = getattr(item, "caster_index", None)
    return out
