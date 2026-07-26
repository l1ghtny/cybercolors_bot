from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_indexer_image_copies_complete_ai_module_tree():
    dockerfile = (ROOT / "docker" / "Dockerfile.indexer").read_text()

    assert "COPY src/modules/ai ./src/modules/ai" in dockerfile
    assert "scripts/run_youtube_channel_worker.py" in dockerfile


def test_teamcity_indexer_hash_covers_every_copied_worker_source():
    pipeline = (ROOT / ".teamcity.cybercolors.yml").read_text()

    assert pipeline.count("scripts/run_youtube_channel_worker.py") == 2
    assert pipeline.count("              src/modules/ai \\") == 2
