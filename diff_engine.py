import difflib


def generate_diff(original_code: str, refactored_code: str):
    original_lines = original_code.splitlines()
    refactored_lines = refactored_code.splitlines()

    unified_diff = difflib.unified_diff(
        original_lines,
        refactored_lines,
        fromfile="original",
        tofile="refactored",
        lineterm="",
    )

    structured_diff = []

    for line in unified_diff:
        if line.startswith("---") or line.startswith("+++"):
            continue

        if line.startswith("@@"):
            continue

        if line.startswith("-"):
            structured_diff.append(
                {
                    "type": "removed",
                    "line": line[1:],
                }
            )

        elif line.startswith("+"):
            structured_diff.append(
                {
                    "type": "added",
                    "line": line[1:],
                }
            )

    return structured_diff