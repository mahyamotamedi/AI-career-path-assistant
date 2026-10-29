"""In-memory per-session store. No persistence. NEVER log session contents."""
from dataclasses import dataclass, field
from threading import Lock, RLock

from app.schemas import CareerProfile, ResumeProfile, UsageReport


@dataclass
class SessionState:
    session_id: str
    history: list[dict] = field(default_factory=list)  # chat messages {role, content}
    questions_asked: int = 0
    profile: CareerProfile | None = None
    resume: ResumeProfile | None = None
    usage: UsageReport = field(default=None)  # type: ignore[assignment]

    lock: object = field(default_factory=RLock, repr=False)
    usage_lock: object = field(default_factory=Lock, repr=False)
    draft: dict = field(default_factory=dict, repr=False)
    usage_complete: bool = True
    cost_complete: bool = True

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = UsageReport(session_id=self.session_id)


_sessions: dict[str, SessionState] = {}
_lock = Lock()


def get_session(session_id: str) -> SessionState:
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = SessionState(session_id=session_id)
        return _sessions[session_id]


def drop_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
