"""Instruction kinds whose picker is read off their own payload.

:data:`_KIND_TO_SPEC_FROM_PAYLOAD` maps an instruction kind to the function
that derives its spec, for the kinds whose target the kind alone cannot fix:
whose graveyard a return reads, which seat a sweep's "target player" names,
what a prevention shield's chosen source may be, how many cards a pile exile
names. Each function reads the payload keys the kind's own *handler* reads, so
the picker offers what the resolution will accept. A kind listed here settles
its own case before the generic ``targets`` reading
(``engine/target_descriptions.py``), because it is the only reader that knows
how to combine its payload with that description; the kinds the kind alone
fixes are ``engine/instruction_targets.py``'s ``_KIND_TO_SPEC``.

One table, consulted by the cast side and the activation side alike. Split
out of ``engine/targeting.py`` at the 2,000-line cap.
"""

from __future__ import annotations

from .target_descriptions import (GRAVEYARD_TARGET_KIND, SINGLE_GRAVEYARD,
                                  _from_targets_payload, _narrowing_flags)


#: The payload key a computed amount's count spec is stamped under. Spelled here
#: rather than imported from ``oracle_types`` beside the module's other
#: constants because the targeting modules are read by ``legality`` and the
#: cast path and nothing else needs the name. Two readers: :func:`_counted_scope_spec`,
#: which asks whose board the count names, and
#: ``targeting.cast_time_count_spec``, which asks whether it is taken at the
#: announcement.
_X_FROM_COUNT = "x_from_count"


def _life_gain_spec(payload: dict) -> dict | None:
    """Who gains the life is what decides whether anything is chosen at all.

    "Target player gains 3 life" picks a player; "you gain 3 life" picks
    nothing, and **37 of the pool's 39 life gains are the second one**. One
    instruction kind serves both because only the amount and the recipient
    differ, so the kind alone could not tell them apart — and answering "any
    target" for all of them put a picker in front of spells that target nothing
    (Revitalize, Witch's Cauldron's ability). Whatever the player clicked was
    sent as a target the handler then ignored, so the prompt was not merely
    spurious: it was a question whose answer went nowhere.

    An unrecognised recipient answers None, which is the safe direction: no
    prompt in front of an effect that chooses nothing, rather than a prompt
    whose answer is discarded.

    Reading the payload here means this entry has to answer the *whole*
    question, including the half it did not come to change: a payload-keyed spec
    is authoritative in ``_from_instruction``, so returning a bare "any" for the
    targeting case would have overridden the grammar's own targets description
    and coarsened Healing Salve and Stream of Life from "target player" to
    "any target".
    """
    if payload.get("recipient") != "target":
        # "…**you** gain 2 life for each black and/or red creature **target
        # opponent** controls." (Honorable Scout.) Who gains the life is fixed
        # and something is chosen all the same: the seat sits inside the
        # *count's* noun phrase, which ``count_spec`` lifts onto the spec's
        # ``owner`` exactly as it does for a counted draw
        # (:func:`_counted_scope_spec`, Theft of Dreams). That function reads
        # ``x_from_count``; a per-each life gain carries the same spec under
        # ``per_each``, and with nobody reading it there the trigger went on the
        # stack with no target — right in a duel, no choice of opponent at three
        # seats, and invisible to "becomes the target of". The shared pronoun
        # reader answers None for every owner the rules already fix.
        counted = payload.get("per_each")
        if isinstance(counted, dict):
            return player_pronoun_spec(counted.get("owner"))
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


#: The ``recipient`` values that mean "whoever this instruction targets".
#:
#: An **absent** key is one of them: a lowering that names no recipient is
#: spelling its kind's default, and for every "target <player> …" kind that
#: default is the target. Every other value names a seat the printed sentence
#: already fixed — the caster, each opponent, each player, the seat some
#: earlier event picked — and a fixed recipient is chosen by nobody
#: (CR 115.1a: a spell is targeted only where its ability says "target").
_CHOSEN_RECIPIENTS = frozenset({None, "target"})


def _player_recipient_spec(payload: dict) -> dict | None:
    """A seat-affecting instruction's picker, or None when the seat is fixed.

    :func:`_life_gain_spec` directly above is the same reading, written for the
    kind that needed it first; these are its twins, and they were flat
    ``{"kind": "player"}`` rows until this round — so the whole question the
    docstring above answers ("who gains the life is what decides whether
    anything is chosen at all") was never asked of who *loses* it.

    Twelve cards paid for that. "Each player loses 2 life" (Bad Deal, Pox),
    "you lose 3 life" (Grim Tutor) and "each opponent loses 2 life" (Caged
    Zombie's ability) each raised a player picker in front of an effect that
    chooses nobody, and whatever seat was clicked was sent as a target the
    handler then ignored. Carrion Grub is the same shape one kind over: an
    enters-the-battlefield mill of *its own controller's* library, which asked
    a creature spell's caster to pick a player.
    """
    if payload.get("recipient") not in _CHOSEN_RECIPIENTS:
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


def _extra_turn_spec(payload: dict) -> dict | None:
    """Who takes the extra turn, or None when the sentence chooses nobody.

    :func:`_life_gain_spec`'s reading one kind over, and here for its reason
    exactly: "**Target player** takes an extra turn after this one" (Time Warp)
    picks a seat and "Take an extra turn after this one" (Time Walk, Time
    Vault) picks none, and the kind alone cannot tell them apart. A flat
    ``{"kind": "player"}`` row would have raised a player picker in front of
    Time Walk, whose handler then ignores whatever was clicked.
    """
    if payload.get("recipient") != "target":
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


def _skipped_seat_spec(payload: dict) -> dict | None:
    """Whose step is skipped, or None when the sentence chooses nobody.

    :func:`_extra_turn_spec`'s reading directly above, one turn structure over:
    "You skip your next draw step" (Ivory Gargoyle) names CR 109.5's controller
    and picks nothing, "**Target player** skips their next draw step" (Fatigue)
    picks a seat, and one instruction kind carries both — so only the payload
    can tell them apart. A flat ``{"kind": "player"}`` row would raise a picker
    in front of the Gargoyle, whose handler ignores whatever was clicked.

    Read through :func:`player_pronoun_spec` rather than compared here, because
    the word means the same thing wherever a payload keeps it.
    """
    return player_pronoun_spec(payload.get("seat"))


def _look_top_pick_spec(payload: dict) -> dict | None:
    """The seat this look-top pick chooses, or None for the cards choosing none.

    Two payload keys name a chosen seat, and they are the family's two printed
    shapes:

    * ``looker`` — "**Target player** looks at the top three cards of their
      library" (Ashnod's Cylix): one seat answers both questions, chosen as the
      ability is activated (CR 602.2b);
    * ``pile_owner`` — "Look at the top X cards of **target opponent's**
      library" (Sealed Fate): the pile is the chosen player's and every decision
      about it is the caster's.

    "Look at the top five cards of **your** library" (Browse, See the Truth,
    Diabolic Vision) chooses nobody, and raising a player picker in front of one
    of those would ask its controller to name a target the handler ignores — the
    twelve-card mistake ``_player_recipient_spec`` above records, which is why
    this is derived from the payload rather than declared flat for the kind.

    The ``pile_owner`` half reads the lowering's own ``targets`` description
    rather than restating it, because the narrowing is part of the answer:
    "target opponent" may not choose the caster (CR 102.2/102.3) and "target player"
    may. Restating it was never the bug, though. The bug is that this function
    is registered in ``_KIND_TO_SPEC_FROM_PAYLOAD``, which **pre-empts** the
    generic ``targets`` reading in :func:`_from_instruction` — so answering None
    for a payload carrying a real description threw that description away.
    Sealed Fate derived no picker at all, the client sent a bare cast, and the
    handler logged "no player chosen" and looked at nothing.
    """
    if payload.get("looker") == "target_player":
        return {"kind": "player"}
    if payload.get("pile_owner") is not None:
        return _from_targets_payload(payload.get("targets"))
    return None


