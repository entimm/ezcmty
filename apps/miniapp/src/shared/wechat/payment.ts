export type PanelResult = 'success' | 'cancelled' | 'unknown';
export function requestPayment(parameters: {
  timeStamp: string;
  nonceStr: string;
  package: string;
  signType: 'RSA';
  paySign: string;
}): Promise<PanelResult> {
  return new Promise((resolve) =>
    wx.requestPayment({
      ...parameters,
      success: () => resolve('success'),
      fail: (error) =>
        resolve(error.errMsg.includes('cancel') ? 'cancelled' : 'unknown'),
    }),
  );
}
