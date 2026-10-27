import { bindPhone } from './account-api';
import { normalizePhone } from './format';
import { newKey } from './ids';
import { isUnknownResult, StaleSessionError } from './request';
import { onSessionReset } from './session';
import { PhoneBinding } from './types';

/** WeChat codes are retained only in this page-lifetime object and are never persisted. */
export class PhoneVerification {
  private operation: { code: string; key: string; expected?: string } | null =
    null;
  private epoch = 0;
  private active = false;
  private uncertain = false;
  private off = onSessionReset(() => this.reset());
  get unknown(): boolean {
    return this.uncertain;
  }
  get busy(): boolean {
    return this.active;
  }

  authorize(code: string, expectedPhone?: string): Promise<PhoneBinding> {
    if (this.active || this.uncertain)
      return Promise.reject(new Error('请先恢复原手机号验证结果'));
    if (!code) return Promise.reject(new Error('请先完成微信手机号授权'));
    const expected = expectedPhone?.trim()
      ? normalizePhone(expectedPhone)
      : undefined;
    if (expected === null)
      return Promise.reject(new Error('请填写有效的中国大陆手机号'));
    this.operation = { code, key: newKey(), expected };
    return this.retry();
  }
  async retry(): Promise<PhoneBinding> {
    if (this.active) throw new Error('正在验证，请稍候');
    if (!this.operation) throw new Error('请重新进行微信手机号授权');
    const operation = this.operation;
    const epoch = this.epoch;
    this.active = true;
    try {
      const result = await bindPhone(
        operation.code,
        operation.key,
        operation.expected,
      );
      if (epoch !== this.epoch) throw new StaleSessionError();
      this.operation = null;
      this.uncertain = false;
      return result;
    } catch (error) {
      if (epoch !== this.epoch) throw new StaleSessionError();
      this.uncertain = isUnknownResult(error);
      if (!this.uncertain) this.operation = null;
      throw error;
    } finally {
      if (epoch === this.epoch) this.active = false;
    }
  }
  reset(): void {
    this.epoch++;
    this.operation = null;
    this.active = false;
    this.uncertain = false;
  }
  dispose(): void {
    this.reset();
    this.off();
  }
}
