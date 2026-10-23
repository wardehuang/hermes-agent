"""Per-turn client presentation (hidden widget intents, paste title preview, bubble label) through canonical admission.

The Desktop composer types some sends ``display_kind="hidden"`` (goal control, inline-preview decisions,
first-run kickoffs): model-facing text no client may render as a user bubble. A large paste carries a
``title_preview`` that only the session titler reads. A ``display_text`` names the bubble label when it
differs from the model-facing ``text`` (a ``/goal`` kickoff, a skill expansion): the persisted user row
carries it while the model still receives ``text``. All are facts about ONE admitted turn, committed with
the admission row as ``display_v1`` so a retry, a queued drain or a managed child applies exactly what
was admitted, and bound to that admission's own event, never to a later turn on the same task.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from hermes_state_runtime import RuntimeStoreError

HIDDEN = 'hidden'
_TITLE_PREVIEW_LIMIT = 1000
_SUBMIT_FIELDS = ('display_kind', 'title_preview', 'display_text')
_display_turn: ContextVar[tuple | None] = ContextVar('display_turn', default=None)


def submit_display_fields(params):
    """The raw per-turn presentation fields of a ``prompt.submit`` request, forwarded to admission."""
    return {key: params[key] for key in _SUBMIT_FIELDS if key in params}


def admit_display(params):
    """Wire ``display_kind`` / ``title_preview`` / ``display_text`` -> committed ``display_v1``
    (``{}`` when absent).

    Only ``hidden`` is a client-authorable kind; anything else is refused rather than rendered,
    so a typo can never turn machine text into a visible user row. ``display_text`` is the bubble
    label when it differs from the model-facing ``text`` (a ``/goal`` kickoff, a skill expansion):
    the persisted user row carries it while the model still receives ``text``.
    """
    kind, preview = params.get('display_kind'), params.get('title_preview')
    label = params.get('display_text')
    if kind is not None and kind != HIDDEN:
        raise RuntimeStoreError('invalid_params')
    if preview is not None and not isinstance(preview, str):
        raise RuntimeStoreError('invalid_params')
    if label is not None and not isinstance(label, str):
        raise RuntimeStoreError('invalid_params')
    committed = {}
    if kind:
        committed['kind'] = HIDDEN
    if preview and preview.strip():
        committed['title_preview'] = preview[:_TITLE_PREVIEW_LIMIT]
    if label and label.strip():
        committed['display_text'] = label
    return {'display_v1': committed} if committed else {}


def restore_display(committed):
    """A committed ``display_v1`` arriving across a process boundary (managed worker), re-checked by the
    admission validator: only an object admission itself could have committed is accepted."""
    if not isinstance(committed, dict) or not committed or set(committed) - {'kind', 'title_preview', 'display_text'}:
        raise RuntimeStoreError('invalid_params')
    wire = {'display_kind': committed.get('kind'), 'title_preview': committed.get('title_preview'),
            'display_text': committed.get('display_text')}
    if admit_display(wire).get('display_v1') != committed:
        raise RuntimeStoreError('invalid_params')
    return committed


@contextmanager
def display_turn_scope(admission_id, committed):
    token = _display_turn.set((admission_id, committed) if committed else None)
    try:
        yield
    finally:
        _display_turn.reset(token)


def display_turn(message_id):
    """The committed presentation of the admission ``message_id`` names; ``{}`` for any other turn, so
    a follow-up on the same task never inherits an earlier admission's presentation."""
    bound = _display_turn.get()
    if bound is None or message_id is None or str(message_id) != bound[0]:
        return {}
    return bound[1]


def admission_display(event):
    """The committed presentation of the admission ``event`` executes (its ``message_id`` is the
    admission id), ``{}`` for any other event."""
    return display_turn(getattr(event, 'message_id', None) if event is not None else None)


def persisted_user_text(message_id):
    """The user row's content for this admission when its committed ``display_text`` names a bubble
    label (a ``/goal`` kickoff, a skill invocation): the transcript keeps what the user saw, while
    the model still receives the admitted ``text``. ``None`` when the admission committed no label."""
    return display_turn(message_id).get('display_text')


def worker_display_kwargs():
    """``run_conversation`` persistence kwargs of the managed child's single admitted turn."""
    bound = _display_turn.get()
    committed = bound[1] if bound is not None else {}
    return {**({'persist_user_display_kind': HIDDEN} if committed.get('kind') == HIDDEN else {}),
            **({'persist_user_message': committed['display_text']} if committed.get('display_text') else {}),
            **({'persist_user_display_metadata': {'title_preview': committed['title_preview']}}
               if committed.get('title_preview') else {})}
