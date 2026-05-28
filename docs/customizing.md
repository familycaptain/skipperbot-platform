# Customizing Skipperbot

> **Placeholder** — the full customization guide ships with Chunk 2+.

## Replacing a required app with your own fork

Required apps (those with `core: true` in their manifest) cannot be
uninstalled through normal means. The platform refuses to boot if one is
missing.

To replace one with your own version:

1. Fork the required app's source (currently lives in `apps/<id>/` inside
   this repo).
2. Delete the original folder.
3. Drop your fork's folder into `apps/<id>/` with the same `id` in its
   manifest.
4. Restart.

The loader doesn't care that the folder came from a different source — as
long as the manifest declares the right `id` and `core: true`, the
contract is satisfied.

## Writing your own optional app

See [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md). To scaffold:

```bash
python scripts/new_app.py my-app-name
```

This creates `../skipperbot-app-my-app-name/` with the standard skeleton.

## Disabling a built-in feature

Most platform-level features are gated by configuration in `app_config`.
Open the Settings app and adjust the platform section.

## More to come

Chunk 2+ fills in the full customization guide.
