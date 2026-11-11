"""Which ability an AI seat activates on a permanent **it controls**.

:func:`choose_activation_action` walks the seat's own board for the best
ability it may activate and can pay for, asking the engine's gates first —
the activation prohibitions and restrictions (CR 602.5), a target
requirement, a cost no board can pay — and aiming each target on the side
its effect wants (``ai_activation_targets._activation_target_side``, read
step by step off the program). What the flat score cannot price — a land's
ability, an X, a hamper or a rewrite of its own source, a replacement
waiting on a later draw, a shield — is rehearsed
(``ai_activation_rehearsal._land_ability_worth``, ``_sized_x_activation``).

Instant speed is ``ai_policy``'s: it rehearses this chooser's proposals in a
priority window (``ai_activation_rehearsal._rehearse_activation``, imported
from here) and sets aside the ones it turned down
(``_ACTIVATIONS_SET_ASIDE``, read here).

Each other place an ability is activated from has a chooser of its own
beside this one, by the door the engine opens for it: a permanent **another
seat** controls (CR 602.1b, ``ai_foreign_activations``, which asks
``ai_activation_targets._choose_target_for_instruction`` through here for
the seat an aimed ability names), a card **in the hand** (CR 113.6j,
``ai_hand_activations``) and one **in the graveyard** (CR 113.6b,
``ai_graveyard_activations``).
"""

from __future__ import annotations

from contextvars import ContextVar

from .ai_activation_rehearsal import (
    _gives_up_its_source,
    _land_ability_worth,
    _moves_something,
    _queue_activation,
    _rehearse_activation,
    _sacrifice_priced_activation,
    _sized_x_activation,
    _spends_a_one_shot_on_something,
    _text_change_activation,
)
from .ai_activation_targets import (
    _activation_target_side,
    _choose_activation_role_targets,
    _choose_equip_target,
    _choose_target_for_instruction,
    _held_by_its_tapped_source,
    _keyword_walk_order,
    _required_activation_target,
    _untaps_only,
)
from .ai_target_sides import (
    ability_denies_its_target,
    host_effect_by_the_moment,
    host_effect_side,
    sweep_a_named_counter_spares,
    sweeps_what_its_counter_shelters,
)
from .ai_valuation import (
    hand_entry_steps,
    hampers_its_own_source,
    harms_its_own_source,
    is_mana_ability,
    reaches_both_sides,
    shields_only,
    sized_by_its_own_empty_counters,
    waits_on_a_later_draw,
)
from .activation_permissions import activation_permission_denial
from .activation_prohibitions import activation_prohibition
from .activation_restrictions import activation_denial, global_activation_ban
from .cost_modifiers import sacrifice_taxes
from .game import Game
from .models import Permanent
from .named_counters import counters_on
from .oracle import compile_card_oracle
from .targeting import (
    derive_activation_spec,
    spec_roles,
    usable_activated_abilities,
)
from .target_descriptions import SINGLE_GRAVEYARD
from .target_roles import role_is_seat
from .cost_pickers import spec_is_a_cost
from .ai_payment import _plan_land_taps, plan_printed_activation_cost
from .ai_rehearsal import deliberating
from .ai_standing import permanent_worth
from .subject_filters import subject_matches
from .ai_weighed_cast import _effect_steps
from .ai_actions import ActivationAction, target_keywords
from .target_keywords import ability_target_zone
from .ai_text_changes import ability_text_change_mode, ranked_word_choices
from .ai_scoring import _score_activation
from .ai_targets import (
    _graveyard_denial_target,
    _one_graveyard_card_is_denied,
    _choose_damage_source,
)
from .ai_graveyard_returns import best_graveyard_return, graveyard_return_destination
from .ai_player_control import plays_for_another


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    """The ability this seat activates in its main phase, or None: the best
    candidate (:func:`_activation_candidate`) over every untapped permanent it
    controls that is able to act.

    **A land's non-mana abilities are weighed too**, each by its own index
    (:func:`_abilities_weighed`). This passed over every land, so Krosan
    Verge's search, Mishra's Factory's animation and every other land ability
    in the pool (71 on 70 lands, measured at JUD's wave 2) were never
    activated by an AI seat. A land's *mana* abilities stay the payment
    planner's (``_plan_land_taps``), and a land ability is proposed only where
    a rehearsal of it says it leaves the seat ahead (:func:`_land_ability_worth`).
    It is asked after the turn's casts have tapped what they needed, so the
    land it taps is one nothing else this main phase wanted.

    A tapped or summoning-sick permanent is passed over, except **at instant
    speed** (``_AT_INSTANT_SPEED``, every proposal rehearsed): there only its
    {T} abilities are (CR 107.5, 602.5a) — an attacker's "{1}: …" is not.

    **It is a main phase's chooser, asked only at sorcery speed**: the seat's
    own main phase with an empty stack, by the simulator's
    ``_play_activations`` and the web's AI step. Everywhere else both ask the
    engine's priority answer (``ai_priority.act_at_priority``), which reaches
    this chooser only through ``choose_instant_speed_activation``. The web's AI
    step used to ask it in every step of the seat's turn, combat included, so
    an attacking Krosan Warchief a person had blocked was passed over (it is
    tapped) with {1}{G} open and died unregenerated (SCG Phase 5, smoke game 2).
    """
    # CR 723.5: a seat another player decides for plays nothing
    # optional for itself (``ai_player_control``'s measured policy).
    if plays_for_another(game, player_index):
        return None
    player = game.players[player_index]

    best: ActivationAction | None = None
    set_aside = _ACTIVATIONS_SET_ASIDE.get()
    at_instant_speed = _AT_INSTANT_SPEED.get()
    # One deliberation: every land ability weighed here is rehearsed against
    # the same table with nothing activated.
    with deliberating():
        for permanent_index, permanent in enumerate(player.battlefield):
            held = permanent.tapped or game._is_summoning_sick(permanent)
            if held and not at_instant_speed:
                continue
            # Stripped of its abilities (CR 305.7): the engine refuses each.
            if game.lost_abilities_refusal(permanent) is not None:
                continue
            for ability_index, ability in _abilities_weighed(game, permanent):
                if held and ability.cost.requires_tap:
                    continue
                # One the instant-speed chooser has rehearsed and turned down
                # this time it was asked (`ai_policy.
                # choose_instant_speed_activation`), so the next-best is the
                # one proposed — **that ability**, not its permanent: the set
                # held permanents, so a regeneration shield behind a turned-down
                # pump on the same creature was never asked.
                if (permanent.permanent_id, ability_index) in set_aside:
                    continue
                candidate = _activation_candidate(
                    game, player_index, permanent_index, permanent,
                    ability, ability_index,
                )
                if candidate is not None and (
                    best is None or candidate.score > best.score
                ):
                    best = candidate

    return best


