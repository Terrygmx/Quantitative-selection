from tail_momentum_selector import build_report


def report_record(name="中国巨石", code="sh600176", total=82.0):
    return {
        "code": code,
        "name": name,
        "day_chg_pct": 3.97,
        "morn_ret": 0.001,
        "atr": 2.0,
        "score": {
            "total": total,
            "afternoon": 17.0,
            "volume": 20.0,
            "rs": 15.0,
            "risk": 8.0,
            "snapshot_close": 47.09,
            "aft_det": {
                "aft_1400": 0.006,
                "aft_vs_morn": 0.023,
                "break_high": True,
                "vol_pace_ratio": 1.3,
            },
            "vol_det": {"vol_surge": 1.5},
            "rs_det": {
                "rs_hs300": 0.04,
                "rs_zz1000": 0.04,
                "rs_industry": 0.03,
                "industry_available": True,
            },
            "risk_det": {"amount_yi": 253.9, "near_limitup": False, "recent_up_streak": 1},
        },
        "miss": [],
    }


def test_report_contains_candidate_watch_and_risk_sections():
    candidate = report_record()
    watch = report_record(name="观察股", code="sz000858", total=65)
    watch["miss"] = ["总分65.0<80"]

    report = build_report(
        [candidate], [watch], "Bear", 4,
        {"idx_avg_chg": -0.62, "breadth_ratio": 20.4, "limitup": 32, "limitdown": 34},
        "1430", 5, 80,
    )

    assert "市场状态：Bear" in report
    assert "中国巨石 (sh600176)" in report
    assert "观察股 (sz000858)" in report
    assert "未入选原因：总分65.0<80" in report
    assert "T+1" in report
    assert "不构成任何投资建议" in report
    assert "生成时间:" in report
