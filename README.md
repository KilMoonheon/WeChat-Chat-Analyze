# WeChat Chat Analytics

本地分析微信 PC 版聊天记录的工具集，包含**私聊统计**与**群聊成员分析**两个子项目，共享同一套解密与解析核心库。

> 仅读取本机已同步的微信数据，不上传、不修改微信原始文件。  
> 性格与话题分析为启发式推断，仅供娱乐参考，不代表心理测评结果。

## 功能概览

| 模块 | 入口 | 适用场景 |
|------|------|----------|
| **私聊分析** `private_chat/` | 与某好友/联系人的一对一聊天 | 聊天频率、消息类型、双方性格与关注话题 |
| **群聊分析** `group_chat/` | 微信群聊 | 各成员发言条数、频率、时段、内容偏好、性格与关注话题 |

### 私聊分析输出

- 总消息数、类型分布（文字/图片/语音/视频/表情等）
- 月度/日度聊天频率图表
- **双方分别**的性格倾向、语言特点、最关心的话题

### 群聊分析输出

- 成员发言排行与占比
- 月度趋势、时段热力图、内容类型构成
- **每位成员单独**的性格倾向、语言特点、最关心的话题

## 环境要求

- Windows 10/11（密钥提取与解密依赖 Windows API）
- Python 3.10+
- 微信 PC 版 4.x（Weixin.exe），已登录且聊天记录已同步到电脑

## 安装

```powershell
git clone <your-repo-url>
cd wechat-chat-analytics

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

## 快速开始

### 第一步：解密数据库

**首次使用**需手动解密（保持微信 PC 版运行）：

```powershell
python private_chat/main.py prepare
```

之后运行 `analyze` / `contacts` / `groups` 时会**自动检测**微信源库是否有更新，有则自动重新解密，无需每次手动 `prepare`。

解密结果保存在 `.wechat_stats/decrypted/`（已在 `.gitignore` 中排除，不会误提交）。

> 若密钥提取失败，请以**管理员身份**运行终端后重试。  
> 若分析结果缺少今日消息，请先在**微信 PC 端打开该聊天**让手机消息同步到电脑，再重新运行分析。

### 第二步：私聊分析

```powershell
# 列出联系人
python private_chat/main.py contacts
python private_chat/main.py contacts --search 张三

# 分析指定联系人（默认自动同步最新微信数据）
python private_chat/main.py analyze "联系人备注或昵称"

# 跳过同步，直接使用本地缓存
python private_chat/main.py analyze "联系人" --no-sync
```

输出目录：`output/private/<联系人名>/`

### 第三步：群聊分析

```powershell
# 列出群聊
python group_chat/main.py groups
python group_chat/main.py groups --search 群名关键词

# 分析指定群聊
python group_chat/main.py analyze "群名称"
python group_chat/main.py analyze "群名" --top 20 --json

# 跳过自动同步
python group_chat/main.py analyze "群名" --no-sync
```

输出目录：`output/group/<群名>/`

## 项目结构

```
wechat-chat-analytics/
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
├── wechat_stats/              # 共享核心库
│   ├── wcdb.py                # 微信 4.x 数据库解密
│   ├── decrypt.py             # 解密封装
│   ├── reader.py              # 联系人 / 消息读取
│   ├── personality.py         # 性格 · 语言 · 关注话题分析
│   ├── types.py
│   └── config.py
├── private_chat/              # 私聊分析
│   ├── main.py
│   ├── cli.py
│   ├── stats.py
│   └── charts.py
└── group_chat/                # 群聊分析
    ├── main.py
    └── group_stats/
        ├── cli.py
        ├── reader.py
        ├── analyze.py
        └── charts.py
```

## 输出文件说明

### 私聊 `output/private/<联系人>/`

| 文件 | 说明 |
|------|------|
| `*_类型分布.png` | 消息类型占比 |
| `*_月度频率.png` | 每月聊天量趋势 |
| `*_近期日频率.png` | 最近 90 天日聊天量 |
| `*_时段分布.png` / `*_星期分布.png` | 时间分布 |
| `*_聊天频次热力图.png` | 全量日频次日历热力图 + 星期×小时分布 |
| `*_收发比例.png` | 我 vs 对方发送比例 |
| `*_统计报告.txt` | 文字统计摘要 |
| `*_性格与关注分析.txt` | 双方性格、语言特点、关注话题 |

### 群聊 `output/group/<群名>/`

| 文件 | 说明 |
|------|------|
| `*_成员分析报告.txt` | 成员排行 + 内容偏好 + 性格分析 |
| `*_成员发言排行.png` 等 | 各类统计图表 |
| `*_聊天频次热力图.png` | 全量日频次日历热力图 + 星期×小时分布 |
| `*_性格与关注分析.txt` | 各成员性格与关注话题专报 |
| `members.json` | 可选（`--json`）结构化数据 |

## 原理简述

微信 4.x 将聊天记录加密存储在：

```
%USERPROFILE%\Documents\xwechat_files\<账号>\db_storage\
```

本工具从微信进程内存提取 WCDB 密钥（参考 [wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool) 思路），解密 SQLite 数据库后统计 `message_*.db` 中的消息元数据与文本内容。

## 从旧版独立项目迁移

若你之前使用过 `聊天记录阅读` 或 `群聊成员分析` 两个独立文件夹，可按以下方式迁移：

1. 克隆或复制本仓库 `wechat-chat-analytics/` 到新位置
2. 将旧项目中的 `.wechat_stats/` 文件夹**整份复制**到本仓库根目录（含 `keys.json` 与 `decrypted/`，**不要提交到 Git**）
3. 或在本仓库重新执行 `python private_chat/main.py prepare`（需微信运行）

旧项目的 `output/` 分析结果无需迁移，重新运行 `analyze` 即可生成。

## 注意事项

1. 手机聊天记录需先同步到 PC 端微信
2. `.wechat_stats/` 含密钥与解密数据，**切勿提交到 Git 或公开分享**
3. `output/` 含个人聊天记录分析结果，默认已 gitignore
4. 微信版本更新可能导致解密失效，需等待适配
5. 仅供个人备份与分析，请勿用于非法用途

## License

MIT — 见 [LICENSE](LICENSE)
