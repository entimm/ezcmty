import { describe, expect, it, vi } from 'vitest';
import { propertyPaymentReads } from '../../src/features/property/payments/api';
import { platformPaymentWrites } from '../../src/features/platform/payments/api';
import type { AdminRequest, RequestOptions } from '../../src/shared/request';
function transport() {
  return vi
    .fn<(path: string, options?: RequestOptions) => Promise<unknown>>()
    .mockResolvedValue({});
}
describe('双后台资金能力边界', () => {
  it('物业API只提供读取且阻止公司筛选进入本端查询', async () => {
    const request = transport();
    const api = propertyPaymentReads(request as AdminRequest);
    expect(
      Object.keys(api).some((key) =>
        /recover|activate|create|external|recheck/i.test(key),
      ),
    ).toBe(false);
    await api.orders({
      property_company_id: 'other-company',
      community_id: 'current-community',
      page: 1,
    });
    const url = new URL(request.mock.calls[0][0], 'https://property.test');
    expect(url.searchParams.has('property_company_id')).toBe(false);
    expect(url.searchParams.get('community_id')).toBe('current-community');
  });
  it('平台配置创建带固定幂等键和原配置令牌', async () => {
    const request = transport();
    const api = platformPaymentWrites(request as AdminRequest);
    await api.createBinding(
      'company',
      {
        merchant_name: '实际物业公司',
        merchant_no: '1900009239',
        expected_configuration_token: 'original-config-token',
      },
      'binding-key',
    );
    const options = request.mock.calls[0][1];
    expect(new Headers(options?.headers).get('Idempotency-Key')).toBe(
      'binding-key',
    );
    expect(JSON.parse(String(options?.body)).expected_configuration_token).toBe(
      'original-config-token',
    );
  });
  it('外部处置携带原差异令牌及依据，不能指定资金成功', async () => {
    const request = transport();
    const api = platformPaymentWrites(request as AdminRequest);
    await api.externalResolution('difference', {
      reason: '已核实银行结论',
      evidence_reference: '工单 A-123',
      expected_state_token: 'original-state-token',
    });
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe(
      '/v1/payment-reconciliation-discrepancies/difference/external-resolutions',
    );
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
      reason: '已核实银行结论',
      evidence_reference: '工单 A-123',
      expected_state_token: 'original-state-token',
    });
  });
});
