"""S30 call 1: organizations are created only by the CLI, run in the app
container as `python -m auspex.tenancy …`. Driven in-process here."""

import asyncio

import pytest
from _tenancy import drop_orgs

from auspex.db import create_pool
from auspex.tenancy.__main__ import main

PREFIX = "t-s30-cli"


@pytest.fixture
def clean(client, settings):
    async def _drop():
        pool = await create_pool(settings.database_url, retries=2, delay=0.5)
        try:
            await drop_orgs(pool, PREFIX)
        finally:
            await pool.close()

    asyncio.run(_drop())
    yield
    asyncio.run(_drop())


def test_the_cli_builds_an_mssp_and_lists_it_without_emails(clean, capsys):
    assert main(["create-org", "--kind", "provider", "--name", f"{PREFIX}-mssp",
                 "--workspace", f"{PREFIX}-mssp", "--admin", f"boss@{PREFIX}.auspex.dev"]) == 0
    assert main(["create-client", "--provider", f"{PREFIX}-mssp", "--name", f"{PREFIX}-bank",
                 "--workspace", f"{PREFIX}-bank", "--region", "ksa", "--restricted"]) == 0
    assert main(["set-member", "--workspace", f"{PREFIX}-mssp", "--email",
                 f"ops@{PREFIX}.auspex.dev", "--role", "analyst", "--provider-wide"]) == 0
    assert main(["set-restricted", "--client", f"{PREFIX}-bank", "off"]) == 0
    assert main(["remove-member", "--workspace", f"{PREFIX}-mssp", "--email",
                 f"ops@{PREFIX}.auspex.dev"]) == 0
    capsys.readouterr()
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert f"{PREFIX}-bank" in listed and "ksa" in listed
    assert "@" not in listed


def test_a_refusal_exits_1_with_the_reason(clean, capsys):
    assert main(["create-client", "--provider", f"{PREFIX}-nope", "--name", f"{PREFIX}-x",
                 "--workspace", f"{PREFIX}-x"]) == 1
    assert "No organization named" in capsys.readouterr().err


def test_an_unknown_region_is_refused_before_anything_is_written(clean, capsys):
    with pytest.raises(SystemExit):
        main(["create-org", "--kind", "direct", "--name", f"{PREFIX}-r",
              "--workspace", f"{PREFIX}-r", "--admin", f"r@{PREFIX}.auspex.dev",
              "--region", "mars"])
