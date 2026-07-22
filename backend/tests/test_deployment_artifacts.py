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


def test_backend_deploy_only_runs_for_production_inputs():
    workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()

    for path in (
        ".github/workflows/deploy-backend.yml",
        "backend/**",
        "deploy/**",
        "docker-compose.production.yml",
        "infra/aws/**",
    ):
        assert f"- {path}" in workflow

    assert "frontend/**" not in workflow


def test_backend_deploy_is_serialized_bounded_and_observable():
    workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()

    assert "group: finora-production-backend" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "--timeout-seconds 60" in workflow
    assert 'executionTimeout: ["600"]' in workflow
    assert 'echo "SSM command ID: $COMMAND_ID"' in workflow
    assert "StatusDetails:StatusDetails" in workflow
    assert "aws ssm cancel-command" in workflow
