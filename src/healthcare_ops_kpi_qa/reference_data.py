from __future__ import annotations

import yaml

from .settings import get_project_paths


def load_reference_data() -> dict:
    config_path = get_project_paths().config_dir / "reference_data.yml"
    return yaml.safe_load(config_path.read_text())
