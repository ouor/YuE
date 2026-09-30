"""YuE2 Song Studio — run with: python app/app.py [--port 7860] [--share]"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.config import Settings  # noqa: E402
from studio.core import Studio  # noqa: E402
from studio.ui.layout import build, launch_options  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--share", action="store_true", default=None)
    parser.add_argument("--data-dir", type=Path, help="Where songs are stored (default: app/data)")
    parser.add_argument("--device", help="auto, cuda, cuda:1, cpu …")
    parser.add_argument("--offline", action="store_true", default=None, help="Use cached/local models only")
    parser.add_argument("--ssl-cert", dest="ssl_certfile", help="PEM certificate to serve HTTPS")
    parser.add_argument("--ssl-key", dest="ssl_keyfile", help="PEM private key to serve HTTPS")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings().with_overrides(host=args.host, port=args.port, share=args.share, data_dir=args.data_dir,
                                         device=args.device, offline=args.offline, ssl_certfile=args.ssl_certfile,
                                         ssl_keyfile=args.ssl_keyfile)
    studio = Studio(settings)
    demo, ctx = build(studio)
    demo.queue(default_concurrency_limit=8)
    auth = tuple(settings.auth.split(":", 1)) if settings.auth and ":" in settings.auth else None
    demo.launch(server_name=settings.host, server_port=settings.port, share=settings.share, i18n=ctx.i18n,
                auth=auth, ssl_certfile=settings.ssl_certfile, ssl_keyfile=settings.ssl_keyfile,
                ssl_verify=False, **launch_options(settings))


if __name__ == "__main__":
    main()
