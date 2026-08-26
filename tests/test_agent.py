# -*- coding: utf-8 -*-
"""
企业微信群聊智能体 - 测试套件

运行: python tests/test_agent.py
"""
import sys
import json
import unittest
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.main import WeComGroupAgent
from src.core.intent_classifier import IntentClassifier
from src.core.role_manager import RoleManager
from src.core.trigger_engine import TriggerEngine


class TestIntentClassifier(unittest.TestCase):
    """测试意图分类器"""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier()

    def test_booking_message(self):
        """测试订单信息识别"""
        content = "上门时间26.8.18 标准：精致母婴 平台：点评北京 面积：70㎡优惠价：1960 姓名：李天浩 电话：13717557222 地址：北京市丰台区钟萃路 3 号院 2号楼2单元1301"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_BOOKING)
        self.assertGreater(score, 5)

    def test_appointment_intent(self):
        """测试预约时间意图"""
        content = "哦，忘了，我明天上午有事，十十十点以后可以吗？"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_APPOINTMENT)
        self.assertGreaterEqual(score, 3)

    def test_contract_intent(self):
        """测试合同意图"""
        content = "为什么要填写这么多个人信息，你们带纸质合同过来我直接签"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_CONTRACT)
        self.assertGreaterEqual(score, 3)

    def test_construction_intent(self):
        """测试施工意图"""
        content = "今天进人不影响吧，屋子里可以呆了吗"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_CONSTRUCTION)
        self.assertGreaterEqual(score, 3)

    def test_medication_intent(self):
        """测试药剂意图"""
        content = "我有个疑问，甲醛无色无味，所以即使催化了，快速释放也是没有味道的，现在房间的味道为啥那么大呢"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_MEDICATION)
        self.assertGreaterEqual(score, 3)

    def test_no_intent(self):
        """测试无意图"""
        content = "好的，谢谢"
        intent, score = self.classifier.classify(content)
        self.assertEqual(intent, IntentClassifier.INTENT_NONE)


class TestTriggerEngine(unittest.TestCase):
    """测试触发引擎"""

    @classmethod
    def setUpClass(cls):
        cls.role_manager = RoleManager()
        cls.classifier = IntentClassifier()
        cls.engine = TriggerEngine(cls.classifier, cls.role_manager)

    def _make_msg(self, userid, role, content, **kwargs):
        from src.models.message import Message
        return Message(
            userid=userid, role=role, content=content,
            timestamp=kwargs.get("timestamp", ""),
            msgid=kwargs.get("msgid", "test"),
            is_last_in_window=kwargs.get("is_last_in_window", False),
            has_response_after=kwargs.get("has_response_after", False),
        )

    def test_trigger1_booking(self):
        """测试触发1: 销售发送订单"""
        msg = self._make_msg(
            "王销售", "销售",
            "上门时间26.8.18 标准：精致母婴 平台：点评北京 面积：70㎡优惠价：1960 姓名：李天浩 电话：13717557222 地址：北京市丰台区钟萃路 3 号院 2号楼2单元1301"
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_BOOKING)

    def test_trigger2_appointment_timeout(self):
        """测试触发2: 预约时间超时"""
        msg = self._make_msg(
            "李天浩", "客户",
            "哦，忘了，我明天上午有事，明嗯，十十十点以后可以吗？",
            is_last_in_window=True, has_response_after=False
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_APPOINTMENT_TIMEOUT)

    def test_trigger3_contract_timeout(self):
        """测试触发3: 合同超时"""
        msg = self._make_msg(
            "李天浩", "客户",
            "为什么要填写这么多个人信息，你们带纸质合同过来我直接签",
            is_last_in_window=True, has_response_after=False
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_CONTRACT_TIMEOUT)

    def test_trigger4_construction_timeout(self):
        """测试触发4: 施工超时"""
        msg = self._make_msg(
            "李天浩", "客户",
            "今天进人不影响吧，屋子里可以呆了吗",
            is_last_in_window=True, has_response_after=False
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_CONSTRUCTION_TIMEOUT)

    def test_trigger5_medication_timeout(self):
        """测试触发5: 药剂超时"""
        msg = self._make_msg(
            "李天浩", "customer",
            "我有个疑问，甲醛无色无味，所以即使催化了，快速释放也是没有味道的，现在房间的味道为啥那么大呢",
            is_last_in_window=True, has_response_after=False
        )
        # role = "customer" 需要正确映射
        msg.role = "customer"
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_MEDICATION_TIMEOUT)

    def test_no_trigger_customer_responded(self):
        """测试: 客户消息但已有人响应 -> 不触发"""
        msg = self._make_msg(
            "李天浩", "customer",
            "明天上午十点以后可以吗？",
            is_last_in_window=True, has_response_after=True
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_NONE)

    def test_no_trigger_master_message(self):
        """测试: 师傅消息 -> 不触发"""
        msg = self._make_msg(
            "霍师傅", "master",
            "好的，我明天上午9点准时到"
        )
        trigger, intent, score = self.engine.evaluate(msg)
        self.assertEqual(trigger, TriggerEngine.TRIGGER_NONE)


