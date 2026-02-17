# 小说处理工具集

本工具集包含两个独立的Python程序，用于处理大型TXT小说文件：
1. **novel_splitter.py** - 按章节分割小说文件
2. **novel_summarizer.py** - 调用AI大模型批量总结情节

---

## 一、小说分割程序 (novel_splitter.py)

### 功能说明
- 读取大型TXT小说文件
- 识别"第X章"格式的章节标题
- 每10章分割为一个文件
- 输出到TXT文件夹

### 使用方法

1. **准备工作**
   ```bash
   # 将你的小说文件命名为 novel.txt（或修改代码中的配置）
   # 确保小说使用 UTF-8 编码
   ```

2. **修改配置**（可选）
   ```python
   # 在代码底部的 main() 函数中修改配置
   INPUT_FILE = "novel.txt"        # 输入文件名
   OUTPUT_DIR = "TXT"              # 输出文件夹
   CHAPTERS_PER_FILE = 10          # 每文件章节数
   ```

3. **运行程序**
   ```bash
   python novel_splitter.py
   ```

4. **输出结果**
   - 在工作目录下创建 `TXT` 文件夹
   - 生成 `1-10.txt`, `11-20.txt`, `21-30.txt` 等文件

### 支持的章节格式
- 阿拉伯数字：`第1章`, `第123章`
- 中文数字：`第一章`, `第一百二十三章`
- 混合格式：`第1章 标题`, `第一章 标题`

---

## 二、AI总结程序 (novel_summarizer.py)

### 功能说明
- 遍历TXT文件夹中的文本文件
- 调用大模型API生成情节摘要
- 保留关键人物、转折点和结局
- 每段摘要控制在500-1000字
- 合并所有摘要到 `总结.txt`

### 环境准备

1. **安装依赖**
   ```bash
   pip install openai
   # 如果使用Anthropic
   pip install anthropic
   ```

2. **配置API密钥**（选择一种方式）

   **方式1：环境变量（推荐）**
   ```bash
   # Linux/Mac
   export OPENAI_API_KEY="your-api-key-here"

   # Windows CMD
   set OPENAI_API_KEY=your-api-key-here

   # Windows PowerShell
   $env:OPENAI_API_KEY="your-api-key-here"
   ```

   **方式2：直接修改代码**
   ```python
   API_KEY = "your-api-key-here"  # 在代码中填写
   ```

### 使用方法

1. **修改配置**
   ```python
   # 在代码底部的 main() 函数中配置

   INPUT_DIR = "TXT"                    # 输入文件夹
   OUTPUT_FILE = "总结.txt"              # 输出文件名

   # API配置
   API_KEY = ""                         # API密钥（或设置环境变量）
   API_BASE = ""                        # API基础URL（可选）
   MODEL = "gpt-3.5-turbo"              # 模型名称
   PROVIDER = "openai"                  # 提供商

   # 总结设置
   MIN_LENGTH = 500                     # 最少字数
   MAX_LENGTH = 1000                    # 最多字数
   DELAY = 1.0                          # API调用间隔
   ```

2. **运行程序**
   ```bash
   python novel_summarizer.py
   ```

3. **输出结果**
   - 生成 `总结.txt` 文件
   - 包含所有章节的情节摘要

### 支持的API提供商

| 提供商 | 模型示例 | API_BASE |
|--------|----------|----------|
| OpenAI | gpt-3.5-turbo, gpt-4, gpt-4o | https://api.openai.com/v1 |
| 通义千问 | qwen-turbo, qwen-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| DeepSeek | deepseek-chat | https://api.deepseek.com |
| Anthropic | claude-3-opus, claude-3-sonnet | - |

---

## 三、完整工作流程示例

```bash
# 1. 准备工作目录
mkdir novel_processing
cd novel_processing

# 2. 将小说文件放入目录（确保UTF-8编码）
cp /path/to/your/novel.txt ./

# 3. 设置API密钥（用于总结程序）
export OPENAI_API_KEY="sk-xxxxxxxx"

# 4. 运行分割程序
python novel_splitter.py

# 5. 运行总结程序
python novel_summarizer.py

# 6. 查看结果
cat 总结.txt
```

---

## 四、常见问题

### Q1: 分割程序无法识别章节标题？
**A:** 确保章节标题格式为"第X章"，支持中文数字和阿拉伯数字。如果格式不同，可以修改代码中的正则表达式：
```python
chapter_pattern = r'(第[一二三四五六七八九十百千万零\d]+章[^\n]*)'
```

### Q2: 文件编码错误？
**A:** 确保小说文件使用UTF-8编码。如需转换：
```bash
# Linux/Mac
iconv -f GBK -t UTF-8 input.txt > output.txt
```

### Q3: API调用失败？
**A:** 
- 检查API密钥是否正确
- 检查网络连接
- 检查API余额是否充足
- 查看具体的错误信息

### Q4: 总结内容太长/太短？
**A:** 修改 `MIN_LENGTH` 和 `MAX_LENGTH` 参数

### Q5: API限流？
**A:** 增大 `DELAY` 参数的值，如设置为 2.0 或 3.0

---

## 五、注意事项

1. **API费用**：AI总结程序会消耗API额度，运行前请查看程序显示的成本估算
2. **内容长度**：单段文本过长时会自动截断，如需完整总结请调整 `max_input_length`
3. **备份数据**：建议先备份原始小说文件
4. **编码问题**：确保所有文件使用UTF-8编码

---

## 六、文件结构

```
工作目录/
├── novel.txt              # 原始小说文件
├── novel_splitter.py      # 分割程序
├── novel_summarizer.py    # 总结程序
├── TXT/                   # 分割后的文件
│   ├── 1-10.txt
│   ├── 11-20.txt
│   └── ...
└── 总结.txt               # 最终的总结文件
```
