#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
队列状态诊断脚本
"""
import redis

# 连接Redis
redis_client = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)

print("=" * 60)
print("RPA队列状态诊断")
print("=" * 60)

# 检查队列暂停状态
queue_paused = redis_client.get('rpa:queue_paused')
print(f"\n1. 队列暂停标志 (rpa:queue_paused):")
if queue_paused:
    print(f"   ❌ 队列已暂停，值: {queue_paused}")
    # 检查TTL
    ttl = redis_client.ttl('rpa:queue_paused')
    if ttl > 0:
        print(f"   ⏰ 剩余有效期: {ttl}秒 ({ttl // 60}分钟)")
    else:
        print(f"   ⚠️  无过期时间或已过期")
else:
    print(f"   ✅ 队列正常运行（标志不存在）")

# 检查恢复token
resume_token = redis_client.get('rpa:resume_token')
print(f"\n2. 恢复Token (rpa:resume_token):")
if resume_token:
    print(f"   存在，值: {resume_token}")
    ttl = redis_client.ttl('rpa:resume_token')
    if ttl > 0:
        print(f"   ⏰ 剩余有效期: {ttl}秒 ({ttl // 60}分钟)")
    else:
        print(f"   ⚠️  无过期时间或已过期")
else:
    print(f"   ✅ Token不存在（已恢复或未暂停）")

# 检查任务执行状态
task_running = redis_client.get('rpa:task_running')
print(f"\n3. 任务执行状态 (rpa:task_running):")
if task_running:
    print(f"   ⚙️  有任务正在执行，值: {task_running}")
else:
    print(f"   ✅ 无任务执行中")

# 检查Celery队列
celery_queue_len = redis_client.llen('celery')
print(f"\n4. Celery队列长度:")
print(f"   待处理任务数: {celery_queue_len}")

# 列出所有RPA相关的键
print(f"\n5. 所有RPA相关的Redis键:")
rpa_keys = redis_client.keys('rpa:*')
if rpa_keys:
    for key in rpa_keys:
        value = redis_client.get(key)
        ttl = redis_client.ttl(key)
        print(f"   - {key}: {value} (TTL: {ttl}s)")
else:
    print(f"   ✅ 无RPA相关键（队列正常）")

print("\n" + "=" * 60)
print("诊断建议:")
print("=" * 60)

if queue_paused:
    print("⚠️  队列当前处于暂停状态，需要执行以下操作之一：")
    print("   1. 访问恢复链接（如果token有效）")
    print("   2. 手动删除暂停标志: redis-cli DEL rpa:queue_paused")
    print(f"   3. 等待 {redis_client.ttl('rpa:queue_paused')}秒 自动过期")
else:
    print("✅ 队列状态正常，可以接收新任务")

print("=" * 60)
