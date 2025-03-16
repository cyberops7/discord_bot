# discord_bot

A bot for Jim's Garage Discord Server

## Bot Features

TBD

## API

The bot runs a FastAPI webserver in parallel to the bot, providing an API to
interact with the bot.

The webserver defaults to port `8080`, but you can customize this by setting
the `API_PORT` environment variable. That said, when running this as a
container, you should probably leave that alone and just map a different host
port if needed.

### Endpoints

Automatically generated API documentation is available at:

- `/docs`
- `/redoc`

#### GET /healthcheck

#### GET /status

## Running the bot

The bot is packaged up inside a Docker image, which can be run
via Docker, Docker Compose, or Kubernetes.

The following environment variables are supported:

| ENV VAR          | Required | Use                                                    | Default  |
|------------------|----------|--------------------------------------------------------|----------|
| API_PORT         | No       | Set the port the API listens on (inside the container) | 8080     |
| BOT_TOKEN        | YES      | The token for your Discord bot                         | N/A      |
| LOG_DIR          | No       | Directory where the bot's logs will be written         | /app/log |
| LOG_FILE         | No       | Filename the logs will be written to                   | bot.log  |
| LOG_LEVEL_FILE   | No       | Log level written to the log file                      | INFO     |
| LOG_LEVEL_STDOUT | No       | Log level written to stdout                            | INFO     |

If all goes well, you should see logs like the following:

```shell
[2025-03-05 04:39:38] [INFO   ] lib.bot: We have logged in as <your bot name shows up here>
[2025-03-05 04:39:39] [INFO   ] uvicorn.access: GET /healthcheck HTTP/1.1 200 OK
```

### Available tags

Each image will be published with 4 tags: `latest`, the major version, the
minor version, and the patch version. For example, for a version of 1.3.12,
the tags would be:

- `latest`
- `v1`
- `v1.3`
- `v1.3.12`

This gives you flexibility in how discrete you want to be in choosing the
version of the bot that you run. I strongly discourage using `latest`. You
never know what might get written over that tag, and the next time you restart
your container there would be a decent chance of pulling a broken or
unexpected image.

### Docker

Make your own copy of the `sample.env` for yourself with your bot token.
The `.env` file is `.gitignore`'d to keep any tokens out of Git.

```shell
docker run --name bot \
    --env-file .env \
    -p 8080:8080 \
    -dit \
    ghcr.io/cyberops7/discord_bot:"${TAG}"
```

### Docker Compose

The Compose file is set up to read the environment variables from a `.env`
file (to keep the bot token out of Git). A copy of the main `sample.env` file
is symlinked in the `docker/` directory.  Make your own `.env` file and
customize it all to your liking.

```shell
docker compose -f docker/docker-compose.yaml up -d
```

### Kubernetes

A sample manifest is provided in [kubernetes/](kubernetes/).
There are a few things that you'll need to customize:

- How you create your Kubernetes Secret for the bot token. The sample manifest
  leverages a 1Password operator to create a Secret directly from a 1Password
  vault.
- The storageClass of the PersistentVolumeClaim

I am using a `.gitignore`'d Kustomize manifest to add my correct 1Password
vault path. A sample Kustomize manifest is included if you are curious about
that.

The namespace also includes a `projectId` annotation unique to my Rancher
instance to put the namespace into a project automatically.  Update it for
yours, or just remove it.

To test the manifest generation using Kustomize:

```shell
kubectl kustomize kubernetes/
```

To apply the manifest with Kustomize:

```shell
kubectl apply -k kubernetes/
```

## Contributing

For details on contributing to the project, see [CONTRIBUTING](.github/CONTRIBUTING.md).

## ToDos

To see planned features and improvements, check out [TODO](.github/TODO.md).

Please submit Issues here in GitHub to track suggestions/bug fixes, etc.
Once the initial backlog of ToDos are wrapped up, I plan to deprecate TODO.md
and work off of GitHub Issues.
