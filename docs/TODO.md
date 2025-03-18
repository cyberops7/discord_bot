# ToDo

## Bot Features

- [ ] DM new members on join
- [ ] Link resources for common topics
   - Slash commands?
   - Buttons/dropdowns?

## Documentation

- [x] Move CONTRIBUTING and TODO into a docs/ directory

### CONTRIBUTING

- [x] Pre-commit hooks
- [ ] Using the DiscordBot class
- [x] Add new modules into `lib/`
- [ ] Add hyperlinks to tools table
- Testing
   - [x] How to run locally
   - [x] `invoke build-test`
   - [x] `invoke test-docker`
   - [x] Add `ACTIONS_STEP_DEBUG` set to `true` to Actions variable if debugging
     workflows
- [x] Update the `version` in `pyproject.toml`
- [x] make -> invoke
- [x] invoke shell completion (source <(inv --print-completion-script zsh))
- [ ] Add brief notes for each code quality tool
   - [ ] bandit
   - [ ] hadolint
   - [ ] shellcheck
   - [ ] trivy
   - [ ] yamllint

### README

- [ ] Bot features
- [ ] Brief architecture overview
- [ ] Link to discord.py documentation
- [ ] While tailored to Jim's Garage and my own dev environment, feel free to
      fork, etc.
- [ ] How to run your own instance of the bot - docker, kubernetes
   - [ ] For docker compose, you'll need to put your .env file in the same
         directory as your compose file. The current sample.env in the docker
         dir is a symlink to the one in the repository root.

## CI/CD

### Miscellaneous

- [x] Add new `test` dep group to `uv` for unit testing packages so we don't
      have to install all the linting deps into the test image
- [x] Change from makefile to Python Invoke
- [ ] Use trivy as a container instead of an installed binary?
- [ ] Cache uv/venv in check-test workflow
- [ ] Move dot files into a .conf directory?
- [ ] `pyre analyze`? `pyre infer`? `pyre persistent`?
- [ ] markdownlint -> markdownlint-cli2?
   - The current solution seems poorly maintained, is missing features like
     inline exclusions.
- [ ] Keep an eye on pyrefly as a replacement for pyre

### Makefile / Core Functions

- [x] Add ARG information to target help comments
- `make build`
   - [ ] add support for CACHE flag
- `make check`
   - [x] Run linters and checkers
   - [x] `make fix` as a fix-enabled version of `make check`
   - [x] Add yaml linting (yamllint)
   - [x] Add shellcheck
   - [ ] Change `make check` to call pre-commit commands?
         Could be a good way to prevent drift...
   - [ ] Compare/test between Pyre and Pyright
   - [ ] Add hadolint
- `make clean`
   - [x] Clean up old Docker containers and buildx builders
   - [x] Run as a prerequisite for `make run`, `make build`
- `make deps`
   - Check that dev dependencies are installed
   - [ ] hadolint
- `make publish`
   - [x] Make it a variant `build`, just with an extra flag to push the image
- `make run`
   - Run the bot container locally
- `make scan`
   - [ ] Get other scanners working
- `make test`
   - [x] add support for flag to run tests inside container
      - That will need to include having uv install deps

### Pre-commit Hooks

- [x] Ruff (check + format)
- [ ] ~~Pyre~~
   - ~~There are some recent fixes to the pre-commit-hooks,
     but there has not been a release yet that includes them~~
- [x] Trivy fs
- [x] uv lock
- [x] yamllint
- [x] shellcheck
- [ ] look for other good python pre-commit checks
- [x] check project version
- [x] Dockerfile linting (hadolint)
- [x] Makefile linting (makefilelint)
- [x] Just have it run `make check` and `make test`. No more duplicating.

### GitHub Actions

#### Submitted PRs

- [x] Lint/check code
- [x] Build image
- [x] Run automated/unit tests
- [x] Scan image

#### Accepted PRs

- [x] Build and publish image to ghcr

## Logging

- [x] Logger config read from yaml/JSON file
- [x] JSON log formatting
- [x] Log to a queue handler to make logging non-blocking
- [x] Bash logging library
- [x] Logs in bash files (colorized)
- [ ] Add more logging everywhere
- [x] Tune discord's noisy logs

## API

- [x] Logging config
- [x] API logs to separate file
- [ ] Uvicorn reverse proxy settings
- [ ] Uvicorn settings - workers, loop, etc.

## Docker

- [ ] ~~Write a healthcheck script (from discord.ext import tasks)~~
- [x] Investigate moving to python:3.13-alpine base image
- [x] Move to a `docker/` directory
- [x] A docker compose file
- [x] Expose/map the API port
- [x] Run as non-root user
- [ ] ~~Have `uv` install Python, just use non-python base image
      (Dockerfile and Dockerfile-test)~~ - no aarch64-musl pre-built version
      of python is availabe to `uv`.

## Kubernetes

- [x] Create `kubernetes/` directory with manifests
- [ ] Use a prod tag, not test
- [ ] Pull those into or from internal k3s repo (TBD)
- [ ] [Trivy config scanning](https://trivy.dev/v0.57/docs/scanner/misconfiguration/)

## Unit Testing

- [x] Choose a testing platform
- [x] Run tests in *-test Docker image

### Code Coverage

- [x] utils.py
- [ ] main.py
- [ ] api.py
- [ ] bot.py
- [ ] confi_parser.py
- [ ] logger_extras.py
- [ ] logger_setup.py
