from hound_agent.ingest.git import correlated_commit_subjects, gather


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


def test_correlated_commit_subjects_only_include_changed_frame_files(fake_repo):
    repo, path = fake_repo
    cart = path / "app" / "cart.py"
    cart.write_text("class Cart:\n    total = 10.0\n", encoding="utf-8")
    repo.index.add(["app/cart.py"])
    repo.index.commit("fix: correct cart total")
    # The CI workspace has a new uncommitted change; its most recent committed
    # subject is useful context for the matching stack frame.
    cart.write_text("class Cart:\n    total = 11.0\n", encoding="utf-8")

    info = gather(str(path))
    subjects = correlated_commit_subjects(str(path), ["app/cart.py"], info.changed_files)

    assert len(subjects) == 1
    assert subjects[0].startswith("app/cart.py (")
    assert "fix: correct cart total" in subjects[0]
    assert correlated_commit_subjects(str(path), ["app/other.py"], info.changed_files) == []


def test_correlated_commit_subjects_reject_outside_repo_paths(fake_repo, monkeypatch):
    _, path = fake_repo
    calls = []

    def record(*args):
        calls.append(args)
        return ""

    monkeypatch.setattr("hound_agent.ingest.git._run", record)
    assert correlated_commit_subjects(str(path), ["../outside.py"], ["../outside.py"]) == []
    assert calls == []


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
