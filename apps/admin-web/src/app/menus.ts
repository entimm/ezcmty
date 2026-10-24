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
}
export interface MenuGroup {
  label: string;
  items: MenuItem[];
}
const item = (page: string, label: string, icon: ComponentType): MenuItem => ({
  page,
  label,
  icon,
});
export const menus: Record<Scope, MenuGroup[]> = {
  property: [
    { label: '日常工作', items: [item('home', '工作台', AppstoreOutlined)] },
    {
      label: '收费管理',
      items: [
        item('bills', '物业费账单', FileTextOutlined),
        item('payments', '线上收款', WalletOutlined),
        item('reconciliation', '核对结果', FileSearchOutlined),
      ],
    },
    {
      label: '房屋与住户',
      items: [
        item('houses', '房屋管理', HomeOutlined),
        item('claims', '房屋认领审核', CheckSquareOutlined),
        item('bindings', '居民房屋绑定', TeamOutlined),
      ],
    },
    {
      label: '资料与工具',
      items: [
        item('imports', '导入中心', ImportOutlined),
        item('communities', '小区资料', ApartmentOutlined),
        item('payment-configuration', '收款信息', SettingOutlined),
      ],
    },
  ],
  platform: [
    { label: '日常工作', items: [item('home', '工作台', AppstoreOutlined)] },
    {
      label: '物业接入',
      items: [
        item('companies', '物业公司', BankOutlined),
        item('platform-communities', '小区管理', ApartmentOutlined),
      ],
    },
    {
      label: '支付与资金',
      items: [
        item('payments', '支付记录', WalletOutlined),
        item('reconciliation', '资金核对', FileSearchOutlined),
      ],
    },
    {
      label: '系统管理',
      items: [
        item('accounts', '管理员', UserOutlined),
        item('roles', '角色与权限', SafetyCertificateOutlined),
        item('audit', '审计日志', AuditOutlined),
      ],
    },
    {
      label: '资料与工具',
      items: [item('imports', '导入历史', ImportOutlined)],
    },
  ],
};
