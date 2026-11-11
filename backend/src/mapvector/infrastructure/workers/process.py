import os
import subprocess
import time
from pathlib import Path

import psutil

from mapvector.domain.errors import CommandConflict


def terminate_owned_tree(process):
    """Only terminate descendants of the Popen instance created for this run."""
    try:
        parent=psutil.Process(process.pid)
        children=parent.children(recursive=True)
        for child in children:
            try:child.terminate()
            except psutil.NoSuchProcess:pass
        try:parent.terminate()
        except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs([*children,parent],timeout=3)
        for item in alive:
            try:item.kill()
            except psutil.NoSuchProcess:pass
        process.wait(timeout=5)
    except psutil.NoSuchProcess:
        process.poll()


def run_process(arguments,work,environment,on_start,on_heartbeat,is_cancelled,timeout_seconds,timeout_code):
    stdout_path=Path(work)/'stdout.log';stderr_path=Path(work)/'stderr.log'
    with stdout_path.open('ab') as stdout,stderr_path.open('ab') as stderr:
        process=subprocess.Popen(arguments,cwd=work,env=environment,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0),start_new_session=os.name!='nt')
        started=time.monotonic();heartbeat=0.
        try:
            on_start(process)
            while process.poll() is None:
                if is_cancelled():raise CommandConflict('RUN_CANCELLED')
                if time.monotonic()-started>timeout_seconds:raise CommandConflict(timeout_code)
                if time.monotonic()-heartbeat>=1:
                    on_heartbeat();heartbeat=time.monotonic()
                time.sleep(.1)
            if is_cancelled():raise CommandConflict('RUN_CANCELLED')
            if process.returncode:
                stdout.flush();stderr.flush()
                with stderr_path.open('rb') as stream:
                    stream.seek(max(0,stderr_path.stat().st_size-6000));detail=stream.read().decode('utf-8',errors='replace')
                raise CommandConflict('OCR_EXECUTION_FAILED' if 'ocr' in str(arguments).lower() or 'paddle.py' in str(arguments) else 'RECOGNITION_FAILED',{'returncode':process.returncode,'reason':detail})
        finally:
            if process.poll() is None:terminate_owned_tree(process)


def worker_is_alive(pid,run_id):
    if not pid:return False
    try:
        process=psutil.Process(pid)
        return process.is_running() and run_id in ' '.join(process.cmdline())
    except (psutil.NoSuchProcess,psutil.AccessDenied,ValueError):return False
