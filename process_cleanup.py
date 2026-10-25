"""Last-resort ownership when OS/process cleanup cannot be confirmed.

Independent steps still run after failures. A live child's files are retained;
the entry point terminates the host so OS-owned Jobs/handles are reclaimed.
"""
_retained = []


class IncompleteProcessCleanup(RuntimeError):
    pass


def has_retained_resources():
    return bool(_retained)


def retain(resource):
    _retained.append(resource)


def _message(*parts):
    try:
        print(*parts, flush=True)
    except BaseException:
        pass


def close_job(kernel, job):
    if not kernel.CloseHandle(job):
        raise OSError('Could not close process Job Object')


def close_trace(trace):
    try:
        trace.close()
    except BaseException:
        retain(trace)
        raise


def preserve_temp(temp):
    # TemporaryDirectory's exit finalizer must not remove a live child's files.
    retain(temp)
    finalizer = getattr(temp, '_finalizer', None)
    if finalizer is not None:
        finalizer.detach()


def cleanup_scheduler(api, job, slots, dispose, temp):
    errors = []
    if job:
        try:
            close_job(api.kernel32, job)
        except BaseException as exc:
            retain(job)
            errors.append(exc)
    for index in range(len(slots)):
        try:
            dispose(index)
        except BaseException as exc:
            errors.append(exc)
            _message(f'[independent] cleanup warning slot={index + 1}:', exc)
    if temp is not None:
        if any(slot is not None for slot in slots):
            retain(slots)
            preserve_temp(temp)
        else:
            try:
                temp.cleanup()
            except BaseException as exc:
                preserve_temp(temp)
                errors.append(exc)
    if errors:
        raise IncompleteProcessCleanup('Scheduler cleanup incomplete; process exit required') from errors[0]


def cleanup_supervisor(kernel, job, backdrop, guard, trace, snapshot, restore,
                       unassigned=None, workspace_cleanup=None):
    """Order: Job, desktop restoration, guard, trace, config snapshot.

    Each release is attempted even if a preceding independent release fails.
    Failed owners stay strongly reachable until the entry point forces exit.
    """
    errors = []
    def attempt(owner, action):
        try:
            action()
            return True
        except BaseException as exc:
            retain(owner)
            errors.append(exc)
            _message('[shutdown] supervisor cleanup warning:', exc)
            return False

    if workspace_cleanup is not None:
        attempt(workspace_cleanup, workspace_cleanup)
    if job:
        _message('[supervisor] closing worker Job Object; any remaining worker will be terminated')
        attempt(job, lambda: close_job(kernel, job))
    if unassigned is not None:
        def stop_unassigned():
            try:
                if unassigned.poll() is None:
                    unassigned.kill()
            finally:
                unassigned.wait(timeout=5)
        attempt(unassigned, stop_unassigned)
    if backdrop is not None:
        _message('[supervisor] restoring Windows desktop and closing black backdrop')
    attempt(backdrop, lambda: restore(backdrop))
    if guard is not None:
        if attempt(guard, guard.close):
            if backdrop is not None:
                backdrop.supervisor_guard = None
    if trace is not None:
        attempt(trace, trace.close)
    if snapshot is not None:
        attempt(snapshot, snapshot.close)
    if errors:
        raise IncompleteProcessCleanup('Supervisor cleanup incomplete; process exit required') from errors[0]