def _abilities_weighed(game: Game, permanent) -> list:
    """``(ability_index, ability)`` for each ability of *permanent* the
    main-phase chooser weighs.

    **What the permanent has, not what its card prints** — the engine's own
    list (`Game.usable_abilities_of`), which is the one the activation path
    indexes into and the browser shows a person. It compiles the permanent's
    *effective* card: CR 613's layer 1 gives a copy the copied object's
    abilities and layer 6 gives an enchanted permanent the ones its Aura
    quotes. This compiled ``permanent.card``, so a Clone of a Prodigal
    Sorcerer never pinged in an AI's hands and a creature wearing Hermetic
    Study was a creature wearing nothing
    (`tests/ai/test_ai_activation_effective_card_census.py`: of 931 cards
    whose printed self the seat activates, a copy of none).

    The shared reader, not a third copy of its predicate: it carries CR
    113.6's zone read, so a cycling creature's "{2}, Discard this card: Draw a
    card." is not on this list at all. Open-coded, the policy proposed it
    every main phase and the engine ran it — a free repeatable draw for a card
    that was never discarded, on eight of Urza's Saga's creatures.

    For anything but a land, the **first** ability unindexed (the action
    names none and the engine takes the first it can pay for), as it always
    has been — and **every later ability that is not a mana ability**, each by
    its index. This read the first alone, so a permanent's second ability was
    never activated by an AI seat in either window: Pemmin's Aura's flying
    behind its untap, Morphling's shroud in front of the burn spell aimed at
    it behind its untap, Mazemind Tome's draw behind its scry (179
    permanents in the shipped pool print two or more non-mana abilities,
    kg4). A later ability is proposed only where a rehearsal of it says it
    pays (``_land_ability_worth``, asked of every indexed ability), so
    a permanent whose first ability was what it always did keeps doing it.

    For a land, **every ability that is not a mana ability**, each by its
    index — CR 605.1a asked of the engine's own predicate
    (``mana_abilities.is_mana_ability``), which reads a painland's "Add {W} or
    {U}. This land deals 1 damage to you." as the mana ability it is.
    """
    from .mana_abilities import is_mana_ability as is_cr_mana_ability

    usable = game.usable_abilities_of(permanent)
    later = [
        (index, ability)
        for index, ability in enumerate(usable)
        if ability.instruction is not None and not is_cr_mana_ability(ability)
    ]
    # A land now (CR 613 layer 4), as every other reader of a permanent's
    # type here asks: a Mishra's Factory animated is still a land, and a
    # land is what the payment planner taps for mana.
    if not permanent.has_type("land"):
        first = next(iter(usable), None)
        head = [] if first is None else [(None, first)]
        return head + [(index, ability) for index, ability in later if index > 0]
    return later


