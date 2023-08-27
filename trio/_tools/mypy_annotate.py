"""Translates Mypy's output into GitHub's error/warning annotation syntax.

See: https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions
"""
import re
import sys

# Example: 'package/filename.py:42:1:46:3: error: Type error here [code]'
report_re = re.compile(
    r"""
    ([^:]+):  # Filename (anything but ":")
    ([0-9]+):  # Line number (start)
    (?:([0-9]+):  # Optional column number
      (?:([0-9]+):([0-9]+):)?  # then also optionally, 2 more numbers for end columns
    )?
    \s*(error|warn|note):  # Kind, prefixed with space
    (.+)  # Message
    """,
    re.VERBOSE,
)

mypy_to_github = {
    "error": "error",
    "warn": "warning",
    "note": "notice",
}


def process_line(platform: str, line: str) -> str:
    if match := report_re.fullmatch(line.rstrip()):
        filename, st_line, st_col, end_line, end_col, kind, message = match.groups()
        result = [f"::{mypy_to_github[kind]} file={filename},line={st_line},"]
        if st_col is not None:
            result.append(f"col={st_col},")
            if end_line is not None and end_col is not None:
                result.append(f"endLine={end_line},endColumn={end_col},")
                message = f"({st_line}:{st_col} - {end_line}:{end_col}):{message}"
            else:
                message = f"({st_line}:{st_col}):{message}"
        else:
            message = f"{st_line}:{message}"
        result.append(f"title=Mypy-{platform}::{message}\n")
        return "".join(result)
    else:
        return line


def main(platform: str) -> None:
    """Look for error messages, and convert the format."""
    for line in sys.stdin:
        sys.stdout.write(process_line(platform, line))


if __name__ == "__main__":
    main(sys.argv[1])
