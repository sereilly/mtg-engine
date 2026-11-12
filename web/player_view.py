"""One player's part of the state payload, as one viewer is shown it.

:func:`_serialize_player` is one seat: its life and shields, its mana pool
and the restricted buckets beside it (:func:`_serialize_mana_pool`), the
emblems it may click (:func:`_serialize_emblems`), and every zone it owns,
each card and permanent drawn by the leaves in :mod:`web.serialization`.
What is decided here is **who is shown what**. A hand is card backs to every
seat but its owner, a seat an effect reveals it to, and the seat making its
owner's decisions (:func:`_hand_revealed_to_viewer`; CR 400.2, 701.20a,
723.4) — one card of it can be revealed on its own. A card exiled
face down is a card back (:func:`exile_hidden_flags`, CR 406.3). A
face-down permanent's card (CR 708.5), the library top only its owner may
look at, the sideboard, and the puts of an open entry event
(:func:`_serialize_arriving`, CR 101.4a) go to that seat alone. And the
viewer's own permanents carry what each activated ability offers right now
— its target spec, whether it may name nothing
(:func:`_mark_pickers_that_owe_nothing`), its refusal, mana, X, price, text
change and printed cost choices — read off :mod:`web.offers`.

Split out of ``serialization.py`` as it neared its 2,000-line cap — code
motion, the bodies unchanged. This is the half that grows with the pool:
each answer the client stops re-deriving about a permanent is attached here,
to the viewer's own board. The whole state payload is assembled further up,
in :mod:`web.state_view`.
"""

from __future__ import annotations

from engine import Game
from engine.activation_cost_alternatives import (has_alternative_costs,
                                              mana_cost_text,
                                              printed_mana_costs)
from engine.cost_pickers import spec_is_a_cost
from engine.hand_locks import locked_hand_indices
from engine.legality import activation_target_obligation
from engine.library_top import top_is_public, top_is_visible
from engine.models import PlayerState
from engine.revealed_hands import hand_revealed_to

from .offers import (
    _ability_denial, _ability_mana_payload, ability_price, ability_text_change_offer,
    ability_x_payable,
)
from .prompt_values import restricted_mana_words
from .runtime import CARD_BY_NAME
from .seats import _player_has_lost
from .serialization import (
    _card_image_uris, _serialize_card, _serialize_permanent, _shield_source_payload,
    hidden_card_view,
)


#: Spec kinds that are not a pick of one object or player, so "naming nothing"
#: is not a question about them.
_NOT_A_SINGLE_PICK = frozenset({
    "none", "modal", "faces", "hand_card", "divided", "roles",
})


def _may_name_nothing(spec: dict, ability) -> bool:
    """Whether an activation of *ability* may be announced naming **nothing**
    from the picker *spec* describes.

    The engine's own answer — ``legality.activation_target_obligation``, the
    one definition of "this ability owes a target" the activation gate and the
    wire's bare-activation refusal read. None there is a picker that is a
    *choice*: "an artifact source **of your choice**" (CR 609.7a: a source is
    chosen, not targeted), "up to one target creature".

    Only for a picker of one object or player: a cost, a division, a walk of
    roles and a counted or X-sized list each have a prompt of their own.
    """
    if ability is None or not isinstance(spec, dict):
        return False
    if spec.get("kind") in _NOT_A_SINGLE_PICK or spec_is_a_cost(spec):
        return False
    if spec.get("max_targets") or spec.get("x_targets"):
        return False
    return activation_target_obligation(ability) is None


