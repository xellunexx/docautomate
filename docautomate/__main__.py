"""Start the app:  python -m docautomate  (opens http://127.0.0.1:5000 in the browser)."""
import argparse
import threading
import webbrowser

from .app import create_app


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = само този компютър")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    app = create_app()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Docautomate работи на {url}  (спиране: Ctrl+C)")
    print(f"Данни: {app.config['DATA_DIR']}")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve  # optional, quieter production server
        serve(app, host=args.host, port=args.port)
    except ImportError:
        app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
