import { expectTypeOf, it } from 'vitest';
import type { components } from '../../../../openapi/types';

type Schemas = components['schemas'];

it('preserves encrypted resource fields together with each notification refinement', () => {
  type Payment = Schemas['WechatPayPaymentSuccessNotification']['resource'];
  type Sharing = Schemas['WechatPayProfitSharingNotification']['resource'];
  expectTypeOf<Payment['original_type']>().toEqualTypeOf<'transaction'>();
  expectTypeOf<Sharing['original_type']>().toEqualTypeOf<'profitsharing'>();
  expectTypeOf<
    Pick<Payment, 'ciphertext' | 'nonce' | 'algorithm'>
  >().toEqualTypeOf<{
    ciphertext: string;
    nonce: string;
    algorithm: 'AEAD_AES_256_GCM';
  }>();
  expectTypeOf<Sharing['associated_data']>().toEqualTypeOf<
    string | undefined
  >();
});

it('keeps request defaults optional and the profit-sharing receiver count fixed', () => {
  expectTypeOf<Schemas['AccountCreate']['role_ids']>().toEqualTypeOf<
    string[] | undefined
  >();
  expectTypeOf<
    Schemas['ProfitSharingRuleCreate']['items']['length']
  >().toEqualTypeOf<1>();
});
