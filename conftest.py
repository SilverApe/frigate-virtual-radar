"""Test fixtures: real Home Assistant via pytest-homeassistant-custom-component (GitHub Actions)."""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/frigate_virtual_radar."""
    yield
