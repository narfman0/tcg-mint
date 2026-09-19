"""The job runner: one worker, events for the page. A job reports each finished unit as it lands."""
import queue

from mint.web.jobs import Jobs


def drain(q, until, timeout=5):
    """Events off a subscriber queue up to and including the next `until` event."""
    out = []
    while True:
        ev = q.get(timeout=timeout)
        out.append(ev)
        if ev[0] == until:
            return out


def test_each_finished_unit_is_an_event_before_the_job_ends():
    jobs = Jobs()
    q = jobs.subscribe()

    def run(job):
        job.step(0, 2)
        for name in ("Alpha", "Beta"):
            job.say(f"restyled {name}")
            job.made(set="TST", name=name)
            job.step(job.done + 1)
        return {"variants": ["a", "b"]}

    job = jobs.submit("restyle", "restyle 2 cards", {}, run)
    events = drain(q, "job")            # queued
    events += drain(q, "job")           # running
    events += drain(q, "job")           # done
    names = [e for e, _ in events]
    items = [d for e, d in events if e == "item"]
    assert items == [{"id": job.id, "set": "TST", "name": "Alpha"}, {"id": job.id, "set": "TST", "name": "Beta"}]
    # an item follows its card's log line and lands before the terminal job event
    assert names.index("log") < names.index("item") < len(names) - 1
    assert job.state == "done" and job.result == {"variants": ["a", "b"]}
    jobs.unsubscribe(q)
    try:
        q.get(timeout=0.2)
        raise AssertionError("no events after unsubscribing")
    except queue.Empty:
        pass
