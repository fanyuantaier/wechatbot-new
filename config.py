# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# ***********************************************************************

# 用户列表(请配置要和bot说话的账号的微信昵称！)
# 例如：LISTEN_LIST = [['微信名1', '角色1'],['微信名2', '角色2']]
LISTEN_LIST = [['你的微信昵称', '角色1']]

# 本机 empero（Qwen3.8-35B-A3B-Distill IQ3_M）：llama.cpp Vulkan llama-server 直连
# 服务不是开机常驻，重启或异常后要先把 11440 拉起来（见 bot 侧 README 备注 / oc_matrix.load）
DEEPSEEK_API_KEY = 'local35b'
DEEPSEEK_BASE_URL = 'http://127.0.0.1:11440/v1'
# 这里填任意标签都行：llama.cpp 不校验 model 字段。若用严格客户端，/v1/models 返回的 id 是权重文件全路径
MODEL = 'empero-35b'
# 用户和AI对话轮数
MAX_GROUPS = 5

# 如果要使用官方的API
# DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
# 官方API的V3模型
# MODEL = 'deepseek-chat'

# 回复最大token。empero 是开思考的模型，思考也计入这个额度：2026-10-01 实测 Nex（同族）在 8192 下
# 有一跳把 50,968 字符全花在思考上、正文为 0；给到 16384 且服务端 -c 65536 才彻底不再空白。
# 所以这里不能按旧远程模型的 2000 用。
MAX_TOKEN = 8192
# DeepSeek温度
TEMPERATURE = 0.7

# Moonshot AI配置（用于图片和表情包识别）
# API申请https://platform.moonshot.cn/
MOONSHOT_API_KEY = 'local35b'
# 本机 empero 带视觉：同一个 llama-server（:11440）启动时挂了 mmproj-Qwen3.8-35B-A3B-F16.gguf，
# 服务端日志已确认 "loaded multimodal model"。注意 bot.py 是往 f"{BASE}/chat/completions" 发的，
# 所以这里必须带上 /v1。实测：普通图片 18.0s、表情包提示词 38.2s，图里四字埋点 4/4 全读回。
MOONSHOT_BASE_URL = 'http://127.0.0.1:11440/v1'
MOONSHOT_MODEL = 'empero-35b'
MOONSHOT_TEMPERATURE = 0.5
ENABLE_IMAGE_RECOGNITION = True
ENABLE_EMOJI_RECOGNITION = True

# 消息队列等待时间
QUEUE_WAITING_TIME = 7

# 表情包存放目录
EMOJI_DIR = 'emojis'
ENABLE_EMOJI_SENDING = True
EMOJI_SENDING_PROBABILITY = 70

# 自动消息配置
AUTO_MESSAGE = '请你模拟系统设置的角色，在微信上找对方继续刚刚的话题或者询问对方在做什么'
ENABLE_AUTO_MESSAGE = False
# 等待时间
MIN_COUNTDOWN_HOURS = 1.0
MAX_COUNTDOWN_HOURS = 2.0
# 消息发送时间限制
QUIET_TIME_START = '22:00'
QUIET_TIME_END = '8:00'
# 不对群聊发送自动消息
IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE = False

# 消息回复时间间隔
# 间隔时间 = 字数 * (平均时间 + 随机时间)
AVERAGE_TYPING_SPEED = 0.5
RANDOM_TYPING_SPEED_MIN = 0.05
RANDOM_TYPING_SPEED_MAX = 0.1
SEPARATE_ROW_SYMBOLS = True

# 记忆功能
# 采用综合评分公式：0.6*重要度 - 0.4*(存在时间小时数)
# 示例：
# 重要度5的旧记忆（存在12小时）得分：0.65 - 0.412 = 3 - 4.8 = -1.8
# 重要度4的新记忆（存在1小时）得分：0.64 - 0.41 = 2.4 - 0.4 = 2.0 → 保留新记忆
ENABLE_MEMORY = True
MEMORY_TEMP_DIR = 'Memory_Temp'
MAX_MESSAGE_LOG_ENTRIES = 30
MAX_MEMORY_NUMBER = 50
UPLOAD_MEMORY_TO_AI = True
# 记忆存储方式：True = 保存到单独的JSON文件，False = 保存到prompt文件中
SAVE_MEMORY_TO_SEPARATE_FILE = True
CORE_MEMORY_DIR = 'CoreMemory'

# 是否接收全部群聊消息
ACCEPT_ALL_GROUP_CHAT_MESSAGES = False
ENABLE_GROUP_AT_REPLY = True
ENABLE_GROUP_KEYWORD_REPLY = True
GROUP_KEYWORD_LIST = ['樊伊航', '机器人', '人机']
GROUP_CHAT_RESPONSE_PROBABILITY = 0
GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY = True

# 登录配置编辑器设置
ENABLE_LOGIN_PASSWORD = False
LOGIN_PASSWORD = 'YOUR_PASSWORD'
PORT = 5000

