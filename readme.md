# 说明

> [!NOTE]
> **📢 维护状态 / Maintenance Notice**
> 本人因今年升高一，明天（8月23日）报到。开学后几乎没有时间继续更新本项目（如果有时间，争取周日更新）。遇到问题请自行在 Issues 区讨论，或询问 AI 协助解决。感谢支持！
>
> I'm starting senior high school and will register tomorrow (Aug 23). After school starts I'll have almost no time to keep updating (Sundays if possible). Please discuss issues in the Issues section or ask an AI. Thanks for your support!


![PyPI version](https://img.shields.io/pypi/v/wechatbot-new)
![PyPI downloads](https://img.shields.io/pypi/dw/wechatbot-new)
![Python](https://img.shields.io/pypi/pyversions/wechatbot-new)
![License](https://img.shields.io/github/license/fanyuantaier/wechatbot-new)
![GitHub stars](https://img.shields.io/github/stars/fanyuantaier/wechatbot-new)

- 这是一个智能微信聊天机器人。通过wechatauto-replica收发微信消息，调用deepseek、gpt、gemini等大语言模型生成回复消息。
- 原项目仓库：https://github.com/KouriChat/KouriChat
- 本项目由iwyxdxl在原项目基础上修改创建，fanyuantaier进行兼容性重构（UIA路线在新版本微信上完全失效）
- 由于原项目停止更新，现由fanyuantaier继续更新维护
- 本机器人致力于实现更加拟人化聊天效果，支持多种功能。
- 本程序现已支持微信4.1.12.26及以上（底层 wechatauto-replica 已适配 4.1.15.13）
- 本版本已去除 Run.exe 的微信版本检查，可跳过注册表检测直接启动。

> [!WARNING]
> **关于配置里的默认模型地址**：`config.py` 出厂预置的是 `https://opencode.ai/zen/v1` + 模型名 `space-bunny-free`，API Key 填的是 `public`（这个端点不校验 Key）。
> **它是免费的，但不保证一直可用** —— 站点随时可能下线、改名或改成收费，届时表现是模型调用报错、机器人不回。
> 要稳定使用请自己换服务商：在配置页填 Chat / 辅助 / 识图 / 联网各自的地址与 Key（DeepSeek 官方、硅基流动、WeAPIs 等都可以），或点「获取可用模型」列出可用型号再填。本机跑模型的话把地址指成 `http://127.0.0.1:11434/v1` 这类本地端点即可。

# 效果展示
<img src="Demo_Image/1.png" alt="示例图片1" width="300px">
<img src="Demo_Image/2.png" alt="示例图片2" width="300px">
<img src="Demo_Image/3.png" alt="示例图片2" width="300px">
<img src="Demo_Image/4.png" alt="示例图片3" width="900px">
<img src="Demo_Image/5.png" alt="示例图片4" width="900px">

# 版本号
- v2.2.8.3（2026-10-17：修 2.2.8 引入的连接泄漏——判「我」时读 `status` 没关 `_msg_conns` 的分片连接，导致缓存重建被 Windows 拒绝，监听轮询/防撤回扫描刷 `PermissionError(13)` 且收不到新消息；`status_votes()` 改 try/finally 全关，回归测试补齐）
- v2.2.8.2（2026-10-03：仅文档——离线包直链换成 2.2.8.1 那份，代码与依赖零改动；发这个号只是为了让链接进 PyPI 描述）
- v2.2.8.1（2026-10-03：**代码与 2.2.8 一字未改**，只是撤回重发——2.2.8 的 wheel/sdist 里打进了打包机的真实 `config.py`（含 2 个联系人昵称，无密钥无令牌），该版本号作废；发布链路上加了「构建前查工作副本、构建后查产物」的 config.py 占位校验）
- v2.2.8（2026-10-03：修「这条是不是我发的」判错——`real_sender_id` 是分片内的短编号，写死 `== 2` 会把换编号那一段历史里的自己算成对方，风格档案于是照着对方的口吻学并替代该用户 Prompt；改为按 `status==2` 与表情 XML 里的 `fromusername` 两条正向证据判定，历史与实时两条路共用，群成员不再靠 `== 2` 冒充本机。另外：合并转发内容不再永远为空、识图接口补 timeout、读不到聊天记录时的提示不再自己抛 NameError、重试耗尽不再一律报「余额不足」、config 解析由 eval 改 literal_eval、机器人写 config.py 与编辑器共用文件锁、`ENABLE_URL_FETCHING` 补上界面开关；依赖下限 `wechatauto-replica>=1.2.4.4`）
- v2.2.7.1（2026-10-02：仅文档——新增「免安装离线包」一节，给出自带 Python 运行时的 zip 直链与用法（解压即用、不需要装 Python/pip、不联网、不需管理员权限），代码与依赖零改动）
- v2.2.7（2026-10-01：用户列表新增「读聊天记录」——用该会话的本地聊天记录生成「模仿我」的风格档案并替代该用户的 Prompt（生成即启用，不用再手动勾选保存）；未启用档案的用户可开「按需读取上下文」（启动预读 + 模型判断需要时再读，群聊也能按群名读到）；模型配置新增「获取可用模型」一键拉取 /models 列表、自定义模型名，以及单独的「档案生成模型」；消息识别重整——表情/卡片/红包/位置/合并转发不再把整段 XML 当正文给模型，卡片里的微信资源地址不再被当成网页链接，链接与引用判据补上 zstd 解压后在真机才真正生效；配置界面保存不再丢掉未选 Prompt 的用户行，新增配置项会自动补进旧 config.py）
- v2.2.6.1（2026-09-25：打包修正——把一键启动器 Run.exe 与 __init__.py 一起放进源码包（PyPI 的 sdist），__init__.py 改为按自身所在目录调用 Run.exe，不再依赖当前工作目录）
- v2.2.6（2026-09-25：依赖抬到 wechatauto-replica>=1.2.4.1——低于 1.2.4 在微信 4.1.15 上发送会直接失败；接入群消息真实发送者身份、语音取不到的原因、群成员；识图新增 DeepSeek官方（deepseek-flash）；新增防撤回（/撤回、/撤回 [条数]、/撤回统计、撤回提醒开关）与朋友圈（/朋友圈 [昵称|条数]、/朋友圈互动、朋友圈监听开关）；默认节流档位改为 fast）
- v2.2.5（2026-08-31：修复 WAL 合并后数据库解密缓存损坏导致死循环——改用 PRAGMA quick_check 全库校验，新增缓存自动失效+重建重试机制）
- v2.2.4（2026-08-17：修复首条消息响应延迟约 40 秒——聊天类型判断优先读监听缓存 O(1)，不再全量扫描；wxbot 新增 GetListenChatType()）
- v2.2.3（2026-08-16：兼容层接入拍一拍/撤回/语音通话，委托 wechatauto 1.1.x）
- v2.2.2（2026-08-12：修复 PyPI/GitHub 描述乱码——readme 恢复正确 UTF-8 中文，description 重写）
- v2.2.1（2026-08-11：readme 转 UTF-8 + 徽章，PyPI 元数据 SEO 优化）
- v2.2.0

# 致谢
- 感谢 [@liyifu-2026](https://github.com/liyifu-2026) 提出「聊天类型判断优先读监听缓存」的优化建议与方案（v2.2.4 修复首条消息响应延迟约 40 秒的问题）

# 目前支持的功能
1. 智能自动回复，支持多用户/群聊同时聊天，并可为每个用户或群聊分配独立的提示词（Prompt）
2. 图片和表情包内容识别
3. 情绪识别并回复表情包
4. 获取消息中的包含的链接的网页内容
5. AI时间感知（年-月-日 星期 时-分-秒）
6. 主动发送消息及合并处理多条消息或表情包。
7. 前端WebUI支持：启动程序、修改配置文件、生成和管理Prompt
8. 记忆功能：调用AI总结聊天记录保存到Prompt或者独立核心记忆文件
9. 让AI设置定时任务功能，例如"15分钟后提醒我出门"或"每天早上八点叫我起床"，并支持通过语音通话提醒
10. 支持联网搜索
11. 接收语音消息（需在微信设置中开启"聊天中的语音消息自动转文字"功能）
12. 自动更新程序
13. 特色功能 - 角色论坛
14. 指令功能

# 免安装离线包（不用装 Python）

不想在目标机上装 Python、也不想联网拉依赖，可以直接用离线包：一个自包含目录，里面是官方嵌入式 Python 3.12 运行时 + 本项目全部依赖，解压即用，不需要管理员权限。

- **下载**：`wechatbot-new-offline-2.2.8.1.zip`（142.6 MB，解压后 393 MB，4700 个文件 + 889 个目录条目）
  https://livefile.xesimg.com/programme/python_assets/38b0312752cece199400864abf0f67aa.zip
- **怎么用**：解压后双击 `start.bat` 打开配置网页（登录微信 → 填 API → Start Bot）；`wx.bat 你的脚本.py` 用包内 Python 跑任意脚本；`diagnose.bat` 自检能不能解密本地数据库；`README-offline.md` 是完整说明。
- **前提**：64 位 Windows 10/11，微信 4.1.12 及以上且已登录；**不要「以管理员身份运行」**——微信以普通权限运行时，提权进程读它的内存会被系统拒绝，表现为取不到密钥。
- **出厂配置是占位内容**（`微信名1` / `角色1`），包内不含任何人的昵称或聊天记录；数据库密钥缓存在 `%LOCALAPPDATA%\wechatauto_keys\`、风格档案与节流配置在 `%USERPROFILE%\.wechatauto\`，都写在当前用户目录、不跟着包走，别把这两个目录发给别人。
- 离线包按版本单独打，包内 `python.exe` 与打包机的 Python 小版本一致（当前 3.12.9）；出问题时先跑 `check_env.py`，它会打印读到的监听用户、模型地址与会话数。

# 使用前准备
1. 请先安装python、pip，python版本应大于等于3.9（用上面的离线包可跳过这一步）
2. 申请大模型API,推荐WeAPIs https://vg.v1api.cc/register?aff=WnGO

# 快速上手
1. 登录电脑微信，确保在后台运行
2. 运行 Run.exe 启动程序，等待自动安装依赖文件（Run.exe 会自动检查 Python 和 pip 环境并安装所需依赖，不检查微信版本）
3. 在打开的网页中修改配置文件，选择您的API服务提供商、模型，并填入您的API KEY
4. 在页面左侧点击'Prompt管理' 进入提示词管理页面
5. 在提示词管理页面您可以参考自带的提示词样式编写或者使用提示词生成器生成您需要的提示词
6. 回到配置编辑器页面，填入微信昵称或群聊名称，并选择对应提示词
7. 修改完配置后点击页面右上角'Start Bot'启动程序
8. 如果想要自定义表情包请将表情包(.gif .png .jpg .jpeg)文件放入emojis文件夹中对应的情绪文件夹内（可以自己添加情绪种类）

# 联系方式
1. 邮箱 fanyuantaier@163.com

# 声明
- 本项目基于 [KouriChat](https://github.com/KouriChat/KouriChat) 修改(原My-Dream-Moments项目)，遵循 **GNU GPL-3.0 或更高版本** 许可证，原项目版权归属：umaru (2025)。
- **修改说明**：本项目在2025年期间对原始代码进行了大量修改和重构，包括但不限于：
  - 完全重写了用户界面和配置系统
  - 大幅扩展了机器人功能和AI集成
  - 重构了消息处理和自动化逻辑
  - 添加了大量新特性如情绪识别、定时任务、联网搜索等
- 由于修改范围广泛且深入，无法精确标注每处修改的具体日期，但所有修改均在上述时间段内完成。
- 本修改版本保持与原项目相同的GPL-3.0许可证，确保用户享有相同的自由软件权利。

- **修改说明**：本项目在上一位维护者基础上兼容了微信4.1.12.26，具体内容包括但不限于：
  - 由于wxautox已经不支持最新版微信，使用opencode复刻出wechatauto-replica（发布在pypi和github）
  - 重构核心代码，全部替换为wechatauto-replica的接口
  - 去除Run.exe中的检查微信版本功能，不限微信版本
- 修改的具体日期是2026年8月初

## 许可证和依赖说明
- **主许可证**：GNU GPL-3.0 或更高版本
- **依赖库**：项目使用私有授权的微信自动化库作为可选增强功能，并提供开源备选方案
- **合规性**：详细的许可证合规性说明请参阅 [DEPENDENCIES.txt](DEPENDENCIES.txt)
- **用户权利**：无论使用哪种依赖库，用户都享有完整的GPL-3.0自由软件权利
