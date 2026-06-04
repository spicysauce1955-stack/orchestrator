def test_package_imports_and_has_version():
    import orchestrator

    assert isinstance(orchestrator.__version__, str)
    assert orchestrator.__version__
