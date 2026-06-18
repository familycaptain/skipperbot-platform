"""Weather App — Platform Hooks
================================
Registers the weather cache-refresh loop as a platform background task, so the
platform core never imports ``apps.weather`` directly (see the lifecycle-hooks
loader mechanism, #11).

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register the weather background cache-refresh loop with the platform."""
    from app_platform.lifecycle import register_background_task
    # App importing its own module — allowed (the rule is platform-must-not-import-apps).
    from apps.weather.background import start_weather_cache_loop

    # Pass the function itself (zero-arg factory), NOT start_weather_cache_loop().
    register_background_task("weather_cache_refresh", start_weather_cache_loop)