def _mark_pickers_that_owe_nothing(perm_dict: dict, usable: list) -> None:
    """Write ``may_name_nothing`` onto the activation specs of one permanent
    whose ability owes no target (:func:`_may_name_nothing`).

    ``requires_target`` goes false beside it, on the wire's copy: the engine
    writes that field as "there is a picker" (``kind != "none"``), which for
    these is the opposite of what the words say.

    **Why the client is told.** The browser's activation cascade refuses an
    empty picker — "No valid artifact targets in
    play" — for every kind alike. So a Circle of Protection: Artifacts on a
    table with no artifact could not be activated by a person at all, where
    the engine accepts the activation from every other caller: nothing is
    targeted, so nothing is owed (CR 609.7), and a source-less Circle arms its
    shield against the next source of its printed kind. The same refusal met
    a planeswalker's "+1: … up to one target creature" on a board with no
    creature. Absent wherever a target is owed, which is nearly every spec.

    Each per-ability spec is marked by its own ability. The permanent's
    top-level spec describes "the first ability that chooses anything": the
    one ability of a single-ability permanent, and otherwise the first whose
    own spec is a picker.
    """
    per_ability = perm_dict.get("ability_target_specs")
    described = None
    if isinstance(per_ability, list):
        for spec, ability in zip(per_ability, usable):
            if _may_name_nothing(spec, ability):
                spec["may_name_nothing"] = True
                spec["requires_target"] = False
            if described is None and spec.get("kind") not in (None, "none"):
                described = ability
    elif len(usable) == 1:
        described = usable[0]
    top = perm_dict.get("target_spec")
    if _may_name_nothing(top, described):
        top["may_name_nothing"] = True
        top["requires_target"] = False


def _serialize_mana_pool(player: PlayerState) -> dict:
    mana = dict(player.mana_pool)
    for symbol in ("W", "U", "B", "R", "G", "C"):
        mana.setdefault(symbol, 0)
    return mana


def _serialize_emblems(player: PlayerState) -> list[dict]:
    """Player-owned, non-card activated abilities granted until end of turn.

    Currently only Guardian Angel's "pay {1}: prevent the next 1 damage" emblem.
    Each emblem renders as a card-like token (with the source card's art) the
    controller can click to activate; the rich card fields drive the hover
    preview. `index` matches the engine list position used by activate_emblem."""
    emblems: list[dict] = []
    entries = player.prevent_one_damage_emblems
    if entries:
        source = CARD_BY_NAME.get("guardian angel")
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        # The granted ability's reminder text — {1} renders as the mana symbol in
        # the preview, and names the fixed target ("that permanent or player").
        ability_text = (
            "Pay {1} any time you could cast an instant: Prevent the next 1 damage "
            "that would be dealt to that permanent or player this turn."
        )
        for index in range(len(entries)):
            emblems.append({
                "kind": "prevent_one_damage",
                "index": index,
                "label": "Pay {1}: prevent next 1",
                "name": "Guardian Angel",
                "source": "Guardian Angel",
                "type": "Emblem — Guardian Angel",
                "oracle_text": ability_text,
                "image_uri": image_uri,
                "large_image_uri": large_image_uri,
            })
    # Channel: "Until end of turn, any time you could activate a mana ability, you
    # may pay 1 life. If you do, add {C}." A synthetic emblem the controller clicks
    # to spend life for colorless mana while the effect is active.
    if player.channel_active_until_eot:
        source = CARD_BY_NAME.get("channel")
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        emblems.append({
            "kind": "channel",
            "index": -1,  # not an activate_emblem index; the client uses channel_mana
            "label": "Pay 1 life: add {C}",
            "name": "Channel",
            "source": "Channel",
            "type": "Emblem — Channel",
            "oracle_text": (
                "Until end of turn, any time you could activate a mana ability, you "
                "may pay 1 life. If you do, add {C}."
            ),
            "image_uri": image_uri,
            "large_image_uri": large_image_uri,
        })
    # CR 114 emblems proper (planeswalker ultimates): passive triggered
    # abilities in the command zone. No `index` for activate_emblem — nothing
    # to click; the entry is informational, in the same card-like shape.
    for emblem in getattr(player, "emblems", ()):
        source = CARD_BY_NAME.get(str(emblem.get("source_name", "")).lower())
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        emblems.append({
            "kind": "emblem",
            "index": -1,
            "label": emblem.get("name", "Emblem"),
            "name": emblem.get("name", "Emblem"),
            "source": emblem.get("source_name", ""),
            "type": "Emblem",
            "oracle_text": emblem.get("oracle_text", ""),
            "image_uri": image_uri,
            "large_image_uri": large_image_uri,
        })
    return emblems


