"""Run the test suite; on failure, print each failing test as a GitHub annotation (readable on the run
page without opening the log) and exit non-zero."""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # as "python -m unittest" from the project root

stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=1).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
sys.stderr.write(stream.getvalue())
for test, trace in result.failures+result.errors:
    last = [line for line in trace.strip().splitlines() if line.strip()][-6:]
    message = ' | '.join(last).replace('%', '%25').replace('\r', '').replace('\n', ' ')[:900]
    print('::error title=%s::%s' % (str(test).replace(':', ' ').replace(',', ' ')[:200], message))
sys.exit(0 if result.wasSuccessful() else 1)
