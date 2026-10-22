from dataclasses import dataclass

from backend_app.domain.admin.types import AdminScope


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    name: str
    group: str
    assignable: bool


def permission_catalog(scope: AdminScope) -> list[PermissionDefinition]:
    imports = [
        PermissionDefinition(
            code=f"{'platform' if scope == 'platform_admin' else 'property'}.import.{code}",
            name=name,
            group="批量导入",
            assignable=True,
        )
        for code, name in (
            ("read", "查看导入"),
            ("create", "新建导入"),
            ("upload", "上传导入文件"),
            ("precheck", "预检导入"),
            ("execute", "执行导入"),
            ("cancel", "取消导入"),
            ("retry", "重跑失败行"),
            ("recover", "恢复原任务"),
            ("generate_error_file", "生成错误文件"),
            ("download", "下载错误文件"),
        )
    ]
    if scope == "property_admin":
        return imports + [
            PermissionDefinition(code=c, name=n, group=g, assignable=True)
            for c, n, g in (
                ("property.company.read", "查看本公司资料", "物业公司"),
                ("property.payment_config.read", "查看收款配置", "支付"),
                ("property.payment.read", "查看支付记录", "支付"),
                ("property.payment_funds.read", "查看资金处理", "支付"),
                ("property.payment_reconciliation.read", "查看本公司核对结果", "支付"),
                ("property.house_claim.read", "查看房屋认领申请", "房屋认领"),
                ("property.house_claim.review", "审核房屋认领申请", "房屋认领"),
                ("property.resident_house_binding.read", "查看居民房屋授权", "居民房屋"),
                ("property.resident_house_binding.revoke", "撤销居民房屋授权", "居民房屋"),
                ("property.fee_basis.read", "查看物业费计费依据及试算", "计费依据"),
                ("property.fee_basis.create", "新增计费依据版本", "计费依据"),
                ("property.bill.read", "查看账单及收款历史", "账单"),
                ("property.bill.create", "建立账单", "账单"),
                ("property.bill.update", "修改账单资料", "账单"),
                ("property.bill.void", "作废账单", "账单"),
                ("property.bill_receipt.create", "登记线下收款", "收款"),
                ("property.bill_receipt.correct", "纠正及撤销收款登记", "收款"),
                ("property.community.read", "查看本公司小区", "小区"),
                ("property.space.read", "查看空间节点", "空间管理"),
                ("property.space.create", "创建空间节点", "空间管理"),
                ("property.space.update", "编辑及启停空间节点", "空间管理"),
                ("property.house.read", "查看房屋", "房屋管理"),
                ("property.house.create", "创建房屋", "房屋管理"),
                ("property.house.update", "编辑及启停房屋", "房屋管理"),
                ("property.house_owner.read", "查看房屋业主", "业主资料"),
                ("property.house_owner.create", "登记房屋业主", "业主资料"),
                ("property.house_owner.update", "编辑及启停房屋业主", "业主资料"),
            )
        ]
    definitions = [
        ("platform.payment_config.read", "查看收款配置", "支付", True),
        ("platform.payment_config.manage", "维护收款配置", "支付", True),
        ("platform.payment.read", "查看支付记录", "支付", True),
        ("platform.payment_funds.read", "查看资金处理", "支付", True),
        ("platform.payment_funds.recover", "恢复资金处理", "支付", True),
        ("platform.payment_reconciliation.read", "查看资金核对", "支付", True),
        ("platform.payment_reconciliation.recheck", "重新核对资金", "支付", True),
        ("admin.account.read", "查看管理员", "管理员", True),
        ("admin.account.create", "创建管理员", "管理员", False),
        ("admin.account.update", "编辑及启停管理员", "管理员", False),
        ("admin.account.reset_password", "重置管理员密码", "管理员", False),
        ("admin.account.assign_roles", "分配管理员角色", "管理员", False),
        ("admin.role.read", "查看角色与权限目录", "角色", True),
        ("admin.role.create", "创建角色", "角色", False),
        ("admin.role.update", "编辑及启停角色", "角色", False),
        ("admin.role.assign_permissions", "配置角色权限", "角色", False),
        ("admin.audit.read", "查看审计日志", "审计", True),
        ("property.company.read", "查看物业公司", "物业公司", True),
        ("property.company.create", "创建物业公司", "物业公司", True),
        ("property.company.update", "编辑及启停物业公司", "物业公司", True),
        ("property.community.read", "查看小区", "小区", True),
        ("property.community.create", "创建小区", "小区", True),
        ("property.community.update", "编辑及启停小区", "小区", True),
        ("property.admin.read", "查看公司管理员", "公司管理员", True),
        ("property.admin.create", "开通公司管理员", "公司管理员", False),
        ("property.admin.update", "编辑及启停公司管理员", "公司管理员", False),
        ("property.admin.reset_password", "重置公司管理员密码", "公司管理员", False),
    ]
    return imports + [
        PermissionDefinition(code=c, name=n, group=g, assignable=a) for c, n, g, a in definitions
    ]