class TestWeComGroupAgent(unittest.TestCase):
    """测试完整智能体"""

    @classmethod
    def setUpClass(cls):
        cls.agent = WeComGroupAgent()

    def _load_test_data(self, filename):
        path = PROJECT_ROOT / "tests" / "test_data" / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_trigger1_booking_full(self):
        """测试触发1完整流程"""
        data = self._load_test_data("trigger1_booking.json")
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["trigger_type"], "booking")
        self.assertGreaterEqual(len(result["responses"]), 3)  # 前摇1 + 前摇2 + @师傅
        # 检查@师傅
        at_targets = result["responses"][-1]["at_target"]
        self.assertTrue(any("师傅" in t for t in at_targets))
        # 检查内容包含"请主动联系客户确认上门时间"
        action_content = result["responses"][-1]["content"]
        self.assertIn("请主动联系客户确认上门时间", action_content)

    def test_trigger2_appointment_full(self):
        """测试触发2完整流程"""
        data = self._load_test_data("trigger2_appointment.json")
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["trigger_type"], "appointment_timeout")
        self.assertEqual(len(result["responses"]), 1)
        at_targets = result["responses"][0]["at_target"]
        self.assertTrue(any("师傅" in t for t in at_targets))

    def test_trigger3_contract_full(self):
        """测试触发3完整流程"""
        data = self._load_test_data("trigger3_contract.json")
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["trigger_type"], "contract_timeout")
        at_targets = result["responses"][0]["at_target"]
        self.assertTrue(any("销售" in t for t in at_targets))

    def test_trigger4_construction_full(self):
        """测试触发4完整流程"""
        data = self._load_test_data("trigger4_construction.json")
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["trigger_type"], "construction_timeout")
        at_targets = result["responses"][0]["at_target"]
        self.assertTrue(any("销售" in t for t in at_targets))

    def test_trigger5_medication_full(self):
        """测试触发5完整流程"""
        data = self._load_test_data("trigger5_medication.json")
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        self.assertEqual(result["trigger_type"], "medication_timeout")
        at_targets = result["responses"][0]["at_target"]
        self.assertTrue(any("销售" in t for t in at_targets))
        self.assertTrue(any("工程部负责人" in t for t in at_targets))

    def test_no_trigger_normal(self):
        """测试无触发 - 正常消息"""
        data = self._load_test_data("no_trigger_normal.json")
        result = self.agent.process(data)
        self.assertFalse(result["triggered"])
        self.assertEqual(len(result["responses"]), 0)

    def test_no_trigger_responded(self):
        """测试无触发 - 已有人响应"""
        data = self._load_test_data("no_trigger_responded.json")
        result = self.agent.process(data)
        self.assertFalse(result["triggered"])

    def test_empty_messages(self):
        """测试空消息列表"""
        result = self.agent.process({"group_name": "test", "messages": []})
        self.assertFalse(result["triggered"])

    def test_debug_classify(self):
        """测试调试分类"""
        result = self.agent.debug_classify("甲醛味道很大，是不是药剂有问题")
        self.assertIn("all_scores", result)
        self.assertGreater(result["all_scores"].get("medication", 0), 0)


class TestResponseContent(unittest.TestCase):
    """测试响应内容正确性"""

    @classmethod
    def setUpClass(cls):
        cls.agent = WeComGroupAgent()

    def test_booking_preamble_content(self):
        """测试前摇文案内容"""
        data = {
            "group_name": "test",
            "messages": [{
                "userid": "王销售", "role": "销售",
                "content": "上门时间26.8.18 标准：精致母婴 平台：点评北京 面积：70㎡优惠价：1960 姓名：李天浩 电话：13717557222 地址：北京市丰台区钟萃路",
                "is_last_in_window": False, "has_response_after": False
            }]
        }
        result = self.agent.process(data)
        self.assertTrue(result["triggered"])
        # 检查前摇1包含"感谢您选择"
        preamble1 = result["responses"][0]["content"]
        self.assertIn("感谢", preamble1)
        self.assertIn("清新全家", preamble1)
        self.assertIn("科迈斯诺", preamble1)
        # 检查前摇2包含师傅电话
        preamble2 = result["responses"][1]["content"]
        self.assertIn("霍师傅", preamble2)
        self.assertIn("15120069954", preamble2)
        # 检查@师傅行动
        action = result["responses"][2]["content"]
        self.assertIn("请主动联系客户确认上门时间", action)

    def test_timeout_response_templates(self):
        """测试超时响应模板"""
        # 预约超时
        result = self.agent.process({
            "group_name": "test",
            "messages": [{
                "userid": "李天浩", "role": "customer",
                "content": "明天上午十点以后可以吗？",
                "is_last_in_window": True, "has_response_after": False
            }]
        })
        self.assertIn("师傅", result["responses"][0]["content"])

        # 药剂超时
        result = self.agent.process({
            "group_name": "test",
            "messages": [{
                "userid": "李天浩", "role": "customer",
                "content": "甲醛无色无味，催化了也没味道，为啥房间味道那么大",
                "is_last_in_window": True, "has_response_after": False
            }]
        })
        self.assertIn("专家", result["responses"][0]["content"])


def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestIntentClassifier))
    suite.addTests(loader.loadTestsFromTestCase(TestTriggerEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestWeComGroupAgent))
    suite.addTests(loader.loadTestsFromTestCase(TestResponseContent))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("企业微信群聊智能体 - 测试套件")
    print("=" * 60)
    result = run_all_tests()
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"✅ 全部测试通过! ({result.testsRun} 个测试)")
    else:
        print(f"❌ 测试失败: {len(result.failures)} 个失败, {len(result.errors)} 个错误")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
