# SPDX-License-Identifier: GPL-3.0-only
"""Luminaire Edit Studio. Uses the host's Torch, Pillow and native Comfy nodes."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
