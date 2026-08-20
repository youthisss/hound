from hound_agent.ingest.git import gather


def test_no_repo():
    info = gather(None)
    assert info.branch is None
    assert info.head == ""
    assert info.changed_files == []


def test_gather_context(fake_repo):
    repo, path = fake_repo
    (path / "app" / "cart.py").write_text(
        "class Cart:\n    total = 5.0\n    def add(self, i): pass\n", encoding="utf-8"
    )
    (path / "new.txt").write_text("hi", encoding="utf-8")
    repo.index.add(["app/cart.py", "new.txt"])

    info = gather(str(path))
    assert info.head
    assert info.branch
    assert "app/cart.py" in info.changed_files
    assert "new.txt" in info.changed_files


def test_gather_bad_dir(tmp_path):
    info = gather(str(tmp_path / "missing"))
    assert info.changed_files == []


def test_gather_rejects_option_like_revisions(fake_repo, monkeypatch):
    _, path = fake_repo
    calls = []
    real_run = __import__("hound_agent.ingest.git", fromlist=["_run"])._run

    def record(repo, *args):
        calls.append(args)
        return real_run(repo, *args)

    monkeypatch.setattr("hound_agent.ingest.git._run", record)
    gather(str(path), base_sha="--output=owned", head_sha="--help")
    assert all("--output=owned" not in call and "--help" not in call for call in calls)
