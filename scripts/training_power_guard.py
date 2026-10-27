"""Run a fixed local training command; cleanly stop on low battery or an owner stop file."""
import argparse
import json
from pathlib import Path
import re
import signal
import subprocess
import time


def low_battery(text, threshold=25):
    level = re.search(r'(\d+)%;',text)
    if not level or not any(source in text for source in ("'AC Power'","'Battery Power'")):
        raise ValueError('Power status unavailable')
    return "'Battery Power'" in text and int(level.group(1)) <= threshold


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:
        parser.error('A training command is required')
    state = dict(status='checking power',started=time.time())
    def save():
        args.state.write_text(json.dumps(state,indent=2)+'\n')
    def power():
        return subprocess.run(['pmset','-g','batt'],capture_output=True,text=True,check=True,timeout=5).stdout
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    child = None
    try:
        if low_battery(power()):
            raise RuntimeError('battery at or below 25%; plug in before training')
        with args.log.open('w') as log:
            child = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            state.update(status='training',pid=child.pid);save()
            while child.poll() is None:
                if args.state.with_suffix('.stop').exists():
                    raise RuntimeError('owner stop file')
                if low_battery(power()):
                    raise RuntimeError('battery at or below 25%; saving and stopping')
                time.sleep(10)
            state.update(status='complete' if child.returncode==0 else 'failed',returncode=child.returncode)
    except (KeyboardInterrupt,RuntimeError,ValueError,subprocess.SubprocessError) as error:
        state.update(status='stopping',reason=str(error) or 'owner interrupted');save()
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                child.send_signal(signal.SIGSTOP)
                state.update(status='paused: clean stop unresponsive; do not resume automatically')
            else:
                state.update(status='stopped',returncode=child.returncode)
        else:
            state['status']='not started'
    finally:
        state['updated']=time.time();save()


if __name__=='__main__':
    main()
