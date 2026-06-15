# 🧮 命令行计算器

一个简单但结构完整的 Python 命令行计算器项目。

## 功能

- 支持四则运算：加 `+`、减 `-`、乘 `*`、除 `/`
- 命令行界面
- 完整的单元测试

## 使用方法

```bash
python -m calculator.main <数字1> <运算符> <数字2>
```

### 示例

```bash
python -m calculator.main 10 + 5
# 输出: 10.0 + 5.0 = 15.0

python -m calculator.main 20 / 4
# 输出: 20.0 / 4.0 = 5.0
```

## 项目结构

```
.
├── calculator/
│   ├── __init__.py      # 包初始化
│   ├── calc.py          # 核心计算逻辑
│   └── main.py          # 命令行入口
├── tests/
│   ├── __init__.py
│   └── test_calc.py     # 单元测试
├── requirements.txt     # 依赖文件
└── README.md            # 项目说明
```

## 运行测试

```bash
pip install pytest
pytest tests/ -v
```

## 许可证

MIT
