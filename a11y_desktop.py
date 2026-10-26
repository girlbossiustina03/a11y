"""Launch the native desktop companion."""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description='A11y desktop accessibility companion')
    parser.add_argument('--panel', action='store_true', help='Also open the settings panel at launch')
    parser.add_argument('--self-test', metavar='RESULT_JSON', help='Check the packaged app (HTTPS, voice, Qt, helpers) and exit')
    args = parser.parse_args()
    from companion.paths import data_dir, frozen, use_bundled_certificates
    use_bundled_certificates()
    if args.self_test:
        from companion.self_test import run
        return run(args.self_test)
    if frozen():
        # A double-clicked app has no terminal: keep the timing/diagnostic log in its data folder.
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        log = directory/'a11y.log'
        if log.exists() and log.stat().st_size > 5_000_000:
            log.replace(directory/'a11y.previous.log')
        sys.stdout = sys.stderr = open(log, 'a', buffering=1, encoding='utf-8')
    # PyQt aborts the whole app on an exception inside a Qt callback unless an excepthook is set.
    # Log it and keep the companion running instead; the failing action simply does nothing.
    def log_unexpected(kind, value, trace):
        import traceback
        print('A11y unexpected error (the app kept running):', file=sys.stderr)
        traceback.print_exception(kind, value, trace, file=sys.stderr)
    sys.excepthook = log_unexpected
    try:
        from PyQt6.QtWidgets import QApplication
        from companion.desktop import CompanionWindow
    except ImportError as e:
        raise SystemExit('Install native dependencies with: python3 -m pip install -r requirements.txt\n'
                         +str(e))
    from companion.service import Companion
    from companion.instance import DesktopInstance, build_id
    service = Companion.from_env()
    try:
        instance = DesktopInstance(service.store.directory)
    except RuntimeError as error:
        print(str(error), file=sys.stderr, flush=True)
        notice_app = QApplication(sys.argv[:1])
        from companion.theme import apply_theme
        from PyQt6.QtWidgets import QMessageBox
        apply_theme(notice_app)
        QMessageBox.information(None, 'A11y is already running',
            'This launch did not load new code. Quit the existing companion from its right-click menu, then relaunch.\n\n'+str(error))
        return 1
    print(f'A11y desktop build {build_id()}', flush=True)
    # On macOS Qt's raise_() also activates the whole app. Raising the mascot after each action
    # then took keyboard focus from the app the user (or a task) was working in. Opening the
    # panel still activates A11y through activateWindow().
    os.environ.setdefault('QT_MAC_SET_RAISE_PROCESS', '0')
    app = QApplication(sys.argv[:1])
    from companion.theme import apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('A11y')
    app.setOrganizationName('A11y Hackathon')
    window = CompanionWindow(service)
    from companion import eval_control
    if eval_control.enabled():
        # scripts/live_eval.py drives this source run through an owner-only local socket.
        window.eval_control = eval_control.EvalControl(window, os.getenv('A11Y_EVAL_SOCKET') or service.store.directory/'eval.sock')
    window.start_companion()
    if args.panel:
        window.show()
    try:
        return app.exec()
    finally:
        instance.close()


if __name__ == '__main__':
    # Packaged apps re-launch themselves for multiprocessing helpers (joblib's resource
    # tracker); this runs the helper and exits before A11y parses its own arguments.
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
