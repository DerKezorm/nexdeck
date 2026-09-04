# Boards as files

Every board can be exported as YAML (board menu > File > Export) and
imported again, on the same or another installation. Secrets never leave:
integration secrets are written as `${ENVIRONMENT_VARIABLE}` references.

## The file

```yaml
nexdeck: 1
board:
  name: Media
  slug: media
  icon: layout-dashboard
  background: { kind: bundled, value: aurora }
pages:
  - name: Overview
    slug: overview
    widgets:
      - kind: radarr.queue
        title: Radarr queue
        icon: radarr
        integration: Movies
        options: { limit: 8 }
        layout:
          lg: { x: 0, y: 0, w: 4, h: 3 }
          md: { x: 0, y: 0, w: 4, h: 3 }
          sm: { x: 0, y: 0, w: 4, h: 3 }
      - kind: core.app
        title: Radarr
        icon: radarr
        link: https://radarr.example.com
        options: { description: Movies, check: true }
integrations:
  - name: Movies
    kind: radarr
    config:
      url: http://radarr:7878
      api_key: ${NEXDECK_RADARR_1_API_KEY}
```

Widgets reference integrations by **name**. On import, an integration with
that name and kind is reused; otherwise it is created from the `config`
block, with `${VARIABLE}` values taken from the environment. A widget
without `layout` is placed at the bottom of every screen size.

## Provisioning

Files in `data/boards/*.yaml` become boards on their own:

- They are loaded at start and re-read whenever the file changes (checked every ten seconds).
- They are marked as *from a file* in the interface and cannot be edited there; the file is the source.
- When the file disappears, the board goes with it.
- Secrets belong in environment variables, referenced from the file.

This is the way to keep boards in Git or to roll out the same board to
several installations.
