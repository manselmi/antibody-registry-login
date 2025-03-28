#!/usr/bin/env python
# vim: set ft=python :

import getpass
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from threading import RLock
from typing import Annotated

import lxml.html
import structlog
import typer
from httpx import (
    URL,
    Auth,
    Client,
    Cookies,
    Request,
    Response,
    Timeout,
    codes,
)
from lxml.etree import _ElementUnicodeResult

from logging_config import configure_logging
from secret import Secret, secret_cmd_argv, secret_env_var

logger = structlog.get_logger(__name__)


HTTP2 = True
TIMEOUT = Timeout(10.0)  # seconds


class AntibodyRegistryAuth(Auth):
    def __init__(self, cookies: Cookies | None = None, /) -> None:
        self._cookies = cookies
        self._lock = RLock()

    @property
    def cookies(self) -> Cookies | None:
        with self._lock:
            return self._cookies

    def _set_cookie_header(self, request: Request) -> None:
        with self._lock:
            if self._cookies is not None:
                self._cookies.set_cookie_header(request)

    def sync_auth_flow(self, request: Request) -> Generator[Request, Response]:
        with self._lock:
            self._set_cookie_header(request)
            response = yield request

            if response.status_code == codes.UNAUTHORIZED:
                self._cookies = login_to_antibody_registry()
                self._set_cookie_header(request)
                yield request

    async def async_auth_flow(self, request: Request) -> AsyncGenerator[Request, Response]:  # type: ignore[override] # noqa: ARG002
        msg = "async_auth_flow_not_implemented"
        logger.error(msg)
        raise RuntimeError(msg)


def login_to_antibody_registry() -> Cookies:
    username, password = get_antibody_registry_credentials()

    with Client(follow_redirects=True, http2=HTTP2, timeout=TIMEOUT) as client:
        response = client.get(URL("https://www.antibodyregistry.org/login"))
        response.raise_for_status()

        cookies = response.cookies
        tree = lxml.html.fromstring(response.content)
        xpath: list[_ElementUnicodeResult] = tree.xpath('//form[@id="kc-form-login"]/@action')  # type: ignore[assignment]
        if not xpath:
            msg = "login_post_url_not_found"
            logger.error(msg)
            raise RuntimeError(msg)
        login_post_url = URL(str(xpath[0]))

        response = client.post(
            login_post_url,
            cookies=cookies,
            data={
                "username": username.get_secret_value(),
                "password": password.get_secret_value(),
                "rememberMe": "on",
                "credentialId": "",
            },
        )
        response.raise_for_status()

        return response.history[1].cookies


def get_antibody_registry_credentials() -> tuple[Secret, Secret]:
    if getpass.getuser() in {"manselmi", "m.anselmi"}:
        username = secret_cmd_argv(
            [
                "op",
                "read",
                "--no-newline",
                "op://yksesvynnyj573ps3dagfglceu/ynqycbcmytlr3qx4ggbxioriiu/username",
            ],
        )
        password = secret_cmd_argv(
            [
                "op",
                "read",
                "--no-newline",
                "op://yksesvynnyj573ps3dagfglceu/ynqycbcmytlr3qx4ggbxioriiu/password",
            ],
        )
    else:
        username = secret_env_var("ANTIBODY_REGISTRY_USERNAME")
        password = secret_env_var("ANTIBODY_REGISTRY_PASSWORD")

    return username, password


def main(
    logging_config: Annotated[
        Path, typer.Option(help="file from which the logging configuration will be read")
    ] = Path("logging_config.json"),
) -> None:
    configure_logging(logging_config)

    auth = AntibodyRegistryAuth()
    with Client(auth=auth, http2=HTTP2, timeout=TIMEOUT) as client:
        for url in map(
            URL,
            [
                "https://www.antibodyregistry.org/api/antibodies?size=10&page=51",
                "https://www.antibodyregistry.org/api/antibodies?size=10&page=52",
            ],
        ):
            client.get(url)


if __name__ == "__main__":
    typer.run(main)
