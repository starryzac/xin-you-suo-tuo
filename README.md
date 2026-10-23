# 芯有所托

退役动力电池在企业之间流转时，交接的不只是电池，还有检测依据和后续责任。这个原型把接收确认、证据争议和更正记录放到同一条交接流程里，方便参与方查清每一步由谁处理、依据是什么。

这是“理解当代中国”四新专项赛项目的程序部分，使用 Python、Streamlit、SQLAlchemy 和 SQLite，页面沿用英文界面。

## 能做什么

- 查看电池档案、当前持有方和历次交接。
- 分开记录“电池已经收到”和“接收方认可随附证据”。收到电池后，证据仍然可以处于待确认或不完整状态。
- 为证据争议指定责任机构，跟踪复核进度。
- 更正评估信息时保留原版本，记录修改内容、原因、操作人和时间，并交回接收方重新确认。
- 按发送方、接收方、复核方和监管方展示可操作的内容，保留操作日志。

## 本地运行

需要 Python 3.11 或更新版本。以下命令在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run battery_handover_demo/app.py
```

打开终端提示的本地地址。首次启动会自动建立 `battery_handover_demo/data/demo.db`，并写入虚构的电池、机构和交接示例，无需另外导入数据。侧栏可以切换演示角色。

## 代码位置

| 文件 | 内容 |
| --- | --- |
| `battery_handover_demo/app.py`、`pages/` | 概览和五个业务页面 |
| `models.py`、`database.py` | 数据结构与存储 |
| `services.py`、`rules.py`、`permissions.py` | 交接、争议、更正和权限规则 |
| `schemas.py` | 操作输入的数据结构 |
| `seed.py` | 首次运行所需的演示数据 |
| `config.py`、`ui_helpers.py` | 配置和页面共用逻辑 |

当前版本使用角色切换模拟身份，适合本地演示交接流程。它尚未接入真实企业或国家溯源平台，不能代替电池安全检测或实际合规判断。
