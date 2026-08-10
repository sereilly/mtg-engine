"""Web application package for MTG gameplay.

``app.py`` used to be the whole thing. It is a layered set of modules now, and
:data:`LAYERS` is the layering: a module may import from any module *earlier* in
this tuple and from none later, which is what makes the split acyclic and keeps
``app.py`` free to be nothing but the route table.

The tuple is the contract, not a description of one — ``tests/ui/test_web_layering.py``
reads it and fails on an import that reaches sideways or down, which is how the
one cycle this shape can grow (a leaf reaching back up to the assembler) shows up
as a test failure rather than as an ImportError at startup.
"""

LAYERS = (
    # Pre-existing leaves: request/response models and the three stores.
    "schemas",
    "verification_store",
    "deck_legality",
    "deck_builder",
    "deck_store",
    "prompts",
    "session_store",
    # The card pool, the stores' instances, and session lookup.
    "runtime",
    # Server-sent events.
    "events",
    # Seat identity, loss/win, and whether to hold priority.
    "seats",
    # Engine object -> client JSON, one function per kind of object.
    "serialization",
    # The card pool and decks as the client browses them.
    "catalog",
    # The manual-verification tracker's read side.
    "verification_report",
    # Coin flip and mulligans.
    "pregame",
    # The beginning phase and the turn's boundaries.
    "turn_steps",
    # Combat assignments that need a prompt.
    "combat_prompts",
    # Priority and phase advancement, including AI stepping.
    "game_flow",
    # The whole-state payload a client polls.
    "state_view",
    # Debug-menu board manipulation and raw-state injection.
    "debug_actions",
    # The one dispatch over ActionKind.
    "actions",
    # The FastAPI app: the one place a route is declared.
    "app",
)