def _hand_revealed_to_viewer(game: Game, viewer_seat: int | None, seat: int) -> bool:
    """Whether an in-progress effect reveals *seat*'s hand to *viewer_seat*:
    a pending hand reveal (Glasses of Urza) whose viewer is this seat, or a
    pending Word of Command whose caster is this seat. While one is active the
    target's hand serializes face-up for that viewer only.

    A *standing* effect can reveal it too — "Players play with their hands
    revealed." (Revelation, CR 701.20a) — derived from the battlefield by
    ``engine/revealed_zones.py``, so it starts and stops with the permanent."""
    if viewer_seat is None:
        return False
    if hand_revealed_to(game, seat, viewer_seat):
        return True
    # CR 723.4 (Mindslaver): what the controlled player could see, its
    # controller sees too — its hand first of all (the rule's own example).
    if seat != viewer_seat and game.decider_of(seat) == viewer_seat:
        return True
    reveal = game.pending_hand_reveal
    if (
        reveal is not None
        and reveal.get("viewer_index") == viewer_seat
        and reveal.get("target_index") == seat
    ):
        return True
    woc = game.pending_word_of_command
    if (
        woc is not None
        and woc.get("caster_index") == viewer_seat
        and woc.get("target_index") == seat
    ):
        return True
    return False


def _exile_payload(
    game: Game, player: PlayerState, viewer_seat: int | None, seat: int
) -> list:
    """The exile zone as a viewer sees it — face-down cards as card backs.

    Exile is a public zone, but a card put there **face down** (CR 406.3) is
    hidden from every player, its owner included: Knowledge Vault's ``{2}, {T}``
    says nothing about looking. The ``<hidden>`` placeholder is the same one a
    concealed hand uses.

    The hiding *is* per viewer, but only because a card can say so — Gustha's
    Scepter's "you may look at it for as long as it remains exiled" grants one
    seat a look at a card the rest of the table cannot see, and the record
    carries which seat. Absent such a permission every viewer gets the same
    answer, Knowledge Vault included.

    Which cards those are is read from the linked-exile record
    (engine/linked_exile.py) and the exile register rather than from a flag on
    the card, and a record names the object it was written for — which is a
    position here because **no exile holds one object twice**
    (``Game.put_card_into_exile``: a copy arriving as an object some exile
    already holds arrives as a new one). This used to say the count of
    face-down entries made it sound, "one per matching position": it hid the
    *first* positions holding the object, and with a Dimensional Breach's
    face-up Temple of the False God ahead of a Parallel Thoughts pile's
    face-down one, the Breach's showed as a card back and the pile's by name
    (Scourge's post-promotion session). The count is still honoured, for a
    pile written directly (a test, the Debug Menu's state injection), where it
    is the best a shared object allows.
    """
    payload: list = []
    for card, hidden in zip(player.exile, exile_hidden_flags(game, player, viewer_seat, seat)):
        if hidden:
            payload.append("<hidden>")
            continue
        payload.append(
            _serialize_card(card, game, seat, from_zone="exile") if viewer_seat == seat
            else _serialize_card(card, game, owner_seat=seat)
        )
    return payload


