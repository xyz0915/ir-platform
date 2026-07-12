"""调试 AlertEngine."""
import logging
logging.basicConfig(level=logging.DEBUG)

from app.services.alert_engine import AlertEngine
from app.models.alert import Alert

engine = AlertEngine()

# 使用一个完全不存在的 rule_name 测试
result = Alert.create_or_aggregate(
    host_id=5,
    rule_name="unique_test_rule_12345",
    severity="high",
    title="Unique Test",
)
print("create_or_aggregate result:", result)

# 检查创建结果
if result[0]:
    alert = Alert.get_by_id(result[0])
    print("Created alert:", alert)
