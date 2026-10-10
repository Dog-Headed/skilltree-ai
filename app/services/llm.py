import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def get_llm():
    config = {
        name: os.getenv(name, "").strip()
        for name in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL")
    }
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError(
            f"缺少模型配置：{', '.join(missing)}。请在 {ENV_PATH} 中填写对应的环境变量。"
        )

    return ChatOpenAI(
        model=config["LLM_MODEL"],
        api_key=config["LLM_API_KEY"],
        base_url=config["LLM_BASE_URL"],
        temperature=0,
    )
