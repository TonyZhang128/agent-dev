"""表头标签与版面生成共用的坐标规则。"""


def r3(value: float) -> float:
    return round(value, 3)


# 第二册 JB12 抽检记录表:标签 → 字段 + 填写区域(x 固定列取表格版式)
JB = [
    (r"^监\s*理\s*单\s*位", "fld_supervisor", lambda x, y: [0.24, y, 0.42, 0.022], None),
    (r"^施\s*工\s*单\s*位", "fld_contractor", lambda x, y: [0.23, y, 0.42, 0.024], None),
    (r"^合\s*同\s*段", "fld_contract_sec", lambda x, y: [0.74, y, 0.18, 0.024], None),
    (r"^抽\s*检\s*人", "fld_sampler", lambda x, y: [0.23, y, 0.36, 0.024], "APPROVAL_OUTPUT"),
    (r"^(抽检|检查)时间", "fld_sample_date", lambda x, y: [0.735, y, 0.1, 0.024], None),
    (r"^工\s*程\s*部\s*位", "fld_location", lambda x, y: [0.23, y, 0.36, 0.025], None),
    (r"^检\s*查\s*结\s*论", "fld_conclusion", lambda x, y: [0.23, y - 0.006, 0.69, 0.032], None),
    (r"^处\s*理\s*意\s*见", "fld_sv_opinion", lambda x, y: [0.23, y - 0.006, 0.69, 0.032], None),
    (r"^审\s*核\s*人", "fld_reviewer", lambda x, y: [0.23, y, 0.36, 0.024], "APPROVAL_OUTPUT"),
    (
        r"^审\s*核\s*日\s*期",
        "fld_review_date",
        lambda x, y: [0.70, y, 0.2, 0.024],
        "APPROVAL_OUTPUT",
    ),
]


# 第一册:标签 → 字段;nth = 同名标签取第几个(标段:施工 / 监理)
B1 = [
    (
        r"公路工程项目$",
        "fld_project",
        lambda t: [r3(max(0.1, t["x"] - 0.26)), r3(t["y"] - 0.004), 0.25, 0.022],
        None,
        None,
    ),
    (
        r"^施\s*工\s*单\s*位",
        "fld_contractor",
        lambda t: [r3(t["x"] + 0.085), t["y"], 0.4, 0.02],
        None,
        None,
    ),
    (
        r"^监\s*理\s*单\s*位",
        "fld_supervisor",
        lambda t: [r3(t["x"] + 0.085), t["y"], 0.4, 0.02],
        None,
        None,
    ),
    (r"^标\s*段", "fld_contract_sec", lambda t: [r3(t["x"] + 0.045), t["y"], 0.12, 0.02], None, 0),
    (r"^标\s*段", "fld_sv_sec", lambda t: [r3(t["x"] + 0.045), t["y"], 0.12, 0.02], None, 1),
    (
        r"工程名称$|^工\s*程\s*名\s*称",
        "fld_item_name",
        lambda t: [r3(t["x"] + min(0.2, t["w"] + 0.01)), t["y"], 0.25, 0.022],
        None,
        None,
    ),
    (
        r"^(桩号及|工程)?部\s*位|^桩号及工程部位|^施工桩号|^检查桩号范围",
        "fld_location",
        lambda t: [r3(t["x"] + min(0.16, t["w"] + 0.01)), t["y"], 0.24, 0.022],
        None,
        None,
    ),
    (
        r"^(检测|检查|施工|检验|试验|抽检|记录)日期|^日\s*期$",
        "fld_check_date",
        lambda t: [r3(t["x"] + min(0.1, t["w"] + 0.01)), t["y"], 0.14, 0.022],
        None,
        None,
    ),
    (
        r"^计划开(工)?日期",
        "fld_plan_start",
        lambda t: [r3(t["x"] + 0.12), t["y"], 0.2, 0.022],
        None,
        None,
    ),
    (
        r"^计划(完工|完成)日期",
        "fld_plan_end",
        lambda t: [r3(t["x"] + 0.12), t["y"], 0.2, 0.022],
        None,
        None,
    ),
    (
        r"^(检查|检验|自检)结果|^检查结论|^评定(意见|结论)",
        "fld_result",
        lambda t: [r3(t["x"] + min(0.12, t["w"] + 0.01)), r3(t["y"] - 0.004), 0.5, 0.03],
        "CALCULATED",
        None,
    ),
    (
        r"监理员意见",
        "fld_sv_member",
        lambda t: [r3(t["x"] + 0.02), r3(t["y"] + 0.02), 0.7, 0.07],
        None,
        None,
    ),
    (
        r"专业监理工程师(意见|音见)|驻地监理工程师意见",
        "fld_sv_check",
        lambda t: [r3(t["x"] + 0.02), r3(t["y"] + 0.02), 0.7, 0.06],
        None,
        None,
    ),
    (
        r"总监理工程师(意见|审批意见)",
        "fld_chief_opinion",
        lambda t: [r3(t["x"] + 0.02), r3(t["y"] + 0.02), 0.7, 0.05],
        "APPROVAL_OUTPUT",
        None,
    ),
]
