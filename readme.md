# 说明

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
- 本程序现已支持微信4.1.12.26
- 本版本已去除 Run.exe 的微信版本检查，可跳过注册表检测直接启动。

# 效果展示
<img src="Demo_Image/1.png" alt="示例图片1" width="300px">
<img src="Demo_Image/2.png" alt="示例图片2" width="300px">
<img src="Demo_Image/3.png" alt="示例图片2" width="300px">
<img src="Demo_Image/4.png" alt="示例图片3" width="900px">
<img src="Demo_Image/5.png" alt="示例图片4" width="900px">

# 版本号
- v2.2.4（2026-08-17：修复首条消息响应延迟约 40 秒——聊天类型判断优先读监听缓存 O(1)，不再全量扫描；wxbot 新增 GetListenChatType()）
- v2.2.3（2026-08-16：兼容层接入拍一拍/撤回/语音通话，委托 wechatauto 1.1.x）
- v2.2.2（2026-08-12：修复 PyPI/GitHub 描述乱码——readme 恢复正确 UTF-8 中文，description 重写）
- v2.2.1（2026-08-11：readme 转 UTF-8 + 徽章，PyPI 元数据 SEO 优化）
- v2.2.0

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

# 使用前准备
1. 请先安装python、pip，python版本应大于等于3.9
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
