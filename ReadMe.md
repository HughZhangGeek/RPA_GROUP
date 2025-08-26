# 自动化建群工具

基于FastAPI + Celery + PyAutoGUI实现的跨平台群聊自动化创建工具，支持企业微信/钉钉的自动化操作。

## 功能特性

- RESTful API 触发自动化流程
- API密钥鉴权保障安全性
- Excel驱动指令配置（支持动态切换模板）
- 支持图像识别点击/坐标点击/快捷键操作
- 窗口激活/粘贴输入/等待检查等复合操作
- Celery任务队列支持异步处理
- 完善的日志记录与错误处理

## 快速开始

### 环境要求

- Python 3.8+
- Redis Server
- Windows系统（支持企业微信/钉钉客户端）

### 安装步骤

1. 克隆仓库
```bash
git clone https://github.com/HughZhangGeek/RPA_GROUP.git
```
2. 安装依赖
```bash
pip install -r requirements.txt
```
3. 准备基础环境
- 安装并启动Redis服务
- 配置企业微信/钉钉客户端
- 准备cmd.xlsx指令文件

4. 启动服务
```bash
uvicorn RPA:app --reload
celery -A RPA:celery_app worker --loglevel=info -P eventlet

```

## API文档
### 请求示例
```http
POST /start-automation
Headers:
  X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il
Body:
{
    "group_config": {
        "粘贴群成员": "外部群专用  测试成员1 测试成员2",
        "粘贴群名称": "企微自动拉群测试sss8",
        "粘贴群主姓名": "群主",
        "粘贴@销售姓名": "sales",
        "群类型":"企业微信群"
    }
}
```
### 响应示例
```json
{
  "status": "任务已提交",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "monitor": "/tasks/550e8400-e29b-41d4-a716-446655440000"
}
```

## 操作映射表
| 操作类型     | 参数示例 | 说明      |
|----------|------|---------|  
| 左击图片     | /images/button.png | 识别图片左键单击 |
| 右击图片     | /images/button.png | 识别图片右键单击 |
| 快捷键      | ctrl+v | 组合键操作   |
| 检查图片是否存在 | /images/confirm.png | 返回布尔值|
| 激活企业微信	 | C:/WXWork.lnk | 窗口激活+最大化|
| 粘贴     | 测试文本 | 系统级剪贴板操作 |

## 注意事项
1. 安全配置
- 请在启动服务前设置API密钥，并确保在请求中携带正确的API密钥
- 请在启动服务前设置Redis服务地址，并确保Redis服务正常启动
- 生产环境建议关闭reload参数

2. 路径配置
- 确保EXCEL_PATH指向有效的指令文件
- 图像路径建议使用绝对路径

3. 兼容性
- 屏幕分辨率与图像截图一致
- 钉钉企微版本需要匹配操作逻辑

4. 性能调优
- 调整CONFIDENCE平衡识别精度/速度
- 根据硬件配置修改CLICK_INTERVAL
