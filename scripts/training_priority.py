"""Fail closed if a local model job could run at normal CPU priority."""
import os


def require_background():
    if not hasattr(os, 'getpriority') or os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise RuntimeError('Background priority was not applied. Run with nice -n 19; aborting before model access.')


if __name__ == '__main__':
    require_background()
