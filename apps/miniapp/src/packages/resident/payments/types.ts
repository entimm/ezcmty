export interface PaymentInput {
  items: [{ bill_id: string; expected_row_version: number }];
}
export interface PaymentOrder {
  id: string;
  order_no: string;
  merchant_name: string;
  amount_cents: number;
  payer_total_cents: number | null;
  status:
    'pending' | 'unknown' | 'payable' | 'closing' | 'succeeded' | 'closed';
  confirmation_status: 'unconfirmed' | 'awaiting_posting' | 'posted';
  available_actions: ('continue_payment' | 'refresh' | 'close')[];
  items: {
    id: string;
    bill_id: string;
    bill_type: 'property_fee';
    billing_month: string;
    house_label_snapshot: string;
    amount_cents: number;
  }[];
  expires_at: string;
  paid_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface ClientParameters {
  payment_order_id: string;
  channel: 'wechat_pay';
  client_parameters: {
    timeStamp: string;
    nonceStr: string;
    package: string;
    signType: 'RSA';
    paySign: string;
  };
}
