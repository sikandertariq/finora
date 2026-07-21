from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_compose_keeps_database_and_cache_private():
    compose = (ROOT / "docker-compose.production.yml").read_text()
    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose


def test_cloudformation_avoids_ssh_and_paid_managed_data_services():
    template = (ROOT / "infra/aws/finora.yaml").read_text()
    assert "FromPort: 22" not in template
    assert "AWS::RDS::DBInstance" not in template
    assert "AWS::ElastiCache::" not in template
    assert "InstanceType: t3.micro" in template
