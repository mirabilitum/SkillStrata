"""冒烟测试：确认包可导入、测试管线通。

工程纪律（grill 提醒）：每个里程碑的代码都连带测试一起交，不后补。
"""

import distiller


def test_package_importable():
    assert distiller.__version__ == "0.0.1"
