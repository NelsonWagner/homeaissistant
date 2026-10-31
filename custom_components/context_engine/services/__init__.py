"""Register intent service handlers."""

from .add_intent import async_register_add_intent
from .remove_intent import async_register_remove_intent
from .refresh_profile import async_register_refresh_profile
from .set_posture import async_register_set_posture

__all__ = [
    "async_register_add_intent",
    "async_register_remove_intent",
    "async_register_refresh_profile",
    "async_register_set_posture",
]