def _activation_candidate(
    game: Game, player_index: int, permanent_index: int, permanent,
    ability, ability_index: int | None,
) -> ActivationAction | None:
    """*ability* of the permanent at *permanent_index* as a proposal — gated,
    aimed, planned and scored — or None when it is not one to make.
    *ability_index* is its index among the permanent's usable abilities, or
    None for the first (see :func:`_abilities_weighed`)."""
    from .targeting import GRAVEYARD_TARGET_KIND

    player = game.players[player_index]
    # The index every spec question below is asked at.
    spec_index = 0 if ability_index is None else ability_index
    if ability is None or ability.instruction is None:
        return None

    # A mana ability is activated to *pay* for something (_plan_land_taps
    # arranges that), never for its own sake: mana added here empties at the
    # end of the step, and Black Lotus sacrifices itself to add it. The set
    # this replaced named two instruction kinds that no longer exist, so the
    # skip had silently stopped happening — see MANA_ABILITY_KINDS.
    if is_mana_ability(ability.instruction):
        return None

    # An effect that **removes its own source** (Quicksilver Wall's bounce,
    # Volrath's Dungeon): a drawback printed for an opponent to pay for (CR
    # 602.1b), skipped (`ai_valuation.harms_its_own_source`). A **hamper** that
    # leaves it in play (Swooping Talon shedding flying) is rehearsed below.
    #
    # **Except at instant speed**, where the same effect is a **rescue**: a
    # Quicksilver Wall returned to its owner's hand in front of the Terror
    # aimed at it, an Ivory Gargoyle exiled out of it, a Fleeting Image
    # bounced off a lethal block. Only a rehearsal of what is coming tells
    # the rescue from the self-inflicted loss — the same bounce with nothing
    # coming is a permanent traded for a card — and every instant-speed
    # proposal is rehearsed (``ai_policy.choose_instant_speed_activation``),
    # so it is proposed there and the rehearsal disposes.
    hampers = hampers_its_own_source(ability.instruction)
    rescue = (
        harms_its_own_source(ability.instruction) and not hampers
        and _AT_INSTANT_SPEED.get()
    )
    if harms_its_own_source(ability.instruction) and not hampers and not rescue:
        return None
    # An effect that lands on **the permanent its source is attached to**
    # ("Enchanted creature …"): whose that permanent is, against the side the
    # effect helps (`_host_refusal`).
    if _host_refusal(game, player_index, permanent, ability.instruction):
        return None

    # A cost paid in cards is a trade this policy cannot price: the score
    # below reads the *effect* alone, and a card spent on a pump that wears
    # off is a card gone. Skipping is the honest floor. Derived from the
    # compiled cost, so it reaches every card printed this way and names none.
    #
    # **Except a discard that takes a card with madness** (CR 702.35a)
    # whose madness cost the board can pay beside the ability: that card
    # is not spent but offered for less (`_madness_discard_index`), so the
    # trade is priced — by the offer's own rehearsal when it is made.
    #
    # **A cost paid in permanents is priced by rehearsal** (kg5): "Sacrifice
    # an artifact: This creature gets +2/+2 until end of turn" (Atog) is worth
    # an artifact only sometimes, and only carrying it out on a copy — the
    # victim gone, read through the fight before a combat — says when
    # (:func:`_sacrifice_is_weighed`, ``ai_activation_rehearsal.
    # _sacrifice_priced_activation``). Declined here, 173 non-mana abilities
    # in both manifest roles were never activated by an AI seat: Goblin
    # Lookout's and Orc General's pumps, Squirrel Wrangler's Squirrels, Bosh's
    # fling and the thirteen others whose effect reads what was sacrificed.
    madness_discard = (
        _madness_discard_index(
            game, player_index, ability, dict(ability.cost.mana),
            paying_for=permanent,
        )
        if ability.cost.discard_cards and ability.cost.sacrifice_filter is None
        else None
    )
    sacrifice_weighed = _sacrifice_is_weighed(ability.cost)
    if (ability.cost.sacrifice_filter is not None and not sacrifice_weighed) or (
        ability.cost.discard_cards and madness_discard is None
    ):
        # A conjoined sacrifice ("a creature **and a Swamp**", Viscerid
        # Drone) is covered by the clause above rather than by a second
        # test: the charger never fills `sacrifice_also_filter` without
        # `sacrifice_filter`, so a second condition would be unreachable
        # and would read as a claim that it is not.
        return None
    # …and the same trade imposed from outside: "Activated abilities of
    # nontoken Rebels cost an additional "Sacrifice a land"" (Brutal
    # Suppression), Drought's per-{B} Swamp. Asked of the reader the charger
    # uses, so a tax the engine would collect is a tax this policy sees.
    if sacrifice_taxes(
        game, player_index, ability.cost.mana, "activate", source=permanent,
    ):
        return None
    # "…+X/+0 until end of turn, where X is **the power of the creature
    # tapped this way**" (Keldon Battlewagon). The effect is as large as the
    # creature the cost taps, which the score below cannot see — and the
    # payment's default is the first untapped creature, which for the
    # Battlewagon is itself: +0/+0 and its own attack spent, every main
    # phase. Derived from the payload, so it names no card.
    if "cost_tap_characteristic" in (
        ability.instruction.payload.get("x_from_count") or {}
    ):
        return None
    # "…damage equal to the number of +1/+1 counters on it" with none on it
    # (an amplifier that revealed nothing): a tap spent on nothing. Not when
    # the cost itself puts a counter there first.
    if ability.cost.put_counter is None and sized_by_its_own_empty_counters(
        ability.instruction, permanent,
    ):
        return None

    # "Put a -1/-1 counter on a creature you control" (Wandering Mage). The
    # same trade one resource over, and the same reason the policy cannot
    # price it: the score below reads the *effect*, so a shield bought by
    # permanently shrinking a creature reads as free — and the AI would pay
    # it every main phase until its own board is gone. Derived from the
    # compiled cost, so it names no card.
    if ability.cost.put_counter_filter is not None:
        return None

    # "{1}{B}, Pay 2 life: …" (Phyrexian Reclamation). Life is the one cost
    # here the score below never weighed, so the seat paid it every main
    # phase down to 1 — and then proposed it once more, which the engine
    # refuses (CR 119.4: a player can pay life only up to their total) and
    # the simulator counts as a seat doing nothing. The reserve is the one
    # `ai_foreign_activations.FOREIGN_ACTIVATION_LIFE_RESERVE`,
    # `ai_casts.BUYBACK_LIFE_RESERVE` and `ai_scoring.X_LIFE_RESERVE` already
    # keep, for their reason: the last points of life are the ones that lose
    # the game.
    life_cost = int(ability.cost.pay_life or 0)
    if life_cost and player.life - life_cost < ACTIVATION_LIFE_RESERVE:
        return None

    # "Remove a +1/+1 counter from a creature you control" (Spike Rogue).
    # The same trade in the opposite direction and the same reason the
    # policy cannot price it: the score below reads the *effect*, so moving
    # a counter from one creature to another reads as a free +1/+1 — and
    # the AI would shuttle its board's counters onto the Spike every main
    # phase for no net gain. Derived from the compiled cost, so it names no
    # card. The self-referring spelling is left alone: that one is priced by
    # the source's own counters, which the score does read.
    if ability.cost.remove_counter_filter is not None:
        return None
    # …and every cost the score does price still has to be **payable**
    # (CR 601.2h via CR 602.2b; CR 118.3): "{T}, Remove a javelin counter
    # from this creature" with none left (Icatian Javelineers), "Exile two
    # cards from your graveyard" over an empty one (Grim Lavamancer),
    # "Tap two untapped Spirits you control" with one (Shacklegeist),
    # "Return a Forest you control" with none (Quirion Ranger). The
    # activation path refuses each with nothing paid, and this proposed it
    # again every main phase, the seat's one activation of the turn.
    #
    # **Asked of the engine's own gate** (`Game.unpayable_activation_cost`,
    # the one the activation path refuses with), not of a reading here.
    # This chooser asked the costs it knew one at a time — the counter
    # above was the last it learned — and none it did not: on a board that
    # could pay nothing, 26 abilities in the pool were proposed and
    # refused for their cost (`tests/ai/test_ai_activation_cost_census.py`).
    if game.unpayable_activation_cost(player_index, permanent, ability) is not None:
        return None

    # "Exile the top card of your library" (Royal Herbalist, Phyrexian
    # Devourer). The same floor one zone over, and the sharper case for it:
    # the resource spent is the seat's remaining turns (CR 704.5b — a player
    # who would draw from an empty library loses), which this policy has no
    # term for at all. Left in, a seat with two mana gains 1 life every turn
    # until it decks itself, which is a loss traded for nothing.
    if ability.cost.exile_top_of_library:
        return None

    # "Exile the top creature card of your graveyard" (Necratog, Zombie
    # Scavengers), "…the top card…" (Alms, Nature's Kiss). The same floor
    # one zone over, with a second reason the library cost does not have:
    # the cost **scans** the pile, so an activation the policy proposes
    # against a graveyard holding no matching card is refused with nothing
    # spent — and the policy would propose it again next turn, and every
    # turn after, which is the "a seat doing nothing all game" shape a
    # refused action makes. Derived from the compiled cost, so it names no
    # card.
    if ability.cost.exile_graveyard_position is not None:
        return None

    # CR 602.1a and its exceptions: a permanent whose printed permission
    # closes its ability to *its own controller* — "Only your opponents may
    # activate this ability" (Clergy of the Holy Nimbus), "Only the
    # controller of the enchanted creature…" (Merseine) — is an ability
    # this seat may not activate at all. Asked of the module that enforces
    # it rather than scored, so the answer is the engine's own; without it
    # the policy proposed the same refused activation every turn for the
    # whole game, which is the "a seat doing nothing all game" shape a
    # refused action makes.
    if activation_permission_denial(
        game, player_index, permanent, ability.source_line or ""
    ):
        return None
    # CR 602.5 as **one question** (``engine/activation_prohibitions.py``):
    # the table the activation path refuses with. The two checks around
    # this one are three of its ten rows; the other seven this chooser
    # never asked — City of Solitude's "…activate abilities only during
    # their own turns", Hand to Hand's "during combat", an Abeyance, an
    # Interdict, Faith's Fetters, Volrath's Curse, Katabatic Winds — so it
    # proposed the ability and the engine refused it, the seat's only
    # activation of the turn, every turn.
    if activation_prohibition(game, player_index, permanent, ability) is not None:
        return None
    # CR 602.5: the printed timing ("Activate only during your upkeep",
    # Svyelunite Priest; "…only during combat", Arcum's Sleigh) and a
    # board-wide ban ("Activated abilities of artifacts can't be
    # activated", Null Rod). This chooser runs in a main phase and asked
    # neither, so it proposed them and the engine refused them, every
    # turn, each one the seat's only activation of the turn. The default
    # seeded runs (every shipped set plus PCY) logged 184 refused
    # activations at PCY's wave 2 and 47 with this asked; what is left is
    # costs the board cannot pay (a counter, an exile). Asked of the
    # tables the engine enforces, so the answer is the engine's.
    if activation_denial(
        game, player_index, permanent, ability.source_line or ""
    ) or global_activation_ban(game, permanent, ability):
        return None

    # "Pay enchanted creature's mana cost" (Merseine). A cost the compiled
    # program cannot state — it is whatever the attached permanent's
    # printed cost is right now — so the tap planner below has nothing to
    # plan against. Skipping is the same honest floor the cost skips above
    # take, and it is derived from the compiled cost, so it names no card.
    if ability.cost.mana_from_attached:
        return None

    target = _choose_target_for_instruction(ability.instruction, player_index, game)
    # An equip ability (CR 702.6a): the creature is chosen here, because the
    # handler declines a target it was not given rather than scanning for
    # one (a misplaced Equipment is wrong in a way a fizzled pump is not).
    # Skipped entirely when nothing is worth equipping, so the AI does not
    # pay {1} every main phase to move a sword onto the creature it is
    # already on.
    target_permanent_index: int | list[int] | None = None
    if ability.instruction.kind == "attach_source_to_target":
        target_permanent_index = _choose_equip_target(game, player_index, permanent)
        if target_permanent_index is None:
            return None
    if ability.instruction.kind == "grant_banding_to_target":
        # Banding grants go to the controller's own creatures.
        target = player_index
        target_creatures = [
            perm for perm in game.controlled_by(player_index) if perm.is_creature
        ]
        if not target_creatures:
            return None

    # An object-targeted ability (Silent Dart's "deal 3 to target creature",
    # a "destroy target …") must name a legal permanent, or the activation
    # is refused with nothing paid (CR 602.2b). Derive the target the way the
    # picker does and aim it by the effect's category; skip when nothing is
    # worth (or legal) to target, so the AI does not burn a turn on an
    # ability it cannot resolve.
    spec = derive_activation_spec(ability)
    # "{X}, {T}: Untap **X target** lands." (Candelabra of Tawnos, Alexi,
    # Orcish Settlers.) CR 601.2c sizes the target list from the X the
    # activator announces, and this policy announces none — so the engine
    # reads X as zero and refuses any named target. Proposing the ability
    # anyway is a refused activation every turn; skipping it is the honest
    # floor until the policy prices an X. Read off the cost clause the way
    # the activation path counts its ``{X}`` symbols, so a *defined* X (the
    # verse cycle's "where X is …") is left to the sizing that answers it.
    #
    # And the same floor for **every** ``{X}`` in a cost, not only one that
    # sizes a target list: "{X}, {T}: This creature deals X damage to target
    # creature" (Crimson Hellkite) is an X its controller announces
    # (CR 107.3a), this policy announces none, and the engine reads that as
    # zero — a tap and a turn spent dealing nothing. It reached the score
    # below only to crash there on the payload's "x".
    #
    # **An X that sizes only the effect is announced now** (ONS W2G5: Silklash
    # Spider was never activated), sized by rehearsal (`_sized_x_activation`).
    # Still declined: an X that sizes the target list (the spec's
    # ``x_targets``, Candelabra, CR 601.2c).
    #
    # **An X the card defines is priced as the engine charges it** (MRD W2G5):
    # "{X}, {T}: Create a token that's a copy of the exiled card. X is the
    # mana value of that card." (Soul Foundry; Voodoo Doll, Bargaining Table.)
    # Nobody announces it, so there is nothing to size: the charge below
    # (`Game.activation_mana_charge`, which reads `cost_x_definitions`) is the
    # price, planned like a printed one, and the rehearsal judges the rest.
    # Declined outright, a Soul Foundry that had taken its imprint made no
    # token all game.
    from .cost_x_definitions import cost_x_is_defined

    x_symbols = (ability.source_line or "").lower().split(":", 1)[0].count("{x}")
    if x_symbols and (spec or {}).get("x_targets"):
        return None
    if x_symbols and cost_x_is_defined(ability.source_line or ""):
        # The X the activator announces: none, here.
        x_symbols = 0
    # An ability naming several targets of *different* kinds, chosen in
    # dependency order (CR 602.2b reaches CR 601.2c). Asked before the
    # single-target block below, which has no arm for it: the kind is
    # "roles", so that block leaves the announcement empty and the ability
    # goes on the stack with no targets — an activation that resolves and
    # does nothing, which is the shape `refused_casts` exists to make
    # visible one step later.
    target_role_refs: list[dict] | None = None
    # The word a "Choose flying, first strike, trample, or shadow" cost
    # announces (Phyrexian Splicer). None is the engine's default, kept
    # wherever the default's walk has a chain; another printed word is named
    # only where it does not, because which creatures "with the chosen
    # ability" admits is the whole of what the word decides.
    chosen_keyword: str | None = None
    if spec_roles(spec):
        side = (
            # A side only for a chain that announces a **seat** — the three
            # abilities this walk could not answer at all until it grew an
            # arm for one (see the function). Every other roles ability
            # keeps the first-option walk it has always had: giving those a
            # side too is the right policy and a different change, one that
            # moves what the AI does with every card already activating.
            _activation_target_side(permanent, ability.instruction)
            if any(role_is_seat(role) for role in spec_roles(spec))
            else None
        )
        for word in _keyword_walk_order(game, ability):
            target_role_refs = _choose_activation_role_targets(
                game, player_index, permanent_index, side=side,
                ability_index=spec_index, chosen_keyword=word,
            )
            if target_role_refs is not None:
                chosen_keyword = word
                break
        if target_role_refs is None:
            # No legal chain. Skipped rather than proposed: CR 602.2b fills
            # every role or the activation is refused with nothing paid,
            # and the gate would refuse it.
            return None
    # "{T}: Change the text of target white enchantment you control … by
    # replacing all instances of one color word with another" (Balduvian
    # Shaman, CR 612 through CR 602.2b). The activation announces the two
    # words beside its target, and this chooser named neither: the engine
    # took the strongest permanent and no words, the handler logged "had no
    # effect", and a rehearsal of that read nothing to propose. The object
    # and the words are weighed together, as the cast side weighs them
    # (`ai_text_changes.ranked_word_choices`), and the best few rehearsed
    # (:func:`_text_change_activation`).
    word_choices: list = []
    text_mode = ability_text_change_mode(ability.instruction)
    if text_mode is not None and target_permanent_index is None and not target_role_refs:
        word_choices = ranked_word_choices(
            game, player_index,
            game.activation_target_spec(
                player_index, permanent_index, ability_index=spec_index,
            ).get("valid_targets") or [],
            text_mode,
        )
        if not word_choices:
            return None
        target = word_choices[0].seat
        target_permanent_index = word_choices[0].permanent_index
    object_kinds = {"creature", "artifact", "land", "permanent", "planeswalker"}
    if (
        target_permanent_index is None
        and spec is not None
        and spec.get("kind") in object_kinds
        and not spec.get("sacrifice_cost")
        and not spec.get("discard_cost")
        # A tap-cost picker (Llanowar Behemoth) names no target either: the
        # payment is the engine's default for a seat that names nothing.
        and not spec.get("tap_cost")
        and not spec.get("return_cost")
        # …nor an untap picker over an opponent's tapped lands (Benthic
        # Explorers, PCY W3G5): read as a target, the AI would aim at the
        # land it untaps and announce a target the ability does not have.
        # The counter-cost pickers are skipped above, before this block.
        and not spec.get("untap_cost")
    ):
        # The AI activates the first usable ability (selected above), which
        # is usable_activated_abilities()[0] — the index activation_target_spec
        # narrows by.
        legal = game.activation_target_spec(
            player_index, permanent_index, ability_index=spec_index,
        ).get("valid_targets") or []
        perms = [t for t in legal if t.get("kind") == "permanent"]
        if not perms:
            return None
        # Which board, from what the effect does to its target
        # (`_activation_target_side`) — and **only** that
        # board. This fell back to "any legal permanent" when the wanted
        # side had none, which is how a destroy, a tap or a "can't block"
        # with no opposing target landed on the activator's own creature,
        # and a pump with no friendly one landed on an opponent's: an
        # activation that resolves and harms the seat that paid for it.
        side = _activation_target_side(permanent, ability.instruction)
        if spec.get("source_of_choice"):
            # "…a source of your choice…" (CR 609.7a) is not a target, so
            # no side describes it — and a shield's own category reads
            # "you", which named the activator's own largest creature as
            # the thing to be shielded *from* (Bone Mask, Dark Sphere,
            # Kithkin Armor, Pentagram of the Ages, Protective Sphere,
            # Righteous Aura). The cast side's answer, for the same phrase.
            named = _choose_damage_source(game, player_index, perms)
            if not named:
                return None
            perms = [
                t for t in perms if (t["seat"], t["index"]) == (named[0], named[1])
            ]
            side = None
        if side == "you" and ability_denies_its_target(ability.instruction):
            # "Destroy target … you control" (Rats of Rath), "Return target
            # land you control to its owner's hand" (Trade Routes): the
            # printed seat is the activator's and the effect is a denial,
            # so activating it for its own sake only costs the seat a
            # permanent. Before this the fallback above aimed Rats of
            # Rath at whatever it found.
            return None
        if side == "you":
            perms = [t for t in perms if t["seat"] == player_index]
        elif side == "opponent":
            perms = [t for t in perms if t["seat"] != player_index]
        if _held_by_its_tapped_source(ability):
            # "{2}{W}, {T}: Target Soldier creature gets +2/+2 and has
            # vigilance for as long as this creature remains tapped." (the
            # Couriers.) The one creature such a bonus cannot help in combat
            # is the source: it holds the effect by staying tapped, and a
            # tapped creature neither attacks nor blocks (CR 508.1a, 509.1a).
            # Each Courier is its own printed type, so the strongest-target
            # pick below named it nearly every time.
            perms = [
                t for t in perms
                if game.permanent_at(t["seat"], t["index"]) is not permanent
            ]
        if _untaps_only(ability.instruction):
            # "{T}: Untap target creature." (Seeker of Skybreak, Jandor's
            # Saddlebags, Voltaic Key, Aphetto Alchemist.) An untap aimed at a
            # permanent that is untapped moves nothing — nor one aimed at its
            # own source, which its {T} has just tapped. The strongest-target
            # pick below named whichever was biggest, tapped or not: the
            # targeted twin of `_host_refusal`'s untap (SCG Phase 5).
            perms = [
                t for t in perms
                if (target := game.permanent_at(t["seat"], t["index"])) is not None
                and target.tapped
                and not (ability.cost.requires_tap and target is permanent)
            ]
        def _power(t):
            perm = game.permanent_at(t["seat"], t["index"])
            return perm.effective_power if perm is not None else 0

        rank = _power
        sheltered = sweep_a_named_counter_spares(permanent.effective_card, ability.instruction)
        if sheltered is not None:
            # "Put a fate counter on target permanent" beside the same card's
            # "Destroy each nonland permanent without a fate counter on it"
            # (Oblivion Stone): a shelter, so one of the seat's own that the
            # sweep would take and that has none yet — never the source,
            # which the sweep's cost sacrifices — the most valuable first. The
            # strongest-power pick stacked three on one Grizzly Bears.
            counter, swept = sheltered
            perms = [
                t for t in perms
                if (perm := game.permanent_at(t["seat"], t["index"])) is not None
                and perm is not permanent
                and counters_on(perm, counter) == 0
                and subject_matches(game, perm, swept, observer=player_index)
            ]

            def rank(t):
                return permanent_worth(game.permanent_at(t["seat"], t["index"]), now=False)
        if not perms:
            return None
        chosen = max(perms, key=rank)
        target = chosen["seat"]
        target_permanent_index = chosen["index"]
        # "{T}: Untap **two** target lands" (Argothian Elder), "Choose two
        # target blocked attacking creatures" (General Jarkeld): a printed
        # count names that many (CR 601.2c), and the engine refuses an
        # activation naming fewer. All on the chosen permanent's seat,
        # because this action carries one seat beside its slots — the
        # strongest there first, the order the single pick takes.
        wanted = spec.get("max_targets")
        if spec.get("exact_targets") and isinstance(wanted, int) and wanted > 1:
            beside = sorted(
                (t for t in perms if t["seat"] == target),
                key=_power, reverse=True,
            )
            if len(beside) < wanted:
                return None
            target_permanent_index = [t["index"] for t in beside[:wanted]]

    # "{G}: Exile target card from a graveyard." (Scavenging Ooze.) A card
    # in a graveyard is a target like any other (CR 115.1c), and this
    # chooser named none: the block above reads battlefield kinds, so the
    # announcement went out bare and the engine's default answered it —
    # the picker's first card, which is a stated default for a script and
    # not a choice. The seat's own pick instead: the pile the effect's
    # side wants (`_activation_target_side`), and within it the card with
    # the greatest mana value. Where the effect reads as neither side's —
    # the Ooze's exile is one — an opposing pile is taken before the
    # seat's own, which is the order an unnamed target is looked for in
    # everywhere else. Skipped when nothing on the wanted side is legal,
    # for the battlefield block's reason — and for the two shapes a block
    # below names: several cards out of a single pile (``SINGLE_GRAVEYARD``)
    # and a card exiled to deny it (`_graveyard_denial_target`: an
    # opponent's pile, the cards its owner could still cast first).
    if (
        target_permanent_index is None
        and spec is not None
        and spec.get("kind") == GRAVEYARD_TARGET_KIND
        and not spec_is_a_cost(spec)
        and not spec.get("source_of_choice")
        and not spec.get(SINGLE_GRAVEYARD)
        and not _one_graveyard_card_is_denied(spec, (ability.instruction,))
    ):
        cards = [
            t for t in game.activation_target_spec(
                player_index, permanent_index, ability_index=spec_index,
            ).get("valid_targets") or []
            if t.get("kind") == "graveyard"
        ]
        side = _activation_target_side(permanent, ability.instruction)
        if side == "you":
            cards = [t for t in cards if t["seat"] == player_index]
        elif side == "opponent":
            cards = [t for t in cards if t["seat"] != player_index]
        if not cards:
            return None

        def _mana_value(t):
            pile = game.players[t["seat"]].graveyard
            held = pile[t["index"]] if 0 <= t["index"] < len(pile) else None
            return float(getattr(held, "cmc", 0) or 0)

        if side is None and any(t["seat"] != player_index for t in cards):
            cards = [t for t in cards if t["seat"] != player_index]
        # A return's card: the one worth most back that can arrive
        # (`ai_graveyard_returns`); any other effect's, the greatest value.
        returned_to = graveyard_return_destination((ability.instruction,))
        chosen = (
            best_graveyard_return(game, player_index, cards, returned_to)
            if returned_to else max(cards, key=_mana_value)
        )
        if chosen is None:
            return None
        target = chosen["seat"]
        target_permanent_index = chosen["index"]

    # "{2}{B}, {T}: Exile up to three target cards from a single
    # graveyard." (Carrion Beetles, Famished Ghoul.) The cards are announced
    # (CR 602.2b), so an activation that names none is the legal "up to"
    # announcement and exiles nothing — a cost paid for no effect, which is
    # what this seat did with every one of them once the handler stopped
    # picking for it. Named here the way the cast side names them
    # (`ai_targets._choose_several_targets`): the maximum, out of one opponent's pile,
    # and skipped when no opponent has a card to take.
    if (
        spec is not None
        and spec.get(SINGLE_GRAVEYARD)
        and target_permanent_index is None
        and not target_role_refs
    ):
        piles: dict[int, list[int]] = {}
        for entry in game.activation_target_spec(
            player_index, permanent_index, ability_index=spec_index,
        ).get("valid_targets") or []:
            if entry.get("kind") == "graveyard" and entry.get("seat") != player_index:
                piles.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
        if not piles:
            return None
        target = min(piles)
        target_permanent_index = piles[target][: int(spec.get("max_targets") or 1)]
    # "{3}, {T}: Exile target card from a graveyard." (Steamclaw; Crypt
    # Creeper, Grave Robbers, Scavenging Ooze.) Whose graveyard, named —
    # the cast side's answer (`_graveyard_denial_target`) over this
    # ability's own picker. Named nothing, the handler took the first pile
    # in seat order: the activator's own, from chair 0.
    if (
        target_permanent_index is None
        and not target_role_refs
        and _one_graveyard_card_is_denied(spec, (ability.instruction,))
    ):
        buried = _graveyard_denial_target(
            game, player_index,
            game.activation_target_spec(
                player_index, permanent_index, ability_index=spec_index,
            ).get("valid_targets") or [],
        )
        if buried is not None:
            target, target_permanent_index = buried

    # CR 601.2d asked of an ability: a divided announcement ("…divided as
    # you choose", Serra's Hymn) is one this chooser never makes, and the
    # engine refuses an activation announced without it — so proposing one
    # is a turn spent on a refusal, every turn. Then the engine's own
    # announcement gate (CR 602.2b/601.2c) over exactly what this policy is
    # about to announce: an ability whose only legal targets are cards in
    # an empty graveyard (Rootwater Diver, Groundskeeper) passed every
    # check above, because they look only at battlefield targets, and was
    # refused with nothing paid. Neither shows in `refused_casts`, which
    # counts casts; one ten-game run each of USG, TMP and MMQ logged 44
    # refused Serra's Hymn, 21 Rootwater Diver and 15 Groundskeeper
    # activations.
    if spec is not None and spec.get("kind") == "divided":
        return None
    # "{3}, {T}: You may put a creature card of the chosen type from your
    # hand onto the battlefield." With no such card in hand the ability's
    # whole effect is nothing, and the cost is still paid: Belbe's Portal
    # spent {3} every turn of NEM's simulation to log that it had no card.
    if not _hand_entry_has_a_card(
        game, player_index, permanent, ability.instruction, cost=ability.cost,
    ):
        return None
    # "{B}{B}{B}, Exile Balthor: Each player returns all black and all red
    # creature cards from their graveyard to the battlefield." The Portal's
    # floor one zone over: a sweep out of the graveyards whose piles hold
    # nothing for the activator is a cost (here the source itself) paid to
    # return nothing — or to return only an opponent's creatures.
    if not _graveyard_sweep_favours_the_seat(game, player_index, ability.instruction):
        return None
    if game.activation_target_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
        target_role_refs=target_role_refs,
        chosen_keyword=chosen_keyword,
    ) is not None:
        return None
    # …and what an opponent's Flagbearer demands of that announcement
    # (`Game.activation_target_requirement_refusal`): a seat named alone
    # for an "any target" ability is re-aimed at the Flagbearer on that
    # seat, and anything else the gate would refuse is not proposed.
    if game.activation_target_requirement_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
        target_role_refs=target_role_refs,
        chosen_keyword=chosen_keyword,
    ) is not None:
        required_slot = (
            _required_activation_target(
                    game, player_index, permanent_index, target,
                    ability_index=spec_index,
                )
            if target_permanent_index is None and not target_role_refs
            else None
        )
        if required_slot is None:
            return None
        target_permanent_index = required_slot

    land_taps: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    # "{3}, {T} or {U}, {T}" (the Mirrodin Shards): which printed cost is
    # announced — the cheapest the board pays (None for an ability printing
    # one cost) — and then that cost priced as the activation will charge it.
    alternative_cost_index = None
    required = dict(ability.cost.mana)
    if game.enforce_mana_costs and not x_symbols:
        alternative_cost_index, _printed_plan = plan_printed_activation_cost(
            game, player, ability.cost, paying_for=permanent,
        )
        # The price the activation will charge, from the one charger every
        # reader asks (CR 601.2f via 602.2b: taxes, then reductions) — not
        # the printed cost. "Equip costs you pay cost {1} less" (Auriok
        # Steelshaper) makes Leonin Scimitar's {1} free, and a plan for the
        # printed {1} refused the equip on a board with no untapped land. The
        # announced alternative is priced the same way.
        charge = game.activation_mana_charge(
            player_index, permanent, ability,
            alternative_cost_index=alternative_cost_index,
        )
        if isinstance(charge, str):
            return None
        required = dict(charge[0])
    if game.enforce_mana_costs and any(required.values()) and not x_symbols:
        plan = _plan_land_taps(game, player, required, paying_for=permanent)
        if plan is None:
            return None
        land_taps, tap_colors = plan

    score = _score_activation(game, player_index, ability.instruction, target)
    if score <= 0.0:
        return None
    candidate = ActivationAction(
        permanent_name=permanent.card.name,
        permanent_index=permanent_index,
        target_player_index=target,
        land_tap_indices=land_taps,
        score=score,
        **target_keywords(
            game, ability_target_zone(ability), player_index, target,
            target_permanent_index,
        ),
        target_role_refs=target_role_refs,
        land_tap_colors=tap_colors,
        cost_hand_index=madness_discard,
        ability_index=ability_index,
        chosen_keyword=chosen_keyword,
        alternative_cost_index=alternative_cost_index,
    )
    if sacrifice_weighed:
        # The permanent the cost eats, named (`ActivationAction.
        # cost_permanent_ids`) and weighed by rehearsal with the rest of the
        # cost: the cheapest to lose, or — where the effect reads what it ate
        # ("…damage equal to the sacrificed artifact's mana value", Bosh) —
        # each distinct reading the board offers. At instant speed the
        # cheapest reading is proposed and its caller's rehearsal disposes,
        # as for every proposal there. An X beside it is not announced.
        if x_symbols:
            return None
        return _sacrifice_priced_activation(
            game, player_index, permanent, ability, candidate,
            at_instant_speed=_AT_INSTANT_SPEED.get(),
        )
    if x_symbols:
        return _sized_x_activation(game, player_index, permanent, ability, candidate)
    if word_choices:
        return _text_change_activation(game, player_index, candidate, word_choices)
    # A land's ability, an ability whose whole effect is what its own source
    # is until end of turn (a Mistform's "becomes the creature type of your
    # choice"), and an ability whose whole effect is a replacement armed for a
    # later draw this turn (the Words, Mangara's Tome —
    # ``ai_valuation.waits_on_a_later_draw``): each proposed only where carrying
    # it out on a copy of the game leaves the seat ahead once the turn is over.
    # The flat heuristic score above rates the last two 2.5 like any other
    # effect: the seat paid {1} every main phase for a type nothing on the board
    # asks about, and armed every Word in every main phase after its own draw —
    # mana spent on a replacement no draw that turn would meet.
    #
    # Also (ONS W2G5) a cost giving up a source that is not a one-shot (Crown of
    # Vigor, `_exists_to_be_given_up`), an effect that comes back at its
    # activator (Shepherd of Rot, `reaches_both_sides`), a 1 -> 1 rewrite
    # (Riptide Mangler, `_OWN_REWRITE_KINDS`) and a shield (LGN C2: Deftblade
    # Elite in both main phases, `ai_valuation.shields_only`).
    #
    # And (kg4) every ability named by its index: a land's, and a non-land's
    # later ability (`_abilities_weighed`), which nothing had ever weighed —
    # and a rescue at instant speed (above).
    if (
        ability_index is not None or hampers or rescue
        or _sets_only_what_its_source_is(ability.instruction)
        or waits_on_a_later_draw(ability.instruction) or shields_only(ability.instruction)
        or (
            _gives_up_its_source(ability.cost)
            and not _exists_to_be_given_up(permanent)
        )
        or reaches_both_sides(ability.instruction)
        # ...and (kg4) a host effect worth something on one host and not
        # another by what the host is: Flowstone Blade's "+1/-1" killed its
        # controller's own Llanowar Elves at the flat score.
        or host_effect_by_the_moment(ability.instruction)
    ):
        worth = _land_ability_worth(game, player_index, candidate)
        if worth is None:
            return None
        if sweeps_what_its_counter_shelters(permanent.effective_card, ability.instruction):
            # **A sweep whose shelter the same card sells is scored by what
            # its rehearsal measured** (MRD W2G5), never below the flat score.
            # "{5}, {T}, Sacrifice this artifact: Destroy each nonland
            # permanent without a fate counter on it" (Oblivion Stone) is the
            # trade of a whole board, and at the flat 2.5 it tied the Stone's
            # own "put a fate counter" beside it — which the chooser's strict
            # comparison then kept, every turn, so the Stone never swept.
            # Narrowed to the pair on purpose: every ability giving up its
            # source scored this way outranked the flat abilities beside it
            # (sim_fingerprint TOR: Narcissism's sacrifice beat its own
            # madness discard and the seat lost the Narcissism it then needed).
            from dataclasses import replace

            return replace(candidate, score=max(candidate.score, worth))
        return candidate
    # **And every other ability** (kg4): proposed only where carried out on a
    # copy it moves something that lasts without leaving the seat worse off
    # (`_moves_something`) — in the main phase; at instant speed every
    # proposal is rehearsed by its caller, and held to more.
    #
    # **A one-shot given up** (`_exists_to_be_given_up`: Feldon's Cane,
    # Tormod's Crypt) keeps its flat score — the standing prices the
    # permanent at least a card, so a rehearsal of the whole cost would never
    # crack it — but is asked the same question **with the source given up on
    # both copies** (kg5): what is weighed is what the effect does now. Kept
    # flat, a Cane was cracked over an empty graveyard and a Crypt aimed at
    # one, each the seat's activation of the turn.
    one_shot = _gives_up_its_source(ability.cost) and _exists_to_be_given_up(permanent)
    if not _AT_INSTANT_SPEED.get() and not (
        _spends_a_one_shot_on_something(game, player_index, candidate) if one_shot
        else _moves_something(game, player_index, candidate)
    ):
        return None
    return candidate


