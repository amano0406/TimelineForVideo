from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from video2timeline_worker import processor


class ProcessorQueueTests(unittest.TestCase):
    def test_process_job_waits_for_running_job_before_picking_pending(self) -> None:
        with (
            patch.object(processor, "_collect_running_jobs", return_value=[Path("/tmp/run-1")]),
            patch.object(processor, "_collect_pending_jobs") as collect_pending,
        ):
            self.assertFalse(processor.process_job())
            collect_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
