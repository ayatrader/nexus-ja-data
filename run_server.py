"""cwd を指定できないMCPクライアント用の起動ファイル: python C:\\...\\run_server.py"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from nexus_ja.server import main  # noqa: E402

if __name__ == "__main__":
    main()