#: What an ability that only changes what its own source — or the creature
#: its Aura enchants — **is** until end of turn compiles to: "{1}: This
#: creature becomes the creature type of your choice until end of turn" (the
#: Mistforms), "{1}: Enchanted creature becomes …" (Mistform Mask), with the
#: choosing step in front. Read off the compiled program, so it names no card.
_OWN_TYPE_SET_KINDS = frozenset({
    "set_self_creature_type", "set_enchanted_creature_type",
})

#: Every rewrite of what its source **is** that is rehearsed, not scored: the
#: type sets above, a base P/T read off a target (Riptide Mangler,
#: Sentinel, Sworn Defender) — worth nothing when the two powers are equal —
#: and turning itself face down ("{3}{U}{U}: Turn this creature face down.",
#: Mischievous Quanar, CR 708.2a), which makes it the blank 2/2 and is worth
#: only what turning it up again will buy: scored flat, the seat paid five
#: mana every main phase to shrink a 3/3 (SCG W1G5).
_OWN_REWRITE_KINDS = _OWN_TYPE_SET_KINDS | {
    "set_source_base_pt_from_target", "turn_self_face_down",
}


#: The host steps that untap it: worth nothing on a host that is untapped.
_HOST_UNTAP_KINDS = frozenset({"untap_enchanted_creature"})


