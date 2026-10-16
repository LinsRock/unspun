"""A failed verification must not leave a deploy process running after cleanup."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from verify_startup import run_command


class VerifierProcesses(unittest.TestCase):
    def assert_timeout_stops_descendants(self, parent_exits=False):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "late-service-start"
            child = (
                "import pathlib,time; time.sleep(1); "
                f"pathlib.Path({str(marker)!r}).write_text('started')"
            )
            parent = (
                "import subprocess,sys,time; "
                + (f"subprocess.Popen([sys.executable, '-c', {child!r}]); ")
                + ("" if parent_exits else "time.sleep(10)")
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                run_command([sys.executable, "-c", parent], env=os.environ, timeout=0.3)
            time.sleep(1.1)
            self.assertFalse(marker.exists())

    def test_timeout_stops_descendants_before_returning(self):
        self.assert_timeout_stops_descendants()

    def test_timeout_stops_descendants_of_an_already_exited_parent(self):
        self.assert_timeout_stops_descendants(parent_exits=True)

    def test_failed_command_preserves_output_and_status(self):
        result = run_command(
            [sys.executable, "-c", "import sys; print('failed'); sys.exit(7)"],
            env=os.environ,
            check=False,
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), "failed")


if __name__ == "__main__":
    unittest.main()
