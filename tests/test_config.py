from rag import config


def test_paths_resolve_against_repo_root():
    assert (config.ROOT_DIR / "pyproject.toml").exists()
    assert config.WORKER_DB_PATH.is_absolute()
    assert config.WORKER_DB_PATH.parent == config.ROOT_DIR / "data"


def test_readme_limit_has_default():
    assert config.README_MAX_BYTES > 0
