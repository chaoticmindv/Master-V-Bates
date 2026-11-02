"""
Comprehensive test suite for Arena CLI developer tools and cookie parsing.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from arena.tools.file_tools import ReadFileTool, WriteFileTool, EditFileTool, SearchTool, LsTool
from arena.tools.shell_tools import RunCmdTool
from arena.tools import parse_tool_calls
from arena.auth import parse_cookie_input


class TestFileTools(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="arena_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_write_file_basic_and_nested(self):
        writer = WriteFileTool(self.test_dir)

        # 1. Basic write
        res = writer.execute({"path": "sample.txt", "content": "hello world\nline two"})
        self.assertIn("Successfully wrote 'sample.txt'", res)
        target = Path(self.test_dir) / "sample.txt"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "hello world\nline two")

        # 2. Nested directory creation
        res2 = writer.execute({"path": "sub/folder/nested.py", "content": "print('nested')"})
        self.assertIn("Successfully wrote 'nested.py'", res2)
        nested_target = Path(self.test_dir) / "sub" / "folder" / "nested.py"
        self.assertTrue(nested_target.exists())
        self.assertEqual(nested_target.read_text(encoding="utf-8"), "print('nested')")

    def test_read_file(self):
        reader = ReadFileTool(self.test_dir)
        writer = WriteFileTool(self.test_dir)

        writer.execute({"path": "read_test.txt", "content": "Line 1\nLine 2\nLine 3"})

        # Read existing file
        res = reader.execute({"path": "read_test.txt"})
        self.assertIn("File 'read_test.txt' (3 lines):", res)
        self.assertIn("   1 | Line 1", res)
        self.assertIn("   2 | Line 2", res)
        self.assertIn("   3 | Line 3", res)

        # Non-existent file
        err_res = reader.execute({"path": "does_not_exist.txt"})
        self.assertIn("Error: File not found", err_res)

    def test_read_file_truncation(self):
        reader = ReadFileTool(self.test_dir)
        writer = WriteFileTool(self.test_dir)

        # Create file with 350 lines
        lines = [f"Data line {i}" for i in range(350)]
        writer.execute({"path": "huge.txt", "content": "\n".join(lines)})

        res = reader.execute({"path": "huge.txt"})
        self.assertIn("lines omitted", res)
        self.assertIn("   1 | Data line 0", res)
        self.assertIn("350 | Data line 349", res)

    def test_edit_file(self):
        editor = EditFileTool(self.test_dir)
        writer = WriteFileTool(self.test_dir)

        writer.execute({
            "path": "app.py",
            "content": "def run():\n    return 'old_value'\n"
        })

        # Successful targeted edit
        res = editor.execute({
            "path": "app.py",
            "old_text": "'old_value'",
            "new_text": "'new_value'"
        })
        self.assertIn("Successfully edited 'app.py'", res)

        target = Path(self.test_dir) / "app.py"
        self.assertEqual(target.read_text(encoding="utf-8"), "def run():\n    return 'new_value'\n")

        # Error if old_text is missing
        err_res = editor.execute({
            "path": "app.py",
            "old_text": "non_existent_snippet",
            "new_text": "replacement"
        })
        self.assertIn("Error: Target text not found", err_res)

        # Error if old_text is empty
        empty_res = editor.execute({
            "path": "app.py",
            "old_text": "",
            "new_text": "test"
        })
        self.assertIn("Error: 'old_text' cannot be empty", empty_res)

    def test_ls_tool(self):
        ls = LsTool(self.test_dir)
        writer = WriteFileTool(self.test_dir)

        writer.execute({"path": "file1.txt", "content": "12345"})
        writer.execute({"path": "dir1/subfile.txt", "content": "abc"})

        res = ls.execute({"path": "."})
        self.assertIn("📁 dir1/", res)
        self.assertIn("📄 file1.txt", res)

    def test_search_tool(self):
        searcher = SearchTool(self.test_dir)
        writer = WriteFileTool(self.test_dir)

        writer.execute({"path": "module_a.py", "content": "SECRET_KEY = 'vanta_prod_token'"})
        writer.execute({"path": "module_b.py", "content": "OTHER_KEY = 'ordinary_val'"})

        res = searcher.execute({"path": ".", "pattern": "vanta_prod"})
        self.assertIn("module_a.py:1: SECRET_KEY = 'vanta_prod_token'", res)
        self.assertNotIn("module_b.py", res)

    def test_run_cmd_tool(self):
        runner = RunCmdTool(self.test_dir)

        # Successful command
        res = runner.execute({"cmd": "python -c \"print('Hello from shell')\""})
        self.assertIn("Hello from shell", res)

        # Command with error
        err_res = runner.execute({"cmd": "python -c \"import sys; sys.stderr.write('error msg'); sys.exit(2)\""})
        self.assertIn("[STDERR]", err_res)
        self.assertIn("error msg", err_res)
        self.assertIn("exited with code 2", err_res)


class TestToolParsing(unittest.TestCase):
    def test_parse_tool_calls(self):
        assistant_output = """
I will first inspect the file and then write an update.
<tool name="read_file"><path>src/index.ts</path></tool>
And then write the config:
<tool name="write_file"><path>config.json</path><content>
{
  "active": true
}
</content></tool>
Done!
"""
        calls = parse_tool_calls(assistant_output)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["params"]["path"], "src/index.ts")
        self.assertEqual(calls[1]["name"], "write_file")
        self.assertEqual(calls[1]["params"]["path"], "config.json")
        self.assertIn('"active": true', calls[1]["params"]["content"])


class TestAuthParsing(unittest.TestCase):
    def test_parse_dev_tools_tab_separated(self):
        raw_table = (
            "arena-auth-prod-v1.0\tbase64-eyJlbWFpbCI6ICJ0ZXN0QGdtYWlsLmNvbSJ9\tarena.ai\t/\t2027\t100\n"
            "_vcrr_token\tdpl_12345\tarena.ai\t/\tSession\t50\n"
        )
        hdr, c_dict, _ = parse_cookie_input(raw_table)
        self.assertIn("arena-auth-prod-v1.0", c_dict)
        self.assertIn("_vcrr_token", c_dict)
        self.assertIn("arena-auth-prod-v1.0=base64-", hdr)


if __name__ == "__main__":
    unittest.main()

