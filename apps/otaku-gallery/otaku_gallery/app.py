"""Wiring: configuration -> gallery -> research manager -> HTTP server."""
import logging
import os
import sys
from functools import partial
from pathlib import Path

from .config import Config, ROOT, load_dotenv
from .evidence import Fixtures, gather_evidence
from .gallery import Gallery
from .nebius import NebiusWriter
from .research import ResearchManager
from .server import App, make_server


def build_app(config=None, writer=None, gather=None):
    config = config or Config.from_env()
    gallery = Gallery(config.root / "data" / "gallery.json", config.root / "web" / "art",
                      local_manifest=config.local_manifest, media_dir=config.local_manifest.parent)
    writer = writer or NebiusWriter()
    if gather is None:
        fixtures = Fixtures(config.root / "data" / "fixtures" / "wikipedia-snapshots.json")
        gather = partial(gather_evidence, mode=config.evidence_mode, fixtures=fixtures)
    manager = ResearchManager(writer, gather=gather, enabled=config.research_enabled,
                              rate_max_runs=config.rate_max_runs, cache_ttl=config.cache_ttl)
    return App(config, gallery, manager, writer, config.root / "web")


def main(argv=None):
    load_dotenv(Path.cwd() / ".env")
    logging.basicConfig(level=os.environ.get("OTAKU_LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    config = Config.from_env()
    app = build_app(config)
    try:
        server = make_server(app, config.host, config.port)
    except OSError as exc:
        print("Cannot listen on %s:%d (%s). Choose another port with OTAKU_PORT." % (config.host, config.port, exc.strerror),
              file=sys.stderr)
        return 2
    key_state = "configured" if app.writer.configured() else "NOT set (research falls back to source excerpts)"
    print("OTAKU Gallery (English) listening on http://%s:%d/  |  NEBIUS_API_KEY %s" % (config.host, config.port, key_state),
          file=sys.stderr)
    if config.host not in ("127.0.0.1", "::1", "localhost"):
        print("Warning: bound to a non-loopback address. Anyone who can reach this port can spend your API credit "
              "through /api/research (rate limited, but unauthenticated). Put it behind access control.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