# 文字指令识别开关
# 开启后，私聊/群聊（满足触发条件）中以“/”开头的指令将被解析并执行
ENABLE_TEXT_COMMANDS = True

# 定时器/提醒设置
# 启用提醒功能
ENABLE_REMINDERS = True
# 是否允许在安静时间内发送提醒 (True/False)
# 如果设置为 False，则在安静时间内安排的提醒将被跳过。
ALLOW_REMINDERS_IN_QUIET_TIME = True
# 是否使用语音通话进行提醒
# 群聊无法使用语音通话进行提醒
USE_VOICE_CALL_FOR_REMINDERS = True

# 联网API配置
# 主模型换成本机 empero 后，"联网"改成两步：bot.py 的取证层抓材料（免 key，本机实测可达的
# cn.bing.com 与 wttr.in），作答仍由本机 empero 做。ONLINE_API_KEY / ONLINE_BASE_URL / ONLINE_MODEL
# 这三项已经不再被调用（保留仅为兼容配置编辑器界面），所以留空也能用。
# 代价：一条需要联网的消息要多排两次队（检测 + 作答，服务端 --parallel 1），实测各 9-13 秒。
ENABLE_ONLINE_API = True
ONLINE_SEARCH_TOP_N = 3
# 关键词预筛：False 则每条消息都过一次"要不要联网"的大模型检测（实测 8.7-20.4 秒/条）
ENABLE_ONLINE_PREFILTER = True
# 命中任意一个词才去做检测；漏判就往这里加词
ONLINE_PREFILTER_WORDS = (
    "天气", "气温", "温度", "多少度", "下雨", "下雪", "新闻", "热搜", "最新", "最近", "刚刚",
    "现在", "此刻", "几点", "今天", "明天", "后天", "这周", "本周", "今年", "去年",
    "股价", "股票", "汇率", "油价", "票价", "价格", "多少钱", "比分", "赛果", "榜单",
    "查一下", "查查", "帮我查", "搜一下", "搜索", "是不是真的", "什么时候", "多少人来着",
)
ONLINE_BASE_URL = 'https://vg.v1api.cc/v1'
ONLINE_MODEL = 'deepseek-r1-searching'
ONLINE_API_KEY = 'YOUR_API_KEY'
ONLINE_API_TEMPERATURE = 0.5
ONLINE_API_MAX_TOKEN = 2000
SEARCH_DETECTION_PROMPT = '是否需要查询今天的天气、最新的新闻事件、特定网站的内容、股票价格、特定人物的最新动态、歌词、小说情节、游戏内容、网络热梗、历史信息等'
ONLINE_FIXED_PROMPT = ''

# 是否启用自动抓取消息中URL链接内容的功能
ENABLE_URL_FETCHING = True
# 网络请求超时时间 (秒)
REQUESTS_TIMEOUT = 10
# 抓取网页时使用的 User-Agent，模拟浏览器防止被屏蔽
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
REQUESTS_USER_AGENT = 'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36'
# 从网页提取内容的最大字符数，防止上下文过长，影响AI处理效率和成本
MAX_WEB_CONTENT_LENGTH = 2000

# 定时重启配置
ENABLE_SCHEDULED_RESTART = True
RESTART_INTERVAL_HOURS = 2.0
RESTART_INACTIVITY_MINUTES = 15

# 强制移除括号当中的内容
REMOVE_PARENTHESES = False

# 是否使用辅助模型
# 关掉的原因：辅助模型那几项还指向远程网关且 key 是占位符，开着会在"记忆摘要"这一步反复失败；
# 关掉后摘要改由主模型（本机 empero）做，代码里所有分支都带 and ENABLE_ASSISTANT_MODEL 保护，安全。
# 想要快又省，这一项最适合放本机 4B（Qwen3-4B-Instruct-2507，2.55 GB，短输入 prefill 实测 368 t/s）。
ENABLE_ASSISTANT_MODEL = False
ASSISTANT_BASE_URL = 'https://vg.v1api.cc/v1'
ASSISTANT_MODEL = 'gpt-4o-mini'
ASSISTANT_API_KEY = 'YOUR_API_KEY'
ASSISTANT_TEMPERATURE = 0.3
ASSISTANT_MAX_TOKEN = 1000
USE_ASSISTANT_FOR_MEMORY_SUMMARY = True

# 敏感词处理配置
# 开启后遇到敏感词时自动清除Memory_Temp文件和聊天上下文
ENABLE_SENSITIVE_CONTENT_CLEARING = True

# 论坛自定义模型配置（可选）
ENABLE_FORUM_CUSTOM_MODEL = False
FORUM_BASE_URL = 'https://vg.v1api.cc/v1'
FORUM_MODEL = 'deepseek-ai/DeepSeek-V3'
FORUM_API_KEY = ''
FORUM_TEMPERATURE = 1.0
FORUM_MAX_TOKEN = 1200


