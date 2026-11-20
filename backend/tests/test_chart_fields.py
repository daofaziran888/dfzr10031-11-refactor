"""图表消费字段字典与看板横轴绑定的回归测试。

运行：cd backend && python3 -m pytest tests 或 python3 tests/test_chart_fields.py
"""
from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import chart_fields  # noqa: E402
from app.store import store  # noqa: E402

CHART_LIST_FIELDS = ["图表编号", "图表名称", "图表类型", "数据来源", "坐标字段", "聚合方式", "颜色方案", "图表状态"]
DASHBOARD_LIST_FIELDS = ["看板编号", "看板名称", "包含图表", "数据刷新", "可见范围", "创建人", "创建时间", "看板状态"]

PRICE_CHART = {
    "图表编号": "CHAR-PRICE",
    "图表名称": "售价图",
    "图表类型": "售价图",
    "数据来源": "售价明细库",
    "坐标字段": "等级",
    "坐标字段类型": "数值",
    "聚合方式": "求和",
    "旧字段名": "等级档位",
}

LABEL_CHART = {
    "图表编号": "CHAR-LABEL",
    "图表名称": "标签图",
    "图表类型": "标签图",
    "数据来源": "会员标签库",
    "坐标字段": "等级",
    "坐标字段类型": "字符",
    "聚合方式": "计数",
}


def _register(client: TestClient, values: dict) -> dict:
    body = client.post("/api/chart", json={"values": values}).json()
    assert body["ok"], body
    return body["entry"]


def _reset() -> None:
    store.reset()
    chart_fields.reset_runtime_state()


class FieldDictionaryTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset()
        self.client = TestClient(app)
        self.price = _register(self.client, PRICE_CHART)
        self.label = _register(self.client, LABEL_CHART)

    def test_seed_chart_keeps_original_keys_and_order(self) -> None:
        entry = self.client.get("/api/chart/1").json()
        self.assertEqual(list(entry.keys()), ["id", "status", "pending", "abnormal"] + CHART_LIST_FIELDS)

    def test_chart_and_dashboard_export_shape_unchanged(self) -> None:
        chart = self.client.get("/api/chart/export").json()
        self.assertEqual(set(chart.keys()), {"module", "total", "items"})
        self.assertEqual(chart["module"], "chart")
        dashboard = self.client.get("/api/dashboard/export").json()
        self.assertEqual(set(dashboard.keys()), {"module", "total", "items"})
        self.assertEqual(dashboard["module"], "dashboard")

    def test_registration_without_metadata_keeps_old_output(self) -> None:
        body = self.client.post("/api/chart", json={"values": {
            "图表编号": "CHAR-BARE", "图表名称": "裸登记", "图表类型": "售价图",
        }}).json()
        self.assertTrue(body["ok"])
        self.assertNotIn("坐标字段", body["entry"])

    def test_same_display_name_keeps_distinct_sources(self) -> None:
        items = self.client.get("/api/chart/fields", params={"keyword": "等级"}).json()["items"]
        identity = {(item["来源"], item["图表编号"], item["字段名"]) for item in items}
        self.assertIn(("售价明细库", "CHAR-PRICE", "等级"), identity)
        self.assertIn(("会员标签库", "CHAR-LABEL", "等级"), identity)
        self.assertEqual(len(identity), 2)

    def test_numeric_level_sumable_text_level_not(self) -> None:
        items = self.client.get("/api/chart/fields", params={"keyword": "等级"}).json()["items"]
        by_chart = {item["图表编号"]: item for item in items}
        self.assertEqual(by_chart["CHAR-PRICE"]["类型"], "数值")
        self.assertTrue(by_chart["CHAR-PRICE"]["可求和"])
        self.assertEqual(by_chart["CHAR-LABEL"]["类型"], "字符")
        self.assertFalse(by_chart["CHAR-LABEL"]["可求和"])
        self.assertFalse(by_chart["CHAR-LABEL"]["可聚合"])

    def test_corrected_field_name_is_alias(self) -> None:
        items = self.client.get("/api/chart/fields", params={"keyword": "等级档位"}).json()["items"]
        self.assertEqual([(item["图表编号"], item["字段名"]) for item in items], [("CHAR-PRICE", "等级")])

    def test_export_columns_match_list(self) -> None:
        listed = self.client.get("/api/chart/fields", params={"page": 1, "size": 200}).json()["items"]
        exported = self.client.get("/api/chart/fields/export").json()["items"]
        self.assertEqual(listed, exported)
        if listed:
            self.assertEqual(
                list(listed[0].keys()),
                ["来源", "字段名", "别名", "类型", "可聚合", "可求和", "可运算", "图表编号", "图表名称", "图表类型", "聚合方式"],
            )


class DashboardBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset()
        self.client = TestClient(app)
        _register(self.client, PRICE_CHART)
        _register(self.client, LABEL_CHART)
        dashboard = self.client.post("/api/dashboard", json={"values": {
            "看板编号": "DASH-TEST",
            "看板名称": "售价标签看板",
            "包含图表": "CHAR-PRICE,CHAR-LABEL",
        }}).json()["entry"]
        self.dashboard_id = dashboard["id"]

    def test_legacy_axis_name_and_type(self) -> None:
        payload = self.client.get(f"/api/dashboard/{self.dashboard_id}/axis-bindings", params={}).json()
        self.assertEqual(payload["items"], [])

        # 旧坐标写的是更正前的字段名，历史看板不要求改配置。
        entry = store.find("dashboard", self.dashboard_id)
        entry["坐标绑定"] = ["等级档位", {"字段名": "等级", "图表编号": "CHAR-LABEL"}, "会员层级"]
        payload = self.client.get(f"/api/dashboard/{self.dashboard_id}/axis-bindings").json()
        pairs = {(item["来源"], item["横轴"], item["字段名"], item["类型"]) for item in payload["items"]}
        self.assertIn(("售价明细库", "等级档位", "等级", "数值"), pairs)
        self.assertIn(("会员标签库", "等级", "等级", "字符"), pairs)

    def test_unbound_unknown_name(self) -> None:
        entry = store.find("dashboard", self.dashboard_id)
        entry["坐标绑定"] = ["会员层级"]
        payload = self.client.get(f"/api/dashboard/{self.dashboard_id}/axis-bindings").json()
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["未绑定项"][0]["未绑定原因"], chart_fields.UNBOUND_UNKNOWN)
        self.assertEqual(payload["待复核项"], [])

    def test_name_collision_creates_review_item(self) -> None:
        entry = store.find("dashboard", self.dashboard_id)
        entry["坐标绑定"] = ["等级", {"字段名": "等级", "图表编号": "CHAR-LABEL"}]
        payload = self.client.get(f"/api/dashboard/{self.dashboard_id}/axis-bindings").json()
        reasons = {item["横轴"]: item["未绑定原因"] for item in payload["未绑定项"]}
        self.assertEqual(reasons["等级"], chart_fields.UNBOUND_COLLISION)
        review = payload["待复核项"][0]
        self.assertEqual(review["字段名"], "等级")
        self.assertEqual(review["字段类型"], ["字符", "数值"])
        self.assertEqual({item["图表编号"] for item in review["候选来源"]}, {"CHAR-PRICE", "CHAR-LABEL"})

    def test_concurrent_confirm_records_once(self) -> None:
        entry = store.find("dashboard", self.dashboard_id)
        entry["坐标绑定"] = ["等级档位", {"字段名": "等级", "图表编号": "CHAR-LABEL"}]
        results: list[dict] = []
        threads = [
            threading.Thread(target=lambda: results.append(
                chart_fields.confirm_axis_bindings(entry, {"坐标绑定": list(entry["坐标绑定"])})
            ))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        confirmed = self.client.get(f"/api/dashboard/{self.dashboard_id}/axis-bindings/confirmed").json()
        keys = [(item["来源"], item["图表编号"], item["字段名"]) for item in confirmed["items"]]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(sorted(result["新增确认"] for result in results), [0, 2])

    def test_extract_binding_target_shared(self) -> None:
        target = chart_fields.extract_binding_target({"字段名": "等级", "图表编号": "CHAR-LABEL"})
        self.assertEqual(target["图表编号"], "CHAR-LABEL")
        self.assertEqual(target["字段名"], "等级")
        self.assertEqual(chart_fields.extract_binding_target("等级")["字段名"], "等级")
        self.assertEqual(chart_fields.extract_binding_target("等级")["图表编号"], "")


if __name__ == "__main__":
    unittest.main()
