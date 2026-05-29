"""App Manifest Parser
=====================
Reads and validates manifest.yaml from app package folders.

A manifest declares everything the platform needs to know about an app:
its metadata, entity types, event subscriptions, tool category, UI entries,
job types, and thinking domain configuration.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("platform.manifest")


@dataclass
class EntityTypeDef:
    """An entity type declared by an app."""
    prefix: str
    name: str
    id_format: str
    table: str


@dataclass
class ToolCategoryDef:
    """Tool routing category declared by an app."""
    description: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class UIAppDef:
    """A UI app registration declared by an app."""
    id: str = ""
    name: str = ""
    icon: str = ""
    component: str = ""
    singleton: bool = True
    hidden: bool = False


@dataclass
class JobTypeDef:
    """A job type declared by an app."""
    type: str = ""
    handler: str = ""        # e.g. "handlers.handle_import"
    max_concurrent: int = 1
    cancel_on_shutdown: bool = True


@dataclass
class ThinkingDef:
    """Thinking domain declared by an app."""
    domain: str = ""
    description: str = ""
    schedule: str = ""       # cron expression
    prompt_file: str = ""    # relative to app folder
    tools: list[str] = field(default_factory=list)
    model: str = "smart"     # 'smart' or 'dumb'


@dataclass
class ConfigKeyDef:
    """One key from an app's manifest ``config:`` schema.

    Surfaced by the Settings app so it can render schema-driven
    inputs for every installed app without each app having to ship
    its own settings UI.

    The ``type`` is a hint to the UI — string / integer / boolean.
    Unknown types fall back to a free-text input.
    """
    key: str
    type: str = "string"
    default: object = None
    label: str = ""
    description: str = ""
    # Optional UI hints. Apps may declare ``secret: true`` for keys
    # whose value should be masked in the UI (API keys, paths to
    # credential files, etc.). The value is still stored / returned
    # in plaintext by the config layer — masking is presentation only.
    secret: bool = False
    # Optional ``choices: [a, b, c]`` turns the input into a select.
    choices: list[object] = field(default_factory=list)


@dataclass
class AppManifest:
    """Parsed app manifest with all declarations."""
    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    app_dir: Path = field(default_factory=Path)

    entity_types: list[EntityTypeDef] = field(default_factory=list)
    platform_deps: list[str] = field(default_factory=list)
    emits: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)

    schema: str = ""  # "public" = tables in public schema, skip app_<id> creation
    tool_category: ToolCategoryDef | None = None
    ui: list[UIAppDef] = field(default_factory=list)
    job_types: list[JobTypeDef] = field(default_factory=list)
    # Apps may declare zero, one, or many thinking domains. Single-domain
    # manifests can use a dict; multi-domain manifests use a list. Both
    # parse into the `thinking` list below. The legacy single-domain
    # accessor is preserved via the `thinking_first` property for back-compat.
    thinking: list[ThinkingDef] = field(default_factory=list)
    # Per-app config schema. Each entry becomes a key under
    # ``scope='app:<id>'`` in ``public.app_config`` and a schema-driven
    # input in the Settings app's panel for this app.
    config: list[ConfigKeyDef] = field(default_factory=list)

    # Computed
    has_tools: bool = False
    has_routes: bool = False
    has_guide: bool = False
    has_migrations: bool = False
    has_handlers: bool = False
    has_ui: bool = False


def parse_manifest(app_dir: Path) -> AppManifest:
    """Parse manifest.yaml from an app directory.

    Args:
        app_dir: Path to the app folder (e.g., apps/recipes/)

    Returns:
        AppManifest dataclass

    Raises:
        FileNotFoundError: if manifest.yaml is missing
        ValueError: if required fields are missing
    """
    manifest_path = app_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.yaml in {app_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Required fields
    app_id = raw.get("id")
    if not app_id:
        raise ValueError(f"manifest.yaml in {app_dir} missing required 'id' field")

    name = raw.get("name", app_id)

    manifest = AppManifest(
        id=app_id,
        name=name,
        version=raw.get("version", "0.0.0"),
        description=raw.get("description", ""),
        app_dir=app_dir,
        platform_deps=raw.get("platform_deps", []),
        emits=raw.get("emits", []),
        subscribes=raw.get("subscribes", []),
        schema=raw.get("schema", ""),
    )

    # Entity types
    for et in raw.get("entity_types", []):
        manifest.entity_types.append(EntityTypeDef(
            prefix=et["prefix"],
            name=et.get("name", et["prefix"]),
            id_format=et.get("id_format", f"{et['prefix']}-"),
            table=et.get("table", ""),
        ))

    # Tool category
    tc = raw.get("tool_category")
    if tc:
        manifest.tool_category = ToolCategoryDef(
            description=tc.get("description", ""),
            keywords=tc.get("keywords", []),
        )

    # UI apps
    ui_section = raw.get("ui", {})
    for app_def in ui_section.get("apps", []):
        manifest.ui.append(UIAppDef(
            id=app_def.get("id", ""),
            name=app_def.get("name", ""),
            icon=app_def.get("icon", ""),
            component=app_def.get("component", ""),
            singleton=app_def.get("singleton", True),
            hidden=app_def.get("hidden", False),
        ))

    # Job types
    for jt in raw.get("job_types", []):
        manifest.job_types.append(JobTypeDef(
            type=jt.get("type", ""),
            handler=jt.get("handler", ""),
            max_concurrent=jt.get("max_concurrent", 1),
            cancel_on_shutdown=jt.get("cancel_on_shutdown", True),
        ))

    # Thinking domain(s) — accept either a single dict or a list of dicts.
    thinking = raw.get("thinking")
    if thinking:
        thinking_list = thinking if isinstance(thinking, list) else [thinking]
        for td in thinking_list:
            if not isinstance(td, dict):
                continue
            manifest.thinking.append(ThinkingDef(
                domain=td.get("domain", ""),
                description=td.get("description", ""),
                schedule=td.get("schedule", ""),
                prompt_file=td.get("prompt_file", ""),
                tools=td.get("tools", []),
                model=td.get("model", "smart"),
            ))

    # Per-app config schema
    for ck in raw.get("config", []) or []:
        if not isinstance(ck, dict) or not ck.get("key"):
            continue
        manifest.config.append(ConfigKeyDef(
            key=ck["key"],
            type=ck.get("type", "string"),
            default=ck.get("default"),
            label=ck.get("label", ""),
            description=ck.get("description", ""),
            secret=bool(ck.get("secret", False)),
            choices=ck.get("choices") or [],
        ))

    # Detect which optional files exist
    manifest.has_tools = (app_dir / "tools.py").exists()
    manifest.has_routes = (app_dir / "routes.py").exists()
    manifest.has_guide = (app_dir / "guide.md").exists()
    manifest.has_migrations = (app_dir / "migrations").is_dir()
    manifest.has_handlers = (app_dir / "handlers.py").exists()
    manifest.has_ui = (app_dir / "ui").is_dir()

    return manifest


def discover_apps(apps_dir: Path) -> list[AppManifest]:
    """Scan apps/ directory and parse all valid manifests.

    Invalid manifests are logged as warnings and skipped.
    """
    if not apps_dir.is_dir():
        logger.info("APP LOADER: No apps/ directory found — skipping app discovery")
        return []

    manifests = []
    for child in sorted(apps_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.yaml"
        if not manifest_path.exists():
            continue
        try:
            manifest = parse_manifest(child)
            manifests.append(manifest)
            logger.info("APP LOADER: Discovered app '%s' v%s in %s",
                        manifest.id, manifest.version, child.name)
        except Exception as e:
            logger.warning("APP LOADER: Skipping %s — %s", child.name, e)

    return manifests