def _counter_spec(payload: dict) -> dict:
    """A counterspell, narrowed to the colour its payload names.

    The Elemental Blasts counter one colour and Counterspell counters any, which
    is one kind with different data — exactly why the colour is payload rather
    than part of the kind.
    """
    spec: dict = {"kind": "stack"}
    color = payload.get("color_filter")
    if color:
        spec["stack_color_filter"] = color
    any_colors = payload.get("any_colors")
    if any_colors:
        # "target **red or green** spell" (Tidal Control) — the colour union,
        # handed to the picker under the key the stack enumeration already
        # reads for Circle of Protection, so the offer and the counter cannot
        # name different sets.
        spec["stack_any_colors"] = list(any_colors)
    card_types = payload.get("card_types")
    if card_types:
        # Miscast: "target instant or sorcery spell" — the same union the
        # handler tests at resolution, so the picker offers exactly what the
        # counter would counter.
        spec["stack_card_types"] = list(card_types)
    mana_value = payload.get("mana_value")
    if mana_value:
        # "Counter target spell **with mana value 3 or less**" (Liquify): the
        # printed bound, handed to the enumeration that is both the
        # announcement gate (CR 601.2c) and the resolution one (CR 608.2b).
        spec["stack_mana_value"] = dict(mana_value)
    excluded_types = payload.get("excluded_types")
    if excluded_types:
        # Null Brooch: "target **noncreature** spell" — the complement of the
        # union above, handed to the picker under its own key so the offer and
        # the counter name the same set. Without it the ability is activatable
        # against a creature spell, the {2} and the whole hand are paid, and the
        # handler then declines: a cost spent for nothing, which is the shape
        # ``activation_target_refusal`` exists to prevent.
        spec["stack_excluded_types"] = list(excluded_types)
    any_classes = payload.get("any_classes")
    if any_classes:
        # "target instant or Aura spell" (Avoid Fate, Ring of Immortals) — the
        # cross-axis union, handed to the picker in the same shape the handler
        # tests, so the two cannot offer and counter different sets.
        spec["stack_any_classes"] = [list(entry) for entry in any_classes]
    targets_filter = payload.get("targets_filter")
    if targets_filter:
        # "…that targets a permanent you control". Offering a spell this
        # narrowing excludes would let Ring of Immortals be activated with
        # nothing it could legally counter — the cost paid for no effect.
        spec["stack_targets_filter"] = dict(targets_filter)
    if payload.get("targets_source"):
        # "…that targets **this creature**" (Mistfolk). The picker resolves the
        # word against the ability's own permanent, which `legality` has in hand
        # and this table does not — so the flag travels and the enumeration
        # answers it. Without it the ability offers every spell on the stack and
        # then counters nothing, which is the {U} paid for no effect the
        # narrowing beside it exists to prevent.
        spec["stack_targets_source"] = True
    controller = payload.get("controller")
    if controller:
        # "…spell or ability **an opponent controls**" (Teferi's Response),
        # "…artifact spell **you control**" (Goblin Artisans). Whose object it
        # is, handed over in the word the handler tests — so the offer and the
        # counter name one set, and a spell cast at one's own land is never
        # offered to a card that could not counter it.
        spec["stack_controller"] = controller
    if payload.get("also_ability"):
        # "Counter target spell **or ability** that targets a creature."
        # (Diplomatic Escort.) CR 113.7a: an ability on the stack is not a
        # spell, so the enumeration folds a second list in rather than widening
        # the first — the same key and the same reading the retarget one family
        # over already gives Silver Wyvern. Emitted only when the card prints
        # the union, so every counterspell before it keeps a byte-identical
        # spec.
        spec["stack_include_abilities"] = True
    return spec


def _chosen_permanent_spec(payload: dict) -> dict | None:
    """Whose battlefield a mid-resolution choice is drawn from.

    "You and **target player** exchange control of the creature you each control
    with the greatest mana value" (Juxtapose). The permanents are not targets —
    they are chosen as the spell resolves (CR 601.2c chose nothing but the
    player) — but the *player* is, and this instruction's ``controlled_by``
    is the only place the compiled program records it. ``_controlled_by_seat``
    reads the same word at resolution, so the seat the picker asks for and the
    seat the exchange draws from are one answer.

    The caster's own side answers None: "you" names no choice, and a spell whose
    every step named the caster would otherwise raise a player picker for a
    choice nobody makes.
    """
    return _chooser_announcement_spec(payload)


def _chooser_announcement_spec(payload: dict) -> dict | None:
    """The player a mid-resolution choice **announces**, for both prompts.

    ``controlled_by``/``chooser`` say the seat is the one the line targeted; the
    payload's own ``targets`` description says *which* seats were legal answers,
    which is the half a bare ``{"kind": "player"}`` drops. "**Target opponent**
    chooses any number of creatures they control" (Oracle en-Vec) may not name
    the caster (CR 102.2/102.3), and a picker told only "a player" offers them.

    Read through :func:`_from_targets_payload` rather than by reaching into the
    description, so a narrowing added to that reader reaches this prompt for
    free — the reason every kind with its own spec function is told to combine
    its payload with its description here rather than anywhere else.
    """
    if payload.get("controlled_by") != "target" and payload.get("chooser") != "target":
        return None
    described = _from_targets_payload(payload.get("targets"))
    return described if described is not None else {"kind": "player"}


def _counter_ability_spec(payload: dict) -> dict | None:
    """"Counter target activated ability from an artifact source" (Rust, Ayesha
    Tanaka) — an *ability* on the stack, not a spell.

    The same "stack" picker a counterspell raises, because the object is chosen
    from the same zone; what differs is which objects it may offer, and every
    narrowing is handed over in the shape the handler tests it in
    (``ability_kinds``, ``source_card_types``). One reading, so the ability the
    picker offers and the ability the counter would actually counter are the
    same set — an offer the handler then refuses is a tap paid for nothing.

    "Counter **that** ability" (Imprison) chooses nothing: the object is the one
    its trigger fired on, found by identity. None is the answer there, exactly
    as it is for the counterspell's "counter it".
    """
    if payload.get("bound_to_trigger"):
        return None
    spec: dict = {
        "kind": "stack",
        "stack_ability_kinds": list(payload.get("ability_kinds") or ()) or ["activated", "triggered"],
    }
    source_types = payload.get("source_card_types")
    if source_types:
        spec["stack_ability_source_types"] = list(source_types)
    return spec


