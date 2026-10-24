import {
  AppstoreOutlined,
  WalletOutlined,
  HomeOutlined,
  TeamOutlined,
  CheckSquareOutlined,
  FileTextOutlined,
  ImportOutlined,
  SettingOutlined,
  FileSearchOutlined,
  BankOutlined,
  SafetyCertificateOutlined,
  AuditOutlined,
  ApartmentOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ComponentType } from 'react';
import type { Scope } from '../shared/types';
export interface MenuItem {
  page: string;
  label: string;
  icon: ComponentType;
  aliases?: string[];
}
export interface MenuGroup {
  label: string;
  items: MenuItem[];
}
const item = (
  page: string,
  label: string,
  icon: ComponentType,
  aliases: string[] = [],
): MenuItem => ({
  page,
  label,
  icon,
  aliases,
});
export function matchesMenuSearch(item: MenuItem, query: string) {
  const term = query.trim().toLowerCase();
  return [item.label, item.page, ...(item.aliases || [])].some((value) =>
    value.toLowerCase().includes(term),
  );
}
export const menus: Record<Scope, MenuGroup[]> = {
  property: [
    {
      label: '日常工作',
      items: [item('home', '工作概览', AppstoreOutlined, ['工作台'])],
    },
    {
      label: '收费管理',
      items: [
        item('bills', '物业账单', FileTextOutlined, ['物业费账单']),
        item('payments', '线上收款', WalletOutlined),
        item('reconciliation', '对账结果', FileSearchOutlined, ['核对结果']),
      ],
    },
    {
      label: '房屋住户',
      items: [
        item('houses', '房屋档案', HomeOutlined, ['房屋管理']),
        item('claims', '认领审核', CheckSquareOutlined, ['房屋认领审核']),
        item('bindings', '房屋绑定', TeamOutlined, ['居民房屋绑定']),
      ],
    },
    {
      label: '资料工具',
      items: [
        item('imports', '导入中心', ImportOutlined),
        item('communities', '小区资料', ApartmentOutlined),
        item('payment-configuration', '收款信息', SettingOutlined),
      ],
    },
  ],
  platform: [
    {
      label: '日常工作',
      items: [item('home', '工作概览', AppstoreOutlined, ['工作台'])],
    },
    {
      label: '物业接入',
      items: [
        item('companies', '物业公司', BankOutlined),
        item('platform-communities', '小区管理', ApartmentOutlined),
      ],
    },
    {
      label: '支付资金',
      items: [
        item('payments', '支付记录', WalletOutlined),
        item('reconciliation', '资金对账', FileSearchOutlined, ['资金核对']),
      ],
    },
    {
      label: '系统管理',
      items: [
        item('accounts', '账号管理', UserOutlined, ['管理员', '平台管理员']),
        item('roles', '角色权限', SafetyCertificateOutlined, ['角色与权限']),
        item('audit', '操作日志', AuditOutlined, ['审计日志']),
      ],
    },
    {
      label: '资料工具',
      items: [item('imports', '导入中心', ImportOutlined)],
    },
  ],
};
