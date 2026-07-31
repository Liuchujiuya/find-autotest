def test_project_smoke(login_info):
    """最小冒烟用例：确认测试配置可以被 pytest fixture 正常读取。"""
    assert isinstance(login_info, dict)  # login_info 应该是字典，说明 YAML 读取和 fixture 注入正常。
