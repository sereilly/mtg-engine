"""Token and emblem creation (CR 111, CR 114).

A token is an **object the game creates** (CR 111.1): ``create_token`` makes
one from the characteristics its payload carries (``engine/tokens.py``'s
``make_token_card``), ``create_copy_token`` one that is a copy of a permanent
(``Game.create_token_copy``, because CR 613 layer 1 is applied in one module),
and both ask :func:`token_recipient_seats` who creates them (CR 111.2: each
seat that does owns and controls what it creates). An emblem (CR 114) is the
command-zone object ``create_emblem`` gives its controller.

The handler twin of ``engine/grammar/lowering/tokens.py``. Split out of
``board_misc.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import CardDefinition, Permanent
from ..oracle_types import EVENT_SUBJECT_LAST_KNOWN, LAST_TARGET_CONTROLLER
from ..tokens import (CHOSEN_TOKEN_RECORDS, CREATED_TOKEN_RESULT_KEY,
                      CREATED_TOKENS_RESULT_KEY, CREATED_WITH_PERMANENT_ID,
                      default_token_name, make_token_card)
from ._amounts import evaluate_count, per_recipient_amount, resolve_amount
from ._chosen import count_spec_in_resolution
from ._targets import one_recorded_permanent_id, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("create_emblem")
def create_emblem(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You get an emblem with "<ability>"." (CR 114.2.) The emblem lives on
    its owner's ``emblems`` list — the engine's command zone — as a dict plus a
    detached Permanent whose card carries the text, which is what lets the
    trigger machinery fire it like any permanent's ability (CR 114.4)."""
    caster = context.caster
    text = str(instruction.payload.get("text", ""))
    name = f"{context.card.name} Emblem"
    emblem_card = CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Emblem",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )
    caster.emblems.append({
        "name": name,
        "oracle_text": text,
        "source_name": context.card.name,
        "_permanent": Permanent(card=emblem_card),
    })
    game.log.append(f'{caster.name} gets an emblem: "{text}"')
    return True, "resolved"