def _host_refusal(game: Game, seat: int, permanent, instruction) -> bool:
    """Whether an ability of *permanent* whose whole effect lands on the
    permanent it is attached to (``ai_target_sides.host_effect_side``) is not
    one for *seat* to activate: attached to nothing, attached to a permanent
    on the other side from the one the effect helps, or an untap of a host
    that is already untapped.

    The Aura's controller pays and the host's controller gains. Asked nothing,
    the flat score rated "{U}: Untap enchanted creature" 2.5 wherever the
    Aura was: an AI seat holding Pemmin's Aura on a person's Krosan Warchief
    paid {U} to untap it in its main phase — the person's attacker, which then
    blocked — and again in its declare-attackers step (SCG Phase 5, smoke game
    1). On its own untapped creature the same untap moves nothing, and a cast
    that moves nothing is not proposed either. A host side of None (a bounce,
    a phase-out, a recolour: either side's, by the moment) is left to the
    score, as it always was.
    """
    from .handlers._targets import attached_host

    side = host_effect_side(instruction)
    if side is None:
        return False
    host = attached_host(game, permanent, last_known=False)
    if host is None:
        return True
    if (game.controller_index_of(host) == seat) != (side == "you"):
        return True
    return not host.tapped and all(
        step.kind in _HOST_UNTAP_KINDS for step in _effect_steps(instruction)
    )


