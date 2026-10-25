"""Run the test suite; on failure, print each failing test as a GitHub annotation (readable on the run
page without opening the log). The suite runs in a child process that names each test as it starts, so a
silent crash (Windows aborts the process when a QThread outlives its window) still names the test."""
import io
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def child():
    import faulthandler
    faulthandler.enable(all_threads=True)  # an abort still prints where every thread was
    sys.path.insert(0, str(ROOT))  # as "python -m unittest" from the project root

    class Named(unittest.TextTestResult):
        def startTest(self, test):
            print('START', test, flush=True)
            super().startTest(test)

    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1, resultclass=Named).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
    sys.stderr.write(stream.getvalue())
    for test, trace in result.failures+result.errors:
        last = [line for line in trace.strip().splitlines() if line.strip()][-6:]
        message = ' | '.join(last).replace('%', '%25').replace('\r', '').replace('\n', ' ')[:900]
        print('::error title=%s::%s' % (str(test).replace(':', ' ').replace(',', ' ')[:200], message), flush=True)
    sys.exit(0 if result.wasSuccessful() else 1)


def main():
    process = subprocess.Popen([sys.executable, __file__, '--child'], stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    last = ''
    for line in process.stdout:
        if line.startswith('START '):
            last = line[6:].strip()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()
    code = process.wait()
    if code not in (0, 1):
        print('::error title=Test process crashed (exit %s)::The last test started was %s' % (code, last.replace(':', ' ')))
    sys.exit(0 if code == 0 else 1)


if __name__ == '__main__':
    child() if '--child' in sys.argv else main()
