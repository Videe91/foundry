def test_foundry_package_imports() -> None:
    import foundry

    assert foundry.__version__ == "0.1.0"