def exile_hidden_flags(
    game: Game, player: PlayerState, viewer_seat: int | None, seat: int
) -> list[bool]:
    """Per position of *player*'s exile, whether *viewer_seat* is shown it as
    ``<hidden>`` (:func:`_exile_payload`'s reading, CR 406.3).

    Its own function because two readers need the same answer by position: the
    payload, and the Debug Menu's paste (``web/debug_actions``), which reads a
    pasted ``<hidden>`` as "the object this viewer was shown a card back for"
    and keeps it — the text names no card, and a paste that rebuilt the pile
    from names deleted every face-down card in it.
    """
    from engine.linked_exile import face_down_exiled_cards

    owed: dict[int, int] = {}
    for card in face_down_exiled_cards(game, seat, viewer_seat):
        owed[id(card)] = owed.get(id(card), 0) + 1
    flags: list[bool] = []
    for card in player.exile:
        hidden = owed.get(id(card), 0) > 0
        if hidden:
            owed[id(card)] -= 1
        flags.append(hidden)
    return flags


def _serialize_arriving(
    game: Game, seat: int, viewer_seat: int | None = None,
) -> list[dict]:
    """The permanents on their way onto *seat*'s battlefield while their "as
    it enters" choice is made (CR 614.12a, ``engine/entry_awaiting.py``),
    each marked ``entering: True`` — and, to *seat* alone, what it has put
    into an event still waiting on another seat's choice.

    The engine has such a permanent in no zone until the answer — its spell
    is still on the stack and nothing on the board sees it — but the table is
    shown it arriving, which is what the client draws an ``entering``
    permanent as (the printed card ghosted under an ENTERING ribbon, no
    badges). Nothing can be done to it in that window: the game waits on the
    prompt (CR 117.3b), and an id the client sends for it resolves to nothing
    on the battlefield. No choice of its is shown, because none is recorded
    for a person before they answer.

    **A put handed to an open event** (CR 603.6a, ``Game.open_entry_events``)
    is the other way a permanent waits in no zone: "Each player may put an
    artifact, creature, enchantment, or land card from their hand onto the
    battlefield" (Show and Tell) asks each seat in turn and puts every card
    down together at the last answer, so the first seat's card has left its
    hand and is nowhere while a later seat chooses. CR 101.4a lets a card
    chosen from a hidden zone stay face down as it is chosen, so the other
    seats are shown nothing — but its own controller chose it, and was shown
    nothing either: the card was gone from its hand and on no board. It is
    listed to its controller (*viewer_seat* = *seat*), arriving, and to
    nobody else."""
    from engine.entry_awaiting import awaited_entries

    arriving = []
    for record in awaited_entries(game):
        if record.controller_index != seat:
            continue
        payload = _serialize_permanent(record.permanent, game)
        payload["entering"] = True
        arriving.append(payload)
    if viewer_seat is not None and viewer_seat == seat:
        shown = {id(record.permanent) for record in awaited_entries(game)}
        for event in getattr(game, "open_entry_events", ()) or ():
            if event.closed:
                continue
            for put in event.puts:
                if put.controller_index != seat or id(put.permanent) in shown:
                    continue
                shown.add(id(put.permanent))
                payload = _serialize_permanent(put.permanent, game)
                payload["entering"] = True
                arriving.append(payload)
    return arriving


