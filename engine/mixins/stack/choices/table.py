"""The prompt table: one ``register_choice`` row per interactive decision.

The index of every prompt in the engine — what answers it, what a
non-interactive seat does instead, and how the web layer renders, gates and
refuses around it (``engine/pending_choices.py`` says what each field means).
A row names its resolver and default through the game (``game._resolve_…``),
so the methods live with their family in the modules beside this one and this
module imports none of them.

**Row order is behaviour.** ``Game.iter_pending_prompts`` yields owed prompts
in registration order, and the AI's drain, ``waiting_prompt`` and
``blocking_prompt`` each act on the first one it yields. That is why the rows
stay one table here rather than travelling with their families: split across
modules, the order would be whichever module happened to import first. Append a
new kind at the bottom.
"""

from __future__ import annotations

from .... import madness as _madness, piles
from ....pending_choices import register_choice
from ....trigger_order import ORDER_TRIGGERS, order_is_open


# ---------------------------------------------------------------------------
# The prompt table
# ---------------------------------------------------------------------------
#
# One row per interactive decision in the engine. ``resolve`` applies the
# answering seat's response, ``default`` is what every other seat does, and the
# rest is what the web layer needs to render the prompt, gate the actions
# around it and route the action that answers it. A kind whose behaviour lives
# in another mixin is registered here anyway, so this stays the one index.

register_choice(
    "effect_order",
    resolve=lambda game, choice, r: game._resolve_effect_order(choice, r["option_index"]),
    default=lambda game, choice: game._default_effect_order(choice),
    action="effect_order_confirm",
    prompt_key="effect_order",
    blocked_detail="choose which effect applies first before other actions",
    # The event this interrupts has not happened yet — a draw that is waiting on
    # the answer has not drawn, damage waiting on it has not been dealt — so no
    # seat should be acting on a board that is mid-event.
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The one kind that has always suspended: CR 616.1e stops an event dead, and
    # the loop that event was a step of has to stop with it. The flag it used to
    # set by hand in engine/replacements.py is this field.
    suspends=True,
)

register_choice(
    "hand_to_library",
    resolve=lambda game, choice, r: game._resolve_hand_to_library(
        choice, r["hand_indices"], bool(r.get("to_bottom")),
    ),
    default=lambda game, choice: game._default_hand_to_library(choice),
    action="hand_to_library_confirm",
    prompt_key="hand_to_library",
    blocked_detail="choose which cards go back on top of your library",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Brainstorm draws three and then puts two back, and the two are steps of
    # one resolution: nothing after the prompt may read a hand the answer has
    # not reshaped yet (CR 608.2, CR 117.3b).
    suspends=True,
)

register_choice(
    "search_library",
    # `zone` defaults so a caller written before the graveyard existed — and the
    # web action, which sends it only when the client picked one — still names
    # the library. A counted search ("up to two basic land cards") is answered
    # whole through `picks`; the single-find shape keeps its one index.
    resolve=lambda game, choice, r: (
        game._resolve_search_library_picks(choice, r["picks"])
        if "picks" in r
        else game._resolve_search_library(
            choice, r["library_index"], r.get("zone", "library")
        )
    ),
    default=lambda game, choice: game._default_search_library(choice),
    action="search_library_confirm",
    # "Fail to find" (CR 701.23b) is the second answer, not a way around the
    # prompt — and the only one available when nothing matches the restriction.
    also_answers=("search_library_decline",),
    prompt_key="search_library",
    blocked_detail="complete library search before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # A search is armed for AI seats too and drained by the auto-resolver; the
    # prompt is rendered for whoever still owes it.
    hidden_for_ai=False,
    # A search takes a card out of the library and shuffles what is left, so any
    # later step of the same resolution reads a library the answer decided.
    suspends=True,
)

register_choice(
    "search_destination",
    # A counted search whose printed slots differ ("put one onto the
    # battlefield tapped and the other into your hand") asks its finder which
    # found card fills which slot. The finds are already made and shown — this
    # is only where each lands, so it works the same over any zone a picker
    # took the cards from.
    resolve=lambda game, choice, r: game._resolve_search_destination(
        choice, r.get("assignments") or []
    ),
    default=lambda game, choice: game._default_search_destination(choice),
    action="search_destination_confirm",
    prompt_key="search_destination",
    blocked_detail="choose where each found card goes before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The cards land only when the answer is applied, so a later step of the
    # same resolution must not read a board they have not reached yet.
    suspends=True,
)

register_choice(
    "look_top_pick",
    resolve=lambda game, choice, r: game._resolve_look_top_pick(choice, r.get("keep_index", -1)),
    default=lambda game, choice: game._default_look_top_pick(choice),
    action="look_top_pick_confirm",
    prompt_key="look_top_pick",
    blocked_detail="choose a card to keep before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer reshapes the library, and CR 608.2n's move to the graveyard
    # is a later step of the same resolution — the scry discipline exactly.
    suspends=True,
)

