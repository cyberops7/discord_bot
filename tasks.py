"""Compilation of Invoke tasks for common dev actions."""

import logging
from logging import Logger
from pathlib import Path

from invoke import Context, Result, task

from lib.logger_setup import configure_logger

logging.getLogger("lib.logger_setup").setLevel(logging.WARNING)
configure_logger()
logger: Logger = logging.getLogger(__name__)


# Default variables
_SCRIPTS_DIR_CACHE: dict[str, str] = {}
DEFAULT_IMAGE: str = "ghcr.io/cyberops7/discord_bot"
DEFAULT_TEST_IMAGE: str = "ghcr.io/cyberops7/discord_bot_test"
DEFAULT_TAG: str = "test"
DEFAULT_SCANNER: str = "trivy"


def get_scripts_dir(c: Context) -> str:
    if "dir" not in _SCRIPTS_DIR_CACHE:
        result: Result | None = c.run("git rev-parse --show-toplevel", hide=True)
        if result:
            _SCRIPTS_DIR_CACHE["dir"] = f"{Path(result.stdout.strip())}/scripts"
        else:
            msg = "Failed to retrieve git root directory."
            logger.error(msg)
            raise RuntimeError(msg)
    return _SCRIPTS_DIR_CACHE["dir"]


@task()
def clean(c: Context, silent: bool = False) -> None:
    """Clean up resources (containers, builders, etc.)."""
    if silent:
        logger.info("Cleaning resources quietly.")
        c.run(f"bash {get_scripts_dir(c)}/clean.sh", hide=True)
    else:
        logger.info("Cleaning resources with verbose output.")
        c.run(f"bash {get_scripts_dir(c)}/clean.sh")


@task
def deps(c: Context, silent: bool = False) -> None:
    """Verify dependencies (e.g. Docker, buildx, uv)."""
    if silent:
        logger.info("Checking dependencies quietly.")
        c.run(f"bash {get_scripts_dir(c)}/deps.sh", hide=True)
    else:
        logger.info("Checking dependencies with verbose output.")
        c.run(f"bash {get_scripts_dir(c)}/deps.sh")


@task()
def build(c: Context, image: str = DEFAULT_IMAGE, tag: str = DEFAULT_TAG) -> None:
    """Build the Docker image."""
    deps(c, silent=True)
    clean(c, silent=True)
    logger.info("Building Docker image '%s:%s'", image, tag)
    c.run(f"bash {get_scripts_dir(c)}/build.sh --image {image} --tag {tag} --local")


@task()
def build_test(c: Context, tag: str = DEFAULT_TAG) -> None:
    """Build the Docker test image."""
    deps(c, silent=True)
    clean(c, silent=True)
    logger.info("Building Docker test image with tag '%s'", tag)
    c.run(f"bash {get_scripts_dir(c)}/build.sh --tag {tag} --local --test")


@task
def check(c: Context) -> None:
    """Run linters and other code quality checks."""
    logger.info("Running code quality checks.")
    c.run(f"bash {get_scripts_dir(c)}/check.sh")


@task
def fix(c: Context) -> None:
    """Run linters and code quality checks (fix mode)."""
    logger.info("Running code quality checks and applying fixes.")
    c.run(f"bash {get_scripts_dir(c)}/check.sh --fix")


@task
def help(c: Context) -> None:  # noqa: A001
    """List available Invoke tasks."""
    c.run("invoke --list")


@task()
def publish(c: Context, tag: str = DEFAULT_TAG) -> None:
    """Build and push Docker image."""
    deps(c, silent=True)
    clean(c, silent=True)
    logger.info("Publishing Docker image with tag '%s'", tag)
    c.run(f"bash {get_scripts_dir(c)}/build.sh --tag {tag} --push")


@task()
def run(c: Context, image: str = DEFAULT_IMAGE, tag: str = DEFAULT_TAG) -> None:
    """Run the Docker image locally."""
    deps(c, silent=True)
    clean(c, silent=True)
    logger.info("Running Docker image '%s:%s' locally.", image, tag)
    c.run(f"bash {get_scripts_dir(c)}/run.sh --image {image} --tag {tag}")


@task()
def scan(
    c: Context,
    image: str = DEFAULT_IMAGE,
    scanner: str = DEFAULT_SCANNER,
    tag: str = DEFAULT_TAG,
) -> None:
    """Scan Docker image for vulnerabilities."""
    deps(c, silent=True)
    logger.info("Scanning Docker image '%s:%s' using scanner '%s'", image, tag, scanner)
    c.run(
        f"bash {get_scripts_dir(c)}/scan.sh "
        f"--image {image} --tag {tag} --scanner {scanner}"
    )


@task
def test(c: Context) -> None:
    """Run pytest unit tests locally."""
    logger.info("Running pytest unit tests locally.")
    c.run(f"bash {get_scripts_dir(c)}/test.sh")


@task
def test_docker(
    c: Context,
    image: str = DEFAULT_TEST_IMAGE,  # noqa: PT028 no default args for "tests"
    tag: str = DEFAULT_TAG,  # noqa: PT028 no default args for "tests"
) -> None:
    """Run pytest unit tests in Docker."""
    logger.info("Running pytest unit tests in Docker '%s:%s'", image, tag)
    c.run(f"bash {get_scripts_dir(c)}/test.sh --docker --image {image} --tag {tag}")
