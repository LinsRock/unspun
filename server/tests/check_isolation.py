"""Fail before regression unless the fresh mock database and egress block hold."""

import socket

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from unspun.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.openrouter_api_key:
        raise SystemExit("isolated regression requires an empty real API key")
    url = make_url(settings.database_url)
    if url.host != "127.0.0.1" or url.database != "unspun_test":
        raise SystemExit("use only the new isolated loopback unspun_test database")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT count(*) FROM articles")) != 0:
                raise SystemExit("isolated regression requires an empty migrated database")
    finally:
        engine.dispose()
    for family, host in (
        (socket.AF_INET, "1.1.1.1"),
        (socket.AF_INET6, "2606:4700:4700::1111"),
    ):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                probe.connect((host, 443))
        except OSError:
            continue
        raise SystemExit("external network is reachable; refuse to run regressions")
    print("isolation verified: empty key, fresh database, IPv4/IPv6 egress blocked")


if __name__ == "__main__":
    main()