def _serialize_player(
    player: PlayerState,
    viewer_seat: int | None,
    seat: int,
    game: Game,
    playable_hand_indices: list[int] | None = None,
    playable_command_indices: list[int] | None = None,
    castable_hand_faces: dict[int, list[str]] | None = None,
) -> dict:
    if viewer_seat == seat:
        hand = [
            _serialize_card(card, game, seat, hand_index=index)
            for index, card in enumerate(player.hand)
        ]
        # Which half of a split card in hand could be cast right now. The
        # card's own entry in `playable_hand_indices` says "at least one"; the
        # two halves have different costs, colours and targets (CR 709.3a), so
        # the prompt that offers them has to know which. Stamped on the face
        # entries rather than sent as a second list keyed by position.
        for index, names in (castable_hand_faces or {}).items():
            for face in hand[index].get("faces", ()):
                face["castable_now"] = face["name"] in names
    elif _hand_revealed_to_viewer(game, viewer_seat, seat):
        # An active reveal (Glasses of Urza's look, Word of Command's forced-play
        # choice) lets the viewer see this player's actual cards, so the opponent
        # hand fan renders real card faces instead of card backs.
        hand = [_serialize_card(card, game, owner_seat=seat) for card in player.hand]
    else:
        # A hidden hand can still hold a face-up card: "that player plays with
        # that card revealed in their hand" (Firestorm Phoenix, CR 701.20a).
        # Per position rather than per hand, because the reveal is about one
        # card — the rest of the hand stays a hidden zone.
        revealed = locked_hand_indices(game, seat)
        hand = [
            _serialize_card(card, game, owner_seat=seat) if index in revealed else "<hidden>"
            for index, card in enumerate(player.hand)
        ]

    top_public = bool(player.library) and top_is_public(game, seat)
    permanents = list(game.controlled_by(seat))
    battlefield = [
        _serialize_permanent(perm, game) for perm in permanents
    ]
    # The viewer's own permanents carry the target spec for their activated ability
    # (kind + legal targets) so the UI can drive activation targeting from backend
    # data rather than parsing the ability text client-side.
    if viewer_seat == seat:
        for idx, (perm, perm_dict) in enumerate(zip(permanents, battlefield)):
            # CR 708.5: the controller may look at its own face-down
            # permanents (``hidden_card_view``); nobody else is sent this.
            hidden = hidden_card_view(perm)
            if hidden is not None:
                perm_dict["hidden_card"] = hidden
            perm_dict["target_spec"] = game.activation_target_spec(seat, idx)
            # Multi-ability permanents whose abilities target differently
            # (Pyramids): one spec per usable ability, indexed like the
            # ability_index the activate action takes.
            usable = game.usable_abilities_of(perm, card=perm.effective_card)
            if len(usable) > 1:
                perm_dict["ability_target_specs"] = [
                    game.activation_target_spec(seat, idx, ability_index=k)
                    for k in range(len(usable))
                ]
            _mark_pickers_that_owe_nothing(perm_dict, usable)
            # CR 602.5: why each usable ability may not be activated **now**,
            # in the engine's own words, or None — indexed like the
            # ``ability_index`` the activate action takes. The activation
            # path's own predicates (``_ability_denial``), so a menu built from
            # this greys out exactly what a click would be refused for: the
            # ability's own printed restriction (Barbarian Ring's threshold,
            # whose payload was identical at six and at seven cards in the
            # graveyard and whose picker opened either way), what another
            # permanent forbids — a City of Solitude on an opponent's turn, a
            # Null Rod, an Interdict — a loyalty ability's window, and a cost
            # the board cannot pay. Present only when some ability is denied,
            # which is nearly no permanent on any poll.
            denials = [_ability_denial(game, seat, perm, ability) for ability in usable]
            if any(found is not None for found in denials):
                perm_dict["ability_denials"] = denials
            # What each ability adds and whether activating it asks for a
            # colour (``offers._ability_mana``) - the per-ability fact behind the
            # permanent-wide ``produced_mana`` summary.
            ability_mana = _ability_mana_payload(game, perm, usable)
            if ability_mana is not None:
                perm_dict["ability_mana"] = ability_mana
            # The X each "{X}…:" ability can be paid for now
            # (``offers.ability_x_payable``), indexed like ``ability_index``;
            # absent where no ability's cost prints an {X}.
            x_payable = [ability_x_payable(game, seat, perm, ability) for ability in usable]
            if any(entry is not None for entry in x_payable):
                perm_dict["ability_x_payable"] = x_payable
            # The mana each ability's activation will charge now, where a tax
            # or a reduction moves it off the printed cost (``offers.
            # ability_price``: Auriok Steelshaper's free equip), indexed like
            # ``ability_index``; absent where every ability costs as printed.
            prices = [ability_price(game, seat, perm, ability) for ability in usable]
            if any(entry is not None for entry in prices):
                perm_dict["ability_prices"] = prices
            # The two words each ability's text change announces
            # (``offers.ability_text_change_offer``: Balduvian Shaman), indexed
            # like ``ability_index``; absent where no ability announces any.
            text_change = [ability_text_change_offer(game, ability) for ability in usable]
            if any(entry is not None for entry in text_change):
                perm_dict["ability_text_change"] = text_change
            # The printed activation costs each ability offers a choice
            # between ("{3}, {T} or {U}, {T}", the Mirrodin Shards), as mana
            # strings in printed order — the index of the one chosen is what
            # the activate action's ``alternative_cost_index`` sends back
            # (CR 602.2b through 601.2b). Indexed like ``ability_index``;
            # absent where no ability prints an "or" between costs.
            cost_choices = [
                [mana_cost_text(mana) for mana in printed_mana_costs(ability.cost)]
                if has_alternative_costs(ability.cost) else None
                for ability in usable
            ]
            if any(entry is not None for entry in cost_choices):
                perm_dict["ability_cost_alternatives"] = cost_choices
    # …and, after them, the permanents on their way onto this seat's board
    # (``_serialize_arriving``), after the board's own so no slot a client
    # addresses an action by moves.
    battlefield.extend(_serialize_arriving(game, seat, viewer_seat))

    def _crowned(entries: list, cards) -> list:
        # CR 903.3: mark the designated commander card, wherever its zone
        # payload is visible. Identity-keyed, so a same-name card or a token
        # copy's card is never marked. Hidden hands are strings and skipped.
        for payload, card in zip(entries, cards):
            if isinstance(payload, dict) and game.is_commander_card(seat, card):
                payload["is_commander"] = True
        return entries

    return {
        "name": player.name,
        "life": player.life,
        # Eliminated but the game continues (Free-For-All): the client drops
        # this seat into spectator mode and skips it in targeting helpers.
        "lost": _player_has_lost(game, seat),
        # Damage-prevention shield protecting the player directly (Conservator,
        # Circle of Protection, Healing Salve's "to any target" mode, …).
        "damage_prevention_pool": player.damage_prevention_pool,
        "shield_source": _shield_source_payload(player.damage_prevention_source),
        # Color a Circle of Protection shield is set against (e.g. "R").
        "shield_color": player.damage_prevention_color,
        # Channel emblem: while active the player may pay life for {C} this turn.
        "channel_active": player.channel_active_until_eot,
        "hand": _crowned(hand, player.hand),
        "hand_count": len(player.hand),
        # Jandor's Ring: whether a card drawn this turn is still in hand, i.e.
        # whether its "Discard the last card you drew this turn" cost is payable.
        "has_last_drawn_card": player.last_card_drawn_this_turn() is not None,
        "deck": {"count": len(player.library)},
        "library_count": len(player.library),
        # A revealed top card of the library — "Players play with the top card
        # of their libraries revealed." (Field of Dreams, CR 401.5) or this
        # player's own "Play with the top card of your library revealed."
        # (Conspicuous Snoop). Revealed is revealed to everyone (CR 701.20a),
        # the owner included — playing this way shows them a card they could
        # not otherwise see — so the card face rides the payload for every
        # viewer while a source stands, and is absent otherwise.
        "library_top": (
            _serialize_card(player.library[0], game, owner_seat=seat)
            if top_public
            else None
        ),
        # The weaker permission: "You may look at the top card of your library
        # any time." (Radha, Heart of Keld) — the owner may see it and nobody
        # else may (CR 400.2: a library is hidden). Its own key rather than
        # ``library_top`` so that one keeps meaning "revealed to the table",
        # and sent only to that owner and only while the top is not public
        # anyway (``engine.library_top.top_is_visible``).
        "library_top_private": (
            _serialize_card(player.library[0], game, owner_seat=seat)
            if viewer_seat == seat and player.library and not top_public
            and top_is_visible(game, seat)
            else None
        ),
        # The viewer's own graveyard/exile carry the same target specs a hand
        # card does, because a cast permission (engine/cast_permissions.py) can
        # make one castable — and the cast prompts read the spec off the card.
        "graveyard": _crowned([
            _serialize_card(card, game, seat, from_zone="graveyard")
            if viewer_seat == seat else _serialize_card(card, game, owner_seat=seat)
            for card in player.graveyard
        ], player.graveyard),
        "exile": _crowned(_exile_payload(game, player, viewer_seat, seat), player.exile),
        # The ante zone (CR 407) — public, like exile. Empty unless an ante card
        # (Contract from Below, Demonic Attorney, Jeweled Bird) has resolved.
        "ante": [_serialize_card(card, game, owner_seat=seat) for card in player.ante],
        # The command zone (CR 408), public like the ante zone: CR 903.6 puts a
        # commander there *face up*. Serialized with the viewer's seat when it
        # is their own, because a commander in it is castable (CR 903.8) and the
        # cast prompt reads its target spec off the card exactly as a hand
        # card's. Empty outside a Commander game.
        "command_zone": _crowned([
            _serialize_card(card, game, seat, from_zone="command")
            if viewer_seat == seat else _serialize_card(card, game, owner_seat=seat)
            for card in player.command_zone
        ], player.command_zone),
        # CR 903.8: what each commander in that zone would cost extra to cast
        # right now, keyed by name, so the client can show the tax without
        # re-deriving "each previous time".
        "commander_tax": {
            card.name: game.commander_tax(seat, card) for card in player.command_zone
        },
        # CR 903.10a: combat damage this player has taken from each commander,
        # as a list so the client need not parse a tuple key. ``seat`` is the
        # commander's owner and ``name`` the commander.
        "commander_damage": [
            {"seat": owner, "name": name, "damage": dealt}
            for (owner, name), dealt in sorted(player.commander_damage_taken.items())
        ],
        # Cards owned from outside the game (CR 100.4). Private, like the hand:
        # only their owner sees what's in it, everyone sees the count.
        "sideboard": (
            [_serialize_card(card) for card in player.sideboard] if viewer_seat == seat else []
        ),
        "sideboard_count": len(player.sideboard),
        "battlefield": battlefield,
        "emblems": _serialize_emblems(player),
        "mana_pool": _serialize_mana_pool(player),
        # "Spend this mana only to…" (CR 106.6). Each restriction keeps its own
        # bucket so the UI can show it as a distinct, labelled tracker instead
        # of folding it into the ordinary pool — which would overstate what is
        # spendable. ``creature_only_mana`` is the first of these and keeps its
        # own key because the client already reads it by name.
        "creature_only_mana": {sym: n for sym, n in player.creature_only_mana.items() if n > 0},
        "restricted_mana": {
            key: {sym: n for sym, n in bucket.items() if n > 0}
            for key, bucket in (player.restricted_mana or {}).items()
            if any(n > 0 for n in bucket.values())
        },
        # What each of those buckets may be spent on, as the card says it, for
        # the chip's label: the client's own table named two of the eight
        # restrictions and called the rest "spent on certain spells" — an
        # artifact-ability bucket (Vedalken Engineer) included.
        "restricted_mana_words": {
            key: restricted_mana_words(key)
            for key, bucket in (player.restricted_mana or {}).items()
            if any(n > 0 for n in bucket.values())
        },
        "playable_hand_indices": playable_hand_indices if viewer_seat == seat else [],
        # The same answer for the viewer's own command zone (CR 903.8): which
        # commanders they could cast right now, so the board highlights one the
        # way it highlights a castable card in hand. Distinct from
        # `castable_from_zones`, which says the zone is open at all.
        "playable_command_indices": playable_command_indices if viewer_seat == seat else [],
    }
