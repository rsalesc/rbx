from rbx.box.ui.task_queue import TaskQueue, TaskStatus


class TestTaskQueue:
    def _make_queue(self, num_terminals=3, parallel=True):
        self.ready_tasks = []
        return TaskQueue(
            num_terminals=num_terminals,
            parallel=parallel,
            on_task_ready=lambda t: self.ready_tasks.append(t),
        )

    def test_enqueue_starts_immediately_when_idle(self):
        q = self._make_queue()
        task = q.enqueue('echo hello', terminal_id=0)
        assert task.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 1
        assert self.ready_tasks[0] is task

    def test_enqueue_stays_pending_when_terminal_busy(self):
        q = self._make_queue()
        t1 = q.enqueue('echo first', terminal_id=0)
        t2 = q.enqueue('echo second', terminal_id=0)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert len(self.ready_tasks) == 1

    def test_notify_complete_starts_next_in_same_terminal(self):
        q = self._make_queue()
        t1 = q.enqueue('echo first', terminal_id=0)
        t2 = q.enqueue('echo second', terminal_id=0)
        q.notify_complete(t1.task_id)
        assert t1.status == TaskStatus.COMPLETED
        assert t2.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 2

    def test_parallel_different_terminals_run_concurrently(self):
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 2

    def test_exclusive_waits_for_all_idle(self):
        q = self._make_queue(parallel=False)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        # Sequential mode: all exclusive. t1 runs, t2 waits.
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        # Complete t1 -> t2 starts.
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING

    def test_exclusive_blocks_behind_running_other_terminal(self):
        """An exclusive task must wait even if its own terminal is idle."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        # Enqueue an exclusive task on terminal 1 in parallel mode.
        t2 = q.enqueue('exclusive cmd', terminal_id=1, exclusive=True)
        # t1 is running on terminal 0, so exclusive t2 can't start.
        assert t2.status == TaskStatus.PENDING
        # Complete t1 -> now all idle -> t2 starts.
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING

    def test_ordering_same_terminal_preserved(self):
        """Tasks on the same terminal run in FIFO order."""
        q = self._make_queue()
        t1 = q.enqueue('echo 1', terminal_id=0)
        t2 = q.enqueue('echo 2', terminal_id=0)
        t3 = q.enqueue('echo 3', terminal_id=0)
        assert [t.status for t in [t1, t2, t3]] == [
            TaskStatus.RUNNING,
            TaskStatus.PENDING,
            TaskStatus.PENDING,
        ]
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t2.task_id)
        assert t3.status == TaskStatus.RUNNING

    def test_non_exclusive_skips_blocked_terminal(self):
        """A task on terminal 1 can start even if terminal 0 has a pending task blocked behind a running one."""
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=0)  # blocked behind t1
        t3 = q.enqueue('echo c', terminal_id=1)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.RUNNING

    def test_auto_increments_task_id(self):
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        assert t1.task_id == 0
        assert t2.task_id == 1

    def test_notify_complete_unknown_id_is_noop(self):
        q = self._make_queue()
        q.notify_complete(999)  # Should not raise.

    def test_completed_tasks_pruned_from_queue(self):
        """Completed tasks are removed from the internal queue after drain."""
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        q.notify_complete(t1.task_id)
        # After completion and drain, the queue should be empty.
        assert len(q) == 0

    def test_exclusive_unblocks_after_all_terminals_idle(self):
        """An exclusive task starts only after ALL other running tasks finish."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        t3 = q.enqueue('exclusive', terminal_id=2, exclusive=True)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.RUNNING
        assert t3.status == TaskStatus.PENDING
        # Complete t1 -> t3 still blocked because t2 is running.
        q.notify_complete(t1.task_id)
        assert t3.status == TaskStatus.PENDING
        # Complete t2 -> all idle -> t3 starts.
        q.notify_complete(t2.task_id)
        assert t3.status == TaskStatus.RUNNING

    def test_non_exclusive_starts_despite_blocked_exclusive_on_other_terminal(self):
        """A non-exclusive task on a free terminal can start even if an exclusive task is blocked."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        # Exclusive task on terminal 1 -- blocked because terminal 0 is running.
        t2 = q.enqueue('exclusive', terminal_id=1, exclusive=True)
        # Non-exclusive task on terminal 2 -- should start despite t2 being blocked.
        t3 = q.enqueue('echo c', terminal_id=2)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.RUNNING

    def test_multiple_exclusive_tasks_run_sequentially(self):
        """Multiple exclusive tasks run one at a time."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('ex1', terminal_id=0, exclusive=True)
        t2 = q.enqueue('ex2', terminal_id=1, exclusive=True)
        t3 = q.enqueue('ex3', terminal_id=2, exclusive=True)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t2.task_id)
        assert t3.status == TaskStatus.RUNNING

    def test_single_terminal_fifo(self):
        """With a single terminal, tasks run strictly in FIFO order."""
        q = self._make_queue(num_terminals=1, parallel=True)
        t1 = q.enqueue('echo 1', terminal_id=0)
        t2 = q.enqueue('echo 2', terminal_id=0)
        t3 = q.enqueue('echo 3', terminal_id=0)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t2.task_id)
        assert t3.status == TaskStatus.RUNNING

    def test_explicit_exclusive_false_overrides_non_parallel(self):
        """Setting exclusive=False in non-parallel mode allows concurrent execution."""
        q = self._make_queue(parallel=False)
        t1 = q.enqueue('echo a', terminal_id=0, exclusive=False)
        t2 = q.enqueue('echo b', terminal_id=1, exclusive=False)
        # Both should run because exclusive is explicitly False.
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.RUNNING

    def test_task_stores_correct_fields(self):
        """Task fields match what was passed to enqueue."""
        q = self._make_queue()
        task = q.enqueue('my-command', terminal_id=2)
        assert task.command == 'my-command'
        assert task.terminal_id == 2
        assert task.exclusive is False  # parallel=True -> not exclusive

    def test_exclusive_starts_immediately_when_all_idle(self):
        """An exclusive task starts immediately if no other task is running."""
        q = self._make_queue(parallel=True)
        task = q.enqueue('exclusive', terminal_id=1, exclusive=True)
        assert task.status == TaskStatus.RUNNING

    def test_queue_empty_after_all_complete(self):
        """Internal queue is empty once all tasks have been completed."""
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        q.notify_complete(t1.task_id)
        q.notify_complete(t2.task_id)
        assert len(q) == 0

    def test_non_exclusive_blocked_by_busy_terminal_not_by_other_terminals(self):
        """A non-exclusive pending task is only blocked by its own terminal, not others."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=0)  # blocked: terminal 0 busy
        t3 = q.enqueue('echo c', terminal_id=1)
        t4 = q.enqueue('echo d', terminal_id=1)  # blocked: terminal 1 busy
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.RUNNING
        assert t4.status == TaskStatus.PENDING
        # Complete t1 -> t2 starts, t4 still blocked
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING
        assert t4.status == TaskStatus.PENDING
