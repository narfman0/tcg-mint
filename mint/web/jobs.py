"""One worker thread, a queue of jobs, and a stream of events for the page."""
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field


class Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    params: dict
    state: str = "queued"      # queued | running | done | failed | cancelled
    log: list = field(default_factory=list)
    items: list = field(default_factory=list)   # what the job made, one entry per unit (job.made)
    done: int = 0
    total: int = 0
    result: object = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    _cancel: bool = field(default=False, repr=False)
    _fn: object = field(default=None, repr=False)
    _jobs: object = field(default=None, repr=False)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "params": self.params, "state": self.state,
                "log": self.log[-200:], "items": self.items[-500:], "done": self.done, "total": self.total, "result": self.result,
                "error": self.error, "created": self.created, "started": self.started, "finished": self.finished}

    # --- for the job function -------------------------------------------------
    def say(self, msg):
        self.log.append(msg)
        self._jobs.emit("log", {"id": self.id, "msg": msg})

    def made(self, **what):
        """One unit of the job's output is on disk -- a card's variant, a render -- and the page can
        show it now rather than when the whole batch ends, and link to it from the job afterwards.
        `what` names it: set and name (the card), and what was made -- kind, key (the column on the
        card page: a variant hash, render-plain / render-styled), path (the file), label / file."""
        self.items.append(dict(what))
        self._jobs.emit("item", {"id": self.id, **what})

    def step(self, done, total=None):
        self.done = done
        if total is not None:
            self.total = total
        self._jobs.emit("progress", {"id": self.id, "done": self.done, "total": self.total})
        if self._cancel:
            raise Cancelled()

    @property
    def cancelled(self):
        return self._cancel


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.queue: queue.Queue = queue.Queue()
        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.current: Job | None = None
        self.worker = threading.Thread(target=self._run, name="mint-jobs", daemon=True)
        self.worker.start()

    def submit(self, kind, title, params, fn):
        """fn(job) does the work; it may call job.say(), job.step(), job.made() and return a JSON-able result."""
        job = Job(uuid.uuid4().hex[:8], kind, title, params, _fn=fn, _jobs=self)
        with self.lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
        self.emit("job", job.to_dict())
        self.queue.put(job.id)
        return job

    def cancel(self, jid):
        job = self.jobs.get(jid)
        if not job:
            return None
        if job.state == "queued":
            job.state, job.finished = "cancelled", time.time()
            self.emit("job", job.to_dict())
        elif job.state == "running":
            job._cancel = True
        return job

    def list(self):
        return [self.jobs[j].to_dict() for j in reversed(self.order)]

    # --- events -----------------------------------------------------------------
    def emit(self, event, data):
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                pass

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    # --- the worker ---------------------------------------------------------------
    def _run(self):
        while True:
            jid = self.queue.get()
            job = self.jobs[jid]
            if job.state != "queued":
                continue
            job.state, job.started = "running", time.time()
            self.current = job
            self.emit("job", job.to_dict())
            try:
                job.result = job._fn(job)
                job.state = "done"
            except Cancelled:
                job.state = "cancelled"
            except Exception as e:  # noqa: BLE001 - anything the job raised is the job's failure
                job.state, job.error = "failed", f"{type(e).__name__}: {e}"
                job.log.append(traceback.format_exc().splitlines()[-1])
            job.finished = time.time()
            self.current = None
            self.emit("job", job.to_dict())
