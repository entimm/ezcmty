import { beforeEach, expect, it, vi } from 'vitest';
import type {
  ClaimInput,
  Community,
  House,
  SpaceNode,
} from '../src/packages/resident/types';
const api = vi.hoisted(() => ({
  createClaim: vi.fn(),
  communities: vi.fn(),
  nodes: vi.fn(),
  houses: vi.fn(),
  house: vi.fn(),
}));
vi.mock('../src/packages/resident/api', () => api);
const auth = vi.hoisted(() => ({ listPhones: vi.fn(), reset: () => {} }));
vi.mock('../src/auth/resident', () => ({
  requireSession: () => true,
  onSessionReset: (callback: () => void) => {
    auth.reset = callback;
    return () => {};
  },
  listPhones: auth.listPhones,
}));

interface ClaimPage {
  data: {
    step: number;
    busy: boolean;
    unknown: boolean;
    error: string;
    house: House | null;
    name: string;
    remark: string;
    phoneId: string;
    community: Community | null;
    trail: SpaceNode[];
    nodes: SpaceNode[];
    houses: House[];
    choicePage: number;
    phones: { id: string }[];
  };
  operation?: { data: ClaimInput; key: string };
  setData: (values: object) => void;
  submit: () => Promise<void>;
  onLoad: (options: Record<string, string>) => void;
  loadPhones: () => Promise<void>;
  loadChoices: (more?: boolean) => Promise<void>;
}
let page: ClaimPage;
beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal('wx', { redirectTo: vi.fn(), pageScrollTo: vi.fn() });
  vi.stubGlobal('Page', (definition: ClaimPage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (values: object) => Object.assign(page.data, values);
  });
  await import('../src/packages/resident/pages/claim/index');
});
it('reuses exactly the same submission key and normalized input after an unknown outcome', async () => {
  const { ApiError } = await import('../src/shared/http/client');
  page.data.house = {
    id: 'house',
    community_id: 'community',
    space_node_id: 'building',
    room_no: '101',
    display_address: '悦景一栋101',
  };
  Object.assign(page.data, {
    name: ' 张三 ',
    remark: ' ',
    phoneId: 'phone',
    step: 3,
  });
  api.createClaim
    .mockRejectedValueOnce(new ApiError(0, 'network', '网络错误'))
    .mockResolvedValueOnce({ id: 'application' });
  await page.submit();
  expect(page.data.unknown).toBe(true);
  const first = api.createClaim.mock.calls[0];
  await page.submit();
  expect(api.createClaim.mock.calls[1]).toEqual(first);
  expect(first[0]).toEqual({
    house_id: 'house',
    applicant_name: '张三',
    phone_binding_id: 'phone',
    applicant_remark: null,
  });
  expect(page.data.name).toBe('');
  expect(page.operation).toBeUndefined();
});
it('presents building direct houses alongside its units', async () => {
  Object.assign(page.data, {
    community: { id: 'community' },
    trail: [{ id: 'building', node_type: 'building' }],
  });
  api.nodes.mockResolvedValue({ items: [{ id: 'unit' }], total: 1 });
  api.houses.mockResolvedValue({ items: [{ id: 'direct-house' }], total: 1 });
  await page.loadChoices();
  expect(page.data.nodes).toEqual([{ id: 'unit' }]);
  expect(page.data.houses).toEqual([{ id: 'direct-house' }]);
  expect(api.houses).toHaveBeenCalledWith('community', 'building', '', 1);
});

it('discards a partially accumulated phone list after account reset', async () => {
  page.onLoad({});
  const phone = {
    id: 'old-phone',
    phone: '13800138000',
    status: 'active',
    last_verified_at: '2026-01-01T00:00:00Z',
  };
  let entered!: () => void;
  const secondEntered = new Promise<void>((resolve) => {
    entered = resolve;
  });
  let finish!: (result: object) => void;
  auth.listPhones
    .mockResolvedValueOnce({ items: [phone], total: 101, page_size: 100 })
    .mockImplementationOnce(() => {
      entered();
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
  const loading = page.loadPhones();
  await secondEntered;
  auth.reset();
  finish({ items: [], total: 101, page_size: 100 });
  await loading;
  expect(page.data.phones).toEqual([]);
});
