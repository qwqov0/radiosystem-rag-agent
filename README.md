# RadioSystem RAG Agent

本地大模型、私有项目知识问答与任务驱动战棋 Agent 的课程项目。系统使用 LangChain、FAISS 和 BGE 检索项目资料；通过分阵营战场记忆检索历史观察，由本地模型比较对手目的并选择行动，C++ 引擎结算移动、地形、兵种、夹击、士气与任务结果。

## 功能

- 公开出口突破、隐藏 A/B 出口、坚守后撤三类非对称任务。
- 步兵、轻步兵、坦克和炮兵；森林、城镇、开阔地和高地。
- 各方独立观察与历史记录，目击、移动、失联和任务进度检索。
- 证据引用、竞争假设、联合提案、异步执行与回放。
- 私有源码问答、键值位置实验与可追溯实验记录。

## 构建和运行

需要 Python 3.12、CMake 及 C++17 编译器。Windows 可使用 MinGW 或 Visual Studio；运行时应将编译器动态库目录加入 PATH。以下命令从仓库根目录执行：

```sh
python -m venv .venv
# 激活虚拟环境后执行
python -m pip install -r requirements.txt
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --config Release
cd app
python launch_battle.py
```

打开 http://127.0.0.1:18083/ 。规则基线和人工指挥无需大模型。Visual Studio 多配置构建可设置 RADIOSYSTEM_BATTLE_ENGINE 和 RADIOSYSTEM_ENGINE 指向 Release 目录中的对应程序。

## 本地模型与知识问答

下载官方 [llama.cpp](https://github.com/ggml-org/llama.cpp) 和 [Qwen2.5 GGUF](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF) 权重。在 app 目录运行：

```sh
python configure_model.py
python generate_local_corpus.py
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 18082 --ctx-size 32768 --parallel 1 --n-gpu-layers 99 --alias qwen2.5-7b-instruct-q4_k_m --api-key-file runtime/local_api_key.txt
```

在战场控制器中选择“历史检索 Agent”。建议每拍 2 秒。两个 Agent 共用模型服务时会排队，返回命令由引擎检查时效。项目知识问答使用战场右上入口 /knowledge；先运行 generate_local_corpus.py 从当前公开源码生成本地语料，第一次检索会下载 BGE 嵌入模型并建立本地 FAISS 索引。可用 --source 指向自己的文本资料目录。独立问答页面通过 `python launch_api.py` 在 18081 端口启动。

## 验证

在 app 目录执行：

```sh
python -m unittest test_battle_v3 test_battle_service test_commander_v4 test_missions_v5 test_mission_api test_guards test_grounding test_engine_adapter -v
node test_mission_ui.cjs
python run_mission_validation.py --tag local_check
python run_mission_validation.py --model --tag local_model
```

原实验环境记录在 environment-original.txt。源码发布副本将本机绝对路径改为仓库相对路径。当前代码通过 123 项自动检查及任务界面测试。

## 论文实验

`app/paper_gpu_experiment.py` 使用 [Lost in the Middle 作者代码与数据](https://github.com/nelson-liu/lost-in-the-middle) 的键值任务。配置好本地模型后，从仓库根目录执行：

```sh
git clone https://github.com/nelson-liu/lost-in-the-middle.git app/paper/author_code
cd app
python paper_gpu_experiment.py
```

数据按作者仓库说明下载到 kv_retrieval_data。脚本在本地 results/paper_gpu 下生成协议与输出。本仓库仅发布代码和运行说明，课程使用的知识库资料、源码快照、评测题库与历史实验记录由作者本地保存。

## 目录

| 目录 | 内容 |
|---|---|
| engine | C++ 权威引擎及 nlohmann JSON 头文件 |
| app | 服务、Agent、前端、评测脚本与测试 |
| app/generate_local_corpus.py | 从当前源码或自有文本生成本地检索语料 |

知识库资料、历史实验记录、模型权重、推理二进制、个人密钥、运行缓存和学生报告不随仓库发布。第三方项目保留原许可：nlohmann/json 为 MIT，Lost in the Middle 作者代码为 MIT；模型许可见各官方下载页面。
