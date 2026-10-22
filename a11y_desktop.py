"""Launch the native companion. Use server.py for the dependency-free web fallback."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description='A11y adaptive workplace companion')
    parser.add_argument('--panel', action='store_true', help='Also open the settings panel at launch')
    parser.add_argument('--admin', action='store_true', help='Enable local company document management')
    args = parser.parse_args()
    try:
        from PyQt6.QtWidgets import QApplication
        from companion.desktop import CompanionWindow
    except ImportError as e:
        raise SystemExit('Install native dependencies with: python3 -m pip install -r requirements.txt\n'
                         'Or launch the browser fallback: python3 server.py\n'+str(e))
    from companion.service import Companion
    from companion.instance import DesktopInstance, build_id
    service = Companion.from_env(admin=args.admin)
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
    app = QApplication(sys.argv[:1])
    from companion.theme import apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('A11y')
    app.setOrganizationName('A11y Hackathon')
    window = CompanionWindow(service)
    window.start_companion()
    if args.panel:
        window.show()
    try:
        return app.exec()
    finally:
        instance.close()


if __name__ == '__main__':
    sys.exit(main())
