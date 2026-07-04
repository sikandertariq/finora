def test_celery_app_configured():
    from config.celery import app
    assert app.main == "finora"
    assert "redis" in app.conf.broker_url
