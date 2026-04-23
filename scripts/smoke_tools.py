from __future__ import annotations

from t212ai.genai.tools import CHAT_TOOLBOX, build_tool_mapping


def main() -> None:
    mapping = build_tool_mapping()
    print(f"toolbox={CHAT_TOOLBOX.name}")
    print("tools=" + ",".join(sorted(CHAT_TOOLBOX.tools_by_name)))
    print("mapping=" + ",".join(sorted(mapping)))


if __name__ == "__main__":
    main()

