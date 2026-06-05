import os

LC_MODEL_NAME = os.getenv("LC_MODEL_NAME", "mimo-v2.5-pro")  # 从环境变量获取模型名称，默认为 "mimo-v2.5-pro"
LC_API_KEY = os.getenv("LC_API_KEY")  # 从环境变量获取
LC_BASE_URL = os.getenv("LC_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")  # 从环境变量获取基础URL，默认为 MiMo 的官方URL

LC_TEMPERATURE = 0  # 温度参数，控制随机性