def _graveyard_return_spec(payload: dict) -> dict:
    """A graveyard return, narrowed to the card type it may take.

    Regrowth takes any card, Raise Dead a creature card, Reconstruction an
    artifact card — the same instruction with different data. The handler pops
    the chosen index out of the *caster's* graveyard, so the picker is scoped to
    it.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    # "…**from a graveyard** to its owner's hand" (Endbringer's Revel). The
    # handler reads the announced seat's pile when the payload says so, so the
    # scope is the payload's answer — :func:`_reanimation_spec`'s reading of
    # the same key one destination over.
    if payload.get("any_graveyard"):
        del spec["own_graveyard_only"]
    # "Up to two target creature cards" (Sanguine Indulgence). This kind settles
    # its own spec, so the generic `targets` reading in `_from_instruction` never
    # runs for it - the maximum has to be lifted here, or the picker collects one
    # card for a spell that names two.
    count = (payload.get("targets") or {}).get("count")
    if isinstance(count, int) and count > 1:
        spec["max_targets"] = count
        # And the quantifier that goes with it, for the reason
        # `_from_targets_payload` reads it: "Return **two** target creature
        # cards" (Death's Duet) is CR 601.2c's fixed number and "Return **up
        # to** two" (Sanguine Indulgence) is not. This builder settles its own
        # spec, so the generic reading never runs and the distinction the
        # grammar has parsed all along was dropped here alone — the picker
        # offered "up to 2" for a card that prints a number.
        if (payload.get("targets") or {}).get("quantifier") == "exactly":
            spec["exact_targets"] = True
    elif count == "x":
        # "Return **X** target creature cards from your graveyard to your
        # hand." (Shattered Crypt.) There is no number here — it is the
        # announced X (CR 601.2b) — so the flag the permanent-shaped picker
        # already uses for "X target creatures" is what the maximum becomes.
        # Left off, the spec fell back to its one-target default and the
        # browser offered one card for a spell paid for X of them.
        spec["x_targets"] = True
    if spec.get("max_targets") not in (None, 1) or spec.get("x_targets"):
        # CR 115.3, the same derivation ``_from_targets_payload`` makes for a
        # permanent and for the same reason: "**two** target creature cards"
        # (Victimize) is one printed instance of the word made plural, so no
        # card may be named twice. This builder settles its own spec, so the
        # generic reading never runs and the flag has to be lifted here — the
        # arrangement ``max_targets`` and ``exact_targets`` above already have.
        #
        # Unconditional here, unlike the permanent side: a graveyard target is
        # named by a *card*, and no printing in this pool spells one sentence
        # with two instances of "target ... card" in it.
        spec["distinct_targets"] = True
    if payload.get("card_types"):
        # "target instant or sorcery card" (Shipwreck Dowser) — the union the
        # round-19 graveyard picker already tests by primary type.
        spec["card_types"] = list(payload["card_types"])
    elif payload.get("any_card"):
        spec["any_card"] = True
    elif payload.get("card_type") not in (None, "creature"):
        spec["card_type"] = payload["card_type"]
    # "target **Griffin** card" (Mtenda Griffin). Handed over in the key name
    # `graveyard_card_matches` reads, for the reason the card type beside it is:
    # a spec that dropped the subtype would offer every creature card in the
    # pile and the handler's own re-check would then decline what the picker had
    # just offered.
    if payload.get("graveyard_subtypes"):
        spec["graveyard_subtypes"] = list(payload["graveyard_subtypes"])
    # "target **green** card" (Revive) and "target **basic** land card"
    # (Groundskeeper). Handed over in the key names ``graveyard_card_matches``
    # reads, for the subtype's reason directly above: the handler re-checks the
    # chosen card against this same payload, so a spec that dropped either would
    # offer a card the resolution then declines — and for Revive, whose line has
    # no *other* narrowing, dropping the colour is the whole restriction gone.
    if payload.get("graveyard_colors"):
        spec["graveyard_colors"] = list(payload["graveyard_colors"])
    if payload.get("supertypes"):
        spec["supertypes"] = list(payload["supertypes"])
    # "Return **another** target artifact card…" (Junk Diver). Carried onto the
    # spec for the subtype's reason directly above: the enumerator reads it
    # through the one predicate the handler also reads
    # (``handlers/_filters.excluded_graveyard_slot``), so the picker cannot offer
    # the card the printed word excludes and then have resolution decline it.
    if payload.get("exclude_source_card"):
        spec["exclude_source_card"] = True
    return spec


def _graveyard_bottom_spec(payload: dict) -> dict:
    """"Put target card from your graveyard on the bottom of your library."

    Epitaph Golem's empty payload is any card in the activator's own pile —
    the fixed row this kind had before a narrowed printing existed. "Target
    **Rebel** card" (Lin Sivvi, Defiant Hero) carries the graveyard-return
    keys, so it derives the return's picker: the same pile, narrowed by the one
    predicate the handler re-checks the chosen card against.
    """
    if not payload:
        return {
            "kind": "graveyard_creature", "own_graveyard_only": True,
            "any_card": True,
        }
    return _graveyard_return_spec(payload)


def _graveyard_exile_spec(payload: dict) -> dict:
    """"Exile target card from a graveyard", narrowed to the card type it may
    take.

    Any seat's graveyard, so no ``own_graveyard_only`` — the picker is the
    reanimation one because the *choice* is identical; only where the card goes
    afterwards differs, and that is the handler's business.

    Derived from the payload rather than a fixed dict, for the reason
    :func:`_graveyard_return_spec` is: Return to Nature takes any card, Grave
    Robbers an artifact card and Eater of the Dead a creature card, and a fixed
    ``any_card`` spec would offer Grave Robbers a creature its own re-check then
    refuses. ``graveyard_card_matches`` reads the same keys in all three places.
    """
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    card_type = payload.get("card_type")
    if payload.get("any_card") or card_type is None:
        spec["any_card"] = True
    elif card_type != "creature":
        # "creature" is the enumerator's own default, so naming it changes
        # nothing; every other type is carried.
        spec["card_type"] = card_type
    return spec


def _graveyard_exile_pile_spec(payload: dict) -> dict | None:
    """"Exile X target creature cards from **your** graveyard." (Midnight
    Ritual.)

    The counted graveyard exile is one instruction over three piles, and the
    payload's ``targets`` description says which of them are announced — the
    lowering writes it for exactly the piles this derives a picker for:

    * the caster's own (Midnight Ritual), scoped by ``own_graveyard_only``;
    * "**a single** graveyard" on a spell or an activated ability (Ebony Charm,
      Rapid Decay, Decompose, Carrion Beetles, Famished Ghoul). Every pile is
      offered, and ``single_graveyard`` says what the announcement gates then
      hold the answer to: a graveyard announcement is one seat and a list of
      slots in *that seat's* pile (``Game.graveyard_target_seat``), so the
      cards are in one graveyard by construction once the seat is named — and
      the gate requires that it is (``legality._unnamed_single_pile_refusal``).
      This row answered None for these until Odyssey's second wave, on the
      ground that the pile "is named by the chooser as the spell resolves"; the
      cards are targets (CR 115.1), chosen as the object is put on the stack
      (CR 601.2c), and choosing them at resolution let a caster pick after the
      opponent had passed.

    The same holds of a **triggered** ability printing it (Gravegouger: "When
    this creature enters, exile up to two target cards from a single
    graveyard"): its cards are chosen as it is put on the stack (CR 603.3d),
    through the ``trigger_target`` prompt over this spec's candidates.

    Rysorian Badger's is "defending player's", frozen into a *trigger's*
    context by the declare-attackers fire site. It carries no description,
    answers **None** here and keeps its resolution prompt: a picker the client
    fills for an effect whose handler then prompts anyway is two questions for
    one decision.

    Everything else is handed straight over in the key names
    ``graveyard_card_matches`` reads — the arrangement every graveyard spec in
    this module has, because the handler re-checks each announced slot against
    that same predicate and a spec described in this module's own spelling
    would be a second answer to which cards may be named.
    """
    owner = payload.get("graveyard_owner")
    if owner not in ("you", "chosen") or not payload.get("targets"):
        # No ``targets``: "exile a land card from your graveyard" (Forgotten
        # Harvest) names nothing at announcement and is picked at resolution.
        return None
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    if owner == "you":
        spec["own_graveyard_only"] = True
    else:
        spec[SINGLE_GRAVEYARD] = True
    card_type = payload.get("card_type")
    if payload.get("any_card") or card_type is None:
        spec["any_card"] = True
    elif card_type != "creature":
        spec["card_type"] = card_type
    count = payload.get("count")
    if count == "x":
        # The announced X (CR 601.2b), which is not a number until the spell is
        # on the stack — the flag ``_graveyard_return_spec`` already uses for
        # Shattered Crypt's identical count, so the browser offers X cards
        # rather than falling back to the one-target default.
        spec["x_targets"] = True
    elif isinstance(count, int) and count > 1:
        spec["max_targets"] = count
        if not payload.get("up_to"):
            spec["exact_targets"] = True
    if spec.get("max_targets") not in (None, 1) or spec.get("x_targets"):
        # CR 115.3: one printed instance of "target" made plural names no
        # object twice. ``_graveyard_return_spec``'s derivation one screen up,
        # and unconditional for its reason — a graveyard target is named by a
        # card, and no printing in this pool spells one sentence with two
        # instances of "target … card" in it.
        spec["distinct_targets"] = True
    return spec


def _prevention_shield_spec(payload: dict) -> dict | None:
    """A "prevent the next N damage" shield, and who is being shielded.

    One kind, six answers, and the payload settles which: the shield sits on
    the caster (Conservator), on the source permanent itself (Rock Hydra), on
    the permanent this Aura is attached to (Fylgja), on a *source of the named
    colour, type or description* the controller chooses (the Circles and Runes
    of Protection), or on a target the ability picks (Oasis, Samite Healer,
    Guardian Angel), or on whoever the *source itself* would have damaged
    (Barbed Wire). Four of the six choose nothing at all, which is why this
    returns None rather than a spec.
    """
    if payload.get("to_self") or payload.get("to_source"):
        return None
    if payload.get("from_source"):
        # "Prevent the next 1 damage that would be dealt **by this artifact**
        # this turn." (Barbed Wire.) The **sixth** answer, and the one this
        # function's twin had already written down: ``_whole_prevention_shield_
        # spec`` below carries the same branch with the reason spelled out —
        # "the source is printed rather than chosen, so there is nothing to
        # ask", and "a flat entry would have raised a picker on the card that
        # names its own source". That is exactly what happened here, because
        # the twin's branch was never copied back.
        #
        # ``any_recipient`` is what makes it look like a target and is not one:
        # it says the shield answers to whoever the damage would have hit
        # (CR 615.1 fixes the recipient at the damage event), not that the
        # activator picks one. Barbed Wire is the pool's only activated
        # ``from_source`` shield, measured over both manifest roles, and it
        # reached the client asking for "any target" for an ability that names
        # none — which `picker_sweep` cannot see, because it asks whether a
        # picker is *derived*, not whether the line wanted one.
        return None
    if payload.get("to_attached"):
        # "…that would be dealt to **enchanted creature**" (Fylgja). The fifth
        # answer, and the docstring above counted four because nothing had
        # looked: an Aura's ability acts on its own host (CR 303.4), so the
        # host is named rather than chosen and the ability raised an "any
        # target" picker whose answer the shield never read.
        return None
    if payload.get("protection_kind") == "color":
        # The chosen source may be a permanent of that colour on any
        # battlefield, or a spell of that colour on the stack; `also_stack`
        # folds both into one prompt because the engine matches the shield by
        # colour rather than by identity.
        spec = {
            "kind": "permanent",
            "color_filter": payload.get("prevention_color"),
            "also_stack": True,
        }
        colours = payload.get("prevention_colors")
        if colours:
            # "a black **or red** source of your choice". The picker narrows to
            # exactly what the shield will answer to, so the offer and the
            # recheck at damage time (CR 615.9) agree; dropping it here would
            # offer a green source for a shield that can never match one.
            spec["any_colors"] = list(colours)
        return spec
    if payload.get("protection_kind") == "source_type":
        # "The next time an **artifact source of your choice** would deal
        # damage to you…" (Circle of Protection: Artifacts, Rune of
        # Protection: Artifacts / Lands). The colour Circles' sentence keyed
        # on a card type, and it fell past them to the line below: "any
        # target", CR 115.4's creature-player-planeswalker union, for an
        # ability that targets nothing. The browser asked "choose any target"
        # and offered both players and every creature — a Grizzly Bears for a
        # shield that answers only to artifacts — and the activation was a
        # target owed in every reader that asks (a bare ``activate`` over the
        # wire was the one thing that could not be sent).
        #
        # CR 609.7a: a source is *chosen*, so the flag is ``source_of_choice``
        # — not a target for the gate, the stack object or "becomes the
        # target" — and the kind is the printed type, so the picker offers
        # exactly what the shield will answer to (CR 615.9), as the colour
        # Circles' does. No ``also_stack``: that half is filtered by colour
        # alone, and an artifact or land source is a permanent.
        printed = str(payload.get("prevention_source_type") or "")
        return {
            "kind": printed if printed in _CHOSEN_SOURCE_TYPE_KINDS else "permanent",
            "source_of_choice": True,
        }
    if payload.get("protection_kind") == "source_subject":
        # "…a **creature of your choice with shadow**…" (Circle of Protection:
        # Shadow). The same sentence keyed on a printed noun phrase: the
        # phrase rides the spec's ``filter``, which the enumeration asks of
        # every candidate through ``subject_matches`` — the reader the shield
        # itself is matched by at damage time.
        described = dict(payload.get("source_filter") or {})
        head = str(described.get("type_filter") or "")
        return {
            "kind": head if head in _CHOSEN_SOURCE_TYPE_KINDS else "permanent",
            "filter": described,
            "source_of_choice": True,
        }
    return _from_targets_payload(payload.get("targets")) or {"kind": "any"}


#: The printed source types a "…source of your choice" picker can be narrowed
#: to by its spec ``kind`` — the kinds ``legality_enumeration._permanent_matches_target_kind``
#: has an arm for. Any other printed type is offered as a permanent, which is
#: wider than the card and never narrower: a shield is matched by its own
#: predicate at damage time (CR 615.9), so an over-wide offer is a choice that
#: prevents nothing, where an under-wide one would be a source the player may
#: not choose.
_CHOSEN_SOURCE_TYPE_KINDS = frozenset({"artifact", "creature", "land"})


def _whole_prevention_shield_spec(payload: dict) -> dict | None:
    """Pentagram of the Ages’ shield, and the one printing that chooses nothing.

    "The next time **a source of your choice** would deal damage to you this
    turn, prevent that damage" runs the prompt its four siblings above run — a
    permanent on any battlefield or a spell on the stack, matched by identity,
    so no filter narrows it. CR 609.7a is what makes them one prompt rather than
    four: the phrase names *a source of damage*, and the set a player may choose
    from is the rule’s, not the card’s.

    ``from_source`` is the other printing — "The next time **this creature**
    would deal damage to you this turn" (Mercenaries) — where the source is
    printed rather than chosen, so there is nothing to ask. That is why this is
    a payload reader and not a flat entry beside ``grant_half_prevention_shield``:
    one kind, two printings, and a flat entry would have raised a picker on the
    card that names its own source.

    Pentagram had no entry at all until Ice Age was promoted, and the omission
    was not a missing prompt but a **stronger card**: with nothing chosen the
    handler falls through to ``make_whole_charge``, a shield answering to every
    source, so the next damage from anything was prevented.
    """
    if payload.get("from_source"):
        return None
    if payload.get("recipient") == "target":
        # "…would deal damage to **any target** this turn" (Circle of Despair).
        # Two choices in one announcement, which is Jade Monolith's shape and
        # runs Jade Monolith's two-stage prompt: the *target* first — CR 115.4's
        # creature, planeswalker, battle or player — and then the damage source,
        # which ``requires_source`` is what tells the client to ask for.
        #
        # The source cannot ride ``source_of_choice`` here as it does below,
        # because that flag makes the *only* prompt a source picker and this
        # card has a real target to announce (CR 601.2c).
        #
        # The target half is read off the description the lowering wrote rather
        # than fixed at "any": Charm Peddler prints the same shield over
        # **target creature**, and a picker offering CR 115.4's whole union
        # would let the announcement name a player the ability cannot shield.
        # Circle of Despair's own description reduces to ``{"kind": "any"}``, so
        # its spec is unchanged.
        described = _from_targets_payload(payload.get("targets"))
        return {**(described or {"kind": "any"}), "requires_source": True}
    return {"kind": "permanent", "source_of_choice": True, "also_stack": True}


def _set_base_pt_spec(payload: dict) -> dict:
    """"Target creature ... has base power 0 until end of turn", narrowed to the
    creatures the printed line allows.

    Island of Wak-Wak reaches only fliers and Singing Tree only attackers; the
    enumerator applies both itself, so unlike a subtype or tapped restriction
    they have to reach the spec rather than being left to the instruction
    filter. Sorceress Queen's "other than this creature" does not appear here
    because `_ability_target_legal` already excludes the source.
    """
    return {"kind": "creature", **_narrowing_flags(payload)}


def _cast_permission_spec(payload: dict) -> dict | None:
    """A cast-permission grant targets only in its graveyard form ("You may
    cast target red instant or sorcery card from your graveyard", Chandra,
    Flame's Catalyst's −2); the exiled-cards and cost-waiver forms choose
    nothing as they go on the stack."""
    if not payload.get("target_graveyard_card"):
        return None
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    card_types = tuple(payload.get("card_types") or ())
    if card_types:
        spec["card_types"] = list(card_types)
    colors = tuple(payload.get("colors") or ())
    if colors:
        # Every printed colour, not the first: "white or black" is a union
        # (CR 105.2b), and offering only the first silently takes half the
        # legal choices away.
        spec["graveyard_colors"] = list(colors)
    return spec


def _reanimation_spec(payload: dict) -> dict | None:
    """"Return target creature card from your graveyard to the battlefield",
    narrowed by the colours the phrase prints (Dreams of the Dead's "white or
    black") and by **whose graveyard** the printed phrase reads.

    Derived rather than a fixed dict for :func:`_graveyard_return_spec`'s
    reason: the handler re-checks the same narrowing against the same predicate
    (``graveyard_card_matches``), so a picker that offered more would be
    offering choices the resolution then declines — and one that offered fewer
    would take a legal choice away.

    ``own_graveyard_only`` is the second half of that and was a constant here,
    which is the same failure one key over. "Put target creature card **from a
    graveyard** onto the battlefield under your control" (Hymn of Rebirth) is
    lowered with ``any_graveyard``, and its handler already reads the named
    seat's graveyard — so the flag was the derivation disagreeing with the
    program it is derived from, and the disagreement cost the card every target:
    with the only creature card in an opponent's pile, ``_enumerate_targets``
    returned nothing and the cast was refused outright. The payload is the
    evidence, exactly as the colours beside it are.

    ``from_top`` is the same reading pushed all the way: "Return **the top**
    creature card of your graveyard to the battlefield" (Shallow Grave) names
    its card by position, so nobody chooses and there is no picker to derive.
    The handler says so outright — it overwrites any index the wire carried —
    and this function claimed one anyway, which is the derivation disagreeing
    with the program it is derived from once more. The cost is the mirror of
    Hymn of Rebirth's: with an empty graveyard ``_enumerate_targets`` returns
    nothing, and a picker the client must fill from an empty list is a cast that
    cannot be made — where the card, resolving, simply finds no creature.
    """
    if payload.get("from_top"):
        return None
    spec: dict = {"kind": "graveyard_creature"}
    if not payload.get("any_graveyard"):
        spec["own_graveyard_only"] = True
    # "Return target **artifact** card from your graveyard to the battlefield"
    # (Argivian Restoration). The printed type, handed straight over in the key
    # ``graveyard_card_matches`` reads — the same arrangement the colours below
    # get and for the same reason: the handler re-checks the card against this
    # payload, so a picker offering a type the resolution then declines is the
    # disagreement this function exists to prevent. Absent means "creature",
    # which is what every printing before this one said.
    if payload.get("card_type"):
        spec["card_type"] = payload["card_type"]
    colors = tuple(payload.get("colors") or ())
    if colors:
        spec["graveyard_colors"] = list(colors)
    # "…**with mana value 3 or less**" (Unearth). Handed straight over in the
    # key ``graveyard_card_matches`` reads, for the type's and the colours'
    # reason above: the handler re-checks the chosen card against this same
    # payload, so a picker that ignored the bound would offer a card the
    # resolution then declines — and this card's line has *no other* narrowing,
    # so ignoring it is the whole restriction gone.
    if payload.get("graveyard_mana_value"):
        spec["graveyard_mana_value"] = dict(payload["graveyard_mana_value"])
    return spec


def _graveyard_aura_spec(payload: dict) -> dict:
    """"Return target **Aura** card from your graveyard to the battlefield"
    (Hakim, Loreweaver).

    The graveyard picker with the payload handed straight over, in the key
    names ``graveyard_card_matches`` reads — the same arrangement
    :func:`_reanimation_spec` makes and for the same reason: the handler
    re-checks the card it is given against this exact payload, so a spec that
    narrowed differently would offer an Aura the resolution then declines.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    if payload.get("card_type"):
        spec["card_type"] = payload["card_type"]
    if payload.get("graveyard_subtypes"):
        spec["graveyard_subtypes"] = list(payload["graveyard_subtypes"])
    return spec


#: The two printed pronouns a lowering records when a line names a player as a
#: **target**, and the picker each one means. One table, because the word says
#: the same thing wherever the payload keeps it — under ``who`` for a forced
#: sacrifice, ``controller`` inside a sweep's noun phrase, ``recipient`` for a
#: damage or a life change — and a spec function that spelled the pair out for
#: itself would be the place the two spellings drift apart.
_PLAYER_PRONOUN_SPECS = {
    "target_opponent": {"kind": "player", "opponents_only": True},
    "target_player": {"kind": "player"},
}


def player_pronoun_spec(word) -> dict | None:
    """The picker a printed "target player"/"target opponent" pronoun means.

    None for every other word, which is what makes this safe to ask of a
    payload key that usually holds something else: "each player" and
    "defending player" name a set or a seat the rules already fix, and neither
    announces anything (CR 115.1 is about a *chosen* target).
    """
    spec = _PLAYER_PRONOUN_SPECS.get(str(word or ""))
    return dict(spec) if spec is not None else None


def _forced_sacrifice_spec(payload: dict) -> dict | None:
    """Who a "sacrifices a creature" effect asks is what decides whether it
    targets at all.

    "Sacrifice a creature" (Dire Fleet Warmonger) and "each opponent sacrifices
    a creature" (Goremand) choose nothing — the payers follow from the effect's
    own controller. "Target opponent sacrifices a creature of their choice with
    flying" (Run Afoul) chooses a player, and it may not choose the caster
    (CR 102.2/102.3). One instruction kind serves all three, so only the payload can
    tell them apart; answering "player" for every one of them would put a
    picker in front of Goremand, whose answer nothing reads.
    """
    return player_pronoun_spec(payload.get("who"))


def _sweep_controller_spec(payload: dict) -> dict | None:
    """"Simoon deals 1 damage to each creature **target opponent** controls."
    "…put a rust counter on each artifact **target opponent** controls."
    (Corrosion.)

    A sweep over a described set that nonetheless *targets*, and the two facts
    live in different halves of the payload: the noun phrase says which
    permanents are touched, the ``controller`` key inside it says whose, and
    only the second is a choice (CR 601.2c).

    One instruction kind serves both readings, exactly as
    ``_forced_sacrifice_spec`` does one entry down, so only the payload can tell
    them apart — "each Goblin creature" (Goblin Shrine) picks nobody and must
    not raise a prompt whose answer nothing reads, while this one picks a seat
    and was refusing every cast for want of it. The client sent a bare cast, the
    engine refused it, and the card reported supported the whole time: the Roots
    class, found by ``scripts/picker_sweep.py`` and by nothing else.

    The counter sweep is the same sentence one verb over, and it is read here
    rather than left to the resolution for the reason the damage one is: the
    seat is announced (CR 603.3d for the trigger that prints it), and a
    resolution asked to guess it can only be right where there is exactly one
    opponent.
    """
    # Two payload shapes, one noun phrase. The damage sweep nests its filter
    # under ``filter`` and the destroy sweep spreads it across the payload
    # itself, so the ``controller`` key is looked for in both — reading only the
    # nested one answered None for every card written the other way, which is
    # the silent half of the Roots class rather than a refusal.
    described = payload.get("filter")
    if not isinstance(described, dict):
        described = payload
    return player_pronoun_spec(described.get("controller"))


def _matching_sweep_spec(payload: dict) -> dict | None:
    """:func:`_sweep_controller_spec` for the two sweeps that may *also* carry
    an ordinary target description.

    "Destroy all creatures **target player** controls" (Mogg Infestation)
    announces a seat inside its noun phrase; "Destroy all creatures that were
    blocked by **target Wall** this turn" (Glyph of Reincarnation) announces an
    object under the same kind, through the ``targets`` key every other
    instruction uses. A row in :data:`_KIND_TO_SPEC_FROM_PAYLOAD` is read
    *instead of* the generic description, so a reader that answered only the
    first would have taken the second card's prompt away — which is why the
    fall-through is here rather than a second row somewhere.
    """
    seat = _sweep_controller_spec(payload)
    if seat is not None:
        return seat
    return _from_targets_payload(payload.get("targets"))


def _counted_scope_spec(payload: dict) -> dict | None:
    """"Draw a card for each tapped creature **target opponent** controls."
    (Theft of Dreams.)

    :func:`_sweep_controller_spec` one payload key over. There the seat sits
    inside the noun phrase of a *sweep*; here it sits inside the ``x_from_count``
    spec of a **counted amount** — ``count_spec`` lifts a "target opponent"
    controller narrowing onto the spec's ``owner`` (``lowering/_amounts``),
    because nothing downstream tests a controller key and the count has to be
    *scoped* to a player instead. That lift is the whole announcement: the seat
    is a target choice (CR 115.1) made at the announcement (CR 601.2c) and every other
    ``owner`` value names a seat the rules already fix ("you", "all", the seat a
    firing event froze), which the shared pronoun reader answers None for.

    Without the row the derivation offered no picker at all, the client sent a
    bare cast and the engine refused it — the Roots class, and the one
    ``picker_sweep.py`` finding in Exodus.
    """
    spec = payload.get(_X_FROM_COUNT)
    if not isinstance(spec, dict):
        return None
    return player_pronoun_spec(spec.get("owner"))


def _ability_text_grant_spec(payload: dict) -> dict | None:
    """Who a quoted-ability grant reaches is what decides whether it targets.

    ``grant_target_ability_text`` serves four printings and only one of them
    chooses: a named target (Life Matrix), the object the sentence in front of
    it bound (Dreams of the Dead), the creatures an earlier step recorded
    (Dread Wight) — and, since Resuscitate, a **described set** ("creatures you
    control gain …"), which is CR 611.2c's board walked at resolution and
    chooses nobody.

    The same reading :func:`_forced_sacrifice_spec` makes one kind over, and the
    same reason it has to be made here: only the payload can tell the printings
    apart, and answering "creature" for all of them puts a picker in front of a
    spell that targets nothing — the Cleanse class, where the prompt aborts the
    cast on a board with no legal answer.

    The two recorded readings are restated rather than left to the generic
    fall-through, because a ``_KIND_TO_SPEC_FROM_PAYLOAD`` row is read
    *instead of* it: a row that answered None for them would take Life Matrix's
    picker away.
    """
    if payload.get("filter") is not None:
        return None
    if payload.get("permanents_from") or payload.get("on_block_pair"):
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "creature"}


def _control_gift_spec(payload: dict) -> dict | None:
    """"**Target opponent** gains control of this creature …" (Chaos Lord.)

    The seat under the same ``who`` key ``_forced_sacrifice_spec`` reads, and a
    separate entry rather than a shared one because the two ask different
    questions of it: a sacrifice's ``who`` may name the effect's own controller
    or every opponent at once, while a control gift's may also be ``chosen``
    (Rainbow Vale) or the seat whose upkeep it is (Emberwilde Djinn). Only the
    two printed *target* pronouns announce anything, which is what the shared
    reader answers.
    """
    return player_pronoun_spec(payload.get("who"))


def _chosen_from_target_player_spec(payload: dict) -> dict | None:
    """"…**choose a land that player controls**" (Equipoise.)

    The permanents are chosen as the ability *resolves* — that is
    ``choose_permanents``' own prompt — but whose board they come off is the
    "target player" the line announced one clause earlier, and that is a
    CR 601.2c choice made when the ability goes on the stack. The payload keeps
    it as ``controlled_by``/``count_from.owner``, both of which read ``target``,
    so the announcement is derived from the first of them.

    Every other spelling of ``controlled_by`` names a seat the sentence already
    fixes ("chooser", Raiding Party) and announces nothing.
    """
    # "**Target opponent** chooses any number of creatures they control."
    # (Oracle en-Vec.) The other way a plural pick announces a seat: the
    # *chooser* is the targeted player rather than the owner of the board it is
    # drawn from. One reader for both, so which of the two the sentence printed
    # cannot change whether a picker is offered.
    return _chooser_announcement_spec(payload)


# One kind, several specs, decided by payload.
def _graveyard_to_library_spec(payload: dict) -> dict:
    """Drafna's Restoration's picker: cards of one type, in *any* graveyard.

    Not scoped to the caster's own — the spell names a target player, and the
    graveyard the cards come from is theirs. The maximum is deliberately absent:
    "any number" prints no ceiling, so the only cap is how many legal targets
    exist, which `cast_target_spec` fills in once it has enumerated them.
    """
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    # Handed over in the key names ``graveyard_card_matches`` reads, so the
    # picker and the handler ask one question. "Any card" (Misinformation) and
    # a supertype (Lodestone Bauble) are narrowings that predicate already
    # knows; a spec that only ever said ``card_type`` offered the whole pile for
    # the first and every land for the second.
    if payload.get("any_card"):
        spec["any_card"] = True
    else:
        spec["card_type"] = payload.get("card_type", "artifact")
    if payload.get("supertypes"):
        spec["supertypes"] = list(payload["supertypes"])
    # "From **your** graveyard" (Reinforcements) is one pile, and the picker has
    # to say so: the enumerator walks every graveyard by default, so a picker
    # left unscoped would offer the opponent's creature cards for a spell that
    # cannot touch them — and the handler, which indexes the caster's pile,
    # would then move whatever card happened to sit at that slot.
    if payload.get("graveyard_owner") == "you":
        spec["own_graveyard_only"] = True
    # "from **an opponent's** graveyard" (Misinformation). CR 102.2/102.3's exclusion
    # with nothing chosen: the pile is not a target, but which piles the *cards*
    # may be taken from is printed, and left unscoped the picker would offer the
    # caster their own graveyard — a strictly better card than the one printed,
    # and the mirror of the mistake `own_graveyard_only` above exists to stop.
    elif payload.get("graveyard_owner") == "an_opponent":
        spec["opponent_graveyard_only"] = True
    described = payload.get("targets") or {}
    if described.get("unbounded"):
        spec["unbounded_targets"] = True
    else:
        spec["count"] = int(described.get("count") or 1)
    if spec.get("unbounded_targets") or spec.get("count", 1) > 1:
        # CR 115.3 again, for "**any number of** target artifact cards"
        # (Drafna's Restoration) and its counted siblings — one instance of the
        # printed word, so one card cannot fill two of its slots.
        spec["distinct_targets"] = True
    return spec


def _chosen_graveyard_shuffle_spec(payload: dict) -> dict | None:
    """The picker for a graveyard shuffle that names its cards as targets.

    None for every other printing of this kind, and that is the whole of what
    this wrapper adds: "Shuffle your graveyard into your library" (Feldon's
    Cane) and "Shuffle all creature cards from your graveyard into your library"
    (Barishi) choose nothing at all — CR 115.1 makes a target something the
    sentence says the word "target" about — so a spec here would raise a picker
    the client must fill for a spell that names no target, which is a cast that
    cannot be made. The evidence is the ``targets`` description, exactly as it
    is for every other kind that answers None: absent, there is nothing to pick.
    """
    if not (payload.get("targets") or {}):
        # "Shuffle all creature cards from **target player's** graveyard into
        # that player's library." (Repopulate.) The cards are *described* and
        # nobody picks one, but the seat whose two zones they move between is
        # chosen (CR 115.1), and that seat is the whole of what this spell
        # announces. ``whose`` is the evidence, exactly as ``targets`` is for
        # the branch above — and without it the card compiled, claimed its
        # sentence, and had no picker at all: the client sent a bare cast and
        # the engine refused it.
        return player_pronoun_spec(payload.get("whose"))
    return _graveyard_to_library_spec(payload)


def _retarget_spec(payload: dict) -> dict:
    """"Target spell with a single target [if that target is you]"
    (Deflection, Reflecting Mirror — CR 115.7a, CR 115.9a).

    The same "stack" picker a counterspell raises — the object is chosen from
    the same zone — narrowed by what the card asks about it. **Two keys, and
    the first is not optional:** ``stack_single_target`` is CR 115.9a's count,
    which every card printing this sentence carries, while
    ``stack_single_target_is`` is Reflecting Mirror's extra question about
    *whose* face it is. They were one key while only one card printed the
    sentence, and that made the count vanish for the card that prints no "if":
    Deflection would have been offered every spell on the stack, including ones
    that target nothing.

    Handed over in the shape the handler tests it in, so the spells offered and
    the spells the effect could actually re-aim are the same set — an offer the
    handler then refuses is mana paid for nothing.
    """
    spec = {
        "kind": "stack",
        "stack_single_target": True,
        "stack_single_target_is": payload.get("current_target"),
    }
    # "…and **that target is a creature**" (Meddle). The object half of the
    # same question, on its own key because the two are tested with different
    # readers — a seat is compared against the caster and a permanent is asked
    # what type it is. Emitted only when the card prints it, so Deflection's and
    # Reflecting Mirror's specs stay byte-identical.
    if payload.get("current_target_type"):
        spec["stack_single_target_type"] = payload["current_target_type"]
    # "…target spell **or ability**" (Silver Wyvern). CR 113.7a: an ability on
    # the stack is not a spell, so the enumeration folds a second list in rather
    # than widening the first — every other key here is a question about a
    # *card*, which an ability does not have. Emitted only when the card prints
    # the union, so the four earlier retargets' specs stay byte-identical.
    if payload.get("also_ability"):
        spec["stack_include_abilities"] = True
    return spec


def _copy_for_each_other_target_spec(payload: dict) -> dict:
    """"Choose target instant or sorcery spell **that targets only a single
    permanent or player**." (Radiate.) The stack picker a copy raises, with
    CR 115.9a's count — ``stack_single_target``, whose reader
    (``single_spell_target``) answers only for a lone permanent or player
    target, which is the restriction printed — and the type union, handed to
    the enumeration under the keys a counterspell's are, so a spell the
    handler could not copy around is never offered and, re-asked at
    CR 608.2b, a spell re-aimed at two targets in response is not copied."""
    spec = {
        "kind": "stack",
        "copies_spell": True,
        "stack_single_target": True,
    }
    if payload.get("card_types"):
        spec["stack_card_types"] = list(payload["card_types"])
    return spec


def _chosen_source_redirect_spec(payload: dict) -> dict:
    """Nova Pentacle's source picker, and General's Regalia's two announcements.

    One kind, two printings, exactly as ``_whole_prevention_shield_spec`` is one
    kind over two: "The next time a source of your choice would deal damage to
    you this turn, that damage is dealt to **target creature you control**
    instead" (General's Regalia) announces a target as well, while Nova
    Pentacle's taker is picked by an *opponent* as the ability resolves and
    Reflect Damage names no taker at all. So the payload decides — a ``targets``
    description means a target to announce, and its absence is the source-only
    prompt those two have always run.

    ``source_of_choice`` makes the *only* prompt a source picker, which is why
    the announcing printing cannot use it: it has a real target to name first
    (CR 601.2c), and ``requires_source`` is what adds the second stage.
    """
    described = _off_target_chosen_source_redirect_spec(payload)
    if described is not None:
        return described
    return {"kind": "permanent", "source_of_choice": True, "also_stack": True}


def _off_target_chosen_source_redirect_spec(payload: dict) -> dict | None:
    """Shaman en-Kor's second ability: "The next time **a source of your
    choice** would deal damage to **target creature** this turn…" — and Kor
    Chant, which announces a second target as well.

    Two announcements in one activation, which is Jade Monolith's shape: the
    creature is a target (CR 601.2c) and the source is CR 615.8's choice, which
    is not a target at all. So the target description is read the ordinary way
    and ``requires_source`` is what tells the client to ask for the second.

    ``source_of_choice`` cannot carry it, as it does for Nova Pentacle and the
    Circles: that flag makes the *only* prompt a source picker, and this ability
    has a real target to announce.

    One function for both kinds because the *targets* half is what differs and
    ``_from_targets_payload`` already tells the two apart: Shaman en-Kor's
    description carries one filter and comes back a creature picker, while Kor
    Chant's carries one per slot and comes back ordered **roles** (its two slots
    are narrowed differently, so a shared candidate list would drop the printed
    "you control"). ``requires_source`` rides on top of whichever it is, which
    is what makes this row the whole difference between the two kinds' specs.
    """
    described = _from_targets_payload(payload.get("targets"))
    if described is None:
        return None
    return {**described, "requires_source": True}


_KIND_TO_SPEC_FROM_PAYLOAD = {
    "redirect_chosen_source_damage_off_target_until_eot": (
        _off_target_chosen_source_redirect_spec
    ),
    "redirect_chosen_source_damage_between_targets_until_eot": (
        _off_target_chosen_source_redirect_spec
    ),
    "redirect_damage_from_chosen_source_until_eot": _chosen_source_redirect_spec,
    "choose_new_spell_target": _retarget_spec,
    "copy_spell_for_each_other_target": _copy_for_each_other_target_spec,
    "change_target_spell_target": _retarget_spec,
    "put_graveyard_cards_on_library_top": _graveyard_to_library_spec,
    # "Target player shuffles up to three target cards from their graveyard
    # into their library." (Gaea's Blessing.) The same picker: the cards are
    # named out of a graveyard by the same noun phrase, and only what happens to
    # them afterwards differs. `_chosen_graveyard_shuffle` writes the payload in
    # the keys that function reads, which is what lets one spec serve both.
    "shuffle_graveyard_into_library": _chosen_graveyard_shuffle_spec,
    "sacrifice_matching_permanent": _forced_sacrifice_spec,
    "deal_damage_each_matching": _sweep_controller_spec,
    # "Destroy all creatures **target player** controls." (Mogg Infestation.)
    # "Tap all lands **target player** controls …" (Mana Short.) The same
    # sentence two verbs over, and the same two halves of one payload: the noun
    # phrase says which permanents, the ``controller`` key inside it says whose,
    # and only the second is a choice. Without the rows the sweeps announced
    # nothing, the client sent a bare cast and the engine refused it — the Roots
    # class again, on kinds most of whose cards choose nobody.
    "destroy_all_matching": _matching_sweep_spec,
    "tap_all_matching": _matching_sweep_spec,
    # "Untap all creatures **target opponent** controls." (Reins of Power.) The
    # tap row's own twin, and it was missing: the two directions are one handler
    # (``_tap_or_untap_all_matching``) reading one payload, so a seat the tap
    # sweep announces is a seat the untap sweep announces too. Early Harvest hid
    # the gap — its lowering emits an explicit ``targets`` description for the
    # "target player untaps …" spelling, which the fall-through below answers —
    # so the kind looked covered while every "untap all X <seat> controls"
    # announced nothing at all.
    "untap_all_matching": _matching_sweep_spec,
    # "Creatures and lands **target opponent** controls don't untap during
    # their next untap step." (Exhaustion.) The third verb over the two rows
    # above, and the same two halves of one payload: the noun phrase says which
    # permanents, the ``controller`` key inside it says whose, and only the
    # second is a choice (CR 601.2c). ``_matching_sweep_spec`` rather than the
    # bare seat reader, because this kind's *other* printing chooses an object
    # instead ("Target creature doesn't untap during its controller's next
    # untap step", Barl's Cage) and reaches the picker through the ordinary
    # ``targets`` key — a row that answered only the seat would have taken that
    # card's prompt away.
    "skip_next_untap": _matching_sweep_spec,
    # Corrosion's rust counters: the same printed noun phrase as Simoon's, so
    # the same reader — what is being *chosen* is a seat, whatever the sweep
    # then does to that seat's permanents.
    "add_counter_to_each_matching": _sweep_controller_spec,
    # "All lands **target player** controls become 3/3 creatures until end of
    # turn." (Jolrael, Empress of Beasts.) The animation sweep's turn at the
    # same two-halves payload; without the row the ability announced no seat
    # and its picker offered only the discard cost.
    "animate_matching_until_eot": _sweep_controller_spec,
    # "Creatures **target player** controls get +1/+1 until end of turn."
    # (Day.) The pump sweep's turn at the same two-halves payload, and the one
    # finding `picker_sweep.py` had in Apocalypse: with no row the half derived
    # no picker, so a client sent a bare cast. ``_matching_sweep_spec`` so a
    # payload that reaches the picker through the ordinary ``targets`` key
    # keeps the prompt it had.
    "buff_creatures_global": _matching_sweep_spec,
    # "Draw a card for each tapped creature **target opponent** controls."
    # (Theft of Dreams.) The seat is inside the counted amount rather than
    # inside a noun phrase, which is the only thing that separates this row
    # from the two sweeps above it.
    "draw_controller_cards": _counted_scope_spec,
    "grant_target_ability_text": _ability_text_grant_spec,
    "give_control_of_source_to_player": _control_gift_spec,
    "choose_permanents": _chosen_from_target_player_spec,
    "target_gains_life": _life_gain_spec,
    "target_loses_life": _player_recipient_spec,
    "mill_target_player": _player_recipient_spec,
    # "**Target player's** life total becomes 20." (Blessed Wind.) Rebirth's
    # "that player" spells a fixed seat and so chooses nobody; only the
    # ``"target"`` recipient raises a picker.
    "set_life_total": _player_recipient_spec,
    "grant_extra_turn": _extra_turn_spec,
    "skip_next_step": _skipped_seat_spec,
    # Moment of Silence names a seat the same way Fatigue does, so it derives
    # the same picker: the spec is about what is being *chosen*, not about
    # which part of the turn structure is then skipped.
    "skip_next_phase": _skipped_seat_spec,
    "counter_top_stack_spell": _counter_spec,
    "counter_stack_ability": _counter_ability_spec,
    "choose_permanent": _chosen_permanent_spec,
    # Reverberation names a spell on the stack the same way a counter does, and
    # narrows it the same way ("target **sorcery** spell"), so it derives the
    # same picker — the spec is about what is being *chosen*, not about what is
    # then done to it.
    "redirect_damage_from_target_spell_until_eot": _counter_spec,
    # Hidden Retreat names a spell on the stack the same way a counter
    # does, and narrows it the same way ("target **instant or sorcery**
    # spell"), so it derives the same picker — the spec is about what is
    # being *chosen*, not about what is then done to it.
    "prevent_damage_by_target_spell_until_eot": _counter_spec,
    # "You and **target spell's controller** bid life." (Mages' Contest.) The
    # seat is read off a spell, so what the announcement chooses is the spell
    # (CR 115.1) — any spell, the paragraph narrows nothing — and the picker is
    # a counterspell's. The counter the bidding decides sits behind this step
    # and names the same object by back-reference, so this is the one row that
    # says the card targets.
    "bid_life": _counter_spec,
    "return_creature_from_graveyard_to_hand": _graveyard_return_spec,
    # "Choose two target creature cards in your graveyard." (Victimize.) The
    # same picker as the return above and derived by the same builder, because
    # the announcement is identical — a fixed number of cards out of the
    # caster's own pile, narrowed by a printed type. Only what a later sentence
    # does with them differs, and that is the handler's business.
    "choose_target_cards": _graveyard_return_spec,
    "reanimate_creature": _reanimation_spec,
    # Epitaph Golem's any card, Lin Sivvi's "target Rebel card" — see the
    # builder for why the empty payload keeps its old fixed row.
    "put_graveyard_card_on_library_bottom": _graveyard_bottom_spec,
    # Hakim, Loreweaver. The same graveyard picker, narrowed by the payload
    # the handler re-checks against — one predicate, so the Auras offered are
    # exactly the Auras the resolution will take.
    "reanimate_aura_onto_source": _graveyard_aura_spec,
    "exile_target_graveyard_card": _graveyard_exile_spec,
    # The counted twin beside it, and a spec only for the pile whose seat is
    # known at announcement — see the builder for why the other two are None.
    "exile_cards_from_graveyard": _graveyard_exile_pile_spec,
    "grant_prevention_shield": _prevention_shield_spec,
    "grant_whole_prevention_shield": _whole_prevention_shield_spec,
    # Honorable Passage names its protected object the way Circle of
    # Despair does — "would deal damage to **any target**" — and its
    # chosen source the way every CR 615.8 shield does. Same two
    # prompts, same reader, one rider later.
    "grant_reflecting_prevention_shield": _whole_prevention_shield_spec,
    "set_base_pt_target_until_eot": _set_base_pt_spec,
    "grant_cast_permission": _cast_permission_spec,
    "look_top_pick_to_hand": _look_top_pick_spec,
}
