from langchain_openai import ChatOpenAI
from LangCode.shared.config import LC_MODEL_NAME, LC_API_KEY, LC_BASE_URL
from LangCode.shared.logger import get_logger

log = get_logger("llm")

# 实例化 MiMo 模型
llm = ChatOpenAI(
    model=LC_MODEL_NAME,
    api_key=LC_API_KEY,
    base_url=LC_BASE_URL,
    temperature=0,  # 温度参数，控制随机性
)
log.info("LLM 初始化完成: model=%s base_url=%s", LC_MODEL_NAME, LC_BASE_URL)

