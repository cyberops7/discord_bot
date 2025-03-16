# Contributing Guidelines

## Dev Scripts

The `scripts/` directory has a number of bash scripts to streamline common
development tasks. For ease of use, these scripts are mapped to various `make`
targets (see [Install Development Tools](#install-development-tools)
for installing `make`).

`make help` (or, simply `make`) will give you the most up-to-date state of
available targets, but this is a snapshot (which may or may not be up-to-date):

```text
❯ make help
Available commands:
  build           Build the Docker image with TAG
  check           Run linters and other code quality checks
  clean           Clean up resources (containers, builders, etc.)
  deps            Verify dependencies (e.g. Docker, buildx, uv)
  fix             Run linters and other code quality checks in fix mode
  publish         Build and push the Docker image with TAG
  run             Run the Docker image locally
  scan            Scan the Docker image:TAG for vulnerabilities
```

Use these commands to run linting checks, build test tags of the
Docker image, publish a test build to GitHub container registry, etc.

You can pass supported arguments to the targets like this:

```shell
make build TAG=new-feature-test
```

## Code Quality

This project leverages the following tools:

| Tool         | Use                           |
|--------------|-------------------------------|
| bandit       |                               |
| hadolint     |                               |
| markdownlint |                               |
| pyre         | Enforcing Python typing       |
| ruff         | Python formatting and linting |
| shellcheck   | Bash linting                  |
| trivy        | Vulnerability scanning        |
| yamllint     | Yaml linting                  |

Clean scans from all of these tools will be required for accepting Pull
Requests.

Checks by these tools are built into the `make check` command, which will
report problems they detect.

To have eligible problems automatically fixed, you can use `make fix` instead,
which runs the same checks but with different flags to enable remediation.

### Pre-Commit Hooks

`pre-commit` facilitates running many of the same tests that will
need to pass for PRs to be accepted, but running them before allowing
a `git commit` to go through. Enabling this will streamline the PR
process.

To manually run the checks against all files (not just changed files),
you can run:

```shell
pre-commit run --all-files
```

### Markdownlint Notes

To see information about the various linting checks,
see [Markdownlint RULES.md](https://github.com/markdownlint/markdownlint/blob/main/docs/RULES.md)

### Ruff Notes

Ruff performs both code formatting and code linting.

### Pyre Notes

Pyre will need to be run with the virtual environment active - at least, I have
not figured out how to get Pyre to place nice with a command like
`uvx --from pyre-check pyre check` and have it be able to find all the modules.
If someone else figures this out, I'd love to learn.

The way I have it working is to run Pyre from within the venv
(which is how their documentation says to run it):

```shell
source .venv/bin/activate
pyre check
```

Your IDE is likely already be activating your virtual environment if you have
things set up for Python, so if that is the case, `pyre` commands should work
as expected within your IDE's terminal.

If you make up dates to `.pyre_configuration`,
you need to run the following in order to pick up the new configuration.:

```shell
pyre restart
```

* Run a full scan:

   ```shell
   pyre check
   ```

* Run an incremental scan

   ```shell
   pyre
   ```

* Running `pyre` starts up a pyre server (if `watchman` is also installed
  on the host), and does an incremental check.

   * See the list of running servers:

     ```shell
     pyre servers
     ```

## Container Scanning

`make scan` will run a vulnerability scan against a fresh Docker image build.
Trivy is currently the default, but other scanners will be explored in the
future. A clean scan from Trivy (at least, with no new findings) will be
required for accepting Pull Requests.

## Dependencies

Python dependencies for this project are managed by `uv`.
Do not add Python modules to the project with `pip`, `poetry`, etc.

### Adding dependencies

To add a runtime dependency (needed for the code to run):

```shell
uv add package-name
```

To add a development dependency (needed for code linting, checking, etc.):

```shell
uv add --dev package-name
```

### Updating dependencies

If you want to upgrade dependencies and test for compatibility,
use `uv` to upgrade them all at once or one at a time.
Do thorough compatibility testing before submitting a PR
with updated dependencies.

* Upgrading a package

   ```shell
   uv lock --upgrade-package package-name
   ```

* Upgrading all packages

   ```shell
   uv lock --upgrade
   ```

## Testing

* TBD

## Dev Environment Setup

### Install Development Tools

* If you do not have `make` installed, you'll need to follow instructions for
  your OS:
   * macOS
      * `brew install make`
   * Linux
      * Use your OS's package manager (e.g. `sudo apt install make`)
   * Windows
      * If you have WSL setup, install it like you would in Linux
      * If you are using Cygwin, install it that way
      * If not, there appears to be a version more native for Windows:
        [Make for Windows](https://gnuwin32.sourceforge.net/packages/make.htm)
* Run `make deps` to check for non-python required packages.
  Install any that are missing.

   ```shell
   make deps
   ```

* Optional: add [uv and uvx shell completion](https://docs.astral.sh/uv/getting-started/installation/#shell-autocompletion)
    to your shell's rc file - e.g.:

   ```shell
   echo 'eval "$(uv generate-shell-completion zsh)"' >> ~/.zshrc
   echo 'eval "$(uvx --generate-shell-completion zsh)"' >> ~/.zshrc
   ```

### Sync Python Environment

This will take care of installing the correct Python version (if needed),
creating a virtual environment, and installing all Python dependencies.

```shell
uv sync --frozen
```

### Create your own `.env` file

The repo has a sample .env file that enumerates the environment variables that
you can tweak. Make a copy of it as `.env` for your own development
environment.

```shell
cp sample.env .env
```

This new file (`.env`) is ignored by git, so you can put your bot token in
there without worrying about it being committed.  Otherwise, you'll need to
provide your own token to the shell environment, Docker container, etc. in
some other way.

### Install Pre-Commit Hooks

The `pre-commit` Python module was installed as a dev dependency.
See [Pre-Commit Hooks](#pre-commit-hooks) for more information.
To enable it, run:

```shell
pre-commit install
```

## Running the app

During development, you may not want to keep building the Docker image and
running the container when you're iterating.

To easily run the app, you can use `uv`:

```shell
uv run main.py
```

`uv` will transparently activate the virtual environment and run the app inside
of it.