def _sacrifice_is_weighed(cost) -> bool:
    """Whether *cost* sacrifices a printed number of permanents chosen as it
    is paid ("Sacrifice a Goblin", "Sacrifice two lands", "…another Orc or
    Goblin") — a trade the chooser prices by rehearsal. Not "any number of
    creatures" (Sword of the Ages: naming none pays nothing, and what to name
    is a search) nor "Sacrifice X lands" (an X this chooser does not
    announce beside a sacrifice)."""
    return cost.sacrifice_filter is not None and isinstance(cost.sacrifice_count, int)


def _exists_to_be_given_up(permanent) -> bool:
    """Whether *permanent* is a one-shot: a noncreature artifact with no
    triggered ability whose every activated ability gives it up
    (`_gives_up_its_source`) — Mossfire Egg, Chromatic Sphere, Urza's
    Bauble, Aeolipile, Bottle of Suleiman. (A creature's body, an Aura's host,
    a Seal's or an Aura of Silence's enchantment are what a rehearsal weighs.)

    It is worth nothing but the ability, and the standing prices every
    permanent at least a card (``ai_standing.permanent_worth``): rehearsed,
    the Egg's {R}{G} and card were worth less than the Egg, and it was never
    cracked (sim_fingerprint ODY, ICE). Its ability keeps its flat score, and
    is rehearsed with the source given up on both copies
    (``ai_activation_rehearsal._spends_a_one_shot_on_something``)."""
    if permanent.is_creature or not permanent.has_type("artifact"):
        return False
    program = compile_card_oracle(permanent.effective_card)
    if program.triggered_abilities or getattr(program, "static_lines", ()):
        return False
    abilities = usable_activated_abilities(program)
    return bool(abilities) and all(_gives_up_its_source(ability.cost) for ability in abilities)


