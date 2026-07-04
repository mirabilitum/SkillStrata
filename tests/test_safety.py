"""Safety 静态扫描单元测试（阶段 3 同步落地）。"""
from pathlib import Path
from distiller import safety


class TestScanSource:
    def test_detects_file_deletion(self):
        risks = safety.scan_source("os.remove(tmp_path)")
        assert "file_deletion" in risks

    def test_detects_rmtree(self):
        risks = safety.scan_source("shutil.rmtree('/tmp/x')")
        assert "file_deletion" in risks

    def test_detects_shell_exec(self):
        risks = safety.scan_source("subprocess.run(['ls'], shell=True)")
        assert "shell_exec" in risks

    def test_detects_secret_access(self):
        risks = safety.scan_source("os.environ['ANTHROPIC_API_KEY']")
        assert "secret_access" in risks

    def test_multiple_risks(self):
        risks = safety.scan_source(
            "os.remove('x')\nsubprocess.run('rm -rf /', shell=True)"
        )
        assert risks >= {"file_deletion", "shell_exec"}

    def test_safe_script(self):
        risks = safety.scan_source(
            "import csv, json\n"
            "with open('in.csv') as f: rows = list(csv.reader(f))\n"
            "with open('out.json', 'w') as f: json.dump(rows, f)\n"
        )
        assert risks == set()


class TestAssess:
    def test_dangerous(self):
        assert safety.assess({"file_deletion"}) == "dangerous"
        assert safety.assess({"shell_exec"}) == "dangerous"
        assert safety.assess({"git_modification"}) == "dangerous"

    def test_review(self):
        assert safety.assess({"secret_access"}) == "review"
        assert safety.assess({"write_outside_workspace"}) == "review"

    def test_dangerous_trumps_review(self):
        assert safety.assess({"file_deletion", "secret_access"}) == "dangerous"

    def test_safe(self):
        assert safety.assess(set()) == "safe"


class TestScanAndAssess:
    def test_dangerous_script(self):
        v, r = safety.scan_and_assess("os.remove('x')")
        assert v == "dangerous"
        assert "file_deletion" in r

    def test_safe_script(self):
        v, r = safety.scan_and_assess("print('hello')")
        assert v == "safe"
        assert r == set()


class TestAuditFileChanges:
    def test_safe_empty_changes(self):
        v, r = safety.audit_file_changes([])
        assert v == "safe"

    def test_detects_input_overwrite(self):
        v, r = safety.audit_file_changes(
            [{"path": "/work/input.html", "action": "modify"}],
            cwd="/work",
            input_paths={"/work/input.html"},
        )
        assert v in ("dangerous", "review")  # overwrite_input → review after removing from assess
        assert "overwrite_input" in r

    def test_detects_write_outside_workspace(self):
        v, r = safety.audit_file_changes(
            [{"path": "/home/user/secret.txt", "action": "write"}],
            cwd="/work",
        )
        assert v == "review"
        assert "write_outside_workspace" in r

    def test_detects_file_deletion(self):
        v, r = safety.audit_file_changes(
            [{"path": "/work/output.tmp", "action": "delete"}],
        )
        assert v == "dangerous"
        assert "file_deletion" in r

    def test_safe_write_in_cwd(self):
        v, r = safety.audit_file_changes(
            [{"path": "/work/output.md", "action": "write"}],
            cwd="/work",
        )
        assert v == "safe"

    def test_safe_temp_write(self):
        import tempfile
        v, r = safety.audit_file_changes(
            [{"path": str(Path(tempfile.gettempdir()) / "distiller-replay-sandbox" / "out.json"),
              "action": "write"}],
            cwd="/work",
        )
        assert v == "safe"