register_choice(
    "tap_any_number",
    resolve=lambda game, choice, r: game._resolve_tap_any_number(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_tap_any_number(choice),
    action="tap_any_number_confirm",
    prompt_key="tap_any_number",
    blocked_detail="choose which permanents to tap before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # "For each creature tapped this way, that player chooses…" (Raiding Party)
    # is a later step of the same resolution, and what it walks is exactly what
    # this prompt records — so the loop it is a step of has to stop until every
    # seat has answered (CR 608.2, CR 608.2e).
    #
    # Siege Striker, the other card that arms this, needs neither: its boost is
    # applied by this choice's own resolver, which is why the two printed
    # sentences fuse into one instruction there. Suspending costs it nothing —
    # the prompt is the last step of what armed it — and one prompt shared by
    # both cards is cheaper than two that differ by a flag.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish
    # before the sentence behind it can read what was tapped, and the stated
    # default is taken where the effect stands.
    default_at_arm=True,
)

register_choice(
    "untap_up_to",
    resolve=lambda game, choice, r: game._resolve_untap_up_to(choice, r.get("permanent_ids") or []),
    default=lambda game, choice: game._default_untap_up_to(choice),
    action="untap_up_to_confirm",
    prompt_key="untap_up_to",
    blocked_detail="choose which permanents to untap before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Deliberately not suspending: the untap is the last step of the effect
    # that armed it, so nothing later in the same resolution reads the answer.
)

register_choice(
    "search_exile_cards",
    resolve=lambda game, choice, r: game._resolve_search_exile(choice, r.get("picks") or []),
    default=lambda game, choice: game._default_search_exile(choice),
    action="search_exile_confirm",
    prompt_key="search_exile",
    blocked_detail="complete your search before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The picks are what the next step of the same resolution ("You may cast
    # them this turn.") grants permission over, so that step must wait.
    suspends=True,
)

register_choice(
    "reorder_library",
    resolve=lambda game, choice, r: game._resolve_reorder_library(choice, r["new_order"], r["shuffle"]),
    default=lambda game, choice: game._default_reorder_library(choice),
    action="reorder_library_confirm",
    prompt_key="reorder_library",
    blocked_detail="complete library reorder before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # Same reason as scry: the answer *is* what the next card off the library
    # will be.
    suspends=True,
)

register_choice(
    "scry",
    resolve=lambda game, choice, r: game._resolve_scry(choice, r["card_order"], r["bottom_count"]),
    default=lambda game, choice: game._default_scry(choice),
    action="scry_confirm",
    prompt_key="scry",
    blocked_detail="complete scry before other actions",
    # Same treatment as reorder_library: the scry suspends a resolution, so the
    # whole game waits and a spectator sees that it is waiting. An AI seat stays
    # queued and is drained by the auto-resolver, which keeps ordering
    # deterministic per seed.
    blocks_every_seat=True,
    spectator_visible=True,
    # "Scry 1. Draw a card." is the shape this field exists for: the draw is a
    # later step of the same resolution and must see the library the scry
    # arranged, not the one it was handed.
    suspends=True,
)

register_choice(
    "revealed_hand_pick",
    # ``.get``, not ``[...]``: an answer with **no** index is the chooser
    # declining, which "choose **up to** X cards from it" (Discordant Dirge)
    # permits and every earlier printing does not. The resolver is what decides
    # whether the words were printed; a subscript here would make the decline a
    # KeyError before it could be judged.
    resolve=lambda game, choice, r: game._resolve_revealed_hand_pick(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_revealed_hand_pick(choice),
    action="revealed_hand_pick_confirm",
    prompt_key="revealed_hand_pick",
    blocked_detail="choose a card from the revealed hand before other actions",
    # "…then you choose a card … from it. **Search that player's graveyard,
    # hand, and library for all cards with the same name as the chosen card**…"
    # (Lobotomy.) The step behind the pick reads what it chose, so it must not
    # run while the choice is still owed (CR 608.2, CR 117.3b) — the same reason
    # the search beside it suspends, and inert for every printing that has
    # nothing behind the pick.
    suspends=True,
    # The revealed hand is public from the moment it is revealed (CR 701.20),
    # so a spectator sees the prompt exactly as the choosing seat does.
    spectator_visible=True,
)

register_choice(
    "opponent_picks_revealed",
    resolve=lambda game, choice, r: game._resolve_opponent_picks_revealed(
        choice, r.get("index")
    ),
    default=lambda game, choice: game._default_opponent_picks_revealed(choice),
    action="opponent_picks_revealed_confirm",
    prompt_key="opponent_picks_revealed",
    blocked_detail="choose one of the revealed cards before other actions",
    # The draw behind the pick is a later step of the same resolution
    # (CR 608.2), and it must not run against a library the answer is about to
    # change \u2014 so arming this stops the sequence until it is answered.
    suspends=True,
    # A non-interactive chooser answers where the offer stands: the resolution
    # is suspended on this prompt, and a seat that never queues would hold it
    # open for the rest of the game.
    default_at_arm=True,
    # A reveal is public: CR 701.20 reveals the cards to every player, and so
    # is whose choice this is.
    spectator_visible=True,
)

register_choice(
    "discard",
    resolve=lambda game, choice, r: game._resolve_discard(choice, r["hand_indices"], r["to_library"]),
    default=lambda game, choice: game._default_discard(choice),
    action="discard_confirm",
    prompt_key="discard_select",
    blocked_detail="complete discard before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # "Discard X cards, then <do something for each card discarded this way>"
    # (Recall) is the shape: the step behind the discard has to see the cards
    # that were actually discarded, not the hand as it stood when the prompt was
    # armed. CR 608.2 / CR 117.3b — nothing else in the resolution happens until
    # the last of its prompts is answered.
    suspends=True,
)

register_choice(
    "balance",
    resolve=lambda game, choice, r: game._resolve_balance(
        choice, r["land_indices"], r["creature_indices"], r["hand_indices"]
    ),
    default=lambda game, choice: game._default_balance(choice),
    action="balance_confirm",
    prompt_key="balance_select",
    blocked_detail="complete Balance sacrifices before other actions",
)

register_choice(
    "sacrifice",
    resolve=lambda game, choice, r: game._resolve_sacrifice(choice, r["indices"]),
    default=lambda game, choice: game._default_sacrifice(choice),
    action="sacrifice_confirm",
    prompt_key="sacrifice_select",
    blocked_detail="complete forced sacrifice before other actions",
    default_at_arm=True,
    spectator_visible=True,
    # "Sacrifice an artifact. **If you do**, search your library…" (Transmute
    # Artifact): what the player gives up decides what the rest of the same
    # resolution may find, so the rest has to wait for the answer. Only an
    # interactive seat ever queues this — `default_at_arm` takes the
    # deterministic answer before the flag is set — so headless and AI play run
    # exactly as they did.
    suspends=True,
)

register_choice(
    "mana_color_choice",
    resolve=lambda game, choice, r: game._resolve_mana_color_choice(
        choice, r.get("color")
    ),
    default=lambda game, choice: game._default_mana_color_choice(choice),
    action="mana_color_choice_confirm",
    prompt_key="mana_color_choice",
    blocked_detail="choose the color of the mana before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # CR 608.2d's choice is the whole of what the clause does, and nothing
    # behind it in the same resolution reads the answer — the mana lands in a
    # pool, not in the scratchpad. So the offer is taken inline by every
    # non-interactive seat, which is what keeps a seeded AI run producing the
    # mana it always produced.
    default_at_arm=True,
)

register_choice(
    "color_set_choice",
    resolve=lambda game, choice, r: game._resolve_color_set_choice(
        choice, r.get("colors")
    ),
    default=lambda game, choice: game._default_color_set_choice(choice),
    action="color_set_choice_confirm",
    prompt_key="color_set_choice",
    blocked_detail="choose the colour or colours before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The colour is the whole of what this resolution does; nothing after it in
    # the same trigger reads the answer, so the loop has nothing to wait for.
    default_at_arm=True,
)

register_choice(
    "revealed_draw_buyout",
    resolve=lambda game, choice, r: game._resolve_revealed_draw_buyout(
        choice, r["accept"]
    ),
    default=lambda game, choice: game._default_revealed_draw_buyout(choice),
    action="revealed_draw_buyout_confirm",
    prompt_key="revealed_draw_buyout",
    blocked_detail="answer the revealed-card offer before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer decides what happens to the card the drawing player is about to
    # draw -- and whether the seat behind you is asked at all -- so the replaced
    # draw genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the draw it replaced has to
    # finish, so the stated default is taken where the offer stands.
    default_at_arm=True,
)

register_choice(
    "pay_life_to_save",
    resolve=lambda game, choice, r: game._resolve_pay_life_to_save(choice, r["accept"]),
    default=lambda game, choice: game._default_pay_life_to_save(choice),
    action="pay_life_to_save_confirm",
    prompt_key="pay_life_to_save",
    blocked_detail="answer the pay-to-save offer before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer decides what the *next* step of the same resolution does with
    # this permanent — and, one step later, whether the seat behind you is
    # asked about it at all — so the loop genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the sweep has to finish, and the
    # stated default is taken where the offer stands. That is also what keeps
    # AI and headless play free of the suspension above.
    default_at_arm=True,
)

register_choice(
    "optional_pay",
    resolve=lambda game, choice, r: game._resolve_optional_pay(
        choice, r["accept"], r.get("option"), asked=True,
    ),
    default=lambda game, choice: game._default_optional_pay(choice),
    action="resolve_optional_pay",
    prompt_key="optional_pay",
    # The kind outgrew its first card: it now carries any optional cost or
    # action, on a trigger or on a whole spell (Twiddle, Rebirth), so the
    # message names the offer rather than the one card it was written for.
    blocked_detail="answer the optional-cost offer before other actions",
    # An offer priced in mana is paid by tapping for it, and the engine taps
    # only free land abilities on a payer's behalf — so the seat's own mana
    # abilities answer the offer as much as the yes does (CR 605.3a), exactly
    # as they do for ``mana_payment`` below. The web layer admits a *mana*
    # ability and nothing else while one of these is owed
    # (``web/actions.py``): nobody has priority in the middle of a resolution.
    also_answers=("tap", "activate"),
)

register_choice(
    "trigger_target",
    resolve=lambda game, choice, r: game._resolve_trigger_target(
        choice, r.get("permanent_id"), r.get("seat"), r.get("permanent_ids"),
        graveyard_index=r.get("graveyard_index"), stack_item=r.get("stack_item"),
        amounts=r.get("amounts"), graveyard_indices=r.get("graveyard_indices"),
    ),
    default=lambda game, choice: game._default_trigger_target(choice),
    action="trigger_target_confirm",
    prompt_key="trigger_target",
    blocked_detail="choose the triggered ability's target before other actions",
    # The choice is part of putting the ability on the stack (CR 603.3d), so a
    # non-interactive seat takes it there and then — nothing queues, and
    # headless and AI play run exactly as they did.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    ORDER_TRIGGERS,
    resolve=lambda game, choice, r: game._resolve_order_triggers(choice, r["order"]),
    default=lambda game, choice: game._default_order_triggers(choice),
    action="order_triggers_confirm",
    prompt_key="order_triggers",
    blocked_detail="choose the order of your triggered abilities before other actions",
    # CR 603.3b's choice is part of putting the abilities on the stack, like
    # a trigger's target (CR 603.3d) above: a seat nobody asks keeps the order
    # they were pushed in there and then, nothing queues, and a seeded run
    # reproduces exactly.
    default_at_arm=True,
    spectator_visible=True,
    # Owed while two of its objects are still on the stack to be ordered
    # (``trigger_order.order_is_open``) — a target prompt answered meanwhile
    # can remove one (CR 603.3d).
    is_open=order_is_open,
)

register_choice(
    "reflexive_target",
    resolve=lambda game, choice, r: game._resolve_reflexive_target(
        choice, r["permanent_id"]
    ),
    default=lambda game, choice: game._default_reflexive_target(choice),
    action="reflexive_target_confirm",
    prompt_key="reflexive_target",
    blocked_detail="choose the reflexive trigger's target before other actions",
)

register_choice(
    "copy_spell_target",
    resolve=lambda game, choice, r: game._resolve_copy_spell_target(choice, r),
    default=lambda game, choice: game._default_copy_spell_target(choice),
    action="copy_spell_target_confirm",
    prompt_key="copy_spell_target",
    blocked_detail="choose the copy's target before other actions",
    # CR 707.10: the copy's targets are chosen as the copy is created, which is
    # part of the resolution that created it — so a non-interactive seat answers
    # there and then and nothing queues. That is also what keeps the headless
    # path honest: `_settle()` drains the stack without pausing, and a prompt
    # left queued here would be answered after the copy it was meant to aim.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "discard_unless_pay_life",
    resolve=lambda game, choice, r: game._resolve_discard_unless_pay_life(
        choice, r["accept"]
    ),
    default=lambda game, choice: game._default_discard_unless_pay_life(choice),
    action="discard_unless_pay_life_confirm",
    prompt_key="discard_unless_pay_life",
    blocked_detail="answer the pay-or-discard offer before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The offer is armed from inside a CR 614 draw replacement, which may be
    # replacing a draw that is itself one step of a resolution. Nothing of that
    # resolution may run until this is answered (CR 608.2).
    suspends=True,
    # A non-interactive seat never queues it: a draw replacement has to finish
    # where it stands, and the stated default is taken at once. That is also
    # what keeps AI and headless play free of the suspension above.
    default_at_arm=True,
)

register_choice(
    "hand_reveal",
    resolve=lambda game, choice, r: game._dismiss_hand_reveal(choice),
    default=lambda game, choice: game._dismiss_hand_reveal(choice),
    action="dismiss_hand_reveal",
    prompt_key="hand_reveal",
    # Not a decision — the viewer has already seen the hand. Nothing waits on it.
    blocked_detail=None,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "draw_up_to",
    resolve=lambda game, choice, r: game._resolve_draw_up_to(choice, r["number"]),
    default=lambda game, choice: game._default_draw_up_to(choice),
    action="draw_up_to_confirm",
    prompt_key="draw_up_to",
    blocked_detail="say how many cards you draw before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # "Each player may draw up to two cards. **For each card less than two a
    # player draws this way**, that player gains 2 life." (Truce.) The sentence
    # behind this one is sized from every seat's answer, so nothing in the
    # resolution may run until the last of them is given — the same reason the
    # discard prompt beside it suspends (CR 608.2).
    suspends=True,
)

register_choice(
    "pay_any_amount",
    resolve=lambda game, choice, r: game._resolve_pay_any_amount(choice, r["amount"]),
    default=lambda game, choice: game._default_pay_any_amount(choice),
    action="pay_any_amount_confirm",
    prompt_key="pay_any_amount",
    blocked_detail="say how much mana you pay before other actions",
    # Every seat is offered at once and the sentence behind the offer reads all
    # of their answers, so the board must not move under any of them (CR 608.2).
    blocks_every_seat=True,
    # How much each player paid is public: the mana leaves visible pools and
    # taps visible lands.
    spectator_visible=True,
    # "… equal to the amount of mana **they paid this way**" is a later step of
    # the same resolution, so it may not run before the last answer exists
    # (CR 608.2, CR 117.3b).
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default (pay nothing) is taken where the offer stands.
    default_at_arm=True,
)

register_choice(
    "number_choice",
    resolve=lambda game, choice, r: game._resolve_number_choice(choice, r["number"]),
    default=lambda game, choice: game._default_number_choice(choice),
    action="number_choice_confirm",
    prompt_key="number_choice",
    blocked_detail="choose a number before other actions",
    # Tetravus's removal is one step of a sentence whose next step reads the
    # answer ("create **that many** … tokens"), so the loop it is a step of has
    # to stop until the number exists. Shapeshifter's two armings sit at the end
    # of what they are part of, so suspending costs them nothing.
    suspends=True,
)

register_choice(
    "secret_number",
    resolve=lambda game, choice, r: game._resolve_secret_number(choice, r.get("number")),
    default=lambda game, choice: game._default_secret_number(choice),
    action="secret_number_confirm",
    prompt_key="secret_number",
    blocked_detail="every player chooses a hidden number before anything else happens",
    # Every seat is asked at once and the spell is mid-resolution: a seat that
    # has answered may not act while another is still choosing (CR 608.2).
    blocks_every_seat=True,
    # Deliberately not ``spectator_visible``: a seatless viewer is shown no
    # seat's prompt, and nothing about any answer, until the reveal is logged.
    #
    # "Each player loses life equal to **the number of items they revealed**"
    # is a later step of the same resolution and reads every seat's answer, so
    # none of it may run before the last one exists (CR 608.2, CR 117.3b).
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish,
    # and answering where the prompt is armed is what makes that seat commit
    # before any other answer exists.
    default_at_arm=True,
)

register_choice(
    "bid_life",
    resolve=lambda game, choice, r: game._resolve_bid_life(choice, r.get("number")),
    default=lambda game, choice: game._default_bid_life(choice),
    action="bid_life_confirm",
    # Passing is a second *answer*, not a way around the prompt -- the same
    # shape a search's "fail to find" takes. It has to be an action of its own
    # because the bid is a number and there is no number that means "no".
    also_answers=("bid_life_pass",),
    prompt_key="bid_life",
    blocked_detail="answer the bidding before other actions",
    # The spell is resolving and the board is mid-effect: whoever wins has not
    # lost the life or taken the creature yet, so nobody should be acting on
    # what they can see (CR 608.2).
    blocks_every_seat=True,
    # The offer is made in the open -- every seat can see what the standing bid
    # is, which is the whole of what makes the next offer a decision.
    spectator_visible=True,
    # A non-interactive seat never queues it: the auction is one resolution and
    # it has to finish, so the stated default (pass) is taken where the offer
    # stands. Without this an AI or headless seat would hold the spell on the
    # stack for the rest of the game.
    default_at_arm=True,
    # The two printed sentences behind the bidding -- the life loss and the
    # control change -- are performed by the *last* answer, so no later step of
    # this resolution may run before it (CR 608.2). Mages' Contest is the card
    # with a later step: "If you win the bidding, counter that spell" reads who
    # won, and waits here for the answer that decides it.
    suspends=True,
)

register_choice(
    "land_type_choice",
    resolve=lambda game, choice, r: game._resolve_land_type(choice, r["land_type"]),
    # The provisional default stamped when the Aura attached is an Island, so
    # taking it again is what a non-interactive controller does.
    # …unless the sentence offered a list without one (``default_land_type_
    # choice``): the default must be an answer the resolver accepts.
    default=lambda game, choice: game._resolve_land_type(
        choice, game.default_land_type_choice(choice)
    ),
    action="land_type_confirm",
    prompt_key="land_type_choice",
    # Phantasmal Terrain arms this as it enters, and its own comment says "the
    # spell never visibly resolves the land change before the player finishes
    # the choice" — which needs the game to actually wait. The Aura is already
    # on the battlefield (not a spell held on the stack), so it is armed with
    # ``_stack_item=None``: holds priority, holds no finished object.
    blocked_detail="choose the land type before other actions",
    # And nothing behind the choice may happen before it is made (CR 608.2c:
    # the instructions are followed in the order written). "Target land
    # becomes the basic land type of your choice until end of turn. / Draw a
    # card." (Shimmering Mirage) drew the card while the type was still being
    # chosen — the game waited, but only after the step behind the prompt had
    # run. ``scry``'s arrangement, for Opt's reason, and like ``scry`` without
    # ``default_at_arm``: the kind stays queued for every seat, which is what
    # its callers and thirty-odd tests are written around.
    suspends=True,
)

register_choice(
    "land_type_swap",
    resolve=lambda game, choice, r: game._resolve_land_type_swap(
        choice, r.get("from_type"), r.get("to_type")
    ),
    # The default pair is computed where the prompt is armed, against the board
    # as it then stood, and applied here — the swap *is* the effect, so a
    # default that merely discarded the prompt would resolve the spell having
    # done nothing.
    default=lambda game, choice: game._resolve_land_type_swap(
        choice, choice.data.get("default_from"), choice.data.get("default_to")
    ),
    action="land_type_swap_confirm",
    prompt_key="land_type_swap",
    blocked_detail="choose the two land types before other actions",
)

register_choice(
    "card_type_choice",
    resolve=lambda game, choice, r: game._resolve_card_type_choice(
        choice, r.get("card_type")
    ),
    # The handler stamps its deterministic default on the source before arming,
    # so a non-interactive seat has nothing left to apply and the sweep behind
    # this prompt runs at once with that answer.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="card_type_choice_confirm",
    prompt_key="card_type_choice",
    blocked_detail="choose a card type before other actions",
    # A non-interactive seat takes the default *inline*, because the resolution
    # this interrupts has to finish: the sweep is the next step of the same
    # sequence.
    default_at_arm=True,
    # And an interactive seat's answer has to arrive before that sweep runs —
    # a one-shot that had already phased out the default's type would make the
    # prompt a lie. See `_resolve_card_type_choice` for why `enter_choice`,
    # whose readers are continuous effects, does not need this and must not
    # gain it.
    suspends=True,
)

register_choice(
    "creature_type_choice",
    resolve=lambda game, choice, r: game._resolve_creature_type_choice(
        choice, r.get("creature_type")
    ),
    # The handler stamps its deterministic default into the scratchpad before
    # arming, so a non-interactive seat has nothing left to apply and the sweep
    # behind this prompt runs at once with that answer — ``card_type_choice``'s
    # arrangement, and for its reason.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="creature_type_choice_confirm",
    prompt_key="creature_type_choice",
    blocked_detail="choose a creature type before other actions",
    default_at_arm=True,
    # And an interactive seat's answer has to arrive before the sweep runs: an
    # answer that landed after the board had already been swept on the default
    # would change nothing, which is a prompt that lies.
    suspends=True,
    # Which creature type a player named is announced in the open (CR 608.2d is
    # applied where everyone can see), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "color_choice",
    resolve=lambda game, choice, r: game._resolve_color_choice(
        choice, r.get("mana_color")
    ),
    # The handler stamps its deterministic default on the source and in the
    # scratchpad before arming, so a non-interactive seat has nothing left to
    # apply and whatever reads the colour runs at once with that answer —
    # ``card_type_choice``'s arrangement, and for its reason.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="color_choice_confirm",
    prompt_key="color_choice",
    blocked_detail="choose a color before other actions",
    default_at_arm=True,
    # And an interactive seat's answer has to arrive before the step behind it
    # runs: Scrying Glass counts the revealed hand against the chosen colour in
    # the same resolution, and an answer that landed after the count would
    # change nothing at all — a prompt that lies.
    suspends=True,
    # Which colour a player named is announced in the open (CR 608.2d is applied
    # where everyone can see), so a seatless viewer may see the question — the
    # same reading ``creature_type_choice`` takes of the same rule.
    spectator_visible=True,
)

register_choice(
    "mana_payment",
    resolve=lambda game, choice, r: game._resolve_mana_payment(
        choice, r["pay"], asked=True,
    ),
    default=lambda game, choice: game._default_mana_payment(choice),
    action="confirm_mana_payment",
    prompt_key="mana_payment",
    # "…unless its controller pays {X}" (Power Sink) is paid *during* the
    # counterspell's resolution, so the game genuinely waits on it — this used
    # to say so by being named in ``pass_priority`` instead, which is a second
    # place to state one fact and the reason every other prompt was left out of
    # it. Paying means tapping lands and activating mana abilities, so those two
    # answer the prompt as much as the confirm does; everything else waits.
    blocked_detail="pay for the spell on the stack before other actions",
    also_answers=("tap", "activate"),
)

register_choice(
    "player_choice",
    resolve=lambda game, choice, r: game._resolve_player_choice(choice, r.get("seat")),
    default=lambda game, choice: game._default_player_choice(choice),
    action="player_choice_confirm",
    prompt_key="player_choice",
    blocked_detail="choose a player for the resolving spell before other actions",
    # The steps behind this one in the same sentence read the answer - the pick
    # of "one of those spells" is narrowed by it, and the damage lands on the
    # seat it names - so the loop they are part of has to stop until it exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Who cast what this turn is public information (no CR 400.2 hidden zone is
    # involved), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "cast_choice",
    resolve=lambda game, choice, r: game._resolve_cast_choice(choice, r.get("cast_index")),
    default=lambda game, choice: game._default_cast_choice(choice),
    action="cast_choice_confirm",
    prompt_key="cast_choice",
    blocked_detail="choose one of those spells before other actions",
    # Armed by the *answer* to the player choice above, and read by the damage
    # step behind it - the chain of decisions that stays one resolution.
    suspends=True,
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "madness_cast",
    resolve=lambda game, choice, r: _madness.resolve_madness_offer(game, choice, r),
    default=lambda game, choice: _madness.default_madness_offer(game, choice),
    action="madness_cast_confirm",
    prompt_key="madness_cast",
    # CR 608.2g: the cast is made *during* the trigger's resolution, so the
    # game waits on the answer and the trigger stays on the stack under the
    # spell the answer casts. Paying for that cast is CR 601.2g's mana
    # abilities, so a land's tap and a mana ability answer it as much as the
    # confirm does — the arrangement every prompt paid in mana has.
    blocked_detail="decide whether to cast the exiled card for its madness cost",
    also_answers=("tap", "activate"),
    # A seat nobody asks answers where the offer stands, inside the
    # resolution, with the AI's rehearsed cast chooser — the same moment a
    # person's cast would be made.
    default_at_arm=True,
    # The card is in exile (a public zone) and the offer is the rule's, so a
    # seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "retarget_choice",
    resolve=lambda game, choice, r: game._resolve_retarget_choice(
        choice, r.get("target_index")
    ),
    default=lambda game, choice: game._default_retarget_choice(choice),
    action="retarget_choice_confirm",
    prompt_key="retarget_choice",
    blocked_detail="choose the spell's new target before other actions",
    # The step behind this one in the same sentence writes the answer onto the
    # stack item, so Deflection's resolution is not over until it exists
    # (CR 608.2).
    suspends=True,
    # A non-interactive seat never queues it, for ``player_choice``'s reason:
    # the resolution has to finish, and the stated default is taken where the
    # effect stands.
    default_at_arm=True,
    # What a spell on the stack targets is public (CR 601.2c is announced in
    # the open), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "permanent_choice",
    resolve=lambda game, choice, r: game._resolve_permanent_choice(choice, r["permanent_id"]),
    default=lambda game, choice: game._default_permanent_choice(choice),
    action="permanent_choice_confirm",
    prompt_key="permanent_choice",
    blocked_detail="choose a permanent for the resolving spell before other actions",
    # The steps behind this one in the same sentence are what read the answer
    # (Enchantment Alteration's attach), so the loop they are part of has to
    # stop until it exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "permanent_set_choice",
    resolve=lambda game, choice, r: game._resolve_permanent_set_choice(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_permanent_set_choice(choice),
    action="permanent_set_choice_confirm",
    prompt_key="permanent_set_choice",
    blocked_detail="choose the permanents for the resolving effect before other actions",
    # "Then destroy all Plains that weren't chosen this way by any player" is a
    # later step of the same resolution and reads exactly what this records, so
    # nothing may run past it (CR 608.2). The iteration behind it arms the next
    # one, which is how a chain of decisions stays one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "flip_again",
    resolve=lambda game, choice, r: game._resolve_flip_again(
        choice, bool(r.get("accept", True))
    ),
    default=lambda game, choice: game._default_flip_again(choice),
    action="flip_again_confirm",
    prompt_key="flip_again",
    blocked_detail="decide whether to flip again before other actions",
    # The answer is whether the *rest of this resolution* happens at all, so
    # nothing may run past it (CR 608.2) — and the round it starts arms the next
    # offer, which is how a chain of decisions stays one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the stated default is to stop, and
    # taking it where the offer stands is what keeps AI and headless play from
    # holding a resolution open on a decision nobody will make.
    default_at_arm=True,
    # Both players' life totals are public, and so is whose decision it is.
    hidden_for_ai=False,
    spectator_visible=True,
)

register_choice(
    "repeat_process",
    resolve=lambda game, choice, r: game._resolve_repeat_process(
        choice, bool(r.get("accept", True))
    ),
    default=lambda game, choice: game._default_repeat_process(choice),
    action="repeat_process_confirm",
    prompt_key="repeat_process",
    blocked_detail="decide whether to repeat the process before other actions",
    # The answer is whether the *rest of this resolution* happens at all, so
    # nothing may run past it (CR 608.2) — and the round it starts arms the
    # next question, which is how a chain of decisions stays one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the stated default is to stop, and
    # taking it where the question stands is what keeps AI and headless play
    # from holding a resolution open on a decision nobody will make.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "exile_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_exile_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_exile_from_hand_choice(choice),
    action="exile_from_hand_confirm",
    prompt_key="exile_from_hand_choice",
    blocked_detail="choose a card to exile before other actions",
    # The sentence behind this one reads what was exiled ("you may cast that
    # card for as long as it remains exiled"), so nothing after it may run
    # until it is answered (CR 608.2).
    suspends=True,
    # …and a non-interactive seat therefore never queues it: the rest of the
    # activation — the charge counter and the mana note — has to finish, which
    # is the same reason `cast_choice` and `pay_life_to_save` take their default
    # where the offer stands.
    default_at_arm=True,
    # A hand is hidden (CR 400.2), so the options are the chooser's alone.
    hidden_for_ai=False,
)

register_choice(
    "exile_hand_pile_choice",
    resolve=lambda game, choice, r: game._resolve_exile_hand_pile(
        choice, r.get("hand_indices") or []
    ),
    default=lambda game, choice: game._default_exile_hand_pile(choice),
    action="exile_hand_pile_confirm",
    prompt_key="exile_hand_pile_choice",
    blocked_detail="choose which cards to exile before other actions",
    # "Put **that many** cards from the top of your library into your hand" is
    # the next step of the same resolution and reads what this exiled, so
    # nothing after it may run until it is answered (CR 608.2).
    suspends=True,
    # A hand is hidden (CR 400.2), so the options are the chooser's alone.
    hidden_for_ai=False,
)

register_choice(
    "library_pile_split",
    resolve=lambda game, choice, r: game._resolve_library_pile_split(
        choice, r.get("first_pile")
    ),
    default=lambda game, choice: game._default_library_pile_split(choice),
    action="library_pile_split_confirm",
    prompt_key="library_pile_split",
    blocked_detail="divide the piles before other actions",
    # Answering arms the controller's choice, which is a later step of this
    # same resolution (CR 608.2).
    suspends=True,
    # …and a non-interactive divider answers at once, or the resolution stops
    # on a prompt nobody owes an answer to.
    default_at_arm=True,
)

register_choice(
    "pile_exile_choice",
    resolve=lambda game, choice, r: game._resolve_pile_exile_choice(
        choice, r.get("pile_index")
    ),
    default=lambda game, choice: game._default_pile_exile_choice(choice),
    action="pile_exile_confirm",
    prompt_key="pile_exile_choice",
    blocked_detail="choose a pile to exile before other actions",
    suspends=True,
    default_at_arm=True,
)

register_choice(
    "pile_search",
    resolve=lambda game, choice, r: game._resolve_pile_search(
        choice, r.get("pile_index")
    ),
    default=lambda game, choice: game._default_pile_search(choice),
    action="pile_search_confirm",
    prompt_key="pile_search",
    blocked_detail="search the pile before other actions",
    suspends=True,
    default_at_arm=True,
)

register_choice(
    "pile_split",
    resolve=lambda game, choice, r: piles.resolve_pile_split(
        game, choice, r.get("first_pile")
    ),
    default=lambda game, choice: piles.default_pile_split(game, choice),
    action="pile_split_confirm",
    prompt_key="pile_split",
    blocked_detail="separate the piles before other actions",
    # The choice between the piles is a later step of this same resolution
    # (CR 608.2), and it is between what this answer made.
    suspends=True,
    # A non-interactive separator answers at once, or the resolution stops on
    # a prompt nobody owes an answer to.
    default_at_arm=True,
    # The piles are face up (CR 700.3) — unlike Phyrexian Portal's, every
    # player sees them — so the prompt is the separator's but hides nothing.
    spectator_visible=True,
)

register_choice(
    "pile_choice",
    resolve=lambda game, choice, r: piles.resolve_pile_choice(
        game, choice, r.get("pile_index")
    ),
    default=lambda game, choice: piles.default_pile_choice(game, choice),
    action="pile_choice_confirm",
    prompt_key="pile_choice",
    blocked_detail="choose a pile before other actions",
    # What becomes of each pile is the next step of the same resolution.
    suspends=True,
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "library_cycle_offer",
    resolve=lambda game, choice, r: game._resolve_library_cycle_offer(
        choice, bool(r.get("accept"))
    ),
    default=lambda game, choice: game._default_library_cycle_offer(choice),
    action="library_cycle_confirm",
    prompt_key="library_cycle_offer",
    blocked_detail="answer the library cycle before other actions",
    # Answering arms either the next round or the shuffle that ends the card,
    # so nothing after it may run until it is answered (CR 608.2).
    suspends=True,
    # …and a non-interactive seat therefore takes its default the moment the
    # offer is armed, or the resolution would stop on a prompt nobody answers.
    default_at_arm=True,
)

register_choice(
    "linked_exile_return",
    resolve=lambda game, choice, r: game._resolve_linked_exile_return(
        choice, r.get("entry_index")
    ),
    default=lambda game, choice: game._default_linked_exile_return(choice),
    action="linked_exile_return_confirm",
    prompt_key="linked_exile_return",
    blocked_detail="choose a card to return before other actions",
    # The prompt refuses every other action, so a seat that never answers it
    # freezes the game. A non-interactive seat therefore takes its default the
    # moment it is armed, exactly as the exile that filled the pile does —
    # ``auto_resolve_pending_choices`` drains only the kinds a caller lists,
    # and a blocking prompt left off that list is a headless run that stops.
    default_at_arm=True,
    # The pile is face down (CR 406.3) and only its owner may look, so the
    # options are the chooser's alone — exactly the hand pick's reason.
    hidden_for_ai=False,
)

register_choice(
    "put_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_put_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_put_from_hand_choice(choice),
    action="put_from_hand_confirm",
    prompt_key="put_from_hand_choice",
    blocked_detail="choose a card to put onto the battlefield before other actions",
    # The round this is a step of counts the answers to decide whether it
    # happens again (Eureka), so the loop genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, unlike the permanent pick above: the
    # candidates are cards in a hand (CR 400.2, a hidden zone), so rendering them
    # to a seatless viewer would publish the hand. Only the seat that owes the
    # decision is shown it.
)

register_choice(
    "text_change_vocabulary",
    resolve=lambda game, choice, r: game._resolve_text_change_vocabulary(
        choice, r.get("mode")
    ),
    default=lambda game, choice: game._default_text_change_vocabulary(choice),
    action="text_change_vocabulary_confirm",
    prompt_key="text_change_vocabulary",
    blocked_detail="choose which kind of word to replace before other actions",
    # **Not** ``suspends``: the rewrite *is* the answer and it is the last step
    # of the spell, so nothing behind it reads a record. ``blocked_detail`` is
    # what makes the game wait (CR 608.2).
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # A text change is a public change to a public object (CR 612), so a
    # seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "aggregate_sacrifice",
    resolve=lambda game, choice, r: game._resolve_aggregate_sacrifice(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_aggregate_sacrifice(choice),
    action="aggregate_sacrifice_confirm",
    prompt_key="aggregate_sacrifice",
    blocked_detail="choose what to sacrifice before other actions",
    # **Not** ``suspends``: the sacrifice *is* the answer and it is the last
    # step of the offer's accept branch, so nothing behind it reads a record.
    # ``blocked_detail`` is what makes the game wait (CR 608.2), which it must —
    # the creatures are still on the battlefield until the answer arrives.
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "library_end_choice",
    resolve=lambda game, choice, r: game._resolve_library_end_choice(
        choice, bool(r.get("to_bottom"))
    ),
    default=lambda game, choice: game._default_library_end_choice(choice),
    action="library_end_confirm",
    prompt_key="library_end_choice",
    blocked_detail="choose which end of the library before other actions",
    # **Not** ``suspends``: the move *is* the answer and it is the last step of
    # the sentence, so nothing behind it reads the record — which is the whole
    # of what that field claims. ``blocked_detail`` is what makes the game wait
    # (CR 608.2), and the permanent is still on the battlefield until the answer
    # arrives, which is why no action may run in between.
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # Which end of a library a card went to is public (both ends of CR 401.1's
    # ordered zone are announced), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "graveyard_pile_choice",
    resolve=lambda game, choice, r: game._resolve_graveyard_pile_choice(
        choice, r.get("seat")
    ),
    default=lambda game, choice: game._default_graveyard_pile_choice(choice),
    action="graveyard_pile_confirm",
    prompt_key="graveyard_pile_choice",
    blocked_detail="choose which graveyard to exile from before other actions",
    # The pick this arms is a later step of the same resolution and reads the
    # answer, so nothing may run past it (CR 608.2). The chain is what makes
    # both prompts one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # Whose graveyard holds what is public (CR 400.2 makes a graveyard an open
    # zone), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "graveyard_exile_pick",
    resolve=lambda game, choice, r: game._resolve_graveyard_exile_pick(
        choice, r.get("graveyard_indices")
    ),
    default=lambda game, choice: game._default_graveyard_exile_pick(choice),
    action="graveyard_exile_confirm",
    prompt_key="graveyard_exile_pick",
    blocked_detail="choose the cards to exile from that graveyard before other actions",
    blocks_every_seat=True,
    # "…**If you do**, you gain 1 life for each card exiled this way" is a
    # later step of the same resolution and reads what this answer records, so
    # that step must not run before the answer exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # A graveyard is a public zone (CR 400.2), so a seatless viewer sees the
    # pile the chooser is looking at — unlike every hand pick in this file.
    spectator_visible=True,
)

register_choice(
    "choose_cards_in_hand",
    resolve=lambda game, choice, r: game._resolve_choose_cards_in_hand(
        choice, r.get("hand_indices")
    ),
    default=lambda game, choice: game._default_choose_cards_in_hand(choice),
    action="choose_cards_in_hand_confirm",
    prompt_key="choose_cards_in_hand",
    blocked_detail="choose the cards in your hand before other actions",
    blocks_every_seat=True,
    # The pick is what the next step of the same resolution repeats over, so
    # that step must not run before the answer exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, for ``put_from_hand_choice``'s
    # reason: the candidates are cards in a hand (CR 400.2, a hidden zone), so
    # rendering them to a seatless viewer would publish the hand.
)

register_choice(
    "face_down_cast",
    resolve=lambda game, choice, r: game._resolve_face_down_cast(choice, r["hand_index"]),
    default=lambda game, choice: game._default_face_down_cast(choice),
    action="face_down_cast_confirm",
    prompt_key="face_down_cast",
    # Illusionary Mask's own comment: "the actual cast happens in
    # confirm_face_down_cast" — armed mid-resolution, so the game waits.
    blocked_detail="choose the face-down creature before other actions",
)

register_choice(
    "word_of_command",
    resolve=lambda game, choice, r: game._resolve_word_of_command(
        choice, r["hand_index"], r["defer_resolution"], r.get("spell_name"),
    ),
    default=lambda game, choice: game._default_word_of_command(choice),
    action="word_of_command_confirm",
    prompt_key="word_of_command",
    blocked_detail="choose the Word of Command card before other actions",
    # The caster's answer is recorded while the spell keeps waiting on the
    # stack, so the object outlives the decision it carries.
    is_open=lambda game, choice: "chosen_hand_index" not in choice.data,
)

register_choice(
    "opponent_damage",
    resolve=lambda game, choice, r: game._resolve_opponent_damage_choice(
        choice, r["target_seat"], r["target_permanent_index"]
    ),
    default=lambda game, choice: game._default_opponent_damage_choice(choice),
    action="opponent_damage_choose",
    prompt_key="opponent_damage_choice",
    blocked_detail="choose a target for the opponent-choice damage before other actions",
    default_at_arm=True,
)

register_choice(
    "name_and_strip",
    resolve=lambda game, choice, r: game._resolve_name_and_strip(choice, r["card_name"]),
    default=lambda game, choice: game._default_name_and_strip(choice),
    action="name_and_strip_confirm",
    prompt_key="name_and_strip",
    blocked_detail="name a card for the search before other actions",
)

register_choice(
    "choose_card_name",
    resolve=lambda game, choice, r: game._resolve_choose_card_name(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_choose_card_name(choice),
    action="choose_card_name_confirm",
    prompt_key="choose_card_name",
    blocked_detail="name a card before other actions",
    # The sentences behind this read the name, and one of them mills: a seat
    # that saw the milled card before naming would be choosing with information
    # the card does not give them (CR 608.2, CR 117.3b).
    suspends=True,
)

register_choice(
    "name_then_reveal_top",
    resolve=lambda game, choice, r: game._resolve_name_then_reveal_top(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_then_reveal_top(choice),
    action="name_then_reveal_top_confirm",
    prompt_key="name_then_reveal_top",
    blocked_detail="name a card before other actions",
)

register_choice(
    "exiled_pile_claim",
    resolve=lambda game, choice, r: game._resolve_exiled_pile_claim(
        choice, r["pile_index"]
    ),
    default=lambda game, choice: game._default_exiled_pile_claim(choice),
    action="exiled_pile_claim_confirm",
    prompt_key="exiled_pile_claim",
    blocked_detail="choose one of the exiled cards before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # Armed for AI seats too and drained by the auto-resolver: the round-robin
    # is one resolution, and a seat whose prompt was never queued would be
    # skipped rather than defaulted.
    hidden_for_ai=False,
    # The pile shrinks by one with every answer and the seats behind this one
    # are picking out of what is left, so nothing later in the resolution may
    # run before the answer arrives (CR 608.2, CR 117.3b).
    suspends=True,
)

register_choice(
    "graveyard_pick_for_price",
    resolve=lambda game, choice, r: game._resolve_graveyard_pick_for_price(
        choice, r["graveyard_index"]
    ),
    default=lambda game, choice: game._default_graveyard_pick_for_price(choice),
    action="graveyard_pick_for_price_confirm",
    prompt_key="graveyard_pick_for_price",
    blocked_detail="choose a card in that graveyard before other actions",
    # A graveyard is a public zone (CR 400.2), so a spectator sees the offer
    # exactly as the choosing seat does.
    spectator_visible=True,
    hidden_for_ai=False,
    # The sentence after this one reads the pick, and the one after that reads
    # the whole set of them: nothing behind this prompt may run until it is
    # answered (CR 608.2).
    suspends=True,
)

register_choice(
    "name_then_consult",
    resolve=lambda game, choice, r: game._resolve_name_then_consult(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_then_consult(choice),
    action="name_then_consult_confirm",
    prompt_key="name_then_consult",
    blocked_detail="name a card for the consultation before other actions",
)

register_choice(
    "name_and_random_reveal",
    resolve=lambda game, choice, r: game._resolve_name_and_random_reveal(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_and_random_reveal(choice),
    action="name_and_random_reveal_confirm",
    prompt_key="name_and_random_reveal",
    blocked_detail="name a card for the reveal before other actions",
)

register_choice(
    "enter_choice",
    resolve=lambda game, choice, r: game._resolve_enter_choice(
        choice, r.get("opponent_index"), r.get("mana_color"), r.get("card_name"),
        r.get("land_types"), r.get("creature_type"), r.get("land_type"),
    ),
    # Black Vise / Jihad stamp their deterministic defaults on the permanent as
    # it enters, so a non-interactive controller has nothing left to apply.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="enter_choice_confirm",
    prompt_key="enter_choice",
    blocked_detail="choose an opponent (and color) for the entering permanent before other actions",
    default_at_arm=True,
)

register_choice(
    "entry_exile",
    resolve=lambda game, choice, r: game._resolve_entry_exile(choice, r.get("picks")),
    default=lambda game, choice: game._default_entry_exile(choice),
    action="entry_exile_confirm",
    prompt_key="entry_exile",
    blocked_detail="exile the entering permanent's cards before other actions",
    # The resolution that armed this has to finish, so a non-interactive seat
    # never queues it: the stated default is taken where the entry stands, which
    # is also what keeps AI and headless play from waiting on a prompt nobody
    # will answer.
    default_at_arm=True,
    # A graveyard is a public zone (CR 400.2), so there is nothing here a
    # seatless viewer may not already see - unlike `put_from_hand_choice` and
    # `choose_cards_in_hand`, whose candidates would publish a hand.
    spectator_visible=True,
)

register_choice(
    "body_choice",
    resolve=lambda game, choice, r: game._resolve_body_choice(choice, r["option_index"]),
    # Primal Clay's first printed body is applied as it enters, so the default
    # is already in place; the prompt only offers to replace it.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="body_choice_confirm",
    prompt_key="body_choice",
    blocked_detail="choose the entering creature's body before other actions",
    default_at_arm=True,
)

register_choice(
    "modal_mode_targets",
    resolve=lambda game, choice, r: game._resolve_modal_mode_targets(
        choice, r.get("permanent_ids")
    ),
    default=lambda game, choice: game._default_modal_mode_targets(choice),
    action="modal_mode_targets_confirm",
    prompt_key="modal_mode_targets",
    blocked_detail=(
        "name the targets for the mode your opponent chose before other actions"
    ),
    # The other half of `opponent_mode_choice` below, and every flag on it is
    # here for that flag's own reason: this is still inside CR 601.2i's
    # announcement, so nobody acts until it is answered, and a non-interactive
    # caster takes the stated default where the offer stands rather than
    # holding the cast open forever.
    blocks_every_seat=True,
    default_at_arm=True,
    # A spell's targets are announced in the open (CR 601.2c).
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "opponent_mode_choice",
    resolve=lambda game, choice, r: game._resolve_opponent_mode_choice(
        choice, r.get("mode_index")
    ),
    default=lambda game, choice: game._default_opponent_mode_choice(choice),
    action="opponent_mode_choice_confirm",
    prompt_key="opponent_mode_choice",
    blocked_detail=(
        "an opponent is choosing that spell's mode; wait for the answer"
    ),
    # CR 601.2i finishes the cast before anyone may respond, and CR 700.2e puts
    # this choice inside that announcement — so **nobody** acts until it is
    # answered, the caster included. That is what `blocks_every_seat` says, and
    # it is stronger than the priority hold the detail above already implies.
    blocks_every_seat=True,
    # **Not** ``suspends``. That flag stops the resumable loop an effect was a
    # step of, and this prompt is armed inside an *announcement*: no effect is
    # running, the spell has not resolved, and there is no loop behind it. What
    # holds the game is the block above — CR 601.2i finishes the cast, and then
    # nobody has priority until the mode is known.
    # A non-interactive chooser never queues it: the cast has to finish, and the
    # stated default (the first printed mode) is taken where the offer stands.
    # Without this an AI or headless seat would hold a cast open forever.
    default_at_arm=True,
    # A spell's modes are announced in the open (CR 601.2b), and so is whose
    # choice this is.
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "mode_choice",
    resolve=lambda game, choice, r: game._resolve_mode_choice(
        choice, r["mode_index"], r.get("target"),
    ),
    default=lambda game, choice: game._default_mode_choice(choice),
    action="mode_choice_confirm",
    prompt_key="mode_choice",
    blocked_detail="choose a mode for the triggered ability before other actions",
    default_at_arm=True,
    spectator_visible=True,
    # "**For each of those cards**, pay 4 life or put the card on top of your
    # library." (Sylvan Library.) A choice reached inside a repetition, whose
    # branch acts on the object the repetition is *currently* on — so the next
    # iteration must not start before this answer is applied. Without it both
    # iterations armed at once and both answers were applied against whichever
    # card the loop had ended on.
    suspends=True,
)

register_choice(
    "loyalty_recipient",
    resolve=lambda game, choice, r: game._resolve_loyalty_recipient(
        choice, r["permanent_id"]
    ),
    default=lambda game, choice: game._default_loyalty_recipient(choice),
    action="loyalty_recipient_confirm",
    prompt_key="loyalty_recipient",
    blocked_detail="choose which planeswalker gets the loyalty counter before other actions",
    # The trigger that armed this has to finish resolving, so a non-interactive
    # seat never queues it — it takes the stated default where it stands.
    default_at_arm=True,
    # Nothing later in the same resolution reads the answer: the counter is the
    # last thing the ability does.
)

# Replacement effects that suspend on a decision (CR 614) keep their own queue —
# see engine/replacement_choices.py — but they are prompts like any other, so
# they are described here too and the web layer treats both queues alike.
# ``ReplacementChoice`` carries the same kind / player_index / data attributes,
# which is why no adapter is needed.

def _resolve_replacement(game, choice, response) -> bool:
    return bool(game.resolve_replacement_choice(
        choice.player_index, response["option"], kind=choice.kind
    ))


def _default_replacement(game, choice) -> None:
    game.resolve_replacement_choice(
        choice.player_index, choice.default_option, kind=choice.kind
    )


register_choice(
    "commander_zone_change",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="commander_zone_change_confirm",
    prompt_key="commander_zone_change",
    blocked_detail="choose whether your commander goes to the command zone before other actions",
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "leng_discard",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="leng_discard_confirm",
    prompt_key="leng_discard",
    blocked_detail="choose where the discarded card goes (Library of Leng) before other actions",
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "optional_damage_redirect",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="optional_damage_redirect_confirm",
    prompt_key="optional_damage_redirect",
    blocked_detail=(
        "choose whether you take the damage headed for that creature before "
        "other actions"
    ),
    # The damage event that armed this is over — it was consumed so that both
    # answers could run through one resolver — so nothing is waiting on the
    # answer to carry on. A non-interactive seat takes the stated policy where
    # it stands, exactly as the three offers above do.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "entry_discard_toll",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="entry_discard_toll_confirm",
    prompt_key="entry_discard_toll",
    blocked_detail=(
        "choose whether to discard a card to put that permanent onto the "
        "battlefield (Mox Diamond) before other actions"
    ),
    # The entry that armed this was consumed so that both answers run through
    # one resolver - the permanent is put onto the battlefield by the resolver
    # itself - so nothing is waiting on the answer to carry on.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "draw_becomes_counter",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="draw_becomes_counter_confirm",
    prompt_key="draw_becomes_counter",
    blocked_detail=(
        "choose whether to take the counter instead of the draw (Pursuit of "
        "Knowledge) before other actions"
    ),
    # The draw that armed this was consumed so that both the answer and the
    # default run through one resolver, and the draw a decline remakes is the
    # resolver's own business - so nothing is waiting on the answer to carry
    # on, exactly as for the offers around it.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "reveal_until_kind_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="reveal_until_kind_draw_confirm",
    prompt_key="reveal_until_kind_draw",
    blocked_detail=(
        "choose whether to reveal until a land or nonland card (Abundance) "
        "before other actions"
    ),
    # The draw that armed this was consumed so that every answer - both kinds
    # and the decline - runs through one resolver, and the draw a decline
    # remakes is the resolver's own business. So nothing inside the resolution
    # is waiting on the answer, exactly as for the offers around it.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    # "If you would draw a card, you may skip that draw instead." (Obstinate
    # Familiar.) The third optional replacement of one draw, registered the
    # way the two above are and for their reasons: the draw that armed it was
    # consumed, both answers run through one resolver, and a non-interactive
    # seat takes the stated default where it stands.
    "skip_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="skip_draw_confirm",
    prompt_key="skip_draw",
    blocked_detail=(
        "choose whether to skip that draw (Obstinate Familiar) before other "
        "actions"
    ),
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "lamp_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="lamp_draw_confirm",
    prompt_key="lamp_draw",
    blocked_detail="choose a card for Aladdin's Lamp before other actions",
    default_at_arm=True,
)

register_choice(
    "outside_game_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="outside_game_draw_confirm",
    prompt_key="outside_game_draw",
    blocked_detail="choose a card from outside the game before other actions",
    default_at_arm=True,
)

register_choice(
    "return_from_graveyard_instead_of_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="graveyard_return_draw_confirm",
    prompt_key="return_from_graveyard_instead_of_draw",
    blocked_detail=(
        "choose which card comes back from your graveyard (Forbidden Crypt) "
        "before other actions"
    ),
    # The draw that armed this was consumed so that both the answer and the
    # default run through one resolver, and the draws queued behind it are the
    # resolver's own business - so nothing is waiting on the answer to carry on,
    # exactly as for the four offers above.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "keep_permanents",
    resolve=lambda game, choice, r: game._resolve_keep_permanents(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_keep_permanents(choice),
    action="keep_permanents_confirm",
    prompt_key="keep_permanents",
    blocked_detail="choose which permanents to keep before other actions",
    # The sacrifice is this prompt's own resolver rather than a step behind it,
    # so nothing inside the resolution is waiting on the answer - but the
    # *other* seats' prompts are armed by the same instruction and the object
    # stays on the stack until the last of them is answered (CR 608.2), which is
    # what the gate above buys.
    #
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated maximum keep is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
    # "…then sacrifices the rest. **Each player discards cards the same
    # way.**" (Balancing Act.) The first card with a step *behind* the keep,
    # and that step arms a prompt of its own for the same seat. Left running,
    # one seat owed a keep and a discard at once and each answer was refused
    # naming the other — every blocking prompt refuses every action but its
    # own. So the keep holds the resolution the way a forced sacrifice does,
    # and the step behind it runs when the last keep is answered. Nothing
    # changes for the four cards printed before it: none has a step behind
    # the keep, and a seat nobody asks never queues one.
    suspends=True,
)
