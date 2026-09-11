"""Confirms cancelling run_command actually kills the OS subprocess, not just
the Python await -- asyncio.wait_for being cancelled does NOT do this on its
own; without the explicit proc.kill() in bash_tool.py, this leaves an orphaned
child process running after the tool call "stopped"."""

import asyncio
import os

import pytest

from samixa_code.agent.tools.bash_tool import RunCommandTool


async def test_cancelling_run_command_kills_the_subprocess(tmp_path):
    tool = RunCommandTool()
    marker = tmp_path / "still_running"

    # Writes a marker file every 0.1s in a loop; if the process survives
    # cancellation, the marker's mtime keeps advancing after we cancel.
    command = f"while true; do date +%s > {marker}; sleep 0.1; done"

    task = asyncio.create_task(tool.run({"command": command}, tmp_path))
    # Give the shell time to actually start and write the marker at least once.
    for _ in range(50):
        if marker.exists():
            break
        await asyncio.sleep(0.05)
    assert marker.exists(), "test setup failed: subprocess never started"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    mtime_at_cancel = os.stat(marker).st_mtime
    await asyncio.sleep(0.5)  # if the process survived, the marker would update again in this window
    mtime_after_wait = os.stat(marker).st_mtime

    assert mtime_after_wait == mtime_at_cancel, "subprocess kept running after the tool call was cancelled"
