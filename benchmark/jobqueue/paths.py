"""Where the queue keeps its state, and which board we are on.

The Pi keeps its results tree in ~/Research, the Jetson in ~/research. That
case difference has caused board-specific bugs before (AGENTS §7), so it is
detected once here and nowhere else.

AGENTIC_QUEUE_ROOT and AGENTIC_BOARD override detection. The test suite runs
on a Mac that has neither directory, and `queue_ctl.py --dry-run` uses them
to resolve commands off-board.
"""
import os


class BoardUnknown(Exception):
    """Neither ~/Research nor ~/research exists and no override was given."""


class Paths:
    def __init__(self, root, board):
        self.root = root
        self.board = board

    @property
    def queue_dir(self):
        return os.path.join(self.root, "queue")

    @property
    def queue_file(self):
        return os.path.join(self.queue_dir, "queue.json")

    @property
    def lock_file(self):
        # Separate from queue.json: atomic writes replace the inode, so a lock
        # held on the data file itself would be released by its own update.
        return os.path.join(self.queue_dir, "queue.lock")

    @property
    def events_file(self):
        return os.path.join(self.queue_dir, "events.jsonl")

    @property
    def pid_file(self):
        return os.path.join(self.queue_dir, "runner.pid")

    @property
    def jobs_dir(self):
        return os.path.join(self.queue_dir, "jobs")

    def job_dir(self, job_id):
        return os.path.join(self.jobs_dir, job_id)

    @property
    def stdbench(self):
        return os.path.join(self.root, "stdbench")

    @property
    def measured(self):
        return os.path.join(self.root, "measured")


def detect(home=None, env=None, isdir=None):
    env = os.environ if env is None else env
    home = os.path.expanduser("~") if home is None else home
    isdir = os.path.isdir if isdir is None else isdir

    root = env.get("AGENTIC_QUEUE_ROOT")
    board = env.get("AGENTIC_BOARD")
    if root and board:
        return Paths(root, board)

    for candidate, name in ((os.path.join(home, "Research"), "pi"),
                            (os.path.join(home, "research"), "jetson")):
        if isdir(candidate):
            return Paths(root or candidate, board or name)
    raise BoardUnknown(
        "no ~/Research or ~/research here; set AGENTIC_QUEUE_ROOT and AGENTIC_BOARD")


def bench_dir():
    """The benchmark/ directory — where run_measured.sh and the run scripts live."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
