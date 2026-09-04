# Docker labels

With a Docker integration, nexdeck suggests tiles for running containers
(Settings of a board > Edit > Add widget > App tile, or the setup wizard).
Labels on a container fill the suggestion in; without labels, nexdeck
guesses from the image name and the first published port.

```yaml
services:
  radarr:
    image: lscr.io/linuxserver/radarr
    labels:
      nexdeck.name: Radarr
      nexdeck.url: https://radarr.example.com
      nexdeck.icon: radarr
      nexdeck.group: Media
      nexdeck.description: Movies
```

| Label | Meaning |
|---|---|
| `nexdeck.name` | Title of the tile. |
| `nexdeck.url` | Where the tile leads; also the address of the reachability check. |
| `nexdeck.icon` | A dashboard-icons or selfh.st name, `lucide:name`, or an image URL. |
| `nexdeck.group` | A section name, used when the suggestion is placed. |
| `nexdeck.description` | Small text under the title. |

## Homepage labels

The `homepage.*` labels (`homepage.name`, `homepage.href`, `homepage.icon`,
`homepage.group`, `homepage.description`) are read as well, so a stack that
was labelled for Homepage shows the same tiles here without changes. When
both are present, `nexdeck.*` wins.

Service widgets (queues, streams, containers) are not created from labels;
they need an integration with credentials, which labels should not carry.
