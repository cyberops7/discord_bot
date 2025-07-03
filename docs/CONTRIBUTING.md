# Contributing

* [General Guidelines](#general-guidelines)
* [Key Tools](#key-tools)
  * [uv](#uv)
  * [Invoke](#invoke)
  * [Dev Scripts](#dev-scripts)
  * [Pre-Commit Hooks](#pre-commit-hooks)
* [Dev Environment Setup](#dev-environment-setup)
  * [Install / Setup `uv`](#install--setup-uv)
  * [Sync Python Environment](#sync-python-environment)
  * [Install Development Tools](#install-development-tools)
  * [Create your own `.env` file](#create-your-own-env-file)
  * [Install Pre-Commit Hooks](#install-pre-commit-hooks)
  * [Set up Invoke shell completion](#set-up-invoke-shell-completion)
* [Code Quality](#code-quality)
  * [Markdownlint Notes](#markdownlint-notes)
  * [Ruff Notes](#ruff-notes)
  * [Pyre Notes](#pyre-notes)
* [Container Scanning](#container-scanning)
* [Dependencies](#dependencies)
  * [Adding dependencies](#adding-dependencies)
  * [Updating dependencies](#updating-dependencies)
* [Running the app](#running-the-app)
* [Testing](#testing)
  * [Testing GitHub Actions / Workflows](#testing-github-actions--workflows)

## General Guidelines

* Keep `main.py` clean and light. If necessary, extend it with functions from
  a module in `lib/`.
* Build new Discord functionality around the `DiscordBot` class in `lib/bot.py`
* Use the logger available in this project. Don't use `print()` statements.
* With every PR, you'll be required to increment the app `version` found in
  `pyproject.toml`. This `version` is used to generate the tags for the new
  image built after each PR, and each PR needs to result in a unique tag.
  * The `version` uses [semantic versioning](https://semver.org/):

> Given a version number MAJOR.MINOR.PATCH, increment the:
> 1. MAJOR version when you make incompatible API changes
> 2. MINOR version when you add functionality in a backward compatible manner
> 3. PATCH version when you make backward compatible bug fixes

* Create unit tests for your additions/changes. See [Testing](#testing) for
  more details.

## Key Tools

### uv

This repo uses `uv` for managing the Python project and dependencies. If you
are unfamiliar with it, you can find plentiful documentation here:
[uv docs](https://docs.astral.sh/uv/).

> [!IMPORTANT]
> Do not use `pip`, `pipx`, `poetry`, or other similar tools for managing the
> Python environment.

### Invoke

> Invoke is a Python library for managing shell-oriented subprocesses and
> organizing executable Python code into CLI-invokable tasks.

\- [Invoke Docs](https://www.pyinvoke.org/)

A variety of key dev actions for the project are wrapped up into Invoke tasks.
It will get installed as a project dependency when you
[sync the Python environment](#sync-python-environment).

> [!TIP]
> By default, there is also an alias `inv` that you can use in place of `invoke`
> in your terminal.

If you feel there are frequent dev tasks you'd like to automate, feel free to
submit a PR or Issue with your ideas.

> [!NOTE]
> To use `invoke`, the virtual environment must be activated.
> Otherwise, you will need to use `uv run invoke` to run the tasks.

### Dev Scripts

The `scripts/` directory has a number of bash scripts to streamline common
development tasks. For ease of use, these scripts are mapped to various `invoke`
tasks.

`invoke help` will give you the most up-to-date state of available tasks,
but this is a snapshot (which may or may not be up-to-date):

```text
❯ invoke help
Available tasks:

  build         Build the Docker image.
  build-test    Build the Docker test image.
  check         Run linters and other code quality checks.
  clean         Clean up resources (containers, builders, etc.).
  deps          Verify dependencies (e.g. Docker, buildx, uv).
  fix           Run linters and code quality checks (fix mode).
  help          List available Invoke tasks.
  publish       Build and push Docker image.
  run           Run the Docker image locally.
  scan          Scan Docker image for vulnerabilities.
  test          Run pytest unit tests locally.
  test-docker   Run pytest unit tests in Docker.
```

You can use these commands to run linting checks, build test tags of the
Docker image, run unit tests, etc.

You can pass supported arguments to the tasks like this:

```shell
invoke build --tag new-feature-test
```

### Pre-Commit Hooks

`pre-commit` facilitates running many of the same tests that will
need to pass for PRs to be accepted, and running those before allowing
a `git commit` to go through. Enabling this will streamline the PR
process, but does admittedly slow down your `git commit`s.

To manually run the checks against all files (not just changed files),
you can run:

```shell
pre-commit run --all-files
```

Make sure you [enable/install them](#install-pre-commit-hooks) as part of the
environment setup.

> [!TIP]
> Be sure to leverage tasks like `invoke check` and `invoke test` during your
> development work to check your changes along the way. Pre-commit runs these
> same tasks before letting a commit go through.

## Dev Environment Setup

### Install / Setup `uv`

If you do not have it installed already, you can follow the installation
instructions for your operating system here:
[uv installation](https://docs.astral.sh/uv/getting-started/installation/).

Optional: add
[uv and uvx shell completion](https://docs.astral.sh/uv/getting-started/installation/#shell-autocompletion)
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

### Install Development Tools

Run `invoke deps` to check for non-python required packages.
Install any that are missing.

   ```shell
   invoke deps
   ```

### Create your own `.env` file

The repo has a sample .env file that enumerates the environment variables that
you can tweak. Make a copy of it as `.env` for your own development
environment.

```shell
cp sample.env .env
```

This new file (`.env`) is ignored by git, so you can put your bot token in
there without worrying about it being committed. Otherwise, you'll need to
provide your own token to the shell environment, Docker container, etc. in
some other way.

### Install Pre-Commit Hooks

The `pre-commit` Python module was installed as a dev dependency.
See [Pre-Commit Hooks](#pre-commit-hooks) for more information.
To enable the hooks for this repo, run:

```shell
pre-commit install
```

### Set up Invoke shell completion

To make things easier using `invoke`/`inv`, you can set up tab completion for
your shell. Invoke has docs on this [here](https://docs.pyinvoke.org/en/stable/invoke.html#shell-tab-completion).

Essentially, `invoke` can generate a completion script for you that you need
to source in your shell's rc file. If you're using `zsh`, you can add:

* Create the completion script in your home directory:

  ```shell
  inv --print-completion-script zsh > ~/.invoke-completion.sh
  ```

* Source the script in your rc file:

  ```shell
  echo "source ~/.invoke-completion.sh" >> ~/.zshrc
  ```

## Code Quality

This project leverages the following tools:

| Tool         | Use                           | Reference                                                 |
|--------------|-------------------------------|-----------------------------------------------------------|
| bandit       | Python security linting       | https://bandit.readthedocs.io/en/latest/start.html        |
| hadolint     | Dockerfile linting            | https://github.com/hadolint/hadolint?tab=readme-ov-file   |
| markdownlint | Markdown linting              | https://github.com/markdownlint/markdownlint              |
| pyre         | Enforcing Python typing       | https://pyre-check.org/                                   |
| ruff         | Python formatting and linting | https://docs.astral.sh/ruff/                              |
| shellcheck   | Bash linting                  | https://github.com/koalaman/shellcheck?tab=readme-ov-file |
| trivy        | Vulnerability scanning        | https://trivy.dev/latest/docs/                            |
| yamllint     | Yaml linting                  | https://yamllint.readthedocs.io/en/stable/                |

Clean scans from all of these tools will be required for accepting Pull
Requests.

Checks by these tools are built into the `invoke check` command, which will
report problems they detect.

To have eligible problems automatically fixed, you can use `invoke fix` instead,
which runs the same checks but with different flags to enable remediation.
Only a subset of the tools support automated fixing.

### Markdownlint Notes

To see information about the various linting checks,
see [Markdownlint RULES.md](https://github.com/markdownlint/markdownlint/blob/main/docs/RULES.md)

### Ruff Notes

Ruff performs both code formatting and code linting. Within the virtual
environment, you can run:

```shell
ruff format
```

to quickly reformat Python files, and

```shell
ruff check
```

to run `ruff`'s linting checks. Both of these are included as part of
`invoke check`, but it can be useful to run them separately when working
through a longer list of things to fix.

### Pyre Notes

Pyre will need to be run with the virtual environment active. From within the
venv, you can run:

```shell
pyre check
```

From outside the venv, you can run:

```shell
uv run pyre check
```

If you simply run `pyre`, that starts up a background `pyre` server that works
together with `watchman` to enable doing incremental `pyre` checks on
changed files.

If you have `pyre` running in the background and make updates to
`.pyre_configuration`, you need to run the following to pick up the
new configuration:

```shell
pyre restart
```

Other related commands:

* See the list of running servers:

   ```shell
   pyre servers
   ```

* Stop the `pyre` server:

   ```shell
   pyre stop
   ```

* Stop all `pyre` servers (I have ended up with multiple `pyre` processes
  running before when experimenting with `pyre`):

   ```shell
   pyre kill
   ```

## Container Scanning

`invoke scan` will run a vulnerability scan against a fresh Docker image build.
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

To add a testing dependency (needed for running unit tests):

```shell
uv add --group test package-name
```

### Updating dependencies

If you want to upgrade dependencies and test for compatibility, use `uv` to
upgrade them all at once or one at a time. Do thorough compatibility/regression
testing before submitting a PR with updated dependencies.

* Upgrading a package

   ```shell
   uv lock --upgrade-package package-name
   ```

* Upgrading all packages

   ```shell
   uv lock --upgrade
   ```

## Running the app

During development, you may not want to keep building the Docker image and
running the container when you're quickly iterating.

To easily run the app, you can use `uv`:

```shell
uv run main.py
```

`uv` will transparently activate the virtual environment and run the app inside
of it.

## Testing

This project uses `pytest` for its unit testing:
[pytest docs](https://docs.pytest.org/en/stable/).

A pair of `invoke` tasks are provided for running the suite of unit tests:

```shell
invoke test
```

and

```shell
invoke test-docker
```

`invoke test` runs the unit tests in your virtual environment.

`invoke test-docker` runs the unit tests inside a Docker image that is
representative of the application/production image. You can build yourself
a copy of the test image by running:

```shell
invoke build-test
```

This image does not include the actual application or test files - those get
volume mounted into the container. The image itself is simply the same base
as the production image with the extra dependencies needed for running the
unit tests. This arrangement means that you do not need to keep rebuilding
the test image as the application or test files change. You only need to
rebuild the image if you change the dependencies or make other changes to
the Dockerfiles.

### Testing GitHub Actions / Workflows

If you have made changes to the GitHub Actions/Workflows and need some better
signal around what is happening, you can enable debug mode for the repo's
workflows.

To do this, you'll need privileged access to the repo. With that access
granted, navigate from the GitHub repo to Settings -> Security -> Secrets and
Variables -> [Variables](https://github.com/cyberops7/discord_bot/settings/variables/actions).
There is already a `ACTIONS_STEP_DEBUG` variable defined with a value of
`false`. Change that to `true`, and re-run the workflow. Don't forget to
change it back to `false` when you are done.