def _sets_only_what_its_source_is(instruction) -> bool:
    """Whether *instruction* rewrites what its source or host is and nothing
    else (:data:`_OWN_REWRITE_KINDS`, behind any ``choose_creature_type``)."""
    steps = (
        tuple(instruction.payload.get("steps") or ())
        if instruction.kind == "sequence" else (instruction,)
    )
    kinds = {step.kind for step in steps}
    return bool(kinds & _OWN_REWRITE_KINDS) and kinds <= (
        _OWN_REWRITE_KINDS | {"choose_creature_type"}
    )


#: Abilities `choose_activation_action` passes over, as ``(permanent_id,
#: ability_index)`` (the index as `_abilities_weighed` gives it, None for a
#: non-land's first): the ones `ai_policy.choose_instant_speed_activation` has
#: rehearsed and turned down in the one decision it is making.
_ACTIVATIONS_SET_ASIDE: ContextVar[frozenset] = ContextVar(
    "ai_activations_set_aside", default=frozenset(),
)
#: True while `ai_policy.choose_instant_speed_activation` asks (see above).
_AT_INSTANT_SPEED: ContextVar[bool] = ContextVar("ai_at_instant_speed", default=False)


def _madness_discard_index(
    game: Game, seat: int, ability, required: dict[str, int], *,
    paying_for: "Permanent | None" = None,
) -> int | None:
    """The hand position a "Discard a card" cost should take: a card with
    **madness** (CR 702.35a) whose madness cost the seat's board can pay on
    top of the ability's own *required* mana — or None, the engine's default.

    The weight the madness offer's other half needs. Discarding such a card
    exiles it and offers it for its madness cost, so it is the card the cost
    costs least; whether the cast is then *worth* making is the offer's own
    rehearsed question (`ai_policy.choose_madness_cast`), asked when it is made. Only a
    chosen single discard: a discard at random is nobody's choice, and a cost
    of several cards is the engine's to fill in hand order. Of several such
    cards, the one the seat least wants to lose (``ai_prompt_picks.
    discard_order``'s ``discard_worth``), not the first in hand.
    """
    from .madness import printed_madness_cost
    from .mana_payment import mana_cost_from_symbols
    from .subject_filters import card_matches_any

    cost = ability.cost
    if (
        cost.discard_cards != 1 or cost.discard_at_random
        or cost.discard_whole_hand
    ):
        return None
    player = game.players[seat]
    payable: list[int] = []
    for index, card in enumerate(player.hand):
        madness = printed_madness_cost(card)
        if madness is None or not card_matches_any(
            card, cost.discard_filters, game=game, owner=seat,
        ):
            continue
        if game.enforce_mana_costs:
            combined = dict(required)
            for symbol, amount in (mana_cost_from_symbols(madness) or {}).items():
                combined[symbol] = combined.get(symbol, 0) + amount
            if any(combined.values()) and _plan_land_taps(
                game, player, combined, paying_for=paying_for,
            ) is None:
                continue
        payable.append(index)
    from .ai_prompt_picks import discard_order

    return discard_order(game, seat, payable, None)[0] if payable else None


