from langchain_openai import ChatOpenAI
from LangCode.shared.config import *
# 实例化 MiMo 模型
llm = ChatOpenAI(
    model=LC_MODEL_NAME,
    api_key=LC_API_KEY,  
    base_url=LC_BASE_URL,
    temperature=0,  # 温度参数，控制随机性
)

