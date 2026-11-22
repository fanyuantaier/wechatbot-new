# -*- coding: utf-8 -*-
"""Test wxbot module"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\WeChatBot-main')
from wxbot import WeChat

w = WeChat(debug=True)

print('=== Full API Test ===')
print(f'nickname: {w.nickname}')
r = w.AddListenChat(nickname='小哲', callback=lambda m, c: None)
print(f'AddListenChat: {r}')
print(f'Listen: {list(w.listen.keys())}')
print(f'GetAllSubWindow: {w.GetAllSubWindow()}')
r2 = w.ChatWith('文件传输助手')
print(f'ChatWith: {r2}')
r3 = w.SendMsg('hello from wxbot', who='文件传输助手')
print(f'SendMsg: {r3}')
print(f'GetAllMessage: {len(w.GetAllMessage())}')
print('=== All OK ===')