#: Life a seat keeps back when it pays life for an ability of its own
#: (`choose_activation_action`): the number
#: `ai_foreign_activations.FOREIGN_ACTIVATION_LIFE_RESERVE` keeps for an
#: opponent's ability, for the same reason; a separate name because it is a
#: separate weight, and tuning one should not move the other.
ACTIVATION_LIFE_RESERVE = 10


def _hand_entry_has_a_card(
    game: Game, player_index: int, source: Permanent, instruction, *, cost=None,
) -> bool:
    """Whether every "put a … card from your hand onto the battlefield" step of
    an ability (``ai_valuation.hand_entry_steps``) has a card to put.

    The candidates are the engine's own (``put_from_hand_candidates``), with
    "of the chosen type" resolved off the source the way the handler resolves
    it (``_resolve_chosen_subtype``), so the policy and the resolution cannot
    disagree about which cards the step admits.

    "…a creature card from your hand that shares a creature type with **each
    creature tapped this way**" (Cryptic Gateway) is resolved against the
    creatures the activation's tap cost will tap — this policy names none, so
    the engine's own deterministic pick (``_choose_tap_cost_permanents``) —
    through the handler's own resolver. Unresolved, the matcher refuses every
    card, and the Gateway was an artifact this seat never once activated.
    """
    from types import SimpleNamespace

    from .handlers._chosen import (SHARES_CREATURE_TYPE_WITH,
                                   _resolve_chosen_subtype,
                                   resolve_shared_creature_type)
    from .handlers.hand import (put_from_hand_candidates,
                                resolve_source_counted_mana_value)

    player = game.players[player_index]
    for payload in hand_entry_steps(instruction):
        described = _resolve_chosen_subtype(
            dict(payload.get("card_filter") or {}), source
        )
        # "…with mana value equal to the number of charge counters on this
        # artifact" (Aether Vial), through the handler's own resolver.
        described = resolve_source_counted_mana_value(described, source)
        if described.get(SHARES_CREATURE_TYPE_WITH) and cost is not None and getattr(
            cost, "tap_count", 0
        ):
            tapped = game._choose_tap_cost_permanents(
                cost, game._tap_cost_candidates(cost, player_index), None,
            )
            described = resolve_shared_creature_type(
                described,
                SimpleNamespace(
                    choices={"tapped_set_for_cost": tapped}, caster=player,
                    trigger_context=None,
                ),
                game,
            )
        if not put_from_hand_candidates(
            game, {**payload, "card_filter": described}, player
        ):
            return False
    return True


def _graveyard_sweep_favours_the_seat(
    game: Game, player_index: int, instruction
) -> bool:
    """Whether every "return all <cards> from <graveyard(s)> to the
    battlefield" step of an ability returns more cards for *player_index*
    than for the rest of the table — True for an ability with no such step.

    The matcher is the handler's own (``handlers._filters._card_matches_filter``),
    so the count is of exactly the cards the resolution would move. "Each
    player returns" is a sweep over every living seat, and what comes back
    under an opponent's control is a cost, not a gain; a sweep of the seat's
    own pile only needs one card.
    """
    from .handlers._filters import _card_matches_filter

    for step in _effect_steps(instruction):
        if step.kind != "return_all_cards_from_graveyard":
            continue
        payload = step.payload or {}
        if payload.get("destination", "battlefield") != "battlefield":
            continue
        described = dict(payload.get("filter") or {})

        def returned(seat: int) -> int:
            player = game.players[seat]
            return sum(
                1 for card in player.graveyard
                if _card_matches_filter(card, described, game=game, owner=player)
            )

        own = returned(player_index)
        if payload.get("who") == "each_player":
            others = sum(
                returned(seat) for seat, player in enumerate(game.players)
                if seat != player_index and not player.lost
            )
            if own <= others:
                return False
        elif own == 0:
            return False
    return True

