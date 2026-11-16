# NexDeck Self-Update Agent

The NexDeck self-update feature uses a separate, authenticated
host-side agent to manage Docker Compose updates.

The NexDeck application container does not require access to
the Docker socket.

## Update workflow

1. An administrator requests an update through NexDeck.
2. The agent validates the enrolled deployment.
3. A backup is created and verified.
4. A recovery package is prepared.
5. The official version-specific NexDeck image is downloaded.
6. Docker Compose recreates the application container.
7. The replacement is checked for health.
8. If an update fails after deployment changes begin, the
   agent attempts automatic rollback using verified recovery data.

Updates are restricted to official stable NexDeck releases.

## Requirements

- Linux with systemd
- Docker Engine and Docker Compose v2
- Python with support for the agent's standard-library modules
- A NexDeck Docker Compose deployment
- Administrator access for initial installation
- Access to GitHub and the official NexDeck container registry

The NexDeck backend requires Python 3.13 or newer. The standalone
agent's compatibility with older Python versions should be
validated separately.

## Deployment manifest

The agent requires an administrator-owned JSON manifest containing:

- deployment_id
- compose_file
- project_directory
- project_name
- service_name
- container_name
- data_directory

Filesystem paths must be absolute and canonical.

The manifest and its parent directories must satisfy the agent's
strict ownership and permissions checks.

## Authentication

The backend communicates with the agent through an authenticated
Unix domain socket.

Configure the backend with:

- update_agent_socket
- update_agent_token
- update_deployment_id

The deployment ID must match the enrolled manifest.

Keep the authentication token secret. Never expose it through the
frontend, commit it to Git or place it in application logs.

Do not mount the Docker socket inside the NexDeck application.

## systemd

A service template is provided at:

systemd/nexdeck-update-agent.service

The service expects installation-specific paths for the agent
code, deployment manifest, authentication token and Unix socket.

Review these paths before enabling the service.

An example deployment-specific permissions override is provided:

systemd/nexdeck-update-agent.conf.example

Replace its placeholder path with the actual deployment directory.

The agent requires write access to application data, managed
Compose overrides and recovery storage. Rollback may also require
write access to the parent of the application data directory.

Do not grant filesystem access more broadly than necessary.

The service uses restricted Linux capabilities. Because it can
communicate with the Docker daemon, it must still be treated as
a privileged host component.

## Backups and recovery

Before updating, the agent creates and verifies a backup and
prepares recovery material.

Recovery storage must be securely provisioned before updates
are enabled.

Do not manually delete recovery directories or interrupt an
unresolved recovery operation.

If automatic rollback cannot complete, investigate the retained
recovery material before attempting another update.

Maintain independent backups in addition to the updater's
automatic recovery packages.

## Verification

Before enabling updates on a production deployment:

1. Verify the manifest and authentication configuration.
2. Confirm the agent socket is accessible to the application.
3. Verify the service starts successfully.
4. Confirm Docker and GitHub connectivity.
5. Test backup and recovery against an isolated deployment.
6. Confirm the application remains healthy after updating.

The complete update and rollback workflow has been exercised
against an isolated NexDeck deployment.

The hardened systemd configuration has passed basic sandbox
access checks but still requires full end-to-end validation
before production use.

## Important limitation

The self-update feature must be present in the running NexDeck
application image.

Updating to an upstream image that does not include this feature
will remove its API and user interface until the feature is
included in that image.
