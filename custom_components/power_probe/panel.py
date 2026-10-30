"""The Power Probe sidebar panel: one static JavaScript module."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PANEL_ELEMENT, PANEL_URL_PATH, STATIC_URL, VERSION

FRONTEND_DIR = Path(__file__).parent / "frontend"
MODULE_FILE = "power-probe-panel.js"
_STATIC_KEY = f"{DOMAIN}_static_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel's script and add it to the sidebar, admins only.

    The panel can switch devices, so it is hidden from non-admin users.
    """
    if not hass.data.get(_STATIC_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), False)]
        )
        hass.data[_STATIC_KEY] = True
    # A reload registers again; the old entry is removed on unload, but a
    # crashed unload must not stop the panel from coming back.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="Power Probe",
        sidebar_icon="mdi:flash",
        module_url=f"{STATIC_URL}/{MODULE_FILE}?v={VERSION}",
        require_admin=True,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Take the panel out of the sidebar."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
