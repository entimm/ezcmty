import { createClaim } from '../../core/api';
import { newKey } from '../../core/ids';
import { isUnknownResult, StaleSessionError } from '../../core/request';
import { onSessionReset } from '../../core/session';
import { Claim, ClaimInput } from '../../core/types';

/** A claim draft never leaves memory; an uncertain write can only replay its original input. */
export class ClaimSubmission {
  private operation: { data: ClaimInput; key: string } | null = null;
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

  submit(input: ClaimInput): Promise<Claim> {
    const data = {
      house_id: input.house_id,
      applicant_name: input.applicant_name.trim(),
      phone_binding_id: input.phone_binding_id,
      applicant_remark: input.applicant_remark?.trim() || null,
    };
    if (!data.applicant_name || data.applicant_name.length > 80)
      return Promise.reject(new Error('请填写 1 至 80 字的姓名'));
    if (!data.house_id || !data.phone_binding_id)
      return Promise.reject(new Error('请选择房屋和已验证手机号'));
    if ((data.applicant_remark?.length || 0) > 1000)
      return Promise.reject(new Error('备注请控制在 1000 字以内'));
    if (
      this.operation &&
      JSON.stringify(this.operation.data) !== JSON.stringify(data)
    ) {
      if (this.uncertain || this.active)
        return Promise.reject(
          new Error('原申请结果尚未确认，请先恢复原提交结果'),
        );
      this.operation = null;
    }
    if (!this.operation) this.operation = { data, key: newKey() };
    return this.retry();
  }

  async retry(): Promise<Claim> {
    if (this.active) throw new Error('正在提交，请稍候');
    if (!this.operation) throw new Error('请先填写认领资料');
    const operation = this.operation;
    const epoch = this.epoch;
    this.active = true;
    try {
      const result = await createClaim(operation.data, operation.key);
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
