"""清理前端 dist 目录，仅保留最新构建产物"""
import pathlib, shutil, re

dist = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"
if not dist.exists():
    print("dist 目录不存在")
    exit(0)

# 统计旧文件
old_js = list(dist.rglob("*.js"))
old_size = sum(f.stat().st_size for f in old_js)
print(f"当前 dist: {len(old_js)} 个 JS 文件, {old_size // 1024 // 1024} MB")

# 全部删除
shutil.rmtree(dist)
print(f"已删除 {dist}")

# 重新 mkdir（保持目录存在）
dist.mkdir(parents=True)
print("dist 目录已重建")
