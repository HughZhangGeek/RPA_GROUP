#!/usr/bin/env python3
"""
RPA_GROUP 项目打包脚本
生成可分发的 zip 包，排除敏感文件和运行时生成的文件
"""
import os
import zipfile
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# 输出文件名（带时间戳）
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = PROJECT_ROOT / f"RPA_GROUP_v1.0_{timestamp}.zip"

# 需要打包的文件和目录
INCLUDE_PATTERNS = [
    # Python 源码
    "RPA.py",
    "database.py",
    "queue_worker.py",
    "check_queue_status.py",
    "migrate_redis_to_sqlite.py",

    # 配置模板
    ".env.example",
    "config.py.example",
    ".gitignore",

    # 依赖文件
    "requirements.txt",
    "environment.yml",

    # 文档
    "ReadMe.md",
    "CLAUDE.md",
    "DEPLOYMENT.md",
    "PACKAGE_README.md",
    "优化.md",

    # 启动脚本
    "start.bat",
    "start_linux.sh",

    # 测试文件
    "test_send_message.http",
    "恢复队列.http",

    # 模板目录
    "templates/",

    # 资源文件
    "file/excel/",
    "file/pictures/wxwork/",
    "file/pictures/error.png",
]

# 排除的文件和目录
EXCLUDE_PATTERNS = [
    # 敏感配置
    ".env",
    "config.py",

    # 数据库文件
    "*.db",
    "*.db-shm",
    "*.db-wal",

    # 日志文件
    "*.log",
    "*.log.*",

    # 运行时生成的截图
    "file/pictures/error_shots/",

    # Python 缓存
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".Python",
    "*.egg-info/",
    "dist/",
    "build/",
    ".eggs/",

    # IDE 配置
    ".idea/",
    ".vscode/",
    "*.swp",
    "*.swo",

    # Git
    ".git/",

    # 系统文件
    "Thumbs.db",
    "Desktop.ini",
    ".DS_Store",

    # 打包脚本本身
    "create_package.py",
]


def should_exclude(file_path: Path) -> bool:
    """检查文件是否应该被排除"""
    path_str = str(file_path.relative_to(PROJECT_ROOT))

    for pattern in EXCLUDE_PATTERNS:
        if pattern.endswith('/'):
            # 目录匹配
            if path_str.startswith(pattern.rstrip('/')):
                return True
        elif '*' in pattern:
            # 通配符匹配
            import fnmatch
            if fnmatch.fnmatch(path_str, pattern):
                return True
        else:
            # 精确匹配
            if path_str == pattern or path_str.endswith('/' + pattern):
                return True

    return False


def add_to_zip(zipf: zipfile.ZipFile, file_path: Path, arcname: str):
    """添加文件到 zip"""
    if file_path.is_file():
        if not should_exclude(file_path):
            print(f"  添加: {arcname}")
            zipf.write(file_path, arcname)
    elif file_path.is_dir():
        for item in file_path.rglob('*'):
            if item.is_file() and not should_exclude(item):
                rel_path = item.relative_to(PROJECT_ROOT)
                print(f"  添加: {rel_path}")
                zipf.write(item, f"RPA_GROUP/{rel_path}")


def create_package():
    """创建打包文件"""
    print("=" * 60)
    print("RPA_GROUP 项目打包工具")
    print("=" * 60)
    print()

    # 创建 zip 文件
    with zipfile.ZipFile(OUTPUT_FILE, 'w', zipfile.ZIP_DEFLATED) as zipf:
        print("正在打包文件...")
        print()

        for pattern in INCLUDE_PATTERNS:
            path = PROJECT_ROOT / pattern

            if not path.exists():
                print(f"  警告: {pattern} 不存在，跳过")
                continue

            if path.is_file():
                arcname = f"RPA_GROUP/{pattern}"
                add_to_zip(zipf, path, arcname)
            elif path.is_dir():
                add_to_zip(zipf, path, pattern)

    # 显示结果
    print()
    print("=" * 60)
    print("打包完成！")
    print("=" * 60)
    print(f"输出文件: {OUTPUT_FILE.name}")
    print(f"文件大小: {OUTPUT_FILE.stat().st_size / 1024:.2f} KB")
    print()

    # 列出 zip 内容
    print("包含的文件:")
    with zipfile.ZipFile(OUTPUT_FILE, 'r') as zipf:
        for info in zipf.filelist:
            print(f"  {info.filename} ({info.file_size} bytes)")

    print()
    print("提示:")
    print("1. 解压后需要创建 .env 和 config.py 文件")
    print("2. 参考 .env.example 和 config.py.example")
    print("3. 详细部署步骤请查看 DEPLOYMENT.md")
    print()


if __name__ == "__main__":
    create_package()