@effect_handler("create_copy_token")
def create_copy_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Create a token that's a copy of target creature you control."
    (Sublime Epiphany.)

    What a token is and what a copy is are two rules, and both live one layer
    down: ``Game.create_token_copy`` performs them, because CR 613 layer 1 is
    applied in exactly one module and this handler is not it.

    What is decided *here* is the printed phrase. The filter is enforced rather
    than trusted, and the target is strict (CR 608.2b): a target that has left,
    or that no longer answers "creature you control", makes no token at all.
    There is nothing sensible to fall back to — a copy of some other creature is
    not a smaller version of this effect, it is a different one.
    """
    from ..subject_filters import subject_matches

    caster = context.caster
    controller_index = game.players.index(caster)
    described = dict(instruction.payload.get("filter") or {})

    def _legal(perm) -> bool:
        return not described or subject_matches(
            game, perm, described,
            observer=controller_index, source=context.source_permanent,
        )

    # "An opponent chooses target creature they control. Create a token that's
    # a copy of **that creature**." (Echo Chamber.) The permanent an earlier
    # step of this same resolution recorded, read through the one channel every
    # ``permanents_from`` reader goes through — the pick was made by another
    # seat as this ability resolved, so there is no target on the stack to
    # resolve and no legality to re-check (CR 608.2b is about targets).
    recorded_key = instruction.payload.get("permanents_from")
    if instruction.payload.get("copied") == "loop_object":
        # "For each creature token on the battlefield, its controller creates a
        # token that's a copy of **that creature**." (Parallel Evolution.) The
        # permanent the board loop is on (``for_each`` binds it per iteration
        # and fixed the set before the first, so a copy made here is never
        # itself copied). Read live: it is on the battlefield, and its copiable
        # values (CR 707.2) are what ``create_token_copy`` takes — including
        # the copy effect a token copy already carries.
        source = context.iteration_target
        if getattr(source, "permanent_id", None) is None or not game.is_on_battlefield(source):
            game.log.append(f"{context.card.name}: the creature it names is gone")
            return True, "resolved"
    elif instruction.payload.get("copied") == "event_subject":
        # "Whenever a nontoken creature enters, its controller creates a token
        # that's a copy of **that creature**." (Dual Nature.) The object the
        # trigger's event was about, by the id the entry seam froze — and when
        # it has left by resolution, CR 608.2h's last-known information: the
        # effect uses the object as it last existed on the battlefield, which
        # the same seam froze beside the id. Nothing is targeted (CR 603.3d), so
        # there is no legality to re-check; the condition's own filter already
        # admitted this object.
        tctx = context.trigger_context or {}
        source = game.permanent_by_id(tctx.get("event_subject_permanent_id"))
        if source is None:
            last_known = tctx.get(EVENT_SUBJECT_LAST_KNOWN)
            source = last_known if isinstance(last_known, Permanent) else None
        if source is None:
            game.log.append(f"{context.card.name}: no creature to copy")
            return True, "resolved"
    elif recorded_key is not None:
        found = one_recorded_permanent_id(context, recorded_key)
        source = game.permanent_by_id(found) if found is not None else None
        if source is None or not game.is_on_battlefield(source):
            # The chosen creature has left. CR 608.2 does as much as it can,
            # which here is nothing — a copy of some other creature is a
            # different effect.
            game.log.append(f"{context.card.name}: the chosen creature is gone")
            return True, "resolved"
    else:
        # No ``fallback_players``: a scan for *some* legal creature is what makes
        # an illegal choice quietly succeed, and CR 608.2b says an illegal target
        # makes that part of the spell do nothing. Copying a different creature
        # is not a smaller version of this effect.
        source = resolve_target_permanent(
            game, context, fallback_on_invalid_choice=False, predicate=_legal,
        )
        if source is None:
            game.log.append(f"{context.card.name}: no legal creature to copy")
            return True, "resolved"

    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    # "**Its controller** creates …" (Dual Nature): CR 111.2 makes whoever
    # creates the token its owner and controller, and that seat is the frozen
    # one the lowering named — the same reader ``create_token`` asks. One seat
    # per token made, so a count over several recipients is a flat list.
    makers = [
        seat
        for seat in token_recipient_seats(
            game, instruction.payload, context, controller_index,
        )
        for _ in range(max(0, count))
    ]
    for seat in makers:
        token = game.create_token_copy(seat, source)
        # "When this enchantment leaves the battlefield, exile **the token**."
        # (Dance of Many.) Which permanent made this one, stamped for the same
        # reason `create_token` beside it stamps it: the sentences that name
        # the token belong to *other* abilities of the same permanent, fired
        # turns after the resolution that made it, so the resolution scratchpad
        # is long gone and nothing about the token itself records its maker.
        if context.source_permanent is not None:
            token.metadata[CREATED_WITH_PERMANENT_ID] = (
                context.source_permanent.permanent_id
            )
        # "…**That token** gains haste until end of turn." (Echo Chamber.) The
        # permanent this step made, for the sentences behind it in the same
        # resolution — written under the key ``create_token`` beside this one
        # has written since Stangg, and for that handler's stated reason: a
        # token is a new object with a fresh id (CR 400.7), so nothing about it
        # can be looked up afterwards. The last one when several are made, which
        # is the same reading, and the lowering admits the singular phrase only
        # behind a maker.
        context.results[CREATED_TOKEN_RESULT_KEY] = token.permanent_id
        game.log.append(
            f"{context.card.name} created a token copy of {source.card.name}"
        )
    return True, "resolved"


def token_recipient_seats(
    game: Game, payload: dict, context: OracleExecutionContext, controller_index: int,
) -> list[int]:
    """The seats that create the tokens *payload* describes (CR 111.2: each
    becomes the owner and controller of what it creates).

    Shared by ``create_token`` and ``create_copy_token``, because who creates a
    token is not a characteristic of it — a described token and a copied one
    answer the same question the same way, and the lowering writes it with one
    stamp (``lowering/tokens._stamp_token_recipient``). It was inline in
    ``create_token`` until Dual Nature printed a recipient in front of a copy.

    A seat that has left the game gets none (CR 800.4a).
    """
    # "**Each opponent** creates …" (Pursued Whale). Who gets the tokens, which
    # for every earlier token card is the effect's own controller.
    recipients = [controller_index]
    who = payload.get("recipient_players")
    if who == "each_opponent":
        recipients = list(game.opponents_of(controller_index))
    elif who in ("target_opponent", "that_player", "controller"):
        # "**Target** opponent creates …" (Phantasmal Sphere, Phelddagrif) and
        # "…**that player** creates …" (Mogg Infestation). One chosen seat
        # rather than every opponent, read off the context rather than guessed:
        # with no target chosen there is nobody the card names, and creating the
        # token for the controller instead would be the opposite of what it
        # says. A target that has left the game makes no token (CR 800.4a).
        #
        # One branch for both words because the seat is found the same way — the
        # difference between them is which seats the *picker* offers, which is
        # the ``targets`` description the lowering writes, not this lookup. This
        # used to be two branches, the second of them unreachable behind the
        # first, so the ``lost`` check it carried was never run.
        # "…**the player** creates a 1/1 green Saproling creature token."
        # (Greener Pastures.) Under a trigger that chose nobody the seat is the
        # one the firing event was about, frozen by the fire site (CR 603.10) —
        # ``context.target`` there is whatever the resolution was carrying,
        # which for an each-player upkeep is the wrong player half the time.
        # The key is stamped by the lowering only where an event really froze
        # a seat, so a *spell* printing the same two words (Mogg Infestation)
        # still reads its own target below.
        record = payload.get("recipient_seat_record")
        iteration_record = payload.get("recipient_iteration_seat")
        if payload.get("recipient_loop_controller"):
            # "For each creature token on the battlefield, **its controller**
            # creates …" (Parallel Evolution.) The controller of the permanent
            # the board loop is on, read live through the control seam — the
            # loop's object is still on the battlefield (CR 110.2). Outside a
            # loop there is no such permanent and nobody gets a token.
            iterated = context.iteration_target
            seat = (
                game.controller_index_of(iterated)
                if getattr(iterated, "permanent_id", None) is not None
                and game.is_on_battlefield(iterated)
                else None
            )
            recipients = (
                [seat]
                if isinstance(seat, int) and not game.players[seat].lost
                else []
            )
        elif iteration_record is not None:
            # "For each creature destroyed this way, **its controller** creates
            # a 1/1 white Spirit creature token with flying." (March of Souls.)
            # The seat the sweep froze about the object *this iteration* is on
            # (CR 608.2h: last known information — the creature is a card in a
            # graveyard by now and controlled by nobody). ``for_each`` resolves
            # the per-object record to this object's entry before the step
            # runs, so the lookup is by the record's name and never by the
            # object — ``draw_target_cards`` and ``gain_life`` read the same
            # binding for the same two words.
            #
            # No entry means no loop is running or the sweep recorded nothing
            # about this object, and nobody gets a token: a seat guessed here
            # is a player the card never named.
            seat = context.iteration_seats.get(str(iteration_record))
            recipients = (
                [seat]
                if isinstance(seat, int)
                and 0 <= seat < len(game.players)
                and not game.players[seat].lost
                else []
            )
        elif record is not None:
            seat = (context.trigger_context or {}).get(str(record))
            recipients = (
                [seat]
                if isinstance(seat, int)
                and 0 <= seat < len(game.players)
                and not game.players[seat].lost
                else []
            )
        elif who == "controller":
            # "**Its controller** creates …" (Dual Nature) is only ever lowered
            # with the frozen seat beside it; without one it names nobody, and
            # the resolution's target is not a seat this sentence ever chose.
            recipients = []
        else:
            chosen = context.target
            recipients = (
                [game.players.index(chosen)]
                if chosen is not None and chosen in game.players
                and not chosen.lost
                else []
            )
    elif who == "each_player":
        recipients = [i for i, p in enumerate(game.players) if not p.lost]
    return recipients


@effect_handler("create_token")
def create_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Generic token creation: payload carries name / P/T / type_line / colors /
    keywords / count ("x" resolves to the cast's X). Tokens are stamped
    ``is_token`` so they cease to exist instead of hitting the graveyard
    (CR 704.5d / 111.7)."""
    caster = context.caster
    card = context.card
    payload = instruction.payload
    controller_index = game.players.index(caster)
    # "Its controller creates …" (Angelic Ascension, Secure the Scene): the
    # token goes to the controller the exile step of this same resolution
    # recorded. No record means nothing was exiled — the referent never
    # existed, so no token either (CR 608.2b's "does as much as it can" cuts
    # both ways: there is no controller to hand a token to).
    if payload.get("recipient") == LAST_TARGET_CONTROLLER:
        recorded = context.results.get(LAST_TARGET_CONTROLLER)
        if not isinstance(recorded, int):
            game.log.append(f"{card.name}: nothing was exiled, so no token is created")
            return True, "resolved"
        controller_index = recorded
    # A predefined token (a Treasure) carries its own printed text and has no
    # P/T at all — CR 208.1 gives P/T to creatures, and 0/0 would be a creature
    # card that dies the moment anything animates it.
    printed_power = payload.get("power")
    printed_toughness = payload.get("toughness")
    # "Create an **X/X** … token, where X is the number of …" (Experimental
    # Overload). The where-clause's count is already resolved into the context's
    # X by the time this runs, so both halves read the one number. Taken **now**
    # and then fixed onto the token's card: a token has no
    # characteristic-defining ability, so a card later leaving the graveyard
    # does not shrink it (CR 608.2 counts at resolution).
    if printed_power == "x" or printed_toughness == "x":
        counted = max(0, int(context.x_value or 0))
        printed_power = counted if printed_power == "x" else printed_power
        printed_toughness = counted if printed_toughness == "x" else printed_toughness
    # "Create a black Spirit creature token. **Its power is equal to that
    # creature's power and its toughness is equal to that creature's
    # toughness.**" (Broken Visage.) Each half names a scratchpad key an earlier
    # step of this same resolution wrote — the destroy froze both numbers about
    # the creature it was aimed at, because by now that creature is a card in a
    # graveyard with no computed characteristics at all (CR 613.1).
    #
    # A key nothing wrote reads as zero, and a 0/0 creature token dies to
    # CR 704.5a the moment it arrives. That is the honest outcome and not a
    # silent one: the lowering refuses the sentence unless a step of the effect
    # declares the record, so the only way to reach it is a target that was
    # already gone when the spell resolved (CR 608.2b), where nothing should be
    # created anyway.
    for key, field in (("power_from", "power"), ("toughness_from", "toughness")):
        recorded = payload.get(key)
        if recorded is None:
            continue
        value = max(0, int(context.results.get(recorded, 0) or 0))
        if field == "power":
            printed_power = value
        else:
            printed_toughness = value
    token_name = str(payload.get("name", "Token"))
    type_line = str(payload.get("type_line", "Creature — Token"))
    colors = tuple(payload.get("colors") or ())
    # "Create a 2/2 creature token **of the chosen color and type**."
    # (Volrath's Laboratory.) CR 614.1c's choice, made as *this* permanent
    # entered and recorded on it — so the characteristics come off the source,
    # under the same metadata keys `engine/enter_effects.py` writes and
    # `subject_filters` reads. The token's CR 111.4 name follows the subtype,
    # which is why the lowering leaves the name empty rather than rendering one.
    #
    # A record that is not there is not a token to build: the colour would come
    # out colourless and the subtype missing, which is a strictly different
    # token arriving silently. The instruction fails instead — the honest
    # direction, and reachable only from an ability whose source is no longer
    # the permanent that made the choice.
    from_chosen = payload.get("from_chosen") or ()
    if from_chosen:
        source = context.source_permanent
        if source is None:
            return False, "no permanent made the choice this token is built from"
        for characteristic in from_chosen:
            key = CHOSEN_TOKEN_RECORDS.get(str(characteristic))
            recorded = None if key is None else source.metadata.get(key)
            if not recorded:
                return False, f"nothing was chosen for the token's {characteristic}"
            if characteristic == "color":
                colors = (str(recorded).upper()[:1],)
            else:
                subtype = str(recorded).strip().title()
                type_line = f"Creature — {subtype}"
                token_name = default_token_name((subtype.lower(),))
    # ``*`` is a P/T the token's own CR 604.3 ability defines (Saproling Burst's
    # Saproling), carried through as a printed */* creature card carries it and
    # recomputed once the token is on the battlefield; every other value is a
    # number.
    token_card = make_token_card(
        token_name,
        None if printed_power is None
        else "*" if printed_power == "*" else int(printed_power),
        None if printed_toughness is None
        else "*" if printed_toughness == "*" else int(printed_toughness),
        type_line,
        colors=colors,
        keywords=tuple(payload.get("keywords") or ()),
        oracle_text=payload.get("oracle_text"),
        image_source=card,
    )
    # "that many" — a delayed attack trigger's batch count (Basri Ket's −2),
    # carried in the firing event's trigger context.
    raw_count = payload.get("count", 1)
    if raw_count == "trigger_count" and payload.get("amount_from_trigger") is not None:
        # "Whenever this creature is dealt damage, … create **that many** …
        # tokens." (Saber Ants, Druid's Call.) The firing event's own number,
        # out of the context its fire site froze (CR 603.10) — the channel
        # `add_counter_to_self` reads for Light of Promise, and never the
        # scratchpad, which for a sentence with no earlier step of its own is
        # a key nothing writes.
        count = int(
            (context.trigger_context or {}).get(
                str(payload["amount_from_trigger"]), 0
            ) or 0
        )
    elif raw_count == "trigger_count":
        tctx = context.trigger_context or {}
        count = int(tctx.get("trigger_count", context.results.get("trigger_count", 0)))
    elif isinstance(raw_count, dict) and "source_record" in raw_count:
        # "…for each time it regenerated this turn" (Spiny Starfish). A record
        # on the permanent whose ability this is, not a game-wide tally — so it
        # is read off the source rather than off the game, and a resolution with
        # no source permanent makes nothing rather than falling back to one.
        source = context.source_permanent
        count = (
            0 if source is None
            else int(source.metadata.get(str(raw_count["source_record"]), 0) or 0)
        )
    elif isinstance(raw_count, dict) and "dead_counters" in raw_count:
        # "…for each fungus counter on that creature" (Sporogenesis). The
        # counters the dying creature carried, out of what the death fire site
        # froze (CR 603.10 / 608.2h) and never off any board: by the time this
        # trigger resolves the creature is a card in a graveyard with no
        # counters at all (CR 400.7), so a live read would answer zero on every
        # card that can print the words.
        #
        # No record is a death nothing observed — zero tokens, rather than a
        # guess at a pile that no longer exists.
        frozen = (context.trigger_context or {}).get("dead_counters") or {}
        count = max(0, int(frozen.get(str(raw_count["dead_counters"]), 0) or 0))
    elif isinstance(raw_count, dict) and "history" in raw_count:
        # "…for each nontoken creature that died this turn" (Gadrak): the game's
        # own tally, because the objects counted are exactly the ones no zone
        # still holds. Which tally the phrase named is settled at lowering; an
        # unknown one makes no tokens rather than falling back to a wider count.
        count = int(getattr(game, str(raw_count["history"]), 0) or 0)
    elif isinstance(raw_count, dict) and "seat_record" in raw_count:
        # "…equal to **the amount of mana they paid this way**" (Liege of the
        # Hollows). One number per recipient, out of this resolution's own
        # scratchpad rather than off any board — so it is left to the loop
        # below, exactly as the per-each board count beside it is, and read
        # through the one per-recipient reader.
        count = 0
    elif isinstance(raw_count, dict) and "per_each" in raw_count:
        # "…for each untapped Forest **they** control" (Waiting in the Weeds).
        # A board count rather than a tally, and the one count here that is
        # taken **per recipient**: "they" is each player the sentence
        # distributes over, so the number is different for each of them and
        # cannot be computed in front of the loop. Left to the loop below,
        # which passes the seat it is making tokens for.
        count = 0
    else:
        count = resolve_amount(raw_count, context.x_value)
    recipients = token_recipient_seats(game, payload, context, controller_index)
    for seat in recipients:
      # The per-recipient count, evaluated here rather than above: "for each
      # untapped Forest **they** control" is a different number for each seat,
      # and evaluating it once would make every player create as many tokens as
      # the caster's own board carried. ``per_recipient`` false is the same
      # spec taken on the caster's board every time (nothing prints it yet, and
      # refusing it in the lowering would refuse a sentence this can answer).
      if isinstance(raw_count, dict) and "seat_record" in raw_count:
          count = per_recipient_amount(
              game, context, raw_count, game.players[seat],
              source=context.source_permanent,
          )
      elif isinstance(raw_count, dict) and "per_each" in raw_count:
          owner = game.players[seat] if raw_count.get("per_recipient") else caster
          # "…for each permanent **of that color**" (Rith, the Awakener): the
          # colour the step in front of this one chose (CR 608.2d) is resolved
          # into the spec first, because `evaluate_count` holds no resolution
          # and the matcher refuses the word unresolved.
          count = evaluate_count(
              game, owner,
              count_spec_in_resolution(raw_count["per_each"], context),
              source=context.source_permanent,
          )
      for _ in range(count):
        metadata: dict = {"is_token": True}
        # "…any number of tokens **created with this creature**." (Tetravus.)
        # Which permanent made the token is a fact about its history that
        # nothing about the token itself records, and it is stamped by
        # `permanent_id` rather than by identity: a Tetravus that leaves and
        # comes back is a new object (CR 400.7), and its old Tetravites were
        # not created with *it*.
        if context.source_permanent is not None:
            metadata[CREATED_WITH_PERMANENT_ID] = context.source_permanent.permanent_id
        token = Permanent(card=token_card, metadata=metadata)
        game._put_permanent_onto_battlefield(seat, token, None)
        # "…that are tapped and attacking" (Basri Ket): entry state, not an
        # attack declaration — the tokens join the combat the trigger saw
        # (CR 111.10c-style entry), attacking whatever seat is already under
        # attack.
        if payload.get("tapped"):
            token.tapped = True
        # "Create Stangg Twin, a … token. **Exile that token** when …"
        # (Stangg.) Which permanent this step made, for the sentences behind it
        # in the same resolution: a token is a new object with a fresh id
        # (CR 400.7), so nothing about it can be looked up afterwards.
        #
        # Written for every token maker, and deliberately the *last* one when
        # several are made: the phrase "that token" is singular, and the
        # lowering admits it only behind a maker — a card printing it after a
        # plural maker would be a card this engine has not met, and it would
        # arrive as one token addressed rather than as a silently wider effect.
        context.results[CREATED_TOKEN_RESULT_KEY] = token.permanent_id
        # …and **all** of them, for the plural back-reference ("Exile
        # them", Waylay). Appended per token rather than assigned at the
        # end of the loop, so a sentence behind a maker that made some and
        # then stopped still names the ones it made.
        context.results.setdefault(CREATED_TOKENS_RESULT_KEY, []).append(
            token.permanent_id
        )
        if payload.get("attacking") and game.current_turn_phase == "combat":
            defending = (context.trigger_context or {}).get("trigger_defending_player_index")
            if not isinstance(defending, int):
                defending = next(iter(sorted(game.combat_defending_players())), None)
            if isinstance(defending, int):
                slot = game.battlefield_index_of(token)
                if slot is not None:
                    game.combat_attackers[slot] = defending
                    token.attacking = True
                    token.defending_player_index = defending
    if count == 1:
        game.log.append(f"{card.name} created a {token_card.name} token")
    elif count > 1:
        game.log.append(f"{card.name} created {count} {token_card.name} tokens")
    return True, "resolved"
